from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .data import load_mt5_csv
from .demo import make_demo_bars
from .engine import BacktestEngine
from .exporter import write_export_bundle
from .filtering import MetricFilter
from .generator import generate_candidates
from .research import results_frame, run_research


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="strategy-quant")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="Run the end-to-end engine on deterministic data")
    demo.add_argument("--bars", type=int, default=1_500)
    demo.add_argument("--export", type=Path)
    research = subparsers.add_parser("research", help="Research strategies on an MT5 CSV")
    research.add_argument("csv", type=Path, nargs="+")
    research.add_argument("--symbol")
    research.add_argument("--timezone", default="UTC")
    research.add_argument("--limit", type=int, default=20)
    research.add_argument("--export", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    frame = make_demo_bars(bars=args.bars) if args.command == "demo" else None
    if args.command == "research" and len(args.csv) > 1:
        from .portfolio import PortfolioEngine, rank_portfolio_candidates

        frames = {
            path.stem.upper(): load_mt5_csv(
                path, symbol=args.symbol or path.stem.upper(), timezone=args.timezone
            )
            for path in args.csv
        }
        portfolio_engine = PortfolioEngine()
        results = rank_portfolio_candidates(
            frames, generate_candidates()[: args.limit], portfolio_engine
        )
        table = pd.DataFrame(
            [{"strategy_id": item.strategy.strategy_id, **item.metrics} for item in results]
        )
        columns = ["strategy_id", "total_return", "max_drawdown", "profit_factor", "trades"]
        print(table[columns].head(10).to_string(index=False))
        if args.export:
            json_path, mq5_path = write_export_bundle(
                args.export, results[0].strategy, portfolio_engine.config
            )
            print(f"Exported {json_path} and {mq5_path}")
        return 0
    if args.command == "research":
        frame = load_mt5_csv(
            args.csv[0], symbol=args.symbol, timezone=args.timezone
        )
    engine = BacktestEngine()
    evaluations = run_research(
        frame,  # type: ignore[arg-type]
        generate_candidates()[: args.limit] if hasattr(args, "limit") else generate_candidates(),
        engine,
        metric_filter=MetricFilter(min_trades=5),
        robustness_top_n=3,
        monte_carlo_runs=100,
    )
    table = results_frame(evaluations)
    columns = ["strategy_id", "accepted", "total_return", "max_drawdown", "profit_factor", "trades"]
    print(table[columns].head(10).to_string(index=False))
    if args.export:
        json_path, mq5_path = write_export_bundle(
            args.export, evaluations[0].result.strategy, engine.config
        )
        print(f"Exported {json_path} and {mq5_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
