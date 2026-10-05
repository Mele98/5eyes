# Sub-Asset-Risikoaggregations-, Cache- und Replay-Integritätsaudit

**Kontrollrunde 51 · Stand 05.10.2026 · Status: Release-Hold**

## Kurzfazit

Die Sub-Asset-Risikomodellierung beeinflusst Solver, Monte Carlo,
Asset Allocation und Ziele materiell, ist aber weder als genehmigtes
Modellinput noch als vollständige Cache-/Replay-Identität gebunden:

1. Ein globaler Umgebungswert `sub_class_intra_correlation` ersetzt für jede
   Sub-Asset-Paarung in jedem Bucket die fehlende Korrelationsstruktur. Default
   `1.0` bedeutet perfekte Korrelation und damit keine Intra-Bucket-
   Diversifikation. Quelle, Jurisdiktion, Zeitraum, As-of-Date und Approval
   fehlen.
2. Der Wert verändert die effektiven Bucket-Volatilitäten und somit die
   Szenariopfade, erscheint aber weder in der persistierten Optimizer-
   Modellbasis noch im `allocation_context_hash`, im Sensitivity-
   `model_input_hash` oder in UI/PDF.
3. Der Scenario-Cache bindet CMA-ID und Sub-Mix, nicht jedoch die effektiven
   `ScenarioInputs`. Nach einer Änderung des Risikomodells unter identischer
   CMA/Sub-Allokation liefert er alte Pfade als gültigen Cache-Hit.

Neu bestätigt sind drei P1:

- `SUBRISK-GLOBAL-RHO-MODEL-001`;
- `SUBRISK-CONTEXT-REPLAY-001`;
- `SCENARIO-CACHE-EFFECTIVE-INPUT-001`.

Die Produktprobe mit unveränderten Returns, Volatilitäten, CMA-ID und
Sub-Allokationen ergab:

```text
globales ρ     Equity-Vol   Bond-Vol   Portfolio-Vol
1.0              1645         470           982 bps
0.8              1536         447           918 bps
0.5              1356         410           812 bps
0.0               985         338           594 bps
```

Die 388-bps-Spannweite entsteht allein aus einem nicht evidencegebundenen
Deploymentsetting. Returns und Sub-Allokation bleiben in allen vier Läufen
identisch.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
3b9f17c
docs(audit): document CMA risk model parity gaps
```

Geprüft wurden:

- Sub-Asset-CMA-Parsing und gewichtete Bucket-Metriken;
- Intra-Bucket-Varianzformel und globales Korrelationssetting;
- stochastischer Optimizer, allgemeiner Monte Carlo und erwartete Kennzahlen;
- Standard- und Importance-Sampling-Scenario-Cache;
- Allocation-Context-, Effective-Constraints- und Sensitivity-Hashes;
- persistierte Modellbasis, Reload-/Drift-Prüfung und Methodology-Anzeige;
- Electron-Sub-CMA-Editor und Kunden-/Auditdarstellung;
- bestehende Weighted-Metrics-, Sub-Allocation-, Cache-, Effective-Context-
  und Methodology-Tests.

Produktionscode, Schema, Migrationen, Tests und UI wurden nicht verändert.
Persistiert werden ausschließlich die fünf Dokumentationspfade des
Auditmanifests.

## Verhältnis zu Runde 50

Runde 50 behandelt die fünfdimensionale Inter-Bucket-Korrelationsmatrix,
Tailmomente und consumerübergreifende Verteilungsparität. Runde 51 untersucht
die vorgelagerte Kompilierung mehrerer Sub-Assets zu genau diesen fünf
Bucket-Volatilitäten sowie deren Cache-/Replay-Identität.

Die IDs überschneiden sich nicht:

- `CMA-CORRELATION-JURISDICTION-PROVENANCE-001` betrifft die 5×5-Bucketmatrix.
- `SUBRISK-GLOBAL-RHO-MODEL-001` betrifft die Korrelation **innerhalb** eines
  Buckets vor dessen Aggregation.
- Beide Ebenen müssen in einem gemeinsamen effektiven Kovarianzmodell
  zusammengeführt und evidencegebunden werden.

## Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `SUBRISK-GLOBAL-RHO-MODEL-001` | P1 | neu bestätigt | Ein globaler, unprovenancierter Umgebungswert gilt gleich für jedes Sub-Asset-Paar und jeden Bucket; Default 1.0 unterstellt perfekte Korrelation. |
| `SUBRISK-CONTEXT-REPLAY-001` | P1 | neu bestätigt | Der outputwirksame Wert und die daraus materialisierten Bucket-Sigmas fehlen in Modellbasis, Allocation-/Sensitivity-Hashes, Driftprüfung und Publikation. |
| `SCENARIO-CACHE-EFFECTIVE-INPUT-001` | P1 | neu bestätigt | Standard-/IS-Cache identifizieren Pfade über CMA-ID/Sub-Mix statt über den vollständigen effektiven Szenarioinput; geänderte Sigmas können alte Pfade treffen. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
Sub-CMA vols + Sub-Allocation weights
                 |
                 v
settings.sub_class_intra_correlation
global, default 1.0, not in CMA/evidence
                 |
                 v
bucket sigma = sqrt(w' Sigma_sub w)
                 |
        +--------+---------+
        |                  |
Optimizer ScenarioInputs   Reporting MC
        |                  |
        +--> Scenario Cache key
             CMA id + sub-mix + horizon/seed
             effective sigma/rho missing
                 |
                 v
Allocation / Goal Probability / Sensitivity / UI / PDF
context hashes omit the output-driving sub-risk model
```

## `SUBRISK-GLOBAL-RHO-MODEL-001`

### Repository-Beleg

- `config.py:321-327` definiert genau einen
  `sub_class_intra_correlation`-Wert für das gesamte System; Default ist
  `1.0 = perfekt korreliert`.
- Der Validator erlaubt jeden Wert in `[0,1]`, verlangt aber keine Quelle,
  Modellversion oder Umgebungskonsistenz (`config.py:356-365`).
- `_weighted_bucket_metrics()` liest das globale Setting direkt
  (`services/portfolio_engine_cma.py:511-535`). Es ist weder Parameter der
  Funktion noch Feld der CMA.
- Für jeden Bucket und jedes Paar wird dieselbe equicorrelation verwendet.
  Equity Schweiz/Global, Equity Global/EM, CHF IG/High Yield und alle anderen
  künftigen Paare erhalten denselben Wert.
- Die Implementierungsdokumentation bezeichnet das als „Block-Diagonal-
  Vola“; tatsächlich werden Sub-Assets zunächst zu fünf Skalarsigmas
  kollabiert und danach mit der separaten 5×5-Bucketmatrix korreliert.
  Paarindividuelle Cross-Bucket-Korrelationen existieren nicht.
- Die Roadmap nennt eine volle Sub-Correlation-Matrix ausdrücklich weiterhin
  als Architektur-Refactor/ausstehende Sub-Asset-Tiefe.

### Produktive Reproduktion

Verwendet wurden die im Bestandstest etablierten Sub-CMA-Werte:

```text
Equity Schweiz 1450 bps, Global 1500 bps, EM 1900 bps
Sub-Mix Equity 30/30/40

Bond CHF IG 350 bps, High Yield 950 bps
Sub-Mix Bonds 80/20

Portfolio 60 % Equity, 30 % Bonds, 5 % Alternatives, 5 % Liquidity
```

Nur das globale ρ wurde variiert:

```text
ρ       Equity-Bucket   Bond-Bucket   Portfolio
1.0        1645             470          982 bps
0.8        1536             447          918 bps
0.5        1356             410          812 bps
0.0         985             338          594 bps
```

Die Formel selbst ist für eine equicorrelierte Teilmatrix rechnerisch korrekt.
Der Befund ist der nicht genehmigte Modellvertrag: Ein einziger globaler Wert
steht für wirtschaftlich unterschiedliche Paarungen, und Default 1.0 ist eine
starke Annahme, keine neutrale technische Konstante.

### Wirkung

- Risk Budget, Markowitz-Kandidat und Zielallokation können sich ändern.
- VaR/CVaR, Downside, Drawdown und Zielwahrscheinlichkeit verschieben sich.
- Dieselbe CMA-ID kann je Deployment eine andere effektive Volatilität haben.
- Die sichtbaren Sub-CMA-Sigmas erklären den publizierten Bucket-/Portfolio-
  Risk nicht ohne den unsichtbaren globalen ρ-Wert.

### Erforderliche Lösung

1. Eine versionierte `SubAssetCovarianceEvidence` pro Jurisdiktion und
   Bucketuniversum einführen: Paarmatrix, Bucket-/Sleeve-IDs,
   Beobachtungsfenster, Frequenz, Estimator, Shrinkage, Währungs-/Hedge-Basis,
   As-of-Date, Quelle, Unsicherheit, Approval und Hash.
2. Ein globales equicorrelation-Modell darf nur als explizit genehmigter
   Fallback existieren; Scope und konservative Begründung müssen sichtbar
   sein. Ohne Evidence fail-closed.
3. Die volle Sub-Asset-Kovarianz zuerst materialisieren und erst danach auf
   Bucket-/Portfolioebene aggregieren. Cross-Bucket-Paarungen dürfen nicht
   still als uniformer Bucketwert behandelt werden.
4. Effective Sigmas, Covariance Hash und Aggregationsversion in Run Evidence
   persistieren.

## `SUBRISK-CONTEXT-REPLAY-001`

### Repository-Beleg

- Die persistierte `optimization_model_basis` enthält Tail-, Tax-, Horizon-
  und andere Methodikfelder, aber weder `sub_class_intra_correlation` noch
  effektive Bucket-Sigmas/Kovarianz
  (`services/portfolio_engine.py:2552-2789`).
- `allocation_context_payload` hasht Engine-Version, Policy-/CMA-/Assessment-
  ID, Input-Snapshot, Preferences, Targets, Sub-Allokationen, Constraints und
  Seed; das Sub-Risikomodell fehlt (`portfolio_engine.py:3963-3988`).
- Die Reload-Verifikation rekonstruiert denselben unvollständigen Payload
  (`portfolio_engine.py:4338-4358`). Eine geänderte Umgebung kann deshalb den
  Hash weiterhin erfolgreich verifizieren.
- Der Sensitivity-`model_input_hash` nimmt einen vollständigen CMA-Snapshot
  auf, aber keine globale Setting-/Effective-Sigma-Evidence
  (`portfolio_engine.py:5167-5263`).
- `_strategy_drift_warnings()` prüft CMA-ID und Eingabesnapshot, nicht die
  Sub-Risiko-Modellversion.
- Der Electron-Client zeigt einzelne Sub-CMA-Returns/-Volatilitäten, aber
  weder aggregierte Bucket-Sigmas noch verwendetes ρ, Matrix-/Modellhash oder
  Fallbackstatus (`5eyes_v2.html:7333-7338`, `10912-10936`).

### Replay-Bruch

Ein persistierter Allocation-Context kann auf Umgebung A mit `ρ=1.0`
erzeugt und auf Umgebung B mit `ρ=0.5` formal erfolgreich verifiziert werden:

```text
persistierte CMA-ID:              gleich
persistierter Sub-Mix:            gleich
allocation_context_hash inputs:   gleich
effektive Equity-Sigma:           1645 -> 1356 bps
effektive Bond-Sigma:               470 -> 410 bps
Portfolio-Sigma:                    982 -> 812 bps
```

Der Hash beweist damit die JSON-Struktur des gespeicherten Contexts, nicht die
tatsächlich verwendete stochastische Risikobasis.

### Erforderliche Lösung

1. `EffectiveRiskModelSnapshot` vor jeder Szenarioerzeugung materialisieren:
   rohe Sub-Sigmas, vollständige Sub-Covariance, Aggregationsversion,
   effektive Bucket-Sigmas, Inter-Bucket-Matrix und finale Covariance.
2. Den kanonischen Snapshot-Hash in Optimizer Context, Allocation Context,
   Sensitivity Input Hash, Reporting Model Basis und PDF/Signatur binden.
3. Reload/Finalize/PDF/Signatur blockieren, wenn aktuelle und persistierte
   Risk-Model-Hashes differieren. Keine Rekonstruktion aus heutigen Settings.
4. Umgebungsabhängige fachliche Inputs aus `Settings` entfernen oder als
   versionierte, deploymentidentische Referenzdaten mit Startup-Hash-Gate
   behandeln.

## `SCENARIO-CACHE-EFFECTIVE-INPUT-001`

### Repository-Beleg

- `ScenarioCache` dokumentiert den Key als CMA-ID, Horizon, Pfadzahl, Seed und
  Antithetic; `ScenarioInputs` selbst werden nicht gehasht
  (`services/optimizer/scenario_cache.py`).
- Der Standardkey enthält
  `("STD", cma_id, RETURN_MOMENT_MODEL_VERSION, horizon, n_paths, seed,
  antithetic)`.
- Der IS-Key ergänzt Shiftvektor, bindet aber ebenfalls keine Mu-, Sigma-,
  Tail- oder Faktorwerte.
- `solver.py:424-444` ergänzt bei Sub-Allokationen nur deren JSON-Hash an die
  CMA-ID. Das globale ρ und die daraus berechneten Sigmas fehlen.
- Der Cache-Kommentar nimmt an, CMA-Werte seien unter einer ID immutable.
  Diese Annahme schützt nicht vor outputwirksamen Settings außerhalb der CMA.

### Produktive Cache-Gegenprobe

1. CMA-ID, Sub-Mix, Horizon, Pfadzahl und Seed blieben identisch.
2. Bei `ρ=1.0` wurden ScenarioInputs mit Sigmas
   `[1645,470,820,1200,15]` erzeugt und gecacht.
3. Bei `ρ=0.5` entstanden korrekt neue Sigmas
   `[1356,410,820,1200,15]`.
4. Der zweite Cache-Aufruf lieferte trotzdem einen Hit und exakt die alten
   Pfade.
5. Ein direkter, ungecachter Build mit den neuen Inputs erzeugte andere Pfade.

```text
cached_old_equals_cached_new   True
cached_new_equals_direct_new   False
cache hits / misses            1 / 1
```

Ein temporärer Contract-Test verlangte, dass geänderte effektive Sigmas unter
sonst gleicher Identität andere Pfade liefern. Er schlug deterministisch mit
`assert not True` fehl und wurde danach entfernt.

### Erforderliche Lösung

1. Cache-Key ausschließlich aus vollständigem kanonischem
   `EffectiveScenarioInput` ableiten: Mu, Sigma, Tailmomente,
   Korrelations-/Faktorhash, Transform-/Momentmodellversion sowie alle
   stochastischen Aktivierungsparameter.
2. CMA-ID und Sub-Mix dürfen Metadaten sein, nicht Proxy für effektive Inputs.
3. Standard- und IS-Cache verwenden denselben Basis-Inputhash; IS ergänzt
   exakt Shift-/Weight-/Estimatorversion.
4. Cachewerte immutable/read-only speichern und beim Hit optional Shape,
   Inputhash und Modelversion verifizieren.
5. Konfigurations-/Referenzdatenwechsel invalidieren nicht nur pro CMA,
   sondern über den geänderten Inputhash automatisch alle betroffenen Keys.

## Kanonische Zielarchitektur für Claude

```text
SubAssetRiskObservation
  sub_asset_id / jurisdiction / currency / hedge_basis
  as_of_date / observation_window / frequency
  volatility / pairwise_correlations / source_snapshot_hash

SubAssetCovarianceEvidence
  universe_version / estimator_version / shrinkage_policy
  raw_covariance / effective_covariance / PSD_diagnostics
  fallback_scope / approval / covariance_hash

EffectiveScenarioInput
  cma_id / sub_allocation_blueprint_hash
  mu_vector / sigma_vector / tail_vector
  sub_covariance_hash / bucket_covariance_hash / factor_hash
  aggregation_version / distribution_version
  canonical_input_hash

ScenarioArtifact
  canonical_input_hash / seed / horizon / n_paths
  estimator_and_shift_version / paths_hash / weights_hash
```

Der `canonical_input_hash` wird Cache-Key-Basis und muss unverändert durch
Optimizer, Sensitivity, Stress, allgemeines MC, Allocation, Goals, UI, PDF,
Signatur und Handoff laufen.

## Verbindliche Regressionstests

- Eine Änderung irgendeines effektiven Mu-/Sigma-/Tail-/Korrelations-/Faktor-
  Inputs ändert den Scenario-Cache-Key.
- Identische CMA-ID und identischer Sub-Mix mit verändertem Risk-Model-Hash
  dürfen keinen Cache-Hit erzeugen.
- Standard- und IS-Cache binden denselben vollständigen Basisinput.
- `ρ=1.0/0.8/0.5/0.0` erzeugt reproduzierbar die analytisch erwarteten
  Bucket-Sigmas.
- Paarindividuelle Sub-Korrelationen erzeugen die volle erwartete Covariance;
  Bucketaggregation entspricht `A Σ_sub A'`.
- Fehlende/inkompatible Sub-Covariance-Evidence blockiert Approval und Run.
- Allocation-Context- und Sensitivity-Hashes ändern sich mit jeder fachlichen
  Risikomodelländerung.
- Persistierter Context mit abweichendem aktuellem Risk-Model-Hash blockiert
  Reload, Finalize, PDF, Signatur und Handoff.
- Zwei Zielumgebungen mit identischem Evidence-Hash reproduzieren Bucket-
  Sigmas, Covariance, Pfade und Ergebnisse bitgenau.
- UI/PDF zeigen effektive Bucket-Sigmas, verwendete Matrix-/Fallbackbasis,
  As-of-Date und Modellversion; einzelne Sub-CMA-Werte allein genügen nicht.
- Legacy-Allocations ohne Risk-Model-Snapshot werden replayed oder
  quarantänisiert, nicht still unter heutigen Settings neu interpretiert.

## Verifikation dieser Runde

### Produktive Probes

- `_weighted_bucket_metrics()` mit identischen CMA-/Sub-Allokationen unter
  vier ρ-Werten ausgeführt.
- `_portfolio_volatility_bps()` auf den resultierenden Bucket-Sigmas und der
  produktiven Inter-Bucket-Matrix ausgeführt.
- `scenario_inputs_from_cma()` vor/nach Settingwechsel verglichen.
- `build_scenario_paths_cached()` mit identischem aktuellem Key, aber
  verschiedenen effektiven Sigmas ausgeführt und gegen den ungecachten Build
  geprüft.
- Temporären Red-Contract-Test für vollständige Cache-Identität ausgeführt und
  entfernt.

### Bestandsgate

```text
104 passed, 1 Pytest-Cache-Warnung
```

Ausgeführt wurden:

- `test_audit_z4_weighted_metrics.py`;
- `test_sub_allocation_aware_returns.py`;
- `test_optimizer_scenario_cache.py`;
- `test_optimizer_effective_context.py`;
- `test_methodology_models_audit.py`;
- `test_optimizer_production_contract.py`.

Die Warnung betrifft den vorbestehenden lokalen Pytest-Cache-ACL-Zustand. Der
temporäre Test, die Probe und alle neu angelegten Testartefakte wurden entfernt.

## Release-Entscheid

Sub-Asset-basierte reale Beratung, stochastische Zielwahrscheinlichkeit,
Sensitivity, Stress und Publikation bleiben im Release-Hold, bis:

1. die volle effektive Sub-Asset-Kovarianz fachlich genehmigt, versioniert und
   provenanciert ist;
2. outputwirksame Risikoparameter keine ungebundenen Deploymentsettings mehr
   sind;
3. Allocation-/Sensitivity-/Run-Evidence den vollständigen effektiven
   Risikomodellhash bindet;
4. der Scenario-Cache ausschließlich vollständige effektive Inputs
   identifiziert;
5. die dokumentierten Red-/Golden-/Replay-/Cross-Channel-Tests und die
   Zielumgebungsabnahme grün sind.

## Reihenfolge für Claude

1. Den roten Cache-Test permanent anlegen und um Standard-/IS-/Reload-/
   Zielumgebungsvarianten erweitern.
2. `SubAssetCovarianceEvidence` und den kanonischen
   `EffectiveScenarioInput`-Compiler implementieren.
3. Den globalen Setting-Fallback entfernen oder als explizit genehmigte,
   versionierte Evidence modellieren.
4. Cache, Allocation Context, Sensitivity, Drift-/Finalize-Gates und
   Publikation auf denselben Inputhash umstellen.
5. Legacy-Contexts replayen/quarantänisieren und danach vollständige
   Backend-/UI-/PDF-/Cross-Environment-Gates ausführen.

Keine Reparatur durch bloßes Ergänzen von `ρ` an einen UI-Text oder an den
heutigen Cache-Key: Maßgeblich ist der Hash des vollständig materialisierten
effektiven Kovarianz- und Verteilungsinputs.
