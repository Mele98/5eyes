---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-stress-replay-and-policy-ab-model-integrity-followup-audit"
status_as_of: "2026-08-28"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "cc990669a2de96a2a9c1976a1faf147dd29ae1c5"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md"
prior_release_audit_commit: "cc990669a2de96a2a9c1976a1faf147dd29ae1c5"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md"
audit_mode: "read_only_static_service_router_advisory_pdf_frontend_review_isolated_orm_and_math_reproduction_cross_jurisdiction_reproduction_and_existing_test_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "historical stress replay allocation context, scenario semantics and versioning, stochastic versus house-matrix model identity, policy comparison CMA jurisdiction and customer publication"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_adjacent_tests_passed: 116
focused_adjacent_tests_skipped: 0
focused_adjacent_tests_failed: 0
required_next_action: "bind every stress result to one verified allocation and versioned scenario catalog, then separate an internal House-Matrix sensitivity from a true stochastic policy comparison using the mandate-scoped approved CMA and exact publication anchors"
---

# Stress-Replay- und Policy-A/B-Modellintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die siebzehnte Read-only-
Kontrollrunde auf Repository-Head `cc990669`. Er ergänzt, ersetzt aber nicht:

1. den
   [Strategy-Backtest-Context-/Gebühren-/Publikationsintegritätsaudit](2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md),
2. den
   [Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit](2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md),
3. den
   [Historische-Renditen-/Schema-/Driftintegritätsaudit](2026-08-28-historical-return-schema-and-drift-integrity-audit.md),
4. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
5. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
6. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
7. den
   [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
8. den
   [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
9. den
   [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
10. den
    [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
11. den
    [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
12. den
    [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
13. den
    [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
14. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
15. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
16. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
17. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die siebzehn vorgenannten Dokumente in dieser
Reihenfolge. Dieser Audit wiederholt nicht die bereits belegten
Marktdaten-/Annual-Return-Probleme. Er untersucht die darüberliegende
Modellfrage: Welche Allocation, welches Krisenszenario und welche Policy-/CMA-
Basis werden im Stress- beziehungsweise A/B-Ergebnis tatsächlich gerechnet
und anschließend als Kundeninformation publiziert?

Die Analyse hat keine Produkt- oder Testdatei verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Vier weitere P1-Verträge sind offen:

- Das historische Stress-Replay liest die erste Current-TA und nur deren fünf
  Bucketgewichte. Ein ausdrücklich moderner Datensatz ohne RA, Policy,
  Snapshot-CMA, Input-/Context-Hash oder eines der drei Contextartefakte liefert
  trotzdem fünf erfolgreiche Szenarien.
- Die fünf Replay-Szenarien sind unversionierte Code-Hardcodes. „Max Drawdown“
  wird nur aus Jahresendpunkten berechnet, „Recovery Months“ ist ein für alle
  Portfolios identischer Quellindexwert. Ein reines Bondportfolio mit positivem
  GFC-Pfad erhält deshalb 0 Drawdown, aber 36 Monate Recovery; Equity-Covid
  erscheint als +15 % bei 0 Drawdown.
- Das Produkt besitzt zwei voneinander abweichende Stresskataloge. Der
  stochastische Solver persistiert drei cashflow-/liability-fähige Pfade; der
  Advisory-/Depotcheck-Pfad berechnet live fünf andere, cashflowfreie Replays.
  Dieselbe 60/40-Strategie zeigt für Covid einmal +12 %/0 Drawdown und einmal
  16,8 % Drawdown.
- Der sogenannte A/B-Backtest läuft immer über House-Matrix-Zielgewichte,
  niemals über die produktive stochastic Engine. Goals, Reserve,
  Sub-Allokationen, Produkte und Fees fehlen. Ein DE-Mandat mit gültiger
  DE-CMA wurde gegen die CH-CMA gerechnet; beide Policies mit dokumentiertem
  75-bps-Fee-Modell wurden als TER 0 und „Expected Return (netto)“ ausgewiesen.

Damit gibt es weder einen einzigen Stress-Snapshot noch einen fachlich
eindeutigen „Policy-Backtest“. UI, Advisory und Depotcheck können plausible
Zahlen zeigen, die nicht aus dem freigegebenen stochastic Entscheidungscontext
stammen.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `STRESS-CONTEXT-001` | P1 | offen | Stress-Replays werden ausschließlich aus genau einer verifizierten modernen Allocation mit gültigen 10.000-bps-Gewichten, RA-/Policy-/CMA-/Input-/Contextankern und unverändertem Modellcontext gebaut |
| `STRESS-SCENARIO-001` | P1 | offen | Jeder Stresskatalog ist versioniert, quellen- und periodenbelegt, mathematisch zur ausgewiesenen Frequenz passend und über Solver, API, Advisory und PDF entweder identisch oder unmissverständlich getrennt |
| `AB-CMA-SCOPE-001` | P1 | offen | Policyvergleiche verwenden die mandatsspezifische, tenant-/jurisdiktionskorrekte und für Kundennutzung freigegebene CMA; globale `.first()`- oder Defaultauswahl ist verboten |
| `AB-MODEL-001` | P1 | offen | Ein als A/B-Backtest publiziertes Ergebnis vergleicht zwei vollständige, identisch eingefrorene stochastic Modellcontexts oder wird ausdrücklich als interner House-Matrix-Konfigurationsdiff ohne Netto-/Backtestbehauptung geführt |

## Codeanker auf dem auditierten Head

| Bereich | Codeanker |
|---|---|
| Fünf unversionierte historische Hardcode-Szenarien | `5eyes-backend/services/backtest_stress.py:32-84` |
| Jahresendpunkt-Drawdown und feste Recovery Months | `5eyes-backend/services/backtest_stress.py:87-121` |
| Reiner Helper ohne Gewichtsdomäne | `5eyes-backend/services/backtest_stress.py:125-132` |
| Stress-Reader wählt Current-TA per `.first()` | `5eyes-backend/services/backtest_stress.py:135-169` |
| Öffentliche Stress-Route reicht Service unverändert durch | `5eyes-backend/routers/allocation.py:819-833` |
| Advisory macht jeden Stressfehler zu `data_pending` | `5eyes-backend/services/advisory_report.py:2588-2644` |
| Depotcheck berechnet denselben Legacy-Stress live | `5eyes-backend/routers/pdf_reports.py:1514-1521`; `:1599` |
| Separater Solver-Stresskatalog mit drei Szenarien | `5eyes-backend/services/optimizer/stress_scenarios.py:31-70` |
| Solver-Stress nutzt Wealth, Cashflows, Liabilities und Horizon | `5eyes-backend/services/optimizer/stress_scenarios.py:110-161` |
| Solver-Stress wird an Allocation persistiert | `5eyes-backend/services/portfolio_engine.py:3829-3843`; `:4034` |
| A/B liest Policy per ID und rechnet reinen House-Matrix-Pfad | `5eyes-backend/services/backtest_ab.py:50-93` |
| A/B setzt Sub-Allokationen und Produkte ausdrücklich auf `None` | `5eyes-backend/services/backtest_ab.py:74` |
| A/B lädt globale Current-CMA per `.first()` | `5eyes-backend/services/backtest_ab.py:151-194` |
| A/B-Note schließt Goals, Reserve und Tilts aus | `5eyes-backend/services/backtest_ab.py:210-220` |
| Advisory wählt automatisch Global-Current plus jüngste andere Policy | `5eyes-backend/services/advisory_report.py:2652-2704` |
| Advisory verschluckt A/B-Domain-/Integritätsfehler | `5eyes-backend/services/advisory_report.py:2703-2717` |
| UI nennt House-Matrix, aber publiziert Netto-/Stressmetrik | `5eyes-electron/frontend/5eyes_v2.html:4169-4208`; `:13314` |
| Korrekte jurisdiktions-/tenantgebundene CMA-Auflösung existiert | `5eyes-backend/services/jurisdiction/resolve.py:42-145` |

## `STRESS-CONTEXT-001` – Fünf Szenarien ohne Strategieanker

### Aktueller Pfad

`compute_stress_replays()` lädt eine Current-TA per `.first()`, kopiert die
fünf Top-Level-Zielgewichte und ruft den reinen Hardcode-Helper auf. Es prüft
weder die moderne Provenienz noch die Gewichtsdomäne:

- keine exactly-one-Auflösung;
- kein `context_artifacts_required`-Vertrag;
- keine RA-, Policy- oder Snapshot-CMA-ID;
- kein `input_snapshot_hash` oder Inputdrift;
- keine drei Allocation-Contextartefakte und kein Context-Hash;
- keine Jurisdiktion, kein Tenant und keine Engine-Version;
- keine Einzelbounds und keine exakte Summe von 10.000 bps.

Der Helper kappt jedes einzelne negative Gewicht auf null, normalisiert die
Restsumme aber nicht. Ein 15.000-bps-Bondgewicht wird deshalb wie 150 Prozent
Exposure gerechnet.

### Ausgeführte ORM-Reproduktion

Eine Current-TA wurde mit `context_artifacts_required=1` und gültigen 60/40-
Top-Level-Gewichten angelegt. Gleichzeitig waren alle folgenden Felder NULL:

```text
based_on_assessment_id
capital_market_assumptions_id
input_snapshot_hash
sub_allocations_json
effective_constraints_json
allocation_context_hash
```

`compute_stress_replays()` lieferte dennoch fünf Szenarien und die 60/40-
Gewichte. Der kanonische moderne Allocation-Rebuild würde diesen Zustand
fail-closed ablehnen.

Direkte Gewichtreproduktion:

```text
10.000 bps Bonds, GFC: cumulative +17,70 %, max DD 0
15.000 bps Bonds plus -5.000 bps Equities:
                     cumulative +27,07 %, max DD 0
```

Der negative Aktienfehler verschwindet, der verbleibende Bondfehler wird als
150-Prozent-Hebel weitergerechnet.

### Publikationsfolge

Die öffentliche Route liefert den Service unverändert. Advisory mappt jede
Exception broad zu `data_pending`, während Depotcheck denselben Service live
aufruft. Dadurch kann ein Kundenbericht entweder eine ungebundene Zahl oder
einen scheinbar harmlosen „noch nicht verfügbar“-Abschnitt enthalten, ohne den
zugrunde liegenden Integritätsbruch als Publikationskonflikt auszuweisen.

## `STRESS-SCENARIO-001` – Zwei Krisenwahrheiten ohne Version

### Legacy-Replay

`backtest_stress.py` enthält fünf statische Listen jährlicher Bucketreturns.
Die Kommentare nennen verschiedene Indizes, Währungen und Hedgingannahmen,
aber das Ergebnis besitzt keine:

- Katalog-/Schema-Version;
- exakte Quelle, Publikation oder Abrufzeit;
- Währung, FX-/Hedgingmethode oder Total-/Price-Return-Kennzeichnung;
- As-of, Datenhash oder Genehmigungsstatus;
- Frequenz- und Periodencutoff;
- Bindung an Allocation- oder Publication-Fingerprint.

Der Code nennt teilweise intra-year Krisenperioden, rechnet aber ausschließlich
volle Jahreswerte. Max Drawdown entsteht nur aus diesen Jahresendpunkten.
`recovery_months` wird überhaupt nicht aus dem Portfoliopfad berechnet, sondern
unverändert aus dem Szenario kopiert.

### Ausgeführte Semantikreproduktion

```text
100 % Bonds, GFC 2008/2009:
  cumulative return  +17,70 %
  max drawdown         0,00 %
  recovery            36 Monate

100 % Equities, Covid 2020:
  cumulative return  +15,00 %
  max drawdown         0,00 %
  recovery             5 Monate
```

Ein Portfolio ohne Verlust kann definitionsgemäß keine 36-monatige
Portfolio-Recovery benötigen. Ein als Covid-Crash bezeichnetes Ergebnis von
+15 Prozent und 0 Drawdown bildet die im Label genannte Februar-/Märzkrise
nicht ab; es ist ein Volljahresreturn mit externem Recovery-Label.

### Separater Solver-Katalog

Die stochastic Engine besitzt einen zweiten Katalog mit drei anderen Pfaden.
Dieser wird nach Solverkonvergenz unter Einbezug von Startvermögen, Cashflows,
Liabilities und Horizon gerechnet und als `stress_evaluations_json` an der TA
persistiert. Das historische Legacy-Replay ignoriert diese Snapshotwerte und
rechnet live fünf andere Szenarien ohne Cashflows/Liabilities.

Für identische 60/40-Gewichte ergab die ausgeführte Gegenprobe:

```text
Legacy covid_2020:
  cumulative return +12,00 %, max drawdown 0,00 %

Optimizer covid_inflation_2020_2022:
  min wealth CHF 87.905,79 bei CHF 100.000 Start
  max drawdown 16,80 %
```

Beide Kataloge sind als vereinfachte Hardcodes dokumentiert, aber nur der
Solverwert ist an einen konkreten Optimizerlauf gebunden. Kunden-UI,
Advisory-/Depotcheck-PDF und Solverpanel können daher verschiedene Antworten
auf dieselbe Frage zeigen.

## `AB-CMA-SCOPE-001` – DE wird mit CH gerechnet

### Ursache

`run_ab_backtest()` lädt jede Current-CMA global und nimmt `.first()`. Der
Mandatswert `jurisdiction`, `tenant_id`, der Committee-Approval-Status und die
bewährte `resolve_cma_for_jurisdiction()`-Logik werden nicht verwendet. Bei
mehreren legitimen Current-CMAs verschiedener Jurisdiktionen entscheidet die
DB-Reihenfolge.

### Ausgeführte Cross-Jurisdiction-Reproduktion

In einer isolierten echten ORM-Datenbank existierten gleichzeitig:

```text
Mandat.jurisdiction = DE
Current CMA 1       = CH, committee_approved
Current CMA 2       = DE, committee_approved, vollständige Home-Felder
```

`run_ab_backtest()` lieferte:

```text
selected_cma_id            = ID der CH-CMA
selected_cma_jurisdiction  = CH
```

Die DE-CMA wurde trotz passender, freigegebener Referenzzeile vollständig
ignoriert. Expected Return, Volatilität, Sharpe und beide Policy-Diffs stammen
damit aus dem falschen Marktmodell.

### Risiko

- CH-/DE-Ergebnisse ändern sich abhängig von Insert-Reihenfolge.
- Tenantprivate DE-CMA-Overrides werden nicht verwendet.
- Eine provisional oder nicht genehmigte globale Zeile kann in einen
  kundenbezogenen Vergleich gelangen.
- `cma_id` im Response macht die falsche Auswahl sichtbar, verhindert sie aber
  nicht.

## `AB-MODEL-001` – „Backtest“ ohne stochastic Modell und ohne Kosten

### Tatsächlich gerechnetes Modell

Der A/B-Service lädt je Policy genau die House-Matrix-Zeile des aktuellen
Risk-Score-Buckets. Er berechnet deren statische Targets und ruft
`_expected_metrics(..., sub_allocations=None, products=None)` auf. Nicht
enthalten sind:

- stochastischer Solver und Seed;
- Goals, Cashflows, Liabilities und Reserve;
- Mandats-/Preference-Tilts und externe Exposures;
- globale beziehungsweise mandatsspezifische harte Constraints;
- kanonische Sub-Allokationen und Risky-Fractions;
- Produktselektion, TER und Fee-Modell;
- aktuelle Target Allocation oder deren Policy-/Context-Hash.

Das ist ein House-Matrix-Konfigurationsdiff, kein historischer Backtest und
kein Vergleich der beiden produktiven stochastic Policyergebnisse. UI und
Servicehinweis nennen den House-Pfad zwar, gleichzeitig heißen Modal und
Report „A/B-Backtest“ und die UI zeigt „Expected Return (netto)“.

### Ausgeführte Fee-Reproduktion

Die Default-Policy und ihr Klon enthielten jeweils:

```text
fee_model_json = {"default_advisory_fee_bps": 75}
```

Der A/B-Response meldete für beide:

```text
expected_ter_bps = 0
```

Die als netto bezeichneten Returns sind damit faktisch Bruttowerte. Der
Policyvergleich kann einen realen Kostenunterschied nicht darstellen.

### Automatische Advisory-Auswahl

Der Advisory-Builder nimmt als B die globale Current-Policy und als A die
jüngste beliebige andere Policy. Er bindet keine der beiden an
`TargetAllocation.policy_id`, keinen expliziten Nutzerentscheid und keinen
Publication-Fingerprint. Nach einem Policy-Rollover kann derselbe Report daher
ein anderes A/B-Paar zeigen, obwohl die Allocation unverändert blieb. Jeder
Fehler wird broad zu `data_pending` statt zu einem klaren Contextkonflikt.

## Verbindlicher Fixvertrag

### Stress-Context

1. Jede Stress-Route und jeder PDF-/Advisory-Consumer erhält einen bereits
   verifizierten Allocation-/Publication-Context. Keine eigene `.first()`-
   Current-Abfrage im Stress-Service.
2. Exakt eine moderne TA, aktuelle/verankerte RA, Policy und Snapshot-CMA sowie
   Input-/Context-Hash und die drei Artefakte werden vor Berechnung geprüft.
3. Gewichte sind exakte, bool-sichere Integer in 0..10.000 und summieren sich
   exakt auf 10.000. Ein Raw-/Legacy-Fehler endet 409; keine Kappung oder
   Normalisierung im Rechner.
4. Verwendete Gewichte kommen aus dem verifizierten Target-Payload. Wenn das
   Szenario Sub-Allokationen benötigt, stammen sie aus dem persistierten
   Allocation-Context, nie aus Live-Produkten.
5. Ergebnis bindet TA-/RA-/Policy-/CMA-ID, Allocation-/Input-Hash,
   Scenario-Catalog-ID/-Version/-Hash, Berechnungsversion und einen
   `stress_result_fingerprint`.

### Szenariokatalog und Mathematik

6. Ein zentraler versionierter Katalog definiert pro Szenario Quelle,
   Frequenz, exakte Periodengrenzen, Asset-/Sub-Asset-Proxies, Währung,
   Hedging, Returntyp, As-of, Approval und Hash.
7. Solver-, historisches Replay-, API- und PDF-Szenarien verwenden denselben
   Katalog oder tragen bewusst verschiedene Typen wie
   `historical_bucket_replay` und `goal_cashflow_stress`. Gleiche Namen dürfen
   keine abweichende, unsichtbare Methodik besitzen.
8. Ein als Max Drawdown ausgewiesener Wert braucht eine Frequenz, die den
   Peak-to-Trough-Verlauf enthält. Bei reinen Jahresenddaten heißt die Kennzahl
   ausdrücklich „maximaler Jahresendverlust“, nicht Krisen-Max-DD.
9. Recovery wird aus dem konkreten Portfoliopfad berechnet. Falls stattdessen
   die Recovery eines Referenzindex gezeigt wird, heißt das Feld entsprechend
   und nennt Index/Quelle; ein Portfolio ohne Drawdown erhält keine
   Portfolio-Recovery.
10. Cashflows, Liabilities, Rebalancing und Horizon sind pro Szenariotyp
    explizit. Ein finaler Report darf nicht unmarkiert einen cashflowfreien
    Replay neben ein cashflowabhängiges Solverresultat stellen.
11. Szenarien werden bei Allocation-/Recommendation-Finalisierung persistiert
    oder über einen unveränderlichen Catalog-Hash reproduzierbar gebunden.
    Ein Live-Codeupdate ändert keinen historischen Kundenbericht.

### CMA- und Policy-Scope

12. CMA wird ausschließlich über `resolve_mandate_jurisdiction(mandate)` und
    `resolve_cma_for_jurisdiction(..., tenant_id=mandate.tenant_id,
    require_committee_approved=True)` geladen.
13. Für einen historischen, an eine Allocation gebundenen Vergleich gilt deren
    Snapshot-CMA. Ein aktueller What-if-Vergleich verwendet eine explizit
    ausgewiesene aktuelle genehmigte CMA; die zwei Modi werden nicht vermischt.
14. Beide Policy-IDs sind explizit, vorhanden, fachlich vergleichbar und im
    Resultat gebunden. Der finale Kundenbericht wählt nicht still „Current plus
    jüngste andere“.
15. Wenn der Vergleich erklären soll, wie die aktive Allocation gegenüber
    einer Alternative steht, muss mindestens eine Seite exakt
    `TargetAllocation.policy_id` und deren Context entsprechen.

### Wahrer Modellvergleich

16. Produktentscheidung A: Der bestehende Pfad bleibt ein interner
    `HouseMatrixPolicySensitivity`-Report. Dann heißt er nie Backtest,
    stochastic Allocation oder Nettovergleich; Kundenpublikation ist
    standardmäßig ausgeschlossen.
17. Produktentscheidung B: Ein echter A/B-Vergleich baut für beide Policies
    vollständige stochastic Kandidaten aus demselben eingefrorenen Mandat,
    RA, CMA, Wealth-/Goal-/Cashflowstand, Preferences, Building Blocks,
    Sub-Allokationsuniversum, Seed, Szenariocube und Solververtrag.
18. Die beiden Läufe sind read-only und persistieren keine Current-TA. Ihr
    Context-/Resulthash beweist, dass außer der expliziten Policyvariation
    alle Inputs identisch sind.
19. Technischer House-Fallback wird pro Seite sichtbar ausgewiesen und nur
    nach dem produktiven Allowlist-/Feasibility-Vertrag zugelassen. Ein
    stochastic-vs-House-Ergebnis darf nicht als reiner Policyeffekt erscheinen.
20. Fees werden entweder aus exakt identischen Produkt-/Kostenannahmen oder
    aus dem versionierten Policy-Fee-Modell berechnet. „Netto“ ist nur erlaubt,
    wenn `expected_ter_bps`/weitere Fees tatsächlich abgezogen und belegt sind.

### Publikation und HTTP

21. Advisory, Depotcheck, UI und direkte API konsumieren denselben Context und
    Scenario-/A-B-Fingerprint. Mandatory Integritätsfehler werden nicht broad
    zu `data_pending` oder einem partiellen Kundenreport.
22. Fehlende/ambige/stale Anker und CMA-/Policy-Scopefehler ergeben 409 vor
    Renderer. Malformed/gleiche/inkompatible Policyparameter ergeben 422.
23. Jeder Report nennt Modelltyp, Scenario-Version, CMA-/Policy-/Allocation-
    IDs, As-of, Cashflow-/Liability-Einbezug, Fee-Basis und Limitationen.
24. Previewannahmen sind sichtbar gewässert; ein finaler Bericht verlangt den
    vollständigen Publication-Context aus dem Advisory-Publikationsaudit.

## Verbindliche Testmatrix

### Stress-Context und Gewichte

- Kein/duplicate Current-TA, Legacy-TA, fehlendes modernes Artefakt,
  Hashfehler, RA-/Policy-/CMA-Mismatch und Inputdrift ergeben 409; Stresshelper
  und Renderer werden nicht aufgerufen.
- Je Gewicht: negativ, >10.000, Bool, Float, Stringzahl; Summen 0, 9.999,
  10.001 und 15.000 ergeben Domainfehler. Exakt 10.000 roundtrippt.
- DE-/Tenant-Allocation verwendet exakt ihre Snapshot-CMA und ihren
  persistierten Submix; CH-/Globalwerte dürfen nicht erscheinen.
- Advisory-, Depotcheck- und direkte Route liefern denselben Fingerprint und
  identische Werte.

### Szenariomethodik

- 100-%-Bonds-GFC mit durchgehend positivem Pfad hat Portfolio-Drawdown 0 und
  Portfolio-Recovery 0/None; keine feste 36.
- Ein Covid-Crash besitzt einen negativen Peak-to-Trough-Punkt oder wird
  ausdrücklich als Volljahresreturn ohne Krisen-Max-DD bezeichnet.
- Scenario-Version, Quelle, Frequenz, Währung/Hedge, As-of und Hash sind in
  Resultat/PDF testbar und ändern sich deterministisch bei Katalogänderung.
- Solver-/Replay-Parität beziehungsweise explizite Typtrennung wird für GFC
  und Covid geprüft; keine zwei gleich klingenden Wahrheiten ohne Methodiktag.
- Cashflow-/Liability-Einbezug, Horizon und Rebalancing werden mit bekannten
  Pfaden mathematisch gegengeprüft.

### A/B-Scope und Modell

- Mandat DE plus Current CH/DE wählt exakt DE; Tenantoverride gewinnt vor
  firmwide; provisional/fremder Tenant/fehlende CMA ergibt 409.
- Duplicate CMA desselben wirksamen Scopes ergibt Konflikt, nicht `.first()`.
- Policy A/B mit identischem Fee-Modell 75 bps meldet 75 oder einen klar
  benannten Bruttovergleich, niemals Netto/0.
- House-Matrix-Sensitivität besitzt einen eigenen Typ/Titel und erscheint
  nicht als stochastic Backtest.
- Echter stochastic A/B-Lauf bindet gleiche RA/CMA/Inputs/Goals/Cashflows/
  Preferences/Submix/Seed; nur Policy unterscheidet sich. Kein DB-Write.
- Ergebnis zeigt je Seite `stochastic`, technischen Fallback oder Fehler; ein
  versteckter Housepfad ist ausgeschlossen.
- Finaler Advisory-Report verwendet explizite/Allocation-Policy-IDs; ein
  späterer globaler Policy-Rollover ändert den historischen Vergleich nicht.

### Publikation, Race und PostgreSQL

- Context- oder Policy-Rollover zwischen Resolve und Render führt zu 409 oder
  konsistentem Snapshot, nie Hybrid.
- Mandatory Stress-/A-B-Integritätsfehler lassen Renderer-Spy und Cache
  unberührt; kein partieller 200-Report.
- SQLite und PostgreSQL erzeugen für gleichen Catalog-/Context-Hash exakt
  dieselben Szenario- und A/B-Ergebnisse.
- Kunden-PDF-Textprüfung beweist Modeltyp, Scenario-Version, CMA-
  Jurisdiktion, Policy-/TA-IDs, Fees und Limitationen.

## Empfohlene Umsetzungsreihenfolge

1. Produkt Owner trennt ausdrücklich historischen Bucket-Replay,
   goal-/cashflowfähigen Solver-Stress und House-Matrix-Konfigurationsdiff.
2. Gemeinsamen versionierten Scenario-Catalog samt Quellen-/Approval-/Hash-
   Vertrag definieren und beide vorhandenen Hardcodebibliotheken inventarisieren.
3. Stress-Reader auf den verifizierten Allocation-/Publication-Context und
   strikte Gewichtdomain umstellen.
4. Recovery-/Drawdown-/Periodenmethodik korrigieren und historische
   Kundenberichte an unveränderliche Catalog-Versionen binden.
5. A/B-CMA über Jurisdiktion/Tenant/Approval auflösen und automatische
   Advisory-Policywahl entfernen.
6. House-Matrix-Sensitivität intern korrekt benennen oder einen echten
   read-only stochastic A/B-Runner bauen; Fee-/Nettovertrag schließen.
7. Context-, Math-, Cross-Jurisdiction-, Scenario-, A/B-, PDF-, Race- und
   echte PostgreSQL-Tests ausführen.

## Definition of Done

Die vier Findings gelten erst als geschlossen, wenn gleichzeitig:

- jeder Stresswert an eine vollständig verifizierte moderne Allocation und
  exakt 10.000 bps gültige Gewichte gebunden ist;
- Scenario-Katalog, Quelle, Frequenz, Perioden, As-of, Approval und Hash
  versioniert und im Resultat sichtbar sind;
- Drawdown und Recovery fachlich aus dem ausgewiesenen Portfoliopfad stammen
  oder korrekt als Referenzindexkennzahlen bezeichnet werden;
- Solver-, Advisory-, Depotcheck- und API-Stress entweder dieselbe Wahrheit
  oder klar getrennte, benannte Modelltypen zeigen;
- jede A/B-CMA Mandatsjurisdiktion, Tenant und Committee-Approval respektiert;
- kein House-Matrix-Diff als stochastic/historischer/Netto-Backtest erscheint;
- echte Nettoangaben alle dokumentierten Fees einbeziehen;
- final publizierte Policyvergleiche explizite, fingerprintgebundene Policy-
  und Allocation-Contexts verwenden;
- Context-, Domain-, Math-, Scenario-, Cross-Jurisdiction-, PDF-, Race- und
  echte PostgreSQL-Tests grün sind;
- der vollständige Backend-/Frontend-Gate auf dem Fixcommit erneut grün ist;
  und
- dieser Audit mit Fixcommit, Testzahlen und Restpunkten aktualisiert oder
  durch einen klar verlinkten Abschlussaudit ersetzt wurde.

## Claude-/GPT-Startcheckliste

Vor Änderungen an Stress-Replay oder Policy-A/B:

1. Diesen Audit und den direkt vorgelagerten Strategy-Backtest-/Snapshot-
   sowie Advisory-Publikationsaudit vollständig lesen.
2. Nicht nur `.first()` durch einen anderen Query ersetzen: zuerst Context,
   Szenariotyp und Publikationsmodus definieren.
3. Den bestehenden Allocation-Rebuild und die Jurisdiktionsresolver
   wiederverwenden.
4. Legacy-Replay und stochastic Solver-Stress nicht unter demselben Begriff
   vermischen; Catalog-Version und Methodik sind Pflicht.
5. Recovery niemals als Portfolioergebnis ausgeben, wenn sie nur ein fixer
   Referenzindexwert ist.
6. A/B nur dann „stochastic Backtest“ oder „netto“ nennen, wenn genau das
   gerechnet und belegt wird.
7. House-Matrix-Sensitivität darf als internes Diagnosewerkzeug bleiben, muss
   aber einen eigenen Typ und klare Grenzen besitzen.
8. DE-/Tenant-CMA niemals über globale Current-Auswahl ersetzen.
9. Advisory-/PDF-Fehler nicht broad zu `data_pending` machen, wenn ein
   mandatory Entscheidungs- oder Modellanker fehlt.
10. Produkt-/Testfix und nachgelagerte Dokumentation getrennt tracebar halten.

## Unveränderte Baseline- und Audit-Evidenz

Der letzte vollständige Backend-Gate des Implementierungscommits bleibt:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
1681.86s (28:01), Exit 0
```

Der fokussierte bestehende Stress-/A-B-/Advisory-/Depotcheck-Ring auf dem
auditierten Head ergab:

```text
116 passed, 0 skipped, 1 warning in 82.64s
```

Ausgeführt wurden:

```text
tests/test_backtest_ab.py
tests/pdf/test_ab_backtest_pdf.py
tests/test_optimizer_stress_scenarios.py
tests/test_advisory_report.py
tests/test_depot_check.py
```

Die grünen Tests widerlegen die Findings nicht. Sie prüfen Happy-Path-
House-Matrix-Diffs, gleiche/fehlende Policy, Assessmentpflicht,
Read-only-Verhalten, getrennte Legacy-/Solver-Stress-Pure-Math-Helfer,
Advisory-`data_pending` und PDF-Rendering. Sie enthalten weder beschädigten
modernen Stress-Context, ungültige Gewichtssummen, Recovery-Semantik,
Katalogparität, DE-versus-CH-CMA noch Policy-Fee-/stochastic-Modellwahrheit.
