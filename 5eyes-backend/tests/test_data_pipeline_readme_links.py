"""P23: Lint-Test fuer den Master-README der Datenpipeline.

Verifiziert dass:
- README existiert.
- Alle referenzierten doc-Dateien existieren.
- Alle referenzierten Script-Pfade existieren.
- Alle Phase-PR-Branches in der Tabelle sind plausibel (codex/data-pipeline-pXX-...).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "docs" / "data_pipeline_README.md"


def test_readme_exists():
    assert README.exists(), f"README fehlt: {README}"


def _read():
    return README.read_text(encoding="utf-8")


def test_referenced_doc_files_exist():
    text = _read()
    # Markdown-Links wie [foo](bar.md) — relativ zu docs/
    refs = re.findall(r"\(([^)]+\.md)\)", text)
    docs_dir = REPO_ROOT / "docs"
    for ref in refs:
        if ref.startswith("http"):
            continue
        target = docs_dir / ref
        assert target.exists(), f"Doc-Link gebrochen: {ref}"


def test_referenced_scripts_exist():
    text = _read()
    # Greift scripts/foo.py-Pfade
    scripts = re.findall(r"`?python (scripts/\S+\.py)`?", text)
    scripts += re.findall(r"\bscripts/(\S+\.py)\b", text)
    seen = set()
    for raw in scripts:
        path = raw if raw.startswith("scripts/") else f"scripts/{raw}"
        path = path.rstrip("`")
        if path in seen:
            continue
        seen.add(path)
        target = REPO_ROOT / path
        assert target.exists(), f"Script-Pfad gebrochen: {path}"


def test_phase_branches_in_table_format():
    text = _read()
    # Tabellenzeilen wie "| P3 | #20 | `codex/data-pipeline-p03-stooq` |"
    pattern = re.compile(r"\| P\d+ \| #\d+ \| `(codex/data-pipeline-p\d+-[^`]+)` \|")
    matches = pattern.findall(text)
    assert len(matches) >= 20, f"Zu wenige Phase-Branches gelistet: {len(matches)}"
    for branch in matches:
        assert re.fullmatch(r"codex/data-pipeline-p\d+-[\w-]+", branch), \
            f"Branch-Name unueblich: {branch}"


def test_tier_table_has_three_rows():
    text = _read()
    # Mindestens "Tier 1", "Tier 2", "Tier 3" im Text
    assert "**1**" in text and "**2**" in text and "**3**" in text


def test_env_cheatsheet_has_minimum_block():
    text = _read()
    assert "PRICE_REFRESH_PRIMARY_PROVIDER=aggregator" in text
    assert "MARKET_DATA_PROVIDERS=" in text
    assert "ALPHAVANTAGE_API_KEY=" in text


def test_referenced_modules_exist():
    """Im 'Architektur in einem Bild'-Block: Modul-Pfade pruefen."""
    text = _read()
    assert "legacy_compat.fetch_latest_prices_via_aggregator" in text
    legacy = REPO_ROOT / "5eyes-backend" / "services" / "market_data" / "legacy_compat.py"
    assert legacy.exists()
    notifier = REPO_ROOT / "5eyes-backend" / "services" / "market_data" / "notifier.py"
    assert notifier.exists()
    scheduled = REPO_ROOT / "5eyes-backend" / "services" / "market_data" / "scheduled.py"
    assert scheduled.exists()
