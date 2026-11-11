"""G7 -- App und PDF zeigen bei identischem Input dieselben Zahlen (End-to-End).

Ein synthetisches Mandat mit Grenzfall-Gewichten (x.x5-Gleichstaende, die einzeln
gerundet 100.2 % ergaeben; halbe Franken in den Betraegen) wird

* in der App durch die echten Module ``presentation-rounding.js`` + ``aa-chart.js``
  (Legende, SOLL-Quoten, Tooltip-Daten der Torte) in Node gerendert und
* im PDF durch die echten Komponenten ``saa_bar_table`` + ``saa_donut`` in ein
  ReportLab-PDF geschrieben, dessen Text mit pypdf extrahiert wird.

Verglichen werden die Zahlen je Anlageklasse/Unterklasse (Typografie-Schicht
U+2212/U+00A0 normalisiert, Ziffern exakt). Vorher wichen App (toFixed, half-up auf
der Binaerexpansion) und PDF (Python-format, half-even) bei genau diesen Werten ab,
und beide summierten nicht auf 100.0 %.

Der Browser-Lauf (Playwright, isolierte Instanz) ist im Handoff H-153 belegt; dieser
Test ist die CI-faehige Form desselben Vergleichs.
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
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate

from services.pdf.components.saa_bar_table import make_saa_bar_table
from services.pdf.components.saa_donut import make_saa_donut_with_legend
from services.pdf.styles import asset_class_label

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "ares-desktop" / "frontend"

ALLOCATION_BPS = {"equities": 3335, "bonds": 2525, "real_estate": 1995, "alternatives": 1225, "liquidity": 920}
AMOUNTS_RAPPEN = {"equities": 66700050, "bonds": 50500050, "real_estate": 39900150, "alternatives": 24500250, "liquidity": 18400000}
SUBS = {
    "equities": {"Aktien Schweiz": 1665, "Aktien Welt": 1670},
    "bonds": {"Obligationen CHF": 1265, "Obligationen Global": 1260},
}
EXPECTED_CLASS = {"equities": "33.4 %", "bonds": "25.3 %", "real_estate": "19.9 %", "alternatives": "12.2 %", "liquidity": "9.2 %"}
EXPECTED_SUB = {"Aktien Schweiz": "16.7 %", "Aktien Welt": "16.7 %", "Obligationen CHF": "12.7 %", "Obligationen Global": "12.6 %"}
EXPECTED_AMOUNT = {"equities": "CHF 667'001", "bonds": "CHF 505'001", "real_estate": "CHF 399'002",
                   "alternatives": "CHF 245'003", "liquidity": "CHF 184'000"}


def _plain(text: str) -> str:
    return text.replace("−", "-").replace(" ", " ")


def _app_values() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    items = [{
        "name": asset_class_label(key), "key": {"equities": "eq", "bonds": "bd", "real_estate": "re",
                                                 "alternatives": "alt", "liquidity": "liq"}[key],
        "bps": bps, "color": "#000000", "amountChf": AMOUNTS_RAPPEN[key] / 100,
        "subs": [{"name": n, "bps": b} for n, b in SUBS.get(key, {}).items()],
    } for key, bps in ALLOCATION_BPS.items()]
    script = (
        (FRONTEND / "presentation-rounding.js").read_text(encoding="utf-8")
        + "\nvar window={};var document={documentElement:{},querySelectorAll:function(){return [];},getElementById:function(){return null;}};"
        + "function getComputedStyle(){return {getPropertyValue:function(){return '#ffffff';}};}\n"
        + (FRONTEND / "aa-chart.js").read_text(encoding="utf-8")
        + "\nvar items=" + json.dumps(items) + ";"
        + "var rows=aaChartPrepare(items);var ds=aaChartDonutDatasets(rows,'#FFFFFF');"
        + "process.stdout.write(JSON.stringify({rows:rows.map(function(r){return {name:r.name,pct:r.pct,subs:r.subs.map(function(s){return [s.name,s.pct];})};}),"
        + "legend:aaChartLegendHtml(items,null),quota:aaChartQuotaHtml(items.map(function(i){i.expanded=true;return i;})),"
        + "tooltipAmounts:ds[ds.length-1]._aaAmt}));"
    )
    proc = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _pdf_text() -> str:
    products = [{"asset_class": key, "sub_asset_class": name, "target_weight_bps": bps}
                for key, subs in SUBS.items() for name, bps in subs.items()]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = list(make_saa_bar_table(ALLOCATION_BPS, bucket_amounts_rappen=AMOUNTS_RAPPEN, base_currency="CHF"))
    story.append(make_saa_donut_with_legend(ALLOCATION_BPS, products=products))
    doc.build(story)
    reader = PdfReader(io.BytesIO(buf.getvalue()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _pdf_value_after(text: str, label: str, pattern: str) -> list[str]:
    return re.findall(re.escape(label) + r"\s+(" + pattern + r")", text)


def test_app_and_pdf_show_identical_class_sub_and_amount_values():
    app = _app_values()
    text = _pdf_text()
    pct = r"-?\d[\d']*\.\d %"
    by_label = {asset_class_label(k): k for k in ALLOCATION_BPS}
    # App: Klassen + Unterklassen.
    app_class = {by_label[r["name"]]: _plain(r["pct"]) for r in app["rows"]}
    app_sub = {name: _plain(p) for r in app["rows"] for name, p in r["subs"]}
    assert app_class == EXPECTED_CLASS
    assert app_sub == EXPECTED_SUB
    # PDF: jede Klasse erscheint in Tabelle und Legende mit demselben Wert.
    for key, expected in EXPECTED_CLASS.items():
        found = _pdf_value_after(text, asset_class_label(key), pct)
        assert found and set(found) == {expected}, (key, found)
    for name, expected in EXPECTED_SUB.items():
        found = re.findall(re.escape(name) + r"\s+(" + pct + r")", text)
        assert found == [expected], (name, found)
    # Summen: App und PDF exakt 100.0 %.
    assert sum(round(float(v[:-2]) * 10) for v in app_class.values()) == 1000
    assert "100.0 %" in text and "100.2 %" not in text
    # Betraege (halbe Franken): App-Tooltip == PDF-Tabelle == Half-up.
    app_amounts = dict(zip([by_label[r["name"]] for r in app["rows"]], app["tooltipAmounts"]))
    for key, expected in EXPECTED_AMOUNT.items():
        assert _plain(app_amounts[key]) == expected, key
        assert expected in text, (key, expected)


def test_app_legend_and_quota_render_the_same_numbers_without_rounding_note():
    app = _app_values()
    legend = _plain(html_lib.unescape(app["legend"]))
    quota = _plain(html_lib.unescape(app["quota"]))
    for value in list(EXPECTED_CLASS.values()) + list(EXPECTED_SUB.values()):
        assert value in quota, value
    for value in EXPECTED_CLASS.values():
        assert value in legend, value
    for amount in EXPECTED_AMOUNT.values():
        assert amount in legend, amount
    assert "Rundungsdifferenzen" not in legend + quota


def test_legacy_individual_rounding_would_have_diverged():
    """Rueckname-Gegenprobe im Test: die alte Einzelrundung beider Kanaele haette
    hier andere Zahlen und keine 100.0 % geliefert (Begruendung der Goldens)."""
    legacy_pdf = {k: f"{v / 100:.1f}" for k, v in ALLOCATION_BPS.items()}
    assert legacy_pdf == {"equities": "33.4", "bonds": "25.2", "real_estate": "19.9",
                          "alternatives": "12.2", "liquidity": "9.2"}  # half-even auf Binaerwert
    assert round(sum(float(v) for v in legacy_pdf.values()), 1) != 100.0 or legacy_pdf["bonds"] != "25.3"
    assert f"{667000.5:,.0f}" == "667,000"  # Banker's Rounding: CHF 667'000 statt 667'001
