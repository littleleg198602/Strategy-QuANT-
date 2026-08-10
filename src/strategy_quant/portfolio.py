from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .engine import BacktestEngine
from .metrics import calculate_metrics
from .models import BacktestConfig, BacktestResult, StrategySpec


class PortfolioEngine:
    """Equal-capital multi-symbol wrapper around the deterministic bar engine."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, frames: dict[str, pd.DataFrame], strategy: StrategySpec) -> BacktestResult:
        if not frames:
            raise ValueError("At least one symbol is required")
        allocated = self.config.initial_capital / len(frames)
        child_config = replace(self.config, initial_capital=allocated)
        child_engine = BacktestEngine(child_config)
        child_results = [child_engine.run(frame, strategy) for frame in frames.values()]
        union_index = child_results[0].equity.index
        for result in child_results[1:]:
            union_index = union_index.union(result.equity.index)
        union_index = union_index.sort_values()
        curves = [
            result.equity.reindex(union_index).ffill().fillna(allocated)
            for result in child_results
        ]
        equity = pd.concat(curves, axis=1).sum(axis=1).rename("equity")
        trades = sorted(
            [trade for result in child_results for trade in result.trades],
            key=lambda trade: trade.exit_time,
        )
        metrics = calculate_metrics(
            equity,
            trades,
            initial_capital=self.config.initial_capital,
            annual_bars=self.config.annual_bars,
        )
        metrics["symbols"] = float(len(frames))
        metrics["drawdown_guard_triggered"] = float(
            any(result.metrics["drawdown_guard_triggered"] for result in child_results)
        )
        return BacktestResult(
            strategy=strategy,
            symbol="PORTFOLIO",
            trades=trades,
            equity=equity,
            metrics=metrics,
        )


def rank_portfolio_candidates(
    frames: dict[str, pd.DataFrame],
    candidates: list[StrategySpec],
    engine: PortfolioEngine,
) -> list[BacktestResult]:
    results = [engine.run(frames, candidate) for candidate in candidates]
    results.sort(
        key=lambda result: (
            result.metrics["sharpe"]
            + result.metrics["total_return"]
            - 1.5 * result.metrics["max_drawdown"]
        ),
        reverse=True,
    )
    return results

