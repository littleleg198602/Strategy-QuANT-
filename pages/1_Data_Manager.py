from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from strategy_quant.data_catalog import DataCatalog
from strategy_quant.data_manager import DataManager
from strategy_quant.data_models import BrokerProfile, InstrumentSpec
from strategy_quant.data_quality import validate_canonical_bars, validate_canonical_ticks
from strategy_quant.mt5_data import MT5DataSource, discover_mt5_terminals

CONFIG_PATH = Path("config/darwinex_zero_usd.json")
CATALOG_PATH = Path("data/catalog")


def load_reference_config(
    path: Path = CONFIG_PATH,
) -> tuple[dict[str, Any], tuple[InstrumentSpec, ...]]:
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


def build_profile(
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


def years_ago(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


def selected_terminal(detected: list[Path], choice: str, manual: str) -> Path | None:
    if manual.strip():
        return Path(manual.strip())
    if choice == "Použít právě otevřený MT5 automaticky":
        return None
    return Path(choice)


def catalog_table(catalog: DataCatalog) -> pd.DataFrame:
    rows = [
        {
            "ID": item.dataset_id,
            "Symbol": item.broker_symbol,
            "Typ": item.timeframe,
            "Kvalita": item.quality_status,
            "Řádků": item.row_count,
            "Od": item.first_timestamp,
            "Do": item.last_timestamp,
            "Vytvořeno": item.created_at,
        }
        for item in catalog.list_manifests()
    ]
    return pd.DataFrame(rows)


st.set_page_config(page_title="Data Manager · Strategy QuANT", layout="wide")
st.title("Data Manager")
st.caption("Stažení, kontrola a lokální katalog historie z MetaTraderu 5")
st.info(
    "Tato část je pouze pro čtení historie. Nepřijímá heslo a neumí odeslat obchodní příkaz."
)

if sys.platform != "win32":
    st.warning(
        "Přímé připojení k MT5 funguje ve Windows. Katalog lze na jiném systému pouze prohlížet."
    )

config, templates = load_reference_config()
configured_symbols = [item.broker_symbol for item in templates]
detected = discover_mt5_terminals()
terminal_options = ["Použít právě otevřený MT5 automaticky", *[str(path) for path in detected]]

st.subheader("1. Připojení k MT5")
left, right = st.columns([2, 3])
with left:
    terminal_choice = st.selectbox("Nalezený terminál", terminal_options)
with right:
    manual_terminal = st.text_input(
        "Nebo zadej cestu k terminal64.exe",
        placeholder=r"C:\Program Files\Darwinex MetaTrader 5\terminal64.exe",
    )

terminal = selected_terminal(detected, terminal_choice, manual_terminal)
if detected:
    st.caption(f"Nalezeno terminálů: {len(detected)}")
else:
    st.caption("Automatické hledání terminál nenašlo; lze použít otevřený MT5 nebo zadat cestu.")

if st.button("Ověřit připojení a účet", disabled=sys.platform != "win32"):
    try:
        if terminal is not None and not terminal.is_file():
            raise FileNotFoundError(f"Soubor neexistuje: {terminal}")
        catalog = DataCatalog(CATALOG_PATH)
        with st.spinner("Připojuji se pouze pro čtení metadat..."):
            with MT5DataSource(terminal) as source:
                profile = build_profile(source, config, templates)
                profile_path = catalog.save_profile(profile)
        st.session_state["dm_profile"] = {
            "Měna účtu": profile.account_currency,
            "Páka": profile.leverage,
            "Symboly": ", ".join(item.broker_symbol for item in profile.instruments),
            "Verze profilu": profile.version,
            "Soubor profilu": str(profile_path),
        }
        st.success("MT5 je připojený a profil Darwinex Zero / USD odpovídá.")
    except Exception as error:
        st.error(f"Připojení se nepodařilo: {error}")

if "dm_profile" in st.session_state:
    st.json(st.session_state["dm_profile"])

st.subheader("2. Stažení historie")
kind_label = st.radio(
    "Typ historie",
    ("M1 bary — první test", "Ticková data — až po ověření M1"),
    horizontal=True,
)
kind = "m1" if kind_label.startswith("M1") else "ticks"
retention_years = int(config["history"]["m1_years" if kind == "m1" else "tick_years"])
today = datetime.now(UTC).date()

symbols = st.multiselect(
    "Symboly",
    configured_symbols,
    default=["XAUUSD"],
    help="Nejdřív stáhni pouze XAUUSD M1. Ostatní symboly přidej po kontrole výsledku.",
)
date_left, date_right = st.columns(2)
with date_left:
    start_date = st.date_input("Od", value=years_ago(today, retention_years))
with date_right:
    end_date = st.date_input("Do", value=today)

tick_confirmed = True
if kind == "ticks":
    st.warning("Ticková historie za rok může zabrat mnoho GB a stahování může trvat dlouho.")
    tick_confirmed = st.checkbox("Rozumím a chci stáhnout ticková data")

run_disabled = (
    sys.platform != "win32"
    or not symbols
    or start_date >= end_date
    or not tick_confirmed
)

if st.button("Stáhnout a zkontrolovat historii", type="primary", disabled=run_disabled):
    try:
        if terminal is not None and not terminal.is_file():
            raise FileNotFoundError(f"Soubor neexistuje: {terminal}")
        start = datetime.combine(start_date, time.min, tzinfo=UTC)
        end = (
            datetime.now(UTC)
            if end_date == today
            else datetime.combine(end_date, time.max, tzinfo=UTC)
        )
        catalog = DataCatalog(CATALOG_PATH)
        manager = DataManager(catalog)
        imported: list[dict[str, Any]] = []
        with st.status("Načítám historii z MT5...", expanded=True) as status:
            with MT5DataSource(terminal) as source:
                profile = build_profile(source, config, templates)
                catalog.save_profile(profile)
                for requested_symbol in symbols:
                    instrument = next(
                        item
                        for item in profile.instruments
                        if item.instrument_id
                        == next(
                            template.instrument_id
                            for template in templates
                            if template.broker_symbol == requested_symbol
                        )
                    )
                    st.write(f"Stahuji {instrument.broker_symbol} / {kind.upper()}...")
                    manifest = manager.import_mt5(
                        source,
                        broker_profile=profile,
                        broker_symbol=instrument.broker_symbol,
                        datatype="bar" if kind == "m1" else "tick",
                        start=start,
                        end=end,
                        minimum_coverage=float(
                            config["history"].get("minimum_coverage", 0.98)
                        ),
                    )
                    imported.append(
                        {
                            "ID": manifest.dataset_id,
                            "Symbol": manifest.broker_symbol,
                            "Typ": manifest.timeframe,
                            "Kvalita": manifest.quality_status,
                            "Řádků": manifest.row_count,
                            "Od": manifest.first_timestamp,
                            "Do": manifest.last_timestamp,
                        }
                    )
            status.update(label="Historie je stažená a zkontrolovaná.", state="complete")
        st.session_state["dm_last_import"] = imported
        st.success(f"Hotovo: uloženo datasetů {len(imported)}.")
    except Exception as error:
        st.error(f"Import se nepodařil: {error}")

if "dm_last_import" in st.session_state:
    st.dataframe(pd.DataFrame(st.session_state["dm_last_import"]), hide_index=True, use_container_width=True)

st.subheader("3. Lokální katalog")
catalog = DataCatalog(CATALOG_PATH)
table = catalog_table(catalog)
if table.empty:
    st.caption("Katalog je zatím prázdný.")
else:
    st.dataframe(table, hide_index=True, use_container_width=True)
    dataset_id = st.selectbox("Dataset pro opakovanou kontrolu", table["ID"].tolist())
    if st.button("Znovu ověřit kvalitu"):
        try:
            manifest = catalog.get_manifest(dataset_id)
            frame = catalog.load(dataset_id, allow_non_pass=True)
            result = (
                validate_canonical_bars(frame, raise_on_fail=False)
                if manifest.datatype == "bar"
                else validate_canonical_ticks(frame, raise_on_fail=False)
            )
            st.json(result.report.to_dict())
        except Exception as error:
            st.error(f"Kontrola se nepodařila: {error}")
