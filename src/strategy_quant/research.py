from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .engine import BacktestEngine
from .filtering import MetricFilter
from .models import BacktestResult, StrategySpec
from .robustness import RobustnessReport, evaluate_robustness


@dataclass
class CandidateEvaluation:
    result: BacktestResult
    accepted: bool
    score: float
    robustness: RobustnessReport | None = None

    def row(self) -> dict[str, object]:
        return {
            "strategy_id": self.result.strategy.strategy_id,
            "family": self.result.strategy.family,
            "accepted": self.accepted,
            "score": self.score,
            **self.result.metrics,
            **(self.robustness.to_dict() if self.robustness else {}),
        }


def run_research(
    frame: pd.DataFrame,
    candidates: list[StrategySpec],
    engine: BacktestEngine,
    *,
    metric_filter: MetricFilter | None = None,
    robustness_top_n: int = 5,
    monte_carlo_runs: int = 300,
) -> list[CandidateEvaluation]:
    filter_config = metric_filter or MetricFilter()
    evaluations: list[CandidateEvaluation] = []
    for candidate in candidates:
        result = engine.run(frame, candidate)
        accepted = filter_config.accepts(result.metrics)
        score = (
            result.metrics["sharpe"]
            + result.metrics["total_return"]
            - 1.5 * result.metrics["max_drawdown"]
        )
        evaluations.append(CandidateEvaluation(result=result, accepted=accepted, score=score))
    evaluations.sort(key=lambda item: (item.accepted, item.score), reverse=True)

    for evaluation in evaluations[:robustness_top_n]:
        evaluation.robustness = evaluate_robustness(
            frame,
            evaluation.result.strategy,
            engine,
            monte_carlo_runs=monte_carlo_runs,
        )
    return evaluations


def results_frame(evaluations: list[CandidateEvaluation]) -> pd.DataFrame:
    return pd.DataFrame([evaluation.row() for evaluation in evaluations])

