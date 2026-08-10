from __future__ import annotations

import hashlib
import importlib
import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Self

import pandas as pd

from .data import canonicalize_mt5_rates, canonicalize_mt5_ticks
from .data_models import BrokerProfile, InstrumentSpec, stable_json


class MT5UnavailableError(RuntimeError):
    pass


def discover_mt5_terminals() -> list[Path]:
    """Find likely Windows terminal64.exe installations without starting them."""

    if sys.platform != "win32":
        return []
    roots = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    candidates: set[Path] = set()
    patterns = (
        "MetaTrader 5/terminal64.exe",
        "*/terminal64.exe",
        "Programs/*/terminal64.exe",
    )
    for raw_root in roots:
        if not raw_root:
            continue
        root = Path(raw_root)
        for pattern in patterns:
            candidates.update(path.resolve() for path in root.glob(pattern) if path.is_file())
    return sorted(candidates)


class MT5DataSource:
    """Strictly read-only wrapper around the official MetaTrader5 Python package."""

    def __init__(self, terminal: str | Path | None = None, *, module: ModuleType | object | None = None):
        self.terminal = Path(terminal).resolve() if terminal else None
        self._provided_module = module
        self._mt5: object | None = None
        self._connected = False

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _load_module(self) -> object:
        if self._provided_module is not None:
            return self._provided_module
        try:
            return importlib.import_module("MetaTrader5")
        except ImportError as error:
            raise MT5UnavailableError(
                "MetaTrader5 package is available only on the Windows collector. "
                "Install the project on the same Windows host as MT5."
            ) from error

    def connect(self) -> None:
        if self._connected:
            return
        module = self._load_module()
        kwargs = {"path": str(self.terminal)} if self.terminal else {}
        if not module.initialize(**kwargs):
            raise MT5UnavailableError(f"MT5 initialize failed: {module.last_error()}")
        self._mt5 = module
        self._connected = True

    def close(self) -> None:
        if self._connected and self._mt5 is not None:
            self._mt5.shutdown()
        self._connected = False
        self._mt5 = None

    @property
    def module(self) -> object:
        if not self._connected or self._mt5 is None:
            raise MT5UnavailableError("MT5 data source is not connected")
        return self._mt5

    def list_symbols(self) -> list[str]:
        symbols = self.module.symbols_get()
        if symbols is None:
            raise MT5UnavailableError(f"MT5 symbols_get failed: {self.module.last_error()}")
        return sorted(str(symbol.name) for symbol in symbols)

    def resolve_symbol(self, requested: str, *, aliases: Iterable[str] = ()) -> str:
        available = self.list_symbols()
        requested_names = (requested, *aliases)
        matches = {
            symbol
            for symbol in available
            if any(symbol.casefold() == candidate.casefold() for candidate in requested_names)
        }
        if len(matches) == 1:
            return matches.pop()
        if not matches:
            nearby = [symbol for symbol in available if requested.casefold() in symbol.casefold()]
            hint = f" Nearby symbols: {', '.join(nearby[:10])}." if nearby else ""
            raise ValueError(f"No exact MT5 symbol mapping for {requested!r}.{hint}")
        raise ValueError(f"Ambiguous MT5 symbol mapping for {requested!r}: {', '.join(sorted(matches))}")

    def source_fingerprint(self) -> str:
        terminal = self.module.terminal_info()
        account = self.module.account_info()
        if terminal is None or account is None:
            raise MT5UnavailableError("MT5 terminal/account metadata are unavailable")
        payload = {
            "terminal": {
                "company": getattr(terminal, "company", None),
                "name": getattr(terminal, "name", None),
                "build": getattr(terminal, "build", None),
                "path": str(getattr(terminal, "path", "")),
            },
            "account": {
                "login": getattr(account, "login", None),
                "server": getattr(account, "server", None),
                "currency": getattr(account, "currency", None),
            },
        }
        digest = hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
        return f"mt5:{digest[:24]}"

    def build_broker_profile(
        self,
        *,
        profile_id: str,
        broker_id: str,
        account_currency: str,
        timezone: str,
        timezone_offset_minutes: int = 0,
        instruments: Iterable[InstrumentSpec],
    ) -> BrokerProfile:
        account = self.module.account_info()
        if account is None:
            raise MT5UnavailableError(f"MT5 account_info failed: {self.module.last_error()}")
        actual_currency = str(getattr(account, "currency", ""))
        if actual_currency.upper() != account_currency.upper():
            raise ValueError(
                f"Connected MT5 account currency is {actual_currency!r}, expected {account_currency!r}"
            )
        resolved: list[InstrumentSpec] = []
        for template in instruments:
            symbol = self.resolve_symbol(template.broker_symbol, aliases=template.aliases)
            info = self.module.symbol_info(symbol)
            if info is None:
                raise MT5UnavailableError(f"MT5 symbol_info({symbol!r}) failed: {self.module.last_error()}")
            resolved.append(
                replace(
                    template,
                    broker_symbol=symbol,
                    display_name=str(getattr(info, "description", "") or template.display_name),
                    base_currency=str(getattr(info, "currency_base", "") or "") or None,
                    quote_currency=str(getattr(info, "currency_profit", "") or "") or None,
                    digits=int(getattr(info, "digits", 0)),
                    point=float(getattr(info, "point", 0.0)),
                    tick_size=float(getattr(info, "trade_tick_size", 0.0)),
                    tick_value=float(getattr(info, "trade_tick_value", 0.0)),
                    contract_size=float(getattr(info, "trade_contract_size", 0.0)),
                    volume_min=float(getattr(info, "volume_min", 0.0)),
                    volume_max=float(getattr(info, "volume_max", 0.0)),
                    volume_step=float(getattr(info, "volume_step", 0.0)),
                    stops_level=int(getattr(info, "trade_stops_level", 0)),
                    freeze_level=int(getattr(info, "trade_freeze_level", 0)),
                    trade_mode=int(getattr(info, "trade_mode", 0)),
                    filling_mode=int(getattr(info, "filling_mode", 0)),
                    order_mode=int(getattr(info, "order_mode", 0)),
                    swap_long=float(getattr(info, "swap_long", 0.0)),
                    swap_short=float(getattr(info, "swap_short", 0.0)),
                    triple_swap_day=int(getattr(info, "swap_rollover3days", 0)),
                )
            )
        return BrokerProfile(
            profile_id=profile_id,
            broker_id=broker_id,
            account_currency=actual_currency.upper(),
            timezone=timezone,
            timezone_offset_minutes=timezone_offset_minutes,
            source_fingerprint=self.source_fingerprint(),
            instruments=tuple(resolved),
            margin_mode=int(getattr(account, "margin_mode", 0)),
            leverage=int(getattr(account, "leverage", 0)),
        )

    def iter_m1(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        chunk_days: int = 31,
    ) -> Iterator[pd.DataFrame]:
        start, end = _utc_range(start, end)
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=chunk_days) - timedelta(seconds=1), end)
            rates = self.module.copy_rates_range(
                symbol,
                self.module.TIMEFRAME_M1,
                cursor,
                chunk_end,
            )
            if rates is None:
                raise MT5UnavailableError(f"MT5 copy_rates_range failed: {self.module.last_error()}")
            if len(rates):
                yield canonicalize_mt5_rates(rates, timeframe="M1", as_of=end)
            cursor = chunk_end + timedelta(seconds=1)

    def iter_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        chunk_days: int = 1,
    ) -> Iterator[pd.DataFrame]:
        start, end = _utc_range(start, end)
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=chunk_days) - timedelta(microseconds=1), end)
            ticks = self.module.copy_ticks_range(
                symbol,
                cursor,
                chunk_end,
                self.module.COPY_TICKS_ALL,
            )
            if ticks is None:
                raise MT5UnavailableError(f"MT5 copy_ticks_range failed: {self.module.last_error()}")
            if len(ticks):
                yield canonicalize_mt5_ticks(ticks)
            cursor = chunk_end + timedelta(microseconds=1)


def _utc_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("MT5 import start/end must be timezone-aware UTC datetimes")
    utc_start = start.astimezone(UTC)
    utc_end = end.astimezone(UTC)
    if utc_end <= utc_start:
        raise ValueError("MT5 import end must be later than start")
    return utc_start, utc_end
