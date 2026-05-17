# Sprint 5 — PDF-Engine (Kundendokumente)

**Datum:** 2026-05-17
**Status:** Spec / aktiv
**Vorgaenger:** Standortanalyse §C.3 — letzter P1-UX-Gap zu 3eyes.

## 0. Problem

Aktuell: Berater drueckt Strg-P im Browser → Print-Dialog → "Save as PDF".
Resultat: Browser-Print-Qualitaet (Header/Footer von Browser, Skalierungs-
artefakte, keine Kontrolle ueber Seitenumbruch, keine Branding-Optionen).

**3eyes liefert:** Server-seitig generierte PDF-Reports in
Beraterqualitaet (Header mit Logo, Footer mit Audit-Hash, gezielte
Seitenumbrueche, Tabellen-Formatierung).

**Asset-Allocation-Relevanz:** Indirekt — Kundendokumente sind das
*Lieferprodukt* der Beratung. Schlechte PDFs → unprofessioneller Eindruck
→ kein Kundenvertrauen.

## 1. Loesung

**Bibliothek: ReportLab** (pure-Python, PyInstaller-tauglich, kein
Native-Binary). Verworfen wurden:
- WeasyPrint: braucht GTK/Cairo-DLLs auf Windows → PyInstaller-Probleme
- xhtml2pdf: CSS-Support zu limitiert fuer professionelle Reports
- Playwright/Chromium: ~100 MB Binary, Overkill fuer Reports

**Trade-off**: ReportLab erfordert Python-Code-Templates statt HTML/CSS.
Aufwand pro Template hoeher, aber: vollstaendige Kontrolle, deterministisch,
keine externen Dependencies.

## 2. Modul-Struktur

```
5eyes-backend/
├── services/pdf/
│   ├── __init__.py
│   ├── base.py                   # PDFRenderer-Protocol + PDFContext
│   ├── reportlab_renderer.py     # ReportLab-Impl (Foundation)
│   ├── styles.py                 # Farben, Schriftarten, Spacings
│   ├── components/               # Wiederverwendbare PDF-Bausteine
│   │   ├── header.py             # Titel + Logo + Datum
│   │   ├── footer.py             # Seitenzahl + Audit-Hash + Disclaimer
│   │   ├── table.py              # SAA-Tabelle, Cashflow-Tabelle
│   │   ├── pie_chart.py          # SAA-Tortendiagramm (ReportLab-graphics)
│   │   └── line_chart.py         # MC P10/P50/P90-Linien
│   └── documents/                # Konkrete Dokumente
│       ├── anlagestrategie.py    # Anlagestrategie-Bericht
│       ├── risikoprofil.py       # Risikoprofil-Bericht
│       └── quartalsbericht.py    # Phase 2+ (optional)
├── api/pdf.py                    # FastAPI-Endpoints
└── tests/pdf/
    ├── test_base.py
    ├── test_reportlab_renderer.py
    ├── test_components/
    └── test_documents/
```

## 3. Core-Interface

```python
# services/pdf/base.py
@dataclass(frozen=True)
class PDFContext:
    """Eingabe fuer alle PDF-Renderer."""
    mandate_name: str
    advisor_name: str
    advisor_org: str | None
    report_date: date
    audit_hash: str | None     # SHA-256 der zugrundeliegenden Daten
    locale: str = "de-CH"      # de-CH, de-DE, fr-CH, en-US
    
class PDFRenderer(Protocol):
    def render_anlagestrategie(
        self, ctx: PDFContext, data: AnlagestrategieData
    ) -> bytes: ...
    
    def render_risikoprofil(
        self, ctx: PDFContext, data: RisikoprofilData
    ) -> bytes: ...
```

## 4. Phasen-Plan

### Phase 1 — Foundation (diese Session, ~2h)
- services/pdf/base.py: Protocol + PDFContext
- services/pdf/reportlab_renderer.py: minimaler ReportLab-Setup
- services/pdf/styles.py: 5eyes-Designsystem (Farben, Fonts)
- services/pdf/components/header.py + footer.py
- Test: PDF-Validitaet (Magic Bytes %PDF-, PageCount >= 1)
- **~20 Tests**

### Phase 2 — Anlagestrategie-Dokument (diese Session, ~2h)
- services/pdf/documents/anlagestrategie.py
- Layout: Titel, Mandant, SAA-Tabelle, SAA-Tortendiagramm,
  MC-Statistik (P10/P50/P90), Disclaimer
- services/pdf/components/pie_chart.py: SAA-Torte mit ReportLab-graphics
- api/pdf.py: GET /api/mandate/{id}/anlagestrategie.pdf
- DataLoader: lest Mandate + TargetAllocation + LastOptimizerRun aus DB
- **~15 Tests**

### Phase 3 — Risikoprofil-Dokument (naechste Session, ~1.5h)
- services/pdf/documents/risikoprofil.py
- FINMA-konform: W305.02-Tabelle (Knowledge), W305.03-Tabelle (Erfahrung)
- API-Endpoint

### Phase 4 — Quartalsbericht (Phase optional)
- Performance vs. Benchmark
- Rebalancing-Empfehlungen
- Lifegap-Update

## 5. Out-of-Scope

- Whitelabel-Branding (Berater-Logo) — Phase 4+
- E-Signing / DocuSign-Integration
- PDF-Verschluesselung / Wasserzeichen
- Mehrsprachigkeit ausser de-CH (Phase 4+)

## 6. Erfolgskriterien

| Kriterium | Messbar |
|---|---|
| PDF-Magic-Bytes korrekt | bytes[:4] == b'%PDF' |
| PageCount >= 1 | via reportlab oder PyPDF2 |
| Datei-Groesse plausibel | 30 KB < size < 500 KB |
| Enthaelt Mandant-Name | bytes contains b'<name>' |
| FINMA-Disclaimer im Footer | bytes contains "Schaetzwerte" |
| Endpoint < 2s | time.perf_counter Benchmark |
| Backwards-Compat | keine Brueche in bestehenden Tests |

## 7. Bibliotheks-Vergleich

| Lib | Pro | Contra | 5eyes-Fit |
|---|---|---|---|
| **ReportLab** | pure-Python, stabil, voll-deterministisch, PyInstaller-OK | Code-Templates, kein HTML | ✅ |
| WeasyPrint | HTML/CSS3 voll | GTK+/Cairo, Windows-PyInstaller-Hoelle | ❌ |
| xhtml2pdf | pure-Python | CSS limited (kein flex/grid) | ❌ |
| Playwright | voller Chromium | ~100 MB binary | ❌ |
| wkhtmltopdf | HTML komplett | deprecated, alte WebKit | ❌ |
