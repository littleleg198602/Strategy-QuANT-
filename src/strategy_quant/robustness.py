from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .engine import BacktestEngine
from .models import BacktestResult, StrategySpec


@dataclass(frozen=True)
class RobustnessReport:
    in_sample_return: float
    out_of_sample_return: float
    out_of_sample_profit_factor: float
    walk_forward_positive_ratio: float
    monte_carlo_return_p05: float
    monte_carlo_drawdown_p95: float

    def to_dict(self) -> dict[str, float]:
        return {
            "is_return": self.in_sample_return,
            "oos_return": self.out_of_sample_return,
            "oos_profit_factor": self.out_of_sample_profit_factor,
            "wf_positive_ratio": self.walk_forward_positive_ratio,
            "mc_return_p05": self.monte_carlo_return_p05,
            "mc_drawdown_p95": self.monte_carlo_drawdown_p95,
        }


def evaluate_robustness(
    frame: pd.DataFrame,
    strategy: StrategySpec,
    engine: BacktestEngine,
    *,
    split_ratio: float = 0.70,
    walk_forward_folds: int = 3,
    monte_carlo_runs: int = 500,
    seed: int = 42,
) -> RobustnessReport:
    if not 0.5 <= split_ratio < 1:
        raise ValueError("split_ratio must be in [0.5, 1)")
    split = int(len(frame) * split_ratio)
    train = engine.run(frame.iloc[:split].copy(), strategy)
    test = engine.run(frame.iloc[split:].copy(), strategy)

    boundaries = np.linspace(0, len(frame), walk_forward_folds + 1, dtype=int)
    chunks = [
        frame.iloc[boundaries[index] : boundaries[index + 1]].copy()
        for index in range(walk_forward_folds)
        if boundaries[index + 1] - boundaries[index] >= 30
    ]
    fold_returns = [engine.run(chunk.copy(), strategy).metrics["total_return"] for chunk in chunks]
    positive_ratio = sum(value > 0 for value in fold_returns) / len(fold_returns) if fold_returns else 0.0
    mc_return, mc_drawdown = monte_carlo_trades(
        train, runs=monte_carlo_runs, seed=seed
    )
    return RobustnessReport(
        in_sample_return=train.metrics["total_return"],
        out_of_sample_return=test.metrics["total_return"],
        out_of_sample_profit_factor=test.metrics["profit_factor"],
        walk_forward_positive_ratio=positive_ratio,
        monte_carlo_return_p05=mc_return,
        monte_carlo_drawdown_p95=mc_drawdown,
    )


def monte_carlo_trades(
    result: BacktestResult, *, runs: int = 500, seed: int = 42
) -> tuple[float, float]:
    returns = np.asarray([trade.return_fraction for trade in result.trades], dtype=float)
    if returns.size == 0:
        return 0.0, 0.0
    rng = np.random.default_rng(seed)
    terminal_returns: list[float] = []
    maximum_drawdowns: list[float] = []
    for _ in range(runs):
        sample = rng.choice(returns, size=len(returns), replace=True)
        curve = np.cumprod(1.0 + sample)
        peaks = np.maximum.accumulate(np.r_[1.0, curve])[1:]
        drawdowns = curve / peaks - 1.0
        terminal_returns.append(float(curve[-1] - 1.0))
        maximum_drawdowns.append(float(abs(drawdowns.min())))
    return (
        float(np.quantile(terminal_returns, 0.05)),
        float(np.quantile(maximum_drawdowns, 0.95)),
    )
