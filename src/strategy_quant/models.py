from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd


DirectionMode = Literal["long", "short", "both"]


@dataclass(frozen=True)
class StrategySpec:
    """Serializable strategy definition produced by the generator."""

    family: Literal["ema_cross", "breakout"]
    params: dict[str, int | float]
    direction: DirectionMode = "both"
    name: str | None = None

    @property
    def strategy_id(self) -> str:
        values = "-".join(f"{key}{self.params[key]:g}" for key in sorted(self.params))
        return self.name or f"{self.family}-{self.direction}-{values}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"strategy_id": self.strategy_id}


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    risk_fraction: float = 0.005
    max_drawdown: float = 0.20
    spread_bps: float = 1.0
    slippage_bps: float = 0.5
    annual_bars: int = 252 * 24
    same_bar_policy: Literal["stop_first", "target_first"] = "stop_first"

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not 0 < self.risk_fraction <= 1:
            raise ValueError("risk_fraction must be in (0, 1]")
        if not 0 < self.max_drawdown < 1:
            raise ValueError("max_drawdown must be in (0, 1)")
        if self.spread_bps < 0 or self.slippage_bps < 0:
            raise ValueError("costs cannot be negative")


@dataclass(frozen=True)
class Trade:
    symbol: str
    direction: Literal[1, -1]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    quantity: float
    pnl: float
    return_fraction: float
    exit_reason: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["side"] = "long" if self.direction == 1 else "short"
        return data


@dataclass
class BacktestResult:
    strategy: StrategySpec
    symbol: str
    trades: list[Trade]
    equity: pd.Series
    metrics: dict[str, float] = field(default_factory=dict)

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([trade.to_dict() for trade in self.trades])

