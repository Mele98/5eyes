# ADR-014: Engine-God-Modul `portfolio_engine.py` — Split-Plan

- **Status:** Accepted, Implementation: **Complete** (alle 8 Schritte
  umgesetzt, 2026-08-03)
- **Datum:** 2026-08-02 (Plan) / 2026-08-03 (Umsetzung abgeschlossen)
- **Sprint:** Welle 3.2 (Umsetzungsplan-Verbesserungen §3.2, siehe
  `docs/planning/2026-07-18-umsetzungsplan-verbesserungen.md`)

## Umsetzungs-Ergebnis (2026-08-03)

Alle 8 Schritte in der geplanten Reihenfolge umgesetzt, jeder Schritt
einzeln committet und gepusht (`git log`-Suchbegriff
`refactor(engine): ADR-014 Schritt`), jeder Schritt einzeln durch
`test_golden_snapshot_ch_regression.py` (byte-identisch) + alle
Test-Dateien, die `services.portfolio_engine` importieren + volle
Backend-Suite + Security-Gate verhaltens-bewiesen:

| # | Cluster | Ziel-Datei | Status |
|---|---|---|---|
| 1 | Gesamtvermoegen | `portfolio_engine_gesamtvermoegen.py` | ✅ |
| 2 | Live-Rebalancing | `portfolio_engine_live_rebalancing.py` | ✅ |
| 3 | CMA-Verarbeitung | `portfolio_engine_cma.py` | ✅ |
| 4 | Reserve | `portfolio_engine_reserve.py` | ✅ |
| 5 | MC-Simulation | `portfolio_engine_mc_simulation.py` | ✅ |
| 6 | Optimizer-Integration | `portfolio_engine_optimizer_integration.py` | ✅ |
| 7 | Payload-Bau Phase B | `portfolio_engine_payload.py` | ✅ |
| 8 | House-Matrix/Tilt | `portfolio_engine_house_matrix.py` | ✅ |

**`portfolio_engine.py`: 8'820 → ~3'671 Zeilen** (CORE-Helfer + die 5
Orchestratoren `generate_target_allocation`, `evaluate_goal_sensitivity`,
`build_target_payload_from_allocation`, `build_recommendation_payload_
from_run`, `generate_recommendation_run` — exakt wie im Plan vorgesehen).

**Methodik-Korrektur waehrend der Umsetzung:** die ersten Extraktionen
(Schritte 1-4) nutzten manuelle Zeilennummer-Grenzen. Schritt 5 (MC-
Simulation) deckte auf, dass eine Kontiguitaets-ANNAHME zwischen zwei
Zielfunktionen falsch war (2 unbeteiligte Funktionen sassen dazwischen und
wurden versehentlich mitgeloescht) — sofort vom Golden-Snapshot-Test
gefangen (`NameError`), zurueckgesetzt, mit vollstaendigem `def`-Scan
korrekt neu gemacht. Schritt 7 (Payload-Bau Phase B) deckte einen
zweiten, subtileren Fehlermodus auf: ein Kontiguitaets-Scan, der nur
`def`-Zeilen prueft, uebersieht Import-Re-Export-Bloecke aus fruehen
Schritten, die mitten im geplanten Loeschbereich stehen koennen — ebenfalls
vom Golden-Snapshot-Test gefangen. Ab Schritt 7 wurde auf eine **AST-
basierte Funktions-Span-Extraktion** (Python's `ast`-Modul liefert exakte
Zeilenspannen pro Funktion, unabhaengig davon, was dazwischen steht)
umgestellt — Schritt 8 (der am staerksten verflochtene, riskanteste
Cluster) lief damit beim ersten Versuch fehlerfrei durch.

**Externe Konsumenten ueber das urspruengliche ADR hinaus gefunden**
(alle bereits vor der jeweiligen Extraktion per Lazy-Import/Re-Export
transparent gehalten, keine Aenderung an den Konsumenten noetig):
`routers/clients.py` (Gesamtvermoegen-Cluster), `routers/wealth.py`
(CMA- UND House-Matrix-Cluster, `calculate_max_pension_spending`),
`services/optimizer/scenario_engine.py` (CMA-Cluster).

**Text-Scan-Test-Nachziehungen** (Tests, die `portfolio_engine.py` als
Roh-Text lesen statt zu importieren, brechen bei Code-Umzug auch ohne
Verhaltensaenderung — jeweils auf Scan ueber alle `portfolio_engine*.py`-
Submodule per Glob umgestellt, analog zueinander):
`test_liquidity_zero_engine_lock.py` (Schritt 5),
`test_tax_solver_wiring.py` (Schritt 6),
`test_frontend_goal_soll_ist.py` (Schritt 7). 5 weitere verdaechtigte
Testdateien (`test_bb_risky_fractions_audit.py`,
`test_house_matrix_risk_budget_consistency.py`,
`test_house_matrix_yaml_loader.py`, `test_liquidity_cascade_warning.py`,
`test_liquidity_hard_cap_in_fallback.py`) wurden vor Schritt 8 verifiziert
und stellten sich als falsch-positiv heraus (ihre geprueften Muster liegen
in CORE-Referenzdaten-Bootstrap oder im Haupt-Orchestrator, beide bleiben
in `portfolio_engine.py`).

**Ein Monkeypatch-Test-Fund** (Schritt 5):
`test_portfolio_engine_regressions.py` patchte
`services.portfolio_engine._monte_carlo_simulations`, aber
`_run_allocation_monte_carlo` ruft diesen Namen nach der Extraktion als
modul-lokalen Namen in `portfolio_engine_mc_simulation` auf — das
Monkeypatch auf dem Re-Export-Modul alleine wirkt sich nicht auf den
tatsaechlichen Aufruf aus (getrennte Modul-Namespaces). Fix: beide Module
patchen.

**Korrektur (Mega-Audit 2026-08-04, verifiziert per grep):** dieses ADR
behauptet unten (Reserve-Abschnitt, Zeile ~217/237/291/431) sowie in der
Tabelle "Reserve haenge von 5 Goal-Metadaten-Helfern ab" (`_goal_projection_
years`, `_annualize_goal_amount`, `_goal_hardness_key`,
`_goal_probability_factor`, `_goal_pension_state_funded`). Das ist nur fuer
2 der 5 Namen zutreffend (`_goal_projection_years`, `_annualize_goal_amount`).
`_goal_hardness_key` ist KEINE Reserve-Abhaengigkeit -- siehe die
ausfuehrliche Herleitung im Modul-Docstring von
`services/portfolio_engine_reserve.py`, die diese Diskrepanz beim
tatsaechlichen Extrahieren (Schritt 4) aufgedeckt und korrekt umgesetzt hat.
Der Plan unten bleibt als historischer Stand unveraendert; die Umsetzung
folgte der hier verlinkten, verifizierten Korrektur, nicht dem urspruenglichen
Plantext.

## Kontext

`5eyes-backend/services/portfolio_engine.py` ist **8'820 Zeilen** gross und
enthaelt praktisch die gesamte Beratungs-Engine: Kapitalmarktannahmen-
Verarbeitung, Monte-Carlo-Simulation, House-Matrix/Tilt-Logik, Reserve-
Berechnung, Gesamtvermoegens-Darstellung, Payload-Bau fuer Ziel-/
Empfehlungs-Antworten, Produktselektion und die Stochastic-Optimizer-
Integration — alles in einer Datei, mit **~230 Top-Level-Funktionen/Klassen**.

Das ist das gleiche God-Modul-Muster wie beim HTML-Frontend-Monolithen
(ADR-008), nur auf der Backend-Seite: jede Aenderung an einer Facette der
Engine (z.B. Reserve-Formel) erfordert Navigation durch eine Datei, die
gleichzeitig CMA-Mathematik, Solver-Aufrufe und Produkt-Scoring enthaelt.
Zwei Unterschiede zu ADR-008 sind wichtig fuer die Strategie hier:

1. **Kein bestehender Plan.** Fuer den HTML-Monolithen gab es bereits
   ADR-008 + einen Modul-Split-Plan (`2026-06-02-sprint-u-35-modul-split-
   plan.md`). Fuer die Engine existierte laut Umsetzungsplan **kein Plan**
   — dieser ADR ist die nachgeholte Vorarbeit.
2. **Sehr hohe faktische Verflechtung.** Anders als beim Frontend (das sich
   entlang UI-Sektionen trennen laesst) ruft die Engine ihre eigenen
   „privaten" (unterstrich-prefixten) Helfer nicht nur intern auf, sondern
   mehrere Nicht-Test-Module importieren sie **direkt**:

   ```
   services/backtest_ab.py:      _baseline_target_bands, _expected_metrics,
                                  _house_matrix_or_default, _risk_score_bucket,
                                  require_strategy_ready_assessment
   services/review_engine.py:    build_target_payload_from_allocation,
                                  ensure_runtime_reference_data
   services/advisory_report.py:  _allocation_snapshot_preferences,
                                  _compute_reserve_for_inputs, _inflation_path_series,
                                  _normalize_preferences, _simulation_horizon_years,
                                  _wealth_inflow_series_rappen, _SAA_LIQUIDITY_HARD_CAP_BPS
   services/foundation_example.py: build_recommendation_payload_from_run,
                                  build_target_payload_from_allocation,
                                  ensure_runtime_reference_data,
                                  generate_recommendation_run, generate_target_allocation
   ```

   Das heisst: die „privaten" Helfer sind faktisch **Teil der oeffentlichen
   API** von `services.portfolio_engine`. Jede Extraktion MUSS diese
   Namen unter `services.portfolio_engine` importierbar halten — sonst
   brechen vier produktive Module ausserhalb der Testsuite.

## Ist-Zustand — Funktions-/Klassen-Inventar

Verifiziert durch vollstaendiges Lesen von `services/portfolio_engine.py`
(8'820 Zeilen) plus `grep` auf alle `^def `/`^class `/`@dataclass`-Zeilen
und auf Call-Sites/Import-Sites der wichtigsten Namen. **Keine der
folgenden Zahlen ist geschaetzt** — Zeilenbereiche stammen aus dem
tatsaechlichen Datei-Inhalt.

Die Datei gliedert sich faktisch in **8 Cluster**: die vom Umsetzungsplan
genannten 6 Kandidaten-Schnitte (MC-Simulation, House-Matrix/Tilt,
CMA-Verarbeitung, Reserve, Gesamtvermoegen, Payload-Bau) plus **2 weitere,
im Plan nicht genannte Cluster**, die beim Lesen sichtbar wurden
(Optimizer-Integration, Kern-Helfer/Orchestratoren). Das wird unten explizit
als Abweichung vom Plan ausgewiesen, statt die Zahl 6 künstlich zu erzwingen.

### 1. CORE — Kern-Helfer, Risikoprofil-Gate, Referenzdaten-Seed (bleibt in `portfolio_engine.py`)

| Funktion/Klasse | Zeilen | Beschreibung |
|---|---|---|
| `PortfolioSummary` (dataclass) | 273-277 | Bucket-Betraege + Total (rappen) |
| `StoredReferencePrice` (dataclass) | 279-284 | Referenzpreis-Snapshot fuer Rebalancing |
| `_now`, `_today` | 287-293 | ISO-Zeitstempel-Helfer |
| `_parse_bps_percent`, `_parse_rappen` | 295-317 | Berater-Eingabe-Parsing (%, CHF) |
| `_norm_text` | 319-329 | Deutsch-ASCII-Normalisierung (Umlaute) — **38 Referenzen im File** |
| `_risk_json_field_is_type` … `require_strategy_ready_assessment` | 358-489 | Risikoprofil-Readiness-Gate (Schema-Marker, Fragebogen-Antworten-Matching, Override-Dokumentation). Eigener kohaerenter Cluster, aber nicht einer der 6 benannten — bleibt CORE. `require_strategy_ready_assessment` extern importiert (`backtest_ab.py`). |
| `_normalize_preferences` | 492-503 | Preferences-Dict normalisieren — **extern importiert** (`advisory_report.py`) |
| `_allocation_snapshot_preferences` | 506-517 | Persistierte Preferences aus Allocation lesen — **extern importiert** |
| `_merge_mandate_defaults_into_prefs` | 519-551 | Mandats-Default-Building-Blocks in Preferences mergen |
| `_bucket_key`, `_coerce_band_bps` | 554-603 | Label→Bucket-Key, Berater-Bandbreiten-Parsing |
| `_risk_score_bucket` | 606-621 | Score→Bucket(1-10) — **extern importiert** |
| `_default_weights_for_position`, `_convert_position_amount_to_target_currency`, `_summarize_positions`, `_bps`, `_amount_from_weight_bps` | 624-708 | Positions→Bucket-Betraege, FX-Konvertierung, bps-Rechnung — **generischste Helfer im File, 13-58 Call-Sites je Funktion** |
| `_current_recommendation_run` | 711-720 | Aktuellster Run fuer Mandat |
| `_resolve_jurisdiction_context` | 1594-1631 | CH-vs-Nicht-CH-Kontext (Waehrung/Heimmarkt-Label) fuer Produktfilter — von HM- UND Payload-Cluster genutzt, daher CORE |
| `_validate_default_products`, `ensure_runtime_reference_data`, `_ensure_runtime_reference_data_ch`, `ensure_default_products` | 4504-4813 | Referenzdaten-Bootstrap (Policy/House-Matrix/BuildingBlocks/CMA/Fondskatalog-Seed) — **`ensure_runtime_reference_data` extern importiert** (`review_engine.py`, `foundation_example.py`) |
| `_load_allocation_inputs` | 4874-5031 | Laedt Positionen/Cashflows/Goals/Inflows, FX-konvertiert — Orchestrator-naher Glue, bleibt CORE |
| `_current_planning_inflation_bps` | 5068-5081 | PlanningAssumption-Lookup |
| `_investable_advisory_wealth_rappen` | 5478-5479 | `advisory_wealth - external_reserve`, 1 Zeile Substanz |
| `_compute_input_snapshot_hash`, `_strategy_drift_warnings`, `_target_allocation_reserve_warnings`, `_target_allocation_context_warnings`, `_assert_allocation_has_basis` | 6364-6635 | Audit-Anker/Drift-Warnungen fuer TargetAllocation-Wiederaufbau |

**Ca. 900 Zeilen**, ueber das File verteilt (nicht zusammenhaengend). Bleibt
in `portfolio_engine.py` — diese Helfer sind die Basis, von der ALLE
anderen Cluster lesen (Definition liegt frueh im File, siehe
Migrations-Pattern unten fuer die Import-Reihenfolge-Konsequenz).

### 2. Gesamtvermoegen (Kandidat 1 im Plan)

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `_build_total_wealth_allocation` | 2380-2455 | IST/SOLL auf Gesamtvermoegen, Immobilie als Fundament (netto Hypothek) — Produkt-Entscheid 2026-07-13 |
| `_goal_uses_total_scope` | 2949-2952 | Goal-Scope='Gesamtvermoegen'-Flag |
| `_external_assets_inflation_value` | 2955-2972 | Externe Assets nur mit Teuerung hochrechnen (real 0%) |
| `_wealth_inflow_series_rappen` | 4816-4871 | WealthInflow→Year-Series — **extern importiert** (`advisory_report.py`) |

**Ca. 160 Zeilen.** Kleinster Cluster, 1 Haupt-Pure-Function mit 3
Call-Sites, keine Rueckwaerts-Abhaengigkeit auf andere Cluster.

### 3. CMA-Verarbeitung (Kandidat 2 im Plan)

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `_bare_market_token`, `_resolve_home_equity_label` | 1563-1591 | Home-Bias-Label-Parsing fuer Nicht-CH-Jurisdiktionen |
| `_cholesky`, `_is_valid_cholesky`, `_identity_cholesky` | 1634-1658 | Cholesky-Zerlegung + Fallback-Kette fuer MC-Korrelation |
| `_cornish_fisher_transform` | 1661-1691 | Skew/Kurtosis-Transform fuer Tail-Risk-Sampling |
| `_crisis_stress_matrix`, `_build_cholesky_from_cma` | 1694-1765 | Crisis-Korrelation + CMA→Cholesky-Matrix |
| `_sub_asset_class_assumption_map`, `_sub_asset_class_metrics` | 1768-1808 | Sub-Asset-Class-CMA-Overrides mit Default-Fallback |
| `_apply_cma_market_adjustments` | 1811-1852 | Nelson-Siegel/KGV/Risikopraemien-Adjustments (lazy Import aus `services.optimizer.scenario_engine`) |
| `_asset_class_expected_metrics` | 1855-1918 | CH- vs Nicht-CH-CMA-Spalten (jurisdiktionsbewusst, WP2) |
| `_weighted_bucket_metrics` | 1921-1994 | Sub-Allocation-gewichtete Bucket-Metriken — **7 interne Call-Sites** |
| `_bucket_expected_metrics` | 1997-2002 | Compat-Alias fuer `_weighted_bucket_metrics` |
| `_portfolio_volatility_bps`, `_portfolio_weighted_ter_bps` | 2005-2047 | Portfolio-Vola via `w'Σw`, TER-Drag |
| `_expected_metrics` | 2050-2084 | Aggregiert Return/Vol/Sharpe/Sortino — **extern importiert** (`backtest_ab.py`), **8 interne Call-Sites** |
| `_inflation_path_series` | 2236-2256 | CMA-Inflationspfad-Lookup — **extern importiert** (`advisory_report.py`) |
| `_real_series_from_nominal` | 2259-2270 | Realwert-Serie aus Nominal + Inflation |
| `_goal_inflation_series_bps` | 2759-2768 | Wrapper um `_inflation_path_series` fuer Goal-Kontext |

**Ca. 525 Zeilen.** Reine Ein-Richtungs-Abhaengigkeit: MC-Simulation und
House-Matrix/Tilt lesen von hier, CMA-Verarbeitung liest von nichts anderem
(nur BUCKET_FIELDS/settings/Modelle).

### 4. Reserve (Kandidat 3 im Plan)

| Funktion/Konstante | Zeilen | Beschreibung |
|---|---|---|
| `_reserve_decay_mode_smooth`, `_reserve_decay_factor`, `_reserve_bucket_mode_time_bucket`, `_time_bucket_reserve_factor`, `_time_bucket_label` | 91-177 | Zwei alternative Decay-Modelle (smooth-exp vs. Time-Bucket), Feature-Flag-gesteuert |
| `_goal_probability_factor`, `_goal_is_conditional` | 184-196 | Bedingte-Goals-Gewichtung (Sprint B6) — **cross-cluster**: auch von MC + Payload-Bau genutzt |
| `_goal_pension_pillar`, `_goal_pension_state_funded` | 208-222 | AHV/Vorsorge-Saeulen-Erkennung — **cross-cluster** |
| `_goal_reserve_for_goal` | 2872-2915 | Zielbezogene Reserve pro Goal (nutzt Decay/Time-Bucket-Flags) |
| `_compute_reserve_for_inputs` | 5109-5297 | **Single Source of Truth** fuer Reserve-Berechnung — **extern importiert** (`advisory_report.py`), 4 interne Call-Sites |
| `_compute_reserve_requirements` | 6509-6529 | Compat-Wrapper — laut Code-Kommentar **direkt von `tests/test_portfolio_engine_regressions.py` importiert** |

**Ca. 395 Zeilen.** Wichtiger Fund: Reserve haengt inhaltlich von 5
Goal-Metadaten-Helfern ab (`_goal_projection_years`, `_annualize_goal_amount`,
`_goal_hardness_key`, `_goal_probability_factor`, `_goal_pension_state_funded`
— je 5-6 Referenzen im File verifiziert per `grep`), die **physisch im
Payload-Bau-Abschnitt** (Zeilen 2651-2850) stehen und AUCH von
MC-Simulation (`_monte_carlo_goal_summary`) genutzt werden. Das ist echte,
gemessene Drei-Wege-Verflechtung (Reserve ↔ Payload-Bau ↔ MC-Simulation),
keine Vermutung — siehe Migrations-Pattern fuer die Konsequenz.

### 5. MC-Simulation (Kandidat 4 im Plan — groesster Cluster)

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `_simulation_horizon_years` | 2087-2108 | Horizont aus Prefs/Goals/Lebenserwartung — **extern importiert** (`advisory_report.py`) |
| `_simulation_stress_multiplier`, `_simulation_transaction_cost_bps`, `_simulation_rebalance_mode`, `_simulation_crisis_strength`, `_simulation_use_tail_risk` | 2111-2178 | Simulation-Preferences-Parsing |
| `_target_bucket_values`, `_weights_from_bucket_values`, `_apply_cashflow_to_bucket_values`, `_rebalance_bucket_values_to_targets` | 2180-2233 | Bucket-Werte↔Gewichte, Cashflow-Anwendung, Rebalancing-Turnover |
| `_simulate_bucket_path` | 2273-2348 | Ito-korrigierte geometrische Pfadsimulation (deterministisch UND als MC-Bausatz) |
| `_build_simulation_payload` | 2494-2641 | Deterministische IST/SOLL/Downside/Upside-Pfade + Total-Vermoegen-Pfade |
| `_monte_carlo_simulations`, `_monte_carlo_seed` | 3116-3128 | N-Simulationen-Parsing, deterministischer Seed |
| `_percentile`, `_annualized_return_bps`, `_twr_annualized_bps`, `_return_bps`, `_loss_bps`, `_stddev_bps`, `_conditional_percentile_average`, `_max_drawdown_bps` | 3131-3214 | Statistik-Primitiven (Quantil, CAGR, TWR, Drawdown) |
| `_year_index_for_goal`, `_full_goal_duration_years`, `_goal_duration_years` | 3217-3241 | Goal-Zeitfenster-Mapping auf MC-Jahres-Achse |
| `_monte_carlo_goal_summary` | 3244-3457 | Pro-Goal-MC-Auswertung (P10/P25/P50/P90, Score) — **nutzt die 5 Goal-Metadaten-Helfer aus Reserve/Payload-Bau** |
| `_sequence_of_returns_depletion` | 3460-3475 | Verzehr-/Sequence-of-Returns-Kennzahl (#96) |
| `_run_allocation_monte_carlo` | 3478-3869 | **Kern-MC-Loop, ~390 Zeilen** — Cholesky-korrelierte Pfade, Cornish-Fisher, Total-Vermoegen-Pfade, VaR/CVaR/Drawdown/Depletion |

**Ca. 1'170 Zeilen** — der groesste einzelne Cluster (bestaetigt: Plan nennt
MC-Simulation zuerst, vermutlich weil er am groessten ist).

### 6. House-Matrix/Tilt (Kandidat 5 im Plan — am staerksten verflochten)

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `_building_block_risky_map`, `_building_block_rows_for_policy` | 1259-1317 | BuildingBlock-Zeilen laden (jurisdiktionsbewusst, WP-A 2026-08-01) — **6 interne Call-Sites** |
| `_asset_risky_weight_fallbacks`, `_apply_band_preferences`, `_has_manual_target_overrides`, `_rebalance_to_total` | 1320-1409 | Bandbreiten-Preferences anwenden, auf 10'000 bps normalisieren |
| `_enrich_sub_allocations_with_risk`, `_risk_budget_from_targets`, `_enforce_risk_budget` | 1412-1495 | Risky-Fraction pro Sub-Allocation, Budget-Enforcement-Loop (Donor/Receiver-Cascade) — **5 interne Call-Sites** |
| `_growth_goals_for_equity_tilt` | 2789-2811 | Growth-Goals-Filter fuer opportunistischen Equity-Tilt |
| `_normalize_splits`, `_preference_choice` | 3911-3944 | Sub-Class-Split-Normalisierung, UI-Wert-Normalisierung |
| `_build_sub_allocations` | 3947-4231 | **~285 Zeilen** — Home-Bias-Splits (CH hartcodiert / Nicht-CH via `resolve_home_bias_defaults`), Theme-Tilts, EM/HY-Filter |
| `_apply_illiquid_cap` | 4241-4309 | Private-Equity-Deckel (3eyes: nur PE ist "illiquid", nicht ganz Alternative) |
| `_house_matrix_or_default`, `_validate_house_matrix_defaults`, `_normalize_house_matrix_defaults`, `_seed_house_matrix_rows`, `_seed_building_blocks` | 4312-4502 | House-Matrix-Lookup + Default-Seed-Validierung — **`_house_matrix_or_default` extern importiert** |
| `_baseline_target_bands`, `_house_matrix_mid_targets` | 5034-5066 | Targets/Min/Max aus House-Matrix-Zeile — **`_baseline_target_bands` extern importiert** |
| `_apply_external_exposure_tilts` | 5084-5106 | Gesamtvermoegen-Exposure tiltet Beratungs-Targets |
| `_renditeziel_equity_tilt_bps`, `_apply_goal_and_reserve_tilts` | 5300-5475 | Renditeziel-Tilt + **ruft `_compute_reserve_for_inputs` aus dem Reserve-Cluster auf** — die zentrale Cross-Bucket-Bruecke Reserve→House-Matrix |

**Ca. 1'110 Zeilen.** Nachweislich am staerksten verflochten:
1. ruft in `_apply_goal_and_reserve_tilts` direkt in den Reserve-Cluster,
2. wird in `generate_target_allocation` in einer **3-stufigen
   Eskalations-Kaskade** (Risk-Budget-Exceeded-Fallback) bis zu **dreimal**
   mit unterschiedlichen Zwischen-Zustaenden aufgerufen
   (`_build_sub_allocations`/`_apply_illiquid_cap`/
   `_enrich_sub_allocations_with_risk` je 4-8×),
3. zwei Funktionen sind extern importiert.

### 7. Payload-Bau (Kandidat 6 im Plan — zweitgroesster Cluster, 2 Phasen)

**Phase A — Live-Rebalancing (self-contained, niedrig verflochten):**

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `_reference_price_snapshot_for_run`, `_stored_reference_price_for_position`, `_holdings_snapshot_for_run`, `_latest_holdings_by_product_for_mandate`, `_units_milli_from_amount`, `_value_from_units_milli` | 723-827 | Referenzpreis-/Holdings-Snapshots laden |
| `_canonical_asset_class_label`, `_rebalancing_action`, `_rebalancing_action_meta`, `_aligned_reference_price` | 830-877 | Bucket-Label-Mapping, Buy/Sell/Hold-Klassifikation, Referenzpreis-Rekalibrierung |
| `_load_live_rebalancing_sources`, `_build_live_rebalancing_entry` | 880-1029 | Pro-Position Live-Bewertung (Holdings vs. implizit aus Zielbetrag) |
| `_build_live_bucket_targets`, `_build_live_bucket_drifts`, `_build_live_position_drifts`, `_build_live_action_summary` | 1032-1151 | Bucket-/Positions-Drift, Handlungsempfehlungs-Text |
| `build_live_rebalancing_payload` | 1153-1256 | Oeffentlicher Einstiegspunkt (3 interne Call-Sites, alle in Orchestratoren) |

**Ca. 535 Zeilen.** Haengt nur von CORE-Helfern + externen Services
(`price_updater`, `product_market_data`) ab — keine Abhaengigkeit auf
CMA/HM/Reserve/MC.

**Phase B — Goal-Analyse-Formatierung + Produktselektion (verflochten mit Reserve/MC):**

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `_build_asset_class_assumptions`, `_build_sub_asset_class_assumption_reference` | 2351-2491 | Anzeige-Payload fuer Asset-/Sub-Asset-Class-Annahmen |
| `_goal_hardness_key`, `_goal_weight`, `_build_mandate_score`, `_compute_goal_score` | 2651-2756 | Goal-Hardness-Gewichtung, Mandats-Score-Aggregation (weighted + weakest-hard) |
| `_inflate_real_goal_target_rappen`, `_goal_target_wealth_rappen`, `_goal_projection_years`, `_annualize_goal_amount`, `_goal_timing_label` | 2771-2869 | **Goal-Metadaten-Helfer — auch von Reserve + MC genutzt (siehe Reserve-Abschnitt)** |
| `_expected_death_year_offset_from_mandate` | 2918-2946 | BFS-Mortalitaets-Cutoff fuer Goal-Analyse |
| `_build_goal_analysis` | 2975-3113 | Deterministische Goal-Analyse (pro Goal: Status/Score/Projected-Value) |
| `_merge_goal_analysis_with_monte_carlo` | 3872-3908 | Merged MC-Goal-Summaries in die deterministische Goal-Analyse — liest MC-Output-Dict per Key, daher **erst NACH stabiler MC-Extraktion extrahieren** |
| `_build_bucket_response` | 6571-6605 | Bucket-Antwort-Payload (IST/SOLL/Band) |
| `_product_matches_constraints` … `_filter_products_by_universe` | 8168-8439 | Produktfilter (Suitability/ESG/Hedging/chf_only), Produkt-Scoring, TER-Aggregation, Konzentrationslimiten, Produktuniversum-Filter (Tenant+Jurisdiktion) |

**Ca. 775 Zeilen.**

**Payload-Bau gesamt: ca. 1'310 Zeilen.**

### 8. Optimizer-Integration — NICHT einer der 6 Plan-Kandidaten (Abweichungs-Fund)

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `_assessment_score_x10`, `_optimizer_status_is_converged`, `_build_tax_solver_kwargs` | 5495-5572 | Solver-Input-Vorbereitung (Score, Status-Klassifikation, Tax-Regime-Kwargs) |
| `_run_stochastic_optimizer_pass` | 5575-5726 | Solver in Stochastic-/Shadow-Modus aufrufen |
| `_optimizer_audit_fields`, `_driving_goal_id_from_achievability` | 5729-5768 | Audit-Anker-Extraktion, treibendes Goal ermitteln |
| `_weights_from_targets`, `_objective_to_milli`, `_allocation_comparison_note`, `_build_allocation_method_comparison` | 5780-5915 | House-Matrix-vs-Solver-Methodenvergleich |
| `_build_shadow_comparison_with_evaluations` | 5918-6018 | Apples-to-Apples-Objective-Vergleich (gleicher Seed, gleicher Context) |
| `_build_shadow_optimization_payload` | 6021-6108 | Persistierbarer Shadow-Snapshot fuer Admin/Compliance |
| `_build_optimizer_explainability` | 6114-6246 | Constraint-Slacks + Goal-Driver-Ranking |
| `_persist_optimizer_run` | 6253-6361 | OptimizerRun-DB-Persistenz |

**Ca. 868 Zeilen.** Fund: Der Umsetzungsplan (§3.2) nennt 6 Kandidaten-
Schnitte, aber die tatsaechliche Datei hat einen **siebten, ebenso grossen
und ebenso kohaerenten** Cluster, der bei der Planerstellung offenbar
uebersehen wurde. Strukturell relativ sauber (ueberwiegend Ein-Richtungs-
Abhaengigkeit: liest Targets/CMA/Goals, schreibt Shadow-/Audit-Payloads,
lazy-importiert `services.optimizer.*`). Wird in diesem ADR als
gleichwertiger 7. Kandidat mitgefuehrt statt ignoriert.

### 9. Orchestratoren — bleiben unveraendert in `portfolio_engine.py`

| Funktion | Zeilen | Beschreibung |
|---|---|---|
| `generate_target_allocation` | 6638-7309 | **Haupt-Einstiegspunkt** (~670 Zeilen) — ruft nacheinander in praktisch jeden der 7 Cluster oben |
| `evaluate_goal_sensitivity` | 7311-7508 | Sensitivitaets-Analyse (Solver 2× mit gepinntem Seed) |
| `build_target_payload_from_allocation` | 7511-7973 | „Rebuild"-Pfad (~460 Zeilen) — **extern importiert**, spiegelt `generate_target_allocation`s Cluster-Aufrufe fuer bestehende Allocations |
| `build_recommendation_payload_from_run` | 7976-8165 | Empfehlungs-Payload aus persistiertem Run — **extern importiert** |
| `generate_recommendation_run` | 8442-8819 | Produktselektion + Recommendation-Run-Persistenz (~380 Zeilen) |

**Ca. 1'900 Zeilen.** Diese 5 Funktionen sind explizit **keine
Extraktions-Kandidaten**: sie SIND die Orchestrierung — sie rufen
nacheinander in mehrere Cluster hinein und wuerden, verschoben in ein
eigenes Modul, lediglich das God-Modul-Problem an einen anderen Ort
verlagern. Sie bleiben als duenne Kleber-Schicht in `portfolio_engine.py`,
sobald die 7 Cluster darunter extrahiert sind.

### Summen-Kontrolle

CORE ~900 + Gesamtvermoegen ~160 + CMA ~525 + Reserve ~395 + MC ~1'170 +
House-Matrix/Tilt ~1'110 + Payload-Bau ~1'310 + Optimizer-Integration ~868 +
Orchestratoren ~1'900 ≈ 8'340 Zeilen (+ Docstrings/Imports/Konstanten-
Rauschen ≈ 8'820 Zeilen Ist-Stand). Grobe Schaetzung pro Cluster, aber
Reihenfolge-Groessenverhaeltnis (MC > Payload-Bau > Orchestratoren >
House-Matrix > Optimizer > CORE > CMA > Reserve > Gesamtvermoegen) ist aus
den tatsaechlichen Zeilenbereichen abgeleitet, nicht geschaetzt.

## Ist-Zustand — Absicherung (Tests)

Der Umsetzungsplan behauptet **„16 vorhandene Engine-Test-Dateien"**. Das
wurde verifiziert und ist **falsch / veraltet**:

```
grep -rl "from services\.portfolio_engine import\|import services\.portfolio_engine" tests/*.py | wc -l
→ 90
```

**Tatsaechliche Zahl: 90 Test-Dateien** importieren direkt aus
`services.portfolio_engine` (siehe vollstaendige Liste als Kommentar im
zugehoerigen PR-Diff / Task-Output — u.a. `test_portfolio_engine_regressions.py`,
alle `test_audit_z*`/`test_audit_b*`/`test_aa*`-Dateien, `test_sprint_b_batch1..5.py`,
`test_optimizer_*.py`, `test_engine_*.py`, `test_house_matrix_real_estate_cap.py`,
`test_reserve_explainability_section.py`, `test_total_wealth_allocation.py` etc.).
Der Plan-Text ist damit **um Faktor ~5.6 zu niedrig** — vermutlich eine
veraltete Zaehlung aus einer frueheren Projekt-Phase. Fuer diesen ADR gilt
die verifizierte Zahl (90), nicht die Plan-Annahme (16).

Zusaetzlich existiert **`tests/test_golden_snapshot_ch_regression.py`**
(WP-G, 2026-07-30) — das ist der **primaere Sicherheitsnetz-Test** fuer
genau dieses Vorhaben: er generiert fuer 6 Score/Praeferenz-Kombinationen
`generate_target_allocation` + `generate_recommendation_run` End-to-End und
vergleicht das Ergebnis (Targets, Bands, Risky-Fraction, Limiting-Factor,
Expected-Return/Vol, komplette Produktselektion/Sub-Allocations/Totals)
gegen eingefrorene JSON-Fixtures — **exakte Gleichheit**, kein Toleranz-
Fenster. Er wurde laut Docstring manuell verifiziert, dass er bei einer
Aenderung des CH-Default-Verhaltens tatsaechlich ROT wird (kein
Placebo-Test). Nicht-deterministische Felder (MC-Kennzahlen, deren Seed an
eine pro-Testlauf neue CMA-UUID haengt) sind bewusst und dokumentiert vom
Vergleich ausgeschlossen.

**Absicherung fuer diese Migration = alle 90 Test-Dateien unveraendert grün
+ `test_golden_snapshot_ch_regression.py` unveraendert grün, pro
Extraktionsschritt.** Das ist strenger als die im Plan angenommene
16-Datei-Basis, aber genau deshalb ein staerkerer Verhaltens-Beweis.

## Strategie

**Modul-fuer-Modul-Extraktion, kein Big-Bang** — analog zur
Two-Track-Migration in ADR-008, aber ohne Parallelbetrieb (die Engine hat
keine "zwei Stacks", nur eine Datei, die schrumpft).

### Kern-Prinzip: Import-Reihenfolge statt Circular-Import-Workaround

`portfolio_engine.py` definiert seine Konstanten (`BUCKET_FIELDS`,
`BUCKET_LABELS`, etc.) und generischen Helfer (`_norm_text`, `_bps`, ...)
**sehr frueh** im File (Zeilen 72-720). Die zu extrahierenden Cluster-
Funktionen stehen alle **spaeter** (ab Zeile 1259). Das erlaubt ein
einfaches, zirkular-import-sicheres Muster **ohne** ein zusaetzliches
`portfolio_engine_core.py`:

1. Extrahiertes Modul (z.B. `services/portfolio_engine_gesamtvermoegen.py`)
   importiert seine Abhaengigkeiten ganz normal per
   `from services.portfolio_engine import BUCKET_FIELDS, BUCKET_LABELS, PortfolioSummary`.
2. `portfolio_engine.py` fuegt **am Ende der Datei** (nach allen
   Konstanten-/Kern-Helfer-Definitionen, aber vor den Orchestratoren, die
   die verschobenen Namen aufrufen) einen Re-Export ein:
   `from services.portfolio_engine_gesamtvermoegen import _build_total_wealth_allocation, _goal_uses_total_scope, ...  # noqa: F401`
3. Solange die Konstanten/Kern-Helfer, von denen das neue Modul liest,
   **vor** dieser Re-Export-Zeile in `portfolio_engine.py` stehen (sie tun
   es bereits — das ist der aktuelle Ist-Zustand), gibt es keinen
   Import-Zyklus: Beim ersten Import von `portfolio_engine` ist
   `BUCKET_FIELDS` etc. bereits gebunden, wenn Python zur Re-Export-Zeile
   kommt und das neue Modul laedt.

Das ist explizit **keine** Erfindung eines neuen synthetischen Layers —
es nutzt aus, dass die Datei bereits so aufgebaut ist (Konstanten zuerst,
Cluster-Logik spaeter, Orchestratoren zuletzt).

### Reihenfolge (am wenigsten verflochtene Bloecke zuerst)

Begruendung siehe Inventar oben (Call-Site-Zaehlung + externe
Import-Zaehlung per `grep`, keine Vermutung):

| # | Cluster | Ziel-Datei | Zeilen (ca.) | Verflechtungs-Risiko | Warum diese Position |
|---|---|---|---|---|---|
| 1 | Gesamtvermoegen | `services/portfolio_engine_gesamtvermoegen.py` | ~160 | **Niedrig** | 1 Pure-Function, 3 Call-Sites, keine Abhaengigkeit auf andere Cluster |
| 2 | Payload-Bau Phase A (Live-Rebalancing) | `services/portfolio_engine_live_rebalancing.py` | ~535 | **Niedrig** | Self-contained; haengt nur von CORE + externen Preis-Services ab |
| 3 | CMA-Verarbeitung | `services/portfolio_engine_cma.py` | ~525 | **Mittel** | Reine Ein-Richtungs-Abhaengigkeit (MC + House-Matrix lesen von hier, nie umgekehrt); Risiko kommt allein von 2 extern importierten Namen (`_expected_metrics`, `_inflation_path_series`) |
| 4 | Reserve | `services/portfolio_engine_reserve.py` | ~395 | **Mittel** | Haengt von 5 Goal-Metadaten-Helfern ab, die physisch im Payload-Bau-Abschnitt stehen (bleiben dort/in CORE, Reserve importiert sie zurueck — kein Zyklus, da sie vor Zeile 2872 stehen); 2 extern importierte Namen |
| 5 | MC-Simulation | `services/portfolio_engine_mc_simulation.py` | ~1'170 | **Mittel-Hoch** | Groesster Cluster — Risiko ist Umfang-getrieben (mehr Code = mehr Chance auf Kopierfehler), nicht Architektur-getrieben; haengt von CMA (Schritt 3, bereits stabil) + Goal-Metadaten (bleiben in CORE) ab |
| 6 | Optimizer-Integration *(nicht im Original-Plan)* | `services/portfolio_engine_optimizer_integration.py` | ~868 | **Mittel** | Ueberwiegend Ein-Richtungs-Abhaengigkeit, aber `evaluate_goal_sensitivity` (Orchestrator) ruft mehrere dieser Helfer direkt auf |
| 7 | Payload-Bau Phase B (Goal-Analyse/Produktselektion) | `services/portfolio_engine_payload.py` | ~775 | **Mittel** | `_merge_goal_analysis_with_monte_carlo` liest das MC-Output-Dict per Key — braucht eine stabile, bereits getestete MC-Extraktion (Schritt 5) als Voraussetzung |
| 8 | House-Matrix/Tilt | `services/portfolio_engine_house_matrix.py` | ~1'110 | **Hoch** | Ruft aktiv in Reserve hinein (`_apply_goal_and_reserve_tilts`), wird in der 3-stufigen Risk-Budget-Eskalationskaskade des Haupt-Orchestrators bis zu 3× mit unterschiedlichem Zwischenzustand aufgerufen, 2 extern importierte Namen — bewusst zuletzt, wenn alle Cluster, in die es hineinruft, bereits stabile Module sind |

**Payload-Bau erscheint zweimal** (Position 2 und 7), weil die faktische
Kopplung innerhalb des vom Plan benannten „Payload-Bau"-Kandidaten selbst
zweigeteilt ist (Live-Rebalancing ist isoliert, Goal-Analyse/
Produktselektion ist es nicht) — das ist ein Fund aus dem Code-Lesen, kein
Plan-Vorgabe-Bruch.

## Migrations-Pattern pro Modul

Analog zu ADR-008s Pattern pro Sektion, angepasst an Backend/Python:

```
1. Extraktion (0.5-1 Tag pro Cluster, je nach Groesse)
   - Zielfunktionen + ihre direkten Modul-Abhaengigkeiten (Konstanten,
     kleine Helfer, die NUR von diesem Cluster genutzt werden) verbatim
     in die neue Datei kopieren (nicht neu schreiben — Byte-fuer-Byte-
     Kopie der Funktionskoerper).
   - Aus portfolio_engine.py entfernen.
   - Cluster-lokale Imports (Modelle, andere Services) an den Dateikopf
     der neuen Datei setzen.
   - Cross-Cluster-Abhaengigkeiten (Konstanten/Helfer aus CORE oder einem
     noch nicht extrahierten Cluster) per `from services.portfolio_engine
     import ...` beziehen — NICHT dupliziert.

2. Rueckwaerts-kompatibler Re-Export
   - In portfolio_engine.py, an der Stelle, wo die Original-Funktionen
     standen (oder gesammelt am Dateiende vor den Orchestratoren):
     `from services.portfolio_engine_<cluster> import (name1, name2, ...)  # noqa: F401`
   - Explizite Namensliste statt `import *` — macht sichtbar, welche
     Namen re-exportiert werden, und verhindert versehentliches
     Verschlucken von Linter-Warnungen fuer unbenutzte Wildcard-Importe.
   - Jeder Name, der HEUTE per grep als extern importiert verifiziert
     wurde (siehe Cluster-Tabellen oben), MUSS in dieser Liste stehen.

3. Verhaltens-Beweis (Pflicht vor jedem Merge)
   - Alle 90 Test-Dateien aus `grep -rl "portfolio_engine" tests/*.py`
     unveraendert gruen (kein Test-File wird angefasst).
   - `tests/test_golden_snapshot_ch_regression.py` unveraendert gruen
     (exakter Byte-Vergleich gegen eingefrorene Fixtures).
   - Determinismus-Check: `generate_target_allocation` zweimal mit
     identischem Input aufrufen, Ergebnis muss identisch sein (bereits
     Bestandteil der Golden-Snapshot-Suite, aber explizit re-verifizieren
     nach jeder Extraktion).

4. Ein Extraktionsschritt = ein PR
   - PR-Titel-Muster: `refactor(engine)/extract-<cluster-name>`
   - PR-Beschreibung listet die verschobenen Funktionsnamen + bestaetigt
     „0 Zeilen Fachlogik-Aenderung, nur Datei-Grenze verschoben".
   - Branch-Check vor Commit (Dual-Agent-Setup, siehe Memory
     `feedback_branch_check_before_commit`).
```

## Entscheidung

**Modul-fuer-Modul-Extraktion in der oben genannten Reihenfolge, KEIN
Big-Bang-Rewrite.** Konsistent mit der bereits etablierten Philosophie aus
ADR-008 (Frontend) und dem Umsetzungsplan Welle 3 generell
("Struktur-Migration ... nie big-bang"):

- Jeder Schritt ist einzeln PR-faehig, einzeln testbar, einzeln
  revertierbar.
- Die Reihenfolge (am wenigsten verflochten zuerst) minimiert das Risiko,
  dass ein frueher Schritt durch einen spaeteren Schritt nochmal beruehrt
  werden muss.
- House-Matrix/Tilt (der am staerksten verflochtene Cluster) und
  Optimizer-Integration (im Plan nicht vorgesehen, aber real vorhanden)
  werden explizit als eigene, spaete Schritte gefuehrt statt uebersprungen
  oder in einen anderen Cluster gequetscht.
- Die 5 Orchestrator-Funktionen (`generate_target_allocation`,
  `evaluate_goal_sensitivity`, `build_target_payload_from_allocation`,
  `build_recommendation_payload_from_run`, `generate_recommendation_run`,
  zusammen ~1'900 Zeilen) werden **nicht** extrahiert — sie sind der
  gewuenschte, duenne Kleber, der nach Abschluss aller 8 Extraktionen
  in `portfolio_engine.py` uebrig bleibt.

## Konsequenzen

**Positiv:**
- `portfolio_engine.py` schrumpft von 8'820 auf ca. 1'900-2'800 Zeilen
  (Orchestratoren + irreduzibler CORE-Kern), abhaengig davon, wie viel von
  CORE sich am Ende noch sinnvoll mitverschieben laesst.
- Jeder der 8 Cluster wird eigenstaendig lesbar, ohne die anderen 7 im Kopf
  behalten zu muessen.
- Import-Alias-Pattern haelt alle 4 bekannten externen Konsumenten
  (`backtest_ab.py`, `review_engine.py`, `advisory_report.py`,
  `foundation_example.py`) sowie alle 90 Test-Dateien unveraendert
  funktionsfaehig — die Migration ist von aussen unsichtbar.
- Golden-Snapshot-Test macht die Verhaltensneutralitaet **beweisbar**,
  nicht nur behauptet.

**Negativ / Trade-offs:**
- **Temporaere Import-Indirektion**: fuer die Dauer der Migration (und
  vermutlich darueber hinaus, siehe ADR-008s aehnliche Erfahrung mit dem
  Frontend) importiert `portfolio_engine.py` von seinen eigenen
  ehemaligen Bestandteilen zurueck — ein Engineer, der `_expected_metrics`
  sucht, findet in `portfolio_engine.py` nur eine Re-Export-Zeile und muss
  einen Schritt weiter zu `portfolio_engine_cma.py` gehen.
- **Zwei-Datei-Mentalmodell pro Cluster** bis alle 8 Extraktionen
  abgeschlossen sind: „ist diese Funktion schon extrahiert oder noch im
  Hauptfile?" — genau das gleiche Trade-off wie ADR-008s "Zwei
  Stack-Mentalitaeten".
- **90-Test-Datei-Ueberraschung**: die tatsaechliche Testbasis ist 5.6×
  groesser als im Umsetzungsplan angenommen. Das ist per se positiv
  (mehr Absicherung), macht aber jeden Extraktionsschritt langsamer zu
  verifizieren (volle Suite statt 16 Dateien).
- **House-Matrix/Tilt bleibt bis zum Schluss ein grosser, unextrahierter
  Klumpen** (~1'110 Zeilen) — wenn die Migration nach Schritt 5-6 aus
  Prioritaetsgruenden pausiert wird, bleibt der am staerksten verflochtene
  (und damit fehleranfaelligste) Teil unangetastet im Hauptfile. Das ist
  bewusst in Kauf genommen (Risiko zuletzt statt Risiko zuerst), aber ein
  Abbruch nach Schritt 6 liefert weniger Netto-Verbesserung als ein
  Abbruch nach Schritt 4.
- **Kein neuer Fachlogik-Wert**: wie bei ADR-008 ist dies reines
  Refactoring — kein Feature, kein Bugfix. Rechtfertigung ist
  Wartbarkeit/Onboarding-Zeit, nicht Kundennutzen. Muss entsprechend
  gegen andere Roadmap-Punkte priorisiert werden (siehe Umsetzungsplan
  Welle 3: "eigene Sprint-Spur", nicht im Sofort-Start-Autonomie-Batch).

## Wann re-evaluieren?

- Wenn ein Extraktionsschritt den Golden-Snapshot-Test bricht und die
  Ursache nicht binnen Stunden gefunden wird → Schritt zurueckrollen,
  Cluster-Grenze in diesem ADR nachschaerfen (vermutlich war die
  Abhaengigkeitsannahme fuer diesen Cluster unvollstaendig).
- Wenn nach Schritt 4 (Reserve) klar wird, dass die 5 geteilten
  Goal-Metadaten-Helfer haeufiger angefasst werden als erwartet → eigenes,
  neuntes Mini-Modul `services/portfolio_engine_goal_metadata.py` in
  Betracht ziehen statt sie dauerhaft in CORE zu belassen.
- Wenn eine neue Jurisdiktion (nach DE) onboarded wird, WAEHREND diese
  Migration laeuft → Migration pausieren, Jurisdiktions-Arbeit hat
  Vorrang (fachlicher Wert vs. reines Refactoring).

## Referenzen

- `5eyes-backend/services/portfolio_engine.py` — das God-Modul (8'820 Zeilen)
- `docs/adr/ADR-008-html-monolith-migration.md` — Struktur-/Ton-Vorbild fuer
  diesen ADR; gleiches Big-Bang-vermeidendes Migrations-Muster
- `docs/planning/2026-07-18-umsetzungsplan-verbesserungen.md` §3.2 —
  Auftrag fuer diesen Plan
- `5eyes-backend/tests/test_golden_snapshot_ch_regression.py` — primaeres
  Sicherheitsnetz (CH-Pfad byte-identisch)
- `5eyes-backend/tests/test_portfolio_engine_regressions.py` — importiert
  `_compute_reserve_requirements`-Compat-Wrapper direkt beim Namen
- `services/backtest_ab.py`, `services/review_engine.py`,
  `services/advisory_report.py`, `services/foundation_example.py` — die 4
  bekannten externen Nicht-Test-Konsumenten "privater" Engine-Funktionen
- `services/optimizer/` — Vorbild fuer flache Modul-Benennung
  (`services/optimizer/solver.py`, `constraints.py`, ...), analog fuer
  `services/portfolio_engine_<cluster>.py`
