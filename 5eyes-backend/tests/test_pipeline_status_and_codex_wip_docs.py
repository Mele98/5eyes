"""Sprint U-84+U-85 (2026-06-05): Drift-Schutz fuer Pipeline-Status und Codex-WIP-Doku.

Beide Docs sind Status-Tracker — sie veralten schnell. Tests stellen
sicher, dass die Kern-Sektionen erhalten bleiben.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_STATUS = REPO_ROOT / "docs" / "DATA_PIPELINE_STATUS.md"
CODEX_WIP = REPO_ROOT / "docs" / "CODEX_WIP.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# DATA_PIPELINE_STATUS.md (U-85)
# ---------------------------------------------------------------------------

def test_pipeline_status_exists():
    assert PIPELINE_STATUS.exists()


def test_pipeline_status_has_phasen_status_section():
    text = _read(PIPELINE_STATUS)
    assert "Phasen-Status" in text


def test_pipeline_status_documents_provider_stack():
    text = _read(PIPELINE_STATUS)
    for provider in ("YFinanceProvider", "StooqProvider", "AlphaVantageProvider"):
        assert provider in text


def test_pipeline_status_documents_macro_pipeline():
    text = _read(PIPELINE_STATUS)
    for source in ("FRED", "ECB", "SNB"):
        assert source in text


def test_pipeline_status_links_adr_005():
    text = _read(PIPELINE_STATUS)
    assert "ADR-005" in text


def test_pipeline_status_documents_chf_0_constraint():
    text = _read(PIPELINE_STATUS)
    lowered = text.lower()
    assert "chf 0" in lowered
    assert "hard-constraint" in lowered or "hard constraint" in lowered


def test_pipeline_status_has_live_diagnose_section():
    text = _read(PIPELINE_STATUS)
    assert "Live-Diagnose" in text
    assert "/admin/system/market-data/provider-health" in text
    assert "smoketest_market_data.py" in text


def test_pipeline_status_references_open_roadmap_points():
    """Offene Roadmap-Punkte aus dem Pipeline-Bereich muessen genannt sein."""
    text = _read(PIPELINE_STATUS)
    for nr in ("#30", "#31", "#99", "#100"):
        assert nr in text, f"Roadmap-Verweis {nr} fehlt"


def test_pipeline_status_has_update_instruction():
    """Doku muss erklaeren wie sie selbst aktualisiert wird."""
    text = _read(PIPELINE_STATUS)
    assert "Wie diesen Doc aktualisieren" in text or "aktualisieren" in text.lower()


# ---------------------------------------------------------------------------
# CODEX_WIP.md (U-84)
# ---------------------------------------------------------------------------

def test_codex_wip_exists():
    assert CODEX_WIP.exists()


def test_codex_wip_documents_file_separation():
    text = _read(CODEX_WIP)
    assert "Datei-Trennung" in text
    # Claude-Bereiche
    assert "advisory_report.py" in text
    assert "frontend/reporting/" in text
    # Codex-Bereiche
    assert "services/pdf/" in text
    assert "pdf_reports.py" in text


def test_codex_wip_documents_branch_check():
    text = _read(CODEX_WIP)
    assert "git branch --show-current" in text
    assert "ABORT" in text


def test_codex_wip_documents_race_recovery():
    text = _read(CODEX_WIP)
    assert "Race-Recovery" in text or "race-recovery" in text.lower()
    assert "Backup" in text or "backup" in text.lower()


def test_codex_wip_documents_codex_prompt_format():
    text = _read(CODEX_WIP)
    assert "Codex-Prompt" in text
    assert "Datei-Overlap" in text


def test_codex_wip_documents_known_conflict_classes():
    text = _read(CODEX_WIP)
    assert "Konflikt-Klassen" in text
    assert "AUDIT_LOG_VALID_ACTIONS" in text
    assert "Sidebar-Section-Count" in text


def test_codex_wip_lists_historic_race_recoveries():
    text = _read(CODEX_WIP)
    assert "2026-06-04" in text  # Repo-Hygiene
    assert "2026-06-05" in text  # heutige Race-Resolutions
