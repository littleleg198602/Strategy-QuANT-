from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_quant.indicators import ema
from strategy_quant.models import StrategySpec


def build_signal(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    if spec.family == "ema_cross":
        fast_period = int(spec.params["fast"])
        slow_period = int(spec.params["slow"])
        if fast_period >= slow_period:
            raise ValueError("EMA fast period must be lower than slow period")
        fast = ema(frame["close"], fast_period)
        slow = ema(frame["close"], slow_period)
        raw = pd.Series(np.where(fast > slow, 1, -1), index=frame.index, dtype="int8")
        raw[(fast.isna()) | (slow.isna())] = 0
    elif spec.family == "breakout":
        window = int(spec.params["window"])
        previous_high = frame["high"].rolling(window).max().shift(1)
        previous_low = frame["low"].rolling(window).min().shift(1)
        raw = pd.Series(0, index=frame.index, dtype="int8")
        raw[frame["close"] > previous_high] = 1
        raw[frame["close"] < previous_low] = -1
    else:
        raise ValueError(f"Unsupported strategy family: {spec.family}")

    if spec.direction == "long":
        raw[raw < 0] = 0
    elif spec.direction == "short":
        raw[raw > 0] = 0
    return raw

