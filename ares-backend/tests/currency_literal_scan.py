"""G7 / H-153 Nachtrag 3+4 -- Scanner fuer fest eingetragene CHF-Waehrungsangaben.

Durchsucht die Anzeige-/Formatierpfade aller drei Kanaele:

* Classic-Bundle: ``ares-desktop/frontend/ares.html`` und jedes ausgelagerte bzw.
  eigenstaendige Modul -- die Liste kommt aus ``scripts/audit_html_monolith.py``
  (EXTRACTED_MONOLITH_PARTS + STANDALONE_FRONTEND_MODULES, nur ``.js``), nicht von Hand;
* React-Bericht: ``ares-desktop/frontend/reporting/src/**/*.ts(x)`` ohne Tests
  und ohne ``src/test/`` (Test-Fixtures);
* PDF: ``ares-backend/services/pdf/**/*.py`` und ``ares-backend/routers/pdf_reports.py``.

Treffer:

* Token ``CHF`` (nicht Teil eines Bezeichners wie ``formatCompactCHF``) im Code
  ausserhalb von Kommentaren (Python: nur String-Literale ohne Docstrings);
* N-894-15: ausgeschriebene Formen ``Schweizer Franken``, ``Franken``, ``Fr.``,
  ``SFr`` (jede Schreibweise, H11: auch ``sfr``) und kleingeschriebenes ``chf``
  (Wortgrenzen) in String-Literalen und
  Markup-Text (Bezeichner wie ``var chf`` sind kein Anzeigetext).

Jeder Treffer braucht einen Eintrag mit Einzelbegruendung in
``docs/audits/2026-11-13-g7-currency-literal-allowlist.json``.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = REPO_ROOT / "docs/audits/2026-11-13-g7-currency-literal-allowlist.json"
TOKEN = re.compile(r"(?<![A-Za-z0-9_$])CHF(?![A-Za-z0-9_$])")
WORDS = re.compile(
    r"(?<![A-Za-z0-9_$\-])(?:Schweizer\s+Franken|Franken|[Ss][Ff][Rr]\.?|Fr\.(?=\s*[\d'])|chf)(?![A-Za-z0-9_$\-])"
)
STRING_SEGMENT = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`")


def classic_modules(root: Path = REPO_ROOT) -> list[str]:
    """N-894-13: Modulliste aus der Monolith-Inventur generiert (nicht von Hand)."""
    scripts = str(root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from audit_html_monolith import EXTRACTED_MONOLITH_PARTS, STANDALONE_FRONTEND_MODULES

    names = {name for name, kind in EXTRACTED_MONOLITH_PARTS if kind == "js"}
    names |= {name for name in STANDALONE_FRONTEND_MODULES if name.endswith(".js")}
    return sorted(names)


def scanned_files(root: Path = REPO_ROOT) -> list[Path]:
    fe = root / "ares-desktop/frontend"
    files = [fe / "ares.html", *[fe / name for name in classic_modules(root)]]
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


def _python_string_lines(text: str, pattern: re.Pattern) -> set[int]:
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
            if pattern.search(node.value):
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    lines.add(ln)
    return lines


def _display_text(code: str) -> str:
    """String-Literale und Markup-Text einer Codezeile (ohne Bezeichner)."""
    # Template-Platzhalter ${...} sind Code, kein Anzeigetext.
    parts = [re.sub(r"\$\{[^}]*\}", " ", m.group(0)) for m in STRING_SEGMENT.finditer(code)]
    if code.lstrip().startswith("<"):
        # Markup-Zeile: Textknoten (Tags entfernt) zusaetzlich zu den Attributwerten.
        parts.append(re.sub(r"<[^>]*>", " ", code))
    return "\n".join(parts)


def scan_text(rel: str, text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    if rel.endswith(".py"):
        src = text.splitlines()
        lines = _python_string_lines(text, TOKEN) | _python_string_lines(text, WORDS)
        for ln in sorted(lines):
            hits.append((rel, src[ln - 1].strip()))
        return hits
    for _no, code in _strip_js_comments(text):
        if TOKEN.search(code) or WORDS.search(_display_text(code)):
            hits.append((rel, code.strip()))
    return hits


def scan(root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for path in scanned_files(root):
        rel = path.relative_to(root).as_posix()
        hits += scan_text(rel, path.read_text(encoding="utf-8"))
    return hits
