from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from .errors import RateLimitError

RateLimitPolicy = Literal["raise", "sleep", "off"]


@dataclass(frozen=True, slots=True)
class RateLimitState:
    limit_per_hour: int
    used: int
    remaining: int
    reset_at: datetime | None
    retry_after_s: float


class TokenBucket:
    def __init__(
        self,
        limit_per_hour: int,
        policy: RateLimitPolicy = "raise",
        bucket_file: Path | str | None = None,
    ):
        if limit_per_hour < 1:
            raise ValueError("rate_limit_per_hour must be >= 1")
        if policy not in {"raise", "sleep", "off"}:
            raise ValueError("rate_limit_policy must be 'raise', 'sleep', or 'off'")

        self.limit_per_hour = limit_per_hour
        self.policy = policy
        self.bucket_file = Path(bucket_file) if bucket_file is not None else None
        self._timestamps: list[float] = []

    def acquire(self, *, dataset: str | None = None, path: str | None = None) -> None:
        if self.policy == "off":
            return

        while True:
            retry_after = self._try_acquire_once()
            if retry_after is None:
                return
            if self.policy == "raise":
                raise RateLimitError(
                    retry_after,
                    dataset=dataset,
                    path=path,
                )
            time.sleep(retry_after)

    def state(self) -> RateLimitState:
        if self.policy == "off":
            return RateLimitState(
                limit_per_hour=self.limit_per_hour,
                used=0,
                remaining=self.limit_per_hour,
                reset_at=None,
                retry_after_s=0.0,
            )

        timestamps = self._read_timestamps() if self.bucket_file else self._timestamps
        timestamps = self._fresh(timestamps, time.time())
        used = len(timestamps)
        remaining = max(self.limit_per_hour - used, 0)
        retry_after = self._retry_after(timestamps, time.time())
        # When at least one slot has been used, expose when the oldest one
        # rolls off — useful for UI even if the bucket isn't yet exhausted.
        reset_at = (
            datetime.fromtimestamp(timestamps[0], UTC) + timedelta(hours=1)
            if timestamps
            else None
        )
        return RateLimitState(
            limit_per_hour=self.limit_per_hour,
            used=used,
            remaining=remaining,
            reset_at=reset_at,
            retry_after_s=retry_after,
        )

    def _try_acquire_once(self) -> float | None:
        if self.bucket_file is not None:
            return self._try_acquire_file()

        now = time.time()
        self._timestamps = self._fresh(self._timestamps, now)
        if len(self._timestamps) < self.limit_per_hour:
            self._timestamps.append(now)
            return None
        return self._retry_after(self._timestamps, now)

    def _try_acquire_file(self) -> float | None:
        assert self.bucket_file is not None
        self.bucket_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover — Windows / non-POSIX
            raise RuntimeError(
                "bucket_file= requires fcntl, which is POSIX-only. "
                "Multi-process rate-limit coordination is not supported on "
                "this platform; use the in-memory bucket (omit bucket_file=) "
                "or run the coordinating process on Linux/macOS."
            ) from exc

        with self.bucket_file.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                raw = handle.read().strip()
                try:
                    parsed = json.loads(raw) if raw else []
                except json.JSONDecodeError:
                    parsed = []
                timestamps = self._coerce_timestamps(parsed)
                now = time.time()
                timestamps = self._fresh(timestamps, now)

                if len(timestamps) < self.limit_per_hour:
                    timestamps.append(now)
                    self._write_locked(handle, timestamps)
                    return None

                self._write_locked(handle, timestamps)
                return self._retry_after(timestamps, now)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_timestamps(self) -> list[float]:
        if self.bucket_file is None or not self.bucket_file.exists():
            return []
        try:
            raw = self.bucket_file.read_text(encoding="utf-8").strip()
            return self._coerce_timestamps(json.loads(raw) if raw else [])
        except (OSError, json.JSONDecodeError):
            return []

    @staticmethod
    def _write_locked(handle, timestamps: list[float]) -> None:
        handle.seek(0)
        handle.truncate()
        json.dump(timestamps, handle)
        handle.flush()
        os.fsync(handle.fileno())

    @staticmethod
    def _coerce_timestamps(values: object) -> list[float]:
        if not isinstance(values, list):
            return []
        timestamps: list[float] = []
        for value in values:
            try:
                timestamps.append(float(value))
            except (TypeError, ValueError):
                continue
        return timestamps

    @staticmethod
    def _fresh(timestamps: list[float], now: float) -> list[float]:
        cutoff = now - 3600
        return [ts for ts in timestamps if ts > cutoff]

    def _retry_after(self, timestamps: list[float], now: float) -> float:
        if len(timestamps) < self.limit_per_hour:
            return 0.0
        return max(3600 - (now - min(timestamps)), 0.0)
