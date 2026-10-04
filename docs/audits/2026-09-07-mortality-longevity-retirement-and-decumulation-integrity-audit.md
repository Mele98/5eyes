---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-mortality-longevity-retirement-decumulation-integrity-followup-audit"
status_as_of: "2026-09-07"
audit_started_on: "2026-09-05"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "b769f42b434585cb504a0c86050ec33f88e0ff2e"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-09-05-tax-model-regime-parameter-and-after-tax-publication-integrity-audit.md"
prior_release_audit_commit: "b769f42b434585cb504a0c86050ec33f88e0ff2e"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-07-mortality-longevity-retirement-and-decumulation-integrity-audit.md"
audit_mode: "read_only_static_ui_router_service_orm_schema_alembic_pdf_test_review_official_bfs_reference_and_isolated_runtime_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "Mortality reference data and sampler, death-state cashflow and goal semantics, longevity and planning horizons, retirement and decumulation context, optimizer/reporting parity, immutable run evidence, API/UI/PDF claims and reload semantics"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
static_findings_confirmed: 9
focused_existing_tests_passed: 395
focused_existing_tests_failed: 0
isolated_runtime_harness_executed: true
isolated_runtime_reproductions_confirmed: 7
official_bfs_reference_accessed: true
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "introduce one immutable MortalityAndLifeCourseSnapshot bound to TargetAllocation and OptimizerRun; use a versioned and hash-verified mortality source; define person, household, survivor and estate ownership for every flow and goal; make survival-conditioned and unconditional goal probabilities explicit; derive bounded horizons and yearly retirement states from one validated as-of context independent of tax configuration; route optimizer, reporting, API, UI and PDF through the same snapshot or fail closed"
---

# Mortalitäts-/Langlebigkeits-/Retirement-/Decumulation-Integritätsaudit

## Geltung und Abgrenzung

Dieser additive Folgeaudit dokumentiert die achtundzwanzigste Read-only-
Kontrollrunde. Die Prüfung begann am 5. September 2026, wurde am 7. September
2026 abgeschlossen und lief gegen den unveränderten Repository-Head
`b769f42`. Produktcode und Tests wurden nicht verändert.

Geprüft wurde nicht, ob eine bestimmte Person tatsächlich ein bestimmtes Alter
erreicht und auch nicht, welche medizinische oder versicherungsmathematische
Tafel für jeden Beratungsfall materiell die beste ist. Geprüft wurde der
technische und fachliche Vertrag, den 5eyes selbst behauptet:

1. welche Mortalitätsquelle und welches Berechnungsmodell produktiv wirken,
2. wie Todesalter und Todesjahr pro Pfad erzeugt werden,
3. welche Cashflows, Verbindlichkeiten und Ziele nach welchem Todesereignis
   fortbestehen,
4. wie Zielerreichung bei Tod, Überleben, Partner- und Nachlassfällen definiert
   ist,
5. wie Lebenserwartung, Retirement, Planungshorizont und Decumulation getrennt
   oder zusammengeführt werden,
6. ob Optimizer, Reporting-Monte-Carlo, API, UI und PDF dieselbe Semantik
   verwenden,
7. ob historische Ergebnisse mit einem unveränderlichen Quellen-, Personen-,
   Zeit- und Algorithmusstand reproduzierbar sind.

Dieser Audit ergänzt und ersetzt insbesondere nicht:

1. den unmittelbar vorherigen
   [Steuerregime-/Parameter-/After-Tax-Publikationsintegritätsaudit](2026-09-05-tax-model-regime-parameter-and-after-tax-publication-integrity-audit.md),
2. den
   [Zielerreichbarkeits-/Monte-Carlo-Publikationsintegritätsaudit](2026-09-02-goal-achievability-and-monte-carlo-publication-integrity-audit.md),
3. den
   [Advisory-Risk-KPI-/Engine-Konfigurations-/Reserve-/Compliance-Integritätsaudit](2026-09-02-advisory-risk-kpi-engine-config-reserve-and-compliance-integrity-audit.md),
4. den
   [Request-Ingestion-/Ressourcen-Governance-Audit](2026-08-27-request-ingestion-and-resource-governance-audit.md),
5. den historischen
   [Cashflow-in-Monte-Carlo-Audit](2026-06-07-cashflow-in-mc-audit.md),
6. sowie die weiterhin gültige
   [Stochastic-Core-Implementierungsbasis](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code, Tests und Migrationen zuerst, danach
dieser Audit und anschließend die genannten Dokumente.

### Verhältnis zu früheren Findings

Der Cashflow-Audit hat mit `F4` bereits bestätigt, dass die vorhandene
Todesmaske aggregierten Cashflow und aggregierte Goal-Liability nach dem
Todesindex auf null setzt und das Vermögen als Nachlass weiterwachsen lässt.
Diese Runde dupliziert `F4` nicht. Neu ist der fehlende Vertrag, **wessen** Tod
welchen personenbezogenen, gemeinsamen, überlebenden oder nachlassbezogenen
Flow beendet.

Die Findings `MC-CONTEXT-001`, `MC-CASHFLOW-CURRENCY-001` und
`GOAL-PUBLICATION-001` besitzen weiterhin den allgemeinen Vertrag für
Optimizer-/Reporting-Context, Cashflows und kanalgleiche Zielpublikation.
`MORT-CHANNEL-001` und `MORT-SNAPSHOT-001` erweitern diese Verträge nur um die
konkrete Mortalitätssemantik, Tabellenprovenienz und Todespfadbindung.

`TAX-CONTEXT-001` bleibt für den einmalig berechneten und über den gesamten
Steuerhorizont konstanten Retirementstatus zuständig. Diese Runde vergibt
dafür bewusst keine zweite ID. `RETIREMENT-CONTEXT-001` erfasst ausschließlich
den zusätzlichen, davon unabhängigen Fehler, dass das allgemeine
Decumulation-/Importance-Sampling-Signal derzeit an das Vorhandensein einer
Steuerjurisdiktion gekoppelt ist.

`RESOURCE-003` bleibt für globale Admission Control und Tenant-Fairness des
Solvers maßgeblich. `LIFE-INPUT-001` beschreibt ergänzend den konkreten
Fachinput, über den ein syntaktisch akzeptierter Geburtswert einen
unbegrenzten Mehrtausendjahres-Horizont erzeugt.

## Kurzurteil

Der aktuelle Stand darf **nicht** als mortalitätsadjustierte,
langlebigkeitsrobuste, haushaltsgerechte und über Optimizer, Zielanalyse,
Monte-Carlo-Chart und PDF konsistente Vorsorge-/Decumulationsrechnung
freigegeben werden.

Bestätigt sind insbesondere:

1. Die produktive Klasse bezeichnet ihre Werte als approximative,
   interpolierte und oberhalb Alter 100 extrapolierte BFS-2020-2022-Werte. Ein
   reproduzierbares Quellartefakt oder dessen Hash fehlt. Die tatsächlich
   berechnete Lebenserwartung bei Geburt liegt für Männer bei `79.7138` statt
   der im Modul genannten ungefähr `81.6` und für Frauen bei `83.5634` statt
   ungefähr `85.4`. Die Tests kennen diese Abweichung und akzeptieren breite
   Plausibilitätsfenster.
2. Das BFS stellt inzwischen offizielle Periodensterbetafeln 2023 mit neuem
   Berechnungsmodell bereit. Der lokale Stale-Helper beurteilt nur den Abstand
   zum Vintage-Endjahr, wird produktiv nicht konsumiert und blockiert oder
   kennzeichnet die Modellrechnung nicht.
3. Der Inverse-CDF-Sampler dokumentiert den Rückgabebereich bis
   `max_age + 1`, kann aber höchstens Alter `119` liefern. Bei aktuellem Alter
   119 gibt er stets 119 zurück und verletzt damit sogar seine eigene
   `current_age + 1`-Untergrenze.
4. Eine einzige Todesmaske des Hauptmandanten setzt sämtliche aggregierten
   Cashflows und Goal-Liabilities auf null. Die Models besitzen keine
   Zuordnung zu Hauptperson, Partner, Haushalt, Hinterbliebenen oder Nachlass,
   obwohl die UI Paar- und Familienmandate anbietet.
5. Wird eine Zielzahlung wegen Tod aus dem Wealth-Pfad entfernt, prüft die
   Zielerreichung dennoch am ursprünglichen Fälligkeitsindex nur
   `wealth >= 0`. Ein isolierter Zweipfadfall ergibt daher `success=[1,0]`:
   Der vor der Zahlung verstorbene Pfad wird als Zielerfolg gezählt, der
   überlebende und unterdeckte Pfad als Misserfolg.
6. Drei produktive Kanäle verwenden drei verschiedene Lebensdauerlogiken:
   Der Optimizer sampelt stochastisch nur bei aktivem Flag, die deterministische
   Zielanalyse setzt auch bei ausgeschaltetem Flag einen einzelnen erwarteten
   Todes-Cutoff, und die sichtbare Reporting-Monte-Carlo-Simulation berücksichtigt
   Mortalität überhaupt nicht. Ihre Goal-Summaries werden anschließend in die
   gemeinsame Zielanalyse gemischt.
7. Der UI-Text behauptet dennoch, dass „MC-Pfade“ die BFS-Sterbewahrscheinlichkeit
   berücksichtigen. Die publizierte Reporting-Modellbasis enthält kein
   Mortalitätsfeld und macht den Modellbruch nicht sichtbar.
8. Rohe Mandatsfelder liegen zwar sinnvoll im Input-Hash. Weder OptimizerRun
   noch die gespeicherte Modellbasis binden aber Tabelle, Quellhash,
   Referenzdatum, Alter-at-as-of, Sampleralgorithmus, RNG-Substream,
   Todesindexkonvention, Personen-/Flowklassifikation oder einen Hash der
   abgeleiteten Mortalitätspfade.
9. Persistierte `PlanningAssumption.life_expectancy_primary/partner` werden
   produktiv nicht zur Horizont- oder Mortalitätsberechnung gelesen. Parallel
   gelten Backend-Defaults 83/85, ein Frontend-Horizont 85/87/86 und ein
   zweiter Frontend-Chart-Horizont 83/85. Solver, Haushaltsprojektion und
   Zielanalyse beziehen sich zudem auf unterschiedliche Personenstände.
10. Client-Geburtsdaten sind freie Strings. Der gemeinsame Year-Parser liest
    nur die ersten vier Zeichen und besitzt keine Obergrenze; die
    Allocation-Horizontfunktion besitzt ebenfalls keinen Cap. Der Wert
    `9999-not-a-date` erzeugt bei Anrede `Herr` und Systemjahr 2026
    reproduzierbar einen Horizont von 8.057 Jahren.
11. Die PATCH-Chronologieprüfung sieht nur Felder desselben Requests. Die
    Router-Mergevalidierung enthält Retirement- und Lebenserwartungsjahr nicht.
    Zwei einzeln gültige Requests können daher `retirement_year=2100` und
    danach `life_expectancy_year=2000` persistieren.
12. Der Optimizer erhält `is_retired` nur über `_build_tax_solver_kwargs`.
    Ohne `tax_jurisdiction` kehrt diese Funktion vorher mit `{}` zurück. Ein
    bereits pensioniertes, steuernaives Mandat verliert so den vorgesehenen
    Decumulation-Trigger für Importance Sampling.

Der fokussierte Bestands-Gate mit 395 bestandenen Tests bestätigt vorhandene
Einzelverträge. Er enthält jedoch keinen End-to-End-Negativfall für
personenklassifizierte Post-Death-Flows, konkurrierende Mortalitäts-/
Zielereignisse, Flag-off-Parität, Mortality-Reporting-MC, Quellhash-Replay,
unbegrenzte Geburtsjahre, Split-PATCH-Chronologie oder steuerunabhängiges
Retirement-Routing.

## Stabiles Findings-Register

| ID | Priorität | Status | Kernaussage |
|---|---:|---|---|
| `MORT-SOURCE-001` | P1 | bestätigt | Die approximative Hardcode-Tafel besitzt kein reproduzierbares Quellartefakt/Hash, verfehlt die selbst genannte Geburtskalibrierung und bleibt trotz verfügbarer offizieller 2023-Tafel produktiv unmarkiert. |
| `MORT-SAMPLING-001` | P2 | bestätigt | Der Sampler kann den dokumentierten Terminalzustand `max_age + 1` nicht erzeugen und liefert bei aktuellem Alter 119 Tod im bereits erreichten Alter. |
| `MORT-POSTDEATH-001` | P1 | bestätigt | Der Tod der Hauptperson beendet undifferenziert alle aggregierten Personen-, Haushalts-, Partner- und Ziel-Cashflows; Survivor-/Estate-Semantik fehlt. |
| `MORT-GOAL-001` | P1 | bestätigt | Wegen Tod entfernte Zielzahlungen werden als erfüllt gezählt; Survival-, Anwendbarkeits- und Funding-Wahrscheinlichkeit sind nicht getrennt. |
| `MORT-CHANNEL-001` | P1 | bestätigt | Optimizer, deterministische Zielanalyse und Reporting-Monte-Carlo verwenden drei widersprüchliche Mortalitätslogiken, während die UI pauschal mortalitätsadjustierte MC-Pfade behauptet. |
| `MORT-SNAPSHOT-001` | P1 | bestätigt | TA/OptimizerRun/Model-Basis binden keinen vollständigen, unveränderlichen Mortalitäts- und Life-Course-Context; historische Reproduktion bleibt zeit- und codeabhängig. |
| `LIFE-ASSUMPTION-001` | P1 | bestätigt | Persistierte Lebenserwartungsannahmen sind inert; mehrere Backend-/Frontend-Defaults und Personenbezüge konkurrieren ohne kanonische Source of Truth. |
| `LIFE-INPUT-001` | P1 | bestätigt | Freie Datumsstrings, fehlender Horizon-Cap und unvollständige PATCH-Mergevalidierung erlauben Mehrtausendjahreshorizonte und widersprüchliche Lebensphasen. |
| `RETIREMENT-CONTEXT-001` | P1 | bestätigt | Das allgemeine Decumulation-Signal des Optimizers hängt fälschlich von einer Steuerjurisdiktion ab; ohne Tax-Setup gilt selbst ein pensioniertes Mandat als nicht pensioniert. |

## Positivkontrollen, die erhalten bleiben müssen

Die Reparatur darf folgende bestehende Kontrollen nicht zurückbauen:

1. Aktivierte Mortalität validiert Jurisdiktion `CH`, Geburtsjahr im
   unterstützten Altersbereich und Geschlecht `M/F` fail-closed.
2. Ohne aktiviertes Mortalitätsflag liefert
   `mortality_solver_kwargs_from_mandate()` bewusst ein leeres Dict.
3. `death_year_index_per_path` wird auf exakt `(n_paths,)` validiert.
4. Der Solver baut einen gemeinsamen `OptimizerContext` und reicht dieselbe
   Objektidentität an Bewertung, Explainability und kontrollierten Fallback
   weiter.
5. Seed und Pfadzahl werden pro OptimizerRun gespeichert.
6. Die BFS-Klasse ist immutable; q(x)-Werte werden auf gültiges Geschlecht und
   Altersgrenzen geprüft.
7. Die Scenario-Engine dokumentiert die gegenwärtige Todesindexkonvention und
   lässt Vermögen nach dem Cashflowende als Nachlass weiterwachsen.
8. Datierte Ziele verlängern den automatischen Projekthorizont und werden
   nicht allein wegen eines kürzeren Berater-Overrides abgeschnitten.
9. Der allgemeine Haushalts-Horizont wählt bei vorhandener Partnerperson das
   spätere der beiden pauschalen Endjahre.
10. Die rohen Felder `client_birth_year`, `client_sex`,
    `use_mortality_simulation`, `retirement_year` und
    `life_expectancy_year` sind bereits Bestandteil des Projection-
    Input-Snapshots und können dadurch Input-Drift auslösen.
11. Der Frontend-Save markiert die Strategie nach geänderten
    Mandatseinstellungen als neu zu berechnen.
12. Bestehende Tests decken Tabellen-Basics, Stichprobenverteilung,
    Todesmaskierung, Jurisdiktionsgate, Horizon-Verlängerung, Input-Hash und
    direkte Importance-Sampling-Entscheidungen breit ab.
13. Der Max-Pension-Spending-Endpunkt bezeichnet seine Berechnung heute
    ausdrücklich als deterministische Annuitätennäherung; er behauptet noch
    keine stochastisch nachhaltige Withdrawal Rate. Diese ehrliche Begrenzung
    bleibt erhalten, bis ein echter Decumulation-Snapshot existiert.

## Tatsächlicher Mortalitäts- und Life-Course-Fluss

```text
Client / Mandate / PlanningAssumption
  Client.date_of_birth / partner_date_of_birth: freie Strings
  Mandate.client_birth_year / client_sex / use_mortality_simulation
  Mandate.retirement_year / life_expectancy_year
  PlanningAssumption.life_expectancy_primary / partner: persistiert, inert
        |
        +-------------------------------+
        |                               |
        v                               v
Optimizer-Entscheidung                  allgemeiner Projektionshorizont
  mortality flag true?                  manual life_expectancy_year, sonst
  CH + birth + M/F                      birth + 83/85, längerer Partner
        |                               kein oberer Cap
        v
BFS_2020_2022 + date.today().year
  sample one primary death age/path
        |
        v
one alive_mask
  all aggregate cashflows * mask
  all aggregate goal liabilities * mask
  wealth growth continues as estate
        |
        v
Goal probability
  original goal due indices
  no survival/applicability state
  removed payment can become success

Parallel publication paths
  deterministic goal analysis:
    one expected death cutoff, even when mortality flag is false

  reporting Monte Carlo:
    no mandate/death input; all cashflows run for every path
    its goal summaries overwrite/merge deterministic summaries

  UI/PDF model basis:
    claims MC/BFS or generic methodology
    no exact mortality source, state semantics or snapshot id
```

## Kanal- und Semantikmatrix

| Verbraucher | Lebensdauerbasis | Personenbasis | Cashflow-/Goal-Verhalten | Gespeicherte/angezeigte Evidenz |
|---|---|---|---|---|
| Stochastic Optimizer | BFS-Sample nur bei Flag an | nur Hauptmandant | alle aggregierten Cashflows und Liabilities nach dessen Tod null | Seed/Pfadzahl; keine Tabellen-/Pfad-/Personenprovenienz |
| deterministische Goal Analysis | manuelles Endjahr, sonst BFS-Median für CH; Flag wird nicht geprüft | Hauptmandant | Contribution-Series ab einem einzelnen Cutoff null | keine sichtbare Trennung zur Reporting-MC |
| Reporting Monte Carlo | keine Mortalität | keine Todesperson | jeder Pfad erhält über den ganzen Horizont dieselbe Cashflowserie | generische `implementation_projection_v2`-Basis ohne Mortalität |
| Backend-Horizont | manuell, sonst Geburt +83/+85 | späteres Ende von Hauptperson/Partner | bestimmt Arraylänge, nicht Todeszustand | kein Life-Course-Snapshot |
| Frontend vorgeschlagener Mandatshorizont | Geburt +85/+87/+86 | späteres Ende im Paar/Familie | UI-Datumsbereich | andere Defaults als Backend |
| Frontend Cashflow-/Chart-Horizont | Geburt +83/+85, maximal 80 Jahre | späteres Ende im Haushalt | Chart-/Requesthorizont | anderer Default als erster Frontendpfad |
| Advisory-Report-Horizont | primär Zeit bis Retirement, dann PlanningAssumption-Retirement, dann Mandats-Endjahr | primär Hauptperson | eigener Reporting-Horizont | nicht mit Mortalitätssnapshot reconciliert |
| Max Pension Spending | deterministische Annuität bis übergebenes Endalter | Requestwerte | keine Mortalitätsverteilung | korrekt als deterministisch begrenzt |

## Prüfmethodik und Quellen

### Statische Prüfung

Gelesen und quergeprüft wurden insbesondere:

- `services/mortality/base.py`, `bfs.py`, `sampler.py` und deren Tests,
- `services/optimizer/solver.py`, `scenario_engine.py`, `objective.py`,
  `goal_liabilities.py` und `importance_sampling.py`,
- `services/portfolio_engine.py`, `portfolio_engine_payload.py`,
  `portfolio_engine_mc_simulation.py` und
  `portfolio_engine_optimizer_integration.py`,
- `services/planning_horizon.py` und `advisory_report.py`,
- Mandats-, Client-, Wealth- und Allocation-Models/Schemas/Router sowie
  Alembic-Baseline,
- `5eyes-electron/frontend/5eyes_v2.html`,
- bestehende Planungs-, Handoff-, Audit- und Deploymentdokumente.

### Offizielle Referenz

Am 7. September 2026 wurde die offizielle
[BFS-Periodensterbetafel 2023](https://www.pxweb.bfs.admin.ch/pxweb/de/px-x-0102020300_102/-/px-x-0102020300_102.px/)
geprüft. Die BFS-Seite bezeichnet den Datenbankstand als November 2023 und
nennt ausdrücklich ein neues Berechnungsmodell. Der Audit leitet daraus nicht
ab, dass jede 2023-Zahl automatisch für jede Beratung materiell richtig ist.
Er belegt nur, dass eine neuere offizielle Modellbasis existiert und ein rein
zeitabstandsbasierter lokaler Stale-Helper diese Verfügbarkeit nicht abbildet.

### Isolierte Laufzeitreproduktionen

Die Reproduktionen importierten ausschließlich bestehende Funktionen mit
`PYTHONDONTWRITEBYTECODE=1`. Sie schrieben keine Produktdaten und änderten
weder Code noch Tests.

#### Tod entfernt Zahlung und erzeugt Zielerfolg

Zwei identische Nullrenditepfade, Startvermögen null, einmalige Zahlung 100 im
zweiten Jahr:

```text
death_year_index_per_path = [1, 3]
wealth = [
  [0.0, 0.0,    0.0,    0.0],
  [0.0, 0.0, -100.0, -100.0],
]
goal_probability_per_path = [1, 0]
```

Pfad 1 stirbt vor der Zahlung. Die Liability wird entfernt und derselbe Pfad
als Erfolg gezählt. Pfad 2 lebt bis zur Zahlung, wird negativ und scheitert.

#### Flag-off-Cutoff, ungebremster Horizont und Tax-Kopplung

```text
{
  "mortality_flag": false,
  "deterministic_death_offset": 38,
  "unbounded_horizon": 8057,
  "retired_without_tax_kwargs": {}
}
```

Der erste Wert stammt aus einem CH-Mandat mit Geburtsjahr 1980, Geschlecht M
und ausgeschaltetem Mortalitätsflag. Der 8.057-Jahre-Horizont stammt bei
Anrede `Herr` und Systemjahr 2026 aus
`date_of_birth="9999-not-a-date"`. Das pensionierte Testmandat besitzt keine
Steuerjurisdiktion und erhält deshalb kein `is_retired`-Argument.

#### Tabellenkalibrierung und Terminalalter

```text
{
  "LE_M_0": 79.7138482552842,
  "LE_F_0": 83.56337256384887,
  "LE_M_65": 19.02546106350948,
  "LE_F_65": 21.825297437064094,
  "survival_M_118": [1.0, 0.18727000000000005],
  "survival_M_119": [1.0],
  "samples_age118": [119, 119, 119, 119, 119],
  "samples_age119": [119, 119, 119, 119, 119]
}
```

`q(119)=1` wird von der Survival-Schleife für Startalter 119 nicht mehr
verarbeitet. Der Sampler kann weder Alter 120 noch ein Todesjahr nach dem
aktuellen Alter 119 liefern.

#### Split-PATCH-Chronologie

```text
patch_1 = {"retirement_year": 2100}
patch_2 = {"life_expectancy_year": 2000}
both_individually_accepted = true
```

Beide `MandateUpdate`-Objekte passieren getrennt die Schema-Validierung. Die
Router-Mergevalidierung ergänzt die beiden Felder nicht aus dem Bestand.

## `MORT-SOURCE-001` – Mortalitätsquelle und Kalibrierung sind nicht reproduzierbar freigabefähig

### Beobachtung

`services/mortality/bfs.py` beschreibt `_Q_MALE` und `_Q_FEMALE` zugleich als
„empirisch kalibriert“ und als approximative, gerundete und interpolierte
Werte. Oberhalb Alter 100 werden Werte per Gompertz extrapoliert. Im
Repository liegt weder die genannte XLSX-Datei noch ein normalisierter
Importdatensatz, ein Transformationsskript, eine Prüfsumme oder ein
Abnahmeprotokoll, das die 240 Werte exakt auf eine BFS-Veröffentlichung
zurückführt.

Der Modul-Docstring nennt als Plausibilitätsziel bei Geburt ungefähr 81,6
Jahre für Männer und 85,4 für Frauen. Der reale Helper liefert 79,7138 und
83,5634. Die Datei `tests/test_bfs_mortality_stale_audit.py` dokumentiert
diese Abweichung sogar ausdrücklich und akzeptiert sie mit den Fenstern
78–83 beziehungsweise 82–87. Das prüft Plausibilität, nicht
Quellübereinstimmung.

`is_stale_for_year()` wird erst bei mehr als fünf Jahren Abstand zum
Vintage-Endjahr 2022 wahr, blockiert laut eigenem Docstring nie und besitzt
keinen produktiven Consumer. Eine neu veröffentlichte Tafel wird dadurch
nicht erkannt. Die offizielle BFS-Periodensterbetafel 2023 mit neuem
Berechnungsmodell existiert bereits.

### Risiko

Eine approximative Hazard-Kurve wirkt direkt auf Todesalter, Cashflowdauer,
Goal-Liabilities, Shortfall-Tails und potenziell die ausgewählte Allokation.
Breite Plausibilitätstests können eine in sich monotone, aber materiell falsch
kalibrierte Kurve grün halten. Ohne Quellhash und Transformationsnachweis ist
ein historischer Run trotz Tabellenname nicht beweisbar.

### Verbindlicher Fixvertrag

- Ein versioniertes Mortality-Source-Registry-Objekt definiert Jurisdiktion,
  Population, Perioden-/Kohortenbasis, Referenzjahre, Geschlechts-/
  Altersabdeckung, Einheit, Quelle, Veröffentlichungsdatum und Freigabestatus.
- Originalartefakt oder rechtlich zulässiger kanonischer Extract, Source-URL,
  Byte-Hash und Transformationscode werden reproduzierbar archiviert.
- Die generierten q(x)-Arrays besitzen einen kanonischen Content-Hash und
  Golden-Value-/Gesamtkurvenabgleich, nicht nur breite LE-Fenster.
- Interpolation, Extrapolation, Terminalannahme und Rundung sind versionierte
  Algorithmen und Bestandteil des Snapshot-Hashes.
- Freshness bewertet verfügbare/zugelassene Veröffentlichungen, nicht nur
  Kalenderabstand. Unknown/stale/unapproved ist im produktiven Run entweder
  fail-closed oder explizit als nicht freigabefähig sichtbar.
- Ein bewusst beibehaltener älterer Vintage bleibt für historischen Replay
  verfügbar, darf aber nicht still der neue Default sein.

### Abnahmetests

- Byte-/Content-Hash gegen das freigegebene Quellartefakt.
- Vollständiger q(x)-Golden-Test je Personenkategorie und Alter.
- Reproduzierbarer Transformer auf leerem Checkout.
- Available-newer-, stale-, unknown-source- und revoked-source-Negativfälle.
- Historischer Replay bleibt auf dem gespeicherten Vintage, neuer Run nutzt
  nur einen explizit freigegebenen aktuellen Vintage.

## `MORT-SAMPLING-001` – Terminalverteilung und dokumentierter Wertebereich widersprechen sich

### Beobachtung

`survival_curve(current_age)` erzeugt
`max_age - current_age + 1` Elemente und verwendet in der Schleife nur
q(x) bis `max_age - 1`. Der terminale Wert `q(119)=1` liegt daher nicht in
der CDF des Samplers. `sample_age_at_death()` begrenzt den von
`searchsorted()` erzeugten Index anschließend auf
`len(survival) - 1`. Das maximal mögliche Ergebnis ist Alter 119, obwohl der
Docstring `table.max_age + 1` verspricht.

Bei aktuellem Alter 119 hat die Survival-Kurve nur ein Element,
`max_relative=0`. Das Clipping ergibt relative null; alle Samples liefern
Alter 119 statt mindestens Alter 120. Bei Alter 118 werden sowohl Todesfälle
im Folgejahr als auch der verbliebene Survivor-Anteil auf Alter 119
zusammengeclippt.

Die vorhandenen Tests prüfen `> current_age` nur für normale Startalter und
akzeptieren für die Obergrenze lediglich `<= max_age + 1`. Der exakte
Terminalvertrag bleibt dadurch ungetestet.

### Risiko

Der Fehler betrifft seltene Hochaltrigenfälle, aber genau diese liegen im
unterstützten Schema-Altersbereich 0–119. Er verletzt die dokumentierte
Verteilung, erschwert Censoring-Audits und kann für sehr alte Mandate
Cashflows ein Jahr zu früh beenden.

### Verbindlicher Fixvertrag

- Es wird explizit entschieden, ob q(x) den Tod im Intervall
  `[x, x+1)` oder `(x, x+1]` beschreibt.
- Die Survival-/CDF-Länge enthält die terminale Hazard vollständig oder ein
  separater Survivor-/Censoring-Atom wird modelliert.
- Der Sampler liefert für jeden zulässigen Startwert ein Todesalter strikt
  größer als `current_age`, sofern der fachliche Vertrag so lautet.
- „lebt über den Horizont hinaus“ wird als eigener Status oder eindeutig
  dokumentierter Censoringwert behandelt, nicht still mit einem Todeszeitpunkt
  verwechselt.
- Maximalalter und erlaubter Inputbereich werden zwischen Source Registry,
  Schema und Sampler identisch definiert.

### Abnahmetests

- Exakte Fälle für Startalter 118 und 119 sowie beide Geschlechter.
- CDF-Masse summiert sich inklusive Terminal-/Survivoratom auf eins.
- Seed-fixe Quantil- und Häufigkeitstests einschließlich rechter Grenze.
- Roundtrip Todesalter → Todesindex → Alive-Mask an Horizontgrenzen.

## `MORT-POSTDEATH-001` – Eine Hauptpersonenmaske beendet undifferenziert den gesamten Haushalt

### Beobachtung

`build_optimizer_context()` sampelt ausschließlich aus
`mandate.client_birth_year` und `client_sex`. Die Scenario-Engine baut daraus
eine einzige `alive_mask` und multipliziert sowohl die vollständige
Cashflowserie als auch die vollständige aggregierte Liabilityserie damit.

`Cashflow`, `WealthInflow` und `Goal` besitzen kein Feld für Person,
wirtschaftlichen Eigentümer, Survivor, Haushalt oder Nachlass. In der
Produktaggregation fließen manuelle Einkommen/Ausgaben, erwartete Zuflüsse,
Hypotheken-/Immobilienströme, Steuerflüsse und sämtliche Goals zusammen. Nach
dem Tod der Hauptperson können daher unter anderem Partnereinkommen,
Haushaltskosten, Hypotheken, Ausbildungskosten der Kinder, Hinterbliebenen-
leistungen und Nachlassziele gleichzeitig verschwinden. Das Portfoliovermögen
wächst dagegen weiter als „Erbschaft“.

Die UI bietet `Einzelperson`, `Paar` und `Familie` sowie eine
„Lebensdauer-Unsicherheit“ an. Die ursprüngliche Spec nennt
Multi-Person-/Joint-Survival ausdrücklich als Out-of-Scope, blockiert Paar-
oder Familienmandate aber nicht und publiziert diese Begrenzung nicht am
Ergebnis.

### Risiko

Ein Ereignis der Hauptperson wird fälschlich zum Ende aller
Haushaltsverpflichtungen und -einnahmen. Dadurch können Shortfall,
Liquiditätsreserve, Entnahmebedarf, Zielwahrscheinlichkeit und optimale
Allokation in beide Richtungen materiell verzerrt werden. Besonders kritisch
sind Partner- und Kinderziele, die gerade **nach** dem Tod fortbestehen.

### Verbindlicher Fixvertrag

- Jede Person im Haushalt erhält eine stabile ID und einen eigenen
  Life-Course-/Survival-Zustand.
- Jeder Cashflow, Zufluss und jedes Goal erhält eine Pflichtklassifikation,
  zum Beispiel `primary_contingent`, `partner_contingent`, `joint_household`,
  `survivor`, `estate` oder eine fachlich gleichwertige Typisierung.
- Post-Death-Regeln sind explizite Transformationen: endet, reduziert sich,
  startet, wechselt Empfänger oder bleibt unverändert.
- Gemeinsame Kosten dürfen nicht pauschal verschwinden; Survivor-Kosten und
  Hinterbliebenenleistungen sind gesondert modellierbar.
- Estate-Ziele und Vermögensfortschreibung besitzen eine konsistente
  Eigentums-/Steuer-/Goal-Semantik.
- Solange Multi-Person nicht unterstützt ist, blockiert aktivierte
  Mortalität für Paar/Familie fail-closed oder der gesamte Kundenclaim wird
  sichtbar und technisch auf Einzelperson begrenzt.

### Abnahmetests

- Hauptperson stirbt, Partner lebt: Partnercashflow und gemeinsames Ziel
  folgen ihrer klassifizierten Regel.
- Partner stirbt zuerst und beide sterben innerhalb/außerhalb des Horizonts.
- Kinder-/Ausbildungsziel, Hypothek, Witwen-/Witwerrente und Estate-Bequest.
- Unknown/fehlende Ownership blockiert statt auf Hauptperson zu fallen.
- API, UI, PDF und signierter Snapshot zeigen Personenbasis und
  Post-Death-Regel identisch.

## `MORT-GOAL-001` – Tod kann eine nicht bezahlte Zielverpflichtung als Erfolg zählen

### Beobachtung

Die Scenario-Engine entfernt die aggregierte Liability nach dem Todesindex.
Das einzelne `GoalLiability`-Objekt behält jedoch seinen ursprünglichen
positiven Fälligkeitspfad. `goal_probability_per_path()` bestimmt daraus die
Wealth-Spalten und wertet bei `cashflow_in_year` und `outflow_stream` lediglich
aus, ob der bereits mortalitätsmaskierte Wealth-Pfad an diesen Spalten
nichtnegativ ist.

Es gibt weder einen Alive-/Applicable-Vektor je Goal noch einen
survival-conditioned Nenner. Die isolierte Reproduktion zeigt den Effekt
direkt: Der vor einer 100-Rappen-Zahlung verstorbene Pfad bleibt bei null und
erhält Erfolg 1; der überlebende Pfad zahlt, wird -100 und erhält Erfolg 0.

Auch `wealth_at_t` unterscheidet nicht, ob ein persönliches Vermögensziel nach
Tod noch anwendbar ist oder als Nachlassziel weiterlebt. Das System publiziert
somit eine einzelne „Erreichungswahrscheinlichkeit“, obwohl mindestens
Survival, Anwendbarkeit und Funding getrennte Zufallsereignisse sind.

### Risiko

Je höher die Sterbewahrscheinlichkeit vor einem belastenden persönlichen
Ziel, desto besser kann dessen ausgewiesene Erfolgsquote werden. Das kehrt die
fachliche Bedeutung um und kann harte Vorsorge- oder Ausgabenziele scheinbar
erreichbar machen, ohne dass sie finanziert wurden.

### Verbindlicher Fixvertrag

- Jedes Goal definiert, in welchen Life-/Household-/Estate-Zuständen es
  anwendbar und wer begünstigt ist.
- Pro Goal werden mindestens `P(applicable)`, `P(funded AND applicable)` und
  `P(funded | applicable)` unterschieden, sofern sie fachlich relevant sind.
- Für persönliche Langlebigkeitsziele wird explizit zwischen
  `alive_and_funded`, `died_before_due` und `alive_but_shortfall`
  unterschieden. `died_before_due` ist nicht automatisch Erfolg.
- Survivor- und Estate-Ziele verwenden ihren jeweils eigenen Zustandsnenner.
- Optimizerobjektiv, Constraint-Prüfung, Explainability, API, UI und PDF
  konsumieren dieselbe maschinenlesbare Semantik.
- Bestehende Conditional-Goal-Semantik wird mit Mortalität komponiert und
  nicht durch eine zweite lose Prozentzahl überlagert.

### Abnahmetests

- Exakte Zweipfad-Golden-Tests für Tod vor, am und nach der Fälligkeit.
- Einmalzahlung, Outflow-Stream, Wealth-at-T, Survivor- und Estate-Ziel.
- Unconditional- und conditional-Wahrscheinlichkeiten reconciliieren auf die
  Anzahl/Weights der Pfade.
- Importance-Sampling-Pfadgewichte werden in allen Nennern identisch
  angewendet.
- Kein UI-/PDF-Kanal darf `not_applicable` als Erfolg formatieren.

## `MORT-CHANNEL-001` – Decision, Zielanalyse und Reporting-MC besitzen drei Mortalitätsmodelle

### Beobachtung

Der Optimizer aktiviert BFS-Sampling nur, wenn
`use_mortality_simulation=true` und die Mandatsinputs vollständig sind.

`_expected_death_year_offset_from_mandate()` prüft dieses Flag dagegen nicht.
Ein manuelles `life_expectancy_year` oder bei CH ein Geburtsjahr plus
Geschlecht erzeugt einen einzelnen erwarteten Todes-Cutoff. Die
deterministische `_build_goal_analysis()` setzt ihre Contribution-Series ab
diesem Offset auf null. Die Laufzeitreproduktion mit ausgeschaltetem Flag
lieferte dennoch einen Cutoff von 38 Jahren. Das verletzt die ursprüngliche
Backwards-Compat-Spec „Flag false → kein Verhalten geändert“.

`_run_allocation_monte_carlo()` akzeptiert weder Mandat noch Todesindizes. In
jeder Iteration wendet sie die vollständige
`cashflow_projection_series_rappen` über den ganzen Horizont an. Danach baut
sie eigene `goal_summaries`, die über
`_merge_goal_analysis_with_monte_carlo()` in die gemeinsame Zielanalyse
eingesetzt werden.

Die UI bezeichnet die Checkbox als „Lebensdauer-Unsicherheit“ und erklärt,
„MC-Pfade“ würden die BFS-Sterbewahrscheinlichkeit berücksichtigen. Der
sichtbare MC-Block publiziert Pfadzahl, Seed, Quantile und Goal-Pfaderfolg,
aber nur die generische Reportingbasis. `_build_allocation_model_basis()`
enthält in weder Optimization- noch Reportingobjekt ein Mortality-Feld.

### Risiko

Ein sichtbarer Goal-Prozentsatz kann je nach Mergequelle ohne Mortalität, mit
einem deterministischen erwarteten Cutoff oder mit einer stochastischen
Einzelpersonenverteilung entstanden sein. Das Flag besitzt keine eindeutige
Produktwirkung und die UI beschreibt den falschen MC-Kanal. Decision und
Kundenerklärung sind dadurch nicht reconciliert.

### Verbindlicher Fixvertrag

- Ein einziger gesnapshotteter Mortality-/Life-Course-Context wird vor allen
  Simulationen aufgelöst.
- Flag-off bedeutet in allen Kanälen exakt dieselbe dokumentierte Semantik;
  ein manuelles Planungsendjahr darf nicht still als Todesereignis umgedeutet
  werden.
- Decision- und Reporting-MC konsumieren entweder dieselben Todeszustände und
  klassifizierten Flows oder veröffentlichen klar getrennte, reconciliable
  Modelle mit unterschiedlichen Namen.
- Deterministische Lebenserwartung, stochastische Survival-Verteilung und
  reiner Planungshorizont erhalten getrennte Typen/Felder.
- Goal-Merge prüft Basis-ID, Snapshot-ID, Pfadweights und Semantik; inkompatible
  Summaryobjekte blockieren.
- UI und PDF nennen exakt, welcher Kanal mortalitätsadjustiert ist, welche
  Person(en) modelliert sind und ob Werte conditional oder unconditional sind.

### Abnahmetests

- Flag an/aus verändert jeden vorgesehenen Kanal kontrolliert und keinen
  unbeabsichtigten Kanal.
- Identische Snapshot-ID in Optimizer, Reporting-MC, Goal Analysis, API, UI
  und PDF.
- Mutation von Live-Mandat/Setting nach Run verändert historische Ausgabe
  nicht.
- Browser-/PDF-Golden-Tests prüfen die konkrete Mortalitätsdisclosure, nicht
  nur das Vorhandensein des Wortes „MC“.
- Inkompatible oder fehlende Basis erzeugt `unknown/blockiert`, nie einen
  positiven Zielclaim.

## `MORT-SNAPSHOT-001` – Historische Mortalitäts- und Life-Course-Evidenz fehlt

### Beobachtung

Der Projection-Input-Snapshot bindet die rohen Mandatswerte für Geburtsjahr,
Geschlecht, Flag, Retirement- und Lebenserwartungsjahr. Das ist eine wichtige
Driftkontrolle, beweist aber nicht, wie diese Werte aufgelöst wurden.

`build_optimizer_context()` berechnet das aktuelle Alter mit
`date.today().year`, importiert den globalen Convenience-Export
`BFS_2020_2022` und erzeugt daraus Todesindizes. `OptimizerRun` speichert Seed,
Pfadzahl, Ergebnis- und Diagnosedaten, aber keinen vollständigen Inputcontext.
`_persist_optimizer_run()` schreibt weder Tabellen-/Algorithmusmetadaten noch
einen Context- oder Todespfadhash.

Die gespeicherte `optimization_model_basis` kennt Return-, Tail-, Tax-,
Liability- und Portfolio-Dynamik, aber keine Mortalitätsbasis. Der
`allocation_context_hash` bindet diese unvollständige Basis und den Raw-
Inputhash. Ein späterer Wechsel des Convenience-Exports, des Samplers, des
Systemjahres oder der Personen-/Maskenlogik ist daraus nicht rekonstruierbar.

### Risiko

Gleicher Mandatsinput und gleicher Seed können in einem späteren Kalenderjahr
oder nach Tabellen-/Codewechsel andere Todesindizes und damit andere
Zielwahrscheinlichkeiten erzeugen. Ein historisches PDF kann weder die
tatsächlich verwendete Source noch die modellierte Person, Population,
Terminalkonvention oder Post-Death-Regel beweisen.

### Verbindlicher Fixvertrag

Ein immutable `MortalityAndLifeCourseSnapshot` bindet mindestens:

- Snapshot-ID, Schema-/Resolverversion, `calculation_as_of` und Zeitzone,
- Personen-IDs, validierte DOB-/Sex-/Householdinputs und Source-Priorität,
- Retirement-/Lebensphasenereignisse und deren Quelle,
- Mortality-Source-ID, Jurisdiktion, Population, Period/Cohort,
  Referenzjahre, Veröffentlichungsstand, Quell- und q(x)-Hash,
- Interpolations-, Extrapolations-, Terminal- und Sampleralgorithmusversion,
- RNG-Generator, Seed-Domain/Substream, Pfadzahl, Horizon und Weight-Basis,
- Todesindex-/Alive-Konvention sowie Hash der abgeleiteten Zustandsmatrix oder
  eine vollständig deterministische Replay-Rezeptur,
- Flow-/Goal-Ownership und Post-Death-Regelversion,
- Probability-Semantik und kanalweise Modellbasis.

TargetAllocation und jeder zugehörige OptimizerRun referenzieren atomar
denselben Snapshot. Reporting, Reload, PDF und Signatur lesen historische
Felder ausschließlich daraus. Fehlender, fremder, manipulierter oder nicht
replaybarer Snapshot blockiert fail-closed.

### Abnahmetests

- Replay in anderem Kalenderjahr und nach neuem Default-Vintage bleibt
  byte-/hashstabil.
- Gleicher Seed mit getrennten Return-/Mortality-Substreams bleibt bei
  interner Refaktorierung definiert.
- TA/Run-/Mandat-/Tenant-/Snapshot-FKs und Hashes werden DB-seitig geprüft.
- Tamper an Source, q(x), Person, Horizon, Ownership oder Algorithmus wird
  erkannt.
- Reload/API/UI/PDF/Signatur publizieren dieselbe Snapshot-ID und Basis.
- Alte Rows ohne Snapshot werden sichtbar als Legacy/unverifiziert behandelt,
  nie still mit heutigen Defaults repariert.

## `LIFE-ASSUMPTION-001` – Lebenserwartungsannahmen und Defaults besitzen keine kanonische Bedeutung

### Beobachtung

`PlanningAssumption` speichert `life_expectancy_primary` und
`life_expectancy_partner`; Schema-Kommentare behaupten, diese Werte flössen in
MC-Simulation und Zielprojektion jedes Berichts. Die produktive Suche findet
jedoch nur Persistenz, API-Ausgabe, Foundation-Seed und Tests. Weder
`planning_horizon.py` noch Optimizer, Goal Analysis oder Reporting-MC lesen
diese beiden Felder.

`retirement_age_primary` wird in einem Advisory-Report-Fallback verwendet;
Partner-Retirement wird dort nicht berücksichtigt. Gleichzeitig existieren
mehrere pauschale Life-End-Regeln:

- Backend-Haushalt: Mann 83, sonst 85;
- Frontend-Mandatshorizont: Mann 85, Frau 87, unbekannt 86;
- Frontend-Cashflow-/Chart-Horizont: Mann 83, sonst 85, zusätzlich auf 80
  Jahre begrenzt;
- deterministische Goal Analysis: manuelles Mandatsjahr oder BFS-Median der
  Hauptperson;
- stochastic Optimizer: Survival-Sample der Hauptperson;
- Haushaltshorizont: späteres pauschales Endjahr von Hauptperson und Partner.

Damit bezeichnen „Lebenserwartung“, „Horizont“ und „Lebensdauer“ je nach
Consumer Erwartungswert, Default-Endalter, späteren Partner, manuelles
Planungsende oder stochastisches Todesereignis.

### Risiko

Ein Berater kann Werte speichern, die sichtbar korrekt erscheinen, aber die
Entscheidung nicht beeinflussen. Derselbe Haushalt erhält abhängig vom Kanal
unterschiedliche Laufzeiten und Personenbezüge. Das kann Cashflowarrays,
Zieljahre, Verlust-/Depletionwahrscheinlichkeit und PDF-Erklärung verändern,
ohne dass ein einzelner Override oder eine Source-Priorität erkennbar ist.

### Verbindlicher Fixvertrag

- Fachlich getrennte Typen für `planning_horizon_end`,
  `retirement_event`, `expected_remaining_lifetime`, Survival-Verteilung,
  Survival-Quantil und Estate-Horizon einführen.
- Eine zentrale Resolver-Priorität legt fest, welche validierte Quelle für
  welchen Typ gilt; Mandatsjahr und PlanningAssumption dürfen nicht parallel
  unversöhnt aktiv sein.
- Primary-/Partnerwerte werden personenidentisch aufgelöst und im
  Household-Context kombiniert.
- Frontend und Backend beziehen Defaults und Labels aus derselben versionierten
  Capability/Policy statt aus duplizierten Konstanten.
- Persistierte, aber fachlich inaktive Felder werden entfernt, migriert oder
  bis zur Implementierung sichtbar als „nicht verwendet“ markiert.
- Jede effektive Annahme trägt Source, Actor, Zeitpunkt, Begründung und
  Snapshotbindung.

### Abnahmetests

- Mutation jedes angebotenen Felds bewirkt den spezifizierten Consumer oder
  wird sichtbar abgelehnt.
- Primary-/Partner- und Single-/Paar-/Familienfälle über API, UI, Engine und
  PDF.
- Defaultwerte sind serverseitig versionsgebunden und über alle Kanäle gleich.
- Manual Override, statistischer Erwartungswert und Survival-Quantil bleiben
  getrennt und werden korrekt beschriftet.
- Legacy-PlanningAssumptions besitzen einen expliziten Migrations-/Unknown-
  Vertrag.

## `LIFE-INPUT-001` – Lebensphaseninputs können widersprüchliche und ungebremste Horizonte erzeugen

### Beobachtung

`ClientCreate` und `ClientUpdate` deklarieren Geburts-/Partnergeburts- und
Investment-Horizon-Daten als freie optionale Strings. Der gemeinsame Helper
`_year()` nimmt bei einem String lediglich die ersten vier Zeichen und prüft
eine Unter-, aber keine Obergrenze oder ein echtes Datum.

`_simulation_horizon_years()` bildet ohne expliziten Override das Maximum aus
Default, Goals und abgeleitetem Life-Year. Eine fachliche oder technische
Obergrenze fehlt. Der syntaktisch akzeptierte Wert
`9999-not-a-date` erzeugt bei Anrede `Herr` und Systemjahr 2026 einen
8.057-Jahre-Horizont. Solche Horizonwerte bestimmen Listen, Matrizen, Pfade
und Solverarbeit.

Mandatsjahre sind zwar auf 1900–2200 begrenzt und `MandateUpdate` prüft die
Chronologie, aber nur wenn die beteiligten Felder im selben PATCH vorhanden
sind. Der Router baut vor Persistenz einen Merged-Feature-Input aus
Jurisdiktion, Mortalitäts-, Steuer- und Präferenzfeldern; `retirement_year`
und `life_expectancy_year` fehlen darin. Datenbank-Checks für die
feldübergreifende Chronologie fehlen ebenfalls.

### Risiko

Unplausible Life-Course-Daten können eine wirtschaftlich sinnlose Beratung
erzeugen und zugleich CPU-/Speicherarbeit stark vergrößern. Getrennte PATCHes
können Geburt, Retirement und Lebensende in eine unmögliche Reihenfolge
bringen. UI-Maxwerte schützen weder API noch bestehende/rohe Daten.

### Verbindlicher Fixvertrag

- Geburts- und Ereignisdaten werden als echte ISO-Datums-/Jahrestypen mit
  klarer Partial-Date-Semantik validiert.
- Plausibilität wird relativ zum gesnapshotteten `calculation_as_of` geprüft;
  Future DOB, unmögliche Kalenderdaten und unzulässige Altersbereiche
  blockieren.
- Der Router validiert nach Merge **alle** Life-Course-Felder gegen den
  bestehenden Record; Create, PATCH, Import und Migration teilen denselben
  Validator.
- Datenbank-Constraints sichern darstellbare Reihenfolgen, soweit
  cross-field/cross-table möglich; komplexere Regeln werden atomar in der
  Servicegrenze geprüft.
- Ein fachlicher maximaler Projekthorizont und ein separates technisches
  Work-Budget werden explizit definiert. Ziele außerhalb werden nicht still
  gekappt, sondern blockiert oder als außerhalb des unterstützten Modells
  ausgewiesen.
- `RESOURCE-003`-Admission-Control bleibt zusätzlich erforderlich.

### Abnahmetests

- Malformed, Future, Jahr 9999, Schaltjahr- und Grenzaltersfälle.
- Split-PATCH in jeder Feldreihenfolge sowie parallele PATCHes unter echtem
  PostgreSQL.
- Import/Raw-SQL-Migrationsprüfung für bestehende ungültige Rows.
- Horizon-Max, Goal-beyond-max und kontrollierter 422/409-Vertrag.
- Kein Request kann vor Admission Control Mehrtausendjahresarrays erzeugen.

## `RETIREMENT-CONTEXT-001` – Decumulation-Aktivierung ist an Steuerkonfiguration gekoppelt

### Beobachtung

`should_auto_enable_is()` nennt `is_retired=true` ausdrücklich als
eigenständigen Trigger für Decumulation-/Sequence-of-Returns-Tail-Sampling.
Der produktive Mandatsorchestrator besitzt jedoch keinen separaten
Life-Phase-Resolver. `_run_stochastic_optimizer_pass()` erhält
`is_retired` ausschließlich über das Dict aus `_build_tax_solver_kwargs()`.

Diese Funktion kehrt sofort mit einem leeren Dict zurück, wenn keine
`tax_jurisdiction` gesetzt ist. Erst nach erfolgreicher Tax-Regime-Auflösung
berechnet sie anhand von `retirement_year` und Basisjahr einen einmaligen
Retirementstatus. Die Reproduktion eines bereits pensionierten Mandats ohne
Tax-Setup ergab `{}`.

Direkte Solvertests reichen `is_retired` explizit ein und bestätigen damit den
internen Trigger, prüfen aber nicht den produktiven Mandate→Tax-Helper→Solver-
Callgraph. Der bereits in `TAX-CONTEXT-001` dokumentierte statische Status
bleibt zusätzlich offen.

### Risiko

Zwei sonst identische pensionierte Mandate können allein wegen eines
optionalen Steuerfelds unterschiedliche Tail-Sampling-Aktivierung,
Reasoning-Evidenz und bei endlicher Pfadzahl potenziell unterschiedliche
Optimierungsergebnisse erhalten. Retirement ist damit keine eigenständige
Lebensphase, sondern ein unbeabsichtigter Nebeneffekt des Tax-Resolvers.

### Verbindlicher Fixvertrag

- Retirement-/Decumulation-Context wird in einem steuerunabhängigen
  Life-Course-Resolver vor Tax- und Mortality-Adaptern erzeugt.
- Der Status wird pro Person und Simulationsjahr aus gesnapshotteten
  Ereignissen bestimmt; die steuerliche Verwendung konsumiert diesen Context,
  besitzt ihn aber nicht.
- Importance-Sampling-Entscheidung, TaxContext, Cashflowphase,
  Withdrawal-/Pensionlogik und Disclosure verwenden denselben
  Life-Phase-Snapshot.
- Fehlende Retirementdaten führen zu einem expliziten Unknown-/Defaultvertrag,
  nicht zu einer Abhängigkeit von `tax_jurisdiction`.
- `TAX-CONTEXT-001` wird gemeinsam, aber ohne ID-/Scope-Duplikation behoben.

### Abnahmetests

- Retired/not-retired mit und ohne Tax-Jurisdiktion ergeben denselben
  nichtsteuerlichen IS-Entscheid.
- Retirement innerhalb des Horizonts wechselt die Phase im korrekten Jahr.
- Primary und Partner können verschiedene Retirementereignisse besitzen.
- Tax an/aus verändert ausschließlich Taxwirkung, nicht Life-Phase-Wahrheit.
- Run-/Model-Basis und PDF zeigen die effektive Phase/Transition aus dem
  gespeicherten Snapshot.

## Zielarchitektur: `MortalityAndLifeCourseSnapshot`

Der Audit verlangt nicht zwingend genau diesen Klassennamen, wohl aber einen
gleichwertigen unveränderlichen Vertrag. Eine sinnvolle Struktur ist:

```text
MortalityAndLifeCourseSnapshot
  identity
    id / tenant_id / mandate_id / schema_version / content_hash
    calculation_as_of / timezone / resolver_version

  persons[]
    person_id / role / dob / sex_category / household_role
    retirement_events[] / manual_overrides[] / source_evidence[]

  mortality_model
    jurisdiction / population / period_or_cohort
    vintage / publication_date / source_url / source_hash / qx_hash
    interpolation / extrapolation / terminal_rule / max_age

  stochastic_contract
    rng / seed_domain / substream / n_paths / horizon
    sampling_algorithm / death_index_convention / censoring_rule
    path_state_hash_or_replay_recipe

  economic_state_contract
    flow_rules[]: owner / state / continuation_or_transition
    goal_rules[]: beneficiary / applicability / probability_semantics
    estate_and_survivor_rules_version

  channel_contract
    optimization_basis_id / reporting_basis_id / goal_basis_id
    conditionality / labels / warnings / release_state
```

Große per-path Arrays müssen nicht zwingend als unkomprimierter JSON-Blob
gespeichert werden. Zulässig ist eine vollständig deterministische,
versionierte Replay-Rezeptur plus kanonischer Ergebnis-/Zustandshash. Nicht
zulässig ist ein bloßer Seed ohne Tabelle, Referenzzeit, RNG-Domain und
Algorithmusversion.

## Empfohlene Umsetzungsreihenfolge

### Phase A – Falschclaims und gefährliche Inputs unmittelbar schließen

1. UI-/PDF-Claim auf den tatsächlich mortalitätsadjustierten Kanal begrenzen.
2. Paar/Familie bei aktivierter Einzelpersonenmortalität blockieren oder die
   Begrenzung unübersehbar und maschinenlesbar ausweisen.
3. Geburts-/Life-Course-Daten streng validieren und Horizon-Max/Work-Budget
   einführen.
4. Flag-off darf keinen versteckten Todes-Cutoff mehr erzeugen.

### Phase B – Fachdomäne für Personen, Flows und Goals

1. Person-/Household-IDs und Flow-/Goal-Ownership-Schema migrieren.
2. Post-Death-/Survivor-/Estate-Transitions fachlich festlegen.
3. Applicable-/Survival-/Funding-Wahrscheinlichkeiten typisieren.
4. Unknown Legacydaten fail-closed migrieren oder sichtbar ausgrenzen.

### Phase C – Quellen- und Samplerhärtung

1. Freigegebene BFS-Quelle samt Artefakt, Transformer und Hash registrieren.
2. q(x)-Golden- und Provenienztests aufbauen.
3. Terminal-/Censoring-Mathematik korrigieren und versionieren.
4. Freshness-/Approval-Gate implementieren.

### Phase D – Life-Course-Resolver und Snapshot

1. Planning-Horizon, Life Expectancy, Survival und Retirement fachlich
   trennen.
2. Persistierte PlanningAssumptions und Mandatsfelder auf eine kanonische
   Priorität migrieren.
3. `MortalityAndLifeCourseSnapshot` mit FK-/Hash-/Tenantconstraints bauen.
4. TA und OptimizerRun atomar an denselben Snapshot binden.

### Phase E – Consumer vereinheitlichen

1. Optimizer, Reporting-MC, Goal Analysis und Decumulation aus dem Snapshot
   speisen.
2. Retirement vom Tax-Resolver entkoppeln; Tax konsumiert Life-Phase.
3. Merge nur bei gleicher Snapshot-/Semantikbasis erlauben.
4. API, Frontend, PDF, Signatur und Handoff auf gespeicherte Felder umstellen.

### Phase F – Abnahme

1. Fokussierte Unit-, Property-, Integration-, Browser- und PDF-Tests.
2. Echte PostgreSQL-Constraint-, Split-PATCH-, Race- und Migrationstests.
3. Historischer Replay über Kalender-, Tabellen- und Codeversionen.
4. Vollständiger Backend-/Frontend-/Electron-/Packaging-Gate.

## Definition of Done

Runde 28 ist erst geschlossen, wenn alle folgenden Aussagen wahr sind:

- [ ] Jede produktive Mortality Source besitzt Source-, Artefakt-, q(x)- und
      Transformer-Hash sowie Freigabestatus.
- [ ] Tabellenkalibrierung wird exakt, nicht nur über breite
      Plausibilitätsfenster geprüft.
- [ ] Freshness erkennt verfügbare neuere Quellen und ist produktiv wirksam.
- [ ] Perioden-/Kohortenbasis, Population und Referenzjahre sind sichtbar.
- [ ] Terminalhazard, CDF, Censoring und Todesindex sind mathematisch eindeutig.
- [ ] Startalter 118/119 und Horizon-Grenzen besitzen Golden-Tests.
- [ ] Jede Haushaltsperson besitzt stabile Identität und eigenen Zustand.
- [ ] Jeder Cashflow, Zufluss und jedes Goal besitzt eine Post-Death-
      Klassifikation.
- [ ] Partner-, Haushalts-, Survivor- und Estate-Flows werden nicht pauschal
      durch Tod der Hauptperson beendet.
- [ ] Unsupported Multi-Person-Mortalität blockiert fail-closed.
- [ ] `died_before_due` wird nicht als Zielerfolg gezählt.
- [ ] Applicable-, survival-conditioned und unconditional Funding-
      Wahrscheinlichkeit sind getrennt und reconciliert.
- [ ] Importance-Sampling-Weights gelten in allen Mortalitätsnennern korrekt.
- [ ] Flag an/aus besitzt in allen Kanälen dieselbe definierte Wirkung.
- [ ] Deterministischer Planungshorizont ist kein verstecktes Todesereignis.
- [ ] Decision-, Reporting-MC- und Goal-Kanal referenzieren denselben Snapshot
      oder blockieren bei Inkompatibilität.
- [ ] UI/PDF behaupten nur die tatsächlich aktive Mortalitätslogik.
- [ ] PlanningAssumption-Felder sind wirksam, migriert oder sichtbar inert.
- [ ] Backend und Frontend verwenden eine gemeinsame versionierte Defaultbasis.
- [ ] Primary-/Partner-/Household-Bezug ist je Kennzahl eindeutig.
- [ ] Geburts- und Ereignisdaten sind echte validierte Domänenwerte.
- [ ] Split-PATCH kann keine widersprüchliche Chronologie persistieren.
- [ ] Projekthorizont und Solverarbeit besitzen fachliche und technische Caps.
- [ ] Retirement-/Decumulation-Context ist unabhängig von Tax-Konfiguration.
- [ ] Retirementtransition wird pro Jahr und Person korrekt abgeleitet.
- [ ] Ein immutable MortalityAndLifeCourseSnapshot bindet Mandat, TA und Run.
- [ ] As-of, Source, Algorithmus, RNG-Domain und Zustands-/Replayhash sind
      historisch reproduzierbar.
- [ ] Historical Reload liest keine heutigen Defaults oder Convenience-
      Exporte.
- [ ] Missing-, unknown-, stale-, unapproved-, tampered- und cross-mandate-
      Fälle blockieren fail-closed.
- [ ] API, UI, PDF, Signatur und Handoff zeigen denselben Snapshotstand.
- [ ] SQLite und PostgreSQL besitzen denselben Fachvertrag.
- [ ] Reale PostgreSQL-Race-/Migrationstests sind grün.
- [ ] Vollständiger Backend-/Frontend-/Electron-Gate ist grün.

## Claude-/GPT-Startcheckliste

Vor der Umsetzung muss Claude/GPT diese Reihenfolge einhalten:

1. Diesen Audit vollständig lesen.
2. `F4`, `MC-CONTEXT-001`, `MC-CASHFLOW-CURRENCY-001`,
   `GOAL-PUBLICATION-001`, `RESOURCE-003` und `TAX-CONTEXT-001` mitlesen;
   keine Duplicate-ID erzeugen.
3. Zuerst die Begriffe Planungshorizont, statistische Lebenserwartung,
   Survival-Verteilung, Retirementphase, Survivor und Estate fachlich
   trennen.
4. Vor Sampleränderung Intervall-, Terminal- und Censoring-Konvention als
   Testvektoren festlegen.
5. Vor Schemaänderung Personen-/Flow-/Goal-Ownership und Legacy-Migration
   entscheiden.
6. Falschclaims, Flag-off-Verhalten und ungebremste Inputs zuerst schließen.
7. Bestehende CH-/M/F-Fail-closed-Validierung und gemeinsamen
   OptimizerContext erhalten.
8. Raw Input-Hash erweitern, nicht ersetzen; zusätzlich den aufgelösten
   Mortality-/Life-Course-Hash binden.
9. Retirement nicht im Taxadapter berechnen; der Taxadapter konsumiert den
   gemeinsamen Life-Phase-Context.
10. Goal Probability nie aus einer mortalitätsmaskierten Zahlung ohne
    Applicable-/Survivalzustand ableiten.
11. Reporting-MC nicht allein durch Textänderung als mortalitätsadjustiert
    deklarieren; der produktive Pfad muss die Zustände wirklich konsumieren.
12. Erst nach Source-, Math-, E2E-, Browser-, PDF-, Tamper-, Replay- und echten
    PostgreSQL-Tests einen Blocker als geschlossen markieren.

## Unveränderte Baseline- und Audit-Evidenz

### Repositoryzustand vor Dokumentation

```text
branch: codex/asset-allocation-stochastic-core
HEAD: b769f42b434585cb504a0c86050ec33f88e0ff2e
visible tracked/untracked entries: 0
git status ACL warnings for historical pytest temp directories: 53
global clean claim: intentionally false
```

Die ACL-geschützten historischen `.pytest_tmp*`-/`.pytest-tmp*`-Verzeichnisse
wurden weder betreten noch verändert oder gelöscht. Der Audit behauptet daher
nur einen leeren sichtbaren Status, nicht globale Lesbarkeit oder globale
Sauberkeit.

### Statische Kontrollflussbelege

Die wichtigsten verifizierten Anker sind:

- `services/mortality/bfs.py:1-184` – Quelle, Approximation, Vintage,
  Stale-Helper, q(x), Survival und Lebenserwartung;
- `services/mortality/sampler.py:18-82` – Inverse CDF, Clipping und Todesindex;
- `services/optimizer/solver.py:321-589` – Context, Systemjahr,
  BFS-Sampling und Death-Indices;
- `services/optimizer/scenario_engine.py:406-578` – eine Alive-Mask für
  gesamten Cashflow/Liability;
- `services/optimizer/objective.py:154-175,246-332` – ursprüngliche
  Due-Indices und Goal-Erfolg ohne Alive-/Applicable-Zustand;
- `models/wealth.py:65-183` – Cashflow, WealthInflow, Goal und
  PlanningAssumption ohne Ownershipvertrag;
- `services/portfolio_engine_payload.py:407-503` – einzelner erwarteter
  Todes-Cutoff ohne Flagprüfung;
- `services/portfolio_engine_mc_simulation.py:111-151,1132-1622` –
  ungebremster Horizon und Reporting-MC ohne Mortalität;
- `services/portfolio_engine.py:2237-2543,2552-2791,3679-3736,5907-5970` –
  Raw Snapshot, Model Basis und Merge beider Publikationspfade;
- `models/allocation.py:146-193` und
  `services/portfolio_engine_optimizer_integration.py:1221-1347` –
  unvollständige OptimizerRun-Evidenz;
- `services/planning_horizon.py:9-74` – pauschale Backend-Endalter und
  Partner-Maximum;
- `services/advisory_report.py:796-866` und
  `routers/wealth.py:1211-1322` – eigener Advisory-Horizon-Fallback und
  ausdrücklich deterministische Max-Pension-Spending-Näherung;
- `schemas/clients.py:6-65`, `schemas/mandates.py:47-117` und
  `routers/mandates.py:135-175` – freie Strings und unvollständige
  Merged-Chronologievalidierung;
- `services/optimizer/importance_sampling.py:262-340` und
  `services/portfolio_engine_optimizer_integration.py:132-212,215-364` –
  Decumulation-Trigger und Tax-Kopplung;
- `5eyes-electron/frontend/5eyes_v2.html:3962-4004,4387-4411,7339-7377`
  und `5eyes-electron/frontend/5eyes_v2.html:15041-15081,18530-18556` –
  sichtbare Claims und widersprüchliche Defaults.

### Fokussierter Bestands-Gate

```powershell
python -m pytest -p no:cacheprovider `
  --basetemp=C:\tmp\5eyes-round28-gate-20260907-1 `
  tests\mortality `
  tests\test_bfs_mortality_stale_audit.py `
  tests\test_bfs_mortality_jurisdiction_gate.py `
  tests\test_life_expectancy_projection_horizon.py `
  tests\test_frontend_horizon_life_expectancy.py `
  tests\test_frontend_aa_horizon_control.py `
  tests\test_cholesky_and_horizon.py `
  tests\test_calendar_horizon_contract.py `
  tests\test_cashflow_projection.py `
  tests\test_cashflow_in_mc_integration.py `
  tests\test_goals_conditional_probability_mc_path.py `
  tests\test_goal_scoring_horizon.py `
  tests\test_total_scope_goal_path_contract.py `
  tests\test_monte_carlo_paths.py `
  tests\test_optimizer_is_auto_activation.py `
  tests\test_optimizer_fail_closed_boundaries.py `
  tests\test_optimizer_phase6.py `
  tests\test_engine_input_sensitivity.py `
  tests\test_mandate_api_contracts.py `
  tests\test_schema_validator_hardening.py `
  tests\test_planning_assumption_data_classification_gate.py `
  tests\test_wave13_planning_fx_bounds.py `
  tests\test_frontend_b3_pension_pillar.py `
  tests\test_audit_z6_anchors.py -q

395 passed in 120.18s (0:02:00)
```

Der Gate lief außerhalb der ACL-geschützten historischen Verzeichnisse in
einem neuen, expliziten Basetemp. Er bestätigt den bestehenden Stand, ist aber
kein Nachweis für die in diesem Audit neu verlangten Negativ- und
Kanalverträge.

### Nicht ausgeführte Prüfungen

Nicht durchgeführt wurden:

- Änderung oder Kalibrierung produktiver Mortality-Werte,
- medizinische/aktuarielle Fachfreigabe der BFS-Quelle,
- Browser-DOM-/Electron-Laufzeittest,
- echtes PDF-Rendering mit neuem Mortalitätssnapshot,
- echte PostgreSQL-Split-PATCH-/Race-/Constraintprüfung,
- vollständiger Backend-/Frontend-/Electron-/Packaging-Gate.

Der letzte dokumentierte vollständige Backend-Gate bleibt daher
`6074 passed, 0 failed` auf Implementierungscommit `661fe73c`; er wird durch
diese Read-only-Runde weder ersetzt noch auf den Dokumentations-Head
hochgerechnet.

## Dokumentationsmanifest

Diese Runde darf genau folgende fünf Dokumentationspfade ändern:

1. `docs/audits/2026-09-07-mortality-longevity-retirement-and-decumulation-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Produktcode, Tests, Migrationen, Konfiguration und Abhängigkeiten bleiben
unverändert. Der spätere Dokumentationscommit ist über
`document_commit_resolution` außerhalb des eigenen Dateiinhalts aufzulösen.

## Schlussentscheid

Runde 28 bestätigt keinen neuen P0, aber acht neue P1-Verträge und einen
begrenzten P2-Terminalfall. Mortalitätsadjustierte oder
langlebigkeitsrobuste Beratung bleibt blockiert, bis Quelle, Personen- und
Post-Death-Semantik, Goal-Nenner, Kanalbasis, Life-Course-Inputs,
Retirementrouting und historische Snapshot-Evidenz gemeinsam geschlossen und
auf der Zielumgebung geprüft sind.

Ein isolierter Fix am Sampler, ein neues BFS-Label oder ein zusätzlicher
Disclaimer genügt nicht. Maßgeblich ist der durchgängige Vertrag vom
validierten Haushalt und freigegebenen Quellenartefakt über Zustands- und
Goal-Pfade bis zum exakt selben gespeicherten Ergebnis in API, UI, PDF,
Signatur und Handoff.
