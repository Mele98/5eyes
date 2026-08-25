# Codex-Sprint U-P28 — Berater-Overrides für Advisory-Report (MandateReportNotes)

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25.
> **Voraussetzung:** U-P21 (Backend-Aggregator) ✅. U-P23 (Frontend-Phase-1) und
> U-P26 (PDF) parallel möglich — dieser Sprint blockiert sie nicht.
> **Audit-Quelle:** §6 Top-Empfehlung #7 (Audit-Bericht vom 2026-05-25).
> **Größenordnung:** klein bis mittel — ~6-10 Stunden, 3 PRs.

---

## Zweck

Heute hat der Advisory-Report einige Text-Felder, die der Berater pro
Mandat **individuell überschreiben** sollte, aber sie sind hartcodierte
Default-Platzhalter im Aggregator:

| Sektion | Feld | Heute |
|---|---|---|
| Asset Allocation | `anmerkungen` | Auto-Text aus Drift-Status |
| Risikowährungen | `erklaerung` | Auto-Text aus CHF-Anteil |
| Branchen | `analyse` | Auto-Text aus Sektor-Drift |
| Weiteres Vorgehen | `block_optimierungen` | "(Vom Berater zu ergänzen …)" |
| Weiteres Vorgehen | `block_zielstrategie` | "(Vom Berater zu ergänzen …)" |
| Weiteres Vorgehen | `offene_fragen` | `[]` |
| Weiteres Vorgehen | `naechster_termin` | `None` |
| Weiteres Vorgehen | `todos` | `[]` |
| Weiteres Vorgehen | `dokumente` | `[]` |

**Wert:** Berater pflegt pro Mandat sein individuelles Vorgehen +
Kommentare, ohne PDF-Code anzufassen. **Single Source of Truth bleibt
der Aggregator** — der konsumiert Overrides falls vorhanden, sonst
fallback auf Auto-Default.

---

## Architektur

### Daten-Modell `models/review.py` (NEU im File, anhängen am Ende)

```python
class MandateReportNotes(Base):
    """Berater-individuelle Texte für den Advisory-Report (Sprint U-P28).

    Eine Zeile pro Mandat (UNIQUE auf mandate_id). Wird durch den
    Aggregator services.advisory_report.py konsumiert; fehlende Felder
    fallen auf Auto-Defaults zurück.
    """
    __tablename__ = "mandate_report_notes"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False, unique=True)

    # Sektion Asset Allocation
    aa_anmerkungen = Column(String)

    # Sektion Risikowährungen
    waehrungen_erklaerung = Column(String)

    # Sektion Branchen
    branchen_analyse = Column(String)

    # Sektion Weiteres Vorgehen
    vorgehen_block_optimierungen = Column(String)
    vorgehen_block_zielstrategie = Column(String)
    vorgehen_offene_fragen_json = Column(String)  # ["frage 1","frage 2",...]
    vorgehen_naechster_termin = Column(String)    # ISO-Datum oder freier Text
    vorgehen_todos_json = Column(String)          # ["todo 1",...]
    vorgehen_dokumente_json = Column(String)      # ["Identifikationspapier", ...]

    # Audit-Anchor
    last_edited_by = Column(String, ForeignKey("users.id"), nullable=False)
    last_edited_at = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
```

### Schema-Migration

Da es eine **neue Tabelle** ist (nicht nur neue Column), kann
`Base.metadata.create_all(engine)` sie idempotent erzeugen.
Pattern in `database.py::ensure_runtime_tables()` (NEU) oder direkt im
bootstrap. Plus SQL-DDL in `5eyes_schema_v4.0_FINAL.sql` ergänzen.

---

## Endpoints

```python
# routers/allocation.py oder routers/reporting.py (NEU)

@router.get("/mandates/{mandate_id}/report-notes")
def get_report_notes(mandate_id, db, current_user) -> dict:
    """Liefert die Berater-Overrides; leeres Objekt wenn noch nichts gepflegt."""

@router.put("/mandates/{mandate_id}/report-notes")
def put_report_notes(mandate_id, body: ReportNotesUpdate, db, current_user):
    """Upsert. Berater-Auth (require_advisor)."""
```

Pydantic-Schema:
```python
class ReportNotesUpdate(BaseModel):
    aa_anmerkungen: str | None = None
    waehrungen_erklaerung: str | None = None
    branchen_analyse: str | None = None
    vorgehen_block_optimierungen: str | None = None
    vorgehen_block_zielstrategie: str | None = None
    vorgehen_offene_fragen: list[str] | None = None
    vorgehen_naechster_termin: str | None = None
    vorgehen_todos: list[str] | None = None
    vorgehen_dokumente: list[str] | None = None
```

---

## Aggregator-Integration

In `services/advisory_report.py`:
- Notes **einmal** am Entry-Point laden:
  ```python
  notes = db.query(MandateReportNotes).filter_by(mandate_id=mandate.id).first()
  ```
- An die 4 betroffenen Sektion-Builder weitergeben:
  - `_build_asset_allocation(dc, notes=notes)` — wenn `notes.aa_anmerkungen`
    vorhanden, nutze diesen Text; sonst aktueller Auto-Default
  - analog `_build_risikowaehrungen`, `_build_branchen`, `_build_weiteres_vorgehen`

---

## Frontend-UI

In der Reporting-Sub-App: **Edit-Modus für Berater**:
- Floating-Button rechts oben in jeder Sektion mit Override-Möglichkeit
  („✎ Bearbeiten")
- Klick öffnet Editor-Drawer (rechts-side) mit Textarea + Save-Button
- PUT-Call → Reload des aktuellen Reports
- Visueller Unterschied: Auto-Default-Text in `text-ink-muted`,
  Berater-Override in `text-ink` mit kleinem „Bearbeitet"-Tag

In der Hauptapp `5eyes_v2.html`: KEIN Edit — alles über die Reporting-
Sub-App.

---

## Tests

`tests/test_mandate_report_notes.py` (NEU):
- 8-10 Tests: CRUD über Endpoint, Aggregator-Override-Logik,
  Defaults-Fallback, Audit-Anchors gesetzt

---

## PR-Aufteilung

| PR | Inhalt |
|---|---|
| **PR A** | Daten-Modell + Migration + Endpoints + Tests |
| **PR B** | Aggregator-Integration (Notes ↔ Sektionen) + Aggregator-Tests |
| **PR C** | Frontend Edit-Drawer + PUT-Call |

---

## Verboten

- **NICHT** alle Text-Felder als generisch „freier-Text"-Blob speichern
  — saubere getrennte Spalten pro Feld.
- **NICHT** Notes synchron im PDF-Code lesen — der PDF-Code (U-P26)
  konsumiert schon den Aggregator, Override greift automatisch.
- **KEINE Dritt-Marken** im Default-Text (Memory-Regel).

---

## Acceptance

1. Berater öffnet Sektion „Weiteres Vorgehen" in der Reporting-App
   → „✎ Bearbeiten"
2. Schreibt eigene Vorgehen-Texte + 3 To-Dos + Termin
3. Speichern → Sektion zeigt sofort die neuen Texte
4. PDF (`advisory-report.pdf`) heruntergeladen → identische Texte
5. Bei anderem Mandat: leere Felder → Default-Auto-Text wie bisher
6. Audit-Anchor (`last_edited_by`, `last_edited_at`) korrekt gesetzt
