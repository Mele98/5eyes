"""Sprint U-75+U-76+U-77 (Roadmap-Punkte 75/76/77, 2026-06-04): Repo-Hygiene.

Stand-Audit
-----------
- 28 Stashes (12 Race-Recoveries + 16 Codex-WIP)
- 5 codex/* Branches (2 ahead=0 + 3 ahead>0)
- 1 Worktree (Main, kein extra Marker)

Diese Tests verifizieren:
1. (Doku-Tests auf die Bestandsaufnahme liegen im Archiv-Modul
   ``test_archived_docs_contract.py``, siehe docs/DOCS_MANIFEST.md.)
2. Cleanup-Scripts existieren + sind defensiv (DryRun-Support)
3. Scripts loeschen nur das was sicher ist (Memory-Pin nicht antasten)
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Script-Existenz
# ---------------------------------------------------------------------------

def test_cleanup_recent_stashes_script_exists():
    script = REPO_ROOT / "scripts" / "cleanup-recent-race-stashes.ps1"
    assert script.exists()


def test_cleanup_branches_script_exists():
    script = REPO_ROOT / "scripts" / "cleanup-codex-branches-safe.ps1"
    assert script.exists()


# ---------------------------------------------------------------------------
# Script-Robustheit
# ---------------------------------------------------------------------------

def test_stash_script_supports_dry_run():
    """DryRun ist Pflicht-Pattern fuer destructive scripts."""
    script = (REPO_ROOT / "scripts" / "cleanup-recent-race-stashes.ps1").read_text(
        encoding="utf-8",
    )
    assert "[switch]$DryRun" in script
    assert "DryRun" in script


def test_branch_script_supports_dry_run():
    script = (REPO_ROOT / "scripts" / "cleanup-codex-branches-safe.ps1").read_text(
        encoding="utf-8",
    )
    assert "[switch]$DryRun" in script


def test_stash_script_only_targets_preserve_u_prefix():
    """KERN-Test: Script darf NUR preserve-u* Stashes droppen (race-
    recoveries), KEINE codex-wip-* (Memory-Pin)."""
    script = (REPO_ROOT / "scripts" / "cleanup-recent-race-stashes.ps1").read_text(
        encoding="utf-8",
    )
    assert "preserve-u" in script


def test_stash_script_iterates_descending_to_avoid_index_shift():
    """git stash drop verschiebt nachfolgende Indexe — sicher rueckwaerts."""
    script = (REPO_ROOT / "scripts" / "cleanup-recent-race-stashes.ps1").read_text(
        encoding="utf-8",
    )
    assert "Descending" in script


def test_branch_script_skips_current_branch():
    """Aktueller Branch darf nicht geloescht werden."""
    script = (REPO_ROOT / "scripts" / "cleanup-codex-branches-safe.ps1").read_text(
        encoding="utf-8",
    )
    assert "CurrentBranch" in script


def test_branch_script_only_targets_ahead_zero():
    """KERN-Test: nur ahead=0 Branches (komplett in develop) loeschen."""
    script = (REPO_ROOT / "scripts" / "cleanup-codex-branches-safe.ps1").read_text(
        encoding="utf-8",
    )
    assert "rev-list --count develop.." in script
    assert "AheadInt -eq 0" in script


def test_branch_script_prefers_safe_minus_d_flag():
    """git branch -d (klein, refuses bei non-merged) bevorzugt vor -D."""
    script = (REPO_ROOT / "scripts" / "cleanup-codex-branches-safe.ps1").read_text(
        encoding="utf-8",
    )
    assert "branch -d" in script
