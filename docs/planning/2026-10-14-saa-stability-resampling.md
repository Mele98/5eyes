# SAA-Stabilitaet: Inhalts-Seed, Resampled Efficiency, Signifikanztest gegen die Hausmatrix

## Meta

- ID: SAA-RESAMPLED-STABILITY-001
- Datum: 2026-10-14 (Umsetzung), 2026-10-16 (Abschluss, Messungen, Rebase auf develop 99bcd67)
- Owner: Emanuele Konzelmann (Design freigegeben, siehe "Owner-Vorgaben")
- Branch: `feat/saa-resampled-stability`
- Code: `services/optimizer/resampling.py` (neu), `services/optimizer/solver.py`,
  `services/portfolio_engine_optimizer_integration.py`,
  `services/portfolio_engine_model_basis.py`, `services/portfolio_engine.py` (Zeilen-Delta 0)
- Tests: `tests/test_saa_resampled_stability.py` (neu) plus angepasste Bestandstests (siehe unten)

## Befund

Auf dem Fundament-Beispielmandat (`services/foundation_example.upsert_foundation_example_case`)
haengt die publizierte SAA am Monte-Carlo-Seed. Identische Inputs, nur der Seed variiert
(10 Seed-Salze, alle Laeufe `converged`):

| Pfade | Sigma Aktien | Sigma Immobilien | verschiedene SAAs |
|---|---|---|---|
| 2'000 (Produktion, Messung Auftrag) | 5.4 pp | 6.6 pp | 7 von 10 |
| 8'000 (Messung Auftrag) | 3.7 pp | 4.2 pp | 6 von 8 auf einer Eckloesung |
| 2'000 (Nachmessung 2026-10-16, tmp-DB) | 4.93 pp | 7.06 pp | 6 von 10 |

Zwei Ursachen:

1. **Der Seed hing an Datenbank-IDs.** `deterministic_seed(cma.id, goal_ids, score, horizon, n_paths)`.
   Ein geloeschtes und identisch neu erfasstes Ziel (neue UUID) zog einen anderen Wuerfel --
   und auf diesem flachen Optimum eine andere Strategie.
2. **Das Argmin eines einzelnen Wuerfels ist Stichprobenrauschen.** Die Zielfunktion ist hier
   flach und wegen der Chance-Constraint-Indikatoren stueckweise konstant; der Solver springt
   zwischen nahezu gleichwertigen Ecken. Mehr Pfade helfen nur langsam (2'000 -> 8'000 Pfade:
   Faktor 4 Rechenzeit fuer ~30 % weniger Streuung).

## Owner-Vorgaben (nicht redesignt)

1. Inhalts-Seed statt DB-UUIDs.
2. Michaud-artiges Resampling: K unabhaengige Szenario-Teilstichproben aus Teil-Seeds des
   Inhalts-Seeds, Mittel der optimalen Gewichte, Projektion auf alle harten Constraints mit der
   bestehenden Zulaessigkeits-Maschinerie; Ergebnis muss `evaluate_weights`/Constraint-Checks
   bestehen; Rechenzeit <= ~3x der heutigen Generierung; Streuung je Bucket additiv in
   Audit/Modellbasis.
3. Signifikanztest gegen die Hausmatrix-Zielquote auf dem bestehenden unabhaengigen
   Validierungs-Cube (`_certify_on_independent_validation_cube`), gepaart, einseitig 95 %;
   nicht signifikant -> Hausmatrix-Zielquote mit deutscher Begruendungszeile.
4. Deterministisch; derselbe Pfad fuer Generate, Sensitivity und Nachzertifizierung.

## Methode

### 1. Inhalts-Seed (`solver.optimizer_content_seed`)

SHA-256 (ueber das bestehende `deterministic_seed`) aus:

- `OPTIMIZER_SEED_SCHEME = "content_seed_v1"` und `OPTIMIZER_ENGINE_VERSION = "saa_resampled_v1"`
  (eine neue Engine-Version zieht bewusst neue Wuerfel),
- `scenario_inputs_digest(ScenarioInputs)` -- mu, sigma, Schiefe, Kurtosis und Cholesky der
  Korrelation, also CMA-Werte **inklusive Sub-Klassen-Annahmen und Korrelationsstruktur**
  (die Inputs werden mit den kanonischen Sub-Allokationen gebaut),
- die wirtschaftlichen Goal-Felder (`GOAL_ECONOMIC_FIELDS`: Familie, Typ, Scope, Rang, Gewicht,
  Haerte, Wertmodus, Betraege, Renditeziel, Mindest-Erfolgswahrscheinlichkeit, Daten, Horizont,
  Frequenz, Saeule, Aktiv-/Einschluss-/Lifecycle-Status), je Ziel kanonisch als JSON, die Liste
  sortiert -- **ohne** `id`, `mandate_id`, `label`, `notes`, `linked_position_id`, Zeitstempel,
- `score_x10`, Optimierungs- und Szenario-Horizont, `n_paths`.

Die Goal-Sensitivity nutzt `sensitivity_content_seed` = derselbe Inhalts-Seed plus Salz
`("sensitivity", <Fingerabdruck des variierten Ziels>)`. Baseline und Variante teilen ihn
weiterhin (Common Random Numbers, GOAL-SENSITIVITY-COMMON-BASELINE-001); die Slider-Deltas und
`target_goal.id` gehen nicht ein (strukturell getestet).

Der Fallback-Pfad in `_run_stochastic_optimizer_pass` (technischer Solver-Fehler) weist den
Inhalts-Seed des bereits gebauten Contexts aus, sonst 0 -- nie mehr einen ID-Seed.

### 2. Resampled Efficiency (`solver._run_resampled_solver`)

- `n_bags = 40` Teil-Seeds `bag_seeds(content_seed, 40)` (SHA-256 mit eigener Domain).
- Je Bag ein unabhaengiger Wuerfel mit `bag_n_paths = 500` Pfaden (nie mehr als der
  Hauptwuerfel), gleiche Verteilung, gleiche Importance-Sampling-Entscheidung, auf dem
  gemeinsamen Szenario-Horizont gezogen und auf den Optimierungshorizont gekuerzt; der
  Bag-Context entsteht ausschliesslich aus dem Haupt-Context (`_bag_context`), damit Generate,
  Sensitivity und jede Nachbewertung per Konstruktion dieselben Bags sehen.
- Auf jedem Bag laeuft die **unveraenderte** bisherige Auswahl-Logik (Multi-Start-SLSQP,
  DE-Fallback, Stage-9-Robustifizierung), nur aus `run_solver` nach `_select_cube_candidate`
  herausgeloest.
- Mittel der Bag-Gewichte; Streuung je Bucket = Standardabweichung ueber die Bags
  (`dispersion_bps`), Standardfehler des Mittels (`standard_error_bps`).
- Projektion auf {Bandbreiten inkl. Reserve-Untergrenze und Illiquiditaets-Caps, Risikobudget,
  Summe = 1} (`_project_onto_feasible_set`, euklidisch via SLSQP auf exakt
  `context.bounds`/`context.scipy_constraints`). Die Menge ist konvex (Box + lineare
  Ungleichung + lineare Gleichung), der Mittelwert zulaessiger Punkte ist selbst zulaessig --
  in allen Messungen war `projection_distance_bps = 0.0`; die Projektion ist eine Absicherung.
- Weniger als 50 % erfolgreiche Bags oder keine zulaessige Projektion -> bestehender
  House-Matrix-Fallback (OD-5) mit Begruendung.
- Abschluss (Rundung, Status, Nachzertifizierung auf dem unabhaengigen Validierungs-Cube,
  Stress, Audit) unveraendert in `_finalize_solver_result`, bewertet auf dem Hauptwuerfel.
  `evaluate_weights(result.context, result.weights_bps).feasible` ist getestet.
- Ein einzelner robustifizierter Bag macht den Lauf `converged_robustified` (sichtbar statt
  im Mittel versteckt).
- Einzelwuerfel-Altpfad bleibt nur fuer Vergleichsmessungen (`resampling=SINGLE_CUBE`); kein
  produktiver Aufrufer setzt ihn.

### 3. Signifikanztest gegen die Hausmatrix (`solver._significance_vs_house_anchor`)

- Anker: die Hausmatrix-Zielquote des Generierungslaufs (`targets` nach Praeferenzen,
  Exposure-/Ziel-/Reserve-Tilts), uebergeben als `house_anchor_bps`; projiziert auf dieselben
  harten Constraints wie der Kandidat (z.B. fixiert die Reserve-Untergrenze die Liquiditaet).
  Ohne explizite Uebergabe: target-Spalten der Hausmatrix-Zeile; fehlt auch die, entfaellt der
  Test sichtbar (`decision = optimizer_untested`, Grund im Audit) statt einen Anker zu erfinden.
- Cube: exakt der Validierungs-Cube der Nachzertifizierung (`_build_validation_context`,
  Seed `content_seed + 1'000'003`, gleiche Pfadzahl). Die Konstruktion ist jetzt EINE Funktion,
  die Nachzertifizierung und Test gemeinsam nutzen.
- Test: **gepaarter Bootstrap, einseitig, alpha = 5 %, B = 400.** Begruendung, warum kein
  gepaarter t-Test: die Zielfunktion ist kein Mittelwert pfadweiser Verluste -- die
  Chance-Constraint-Strafe ist quadratisch in der Wilson-Untergrenze einer Erfolgsquote. Ein
  t-Test auf pfadweisen Differenzen waere nicht dieselbe Groesse, die optimiert wird. Der
  Bootstrap zieht Pfadindizes mit Zuruecklegen und wertet auf DENSELBEN Indizes fuer Anker und
  Kandidat die vollstaendige Zielfunktion neu aus (inkl. Soft-Preference-Strafe, gleicher
  Vertrag wie `evaluate_weights`) -- das ist die Paarung je Pfad. Signifikant genau dann, wenn
  die Punktschaetzung der Verbesserung `L(Anker) - L(Kandidat)` > 0 UND das untere
  5-%-Perzentil der Bootstrap-Verteilung > 0. p-Wert = (1 + #{Replikate <= 0}) / (1 + B), also
  nie 0 (Untergrenze 1/401 = 0.0025). Bootstrap-Seed aus dem Validierungs-Seed (deterministisch).
- Entscheid: `optimizer` (signifikant) / `house_matrix` (nicht signifikant oder identisch) /
  `optimizer_untested`. Begruendungszeile z.B. "Optimierer-Abweichung von der Hausmatrix ist
  statistisch nicht signifikant; Hausmatrix-Zielquote beibehalten. Gepaarter Bootstrap
  (B=400, einseitig, alpha=5%) auf dem unabhaengigen Validierungs-Cube (2000 Pfade): ...".

### 4. Determinismus und ein Pfad fuer alle Aufrufer

- Generate (`_run_stochastic_optimizer_pass`), Goal-Sensitivity (`evaluate_goal_sensitivity`)
  und die Nachzertifizierung laufen alle durch `run_solver` -> `_run_resampled_solver`.
- Die Sensitivity testet gegen DENSELBEN Anker wie die aktive Strategie
  (`sensitivity_house_anchor_bps`: persistierter Anker der aktiven Allokation, sonst die live wie
  in Generate aufgebaute Zielquote; Alt-Allokation ohne Anker -> Hausmatrix-Zeile).
- Identischer Inhalt -> bitidentisches Ergebnis inkl. Resampling-Audit (getestet, ausser
  Laufzeiten).

### Persistenz (additiv, schema-kompatibel)

- `OptimizerResult.resampling` (neu, Default None).
- `effective_constraints_json.optimization_model_basis.resampling` (nur frische stochastische
  Basis; zurueckgespielte Basen bleiben wortgetreu): Schema, Seed-Schema, Engine-Version,
  Inhalts-Seed, Bag-Zahlen, Mittel/Streuung/Standardfehler je Bucket, Projektionsabstand,
  Kandidat, Endgewichte, Entscheid sowie der Signifikanzblock (Anker roh/projiziert, Statistik,
  Validierungs-Seed/-Hash). Bewusst NICHT: Laufzeiten und Einzel-Bags (nicht deterministisch
  bzw. Umfang). Geht damit in den `allocation_context_hash` ein.
- `OptimizerRun.restart_results_json`: eine Zeile je Bag mit denselben Schluesseln wie die
  bisherige Start-Diagnose (`attempt, stage="resampling_bag", status, reason, objective_value,
  feasible_candidate, n_paths, n_starts, seed, elapsed_ms`) plus `bag`, `iterations`,
  `weights_bps`.
- `model_basis` ist in den Response-Schemas ein freies `dict`; es gibt keine TS-Typen fuer
  diese Felder -- kein Schema-Drift.

## Parameter

| Parameter | Wert | Begruendung |
|---|---|---|
| `n_bags` | 40 | Streuung des Mittels ~ 1/sqrt(K); 40 Bags -> < 1 pp je Bucket (gemessen) |
| `bag_n_paths` | 500 | Streuung je Bag ~4-5 pp, kaum abhaengig von der Bag-Groesse; zu kleine Bags verschieben das Optimum (Wilson-Untergrenze haengt von n ab) |
| `MIN_SUCCESSFUL_BAG_SHARE` | 0.5 | weniger -> kein belastbares Mittel -> House-Fallback |
| `significance_alpha` | 0.05 einseitig | Owner-Vorgabe 95 % |
| `n_bootstrap` | 400 | p-Aufloesung 0.0025; Laufzeit < 1 s |

## Messungen (Fundament-Beispielmandat, frische tmp-DB, 2'000 Pfade, 10 Seed-Salze)

Skript: `scratchpad/stab2/measure.py` (nicht im Repo; patcht `solver.deterministic_seed` mit
einem Salz, ruft `generate_target_allocation` End-to-End).

| | Aktien | Obligationen | Immobilien | Alternative | Liquiditaet |
|---|---|---|---|---|---|
| **Vorher** (Einzelwuerfel) Mittel % | 69.01 | 11.28 | 13.50 | 3.70 | 2.51 |
| Vorher Sigma pp | **4.93** | 1.92 | **7.06** | 2.21 | 0.00 |
| Vorher min..max % | 64.5..75.0 | 10.0..14.5 | 5.0..20.0 | 3.0..10.0 | 2.51 |
| **Nachher** (40 Bags x 500) Mittel % | 67.35 | 11.41 | 15.68 | 3.06 | 2.51 |
| Nachher Sigma pp | **0.76** | 0.40 | **0.77** | 0.05 | 0.00 |
| Nachher min..max % | 66.5..68.9 | 10.9..12.3 | 14.1..16.6 | 3.0..3.1 | 2.51 |

- Ziel "Sigma je Bucket < 1 pp ueber 10 Salze": erfuellt (max 0.77 pp).
- Vorher 6 verschiedene SAAs in 10 Laeufen, davon 5 auf derselben Ecke (64.5/10/20/3/2.5);
  nachher 10 verschiedene, aber alle innerhalb +/- 1.6 pp um das Mittel.
- Entscheid in allen 10 Laeufen `optimizer` (p = 0.0025, Untergrenze der Verbesserung klar > 0).
- Identisch neu erfasstes Ziel -> identischer Seed, identische SAA (Test
  `test_seed_does_not_depend_on_database_ids`).
- Ein Bag allein streut ~4-5 pp (Aktien/Immobilien), 40 Bags -> ~0.8 pp: konsistent mit 1/sqrt(40).
- 20 Bags zum Vergleich (gleiche 10 Salze): Sigma Aktien 1.37 pp / Immobilien 1.37 pp, Generate
  8.4 s (1.6x) -- verfehlt das 1-pp-Ziel. 40 Bags sind die kleinste gepruefte Zahl, die es erreicht;
  60+ Bags wuerden das 3x-Laufzeitbudget ueberschreiten.

### Laufzeit

| | Generate gesamt | davon `run_solver` |
|---|---|---|
| Vorher | 5.1 s | 0.4 s |
| Nachher | 12.3 s | 7.5 s |
| Faktor | **2.4x** (Budget <= 3x) | |

(Windows-Entwicklungsrechner, geteilte Maschine, Mittel ueber 10 Laeufe.) Die Goal-Sensitivity
faehrt zwei Solver-Laeufe und wird entsprechend um ~2 x 7 s langsamer.

## Golden-Snapshots (CH) -- Begruendung je Datei

Alle sechs Fixtures unter `tests/fixtures/golden_ch_recommendations/` neu eingefroren. Ursache
in jedem Fall ausschliesslich die Methodenaenderung (Inhalts-Seed + Resampling +
Signifikanzentscheid); Produktauswahl, Reihenfolge, Positionszahl, Methode/Status und
engine_version sind unveraendert. Alle Laeufe: 40/40 Bags erfolgreich, Projektionsabstand 0,
Status `converged`.

Linux-Runner nicht verfuegbar (Branch ohne PR loest kein CI aus). Ersatzkontrolle: lokal mit
Thread-Pinning je einmal unter `OPENBLAS_CORETYPE=Haswell` und `=Nehalem` (die beiden
Kernel-Familien hinter den zwei frueheren CI-Auspraegungen) erzeugt -- **alle sechs Dateien
byte-identisch**. **CI-Lauf beim PR muss das bestaetigen.**

| Fixture | Entscheid (p) | Ziel vorher -> nachher (Aktien/Obl/Immo/Alt/Liq, %) | Begruendung |
|---|---|---|---|
| `bucket3_defensiv_default_prefs` | optimizer (0.0025) | 0/90.74/0/4.94/4.32 -> 0/89.70/0/5.69/4.61 | Bag-Mittel statt einer Ecke; Alternative +0.75 pp, Obl -1.0 pp; Hausmatrix-Anker 0/95/0/3/2 signifikant schlechter |
| `bucket5_ausgewogen_default_prefs` | optimizer (0.0025) | 40/45/9/3/3 -> 46.38/38.13/8.85/4.17/2.47 | Vorher ein Einzelwuerfel-Ergebnis auf runden Eckwerten; das Bag-Mittel liegt innen, Aktien +6.4 pp. Implementierungsschritte 4 -> 5 ("Aktien aufbauen" neu) |
| `bucket7_wachstum_default_prefs` | **house_matrix (0.64)** | 60/25/10/3/2 -> **68/16/8/6/2** | Alle 40 Bags waehlen dieselbe Ecke wie vorher (Streuung 0), aber auf dem unabhaengigen Validierungs-Cube ist sie NICHT besser als die Hausmatrix-Zielquote (Bootstrap-Verbesserung in 64 % der Replikate <= 0) -> Hausmatrix-Zielquote publiziert. Aktien +8 pp |
| `bucket9_dynamisch_default_prefs` | **house_matrix (0.13)** | 75/15/6/2/2 -> **79/8/7/4/2** | Wie bucket7: einstimmige Ecke, Verbesserung nicht signifikant -> Hausmatrix. Aktien +4 pp |
| `bucket5_ausgewogen_equities_global` | optimizer (0.0025) | 46.12/33.98/12.13/5.34/2.43 -> 48.04/36.98/8.53/4.12/2.33 | Bag-Mittel; Immobilien -3.6 pp, Obl +3 pp, TER 28 -> 26 bps |
| `bucket5_ausgewogen_chfonly_em_focus` | optimizer (0.0025) | 47.5/42.5/5/3/2 -> 47.25/37.54/8.81/4.06/2.34 | Bag-Mittel; Immobilien +3.8 pp, Obl -5 pp; `limiting_factor` liquiditaetsreserve -> bandbreite, TER 23 -> 24 bps |

**Kundensichtbar und fachlich zu beachten:** bei Score 7 und 9 steigt die publizierte
Aktienquote auf die Hausmatrix-Zielquote (+8 bzw. +4 pp), weil die Optimierer-Abweichung davon
statistisch nicht belegt ist. Das ist genau die freigegebene Regel ("nicht signifikant ->
Hausmatrix"), aber es ist eine Risikoerhoehung gegenueber dem bisherigen Output. Die
Hausmatrix-Zielquote liegt innerhalb aller harten Constraints (Risikobudget, Bandbreiten).

## Angepasste Bestandstests (mit Begruendung)

- `test_optimizer_context.py::test_build_context_seed_none_uses_content_seed_not_database_ids`
  (ersetzt `..._uses_deterministic_seed`): pinnte die ID-Formel; pinnt jetzt ID-Unabhaengigkeit
  und Inhaltsabhaengigkeit.
- `test_goal_sensitivity_common_baseline_seed_leaks_delta.py`: Aufrufstelle heisst jetzt
  `sensitivity_content_seed(`; zusaetzlich darf keine `.id` im Seed-Aufruf stehen.
- `test_optimizer_solver.py::test_solver_hard_pension_more_conservative_than_maximierung`:
  vergleicht die Optimierer-Kandidaten (`resampled_weights_bps`). Beim harten Pensionsziel ist
  die Verbesserung gegenueber der Hausmatrix auf 300 Pfaden nicht signifikant (p ~ 0.11) ->
  publiziert wird bewusst die Hausmatrix (60 % Aktien); die Richtung der Zielfunktion, die der
  Test pinnt, steckt im Kandidaten (45 % vs. 45 %).
- `test_optimizer_solver.py::test_solver_restart_results_include_stage9_audit_fields`: laeuft
  auf `SINGLE_CUBE` (Stage-9-Start-Diagnose der Auswahl, die in jedem Bag identisch laeuft);
  neu `test_resampled_restart_results_have_one_row_per_bag` fuer den Produktionspfad.
- `test_optimizer_runs.py` (2 Tests): erste `restart_results`-Zeile ist der erste Bag; ihr
  Seed ist `bag_seeds(run.seed, ...)[0]`.

## Offen / nicht Teil dieses Auftrags

- `services/portfolio_engine.py`: diese Branch aendert die Zeilenzahl nicht (Delta 0). Nach dem
  Rebase auf develop 99bcd67 (#618, Extraktion der Allocation-Integritaetspruefung) steht die
  Datei bei 6'937/7'100 Zeilen, das Budget-Gate ist gruen.
- `engine_version` der Allokation bleibt `stochastic_core_v2`; die Methode ist ueber
  `optimization_model_basis.resampling.scheme/engine_version` versioniert.
- Validierungs-Cube nutzt weiterhin `context.n_paths` (2'000); der Owner-Entscheid 4c
  (20'000 Validierungspfade) ist davon unabhaengig und hier nicht umgesetzt.
