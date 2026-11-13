"""Drift-Tests auf ARCHIVE-Dokumente (Agenten-Koordination, Repo-Hygiene).

Die Tests stammen unveraendert aus ``test_pipeline_status_and_codex_wip_docs.py``
(U-84) und ``test_repo_hygiene_docs.py`` (U-75). Sie pruefen Dokumente, die
docs/DOCS_MANIFEST.md als ARCHIVE fuehrt. Dieses Modul ist selbst ARCHIVE:
Es laeuft nur im Archiv-Repo und wird beim Clean-Room-Export weggelassen.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_WIP = REPO_ROOT / "docs" / "CODEX_WIP.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


# ---------------------------------------------------------------------------
# REPO_HYGIENE_2026-06-04.md (U-75)
# ---------------------------------------------------------------------------

def test_repo_hygiene_doc_exists():
    doc = REPO_ROOT / "docs" / "REPO_HYGIENE_2026-06-04.md"
    assert doc.exists(), "Audit-Doku fehlt — Bestandsaufnahme nicht persistiert."


# ---------------------------------------------------------------------------
# Doku-Content
# ---------------------------------------------------------------------------

def test_doc_classifies_28_stashes_and_5_branches():
    doc = (REPO_ROOT / "docs" / "REPO_HYGIENE_2026-06-04.md").read_text(
        encoding="utf-8",
    )
    assert "28 Stashes" in doc or "28 Total" in doc
    assert "5 codex/* Branches" in doc or "5 Lokale Total" in doc


def test_doc_distinguishes_race_recovery_from_codex_wip():
    doc = (REPO_ROOT / "docs" / "REPO_HYGIENE_2026-06-04.md").read_text(
        encoding="utf-8",
    )
    assert "Race-Recovery" in doc
    assert "Codex-WIP" in doc


def test_doc_classifies_branches_by_ahead_count():
    doc = (REPO_ROOT / "docs" / "REPO_HYGIENE_2026-06-04.md").read_text(
        encoding="utf-8",
    )
    # Mind. die 2 ahead=0 Branches namentlich genannt
    assert "codex/u-p23-pr-a-schema-toc" in doc
    assert "codex/u-p23-pr-c-report-navigation" in doc


# ---------------------------------------------------------------------------
# Folge-Sprint Trail
# ---------------------------------------------------------------------------

def test_doc_lists_folge_sprints():
    doc = (REPO_ROOT / "docs" / "REPO_HYGIENE_2026-06-04.md").read_text(
        encoding="utf-8",
    )
    assert "Folge-Sprints" in doc
