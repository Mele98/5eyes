---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-followup-audit"
status_as_of: "2026-09-02"
audit_started_on: "2026-08-31"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend/reporting"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "2ba969b34061430df760cae3ea57f745af079db6"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-31-performance-attribution-context-and-model-integrity-audit.md"
prior_release_audit_commit: "2ba969b34061430df760cae3ea57f745af079db6"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md"
audit_mode: "read_only_static_service_orm_pdf_api_react_review_targeted_runtime_reproduction_existing_backend_and_frontend_test_gates"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "advisory risk KPI provenance and semantics, methodology and recommendation audit context, disclosed engine configuration, reserve explanation, liquidity cascade, React compliance aggregation and runtime report schema"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_backend_tests_passed: 138
focused_backend_tests_skipped: 1
focused_backend_tests_failed: 0
focused_frontend_tests_passed: 19
focused_frontend_tests_failed: 0
required_next_action: "introduce one immutable advisory publication context and discriminated evidence states, bind every KPI, methodology, optimizer, reserve and liquidity statement to the exact current target-allocation snapshot, then make API, React, client portal and PDF fail closed with identical semantics"
---

# Advisory-Risk-KPI-, Engine-Konfigurations-, Reserve- und Compliance-Integritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die neunzehnte Read-only-
Kontrollrunde. Die Analyse begann am 31. August 2026, wurde gegen den
unveränderten Repository-Head `2ba969b3` abgeschlossen und am 2. September
2026 als Handoff konsolidiert. Sie ergänzt, ersetzt aber nicht:

1. den
   [Performance-Attribution-Context-/Modellintegritätsaudit](2026-08-31-performance-attribution-context-and-model-integrity-audit.md),
2. den
   [Stress-Replay-/Policy-A/B-Modellintegritätsaudit](2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md),
3. den
   [Strategy-Backtest-Context-/Gebühren-/Publikationsintegritätsaudit](2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md),
4. den
   [Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit](2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md),
5. den
   [Historische-Renditen-/Schema-/Driftintegritätsaudit](2026-08-28-historical-return-schema-and-drift-integrity-audit.md),
6. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
7. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
8. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
9. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
10. den
    [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
11. den
    [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
12. den
    [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
13. den
    [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
14. den
    [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
15. den
    [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
16. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
17. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
18. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
19. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Laufzeitbelege
zuerst, danach dieser Audit und anschließend die vorgenannten Dokumente in
dieser Reihenfolge. Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Die Advisor-JSON ist keine geschlossene,
entscheidungsgebundene Beweissicht. Mehrere kundenrelevante Sektionen lesen
unabhängig voneinander aktuelle Tabellen, Live-Settings oder globale
Referenzdaten und verbinden sie anschließend mit einer älteren Soll-Allokation.
Andere Sektionen löschen echte Nullwerte, behandeln fehlende Evidenz als
konform oder färben unbekannte Zustände grün.

Bestätigt sind insbesondere:

- Persistierte Monte-Carlo-KPIs werden ohne Publication-Preflight aus der
  Current-TA gelesen. Nach geänderten Vermögens-, Ziel- oder Risikoprofilinputs
  bleiben die alten Zahlen im Advisory-JSON und Kundenportal sichtbar, obwohl
  der strikte Allocation-Rebuild denselben Zustand als stale ablehnt.
- PDF und HTML-Monolith berechnen Sharpe mit hartcodierten `80 bp`, während
  die Engine die Liquiditätsrendite der Snapshot-CMA verwendet. Ein Snapshot
  mit `250 bp` erzeugt deshalb publiziert `0.42` statt fachlich `0.25`.
- `0` wird in mehreren KPI-Buildern über `... or None` zu „fehlend“; negative
  oder fachlich unmögliche persistierte Werte werden dagegen unverändert
  publiziert. Die UI blendet fehlende Kern-KPIs vollständig aus.
- Methodology-Audit verwendet die jüngste globale Current-CMA statt der
  Snapshot-CMA des Mandats und erklärt allein die Feldpräsenz zur Aktivierung.
  Ein vollständiger Nelson-Siegel-Satz mit `lambda=0` erscheint aktiv, obwohl
  der Runtime-Validator ihn ablehnt.
- Kein Optimizer-Run und reiner Shadow-Betrieb gelten als `is_compliant=true`.
  Die Engine-Konfigurationssektion nimmt zugleich den jüngsten beliebigen Run
  statt `TargetAllocation.optimization_run_id` und kann so eine aktive
  House-Matrix-Allokation als neueren Shadow-Stochastic-Lauf beschreiben.
- Der ausgewiesene Tax-Modus stammt aus einer Live-Einstellung; der Solver
  übergibt diesen Modus nicht und rechnet weiterhin mit dem Default
  `median`. Die Publikation kann daher `binned` behaupten, obwohl `median`
  gerechnet wurde.
- Reserve-Narrative werden aus heutigen Goals, Positionen, Cashflows,
  Inflows, FX und einer globalen Current-CMA rekonstruiert. Nur zwei Summen
  werden verglichen. Eine geänderte Ursache mit identischen Summen wird damit
  als historische Erklärung akzeptiert.
- Die Liquiditätsklassifikation besitzt einen unerreichbaren
  `hard_cap`-Status, akzeptiert negative Werte und Bools und klassifiziert
  sämtliche Werte über `1000 bp` weiter als normalen Emergency-Zustand.
- Das React-Gesamtbanner wertet nur vier von sechs sichtbaren Prüfungen aus.
  Die Standardfixture zeigt trotz fehlender CMA-Modelle, fehlendem aktivem Run
  und unbekannter Liquidität „Alle 5 Audit-Pruefungen unauffaellig“.
- Mehrere Pflichtpayloads – unter anderem Performance-Attribution,
  Engine-Konfiguration und Optimizer-Historie – besitzen keinen sichtbaren
  React-Reportpfad. Die Runtime-Prüfung validiert nur Top-Level-Key-Präsenz;
  malformed Unterobjekte können bis zum Renderer gelangen.

Der fokussierte Backend- und Frontend-Gate bleibt grün, weil die vorhandenen
Tests mehrere dieser Zustände als Sollverhalten festschreiben und keinen
gemeinsamen Publication-Context prüfen.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `KPI-CONTEXT-001` | P1 | offen | Alle publizierten Risiko-KPIs stammen aus der verifizierten Current-TA und exakt ihren RA-/Policy-/CMA-/Input-/Context-Ankern; Stale oder Mixed Context blockiert vor Cache und Renderer |
| `KPI-RF-001` | P1 | offen | Sharpe und verwandte Kennzahlen verwenden über Engine, JSON, PDF und HTML dieselbe Snapshot-CMA-Risk-free-Rate; kein Publikationshardcode |
| `KPI-ZERO-001` | P1 | offen | `0`, Missing, Invalid und Negative besitzen getrennte, strikt validierte Zustände; Pflicht-KPIs werden nie still ausgeblendet |
| `METHOD-CONTEXT-001` | P1 | offen | Methodology- und Recommendation-Audit sind an die TA-Snapshot-CMA beziehungsweise den exakten TA-Run gebunden; „keine Evidenz“ ist nicht „konform“ |
| `ENGCFG-SNAPSHOT-001` | P1 | offen | Engine-Konfiguration beschreibt ausschließlich den nachweislich wirksamen TA-Run und dessen eingefrorene Settings, Tax-Modus, Suballocation- und Degradationsstatus |
| `RESERVE-PROVENANCE-001` | P1 | offen | Reservebeträge und Narrative sind als vollständiger Generation-Snapshot mit Context-/Inputhash, Currency und Domain-Invarianten persistiert und in allen Kanälen identisch |
| `LIQ-CASCADE-001` | P1 | offen | Liquiditäts-Cascade wird aus persistierter Engine-Evidenz statt nachträglicher Zielgewichtsklassifikation abgeleitet; alle Werte und Stages sind erreichbar und strikt |
| `COMPLIANCE-UI-001` | P1 | offen | Jede sichtbare Complianceprüfung trägt zu einem tri-state Gesamtstatus bei; unknown/degraded/missing/drift ist niemals grün |
| `ANALYTICS-SCHEMA-001` | P1 | offen | API, React, Kundenportal und PDF besitzen denselben verschachtelt validierten Analytics-Vertrag und dieselben sichtbaren `available|unavailable|blocked`-Zustände |
| `KPI-SEMANTICS-001` | P2 | offen | Median, Erwartungswert, Horizont, Quantil, Verlustvorzeichen, Modellbasis und As-of werden fachlich korrekt benannt und transportiert |
| `RATIO-PROXY-001` | P2 | offen | Heuristische Sortino-/Calmar-/Information-Ratio-Proxys werden nicht als beobachtete Standardkennzahlen publiziert; Benchmark und Tracking Error sind explizit |

Der bereits dokumentierte Tippfehler `sub_allocation_json` statt
`sub_allocations_json` bleibt als geerbter P2 offen. Er wird in
`ENGCFG-SNAPSHOT-001` mitgetestet, aber hier nicht erneut als neuer Befund
gezählt.

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Current-TA wird call-scoped gecacht, aber nicht gegen Live-Inputdrift geprüft | `5eyes-backend/services/advisory_report.py:106-120` |
| Key-Metrics lesen Rohfelder und machen `0` mit `or None` zu Missing | `5eyes-backend/services/advisory_report.py:738-771` |
| Persistierte KPI-Semantik: 1y-Vol, annualisierter Median, Median-MaxDD, 1y-VaR95 | `5eyes-backend/models/allocation.py:95-106` |
| PDF-Datenmodell setzt Risk-free standardmäßig auf 80 bp | `5eyes-backend/services/pdf/base.py:202-204` |
| PDF-Router setzt `risk_free_bps` nicht aus Snapshot-CMA | `5eyes-backend/routers/pdf_reports.py:778-821` |
| Strategie-PDF berechnet Sharpe mit dem PDF-Feld | `5eyes-backend/services/pdf/anlagestrategie.py:545-577` |
| Soll/Ist-PDF nutzt denselben Wert | `5eyes-backend/services/pdf/sollist_vergleich.py:35-44` |
| HTML-Monolith hardcodiert `_RF_BPS = 80` | `5eyes_v2.html:21095-21102` |
| Engine nimmt Risk-free aus der gelösten Snapshot-CMA | `5eyes-backend/services/portfolio_engine_cma.py:640-647` |
| Methodology lädt globale Current-CMA per `.first()` | `5eyes-backend/services/methodology_audit.py:139-180` |
| Model „active“ prüft Präsenz, nicht Runtime-Domain | `5eyes-backend/services/methodology_audit.py:40-98` |
| Nelson-Siegel-Runtimevalidierung lehnt ungültige Parameter ab | `5eyes-backend/services/cma_validation.py:171-225` |
| Recommendation ohne Run oder ohne active Run gilt als compliant | `5eyes-backend/services/recommendation_audit.py:91-169` |
| TA persistiert den tatsächlich verwendeten Optimizer-Run | `5eyes-backend/models/allocation.py:112-143` |
| Engine-Konfiguration lädt jüngsten beliebigen Run statt TA-Run | `5eyes-backend/services/advisory_report.py:3559-3615` |
| Tax-Disclosure liest Live-Setting | `5eyes-backend/services/advisory_report.py:3517-3529` |
| Solver übergibt keinen Tax-Modus; Scenario-Default ist `median` | `5eyes-backend/services/optimizer/solver.py:270-283`; `5eyes-backend/services/optimizer/scenario_engine.py:406-420` |
| Suballocation-Erkennung liest falschen Singularnamen | `5eyes-backend/services/advisory_report.py:3541-3555`; `5eyes-backend/models/allocation.py:78-81` |
| Reserve-Rebuild liest Live-Goals/-Positions/-Cashflows/-Inflows und globale CMA | `5eyes-backend/services/advisory_report.py:3158-3255` |
| Reserve vergleicht nur zwei Totale | `5eyes-backend/services/advisory_report.py:3363-3376` |
| Reserve-Output enthält keine TA-/CMA-/Input-/Context-Provenienz | `5eyes-backend/services/advisory_report.py:3401-3414` |
| `_safe_int` kollabiert malformed und Missing zu null | `5eyes-backend/services/advisory_report.py:2925-2929` |
| Liquidity-Classifier macht `hard_cap` unerreichbar | `5eyes-backend/services/liquidity_cascade_audit.py:31-78` |
| Liquidity-Audit klassifiziert nur Current-TA-Zielgewicht | `5eyes-backend/services/liquidity_cascade_audit.py:81-169` |
| React-Gesamtstatus ignoriert Methodology und Reserve | `5eyes-electron/frontend/reporting/src/pages/Compliance.tsx:52-73` |
| Banner behauptet fünf Prüfungen, während sechs Cards gerendert werden | `5eyes-electron/frontend/reporting/src/pages/Compliance.tsx:82-99` |
| Reserve-UI macht Nullable-Betrag via `?? 0` zu „kein Bedarf“ | `5eyes-electron/frontend/reporting/src/pages/Compliance.tsx:332-375` |
| Pflicht-Analytics sind typisiert und im API-Keycheck verlangt | `5eyes-electron/frontend/reporting/src/api/types.ts:695-726`; `5eyes-electron/frontend/reporting/src/api/client.ts:126-170` |
| Pflicht-Analytics besitzen keinen vollständigen App-/Sidebar-Renderpfad | `5eyes-electron/frontend/reporting/src/components/Sidebar.tsx:13-37`; `5eyes-electron/frontend/reporting/src/App.tsx:448-477` |
| KPI-Karten filtern Nullable-Werte vollständig heraus | `5eyes-electron/frontend/reporting/src/pages/Ausgangslage.tsx:29-64` |
| Reserve-Type erlaubt widersprüchliche Zustände | `5eyes-electron/frontend/reporting/src/api/types.ts:788-801` |
| Extended ratios sind Heuristik-Proxys | `5eyes-backend/services/risk_metrics_kpi.py:1-160` |
| Ratio-Ergebnis wird vor API/Persistenz weitgehend verworfen | `5eyes-backend/services/portfolio_engine_cma.py:648-665`; `5eyes-backend/services/portfolio_engine.py:4129-4130` |

## `KPI-CONTEXT-001` – Persistierte Zahlen ohne gültigen Publication-Context

### Tatsächlicher Pfad

`_build_key_metrics` liest die call-scoped gecachte Current-TA und übernimmt
deren persistierte KPI-Spalten. Dieser Read ist für sich legitim. Der
Advisory-Aggregator führt davor aber nicht denselben strikten Context- und
Inputdrift-Check aus wie `build_target_payload_from_allocation`.

Dadurch kann derselbe Request gleichzeitig zeigen:

- aktuelles Kundenvermögen, aktuelle Goals und aktuelle Cashflows;
- das neueste Current-Risk-Assessment;
- ältere Monte-Carlo-KPIs einer TA, deren Inputsnapshot nicht mehr zu diesen
  aktuellen Daten passt.

Der Kundenportal-Endpunkt liefert denselben Aggregator direkt. Der Advisory-
PDF-Pfad baut ebenfalls KPI-Werte aus der Current-TA, ohne die vollständige
Entscheidungsbasis als Publication-Precondition zu prüfen.

### Ausgeführte Reproduktionen

Nach Generierung einer Soll-Allokation wurden die relevanten Live-Inputs
geändert:

```text
before/after advisory KPI:
exp_vol_bps=655
exp_return_bps=367
max_drawdown_bps=619
var_95_bps=600

strict allocation rebuild:
StaleAllocationInputError
```

In einer zweiten Reproduktion wurde die TA mit Risikoscore `60` erzeugt und
anschließend ein neues gültiges Current-Risk-Assessment mit Score `10`
angelegt. Der Report zeigte das aktuelle Profil `10` zusammen mit den alten
TA-KPIs. Der strengere Strategy-PDF-Contextcheck lehnte den nicht mehr aktuellen
Assessment-Anker dagegen ab.

### Fixvertrag

- Ein zentraler, unveränderlicher `AdvisoryPublicationContext` wird einmal pro
  Request aufgelöst und vor Cache, Aggregator und Renderer verifiziert.
- Er enthält mindestens TA-ID/-Version/-`set_at`, RA-/Policy-/CMA-/Run-IDs,
  Jurisdiktion, Tenant, Engine-/Modelversion, Inputsnapshot- und
  Allocation-Context-Hash sowie Publication-Fingerprint.
- Alle Advisory-Builder erhalten nur diesen Context; innerhalb der Builder
  sind keine unabhängigen Current- oder globalen Referenzdatenqueries erlaubt.
- Final-/Kundenmodus liefert bei Missing, Mismatch, Stale oder Corrupt stabil
  HTTP 409. Preview darf einen strukturierten `blocked`-Status anzeigen.
- Cache-Hits werden erst nach einem erneuten Currentness-/Drift-Preflight
  bedient.

## `KPI-RF-001` – Publizierter Sharpe verwendet eine andere Modellbasis

Die Engine berechnet erweiterte Kennzahlen gegen
`cma.liquidity_return_bps`. Das PDF-Datenmodell besitzt dagegen einen Default
von `80 bp`. Der Router setzt das Feld beim Bau des Strategie-PDFs nicht aus
der Snapshot-CMA, und der HTML-Monolith besitzt denselben Hardcode.

Ausgeführter Zahlenbeleg:

```text
snapshot risk-free:       250 bp
annualized return:        500 bp
volatility:              1000 bp
correct snapshot Sharpe: 0.25
published 80-bp Sharpe:  0.42
```

Der Fehler ist kein reines Labelproblem: Zwei Publikationskanäle behaupten
für dieselbe Strategie eine andere risikoadjustierte Kennzahl als die Engine.

### Fixvertrag

- `risk_free_bps` ist ein Pflichtfeld des eingefrorenen Modellbasis-Snapshots.
- KPI-Persistenz speichert Wert, CMA-ID/-Version, Feldquelle und As-of.
- JSON, React, Kundenportal, alle PDFs und Legacy-HTML erhalten exakt diesen
  Wert; Defaults sind im Finalpfad verboten.
- Legacy-Dokumente ohne Provenienz zeigen „nicht verfügbar“ statt
  nachträglich mit aktuellem oder hartcodiertem Zins zu rechnen.
- Cross-channel Golden-Tests prüfen dieselbe Zahl und dieselbe Basis-ID.

## `KPI-ZERO-001` und `KPI-SEMANTICS-001` – Falsche Zustands- und Fachsemantik

### Null ist nicht Missing

`_safe_int(value) or None` löscht echte Nullwerte für Risky Fraction,
Volatilität, Rendite, Max Drawdown und VaR. Die PDF-Router besitzen denselben
Truthy-Fehler. In React werden Nullable-KPIs aus der Kartenliste gefiltert;
sind alle Werte missing, verschwindet der gesamte Block.

Umgekehrt werden negative persistierte Werte nicht als korrupt abgelehnt.
Eine Laufzeitreproduktion lieferte negative Risky Fraction, Volatilität,
Rendite, Max Drawdown und VaR unverändert aus.

Benötigt werden vier getrennte Zustände:

| Zustand | Beispiel | Publikation |
|---|---|---|
| `available` | echte 0-bp-Rendite | Zahl `0.00 %` mit Basis |
| `unavailable` | Legacy-TA ohne KPI-Spalte | „Nicht verfügbar“ plus Grund |
| `blocked` | Stale/Mismatch/Corrupt | keine Zahl; Publication-Blocker |
| `not_applicable` | fachlich nicht anwendbar | explizite Begründung |

### Median ist kein Erwartungswert

`mc_exp_return_bps` wird aus
`target_annualized_return_p50_bps` persistiert. Das ist der Median der
annualisierten simulierten Time-Weighted Returns, nicht ohne Weiteres deren
Erwartungswert. Frontend und Beratertext nennen ihn „Erw. Rendite“.

Auch Volatilität, Max Drawdown und VaR benötigen:

- Horizont;
- Quantil beziehungsweise Aggregationsstatistik;
- Loss-Sign-Konvention;
- Pathzahl und Seed/Run;
- Modell-/CMA-Basis und As-of;
- Currency und Gebühren-/Steuerstatus.

### Fixvertrag

- Keine Truthy-Coercion numerischer Fachwerte.
- Pydantic-/Domainvalidierung für echte Integer ohne Bool, fachliche Bounds
  und zulässige Loss-Sign-Konvention.
- Key-Metric-Vertrag als discriminated union mit Provenienz.
- Kern-KPIs bleiben sichtbar; Missing und Blocked werden erklärt.
- Fachlabels nennen „annualisierter Median“, „1-Jahres-VaR 95 %,
  modelliert, positiver Verlust“ und den jeweiligen Drawdown-Horizont.

## `RATIO-PROXY-001` – Heuristische Ratios sind keine Standardmessungen

`risk_metrics_kpi.py`:

- approximiert Downside-Deviation als Gesamtvolatilität geteilt durch
  `sqrt(2)`;
- schätzt fehlenden Max Drawdown aus Volatilität und Horizont;
- ersetzt fehlenden Benchmark durch Risk-free und fehlenden Tracking Error
  durch Gesamtvolatilität.

Die resultierende „Information Ratio“ ist in diesem Default faktisch eine
Sharpe Ratio unter anderem Namen. Die Werte werden derzeit zwar berechnet,
aber vor dem publizierten Ergebnis weitgehend verworfen. Das ist aktuell ein
P2-Vertrags- und Wartbarkeitsproblem, kein zusätzlicher sichtbarer P1.

Zielvertrag:

- Entweder persistierte Path-Downside-/Drawdown-Verteilung und explizite
  Benchmark-Returnserie plus Tracking Error verwenden;
- oder die Werte klar als intern heuristische Proxys benennen und nicht als
  standardisierte Kundenkennzahlen publizieren;
- tote Berechnung entfernen, falls kein fachlich verantworteter Verbraucher
  existiert.

## `METHOD-CONTEXT-001` – Methodik und Recommendation beschreiben nicht die TA

### Globale CMA statt Snapshot-CMA

`audit_engine_models(db)` hat keinen Mandats- oder Publication-Context. Es
lädt die jüngste globale Current-CMA. Ein DE-Mandat kann dadurch mit der
aktuellen CH-CMA erklärt werden; eine ältere, an der TA verankerte
Snapshot-CMA wird durch eine spätere globale Version überschrieben.

Ausgeführter ORM-Beleg:

```text
TA snapshot CMA: cma-de-snapshot
newer global current CMA: cma-ch-latest
reported methodology CMA: cma-ch-latest
reported active_count: 0
```

Die Aktivierungsregel `_all_set` prüft zudem nur, dass Felder nicht `None`
sind. Ein kompletter Nelson-Siegel-Satz mit `lambda=0` wird als aktiv
gemeldet, während `validate_nelson_siegel_parameters` denselben Satz mit
`CMAValidationError` ablehnt.

### Fehlende Recommendation-Evidenz gilt als konform

Bei null Runs und bei reinem Shadow-Betrieb liefert
`audit_recommendation_methodology` `is_compliant=true`:

```text
latest_run=None
latest_active_run=None
total_runs=0
is_compliant=True
```

„Es existiert kein belegter aktiver Lauf“ ist jedoch ein
`nicht_beurteilbar`-Zustand. Außerdem muss nicht irgendein letzter aktiver
Run, sondern der in der Current-TA referenzierte `optimization_run_id`
geprüft werden.

### Fixvertrag

- Methodology erhält den verifizierten TA-Context und liest ausschließlich
  dessen Snapshot-CMA.
- Aktivierungsstatus wird mit demselben Runtime-Validator bestimmt, den der
  Solver verwendet; invalid complete groups sind `blocked`.
- Recommendation löst exakt `TA.optimization_run_id` auf und prüft Mandat,
  Rolle, Methode, Status, Context-/Inputhash und Runzeitpunkt.
- Null Runs, Shadow-only, fehlende Referenz oder Run-Mismatch sind
  `unavailable` beziehungsweise `blocked`, niemals `compliant=true`.
- Methodology, Recommendation und Engine Configuration publizieren dieselbe
  TA-/CMA-/Run-ID.

## `ENGCFG-SNAPSHOT-001` – Disclosure kann einen unwirksamen Run beschreiben

`_build_engine_configuration` lädt den jüngsten beliebigen OptimizerRun des
Mandats. Ein nachträglicher Shadow-Run kann damit die aktuell wirksame
Allokation überschreiben.

Ausgeführter ORM-Beleg:

```text
current TA optimization_run_id: run-active-old
newer unrelated run:            run-shadow-new
reported_optimizer_mode:        shadow_stochastic
reported_is_active:             False
suballocation_aware:            False
```

Die Sektion nennt weder TA-ID noch Run-ID/-Zeit, Context-Hash oder einen
degradierten Zustand. Zusätzlich stammt `tax_mode` aus dem aktuellen Setting,
nicht aus dem Solverrun. Der Solver übergibt den Modus nicht an die
Scenario-Engine; deren Default bleibt `median`. Ein Live-Setting `binned`
kann deshalb eine nicht gerechnete Konfiguration behaupten.

Der geerbte Singular-/Pluralfehler
`sub_allocation_json`/`sub_allocations_json` macht reale moderne
Allokationen außerdem regelmäßig zu `suballocation_aware=false`.

### Fixvertrag

- Engine Configuration ist ein persistierter, versionierter
  `OptimizerExecutionSnapshot` des tatsächlich wirksamen TA-Runs.
- Pflichtfelder: TA-/Run-/RA-/Policy-/CMA-ID, Runzeit, Rolle, Methode, Status,
  Seed, Paths, Iterationen, Engine-/Scenario-Version, Tax-Modus,
  Suballocation-Modus, Gebührenbasis, Constraints, Degradationsgrund,
  Input-/Context-Hash.
- Der Solver muss den publizierten Tax-Modus tatsächlich anwenden; Settings
  nach dem Run dürfen historische Disclosure nicht ändern.
- Keine „latest arbitrary run“-Query und keine Ableitung aus heutigen
  Settings.
- Schema und UI sind typisiert; `Record<string, unknown>` ist kein
  Freigabevertrag.

## `RESERVE-PROVENANCE-001` – Heutige Nachrechnung impersoniert historische Erklärung

Die persistierten Reserve-Totale sind ein nützlicher Anker. Das Narrativ wird
jedoch nicht bei Generierung persistiert, sondern im Readpfad aus heutigen
Daten erneut erzeugt:

- aktive Goals;
- Wealth Positions und abgeleitete Cashflows;
- manuelle Cashflows;
- Vermögenssteuer;
- Inflows;
- aktuelle FX-Quelle;
- jüngste globale Current-CMA;
- TA-Präferenzsnapshot.

Anschließend werden nur `reserve_needed_rappen` und
`external_reserve_rappen` mit den persistierten Summen verglichen. Wenn sich
die Ursache ändert, aber beide Totale gleich bleiben, gilt die neue Erzählung
als historische Komposition. TA-/CMA-/Input-/Context-ID und Narrative-Hash
fehlen im Output.

### Domain- und Publikationsfolgen

- `_safe_int` macht malformed Werte zu null.
- Bei `reserve_needed <= 0` zwingt der Builder mehrere Felder in einen
  scheinbar sauberen „kein Bedarf“-Zustand; negative Reserve plus positive
  externe Reserve kann damit kollabieren.
- DB-Spalten besitzen keine ausreichenden Check-Constraints.
- React macht nullable Betrag über `?? 0` zu „kein Reservebedarf“ und erlaubt
  `available=true` mit unvollständigen Beträgen.
- Currency ist im Backend Mandatsbasis, die UI beschriftet Reservewerte jedoch
  hart als CHF.
- Reserve-Drift beziehungsweise `available=false` fließt nicht in das
  Gesamtbanner ein.
- Die serverseitigen Advisory-PDF-Complianceblöcke enthalten die
  Reserveherleitung nicht; JSON/React/PDF sind nicht parity.

### Fixvertrag

- Generation persistiert eine immutable
  `ReserveExplanationSnapshot`-Struktur einschließlich vollständiger
  Komponenten, Narrative-Codes, Currency, TA-/CMA-/RA-/Policy-ID, As-of,
  Input-/Context-Hash und Engine-Version.
- Readpfade erklären ausschließlich diesen Snapshot; Live-Rebuild ist höchstens
  ein separater Driftcheck, nie historische Wahrheit.
- Beträge sind echte Integer ohne Bool, `>=0`; externe Reserve und
  Recommendation-Flag sind invariant gekoppelt.
- `available=true` verlangt alle Pflichtbeträge und eine valide Komposition.
- Currency wird aus dem Snapshot transportiert und über alle Renderer
  verwendet.
- Drift, unavailable oder invalid blockiert grünes Compliance-Gesamturteil.
- JSON, React, Kundenportal und PDF zeigen dieselbe Snapshot-ID und denselben
  Zustand.

## `LIQ-CASCADE-001` – Nachträgliche Gewichtsklassifikation ist keine Engine-Evidenz

Der Service beschreibt drei Stufen, implementiert aber:

```text
-1    -> normal
True  -> normal
300   -> normal
301   -> emergency
1000  -> emergency
2000  -> emergency
15000 -> emergency
```

`STAGE_HARD_CAP` wird nie zurückgegeben. Negative Werte und Bools werden
akzeptiert; Werte oberhalb des Emergency-Caps bleiben Emergency statt
Corrupt/Blocked. Der Audit liest nur das aktuelle Top-Level-
Liquiditätszielgewicht. Er belegt nicht, welche Cascade-Stufe die Engine
tatsächlich betreten hat, warum sie eskalierte, welche Constraints wirksam
waren oder ob die TA seitdem driftete.

### Fixvertrag

- Die Engine persistiert `liquidity_cascade_stage`, Trigger/Reason Codes,
  ursprüngliche und wirksame Caps, benötigte Reserve, Zielgewicht,
  Constraintquelle und Context-Hash im TA-Run.
- Read-Audit validiert diese Evidenz gegen den Publication-Context; keine
  heuristische Rekonstruktion allein aus dem Endgewicht.
- Domain: Integer ohne Bool, `0..10000`; konfigurierbare Caps ebenfalls
  geordnet und bounded.
- Jede dokumentierte Stage ist über definierte Boundarywerte erreichbar.
- Werte über Emergency-Cap, negative Werte, unmögliche Stage-/Gewichtspaare
  und fehlende Evidenz sind `blocked` oder `unavailable`, niemals normal.

## `COMPLIANCE-UI-001` – Unbekannt und nicht geprüft erscheinen grün

`overallOk` berücksichtigt nur:

1. Suitability;
2. Recommendation;
3. Mandate Lock;
4. Liquidity-Warnflag.

Methodology und Reserve werden zwar als Cards gerendert, fließen aber nicht in
das Gesamturteil ein. Bei Liquidity zählt nur `warning_required`; der
`unknown`-Status mit `warning_required=false` ist grün.

Die Standardfixtures reproduzieren bereits:

- keine CMA-Modelle;
- kein aktiver Optimizer-Run, trotzdem `is_compliant=true`;
- Liquidity `unknown` mit `warning_required=false`;
- grünes Banner „Alle 5 Audit-Pruefungen unauffaellig“;
- tatsächlich sechs gerenderte Cards.

Reserve `available=false` oder `drift_detected=true` ändert das Banner
ebenfalls nicht.

### Zielvertrag

Ein zentraler Aggregator bildet jeden sichtbaren Check auf:

```text
ok | handlungsbedarf | nicht_beurteilbar
```

- `ok` nur bei positiver, vollständiger und current Evidenz;
- `handlungsbedarf` bei fachlichem Verstoß oder Drift;
- `nicht_beurteilbar` bei unknown, unavailable, degraded, missing oder
  Vertragsfehler.

Alle sichtbaren Cards tragen zum Gesamtstatus bei. Die Zahl der Prüfungen wird
dynamisch aus derselben Liste erzeugt. Eine rote oder amberne Card kann nie in
einem grünen Gesamtbanner verschwinden.

## `ANALYTICS-SCHEMA-001` – Pflichtpayloads ohne sichtbaren oder validierten Vertrag

`AdvisoryReportData` verlangt unter anderem:

- `stress_replay`;
- `optimizer_run_history`;
- `performance_attribution`;
- `engine_configuration`;
- `ab_backtest`.

Die API-Runtimeprüfung kontrolliert überwiegend, ob diese Top-Level-Keys
existieren. Sie prüft keine verschachtelten Typen, Enums oder Invarianten.
`reserve_explainability: null` kann dadurch die Prüfung passieren und später
beim Zugriff auf `data.available` crashen.

Gleichzeitig existiert für mehrere Analyticsblöcke kein vollständiger
Sidebar-/`renderSection`-Pfad. Die Daten werden berechnet, gecacht und
transportiert, bleiben für den Berater aber unsichtbar. Engine Configuration
ist nur `Record<string, unknown>`; die Standardfixture ist ein leeres Objekt.

Die Backend-/Type-Synchronisationstests prüfen Stringvorkommen beziehungsweise
Substrings statt echte Property-Strukturen. Ein ähnlich benannter Unterkey
kann dadurch einen fehlenden Top-Level-Vertrag kaschieren.

### Fixvertrag

- Backend und TypeScript werden aus einem gemeinsamen versionierten Schema
  beziehungsweise gegenseitig maschinenlesbar validiert.
- Verschachtelte Runtime-Validierung prüft Typen, Enums, Nullability,
  Discriminators, Bounds und Cross-field-Invarianten.
- Jeder kundenorientierte Pflichtkey besitzt eine sichtbare Sektion oder wird
  aus dem Pflichtvertrag entfernt.
- Jede Sektion hat `available|unavailable|blocked` und einen begründeten
  Empty-/Error-State.
- Fehlerhafte Analytics dürfen weder als leere erfolgreiche Zahlen erscheinen
  noch die ganze App ungefangen crashen.
- API, React, Kundenportal und PDF verwenden denselben Schema- und
  Publication-Fingerprint.

## Verbindliche Testmatrix

### Gemeinsamer Publication-Context

Neue Integrationstests für CH und DE:

- exakt eine Current-TA mit vollständigen modernen Contextartefakten;
- TA-/RA-/Policy-/CMA-/Run-/Tenant-/Jurisdiktions-IDs stimmen in jeder
  Advisory-Sektion überein;
- Live-Wealth-, Goal-, Cashflow-, Preference- oder RA-Änderung blockiert vor
  Cache, Aggregator und Renderer;
- Snapshot-CMA wird nie durch spätere globale Current-CMA ersetzt;
- Cache-Hit validiert Currentness und Inputdrift erneut;
- JSON, Kundenportal, React und PDF zeigen dieselbe
  Publication-Context-ID/-Hash.

### Risk-KPI-Verträge

- echte `0` für Return/Vol/Risky Fraction bleibt numerisch null und sichtbar;
- Missing-Legacywert wird `unavailable`, invalid/negative/unbounded wird
  `blocked`;
- Bool/String/NaN/Infinity und falsche Loss-Sign-Konvention werden abgelehnt;
- Score-/RA-Drift verhindert gemischte aktuelle Profil- und alte KPI-Anzeige;
- Snapshot-Risk-free `250 bp` ergibt kanalübergreifend denselben Sharpe;
- Median-/Horizont-/Quantil-/As-of-/Currency-/Fee-Semantik ist maschinenlesbar
  und sichtbar;
- Preview/Final verwenden identische Werte oder Final blockiert.

### Methodology, Recommendation und Engine Configuration

- DE-TA mit DE-Snapshot-CMA bleibt DE trotz neuer globaler CH-CMA;
- `lambda=0` und andere invalid complete groups sind `blocked`, nicht active;
- null Runs und shadow-only sind `nicht_beurteilbar`;
- TA-Run ist älter als neuer Shadow-Run: Disclosure bleibt am TA-Run;
- Run-Mandat/-Rolle/-Methode/-Status/-Context-Mismatch blockiert;
- Live-Setting nach Run verändert historischen Tax-Modus nicht;
- `binned` wird nur publiziert, wenn Solver und Scenario-Engine ihn tatsächlich
  verwendet haben;
- echte `sub_allocations_json` wird erkannt; Singularfeld ist kein Fallback.

### Reserve und Liquidität

- geänderte Reserveursache bei gleichen Totalen verändert die historische
  Erklärung nicht;
- Narrative-/Component-/Context-Hash-Tampering blockiert;
- negative, Bool-, String-, widersprüchliche und Overflow-Beträge blockieren;
- CHF/EUR/USD werden mit Snapshot-Currency identisch gerendert;
- Reserve unavailable/drift/invalid verhindert grünes Gesamtbanner;
- PDF und React zeigen dieselbe Reserve-Snapshot-ID und Komposition;
- Liquidity-Boundaries machen jede zulässige Stage erreichbar;
- negative, Bool und `>10000` blockieren;
- Endgewicht ohne persistierten Cascade-Trail ist `unavailable`;
- Stage-/Cap-/Reason-/Constraint-Mismatch blockiert.

### React und Runtime-Schema

- jeder der sechs Compliancechecks kann einzeln
  `nicht_beurteilbar`/`handlungsbedarf` auslösen;
- Gesamtbanner und dynamische Anzahl stimmen mit Cards überein;
- `reserve_explainability=null`, falsche Untertypen, unbekannte Enums und
  fehlende Pflichtunterfelder erzeugen einen gefangenen Schemafehler;
- Attribution, Engine Configuration und Optimizer-History sind mit nichtleeren
  Payloads sichtbar;
- Empty/Error/Blocked werden pro Sektion getestet;
- Schema-Sync parst echte Top-Level-Properties statt Substrings.

### PostgreSQL, Race und Publikation

- paralleler Run-/TA-Wechsel erzeugt keinen Mixed Context;
- Exactly-one-Current-Invarianten und Foreign Keys werden auf PostgreSQL
  geprüft;
- Snapshot-/Narrative-/Executionfelder besitzen passende Check-Constraints;
- Final-/Kundenpfad liefert bei Contextkonflikt stabil 409;
- kein Renderer, Cache-Write oder Download nach fehlgeschlagenem Preflight;
- Audit-/Publication-Fingerprint ist transaktionskonsistent.

## Empfohlene Umsetzungsreihenfolge

1. Gemeinsamen `AdvisoryPublicationContext` und tri-state Evidence-Vertrag
   definieren.
2. Final-/Kunden-Preflight vor Cache und Aggregator erzwingen.
3. Key Metrics und Sharpe auf TA-/Snapshot-CMA-Provenienz migrieren; Null- und
   Domainsemantik korrigieren.
4. Methodology, Recommendation und Engine Configuration an Snapshot-CMA und
   exakten TA-Run binden; Solver-Taxmodus tatsächlich persistieren/anwenden.
5. ReserveExplanation- und LiquidityCascade-Snapshot bei Generierung
   persistieren.
6. Verschachteltes API-/TypeScript-Schema und sichtbare Analyticssektionen
   implementieren.
7. Compliance-Gesamtstatus aus allen Cards tri-state aggregieren.
8. PDF, React, Kundenportal und Legacy-HTML auf denselben Context und dieselben
   Labels migrieren.
9. Negativ-, CH/DE-, Race-, Cache-, PostgreSQL- und Cross-channel-Tests
   schließen.

## Definition of Done

Diese Kontrollrunde ist erst geschlossen, wenn gleichzeitig gilt:

- jede kundenrelevante Zahl nennt und beweist dieselbe TA-/RA-/Policy-/CMA-/
  Run-/Tenant-/Jurisdiktionsbasis;
- Stale oder Mixed Context blockiert vor Cache und Renderer;
- echte Null, Missing, Invalid und Not-applicable bleiben getrennt;
- kein PDF-/HTML-Hardcode ersetzt Snapshot-Risk-free;
- KPI-Labels nennen Median/Quantil/Horizont/As-of/Loss-Sign korrekt;
- Methodology validiert exakt die Snapshot-CMA mit Solverregeln;
- null Runs, shadow-only oder fehlender TA-Run sind nicht konform;
- Engine Configuration entspricht dem wirksamen Run und dessen tatsächlich
  angewandten Tax-/Suballocation-/Fee-/Constraintsettings;
- Reserve-Narrativ und Liquidity-Cascade sind immutable
  Generationsevidenz mit Hashes, nicht heutige Rekonstruktion;
- Reserve-/Liquidity-Domänen und Currency sind strikt;
- jede sichtbare Compliance-Card trägt zum tri-state Gesamtstatus bei;
- alle Pflichtanalytics sind sichtbar oder bewusst aus dem Pflichtvertrag
  entfernt;
- verschachtelte Runtime-Schemavalidierung verhindert malformed Rendererinput;
- JSON, React, Kundenportal und PDF haben Parität;
- PostgreSQL-/Race-/Cache-/Cross-channel-Negativtests laufen grün;
- bestehende Tests wurden nicht durch breite Golden-/Null-Orakelupdates
  beruhigt.

## Claude-/GPT-Startcheckliste

Vor jeder Änderung in dieser Fläche:

1. Diesen Audit und die vier unmittelbar vorherigen Modell-/Publikationsaudits
   vollständig lesen.
2. Zuerst den gemeinsamen Publication-Context und die Evidence-State-Machine
   festlegen; keine weiteren unabhängigen Current-Queries ergänzen.
3. `TargetAllocation.optimization_run_id` und Snapshot-CMA sind die Anker,
   nicht der jüngste beliebige Run und nicht globale Current-CMA.
4. Keine Live-Settings als historische Solverkonfiguration publizieren.
5. `0` niemals über Truthiness in Missing umwandeln.
6. Keine unbekannten/degradierten Zustände als `is_compliant=true` erhalten.
7. Reserve-/Liquidity-Narrative bei Generierung persistieren, nicht im
   Kundenread neu erfinden.
8. API-Schema verschachtelt und discriminated gestalten; Frontend-Types nicht
   mit `Record<string, unknown>` beruhigen.
9. Jede Compliance-Card in denselben Gesamtstatus-Reducer aufnehmen.
10. Tests zuerst rot auf Mixed Context, RF 250, Null/Missing, lambda 0,
    No-run, newer-shadow-vs-TA-run, binned-vs-median, gleiche Reserve-Totale
    bei anderer Ursache, negative/Bools in Liquidity und malformed
    Frontendpayloads schreiben.
11. Finalpfade auf 409 plus „Cache/Renderer nicht aufgerufen“ prüfen.
12. Nach Umsetzung Audit, Stable Entry, Claude-Handoff, Deploy- und
    Provisioning-Blocker synchron aktualisieren.

## Unveränderte Baseline- und Audit-Evidenz

Ausgeführter fokussierter Backend-Gate:

```text
python -m pytest -q -p no:cacheprovider --basetemp <TEMP> \
  tests/test_methodology_models_audit.py \
  tests/test_recommendation_methodology_audit.py \
  tests/test_liquidity_cascade_warning.py \
  tests/test_advisory_engine_configuration.py \
  tests/test_reserve_explainability_section.py \
  tests/test_risk_metrics_kpi.py \
  tests/property/test_risk_metrics_kpi_properties.py \
  tests/test_ar2_persist_mc_risk_kpis.py \
  tests/pdf/test_anlagestrategie_sollist_vergleich.py \
  tests/test_pdf_compliance_audit_section.py \
  tests/pdf/test_compliance_engine_configuration_block.py
```

Ergebnis:

```text
138 passed, 1 skipped in 15.39s
```

Der Skip ist die optionale, lokal nicht installierte Hypothesis-Abhängigkeit.

Ausgeführter Frontend-Gate:

```text
npm.cmd test -- --run src/pages/Compliance.test.tsx
```

Ergebnis:

```text
1 test file passed
19 tests passed
Duration 21.55s
```

Die Vite-/esbuild-/oxc-Hinweise waren Deprecation-Warnungen, keine
Testfehler.

Diese grünen Gates widerlegen die Findings nicht:

- Tests erwarten `is_compliant=true` bei fehlendem aktivem Run;
- die Compliance-Standardfixture erwartet ein grünes Banner trotz unknown;
- `hard_cap` wird nur als erlaubter Enumwert, nicht als erreichbare
  Klassifikation gesichert;
- es gibt keinen gemeinsamen TA-/RA-/CMA-/Run-Publication-Context;
- es gibt keinen RF-250-Cross-channel-Test;
- Reserveursache bei identischen Totalen wird nicht geprüft;
- Frontend-Keycheck und Pflichtanalytics werden nicht gegen malformed
  verschachtelte Payloads und tatsächliche Sichtbarkeit getestet.

Der letzte vollständige Backend-Gate bleibt unverändert:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
```

Auch dieser grüne SQLite-Gate hebt die bestätigten Context-, Semantik-,
Provenienz-, Disclosure-, Schema- und Publikationsblocker nicht auf.
