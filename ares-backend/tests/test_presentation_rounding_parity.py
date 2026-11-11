"""G7 -- gemeinsamer Rundungsformatter: Python (PDF) == Classic-App == React.

Vertrag: ``services/presentation_rounding.py`` (Policy ``ares-rounding/1``).
Die drei Implementierungen werden hier

1. gegen den von Hand gesetzten Golden-Vektor
   ``services/presentation_rounding_golden.json`` (beide Typografien) und
2. gegeneinander ueber den vollen Wertebereich (alle ganzen bps -10000..10000
   mit 0/1/2 Nachkommastellen, Geldbetraege, kompakte Betraege und
   deterministisch gezogene Apportionierungsfaelle)

geprueft. Weicht eine Seite in einem einzigen Zeichen ab, ist der Test rot.
Zusaetzlich ein unabhaengiges Orakel (direkte Decimal-Rechnung) fuer Prozent
und die Summenerhaltung.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from services import presentation_rounding as R

ROOT = Path(__file__).resolve().parents[2]
CLASSIC = ROOT / "ares-desktop" / "frontend" / "presentation-rounding.js"
REACT = ROOT / "ares-desktop" / "frontend" / "reporting" / "src" / "lib" / "presentationRounding.ts"
HTML = ROOT / "ares-desktop" / "frontend" / "ares.html"
GOLDEN = R.GOLDEN_PATH

NB, MI = " ", "−"


def _cross_cases() -> list[list]:
    """Gemeinsame Fallliste fuer den Kanalvergleich (deterministisch)."""
    cases: list[list] = []
    for d in (0, 1, 2):
        for b in range(-10000, 10001):
            cases.append(["percent_bps", [b, d]])
    for b in range(-2000, 2001, 5):
        cases.append(["signed_percent_bps", [b, 1]])
    for v in (0, 0.05, 0.15, 0.25, 12.35, 99.95, -12.25, 1.005, 2.675, 73.5, 72.5, 99.5, 0.5):
        cases.append(["percent", [v, 1]])
        cases.append(["percent", [v, 2]])
        cases.append(["probability_pct", [v]])
    rng = random.Random(20261111)
    for minor in list(range(-1000, 1001, 7)) + [rng.randint(-10**12, 10**12) for _ in range(400)] + [250, 150, -150, -250, 50, -50]:
        cases.append(["money_minor", [minor, "CHF", 2, 0]])
        cases.append(["money_minor", [minor, "EUR", 2]])
        cases.append(["signed_money_minor", [minor, "CHF", 2, 0]])
        cases.append(["money_compact_minor", [minor * 1000, "CHF", 2]])
    cases.append(["money_minor", [rng.randint(-10**6, 10**6), "JPY", 0]])
    for _ in range(300):
        n = rng.randint(1, 7)
        cuts = sorted(rng.randint(0, 10000) for _ in range(n - 1))
        parts = [b - a for a, b in zip([0] + cuts, cuts + [10000])]
        cases.append(["apportion_percent_bps", [parts, rng.choice([0, 1, 2])]])
    # Unterklassen auf einen angezeigten Klassenwert (Ziel = floor oder ceil der Summe).
    for _ in range(200):
        n = rng.randint(1, 5)
        subs = [rng.randint(0, 3000) for _ in range(n)]
        total = sum(subs)
        floor_units = total // 10
        target = Decimal(floor_units + (1 if total % 10 and rng.random() < 0.5 else 0)) / 10
        cases.append(["apportion_percent_bps", [subs, 1, str(target)]])
    return cases


def _python(cases, typography):
    return [R.run_case(fn, args, typography) for fn, args in cases]


def _need_node():
    if shutil.which("node") is None:
        pytest.skip("node not available")


def _run_classic(cases, typography, tmp_path):
    _need_node()
    script = tmp_path / "classic.js"
    script.write_text(
        "const R=require(" + json.dumps(str(CLASSIC)) + ");\n"
        "const fs=require('fs');const C=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));\n"
        "process.stdout.write(JSON.stringify({policy:R.POLICY_VERSION,out:C.map(c=>R.runCase(c[0],c[1]," + json.dumps(typography) + "))}));\n",
        encoding="utf-8",
    )
    data = tmp_path / "cases.json"
    data.write_text(json.dumps(cases), encoding="utf-8")
    proc = subprocess.run(["node", str(script), str(data)], capture_output=True, text=True, encoding="utf-8", timeout=240)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _run_react(cases, typography, tmp_path):
    _need_node()
    script = tmp_path / "react.mts"
    script.write_text(
        "import * as R from " + json.dumps(REACT.as_uri()) + ";\n"
        "import { readFileSync } from 'node:fs';\n"
        "const C = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        "process.stdout.write(JSON.stringify({policy: R.POLICY_VERSION, out: C.map((c: [string, unknown[]]) => R.runCase(c[0], c[1], "
        + json.dumps(typography) + "))}));\n",
        encoding="utf-8",
    )
    data = tmp_path / "cases.json"
    data.write_text(json.dumps(cases), encoding="utf-8")
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(script), str(data)],
        capture_output=True, text=True, encoding="utf-8", timeout=240,
    )
    if proc.returncode != 0 and "strip-types" in proc.stderr:
        pytest.skip("Node ohne Type-Stripping")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _golden_cases():
    return [[c["fn"], c["args"]] for c in _golden()["cases"]]


# ---------------------------------------------------------------------------
# 1) Golden-Vektor (von Hand gesetzt) -- alle drei Kanaele, beide Typografien
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typography", ["plain", "screen"])
def test_python_matches_golden(typography):
    g = _golden()
    assert g["policy_version"] == R.ROUNDING_POLICY_VERSION
    got = _python(_golden_cases(), typography)
    expected = [c[typography] for c in g["cases"]]
    diffs = [(c["id"], a, b) for c, a, b in zip(g["cases"], got, expected) if a != b]
    assert diffs == []


@pytest.mark.parametrize("typography", ["plain", "screen"])
def test_classic_matches_golden(typography, tmp_path):
    g = _golden()
    res = _run_classic(_golden_cases(), typography, tmp_path)
    assert res["policy"] == g["policy_version"]
    diffs = [(c["id"], a, c[typography]) for c, a in zip(g["cases"], res["out"]) if a != c[typography]]
    assert diffs == []


@pytest.mark.parametrize("typography", ["plain", "screen"])
def test_react_matches_golden(typography, tmp_path):
    g = _golden()
    res = _run_react(_golden_cases(), typography, tmp_path)
    assert res["policy"] == g["policy_version"]
    diffs = [(c["id"], a, c[typography]) for c, a in zip(g["cases"], res["out"]) if a != c[typography]]
    assert diffs == []


def test_golden_covers_release_gate_boundaries():
    """G7-Auflage: ...25 / ...5 bps, 0.05 %, 99.95 %, Summenerhaltung, CHF/Fremdwaehrung,
    negative Werte, Null vs. keine Angabe."""
    ids = {c["id"] for c in _golden()["cases"]}
    for required in (
        "percent_1225_bps_1dp", "percent_negative_1225_bps_1dp", "percent_1235_bps_1dp",
        "percent_5_bps_1dp", "percent_9995_bps_1dp", "percent_25_bps_1dp", "weights_sum",
        "apportion_three_thirds", "apportion_tie_canonical_order", "apportion_subs_to_class_display",
        "chf_minor", "usd_minor", "jpy_minor", "chf_whole_250_rappen", "chf_whole_negative_150_rappen",
        "percent_zero_bps_1dp", "percent_none", "chf_whole_zero", "chf_none",
    ):
        assert required in ids, required
    vectors = R.golden_vectors()
    assert vectors["percent_1225_bps_1dp"] == "12.3 %"
    assert vectors["percent_negative_1225_bps_1dp"] == "-12.3 %"
    assert vectors["weights_sum"] == "100.0 %"
    assert vectors["chf_minor"] == "CHF 10.05"
    assert vectors["usd_minor"] == "USD -10.05"


# ---------------------------------------------------------------------------
# 2) Kanalvergleich ueber den vollen Wertebereich
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typography", ["plain", "screen"])
def test_classic_and_react_equal_python_on_full_range(typography, tmp_path):
    cases = _cross_cases()
    py = _python(cases, typography)
    classic = _run_classic(cases, typography, tmp_path)["out"]
    react = _run_react(cases, typography, tmp_path)["out"]
    d1 = [(c, a, b) for c, a, b in zip(cases, py, classic) if a != b]
    d2 = [(c, a, b) for c, a, b in zip(cases, py, react) if a != b]
    assert d1 == [], d1[:5]
    assert d2 == [], d2[:5]
    assert len(cases) > 60000


def test_typographies_differ_only_in_minus_and_percent_space():
    cases = _cross_cases()[:30003]
    for plain, screen in zip(_python(cases, "plain"), _python(cases, "screen")):
        if isinstance(plain, list):
            continue
        assert screen.replace(MI, "-").replace(NB + "%", " %") == plain


# ---------------------------------------------------------------------------
# 3) Unabhaengiges Orakel
# ---------------------------------------------------------------------------

def _oracle_pct(bps: int, d: int) -> str:
    q = (Decimal(bps) / 100).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    neg = q < 0
    text = f"{abs(q):,.{d}f}".replace(",", "'")
    return ("-" if neg else "") + text + " %"


def test_percent_matches_independent_decimal_oracle():
    for d in (0, 1, 2):
        for b in range(-10000, 10001):
            assert R.format_percent_bps(b, d) == _oracle_pct(b, d), (b, d)


def test_apportionment_preserves_sum_and_is_never_more_than_one_unit_off():
    rng = random.Random(7)
    for _ in range(2000):
        n = rng.randint(1, 8)
        cuts = sorted(rng.randint(0, 10000) for _ in range(n - 1))
        parts = [b - a for a, b in zip([0] + cuts, cuts + [10000])]
        shown = R.apportion_percent_bps(parts, 1)
        assert sum(shown) == Decimal("100.0")
        for raw, disp in zip(parts, shown):
            exact = Decimal(raw) / 100
            assert abs(disp - exact) < Decimal("0.1"), (parts, shown)
            if raw == 0:
                assert disp == 0


def test_sub_apportionment_sums_to_displayed_class_value():
    rng = random.Random(11)
    for _ in range(500):
        classes = {k: rng.randint(0, 5000) for k in R.CANONICAL_ASSET_CLASS_ORDER}
        shown = R.apportion_bucket_bps(classes)
        for key, bps in classes.items():
            if bps <= 0:
                continue
            subs = {f"S{i}": rng.randint(0, bps) for i in range(rng.randint(1, 4))}
            total = sum(subs.values())
            if total > bps:
                continue
            sub_shown = R.apportion_sub_bps(shown[key], subs, bps)
            if total == bps:
                assert sum(sub_shown.values()) == shown[key]
            else:
                assert sum(sub_shown.values()) <= shown[key]


def test_negative_weights_are_not_apportioned():
    with pytest.raises(ValueError):
        R.apportion_percent_bps([12000, -2000], 1)


# ---------------------------------------------------------------------------
# 4) Verdrahtung
# ---------------------------------------------------------------------------

def test_monolith_loads_rounding_module_before_inline_script_and_chart():
    html = HTML.read_text(encoding="utf-8")
    tag = '<script src="./presentation-rounding.js"></script>'
    assert html.count(tag) == 1
    assert html.index(tag) < html.index('<script src="./aa-chart.js"></script>')
    assert html.index(tag) < html.index("function fmtPct(")


def test_policy_version_is_identical_in_all_three_sources():
    classic = CLASSIC.read_text(encoding="utf-8")
    react = REACT.read_text(encoding="utf-8")
    assert f"'{R.ROUNDING_POLICY_VERSION}'" in classic
    assert f"'{R.ROUNDING_POLICY_VERSION}'" in react


def test_artifact_rows_carry_raw_unit_policy_and_display():
    row = R.presentation_artifact(1225, "bps", R.format_percent_bps(1225))
    assert row == {"raw": 1225, "unit": "bps", "policy_version": "ares-rounding/1", "display": "12.3 %"}
