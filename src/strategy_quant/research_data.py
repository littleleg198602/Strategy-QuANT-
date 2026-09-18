from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .data import canonical_bars_to_engine_frame
from .data_catalog import DataCatalog
from .data_models import DatasetManifest


@dataclass(frozen=True)
class ResearchDataset:
    """A quality-approved catalog dataset prepared for the backtest engine."""

    manifest: DatasetManifest
    frame: pd.DataFrame

    def provenance(self) -> dict[str, str | int]:
        return {
            "dataset_id": self.manifest.dataset_id,
            "symbol": self.manifest.broker_symbol,
            "timeframe": self.manifest.timeframe,
            "quality": self.manifest.quality_status,
            "rows": self.manifest.row_count,
            "from": self.manifest.first_timestamp,
            "to": self.manifest.last_timestamp,
            "canonical_hash": self.manifest.canonical_hash,
        }


def available_research_datasets(catalog: DataCatalog) -> list[DatasetManifest]:
    """Return only immutable, quality-approved bar datasets suitable for research."""

    return [
        manifest
        for manifest in catalog.list_manifests()
        if manifest.datatype == "bar" and manifest.quality_status == "PASS"
    ]


def load_research_dataset(catalog: DataCatalog, dataset_id: str) -> ResearchDataset:
    """Load one approved bar dataset and convert it into the engine input contract."""

    manifest = catalog.get_manifest(dataset_id)
    if manifest.datatype != "bar":
        raise ValueError(f"Dataset {dataset_id} contains ticks, not backtest bars")
    if manifest.quality_status != "PASS":
        raise ValueError(
            f"Dataset {dataset_id} has quality {manifest.quality_status}; only PASS data can run research"
        )
    canonical = catalog.load(dataset_id)
    frame = canonical_bars_to_engine_frame(canonical, symbol=manifest.broker_symbol)
    return ResearchDataset(manifest=manifest, frame=frame)
