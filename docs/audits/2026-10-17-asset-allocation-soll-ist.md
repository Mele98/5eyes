# Assetallocation – Soll-Ist-Analyse für den CH-Launch (2026-10-17)

Geltungsbereich: Schritt SAA der Journey Stammdaten → Cashflow/Ziele →
Risikoprofil → **SAA** → Portfolio. Referenzstand IST: `origin/develop` @
`ac93094` (nach #612). Offene PRs und Branches gelten als „in Arbeit“, nicht
als IST. Alle Zeilenangaben beziehen sich auf `origin/develop`, sofern nicht
anders vermerkt. Pfade ohne Präfix liegen unter `5eyes-backend/`.

Methode: rein statisch (Code, PR-Beschreibungen, Commit-Messages,
CI-Status). Es wurden keine Tests und keine App gestartet; die Live-DB wurde
nicht geöffnet. Messwerte aus PRs sind als solche gekennzeichnet und nicht
nachgemessen.

## Executive Summary

Die Assetallocation ist mathematisch weit fortgeschritten: Die Herleitung aus
dem Risikoprofil ist fail-closed, Risikobudget, Illiquiditäts-Cap, Reserve und
Gesamtvermögens-IST sind verdrahtet, und jeder Lauf ist mit Hashes,
Seed und eingefrorenem Zielfunktions-Vertrag nachvollziehbar. Für einen
Launch mit echten Mandanten fehlt aber noch die **Stabilität** (die
Soll-Allokation hängt heute vom Monte-Carlo-Seed ab, und der Seed hängt an
Datenbank-IDs) sowie die **Deckungsgleichheit von Engine und Dokument** bei
ESG, Themen-Ausschlüssen und Stresstests: Heute verspricht das Kunden-PDF
Ausschlüsse und ESG-Filter, die die Engine nicht so umsetzt. Dazu kommen
zwei P0-Bedienfehler (Band-Editor, manueller Editor), die in offenen PRs
gelöst sind. Reifegrad auf `develop`: **rund 52 %**. Werden alle offenen PRs
und Branches gemergt, steigt er auf **rund 76 %**. Danach verbleiben vor allem
Datenarbeit (ESG-Katalog, IC-Parameter), Governance (Vier-Augen-Freigabe
von Hausmatrix und CMA, Eignungs-Gate in Produktion) und die Normierung der
Zielfunktion. Der kritische Pfad bis 1.7.2027 ist damit weniger Code als
**Owner-Entscheide und Fachdaten**.

Bewertung: erfüllt = 1, teilweise = 0.5, in PR = 0.25, fehlt = 0; 27
CH-relevante Fähigkeiten (DE separat, nicht im Nenner). Nach Merge zählt
eine Fähigkeit mit verbleibender Daten- oder CI-Lücke als 0.75.

## Fähigkeiten im Einzelnen

### A. Herleitung und Rahmen

| Fähigkeit | SOLL | IST (Beleg) | Status | Lücke | Aufwand | Launch-Blocker |
|---|---|---|---|---|---|---|
| A1 Score → Hausmatrix-Zeile | Eindeutige, monotone, fail-closed Zuordnung des Risikoprofils zu genau einer Hausmatrix-Zeile | Bucket per round-half-up, kein stiller Fallback (`services/portfolio_engine.py:619-631`); Lookup wirft bei Überlappung oder Lücke (`services/portfolio_engine_house_matrix.py:1546-1560`); Default-Matrix mit 7 Zeilen (`services/portfolio_engine.py:1743-1751`) | erfüllt | – | – | nein |
| A2 Hausmatrix-Governance | Eine Quelle, versioniert, Vier-Augen-Freigabe, Zeilensumme exakt 100 % | Admin-Endpoints für Zeilen, Aktivierung und Klon (`routers/allocation.py:1413-1515`), Policy-Archiv (`routers/allocation.py:88`); Aktivierung braucht nur `require_admin` (`routers/allocation.py:1463`). Der YAML-Loader `services/house_matrix_loader.py` wird von keinem Modul importiert (tote zweite Quelle). Zeile 7–8 summiert sich zu 9'950 bps (`services/portfolio_engine.py:1747`) und wird zur Laufzeit normalisiert (`services/portfolio_engine_house_matrix.py:1622`) | teilweise | YAML verdrahten oder löschen (MATH-HM-1); Rohdaten der Zeile 7–8 korrigieren; Vier-Augen-Aktivierung | S–M | ja (Governance-Nachweis) |
| A3 Bänder und Berater-Overrides | Overrides bleiben über Rundläufe erhalten; Abweichung vom Hausmatrix-Band nur mit Begründung, offengelegt im Kundendokument | Offenlegung als Reasoning und Warnung (`services/portfolio_engine_house_matrix.py:317-330`), Freigabe-Warnung (`routers/review.py:376-398`, „bewusst nur WARNUNG“), Cap-Klemmung offengelegt (`services/portfolio_engine_house_matrix.py:384`). Rundlauf-Verlust, 422 bei Teil-Edit und bps/%-Verwechslung im Editor bestehen (#601, P0) | in PR (#601; Branch `feat/band-deviation-reason-required`) | Merge #601; Pflichtbegründung als Freigabe-Gate und PDF-Abschnitt (Branch) | S | **ja** (P0) |
| A4 Risikobudget | Risikoanteil ≤ Budget der Hausmatrix, in jedem Pfad durchgesetzt | Durchsetzung `_enforce_risk_budget` (`services/portfolio_engine_house_matrix.py:700`); Lock-Grund `risk_budget_violated` (`services/mandate_lock_audit.py:34`) blockiert die Finalisierung (`routers/review.py:205`) | erfüllt | Manueller Pfad: siehe E2 | – | nein |
| A5 Illiquiditäts-Cap | Obergrenze für illiquide Anlagen | `_apply_illiquid_cap` (`services/portfolio_engine_house_matrix.py:1149`) | erfüllt | – | – | nein |
| A6 Reserve und Gesamtvermögen | Liquiditätsreserve einmal gehalten; IST auf Gesamtvermögen netto aller Schulden; Immobilie als Sockel | `services/portfolio_engine_reserve.py`, `services/portfolio_engine_gesamtvermoegen.py`; Doppelreserve (#602) und Schuldenabzug (#605) gemergt | erfüllt | MATH-RES-2: Reserve im House-Fallback um c·E unterfinanziert (P2, offen) | S | nein |

### B. Präferenzen, Tilts, ESG

| Fähigkeit | SOLL | IST (Beleg) | Status | Lücke | Aufwand | Launch-Blocker |
|---|---|---|---|---|---|---|
| B1 Anlagepräferenzen und Restriktionen | Universum, Heimmarkt, Währung/Hedging, Produktrestriktionen wirken wie beschriftet | Validierung (`schemas/allocation.py:95-109`); Produktfilter (`services/portfolio_engine_payload.py:740-763`). Offen: F-HEDGE-1/2 (bei Pflicht-Hedging wandert Alkohol-Thema in den SPI; „Hedging bevorzugt“ wählt ungehedgt ohne Hinweis) | teilweise | F-HEDGE-1/2 nach ESG-Fix | S–M | nein |
| B2 Tilts mit ehrlicher Begründung | Jeder Tilt sagt, ob er Startwert oder Band ist, und der Effekt ist im Ergebnis sichtbar | Themen-Tilts `exclude/underweight/neutral/overweight` (`schemas/allocation.py:26-27`); Wirkung nur als Score im Produktslot (`services/portfolio_engine_payload.py:916-942`). F-TILT-1 (Begründung behauptet Effekte, die der Solver überschreibt) und F-TILT-2 (Ziel-Tilt verschiebt explizite Berater-Zielquote im Fallback) offen | teilweise | Tilt-Typ pro Tilt unterscheiden, Fallback-Vorrang korrigieren | M | nein |
| B3 ESG-Policy unterscheidbar | `esg_integration`, `best_in_class`, `impact`, `net_zero` je mit eigenem, datengestütztem Kriterium; UI, PDF und Engine aus einer Quelle; fehlende Daten = nicht zulässig | Alle vier Policies = derselbe SFDR-8/9-Filter (`services/portfolio_engine_payload.py:773-778`). UI-Labels widersprechen: „Impact (SFDR 9 Filter aktiv)“ und „ESG-Integration (Dokumentation, kein Filter)“ (`5eyes-electron/frontend/5eyes_v2.html:3672`) | in PR (#615 Labels; Branch `feat/esg-premium-criteria`: SFDR 9 für Impact, SFDR 9 oder PAB/CTB für Net Zero, Rating/Score für Best-in-Class, `ESG_POLICY_CRITERIA` als Einzelquelle) | Merge; danach Datenlücke (siehe B5) | M | **ja** (Greenwashing-Risiko, FIDLEG-Informationspflicht) |
| B4 Themen-Ausschlüsse wirksam | Ausschluss ist harter Produktfilter für jeden Slot inkl. Fallback; Dokument behauptet nur, was wirkt | Ausschluss nur als `-10000`-Score im Themen-Slot (`services/portfolio_engine_payload.py:935-939`); PDF druckt „ausschliessen“ (`services/pdf/documents/anlagestrategie.py:729`). Laut #615 live: alle 6 Themen „exclude“, empfohlen 60 % Energy-Sektor-ETF | in PR (#615, gestapelt im Branch `feat/esg-premium-criteria` inkl. „bewusst zulassen“ mit Begründung und `theme_tags`) | Merge; Entscheid zu Negativ-Screening-Default (#615 Entscheid 1) | S | **ja** (P1, Dokument ≠ Engine) |
| B5 ESG-Datenbasis | Katalog mit SFDR-Klasse, ESG-Rating/Score, Klima-Benchmark (PAB/CTB) und Themen-Tags; pflegbar inkl. Löschen | Seed-Katalog: 11× SFDR 6, 12× SFDR 8, 2× ohne Angabe, **kein SFDR 9** (`services/portfolio_engine.py:1913-1978`); keine Spalte `climate_benchmark` auf develop. Im Branch: `climate_benchmark` und `theme_tags` neu, aber das Produkt-Update nutzt `model_dump(exclude_none=True)` (`routers/review.py:2333`; Branch `:2226`), ein gesetzter Klima-Benchmark lässt sich per Edit **nicht** auf leer zurücksetzen | fehlt | Mit dem Premium-Branch sind Impact und Net Zero auf dem Seed-Katalog **immer fail-closed** (kein zulässiges Produkt). Echte Produktdaten nötig; Update auf `exclude_unset` umstellen | S (Code) + Daten | **ja**, oder Impact/Net Zero bis zur Datenlieferung ausblenden |

### C. Optimierung und Robustheit

| Fähigkeit | SOLL | IST (Beleg) | Status | Lücke | Aufwand | Launch-Blocker |
|---|---|---|---|---|---|---|
| C1 Zielbasierte Optimierung | Ziele als Liabilities auf der Kalenderjahr-Achse; Zielerreichung je Ziel ehrlich nach Priorität | Liability-Pfad auf Kalenderjahren (ADR-2, `services/optimizer/goal_liabilities.py:1-30`, `:588`); Chance-Penalty je Ziel (`services/optimizer/objective.py:533-715`). Die je Ziel publizierte Quote ist die gemeinsame Plan-Solvenz (GOAL-ACHIEVABILITY-ATTRIBUTION-001) | teilweise; Attribution in Branch `feat/goal-attribution-and-dd-certification` (`priority_funded` je Ziel, `joint_plan` einmal) | Merge; Wealth-Ziel-Achse (offener Quant-Punkt) | M | ja (falsche Zielampel im Kundendokument) |
| C2 Zielfunktion und Drawdown | Wählbare, erklärbare Zielfunktion; Drawdown-Ergebnis selektionsfrei zertifiziert; Terme vergleichbar skaliert | 5 Modi (`services/optimizer/objective_variants.py:128-132`), Auswahl nur per Umgebungsvariable `OPTIMIZER_OBJECTIVE` (`:206-218`), nicht pro Mandat. `LAMBDA_CHANCE_DEFAULT = 1e6` (`services/optimizer/objective.py:44`) dominiert den Primärterm um ~6 Grössenordnungen. Drawdown-Nachrechnung nur für den Gewinner auf dem Trainings-Cube, reine Anzeige (`services/optimizer/objective_variants.py:553-590`). Keine mandatsspezifische Verlusttoleranz als Nebenbedingung (`services/optimizer/constraints.py`, keine Drawdown-Restriktion) | teilweise; Drawdown-Rerank auf Validierungs-Cube im Branch `feat/goal-attribution-and-dd-certification` | Normierung der Chance-Penalty (geplant nach #619) | M | nein (Normierung), aber vor Launch empfohlen |
| C3 Stabilität (Resampling) | Gleiche ökonomische Inputs ⇒ gleiche SAA; Seed-Streuung ≪ Bandbreite; Abweichung von der Hausmatrix nur, wenn signifikant besser | Seed aus CMA-ID und Ziel-IDs (`services/optimizer/solver.py:594-597`); 2'000 Pfade (`services/portfolio_engine.py:2484`); kein Resampling im Code. Audit 2026-10-14: Aktien 63–75 % allein durch den Seed | in PR (#619: Inhalts-Seed, 40×500 Michaud-Bagging, gepaarter Bootstrap gegen die Hausmatrix; σ Aktien laut PR 4.93 → 0.76 Pp) | **CI rot**: 4 Golden-Snapshots weichen in CI ab (CPU-abhängig, lokal byte-identisch), dazu `test_ci_workflow_audit` (Timeout 200 statt 150). Kundensichtbar: bucket7 Aktien 60 → 68 %, bucket9 75 → 79 % | M | **ja** |
| C4 Sensitivität / What-if | Berater sieht, wie empfindlich die SAA auf Annahmen reagiert | Endpoint `POST …/target-allocation/sensitivity` (`routers/allocation.py:771`), `evaluate_goal_sensitivity` (`services/portfolio_engine.py:4307`); Shadow-Vergleich (`services/shadow_comparison.py:22`) | erfüllt | Mit #619 gleicher Anker (im PR enthalten) | – | nein |
| C5 Stress-Szenarien | Krisen-Kennzahlen im Bereich [0, 100 %], Krisen-Effekt getrennt von Entnahmen; zusätzlich Faktor-Schocks (Zins, CHF-Aufwertung, Inflation, Spread) | 3 starre Bucket-Pfade (`services/optimizer/stress_scenarios.py:43-62`), 0 %-Padding bis Horizontende (`:90-107`), Drawdown auf dem Vermögenspfad inkl. Entnahmen. Laut #608 live bis 515 % Drawdown. Historische Replays im Beratungsreport (`services/advisory_report.py:2847`) und Depot-Check-PDF (`services/pdf/documents/depotcheck.py:135`); keine Stresstabelle im Anlagestrategie-PDF | in PR (#608) | Merge; Faktor-Stress fehlt ganz; Reasoning im House-Fallback beschreibt verworfenen Kandidaten (#608 offen) | S (Merge) / L (Faktor-Stress) | **ja** für #608 (sinnlose Zahlen in der Maske); Faktor-Stress nein |
| C6 Performance | Generierung im interaktiven Rahmen (< 10 s) | Budget 9.0 s (`tests/test_performance_budget.py:106`); synchroner Request (`routers/allocation.py:701`) | teilweise | #619 misst 5.1 → 12.3 s am Foundation-Mandat; Budget-Test unverändert. CI-Backend-Job läuft mit #619 1 h 44 min | M | nein, aber Entscheid zu Budget oder Hintergrund-Job vor Launch |

### D. Modellparameter

| Fähigkeit | SOLL | IST (Beleg) | Status | Lücke | Aufwand | Launch-Blocker |
|---|---|---|---|---|---|---|
| D1 CMA-Herkunft und Freigabe | Jede CMA-Version mit Quelle, Datum, Freigabe durch zweite Person | Felder `source`, `source_date`, `valid_from`, `status` (`models/allocation.py:255-347`); neue Version wird sofort `is_current=1` (`routers/allocation.py:680`), Rolle Portfolio-Management (`:603`), keine zweite Freigabe | teilweise | Vier-Augen-Freigabe vor Aktivierung | M | ja (FINIG-Organisationspflicht, interne Kontrolle) |
| D2 Korrelationen und rho-Provenienz | Korrelationsmatrix und Intra-Bucket-Korrelation (rho) mit Quelle und IC-Freigabe | 5×5-Herkunft im Nachweis sichtbar (`services/cma_correlation_provenance.py:1-25`); rho = `sub_class_intra_correlation`, Default 1.0 (`config.py:471`), in Hashes gebunden (`services/portfolio_engine_cma.py:434-447`), aber ohne Quelle | teilweise | rho-Wert und Quelle durch IC | S + Daten | nein (konservativer Default 1.0) |
| D3 Nelson-Siegel-Obligationen | Zinskurve wirkt sleeve-spezifisch (Duration je Obligationen-Sleeve) | Niveau-Kollaps behoben, Kurve nur noch als Tilt (`services/optimizer/scenario_engine.py:916-935`); Tilt für alle Sleeves identisch (`:976-978`) | teilweise | Sleeve-Durationen brauchen IC-Daten | M + Daten | nein |

### E. Overrides, Staleness, manuelle Allokation

| Fähigkeit | SOLL | IST (Beleg) | Status | Lücke | Aufwand | Launch-Blocker |
|---|---|---|---|---|---|---|
| E1 Berater-Overrides mit Begründung | Jede Abweichung (Risikoprofil, Band, Tilt, manuelle Quote) braucht eine qualitätsgeprüfte Begründung, die im Kundendokument erscheint | Qualitätsprüfung (`services/override_reason_quality.py:38-59`) heute nur für Risikoprofil-Override (`services/risk_assessment_semantics.py:368`), Report und PDF (`services/advisory_report.py:2352`, `routers/pdf_reports.py:1057`). Band, Tilt und manuelle Quote ohne Begründungspflicht | teilweise; Band (Branch `feat/band-deviation-reason-required`), Tilt „bewusst zulassen“ (Branch `feat/esg-premium-criteria`), manuell (#616) | Merge | S | ja |
| E2 Manuelle Allokation | Speichern ist ein verifizierbarer Anker; Risikobudget und Datenbasis wie bei Generate; Audit mit Alt/Neu und Begründung | `POST …/target-allocation` (`routers/allocation.py:226-462`): Risikobudget wird berechnet (`:364`), aber nicht gegen den Risikoanteil geprüft; Audit-Eintrag ohne Werte und Begründung (`:449-452`). Laut #616 führt schon das Speichern identischer Werte zu 409 und degradiert die gültige Allokation | in PR (#616; Branch `fix/manual-save-requires-basis` mit Basis-Guard `_assert_allocation_has_basis`, `services/portfolio_engine.py:3006`) | Merge; Zeilen vom 09.–14.10. neu speichern (#616 Entscheid 2) | S | **ja** (P1-Sackgasse) |
| E3 Staleness-Erkennung | Jede Input-Änderung (Vermögen, Cashflow, Ziele, Risikoprofil, CMA) macht die SAA veraltet; veraltete Ziele werden nicht gezeigt | Input-Hash blockiert den Payload (`services/portfolio_engine.py:5926-5944`); Risikoprofil-Override (#606) gemergt; Depot-Check und Report erkennen es (`services/depot_check.py:627-636`), zeigen die alten Ziele aber weiter neben dem Hinweis. CMA-Wechsel nur als Hinweis (`services/portfolio_engine.py:2993-3000`). Risikoprofil-Aktualität (365 Tage) nur per Opt-in-Flag `require_suitability_before_recommendation=False` (`config.py:426`, genutzt `routers/allocation.py:258`) | teilweise; Ziele ausblenden im Branch `fix/stale-allocation-hide-targets` | Merge; Produktionswert des Eignungs-Gates entscheiden; CMA-Wechsel blockierend oder bewusst Hinweis | S | ja (Eignungs-Gate in Produktion) |
| E4 Simulationshorizont | Horizont aus Lebenserwartung/BFS/letztem Cashflow, ausser Berater wählt explizit | Fix gemergt (#611, `90b5e43`) | teilweise; Alt-Default-Migration im Branch `feat/sim-horizon-legacy-migration` | Merge | S | nein |

### F. Nachweis und Kundendokumente

| Fähigkeit | SOLL | IST (Beleg) | Status | Lücke | Aufwand | Launch-Blocker |
|---|---|---|---|---|---|---|
| F1 Audit-Trail und Reproduzierbarkeit | Jede SAA mit Inputs, Präferenz-Snapshot, Modellbasis, Seed, Zielfunktion; unveränderliches Log; referenziell saubere Daten | `TargetAllocation` mit `allocation_context_hash`, `input_snapshot_hash`, `preferences_json`, `optimization_seed`, Reasoning, Stress (`models/allocation.py:80-136`); `OptimizerRun` mit Seed, Validierungs-Seed und Cube-Hash (`:146-202`); Zielfunktions-Vertrag `objective-contract-v1` (`services/optimizer/objective_contract.py:64`). FK-Waisen in Altdaten: `PRAGMA foreign_keys = ON` (`database.py:105`), aber nirgends `foreign_key_check` | teilweise | Seed nicht inhaltsbasiert (C3); FK-Bereinigung plus Prüflauf | S–M | ja (Altdaten vor Mandanten-Migration bereinigen) |
| F2 Kundendokumente konsistent | Anlagestrategie-PDF, Beratungsentscheid, Kostenausweis und Depot-Check zeigen dieselbe aktuelle SAA mit den Produkten desselben Laufs | Run-Resolver für Kundendokumente gemergt (#609). Kostenausweis wählt den Quelllauf noch nach Rang über **alle** Läufe (`services/cost_disclosure.py:220-260`), ohne Bindung an die aktuelle Allokation | teilweise; Branch `fix/cost-disclosure-run-resolver` | Merge (FIDLEG-Ex-ante-Kosten) | S | **ja** |
| F3 Offenlegung im Kundendokument | ESG-Policy, Ausschlüsse, Band-Abweichungen, Overrides, Zielerreichung und Stress so, wie die Engine sie umgesetzt hat | Präferenz-Tabelle (`services/pdf/documents/anlagestrategie.py:664-690`), Bänder nur bei Overrides (`:851-857`), Risiko-Override-Begründung (`:178`, `:388`), Zielerreichung (`:300`). Themen-„ausschliessen“ ohne Wirkung (`:729`); keine Stresstabelle im Anlagestrategie-PDF | teilweise | Mit B3/B4/A3/C1 gemergt grösstenteils geschlossen; Stress-Abschnitt im Anlagestrategie-PDF ergänzen | S–M | ja (über B3/B4) |

### G. Jurisdiktion (nicht im CH-Nenner)

| Fähigkeit | SOLL | IST (Beleg) | Status | Lücke | Aufwand | Launch-Blocker |
|---|---|---|---|---|---|---|
| G1 DE-Mandate | Eigene Korrelationsmatrix und Sub-Anlageklassen-CMA; im Monolith berechenbar | DE erhält die Schweizer Default-Korrelation (`services/cma_correlation_provenance.py:12-19`); Monolith bietet nur CH-Optionen (`5eyes-electron/frontend/5eyes_v2.html:3790`, F4b) | fehlt | IC-Daten DE; UI-Optionen | M + Daten | nein (CH-Launch) |

## Reifegrad-Rechnung

| | develop | nach Merge aller PRs/Branches |
|---|---|---|
| erfüllt | 5 (A1, A4, A5, A6, C4) | 11 (zusätzlich A3, B4, E1, E2, E4, F2) |
| Punkte / 27 | 14.0 → **52 %** | 20.5 → **76 %** |

Nach dem Merge bleiben offen oder teilweise: A2, B1, B2, B3/B5 (Daten), C1,
C2, C3 (CI), C5 (Faktor-Stress), C6, D1–D3, E3 (Eignungs-Gate), F1, F3.

## Priorisierte Restliste bis Launch

**Welle 1 – Merge-Kette (Code liegt vor, S)**

1. #620 mergen, damit die CI für alle PRs wieder grün sein kann.
2. #601 Band-Roundtrip (P0), danach `feat/band-deviation-reason-required`.
3. #616 manuelle Allokation, danach `fix/manual-save-requires-basis`.
4. #615 Themen-Ausschluss, danach `feat/esg-premium-criteria`.
5. #608 Stress-Semantik.
6. `fix/cost-disclosure-run-resolver`, `fix/stale-allocation-hide-targets`,
   `feat/sim-horizon-legacy-migration`, `feat/goal-attribution-and-dd-certification`.
   Inventar-Snapshot des Monolithen bei jedem zweiten Merge neu erzeugen.

**Welle 2 – Stabilität (M)**

7. #619 grün machen: Golden-Snapshots CPU-unabhängig (Toleranz oder
   CI-seitig erzeugt) und CI-Timeout-Audit nachziehen. Kundensichtbare
   Verschiebung (bucket7 60 → 68 % Aktien) vom CIO abnehmen lassen und
   Bestandsmandate gezielt neu berechnen.
8. Chance-Penalty normieren (auf #619 aufbauend), danach Golden neu.
9. Performance: 12.3 s gegen das 9-s-Budget. Entweder Budget anheben oder
   Generierung als Hintergrund-Job.

**Welle 3 – Daten und Governance (S–M, Owner-abhängig)**

10. ESG-Katalog mit SFDR 9, PAB/CTB und Ratings befüllen; bis dahin Impact
    und Net Zero in UI ausblenden. `climate_benchmark`-Edit auf
    `exclude_unset` umstellen.
11. Vier-Augen-Freigabe für Hausmatrix-Aktivierung und CMA-Version.
12. Hausmatrix-YAML entscheiden; Zeile 7–8 auf 10'000 bps korrigieren.
13. `require_suitability_before_recommendation` für Produktion festlegen.
14. FK-Waisen: `foreign_key_check`-Prüflauf und Bereinigung der Altdaten vor
    der Mandanten-Migration.

**Welle 4 – Qualität (P2, nicht blockierend)**

15. F-TILT-1/2, F-HEDGE-1/2, MATH-RES-2, Reasoning im House-Fallback.
16. Stress-Abschnitt im Anlagestrategie-PDF; Faktor-Stress (Zins,
    CHF-Aufwertung, Inflation, Spread) als Ausbau.
17. Zielfunktion pro Mandat wählbar statt nur per Umgebungsvariable.

## Was vom Owner nötig ist

**Entscheide**

- #619: Abnahme der kundensichtbaren Verschiebung und des Laufzeit-Budgets.
- Normierung der Chance-Penalty: Zielgewicht von Primärterm zu Zielstrafe.
- #615: Negativ-Screening-Default; mit dem Premium-Branch durch „bewusst
  zulassen“ vorbereitet, aber zu bestätigen.
- #616: Gleiche Basis-Strenge für manuelle Speicherung (Branch umgesetzt,
  Abnahme) und Umgang mit den Zeilen vom 09.–14.10.
- Eignungs-Gate (365-Tage-Aktualität) in Produktion an oder aus.
- CMA-Wechsel: blockierend oder weiter nur Hinweis.
- Hausmatrix-YAML: verdrahten oder entfernen.
- Impact/Net Zero bis zur Datenlieferung anbieten oder ausblenden.

**Fachinput und Daten (nicht erfinden)**

- Produktdaten: SFDR-Klasse, ESG-Rating/Score, Klima-Benchmark, Themen-Tags
  für den echten Katalog.
- IC-Parameter: rho (Intra-Bucket-Korrelation) mit Quelle,
  Obligationen-Sleeve-Durationen für Nelson-Siegel, Wealth-Ziel-Achse.
- Für DE (nach CH-Launch): Korrelationsmatrix und Sub-Anlageklassen-CMA.
- Freigabeprozess: Wer ist zweite Person für Hausmatrix und CMA.
- Bereinigung der Altdaten (FK-Waisen): welche Datensätze gelöscht oder
  umgehängt werden dürfen.
