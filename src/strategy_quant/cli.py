from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .data import load_mt5_csv
from .data_catalog import DataCatalog
from .data_manager import DataManager
from .data_models import BrokerProfile, InstrumentSpec, broker_profile_from_dict
from .data_quality import validate_canonical_bars, validate_canonical_ticks
from .demo import make_demo_bars
from .engine import BacktestEngine
from .exporter import write_export_bundle
from .filtering import MetricFilter
from .generator import generate_candidates
from .mt5_data import MT5DataSource, discover_mt5_terminals
from .research import results_frame, run_research

DEFAULT_DATA_CONFIG = Path("config/darwinex_zero_usd.json")


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
    _add_data_parser(subparsers)
    return parser


def _add_data_parser(subparsers: Any) -> None:
    data = subparsers.add_parser("data", help="Import, validate and catalog MT5 history")
    commands = data.add_subparsers(dest="data_command", required=True)

    commands.add_parser("terminals", help="Discover local Windows MT5 terminals")

    profile = commands.add_parser("profile-mt5", help="Capture a versioned read-only broker profile")
    profile.add_argument("--terminal", type=Path)
    profile.add_argument("--config", type=Path, default=DEFAULT_DATA_CONFIG)
    profile.add_argument("--catalog", type=Path, default=Path("data/catalog"))

    direct = commands.add_parser("mt5-import", help="Stream M1 bars or ticks from local MT5")
    direct.add_argument("--terminal", type=Path)
    direct.add_argument("--config", type=Path, default=DEFAULT_DATA_CONFIG)
    direct.add_argument("--catalog", type=Path, default=Path("data/catalog"))
    direct.add_argument("--symbol", action="append", help="Repeat for multiple symbols; default is all")
    direct.add_argument("--kind", choices=("m1", "ticks"), required=True)
    direct.add_argument("--start", help="ISO-8601 UTC; defaults to configured retention")
    direct.add_argument("--end", help="ISO-8601 UTC; defaults to now")

    file_import = commands.add_parser("import-file", help="Import an MT5 CSV/TSV export")
    file_import.add_argument("source", type=Path)
    file_import.add_argument("--profile", type=Path, required=True)
    file_import.add_argument("--symbol", required=True, help="Exact broker symbol from the profile")
    file_import.add_argument("--timezone", help="Override profile IANA timezone")
    file_import.add_argument("--timeframe", default="M1")
    file_import.add_argument("--catalog", type=Path, default=Path("data/catalog"))

    listing = commands.add_parser("list", help="List local immutable datasets")
    listing.add_argument("--catalog", type=Path, default=Path("data/catalog"))

    show = commands.add_parser("show", help="Show one dataset manifest")
    show.add_argument("dataset_id")
    show.add_argument("--catalog", type=Path, default=Path("data/catalog"))

    validate = commands.add_parser("validate", help="Re-run the quality gate")
    validate.add_argument("dataset_id")
    validate.add_argument("--catalog", type=Path, default=Path("data/catalog"))

    resample = commands.add_parser("resample", help="Create an immutable timeframe from M1")
    resample.add_argument("dataset_id")
    resample.add_argument("--profile", type=Path, required=True)
    resample.add_argument("--timeframe", choices=("M5", "M15", "M30", "H1", "H4", "D1"), required=True)
    resample.add_argument(
        "--gap-policy",
        choices=("reject", "keep-with-flag", "session-expected"),
        default="session-expected",
    )
    resample.add_argument("--catalog", type=Path, default=Path("data/catalog"))

    diff = commands.add_parser("diff", help="Compare two immutable manifests")
    diff.add_argument("first")
    diff.add_argument("second")
    diff.add_argument("--catalog", type=Path, default=Path("data/catalog"))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "data":
        return _run_data_command(args)
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
        frame = load_mt5_csv(args.csv[0], symbol=args.symbol, timezone=args.timezone)
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


def _run_data_command(args: argparse.Namespace) -> int:
    if args.data_command == "terminals":
        terminals = discover_mt5_terminals()
        print("\n".join(str(path) for path in terminals) if terminals else "No MT5 terminal found")
        return 0
    catalog = DataCatalog(args.catalog)
    manager = DataManager(catalog)
    if args.data_command == "profile-mt5":
        config, templates = _load_data_config(args.config)
        with MT5DataSource(args.terminal) as source:
            profile = _build_profile(source, config, templates)
        path = catalog.save_profile(profile)
        print(json.dumps({"profile": str(path), "version": profile.version}, indent=2))
        return 0
    if args.data_command == "mt5-import":
        config, templates = _load_data_config(args.config)
        selected = _select_templates(templates, args.symbol)
        end = _parse_utc(args.end) if args.end else datetime.now(UTC)
        years = config["history"]["m1_years" if args.kind == "m1" else "tick_years"]
        start = _parse_utc(args.start) if args.start else (pd.Timestamp(end) - pd.DateOffset(years=years)).to_pydatetime()
        with MT5DataSource(args.terminal) as source:
            profile = _build_profile(source, config, templates)
            manifests = []
            for template in selected:
                actual = next(
                    item for item in profile.instruments if item.instrument_id == template.instrument_id
                )
                manifests.append(
                    manager.import_mt5(
                        source,
                        broker_profile=profile,
                        broker_symbol=actual.broker_symbol,
                        datatype="bar" if args.kind == "m1" else "tick",
                        start=start,
                        end=end,
                        minimum_coverage=float(config["history"].get("minimum_coverage", 0.98)),
                    )
                )
        print(json.dumps([manifest.to_dict() for manifest in manifests], indent=2))
        return 0
    if args.data_command == "import-file":
        profile = _load_profile(args.profile)
        manifest = manager.import_file(
            args.source,
            broker_profile=profile,
            broker_symbol=args.symbol,
            timezone=args.timezone or profile.timezone,
            timeframe=args.timeframe,
        )
        print(json.dumps(manifest.to_dict(), indent=2))
        return 0
    if args.data_command == "list":
        rows = [
            {
                "dataset_id": item.dataset_id,
                "symbol": item.broker_symbol,
                "timeframe": item.timeframe,
                "quality": item.quality_status,
                "rows": item.row_count,
                "first": item.first_timestamp,
                "last": item.last_timestamp,
            }
            for item in catalog.list_manifests()
        ]
        print(pd.DataFrame(rows).to_string(index=False) if rows else "No datasets")
        return 0
    if args.data_command == "show":
        print(json.dumps(catalog.get_manifest(args.dataset_id).to_dict(), indent=2))
        return 0
    if args.data_command == "validate":
        manifest = catalog.get_manifest(args.dataset_id)
        frame = catalog.load(args.dataset_id, allow_non_pass=True)
        validated = (
            validate_canonical_bars(frame, raise_on_fail=False)
            if manifest.datatype == "bar"
            else validate_canonical_ticks(frame, raise_on_fail=False)
        )
        print(json.dumps(validated.report.to_dict(), indent=2))
        return 1 if validated.report.status == "FAIL" else 0
    if args.data_command == "resample":
        profile = _load_profile(args.profile)
        manifest = manager.resample_dataset(
            args.dataset_id,
            timeframe=args.timeframe,
            broker_profile=profile,
            gap_policy=args.gap_policy,
        )
        print(json.dumps(manifest.to_dict(), indent=2))
        return 0
    if args.data_command == "diff":
        first = catalog.get_manifest(args.first).to_dict()
        second = catalog.get_manifest(args.second).to_dict()
        differences = {
            key: {"first": first.get(key), "second": second.get(key)}
            for key in sorted(set(first) | set(second))
            if first.get(key) != second.get(key)
        }
        print(json.dumps(differences, indent=2))
        return 0
    raise AssertionError(f"Unhandled data command {args.data_command}")


def _load_data_config(path: Path) -> tuple[dict[str, Any], tuple[InstrumentSpec, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    templates = tuple(
        InstrumentSpec(
            instrument_id=item["instrument_id"],
            asset_class=item["asset_class"],
            broker_symbol=item["broker_symbol"],
            display_name=item["display_name"],
            aliases=tuple(item.get("aliases", ())),
        )
        for item in payload["instruments"]
    )
    return payload, templates


def _build_profile(
    source: MT5DataSource,
    config: dict[str, Any],
    templates: tuple[InstrumentSpec, ...],
) -> BrokerProfile:
    return source.build_broker_profile(
        profile_id=config["profile_id"],
        broker_id=config["broker_id"],
        account_currency=config["account_currency"],
        timezone=config["timezone"],
        timezone_offset_minutes=int(config.get("timezone_offset_minutes", 0)),
        instruments=templates,
    )


def _select_templates(
    templates: tuple[InstrumentSpec, ...], requested: list[str] | None
) -> tuple[InstrumentSpec, ...]:
    if not requested:
        return templates
    selected = [
        item
        for item in templates
        if any(
            name.casefold() in {item.broker_symbol.casefold(), *(alias.casefold() for alias in item.aliases)}
            for name in requested
        )
    ]
    if len(selected) != len({name.casefold() for name in requested}):
        raise ValueError("Every requested symbol must resolve to exactly one configured instrument")
    return tuple(selected)


def _load_profile(path: Path) -> BrokerProfile:
    return broker_profile_from_dict(json.loads(path.read_text(encoding="utf-8")))


def _parse_utc(value: str) -> datetime:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        raise ValueError("Date/time must include an explicit UTC offset, for example 2026-08-10T00:00:00Z")
    return parsed.tz_convert("UTC").to_pydatetime()


if __name__ == "__main__":
    raise SystemExit(main())
