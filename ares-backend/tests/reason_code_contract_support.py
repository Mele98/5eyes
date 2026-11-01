"""Statische Extraktion der Reason-Codes (K-2, A2 M5/M17).

Nur Standardbibliothek, keine Datenbank, kein App-Start. Wird von
``test_reason_code_catalog_contract.py`` benutzt und ist zugleich das
Werkzeug, mit dem ``core/reason_codes.py`` aus den bestehenden Literalen
erzeugt wurde (Werte 1:1).

Backend (Produzenten): ein Reason-Code ist jeder statisch aufloesbare String,
der an einer dieser Stellen steht:

* Keyword ``reason_code=<expr>`` in einem Aufruf,
* Dict-Literal ``{"reason_code": <expr>}``,
* Zuweisung an ``reason_code`` / ``<obj>.reason_code`` / ``x["reason_code"]``,
* positionales Argument an der Stelle des Parameters ``reason_code`` einer im
  Backend definierten Funktion oder Klasse (``__init__``/Dataclass-Feld), z. B.
  ``OnsiteSignatureError(TRANSACTION_NOT_FOUND, ...)``.

``<expr>`` wird aufgeloest ueber Literale, ``a if c else b``, ``a or b``,
f-Strings, ``str(x)``, Modul- und Klassenkonstanten (auch importierte), lokale
Zuweisungen inkl. Tupel-Entpackung, Rueckgabewerte von Backend-Funktionen,
Attribute gefangener Exceptions bzw. ``self.<attr>`` (-> Konstruktor-Argumente
an allen Aufrufstellen der Klasse) und ``ReasonCode.X``. Nicht aufloesbare
Ausdruecke werden mit Datei:Zeile gemeldet (Durchreichungen wie
``exc.reason_code`` einer fremden Exception, Parameter).

Backend (Auswerter, inkl. PDF): Vergleiche ``<...reason_code...> == "X"`` bzw.
``in {"X", ...}``.

Frontend: Monolith ``ares.html`` (inkl. Begleit-JS) und Reporting
``reporting/src`` (ohne Tests): Vergleiche mit ``reason_code`` bzw.
``reasonCode``, Lookup-Maps ``MAP[<x>.reason_code]`` (Schluessel der Map),
``switch(<x>.reason_code)``-Faelle und JS-Konstanten, die mit ``reason_code``
verglichen werden.
"""
from __future__ import annotations

import ast
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "ares-desktop" / "frontend"
MONOLITH = FRONTEND_ROOT / "ares.html"
REPORTING_SRC = FRONTEND_ROOT / "reporting" / "src"

EXCLUDED_TOP = {"tests", "alembic", "scripts", "migrations", "venv", ".venv", "node_modules"}
# Dateien, deren Reason-Code-Auswertung Teil der PDF-Erzeugung ist.
PDF_PREFIXES = ("services/pdf", "routers/pdf_reports.py", "services/advisory_report.py")
# Reine Schema-Beschreibungen (Spaltenname -> DDL-Typ), keine Codes.
SCHEMA_ONLY_MODULES = frozenset({"core/product_eligibility_override_schema.py"})

_REASON_NAME = "reason_code"
_MAX_DEPTH = 14


@dataclass(frozen=True)
class Site:
    value: str
    path: str
    line: int


@dataclass
class Extraction:
    produced: list[Site] = field(default_factory=list)
    consumed: list[Site] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    # Je nicht aufloesbarer Stelle (Datei, Funktion, Ausdruck); eine Zeile = ein
    # Eintrag, damit gleiche Ausdruecke in derselben Funktion mitgezaehlt werden.
    unresolved_keys: list[tuple[str, str, str]] = field(default_factory=list)

    def produced_codes(self) -> set[str]:
        return {s.value for s in self.produced}

    def consumed_codes(self, *, pdf_only: bool = False) -> set[str]:
        return {
            s.value for s in self.consumed
            if not pdf_only or s.path.startswith(PDF_PREFIXES)
        }


# --------------------------------------------------------------------------
# Backend: Modulindex
# --------------------------------------------------------------------------


def _iter_backend_files(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] in EXCLUDED_TOP or "__pycache__" in rel.parts:
            continue
        out.append(path)
    return out


def _module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_from(module: str, is_pkg: bool, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    base = module.split(".")
    if not is_pkg:
        base = base[:-1]
    if node.level > 1:
        base = base[: len(base) - (node.level - 1)]
    if node.module:
        base = base + node.module.split(".")
    return ".".join(base)


@dataclass
class _Module:
    name: str
    rel: str
    tree: ast.Module
    consts: dict[str, ast.expr] = field(default_factory=dict)
    class_consts: dict[str, ast.expr] = field(default_factory=dict)  # "Cls.NAME"
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    name_imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    module_aliases: dict[str, str] = field(default_factory=dict)


def _load_modules(root: Path) -> dict[str, _Module]:
    mods: dict[str, _Module] = {}
    for path in _iter_backend_files(root):
        rel = path.relative_to(root)
        rel_posix = rel.as_posix()
        if rel_posix in SCHEMA_ONLY_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        mod = _Module(name=_module_name(rel), rel=rel_posix, tree=tree)
        is_pkg = rel.name == "__init__.py"
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        mod.consts[t.id] = node.value
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mod.functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                mod.classes[node.name] = node
                for sub in node.body:
                    if isinstance(sub, (ast.Assign, ast.AnnAssign)) and sub.value is not None:
                        targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                        for t in targets:
                            if isinstance(t, ast.Name):
                                mod.class_consts[f"{node.name}.{t.id}"] = sub.value
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                src = _resolve_from(mod.name, is_pkg, node)
                for a in node.names:
                    mod.name_imports[a.asname or a.name] = (src, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        mod.module_aliases[a.asname] = a.name
                    else:
                        top = a.name.split(".")[0]
                        mod.module_aliases[top] = top
        mods[mod.name] = mod
    _inherit_constructors(mods)
    return mods


def _base_names(cls: ast.ClassDef) -> list[str]:
    return [b.id if isinstance(b, ast.Name) else b.attr
            for b in cls.bases if isinstance(b, (ast.Name, ast.Attribute))]


def _own_init(cls: ast.ClassDef) -> ast.FunctionDef | None:
    return next((sub for sub in cls.body if isinstance(sub, ast.FunctionDef) and sub.name == "__init__"), None)


def _init_of(cls: ast.ClassDef) -> ast.FunctionDef | None:
    """Eigenes oder (per ``_inherit_constructors``) geerbtes ``__init__``."""
    return _own_init(cls) or getattr(cls, "_k2_inherited_init", None)


def _is_dataclass(cls: ast.ClassDef) -> bool:
    for d in cls.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        if name == "dataclass":
            return True
    return False


def _dataclass_fields(cls: ast.ClassDef) -> list[str]:
    return [
        sub.target.id for sub in cls.body
        if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name)
        and "ClassVar" not in ast.unparse(sub.annotation)
    ]


def _inherit_constructors(mods: dict[str, _Module]) -> None:
    """Klassen ohne eigenen Konstruktor erben ``__init__`` der (namensgleich
    gefundenen) Basisklasse -- z. B. ``OnsiteSignatureError(DomainError)``.
    Nur als Attribut am AST-Knoten vermerkt (nicht in den Body gehaengt), damit
    der geerbte Rumpf nicht der Unterklassen-Datei zugeschrieben wird."""
    index = {name: c for m in mods.values() for name, c in m.classes.items()}
    changed = True
    while changed:
        changed = False
        for cls in index.values():
            if _init_of(cls) is not None or _is_dataclass(cls):
                continue
            for base in _base_names(cls):
                bcls = index.get(base)
                if bcls is None or bcls is cls:
                    continue
                init = _init_of(bcls)
                if init is not None:
                    cls._k2_inherited_init = init  # type: ignore[attr-defined]
                    changed = True
                    break


def _positional_params(fn: ast.FunctionDef | ast.AsyncFunctionDef, *, skip_self: bool) -> list[str]:
    args = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    return args[1:] if skip_self and args else args


def _class_params(cls: ast.ClassDef) -> list[str] | None:
    """Positionale Konstruktor-Parameter (``__init__`` oder Dataclass-Felder)."""
    init = _init_of(cls)
    if init is not None:
        return _positional_params(init, skip_self=True)
    if _is_dataclass(cls):
        return _dataclass_fields(cls) or None
    return None


def _class_attr_param(cls: ast.ClassDef, attr: str) -> str | None:
    """Welcher Konstruktor-Parameter landet in ``self.<attr>``?"""
    init = _init_of(cls)
    if init is None:
        return attr if _is_dataclass(cls) and attr in _dataclass_fields(cls) else None
    for node in ast.walk(init):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and t.attr == attr
                        and isinstance(t.value, ast.Name) and t.value.id == "self"
                        and isinstance(node.value, ast.Name)
                        and node.value.id in _all_params(init)):
                    return node.value.id
    return None


# Lokale Bindungen: ("expr", e) | ("unpack", e, idx) | ("exc", (Klassennamen,))
_Binding = tuple


def _local_bindings(fn: ast.AST) -> dict[str, list[_Binding]]:
    out: dict[str, list[_Binding]] = {}
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(("expr", node.value))
                elif isinstance(t, ast.Tuple):
                    for i, el in enumerate(t.elts):
                        if isinstance(el, ast.Name):
                            out.setdefault(el.id, []).append(("unpack", node.value, i))
        elif isinstance(node, ast.ExceptHandler) and node.name and node.type is not None:
            types = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            names = tuple(
                t.id if isinstance(t, ast.Name) else t.attr
                for t in types if isinstance(t, (ast.Name, ast.Attribute))
            )
            out.setdefault(node.name, []).append(("exc", names))
    return out


@dataclass(frozen=True)
class _Ctx:
    mod: _Module
    local: dict
    cls: str | None = None
    fn: ast.FunctionDef | ast.AsyncFunctionDef | None = None


class _Resolver:
    def __init__(self, mods: dict[str, _Module]):
        self.mods = mods
        self.class_index: dict[str, list[tuple[_Module, ast.ClassDef]]] = {}
        for m in mods.values():
            for name, c in m.classes.items():
                self.class_index.setdefault(name, []).append((m, c))
        self._call_sites: dict[str, list[tuple[ast.Call, _Ctx]]] | None = None
        self.subclasses: dict[str, set[str]] = {}
        for m in mods.values():
            for name, c in m.classes.items():
                for b in _base_names(c):
                    self.subclasses.setdefault(b, set()).add(name)
        self._active: set = set()
        self._fn_mod: dict[int, _Module] | None = None

    def class_family(self, name: str) -> list[str]:
        """Klasse plus alle (transitiven) Unterklassen, deterministisch."""
        out, todo = [], [name]
        while todo:
            n = todo.pop()
            if n in out:
                continue
            out.append(n)
            todo.extend(sorted(self.subclasses.get(n, ())))
        return out

    # ---- Aufrufstellen je Funktions-/Klassenname (lazy, einmal) ----
    def call_sites(self, name: str) -> list[tuple[ast.Call, _Ctx]]:
        if self._call_sites is None:
            sites: dict[str, list[tuple[ast.Call, _Ctx]]] = {}
            for m in self.mods.values():
                for node, ctx in _walk_with_ctx(m):
                    if isinstance(node, ast.Call):
                        fn = node.func
                        key = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                        if key:
                            sites.setdefault(key, []).append((node, ctx))
            self._call_sites = sites
        return self._call_sites.get(name, [])

    def param_values(self, fdef: ast.FunctionDef | ast.AsyncFunctionDef, param: str,
                     path: tuple, depth: int, call_name: str | None = None) -> tuple[list[str], bool]:
        """Parameter -> Default + Argumente an allen Aufrufstellen der Funktion
        (namensbasiert, gleichnamige Funktionen werden vereinigt)."""
        key = ("param", id(fdef), param, path)
        if key in self._active or depth > _MAX_DEPTH:
            return [], True
        self._active.add(key)
        try:
            skip = bool(fdef.args.args) and fdef.args.args[0].arg in {"self", "cls"}
            params = _positional_params(fdef, skip_self=skip)
            idx = params.index(param) if param in params else None
            default = None
            all_pos = [a.arg for a in (*fdef.args.posonlyargs, *fdef.args.args)]
            if param in all_pos:
                k = all_pos.index(param) - (len(all_pos) - len(fdef.args.defaults))
                default = fdef.args.defaults[k] if k >= 0 else None
            for a, d in zip(fdef.args.kwonlyargs, fdef.args.kw_defaults):
                if a.arg == param:
                    default = d
            vals: list[str] = []
            ok = True
            if default is not None:
                r, o = self.resolve(default, _Ctx(self._mod_of(fdef), {}), path, depth + 1)
                vals += r
                ok = ok and o
            home = self._mod_of(fdef)
            names = self.class_family(call_name) if call_name else [fdef.name]
            for call, ctx in [cs for n in names for cs in self.call_sites(n)]:
                if call_name is None and not self._targets(call, ctx, home):
                    continue
                arg = next((kw.value for kw in call.keywords if kw.arg == param), None)
                if arg is None and idx is not None and len(call.args) > idx \
                        and not any(isinstance(a, ast.Starred) for a in call.args[: idx + 1]):
                    arg = call.args[idx]
                if arg is None:
                    continue
                r, o = self.resolve(arg, ctx, path, depth + 1)
                vals += r
                ok = ok and o
            return vals, ok
        finally:
            self._active.discard(key)

    def _targets(self, call: ast.Call, ctx: _Ctx, home: _Module) -> bool:
        """Zeigt der Aufruf (moeglicherweise) auf eine Funktion aus ``home``?"""
        fn = call.func
        if isinstance(fn, ast.Name):
            if fn.id in ctx.mod.functions or fn.id in ctx.mod.classes:
                return ctx.mod is home
            if fn.id in ctx.mod.name_imports:
                return ctx.mod.name_imports[fn.id][0] == home.name
            return ctx.mod is home
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            alias = fn.value.id
            if alias in ctx.mod.module_aliases:
                return ctx.mod.module_aliases[alias] == home.name
            if alias in ctx.mod.name_imports:
                src, orig = ctx.mod.name_imports[alias]
                if f"{src}.{orig}" in self.mods:
                    return f"{src}.{orig}" == home.name
        return True  # Methodenaufruf: namensbasiert

    def _mod_of(self, node: ast.AST) -> _Module:
        if self._fn_mod is None:
            self._fn_mod = {}
            for m in self.mods.values():
                for n in ast.walk(m.tree):
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._fn_mod[id(n)] = m
        return self._fn_mod[id(node)]

    def ctor_values(self, cls_name: str, attr: str, depth: int) -> tuple[list[str], bool]:
        key = ("ctor", cls_name, attr)
        if key in self._active or depth > _MAX_DEPTH:
            return [], True
        self._active.add(key)
        try:
            vals: list[str] = []
            ok = True
            found = False
            for _m, cls in self.class_index.get(cls_name, []):
                param = _class_attr_param(cls, attr)
                if param is None:
                    continue
                found = True
                params = _class_params(cls) or []
                idx = params.index(param) if param in params else None
                for call, ctx in [cs for n in self.class_family(cls_name) for cs in self.call_sites(n)]:
                    arg = next((kw.value for kw in call.keywords if kw.arg == param), None)
                    if arg is None and idx is not None and len(call.args) > idx \
                            and not any(isinstance(a, ast.Starred) for a in call.args[: idx + 1]):
                        arg = call.args[idx]
                    if arg is None:
                        continue
                    r, o = self.resolve(arg, ctx, (), depth + 1)
                    vals += r
                    ok = ok and o
            return vals, found and ok
        finally:
            self._active.discard(key)

    def call_returns(self, call: ast.Call, ctx: _Ctx, path: tuple, depth: int) -> tuple[list[str], bool]:
        fn = call.func
        target: tuple[_Module, ast.FunctionDef] | None = None
        if isinstance(fn, ast.Name):
            if fn.id == "str" and len(call.args) == 1:
                return self.resolve(call.args[0], ctx, path, depth + 1)
            if fn.id in ctx.mod.functions:
                target = (ctx.mod, ctx.mod.functions[fn.id])
            elif fn.id in ctx.mod.name_imports:
                src, orig = ctx.mod.name_imports[fn.id]
                if src in self.mods and orig in self.mods[src].functions:
                    target = (self.mods[src], self.mods[src].functions[orig])
        elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            alias = fn.value.id
            mname = ctx.mod.module_aliases.get(alias)
            if mname is None and alias in ctx.mod.name_imports:
                src, orig = ctx.mod.name_imports[alias]
                mname = f"{src}.{orig}"
            if mname in self.mods and fn.attr in self.mods[mname].functions:
                target = (self.mods[mname], self.mods[mname].functions[fn.attr])
        if target is None:
            return [], False
        mod, fdef = target
        key = ("ret", mod.name, fdef.name, path)
        if key in self._active or depth > _MAX_DEPTH:
            return [], True
        self._active.add(key)
        try:
            fctx = _Ctx(mod, _local_bindings(fdef), None, fdef)
            vals: list[str] = []
            ok = True
            any_ret = False
            for node in ast.walk(fdef):
                if isinstance(node, ast.Return) and node.value is not None:
                    any_ret = True
                    r, o = self.resolve(node.value, fctx, path, depth + 1)
                    vals += r
                    ok = ok and o
            return vals, any_ret and ok
        finally:
            self._active.discard(key)

    def resolve(self, expr: ast.expr | None, ctx: _Ctx, path: tuple = (),
                depth: int = 0) -> tuple[list[str], bool]:
        """-> (Werte, vollstaendig_aufgeloest). ``path`` = noch anzuwendende
        Indizes (Tupel-Entpackung/Subscript)."""
        if expr is None or depth > _MAX_DEPTH:
            return [], expr is None
        if isinstance(expr, ast.Constant):
            if path:
                return [], False
            if isinstance(expr.value, str):
                return [expr.value], True
            return [], expr.value is None
        if isinstance(expr, ast.IfExp):
            a, ok_a = self.resolve(expr.body, ctx, path, depth + 1)
            b, ok_b = self.resolve(expr.orelse, ctx, path, depth + 1)
            return a + b, ok_a and ok_b
        if isinstance(expr, ast.BoolOp):
            vals, ok = [], True
            for v in expr.values:
                r, o = self.resolve(v, ctx, path, depth + 1)
                vals += r
                ok = ok and o
            return vals, ok
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            if not path:
                return [], False
            head, rest = path[0], path[1:]
            if isinstance(expr, ast.Tuple) and isinstance(head, int):
                if -len(expr.elts) <= head < len(expr.elts):
                    return self.resolve(expr.elts[head], ctx, rest, depth + 1)
                return [], False
            vals, ok = [], True
            for el in expr.elts:  # Listen-Element: jedes moegliche
                r, o = self.resolve(el, ctx, rest, depth + 1)
                vals += r
                ok = ok and o
            return vals, ok
        if isinstance(expr, ast.Subscript):
            s = expr.slice
            if isinstance(s, ast.Constant) and isinstance(s.value, int):
                return self.resolve(expr.value, ctx, (s.value, *path), depth + 1)
            return [], False
        if isinstance(expr, ast.JoinedStr):
            if path:
                return [], False
            parts: list[list[str]] = []
            ok = True
            for v in expr.values:
                if isinstance(v, ast.Constant):
                    parts.append([str(v.value)])
                elif isinstance(v, ast.FormattedValue):
                    r, o = self.resolve(v.value, ctx, (), depth + 1)
                    ok = ok and o and bool(r)
                    parts.append(sorted(set(r)) or [""])
            if not ok:
                return [], False
            return ["".join(p) for p in itertools.product(*parts)], True
        if isinstance(expr, ast.Call):
            return self.call_returns(expr, ctx, path, depth)
        if isinstance(expr, ast.Name):
            if expr.id in ctx.local:
                vals, ok = [], True
                for b in ctx.local[expr.id]:
                    # Ohne die eigene Bindung weiter (``x = x or "A"`` terminiert).
                    inner = _Ctx(ctx.mod, {k: v for k, v in ctx.local.items() if k != expr.id}, ctx.cls)
                    if b[0] == "expr":
                        r, o = self.resolve(b[1], inner, path, depth + 1)
                    elif b[0] == "unpack":
                        r, o = self.resolve(b[1], inner, (b[2], *path), depth + 1)
                    else:
                        r, o = [], False
                    vals += r
                    ok = ok and o
                return vals, ok
            if ctx.fn is not None and expr.id in _all_params(ctx.fn):
                if ctx.fn.name == "__init__":
                    if not ctx.cls:
                        return [], False
                    # Konstruktor-Parameter -> Argumente an den Aufrufstellen der Klasse
                    return self.param_values(ctx.fn, expr.id, path, depth + 1, call_name=ctx.cls)
                return self.param_values(ctx.fn, expr.id, path, depth + 1)
            return self._resolve_global(ctx.mod, expr.id, path, depth)
        if isinstance(expr, ast.Attribute):
            return self._resolve_attribute(expr, ctx, path, depth)
        return [], False

    def _resolve_attribute(self, expr: ast.Attribute, ctx: _Ctx, path: tuple, depth: int):
        node = expr
        if node.attr == "value" and isinstance(node.value, ast.Attribute):
            node = node.value
        if not isinstance(node.value, ast.Name):
            return [], False
        owner, attr = node.value.id, node.attr
        # gefangene Exception: exc.<attr> -> Konstruktor-Argumente
        if owner in ctx.local:
            exc_classes = [n for b in ctx.local[owner] if b[0] == "exc" for n in b[1]]
            if exc_classes:
                vals, ok = [], True
                for cname in exc_classes:
                    r, o = self.ctor_values(cname, attr, depth + 1)
                    vals += r
                    ok = ok and o
                return vals, ok
        if owner in {"self", "cls"} and ctx.cls:
            key = f"{ctx.cls}.{attr}"
            if key in ctx.mod.class_consts:
                return self.resolve(ctx.mod.class_consts[key], ctx, path, depth + 1)
            return self.ctor_values(ctx.cls, attr, depth + 1)
        if owner in ctx.mod.module_aliases or owner in ctx.mod.name_imports:
            target = ctx.mod.module_aliases.get(owner)
            if target is None:
                src, name = ctx.mod.name_imports[owner]
                if f"{src}.{name}" in self.mods:
                    target = f"{src}.{name}"
                elif src in self.mods and f"{name}.{attr}" in self.mods[src].class_consts:
                    m = self.mods[src]
                    return self.resolve(m.class_consts[f"{name}.{attr}"], _Ctx(m, {}), path, depth + 1)
            if target in self.mods:
                return self._resolve_global(self.mods[target], attr, path, depth)
        key = f"{owner}.{attr}"
        if key in ctx.mod.class_consts:
            return self.resolve(ctx.mod.class_consts[key], _Ctx(ctx.mod, {}), path, depth + 1)
        return [], False

    def _resolve_global(self, mod: _Module, name: str, path: tuple, depth: int):
        if name in mod.consts:
            return self.resolve(mod.consts[name], _Ctx(mod, {}), path, depth + 1)
        if name in mod.name_imports:
            src, orig = mod.name_imports[name]
            if src in self.mods and depth <= _MAX_DEPTH:
                return self._resolve_global(self.mods[src], orig, path, depth + 1)
        return [], False


def _all_params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    a = fn.args
    return {x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)}


def _walk_with_ctx(mod: _Module):
    """Alle Knoten mit lokalem Kontext (innerste Funktion, umschliessende Klasse)."""
    def visit(node: ast.AST, ctx: _Ctx):
        if isinstance(node, ast.ClassDef):
            ctx = _Ctx(ctx.mod, ctx.local, node.name, None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ctx = _Ctx(ctx.mod, _local_bindings(node), ctx.cls, node)
        elif isinstance(node, ast.Lambda):
            ctx = _Ctx(ctx.mod, _local_bindings(node), ctx.cls, None)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local = dict(ctx.local)
            local[node.name] = [b for b in _local_bindings(node).get(node.name, []) if b[0] == "exc"][:1]
            ctx = _Ctx(ctx.mod, local, ctx.cls, ctx.fn)
        yield node, ctx
        for child in ast.iter_child_nodes(node):
            yield from visit(child, ctx)
    yield from visit(mod.tree, _Ctx(mod, {}))


def _reason_param_positions(mods: dict[str, _Module]) -> dict[str, int]:
    """Funktions-/Klassenname -> Position des Parameters ``reason_code``
    (ohne self/cls). Mehrdeutige Namen werden verworfen."""
    found: dict[str, set[int]] = {}
    for mod in mods.values():
        for node in ast.walk(mod.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "__init__":
                skip = bool(node.args.args) and node.args.args[0].arg in {"self", "cls"}
                params = _positional_params(node, skip_self=skip)
                if _REASON_NAME in params:
                    found.setdefault(node.name, set()).add(params.index(_REASON_NAME))
            elif isinstance(node, ast.ClassDef):
                params = _class_params(node) or []
                if _REASON_NAME in params:
                    found.setdefault(node.name, set()).add(params.index(_REASON_NAME))
    return {k: next(iter(v)) for k, v in found.items() if len(v) == 1}


def _is_reason_ref(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == _REASON_NAME
    if isinstance(node, ast.Attribute):
        return node.attr == _REASON_NAME
    if isinstance(node, ast.Subscript):
        s = node.slice
        return isinstance(s, ast.Constant) and s.value == _REASON_NAME
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == _REASON_NAME
    return False


def extract_backend(root: Path = BACKEND_ROOT) -> Extraction:
    mods = _load_modules(root)
    positions = _reason_param_positions(mods)
    res = _Resolver(mods)
    ex = Extraction()
    seen_unresolved: set[str] = set()

    def record(expr: ast.expr, ctx: _Ctx, line: int) -> None:
        vals, ok = res.resolve(expr, ctx)
        for v in vals:
            if v:  # leerer String = "kein Code"
                ex.produced.append(Site(v, ctx.mod.rel, line))
        if not ok:
            text = ast.unparse(expr)[:90]
            entry = f"{ctx.mod.rel}:{line}: {text}"
            if entry not in seen_unresolved:
                seen_unresolved.add(entry)
                ex.unresolved.append(entry)
                func = ".".join(
                    x for x in (ctx.cls, ctx.fn.name if ctx.fn is not None else None) if x
                ) or "<module>"
                ex.unresolved_keys.append((ctx.mod.rel, func, text))

    for mod in mods.values():
        for node, ctx in _walk_with_ctx(mod):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == _REASON_NAME:
                        record(kw.value, ctx, node.lineno)
                fn = node.func
                fname = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if fname in positions and len(node.args) > positions[fname]:
                    idx = positions[fname]
                    if not any(isinstance(a, ast.Starred) for a in node.args[: idx + 1]):
                        record(node.args[idx], ctx, node.lineno)
            elif isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == _REASON_NAME:
                        record(v, ctx, node.lineno)
            if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                    and node.target.id == _REASON_NAME):
                # API-Feld ``reason_code: Literal["A", "B"]`` (vom Client gewaehlt,
                # vom Backend persistiert und wieder ausgeliefert).
                for sub in ast.walk(node.annotation):
                    if (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name)
                            and sub.value.id == "Literal"):
                        for c in ast.walk(sub.slice):
                            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                                ex.produced.append(Site(c.value, mod.rel, node.lineno))
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.value is not None and any(_is_reason_ref(t) for t in targets):
                    # Spaltendefinitionen (``reason_code = Column(String)``) sind keine Codes.
                    if not (isinstance(node.value, ast.Call)
                            and isinstance(node.value.func, ast.Name)
                            and node.value.func.id in {"Column", "mapped_column", "Field"}):
                        record(node.value, ctx, node.lineno)
            elif isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                if any(_is_reason_ref(o) for o in operands):
                    for o in operands:
                        if _is_reason_ref(o):
                            continue
                        items = o.elts if isinstance(o, (ast.Tuple, ast.List, ast.Set)) else [o]
                        for it in items:
                            vals, _ = res.resolve(it, ctx)
                            for v in vals:
                                ex.consumed.append(Site(v, mod.rel, node.lineno))
    return ex


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------

_JS_STR = r"""['"]([A-Za-z][A-Za-z0-9_.\-]*)['"]"""
_RC_NAME = r"(?:reason_code|reasonCode)"
# ``x.reason_code`` und ``x['reason_code']`` (Klammer-Zugriff, K-2-Review N1b)
_RC = _RC_NAME + r"""(?:['"]\s*\])?"""
_CASE_RE = re.compile(r"case\s+" + _JS_STR + r"\s*:")
# Alias-Variable: ``const rc = x.reason_code;`` / ``const { reason_code: rc } = x``
_ALIAS_RE = re.compile(
    r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*[\w$.?]*"
    r"""(?:\.""" + _RC_NAME + r"""\b|\[\s*['"]""" + _RC_NAME + r"""['"]\s*\])"""
    r"\s*(?:;|,|\n|\)|\|\||\?\?)"
)
_ALIAS_DESTRUCT_RE = re.compile(r"\{[^{}]*\b" + _RC_NAME + r"\s*:\s*([A-Za-z_$][\w$]*)[^{}]*\}\s*=")


def _frontend_rules(ref: str) -> dict[str, re.Pattern]:
    """Erkennungsregeln fuer einen Referenz-Ausdruck ``ref`` (Code oder Alias)."""
    return {
        "cmp": re.compile(ref + r"\s*(?:===?|!==?)\s*" + _JS_STR),
        "cmp_rev": re.compile(_JS_STR + r"""\s*(?:===?|!==?)\s*[\w$.\]\[?'"]*""" + ref + r"(?![\w$])"),
        "cmp_const": re.compile(ref + r"\s*(?:===?|!==?)\s*([A-Z][A-Z0-9_]+)\b"),
        "map_use": re.compile(r"\b([A-Za-z_$][\w$]*)\s*\[\s*[\w$.?]*" + ref + r"\s*\]"),
        "switch": re.compile(r"switch\s*\(\s*[\w$.?]*" + ref + r"\s*\)\s*\{(.*?)\n\s*\}", re.S),
        "includes": re.compile(r"\[([^\[\]]*)\]\s*\.includes\(\s*[\w$.?]*" + ref + r"\s*\)"),
        "starts": re.compile(ref + r"\s*\??\.startsWith\(\s*" + _JS_STR + r"\s*\)"),
    }


def _js_const(text: str, name: str) -> str | None:
    m = re.search(r"(?:var|let|const)\s+" + re.escape(name) + r"\s*(?::\s*\w+\s*)?=\s*" + _JS_STR, text)
    return m.group(1) if m else None


def _js_object_keys(text: str, name: str) -> list[str]:
    """Schluessel der obersten Ebene eines JS-Objektliterals ``var NAME={...}``.

    Kleiner Scanner: Strings, Kommentare und verschachtelte Klammern werden
    uebersprungen, damit Kommas/Doppelpunkte in Meldungstexten keine
    Schluessel vortaeuschen.
    """
    m = re.search(r"(?:var|let|const)\s+" + re.escape(name) + r"\s*(?::[^=]+)?=\s*\{", text)
    if not m:
        return []
    i, n = m.end(), len(text)
    keys: list[str] = []
    expect_key = True
    depth = 0

    def skip_string(j: int) -> int:
        quote = text[j]
        j += 1
        while j < n and text[j] != quote:
            j += 2 if text[j] == "\\" else 1
        return j + 1

    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if text.startswith("/*", i):
            i = text.find("*/", i) + 2
            continue
        if depth == 0 and expect_key:
            km = re.compile(r"""(?:['"]([^'"]*)['"]|([A-Za-z_$][\w$]*))\s*:""").match(text, i)
            if km:
                keys.append(km.group(1) if km.group(1) is not None else km.group(2))
                i = km.end()
                expect_key = False
                continue
            if c == "}":
                break
            expect_key = False
        if c in "'\"`":
            i = skip_string(i)
            continue
        if c in "{[(":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "}":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            expect_key = True
        i += 1
    return keys


def extract_frontend_text(text: str) -> set[str]:
    """Ausgewertete Reason-Codes eines JS/TS-Texts (Regex, kein Parser).

    Erkannt werden, jeweils fuer ``x.reason_code``, ``x['reason_code']``
    (auch ``reasonCode``) und fuer Alias-Variablen (``const rc =
    x.reason_code`` bzw. ``const { reason_code: rc } = x``):
    Vergleich mit Literal (beide Richtungen) oder Konstante, Map-Zugriff
    ``MAP[x.reason_code]`` (Objekt-Schluessel), ``switch``/``case``,
    ``['A', 'B'].includes(x.reason_code)`` und ``x.reason_code.startsWith('P')``
    (geliefert als ``"P*"``, ein Praefix).

    Grenzen (bewusst, weil per Regex nicht robust): Aliase sind nicht
    scope-genau (der Aliasname gilt in der ganzen Datei); Weitergabe ueber
    Funktionsparameter, ``includes`` auf benannten Arrays
    (``CODES.includes(rc)``), berechnete Strings, ``indexOf``/``Set.has``
    und mehrstufige Aliase werden nicht verfolgt.
    """
    codes: set[str] = set()
    aliases = sorted(
        {m.group(1) for m in _ALIAS_RE.finditer(text)}
        | {m.group(1) for m in _ALIAS_DESTRUCT_RE.finditer(text)}
    )
    refs = [_RC] + [r"(?<![\w$.])" + re.escape(a) for a in aliases]
    for ref in refs:
        rules = _frontend_rules(ref)
        for m in rules["cmp"].finditer(text):
            # ``typeof x.reason_code === 'string'`` ist eine Typpruefung, kein Code.
            if not re.search(r"typeof\s+[\w$.\[\]'\"]*$", text[max(0, m.start() - 60):m.start()]):
                codes.add(m.group(1))
        codes.update(m.group(1) for m in rules["cmp_rev"].finditer(text))
        for m in rules["cmp_const"].finditer(text):
            v = _js_const(text, m.group(1))
            if v:
                codes.add(v)
        for m in rules["map_use"].finditer(text):
            codes.update(_js_object_keys(text, m.group(1)))
        for sm in rules["switch"].finditer(text):
            codes.update(c.group(1) for c in _CASE_RE.finditer(sm.group(1)))
        for m in rules["includes"].finditer(text):
            codes.update(c.group(1) for c in re.finditer(_JS_STR, m.group(1)))
        codes.update(m.group(1) + "*" for m in rules["starts"].finditer(text))
    return codes


def split_prefixes(codes: set[str]) -> tuple[set[str], set[str]]:
    """(exakte Codes, Praefixe ohne ``*``) aus ``extract_frontend_text``."""
    return {c for c in codes if not c.endswith("*")}, {c[:-1] for c in codes if c.endswith("*")}


def _is_test_file(path: Path) -> bool:
    return ".test." in path.name or ".spec." in path.name or "__tests__" in path.parts


def extract_monolith() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    files = [MONOLITH, *sorted(FRONTEND_ROOT.glob("*.js"))]
    for f in files:
        codes = extract_frontend_text(f.read_text(encoding="utf-8"))
        if codes:
            out[f.relative_to(REPO_ROOT).as_posix()] = codes
    return out


def extract_reporting() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(REPORTING_SRC.rglob("*")):
        if f.suffix not in {".ts", ".tsx", ".js", ".jsx"} or _is_test_file(f):
            continue
        codes = extract_frontend_text(f.read_text(encoding="utf-8"))
        if codes:
            out[f.relative_to(REPO_ROOT).as_posix()] = codes
    return out
