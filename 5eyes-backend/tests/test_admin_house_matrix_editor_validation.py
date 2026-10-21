"""ADMIN-HOUSE-MATRIX-PERCENT-001: Admin-Hausmatrix-/Policy-Editor in Prozent.

Der Editor (Admin -> "House-Matrix & Optimizer-Policy") arbeitete in
Basispunkten (``type=number``, "Werte in bps") und pruefte nur
min<=Ziel<=max sowie die Zielsumme -- weder die Aktien-Mindestquote noch
die Bereichsgrenzen noch die Abdeckung, und die Aktien-Mindestquote war
gar nicht editierbar.

Diese Tests fuehren die ECHTEN Monolith-Funktionen in Node aus:

* ``adminPolicyParsePercentInput`` / ``adminPolicyFormatPercentInput``:
  Prozent <-> bps exakt (Roundtrip ueber alle 10'001 Werte, keine Rundung).
* ``computeAdminPolicyValidation``: fuer viele Szenarien dieselbe
  Entscheidung wie das Backend -- ``schemaValid`` == Pydantic
  ``HouseMatrixRowsReplace`` (PUT .../house-matrix, 422), ``valid`` ==
  Schema UND Engine (``_baseline_target_bands`` + ``_rebalance_to_total``)
  fuer jede Zeile.
* Wiring: Raster rendert Prozent-Textfelder, Fehler landen am Feld,
  Speichern/Aktivieren sind gesperrt, der PUT-Body ist in bps.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"

PREFIXES = ("liq", "bonds", "equity", "real_estate", "alt")
FIELDS = [f"{p}_{s}_bps" for p in PREFIXES for s in ("min", "target", "max")] + [
    "equity_minimum_bps",
    "max_risky_fraction_bps",
]
DEFAULT_POLICY = {"max_real_estate_bps": 2000, "max_alternatives_bps": 1000, "min_liquidity_bps": 0}


def _function(src: str, signature: str) -> str:
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _var(src: str, name: str) -> str:
    start = src.index("var " + name + " =")
    eq = src.index("=", start)
    open_idx = min(i for i in (src.find("[", eq), src.find("{", eq)) if i >= 0)
    pairs = {"[": "]", "{": "}"}
    opener, closer = src[open_idx], pairs[src[open_idx]]
    depth, j = 1, open_idx + 1
    while depth:
        depth += 1 if src[j] == opener else -1 if src[j] == closer else 0
        j += 1
    end = src.index(";", j)
    return src[start : end + 1]


VALIDATOR_FUNCS = (
    "function normalizeNumberInputCH(",
    "function fmtNumber(",
    "function fmtPct(",
    "function escapeHtml(",
    "function adminPolicyFieldList(",
    "function adminPolicyFormatPercentInput(",
    "function adminPolicyParsePercentInput(",
    "function computeAdminPolicyValidation(",
)
VALIDATOR_VARS = (
    "ADMIN_POLICY_BUCKETS",
    "ADMIN_POLICY_EXTRA_FIELDS",
    "ADMIN_POLICY_SUB_LABELS",
    "ADMIN_POLICY_DEFAULT_RISKY_BPS",
)


def _node(script_body: str, extra_funcs: tuple[str, ...] = (), extra_vars: tuple[str, ...] = ()) -> object:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    parts = [_var(src, v) for v in VALIDATOR_VARS + extra_vars]
    parts += [_function(src, f) for f in VALIDATOR_FUNCS + extra_funcs]
    script = "\n".join(parts) + "\n" + script_body
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    try:
        res = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        Path(path).unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _pct(bps: int) -> str:
    """Unabhaengige Python-Formatierung bps -> Prozenttext (exakt)."""
    return format((Decimal(bps) / 100).normalize(), "f")


def _default_rows() -> list[dict]:
    from services.house_matrix_loader import _HARDCODED_FALLBACK

    rows = []
    for t in _HARDCODED_FALLBACK:
        (sf, st, name, lmn, ltg, lmx, bmn, btg, bmx, emn, etg, emx, rmn, rtg, rmx, amn, atg, amx, risky, eqmin) = t
        rows.append({
            "score_from": sf, "score_to": st, "profile_name": name,
            "liq_min_bps": lmn, "liq_target_bps": ltg, "liq_max_bps": lmx,
            "bonds_min_bps": bmn, "bonds_target_bps": btg, "bonds_max_bps": bmx,
            "equity_min_bps": emn, "equity_target_bps": etg, "equity_max_bps": emx,
            "real_estate_min_bps": rmn, "real_estate_target_bps": rtg, "real_estate_max_bps": rmx,
            "alt_min_bps": amn, "alt_target_bps": atg, "alt_max_bps": amx,
            "equity_minimum_bps": eqmin, "max_risky_fraction_bps": risky,
        })
    return rows


def _valid_rows() -> list[dict]:
    """Ausgelieferte Default-Zeilen -- seit CIO-Entscheid 1 alle schema-gueltig
    (siehe ``test_all_shipped_default_rows_are_schema_valid``)."""
    return _default_rows()


def _as_inputs(rows: list[dict], overrides: dict | None = None) -> list[dict]:
    """rows (bps) -> Editor-Eingaben; overrides: {(rowIdx, field): raw_text}."""
    out = []
    for idx, row in enumerate(rows):
        values = {f: _pct(row[f]) for f in FIELDS}
        for (ri, field), raw in (overrides or {}).items():
            if ri == idx and field in values:
                values[field] = raw
        out.append({"score_from": row["score_from"], "score_to": row["score_to"],
                    "profile_name": row["profile_name"], "values": values})
    return out


def _validate(cases: list[dict]) -> list[dict]:
    body = (
        "var CASES=" + json.dumps(cases) + ";\n"
        "console.log(JSON.stringify(CASES.map(function(c){"
        "var r=computeAdminPolicyValidation(c.rows,c.policy);"
        "return {valid:r.valid,schemaValid:r.schemaValid,payloadRows:r.payloadRows,globalErrors:r.globalErrors,"
        "rows:r.rows.map(function(x){return {fieldErrors:x.fieldErrors,errors:x.errors,hints:x.hints,"
        "valid:x.valid,schemaValid:x.schemaValid,targetSum:x.targetSum,effMinSum:x.effMinSum,effMaxSum:x.effMaxSum,"
        "riskyEstimateBps:x.riskyEstimateBps};})};})));"
    )
    return _node(body)


def _schema_accepts(rows: list[dict]) -> bool:
    from pydantic import ValidationError

    from schemas.allocation import HouseMatrixRowsReplace

    try:
        HouseMatrixRowsReplace(rows=rows)
    except ValidationError:
        return False
    return True


def _feasibility_accepts(rows: list[dict], policy: dict) -> bool:
    """Server-Gate (POST .../activate) -- die Python-Funktion, die der JS-Validator spiegelt."""
    from services.house_matrix_feasibility import policy_activation_violations

    return not policy_activation_violations([SimpleNamespace(**r) for r in rows], SimpleNamespace(**policy))


def _engine_accepts(rows: list[dict], policy: dict) -> bool:
    from services.portfolio_engine_house_matrix import _baseline_target_bands, _rebalance_to_total

    pol = SimpleNamespace(**policy)
    for row in rows:
        try:
            targets, minimums, maximums = _baseline_target_bands(SimpleNamespace(**row), pol)
            _rebalance_to_total(targets, minimums, maximums)
        except ValueError:
            return False
    return True


# ---------------------------------------------------------------- Umrechnung

def test_percent_bps_roundtrip_is_exact_for_every_bps_value():
    out = _node(
        "var bad=[];for(var b=0;b<=10000;b++){var t=adminPolicyFormatPercentInput(b);"
        "var p=adminPolicyParsePercentInput(t);if(!p.ok||p.bps!==b)bad.push([b,t,p]);}"
        "console.log(JSON.stringify(bad));"
    )
    assert out == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12.5", 1250), ("12,5", 1250), ("12.34", 1234), ("12.340", 1234), ("0.01", 1),
        ("0.1", 10), ("65 %", 6500), ("65%", 6500), ("100", 10000), ("100.00", 10000),
        ("0", 0), (" 7 ", 700), ("4.35", 435), ("16.65", 1665), ("57.05", 5705),
    ],
)
def test_parse_accepts_percent_without_rounding(raw, expected):
    out = _node("console.log(JSON.stringify(adminPolicyParsePercentInput(" + json.dumps(raw) + ")));")
    assert out == {"ok": True, "bps": expected}


@pytest.mark.parametrize(
    "raw,code",
    [
        ("12.345", "precision"), ("0.005", "precision"), ("100.01", "range"), ("101", "range"),
        ("1'000", "range"), ("-1", "format"), ("−1", "format"), ("abc", "format"),
        ("1e2", "format"), ("", "empty"), ("   ", "empty"), ("6500 bps", "format"),
    ],
)
def test_parse_rejects_instead_of_silently_rounding(raw, code):
    out = _node("console.log(JSON.stringify(adminPolicyParsePercentInput(" + json.dumps(raw) + ")));")
    assert out["ok"] is False and out["code"] == code


def test_default_risky_fractions_mirror_backend_constant():
    from services.optimizer.constraints import DEFAULT_BUCKET_RISKY_FRACTION

    out = _node("console.log(JSON.stringify(ADMIN_POLICY_DEFAULT_RISKY_BPS));")
    mapping = {"liq": "liquidity", "bonds": "bonds", "equity": "equities",
               "real_estate": "real_estate", "alt": "alternatives"}
    assert {k: out[k] for k in mapping} == {
        k: round(DEFAULT_BUCKET_RISKY_FRACTION[v] * 10000) for k, v in mapping.items()
    }


# ---------------------------------------------- Validator = Backend-Entscheid

def _named_cases() -> list[tuple[str, list[dict], dict, dict]]:
    base = _valid_rows()
    # Zeile 3 = Score 5-6 "Ausgewogen": liq 0/200/300, bonds 2500/3500/4500,
    # equity 4000/4800/5500, RE 500/1000/2000, alt 300/500/800, cap 6000.
    cases = [
        ("defaults_valid", base, DEFAULT_POLICY, {}),
        ("target_above_max", base, DEFAULT_POLICY, {(3, "equity_target_bps"): "56"}),
        ("min_above_max", base, DEFAULT_POLICY, {(3, "bonds_min_bps"): "46"}),
        ("target_sum_off", base, DEFAULT_POLICY, {(3, "liq_target_bps"): "3"}),
        ("target_sum_within_tolerance", base, DEFAULT_POLICY, {(3, "liq_target_bps"): "2.05"}),
        ("target_sum_just_outside_tolerance", base, DEFAULT_POLICY, {(3, "liq_target_bps"): "2.06"}),
        ("equity_minimum_above_equity_max", base, DEFAULT_POLICY, {(3, "equity_minimum_bps"): "56"}),
        # Schema ok (<= Aktien-Max), Engine: wirksame Minima 0+2500+5500+500+300 = 88 % -> ok
        ("equity_minimum_above_target_hint_only", base, DEFAULT_POLICY, {(3, "equity_minimum_bps"): "55"}),
        ("risky_above_100", base, DEFAULT_POLICY, {(3, "max_risky_fraction_bps"): "100.5"}),
        ("three_decimals", base, DEFAULT_POLICY, {(3, "alt_target_bps"): "5.001"}),
        ("empty_field", base, DEFAULT_POLICY, {(3, "alt_max_bps"): ""}),
        ("comma_decimal_valid", base, DEFAULT_POLICY, {(3, "liq_target_bps"): "2,00"}),
        ("risk_budget_low_hint_only", base, DEFAULT_POLICY, {(3, "max_risky_fraction_bps"): "40"}),
    ]
    # Engine-only (Schema akzeptiert): Summe der Minima > 100 % ueber die
    # Aktien-Mindestquote. Zeile 3: Minima 0+2500+4000+500+300; Aktien-Min
    # 4000 -> Mindestquote 5500 hebt auf 8800; dazu bonds_min 4000 -> 10300.
    eng = [dict(r) for r in base]
    eng[3].update(bonds_min_bps=3500, bonds_target_bps=3500, equity_minimum_bps=5500, liq_min_bps=200,
                  real_estate_min_bps=1000, alt_min_bps=500)
    cases.append(("engine_min_sum_over_100_via_equity_minimum", eng, DEFAULT_POLICY, {}))
    # Engine-only: Zielsumme 99.95 % (Schema-Toleranz), Maxima genau 99.95 %.
    tight = [dict(r) for r in base]
    tight[0].update(liq_min_bps=0, liq_target_bps=300, liq_max_bps=300, bonds_target_bps=9195,
                    bonds_max_bps=9195, alt_target_bps=500, alt_max_bps=500)
    cases.append(("engine_max_sum_below_100_within_schema_tolerance", tight, DEFAULT_POLICY, {}))
    # Engine-only via Policy: Alternative-Cap 0 senkt die Maxima der Zeile 0
    # (liq 800 + bonds 9500 + alt 500) -- erst ein enger Bonds-Max kippt es.
    cap = [dict(r) for r in base]
    cap[0].update(bonds_max_bps=9200, liq_max_bps=300)
    cases.append(("engine_policy_alt_cap_zero", cap, {"max_real_estate_bps": 2000, "max_alternatives_bps": 0,
                                                       "min_liquidity_bps": 0}, {}))
    # Policy-Liquiditaetsminimum hebt die Minima ueber 100 %.
    cases.append(("engine_policy_liquidity_floor", base, {"max_real_estate_bps": 2000, "max_alternatives_bps": 1000,
                                                           "min_liquidity_bps": 4000}, {}))
    # Policy-Caps NULL = nicht gesetzt.
    cases.append(("policy_caps_unset", base, {"max_real_estate_bps": None, "max_alternatives_bps": None,
                                               "min_liquidity_bps": None}, {}))
    # Abdeckung: Zeile entfernt -> Luecke.
    cases.append(("coverage_gap", base[:2] + base[3:], DEFAULT_POLICY, {}))
    long_name = [dict(r) for r in base]
    long_name[1]["profile_name"] = "x" * 81
    cases.append(("profile_name_too_long", long_name, DEFAULT_POLICY, {}))
    empty_name = [dict(r) for r in base]
    empty_name[1]["profile_name"] = ""
    cases.append(("profile_name_empty", empty_name, DEFAULT_POLICY, {}))
    return cases


def _random_cases(n: int, seed: int = 20261021) -> list[tuple[str, list[dict], dict, dict]]:
    rng = random.Random(seed)
    base = _valid_rows()
    policies = [DEFAULT_POLICY,
                {"max_real_estate_bps": None, "max_alternatives_bps": None, "min_liquidity_bps": None},
                {"max_real_estate_bps": 0, "max_alternatives_bps": 0, "min_liquidity_bps": 0},
                {"max_real_estate_bps": 1000, "max_alternatives_bps": 300, "min_liquidity_bps": 1500}]
    out = []
    for k in range(n):
        rows = [dict(r) for r in base]
        ri = rng.randrange(len(rows))
        for _ in range(rng.randint(1, 3)):
            field = rng.choice(FIELDS)
            cur = rows[ri][field]
            rows[ri][field] = max(0, min(10000, rng.choice([
                0, 10000, cur + 1, cur - 1, cur + 5, cur - 5, cur + 6, cur - 6,
                cur + 500, cur - 500, rng.randint(0, 10000),
            ])))
        out.append((f"random_{k}", rows, rng.choice(policies), {}))
    return out


def _run_parity(cases):
    payload = [{"rows": _as_inputs(rows, ov), "policy": pol} for _, rows, pol, ov in cases]
    results = _validate(payload)
    decided = []
    for (name, rows, pol, ov), res in zip(cases, results):
        # Was der Editor aus den Eingaben macht (fuer Schema/Engine in bps):
        sent_rows = []
        parse_ok = True
        for idx, row in enumerate(rows):
            r = dict(row)
            for (ri, field), raw in ov.items():
                if ri == idx:
                    txt = raw.replace(",", ".").replace("%", "").strip()
                    try:
                        dec = Decimal(txt)
                    except Exception:
                        parse_ok = False
                        continue
                    if dec != dec.quantize(Decimal("0.01")) or dec < 0:
                        parse_ok = False
                        continue
                    r[field] = int(dec * 100)
            sent_rows.append(r)
        schema = parse_ok and _schema_accepts(sent_rows)
        engine = schema and _engine_accepts(sent_rows, pol)
        if schema:
            # Server-Gate == tatsaechliches Engine-Verhalten.
            assert _feasibility_accepts(sent_rows, pol) == engine, name
            from services.house_matrix_feasibility import house_matrix_row_feasibility

            for js_row, row in zip(res["rows"], sent_rows):
                py = house_matrix_row_feasibility(SimpleNamespace(**row), SimpleNamespace(**pol))
                assert (js_row["effMinSum"], js_row["effMaxSum"]) == (
                    py["effective_min_sum_bps"], py["effective_max_sum_bps"]), name
        assert res["schemaValid"] == schema, (name, res)
        assert res["valid"] == engine, (name, res)
        if res["valid"]:
            assert res["payloadRows"] == sent_rows, name
        else:
            assert res["payloadRows"] is None, name
        decided.append((name, schema, engine, res))
    return decided


def test_named_scenarios_match_schema_and_engine_decision():
    decided = {name: (schema, engine, res) for name, schema, engine, res in _run_parity(_named_cases())}
    # Die Szenarien decken alle drei Ausgaenge ab.
    assert decided["defaults_valid"][:2] == (True, True)
    assert decided["engine_min_sum_over_100_via_equity_minimum"][:2] == (True, False)
    assert decided["engine_max_sum_below_100_within_schema_tolerance"][:2] == (True, False)
    assert decided["engine_policy_liquidity_floor"][:2] == (True, False)
    assert decided["target_sum_within_tolerance"][:2] == (True, True)
    assert decided["target_sum_just_outside_tolerance"][0] is False
    assert decided["equity_minimum_above_target_hint_only"][:2] == (True, True)


def test_random_scenarios_match_schema_and_engine_decision():
    decided = _run_parity(_random_cases(400))
    outcomes = {(s, e) for _, s, e, _ in decided}
    # Stichprobe deckt gueltig, Schema-Fehler und Engine-Fehler ab.
    assert (True, True) in outcomes and (False, False) in outcomes and (True, False) in outcomes


# ---------------------------------------------------- Fehler am richtigen Feld

def _row3(cases):
    res = _validate([{"rows": _as_inputs(_valid_rows(), ov), "policy": DEFAULT_POLICY} for ov in cases])
    return [r["rows"][3] for r in res]


def test_errors_are_attached_to_the_offending_field():
    target, minmax, eqmin, fmt, risky = _row3([
        {(3, "equity_target_bps"): "56"},
        {(3, "bonds_min_bps"): "46"},
        {(3, "equity_minimum_bps"): "56"},
        {(3, "alt_target_bps"): "5.001"},
        {(3, "max_risky_fraction_bps"): "100.5"},
    ])
    assert "equity_target_bps" in target["fieldErrors"]
    assert any(e.startswith("Aktien Ziel: muss zwischen") for e in target["errors"])
    assert "40.00 %" in target["fieldErrors"]["equity_target_bps"]
    assert {"bonds_min_bps", "bonds_max_bps"} <= set(minmax["fieldErrors"])
    assert set(eqmin["fieldErrors"]) == {"equity_minimum_bps"}
    assert set(fmt["fieldErrors"]) == {"alt_target_bps"}
    assert "zwei Nachkommastellen" in fmt["fieldErrors"]["alt_target_bps"]
    assert set(risky["fieldErrors"]) == {"max_risky_fraction_bps"}


def test_target_sum_error_marks_all_target_fields_and_reports_percent():
    (row,) = _row3([{(3, "liq_target_bps"): "3"}])
    assert {f"{p}_target_bps" for p in PREFIXES} <= set(row["fieldErrors"])
    assert any("Summe der Ziele 101.00 %" in e for e in row["errors"])


def test_hints_do_not_block():
    eqmin, risky = _row3([
        {(3, "equity_minimum_bps"): "55"},
        {(3, "max_risky_fraction_bps"): "40"},
    ])
    assert eqmin["valid"] and eqmin["errors"] == [] and any("hebt das Aktien-Ziel an" in h for h in eqmin["hints"])
    assert risky["valid"] and any("Risikobudget" in h for h in risky["hints"])
    # 4800*.8 + 3500*.25 + 1000*.6 + 500*.6 + 200*0 = 3840+875+600+300 = 5615 bps
    assert risky["riskyEstimateBps"] == pytest.approx(5615)


def _runtime_seed_tuples() -> list[tuple]:
    """Roh-Tupel der Runtime-Seeds in services/portfolio_engine.py (vor der
    Normalisierung), direkt aus dem Quelltext gelesen."""
    import ast

    src = (REPO_ROOT / "5eyes-backend" / "services" / "portfolio_engine.py").read_text(encoding="utf-8")
    body = _function(src, "def _ensure_runtime_reference_data_ch(")
    start = body.index("_normalize_house_matrix_defaults([")
    end = body.index("])", start)
    return list(ast.literal_eval("[" + body[start + len("_normalize_house_matrix_defaults(["):end] + "]"))


def test_all_shipped_default_rows_are_schema_valid():
    """CIO-Entscheid 1 (2026-10-21): "Wachstumsorientiert" (Score 7-8) summierte
    auf 99.5 % (Liquiditaet 150). Die Runtime-Normalisierung legte die fehlenden
    50 bps schon immer auf die Liquiditaet (200) -- die Konfiguration bildet
    jetzt nur das tatsaechliche Verhalten ab. Alle drei Quellen (YAML,
    Loader-Fallback, Runtime-Seeds) sind schema-gueltig, identisch und werden
    von der Normalisierung nicht mehr veraendert."""
    from services.house_matrix_loader import _HARDCODED_FALLBACK, load_house_matrix_default_tuples
    from services.portfolio_engine_house_matrix import _normalize_house_matrix_defaults

    yaml_rows = [tuple(t) for t in load_house_matrix_default_tuples()]
    seeds = _runtime_seed_tuples()
    assert yaml_rows == list(_HARDCODED_FALLBACK) == seeds
    assert _normalize_house_matrix_defaults(seeds) == seeds
    growth = next(t for t in seeds if t[0] == 7)
    assert growth[3:6] == (0, 200, 200)
    assert _schema_accepts(_default_rows()) is True
    assert _feasibility_accepts(_default_rows(), DEFAULT_POLICY) is True
    res = _validate([{"rows": _as_inputs(_default_rows()), "policy": DEFAULT_POLICY}])[0]
    assert res["valid"] is True and all(r["errors"] == [] for r in res["rows"])


def test_default_rows_have_no_risk_budget_hint():
    res = _validate([{"rows": _as_inputs(_valid_rows()), "policy": DEFAULT_POLICY}])[0]
    assert res["valid"] is True
    assert all(not r["hints"] for r in res["rows"])


# ------------------------------------------------------------------- Wiring

_DOM_HARNESS = r"""
var ELS={}, GRID_INPUTS=[], PUTS=[];
function unesc(s){return String(s).replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');}
function mkInput(attrs){
  var cls={};
  var o={value:unesc(attrs.value||''),title:'',attrs:attrs,
    getAttribute:function(k){return o.attrs[k]==null?null:unesc(o.attrs[k]);},
    setAttribute:function(k,v){o.attrs[k]=String(v);},
    classList:{toggle:function(c,on){if(on)cls[c]=1;else delete cls[c];},contains:function(c){return !!cls[c];}}};
  return o;
}
function mkEl(id){
  var e={id:id,style:{},disabled:false,title:'',textContent:'',_html:''};
  Object.defineProperty(e,'innerHTML',{get:function(){return e._html;},set:function(v){
    e._html=v;
    if(id==='admin-policy-grid'){
      GRID_INPUTS=[];
      var re=/<input ([^>]*)>/g,m;
      while((m=re.exec(v))){var attrs={},ra=/([\w-]+)="([^"]*)"/g,a;while((a=ra.exec(m[1])))attrs[a[1]]=a[2];GRID_INPUTS.push(mkInput(attrs));}
    }
  }});
  return e;
}
var document={
  getElementById:function(id){
    var hit=GRID_INPUTS.filter(function(i){return i.attrs.id===id;})[0];
    if(hit)return hit;
    if(!ELS[id])ELS[id]=mkEl(id);
    return ELS[id];
  },
  querySelector:function(sel){return document.querySelectorAll(sel)[0]||null;},
  querySelectorAll:function(sel){
    var row=/data-row="(\d+)"/.exec(sel), field=/data-field="([^"]+)"/.exec(sel);
    return GRID_INPUTS.filter(function(i){
      if(row&&i.attrs['data-row']!==row[1])return false;
      if(field&&i.attrs['data-field']!==field[1])return false;
      return i.attrs['data-field']!=null;
    });
  },
};
var window={};
var API={get:async function(){return DETAIL;},put:async function(url,body){PUTS.push({url:url,body:body});return DETAIL;}};
function field(row,f){return document.querySelector('#admin-policy-grid input[data-row="'+row+'"][data-field="'+f+'"]');}
"""

_DOM_FUNCS = (
    "function adminRenderPolicyList(",
    "async function adminPolicyOpen(",
    "function adminRenderPolicyGrid(",
    "function adminPolicyReadGridRows(",
    "function adminPolicyValidateAll(",
    "function adminPolicyAllRowsValid(",
    "function adminPolicyIsDirty(",
    "function adminPolicyRefreshSaveState(",
    "async function adminPolicySaveRows(",
)


def _dom(script: str, *, is_current: bool = False) -> dict:
    detail = {
        "id": "pol-1", "policy_name": "Test", "version": 2, "is_current": is_current,
        "max_real_estate_bps": 2000, "max_alternatives_bps": 1000, "min_liquidity_bps": 0,
        "house_matrix_rows": _valid_rows(),
    }
    body = "var DETAIL=" + json.dumps(detail) + ";\n" + _DOM_HARNESS + "\n(async function(){\n" + script + "\n})().catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    return _node(body, extra_funcs=_DOM_FUNCS, extra_vars=("adminPolicyState",))


def test_grid_renders_percent_text_inputs_with_accessible_labels():
    out = _dom(
        "await adminPolicyOpen('pol-1');"
        "var f=field(3,'equity_target_bps');"
        "console.log(JSON.stringify({n:GRID_INPUTS.length,value:f.value,type:f.attrs.type,mode:f.attrs.inputmode,"
        "label:f.getAttribute('aria-label'),eqmin:field(3,'equity_minimum_bps').value,risky:field(0,'max_risky_fraction_bps').value,"
        "save:document.getElementById('btn-policy-save').disabled,act:document.getElementById('btn-policy-activate').disabled}));"
    )
    rows = len(_valid_rows())
    assert out["n"] == rows * (len(FIELDS) + 1)  # + Profilname
    assert out["value"] == "48" and out["type"] == "text" and out["mode"] == "decimal"
    assert out["label"] == "Score 5–6 Aktien Ziel in %"
    assert out["eqmin"] == "0" and out["risky"] == "30"
    assert out["save"] is False and out["act"] is False  # gespeichert + gueltig


def test_invalid_input_marks_field_blocks_save_and_activate_and_sends_nothing():
    out = _dom(
        "await adminPolicyOpen('pol-1');"
        "var f=field(3,'equity_target_bps');f.value='56';adminPolicyValidateAll();"
        "await adminPolicySaveRows();"
        "console.log(JSON.stringify({invalid:f.classList.contains('is-invalid'),aria:f.attrs['aria-invalid'],title:f.title,"
        "status:document.getElementById('pol-row-status-3').innerHTML,save:document.getElementById('btn-policy-save').disabled,"
        "act:document.getElementById('btn-policy-activate').disabled,puts:PUTS.length}));"
    )
    assert out["invalid"] is True and out["aria"] == "true" and "muss zwischen" in out["title"]
    assert "Aktien Ziel: muss zwischen" in out["status"]
    assert out["save"] is True and out["act"] is True and out["puts"] == 0


def test_valid_edit_sends_exact_bps_and_activate_waits_for_save():
    out = _dom(
        "await adminPolicyOpen('pol-1');"
        "field(3,'equity_target_bps').value='47,65';field(3,'bonds_target_bps').value='35.35';"
        "field(3,'equity_minimum_bps').value='12.5';adminPolicyValidateAll();"
        "var actDirty=document.getElementById('btn-policy-activate').disabled;"
        "await adminPolicySaveRows();"
        "console.log(JSON.stringify({actDirty:actDirty,puts:PUTS}));"
    )
    assert out["actDirty"] is True
    assert len(out["puts"]) == 1
    put = out["puts"][0]
    assert put["url"] == "/admin/optimizer-policies/pol-1/house-matrix"
    row = put["body"]["rows"][3]
    assert row["equity_target_bps"] == 4765 and row["bonds_target_bps"] == 3535
    assert row["equity_minimum_bps"] == 1250
    assert all(isinstance(row[f], int) for f in FIELDS)
    expected = _valid_rows()
    expected[3].update(equity_target_bps=4765, bonds_target_bps=3535, equity_minimum_bps=1250)
    assert put["body"]["rows"] == expected
    assert _schema_accepts(put["body"]["rows"])


def test_active_policy_keeps_save_locked():
    out = _dom(
        "await adminPolicyOpen('pol-1');"
        "console.log(JSON.stringify({save:document.getElementById('btn-policy-save').disabled}));",
        is_current=True,
    )
    assert out["save"] is True


def test_monolith_no_longer_edits_policy_in_bps():
    src = HTML_PATH.read_text(encoding="utf-8")
    grid = _function(src, "function adminRenderPolicyGrid(")
    assert 'type="number"' not in grid and "pol-bps" not in grid
    assert "Werte in bps" not in src
    assert 'oninput="adminPolicyValidateAll()"' in grid
    save = _function(src, "async function adminPolicySaveRows(")
    assert "validation.payloadRows" in save
    assert ".pol-pct.is-invalid" in src


# ------------------------------------------- Klonen ohne prompt (CIO-Entscheid 2)

_CLONE_HARNESS = r"""
var ELS={}, CALLS=[], OPENED=[], LOADED=[], PROMPTS=0;
function unesc(s){return String(s).replace(/&amp;/g,'&');}
function reg(attrs){
  var o={value:unesc(attrs.value||''),disabled:false,textContent:'',attrs:attrs,focus:function(){},select:function(){}};
  if(attrs.id)ELS[attrs.id]=o;
  return o;
}
var document={
  body:{appendChild:function(el){
    ELS[el.id]=el;
    var re=/<(input|button|div)\s([^>]*)>/g,m;
    while((m=re.exec(el.innerHTML))){var attrs={},ra=/([\w-]+)="([^"]*)"/g,a;while((a=ra.exec(m[2])))attrs[a[1]]=a[2];if(attrs.id)reg(attrs);}
  }},
  createElement:function(){var cls={};return {id:'',className:'',innerHTML:'',dataset:{},
    classList:{add:function(c){cls[c]=1;},remove:function(c){delete cls[c];},contains:function(c){return !!cls[c];}}};},
  getElementById:function(id){return ELS[id]||null;},
};
var window={prompt:function(){PROMPTS++;return 'X';}};
function prompt(){PROMPTS++;return 'X';}
function prepareModalBeforeOpen(){return true;}
function cleanupModalAfterClose(){}
var adminPolicyState={policies:[{id:'pol-active',policy_name:'Haus',version:3,is_current:1}],selectedId:null,rows:[]};
var API={post:async function(url,body){CALLS.push(url);return {id:'pol-clone',policy_name:'Haus Variante',version:1};}};
async function adminLoadPolicies(h){LOADED.push(h);}
async function adminPolicyOpen(id){OPENED.push(id);}
"""


def _clone(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    fns = [_function(src, s) for s in (
        "function om(", "function cm(", "function adminPolicyEnsureCloneModal(",
        "function adminPolicyCloneActive(", "async function adminPolicyCloneConfirm(",
    )]
    body = _CLONE_HARNESS + "\n".join(fns) + "\n(async function(){\n" + script + "\n})().catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        path = fh.name
    try:
        res = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        Path(path).unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_clone_uses_modal_not_prompt_and_clones():
    out = _clone(
        "adminPolicyCloneActive();"
        "var open=ELS['m-policy-clone'].classList.contains('open');var prefill=ELS['policy-clone-name'].value;"
        "ELS['policy-clone-name'].value='  Haus Variante  ';"
        "await adminPolicyCloneConfirm();"
        "console.log(JSON.stringify({open:open,prefill:prefill,closed:!ELS['m-policy-clone'].classList.contains('open'),"
        "calls:CALLS,opened:OPENED,loaded:LOADED,prompts:PROMPTS}));"
    )
    assert out["open"] is True and out["prefill"] == "Haus (Kopie)"
    assert out["calls"] == ["/admin/optimizer-policies/pol-active/clone?new_name=Haus%20Variante"]
    assert out["closed"] is True and out["loaded"] == [True] and out["opened"] == ["pol-clone"]
    assert out["prompts"] == 0


def test_clone_with_empty_name_stays_open_and_sends_nothing():
    out = _clone(
        "adminPolicyCloneActive();ELS['policy-clone-name'].value='   ';await adminPolicyCloneConfirm();"
        "console.log(JSON.stringify({open:ELS['m-policy-clone'].classList.contains('open'),"
        "err:ELS['policy-clone-error'].textContent,calls:CALLS}));"
    )
    assert out["open"] is True and out["calls"] == [] and "Namen" in out["err"]


def test_policy_editor_sources_contain_no_native_dialogs():
    src = HTML_PATH.read_text(encoding="utf-8")
    for sig in ("function adminPolicyCloneActive(", "async function adminPolicyCloneConfirm(",
                "function adminPolicyEnsureCloneModal(", "async function adminPolicySaveRows(",
                "function adminRenderPolicyGrid(", "function adminPolicyValidateAll("):
        body = _function(src, sig)
        assert not re.search(r"\b(prompt|alert|confirm)\s*\(", body), sig
