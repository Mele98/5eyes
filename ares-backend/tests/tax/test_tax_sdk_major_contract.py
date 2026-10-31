"""W2-804-01: Der Breaking-Wechsel der Tax-Plugin-Entry-Point-Gruppe ist ein
synchronisierter SDK-Major (Code == Doku, Major >= 2).

Uebernommen aus dem Codex-Abnahme-Reproducer
``test_breaking_tax_entry_point_contract_is_a_synchronized_major``
(dort strict-xfail); hier als regulaerer Test ohne xfail, Pfade relativ
zur Testdatei statt zum Arbeitsverzeichnis.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_breaking_tax_entry_point_contract_is_a_synchronized_major() -> None:
    from services.tax.sdk import TAX_SDK_VERSION

    assert (REPO_ROOT / "ares-backend").is_dir(), f"not an Ares tree: {REPO_ROOT}"
    doc = (REPO_ROOT / "docs" / "architecture" / "tax-plugin-sdk.md").read_text(
        encoding="utf-8"
    )
    documented = re.search(r"TAX_SDK_VERSION\s*=\s*`([^`]+)`", doc)
    assert documented is not None
    assert int(TAX_SDK_VERSION.split(".", 1)[0]) >= 2
    assert documented.group(1) == TAX_SDK_VERSION
