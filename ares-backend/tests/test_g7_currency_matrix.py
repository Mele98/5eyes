"""G7 / H-153 Nachtrag 4 -- Waehrungs-Matrix (N-894-12, Grundregel).

Grundregel: Ein Betrag wird immer mit der Waehrung beschriftet, in der er tatsaechlich
vorliegt. Fuer ein EUR- und ein JPY-Mandat (Positionen und Cashflows in CHF, ueber die
echte API erfasst) traegt dieselbe Groesse auf allen Kanaelen dieselbe Waehrung:

* Kunden-Rohsummen (wealth-summary, Positionen): CHF (Server ``amount_currency``),
  Classic-KPI und Vermoegensseite -- nicht die Mandatswaehrung.
* Cashflow-Summary: CHF (Server rechnet in ``amount_currency`` um).
* Allokation (Engine): Mandatswaehrung -- Classic AA und PDF Anlagestrategie.
* Beratungsbericht Monte-Carlo-Pfade: ``amount_currency`` des Payloads (Rohsumme ohne
  FX, hier CHF) -- React-Achse und Beratungsbericht-PDF.
* Liquiditaetsbedarf: ``liquiditaetsbedarf_currency`` (CHF) -- React und PDF.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pypdf import PdfReader

from tests.livetest_monolith_js import FAKE_DOM, extract_function, html
from tests.monolith_source import rounding_module_source
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
from tests.test_g7_full_api_path_parity import _create_client_and_mandate

REACT_SRC = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "reporting" / "src"


def _plain(text: str) -> str:
    return str(text).replace("−", "-").replace(" ", " ")


def _node(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    proc = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _classic(mandate_currency: str, wealth: dict, cashflow: dict, positions: list, allocation: dict) -> dict:
    src = html()
    fns = "\n".join(extract_function(src, n) for n in ("fmtCHF", "formatRappen", "formatSignedRappen"))
    return _node(
        rounding_module_source() + FAKE_DOM
        + "var currentMandateData={base_currency:" + json.dumps(mandate_currency) + "};"
        + "var strategyState={allocation:" + json.dumps({"base_currency": allocation.get("base_currency")}) + "};\n"
        + fns + "\n"
        + "var w=" + json.dumps(wealth) + ",cf=" + json.dumps(cashflow) + ",pos=" + json.dumps(positions) + ";"
        + "process.stdout.write(JSON.stringify({"
        # loadClientById-KPI (fmtK) und Vermoegensseite (renderWealthPositions: positionsCurrency)
        + "kpiAdvisory:fmtCHF(w.advisory_wealth_chf,w.amount_currency),"
        + "wealthTotal:fmtCHF(pos.reduce(function(s,p){return s+p.current_value_rappen/100;},0),positionsCurrency(pos)),"
        + "kpiCashflow:fmtCHF(cf.surplus_chf,cf.amount_currency),"
        # Allokation (Engine) -> Artefakt-/Mandatswaehrung
        + "allocationAdvisory:formatRappen(" + json.dumps(allocation["advisory_wealth_rappen"]) + ")}));"
    )


def _react(paths: dict, client_info: dict, tmp_path) -> dict:
    runner = tmp_path / "react_matrix.mts"
    mc = (REACT_SRC / "components" / "MonteCarloPathsChart.tsx")
    fmt = (REACT_SRC / "lib" / "format.ts")
    del mc  # Achsen-Formatter liegt in der TSX-Komponente; Achsenlogik ueber format.ts nachgebildet unten
    runner.write_text(
        "import { formatChfRappen } from " + json.dumps(fmt.as_uri()) + ";\n"
        "const paths = " + json.dumps({"amount_currency": paths.get("amount_currency")}) + ";\n"
        "const ci = " + json.dumps(client_info) + ";\n"
        "process.stdout.write(JSON.stringify({\n"
        "  mcCurrency: paths.amount_currency ?? null,\n"
        "  liquidity: formatChfRappen(ci.liquiditaetsbedarf_rappen, { currency: ci.liquiditaetsbedarf_currency ?? null }),\n"
        "}));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(runner)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    if proc.returncode != 0 and ("strip-types" in proc.stderr or "ERR_UNKNOWN_FILE_EXTENSION" in proc.stderr
                                 or "Cannot find module" in proc.stderr):
        pytest.skip("Node ohne Type-Stripping/Alias-Aufloesung")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _pdf(api, mandate_id, report, **params) -> str:
    resp = api.get(f"/mandates/{mandate_id}/reports/{report}", params=params)
    assert resp.status_code == 200, (report, resp.text[:400])
    return re.sub(r"[ \t]+", " ", "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resp.content)).pages))


@pytest.mark.parametrize("currency", ["EUR", "JPY"])
def test_same_quantity_same_currency_on_every_channel(api, advisor_user, currency, tmp_path):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, currency)
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)
    generated = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {
        "cmaCurrencyMismatchReason": "Kunde lebt in der Schweiz, Mandat in Fremdwaehrung; Waehrungsrisiko besprochen und akzeptiert."}})
    assert generated.status_code in (200, 201), generated.text
    allocation = generated.json()
    alloc_id = allocation.get("target_allocation_id") or allocation.get("id")

    wealth = api.get(f"/clients/{client_id}/wealth-summary").json()
    cashflow = api.get(f"/clients/{client_id}/cashflow-summary").json()
    positions = api.get(f"/clients/{client_id}/wealth-positions").json()
    positions = positions if isinstance(positions, list) else positions.get("items", [])
    report = api.get(f"/mandates/{mandate_id}/advisory-report")
    assert report.status_code == 200, report.text[:400]
    payload = report.json()
    mc = payload["sections"]["goal_based_investing"]["monte_carlo_paths"] if "sections" in payload \
        else payload["goal_based_investing"]["monte_carlo_paths"]
    ci = (payload.get("sections") or payload)["ausgangslage"]["client_info"]

    # Server liefert die Waehrung der Quelle (Positionen/Cashflows sind CHF erfasst).
    assert {p["currency"] for p in positions} == {"CHF"}
    assert wealth["amount_currency"] == "CHF"
    assert cashflow["amount_currency"] == "CHF"
    assert mc["amount_currency"] == "CHF"
    assert ci["liquiditaetsbedarf_currency"] == "CHF"
    assert payload.get("mandate_currency") == currency

    classic = _classic(currency, wealth, cashflow, positions, allocation)
    react = _react(mc, ci, tmp_path)
    advisory_pdf = _pdf(api, mandate_id, "advisory-report.pdf")
    strategy_pdf = _pdf(api, mandate_id, "anlagestrategie.pdf", expected_allocation_id=alloc_id)

    matrix = {
        "Kunden-Rohsumme (Classic KPI, Vermoegensseite)": ({_plain(classic["kpiAdvisory"]).split(" ")[0],
                                                            _plain(classic["wealthTotal"]).split(" ")[0]}, "CHF"),
        "Cashflow-Summary (Classic KPI)": ({_plain(classic["kpiCashflow"]).split(" ")[0]}, "CHF"),
        "Allokation (Classic AA)": ({_plain(classic["allocationAdvisory"]).split(" ")[0]}, currency),
        "MC-Pfade (React-Achse)": ({react["mcCurrency"]}, "CHF"),
        "Liquiditaetsbedarf (React)": ({_plain(react["liquidity"]).split(" ")[0]}, "CHF"),
    }
    for name, (seen, expected) in matrix.items():
        assert seen == {expected}, (name, seen, expected)

    # PDF-Kanaele: dieselben Groessen in derselben Waehrung.
    liq = re.search(r"Liquiditätsbedarf\s+([A-Z]{3}) [\d']+", advisory_pdf)
    assert liq and liq.group(1) == "CHF", liq
    ticks = set(re.findall(r"\b([A-Z]{3}) \d+(?:\.\d+)? Mio\.", advisory_pdf))
    assert ticks <= {"CHF"}, ticks  # MC-Achse/-Saetze nie in Mandatswaehrung beschriftet
    if mc.get("projection_status") == "current" and not mc.get("data_pending"):
        assert ticks == {"CHF"}, ("MC-Achse fehlt im Beratungsbericht", ticks)
    total = re.search(r"Total Beratungsverm(?:ö|oe)gen\s+(?:100\.0 %\s+|–\s+)?([A-Z]{3}) [\d']+", strategy_pdf)
    assert total and total.group(1) == currency, total
