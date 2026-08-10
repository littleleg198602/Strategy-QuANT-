"""Strategy QuANT research engine."""

from .engine import BacktestEngine
from .models import BacktestConfig, BacktestResult, StrategySpec, Trade

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "StrategySpec",
    "Trade",
]

__version__ = "0.1.0"

