from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from strategy_quant.data import read_mt5_csv, resample_canonical_bars
from strategy_quant.data_catalog import CanonicalHasher, DataCatalog, canonical_content_hash
from strategy_quant.data_manager import DataManager
from strategy_quant.data_models import BrokerProfile, InstrumentSpec
from strategy_quant.data_quality import (
    DataQualityError,
    validate_canonical_bars,
    validate_canonical_ticks,
)
from strategy_quant.mt5_data import MT5DataSource


def instrument(**changes: object) -> InstrumentSpec:
    base = InstrumentSpec(
        instrument_id="METAL.XAUUSD.CFD",
        asset_class="metal",
        broker_symbol="XAUUSD",
        display_name="Gold / US Dollar",
        aliases=("GOLD",),
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        contract_size=100.0,
    )
    return replace(base, **changes)


def profile(**changes: object) -> BrokerProfile:
    base = BrokerProfile(
        profile_id="darwinex-zero-usd",
        broker_id="darwinex-zero",
        account_currency="USD",
        timezone="America/New_York",
        timezone_offset_minutes=420,
        source_fingerprint="mt5:test-fingerprint",
        instruments=(instrument(),),
        leverage=30,
        margin_mode=2,
    )
    return replace(base, **changes)


def bars(start: str, periods: int) -> pd.DataFrame:
    opens = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    values = 2_000 + np.arange(periods, dtype="float64") / 100
    return pd.DataFrame(
        {
            "open_ts_utc": opens,
            "close_ts_utc": opens + pd.Timedelta(minutes=1),
            "open": values,
            "high": values + 0.1,
            "low": values - 0.1,
            "close": values + 0.05,
            "tick_volume": np.full(periods, 100, dtype="int64"),
            "real_volume": np.full(periods, np.nan),
            "spread_points": np.full(periods, 12.0),
            "is_complete": np.full(periods, True),
            "session_id": np.full(periods, None),
        }
    )


class QualityGateTests(unittest.TestCase):
    def test_identical_duplicate_is_warned_and_conflict_is_rejected(self) -> None:
        source = bars("2026-01-02T00:00:00", 2)
        duplicate = pd.concat([source.iloc[[0]], source], ignore_index=True)
        validated = validate_canonical_bars(duplicate)
        self.assertEqual(validated.report.status, "WARN")
        self.assertEqual(len(validated.frame), 2)
        conflict = duplicate.copy()
        conflict.loc[0, "close"] += 0.01
        with self.assertRaisesRegex(DataQualityError, "Conflicting"):
            validate_canonical_bars(conflict)

    def test_crossed_tick_is_rejected(self) -> None:
        ticks = pd.DataFrame(
            {
                "ts_utc": [pd.Timestamp("2026-01-02T00:00:00Z")],
                "bid": [2.0],
                "ask": [1.9],
                "last": [np.nan],
                "volume": [1.0],
                "flags": [3],
                "source_seq": [0],
            }
        )
        with self.assertRaisesRegex(DataQualityError, "ask is below bid"):
            validate_canonical_ticks(ticks)

    def test_dst_ambiguity_is_never_silently_shifted(self) -> None:
        source = io.StringIO(
            "time,open,high,low,close\n"
            "2026-11-01 01:30:00,1,1.1,0.9,1\n"
        )
        with self.assertRaisesRegex(Exception, "ambiguous"):
            read_mt5_csv(source, timezone="America/New_York")

    def test_darwinex_server_wall_time_maps_to_official_utc_offset(self) -> None:
        source = io.StringIO(
            "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\n"
            "2026.07.01\t00:00:00\t2000\t2001\t1999\t2000.5\n"
        )
        frame = read_mt5_csv(
            source,
            timezone="America/New_York",
            wall_clock_offset_minutes=420,
        )
        self.assertEqual(frame["open_ts_utc"].iloc[0], pd.Timestamp("2026-06-30T21:00:00Z"))


class CatalogTests(unittest.TestCase):
    def test_canonical_hash_is_independent_of_stream_chunk_size(self) -> None:
        frame = bars("2026-01-02T00:00:00", 10)
        hasher = CanonicalHasher("bar")
        hasher.update(frame.iloc[:3])
        hasher.update(frame.iloc[3:])
        self.assertEqual(hasher.hexdigest(), canonical_content_hash(frame, datatype="bar"))

    def test_same_canonical_data_has_same_id_and_round_trips_through_parquet(self) -> None:
        frame = bars("2026-01-02T00:00:00", 5)
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = DataManager(DataCatalog(first_dir)).import_canonical_frame(
                frame,
                broker_profile=profile(),
                broker_symbol="XAUUSD",
                datatype="bar",
                timeframe="M1",
                source_type="fixture",
                source_fingerprint="fixture:one",
                requested_start="2026-01-02T00:00:00+00:00",
                requested_end="2026-01-02T00:05:00+00:00",
            )
            second = DataManager(DataCatalog(second_dir)).import_canonical_frame(
                frame.copy(),
                broker_profile=profile(),
                broker_symbol="XAUUSD",
                datatype="bar",
                timeframe="M1",
                source_type="fixture",
                source_fingerprint="fixture:two",
                requested_start="2026-01-02T00:00:00+00:00",
                requested_end="2026-01-02T00:05:00+00:00",
            )
            self.assertEqual(first.dataset_id, second.dataset_id)
            loaded = DataCatalog(first_dir).load(first.dataset_id)
            self.assertEqual(canonical_content_hash(loaded, datatype="bar"), first.canonical_hash)

    def test_broker_metadata_change_creates_a_new_profile_version(self) -> None:
        original = profile()
        changed = replace(original, instruments=(instrument(tick_size=0.1),))
        self.assertNotEqual(original.version, changed.version)

    def test_darwinex_daily_bucket_uses_new_york_close_boundary(self) -> None:
        frame = bars("2026-06-30T21:00:00", 24 * 60)
        result = resample_canonical_bars(
            frame,
            timeframe="D1",
            broker_timezone="America/New_York",
            broker_offset_minutes=420,
            gap_policy="reject",
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result["open_ts_utc"].iloc[0], pd.Timestamp("2026-06-30T21:00:00Z"))
        self.assertEqual(result["close_ts_utc"].iloc[0], pd.Timestamp("2026-07-01T21:00:00Z"))

    def test_csv_import_uses_profile_wall_clock_and_round_trips_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "XAUUSD.csv"
            source.write_text(
                "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\n"
                "2026.07.01\t00:00:00\t2000\t2001\t1999\t2000.5\n",
                encoding="utf-8",
            )
            catalog = DataCatalog(root / "catalog")
            manifest = DataManager(catalog).import_file(
                source,
                broker_profile=profile(),
                broker_symbol="XAUUSD",
                timezone="America/New_York",
            )
            loaded = catalog.load(manifest.dataset_id)
            self.assertEqual(loaded["open_ts_utc"].iloc[0], pd.Timestamp("2026-06-30T21:00:00Z"))


class FakeMT5:
    TIMEFRAME_M1 = 1
    COPY_TICKS_ALL = -1

    def __init__(self) -> None:
        self.connected = False
        self.order_calls = 0

    def initialize(self, **_: object) -> bool:
        self.connected = True
        return True

    def shutdown(self) -> None:
        self.connected = False

    def last_error(self) -> tuple[int, str]:
        return (0, "ok")

    def symbols_get(self) -> tuple[SimpleNamespace, ...]:
        return (SimpleNamespace(name="XAUUSD"),)

    def terminal_info(self) -> SimpleNamespace:
        return SimpleNamespace(company="Darwinex", name="MT5", build=6000, path="C:/MT5")

    def account_info(self) -> SimpleNamespace:
        return SimpleNamespace(
            login=123456,
            server="DarwinexZero-MT5",
            currency="USD",
            leverage=30,
            margin_mode=2,
        )

    def symbol_info(self, _: str) -> SimpleNamespace:
        return SimpleNamespace(
            description="Gold / US Dollar",
            currency_base="XAU",
            currency_profit="USD",
            digits=2,
            point=0.01,
            trade_tick_size=0.01,
            trade_tick_value=1.0,
            trade_contract_size=100.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_stops_level=0,
            trade_freeze_level=0,
            trade_mode=4,
            filling_mode=1,
            order_mode=127,
            swap_long=-1.0,
            swap_short=0.5,
            swap_rollover3days=3,
        )

    def copy_rates_range(self, *_: object) -> list[dict[str, float | int]]:
        start = int(pd.Timestamp("2026-01-02T00:00:00Z").timestamp())
        return [
            {
                "time": start + minute * 60,
                "open": 2000 + minute,
                "high": 2001 + minute,
                "low": 1999 + minute,
                "close": 2000.5 + minute,
                "tick_volume": 100,
                "spread": 12,
                "real_volume": 0,
            }
            for minute in range(3)
        ]

    def copy_ticks_range(self, *_: object) -> list[dict[str, float | int]]:
        return []

    def order_send(self, *_: object) -> None:
        self.order_calls += 1
        raise AssertionError("Data collector must never send orders")


class MT5ReadOnlyTests(unittest.TestCase):
    def test_direct_collector_streams_bars_without_any_order_call(self) -> None:
        fake = FakeMT5()
        template = instrument(digits=None, tick_size=None, tick_value=None)
        with tempfile.TemporaryDirectory() as directory, MT5DataSource(module=fake) as source:
            broker = source.build_broker_profile(
                profile_id="darwinex-zero-usd",
                broker_id="darwinex-zero",
                account_currency="USD",
                timezone="America/New_York",
                timezone_offset_minutes=420,
                instruments=(template,),
            )
            catalog = DataCatalog(directory)
            manifest = DataManager(catalog).import_mt5(
                source,
                broker_profile=broker,
                broker_symbol="XAUUSD",
                datatype="bar",
                start=datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
                end=datetime(2026, 1, 2, 0, 2, tzinfo=UTC),
                minimum_coverage=0.0,
            )
            loaded = catalog.load(manifest.dataset_id)
            self.assertEqual(canonical_content_hash(loaded, datatype="bar"), manifest.canonical_hash)
        self.assertEqual(manifest.row_count, 2)
        self.assertEqual(manifest.quality_status, "PASS")
        self.assertEqual(fake.order_calls, 0)

    def test_reference_config_records_the_approved_universe(self) -> None:
        config = json.loads(Path("config/darwinex_zero_usd.json").read_text(encoding="utf-8"))
        self.assertEqual(config["account_currency"], "USD")
        self.assertEqual(config["history"], {"m1_years": 5, "tick_years": 1, "minimum_coverage": 0.98})
        self.assertEqual(
            [item["broker_symbol"] for item in config["instruments"]],
            ["XAUUSD", "US500", "NAS100", "GER40", "US30"],
        )


if __name__ == "__main__":
    unittest.main()
