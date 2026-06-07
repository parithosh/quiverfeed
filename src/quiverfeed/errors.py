from __future__ import annotations


class QuiverFeedError(Exception):
    """Base exception for quiverfeed-specific failures."""


class AuthError(QuiverFeedError):
    """Raised for missing tokens or upstream 401 responses."""


class PlanRequiredError(QuiverFeedError):
    def __init__(
        self,
        dataset: str,
        message: str,
        hint_plan: str | None = None,
        path: str | None = None,
    ):
        self.dataset = dataset
        self.message = message
        self.hint_plan = hint_plan
        self.path = path
        hint = f" Hint plan: {hint_plan}." if hint_plan else ""
        path_detail = f" path={path!r}" if path else ""
        super().__init__(
            f"Plan required for dataset {dataset!r}{path_detail}: {message}.{hint}"
        )


class RateLimitError(QuiverFeedError):
    def __init__(self, retry_after_s: float):
        self.retry_after_s = float(retry_after_s)
        super().__init__(
            f"Rate limit reached; retry after {self.retry_after_s:.0f} seconds."
        )


class CatalogDriftError(QuiverFeedError):
    def __init__(self, dataset: str, missing_col: str, actual_cols: list[str]):
        self.dataset = dataset
        self.missing_col = missing_col
        self.actual_cols = actual_cols
        super().__init__(
            f"Catalog drift for {dataset!r}: expected column {missing_col!r}, "
            f"got columns {actual_cols!r}."
        )


class TruncatedResultError(QuiverFeedError):
    def __init__(self, dataset: str, max_pages: int):
        self.dataset = dataset
        self.max_pages = max_pages
        super().__init__(
            f"Fetch for {dataset!r} hit max_pages={max_pages} with a full final "
            "page; more data may exist."
        )


class UnknownDatasetError(QuiverFeedError):
    def __init__(self, name: str, known: list[str]):
        self.name = name
        self.known = known
        super().__init__(
            f"Unknown dataset {name!r}. Known datasets: {', '.join(sorted(known))}."
        )


class ResponseShapeError(QuiverFeedError):
    def __init__(self, dataset: str, shape: str):
        self.dataset = dataset
        self.shape = shape
        super().__init__(
            f"Unexpected response shape for {dataset!r}; expected a list or "
            f"an object with a list-valued 'data' key, got {shape}."
        )


class ParamIgnoredWarning(UserWarning):
    """Warns when a caller passes a known ignored upstream parameter."""


class CatalogDriftWarning(UserWarning):
    """Warns when catalog drift is detected with strict_catalog=False."""


class TruncatedResultWarning(UserWarning):
    """Warns when a caller asks to return potentially truncated results."""
