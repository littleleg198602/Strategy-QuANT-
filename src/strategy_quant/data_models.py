from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

QualityStatus = Literal["PASS", "WARN", "FAIL"]
Severity = Literal["INFO", "WARN", "FAIL"]
AssetClass = Literal["forex", "index_cfd", "metal"]
DataType = Literal["tick", "bar"]


def stable_json(value: Any) -> str:
    """Serialize metadata in the canonical form used by all manifest hashes."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, value: Any, *, length: int = 16) -> str:
    digest = hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:length]}"


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    asset_class: AssetClass
    broker_symbol: str
    display_name: str
    aliases: tuple[str, ...] = ()
    base_currency: str | None = None
    quote_currency: str | None = None
    digits: int | None = None
    point: float | None = None
    tick_size: float | None = None
    tick_value: float | None = None
    contract_size: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    volume_step: float | None = None
    stops_level: int | None = None
    freeze_level: int | None = None
    trade_mode: int | None = None
    filling_mode: int | None = None
    order_mode: int | None = None
    swap_long: float | None = None
    swap_short: float | None = None
    triple_swap_day: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["aliases"] = list(self.aliases)
        return result


@dataclass(frozen=True)
class BrokerProfile:
    profile_id: str
    broker_id: str
    account_currency: str
    timezone: str
    timezone_offset_minutes: int
    source_fingerprint: str
    instruments: tuple[InstrumentSpec, ...]
    margin_mode: int | None = None
    leverage: int | None = None
    commission_model: str = "from_execution_or_external_config"
    spread_model: str = "historical_points"
    notes: str = ""

    def version_payload(self) -> dict[str, Any]:
        result = asdict(self)
        result["instruments"] = [instrument.to_dict() for instrument in self.instruments]
        return result

    @property
    def version(self) -> str:
        return stable_id("bp", self.version_payload())

    def to_dict(self) -> dict[str, Any]:
        return self.version_payload() | {"version": self.version}

    def instrument(self, broker_symbol: str) -> InstrumentSpec:
        matches = [item for item in self.instruments if item.broker_symbol == broker_symbol]
        if len(matches) != 1:
            raise ValueError(
                f"Broker symbol {broker_symbol!r} must resolve to exactly one instrument; "
                f"found {len(matches)}"
            )
        return matches[0]


def broker_profile_from_dict(payload: dict[str, Any]) -> BrokerProfile:
    instruments = tuple(
        InstrumentSpec(
            **(
                {key: value for key, value in item.items() if key != "aliases"}
                | {"aliases": tuple(item.get("aliases", ())) }
            )
        )
        for item in payload["instruments"]
    )
    accepted = {
        "profile_id",
        "broker_id",
        "account_currency",
        "timezone",
        "timezone_offset_minutes",
        "source_fingerprint",
        "margin_mode",
        "leverage",
        "commission_model",
        "spread_model",
        "notes",
    }
    values = {key: value for key, value in payload.items() if key in accepted}
    values.setdefault("timezone_offset_minutes", 0)
    return BrokerProfile(**values, instruments=instruments)


@dataclass(frozen=True)
class QualityIssue:
    check_id: str
    severity: Severity
    message: str
    count: int = 1
    samples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["samples"] = list(self.samples)
        return result


@dataclass(frozen=True)
class QualityReport:
    report_id: str
    status: QualityStatus
    datatype: DataType
    row_count_input: int
    row_count_output: int
    issues: tuple[QualityIssue, ...] = ()
    created_at: str = ""

    @classmethod
    def build(
        cls,
        *,
        datatype: DataType,
        row_count_input: int,
        row_count_output: int,
        issues: list[QualityIssue],
        created_at: str,
    ) -> QualityReport:
        status: QualityStatus = "PASS"
        if any(issue.severity == "FAIL" for issue in issues):
            status = "FAIL"
        elif any(issue.severity == "WARN" for issue in issues):
            status = "WARN"
        payload = {
            "datatype": datatype,
            "row_count_input": row_count_input,
            "row_count_output": row_count_output,
            "issues": [issue.to_dict() for issue in issues],
        }
        return cls(
            report_id=stable_id("qr", payload),
            status=status,
            datatype=datatype,
            row_count_input=row_count_input,
            row_count_output=row_count_output,
            issues=tuple(issues),
            created_at=created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["issues"] = [issue.to_dict() for issue in self.issues]
        return result


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    schema_version: str
    source_type: str
    source_fingerprint: str
    instrument_id: str
    broker_symbol: str
    broker_profile_id: str
    broker_profile_version: str
    datatype: DataType
    timeframe: str
    timestamp_convention: Literal["start_of_bar", "tick"]
    source_timezone: str
    requested_start: str
    requested_end: str
    first_timestamp: str
    last_timestamp: str
    row_count: int
    canonical_hash: str
    import_config_hash: str
    quality_report_id: str
    quality_status: QualityStatus
    created_at: str
    partitions: tuple[str, ...]
    raw_content_hashes: tuple[str, ...] = ()
    software_version: str = "unknown"
    resampling_parent: str | None = None
    resampler_version: str | None = None
    immutable: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["partitions"] = list(self.partitions)
        result["raw_content_hashes"] = list(self.raw_content_hashes)
        return result
