# Equity-Valuation-, KGV-Kalibrierungs-, Horizont- und Publikationsintegritätsaudit

**Kontrollrunde 47 · Stand 04.10.2026 · Status: Release-Hold**

## Kurzfazit

Das KGV-/CAPE-Mean-Reversion-Modell besitzt keinen freigabefähigen
Ende-zu-Ende-Vertrag. Drei voneinander unabhängige P1 sind neu bestätigt:

1. **Kalibrierung und Referenzbeispiel widersprechen sich.** Die aktive
   Sprint-Spezifikation erwartet für `KGV 25 / fair 17 / alpha 0,15 / 10J`
   ungefähr `-100 bps p.a.`. Die produktive Formel und ihr Golden-Test liefern
   `-494,117647 bps p.a.`. Damit ist nicht geklärt, ob Code, Einheit,
   Kalibrierung oder Spezifikation die fachliche Wahrheit darstellt.
2. **Der wirksame Horizont ist immer 10 Jahre.** Das Modell ist ausdrücklich
   horizontabhängig, aber `scenario_inputs_from_cma()`,
   `_weighted_bucket_metrics()` und `_compute_equity_kgv_adjustment()` nehmen
   keinen Horizont entgegen. Solver, Haupt-Monte-Carlo, Advisory-MC,
   erwartete Kennzahlen und Sensitivity materialisieren deshalb immer denselben
   10-Jahres-Return, obwohl ihre echten Horizonte bereits vorliegen.
3. **Datenabgeleitete CMAs werden falsch offengelegt.** Die Nicht-CH-Pipeline
   bettet KGV-Mean-Reversion bereits in `equity_home_return_bps` ein, setzt aber
   die strukturierten KGV-Felder nicht. Der Methodology-Audit prüft nur diese
   drei Felder und publiziert das wirksame Modell folglich als „Inaktiv“; bei
   sonst fehlenden erweiterten Feldern behauptet er sogar, mit fixen
   Renditeerwartungen zu arbeiten. React-Compliance und PDF zeigen diesen
   falschen Status an.

Der produktive Zahlenbeleg für das dokumentierte Beispiel lautet:

```text
horizon  1: -684.705882 bps p.a.
horizon  5: -600.000000 bps p.a.
horizon 10: -494.117647 bps p.a.
horizon 20: -282.352941 bps p.a.
horizon 30: -211.764706 bps p.a.
horizon 50: -211.764706 bps p.a.

fixed-10 minus correct-5:   +105.882353 bps
fixed-10 minus correct-30:  -282.352941 bps
spec example versus code:  -394.117647 bps
```

Diese Abweichungen verändern Equity-Erwartungswert, Allokationsentscheidung,
Monte-Carlo-Verteilung, Zielwahrscheinlichkeit, Sensitivity, erwartete
Kennzahlen und veröffentlichte Begründung. KGV-aktivierte reale Beratung,
Recommendation, PDF, Signatur und Handoff bleiben gesperrt. Der Fix darf nicht
einfach `horizon_years` an eine Hilfsfunktion weiterreichen: Zuerst muss das
Investment Committee den mathematischen, kalibratorischen und zeitlichen
Vertrag genehmigen. Danach müssen alle Konsumenten einen unveränderlichen,
gehashten `EquityValuationEvidence`-Snapshot verwenden.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
23b5bfc
docs(audit): document sensitivity baseline pairing gap
```

Geprüft wurden insbesondere:

- Sprint-7-Spezifikation und produktive KGV-Formel;
- Unit- und Integrations-Golden-Tests;
- CMA-Schema und Modellfelder;
- Solver- und Scenario-Input-Materialisierung;
- Haupt-Monte-Carlo, Advisory-Monte-Carlo und erwartete Kennzahlen;
- Goal-Sensitivity mit unterschiedlichen Horizonten;
- Nicht-CH-Jurisdiktions-Pipeline und deren `source_detail`;
- Methodology-Audit, Advisory-Report, React-Compliance und PDF-Komponente;
- bestehende Audits zur Stochastik, CMA, Zielhorizonten und Publikation.

Produktionscode, Schema, Migrationen, Tests und UI wurden nicht verändert.
Persistiert werden ausschließlich die fünf Dokumentationspfade des
Auditmanifests.

## Abgrenzung zu früheren Runden

Frühere Audits bestätigten unter anderem ungebundene CMA-Zeitgültigkeit,
Inflationsdomänen, Goal-Horizonte, Monte-Carlo-Evidence und Sensitivity-
Vergleichbarkeit. Sie prüften jedoch weder den Widerspruch zwischen dem
KGV-Referenzbeispiel und seiner produktiven Zahl noch die feste
10-Jahres-Materialisierung oder den falschen Methodology-Status einer
datenabgeleiteten CMA. Die drei IDs dieser Runde sind deshalb neu und
duplizieren keine bestehende Finding-ID.

Der anfangs geprüfte Verdacht einer unmittelbaren KGV-Doppelanwendung in der
Nicht-CH-Pipeline hat sich **nicht** bestätigt: Die Pipeline speichert den
bereits adjustierten Home-Equity-Return, setzt aber nicht zusätzlich die drei
strukturierten KGV-Felder. Genau diese Vermeidung der Doppelanwendung erzeugt
allerdings den eigenständigen Provenienz-/Publikationsfehler.

## Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `KGV-CALIBRATION-CONTRACT-001` | P1 | neu bestätigt | Das aktive Referenzbeispiel erwartet ungefähr −100 bps p.a.; produktiver Code und Test erzwingen −494,12 bps. Alpha-Erklärung, Einheit und Kalibrierung besitzen keine widerspruchsfreie fachliche Wahrheit. |
| `KGV-HORIZON-BINDING-001` | P1 | neu bestätigt | Das horizontabhängige Modell wird in Solver, Haupt-MC, Advisory-MC, Kennzahlen und Sensitivity stets mit 10 Jahren materialisiert. Echte Run-/Zielhorizonte erreichen die Return-Annahme nicht. |
| `KGV-PROVENANCE-PUBLICATION-001` | P1 | neu bestätigt | Datenabgeleitete Nicht-CH-CMAs enthalten KGV im materialisierten Equity-Return, werden mangels strukturierter KGV-Felder in React/PDF aber als KGV-inaktiv beziehungsweise als fixe CMA publiziert. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
manuell gepflegte CMA
  base equity return + drei KGV-Felder
                         |
                         v
                fixed horizon = 10
                         |
       +-----------------+------------------+
       |                 |                  |
     Solver          Haupt-MC          Reporting metrics
       |                 |                  |
       +------ gleiche feste 10J-Annahme ---+

datenabgeleitete Nicht-CH-CMA
  risk-free + KGV(10J) -> equity_home_return_bps
  drei strukturierte KGV-Felder bleiben NULL
                         |
            +------------+-------------+
            |                          |
       Engine nutzt                 Methodology-Audit
       eingebetteten Effekt          meldet „Inaktiv“
                                       |
                                  React + PDF
```

Damit bestehen zwei unterschiedliche Repräsentationen desselben Modells:
einmal als rohe Parameter plus Laufzeitanpassung, einmal als bereits
materialisierter Return plus JSON-Provenienz. Weder Typ noch Evidence machen
diesen Unterschied maschinenlesbar.

## `KGV-CALIBRATION-CONTRACT-001` – Spezifikation und produktive Zahl widersprechen sich

### Beleg

- `docs/planning/2026-05-17-sprint-7-kgv-mean-reversion.md:27-37`
  definiert die Formel und erwartet für `25 / 17 / 0,15 / 10J` ungefähr
  `-100 bps p.a.`.
- `services/equity_valuation/mean_reversion.py:58-83` multipliziert die
  relative Bewertungsdifferenz mit `alpha`, `10000` und
  `max(0.3, 1 - 0.03*t)`.
- `tests/equity_valuation/test_mean_reversion.py:102-114` schreibt für genau
  dasselbe Beispiel `-494,117647 bps` als korrekten Golden-Wert fest.
- `mean_reversion.py:43` erklärt außerdem, `alpha=0,15` reduziere ein Drittel
  der Überbewertung pro Jahr. `0,15` und ein Drittel sind keine identischen
  Reversionsraten.

Die Formel ist intern deterministisch; das Problem ist nicht numerische
Instabilität, sondern ein ungeklärter fachlicher Vertrag. Ein grüner Test
beweist hier lediglich, dass der Code seinen eigenen Wert reproduziert.

### Wirkung

Beim dokumentierten Beispiel liegt der Code um rund `394 bps p.a.` negativer
als die Spezifikation. Bei einem Basisertrag von beispielsweise 650 bps würde
allein der produktive 10-Jahres-KGV-Effekt den Equity-Return auf rund 156 bps
senken. Solche Größenordnungen können:

- die optimale Aktienquote und aktive Constraints verändern;
- Zielwahrscheinlichkeiten und Wealth-Quantile materiell verschieben;
- Risk/Return- und Sharpe-Kennzahlen verändern;
- Sensitivity-Erklärungen dominieren;
- einen fachlich nicht genehmigten Modellentscheid als Investment-Committee-
  Annahme erscheinen lassen.

### Erforderliche Lösung

1. Investment Committee/Model Owner genehmigt **eine** kanonische Formel,
   Einheit und Kalibrierung. Audit darf nicht entscheiden, ob `-100` oder
   `-494,12` richtig ist.
2. Versionierte Modell-ID einführen, etwa
   `equity_valuation_formula_version` und `calibration_id`.
3. Golden-Tabelle für Fair Value, Über-/Unterbewertung, mehrere Alpha-Werte
   und 1/5/10/20/30/50 Jahre festschreiben.
4. Plausibilitätsgrenzen und ein formales Model-Change-Approval erzwingen.
5. Bestehende Allocations, Runs, Recommendations und Reports mit unbekannter
   Modellversion als legacy/unverifizierbar markieren; nicht still neu deuten.

## `KGV-HORIZON-BINDING-001` – Run- und Zielhorizonte erreichen das Modell nicht

### Beleg

- Die Spezifikation nennt `horizon_years` als Modellinput und verlangt bei
  mehr als 20 Jahren deutlich weniger Wirkung als bei 5 Jahren.
- Der Unit-Test `test_adjustment_dampening_for_long_horizon` bestätigt genau
  diese Fachsemantik.
- `scenario_engine.py:737-762` definiert trotzdem
  `_KGV_DEFAULT_HORIZON_YEARS = 10`; der Kommentar verweist den Override auf
  ein nicht realisiertes TODO.
- `scenario_inputs_from_cma(cma, sub_allocations)` besitzt keinen
  Horizontparameter.
- `solver.py:333-377` kennt den echten `horizon_years` und den gemeinsamen
  `scenario_horizon_years`, ruft an `401-404` die CMA-Materialisierung jedoch
  ohne einen der beiden Werte auf.
- `monte_carlo_paths.py:294-315` kennt den Advisory-Horizont, materialisiert
  die CMA aber ebenfalls ohne ihn.
- `portfolio_engine_mc_simulation.py:513/1167` berechnet den tatsächlichen
  Horizont aus der Cashflowserie; `522/1179` ruft
  `_weighted_bucket_metrics()` ohne ihn auf.
- `_weighted_bucket_metrics()`, `_expected_metrics()` und alle
  Payload-/Backtest-Aufrufer besitzen ebenfalls keinen Horizontvertrag.

Die Funktionssignaturen wurden produktiv introspektiert:

```text
scenario_inputs_from_cma(cma, sub_allocations=None)
_compute_equity_kgv_adjustment(cma)
_compute_paths_core(..., horizon_years, ..., cma, ...)
```

Der letzte Pfad kennt den Horizont, aber der mittlere Modellaufruf kann ihn
nicht empfangen.

### Konkrete Auswirkung

Für `KGV 25 / fair 17 / alpha 0,15` gilt:

| Run-Horizont | Modellwert | tatsächlich verwendet | Fehler `fixed10 - korrekt` |
|---:|---:|---:|---:|
| 5 Jahre | −600,00 bps | −494,12 bps | +105,88 bps |
| 10 Jahre | −494,12 bps | −494,12 bps | 0,00 bps |
| 30 Jahre | −211,76 bps | −494,12 bps | −282,35 bps |

Ein 5-Jahres-Mandat erhält damit ein zu schwaches negatives Signal; ein
30-Jahres-Mandat ein zu starkes. Bei Unterbewertung kehrt sich das Vorzeichen
des Fehlers entsprechend um.

### Sensitivity-Nuance

Ein bloßes Durchreichen von `scenario_horizon_years` wäre ebenfalls falsch:
Dieser Wert kann nur die gemeinsame maximale Cube-Länge einer gepaarten
Sensitivity repräsentieren. Fachlich relevant ist je nach genehmigtem Vertrag
der konkrete Run-/Goal-Horizont oder ein expliziter CMA-Prognosehorizont.

Wenn eine Horizon-Sensitivity den Modellhorizont verändern soll, dürfen beide
Seiten dieselben standardisierten Zufallsschocks verwenden; ihre transformierten
Returns müssen wegen unterschiedlichem `mu` aber nicht bytegleich sein. Der
Common-Random-Numbers-Vertrag ist dann auf Innovations- statt Return-Cube-
Ebene zu definieren.

### Erforderliche Lösung

1. Fachlich entscheiden, ob der KGV-Horizont der konkrete Run-Horizont, ein
   zielbezogener Horizont oder ein expliziter strategischer CMA-Horizont ist.
2. Den Wert mit Quelle und Semantik in einen `EquityValuationContext` aufnehmen;
   implizite Defaults sind in freigabefähigen Runs verboten.
3. Den Context durch Solver, Haupt-MC, Advisory-MC, Kennzahlen, Sensitivity,
   Backtest und Payload-Builder reichen.
4. Bei mehreren Zielen definieren, ob ein gemeinsamer Portfoliohorizont oder
   zielbezogene Return-Annahmen gelten; diese Entscheidung versionieren.
5. Model-Input-, Scenario- und Run-Hashes um Modellversion, Kalibrierung,
   effektiven Horizont und berechneten Adjustment-Wert erweitern.
6. Replay muss denselben Adjusted Return erzeugen oder fail-closed stoppen.

## `KGV-PROVENANCE-PUBLICATION-001` – Eingebettetes Modell wird als inaktiv publiziert

### Beleg

- `jurisdiction/data_pipeline.py:320-350` berechnet für einen vorhandenen
  PE-Proxy `equity_home_return_bps` als Nelson-Siegel-Short-Rate plus
  `KGVMeanReversionModel(...).expected_annual_return_adjustment_bps(10)`.
- `data_pipeline.py:344-349` hält Parameter und 10-Jahres-Horizont nur im
  freien `source_detail`-JSON fest.
- Beim Erstellen der CMA an `394-410` werden `equity_home_return_bps`, aber
  keine `equity_kgv_current_x10`, `equity_kgv_fair_x10` oder
  `equity_kgv_alpha_x100` gesetzt.
- `_build_kgv_status()` an `methodology_audit.py:82-100` nennt das Modell nur
  aktiv, wenn genau diese drei strukturierten Felder vorhanden sind; das
  `source_detail` wird nicht gelesen.
- `audit_engine_models()` behauptet bei `active_count == 0`, der Optimizer
  arbeite mit fixen Renditeerwartungen aus der CMA.
- `advisory_report.py:2989-3000` übernimmt diesen Status.
- React `Compliance.tsx:147-181` zeigt pro Modell „Aktiv“ oder „Inaktiv“.
- PDF `pdf/components/compliance_audit.py:137-145` druckt denselben Status und
  Basistext.

Eine direkte produktive Statusprobe mit eingebetteter KGV-Provenienz und
NULL-Strukturfeldern ergab:

```text
active=False
parameters={kgv_current_x10: None, kgv_fair_x10: None, alpha_x100: None}
source_detail_has_embedded_kgv=True
```

### Zusätzliche Modellbasisfrage

Die Nicht-CH-Pipeline bildet den Home-Equity-Return aus Risk-Free plus
Bewertungsadjustment. Eine separate, versionierte Equity-Risk-Premium-
Komponente ist in dieser Formel nicht sichtbar. Bei dem produktiven
Referenzwert kann der negative KGV-Effekt den Risk-Free-Wert vollständig
übersteigen. Ob dies fachlich beabsichtigt ist, muss der Model Owner explizit
entscheiden; das Audit erfindet keine fehlende Prämie.

### Erforderliche Lösung

1. Keine untypisierte Mischung aus rohen Parametern und bereits
   materialisierten Returns mehr zulassen.
2. Vorzugsweise Rohkomponenten strukturiert persistieren und den effektiven
   Return genau einmal im Run materialisieren:

```text
base_equity_return_bps
equity_risk_premium_bps?
kgv_current / kgv_fair / alpha
formula_version / calibration_id
effective_horizon_years / horizon_source
kgv_adjustment_bps
adjusted_equity_return_bps
source_id / market_as_of / computed_at / jurisdiction
```

3. Falls ein bereits adjustierter Return importiert wird, muss ein
   maschinenlesbares `return_includes_kgv=true` inklusive Komponenten die
   erneute Anwendung verhindern und die Offenlegung speisen.
4. Methodology darf nicht die aktuelle globale CMA erneut interpretieren,
   sondern muss den exakt an Allocation/Run gebundenen Evidence-Snapshot
   anzeigen.
5. React, PDF, Recommendation, Signatur und Handoff müssen dieselbe
   Modellaktivität, Formelversion, Horizonquelle und effektive Zahl zeigen.

## Zielarchitektur für Claude

### Ein kanonischer Evidence-Snapshot

```text
EquityValuationEvidence
  schema_version
  formula_version
  calibration_id
  model_owner_approval_id
  cma_id / cma_version / cma_hash
  jurisdiction / source_id / market_as_of
  base_return_bps
  equity_risk_premium_bps?
  kgv_current / kgv_fair / alpha
  horizon_semantics
  effective_horizon_years
  kgv_adjustment_bps
  adjusted_return_bps
  source_detail_hash
  evidence_hash
```

Dieser Snapshot wird **vor** Szenarioerzeugung validiert, ist immutable und
wird an TargetAllocation, OptimizerRun, Monte-Carlo-Resultat, Recommendation,
Report, Signatur und Handoff gebunden. Keine Publikationsschicht rekonstruiert
Modellaktivität aus nullable CMA-Feldern.

### Umsetzungsschritte

1. **Owner-Entscheid:** Formel, Einheiten, Alpha-Semantik, Equity-Premium und
   Horizon-Semantik schriftlich genehmigen.
2. **Datenmodell:** rohe Komponenten von materialisierten Outputs trennen;
   Formel-/Kalibrierungsversion und `as_of` verpflichtend machen.
3. **Compiler:** eine pure, streng validierende Funktion erzeugt
   `EquityValuationEvidence` und genau einen effektiven Equity-Return.
4. **Engine-Wiring:** Solver, beide MC-Pfade, Kennzahlen, Sensitivity und
   Backtest konsumieren denselben Snapshot.
5. **Persistenz:** Evidence-Hash an Run/Allocation binden; Reload und Replay
   verifizieren Hash und Komponenten.
6. **Publikation:** UI/PDF/Recommendation/Signatur/Handoff lesen ausschließlich
   den gebundenen Snapshot.
7. **Migration:** alte Runs ohne Formelversion/Horizonquelle nicht nachträglich
   als verifiziert darstellen.

## Verbindliche Regressionstests

- Golden-Vektoren für die owner-genehmigte Referenzzahl und Einheiten.
- 1/5/10/20/30/50-Jahres-Tests auf Model-, Solver-, Haupt-MC- und Advisory-
  MC-Ebene.
- Test, dass Run-Horizon und effektiver KGV-Horizon entweder identisch oder
  durch einen expliziten CMA-Horizon-Vertrag nachvollziehbar verschieden sind.
- Sensitivity-Test mit gemeinsamen Innovationen und horizonspezifischem `mu`.
- Datenpipeline-Test, der rohe Komponenten, Materialisierungsflag und
  Adjustment exakt bindet.
- Test gegen Doppelanwendung und gegen stille Omission.
- Methodology-Test: datenabgeleitete CMA erscheint als KGV-aktiv mit
  Formelversion, Horizont und Adjustment.
- API-/React-/PDF-Golden: identische Modellaktivität und Zahlen.
- Replay-Test mit unverändertem Evidence-Hash; Tampering stoppt fail-closed.
- Migrationstest für unverifizierbare Legacy-CMAs und -Runs.

## Verifikation dieser Runde

### Numerische und strukturelle Probes

- Produktive Modellfunktion für 1/5/10/20/30/50 Jahre ausgeführt.
- Abweichung zwischen Spezifikationsbeispiel und Code berechnet.
- Signaturen von `scenario_inputs_from_cma`,
  `_compute_equity_kgv_adjustment` und `_compute_paths_core` introspektiert.
- Methodology-Status mit eingebetteter KGV-Provenienz und NULL-Strukturfeldern
  ausgeführt; Ergebnis war erwartungsgemäß falsch-inaktiv.
- Nicht-CH-Pipeline auf mögliche Doppelanwendung geprüft; keine unmittelbare
  Doppelanwendung bestätigt.

### Unveränderte Bestandstests

```text
python -m pytest -q --basetemp ..\tmp\round47_kgv \
  tests/equity_valuation/test_mean_reversion.py \
  tests/equity_valuation/test_engine_integration.py \
  tests/test_methodology_models_audit.py \
  tests/test_monte_carlo_paths.py \
  tests/test_optimizer_scenario_engine.py \
  tests/test_cma_data_pipeline.py

98 passed in 13.16s
```

Ein erster identischer Lauf mit `C:\tmp\ares_round47_kgv` erreichte 82 grüne
Tests und 16 Setup-Fehler, weil Windows das Basetemp-Verzeichnis nicht anlegen
durfte. Nach Wechsel in das explizit beschreibbare Workspace-Tempverzeichnis
lief derselbe Gate vollständig grün. Das war ein lokaler Harness-/ACL-Effekt,
kein Produktfehler.

Die grüne Suite widerlegt die Findings nicht: Sie prüft das intern
konsistente `-494`-Golden, Richtung, Validierung und Status anhand der drei
strukturierten Felder. Sie enthält keinen Test auf die spezifizierten
`-100 bps`, keinen Ende-zu-Ende-Horizonvertrag und keinen datenabgeleiteten
Methodology-Status.

## Release-Entscheid

**Release-Hold bleibt bestehen.** Zusätzlich zu allen früheren P0/P1 gilt:

- KGV-aktivierte reale Allocations und Zielwahrscheinlichkeiten sind nicht
  fachlich freigabefähig, solange Formel und Kalibrierung widersprüchlich sind.
- Horizontabhängige KGV-Aussagen dürfen nicht mit dem versteckten festen
  10-Jahreswert beraten oder publiziert werden.
- Datenabgeleitete CMAs dürfen nicht als „KGV inaktiv“ beziehungsweise als
  fixe Renditeannahmen dargestellt werden.
- Ein grüner Unit-Test der aktuellen Formel ist kein Model-Risk-Approval.

## Selbstkontrolle

- [x] Vorherige Audits auf Duplikate durchsucht.
- [x] Doppelanwendungsverdacht geprüft und nicht fälschlich als Finding geführt.
- [x] Spezifikations-, Code-, Test- und Publikationspfad Ende zu Ende verfolgt.
- [x] Produktive Zahlen statt nur statischer Vermutung reproduziert.
- [x] Prioritäten nach direkter Allocation-/MC-/Publikationswirkung kalibriert.
- [x] Keine fachliche Sollformel erfunden; Owner-Entscheid explizit verlangt.
- [x] Produktcode, Tests, Schema, Migrationen und UI unverändert gelassen.
- [x] Nur die fünf Dokumentationspfade des Manifests vorgesehen.
