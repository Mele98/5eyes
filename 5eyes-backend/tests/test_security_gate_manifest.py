"""Meta-Test: die Security-Gate-Liste (scripts/security_gate.py) bleibt gueltig.

Schuetzt davor, dass das Gate still schrumpft: jeder gelistete Pfad muss
existieren, und neu hinzugekommene, offensichtlich sicherheitskritische
Test-Dateien sollten im Gate stehen (weicher Hinweis via Kern-Set).
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
GATE_FILE = REPO_ROOT / "scripts" / "security_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("security_gate", GATE_FILE)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_gate_file_exists():
    assert GATE_FILE.is_file(), f"Security-Gate-Skript fehlt: {GATE_FILE}"


def test_all_listed_security_tests_exist():
    gate = _load_gate()
    missing = [t for t in gate.SECURITY_TESTS if not (BACKEND_ROOT / t).is_file()]
    assert not missing, f"Im Security-Gate gelistete Tests fehlen (umbenannt/verschoben?): {missing}"


def test_core_isolation_tests_are_gated():
    """Kern-Set der Mandanten-Trennung MUSS im Gate stehen — verhindert, dass die
    wichtigsten Leak-Tests versehentlich aus dem Gate fallen."""
    gate = _load_gate()
    listed = set(gate.SECURITY_TESTS)
    core = {
        "tests/test_repository_tenant_scoping.py",
        "tests/test_tenant_endpoint_leak_regression.py",
        "tests/test_strict_tenant_isolation.py",
        "tests/test_client_portal_tenant_isolation.py",
        "tests/test_2fa_login.py",
    }
    assert core.issubset(listed), f"Kern-Isolations-Tests fehlen im Gate: {core - listed}"


def test_gate_list_has_no_duplicates():
    gate = _load_gate()
    seen, dupes = set(), set()
    for t in gate.SECURITY_TESTS:
        (dupes if t in seen else seen).add(t)
    assert not dupes, f"Doppelte Eintraege im Security-Gate: {dupes}"
