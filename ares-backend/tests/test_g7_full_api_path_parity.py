"""G7 / H-153 Nachtrag 1+2 -- Paritaet App/PDF ueber den vollen API-Pfad.

Kunde, Mandat (CHF, EUR oder JPY), Cashflows, Vermoegen, Ziele, Risikoprofil und
Produkte werden ueber die echte API erfasst (Seeds aus dem Thierry-Goessi-
Walkthrough), die Soll-Allokation ueber ``POST /target-allocation/generate`` erzeugt.

* App: das Server-Artefakt geht wie in ``applyAllocationEngineResult`` in die echten
  Monolith-Funktionen (``aaChartAllocItems``/``aaChartPrepare``/``aaChartLegendHtml``,
  ``sollPct`` der Review-Seite); React ``bucketPctMap`` (presentationRounding.ts).
* PDF: ``GET /reports/anlagestrategie.pdf`` (Soll-Tabelle, Produkt-Subtotale) und
  ``GET /reports/assetallocation.pdf`` (Hauptklassen-Tabelle), Text per pypdf.

N-894-02: "gleiche Klasse = gleicher Text" ueber alle Kanaele und Tabellen.
N-894-01: JPY-Mandat in korrekter Groessenordnung (Rappen-Felder Faktor 100).
"""
from __future__ import annotations

import html as html_lib
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pypdf import PdfReader

from tests.livetest_monolith_js import extract_function
from tests.monolith_source import read_monolith_bundle, rounding_module_source
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    _seed_cashflows,
    _seed_goals,
    _seed_products,
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)

REACT_TS = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "reporting" / "src" / "lib" / "presentationRounding.ts"
FUNCS = (
    "assetDisplayName", "allocationBucketKey", "allocationSubAllocationsForBucket",
    "allocationReserveBreakdown", "allocationTableGroupKey", "formatRappen", "formatBpsPercent", "fmtPct",
    "aaChartClassRank", "aaChartKey", "aaChartPctText", "aaChartCurrency", "aaChartMoney", "aaChartChf",
    "aaChartApportion", "aaChartPctNumber", "aaChartPrepare", "aaChartShadeStep", "aaChartMix",
    "aaChartDonutDatasets", "aaChartAllocItems", "aaChartHasSubs", "aaChartEsc", "aaChartLegendHtml",
)


def _plain(text: str) -> str:
    return text.replace("−", "-").replace(" ", " ")


def _create_client_and_mandate(api, advisor_user, currency: str) -> tuple[str, str]:
    resp = api.post("/clients", json={
        "client_number": "TG-2026-001", "first_name": "Thierry", "last_name": "Gössi",
        "advisor_id": advisor_user.id, "household_type": "Einzelperson", "birth_date": "1979-04-18",
        "tax_domicile": "CH", "data_classification": "synthetic",
    })
    assert resp.status_code == 201, resp.text
    client_id = resp.json()["id"]
    resp = api.post(f"/clients/{client_id}/mandates", json={
        "mandate_number": "TG-M-001", "mandate_type": "Vermögensverwaltung", "base_currency": currency,
    })
    assert resp.status_code == 201, resp.text
    return client_id, resp.json()["id"]


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
        + "var review={};(strategyState.allocation.buckets||[]).forEach(function(b){review[assetDisplayName(b.asset_class)]=sollPct(b.asset_class,b.target_weight_bps);});"
        + "process.stdout.write(JSON.stringify({rows:rows.map(function(r){return {name:r.name,bps:r.bps,pct:r.pct};}),review:review,"
        + "advisoryText:formatRappen(strategyState.allocation.advisory_wealth_rappen),"
        + "amounts:ds[ds.length-1]._aaAmt,legend:aaChartLegendHtml(items,allocationReserveBreakdown(strategyState.allocation))}));"
    )
    proc = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _react_bucket_texts(buckets: list[dict], tmp_path) -> dict:
    runner = tmp_path / "react_buckets.mts"
    runner.write_text(
        "import * as R from " + json.dumps(REACT_TS.as_uri()) + ";\n"
        "process.stdout.write(JSON.stringify(R.bucketPctMap(" + json.dumps(buckets) + ", { typography: 'screen' })));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(runner)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    if proc.returncode != 0 and "strip-types" in proc.stderr:
        pytest.skip("Node ohne Type-Stripping")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _pdf_text(api, mandate_id, report, allocation_id) -> str:
    pdf = api.get(f"/mandates/{mandate_id}/reports/{report}", params={"expected_allocation_id": allocation_id})
    assert pdf.status_code == 200, (report, pdf.text[:400])
    return re.sub(r"[ \t]+", " ", "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages))


@pytest.mark.parametrize("currency", ["CHF", "EUR", "JPY"])
def test_full_api_path_app_and_pdfs_show_identical_numbers(api, advisor_user, currency, tmp_path):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, currency)
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)

    # EUR/JPY: CMA in CHF -> dokumentierte Beraterbestaetigung (CMA-CURRENCY-GUARD-001).
    body = {} if currency == "CHF" else {"preferences": {"cmaCurrencyMismatchReason": (
        "Kunde lebt in der Schweiz, Mandat wird in Fremdwaehrung ausgewiesen; "
        "Waehrungsrisiko wurde im Gespraech besprochen und bewusst akzeptiert.")}}
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json=body)
    assert generated.status_code in (200, 201), generated.text
    allocation = generated.json()  # Server-Artefakt, das die App uebernimmt
    assert allocation.get("buckets"), sorted(allocation)[:40]
    alloc_id = allocation.get("target_allocation_id") or allocation.get("id")

    strategy = _pdf_text(api, mandate_id, "anlagestrategie.pdf", alloc_id)
    aa_pdf = _pdf_text(api, mandate_id, "assetallocation.pdf", alloc_id)
    app = _app(allocation, currency)
    react = _react_bucket_texts([{"asset_class": b["asset_class"], "target_weight_bps": b["target_weight_bps"]}
                                 for b in allocation["buckets"]], tmp_path)
    rows = [r for r in app["rows"] if r["bps"] > 0]
    assert len(rows) >= 2, app
    assert sum(int(round(float(_plain(r["pct"])[:-2]) * 10)) for r in rows) == 1000, rows

    pct_re = r"(-?\d[\d']*\.\d %)"
    react_by_name = {}
    for b in allocation["buckets"]:
        if b["target_weight_bps"] > 0:
            react_by_name[b["asset_class"]] = react[b["asset_class"]]
    for r in rows:
        shown = _plain(r["pct"])
        # PDF Soll-Tabelle "<Klasse> <Anteil> <Waehrung> <Betrag>".
        soll = set(re.findall(re.escape(r["name"]) + r"\s+" + pct_re + r"\s+" + currency + r" ", strategy))
        assert soll == {shown}, ("Soll-Tabelle", r["name"], shown, soll)
        # Produkttabelle desselben PDFs: Subtotal je Klasse.
        sub = set(re.findall(r"Subtotal " + re.escape(r["name"]) + r"\s+" + pct_re, strategy))
        assert sub <= {shown}, ("Produkt-Subtotal", r["name"], shown, sub)
        # Asset-Allocation-PDF, Hauptklassen-Tabelle "<Klasse> <Zielquote> <Band Min> ...".
        aa = re.findall(r"(?m)^" + re.escape(r["name"]) + r"\s+" + pct_re, aa_pdf)
        assert aa and set(aa) <= {shown}, ("AA-PDF", r["name"], shown, aa)
        # Review-Seite (sollPct) und React (bucketPctMap).
        assert _plain(app["review"][r["name"]]) == shown, ("Review", r["name"])
    for name, text in react_by_name.items():
        disp = next(r for r in rows if r["name"] in (name, name.replace("Liquiditaet", "Liquidität")))
        assert _plain(text) == _plain(disp["pct"]), ("React", name)

    # Betraege in Mandatswaehrung, Groessenordnung: Rappen-Felder Faktor 100 (auch JPY).
    advisory_units = round(allocation["advisory_wealth_rappen"] / 100)
    assert _plain(app["advisoryText"]).startswith(f"{currency} ")
    assert int(_plain(app["advisoryText"]).split(" ", 1)[1].replace("'", "")) == advisory_units
    for r, amount in zip(app["rows"], app["amounts"]):
        if r["bps"] > 0 and amount:
            assert _plain(amount).startswith(currency + " ")
            assert _plain(amount) in strategy, (r["name"], amount)
    legend = _plain(html_lib.unescape(app["legend"]))
    assert "Rundungsdifferenzen" not in legend
    reserve_shown = "Liquiditätsreserve (ausserhalb der Anlagestrategie)" in strategy
    labels = (("Total Anlagestrategie (Strategiebasis)", "Liquiditätsreserve (ausserhalb der Anlagestrategie)",
               "Total Beratungsvermögen") if reserve_shown else ("Total Beratungsvermoegen",))
    for label in labels:
        m = re.search(re.escape(label) + r"\s+(?:100\.0 %\s+|–\s+)?(" + currency + r" [\d']+)", strategy)
        assert m, label
        if reserve_shown:
            assert m.group(1) in legend, (label, m.group(1))
        if label.startswith("Total Beratungsverm"):
            assert int(m.group(1).split(" ", 1)[1].replace("'", "")) == advisory_units, (label, m.group(1))
    if currency != "CHF":
        assert "CHF " not in legend
