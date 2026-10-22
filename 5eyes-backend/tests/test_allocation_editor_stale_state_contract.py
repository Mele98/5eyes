"""ALLOC-EDITOR-STALE-001: Residual-Vertraege zu PR #656 (Codex-Reproducer
``test_2026_10_21_pr656_allocation_editor_stale_publication_adversarial``,
hier als regulaerer Test ohne xfail uebernommen und erweitert).

Der Prozent-Editor und der sichtbare Stale-Zustand nuetzen nur, wenn:

* Beratungs-PDFs nicht als aktuell erzeugt werden, waehrend der Browser weiss,
  dass die angezeigte Berechnung veraltet ist (Monolith-Gate) bzw. die
  angezeigte Allokation nicht mehr die aktuelle ist (Server-Gate);
* ein manueller Save an genau die bearbeitete Allokations-Version gebunden
  ist (409 statt Last-Write-Wins); und
* der React-Editor nach dem Save keine Optimizer-Kennzahlen eines frueheren
  Laufs mehr anzeigt.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from schemas.allocation import TargetAllocationCreate
from tests.test_manual_allocation_save_contract import (
    SF,  # noqa: F401 - pytest fixture re-export
    REASON,
    _assessment,
    _body_from,
    _current,
    _request,
    _seed,
    _shifted_targets,
)
from routers import allocation as allocation_router


PRODUCT_ROOT = Path(allocation_router.__file__).resolve().parents[2]
HTML_PATH = PRODUCT_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"
REACT_EDITOR_PATH = (
    PRODUCT_ROOT
    / "5eyes-electron"
    / "frontend"
    / "reporting"
    / "src"
    / "sections"
    / "allocation"
    / "AllocationEditor.tsx"
)


def _function(src: str, signature: str) -> str:
    start = src.index(signature)
    pos = src.index("{", start + len(signature) - 1)
    depth, end = 1, pos + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[end], 0)
        end += 1
    return src[start:end]



def test_dirty_allocation_blocks_fresh_server_advice_artifacts():
    """A browser-known stale state must block or label final advice artefacts."""
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    src = HTML_PATH.read_text(encoding="utf-8")
    download = _function(src, "async function downloadServerPdf(")
    harness = r"""
var strategyState={dirty:true,staleNotice:'Bandbreiten geaendert',allocation:{buckets:[{}]}};
var window={showAppError:function(){}};
var console={error:function(){}};
function getActiveMandateId(){return 'M1';}
var REQUESTS=[];
function _fetchAndSavePdf(path,type){REQUESTS.push({path:path,type:type});return Promise.resolve({status:'saved'});}
Promise.all([downloadServerPdf('assetallocation'),downloadServerPdf('anlagestrategie')]).then(function(){
  process.stdout.write(JSON.stringify(REQUESTS));
});
"""
    script = download + "\n" + harness
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(script)
        path = Path(handle.name)
    try:
        result = subprocess.run(
            ["node", str(path)], capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        )
    finally:
        path.unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    requests = json.loads(result.stdout)
    assert requests == [], (
        "A dirty/stale allocation must not emit a freshly labelled advice PDF "
        "from an older persisted context. Recalculate, or create an explicit "
        "historical/stale artefact with the bound stale reason and context."
    )



def test_react_manual_save_invalidates_old_optimizer_metrics():
    """Metrics from Generate cannot remain attached to newly saved manual weights."""
    src = REACT_EDITOR_PATH.read_text(encoding="utf-8")
    start = src.index("  async function onSave()")
    end = src.index("\n  const total =", start)
    body = src[start:end]
    save_pos = body.index("await saveTargetAllocation")
    post_save = body[save_pos:]
    assert "setMetrics(" in post_save, (
        "After a manual save the React editor keeps expected return, volatility, "
        "risky fraction and limiting factor from the previous optimizer run. "
        "Clear them or replace them with metrics bound to the saved allocation."
    )



def test_manual_save_rejects_stale_allocation_predecessor(SF):
    """Two editor sessions may not silently last-write-wins each other."""
    with SF() as session:
        mandate, advisor = _seed(session)
        original = _current(session, mandate.id)
        assessment_id = _assessment(session, mandate.id).id

        first_body = _body_from(
            original, assessment_id, **_shifted_targets(original),
        )
        stale_values = _body_from(
            original,
            assessment_id,
            reason=(
                REASON
                + " Zweite Sitzung bestaetigt bewusst den zuvor geladenen Stand."
            ),
        ).model_dump()
        # The field is intentionally sent already. Today Pydantic silently
        # ignores it because the write contract does not define a predecessor
        # token. A closure may make it required without changing this test.
        stale_body = TargetAllocationCreate(
            **stale_values,
            expected_current_allocation_id=original.id,
        )

        first = allocation_router.create_target_allocation(
            mandate.id, first_body, _request(), db=session, current_user=advisor,
        )
        assert first.id != original.id

        with pytest.raises(HTTPException) as exc:
            allocation_router.create_target_allocation(
                mandate.id,
                stale_body,
                _request(),
                db=session,
                current_user=advisor,
            )
        assert exc.value.status_code == 409
        assert "aktuell" in str(exc.value.detail).lower() or "version" in str(exc.value.detail).lower()


# ---------------------------------------------------------------------------
# Erweiterungen ALLOC-EDITOR-STALE-001
# ---------------------------------------------------------------------------


def _run_node(script: str) -> str:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(script)
        path = Path(handle.name)
    try:
        result = subprocess.run(
            ["node", str(path)], capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        )
    finally:
        path.unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _pdf_harness(state_js: str, calls: str) -> dict:
    src = HTML_PATH.read_text(encoding="utf-8")
    download = _function(src, "async function downloadServerPdf(")
    harness = (
        "var strategyState=" + state_js + ";\n"
        "var ERRORS=[];var window={showAppError:function(m){ERRORS.push(m);}};\n"
        "function getActiveMandateId(){return 'M1';}\n"
        "var REQUESTS=[];\n"
        "function _fetchAndSavePdf(path,type){REQUESTS.push({path:path,type:type});"
        "return Promise.resolve({status:'saved'});}\n"
        "Promise.all([" + calls + "]).then(function(res){"
        "process.stdout.write(JSON.stringify({requests:REQUESTS,errors:ERRORS,results:res}));});\n"
    )
    return json.loads(_run_node(download + "\n" + harness))


def test_dirty_state_blocks_all_allocation_bound_pdfs_but_not_risk_profile():
    out = _pdf_harness(
        "{dirty:true,staleNotice:'Bandbreiten geaendert',"
        "allocation:{target_allocation:{id:'TA1'}}}",
        "downloadServerPdf('portfolio'),downloadServerPdf('vertrag'),"
        "downloadServerPdf('cost-disclosure'),downloadServerPdf('risikoprofil')",
    )
    assert [r["type"] for r in out["requests"]] == ["risikoprofil"]
    blocked = [r for r in out["results"] if r and r.get("status") == "cancelled"]
    assert len(blocked) == 3
    assert all(r["reason"] == "allocation_stale" for r in blocked)
    assert out["errors"] and "[allocation_stale]" in out["errors"][0]
    assert "Bandbreiten geaendert" in out["errors"][0]


def test_clean_state_binds_strategy_pdf_to_displayed_allocation_id():
    out = _pdf_harness(
        "{dirty:false,activeMandateId:'M1',allocation:{target_allocation:{id:'TA 7'}}}",
        "downloadServerPdf('assetallocation'),downloadServerPdf('anlagestrategie'),"
        "downloadServerPdf('backtest','?horizon=10')",
    )
    paths = [r["path"] for r in out["requests"]]
    assert paths == [
        "/mandates/M1/reports/assetallocation.pdf?expected_allocation_id=TA%207",
        "/mandates/M1/reports/anlagestrategie.pdf?expected_allocation_id=TA%207",
        "/mandates/M1/reports/backtest.pdf?horizon=10",
    ]


def test_clean_state_of_other_mandate_sends_no_token():
    out = _pdf_harness(
        "{dirty:false,activeMandateId:'M2',allocation:{target_allocation:{id:'TA7'}}}",
        "downloadServerPdf('assetallocation')",
    )
    assert out["requests"][0]["path"] == "/mandates/M1/reports/assetallocation.pdf"


_PAYLOAD_HARNESS = r"""
var BAND_EDITOR_BUCKETS=['equities','bonds','real_estate','alternatives','liquidity'];
var strategyState={};
var V={};BAND_EDITOR_BUCKETS.forEach(function(b){V[b]={target_bps:2000,min_bps:0,max_bps:4000};});
var ta={id:'TA1',version:3,policy_id:'P',based_on_assessment_id:'RA',risky_fraction_bps:5000};
var first=buildManualTargetAllocationPayload(V,ta,'r');
strategyState.manualSaveRef={baseId:'TA1',id:'TA2',version:4};
var second=buildManualTargetAllocationPayload(V,ta,'r');
var other=buildManualTargetAllocationPayload(V,{id:'TA9',version:9,policy_id:'P'},'r');
process.stdout.write(JSON.stringify([first,second,other]));
"""


def test_monolith_manual_payload_carries_predecessor_token():
    src = HTML_PATH.read_text(encoding="utf-8")
    pred = _function(src, "function currentManualSavePredecessor(")
    build = _function(src, "function buildManualTargetAllocationPayload(")
    first, second, other = json.loads(
        _run_node(pred + "\n" + build + "\n" + _PAYLOAD_HARNESS)
    )
    key_id, key_v = "expected_current_allocation_id", "expected_current_allocation_version"
    assert (first[key_id], first[key_v]) == ("TA1", 3)
    # nach eigener manueller Speicherung ist der gespeicherte Satz Vorgaenger
    assert (second[key_id], second[key_v]) == ("TA2", 4)
    # nach Neu-Berechnung (andere Basis) gilt die frisch geladene Allokation
    assert (other[key_id], other[key_v]) == ("TA9", 9)


def test_monolith_save_records_saved_allocation_as_next_predecessor():
    src = HTML_PATH.read_text(encoding="utf-8")
    save = _function(src, "async function saveManualTargetAllocationFromModal(")
    post = save.index("API.post(")
    assert "strategyState.manualSaveRef=" in save[post:]


def test_react_editor_sends_expected_allocation_token():
    src = REACT_EDITOR_PATH.read_text(encoding="utf-8")
    start = src.index("  async function onSave()")
    body = src[start:src.index("\n  const total =", start)]
    assert "expected_current_allocation_id: record.id" in body
    assert "expected_current_allocation_version: record.version" in body


_TOKEN_FIELDS = {"expected_current_allocation_id", "expected_current_allocation_version"}


def test_manual_save_with_matching_token_succeeds_and_wrong_version_conflicts(SF):
    with SF() as session:
        mandate, advisor = _seed(session)
        original = _current(session, mandate.id)
        assessment_id = _assessment(session, mandate.id).id
        base = _body_from(
            original, assessment_id, **_shifted_targets(original),
        ).model_dump(exclude=_TOKEN_FIELDS)
        wrong_version = TargetAllocationCreate(
            **base,
            expected_current_allocation_id=original.id,
            expected_current_allocation_version=int(original.version) + 5,
        )
        with pytest.raises(HTTPException) as exc:
            allocation_router.create_target_allocation(
                mandate.id, wrong_version, _request(), db=session, current_user=advisor,
            )
        assert exc.value.status_code == 409
        assert str(exc.value.detail).endswith("[allocation_version_conflict]")
        session.expire_all()
        assert _current(session, mandate.id).id == original.id

        ok = TargetAllocationCreate(
            **base,
            expected_current_allocation_id=original.id,
            expected_current_allocation_version=int(original.version),
        )
        saved = allocation_router.create_target_allocation(
            mandate.id, ok, _request(), db=session, current_user=advisor,
        )
        assert saved.id != original.id
        assert int(saved.version) == int(original.version) + 1


def test_pdf_report_context_gate_rejects_foreign_allocation_id(SF):
    from routers import pdf_reports

    with SF() as session:
        mandate, _advisor = _seed(session)
        original = _current(session, mandate.id)
        # passendes Token und kein Token: keine Ablehnung
        pdf_reports._assert_report_allocation_context(mandate, session, original.id)
        pdf_reports._assert_report_allocation_context(mandate, session, None)
        with pytest.raises(HTTPException) as exc:
            pdf_reports._assert_report_allocation_context(
                mandate, session, "veraltet-123",
            )
        assert exc.value.status_code == 409
        assert str(exc.value.detail).endswith("[allocation_report_context_stale]")
