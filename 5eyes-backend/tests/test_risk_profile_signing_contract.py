"""Frontend contract test: Risikoprofil-Karte + Berater-Signatur.

Prueft, dass der Monolith 5eyes_v2.html die versionierte/datierte
Risikoprofil-Karte in der Review-Zusammenfassung enthaelt und die
Berater-Signatur gegen den Sign-Endpoint verdrahtet ist.
"""

from pathlib import Path


FRONTEND = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND.read_text(encoding="utf-8")


def test_risk_profile_card_present_in_summary():
    html = _html()
    # Kompakte Risikoprofil-Karte mit stabilen Anker-IDs
    assert 'id="sr-riskprofile-card"' in html
    assert 'id="sr-riskprofile-profile"' in html
    assert 'id="sr-riskprofile-meta"' in html
    assert 'id="sr-riskprofile-signature"' in html
    # Karten-Titel
    assert '<span class="cht">Risikoprofil</span>' in html


def test_risk_profile_sign_button_present():
    html = _html()
    assert 'id="sr-riskprofile-sign-btn"' in html
    assert 'onclick="signRiskProfile()"' in html
    assert '>Signatur erfassen<' in html


def test_risk_profile_render_function_present():
    html = _html()
    assert "function renderReviewRiskProfileCard()" in html
    # Karte wird beim Review-Render aktualisiert
    assert "renderReviewRiskProfileCard();" in html
    # Versionierte/datierte Felder werden aus dem Risikoprofil-State gelesen
    assert "risk.client_signed_at" in html
    assert "risk.client_signed_method" in html
    assert "risk.version" in html
    assert "final_profile" in html


def test_risk_profile_sign_fetch_wired():
    html = _html()
    assert "async function signRiskProfile()" in html
    # Sign-Endpoint POST /mandates/{id}/risk-profile/sign mit {note}
    assert "'/mandates/'+mid+'/risk-profile/sign'" in html
    assert "{note:note}" in html


def test_risk_profile_card_relocated_into_overview():
    html = _html()
    # Karte wird durch normalizeReviewLayout in die Overview-Zone gehoben,
    # damit sie nicht in der ausgeblendeten Zusammenfassung verschwindet.
    assert "var riskProfileCard=document.getElementById('sr-riskprofile-card');" in html
    assert "[heroCard,summaryKpis,riskProfileCard,cockpit]" in html


def test_risk_profile_card_renders_signoff_state_and_references():
    """RISK-PROFILE-SIGNOFF-001: die Karte zeigt den Signoff-Zustand aus dem
    Backend (signoff_state), die Signoff- und Decision-Referenz, die neue
    Signaturpflicht nach Override und die Altsignatur ausdruecklich
    ungebunden. 'advisor_recorded' wird nicht als Kundensignatur ausgegeben."""
    html = _html()
    assert "function riskSignoffState(risk)" in html
    assert "risk.signoff_state" in html
    assert "risk.signoff_id" in html and "risk.signoff_hash" in html
    assert "risk.override_decision_id" in html and "risk.override_decision_hash" in html
    assert "neue Signatur erforderlich" in html
    assert "Altsignatur, nicht an Decision gebunden" in html
    assert "signoffState==='remediation_required'" in html
    assert "'vom Berater erfasst'" in html
    assert 'id="sr-riskprofile-signoff-ref"' in html


def test_risk_profile_sign_sends_concurrency_expectations():
    html = _html()
    assert "payload.expected_assessment_version=" in html
    assert "payload.expected_override_decision_id=" in html
    assert "payload.expected_signoff_id=" in html
    assert "API.post('/mandates/'+mid+'/risk-profile/sign',payload)" in html
