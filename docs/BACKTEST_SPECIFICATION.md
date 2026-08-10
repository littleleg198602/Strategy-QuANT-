# Specifikace backtestovacího enginu

Status: návrh 0.1 k odsouhlasení  
Milník: M2  
Závislost: M1 Data musí mít PASS

## 1. Cíl

Engine musí být deterministický, bez look-ahead a auditovatelný na úroveň order → fill
→ position → cash/margin. Primárním referenčním enginem je MetaTrader 5 Strategy
Tester. Souhrnná equity sama o sobě není důkaz parity.

Veřejně popsané SQX režimy Selected Timeframe, M1, Real Tick s vlastním spreadem a
Real Tick s reálným spreadem jsou cílové režimy naší vlastní implementace:
[Settings – Data](https://strategyquant.com/doc/strategyquant/data/).

## 2. Neměnné vstupy runu

- dataset manifest a hash,
- broker profile version,
- strategy DSL version a hash,
- engine version,
- execution config,
- account config,
- date range a timezone display preference,
- random seed pro stochastic slippage/robustness; základní backtest je bez RNG.

Po startu runu se žádný vstup nesmí načítat přes „latest“.

## 3. Časový model a zákaz look-ahead

Každá hodnota má known_at timestamp. Strategie smí na události T číst jen data, jejichž
known_at <= T.

- Signál z baru je dostupný až po jeho close.
- Výchozí market vstup z bar-close signálu je nejdříve na následující obchodovatelné
  ceně.
- Multi-timeframe bar je dostupný až po close pomalejšího baru.
- Cross-symbol data jsou dostupná podle skutečného timestampu; forward fill je
  explicitní a nesmí překročit max staleness.
- Indikátor deklaruje warm-up; před jeho dokončením vrací unavailable, ne nulu.

Test „future mutation“ změní všechna data po T a musí potvrdit identické signály,
objednávky, fills a equity do T.

## 4. Event order

Stabilní pořadí událostí se stejným timestampem:

1. broker/session/calendar změna,
2. market data update,
3. aktivace pending orders a protective orders,
4. fills podle precision modelu,
5. position/cash/margin accounting,
6. uzavření baru a indikátory,
7. strategie vytvoří/cancel/modify intents,
8. pre-trade validation,
9. přijaté orders čekají na první dovolený fill event,
10. snapshot equity a audit log.

Konkrétní MT5 rozdíly zjištěné parity testy mohou pořadí zpřesnit. Jakákoli změna je
engine semantic version change a invaliduje golden výsledky.

## 5. Cenové domény

Engine pracuje explicitně s Bid a Ask:

- buy entry a sell exit používají Ask,
- sell entry a buy exit používají Bid,
- protective order trigger a fill pravidla jsou definována po stranách trhu dle MT5
  parity fixture,
- všechny ceny se roundují na tick_size, ne pouze digits,
- cash conversion používá tick value/contract a account currency conversion.

Spread není samostatný dodatečný poplatek, pokud už data obsahují Bid/Ask. Engine musí
zabránit dvojímu započtení.

## 6. Precision modes

### 6.1 Selected Timeframe

Používá OHLC signálního timeframe a čtyři pseudo-ticky. Intrabar cesta musí být
explicitní a parity-tested. Dokud není MT5/SQX pořadí ověřeno, režim se označí
APPROXIMATE a pro konflikt SL+TP použije konzervativní variantu.

### 6.2 M1

Každý vyšší bar se přehraje z jeho M1 barů. V rámci M1 se použije dokumentované
čtyřbodové pořadí nebo konzervativní konflikt. M1 po close nesmí ovlivnit předchozí
událost.

### 6.3 Real Tick — custom spread

Zdrojový Bid tick + custom spread v bodech instrumentu vytvoří Ask. Spread config může
být fixed nebo deterministic schedule; stochastic spread patří do robustness runu.

### 6.4 Real Tick — real spread

Použije uložené Bid/Ask. Tie-break stejného timestampu vychází ze source_seq/raw_row_id.
Tento režim je finální validační přesnost.

Každý výsledek nese precision mode a nesmí být porovnáván jako rovnocenný bez
viditelného štítku.

## 7. Order lifecycle

Stavy: CREATED, ACCEPTED, ACTIVE, PARTIALLY_FILLED, FILLED, CANCELLED, EXPIRED,
REJECTED.

Podporované order intents Core v1:

- market,
- buy/sell stop,
- buy/sell limit,
- stop loss,
- take profit,
- close/reverse,
- modify/cancel pending,
- time expiry.

Každý přechod uloží timestamp, requested price/volume, accepted rounded values, reason
a zdrojový strategy node ID.

Pre-trade validation:

- session dovoluje typ operace,
- volume min/max/step,
- price tick rounding,
- stops/freeze level,
- margin a leverage,
- max open/pending trades,
- risk/drawdown guard,
- account hedging/netting pravidla.

Neplatná objednávka se nesmí tiše přeskočit. Vznikne REJECTED record s reason code.

## 8. Fills, gapy a konflikty

- Market order se plní první dostupnou stranou trhu po přijetí.
- Pending order aktivovaný gapem se plní podle MT5 parity pravidla; nesmí dostat lepší
  cenu jen proto, že barový engine neviděl cestu.
- Slippage se aplikuje směrově nepříznivě, ledaže zvolený model explicitně dovoluje
  oboustrannou stochastic slippage.
- Pokud nízká přesnost nedokáže určit, zda byl první SL nebo TP, výsledek musí nést
  ambiguity flag. Výchozí výběr je konzervativní.
- Částečné fill se implementuje až s definovaným liquidity mode; bez něj je v1
  all-or-reject/all-fill podle referenčního MT5 CFD chování.

## 9. Positions a account model

### Hedging

Každý fill může otevřít samostatnou position identifikovanou ticketem/magic/strategy ID.
Protective orders jsou spojeny s konkrétní position.

### Netting

Jeden symbol má jednu netto position. Opačný fill position sníží, uzavře nebo otočí.
Realized a unrealized P&L se musí oddělit.

Account ledger obsahuje:

- balance,
- equity,
- cash,
- realized/unrealized P&L,
- used/free margin,
- commission a swap,
- deposits/withdrawals pouze jako explicitní externí event,
- drawdown z equity i balance.

## 10. Náklady

| Náklad | Požadované modely Core v1 |
|---|---|
| Spread | real Bid/Ask, fixed points, deterministic schedule |
| Slippage | fixed points; stochastic jen robustness |
| Commission | per side/round turn, fixed nebo volume-based |
| Swap | points, money nebo percent; long/short; triple day |
| Currency conversion | explicitní conversion series/snapshot |

Všechny náklady jsou samostatné ledger entries. Součet trade P&L se musí rovnat změně
balance po zahrnutí nákladů v toleranci zaokrouhlení.

## 11. Sizing a risk

Core v1:

- fixed volume,
- fixed cash risk podle vzdálenosti SL,
- percent balance,
- percent equity.

Sizing postup: raw risk volume → broker volume rounding down → min/max check → margin
check → accepted volume. Pokud po roundingu nelze otevřít validní volume, order je
REJECTED; nikdy se automaticky nezvýší risk.

Guardy:

- max risk per trade,
- max total open risk,
- max positions/pending,
- daily loss,
- max drawdown stop nových vstupů,
- emergency close je samostatná explicitní politika, ne automatický důsledek guardu.

## 12. Sessions

Quote session určuje dostupnost cen. Trade session určuje přijetí/aktivaci příkazů.
Kalendář může obsahovat více intervalů denně, svátky a overrides. Friday/EOD exit se
vyhodnocuje v broker timezone.

Pending order přes uzavřenou session zůstane/expiruje podle order configu. Protective
order chování při market close/open musí projít MT5 parity fixture.

## 13. Multi-timeframe a multi-symbol

Strategy DSL definuje charts:

- chart ID,
- instrument reference,
- timeframe,
- session/filter,
- max staleness.

Event queue je globální a stabilní. Pokud dva symboly mají stejný timestamp, tie-break
je canonical instrument ID. Výsledek nesmí záviset na pořadí dictionary/input files.

## 14. Trade ledger a výsledky

Minimální auditní tabulky:

- orders,
- order_events,
- fills,
- positions/position_events,
- account snapshots,
- rejected intents,
- strategy decisions.

Trade view je odvozenina ledgeru. Každý trade uvádí symbol, side, entry/exit
timestamps/prices, volume, gross P&L, jednotlivé náklady, net P&L, MAE/MFE, SL/PT,
exit reason, strategy ID a source node IDs.

Metriky musí mít samostatný dokument vzorců. NaN/zero-trade/only-wins/only-losses se
nesmí maskovat nekonečnem bez označení.

## 15. MT5 parity protocol

### Referenční sada

Nejdříve mikro-strategie, nikoli složitý generovaný EA:

1. market buy/sell na známém baru,
2. buy/sell stop a limit,
3. SL-only, TP-only, SL+TP,
4. gap přes entry/SL/TP,
5. commission/swap,
6. fixed-risk volume rounding,
7. session boundary,
8. netting reverse,
9. hedging dvě positions,
10. multi-timeframe close signal.

### Porovnání

Pro každý order/trade:

- typ a direction musí být exact,
- timestamp v toleranci jednoho zdrojového ticku; u M1 jednoho model eventu,
- cena v toleranci nejvýše jednoho tick_size, pokud fixture neurčí exact,
- volume exact na volume_step,
- reason/state exact,
- gross/net P&L v account-currency rounding toleranci.

Souhrnné limity:

- trade count exact,
- žádný extra/missing order,
- end balance/equity v odvozené rounding toleranci,
- config, data a EA hash shodné s reportem.

Rozdíl není „přijatelný“, dokud není klasifikován jako data, config, model nebo bug.

## 16. Test gates M2

- unit/property tests pro rounding, costs, sizing a lifecycle,
- future-mutation/no-look-ahead tests,
- deterministic replay hash,
- event ordering invariance,
- synthetic gaps a same-bar ambiguity,
- DST/session boundaries,
- multi-symbol input-order invariance,
- accounting conservation,
- MT5 micro parity PASS,
- benchmark bez změny výsledku mezi počtem workerů,
- Bias a Risk agent bez high/critical nálezu.

## 17. Migrace současného MVP

Současný engine zůstane dočasně označen legacy_bar_v0. Nemá se rozšiřovat o další
strategie. Po schválení M2 vznikne nový ledger engine vedle něj. Až parity suite projde,
CLI/Streamlit se přepnou na nový engine a legacy se odstraní v samostatném PR.
