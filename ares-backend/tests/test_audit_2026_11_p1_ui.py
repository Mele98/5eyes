"""Audit 2026-11, Paket P1: Monolith-UI fuer Stammdaten und Retrozessions-Block."""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 7. Monolith-UI: Stammdaten erfassbar, Kennzeichnung sichtbar, Retro-Block
# ---------------------------------------------------------------------------

HTML_PATH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"


def test_monolith_exposes_master_data_and_retro_block():
    html = HTML_PATH.read_text(encoding="utf-8")
    for element_id in ("pf-domicile", "pf-is-hedged", "pf-hedge-currency", "pf-ter-source",
                       "pf-ter-as-of", "pf-retro", "pf-retro-source", "pf-house-product",
                       "pf-distribution", "pf-valor", "pf-min-investment", "cd-retro"):
        assert f'id="{element_id}"' in html, element_id
    assert "Retrozession unbekannt" in html
    assert "ISIN ungueltig" in html
    body = html[html.index("function renderCostDisclosure(data){"):]
    assert "renderCostRetrocessions(data);" in body[:400]
    collect = html[html.index("function adminCollectFundMasterData"):]
    # leer beim Bearbeiten = explizit null (zurueck auf "unbekannt"), nie 0
    assert "payload.retrocession_bps = null;" in collect[:2500]


def _run_collect(values: dict, editing: bool):
    import json
    import subprocess

    from test_esg_premium_criteria import _extract_js_function

    html = HTML_PATH.read_text(encoding="utf-8")
    script = """
    var values = %s;
    var document = {getElementById: function(id){ return id in values ? {value: values[id]} : {value: ''}; }};
    %s
    var payload = {};
    var err = adminCollectFundMasterData(payload, %s);
    process.stdout.write(JSON.stringify({err: err, payload: payload}));
    """ % (json.dumps(values), _extract_js_function(html, "adminCollectFundMasterData"),
           "true" if editing else "false")
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_form_collect_never_invents_retro_zero():
    import sys

    sys.path.insert(0, str(BACKEND_ROOT / "tests"))
    created = _run_collect({"pf-domicile": "ie", "pf-is-hedged": "true"}, editing=False)
    assert created["err"] is None
    assert created["payload"] == {"domicile": "IE", "is_hedged": True}
    edited = _run_collect({}, editing=True)
    assert edited["payload"]["retrocession_bps"] is None
    assert edited["payload"]["is_hedged"] is None
    no_source = _run_collect({"pf-retro": "40"}, editing=False)
    assert "Quelle" in no_source["err"]
    full = _run_collect({"pf-retro": "40", "pf-retro-source": "Vertrag", "pf-min-investment": "1000.5"}, editing=False)
    assert full["payload"]["retrocession_bps"] == 40
    assert full["payload"]["minimum_investment_minor_units"] == 100050
