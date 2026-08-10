# Strategy QuANT Core v1 — rozsah a plán dodání

Status: návrh 0.1 k odsouhlasení  
Navazuje na: SQX_FEATURE_MATRIX.md

## Výsledek Core v1

Core v1 je vlastní, auditovatelná platforma pro systematický výzkum strategií nad MT5
a Darwinex daty pro Forex, indexy a kovy. Uživatel může:

1. získat a zmrazit broker-accurate historii,
2. definovat nebo generovat pravidlové strategie,
3. provést deterministický backtest ve více přesnostech,
4. filtrovat a ukládat kandidáty,
5. provést robustnostní a optimalizační testy,
6. sestavit portfolio,
7. exportovat MQL5 a ověřit shodu v MT5,
8. spustit bezpečnou paper/forward validaci bez live příkazů.

Úspěch neznamená, že systém „najde ziskovou strategii“. Znamená, že výzkumný proces je
reprodukovatelný, bez známého biasu a že stejné strategie na stejných datech dávají
v našem enginu a MT5 výsledek v předem definované toleranci.

## Závazný rozsah

### Platforma a trhy

- Python 3.12+ pro výpočetní jádro.
- Streamlit zůstane dočasné UI; core nesmí importovat Streamlit.
- MetaTrader 5 a broker profil Darwinex.
- Forex, indexové CFD a kovy.
- Výchozí universe je konfigurovatelné; počítá s XAUUSD, XAGUSD, JP225/NI225,
  AU200, GER40/GDAXI, FCHI40, STOXX50, UK100, SPA35, NAS100/NDX, US30/WS30 a SP500.
- Broker alias nikdy nesmí být současně kanonickým ID instrumentu.

### Vyloučeno z Core v1

- živé posílání objednávek,
- MT4, TradeStation, MultiCharts, JForex a NinjaTrader export,
- Stockpicker, akcie, opce a crypto-specific účetnictví,
- cloudový/distribuovaný grid,
- mobilní aplikace,
- kopie vzhledu nebo proprietárního kódu StrategyQuant X,
- slib nebo optimalizace „garantovaného zisku“.

## Architektura

| Vrstva | Odpovědnost | Nesmí dělat |
|---|---|---|
| Data adapters | MT5, CSV a později další zdroje | rozhodovat obchodní logiku |
| Data catalog | dataset verze, hash, metadata, kvalita | tiše přepisovat historii |
| Strategy DSL | neměnná definice strategie | obsahovat UI stav |
| Execution engine | order/fill/position/cash/margin ledger | počítat indikátory z budoucnosti |
| Research engine | generace, ranking, filtry, checkpointy | měnit OOS podle výsledků |
| Robustness engine | OOS, MC, WFO/WFM, SPP | přepisovat původní run |
| Portfolio engine | společná timeline, risk, margin, váhy | jen dodatečně sčítat procenta výnosu |
| Export/parity | MQL5, kompilace, MT5 comparison | schválit export bez parity reportu |
| Application API | orchestrace a job state | obsahovat výpočetní matematiku |
| Streamlit UI | zadání, průběh a výsledky | být jediným způsobem spuštění |

Každý výpočetní run musí nést minimálně:

- run ID a čas,
- git commit/version,
- dataset ID a content hash,
- broker profile version,
- strategy DSL hash,
- execution/robustness config hash,
- random seed,
- stav PASS/FAIL jednotlivých gate.

## Milníky a pořadí

| Milník | Výstup | Vstupní podmínka | Výstupní gate |
|---|---|---|---|
| M0 Specifikace | těchto pět dokumentů | veřejná rešerše + stav main | dokumenty odsouhlasené |
| M1 Data | MT5/CSV catalog a quality report | M0 schválen | zmrazené referenční datasety |
| M2 Backtest | MT5-like order/fill engine | M1 PASS | parity suite s MT5 PASS |
| M3 Strategy DSL | univerzální strom pravidel | M2 execution contract | round-trip + semantic tests PASS |
| M4 Builder/Databank | random builder, ranking, persistence | M3 PASS | seeded reproducibility + resume PASS |
| M5 Genetic/Improver | evoluce a částečné změny | M4 stable | diversity/reproducibility tests PASS |
| M6 Robustness/Optimizer | retester, MC, WFO/WFM, SPP | M2 a M4 PASS | statistical golden tests PASS |
| M7 Portfolio | váhy, margin, korelace, risk | M2 ledger stable | portfolio accounting PASS |
| M8 Workflow/UI/Export | pipeline, dashboard, MQL5 | M1–M7 | end-to-end + compile + parity PASS |
| M9 Forward | paper/forward comparison | M8 PASS | drift and reconciliation report |

Milníky se nesmějí přeskočit způsobem, který obchází jejich gate. Paralelní UI práce je
možná jen nad schváleným API kontraktem.

## Definition of Done pro každou funkci

Funkce není hotová jen proto, že „funguje na jednom souboru“. Musí mít:

1. schválený kontrakt a edge cases,
2. typy a validační chyby,
3. unit testy a alespoň jeden integrační test,
4. golden/reference test, pokud počítá finance nebo čas,
5. deterministický výsledek při stejném seedu,
6. auditní metadata a structured log,
7. dokumentaci pro uživatele,
8. změřený výkon na referenčním datasetu,
9. žádný high/critical nález Bias nebo Risk agenta,
10. release gate v CI.

## Referenční workflow v1

Data import → quality gate → dataset freeze → Builder IS → levné filtry → OOS →
M1/tick retest → Monte Carlo → parameter stability → Walk-Forward → portfolio →
MQL5 compile → MT5 parity → paper/forward.

OOS, parity a forward data nesmějí být použita k přímému fitness výběru kandidátů.
Každý návrat k Builderu vytvoří nový experiment a musí být viditelný v auditní stopě.

## První implementační balík po schválení M0

M1.1 má dodat pouze datový základ:

- kanonická schémata ticků, M1 barů, instrumentu a broker profilu,
- přímý read-only sběrač z lokálního MT5,
- robustní MT5 CSV importer,
- UTC normalizaci bez tichého řešení DST,
- validaci, quality report, dataset manifest a SHA-256,
- Parquet storage a deterministický M1 → vyšší timeframe resampling,
- CLI a API bez povinného Streamlitu,
- referenční data fixtures a testy.

Do M1.1 nepatří generování nových strategií ani další rozšiřování současného
backtestu.

## Otevřená rozhodnutí před implementací M1

Tato rozhodnutí se mají potvrdit při review PR:

1. primární platforma běhu: Windows host s lokálním MT5 (doporučeno),
2. účetní měna referenčního Darwinex profilu,
3. první 3–5 referenčních symbolů pro parity data,
4. minimální požadovaná délka M1 a tick historie,
5. povolené ukládání surových broker dat v repozitáři versus pouze manifest/fixture.

Výchozí bezpečný návrh: reálná velká historie se do GitHubu necommitne; commitnou se
jen malé anonymní fixtures, schémata a manifesty.
