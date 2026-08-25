# Codex-Sprint U-P25 — Advisory-Report Frontend Phase 3 (Sektionen 11-15, finaler Frontend-Sprint)

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25.
> **Voraussetzung:** U-P23 + U-P24 gemerged. Dies ist der **abschliessende
> Frontend-Sprint** — danach sind alle 15 Sektionen sichtbar.
> **Größenordnung:** ~10-13 Stunden, 4 PRs.

---

## Voraussetzung — bitte lesen

- `docs/planning/2026-05-25-codex-sprint-u-p23-advisory-frontend-phase1.md`
  (Sektionen 2-5, Foundation)
- `docs/planning/2026-05-25-codex-sprint-u-p24-advisory-frontend-phase2-charts.md`
  (Sektionen 6-10, Charts-Foundation)
- `docs/planning/2026-05-25-codex-sprint-u-p28-mandate-report-notes.md`
  (Berater-Override-Mechanismus, blockiert NICHT — Sektion 15 wird
  optional drauf integriert)

---

## Ziel dieses Sprints

Die **letzten 4 Sektionen** (11 ist bereits Teil von U-P24 — Goal-Based)
werden als React-Komponenten implementiert. **Damit erreichen wir 15/15
Sektionen visuell sichtbar** und der visuelle Report ist komplett.

---

## Sektionen im Detail (in neuer Reihenfolge per U-P23)

### Sektion 12 — Risikoprofilierung

**Datenquelle:** `data.risikoprofilierung` mit:
- `risky_fraction_bps`
- `risk_capacity_score_x10`
- `risk_willingness_score_x10`
- `final_score_x10`
- `final_profile` (z.B. „Defensiv")
- `is_overridden` + `override_reason`
- `questions[]` (8 Standard-Fragen)

**Layout:**
- Sektion-Titel „Risikoprofilierung"
- Sub-Titel „Risikofähigkeit · Risikobereitschaft · Risky Fraction"

- **Score-Block oben (3 horizontale Bars):**
  ```
  Risikofähigkeit (Capacity)    ████████░░░░  X von 100
  Risikobereitschaft (Willingness) ██████░░░░░░  Y von 100
  Finaler Score                  ███████░░░░░  Z von 100   → Profil: <final_profile>
  ```
  - Bars sind dezent (3mm Höhe, rounded-pill)
  - Score-Werte rechts in Mono-Font
  - **Massgebend ist der niedrigere Wert** (Spec-Hinweis aus User-
    Wunschliste 2026-05-24) — Mini-Annotation dezent

- **Override-Hinweis falls `is_overridden=true`:**
  Petrol-Border-left-Box mit „Risiko-Override aktiv: <override_reason>"

- **Risky-Fraction-Bar separat:**
  ```
  Aktuelle Risikoquote (Risky Fraction)
  ░░░░░░░██████████░░░░░░░░░░░░░░  X.X%   [Limit 40% Defensiv]
  ```
  Mit visueller Limit-Markierung (vertikale Linie)

- **8 Standard-Fragen als Mini-Tabelle:**
  | Frage | Punkte (0-4) |
  | Anlagehorizont | ●●●○ 3 |
  | Liquiditätsreserve | ●●●● 4 |
  | ... |

  Punkte als 4-Punkte-Anzeige (gefüllt = aktiv).

**Komponente:** `src/pages/Risikoprofilierung.tsx`

### Sektion 13 — Building Blocks / iSAA

**Datenquelle:** `data.building_blocks` mit:
- `blocks[]` (5 Anlageklassen mit target_bps, band_min_bps, band_max_bps)
- `constraints[]` (z.B. Max-Risky-Fraction)
- `methodologie` (langer Text-Block)

**Layout:**
- Sektion-Titel „Building Blocks · Institutionelle SAA"
- Sub-Titel „Strategische Allokation auf Anlageklassen-Ebene"

- **Tabelle 5 Anlageklassen:**
  | Anlageklasse | Target | Min | Max | Band-Visualisierung |
  | Aktien | 55.0% | 50.0% | 60.0% | `[───●───]` |
  | ...

  „Band-Visualisierung" ist eine horizontale Skala 0-100% mit:
  - Grauem Band zwischen min und max
  - Petrol-Punkt am Target

- **Constraints-Liste:**
  - Bullet-Liste der `constraints[]` mit Label, Wert und Beschreibung
  - z.B. „Maximale Risikoquote: 40% — Obergrenze für den Anteil risiko-
    behafteter Anlagen gemäss FINMA-Eignungsprüfung"

- **Methodologie-Block unten:**
  - Editorial-Textblock (10pt, line-height 1.55)
  - Petrol-Border-left
  - Beschreibung der iSAA-Logik

**Komponente:** `src/pages/BuildingBlocks.tsx`

### Sektion 14 — Statement aus dem Portfoliomanagement

**Datenquelle:** `data.statement_pm.principles` (7 Investmentgrundsätze
mit `key`, `title`, `body`).

**Layout:**
- Sektion-Titel „Statement aus dem Portfoliomanagement"
- Sub-Titel „Unsere Grundsätze"

- **7 Prinzipien als Editorial-Liste:**
  - Jeder Block in einer eigenen Sub-Section:
    - Akzent-Punkt (5mm Petrol-Kreis links)
    - Titel (h2, Serif, ~16pt)
    - Body (10pt, line-height 1.55, max-width für Lesbarkeit)
    - Dezente horizontale Trenn-Linie zum nächsten Prinzip
- Editorial-Stil: viel Whitespace, lange Zeilen für Lesefluss

**Komponente:** `src/pages/StatementPm.tsx`

### Sektion 15 — Weiteres Vorgehen

**Datenquelle:** `data.weiteres_vorgehen` mit:
- `block_optimierungen`
- `block_zielstrategie`
- `offene_fragen[]`
- `naechster_termin`
- `todos[]`
- `dokumente[]`

**Hinweis zu Berater-Overrides:**
Diese Sektion ist der **Haupt-Use-Case für U-P28** (MandateReportNotes).
Sobald U-P28 gemerged ist, kommen die Texte aus den Berater-Eingaben
statt aus den Platzhaltern. Frontend-Komponente in U-P25 muss **beide
Modi** handhaben:
- Wenn Texte = Default-Platzhalter („Vom Berater zu ergänzen ..."):
  dezent ausgegraut (text-ink-subtle italic) mit ✎-Edit-Button
- Wenn Berater-Override gesetzt: voller text-ink, „Bearbeitet"-Tag oben rechts

**Layout:**
- Sektion-Titel „Weiteres Vorgehen"
- **2 grosse Text-Blöcke nebeneinander (50/50 Grid):**
  - Links: „Mögliche Optimierungen" (block_optimierungen)
  - Rechts: „Zielstrategie und Umsetzung" (block_zielstrategie)
  - Beide als Editorial-Blocks mit Petrol-Border-left

- **Drei Listen darunter (3-Spalten-Grid):**
  - „Offene Fragen" (Bullet-Liste aus offene_fragen[])
  - „Aufgaben" (Bullet-Liste aus todos[])
  - „Dokumente" (Bullet-Liste aus dokumente[])
  - Bei leeren Listen: dezenter „— keine Einträge —" Hinweis

- **Termin-Hinweis dezent oben rechts:**
  „Nächster Termin: {naechster_termin}" — als Pill, Petrol-Outline

- **Unterschriften-Block ganz unten:**
  - 2-Spalten: Berater (links) + Kunde (rechts)
  - Jeweils: Name-Linie, Ort/Datum-Linie, Unterschrift-Linie (75mm)
  - Im UI sichtbar als Hint („wird beim Druck eingesetzt"),
    im PDF als echte Linien

**Komponente:** `src/pages/WeiteresVorgehen.tsx`

---

## Verbesserung am Rande

### Sticky-Sidebar-Komponente (aus U-P23 PR C) erweitern

Nach U-P25 hat die Sidebar alle 15 Sektionen sichtbar. Optionale
Verbesserungen:

- **Scroll-Spy-Indikator:** aktive Sektion wird hervorgehoben (Petrol-
  Border-left + Text-ink statt text-ink-subtle)
- **Fortschritts-Pille oben:** „Sektion 11 von 15" als Mini-Caption
- **Print-Button** in Sidebar: ruft `window.print()` für die aktuelle
  Sektion ODER alle Sektionen (Sidebar wird im Print mit
  `display: none` ausgeblendet)

---

## PR-Aufteilung

| PR | Inhalt | Aufwand |
|---|---|---|
| **PR A** | Sektion 12 Risikoprofilierung (Score-Bars + 8 Fragen + Risky-Fraction-Bar) | ~3h |
| **PR B** | Sektion 13 Building Blocks (Tabelle + Band-Visualisierung + Methodologie) | ~3h |
| **PR C** | Sektionen 14 + 15 (Statement PM + Weiteres Vorgehen) | ~4h |
| **PR D** | Sidebar-Polish (Scroll-Spy, Print-Button, Progress) | ~2h |

---

## Tests

`tests/test_reporting_frontend_phase3.py` (NEU, ~15 Tests):
- Pro Sektion: Datei existiert, Pflicht-Felder gerendert
- Score-Bars für Risikoprofilierung
- Band-Visualisierung für Building Blocks
- 7 Prinzipien für Statement
- Beide Edit-Modi für Weiteres Vorgehen (Default vs. Override)
- App.tsx hat alle 15 Routes
- Branding-Compliance
- data-testids

---

## Wichtig / Verboten

- KEINE Dritt-Marken
- KEINE Garantieversprechen (im Statement-Text gerade besonders heikel)
- KEIN Refactoring von `BarChartIstSoll` (U-P23 PR E, stabil)
- KEIN automatisches PUT für Weiteres-Vorgehen-Overrides (in U-P25 nur
  Render — Edit-Drawer kommt mit U-P28)

---

## Acceptance

1. Berater navigiert in Sidebar zu Sektionen 12 → 15
2. Sektion 12: 3 Score-Bars sichtbar, Risky-Fraction-Bar mit Limit-Marker,
   8 Fragen-Tabelle, Override-Hinweis bei is_overridden=true
3. Sektion 13: 5-Bucket-Tabelle mit Band-Visualisierung, Constraints-Liste,
   Methodologie-Block
4. Sektion 14: 7 Investmentgrundsätze als Editorial-Liste, Akzent-Punkte
5. Sektion 15: 2-Blöcke + 3-Listen + Termin-Pill + Unterschriften-Block
6. Bei Default-Platzhaltern in Sektion 15: dezent ausgegraut mit Edit-Hint
7. Sidebar zeigt jetzt 15 Sektionen, Scroll-Spy aktiv

**Total nach U-P25:** 15/15 Sektionen sichtbar im Frontend.
**Volle Pipeline-Sicht:** Bericht ist visuell komplett.

---

## Was kommt direkt nach U-P25

| Sprint | Inhalt |
|---|---|
| **U-P26** | Server-PDF (ReportLab) — spiegelt das Frontend 1:1 |
| **U-P28** | MandateReportNotes (Berater-Overrides für Sektion 15) |
| **U-P29** | State-of-the-art-Ergänzungen (Performance-Attr, Sortino, Stress-Replay, ESG, Cashflow-Waterfall, Audit-Trail, Glossar) |
| **U-P30** | Ausgangslage-Felder ableiten (Audit §3.1-Fix) |
| **U-P27** | Electron-Window-Integration (Production-Polish) |

**Damit ist die Pipeline post-Audit komplett geplant.**
