from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd

from strategy_quant.data_catalog import DataCatalog
from strategy_quant.data_manager import DataManager
from strategy_quant.data_models import BrokerProfile, DatasetManifest, InstrumentSpec
from strategy_quant.research_data import available_research_datasets, load_research_dataset


def profile() -> BrokerProfile:
    return BrokerProfile(
        profile_id="darwinex-zero-usd",
        broker_id="darwinex-zero",
        account_currency="USD",
        timezone="America/New_York",
        timezone_offset_minutes=420,
        source_fingerprint="mt5:test-fingerprint",
        instruments=(
            InstrumentSpec(
                instrument_id="METAL.XAUUSD.CFD",
                asset_class="metal",
                broker_symbol="XAUUSD",
                display_name="Gold / US Dollar",
            ),
        ),
    )


def bars() -> pd.DataFrame:
    opens = pd.date_range("2026-01-02T00:00:00Z", periods=3, freq="min")
    values = np.array([2000.0, 2001.0, 2002.0])
    return pd.DataFrame(
        {
            "open_ts_utc": opens,
            "close_ts_utc": opens + pd.Timedelta(minutes=1),
            "open": values,
            "high": values + 1.0,
            "low": values - 1.0,
            "close": values + 0.5,
            "tick_volume": [100, 110, 120],
            "real_volume": [np.nan, np.nan, np.nan],
            "spread_points": [10.0, 10.0, 11.0],
            "is_complete": [True, True, True],
            "session_id": [None, None, None],
        }
    )


class CatalogResearchDataTests(unittest.TestCase):
    def test_passed_catalog_dataset_is_loaded_as_engine_frame_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = DataCatalog(Path(directory) / "catalog")
            manifest = DataManager(catalog).import_canonical_frame(
                bars(),
                broker_profile=profile(),
                broker_symbol="XAUUSD",
                datatype="bar",
                timeframe="M1",
                source_type="fixture",
                source_fingerprint="fixture:xauusd",
                requested_start="2026-01-02T00:00:00+00:00",
                requested_end="2026-01-02T00:03:00+00:00",
            )

            self.assertEqual([item.dataset_id for item in available_research_datasets(catalog)], [manifest.dataset_id])
            research = load_research_dataset(catalog, manifest.dataset_id)

        self.assertEqual(research.frame["symbol"].unique().tolist(), ["XAUUSD"])
        self.assertEqual(str(research.frame.index.tz), "UTC")
        self.assertEqual(research.provenance()["canonical_hash"], manifest.canonical_hash)
        self.assertEqual(research.provenance()["rows"], 3)

    def test_ticks_and_non_pass_data_are_never_accepted_for_research(self) -> None:
        manifest = DatasetManifest(
            dataset_id="xauusd-ticks",
            schema_version="1",
            source_type="fixture",
            source_fingerprint="fixture",
            instrument_id="METAL.XAUUSD.CFD",
            broker_symbol="XAUUSD",
            broker_profile_id="darwinex-zero-usd",
            broker_profile_version="bp-fixture",
            datatype="tick",
            timeframe="TICK",
            timestamp_convention="tick",
            source_timezone="UTC",
            requested_start="2026-01-02T00:00:00+00:00",
            requested_end="2026-01-02T00:01:00+00:00",
            first_timestamp="2026-01-02T00:00:00+00:00",
            last_timestamp="2026-01-02T00:01:00+00:00",
            row_count=1,
            canonical_hash="hash",
            import_config_hash="config",
            quality_report_id="report",
            quality_status="PASS",
            created_at="2026-01-02T00:00:00+00:00",
            partitions=(),
        )
        catalog = Mock()
        catalog.list_manifests.return_value = [manifest, replace(manifest, datatype="bar", quality_status="WARN")]
        catalog.get_manifest.return_value = manifest

        self.assertEqual(available_research_datasets(catalog), [])
        with self.assertRaisesRegex(ValueError, "contains ticks"):
            load_research_dataset(catalog, manifest.dataset_id)
        catalog.load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
