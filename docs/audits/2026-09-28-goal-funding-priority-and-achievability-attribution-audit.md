---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-goal-funding-priority-achievability-attribution-and-rank-roundtrip-followup-audit"
status_as_of: "2026-09-28"
audit_started_on: "2026-09-28"
audit_completed_on: "2026-09-28"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "6df808bd018216d3ce2cec2ed7a2d7eab8fed2cf"
prior_mixed_goal_audit_path: "docs/audits/2026-09-28-mixed-goal-sensitivity-objective-evidence-integrity-audit.md"
prior_core_audit_path: "docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md"
prior_goal_publication_audit_path: "docs/audits/2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md"
audit_mode: "read_only_static_goal_funding_priority_joint_path_attribution_rank_hardness_roundtrip_and_publication_review_plus_deterministic_python_node_and_focused_pytest_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "mixed spending and wealth goals, aggregate liability path, funding hierarchy, per-goal shortfall and chance probability attribution, conflict classification, rank and hardness roundtrip, main-goal selection, drag reorder, Classic UI/React/API/PDF parity"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 3
confirmed_prior_p1_extension_groups: 5
new_hardening_p2_count: 0
deterministic_reproduction_groups: 4
focused_existing_tests_passed: 269
focused_existing_tests_skipped: 0
focused_existing_tests_failed: 0
focused_existing_test_runs_confirmed: 1
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "freeze real-advice goal-achievability and conflict claims; define and version an owner-approved per-path goal-funding policy; replace aggregate-path pseudo-attribution with a reconciled per-goal funding ledger or publish only a correctly labelled joint-plan metric; separate rank from hardness in every editor and publication path; implement atomic persisted reordering and select the main goal exclusively from canonical rank; replay or quarantine ambiguous legacy evidence"
---

# Goal-Funding-, Prioritäts-, Achievability-Attributions- und Rang-Roundtrip-Audit

## Geltung, Abgrenzung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die siebenunddreißigste Read-only-
Kontrollrunde. Geprüft wurde der unveränderte Repository-Head
`6df808bd018216d3ce2cec2ed7a2d7eab8fed2cf`. Produktcode, Tests,
Migrationen und Runtime-Konfiguration wurden nicht verändert. Nach Abschluss
der Prüfung werden ausschließlich die fünf Pfade des Dokumentationsmanifests
angepasst.

Die Runde schließt eine in Runde 36 bewusst noch nicht behauptete Kernfrage:

1. Werden harte, primäre und opportunistische Spending-Ziele tatsächlich in
   ihrer dokumentierten Reihenfolge finanziert?
2. Ist die pro Ziel publizierte Wahrscheinlichkeit wirklich eine
   zielindividuelle Wahrscheinlichkeit oder nur derselbe gemeinsame
   Portfoliozustand nach allen Zahlungen?
3. Bleiben `rank` und `hardness` in API, Classic UI, React und Review getrennt
   und verlustfrei erhalten?
4. Ist das im Review als „Hauptziel“ gezeigte Ziel wirklich das kanonische
   Ziel mit Rang eins?

Aktueller Code und ausgeführte Reproduktionen haben Vorrang. Planning-
Dokumente dienen als Soll-Anker. Grüne Bestandstests beweisen vorhandene
Positivkontrollen, widerlegen aber keine nicht assertierten Mehrziel-
Gegenbeispiele.

Dieser Audit ersetzt keine bestehende Finding-ID:

- `GOAL-SCORE-001 / ZERO-WEIGHT` und
  `OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001` bleiben für Gewicht und
  Objective-Modus maßgeblich;
- `GOAL-CONDITIONAL-001` bleibt für Eintrittswahrscheinlichkeiten und
  Expected-Value-Skalierung maßgeblich;
- `GOAL-PUBLICATION-001`, `GOAL-SNAPSHOT-001` und `REP-001` bleiben die
  allgemeinen Publikations- und Evidence-Verträge;
- `PENSION-AHV-001` bleibt der bereits dokumentierte Vertrag für die falsche
  AHV-Vollfinanzierung;
- `GOAL-RETURN-HORIZON-001` bleibt der allgemeine Fail-closed-Vertrag für
  Ziele außerhalb des ausgewerteten Horizonts.

Drei neue IDs grenzen neue Fehler präzise ab:

- `GOAL-FUNDING-PRIORITY-001` betrifft die Ausführung jedes Spending-Ziels
  vor der Prüfung höher priorisierter Ziele;
- `GOAL-ACHIEVABILITY-ATTRIBUTION-001` betrifft die als individuell
  publizierte, tatsächlich aber aus einem gemeinsamen Aggregatepfad
  abgeleitete Wahrscheinlichkeit und Shortfall-Zuordnung;
- `GOAL-RANK-HARDNESS-ROUNDTRIP-001` betrifft die Vermischung von Rang und
  Härte in Classic UI, Reorder und Hauptzielauswahl.

## Kurzurteil

Die Runde bestätigt **drei neue release-blockierende P1**.

**`GOAL-FUNDING-PRIORITY-001`:** Jeder positive Spending-Goal-Pfad wird
unabhängig von Rang und Härte mit seinem materialisierten Betrag in den
aggregierten Liability-Pfad addiert; bedingte Goals werden davor
`probability_pct`-pro-rata skaliert. Die Scenario-Engine zieht diesen
Gesamtbetrag ohne Funding-Entscheidung ab, bevor sie harte und primäre Ziele
auswertet. Damit kann ein opportunistisches Wunschziel ein
hartes Ziel von 100 auf 0 Prozent drücken. Der ausgeführte Repro verwendet
CHF 100 Ausgangsvermögen, ein hartes Vermögensziel von CHF 90 in Jahr zwei und
eine opportunistische Ausgabe von CHF 20 in Jahr eins. Ohne Wunschziel ist das
harte Ziel erfüllt; mit Wunschziel meldet der Kern das Wunschziel mit 100
Prozent als erreicht, das harte Ziel mit 0 Prozent als nicht erreichbar und
erhebt dafür die volle Hard-Goal-Chance-Penalty von `640000`. Das Verhalten
bleibt auch bei `OPTIMIZER_GOAL_WEIGHTING=hardness` bestehen. Die dokumentierte
Aussage „opportunistische Ziele werden nur mitgenommen“ und das
Akzeptanzkriterium, dass das Hauptziel nicht vom Nebenziel dominiert wird,
werden damit verletzt.

**`GOAL-ACHIEVABILITY-ATTRIBUTION-001`:** Der Solver simuliert genau einen
Vermögenspfad nach der Summe aller Goal-Outflows und reicht denselben Pfad an
jede zielindividuelle Shortfall- und Probability-Auswertung weiter. Bei zwei
gleichzeitig fälligen Ausgaben von CHF 90 und CHF 20 auf CHF 100 erhalten beide
Ziele deshalb 0 Prozent und exakt denselben CHF-10-Fehlbetrag, obwohl Betrag,
Härte und Rang verschieden sind. Der Codekommentar räumt ausdrücklich ein,
dass keine kausale Zuordnung oder Reihenfolge existiert. Trotzdem werden daraus
pro Ziel `probability` und `status` persistiert und in Classic UI, Review und
Strategie-PDF als individuelle „Wahrscheinlichkeit“ dargestellt. Derselbe
Aggregatepfad speist separat den shortfall-abgeleiteten Goal-Driver in API und
Classic UI sowie die Konfliktlogik. Ein einziger gemeinsamer Liquiditätsbruch
kann dadurch mehrfach als Zielverfehlung und als Mehrzielkonflikt gezählt
werden.

**`GOAL-RANK-HARDNESS-ROUNDTRIP-001`:** Backend und React behandeln `rank` und
`hardness` als unabhängige Felder. Die Classic UI verwendet dagegen ein
einziges Feld `nz-prio`, schreibt daraus gleichzeitig Rang und Härte und lädt
beim Editieren zuerst aus der Härte statt aus dem gespeicherten Rang. Im
ausgeführten Repro wurden gültige Ziele mit Rang/Härte `1/Primär`, `2/Hart`,
`3/Opportunistisch` gespeichert. Die Classic-Edit-Logik mappt das zweite Ziel
auf Rang eins; der Backend-Konfliktresolver macht aus einem inhaltlichen No-op
danach Rang vier. Bei leerem `weight_bps` sinkt dadurch sein Defaultgewicht von
5.000 auf 1.250 bps. Drag-and-drop nummeriert nur DOM-Elemente um und persistiert
nichts. Zusätzlich wählt das Review „Hart vor Rang“ und zeigte im Node-Repro
das harte Ziel mit Rang zwei statt des primären Ziels mit Rang eins als
Hauptziel.

Es wurde kein neuer P0 bestätigt. Die Releasefreigabe bleibt wegen dieser drei
P1 und der bereits offenen P1 ausgeschlossen.

## Stabiles Findings-Register

| ID | Prio | Status | Kernaussage |
|---|---:|---|---|
| `GOAL-FUNDING-PRIORITY-001` | P1 | neu bestätigt | Alle Spending-Ziele werden unabhängig von Rang/Härte mit ihrem materialisierten Outflow und ohne Funding-Entscheidung abgezogen; ein opportunistischer Outflow kann dadurch ein hartes Ziel scheitern lassen und dessen Chance-Penalty auslösen. |
| `GOAL-ACHIEVABILITY-ATTRIBUTION-001` | P1 | neu bestätigt | Zielzeilen und Goal-Driver werden aus demselben Aggregatepfad abgeleitet; gemeinsame Insolvenz wird ohne Funding-Ledger als individuelle Zielwahrscheinlichkeit und shortfall-abgeleiteter individueller Objective-Beitrag publiziert. |
| `GOAL-RANK-HARDNESS-ROUNDTRIP-001` | P1 | neu bestätigt | Classic UI koppelt Rang und Härte, ein No-op-Edit kann den Rang ändern, Drag-Reorder ist kosmetisch und das Review wählt Härte vor Rang als Hauptziel. |
| `OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001` | P1 | offen, neue Evidence | Selbst der opt-in Hardness-Modus repariert die Funding-Reihenfolge nicht; er gewichtet nur den bereits gemeinsam entstandenen Fehlbetrag. |
| `GOAL-PUBLICATION-001` / `GOAL-SNAPSHOT-001` / `REP-001` | P1 | offen, neue Evidence | Aggregate Goal-Evidence wird ohne Attributionsmodus und Funding-Policy als individuelle Probability bis in UI und PDF getragen. |
| `GOAL-CONDITIONAL-001` | P1 | offen, neue Evidence | Expected-Value-skalierte bedingte Outflows werden ebenfalls in jedem Pfad bezahlt und können so höher priorisierte Ziele kontaminieren. |
| `PENSION-AHV-001` | P1 | offen, keine neue ID | `state_funded` fällt auf Null-Shortfall und Erfolg eins zurück; der Fehler ist im Retirement-Audit bereits vollständig dokumentiert. |
| `GOAL-RETURN-HORIZON-001` | P1 | offen, Boundary bestätigt | Ein leerer Spending-Pfad außerhalb eines direkt gelieferten Context-Horizonts ergibt Erfolg eins; der kanonische Produktionspfad erweitert derzeit den Horizont und verhindert das Gegenbeispiel. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
Goal A: hart, Rang 1, Vermögensziel CHF 90 in Jahr 2
Goal B: opportunistisch, Rang 5, Ausgabe CHF 20 in Jahr 1
Ausgangsvermögen CHF 100, Rendite 0

Goal B Liability [20, 0]
          |
          v
aggregate_liability_path = [20, 0]
          |
          v
ein gemeinsamer Wealth-Pfad = [100, 80, 80]
          |
          +--> Goal B am Due-Termin: Wealth 80 >= 0
          |      => 100 %, erreichbar
          |
          +--> Goal A in Jahr 2: Wealth 80 < Target 90
                 => 0 %, nicht erreichbar
                 => Hard-Goal-Chance-Penalty 1e6 * 0.8^2 = 640000

Es existiert weder:
  - eine Entscheidung, Goal B nicht auszuführen,
  - eine Funding-Reihenfolge,
  - ein funded_amount je Goal und Pfad,
  - noch eine Reserve für höher priorisierte Ziele.
```

Die Probability-Publikation verwendet anschließend dieselbe Aggregatebasis:

```text
aggregate Wealth-Pfad
      |
      +--> probability row Goal A
      +--> probability row Goal B
      +--> shortfall contribution Goal A
      +--> shortfall contribution Goal B
      |
      +--> TargetAllocation.goal_achievability_json
      +--> limiting_factor / Konfliktmessage
      +--> Classic Allocation-Tabelle
      +--> Review-Hauptziel und Goal-Liste
      +--> Strategie-PDF
      +--> Advisory-Zielkompatibilität
```

Die Rang-/Härte-Divergenz verläuft parallel:

```text
API / React: rank und hardness sind getrennt
             |
             v
Classic openGoalEditor:
  storedPriority = priorityMap[hardness] || rank
             |
             v
ein Select schreibt beim Save gleichzeitig:
  rank = selected value
  hardness = hardnessMap[selected value]
             |
             +--> Backend verschiebt Rangkonflikt auf max(rank)+1
             +--> Default weight_bps ändert sich
             +--> DOM-Drag persistiert nicht
             +--> Review sortiert Hart vor Rang
```

## Positivkontrollen, die erhalten bleiben müssen

1. Spending-Outflows werden im Wealth-Pfad genau einmal abgezogen; die
   Shortfall-Funktion fordert den Betrag nicht noch einmal als Target.
2. `outflow_stream` prüft seine eigenen positiven Due-Indizes und ignoriert
   negative Wealth-Zustände außerhalb seines Zahlungsfensters.
3. Cashflow- und Goal-Liability-Serien bleiben getrennte Subtraktoren; dieser
   Audit behauptet keine strukturelle Doppelzählung zwischen beiden Quellen.
4. Der kanonische Produktionspfad erweitert den Simulationshorizont derzeit
   auf den maximalen Goal-/Datums-/Life-Course-Horizont.
5. Der Backend-Validator akzeptiert Rang und Härte bewusst als getrennte
   Felder und verbietet unbekannte Härtewerte.
6. React `GoalWizard` besitzt bereits getrennte Eingaben für Rang und Härte.
7. Der Backend-Rangresolver verhindert doppelte aktive Ränge und bewahrt die
   Härte; er darf bei einer Reparatur nicht durch stille Duplikate ersetzt
   werden.
8. Importance-Sampling-Gewichte werden in Chance Probability und Penalty
   angewandt; eine neue Funding-Auswertung muss dieselben Gewichte verwenden.
9. Goal-Änderungen invalidieren deterministische Achievement-Scores. Künftig
   muss dieselbe Mutation zusätzlich jede abhängige stochastische Evidence
   eindeutig invalidieren.
10. Unknown-/Unsupported-Zustände sollen fail-closed werden; `state_funded`,
    `maximize`, echte Nullwahrscheinlichkeit und außerhalb des Horizonts dürfen
    nicht über einen gemeinsamen stillen Nullpfad-Fallback normalisiert werden.

## Codeanker des auditierten Stands

### Liability-Aufbau und gemeinsamer Wealth-Pfad

- `5eyes-backend/services/optimizer/goal_liabilities.py:43-66` definiert keine
  Funding-Entscheidung, keinen Rang und keinen funded/unfunded-Zustand in
  `GoalLiability`.
- `goal_liabilities.py:388-425` materialisiert eine einmalige Ausgabe
  unabhängig von Rang und Härte als positiven Outflow.
- `goal_liabilities.py:428-485` materialisiert wiederkehrende und
  Pensionsausgaben analog als vollständigen Outflow-Pfad.
- `goal_liabilities.py:601-614` addiert sämtliche Goal-Pfade kommutativ zu
  genau einer Serie. Rang, Härte und Goal-ID wirken auf die Summe nicht.
- `5eyes-backend/services/optimizer/solver.py:270-283` simuliert jeden
  Kandidaten mit `context.aggregated_liability_path`.
- `solver.py:475-523` baut zuerst alle Liabilities und aggregiert sie vor jeder
  Zielauswertung.
- `5eyes-backend/services/optimizer/scenario_engine.py:573-576` zieht die Summe
  der materialisierten Liability-Pfade nach Wachstum und Cashflow vom Wealth
  ab, auch bis in negatives Wealth.

### Shortfall, Probability, Penalty und Attribution

- `5eyes-backend/services/optimizer/objective.py:154-175` selektiert zwar die
  eigenen Due-Indizes eines Ziels, dokumentiert aber ausdrücklich, dass der
  gelieferte Wealth-Pfad über alle Goals aggregiert ist und keine kausale
  Zuordnung oder Reihenfolge erfunden wird.
- `objective.py:246-278` berechnet den Spending-Shortfall als negatives
  Minimum dieses gemeinsamen Wealth-Pfads an den Due-Indizes des jeweiligen
  Ziels.
- `objective.py:283-332` berechnet die zielindividuell benannte Probability
  aus demselben gemeinsamen Pfad.
- `objective.py:335-406` erzeugt daraus pro Goal `probability`, `tau`, `status`
  und für harte/primäre Ziele die Chance-Penalty. Opportunistische Ziele zahlen
  keine direkte Penalty, können die Penalty eines harten Ziels aber indirekt
  auslösen.
- `objective.py:521-591` nennt die daraus gebildete Größe
  `GoalShortfallContribution` und beschreibt sie als Beitrag unter dem
  Aggregatepfad, nicht als marginales Gegenfaktum.
- `5eyes-backend/tests/test_chance_constraint.py:106-114` beweist nur, dass ein
  opportunistisches Ziel auf einem extern gelieferten Wealth-Pfad keine
  direkte Penalty bekommt. Der Test simuliert keinen opportunistischen
  Spending-Outflow gemeinsam mit einem harten Ziel.
- `test_optimizer_objective_constraints.py:115-171` schützt Due-Indizes und
  No-double-count, enthält aber keine Funding-Priorität zwischen Goals.

### Downstream-Publikation und Konfliktklassifikation

- `5eyes-backend/services/portfolio_engine.py:3636-3645` reicht die
  Goal-Zeilen direkt an `classify_limiting_factor` weiter.
- `5eyes-backend/services/risk_matrix.py:101-123` erklärt zwei nicht
  erreichbare harte/primäre Zeilen zum `zielkonflikt`, ohne gemeinsame
  Failure-Event-ID oder Attributionsbasis.
- `5eyes-backend/services/allocation_messages.py:262-311` erzeugt aus denselben
  Zeilen kunden- und beraterseitige Konflikttexte.
- `5eyes-backend/services/advisory_report.py:1612-1663` erklärt die
  Zielkompatibilität anhand der gespeicherten Zeilen rot oder gelb.
- `5eyes-electron/frontend/5eyes_v2.html:7481-7500` rendert jede Zeile als
  Ziel, Härte, Prozent und Status.
- `5eyes_v2.html:24319-24336` rendert dieselben Werte im Review erneut als
  individuelle Goal-Liste.
- `5eyes-backend/services/pdf/components/goal_achievability.py:214-269`
  bezeichnet die Spalte ohne Einschränkung als „Wahrscheinlichkeit“ und zeigt
  pro Goal eine Ampel.

### Rang, Härte, Reorder und Hauptziel

- `5eyes-backend/services/goal_semantics.py:120-154` validiert `rank` und
  `hardness` unabhängig.
- `5eyes-backend/routers/wealth.py:380-427` erklärt Rang ausdrücklich als von
  Härte getrennte Sortiergröße und verschiebt Konflikte auf `max(rank)+1`.
- `5eyes-backend/tests/test_goal_rank_auto_resolution.py:122-175` bestätigt,
  dass mehrere harte Ziele unterschiedliche Ränge bei unveränderter Härte
  besitzen dürfen.
- `5eyes-electron/frontend/reporting/src/sections/goals/GoalWizard.tsx:288-314`
  führt Rang und Härte in getrennten Controls.
- `5eyes-electron/frontend/5eyes_v2.html:26570-26583` lädt die Classic-Auswahl
  dagegen aus `hardness` vor `rank`.
- `5eyes_v2.html:26721-26806` schreibt aus derselben Auswahl gleichzeitig
  `rank` und `hardness`.
- `5eyes_v2.html:6392-6405` verschiebt und nummeriert nur DOM-Knoten; kein
  Request, keine `currentGoals`-Mutation und kein Rollback persistieren die
  neue Reihenfolge.
- `5eyes_v2.html:24286-24299` sortiert für das Review harte Ziele vor allen
  anderen und erst danach nach Rang.
- `5eyes-backend/tests/test_frontend_review_cockpit.py:11-56` prüft nur DOM-
  Anker, Funktionsnamen und Schwellenstrings, nicht die tatsächliche
  Hauptzielauswahl.

## Deterministische Reproduktionen

### Repro 1 – Opportunistisches Ziel verdrängt hartes Ziel

Produktionsfunktionen:

- `goals_to_liabilities`
- `aggregate_liability_path`
- `simulate_wealth_paths`
- `goal_probability_per_path`
- `chance_constraint_penalty`
- `shortfall_contributions`

Input:

```text
initial wealth                  CHF 100
return factors                  1.0 in both years and all five buckets
cashflow                        0

Goal A
  type                          Vermoegensziel
  hardness / rank               Hart / 1
  target                        CHF 90 in year 2

Goal B
  type                          Einmalige_Ausgabe
  hardness / rank               Opportunistisch / 5
  amount                        CHF 20 in year 1
```

Output:

```text
without_optional wealth         [100, 100, 100]
with_optional wealth            [100, 80, 80]

hard probability without B      1
hard probability with B         0
optional probability with B     1

chance penalty with B           640000
hard status                     nicht_erreichbar
optional status                 erreichbar
```

Bei `OPTIMIZER_GOAL_WEIGHTING=hardness` bleibt die Chance-Penalty exakt
`640000`. Die Gewichtung verändert nur den Shortfall-Beitrag, nicht die
vorherige Ausführung des opportunistischen Outflows.

### Repro 2 – Zwei gleichzeitige Goals erhalten denselben Aggregate-Fehlbetrag

Input:

```text
initial wealth                  CHF 100
hard one-off                    CHF 90 in year 1
opportunistic one-off           CHF 20 in year 1
return factor                   1.0
```

Output:

```text
hard-only wealth after due      CHF 10
both wealth after due           CHF -10

hard P with both                0
opportunistic P with both       0
hard raw shortfall²             (CHF 10)^2
opportunistic raw shortfall²    (CHF 10)^2
```

Die beiden Beträge CHF 90 und CHF 20 erzeugen also dieselbe
`mean_shortfall_squared`. `weight_bps` skaliert diesen gemeinsam entstandenen
Defizitwert immer; Hardness skaliert ihn nur im opt-in Modus
`OPTIMIZER_GOAL_WEIGHTING=hardness`. Das ist keine kausale Goal-Zuordnung.

### Repro 3 – Review zeigt Rang zwei als Hauptziel

Die echte Funktion `mainGoalAchievability()` wurde aus dem HTML geladen und
mit folgendem Zustand ausgeführt:

```text
rank 1 / primary / probability 90 %
rank 2 / hard    / probability 20 %
```

Output:

```json
{
  "goal_id": "secondary",
  "label": "Hard rank 2",
  "probability": 0.2,
  "hardness": "hart"
}
```

Das Review-Hauptziel ist damit nicht das kanonische Rang-eins-Ziel.

### Repro 4 – Inhaltlicher No-op verschiebt Rang zwei auf Rang vier

Persistierter gültiger Zustand:

```text
g1  rank=1  hardness=Primär
g2  rank=2  hardness=Hart
g3  rank=3  hardness=Opportunistisch
```

Die Classic-Edit-Logik lädt für `g2` wegen `hardness=Hart` den Selectwert eins.
Ohne fachliche Änderung sendet Save daher `rank=1`. Der echte Backend-
Resolver liefert:

```text
stored_before                  [(g1,1,Primär),(g2,2,Hart),(g3,3,Opportunistisch)]
classic_open_maps_g2_to_rank   1
backend_noop_edit_resolves_to  4
```

Da `_weight_bps()` bei leerem explizitem Gewicht aus Rang ableitet, ändert
dieser Roundtrip außerdem das Optimizergewicht von Rang zwei (`5000`) auf Rang
vier (`1250`).

## Finding `GOAL-FUNDING-PRIORITY-001`

### Beobachtung

Die Engine besitzt eine Zielgewichtung, aber keine Ziel-Funding-Entscheidung.
Jede Ausgabe ist vor der Objective-Auswertung mit ihrem materialisierten, bei
bedingten Goals `probability_pct`-pro-rata skalierten Betrag vom Wealth
abgezogen. `hardness` und `weight_bps` können nur den danach sichtbaren
Fehlbetrag skalieren. Sie können eine opportunistische Ausgabe weder auslassen
noch kürzen noch hinter einen harten Bedarf stellen.

Damit ist die Behauptung „opportunistische Ziele werden nicht erzwungen“ nur
formal für den direkten Penalty-Term wahr. Ein opportunistischer Outflow kann
den Erfolg eines harten Ziels reduzieren und dadurch dessen Penalty auslösen.
Die Chance Constraint erzwingt dann indirekt genügend Vermögen für beide
Ziele.

### Verletzte Verträge

1. `docs/planning/2026-05-23-stochastic-goal-engine-spec.md:216-241`
   definiert Haupt-/Nebenziel sowie Hardness-/Prioritätshierarchie.
2. Derselbe Vertrag verlangt in `:288-306` eine Chance Constraint **pro**
   hartem oder primärem Ziel.
3. Das Akzeptanzkriterium `:607-609` verlangt, dass ein Nebenziel das
   Hauptziel nicht dominiert und die Hauptzielwahrscheinlichkeit mindestens
   der Nebenzielwahrscheinlichkeit entspricht.
4. `docs/engine-spec.md:421` sagt, opportunistische Goals würden nicht
   erzwungen.
5. `docs/methodology/5eyes-engine-whitepaper.md:85-91` sagt, sie würden im
   Hardness-Modus nur „mitgenommen“.

Der Repro liefert dagegen `P_hard=0 < P_opportunistisch=1`.

### Wirkung

1. Ein Berater kann durch Hinzufügen eines Wunschziels ein zuvor erreichbares
   hartes Ziel unbemerkt auf rot setzen.
2. Die Allokation kann wegen des indirekten Hard-Goal-Penalty mehr Risiko oder
   eine andere Asset-Struktur für einen eigentlich optionalen Outflow suchen.
3. Ein Ziel- oder Datenkonflikt kann dem harten Ziel zugeschrieben werden,
   obwohl nur das niedrig priorisierte Ziel auszulassen wäre.
4. Rang, Härte und Goal-Gewicht steuern nicht die Ausführung, sondern nur die
   Bewertung eines bereits gemeinsam ausgeführten Plans.
5. Sensitivity eines niedrigen Ziels kann die Erreichbarkeit eines höheren
   Ziels ändern, ohne dass der Vertrag diese Abhängigkeit erklärt.

### Verbindlicher Reparaturvertrag

Vor Implementierung ist eine Owner-ADR nötig. Sie muss eine der folgenden
Semantiken eindeutig wählen:

1. **Priorisiertes Goal Funding:** Spending-Goals sind finanzierbare Wünsche.
   Pro Pfad und Fälligkeit verteilt ein versionierter Funding-Resolver das
   verfügbare Vermögen nach kanonischem Rang/Hardness. Nicht finanzierte
   niedrigere Ziele werden nicht so ausgeführt, dass sie höhere Ziele
   nachträglich zerstören.
2. **Unbedingter gemeinsamer Plan:** Jeder Outflow ist zwingend. Dann darf
   `opportunistisch` bei Spending-Goals nicht „optional“ oder „nur
   mitgenommen“ heißen; die Engine veröffentlicht eine gemeinsame
   Plan-Solvency statt einer Funding-Hierarchie.

Für das dokumentierte Produktziel ist Variante 1 konsistent. Sie benötigt:

- einen vor Goal-Zahlungen liegenden Cash-/Wealth-Zustand je Pfad und Jahr;
- einen deterministischen `GoalFundingPolicy` mit Version, Prioritätsregel,
  Gleichrangregel, Teilfinanzierungsregel und Behandlung zukünftiger harter
  Verpflichtungen;
- je Goal/Pfad/Jahr mindestens `amount_due`, `amount_funded`,
  `amount_unfunded`, `funded_fraction` und `success`;
- eine Reconciliation
  `wealth_after_growth_and_tax + cashflow - sum(funded) = wealth_after`;
- Chance Constraint und Shortfall auf den zielindividuellen Fundingzustand;
- Bindung der Policy an Context, Model-Basis, Run, Allocation-/Sensitivity-
  Hash, Persistenz, PDF und Signatur;
- fail-closed Verhalten, wenn keine Policyversion vorliegt.

### Pflicht-Negativ- und Invariantentests

1. Das CHF-100/90/20-Gegenbeispiel muss im priorisierten Vertrag das harte
   Ziel erfüllen und das Wunschziel als ungefundet/teilfinanziert markieren.
2. Hinzufügen eines niedriger priorisierten Goals darf `P` eines höheren
   Goals nicht senken, sofern die Policy keinen ausdrücklich dokumentierten
   Zukunftsreserveeffekt vorsieht.
3. Reihenfolge der Inputliste darf das Resultat nicht ändern.
4. Gleichrangige gleichzeitige Goals benötigen eine explizit getestete
   proportionale oder stabile Tie-break-Regel.
5. Teilfinanzierung, null verfügbares Vermögen, negativer Cashflow und spätere
   Erholung müssen reconciliert bleiben.
6. Ein niedriges Ziel darf nie über den Penalty eines höheren Ziels indirekt
   zur Pflicht werden.
7. IS und Standard-MC müssen mit identischem Funding-Ledger dieselben
   gewichteten Erfolgsindikatoren auswerten.
8. Sensitivity muss dieselbe Funding-Policy und denselben Szenariopfad binden.

## Finding `GOAL-ACHIEVABILITY-ATTRIBUTION-001`

### Beobachtung

Die Engine besitzt pro Ziel eine Zeile, aber keinen pro Ziel separaten
Vermögens- oder Fundingpfad. Der aktuelle Wert beantwortet je nach Zieltyp
sinngemäß:

> War der gemeinsame Portfoliozustand nach allen bis zu diesem Due-Termin
> ausgeführten Goal-Outflows nicht negativ beziehungsweise über der
> Wealth-Schwelle?

Das ist eine gemeinsame Planbedingung. Sie ist weder eine marginale
Wahrscheinlichkeit „mit versus ohne dieses Ziel“ noch eine priorisierte
Fundingwahrscheinlichkeit. Bei simultanen Goals kann derselbe negative
Portfoliozustand beliebig oft als individueller Fehlbetrag wiederholt werden.

### Wirkung

1. Zwei Ziele können identische Probability und Shortfall erhalten, obwohl nur
   eines bei priorisierter Finanzierung scheitern würde.
2. `GoalShortfallContribution` wirkt kausal, ist aber nur der gewichtete Blick
   jedes Goals auf denselben gemeinsamen Defizitzustand.
3. Zwei Zeilen desselben Failure-Events können `zielkonflikt` auslösen.
4. Classic UI, Review und PDF nennen den Wert ohne Scopehinweis
   „Wahrscheinlichkeit“ und suggerieren individuelle Evidenz.
5. Advisory-Zielkompatibilität kann ein hartes Ziel rot melden, obwohl der
   niedrig priorisierte Outflow die eigentliche Ursache ist.
6. Eine Änderung eines Goals verändert die Probability anderer Goals; im
   gespeicherten Vertrag fehlt die Event-/Abhängigkeitsstruktur.

### Verbindlicher Reparaturvertrag

1. Goal-Resultate erhalten einen diskriminierten `evaluation_scope`, mindestens
   `priority_funded`, `joint_plan` oder `marginal_counterfactual`.
2. `probability` ohne Scope ist unzulässig. Für Altwerte gilt
   `legacy_aggregate_unknown` und Publikationsquarantäne.
3. Bei `priority_funded` kommt Erfolg aus dem Funding-Ledger des jeweiligen
   Goals.
4. Bei `joint_plan` existiert genau eine Plan-Solvency-Zeile; derselbe Wert
   darf nicht als mehrere individuelle Goalwahrscheinlichkeiten erscheinen.
5. Marginale Driver benötigen ein echtes gepaartes Gegenfaktum oder werden
   klar als `weighted_loss_component_under_joint_path` benannt.
6. Conflict Classification gruppiert gemeinsame Failure-Events und zählt sie
   nicht allein anhand der Anzahl roter Zeilen.
7. Persistenz bindet Goal-Snapshot, Funding-Policy, Szenario-/IS-Basis,
   Evaluation-Scope und Resultathash.
8. API, Classic UI, React, beide PDF-Pfade, Signatur und Handoff verwenden
   dieselbe typisierte Semantik und dasselbe Label.

### Pflicht-Negativ- und Invariantentests

1. Zwei simultane Ausgaben unterschiedlicher Größe und Priorität dürfen nicht
   ohne Scope denselben individuellen Defizitwert erhalten.
2. Ein gemeinsames Failure-Event darf nicht doppelt als unabhängiger Konflikt
   gezählt werden.
3. Summe der publizierten Goal-Beiträge muss zur definierten Objective passen;
   marginale Beiträge benötigen zusätzlich eine klar dokumentierte
   Nichtadditivität oder ein geeignetes Attributionsverfahren.
4. Goal-Reihenfolge und Labels dürfen Mathematik und Failure-Event-ID nicht
   verändern.
5. UI und PDF müssen `joint plan`, `priority funded` und `not evaluable`
   sichtbar unterscheiden.
6. Legacyzeilen ohne Scope dürfen keine grüne/rote individuelle
   Probability-Ampel erzeugen.

## Finding `GOAL-RANK-HARDNESS-ROUNDTRIP-001`

### Beobachtung

Es existieren drei widersprüchliche Verträge:

1. Backend und React: Rang und Härte sind unabhängig.
2. Classic Editor: Rang eins bis drei wird als Synonym für Hart/Primär/
   Opportunistisch verwendet.
3. Classic Review: Härte bestimmt zuerst das Hauptziel, Rang erst innerhalb
   derselben Härteklasse.

Der Backend-Kommentar nennt Rang nur eine UI-Sortierhilfe. Die Goal-Engine-
Spezifikation nennt Rang dagegen Priorität, und `_weight_bps()` leitet daraus
bei fehlendem explizitem Gewicht ein rechenwirksames Optimizergewicht ab. Der
Konflikt ist daher nicht kosmetisch.

### Wirkung

1. Ein inhaltlicher No-op-Edit kann Rang und Defaultgewicht ändern.
2. Rang vier oder fünf kann im Classic Editor nicht verlustfrei geladen und
   gespeichert werden.
3. Ein harter Rang-zwei- bis Rang-fünf-Datensatz wird beim Öffnen als Rang eins
   dargestellt.
4. Drag-and-drop erzeugt visuelles Vertrauen, ändert aber keine persistierte
   Priorität.
5. Das Review kann ein Nebenziel als Hauptziel ausweisen und dessen
   Wahrscheinlichkeit prominent publizieren.
6. React, Classic UI, API und PDF können dasselbe Ziel unterschiedlich als
   Haupt-/Nebenziel interpretieren.
7. Durch Rangdrift ändern sich Goal-Hash, Solvergewicht und künftige
   Sensitivity, obwohl der Berater nur ein anderes Feld bearbeitet hat.

### Verbindlicher Reparaturvertrag

1. Eine Owner-ADR definiert `rank` eindeutig als kanonische Priorität oder als
   reine Sortierung. Für das bestehende Hauptziel-/Weighting-Modell muss es
   kanonische Priorität sein.
2. Classic UI erhält getrennte Controls für `rank` und `hardness`, analog zum
   React Wizard.
3. Edit-Initialisierung liest jedes Feld ausschließlich aus seinem eigenen
   persistierten Wert; ein No-op erzeugt bytegleich dieselben rechenwirksamen
   Felder.
4. Reorder erfolgt über eine atomare Backendoperation für die vollständige
   Goal-Permutation, validiert jede ID genau einmal und schreibt lückenlose
   eindeutige Ränge.
5. Bei Requestfehler rollt die UI sichtbar auf die persistierte Reihenfolge
   zurück.
6. Hauptziel ist ausschließlich das aktive Goal mit kanonischem Rang eins.
   Härte wird separat angezeigt und darf die Identität nicht überschreiben.
7. `GoalLiability` beziehungsweise der Objective-Context bindet den verwendeten
   Rang explizit; keine verdeckte Ableitung nur über ein optionales
   `weight_bps`.
8. Rank-/Hardness-/Weight-Vertrag wird in Goal-Snapshot, Model-Basis, Hash,
   Run, UI und PDF versioniert.

### Pflicht-Negativ- und Invariantentests

1. Roundtrip-Matrix über Ränge 1..5 × alle zulässigen Härtegrade.
2. No-op-Edit bewahrt `rank`, `hardness`, `weight_bps`, Goal-Hash und
   Allocation-Dirty-Semantik exakt.
3. Das konkrete `1/Primär`, `2/Hart`, `3/Opportunistisch`-Beispiel darf Rang
   zwei nicht auf vier verschieben.
4. Drag-Reorder persistiert, reloadet identisch und ist nach Fehler rollback-
   sicher.
5. Classic und React erzeugen für denselben Input exakt denselben Request.
6. Review-Hauptziel ist bei `rank1=Primär`, `rank2=Hart` weiterhin Rang eins.
7. Duplicate-, fehlende-, negative- und sehr große Ränge werden fail-closed
   beziehungsweise atomar normalisiert.
8. Concurrent Reorders verwenden Version/CAS und dürfen keine doppelten oder
   verlorenen Ränge erzeugen.

## Bewusst nicht als neue Findings gezählte Randfälle

### Spending-Ziel außerhalb eines direkt gelieferten Context-Horizonts

Der Low-Level-Vertrag ist fail-open: Ein positiver Outflow außerhalb des
gelieferten Horizons erzeugt einen Nullpfad; ohne positive Due-Indizes liefert
die Objective null und die Probability eins. Der kanonische Produktpfad baut
seinen Horizont derzeit jedoch als Maximum aus Goal-Horizont, Startdatum,
Zieldatum und Life-Course-Horizont. Sensitivity erweitert ebenfalls auf den
größten betroffenen Horizont. Deshalb wird kein neuer produktiver P1 gezählt.

Claude soll die Servicegrenze trotzdem zusammen mit
`GOAL-RETURN-HORIZON-001` härten: Ein positiver Targetbetrag darf nie allein
wegen eines zu kurzen direkt gelieferten Context-Horizonts Erfolg eins
erhalten. Zulässig sind nur explizite Horizonterweiterung oder
`not_evaluable`/Fehler.

### `state_funded`

`state_funded` fällt in `shortfall_squared_per_path()` auf null und in
`goal_probability_per_path()` auf eins zurück. Das ist produktiv und kritisch,
aber bereits exakt als `PENSION-AHV-001` dokumentiert. Keine neue ID und keine
doppelte Zählung.

### Cashflow-/Liability-Doppelzählung

Cashflow und Goal-Liability werden als unabhängige Serien subtrahiert. Dieser
Audit hat keinen neuen generischen Doppelzählungsfehler zwischen beiden
Quellen bestätigt. Die neue Finding betrifft die Aggregation **zwischen
Goals** und ihre Prioritäts-/Attributionssemantik.

## Testverifikation

Ausgeführt wurde:

```text
python -m pytest -q --basetemp ..\.pytest_tmp_round37 \
  tests/test_optimizer_goal_liabilities.py \
  tests/test_optimizer_objective_constraints.py \
  tests/test_optimizer_objective_dimensionless.py \
  tests/test_chance_constraint.py \
  tests/test_optimizer_solver.py \
  tests/test_optimizer_production_contract.py \
  tests/test_goal_rank_auto_resolution.py \
  tests/test_frontend_review_cockpit.py \
  tests/test_goals_editor_wiring_contract.py \
  tests/test_goal_domain_fail_closed_contracts.py
```

Ergebnis:

```text
269 passed in 100.19s
```

Die grüne Suite enthält nicht:

- hartes Ziel plus vorherige opportunistische Ausgabe;
- Main-Goal-Probability kleiner als Secondary-Goal-Probability;
- zwei simultane Spending-Goals mit gemeinsamer Defizitattribution;
- tatsächliche Ausführung von `mainGoalAchievability()` mit Rang-/Härte-
  Konflikt;
- Classic-No-op-Roundtrip über unabhängige Rang-/Härte-Kombinationen;
- persistiertes Drag-Reorder.

Die vier ausgeführten Gegenbeispiele sind daher keine Regression gegen einen
bestehenden roten Vertrag, sondern fehlende Verträge.

## Empfohlene Implementierungsreihenfolge für Claude

1. **Releasegate zuerst:** Goal-Achievability, Goal-Konflikte und prominente
   Hauptzielwahrscheinlichkeit für reale Mandate fail-closed sperren, solange
   `evaluation_scope` oder `funding_policy_version` fehlt.
2. **Rote Tests materialisieren:** Die vier Repros sowie alle Pflicht-
   Invarianten vor Produktcodeänderungen als Tests festschreiben.
3. **Owner-ADR:** Funding-Semantik, Gleichrangregel, Teilfinanzierung,
   Zukunftsreserve und Bedeutung von Rang versus Härte freigeben lassen.
4. **Kanonisches Domainmodell:** `GoalFundingPolicy`, per-path Funding-Ledger,
   Goal-Rank/Hardness/Weight und typisierten Resultatscope einführen.
5. **Solverkern:** Scenario-Simulation von Goal-Funding trennen; Objective,
   Chance Constraint und Explainability auf das Ledger umstellen.
6. **Konfliktlogik:** gemeinsame Failure-Events deduplizieren und nur echte
   Zielkonflikte melden.
7. **UI-Roundtrip:** Classic und React auf getrennte Felder, atomaren Reorder
   und Rang-eins-Hauptziel umstellen.
8. **Evidence:** Policy, Scope, Ledger-Summary, Goal-Snapshot, Szenario-/IS-
   Basis und Hash an Run, Allocation, Sensitivity, PDF, Signatur und Handoff
   binden.
9. **Legacy:** alte Aggregatezeilen replayen oder als
   `legacy_aggregate_unknown` ohne individuelle Ampel quarantänisieren.
10. **Abnahme:** fokussierte, volle Backend-, React-, Electron-, PDF- und
    echte Browser-E2E-Suite sowie Replay auf der Zielumgebung.

## Nicht ausreichende Scheinfixes

- nur den Hardness-Faktor von 1 auf 10 erhöhen;
- nur opportunistische Zeilen aus der Chance-Penalty entfernen;
- nur UI-Labels auf „gemeinsam“ ändern, während Konfliktlogik und Driver weiter
  individuell rechnen;
- für jedes Goal denselben Aggregatepfad kopieren und anders benennen;
- `mainGoalAchievability()` nur nach Rang sortieren, ohne den Classic-
  Roundtrip und Drag-Reorder zu reparieren;
- Rangkonflikte weiter still auf `max+1` verschieben, ohne atomaren
  Reordervertrag;
- nur React reparieren, während Classic UI, PDF und gespeicherte Evidence
  abweichen;
- bestehende grüne Einzelzieltests als Beweis für Mehrziel-Priorität werten;
- AHV- oder Outside-Horizon-Fälle unter neuen IDs erneut zählen.

## Definition of Done

- [ ] Owner-ADR für Funding, Rang, Härte, Teilfinanzierung und Gleichrang liegt vor.
- [ ] `GoalFundingPolicy` ist versioniert und in Context/Hash/Run gebunden.
- [ ] Jedes Spending-Goal besitzt pro Pfad eine reconciliable Funding-Evidence.
- [ ] Ein niedrigeres Wunschziel kann ein höheres Ziel nicht undokumentiert verdrängen.
- [ ] Probability besitzt einen typisierten Evaluation-Scope.
- [ ] Joint-Plan-Solvency wird nicht als mehrere individuelle Goal-P publiziert.
- [ ] Goal-Driver sind marginal, ledgerbasiert oder unmissverständlich anders benannt.
- [ ] Conflict Classification dedupliziert gemeinsame Failure-Events.
- [ ] Rang und Härte roundtrippen getrennt in API, Classic und React.
- [ ] No-op-Edit ändert keine rechenwirksamen Goal-Felder oder Hashes.
- [ ] Drag-Reorder ist atomar persistiert und rollback-sicher.
- [ ] Hauptziel ist in jedem Kanal exakt das aktive Rang-eins-Ziel.
- [ ] UI, PDF, Signatur und Handoff verwenden denselben Scope und Snapshot.
- [ ] Legacy-Aggregatevidence ist replayed oder sichtbar quarantänisiert.
- [ ] Alle Negativ-, Invarianten-, Cross-Channel- und E2E-Tests sind grün.
- [ ] Releasegate wird erst nach dokumentierter Zielumgebungsabnahme geöffnet.

## Abschlussurteil

Claude hat Einzelziel-Due-Indizes, No-double-count, Chance-Penalty und
Rangkonflikt-Abwehr lokal nachvollziehbar umgesetzt. Der Mehrzielvertrag ist
aber nicht vollständig: Die Engine gewichtet Ziele, finanziert sie jedoch nicht
priorisiert; dieselbe gemeinsame Vermögenslücke wird als individuelle
Goal-Evidence publiziert; und der wichtigste UI-Pfad kann Rang und Härte beim
Editieren, Reordern und Auswählen des Hauptziels gegeneinander verschieben.

Die drei neuen P1 sind mathematisch reproduziert, produktionsrelevant und durch
269 grüne Bestandstests nicht abgedeckt. Reale Goal-Achievability-, Konflikt-
und Hauptzielclaims bleiben bis zur vollständigen Umsetzung des
Reparaturvertrags gesperrt.
