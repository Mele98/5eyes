"""BAND-EDITOR-VALIDATION-001 (UX-Audit Befund 15).

Der Bandbreiten-Editor im Monolithen ("Soll-Quoten & Bandbreiten", Modal
m-eq) prueft live, bevor etwas uebernommen wird. Die Regeln sind die des
Backends -- dieser Test fuehrt die echte Monolith-Funktion
``computeBandEditorValidation()`` in Node aus UND prueft fuer jedes Szenario,
dass ``_apply_band_preferences()`` (services/portfolio_engine_house_matrix.py)
dieselbe Entscheidung trifft: was der Editor sperrt, lehnt die Engine ab;
was der Editor zulaesst, akzeptiert die Engine.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"

# Hausmatrix-Bandbreite (policy-bereinigt) und Engine-Ergebnis des Szenarios.
HOUSE = {
    "equities": {"min_bps": 4000, "max_bps": 7500},
    "bonds": {"min_bps": 1000, "max_bps": 4000},
    "real_estate": {"min_bps": 0, "max_bps": 2000},
    "alternatives": {"min_bps": 0, "max_bps": 1000},
    "liquidity": {"min_bps": 200, "max_bps": 1000},
}
TARGETS = {"equities": 6000, "bonds": 2500, "real_estate": 800, "alternatives": 300, "liquidity": 400}


def _function(src: str, signature: str) -> str:
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _var(src: str, name: str) -> str:
    match = re.search(r"^var " + re.escape(name) + r"=.*?;$", src, re.M)
    assert match, name
    return match.group(0)


def _run(edits: dict, stored: dict | None = None) -> dict:
    """edits: {bucket: {field: raw_text}} -- Eingaben im Editor."""
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    fns = [
        _function(src, n)
        for n in (
            "function normalizeBandKey(",
            "function parseBandPercentInput(",
            "function formatBandPercent(",
            "function parseBandPercentUserInput(",
            "function normalizeStoredBandOverride(",
            "function collectBandOverridesFromModal(",
            "function currentHouseMatrixBands(",
            "function computeBandEditorValidation(",
        )
    ]
    fns += [_var(src, "BAND_EDITOR_BUCKETS"), _var(src, "BAND_EDITOR_FIELD_LABELS")]
    harness = (
        "var HOUSE=" + json.dumps(HOUSE) + ";var TARGETS=" + json.dumps(TARGETS) + ";"
        "var STORED=" + json.dumps(stored or {}) + ";var EDITS=" + json.dumps(edits) + ";"
        + r"""
var strategyState={allocation:{house_matrix_bands:HOUSE}};
var allocationBandStoredOverrides=STORED;
var allocationBandBaseline={};
var INPUTS=[];
function fmt(b){return formatBandPercent(b);}
Object.keys(HOUSE).forEach(function(bucket){
  var ov=STORED[bucket]||{};
  var base={min_bps:HOUSE[bucket].min_bps,target_bps:TARGETS[bucket],max_bps:HOUSE[bucket].max_bps};
  allocationBandBaseline[bucket]=base;
  ['min_bps','target_bps','max_bps'].forEach(function(field){
    var shown=ov[field]!=null?ov[field]:base[field];
    var attrs={'data-bucket':bucket,'data-field':field,'data-initial':fmt(shown)};
    var value=fmt(shown);
    if(EDITS[bucket]&&EDITS[bucket][field]!=null)value=EDITS[bucket][field];
    INPUTS.push({value:value,style:{},getAttribute:function(k){return attrs[k]==null?null:attrs[k];}});
  });
});
var document={querySelectorAll:function(){return INPUTS;},getElementById:function(){return null;}};
var r=computeBandEditorValidation();
console.log(JSON.stringify({valid:r.valid,fieldErrors:r.fieldErrors,rowErrors:r.rowErrors,rowHints:r.rowHints,
  globalErrors:r.globalErrors,targetSum:r.targetSum,minSum:r.minSum,allTargetsExplicit:r.allTargetsExplicit,
  sent:collectBandOverridesFromModal()}));
"""
    )
    script = "\n".join(fns) + "\n" + harness
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    res = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=30)
    Path(path).unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _engine_accepts(bands: dict) -> bool:
    """Gleiche Entscheidung im Backend (Bounds beim Eintritt = Hausmatrix)."""
    from services.portfolio_engine_house_matrix import _apply_band_preferences

    targets = dict(TARGETS)
    minimums = {k: v["min_bps"] for k, v in HOUSE.items()}
    maximums = {k: v["max_bps"] for k, v in HOUSE.items()}
    try:
        _apply_band_preferences(bands, targets, minimums, maximums, [])
    except ValueError:
        return False
    return True


def _assert_matches_engine(out: dict) -> None:
    assert out["valid"] == _engine_accepts(out["sent"]), out


def test_untouched_editor_is_valid_and_sums_to_100():
    out = _run({})
    assert out["valid"] is True
    assert out["targetSum"] == 10000
    assert out["sent"] == {}
    _assert_matches_engine(out)


def test_min_above_house_max_blocks_and_names_the_house_limit():
    out = _run({"equities": {"min_bps": "80%"}})
    assert out["valid"] is False
    assert out["fieldErrors"]["equities"]["min_bps"] is True
    assert "Hausmatrix" in out["rowErrors"]["equities"][0]
    _assert_matches_engine(out)


def test_explicit_target_outside_band_blocks_at_the_target_field():
    out = _run({"bonds": {"target_bps": "45%"}})
    assert out["valid"] is False
    assert out["fieldErrors"]["bonds"] == {"target_bps": True}
    assert "zwischen Minimum" in out["rowErrors"]["bonds"][0]
    _assert_matches_engine(out)


@pytest.mark.parametrize("raw", ["abc", "150", "-5%"])
def test_non_percent_or_out_of_range_input_blocks(raw):
    out = _run({"liquidity": {"max_bps": raw}})
    assert out["valid"] is False
    assert out["fieldErrors"]["liquidity"]["max_bps"] is True
    assert "Prozentwert zwischen 0 und 100" in out["rowErrors"]["liquidity"][0]
    # Nie still als bps uebernommen.
    assert "liquidity" not in out["sent"]


def test_minimums_above_100_percent_block():
    out = _run({"equities": {"min_bps": "60%", "max_bps": "75%"}, "bonds": {"min_bps": "40%"}})
    assert out["valid"] is False
    assert any("mehr als 100%" in m for m in out["globalErrors"])
    assert out["fieldErrors"]["equities"]["min_bps"] is True
    _assert_matches_engine(out)


def test_all_five_targets_must_sum_to_exactly_100():
    edits = {k: {"target_bps": str(v / 100) + "%"} for k, v in TARGETS.items()}
    edits["equities"]["target_bps"] = "59%"
    edits["bonds"]["target_bps"] = "25.5%"  # Summe 99.5 %
    out = _run(edits)
    assert out["allTargetsExplicit"] is True
    assert out["valid"] is False
    assert any("genau 100%" in m for m in out["globalErrors"])
    _assert_matches_engine(out)

    edits["bonds"]["target_bps"] = "26%"  # Summe 100 %
    out = _run(edits)
    assert out["valid"] is True
    _assert_matches_engine(out)


def test_partial_target_edit_need_not_sum_to_100_engine_rebalances():
    out = _run({"equities": {"target_bps": "65%"}})
    assert out["valid"] is True
    assert out["targetSum"] == 10500
    assert out["allTargetsExplicit"] is False
    _assert_matches_engine(out)


def test_max_below_untouched_target_is_allowed_with_hint():
    out = _run({"equities": {"max_bps": "50%"}})
    assert out["valid"] is True
    assert "ausserhalb der neuen Bandbreite" in out["rowHints"]["equities"][0]
    _assert_matches_engine(out)


def test_stored_override_is_validated_like_a_fresh_edit():
    out = _run({"equities": {"max_bps": "55%"}}, stored={"equities": {"target_bps": 6000}})
    assert out["valid"] is False
    assert out["fieldErrors"]["equities"]["target_bps"] is True
    _assert_matches_engine(out)


def test_editor_wiring_blocks_apply_and_persist_until_valid():
    src = HTML_PATH.read_text(encoding="utf-8")
    apply_fn = _function(src, "function applyAllocationBandOverrides(")
    assert apply_fn.index("validateBandEditorModal()") < apply_fn.index("persistAllocationPreferences()")
    assert "return false;" in apply_fn
    build = _function(src, "function buildQT(")
    change_handler = build.split("addEventListener('change'", 1)[1].split("});", 1)[0]
    assert change_handler.index("if(!check.valid)return;") < change_handler.index("persistAllocationPreferences()")
    collect = _function(src, "function collectAllocationPreferencesFromUI(")
    assert "bandEditorIsValid()" in collect
    render = _function(src, "function renderBandEditorValidation(")
    assert "primary.disabled=!result.valid" in render
    # Ein Kopf-/Zeilen-Raster, beschriftete Felder in Prozent, Meldung am Feld.
    assert '<div class="qtr qth"' in build
    assert 'aria-label="${r.n} Minimum in %"' in build
    assert 'aria-describedby="${errId}"' in build
    assert "(bps)" not in build


# --- MANUAL-TARGET-SAVE-IN-BAND-EDITOR-001 (CIO-Review #656) -----------------

TA = {"policy_id": "pol-1", "based_on_assessment_id": "ra-1", "risky_fraction_bps": 6100, "version": 3}


def _run_manual(edits: dict, reason: str, api_error: dict | None = None) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    fns = [
        _function(src, n)
        for n in (
            "function normalizeBandKey(",
            "function parseBandPercentInput(",
            "function formatBandPercent(",
            "function parseBandPercentUserInput(",
            "function normalizeStoredBandOverride(",
            "function collectBandOverridesFromModal(",
            "function currentHouseMatrixBands(",
            "function computeBandEditorValidation(",
            "function escapeHtml(",
            "function currentManualSaveContext(",
            "function computeManualTargetSaveValidation(",
            "function buildManualTargetAllocationPayload(",
            "function renderManualTargetSaveState(",
            "function manualTargetSaveErrorText(",
            "async function saveManualTargetAllocationFromModal(",
        )
    ]
    fns += [
        _var(src, "BAND_EDITOR_BUCKETS"),
        _var(src, "BAND_EDITOR_FIELD_LABELS"),
        _var(src, "MANUAL_TARGET_REASON_MIN_LENGTH"),
    ]
    harness = (
        "var HOUSE=" + json.dumps(HOUSE) + ";var TARGETS=" + json.dumps(TARGETS) + ";"
        "var EDITS=" + json.dumps(edits) + ";var TA=" + json.dumps(TA) + ";"
        "var REASON=" + json.dumps(reason) + ";var API_ERROR=" + json.dumps(api_error) + ";"
        + r"""
var strategyState={allocation:{house_matrix_bands:HOUSE,target_allocation:TA}};
var allocationBandStoredOverrides={};
var allocationBandBaseline={};
var INPUTS=[];
Object.keys(HOUSE).forEach(function(bucket){
  var base={min_bps:HOUSE[bucket].min_bps,target_bps:TARGETS[bucket],max_bps:HOUSE[bucket].max_bps};
  allocationBandBaseline[bucket]=base;
  ['min_bps','target_bps','max_bps'].forEach(function(field){
    var attrs={'data-bucket':bucket,'data-field':field,'data-initial':formatBandPercent(base[field])};
    var value=formatBandPercent(base[field]);
    if(EDITS[bucket]&&EDITS[bucket][field]!=null)value=EDITS[bucket][field];
    INPUTS.push({value:value,style:{},getAttribute:function(k){return attrs[k]==null?null:attrs[k];}});
  });
});
var NODES={'aa-manual-save-reason':{value:REASON},'btn-aa-manual-save':{disabled:false},'aa-manual-save-status':{innerHTML:''}};
var document={querySelectorAll:function(){return INPUTS;},getElementById:function(id){return NODES[id]||null;}};
function getActiveMandateId(){return 'M1';}
function isDemoMandateId(){return false;}
var DIRTY=[];function markStrategyDirty(m){DIRTY.push(m);}
var POSTS=[];
var API={post:async function(url,body){POSTS.push({url:url,body:body});
  if(API_ERROR){var e=new Error('x');e.status=API_ERROR.status;e.detail=API_ERROR.detail;throw e;}
  return {version:4,manual_override_warnings:[]};}};
var VALIDATOR_CALLS=0;
var _origValidator=computeBandEditorValidation;
computeBandEditorValidation=function(){VALIDATOR_CALLS++;return _origValidator.apply(this,arguments);};
saveManualTargetAllocationFromModal().then(function(ok){
  console.log(JSON.stringify({ok:ok,posts:POSTS,validatorCalls:VALIDATOR_CALLS,
    status:NODES['aa-manual-save-status'].innerHTML,disabled:NODES['btn-aa-manual-save'].disabled,dirty:DIRTY}));
});
"""
    )
    script = "\n".join(fns) + "\n" + harness
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    res = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=30)
    Path(path).unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


GOOD_REASON = "Kunde wünscht nach Gespräch vom 14.10. eine defensivere Gewichtung."


def test_manual_save_uses_same_validator_and_posts_exact_bps_body():
    out = _run_manual(
        {"equities": {"target_bps": "55,5%"}, "bonds": {"target_bps": "29.5"}},
        GOOD_REASON,
    )
    assert out["ok"] is True
    assert out["validatorCalls"] >= 1
    assert len(out["posts"]) == 1
    post = out["posts"][0]
    assert post["url"] == "/mandates/M1/target-allocation"
    # Derselbe Body wie der bisherige Editor (allocationForm.ts
    # buildTargetAllocationPayload), Prozent -> bps exakt umgerechnet.
    assert post["body"] == {
        "target_equities_bps": 5550, "target_bonds_bps": 2950, "target_real_estate_bps": 800,
        "target_alternatives_bps": 300, "target_liquidity_bps": 400,
        "band_equities_min_bps": 4000, "band_equities_max_bps": 7500,
        "band_bonds_min_bps": 1000, "band_bonds_max_bps": 4000,
        "band_real_estate_min_bps": 0, "band_real_estate_max_bps": 2000,
        "band_alternatives_min_bps": 0, "band_alternatives_max_bps": 1000,
        "band_liquidity_min_bps": 200, "band_liquidity_max_bps": 1000,
        "risky_fraction_bps": 6100, "based_on_assessment_id": "ra-1",
        "policy_id": "pol-1", "override_reason": GOOD_REASON,
    }
    # Der Body besteht die Schema-Validierung des Endpunkts.
    from schemas.allocation import TargetAllocationCreate

    TargetAllocationCreate(**post["body"])
    assert "Version 4" in out["status"]


@pytest.mark.parametrize(
    "edits, reason, expected",
    [
        # Teilvorgabe ist fuer "Neu berechnen" gueltig, fuer die manuelle
        # Speicherung nicht: Summe der Ziele muss 100 % sein.
        ({"equities": {"target_bps": "65%"}}, GOOD_REASON, "genau 100%"),
        # Gemeinsamer Validator sperrt (Min ueber Hausmatrix-Max).
        ({"equities": {"min_bps": "80%"}}, GOOD_REASON, "markierten Felder"),
        ({}, "zu kurz", "Begründung fehlt oder ist zu kurz"),
    ],
)
def test_manual_save_blocked_until_valid(edits, reason, expected):
    out = _run_manual(edits, reason)
    assert out["ok"] is False
    assert out["posts"] == []
    assert out["disabled"] is True
    assert expected in out["status"]


def test_manual_save_shows_basis_409_understandably():
    out = _run_manual(
        {}, GOOD_REASON,
        api_error={"status": 409, "detail": "Keine Vermögensbasis: ohne Datenbasis ist keine Asset-Allocation möglich."},
    )
    assert out["ok"] is False
    assert len(out["posts"]) == 1
    assert "Speichern nicht möglich: Keine Vermögensbasis" in out["status"]
    assert out["dirty"] == []


def test_manual_save_is_a_separate_secondary_action_in_the_one_editor():
    src = HTML_PATH.read_text(encoding="utf-8")
    box = _function(src, "function buildManualTargetSaveBoxHtml(")
    assert "Als manuelle Soll-Allokation speichern (ohne Optimierung)" in box
    assert 'class="btn" id="btn-aa-manual-save"' in box  # sekundaer, nicht btn-p
    build = _function(src, "function buildQT(")
    assert "buildManualTargetSaveBoxHtml()" in build
    # Primaer-Aktion des Modals bleibt "Neu berechnen" (applyAllocationBandOverrides).
    assert '<button class="btn-p" onclick="refreshStrategyData(true)">Neu berechnen</button>' in src
    assert "primary.setAttribute('onclick','applyAllocationBandOverrides()')" in src
