"""H10 N-899-15/-18: statischer Scan auf Prozessausfuehrung im Produktcode.

Gemeldet wird jede Ausfuehrung
- ueber eine Shell (shell=True, os.system/os.popen, create_subprocess_shell,
  subprocess.getoutput, Programm cmd/powershell/sh ...) -> ``shell``,
- mit nicht-literalem Programm (Variable, Funktionsaufruf, f-String) ->
  ``programm-variabel``,
- H11 (N-899-21): ueber dynamische Formen -> ``dynamisch``: ``getattr(os,
  "system")`` bzw. ``getattr(<modul>, <variabel>)`` auf os/subprocess/pty/
  webbrowser/asyncio, ``__import__("os")``, ``importlib.import_module(
  "subprocess")``, ``from os import *``,
- H11: Oeffnen ausserhalb von Ares -> ``extern-oeffnen``: ``os.startfile``,
  ``webbrowser.open*``, ``pty.spawn`` (auch mit Literal/URL).
Aliase werden aufgeloest (``import subprocess as sp``, ``from os import
system``, ``from subprocess import run as r``). Jede Meldung braucht eine
Ausnahme mit Begruendung, Schluessel je Aufrufstelle ``<pfad>::<funktion>#<n>``
(n = n-te Meldung in der Funktion, H11: Ausnahme pro Aufruf statt pro Funktion).
Bewusst nicht erkannt (Laufzeit-Audit-Hook deckt sie ab): Modulname aus einer
Variable (``import_module(name)``), zusammengesetzte Namen.
"""
from __future__ import annotations

import ast
from pathlib import Path

SHELL_NAMES = frozenset({"sh", "bash", "zsh", "dash", "ksh", "cmd", "powershell", "pwsh"})
_SUBPROCESS = ("run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput")
_OS = ("system", "popen", "execv", "execve", "execl", "execle", "execlp", "execlpe", "execvp", "execvpe",
       "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "posix_spawn",
       "posix_spawnp", "startfile")
EXEC_FUNCS = frozenset({("subprocess", f) for f in _SUBPROCESS} | {("os", f) for f in _OS}
                       | {("asyncio", "create_subprocess_exec"), ("asyncio", "create_subprocess_shell")})
SHELL_FUNCS = frozenset({("os", "system"), ("os", "popen"), ("asyncio", "create_subprocess_shell"),
                         ("subprocess", "getoutput"), ("subprocess", "getstatusoutput")})
OPEN_FUNCS = frozenset({("os", "startfile"), ("webbrowser", "open"), ("webbrowser", "open_new"),
                        ("webbrowser", "open_new_tab"), ("pty", "spawn")})
DYNAMIC_MODULES = frozenset({"os", "subprocess", "pty", "webbrowser", "asyncio"})
_ROOTS = ("subprocess", "os", "asyncio", "pty", "webbrowser", "importlib")
SKIP_DIRS = frozenset({"tests", "alembic", "migrations", "venv", ".venv", "node_modules"})


def _aliases(tree: ast.AST) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    modules: dict[str, str] = {}
    funcs: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _ROOTS:
                    modules[alias.asname or root] = root
        elif isinstance(node, ast.ImportFrom) and node.module in _ROOTS:
            for alias in node.names:
                funcs[alias.asname or alias.name] = (node.module, alias.name)
    return modules, funcs


def _target(func: ast.AST, modules: dict[str, str], funcs: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name) and base.id in modules:
            return modules[base.id], func.attr
        if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.attr == "subprocess" \
                and modules.get(base.value.id) == "asyncio":
            return "asyncio", func.attr
        return None
    if isinstance(func, ast.Name):
        return funcs.get(func.id)
    return None


def _program_node(call: ast.Call, target: tuple[str, str]) -> ast.AST | None:
    module, name = target
    if module == "os" and name.startswith("spawn"):
        node = call.args[1] if len(call.args) > 1 else None
    else:
        node = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg in ("args", "path")),
                                                    None)
    if isinstance(node, (ast.List, ast.Tuple)):
        return node.elts[0] if node.elts else None
    return node


def _literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _program_name(text: str) -> str:
    name = text.replace("\\", "/").strip().split()[0].split("/")[-1].lower() if text.strip() else ""
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _dynamic(call: ast.Call, modules: dict[str, str], funcs: dict[str, tuple[str, str]]) -> bool:
    """H11: getattr(<os|subprocess|...>, <exec-Name|variabel>), __import__/import_module("<modul>")."""
    func = call.func
    first = call.args[0] if call.args else None
    if isinstance(func, ast.Name) and func.id == "getattr" and len(call.args) >= 2:
        module = modules.get(first.id) if isinstance(first, ast.Name) else None
        attr = _literal(call.args[1])
        return module in DYNAMIC_MODULES and (attr is None or (module, attr) in EXEC_FUNCS | OPEN_FUNCS)
    importer = (isinstance(func, ast.Name) and func.id == "__import__")         or _target(func, modules, funcs) == ("importlib", "import_module")
    name = _literal(first)
    return bool(importer and name and name.split(".")[0] in DYNAMIC_MODULES)


def scan_source(source: str, rel: str) -> list[tuple[str, int, str]]:
    """Liste von (Schluessel ``pfad::funktion#n``, Zeile, Art)."""
    tree = ast.parse(source)
    modules, funcs = _aliases(tree)
    found = []
    ordinal: dict[str, int] = {}

    def report(scope: str, line: int, kind: str) -> None:
        key = f"{rel}::{scope}"
        ordinal[key] = ordinal.get(key, 0) + 1
        found.append((f"{key}#{ordinal[key]}", line, kind))

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = child.name if scope == "<modul>" else f"{scope}.{child.name}"
            if isinstance(child, ast.ImportFrom) and child.module in DYNAMIC_MODULES                     and any(a.name == "*" for a in child.names):
                report(scope, child.lineno, "dynamisch")
            if isinstance(child, ast.Call):
                target = _target(child.func, modules, funcs)
                if target in OPEN_FUNCS:
                    report(scope, child.lineno, "extern-oeffnen")
                elif target in EXEC_FUNCS:
                    program = _literal(_program_node(child, target))
                    shell_kw = any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and not k.value.value)
                                   for k in child.keywords)
                    if target in SHELL_FUNCS or shell_kw or (program is not None
                                                             and _program_name(program) in SHELL_NAMES):
                        report(scope, child.lineno, "shell")
                    elif program is None:
                        report(scope, child.lineno, "programm-variabel")
                elif _dynamic(child, modules, funcs):
                    report(scope, child.lineno, "dynamisch")
            visit(child, inner)

    visit(tree, "<modul>")
    return found


def scan_tree(root: Path, base: Path | None = None) -> list[tuple[str, int, str]]:
    base = base or root
    found = []
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(root).parts[0] in SKIP_DIRS:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            found.extend(scan_source(source, path.relative_to(base).as_posix()))
        except SyntaxError:
            continue
    return found
