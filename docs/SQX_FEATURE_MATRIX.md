# StrategyQuant X → Strategy QuANT: matice funkcí

Status: návrh 0.1 k odsouhlasení  
Datum rešerše: 2026-08-10  
Cíl: funkční obdoba jádra StrategyQuant X pro MT5, Darwinex, Forex, indexy a kovy

## Jak matici číst

Tento dokument je funkční inventura, nikoli kopie vzhledu, názvů nebo zdrojového kódu
StrategyQuant X. Funkce jsou odvozeny z veřejné dokumentace výrobce. Rozhraní a
implementace Strategy QuANT budou vlastní.

Priorita:

- CORE — součást cíle Strategy QuANT Core v1.
- LATER — smysluplné rozšíření po stabilním Core v1.
- OUT — záměrně mimo rozsah.

Stav:

- YES — použitelný základ už existuje v main.
- PARTIAL — existuje jen zjednodušená část.
- NO — zatím chybí.

Milníky: M1 Data, M2 Backtest, M3 Strategy DSL, M4 Builder + Databank, M5 Genetic
Evolution, M6 Robustness + Optimizer, M7 Portfolio, M8 Workflow + UI + MT5 export,
M9 Paper/forward validation.

## Výchozí stav projektu

Main po PR #1 obsahuje načítání MT5 CSV, 72 EMA/breakout kandidátů, barový next-open
backtest, pevné náklady, ATR SL/TP a risk sizing, základní portfolio, OOS, jednoduchý
rolling test, bootstrap Monte Carlo, Streamlit/CLI, paper simulaci bez brokerských
příkazů a základní JSON/MQL5 export. Tento základ je prototyp; není to zatím
ekvivalent SQX.

## 1. Platforma a moduly

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| PL-01 | Oddělené moduly Builder, Retester, Optimizer a Data Manager | PARTIAL | CORE / M1–M6 | Každý modul má vlastní aplikační službu, API a stav běhu; UI je pouze klient | S01 |
| PL-02 | Custom Projects jako řetězec úloh | NO | CORE / M8 | Verzionovaný workflow umí větvit, opakovat, filtrovat a obnovit přerušený běh | S13, S14 |
| PL-03 | AlgoWizard pro přesnou ruční definici pravidel | NO | CORE / M3, UI v M8 | Každé podporované pravidlo lze vytvořit/editovat v DSL; vizuální editor může přijít až po DSL | S01, S08 |
| PL-04 | Code Editor, vlastní indikátory a bloky | NO | LATER | Stabilní plugin API, sandboxované načtení a testovací kontrakt | S01, S09 |
| PL-05 | Progress, logy, výkon a paměť běhu | PARTIAL | CORE / M8 | Běh publikuje stav, throughput, ETA, chyby, seed, CPU/RAM a checkpoint | S02 |
| PL-06 | Grid Control / distribuované výpočty | NO | LATER | Jeden job lze bezpečně rozdělit mezi pracovníky bez změny výsledku | S01 |
| PL-07 | Interaktivní tutoriály a ukázkové workflow | NO | LATER | Verzionované příklady projdou automatickým smoke testem | S01 |

## 2. Data Manager

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| DM-01 | Přímý import z lokálního MT5 (od SQX build 144) | NO | CORE / M1 | Uživatel zvolí terminál, symbol, typ dat a období; import je opakovatelný a inkrementální | S04 |
| DM-02 | Import vlastních souborů | PARTIAL | CORE / M1 | CSV/TSV profil mapuje sloupce, delimiter, timestamp, timezone a jednotky; chyby jsou v reportu | S03, S05 |
| DM-03 | Integrované zdroje Dukascopy a Darwinex | NO | LATER po MT5 | Konektor stahuje M1/tick data, ukládá licenci/provenienci a umí pokračovat po výpadku | S05, S06 |
| DM-04 | Tick i M1 historie | NO | CORE / M1 | Kanonický tick a M1 dataset se samostatným schématem, hashem a coverage reportem | S03, S04 |
| DM-05 | Tvorba vyšších timeframe z M1 | NO | CORE / M1 | Deterministický resampling respektuje timestamp konvenci, timezone a sessions | S03, S07 |
| DM-06 | Převod časových pásem | PARTIAL | CORE / M1 | Zdrojová timezone, broker timezone a UTC jsou explicitní; DST ambiguity nikdy není tiše odhadnuta | S06, S07 |
| DM-07 | Broker profiles | NO | CORE / M1 | Verzionovaný profil obsahuje timezone, instrumenty, sessions, náklady a MT5 identitu | S06 |
| DM-08 | Instrument metadata: digits, point/tick size/value, contract a lot rules | NO | CORE / M1 | Metadata jsou načtena z MT5, uložena s daty a použita backtestem; změny vytvoří novou verzi | S06 |
| DM-09 | Obchodní a kotovací sessions | NO | CORE / M1 | Kalendář podporuje více intervalů za den, svátky a půl-dny; data mimo pravidla jsou označena | S06, S26 |
| DM-10 | Alias symbolu mezi zdroji/brokery | PARTIAL | CORE / M1 | Kanonický instrument ID je oddělen od broker symbolu; mapování je konfigurovatelné | S06 |
| DM-11 | Kontrola a analýza kvality dat | PARTIAL | CORE / M1 | Report pokryje duplicity, pořadí, OHLC, mezery, crossed tick, nulové ceny, coverage a DST | S05 |
| DM-12 | Tabulkový a grafický náhled dat | NO | CORE / M8 | Uživatel zobrazí rozsah, gaps, ceny, spread a objem bez načtení celé historie do RAM | S05 |
| DM-13 | Export/konverze dat pro podporované platformy | NO | CORE pouze interní/MT5 / M1, M8 | Export kanonického CSV/Parquet a MT5 validační sady je deterministický a zpětně načitatelný | S03, S05 |
| DM-14 | Externě vypočtené indikátorové řady | NO | LATER | Řada je svázána se symbolem, timeframe, verzí výpočtu a přesným timestampem | S10 |
| DM-15 | Inkrementální update historie | NO | CORE / M1 | Update doplní jen chybějící rozsah, detekuje revize a nikdy tiše nepřepíše původní verzi | S04 |
| DM-16 | Data lineage a reprodukovatelnost | NO | CORE / M1 | Každý backtest uvádí dataset ID, obsahový hash, profil brokera a resampling verzi | vlastní požadavek pro audit |

Podrobný kontrakt je v DATA_SPECIFICATION.md.

## 3. Backtest a exekuce

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| BT-01 | Volba trading enginu včetně MT5 | NO | CORE / M2 | Engine profil MT5 přesně definuje ceny, rounding, objednávky, účetní režim a pořadí událostí | S03 |
| BT-02 | Selected Timeframe: čtyři pseudo-ticky O/H/L/C | PARTIAL | CORE / M2 | Reprodukovatelná intrabar cesta je zdokumentována a otestována pro obě polarity baru | S03 |
| BT-03 | M1 precision | NO | CORE / M2 | Signální timeframe používá M1 intrabary bez look-ahead; výsledky mají přesnostní štítek | S03 |
| BT-04 | Real Tick s vlastním spreadem | NO | CORE / M2 | Bid tick + zadaný spread tvoří Ask; rounding a časové shody mají testy | S03 |
| BT-05 | Real Tick s historickým Bid/Ask spreadem | NO | CORE / M2 | Tick replay zachová pořadí a reálný spread; stejné vstupy dají stejný trade ledger | S03 |
| BT-06 | Market, stop, limit a reverse vstupy | PARTIAL | CORE / M2 | Každý typ má jasný lifecycle create/modify/fill/expire/cancel/reject a gap pravidla | S08 |
| BT-07 | SL, PT, trailing, time exit, opposite signal | PARTIAL | CORE / M2 | Všechny exity mají určenou prioritu a důvod v auditu obchodu | S08 |
| BT-08 | Multiple exits / scale-out (ATM) | NO | CORE / M2 později | Částečné výstupy respektují min lot/step; součet fills a P&L sedí na ledger | S11 |
| BT-09 | Spread, slippage, min distance | PARTIAL | CORE / M2 | Náklady jsou v cenových jednotkách instrumentu, směrově nepříznivé a auditované | S03 |
| BT-10 | Komise a swapy v různých modelech | NO | CORE / M2 | Round-turn/per-side, fixed/size-based a swap points/money/percent mají referenční testy | S03 |
| BT-11 | Gapy a současný zásah SL/TP | PARTIAL | CORE / M2 | Politika je explicitní pro každý precision mode; žádné skryté optimistické plnění | parity kontrakt |
| BT-12 | Multi-timeframe podmínky v jedné strategii | NO | CORE / M2–M3 | Pomalejší timeframe je dostupný až po uzavření baru; žádný leakage | S03 |
| BT-13 | Multi-symbol podmínky v jedné strategii | NO | CORE / M2–M3 | Události jsou stabilně seřazeny; každý cross-symbol údaj má known-at timestamp | S03 |
| BT-14 | Netting a hedging účty MT5 | NO | CORE / M2 | Oba režimy mají oddělené position/order účetnictví a parity test | MT5 cílový rozsah |
| BT-15 | Margin, leverage, stop-out a rejected orders | NO | CORE / M2 | Pre-trade check reprodukuje přijetí/odmítnutí; důvod je v rejected-entry logu | M2 požadavek |
| BT-16 | Sessions a omezení obchodování | NO | CORE / M2 | Kotace, obchodování, pending orders, Friday/EOD a holidays používají kalendář z M1 | S06, S26 |
| BT-17 | Position sizing a money management | PARTIAL | CORE / M2 | Fixed lot, fixed cash risk a % equity/balance; rounding a nedostatečná margin jsou testované | S12 |
| BT-18 | Determinismus a zákaz look-ahead | PARTIAL | CORE / M2 | Stejný dataset/config/seed = identický hash ledgeru; změna budoucích dat nemění minulost | release gate |
| BT-19 | Parita s MT5 Strategy Testerem | NO | CORE / M2 | Referenční strategie se porovnají obchod po obchodu v definované tick/time/money toleranci | S07 |

Podrobný kontrakt je v BACKTEST_SPECIFICATION.md.

## 4. Strategie, Builder a Improver

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| ST-01 | Univerzální strom pravidel strategie | NO | CORE / M3 | Verzionované JSON DSL reprezentuje charts, variables, conditions, actions, orders, sizing a exits | S08 |
| ST-02 | Long, short, symetrická a nezávislá logika | PARTIAL | CORE / M3 | DSL umí sdílené i oddělené parametry a explicitní negaci | S08 |
| ST-03 | Building blocks: signals, indicators, values a operátory | PARTIAL | CORE / M3 | Registr bloků s typy, parametry, warm-up, validací a bez-look-ahead kontraktem | S08 |
| ST-04 | Building blocks pro stop/limit ceny, order a exit typy | NO | CORE / M3 | Typový systém zabrání neplatné skladbě ještě před backtestem | S08 |
| ST-05 | Strategy templates s náhodnými placeholdery | NO | CORE / M3–M4 | Pevná kostra + RandomCondition/Value/Action vytvoří validní DSL dle omezení | S15 |
| ST-06 | Random groups | NO | CORE / M4 | Skupina omezuje bloky a rozsahy pro konkrétní placeholder; výběr je auditovaný | S16 |
| ST-07 | Vlastní bloky bez kódu | NO | CORE / M3 později | Složený blok lze uložit, verzovat a otestovat jako jiný blok | S09 |
| ST-08 | Vlastní programované indikátory/bloky | NO | LATER | Plugin má sandbox, API verzi, deterministické testy a exportní implementaci | S01, S09 |
| ST-09 | Rozsahy parametrů a calibration | NO | CORE / M3–M4 | Min/max/step/set/distribution jsou validované na úrovni bloku a šablony | S17 |
| ST-10 | Random Generation | PARTIAL | CORE / M4 | Neomezený seeded stream validních kandidátů, deduplikace a checkpoint/resume | S18 |
| ST-11 | Genetic Evolution | NO | CORE / M5 | Populace, selection, crossover, mutation, elitism a diversity jsou seeded a měřitelné | S18 |
| ST-12 | Improver — změna vybraných částí strategie | NO | CORE / M5 | Uživatel zamkne části DSL a evoluce smí měnit pouze povolené uzly | S19 |
| ST-13 | Fuzzy logika | NO | LATER | Jasně definované fuzzy operátory a exportní parita | veřejný SQX rozsah |

## 5. Databanky, ranking a výsledky

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| DB-01 | Více databank jako zdroj/cíl úloh | NO | CORE / M4 | Trvalé databanky s transakcemi, schema version a lineage | S14 |
| DB-02 | Top-N a maximální kapacita | PARTIAL | CORE / M4 | Top-N funguje streamově a stabilně při shodném skóre | S20 |
| DB-03 | Fitness z jedné nebo složených metrik | PARTIAL | CORE / M4 | Verzionovaný výraz s vahami; uložen spolu s runem | S20 |
| DB-04 | Automatické a vlastní filtry | PARTIAL | CORE / M4 | Filtry jsou serializované výrazy, logují PASS/FAIL a hodnoty operandů | S20 |
| DB-05 | Odstranění identických/podobných strategií | NO | CORE / M4 | Strukturální hash + podobnost obchodů/equity; práh je součást konfigurace | S21 |
| DB-06 | Load/save/edit/retest/portfolio nad strategií | PARTIAL | CORE / M4–M8 | Každá akce zachová původní artefakt a vytvoří auditovanou novou verzi | S22 |
| DB-07 | Konfigurovatelné views a CSV/XLS export tabulky | NO | CORE / M8, XLS later | Uložené sloupce, řazení a filtry; CSV export odpovídá zobrazenému snapshotu | S22 |
| DB-08 | Uložení strategie, configu, source a výsledků | PARTIAL | CORE / M4 | Jeden immutable strategy bundle obsahuje DSL, data/config hashes, ledger, metrics a exporty | S22 |

## 6. Retester, robustnost a optimizer

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| RB-01 | Hromadný Retester na jiných datech/nastaveních | PARTIAL | CORE / M6 | Matrix strategií × datasetů × konfigurací běží dávkově a ukládá každý výsledek | S01 |
| RB-02 | IS/ISV/OOS/No-trade části historie | PARTIAL | CORE / M6 | Části jsou disjunktní, uložené v run configu a generátor nesmí číst OOS | S03 |
| RB-03 | Retest s vyšší přesností | NO | CORE / M6 | Selected-TF kandidát projde M1/tick stupněm se stanoveným filtrem | S23 |
| RB-04 | Další trhy a timeframe | PARTIAL | CORE / M6 | Stejný DSL se testuje na předem zmrazeném universu bez přeladění | S23 |
| RB-05 | Monte Carlo: pořadí a vynechání obchodů | PARTIAL | CORE / M6 | Seeded shuffle/skip, percentily a confidence report mají analytické testy | S23 |
| RB-06 | Monte Carlo full retest: parametry, data, spread, slippage | NO | CORE / M6 | Každá perturbace vytvoří samostatný config/hash a nový deterministický backtest | S23 |
| RB-07 | What-If scénáře | NO | CORE / M6 | Nejlepší obchody, hodiny/dny a další pravidla lze vypnout bez změny původního ledgeru | S38 |
| RB-08 | Simple/exhaustive optimization | NO | CORE / M6 | Projde definovaný kartézský prostor bez duplicit; nejlepší bod lze reprodukovat | S25 |
| RB-09 | Genetic a sequential optimization | NO | CORE / M6 | Seeded algoritmy s budgetem a stejným objektivem; report pokrytí prostoru | S25 |
| RB-10 | Optimization Profile a System Parameter Permutation | NO | CORE / M6 | Stability report ukáže okolí parametrů, nikoli pouze jediný optimum bod | S24 |
| RB-11 | Walk-Forward Optimization | PARTIAL | CORE / M6 | Každé okno má train/selection/test, pouze minulá data a stitched OOS equity | S25 |
| RB-12 | Walk-Forward Matrix | NO | CORE / M6 | Matrix délek a reoptimization period má stabilní oblast a exportovatelný report | S25 |

## 7. Analýza výsledků

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| AN-01 | Overview a rozsáhlé metriky | PARTIAL | CORE / M4, M8 | Metriky mají přesný vzorec, jednotku, edge-case test a scope IS/OOS/portfolio | S27 |
| AN-02 | Kompletní seznam obchodů | PARTIAL | CORE / M2, M8 | Ledger obsahuje order/fill/trade vazby, ceny, náklady, sizing a důvody | S28 |
| AN-03 | Equity, balance a drawdown graf | PARTIAL | CORE / M8 | Přepínání scope, čas/money/percent a export dat | S29 |
| AN-04 | Trade analysis podle roku, hodiny, dne atd. | NO | CORE / M8 | Agregace jsou počítány z ledgeru v broker timezone a jsou testované | S30 |
| AN-05 | Korelace strategií/marketů | NO | CORE / M7–M8 | Pearson/Spearman na zvolené frekvenci a missing-data politika jsou explicitní | S31 |
| AN-06 | Obchody v cenovém grafu | NO | CORE / M8 | Entry/exit/order/fill lze dohledat proti přesné verzi dat | S32 |
| AN-07 | Strategy config a rozdíly konfigurací | NO | CORE / M8 | Diff ukáže data, execution, strategy i robustness config a umí vytvořit nový run | S33 |
| AN-08 | Pseudokód a zdrojový kód | PARTIAL | CORE / M3, M8 | Pseudokód vzniká z DSL; MQL5 export se automaticky kompiluje a parity-testuje | S34 |

## 8. Portfolio

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| PF-01 | Sloučení strategií a společná equity | PARTIAL | CORE / M7 | Společná event timeline, balance/equity, náklady, margin a rejected trades | S22, S35 |
| PF-02 | Korelační matice | NO | CORE / M7 | Více frekvencí a P&L/trade-count varianty se shodují s nezávislým výpočtem | S31 |
| PF-03 | Výběr kombinace strategií | NO | CORE / M7 | Brute-force/genetic budget, constraints a reprodukovatelný výsledek | S35 |
| PF-04 | Optimalizace vah a přepočet position sizing | NO | CORE / M7 | Váhy ovlivní sizing před simulací, nikoli jen dodatečně equity | S35 |
| PF-05 | Leverage, margin a neotevřené obchody | NO | CORE / M7 | Portfolio ledger obsahuje margin snapshots a každý odmítnutý vstup | S35 |
| PF-06 | Fit-to-Portfolio | NO | CORE / M7 | Kandidát je hodnocen inkrementálním přínosem a korelací k existujícímu portfoliu | S36 |

## 9. Workflow, export a forward

| ID | Veřejně popsaná funkce SQX | Stav | Priorita / milník | Definition of Done ve Strategy QuANT | Zdroj |
|---|---|---:|---|---|---|
| WF-01 | Build/Retest/Optimize/Filter/Portfolio úlohy | NO | CORE / M8 | Typované uzly mají vstupy, výstupy, retry a immutable run artefakty | S13, S14 |
| WF-02 | Smyčky a podmíněné větvení | NO | CORE / M8 | Loop má max iterations/time budget; stav lze obnovit | S14 |
| WF-03 | Load/save/clear, update data, external script, wait a notification | NO | CORE částečně / M8 | Bezpečné tasky s explicitními oprávněními; mazání a externí skripty nejsou defaultně povolené | S14 |
| EX-01 | Čitelný MQL5 source export | PARTIAL | CORE / M8 | Generovaný EA projde MetaEditor bez error/warning a nese strategy/config hash | S37 |
| EX-02 | MT5 hedging/netting varianty | NO | CORE / M8 | Export odpovídá zvolenému account modelu a projde parity suite | MT5 cíl |
| EX-03 | MT4, TradeStation, MultiCharts, JForex a jiné exporty | NO | OUT | Neimplementovat v Core v1 | rozhodnutí projektu |
| FW-01 | Paper/forward validace bez live příkazů | PARTIAL | CORE / M9 | Inkrementální očekávané obchody se porovnají s demo/forward ledgerem | projektový cíl |
| FW-02 | Live trading | NO | OUT pro rané verze | Žádné brokerské write API ani automatické live nasazení | bezpečnostní rozhodnutí |

## Rozhodnutí vyplývající z matice

1. M1 musí před M2 vytvořit neměnný datový kontrakt a broker profil.
2. M2 nesmí být schválen jen podle souhrnných metrik; vyžaduje paritu jednotlivých
   obchodů s MT5.
3. Builder M4 se nesmí rozšiřovat bez DSL z M3, jinak vzniknou další natvrdo
   naprogramované strategie.
4. AI agenti nesmí nahrazovat deterministické oracle testy.
5. Streamlit zůstává klientem. Výpočetní a datové služby nesmí záviset na UI.

Poznámka k MT5 importu: veřejná stránka S04 je k datu rešerše vnitřně rozporná.
V popisu dialogu uvádí volbu `Since last date` pro inkrementální stažení, ale v části
„Updating data later“ tvrdí, že každý import vytvoří nový instrument a nejde o
inkrementální aktualizaci. Matice proto považuje přímý MT5 import za ověřenou funkci
SQX, zatímco inkrementální verzovaný update DM-15 je samostatný požadavek naší
implementace, nikoli tvrzení o jednoznačném chování SQX.

## Zdroje

- S01: [Program layout](https://strategyquant.com/doc/strategyquant/program-layout/)
- S02: [Builder](https://strategyquant.com/doc/strategyquant/builder/)
- S03: [Settings – Data](https://strategyquant.com/doc/strategyquant/data/)
- S04: [MetaTrader 5 Direct API Data Import](https://strategyquant.com/doc/quantdatamanager/metatrader5-data-import/)
- S05: [StrategyQuant documentation index / QDM capabilities](https://strategyquant.com/doc/)
- S06: [Broker profiles](https://strategyquant.com/doc/strategyquant/broker-profiles/)
- S07: [Reliable backtesting in MetaTrader](https://strategyquant.com/doc/strategyquant/reliable-backtesting-in-metatrader/)
- S08: [Building blocks](https://strategyquant.com/doc/strategyquant/building-blocks/)
- S09: [Custom blocks](https://strategyquant.com/doc/strategyquant/custom-blocks/)
- S10: [External indicators](https://strategyquant.com/doc/strategyquant/external-indicators/)
- S11: [Settings – ATM](https://strategyquant.com/doc/strategyquant/settings-atm/)
- S12: [Settings – Money management](https://strategyquant.com/doc/strategyquant/money-management/)
- S13: [Introduction to custom projects](https://strategyquant.com/doc/strategyquant/introduction-to-custom-projects/)
- S14: [Custom projects – main concepts](https://strategyquant.com/doc/strategyquant/custom-projects-main-concepts/)
- S15: [Strategy templates](https://strategyquant.com/doc/strategyquant/strategy-templates/)
- S16: [Random groups](https://strategyquant.com/doc/strategyquant/random-groups/)
- S17: [Configuring parameter ranges](https://strategyquant.com/doc/strategyquant/configuring-parameter-ranges-for-standard-and-custom-blocks/)
- S18: [Different build modes](https://strategyquant.com/doc/strategyquant/different-build-modes/)
- S19: [Settings – Parts to improve](https://strategyquant.com/doc/strategyquant/parts-to-improve/)
- S20: [Settings – Ranking](https://strategyquant.com/doc/strategyquant/ranking-options/)
- S21: [Dismiss similar strategies](https://strategyquant.com/doc/strategyquant/builder-dismiss-similar-strategies-in-databank/)
- S22: [Databanks](https://strategyquant.com/doc/strategyquant/databank/)
- S23: [Types of robustness tests](https://strategyquant.com/doc/strategyquant/types-of-robustness-tests-in-sqx/)
- S24: [Optimization Profile and SPP](https://strategyquant.com/doc/strategyquant/optimization-profile-system-parameter-permutation-strategyquant/)
- S25: [Simple Optimization](https://strategyquant.com/doc/strategyquant/simple-optimization/)
- S26: [MT5 trading sessions](https://strategyquant.com/doc/strategyquant/reliable-backtesting-of-futures-in-mt5-trading-sessions/)
- S27: [Strategy analysis metrics](https://strategyquant.com/doc/strategyquant/results-overview/strategy-analysis-metrics/)
- S28: [List of trades](https://strategyquant.com/doc/strategyquant/results-list-of-trades/)
- S29: [Equity chart](https://strategyquant.com/doc/strategyquant/results-equity-chart/)
- S30: [Trade analysis](https://strategyquant.com/doc/strategyquant/results-trade-analysis/)
- S31: [Strategy correlation](https://strategyquant.com/doc/strategyquant/results-strategy-correlation/)
- S32: [Trades on chart](https://strategyquant.com/doc/strategyquant/results-trades-on-chart/)
- S33: [Strategy config](https://strategyquant.com/doc/strategyquant/results-strategy-config/)
- S34: [Source code](https://strategyquant.com/doc/strategyquant/results-source-code/)
- S35: [Portfolio Composer](https://strategyquant.com/doc/strategyquant/portfolio-composer/)
- S36: [Fit strategy to existing portfolio](https://strategyquant.com/doc/strategyquant/fit-strategy-to-existing-portfolio/)
- S37: [Export and test in MetaTrader](https://strategyquant.com/doc/strategyquant/export-strategy-strategyquant-test-trade-metatrader/)
- S38: [What-If simulations](https://strategyquant.com/doc/strategyquant/what-if-simulations/)
