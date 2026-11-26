"""KN5 / N-917R4-01: Kundentexte statt interner Bezeichner in Kunden-PDFs
(Einzelstellen ausserhalb des Compliance-Audit-Abschnitts; der Abschnitt selbst
in tests/test_pdf_compliance_audit_section.py, alle 12 Kunden-PDFs live im
KN3-B-Waechter fuer einen Verzehr- und einen Reserve-Fall).
Gegenproben: Mutationen in H-177 (alle rot)."""
from __future__ import annotations

import inspect


def test_internal_objective_summary_becomes_customer_text():
    from routers.pdf_reports import _customer_recommendation_summary

    assert _customer_recommendation_summary(
        "TBI V1 - strategische Soll-Allokation mit produktiver Titelselektion"
    ) == "Strategische Soll-Allokation mit Titelauswahl aus dem Produktuniversum"
    assert _customer_recommendation_summary("XYZ V2 - eigene Zielbeschreibung") == "Eigene Zielbeschreibung"
    assert _customer_recommendation_summary("Finalisierte Empfehlung") == "Finalisierte Empfehlung"
    assert _customer_recommendation_summary(None) == ""


def test_protocol_hint_without_reason_code():
    from services.pdf.documents.protokoll import _without_reason_code

    assert _without_reason_code("Kenntnislücke [KNOWLEDGE_GAP_ASSET_CLASS]: Die SAA enthält Aktien") == (
        "Kenntnislücke: Die SAA enthält Aktien")
    assert _without_reason_code("Hinweis [siehe Anhang]") == "Hinweis [siehe Anhang]"


def test_backtest_and_stress_texts_have_no_internal_names_or_third_party_brands():
    from services.pdf.components import backtest_metrics, stress_table
    from services.pdf.documents import backtest

    method = inspect.getsource(backtest)
    for raw in ("yfinance", "stooq", "asset_class_annual_returns", "TargetAllocation", "Bucket-Gewichte"):
        assert raw not in method, raw
    assert "Cumul. Return" not in inspect.getsource(stress_table)
    assert '"Recovery"' not in inspect.getsource(stress_table)
    assert 'add_row("Total-Return"' not in inspect.getsource(backtest_metrics)


def test_stress_note_and_ab_note_are_customer_texts():
    from services import advisory_report, backtest_stress

    stress = inspect.getsource(backtest_stress)
    assert '"note": "Replay mit historischen' not in stress and "Foundation-Variante mit hartcodierten Szenarien —" not in stress
    assert '"note": "Nachrechnung mit historischen Jahresrenditen' in stress
    assert "Keine zweite OptimizerPolicy" not in inspect.getsource(advisory_report)
    assert "stochastischer Engine berechnen" not in inspect.getsource(advisory_report)
