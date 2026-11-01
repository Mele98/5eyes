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
     Konstruktoren ``LEAF_PURE_CALL_ORIGINS``. Klassenkoerper unterliegen derselben
     Regel; Dekoratoren nur aus ``LEAF_PURE_DECORATORS``; Aufrufe und
     Dekoratoren werden ueber ihre Import-Herkunft aufgeloest (Alias ->
     Original, z. B. ``from enum import property as unique`` ist
     ``enum.property`` und damit rot; lokal neu gebundene Namen sind rot);
     Defaults und
     Annotationen nur reine Ausdruecke. Alles andere (z. B. ``open(...)``,
     Zuweisung an Attribut/Subscript, ``for``/``with``/``try``/sonstiges
     ``if``) gilt als Modul-Seiteneffekt.
   - Gegen Code des eigenen Moduls beim Import (N-K1, N-842-1): Subscripts
     ``X[...]`` nur auf importierte Stdlib-Namen (``typing`` & Co.) oder
     eingebaute Generics (``tuple``, ``dict`` ...), nie auf eigene Namen
     (``__class_getitem__``). Klassenbasen nur aus ``LEAF_ALLOWED_BASES``
     (Enum-Familie, ``object``/``str``/``int``, Exception-Hierarchie,
     ``NamedTuple``/``TypedDict``/``Protocol``, ``ABC``) oder bereits
     gepruefte eigene Klassen; Klassen-Keywords nur
     ``LEAF_ALLOWED_CLASS_KEYWORDS`` (nie ``metaclass=``). Keine Hook-
     Methoden/-Namen (Dunder/Sunder wie ``__init_subclass__``,
     ``__set_name__``, Modul-``__getattr__``): erlaubt sind nur
     ``LEAF_ALLOWED_DUNDER_METHODS`` in Nicht-Enum-Klassen (Enum-``__init__``
     liefe beim Klassenbau), ``__all__`` auf Modulebene und ``__slots__`` in
     Klassen. Kein ``property``/``cached_property`` in Enum-Klassen
     (Enum-Mitglieder sind Instanzen ohne Aufruf; ``E.A.prop`` fuehrte den
     Getter beim Import aus), kein ``cached_property`` und keine Kombination
     ``classmethod`` + ``property`` in irgendeiner Klasse.
   - Stdlib-Importe (alle Kontexte) nur aus der Positivliste
     ``LEAF_ALLOWED_STDLIB`` (N-K1; sonst z. B. ``pydoc.locate``, ``pickle``,
     ``logging.config`` als dynamischer Projektimport).
   - Im ganzen Modul (auch in Funktionen) rot als dynamischer Import bzw.
     Codeausfuehrung: jede Referenz auf ``LEAF_FORBIDDEN_NAMES``
     (``__import__``, ``exec``, ``eval``, ``compile``, ``importlib``,
     ``runpy`` ...), kein Import aus ``LEAF_FORBIDDEN_MODULES``, kein
     Attribut aus ``LEAF_FORBIDDEN_ATTRS`` (``import_module``,
     ``exec_module``, ``run_module``, ``sys.modules`` ...) und kein
     ``getattr``/``setattr``/``delattr`` mit nicht-konstantem, verbotenem
     oder Dunder-Attributnamen, kein ``setattr``/``delattr`` auf importierte
     Namen (auch mit Literal-Namen), kein Dunder-Attribut ausser
     ``LEAF_ALLOWED_DUNDER_ATTRS`` und kein Dunder-String-Subscript
     (``d["__builtins__"]``), kein Zugriff auf ``LEAF_FORBIDDEN_DOTTED``
     (``sys.modules``, ``sys.path`` ...; auch ueber ``import sys as s`` oder
     ``from sys import path``), keine Zuweisung/Loeschung an Attributen
     importierter Module (z. B. ``json.dumps = ...``). Aliase verbotener
     Importe (``from importlib import import_module as load``) werden
     verfolgt.
   - Importierte Module/Namen (N-842-2): keine Stern-Importe; kein
     ``import a.b`` ohne ``as`` (bindet das Elternpaket ``a``); Attributketten
     ueber importierte Namen hoechstens eine Stufe (``json.dumps`` ja,
     ``enum.bltns.eval`` nein), keine Attribute mit fuehrendem Unterstrich
     (``typing._eval_type``); ein per ``import`` gebundenes Modul nur als
     ``modul.attr``, nie als blosser Wert (``b = enum``); ``modul.attr`` und
     ``from modul import name`` duerfen kein Modulobjekt liefern
     (``enum.bltns``, ``from typing import sys``; geprueft gegen den
     laufenden Interpreter).
   - Jedes Elternpaket (``__init__.py``) eines gelisteten Moduls muss leer
     sein oder selbst alle Blatt-Regeln erfuellen (sonst fuehrt ``import
     core.evidence`` Code aus ``core/__init__.py`` mit aus).
   - Ein gelisteter Modulpfad, der im Backend nicht existiert, ist rot.
   - Modulaufloesung (N-844-1): Fuer jedes gelistete Blatt und jedes seiner
     Elternpakete muss genau die erwartete Datei existieren (Blatt:
     ``core/evidence.py``, Elternpaket: ``core/__init__.py``, also kein
     Namespace-Paket). Daneben darf es keinen weiteren Eintrag mit demselben
     Modulnamen geben (Paketverzeichnis, Namespace-Verzeichnis, ``.pyd``/
     ``.so``/``.pyc``/``.pyw`` ..., Gross-/Kleinschreibung ignoriert), und
     ``importlib.machinery.PathFinder.find_spec`` (nur Aufloesung, kein
     Import) muss genau diese Datei als ``origin`` liefern. Zusaetzlich ist
     im ganzen Backend jeder Modulname rot, auf den zwei ``.py``-Dateien
     abgebildet werden (``x.py`` neben ``x/__init__.py``).
   - Inhalts-Pin: Die Basis fuehrt unter ``leaf_content_sha256`` je
     gelistetem Blatt und je Elternpaket-``__init__.py`` den SHA-256 des
     Dateiinhalts (Bytes, CRLF zu LF normalisiert, damit Windows-Checkouts
     und Linux-CI denselben Wert liefern; das Repo speichert per
     ``.gitattributes`` ohnehin LF). Die Pins sind exakt: weicht ein Inhalt
     ab, fehlt ein Pin oder gibt es zu einem Pin keine Datei bzw. kein
     gelistetes Modul mehr, ist die Ratsche rot. Pins werden nur bewusst im
     Review gesetzt, nachgefuehrt oder entfernt:
     ``python scripts/check_architecture_ratchets.py --update-leaf-pins``
     (verweigert, solange irgendeine andere Regel verletzt ist;
     ``--update-baseline`` aendert keine Pins).

   Grenzen: Die AST-Regeln sind eine konservative Naeherung, kein Beweis,
   dass ein Blatt beim Import keinen eigenen Code ausfuehren kann; Python
   bietet mehr Wege, als eine statische Pruefung vollstaendig erfassen kann.
   Nicht geprueft werden z. B. Bytecode-Caches in ``__pycache__`` (nicht
   versioniert), ``.pth``-Dateien oder fremde Eintraege auf ``sys.path``
   vor dem Backend. Der Inhalts-Pin sorgt dafuer, dass jede Aenderung an
   einem Blatt sichtbar im Review landet. Das Review des Blatt-Diffs ist die
   letzte Instanz.

Ratschen-Regel: Wird ein Wert schlechter, schlaegt der Lauf fehl und nennt
die konkrete Stelle. Wird er besser, meldet der Lauf das; die Basis darf
dann mit ``--update-baseline`` abgesenkt werden. ``--update-baseline``
verweigert das Schreiben, solange irgendein Wert schlechter als die Basis
ist -- die Basis wird nie angehoben.

Aufruf (aus dem Backend-Verzeichnis):
    python scripts/check_architecture_ratchets.py
    python scripts/check_architecture_ratchets.py --update-baseline
    python scripts/check_architecture_ratchets.py --update-leaf-pins
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.machinery
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

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
#   core.reason_codes -- K-2/K-2b (A2 M5/M17): Reason-Code-Katalog + DomainError;
#     Ziel jedes Service-Imports der DomainError-Migration (nur enum/typing).
FAN_OUT_EXEMPT_LEAVES = frozenset({"core.evidence", "core.reason_codes"})
_STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}
_DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module"})
# Regel 6, Blattvertrag (Positivliste der Modulebene, siehe Docstring).
# Qualifizierte Herkunft (N-844-3): Namen werden ueber die Importe des Blatts
# aufgeloest, ungebundene Namen als ``builtins.<name>``.
LEAF_PURE_CALL_ORIGINS = frozenset(
    {
        "builtins.frozenset", "builtins.tuple", "builtins.dict", "builtins.list",
        "builtins.set", "types.MappingProxyType",
    }
)
LEAF_PURE_DECORATORS = frozenset(
    {
        "builtins.property", "builtins.staticmethod", "builtins.classmethod",
        "abc.abstractmethod", "dataclasses.dataclass", "enum.unique", "typing.overload",
        "typing.final", "functools.total_ordering", "functools.cached_property",
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
        # Codeausfuehrung ueber Module der Blatt-Positivliste (N-K1):
        "CodeType", "FunctionType", "LambdaType", "get_type_hints", "ForwardRef",
        "evaluate_forward_ref", "_eval_type", "make_dataclass",
    }
)
_LEAF_ATTR_FUNCS = frozenset({"getattr", "setattr", "delattr"})
# N-K1: Positivliste der Stdlib-Module, die ein Blatt importieren darf (exakte
# Modulnamen, alle Kontexte). Heute genutzt: __future__, hashlib, json, types,
# typing (core.evidence) und enum, typing (core.reason_codes); dazu nur die
# Module, deren Dekoratoren LEAF_PURE_DECORATORS nennt, und collections.abc.
# Alles andere (pydoc, pickle, logging.config, ...) ist rot -- auch in Funktionen.
LEAF_ALLOWED_STDLIB = frozenset(
    {
        "__future__", "abc", "collections.abc", "dataclasses", "enum", "functools",
        "hashlib", "json", "types", "typing",
    }
)
# N-K1: Basisklassen von Blatt-Klassen (qualifiziert); zusaetzlich erlaubt sind
# nur bereits gepruefte eigene Klassen des Moduls. Kein metaclass=.
LEAF_ALLOWED_BASES = frozenset(
    {
        "builtins.object", "builtins.str", "builtins.int",
        "builtins.Exception", "builtins.ValueError", "builtins.TypeError",
        "builtins.KeyError", "builtins.LookupError", "builtins.RuntimeError",
        "enum.Enum", "enum.IntEnum", "enum.StrEnum", "enum.Flag", "enum.IntFlag",
        "typing.NamedTuple", "typing.TypedDict", "typing.Protocol", "abc.ABC",
    }
)
LEAF_ALLOWED_CLASS_KEYWORDS = frozenset({"total"})  # TypedDict
# Dunder-Methoden in Nicht-Enum-Klassen (laufen nur an Instanzen, nie beim
# Import); Enum-Klassen und Modulebene: keine Dunder-/Sunder-Methoden.
LEAF_ALLOWED_DUNDER_METHODS = frozenset(
    {"__init__", "__post_init__", "__repr__", "__str__", "__eq__", "__hash__"}
)
LEAF_ALLOWED_MODULE_HOOK_NAMES = frozenset({"__all__"})
LEAF_ALLOWED_CLASS_HOOK_NAMES = frozenset({"__slots__"})
LEAF_ALLOWED_DUNDER_ATTRS = frozenset({"__init__"})  # super().__init__(...)
LEAF_BUILTIN_GENERICS = frozenset({"tuple", "list", "dict", "set", "frozenset", "type"})
# N-842-1: Properties auf Enum-Mitgliedern laufen beim Attributzugriff auf
# Modulebene; ``cached_property`` und ``classmethod``+``property`` sind nirgends
# erlaubt (``property`` in Nicht-Enum-Klassen bleibt erlaubt: Instanzen eigener
# Klassen entstehen beim Import nicht, weil eigene Aufrufe rot sind).
LEAF_PROPERTY_DECORATORS = frozenset({"builtins.property", "functools.cached_property"})
LEAF_CACHED_PROPERTY_DECORATORS = frozenset({"functools.cached_property"})
# N-844-1: Dateiendungen, unter denen Python ein Modul laden kann (zusaetzlich zu
# denen des laufenden Interpreters, damit Linux und Windows dasselbe melden).
LEAF_LOADABLE_SUFFIXES = tuple(
    sorted(
        {s.casefold() for s in importlib.machinery.all_suffixes()}
        | {".py", ".pyw", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib"}
    )
)
# Inhalts-Pin (Regel 6): Schluessel in der Basis, Befehl zum bewussten Nachfuehren.
LEAF_PIN_KEY = "leaf_content_sha256"
LEAF_PIN_UPDATE_CMD = "python scripts/check_architecture_ratchets.py --update-leaf-pins"
_NOT_ALLOWED_STDLIB = "Stdlib-Modul nicht auf Blatt-Positivliste"


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
    # Inhalts-Pin (nur fuer gelistete Blaetter und deren Elternpakete).
    content_sha256: str | None = None
    # N-844-1: alle Dateien, die auf denselben Modulnamen abgebildet werden
    # (nur befuellt, wenn es mehr als eine ist).
    collisions: list[str] = field(default_factory=list)
    # N-844-1: Abweichungen der Modulaufloesung (nur fuer gelistete Blaetter).
    resolution_problems: list[str] = field(default_factory=list)

    def runtime_targets(self) -> dict[str, int]:
        out = dict(self.lazy)
        for t, ln in self.eager.items():
            out[t] = min(ln, out.get(t, ln))
        return out


def discover_modules(root: Path | None = None) -> dict[str, Path]:
    return _discover(root)[0]


def _discover(root: Path | None = None) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    """Module und Namenskollisionen (mehrere Dateien fuer denselben Modulnamen,
    z. B. ``x.py`` neben ``x/__init__.py``; Python laedt dann das Paket)."""
    root = root or BACKEND_ROOT
    mods: dict[str, Path] = {}
    all_paths: dict[str, list[Path]] = {}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in EXCLUDED_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        name = ".".join(rel.with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods[name] = p
        all_paths.setdefault(name, []).append(p)
    return mods, {n: ps for n, ps in all_paths.items() if len(ps) > 1}


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


@dataclass
class _LeafCtx:
    """Namensbindungen der Modulebene eines Blattmoduls (fuer Regel 6)."""

    imports: dict[str, str]  # durch Import gebundener Name -> qualifizierter Ursprung
    bound: dict[str, int]  # sonst auf Modulebene gebundener Name -> Anzahl Bindungen
    classes: dict[str, bool] = field(default_factory=dict)  # eigene Klasse -> Enum-Familie

    @classmethod
    def of(cls, tree: ast.Module) -> _LeafCtx:
        imports: dict[str, str] = {}
        bound: dict[str, int] = {}

        def bind(name: str) -> None:
            bound[name] = bound.get(name, 0) + 1

        def walk(body: list[ast.stmt]) -> None:
            for st in body:
                if isinstance(st, ast.Import):
                    for a in st.names:
                        top = a.name.split(".", 1)[0]
                        imports[a.asname or top] = a.name if a.asname else top
                elif isinstance(st, ast.ImportFrom):
                    base = "." * st.level + (st.module or "")
                    for a in st.names:
                        imports[a.asname or a.name] = f"{base}.{a.name}"
                elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    bind(st.name)
                elif isinstance(st, ast.If):
                    walk(st.body)
                    walk(st.orelse)
                else:  # Zuweisungen, for/with/try/...: alle gebundenen Namen zaehlen
                    for sub in ast.walk(st):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                            bind(sub.id)

        walk(tree.body)
        return cls(imports=imports, bound=bound)

    def generic_alias_ok(self, node: ast.AST) -> bool:
        """Subscript-Ziel ``X[...]`` nur auf importierte Stdlib-Namen (``typing``
        & Co.) oder unveraenderte eingebaute Generics -- nie auf Namen des eigenen
        Moduls (``__class_getitem__``/``__getitem__`` liefen sonst beim Import)."""
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or root.id in self.bound:
            return False
        return root.id in self.imports or root.id in LEAF_BUILTIN_GENERICS

    def base_origin(self, node: ast.AST) -> str | None:
        """Qualifizierter Ursprung einer Basisklasse, ``own:<Name>`` fuer eine
        bereits gepruefte eigene Klasse, sonst ``None`` (= nicht erlaubt)."""
        if isinstance(node, ast.Name):
            n = node.id
            if n in self.classes and self.bound.get(n) == 1 and n not in self.imports:
                return f"own:{n}"
            if n in self.bound:
                return None
            return self.imports.get(n, f"builtins.{n}")
        if isinstance(node, ast.Attribute):
            head, _, rest = _dotted(node).partition(".")
            if rest and head in self.imports and head not in self.bound:
                return f"{self.imports[head]}.{rest}"
        return None


def _origin(node: ast.AST, ctx: _LeafCtx | None) -> str | None:
    """Qualifizierte Herkunft eines Namens/Attributs (N-844-3): Importe werden
    aufgeloest (``from enum import property as unique`` -> ``enum.property``),
    ungebundene Namen gelten als ``builtins.<name>``, auf Modulebene neu
    gebundene Namen liefern ``None`` (= nicht erlaubt)."""
    dotted = _dotted(node)
    if not dotted:
        return None
    head, _, rest = dotted.partition(".")
    imports = ctx.imports if ctx is not None else {}
    bound = ctx.bound if ctx is not None else {}
    if head in bound:
        return None
    base = imports.get(head, f"builtins.{head}")
    return f"{base}.{rest}" if rest else base


def _special(name: str) -> bool:
    """Dunder-/Sunder-Name (``__x__``/``_x_``): Hook-Namen der Laufzeit."""
    return len(name) > 2 and name.startswith("_") and name.endswith("_")


def _pure_expr(node: ast.AST | None, ctx: _LeafCtx | None = None) -> bool:
    """Reiner Ausdruck (Positivliste, rekursiv): wertet ohne Seiteneffekt aus.

    Ohne ``ctx`` ist jedes Subscript unrein (fail-closed)."""
    if node is None or isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _pure_expr(node.value, ctx)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_pure_expr(e, ctx) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(_pure_expr(k, ctx) for k in node.keys) and all(
            _pure_expr(v, ctx) for v in node.values
        )
    if isinstance(node, ast.Starred):
        return _pure_expr(node.value, ctx)
    if isinstance(node, ast.BinOp):
        return _pure_expr(node.left, ctx) and _pure_expr(node.right, ctx)
    if isinstance(node, ast.UnaryOp):
        return _pure_expr(node.operand, ctx)
    if isinstance(node, ast.BoolOp):
        return all(_pure_expr(v, ctx) for v in node.values)
    if isinstance(node, ast.Compare):
        return _pure_expr(node.left, ctx) and all(_pure_expr(c, ctx) for c in node.comparators)
    if isinstance(node, ast.IfExp):
        return all(_pure_expr(x, ctx) for x in (node.test, node.body, node.orelse))
    if isinstance(node, ast.Subscript):
        return (
            ctx is not None
            and ctx.generic_alias_ok(node.value)
            and _pure_expr(node.value, ctx)
            and _pure_expr(node.slice, ctx)
        )
    if isinstance(node, ast.Slice):
        return all(_pure_expr(x, ctx) for x in (node.lower, node.upper, node.step))
    if isinstance(node, ast.JoinedStr):
        return all(_pure_expr(v, ctx) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _pure_expr(node.value, ctx) and _pure_expr(node.format_spec, ctx)
    if isinstance(node, ast.Lambda):
        return _pure_args(node.args, ctx)
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        elts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        return all(_pure_expr(e, ctx) for e in elts) and all(
            _pure_target(g.target)
            and _pure_expr(g.iter, ctx)
            and all(_pure_expr(i, ctx) for i in g.ifs)
            for g in node.generators
        )
    if isinstance(node, ast.Call):
        return (
            _origin(node.func, ctx) in LEAF_PURE_CALL_ORIGINS
            and all(_pure_expr(a, ctx) for a in node.args)
            and all(_pure_expr(k.value, ctx) for k in node.keywords)
        )
    return False


def _pure_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(_pure_target(e) for e in node.elts)
    return False


def _pure_args(args: ast.arguments, ctx: _LeafCtx | None = None) -> bool:
    """Defaults und Annotationen (letztere werden ohne ``from __future__ import
    annotations`` beim ``def`` ausgewertet) muessen rein sein."""
    every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    return (
        all(_pure_expr(d, ctx) for d in args.defaults)
        and all(_pure_expr(d, ctx) for d in args.kw_defaults)
        and all(_pure_expr(a.annotation, ctx) for a in every if a is not None)
    )


def _pure_decorator(node: ast.AST, ctx: _LeafCtx | None = None) -> bool:
    if isinstance(node, ast.Call):
        return (
            _origin(node.func, ctx) in LEAF_PURE_DECORATORS
            and all(_pure_expr(a, ctx) for a in node.args)
            and all(_pure_expr(k.value, ctx) for k in node.keywords)
        )
    return _origin(node, ctx) in LEAF_PURE_DECORATORS


def _class_head_violations(
    st: ast.ClassDef, ctx: _LeafCtx
) -> tuple[list[tuple[int, str]], bool]:
    """Kopf einer Blatt-Klasse: Basen nur aus ``LEAF_ALLOWED_BASES`` oder bereits
    gepruefte eigene Klassen, Keywords nur ``LEAF_ALLOWED_CLASS_KEYWORDS`` (also
    nie ``metaclass=``), Dekoratoren nur ``LEAF_PURE_DECORATORS``. Liefert
    zusaetzlich, ob die Klasse zur Enum-Familie gehoert."""
    out: list[tuple[int, str]] = []
    is_enum = False
    for b in st.bases:
        origin = ctx.base_origin(b)
        if origin is None or not (origin in LEAF_ALLOWED_BASES or origin.startswith("own:")):
            out.append((st.lineno, f"<Klasse {st.name}: Basis nicht erlaubt: {ast.unparse(b)}>"))
        elif origin.startswith("enum.") or (
            origin.startswith("own:") and ctx.classes[origin[len("own:"):]]
        ):
            is_enum = True
    for k in st.keywords:
        if k.arg not in LEAF_ALLOWED_CLASS_KEYWORDS or not _pure_expr(k.value, ctx):
            out.append(
                (st.lineno, f"<Klasse {st.name}: Klassen-Keyword nicht erlaubt: {k.arg or '**'}>")
            )
    if not all(_pure_decorator(d, ctx) for d in st.decorator_list):
        first = ast.unparse(st).splitlines()[0][:80]
        out.append((st.lineno, f"<Seiteneffekt bei Klasse {st.name}: {first}>"))
    return out, is_enum


def _leaf_body_violations(
    body: list[ast.stmt], where: str, ctx: _LeafCtx, kind: str = "module"
) -> list[tuple[int, str]]:
    """``kind``: ``module`` (Modulebene), ``class`` oder ``enum`` (Klassenkoerper)."""
    out: list[tuple[int, str]] = []
    hook_names = (
        LEAF_ALLOWED_MODULE_HOOK_NAMES if kind == "module" else LEAF_ALLOWED_CLASS_HOOK_NAMES
    )
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
            # Hook-Methoden (``__init_subclass__``, ``__class_getitem__``,
            # ``__set_name__``, Modul-``__getattr__`` ...) laufen implizit; erlaubt
            # sind nur wenige Instanz-Dunder in Nicht-Enum-Klassen.
            if _special(st.name) and (
                kind != "class" or st.name not in LEAF_ALLOWED_DUNDER_METHODS
            ):
                out.append((st.lineno, f"<Hook-Methode {where} nicht erlaubt: {st.name}>"))
                continue
            decos = {
                _origin(d.func if isinstance(d, ast.Call) else d, ctx)
                for d in st.decorator_list
            }
            if kind != "module" and decos & LEAF_PROPERTY_DECORATORS and (
                kind == "enum"
                or decos & LEAF_CACHED_PROPERTY_DECORATORS
                or "builtins.classmethod" in decos
            ):
                out.append(
                    (st.lineno, f"<Property {where} nicht erlaubt (N-842-1): {st.name}>")
                )
                continue
            if (
                all(_pure_decorator(d, ctx) for d in st.decorator_list)
                and _pure_args(st.args, ctx)
                and _pure_expr(st.returns, ctx)
            ):
                continue
        elif isinstance(st, ast.ClassDef):
            head, is_enum = _class_head_violations(st, ctx)
            out.extend(head)
            out.extend(
                _leaf_body_violations(
                    st.body, f"in Klasse {st.name}", ctx, "enum" if is_enum else "class"
                )
            )
            if kind == "module" and not head:
                ctx.classes[st.name] = is_enum
            continue
        elif isinstance(st, (ast.Assign, ast.AnnAssign)):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            hooks = sorted(
                {
                    sub.id
                    for t in targets
                    for sub in ast.walk(t)
                    if isinstance(sub, ast.Name) and _special(sub.id) and sub.id not in hook_names
                }
            )
            if hooks:
                out.append((st.lineno, f"<Hook-Name {where} zugewiesen: {', '.join(hooks)}>"))
                continue
            if isinstance(st, ast.Assign):
                if all(_pure_target(t) for t in st.targets) and _pure_expr(st.value, ctx):
                    continue
            elif (
                isinstance(st.target, ast.Name)
                and _pure_expr(st.value, ctx)
                and _pure_expr(st.annotation, ctx)
            ):
                continue
        elif (
            kind == "module"
            and isinstance(st, ast.If)
            and _dotted(st.test) in ("TYPE_CHECKING", "typing.TYPE_CHECKING")
            and not st.orelse
            and all(isinstance(c, (ast.Import, ast.ImportFrom, ast.Pass)) for c in st.body)
        ):
            continue
        first = ast.unparse(st).splitlines()[0][:80]
        out.append((st.lineno, f"<Seiteneffekt {where}: {first}>"))
    return out


def _is_module_attr(module: str, attr: str) -> bool:
    """``modul.attr`` liefert im laufenden Interpreter ein Modulobjekt
    (``enum.bltns``, ``typing.sys``). Nur fuer Module der Blatt-Positivliste;
    andere Module sind ohnehin rot und werden nicht importiert."""
    if module not in LEAF_ALLOWED_STDLIB:
        return False
    try:
        mod = importlib.import_module(module)
    except ImportError:
        return False
    return isinstance(getattr(mod, attr, None), ModuleType)


def _imported_name_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """N-842-2: Stern-Importe, ``import a.b`` ohne ``as``, Attributketten ueber
    importierte Namen tiefer als eine Stufe, Unterstrich-Attribute darauf,
    Modulobjekte als blosser Wert und Attribute/from-Importe, die ein Modul
    liefern."""
    out: list[tuple[int, str]] = []
    module_of: dict[str, str] = {}  # per ``import`` gebundener Name -> Modul
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname is None and "." in a.name:
                    out.append(
                        (node.lineno, f"<import ohne as bindet Elternpaket: import {a.name}>")
                    )
                bound = a.asname or a.name.split(".", 1)[0]
                module_of[bound] = a.name if a.asname else bound
                imported.add(bound)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                if a.name == "*":
                    out.append((node.lineno, f"<Stern-Import: from {mod} import *>"))
                    continue
                imported.add(a.asname or a.name)
                if not node.level and _is_module_attr(mod, a.name):
                    out.append(
                        (node.lineno, f"<Modulobjekt importiert: from {mod} import {a.name}>")
                    )
    attr_values = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in module_of
            and id(node) not in attr_values
        ):
            out.append((node.lineno, f"<Modulobjekt als Wert: {node.id}>"))
        if not isinstance(node, ast.Attribute):
            continue
        inner = node.value
        if (
            isinstance(inner, ast.Attribute)
            and isinstance(inner.value, ast.Name)
            and inner.value.id in imported
        ):
            out.append(
                (node.lineno, f"<Attributkette ueber importierten Namen: {ast.unparse(node)}>")
            )
        elif isinstance(inner, ast.Name) and inner.id in imported:
            if node.attr.startswith("_"):
                out.append(
                    (
                        node.lineno,
                        f"<Unterstrich-Attribut auf importiertem Namen: {inner.id}.{node.attr}>",
                    )
                )
            elif inner.id in module_of and _is_module_attr(module_of[inner.id], node.attr):
                out.append(
                    (node.lineno, f"<Modulobjekt ueber Attribut: {inner.id}.{node.attr}>")
                )
    return out


def leaf_contract_violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Regel 6, Blattvertrag: Modulebene nur aus der Positivliste; im ganzen
    Modul nur Stdlib-Module der Blatt-Positivliste und keine dynamischen
    Importe oder Codeausfuehrung."""
    out = _leaf_body_violations(tree.body, "auf Modulebene", _LeafCtx.of(tree))
    out.extend(_imported_name_violations(tree))
    # Aliase: importierte Module (fuer Attribut-Zuweisungen), sys-Aliase und
    # Namen, die aus verbotenen Modulen/Attributen importiert wurden.
    module_aliases: set[str] = set()
    imported_names: set[str] = set()
    sys_aliases: set[str] = {"sys"}
    forbidden_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                bound = a.asname or a.name.split(".", 1)[0]
                module_aliases.add(bound)
                imported_names.add(bound)
                if a.name == "sys":
                    sys_aliases.add(bound)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".", 1)[0]
            for a in node.names:
                bound = a.asname or a.name
                imported_names.add(bound)
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
        elif isinstance(node, ast.Attribute) and (
            node.attr in LEAF_FORBIDDEN_ATTRS
            or (_special(node.attr) and node.attr not in LEAF_ALLOWED_DUNDER_ATTRS)
        ):
            out.append((node.lineno, f"<dynamisch: .{node.attr}>"))
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and _special(node.slice.value)
        ):
            out.append((node.lineno, f"<dynamisch: [{node.slice.value!r}]>"))
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
                if a.name not in LEAF_ALLOWED_STDLIB:
                    out.append((node.lineno, f"<{_NOT_ALLOWED_STDLIB}: import {a.name}>"))
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".", 1)[0]
            if top in LEAF_FORBIDDEN_MODULES or any(
                a.name in LEAF_FORBIDDEN_NAMES | LEAF_FORBIDDEN_ATTRS for a in node.names
            ):
                out.append((node.lineno, f"<dynamisch: from {node.module} import ...>"))
            if node.level or node.module not in LEAF_ALLOWED_STDLIB:
                mod = "." * node.level + (node.module or "")
                out.append((node.lineno, f"<{_NOT_ALLOWED_STDLIB}: from {mod} import ...>"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _LEAF_ATTR_FUNCS
        ):
            obj = node.args[0] if node.args else None
            name = node.args[1] if len(node.args) > 1 else None
            if (
                not (isinstance(name, ast.Constant) and isinstance(name.value, str))
                or name.value in LEAF_FORBIDDEN_ATTRS | LEAF_FORBIDDEN_NAMES
                or _special(name.value)
                or any(isinstance(a, ast.Starred) for a in node.args)
            ):
                out.append((node.lineno, f"<dynamisch: {node.func.id}(...)>"))
            elif (
                node.func.id != "getattr"
                and isinstance(obj, ast.Name)
                and obj.id in imported_names
            ):
                out.append(
                    (node.lineno, f"<Modul-Attribut veraendert: {node.func.id}({obj.id}, ...)>")
                )
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


def leaf_content_sha256(path: Path) -> str:
    """SHA-256 des Dateiinhalts fuer den Inhalts-Pin. CRLF wird zu LF
    normalisiert (``.gitattributes``: ``eol=lf``), damit ein Windows-Checkout
    mit CRLF und die Linux-CI denselben Wert liefern."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def leaf_resolution_problems(root: Path, module: str) -> list[str]:
    """N-844-1: Fuer das Blatt und jedes Elternpaket muss genau die erwartete
    Datei existieren, kein weiterer ladbarer Eintrag gleichen Namens daneben
    liegen und ``PathFinder.find_spec`` (Aufloesung ohne Import) genau diese
    Datei liefern."""
    out: list[str] = []
    parts = module.split(".")
    for i in range(1, len(parts) + 1):
        name = ".".join(parts[:i])
        tail = parts[i - 1]
        parent_dir = root.joinpath(*parts[: i - 1])
        is_leaf = i == len(parts)
        expected = parent_dir / f"{tail}.py" if is_leaf else parent_dir / tail / "__init__.py"
        allowed_entry = f"{tail}.py" if is_leaf else tail

        def rel(p: Path) -> str:
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                return str(p)

        if not expected.is_file():
            out.append(f"{name}: erwartete Datei fehlt: {rel(expected)}")
        if parent_dir.is_dir():
            key = tail.casefold()
            for entry in sorted(parent_dir.iterdir()):
                n = entry.name
                low = n.casefold()
                same_name = low == key or (
                    low.startswith(key + ".") and low.endswith(LEAF_LOADABLE_SUFFIXES)
                )
                if same_name and n != allowed_entry:
                    out.append(f"{name}: weiterer Eintrag mit gleichem Modulnamen: {rel(entry)}")
                elif n == allowed_entry and not is_leaf and not entry.is_dir():
                    out.append(f"{name}: kein Paketverzeichnis: {rel(entry)}")
        pkg_dir = parent_dir / tail
        if not is_leaf and pkg_dir.is_dir():
            # N-844-4: ``find_spec`` kennt nur die Endungen des laufenden Interpreters
            # (Linux-CI sieht ``__init__.pyd`` nicht, Windows laedt es vor ``__init__.py``).
            # Darum jede ladbare ``__init__.*`` ausser ``__init__.py`` plattformunabhaengig rot.
            for entry in sorted(pkg_dir.iterdir()):
                low = entry.name.casefold()
                if (
                    low.startswith("__init__.")
                    and low.endswith(LEAF_LOADABLE_SUFFIXES)
                    and entry.name != "__init__.py"
                ):
                    out.append(f"{name}: weitere Paket-Init-Datei: {rel(entry)}")
        importlib.machinery.PathFinder.invalidate_caches()
        try:
            spec = importlib.machinery.PathFinder.find_spec(name, [str(parent_dir)])
        except (ImportError, ValueError):
            spec = None
        origin = spec.origin if spec is not None else None
        if not origin or not Path(origin).is_file() or Path(origin).resolve() != expected.resolve():
            out.append(
                f"{name}: Python wuerde {rel(Path(origin)) if origin else '<Namespace/nichts>'} "
                f"laden statt {rel(expected)}"
            )
    return out


def _pinned_modules() -> list[str]:
    """Gelistete Blaetter plus deren Elternpakete (sofern ``__init__.py`` existiert)."""
    return sorted(FAN_OUT_EXEMPT_LEAVES | _leaf_parent_packages())


def scan_backend(root: Path | None = None) -> dict[str, ModuleScan]:
    root = root or BACKEND_ROOT
    mods, collisions = _discover(root)
    resolve = _resolver(mods)
    scans: dict[str, ModuleScan] = {}
    for name, path in mods.items():
        src = path.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(src, filename=str(path))
        scan = ModuleScan(path=path.relative_to(root).as_posix())
        _Visitor(name, path.name == "__init__.py", resolve, scan).visit(tree)
        if name in FAN_OUT_EXEMPT_LEAVES or name in _leaf_parent_packages():
            scan.leaf_violations = leaf_contract_violations(tree)
            scan.content_sha256 = leaf_content_sha256(path)
        if name in FAN_OUT_EXEMPT_LEAVES:
            scan.resolution_problems = leaf_resolution_problems(root, name)
        if name in collisions:
            scan.collisions = [p.relative_to(root).as_posix() for p in collisions[name]]
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
        LEAF_PIN_KEY: {
            m: scans[m].content_sha256
            for m in _pinned_modules()
            if m in scans and scans[m].content_sha256 is not None
        },
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
        if s.resolution_problems:
            res.regressions.append(
                f"[fan_out_exempt_leaves] {m}: Modulaufloesung weicht ab (Schatten-Datei, "
                f"fehlendes Elternpaket oder anderer origin): "
                + "; ".join(s.resolution_problems)
            )
        if bad:
            detail = "; ".join(f"{s.path}:{ln} -> {t}" for ln, t in bad)
            res.regressions.append(
                f"[fan_out_exempt_leaves] {m}: kein reines Stdlib-Blatt "
                f"(nur Standardbibliothek, Fan-out 0, keine Modul-Seiteneffekte, "
                f"keine dynamischen Importe): {detail}"
            )

    # 6a. Namenskollisionen (N-844-1): zwei Dateien fuer denselben Modulnamen
    for m, s in sorted(scans.items()):
        if s.collisions:
            res.regressions.append(
                f"[module_collisions] {m}: mehrere Dateien fuer denselben Modulnamen "
                f"(gescannt wird nur eine, Python laedt ggf. die andere): "
                + ", ".join(s.collisions)
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

    # 6c. Inhalts-Pin der Blaetter und ihrer Elternpakete
    base_pins = baseline.get(LEAF_PIN_KEY, {})
    cur_pins = current.get(LEAF_PIN_KEY, {})
    for m in _pinned_modules():
        if m not in scans:
            continue  # fehlendes Blatt meldet Regel 6, fehlendes __init__ = Namespace
        pinned, actual = base_pins.get(m), cur_pins.get(m)
        if pinned is None:
            res.regressions.append(
                f"[{LEAF_PIN_KEY}] {m} ({scans[m].path}): kein Inhalts-Pin in der Basis -- "
                f"ein neues Blatt braucht einen bewusst gesetzten Pin: Inhalt im Review "
                f"pruefen, dann {LEAF_PIN_UPDATE_CMD} und die Basis mitcommitten"
            )
        elif pinned != actual:
            res.regressions.append(
                f"[{LEAF_PIN_KEY}] {m} ({scans[m].path}): Inhalt weicht vom Pin ab "
                f"(Basis {pinned[:12]}..., aktuell {(actual or '-')[:12]}...) -- "
                f"Blatt-Diff im Review pruefen, dann bewusst {LEAF_PIN_UPDATE_CMD} "
                f"und die Basis mitcommitten"
            )
    for m in sorted(set(base_pins) - set(cur_pins)):
        res.regressions.append(
            f"[{LEAF_PIN_KEY}] {m}: gepinnt, aber keine Datei mehr bzw. nicht mehr gelistet "
            f"(N-844-2) -- Pins sind exakt; ein Pin wird nur bewusst entfernt: "
            f"{LEAF_PIN_UPDATE_CMD}"
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
    parser.add_argument(
        "--update-leaf-pins",
        action="store_true",
        help="Inhalts-Pins der Blattmodule bewusst nachfuehren (nur nach Review des Blatt-Diffs)",
    )
    args = parser.parse_args(argv)

    scans = scan_backend()
    current = measure(scans)
    print(f"Architektur-Ratschen: {summary(current)}")
    if not BASELINE_FILE.is_file():
        print(f"Basisdatei fehlt: {BASELINE_FILE}", file=sys.stderr)
        return 1
    baseline = load_baseline()
    res = compare(current, baseline, scans)
    pin_prefix = f"[{LEAF_PIN_KEY}]"
    if args.update_leaf_pins:
        other = [r for r in res.regressions if not r.startswith(pin_prefix)]
        for line in other:
            print(f"VERSCHLECHTERT {line}", file=sys.stderr)
        if other:
            print(
                "Inhalts-Pins nicht nachgefuehrt: zuerst die uebrigen Verletzungen beheben.",
                file=sys.stderr,
            )
            return 1
        old = baseline.get(LEAF_PIN_KEY, {})
        baseline[LEAF_PIN_KEY] = current[LEAF_PIN_KEY]
        BASELINE_FILE.write_text(dump_baseline(baseline), encoding="utf-8", newline="\n")
        for m, sha in current[LEAF_PIN_KEY].items():
            if old.get(m) != sha:
                print(f"PIN NACHGEFUEHRT {m}: {old.get(m, '-')} -> {sha}")
        print(f"Inhalts-Pins aktualisiert: {BASELINE_FILE.name} (Blatt-Diff und Basis gemeinsam reviewen)")
        return 0
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
        if any(r.startswith(pin_prefix) for r in res.regressions):
            print(
                f"Blatt-Inhalt geaendert: nach Review des Diffs bewusst {LEAF_PIN_UPDATE_CMD}",
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
