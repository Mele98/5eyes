"""Sprint U-83 (2026-06-05): ADR-Drift-Schutz.

Verifiziert dass docs/adr/ vollstaendig ist und jeder ADR die Pflicht-
Sektionen enthaelt. ADRs sind FINMA-relevant — fehlende Status-/Kontext-
Felder waeren ein Audit-Risk.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = REPO_ROOT / "docs" / "adr"
ADR_INDEX = ADR_DIR / "README.md"

EXPECTED_ADRS = (
    "ADR-001-aggregator-pattern.md",
    "ADR-002-compliance-stack-3-layer.md",
    "ADR-003-anlagephilosophie-no-market-timing.md",
    "ADR-004-editorial-no-recharts.md",
    "ADR-005-free-data-pipeline.md",
    "ADR-006-drift-tests.md",
)

REQUIRED_SECTIONS = ("Status", "Kontext", "Entscheidung", "Konsequenzen")


def _read(name: str) -> str:
    path = ADR_DIR / name
    assert path.exists(), f"ADR fehlt: {name}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Verzeichnis + Index
# ---------------------------------------------------------------------------

def test_adr_directory_exists():
    assert ADR_DIR.is_dir()


def test_adr_index_exists():
    assert ADR_INDEX.exists()


def test_adr_index_lists_all_adrs():
    text = ADR_INDEX.read_text(encoding="utf-8")
    for name in EXPECTED_ADRS:
        assert name in text, f"ADR {name!r} fehlt im Index"


def test_adr_index_has_format_explanation():
    """Index muss erklaeren wie ein ADR aufgebaut ist."""
    text = ADR_INDEX.read_text(encoding="utf-8")
    for field in REQUIRED_SECTIONS:
        assert field in text, f"Format-Erklaerung fehlt: {field}"


def test_adr_index_has_when_to_write_section():
    text = ADR_INDEX.read_text(encoding="utf-8")
    assert "Wann einen neuen ADR" in text or "Wann ein neuer ADR" in text


# ---------------------------------------------------------------------------
# Vollstaendigkeits-Tests pro ADR
# ---------------------------------------------------------------------------

def test_all_adrs_present():
    for name in EXPECTED_ADRS:
        assert (ADR_DIR / name).exists(), f"ADR fehlt: {name}"


def test_each_adr_has_required_sections():
    for name in EXPECTED_ADRS:
        text = _read(name)
        for section in REQUIRED_SECTIONS:
            assert section in text, (
                f"ADR {name!r} fehlt Sektion {section!r}"
            )


def test_each_adr_has_status_field():
    for name in EXPECTED_ADRS:
        text = _read(name)
        assert "**Status:**" in text, f"{name}: Status-Field fehlt"


def test_each_adr_has_date_field():
    for name in EXPECTED_ADRS:
        text = _read(name)
        assert "**Datum:**" in text, f"{name}: Datum-Field fehlt"


def test_each_adr_has_sprint_field():
    for name in EXPECTED_ADRS:
        text = _read(name)
        assert "**Sprint:**" in text, f"{name}: Sprint-Field fehlt"


# ---------------------------------------------------------------------------
# Inhalts-Pins (Kern-Architektur-Entscheidungen sind festgenagelt)
# ---------------------------------------------------------------------------

def test_adr_001_pins_aggregator_function():
    text = _read("ADR-001-aggregator-pattern.md")
    assert "compute_advisory_report" in text
    assert "advisory_report.py" in text
    assert "23 Sektionen" in text or "23 sections" in text.lower()


def test_adr_002_pins_3_layer_paths():
    text = _read("ADR-002-compliance-stack-3-layer.md")
    for path in (
        "advisory_report.py",
        "compliance_audit.py",
        "Compliance.tsx",
    ):
        assert path in text, f"ADR-002 fehlt Layer-Pfad {path}"


def test_adr_003_pins_no_market_timing():
    text = _read("ADR-003-anlagephilosophie-no-market-timing.md")
    lowered = text.lower()
    assert "markt-timing" in lowered or "markttiming" in lowered
    assert "eignungspr" in lowered
    assert "auto-trigger" in lowered or "auto trigger" in lowered


def test_adr_004_pins_no_recharts():
    text = _read("ADR-004-editorial-no-recharts.md")
    assert "recharts" in text.lower()
    assert "SVG" in text
    assert "DESIGN_SYSTEM" in text


def test_adr_005_pins_free_providers():
    text = _read("ADR-005-free-data-pipeline.md")
    lowered = text.lower()
    assert "chf 0" in lowered
    for provider in ("yfinance", "stooq"):
        assert provider in lowered, f"ADR-005: Provider {provider} fehlt"


def test_adr_006_pins_drift_test_pattern():
    text = _read("ADR-006-drift-tests.md")
    assert "parsen" in text.lower() or "parse" in text.lower()
    # 2 von 3 Beispiel-Test-Dateien mussen referenziert sein
    examples = [
        "test_reporting_frontend_phase1.py",
        "test_readme_consistency.py",
        "test_glossar_consistency.py",
    ]
    found = sum(1 for ex in examples if ex in text)
    assert found >= 2, (
        f"ADR-006 sollte 2+ Beispiel-Drift-Tests nennen, gefunden: {found}"
    )


# ---------------------------------------------------------------------------
# Kein "Status: Draft" — wir publizieren nur Accepted/Superseded/Deprecated
# ---------------------------------------------------------------------------

def test_no_adr_in_draft_status():
    for name in EXPECTED_ADRS:
        text = _read(name)
        assert "Status:** Draft" not in text, (
            f"{name}: ADRs duerfen nicht im Draft-Status publiziert sein"
        )
