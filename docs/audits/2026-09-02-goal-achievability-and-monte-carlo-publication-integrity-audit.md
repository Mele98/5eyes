---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-goal-achievability-and-monte-carlo-publication-integrity-followup-audit"
status_as_of: "2026-09-02"
audit_started_on: "2026-09-02"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend/reporting"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "db763b50123fbdc1dd4580c8182f3532e7359e59"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md"
prior_release_audit_commit: "db763b50123fbdc1dd4580c8182f3532e7359e59"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md"
audit_mode: "read_only_static_service_orm_pdf_api_react_review_targeted_runtime_reproduction_existing_backend_and_frontend_test_gates"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "goal snapshot and score integrity, conditional-goal probability semantics, Monte Carlo decision context, projection cashflows and currencies, status and quantile semantics, API React and PDF publication parity"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
focused_backend_tests_passed: 136
focused_backend_tests_failed: 0
focused_frontend_tests_passed: 97
focused_frontend_tests_failed: 0
required_next_action: "define one immutable goal-analysis snapshot and one explicit probability model, bind goal rows, aggregate score and Monte Carlo paths to the same allocation context, then make API, React and every PDF reject stale, invalid or semantically ambiguous evidence with identical currency, status and quantile contracts"
---

# Zielerreichbarkeits- und Monte-Carlo-Publikationsintegritätsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die zwanzigste Read-only-
Kontrollrunde. Er wurde gegen den unveränderten Repository-Head `db763b50`
durchgeführt und am 2. September 2026 als maschinen- und menschenlesbarer
Handoff konsolidiert. Er ergänzt, ersetzt aber nicht:

1. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
2. den
   [Performance-Attribution-Context-/Modellintegritätsaudit](2026-08-31-performance-attribution-context-and-model-integrity-audit.md),
3. den
   [Stress-Replay-/Policy-A/B-Modellintegritätsaudit](2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md),
4. den
   [Strategy-Backtest-Context-/Gebühren-/Publikationsintegritätsaudit](2026-08-28-strategy-backtest-context-fee-and-publication-integrity-audit.md),
5. den
   [Strategy-Snapshot-Provenienz-/Zeitintegritätsaudit](2026-08-28-strategy-snapshot-provenance-and-temporal-integrity-audit.md),
6. den
   [Historische-Renditen-/Schema-/Driftintegritätsaudit](2026-08-28-historical-return-schema-and-drift-integrity-audit.md),
7. den
   [Marktpreis-/FX-Referenzintegritätsaudit](2026-08-27-market-price-and-fx-reference-integrity-audit.md),
8. den
   [Produktstammdaten-/Exposure-Integritätsaudit](2026-08-27-product-master-data-and-exposure-integrity-audit.md),
9. den
   [Referenzdaten-Leserechte-/Modellbasis-Audit](2026-08-27-reference-data-read-authorization-and-model-basis-audit.md),
10. den
    [Advisory-Workflow-/Zeitintegritätsaudit](2026-08-27-advisory-workflow-and-temporal-integrity-audit.md),
11. den
    [Review-Trigger-/Reassessment-Integritätsaudit](2026-08-27-review-trigger-and-reassessment-integrity-audit.md),
12. den
    [Kundenklassifikations-/Compliance-State-Audit](2026-08-27-client-classification-and-compliance-state-audit.md),
13. den
    [Tenant-/Compliance-Referenzintegritätsaudit](2026-08-27-tenant-and-compliance-reference-integrity-audit.md),
14. den
    [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
15. den
    [Recovery-Link-/Mail-Transport-Audit](2026-08-27-recovery-link-mail-transport-security-audit.md),
16. den
    [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
17. den
    [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
18. den
    [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
19. den
    [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
20. den
    [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Laufzeitbelege
zuerst, danach dieser Audit und anschließend die vorgenannten Dokumente in
dieser Reihenfolge. Die Kontrollrunde hat keine Produkt- oder Testdatei
verändert.

## Kurzurteil

**Release bleibt hart blockiert.** Die publizierte Zielanalyse ist kein
unveränderlicher Bestandteil des Entscheids. Sie ist eine zur Lesezeit
zusammengebaute Mischsicht aus mindestens drei unterschiedlichen Zuständen:

1. Wahrscheinlichkeiten, Status und Labels aus dem
   `TargetAllocation.goal_achievability_json` des Optimizer-Laufs;
2. aktuelle Zielbeträge, Zieltermine, Zieltypen und Gewichte aus `Goal`;
3. auf Abruf neu simulierte Quantilpfade aus aktuellem Beratungsvermögen,
   aktuellen manuellen Cashflows, aktueller TA und der ersten globalen
   Current-CMA.

Die vorhandene Goal-Invalidierung setzt nur `Goal.achievement_score` auf
`NULL`. Der Advisory-Report liest dieses Feld jedoch weder für seine
Zielzeilen noch für seinen Gesamt-Score. Nach Create, Update oder Delete eines
Ziels kann deshalb weiterhin die alte TA-Wahrscheinlichkeit erscheinen,
kombiniert mit neuem Betrag/Termin/Gewicht. Ein neues Ziel fehlt, ein
gelöschtes Ziel bleibt, und ein reines Live-Gewichtsupdate ändert den
publizierten Score ohne neue Optimierung.

Zusätzlich liegen mehrere voneinander unabhängige fachliche Verträge unter
denselben Kundenlabels:

- Der Advisory-„Zielerreichungs-Score“ ist nur ein mit heutigen Gewichten
  gemittelter Probability-Wert. Die Engine definiert bereits einen anderen
  `achievement_score` aus Success Rate, Funding Ratio und Hardness sowie eine
  separate Mandatsaggregation mit Hardness-Multiplikatoren.
- Bedingte Ziele werden auf ihren Erwartungswert verkleinert. Anschließend
  wird die Wahrscheinlichkeit, diesen verkleinerten Betrag zu finanzieren, als
  „Erreichungswahrscheinlichkeit“ publiziert. Diese Zahl ist weder die
  bedingte Wahrscheinlichkeit, den vollen Zielbetrag bei Eintritt zu
  finanzieren, noch die unbedingte Erfolgswahrscheinlichkeit.
- Der Optimizer klassifiziert gegen die zielindividuelle Schwelle `tau`; das
  Reporting klassifiziert dasselbe Ziel zusätzlich gegen p50/p75 eines
  separaten Portfoliopfads. Der Advisory-PDF zeigt beide Ampeln nebeneinander,
  ohne die verschiedenen Fragen und Modellbasen zu erklären.
- Ein p5-p75-Band enthält 70 Prozent der empirischen Pfadmasse. React nennt es
  trotzdem „90% des Pfade-Korridors“ und ein „Konfidenz-Band“; p75 wird
  außerdem als „Best-Case“ behandelt.
- Probability-Werte außerhalb `[0,1]` werden im Advisory-JSON unverändert zu
  negativen oder über 100-prozentigen Werten. `NaN` bricht den Report ab. Ein
  anderer PDF-Pfad klemmt dieselben ungültigen Werte still auf `[0,1]`.
- Das Live-MC-Modell ignoriert Snapshot-CMA, Suballokationen, FX, Goal-
  Liabilities, Reserve, Steuern, Fees, Rebalancing und große Teile der
  Cashflow-Domain. Unbekannte Cashflow-Typen werden als positiver Zufluss
  behandelt. React formatiert Ziel und Achse hart als CHF, während der
  Advisory-PDF eine Currency entgegennimmt.

Grüne Testgates sind kein Gegenbeweis: Fokussiert liefen 136 Backend- und 97
Frontend-Tests erfolgreich. Darunter befinden sich Tests, welche die
Erwartungswert-Skalierung bedingter Ziele und die zweite p50/p75-
Statusdefinition ausdrücklich festschreiben. Es fehlen dagegen
Mixed-Snapshot-, Probability-Domain-, Semantik-, Cross-Currency-,
Cross-Channel- und Publication-Preflight-Negativtests.

## Stabiles Findings-Register

| ID | Prio | Status | Releasewirkung |
|---|---:|---|---|
| `GOAL-SNAPSHOT-001` | P1 | bestätigt | Alte TA-Wahrscheinlichkeit wird mit aktuellen Zielmetadaten und Gewichten gemischt; Create/Update/Delete invalidiert die Publikation nicht. |
| `GOAL-SCORE-001` | P1 | bestätigt | Zwei unterschiedliche Score-Formeln tragen praktisch denselben Namen; Missing wird in der Zielsektion als echte Null publiziert. |
| `GOAL-DOMAIN-001` | P1 | bestätigt | Negative/überhöhte Probabilities passieren; `NaN` crasht; ein anderer PDF-Kanal klemmt dieselben Werte still. |
| `GOAL-CONDITIONAL-001` | P1 | bestätigt | Probability eines Expected-Value-Targets wird als volle Zielerreichungswahrscheinlichkeit dargestellt. |
| `MC-CONTEXT-001` | P1 | bestätigt | Das Report-Chart ist eine unabhängige Live-Neusimulation und nicht die Evidenzbasis der persistierten Goal-Wahrscheinlichkeit. |
| `MC-CASHFLOW-CURRENCY-001` | P1 | bestätigt | Cashflow-, FX-, Currency-, Fee-, Tax-, Reserve- und Rebalancing-Vertrag weicht von der Engine ab. |
| `MC-STATUS-001` | P1 | bestätigt | Optimizer-Status gegen `tau` und Reporting-Status gegen p50/p75 können für dasselbe Ziel widersprechen. |
| `MC-QUANTILE-001` | P1 | bestätigt | p5-p75 wird fälschlich als 90-Prozent-/Confidence-Band und p75 als Best Case beschrieben. |
| `GOAL-PUBLICATION-001` | P1 | bestätigt | API, React, Advisory-PDF und Strategie-PDF besitzen keine einheitliche, contextgebundene Goal-Analytics-Semantik. |

Kein Finding aus früheren Audits wird durch diese Liste geschlossen. Ein P1
in kundenorientierter Entscheidungs-, Probability- oder Currency-Darstellung
blockiert Final-/Kundenpublikation unabhängig vom grünen Unit-Teststand.

## Codeanker auf dem auditierten Head

Die wichtigsten Anker sind:

- `5eyes-backend/routers/wealth.py:346-377`, `780-814`, `817-853`,
  `856-878`: Goal-Mutationen nullen nur `Goal.achievement_score`.
- `5eyes-backend/services/advisory_report.py:704-735`: Report-Score aus
  persistierter Probability und aktuellem `Goal.weight_bps`.
- `5eyes-backend/services/advisory_report.py:1964-2058`: persistierte
  Goal-Zeilen werden mit aktuellen Goal-Metadaten gemischt; Missing-Score wird
  zu `0`.
- `5eyes-backend/services/advisory_report.py:2061-2104`: Live-Wealth und
  Live-Horizont starten eine neue MC-Berechnung; Wealth wird ohne FX summiert.
- `5eyes-backend/services/optimizer/objective.py:335-405`: Probability,
  `tau` und Optimizer-Status des persistierten Achievability-Objekts.
- `5eyes-backend/services/optimizer/goal_liabilities.py:91-130`,
  `350-484`: Default-Rank-Gewichte und Pro-rata-Skalierung bedingter Ziele.
- `5eyes-backend/services/portfolio_engine_payload.py:244-322`: bereits
  vorhandene kanonische Goal-Score- und Mandats-Score-Formeln.
- `5eyes-backend/models/allocation.py:77-90`: rohes Goal-JSON neben modernen
  Allocation-Context-Ankern.
- `5eyes-backend/services/portfolio_engine.py:3803-3813`, `3976-4023`:
  Persistierung des rohen Goal-JSON und des Allocation-Contexts.
- `5eyes-backend/services/monte_carlo_paths.py:68-172`, `217-345`: eigene
  Current-CMA-, Weight-, Cashflow- und Simulationspipeline des Reports.
- `5eyes-electron/frontend/reporting/src/api/types.ts:360-397`: Goal-/MC-
  Payload ohne Currency-, Context-, Modell- oder Probability-Semantik.
- `5eyes-electron/frontend/reporting/src/lib/goalClassification.ts:1-20`,
  `52-119`: zweite, p50/p75-basierte Statusdefinition.
- `5eyes-electron/frontend/reporting/src/components/MonteCarloPathsChart.tsx:1-20`,
  `118-136`, `264-277`, `300-306`: CHF-, Confidence- und 90-Prozent-Labels.
- `5eyes-electron/frontend/reporting/src/pages/Goals.tsx:55-84`, `152-204`:
  kundenorientierte Score-/Probability-Ausgabe und CHF-Zielwerte.
- `5eyes-backend/services/pdf/documents/advisory_report.py:1279-1420`:
  Advisory-PDF mit eigenem MC-Status neben persistiertem Status.
- `5eyes-backend/services/pdf/components/goal_achievability.py:119-205`:
  Strategie-PDF klemmt Probability still auf `[0,1]`.
- `5eyes-backend/routers/pdf_reports.py:752-777`, `804-815`: Strategie-PDF
  übernimmt das rohe TA-Goal-JSON direkt.

## `GOAL-SNAPSHOT-001` – Goal-Invalidierung erreicht die Publikation nicht

### Tatsächlicher Datenfluss

`_invalidate_achievement_scores_for_mandate()` dokumentiert korrekt, dass
jedes Hinzufügen, Ändern oder Löschen eines Ziels alle Zielresultate stale
machen kann. Es setzt jedoch ausschließlich `Goal.achievement_score` auf
`NULL`.

Der Advisory-Report verwendet dieses Feld nicht:

- `_compute_goal_achievement_score_bps()` liest die Rows aus
  `TargetAllocation.goal_achievability_json`;
- zu jeder Row wird das aktuell aktive `Goal` gesucht;
- Probability stammt aus der alten Row, Gewicht aus dem heutigen Goal;
- `_build_goal_based_investing()` iteriert ausschließlich über persistierte
  Rows, sofern mindestens eine Row existiert;
- Label und Hardness kommen primär aus der alten Row;
- Zieltyp, Zielbetrag und Zieldatum kommen aus dem heutigen Goal;
- ist das Ziel inzwischen gelöscht, bleibt die Row mit leerem Typ, Betrag
  null und altem Label sichtbar;
- ist ein Ziel neu hinzugekommen, fehlt es vollständig, solange alte Rows
  vorhanden sind.

Das Ergebnis ist weder ein historischer Snapshot noch eine valide aktuelle
Analyse. Es ist ein Feld-für-Feld-Mix.

### Ausgeführte Reproduktion

Die isolierte Service-Reproduktion legte zwei persistierte TA-Rows an:

- `g1`: altes Label, Probability `0.9`;
- `g-del`: bereits gelöschtes Ziel, Probability `0.1`.

Aktiv waren danach:

- `g1`: neuer Zielbetrag und neuer Termin;
- `g-new`: neu hinzugefügtes Ziel, Gewicht `10000`.

Der Report lieferte:

```text
{'goals': [
 {'goal_id': 'g1', 'label': 'Altes Ziel',
  'goal_type': 'Vermoegensziel',
  'target_amount_rappen': 99900, 'target_date': '2045-12-31',
  'hardness': 'primaer', 'probability_bps': 9000,
  'status': 'erreichbar'},
 {'goal_id': 'g-del', 'label': 'Geloeschtes Ziel',
  'goal_type': '', 'target_amount_rappen': 0, 'target_date': '',
  'hardness': 'hart', 'probability_bps': 1000,
  'status': 'nicht_erreichbar'}
], 'score': 5000}
{'score_after_live_weight_change': 8999}
```

Damit sind alle vier Integritätsbrüche direkt belegt:

1. das neue Ziel fehlt;
2. das gelöschte Ziel bleibt;
3. altes Label und neue Zielparameter erscheinen in derselben Zeile;
4. eine reine Änderung heutiger Gewichte verändert den alten Ergebnis-Score
   von `5000` auf `8999`, ohne neuen Optimizer-Lauf.

### Fixvertrag

Eine veröffentlichbare `GoalAnalysisSnapshot` muss mindestens enthalten:

- `schema_version`, `analysis_id`, `allocation_id`, `optimization_run_id`;
- `allocation_context_hash`, `input_snapshot_hash`, `computed_at`;
- Tenant-, Mandats-, Client-, Jurisdiktions-, RA-, Policy- und
  Snapshot-CMA-Anker;
- eine geordnete Goal-Set-ID oder einen kanonischen `goals_snapshot_hash`;
- pro Ziel unveränderlich: ID, Label, Type, Scope, Value Mode, Full Target,
  Effective/Expected Target, Currency, Start/Target Date, Occurrence
  Probability, Hardness, Rank, Weight und Tau;
- Modellversion, Probability-Semantik, Path Count, Seed, Weighting-/IS-Methode
  und alle Ergebnisfelder.

Final-/Kundenpublikation muss vor Cache und Renderer blockieren, wenn das
aktuelle entscheidungsrelevante Goal-Set nicht dem Snapshot entspricht. Eine
Goal-Mutation muss den Publication-State des Mandats atomar auf stale setzen.
Das nachträgliche Joinen heutiger Stammdaten in historische Resultate ist
unzulässig. Soll ausdrücklich eine aktuelle What-if-Sicht gezeigt werden,
braucht sie eine eigene, klar als Preview markierte Analyse-ID und darf nicht
als damaliger Entscheidungsbeleg erscheinen.

## `GOAL-SCORE-001` – Ein Name, zwei fachlich andere Scores

### Advisory-Score

`_compute_goal_achievement_score_bps()` bildet einen Mittelwert der
persistierten Goal-Probabilities. Als Gewichte dienen aktuelle
`Goal.weight_bps`; fehlende, gelöschte oder nicht positive Gewichte werden
gleich `1.0` gesetzt. Der Helper nennt sich „einzige Quelle“, aber nur für zwei
Advisory-Darstellungen.

Wenn Goals existieren, aber keine TA-Row verfügbar ist, erzeugt die
Goal-Sektion `goal_achievement_score_bps=0`. Später wird auch ein Helper-
Ergebnis `None` zu null konvertiert. Damit wird „nicht berechnet“ als
„0 Prozent Zielerreichung“ dargestellt.

### Bereits vorhandener Engine-Score

`portfolio_engine_payload._compute_goal_score()` definiert dagegen:

```text
achievement_score = alpha(hardness) * success_rate
                  + (1 - alpha(hardness)) * funded_ratio
```

Die Werte werden auf `[0,100]` begrenzt. `_build_mandate_score()` aggregiert
danach mit `weight_bps * hardness_multiplier` und publiziert zusätzlich das
schwächste harte Ziel. Die Engine besitzt außerdem geometrische Default-
Gewichte nach Rank (`10000`, `5000`, `2500`, ...), während der Advisory-Report
fehlende Gewichte pauschal gleichgewichtet.

Das sind legitime, aber verschiedene Metriken:

- Probability of Success;
- Funding Ratio;
- per-Goal Achievement Score;
- gewichteter Mandate Score;
- Weakest Hard Goal.

Sie dürfen nicht unter einem einzigen Label zusammenfallen.

### Fixvertrag

Es braucht einen versionierten `GoalScoreSummary` mit expliziten Feldern und
Einheiten, zum Beispiel:

```text
probability_of_full_funding_bps
funded_ratio_p50_bps
achievement_score_x100
mandate_weighted_score_x100
weakest_hard_goal_score_x100
score_method_version
weight_source
```

API und UI müssen `available`, `unavailable`, `stale` und `invalid` trennen.
`None` darf niemals zu null werden. Fallbackgewichte müssen exakt denen des
Optimizers entsprechen oder als andere, bewusst versionierte Reporting-
Methodik bezeichnet werden. Ein Score wird zusammen mit seinen Komponenten,
Hardness-Regeln und Snapshotgewichten persistiert und nicht aus heutigen
Gewichten rekonstruiert.

## `GOAL-DOMAIN-001` – Probability-Domain und Kanäle widersprechen sich

Der Advisory-Builder wandelt `probability` ungeprüft mit `float(...)` um und
multipliziert anschließend mit `10000`. Es gibt keine Prüfung auf:

- boolesche Werte;
- Endlichkeit;
- Bereich `[0,1]`;
- Übereinstimmung von Probability, Tau und Status;
- eindeutige Semantik und Einheit.

Die Reproduktion lieferte:

```text
{'published_probabilities': [-2000, 15000], 'aggregate_score': 6500}
{'nan_exception': 'ValueError',
 'message': 'cannot convert float NaN to integer'}
```

Ein negativer und ein 150-prozentiger Wert werden somit kundenorientiert
publiziert; ihr arithmetischer Mittelwert sieht mit 65 Prozent plausibel aus.
`NaN` führt dagegen zum ungefangenen Reportabbruch.

Der Strategie-PDF behandelt dieselben Eingangswerte anders:

```python
max(0.0, min(1.0, float(probability)))
```

Er repariert ungültige Evidenz still zu 0 oder 100 Prozent. Dadurch können API,
Advisory-PDF und Strategie-PDF aus demselben gespeicherten Artefakt
unterschiedliche Wahrheiten erzeugen.

### Fixvertrag

- Persistenz und Publication-Preflight akzeptieren nur endliche, echte Zahlen
  in `[0,1]`; bool ist kein Integer-/Float-Ersatz.
- Tau liegt ebenfalls endlich in `[0,1]`.
- Status wird serverseitig aus Probability, Tau und einer versionierten Regel
  abgeleitet oder gegen diese Regel verifiziert.
- Ungültige moderne Evidenz ist `blocked`; sie wird weder geklemmt noch als
  Missing interpretiert.
- Legacy-Missing ist explizit `unavailable`, nicht null Prozent.
- Alle Kanäle konsumieren das bereits validierte DTO; Renderer besitzen keine
  eigene fachliche Korrekturlogik.

## `GOAL-CONDITIONAL-001` – Expected Funding wird als Erfolgswahrscheinlichkeit bezeichnet

`Goal.probability_pct` beschreibt die Eintrittswahrscheinlichkeit eines
bedingten Ziels. Die Liability-Pipeline multipliziert den vollen Zielbetrag
vor der Pfadauswertung mit diesem Faktor. Bei 50 Prozent Eintritt wird aus
einem Ziel von 100 eine deterministische Liability von 50. Der
Chance-Constraint berechnet danach `P(wealth >= 50)` und nennt das Resultat
`probability` beziehungsweise „Erreichungswahrscheinlichkeit“.

Die kontrollierte Reproduktion nutzte:

- vollen Zielbetrag: `100`;
- Eintrittswahrscheinlichkeit: `0.5`;
- jeden Wealth-Pfad: `60`.

Ergebnis:

```text
{
 'full_target': 100,
 'occurrence_probability': 0.5,
 'engine_scaled_target': 50,
 'reported_achievement_probability': 1.0,
 'conditional_full_target_probability': 0.0,
 'unconditional_success_probability': 0.5
}
```

Die publizierte 100-Prozent-Zahl beantwortet somit keine der zwei üblichen
Kundenfragen:

- `P(voller Zielbetrag finanziert | Ziel tritt ein)` ist hier 0 Prozent;
- `P(kein Eintritt oder voller Betrag finanziert)` ist hier 50 Prozent.

Sie beantwortet nur `P(Expected-Value-Liability finanziert)`. Bestehende Tests
schreiben diese Skalierung ausdrücklich fest und erwarten bei halbiertem
Target eine höhere Funding Ratio. Das belegt die Implementierung, aber nicht
die kundenorientierte Benennung.

### Verbindliche Produktentscheidung

Vor Implementierung muss genau eine Semantik gewählt und versioniert werden:

1. **Event-Semantik:** Eintritt je Pfad modellieren und sowohl bedingte als
   auch unbedingte Full-Target-Probability ausweisen. Für Chance Constraints
   wird klar festgelegt, welche davon gegen `tau` gilt.
2. **Expected-Funding-Semantik:** Pro-rata-Liability beibehalten, das Resultat
   jedoch ausschließlich als Wahrscheinlichkeit der Finanzierung der
   erwarteten Liability bezeichnen. Es darf nicht als volle
   Zielerreichungswahrscheinlichkeit erscheinen.

Unabhängig von der Wahl müssen Full Target, Effective Target,
Occurrence Probability, Conditional/Unconditional Definition und Method
Version im Snapshot sichtbar bleiben. Reserve-, Optimizer-, Goal-Analysis-
und PDF-Pfade müssen dieselbe Semantik verwenden.

## `MC-CONTEXT-001` – Das Chart ist nicht die Evidenz der Goal-Wahrscheinlichkeit

Die persistierte Goal-Probability stammt aus den Wealth-Pfaden des Optimizer-
Laufs. Das Advisory-Chart lädt beim Lesen dagegen neu:

- aktuelle TA über Mandat;
- die erste globale CMA mit `is_current=1`;
- aktuelle Beratungsvermögenspositionen;
- aktuellen Mandatshorizont;
- aktuelle manuelle Cashflows;
- fixe `1000` Pfade und einen eigenen konstanten Default-Seed;
- das aktuelle Kalenderjahr als erste Achse.

Nicht übernommen werden unter anderem:

- Snapshot-CMA und deren Modell-/Jurisdiktionsbasis;
- Optimizer-Run-ID, Run-Seed, Path Count und Importance-Sampling-Gewichte;
- Suballokationen und vollständige Constraints;
- der vollständige Input Snapshot und sein Hash;
- Goal Liabilities und Conditional-Goal-Modell;
- Reserve und externe Vermögens-/Verbindlichkeitsserien;
- FX-Konversionen;
- Fees, Tax, Rebalancing und Executionannahmen.

Damit ist das Chart weder Reproduktion noch Visualisierung der darunter
angezeigten Probability. Eine neue globale CMA kann das Chart verändern,
während Probability und Status aus der alten TA unverändert bleiben. Eine
Goal-Mutation kann umgekehrt Live-Wealth/Datum verändern, ohne die alte
Probability zu invalidieren.

### Fixvertrag

Eine kundenorientierte Goal-Seite braucht einen einzigen
`GoalAnalysisPublicationContext`. Zulässig sind zwei Architekturen:

- die Quantilpfade werden bei der Optimierung als unveränderliches,
  komprimiertes Artefakt mit exakt derselben Pfadpopulation persistiert; oder
- sie werden deterministisch aus dem vollständigen, validierten Snapshot des
  referenzierten Runs rekonstruiert.

In beiden Fällen müssen mindestens Analysis-/Run-/Allocation-/CMA-/Policy-/
RA-/Goal-Set-/Currency-Anker, Model Version, Seed, Path Count,
Sampling-/Weighting-Methode, As-of und Horizon zurückgegeben werden. Ein
Live-What-if-Chart ist als eigene Preview erlaubt, aber darf nicht neben alten
Final-Probabilities wie deren Beleg aussehen.

## `MC-CASHFLOW-CURRENCY-001` – Die Reportprojektion besitzt eine eigene verkürzte Welt

`_compute_beratungsvermoegen_rappen()` summiert `current_value_rappen` aller
Beratungsvermögenspositionen direkt. `WealthPosition` besitzt jedoch ein
Currency-Feld; die Engine hat einen FX-bewussten Inputpfad. Die Reportsumme
interpretiert damit beispielsweise EUR- und CHF-Rappen als gleiche Einheit.

`_annual_cashflow_series()` reduziert aktuelle manuelle Cashflows auf einen
konstanten Jahresbetrag:

- Monat wird mit 12, Quartal mit 4 multipliziert;
- weitere Frequenzen werden nicht fachlich normalisiert;
- Valid-from/-to und genaue Zahlungszeitpunkte fehlen;
- Inflation und Cashflowänderungen fehlen;
- Currency und FX fehlen;
- Wealth-derived Flows, Goal Liabilities, Reserve und Steuern fehlen;
- unbekannte Cashflow-Typen werden als positiver Zufluss gewertet.

Dieser Betrag wird für jedes Jahr identisch wiederholt. Die Simulation nutzt
nur die fünf Top-Level-TA-Gewichte und die aktuelle globale CMA.

Parallel fehlen im TypeScript-Vertrag Currency und Base Currency. React nutzt
`formatChfRappen` und beschriftet die Achse als CHF. Der Advisory-PDF nimmt
dagegen eine Currency entgegen. Ein fremdwährungsdominiertes oder EUR-
Mandat kann dadurch mathematisch falsch simuliert und anschließend falsch
beschriftet werden.

### Fixvertrag

- Startvermögen, Flows, Ziele und externe Assets laufen durch dieselbe
  quantisierte, as-of-gebundene FX-Pipeline wie der Entscheidungsrun.
- Jede Zahl führt `currency`, `base_currency`, `fx_snapshot_id`, `fx_as_of`
  und gegebenenfalls den verwendeten Rate-/Rounding-Vertrag mit.
- Cashflows nutzen die kanonische Projected-Cashflow-Serie mit Frequency,
  Timing, Validity, Direction, Inflation und Tax.
- Unbekannte Typen, Frequenzen oder Währungen blockieren; sie werden nie zu
  positivem Einkommen.
- Fees, Tax, Rebalancing, Reserve und Goal Liabilities sind entweder exakt
  modelliert oder als nicht enthaltene Modellgrenze sichtbar. Final darf nicht
  still auf ein V1-Teilmodell degradieren.
- React und beide PDFs formatieren ausschließlich anhand der Payload-Currency.

## `MC-STATUS-001` – Zwei Ampeln beantworten zwei verschiedene Fragen

Der Optimizer setzt:

```text
erreichbar        wenn probability >= goal.tau
knapp             wenn probability >= 0.50
nicht_erreichbar  sonst
```

Das Reporting setzt separat:

```text
erreichbar        wenn p50[target_date] >= target
knapp             wenn p75[target_date] >= target > p50[target_date]
nicht_erreichbar  wenn p75[target_date] < target
```

Die zweite Regel kennt weder `tau` noch die per-Goal-Pfaddefinition. Sie nutzt
zudem die unabhängige Live-MC-Population aus `MC-CONTEXT-001`.

Die Reproduktion mit 100 Pfaden verwendete 60 Werte zu `110`, 40 Werte zu
`90`, Ziel `100` und `tau=0.80`:

```text
{
 'optimizer_probability': 0.6,
 'goal_threshold_tau': 0.8,
 'optimizer_status': 'knapp',
 'chart_p50': 110.0,
 'frontend_mc_status': 'erreichbar',
 'p5_p75_probability_mass': 0.7
}
```

Der Advisory-PDF zeigt `Status` und `MC-Status` nebeneinander. Ohne Definition
wirkt das wie eine technische Doppelprüfung derselben Aussage, obwohl zwei
andere Modelle und Schwellen zugrunde liegen.

### Fixvertrag

Es gibt genau einen kanonischen, serverseitig berechneten
`goal_outcome_status` für Kundenentscheidungen. Er enthält:

- `status`;
- `status_rule_version`;
- `probability_metric`;
- `probability_bps`;
- `threshold_bps`;
- `analysis_id` und Context Hash.

Quantilpositionen können zusätzlich als beschreibende Werte erscheinen, aber
nicht als zweite unbenannte Ampel. Falls fachlich zwei Perspektiven gewünscht
sind, müssen sie unterschiedliche Namen, Erklärungen und gemeinsame
Snapshotbasis besitzen. React darf keine neue fachliche Entscheidung aus
Rohquantilen ableiten.

## `MC-QUANTILE-001` – 70 Prozent sind kein 90-Prozent-Konfidenzband

Für eine Verteilung enthält das Intervall vom 5. bis zum 75. Perzentil genau
70 Prozent der Probability-Masse. React bezeichnet es als:

```text
Band p5–p75 (90% des Pfade-Korridors)
```

Die SVG-Description nennt es zusätzlich „Konfidenz-Band“. Es ist jedoch ein
empirisches Prognose-/Pfadquantilband, kein Konfidenzintervall eines
geschätzten Parameters. `goalClassification.ts` nennt p75 „Best-Case“, obwohl
25 Prozent der Pfade darüber liegen.

Diese Beschriftungen unterschätzen beziehungsweise verwechseln Risiko:

- Wer 90 Prozent liest, erwartet typischerweise p5-p95.
- Wer Best Case liest, erwartet ein Extrem oder mindestens ein deutlich
  höheres Quantil als p75.
- Wer Confidence Band liest, kann Modell-/Schätzunsicherheit statt
  Ergebnisverteilung annehmen.

### Fixvertrag

Entweder wird tatsächlich p5-p95 berechnet und als zentrales 90-Prozent-
Prognoseband ausgewiesen, oder p5-p75 wird korrekt als 70-Prozent-
Pfadquantilband benannt. Quantile, enthaltene Masse und Semantik müssen aus
versionierten Backendmetadaten kommen. „Best Case“ und „Confidence“ sind ohne
methodisch passenden Vertrag zu entfernen. Accessibility-Text, Legend,
Tooltip, React, PDF und Export müssen identisch sein.

## `GOAL-PUBLICATION-001` – Kein gemeinsamer Vertrag über API, React und PDF

Der aktuelle TypeScript-Vertrag enthält für Goals im Wesentlichen ID, Label,
Typ, Target, Date, Hardness, Probability und Status. Für Monte Carlo enthält er
Quantilarrays, Path Count, Seed, Horizon und Initial Wealth. Es fehlen:

- Publication-/Analysis-/Allocation-/Run-/CMA-/Policy-/RA-Anker;
- Context- und Goal-Set-Hashes;
- Currency-/FX-/As-of-Angaben;
- Full versus Effective Target;
- Occurrence Probability und Probability-Semantik;
- Threshold, Score-Methode, Weight Source und Model Version;
- Sampling-/Importance-Weighting-Semantik;
- Fee-/Tax-/Cashflow-/Reserve-Modellbasis;
- discriminated Evidence State.

Zusätzlich divergieren die Kanäle:

- Advisory-JSON lässt Out-of-range-Probabilities durch;
- React formatiert CHF und zeigt den persistierten Status;
- React/Advisory-PDF berechnen zusätzlich einen p50/p75-Status;
- Advisory-PDF kann eine andere Currency rendern;
- Strategie-PDF liest das rohe TA-JSON direkt und klemmt Probability;
- Missing-Score erscheint teilweise als null, teilweise als nicht vorhanden.

### Zielvertrag

Ein einziges validiertes DTO muss alle Kanäle speisen, beispielsweise:

```text
GoalAnalyticsSection =
  | { state: "available", context: GoalAnalysisContext,
      goals: GoalOutcome[], score: GoalScoreSummary,
      paths: GoalPathEnvelope }
  | { state: "unavailable", reason_code: ... }
  | { state: "stale", reason_code: ..., expected_hash: ..., actual_hash: ... }
  | { state: "blocked", reason_code: ..., validation_errors: ... }
```

Renderer erhalten keine rohen persistierten JSON-Strings und keine Freiheit,
Probability, Currency, Status oder Missing-Zustände neu zu interpretieren.
Ein Final-/Kundenendpoint liefert bei stale/invalid Context stabil einen
fachlichen Konflikt, schreibt keinen Cache und startet keinen Renderer.

## Verbindliche Testmatrix

### Goal-Snapshot und Publication-Preflight

- Ziel Create nach TA: neues Ziel fehlt nicht still, Final blockiert stale.
- Ziel Update: altes Label/Probability wird nie mit neuem Target/Date gemischt.
- Ziel Delete: gelöschte Row erscheint nicht weiter als aktuelle Evidenz.
- Änderung von Rank, Weight, Hardness, Tau, Probability, Scope, Value Mode,
  Currency, Timing oder Target ändert den Goal-Set-Hash.
- Reines Live-Weight-Update ändert keinen historischen Score.
- Unverändertes Goal-Set reproduziert exakt dieselbe Analysis-ID und Werte.
- Cache-Hit wiederholt Currentness-/Hash-Prüfung vor Rückgabe.
- Race zwischen Goal-Update und Final-Read erzeugt entweder alten vollständig
  konsistenten Snapshot oder Konflikt, nie eine Mischzeile.

### Score- und Probability-Domain

- Missing, stale, invalid und echte Null bleiben getrennt.
- `-0.01`, `1.01`, `NaN`, `Infinity`, Strings, bool und null in modernen Rows
  blockieren kanalübergreifend.
- Tau-Domain und Probability-/Tau-/Status-Konsistenz werden geprüft.
- Strategy-PDF klemmt ungültige Werte nicht.
- Advisory-, Engine- und Mandate-Score besitzen getrennte Felder und Einheiten.
- Rank-Fallbackgewichte stimmen mit dem Solver überein.
- Hardness-Multiplikator und Weakest-Hard-Goal werden erhalten.
- Ziel ohne bewertbare Analyse zeigt `unavailable`, niemals `0%`.

### Bedingte Ziele

- Full Target, Effective Target und Occurrence Probability werden getrennt
  persistiert.
- 50-Prozent-Ziel 100 bei Wealth 60 liefert entsprechend der gewählten
  Semantik explizit conditional `0%`, unconditional `50%` oder korrekt
  benanntes Expected-Funding `100%`; niemals eine unbeschriftete 100-Prozent-
  „Zielerreichung“.
- 0-, 1- und Zwischenwahrscheinlichkeit sowie mehrere korrelierte bedingte
  Ziele werden geprüft.
- Reserve, Liability, Objective, Score, API und PDF verwenden dieselbe
  Method Version.
- Importance Sampling liefert korrekt gewichtete bedingte Schätzer.

### Monte-Carlo-Context

- Chart und Goal-Probability referenzieren dieselbe Analysis-/Run-ID.
- Neue globale Current-CMA verändert einen alten Final-Report nicht.
- CH-/DE- und tenantfremde CMA kann nicht in den Mandatsreport gelangen.
- TA-Suballokationen, Fees, Tax, Reserve, Rebalancing und Goal Liabilities
  entsprechen dem Run oder sind sichtbar ausgeschlossen.
- Seed, Path Count, Quantiles und Importance Weights sind reproduzierbar.
- As-of/Start Year stammt aus dem Snapshot, nicht aus `date.today()`.
- Live-Preview und Final-Snapshot sind typisiert und visuell klar getrennt.

### Cashflow, FX und Currency

- gemischte CHF/EUR/USD-Positionen werden über denselben FX-Snapshot wie der
  Run konvertiert;
- fehlender, nuller, future oder stale FX-Kurs blockiert;
- Cashflow-Frequency, Direction, Validity, Timing, Inflation und Currency
  entsprechen der kanonischen Projection;
- unbekannter Cashflow-Typ wird nicht positiv;
- fremdwährungsdominierte Mandate zeigen in API, React und PDFs identische
  Base Currency und gerundete Werte;
- Gebühren, Steuern und Rebalancing sind mathematisch und textlich identisch.

### Status, Quantile und Kanäle

- Probability 60 Prozent bei Tau 80 Prozent ergibt in allen Kanälen denselben
  Status und dieselbe Begründung;
- React berechnet keinen zweiten kundenorientierten Status aus p50/p75;
- p5-p75 wird exakt als 70-Prozent-Pfadquantilband bezeichnet;
- alternativ wird p5-p95 tatsächlich erzeugt und als 90-Prozent-Band geprüft;
- p75 wird nicht Best Case, Pfadband nicht Confidence Interval genannt;
- Accessibility, Legende, Tooltip, JSON, React und PDFs verwenden dieselben
  Labels;
- Out-of-range-, malformed-, stale- und missing Payloads ergeben denselben
  Evidence State in allen Kanälen.

### PostgreSQL, Concurrency und Artefakte

- Goal-Set-/Analysis-/Allocation-/Run-Referenzen besitzen Foreign Keys und
  passende Unique-/Check-Constraints;
- moderne Artefakte können ihre Pflichtanker nicht vollständig löschen und
  dadurch als Legacy erscheinen;
- Exactly-one-Current-TA und Goal-Mutation-Races werden auf PostgreSQL geprüft;
- Final-Publikation sperrt oder validiert Snapshot und Currentness innerhalb
  einer konsistenten Transaktion;
- Cache-Key enthält Analysis-/Context-/Schema-Version;
- kein PDF-/JSON-/Portal-Cachewrite nach fehlgeschlagenem Preflight;
- Auditlog hält Grund, erwarteten und tatsächlichen Hash sowie Principal fest.

## Empfohlene Umsetzungsreihenfolge

1. Probability- und Conditional-Goal-Semantik fachlich entscheiden und
   versionieren.
2. `GoalAnalysisContext`, `GoalAnalysisSnapshot` und discriminated Evidence
   States als gemeinsamen Backendvertrag definieren.
3. Goal-Set-Hash und atomare Publication-Invalidierung an jede Goal-Mutation
   binden.
4. Vollständige Goal-Metadaten, Probability-Komponenten, Thresholds, Scores
   und Modellmetadaten beim Optimizer-Lauf persistieren.
5. Advisory-Score auf die kanonischen Engine-Resultate migrieren; Missing und
   null trennen.
6. MC-Chart aus derselben Pfadpopulation beziehungsweise demselben vollständigen
   Run-Snapshot speisen.
7. Cashflow-/FX-/Currency-/Fee-/Tax-/Reserve-/Rebalancing-Modell mit der Engine
   vereinheitlichen.
8. Zweite React-/PDF-Statusableitung entfernen oder als klar getrennte,
   benannte Analyse mit gemeinsamer Basis modellieren.
9. Quantilband und alle sichtbaren/zugänglichen Texte korrigieren.
10. API, React, Advisory-PDF, Strategie-PDF und Kundenportal auf dasselbe DTO
    migrieren.
11. Negativ-, Race-, PostgreSQL-, CH/DE-, Cross-Currency-, Cache- und
    Cross-Channel-Tests schließen.

## Definition of Done

Diese Kontrollrunde ist erst geschlossen, wenn gleichzeitig gilt:

- jede Goal-Zeile, jeder Score und jedes Chart trägt dieselbe unveränderliche
  Analysis-/Allocation-/Run-/RA-/Policy-/CMA-/Goal-Set-Basis;
- Create, Update und Delete eines entscheidungsrelevanten Ziels invalidiert
  Final-/Kundenpublikation atomar;
- kein historisches Resultat wird mit heutigen Zielmetadaten oder Gewichten
  vermischt;
- Probability, Funding Ratio, Goal Score, Mandate Score und Weakest Hard Goal
  sind getrennt benannt und versioniert;
- Missing, Stale, Invalid und echte Null bleiben getrennt;
- Probability und Tau sind endlich, strikt in Domain und konsistent zum
  Status;
- Conditional-Goal-Probability beantwortet eine explizit benannte fachliche
  Frage;
- Full Target, Effective Target und Occurrence Probability bleiben sichtbar;
- Chart und Probability stammen aus derselben Pfadpopulation oder exakt
  demselben reproduzierbaren Snapshot;
- CMA, Seed, Path Count, Sampling, As-of, Horizon, Cashflows, FX, Fees, Tax,
  Reserve und Rebalancing sind belegt;
- es gibt genau eine kanonische kundenorientierte Statusregel;
- p5-p75 wird als 70-Prozent-Pfadquantilband oder p5-p95 als echtes
  90-Prozent-Pfadquantilband bezeichnet;
- Currency und FX sind in API, React und jedem PDF identisch;
- kein Renderer klemmt, defaultet oder repariert ungültige Evidenz selbst;
- Final-/Kundenpfade blockieren stale/invalid vor Cache und Renderer;
- PostgreSQL-/Race-/Cache-/Cross-channel-Negativtests laufen grün;
- bestehende Tests wurden nicht durch breite Golden-, Clamp- oder
  Null-Fallback-Updates beruhigt.

## Claude-/GPT-Startcheckliste

Vor jeder Änderung in dieser Fläche:

1. Diesen Audit und den unmittelbar vorherigen Advisory-Analytics-Audit
   vollständig lesen.
2. Keine lokale UI-Korrektur implementieren, bevor Probability-Semantik und
   gemeinsamer Snapshotvertrag feststehen.
3. `Goal.achievement_score = NULL` nicht als ausreichende Publication-
   Invalidierung behandeln.
4. Keine historische TA-Row mit aktuellen Goal-Feldern oder Gewichten joinen.
5. Existing `achievement_score`, `mandate_score` und Weakest-Hard-Goal-
   Semantik wiederverwenden oder bewusst versioniert migrieren.
6. Conditional-Goal-Pro-rata nicht weiter als volle Zielerreichung labeln.
7. Chart nicht aus globaler Current-CMA oder Live-Inputs neben alten
   Wahrscheinlichkeiten erzeugen.
8. Currency niemals aus UI-Kontext raten oder hart auf CHF setzen.
9. React und PDF dürfen Status, Probability oder Clamp nicht selbst neu
   definieren.
10. Tests zuerst rot für Mixed Snapshot, Live-Weight-Drift, negative/
    überhöhte/NaN-Probability, Conditional 50/100/60, Tau-vs-p50-Status,
    p5-p75-Label, globale CMA-Drift und Mixed Currency schreiben.
11. Finalpfade auf Konflikt plus „Cache/Renderer nicht aufgerufen“ prüfen.
12. Nach Umsetzung Audit, Stable Entry, Claude-Handoff, Deploy- und
    Provisioning-Blocker synchron aktualisieren.

## Unveränderte Baseline- und Audit-Evidenz

Ausgeführter fokussierter Backend-Gate:

```text
python -m pytest -q -p no:cacheprovider --basetemp <TEMP> \
  tests/test_advisory_report.py \
  tests/test_monte_carlo_paths.py \
  tests/test_goal_achievability_invalidation.py \
  tests/test_goals_conditional_probability_mc_path.py \
  tests/test_chance_constraint.py \
  tests/test_current_goal_analysis_contract.py \
  tests/pdf/test_goal_achievability_component.py \
  tests/pdf/test_anlagestrategie_goal_achievability.py \
  tests/pdf/test_goal_achievability_table.py
```

Ergebnis:

```text
136 passed in 69.86s
```

Ausgeführter Frontend-Gate:

```text
npm.cmd test -- --run \
  src/components/MonteCarloPathsChart.test.tsx \
  src/lib/goalClassification.test.ts \
  src/lib/sortGoals.test.ts \
  src/pages/sections.test.tsx
```

Ergebnis:

```text
4 test files passed
97 tests passed
Duration 20.27s
```

Die Vite-/esbuild-/oxc-Hinweise waren Deprecation-Warnungen, keine
Testfehler.

Diese grünen Gates widerlegen die Findings nicht:

- Goal-Invalidierungstests prüfen `Goal.achievement_score`, nicht die weiterhin
  gelesene TA-Row und den Advisory-Publication-State;
- Conditional-Goal-Tests verlangen explizit die Expected-Value-
  Targetskalierung, ohne das kundenorientierte Probability-Label zu prüfen;
- Goal-Classification-Tests verlangen explizit den zweiten p50/p75-Status;
- Charttests sichern Struktur und Rendering, nicht die falsche 90-Prozent-
  Aussage gegen die tatsächliche Quantilmasse;
- es gibt keinen Mixed-Goal-Snapshot- oder Live-Weight-Drift-Test;
- es gibt keinen negativen, überhöhten oder NaN-Probability-Cross-channel-
  Test;
- es gibt keinen Snapshot-CMA-/Global-CMA-Paritätstest für das Goal-Chart;
- es gibt keinen vollständigen Cashflow-/FX-/Currency-Paritätstest;
- es gibt keinen gemeinsamen Analysis-ID-/Context-Hash-Vertrag über API,
  React, Advisory-PDF und Strategie-PDF.

Der letzte vollständige Backend-Gate bleibt unverändert:

```text
6074 passed, 0 failed, 10 skipped, 1 xfailed, 269 warnings
```

Auch dieser grüne SQLite-Gate hebt die bestätigten Snapshot-, Score-, Domain-,
Probability-, MC-Context-, Currency-, Status-, Quantil- und
Publikationsblocker nicht auf.
