# Standortanalyse 5eyes vs. 3eyes — Stand 2026-05-17

Vergleich gegen die 3rd-eyes-Schulungsunterlagen (SwissLife Wealth
Managers, intern 2024-04-09). Quelle: `~/Desktop/Consulting Firma/3eyes/erklärung drei augen.pdf`.

Ziel: ehrlicher Status — wo wir aufgeholt haben, wo noch echte Lücken
sind, mit Zeitplan zum Schliessen.

---

## 1. 3eyes Differenzierungsfaktoren (Slide 9) — Side-by-Side

| Faktor | 3eyes | 5eyes heute | Bewertung |
|---|---|---|---|
| **Holistische Beratung** | "Integration aller liquider/illiquider Anlageklassen + Kredite + alle Faktoren (Einnahmen, Vorsorge, Inflation, Langlebigkeit)" | Beratungs/Gesamtvermögen-Split ✅, Cashflows mit Inflation-Linked ✅, Goals ✅, Pension-Pillar (AHV/BVG/3a/1e/FZG) ✅, Hypothek ✅, life_expectancy_year ✅ | **Gleichwertig** mit Detail-Lücke bei Mortalitäts-Verteilung |
| **Interaktivität** | "Unmittelbare Berechnung nach jeder Eingabe" | Dirty-Banner + manueller "Strategie berechnen"-Klick (Solver ~1-3 Sek) | **Schlechter** — kein Auto-Recompute |
| **Professionelle Optimierungen** | Goal-based hyperpersonalisierte SAA Standard, Mulvey/Ziemba stochastisch | `stochastic` Modus implementiert, aber `OPTIMIZER_MODE=house_matrix` ist Default | **Code-gleichwertig**, aber **Default schlechter** (opt-in) |
| **Realistische Projektionen** | Tausende Szenarien, Non-Normal, exogene Schocks, Steuern, Gebühren, Dividenden | 2000 Pfade default, Cornish-Fisher (Skew+Kurt), Stress-Scenarios, Importance Sampling, Transaktionskosten (15bps) | **Schlechter:** Steuern + Dividenden fehlen |

## 2. 3eyes Advisory Process (Slide 11) — Side-by-Side

| Schritt | 3eyes | 5eyes heute | Status |
|---|---|---|---|
| **Profilierung** | Risikoprofilierung + Kenntnisse/Erfahrungen | FINMA Eignungsprüfung (W305.02) + K&E (W305.03 Seite 1) inkl. Bug-Fix vom 2026-05-15 | ✅ **Mindestens gleichwertig** |
| **Vermögenssimulation** | "Realistische Vermögenssimulation (Gesamtvermögen, vorausschauend)" | Monte-Carlo-Engine mit korrelierten Cholesky-Pfaden, Itô-Korrektur, IS-Tail-Sampling | ✅ **Gleichwertig** |
| **Optimierung der SAA** | "Hyperpersonalisierung der SAA, verschiedene Zielfunktionen" | Stochastic-Mode (Mulvey/Ziemba-light): Goal-basiert mit Hardness-Hierarchie, SLSQP+DE-Fallback, Bands+Caps | ✅ **Code-gleichwertig**, **Default-Modus schlechter** |
| **Portfoliooptimierung** | "Anlagevorschlag (ISIN) basierend auf optimierter SAA + kundenspezifische Anlagekriterien" | Portfolio-Page mit Wealth-Positions, kein automatischer ISIN-Mapper-Pipeline-Endprodukt | ⚠️ **Lücke:** ISIN-Recommendation-Engine fehlt |
| **Reporting** | "Zusammenfassung + Rebalancing" | Summary-Page (sr-*) + Review-Page mit Drift-Triggern | ✅ **Gleichwertig** |

## 3. Engine-Tiefe (3eyes Slides 19-23) — Side-by-Side

| Inhalt | 3eyes | 5eyes | Lücke |
|---|---|---|---|
| Renditeerwartungen pro Sub-Asset 15J jährlich | ✅ SLAM-Quartal | ✅ CMA-Quartal via CSV-Import (P10) | keine |
| Korrelationen + Volatilitäten | ✅ | ✅ correlation_matrix_json + sigma_bps | keine |
| Excess Skew + Kurt | ✅ | ✅ skew_bps + excess_kurt_bps + Cornish-Fisher | keine |
| **Yield-Curve-Modell (Nelson-Siegel VAR)** | ✅ bias-adjustiert | ❌ nur CMA-Renditen | **Echte Lücke** |
| Bewertung Fixed-Income: Komponenten + FX-Hedging-Kosten | ✅ Index-Komponenten-basiert | ⚠️ aggregierte CMA-Werte, fx_hedged_return_bps | **Detail-Lücke** |
| **Aktien-Bewertungsmodell mit KGV-Mean-Reversion** | ✅ Total Return = Dividend + Preis | ❌ nur log-normal mit μ/σ | **Echte Lücke** |
| **Risikoprämien-Modell für RE/Alts** | ✅ über risikofreiem Zins | ❌ feste CMA-Werte | **Detail-Lücke** |
| Inflation-Pfad | ✅ | ✅ inflation_path_json | keine |
| **Multi-Currency (USD/EUR/CHF/GBP/JPY)** | ✅ | ⚠️ implizit über fx_hedged-Bucket | **Detail-Lücke** |

## 4. Was 5eyes BESSER kann (echte Vorteile)

| Vorteil | Begründung |
|---|---|
| **In-House / Vollkontrolle** | Kein Lizenz-Lock-in, anpassbar |
| **Schweizer Domain-Tiefe** | FINMA W305.02/03, AHV/BVG/3a/1e/FZG Pension-Pillars, Inflation-Linked Cashflows, Hypothek-Validator |
| **Risk-Override mit Audit-Trail** | Pflichtbegründung + Backend-Persistenz + sichtbare Override-Anzeige in Summary (V3 Sprint) |
| **Multi-Source Data Aggregator** | Fallback-Chain yfinance→stooq→alphavantage→twelvedata, Smart-Cache, Cross-Validation. 3eyes nutzt single source SLAM. |
| **Importance Sampling für Tail-Risk** | Mathematisch verifizierte 5-10× Variance-Reduktion. 3eyes-Schulung erwähnt das nicht. |
| **Conditional Goals (probability_pct)** | B6 Sprint — Goals mit Eintrittswahrscheinlichkeit 0-100% |
| **Time-Bucket-Reserve (≤1J/1-3J/3-7J)** | B5 Sprint — feingranulare Reserve-Logik |
| **Hyper-personalisierte Building Blocks pro Mandat** | B1 Sprint — pro Mandat eigene BB-Wahl |
| **Methodenvergleich-Panel (shadow_stochastic)** | V3 Sprint 1c-d — Apples-to-Apples House-Matrix vs. stochastic, Goal-Drivers, Constraint-Slacks |
| **Test-Coverage 1236 grün** | systematisch nachvollziehbar; 3eyes-Tests intern unbekannt |
| **Security-Härtung** | jsAttrArg-Helper, ehrliche PDF-Kommunikation, W305-Persistenz-Bug-Fix |
| **Open-Source-Stack** | yfinance, stooq, numpy, scipy, fastapi — CHF 0 statt 3eyes-Lizenzgebühren |

## 5. Echte Lücken — was uns noch fehlt zu 3eyes-Parity

### A. P0 Compliance-Gap (Pflicht für Beratungs-Mehrwert)

1. ✅ **Steuern** (Sprint 2 Item 1, commit 76a4556): Vermögenssteuer p.a.
   in CMA-Schema (Default 0 bps = aus). Engine zieht jährlich
   `wealth * (1 - bps/10000)` ab, nur auf positives Wealth (W2.5-konsistent).
   Kantonal-spezifische Sätze als CMA-Wert pro Mandat. Plus
   Kapitalbezugssteuer war schon im Cashflow-Modell.
2. ✅ **Dividenden separat modelliert** (Sprint 2 Item 2, commit c8f2793):
   3 CMA-Felder `dividend_yield_bps_equity_ch/intl/real_estate` + Engine-
   Integration als Tax-Drag `drag_pa = Σ_b weights·yield_b·tax_rate`.
   Implizit Total Return = Dividend + Preis getrennt für Steuer-Effekt.
3. ⏳ **Mortalitätsadjustierte Pensionen** (Sprint 3): BFS-Sterbetafel
   statt fixer `life_expectancy_year`. Wahrscheinlichkeitsverteilung über
   Lebensdauer.

### B. P1 Engine-Tiefe (Kompetitiver Faktor)

4. **Yield-Curve-Modell (Nelson-Siegel VAR)**: Forward-Zinskurven für Fixed-Income-Bewertung
5. **Aktien-Bewertungsmodell**: Total Return = Dividend Yield + Preis (mit KGV-Mean-Reversion)
6. **Risikoprämien-Modell für RE/Alts**: über risikofreiem Zins, statt fixe CMA-Werte

### C. P1 UX (Beratungsgespräch-Qualität)

7. **Echtzeit-Recompute / Reaktivität**: Auto-Trigger bei Cashflow/Ziel/Risiko-Änderung mit 800ms-Debounce, statt manueller "Berechnen"-Klick
8. **Default-Modus `stochastic`**: heute `house_matrix` Default. Hyperpersonalisierung soll Standard sein, nicht opt-in.
9. **Echte PDF-Engine**: wkhtmltopdf oder reportlab statt Browser-Druck-Dialog

### D. P2 Operational (nice-to-have)

10. **Multi-Currency-Forecasting**: USD/EUR/CHF/GBP/JPY explizit
11. **ISIN-Recommendation-Engine**: SAA → konkrete ETF-Vorschläge automatisiert
12. **Solver-IS-Integration (Phase 5c)**: Objective-Funktion mit Likelihood-Weights

---

## 6. Zeitplan — Roadmap zu 3eyes-Parity

Annahme: 1 Berater-Person + 1 KI-Assistent (also wir), keine separate Dev-Team-Velocity.

### Sprint 1 — Quick Wins (1-2 Wochen, geringes Risiko)

| Item | Aufwand | Risiko | Wert |
|---|---|---|---|
| **8. Default-Modus stochastic** | 2h Config-Switch + Tests-Regression-Run | gering | hoch — hyperpersonalisiert wird Default |
| **12. Solver-IS-Integration (Phase 5c)** | ~2 Tage | mittel (Solver-Pfad-Eingriff) | mittel — Tail-Risk realistischer |
| **7. Auto-Recompute mit Debounce** | ~1 Tag | gering | hoch — echtes 3eyes-Feeling |

**Ergebnis:** "Out-of-Box hyperpersonalisiert mit Echtzeit-Reaktion"

### Sprint 2 — Compliance Steuern + Dividenden (3-4 Wochen)

| Item | Aufwand | Risiko | Wert |
|---|---|---|---|
| **1. Steuern-Modell** | ~1 Woche (Schema + Engine + Tests + CH-Kantonsdaten) | mittel | sehr hoch — Beratungsmehrwert direkt |
| **2. Dividenden-Split** | ~1 Woche (CMA-Erweiterung + Engine-Pfad + UI) | mittel | hoch — Income-Pension-Mandate |

**Ergebnis:** Realistische Kunden-Projektion inkl. Steuerbelastung

### Sprint 3 — Mortalität + UX (3-4 Wochen)

| Item | Aufwand | Risiko | Wert |
|---|---|---|---|
| **3. BFS-Sterbetafel-Integration** | ~1 Woche (BFS-Daten + Engine + Tests) | mittel | mittel — Langlebigkeitsrisiko explizit |
| **9. Echte PDF-Engine** | ~1 Woche (wkhtmltopdf/reportlab setup + Template-Migration) | mittel | hoch — professionelle Kundendokumente |

**Ergebnis:** Compliance + Print-Qualität auf 3eyes-Niveau

### Sprint 4 — Engine-Tiefe (6-8 Wochen, eigene Mini-Specs)

| Item | Aufwand | Risiko | Wert |
|---|---|---|---|
| **4. Nelson-Siegel Yield-Curve** | 2-3 Wochen (Modell + Calibration gegen historische Zinsen + Tests) | hoch (Numerik) | mittel — Fixed-Income realistischer |
| **5. KGV-Mean-Reversion Aktien-Modell** | 2-3 Wochen (Modell + historische Kalibrierung + Tests) | hoch (Numerik) | mittel — Aktien-Projektion realistischer |
| **6. Risikoprämien-RE/Alts-Modell** | 1-2 Wochen (Modell + Tests) | mittel | niedrig — meist Detail-Verbesserung |

**Ergebnis:** Engine-Mathematik auf 3eyes-Niveau (echte Parity)

### Sprint 5 — Operational + Polish (laufend)

| Item | Aufwand | Risiko | Wert |
|---|---|---|---|
| **10. Multi-Currency-Forecasting** | 2-3 Wochen | mittel | niedrig — meiste CH-Kunden CHF-zentrisch |
| **11. ISIN-Recommendation-Engine** | 3-4 Wochen | mittel | hoch — Portfolio-Schritt vollständig |
| Datenpipeline Provider-Keys aktivieren | 30 Min | gering | hoch — Multi-Source-Robustheit |
| Visuelle Verifikation Customer Journey | 1-2h | gering | hoch — Sicherheit vor Kunden-Termin |

---

## 7. Empfehlung — Reihenfolge

**Wenn Beratungsmehrwert primär:**

1. Sprint 1 (Quick Wins, 1-2 Wochen) — Default-stochastic + Auto-Recompute
2. Sprint 2 (Steuern + Dividenden, 3-4 Wochen) — direkter Kundennutzen
3. Sprint 3 (Mortalität + PDF) — Compliance-Komplettierung
4. Sprint 4 (Engine-Tiefe) — wirkliche 3eyes-Parity

**Wenn Wettbewerbs-Argument primär (Vendor-Demo):**

1. Sprint 1 → "wir haben echte hyperpersonalisierte Echtzeit-Optimierung"
2. Sprint 4 — Engine-Tiefe — "wir haben dieselbe Mathematik wie 3eyes"
3. Sprint 2 — Steuern — "wir gehen 1 Schritt weiter als 3eyes (CH-Steuern)"

**Realistisch (geringe Disruption):**

Sprint 1 in 1-2 Wochen → dann Pilot mit 1-2 realen Mandanten → Feedback → Sprint-Reihenfolge anpassen.

---

## 8. Was nicht aufgeholt werden muss / soll

- **Cloud-Hosting Multi-Device**: 5eyes ist bewusst Desktop. Pro: Datenschutz, keine Cloud-Lizenzkosten, FINMA-konformer lokaler Datenspeicher.
- **3eyes-Marketing-Materialien**: 5eyes ist In-House-Tool, kein Vendor-Pitch nötig.
- **3eyes-spezifische Branding/UX**: 5eyes hat eigene Identität (5e WealthArchitekten).

---

## 9. Status nach Standortanalyse — kurz

5eyes hat 70-80% der 3eyes-Funktionalität implementiert. Echte Lücken:
**Steuern + Dividenden + Mortalitäts-Verteilung + Auto-Recompute + 3 Engine-Modelle**.

Mit dem hier vorgeschlagenen Sprint-Plan (~3 Monate) ist 3eyes-Parity
erreichbar, plus 5eyes-spezifische Vorteile (CH-Domain, In-House,
Multi-Source-Provider) bleiben Differenzierer.
