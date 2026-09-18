from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from strategy_quant.data import load_mt5_csv
from strategy_quant.data_catalog import DataCatalog
from strategy_quant.demo import make_demo_bars
from strategy_quant.exporter import export_mql5, export_strategy_json
from strategy_quant.generator import SearchSpace, generate_candidates
from strategy_quant.models import BacktestConfig
from strategy_quant.portfolio import PortfolioEngine, rank_portfolio_candidates
from strategy_quant.research_data import available_research_datasets, load_research_dataset


CATALOG_PATH = Path("data/catalog")


def dataset_label(dataset_id: str, catalogs: dict[str, object]) -> str:
    manifest = catalogs[dataset_id]
    return (
        f"{manifest.broker_symbol} / {manifest.timeframe} · {manifest.row_count:,} barů · "
        f"{manifest.first_timestamp[:10]} až {manifest.last_timestamp[:10]} · PASS"
    )


st.set_page_config(page_title="Strategy QuANT", layout="wide")
st.title("Strategy QuANT")
st.caption("Generátor strategií · deterministický backtest · robustnost · MT5 export")

with st.sidebar:
    st.header("Data a riziko")
    catalog_error: str | None = None
    try:
        catalog = DataCatalog(CATALOG_PATH)
        catalog_datasets = available_research_datasets(catalog)
    except Exception as error:
        catalog = None
        catalog_datasets = []
        catalog_error = str(error)

    source_options = ["Lokální katalog (ověřená data)", "MT5 CSV", "Demo data — pouze ukázka"]
    source_mode = st.radio("Zdroj dat", source_options, index=0 if catalog_datasets else 1)
    uploads = []
    broker_timezone = "UTC"
    selected_dataset_id: str | None = None
    selected_manifest = None

    if source_mode == "Lokální katalog (ověřená data)":
        if catalog_error:
            st.error(f"Lokální katalog nelze otevřít: {catalog_error}")
        elif not catalog_datasets:
            st.warning("V katalogu zatím není žádný dataset s kvalitou PASS. Otevři Data Manager.")
        else:
            manifests_by_id = {item.dataset_id: item for item in catalog_datasets}
            selected_dataset_id = st.selectbox(
                "Uložený dataset",
                list(manifests_by_id),
                format_func=lambda identifier: dataset_label(identifier, manifests_by_id),
            )
            selected_manifest = manifests_by_id[selected_dataset_id]
            st.caption(f"SHA-256 dat: {selected_manifest.canonical_hash}")
            st.caption("Použijí se pouze neměnná data s kvalitou PASS.")
    elif source_mode == "MT5 CSV":
        uploads = st.file_uploader(
            "MT5 CSV (jeden soubor na symbol)", type=["csv", "txt"], accept_multiple_files=True
        )
        broker_timezone = st.text_input("Časová zóna exportu", "UTC")
    else:
        st.warning("Demo data jsou umělá. Výsledky z nich nepoužívej pro rozhodování.")

    risk_percent = st.number_input("Riziko na obchod (%)", 0.1, 5.0, 0.5, 0.1)
    max_drawdown_percent = st.number_input("Stop nových obchodů při DD (%)", 1.0, 50.0, 20.0, 1.0)
    spread_bps = st.number_input("Spread (bps)", 0.0, 100.0, 1.0, 0.1)
    slippage_bps = st.number_input("Slippage (bps)", 0.0, 100.0, 0.5, 0.1)
    first_run = source_mode == "Lokální katalog (ověřená data)" and selected_manifest is not None
    candidate_limit = st.slider(
        "Počet kandidátů",
        1,
        100,
        1 if first_run else 50,
        1 if first_run else 5,
        key=f"candidate_limit_{source_mode}",
    )
    if first_run and selected_manifest.row_count > 500_000:
        st.warning(
            "Tento pětiletý M1 dataset je velký. První běh nech na 1 kandidátu; "
            "vyšší počet bude trvat podstatně déle."
        )

st.info(
    "V1 je výzkumný a paper-simulační nástroj. Nic neposílá brokerovi. "
    "Signál vzniká na close a vstup se provede na open následujícího baru."
)

if st.button("Spustit výzkum", type="primary"):
    try:
        data_provenance: dict[str, str | int]
        if source_mode == "Lokální katalog (ověřená data)":
            if catalog is None or selected_dataset_id is None:
                raise ValueError("Nejdřív v Data Manageru vyber nebo vytvoř dataset s kvalitou PASS")
            research_dataset = load_research_dataset(catalog, selected_dataset_id)
            frames = {research_dataset.manifest.broker_symbol: research_dataset.frame}
            data_provenance = research_dataset.provenance()
        elif source_mode == "Demo data — pouze ukázka":
            frames = {
                "EURUSD": make_demo_bars(symbol="EURUSD"),
                "GBPUSD": make_demo_bars(symbol="GBPUSD", seed=19),
            }
            data_provenance = {"source": "demo", "warning": "Uměle vytvořená data"}
        else:
            if not uploads:
                raise ValueError("Nahraj alespoň jeden MT5 CSV soubor")
            frames = {
                upload.name.rsplit(".", 1)[0].upper(): load_mt5_csv(
                    upload,
                    symbol=upload.name.rsplit(".", 1)[0].upper(),
                    timezone=broker_timezone,
                )
                for upload in uploads
            }
            data_provenance = {
                "source": "csv",
                "files": len(uploads),
                "timezone": broker_timezone,
            }
        config = BacktestConfig(
            risk_fraction=risk_percent / 100,
            max_drawdown=max_drawdown_percent / 100,
            spread_bps=spread_bps,
            slippage_bps=slippage_bps,
        )
        candidates = generate_candidates(SearchSpace())[:candidate_limit]
        results = rank_portfolio_candidates(frames, candidates, PortfolioEngine(config))
        best = results[0]
        table = pd.DataFrame(
            [{"strategy_id": item.strategy.strategy_id, **item.metrics} for item in results]
        )
        st.session_state["best"] = best
        st.session_state["config"] = config
        st.session_state["table"] = table
        st.session_state["data_provenance"] = data_provenance
    except Exception as error:
        st.error(f"Výzkum se nepodařilo spustit: {error}")

if "best" in st.session_state:
    best = st.session_state["best"]
    config = st.session_state["config"]
    table = st.session_state["table"]
    provenance = st.session_state["data_provenance"]
    st.subheader("Použitá data")
    if provenance.get("source") == "demo":
        st.warning("Výsledek níže je z demo dat, nikoliv z MT5 historie.")
    elif provenance.get("source") == "csv":
        st.info(f"Zdroj: {provenance['files']} CSV soubor(y), časová zóna: {provenance['timezone']}.")
    else:
        first, second, third, fourth = st.columns(4)
        first.metric("Symbol", str(provenance["symbol"]))
        second.metric("Timeframe", str(provenance["timeframe"]))
        third.metric("Barů", f"{int(provenance['rows']):,}")
        fourth.metric("Kvalita", str(provenance["quality"]))
        st.caption(
            f"Dataset: {provenance['dataset_id']} · {provenance['from'][:10]} až "
            f"{provenance['to'][:10]} · SHA-256: {provenance['canonical_hash']}"
        )
    st.subheader("Nejlepší kandidát")
    first, second, third, fourth = st.columns(4)
    first.metric("Výnos", f"{best.metrics['total_return']:.1%}")
    second.metric("Max. drawdown", f"{best.metrics['max_drawdown']:.1%}")
    third.metric("Profit factor", f"{best.metrics['profit_factor']:.2f}")
    fourth.metric("Obchody", f"{int(best.metrics['trades'])}")
    st.line_chart(best.equity)
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.subheader("Obchody")
    st.dataframe(best.trades_frame(), use_container_width=True, hide_index=True)
    left, right = st.columns(2)
    left.download_button(
        "Stáhnout MT5 EA (.mq5)",
        export_mql5(best.strategy, config),
        file_name=f"{best.strategy.strategy_id}.mq5",
        mime="text/plain",
    )
    right.download_button(
        "Stáhnout konfiguraci (.json)",
        export_strategy_json(best.strategy, config),
        file_name=f"{best.strategy.strategy_id}.json",
        mime="application/json",
    )
