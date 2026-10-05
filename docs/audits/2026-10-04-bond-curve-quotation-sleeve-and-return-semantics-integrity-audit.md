# Bond-Zinskurven-, Quotierungs-, Sleeve- und Renditesemantik-Integritätsaudit

**Kontrollrunde 49 · Stand 04.10.2026 · Status: Release-Hold**

## Kurzfazit

Die Nelson-Siegel-Integration ist numerisch stabil getestet, ihr fachlicher
Vertrag ist jedoch in vier voneinander unabhängigen Punkten nicht
produktionsreif:

1. Die US-Pipeline übergibt Par-Yields auf halbjährlicher
   Bond-Equivalent-Basis, die DE-Pipeline dagegen kontinuierlich verzinste
   Zero-/Spotrates. Beide werden ohne Curve-Type-, Compounding- oder
   Day-Count-Normalisierung in dieselbe Spotkurvenfunktion gefittet.
2. Eine Staats-/AAA-Government-Kurve wird im Nicht-CH-Pfad unmittelbar als
   `bonds_home_ig_return_bps` gespeichert. Der Home-IG-Baustein umfasst laut
   Produktmodell aber Fonds bzw. Staats-/Unternehmensanleihen; eine
   Kreditspread-, Ausfall-/Migration-, Gebühren- oder Liquiditätskomponente
   fehlt.
3. Sobald die vier Nelson-Siegel-Felder aktiv sind, überschreibt der
   5-Jahres-Kurvenwert **nach** der korrekten Sub-Asset-Gewichtung den Return
   des gesamten Bond-Buckets. CHF IG, Global Hedged, High Yield und Emerging
   verlieren damit ihre genehmigten Return-Unterschiede.
4. Ein heutiger 5-Jahres-Yield wird als konstanter jährlicher erwarteter
   Portfolio-Return für jeden Planungshorizont verwendet. Coupon, Duration,
   Roll-down, Preisänderung, Reinvestment, Credit und FX-Hedge werden nicht
   modelliert; die vorhandene `bondsDuration`-Präferenz steuert keinen
   passenden 2-/5-/10-Jahres-Return.

Neu bestätigt sind vier P1:

- `NS-CURVE-QUOTE-NORMALIZATION-001`;
- `CMA-BOND-HOME-IG-PROXY-001`;
- `NS-BOND-SLEEVE-COLLAPSE-001`;
- `NS-YIELD-RETURN-HORIZON-001`.

Die entscheidende Produktprobe mit den bereits in Tests verwendeten
Sub-CMA- und Nelson-Siegel-Werten ergab:

```text
Rohannahme 100 % CHF IG             180 bps
Rohannahme 100 % High Yield         420 bps
Rohannahme 80 % CHF IG / 20 % HY    228 bps

mit aktivem Nelson-Siegel-Modell:
100 % CHF IG                         366 bps
100 % High Yield                     366 bps
80 % CHF IG / 20 % HY                366 bps
```

Das ist kein bloßer Dokumentationsmangel: Die Engine vernichtet eine
ökonomisch wesentliche Inputdimension, bevor Solver, Monte Carlo,
Asset Allocation und Zielwahrscheinlichkeiten rechnen.

## Auditbasis und Scope

Auditiert wurde Commit:

```text
c35d8fa
docs(audit): document jurisdiction CMA model risks
```

Geprüft wurden:

- FRED-/U.S.-Treasury- und EZB-Zinskurvensemantik;
- Nicht-CH-CMA-Kandidatenberechnung und Home-IG-Persistenz;
- Nelson-Siegel-Kurve, Kalibrierung, Forward- und Short-Rate-Semantik;
- CMA-Compiler, Sub-Asset-Gewichtung und Market-Adjustment-Reihenfolge;
- CH-/DE-Bond-Bausteine, Duration-Präferenz und Produktuniversum;
- Solver-/Haupt-MC-/Reporting-Methodology-Vertrag;
- bestehende Rate-, CMA-, Weighted-Metrics-, Methodology- und
  Jurisdiktions-Tests;
- Primärquellen der U.S. Treasury, EZB und SEC.

Produktionscode, Schema, Migrationen, Tests und UI wurden nicht verändert.
Persistiert werden ausschließlich die fünf Dokumentationspfade des
Auditmanifests.

## Verhältnis zu den Kontrollrunden 47 und 48

Runde 47 untersuchte den KGV-Adjustment-Vertrag; Runde 48 die Messbasis,
Return-Zerlegung, Snapshot- und Approval-Integrität der Nicht-CH-CMA. Runde 49
prüft die analoge Bond-Seite. Die IDs überschneiden sich nicht:

- Runde 48 beanstandet unter anderem fehlende Observation Dates und den
  Approval-Bypass.
- Runde 49 beanstandet Curve-Type/Quote-Konvention, Asset-Proxy,
  Sleeve-Erhaltung sowie Yield-/Total-Return-/Horizon-Semantik.

Alle Findings sind gemeinsam zu schließen. Ein Approval-Preflight macht ein
ökonomisch falsches Bondmodell nicht richtig; ein korrektes Bondmodell darf
umgekehrt nicht ohne Snapshot- und Approval-Evidence freigegeben werden.

## Findings-Register

| ID | Priorität | Status | Befund |
|---|---:|---|---|
| `NS-CURVE-QUOTE-NORMALIZATION-001` | P1 | neu bestätigt | US-Par-Yields auf halbjährlicher Bond-Equivalent-Basis und kontinuierlich verzinste EZB-Zero-/Spotrates werden ohne typisierte Normalisierung in dieselbe Nelson-Siegel-Spotkurve gegeben. |
| `CMA-BOND-HOME-IG-PROXY-001` | P1 | neu bestätigt | Eine Sovereign-/AAA-Government-Kurve wird ohne Credit-/Fee-/Liquidity-Komponenten als vollständiger Home-IG-Expected-Return persistiert. |
| `NS-BOND-SLEEVE-COLLAPSE-001` | P1 | neu bestätigt | Der aktive 5J-NS-Wert überschreibt nach der Sub-Asset-Gewichtung den gesamten Bond-Bucket und löscht Unterschiede zwischen IG, Global Hedged, HY und EM. |
| `NS-YIELD-RETURN-HORIZON-001` | P1 | neu bestätigt | Ein heutiger 5J-Yield wird unabhängig von Sleeve-Duration und Planungshorizont als konstanter jährlicher Portfolio-Total-Return verwendet. |

Keine bestehende Finding-ID wird geschlossen.

## Ende-zu-Ende-Systembild

```text
US Treasury/FRED                       ECB
par yield / semiannual BEY             zero spot / continuous compounding
            \                           /
             +-- raw percent * 100 ----+
                          |
                  same NS spot formula
                          |
                  curve.yield_at(5.0)
                          |
        +-----------------+------------------+
        |                                    |
non-CH candidate                    active NS CMA adjustment
bonds_home_ig_return_bps            applied after sleeve weighting
        |                                    |
government proxy labelled IG        IG / global / HY / EM -> same return
        +-----------------+------------------+
                          |
               constant annual MC mean
                          |
          Solver / Allocation / Goals / PDF
```

## `NS-CURVE-QUOTE-NORMALIZATION-001` – Verschiedene Kurvenobjekte werden gleich kompiliert

### Repository-Beleg

- `services/jurisdiction/data_pipeline.py:84-99` registriert die FRED-Reihen
  DGS3MO bis DGS30 als U.S.-Treasury-Constant-Maturity-Kurve.
- `data_pipeline.py:100-117` registriert für DE die EZB-Reihen
  `SV_C_YM`, ausdrücklich als Spotrate mit kontinuierlicher Verzinsung.
- `data_pipeline.py:209-220` reduziert beide Quellen auf
  `(maturity_years, value * 100)`; Curve-Type, Coupon-Frequenz,
  Compounding und Day Count sind kein Teil des Rückgabevertrags.
- `data_pipeline.py:309-318` fittet beide Vektoren identisch über
  `fit_nelson_siegel()` und liest `yield_at(5.0)`.
- `services/rates/nelson_siegel.py:84-96` leitet Forward Rates explizit unter
  Continuous Compounding ab; `short_rate_bps()` bezeichnet den Grenzwert als
  instantanen Spot.

### Primärquellen

Die U.S. Treasury erklärt, dass Constant-Maturity-Rates aus einer
**Par-Yield-Curve** gelesen werden, Bond-Equivalent-Yields für halbjährlich
zahlende Wertpapiere sind und weder effektive Jahresrenditen noch eine
Zero-Coupon-Kurve darstellen. Siehe
[U.S. Treasury – Interest Rates FAQ](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/interest-rates-frequently-asked-questions)
und
[Treasury Yield Curve Methodology](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/treasury-yield-curve-methodology).

Die EZB beschreibt ihre veröffentlichten Euro-Area-Kurven dagegen als
geschätzte Zero-Coupon-/Spotkurven und nennt Continuous Compounding als
Berechnungsannahme. Siehe
[ECB yield curve methodology](https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf).

Damit ist die Messbasisdifferenz keine Interpretation des Audits, sondern
offizielle Providersemantik.

### Größenordnung und Wirkung

Selbst bei nominell identischen 5,00 % unterscheiden sich die effektiven
Jahreswerte:

```text
5.00 % Bond-Equivalent, halbjährlich: (1 + .05/2)^2 - 1 = 5.0625 %
5.00 % kontinuierlich:               exp(.05) - 1       = 5.1271 %
Differenz:                                                    6.46 bps
```

Wichtiger als diese Einzelkonversion ist der Curve-Type: Par-Yields dürfen
nicht als Zero-/Spotrates behandelt werden. Ohne Bootstrap entstehen falsche
Discount Factors, Spot-/Forward-Rates und insbesondere ein methodisch nicht
vergleichbarer `short_rate_bps()`-Anker. Dieser Anker fließt auch in Equity-
und Risk-Premium-Modelle ein.

### Erforderliche Lösung

1. Jeder Marktpunkt benötigt mindestens `curve_type`, `quote_basis`,
   `compounding_frequency`, `day_count`, `currency`, `issuer_universe`,
   `rating_universe`, `observation_date` und `source_series`.
2. Eine versionierte Normalisierungsstufe erzeugt kanonische Discount Factors
   oder Zero Rates auf einer festgelegten Compounding-Basis.
3. U.S.-Parraten werden coupon- und frequenzkonsistent gebootstrapped; EZB-
   Spotrates werden entsprechend ihrer dokumentierten Basis konvertiert.
4. Erst die normalisierte Zero Curve darf Nelson-Siegel fitten und Spot-/
   Forward-/Short-Rates liefern.
5. Input-, Normalisierungs-, Kalibrierungs- und Output-Hash werden als
   immutable Evidence gespeichert und beim Approval geprüft.

## `CMA-BOND-HOME-IG-PROXY-001` – Government Yield ist kein vollständiger Home-IG-Return

### Repository-Beleg

- Die U.S.-Quelle besteht ausschließlich aus U.S. Treasuries.
- Die DE-Quelle besteht laut Registry aus AAA-Euro-Area-Government-Bonds.
- `data_pipeline.py:318` speichert den gefitteten 5J-Wert direkt als
  `bonds_home_ig_return_bps`.
- `data_pipeline.py:378-383` persistiert exakt diese Gleichsetzung als Formel.
- `docs/cma_import_workflow.md:72` beschreibt Bonds CHF IG dagegen als
  Schweizer Staats-/**Unternehmens**anleihen Investment Grade.
- Das Produktuniversum enthält für Home IG einen Bond-Fonds und für Global
  Hedged einen Aggregate-Bond-ETF, nicht ein einzelnes 5J-Staatspapier.
- Der DE-Seed nennt `Obligationen EUR IG` als EUR-Qualitätskern und mischt
  Global Hedged, High Yield und Emerging bei.

### Wirkung

Ein staatlicher oder AAA-staatlicher Yield kann ein Risk-Free-/Sovereign-
Basiselement sein. Er ist aber ohne genehmigte Ergänzungen kein erwarteter
Return eines IG-Fonds oder Aggregate-Portfolios. Es fehlen mindestens:

- Corporate-/Covered-/Agency-Credit-Spread und erwarteter Default-/Migration-
  Loss;
- Duration-/Coupon-/Roll-down-Komponente;
- Liquiditäts- und Indexzusammensetzung;
- Management Fee/TER und gegebenenfalls FX-Hedge-Kosten;
- Rebalancing- und Reinvestment-Policy.

Das Audit behauptet nicht, dass jeder Home-IG-Baustein zwingend Corporate
Bonds enthalten muss. Der Fehler ist, dass der Datenvertrag dies nicht
festlegt und eine reine Government-Kurve trotzdem als vollständigen
generischen Home-IG-Return benennt.

### Erforderliche Lösung

1. `risk_free_curve`/`sovereign_curve` strikt von `bond_sleeve_expected_return`
   trennen.
2. Pro Sleeve einen versionierten Return-Compiler definieren, beispielsweise:

```text
expected_bond_total_return
  = risk_free_carry
  + sovereign_or_credit_spread_carry
  + expected_roll_down
  + expected_price_change
  - expected_default_and_migration_loss
  - hedge_cost
  - fees_and_turnover
```

3. Index-/Produktuniversum, Ratingmix, Duration, Currency und Hedge-Policy
   binden.
4. Fehlende Pflichtkomponenten lassen den Sleeve-Return NULL und verhindern
   Approval; kein stiller Government-Proxy als Gesamtreturn.

## `NS-BOND-SLEEVE-COLLAPSE-001` – NS überschreibt die Sub-Asset-Wahrheit

### Repository-Beleg

- `_weighted_bucket_metrics()` in
  `services/portfolio_engine_cma.py:395-536` berechnet zunächst korrekt die
  gewichteten Sub-Asset-Returns.
- Unmittelbar vor der Rückgabe ruft Zeile 536
  `_apply_cma_market_adjustments(returns, cma)` auf.
- `_apply_cma_market_adjustments()` setzt bei aktivem NS-Modell in
  `portfolio_engine_cma.py:272-275` `adjusted["bonds"]` vollständig auf den
  5J-Kurvenwert; es addiert keinen Basis-/Spread-Term und differenziert keine
  Sleeves.
- Das kanonische Universum besitzt getrennte Annahmen für CHF IG, Global
  Hedged, High Yield und Emerging (`portfolio_engine.py:1205-1208`).
- Die bestehenden Weighted-Metrics-Tests prüfen den HY-Tilt nur mit
  **inaktivem** NS-Modell. Die Rate-Integrationstests prüfen aktives NS nur
  ohne differenzierte Bond-Sleeves.

### Produktive Gegenprobe

Die Probe verwendete unverändert die Testannahmen 180 bps CHF IG und 420 bps
High Yield sowie die NS-Parameter `beta0=400`, `beta1=-150`, `beta2=50`,
`lambda=0.6`:

```text
                                    ohne NS    mit NS
100 % CHF IG                        180        366
100 % High Yield                    420        366
80 % CHF IG / 20 % High Yield       228        366
```

Ein temporärer Contract-Test verlangte, dass 100 % IG und 100 % HY
unterschiedliche Returns behalten. Er schlug deterministisch mit
`assert 366 != 366` fehl. Die Probe wurde danach entfernt.

### Wirkung

- Präferenz- und Recommendation-Unterschiede ändern Risiko/Volatilität,
  nicht aber den erwarteten Bond-Return.
- Ein HY-/EM-Tilt verliert seine genehmigte Risikoprämie.
- Solver und MC optimieren gegen eine andere ökonomische Basis als Admin-CMA,
  Sub-Allocation und Produktdarstellung suggerieren.
- Zielwahrscheinlichkeit, erwarteter Portfolioreturn, Sensitivity und PDF
  können formal konsistent, aber fachlich falsch sein.
- Die Methodology-Anzeige meldet lediglich „Bond-Returns aus Yield-Curve“ und
  legt den Verlust der Sleeve-Differenzierung nicht offen.

### Erforderliche Lösung

1. NS liefert nur den typisierten risikofreien/sovereign Basisterm.
2. Pro Sleeve werden genehmigte Spread-/Loss-/Hedge-/Fee-Komponenten addiert.
3. Die Berechnung erfolgt **pro Sub-Asset vor Gewichtung**; erst danach wird
   zum Bucket aggregiert.
4. Bei fehlendem Sleeve-Modell fail-closed oder explizit auf den genehmigten
   vollständigen Sub-CMA-Return zurückfallen; niemals alle Sleeves auf einen
   Wert setzen.
5. Model Evidence speichert Inputs und Komponenten pro Sleeve sowie den
   gewichteten Bucket-Nachweis.

## `NS-YIELD-RETURN-HORIZON-001` – 5J-Yield wird zum horizonlosen Total Return

### Repository-Beleg

- `services/cma_validation.py:19` definiert die einzige Laufzeit als
  `NELSON_SIEGEL_DEFAULT_MATURITY_YEARS = 5.0`.
- `scenario_engine.py:683` bindet diesen Wert als globalen Bond-Default.
- `_compute_bonds_return_from_nelson_siegel()` akzeptiert nur `cma`, keinen
  Mandats-, Simulations-, Holding- oder Sleeve-Horizont.
- `scenario_engine.py:775-805` gibt `yield_at(5J)` als „Bond-Return“ zurück.
- `data_pipeline.py:318` nutzt dieselbe Konvention für Nicht-CH-CMA.
- Der Planning-Spec versprach Maturities pro Bond-Bucket 2J/5J/10J und nennt
  Curve Dynamics sowie explizites Reinvestment als spätere Phase. Der
  Runtimepfad besitzt diese Differenzierung nicht.
- Der DE-Seed bietet `Kurzfristig`, `Gemischt`, `Langfristig`, aber keine
  dieser Präferenzen wird als Maturity/Duration an den Return-Compiler
  übergeben.

Die SEC erläutert, dass Yield to Maturity die Rendite beim Halten bis zur
Fälligkeit beschreibt und dass sich Bondpreise bei Zinsänderungen invers
bewegen; Laufzeit beeinflusst das Zinsänderungsrisiko. Siehe
[SEC Investor Bulletin – Fixed Income and Interest Rate Risk](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-86).

### Größenordnung

Für dieselbe Testkurve liefert das Modell:

```text
2 Jahre    326.7065 bps
5 Jahre    365.8369 bps
10 Jahre   383.2507 bps
```

Die 5J-Konvention liegt hier rund 39 bps über 2J und 17 bps unter 10J. Diese
Differenzen werden trotz Duration-Präferenz und Mandatshorizont nie gewählt.
Noch wichtiger: Keiner der drei Yields ist automatisch der jährlich
realisierte Total Return eines über Jahre rollierenden Fondsportfolios.

### Erforderliche Lösung

1. `BondReturnContext` einführen: valuation date, holding period,
   target maturity/duration, coupon/index policy, rebalance, currency/hedge,
   spread/default model und fee basis.
2. Duration-Präferenz und tatsächliche Sleeve-/Produktduration verbindlich
   auf den Context mappen.
3. Für Buy-and-Hold, Constant-Maturity-Roll und rebalancierten Fonds
   unterschiedliche, explizite Modelle verwenden.
4. Bei Mehrperioden-MC entweder versionierte Curve Dynamics implementieren
   oder die statische Vereinfachung als genehmigte Szenarioannahme mit
   Gültigkeitsbereich, Unsicherheit und Limit offenlegen.
5. Planning Horizon und Bond Holding Period getrennt modellieren; keine
   Gleichsetzung aufgrund identischer Jahreszahl.

## Kanonische Zielarchitektur für Claude

```text
YieldCurveObservationSnapshot
  provider / series / observation_date / raw_hash
  currency / issuer_universe / rating_universe
  curve_type = par | zero | forward
  quote_basis / compounding / day_count / coupon_frequency

NormalizedDiscountCurve
  normalization_version / bootstrap_version
  discount_factors[] / zero_rates[] / canonical_compounding
  source_snapshot_hash / calibration_hash / fit_diagnostics

BondReturnContext
  valuation_date / holding_period / planning_horizon
  sleeve_id / index_or_product_universe
  target_maturity / effective_duration / coupon_policy
  credit_rating_mix / currency / hedge_policy / rebalance_policy

BondSleeveReturnEvidence
  risk_free_carry / spread_carry / roll_down / price_change
  default_migration_loss / hedge_cost / fees_turnover
  expected_total_return / uncertainty / model_version
  curve_hash / context_hash / approval_evidence_id

BondBucketEvidence
  sleeve_returns[] / exact sleeve weights
  weighted_return / weighted_risk / aggregation_version
  run_id / allocation_id / model_basis_hash
```

Solver, allgemeiner Monte Carlo, Allocation, Goal Probability, Sensitivity,
Recommendation, UI, PDF, Signatur und Handoff müssen denselben gebundenen
`BondBucketEvidence`-Hash verwenden.

## Verbindliche Regressionstests

- U.S.-Par-/BEY- und EZB-Zero-/Continuous-Inputs müssen vor Kalibrierung auf
  dieselbe kanonische Basis normalisiert werden.
- Ein Par-Yield darf nicht ohne Bootstrap als Zero Rate verwendet werden.
- Quote-/Compounding-/Day-Count-Metadaten fehlen -> Kandidat/Approval stoppt.
- Home-IG-Return fehlt eine genehmigte Spread-/Loss-/Fee-Komponente -> NULL
  oder fail-closed.
- Bei aktivem NS bleiben 100 % IG und 100 % HY ökonomisch verschieden.
- Ein 80/20-IG/HY-Mix entspricht exakt der gewichteten Summe seiner
  vollständigen Sleeve-Returns.
- `Kurzfristig`, `Gemischt`, `Langfristig` binden unterschiedliche
  Maturity-/Duration-Contexts und erzeugen erklärbare Outputs.
- 2J-/5J-/10J-Kontexte werden nicht auf denselben 5J-Wert reduziert.
- Yield-to-maturity, erwarteter Holding-Period-Return und realisierter
  Total Return sind im Schema und in UI/PDF getrennt benannt.
- Static-Curve- und Dynamic-Curve-Modus sind versioniert, sichtbar und
  gegeneinander golden-getestet.
- Solver, Haupt-MC, Sensitivity, Reporting und PDF konsumieren denselben
  Bond-Evidence-Hash; Replay reproduziert den Output.
- Freigabe blockiert bei verändertem Curve-, Context-, Sleeve- oder
  Aggregationshash.

## Verifikation dieser Runde

### Produktive Probes

- 100-%-IG-, 100-%-HY- und 80/20-Mix durch denselben produktiven
  `_weighted_bucket_metrics()`-Pfad materialisiert.
- 2J-/5J-/10J-Yields derselben produktiven `NelsonSiegelCurve` verglichen.
- 5-%-Quote auf U.S.-BEY- und Continuous-Effective-Basis gegengerechnet.
- Temporären Red-Contract-Test für Sleeve-Erhaltung ausgeführt und entfernt.
- FRED/Treasury-/EZB-/SEC-Primärquellen gegen den Codevertrag geprüft.

### Unveränderte Bestandstests

```text
python -m pytest -q --basetemp ..\tmp\round49_bonds\pytest \
  tests/rates/test_nelson_siegel.py \
  tests/rates/test_engine_integration.py \
  tests/test_ns_calibration_2024.py \
  tests/test_audit_z4_weighted_metrics.py \
  tests/test_methodology_models_audit.py \
  tests/test_cma_data_pipeline.py \
  tests/test_engine_de_jurisdiction_wiring.py

97 passed, 1 warning in 17.28s
```

Die Warnung betrifft ausschließlich den bekannten lokalen Pytest-Cache-ACL-
Pfad. Der beschreibbare temporäre Testpfad wurde nach dem Gate entfernt.

Zusätzlicher temporärer Contract-Test:

```text
FAILED ... test_active_ns_preserves_credit_sleeve_return_differentiation
AssertionError: ...
assert 366 != 366
```

Dieser erwartete Red-Test beweist das Finding und wurde anschließend entfernt.
Die grüne Bestandssuite widerlegt die Findings nicht: Sie testet NS und
Sub-Asset-Gewichtung jeweils isoliert, nicht ihre kritische Kombination.

## Release-Entscheid

**Release-Hold bleibt aktiv.** Reale Mandate dürfen nicht auf einem aktiven
Nelson-Siegel-Bondmodell oder einer datenabgeleiteten Nicht-CH-Home-IG-CMA
freigegeben werden, bis:

1. Curve-Type und Quote-Konvention normalisiert und evidenzgebunden sind;
2. Government-/Risk-Free-Kurve und vollständiger Sleeve-Expected-Return
   getrennt sind;
3. Credit-, Hedge-, Fee- und Duration-Unterschiede pro Sleeve erhalten
   bleiben;
4. Holding Period, Duration und Planungshorizont explizit gebunden sind;
5. Solver, MC, Allocation, Goals, UI, PDF, Signatur und Handoff dieselbe
   immutable Bond-Evidence konsumieren;
6. die neuen Red-/Golden-/Replay-/Cross-Channel-Tests sowie die vollständigen
   Zielumgebungs-Suites grün sind.

Der heutige Runtimepfad erzwingt diesen Hold nicht vollständig technisch.
