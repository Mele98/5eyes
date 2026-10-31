"""Sprint U-82 (2026-06-05): Drift-Schutz fuer Berater-Onboarding-Doku.

Verifiziert dass docs/BERATER_ONBOARDING.md die Pflicht-Sektionen +
Sprint-Verweise nicht veraltet.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARDING_PATH = REPO_ROOT / "docs" / "BERATER_ONBOARDING.md"


def _read() -> str:
    return ONBOARDING_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Existenz + Struktur
# ---------------------------------------------------------------------------

def test_onboarding_exists():
    assert ONBOARDING_PATH.exists()


def test_onboarding_has_8_sections():
    text = _read()
    for nr in range(1, 9):
        assert f"## {nr}." in text, f"Sektion {nr} fehlt"


def test_onboarding_has_self_check_checklist():
    text = _read()
    assert "Selbst-Check" in text
    # Sollte > 10 Checkboxen haben
    assert text.count("- [ ]") >= 10


# ---------------------------------------------------------------------------
# Voraussetzungen + Compliance
# ---------------------------------------------------------------------------

def test_documents_finma_zulassung():
    text = _read()
    assert "FINMA" in text
    assert "FIDLEG" in text


def test_documents_no_programming_required():
    text = _read()
    lowered = text.lower()
    assert "programmier" in lowered


# ---------------------------------------------------------------------------
# Workflows + Sprint-Refs
# ---------------------------------------------------------------------------

def test_documents_token_ttl():
    text = _read()
    assert "8h" in text or "Token-TTL" in text


def test_documents_customer_journey_order():
    text = _read()
    assert "Customer-Journey" in text or "Customer Journey" in text


def test_documents_gesamt_vs_beratungsvermoegen():
    text = _read()
    assert "Gesamt" in text
    assert "Beratungsverm" in text


def test_documents_ist_vs_soll():
    text = _read()
    assert "IST" in text
    assert "SOLL" in text


def test_documents_override_workflow_min_20_chars():
    """U-28/U-29: Override-Begruendung >= 20 Zeichen."""
    text = _read()
    assert "U-28" in text or "U-29" in text
    assert "20 Zeichen" in text or "20" in text


# ---------------------------------------------------------------------------
# Heute neu hinzugekommene Features
# ---------------------------------------------------------------------------

def test_documents_u_87_error_boundary():
    text = _read()
    assert "U-87" in text


def test_documents_u_94_optimizer_run_history():
    text = _read()
    assert "U-94" in text


def test_documents_u_95_esg_filter():
    text = _read()
    assert "U-95" in text


def test_documents_u_98_hedge_quote():
    text = _read()
    assert "U-98" in text
    assert "Hedge" in text


def test_documents_u_99_fx_refresh():
    text = _read()
    assert "U-99" in text


def test_documents_u_100_ns_calibration():
    text = _read()
    assert "U-100" in text


def test_documents_u_102_audit_whitelist():
    text = _read()
    assert "U-102" in text


# ---------------------------------------------------------------------------
# Compliance-Sektion: Pflichten-Tabelle
# ---------------------------------------------------------------------------

def test_documents_fidleg_pflichten_table():
    text = _read()
    for pflicht in (
        "Risikoprofil",
        "Eignungspr",
        "Beratungsprotokoll",
        "Konflikt",
    ):
        assert pflicht in text


# ---------------------------------------------------------------------------
# Doku-Verweise
# ---------------------------------------------------------------------------

def test_links_to_berater_readme():
    text = _read()
    assert "BERATER_README.md" in text


def test_links_to_glossar():
    text = _read()
    assert "GLOSSAR.md" in text


def test_links_to_adr_003():
    text = _read()
    assert "ADR-003" in text


def test_links_to_adr_005():
    text = _read()
    assert "ADR-005" in text


def test_documents_24_aggregator_sections():
    text = _read()
    assert "24" in text and "Sektion" in text


def test_documents_dsg_art_25():
    """DSG-Datenexport-Endpoint."""
    text = _read()
    assert "DSG" in text
    assert "data-export" in text or "Datenexport" in text


def test_documents_naechste_schritte_quartal_monat_woche():
    """Quartal/Monat/Woche-Rhythmus muss erwaehnt sein."""
    text = _read()
    assert "Quartal" in text
    assert "Monat" in text or "monatlich" in text.lower()
    assert "Woche" in text or "woechentlich" in text.lower()
