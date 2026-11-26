"""UX-L1a (UX-CH-05, Codex-UX-Audit 25.11.2026): produktweit Sie-Ansprache.

Sichtbare Texte im Frontend und an die Oberflaeche gesendete Servermeldungen
enthalten keine Du-Formen. Erkennung wie im Codex-Abnahmevertrag
test_2026_11_27_ux_l1_contracts.py (Ich-Form "Ich bestaetige" ist korrekt).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADDRESS = re.compile(
    r"(?i)\b(du|dir|dich|dein(?:e|en|em|er|es)?|kannst|möchtest|willst|"
    r"wähle|gib|prüfe|füge|klicke|trage|lege|speichere|bestätige|setze|bewahre|scanne|gehst)\b"
)
SCOPES = ("ares-desktop/frontend", "ares-backend/core", "ares-backend/routers", "ares-backend/services")
SKIP = ("/vendor/", "/node_modules/", "/dist/", "/build/", "/tests/")
SUFFIXES = (".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".py")
SERVER_VISIBLE = re.compile(
    r"(?i)(detail\s*=|message\s*=|HTTPException|DomainError|status_text|"
    r"user_message|customer_message|ui_message|label\s*=)"
)


def _candidates(text: str) -> list[str]:
    return [
        line for line in text.splitlines()
        if ADDRESS.search(line)
        and not line.lstrip().startswith(("#", "//", "/*", "*"))
        and not re.search(r"\bIch bestätige\b", line, re.I)
    ]


def _sources():
    for scope in SCOPES:
        for path in sorted((REPO / scope).rglob("*")):
            rel = path.relative_to(REPO).as_posix()
            if not path.is_file() or not rel.endswith(SUFFIXES) or any(s in f"/{rel}" for s in SKIP):
                continue
            yield rel, path.read_text(encoding="utf-8", errors="replace")


def test_detector_controls():
    assert _candidates("<button>Wähle dein Ziel</button>")
    assert _candidates("msg='Passwort gesetzt. Du kannst dich jetzt anmelden.'")
    assert not _candidates("<button>Wählen Sie Ihr Ziel</button>")
    assert not _candidates("<span>Ich bestätige, dass ich informiert habe.</span>")


def test_visible_copy_uses_formal_address():
    hits = []
    for rel, text in _sources():
        frontend = rel.startswith("ares-desktop/frontend/")
        for line in _candidates(text):
            if frontend or SERVER_VISIBLE.search(line):
                hits.append(f"{rel}: {line.strip()[:160]}")
    assert not hits, "Du-Formen in sichtbaren Texten:\n" + "\n".join(hits[:60])
