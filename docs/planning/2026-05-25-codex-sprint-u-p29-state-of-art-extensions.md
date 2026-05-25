# Codex-Sprint U-P29 — State-of-the-art-Ergänzungen für Advisory-Report

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25.
> **Voraussetzung:** U-P21 (Backend), U-P23/U-P24/U-P25 (Frontend), U-P26 (PDF)
> fertig. Dieser Sprint bringt 5eyes auf das Niveau Family-Office-Reporting
> (UBS GFO Report, Pictet, PPC Metrics) — siehe Audit §4.2.
> **Größenordnung:** ~25-35 Stunden über 5 PRs.

---

## Was kommt rein (5 Ergänzungen aus Audit §6 P3-P4)

### E1 Performance-Attribution (Audit Top-8)
Zerlegt erwartete Rendite in Anteile:
- **Asset-Allocation-Effekt** (welcher Anteil aus Bucket-Wahl)
- **Security-Selection-Effekt** (welcher Anteil aus konkreter Produkt-Wahl)
- **Timing-Effekt** (irrelevant bei strategischer SAA — wird mit 0
  ausgewiesen, dokumentiert dass aktives Timing nicht praktiziert wird)

Implementierung:
- `services/performance_attribution.py` (NEU): klassische
  Brinson-Hood-Beebower-Zerlegung gegen das aktuelle CMA-Set
- Neue Sektion im Advisory-Report unter „Asset Allocation" oder
  als eigene Karte
- Frontend: 3-Balken-Karte (AA / Selection / Timing-Anteil)

### E2 Sortino + Calmar zusätzlich zu Sharpe (Audit Top-9)
Heute liefert das CMA + Optimizer nur `expected_return_bps` und
`expected_vol_bps`. Ergänzen:
- **Sortino-Ratio** = `(ExpRet − RiskFree) / Downside-Vol`
- **Calmar-Ratio** = `ExpRet / |MaxDD|`
- **Rolling-Sharpe** (5-Jahres-Fenster, wenn historische Daten da)

Implementierung:
- `services/risk_metrics.py` (NEU): Sortino, Calmar, Rolling-Sharpe
- Aggregator-Sektion „Ausgangslage::key_metrics" um diese 3 Metriken
  erweitern
- Frontend: KPI-Karten zeigen sie als zusätzliche Zeile

### E3 Stress-Replay im Report (Audit Top-10)
Der Depot-Check hat **bereits Stress-Szenarien implementiert** (Sprint
U-P13: Dotcom 2000, GFC 2008, Covid 2020, Bonds-Crash 2022,
Stagflation 1973-74) — sind aber NICHT im Advisory-Report sichtbar.

Implementierung:
- `services/advisory_report.py::_build_stress_szenarien()` (NEU):
  ruft `compute_stress_replays(db, mandate)` aus dem bestehenden
  `services.backtest_stress` und packt es in eine neue Sektion
- Neue Sektion (vor Goal-Based oder eigenständig) mit Tabelle:
  | Szenario | Periode | Portfolio-Performance | MaxDD im Szenario |
- Frontend: Sektion mit dezenter Tabelle + Mini-Sparkline pro Szenario

### E4 ESG/SFDR-Aggregation
Produkt-Modell hat schon `sfdr_class` + `esg_rating` + `esg_score_x10`.
Aggregator nutzt es aber nicht.

Implementierung:
- `services/esg_aggregation.py` (NEU):
  - SFDR-Klassen-Anteil (Art. 6 / Art. 8 / Art. 9)
  - Gewichteter ESG-Score (0-100, MSCI-style)
  - Carbon-Intensity (wenn Produkt-Daten vorhanden — optional)
- Aggregator-Sektion „ESG-Profil" (NEU, zwischen Branchen und Goal-Based)
- Frontend: ESG-Donut + SFDR-Bar-Chart

### E5 Cashflow-Forecast-Waterfall (Audit „nice-to-have")
Multi-Jahre-Cashflow-Visualisierung:
- 10-Jahre Income vs. Ausgaben als Waterfall-Chart
- Differenz wird zum Beratungsvermögen addiert/abgezogen
- Goal-Termine als vertikale Marker

Implementierung:
- Daten kommen schon aus `services.cashflow_projection`
- Aggregator-Sektion „Cashflow-Vorausschau" (NEU)
- Frontend: Waterfall + Marker-Linien (Recharts oder D3)

---

## Bonus E6 (klein, schnell): Audit-Trail im Footer

Audit-Trail-Zeile im PDF/UI-Footer:
- "Datenquelle: TA v3, RiskAssessment v2, CMA 2026-Q1, Generiert 2026-05-25 14:32"
- Daten kommen aus den persistierten `version`-Feldern der Tabellen
- Aggregator-Sektion `audit_trail` (NEU, Schema-bump auf v3)

---

## Bonus E7: Glossar-Seite

1-Seiten-Glossar am Ende des Reports:
- Sharpe-Ratio, Sortino, Calmar, MaxDD, Risky Fraction, iSAA,
  Monte-Carlo-Simulation, SFDR-Klassen, GICS-Sektoren, HHI
- Statisch in Aggregator als 16. Sektion (oder Anhang vor Disclaimer)
- Wenn der Bericht zu mailbar Stück wird → wertvoller Kontext für den
  Endkunden

---

## PR-Aufteilung

| PR | Sprint-Teil | Aufwand |
|---|---|---|
| **PR A** | E1 Performance-Attribution | ~6h |
| **PR B** | E2 Sortino + Calmar + Rolling-Sharpe | ~3h |
| **PR C** | E3 Stress-Replay-Sektion | ~5h |
| **PR D** | E4 ESG/SFDR-Aggregation | ~6h |
| **PR E** | E5 Cashflow-Forecast + E6 Audit-Trail + E7 Glossar | ~8h |

---

## Inspirations-Quellen (Audit-Recherche)

- [UBS Global Family Office Report 2025](https://www.ubs.com/global/en/media/display-page-ndp/en-20250521-global-family-office-report-2025.html)
- [KPMG Private Banking Report 2025](https://assets.kpmg.com/content/dam/kpmg/lu/pdf/private-banking-survey-2025-secured.pdf)
- [CFA Institute ESG Performance Attribution](https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/rf-brief/Horan-ESG_RF_Brief_2022_Online.pdf)
- [Sia Partners Private Banking Reporting](https://www.sia-partners.com/en/insights/publications/private-banking-reporting-next-competitive-battleground)

---

## Acceptance

Nach U-P29 hat der Advisory-Report:
1. ✅ Performance-Attribution (Berater kann erklären woher die Rendite kommt)
2. ✅ Sortino + Calmar (klassische Risk-Adjusted-Metriken)
3. ✅ Stress-Replay (historische Szenarien sichtbar)
4. ✅ ESG-Profil (SFDR + MSCI-style ESG-Score)
5. ✅ Cashflow-Forecast-Waterfall (10-Jahre)
6. ✅ Audit-Trail im Footer
7. ✅ Glossar-Seite

→ **Niveau erreicht: Family-Office-Standard.**

---

## Verboten

- Keine Dritt-Marken in Code/Texten (Memory)
- Keine Garantieversprechen
- KEIN Refactoring bestehender Sektionen (additive only)
- Bei ESG: konservative Quelle (Produkt-Felder), KEIN Greenwashing-Text
