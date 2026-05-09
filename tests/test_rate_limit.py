from __future__ import annotations

import time

import pytest

from quiverfeed.errors import RateLimitError
from quiverfeed.rate_limit import TokenBucket


def test_invalid_limit_rejected():
    with pytest.raises(ValueError):
        TokenBucket(limit_per_hour=0)


def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        TokenBucket(limit_per_hour=10, policy="explode")  # type: ignore[arg-type]


def test_off_policy_skips_acquire():
    bucket = TokenBucket(limit_per_hour=1, policy="off")
    for _ in range(5):
        bucket.acquire()  # never raises, never blocks
    state = bucket.state()
    assert state.remaining == 1
    assert state.used == 0


def test_raise_policy_emits_rate_limit_error_when_full():
    bucket = TokenBucket(limit_per_hour=2, policy="raise")
    bucket.acquire()
    bucket.acquire()
    with pytest.raises(RateLimitError) as exc:
        bucket.acquire()
    assert exc.value.retry_after_s > 0


def test_state_tracks_remaining_in_memory():
    bucket = TokenBucket(limit_per_hour=3, policy="raise")
    bucket.acquire()
    state = bucket.state()
    assert state.limit_per_hour == 3
    assert state.used == 1
    assert state.remaining == 2
    # reset_at populated as soon as any slot is in use; this is when the
    # oldest slot rolls off the rolling 1h window.
    assert state.reset_at is not None


def test_state_reset_at_none_when_unused():
    bucket = TokenBucket(limit_per_hour=3, policy="raise")
    state = bucket.state()
    assert state.used == 0
    assert state.reset_at is None


def test_state_reports_reset_at_when_exhausted():
    bucket = TokenBucket(limit_per_hour=1, policy="raise")
    bucket.acquire()
    state = bucket.state()
    assert state.remaining == 0
    assert state.reset_at is not None


def test_sleep_policy_waits_then_acquires(monkeypatch):
    bucket = TokenBucket(limit_per_hour=1, policy="sleep")
    bucket.acquire()
    # Force the in-memory timestamp to look an hour old so retry_after is 0.
    bucket._timestamps = [time.time() - 4000]
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    bucket.acquire()
    # Either no sleep or a positive sleep value, but never an exception.
    assert all(s >= 0 for s in sleeps)


def test_file_backed_bucket_persists_across_instances(tmp_path):
    bucket_file = tmp_path / "bucket.json"
    a = TokenBucket(limit_per_hour=2, policy="raise", bucket_file=bucket_file)
    a.acquire()
    a.acquire()

    # New bucket instance reads the same file and should see it as full.
    b = TokenBucket(limit_per_hour=2, policy="raise", bucket_file=bucket_file)
    with pytest.raises(RateLimitError):
        b.acquire()


def test_file_backed_bucket_state_shows_used(tmp_path):
    bucket_file = tmp_path / "bucket.json"
    a = TokenBucket(limit_per_hour=5, policy="raise", bucket_file=bucket_file)
    a.acquire()
    a.acquire()

    b = TokenBucket(limit_per_hour=5, policy="raise", bucket_file=bucket_file)
    state = b.state()
    assert state.used == 2
    assert state.remaining == 3


def test_file_backed_bucket_handles_corrupt_file(tmp_path):
    bucket_file = tmp_path / "bucket.json"
    bucket_file.write_text("not-json", encoding="utf-8")
    bucket = TokenBucket(limit_per_hour=1, policy="raise", bucket_file=bucket_file)
    # Corrupt content should be treated as empty rather than crashing.
    bucket.acquire()


def test_fresh_drops_old_timestamps():
    bucket = TokenBucket(limit_per_hour=2, policy="raise")
    now = time.time()
    bucket._timestamps = [now - 4000, now - 10]
    bucket.acquire()
    # Old ts dropped, new ts appended; should still have 2 fresh entries.
    assert len(bucket._timestamps) == 2
