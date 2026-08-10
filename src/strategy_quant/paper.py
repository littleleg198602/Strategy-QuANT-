from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .data import load_mt5_csv
from .engine import BacktestEngine
from .models import BacktestResult, StrategySpec


@dataclass(frozen=True)
class PaperUpdate:
    result: BacktestResult
    new_trades: int
    latest_bar: pd.Timestamp


class PaperSimulator:
    """CSV polling state; it never connects to a broker or sends an order."""

    def __init__(self, state_path: str | Path, engine: BacktestEngine) -> None:
        self.state_path = Path(state_path)
        self.engine = engine

    def refresh(
        self,
        csv_path: str | Path,
        strategy: StrategySpec,
        *,
        symbol: str | None = None,
        timezone: str = "UTC",
    ) -> PaperUpdate:
        frame = load_mt5_csv(csv_path, symbol=symbol, timezone=timezone)
        result = self.engine.run(frame, strategy)
        previous = self._read_state()
        previous_count = int(previous.get("trade_count", 0))
        self._write_state(
            {
                "strategy_id": strategy.strategy_id,
                "latest_bar": frame.index[-1].isoformat(),
                "trade_count": len(result.trades),
            }
        )
        return PaperUpdate(
            result=result,
            new_trades=max(0, len(result.trades) - previous_count),
            latest_bar=frame.index[-1],
        )

    def _read_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write_state(self, state: dict[str, object]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

