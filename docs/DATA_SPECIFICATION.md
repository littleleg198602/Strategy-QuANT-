# Specifikace Data Manageru

Status: schváleno 0.2; implementační balík M1.1  
Milník: M1  
Normativní slova MUST, MUST NOT, SHOULD a MAY určují závaznost.

## 1. Cíl

Data Manager vytvoří broker-accurate, verzované a reprodukovatelné vstupy pro backtest.
Primární zdroj pro v1 je lokální MetaTrader 5. CSV je podporovaný auditovatelný import.
Dukascopy a Darwinex download konektory přijdou až po stabilním MT5 importu.

Veřejná dokumentace SQX uvádí přímý MT5 import od buildu 144 a doporučuje broker data
z platformy, pokud jsou dostupná. Broker profiles v SQX nesou timezone, instrumenty a
sessions. Náš návrh tuto funkčnost implementuje vlastním datovým modelem.

Zdroje:

- [MT5 Direct API Data Import](https://strategyquant.com/doc/quantdatamanager/metatrader5-data-import/)
- [Broker profiles](https://strategyquant.com/doc/strategyquant/broker-profiles/)
- [Reliable backtesting in MetaTrader](https://strategyquant.com/doc/strategyquant/reliable-backtesting-in-metatrader/)
- [QDM capability overview](https://strategyquant.com/doc/)

## 2. Zásady

1. Surová data jsou append-only. Oprava vytvoří novou verzi datasetu.
2. Interní čas je UTC nanosecond timestamp; zdrojová i broker timezone zůstávají v
   metadatech.
3. Naive timestamp bez explicitní timezone MUST být odmítnut, pokud importní profil
   timezone neurčuje.
4. DST ambiguous/nonexistent čas MUST vyvolat chybu nebo explicitní uživatelskou
   politiku; nesmí být tiše posunut.
5. Timestamp barů MUST deklarovat start_of_bar nebo end_of_bar.
6. Každý odvozený timeframe nese vazbu na zdrojový dataset a resampler version.
7. Backtest nesmí přijmout dataset bez PASS quality gate, pokud uživatel explicitně
   nespustí diagnostický override. Override je součást run manifestu.
8. Data import je read-only vůči brokerovi a nesmí odesílat objednávky.

## 3. Identita instrumentu

Kanonický instrument je nezávislý na broker symbolu.

| Pole | Typ | Pravidlo |
|---|---|---|
| instrument_id | string | stabilní interní ID, například INDEX.US.NASDAQ100.CFD |
| asset_class | enum | forex, index_cfd, metal |
| base/quote | optional string | povinné pro Forex a kovy, pokud dává smysl |
| broker_id | string | například darwinex |
| broker_symbol | string | přesný symbol z MT5, včetně suffixu |
| display_name | string | pouze UI |
| aliases | string[] | například NAS100, NDX; nikdy ne automatická jistota |

Alias resolution MUST být jednoznačný. Pokud NAS100 mapuje na více broker symbolů,
import se zastaví a vyžádá výběr.

## 4. Broker profile

BrokerProfile v1:

| Skupina | Povinná pole |
|---|---|
| Identita | broker_id, profile_id, version, source terminal/account fingerprint |
| Čas | IANA timezone, DST rule source |
| Účet | account currency, leverage model, margin mode |
| Instrument | digits, point, tick_size, tick_value, contract_size |
| Objem | volume_min, volume_max, volume_step |
| Objednávky | stops_level, freeze_level, supported filling/order modes |
| Náklady | spread model, commission model, swap long/short, triple-swap day |
| Sessions | quote a trade sessions pro každý weekday, holidays/overrides |

Číselné hodnoty MUST zachovat zdrojovou jednotku. Převod na cash risk se provede až
pomocí konkrétního account currency conversion snapshotu.

Změna kteréhokoli pole vytváří novou profile version. Historický backtest používá
profil, který je explicitně připojen k runu; „latest“ není reprodukovatelné označení.

## 5. Kanonická schémata

### 5.1 Tick

Povinná pole:

| Pole | Typ | Omezení |
|---|---|---|
| ts_utc | int64 ns / timestamp | neklesající v rámci partition |
| bid | decimal/float64 | > 0 |
| ask | decimal/float64 | > 0 a ask >= bid |
| last | nullable float64 | > 0 pokud existuje |
| volume | nullable float64 | >= 0 |
| flags | uint32 | zdrojové MT5 flags |
| source_seq | nullable int64 | stabilní tie-break pro stejný timestamp |

Partition klíče: broker_id, broker_symbol, UTC date. Pořadí při shodném timestampu:
source_seq, jinak stabilní pořadí importu uložené v raw_row_id.

### 5.2 M1 bar

| Pole | Typ | Omezení |
|---|---|---|
| open_ts_utc | timestamp | unikátní v symbol/dataset/timeframe |
| close_ts_utc | timestamp | > open_ts_utc |
| open/high/low/close | float64 | finite, > 0, validní OHLC envelope |
| tick_volume | int64 | >= 0 |
| real_volume | nullable float64 | >= 0 |
| spread_points | nullable int32 | >= 0 |
| is_complete | bool | neúplný poslední bar nesmí do zmrazeného datasetu |
| session_id | nullable string | výsledek calendar mapping |

### 5.3 Dataset manifest

Manifest MUST obsahovat:

- dataset_id a schema_version,
- source type a source fingerprint,
- instrument_id, broker_symbol a broker profile version,
- datatype tick/M1/bar a timeframe,
- timestamp convention a source timezone,
- first/last timestamp, row count a partitions,
- raw content hashes a canonical content hash,
- import config hash a software/git version,
- resampling parent a resampler version,
- quality report ID a stav PASS/WARN/FAIL,
- created_at a immutable flag.

## 6. Zdroj A — přímý MT5 import

### 6.1 Předpoklady

- MT5 je na stejném Windows hostu nebo je dostupný přes lokální collector.
- Terminál byl spuštěn a přihlášen, aby měl symbol metadata.
- Collector ověřuje cestu k terminal64.exe.
- Uživatel vidí, že MT5 historie může být omezená nastavením Max bars/history.

### 6.2 Uživatelský vstup

- terminal instance,
- broker account/profile,
- symboly,
- datatype: M1, ticks nebo obojí,
- start/end,
- update existing dataset versus new snapshot.

### 6.3 Import pipeline

Discover terminal → fetch symbols/metadata/sessions → resolve canonical instrument →
request range → write raw partitions → canonicalize → validate → create manifest →
freeze dataset.

Import MUST logovat requested a actual range. Truncated history není úspěch; je WARN
nebo FAIL podle nastaveného minimum coverage.

### 6.4 Inkrementální update

Update načte overlap okno před posledním uloženým timestampem. Pokud se overlap liší:

- původní dataset zůstane immutable,
- vytvoří se revision report,
- nový snapshot dostane nové dataset ID,
- žádný minulý backtest se automaticky nepřepočítá.

## 7. Zdroj B — MT5 CSV/TSV

Importní profil MUST definovat:

- delimiter a encoding,
- datum/čas nebo datetime sloupec,
- formát data,
- timezone,
- timestamp convention,
- OHLC/tick sloupce a jednotky spreadu/volume,
- symbol a broker profile.

Podporujeme běžný MT5 bars export s DATE, TIME, OPEN, HIGH, LOW, CLOSE,
TICK_VOLUME, VOLUME a SPREAD. Automatická detekce MAY nabídnout návrh, ale uložený
manifest vždy obsahuje explicitní výsledné mapování.

Duplicity se nesmějí tiše řešit „keep last“. Výchozí pravidlo:

- identické řádky: deduplicate + WARN + count,
- stejný klíč, rozdílný obsah: FAIL.

## 8. Resampling

Zdroj pro vyšší timeframe je M1, nikoli již agregovaný vyšší timeframe.

Agregace:

- open = první open,
- high = maximum high,
- low = minimum low,
- close = poslední close,
- volumes = součet,
- spread_points = poslední nebo explicitně definovaná agregace; v1 používá last.

Bucket boundaries používají broker timezone a session calendar, potom se uloží v UTC.
H4/D1 nesmějí být tvořeny pouhým UTC modulo, pokud broker den začíná jinak. Týden
začíná podle explicitního profilu.

Bar je complete pouze pokud skončil bucket a neobsahuje nevysvětlený gap. Politika
gapů je v resampling configu: reject, keep-with-flag nebo session-expected.

## 9. Quality checks

| ID | Kontrola | Výchozí závažnost |
|---|---|---|
| Q01 | schéma, typy, finite a kladné ceny | FAIL |
| Q02 | high >= max(open, close), low <= min(open, close), high >= low | FAIL |
| Q03 | monotonic timestamps | FAIL |
| Q04 | identické duplicity | WARN |
| Q05 | konfliktní duplicity | FAIL |
| Q06 | ask < bid nebo záporný spread | FAIL |
| Q07 | gaps proti timeframe + session calendar | WARN/FAIL podle prahu |
| Q08 | nečekaná data mimo quote session | WARN |
| Q09 | chybějící celé obchodní dny | WARN/FAIL |
| Q10 | DST duplicate/nonexistent local times | FAIL bez explicitní politiky |
| Q11 | outlier return/spread/volume | WARN, nikdy automatický delete |
| Q12 | nulový tick/real volume | INFO/WARN dle trhu |
| Q13 | neúplný poslední bar | DROP from frozen + INFO |
| Q14 | coverage requested versus actual | FAIL pod minimem |
| Q15 | tick → M1 versus source M1 discrepancy | WARN/FAIL podle tolerance |

Quality report obsahuje počty, konkrétní rozsahy/řádky, prahy, software version a
PASS/WARN/FAIL. Oprava dat musí být samostatná transformace s vlastní verzí; report
nesmí data modifikovat.

## 10. Uložení

- Parquet pro kanonická tick/M1/bar data.
- JSON pro manifesty, profile versions a quality reporty.
- SQLite nebo PostgreSQL catalog podle nasazení; v1 lokálně SQLite.
- Large raw broker data a secrets se necommitují do GitHubu.
- Repo obsahuje pouze schémata a malé deterministické fixtures.

Content hash se počítá nad kanonickým pořadím, schématem a hodnotami, nikoli nad
náhodnými Parquet metadata. Dataset ID může být prefix SHA-256 + semantic label.

## 11. API a CLI kontrakt

Minimální application service:

- discover_mt5_terminals
- list_mt5_symbols
- import_mt5
- import_file
- update_dataset
- validate_dataset
- resample_dataset
- freeze_dataset
- list/show/diff datasets

Každá operace vrací job ID, structured status a artefakty. Dlouhá operace podporuje
cancel a restart od bezpečného checkpointu. Streamlit volá stejné služby jako CLI.

## 12. Security a privacy

- Nikdy neukládat MT5 heslo.
- Account fingerprint nesmí obsahovat tajné přihlašovací údaje.
- Collector má read-only data scope a žádnou funkci order_send.
- Logy redigují cesty a účty podle konfigurace.
- Zdrojové podmínky/licence jsou součástí provenance.

## 13. Acceptance suite M1

M1 je PASS pouze pokud:

1. dva importy stejného MT5 snapshotu mají stejný canonical hash,
2. CSV a přímý MT5 import stejného rozsahu vytvoří ekvivalentní M1 data v toleranci,
3. Europe DST spring/fall fixtures skončí očekávaným PASS/FAIL bez tichého posunu,
4. conflicting duplicate, invalid OHLC a crossed tick jsou odmítnuty,
5. session-aware H1/H4/D1 resampling sedí na ručně ověřené golden tabulky,
6. změna broker metadata vytvoří nový profile version,
7. update detekuje historickou revizi,
8. manifest reprodukuje přesný dataset po čisté instalaci,
9. paměťová spotřeba je bounded streamováním partitions,
10. Data QA Agent nevydá high/critical nález.

## 14. První referenční datasety

Schválený referenční profil:

- účetní měna: USD,
- symboly: XAUUSD, US500, NAS100, GER40 a US30,
- minimální historie: 5 let M1 a 1 rok ticků,
- přímý import: lokální MT5 na Windows, pouze čtení,
- velká historie: pouze lokálně, nikdy v GitHubu.

Darwinex nastavuje MetaTrader na New York Close: GMT+3 během amerického letního času
a GMT+2 mimo něj. Profil proto reprezentuje serverový čas jako `America/New_York +
420 minut`; nejde o evropské DST. Zdroj: [Darwinex Trading Hours in MetaTrader
terminals](https://help.darwinex.com/metatrader-time).

## 15. Stav implementace M1.1

Implementovaný první vertikální řez obsahuje:

- read-only `MetaTrader5` adaptér používající jen `symbols_get`, `symbol_info`,
  `account_info`, `terminal_info`, `copy_rates_range` a `copy_ticks_range`,
- streamování M1 po 31 dnech a ticků po dnech,
- kanonická bar/tick schémata a quality checks Q01–Q06, Q13 a Q14,
- verzované broker profily bez hesla a s hashovaným account/terminal fingerprintem,
- deterministický content hash nezávislý na Parquet metadatech,
- immutable Parquet partitions + JSON manifest/report + SQLite katalog,
- přísný CSV/TSV import včetně DST a server wall-clock převodu,
- M1 resampling do M5/M15/M30/H1/H4/D1 přes broker-local boundaries,
- CLI `terminals`, `profile-mt5`, `mt5-import`, `import-file`, `list`, `show`,
  `validate`, `resample` a `diff`.

MetaQuotes výslovně uvádí, že časové rozsahy pro `copy_rates_range` a
`copy_ticks_range` musí být zadány v UTC a že dostupnost barů je omezená historií
staženou terminálem a nastavením Max bars in chart:

- [copy_rates_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py)
- [copy_ticks_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py)

Pro úplné uzavření M1 ještě zbývá session/holiday calendar, inkrementální update s
revision reportem, tick→M1 parity a reálné referenční datasety z uživatelova MT5.
