# Jurisdiktions-CMA-, Equity-Messbasis-, Snapshot- und Freigabeintegritätsaudit

**Kontrollrunde 48 · Stand 04.10.2026 · Status: Release-Hold**

## Kurzfazit

Die datenabgeleitete Nicht-CH-CMA-Pipeline besitzt vier neue, eigenständige
Integritätslücken:

1. Ein ETF-`trailingPE` wird gegen einen generischen Shiller-CAPE-Fair-Value
   verglichen. Die beiden Kennzahlen besitzen unterschiedliche Earnings-
   Fenster und sind nicht ohne genehmigte Transformation austauschbar.
2. Der Equity-Return wird als `short_rate + KGV adjustment` gebildet. Anders
   als der manuelle CMA-Pfad addiert die Pipeline das Bewertungsadjustment
   nicht auf einen vollständigen Equity-Basisertrag; eine explizite
   Equity-Risk-Premium-/Cash-Yield-/Growth-Komponente fehlt.
3. Die Zinskurve kann aus je Serie unterschiedlichen letzten
   Beobachtungstagen innerhalb eines 30-Tage-Fensters bestehen. Diese
   Observation Dates werden verworfen; beim PE-Proxy wird gar kein
   Marktstichtag persistiert. `fetched_at` und `valid_from` beweisen deshalb
   keinen kohärenten Markt-Snapshot.
4. Der Approval-Endpunkt führt keinerlei fachlichen Preflight aus. Er setzt
   jede vorhandene CMA-Zeile auf `committee_approved` und `is_current=1`,
   unabhängig von Ausgangsstatus, Vollständigkeit, Quellenalter,
   Modellversion, Hash oder Kundenverwendbarkeit. Der bestehende grüne Test
   genehmigt sogar eine DE-CMA, deren sämtliche Kapitalmarktwerte NULL sind.

Neu bestätigt sind damit drei P1 und ein P2:

- `CMA-EQUITY-MEASUREMENT-BASIS-001` – P1;
- `CMA-EQUITY-RETURN-DECOMPOSITION-001` – P1;
- `CMA-APPROVAL-PREFLIGHT-001` – P1;
- `CMA-MARKET-SNAPSHOT-001` – P2.

Der produktive Zahlenprobe mit den bestehenden DE-Testkurvenwerten und
`trailingPE=22` ergab:

```text
Nelson-Siegel short rate       +172.675703 bps
KGV adjustment (22 / 16, 10J) -393.750000 bps
persistierter Equity-Return    -221.074297 bps
Equity-Risk-Premium-Komponente nicht vorhanden
```

Damit kann ein als „aus echten Marktdaten berechnet“ beworbener Equity-Return
negativ werden, ohne dass eine eigenständige erwartete Equity-Prämie,
Earnings-/Cash-Yield- oder Growth-Komponente existiert. Das Audit behauptet
nicht, dass ein negativer Equity-Return grundsätzlich unmöglich ist. Der
Fehler ist, dass die ökonomische Zerlegung und Messbasis weder konsistent noch
genehmigt und trotzdem direkt freigabefähig sind.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
5c88d07
docs(audit): document KGV valuation contract gaps
```

Geprüft wurden:

- FRED-/ECB-Zinskurvenabruf und `MacroPoint`-Provenienz;
- PE-Proxy-Abruf über `yfinance.Ticker.info["trailingPE"]`;
- Nicht-CH-CMA-Kandidatenberechnung;
- Home-Equity-Return-Zerlegung;
- Status-, `source_detail`-, `computed_at`- und `valid_from`-Semantik;
- Committee-Approval, Current-Promotion, Rollen- und Tenant-Scope;
- Resolver-/Provisional-Gate und DE-Onboarding;
- vorhandene Datenpipeline-, Approval-, Engine-, Onboarding-, PDF- und
  Strict-CMA-Tests;
- Primär-/Originalquellen zur CAPE-Definition und erwarteten Equity-Prämie.

Produktionscode, Schema, Migrationen, Tests und UI wurden nicht verändert.
Persistiert werden ausschließlich die fünf Dokumentationspfade des
Auditmanifests.

## Verhältnis zu Kontrollrunde 47

Runde 47 bestätigte den KGV-Kalibrierungswiderspruch, den versteckten festen
10-Jahres-Horizont und den falschen Methodology-Status. Diese Runde baut darauf
auf, vergibt aber keine doppelten IDs:

- Runde 47: Wie wird ein vorhandenes KGV-Modell gerechnet, gebunden und
  publiziert?
- Runde 48: Sind die Eingangskennzahl, die Equity-Return-Zerlegung, der
  Markt-Snapshot und die Freigabe eines datenabgeleiteten Kandidaten überhaupt
  belastbar?

Die Findings müssen gemeinsam geschlossen werden. Ein korrekter Horizon-
Parameter repariert weder eine inkompatible PE/CAPE-Messbasis noch eine
unvollständige Return-Zerlegung oder einen Approval-Bypass.

## Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `CMA-EQUITY-MEASUREMENT-BASIS-001` | P1 | neu bestätigt | ETF-Trailing-P/E wird untransformiert mit einem generischen, jurisdiktionsunabhängigen Shiller-CAPE-Fair-Value verglichen. Earnings-Fenster, Index-/ETF-Basis und Länderbasis sind nicht kongruent. |
| `CMA-EQUITY-RETURN-DECOMPOSITION-001` | P1 | neu bestätigt | Nicht-CH-Equity-Return ist nur Short Rate plus Bewertungsadjustment. Eine explizite Equity-Risk-Premium-/Cash-Yield-/Growth-Komponente fehlt; der Pfad besitzt damit eine andere Semantik als manuelle CMA-Basisreturn-plus-Adjustment. |
| `CMA-APPROVAL-PREFLIGHT-001` | P1 | neu bestätigt | Approval setzt jede gefundene CMA ohne Status-, Vollständigkeits-, Quellen-, Modell-, Freshness- oder Hash-Prüfung auf approved/current. Eine vollständig leere DE-CMA wird durch den grünen Bestandstest erfolgreich aktiviert. |
| `CMA-MARKET-SNAPSHOT-001` | P2 | neu bestätigt | Pro Serie unterschiedliche letzte Observation Dates und ein undatierter PE-Info-Wert werden zu einem Snapshot kombiniert; persistiert werden nur Werte und Fetch-Zeit, nicht die effektiven Marktstichtage. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
ECB/FRED series A -> latest point date A --+
ECB/FRED series B -> latest point date B --+--> dates discarded
ECB/FRED series C -> latest point date C --+       |
                                                     v
                                              Nelson-Siegel curve
                                                     |
ETF Ticker.info trailingPE -> no market-as-of --------+
                                                     |
                      compare trailing PE to generic Shiller-CAPE 16
                                                     |
          equity return = short rate + valuation adjustment
                                                     |
             source_detail JSON + data_derived candidate
                                                     |
                  POST /.../{id}/approve
                  no model/completeness preflight
                                                     |
                    committee_approved + current
                                                     |
                 Solver / MC / UI / PDF / Advice
```

## `CMA-EQUITY-MEASUREMENT-BASIS-001` – Trailing-P/E und Shiller-CAPE werden vermischt

### Repository-Beleg

- `data_pipeline.py:121-130` definiert SPY/EWG als ETF-Proxies.
- `data_pipeline.py:231-267` liest `Ticker.info["trailingPE"]`, rundet den
  Wert auf einen ganzen Integer und bezeichnet ihn ausdrücklich als
  ETF-Trailing-KGV, nicht als reines Index-KGV.
- `data_pipeline.py:132-142` definiert dagegen den Fair Value `16.0` als
  generischen, jurisdiktionsunabhängigen Shiller-CAPE-Langfristwert.
- `data_pipeline.py:325-330` übergibt beide Werte ohne Normalisierung oder
  Measurement-Basis-Gate an dasselbe Mean-Reversion-Modell.
- `source_detail` räumt den Proxycharakter ein, aber die Approval-Logik wertet
  diese Warnung nicht aus.

### Externe Begriffsabgrenzung

Robert Shillers Yale-Datenseite beschreibt CAPE anhand realer Earnings und
deren Durchschnitt und stellt die lange Zeitreihe separat bereit. Das ist
eine andere Messbasis als ein einzelnes `trailingPE`-Feld. Siehe
[Robert Shiller – Online Data](https://www.econ.yale.edu/~shiller/data.htm).

Die offizielle yfinance-Dokumentation bestätigt, dass `Ticker.info` ein
allgemeiner Info-Abruf der Yahoo-Finance-Schnittstelle ist; sie liefert hier
keinen versionierten CAPE-Datensatz oder eine im Repository gebundene
Definition. Siehe
[yfinance API documentation](https://github.com/ranaroussi/yfinance/blob/main/doc/source/index.rst).

Die externe Recherche wird nur zur Begriffsabgrenzung verwendet. Der Befund
steht bereits durch den eigenen Codekommentar fest: `trailingPE` und
„Shiller-CAPE Mittel über 100J“ werden als verschiedene Größen bezeichnet und
danach trotzdem numerisch gleichartig behandelt.

### Wirkung

- Ein Unterschied im Earnings-Fenster wird als Über-/Unterbewertung gedeutet.
- ETF-, Index- und Länderbasis können voneinander abweichen.
- Das Runden von beispielsweise `24,7` auf `25` vernichtet zusätzliche
  Messpräzision, bevor ein mehrere hundert Basispunkte starker Effekt entsteht.
- Ein generischer US-Langfristwert wird auch für Deutschland verwendet, ohne
  genehmigte Cross-Market-Normalisierung.
- Committee Approval bestätigt aktuell nur die Zeile, nicht die
  Vergleichbarkeit ihrer Messgrößen.

### Erforderliche Lösung

1. Eine kanonische Measurement-ID einführen, etwa `cape_10y_real_v1` oder
   `trailing_pe_ttm_v1`; Current und Fair müssen dieselbe Basis besitzen.
2. Index-/ETF-, Earnings-, Inflations-, Währungs- und Jurisdiktionsbasis
   maschinenlesbar speichern.
3. Nur eine fachlich genehmigte Transformation zwischen Messbasen zulassen;
   Transformationsversion und Unsicherheit persistieren.
4. Rohwert mit voller Präzision halten; erst publizierte Anzeige runden.
5. Mismatch vor Kandidatenerzeugung oder spätestens Approval fail-closed
   blockieren.

## `CMA-EQUITY-RETURN-DECOMPOSITION-001` – Equity-Prämie/Basisertrag fehlt

### Repository-Beleg

- Die manuelle CMA-Integration addiert KGV-Mean-Reversion auf vorhandene
  `equity_*_return_bps`-Basisreturns.
- Die Nicht-CH-Pipeline ersetzt diese Semantik durch
  `equity_home_return_bps = short_rate + kgv_adjustment`.
- `source_detail` hält genau diese Zwei-Komponenten-Formel fest.
- Es existiert in diesem Pfad keine separate Equity-Risk-Premium-, Earnings-
  Yield-, Dividend-/Buyback-Yield- oder Growth-Komponente.
- Real-Estate und Alternatives bleiben bei fehlender Prämienquelle bewusst
  NULL; beim Equity-Pfad wird trotz ebenfalls fehlender expliziter Prämie ein
  vollständiger Return persistiert.

Die Projektarchitektur kennt das Prinzip `risk_free + risk_premium` bereits
für andere Risk Assets. Auch die Originalreferenz von Aswath Damodaran
beschreibt erwartete Risk-Asset-Returns als Risk-Free plus eine für das Risiko
verlangte Prämie. Siehe
[Damodaran – Discount rates and expected return](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/discountrates.htm).

Das bedeutet nicht, dass zwingend CAPM verwendet werden muss. Es zeigt, warum
`short_rate + reines Bewertungsadjustment` eine genehmigungsbedürftige
Modellzerlegung und kein neutraler Default ist.

### Produktive Gegenprobe

Mit den bestehenden DE-Testwerten:

```text
maturities = [1, 2, 5, 10, 30]
yields_bps = [200, 230, 260, 290, 310]
trailingPE = 22
fair CAPE = 16
alpha = 0.15
horizon = 10

short_rate_bps       = +172.675703
kgv_adjustment_bps   = -393.750000
equity_return_bps    = -221.074297
```

Der persistierte Integer wäre ungefähr `-221 bps p.a.`. Weder Test noch
Approval fragen, ob dies aus einem vollständigen, freigegebenen Equity-
Expected-Return-Modell stammt.

### Erforderliche Lösung

1. Model Owner definiert eine vollständige, versionierte Zerlegung:

```text
expected_equity_return
  = risk_free_component
  + approved_equity_risk_premium_or_cashflow_component
  + valuation_adjustment
  + optional jurisdiction/currency adjustments
```

2. Jede Komponente erhält Quelle, Datum, Einheit, Horizon und Unsicherheit.
3. Wenn eine Komponente fehlt, bleibt der Gesamtreturn NULL und nicht
   `data_derived`-freigabefähig.
4. Manuelle und datenabgeleitete CMAs müssen denselben semantischen Compiler
   verwenden.
5. Plausibilitäts- und Change-Budget-Gates dürfen negative Returns nicht
   pauschal verbieten, müssen aber extreme oder unvollständige Zerlegungen
   explizit reviewpflichtig machen.

## `CMA-MARKET-SNAPSHOT-001` – Kein kohärenter, replaybarer Marktstichtag

### Beleg

- `MacroPoint` besitzt `date`, `value`, `series_code` und `source`.
- `fetch_yield_curve_for_jurisdiction()` holt je Serie den letzten Punkt in
  einem 30-Tage-Fenster. Jeder Punkt kann daher ein anderes Datum besitzen.
- Die Rückgabe reduziert den Punkt auf `(maturity_years, yield_bps)` und
  verwirft `date`, `series_code` aus dem tatsächlichen Punkt und `source`.
- `source_detail["fetched_points_bps"]` speichert nur Maturity und Wert.
- Der PE-Abruf speichert Ticker und Wert, aber keinen Markt-/Fundamental-
  Stichtag, Datenalter oder Provider-Payload-Hash.
- `fetched_at_utc` beschreibt Abrufzeit, nicht die Observation Dates.
- Der Router setzt `valid_from` auf `date.today()`, auch wenn einzelne
  Kurvenpunkte älter sind.

### Wirkung und Priorität

Der Befund ist P2, weil die Pipeline ein enges 30-Tage-Fenster verwendet und
der aktuelle Code keine konkrete Fehlallokation allein aus dem Datumsverlust
beweist. Er ist dennoch vor realer Nutzung zu schließen:

- eine Kurve kann asynchron veröffentlichte Maturitäten mischen;
- der PE-Wert kann zeitlich nicht zur Kurve passen;
- spätere Reproduktion kann die ursprünglichen Inputs nicht erneut laden;
- Approval und PDF können „computed_at“ mit „market as of“ verwechseln;
- Source-Correction oder Provider-Revision bleibt unerkennbar.

### Erforderliche Lösung

1. Für jeden Kurvenpunkt Observation Date, Provider, Series Code, Abrufzeit,
   Raw Value und Payload-/Record-Hash persistieren.
2. PE/CAPE-Quelle benötigt explizites `market_as_of` und `fundamentals_as_of`.
3. Einen kanonischen Snapshot-Stichtag sowie maximale Cross-Series- und
   Cross-Asset-Abweichung definieren.
4. Zu alte oder zu weit auseinanderliegende Daten fail-closed blockieren.
5. `valid_from`, `computed_at`, `fetched_at` und `market_as_of` typisiert
   trennen.
6. Replay muss aus den gebundenen Rohinputs identische Modelloutputs erzeugen.

## `CMA-APPROVAL-PREFLIGHT-001` – Approval ist nur ein Statusschalter

### Beleg

- `routers/jurisdiction.py:312-356` lädt eine beliebige nicht gelöschte CMA-ID,
  setzt sofort `status="committee_approved"`, promotet bei Bedarf
  `is_current=1`, supersediert die bisherige Current-Zeile und committet.
- Es gibt keine Prüfung auf den Ausgangsstatus `data_derived`.
- Es gibt keine Pflichtwerte pro Jurisdiktion, keine Volatilitäts-,
  Korrelations- oder Sub-CMA-Vollständigkeit und keinen Strict-CMA-Compiler.
- `source_detail`, Observation Dates, Alter, Measurement Basis, Formelversion,
  Kalibrierung und Model-Owner-Approval werden nicht validiert.
- Der AuditLog enthält nur Action und Record-ID; ein Approval-Entscheid,
  geprüfter Hash, Reviewer-Kommentar oder Vier-Augen-Nachweis fehlt.
- `tests/test_cma_approval_endpoint.py:58-65` erzeugt die Test-CMA ohne einen
  einzigen Kapitalmarktwert.
- `test_approve_de_candidate_promotes_to_current_and_supersedes_previous`
  erwartet für genau diese leere Zeile HTTP 200, `committee_approved` und
  `is_current=1`.

Die nachgelagerten Provisional-Gates helfen hier nicht: Sie prüfen nur den
String `committee_approved`. Sobald der blinde Statusschalter erfolgreich war,
gilt die leere oder methodisch inkonsistente CMA als freigegeben.

### Erforderliche Lösung

1. Approval als atomare Domain Transition implementieren:

```text
data_derived
  -> preflight_passed(model_input_hash, validation_report)
  -> independently_reviewed(approver, decision, evidence_hash)
  -> committee_approved
  -> activated(valid_from, scope, predecessor)
```

2. Kandidat muss exakt den erwarteten Ausgangsstatus besitzen.
3. Jurisdiktionsspezifische Pflichtfelder, vollständige Return-/Risk-
   Zerlegung, Measurement- und Snapshot-Vertrag strikt validieren.
4. Approval-Request verlangt immutable Kandidatenhash, Entscheidgrund und
   gegebenenfalls zweiten Approver; Self-Approval-Regel explizit definieren.
5. Zwischen Review und Commit erneut Hash/Current-Anker prüfen.
6. AuditLog speichert vorherigen/neuen Hash, Validation-Report-ID,
   Reviewer/Approver, Zeit und Scope append-only.
7. Activation darf erst nach erfolgreichem Preflight erfolgen; ein Fehler darf
   den bisherigen Current-Anker nicht verändern.

## Kanonische Zielarchitektur für Claude

```text
MarketObservationSnapshot
  snapshot_id / schema_version / hash
  jurisdiction / currency / market_as_of
  curve_points[]:
    maturity / raw_value / unit / observation_date
    provider / series_code / fetched_at / raw_record_hash
  equity_measure:
    measure_id / raw_value / precision
    index_or_etf / earnings_window / inflation_basis
    fundamentals_as_of / provider / raw_record_hash

EquityReturnModelEvidence
  formula_version / calibration_id / owner_approval_id
  risk_free_bps
  equity_premium_or_cashflow_components_bps
  valuation_adjustment_bps
  effective_horizon_years
  expected_return_bps
  input_snapshot_hash / evidence_hash

CmaApprovalEvidence
  candidate_id / candidate_hash
  validation_report_id / validation_version
  reviewer_id / approver_id / decision / rationale
  approved_at / activation_scope / predecessor_id
  market_snapshot_hash / model_evidence_hash
```

Solver, Monte Carlo, Allocation, Recommendation, PDF, Signatur und Handoff
referenzieren diese IDs und Hashes; kein Kanal leitet die Wahrheit erneut aus
freien JSON-Notizen oder einem Statusstring ab.

## Verbindliche Regressionstests

- Trailing-P/E darf nicht ohne explizite Transformation gegen CAPE-Fair-Value
  laufen.
- Current/Fair Measurement-ID, Earnings-Fenster, Indexbasis und Jurisdiktion
  müssen identisch oder genehmigt transformiert sein.
- Fehlende Equity-Return-Komponente lässt den Gesamtreturn NULL/fail-closed.
- Golden-Test für vollständige Return-Zerlegung und Summengleichheit.
- Pro Kurvenpunkt bleiben Observation Date, Provider und Raw Hash erhalten.
- Mixed-date Curve außerhalb der Toleranz wird abgelehnt.
- Undatierter/staler PE-Proxy wird abgelehnt.
- Approval einer leeren, provisorischen, stale, manipulierten oder
  unvollständigen CMA liefert 409/422 und ändert Current nicht.
- Approval mit falschem Kandidatenhash stoppt bei Concurrent Change.
- Vier-Augen-/Self-Approval-Regel und append-only Evidence werden getestet.
- Resolver, Solver, MC, UI und PDF akzeptieren nur den exakt genehmigten Hash.
- Replay aus dem Observation Snapshot erzeugt bit-/toleranzidentische
  Modelloutputs.

## Verifikation dieser Runde

### Produktive Probes

- Nelson-Siegel-Short-Rate, KGV-Adjustment und resultierenden DE-Equity-
  Return mit den vorhandenen Testkurvenwerten berechnet.
- Pipeline-Rückgabetyp gegen `MacroPoint` geprüft; Observation Dates gehen
  nachweislich vor `source_detail` verloren.
- Approval-Endpoint und grünen Leer-CMA-Test statisch und dynamisch geprüft.
- Primär-/Originalquellen zur Begriffs- und Return-Zerlegung konsultiert.

### Unveränderte Bestandstests

Erster Gate:

```text
68 passed
10 setup errors: sqlite3.OperationalError: unable to open database file
```

Die zehn Fehler entstanden beim globalen App-Lifespan vor dem jeweiligen Test,
weil der Default-`DB_PATH` im aktuellen Sandboxkontext nicht schreibbar war.
Mit explizitem beschreibbarem `DB_PATH` wurden genau diese API-/Onboardingtests
erneut ausgeführt:

```text
python -m pytest -q --basetemp ..\tmp\round48_cma_retry \
  tests/test_cma_approval_endpoint.py \
  tests/test_de_onboarding_integration.py

10 passed, 2 warnings in 18.70s
```

Damit liefen alle 78 ausgewählten Tests. Die zwei Warnungen waren eine
bekannte `datetime.utcnow()`-Deprecation und ein lokaler Pytest-Cache-ACL-
Hinweis; kein Produkttest war rot.

Die grüne Suite widerlegt die Findings nicht. Insbesondere schreibt sie die
erfolgreiche Approval-Promotion einer leeren CMA als erwartetes Verhalten fest
und prüft nicht Measurement-Kompatibilität, vollständige Equity-Return-
Zerlegung oder Observation-Snapshot-Replay.

## Release-Entscheid

**Release-Hold bleibt bestehen.** Zusätzlich zu allen früheren P0/P1 gilt:

- Datenabgeleitete Nicht-CH-Equity-CMAs dürfen nicht real beraten werden,
  bevor Current/Fair-Messbasis und Return-Zerlegung genehmigt sind.
- Ein `committee_approved`-Status ohne gebundenen Preflight-/Approval-
  Evidence-Hash ist keine fachliche Freigabe.
- `fetched_at` darf nicht als Marktstichtag oder Replay-Nachweis verwendet
  werden.
- Bereits genehmigte datenabgeleitete CMAs sind gegen die neuen Verträge zu
  inventarisieren und bis zur Revalidierung als unverifiziert zu behandeln.

## Selbstkontrolle

- [x] Runde 47 abgegrenzt und keine Finding-ID dupliziert.
- [x] Repository-Kommentare nicht unkritisch als Validierung übernommen.
- [x] Externe Quellen nur zur Begriffsabgrenzung, nicht als Sollkalibrierung verwendet.
- [x] Negative Returnzahl produktiv reproduziert.
- [x] Approval einer wertleeren CMA im vorhandenen Testpfad bestätigt.
- [x] Harness-Fehler mit beschreibbarem DB-Pfad sauber wiederholt.
- [x] Priorität des nicht numerisch geflippten Snapshot-Befunds auf P2 begrenzt.
- [x] Produktcode, Tests, Schema, Migrationen und UI unverändert gelassen.
- [x] Nur die fünf Dokumentationspfade des Manifests vorgesehen.
