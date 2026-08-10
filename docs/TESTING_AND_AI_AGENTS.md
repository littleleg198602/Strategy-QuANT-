# Plán testování a AI agentů

Status: návrh 0.1 k odsouhlasení  
Platí pro: M1–M9

## 1. Základní pravidlo

AI agent může navrhovat testy, hledat podezřelé rozdíly, spouštět nástroje a
vysvětlovat příčinu. Nesmí být matematickým oracle a nesmí sám rozhodnout, že
nezdokumentovaný rozdíl je „dost dobrý“.

PASS/FAIL určuje strojově ověřitelný kontrakt:

- exact hash nebo explicitní numerická tolerance,
- invariant,
- schválený golden dataset,
- MT5 trade-by-trade parity,
- předem definovaný statistický test.

## 2. Vrstvy testování

| Vrstva | Frekvence | Typická délka | Účel |
|---|---|---:|---|
| L0 Static | každý commit | sekundy | typy, lint, schema a dependency checks |
| L1 Unit | každý commit | minuty | čisté funkce, edge cases, invariants |
| L2 Integration | každý PR | minuty | data → engine → artefakty |
| L3 Golden/parity | každý PR pro dotčený modul | desítky minut | stabilita vůči referenci/MT5 |
| L4 Fuzz/property | nightly | hodiny | náhodné validní i nevalidní vstupy |
| L5 Robustness/statistical | nightly/weekly | hodiny | MC/WF/SPP vlastnosti a reprodukovatelnost |
| L6 End-to-end/release | milník | hodiny až den | celý schválený workflow |

Žádný flaky test se nesmí jen opakovat do PASS. Musí mít bug ticket, vlastníka a
karanténu s časovým limitem.

## 3. Agent roles

### Specification Agent

Vstup: feature ID, specifikace, diff a testy.  
Výstup: coverage report.

Kontroluje:

- každý změněný behavior má feature/requirement ID,
- implementace nepřidává skryté chování,
- Definition of Done má test,
- dokumentace a schema version odpovídají změně.

Není oprávněn měnit scope ani automaticky schválit PR.

### Data QA Agent

Generuje a analyzuje:

- gaps, duplicates, conflicts,
- DST ambiguous/nonexistent časy,
- invalid OHLC a crossed Bid/Ask,
- outliers a neúplný konec historie,
- rozdíly MT5 direct versus CSV,
- resampling okraje sessions.

Oracle: DATA_SPECIFICATION quality rules a golden fixtures.

### Backtest Parity Agent

Orchestrace:

1. připraví data/config bundle,
2. vygeneruje/kompiluje referenční MQL5 EA,
3. spustí MT5 Strategy Tester,
4. načte MT5 order/deal report,
5. spustí náš engine,
6. provede ordered diff order/fill/trade,
7. klasifikuje první odchylku.

Agent nesmí upravit toleranci během běhu. Tolerance je verzovaná.

### Bias Agent

Hledá:

- look-ahead a nesprávné shift,
- forward-filled budoucí data,
- indikátor warm-up leakage,
- OOS použitý při builder fitness,
- selection bias po opakovaném testování,
- survivorship/alias/timezone leakage,
- závislost na pořadí symbolů.

Povinný útok: future mutation a delayed availability.

### Robustness Agent

Kontroluje:

- stejný seed = stejný výsledek,
- jiné seeds dávají rozumnou distribuci,
- analyticky známé toy cases,
- MC percentily a confidence intervals,
- stitched WFO používá pouze skutečné OOS segmenty,
- parameter perturbation nemění nepovolené parametry.

### Risk Agent

Zkouší:

- min/max/step volume,
- tick-size versus digits,
- nedostatečnou margin,
- concurrent entries,
- portfolio risk a daily loss,
- drawdown guard,
- stop/freeze levels,
- gap a extrémní spread/slippage,
- netting/hedging účetnictví.

Oracle: ledger conservation a broker profile constraints.

### UI Agent

Prochází schválené user journeys:

- import a quality report,
- vytvoření runu,
- pause/cancel/resume,
- databank filter,
- detail a provenance strategie,
- export a parity report.

UI agent nekontroluje správnost P&L; pouze to, že správné backend artefakty jsou
zobrazeny bez ztráty/změny významu.

### Release Agent

Sestaví neměnný release evidence bundle:

- commit SHA,
- test results,
- dependency/security report,
- feature coverage,
- data/config hashes,
- parity a performance reports,
- otevřené waivers.

Release Agent může vydat jen ALLOW/BLOCK podle policy. Nesmí mergeovat, nasazovat live
obchodování ani měnit policy.

## 4. Není potřeba AI všude

Klasické deterministické testy jsou správný nástroj pro:

- finanční vzorce,
- rounding,
- event ordering,
- schema validation,
- hashing,
- exact MT5 diff,
- reproducibility.

AI je přínosná pro:

- generování hraničních scénářů,
- hledání chybějící coverage,
- triage dlouhých diffů/logů,
- vytváření minimální reprodukce,
- cross-check dokumentace versus implementace,
- exploratorní UI test.

## 5. Test artefakty

Každý test run ukládá:

- test suite version,
- git SHA a environment,
- data/profile/strategy/config hashes,
- seed,
- raw report a machine-readable summary,
- první odchylku, ne jen konečný rozdíl,
- pass/fail/blocked a reason,
- odkazy na reprodukční bundle.

Velká broker data se necommitují. Evidence bundle obsahuje manifest/hash a bezpečný
způsob lokální reprodukce.

## 6. CI workflow

### Na PR

Static → unit → integration → dotčené golden tests → feature coverage →
Specification/Bias/Risk review.

M2+ změny execution semantics vždy spouštějí parity suite. M1 změny resampleru vždy
spouštějí všechny dataset hashes a následné golden backtesty.

### Nightly

- property/fuzz testy s uloženými failing seeds,
- delší multi-symbol replay,
- MC/WFO/SPP statistical suite,
- dependency/security scan,
- AI agent explorace nad změnami posledních 24 hodin.

### Milestone release

Čisté prostředí → reproduce datasets → všechny suites → MT5 full parity →
end-to-end workflow → evidence bundle → lidské schválení.

## 7. Severity a gate

| Severity | Příklad | Dopad |
|---|---|---|
| Critical | look-ahead, špatný side price, live order path | okamžitý BLOCK |
| High | missing trade, P&L/margin nesedí, dataset není reprodukovatelný | BLOCK |
| Medium | chybná metrika vedlejšího reportu, UI ztratí provenance | BLOCK milestone, lze waiver na draft |
| Low | text, ergonomie, neblokující warning | ticket; podle scope |

Waiver musí mít owner, důvod, expiry a konkrétní omezení. Critical se newaivuje.

## 8. Agent bezpečnost

- Agenti pracují jen nad test/demo účty a read-only daty.
- Žádný agent nemá broker trade permission.
- Žádný agent nesmí měnit golden reference a současně schválit její test.
- Změna tolerance/policy vyžaduje samostatný review.
- Agenti nesmí mergeovat vlastní změnu.
- Prompt/log data se nesmí stát skrytým vstupem finančního výpočtu.

## 9. První implementace agentů

Agenty nestavíme jako autonomní „tým“ před enginem. Implementace jde postupně:

1. M1: Data QA Agent jako orchestrátor deterministických quality checks.
2. M2: Backtest Parity, Bias a Risk Agent nad pevnými CLI kontrakty.
3. M3–M4: Specification Agent a builder fuzzing.
4. M6: Robustness Agent.
5. M8: UI a Release Agent.

První verze každého agenta může být CI workflow + strukturovaný report. LLM vrstva se
přidá pouze tam, kde prokazatelně zrychlí tvorbu scénářů nebo triage.

## 10. Acceptance criteria testovacího systému

- failing seed lze jedním příkazem reprodukovat,
- agent report obsahuje použitý kontrakt a evidence,
- změna seedu/configu je viditelná,
- parity tolerance není runtime prompt,
- stejné evidence vedou ke stejnému PASS/FAIL bez ohledu na model,
- při nedostupném MT5 je výsledek BLOCKED, nikdy PASS,
- release nelze označit PASS s critical/high nálezem.
