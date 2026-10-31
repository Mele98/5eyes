"""DEP-SEC-003 (AUDIT-FIX, 2026-10-28): Sicherheits-Untergrenzen fuer die
Test-Abhaengigkeiten pypdf und pytest.

Vorher
------
- ``pypdf>=4,<6`` (installiert 5.9.0): pip-audit meldete 96 Advisories
  (u.a. Endlosschleifen/Speicher-DoS beim Parsen manipulierter PDFs), Fixes
  nur in der 6.x-Linie (letzte gemeldete Fix-Version 6.21.2).
- ``pytest==8.3.3``: CVE-2025-71176 (GHSA-6w46-j5rx-g56g), Fix erst in 9.0.3.

Nachher
-------
- Beide Pakete exakt gepinnt auf Versionen ohne bekannte Funde.
- pypdf bleibt reine Test-Abhaengigkeit: kein Laufzeitmodul des Backends
  importiert es (sonst gehoerte der Fund in den Produkt-Scope und in das
  PyInstaller-Manifest).
"""
from __future__ import annotations

import re
from importlib.metadata import version as installed_version
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REQUIREMENTS = _BACKEND_ROOT / "requirements.txt"

# Letzte Fix-Version der bei der Pruefung 2026-10-28 gemeldeten Advisories.
_FLOORS = {
    "pypdf": (6, 21, 2),
    "pytest": (9, 0, 3),
}


def _as_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def _pinned_version(package: str) -> tuple[int, ...]:
    pattern = re.compile(rf"^{re.escape(package)}==([0-9.]+)\s*$", re.IGNORECASE)
    for line in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            return _as_tuple(match.group(1))
    raise AssertionError(f"{package} ist in requirements.txt nicht exakt gepinnt")


@pytest.mark.parametrize(("package", "floor"), sorted(_FLOORS.items()))
def test_requirements_pin_is_not_below_security_floor(package, floor):
    assert _pinned_version(package) >= floor


@pytest.mark.parametrize(("package", "floor"), sorted(_FLOORS.items()))
def test_installed_library_is_not_below_security_floor(package, floor):
    assert _as_tuple(installed_version(package)) >= floor


def test_pypdf_is_not_imported_by_runtime_code():
    pattern = re.compile(r"^\s*(?:import|from)\s+(?:pypdf|PyPDF2)\b", re.MULTILINE)
    offenders = []
    for path in _BACKEND_ROOT.rglob("*.py"):
        relative = path.relative_to(_BACKEND_ROOT)
        top = relative.parts[0]
        if top in {"tests", "venv", "build", "dist"} or top.startswith("."):
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(relative.as_posix())
    assert offenders == []
