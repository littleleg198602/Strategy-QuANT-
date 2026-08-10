from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from strategy_quant.data import load_mt5_csv
from strategy_quant.demo import make_demo_bars
from strategy_quant.engine import BacktestEngine
from strategy_quant.exporter import export_mql5, export_strategy_json
from strategy_quant.generator import generate_candidates
from strategy_quant.models import BacktestConfig, StrategySpec
from strategy_quant.paper import PaperSimulator
from strategy_quant.portfolio import PortfolioEngine
from strategy_quant.robustness import monte_carlo_trades
from strategy_quant.strategies import build_signal


def ema_strategy() -> StrategySpec:
    return StrategySpec(
        family="ema_cross",
        params={"fast": 5, "slow": 15, "atr_period": 7, "stop_atr": 2.0, "target_atr": 3.0},
    )


class DataTests(unittest.TestCase):
    def test_mt5_date_time_export_is_normalised_to_utc(self) -> None:
        csv = io.StringIO(
            "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICK_VOLUME>\n"
            "2026.01.02\t10:00:00\t1.1\t1.2\t1.0\t1.15\t100\n"
            "2026.01.02\t11:00:00\t1.15\t1.25\t1.1\t1.2\t120\n"
        )
        frame = load_mt5_csv(csv, symbol="EURUSD", timezone="Europe/Prague")
        self.assertEqual(list(frame.columns), ["open", "high", "low", "close", "volume", "symbol"])
        self.assertEqual(str(frame.index.tz), "UTC")
        self.assertEqual(frame["symbol"].iloc[0], "EURUSD")

    def test_invalid_ohlc_is_rejected(self) -> None:
        csv = io.StringIO("time,open,high,low,close\n2026-01-01,1,0.9,0.8,1.1\n")
        with self.assertRaisesRegex(ValueError, "High"):
            load_mt5_csv(csv)


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = make_demo_bars(bars=600)
        self.strategy = ema_strategy()

    def test_backtest_is_deterministic_and_returns_auditable_trades(self) -> None:
        first = BacktestEngine().run(self.frame, self.strategy)
        second = BacktestEngine().run(self.frame, self.strategy)
        self.assertGreater(len(first.trades), 0)
        self.assertAlmostEqual(first.equity.iloc[-1], second.equity.iloc[-1])
        self.assertIn(first.trades[0].exit_reason, {
            "stop", "target", "stop_gap", "target_gap", "stop_same_bar",
            "target_same_bar", "opposite_signal", "end_of_data"
        })

    def test_signal_is_executed_on_the_next_bar(self) -> None:
        signals = build_signal(self.frame, self.strategy)
        result = BacktestEngine().run(self.frame, self.strategy)
        first_signal_time = signals[signals != 0].index[0]
        expected_entry = self.frame.index[self.frame.index.get_loc(first_signal_time) + 1]
        self.assertEqual(result.trades[0].entry_time, expected_entry)

    def test_costs_reduce_equity(self) -> None:
        free = BacktestEngine(BacktestConfig(spread_bps=0, slippage_bps=0)).run(
            self.frame, self.strategy
        )
        costly = BacktestEngine(BacktestConfig(spread_bps=3, slippage_bps=2)).run(
            self.frame, self.strategy
        )
        self.assertLess(costly.equity.iloc[-1], free.equity.iloc[-1])

    def test_last_bar_change_cannot_change_earlier_signals(self) -> None:
        before = build_signal(self.frame, self.strategy)
        changed = self.frame.copy()
        changed.loc[changed.index[-1], "close"] *= 1.5
        changed.loc[changed.index[-1], "high"] = changed.loc[changed.index[-1], "close"]
        after = build_signal(changed, self.strategy)
        pd.testing.assert_series_equal(before.iloc[:-1], after.iloc[:-1])


class ResearchTests(unittest.TestCase):
    def test_default_generator_is_stable(self) -> None:
        candidates = generate_candidates()
        self.assertEqual(len(candidates), 72)
        self.assertEqual(len({candidate.strategy_id for candidate in candidates}), 72)

    def test_monte_carlo_is_seeded(self) -> None:
        result = BacktestEngine().run(make_demo_bars(bars=600), ema_strategy())
        self.assertEqual(
            monte_carlo_trades(result, runs=50, seed=123),
            monte_carlo_trades(result, runs=50, seed=123),
        )

    def test_portfolio_splits_and_recombines_capital(self) -> None:
        frames = {
            "EURUSD": make_demo_bars(bars=500, symbol="EURUSD"),
            "GBPUSD": make_demo_bars(bars=500, symbol="GBPUSD", seed=11),
        }
        result = PortfolioEngine().run(frames, ema_strategy())
        self.assertEqual(result.symbol, "PORTFOLIO")
        self.assertEqual(result.metrics["symbols"], 2.0)
        self.assertEqual(result.equity.index[0], frames["EURUSD"].index[0])


class IntegrationTests(unittest.TestCase):
    def test_exports_are_self_describing(self) -> None:
        strategy = ema_strategy()
        mql5 = export_mql5(strategy, BacktestConfig())
        config = export_strategy_json(strategy, BacktestConfig())
        self.assertIn("void OnTick()", mql5)
        self.assertIn("signal on closed bar", mql5)
        self.assertIn(strategy.strategy_id, config)

    def test_paper_refresh_persists_only_simulation_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "EURUSD.csv"
            make_demo_bars(bars=300).reset_index().to_csv(csv_path, index=False)
            simulator = PaperSimulator(root / "state.json", BacktestEngine())
            first = simulator.refresh(csv_path, ema_strategy(), symbol="EURUSD")
            second = simulator.refresh(csv_path, ema_strategy(), symbol="EURUSD")
            self.assertGreaterEqual(first.new_trades, 0)
            self.assertEqual(second.new_trades, 0)
            self.assertTrue((root / "state.json").exists())


if __name__ == "__main__":
    unittest.main()

