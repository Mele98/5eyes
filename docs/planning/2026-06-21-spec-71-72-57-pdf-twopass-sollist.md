# Spec: PDF-Cluster #71 / #72 / #57 — Two-Pass-Seitenzahlen, TOC-Page-Ranges + Hyperlinks, SOLL/IST-Kennzahlen-Sektion

Datum: 2026-06-21
Branch: `codex/u71-pdf-twopass`
Status: implementierungsfertig
Scope: 3 Punkte aus dem PDF-Cluster der Master-Roadmap (`docs/planning/2026-06-14-roadmap-master.md`).

Alle Befunde sind per Read-Tool an `file:line` verifiziert. Keine Halluzination.
Branding-Disziplin: keine Dritt-Marken in Code/PDF/Texten (Memory-Regel).

---

## Kontext — die Render-Pipeline (verifiziert)

Haupt-Renderer: `5eyes-backend/services/pdf/documents/advisory_report.py`

- Entry-Point `render_advisory_report_pdf()` (`advisory_report.py:95-128`) lädt das Aggregator-Payload (`compute_advisory_report`, `services/advisory_report.py:184`) und ruft `render_advisory_report_pdf_from_payload()` (`advisory_report.py:131-190`).
- **Two-Pass existiert bereits** (`advisory_report.py:163-190`):
  - Pass 1 (`advisory_report.py:168-176`): baut alle Flowables mit einem `TocCollector`, rendert in einen Scratch-Buffer, ein `_PageCounter` (`advisory_report.py:290-297`) zählt die Gesamtseiten, der `TocCollector` sammelt pro Sektion die erste Seite.
  - Pass 2 (`advisory_report.py:178-187`): rendert erneut, diesmal mit `toc_page_numbers` (Titel→Seite) und dem echten `make_advisory_page_chrome(...)` inkl. `total_pages_hint`.
- Flowable-Aufbau: `_build_all_flowables()` (`advisory_report.py:193-279`). Jede Sektion folgt dem Muster:
  ```python
  flowables.append(_toc_anchor(toc_collector, "<section_id>", "<Titel>"))
  flowables.extend(_build_<section>_flowables(payload.get("<key>") or {}, styles))
  flowables.append(PageBreak())
  ```
  `_toc_anchor()` (`advisory_report.py:282-287`) erzeugt einen `TocSectionAnchor`.

TOC-Mechanik: `5eyes-backend/services/pdf/components/table_of_contents.py`

- `TocCollector` (`table_of_contents.py:36-62`): `register(section_id, title, page_number)` ist **idempotent** — `if not safe_id or safe_id in self._seen: return` (`table_of_contents.py:48-51`). D.h. nur die **erste** Seite jeder Sektion wird gespeichert. **Es gibt keine Last-Page-Erfassung** → Voraussetzung für #72 fehlt heute.
- `TocSectionAnchor` (`table_of_contents.py:65-86`): Zero-Height-Flowable; `draw()` (`:79-86`) ruft `self.collector.register(..., int(self.canv.getPageNumber()))`.
- `make_toc_table()` (`table_of_contents.py:89-141`): rendert 4 Spalten (Nr / Titel / Dot-Leader / Seite). Seitenzahl ist **reiner Text** (`table_of_contents.py:122-128`) — **kein Hyperlink/`<a href>`** → Voraussetzung für #71-Hyperlinks fehlt heute.
- `_resolve_page_number()` (`table_of_contents.py:170-180`): Titel-Match mit Normalisierung + Präfix-Fallback (`_norm`, `:191-202`).
- TOC-Kapitel-Liste kommt aus dem Aggregator `_build_inhaltsverzeichnis()` (`services/advisory_report.py:499-526`), 20 Einträge.

Page-Chrome / Seitenzahlen: `5eyes-backend/services/pdf/components/advisory_page_chrome.py`

- `make_advisory_page_chrome()` (`advisory_page_chrome.py:105-136`) → Page-Callback, der `_draw_advisory_page_chrome` (`:139-201`) aufruft; schreibt `"Seite {page} / {total}"` (`:166-170`). **Pass-2-Standardpfad nutzt diesen Callback**, nicht den `AdvisoryNumberedCanvas`.
- `AdvisoryNumberedCanvas` (`:53-102`) existiert als Single-Pass-Alternative, wird im aktuellen Two-Pass-Pfad **nicht** verwendet.
- **Wichtig (ReportLab-Fakt):** `int(doc.page)` / `canvas.getPageNumber()` ist die fortlaufende physische Seitenzahl ab 1 inkl. Cover. Bookmarks/Links werden über die Canvas-API gezeichnet — **es gibt heute keinerlei `bookmarkPage` / `linkRect` / `addOutlineEntry` im gesamten `services/pdf`-Baum** (Grep: 0 Treffer). #71-Hyperlinks sind also komplett Greenfield.

Hilfsfunktionen (verifiziert, wiederverwenden):
- `_hr()` (`advisory_report.py:2962-2972`), `_escape()` (`:2993-3000`), `_safe_string()` (`:2923-2928`), `_ar_paragraph_style()` (`:2941-2959`).
- Styles: `make_advisory_styles()` (`services/pdf/components/advisory_palette.py:87-188`) — Keys: `display,h1,h2,h3,body,body_muted,caption,caption_mono,micro,kicker`.
- Zahlenformat: `format_bps_as_pct`, `format_bps_signed_pct` (`services/pdf/components/swiss_numbers.py:22,33`), `format_chf_rappen`.

Test-Konventionen (verifiziert):
- `5eyes-backend/tests/test_advisory_report_pdf.py` — `_make_minimal_payload()` (`:35-...`), Render-Tests mit `pypdf` `extract_text()` (`:103-122` in `tests/test_toc_page_numbers.py`).
- Zwei TOC-Test-Dateien: `tests/test_toc_page_numbers.py` und `tests/pdf/test_toc_page_numbers.py`.

---

# Punkt #71 — Two-Pass echte Seitenzahlen + TOC-Hyperlinks

## Ziel
Die TOC-Seitenzahlen sind bereits echt (Two-Pass aktiv). Der **noch fehlende Teil von #71 ist der Hyperlink**: jeder TOC-Eintrag soll im PDF anklickbar sein und zur Start-Seite der Sektion springen (interner Sprung + PDF-Outline/Bookmarks im Reader-Navigationsbaum).

## IST (verifiziert)
- Echte Seitenzahlen: vorhanden (`advisory_report.py:168-187`, `table_of_contents.py:58-59`).
- Hyperlinks/Bookmarks: **nicht vorhanden** (0 Treffer für `bookmarkPage|linkRect|addOutlineEntry|canv.bookmark` in `services/pdf`).
- TOC-Zelle „Seite" ist Plain-Text-Paragraph (`table_of_contents.py:122-128`).

## SOLL-Design

### Anchor-Namen (stabile Bookmark-Keys)
`TocSectionAnchor` bekommt einen deterministischen Bookmark-Key = `section_id` (schon vorhanden, `table_of_contents.py:71`). Beim Zeichnen setzen wir an der aktuellen Position ein ReportLab-Bookmark:

`table_of_contents.py` — `TocSectionAnchor.draw()` erweitern (`:79-86`):
```python
def draw(self) -> None:
    # Bookmark IMMER setzen (auch in Pass 1 harmlos), Ziel = section_id.
    try:
        self.canv.bookmarkPage(self.section_id)       # interner Sprungziel-Key
        self.canv.addOutlineEntry(                     # Reader-Navigationsbaum
            self.title or self.section_id,
            self.section_id,
            level=0,
            closed=False,
        )
    except Exception:
        pass  # Bookmark ist additiv; Render darf daran nie scheitern
    if self.collector is None:
        return
    self.collector.register(self.section_id, self.title, int(self.canv.getPageNumber()))
```
Edge-Case Doppel-Anchor: `bookmarkPage` mit identischem Key über zwei Pässe ist unkritisch (Pass 1 = Scratch-Buffer, eigener Canvas; Pass 2 = finaler Canvas). Innerhalb **eines** Passes ist jeder `section_id` unique (durch `_seen`-Disziplin im Aufbau).

### TOC-Zeile als Link
`make_toc_table()` muss den Bookmark-Key kennen, um `<a href="#section_id">…</a>` zu rendern. ReportLab-`Paragraph` unterstützt interne Links via `<a href="#name">` wenn das passende `bookmarkPage(name)` gesetzt ist.

Dazu muss die Kapitel-Liste den `section_id` mitführen. Heute trägt `_build_inhaltsverzeichnis()` (`services/advisory_report.py:499-526`) nur `nr`+`title`. **OWNER-DECISION D1** (siehe unten) — empfohlen: Variante B (Mapping im PDF-Layer, kein Aggregator-Change).

Neue Signatur (additiv, rückwärtskompatibel):
```python
# table_of_contents.py
def make_toc_table(
    chapters: list[dict],
    styles: dict,
    *,
    inner_width: float,
    page_numbers_by_title: Mapping[str, int] | None = None,
    page_ranges_by_title: Mapping[str, tuple[int, int]] | None = None,   # #72
    section_id_by_title: Mapping[str, str] | None = None,                 # #71-Link
) -> Table:
```
In `_toc_rows()` (`table_of_contents.py:152-167`) pro Zeile zusätzlich `anchor = section_id_by_title.get(title)` auflösen (gleiche Normalisierungs-Logik wie `_resolve_page_number`, ausgelagert in einen gemeinsamen Resolver `_resolve_for_title`). Die Titel- bzw. Seite-Zelle wird dann:
```python
page_text = row["page"]  # "4" oder "4–6" (siehe #72)
if anchor and page_text:
    page_cell = f"<a href=\"#{escape(anchor)}\" color=\"#0F1C2E\">{escape(page_text)}</a>"
else:
    page_cell = escape(page_text)
```
Der Titel-Text sollte **ebenfalls** verlinkt werden (grössere Klickfläche). Farbe = `COLOR_INK` (kein Blau — Editorial-Stil bleibt; Link ist optisch unsichtbar, aber funktional).

### Mapping section_id ↔ TOC-Titel (Variante B, empfohlen)
Im PDF-Layer existiert die kanonische Reihenfolge bereits in `_build_all_flowables` (`advisory_report.py:204-278`) als `_toc_anchor(collector, "<id>", "<Titel>")`. Diese Paare zentralisieren:

`advisory_report.py` — neue Modul-Konstante (Single-Source der Anchor-Reihenfolge):
```python
# (section_id, toc_title) in Render-Reihenfolge. Single-Source fuer Anchors,
# TOC-Title-Mapping (#71-Link) und Page-Range-Zuordnung (#72).
_SECTION_ANCHORS: tuple[tuple[str, str], ...] = (
    ("disclaimer", "Rechtliche Hinweise"),
    ("toc", "Inhaltsverzeichnis"),
    ("ausgangslage", "Ausgangslage"),
    ("positionen", "Übersicht Ihrer Positionen"),
    ("pruefpunkte", "Was wir im Depotcheck prüfen"),
    ("erkenntnisse", "Erkenntnisse aus dem Depotcheck"),
    ("asset_allocation", "Asset Allocation"),
    ("risikowaehrungen", "Risikowährungen"),
    ("branchen", "Diversifikation Branchen"),
    ("goal_based_investing", "Zielbasierte Optimierung"),
    ("soll_ist_kennzahlen", "SOLL/IST-Kennzahlenvergleich"),   # #57 (neu)
    ("risikoprofilierung", "Risikoprofilierung"),
    ("building_blocks", "Building Blocks / iSAA"),
    ("statement_pm", "Statement aus dem Portfoliomanagement"),
    ("weiteres_vorgehen", "Weiteres Vorgehen"),
    ("beratungsprotokoll", "Beratungsprotokoll"),
    ("stress_replay", "Historische Stress-Szenarien"),
    ("suitability_summary", "Eignungspruefung"),
)
_SECTION_ID_BY_TITLE = {title: sid for sid, title in _SECTION_ANCHORS}
```
`section_id_by_title=_SECTION_ID_BY_TITLE` wird in `_build_toc_flowables()` (`advisory_report.py:439-469`) bis `make_toc_table()` durchgereicht.

> Hinweis: `_SECTION_ANCHORS` muss **nicht** die `_build_all_flowables`-Reihenfolge ersetzen (kein Refactor-Zwang) — es genügt als Mapping-Quelle. Optionaler Folge-Cleanup: `_build_all_flowables` aus `_SECTION_ANCHORS` generieren (nicht in dieser Spec).

## Konkrete Funktionen/Signaturen #71
- `table_of_contents.py`: `TocSectionAnchor.draw()` (Bookmark+Outline), `make_toc_table(..., section_id_by_title=...)`, `_toc_rows(..., section_id_by_title=...)`, neuer Resolver `_resolve_for_title(title, mapping)`.
- `advisory_report.py`: Konstanten `_SECTION_ANCHORS`/`_SECTION_ID_BY_TITLE`; `_build_toc_flowables(..., section_id_by_title=...)`.

## Test-Plan #71
Neue Tests in `tests/pdf/test_toc_hyperlinks.py`:
1. `test_toc_section_anchor_calls_bookmark_and_outline` — DummyCanvas mit `bookmarkPage`/`addOutlineEntry`-Spies; `anchor.draw()` registriert beide mit `section_id`/`title`.
2. `test_toc_table_renders_internal_link` — `make_toc_table(..., section_id_by_title={"Ausgangslage":"ausgangslage"}, page_numbers_by_title={"Ausgangslage":4})`; Zelle enthält `href="#ausgangslage"`.
3. `test_rendered_pdf_has_outline_entries` — `pypdf.PdfReader(...).outline` ist nicht leer und enthält ≥ Anzahl Sektionen Einträge.
4. `test_toc_link_absent_when_no_mapping` — ohne `section_id_by_title` bleibt die Zelle Plain-Text (Backwards-Compat).
5. `test_render_never_crashes_on_bookmark_failure` — Canvas-Stub, dessen `bookmarkPage` wirft; Render läuft trotzdem durch (try/except).

## Edge-Cases #71
- Sektion mit gleichem Titel wie ein anderer Eintrag: `_seen`-Disziplin + eindeutige `section_id` verhindern Kollision.
- Titel mit Umlauten/Sonderzeichen: `section_id` ist ASCII-Slug (bereits so vergeben), `href` daher unproblematisch; `escape()` auf den sichtbaren Text.
- Reader ohne Outline-Support: Bookmarks sind additiv, Seitenzahl-Text bleibt sichtbar.

---

# Punkt #72 — Page-Range-Anzeige pro Sektion im TOC

## Ziel
TOC zeigt statt Einzelseite die volle Spanne pro Sektion: `S. 4` wenn 1 Seite, `S. 4–6` wenn mehrseitig.

## IST (verifiziert)
- `TocCollector` speichert nur die **erste** Seite (`table_of_contents.py:48-56`). Keine Last-Page.
- TOC rendert genau eine Zahl pro Zeile (`table_of_contents.py:160-166`, `:122-128`).

## SOLL-Design
„Last page einer Sektion" = (Startseite der **nächsten** Sektion). Falls gleich → 1-seitig. Robuster als Anchor-am-Ende, weil jede Sektion in `_build_all_flowables` mit `PageBreak()` endet (`advisory_report.py:208,214,...`), d.h. die nächste Sektion startet garantiert auf einer neuen Seite. Die letzte Sektion endet bei `total_pages`.

### Datenfluss
1. `TocCollector` bekommt eine Methode, die geordnete Start-Seiten liefert:
   ```python
   # table_of_contents.py — TocCollector
   def page_ranges_by_title(self, total_pages: int) -> dict[str, tuple[int, int]]:
       """Pro Titel (first_page, last_page). last = (next.first - 1), bzw.
       total_pages fuer die letzte Sektion. Mindestens 1-seitig."""
       entries = list(self._entries)  # Insertion-Order = Render-Reihenfolge
       ranges: dict[str, tuple[int, int]] = {}
       for i, e in enumerate(entries):
           if i + 1 < len(entries):
               last = max(e.page_number, entries[i + 1].page_number - 1)
           else:
               last = max(e.page_number, int(total_pages))
           ranges[e.title] = (e.page_number, last)
       return ranges
   ```
   Insertion-Order ist garantiert (`_entries` ist eine Liste, `register` hängt an, `table_of_contents.py:52`).

2. Pass 2 in `render_advisory_report_pdf_from_payload` (`advisory_report.py:176-185`) zusätzlich:
   ```python
   toc_page_ranges = toc_collector.page_ranges_by_title(total_pages)
   ...
   _build_all_flowables(payload, styles,
       toc_page_numbers=toc_page_numbers,
       toc_page_ranges=toc_page_ranges)
   ```
   `_build_all_flowables` (`advisory_report.py:193-202`) und `_build_toc_flowables` (`:439-469`) bekommen `toc_page_ranges` als Keyword und reichen es an `make_toc_table(..., page_ranges_by_title=...)`.

3. Render-Logik in `_toc_rows()` (`table_of_contents.py:152-167`): Range hat Vorrang vor Einzelseite:
   ```python
   rng = _resolve_for_title(title, page_ranges) if page_ranges else None
   if rng:
       first, last = rng
       page_str = f"{first}" if first == last else f"{first}–{last}"  # – = en dash
   else:
       page = _resolve_page_number(title, page_numbers)
       page_str = str(page) if page is not None else ""
   ```
   Dot-Leader-Logik unverändert (Leader nur wenn `page_str` nicht leer).

## Konkrete Funktionen/Signaturen #72
- `TocCollector.page_ranges_by_title(total_pages) -> dict[str, tuple[int,int]]`.
- `make_toc_table(..., page_ranges_by_title=...)`, `_toc_rows(..., page_ranges_by_title=...)`, `resolve_toc_rows(..., page_ranges=...)` (Test-Helper, `table_of_contents.py:144-149`).
- `_build_toc_flowables(..., toc_page_ranges=...)` und `_build_all_flowables(..., toc_page_ranges=...)`.

## Test-Plan #72
Neu in `tests/pdf/test_toc_page_ranges.py`:
1. `test_single_page_section_shows_single_number` — Collector mit `A@4`, `B@5`, `total=5` → `A`-Range = (4,4) → Text `"4"`.
2. `test_multi_page_section_shows_range` — `A@4`, `B@7`, `total=8` → `A` = (4,6) → `"4–6"` (en dash, `–`).
3. `test_last_section_extends_to_total_pages` — letzte Sektion `Z@10`, `total=12` → `(10,12)` → `"10–12"`.
4. `test_range_takes_precedence_over_single` — wenn `page_ranges` gesetzt, wird `page_numbers` ignoriert.
5. `test_rendered_pdf_toc_shows_range` — Full-Render mit `_make_minimal_payload`, `pypdf` `extract_text()` auf TOC-Seite enthält mindestens eine Range-Zeile `\d+–\d+` (sofern ≥1 Sektion mehrseitig; sonst Test auf monotone Einzelzahlen — siehe Edge-Case).
6. `test_page_ranges_monotonic_non_overlapping` — Ranges decken `[1..total]` lückenlos & überlappungsfrei ab.

## Edge-Cases #72
- **Sektion über mehrere Seiten:** durch „next.first − 1" korrekt erfasst.
- **Leere/sehr kurze Sektion (1 Seite):** `first == last` → Einzelzahl, kein Dash.
- **Sektion, die durch `if ab_bt:` (`advisory_report.py:259`) ausgelassen wird:** kein Anchor → kein Collector-Eintrag → erscheint nicht im Range-Mapping; das nächste vorhandene Anchor liefert korrekt die nächste Startseite. Konsistent.
- **Minimal-Payload-Render** kann alle Sektionen auf je 1 Seite legen → Test 5 darf nicht hart auf einen Dash bestehen (OWNER-DECISION D2: Test-Fixture so wählen, dass eine Sektion garantiert ≥2 Seiten füllt, z.B. via langem Erkenntnisse-Block).
- **TOC selbst** (`section_id="toc"`) bekommt ebenfalls eine Range — fachlich ok.

---

# Punkt #57 — SOLL/IST-Kennzahlen + Risiko-Vergleich als PDF-Sektion

## Ziel
Die im Frontend bestehende zweispaltige SOLL/IST-Kennzahlen-Tabelle (Strategie vs. heutiger Mix) als eigene PDF-Sektion rendern.

## IST — Frontend-Quelle (verifiziert)
Datei: `5eyes-electron/frontend/5eyes_v2.html`
- Tabelle: `5eyes_v2.html:3082-3106`. Header `Kennzahl | SOLL — Strategie | IST — heutiger Mix` (`:3086-3088`).
- 13 Zeilen, je SOLL-Zelle-id + IST-Zelle-id:

  | Zeile (DE) | SOLL-Zelle | IST-Zelle | HTML-Zeile |
  |---|---|---|---|
  | Prognose Endwert (Median) | `aa-proj-median` | `aa-proj-current-median` | 3092 |
  | Endwert optimistisch (P90) | `aa-proj-p90` | `aa-proj-current-p90` | 3093 |
  | Endwert pessimistisch (P10) | `aa-proj-p10` | `aa-proj-current-p10` | 3094 |
  | Erwartete Rendite p.a. (P50) | `aa-proj-p50-return` | `aa-proj-current-p50-return` | 3095 |
  | Wachstum p.a. (CAGR Median) | `aa-proj-cagr` | `aa-proj-current-cagr` | 3096 |
  | Rendite/Risiko (Sharpe) | `aa-proj-sharpe` | `aa-proj-current-sharpe` | 3097 |
  | Median-Reichweite | `aa-proj-runway-target` | `aa-proj-runway-current` | 3098 |
  | *Zwischen-Header „Risiko (Monte-Carlo, 1 Jahr · tiefer = besser)"* | — | — | 3099 |
  | Volatilität (1J) | `aa-proj-vol` | `aa-proj-current-vol` | 3100 |
  | VaR 95% (1J) | `aa-proj-var95` | `aa-proj-current-var95` | 3101 |
  | CVaR 95% (1J) | `aa-proj-cvar95` | `aa-proj-current-cvar95` | 3102 |
  | Max Drawdown (Median) | `aa-proj-drawdown` | `aa-proj-current-drawdown` | 3103 |
  | Verlust-Wkeit (1J) | `aa-proj-lossprob` | `aa-proj-current-lossprob` | 3104 |
  | Verzehr-Risiko | `aa-proj-depletion` | `aa-proj-current-depletion` | 3105 |

- Fill-Logik (JS) `5eyes_v2.html:19370-19434`. Feld-Mapping (verifiziert):
  - Median Endwert = letztes Element von `target_p50_series_rappen` / `current_p50_series_rappen` (`:19370`).
  - P90/P10 Endwert = letztes Element von `target_p90_series_rappen` / `target_p10_series_rappen` (+ `_resRappen` Reserve-Sockel auf SOLL) bzw. `current_p90/p10_series_rappen` (`:19399-19406`).
  - Sharpe = `(annualized_return_p50_bps − 80) / volatility_1y_bps`, RF=80bps (`:19407-19414`). SOLL: `target_annualized_return_p50_bps`,`target_volatility_1y_bps`; IST: `current_*`.
  - Vol/VaR/CVaR/Drawdown/LossProb/Depletion = `target_*` vs `current_*_…_bps`/`_pct` (`:19383-19397`).
  - SOLL-Zelle wird grün/orange eingefärbt via `_colorBetter(id, soll, ist, higherBetter)` (`:19417-19434`).

## IST — Backend-Quelle (verifiziert, KRITISCH)
Die Tabelle wird aus dem `monte_carlo`-Dict von `portfolio_engine.generate_target_allocation()` gefüllt. Dieses Dict (verifiziert in `services/portfolio_engine.py:3442-3504`) enthält **symmetrische** SOLL/IST-Felder:
- Serien: `target_p10/p50/p90_series_rappen`, `current_p10/p50/p90_series_rappen` (`:3448-3453`).
- `target_annualized_return_p50_bps`, `current_annualized_return_p50_bps` (`:3474-3475`).
- `target_volatility_1y_bps`, `current_volatility_1y_bps` (`:3492-3493`).
- `target_var_95_1y_bps`/`current_var_95_1y_bps`, `…cvar_95…`, `…max_drawdown_p50_bps`, `…loss_probability_1y_pct`, `…depletion_probability_pct`/`…depletion_median_year` (`:3482-3501`).
- `goal_analysis` (SOLL) + `current_goal_analysis` (IST), je mit `success_rate_pct,median_achievement_pct,pessimistic_shortfall_rappen` (Contract in `tests/test_current_goal_analysis_contract.py:11-17,49-61`; Engine-Output `portfolio_engine.py:6593-6595` und `:7248-7250`).

Schema/Endpoint-Kontext (verifiziert): Pydantic `MonteCarloResponse` (`schemas/allocation.py:557-587`) listet die `target_*`-Risikofelder, aber **nicht** die `current_*`-Risikofelder (`current_var_95_1y_bps`, `current_cvar_95_1y_bps`, `current_volatility_1y_bps`, `current_max_drawdown_p50_bps`, `current_loss_probability_1y_pct`, `current_depletion_*`) — diese existieren nur im Engine-Dict und werden vom Frontend direkt konsumiert. Endpoint: `POST /mandates/{id}/target-allocation/generate` (`routers/allocation.py:367-391`), Response `TargetAllocationGenerateResponse` mit `monte_carlo`/`goal_analysis`/`current_goal_analysis` (`schemas/allocation.py:780-782`). Für #57 ist das irrelevant solange der Aggregator das **Dict** (nicht die serialisierte Response) konsumiert; falls D3b serialisiert wird, müssen die `current_*`-Felder ins Schema ergänzt werden.

**Problem (verifiziert):** Dieses volle `monte_carlo`-Dict wird **nicht** persistiert. `TargetAllocation` hat nur `shadow_optimization_json` (`models/allocation.py:98`), nicht die SOLL/IST-Reihen. Der Aggregator berechnet in `_build_monte_carlo_paths_section` (`services/advisory_report.py:1920-1941`) lediglich **SOLL-Pfade** über `services.monte_carlo_paths.compute_quantile_paths`, dessen Schema **nur** `p5/p50/p75` (SOLL) liefert (`services/monte_carlo_paths.py:98-110`) — **keine** IST-Spalte, keine Sharpe/VaR-Symmetrie.

→ Die für #57 nötige IST-Spalte existiert heute **nicht** im Aggregator-Payload. Datenquelle existiert (Engine), muss aber dem Aggregator zugänglich gemacht werden. Siehe **OWNER-DECISION D3** (Datenbeschaffung).

## SOLL-Design

### Aggregator: neue Payload-Sektion `soll_ist_kennzahlen`
Neuer Builder in `services/advisory_report.py`, eingehängt im Return-Dict von `_compute_advisory_report_inner` (`advisory_report.py:245-316`) z.B. nach `goal_based_investing` (`:279`):
```python
"soll_ist_kennzahlen": _build_soll_ist_kennzahlen(db, mandate),
```
Builder-Skizze (D3-Variante „On-Demand-Recompute", empfohlen):
```python
def _build_soll_ist_kennzahlen(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Sektion #57 — zweispaltiger SOLL/IST-Kennzahlenvergleich (gleiche
    MC-Methodik wie das Frontend, 5eyes_v2.html:3082-3106 / :19370-19434).

    Datenquelle: portfolio_engine.generate_target_allocation()['monte_carlo'].
    Wird NICHT persistiert -> hier auf den persistierten MC-Recompute-Pfad
    abgebildet. Bei fehlenden Daten: data_pending=True (UI/PDF rendert Hinweis).
    """
    mc = _compute_sollist_monte_carlo(db, mandate)  # D3
    if not mc or mc.get("data_pending"):
        return {"data_pending": True,
                "note": (mc or {}).get("note") or
                        "SOLL/IST-Kennzahlen benötigen eine berechnete Anlagestrategie.",
                "rows": []}
    RF = 80
    def last(arr): return int(arr[-1]) if arr else None
    def sharpe(r, v): return None if not (r and v and v > 0) else round((r - RF) / v, 2)
    rows = [
        {"key": "median", "label": "Prognose Endwert (Median)", "kind": "chf",
         "soll": last(mc.get("target_p50_series_rappen")),
         "ist":  last(mc.get("current_p50_series_rappen")), "higher_better": True},
        {"key": "p90", "label": "Endwert optimistisch (P90)", "kind": "chf",
         "soll": last(mc.get("target_p90_series_rappen")),
         "ist":  last(mc.get("current_p90_series_rappen")), "higher_better": True},
        {"key": "p10", "label": "Endwert pessimistisch (P10)", "kind": "chf",
         "soll": last(mc.get("target_p10_series_rappen")),
         "ist":  last(mc.get("current_p10_series_rappen")), "higher_better": True},
        {"key": "return_p50", "label": "Erwartete Rendite p.a. (P50)", "kind": "pct_bps",
         "soll": mc.get("target_annualized_return_p50_bps"),
         "ist":  mc.get("current_annualized_return_p50_bps"), "higher_better": True},
        {"key": "sharpe", "label": "Rendite/Risiko (Sharpe)", "kind": "ratio",
         "soll": sharpe(mc.get("target_annualized_return_p50_bps"), mc.get("target_volatility_1y_bps")),
         "ist":  sharpe(mc.get("current_annualized_return_p50_bps"), mc.get("current_volatility_1y_bps")),
         "higher_better": True},
        {"key": "vol", "label": "Volatilität (1J)", "kind": "pct_bps",
         "soll": mc.get("target_volatility_1y_bps"), "ist": mc.get("current_volatility_1y_bps"),
         "higher_better": False},
        {"key": "var95", "label": "VaR 95% (1J)", "kind": "loss_bps",
         "soll": mc.get("target_var_95_1y_bps"), "ist": mc.get("current_var_95_1y_bps"),
         "higher_better": False},
        {"key": "cvar95", "label": "CVaR 95% (1J)", "kind": "loss_bps",
         "soll": mc.get("target_cvar_95_1y_bps"), "ist": mc.get("current_cvar_95_1y_bps"),
         "higher_better": False},
        {"key": "drawdown", "label": "Max Drawdown (Median)", "kind": "loss_bps",
         "soll": mc.get("target_max_drawdown_p50_bps"), "ist": mc.get("current_max_drawdown_p50_bps"),
         "higher_better": False},
        {"key": "lossprob", "label": "Verlust-Wkeit (1J)", "kind": "pct_plain",
         "soll": mc.get("target_loss_probability_1y_pct"), "ist": mc.get("current_loss_probability_1y_pct"),
         "higher_better": False},
        {"key": "depletion", "label": "Verzehr-Risiko", "kind": "pct_plain",
         "soll": mc.get("target_depletion_probability_pct"), "ist": mc.get("current_depletion_probability_pct"),
         "higher_better": False},
    ]
    return {"data_pending": False, "risk_free_bps": RF, "rows": rows}
```
> Hinweis CAGR/Median-Reichweite: Frontend berechnet CAGR JS-seitig (`simulationCagrBps`, `5eyes_v2.html:19372`) und „Reichweite" separat. Diese zwei Zeilen sind im PDF **optional** (OWNER-DECISION D4) — bei Auslassung bleibt die PDF-Tabelle bei 11 Datenzeilen. Empfehlung: weglassen (Reichweite hat im Frontend eigene Quelle, CAGR ist redundant zur P50-Rendite).

### PDF-Renderer: neue Sektion analog bestehender Sektionen
Neuer Builder in `services/pdf/documents/advisory_report.py`, eingehängt in `_build_all_flowables` (`advisory_report.py:236-241`) zwischen `goal_based_investing` und `risikoprofilierung`:
```python
flowables.append(PageBreak())
flowables.append(_toc_anchor(toc_collector, "soll_ist_kennzahlen", "SOLL/IST-Kennzahlenvergleich"))
flowables.extend(_build_soll_ist_kennzahlen_flowables(payload.get("soll_ist_kennzahlen") or {}, styles))
```
Renderer (Muster: `_build_erkenntnisse_flowables`/`_build_bar_chart_section`, `advisory_report.py:866-945` / `:1035-1092`):
```python
def _build_soll_ist_kennzahlen_flowables(data: dict, styles: dict) -> list[Any]:
    out: list[Any] = []
    out.append(Paragraph("Sektion 11", styles["kicker"]))            # Nr. anpassen
    out.append(Paragraph("SOLL/IST-Kennzahlenvergleich", styles["h1"]))
    out.append(Paragraph(
        "<i>Strategie (SOLL) gegen heutigen Mix (IST), gleiche Monte-Carlo-Methodik.</i>",
        _ar_paragraph_style(styles["h3"], color=COLOR_INK_MUTED)))
    out.append(Spacer(1, 3 * mm)); out.append(_hr()); out.append(Spacer(1, 4 * mm))
    if data.get("data_pending"):
        out.append(Paragraph(_escape(str(data.get("note") or "Keine Daten.")),
                             _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED)))
        return out
    rows = data.get("rows") or []
    rf = int(data.get("risk_free_bps") or 80)
    page_width, _ = PAGE_SIZE
    inner = page_width - MARGIN_LEFT - MARGIN_RIGHT
    c_label, c_soll, c_ist = inner * 0.46, inner * 0.27, inner * 0.27
    header = [_th("Kennzahl", styles), _th("SOLL — Strategie", styles), _th("IST — heutiger Mix", styles)]
    table_rows = [header]
    cell_cmds = []
    for i, r in enumerate(rows, start=1):
        soll_txt = _fmt_sollist(r.get("kind"), r.get("soll"))
        ist_txt  = _fmt_sollist(r.get("kind"), r.get("ist"))
        # SOLL-Zelle einfaerben analog _colorBetter (gruen=besser, rot=schlechter)
        color = _sollist_color(r.get("soll"), r.get("ist"), bool(r.get("higher_better")))
        table_rows.append([
            Paragraph(_escape(r.get("label") or "—"), styles["caption"]),
            Paragraph(_escape(soll_txt), _ar_paragraph_style(styles["caption"], color=color, font=FONT_SANS_BOLD)),
            Paragraph(_escape(ist_txt), _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED)),
        ])
    table = Table(table_rows, colWidths=[c_label, c_soll, c_ist])
    table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (1,0), (2,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LINEBELOW", (0,0), (-1,0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0,1), (-1,-1), 0.2, COLOR_RULE),
    ]))
    out.append(table)
    out.append(Spacer(1, 3 * mm))
    out.append(Paragraph(
        f"Sharpe-Ratio = (Median-Rendite p.a. − risikofrei {rf/100:.1f}%) / Volatilität. "
        "Bei Risikokennzahlen ist tiefer besser.",
        _ar_paragraph_style(styles["micro"], color=COLOR_INK_SUBTLE)))
    return out
```
Hilfs-Formatter (neu, im PDF-Modul):
```python
def _fmt_sollist(kind: str, value) -> str:
    if value is None: return "—"
    if kind == "chf":       return format_chf_rappen(int(value))
    if kind == "pct_bps":   return format_bps_as_pct(int(value), decimals=2)       # swiss_numbers:22
    if kind == "loss_bps":  return "−" + format_bps_as_pct(abs(int(value)), decimals=2)
    if kind == "pct_plain": return f"{int(round(float(value)))}%"
    if kind == "ratio":     return f"{float(value):.2f}"
    return _safe_string(value)

def _sollist_color(soll, ist, higher_better: bool):
    try:
        sv, iv = float(soll), float(ist)
    except (TypeError, ValueError):
        return COLOR_INK
    if sv == iv: return COLOR_INK
    better = (sv > iv) if higher_better else (sv < iv)
    return COLOR_STATUS_GRUEN if better else COLOR_STATUS_ROT   # advisory_palette:59,61
```
`_th(...)` existiert bereits im Modul (verwendet in `_goals_table`, `advisory_report.py:1246-1252`). `COLOR_STATUS_GRUEN/ROT`, `FONT_SANS_BOLD`, `format_chf_rappen`, `format_bps_as_pct` sind bereits importiert (`advisory_report.py:54-85`).

### TOC-Eintrag
`_build_inhaltsverzeichnis()` (`services/advisory_report.py:499-526`) um einen Kapitel-Eintrag „SOLL/IST-Kennzahlenvergleich" erweitern und die `nr`-Nummerierung der Folgeeinträge anpassen (oder als additiven Eintrag mit neuer Nr ans Ende einsortieren — OWNER-DECISION D5). Da `_resolve_page_number`/Range über **Titel** matchen, ist die exakte `nr`-Position unkritisch für die Seitenzahl, nur für die Lesbarkeit.

## Konkrete Funktionen/Signaturen #57
- Aggregator: `_build_soll_ist_kennzahlen(db, mandate) -> dict`, Helper `_compute_sollist_monte_carlo(db, mandate) -> dict` (D3).
- PDF: `_build_soll_ist_kennzahlen_flowables(data, styles) -> list`, `_fmt_sollist(kind, value) -> str`, `_sollist_color(soll, ist, higher_better)`.

## Test-Plan #57
Aggregator-Tests (`tests/test_advisory_sollist_section.py`):
1. `test_builder_returns_data_pending_without_ta` — Mandat ohne TA → `data_pending=True`, `rows == []`.
2. `test_builder_maps_all_rows_with_symmetric_keys` — gemocktes `_compute_sollist_monte_carlo` mit allen `target_/current_`-Feldern → 11 Rows, jede mit `soll`,`ist`,`higher_better`,`kind`.
3. `test_sharpe_uses_rf_80bps` — `target_annualized_return_p50_bps=580`,`target_volatility_1y_bps=1100` → Sharpe ≈ `(580−80)/1100 = 0.45`.
4. `test_loss_metrics_higher_better_false` — VaR/CVaR/DD/LossProb/Depletion haben `higher_better=False`.

PDF-Tests (`tests/test_advisory_report_pdf.py`-Stil, neue Datei `tests/pdf/test_sollist_pdf.py`):
5. `test_section_renders_header_and_rows` — Payload mit `soll_ist_kennzahlen.rows` → `pypdf extract_text()` enthält „SOLL/IST", „Sharpe", „VaR 95%".
6. `test_section_renders_data_pending_hint` — `data_pending=True` → Hinweis-Text im PDF, kein Crash.
7. `test_section_in_toc_and_anchored` — TOC-Render enthält „SOLL/IST-Kennzahlenvergleich" mit Seitenzahl; Outline-Eintrag vorhanden (#71-Synergie).
8. `test_no_third_party_brands` — analog `test_pdf_contains_no_third_party_brands_in_layout` (`test_advisory_report_pdf.py:669`).
9. `_make_minimal_payload()` (`test_advisory_report_pdf.py:35`) um einen minimalen `soll_ist_kennzahlen`-Block erweitern (sonst rendert die Sektion `data_pending` — auch ok, aber Tests 5 brauchen Daten).

## Edge-Cases #57
- **IST nicht berechenbar** (kein current-Mix gepflegt): Engine liefert `current_*`=0/leer. `_fmt_sollist` → `—`, Einfärbung neutral. Tabelle bleibt renderbar.
- **Fehlendes MC-Dict** (`data_pending`): eigener Hinweis-Pfad (Test 6).
- **Sektion mehrseitig:** unkritisch — Page-Range (#72) erfasst sie automatisch.
- **Negative Werte bei Loss-Kennzahlen:** Engine liefert VaR/CVaR/DD bereits als positive Loss-Bps (`portfolio_engine.py:3482-3491`); `_fmt_sollist` setzt das Minuszeichen für die Anzeige (konsistent zum Frontend `formatRiskLossBps`).
- **Branding:** Labels sind 5eyes-eigen, keine Dritt-Marken.

---

# OWNER-DECISIONs

- **D1 (#71 Mapping-Quelle):** section_id↔TOC-Titel. Empfehlung **Variante B** (Modul-Konstante `_SECTION_ANCHORS` im PDF-Layer, kein Aggregator-Schema-Change). Alternative A: `nr`+`section_id` in `_build_inhaltsverzeichnis()` ergänzen (invasiver, berührt Frontend-Schema-Konsumenten).
- **D2 (#72 Test-Fixture):** Soll der Render-Test eine garantiert mehrseitige Sektion erzwingen (langer Block in `_make_minimal_payload`) oder nur die reine Range-Logik unit-testen? Empfehlung: Unit-Test der Range-Logik hart + Render-Test tolerant.
- **D3 (#57 Datenbeschaffung — wichtigste Entscheidung):** Das volle symmetrische `monte_carlo`-Dict ist nicht persistiert.
  - **Variante D3a (empfohlen, On-Demand):** `_compute_sollist_monte_carlo` ruft beim Report-Build die Engine-MC-Funktion mit SOLL- **und** IST-Gewichten auf (IST-Mix aus aktuellem Bestand). Vorteil: identische Zahlen wie Frontend. Nachteil: zusätzliche MC-Latenz beim PDF-Build (mehrere Sekunden). Mitigation: `n_paths` reduzieren (z.B. 500) und Ergebnis im call-scoped Cache (`_aggregator_cache_get`, `advisory_report.py:45-58`) ablegen.
  - **Variante D3b (Persistenz):** neue Spalte `monte_carlo_sollist_json` auf `TargetAllocation` (Migration), befüllt beim `generate_target_allocation`-Lauf (`portfolio_engine.py:6593`/`:7248`). Aggregator liest nur. Vorteil: schneller PDF-Build, exakt der Lauf der dem Berater angezeigt wurde. Nachteil: DB-Migration + Engine-Schreibpfad (grösserer Scope, evtl. eigener Folge-PR).
  - Empfehlung: **D3a für diesen PR** (kein DB-Change), D3b als Folge-Optimierung notieren.
- **D4 (#57 Zeilenumfang):** CAGR-Median + Median-Reichweite aufnehmen oder weglassen? Empfehlung: **weglassen** (CAGR redundant zu P50-Rendite; Reichweite hat separate Frontend-Quelle). 11 Datenzeilen.
- **D5 (#57 TOC-Position/Nummerierung):** Neue Sektion zwischen „Zielbasierte Optimierung" und „Risikoprofilierung" einsortieren und Folge-`nr` verschieben, oder additiv ans Ende? Empfehlung: thematisch nach „Zielbasierte Optimierung" einsortieren, `nr` durchnummerieren.
- **D6 (Sektions-Nummer-Kicker):** Die „Sektion N"-Kicker im PDF sind hartkodiert pro Builder (z.B. `advisory_report.py:1159` „Sektion 11"). Beim Einfügen der neuen Sektion die Kicker der nachfolgenden Sektionen anpassen oder Kicker dynamisch aus `_SECTION_ANCHORS`-Index ableiten? Empfehlung: für diesen PR Kicker der neuen Sektion sinnvoll setzen, globale Dynamisierung als optionaler Cleanup.

---

# Datei-Touch-Liste (Implementierung)
- `5eyes-backend/services/pdf/components/table_of_contents.py` — Bookmark/Outline in `TocSectionAnchor.draw()`, `page_ranges_by_title()`, `make_toc_table`/`_toc_rows`/`resolve_toc_rows` um `page_ranges_by_title`+`section_id_by_title`, Resolver `_resolve_for_title`.
- `5eyes-backend/services/pdf/documents/advisory_report.py` — `_SECTION_ANCHORS`/`_SECTION_ID_BY_TITLE`; Pass-2 `toc_page_ranges`; `_build_all_flowables`/`_build_toc_flowables` Keywords; neue Sektion `_build_soll_ist_kennzahlen_flowables` + Formatter; Einhängen in `_build_all_flowables`.
- `5eyes-backend/services/advisory_report.py` — `_build_soll_ist_kennzahlen` + `_compute_sollist_monte_carlo`; Eintrag in `_compute_advisory_report_inner`; TOC-Kapitel in `_build_inhaltsverzeichnis`.
- (D3b nur falls gewählt) `models/allocation.py` + Migration + Engine-Schreibpfad.
- Tests: `tests/pdf/test_toc_hyperlinks.py`, `tests/pdf/test_toc_page_ranges.py`, `tests/test_advisory_sollist_section.py`, `tests/pdf/test_sollist_pdf.py`; ergänzen `_make_minimal_payload`.
