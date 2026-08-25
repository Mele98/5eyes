"""Roadmap #39 (Standpunkt 2026-08-07): FE-Toggle fuer die geschaetzte
Vermoegenssteuer in der Cashflow-Projektion (Mandat-Einstellungen-Modal).
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def test_checkbox_exists_in_mandate_settings_modal():
    html = _html()
    assert 'id="ms-tax-estimate-cashflow"' in html
    assert 'type="checkbox"' in html.split('id="ms-tax-estimate-cashflow"')[0][-80:]


def test_checkbox_included_in_reset_list():
    html = _html()
    start = html.find("openMandateSettingsModal")
    assert start != -1
    end = html.find("\n}", html.find("async function openMandateSettingsModal"))
    # Reset-Array-Zeile ist vor dem Modal-Open -- suche im ganzen Funktionsblock.
    block = html[html.find("async function openMandateSettingsModal"):end + 2]
    assert "'ms-tax-estimate-cashflow'" in block


def test_load_reads_field_from_api_response():
    html = _html()
    start = html.find("async function openMandateSettingsModal")
    end = html.find("async function saveMandateSettings")
    block = html[start:end]
    assert "m.tax_estimate_in_cashflow_enabled" in block
    assert "ms-tax-estimate-cashflow" in block


def test_save_sends_field_to_api():
    html = _html()
    start = html.find("async function saveMandateSettings")
    end = html.find("\n}", start)
    block = html[start:end]
    assert "tax_estimate_in_cashflow_enabled" in block
    assert "ms-tax-estimate-cashflow" in block
