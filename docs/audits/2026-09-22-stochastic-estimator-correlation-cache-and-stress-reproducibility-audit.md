---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-stochastic-estimator-correlation-cache-stress-reproducibility-followup-audit"
status_as_of: "2026-09-22"
audit_started_on: "2026-09-22"
audit_completed_on: "2026-09-22"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "e883bb9f0b5e4e8908de627a5c0e80d27a1a667e"
prior_release_audit_path: "docs/audits/2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md"
prior_stress_audit_path: "docs/audits/2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-09-22-stochastic-estimator-correlation-cache-and-stress-reproducibility-audit.md"
audit_mode: "read_only_static_numerical_estimator_correlation_factor_cache_stress_and_reproducibility_review_plus_deterministic_python_reproductions_and_focused_pytest_gate"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "importance-sampling reliability and horizon semantics, effective sample size, singular-PSD correlation factors, main-Monte-Carlo parity, stress replay context, scenario-cache ownership and exact shift-vector behavior"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 2
confirmed_prior_p1_extension_groups: 1
new_hardening_p2_count: 2
deterministic_reproduction_groups: 5
focused_existing_tests_passed: 226
focused_existing_tests_skipped: 0
focused_existing_tests_failed: 0
focused_existing_test_runs_confirmed: 1
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "replace the fixed long-horizon IS proposal with one horizon- and event-correct estimator contract that computes and gates ESS and prefix likelihood ratios; consume generic PSD factors as full matrices in every engine; replay stress through the retained optimizer context with cashflow-neutral market drawdown; make cached scenario arrays immutable and honor the exact requested shift vector; then bind diagnostics, factor identity, scenario hashes and fallback verdict to StochasticRunEvidence"
---

# Stochastik-, Estimator-, Korrelations-, Cache- und Stress-Reproduzierbarkeitsaudit

## Geltung, Abgrenzung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die vierunddreißigste Read-only-
Kontrollrunde. Sie wurde am 22. September 2026 gegen den unveränderten
Repository-Head `e883bb9f0b5e4e8908de627a5c0e80d27a1a667e`
durchgeführt. Produktcode, Tests, Migrationen und Runtime-Konfiguration wurden
nicht verändert. Nach Abschluss der Prüfung werden ausschließlich die fünf im
Dokumentationsmanifest genannten Dokumentationspfade angepasst.

Die Runde vertieft bewusst den mathematischen Kern des Vortagsaudits. Geprüft
wurden:

1. die endliche Stichprobengüte des produktiven Importance Sampling,
2. die Likelihood-Ratio-Semantik bei gemeinsam gezogenen, aber verschieden
   langen Sensitivitätshorizonten,
3. die Behandlung positiver semidefiniter, aber singulärer
   Korrelationsmatrizen in Optimizer und Haupt-Monte-Carlo,
4. der Modellkontext der nachgelagerten Solver-Stressauswertung,
5. sowie Ownership, Mutierbarkeit und Parameterwahrheit des Szenario-Caches.

Dieser Audit ersetzt keine Finding-ID des
[Stochastic-/Optimizer-/MC-/Goal-Audits vom 21. September](2026-09-21-stochastic-optimizer-monte-carlo-asset-allocation-and-goal-integrity-audit.md).
Insbesondere bleibt `OPTIMIZER-IS-EVIDENCE-001` dort der Vertrag für die
Parität zwischen Objective, Goal Drivers, Probability und Quantilen. Der neue
`OPTIMIZER-IS-ESS-001` bewertet dagegen, ob der gemeinsame gewichtete
Estimator überhaupt eine ausreichende effektive Stichprobe und den richtigen
Zeithorizont besitzt.

Für Aussagen zum Stressmodell bleiben die stabilen IDs aus dem
[Stress-Replay-/Policy-A/B-Audit vom 28. August](2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md)
maßgeblich. Die neue Evidence erweitert `STRESS-CONTEXT-001` und
`STRESS-SCENARIO-001`; sie erzeugt keine konkurrierende ID.

Aktueller Code, ausgeführte Reproduktionen und Tests haben Vorrang bei der
Beschreibung des Ist-Stands. Für den Zielvertrag gilt dieser Audit vor älteren
Handoffs. Grüne Bestandstests belegen vorhandene Positivkontrollen, nicht die
Abwesenheit der hier mit neuen Gegenbeispielen gezeigten Fehlerklassen.

## Kurzurteil

Die geprüfte Engine ist deterministisch wiederholbar, besitzt eine saubere
Grundformel für Likelihood Ratios und akzeptiert bewusst allgemeine gültige
PSD-Korrelationen. Genau an den Übergängen dieser Bausteine entstehen jedoch
zwei neue release-blockierende P1-Verträge:

1. **`OPTIMIZER-IS-ESS-001`:** Der feste Equity-Mean-Shift von `-0.5`
   Standardabweichungen wird in jedem Jahr erneut angewendet, während die
   produktive Pfadzahl bei 2.000 bleibt und weder Effective Sample Size noch
   Konzentration der normalisierten Gewichte geprüft werden. Bereits bei 20
   Jahren fällt die mediane ESS im Repro auf rund 45, bei 30 Jahren auf rund
   19 und bei 40 Jahren auf rund 8. Ein produktionsnahes defensives
   30-Jahres-Portfolio zeigt dadurch eine 61-fach höhere Seed-zu-Seed-
   Standardabweichung seines erwarteten Endvermögens als Standard-MC. Bei
   gepaarten Sensitivitätsläufen werden außerdem zwar die Return-Pfade auf den
   kürzeren Horizont geschnitten, die Likelihood Ratios aber über den längeren
   gemeinsamen Würfel belassen. Ein Einjahres-Schätzer wird so von 29 späteren,
   fachlich irrelevanten Innovationsjahren gewichtet; sein Repro-Fehler steigt
   um Faktor 9.
2. **`MC-PSD-FACTOR-001`:** Die zentrale CMA-Validierung akzeptiert singuläre
   PSD-Korrelationen und liefert dafür korrekt einen allgemeinen Eigenfaktor
   `F` mit `F @ F.T == C`. Der Haupt-Monte-Carlo-Consumer multipliziert diesen
   Faktor dennoch wie eine untere Cholesky-Matrix und ignoriert alle Elemente
   oberhalb beziehungsweise rechts der angenommenen Dreiecksstruktur. Für
   eine gültige 5x5-All-ones-Korrelation werden vier Assetinnovationen zu exakt
   null, obwohl alle fünf identische Standardnormal-Schocks besitzen müssten.

Zusätzlich bestätigt die Runde zwei Erweiterungen der bereits offenen
Stressverträge: Die Solver-Stressauswertung übernimmt weder Steuer- noch
Mortalitäts-/Lebensphasenkontext und berechnet „Max Drawdown“ auf einem von
Cashflows und Liabilities bewegten Vermögenspfad. Geplante Entnahmen können
damit als Markteinbruch erscheinen.

Zwei P2-Härtungsverträge sind ebenfalls reproduziert: Der Szenario-Cache gibt
dieselben schreibbaren NumPy-Objekte an alle Consumer zurück, und seine
öffentliche IS-Funktion verwendet den angeforderten Shift-Vektor nur im
Cache-Key. Für die Berechnung reduziert sie ihn auf den maximalen Absolutwert
und erzeugt stets den internen negativen Equity-Default. Unterschiedliche
Richtung und Assetklasse liefern deshalb identische Pfade und Gewichte.

Es wurde kein neuer P0 bestätigt. Eine Releasefreigabe ist wegen der beiden
neuen P1 und der bereits offenen P1 weiterhin ausgeschlossen.

## Stabiles Findings-Register

| ID | Prio | Status | Kernaussage |
|---|---:|---|---|
| `OPTIMIZER-IS-ESS-001` | P1 | neu bestätigt | Fester jährlicher Shift und 2.000 Pfade kollabieren bei langen Horizonten auf sehr geringe ESS; es gibt kein Reliability-Gate. Kürzere gepaarte Runs behalten zusätzlich die Likelihood Ratio des längeren Würfels. |
| `MC-PSD-FACTOR-001` | P1 | neu bestätigt | Ein korrekter allgemeiner Eigenfaktor für gültige singuläre PSD-Korrelationen wird im Haupt-MC fälschlich als untere Dreiecksmatrix konsumiert. |
| `OPTIMIZER-IS-EVIDENCE-001` | P1 | offen, nicht dupliziert | Der Vortagsaudit fordert weiterhin denselben gewichteten Estimator für Objective, Contributions, Probability und Quantile. Der neue ESS-Vertrag kommt davor als Reliability-Voraussetzung. |
| `STRESS-CONTEXT-001` / `STRESS-SCENARIO-001` | P1 | bestehend, neue Evidence | Solver-Stress verliert Tax-/Mortality-/Life-Course-Kontext und vermischt Market Drawdown mit geplanten Flows. |
| `SCENARIO-CACHE-IMMUTABILITY-001` | P2 | neu bestätigt | Cache-Hits teilen schreibbare Pfad- und Gewichtsobjekte; eine Consumer-Mutation vergiftet alle späteren Runs desselben Keys. |
| `SCENARIO-IS-SHIFT-CONTRACT-001` | P2 | neu bestätigt | Der IS-Cache keyt den vollständigen Shift-Vektor, wendet aber nur dessen maximalen Betrag auf den internen negativen Equity-Default an. |

Keine bestehende Finding-ID wird durch diesen Audit geschlossen.

## Ende-zu-Ende-Systembild

```text
Mandat / Goals / CMA
         |
         v
Auto-IS-Entscheidung
  score <= 30 oder retired oder hartes Goal
         |
         v
fester Shift [-0.5, 0, 0, 0, 0] pro Jahr
         |
         +------------------------------+
         |                              |
         v                              v
Return-Würfel T_common          Pfad-Likelihood über T_common
         |                              |
         v                              |
Slice auf T_run < T_common              |
         +---------------+--------------+
                         v
          Objective / Probability / Quantile
              ohne ESS-/Konzentrations-Gate

CMA-Korrelation C (PSD, ggf. singulär)
         |
         v
generischer Faktor F mit F F^T = C
         |
         +------------------------------+
         |                              |
         v                              v
Optimizer: vollständiges F @ z   Haupt-MC: nur j <= i
         |                              |
         v                              v
korrekte Kovarianz               falsche Kovarianz bei Eigenfaktor
```

Die beiden P1 sind damit keine UI- oder Rundungsfehler. Sie verändern die
statistische Aussage beziehungsweise die tatsächlich simulierte gemeinsame
Verteilung vor jeder späteren Goal-, Allocation- oder Publikationslogik.

## Positivkontrollen, die erhalten bleiben müssen

1. `compute_likelihood_weights()` verwendet im aktuellen IS-Call-Site die
   tatsächlich gezogene Proposal-Stichprobe; der frühere globale
   Normalisierungsfehler ist behoben.
2. Standard-MC und IS verwenden deterministische Seeds und reproduzierbare
   NumPy-Generatoren.
3. Der Optimizer multipliziert den Korrelationsfaktor als vollständige Matrix
   und behandelt dadurch auch allgemeine PSD-Faktoren korrekt.
4. Die zentrale CMA-Validierung prüft Shape, Endlichkeit, Symmetrie,
   Diagonale, Wertebereich und positive Semidefinitheit.
5. Positiv definite Korrelationen behalten den historischen unteren
   Cholesky-Faktor; nur singuläre gültige Matrizen benötigen den allgemeinen
   Eigenfaktor.
6. Gepaarte Sensitivitäten ziehen bewusst einen gemeinsamen maximalen
   Return-Würfel, sodass überlappende Zufallsschocks bytegleich sind. Die
   Reparatur darf diese Common-Random-Numbers-Eigenschaft nicht verlieren.
7. Solver und `evaluate_weights()` können denselben `OptimizerContext`
   wiederverwenden. Dieser Kontext ist der richtige Ort für eine unveränderliche
   Estimator- und Reliability-Evidence.
8. Der Haupt-MC berechnet seinen normalen Max Drawdown bereits über einen
   cashflow-neutralen Marktindex. Dieselbe Semantik kann im Stresspfad
   wiederverwendet werden.
9. Die CMA-Pflege erzeugt bei normalen Admin-Updates neue versionierte IDs;
   dieser Audit behauptet daher keinen produktiven Same-ID-CMA-Updatefehler.

## Codeanker des auditierten Stands

### Importance Sampling und gemeinsamer Horizont

- `5eyes-backend/services/optimizer/importance_sampling.py:70-71` definiert
  den Default-Shift mit Stärke `0.5` und negativer Equity-Richtung.
- `5eyes-backend/services/optimizer/importance_sampling.py:99-136` bildet
  eine einzige Pfad-Likelihood aus der Summe über alle Jahre.
- `5eyes-backend/services/optimizer/importance_sampling.py:245-340` aktiviert
  IS standardmäßig automatisch bei `score_x10 <= 30`, Retirement oder einem
  harten Ziel. Das Problem betrifft damit normale Produktkontexte.
- `5eyes-backend/services/optimizer/scenario_engine.py:275-304` wendet den
  gleichen Shift in jedem Jahr an und berechnet genau ein skalares Gewicht je
  vollständigem Pfad.
- `5eyes-backend/services/portfolio_engine.py:2203-2204` setzt produktiv 2.000
  Optimizerpfade.
- `5eyes-backend/services/optimizer/solver.py:364-372` erlaubt einen
  `scenario_horizon_years`, der länger als der konkrete Run-Horizont ist.
- `5eyes-backend/services/optimizer/solver.py:493-522` erzeugt Pfade und
  Gewichte über den gemeinsamen Horizont, schneidet anschließend aber nur die
  Return-Pfade. `scenario_weights` bleiben unverändert vollhorizontig.
- `5eyes-backend/services/portfolio_engine.py:5276-5315` verwendet diesen
  Mechanismus im produktiven Goal-Sensitivity-Pfad für Baseline und Änderung.
- Im geprüften Code existieren weder ESS, maximale normalisierte
  Gewichtskonzentration, Weight-Entropy, Reliability-Verdict noch ein
  adaptiver Standard-MC-/Mixture-Fallback.

### Korrelation und Haupt-Monte-Carlo

- `5eyes-backend/services/cma_validation.py:264-328` akzeptiert ausdrücklich
  gültige positive semidefinite, also auch singuläre Korrelationen.
- `5eyes-backend/services/cma_validation.py:350-369` gibt bei positiver
  Definitheit Cholesky, sonst einen allgemeinen Eigenfaktor
  `eigenvectors @ diag(sqrt(eigenvalues))` zurück.
- `5eyes-backend/services/portfolio_engine_cma.py:189-217` reicht diesen
  generischen Faktor aus `_build_cholesky_from_cma()` weiter und dokumentiert
  die Erhaltung singulärer PSD-Abhängigkeiten.
- `5eyes-backend/services/portfolio_engine_mc_simulation.py:1185` übernimmt
  den Faktor; `:1380-1382` summiert trotzdem nur `j in range(i + 1)` und setzt
  damit fälschlich Dreiecksstruktur voraus.
- `5eyes-backend/services/optimizer/scenario_engine.py:189-191` und
  `:295-297` verwenden demgegenüber korrekt alle Quellendimensionen.

### Stress und Cache

- `5eyes-backend/services/optimizer/solver.py:132-198` hält den vollständigen
  Tax-, Dividend-, Alter-, Retirement- und Mortality-Kontext für den
  eigentlichen Optimizerlauf.
- `5eyes-backend/services/optimizer/solver.py:1595-1619` ruft die
  Stressauswertung nach dem Solver mit rohen Funktionsargumenten auf und stuft
  jeden Fehler als nicht blockierendes „nice-to-have“ ein.
- `5eyes-backend/services/optimizer/stress_scenarios.py:110-160` reicht nur
  Wealth, Allocation, Returns, Cashflows und Liabilities an
  `simulate_wealth_paths()` weiter. Tax-Regime, Dividend Yields, Basisjahr,
  Alter, Retirement und Death-Indices fehlen. Drawdown wird direkt aus dem
  flowbewegten Wealth-Pfad berechnet.
- `5eyes-backend/services/portfolio_engine_mc_simulation.py:1360-1419` und
  `:1493-1508` zeigen die bereits vorhandene cashflow-neutrale
  Marktindexmethodik des Haupt-MC.
- `5eyes-backend/services/optimizer/scenario_cache.py:69-84`, `:145-167` und
  `:220-246` speichern und liefern die originalen Array-/Tuple-Objekte ohne
  defensive Kopie oder Read-only-Flag.
- `5eyes-backend/services/optimizer/scenario_cache.py:170-245` nimmt einen
  vollständigen `shift_vector` entgegen und keyt ihn, ruft die Engine aber nur
  mit `max(abs(shift_vector))` auf. Die Engine baut danach ihren Default-
  Equity-Shift neu auf.

## `OPTIMIZER-IS-ESS-001` – Langhorizontiger Gewichtszerfall ohne Reliability-Gate

### Mathematischer Vertrag

Für normalisierte Importance-Sampling-Gewichte ist die diagnostische
effektive Stichprobengröße

```text
ESS = (sum_i w_i)^2 / sum_i(w_i^2)
```

Sie ist nicht identisch mit einem vollständigen Konfidenzintervall, aber eine
notwendige Mindestdiagnose. Bei einem konstanten Normal-Mean-Shift `mu` in
jedem von `T` unabhängigen Jahren gilt idealisiert

```text
E_q[w] = 1
E_q[w^2] = exp(T * ||mu||^2)
ESS / N ~= exp(-T * ||mu||^2)
```

Der aktuelle Default hat `||mu||^2 = 0.25`. Die relative theoretische ESS
fällt daher exponentiell mit dem Horizont. Mehr Jahre liefern bei diesem
Proposal nicht automatisch mehr Information; sie konzentrieren die
Likelihood auf immer weniger Pfade.

### Reproduktion 1: ESS und Gewichtskonzentration

Mit den echten Funktionen `build_shift_vector()`, `apply_mean_shift()` und
`compute_likelihood_weights()`, 2.000 Pfaden und 20 Seeds ergab sich:

| Horizont | ESS Median | ESS Min | ESS Max | Median `mean(w)` | Median größtes normalisiertes Gewicht |
|---:|---:|---:|---:|---:|---:|
| 1 | 1.558,59 | 1.525,76 | 1.584,10 | 1,003 | 0,24 % |
| 5 | 598,48 | 496,92 | 736,81 | 1,003 | 1,18 % |
| 10 | 209,29 | 113,84 | 297,60 | 0,976 | 3,27 % |
| 20 | 45,17 | 2,33 | 114,19 | 1,014 | 9,99 % |
| 30 | 19,11 | 1,66 | 50,79 | 0,894 | 17,30 % |
| 40 | 8,38 | 3,30 | 39,57 | 0,727 | 31,09 % |

Dass `mean(w)` bei langen Horizonten deutlich von eins abweicht, ist hier
kein globaler Formel-Bias, sondern ein weiteres Symptom der zu kleinen
endlichen Stichprobe: Die seltenen gewichtstragenden Pfade werden mit 2.000
Ziehungen häufig nicht angemessen getroffen.

### Reproduktion 2: produktionsnahes defensives Portfolio

Die echte Szenario- und Wealth-Engine wurde für 60 Seeds mit 2.000 Pfaden,
30 Jahren, plausiblen fünf Bucket-Momenten, einer gültigen Korrelation und
der defensiven Allocation

```text
[Equities 10 %, Bonds 65 %, Real Estate 10 %, Alternatives 5 %, Liquidity 10 %]
```

ausgeführt. Gemessen wurde der selbstnormalisiert gewichtete Mittelwert des
Endvermögens ohne zusätzliche Cashflows:

```text
Standard-MC CHF: mean 193544.95, seed-sd 287.53,
                 range 192933.79..194178.99
Auto-IS CHF:     mean 190033.83, seed-sd 17667.42,
                 range 165380.49..258966.81
SD-Verhältnis:  61.44
IS-ESS:          median 19.89, min 1.59, max 78.97
```

Der Auto-Trigger ist für konservative Profile gerade besonders leicht aktiv,
obwohl das Portfolio nur zehn Prozent Equity besitzt und der alleinige
Equity-Shift deshalb ein schlechter Proposal-Treiber sein kann. Das als
Tail-Schutz gedachte Verfahren macht in diesem Repro den veröffentlichten
Schätzer massiv seedabhängiger.

### Reproduktion 3: falsche Likelihood-Horizontkopplung

Für eine Einjahres-Statistik wurden dieselben 30-Jahres-innovationen einmal
mit der korrekten Einjahres-Likelihood und einmal wie im aktuellen
Sensitivity-Kontext mit der vollen 30-Jahres-Likelihood gewichtet. 60 Seeds,
je 2.000 Pfade:

```text
Prefix-1Y-Gewicht: mean -0.0008, sd 0.0330,
                   range -0.0712..0.0668, median ESS 1557.7
volles 30Y-Gewicht: mean -0.0179, sd 0.2972,
                    range -0.6230..0.7675, median ESS 19.9
SD-Verhältnis:      9.01
```

Die späteren 29 Jahre sind unabhängig von der Einjahres-Zielgröße. Sie
ändern den Zielwert asymptotisch nicht, multiplizieren in der endlichen
Stichprobe aber nutzlose Likelihood-Varianz ein. Common Random Numbers sind
richtig; eine gemeinsame volle Likelihood für unterschiedlich lange
Prefix-Statistiken ist es nicht.

### Risiko

1. Solver-Objective, Chance Probability, Goal Sensitivity und Fallback-
   Vergleich können zwischen Seeds oder kleinen Kontextänderungen stark
   springen.
2. Ein formal reproduzierbarer Einzel-Seed kaschiert die Schätzunsicherheit;
   Determinismus ist kein Genauigkeitsnachweis.
3. Ein einzelner hoch gewichteter Pfad kann Allocation und Goal-Status
   dominieren, ohne dass API, UI oder Audit-Trail dies erkennen.
4. Die im Vortagsaudit geforderte Parität aller Estimator-Consumer wäre allein
   noch unzureichend: Sie könnte lediglich denselben unzuverlässigen Schätzer
   überall konsistent publizieren.
5. Sensitivity-Deltas können stärker vom irrelevanten Future-Weight-Rauschen
   als von der fachlichen Goal-Änderung abhängen.

### Verbindlicher Lösungskontrakt

1. Eine zentrale Weight-Evidence berechnet Log-Gewichte stabil per
   Log-Sum-Exp und validiert Shape, Endlichkeit, Nichtnegativität und positive
   Normierung.
2. Für jedes konsumierte Prefix `t` existiert ein eigenes kumulatives
   Log-Likelihood- beziehungsweise normalisiertes Weight-Array. Ein
   `t`-Jahres-Consumer darf keine Innovation nach Jahr `t` gewichten.
3. `StochasticRunEvidence` persistiert mindestens `ess`, `ess_ratio`, größtes
   normalisiertes Gewicht, Weight-Entropy oder Variationskoeffizient,
   Proposal-/Estimatorversion, Shift-Vektor, Weight-Hash und Reliability-
   Verdict je relevantem Horizont.
4. Vor Solver und Publikation gelten versionierte Mindestschwellen. Unterhalb
   der Schwelle wird nicht still weitergerechnet, sondern deterministisch auf
   Standard-MC, ein validiertes Mixture-Proposal oder einen erhöhten
   sequentiellen Pfadumfang gewechselt. Auch der Fallback erhält ein explizites
   Verdict.
5. Der Shift wird an Horizont, tatsächlichen Verlusttreiber, Portfolioexposure
   und Shortfall-Event angepasst. Eine bloße Mindestheuristik kann die Stärke
   mit ungefähr `1/sqrt(T)` skalieren; belastbarer ist ein getestetes
   Cross-Entropy-/Adaptive-Mixture-Verfahren.
6. Der Auto-Trigger „konservativ/retired/hart“ allein reicht nicht. Die
   Proposalwahl muss nachweisen, dass der verschobene Faktor das konkrete
   Tail-Event des Portfolios beeinflusst.
7. Kritische Probability-/Decision-Werte werden zusätzlich über ein
   festgelegtes Seed-Ensemble oder sequentielle Konvergenz geprüft. Die
   akzeptierte Entscheidung benötigt ein Difference-/Confidence-Budget.
8. `OPTIMIZER-IS-EVIDENCE-001` bleibt nach dieser Reparatur vollständig
   umzusetzen: Objective, Contributions, Probability und Quantile konsumieren
   danach dieselbe validierte Weight-Evidence.

### Mindesttests

1. ESS- und Konzentrationsgrenzen für 1, 5, 10, 20, 30 und 40 Jahre.
2. Low-Equity-/Bond-dominantes Portfolio mit Auto-IS und Standard-MC über ein
   festes Seed-Ensemble; der IS-Modus darf die definierte Varianzgrenze nicht
   überschreiten.
3. Hartes Goal und Retirement-Fall mit tatsächlich zielgerichtetem Proposal.
4. Kurzer Prefix bleibt exakt invariant, wenn nur spätere Zufallszahlen des
   gemeinsamen Würfels geändert werden.
5. Baseline und Modified Sensitivity teilen die Schocks im gemeinsamen Prefix,
   verwenden aber jeweils nur ihre eigene kumulative Likelihood.
6. Under-ESS, Weight-Overflow, NaN, Nullsumme und übermäßige
   Gewichtskonzentration führen zum spezifizierten fail-closed/Fallback-
   Verdict.
7. Replay beweist identische Evidence-Hashes bei identischem Input und Seed.

## `MC-PSD-FACTOR-001` – Gültiger Eigenfaktor wird als Cholesky-Dreieck abgeschnitten

### Reproduktion

Als gültige singuläre 5x5-Korrelationsmatrix wurde die All-ones-Matrix
verwendet. Sie beschreibt fünf perfekt positiv korrelierte Einheitsvarianz-
Innovationen. Die produktive Faktor-Funktion liefert korrekt:

```text
F =
[[ 0.  0.  0.  0. -1.]
 [ 0.  0.  0.  0. -1.]
 [ 0.  0.  0.  0. -1.]
 [ 0.  0.  0.  0. -1.]
 [ 0.  0.  0.  0. -1.]]

F @ F.T =
[[1. 1. 1. 1. 1.]
 [1. 1. 1. 1. 1.]
 [1. 1. 1. 1. 1.]
 [1. 1. 1. 1. 1.]
 [1. 1. 1. 1. 1.]]
```

Der Haupt-MC verwendet durch `j <= i` effektiv `tril(F)`. Daraus folgt:

```text
tril(F) @ tril(F).T =
[[0. 0. 0. 0. 0.]
 [0. 0. 0. 0. 0.]
 [0. 0. 0. 0. 0.]
 [0. 0. 0. 0. 0.]
 [0. 0. 0. 0. 1.]]
```

Vier Assets verlieren ihre gesamte Innovationsvarianz; nur das fünfte bleibt
stochastisch. Der Optimizer verwendet denselben Faktor vollständig und erhält
die korrekte All-ones-Kovarianz. Damit simulieren Optimizer und Haupt-MC für
dieselbe zugelassene CMA verschiedene Märkte.

### Risiko

1. Volatilität, VaR, CVaR, Drawdown, Goal Probability und Current-/Target-
   Vergleich können bei singulären PSD-Matrizen materiell falsch sein.
2. Die Datenvalidierung signalisiert „gültig“, während ein nachgelagerter
   Consumer die zugelassene Darstellung semantisch zerstört.
3. Der Fehler ist still: Keine Exception, Warnung oder Quality-Flag zeigt die
   verlorenen Varianzen.
4. Ein späterer anderer Eigenfaktor für dieselbe Matrix kann ein anderes
   Fehlermuster erzeugen, obwohl alle Faktoren mathematisch äquivalent wären.

### Verbindlicher Lösungskontrakt

1. Die interne Bezeichnung wird von `chol`/`cholesky` auf
   `correlation_factor` geändert, sofern der Wert allgemeine Faktoren tragen
   darf.
2. Jeder Consumer multipliziert die vollständige Matrix:

   ```python
   correlated = factor @ independent
   ```

   beziehungsweise äquivalent über alle `n_assets` Quellendimensionen.
3. Vor Nutzung werden Shape, Endlichkeit und
   `factor @ factor.T == validated_correlation` innerhalb einer festgelegten
   Toleranz geprüft oder als bereits verifizierte Snapshot-Evidence gebunden.
4. Optimizer, Haupt-MC, Risikoaggregation und alle weiteren Consumer erhalten
   denselben Faktorvertrag und dieselbe Bucketreihenfolge.
5. `StochasticRunEvidence` bindet Korrelationsmatrix-Hash,
   Faktorisierungsalgorithmus/-version, Faktor-Hash und Validierungsverdict.

### Mindesttests

1. Positive-definite Matrix: historische Cholesky-Semantik bleibt erhalten.
2. All-ones-PSD: alle fünf simulierten Standardinnovationen sind pfadweise
   identisch und besitzen empirisch Varianz ungefähr eins.
3. Rangdefiziente Blockmatrix: empirische Kovarianz entspricht der
   validierten Zielmatrix.
4. Cross-Engine-Test: Optimizer und Haupt-MC erzeugen bei identischem Faktor
   und denselben unabhängigen Schocks dieselbe korrelierte Innovation.
5. Factor-Shape-, NaN-/Inf- und Covariance-Reconstruction-Fehler blockieren
   vor Simulation.

## Erweiterung `STRESS-CONTEXT-001` / `STRESS-SCENARIO-001`

### Neue Evidence

Der Solver baut einen `OptimizerContext`, der unter anderem Tax-Regime,
Dividend Yields, Basisjahr, Mandatsalter, Retirement und optional je Pfad den
Death-Year-Index hält. Das normale Objective simuliert mit diesem Kontext.

Die spätere Stressauswertung verwendet dagegen:

1. die rohen `advisory_wealth_rappen`- und `cashflow_series_rappen`-
   Funktionsargumente statt ausschließlich den retained Context,
2. keine Steuer-/Dividend-/Alter-/Retirement-Parameter,
3. keine Mortalitäts-Death-Indices,
4. und berechnet Drawdown direkt auf dem Wealth-Pfad nach Cashflows und
   Liabilities.

Im heutigen normalen Produktaufruf sind rohe Argumente und Kontextwerte meist
gleich. Der Modellverlust bei Tax, Mortality und Drawdown ist jedoch aktuell;
die mögliche Raw-vs-Context-Abweichung ist ein zusätzlicher latenter
Reproduzierbarkeitsbruch.

### Lösung

1. `evaluate_stress_scenarios()` erhält den unveränderlichen retained Context
   oder einen daraus abgeleiteten, vollständig versionierten
   `StressEvaluationContext`; keine parallele Rohargument-Wahrheit.
2. Wealth-Replay verwendet exakt dieselbe Tax-, Dividend-, Kalender-, Alter-,
   Retirement-, Mortalitäts-, Liability- und Periodenreihenfolge wie der
   entscheidungswirksame Pfad.
3. `market_max_drawdown_bps` wird über einen cashflow-neutralen Marktindex
   berechnet. Depletion, Minimum Wealth und Shortfall bleiben getrennte
   flowabhängige Kennzahlen.
4. Szenariokatalog, Bucketreihenfolge, Frequenz und Returntyp werden versioniert
   und gehasht; bestehende historische Replay- und Solver-Stresskataloge
   bleiben entweder vereinheitlicht oder klar als verschiedene Produkttypen
   benannt.
5. Ein kunden- oder entscheidungswirksamer Stressfehler darf nicht pauschal
   als „nice-to-have“ verschluckt werden. Das Evidence-Verdict entscheidet
   fail-closed über die jeweilige Publikation.

### Mindesttests

1. Retained Context gewinnt gegen absichtlich abweichende Rohargumente.
2. Tax on/off, Dividend Tax, Death Cutoff und Retirement ändern Stress-Wealth
   genau wie im Hauptpfad.
3. Reine geplante Entnahme verändert Depletion, aber nicht
   cashflow-neutralen Market Drawdown.
4. API, Reasoning, React/PDF und Snapshot zeigen dieselbe Scenario-Version und
   dieselben getrennten Kennzahlen.

## P2-Härtung des Szenario-Caches

### `SCENARIO-CACHE-IMMUTABILITY-001`

Ein direkter Cache-Repro ergab:

```text
Standardpfad:
  same_object = True
  writeable = True
  ursprünglicher Wert 1.039629
  nach Consumer-Mutation beim nächsten Hit -123.0

IS-Pfad:
  same_paths_object = True
  same_weights_object = True
  weights_writeable = True
  ursprüngliches Gewicht 0.474635
  nach Consumer-Mutation beim nächsten Hit 999.0
```

Die `frozen=True`-Deklaration des `OptimizerContext` friert NumPy-Inhalte nicht
ein. Ein versehentliches In-place-Normalisieren, Slicing-Assignment oder
Test-/Analysepatch kann daher spätere Runs desselben Prozesses verfälschen.
Im aktuellen internen Suchumfang wurde kein absichtlicher Mutator gefunden;
deshalb ist dies P2-Härtung und kein zusätzlicher P1.

Vertrag:

1. Cache speichert eigene Arrays und setzt `write=False`, bevor sie geteilt
   werden; alternativ gibt er defensive Kopien aus.
2. Pfad- und Weight-Arrays im retained Context sind ebenfalls read-only.
3. Ein Mutationstest muss scheitern, und ein späterer Cache-Hit muss bytegleich
   zum ursprünglichen gespeicherten Wert bleiben.
4. Die bestehende LRU-/Hit-/Miss-Semantik bleibt erhalten.

### `SCENARIO-IS-SHIFT-CONTRACT-001`

Drei angeforderte Vektoren gleicher Stärke wurden mit identischem Input und
Seed über die öffentliche Cache-Funktion erzeugt:

```text
negative Equity: [-0.5,  0.0, 0.0, 0.0, 0.0]
negative Bonds:  [ 0.0, -0.5, 0.0, 0.0, 0.0]
positive Equity: [ 0.5,  0.0, 0.0, 0.0, 0.0]

Equity-vs-Bond paths equal:       True
Equity-vs-Bond weights equal:     True
negative-vs-positive paths equal: True
negative-vs-positive weights:     True
Cache misses/hits:                3 / 0
```

Die drei verschiedenen Keys berechnen somit denselben internen Default. Der
produktive Solver übergibt heute genau diesen Default, weshalb der Befund dort
noch keinen zusätzlichen P1 erzeugt. Die öffentliche API und jede geplante
adaptive Proposalwahl sind aber falsch, bis der Vertrag geschlossen ist.

Vertrag:

1. Die Engine akzeptiert den exakten validierten Shift-Vektor; Richtung,
   Bucket und Betrag werden nicht intern neu interpretiert.
2. Der Cache-Key wird aus genau dem tatsächlich angewendeten Vektor gebildet.
3. Shape, Endlichkeit und zulässige Norm werden vor Ziehung geprüft.
4. Shift-Vektor und Hash werden in der Run-Evidence persistiert.
5. Regressionstests beweisen unterschiedliche Pfade/Gewichte für Bucket- und
   Richtungswechsel sowie identischen Replay für denselben Vektor.

## Erweiterter `StochasticRunEvidence`-Zielvertrag

Der Vortagsaudit fordert bereits eine gemeinsame unveränderliche Evidence.
Diese Runde ergänzt zwingend folgende numerische Felder:

```text
StochasticRunEvidence
  scenario_context
    seed / seed_ensemble_version
    n_paths_requested / n_paths_accepted
    run_horizon_years
    common_scenario_horizon_years
    scenario_cube_hash / dtype / shape
    correlation_matrix_hash
    correlation_factor_hash / algorithm_version
    factor_reconstruction_verdict
  estimator
    proposal_version
    exact_shift_vector / shift_hash
    cumulative_log_weight_artifact_hash
    weight_hash_by_consumed_horizon
    ess_by_horizon
    ess_ratio_by_horizon
    max_normalized_weight_by_horizon
    weight_entropy_or_cv_by_horizon
    reliability_threshold_version
    reliability_verdict
    fallback_type / fallback_reason
  stress
    stress_context_hash
    scenario_catalog_id / version / hash
    tax_mortality_lifecycle_parity_verdict
    market_max_drawdown_bps
    depletion_min_wealth_rappen
    shortfall_metrics
  publication
    evidence_hash
    readiness_verdict
```

Große Szenario- und Prefix-Weight-Matrizen dürfen content-addressed außerhalb
des JSON liegen. Der Run muss deren Hash, Shape, Dtype, Methodenversion und
Retentionstatus binden.

## Empfohlene Implementierungsreihenfolge für Claude

### Phase 0: rote Reprotests

Zuerst unverändert materialisieren:

1. ESS-Tabelle für lange Horizonte,
2. defensives 30-Jahres-Portfolio über ein festes Seed-Ensemble,
3. Einjahres-Prefix mit verändertem Future-Cube,
4. All-ones-PSD-Faktor im Haupt-MC,
5. Cache-Poisoning und exakte Shift-Vektoren,
6. Stress Tax-/Mortality-/Cashflow-neutraler-Drawdown-Parität.

### Phase 1: Korrelationsfaktor reparieren

Diese Reparatur ist lokal, deterministisch und unabhängig vom späteren
Proposaldesign:

1. generischen Faktor benennen,
2. vollständige Matrixmultiplikation in allen Consumern,
3. Reconstruction- und Cross-Engine-Tests,
4. Faktoridentität in Evidence aufnehmen.

### Phase 2: Weight-Kern und Prefix-Likelihood

1. Log-Weight-Berechnung und kumulative Prefix-Evidence zentralisieren.
2. Jede Goal-/Run-Auswertung wählt exakt ihren Horizont.
3. Weight-Validierung, ESS und Konzentration an einer Stelle implementieren.
4. Sensitivity behält Common Random Numbers, aber nicht Future-Likelihood.

### Phase 3: Proposal und Fallback

1. Versionierten adaptiven beziehungsweise Mixture-Proposalvertrag festlegen.
2. Exakte Shift-Vektoren durch Engine und Cache transportieren.
3. Reliability-Schwellen und Standard-MC-/Path-Increase-Fallback festlegen.
4. Seed-Ensemble-/Konvergenzbudget für kritische Entscheidungen einführen.

### Phase 4: Estimator-Consumer vereinheitlichen

Erst auf der validierten Weight-Evidence werden
`OPTIMIZER-IS-EVIDENCE-001`, Goal-Horizonte, Weighted Quantiles,
Contributions und Probability-Reconciliation geschlossen.

### Phase 5: Stress und immutable Ownership

1. Stress auf retained Context umstellen.
2. Market Drawdown von Depletion trennen.
3. Cache- und Context-Arrays read-only machen.
4. Szenario-/Stress-/Weight-Artefakte an `StochasticRunEvidence` binden.

### Phase 6: Replay und Publication-Preflight

1. Repräsentative konservative, retired, harte-Goal-, lange-Horizont- und
   singuläre-PSD-Mandate shadow-replayen.
2. Difference-/Reliability-Budget dokumentieren.
3. API, Classic UI, React, PDF, Signed Artifact und Handoff auf dieselbe
   Evidence-ID prüfen.
4. Erst danach Freigabe beantragen.

## Harte Invarianten der Abnahme

1. **ESS-Gate:** Kein IS-Ergebnis wird entscheidungs- oder kundenwirksam,
   wenn seine horizon-spezifische Reliability-Evidence die versionierten
   Schwellen verletzt.
2. **Prefix-Likelihood:** Ein `t`-Jahres-Ergebnis ist invariant gegenüber
   Änderungen ausschließlich nach Jahr `t`.
3. **Proposal-Wahrheit:** Der persistierte Shift-Vektor ist bytegleich zum
   tatsächlich angewendeten Vektor.
4. **Factor Reconstruction:** Jeder Korrelationsfaktor rekonstruiert die
   validierte Zielmatrix innerhalb Toleranz.
5. **Cross-Engine-Parität:** Bei identischen unabhängigen Schocks und demselben
   Faktor erzeugen Optimizer und Haupt-MC dieselben korrelierten Schocks.
6. **Cache Ownership:** Kein Consumer kann durch Array-Mutation einen späteren
   Run verändern.
7. **Stress Context:** Stress-Wealth verwendet denselben Tax-/Mortality-/Flow-
   und Lifecycle-Kontext wie die gebundene Entscheidung.
8. **Kennzahlentrennung:** Market Drawdown ist cashflow-neutral; Depletion und
   Shortfall bleiben separat.
9. **Evidence-Parität:** Objective, Contributions, Probability, Quantile,
   Sensitivity, Stress und Publikation referenzieren denselben validierten
   Run-Kontext oder klar versionierte abgeleitete Artifacts.
10. **Fail-closed:** Ungültiger Faktor, unzuverlässige Gewichte, fehlende
    Prefix-Evidence, mutiertes Artifact oder Kontextdrift blockiert vor
    Finalisierung und kundenwirksamer Publikation.

## Unzureichende Scheinlösungen

Folgende Änderungen schließen den Audit ausdrücklich nicht:

1. Nur die Pfadzahl pauschal erhöhen, ohne ESS-/Konzentrationsmessung.
2. Die aktuelle ESS nur im Log anzeigen, aber das Ergebnis trotzdem als
   belastbar publizieren.
3. Auto-IS global abschalten und damit die beabsichtigte Tail-Methode ohne
   Ersatz entfernen.
4. Für kurze Runs weiter volle Gewichte verwenden und nur den ESS-Wert des
   kurzen Prefix anzeigen.
5. Eine singuläre gültige PSD-Matrix still durch Identity oder Default-
   Korrelation ersetzen.
6. Eigenfaktoren nachträglich dreieckig nullen; damit wird ihre Zielkovarianz
   verändert.
7. Nur den Optimizer oder nur den Haupt-MC reparieren.
8. Cache-Hits kopieren, aber die im Context gehaltenen Arrays schreibbar
   lassen oder umgekehrt.
9. Stress-Drawdown umbenennen, obwohl weiterhin Cashflows als Marktverlust
   eingehen.
10. Neue JSON-Felder ohne Hash, Methodenversion, Readiness und kanalgleiche
    Consumer hinzufügen.
11. Die 226 grünen Bestandstests als Ersatz für die neuen Gegenbeispiele
    behandeln.

## Verifikationsnachweis

### Deterministische Reproduktionen

In fünf isolierten Gruppen wurden ausgeführt:

1. ESS-/Weight-Konzentration über sechs Horizonte und 20 Seeds,
2. produktionsnahe 30-Jahres-Wealth-Schätzung über 60 Seeds,
3. Prefix-gegen-Full-Horizon-Likelihood über 60 Seeds,
4. singuläre All-ones-PSD-Faktorreconstruction und tatsächlich konsumierte
   Kovarianz,
5. Standard-/IS-Cache-Mutation sowie drei verschiedene Shift-Vektoren.

Alle im Audit angegebenen Zahlen stammen aus diesen Ausführungen gegen die
Produktionsfunktionen des auditierten Heads.

### Ausgeführtes fokussiertes Bestands-Gate

Aus `5eyes-backend` wurde ein isoliertes, cachefreies Numerik-Gate ausgeführt:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp=..\tmp\pytest-round34-numerics `
  tests/test_optimizer_importance_sampling.py `
  tests/test_scenario_engine_is_wrapper.py `
  tests/test_optimizer_is_auto_activation.py `
  tests/test_optimizer_solver_with_is.py `
  tests/test_optimizer_scenario_cache.py `
  tests/test_optimizer_scenario_engine.py `
  tests/test_optimizer_context.py `
  tests/test_cholesky_and_horizon.py `
  tests/test_cma_correlation_matrix_validation.py `
  tests/test_cma_strict_runtime_contract.py `
  tests/test_optimizer_stress_scenarios.py `
  tests/test_simulation_rebalance_costs.py `
  tests/test_asset_allocation_current_integrity_contracts.py `
  tests/test_asset_allocation_remaining_integrity_edges.py `
  tests/test_asset_allocation_reference_integrity_edges.py
```

Ergebnis:

```text
226 passed in 52.32s
```

Es gab keine Fehler und keine übersprungenen Tests. Der grüne Status bestätigt
die bestehenden Positivpfade. Das Gate enthält jedoch weder lange-Horizont-
ESS-Grenzen noch Prefix-Weight-Invarianz, einen All-ones-PSD-Consumer-Test,
Cache-Immutability, exakte Shift-Richtung oder vollständige Stress-Kontext-
Parität. Es widerlegt die neuen Findings daher nicht.

### Bewusst nicht behauptete Gates

- Kein Browser-DOM-Lauf wurde in dieser Runde ausgeführt.
- Kein echter PostgreSQL-/Concurrency-Lauf wurde in dieser Runde ausgeführt.
- Kein Full-Backend-Gate wurde erneut gestartet; der 226-Test-Fokus deckt die
  geprüften numerischen Module ab und vermeidet eine ressourcenintensive
  Wiederholung unveränderter Bereiche.
- Die vorbestehenden ACL-Warnungen beim Lesen alter `.pytest_tmp*`-
  Verzeichnisse wurden nicht als Produktfehler interpretiert.

## Dokumentationsmanifest

Diese Kontrollrunde ändert genau folgende fünf Dokumentationspfade:

1. `docs/audits/2026-09-22-stochastic-estimator-correlation-cache-and-stress-reproducibility-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Produktcode, Tests, Migrationen und Runtime-Konfiguration bleiben
unverändert.

## Claude-Startcheckliste

Vor der ersten Codeänderung muss Claude:

1. diesen Audit und den Vortagsaudit vollständig lesen,
2. die stabilen Findings-IDs beibehalten und Stress-IDs nicht duplizieren,
3. alle sechs Phase-0-Reprogruppen zuerst als rote Tests materialisieren,
4. `correlation_factor` als generischen Vollmatrixvertrag reparieren,
5. Prefix-Log-Likelihood und Weight-Diagnostik zentral spezifizieren,
6. ESS-/Konzentrationsschwellen sowie Fallback-/Konvergenzpolitik als
   versionierte Owner-Entscheidung dokumentieren,
7. erst danach das adaptive Proposal implementieren,
8. Cache und retained Context unveränderlich machen,
9. Stress auf denselben Modellkontext und getrennte Drawdown-/Depletion-
   Semantik umstellen,
10. nach jeder Phase das 226-Test-Gate und die neuen Reprotests ausführen,
11. anschließend den breiteren 609-Test-Core-Gate des Vortagsaudits laufen
    lassen,
12. und erst nach Shadow-Replay, Publication-Preflight und kanalgleicher
    Evidence eine Releasefreigabe beantragen.

## Releaseentscheidung

**Release bleibt hart blockiert.** Vor Freigabe müssen mindestens
`OPTIMIZER-IS-ESS-001` und `MC-PSD-FACTOR-001` geschlossen sein. Zusätzlich
bleiben `OPTIMIZER-IS-EVIDENCE-001`, die Goal-/MC-/Publication-P1 sowie
`STRESS-CONTEXT-001` und `STRESS-SCENARIO-001` offen. Ein deterministischer
Seed ersetzt keine ausreichende effektive Stichprobe; eine validierte
Korrelationsmatrix ersetzt keine korrekte Faktorverwendung; und ein
Stresslabel ersetzt keinen identischen Modellkontext.
