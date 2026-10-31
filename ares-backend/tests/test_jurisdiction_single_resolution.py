"""X2 (OPTIMIZATION): eine Aufloesung des Laendercodes ueber resolve_pack.

Belegt:
- Tabellentest alt == neu: ``resolve_pack(m).code`` liefert fuer NULL, "",
  "CH", "ch", unbekannte Codes und Sonderwerte exakt dasselbe wie die bisherige
  Formel bzw. ``resolve_mandate_jurisdiction``; ``resolve_pack(code=x).code``
  exakt dasselbe wie ``x or "CH"``. Unbekannte Codes bleiben unveraendert
  (fail-closed erst in X14).
- Die umgestellten Module rufen ``resolve_mandate_jurisdiction`` nicht mehr
  auf und enthalten keinen Inline-Fallback ``... or "CH"`` mehr.
- Ratsche: Inline-Fallbacks, Resolver-Aufrufe und "CH"-Vergleiche ausserhalb
  von ``jurisdictions/`` duerfen nur sinken.

Keine Datenbank, kein App-Start.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from jurisdictions.resolve import resolve_pack
from services.jurisdiction.resolve import resolve_mandate_jurisdiction

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_EXCLUDED = {"tests", "alembic", "scripts", "migrations", "jurisdictions", "assets", "node_modules", "venv", "__pycache__"}

_MISSING = object()
_CASES = [None, "", "CH", "ch", " CH ", "CH-ZH", "DE", "AT", "XX", "de", 0, _MISSING]


def _case_id(raw) -> str:
    return "missing_attribute" if raw is _MISSING else repr(raw)


def _mandate(raw):
    return SimpleNamespace() if raw is _MISSING else SimpleNamespace(jurisdiction=raw)


@pytest.mark.parametrize("raw", _CASES, ids=_case_id)
def test_mandate_code_alt_equals_neu(raw):
    mandate = _mandate(raw)
    legacy = getattr(mandate, "jurisdiction", None) or "CH"
    assert resolve_pack(mandate).code == legacy
    assert resolve_pack(mandate).code == resolve_mandate_jurisdiction(mandate)
    assert type(resolve_pack(mandate).code) is type(legacy)


@pytest.mark.parametrize("raw", [c for c in _CASES if c is not _MISSING], ids=_case_id)
def test_explicit_code_alt_equals_neu(raw):
    # ``jurisdiction or "CH"`` (portfolio_engine.ensure_default_products-Pfad)
    assert resolve_pack(code=raw).code == (raw or "CH")
    # ``str(getattr(mandate, "jurisdiction", None) or "CH")`` (Input-Snapshot)
    assert str(resolve_pack(_mandate(raw)).code) == str(getattr(_mandate(raw), "jurisdiction", None) or "CH")


def test_unknown_codes_are_not_normalised_or_rejected():
    for raw in ("ch", " CH ", "XX", "DE"):
        resolved = resolve_pack(SimpleNamespace(jurisdiction=raw))
        assert resolved.code == raw
        assert resolved.pack is None
    assert resolve_pack(SimpleNamespace(jurisdiction=None)).pack.code == "CH"


# --------------------------------------------------------------------------
# Statische Nachweise
# --------------------------------------------------------------------------

CONVERTED_MODULES = (
    "routers/allocation.py",
    "routers/wealth.py",
    "services/cost_disclosure.py",
    "services/manual_target_allocation.py",
    "services/portfolio_engine.py",
    "services/preference_snapshot.py",
    "services/review_engine.py",
)


def _tree(rel: str) -> ast.Module:
    return ast.parse((BACKEND_ROOT / rel).read_text(encoding="utf-8-sig"))


def _is_ch(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "CH"


def _call_name(node: ast.Call) -> str | None:
    return getattr(node.func, "id", getattr(node.func, "attr", None))


def _measure() -> dict[str, int]:
    fallbacks = calls = comparisons = 0
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT)
        if any(part in _EXCLUDED or part.startswith(".") for part in rel.parts[:-1]):
            continue
        for node in ast.walk(_tree(rel.as_posix())):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and _is_ch(node.values[-1]):
                fallbacks += 1
            elif isinstance(node, ast.Call) and _call_name(node) == "resolve_mandate_jurisdiction":
                calls += 1
            elif isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                if any(
                    _is_ch(o) or (isinstance(o, (ast.Tuple, ast.List, ast.Set)) and any(_is_ch(e) for e in o.elts))
                    for o in operands
                ):
                    comparisons += 1
    return {"inline_fallbacks": fallbacks, "resolver_calls": calls, "ch_comparisons": comparisons}


@pytest.mark.parametrize("rel", CONVERTED_MODULES)
def test_converted_module_uses_resolve_pack_only(rel):
    tree = _tree(rel)
    names = [_call_name(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert "resolve_mandate_jurisdiction" not in names
    assert "resolve_pack" in names
    assert not [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and _is_ch(n.values[-1])
    ]


# Stand nach X2 (vor X2: 21 / 17 / 33). Die Zaehlung der Inline-Fallbacks ist
# AST-basiert; verschachtelte Formen wie ``(x or "CH").strip() or "CH"`` zaehlen
# doppelt, ``client.country_of_residence or "CH"`` (Steuerdomizil, kein
# Pack-Code) zaehlt mit. Werte duerfen nur sinken (X15: Endwert 0).
RATCHET = {"inline_fallbacks": 19, "resolver_calls": 5, "ch_comparisons": 33}


def test_ch_literal_ratchet_only_sinks():
    current = _measure()
    worse = {k: (current[k], RATCHET[k]) for k in RATCHET if current[k] > RATCHET[k]}
    assert not worse, f"Ratsche verletzt (aktuell, Basis): {worse}"
