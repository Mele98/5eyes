"""E2 Nachhaltigkeitspraeferenzen (Dok. 106): Maskenteil
``sustainability-preferences.js`` (ausgelagerter Monolith-Teil, eigenes Budget).

Vertragstests ohne Browser (die Verhaltensprobe laeuft separat mit
Playwright): Einbindung direkt nach dem Risikoprofil-Teil, Texte nur vom
Server (eine Quelle, Claim-Waechter-geprueft), keine Vorauswahl, zuerst nur
Frage 1, Ausschluesse nur wie vom Server angeboten, Payload mit Version und
Definitions-Hash, A11y-Semantik, Mandatswechsel ohne Restzustand, keine Claims
"nachhaltig"/"verantwortungsbewusst" im Modul.
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


def test_module_is_an_extracted_part_loaded_after_the_monolith_core():
    # E2 (Owner-Entscheid 2026-11-08): ohne Fragebogen v2 -- das Modul ist
    # der letzte Teil und haengt sich in loadCurrentRiskAssessment ein.
    names = [name for name, _kind in EXTRACTED_PARTS]
    assert "risk-questionnaire-v2.js" not in names
    assert names[-1] == "sustainability-preferences.js"
    bundle = read_monolith_bundle()
    assert include_tag("sustainability-preferences.js", "js") not in bundle  # inline gebuendelt
    assert bundle.index("async function loadCurrentRiskAssessment(") < bundle.index("var SUST=")
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


def test_no_preselection_and_question_one_first():
    src = _module()
    assert not re.search(r"type=\"radio\"[^>]*checked", src)
    assert "'declined'" in src  # Keine Angabe getrennt von "Nicht relevant"
    # Zuerst nur Frage 1: Folgefragen und Abschluss sind verborgen, bis
    # Frage 1 beantwortet ist; Folgefragen nur bei "Ja".
    assert '<div id="sust-yes-block" hidden>' in src
    assert '<div id="sust-finish" hidden>' in src
    assert "yes.hidden=q1!=='yes';" in src
    assert "finish.hidden=!q1;" in src
    # Keine Hydrierung frueherer Antworten (keine Vorauswahl durch Ares).
    assert "sustHydrate" not in src


def test_exclusions_are_offered_only_as_the_server_allows():
    """Nur Erfuellbares anbieten (N-901-06): Optionen werden bei jedem An-/
    Abwaehlen gegen die LAUFENDE Auswahl vom Server neu bewertet; ungewaehlte
    nicht kombinierbare sind disabled mit Grund (aria-describedby), gewaehlte
    bleiben abwaehlbar."""
    src = _module()
    assert "state.exclusion_options" in src
    assert "/sustainability-preferences/exclusion-options" in src
    assert "addEventListener('change',sustRefreshExclusions)" in src
    assert "var off=!o.available&&!cb.checked;" in src
    assert "cb.setAttribute('aria-describedby','sust-excl-why-'+o.key)" in src


def test_waiver_only_for_advisory_mandates():
    src = _module()
    assert "if(st.waiver_allowed){" in src
    assert "preference_waived:waived" in src


def test_module_strings_contain_no_product_claims():
    """Alle sichtbaren Zeichenketten des Moduls (JS-String-Literale)."""
    literals = re.findall(r"'((?:[^'\\\n]|\\.)*)'", _module())
    assert literals
    for literal in literals:
        assert not sp.customer_text_claim_hits(literal, ESG_CUSTOMER_CLAIM_LABELS), literal


def test_accessibility_semantics():
    src = _module()
    assert 'role="alert" tabindex="-1"' in src  # Fehlerzusammenfassung
    assert 'role="status" aria-live="polite"' in src  # Zustand
    assert "<fieldset id=\"sust-q1\"" in src and "<legend" in src
    assert "setAttribute('aria-invalid','true')" in src
    assert "box.focus()" in src
    # Jede Eingabe hat ein Label (for=id).
    assert "for=\"sust-channel\"" in src and "for=\"sust-confirm\"" in src


def test_mandate_switch_clears_state_before_loading():
    src = _module()
    body = src[src.index("function sustLoad(mid){"):src.index("var _sustBaseLoadRisk=null;")]
    assert "SUST.state=null;SUST.mandateId=null;" in body
    assert "old.innerHTML='';" in body
    assert "seq!==SUST.loadSeq" in body
    assert "loadCurrentRiskAssessment=function" in src


def test_e2b_strategy_blocks_take_over_customer_exclusions_read_only():
    """E2b: Kundenausschluss -> Tilt "Ausschliessen", deaktiviert, Hinweis
    "aus Kundenpraeferenz" mit Link zurueck; nicht erfuellbare Optionen
    ausgegraut mit Grund (Server-Abdeckung)."""
    src = _module()
    body = src[src.index("function sustApplyStrategyBlocks(){"):src.index("function sustLoadCoverage(mid){")]
    assert "sel.value='exclude'" in body and "sel.disabled=true;" in body
    assert "Ausschliessen · aus Kundenpräferenz" in body
    assert "go('rp')" in body
    assert "o.disabled=!!blocked" in body
    assert "'aa-product-no-leverage','noLeverage'" in body and "'aa-product-no-structured','noStructured'" in body
    assert "['required','hedgingRequired'],['chf_only','chfOnly']" in body
    assert "setAttribute('aria-describedby'" in body
    assert "/strategy-option-coverage" in src


def test_allocation_stale_state_is_reloaded_from_the_server_on_every_visit():
    """N-888-11/14/16 (uebernommen): Status "veraltet" vom Server je Mandat,
    "Portfolio umsetzen" folgt genau dieser Bedingung."""
    src = _module()
    assert "go=function(p)" in src and "if(p==='al')" in src
    body = src[src.index("function sustStaleNotice()"):src.index("var _sustBaseLoadRisk=null;")]
    assert "/sustainability-preferences" in body
    assert "markStrategyDirty(notice,true)" in body
    assert "btn.disabled=stale;" in body and "btn.disabled=true" not in body
    assert "loadCurrentAllocationResult=function" in src
    assert "syncPortfolioUmsetzenButtonVisibility=function" in src
