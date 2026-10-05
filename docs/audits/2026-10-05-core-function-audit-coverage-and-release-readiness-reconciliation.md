---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "core-function-audit-coverage-and-release-readiness-reconciliation"
status_as_of: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core"
branch: "codex/asset-allocation-stochastic-core"
audit_mode: "read_only_reconciliation_of_existing_audits_static_code_and_test_surfaces"
audit_mutated_product_code: false
scope: "goals, stochastic engine, monte carlo, asset allocation, portfolio construction, benchmarking, depotcheck and publication"
decision: "core is deeply audited but not release-ready; close two cross-consumer audit gaps and require post-fix certification"
---

# Core-Funktions-Auditabdeckung und Release-Readiness

## Zweck

Dieses Dokument beantwortet bewusst getrennt:

1. Wurde eine Kernfunktion bereits fachlich und technisch tief auditiert?
2. Sind die dabei gefundenen Fehler umgesetzt und nachgeprueft?
3. Ist die Funktion deshalb fuer reale B2B-Beratung freigegeben?

Ein vorhandener Audit und gruene Bestandstests beweisen weder Fehlerfreiheit
noch Release-Readiness. `auditiert`, `korrigiert`, `regressionsgetestet` und
`freigegeben` sind vier verschiedene Zustände. Dieses Dokument ist eine
Bestandsaufnahme und keine fachliche, rechtliche oder produktive Freigabe.

## Kurzurteil

**Nein, die genannten Kernfunktionen sind am 05.10.2026 nicht als perfekt oder
release-ready nachgewiesen.** Ziele, Stochastik, Monte Carlo und Asset
Allocation sind aussergewoehnlich tief auditiert; gerade diese Audits enthalten
aber noch reproduzierte P1-Releaseblocker. Portfoliozusammensetzung ist durch
mehrere Fachaudits breit abgedeckt, jedoch noch nicht als ein zusammenhaengender
Empfehlungs- und Umsetzungsvertrag zertifiziert. Benchmarking und Depotcheck
sind nur fragmentiert ueber mehrere Consumer auditiert und benoetigen je einen
eigenen End-to-End-Audit.

| Kernbereich | Audit-Tiefe | Umsetzungs-/Freigabestatus | Urteil |
|---|---:|---:|---|
| Ziele und Zielerreichung | sehr hoch | offene reproduzierte P1 | nicht freigegeben |
| Stochastik und Monte Carlo | sehr hoch | offene Modell-, Evidence-, Cache- und Paritaets-P1 | nicht freigegeben |
| Asset Allocation | sehr hoch | offene Constraint-, Policy-, Risk-Budget-, CMA- und Editor-P1 | nicht freigegeben |
| Portfoliozusammensetzung / Empfehlung | hoch, aber ueber Einzelaudits verteilt | offene Eligibility-, Preference-, Holdings-, Kosten- und Handoff-P1 | nicht freigegeben |
| Benchmarking | mittel bis hoch, consumerweise | kein kanonischer Benchmarkvertrag; Querschnittsaudit fehlt | nicht freigegeben |
| Depotcheck | mittel bis hoch, komponentenweise | kein vollstaendiger IST-SOLL-End-to-End-Nachweis | nicht freigegeben |
| API/UI/PDF/Signatur/Handoff | hoch | Snapshot- und Publikationsbindung mehrfach blockiert | nicht freigegeben |

## 1. Ziele und Zielerreichung

### Was bereits tief auditiert wurde

- Zielerreichung und Bindung an Monte-Carlo-/Publikationsevidence:
  `2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md`
- Zusammenspiel aus Stochastik, Optimizer, Monte Carlo, Asset Allocation und
  Zielen:
  `2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md`
- Solver, Zielmaximierung, Rundung und Publikation:
  `2026-09-23-solver-goal-maximization-and-publication-integrity-audit.md`
- Finanzierung, Prioritaet und Attribution pro Ziel:
  `2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md`
- Gemischte Zieltypen und Sensitivitaetsevidence:
  `2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md`
- Wiederkehrende Ziele, Kalender, Lifecycle und unabhaengige MC-Validierung:
  `2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md`
- Nominal-/Realwertmodus, Inflation und Publikationsparitaet:
  `2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md`
- Gemeinsame Sensitivitaetsbasis und Publikationsintegritaet:
  `2026-10-04-goal-sensitivity-common-baseline-and-publication-integrity-audit.md`

### Warum „funktioniert perfekt“ nicht bestaetigt werden kann

Die offenen Verträge betreffen nicht Randfaelle, sondern die Bedeutung der
ausgegebenen Zielwahrscheinlichkeit: eigener Zeithorizont, wiederkehrende
Zahlungen, ueberfaellige Ziele, Funding-Reihenfolge, reale Zielwerte,
Feasibility, Gewichtung, gemeinsame Szenariobasis und Bindung an genau die
publizierte Allokation. Solange Goal-Zeilen, Gesamtscore, MC, API, UI und PDF
nicht auf ein unveraenderliches gemeinsames Analysemanifest zeigen, kann eine
plausible Prozentzahl fachlich trotzdem aus dem falschen Lauf stammen.

### Naechster sinnvoller Schritt

Kein weiterer generischer Ziel-Audit. Zuerst die bereits dokumentierten roten
Vertraege implementieren. Danach ein fokussierter **Goal Certification Run**
mit Golden Cases, Randfaellen, Metamorphic Tests, Run-Replay und
API/UI/PDF-Paritaet.

## 2. Stochastik, Monte Carlo und Asset Allocation

### Was bereits tief auditiert wurde

Der Core wurde unter anderem fuer Solver-/Zielsemantik, manuelle Zielbaender,
Editor-/Lifecycle-Kontext, Risk-Budget-Fallback, Policy-Versionierung,
House-Matrix-Constraints, Nicht-CH-CMA, Bondkurven, Korrelation/Tailmomente und
Sub-Asset-Risikoaggregation samt Cache/Replay auditiert. Besonders massgeblich
sind die Audits vom 04./05.10.2026:

- `2026-10-04-manual-target-band-and-publication-semantics-integrity-audit.md`
- `2026-10-04-target-allocation-editor-context-and-release-lifecycle-integrity-audit.md`
- `2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md`
- `2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md`
- `2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md`
- `2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md`
- `2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md`
- `2026-10-05-cma-correlation-tail-moment-and-runtime-parity-integrity-audit.md`
- `2026-10-05-sub-asset-risk-aggregation-cache-and-replay-integrity-audit.md`

### Releaseblocker in einem Satz

Effective Inputs, Policy, Constraints, Returns, Covariance/Tails, Cache-Key,
Solverresultat, MC-Pfade, Ziele, UI und Publikation sind noch nicht durchgehend
als ein unveraenderlicher, vollstaendiger und reproduzierbarer Lauf gebunden.
Darum beweisen lokale Unit Tests und plausible Ausgaben keine globale
Korrektheit.

### Naechster sinnvoller Schritt

Die dokumentierten Verträge in Abhaengigkeitsreihenfolge implementieren:

1. kanonische Domains und Evidence-Snapshots;
2. ein Effective-Input-Manifest und ein einziger Inputhash;
3. Constraint-/Policy-Compiler;
4. Solver und unabhaengige Post-Selection-Validierung;
5. Monte Carlo, Ziele und Sensitivitaet auf exakt demselben Lauf;
6. API/UI/PDF/Signatur/Handoff fail-closed an denselben Snapshot binden;
7. erst danach Core Certification Run.

## 3. Portfoliozusammensetzung und Produktempfehlung

### Vorhandene Abdeckung

Die wichtigsten Einzelvertraege sind auditiert:

- Produktstammdaten und Exposure-Integritaet:
  `2026-08-27-product-master-data-and-exposure-integrity-audit.md`
- Suitability, Appropriateness und Recommendation Eligibility:
  `2026-09-04-product-suitability-appropriateness-and-recommendation-eligibility-integrity-audit.md`
- Anlagepraeferenzen, ESG, Exclusions und Recommendation Constraints:
  `2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md`
- IST-Bestaende, Bewertung und IST-SOLL-Publikation:
  `2026-09-03-depot-current-holdings-valuation-and-ist-soll-publication-integrity-audit.md`
- Kosten, Zuwendungen und Interessenkonflikte:
  `2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md`
- Liquiditaetsinstrumente, Renditen und Funding:
  `2026-09-16-liquidity-instrument-availability-yield-and-funding-integrity-audit.md`
- Alternative Anlagen, Bewertung und Handelbarkeit:
  `2026-09-21-alternative-custom-asset-valuation-tradability-and-publication-integrity-audit.md`
- Trade-/Execution-Handoff:
  `2026-09-03-portfolio-handoff-trade-instruction-and-execution-evidence-integrity-audit.md`

### Offene Querschnittsfrage

Es fehlt ein einziger beweisbarer Weg von der freigegebenen Target Allocation
ueber Produktuniversum, Eignung, Praeferenzen, Verfuegbarkeit, Kosten,
Steuern/FX, Mindeststueckelung und bestehende Positionen bis zur finalen
Empfehlung und Ausfuehrungsanweisung. Diese Einzelvertraege duerfen nicht erst
im PDF lose zusammenlaufen.

### Neuer Auditauftrag `CORE-COVERAGE-003`

Ein **Portfolio-Construction-/Recommendation-Reconciliation-Audit** muss
insbesondere beweisen:

- RecommendationRun referenziert genau die freigegebene TargetAllocation;
- jedes Produkt war zum Entscheidzeitpunkt eligible, verfuegbar und bewertet;
- Zielgewichte, Produktgewichte, Cash/Reserve, Kosten, Steuern und Rundung
  reconciliieren ohne stillen Rest;
- bestehende Holdings, Keep/Sell/Buy und Trades sind wert- und zeitkonsistent;
- API, UI, Portfolio-PDF, Beratungsprotokoll und Handoff verwenden denselben
  immutable Run;
- stale, unvollstaendige oder fachlich nicht erklaerbare Runs blockieren die
  Publikation.

**Prioritaet:** P1 vor realer Beratung und Ausfuehrung.

## 4. Benchmarking

### Vorhandene Abdeckung

- Der Strategie-Backtest wurde auf Kontext, Gebuehren und Publikation auditiert:
  `2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md`.
- Performance Attribution wurde auf Kontext und Modellbedeutung auditiert:
  `2026-08-31-performance-attribution-context-and-model-integrity-audit.md`.

### Warum die Abdeckung nicht vollstaendig ist

Die Codeoberflaechen zeigen mehrere voneinander abweichende
Benchmark-Definitionen:

- der Backtest akzeptiert einen frei konfigurierbaren Top-Level- oder
  Sub-Asset-Mix samt eigener Benchmarkgebuehr;
- Performance Attribution nutzt automatisch den House-Matrix-Default zum
  Risikoscore und verwendet im forward-looking Modell dieselben Returns fuer
  Portfolio und Benchmark;
- der Depotcheck baut eine eigene House-Matrix-Benchmark;
- Risk-KPIs koennen bei fehlender Benchmark auf eine andere Referenzsemantik
  fallen.

Ohne Zweck- und Versionsbindung koennen alle Einzelrechnungen technisch
korrekt sein und dennoch verschiedene Fragen beantworten.

### Neuer Auditauftrag `CORE-COVERAGE-001`

Ein **Cross-Consumer Benchmark Governance Audit** muss pro Verwendung einen
typisierten Benchmarkvertrag erzwingen:

- Zweck: strategischer Vergleich, Kundenreferenz, Risikomessung, Attribution
  oder Depotcheck;
- erlaubtes Universum und Auswahl-/Genehmigungsregel;
- Gewichte, Rebalancing, Gueltigkeitszeitpunkt und Version;
- Total Return versus Price Return, brutto/netto und Gebuehren;
- Basiswaehrung, FX- und Hedgingbehandlung;
- Zeitraum, Kalender, Missing Data, Corporate Actions und Datenquelle;
- keine Survivorship-/Look-ahead-Verzerrung;
- Fingerprint und identische Verwendung in API, UI, PDF und Replay;
- klare Kennzeichnung, wenn Resultate nicht miteinander vergleichbar sind.

**Prioritaet:** P1 vor kundenwirksamem Benchmarking oder Performance-Claim.

## 5. Depotcheck

### Vorhandene Abdeckung

Holdings/Valuation, Produktdaten, Kosten, Risk KPIs, Backtest,
Performance-Attribution und Reporting sind jeweils teilweise auditiert. Der
zentrale Holdings-Audit fordert bereits einen immutable, mandatsgebundenen
Bewertungssnapshot mit Preisen, FX, Coverage und konsistenten Exposures.

### Nachgewiesene Abdeckungsluecke

Der aktive PDF-Endpunkt beschreibt den Depotcheck in
`routers/pdf_reports.py` als **reine Analyse des empfohlenen Zielportfolios**.
Damit ist nicht bewiesen, dass der Name „Depotcheck“ eine vollstaendige
Pruefung des aktuellen Kundendepots, einen sauberen IST-SOLL-Vergleich und
konkrete, eignungsgepruefte Massnahmen bezeichnet. Tests, die nur Struktur,
Seitenzahl oder degradiertes Rendering pruefen, schliessen diese semantische
Luecke nicht.

### Neuer Auditauftrag `CORE-COVERAGE-002`

Ein **Depotcheck End-to-End Integrity Audit** muss mindestens reconciliieren:

- vollstaendiges aktuelles Depot, Konten/Cash, As-of-Zeit, Preise, FX,
  Accrued Income, Bewertungsstatus und Coverage;
- Kosten, Waehrung, Konzentration, Liquiditaet, Bonitaet, Duration,
  Diversifikation und weitere ausgewiesene Risiken;
- ein zweckgebundener, versionierter Benchmark;
- IST-Performance und Cashflows getrennt von forward-looking Projektion;
- aktuelles Depot versus freigegebene Target Allocation versus konkrete
  Empfehlung/Trades;
- Tax-/Cost-/Suitability-/Preference-Wirkung jeder Handlungsempfehlung;
- identischer Snapshot und identische Warnungen in API, UI und PDF;
- fail-closed bei fehlenden, veralteten, unbewerteten oder gemischten Daten;
- sprachliche Wahrheit: Zielportfolioanalyse darf nicht als umfassender
  aktueller Depotcheck verkauft werden.

**Prioritaet:** P1 vor Nutzung des Depotchecks in realer Beratung.

## 6. Priorisierte Fortsetzung waehrend Claude implementiert

Die ressourcenschonendste Parallelroute ist:

1. `CORE-COVERAGE-001` Cross-Consumer Benchmark Governance auditieren;
2. `CORE-COVERAGE-002` Depotcheck End-to-End auditieren;
3. `CORE-COVERAGE-003` Portfolio Construction/Recommendation reconciliieren;
4. Claudes Fixes nicht nur per Diff, sondern gegen die roten
   Auditvertraege und reproduzierten Probes kontrollieren;
5. nach Umsetzung Goal Certification und Core Certification ausfuehren;
6. erst nach gruenem End-to-End-Nachweis Release-/B2B-Readiness neu bewerten.

## 7. Definition of Done fuer „perfekt“

Der Begriff soll intern erst verwendet werden, wenn alle folgenden Punkte
belegt sind:

- kein offenes P0/P1 im betroffenen Core-Pfad;
- fachliche Invarianten und bekannte Repros sind permanent getestet;
- deterministische Wiederholung oder explizit kontrollierte Zufallsbasis;
- vollständige Input-, Modell-, Policy-, Daten- und Versionsprovenienz;
- unabhaengige Post-Selection-Validierung statt Selbstbestaetigung;
- Mandats-/Tenant-/Zeit-/Waehrungsbindung und Staleness-Pruefung;
- API/UI/PDF/Signatur/Handoff zeigen denselben immutable Snapshot;
- degraded oder fehlende Evidence blockiert und wird nicht mit Defaults
  schoengerechnet;
- realistische Golden Cases, negative Tests und End-to-End-Replay sind gruen;
- unabhaengiger Re-Audit bestaetigt die Umsetzung ohne neue P1.

Bis dahin lautet der sachlich richtige Status: **tief auditiert, gezielt in
Umsetzung, aber noch nicht freigegeben**.
