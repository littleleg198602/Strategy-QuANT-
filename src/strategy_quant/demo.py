from __future__ import annotations

import numpy as np
import pandas as pd


def make_demo_bars(*, bars: int = 1_500, symbol: str = "EURUSD", seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=bars, freq="h", tz="UTC", name="time")
    drift = np.sin(np.arange(bars) / 80.0) * 0.00005
    close = 1.10 + np.cumsum(rng.normal(drift, 0.0007, bars))
    open_price = np.r_[close[0], close[:-1]]
    wick = rng.uniform(0.0001, 0.0008, bars)
    frame = pd.DataFrame(
        {
            "open": open_price,
            "high": np.maximum(open_price, close) + wick,
            "low": np.minimum(open_price, close) - wick,
            "close": close,
            "volume": rng.integers(100, 2_000, bars),
            "symbol": symbol,
        },
        index=index,
    )
    return frame

