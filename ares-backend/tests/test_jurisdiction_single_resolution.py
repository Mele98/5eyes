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


# --------------------------------------------------------------------------
# Form jeder umgestellten Stelle (Vorpruefung B-7): ``resolve_pack(...)`` wird
# ausschliesslich als ``.code`` verwendet -- ohne Normalisierung, ohne
# Fallback, ohne weitere Aufrufkette. Einzig zulaessige Huelle ist ein
# einfaches ``str(...)`` (Input-Snapshot, war vorher ebenfalls ``str(...)``).
# Ab K-3 zusaetzlich zulaessig: ``RunContext.capture(resolve_pack(mandate), ...)``
# (build_run_context; capture liest unveraendert ``.code``).
# Die Anzahl der Stellen je Modul ist gepinnt, damit keine Stelle still auf
# eine andere Formel zurueckfaellt.
# --------------------------------------------------------------------------

EXPECTED_RESOLVE_PACK_SITES = {
    "routers/allocation.py": 2,
    "routers/wealth.py": 1,
    "services/cost_disclosure.py": 1,
    "services/manual_target_allocation.py": 1,
    "services/portfolio_engine.py": 7,
    "services/preference_snapshot.py": 1,
    "services/review_engine.py": 1,
}


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _resolve_pack_site_violations(tree: ast.AST) -> tuple[int, list[str]]:
    parents = _parents(tree)
    count = 0
    problems: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _call_name(node) == "resolve_pack"):
            continue
        count += 1
        where = f"Z.{node.lineno}"
        # Argumentform: genau ``resolve_pack(<Name>)`` oder ``resolve_pack(code=<Name>)``.
        positional_ok = len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Name)
        keyword_ok = (
            not node.args
            and len(node.keywords) == 1
            and node.keywords[0].arg == "code"
            and isinstance(node.keywords[0].value, ast.Name)
        )
        if not (positional_ok or keyword_ok):
            problems.append(f"{where}: Argumentform {ast.unparse(node)}")
        attr = parents.get(node)
        if (
            isinstance(attr, ast.Call)
            and isinstance(attr.func, ast.Attribute)
            and attr.func.attr == "capture"
            and isinstance(attr.func.value, ast.Name)
            and attr.func.value.id == "RunContext"
            and attr.args[:1] == [node]
        ):
            # K-3 build_run_context: RunContext.capture liest genau .code
            # (config.RunContext.capture: jurisdiction=resolved_pack.code).
            continue
        if not (isinstance(attr, ast.Attribute) and attr.attr == "code" and attr.value is node):
            problems.append(f"{where}: resolve_pack ohne direktes .code")
            continue
        outer: ast.AST = attr
        parent = parents.get(outer)
        if (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Name)
            and parent.func.id == "str"
            and parent.args == [outer]
            and not parent.keywords
        ):
            outer = parent
            parent = parents.get(outer)
        if isinstance(parent, (ast.Attribute, ast.Subscript, ast.BoolOp, ast.BinOp, ast.IfExp, ast.UnaryOp)):
            problems.append(f"{where}: weitere Verarbeitung {ast.unparse(parent)}")
        elif isinstance(parent, ast.Call) and parent.func is outer:
            problems.append(f"{where}: Aufruf auf .code")
        elif isinstance(parent, ast.Call) and _call_name(parent) in {"str", "upper", "lower", "strip"}:
            problems.append(f"{where}: Normalisierung {ast.unparse(parent)}")
    return count, problems


@pytest.mark.parametrize("rel", CONVERTED_MODULES)
def test_converted_sites_use_plain_resolve_pack_code(rel):
    count, problems = _resolve_pack_site_violations(_tree(rel))
    assert not problems, f"{rel}: {problems}"
    assert count == EXPECTED_RESOLVE_PACK_SITES[rel], (rel, count)


@pytest.mark.parametrize(
    "mutated",
    [
        "x = str(resolve_pack(mandate).code).strip().upper()",
        "x = resolve_pack(mandate).code.strip()",
        "x = resolve_pack(mandate).code or 'CH'",
        "x = resolve_pack(mandate).pack.code",
        "x = resolve_pack(getattr(mandate, 'jurisdiction', None)).code",
        "x = str(resolve_pack(mandate).code).upper()",
        "x = Other.capture(resolve_pack(mandate), settings)",
        "x = RunContext.capture(settings, resolve_pack(mandate))",
    ],
)
def test_site_check_rejects_reintroduced_normalisation(mutated):
    """Positivkontrolle des Pruefers: die Vorpruefungs-Mutation (B-7) und
    verwandte Formen werden erkannt."""
    _, problems = _resolve_pack_site_violations(ast.parse(mutated))
    assert problems, mutated
