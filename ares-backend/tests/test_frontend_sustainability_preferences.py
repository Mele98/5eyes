"""E2 Nachhaltigkeitspraeferenzen (Dok. 106): Maskenteil
``sustainability-preferences.js`` (ausgelagerter Monolith-Teil, eigenes Budget).

Vertragstests ohne Browser (die Verhaltensprobe laeuft separat mit
Playwright): Einbindung direkt nach dem Risikoprofil-Teil, Texte nur vom
Server (eine Quelle, Claim-Waechter-geprueft), keine Vorauswahl, harter
Ausschluss gesperrt, Payload mit Version und Definitions-Hash, Untergrenze in
den Strategiebausteinen sichtbar, keine Claims "nachhaltig"/"verantwortungs-
bewusst" im Modul.
"""
from __future__ import annotations

import re
from pathlib import Path

from core import sustainability_preference as sp
from services.portfolio_engine_payload import ESG_CUSTOMER_CLAIM_LABELS
from tests.monolith_source import EXTRACTED_PARTS, include_tag, read_monolith_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "ares-desktop" / "frontend"
MODULE = FRONTEND / "sustainability-preferences.js"


def _module() -> str:
    return MODULE.read_text(encoding="utf-8")


def test_module_is_an_extracted_part_loaded_after_the_risk_profile_part():
    names = [name for name, _kind in EXTRACTED_PARTS]
    assert names.index("risk-questionnaire-v2.js") < names.index("sustainability-preferences.js")
    bundle = read_monolith_bundle()
    assert include_tag("sustainability-preferences.js", "js") not in bundle  # inline gebuendelt
    assert bundle.index("RISK_Q10_BAND_FOOTNOTE") < bundle.index("var SUST=")
    assert "sustInstallWrappers();" in bundle


def test_texts_come_from_the_server_definition():
    src = _module()
    assert "/sustainability-preferences/definition" in src
    assert "definition_hash:SUST.definition.definition_hash" in src
    assert "questionnaire_version:SUST.definition.questionnaire_version" in src
    # Keine Kopie der Fragetexte im Client (eine Quelle).
    for question in sp.QUESTIONS:
        assert question["text"] not in src
        for option in question["options"]:
            if len(option["label"]) > 20:
                assert option["label"] not in src


def test_no_preselection_and_hard_exclusion_locked():
    src = _module()
    assert not re.search(r"type=\"radio\"[^>]*checked", src)
    assert "id=\"sust-hard\" disabled" in src
    assert "hard_exclusion_requested:false" in src
    assert "'declined'" in src  # Keine Angabe getrennt von "Nicht relevant"


def test_module_strings_contain_no_product_claims():
    """Alle sichtbaren Zeichenketten des Moduls (JS-String-Literale)."""
    literals = re.findall(r"'((?:[^'\\\n]|\\.)*)'", _module())
    assert literals
    for literal in literals:
        assert not sp.customer_text_claim_hits(literal, ESG_CUSTOMER_CLAIM_LABELS), literal


def test_floor_badge_and_journey_hooks():
    src = _module()
    assert "Kundenpräferenz" in src
    assert "loadCurrentRiskAssessment=function" in src
    assert "openAllocationPreferencesModal=function" in src
    assert "review_notice" in src  # Eignungspruefung faellig = Hinweis


def test_allocation_stale_state_is_reloaded_from_the_server_on_every_visit():
    """N-888-11: nach neuem Login zeigt die Asset Allokation den Status
    "veraltet" wieder (Server-Ableitung), blendet "Portfolio umsetzen" aus."""
    src = _module()
    assert "go=function(p)" in src and "if(p==='al')" in src
    body = src[src.index("function sustStaleNotice()"):src.index("var _sustBaseGo=null;")]
    assert "/sustainability-preferences" in body
    assert "markStrategyDirty(notice,true)" in body
    assert "btn-portfolio-umsetzen" in body and "btn.disabled=true" in body
    # N-888-14: nach jedem Laden der Strategie erneut anwenden, Button ueber
    # dieselbe Bedingung (Verhalten: test_livetest_n888_14_*).
    assert "loadCurrentAllocationResult=function" in src
    assert "syncPortfolioUmsetzenButtonVisibility=function" in src
