"""G7 / H-153 Nachtrag 1 -- Paritaet App/PDF ueber den vollen API-Pfad.

Kunde, Mandat, Cashflows, Vermoegen, Ziele, Risikoprofil und Produkte werden
ueber die echte API erfasst (Fixtures/Seeds aus dem Thierry-Goessi-Walkthrough),
die Soll-Allokation ueber ``POST /target-allocation/generate`` erzeugt und

* das Server-Artefakt (``GET /target-allocation/current``) wie im Monolithen
  (``applyAllocationEngineResult``-Abbildung) in die echten Monolith-Funktionen
  gegeben: ``aaChartAllocItems`` -> ``aaChartPrepare`` / ``buildDLegend`` (Node),
* das Anlagestrategie-PDF ueber ``GET /reports/anlagestrategie.pdf`` geladen und
  sein Text mit pypdf extrahiert.

Verglichen werden Anteile je Anlageklasse (apportioniert, Summe 100.0 %) und
Zielbetraege inklusive Mandatswaehrung.
"""
from __future__ import annotations

import html as html_lib
import io
import json
import re
import shutil
import subprocess

import pytest
from pypdf import PdfReader

from tests.livetest_monolith_js import extract_function
from tests.monolith_source import read_monolith_bundle, rounding_module_source
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    _create_client_and_mandate,
    _seed_cashflows,
    _seed_goals,
    _seed_products,
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)

FUNCS = (
    "assetDisplayName", "allocationBucketKey", "allocationSubAllocationsForBucket",
    "allocationReserveBreakdown", "allocationTableGroupKey", "formatRappen",
    "aaChartClassRank", "aaChartKey", "aaChartPctText", "aaChartCurrency", "aaChartMoney", "aaChartChf",
    "aaChartApportion", "aaChartPctNumber", "aaChartPrepare", "aaChartShadeStep", "aaChartMix",
    "aaChartDonutDatasets", "aaChartAllocItems", "aaChartHasSubs", "aaChartEsc", "aaChartLegendHtml",
)


def _plain(text: str) -> str:
    return text.replace("−", "-").replace(" ", " ")


def _app(allocation: dict, mandate_currency: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = read_monolith_bundle()
    fns = "\n".join(extract_function(src, n) for n in FUNCS)
    script = (
        rounding_module_source()
        + "var window={};var document={documentElement:{},querySelectorAll:function(){return [];},getElementById:function(){return null;}};"
        + "function getComputedStyle(){return {getPropertyValue:function(){return '#ffffff';}};}\n"
        + "function assetClassColor(){return '#000000';}function assetClassKey(l){return allocationBucketKey(l);}\n"
        + "var allocationSuballocExpanded={};\n"
        + "var strategyState={allocation:" + json.dumps(allocation) + "};\n"
        + "var currentMandateData={base_currency:" + json.dumps(mandate_currency) + "};\n"
        + fns
        # Abbildung wie applyAllocationEngineResult (ares.html).
        + "\nvar alloc=(strategyState.allocation.buckets||[]).map(function(bucket){var key=String(bucket.asset_class||'');"
        + "return {n:assetDisplayName(key),c:assetClassColor(key),soll:Number(bucket.target_weight_bps||0)/100,"
        + "chfTarget:Math.round((Number(bucket.target_amount_rappen||0))/100)};});\n"
        + "var items=aaChartAllocItems();var rows=aaChartPrepare(items);var ds=aaChartDonutDatasets(rows,'#FFFFFF');"
        + "process.stdout.write(JSON.stringify({rows:rows.map(function(r){return {name:r.name,bps:r.bps,pct:r.pct};}),"
        + "amounts:ds[ds.length-1]._aaAmt,legend:aaChartLegendHtml(items,allocationReserveBreakdown(strategyState.allocation))}));"
    )
    proc = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_full_api_path_app_and_strategy_pdf_show_identical_numbers(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user)
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    risk = _seed_risk_profile(api, mandate_id)
    assert risk.get("final_profile")
    _seed_products(api, advisor_user)

    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={})
    assert generated.status_code in (200, 201), generated.text
    # Server-Artefakt, das die App als strategyState.allocation uebernimmt.
    allocation = generated.json()
    assert allocation.get("buckets"), sorted(allocation)[:40]
    mandate = api.get(f"/mandates/{mandate_id}").json()
    currency = str(mandate.get("base_currency") or "CHF").upper()

    pdf = api.get(f"/mandates/{mandate_id}/reports/anlagestrategie.pdf",
                  params={"expected_allocation_id": allocation.get("target_allocation_id") or allocation.get("id")})
    assert pdf.status_code == 200, pdf.text[:400]
    text = re.sub(r"[ \t]+", " ", "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages))

    app = _app(allocation, currency)
    rows = [r for r in app["rows"] if r["bps"] > 0]
    assert len(rows) >= 2, app
    # Summenerhaltung in der App: exakt 100.0 %.
    tenths = [int(round(float(_plain(r["pct"])[:-2]) * 10)) for r in rows]
    assert sum(tenths) == 1000, rows
    pct_re = r"(-?\d[\d']*\.\d %)"
    # Soll-Tabelle (saa_bar_table): "<Klasse> <Anteil> <Waehrung> <Betrag>" -- eindeutig;
    # die IST-Torte (Ausgangslage) nennt dieselben Klassen ohne Betrag.
    for r in rows:
        shown = _plain(r["pct"])
        found = set(re.findall(re.escape(r["name"]) + r"\s+" + pct_re + r"\s+" + currency + r" ", text))
        assert found == {shown}, (r["name"], shown, found)
    # Betraege in Mandatswaehrung: App-Tooltip == PDF-Soll-Tabelle.
    for r, amount in zip(app["rows"], app["amounts"]):
        if r["bps"] > 0 and amount:
            assert _plain(amount).startswith(currency + " ")
            assert _plain(amount) in text, (r["name"], amount)
    legend = _plain(html_lib.unescape(app["legend"]))
    assert "Rundungsdifferenzen" not in legend
    # Strategiebasis, Reserve und Beratungsvermoegen: Legende == PDF-Soll-Tabelle.
    for label in ("Total Anlagestrategie (Strategiebasis)", "Liquiditätsreserve (ausserhalb der Anlagestrategie)",
                  "Total Beratungsvermögen"):
        m = re.search(re.escape(label) + r"\s+(?:100\.0 %\s+|–\s+)?(" + currency + r" [\d']+)", text)
        assert m, label
        assert m.group(1) in legend, (label, m.group(1))
    assert "100.0 %" in text
