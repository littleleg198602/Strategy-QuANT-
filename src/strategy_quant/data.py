from __future__ import annotations

import hashlib
from pathlib import Path
from typing import IO, Literal

import numpy as np
import pandas as pd

from .data_quality import (
    BAR_COLUMNS,
    TICK_COLUMNS,
    validate_canonical_bars,
)

OHLC = ("open", "high", "low", "close")
TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}
RESAMPLER_VERSION = "1"


def _normalise_name(value: str) -> str:
    return value.strip().lower().replace("<", "").replace(">", "").replace(" ", "_")


def _parse_timestamps(
    values: pd.Series,
    timezone: str | None,
    wall_clock_offset_minutes: int = 0,
) -> pd.Series:
    parsed = pd.to_datetime(values, errors="raise")
    if parsed.dt.tz is None:
        if not timezone:
            raise ValueError("Naive timestamps require an explicit IANA timezone")
        if wall_clock_offset_minutes:
            parsed = parsed - pd.Timedelta(minutes=wall_clock_offset_minutes)
        parsed = parsed.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    return parsed.dt.tz_convert("UTC")


def _timeframe_delta(timeframe: str) -> pd.Timedelta:
    normalized = timeframe.upper()
    if normalized not in TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe {timeframe!r}")
    return pd.Timedelta(minutes=TIMEFRAME_MINUTES[normalized])


def read_mt5_csv(
    source: str | Path | IO[bytes] | IO[str],
    *,
    timezone: str | None,
    timeframe: str = "M1",
    as_of: pd.Timestamp | None = None,
    wall_clock_offset_minutes: int = 0,
) -> pd.DataFrame:
    """Read a bars export and return the canonical M1/bar schema.

    Timestamp localization is deliberately strict: naive values require a configured
    broker timezone and ambiguous/nonexistent DST timestamps raise an exception.
    """

    frame = pd.read_csv(source, sep=None, engine="python")
    frame.columns = [_normalise_name(str(column)) for column in frame.columns]
    if "datetime" in frame:
        timestamps = frame.pop("datetime")
    elif "time" in frame and "date" in frame:
        timestamps = frame.pop("date").astype(str) + " " + frame.pop("time").astype(str)
    elif "time" in frame:
        timestamps = frame.pop("time")
    elif "date" in frame:
        timestamps = frame.pop("date")
    else:
        raise ValueError("CSV must contain time/datetime or date + time columns")

    missing = set(OHLC) - set(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
    opens = _parse_timestamps(timestamps, timezone, wall_clock_offset_minutes)
    delta = _timeframe_delta(timeframe)
    complete_at = pd.Timestamp.now(tz="UTC") if as_of is None else pd.Timestamp(as_of)
    if complete_at.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    complete_at = complete_at.tz_convert("UTC")

    result = pd.DataFrame(
        {
            "open_ts_utc": opens,
            "close_ts_utc": opens + delta,
            "open": pd.to_numeric(frame["open"], errors="coerce"),
            "high": pd.to_numeric(frame["high"], errors="coerce"),
            "low": pd.to_numeric(frame["low"], errors="coerce"),
            "close": pd.to_numeric(frame["close"], errors="coerce"),
            "tick_volume": _numeric_column(frame, ("tick_volume", "volume", "vol"), 0, "int"),
            "real_volume": _numeric_column(frame, ("real_volume",), np.nan, "float"),
            "spread_points": _numeric_column(frame, ("spread", "spread_points"), np.nan, "float"),
            "is_complete": (opens + delta) <= complete_at,
            "session_id": None,
        }
    )
    return result.loc[:, BAR_COLUMNS]


def _numeric_column(
    frame: pd.DataFrame,
    names: tuple[str, ...],
    default: float,
    dtype: Literal["float", "int"],
) -> pd.Series:
    column = next((name for name in names if name in frame.columns), None)
    if column is None:
        values = pd.Series([default] * len(frame), index=frame.index)
    else:
        values = pd.to_numeric(frame[column], errors="coerce")
    if dtype == "int" and not values.isna().any():
        return values.astype("int64")
    return values.astype("float64")


def canonicalize_mt5_rates(
    rates: object,
    *,
    timeframe: str = "M1",
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    raw = pd.DataFrame(rates)
    if raw.empty:
        raise ValueError("MT5 returned no bars")
    if "time" not in raw:
        raise ValueError("MT5 rates are missing the time field")
    opens = pd.to_datetime(raw["time"], unit="s", utc=True)
    delta = _timeframe_delta(timeframe)
    complete_at = pd.Timestamp.now(tz="UTC") if as_of is None else pd.Timestamp(as_of)
    if complete_at.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    result = pd.DataFrame(
        {
            "open_ts_utc": opens,
            "close_ts_utc": opens + delta,
            "open": pd.to_numeric(raw["open"], errors="coerce"),
            "high": pd.to_numeric(raw["high"], errors="coerce"),
            "low": pd.to_numeric(raw["low"], errors="coerce"),
            "close": pd.to_numeric(raw["close"], errors="coerce"),
            "tick_volume": _numeric_column(raw, ("tick_volume",), 0, "int"),
            "real_volume": _numeric_column(raw, ("real_volume",), np.nan, "float"),
            "spread_points": _numeric_column(raw, ("spread",), np.nan, "float"),
            "is_complete": (opens + delta) <= complete_at.tz_convert("UTC"),
            "session_id": None,
        }
    )
    return result.loc[:, BAR_COLUMNS]


def canonicalize_mt5_ticks(ticks: object) -> pd.DataFrame:
    raw = pd.DataFrame(ticks)
    if raw.empty:
        raise ValueError("MT5 returned no ticks")
    if "time_msc" in raw:
        timestamps = pd.to_datetime(raw["time_msc"], unit="ms", utc=True)
    elif "time" in raw:
        timestamps = pd.to_datetime(raw["time"], unit="s", utc=True)
    else:
        raise ValueError("MT5 ticks are missing time_msc/time")
    sequence = pd.Series(np.arange(len(raw), dtype="int64"), index=raw.index)
    result = pd.DataFrame(
        {
            "ts_utc": timestamps,
            "bid": pd.to_numeric(raw["bid"], errors="coerce"),
            "ask": pd.to_numeric(raw["ask"], errors="coerce"),
            "last": _numeric_column(raw, ("last",), np.nan, "float"),
            "volume": _numeric_column(raw, ("volume_real", "volume"), np.nan, "float"),
            "flags": _numeric_column(raw, ("flags",), 0, "int"),
            "source_seq": sequence,
        }
    )
    return result.loc[:, TICK_COLUMNS]


def load_mt5_csv(
    source: str | Path | IO[bytes] | IO[str],
    *,
    symbol: str | None = None,
    timezone: str | None = "UTC",
) -> pd.DataFrame:
    """Load a common MT5 bars export into the legacy backtest frame.

    Data Manager uses :func:`read_mt5_csv`; this compatibility helper keeps the existing
    engine API while enforcing the same quality gate.
    """

    canonical = read_mt5_csv(source, timezone=timezone, timeframe="M1")
    validated = validate_canonical_bars(canonical).frame
    return canonical_bars_to_engine_frame(validated, symbol=symbol or _infer_symbol(source))


def canonical_bars_to_engine_frame(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    validated = validate_canonical_bars(frame).frame
    result = validated.set_index("open_ts_utc")[["open", "high", "low", "close"]].copy()
    result.index.name = "time"
    result["volume"] = validated["tick_volume"].to_numpy(dtype="float64")
    result["symbol"] = symbol
    validate_bars(result)
    return result


def validate_bars(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise ValueError("No bars found")
    if frame.index.tz is None:
        raise ValueError("Bar index must be timezone-aware")
    if frame[list(OHLC)].isna().any().any():
        raise ValueError("OHLC data contains missing values")
    if (frame[list(OHLC)] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any():
        raise ValueError("High is below open or close")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any():
        raise ValueError("Low is above open or close")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("Bars must be sorted by time")


def resample_canonical_bars(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    broker_timezone: str,
    broker_offset_minutes: int = 0,
    gap_policy: Literal["reject", "keep-with-flag", "session-expected"] = "session-expected",
) -> pd.DataFrame:
    """Aggregate M1 bars using broker-local bucket boundaries.

    ``session-expected`` keeps a bucket complete when every supplied M1 bar is complete;
    this is the safe default until an instrument session calendar is available.
    """

    target = timeframe.upper()
    if target == "M1":
        return validate_canonical_bars(frame).frame
    minutes = TIMEFRAME_MINUTES.get(target)
    if minutes is None:
        raise ValueError(f"Unsupported target timeframe {timeframe!r}")
    source = validate_canonical_bars(frame).frame
    local = source.copy()
    offset = pd.Timedelta(minutes=broker_offset_minutes)
    local.index = pd.DatetimeIndex(local["open_ts_utc"]).tz_convert(broker_timezone) + offset
    rule = f"{minutes}min"
    grouped = local.resample(rule, origin="start_day", label="left", closed="left")
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        tick_volume=("tick_volume", "sum"),
        real_volume=("real_volume", lambda values: values.sum(min_count=1)),
        spread_points=("spread_points", "last"),
        is_complete=("is_complete", "all"),
        session_id=("session_id", "last"),
    ).dropna(subset=["open"])
    counts = grouped["open"].count().reindex(result.index)
    expected = minutes
    if gap_policy == "reject" and (counts != expected).any():
        bad = result.index[counts != expected]
        raise ValueError(f"Incomplete {target} buckets: {', '.join(str(value) for value in bad[:5])}")
    if gap_policy == "keep-with-flag":
        result["is_complete"] = result["is_complete"] & (counts == expected)
    result.insert(0, "open_ts_utc", (result.index - offset).tz_convert("UTC"))
    result.insert(
        1,
        "close_ts_utc",
        (result.index + pd.Timedelta(minutes=minutes) - offset).tz_convert("UTC"),
    )
    return validate_canonical_bars(result.reset_index(drop=True)).frame


def source_sha256(source: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(source).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _infer_symbol(source: object) -> str:
    name = getattr(source, "name", None)
    if name:
        return Path(str(name)).stem.upper()
    if isinstance(source, (str, Path)):
        return Path(source).stem.upper()
    return "UNKNOWN"
