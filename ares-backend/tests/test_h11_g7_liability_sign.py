"""H11 (Hygiene-Folgepunkt G7, N-894-18): Vorzeichen nur bei einer Zahl.

Befund: Die Vermoegens-Karte (``prependWealthSplitSummary``) haengte ein festes
Minus vor den Betrag. Bei unbekannter Waehrung (Grundregel G7: "—") stand dort
"Verbindlichkeiten -—" bzw. in der Kachel "−—". Jetzt traegt nur eine Zahl ein
Vorzeichen; "—" bleibt "—".

Verhaltenstest: die echte Monolith-Funktion samt echtem Formatter
(``fmtCHF``/``AresRounding``) in Node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tests.livetest_monolith_js import extract_function, html
from tests.monolith_source import rounding_module_source



def _fn(src: str, name: str) -> str:
    """Auch eingerueckte Funktionsdeklarationen (Vermoegens-Renderer)."""
    m = re.search(r"\n[ \t]*function " + re.escape(name) + r"\(", src)
    assert m, name
    return extract_function("\n" + src[m.start():].lstrip("\n \t"), name)


FUNCS = ("ccyOf", "_ccyArg", "fmtCHF", "escapeHtml", "wealthSharePercent", "prependWealthSplitSummary")


def _render(meta: dict) -> str:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = html()
    script = (
        rounding_module_source()
        + "\nfunction appCurrency(){return null;}\n"
        + "var out='';var av={querySelector:function(){return null;},"
        + "insertAdjacentHTML:function(_p,h){out=h;}};"
        + "var document={getElementById:function(id){return id==='asset-view'?av:null;}};\n"
        + "\n".join(_fn(src, n) for n in FUNCS)
        + "\nprependWealthSplitSummary(" + json.dumps(meta) + ");"
        + "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return re.sub(r"<[^>]*>", " ", json.loads(proc.stdout))


META = {"grossChf": 1000000, "advisoryChf": 600000, "otherGrossChf": 400000, "liabilitiesChf": 250000,
        "netChf": 750000, "advisoryCount": 2, "otherCount": 1, "liabilityCount": 1}


def test_unknown_currency_shows_dash_without_sign():
    text = _render({**META, "currency": None})
    assert "Verbindlichkeiten —" in text
    for bad in ("-—", "−—", "- —", "− —"):
        assert bad not in text, text


def test_known_currency_keeps_the_minus_sign():
    text = _render({**META, "currency": "CHF"}).replace(" ", " ")
    assert "Verbindlichkeiten −CHF 250" in text
    assert text.count("−CHF 250") == 2  # Fusszeile und Kachel


def test_zero_liabilities_have_no_sign():
    text = _render({**META, "liabilitiesChf": 0, "currency": "EUR"})
    assert "Verbindlichkeiten EUR 0" in text
    assert "−EUR" not in text and "-EUR" not in text
