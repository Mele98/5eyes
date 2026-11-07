"""N-875-01/-05: Das Quelltext-Testnetz deckt jede ausgelagerte Monolith-Datei ab.

Hintergrund (Pruefrunde H3 @ d4b1cd5d): Nach der Auslagerung lasen viele
Tests weiterhin nur ``ares.html``. Ihre "darf nirgends vorkommen"-Guards
(native Dialoge, Token in localStorage, Storage-Key-Praefix ...) waren damit
fuer ``goal-review-runtime.js``/``intro-sequence.js``/``ares.css`` blind --
per Mutation belegt. Dieser Test haelt drei Dinge fest:

1. Statisch: kein Test liest ``ares.html`` roh (``read_text``/``read_bytes``/
   ``open``/``_read``), ausser einer kleinen, begruendeten Ausnahmeliste.
2. Per Mutation: eine verbotene Zeile in JEDER ausgelagerten Datei macht die
   Guards rot (die Original-Mutation aus der Pruefrunde als Regressionstest).
3. Jede lokal von ``ares.html`` eingebundene Datei ist entweder ausgelagerter
   Monolith-Teil (Bundle + Budget) oder steht bewusst in der dokumentierten
   Ausnahmeliste eigenstaendiger Module -- eine neue Datei ohne Eintrag ist rot.
"""
from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path

import pytest

import tests.monolith_source as monolith_source
from audit_html_monolith import STANDALONE_FRONTEND_MODULES

TESTS_DIR = Path(__file__).resolve().parent

# Lesen die Rohdatei bewusst: Groessen-/Inventar-/Einbindungsvertraege,
# der Bundle-Helfer selbst, dieser Meta-Test, und der Reason-Code-Katalog
# (liest ares.html UND alle frontend/*.js separat, deckt die JS-Teile also ab).
RAW_READ_ALLOWED = {
    "monolith_source.py",
    "test_frontend_monolith_size_budget.py",
    "test_monolith_inventory_stable.py",
    "test_frontend_monolith_extracted_parts.py",
    "test_frontend_monolith_bundle_coverage.py",
    "reason_code_contract_support.py",
}

_READ_ATTRS = {"read_text", "read_bytes", "open"}


def _is_html_path_expr(node: ast.AST) -> bool:
    return any(
        isinstance(sub, ast.Constant)
        and isinstance(sub.value, str)
        and (sub.value == "ares.html" or sub.value.endswith("/ares.html"))
        for sub in ast.walk(node)
    )


def _raw_monolith_reads(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if _is_html_path_expr(node.value):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names |= {t.id for t in targets if isinstance(t, ast.Name)}
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # X.read_text() / X.read_bytes() / X.open() mit X = ares.html-Pfad
        if isinstance(func, ast.Attribute) and func.attr in _READ_ATTRS:
            base = func.value
            if (isinstance(base, ast.Name) and base.id in names) or (
                not isinstance(base, ast.Name) and _is_html_path_expr(base)
            ):
                hits.append(f"{path.name}:{node.lineno}")
        # open(X) / _read(X) / beliebige Helfer, die den Pfad zum Lesen bekommen
        elif isinstance(func, ast.Name) and func.id in {"open", "_read", "_scan"}:
            for arg in node.args:
                if (isinstance(arg, ast.Name) and arg.id in names) or _is_html_path_expr(arg):
                    hits.append(f"{path.name}:{node.lineno}")
    return hits


def test_no_test_reads_the_monolith_raw_outside_allowlist():
    offenders = []
    checked = 0
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.name in RAW_READ_ALLOWED or "__pycache__" in path.parts:
            continue
        checked += 1
        offenders += _raw_monolith_reads(path)
    assert checked > 100
    assert offenders == [], (
        "Diese Stellen lesen ares.html roh und sind fuer die ausgelagerten Teile "
        f"blind -- read_monolith_bundle() verwenden: {offenders}"
    )


def test_static_detector_flags_raw_reads(tmp_path):
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        'from pathlib import Path\n'
        'HTML_PATH = Path("x") / "ares-desktop" / "frontend" / "ares.html"\n'
        'def a():\n    return HTML_PATH.read_text(encoding="utf-8")\n'
        'def b():\n    return (Path("x") / "ares.html").read_text()\n'
        'def c():\n    return open(HTML_PATH).read()\n',
        encoding="utf-8",
    )
    assert len(_raw_monolith_reads(sample)) == 3


# --- Mutation: verbotene Zeile in jeder ausgelagerten Datei -> Guards rot ----

_PAYLOAD = (
    "\nif(window.__h3probe){alert('x');localStorage.getItem('ares.token');"
    "localStorage.setItem('h3probe_key','1');}\n"
)


def _guards():
    from tests import (
        test_frontend_no_native_dialogs as dialogs,
        test_frontend_refresh_token_wiring as tokens,
        test_frontend_storage_keys_contract as keys,
    )

    return {
        "native_dialogs": dialogs.test_monolith_has_no_native_dialogs,
        "refresh_token": tokens.test_refresh_token_storage_functions_exist_and_are_distinct_from_access_token,
        "storage_keys": keys.test_every_literal_storage_key_is_ares_prefixed_or_neutral,
    }


def _mirror_frontend(tmp_path: Path) -> Path:
    target = tmp_path / "frontend"
    target.mkdir()
    shutil.copy2(monolith_source.MONOLITH_PATH, target / "ares.html")
    for name, _kind in monolith_source.EXTRACTED_PARTS:
        shutil.copy2(monolith_source.FRONTEND_DIR / name, target / name)
    return target


def test_guards_are_green_on_unmutated_mirror(tmp_path, monkeypatch):
    mirror = _mirror_frontend(tmp_path)
    monkeypatch.setattr(monolith_source, "FRONTEND_DIR", mirror)
    monkeypatch.setattr(monolith_source, "MONOLITH_PATH", mirror / "ares.html")
    for guard in _guards().values():
        guard()


@pytest.mark.parametrize("part", [name for name, _kind in monolith_source.EXTRACTED_PARTS])
@pytest.mark.parametrize("guard_name", ["native_dialogs", "refresh_token", "storage_keys"])
def test_forbidden_line_in_extracted_part_turns_guard_red(tmp_path, monkeypatch, part, guard_name):
    mirror = _mirror_frontend(tmp_path)
    target = mirror / part
    target.write_text(target.read_text(encoding="utf-8") + _PAYLOAD, encoding="utf-8")
    monkeypatch.setattr(monolith_source, "FRONTEND_DIR", mirror)
    monkeypatch.setattr(monolith_source, "MONOLITH_PATH", mirror / "ares.html")
    with pytest.raises(AssertionError):
        _guards()[guard_name]()


def test_original_review_mutation_comment_replaced_in_runtime_turns_guards_red(tmp_path, monkeypatch):
    """Pruefrunde H3: Kommentarzeile groessenneutral ersetzt -> muss rot werden."""
    mirror = _mirror_frontend(tmp_path)
    target = mirror / "goal-review-runtime.js"
    lines = target.read_text(encoding="utf-8").split("\n")
    idx = next(i for i, line in enumerate(lines) if line.lstrip().startswith("//"))
    lines[idx] = "if(window.__p){alert('x');localStorage.getItem('ares.token');}"
    target.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(monolith_source, "FRONTEND_DIR", mirror)
    monkeypatch.setattr(monolith_source, "MONOLITH_PATH", mirror / "ares.html")
    guards = _guards()
    for name in ("native_dialogs", "refresh_token"):
        with pytest.raises(AssertionError):
            guards[name]()


# --- N-875-05: keine lokal eingebundene Datei ohne Zuordnung ------------------

def _local_refs(html: str) -> list[str]:
    refs = re.findall(r'<(?:script|link)\b[^>]*\b(?:src|href)="([^"\'+]+)"', html)
    out = []
    for ref in refs:
        if re.match(r"^[a-z]+:|^//|^#", ref):
            continue
        out.append(ref[2:] if ref.startswith("./") else ref)
    return out


def _unassigned(html: str) -> list[str]:
    extracted = {name for name, _kind in monolith_source.EXTRACTED_PARTS}
    return [
        ref for ref in _local_refs(html)
        if not ref.startswith("vendor/")
        and ref not in extracted
        and ref not in STANDALONE_FRONTEND_MODULES
    ]


def test_every_local_frontend_file_is_extracted_part_or_documented_module():
    html = monolith_source.MONOLITH_PATH.read_text(encoding="utf-8")
    assert _unassigned(html) == [], (
        "Neue lokal eingebundene Datei ohne Zuordnung: in EXTRACTED_MONOLITH_PARTS "
        "(Bundle + Budget) oder begruendet in STANDALONE_FRONTEND_MODULES eintragen."
    )
    refs = set(_local_refs(html))
    stale = sorted(set(STANDALONE_FRONTEND_MODULES) - refs)
    assert stale == [], f"Ausnahmeliste enthaelt nicht mehr eingebundene Module: {stale}"
    for name, reason in STANDALONE_FRONTEND_MODULES.items():
        test_file = reason.rsplit(" ", 1)[-1]
        assert (TESTS_DIR / test_file).is_file(), f"{name}: Modultest {test_file} fehlt"
        assert name in (TESTS_DIR / test_file).read_text(encoding="utf-8"), (name, test_file)


def test_unassigned_new_script_is_detected():
    html = monolith_source.MONOLITH_PATH.read_text(encoding="utf-8")
    grown = html.replace("</body>", '<script src="./new-module.js"></script>\n</body>', 1)
    assert _unassigned(grown) == ["new-module.js"]
