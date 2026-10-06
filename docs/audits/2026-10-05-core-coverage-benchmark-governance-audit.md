---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "cross-consumer-benchmark-governance-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core"
audited_repository_head: "83af2a84fbc16cd2ef602bb3d4baa22c04325bc2"
audit_mode: "read_only_static_service_router_and_test_review_no_product_or_test_mutation"
audit_mutated_product_code: false
scope: "benchmark-/referenzportfolio-konstruktion in strategy backtest, performance attribution, depotcheck und risk-kpi-fallback; cross-consumer-konsistenz und -testabdeckung"
parent_task: "CORE-COVERAGE-001 (siehe asset-allocation-stochastic-core/docs/audits/2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md, Abschnitt 4)"
release_decision: "blocked_confirmed_p1"
---

# Cross-Consumer-Benchmark-Governance-Audit

## Zweck und Geltung

Dieser Audit beantwortet die im Reconciliation-Dokument
`2026-10-05-core-function-audit-coverage-and-release-readiness-reconciliation.md`
(Abschnitt 4, Auftrag `CORE-COVERAGE-001`) offen gelassene Frage: Wie viele
voneinander unabhängige Code-Konstruktionen eines „Benchmarks" existieren
tatsächlich im 5eyes-Backend, was verwenden sie je als Input, und gibt es
einen Test, der zwei dieser Konstruktionen gegeneinander validiert?

Er ergänzt, ersetzt aber nicht:

1. den
   [Strategy-Backtest-Context-/Gebühren-/Publikationsintegritätsaudit](2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md),
2. den
   [Performance-Attribution-Context- und Modellintegritätsaudit](2026-08-31-performance-attribution-context-and-model-integrity-audit.md).

Bei Widersprüchen gelten aktueller Code zuerst, danach dieser Audit, danach
die beiden vorgenannten Dokumente. Die Analyse hat **keine** Produkt- oder
Testdatei verändert; es wurde ausschließlich gelesen (Services, Router,
Tests) und keine Reproduktion über eine laufende Instanz ausgeführt.

Dieses Dokument schlägt bewusst **keine** eigene „richtige" Benchmark-
Methodik vor. Welche der vier gefundenen Konstruktionen für welchen Zweck
die fachlich richtige ist, bleibt eine Entscheidung des Modell-Owners (siehe
dieselbe Zurückhaltung wie beim KGV-Kalibrierungsfund einer früheren Runde in
diesem Projekt). Dokumentiert wird ausschließlich, was existiert, wo es
divergiert, und was ein versöhnter Vertrag entscheiden müsste.

## Kurzfazit

Es existieren **vier unabhängig voneinander codierte** Konstruktionen, die im
Produktcode oder in Kundendokumenten als „Benchmark"/„Referenz" bezeichnet
werden, plus eine fünfte, teilweise überlappende Konstruktion innerhalb des
Depotchecks selbst. Keine der vier teilt eine gemeinsame Typdefinition,
Versionierung oder einen Fingerprint. Jede beantwortet eine andere fachliche
Frage, während alle vier numerisch plausibel aussehen:

| Konsument | Was als „Benchmark" verwendet wird | Kosten | Score→Bucket-Mapping |
|---|---|---|---|
| Strategy Backtest | frei vom Aufrufer übergebener Top-Level-/Sub-Asset-Mix | eigener, konfigurierbarer `benchmark_fee_bps` | n/a (kein Risikoscore beteiligt) |
| Performance Attribution | House-Matrix-Default-Mix fürs Risikoprofil, **gleiche** CMA-Returns wie Portfolio | keine | **fehlerhaft** — rohe `final_score_x10` (0..100) direkt gegen `score_from/score_to` (1..10) |
| Depotcheck-„Performancevergleich" | ebenfalls House-Matrix-Default-Mix, aber per eigener Query + eigenem Backtest-Aufruf ohne Fee-Parameter | implizit 0 bps (Default des Backtest-Service) | **korrekt** — über kanonischen `score_bucket_from_assessment()`-Helper |
| Risk-KPI-Fallback (Information Ratio) | bei fehlendem Benchmark: die Risk-Free-Rate selbst | n/a | n/a |

Diese vier Konstruktionen sind nicht nur konzeptionell verschieden, sie
widersprechen sich teils direkt: Für denselben Mandanten liefert die
Performance-Attribution (gültiger Score z.B. 80) praktisch immer eine
degradierte Leermeldung, während der Depotcheck für exakt denselben
Risikoscore denselben House-Matrix-Gedanken korrekt auflöst — mit derselben
Datenbasis, aber einer anderen, unabhängig geschriebenen Query- und
Mapping-Kette. Kein Test im Repository prüft diese beiden Pfade gegeneinander.

## Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `BENCHMARK-GOV-001` | P1 | offen | Alle Benchmark-Konsumenten verwenden einen gemeinsamen, typisierten, versionierten Benchmark-Vertrag (Zweck, Universum, Gewichte, Kosten, FX/Waehrung, Total-/Price-Return, Fingerprint); keine vier parallelen Ad-hoc-Konstruktionen |
| `BENCHMARK-ATTRIBUTION-SCORE-001` | P1 | offen (live reproduzierbar) | Performance-Attribution mappt `final_score_x10` ausschliesslich ueber den kanonischen, validierten Bucket-Helper, nicht per Rohvergleich gegen `score_from/score_to` |
| `BENCHMARK-DEPOTCHECK-DUPLICATION-001` | P1 | offen | Depotcheck referenziert fuer seinen House-Matrix-Benchmark denselben geprueften Context (TA/RA/Policy) wie der Rest des Advisory-Pfads, statt eine dritte unabhaengige Query-Kette mit eigener Kosten-Default-Semantik zu unterhalten |
| `BENCHMARK-RISKKPI-FALLBACK-001` | P2 | offen | „Information Ratio" im produktiven Allocation-Pfad macht sichtbar, dass ihr Benchmark de facto die Risk-Free-Rate ist, statt einen gleichnamigen, aber inhaltlich anderen Kennwert als eigenstaendige Grosse zu suggerieren |
| `BENCHMARK-CROSSCONSUMER-TEST-001` | P2 | offen (Abwesenheit bestaetigt) | Mindestens ein Test belegt explizit, dass zwei der vier Konstruktionen fuer denselben Mandanten/Score/Zeitpunkt unterschiedliche Zahlen liefern koennen, und dass keine UI/PDF-Flaeche das als "denselben Benchmark" ausweist |

## Codeanker auf dem auditierten Head (`83af2a84`)

| Bereich | Codeanker |
|---|---|
| Backtest: freier Top-Level-/Sub-Asset-Benchmark-Mix, eigener `benchmark_fee_bps` | `5eyes-backend/services/backtest_strategy.py:1121-1131`; `:1265-1266`; `:1271-1273` |
| Backtest: Gewichtsnormalisierung (negativ→0, Rest auf Liquidity) | `5eyes-backend/services/backtest_strategy.py:982-1002` |
| Backtest: Risk-free fuer Sharpe aus globaler Current-CMA, 80-bps-Default | `5eyes-backend/services/backtest_strategy.py:963-979`; `:1187` |
| Backtest: unscoped Current-TA per `.first()`, 100k-CHF-Fallback | `5eyes-backend/services/backtest_strategy.py:1146-1163`; `:1176-1184` |
| Backtest: FX→CHF-Konvertierung nur im Daily-Pfad, dokumentiert | `5eyes-backend/services/backtest_strategy.py:557-624` |
| Attribution: Docstring "benchmark_returns == portfolio_returns" | `5eyes-backend/services/advisory_report.py:3789-3802` |
| Attribution: Portfolio-Weights aus TA per `.first()` | `5eyes-backend/services/advisory_report.py:3818-3837` |
| Attribution: **fehlerhafter** Score→HouseMatrix-Vergleich | `5eyes-backend/services/advisory_report.py:3839-3864` |
| Attribution: Benchmark-Returns = Portfolio-Returns (dieselbe CMA-Query) | `5eyes-backend/services/advisory_report.py:3873-3890` |
| Attribution: Methode/Quelle-Label trotz Degradation immer gesetzt | `5eyes-backend/services/advisory_report.py:3892-3903`; `:3910-3924` |
| Kanonischer, korrekt validierter Score→Bucket-Helper | `5eyes-backend/services/risk_assessment_semantics.py:330-339` |
| Kanonischer Score-Bucket-Wrapper (von Depotcheck verwendet) | `5eyes-backend/services/risk_matrix.py:23-31` |
| House-Matrix-Score-Domaene ist 1..10 (Policy-Validierung) | `5eyes-backend/services/portfolio_engine_house_matrix.py:1220-1287` |
| Depotcheck: eigene House-Matrix-Benchmark-Konstruktion (3. Query-Kette) | `5eyes-backend/routers/pdf_reports.py:1742-1782` |
| Depotcheck: eigene, striktere Current-TA-Resolution (exactly-one-or-raise) | `5eyes-backend/routers/pdf_reports.py:250-265` |
| Depotcheck: Performance-Aufruf ohne Fee-Parameter (0 bps implizit) | `5eyes-backend/routers/pdf_reports.py:1710-1739`; Default in `:1856-1866` |
| Depotcheck-PDF: "reine Analyse des empfohlenen Zielportfolios" | `5eyes-backend/routers/pdf_reports.py:1834` |
| Risk-KPI-Fallback: Benchmark = Risk-Free, Tracking-Error = Vol | `5eyes-backend/services/risk_metrics_kpi.py:146-197` |
| Risk-KPI-Fallback: eigener Docstring nennt es "degenerierten Benchmark" | `5eyes-backend/services/risk_metrics_kpi.py:24-27` |
| Produktiver Aufruf ohne jemals echten Benchmark zu uebergeben | `5eyes-backend/services/portfolio_engine_cma.py:650-675` |
| `_expected_metrics()` im Kern-Allocation-Pfad verwendet (2x) | `5eyes-backend/services/portfolio_engine.py:3956`; `:6036` |
| Kein Test prueft zwei Konstruktionen gegeneinander | kein Treffer in `5eyes-backend/tests/` (siehe Verifikation) |

## `BENCHMARK-GOV-001` — Vier Fragen, eine Bezeichnung

### Konstruktion 1: Strategy Backtest

`run_strategy_backtest()` erwartet einen frei vom Aufrufer (interaktives
Modal oder Depotcheck) übergebenen `benchmark_weights_bps`-Mix
(`services/backtest_strategy.py:1127`), normalisiert ihn ohne Fehlerpfad
(`:982-1002`: negative Gewichte werden zu 0, der Rest wird auf 10.000
reskaliert und die Differenz landet in `liquidity`) und wendet einen
eigenständigen `benchmark_fee_bps` an (`:1130`, `:1265-1266`,
`:1271-1273`), der **unabhängig** vom `strategy_fee_bps` ist. Das heißt: Der
„Benchmark" ist hier schlicht „was auch immer der Aufrufer als Vergleichsmix
und -gebühr geschickt hat" — kein kanonisches Universum, keine
Genehmigungsregel. Für die Daily-Auflösung ist eine explizite FX→CHF-
Konvertierung dokumentiert (`:557-624`); für Annual stammen die Renditen aus
`asset_class_annual_returns` ohne gleichwertige FX-Dokumentation im selben
Modul. Die bereits dokumentierten Context-/Fee-Mängel dieser Konstruktion
(`BACKTEST-CONTEXT-001`, `BACKTEST-FEE-001` im Backtest-Audit) bestehen auf
diesem Head unverändert fort (`.first()`-TA-Resolution
`:1146-1163`, 100k-CHF-Fallback `:1176-1184`, globaler 80-bps-Risk-free-
Default `:963-979`).

### Konstruktion 2: Performance Attribution

`_build_performance_attribution()` (`services/advisory_report.py:3789-3908`)
dokumentiert selbst im Docstring: Benchmark = House-Matrix-Default für den
Risikoscore, Returns = **dieselbe** aktuelle CMA wie das Portfolio
(`:3800-3802`, `:3873-3890`). Das ist mathematisch eine erwartete SAA-Tilt-
Analyse, keine Performance-Attribution mit einem eigenständigen
Benchmark-Rendite-Pfad — dieselbe Einordnung wie im Attribution-Audit vom
31.08. getroffen. Diese Konstruktion trägt zusätzlich einen eigenen,
unabhängig codierten Fehler (siehe `BENCHMARK-ATTRIBUTION-SCORE-001` unten).

### Konstruktion 3: Depotcheck-„Performancevergleich"

`_depotcheck_house_matrix_benchmark()` und `_build_depotcheck_performance()`
(`routers/pdf_reports.py:1742-1782`, `:1710-1739`) bauen **ebenfalls** einen
House-Matrix-Default-Mix für den Risikoscore — dieselbe fachliche Idee wie
Konstruktion 2, aber über eine komplett eigene, dritte Query-Kette (eigene
TA-Resolution über `_latest_target_allocation()` mit Exactly-one-or-raise,
`:250-265`; eigene Current-RA-Query ohne Wiederverwendung des in
Konstruktion 2 bereits gehärteten `_cached_current_ra_is_current()`-Helpers,
`:1750-1759`). Das Ergebnis wird dann **nicht** über die Attribution-Formel
weiterverrechnet, sondern als `benchmark_weights_bps` in exakt denselben
`run_strategy_backtest()`/`_build_backtest_data()`-Aufruf aus Konstruktion 1
gereicht (`:1712-1720`) — jedoch ohne `strategy_fee_bps`/`benchmark_fee_bps`
zu übergeben, sodass beide Pfade implizit mit 0 bps Gebühren compoundieren
(Default in der Signatur `:1856-1866`, angewendet in
`backtest_strategy.py:1265-1266`). Damit ist dieselbe "Performancevergleich"-
Seite im selben PDF-Dokument wie Konstruktion 1 technisch durch dieselbe
Rechenmaschine erzeugt, aber mit einer **anderen** Kostenannahme (0 bps statt
einer vom Berater im interaktiven Backtest gewählten Gebühr) und einer
**dritten** unabhängigen Resolution desselben "aktueller Score → House-
Matrix-Zeile"-Konzepts aus Konstruktion 2.

### Konstruktion 4: Risk-KPI-Fallback (Information Ratio)

Siehe `BENCHMARK-RISKKPI-FALLBACK-001` unten — hier wird bei fehlendem
Benchmark die Risk-Free-Rate selbst als Benchmark eingesetzt.

### Fachliche Folge

Ein Berater, der im selben Beratungsgespräch (a) den interaktiven Backtest
mit einem selbstgewählten Aktien/Anleihen-Mix öffnet, (b) die Performance-
Attribution-Sektion im Advisory-Report ansieht, (c) das Depotcheck-PDF
herunterlädt und (d) die „Information Ratio" im Risiko-Abschnitt
desselben Dokuments liest, sieht vier Zahlen, die alle „Benchmark" oder
„Referenz" heißen oder dies implizieren, aber vier unterschiedliche
Definitionen von Gewichten, Renditequelle, Kosten und Score-Mapping
verwenden. Keine davon trägt eine Version, einen Fingerprint oder eine
explizite Zweckbezeichnung, die dem Leser mitteilt, dass diese vier Zahlen
nicht gegeneinander vergleichbar sind.

### Auditvertrag

- Ein einziger `BenchmarkContract`-Typ pro Zweck (strategischer Vergleich,
  Kundenreferenz, Risikomessung, Attribution, Depotcheck) mit Universum,
  Gewichten, Rebalancing-Regel, Gültigkeits-/Versions-Zeitpunkt, Total- vs.
  Price-Return, Brutto/Netto-Kostenkonvention, Basiswährung/FX-Behandlung und
  Fingerprint.
- Jede der vier Konstruktionen referenziert diesen Typ statt einer eigenen
  Ad-hoc-Struktur; House-Matrix-basierte Benchmarks laufen über **eine**
  kanonische Resolution-Funktion (TA/RA/Policy/Score), nicht über drei.
- API, UI und PDF zeigen bei nicht vergleichbaren Werten eine explizite
  Kennzeichnung statt stillschweigend identisch benannter Felder.

## `BENCHMARK-ATTRIBUTION-SCORE-001` — Gültiger Score sucht weiterhin einen nicht existierenden Bucket

### Bestätigung auf dem aktuellen Head

Der Attribution-Audit vom 31.08.2026 dokumentierte, dass
`final_score_x10` (Domäne `0..100`) direkt gegen `HouseMatrix.score_from/
score_to` (Domäne `1..10`, siehe Policy-Validierung in
`services/portfolio_engine_house_matrix.py:1220-1287` und den kanonischen
Mapper `risk_score_bucket_from_validated_score()` in
`services/risk_assessment_semantics.py:330-339`, der `score/10 + 0.5`
rechnet) verglichen wird. Auf dem für diesen Audit untersuchten Head
`83af2a84` ist der RA-Lookup zwar seither gehärtet worden
(`_cached_current_ra_is_current()`, `advisory_report.py:3846`, Kommentar
verweist auf „Kontrollrunde 2026-09-20"), aber die **Score-Bucket-Abbildung
selbst ist unverändert fehlerhaft**:

```text
5eyes-backend/services/advisory_report.py:3847-3864
risk_score = _safe_int(getattr(ra, "final_score_x10", 0)) if ra else 0
...
HouseMatrix.score_from <= risk_score,
HouseMatrix.score_to >= risk_score,
```

Ein fachlich gültiger Score von z.B. `80` (0..100-Skala) sucht damit eine
House-Matrix-Zeile mit `score_from <= 80 <= score_to`, obwohl alle Zeilen
laut Policy-Validierung die Domäne `1..10` abdecken. Das Ergebnis ist in der
überwältigenden Mehrheit gültiger Scores `hm_row is None`, also
`_performance_attribution_empty("Keine House-Matrix-Default fuer das
Risikoprofil gefunden.")` (`:3861-3864`, `:3910-3924`) statt einer Analyse.

### Gegenbeweis im selben Repository

`services/risk_matrix.py:23-31` (`score_bucket_from_assessment()`) löst
exakt dasselbe Problem korrekt: Es ruft
`validate_risk_assessment_model_input()` und danach
`risk_score_bucket_from_validated_score()` auf — denselben kanonischen
Helper, den Konstruktion 2 ignoriert. Dieser korrekte Helper wird von
Depotcheck (`routers/pdf_reports.py:1742-1745`,
`_depotcheck_house_matrix_benchmark()`) verwendet. Für denselben Mandanten,
dieselbe RiskAssessment-Zeile und dieselbe TA liefert die Performance-
Attribution-Sektion also degradiert/leer, während der Depotcheck für das
inhaltlich identische „House-Matrix-Default-für-den-Risikoscore"-Konzept
eine echte Zeile findet — mit zwei unabhängig geschriebenen Code-Pfaden, von
denen nur einer den bereits im Repository vorhandenen validierten Helper
nutzt.

### Auditvertrag

- `_build_performance_attribution()` verwendet ausschließlich
  `score_bucket_from_assessment()` bzw. den darunterliegenden
  `risk_score_bucket_from_validated_score()`-Helper; kein Rohvergleich von
  `final_score_x10` gegen `score_from/score_to`.
- Ein Regressionstest deckt explizit die in beiden Audits (31.08. und
  05.10.) genannten Score-Randwerte `0, 25, 45, 65, 80, 95` ab und beweist,
  dass Performance-Attribution und Depotcheck für denselben Score dieselbe
  House-Matrix-Zeile referenzieren.

## `BENCHMARK-DEPOTCHECK-DUPLICATION-001` — Dritte Query-Kette statt gemeinsamer Resolution

### Befund

Depotcheck löst TA, aktuelle RiskAssessment und House-Matrix-Zeile über eine
**eigene** Funktionskette auf (`routers/pdf_reports.py:250-265`,
`:1742-1782`), die weder den in Konstruktion 2 inzwischen gehärteten
`_cached_current_ra_is_current()`-Helper noch einen gemeinsamen
„AdvisoryPublicationContext" (wie in den Context-Audits für Attribution und
Backtest gefordert) referenziert. Die TA-Resolution in Depotcheck
(`_latest_target_allocation()`) ist dabei strenger als die in Konstruktion 1
und 2 (Exactly-one-or-raise statt `.first()`), was zeigt, dass im
Repository bereits ein strengerer Standard existiert, aber nicht einheitlich
angewendet wird.

Zusätzlich übergibt `_build_depotcheck_performance()`
(`routers/pdf_reports.py:1710-1739`) an `_build_backtest_data()` weder
`strategy_fee_bps` noch `benchmark_fee_bps` — beide fallen laut
Funktionssignatur (`:1856-1866`) auf `None` und damit in
`backtest_strategy.py:1265-1266` auf `0` zurück. Der im interaktiven
Backtest-Feature vom Berater typischerweise gepflegte Kostenvertrag
(`BACKTEST-FEE-001`-Kontext) existiert für die Depotcheck-eingebettete
Variante desselben Rechenkerns schlicht nicht.

### Risiko

- Ein künftiger Fix von `BENCHMARK-ATTRIBUTION-SCORE-001` in Konstruktion 2
  behebt Depotchecks separate Konstruktion 3 nicht automatisch (und
  umgekehrt) — zwei Stellen müssen synchron gepflegt werden, bis sie
  konsolidiert sind.
- Ein Drift zwischen der TA/RA, die Depotchecks eigene Query findet, und der
  TA/RA, die der Rest des Advisory-Reports (inkl. Attribution) verwendet,
  ist durch keinen gemeinsamen Context-Hash ausgeschlossen.
- Die im selben PDF sichtbare „Performancevergleich"-Grafik suggeriert
  einen Netto-Kostenvergleich, rechnet aber brutto (0 bps), ohne dass das
  Dokument dies als Annahme ausweist (`_build_depotcheck_performance()`
  liefert kein entsprechendes Warning in den `warnings`-Pfad).

### Auditvertrag

- Depotcheck referenziert denselben kanonischen TA-/RA-/HouseMatrix-
  Resolver wie die Performance-Attribution, statt eine dritte eigene Kette
  zu pflegen.
- Wenn Depotcheck bewusst 0-bps-Brutto-Vergleich zeigen soll, wird das als
  explizite, sichtbare Annahme im PDF ausgewiesen statt implizit über eine
  fehlende Kwarg-Übergabe entschieden.

## `BENCHMARK-RISKKPI-FALLBACK-001` — Information Ratio ist strukturell Sharpe

### Befund

`compute_extended_risk_metrics()` (`services/risk_metrics_kpi.py:168-197`)
dokumentiert selbst: „benchmark nicht gegeben -> risk_free (= degenerierter
IR ~ Sharpe)" (`:182`, ausführlicher im Moduldocstring `:24-27`). Der
produktive Aufruf im Kern-Allocation-Pfad
(`services/portfolio_engine_cma.py:661-666`, aufgerufen aus
`_expected_metrics()`, das wiederum zweimal aus dem zentralen
Allocation-Generator `services/portfolio_engine.py:3956` und `:6036`
sowie aus `services/backtest_ab.py:74` und `routers/wealth.py:1521`
aufgerufen wird) übergibt an keiner der geprüften Stellen jemals
`benchmark_return_bps` oder `tracking_error_vol_bps`. Das bedeutet: Überall,
wo diese „Information Ratio" im Produktcode tatsächlich berechnet wird, ist
ihr Benchmark strukturell identisch mit der Risk-Free-Rate, die im selben
Aufruf als Sharpe-Nenner verwendet wird (`:651-666`), und ihr Tracking-Error
ist identisch mit der Portfolio-Volatilität selbst.

### Fachliche Folge

Ein Kennwert, der in Finanzberatung üblicherweise „Überrendite gegenüber
einem Vergleichsindex pro Einheit Tracking-Error" bedeutet, wird hier ohne
sichtbare Kennzeichnung durch „Überrendite gegenüber dem risikolosen Zins
pro Einheit Gesamtvolatilität" ersetzt — ein von Sharpe algebraisch kaum
unterscheidbarer Wert unter anderem Namen. Der Modulcode selbst benennt dies
korrekt als „degeneriert"; diese Einschränkung erreicht aber keinen der vier
Call-Sites und damit auch keine Kundenfläche.

### Auditvertrag

- Jede Stelle, die `information_ratio_x100` konsumiert oder ausgibt,
  entscheidet explizit zwischen zwei Optionen: (a) einen echten,
  typisierten Benchmark aus genau einer der in `BENCHMARK-GOV-001`
  geforderten kanonischen Konstruktionen übergeben, oder (b) den Kennwert
  nicht als „Information Ratio", sondern unter einem Namen ausweisen, der
  die tatsächliche Degeneration zur Risk-Free-Basis kommuniziert.
- Keine API-/PDF-/UI-Fläche zeigt `information_ratio_x100` ohne Hinweis,
  welcher Benchmark (echt oder degeneriert) ihr zugrunde liegt.

## `BENCHMARK-CROSSCONSUMER-TEST-001` — Abwesenheit eines Cross-Consumer-Tests

### Durchgeführte Prüfung

Es wurde in `5eyes-backend/tests/` nach Tests gesucht, die mehr als eine der
vier Konstruktionen gemeinsam aufrufen oder ihre Ergebnisse gegeneinander
vergleichen (Suchmuster u.a. `compute_brinson_attribution`,
`_depotcheck_house_matrix_benchmark`, `run_strategy_backtest.*benchmark`,
`compute_extended_risk_metrics`, sowie Begriffe wie „cross-consumer" oder
„reconcil"). Die Treffer liegen ausschließlich innerhalb je einer einzelnen
Konstruktion:

- `tests/test_backtest_strategy.py`, `tests/test_sub_asset_backtest_engine.py`
  testen ausschließlich Konstruktion 1 isoliert.
- `tests/test_performance_attribution.py` testet ausschließlich Konstruktion
  2 isoliert (und akzeptiert laut Attribution-Audit vom 31.08. explizit den
  degradierten Zustand als grünen Fall).
- `tests/test_risk_metrics_kpi.py`,
  `tests/property/test_risk_metrics_kpi_properties.py` testen ausschließlich
  Konstruktion 4 isoliert.
- Für Konstruktion 3 (`_depotcheck_house_matrix_benchmark`,
  `_build_depotcheck_performance`) wurde **kein dedizierter Unittest**
  gefunden, der die House-Matrix-Resolution oder die 0-bps-Fee-Übergabe
  gezielt prüft; `tests/test_depot_check.py` und
  `tests/test_depot_check_helpers.py` decken die IST-/SOLL-Drift-Logik in
  `services/depot_check.py` ab, nicht die Benchmark-Konstruktion in
  `routers/pdf_reports.py`.

### Bestätigter Befund

Es existiert kein Test, der — für denselben Mandanten, denselben
Risikoscore und denselben Zeitpunkt — beweist oder widerlegt, dass
Konstruktion 2 (Performance Attribution) und Konstruktion 3 (Depotcheck) für
dasselbe „House-Matrix-Default"-Konzept dieselbe oder eine unterschiedliche
Gewichtszeile liefern. Genau diese Divergenz wurde in diesem Audit
(`BENCHMARK-ATTRIBUTION-SCORE-001`) durch reinen Code-Vergleich aufgedeckt,
nicht durch einen fehlschlagenden Test — weil keiner existiert, der sie
hätte fangen können.

### Auditvertrag

- Mindestens ein Test instanziiert einen gemeinsamen Mandats-/RA-/TA-Fixture
  und ruft sowohl `_build_performance_attribution()` als auch
  `_depotcheck_house_matrix_benchmark()` auf; der Test schlägt fehl, wenn
  beide für denselben validierten Score unterschiedliche House-Matrix-Zeilen
  oder einen leeren vs. nicht-leeren Zustand liefern.
- Mindestens ein Test beweist, dass der interaktive Backtest (Konstruktion
  1) mit einem vom Berater gewählten Benchmark-Mix und Depotchecks
  eingebetteter Benchmark-Berechnung (Konstruktion 3) für denselben
  Mandanten unterschiedliche Zahlen liefern **dürfen**, aber dass beide
  Flächen dies für den Leser erkennbar machen (unterschiedliches Label,
  unterschiedlicher Fingerprint) statt stillschweigend „Benchmark" zu
  zeigen.

## Verifikation dieser Runde

Diese Runde hat ausschließlich gelesen: Service- und Router-Quellcode unter
`5eyes-backend/services/` und `5eyes-backend/routers/`, die zugehörigen
Testdateien unter `5eyes-backend/tests/`, sowie die beiden vorgelagerten
Audits. Es wurden keine Tests ausgeführt, keine Migration angewendet und
keine Produkt- oder Testdatei verändert (`git status` vor und nach dieser
Runde zeigt ausschließlich die neue Audit-Datei als Änderung). Die
Codezeilen-Anker wurden durch direktes Lesen der Dateien auf
`83af2a84fbc16cd2ef602bb3d4baa22c04325bc2` erhoben, nicht durch
Wiederverwendung der Zeilennummern aus den beiden älteren Audits (deren
Zeilennummern teilweise nicht mehr zutreffen, da `advisory_report.py`
zwischen dem 31.08.-Audit und diesem Head bereits einmal gehärtet wurde —
siehe `BENCHMARK-ATTRIBUTION-SCORE-001`, wo exakt das dokumentiert ist: der
Context-Teilfix wurde umgesetzt, der Score-Mapping-Fehler nicht).

Keine der vier Erweiterungs-Verträge dieses Audits wurde in Produktcode
umgesetzt. Alle Findings sind als offen zu behandeln, bis ein separater,
mutierender Fix-Audit sie schließt.

## Selbst-Audit und Nachweisgrenzen

- Dieser Audit ist eine statische Code-Lektüre ohne Laufzeit-Reproduktion
  (kein HTTP-Request, kein pytest-Lauf). Die Aussagen zu Verhalten (z.B.
  „liefert fast immer eine leere Antwort") sind aus der Codepfadlogik
  abgeleitet, nicht aus einem beobachteten Response-Objekt. Eine exakte HTTP-
  Reproduktion analog zu den beiden referenzierten Vorgängeraudits wäre der
  nächste Härtungsschritt, wurde hier aber bewusst nicht durchgeführt (reiner
  Lese-Auftrag).
- Für Konstruktion 1 (Strategy Backtest) wurden die bereits im Backtest-Audit
  vom 28.08. dokumentierten Context-/Fee-Mängel nicht erneut im Detail
  reproduziert, sondern nur ihre fortgesetzte Code-Präsenz auf dem aktuellen
  Head bestätigt (Zeilenanker oben). Für eine vollständige Neubewertung
  dieser Konstruktion gilt weiterhin der Backtest-Audit als führendes
  Dokument.
- Die Aussage zu `BENCHMARK-CROSSCONSUMER-TEST-001` ist eine Abwesenheits-
  feststellung über Grep-/Dateisuche in `5eyes-backend/tests/`, nicht über
  eine vollständige Testausführung mit Coverage-Messung. Ein Test, der
  dieselbe Semantik unter einem nicht gesuchten Namen prüft, könnte
  theoretisch übersehen worden sein; die Suche deckte jedoch sowohl
  funktionsnamenbasierte als auch themenbasierte Muster ab.
- Dieses Dokument bewertet nicht, ob eine der vier Konstruktionen für ihren
  jeweiligen Zweck „falsch" ist — nur, dass sie vier verschiedene,
  unversionierte, nicht gegeneinander getestete Antworten auf eine Frage
  geben, die ein Nutzer für dieselbe Frage halten könnte. Die Entscheidung,
  welche Konstruktion kanonisch wird oder ob alle vier mit expliziter
  Zweckkennzeichnung koexistieren, bleibt beim Modell-Owner.
- Dieser Audit ersetzt nicht `CORE-COVERAGE-002` (Depotcheck End-to-End) oder
  `CORE-COVERAGE-003` (Portfolio-Construction-Reconciliation) aus dem
  Reconciliation-Dokument; `BENCHMARK-DEPOTCHECK-DUPLICATION-001` ist ein
  Teilbefund innerhalb des hier auditierten Benchmark-Scopes, nicht eine
  vollständige Depotcheck-Prüfung.
