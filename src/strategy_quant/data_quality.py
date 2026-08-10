from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from .data_models import QualityIssue, QualityReport

BAR_COLUMNS = (
    "open_ts_utc",
    "close_ts_utc",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "real_volume",
    "spread_points",
    "is_complete",
    "session_id",
)
TICK_COLUMNS = (
    "ts_utc",
    "bid",
    "ask",
    "last",
    "volume",
    "flags",
    "source_seq",
)


class DataQualityError(ValueError):
    def __init__(self, report: QualityReport):
        self.report = report
        details = "; ".join(issue.message for issue in report.issues if issue.severity == "FAIL")
        super().__init__(details or "Data quality gate failed")


@dataclass(frozen=True)
class ValidatedFrame:
    frame: pd.DataFrame
    report: QualityReport


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sample_timestamps(values: Iterable[object], *, limit: int = 5) -> tuple[str, ...]:
    return tuple(str(value) for value in list(values)[:limit])


def _coerce_utc(series: pd.Series, name: str) -> pd.Series:
    parsed = pd.to_datetime(series, errors="raise", utc=False)
    timezone = getattr(parsed.dt, "tz", None)
    if timezone is None:
        raise ValueError(f"{name} must be timezone-aware before canonicalization")
    return parsed.dt.tz_convert("UTC")


def validate_canonical_bars(frame: pd.DataFrame, *, raise_on_fail: bool = True) -> ValidatedFrame:
    input_rows = len(frame)
    missing = set(BAR_COLUMNS) - set(frame.columns)
    if missing:
        issue = QualityIssue("Q01", "FAIL", f"Missing bar columns: {', '.join(sorted(missing))}")
        report = QualityReport.build(
            datatype="bar",
            row_count_input=input_rows,
            row_count_output=input_rows,
            issues=[issue],
            created_at=_now(),
        )
        if raise_on_fail:
            raise DataQualityError(report)
        return ValidatedFrame(frame.copy(), report)

    result = frame.loc[:, BAR_COLUMNS].copy()
    result["open_ts_utc"] = _coerce_utc(result["open_ts_utc"], "open_ts_utc")
    result["close_ts_utc"] = _coerce_utc(result["close_ts_utc"], "close_ts_utc")
    issues: list[QualityIssue] = []
    if not result["open_ts_utc"].is_monotonic_increasing:
        issues.append(QualityIssue("Q03", "FAIL", "Bar timestamps are not monotonic"))

    duplicate_mask = result.duplicated(subset=["open_ts_utc"], keep=False)
    if duplicate_mask.any():
        duplicated = result.loc[duplicate_mask]
        conflict_keys: list[object] = []
        identical_removed = 0
        for key, group in duplicated.groupby("open_ts_utc", sort=False):
            if len(group.drop_duplicates()) == 1:
                identical_removed += len(group) - 1
            else:
                conflict_keys.append(key)
        if conflict_keys:
            issues.append(
                QualityIssue(
                    "Q05",
                    "FAIL",
                    "Conflicting rows share the same bar timestamp",
                    len(conflict_keys),
                    _sample_timestamps(conflict_keys),
                )
            )
        if identical_removed:
            issues.append(
                QualityIssue(
                    "Q04",
                    "WARN",
                    "Identical duplicate bars were removed",
                    identical_removed,
                )
            )
            result = result.drop_duplicates(keep="first")

    result = result.sort_values("open_ts_utc", kind="stable").reset_index(drop=True)
    prices = result[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    finite_positive = np.isfinite(prices.to_numpy()).all(axis=1) & (prices > 0).all(axis=1)
    if not finite_positive.all():
        bad = result.loc[~finite_positive, "open_ts_utc"]
        issues.append(
            QualityIssue(
                "Q01",
                "FAIL",
                "OHLC prices must be finite and positive",
                int((~finite_positive).sum()),
                _sample_timestamps(bad),
            )
        )
    envelope = (
        (prices["high"] >= prices[["open", "close"]].max(axis=1))
        & (prices["low"] <= prices[["open", "close"]].min(axis=1))
        & (prices["high"] >= prices["low"])
    )
    if not envelope.all():
        bad = result.loc[~envelope, "open_ts_utc"]
        issues.append(
            QualityIssue(
                "Q02",
                "FAIL",
                "High/low values form an invalid OHLC envelope",
                int((~envelope).sum()),
                _sample_timestamps(bad),
            )
        )
    if (result["close_ts_utc"] <= result["open_ts_utc"]).any():
        bad_mask = result["close_ts_utc"] <= result["open_ts_utc"]
        issues.append(
            QualityIssue(
                "Q01",
                "FAIL",
                "Bar close timestamp must be later than open timestamp",
                int(bad_mask.sum()),
                _sample_timestamps(result.loc[bad_mask, "open_ts_utc"]),
            )
        )
    for column in ("tick_volume", "real_volume", "spread_points"):
        values = pd.to_numeric(result[column], errors="coerce")
        if (values.dropna() < 0).any():
            issues.append(QualityIssue("Q01", "FAIL", f"{column} cannot be negative"))

    incomplete = ~result["is_complete"].astype(bool)
    if incomplete.any():
        issues.append(
            QualityIssue(
                "Q13",
                "INFO",
                "Incomplete bars were removed from the frozen dataset",
                int(incomplete.sum()),
                _sample_timestamps(result.loc[incomplete, "open_ts_utc"]),
            )
        )
        result = result.loc[~incomplete].reset_index(drop=True)

    report = QualityReport.build(
        datatype="bar",
        row_count_input=input_rows,
        row_count_output=len(result),
        issues=issues,
        created_at=_now(),
    )
    if raise_on_fail and report.status == "FAIL":
        raise DataQualityError(report)
    return ValidatedFrame(result, report)


def validate_canonical_ticks(frame: pd.DataFrame, *, raise_on_fail: bool = True) -> ValidatedFrame:
    input_rows = len(frame)
    missing = set(TICK_COLUMNS) - set(frame.columns)
    if missing:
        issue = QualityIssue("Q01", "FAIL", f"Missing tick columns: {', '.join(sorted(missing))}")
        report = QualityReport.build(
            datatype="tick",
            row_count_input=input_rows,
            row_count_output=input_rows,
            issues=[issue],
            created_at=_now(),
        )
        if raise_on_fail:
            raise DataQualityError(report)
        return ValidatedFrame(frame.copy(), report)

    result = frame.loc[:, TICK_COLUMNS].copy()
    result["ts_utc"] = _coerce_utc(result["ts_utc"], "ts_utc")
    original_monotonic = result["ts_utc"].is_monotonic_increasing
    result = result.sort_values(["ts_utc", "source_seq"], kind="stable").reset_index(drop=True)
    issues: list[QualityIssue] = []
    if not original_monotonic:
        issues.append(QualityIssue("Q03", "FAIL", "Tick timestamps are not monotonic"))
    prices = result[["bid", "ask"]].apply(pd.to_numeric, errors="coerce")
    invalid = ~np.isfinite(prices.to_numpy()).all(axis=1) | (prices <= 0).any(axis=1)
    if invalid.any():
        issues.append(
            QualityIssue(
                "Q01",
                "FAIL",
                "Bid and ask must be finite and positive",
                int(invalid.sum()),
                _sample_timestamps(result.loc[invalid, "ts_utc"]),
            )
        )
    crossed = prices["ask"] < prices["bid"]
    if crossed.any():
        issues.append(
            QualityIssue(
                "Q06",
                "FAIL",
                "Tick ask is below bid",
                int(crossed.sum()),
                _sample_timestamps(result.loc[crossed, "ts_utc"]),
            )
        )
    report = QualityReport.build(
        datatype="tick",
        row_count_input=input_rows,
        row_count_output=len(result),
        issues=issues,
        created_at=_now(),
    )
    if raise_on_fail and report.status == "FAIL":
        raise DataQualityError(report)
    return ValidatedFrame(result, report)
