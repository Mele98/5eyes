"""Sprint U-79 (2026-06-05): Drift-Schutz fuer Berater-Handbuch.

Verifiziert dass docs/BERATER_README.md die Kern-Workflows + heute
neu hinzugekommenen Features (U-94/U-95/U-98/U-99/U-100/U-102/U-103/
U-104) erwaehnt. Bei Drift -> Test schlaegt fehl, Doc muss
nachgezogen werden.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BERATER_PATH = REPO_ROOT / "docs" / "BERATER_README.md"


def _read() -> str:
    return BERATER_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Existenz + Mindest-Content
# ---------------------------------------------------------------------------

def test_berater_readme_exists():
    assert BERATER_PATH.exists()


def test_berater_readme_has_table_of_contents():
    text = _read()
    assert "Inhalt" in text
    # 11 Sektionen
    for nr in range(1, 12):
        assert f"{nr}." in text or f"## {nr}" in text


# ---------------------------------------------------------------------------
# Kern-Workflows
# ---------------------------------------------------------------------------

def test_documents_customer_journey_order():
    """Stammdaten -> Cashflows -> Risikoprofil -> SAA -> Portfolio."""
    text = _read()
    assert "Stammdaten" in text
    assert "Cashflows" in text
    assert "Risikoprofil" in text
    assert "SAA" in text
    assert "Portfolio" in text


def test_documents_token_ttl():
    text = _read()
    assert "Token" in text or "TTL" in text
    assert "8h" in text


def test_documents_gesamt_vs_beratungsvermoegen():
    """Kerntrennung: Gesamtvermoegen (Cashflow) vs Beratungsvermoegen (SAA/Portfolio)."""
    text = _read()
    assert "Gesamtverm" in text
    assert "Beratungsverm" in text


def test_documents_risk_profile_override_rules():
    """U-28/U-29: Override-Begruendung mit Mindestlaenge + Phrase-Blacklist."""
    text = _read()
    assert "Override" in text
    assert "20" in text  # Mindestlaenge
    assert "U-28" in text or "U-29" in text


def test_documents_re_validation_12_months():
    """Erkenntnisse-Sektion Risikoprofil: aelter 12 Monate -> rot/gelb."""
    text = _read()
    assert "12 Monate" in text


def test_documents_advisory_log_finma_pflicht():
    text = _read()
    lowered = text.lower()
    assert "beratungsprotokoll" in lowered
    assert "finma" in lowered
    assert "auto-log" in lowered or "automatisch" in lowered


# ---------------------------------------------------------------------------
# Heute neu hinzugekommene Features (Sprint-Referenzen)
# ---------------------------------------------------------------------------

def test_documents_u_94_optimizer_run_history():
    text = _read()
    assert "U-94" in text
    assert "optimizer_run_history" in text


def test_documents_u_95_esg_sfdr_filter():
    text = _read()
    assert "U-95" in text
    assert "SFDR" in text
    assert "sfdr_class" in text or "Art. 6" in text or "Art. 8" in text


def test_documents_u_98_currency_hedge():
    text = _read()
    assert "U-98" in text
    assert "Hedge" in text


def test_documents_u_99_fx_refresh():
    text = _read()
    assert "U-99" in text
    assert "fx-rates/refresh-now" in text


def test_documents_u_100_ns_calibration():
    text = _read()
    assert "U-100" in text
    assert "Nelson-Siegel" in text or "NS-" in text


def test_documents_u_102_audit_trail():
    text = _read()
    assert "U-102" in text
    assert "Audit-Log" in text


def test_documents_u_103_policy_archive():
    text = _read()
    assert "U-103" in text
    assert "Archive" in text or "Archiv" in text


def test_documents_u_104_run_cleanup():
    text = _read()
    assert "U-104" in text
    assert "cleanup" in text.lower() or "Cleanup" in text


def test_documents_u_87_error_boundary():
    text = _read()
    assert "U-87" in text
    assert "Anzeigefehler" in text or "ErrorBoundary" in text


# ---------------------------------------------------------------------------
# Aggregator + Anzahl Sektionen
# ---------------------------------------------------------------------------

def test_documents_24_aggregator_sections():
    text = _read()
    assert "24 Sektionen" in text or "Sektionen 1-24" in text


def test_documents_aggregator_function_name():
    text = _read()
    assert "compute_advisory_report" in text


# ---------------------------------------------------------------------------
# Doku-Verweise
# ---------------------------------------------------------------------------

def test_documents_links_to_glossar():
    text = _read()
    assert "GLOSSAR.md" in text


def test_documents_links_to_adrs():
    text = _read()
    assert "adr" in text.lower()


def test_documents_links_to_data_pipeline_status():
    text = _read()
    assert "DATA_PIPELINE_STATUS" in text


def test_documents_links_to_release_tags():
    text = _read()
    assert "RELEASE_TAGS" in text
