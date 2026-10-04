---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-tax-model-regime-parameter-after-tax-publication-integrity-followup-audit"
status_as_of: "2026-09-05"
audit_started_on: "2026-09-04"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "2f402b087fa38564fe51644aa8b27b34b949a618"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md"
prior_release_audit_commit: "2f402b087fa38564fe51644aa8b27b34b949a618"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-05-tax-model-regime-parameter-and-after-tax-publication-integrity-audit.md"
audit_mode: "read_only_static_ui_router_service_orm_schema_alembic_pdf_test_review_existing_focused_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "Tax residence and mandate inputs, optimizer TaxRegime resolution, per-path tax calculation, reporting cashflow tax, country tax API, reference parameters, plugin discovery, immutable run evidence, API/UI/PDF publication and reload semantics"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
static_findings_confirmed: 8
focused_existing_tests_passed: 315
focused_existing_tests_failed: 0
isolated_runtime_harness_executed: false
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "introduce one immutable TaxModelSnapshot bound to TargetAllocation and OptimizerRun; normalize and validate tax residence at persistence; make valuation year, household context, regime/provider version, parameter rows, rates, overrides, component coverage, dividend and realization assumptions, tax mode and decision/reporting equivalence explicit; route optimizer, reporting, tax API and PDF through that snapshot or fail closed"
---

# Steuerregime-/Parameter-/After-Tax-Publikationsintegritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die siebenundzwanzigste Read-only-
Kontrollrunde. Die Prüfung begann am 4. September 2026, wurde am 5. September
2026 abgeschlossen und lief gegen den unveränderten Repository-Head
`2f402b0`. Produktcode und Tests wurden nicht verändert.

Geprüft wurde nicht, ob ein konkreter Schweizer, deutscher oder anderer
Steuertarif rechtlich oder wirtschaftlich vollständig ist. Geprüft wurde der
technische Vertrag, den 5eyes selbst behauptet:

1. welches Steuerregime ein Mandat auswählt,
2. welche Steuerkomponenten im produktiven Optimizer tatsächlich wirken,
3. welcher Jahr-, Währungs-, Haushalts- und Retirement-Kontext verwendet wird,
4. welche Parameter- und Pluginversion die Rechnung bestimmt,
5. ob Entscheidungs- und Reportingpfad dasselbe After-Tax-Modell verwenden,
6. ob Run, TargetAllocation, API, UI und PDF denselben unveränderlichen
   Modellstand beweisen.

Dieser Audit ergänzt und ersetzt insbesondere nicht:

1. den unmittelbar vorherigen
   [Anlagepräferenz-/ESG-/Ausschluss-/Recommendation-Constraint-Integritätsaudit](2026-09-04-investment-preference-esg-exclusion-and-recommendation-constraint-integrity-audit.md),
2. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
3. den
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
4. den
   [Vertragsdokument-/E-Signatur-/signierte-Publikations-Integritätsaudit](2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md),
5. den
   [B2-Per-Path-Tax-Implementierungsbericht](2026-06-07-b2-per-path-tax-implementation.md),
6. sowie die weiterhin gültige
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code, Tests und Migrationen zuerst, danach
dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu früheren Findings

Der bereits bestätigte Befund `ENGCFG-SNAPSHOT-001` bleibt für die falsche
historische Engine-Disclosure maßgeblich: Der PDF-Payload liest `tax_mode` aus
dem aktuellen Setting, während der produktive Solver keinen Modus übergibt und
damit stets den Scenario-Default `median` verwendet. Diese Runde vergibt dafür
bewusst keine zweite ID.

Neu ist die vollständige fachliche Steuerkette. Selbst bei isolierter Reparatur
von `ENGCFG-SNAPSHOT-001` blieben derzeit folgende eigenständige Lücken:

- Deutschland wird im UI als Steuerregime angeboten, hat im produktiven
  Solverpfad aber effektiv keine Steuerwirkung;
- Reporting und Allokationsentscheidung können verschiedene Steuerbasen
  verwenden;
- Tarif, Parameter, Provider und Komponenten werden nicht als
  reproduzierbarer Snapshot gespeichert;
- die Country-Tax-API und der Optimizer bilden zwei verschiedene Steuerwelten;
- externe Plugins können eingebaute Regimes last-wins überschreiben, ohne
  Allowlist oder produktiven Conformance-Gate.

## Kurzurteil

Der aktuelle Stand darf **nicht** als durchgängig steuerbewusste, reproduzierbar
nach Steuern optimierte und kanalgleich publizierte Modellrechnung freigegeben
werden.

Bestätigt sind insbesondere:

1. Der produktive Mandatspfad übergibt ein `TaxRegime`, aber keine
   `dividend_yield_bps_per_bucket`. Die Scenario-Engine berechnet nur dann
   Dividendensteuer, wenn dieses optionale Array ungleich null ist, und ruft
   Kapitalgewinn-, Zins-, Vorsorge- oder Erbschaftssteuer nie auf.
2. Für CH bleibt damit im produktiven Solver nur die Vermögenssteuer. DE
   unterstützt keine Vermögenssteuer; ohne Dividendenertrag und
   Realisierungspfad ist das angebotene DE-Regime effektiv steuerneutral,
   obwohl die UI Vermögens-, Dividenden- und Kapitalgewinnsteuer ankündigt.
3. Die Reporting-Monte-Carlo-Sicht nutzt bei aktiviertem separatem Flag eine
   statische jährliche Vermögenssteuer-Cashflow-Schätzung auf dem aktuellen
   Gesamtvermögen. Der Optimizer entfernt deren Beratungsvermögensanteil und
   verwendet stattdessen dynamische Vermögenssteuer auf dem simulierten
   Beratungsvermögen. Bei ausgeschaltetem Flag bleibt Reporting steuerfrei,
   während der Optimizer weiter besteuern kann.
4. `base_calendar_year` wird aus `mandate.opened_at` statt aus einem expliziten
   Bewertungs-/Runzeitpunkt abgeleitet. `is_retired` wird einmalig berechnet
   und bleibt über den gesamten Horizont konstant. Währung, Familienstand und
   Kinderzahl fallen in der Scenario-Engine auf `CHF`, `single`, `0` zurück.
5. Der TargetAllocation-Input-Hash bindet die rohen Mandatsfelder sinnvoll und
   verhindert dadurch einige Live-Drifts. `OptimizerRun` und die gespeicherte
   Modellbasis enthalten jedoch weder Tarif-/Plugin-/Parameter-Version noch
   effektive Raten, Override-Hash, Komponentenabdeckung, Tax-Mode oder
   Bewertungsjahr.
6. Die read-only `/tax/estimate`-API besitzt nur einen CH-Country-Pluginpfad,
   während der Optimizer CH, DE und Generic kennt. Ein Request für ein nicht
   vorhandenes Jahr kann auf eingebaute 2026-Parameter zurückfallen, aber das
   Ergebnis mit dem angefragten Zukunftsjahr beschriften. Eine angefragte
   Fremdwährung wird ohne Konversion oder Fehler als CHF beantwortet.
7. `tax_parameter_sets` besitzt weder Domain-Checks noch eine eindeutige
   Current-Version pro Land/Region/Jahr. Doppelte Current-Zeilen können sich
   beim Dict-Aufbau überschreiben; malformed Rows werden übersprungen, ein
   beliebiger nichtleerer Partialbestand verhindert den vollständigen
   Fallback. DB-Version und Quelle werden nicht an den Pluginoutput gebunden.
8. Beim Boot wird jedes installierte Entry-Point-Paket der Gruppe
   `5eyes.tax_regime` geladen. Registry-Doppelbelegung ist ausdrücklich
   last-wins; es gibt im produktiven Startpfad weder Allowlist noch
   Signatur-/Paketpinning noch ausgeführten `ConformanceContract`.
9. Mandatsschemas akzeptieren freie Steuerjurisdiktionsstrings. Persistenz
   prüft lediglich Flag-/Override-Abhängigkeiten, nicht Normalform oder
   tatsächlich unterstützte Auflösung. Lowercase, dokumentiertes `DE-BY` und
   andere IDs können erst beim Solver scheitern beziehungsweise in Generic
   fallen.
10. Die UI bietet `*` als „Generisch (Flat-Rate)“ an, besitzt aber keine
    Eingabe für die dafür zwingend erforderlichen Overrides. Die Auswahl ist
    damit über die sichtbare Oberfläche nicht ausführbar.

Der fokussierte Bestands-Gate mit 315 bestandenen Tests bestätigt vorhandene
Einzelverträge. Er enthält jedoch keinen produktiven End-to-End-Negativfall,
der für ein DE-Mandat eine echte After-Tax-Differenz, für CH/DE vollständige
Komponentenabdeckung oder für API/PDF/Reload dieselbe unveränderliche
Tarifbasis fordert.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `TAX-EFFECT-001` | P1 | bestätigt | Der produktive Solver wendet faktisch nur Vermögenssteuer an; DE bleibt ohne Dividend-Yields und Realisierungsmodell steuerneutral, während die UI Dividenden- und Kapitalgewinnsteuer behauptet. |
| `TAX-MODEL-SPLIT-001` | P1 | bestätigt | Allokationsentscheidung und Reporting-Simulation verwenden abhängig von einem separaten Flag dynamische, statische oder keine Steuerbasis. |
| `TAX-CONTEXT-001` | P1 | bestätigt | Mandatseröffnung wird als Steuer-Basisjahr verwendet; Retirement, Währung und Haushaltskontext sind über den Horizont falsch oder unvollständig. |
| `TAX-SNAPSHOT-001` | P1 | bestätigt | Weder OptimizerRun noch TargetAllocation besitzen einen vollständigen unveränderlichen TaxModelSnapshot mit Regel-, Parameter- und Komponentenprovenienz. |
| `TAX-API-001` | P1 | bestätigt | Country-Tax-API und Optimizer sind getrennte Modellwelten; Jahresfallback und Währungsantwort können die Requestsemantik falsch beschriften. |
| `TAX-PARAM-001` | P1 | bestätigt | TaxParameterSet erzwingt keine eindeutige, gültige Current-Parameterbasis und propagiert DB-Version/Quelle nicht in die Berechnung. |
| `TAX-PLUGIN-001` | P1 | bestätigt | Automatische externe Plugin-Discovery ist nicht allowlist-, conformance- oder snapshotgebunden und kann Built-ins last-wins überschreiben. |
| `TAX-INPUT-001` | P2 | bestätigt | Steuerjurisdiktionen sind frei und nicht kanonisiert persistierbar; sichtbare Generic-Auswahl ist ohne sichtbare Overrides unbrauchbar. |

## Positivkontrollen, die erhalten bleiben müssen

Die Reparatur darf folgende bestehende Kontrollen nicht zurückbauen:

1. Ohne `tax_jurisdiction` bleibt der Legacy-Pfad ausdrücklich tax-naiv.
2. Overrides ohne Jurisdiktion und Generic-Regimes ohne Overrides blockieren
   im produktiven Solver fail-closed.
3. Unbekannte CH-Kantone blockieren im Optimizer statt still auf einen
   Schweizer Durchschnitt zurückzufallen.
4. `TaxContext` und `TaxResult` sind immutable Dataclasses; `TaxResult`
   besitzt bereits Felder für Regime-ID, Tarifversion, Breakdown, Overrides
   und Warnungen.
5. `TaxEstimateResult` prüft, dass die Summe der Komponenten dem Total
   entspricht.
6. Country- und Currency-Codes des Tax-API-Requests werden normalisiert.
7. Der Reporting-Cashflow wird im Optimizer nicht einfach doppelt zur
   dynamischen Steuer addiert: Der ersetzte Beratungsvermögensanteil wird
   entfernt, der externe Rest bleibt bewusst erhalten.
8. Die rohen Steuerkonfigurationsfelder liegen im Projection-/Input-Snapshot;
   eine nachträgliche Mandatsänderung verändert damit den Input-Hash und kann
   einen Reload blockieren.
9. `optimization_model_basis` wird in `effective_constraints_json` gespeichert
   und beim Reload unverändert wiederverwendet.
10. Der CH-Country-Pluginpfad kennzeichnet seine vereinfachte Schätzung und
    einen konservativen Regionsfallback in den Annahmen.
11. Seed, Pfadzahl, Gewichte, Status, Constraints, Stress- und Restartdaten
    werden bereits pro OptimizerRun persistiert.
12. Der Bestands-Gate deckt Regime-Basisfunktionen, Per-Path-Modi, Tax-API,
    Cashflowableitung, Runtime-Auflösung und PDF-Rendering breit ab.

## Tatsächlicher Steuerfluss

```text
Mandate
  tax_jurisdiction / tax_overrides_json
        |
        v
_build_tax_solver_kwargs()
  - resolve TaxRegime class
  - optional canton factory
  - apply overrides
  - base year = opened_at.year
  - one static is_retired flag
  - no dividend-yield input
        |
        v
OptimizerContext
  tax_regime
  dividend_yield_bps_per_bucket = None
  no tax_mode field
        |
        v
simulate_wealth_paths(..., tax_mode default="median")
  - dividend tax only if yields > 0       -> productive path: off
  - annual wealth tax if supported       -> CH: on, DE: off
  - no interest/capital-gains/pension/inheritance call
        |
        +-------------------------------+
        |                               |
        v                               v
Allocation decision                 TargetAllocation evidence
after dynamic CH wealth tax         tax_basis only as short label
                                    raw mandate fields only in input hash
                                    no immutable TaxModelSnapshot

Separate reporting path
  tax_estimate_in_cashflow_enabled = false
      -> no tax cashflow
  tax_estimate_in_cashflow_enabled = true
      -> fixed annual wealth-tax estimate on current total wealth
      -> reporting MC consumes fixed cashflow

Separate /tax/estimate path
  country-level TaxJurisdiction registry
  CH only
  DB parameter mapping or built-in 2026 fallback
  not the optimizer TaxRegime instance or its snapshot

Separate PDF engine-configuration path
  latest arbitrary OptimizerRun + current settings.mc_default_tax_mode
  not the effective TargetAllocation TaxModelSnapshot
```

## Komponenten- und Consumer-Matrix

| Consumer | Regimequelle | tatsächlich berechnete Komponenten | Jahr/Währung | persistierte Evidenz |
|---|---|---|---|---|
| Produktiver Optimizer CH | `TaxRegime` Registry, CH/CH-* | Vermögenssteuer; Dividende nur bei extern geliefertem Yield, produktiv keiner | `opened_at.year`; TaxContext-Default CHF | kurzer `tax_basis`-String + rohe Mandatsfelder im Input-Hash |
| Produktiver Optimizer DE | `TaxRegime` Registry, DE | keine Vermögenssteuer; produktiv keine Dividende/CG | `opened_at.year`; Default CHF trotz DE-Local-Currency EUR | `none_effective_DETaxRegime` |
| Produktiver Optimizer Generic | Catchall plus Pflicht-Overrides | praktisch nur konfigurierte Vermögenssteuer; Dividend nur mit fehlendem Yieldinput | `opened_at.year`; Default CHF | Generic-ID statt angefragter fachlicher Jurisdiktionsidentität |
| Reporting-/Goal-MC, Flag aus | Cashflowprojektion | keine automatisch abgeleitete Steuer | Cashflow-Startjahr/Target-Currency | `tax_basis=configured_cashflows` |
| Reporting-/Goal-MC, Flag an | `derive_tax_cashflow` über selben Regime-Resolver | feste Vermögenssteuer-Schätzung auf heutigem Gesamtvermögen | `opened_at.year`; Label in Mandatswährung | `tax_basis=estimated_wealth_tax_cashflow` ohne Tarifdetails |
| `POST /tax/estimate` | separate Country-`TaxJurisdiction` Registry | CH Einkommen, Vermögen, private/business Capital Gains | Requestjahr im Output; Rechnung ggf. Built-in 2026; Output immer CHF | Response-Tariflabel aus Pluginkonstante, DB-Zeilenquelle verloren |
| PDF Compliance-Audit | aktuelles Setting + jüngster Run | keine Berechnung, reine Disclosure | heutige Settings | kein TA-/Tax-Snapshot-Anker |
| Frontend Monte-Carlo-Detail | Reporting-`model_basis` | zeigt Performancepfade | Reportingbasis vorhanden, `tax_basis` aber nicht gerendert | keine sichtbare Steuerbasis |

## Codeanker auf dem auditierten Head

| Aussage | Beleg |
|---|---|
| Freie Mandatsfelder für Steuerjurisdiktion, Overrides und Reportingflag | `5eyes-backend/models/mandates.py:44-71`; `5eyes-backend/schemas/mandates.py:34-36`; `5eyes-backend/schemas/mandates.py:75-84` |
| Persistenzvalidator prüft nur Abhängigkeiten, nicht Normalform/Support | `5eyes-backend/services/mandate_model_inputs.py:77-100`; `5eyes-backend/routers/mandates.py:148-165` |
| UI bietet CH, DE und Generic an und behauptet drei Steuerarten | `5eyes-electron/frontend/5eyes_v2.html:4006-4021` |
| UI speichert keinen Generic-Override | `5eyes-electron/frontend/5eyes_v2.html:17905-17909`; `5eyes-electron/frontend/5eyes_v2.html:17949-17958` |
| Produktiver Resolver, Generic-Pflichtoverride und Basisjahr aus `opened_at` | `5eyes-backend/services/portfolio_engine_optimizer_integration.py:144-212` |
| Produktiver Context-Aufbau reicht nur die erzeugten Tax-Kwargs durch | `5eyes-backend/services/portfolio_engine_optimizer_integration.py:337-372` |
| OptimizerContext besitzt Regime/Yields/Jahr/Alter/Retirement, aber keinen Tax-Mode | `5eyes-backend/services/optimizer/solver.py:132-181` |
| Solver ruft Scenario-Engine ohne Tax-Mode auf | `5eyes-backend/services/optimizer/solver.py:270-283` |
| Scenario-Engine-API und Default `tax_mode="median"` | `5eyes-backend/services/optimizer/scenario_engine.py:406-420` |
| Dividendenertrag wird nur aus optionalem Yield-Array gebildet | `5eyes-backend/services/optimizer/scenario_engine.py:509-515`; `5eyes-backend/services/optimizer/scenario_engine.py:543-559` |
| Scenario-Loop ruft nur Dividend- und Vermögenssteuer auf | `5eyes-backend/services/optimizer/scenario_engine.py:531-568` |
| Unbekannter Tax-Mode fällt implizit in Binning statt zu blockieren | `5eyes-backend/services/optimizer/scenario_engine.py:312-403` |
| DE besitzt Dividenden-/CG-Rate, aber keine Vermögenssteuer | `5eyes-backend/services/tax/regimes/de.py:21-40` |
| CH-/Kantonregime und pauschale Raten | `5eyes-backend/services/tax/regimes/ch.py:22-115` |
| Reportingsteuer ist nur fixe Vermögenssteuer-Schätzung | `5eyes-backend/services/wealth_cashflows.py:355-421` |
| Reporting-Cashflow und dynamischer Optimizerpfad werden bewusst getrennt | `5eyes-backend/services/portfolio_engine.py:1927-2019` |
| Projection-Snapshot bindet rohe Steuerfelder, Geburts- und Eröffnungsdaten | `5eyes-backend/services/portfolio_engine.py:2237-2324` |
| Modellbasis speichert nur grobe Tax-Basislabels | `5eyes-backend/services/portfolio_engine.py:2552-2791`; `5eyes-backend/services/portfolio_engine.py:3958-3962` |
| OptimizerRun besitzt keine Tax-Snapshotfelder | `5eyes-backend/models/allocation.py:146-193`; `5eyes-backend/schemas/allocation.py:355-377` |
| OptimizerRun-Persistenz schreibt nur allgemeine Solverartefakte | `5eyes-backend/services/portfolio_engine_optimizer_integration.py:1221-1347` |
| TaxParameterSet ohne Checks/Current-Unique | `5eyes-backend/models/tax.py:13-25`; `5eyes-backend/alembic/versions/c91f2c722881_baseline_schema.py:135-151` |
| Parameterquery filtert Current/Jahr, sortiert nur Region und überspringt malformed JSON | `5eyes-backend/services/tax/parameters.py:60-91` |
| Tax-API bindet nur das Parameter-Dict, nicht Zeilenprovenienz | `5eyes-backend/routers/tax.py:22-68` |
| CH-Country-Plugin behält konstante Version und 2026-Annahme | `5eyes-backend/services/tax/jurisdictions/ch.py:88-118` |
| CH-Country-Plugin beschriftet Ergebnis mit Requestjahr und CHF | `5eyes-backend/services/tax/jurisdictions/ch.py:145-164`; `5eyes-backend/services/tax/jurisdictions/ch.py:176-194` |
| Regime-Registry überschreibt doppelte Patterns last-wins | `5eyes-backend/services/tax/registry.py:35-79` |
| Boot lädt externe Entry-Points ohne Allowlistargument | `5eyes-backend/main.py:82-99`; `5eyes-backend/services/tax/discovery.py:67-125` |
| ConformanceContract existiert, wird produktiv aber nicht ausgeführt | `5eyes-backend/services/tax/conformance.py:78-115`; `5eyes-backend/tests/tax/test_conformance.py:25-128` |
| PDF-Steuermodus stammt aus Live-Settings | `5eyes-backend/services/advisory_report.py:3517-3529`; `5eyes-backend/services/advisory_report.py:3559-3607` |
| PDF rendert diesen Wert als Tax-Modus | `5eyes-backend/services/pdf/components/compliance_audit.py:268-300` |
| Frontend zeigt Reporting-Methodik, aber nicht deren `tax_basis` | `5eyes-electron/frontend/5eyes_v2.html:7349-7366` |
| B2-Bericht erklärte Realisierungs-CG und produktive Mode-Entscheidung ausdrücklich als out of scope | `docs/audits/2026-06-07-b2-per-path-tax-implementation.md:145-152` |
| Früherer Audit hält Live-Setting-/Solver-Mode-Drift bereits als `ENGCFG-SNAPSHOT-001` offen | `docs/audits/2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md:413-450` |

## `TAX-EFFECT-001` – Steuer-aware Claim übersteigt die produktive Berechnung

### Beobachtung

`_build_tax_solver_kwargs()` liefert dem produktiven Context ein Regime,
Basisjahr, optional Alter und einen einmaligen Retirementstatus. Es liefert
kein Dividend-Yield-Array und kein Realisierungsmodell. Der einzige produktive
Caller baut `context_kwargs` genau aus diesen Feldern.

Die Scenario-Engine kann theoretisch Dividendensteuer berechnen. Dafür muss
`dividend_yield_bps_per_bucket` gesetzt sein und einen positiven gewichteten
Yield ergeben. Direkte Unit-/Integrationstests liefern dieses Array manuell;
der Mandats-/TargetAllocation-Pfad tut es nicht.

Im jährlichen Loop existieren nur zwei Tax-Calls:

1. `tax_regime.dividend_tax(...)`, bedingt durch den fehlenden Yieldinput,
2. `tax_regime.annual_wealth_tax(...)`, bedingt durch
   `supports_wealth_tax`.

`interest_tax`, `capital_gains_tax`, `pension_lumpsum_tax` und
`inheritance_tax` sind zwar Teil des Protocols und der einzelnen Regimes, aber
kein Bestandteil dieses produktiven Vermögenspfads. Der frühere B2-Bericht
kennzeichnete Realisierungs-Capital-Gains ausdrücklich als out of scope.

Die Konsequenz ist regimespezifisch:

- CH: pauschale/Kanton-Vermögenssteuer wirkt; Dividend und CG wirken nicht.
- DE: Vermögenssteuer ist korrekt deaktiviert; ohne Dividend/CG bleibt der
  vollständige Tax-Drag null.
- Generic: Nur ein gesetzter Wealth-Tax-Override kann produktiv wirken; andere
  sichtbare Rate-Overrides benötigen ebenfalls fehlende Bemessungsgrundlagen.

Dem steht die UI-Aussage gegenüber, die Auswahl aktiviere Vermögens-,
Dividenden- und Kapitalgewinnsteuer „je nach Regime“.

### Risiko

Die Optimierung kann eine Vor-Steuer-Allokation als steuerbewusst darstellen.
Bei DE ist der Unterschied besonders hart: ein fachlich steuerpflichtiges
Regimeobjekt wird im produktiven Zielpfad effektiv zu keiner Steuerwirkung.
Dadurch können Zielwahrscheinlichkeiten, Allokationsvergleich und
Kundenkommunikation denselben Begriff mit verschiedener Bedeutung verwenden.

### Verbindlicher Fixvertrag

- Für jede unterstützte Jurisdiktion ist eine explizite
  `enabled_tax_components`-Liste festzulegen.
- Dividendenerträge müssen aus versionierten Instrument-/Subasset-Daten oder
  einer klar benannten, gesnapshotteten Modellannahme entstehen.
- Realisierte Gewinne benötigen eine definierte Turnover-, Cost-Basis- und
  Holding-Period-Logik; ohne diese Logik darf Capital-Gains nicht behauptet
  werden.
- Zins-, Vorsorge- und Erbschaftskomponenten sind entweder produktiv zu binden
  oder ausdrücklich als nicht modelliert zu publizieren.
- Bis zur Implementierung muss DE als „keine produktive After-Tax-Wirkung“
  gekennzeichnet oder für tax-aware Optimierung blockiert werden.
- Ein produktiver E2E-Test muss mit identischem Seed/CMA/Cashflow für DE einen
  beweisbaren Brutto-/Netto-Unterschied und die erwartete Komponente zeigen.

## `TAX-MODEL-SPLIT-001` – Entscheidung und Reporting verwenden verschiedene Steuerwelten

### Beobachtung

Das Mandat besitzt zwei unabhängig wirkende Schalter:

1. `tax_jurisdiction` aktiviert den dynamischen Solverpfad,
2. `tax_estimate_in_cashflow_enabled` fügt eine statische Reportingausgabe
   hinzu.

`derive_tax_cashflow()` berechnet genau eine jährliche Vermögenssteuer auf dem
aktuellen Gesamtvermögen. Diese feste Ausgabe geht in Reporting, Reserve und
Goal-Monte-Carlo ein. Vor dem Optimizer wird der auf das Beratungsvermögen
entfallende Anteil entfernt, weil der Scenario-Loop diesen Teil dynamisch
berechnet; der externe Rest bleibt erhalten. Das ist ein sinnvoller Schutz vor
Doppelzählung, aber kein gemeinsames Modell.

Damit entstehen mindestens drei fachliche Zustände:

- Jurisdiktion gesetzt, Reportingflag aus: Entscheidung nach dynamischer CH-
  Vermögenssteuer; Reportingpfade ohne automatisch abgeleitete Steuer.
- Jurisdiktion gesetzt, Reportingflag an: Entscheidung nach dynamischer Steuer
  auf simuliertem Beratungsvermögen; Reporting nach fixer Schätzung auf
  heutigem Gesamtvermögen.
- DE gesetzt: dynamischer Solver ohne effektive Komponente; Reportingflag kann
  ebenfalls keinen Wealth-Tax-Cashflow erzeugen.

Die API-Modellbasis unterscheidet diese Sichten erfreulicherweise als
`optimization.tax_basis` und `reporting.tax_basis`. Sie speichert aber nur
Kurzlabels, und das Frontend rendert das Reporting-`tax_basis` nicht.

### Risiko

Die Zielwahrscheinlichkeit, die eine Allokation auswählt, und die
Zielwahrscheinlichkeit, die anschließend erklärt wird, können unterschiedliche
Steuerbelastungen enthalten. Das ist keine bloße Anzeigeabweichung, sondern
eine unterschiedliche wirtschaftliche Modellbasis unter demselben Mandat.

### Verbindlicher Fixvertrag

- Entscheidung und Reporting erhalten denselben `TaxModelSnapshot` und dieselbe
  Komponenten-/Parameterbasis.
- Falls unterschiedliche Approximationsmodi fachlich gewollt sind, wird eine
  maschinenlesbare Equivalence-/Difference-Analyse mit erwarteter Abweichung
  gespeichert und sichtbar gemacht.
- Ein separates Reportingflag darf nicht still die wirtschaftliche Semantik
  eines bereits steuerbewusst optimierten Mandats wechseln.
- API, UI und PDF nennen für beide Sichten Regime, Komponenten, Basis,
  Bewertungsjahr und Approximation.
- E2E-Tests vergleichen Decision- und Reportingpfade bei Flag an/aus für CH,
  DE und tax-naiv.

## `TAX-CONTEXT-001` – Steuerjahr und Haushaltszustand sind nicht simulationszeitgerecht

### Beobachtung

Der produktive Resolver interpretiert die ersten vier Zeichen von
`mandate.opened_at` als `base_calendar_year`. Ein im Jahr 2021 eröffnetes, im
Jahr 2026 neu berechnetes Mandat simuliert damit ab Steuerjahr 2021. Fehlt ein
parsebares Eröffnungsdatum, wird dagegen das heutige Jahr verwendet.

Das Alter wird relativ zu diesem Eröffnungsjahr berechnet. `is_retired` wird
einmal am Start bestimmt und dann unverändert durch jeden Simulationsschritt
gereicht. Ein Kunde, der während eines 30-Jahres-Horizonts in Rente geht,
wechselt im TaxContext daher nie die Phase.

`TaxContext` sieht außerdem `currency_code`, `marital_status` und
`children_count` vor. Die Scenario-Engine setzt diese Felder nicht; sie bleiben
auf `CHF`, `single` und `0`. Die aktuellen pauschalen CH-/DE-Regimes nutzen
diese Felder nur begrenzt, der öffentliche Pluginvertrag kündigt aber gerade
länder- und haushaltssensitive Regimes an.

### Risiko

Ein steuerlicher Regelstand kann für das falsche Jahr gewählt und ein
Lebensphasenwechsel über Jahrzehnte ignoriert werden. Erweiterte Plugins können
außerdem mit einer falschen Währung oder falschem Familienstatus rechnen,
obwohl das Protocol vollständigen Kontext suggeriert.

### Verbindlicher Fixvertrag

- `calculation_as_of` beziehungsweise `valuation_year` wird serverseitig beim
  Run festgelegt; `opened_at` bleibt ausschließlich Mandatshistorie.
- Alter und Retirementstatus werden pro Simulationsjahr aus gesnapshotteten
  Lebensphasenereignissen abgeleitet.
- Jeder vom Regime benötigte Kontext ist als Required-Capability zu deklarieren;
  fehlende Pflichtfelder blockieren vor dem Solver.
- Currency und Betragsbasis müssen zum Regime passen oder über einen
  gesnapshotteten FX-Vertrag konvertiert werden.
- Tests decken Altmandate, Retirement innerhalb des Horizonts, EUR/CHF sowie
  verheiratete/Single-Kontexte ab.

## `TAX-SNAPSHOT-001` – Die steuerliche Entscheidungsbasis ist nicht reproduzierbar gespeichert

### Beobachtung

Der Projection-/Input-Snapshot enthält bereits die rohen Mandatsfelder
`tax_jurisdiction`, `tax_overrides_json`, Reportingflag, Geburtsjahr,
Eröffnungsdatum und Retirementjahr. Das ist ein wertvoller Driftanker.

Er beweist aber nicht, was aus diesen Inputs tatsächlich aufgelöst wurde. Ein
später veränderter Built-in-Tarif, ein überschriebenes Plugin oder eine andere
Parameterzeile kann unter demselben Mandatsstring eine andere Rechnung
erzeugen. `OptimizerRun` persistiert keine der folgenden Informationen:

- konkrete Regime-/Provider-/Paketidentität,
- Tarif- und Conformance-Version,
- ParameterSet-IDs, Versionen, Quellen oder Content-Hash,
- effektive Raten und angewandte Overrides,
- aktivierte beziehungsweise nicht modellierte Komponenten,
- Dividend-Yields, Realisierungs-/Cost-Basis-Annahmen,
- Tax-Mode/Binzahl,
- Berechnungsjahr, Währung und Haushaltssnapshot.

`optimization_model_basis.tax_basis` ist nur
`median_rate_<Klassenname>`, `none_effective_<Klassenname>` oder `none`. Dieses
Label ist hilfreich, aber nicht hinreichend für Replay oder Tamper-Prüfung.

### Risiko

Historische TargetAllocations und Goal-Wahrscheinlichkeiten können nach einem
Code-, Parameter- oder Pluginwechsel nicht beweisen, welcher Steuerstand sie
erzeugt hat. Ein heutiger Reload kann zwar rohe Inputdrift erkennen, nicht aber
semantischen Rule-Drift bei identischen Inputs.

### Verbindlicher Fixvertrag

Ein unveränderlicher `TaxModelSnapshot` wird spätestens vor Context-Aufbau
erzeugt und an TargetAllocation **und** OptimizerRun gebunden. Pflichtfelder:

- Snapshot-ID, Schema-/Engine-/Scenario-Version und `created_at`;
- Mandat-/TA-/Run-ID sowie Input-/Allocation-Context-Hash;
- normalisierte Tax-Residence, Country, Region, Währung und `as_of`;
- Regime-ID, Provider/Package, Version, Distribution-Hash und
  Conformance-Version;
- ParameterSet-IDs, Jahr, Version, Quelle, Gültigkeit und kanonischer
  Content-Hash;
- normalisierte Overrides plus Hash und Actor-/Evidence-Anker;
- Tax-Mode, Binzahl und effektive Komponentenabdeckung;
- Yields, Realisierungs-, Cost-Basis-, Turnover- und Holding-Annahmen;
- Haushalts-/Lebensphasenkontext;
- getrennte Decision-/Reporting-Konfiguration plus Gleichheits- oder
  Abweichungsnachweis.

Historische Reads verwenden ausschließlich diesen Snapshot. Fehlende oder
widersprüchliche Pflichtfelder sind `unavailable/blocked`, nie stiller
Live-Rebuild.

## `TAX-API-001` – Country-Tax-API und Optimizer besitzen keine gemeinsame Source of Truth

### Beobachtung

Der Optimizer löst das `TaxRegime`-Protocol mit CH, CH-*, DE und Generic auf.
Die `/tax`-API nutzt dagegen eine zweite `TaxJurisdiction`-Registry. Im
Repository ist dort nur CH als Country-Plugin registriert; DE liefert beim
Estimate 404, obwohl es im Mandats-UI angeboten wird.

Beim Estimate lädt `_bind_parameter_sets()` ein reines Mapping für das
angefragte Land/Jahr und ersetzt damit die Pluginparameter. Wenn für das
angefragte Jahr keine Rows vorliegen, liefert der CH-Helper die eingebauten
2026-Defaults. Das Resultat setzt dennoch `year=profile.year`. Ein Request für
2099 kann damit 2026-Parameter rechnen und als 2099-Ergebnis zurückgeben; die
Annahmen nennen zwar 2026, aber das strukturierte Jahr bleibt irreführend.

Auch `profile.currency` beeinflusst die Rechnung nicht. CH-Resultate setzen
immer `currency="CHF"`; ein EUR-Request wird weder konvertiert noch
zurückgewiesen.

Die API ist authentifiziert und als read-only Schätzer klar kommentiert. Sie
ist derzeit jedoch kein Beweis für die Steuerbasis einer TargetAllocation und
hat im Frontend keinen produktiven Consumer.

### Risiko

Zwei Endpunkte können für dieselbe scheinbare Jurisdiktion andere Abdeckung,
Raten, Versionen und Währungen liefern. Das strukturierte Antwortjahr kann
einen nicht vorhandenen Tarifstand behaupten, und Beträge können unter einer
anderen Währung als angefragt interpretiert werden.

### Verbindlicher Fixvertrag

- Optimizer und Estimate-API verwenden denselben versionierten Resolver und
  dieselben TaxModel-/Parameter-Snapshots.
- Nicht vorhandene Tarifjahre führen zu 422/409 oder zu einem expliziten
  `requested_year`/`effective_parameter_year`-Paar; niemals zu stiller
  Umetikettierung.
- Nichtlokale Währung blockiert oder wird mit gesnapshottetem FX-Kurs,
  As-of und Rundungsregel konvertiert.
- Coverage je Land ist aus derselben Capability-Matrix ableitbar; UI darf nur
  wirklich ausführbare Regimes anbieten.
- Mandatsbezogene Beratungspublikation referenziert eine Snapshot-ID statt
  einen frei eingereichten Estimate-Request.

## `TAX-PARAM-001` – Parameterpersistenz erzwingt keine eindeutige gültige Tarifbasis

### Beobachtung

`tax_parameter_sets` besitzt einen String-Primärschlüssel und indizierte
Felder, aber keine DB-Checks für Country/Region/Jahr, `is_current`, JSON-
Struktur oder Raten. Es gibt keine partielle Unique Constraint für genau eine
Current-Version pro Land/Region/Jahr.

Der Reader filtert `is_current == 1`, optional das Jahr und sortiert nur nach
Region. Mehrere Current-Zeilen derselben Region werden nacheinander in dasselbe
Dict geschrieben; welche Version gewinnt, ist innerhalb derselben Region
nicht fachlich geordnet. Malformed JSON wird übersprungen. Sobald irgendeine
gültige Region übrig bleibt, wird der Partialbestand zurückgegeben und der
vollständige Built-in-Fallback nicht ergänzt.

`_bind_parameter_sets()` übergibt nur die inneren Parameterdicts. Die
persistierten Felder `id`, `year`, `version`, `source`, `created_at` und
`updated_at` erreichen den Pluginoutput nicht. `SwissTaxJurisdiction.version`
bleibt die Built-in-Konstante, auch wenn DB-Zeilen aus einer anderen Version
stammen.

### Risiko

Insert-Reihenfolge, Partialdaten oder direkte DB-Provisionierung können die
Steuerbasis verändern, ohne dass Resultat oder Run die tatsächliche Quelle
benennen. Fehlerhafte Parameter können erst tief in der Rechnung als 500 oder
wirtschaftlich unplausibler Wert sichtbar werden.

### Verbindlicher Fixvertrag

- DB-Checks erzwingen ISO-Codes, Regionsnormalform, gültige Jahre,
  `is_current IN (0,1)`, nichtleere Version/Quelle und validierte Ratebereiche.
- Eine partielle Unique Constraint erzwingt genau eine Current-Zeile je
  Land/Region/effective-year beziehungsweise versioniertem Tarifvertrag.
- Aktivierung neuer Parameter erfolgt atomar mit Supersedes-/Valid-from-/to-
  Historie.
- Der Reader gibt typisierte `ResolvedTaxParameterSet`-Objekte mit kompletter
  Provenienz zurück; kein Dict-Overwrite entscheidet fachliche Gültigkeit.
- Partial- oder malformed Coverage blockiert fail-closed; Fallback ist ein
  expliziter, versionierter Datensatz, keine implizite Mischstrategie.
- Seed-/Provisioning- und echte PostgreSQL-Tests decken Duplicate-Current,
  Race, malformed/partial JSON, Rangefehler und Versionpropagation ab.

## `TAX-PLUGIN-001` – Externe Steuerlogik ist nicht als produktive Vertrauensgrenze gehärtet

### Beobachtung

Beim Application-Start ruft `main.py` `discover_external_regimes()` ohne
Allowlist oder Skip-Konfiguration auf. Die Discovery lädt jedes installierte
Entry Point der Gruppe `5eyes.tax_regime` und führt damit Paketcode aus.

Die Registry dokumentiert doppelte Patterns als last-wins und überschreibt
`REGIME_REGISTRY[id_pattern]` direkt. Ein externes Paket kann damit nicht nur
eine neue Jurisdiktion ergänzen, sondern ein eingebautes `CH`, `CH-*`, `DE`
oder `*` ersetzen. Der bestehende `ConformanceContract` wird nur durch Tests
beziehungsweise freiwillig im Drittanbieter-CI ausgeführt, nicht beim Load.

Discoveryfehler werden geloggt und stoppen den Boot standardmäßig nicht. Der
DiscoveryResult wird nicht als persistierter Release-/Run-Anker verwendet.
Der OptimizerRun speichert weder Entry-Point-/Distributionversion noch
Package-Hash.

### Risiko

Ein installiertes, kompromittiertes oder versehentlich inkompatibles Paket
kann die wirtschaftliche Entscheidungslogik bestehender Jurisdiktionen ändern.
Selbst bei vertrauenswürdigem Deployment ist ein historischer Run nach einem
Paketupgrade nicht reproduzierbar.

### Verbindlicher Fixvertrag

- Produktion lädt ausschließlich explizit allowlistete Plugin-ID,
  Distribution, Version und Hash/Signatur.
- Built-in-Patterns sind reserviert; Override benötigt einen expliziten,
  auditierten Replacementvertrag und darf nicht durch normale Registration
  entstehen.
- Vor Registry-Aktivierung laufen Protocol-, Conformance-, Capability- und
  Determinismustests; Mandatory-Failure blockiert den Start oder das Regime.
- Failures und geladene Identitäten werden in Readiness und Audit sichtbar,
  nicht nur geloggt.
- Der TaxModelSnapshot bindet Plugin-/Contract-/Packageversion und Hash.
- Tests simulieren Duplicate-Builtin, inkompatibles Plugin, Loadfailure,
  nicht allowlistetes Paket und historischen Versionwechsel.

## `TAX-INPUT-001` – Steuerjurisdiktion ist weder kanonisch noch UI-ausführbar validiert

### Beobachtung

`tax_jurisdiction` ist in Create, Update und Response ein freier optionaler
String. `validate_tax_model_inputs()` trimmt ihn nur lokal und prüft, dass ein
aktiviertes Reportingflag beziehungsweise vorhandene Overrides nicht ohne
Jurisdiktion stehen. Der normalisierte Wert wird nicht zurückgeschrieben, und
eine Regimeauflösung findet an der Persistenzgrenze nicht statt.

Die Registry matcht case-sensitiv. Ein gespeichertes `ch` trifft daher nicht
`CH`, sondern den Generic-Catchall und scheitert ohne Overrides erst bei der
Strategieberechnung. Kommentare nennen `DE-BY` als erwarteten Wert; registriert
sind aber nur `DE`, `CH`, `CH-*` und `*`. `DE-BY` wird somit ebenfalls Generic.

Die sichtbare UI bietet `*` als Generic Flat-Rate an. Sie sendet aber nur
`tax_jurisdiction` und das Reportingflag; `tax_overrides_json` hat dort kein
Eingabefeld. Der produktive Resolver verlangt für Generic zwingend Overrides.

### Risiko

Ein Mandat kann erfolgreich gespeichert, aber später nicht berechnet werden.
Semantisch gleiche Schreibweisen verhalten sich unterschiedlich, und die UI
bietet eine Option an, die über denselben UI-Vertrag nicht vollständig
konfigurierbar ist.

### Verbindlicher Fixvertrag

- Create/Update akzeptieren ein typisiertes Tax-Residence-Objekt und schreiben
  ausschließlich kanonische IDs zurück.
- Persistenz löst das Regime und dessen Pflicht-Capabilities bereits vor Commit
  auf; nicht unterstützte Country-/Region-Kombinationen liefern 422.
- UI-Optionen stammen aus der serverseitigen Capability-Liste.
- Generic besitzt entweder typisierte Ratefelder mit Range-/Evidence-Prüfung
  oder wird aus der UI entfernt.
- Fachliche Jurisdiktionsidentität bleibt auch bei Generic-Implementierung im
  Snapshot erhalten; `GENERIC/XX` ersetzt nicht still den angefragten Sitz.
- Tests decken Whitespace/Case, `DE-BY`, unbekannte Region, Generic ohne/mit
  vollständigen Overrides und UI-Hydration ab.

## Vererbter offener Befund: `ENGCFG-SNAPSHOT-001`

Die PDF-Engine-Konfiguration lädt den Tax-Mode weiterhin aus
`settings.mc_default_tax_mode`. `OptimizerContext` besitzt kein entsprechendes
Feld, und `_simulate_context_wealth()` übergibt keinen Modus. Die Scenario-
Engine verwendet daher immer den Default `median`, während ein späteres
Setting `binned` oder `per_path` im PDF erscheinen kann.

Dieser Zustand wird **nicht** als neuntes neues Finding gezählt. Der Fix ist
Teil desselben TaxModelSnapshot-Vertrags:

- der gewählte Modus wird vor Runbeginn validiert,
- im Context tatsächlich angewendet,
- im OptimizerRun/TargetAllocation-Snapshot gespeichert,
- beim PDF ausschließlich aus diesem wirksamen Run gelesen.

## Zielbild: ein einziger `TaxModelSnapshot`

### 1. Kanonische Auflösung

```text
MandateTaxResidence
  country / region / currency / household / life phases
             |
             v
TaxModelResolver(as_of, purpose)
  - validate supported jurisdiction and components
  - resolve trusted provider/plugin
  - resolve exact parameter sets and validity
  - normalize/evidence-bind overrides
  - resolve yields/realization/cost basis
  - choose and validate tax_mode
             |
             v
Immutable TaxModelSnapshot
  + canonical payload hash
  + provider/rule/parameter hashes
  + complete component coverage
  + decision/reporting configurations
             |
             +--> OptimizerContext
             +--> Reporting/Goal simulation
             +--> /tax estimate for mandate-linked use
             +--> TargetAllocation + OptimizerRun
             +--> API/UI/PDF/Signoff/Handoff
```

### 2. Minimaler Snapshotvertrag

```json
{
  "schema_version": "tax_model_snapshot/v1",
  "snapshot_id": "...",
  "mandate_id": "...",
  "target_allocation_id": "...",
  "optimizer_run_id": "...",
  "calculation_as_of": "2026-09-05",
  "tax_residence": {
    "country": "CH",
    "region": "ZH",
    "currency": "CHF"
  },
  "provider": {
    "regime_id": "CH-ZH",
    "package": "5eyes-core",
    "version": "...",
    "package_hash": "...",
    "conformance_version": "1.0.0"
  },
  "parameters": [{
    "id": "...",
    "effective_year": 2026,
    "version": "...",
    "source": "...",
    "content_hash": "..."
  }],
  "components": {
    "wealth": "enabled",
    "dividend": "enabled",
    "interest": "not_modeled",
    "capital_gains": "not_modeled",
    "pension_lumpsum": "not_modeled",
    "inheritance": "not_modeled"
  },
  "mode": {"name": "median", "n_bins": null},
  "economic_inputs": {
    "dividend_yield_bps_per_bucket": [0, 0, 0, 0, 0],
    "realization_model": null,
    "cost_basis_model": null
  },
  "overrides": {"normalized": {}, "hash": "...", "evidence_id": null},
  "household": {"birth_year": 1980, "marital_status": "single", "children_count": 0},
  "life_phases": [{"from_year": 2045, "is_retired": true}],
  "decision_model": {"...": "..."},
  "reporting_model": {"...": "..."},
  "input_snapshot_hash": "...",
  "tax_model_hash": "..."
}
```

Die konkrete Datenform darf anders aussehen. Nicht verhandelbar sind
Unveränderlichkeit, vollständige Provenienz, wirksame Komponenten, explizite
Nichtabdeckung und Bindung an den tatsächlich wirksamen Run.

### 3. Einziger Consumervertrag

- Der Optimizer erhält keine lose Regimeinstanz mehr, sondern einen aus dem
  Snapshot gebauten, validierten Runtime-Adapter.
- Reporting verwendet denselben Snapshot; abweichende Approximationen sind
  explizite Child-Konfigurationen desselben Snapshots.
- `/tax/estimate` darf als allgemeiner Rechner bestehen, muss aber klar vom
  mandategebundenen Entscheidungsnachweis getrennt sein. Mandatsoutput
  referenziert die Snapshot-ID.
- UI und PDF rendern nur gespeicherte effektive Felder. Live-Settings,
  Klassenname oder jüngster beliebiger Run sind kein historischer Nachweis.
- Finalisierung und SignedPublication blockieren bei fehlendem, driftendem oder
  nicht reproduzierbarem Tax-Snapshot, sobald ein tax-aware Claim aktiv ist.

## Verbindliche Testmatrix

### Produktive Steuerwirkung

- CH/CH-ZH mit identischem Seed: tax-naiv versus tax-aware zeigt exakt die
  erwartete Wealth-Tax-Differenz.
- DE mit positiven Dividenden-/Realisierungsinputs zeigt eine reproduzierbare
  After-Tax-Differenz; ohne unterstützte Inputs blockiert der Claim.
- Generic wirkt für jede freigegebene Komponente oder kennzeichnet sie als
  nicht modelliert.
- Kein Test darf ausschließlich `simulate_wealth_paths()` direkt füttern; der
  Mandat-zu-TargetAllocation-Pfad ist Pflicht.
- Komponentenbreakdown reconciliert zum gesamten Tax-Drag.

### Kontext und Lebensphasen

- Altmandat `opened_at=2021`, Run 2026: effektives Tarifjahr ist 2026.
- Retirement innerhalb des Horizonts wechselt den Context im richtigen Jahr.
- CHF/EUR sowie Single/Married/Children-Pflichtfelder werden korrekt
  weitergereicht oder blockieren.
- Unbekannte und future Tarifjahre sind explizit unavailable, nicht implizit
  Built-in 2026.

### Parameter und Plugin

- Duplicate Current pro Country/Region/Year scheitert auf SQLite und
  PostgreSQL.
- Race beim Versionwechsel hinterlässt genau einen Current-Satz.
- Malformed, partial, negative, Bool-, String-, Overflow- und unbekannte
  Parameter blockieren.
- DB-ID, Version, Quelle, Jahr und Content-Hash erscheinen im Result/Snapshot.
- Nicht allowlistete, falsche Version, falscher Hash, Built-in-Override und
  Mandatory-Conformance-Failure blockieren.
- Pluginupgrade verändert den TaxModelHash und niemals rückwirkend historische
  Runs.

### Snapshot, Reload und Tamper

- TargetAllocation und OptimizerRun referenzieren denselben Snapshot.
- Änderung an Tarif, Plugin, Overrides, Yields, Komponenten oder Mode verändert
  den TaxModelHash.
- Historischer Reload verwendet den alten Snapshot trotz neuer Settings oder
  neuer Pluginversion.
- Fehlende Snapshotzeile, Hashmismatch, Cross-Mandate-/Cross-Run-Verweis und
  manipuliertes JSON blockieren.
- House-/Shadow-/Fallbackrollen werden korrekt und nicht über „latest run“
  aufgelöst.

### Decision-/Reporting-Parität

- Flag an/aus kann keine unbeschriftete wirtschaftliche Modelländerung
  erzeugen.
- Bei identischer Modellart sind Decision- und Reportingsteuer exakt
  reconciliert.
- Bei erlaubter Approximation speichert der Test beide Konfigurationen und eine
  tolerierte, fachlich begründete Abweichung.
- Externes Vermögen wird weder doppelt besteuert noch unbemerkt ausgelassen.

### API, UI und PDF

- UI-Regimeliste stammt aus Server-Capabilities; jede sichtbare Option ist
  vollständig konfigurierbar.
- Case/Whitespace/Region werden kanonisiert; `DE-BY` wird unterstützt oder mit
  422 abgelehnt.
- `/tax/estimate` gibt requested/effective year und Currencysemantik korrekt
  aus.
- API, Frontend, Advisory-PDF und signierte Publikation zeigen dieselbe
  Snapshot-ID, Regimeversion, Komponentenliste und Mode.
- Settingänderung nach dem Run verändert keinen historischen PDF-Wert.
- Unknown/missing/drift ist sichtbar `nicht beurteilbar/blockiert`, niemals
  ein grüner oder steuerbewusster Claim.

## Empfohlene Umsetzungsreihenfolge

### Phase A – Falschclaims unmittelbar schließen

1. UI-/PDF-Texte auf tatsächlich wirksame Komponenten begrenzen.
2. DE und Generic für tax-aware Optimierung blockieren, solange der produktive
   E2E-Pfad keine belastbare Wirkung besitzt.
3. `tax_mode` strikt validieren und im Solver wirklich durchreichen.
4. `opened_at` nicht mehr als Bewertungsjahr verwenden.

### Phase B – Input- und Parametergrenze härten

1. Typisiertes, kanonisches Tax-Residence-Schema einführen.
2. Generic-Override-UX festlegen oder entfernen.
3. TaxParameterSet-Migration mit Checks, Current-Unique, Gültigkeit und
   atomarem Supersedes-Vertrag erstellen.
4. Typisierten Parameterresolver mit vollständiger Provenienz bauen.

### Phase C – Plugin-Vertrauensgrenze

1. External Discovery produktiv default-off beziehungsweise allowlist-only.
2. Built-in-Override sperren.
3. Conformance-/Capability-Gate vor Aktivierung ausführen.
4. Package-/Distributionidentität und Hash in Readiness und Snapshot binden.

### Phase D – `TaxModelSnapshot`

1. Snapshotmodell, Migration, FK-/Unique-/Hashconstraints implementieren.
2. Resolver vor Context-Aufbau ausführen.
3. TargetAllocation und OptimizerRun atomar an denselben Snapshot binden.
4. Komponenten, Yields, Realisierung, Context und Mode vollständig aufnehmen.

### Phase E – Consumer vereinheitlichen

1. Optimizer und Reporting auf Snapshotadapter umstellen.
2. Country-Tax-API an denselben Resolver anbinden beziehungsweise als klar
   separaten ungebundenen Rechner labeln.
3. API/UI/PDF/Signoff/Handoff auf gespeicherte Snapshotfelder umstellen.
4. Alte Live-Setting- und latest-arbitrary-run-Ableitungen entfernen.

### Phase F – Abnahme

1. Fokussierte Unit-/Integration-/Browser-/PDF-Tests.
2. Echte PostgreSQL-Constraint-, Race- und Migrationstests.
3. Deterministischer Replay alter und neuer Plugin-/Tarifversionen.
4. Vollständiger Backend-/Frontend-/Electron-/Packaging-Gate.

## Definition of Done

Runde 27 ist erst geschlossen, wenn alle folgenden Aussagen wahr sind:

- [ ] Jede sichtbare Steuerjurisdiktion ist kanonisch und produktiv ausführbar.
- [ ] Jede behauptete Steuerkomponente besitzt eine echte Bemessungsgrundlage
      und einen produktiven Mandat-E2E-Test.
- [ ] Nicht modellierte Komponenten sind maschinenlesbar und sichtbar benannt.
- [ ] DE ist nicht länger effektiv steuerneutral unter einem tax-aware Claim.
- [ ] Bewertungsjahr stammt aus Run-/As-of, nicht Mandatseröffnung.
- [ ] Alter, Retirement, Währung und Pflicht-Haushaltsdaten sind pro Jahr
      korrekt.
- [ ] Tax-Mode ist streng validiert, angewendet und gesnapshottet.
- [ ] Parameterjahr, ID, Version, Quelle und Hash sind reproduzierbar.
- [ ] Genau ein gültiger Current-Parametersatz ist DB-seitig erzwungen.
- [ ] Partial/malformed Parameter können nicht still produktiv wirken.
- [ ] Externe Plugins sind allowlist-, hash- und conformancegebunden.
- [ ] Built-ins können nicht still last-wins überschrieben werden.
- [ ] Ein immutable TaxModelSnapshot bindet Mandat, TA und Run.
- [ ] Raw Input-Hash und aufgelöster TaxModelHash werden beide geprüft.
- [ ] Decision und Reporting nutzen denselben Snapshot oder eine explizit
      erklärte, getestete Approximation.
- [ ] Externes Vermögen wird exakt einmal und mit dokumentierter Basis erfasst.
- [ ] `/tax/estimate` beschriftet requested/effective year und Currency korrekt.
- [ ] API, UI, PDF, Signatur und Handoff zeigen denselben Snapshotstand.
- [ ] Historische Publikation liest keine heutigen Settings oder neuesten
      beliebigen Runs.
- [ ] Tamper-, Missing-, Drift- und Cross-Mandate-Fälle blockieren fail-closed.
- [ ] SQLite und PostgreSQL besitzen denselben Fachvertrag.
- [ ] Reale PostgreSQL-Race-/Migrationstests sind grün.
- [ ] Vollständiger Backend-/Frontend-/Electron-Gate ist grün.

## Claude-/GPT-Startcheckliste

Vor der Umsetzung muss Claude/GPT diese Reihenfolge einhalten:

1. Diesen Audit vollständig lesen.
2. `ENGCFG-SNAPSHOT-001` im Audit vom 2. September mitlesen; keine Duplicate-ID
   erzeugen.
3. Produktiven Callgraph von Mandate über `_build_tax_solver_kwargs`,
   `OptimizerContext` und `simulate_wealth_paths` zuerst sichern.
4. Reporting-Cashflow und Country-Tax-API als getrennte Ist-Modelle behandeln,
   nicht voreilig als gleiche Source of Truth bezeichnen.
5. Zuerst Claim-/Inputgrenze fail-closed machen, dann Snapshotmodell und
   Parameter-/Pluginmigration implementieren.
6. Vor Schemaänderung SQLite- und PostgreSQL-Constraintdesign festlegen.
7. Bestehenden Schutz vor doppelter Advisory-Wealth-Tax erhalten.
8. Bestehenden Projection-/Input-Hash und gespeicherte Modellbasis erweitern,
   nicht ersetzen.
9. Keine Steuerrechtsvollständigkeit behaupten, die nicht durch
   Komponentenmodell, Daten und Tests belegt ist.
10. Erst nach E2E-, Tamper-, Browser-, PDF- und echten PostgreSQL-Tests einen
    Blocker als geschlossen markieren.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

```text
branch: codex/asset-allocation-stochastic-core
HEAD: 2f402b087fa38564fe51644aa8b27b34b949a618
visible tracked/untracked entries: 0
git status ACL warnings for historical pytest temp directories: 53
global clean claim: intentionally false
```

Die ACL-geschützten historischen `.pytest_tmp*`-/`.pytest-tmp*`-Verzeichnisse
wurden weder betreten noch verändert oder gelöscht. Der Audit behauptet daher
nur einen leeren sichtbaren Status, nicht globale Lesbarkeit oder globale
Sauberkeit.

### Statische Kontrollflussbelege

Durchgeführt wurden unter anderem:

```text
rg across mandate tax fields, schemas, routers and validation
rg across _build_tax_solver_kwargs and its only productive caller
rg across OptimizerContext and all simulate_wealth_paths tax arguments
rg across every dividend_tax / annual_wealth_tax / capital_gains_tax /
  interest_tax call in the productive scenario engine
rg across TaxParameterSet ORM, Alembic baseline and parameter readers
rg across TaxRegime and TaxJurisdiction registries
rg across external discovery, startup and ConformanceContract consumers
rg across OptimizerRun model/schema/persistence
rg across TargetAllocation input snapshot and model_basis persistence
rg across advisory report, PDF component and frontend model-basis rendering
rg across tax-focused tests and prior audit contracts
```

Die Suche nach `ConformanceContract` fand produktive Definition/SDK, aber
Ausführung nur in Tests beziehungsweise der Drittanbieter-Beispieldokumentation.
Die Suche im produktiven Scenario-Loop fand Dividend- und Wealth-Tax-Calls,
aber keine Interest-, Capital-Gains-, Pension- oder Inheritance-Tax-Ausführung.

### Fokussierter Bestands-Gate

Ausgeführt aus `5eyes-backend` ohne pytest Cache und ohne explizites
`--basetemp`:

```powershell
python -m pytest -p no:cacheprovider `
  tests/tax `
  tests/test_tax_solver_wiring.py `
  tests/test_tax_fx_fail_closed.py `
  tests/test_per_path_tax_integration.py `
  tests/test_wealth_cashflows_tax_estimate.py `
  tests/test_frontend_mandate_tax_estimate_toggle.py `
  tests/test_optimizer_production_contract.py `
  tests/test_advisory_engine_configuration.py `
  tests/pdf/test_compliance_engine_configuration_block.py `
  tests/test_asset_allocation_current_integrity_contracts.py `
  -q
```

Ergebnis:

```text
315 passed in 51.69s
```

Die Tests bestätigen unter anderem:

- Basisfunktionen der CH-/DE-/Generic-Regimes,
- direkte Scenario-Engine-Dividenden-/Wealth-Tax-Integration bei manuell
  gelieferten Inputs,
- Median/Binned/Per-Path-Primitive,
- produktive Regimeauflösung und CH-Kanton,
- Cashflow-Schätzung und Schutz vor doppelter Steuer,
- Tax-API-CH-Happy-Path,
- PDF-Rendering aller Tax-Mode-Strings.

Sie widerlegen die Findings nicht, weil der produktive Mandatspfad keine
Dividend-Yields oder Realisierungsdaten liefert, die Tests den falschen
`opened_at`-Jahrvertrag teilweise ausdrücklich festschreiben und PDF-Tests nur
einen frei übergebenen Mode rendern.

### Nicht ausgeführte Umgebungsbelege

- Kein neuer isolierter Custom-Harness wurde erzeugt.
- Kein Browser-/DOM-Runtime-Lauf wurde für diese Read-only-Runde benötigt.
- Keine externe Plugininstallation wurde verändert oder geladen.
- Keine echte PostgreSQL-Constraint-, Migration-, Race- oder RLS-Prüfung wurde
  in dieser Runde ausgeführt.
- Der letzte dokumentierte vollständige Backend-Gate bleibt am
  Implementierungscommit `661fe73`: 6074 bestanden, 0 fehlgeschlagen,
  10 übersprungen, 1 erwartetes XFail.

### Dokumentationsmanifest dieser Runde

Es dürfen ausschließlich folgende fünf Dokumentationspfade geändert werden:

1. `docs/audits/2026-09-05-tax-model-regime-parameter-and-after-tax-publication-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Produktcode, Tests, Migrationen und Konfiguration bleiben in dieser Runde
unverändert.

## Schlussentscheidung

**Release bleibt blockiert.** Es wurde kein neuer bestätigter P0 festgestellt;
die acht neuen Findings enthalten jedoch bestätigte P1 in produktiver
Steuerwirkung, Decision-/Reporting-Parität, Zeit-/Haushaltscontext,
Snapshot-Reproduzierbarkeit, API-/Parameterintegrität und Plugin-Governance.

Die nächste saubere Umsetzungseinheit ist keine weitere lose Rate oder ein
zusätzlicher PDF-Text. Sie ist ein einziger immutable `TaxModelSnapshot` mit
kanonischer Inputgrenze, gesichertem Parameter-/Pluginresolver, expliziter
Komponentenabdeckung und identischer Bindung an Entscheidung, Reporting,
OptimizerRun, TargetAllocation und Publikationskanäle.
