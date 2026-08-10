from __future__ import annotations

import pandas as pd
import streamlit as st

from strategy_quant.data import load_mt5_csv
from strategy_quant.demo import make_demo_bars
from strategy_quant.exporter import export_mql5, export_strategy_json
from strategy_quant.generator import SearchSpace, generate_candidates
from strategy_quant.models import BacktestConfig
from strategy_quant.portfolio import PortfolioEngine, rank_portfolio_candidates


st.set_page_config(page_title="Strategy QuANT", layout="wide")
st.title("Strategy QuANT")
st.caption("Generátor strategií · deterministický backtest · robustnost · MT5 export")

with st.sidebar:
    st.header("Data a riziko")
    uploads = st.file_uploader(
        "MT5 CSV (jeden soubor na symbol)", type=["csv", "txt"], accept_multiple_files=True
    )
    broker_timezone = st.text_input("Časová zóna exportu", "UTC")
    risk_percent = st.number_input("Riziko na obchod (%)", 0.1, 5.0, 0.5, 0.1)
    max_drawdown_percent = st.number_input("Stop nových obchodů při DD (%)", 1.0, 50.0, 20.0, 1.0)
    spread_bps = st.number_input("Spread (bps)", 0.0, 100.0, 1.0, 0.1)
    slippage_bps = st.number_input("Slippage (bps)", 0.0, 100.0, 0.5, 0.1)
    candidate_limit = st.slider("Počet kandidátů", 5, 100, 50, 5)
    use_demo = st.checkbox("Použít demo data", value=not uploads)

st.info(
    "V1 je výzkumný a paper-simulační nástroj. Nic neposílá brokerovi. "
    "Signál vzniká na close a vstup se provede na open následujícího baru."
)

if st.button("Spustit výzkum", type="primary"):
    try:
        if use_demo:
            frames = {
                "EURUSD": make_demo_bars(symbol="EURUSD"),
                "GBPUSD": make_demo_bars(symbol="GBPUSD", seed=19),
            }
        else:
            frames = {
                upload.name.rsplit(".", 1)[0].upper(): load_mt5_csv(
                    upload,
                    symbol=upload.name.rsplit(".", 1)[0].upper(),
                    timezone=broker_timezone,
                )
                for upload in uploads
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
    except Exception as error:
        st.error(f"Výzkum se nepodařilo spustit: {error}")

if "best" in st.session_state:
    best = st.session_state["best"]
    config = st.session_state["config"]
    table = st.session_state["table"]
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

