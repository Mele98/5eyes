"""Audit 2026-11, Paket P1: UI fuer Stammdaten und Retrozessions-Block.

Die Logik liegt im ausgelagerten Modul ``frontend/product-master-data.js``
(Monolith-Budget, Toleranz 0); ``ares.html`` enthaelt nur Container und
``typeof``-Hooks ohne zusaetzliche Zeilen.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

FRONTEND = BACKEND_ROOT.parent / "ares-desktop" / "frontend"
HTML_PATH = FRONTEND / "ares.html"
MODULE_PATH = FRONTEND / "product-master-data.js"
PACKAGE_JSON = BACKEND_ROOT.parent / "ares-desktop" / "package.json"


def test_monolith_loads_module_and_has_hooks():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert '<script src="./product-master-data.js"></script>' in html
    for element_id in ("pf-master-data", "cd-retro"):
        assert f'id="{element_id}"' in html, element_id
    body = html[html.index("function renderCostDisclosure(data){"):]
    assert "renderCostRetrocessions(data)" in body[:400]
    create = html[html.index("function adminCreateFund"):]
    assert "adminCollectFundMasterData(payload, !!adminFundEditingId)" in create[:6000]
    assert "adminFundMasterDataBadges(p)" in html
    assert "adminExportFundsCsv()" in html
    assert "frontend/product-master-data.js" in json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["build"]["files"]


def test_module_renders_all_master_data_fields_and_marks():
    module = MODULE_PATH.read_text(encoding="utf-8")
    for element_id in ("pf-domicile", "pf-is-hedged", "pf-hedge-currency", "pf-ter-source",
                       "pf-ter-as-of", "pf-retro", "pf-retro-source", "pf-house-product",
                       "pf-distribution", "pf-valor", "pf-min-investment"):
        assert f'id="{element_id}"' in module, element_id
    assert "Retrozession unbekannt" in module
    assert "ISIN ungueltig" in module


def _run(script_body: str) -> dict:
    module = MODULE_PATH.read_text(encoding="utf-8")
    script = """
    var document = {addEventListener: function(){}, getElementById: function(id){ return id in values ? {value: values[id]} : null; }};
    var window = {};
    function escapeHtml(v){ return String(v); }
    %s
    %s
    """ % (module, script_body)
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _collect(values: dict, editing: bool) -> dict:
    return _run(
        "var values = %s; var payload = {}; var err = adminCollectFundMasterData(payload, %s);"
        " process.stdout.write(JSON.stringify({err: err, payload: payload}));"
        % (json.dumps(values), "true" if editing else "false")
    )


def test_form_collect_never_invents_retro_zero():
    created = _collect({"pf-domicile": "ie", "pf-is-hedged": "true"}, editing=False)
    assert created["err"] is None
    assert created["payload"] == {"domicile": "IE", "is_hedged": True}
    edited = _collect({}, editing=True)
    assert edited["payload"]["retrocession_bps"] is None
    assert edited["payload"]["is_hedged"] is None
    no_source = _collect({"pf-retro": "40"}, editing=False)
    assert "Quelle" in no_source["err"]
    full = _collect({"pf-retro": "40", "pf-retro-source": "Vertrag", "pf-min-investment": "1000.5"}, editing=False)
    assert full["payload"]["retrocession_bps"] == 40
    assert full["payload"]["minimum_investment_minor_units"] == 100050


def test_badges_mark_unknown_retro_and_invalid_isin():
    out = _run(
        "var values = {}; process.stdout.write(JSON.stringify({"
        "unknown: adminFundMasterDataBadges({isin_status:'invalid', retrocession_status:'unknown', master_data_gaps:['isin','retrocession_bps','domicile']}),"
        "free: adminFundMasterDataBadges({isin_status:'valid', retrocession_status:'none', master_data_gaps:[]})}));"
    )
    assert "ISIN ungueltig" in out["unknown"] and "Retrozession unbekannt" in out["unknown"]
    assert "Stammdaten unvollstaendig" in out["unknown"]
    assert out["free"] == ""


def test_form_collect_own_fund_fields():
    missing = _collect({"pf-listing-status": "unlisted"}, editing=False)
    assert "interne Produkt-ID" in missing["err"]
    ok = _collect({"pf-listing-status": "unlisted", "pf-internal-id": "HF-1", "pf-price-source": "manual_nav",
                   "pf-nav-frequency": "quarterly", "pf-redemption-days": "30", "pf-has-gating": "true"},
                  editing=False)
    assert ok["err"] is None
    assert ok["payload"]["internal_product_id"] == "HF-1"
    assert ok["payload"]["redemption_period_days"] == 30 and ok["payload"]["has_gating"] is True
    module = MODULE_PATH.read_text(encoding="utf-8")
    for element_id in ("pf-listing-status", "pf-internal-id", "pf-price-source", "pf-nav-frequency",
                       "pf-nav-as-of", "pf-redemption-days", "pf-notice-days", "pf-has-gating", "pf-gating-terms"):
        assert f'id="{element_id}"' in module, element_id


def test_minimum_investment_uses_currency_minor_digits():
    """N-861-4: keine feste /100 -- JPY 0, CHF 2, KWD 3 Nachkommastellen."""
    jpy = _collect({"pf-currency": "JPY", "pf-min-investment": "100000"}, editing=False)
    assert jpy["payload"]["minimum_investment_minor_units"] == 100000
    kwd = _collect({"pf-currency": "kwd", "pf-min-investment": "1.234"}, editing=False)
    assert kwd["payload"]["minimum_investment_minor_units"] == 1234
    chf = _collect({"pf-currency": "CHF", "pf-min-investment": "1000.5"}, editing=False)
    assert chf["payload"]["minimum_investment_minor_units"] == 100050
    too_precise = _collect({"pf-currency": "JPY", "pf-min-investment": "10.5"}, editing=False)
    assert "Nachkommastellen" in too_precise["err"]
    shown = _run(
        "var values = {}; var shown = {}; document.getElementById = function(id){"
        " if (!(id in shown)) shown[id] = {value: ''}; return shown[id]; };"
        " adminFillFundMasterData({currency: 'JPY', minimum_investment_minor_units: 5000});"
        " process.stdout.write(JSON.stringify({v: shown['pf-min-investment'].value}));"
    )
    assert shown["v"] == "5000"
