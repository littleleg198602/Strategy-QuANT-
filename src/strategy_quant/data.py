from __future__ import annotations

from pathlib import Path
from typing import IO

import pandas as pd


OHLC = ("open", "high", "low", "close")


def _normalise_name(value: str) -> str:
    return value.strip().lower().replace("<", "").replace(">", "").replace(" ", "_")


def load_mt5_csv(
    source: str | Path | IO[bytes] | IO[str],
    *,
    symbol: str | None = None,
    timezone: str = "UTC",
) -> pd.DataFrame:
    """Load common MT5 CSV/tab exports into a validated canonical OHLCV frame.

    Naive timestamps are interpreted using ``timezone`` and converted to UTC. Pass the
    broker timezone explicitly when the export is not UTC.
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

    parsed = pd.to_datetime(timestamps, errors="raise")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    parsed = parsed.dt.tz_convert("UTC")

    result = pd.DataFrame(index=pd.DatetimeIndex(parsed, name="time"))
    for column in OHLC:
        result[column] = pd.to_numeric(frame[column], errors="raise").to_numpy()

    volume_column = next(
        (name for name in ("tick_volume", "volume", "vol") if name in frame.columns), None
    )
    result["volume"] = (
        pd.to_numeric(frame[volume_column], errors="coerce").fillna(0).to_numpy()
        if volume_column
        else 0.0
    )
    result["symbol"] = symbol or _infer_symbol(source)
    result = result[~result.index.duplicated(keep="last")].sort_index()
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


def _infer_symbol(source: object) -> str:
    name = getattr(source, "name", None)
    if name:
        return Path(str(name)).stem.upper()
    if isinstance(source, (str, Path)):
        return Path(source).stem.upper()
    return "UNKNOWN"

