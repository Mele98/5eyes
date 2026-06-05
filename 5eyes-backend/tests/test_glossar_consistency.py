"""Sprint U-81 (2026-06-05): GLOSSAR-Drift-Schutz.

Verifiziert dass docs/GLOSSAR.md die im Code/PDF referenzierten Fachbegriffe
definiert und Branding-Disziplin einhaelt. Bei Drift -> Test schlaegt fehl,
Glossar muss nachgezogen werden.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOSSAR_PATH = REPO_ROOT / "docs" / "GLOSSAR.md"


def _glossar() -> str:
    return GLOSSAR_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Existenz + Mindest-Content
# ---------------------------------------------------------------------------

def test_glossar_exists():
    assert GLOSSAR_PATH.exists()


def test_glossar_has_header():
    text = _glossar()
    assert "5eyes" in text
    assert "Glossar" in text


# ---------------------------------------------------------------------------
# Fachlogik-Kernbegriffe (User-Memory project_5eyes_fachlogik)
# ---------------------------------------------------------------------------

def test_glossar_defines_gesamtvermoegen_vs_beratungsvermoegen():
    """Cashflow=Gesamtvermoegen, Torte=Beratungsvermoegen - Kerntrennung."""
    text = _glossar()
    assert "Gesamtverm" in text
    assert "Beratungsverm" in text
    assert "Cashflow" in text
    assert "Torte" in text


def test_glossar_defines_ist_soll():
    text = _glossar()
    assert "**IST**" in text
    assert "**SOLL**" in text


def test_glossar_defines_saa_cma():
    text = _glossar()
    assert "**SAA**" in text
    assert "**CMA**" in text


def test_glossar_documents_rebalancing_manual():
    """Re-Balancing ist manuell, kein Auto-Trigger (Anlagephilosophie)."""
    text = _glossar()
    assert "Re-Balancing" in text or "Rebalancing" in text
    lowered = text.lower()
    assert "manuell" in lowered
    assert "eignungspr" in lowered or "kunden" in lowered


def test_glossar_documents_anlagephilosophie_no_markttiming():
    text = _glossar()
    lowered = text.lower()
    assert "anlagephilosophie" in lowered
    assert "markt-timing" in lowered or "markttiming" in lowered


def test_glossar_documents_portfolio_as_saa_derivation():
    """Portfolio = Ableitung der SAA, NICHT Bestand-vs-Empfehlung."""
    text = _glossar()
    assert "Portfolio" in text
    assert "SAA" in text


# ---------------------------------------------------------------------------
# Compliance-Stack-Begriffe
# ---------------------------------------------------------------------------

def test_glossar_defines_compliance_stack_layers():
    text = _glossar()
    for layer in ("advisory_report.py", "compliance_audit.py", "Compliance.tsx"):
        assert layer in text, f"Compliance-Layer {layer!r} fehlt im Glossar"


def test_glossar_defines_finma_fidleg():
    text = _glossar()
    assert "FINMA" in text
    assert "FIDLEG" in text


def test_glossar_defines_beratungsprotokoll():
    text = _glossar()
    assert "Beratungsprotokoll" in text


def test_glossar_defines_eignungspruefung_suitability():
    text = _glossar()
    lowered = text.lower()
    assert "eignungspr" in lowered
    assert "suitability" in lowered


def test_glossar_defines_conflict_disclosures():
    text = _glossar()
    assert "Conflict Disclosures" in text or "conflict_disclosures" in text


# ---------------------------------------------------------------------------
# Aggregator-Sektionen-Begriffe
# ---------------------------------------------------------------------------

def test_glossar_defines_aggregator():
    text = _glossar()
    assert "Aggregator" in text
    assert "compute_advisory_report" in text


def test_glossar_defines_post_konsolidierung_sektionen():
    """Sektionen nach Aggregator-Konsolidierung (PR #163)."""
    text = _glossar()
    for key in (
        "stress_replay",
        "conflict_disclosures",
        "suitability_compliance",
        "recommendation_methodology",
        "liquidity_cascade",
    ):
        assert key in text, f"Sektion-Key {key!r} fehlt im Glossar"


def test_glossar_defines_liquidity_cascade_stages():
    """4 Stages der Liquidity Cascade (U-21)."""
    text = _glossar()
    assert "Liquidity Cascade" in text
    for stage in ("normal", "hard_cap", "emergency", "unknown"):
        assert stage in text


def test_glossar_defines_monte_carlo():
    text = _glossar()
    assert "Monte-Carlo" in text or "Monte Carlo" in text


# ---------------------------------------------------------------------------
# Architektur-Begriffe
# ---------------------------------------------------------------------------

def test_glossar_defines_hauptapp_subapp():
    text = _glossar()
    assert "Hauptapp" in text
    assert "Sub-App" in text


def test_glossar_defines_token_handoff():
    text = _glossar()
    assert "Token-Handoff" in text
    assert "URL-Fragment" in text


def test_glossar_defines_auth_bearer():
    text = _glossar()
    assert "Bearer" in text
    assert "Auth" in text


def test_glossar_defines_health_endpoints():
    text = _glossar()
    assert "/health/live" in text
    assert "/health/ready" in text


# ---------------------------------------------------------------------------
# Branding-Disziplin (project_5eyes_branding feedback)
# ---------------------------------------------------------------------------

def test_glossar_documents_forbidden_third_party_brands():
    """Glossar muss explizit warnen vor Drittmarken."""
    text = _glossar()
    lowered = text.lower()
    # Verbots-Sektion muss existieren
    assert "nicht auftauchen" in lowered or "verboten" in lowered
    # Die verbotenen Begriffe muessen im Verbot gelistet sein
    for brand in ("swiss life", "3eyes"):
        assert brand in lowered, f"Verbotsregel fuer {brand!r} fehlt"


def test_glossar_warns_about_guarantee_language():
    text = _glossar()
    lowered = text.lower()
    assert "garantiert" in lowered  # als Negativ-Beispiel


# ---------------------------------------------------------------------------
# Konservative CMA-Konvention (feedback_conservative_values)
# ---------------------------------------------------------------------------

def test_glossar_documents_conservative_cma_convention():
    """Bei CMA-Bandbreiten immer tieferen Wert nehmen."""
    text = _glossar()
    lowered = text.lower()
    assert "cma" in lowered
    assert "tiefer" in lowered or "konservativ" in lowered


# ---------------------------------------------------------------------------
# Verweise auf andere Docs
# ---------------------------------------------------------------------------

def test_glossar_links_design_system():
    text = _glossar()
    assert "DESIGN_SYSTEM" in text


def test_glossar_links_drift_test_file():
    """Selbstreferenz: Glossar nennt den eigenen Drift-Test."""
    text = _glossar()
    assert "test_glossar_consistency" in text
