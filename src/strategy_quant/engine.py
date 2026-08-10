from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import validate_bars
from .indicators import atr
from .metrics import calculate_metrics
from .models import BacktestConfig, BacktestResult, StrategySpec, Trade
from .strategies import build_signal


@dataclass
class _Position:
    direction: int
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    quantity: float
    equity_before: float


class BacktestEngine:
    """Deterministic single-symbol bar engine with next-bar execution."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, frame: pd.DataFrame, strategy: StrategySpec) -> BacktestResult:
        validate_bars(frame)
        if frame["symbol"].nunique() != 1:
            raise ValueError("BacktestEngine.run expects exactly one symbol")
        symbol = str(frame["symbol"].iloc[0])
        signal = build_signal(frame, strategy)
        atr_period = int(strategy.params.get("atr_period", 14))
        stop_atr = float(strategy.params.get("stop_atr", 2.0))
        target_atr = float(strategy.params.get("target_atr", 3.0))
        volatility = atr(frame, atr_period)

        cash = self.config.initial_capital
        peak_equity = cash
        trading_disabled = False
        position: _Position | None = None
        trades: list[Trade] = []
        equity_values: list[float] = []

        for bar_number, (timestamp, bar) in enumerate(frame.iterrows()):
            desired = int(signal.iloc[bar_number - 1]) if bar_number else 0
            raw_open = float(bar["open"])

            if position and desired and desired != position.direction:
                cash, trade = self._close(position, raw_open, timestamp, symbol, cash, "opposite_signal")
                trades.append(trade)
                position = None

            previous_atr = float(volatility.iloc[bar_number - 1]) if bar_number else np.nan
            if not position and desired and not trading_disabled and np.isfinite(previous_atr):
                stop_distance = previous_atr * stop_atr
                if stop_distance > 0:
                    equity_before = cash
                    quantity = equity_before * self.config.risk_fraction / stop_distance
                    entry_price = self._adverse_price(raw_open, desired, entering=True)
                    position = _Position(
                        direction=desired,
                        entry_time=timestamp,
                        entry_price=entry_price,
                        stop_price=raw_open - desired * stop_distance,
                        target_price=raw_open + desired * previous_atr * target_atr,
                        quantity=quantity,
                        equity_before=equity_before,
                    )

            if position:
                exit_price, reason = self._intrabar_exit(position, bar)
                if exit_price is not None:
                    cash, trade = self._close(
                        position, exit_price, timestamp, symbol, cash, reason, price_already_adjusted=True
                    )
                    trades.append(trade)
                    position = None

            marked_equity = cash
            if position:
                marked_equity += (
                    position.quantity
                    * position.direction
                    * (float(bar["close"]) - position.entry_price)
                )
            equity_values.append(marked_equity)
            peak_equity = max(peak_equity, marked_equity)
            if marked_equity / peak_equity - 1.0 <= -self.config.max_drawdown:
                trading_disabled = True

        if position:
            final_time = frame.index[-1]
            cash, trade = self._close(
                position, float(frame["close"].iloc[-1]), final_time, symbol, cash, "end_of_data"
            )
            trades.append(trade)
            equity_values[-1] = cash

        equity = pd.Series(equity_values, index=frame.index, name="equity", dtype=float)
        metrics = calculate_metrics(
            equity,
            trades,
            initial_capital=self.config.initial_capital,
            annual_bars=self.config.annual_bars,
        )
        metrics["drawdown_guard_triggered"] = float(trading_disabled)
        return BacktestResult(strategy=strategy, symbol=symbol, trades=trades, equity=equity, metrics=metrics)

    def _intrabar_exit(self, position: _Position, bar: pd.Series) -> tuple[float | None, str]:
        open_price = float(bar["open"])
        high = float(bar["high"])
        low = float(bar["low"])
        if position.direction == 1:
            if open_price <= position.stop_price:
                return self._adverse_price(open_price, 1, entering=False), "stop_gap"
            if open_price >= position.target_price:
                return self._adverse_price(open_price, 1, entering=False), "target_gap"
            stop_hit = low <= position.stop_price
            target_hit = high >= position.target_price
        else:
            if open_price >= position.stop_price:
                return self._adverse_price(open_price, -1, entering=False), "stop_gap"
            if open_price <= position.target_price:
                return self._adverse_price(open_price, -1, entering=False), "target_gap"
            stop_hit = high >= position.stop_price
            target_hit = low <= position.target_price

        if stop_hit and target_hit:
            if self.config.same_bar_policy == "stop_first":
                return self._adverse_price(position.stop_price, position.direction, False), "stop_same_bar"
            return self._adverse_price(position.target_price, position.direction, False), "target_same_bar"
        if stop_hit:
            return self._adverse_price(position.stop_price, position.direction, False), "stop"
        if target_hit:
            return self._adverse_price(position.target_price, position.direction, False), "target"
        return None, ""

    def _close(
        self,
        position: _Position,
        raw_price: float,
        timestamp: pd.Timestamp,
        symbol: str,
        cash: float,
        reason: str,
        *,
        price_already_adjusted: bool = False,
    ) -> tuple[float, Trade]:
        exit_price = raw_price
        if not price_already_adjusted:
            exit_price = self._adverse_price(raw_price, position.direction, entering=False)
        pnl = position.quantity * position.direction * (exit_price - position.entry_price)
        cash += pnl
        trade = Trade(
            symbol=symbol,
            direction=position.direction,  # type: ignore[arg-type]
            entry_time=position.entry_time,
            exit_time=timestamp,
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_price=position.stop_price,
            target_price=position.target_price,
            quantity=position.quantity,
            pnl=pnl,
            return_fraction=pnl / position.equity_before,
            exit_reason=reason,
        )
        return cash, trade

    def _adverse_price(self, price: float, direction: int, entering: bool) -> float:
        half_spread = self.config.spread_bps / 2.0
        total_bps = half_spread + self.config.slippage_bps
        sign = direction if entering else -direction
        return price * (1.0 + sign * total_bps / 10_000.0)
