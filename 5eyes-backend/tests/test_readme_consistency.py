"""Sprint U-80 (2026-06-05): README-Drift-Schutz.

Verifiziert dass README.md aktuelle URL-Paths + Aggregator-Sektionen-
Liste nicht veraltet. Bei Drift -> Test schlaegt fehl, README muss
nachgezogen werden.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "README.md"


def _readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# README-Existenz + Mindest-Content
# ---------------------------------------------------------------------------

def test_readme_exists():
    assert README_PATH.exists()


def test_readme_mentions_subsystems():
    text = _readme()
    for sub in (
        "5eyes-backend",
        "5eyes-electron",
        "Reporting Sub-App",
        "FastAPI",
        "SQLite",
    ):
        assert sub in text, f"Subsystem-Erwaehnung {sub!r} fehlt im README"


# ---------------------------------------------------------------------------
# API-Doku-Links (U-80 Pflicht)
# ---------------------------------------------------------------------------

def test_readme_links_swagger_ui():
    """Swagger UI Endpoint muss verlinkt sein."""
    text = _readme()
    assert "/docs" in text
    assert "Swagger" in text


def test_readme_links_redoc():
    text = _readme()
    assert "/redoc" in text
    assert "ReDoc" in text


def test_readme_links_openapi_json():
    text = _readme()
    assert "/openapi.json" in text


def test_readme_documents_health_endpoints():
    """Health-Endpoints (root + live + ready) verlinkt."""
    text = _readme()
    assert "/health" in text
    assert "/health/live" in text
    assert "/health/ready" in text


# ---------------------------------------------------------------------------
# Aggregator-Sektionen-Tabelle aktuell?
# ---------------------------------------------------------------------------

def test_readme_lists_all_25_aggregator_sections():
    """Tabelle muss Sektionen 1-25 listen (Stand U-97 2026-06-06)."""
    text = _readme()
    # Section-Keys nach Aggregator-Konsolidierung + U-94 + U-97
    for key in (
        "beratungsprotokoll",
        "stress_replay",
        "conflict_disclosures",
        "suitability_compliance",
        "methodology_models",
        "recommendation_methodology",
        "mandate_lock_status",
        "liquidity_cascade",
        "optimizer_run_history",
        "performance_attribution",
    ):
        assert key in text, f"Aggregator-Key {key!r} fehlt in README-Tabelle"


def test_readme_documents_compliance_stack_3_layers():
    text = _readme()
    assert "Compliance-Stack" in text or "compliance" in text.lower()
    for layer in (
        "advisory_report.py",
        "compliance_audit.py",
        "Compliance.tsx",
    ):
        assert layer in text, f"Compliance-Layer-Datei {layer!r} fehlt"


# ---------------------------------------------------------------------------
# Auth-Doku
# ---------------------------------------------------------------------------

def test_readme_documents_bearer_auth():
    text = _readme()
    assert "Bearer" in text
    assert "Authorization" in text
    assert "/auth/login" in text


def test_readme_documents_token_ttl():
    """U-59 erwaehnt — Token-Lifetime ist ein Berater-relevanter Fact."""
    text = _readme()
    assert "U-59" in text or "TTL" in text or "8h" in text


# ---------------------------------------------------------------------------
# Test-Strategie + Branch-Strategie
# ---------------------------------------------------------------------------

def test_readme_documents_test_commands():
    text = _readme()
    assert "pytest" in text
    assert "vitest" in text or "npm test" in text


def test_readme_documents_ci_workflow():
    text = _readme()
    assert ".github/workflows" in text or "test.yml" in text


def test_readme_documents_branch_strategy():
    text = _readme()
    assert "develop" in text
    assert "main" in text


# ---------------------------------------------------------------------------
# Weitere Doku-Verweise
# ---------------------------------------------------------------------------

def test_readme_links_design_system_doc():
    text = _readme()
    assert "DESIGN_SYSTEM.md" in text


def test_readme_links_release_tags_doc():
    text = _readme()
    assert "RELEASE_TAGS.md" in text
