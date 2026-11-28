"""UX-L1c (UX-Vertrag 27.11.2026): lesbare Mindest-Schriftgroesse.

Normale Texte, Labels, Hinweise, Status, Buttons, Eingaben, KPI und Metadaten
>= 12 px; nur Tabellenzellen/-koepfe, Badges/Tags/Chips und Schrittkreise
>= 10 px. Gleiche Klassifikation wie der unabhaengige Vertrag: CSS-Dateien je
Regelblock (Selektor), alle anderen Quellen je Zeile (Inline-Stile, fail-closed
bei mehrdeutigen Zeilen).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPE = ("ares-desktop/frontend/", "ares-backend/core/", "ares-backend/routers/", "ares-backend/services/")
SKIP_PARTS = ("/vendor/", "/node_modules/", "/dist/", "/build/", "/tests/")
SUFFIXES = (".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".py")

FONT_PX = re.compile(r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)px", re.I)
COMPACT = re.compile(
    r"(?i)(?:^|[\s>+~,.#:-])(?:table|thead|tbody|tfoot|tr|th|td)(?:$|[\s>+~,.#:-])|"
    r"(?:badge|chip|tag|step(?:-circle)?|circle)"
)


def violations(text: str, *, css: bool) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    if css:
        for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", text, re.S):
            minimum = 10.0 if COMPACT.search(block.group(1)) else 12.0
            found += [(" ".join(block.group(1).split())[-120:], float(m.group(1)))
                      for m in FONT_PX.finditer(block.group(2)) if float(m.group(1)) < minimum]
    else:
        for line in text.splitlines():
            minimum = 10.0 if COMPACT.search(line) else 12.0
            found += [(line.strip()[:120], float(m.group(1)))
                      for m in FONT_PX.finditer(line) if float(m.group(1)) < minimum]
    return found


def _sources():
    listed = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], check=True,
                            capture_output=True, text=True).stdout.splitlines()
    for rel in listed:
        if rel.startswith(SCOPE) and rel.endswith(SUFFIXES) and not any(p in rel for p in SKIP_PARTS):
            yield rel, (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_detector_controls():
    assert violations(".hint{font-size:10px}", css=True)
    assert not violations(".hint{font-size:12px}", css=True)
    assert not violations("table td{font-size:10px}.badge{font-size:10px}.step-circle{font-size:10px}", css=True)
    assert violations("table td{font-size:9px}", css=True)
    assert violations('<div style="font-size:11px">Hinweis</div>', css=False)
    assert not violations('<span class="badge" style="font-size:10px">A</span>', css=False)


def test_no_text_style_is_below_minimum():
    hits = [(rel, ctx, size) for rel, text in _sources()
            for ctx, size in violations(text, css=rel.endswith(".css"))]
    assert not hits, f"{len(hits)} Schriftgroessen unter dem Minimum, z. B. {hits[:10]}"
