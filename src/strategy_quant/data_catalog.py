from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import uuid
from collections.abc import Iterable
from dataclasses import fields
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_models import BrokerProfile, DatasetManifest, QualityIssue, QualityReport, stable_json
from .data_quality import (
    BAR_COLUMNS,
    TICK_COLUMNS,
    validate_canonical_bars,
    validate_canonical_ticks,
)

CATALOG_SCHEMA_VERSION = "1"


class CanonicalHasher:
    """Incremental hash whose result is independent of source chunk sizes."""

    def __init__(self, datatype: str):
        self.datatype = datatype
        self.columns = BAR_COLUMNS if datatype == "bar" else TICK_COLUMNS
        self._column_hashes = {column: hashlib.sha256() for column in self.columns}

    def update(self, frame: pd.DataFrame) -> None:
        missing = set(self.columns) - set(frame.columns)
        if missing:
            raise ValueError(f"Cannot hash frame with missing columns: {', '.join(sorted(missing))}")
        for column in self.columns:
            self._update_column(self._column_hashes[column], frame[column])

    @staticmethod
    def _update_column(digest: Any, series: pd.Series) -> None:
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            timestamps = pd.to_datetime(series, utc=True)
            values = timestamps.array.as_unit("ns").asi8.astype(">i8", copy=False)
            digest.update(values.tobytes())
        elif pd.api.types.is_bool_dtype(series.dtype):
            digest.update(series.fillna(False).to_numpy(dtype=np.uint8).tobytes())
        elif pd.api.types.is_integer_dtype(series.dtype):
            encoded = np.empty(len(series), dtype=[("missing", "u1"), ("value", ">i8")])
            encoded["missing"] = series.isna().to_numpy(dtype=np.uint8)
            encoded["value"] = series.fillna(np.iinfo(np.int64).min).to_numpy(dtype=">i8")
            digest.update(encoded.tobytes())
        elif pd.api.types.is_numeric_dtype(series.dtype):
            encoded = np.empty(len(series), dtype=[("missing", "u1"), ("value", ">f8")])
            encoded["missing"] = series.isna().to_numpy(dtype=np.uint8)
            encoded["value"] = series.fillna(0.0).to_numpy(dtype=">f8")
            digest.update(encoded.tobytes())
        else:
            for value in series:
                encoded = b"" if pd.isna(value) else str(value).encode("utf-8")
                digest.update(struct.pack(">I", len(encoded)) + encoded)

    def hexdigest(self) -> str:
        digest = hashlib.sha256()
        digest.update(f"strategy-quant:{CATALOG_SCHEMA_VERSION}:{self.datatype}\n".encode())
        for column in self.columns:
            digest.update(column.encode("utf-8") + b"\0")
            digest.update(self._column_hashes[column].digest())
        return digest.hexdigest()


def canonical_content_hash(frame: pd.DataFrame, *, datatype: str) -> str:
    """Hash canonical values independently of Parquet writer metadata."""

    hasher = CanonicalHasher(datatype)
    hasher.update(frame)
    return hasher.hexdigest()


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.") or "unknown"


class DataCatalog:
    """Immutable local Parquet datasets with a small SQLite index."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.datasets_root = self.root / "datasets"
        self.profiles_root = self.root / "profiles"
        self.temporary_root = self.root / ".tmp"
        for directory in (self.datasets_root, self.profiles_root, self.temporary_root):
            directory.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "catalog.sqlite3"
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    broker_symbol TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    datatype TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    first_timestamp TEXT NOT NULL,
                    last_timestamp TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    manifest_path TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_datasets_symbol
                    ON datasets(broker_symbol, timeframe, created_at);
                CREATE TABLE IF NOT EXISTS profiles (
                    profile_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    broker_id TEXT NOT NULL,
                    account_currency TEXT NOT NULL,
                    path TEXT NOT NULL,
                    PRIMARY KEY(profile_id, version)
                );
                """
            )

    def save_profile(self, profile: BrokerProfile) -> Path:
        directory = self.profiles_root / _safe_component(profile.profile_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{profile.version}.json"
        content = stable_json(profile.to_dict()) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise ValueError(f"Immutable broker profile collision at {path}")
        if not path.exists():
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO profiles VALUES (?, ?, ?, ?, ?)",
                (
                    profile.profile_id,
                    profile.version,
                    profile.broker_id,
                    profile.account_currency,
                    str(path.relative_to(self.root)),
                ),
            )
        return path

    def freeze(
        self,
        frame: pd.DataFrame,
        report: QualityReport,
        *,
        source_type: str,
        source_fingerprint: str,
        instrument_id: str,
        broker_symbol: str,
        broker_profile: BrokerProfile,
        datatype: str,
        timeframe: str,
        timestamp_convention: str,
        source_timezone: str,
        requested_start: str,
        requested_end: str,
        import_config_hash: str,
        created_at: str,
        raw_content_hashes: Iterable[str] = (),
        software_version: str = "unknown",
        resampling_parent: str | None = None,
        resampler_version: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DatasetManifest:
        if report.status == "FAIL":
            raise ValueError("A failed quality report cannot be frozen")
        canonical_hash = canonical_content_hash(frame, datatype=datatype)
        label = _safe_component(f"{broker_symbol}-{timeframe}").lower()
        dataset_id = f"{label}-{canonical_hash[:16]}"
        final_directory = self.datasets_root / dataset_id
        if final_directory.exists():
            existing = self.get_manifest(dataset_id)
            if existing.canonical_hash != canonical_hash:
                raise ValueError(f"Immutable dataset ID collision for {dataset_id}")
            return existing

        self.save_profile(broker_profile)
        temporary = self.temporary_root / f"{dataset_id}-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True)
        try:
            partitions = self._write_partitions(frame, datatype=datatype, destination=temporary)
            timestamp_column = "open_ts_utc" if datatype == "bar" else "ts_utc"
            first = pd.Timestamp(frame[timestamp_column].iloc[0]).isoformat()
            last = pd.Timestamp(frame[timestamp_column].iloc[-1]).isoformat()
            manifest = DatasetManifest(
                dataset_id=dataset_id,
                schema_version=CATALOG_SCHEMA_VERSION,
                source_type=source_type,
                source_fingerprint=source_fingerprint,
                instrument_id=instrument_id,
                broker_symbol=broker_symbol,
                broker_profile_id=broker_profile.profile_id,
                broker_profile_version=broker_profile.version,
                datatype=datatype,  # type: ignore[arg-type]
                timeframe=timeframe,
                timestamp_convention=timestamp_convention,  # type: ignore[arg-type]
                source_timezone=source_timezone,
                requested_start=requested_start,
                requested_end=requested_end,
                first_timestamp=first,
                last_timestamp=last,
                row_count=len(frame),
                canonical_hash=canonical_hash,
                import_config_hash=import_config_hash,
                quality_report_id=report.report_id,
                quality_status=report.status,
                created_at=created_at,
                partitions=tuple(partitions),
                raw_content_hashes=tuple(raw_content_hashes),
                software_version=software_version,
                resampling_parent=resampling_parent,
                resampler_version=resampler_version,
                extra=extra or {},
            )
            (temporary / "manifest.json").write_text(
                json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (temporary / "quality.json").write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, final_directory)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    manifest.dataset_id,
                    manifest.broker_symbol,
                    manifest.instrument_id,
                    manifest.datatype,
                    manifest.timeframe,
                    manifest.canonical_hash,
                    manifest.quality_status,
                    manifest.first_timestamp,
                    manifest.last_timestamp,
                    manifest.row_count,
                    manifest.created_at,
                    str((final_directory / "manifest.json").relative_to(self.root)),
                ),
            )
        return manifest

    def freeze_stream(
        self,
        chunks: Iterable[pd.DataFrame],
        *,
        source_type: str,
        source_fingerprint: str,
        instrument_id: str,
        broker_symbol: str,
        broker_profile: BrokerProfile,
        datatype: str,
        timeframe: str,
        timestamp_convention: str,
        source_timezone: str,
        requested_start: str,
        requested_end: str,
        import_config_hash: str,
        created_at: str,
        software_version: str = "unknown",
        minimum_coverage: float = 0.98,
        extra: dict[str, Any] | None = None,
    ) -> DatasetManifest:
        """Validate, hash and persist an ordered stream without retaining it in memory."""

        temporary = self.temporary_root / f"stream-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True)
        timestamp_column = "open_ts_utc" if datatype == "bar" else "ts_utc"
        hasher = CanonicalHasher(datatype)
        partitions: list[str] = []
        issues: list[QualityIssue] = []
        input_rows = 0
        output_rows = 0
        first_timestamp: str | None = None
        last_timestamp: str | None = None
        last_row: pd.Series | None = None
        try:
            for sequence, chunk in enumerate(chunks):
                input_rows += len(chunk)
                validated = (
                    validate_canonical_bars(chunk)
                    if datatype == "bar"
                    else validate_canonical_ticks(chunk)
                )
                current = validated.frame
                issues.extend(validated.report.issues)
                if current.empty:
                    continue
                if last_row is not None:
                    first_key: tuple[Any, ...] = (pd.Timestamp(current[timestamp_column].iloc[0]),)
                    previous_key: tuple[Any, ...] = (pd.Timestamp(last_row[timestamp_column]),)
                    if datatype == "tick":
                        first_key += (int(current["source_seq"].iloc[0]),)
                        previous_key += (int(last_row["source_seq"]),)
                    if first_key < previous_key:
                        raise ValueError("Stream chunks overlap out of timestamp order")
                    if first_key == previous_key:
                        comparable = current.iloc[0].copy()
                        equal = all(
                            (pd.isna(comparable[name]) and pd.isna(last_row[name]))
                            or comparable[name] == last_row[name]
                            for name in current.columns
                        )
                        if not equal:
                            raise ValueError("Conflicting rows found at a stream chunk boundary")
                        current = current.iloc[1:].reset_index(drop=True)
                        issues.append(
                            QualityIssue("Q04", "WARN", "Duplicate stream-boundary row removed")
                        )
                if current.empty:
                    continue
                if first_timestamp is None:
                    first_timestamp = pd.Timestamp(current[timestamp_column].iloc[0]).isoformat()
                last_timestamp = pd.Timestamp(current[timestamp_column].iloc[-1]).isoformat()
                last_row = current.iloc[-1].copy()
                hasher.update(current)
                output_rows += len(current)
                partition = self._write_stream_chunk(
                    current,
                    datatype=datatype,
                    destination=temporary,
                    sequence=sequence,
                )
                partitions.append(partition)
            if output_rows == 0 or first_timestamp is None or last_timestamp is None:
                raise ValueError("MT5 returned no canonical rows in the requested range")
            requested_span = pd.Timestamp(requested_end) - pd.Timestamp(requested_start)
            actual_span = pd.Timestamp(last_timestamp) - pd.Timestamp(first_timestamp)
            coverage = 1.0 if requested_span <= pd.Timedelta(0) else actual_span / requested_span
            if coverage < minimum_coverage:
                issues.append(
                    QualityIssue(
                        "Q14",
                        "FAIL",
                        f"History coverage {coverage:.2%} is below required {minimum_coverage:.2%}",
                    )
                )
            report = QualityReport.build(
                datatype=datatype,  # type: ignore[arg-type]
                row_count_input=input_rows,
                row_count_output=output_rows,
                issues=issues,
                created_at=created_at,
            )
            if report.status == "FAIL":
                raise ValueError("Stream failed the data quality gate")
            canonical_hash = hasher.hexdigest()
            label = _safe_component(f"{broker_symbol}-{timeframe}").lower()
            dataset_id = f"{label}-{canonical_hash[:16]}"
            final_directory = self.datasets_root / dataset_id
            if final_directory.exists():
                shutil.rmtree(temporary, ignore_errors=True)
                return self.get_manifest(dataset_id)
            manifest = DatasetManifest(
                dataset_id=dataset_id,
                schema_version=CATALOG_SCHEMA_VERSION,
                source_type=source_type,
                source_fingerprint=source_fingerprint,
                instrument_id=instrument_id,
                broker_symbol=broker_symbol,
                broker_profile_id=broker_profile.profile_id,
                broker_profile_version=broker_profile.version,
                datatype=datatype,  # type: ignore[arg-type]
                timeframe=timeframe,
                timestamp_convention=timestamp_convention,  # type: ignore[arg-type]
                source_timezone=source_timezone,
                requested_start=requested_start,
                requested_end=requested_end,
                first_timestamp=first_timestamp,
                last_timestamp=last_timestamp,
                row_count=output_rows,
                canonical_hash=canonical_hash,
                import_config_hash=import_config_hash,
                quality_report_id=report.report_id,
                quality_status=report.status,
                created_at=created_at,
                partitions=tuple(partitions),
                software_version=software_version,
                extra=extra or {},
            )
            (temporary / "manifest.json").write_text(
                json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (temporary / "quality.json").write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.save_profile(broker_profile)
            os.replace(temporary, final_directory)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        self._register_manifest(manifest, final_directory)
        return manifest

    def _register_manifest(self, manifest: DatasetManifest, directory: Path) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO datasets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    manifest.dataset_id,
                    manifest.broker_symbol,
                    manifest.instrument_id,
                    manifest.datatype,
                    manifest.timeframe,
                    manifest.canonical_hash,
                    manifest.quality_status,
                    manifest.first_timestamp,
                    manifest.last_timestamp,
                    manifest.row_count,
                    manifest.created_at,
                    str((directory / "manifest.json").relative_to(self.root)),
                ),
            )

    def _write_stream_chunk(
        self,
        frame: pd.DataFrame,
        *,
        datatype: str,
        destination: Path,
        sequence: int,
    ) -> str:
        timestamp_column = "open_ts_utc" if datatype == "bar" else "ts_utc"
        first = pd.Timestamp(frame[timestamp_column].iloc[0])
        prefix = f"date={first:%Y-%m-%d}" if datatype == "tick" else f"month={first:%Y-%m}"
        partition = destination / prefix / f"part-{sequence:06d}.parquet"
        partition.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(partition, index=False, engine="pyarrow")
        return str(partition.relative_to(destination))

    def _write_partitions(
        self, frame: pd.DataFrame, *, datatype: str, destination: Path
    ) -> list[str]:
        timestamp_column = "open_ts_utc" if datatype == "bar" else "ts_utc"
        timestamps = pd.to_datetime(frame[timestamp_column], utc=True)
        if datatype == "tick":
            keys = timestamps.dt.strftime("%Y-%m-%d")
            prefix = "date"
        else:
            keys = timestamps.dt.strftime("%Y-%m")
            prefix = "month"
        partitions: list[str] = []
        for key in sorted(keys.unique()):
            partition = destination / f"{prefix}={key}" / "data.parquet"
            partition.parent.mkdir(parents=True, exist_ok=True)
            frame.loc[keys == key].to_parquet(partition, index=False, engine="pyarrow")
            partitions.append(str(partition.relative_to(destination)))
        return partitions

    def get_manifest(self, dataset_id: str) -> DatasetManifest:
        path = self.datasets_root / _safe_component(dataset_id) / "manifest.json"
        if not path.exists():
            raise KeyError(f"Unknown dataset {dataset_id!r}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["partitions"] = tuple(payload.get("partitions", ()))
        payload["raw_content_hashes"] = tuple(payload.get("raw_content_hashes", ()))
        allowed = {item.name for item in fields(DatasetManifest)}
        return DatasetManifest(**{key: value for key, value in payload.items() if key in allowed})

    def load(self, dataset_id: str, *, allow_non_pass: bool = False) -> pd.DataFrame:
        manifest = self.get_manifest(dataset_id)
        if manifest.quality_status != "PASS" and not allow_non_pass:
            raise ValueError(
                f"Dataset {dataset_id} quality is {manifest.quality_status}; "
                "use an explicit diagnostic override to load it"
            )
        root = self.datasets_root / dataset_id
        parts = [pd.read_parquet(root / partition, engine="pyarrow") for partition in manifest.partitions]
        if not parts:
            raise ValueError(f"Dataset {dataset_id} has no partitions")
        frame = pd.concat(parts, ignore_index=True)
        timestamp_column = "open_ts_utc" if manifest.datatype == "bar" else "ts_utc"
        frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True)
        return frame.sort_values(timestamp_column, kind="stable").reset_index(drop=True)

    def list_manifests(self) -> list[DatasetManifest]:
        with self._connect() as connection:
            identifiers = [row["dataset_id"] for row in connection.execute(
                "SELECT dataset_id FROM datasets ORDER BY created_at DESC, dataset_id"
            )]
        return [self.get_manifest(identifier) for identifier in identifiers]
