# Codex-Sprint U-P26 — Advisory-Report Server-PDF (institutionelles Layout)

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25.
> **Voraussetzung:** Sprint U-P23 + U-P24 + U-P25 (Frontend Sektionen 1-15)
> sind gemerged. PDF spiegelt das Frontend-Layout 1:1, damit Berater den
> identischen Bericht sowohl als Web-App als auch als gedrucktes Dokument
> erhält.
> **User-Direktiven:** „Schaue zusätzlich das das Design des PDF super
> ist". Editorial Niveau, Family-Office-Standard, KEIN Retailbank-Look.

---

## Voraussetzung — bitte ZUERST lesen

1. **Bestehende PDF-Pipeline lesen**, damit du die Konventionen kennst:
   - `services/pdf/base.py` — `PDFContext`, `make_paragraph_styles()`, Pixel-Tokens
   - `services/pdf/documents/anlagestrategie.py` — exemplarisch wie ein
     Multi-Sektion-PDF heute aufgebaut ist
   - `services/pdf/documents/depotcheck.py` — der heutige Depot-Check-PDF
     (wird durch das Advisory-Report-PDF in U-P27 ersetzt)
   - `services/pdf/components/` — wiederverwendbare Building-Blocks
     (`header.py`, `unterschrift.py`, `goal_achievability.py`, etc.)

2. **Audit-Bericht lesen:**
   `docs/audits/2026-05-25-advisory-report-audit.md`

3. **Frontend-Spec (U-P23):**
   `docs/planning/2026-05-25-codex-sprint-u-p23-advisory-frontend-phase1.md`
   → das PDF spiegelt diese Sektion-Reihenfolge + Layouts.

4. **Original-Wunschliste des Beraters** (siehe Spec-Datei U-P21 §"User-
   Spec"):
   - Swiss Private Banking Look
   - Institutional Editorial Layout
   - Serif Headlines (Cormorant Garamond), Sans Body (Inter)
   - Offwhite (#FAFAF6), Navy (#0F1C2E), Petrol (#2C5F5F), Mattes Gold (#B39455)
   - **Print-ready identisch zur Bildschirm-Ansicht**
   - Editorial Layout, viel Whitespace, dünne Linien
   - Charts: clean, dünne Linien, KEINE 3D-Effekte, KEINE Schatten

---

## Ziel dieses Sprints

Ein einzelner Endpunkt **`GET /mandates/{id}/reports/advisory-report.pdf`**
liefert ein 15-Seiten institutionelles A4-PDF mit identischem Layout zur
React-Sub-App. Berater kann das PDF herunterladen, ausdrucken oder dem
Kunden mailen — der visuelle Eindruck ist identisch zum digitalen
Bericht.

---

## Architektur

```
services/pdf/documents/advisory_report.py    ← NEU (Haupt-Komposition)
  build_advisory_report_flowables(ctx, data)
    Sektion 1 → uses pdf/components/cover_page.py            (NEU)
    Sektion 2 → uses pdf/components/disclaimer_page.py       (NEU)
    Sektion 3 → uses pdf/components/toc_page.py              (NEU)
    Sektion 4 → uses pdf/components/ausgangslage_page.py     (NEU)
    Sektion 5 → uses pdf/components/positionen_page.py       (NEU)
    Sektion 6 → uses pdf/components/pruefpunkte_page.py      (NEU)
    Sektion 7 → uses pdf/components/erkenntnisse_page.py     (NEU, mit Ampel-Pills)
    Sektion 8 → uses pdf/components/bar_chart_ist_soll.py    (NEU, für AA)
    Sektion 9 → reuses bar_chart_ist_soll                    (für Währungen)
    Sektion 10 → reuses bar_chart_ist_soll                   (für Branchen)
    Sektion 11 → uses pdf/components/goal_based_page.py      (NEU, mit MC-Bändern)
    Sektion 12 → uses pdf/components/risikoprofil_page.py    (NEU, mit Score-Bars)
    Sektion 13 → uses pdf/components/building_blocks_page.py (NEU)
    Sektion 14 → uses pdf/components/statement_pm_page.py    (NEU, statisch)
    Sektion 15 → uses pdf/components/vorgehen_page.py        (NEU, Berater-Overrides)

  Plus shared:
    pdf/components/page_header.py    (NEU, Wordmark + Seitenzahl)
    pdf/components/page_footer.py    (NEU, Audit-Trail + Generated-At)
    pdf/components/swiss_numbers.py  (NEU, Apostroph-Trenner — selber Helper wie Frontend)
```

---

## Teil A — Daten-Konsumierung

Das PDF konsumiert **dieselbe JSON-Struktur** wie das Frontend (Schema
v2 aus U-P23):

```python
def render_advisory_report_pdf(db: Session, mandate: Mandate, advisor: User) -> bytes:
    from services.advisory_report import compute_advisory_report
    payload = compute_advisory_report(db, mandate, advisor=advisor)
    ctx = PDFContext(
        base_currency=str(getattr(mandate, "base_currency", "CHF")),
        page_size=A4,
        margins=PDFMargins(...)
    )
    return render_pdf(ctx, payload)
```

→ Keine Duplikat-Berechnung. Single-Source-of-Truth.

### Endpoint

In `routers/pdf_reports.py` neu:

```python
@router.get(
    "/mandates/{mandate_id}/reports/advisory-report.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_advisory_report_pdf(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """U-P26: Institutioneller 15-Seiten Advisory-Report als PDF.

    Spiegelt exakt das React-Layout (5eyes-electron/frontend/reporting/).
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    pdf_bytes = render_advisory_report_pdf(db, mandate, current_user)
    filename = f"advisory-report-{mandate.mandate_number}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

---

## Teil B — Layout-Disziplin (Print + Editorial)

### A4-Format
- Page: 210 × 297 mm
- Margins: oben 25mm, unten 25mm, links 20mm, rechts 20mm (= editorial,
  nicht eng)
- Body: Inhaltsbereich ~170 × 247 mm

### Typografie
- **Headlines**: Cormorant Garamond (System-Fallback: Source Serif Pro,
  Georgia)
- **Body**: Inter (System-Fallback: Source Sans Pro, Helvetica)
- **Monospace** (Tabellen-Zahlen): JetBrains Mono / Consolas
- Hierarchie:
  - `display` 28pt (Cover-Titel)
  - `h1` 20pt (Sektion-Titel)
  - `h2` 14pt (Sub-Sektion)
  - `body` 10pt (Body-Text)
  - `caption` 9pt (Tabellen, Hilfslabel)
  - `micro` 7pt (Footer, Audit-Trail)

### Farben (identisch zu Frontend `tokens.ts`)
```python
COLOR_CANVAS    = HexColor('#FAFAF6')
COLOR_INK       = HexColor('#0F1C2E')
COLOR_INK_MUTED = HexColor('#3B475A')
COLOR_ACCENT    = HexColor('#2C5F5F')   # Petrol
COLOR_RULE      = HexColor('#E5E4DE')
COLOR_GOLD      = HexColor('#B39455')
COLOR_STATUS_GRUEN = HexColor('#4E6F58')
COLOR_STATUS_GELB  = HexColor('#B59243')
COLOR_STATUS_ROT   = HexColor('#9E4747')
COLOR_STATUS_NEUTR = HexColor('#7A8395')
```

Diese Konstanten in eine neue Datei
`services/pdf/components/advisory_palette.py` damit auch andere
Dokumente sie nutzen können.

### Page-Header (auf jeder Seite ab Seite 2)
```
┌─────────────────────────────────────────────────────────────────┐
│ 5eyes                                                  Seite x  │
│ Wealth Architects · Depotcheck · MX-FOUNDATION-01      von 15   │
│ ──────────────────────────────────────────────────── (rule)     │
│                                                                 │
│   [Sektion-Inhalt]                                              │
```

### Page-Footer (auf jeder Seite ab Seite 2)
```
│   [Sektion-Inhalt]                                              │
│                                                                 │
│ ──────────────────────────────────────────────────── (rule)     │
│ Vertraulich · Generiert 25.05.2026 14:32         5eyes v0.X     │
└─────────────────────────────────────────────────────────────────┘
```

### Sektion-Beginn-Pattern
Jede Sektion startet **auf einer neuen Seite** (`PageBreak()`).
Sektion-Titel groß, Sub-Titel kursiv darunter, dann eine dezente
Trenn-Linie, dann der Inhalt.

---

## Teil C — Pro Sektion (15 Pages, exakt nach neuer Reihenfolge)

### Seite 1 — Cover (Sektion 1)
- Wordmark oben links, "Wealth Architects" oben rechts (micro-Caps)
- Mitte: Display-Titel "Depotcheck" + Subtitle "Strategische
  Portfolioanalyse" in serif italic
- Unterer Drittel: 2×2 Grid: Kundin/Kunde, Mandat-Nr., Berater,
  Berichtsdatum
- KEINE Page-Header/Footer auf Cover
- Datum im Schweizer Format DD.MM.YYYY

### Seite 2 — Disclaimer (Sektion 2)
- Sektion-Titel "Rechtliche Hinweise" (h1)
- 7 Hinweise aus `disclaimer.hinweise` als nummerierte Liste
- Schriftgröße 9pt (kleiner als Body), 1.4 line-height
- Sollte auf 1 Seite passen
- Page-Header beginnt hier (Seite 2 von 15)

### Seite 3 — Inhaltsverzeichnis (Sektion 3)
- Sektion-Titel "Inhaltsverzeichnis"
- 12 Kapitel aus `inhaltsverzeichnis.kapitel`
- Layout: `Nr. (mono)  ·  Kapitel-Name  ·  ......................  ·  Seite N`
- Dünne horizontale Trenn-Linie zwischen Kapiteln
- Berechne Seitenzahlen dynamisch (jeder Kapitel ist 1+ Seiten — Tabelle
  mit Page-Offsets pflegen, siehe Teil F)

### Seite 4-N — Ausgangslage (Sektion 4)
- Sektion-Titel "Ausgangslage"
- Layout 2-Spalten:
  - Links: 7 Felder aus `client_info` (Alter, Anlagehorizont,
    Risikoprofil, Anlageziel, Liquiditätsbedarf, Steuerdomizil,
    Referenzwährung) — Label-Wert-Paare
  - Rechts: `wealth_summary` — 5 Vermögenskategorien (gesamtvermoegen
    bis kredite) als Mini-Tabelle mit Schweizer Number-Format
- Unten: 6 KPI-Karten (Risky Fraction, Zielerreichung, exp Vol/Return,
  Max DD, VaR 95) als horizontale 6er-Reihe (jeder Karte ~28mm breit)
- Bei null-Werten "—" rendern (nie 0)
- Plus: Cashflows-Tabelle (separate Sub-Seite) und Goals-Tabelle
  (weitere Sub-Seite) falls > 3 Einträge

### Seite N — Übersicht Positionen (Sektion 5)
- Sektion-Titel "Übersicht Ihrer Positionen"
- 5 institutionelle Tabellen (eine pro Anlageklasse):
  - Spalten: ISIN | Produkt | Sub-Asset-Class | Währung | Marktwert CHF
    | Anteil % | TER %
  - Header in Petrol-Akzent, Body in Ink
  - Dünne Linien, sparsames Padding (kein Excel-Look)
  - Zeilen-Höhe ~7mm
- Total-Zeile am Ende jeder Tabelle (bold, mit `rule strong` Border)
- Falls Gruppe leer: dezentes "— keine Positionen —" statt leere Tabelle
- Bei `has_recommendation_run=false`: prominenter Editorial-Banner oben

### Seite N — Was wir prüfen (Sektion 6)
- Sektion-Titel "Was wir im Depotcheck prüfen"
- 10 Blöcke aus `pruefpunkte.bloecke` als 2-Spalten-Grid (5 × 2)
- Jeder Block: kleiner Akzent-Punkt, Titel (h3), Beschreibung (caption)
- Dezente Border um jeden Block (rule, 0.5pt)

### Seite N — Erkenntnisse (Sektion 7)
- Sektion-Titel "Erkenntnisse aus dem Depotcheck"
- Tabelle 4 Spalten: Prüfpunkt | Bewertung (Ampel-Pill) | Beurteilung |
  Handlungsempfehlung
- Ampel-Pills: kleine farbige Rounded-Rectangles mit Caption-Text:
  - gruen → COLOR_STATUS_GRUEN
  - gelb → COLOR_STATUS_GELB
  - rot → COLOR_STATUS_ROT
  - nicht_beurteilbar → COLOR_STATUS_NEUTR
- Plus: oben am Sektion-Beginn eine Zeile mit Zähler:
  "Ihr Depotcheck: X grün, Y gelb, Z rot, W ohne Beurteilung"

### Seite N — Asset Allocation (Sektion 8)
- Sektion-Titel "Asset Allocation"
- `BarChartIstSoll`-Komponente (siehe Teil D) für die 5 Buckets
- Rechts daneben: `anmerkungen`-Box als Editorial-Block
- `ist_basiert_auf_soll`-Hinweis oben (falls Flag aus U-P23 true)

### Seite N — Risikowährungen (Sektion 9)
- Sektion-Titel "Risikowährungen"
- `BarChartIstSoll` für 7 Berichts-Kategorien (CHF, USD, EUR, GBP, JPY,
  EM FX, Andere)
- Rechts: `erklaerung`-Box

### Seite N — Diversifikation Branchen (Sektion 10)
- Sektion-Titel "Diversifikation Branchen"
- `BarChartIstSoll` für 11 GICS-Sektoren
- Plus: `hinweis` aus dem neuen U-P23-Backend-Fix
  ("Sektor-Verteilung basiert auf X% Aktien-Allokation")
- Rechts: `analyse`-Box

### Seite N — Goal-Based Investing (Sektion 11)
- Sektion-Titel "Zielbasierte Optimierung"
- **Herzstück:** Monte-Carlo-Pfade als Plot (3 Linien: p5/p50/p75 über
  Zeitachse)
  - Wenn `data_pending=true` (kein MC berechnet): Platzhalter-Box mit
    klarem Hinweis "Monte-Carlo-Pfade werden bei nächster Bericht-
    Generierung berechnet"
- Darunter: Goal-Achievement-Score als Donut (1 grosser Anteils-Donut)
- Darunter: Tabelle der Goals mit P(Erreichung), Status, Hardness
- Plus: Erklärungs-Text in Editorial-Block

### Seite N — Risikoprofilierung (Sektion 12)
- Sektion-Titel "Risikoprofilierung"
- 3 horizontale Score-Bars:
  - Risikofähigkeit (Capacity) — Score x10 als 0-100 Bar
  - Risikobereitschaft (Willingness) — Score x10
  - Final Score
- Plus: Risky-Fraction-Bar (0-100% mit aktuellem Punkt)
- Plus: 8 Standard-Fragen mit Punkte-Anzeige (Mini-Tabelle)
- Bei Override: prominenter Hinweis "Risiko-Override aktiv: <reason>"

### Seite N — Building Blocks / iSAA (Sektion 13)
- Sektion-Titel "Building Blocks · Institutionelle SAA"
- 5-Bucket-Tabelle: Target, Band-Min, Band-Max (mit visueller
  Bar-Indication)
- Plus: Constraints-Liste (Max-Risky-Fraction, etc.)
- Unten: `methodologie`-Text als langer Editorial-Block

### Seite N — Statement Portfoliomanagement (Sektion 14)
- Sektion-Titel "Statement aus dem Portfoliomanagement"
- 7 Investmentgrundsätze als nummerierte Liste mit Titel (h3) + Body
- Editorial-Stil, jeder Block ~4-5 Zeilen
- Erinnerung an institutionelle Verantwortung (FINMA-Sprache)

### Seite N — Weiteres Vorgehen (Sektion 15)
- Sektion-Titel "Weiteres Vorgehen"
- 2 grosse Berater-Text-Blöcke (block_optimierungen + block_zielstrategie)
- Falls leer: dezent ausgegraut mit Hinweis "Berater ergänzt vor Druck"
- Plus: Offene Fragen, Nächster Termin, To-Dos, Dokumente
- Plus: Unterschriften-Block (Berater + Kunde — siehe bestehende
  `pdf/components/unterschrift.py`)

---

## Teil D — Charts in PDF (anspruchsvoller Teil)

### Option 1 (empfohlen): ReportLab native Charts
- `reportlab.graphics.charts.barcharts.HorizontalBarChart`
- Vorteile: keine externen Dependencies, scharfe Vektoren, identische
  Farbpalette
- Nachteile: weniger flexibel als matplotlib

### Option 2: matplotlib → PNG → einbetten
- Vorteile: komplexere Charts (MC-Bänder mit alpha-Füllung) möglich
- Nachteile: Pixel-basiert, Rendering-Performance, extra Dependency

### Empfehlung
- **Standard-BarCharts** (Sektionen 8-10) mit ReportLab native
- **Monte-Carlo-Bänder** (Sektion 11) mit matplotlib (FillBetween für
  p5-p75-Band)
- **Donut** (Goal-Achievement, Sektion 11) mit matplotlib
- **Score-Bars** (Sektion 12) mit ReportLab native (HorizontalBarChart
  mit Single-Value)

### `services/pdf/components/bar_chart_ist_soll.py` (NEU)
```python
def make_bar_chart_ist_soll(
    items: list[dict],     # [{"label": ..., "ist_bps": ..., "soll_bps": ..., "drift_bps": ...}]
    *,
    width: float = 130 * mm,
    height: float = 80 * mm,
) -> Drawing:
    """Horizontale Doppel-Bar (IST vs. SOLL) plus Drift-Pfeil rechts.

    Visual matched 1:1 zur React-Komponente BarChartIstSoll.tsx —
    selbe Reihenfolge, selbe Farben (chartPalette), selbe Hover-Texte
    (wenn PDF interaktiv).
    """
```

Plus optional eine ReportLab-Annotation für interaktive PDF (auf Hover
zeigt Drift-Wert).

---

## Teil E — Schweizer Number-Formatter (geteilt mit Frontend)

`services/pdf/components/swiss_numbers.py`:
```python
def format_chf(rappen: int) -> str:
    """7'970'000 — Apostroph-Trenner, ohne Komma."""

def format_bps_as_pct(bps: int) -> str:
    """89.3% — exakt 1 Dezimalstelle für Prozente."""

def format_drift_bps_as_pp(bps: int) -> str:
    """+3.0pp / -3.0pp — Vorzeichen + Prozentpunkte."""

def format_date_swiss(iso_date: str) -> str:
    """25.05.2026 — DD.MM.YYYY."""
```

**Wichtig:** Die selben Helper sollen auch im Frontend als JS/TS-
Module existieren (in `5eyes-electron/frontend/reporting/src/api/`)
— Output muss exakt identisch sein. Test: PDF und Frontend rendern
dieselbe Zahl identisch.

---

## Teil F — Inhaltsverzeichnis-Seitenzahlen (zwei-Pass-Render)

Standardweg in ReportLab:
- **Pass 1:** Alle Sektionen rendern mit Platzhalter "{{PAGE_N}}",
  dabei `canvasmaker` registriert Sektion-Anfang per `bookmarkPage()`
- **Pass 2:** TOC-Sektion mit echten Seitenzahlen rendern

Alternativ: PageTemplate mit `_doc.afterFlowable` Hook, der pro Sektion
die aktuelle Seite in einem Index speichert.

Schau dir an wie `services/pdf/documents/anlagestrategie.py` heute
Seitenzahlen handhabt (falls überhaupt) — Pattern wiederverwenden.

---

## Teil G — PDF-Metadata + Bookmarks

```python
doc = SimpleDocTemplate(
    buffer,
    pagesize=A4,
    title=f"Advisory-Report {mandate.mandate_number}",
    author="5eyes Wealth Architects",
    subject="Strategische Portfolioanalyse",
    keywords="Family Office, Wealth Management, Schweiz",
    creator="5eyes v0.X",
)
```

Plus: Bookmarks für jede Sektion damit PDF-Viewer eine Outline anzeigen
(Acrobat / Edge / Browser PDF-Viewer).

---

## Teil H — Berater-Overrides (MandateReportNotes)

**Vorgriff:** In einem parallelen Sprint (siehe
`docs/planning/<DATE>-sprint-u-p28-mandate-report-notes.md`, kommt von
Claude) wird eine `MandateReportNotes`-DB-Tabelle eingeführt, in der
der Berater die Text-Felder von Sektion 4 (Anmerkungen), 7
(Erklärung), 9 (Analyse), 14 (Vorgehen) pflegen kann.

**Heute in U-P26:** Render die aktuellen Default-Texte aus dem
Aggregator. Sobald U-P28 gemerged ist, übernimmt der Aggregator
automatisch die Berater-Overrides — kein PDF-Code-Change nötig.

---

## Tests (verbindlich)

`tests/pdf/test_advisory_report_pdf.py` (NEU):

1. `test_pdf_renders_all_15_sections` — pdf_bytes hat erwartete Sektions-
   Marker (via pypdf text-extraction)
2. `test_pdf_cover_renders_client_and_advisor` — Cover-Inhalt
3. `test_pdf_disclaimer_has_all_7_hinweise`
4. `test_pdf_toc_lists_12_chapters_with_page_numbers`
5. `test_pdf_ausgangslage_renders_swiss_numbers` — Apostroph-Trenner
6. `test_pdf_positionen_groups_by_asset_class` — 5 Tabellen
7. `test_pdf_erkenntnisse_renders_ampel_pills` — Farben passen zu
   Status
8. `test_pdf_charts_for_aa_currency_branches` — ReportLab Drawing
   Embedded
9. `test_pdf_branding_compliance` — KEINE Dritt-Marken im PDF-Text
10. `test_pdf_endpoint_returns_application_pdf` — Content-Type
11. `test_pdf_endpoint_requires_auth` — 401 ohne Token
12. `test_pdf_swiss_numbers_helpers` — format_chf, format_bps_as_pct etc.
13. `test_pdf_metadata_set_correctly` — Title/Author/Subject

**Soll-Anzahl Tests nach diesem Sprint:** ca. +20 PDF-Tests, plus
3-5 für swiss_numbers-Helper.

---

## Branchen-Strategie

| PR | Inhalt |
|---|---|
| **PR A** | Endpoint + Skelett `advisory_report.py` mit Cover-Seite (Sektion 1) als Proof |
| **PR B** | Sektionen 2-5 (Disclaimer, TOC, Ausgangslage, Positionen) + Page-Header/Footer |
| **PR C** | Sektionen 6-7 (Pruefpunkte, Erkenntnisse mit Ampel-Pills) |
| **PR D** | Sektionen 8-10 (Asset Allocation, Währungen, Branchen mit `BarChartIstSoll`) |
| **PR E** | Sektionen 11-13 (Goal-Based mit MC-Bändern + Donut, Risikoprofil, Building Blocks) |
| **PR F** | Sektionen 14-15 (Statement, Vorgehen + Unterschrift) + finale Tests |

Stacked OK, jede PR alleine grün durch CI.

---

## Wichtig / Verboten

- **KEINE Dritt-Marken** (UBS, Pictet, Julius Bär, Swiss Life, 3eyes,
  PPC Metrics) im PDF-Text. Memory-Regel.
- **KEINE Garantieversprechen**, kein "garantiert" in Customer-facing
  Texten. FINMA-Compliance.
- **NICHT** bestehende PDFs (anlagestrategie/portfolio/risikoprofil/
  vertrag) refactoren — nur **NEU** das advisory-report.pdf.
- **NICHT** den Aggregator (`services/advisory_report.py`) ändern —
  PDF konsumiert was da ist.
- **MUSS** Single-Source-of-Truth respektieren: dieselben Zahl-Werte,
  dieselbe Reihenfolge, dieselben Texte wie das Frontend.
- **MUSS** Print-tauglich sein (kein dunkler Hintergrund, scharfe
  Vektoren wenn möglich).

---

## Acceptance-Criteria

Sobald alle PRs gemerged:

1. Berater öffnet Hauptapp → Mandat → Portfolio → "Advisory-Report"
2. Im neuen Browser-Tab (Reporting-App) gibt es einen Download-Button
   "PDF herunterladen" — ruft `/mandates/<id>/reports/advisory-report.pdf` auf
3. Browser lädt eine A4-PDF-Datei (~500 KB - 2 MB) herunter
4. Acrobat / Browser zeigt 15-Seiten-Report:
   - Seite 1: Cover mit Daniel Beispiel, MX-FOUNDATION-01
   - Seite 2: Disclaimer mit 7 Hinweisen
   - Seite 3: Inhaltsverzeichnis mit 12 Kapiteln + Seitenzahlen
   - Seite 4-N: Ausgangslage, Positionen, ... bis Vorgehen (Seite 15)
5. Page-Header zeigt "5eyes | Wealth Architects | Depotcheck |
   MX-FOUNDATION-01 — Seite X von 15"
6. Page-Footer zeigt "Vertraulich · Generiert 25.05.2026 14:32 · 5eyes v0.X"
7. PDF-Outline (Bookmarks) zeigt alle 15 Sektionen
8. Bei den Charts (AA, Währungen, Branchen): IST/SOLL-Balken sichtbar,
   Drift-Werte rechts
9. PDF lässt sich problemlos drucken (A4, kein dunkler Hintergrund)
10. **Visueller Vergleich:** Side-by-Side Bildschirm (React) vs. PDF
    zeigt das identische Editorial-Layout

---

## Zeitbudget

**~25-35 Stunden** für alle 6 PRs. Bei Token-Knappheit: abbrechen
nach PR D (= Sektionen 1-10 sind dann fertig), liefern was geht.

---

## Hinweis an Claude (für Übergabe)

Falls dieser Sprint von Claude (Opus 4.7) gemacht wird statt Codex:
gleiche PR-Strategie, gleiche Sektionen, gleiche Tests. Codex hat
Stage-7-PDF-Erfahrung (PR #52 — `_make_strategy_reasoning_section`)
und kennt die `services/pdf/`-Konventionen am besten. Claude müsste
sich erst einlesen.

---

## Bezug zu anderen Sprints

- **U-P21** = Backend-Aggregator (Single-Source-of-Truth) ✅ gemerged
- **U-P22.x** = Frontend Foundation (Scaffold, API-Client, Handoff) ✅ gemerged
- **U-P23** = Frontend Phase 1 (Sektionen 2-5) ⏳ Codex aktuell
- **U-P24** = Frontend Phase 2 (Sektionen 6-10 mit Charts) ⏳ TBD
- **U-P25** = Frontend Phase 3 (Sektionen 11-15) ⏳ TBD
- **U-P26** = PDF (= dieser Sprint) ⏳ nach U-P25
- **U-P27** = Polish + Electron-Window-Integration ⏳ Schluss
- **U-P28** = MandateReportNotes für Berater-Overrides ⏳ parallel zu U-P26
