from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricFilter:
    min_trades: int = 30
    min_profit_factor: float = 1.10
    max_drawdown: float = 0.20
    min_sharpe: float = 0.0

    def accepts(self, metrics: dict[str, float]) -> bool:
        return (
            metrics["trades"] >= self.min_trades
            and metrics["profit_factor"] >= self.min_profit_factor
            and metrics["max_drawdown"] <= self.max_drawdown
            and metrics["sharpe"] >= self.min_sharpe
        )

