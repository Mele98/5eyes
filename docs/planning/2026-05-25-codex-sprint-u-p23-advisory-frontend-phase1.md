# Codex-Sprint U-P23 — Advisory-Report Frontend Phase 1 + 3 Audit-Bugs

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25, nach Audit
> `docs/audits/2026-05-25-advisory-report-audit.md`.
> **User-Direktiven:** Berater hat ausdrücklich gewünscht (Originalton):
> - „Disclaimer nach Titelblatt, danach Inhaltsverzeichnis usw."
> - „Design anpassen"
> - „Ich wäre unbedingt bei den Länder, Branchen usw Balkendiagramme hätte."
> - „Es gibt abertausende Depotchecks als Vergleiche." (= institutionelles
>   Editorial-Niveau, KEIN Retailbank-Look)
> - „Schaue zusätzlich das das Design des PDF super ist" (PDF kommt aber
>   in eigenem Sprint U-P26, nicht hier — du machst U-P26 später)

---

## Voraussetzung — bitte ZUERST lesen

`docs/audits/2026-05-25-advisory-report-audit.md`

Das ist das volle 336-Zeilen-Audit. Dort stehen die 3 Bugs, die Sprint-Logik
und die Internet-Inspiration (UBS GFO Report, KPMG, CFA, Sia Partners). Es
ersetzt keine Spec — es legt nur den Audit-Stand offen.

## Ziel dieses Sprints

Berater sieht in seinem Browser (nicht nur Cover, sondern auch Disclaimer,
Inhaltsverzeichnis, Ausgangslage und Positionen). Plus 3 echte Bugs aus dem
Audit gefixt. Plus Recharts-Basis-Komponente vorbereitet, damit U-P24 mit
Balkendiagrammen direkt starten kann.

---

## Teil A — Struktur-Umstellung (kritisch, weil User explizit so will)

Der User möchte die Reihenfolge der Sektionen ändern. Aktuell:

```
1 Cover → 2 Inhaltsverzeichnis → 3 Ausgangslage → ... → 15 Disclaimer
```

**Neu gewünscht:**

```
 1 Cover (Titelblatt)
 2 Disclaimer (sofort, prominent — Compliance!)
 3 Inhaltsverzeichnis
 4 Ausgangslage
 5 Übersicht Positionen
 6 Was wir im Depotcheck prüfen
 7 Erkenntnisse (Ampel)
 8 Asset Allocation                  ← Balkendiagramm (U-P24)
 9 Risikowährungen                    ← Balkendiagramm (U-P24)
10 Diversifikation Branchen          ← Balkendiagramm (U-P24)
11 Goal-Based Investing
12 Risikoprofilierung
13 Building Blocks / iSAA
14 Statement aus dem Portfoliomanagement
15 Weiteres Vorgehen
```

### Umsetzung

**A.1 Backend `services/advisory_report.py`:**
- Top-Level JSON-Key-Reihenfolge umstellen
  (`compute_advisory_report`-Rückgabe)
- Field-Ordering: `cover`, `disclaimer`, `inhaltsverzeichnis`,
  `ausgangslage`, `positionen`, `pruefpunkte`, `erkenntnisse`,
  `asset_allocation`, `risikowaehrungen`, `branchen`,
  `goal_based_investing`, `risikoprofilierung`, `building_blocks`,
  `statement_pm`, `weiteres_vorgehen`
- `schema_version` auf 2 bumpen (Breaking Change in Reihenfolge)
- `tests/test_advisory_report.py`: erwartete Reihenfolge aktualisieren

**A.2 Inhaltsverzeichnis-Kapitel-Reihenfolge anpassen (Sektion 3 jetzt):**
Die `kapitel`-Liste in `_build_inhaltsverzeichnis()` muss die neue
Reihenfolge widerspiegeln. Disclaimer ist KEIN Kapitel im
Inhaltsverzeichnis (er ist eigene Pflichtseite vor dem Verzeichnis),
bleibt aber selbst-referenziert. Konkret in TOC:

```
 1 Ausgangslage
 2 Übersicht Positionen
 3 Was wir im Depotcheck prüfen
 4 Erkenntnisse aus dem Depotcheck
 5 Asset Allocation
 6 Risikowährungen
 7 Diversifikation
 8 Statement aus dem Portfoliomanagement
 9 Zielbasierte Optimierung
10 Risikoprofilierung
11 Building Blocks
12 Weiteres Vorgehen
```

**A.3 Frontend `src/api/types.ts`:**
- `AdvisoryReport`-Interface-Reihenfolge analog umstellen
- `schema_version: 2` (statt 1)

**A.4 Frontend `src/api/client.ts`:**
- `validateSchemaV1` → umbenennen oder `schema_version`-Check auf 2

---

## Teil B — 3 Bugs aus dem Audit (priorisiert §3.1, §3.3, §3.4)

### B.1 BUG Branchen-Aggregation (Audit §3.3, „Übrige" = 72.2%)

**Problem:** Engine aggregiert ALLE Positionen auf GICS-Sektor-Skala.
Bonds + Real Estate + Liquidität haben keine GICS-Sektoren, landen alle
in „Übrige" → 72% verzerrt.

**Fix in `services/advisory_report.py::_build_branchen()`:**
- Sektor-Aggregation NUR über AKTIEN-Positionen normalisieren
- In den Result zusätzlich aufnehmen:
  ```python
  "anteil_aktien_bps": int      # auf welchem Aktien-Anteil basiert die
                                 # Sektor-Verteilung (z.B. 1500 = 15%)
  "hinweis": str                 # "Sektor-Verteilung basiert auf 15.0%
                                 # Aktien-Allokation"
  ```
- Tests in `tests/test_advisory_report.py`:
  - `test_branchen_only_aggregates_equity_positions`
  - `test_branchen_returns_zero_when_no_equity`
  - `test_branchen_anteil_aktien_bps_matches_asset_allocation`

### B.2 BUG IST=SOLL überall (Audit §3.2)

**Problem:** `current_amount_rappen` ist NULL → fallback auf
`target_amount_rappen` → IST=SOLL → Drift überall 0. User sieht leere
Charts, falsche „alles in Band"-Meldungen.

**Fix-Strategie (zweistufig):**

- **Backend:** in jeder Sektion (`asset_allocation`, `risikowaehrungen`,
  `branchen`) einen Flag setzen:
  ```python
  "ist_basiert_auf_soll": bool
  ```
  `true` wenn ALLE Positionen `current_amount_rappen=NULL` haben.

- **Frontend:** wenn Flag `true`, klarer visueller Hinweis-Box am Anfang
  der Sektion:

  > „Datenstand: SOLL — IST wird ausserhalb des Systems erfasst. Drift-
  > Werte werden in einer späteren Bericht-Version ergänzt."

  Kein knalliges Rot, dezenter Editorial-Banner.

### B.3 BUG Goal-Achievability leer (Audit §3.4)

**Problem:** Foundation-Case rechnet mit `house_matrix` → keine
`goal_achievability_json` persistiert → Sektion 11 zeigt 0 Goals.

**Fix-Optionen:**

- **Option A:** In `services/foundation_example.py::upsert_foundation_example_case`
  nach Mandat-Erstellung einen stochastic-Run triggern + Result persistieren.
  Damit hat das Foundation-Mandat reale Goal-Daten für den Visual-Check.

- **Option B (Fallback falls A zu komplex):** im `_build_goal_based_investing()`-
  Helper für Goals OHNE Achievability eine neutrale Default-`probability=null`
  + `status="data_pending"` liefern. Frontend rendert dann „Berechnung steht
  aus" statt „0%".

---

## Teil C — Frontend Sektionen 2 + 3 + 4 + 5

Erstelle in `5eyes-electron/frontend/reporting/src/pages/`:

### C.1 `Disclaimer.tsx` (Sektion 2 — neu)
- Editorial Layout: kleine Schrift, viel Whitespace
- Liste aller 7 `hinweise` aus `data.disclaimer.hinweise`
- `data-testid="report-page-disclaimer"`
- Print-optimiert (sollte auf 1 Seite passen)

### C.2 `Inhaltsverzeichnis.tsx` (Sektion 3 — neu)
- Cleane Liste mit grossen Whitespaces, dünne horizontale Linie
  zwischen Kapiteln (`border-rule`)
- Elegante Nummerierung (1-12) in Mono-Font
- `data-testid="report-page-toc"`
- Hover-Effekt: subtle, kein Sprung

### C.3 `Ausgangslage.tsx` (Sektion 4 — neu)
Layout per Spec (User-Wunschliste 2026-05-24 §3):
- Linke Spalte: `client_info` (Alter, Horizont, Risikoprofil, Anlageziel,
  Liquiditätsbedarf, Steuerdomizil, Referenzwährung)
- Rechte Spalte: `wealth_summary` (Gesamtvermögen, Beratungsvermögen,
  Immobilien, Vorsorge, Kredite + Cashflows-Liste + Goals-Liste)
- Unten: 6 Key-Metric-Karten (`risky_fraction_bps`, `zielerreichung_bps`,
  `exp_vol_bps`, `exp_return_bps`, `max_drawdown_bps`, `var_95_bps`)
- Bei `null`-Werten „—" rendern (NICHT 0)
- Schweizer Zahl-Formatierung: `7'970'000` (Apostroph-Trenner)
- `data-testid="report-page-ausgangslage"`

### C.4 `Positionen.tsx` (Sektion 5 — neu)
Institutionelle Tabelle pro Asset-Klasse:
- 5 Gruppen-Sections (Liquidität, Obligationen, Aktien, Immobilien,
  Alternative Anlagen) immer gerendert, auch wenn leer
- Spalten: ISIN | Produktname | Sub-Asset-Class | Währung |
  Marktwert CHF | Anteil % | TER %
- Sticky Header im Container
- Dünne Linien (`border-rule`), kein Excel-Look
- Wenn `has_recommendation_run=false`: `hinweis` als Editorial-Banner
  oben, leere Gruppen ausgegraut
- `data-testid="report-page-positionen"`

### C.5 `App.tsx` Routing umbauen
Single-Page-Layout wird zur Multi-Section-Tour. Verwende
`react-router-dom` für die 14 Sektionen (Cover war schon da):

```
/mandates/:id/report                  → Sticky-Sidenav + Seite 1 (Cover)
/mandates/:id/report/disclaimer       → Seite 2
/mandates/:id/report/toc              → Seite 3
/mandates/:id/report/ausgangslage     → Seite 4
/mandates/:id/report/positionen       → Seite 5
...
```

### C.6 NEUE Komponente `Sidebar.tsx` (im `src/components/`)
- Sticky linke Navigation (immer sichtbar)
- Liste aller 15 Sektionen mit Aktiv-Indikator
- Editorial-Style: dünne Linien, Petrol-Akzent für aktive Sektion
- Scroll-Spy (highlight wenn man scrollt, kein Page-Wechsel nötig)
- Auf Mobile: Hamburger-Menü
- `data-testid="report-sidebar"`

---

## Teil D — Recharts-Basis-Komponente (Vorbereitung für U-P24)

Der User hat explizit gesagt: „Ich wäre unbedingt bei den Länder, Branchen
usw Balkendiagramme hätte." Bereite die Recharts-Komponente jetzt schon
vor, damit U-P24 (Sektionen Asset Allocation / Währungen / Branchen)
direkt darauf bauen kann.

### D.1 `src/components/BarChartIstSoll.tsx` (NEU)
- Horizontale Balkendiagramm-Komponente, Recharts-basiert
- Props:
  ```typescript
  {
    items: Array<{
      label: string;
      ist_bps: number;
      soll_bps: number;
      drift_bps: number;
    }>;
    height?: number;
  }
  ```
- Pro Zeile: Label links, dann zwei Balken (IST grau, SOLL Petrol),
  Drift-Pfeil rechts mit Prozentpunkt-Wert
- Tooltips auf Hover: zeigt exakte Prozentzahlen
- Sehr clean: dünne Linien, keine 3D, keine Schatten, KEIN Retailbank-Look
- Print-tauglich (kein dunkles Theme)
- `data-testid="bar-chart-ist-soll"`

### D.2 `src/design/chartTheme.ts` (NEU)
- Recharts-Theme-Objekt mit den Tokens aus `tokens.ts`
- `chartPalette` wird hier konsumiert
- Achsen-Styles, Grid-Styles, Tooltip-Style
- Wichtig: identisch für UI + PDF (later U-P26)

---

## Tests (verbindlich)

### Backend (Pytest)
- `test_advisory_report.py`: top-level-key-order, `schema_version=2`,
  TOC-Kapitel-Reihenfolge, Branchen-Bug-Fix, `ist_basiert_auf_soll`-Flag
- `test_branchen_only_aggregates_equity_positions`
- `test_foundation_case_has_goal_achievability`
  (wenn B.3 via `foundation_example`)

### Frontend (statische Pytest-Contracts)
- `test_reporting_frontend_phase1.py` (NEU):
  - `Disclaimer.tsx` existiert, rendert alle 7 `hinweise`
  - `Inhaltsverzeichnis.tsx` existiert, hat 12 Kapitel (neu nummeriert)
  - `Ausgangslage.tsx` existiert, rendert alle `client_info`-Felder +
    6 KPI-Karten
  - `Positionen.tsx` existiert, hat alle 5 Gruppen-IDs
  - `Sidebar.tsx` existiert, listet alle 15 Sektionen
  - `BarChartIstSoll.tsx` existiert, exportiert die Komponente
  - `App.tsx` hat 15 Routes
  - Schweizer Zahl-Formatierung als shared Helper
  - keine Dritt-Marken
  - `data-testid`s vorhanden

**Soll-Anzahl Tests nach diesem Sprint:** 87 → ca. 110 (rechne mit +23 Tests).

---

## Branchen-Strategie

Empfohlene Sprint-Aufteilung in einzelne PRs (damit Reviews handhabbar):

| PR | Inhalt |
|---|---|
| **PR A** | `schema_version=2` Umstellung + TOC-Reihenfolge (Teil A) |
| **PR B** | Branchen-Bug + IST=SOLL-Flag + Goal-Achievability (Teil B) |
| **PR C** | `Disclaimer.tsx` + `Inhaltsverzeichnis.tsx` + `Sidebar.tsx` + Routing (Teil C.1-C.2 + C.5-C.6) |
| **PR D** | `Ausgangslage.tsx` + `Positionen.tsx` + Schweizer Number-Formatter (Teil C.3-C.4) |
| **PR E** | `BarChartIstSoll` + `chartTheme.ts` (Teil D) |

Stacked OK, aber jede PR muss alleine grün durch CI. Sobald PR A
gemerged, rebase B-E auf neuen develop.

---

## Wichtig / Verboten

- **Keine Dritt-Marken** (UBS, Pictet, Julius Bär, Swiss Life, 3eyes,
  PPC Metrics) in Code / Texten / Tests. Memory-Regel.
- **Keine Garantieversprechen**, kein „garantiert" in Customer-facing
  Texten. FINMA-Compliance.
- **NICHT die echten Charts** (U-P24 Asset Allocation etc.) jetzt schon
  bauen — die kommen in einem späteren Sprint. Nur die
  `BarChartIstSoll`-Komponente als REUSABLE-Foundation.
- **NICHT** `openReportingApp()` in `5eyes_v2.html` refactoren — das ist
  Stand U-P22.6/.7 und funktioniert.
- **KEIN Server-PDF** (U-P26) — separater Sprint, du machst das später.
- **KEIN Refactoring** des bestehenden Stochastic-Stage-9-Codes (deine
  eigene letzte Arbeit, soll stabil bleiben).

---

## Acceptance-Criteria

Sobald alle PRs gemerged:

1. Berater öffnet Hauptapp → Mandat → Portfolio → „Advisory-Report"
2. Neuer Browser-Tab zeigt Cover (wie heute)
3. Sticky-Sidenav links zeigt alle 15 Sektionen
4. Klick auf „Disclaimer" → eigene Seite mit 7 Hinweisen
5. Klick auf „Inhaltsverzeichnis" → cleane 12-Kapitel-Liste
6. Klick auf „Ausgangslage" → 3 Spalten + 6 KPI-Karten mit ECHTEN Daten
   aus dem Mandat (CHF 7'970'000 Gesamtvermögen sichtbar)
7. Klick auf „Positionen" → 5 institutionelle Tabellen
8. Branchen-Sektion (noch nicht visuell, aber im JSON): „Übrige" ist weg,
   Sektor-Verteilung normalisiert auf Aktien-Anteil
9. AA / Risikowährungen / Branchen-Sektionen haben
   `ist_basiert_auf_soll`-Flag (Frontend-Rendering kommt in U-P24)
10. Foundation-Case hat Goals mit Achievability-Daten (oder klares
    „Berechnung steht aus")

---

## Zeitbudget / Kommunikation

Geschätzte **15-20 Stunden für alle 5 PRs**.

Bei Token-Knappheit: abbrechen nach PR C (Disclaimer + TOC + Sidebar),
liefern was geht, Status zurückmelden. Claude (Sonnet/Opus) übernimmt
dann den Rest.

Wenn du irgendwo eine Spec-Unklarheit findest (z.B. „wie genau soll die
Sidebar-Animation aussehen?") → entscheide pragmatisch, dokumentiere in
den Commit-Messages, gehe weiter. Lieber liefern als perfektionieren.

**PDF (= U-P26) bewusst NICHT in diesem Sprint.** Wenn der User später
fragt: du machst U-P26 als separaten Sprint mit demselben Design wie
das Frontend (`BarChartIstSoll`-Komponente wird dann auch in ReportLab
gespiegelt).

---

## Zusatz: Was dem User wichtig ist (Originalton)

- „Disclaimer nach Titelblatt, danach Inhaltsverzeichnis usw."
- „Design anpassen" — Editorial-Look bleibt, aber Frontend-Sektionen
  müssen es überzeugend umsetzen (Cover allein reicht nicht)
- „Ich wäre unbedingt bei den Länder, Branchen usw Balkendiagramme
  hätte." — `BarChartIstSoll`-Foundation ist Teil D, echte Charts kommen
  in U-P24
- „Es gibt abertausende Depotchecks als Vergleiche." — Inspirations-
  Quellen im Audit dokumentiert (UBS GFO Report, KPMG, CFA, Sia Partners).
  Hochwertiger Editorial-Stil, KEIN Retailbank-Look.

**Los gehts.**
