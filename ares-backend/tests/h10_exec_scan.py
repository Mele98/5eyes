"""H10 N-899-15/-18: statischer Scan auf Prozessausfuehrung im Produktcode.

Gemeldet wird jede Ausfuehrung
- ueber eine Shell (shell=True, os.system/os.popen, create_subprocess_shell,
  subprocess.getoutput, Programm cmd/powershell/sh ...) -> ``shell``,
- mit nicht-literalem Programm (Variable, Funktionsaufruf, f-String) ->
  ``programm-variabel``.
Aliase werden aufgeloest (``import subprocess as sp``, ``from os import
system``, ``from subprocess import run as r``). Jede Meldung braucht eine
Ausnahme mit Begruendung, Schluessel ``<pfad>::<funktion>``.
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
SKIP_DIRS = frozenset({"tests", "alembic", "migrations", "venv", ".venv", "node_modules"})


def _aliases(tree: ast.AST) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    modules: dict[str, str] = {}
    funcs: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in ("subprocess", "os", "asyncio"):
                    modules[alias.asname or root] = root
        elif isinstance(node, ast.ImportFrom) and node.module in ("subprocess", "os", "asyncio"):
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


def scan_source(source: str, rel: str) -> list[tuple[str, int, str]]:
    """Liste von (Schluessel ``pfad::funktion``, Zeile, Art)."""
    tree = ast.parse(source)
    modules, funcs = _aliases(tree)
    found = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = child.name if scope == "<modul>" else f"{scope}.{child.name}"
            if isinstance(child, ast.Call):
                target = _target(child.func, modules, funcs)
                if target in EXEC_FUNCS:
                    program = _literal(_program_node(child, target))
                    shell_kw = any(k.arg == "shell" and not (isinstance(k.value, ast.Constant) and not k.value.value)
                                   for k in child.keywords)
                    if target in SHELL_FUNCS or shell_kw or (program is not None
                                                             and _program_name(program) in SHELL_NAMES):
                        found.append((f"{rel}::{scope}", child.lineno, "shell"))
                    elif program is None:
                        found.append((f"{rel}::{scope}", child.lineno, "programm-variabel"))
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
