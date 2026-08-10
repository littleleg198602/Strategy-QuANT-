from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from .models import DirectionMode, StrategySpec


@dataclass(frozen=True)
class SearchSpace:
    ema_fast: tuple[int, ...] = (10, 20, 30)
    ema_slow: tuple[int, ...] = (50, 100, 140)
    breakout_window: tuple[int, ...] = (10, 20, 40)
    atr_period: tuple[int, ...] = (14,)
    stop_atr: tuple[float, ...] = (1.5, 2.0)
    reward_risk: tuple[float, ...] = (1.5, 2.0, 3.0)
    directions: tuple[DirectionMode, ...] = ("both",)


def generate_candidates(space: SearchSpace | None = None) -> list[StrategySpec]:
    """Build a deterministic candidate bank from a constrained search space."""

    search = space or SearchSpace()
    candidates: list[StrategySpec] = []
    for fast, slow, atr_period, stop, reward, direction in product(
        search.ema_fast,
        search.ema_slow,
        search.atr_period,
        search.stop_atr,
        search.reward_risk,
        search.directions,
    ):
        if fast >= slow:
            continue
        candidates.append(
            StrategySpec(
                family="ema_cross",
                direction=direction,
                params={
                    "fast": fast,
                    "slow": slow,
                    "atr_period": atr_period,
                    "stop_atr": stop,
                    "target_atr": stop * reward,
                },
            )
        )
    for window, atr_period, stop, reward, direction in product(
        search.breakout_window,
        search.atr_period,
        search.stop_atr,
        search.reward_risk,
        search.directions,
    ):
        candidates.append(
            StrategySpec(
                family="breakout",
                direction=direction,
                params={
                    "window": window,
                    "atr_period": atr_period,
                    "stop_atr": stop,
                    "target_atr": stop * reward,
                },
            )
        )
    return candidates

