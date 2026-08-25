# 5eyes WealthArchitekten — Methodik-Whitepaper

**Version:** 2026-07-19 · **Zweck:** Nachvollziehbare Offenlegung der Berechnungs- und
Beratungsmethodik der 5eyes-Engine für Aufsicht (FINMA), Compliance und Berater.
**Charakter:** Faktenbelegt, konservativ. Jeder Abschnitt nennt die tragende
Code-Referenz (Datei : Funktion), damit Aussagen am Quellcode überprüfbar sind.

> Alle Referenzen beziehen sich auf das Backend-Verzeichnis
> `5eyes-backend/`. Beträge werden intern in **Rappen** (1 CHF = 100 Rappen) und
> Prozentwerte in **Basispunkten (bps)** geführt (1 % = 100 bps), um
> Rundungsdrift zu vermeiden. Dieses Dokument beschreibt ausschliesslich die
> tatsächlich implementierte Logik; Verfahren, die im Code nicht belegbar sind,
> werden nicht behauptet.

---

## Zusammenfassung

Die 5eyes-Engine bildet eine strukturierte, regelbasierte Vermögensberatung ab.
Sie führt den Berater von der Situationsanalyse über Cashflows und Ziele, das
Risikoprofil und die strategische Asset-Allokation (SAA) bis zum konkreten
Portfoliovorschlag. Die Zukunftsprojektion beruht auf einer Monte-Carlo-Simulation
mit korrelierten, log-normalverteilten Renditepfaden (Cholesky-Zerlegung der
CMA-Korrelationsmatrix, Itô-Korrektur, optionale Cornish-Fisher-Fat-Tails) und
liefert deterministisch reproduzierbare Ergebnisse über gehashte Seeds. Ziel-
erreichung wird methodenkonform mit **Median (P50)** und einem **pessimistischen
Fehlbetrag aus dem schlechtesten Quartil (P25)** ausgewiesen; die Sequence-of-
Returns-Problematik (Vermögensverzehr) wird explizit modelliert.

Die Anlagephilosophie ist bewusst **ohne Markt-Timing** ausgelegt: Es gibt keine
automatischen Handelssignale; Rebalancing erfolgt ausschliesslich im Rahmen der
Eignungsprüfung oder auf Kundenwunsch. Die Engine ist entlang der FIDLEG-Pflichten
gebaut (Eignungsprüfung, Kostenausweis, Beratungsprotokoll) und trennt Mandate
strikt.

---

## 1. Die Beratungs-Journey: SD → Cashflow/Ziele → Risikoprofil → SAA → Portfolio

Die Engine folgt der etablierten Beratungslogik in fünf Stufen:

1. **Situationsanalyse / Standortbestimmung (SD):** Erfassung von Gesamt- und
   Beratungsvermögen, Verbindlichkeiten und Rahmendaten.
2. **Cashflow & Ziele:** Datierte Ein- und Auszahlungen sowie Sparziele/
   Ausgabenziele werden in eine jahresweise Projektionsreihe überführt.
3. **Risikoprofil:** Das (signierte, mandatsbezogene) Risikoprofil bestimmt die
   zulässigen Bandbreiten je Anlageklasse.
4. **Strategische Asset-Allokation (SAA):** Ableitung der Zielgewichte innerhalb
   der Risikoprofil-Bänder (House-Matrix), inklusive Renditeziel-Tilt und
   Reserve-Herleitung.
5. **Portfolio (PO):** Der konkrete Produktvorschlag ist die Ableitung der SAA —
   kein Bestand-gegen-Empfehlung-Abgleich, sondern eine methodisch konsistente
   Umsetzung der Strategie.

Das Portfolio ist damit definitionsgemäss die **Ableitung der SAA**. Die
zentrale Orchestrierung der Zielallokation erfolgt in
`generate_target_allocation` bzw. beim Wiederaufbau aus einer bestehenden
Allokation in `build_target_payload_from_allocation`; die Zielbewertung
(Goal-Analyse) läuft über `_build_goal_analysis`.

**Code-Referenz:** `services/portfolio_engine.py : generate_target_allocation`,
`services/portfolio_engine.py : build_target_payload_from_allocation`,
`services/portfolio_engine.py : _build_goal_analysis`.

---

## 2. Monte-Carlo-Simulation der Vermögensentwicklung

Kern der Zukunftsprojektion ist eine Monte-Carlo-Simulation über den gesamten
Planungshorizont. Sie wird sowohl für die IST-Allokation (`current`) als auch
für die SOLL-Allokation (`target`) mit identischer Methodik gerechnet, damit ein
sauberer, zweispaltiger Kennzahlenvergleich (VaR, CVaR, Drawdown, Verlust-
wahrscheinlichkeit, Volatilität) möglich ist.

**Korrelierte Pfade (Cholesky).** Pro Simulationsjahr werden für die fünf
Anlageklassen (`BUCKET_FIELDS = equities, bonds, real_estate, alternatives,
liquidity`) zunächst unabhängige Standardnormalvariablen gezogen und
anschliessend über die untere Dreiecksmatrix der Cholesky-Zerlegung korreliert
(`Z = L · W`). Die Matrix `L` wird aus der CMA-Korrelationsmatrix
(`correlation_matrix_json`) gebildet; ist diese nicht positiv-definit, greift ein
gestaffelter Fallback (kundenspezifisch → Schweizer-Markt-Default → Identität/
unkorreliert). Optional lässt sich ein **Krisen-Korrelationsmodus** zuschalten,
der die Korrelationen der Risky-Assets Richtung +0,9 zieht (Diversifikations-
Zusammenbruch im Stress), während Liquidität als Safe-Haven unkorreliert bleibt.

**Momententreues Log-Normal-Wachstum.** Die CMA-Werte `μ` und `σ` sind
Mittelwert und Standardabweichung des einfachen Returns. Mit
`v = log(1 + (σ/(1+μ))²)`, `σ_ln = sqrt(v)` und
`μ_ln = log(1+μ) − ½v` lautet der Jahresfaktor
`exp(μ_ln + σ_ln · Z)`. Dadurch entsprechen sowohl Erwartungswert als auch
einfache Return-Volatilität exakt den CMA-Momenten. Bei Cornish-Fisher-Tails
werden Location und Scale nach Begrenzung der Innovation numerisch auf dieselben
Momente kalibriert. Ein optionaler Stress-Multiplikator skaliert die einfache
CMA-Volatilität vor dieser Abbildung.

**Cornish-Fisher-Fat-Tails.** Bei aktivierter Tail-Risk-Option werden die
korrelierten Normal-Samples je Anlageklasse über eine **Cornish-Fisher-Expansion
bis zur 4. Ordnung** transformiert, um Schiefe (Skewness) und Exzess-Kurtosis aus
den CMA-Feldern (`{bucket}_skewness_bps`, `{bucket}_excess_kurt_bps`) abzubilden:
`z' = z + (z²−1)·S/6 + (z³−3z)·K/24 − (2z³−5z)·S²/36`. Bei `S = 0` und `K = 0`
bleibt `z` unverändert (abwärtskompatibel, keine ungewollte Verzerrung).

**Deterministische Hash-Seeds.** Die Simulation ist reproduzierbar: Der Seed wird
per SHA-256 aus einem Bündel identitätsstiftender Parameter gebildet (Mandats-ID,
CMA-ID, Horizont, Simulationszahl, Stress-Multiplikator, Rebalancing-Modus,
Zielgewichte, Sub-Allocation-Signatur, Transaktionskosten, Korrelationsmatrix).
Gleiche Eingaben liefern damit exakt gleiche Pfade — prüfbar und auditierbar.
Die Simulationszahl ist auf `[250, 2500]` begrenzt (Default 2500).

Liquidität wird in der Projektion bewusst flach gehalten (μ = 0, σ = 0), damit
Zinserträge nicht doppelt gezählt werden — sie fliessen ausschliesslich über den
abgeleiteten Zinsertrags-Cashflow ein.

**Code-Referenz:** `services/portfolio_engine.py : _run_allocation_monte_carlo`
(Pfadschleife, Itô-Korrektur), `_build_cholesky_from_cma`, `_crisis_stress_matrix`,
`_cornish_fisher_transform`, `_monte_carlo_seed`, `_monte_carlo_simulations`,
`_weighted_bucket_metrics`. Konstante `DEFAULT_MONTE_CARLO_SIMULATIONS = 2500`.

---

## 3. Stochastischer Optimizer (Mulvey/Ziemba-light)

Neben der House-Matrix-Ableitung verfügt die Engine über einen optionalen
stochastischen Optimizer im Stil des mehrperiodigen Asset-Liability-Managements
(Mulvey/Ziemba-light). Er wird über die Konfiguration **`OPTIMIZER_MODE`**
gesteuert (`house_matrix` = Default ohne Solver, `shadow_stochastic` = Solver
läuft als Methodenvergleich parallel, während die House-Matrix aktive
Zielallokation bleibt, `stochastic` = Solver darf die Zielallokation bei
Konvergenz ersetzen).

**Chance-constrained Shortfall²-Zielfunktion.** Die Zielfunktion minimiert den
gewichteten mittleren **quadrierten Fehlbetrag (Shortfall²)** je Ziel über alle
Szenariopfade: `L(w) = Σ_g h_g · g_g · mean_n(shortfall(g,n)²)`. Der Fehlbetrag
ist stets `max(0, Ziel − erreichtes Vermögen)` (bzw. für Ausgabenströme die
verbleibende „Lebenslücke"), quadriert — grosse Verfehlungen werden also
überproportional bestraft. Ergänzend wirkt eine **Chance-Constraint-Penalty**:
Für harte/primäre Ziele wird die Erreichungswahrscheinlichkeit gegen eine
Zielschwelle (`tau`, Default 80 %) geprüft und eine Unterschreitung quadratisch
mit einem hohen Lagrange-Faktor bestraft. Ist die Zielerreichung im Wesentlichen
erfüllt, tritt sekundär ein Varianz-Term (Endvermögens-Volatilität) hinzu.

**Härtegrad-Gewichte.** Ziele tragen einen Härtegrad — `hart`, `primaer`,
`opportunistisch` — mit hinterlegten Gewichten (`HARDNESS_WEIGHT =
{hart: 10, primaer: 1, opportunistisch: 0.2}`). Methodenkonform ist die
Härtegrad-Gewichtung **standardmässig deaktiviert** (Modus `equal`, alle Ziele
gleich); sie wird nur über `OPTIMIZER_GOAL_WEIGHTING=hardness` aktiviert. Die
zielindividuelle Gewichtung `g_g` (aus dem Liability-Gewicht) wird stets angewandt.

**Solver mit DE-Fallback.** Primär löst ein **SLSQP-Multistart** (mehrere
Startpunkte, sequentielle quadratische Programmierung) unter den
Allokations-Nebenbedingungen. Findet kein Start eine zulässige, konvergierte
Lösung, greift als Fallback ein **Differential-Evolution-Verfahren (DE,
`scipy.optimize.differential_evolution`)** mit penalisierter Zielfunktion und
Renormierung auf Summe = 1. Scheitert auch dieses, fällt der Solver
kontrolliert auf den House-Matrix-Mittelpunkt zurück (`fallback_house_matrix`).
(Anmerkung: Der Fallback ist im Code historisch als „GA" benannt, implementiert
ist jedoch Differential Evolution.)

**Importance-Sampling.** Zur varianzreduzierten Schätzung der Tail-Risiken nutzt
der Optimizer optionales **Mean-Shift-Importance-Sampling** (Glasserman): Die
zugrundeliegenden Standardnormalen werden in den Verlust-Tail verschoben
(standardmässig negativer Shift auf den Aktien-Bucket) und über
Likelihood-Ratio-Gewichte (Radon-Nikodym) erwartungstreu korrigiert. Es wird
automatisch aktiviert bei konservativem Profil, Ruhestand (Sequence-of-Returns-
Risiko) oder harten Zielen (`decide_is_for_context`). Die Szenariopfade selbst
werden korreliert (Cholesky) und log-normal mit Cornish-Fisher-Fat-Tails
(Skew/Kurtosis geklammert) erzeugt — methodisch identisch zum Haupt-MC —
und nutzen zusätzlich antithetische Variate zur Varianzreduktion.

**Code-Referenz:**
`services/optimizer/objective.py : shortfall_objective`,
`shortfall_squared_per_path`, `chance_constraint_penalty`,
`combined_objective_two_phase` (Konstanten `HARDNESS_WEIGHT`, `LAMBDA_CHANCE_DEFAULT`);
`services/optimizer/solver.py : run_solver`, `_solve_single_start` (SLSQP),
`_solve_via_genetic_algorithm` (Differential Evolution);
`services/optimizer/importance_sampling.py : build_shift_vector`,
`compute_likelihood_weights`, `decide_is_for_context`;
`services/optimizer/distributions.py : cornish_fisher_quantile`,
`standard_normal_to_log_return`;
`services/optimizer/scenario_engine.py : build_scenario_paths`,
`simulate_wealth_paths`, `scenario_inputs_from_cma`;
`services/optimizer/goal_liabilities.py : goals_to_liabilities`.
Konfiguration: `config.py` (`optimizer_mode`, env `OPTIMIZER_MODE`).

---

## 4. Capital Market Assumptions (CMA)

Die CMA bündeln die kapitalmarktseitigen Annahmen (erwartete Renditen,
Volatilitäten, höhere Momente und Korrelationen) je Anlageklasse und
Sub-Anlageklasse. Sie sind der einzige Ort, an dem Renditeerwartungen gepflegt
werden.

**Sub-Anlageklassen.** Die Engine kennt granulare Sub-Anlageklassen mit eigenen
Rendite-/Volatilitätsannahmen, u. a. Aktien (Schweiz, Schweiz Small/Mid, Global,
Europa, Schwellenländer sowie Themen-Sleeves), Obligationen (CHF IG, Global
Hedged, High Yield, Emerging), Immobilien (Schweiz, Global) und Alternative
(Gold/Rohstoffe, Liquid Alternatives, Hedge Funds). Die tatsächlichen Bucket-
Metriken für die Simulation werden **gewichtet aus der effektiven Sub-Allokation**
gebildet (`_weighted_bucket_metrics`) — das blosse Vorhandensein einer Annahme im
CMA zieht die Bucket-Rendite nicht ungewollt nach oben.

**Nelson-Siegel-Zinskurve & KGV-Mean-Reversion.** Marktnahe Anpassungen der
erwarteten Renditen werden im Haupt-MC-Pfad angewandt: Die Obligationenrendite
kann aus einer **Nelson-Siegel-Zinskurve** abgeleitet werden, die Aktienrendite
um einen **KGV-Mean-Reversion-Term** (Bewertungs-Rückkehr zum Mittel) additiv
korrigiert, und Immobilien/Alternative über Risikoprämien auf die
Nelson-Siegel-Short-Rate. Fehlen die nötigen CMA-Felder, bleiben die Renditen
unverändert (abwärtskompatibel).

**Modell & Datenhaltung.** Die CMA sind als versioniertes Datenmodell
(`CapitalMarketAssumption`) gepflegt: paarweise `_return_bps`/`_vol_bps`-Felder je
Sub-Anlageklasse (Aktien CH/International/EM, Obligationen CHF-IG/FX-hedged/HY,
Immobilien CH, Gold, Liquidität), höhere Momente (`{bucket}_skewness_bps`,
`{bucket}_excess_kurt_bps`) je Top-Level-Bucket, die 5×5-Korrelationsmatrix
(`correlation_matrix_json`), sowie die Parameter der Nelson-Siegel-Kurve
(`bonds_ns_beta0/1/2_bps`, `bonds_ns_lambda_x100`) und der KGV-Mean-Reversion
(`equity_kgv_current_x10`, `equity_kgv_fair_x10`, `equity_kgv_alpha_x100`).
Zeitliche Gültigkeit (`valid_from`/`valid_until`, `is_current`, `version`) macht
Annahmen nachvollziehbar.

**Datenqualitäts-Guard.** Volatilitäten dürfen nicht negativ sein: Die
Eingabevalidierung weist jede negative Sub-Klassen-Volatilität mit einer
klaren Fehlermeldung ab (negative *Renditen* bleiben zulässig, da fachlich
möglich). Damit werden NaN/komplexe Werte in der Kovarianz-/Cholesky-Bildung der
Monte-Carlo-Simulation ausgeschlossen. Die Nelson-Siegel-Kurve selbst ist als
`y(τ) = β₀ + β₁·(1−e^{−λτ})/(λτ) + β₂·((1−e^{−λτ})/(λτ) − e^{−λτ})`
implementiert (bps), mit Kalibrierung per Least-Squares; die KGV-Mean-Reversion
liefert einen additiven Renditeaufschlag/-abschlag proportional zur
Fehlbewertung `(KGV_fair − KGV_aktuell)/KGV_fair` mit Reversionsgeschwindigkeit
α und einer Zeit-Dämpfung.

**Code-Referenz:**
`models/allocation.py : CapitalMarketAssumption`;
`schemas/allocation.py : CapitalMarketAssumptionCreate._validate_cma` (Vola ≥ 0);
`services/rates/nelson_siegel.py : NelsonSiegelCurve`, `fit_nelson_siegel`;
`services/equity_valuation/mean_reversion.py : KGVMeanReversionModel`;
`services/portfolio_engine.py : _apply_cma_market_adjustments`,
`_asset_class_expected_metrics`, `_sub_asset_class_assumption_map`;
`services/optimizer/scenario_engine.py : _compute_bonds_return_from_nelson_siegel`,
`_compute_equity_kgv_adjustment`, `_compute_return_from_risk_premium`.

---

## 5. Reserve-Herleitung (Liquiditätsreserve)

Die erforderliche Liquiditätsreserve wird zentral und für Generierungs- und
Wiederaufbau-Pfad identisch bestimmt (Single Source of Truth), damit sie nicht
divergieren kann.

**Additive Ziel-Reserven, max-Floor.** Aus mehreren gleichzeitigen Ausgabenzielen
ergibt sich ein **additiver** Liquiditätsbedarf: Kurzfristige Spending-Ziele
werden aufsummiert (`goal_reserve_sum`), statt nur das grösste Ziel zu zählen —
das verhindert eine systematische Unterreservierung. Zeitliche Staffelung:
Ziele in ≤ 3 Jahren voll, in ≤ 7 Jahren zu 50 %; optional stehen Smooth-Decay-
und Zeit-Bucket-Modi bereit. Floor-Kandidaten — manuell gesetzte Mindestreserve,
Liquiditäts-Zieltopf und ein Cashflow-Shortfall der nächsten drei Jahre — werden
demgegenüber über **`max()`** kombiniert. Der finale Reservebedarf ist das Maximum
über alle Kandidaten (`reserve_needed_rappen = max(reserve_candidates)`).

**Fachliche Feinheiten.** AHV-/staatlich gedeckte Ziele tragen keinen
Reservebedarf aus dem Beratungsmandat; bedingte Ziele werden linear mit ihrer
Wahrscheinlichkeit gewichtet; Wealth-Inflows (Erbschaft, Bonus, Verkaufserlöse)
in den ersten drei Jahren reduzieren die kurzfristige Reserve.

**Externe Reserve.** Übersteigt der Reservebedarf die SAA-Liquiditätsobergrenze,
wird der Überhang als **externe Reserve ausserhalb des Beratungsmandats**
ausgewiesen, damit die SAA-Liquidität im Zielband bleibt; verfügbares „anderes
Vermögen" mit Goal-Funding-Schloss kann diesen externen Bedarf decken.

**Code-Referenz:** `services/portfolio_engine.py : _compute_reserve_for_inputs`.

---

## 6. Zielerreichung und Vermögensverzehr

**Median-Zielerreichung, pessimistischer Fehlbetrag (P25).** Je Ziel wird die
Zielerreichung methodenkonform ausgewiesen: die **effektiv erreichte Quote im
Median (P50)**, auf 100 % gedeckelt, sowie ein **pessimistischer CHF-Fehlbetrag
aus dem schlechtesten Quartil (P25-Pfad)**. Für Ausgaben-/Vermögensziele ist der
Fehlbetrag `max(0, Ziel − P25)`; für Renditeziele wird die Rendite über den
P25-Renditepfad in ein implizites Endvermögen umgerechnet und die Differenz zum
gewünschten Endvermögen als CHF-Betrag ausgewiesen. Die Erfolgsrate
(`success_rate_pct`) ist der Anteil der Pfade, die das Ziel erreichen.

Die Bewertung unterscheidet Zieltypen (Renditeziel, einmalige/wiederkehrende
Ausgabe, Pensionsausgabe, Kapitalerhalt/Vermögensziel, Maximierung) und kombiniert
Erfolgsrate und Deckungsgrad zu einem Score, wobei „Härtegrad"-Gewichte
(`hardness_key`) die relative Priorität eines Ziels einfliessen lassen.

**Sequence-of-Returns / Verzehr.** Der Vermögensverzehr wird pfadweise erfasst:
Für jeden Simulationspfad wird das erste Jahr registriert, in dem das Vermögen
aufgezehrt ist (Pfad-Total ≤ 0). Daraus ergeben sich eine
**Verzehr-Wahrscheinlichkeit** und ein **mittleres Erschöpfungsjahr** — separat
für SOLL und IST. Ein vollständig aufgezehrter Pfad geht mit −100 % (−10 000 bps)
in die Renditestatistik ein, nicht mit 0 %, damit Median und Erfolgsrate nicht
geschönt werden. Renditen werden zudem **cashflow-bereinigt** (time-weighted,
geometrische Verkettung der Markt-Wachstumsfaktoren vor Cashflow) gemessen, damit
Ein-/Auszahlungs-Timing die ausgewiesene Strategie-Performance nicht verzerrt.

**Code-Referenz:** `services/portfolio_engine.py : _monte_carlo_goal_summary`,
`_sequence_of_returns_depletion`, `_twr_annualized_bps`, `_annualized_return_bps`.

---

## 7. Gesamtvermögen und Reinvermögen (Immobilie als Fundament)

Die Engine führt Pfade sowohl für das **Beratungsvermögen** (advisory) als auch
für das **Gesamtvermögen** (total) parallel durch die Simulation. Verbindlichkeiten
(z. B. Hypothek) werden als anfänglicher Fehlbetrag auf den IST-Gesamtvermögens-
pfad getragen, während der SOLL-Gesamtvermögenspfad sie bereits beim Start abzieht
— das Ergebnis ist ein **Reinvermögen**-orientierter Verlauf.

Externe Vermögensbestandteile (insbesondere die selbstgenutzte Immobilie) wirken
als **fixes Fundament**: Bei Zielen im Gesamtvermögens-Scope werden externe Assets
**nur mit Teuerung** fortgeschrieben (real 0 %, keine Volatilität) und
deterministisch — also ohne Monte-Carlo-Drift — auf jeden Pfad addiert. Die
Immobilie wird damit nicht „wegoptimiert", sondern als stabiler Sockel des
Vermögens behandelt.

**Code-Referenz:** `services/portfolio_engine.py : _run_allocation_monte_carlo`
(parallele `total_*`-Pfade, Liabilities als Start-Defizit),
`_monte_carlo_goal_summary` (Gesamtvermögens-Scope, `_external_assets_inflation_value`).

---

## 8. Steuer-Plugin-Architektur

Steuern sind als erweiterbare **Plugin-Architektur nach dem Strategy-+-Registry-
Muster** modelliert, damit weitere Jurisdiktionen ohne Eingriff in den Kern
ergänzt werden können. Zwei bewusst getrennte Schnittstellen (beide als
`typing.Protocol`, `@runtime_checkable`) decken die beiden Rechenpfade ab:

- **`TaxRegime`** — der Optimizer-/Pfad-nahe Vertrag mit Methoden wie
  `annual_wealth_tax`, `dividend_tax`, `interest_tax`, `capital_gains_tax`,
  `pension_lumpsum_tax`, `inheritance_tax`, `validate_parameters` und
  `with_overrides`. Eingabe/Ausgabe sind unveränderliche Dataclasses
  (`TaxContext` → `TaxResult`, in Rappen/bps).
- **`TaxJurisdiction`** — der Beratungs-/API-nahe Vertrag mit `estimate_income_tax`,
  `estimate_wealth_tax`, `estimate_capital_gains` und `estimate` samt `metadata`.

**Registry & Discovery.** Regimes registrieren sich per Decorator
`@register_regime(id_pattern)` (exakte IDs, Globs wie `CH-*`, Catch-all `*`);
`resolve_regime_class` löst nach Spezifität auf und fällt zuletzt auf ein
generisches Flatrate-Regime zurück. Jurisdiktionen werden per
`register_jurisdiction` nach ISO-Ländercode registriert. Neben dem
Built-in-Discovery (`discover_builtin_jurisdictions`, Import per `pkgutil`) gibt
es ein **externes Entry-Point-Discovery** (Gruppe `5eyes.tax_regime`), das
fehlerhafte Plugins abfängt, ohne den Start zu gefährden.

**Aktuell implementiert.** Regimes: `CHTaxRegime` (registriert für `CH`/`CH-*`,
inkl. 26-Kantone-Vermögenssteuertabelle, private Kapitalgewinne steuerfrei),
`DETaxRegime` (Abgeltungsteuer) und das generische `GenericFlatRateRegime`
(Catch-all). Jurisdiktion (Beratungs-Layer): `SwissTaxJurisdiction`. Die
After-Tax-Berechnung (`after_tax.py`) bestimmt aktuell den Steuer-Drag auf
realisierte Kapitalgewinne und leitet die Nach-Steuer-Rendite als
`gross − tax_drag` ab (Rendite-Zerlegung für Zins/Dividende ist bewusst
zurückgestellt).

**Robustheit.** Mandatsspezifische Overrides (`overrides.py`) werden
copy-on-write und JSON-fehlerresistent auf ein Regime angewandt; ein
**Konformitäts-Vertrag** (`conformance.py`, Version 1.0.0) prüft jede
Regime-Implementierung gegen zehn Anforderungen (u. a. ISO-3166-Ländercode,
ISO-4217-Währung, nicht-negative Vermögenssteuer, Immutabilität der Overrides).

**Code-Referenz:**
`services/tax/base.py : TaxRegime`, `TaxJurisdiction`, `TaxContext`, `TaxResult`;
`services/tax/registry.py : register_regime`, `resolve_regime_class`,
`register_jurisdiction`, `discover_builtin_jurisdictions`;
`services/tax/discovery.py : discover_external_regimes`;
`services/tax/regimes/ch.py : CHTaxRegime`, `regimes/de.py : DETaxRegime`,
`regimes/generic.py : GenericFlatRateRegime`;
`services/tax/jurisdictions/ch.py : SwissTaxJurisdiction`;
`services/tax/after_tax.py : get_after_tax_return`;
`services/tax/overrides.py`, `services/tax/conformance.py : ConformanceContract`.

---

## 9. FIDLEG-Compliance

Die Engine ist entlang der zentralen Pflichten des Finanzdienstleistungsgesetzes
(FIDLEG) gebaut. Die entsprechenden Gesetzesartikel sind im Code als Belegstellen
hinterlegt.

**Eignungsprüfung (Art. 10 / 12).** Der Suitability-Audit prüft **mandatsbezogen**,
ob für ein Mandat eine Eignungsprüfung erforderlich ist (Execution-only-Mandate
sind nach Art. 13 ausgenommen). Grundlage ist das **aktuelle Risikoprofil**: Der
Audit lädt die als „current" markierte `RiskAssessment` (die 5eyes-seitige
Eignungsprüfung nach Art. 12: finanzielle Verhältnisse, Anlageziel/Horizont,
Risikofähigkeit/-bereitschaft). Die **regelmässige Aktualisierung** wird über eine
Frische-Prüfung sichergestellt (`SUITABILITY_FRESHNESS_MAX_DAYS = 365`, 12 Monate
als Industriestandard); veraltete oder fehlende Profile werden als nicht-konform
markiert. Der Audit ist **fail-closed**: Kann das Profil nicht sicher bewertet
werden, wird der Zustand als „degraded" (Ergebnis unbestimmt) geführt statt
fälschlich als konform. Die **Kunden-Signatur des Risikoprofils**
(`risk_assessment_signed_at`, `_signed_method`: `portal` oder `advisor_recorded`)
wird als Dokumentation erfasst.

**Kostenausweis ex-ante (Art. 8/9).** Der ex-ante-Kostenausweis
(`cost_disclosure.py`, Basis „Art. 8/9 FIDLEG; Art. 8/14 FIDLEV") weist einmalige,
laufende und Erstjahres-Gesamtkosten in CHF und äquivalenten Basispunkten aus:
Dienstleistungskosten (Beratungs-/Verwaltungs-, Depot-, Plattformgebühren),
einmalige Einrichtungskosten, gewichtete Produktkosten (TER, mit
Abdeckungsgrad-Verfolgung) und Transaktionskosten der Erstumsetzung
(konservative Ex-ante-Annahme, Default 15 bps). Grundsatz: **Unbekannte Kosten
werden nie stillschweigend als null behandelt** — fehlende Gebühren/TER erzeugen
explizite Warnungen und der Ausweis gilt nur bei vollständiger TER-Abdeckung als
„complete".

**Beratungsprotokoll & Integrität (Art. 16/17).** Beratungen werden als
versioniertes Beratungsprotokoll (`AdvisoryLog`) festgehalten — mit u. a.
Teilnehmern, Themen, gegebenen Risikohinweisen, Kostenoffenlegungs-Flag,
Empfehlungs-/Eignungsbezug und Kundensignatur. Aktualisierungen erfolgen
**nicht-destruktiv per Versionierung** (neuer Datensatz, `supersedes_id`), nie
durch Überschreiben. Jeder Eintrag trägt einen **SHA-256-Integritäts-Hash** über
eine feste Feldreihenfolge („Hash-Vertrag"); die Verifikation erfolgt
zeitkonstant (Schutz gegen Timing-Angriffe). Die Aufbewahrung ist auf **10 Jahre**
angelegt (`RETENTION_YEARS = 10`, Bezug Art. 17). Ergänzend erkennt
`detect_suitability_mismatches` Abweichungen der Zielallokation vom Risikobudget,
die als Risikohinweis ins nächste Protokoll einfliessen.

**Code-Referenz:**
`services/suitability_audit.py : audit_mandate_suitability`,
`_mandate_requires_suitability`, `_current_risk_assessment`,
`evaluate_suitability_freshness`;
`services/cost_disclosure.py : build_cost_disclosure`, `calculate_cost_disclosure`;
`services/advisory_log_service.py : create_advisory_log`,
`supersede_advisory_log`, `detect_suitability_mismatches`,
`build_auto_log_payload`;
`services/advisory_log_integrity.py : compute_integrity_hash`,
`verify_integrity_hash`, `compute_retain_until`.

---

## 10. Anlagephilosophie: Kein Markt-Timing, Rebalancing nur via Eignungsprüfung

Die 5eyes-Beratung folgt einer regelbasierten, langfristigen Philosophie und
setzt diese technisch durch (ADR-003, Status *Accepted*):

- **Keine Auto-Trigger:** Es existiert kein Cron-Job, Watcher oder
  Notification-Endpoint, der bei Marktbewegungen ein Kauf-/Verkaufssignal auslöst.
- **Rebalancing nur bei Eignungsprüfung:** SAA-Drift wird ausschliesslich im
  Eignungsprüfungs-Workflow oder auf expliziten Kundenwunsch gezeigt — keine
  Reaktion auf Tagesbewegungen.
- **Keine „Markt-Chance"-Sprache:** Begriffe wie „jetzt einsteigen",
  „garantiert" oder „Markt-Chance" sind in Code, PDF und UI untersagt und werden
  durch Drift-Tests geprüft.
- **Marktdaten nur als Bewertungs-Input:** Preise dienen der Portfolio-Bewertung
  und CMA-Pflege — niemals als Handelsauslöser.

Diese Doktrin ist regulatorisch bewusst gewählt: Automatische Signale könnten als
implizite Anlageempfehlung gelten (FIDLEG-relevant). Der Berater bleibt
entscheidend; die Software unterstützt, entscheidet aber nicht.

**Code-Referenz:** `docs/adr/ADR-003-anlagephilosophie-no-market-timing.md`;
Konsistenz getestet in `tests/test_adr_consistency.py`.

---

*Dieses Whitepaper beschreibt die zum Stand 2026-07-19 im Code implementierte
Methodik. Es enthält keine Marketingaussagen und keine Nennung von Drittmarken.*
