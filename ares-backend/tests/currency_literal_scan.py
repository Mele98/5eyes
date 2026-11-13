"""G7 / H-153 Nachtrag 3 -- Scanner fuer fest eingetragene Waehrungscodes "CHF".

Durchsucht die Anzeige-/Formatierpfade aller drei Kanaele:

* Classic-Bundle: ``ares-desktop/frontend/ares.html`` und jedes Standalone-Modul
  ``ares-desktop/frontend/*.js`` (ohne ``vendor/``),
* React-Bericht: ``ares-desktop/frontend/reporting/src/**/*.ts(x)`` ohne Tests
  und ohne ``src/test/`` (Test-Fixtures),
* PDF: ``ares-backend/services/pdf/**/*.py`` und ``ares-backend/routers/pdf_reports.py``.

Treffer = Token ``CHF`` (nicht Teil eines Bezeichners wie ``formatCompactCHF`` oder
``parseCHF``) ausserhalb von Kommentaren; in Python nur in String-Literalen
(inkl. f-Strings), ohne Docstrings. Jeder Treffer braucht einen Eintrag mit
Einzelbegruendung in ``docs/audits/2026-11-13-g7-currency-literal-allowlist.json``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = REPO_ROOT / "docs/audits/2026-11-13-g7-currency-literal-allowlist.json"
TOKEN = re.compile(r"(?<![A-Za-z0-9_$])CHF(?![A-Za-z0-9_$])")


def scanned_files(root: Path = REPO_ROOT) -> list[Path]:
    fe = root / "ares-desktop/frontend"
    files = [fe / "ares.html", *sorted(fe.glob("*.js"))]
    src = fe / "reporting/src"
    files += sorted(
        p for p in src.rglob("*")
        if p.suffix in (".ts", ".tsx") and ".test." not in p.name and "test" not in p.relative_to(src).parts[:1]
    )
    files += [root / "ares-backend/routers/pdf_reports.py", *sorted((root / "ares-backend/services/pdf").rglob("*.py"))]
    return files


def _strip_js_comments(text: str) -> list[tuple[int, str]]:
    """Zeilenweise Code ohne //-, /* */- und <!-- -->-Kommentare (heuristisch, stringbewusst)."""
    out: list[tuple[int, str]] = []
    in_block = None  # '*/' oder '-->'
    for no, line in enumerate(text.splitlines(), 1):
        res = []
        i, n = 0, len(line)
        quote = None
        while i < n:
            if in_block:
                j = line.find(in_block, i)
                if j < 0:
                    i = n
                    break
                i = j + len(in_block)
                in_block = None
                continue
            ch = line[i]
            if quote:
                res.append(ch)
                if ch == "\\" and i + 1 < n:
                    res.append(line[i + 1])
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue
            if ch in "'\"`":
                quote = ch
                res.append(ch)
                i += 1
                continue
            if line.startswith("//", i) and (i == 0 or line[i - 1] != ":"):
                break
            if line.startswith("/*", i):
                in_block = "*/"
                i += 2
                continue
            if line.startswith("<!--", i):
                in_block = "-->"
                i += 4
                continue
            res.append(ch)
            i += 1
        out.append((no, "".join(res)))
    return out


def _python_string_lines(text: str) -> set[int]:
    tree = ast.parse(text)
    doc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                doc_nodes.add(id(body[0].value))
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_nodes:
            if TOKEN.search(node.value):
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    lines.add(ln)
    return lines


def scan_text(rel: str, text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    if rel.endswith(".py"):
        string_lines = _python_string_lines(text)
        src = text.splitlines()
        for ln in sorted(string_lines):
            code = src[ln - 1]
            if TOKEN.search(code.split("#", 1)[0] if '"' not in code and "'" not in code else code):
                hits.append((rel, code.strip()))
        return hits
    for _no, code in _strip_js_comments(text):
        if TOKEN.search(code):
            hits.append((rel, code.strip()))
    return hits


def scan(root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for path in scanned_files(root):
        rel = path.relative_to(root).as_posix()
        hits += scan_text(rel, path.read_text(encoding="utf-8"))
    return hits
