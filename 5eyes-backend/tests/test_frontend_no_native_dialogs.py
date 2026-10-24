"""Electron unterstuetzt die nativen Browser-Dialoge (Eingabe, Bestaetigung,
Hinweis) nicht: ein Aufruf liefert dort keinen Dialog, die Aktion bleibt
unausfuehrbar (z. B. Storno einer Weiterleitung an das Asset Management).

Vertrag: Monolith und React-App rufen sie nie auf, weder ueber ``window.``
noch nackt. Ersatz im Monolith ist der Dialog-Service (``uiConfirm``,
``uiPrompt``, ``uiAlert``) auf Basis der Modal-Komponente ``om``/``cm``.
Ausnahmen nur ueber die explizite Whitelist unten, die leer bleiben soll.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "5eyes-electron" / "frontend"
MONOLITH = FRONTEND / "5eyes_v2.html"
REACT_SRC = FRONTEND / "reporting" / "src"

# Explizite Ausnahmen als (relativer Pfad, gekuerzte Zeile). Muss leer bleiben.
ALLOWED_NATIVE_DIALOG_CALLS: frozenset[tuple[str, str]] = frozenset()

_WINDOW_CALL = re.compile(r"\bwindow\s*(?:\.|\?\.)\s*(prompt|confirm|alert)\b")
_BARE_CALL = re.compile(r"(?<![\w$.])(prompt|confirm|alert)\s*\(")


def _violations(text: str) -> list[tuple[int, str]]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _WINDOW_CALL.search(line) or _BARE_CALL.search(line):
            hits.append((lineno, line.strip()[:160]))
    return hits


def _react_files() -> list[Path]:
    return sorted(
        p for p in REACT_SRC.rglob("*")
        if p.suffix in {".ts", ".tsx", ".js", ".jsx"} and "node_modules" not in p.parts
    )


def _scan(path: Path) -> list[str]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    return [
        f"{rel}:{lineno}: {line}"
        for lineno, line in _violations(path.read_text(encoding="utf-8"))
        if (rel, line) not in ALLOWED_NATIVE_DIALOG_CALLS
    ]


def test_whitelist_is_empty():
    assert ALLOWED_NATIVE_DIALOG_CALLS == frozenset()


@pytest.mark.parametrize("sample", [
    "if(!window.confirm('x'))return;",
    "var r=window.prompt('Grund:');",
    "window.alert(msg)",
    "if(!confirm('x'))return;",
    "else alert('x');",
    "var r=prompt('x','');",
    "try{alert(1);}catch(_){ }",
    "const ok = window?.confirm(msg)",
    "// window.confirm nur im Kommentar",
])
def test_detector_flags_native_dialogs(sample):
    assert _violations(sample), sample


@pytest.mark.parametrize("sample", [
    "if(!(await uiConfirm('x')))return;",
    "var r=await uiPrompt({message:'x'});",
    "uiAlert({level:'error',message:'x'});",
    "async function cancelPortfolioHandoffPrompt(handoffId){",
    "adminPolicyCloneConfirm();",
    "password_reset_confirm(token)",
    "API.post('/x/confirm', {})",
    "dialog.confirm(x)",
])
def test_detector_ignores_service_and_lookalikes(sample):
    assert not _violations(sample), sample


def test_monolith_has_no_native_dialogs():
    assert _scan(MONOLITH) == []


def test_react_app_has_no_native_dialogs():
    files = _react_files()
    assert files, "React-Quellen nicht gefunden"
    hits = [hit for path in files for hit in _scan(path)]
    assert hits == []


def test_monolith_provides_dialog_service_on_modal_component():
    html = MONOLITH.read_text(encoding="utf-8")
    for sig in (
        "function uiConfirm(opts){",
        "function uiPrompt(opts){",
        "function uiAlert(opts){",
        "function uiDialogKeydown(event){",
    ):
        assert sig in html, sig
    start = html.index("function uiDialogShow(req){")
    body = html[start:html.index("\nfunction ", start + 1)]
    assert "om('m-ui-dialog');" in body
    start = html.index("function uiDialogClose(result){")
    body = html[start:html.index("\nfunction ", start + 1)]
    assert "cm('m-ui-dialog');" in body
