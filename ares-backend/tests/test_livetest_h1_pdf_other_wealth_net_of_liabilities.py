"""Live-Test 2026-11 H1 -- Anlagestrategie-PDF addierte die Hypothek zum
"Anderen Vermoegen".

Befund (Live-Test, Mandat mit ETW CHF 500'000 und Hypothek CHF 300'000):
Die PDF-Tabelle "Anderes Vermoegen" listete beide Positionen mit positivem
Betrag und bildete daraus "Total Anderes Vermoegen 800'000". Die App zeigt
korrekt "Total Anderes (netto) CHF 200'000" (Vermoegens-Tab,
``otherTotal = totalChf(other) - totalChf(liabilities)``).

Ursache: ``current_value_rappen`` ist fuer JEDE Position nichtnegativ, die
Richtung laeuft ueber ``assignment`` ('Verbindlichkeit', siehe
LIABILITY-PUBLICATION-001 in services/advisory_report.py). Der PDF-Pfad
``routers/pdf_reports.py::_other_wealth_positions`` gab keine Richtung weiter,
und ``vermoegensuebersicht._make_other_wealth_table`` summierte alles positiv.

Gegenprobe: die Tests pruefen den gerenderten PDF-Text (pypdf) bzw. die
Router-Daten, nicht eine Hilfsfunktion; ohne den Fix enthaelt der Text
"800'000" als Total und keine negative Hypothek.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfReader
from reportlab.platypus import SimpleDocTemplate

from services.pdf.components.vermoegensuebersicht import make_vermoegensuebersicht_section


def _total_text(text: str) -> str:
    """Zeile "Total Anderes Vermoegen ..." samt Betrag (pypdf trennt Zellen
    teils auf eigene Zeilen)."""
    lines = text.splitlines()
    idx = next(i for i, line in enumerate(lines) if "Total Anderes Vermögen" in line)
    return " ".join(lines[idx:idx + 2])


def _render(flowables) -> str:
    buf = BytesIO()
    SimpleDocTemplate(buf).build(flowables)
    reader = PdfReader(BytesIO(buf.getvalue()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


ADVISORY = [{"asset_class": "liquidity", "sub_asset_class": "Konto", "current_amount_rappen": 150_000_00}]
OTHER = [
    {"label": "ETW Biel", "amount_rappen": 500_000_00, "kind": "Immobilien", "is_liability": False},
    {"label": "EGT Biel Hypo", "amount_rappen": 300_000_00, "kind": "Hypothek", "is_liability": True},
]


def test_other_wealth_total_is_net_of_mortgage():
    text = _render(make_vermoegensuebersicht_section(ADVISORY, OTHER))
    assert "800'000" not in text, "Hypothek wurde zum anderen Vermoegen addiert"
    assert "Total Anderes Vermögen (netto)" in text
    total_line = _total_text(text)
    assert "200'000" in total_line
    # Die Verbindlichkeit ist als Abzug erkennbar, nicht als Aktivum.
    assert "−300'000" in text


def test_liability_without_asset_gives_negative_net_total():
    other = [{"label": "Privatkredit", "amount_rappen": 40_000_00, "kind": "Custom", "is_liability": True}]
    text = _render(make_vermoegensuebersicht_section(ADVISORY, other))
    total_line = _total_text(text)
    assert "−40'000" in total_line


def test_router_marks_liability_assignment(monkeypatch):
    """Der Router muss die Richtung ueber die kanonische Assignment-Klassifikation
    weitergeben (nicht ueber Positionstyp-Stichworte)."""
    import routers.pdf_reports as pdf_reports

    rows = [
        SimpleNamespace(label="ETW Biel", current_value_rappen=500_000_00, currency="CHF",
                        position_type="Immobilien", assignment="Anderes Vermögen"),
        SimpleNamespace(label="EGT Biel Hypo", current_value_rappen=300_000_00, currency="CHF",
                        position_type="Hypothek", assignment="Verbindlichkeit"),
        SimpleNamespace(label="Konto", current_value_rappen=150_000_00, currency="CHF",
                        position_type="Liquidität", assignment="Beratungsvermögen"),
    ]

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return rows

    db = SimpleNamespace(query=lambda *_a, **_k: _Q())
    mandate = SimpleNamespace(client_id="c1", base_currency="CHF")
    out = pdf_reports._other_wealth_positions(mandate, db)
    by_label = {item["label"]: item for item in out}
    assert set(by_label) == {"ETW Biel", "EGT Biel Hypo"}
    assert by_label["EGT Biel Hypo"]["is_liability"] is True
    assert by_label["ETW Biel"]["is_liability"] is False
