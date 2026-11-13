"""G7 / H-153 Nachtrag 2 -- Vertragstests zu N-894-01, -04, -05, -06.

* N-894-01: Ares-Rappen-Felder haben immer Speicher-Exponent 2 (auch JPY); nur die
  angezeigten Nachkommastellen folgen ISO. PDF-Helfer, Classic, React gleich.
* N-894-04: Die Rundungs-Policy ist Teil des Archiv-Inhaltshashs.
* N-894-05: App-Geldformatter und Review-Soll-Anteile nutzen die Mandatswaehrung
  bzw. dieselbe Apportionierung wie Legende/PDF; Dossier ueber presentationAmounts.
* N-894-06: presentation_amounts/presentationAmounts erzwingen Ganzzahlen in allen
  drei Kanaelen (gleicher Fehlerfall).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core import presentation_rounding as R
from tests.livetest_monolith_js import extract_function
from tests.monolith_source import read_monolith_bundle, rounding_module_source

ROOT = Path(__file__).resolve().parents[2]
CLASSIC = ROOT / "ares-desktop" / "frontend" / "presentation-rounding.js"
REACT = ROOT / "ares-desktop" / "frontend" / "reporting" / "src" / "lib" / "presentationRounding.ts"


def _node():
    if shutil.which("node") is None:
        pytest.skip("node not available")


def _plain(text: str) -> str:
    return text.replace("−", "-").replace(" ", " ")


# --- N-894-01 ---------------------------------------------------------------

def test_storage_exponent_is_two_for_every_currency_in_python():
    from services.pdf.components.swiss_numbers import format_chf_rappen
    assert R.STORAGE_EXPONENT == 2
    assert R.format_amount_minor(8412698413, "JPY") == "JPY 84'126'984"
    assert R.format_amount_minor(8412698450, "JPY", decimals=2) == "JPY 84'126'985"
    assert format_chf_rappen(8412698413, currency="JPY") == "JPY 84'126'984"
    assert R.format_amount_minor(123456, "EUR", decimals=2) == "EUR 1'234.56"
    units = R.presentation_amounts(841269841300, 830000000050, [6941, 3059], ["equities", "bonds"])
    assert units["advisory_units"] == 8412698413  # ganze Yen, nicht x100


def test_storage_exponent_identical_in_classic_and_react(tmp_path):
    _node()
    js = subprocess.run(
        ["node", "-e", "const R=require(" + json.dumps(str(CLASSIC)) + ");process.stdout.write(JSON.stringify("
         "[R.STORAGE_EXPONENT,R.formatStoredAmount(8412698413,'JPY',0,{typography:'plain'}),"
         "R.formatStoredAmount(8412698450,'JPY',2,{typography:'plain'}),R.formatStoredAmount(123456,'EUR',2,{typography:'plain'})]))"],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert js.returncode == 0, js.stderr
    runner = tmp_path / "r.mts"
    runner.write_text("import * as R from " + json.dumps(REACT.as_uri()) + ";\nprocess.stdout.write(JSON.stringify("
                      "[R.STORAGE_EXPONENT,R.formatStoredAmount(8412698413,'JPY',0,{typography:'plain'}),"
                      "R.formatStoredAmount(8412698450,'JPY',2,{typography:'plain'}),R.formatStoredAmount(123456,'EUR',2,{typography:'plain'})]));\n",
                      encoding="utf-8")
    ts = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(runner)],
                        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert ts.returncode == 0, ts.stderr
    expected = [2, "JPY 84'126'984", "JPY 84'126'985", "EUR 1'234.56"]
    assert json.loads(js.stdout) == expected
    assert json.loads(ts.stdout) == expected


def test_app_money_paths_read_rappen_with_storage_exponent():
    js = (ROOT / "ares-desktop" / "frontend" / "aa-chart.js").read_text(encoding="utf-8")
    html = read_monolith_bundle()
    tsx = (ROOT / "ares-desktop" / "frontend" / "reporting" / "src" / "pages" / "Kostenausweis.tsx").read_text(encoding="utf-8")
    assert "minorExponent(" not in js  # kein ISO-Exponent auf Rappen-Feldern
    assert "AresRounding.formatStoredAmount(" in js
    assert "AresRounding.formatStoredAmount(" in html.split("function _formatRappenChf(", 1)[1].split("\n}", 1)[0]
    assert "formatStoredAmount(" in tsx and "CURRENCY_EXPONENTS" not in tsx


# --- N-894-04 ---------------------------------------------------------------

def test_archive_content_hash_binds_rounding_policy(monkeypatch):
    from services import document_archive

    @dataclasses.dataclass
    class Data:
        weight_bps: int = 1225

    payload = json.dumps({"data": {"weight_bps": 1225}, "rounding_policy": R.ROUNDING_POLICY_VERSION},
                         sort_keys=True, default=str)
    assert document_archive.content_hash_for(Data()) == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    old = json.dumps({"weight_bps": 1225}, sort_keys=True, default=str)
    assert document_archive.content_hash_for(Data()) != hashlib.sha256(old.encode("utf-8")).hexdigest()
    first = document_archive.content_hash_for(Data())
    monkeypatch.setattr(document_archive, "ROUNDING_POLICY_VERSION", "ares-rounding/2")
    assert document_archive.content_hash_for(Data()) != first


# --- N-894-05 ---------------------------------------------------------------

def test_app_money_formatters_and_review_soll_use_mandate_currency_and_apportionment():
    _node()
    src = read_monolith_bundle()
    fns = "\n".join(extract_function(src, n) for n in (
        "formatRappen", "formatSignedRappen", "formatCompactCHFAmount", "formatCompactCHF", "fmtCHF",
        "formatBpsPercent", "fmtPct", "aaChartCurrency"))
    allocation = {"base_currency": "EUR", "buckets": [
        {"asset_class": "Aktien", "target_weight_bps": 6933}, {"asset_class": "Obligationen", "target_weight_bps": 1751},
        {"asset_class": "Immobilien", "target_weight_bps": 551}, {"asset_class": "Alternative", "target_weight_bps": 563},
        {"asset_class": "Liquiditaet", "target_weight_bps": 202}]}
    script = (rounding_module_source() + "var strategyState={allocation:" + json.dumps(allocation) + "};\n" + fns
              + "\nprocess.stdout.write(JSON.stringify({r:formatRappen(55789550),s:formatSignedRappen(-150),"
              "c:formatCompactCHF(2855000),f:fmtCHF(1234.5),soll:['Aktien','Obligationen','Immobilien','Alternative','Liquiditaet']"
              ".map(function(k){var b=strategyState.allocation.buckets.filter(function(x){return x.asset_class===k;})[0];return sollPct(k,b.target_weight_bps);})}));")
    proc = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert _plain(out["r"]) == "EUR 557'896"
    assert _plain(out["s"]) == "-EUR 2"
    assert _plain(out["c"]) == "EUR 2.86 Mio."
    assert _plain(out["f"]) == "EUR 1'235"
    expected = R.apportion_bucket_bps({"equities": 6933, "bonds": 1751, "real_estate": 551, "alternatives": 563, "liquidity": 202})
    assert [_plain(v) for v in out["soll"]] == [f"{expected[k]} %" for k in ("equities", "bonds", "real_estate", "alternatives", "liquidity")]
    assert _plain(out["soll"][0]) == "69.4 %"  # Einzelrundung ergaebe 69.3 % (N-894-02)


def test_dossier_uses_bucket_apportionment_and_presentation_amounts():
    html = read_monolith_bundle()
    block = html.split("var totalTargetBps=buckets.reduce(", 1)[1].split("var allocHtml=", 1)[0]
    assert "AresRounding.bucketPctMap(buckets" in block
    assert "AresRounding.presentationAmounts(_rb.advisoryRappen,_rb.strategyBaseRappen" in block
    assert "target_amount_rappen" not in block


# --- N-894-06 ---------------------------------------------------------------

@pytest.mark.parametrize("bad", [[1000.5, 0], ["x", 0]])
def test_non_integer_inputs_rejected_in_all_three_channels(bad, tmp_path):
    with pytest.raises(ValueError):
        R.presentation_amounts(bad[0], None, [10000], ["equities"])
    with pytest.raises(ValueError):
        R.split_largest_remainder(10, [2.5, 7.5], ["a", "b"])
    _node()
    call = "presentationAmounts(" + json.dumps(bad[0]) + ",null,[10000],['equities'],2)"
    split = "presentationAmounts(1000,null,[2.5,7.5],['a','b'],2)"
    js = ("const R=require(" + json.dumps(str(CLASSIC)) + ");function t(f){try{f();return 'ok';}catch(e){return 'err';}}"
          "process.stdout.write(JSON.stringify([t(()=>R." + call + "),t(()=>R." + split + ")]));")
    proc = subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["err", "err"]
    runner = tmp_path / "r.mts"
    runner.write_text("import * as R from " + json.dumps(REACT.as_uri()) + ";\nfunction t(f: () => unknown){try{f();return 'ok';}catch{return 'err';}}\n"
                      "process.stdout.write(JSON.stringify([t(()=>R." + call + "),t(()=>R." + split + ")]));\n", encoding="utf-8")
    ts = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(runner)],
                        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert ts.returncode == 0, ts.stderr
    assert json.loads(ts.stdout) == ["err", "err"]
