"""KN-B / E2E2-11: echte Umlaute in Kunden-PDFs und Berater-Meldungen.

Befund (Dok. 117): Kunden-PDFs und Servermeldungen zeigten Umlaut-Ersatz
("Vermoegensverwalter", "Fuer", "koennen", "Pruefung", "Waehrung",
"BERATUNGSVERMOEGEN" ...). Code-Bezeichner, Kommentare, Docstrings, Schluessel
und gespeicherte Werte (z. B. Zielhaerte "Primaer") bleiben unveraendert.

Waechter: In den String-Literalen der Kunden-PDF-Module (``services/pdf``,
``routers/pdf_reports.py``) und in den Meldungen der in Dok. 117 beanstandeten
Quellen (``ADVISOR_MESSAGE_SOURCES``) steht keines der Ersatzwoerter mehr.

Gegenprobe: ein Ersatzwort in eine Meldung zuruecksetzen -> rot.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(
    r"\b(fuer|Fuer|FUER|koennen|moeglich|Pruefung|pruefen|Waehrung\w*|Vermoegen\w*|VERMOEGEN\w*|"
    r"persoenlich\w*|beruecksichtigt|muessen|Eignungspruefung|Risikofaehigkeit|Umsetzungsuebersicht|"
    r"ueber|Uebersicht|ausdruecklich\w*|Bestaetigung\w*|vollstaendig\w*|ergaenzt|uebergeben|geaendert|"
    r"Taetigkeitsfeld|Depotbestaende|zusaetzlich\w*|gueltig\w*|ungueltig\w*|zulaessig\w*|unzulaessig\w*)\b"
)
ERROR_CALL = re.compile(r"(Error|Exception)$")
MESSAGE_KEYS = {"detail", "message"}


def _strings(node):
    return [sub for sub in ast.walk(node) if isinstance(sub, ast.Constant) and isinstance(sub.value, str)]


def _docstrings(tree):
    return {id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}


def _excluded(tree):
    """Dict-Schluessel, Vergleiche, Subscripts: Daten, keine Texte."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            out.update(id(k) for k in n.keys if isinstance(k, ast.Constant))
        elif isinstance(n, ast.Compare):
            for part in [n.left, *n.comparators]:
                out.update(id(s) for s in _strings(part))
        elif isinstance(n, ast.Subscript):
            out.update(id(s) for s in _strings(n.slice))
        elif isinstance(n, ast.Call) and getattr(n.func, "attr", None) in {"debug", "info", "warning", "error",
                                                                           "exception", "replace", "get"}:
            for arg in [*n.args, *(k.value for k in n.keywords)]:
                out.update(id(s) for s in _strings(arg))  # Logs bzw. Platzhalter/Schluessel
    return out


def _pdf_texts(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstrings(tree) | _excluded(tree)
    return [s for s in _strings(tree) if id(s) not in skip]


def _message_texts(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None) or ""
            if ERROR_CALL.search(name):
                for arg in [*n.args, *(k.value for k in n.keywords if k.arg in (None, "detail", "message"))]:
                    found += _strings(arg)
        elif isinstance(n, ast.Dict):
            for key, value in zip(n.keys, n.values):
                if isinstance(key, ast.Constant) and key.value in MESSAGE_KEYS and value is not None:
                    found += _strings(value)
    return found


def _hits(paths, collect):
    hits = []
    for path in paths:
        for node in collect(path):
            text = node.value
            if re.fullmatch(r"[a-z0-9_.:/{}\-]+", text.strip()):
                continue  # Schluessel/Bezeichner
            for match in FORBIDDEN.finditer(text):
                rel = path.relative_to(BACKEND).as_posix() if BACKEND in path.parents else path.name
                hits.append(f"{rel}:{node.lineno}: {match.group(0)}")
    return hits


def test_customer_pdf_texts_use_real_umlauts():
    paths = sorted((BACKEND / "services" / "pdf").rglob("*.py")) + [BACKEND / "routers" / "pdf_reports.py"]
    hits = _hits(paths, _pdf_texts)
    assert hits == [], hits


# Berater-Meldungen aus Dok. 117 (Compliance-Sperrtexte/Kundeninformation,
# Handelsliste, Veraltet-Meldung). Die uebrigen Servermeldungen folgen separat
# (viele Texte sind in Tests/Snapshots festgenagelt; siehe H-168).
ADVISOR_MESSAGE_SOURCES = ("services/recommendation_release_gate.py", "services/portfolio_handoff.py",
                           "core/fx_freshness.py")


def test_advisor_messages_use_real_umlauts():
    paths = [BACKEND / rel for rel in ADVISOR_MESSAGE_SOURCES]
    hits = _hits(paths, _message_texts)
    assert hits == [], hits


def test_guard_detects_substitute(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text('raise HTTPException(status_code=409, detail="Bitte Vermoegen fuer den Kunden pruefen")',
                     encoding="utf-8")
    assert len(_hits([probe], _message_texts)) == 3


def test_stored_values_stay_unchanged():
    """Gespeicherte Werte/Schluessel bleiben ASCII (z. B. Zielhaerte "Primaer")."""
    text = (BACKEND / "services" / "goal_semantics.py").read_text(encoding="utf-8")
    assert "Primaer" in text
    static = (BACKEND / "services" / "pdf" / "components" / "static_texts.py").read_text(encoding="utf-8")
    assert "{referenzwaehrung}" in static
