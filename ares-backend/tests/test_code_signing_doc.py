"""Sprint U-109 (2026-06-06): Drift-Schutz fuer Code-Signing-Setup-Doku."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "CODE_SIGNING.md"


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_exists():
    assert DOC.exists()


def test_documents_why_code_signing():
    text = _read()
    assert "SmartScreen" in text
    assert "Gatekeeper" in text or "macOS" in text


def test_documents_windows_ev_vs_ov():
    text = _read()
    assert "EV" in text
    assert "OV" in text


def test_documents_apple_developer_program():
    text = _read()
    assert "Apple Developer" in text
    assert "Notarization" in text


def test_documents_electron_builder_win_config():
    text = _read()
    assert "certificateFile" in text or "certificateSubjectName" in text


def test_documents_electron_builder_mac_config():
    text = _read()
    assert "Developer ID Application" in text
    assert "hardenedRuntime" in text


def test_documents_ci_secrets_strategy():
    text = _read()
    assert "Secrets" in text
    assert "WIN_CERT_PFX_BASE64" in text or "GitHub Actions" in text


def test_documents_security_hygiene():
    text = _read()
    assert "NIE" in text
    assert "Cert-Password" in text or "Cert-Files committen" in text


def test_documents_cert_renewal_flow():
    text = _read()
    assert "ablaeuft" in text or "Renewal" in text


def test_documents_bewusst_nicht_in_scope():
    text = _read()
    assert "Bewusst NICHT" in text
    assert "Cert-Kauf" in text


def test_documents_cost_transparently():
    text = _read()
    assert "CHF" in text
    assert "USD 99" in text or "Apple Developer Program" in text


def test_documents_adr_005_not_applies_to_cert():
    """ADR-005 CHF-0 ist Marktdaten-Disziplin, NICHT Code-Signing."""
    text = _read()
    assert "ADR-005" in text


def test_links_to_auto_update():
    text = _read()
    assert "AUTO_UPDATE.md" in text


def test_links_to_multi_platform_build():
    text = _read()
    assert "MULTI_PLATFORM_BUILD.md" in text
