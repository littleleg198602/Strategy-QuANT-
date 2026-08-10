from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from . import __version__
from .data import (
    RESAMPLER_VERSION,
    read_mt5_csv,
    resample_canonical_bars,
    source_sha256,
)
from .data_catalog import DataCatalog
from .data_models import BrokerProfile, DatasetManifest, stable_id
from .data_quality import validate_canonical_bars, validate_canonical_ticks

if TYPE_CHECKING:
    from .mt5_data import MT5DataSource


class DataManager:
    """Application service shared by CLI and future UI data workflows."""

    def __init__(self, catalog: DataCatalog):
        self.catalog = catalog

    def import_file(
        self,
        source: str | Path,
        *,
        broker_profile: BrokerProfile,
        broker_symbol: str,
        timezone: str,
        timeframe: str = "M1",
        requested_start: str | None = None,
        requested_end: str | None = None,
    ) -> DatasetManifest:
        path = Path(source)
        instrument = broker_profile.instrument(broker_symbol)
        canonical = read_mt5_csv(
            path,
            timezone=timezone,
            timeframe=timeframe,
            wall_clock_offset_minutes=broker_profile.timezone_offset_minutes,
        )
        validated = validate_canonical_bars(canonical)
        start = requested_start or pd.Timestamp(validated.frame["open_ts_utc"].iloc[0]).isoformat()
        end = requested_end or pd.Timestamp(validated.frame["close_ts_utc"].iloc[-1]).isoformat()
        config = {
            "source_type": "mt5_csv",
            "timezone": timezone,
            "wall_clock_offset_minutes": broker_profile.timezone_offset_minutes,
            "timeframe": timeframe,
            "broker_symbol": broker_symbol,
            "requested_start": start,
            "requested_end": end,
        }
        return self.catalog.freeze(
            validated.frame,
            validated.report,
            source_type="mt5_csv",
            source_fingerprint=f"sha256:{source_sha256(path)}",
            instrument_id=instrument.instrument_id,
            broker_symbol=broker_symbol,
            broker_profile=broker_profile,
            datatype="bar",
            timeframe=timeframe.upper(),
            timestamp_convention="start_of_bar",
            source_timezone=timezone,
            requested_start=start,
            requested_end=end,
            import_config_hash=stable_id("ic", config),
            created_at=datetime.now(UTC).isoformat(),
            raw_content_hashes=(source_sha256(path),),
            software_version=__version__,
        )

    def import_canonical_frame(
        self,
        frame: pd.DataFrame,
        *,
        broker_profile: BrokerProfile,
        broker_symbol: str,
        datatype: str,
        timeframe: str,
        source_type: str,
        source_fingerprint: str,
        requested_start: str,
        requested_end: str,
        source_timezone: str = "UTC",
        extra: dict[str, Any] | None = None,
    ) -> DatasetManifest:
        instrument = broker_profile.instrument(broker_symbol)
        validated = (
            validate_canonical_bars(frame)
            if datatype == "bar"
            else validate_canonical_ticks(frame)
        )
        config = {
            "source_type": source_type,
            "datatype": datatype,
            "timeframe": timeframe,
            "broker_symbol": broker_symbol,
            "requested_start": requested_start,
            "requested_end": requested_end,
        }
        return self.catalog.freeze(
            validated.frame,
            validated.report,
            source_type=source_type,
            source_fingerprint=source_fingerprint,
            instrument_id=instrument.instrument_id,
            broker_symbol=broker_symbol,
            broker_profile=broker_profile,
            datatype=datatype,
            timeframe=timeframe,
            timestamp_convention="start_of_bar" if datatype == "bar" else "tick",
            source_timezone=source_timezone,
            requested_start=requested_start,
            requested_end=requested_end,
            import_config_hash=stable_id("ic", config),
            created_at=datetime.now(UTC).isoformat(),
            software_version=__version__,
            extra=extra,
        )

    def import_mt5(
        self,
        source: MT5DataSource,
        *,
        broker_profile: BrokerProfile,
        broker_symbol: str,
        datatype: str,
        start: datetime,
        end: datetime,
        minimum_coverage: float = 0.98,
    ) -> DatasetManifest:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("MT5 start/end must be timezone-aware")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        instrument = broker_profile.instrument(broker_symbol)
        if datatype == "bar":
            chunks = source.iter_m1(broker_symbol, start, end)
            timeframe = "M1"
            convention = "start_of_bar"
        elif datatype == "tick":
            chunks = source.iter_ticks(broker_symbol, start, end)
            timeframe = "TICK"
            convention = "tick"
        else:
            raise ValueError("datatype must be 'bar' or 'tick'")
        config = {
            "source_type": "mt5_direct",
            "datatype": datatype,
            "timeframe": timeframe,
            "broker_symbol": broker_symbol,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "minimum_coverage": minimum_coverage,
        }
        return self.catalog.freeze_stream(
            chunks,
            source_type="mt5_direct",
            source_fingerprint=broker_profile.source_fingerprint,
            instrument_id=instrument.instrument_id,
            broker_symbol=broker_symbol,
            broker_profile=broker_profile,
            datatype=datatype,
            timeframe=timeframe,
            timestamp_convention=convention,
            source_timezone="UTC",
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            import_config_hash=stable_id("ic", config),
            created_at=datetime.now(UTC).isoformat(),
            software_version=__version__,
            minimum_coverage=minimum_coverage,
            extra={"requested_by": "mt5_data_manager"},
        )

    def resample_dataset(
        self,
        dataset_id: str,
        *,
        timeframe: str,
        broker_profile: BrokerProfile,
        gap_policy: str = "session-expected",
    ) -> DatasetManifest:
        parent = self.catalog.get_manifest(dataset_id)
        if parent.datatype != "bar" or parent.timeframe != "M1":
            raise ValueError("Resampling source must be a canonical M1 bar dataset")
        frame = self.catalog.load(dataset_id)
        resampled = resample_canonical_bars(
            frame,
            timeframe=timeframe,
            broker_timezone=broker_profile.timezone,
            broker_offset_minutes=broker_profile.timezone_offset_minutes,
            gap_policy=gap_policy,  # type: ignore[arg-type]
        )
        validated = validate_canonical_bars(resampled)
        config = {
            "parent": dataset_id,
            "timeframe": timeframe.upper(),
            "broker_timezone": broker_profile.timezone,
            "broker_offset_minutes": broker_profile.timezone_offset_minutes,
            "gap_policy": gap_policy,
            "resampler_version": RESAMPLER_VERSION,
        }
        instrument = broker_profile.instrument(parent.broker_symbol)
        return self.catalog.freeze(
            validated.frame,
            validated.report,
            source_type="resample",
            source_fingerprint=f"dataset:{dataset_id}",
            instrument_id=instrument.instrument_id,
            broker_symbol=parent.broker_symbol,
            broker_profile=broker_profile,
            datatype="bar",
            timeframe=timeframe.upper(),
            timestamp_convention="start_of_bar",
            source_timezone=broker_profile.timezone,
            requested_start=parent.first_timestamp,
            requested_end=parent.last_timestamp,
            import_config_hash=stable_id("ic", config),
            created_at=datetime.now(UTC).isoformat(),
            software_version=__version__,
            resampling_parent=dataset_id,
            resampler_version=RESAMPLER_VERSION,
        )
