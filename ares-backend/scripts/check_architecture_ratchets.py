#!/usr/bin/env python
"""Architektur-Ratschen fuer das Backend-Paket (F0-4 / A2 M1).

Misst per AST (nur Standardbibliothek, keine neue Abhaengigkeit) den
Import-Graph aller Backend-Module (ohne ``tests``, ``alembic``, ``scripts``,
``migrations``) und vergleicht ihn mit committeten Basiswerten in
``architecture_ratchets_baseline.json`` (gleiches Verzeichnis):

1. Import-Zyklen
   - ``cycles_eager``: starke Zusammenhangskomponenten (SCC) nur ueber
     Modulebenen-Imports.
   - ``cycles_all``: SCCs ueber Modulebenen- UND funktionslokale Imports
     (die realen Kopplungszyklen, die nur Lazy-Imports lauffaehig halten).
   Verletzung: eine heutige SCC ist nicht Teilmenge einer Basis-SCC (neuer
   Zyklus oder zwei Zyklen verschmolzen). Gemeldet werden die Import-Kanten,
   die den Zyklus neu schliessen (Datei:Zeile).
2. Lazy-Imports: Anzahl interner Import-Anweisungen innerhalb von Funktionen
   je Modul. Verletzung: Anzahl steigt (neue Module: Basis 0).
3. Fan-out: Anzahl importierter interner Module je Modul (Modulebene +
   funktionslokal, ohne ``if TYPE_CHECKING``). Verletzung: Anzahl steigt;
   neue Module duerfen hoechstens ``NEW_MODULE_FAN_OUT_LIMIT`` haben.
4. Schichtung Router -> Service -> Model: ``services``/``models`` duerfen
   ``routers`` nicht importieren, ``models`` nicht ``services`` (alle
   Import-Arten). Verletzung: Kante nicht in der Basisliste.
5. Umgebungsvariablen: direkter Zugriff auf ``os.environ``/``os.getenv``
   (auch ``from os import environ``) ausserhalb der Konfigurationsmodule
   (``CONFIG_MODULES``). Verletzung: Anzahl je Datei steigt (neue Datei:
   Basis 0).
6. Stdlib-Blattmodule (``FAN_OUT_EXEMPT_LEAVES``, explizite Allowlist, keine
   Mustererkennung): Importe eines gelisteten Moduls zaehlen nicht zum Fan-out
   der importierenden Module. Ein Blatt ohne Projektabhaengigkeit erzeugt
   weder Kopplung an weitere Projektmodule noch einen Zyklus. Verletzung:
   ein gelistetes Modul importiert irgendetwas ausser Standardbibliothek
   (Modulebene, funktionslokal, bedingt, ``TYPE_CHECKING``, relativ oder
   dynamisch via ``__import__``/``import_module``) oder hat selbst Fan-out > 0.
   Zusaetzlich erzwingt ``leaf_contract_violations`` fuer jedes gelistete Modul:
   - Modulebene nur aus einer Positivliste: Docstring/String-Konstanten,
     ``import``/``from ... import``, ``def``/``async def``/``class``,
     ``pass``, ``if TYPE_CHECKING:`` (nur Importe, kein ``else``) sowie
     Zuweisungen an einfache Namen (auch ``__all__``), deren Wert ein reiner
     Ausdruck ist: Literale, Namen, Attribute, Container, Operatoren,
     Comprehensions, Lambdas und Aufrufe ausschliesslich der reinen
     Konstruktoren ``LEAF_PURE_CALLS``. Klassenkoerper unterliegen derselben
     Regel; Dekoratoren nur aus ``LEAF_PURE_DECORATORS``; Defaults, Basen und
     Klassen-Keywords nur reine Ausdruecke. Alles andere (z. B. ``open(...)``,
     Zuweisung an Attribut/Subscript, ``for``/``with``/``try``/sonstiges
     ``if``) gilt als Modul-Seiteneffekt.
   - Im ganzen Modul (auch in Funktionen) keine dynamischen Importe oder
     Codeausfuehrung: keine Referenz auf ``LEAF_FORBIDDEN_NAMES``
     (``__import__``, ``exec``, ``eval``, ``compile``, ``importlib``,
     ``runpy`` ...), kein Import aus ``LEAF_FORBIDDEN_MODULES``, kein
     Attribut aus ``LEAF_FORBIDDEN_ATTRS`` (``import_module``,
     ``exec_module``, ``run_module``, ``sys.modules`` ...) und kein
     ``getattr``/``setattr``/``delattr`` mit nicht-konstantem oder
     verbotenem Attributnamen, kein Zugriff auf ``LEAF_FORBIDDEN_DOTTED``
     (``sys.modules``, ``sys.path`` ...; auch ueber ``import sys as s`` oder
     ``from sys import path``), keine Zuweisung/Loeschung an Attributen
     importierter Module (z. B. ``json.dumps = ...``). Aliase verbotener
     Importe (``from importlib import import_module as load``) werden
     verfolgt.
   - Jedes Elternpaket (``__init__.py``) eines gelisteten Moduls muss leer
     sein oder selbst alle Blatt-Regeln erfuellen (sonst fuehrt ``import
     core.evidence`` Code aus ``core/__init__.py`` mit aus).
   - Ein gelisteter Modulpfad, der im Backend nicht existiert, ist rot.

Ratschen-Regel: Wird ein Wert schlechter, schlaegt der Lauf fehl und nennt
die konkrete Stelle. Wird er besser, meldet der Lauf das; die Basis darf
dann mit ``--update-baseline`` abgesenkt werden. ``--update-baseline``
verweigert das Schreiben, solange irgendein Wert schlechter als die Basis
ist -- die Basis wird nie angehoben.

Aufruf (aus dem Backend-Verzeichnis):
    python scripts/check_architecture_ratchets.py
    python scripts/check_architecture_ratchets.py --update-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = Path(__file__).resolve().parent / "architecture_ratchets_baseline.json"

EXCLUDED_DIRS = frozenset(
    {"tests", "alembic", "scripts", "migrations", "assets", "node_modules", "venv", "__pycache__"}
)
LAYER_RULES = (("services", "routers"), ("models", "routers"), ("models", "services"))
CONFIG_MODULES = frozenset({"config"})
NEW_MODULE_FAN_OUT_LIMIT = 20
ENV_ATTRS = frozenset({"environ", "getenv", "putenv", "unsetenv"})
# Versionierte Allowlist reiner Stdlib-Blattmodule (Regel 6). Jede Aufnahme ist
# ein eigener, begruendeter Eintrag; das Gate prueft die Blatt-Eigenschaft.
#   core.evidence -- K-1 (A2 M4): kanonische Serialisierung/Evidence-Hash.
FAN_OUT_EXEMPT_LEAVES = frozenset({"core.evidence"})
_STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}
_DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module"})
# Regel 6, Blattvertrag (Positivliste der Modulebene, siehe Docstring).
LEAF_PURE_CALLS = frozenset(
    {"frozenset", "tuple", "dict", "list", "set", "MappingProxyType", "types.MappingProxyType"}
)
LEAF_PURE_DECORATORS = frozenset(
    {
        "property", "staticmethod", "classmethod", "abstractmethod", "abc.abstractmethod",
        "dataclass", "dataclasses.dataclass", "unique", "enum.unique", "overload",
        "typing.overload", "final", "typing.final", "total_ordering",
        "functools.total_ordering", "cached_property", "functools.cached_property",
    }
)
LEAF_FORBIDDEN_NAMES = frozenset(
    {
        "__import__", "exec", "eval", "compile", "importlib", "runpy", "builtins",
        "__builtins__", "globals", "locals", "vars", "breakpoint", "pkgutil", "imp",
        "zipimport",
    }
)
LEAF_FORBIDDEN_DOTTED = frozenset(
    {"sys.modules", "sys.path", "sys.meta_path", "sys.path_hooks", "sys.path_importer_cache"}
)
LEAF_FORBIDDEN_MODULES = frozenset({"importlib", "runpy", "builtins", "imp", "pkgutil", "zipimport"})
LEAF_FORBIDDEN_ATTRS = frozenset(
    {
        "import_module", "__import__", "exec_module", "load_module", "spec_from_file_location",
        "module_from_spec", "run_module", "run_path", "modules", "__builtins__", "__dict__",
        "f_globals", "f_locals",
    }
)
_LEAF_ATTR_FUNCS = frozenset({"getattr", "setattr", "delattr"})


@dataclass
class ModuleScan:
    path: str  # relativ zum Backend, mit '/'
    eager: dict[str, int] = field(default_factory=dict)  # Ziel -> erste Zeile
    lazy: dict[str, int] = field(default_factory=dict)
    typeonly: dict[str, int] = field(default_factory=dict)
    lazy_lines: list[tuple[int, str]] = field(default_factory=list)  # (Zeile, Ziel)
    env_hits: list[tuple[int, str]] = field(default_factory=list)  # (Zeile, Schluessel)
    # Regel 6: jeder Import, der nicht reine Standardbibliothek ist (alle Kontexte).
    non_stdlib_imports: list[tuple[int, str]] = field(default_factory=list)
    # Regel 6, Blattvertrag (nur fuer gelistete Module befuellt): Modul-
    # Seiteneffekte und dynamische Importe/Codeausfuehrung.
    leaf_violations: list[tuple[int, str]] = field(default_factory=list)

    def runtime_targets(self) -> dict[str, int]:
        out = dict(self.lazy)
        for t, ln in self.eager.items():
            out[t] = min(ln, out.get(t, ln))
        return out


def discover_modules(root: Path | None = None) -> dict[str, Path]:
    root = root or BACKEND_ROOT
    mods: dict[str, Path] = {}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in EXCLUDED_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        name = ".".join(rel.with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods[name] = p
    return mods


def _resolver(mods: dict[str, Path]):
    def resolve(name: str) -> str | None:
        parts = name.split(".")
        while parts:
            cand = ".".join(parts)
            if cand in mods:
                return cand
            parts.pop()
        return None

    return resolve


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str, is_pkg: bool, resolve, scan: ModuleScan):
        self.module = module
        self.pkg = module if is_pkg else (module.rsplit(".", 1)[0] if "." in module else "")
        self.resolve = resolve
        self.scan = scan
        self.func_depth = 0
        self.typecheck_depth = 0
        self.os_aliases: set[str] = set()
        self.parents: dict[int, ast.AST] = {}

    # --- Kontext ---
    def _visit_func(self, node):
        self.func_depth += 1
        self.generic_visit(node)
        self.func_depth -= 1

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func
    visit_Lambda = _visit_func

    def visit_If(self, node: ast.If):
        test = ast.unparse(node.test)
        if "TYPE_CHECKING" in test:
            self.typecheck_depth += 1
            for child in node.body:
                self.visit(child)
            self.typecheck_depth -= 1
            for child in node.orelse:
                self.visit(child)
            self.visit(node.test)
        else:
            self.generic_visit(node)

    def generic_visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.parents[id(child)] = node
        super().generic_visit(node)

    # --- Imports ---
    def _record(self, node: ast.stmt, targets: list[str]):
        resolved = []
        for t in targets:
            r = self.resolve(t)
            if r and r != self.module and r not in resolved:
                resolved.append(r)
        if self.typecheck_depth:
            bucket = self.scan.typeonly
        elif self.func_depth:
            bucket = self.scan.lazy
            if resolved:
                self.scan.lazy_lines.append((node.lineno, resolved[0]))
        else:
            bucket = self.scan.eager
        for r in resolved:
            bucket.setdefault(r, node.lineno)

    def _stdlib_check(self, node: ast.stmt, name: str, level: int = 0):
        top = name.split(".", 1)[0]
        if level or top not in _STDLIB or self.resolve(name) is not None:
            self.scan.non_stdlib_imports.append((node.lineno, "." * level + name))

    def visit_Call(self, node: ast.Call):
        f = node.func
        callee = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        if callee in _DYNAMIC_IMPORT_CALLS:
            self.scan.non_stdlib_imports.append((node.lineno, f"<dynamisch: {callee}>"))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for a in node.names:
            self._stdlib_check(node, a.name)
        for a in node.names:
            if a.name == "os" or (a.name.startswith("os.") and not a.asname):
                self.os_aliases.add(a.asname or "os")
        self._record(node, [a.name for a in node.names])

    def visit_ImportFrom(self, node: ast.ImportFrom):
        self._stdlib_check(node, node.module or "", node.level)
        base = node.module or ""
        if node.level:
            bp = self.pkg.split(".") if self.pkg else []
            if node.level > 1:
                bp = bp[: len(bp) - (node.level - 1)]
            base = ".".join(x for x in bp + ([base] if base else []) if x)
        if base == "os" and not node.level:
            for a in node.names:
                if a.name in ENV_ATTRS:
                    self.scan.env_hits.append((node.lineno, f"<from os import {a.name}>"))
        self._record(node, [f"{base}.{a.name}" if base else a.name for a in node.names])

    # --- os.environ / os.getenv ---
    def visit_Attribute(self, node: ast.Attribute):
        if (
            node.attr in ENV_ATTRS
            and isinstance(node.value, ast.Name)
            and node.value.id in (self.os_aliases or {"os"})
        ):
            self.scan.env_hits.append((node.lineno, self._env_key(node)))
        self.generic_visit(node)

    def _env_key(self, node: ast.Attribute) -> str:
        parent = self.parents.get(id(node))
        arg = None
        if node.attr == "environ":
            if isinstance(parent, ast.Subscript) and parent.value is node:
                arg = parent.slice
            elif isinstance(parent, ast.Attribute) and parent.value is node:
                call = self.parents.get(id(parent))
                if isinstance(call, ast.Call) and call.func is parent and call.args:
                    arg = call.args[0]
                else:
                    return f"<environ.{parent.attr}>"
        elif isinstance(parent, ast.Call) and parent.func is node and parent.args:
            arg = parent.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return "<dynamisch>" if arg is not None else "<environ>"


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _pure_expr(node: ast.AST | None) -> bool:
    """Reiner Ausdruck (Positivliste, rekursiv): wertet ohne Seiteneffekt aus."""
    if node is None or isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _pure_expr(node.value)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_pure_expr(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(_pure_expr(k) for k in node.keys) and all(_pure_expr(v) for v in node.values)
    if isinstance(node, ast.Starred):
        return _pure_expr(node.value)
    if isinstance(node, ast.BinOp):
        return _pure_expr(node.left) and _pure_expr(node.right)
    if isinstance(node, ast.UnaryOp):
        return _pure_expr(node.operand)
    if isinstance(node, ast.BoolOp):
        return all(_pure_expr(v) for v in node.values)
    if isinstance(node, ast.Compare):
        return _pure_expr(node.left) and all(_pure_expr(c) for c in node.comparators)
    if isinstance(node, ast.IfExp):
        return all(_pure_expr(x) for x in (node.test, node.body, node.orelse))
    if isinstance(node, ast.Subscript):
        return _pure_expr(node.value) and _pure_expr(node.slice)
    if isinstance(node, ast.Slice):
        return all(_pure_expr(x) for x in (node.lower, node.upper, node.step))
    if isinstance(node, ast.JoinedStr):
        return all(_pure_expr(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _pure_expr(node.value) and _pure_expr(node.format_spec)
    if isinstance(node, ast.Lambda):
        return _pure_args(node.args)
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        elts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        return all(_pure_expr(e) for e in elts) and all(
            _pure_target(g.target) and _pure_expr(g.iter) and all(_pure_expr(i) for i in g.ifs)
            for g in node.generators
        )
    if isinstance(node, ast.Call):
        return (
            _dotted(node.func) in LEAF_PURE_CALLS
            and all(_pure_expr(a) for a in node.args)
            and all(_pure_expr(k.value) for k in node.keywords)
        )
    return False


def _pure_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(_pure_target(e) for e in node.elts)
    return False


def _pure_args(args: ast.arguments) -> bool:
    return all(_pure_expr(d) for d in args.defaults) and all(
        _pure_expr(d) for d in args.kw_defaults
    )


def _pure_decorator(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        return (
            _dotted(node.func) in LEAF_PURE_DECORATORS
            and all(_pure_expr(a) for a in node.args)
            and all(_pure_expr(k.value) for k in node.keywords)
        )
    return _dotted(node) in LEAF_PURE_DECORATORS


def _leaf_body_violations(body: list[ast.stmt], where: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for st in body:
        if isinstance(st, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if (
            isinstance(st, ast.Expr)
            and isinstance(st.value, ast.Constant)
            and isinstance(st.value.value, str)
        ):
            continue
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if all(_pure_decorator(d) for d in st.decorator_list) and _pure_args(st.args):
                continue
        elif isinstance(st, ast.ClassDef):
            if (
                all(_pure_decorator(d) for d in st.decorator_list)
                and all(_pure_expr(b) for b in st.bases)
                and all(_pure_expr(k.value) for k in st.keywords)
            ):
                out.extend(_leaf_body_violations(st.body, f"in Klasse {st.name}"))
                continue
        elif isinstance(st, ast.Assign):
            if all(_pure_target(t) for t in st.targets) and _pure_expr(st.value):
                continue
        elif isinstance(st, ast.AnnAssign):
            if isinstance(st.target, ast.Name) and _pure_expr(st.value):
                continue
        elif (
            isinstance(st, ast.If)
            and _dotted(st.test) in ("TYPE_CHECKING", "typing.TYPE_CHECKING")
            and not st.orelse
            and all(isinstance(c, (ast.Import, ast.ImportFrom, ast.Pass)) for c in st.body)
        ):
            continue
        first = ast.unparse(st).splitlines()[0][:80]
        out.append((st.lineno, f"<Seiteneffekt {where}: {first}>"))
    return out


def leaf_contract_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Regel 6, Blattvertrag: Modulebene nur aus der Positivliste; im ganzen
    Modul keine dynamischen Importe oder Codeausfuehrung."""
    out = _leaf_body_violations(tree.body, "auf Modulebene")
    # Aliase: importierte Module (fuer Attribut-Zuweisungen), sys-Aliase und
    # Namen, die aus verbotenen Modulen/Attributen importiert wurden.
    module_aliases: set[str] = set()
    sys_aliases: set[str] = {"sys"}
    forbidden_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                bound = a.asname or a.name.split(".", 1)[0]
                module_aliases.add(bound)
                if a.name == "sys":
                    sys_aliases.add(bound)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".", 1)[0]
            for a in node.names:
                bound = a.asname or a.name
                if (
                    top in LEAF_FORBIDDEN_MODULES
                    or a.name in LEAF_FORBIDDEN_NAMES | LEAF_FORBIDDEN_ATTRS
                    or f"{node.module}.{a.name}" in LEAF_FORBIDDEN_DOTTED
                ):
                    forbidden_aliases.add(bound)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in LEAF_FORBIDDEN_NAMES | forbidden_aliases:
            out.append((node.lineno, f"<dynamisch: {node.id}>"))
        elif isinstance(node, ast.Attribute) and (
            isinstance(node.value, ast.Name)
            and node.value.id in sys_aliases
            and f"sys.{node.attr}" in LEAF_FORBIDDEN_DOTTED
        ):
            out.append((node.lineno, f"<dynamisch: sys.{node.attr}>"))
        elif isinstance(node, ast.Attribute) and node.attr in LEAF_FORBIDDEN_ATTRS:
            out.append((node.lineno, f"<dynamisch: .{node.attr}>"))
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = (
                node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            )
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, (ast.Attribute, ast.Subscript)):
                        root = sub
                        while isinstance(root, (ast.Attribute, ast.Subscript)):
                            root = root.value
                        if isinstance(root, ast.Name) and root.id in module_aliases:
                            out.append(
                                (node.lineno, f"<Modul-Attribut veraendert: {ast.unparse(sub)}>")
                            )
                            break
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".", 1)[0] in LEAF_FORBIDDEN_MODULES:
                    out.append((node.lineno, f"<dynamisch: import {a.name}>"))
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".", 1)[0]
            if top in LEAF_FORBIDDEN_MODULES or any(
                a.name in LEAF_FORBIDDEN_NAMES | LEAF_FORBIDDEN_ATTRS for a in node.names
            ):
                out.append((node.lineno, f"<dynamisch: from {node.module} import ...>"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _LEAF_ATTR_FUNCS
        ):
            name = node.args[1] if len(node.args) > 1 else None
            if not (isinstance(name, ast.Constant) and isinstance(name.value, str)) or (
                name.value in LEAF_FORBIDDEN_ATTRS | LEAF_FORBIDDEN_NAMES
            ):
                out.append((node.lineno, f"<dynamisch: {node.func.id}(...)>"))
    return sorted(set(out))


def _leaf_parent_packages() -> set[str]:
    """Alle Elternpakete der gelisteten Blattmodule (``core.evidence`` -> ``core``)."""
    out: set[str] = set()
    for m in FAN_OUT_EXEMPT_LEAVES:
        parts = m.split(".")[:-1]
        while parts:
            out.add(".".join(parts))
            parts.pop()
    return out


def scan_backend(root: Path | None = None) -> dict[str, ModuleScan]:
    root = root or BACKEND_ROOT
    mods = discover_modules(root)
    resolve = _resolver(mods)
    scans: dict[str, ModuleScan] = {}
    for name, path in mods.items():
        src = path.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(src, filename=str(path))
        scan = ModuleScan(path=path.relative_to(root).as_posix())
        _Visitor(name, path.name == "__init__.py", resolve, scan).visit(tree)
        if name in FAN_OUT_EXEMPT_LEAVES or name in _leaf_parent_packages():
            scan.leaf_violations = leaf_contract_violations(tree)
        scan.lazy_lines.sort()
        scan.env_hits.sort()
        scans[name] = scan
    return scans


def strongly_connected(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan, iterativ, deterministisch (sortierte Knoten/Nachbarn)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    out: list[list[str]] = []
    counter = 0
    for start in sorted(graph):
        if start in index:
            continue
        work = [(start, iter(sorted(graph.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(graph.get(w, ())))))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return sorted(out, key=lambda c: (-len(c), c))


def _layer(module: str) -> str:
    return module.split(".", 1)[0]


def measure(scans: dict[str, ModuleScan]) -> dict:
    eager_graph = {m: sorted(s.eager) for m, s in scans.items()}
    all_graph = {m: sorted(s.runtime_targets()) for m, s in scans.items()}
    layer = []
    for m, s in scans.items():
        targets = set(s.eager) | set(s.lazy) | set(s.typeonly)
        for t in targets:
            if (_layer(m), _layer(t)) in LAYER_RULES:
                layer.append(f"{m} -> {t}")
    env = {}
    for m, s in scans.items():
        if m in CONFIG_MODULES or not s.env_hits:
            continue
        env[s.path] = {"count": len(s.env_hits), "keys": sorted({k for _, k in s.env_hits})}
    return {
        "cycles_eager": strongly_connected(eager_graph),
        "cycles_all": strongly_connected(all_graph),
        "lazy_imports": {m: len(s.lazy_lines) for m, s in sorted(scans.items()) if s.lazy_lines},
        "fan_out": {
            m: kept
            for m, t in sorted(all_graph.items())
            if (kept := [x for x in t if x not in FAN_OUT_EXEMPT_LEAVES])
        },
        "layer_violations": sorted(layer),
        "env_readers": dict(sorted(env.items())),
    }


@dataclass
class Result:
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)


def _loc(scans: dict[str, ModuleScan], module: str, line: int) -> str:
    return f"{scans[module].path}:{line}" if module in scans else f"{module}:{line}"


def compare(current: dict, baseline: dict, scans: dict[str, ModuleScan]) -> Result:
    res = Result()

    base_fan = baseline.get("fan_out", {})

    # 1. Zyklen
    for key, graph_of in (
        ("cycles_eager", lambda s: s.eager),
        ("cycles_all", lambda s: s.runtime_targets()),
    ):
        base_sets = [set(c) for c in baseline.get(key, [])]
        base_of = {m: i for i, c in enumerate(base_sets) for m in c}
        for comp in current[key]:
            if any(set(comp) <= b for b in base_sets):
                continue
            members = set(comp)
            inner = [
                (src, dst, line)
                for src in comp
                for dst, line in sorted(graph_of(scans[src]).items())
                if dst in members
            ]
            # Bevorzugt Kanten, die es in der Basis gar nicht gab; sonst die
            # Kanten, die bisher getrennte Komponenten verbinden.
            closing = [e for e in inner if e[1] not in base_fan.get(e[0], [])] or [
                e for e in inner if e[0] not in base_of or base_of.get(e[1]) != base_of[e[0]]
            ]
            edges = "; ".join(f"{s} -> {d} ({_loc(scans, s, ln)})" for s, d, ln in closing)
            res.regressions.append(
                f"[{key}] neuer oder erweiterter Zyklus ({len(comp)} Module), "
                f"schliessende Kante(n): {edges}; Module: {', '.join(comp)}"
            )
        cur_n = sum(len(c) for c in current[key])
        base_n = sum(len(c) for c in base_sets)
        worse = any(r.startswith(f"[{key}]") for r in res.regressions)
        if not worse and (cur_n < base_n or len(current[key]) < len(base_sets)):
            res.improvements.append(
                f"[{key}] {len(current[key])} Zyklen/{cur_n} Module (Basis {len(base_sets)}/{base_n})"
            )

    # 2. Lazy-Imports
    base_lazy = baseline.get("lazy_imports", {})
    for m, n in current["lazy_imports"].items():
        allowed = base_lazy.get(m, 0)
        if n > allowed:
            known = set(base_fan.get(m, []))
            lines = scans[m].lazy_lines
            new = [(ln, t) for ln, t in lines if t not in known] or lines
            detail = "; ".join(f"{_loc(scans, m, ln)} -> {t}" for ln, t in new)
            res.regressions.append(f"[lazy_imports] {m}: {n} > Basis {allowed}: {detail}")
    for m, allowed in base_lazy.items():
        if current["lazy_imports"].get(m, 0) < allowed:
            res.improvements.append(
                f"[lazy_imports] {m}: {current['lazy_imports'].get(m, 0)} < Basis {allowed}"
            )

    # 3. Fan-out
    for m, targets in current["fan_out"].items():
        if m in base_fan:
            allowed, known = len(base_fan[m]), set(base_fan[m])
        else:
            allowed, known = NEW_MODULE_FAN_OUT_LIMIT, set()
        if len(targets) > allowed:
            rt = scans[m].runtime_targets()
            new = [t for t in targets if t not in known] if known else targets
            detail = "; ".join(f"{_loc(scans, m, rt[t])} -> {t}" for t in new)
            res.regressions.append(f"[fan_out] {m}: {len(targets)} > Basis {allowed}: {detail}")
    for m, known in base_fan.items():
        if len(current["fan_out"].get(m, [])) < len(known):
            res.improvements.append(
                f"[fan_out] {m}: {len(current['fan_out'].get(m, []))} < Basis {len(known)}"
            )

    # 6. Stdlib-Blattmodule (vor Schichtung gemeldet, weil Regel 3 davon abhaengt)
    for m in sorted(FAN_OUT_EXEMPT_LEAVES):
        s = scans.get(m)
        if s is None:
            res.regressions.append(
                f"[fan_out_exempt_leaves] {m}: gelistet, aber kein Modul mit diesem "
                f"exakten Pfad im Backend"
            )
            continue
        own = {**s.typeonly, **s.runtime_targets()}
        bad = sorted(
            set(s.non_stdlib_imports) | set(s.leaf_violations) | {(ln, t) for t, ln in own.items()}
        )
        if bad:
            detail = "; ".join(f"{s.path}:{ln} -> {t}" for ln, t in bad)
            res.regressions.append(
                f"[fan_out_exempt_leaves] {m}: kein reines Stdlib-Blatt "
                f"(nur Standardbibliothek, Fan-out 0, keine Modul-Seiteneffekte, "
                f"keine dynamischen Importe): {detail}"
            )

    # 6b. Elternpakete gelisteter Blattmodule (fehlendes __init__ = Namespace, ok)
    for pkg in sorted(_leaf_parent_packages()):
        s = scans.get(pkg)
        if s is None or not s.path.endswith("__init__.py"):
            continue
        own = {**s.typeonly, **s.runtime_targets()}
        bad = sorted(
            set(s.non_stdlib_imports) | set(s.leaf_violations) | {(ln, t) for t, ln in own.items()}
        )
        if bad:
            detail = "; ".join(f"{s.path}:{ln} -> {t}" for ln, t in bad)
            res.regressions.append(
                f"[fan_out_exempt_leaves] {pkg} (Elternpaket eines Blattmoduls): muss leer "
                f"sein oder die Blatt-Regeln erfuellen: {detail}"
            )

    # 4. Schichtung
    base_layer = set(baseline.get("layer_violations", []))
    for edge in current["layer_violations"]:
        if edge not in base_layer:
            src, dst = edge.split(" -> ")
            s = scans[src]
            line = s.eager.get(dst) or s.lazy.get(dst) or s.typeonly.get(dst)
            res.regressions.append(f"[layer_violations] {edge} ({_loc(scans, src, line)})")
    for edge in sorted(base_layer - set(current["layer_violations"])):
        res.improvements.append(f"[layer_violations] {edge} entfernt")

    # 5. Umgebungsvariablen
    base_env = baseline.get("env_readers", {})
    by_path = {s.path: s for s in scans.values()}
    for path, info in current["env_readers"].items():
        allowed = base_env.get(path, {}).get("count", 0)
        if info["count"] > allowed:
            known = set(base_env.get(path, {}).get("keys", []))
            hits = by_path[path].env_hits
            new = [(ln, k) for ln, k in hits if k not in known] or hits
            detail = "; ".join(f"{path}:{ln} ({k})" for ln, k in new)
            res.regressions.append(
                f"[env_readers] {path}: {info['count']} > Basis {allowed} "
                f"(nur Konfigurationsmodule duerfen die Umgebung lesen): {detail}"
            )
    for path, info in base_env.items():
        cur = current["env_readers"].get(path, {}).get("count", 0)
        if cur < info["count"]:
            res.improvements.append(f"[env_readers] {path}: {cur} < Basis {info['count']}")
    return res


def summary(current: dict) -> str:
    return (
        f"Zyklen eager {len(current['cycles_eager'])}, "
        f"Zyklen inkl. lazy {len(current['cycles_all'])} "
        f"({sum(len(c) for c in current['cycles_all'])} Module, groesster "
        f"{max((len(c) for c in current['cycles_all']), default=0)}), "
        f"Lazy-Imports {sum(current['lazy_imports'].values())}, "
        f"Fan-out max {max((len(v) for v in current['fan_out'].values()), default=0)}, "
        f"Schichtverletzungen {len(current['layer_violations'])}, "
        f"Env-Zugriffe {sum(v['count'] for v in current['env_readers'].values())} "
        f"in {len(current['env_readers'])} Dateien"
    )


def dump_baseline(data: dict) -> str:
    """Stabiles, diff-freundliches JSON: ein Eintrag je Zeile."""
    out = ["{"]
    keys = list(data)
    for i, key in enumerate(keys):
        value = data[key]
        out.append(f"  {json.dumps(key)}: " + ("[" if isinstance(value, list) else "{"))
        items = (
            [json.dumps(v, sort_keys=True) for v in value]
            if isinstance(value, list)
            else [f"{json.dumps(k)}: {json.dumps(v, sort_keys=True)}" for k, v in value.items()]
        )
        for j, item in enumerate(items):
            out.append(f"    {item}" + ("," if j < len(items) - 1 else ""))
        out.append("  " + ("]" if isinstance(value, list) else "}") + ("," if i < len(keys) - 1 else ""))
    out.append("}")
    return "\n".join(out) + "\n"


def load_baseline(path: Path | None = None) -> dict:
    return json.loads((path or BASELINE_FILE).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    scans = scan_backend()
    current = measure(scans)
    print(f"Architektur-Ratschen: {summary(current)}")
    if not BASELINE_FILE.is_file():
        print(f"Basisdatei fehlt: {BASELINE_FILE}", file=sys.stderr)
        return 1
    res = compare(current, load_baseline(), scans)
    for line in res.regressions:
        print(f"VERSCHLECHTERT {line}", file=sys.stderr)
    for line in res.improvements:
        print(f"VERBESSERT {line}")
    if res.regressions:
        print(
            "ARCHITEKTUR-RATSCHE VERLETZT: Basiswerte werden nie angehoben -- "
            "Import/Zugriff anders loesen (Konfiguration ueber config.Settings, "
            "Abhaengigkeit umdrehen oder Daten uebergeben).",
            file=sys.stderr,
        )
        return 1
    if args.update_baseline:
        BASELINE_FILE.write_text(dump_baseline(current), encoding="utf-8", newline="\n")
        print(f"Basis abgesenkt/aktualisiert: {BASELINE_FILE.name}")
    elif res.improvements:
        print("Basis kann abgesenkt werden: python scripts/check_architecture_ratchets.py --update-baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
