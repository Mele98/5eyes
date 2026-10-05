# CMA-Korrelations-, Tail-Moment- und Runtime-Paritäts-Integritätsaudit

**Kontrollrunde 50 · Stand 05.10.2026 · Status: Release-Hold**

## Kurzfazit

Die stochastische Risikobasis ist noch nicht als genehmigtes, jurisdiktions-
und laufzeitkonsistentes Modell geschlossen:

1. Fehlt eine Korrelationsmatrix, verwenden Optimizer und Haupt-Monte-Carlo
   für CH, DE, US und jede weitere Jurisdiktion dieselbe hartcodierte und im
   Code selbst als „CH-Markt, konservativ“ bezeichnete Matrix. Quelle,
   Beobachtungszeitraum, Schätzverfahren, As-of-Date und Modellversion sind
   nicht Bestandteil der CMA.
2. `NULL` bei Schiefe und Exzess-Kurtosis wird in beiden Engines zu `0`. Ein
   unbekannter oder nie geschätzter Wert ist damit nicht von der positiven
   Modellbehauptung „symmetrisch/normal“ unterscheidbar. Die Runtime-
   Vollständigkeitsprüfung verlangt Return und Volatilität, aber weder
   Korrelation noch Tail-Momente.
3. Für gespeicherte Tail-Momente existieren widersprüchliche Parameterdomänen:
   Der Optimizer begrenzt Schiefe auf `[-1,1]` und Exzess-Kurtosis auf `[0,8]`;
   der aktive Haupt-MC-Tailpfad verwendet Rohwerte; der Legacy-Helfer begrenzt
   auf `[-3,3]` und `[-2,30]`. Das API-Schema akzeptiert zugleich beliebige
   Integer.
4. Tail-Momente sind im stochastischen Optimizer immer aktiv, im allgemeinen
   Reporting-MC dagegen nur über `tailRisk`/`cornishFisher`; Default ist aus.
   Der aktive Electron-Client exponiert weder die zehn CMA-Tailfelder noch
   diesen Simulationsschalter. Damit kann dieselbe genehmigte CMA je Consumer
   eine andere Renditeverteilung besitzen, ohne dass der Admin die Basis über
   den normalen Produktpfad vollständig steuern kann.

Neu bestätigt sind drei P1 und ein P2:

- `CMA-CORRELATION-JURISDICTION-PROVENANCE-001` – P1;
- `CMA-TAIL-MISSINGNESS-SEMANTICS-001` – P1;
- `CMA-TAIL-PARAMETER-DOMAIN-PARITY-001` – P1;
- `CMA-TAIL-ACTIVATION-GOVERNANCE-001` – P2.

Die Produktprobe zeigte für eine 40/35/15/5/5-Allokation bei unveränderten
Volatilitäten:

```text
Korrelationsbasis                         Portfolio-Volatilität
hartcodierter CH-Default                         669.4365 bps
Identität, nur Sensitivitätsvergleich            639.8920 bps
ρ = 0.50, nur Sensitivitätsvergleich              798.3818 bps
```

Identität und ρ=0,50 sind keine empfohlenen Ersatzmodelle. Die Rechnung zeigt,
dass der implizite, unprovenancierte Fallback eine materielle Risikoeingabe ist.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
9148e28
docs(audit): document bond curve model risks
```

Geprüft wurden:

- CMA-Schema, Persistenz, Versionsupdate und Runtime-Vollständigkeit;
- Korrelationsparser, Standardmatrix und beide Korrelationsfaktor-Consumer;
- stochastischer Optimizer, Haupt-Monte-Carlo und gemeinsame Momentenabbildung;
- Cornish-Fisher-Domänen, Clamps und Modellbasis-Publikation;
- Nicht-CH-CMA-Pipeline und CH-Default-Seed;
- Electron-CMA-Editor und Monte-Carlo-Methodikdarstellung;
- bestehende Korrelations-, CMA-, Tail-, Preference-, Reference-Mandate- und
  Methodology-Tests.

Produktionscode, Schema, Migrationen, Tests und UI wurden nicht verändert.
Persistiert werden ausschließlich die fünf Dokumentationspfade des
Auditmanifests.

## Verhältnis zu früheren Audits

Der Audit vom 22.09.2026 beanstandete die falsche Dreiecksannahme bei
allgemeinen PSD-Korrelationsfaktoren sowie Estimator-, Cache- und
Stress-Evidence. Runde 50 dupliziert diese IDs nicht. Sie untersucht die
**Herkunft und Semantik der effektiven Matrix**, NULL-Tailwerte und die
Parameter-/Aktivierungsparität zwischen den Consumern.

Runde 48 beanstandete Nicht-CH-Messbasis, Snapshot und Approval-Preflight;
Runde 50 ergänzt, dass selbst eine formal vollständige und genehmigte
Nicht-CH-CMA ohne eigene Risikobasis still die CH-Korrelation und Gaussian-
Marginalen erbt. Alle Findings sind gemeinsam zu schließen.

## Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `CMA-CORRELATION-JURISDICTION-PROVENANCE-001` | P1 | neu bestätigt | Fehlende Matrix materialisiert für jede Jurisdiktion dieselbe unversionierte CH-Defaultmatrix; die effektive Risikobasis besitzt keine fachliche Provenienz. |
| `CMA-TAIL-MISSINGNESS-SEMANTICS-001` | P1 | neu bestätigt | `NULL` und explizit `0` sind zur Laufzeit identisch; Completeness/Approval unterscheidet „nicht geschätzt“ nicht von „normal/symmetrisch genehmigt“. |
| `CMA-TAIL-PARAMETER-DOMAIN-PARITY-001` | P1 | neu bestätigt | API, Optimizer, Haupt-MC und Legacy-Helfer akzeptieren bzw. transformieren unterschiedliche Tail-Domänen; gleiche persistierte Werte erzeugen consumerabhängige Verteilungen. |
| `CMA-TAIL-ACTIVATION-GOVERNANCE-001` | P2 | neu bestätigt | Optimizer aktiviert Tail-Momente immer, Reporting-MC nur opt-in; der normale Electron-Pfad exponiert weder Tail-CMA-Felder noch Aktivierung. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
CapitalMarketAssumption
  correlation_matrix_json = NULL
  *_skewness_bps = NULL
  *_excess_kurt_bps = NULL
              |
              +--> NULL correlation -> hardcoded "CH-Markt" matrix
              |                         for CH / DE / US / ...
              |
              +--> NULL tail moment -> 0 -> Gaussian assertion
              |
              +--> persisted non-zero tail moments
                        |
             +----------+-------------------------+
             |                                    |
      stochastic optimizer                 reporting Monte Carlo
      always Cornish-Fisher                default lognormal
      clamp s[-1,1], k[0,8]                tail opt-in; raw s/k
             |                                    |
             +----------> Allocation / Goals / UI / PDF
                           consumer-dependent risk basis
```

## `CMA-CORRELATION-JURISDICTION-PROVENANCE-001`

### Repository-Beleg

- `services/optimizer/scenario_engine.py:143-152` nennt die kanonische
  Standardmatrix ausdrücklich „CH-Markt, konservativ“.
- `scenario_inputs_from_cma()` übergibt bei leerem Payload genau diese Matrix
  an `parse_correlation_matrix_json()` (`scenario_engine.py:602-657`).
- `_build_cholesky_from_cma()` nutzt dieselbe Matrix im Haupt-MC
  (`services/portfolio_engine_cma.py:189-217`). Der Parameter `jurisdiction`
  wird dabei nicht ausgewertet.
- `_DEFAULT_CORRELATION_MATRIX` in `services/portfolio_engine.py:1184-1191`
  enthält nur Zahlen und Bucketlabels; Quelle, Beobachtungszeitraum,
  Schätzmethode, Marktstichtag und Modellversion fehlen.
- Die Nicht-CH-Datenpipeline setzt `correlation_matrix_json` nicht
  (`services/jurisdiction/data_pipeline.py:394-410`).
- `validate_runtime_cma_completeness()` verlangt für Nicht-CH Returns und
  Volatilitäten, aber keine Matrix (`services/cma_validation.py:44-90`).
- Bestehende Tests schreiben den Fallback als erwünschtes Verhalten fest,
  unter anderem `test_cholesky_and_horizon.py` und
  `test_cma_strict_runtime_contract.py`.

### Reproduktion

Ein produktiver Aufruf von `_build_cholesky_from_cma()` mit identischem leeren
Payload und lediglich variierter Jurisdiktion ergab:

```text
CH factor @ factor.T == hardcoded CH matrix
DE factor @ factor.T == hardcoded CH matrix
US factor @ factor.T == hardcoded CH matrix
CH factor == DE factor == US factor: True
```

Für eine 40/35/15/5/5-Allokation mit Bucket-Volatilitäten
1525/390/820/1200/15 bps folgt analytisch aus `sqrt(w'Σw)`:

```text
CH-Default                         669.4365 bps
Identität                          639.8920 bps
gleichkorreliert ρ=0.50            798.3818 bps
```

Die Spannweite von rund 158 bps zwischen den reinen Sensitivitätsankern kann
Solver-Ranking, VaR/CVaR, Zielwahrscheinlichkeit und Eignungsaussagen ändern.

### UI-/Persistenzwirkung

Der Electron-Editor meldet bei fehlendem Payload nur „Standardmatrix“ und
lädt die gleiche hartcodierte Matrix in das Grid
(`5eyes_v2.html:10721-10736`, `11060-11066`). Ein späteres Speichern sendet
sie als explizites JSON (`11233-11269`). Dadurch kann ein technisch
impliziter, unprovenancierter Fallback durch eine sachfremde Admin-Änderung zur
scheinbar bewusst gepflegten CMA-Eingabe werden. Die Anzeige nennt weder
„CH-Markt“ noch Quelle, As-of-Date oder Gültigkeitsbereich.

### Erforderliche Lösung

1. `CorrelationModelEvidence` einführen: Jurisdiktion, Bucketdefinition,
   Returnfrequenz, Währung/Hedge-Basis, Beobachtungsfenster, Estimator,
   Shrinkage-/Missing-Data-Policy, Matrix, Eigenwerte, As-of-Date, Quelle,
   Modellversion und Hash.
2. Nicht-CH ohne genehmigte passende Matrix fail-closed behandeln. Ein
   explizit genehmigter globaler Fallback ist nur zulässig, wenn sein Scope
   und seine Unsicherheit Bestandteil der Evidence sind.
3. Runtime und UI materialisieren die **effektive** Matrix samt Provenienz;
   ein Read darf `NULL` nicht unbemerkt in eine speicherbare Hausannahme
   verwandeln.
4. Approval, Aktivierung, Run, Allocation, Sensitivity, PDF und Signatur an
   denselben Matrix-/Evidence-Hash binden.

## `CMA-TAIL-MISSINGNESS-SEMANTICS-001`

### Repository-Beleg

- Alle zehn Tailfelder sind nullable
  (`models/allocation.py:266-279`, `schemas/allocation.py:572-581`).
- Optimizer und Haupt-MC lesen sie jeweils mit
  `getattr(..., 0) or 0`; `None` und `0` werden identisch
  (`scenario_engine.py:639-647`, `portfolio_engine_mc_simulation.py:1186-1194`).
- Der Datenbankkommentar definiert ausdrücklich `NULL/0 -> Normal-Verteilung`
  (`database.py:456-468`).
- Der CH-Runtime-Seed setzt weder Matrix noch Tailmomente
  (`portfolio_engine.py:1678-1727`).
- Die Nicht-CH-Pipeline setzt ebenfalls keine Tailmomente
  (`data_pipeline.py:394-410`).
- `validate_runtime_cma_completeness()` prüft diese Felder nicht.
- Der vorhandene Test
  `test_scenario_inputs_falls_back_to_zero_when_skew_kurt_none` bestätigt
  gerade die problematische Gleichsetzung.

### Warum NULL nicht Null ist

`0` kann eine bewusst geschätzte und genehmigte Aussage sein:

```text
skewness = 0
excess kurtosis = 0
=> symmetrische Normalinnovation innerhalb des gewählten Modells
```

`NULL` bedeutet dagegen mindestens „nicht vorhanden“, möglicherweise „nicht
geschätzt“, „nicht anwendbar“ oder „Migration noch nicht abgeschlossen“. Die
Laufzeit macht daraus ohne Review dieselbe starke Modellannahme.

Eine fixed-seed-Produktprobe mit identischen Mittelwerten, Volatilitäten und
Korrelationen zeigte für 100.000 Pfade über zehn Jahre:

```text
                                      Gaussian       Equity s=-0.5/k=2.5
Terminal-P1                            0.92974             0.91038
Terminal-P5                            1.06213             1.05807
Verlustwahrscheinlichkeit              2.518 %             2.894 %
```

Die Werte sind kein Kalibrierungsvorschlag. Sie zeigen, dass „fehlend wird
Null“ eine materielle, keine neutrale Defaultentscheidung ist.

### Erforderliche Lösung

1. Pro Bucket diskriminierten Zustand speichern:
   `estimated | explicitly_gaussian | unavailable | not_applicable`.
2. `estimated` verlangt Wert, Quelle, Zeitraum, Frequenz, Estimator,
   Konfidenz/Unsicherheit und As-of-Date; `explicitly_gaussian` verlangt eine
   bewusste Model-Owner-Freigabe.
3. Runtime-Completeness und Approval blockieren `unavailable`/unreviewed für
   produktive stochastische Runs oder wählen einen klar sichtbaren,
   genehmigten konservativen Ersatz mit Evidence.
4. Legacy-NULLs migrieren: replaybar klassifizieren oder quarantänisieren;
   niemals still als explizite Nullwerte umdeuten.

## `CMA-TAIL-PARAMETER-DOMAIN-PARITY-001`

### Repository-Beleg

- `CapitalMarketAssumptionCreate` akzeptiert Tailmomente als optionale Integer,
  ohne fachliche Min-/Max-Domäne (`schemas/allocation.py:572-581, 624-641`).
- Die Probe akzeptierte sowohl `skewness_bps=50000` / `kurt_bps=300000` als
  auch `20000` / `-10000` ohne ValidationError.
- Der Optimizer clippt auf Schiefe `[-1,1]` und Exzess-Kurtosis `[0,8]`
  (`optimizer/distributions.py:33-47`,
  `optimizer/scenario_engine.py:81-125`).
- Der Haupt-MC übergibt die Rohwerte an
  `arithmetic_moments_to_log_parameters()` und danach direkt an
  `bounded_cornish_fisher()` (`portfolio_engine_mc_simulation.py:1186-1202,
  1380-1393`). `bounded_cornish_fisher()` begrenzt nur das resultierende
  Innovationsquantil auf ±8, nicht die Parameter (`return_moments.py:44-60`).
- `_cornish_fisher_transform()` besitzt nochmals andere Grenzen: Schiefe
  `[-3,3]`, Exzess-Kurtosis `[-2,30]`; die zugehörigen Tests schreiben diese
  Legacy-Domäne fest.

### Numerische Gegenprobe

Für dieselben akzeptierten Parameter und `z = [-2, 0, 2]`:

```text
s=2.0, k=-1.0
Optimizer, effektiv s=1/k=0     [-1.333333, -0.166667, 2.333333]
Haupt-MC, Rohwerte              [-0.250000, -0.333333, 2.250000]
Legacy-Helfer                   [-0.250000, -0.333333, 2.250000]

s=5.0, k=30.0
Optimizer, effektiv s=1/k=8     [-2.000000, -0.166667, 3.000000]
Haupt-MC, Rohwerte              [ 2.166667, -0.833333, 2.833333]
Legacy, effektiv s=3/k=30       [-1.500000, -0.500000, 4.500000]
```

Beim zweiten Beispiel ändert sich am linken Quantil sogar das Vorzeichen. Die
Persistenz enthält dennoch keinen `effective_skew`, `effective_kurtosis` oder
Clamp-Verdict je Consumer.

### Erforderliche Lösung

1. Eine fachlich genehmigte `TailMomentDomainVersion` als einzige Quelle
   definieren. Entscheiden, ob Werte außerhalb abgelehnt, winsorisiert oder
   transformiert werden; stille consumerlokale Clamps entfernen.
2. Validierung beim CMA-Write und nochmals beim Approval/Runtime-Load mit
   identischem Code ausführen.
3. Optimizer, Haupt-MC, Stress, Risk-KPI und Reporting verwenden denselben
   normalisierten `EffectiveTailMomentSet` und dieselbe Transformversion.
4. Raw-, effective-, clamp-/reject-reason und Versionshash immutable
   persistieren und veröffentlichen.

## `CMA-TAIL-ACTIVATION-GOVERNANCE-001`

### Repository-Beleg

- `build_scenario_paths()` und der Importance-Sampling-Pfad wenden Cornish-
  Fisher stets an; bei Nullwerten ist die Transformation nur numerisch
  identisch (`scenario_engine.py:193-207, 295-303`).
- Der Haupt-MC aktiviert sie nur, wenn `tailRisk` oder `cornishFisher` wahr ist;
  ohne Preferences ist der Default `False`
  (`portfolio_engine_mc_simulation.py:220-229, 1175-1202, 1383-1393`).
- `optimization_basis.tail_model` wird für jeden stochastischen Lauf als
  Cornish-Fisher ausgewiesen; `reporting.tail_model` kann parallel lognormal
  sein (`portfolio_engine.py:2648-2785`).
- Der Electron-Client zeigt beim Reporting zwar den resultierenden
  `tail_model`, bezeichnet ihn aber nur als von der Allokationsentscheidung
  getrennte Umsetzungsprojektion (`5eyes_v2.html:7349-7364`).
- Im Electron-Frontend existiert kein `tailRisk`-/`cornishFisher`-Steuerelement
  und keine Eingabe/Anzeige der zehn Tail-CMA-Felder. Der Admin-Payload
  `collectAdminCapitalMarketAssumptionsPayload()` lässt sie aus
  (`5eyes_v2.html:11233-11284`). Der Router bewahrt unsichtbare Altwerte beim
  Versionsupdate zwar technisch, macht sie damit aber nicht reviewbar.

### Wirkung

Eine API-seitig gepflegte CMA mit Tailmomenten kann die Kandidatenauswahl und
Optimizer-Zielwahrscheinlichkeit auf Cornish-Fisher-Basis beeinflussen, während
die anschließend sichtbare allgemeine Monte-Carlo-Projektion standardmäßig
lognormal bleibt. Die Basisnamen legen die technische Trennung offen; es fehlt
aber ein Produkt-/Freigabevertrag, der erklärt, welche Wahrscheinlichkeit für
welche Kunden- oder Governance-Aussage maßgeblich ist und wie beide
reconciled werden.

### Erforderliche Lösung

1. Tail-Modell als CMA-/Run-Level-Policy, nicht als versteckten
   consumerlokalen Schalter definieren.
2. Wenn verschiedene Modelle bewusst benötigt werden, getrennte Zwecke,
   Kalibrierungen, Thresholds und eine verpflichtende Reconciliation-Evidence
   veröffentlichen; keine gleich benannten Erfolgswahrscheinlichkeiten.
3. Admin-UI muss Raw-/Effective-Tailmomente, Status, Quelle, Domainversion und
   Aktivierung vollständig lesen, bearbeiten bzw. ausdrücklich read-only
   reviewen können.
4. Kunden-UI/PDF zeigen Modellfamilie und wesentliche Differenzen verständlich;
   Auditansicht zeigt die exakten Parameter und Hashes.

## Kanonische Zielarchitektur für Claude

```text
RiskModelEvidence
  evidence_id / jurisdiction / as_of_date / approved_at / approved_by
  bucket_definition_version / currency_and_hedge_basis

  CorrelationModelEvidence
    observation_window / frequency / estimator / shrinkage_policy
    missing_data_policy / raw_matrix / effective_matrix / eigenvalues
    source_hash / model_version / matrix_hash

  TailMomentEvidence[]
    bucket / state
    raw_skew / raw_excess_kurtosis
    effective_skew / effective_excess_kurtosis
    estimator / observation_window / frequency / confidence
    domain_version / normalization_or_reject_verdict

  DistributionPolicy
    family / transform_version / activation_scope
    optimizer_enabled / reporting_enabled / stress_enabled
    reconciliation_policy / policy_hash

EffectiveStochasticModel
  cma_id / risk_model_evidence_id
  effective_correlation_hash / effective_tail_hash / distribution_policy_hash
  run_seed / scenario_artifact_hash / consumer / purpose
```

Solver, Haupt-MC, Sensitivity, Stress, Asset Allocation, Goal Probability,
Recommendation, UI, PDF, Signatur und Handoff müssen denselben effektiven
Risikomodell-Hash konsumieren oder eine explizit genehmigte, sichtbare
Abweichung samt Reconciliation referenzieren.

## Verbindliche Regressionstests

- Nicht-CH-CMA ohne explizite oder scope-genehmigte Korrelations-Evidence
  scheitert vor Approval und Run.
- CH-, DE- und US-Fallback dürfen nicht allein wegen leerem Payload denselben
  anonymen Matrixwert erben.
- Read/Save eines CMA-Editors wandelt einen NULL-Fallback nicht still in eine
  explizit genehmigte Matrix um.
- Jede effektive Matrix besitzt Source-, As-of-, Model- und Hash-Evidence.
- `NULL`, explizit `0`, `unavailable` und `not_applicable` bleiben in Schema,
  Persistenz, UI und Runtime unterscheidbar.
- Produktionslauf mit unreviewten Tailmomenten scheitert fail-closed.
- Grenz- und Out-of-Range-Werte werden an der API nach genau einer
  versionierten Domäne akzeptiert oder abgelehnt.
- Für jeden akzeptierten Tailwert erzeugen Optimizer, Haupt-MC, Stress und
  Risk-KPI dieselbe normalisierte Innovation bei identischem `z`.
- Raw- und Effective-Werte sowie jeder Clamp-/Reject-Grund sind im Run-
  Evidence nachweisbar.
- Tail-Aktivierung ist in allen Consumern identisch oder die Abweichung wird
  als getrenntes Modell mit eigener Ergebnisbezeichnung und Reconciliation
  publiziert.
- Admin-UI roundtrippt alle Tailfelder und ihre Evidence verlustfrei.
- UI/PDF zeigen die tatsächliche Matrix-/Tail-/Distributionsbasis, nicht nur
  „Standard“ oder einen generischen Methodennamen.
- Änderungen an Matrix, Tailmomenten, Domain- oder Transformversion ändern den
  Context-/Evidence-Hash und blockieren stale Finalize/PDF/Signatur.

## Verifikation dieser Runde

### Produktive Probes

- CH/DE/US mit leerem Payload durch denselben produktiven
  `_build_cholesky_from_cma()`-Pfad materialisiert: Faktoren und rekonstruierte
  Matrizen bitgleich.
- Portfolio-Volatilität der Defaultmatrix gegen zwei reine
  Sensitivitätsmatrizen analytisch über `sqrt(w'Σw)` verglichen.
- 100.000 fixed-seed Pfade über zehn Jahre mit Gaussian- und plausiblen
  Equity-Tailmomenten durch `build_scenario_paths()` erzeugt.
- Schema mit vier außerhalb der Optimizerdomäne liegenden, aber akzeptierten
  Tailwerten geprüft.
- Identische `z`-Werte durch Optimizer-, Haupt-MC- und Legacy-Transform
  geführt; consumerabhängige Outputs reproduziert.
- Temporärer Red-Contract-Test ausgeführt und danach entfernt:

```text
3 failed

1) Nicht-CH ohne explizite Matrix: erwarteter CMAValidationError fehlt
2) Tailwerte außerhalb gemeinsamer Domäne: erwarteter ValidationError fehlt
3) Optimizer-/Reporting-Parität: Arrays sind verschieden
```

### Bestandsgate

```text
263 passed, 1 Pytest-Cache-Warnung
```

Ausgeführt wurden:

- `test_cholesky_and_horizon.py`;
- `test_cma_strict_runtime_contract.py`;
- `test_cma_correlation_matrix_validation.py`;
- `test_optimizer_scenario_engine.py`;
- `test_optimizer_distributions.py`;
- `test_cornish_fisher_input_clamping.py`;
- `test_allocation_preferences_fail_closed_contracts.py`;
- `test_engine_reference_mandates.py`;
- `test_methodology_models_audit.py`.

Die einzige Warnung betrifft den vorbestehenden lokalen Pytest-Cache-ACL-
Zustand. Sie ist kein Produktfehler. Der temporäre Red-Test und alle Probe-
Artefakte wurden entfernt.

## Release-Entscheid

Die stochastische Risikobasis bleibt für reale Beratung, Zielwahrscheinlichkeit,
Sensitivity, Stress, PDF, Signatur und Handoff im Release-Hold. Freigabe erst,
wenn:

1. Korrelation und Tailmomente vollständig provenanciert, jurisdiktions- und
   bucketgerecht sowie approvalpflichtig sind;
2. Missingness nicht länger als positive Gaussian-Annahme interpretiert wird;
3. eine einzige versionierte Tail-Parameterdomäne und Transformpipeline alle
   Consumer speist;
4. Aktivierungs- und Zweckunterschiede beseitigt oder explizit reconciled und
   verständlich publiziert sind;
5. die obigen Red-Verträge, Cross-Consumer-Golden-Tests, Replay, UI-/PDF-
   Roundtrip und Zielumgebungsabnahme grün sind.

## Reihenfolge für Claude

1. Zuerst die drei roten Contract-Tests und Missingness-/UI-Roundtriptests
   permanent anlegen.
2. Dann `CorrelationModelEvidence`, diskriminierten Tailstatus und eine
   gemeinsame `TailMomentDomainVersion` implementieren.
3. Alle Consumer auf einen einzigen `EffectiveStochasticModel`-Compiler
   umstellen; lokale Defaults und Clamps entfernen.
4. Approval/Activation fail-closed an vollständige Evidence und Hashes binden.
5. Admin-, Kunden- und Auditdarstellung samt PDF aktualisieren.
6. Legacy-CMAs migrieren oder quarantänisieren und die vollständige
   Cross-Channel-/Zielumgebungsabnahme durchführen.

Bis dahin nicht durch zusätzliche UI-Hinweise, weitere Defaultwerte oder
consumerlokale Clamps „absichern“: Diese Maßnahmen würden die widersprüchliche
Risikobasis nur verdecken.
