"""DEP-SEC-002 (AUDIT-FIX, 2026-10-27): PyInstaller-Manifest passt zu requirements.txt.

Vorher
------
``ares-desktop/scripts/build-backend.js`` fuehrte nach dem Wechsel auf
PyJWT (2026-07-18) weiterhin ``jose``/``jose.jwt`` als Hidden-Import,
``jose`` in ``--collect-submodules`` und ``python-jose`` in
``--copy-metadata``. Das Paket wird nicht mehr installiert;
``--copy-metadata`` fuer eine fehlende Distribution bricht den
PyInstaller-Lauf ab, ein fehlender Hidden-Import erzeugt nur Warnungen.

Nachher
-------
Jeder Eintrag des Manifests muss in der Test-Umgebung (= requirements.txt)
aufloesbar sein. Damit faellt auch ein kuenftiger Paketwechsel auf, ohne
dass das Manifest nachgezogen wird.
"""
from __future__ import annotations

import importlib.util
import re
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import pytest

BUILD_BACKEND_SCRIPT = (
    Path(__file__).resolve().parents[2] / "ares-desktop" / "scripts" / "build-backend.js"
)


def _script() -> str:
    text = BUILD_BACKEND_SCRIPT.read_text(encoding="utf-8")
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def _string_list(pattern: str) -> list[str]:
    match = re.search(pattern, _script(), re.DOTALL)
    assert match, f"Liste nicht gefunden: {pattern}"
    entries = re.findall(r"'([^']+)'", match.group(1))
    assert entries, f"Liste leer: {pattern}"
    return entries


def _modules() -> list[str]:
    return _string_list(r"const hiddenImports = \[(.*?)\];") + _string_list(
        r"const collectSubmodules = \[(.*?)\];"
    )


def _metadata_packages() -> list[str]:
    return _string_list(r"for \(const pkg of \[(.*?)\]\)")


def test_removed_jwt_library_is_not_referenced():
    assert "jose" not in _modules()
    assert "jose.jwt" not in _modules()
    assert "python-jose" not in _metadata_packages()


@pytest.mark.parametrize("package", _metadata_packages())
def test_copy_metadata_package_is_installed(package):
    try:
        distribution(package)
    except PackageNotFoundError:  # pragma: no cover - Fehlerpfad
        pytest.fail(f"--copy-metadata {package}: Distribution nicht installiert")


@pytest.mark.parametrize("module", _modules())
def test_bundled_module_is_importable(module):
    assert importlib.util.find_spec(module) is not None, module
