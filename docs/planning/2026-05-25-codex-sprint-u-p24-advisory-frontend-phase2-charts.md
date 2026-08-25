# Codex-Sprint U-P24 — Advisory-Report Frontend Phase 2 (Sektionen 6-10 + Charts)

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25.
> **Voraussetzung:** U-P23 fertig (alle 5 PRs A-E gemerged). Insbesondere
> PR E (`BarChartIstSoll` + `chartTheme.ts`) ist die Foundation für diesen
> Sprint.
> **Größenordnung:** ~13-18 Stunden, 5 PRs.

---

## Voraussetzung

1. **Lies zuerst:**
   - `docs/audits/2026-05-25-advisory-report-audit.md`
   - `docs/planning/2026-05-25-codex-sprint-u-p23-advisory-frontend-phase1.md`
     (= dein vorheriger Sprint, dessen Komponenten + Tokens du
     wiederverwendest)

2. **State-of-the-art im Hinterkopf** (siehe Audit §4.2 + Anhang A):
   - Charts: clean, dünne Linien, KEINE 3D, KEINE Schatten, kein Retailbank-Look
   - **Editorial Layout** mit viel Whitespace
   - Print-Vorschau muss identisch zur Bildschirm-Ansicht sein
   - Heart of the report (Sektion 10 Goal-Based) braucht **Monte-Carlo-Bänder**

---

## Ziel dieses Sprints

Berater sieht in seiner Reporting-App die 5 Sektionen 6-10. Davon sind 3
Sektionen (8, 9, 10 nach neuer Nummerierung) Charts-driven — das war
der explizite Berater-Wunsch („Ich wäre unbedingt bei den Länder, Branchen
usw Balkendiagramme hätte").

---

## Sektionen im Detail (in neuer Reihenfolge per U-P23)

### Sektion 6 — Was wir im Depotcheck prüfen

**Datenquelle:** `data.pruefpunkte.bloecke` (10 statische Blöcke aus dem
Backend-Aggregator).

**Layout (Editorial):**
- Sektion-Titel „Was wir im Depotcheck prüfen" (H1, Serif)
- Sub-Titel „Strukturierte Analyse-Bereiche" (italic, kursiv)
- 10 Blöcke in **2-Spalten-Grid** (5 × 2)
- Pro Block:
  - Akzent-Punkt (4mm Petrol-Kreis) oben links
  - Titel (h3, Sans-bold)
  - Beschreibung (caption, 4-5 Zeilen, text-ink-muted)
- Dezente `border-rule` (0.5pt) um jeden Block
- Hover: subtle Hintergrund (canvas-subtle)

**Komponente:** `src/pages/Pruefpunkte.tsx`
**Tests:**
- Datei existiert
- 10 Blöcke gerendert
- alle keys sichtbar
- Branding-Compliance

### Sektion 7 — Erkenntnisse (Ampel)

**Datenquelle:** `data.erkenntnisse.checks` (9 Checks aus Ampel-Logik).

**Layout:**
- Sektion-Titel „Erkenntnisse aus dem Depotcheck"
- **Zusammenfassungs-Zeile oben:** „Ihr Depotcheck: X grün · Y gelb · Z rot · W nicht beurteilbar"
- **Tabelle 4 Spalten:** Prüfpunkt | Bewertung (Ampel-Pill) | Beurteilung | Handlungsempfehlung
- Ampel-Pills (rounded-pill, micro-caps, 4 Farben):
  - GRÜN → status-gruen
  - GELB → status-gelb
  - ROT → status-rot
  - NICHT BEURTEILBAR → status-neutral
- Bei `ist_basiert_auf_soll=true` (aus U-P23 PR B): Editorial-Banner oben:
  „Datenstand: SOLL — IST wird ausserhalb des Systems erfasst. Drift-
  Werte werden in einer späteren Bericht-Version ergänzt."

**Komponente:** `src/pages/Erkenntnisse.tsx`
**Wichtig:** Hover über eine Zeile zeigt einen kleinen Tooltip mit
„zugrundeliegendem Schwellwert" (z.B. „Diversifikation: HHI ≥ 2500 = rot").
Die Schwelle-Werte aus der Aggregator-Spec lesen.

### Sektion 8 — Asset Allocation (CHART!)

**Datenquelle:** `data.asset_allocation` (5 Buckets: liquidity, bonds,
equities, real_estate, alternatives).

**Layout:**
- Sektion-Titel „Asset Allocation"
- **Editorial-Hinweis-Banner** oben falls `ist_basiert_auf_soll=true`
- **Links (60% width):** `<BarChartIstSoll items={data.asset_allocation.items} />`
- **Rechts (40% width):** `anmerkungen`-Box als Editorial-Block mit
  Petrol-Border-left (3pt)
- Unten: kleine Zusammenfassungs-Zeile mit den 3 wichtigsten Drift-Punkten

**Komponente:** `src/pages/AssetAllocation.tsx`
**Reuse:** `BarChartIstSoll` aus U-P23 PR E.

### Sektion 9 — Risikowährungen (CHART!)

**Datenquelle:** `data.risikowaehrungen` (7 Kategorien: CHF, USD, EUR,
GBP, JPY, EM FX, Andere).

**Layout:** identisch zu Sektion 8, anderer Datensatz.
- Links: `<BarChartIstSoll items={data.risikowaehrungen.items} />`
- Rechts: `erklaerung`-Box

**Komponente:** `src/pages/Risikowaehrungen.tsx`

### Sektion 10 — Diversifikation Branchen (CHART!)

**Datenquelle:** `data.branchen` (11 GICS-Sektoren + Übrige).

**Layout:** ähnlich Sektion 8.
- Wichtig: **`anteil_aktien_bps`-Hinweis** aus U-P23 PR B oben anzeigen
  („Sektor-Verteilung basiert auf X% Aktien-Allokation des Beratungsvermögens.
  Bonds + Liquidität + Immobilien werden separat ausgewiesen.")
- Links: `<BarChartIstSoll items={data.branchen.items} />`
- Rechts: `analyse`-Box

**Komponente:** `src/pages/Branchen.tsx`

### Sektion 11 — Goal-Based Investing (HERZSTÜCK!)

**Datenquelle:** `data.goal_based_investing` (goals[], goal_achievement_score_bps,
monte_carlo_paths).

**Layout (besondere Aufmerksamkeit):**
- Sektion-Titel „Zielbasierte Optimierung"
- Sub-Titel „Das Herzstück der strategischen Anlageberatung"
  (italic, Petrol)

**Wenn `monte_carlo_paths.data_pending=false`:**
- **Großer Monte-Carlo-Chart** oben (Width 100%, Height ~280px):
  - 3 Linien (Recharts `LineChart`):
    - p5 (5. Perzentil, dünne graue Linie)
    - p50 (Median, Petrol-Linie, **2pt-stroke**)
    - p75 (75. Perzentil, dünne graue Linie)
  - Optional: `Area` zwischen p5 und p75 mit `alpha=0.08` Petrol-Füllung
    (gibt den charakteristischen „MC-Band"-Look)
  - X-Achse: Jahre (z.B. 2026 → 2046)
  - Y-Achse: Vermögen in CHF (Schweizer Format mit Apostroph)
  - Tooltip: zeigt für jeden Jahr-Punkt die 3 Werte
- **Goal-Achievement-Donut** rechts daneben (Recharts `PieChart` mit
  `innerRadius=60%`):
  - Center-Text: `goal_achievement_score_bps / 100 + "%"` (z.B. „85%")
  - Donut-Ring zeigt den Anteil
  - Drumherum Petrol-Halo

**Wenn `monte_carlo_paths.data_pending=true`:**
- Editorial-Box mit Hinweis: „Monte-Carlo-Pfade werden bei der nächsten
  Bericht-Generierung berechnet (rechenintensiv, ~8 s)"
- Plus: „Berechnung anstoßen"-Button → ruft Backend-Endpoint
  `/mandates/{id}/advisory-report?compute_mc=true` (kommt in U-P24 PR B)
- Donut bleibt sichtbar mit aktuellem Score (oder „—" wenn Score=0)

**Unten:** Tabelle der Goals mit Spalten:
- Goal-Label
- Goal-Typ
- Zielbetrag (Schweizer Format)
- Ziel-Datum
- Hardness (hart/primär/opportunistisch — als Mini-Pill)
- P(Erreichung) als Mini-Bar (0-100%)
- Status (erreichbar/knapp/nicht erreichbar — als Pill)

**Komponente:** `src/pages/GoalBasedInvesting.tsx`

---

## Backend-Ergänzung: Monte-Carlo on-demand

**PR B (Backend):**
- Endpoint-Parameter `?compute_mc=true|false` (default false)
- Wenn true: `_build_goal_based_investing()` ruft eine neue Funktion
  `services.mc_engine.compute_paths_for_mandate(db, mandate)` die:
  - Aus der aktuellen TA + CMA Monte-Carlo-Pfade simuliert (5000 Pfade,
    20 Jahre, p5/p50/p75)
  - Resultat in den `monte_carlo_paths`-Block schreibt
  - **NICHT** persistiert (das käme in U-P29 oder U-P31)

**Acceptance:** Test ohne `?compute_mc=true` liefert `data_pending=true`,
mit dem Parameter liefert echte Pfade (Performance: < 15 s).

---

## PR-Aufteilung

| PR | Inhalt | Aufwand |
|---|---|---|
| **PR A** | Sektionen 6 + 7 (Pruefpunkte + Erkenntnisse mit Ampel-Tabelle) | ~3h |
| **PR B** | Backend MC-Endpoint-Parameter + Sektion 10 Goal-Based mit Stub-Behandlung | ~5h |
| **PR C** | Sektion 8 Asset Allocation (BarChartIstSoll-Integration) | ~2h |
| **PR D** | Sektion 9 + 10 (Währungen + Branchen — gleicher Pattern wie PR C) | ~2h |
| **PR E** | Sektion 11 Goal-Based Echo-Komponenten (MC-Chart + Donut) | ~3h |

---

## Tests

`tests/test_reporting_frontend_phase2.py` (NEU, ~18 Tests):
- Pro Sektion: Datei existiert, Pflicht-Felder gerendert
- BarChartIstSoll wird in AA/Risikowährungen/Branchen verwendet
- Goal-Based: MC-Chart rendert wenn data_pending=false
- Donut zeigt goal_achievement_score korrekt
- App.tsx hat alle 11 Routes (statt 5 aus U-P23)
- Branding-Compliance
- data-testids

---

## Wichtig / Verboten

- KEINE Dritt-Marken
- KEIN Refactoring der `BarChartIstSoll`-Komponente (aus U-P23 PR E,
  stabil halten)
- KEINE 3D-Charts, KEINE Schatten, kein Gradient-Hintergrund
- KEIN Auto-Polling für MC-Berechnung (User triggert via Button)
- KEIN Persistenz der MC-Pfade (kommt in U-P29 oder U-P31)

---

## Acceptance

1. Berater navigiert in Sidebar zu Sektion 6 → 10 Blöcke „Was wir prüfen"
2. Sektion 7 → Ampel-Tabelle mit Pills, Zusammenfassung oben
3. Sektion 8 → BarChartIstSoll mit 5 Buckets, Anmerkungs-Box rechts
4. Sektion 9 → BarChartIstSoll mit 7 Währungs-Kategorien
5. Sektion 10 → BarChartIstSoll mit 11 GICS-Sektoren + Aktien-Anteil-Hinweis
6. Sektion 11 → entweder MC-Chart mit 3 Linien (wenn berechnet) oder
   Stub mit „Berechnung anstoßen"-Button
7. Goal-Achievement-Donut zeigt korrekten Score
8. Goals-Tabelle mit allen 4 Beispiel-Goals

**Total:** nach U-P24 sind 11/15 Sektionen sichtbar.
