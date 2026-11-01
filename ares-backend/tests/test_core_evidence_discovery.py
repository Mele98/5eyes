"""K-1: Entdeckungstest fuer das Evidence-Inventar (Vorpruefung B-15).

Das Inventar in ``test_core_evidence_byte_equality.py`` ist eine geschlossene
Liste bekannter (Datei, Funktion). Dieser Test sucht per AST im ganzen
Backend (ohne ``tests``, ``alembic``, ``scripts``, ``migrations``) nach
Funktionen, die beides tun:

- ``json.dumps(...)`` mit ``sort_keys=`` oder ``separators=`` aufrufen (auch
  ueber einen Alias wie ``import json as _json`` oder ``from json import
  dumps``), und
- ``sha256`` referenzieren (``hashlib.sha256`` oder ``from hashlib import
  sha256``).

Jede solche Funktion (innerster Funktions-Qualname, wie im Inventar) muss im
Inventar stehen oder in ``UNINVENTORIED_EXCEPTIONS`` mit Begruendung.

Reichweite: erfasst werden Funktionen, die Kanonisierung UND Hash selbst
enthalten. Eine Kanonisierungsfunktion ohne eigenen Hash (z. B. ein
``_canonical``, dessen Ergebnis ein Aufrufer hasht) wird nicht entdeckt;
solche Stellen pinnt weiterhin nur das Inventar ("bekannte Stellen").
"""
from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
INVENTORY_TEST = Path(__file__).resolve().parent / "test_core_evidence_byte_equality.py"
EXCLUDED_DIRS = frozenset(
    {"tests", "alembic", "scripts", "migrations", "assets", "node_modules", "venv", "__pycache__"}
)

# (Datei, Funktions-Qualname) -> Begruendung. Heute leer: alle Fundstellen
# sind inventarisiert.
UNINVENTORIED_EXCEPTIONS: dict[tuple[str, str], str] = {}


def _inventoried_sites() -> set[tuple[str, str]]:
    name = "core_evidence_inventory_for_discovery"
    spec = importlib.util.spec_from_file_location(name, INVENTORY_TEST)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    sites: set[tuple[str, str]] = set()
    for attr in ("INVENTORY", "INVENTORY_MULTI", "BESPOKE", "SITES"):
        sites |= set(getattr(mod, attr, {}))
    assert sites, "Inventar nicht gefunden"
    return sites


def _hash_canonicalising_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    json_aliases: set[str] = set()
    dumps_aliases: set[str] = set()
    sha_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "json":
                    json_aliases.add(a.asname or "json")
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for a in node.names:
                if node.module == "json" and a.name == "dumps":
                    dumps_aliases.add(a.asname or "dumps")
                elif node.module == "hashlib" and a.name == "sha256":
                    sha_aliases.add(a.asname or "sha256")

    def is_canonical_dumps(call: ast.Call) -> bool:
        f = call.func
        dumps = (
            isinstance(f, ast.Attribute)
            and f.attr == "dumps"
            and isinstance(f.value, ast.Name)
            and f.value.id in json_aliases
        ) or (isinstance(f, ast.Name) and f.id in dumps_aliases)
        return dumps and any(k.arg in ("sort_keys", "separators") for k in call.keywords)

    found: dict[str, list[bool]] = {}
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def _scoped(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

        def _mark(self, idx: int):
            found.setdefault(".".join(stack) or "<module>", [False, False])[idx] = True

        def visit_Call(self, node):
            if is_canonical_dumps(node):
                self._mark(0)
            self.generic_visit(node)

        def visit_Attribute(self, node):
            if node.attr == "sha256":
                self._mark(1)
            self.generic_visit(node)

        def visit_Name(self, node):
            if node.id in sha_aliases:
                self._mark(1)

    Visitor().visit(tree)
    return {q for q, (dumps, sha) in found.items() if dumps and sha}


def discover(root: Path) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(p in EXCLUDED_DIRS or p.startswith(".") for p in rel.parts[:-1]):
            continue
        out |= {(rel.as_posix(), q) for q in _hash_canonicalising_functions(path)}
    return out


@pytest.fixture(scope="module")
def inventoried() -> set[tuple[str, str]]:
    return _inventoried_sites() | set(UNINVENTORIED_EXCEPTIONS)


def test_every_hash_canonicalising_function_is_inventoried(inventoried):
    found = discover(BACKEND)
    assert found, "Entdeckung findet nichts -- Suchmuster pruefen"
    missing = sorted(found - inventoried)
    assert not missing, (
        "Funktion(en) mit json.dumps(sort_keys/separators) + sha256 ausserhalb des "
        f"Evidence-Inventars (test_core_evidence_byte_equality.py nachfuehren): {missing}"
    )


def test_exceptions_are_justified_and_still_exist():
    found = discover(BACKEND)
    for site, reason in UNINVENTORIED_EXCEPTIONS.items():
        assert reason.strip(), site
        assert site in found, f"{site} ist keine Fundstelle mehr -- Ausnahme entfernen"


def _copy_module(tmp_path: Path, rel: str) -> Path:
    target = tmp_path / "backend" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BACKEND / rel, target)
    return target


def test_negative_control_new_function_in_a_copy_is_red(tmp_path, inventoried):
    rel = "services/reserve_split_snapshot.py"
    target = _copy_module(tmp_path, rel)
    root = tmp_path / "backend"
    assert discover(root) - inventoried == set()  # unveraenderte Kopie: gruen
    with target.open("a", encoding="utf-8") as fh:
        fh.write(
            "\n\nimport hashlib\nimport json\n\n\ndef _new_unlisted_digest(p):\n"
            "    text = json.dumps(p, sort_keys=True, separators=(',', ':'))\n"
            "    return hashlib.sha256(text.encode('utf-8')).hexdigest()\n"
        )
    assert discover(root) - inventoried == {(rel, "_new_unlisted_digest")}


@pytest.mark.parametrize(
    "source",
    [
        "import json as _j\nfrom hashlib import sha256\n"
        "def f(p):\n    return sha256(_j.dumps(p, sort_keys=True).encode()).hexdigest()\n",
        "from json import dumps\nimport hashlib\n"
        "class K:\n    def f(self, p):\n"
        "        return hashlib.sha256(dumps(p, separators=(',', ':')).encode()).hexdigest()\n",
    ],
    ids=["aliased_json_and_sha256", "from_json_import_dumps_in_method"],
)
def test_negative_control_aliases_are_discovered(tmp_path, inventoried, source):
    path = tmp_path / "backend" / "services" / "new_mod.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert len(discover(tmp_path / "backend") - inventoried) == 1
