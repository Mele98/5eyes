"""WITHDRAWAL-TIMING-001 (Phase 0, Honesty-Fix): der Router/UI speichert eine
exakte 'day'|'month'-Praezision fuer einmalige Cashflows und zeigt dem Berater
ein konkretes Datum an -- aber contribution_for_year() (services/
cashflow_timeline.py) prueft fuer einmalige Cashflows nur event_date.year ==
year; Tag und Monat haben KEINE Wirkung auf die Jahresprojektion.

Phase 0 ist bewusst KEIN Rechenfix (das waere die groessere Phase-1-Option
mit echter Sub-Jahres-Mechanik), sondern eine Ehrlichkeits-Korrektur: UI und
API-Schema muessen die tatsaechlich modellierte Jahres-Konvention offen
kommunizieren, statt eine Tages-/Monatspraezision vorzutaeuschen, die das
Modell nicht hat.

Diese Tests sperren:
- die neue Hinweis-Formulierung im Cashflow-Timing-Label (Listenzeilen-Anzeige)
- die neue Hinweis-Formulierung im Cashflow-Modal (syncCashflowModalState)
- die neue Field-description auf schemas.wealth.timing_precision
"""
from pathlib import Path

from schemas.wealth import CashflowCreate, CashflowUpdate, CashflowResponse


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_cashflow_timing_label_marks_date_as_reference_only():
    html = _html()
    assert "function cashflowTimingLabel(" in html
    assert "Referenzdatum, ohne Wirkung auf die Jahresprojektion" in html


def test_cashflow_modal_hint_marks_date_as_documentation_only():
    html = _html()
    assert "function syncCashflowModalState(" in html
    assert (
        "Hinweis: Das Datum ist reine Dokumentation -- die Jahresprojektion "
        "verbucht den vollen Betrag im Kalenderjahr des Datums, unabhängig "
        "vom genauen Tag/Monat."
    ) in html


def test_cashflow_modal_hint_appended_for_all_one_off_variants():
    html = _html()
    # Muss NACH dem Kapitalbezug-Hinweis-Override stehen, damit die
    # Ehrlichkeits-Klarstellung auch fuer Kapitalbezuege (3a/PK/FZK) sichtbar
    # bleibt, statt vom spezifischeren Kapitalbezug-Text ueberschrieben zu werden.
    capital_idx = html.index("Kapitalzufluss wird als einmaliger Nettozufluss")
    honesty_idx = html.index("hint.textContent+=' Hinweis: Das Datum ist reine Dokumentation")
    assert honesty_idx > capital_idx
    assert "if(isOneOffCashflow(freq)&&hint){" in html


def test_schema_timing_precision_description_references_finding():
    for model in (CashflowCreate, CashflowUpdate, CashflowResponse):
        field = model.model_fields["timing_precision"]
        assert field.description is not None
        assert "WITHDRAWAL-TIMING-001" in field.description
        assert "KEINE Wirkung auf die Projektionsrechnung" in field.description
