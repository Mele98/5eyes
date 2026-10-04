---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-house-matrix-policy-constraint-zero-semantics-effective-bounds-and-retirement-allocation-basis-followup-audit"
status_as_of: "2026-10-04"
audit_started_on: "2026-10-04"
audit_completed_on: "2026-10-04"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
frontend_root: "5eyes-electron/frontend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "21086ab2ce8ddf6749fdb16871d1d71c7f903a84"
prior_policy_audit_path: "docs/audits/2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md"
prior_policy_ab_audit_path: "docs/audits/2026-08-28-stress-replay-and-policy-ab-model-integrity-audit.md"
prior_retirement_audit_path: "docs/audits/2026-09-13-retirement-income-pension-withdrawal-and-depletion-integrity-audit.md"
implementation_baseline_path: "docs/audits/2026-08-20-asset-allocation-stochastic-core-handoff.md"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md"
audit_mode: "read_only_static_schema_model_house_matrix_constraint_composition_rebalance_generate_stochastic_sensitivity_backtest_retirement_and_publication_review_plus_ephemeral_sqlite_service_reproductions"
audit_mutated_product_code: false
audit_mutated_tests: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: "not_asserted_due_to_pre_existing_acl_unreadable_pytest_directories"
documentation_manifest_paths: 5
scope: "House-Matrix targets and bands, policy caps, zero semantics, effective-bound feasibility, deterministic and stochastic consumption, risk-budget boundary, sensitivity, policy A/B, Max-Pension-Spending return basis and persisted TargetAllocation constraints"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
new_confirmed_p1_count: 2
confirmed_prior_p1_extension_groups: 2
deterministic_ephemeral_probe_tests_passed: 5
focused_existing_backend_tests_passed: 157
focused_existing_tests_failed: 0
browser_dom_runtime_executed: false
real_postgresql_concurrency_executed: false
required_next_action: "treat zero as an explicit constraint value, introduce one strict effective-bound compiler and validator before every consumer and persistence boundary, bind Max-Pension-Spending to a verified current allocation context, then repair or quarantine allocations and publications produced from ignored or inverted constraints"
---

# House-Matrix-, Policy-Constraint- und Retirement-Basis-Integritätsaudit

## Geltung, Quellenrangfolge und Abgrenzung

Dieser additive Folgeaudit dokumentiert die zweiundvierzigste Read-only-
Kontrollrunde des Asset-Allocation-/Stochastic-Core. Geprüft wurde der
unveränderte Repository-Head
`21086ab2ce8ddf6749fdb16871d1d71c7f903a84`. Produktcode, Migrationen und
dauerhafte Tests wurden nicht verändert. Fünf kurzlebige Audit-Probes wurden
ausgeführt und danach vollständig entfernt. Nach der Prüfung werden nur die
fünf Pfade des Dokumentationsmanifests angepasst.

Die Runde verfolgt den Constraintvertrag vom öffentlichen Policy-/House-
Matrix-Schema über `_baseline_target_bands()`, Rebalancing, House- und
stochastic Generate, Sensitivity, Risk-Budget-Fallback, Policy-A/B und
Max-Pension-Spending bis zur TargetAllocation-Persistenz.

Ein Policywert `0` ist innerhalb der öffentlich erlaubten Domäne ein
expliziter Wert und kein Missing-Sentinel. Ein „effektives Band“ ist nur dann
ein gültiger Vertrag, wenn `0 <= min <= max <= 10000`, die Gesamtheit eine
voll investierte Allokation zulässt und jedes persistierte Target innerhalb
seines Bandes liegt. Eine Renditebasis für eine konkrete Pensionsempfehlung
muss aus demselben verifizierten Strategieentscheid stammen wie die übrige
Beratungsevidence.

## Deduplizierung zu bestehenden Findings

Keine bestehende Finding-ID wird geschlossen oder umbenannt.

- `POLICY-ACTIVATION-COMPLETENESS-001` verlangt bereits, Policy-Caps und
  House-Matrix-Bänder vor Aktivierung als vollständiges Aggregate zu prüfen.
  Der hier produktiv reproduzierte Fall `min > policy max`, den der House-Pfad
  anschließend trotzdem persistiert, ist eine konkrete Runtime- und
  Persistenzerweiterung dieses bestehenden P1. Dafür wird keine dritte neue
  ID gezählt.
- `AB-MODEL-001` dokumentiert bereits, dass Policy-A/B rohe House-Targets
  statt eines vollständigen produktiven Constraint-/Stochastic-Contexts
  vergleicht. Die erneute Feststellung, dass A/B deshalb auch Policy-Caps und
  Equity-Floors nicht in seine Gewichte materialisiert, erweitert diesen P1,
  ist aber kein neuer Befund.
- `POLICY-VERSION-IDENTITY-001` erklärt, wie Caps einer aktiven Policy unter
  derselben ID mutierbar sind. Die vorliegende Runde prüft davon unabhängig,
  ob ein bereits geladener Cap fachlich korrekt interpretiert und ausgeführt
  wird.
- Die Retirement-/Decumulation-Audits halten zu Recht fest, dass Max-Pension-
  Spending nur eine deterministische Annuitätennäherung ist. Sie prüfen nicht,
  ob deren erwartete Rendite aus der tatsächlich wirksamen Allocation und
  deren Constraints stammt. `RETIREMENT-ALLOCATION-BASIS-001` ist deshalb neu.
- `SNAPSHOT-DOMAIN-001` betrifft frei eingesandte Legacy-Strategy-Snapshots.
  Die hier gezeigte invertierte TargetAllocation entsteht dagegen
  serverseitig im produktiven Generate-Pfad.

Zwei neue Ursachen-IDs werden geführt:

- `ZERO-CONSTRAINT-SEMANTICS-001`
- `RETIREMENT-ALLOCATION-BASIS-001`

## Kurzurteil

Die Runde bestätigt **zwei neue release-blockierende P1** und zwei konkrete
Erweiterungen bestehender P1.

**`ZERO-CONSTRAINT-SEMANTICS-001`:** Die öffentlichen Policy-Schemas erlauben
`max_real_estate_bps=0` und `max_alternatives_bps=0`. Der zentrale
Constraint-Composer ersetzt beide Werte jedoch über `value or 10000` durch
10.000 bps. Ein echter House-Generate mit beiden Caps auf null persistierte
weiterhin 800 bps Immobilien und 600 bps Alternative Anlagen; selbst die
gespeicherten Maximalbänder blieben 2.000 und 1.000 bps. Stochastic und eine
Sensitivity ohne bestehende Allocation übernehmen dieselbe bereits
entwertete Baseline und reduzieren sie nur auf die allgemeinen 20-/10-Prozent-
Caps, nicht auf null. Ein expliziter Ausschluss ist damit kein Ausschluss.
Dasselbe Falsy-Muster existiert im contextlosen Defense-in-depth-Risikocheck:
ein erlaubtes `max_risky_fraction_bps=0` wird dort als 10.000 interpretiert.

**`RETIREMENT-ALLOCATION-BASIS-001`:** Der Max-Pension-Spending-Endpunkt lädt
weder die verifizierte aktuelle TargetAllocation noch ihren persistierten
Constraint-/Suballokationscontext. Er nimmt rohe House-Matrix-Targets aus
`_baseline_target_bands()` und verwirft die gleichzeitig berechneten Min-/Max-
Bänder. In einem vollständig machbaren Probe galten Equity-Floor 7.000,
Immobilien-Maximum 600 und Alternatives-Maximum 400 bps. Die kanonisch
rebalancierte Strategie war `7000/1800/600/400/200`; der Endpunkt berechnete
Rendite, Volatilität und Annuität trotzdem auf
`6800/1600/800/600/200`. Er ignoriert damit nicht nur Caps und Floors, sondern
auch ein mögliches stochastic Ergebnis, Mandatsband-Overrides und die
persistierte Strategieidentität. Die als „Modell-Medianrendite“ und maximal
finanzierbare Ausgabe publizierte Zahl kann zu einer anderen Strategie
gehören als die freigegebene Beratung.

**Erweiterung `POLICY-ACTIVATION-COMPLETENESS-001`:** Ein positiver Policy-Cap
unterhalb des House-Minimums erzeugt invertierte effektive Bänder. Der
Rebalancer prüft `min <= max` nicht; seine Clamp-Reihenfolge lässt das Minimum
gewinnen. Ein echter House-Generate mit Immobilien-Cap 300 bei House-Minimum
500 und Alternatives-Cap 200 bei House-Minimum 300 persistierte deshalb
`500/500/300` beziehungsweise `300/300/200` als
`min/target/max`. Target und Minimum liegen über dem Policy-Cap. Der
stochastic Solver besitzt später eine strikte Bounds-Prüfung, der aktive
House-Pfad und die Persistenzgrenze aber nicht.

**Erweiterung `AB-MODEL-001`:** `_evaluate_policy()` gibt rohe Targets an
Metrik und Stress weiter, obwohl es die wirksamen Min-/Max-Bänder daneben
berechnet. Somit kann die angezeigte A/B-Gewichtung außerhalb genau der im
selben Payload ausgegebenen Bänder liegen. Das ist eine weitere konkrete
Ausprägung des bereits offenen modellfremden „Backtests“.

## Findings-Register

| ID | Priorität | Status | Verbindlicher Vertrag |
|---|---:|---|---|
| `ZERO-CONSTRAINT-SEMANTICS-001` | P1 | neu bestätigt | Jeder im öffentlichen Schema erlaubte Nullwert bleibt über Composer, Engine, Fallback, Sensitivity, A/B, Persistenz und Publikation exakt null; Missing besitzt einen getrennten Typ/Sentinel und darf nie über boolesche Truthiness mit null verschmolzen werden |
| `RETIREMENT-ALLOCATION-BASIS-001` | P1 | neu bestätigt | Max-Pension-Spending rechnet auf genau einer verifizierten, aktuellen und hashgebundenen Allocation-/CMA-/Fee-/Inflationsbasis; ohne gültigen Strategieentscheid blockiert der Endpunkt oder erzeugt explizit einen vollständigen kanonischen Candidate-Context, niemals rohe House-Targets |

Bestätigte Erweiterungen bestehender P1:

| Bestehende ID | Erweiterung dieser Runde |
|---|---|
| `POLICY-ACTIVATION-COMPLETENESS-001` | Der House-Rebalancer akzeptiert invertierte effektive Bänder und persistiert TargetAllocation-Min/Target/Max außerhalb des Policy-Caps; Readiness allein beim künftigen Activate genügt deshalb nicht, zusätzlich braucht jede Runtime-/Persistenzgrenze denselben strikten Validator |
| `AB-MODEL-001` | Policy-A/B berechnet Metrik und Stress auf rohen Targets, obwohl die zurückgegebenen effektiven Bänder diese Targets ausschließen können |

## Tatsächlicher Constraintfluss

```text
OptimizerPolicyCreate/Update
  max_real_estate_bps: 0..10000
  max_alternatives_bps: 0..10000
          |
          v
_baseline_target_bands(house, policy)
  targets  := rohe House-Targets
  RE max   := min(House max, policy.max_real_estate_bps or 10000)
  Alt max  := min(House max, policy.max_alternatives_bps or 10000)
          |                         |
          |                         +--> 0 wird zu 10000
          |
          +--> Generate -> _rebalance_to_total -> TargetAllocation
          |       House: kein min<=max-Preflight
          |       stochastic: spätere strikte Solver-Bounds-Prüfung
          |
          +--> Sensitivity ohne TA -> Rebalance + stochastic Guardrails
          |
          +--> Policy-A/B -> rohe Targets direkt an Metrics/Stress
          |
          '--> Max-Pension-Spending -> rohe Targets direkt an
                   Suballocation/Metrics/Annuität; Bänder verworfen
```

## Reproduktion A: Null-Caps werden zu offenen Caps

Die öffentlichen Schemas akzeptierten deterministisch:

```text
OptimizerPolicyCreate.max_real_estate_bps = 0
OptimizerPolicyCreate.max_alternatives_bps = 0
HouseMatrixRowInput.max_risky_fraction_bps = 0
```

Für eine House-Zeile mit Ziel Immobilien 800, Alternatives 600 sowie House-
Maxima 2.000/1.000 lieferte `_baseline_target_bands()` trotz Policy-Caps null:

```text
effective maximum real_estate = 2000
effective maximum alternatives = 1000
rebalanced target real_estate = 800
rebalanced target alternatives = 600
```

Die echte `generate_target_allocation()`-Reproduktion im Modus
`house_matrix` persistierte:

```text
targets = equities 6950, bonds 1500, real_estate 800,
          alternatives 600, liquidity 150
stored real_estate max = 2000
stored alternatives max = 1000
```

Der Fehler liegt vor Tilt, Solver und Persistenz in der gemeinsamen Baseline.
Deshalb reicht es nicht, nur den finalen House-Output zu nullen. Der
Constraintwert muss bereits bei der Komposition erhalten bleiben und alle
Verbraucher müssen denselben validierten effektiven Contract erhalten.

### Companion-Boundary beim Risikobudget

Das House-Matrix-Schema erlaubt ein Risikobudget von null. Der normale
stochastic Context erhält `int(house_matrix.max_risky_fraction_bps)` korrekt.
Wenn ein konvergierter Solverresult jedoch keinen Context trägt, prüft die
Defense-in-depth-Grenze gegen:

```python
int(getattr(house_matrix, "max_risky_fraction_bps", 10000) or 10000)
```

Null wird dort zu 10.000. Dieser Zweig schützt insbesondere zukünftige
Solverimplementierungen und Test-Doubles; er darf gerade deshalb keinen
schwächeren Nullvertrag besitzen. Zugleich behauptet ein Bestandstest für
Seed-Daten, das Risikobudget müsse größer null sein, während das öffentliche
Schema null erlaubt. Claude muss die Fachdomäne entscheiden: null verbieten
und migrieren oder null überall als „kein Risiko zulässig“ ausführen. Eine
stille Mischsemantik ist unzulässig.

## Reproduktion B: positiver Cap erzeugt und persistiert invertierte Bänder

Für Score 8 gelten in der aktiven House Matrix:

```text
real_estate minimum = 500
alternatives minimum = 300
```

Die aktive Policy wurde auf gültige Einzelwerte gesetzt:

```text
max_real_estate_bps = 300
max_alternatives_bps = 200
```

Der Composer erzeugte damit `500..300` und `300..200`. Der Rebalancer beginnt
mit:

```python
adjusted[key] = max(minimums[key], min(maximums[key], adjusted[key]))
```

Bei einem invertierten Band gewinnt dadurch das höhere Minimum. Da nur die
Gesamtsumme geprüft wird, endete der echte produktive House-Generate
erfolgreich mit:

```text
real_estate   min=500 target=500 max=300
alternatives  min=300 target=300 max=200
```

Das ist gleichzeitig:

- ein invertierter gespeicherter Bandvertrag;
- eine Verletzung beider Policy-Caps;
- ein Target außerhalb des eigenen Maximalbandes; und
- ein servererzeugtes Artefakt, das nachgelagerte Payloads und Publikationen
  als normale TargetAllocation behandeln können.

`bands_from_effective_bounds_bps()` würde dieselbe Inversion im stochastic
Pfad korrekt mit `OptimizerInputError` ablehnen. Dass der House-Modus sie
persistiert, ist daher keine unvermeidbare Legacyeigenschaft, sondern ein
fehlender gemeinsamer Boundary-Validator.

## Reproduktion C: Max-Pension-Spending verwendet eine andere Strategie

Der Probe setzte eine vollständig lösbare Constraintkombination:

```text
House target                 6800 / 1600 / 800 / 600 / 200
equity_minimum_bps           7000
max_real_estate_bps           600
max_alternatives_bps          400
House minima RE / Alt         500 / 300
```

Der gemeinsame Rebalancer lieferte korrekt:

```text
effective target            7000 / 1800 / 600 / 400 / 200
sum                         10000
```

Der echte Max-Pension-Spending-Service übergab an `_expected_metrics()` aber:

```text
raw target                  6800 / 1600 / 800 / 600 / 200
sum                         10000
```

Die Abweichung ist kein Infeasibility-Sonderfall. Beide Caps liegen über den
jeweiligen House-Minima; die effektive Strategie ist eindeutig konstruierbar.
Der Endpunkt verwirft die bereits berechneten Bänder absichtlich über
`targets, _, _` und ruft keinen Rebalancer auf.

Zusätzlich lädt dieser Pfad keine aktuelle TargetAllocation. Selbst nach
einem erfolgreichen stochastic Lauf bleibt seine Renditebasis die rohe House
Matrix. `_expected_metrics()` wird ohne Produkte aufgerufen; damit ist auch
der dort mögliche produktgewichtete TER null. Die Annuität ist zwar korrekt
als deterministisch gekennzeichnet, ihre Portfoliobasis ist aber weder die
aktive Strategie noch vollständig kosten- und evidencegebunden.

## Statische Codeanker

| Bereich | Verifizierter Anker auf dem auditierten Head |
|---|---|
| Policy-Caps erlauben null | `5eyes-backend/schemas/allocation.py:451-486` |
| House-Risikobudget erlaubt null | `5eyes-backend/schemas/allocation.py:408-448` |
| Null-Cap wird per `or 10000` aufgehoben | `5eyes-backend/services/portfolio_engine_house_matrix.py:1416-1438` |
| Rebalancer ohne Inversions-Preflight | `5eyes-backend/services/portfolio_engine_house_matrix.py:277-313` |
| Generate komponiert Baseline und persistiert nach Rebalance | `5eyes-backend/services/portfolio_engine.py:3041`; `:3418-3429`; `:3991-4010` |
| Stochastic besitzt strengeren effektiven Bounds-Validator | `5eyes-backend/services/optimizer/constraints.py:136-239` |
| Contextloser Risiko-Guard macht 0 zu 10000 | `5eyes-backend/services/portfolio_engine_optimizer_integration.py:451-460` |
| Sensitivity ohne TA baut dieselbe Live-Baseline | `5eyes-backend/services/portfolio_engine.py:4795-4870` |
| Policy-A/B nutzt rohe Targets direkt | `5eyes-backend/services/backtest_ab.py:61-94` |
| Max-Pension-Spending verwirft Bands | `5eyes-backend/routers/wealth.py:1188-1265` |
| Metrik normalisiert Targets nicht und TER fehlt ohne Produkte | `5eyes-backend/services/portfolio_engine_cma.py:601-665` |
| Bestehender Rebalance-Test prüft Unlösbarkeit, nicht `min > max` | `5eyes-backend/tests/test_allocation_rebalance_normalization.py:6-50` |
| Pensionstests prüfen Plausibilität/Margin/Datum, nicht Strategiebasis | `5eyes-backend/tests/test_sprint_a_quick_wins.py:291-353` |

## Modusparität: verifizierter Owner-Entscheidungspunkt

Die Konstanten `MAX_REAL_ESTATE=20 %`, `MAX_ALTERNATIVES=10 %` und
`MIN_LIQUIDITY=2 %` werden nur im stochastic Candidate-Context zusätzlich
erzwungen. Ein House-/Shadow-Result darf nach heutigem Code beispielsweise
150 bps Liquidität tragen, während stochastic mindestens 200 bps verlangt.

Diese Runde zählt das nicht als neue Finding-ID, weil Code und Tests die drei
Werte bisher als Solver-Guardrails behandeln und ein expliziter
produktübergreifender Ownervertrag fehlt. Vor dem Fix muss die Entscheidung
aber schriftlich fallen:

1. Sind sie globale Produkt-Constraints, müssen House, stochastic, Shadow,
   Fallback, Sensitivity, A/B und Retirement dieselben Werte erzwingen.
2. Sind sie bewusst solver-spezifisch, müssen Felder, UI, Evidence und
   Publikation sie genau so benennen; „global“ ist dann irreführend.

Die Entscheidung darf nicht implizit durch den ausgewählten Engine-Modus
fallen, weil harte Eignungsgrenzen keine Optimizer-Heuristik sind.

## Verbindlicher Lösungsweg für Claude

### 1. Null und Missing typologisch trennen

- In allen Constraint-Composern ausschließlich `is None` für Missing nutzen.
- `int(value or fallback)` bei fachlich nullfähigen BPS-Feldern verbieten.
- Policy-Caps null ergeben effektive Maxima null und erzwingen null Targets.
- Für `max_risky_fraction_bps` einen Ownerentscheid treffen: `gt=0` samt
  Migration oder korrektes Zero-Risk-Verhalten in jedem Pfad.
- Einen kleinen statischen/semantischen Test über alle Constraintfelder
  aufnehmen, der `0`, `None`, positives Minimum und Maximum getrennt prüft.

### 2. Einen kanonischen `EffectiveAllocationConstraints`-Compiler bauen

Ein gemeinsamer Compiler erhält mindestens:

- immutable Policyversion und Content-Hash;
- House-Matrix-Zeile;
- globale oder explizit solver-spezifische Guardrails;
- Mandatsband-Overrides;
- Equity-Floor;
- Reserve-Floor;
- Illiquiditäts-/Suballokations-Cap;
- Risikobudget und exakte risky fractions.

Sein strikt typisiertes Ergebnis enthält Targets, Minima, Maxima, Quellen je
Constraint, Modus/Scope und einen kanonischen Hash. Generate, stochastic,
Shadow, Fallback, Sensitivity, A/B und Retirement konsumieren dasselbe Objekt
oder eine ausdrücklich benannte, engere Projektion davon.

### 3. Vor Rebalance und Persistenz fail-closed validieren

Der gemeinsame Validator prüft vor jeder Verwendung:

- exakt fünf bekannte Buckets;
- bool-sichere Integer in `0..10000`;
- für jeden Bucket `min <= max`;
- `sum(min) <= 10000 <= sum(max)`;
- nach Rebalance `min <= target <= max` je Bucket;
- exakte Targetsumme 10.000;
- Policy-Caps, Equity-Floor, Liquiditätsfloor und Risikobudget explizit;
- keine stillen Bound-Relaxationen ohne versionierten, publizierten
  Governancegrund.

`_rebalance_to_total()` darf invaliden Input nicht „reparieren“. Es soll vor
dem ersten Clamp mit stabiler Domainexception abbrechen und vor Return alle
Postconditions erneut prüfen. Dieselbe Prüfung gehört unmittelbar vor
TargetAllocation-Write und in den modernen Persistenz-/Response-Vertrag.

### 4. Policy-Lifecycle und Legacybestand schließen

- Round 41 vollständig umsetzen: Caps gegen jede House-Zeile bereits im Draft
  und vor atomarer Aktivierung prüfen.
- Ein Cap unter einem Minimum ist 422/409 mit Bucket, Scorebereich und beiden
  Werten; niemals erfolgreiche Aktivierung oder Generate.
- In-place-Edits der Current-Policy beseitigen, damit kein bereits
  zertifiziertes Aggregate nachträglich invertiert wird.
- Bestehende Policies und TargetAllocations nach Null-Cap-Verlust,
  `min > max`, Target außerhalb Band und Capverletzung scannen.
- Betroffene Allocations, Recommendations, PDFs, Signaturen, A/B-Ergebnisse
  und Retirement-Rechnungen replayen oder sichtbar quarantänisieren.

### 5. Max-Pension-Spending an eine verifizierte Strategie binden

- Primär genau eine aktuelle, moderne, nicht stale TargetAllocation über den
  bestehenden strikten Resolver laden.
- Persistierte Targets, kanonische Suballokation, effektive Constraints,
  Snapshot-CMA, Fee-/Produktbasis, Inflation-/As-of-Kontext und Hash prüfen.
- Rendite und Volatilität aus diesem unveränderten Context berechnen; keine
  Live-House-Matrix oder Live-CMA unbemerkt beimischen.
- Falls der fachliche Workflow eine Berechnung vor Strategieerstellung
  benötigt, einen eigenen expliziten `planning_candidate` mit demselben
  Constraint-Compiler erzeugen und im Response klar von einer freigegebenen
  Strategie unterscheiden. Kein teilweiser House-Shortcut.
- Response und UI nennen mindestens Allocation-ID/-Version, Policyversion,
  CMA-ID/As-of, gross/net, Feeannahme, Constraint-Hash, Berechnungsmodus und
  deterministische Limitierung.
- Eine Änderung dieser Basis macht die alte Rechnung stale; PDF und
  Beratungsprotokoll verwenden denselben Snapshot.

### 6. Policy-A/B nicht separat flicken

`AB-MODEL-001` bleibt maßgeblich. Entweder wird der Ablauf ehrlich als
House-Matrix-Konfigurationsdiff ohne Netto-/Backtestclaim geführt, wobei auch
dann Targets innerhalb der ausgegebenen Bänder liegen müssen, oder er
vergleicht zwei vollständige immutable Strategy-Contexts mit identischer
CMA-/Goal-/Cashflow-/Fee-/Stressbasis. Ein lokaler Rebalance-Aufruf allein
schließt diesen älteren Befund nicht.

## Zuerst zu materialisierende rote Tests

### Zero-Semantik

1. Policy-RE-Cap null ergibt effektives RE-Maximum und Target null;
2. Policy-Alternatives-Cap null ergibt effektives Maximum und Target null;
3. House-, stochastic-, Shadow-, Fallback- und Sensitivity-Pfade erhalten
   dieselben Null-Caps;
4. A/B und Retirement publizieren keine positive ausgeschlossene Quote;
5. `None` und `0` erzeugen bewusst verschiedene Resultate;
6. Zero-Risk-Budget wird entweder schemaweit abgelehnt oder überall strikt
   ausgeführt, einschließlich contextlosem Activation-Guard.

### Bounds und Persistenz

7. Policy-Cap unter House-Minimum blockiert Draft/Update/Activate;
8. vorhandene invertierte Policy blockiert House-Generate fail-closed;
9. `_rebalance_to_total()` lehnt jedes `min > max` vor Mutation ab;
10. Summe der Minima über 10.000 und Summe der Maxima unter 10.000 blockiert;
11. jede Rückgabe erfüllt Min/Target/Max und Summe exakt;
12. TargetAllocation-Write lehnt serverseitig invertierte Bänder ab;
13. stochastic und House verwenden dieselbe Domainexception und denselben
    strukturierten Fehlercode;
14. direkte Legacy-DB-Zeile kann ohne Quarantäne nicht publiziert werden.

### Retirement-Basis

15. aktuelles TA-Target unterscheidet sich vom House-Target; Spending nutzt TA;
16. Equity-Floor und positive RE-/Alt-Caps verändern die Renditebasis exakt;
17. stochastic Allocation wird nicht durch House-Targets ersetzt;
18. stale/missing/legacy TA führt zu 409 oder explizitem Candidate-Modus;
19. Snapshot-CMA statt beliebiger Live-CMA wird verwendet;
20. Fee-/TER-Basis ist gebunden und gross/net korrekt bezeichnet;
21. Allocation-/Policy-/CMA-/Constraint-Hash stehen im Response;
22. Strategieänderung invalidiert alte Spending-Evidence;
23. UI, PDF und Beratungsprotokoll zeigen dieselbe Basis und Annuität;
24. Manipulation eines Basisankers blockiert fail-closed.

### Bestehendes A/B-Finding

25. ausgegebene A/B-Gewichte liegen immer innerhalb der ausgegebenen Bänder;
26. Null-Cap und Equity-Floor wirken in A/B oder der Ablauf verweigert den
    Backtestclaim;
27. vollständiger Fix erfüllt zusätzlich alle Tests aus `AB-MODEL-001`.

## Verifikation dieser Audit-Runde

Zuerst liefen fünf kurzlebige, danach entfernte Audit-Probes:

1. öffentliche Zero-Domänen für Policy-Caps und Risikobudget;
2. direkte Null-Cap-Komposition und Rebalance;
3. echter produktiver House-Generate mit RE-/Alt-Cap null;
4. echter produktiver House-Generate mit invertierten effektiven Bändern;
5. echter Max-Pension-Spending-Service mit machbaren Caps/Equity-Floor und
   instrumentierter Metrikbasis.

Ergebnis: **5 passed**, 0 failed. „Grün“ bedeutet hier, dass die erwarteten
Gegenbeispiele deterministisch bestätigt wurden.

Danach liefen die angrenzenden Bestands-Suites:

```powershell
python -m pytest -q --disable-warnings `
  tests/test_allocation_rebalance_normalization.py `
  tests/test_house_matrix_real_estate_cap.py `
  tests/test_house_matrix_yaml_loader.py `
  tests/test_optimizer_objective_constraints.py `
  tests/test_optimizer_integration.py `
  tests/test_optimizer_production_contract.py `
  tests/test_backtest_ab.py `
  tests/test_sprint_a_quick_wins.py `
  tests/test_optimizer_policy_archive.py `
  tests/test_reference_data_fail_closed_gates.py
```

Ergebnis: **157 passed**, 0 failed, 57,74 Sekunden. Zusammen mit den fünf
einmaligen Probes wurden 162 unterschiedliche Checks ausgeführt.

Die grünen Bestandstests beweisen normale 20-Prozent-Caps, Equity-Floor-
Ableitung, lösbare/unlösbare Gesamtsummen, stochastic Effective-Bounds,
Pension-Plausibilität und Policy-Archive. Sie decken gerade nicht ab:

- Policy-Cap exakt null;
- positives Policy-Maximum unter House-Minimum;
- Persistenz von `min > target/max` beziehungsweise Target über Max;
- Pension-Metrikbasis gegen effektive oder aktuelle Allocation;
- contextlosen Zero-Risk-Activation-Guard.

Nicht ausgeführt wurden vollständige Backend-/Frontend-Suites, echte Browser-
E2E, Electron-Packaging, PDF-Pixelvergleich, PostgreSQL-Constraint-/
Concurrencytests und Zielumgebungs-Replay. Diese gehören zur
Implementierungsabnahme.

## Abschließender Selbst-Audit dieser Runde

Der Audit wurde vor Dokumentationsabschluss nochmals gegen folgende Fragen
geprüft:

1. **Ist der Null-Cap-Fall öffentlich zulässig?** Ja; Create und Update
   erlauben einschließlich null. Der Befund beruht nicht auf ungültigem Input.
2. **Ist der produktive Schaden erreicht?** Ja; der echte House-Generate
   persistierte positive ausgeschlossene Buckets und offene Maximalbänder.
3. **Ist der invertierte Fall nur theoretisch?** Nein; der echte Generate
   persistierte beide invertierten Tripel und Targets oberhalb der Policy-Caps.
4. **Ist die Retirement-Reproduktion künstlich infeasible?** Nein; Caps 600/
   400 lagen über den Minima 500/300, die Rebalance war exakt lösbar.
5. **Wurde A/B doppelt gezählt?** Nein; es bleibt ausdrücklich Erweiterung
   von `AB-MODEL-001`.
6. **Wurde Activation-Completeness doppelt gezählt?** Nein; der invertierte
   Runtime-/Persistenzfall erweitert die bestehende ID.
7. **Wird ein stochastic Positivoutput mit Null-Cap behauptet, ohne ihn
   ausgeführt zu haben?** Nein; dokumentiert ist die statisch verifizierte
   falsche Candidate-Bound-Komposition. Der echte Persistenzprobe betrifft den
   House-Modus.
8. **Ist Deterministik mit Nachhaltigkeit verwechselt?** Nein; der bestehende
   Disclosure bleibt erhalten. Neu beanstandet wird ausschließlich die falsche
   Strategie-/Evidencebasis.
9. **Sind Produkt- oder Teständerungen versteckt?** Nein; der temporäre Probe
   wurde entfernt. Das Manifest enthält nur Dokumentation.
10. **Sind Testzahlen und Grenzen transparent?** Ja; 5 Probes und 157
    Bestandstests sind getrennt ausgewiesen, nicht ausgeführte Gates ebenfalls.

Ergebnis des Selbst-Audits: **keine Korrektur der zwei neuen P1 oder ihrer
Priorität erforderlich**. „Perfekt“ bedeutet hier nicht, dass das gesamte
Produkt vollständig bewiesen wäre; es bedeutet, dass Scope, Reproduktion,
Deduplizierung, Gegenbeispiele, Lösungsweg und verbleibende Testgrenzen dieser
Runde konsistent und nachprüfbar sind.

## Definition of Done

Der Release-Hold dieser Runde kann erst aufgehoben werden, wenn:

1. beide neuen Finding-IDs durch rote Vorher-/grüne Nachher-Tests geschlossen
   sind;
2. null und Missing in allen Constraintpfaden getrennt bleiben;
3. ein gemeinsamer Effective-Constraint-Compiler alle Modi und Verbraucher
   speist;
4. Composer, Rebalancer, Runtime und Persistenz dieselben Bounds-Invarianten
   fail-closed prüfen;
5. Policy-Draft/Update/Activate keine Caps unter House-Minima zulässt;
6. House, stochastic, Shadow, Fallback und Sensitivity dieselben als global
   definierten harten Constraints ausführen;
7. Max-Pension-Spending an eine verifizierte Allocation-/CMA-/Fee-/
   Constraintbasis gebunden ist;
8. `AB-MODEL-001` vollständig statt nur lokal kosmetisch geschlossen ist;
9. Legacy-Policies, Allocations, Recommendations und Publikationen gescannt,
   replayt oder quarantänisiert sind;
10. fokussierte und vollständige Backend-, React-, Classic-, Browser-,
    Electron-, PDF-, PostgreSQL- und Zielumgebungsabnahmen grün sind.

## Dokumentationsmanifest dieser Runde

Nur diese fünf Pfade dürfen durch die Runde verändert werden:

1. `docs/audits/2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`
