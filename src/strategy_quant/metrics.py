from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .models import Trade


def calculate_metrics(
    equity: pd.Series,
    trades: list[Trade],
    *,
    initial_capital: float,
    annual_bars: int,
) -> dict[str, float]:
    if equity.empty:
        raise ValueError("Equity curve cannot be empty")
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    elapsed_years = max((equity.index[-1] - equity.index[0]).total_seconds(), 1) / (365.25 * 86400)
    total_return = float(equity.iloc[-1] / initial_capital - 1.0)
    cagr = float((equity.iloc[-1] / initial_capital) ** (1 / elapsed_years) - 1.0)
    volatility = float(returns.std(ddof=0))
    sharpe = float(returns.mean() / volatility * math.sqrt(annual_bars)) if volatility else 0.0
    downside = float(returns[returns < 0].std(ddof=0))
    sortino = float(returns.mean() / downside * math.sqrt(annual_bars)) if downside else 0.0
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [trade.pnl for trade in trades if trade.pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if wins else 0.0)

    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": float(abs(drawdown.min())),
        "sharpe": sharpe,
        "sortino": sortino,
        "profit_factor": float(profit_factor),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "trades": float(len(trades)),
        "net_profit": float(sum(trade.pnl for trade in trades)),
        "average_trade": float(np.mean([trade.pnl for trade in trades])) if trades else 0.0,
    }

