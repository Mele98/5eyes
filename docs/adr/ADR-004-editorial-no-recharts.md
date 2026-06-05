# ADR-004: Editorial-Design ohne Chart-Library

- **Status:** Accepted
- **Datum:** 2026-05-31
- **Sprint:** U-12 + U-14

## Kontext

Der Beratungsreport ist ein **Druck-Artefakt** — er liegt auf dem Tisch
zwischen Berater und Kunde. Default Wealth-Tech-Charts (Plotly, Chart.js,
recharts) sind für Web-Dashboards designed: bunte Tooltips, Hover-Effekte,
animierte Reveals. Auf Papier oder im PDF wirken sie billig.

5eyes hatte initial **recharts** für die Monte-Carlo-Pfade installiert.
Bundle-Cost: +5 KB JS + 2 moderate npm-vulns. Look: Web-typisch, nicht
Editorial.

## Entscheidung

Charts werden als **pure SVG** direkt im React-Component gezeichnet:

1. Fixe Pixel-Dimensionen (z.B. 720x320)
2. Editorial-Farben (matte, niedrige Sättigung)
3. Cormorant Garamond für Achsen-Labels + Inter für Werte
4. Keine Interaktion (Tooltip, Zoom, Pan) — Berater erklärt mündlich
5. Bands statt Konfidenz-Glow, gerade Linien statt Bezier-Kurven

Konkret: `MonteCarloPathsChart` in `src/components/charts/` rendert
p5-p75-Band + p50-Linie + Goal-Marker als reine `<svg><path/></svg>`.

## Konsequenzen

**Positiv:**
- recharts uninstalliert (U-14, PR #113): -5.4 KB JS, -2 npm-vulns
- 0 Imports von Chart-Libraries in `src/` — geprüft via Drift-Test
- SVG ist direkt PDF-fähig (kein Canvas-Screenshot nötig)
- Editorial-Look konsistent über alle Sektionen

**Negativ:**
- Jede neue Chart-Art = neuer SVG-Component (kein "fancy chart in 5 min")
- Komplexere Charts (Heatmap, Sankey) wären Eigenbau-Aufwand
- Keine Hover-Tooltips für Berater am Bildschirm — Trade-off akzeptiert

**Geltungsbereich:**
- Gilt für **Reporting Sub-App** (`5eyes-electron/frontend/reporting/`)
- Hauptapp (`5eyes-electron/frontend/5eyes_v2.html`) ist davon ausgenommen —
  dort sind Web-Charts okay (Berater-Workflow, nicht Druck-Surface)
- DESIGN_SYSTEM.md (`frontend/reporting/DESIGN_SYSTEM.md`) hält die
  Tokens (Farben, Schriften, Spacing)

**Drift-Schutz:**
- Lint/Test prüft dass `node_modules/recharts` nicht reinkommt
- Drift-Test pinnt erwartete Chart-Components → kein "schnell ein
  Plotly für die Demo"
