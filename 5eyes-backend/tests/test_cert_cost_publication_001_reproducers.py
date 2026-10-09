"""CERT-COST-PUBLICATION-001 -- permanent repository reproducers.

Source of truth: the Ares/Codex audit worktree
`C:\\Users\\Emanuele\\Documents\\ChatGPT\\5eyes wird zu Ares\\asset-allocation-stochastic-core`
(branch `codex/asset-allocation-stochastic-core`),
`docs/audits/2026-10-09-cost-publication-channel-delivery-artifact-certification-spec.md`.
That spec documents five canonical P1 findings (ten current assertions);
its own temporary reproducer was deliberately removed after the run, per its
`product_code_mutated: false` / `tests_mutated: false` audit discipline.
Step 1 of the spec's own "Implementierungsreihenfolge fuer Claude" (Section
13) is to adopt these reproducers as PERMANENT repository tests before
touching any product code. This file (plus the frontend reporting-app
test(s) for the pure-React findings) is that step.

All root causes below were independently re-verified against this repo's
actual current `develop` HEAD (717ce3ab529d53c9fb355ee2b401932829ea0054)
before writing these tests -- not copied from the spec's historical evidence
unchecked.

Covered here (backend + monolith-via-Node):
- COST-RENDER-SEMANTICS-001 (4 assertions): monolith currency, nullable
  rate, exact turnus, and dynamic-vs-fixed PDF explanatory text.
- COST-PUBLICATION-GATE-001 (2 assertions): pending-state standalone PDF
  export, and degraded (exception-caught) cost evidence inside the
  Advisory-Report PDF.
- COST-DELIVERY-EVIDENCE-001 (1 of 2 assertions): the monolith's
  download-before-await-then-log-"ausgehaendigt" race. The sibling React
  self-attestation assertion lives in
  `5eyes-electron/frontend/reporting/src/components/AdvisoryLogEditor.cost_publication_001.test.tsx`.
- COST-ARTIFACT-EVIDENCE-001 (1 assertion): the standalone cost-disclosure
  PDF response carries no snapshot/document/byte-hash identity at all.

NOT covered here -- see the frontend test file:
- COST-PUBLICATION-001 (React discards the backend `cost_disclosure`
  section entirely -- no type, no validation requirement, no route, no
  Sidebar entry, no render branch).

Do not close any of these by weakening the assertion, deleting the test, or
reaching for a superficial fix (e.g. renaming the hardcoded "CHF" literal
into a differently-hardcoded string, or mapping `null` to "0%" under a new
label). Closure requires the full `CostPublicationEnvelopeV1` /
`CostArtifactV1` / `CostDeliveryEventV1` contract from Sections 4-9 of the
spec.
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

HTML_PATH = BACKEND_ROOT.parents[0] / "5eyes-electron" / "frontend" / "5eyes_v2.html"

from services.cost_disclosure import calculate_cost_disclosure  # noqa: E402
from services.pdf.components.advisory_palette import (  # noqa: E402
    MARGIN_BOTTOM, MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, PAGE_SIZE,
    make_advisory_styles,
)
from services.pdf.components.kostenausweis import build_kostenausweis_flowables  # noqa: E402

# Reuse the existing fixtures/helpers for the standalone cost-disclosure PDF
# endpoint instead of duplicating fixture code (same reuse convention as
# tests/test_provisional_pdf_gate.py importing from
# tests/test_engine_de_jurisdiction_wiring.py).
from test_cost_disclosure_pdf import (  # noqa: E402,F401
    _seed_minimal_mandate, advisor_user, auth_client, session_factory,
)
from test_engine_de_jurisdiction_wiring import (  # noqa: E402,F401
    _seed_de_mandate, session_factory as de_session_factory,
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_balanced_block(html: str, signature: str) -> str:
    """Return the exact source text of a `function ...(){ ... }` block that
    starts with `signature`, matching braces so the extraction is robust to
    nested blocks (as the GOAL-RANK-HARDNESS-ROUNDTRIP-001 precedent in
    tests/test_goal_classic_noop_edit_shifts_rank_and_weight.py does with a
    simple regex for single-line extractions; this helper generalizes that
    to a whole function body).
    """
    start = html.index(signature)
    i = html.index("{", start)
    depth = 1
    j = i + 1
    while depth > 0:
        ch = html[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return html[start:j]


def _run_node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _require_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")


def _pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    from io import BytesIO

    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _render_kostenausweis_pdf(data: dict) -> bytes:
    from io import BytesIO
    from reportlab.platypus import SimpleDocTemplate

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=PAGE_SIZE, topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
    )
    doc.build(build_kostenausweis_flowables(data, make_advisory_styles()))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# COST-RENDER-SEMANTICS-001 (1/4) -- monolith _formatRappenChf hardcodes
# "CHF " unconditionally; 5eyes_v2.html:13349-13353 never consults
# payload.currency (it does not even take a currency parameter).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-RENDER-SEMANTICS-001 -- CERT-COST-PUBLICATION-001 (currency)")
def test_monolith_format_rappen_ignores_payload_currency():
    _require_node()
    html = _html()
    fn_src = _extract_balanced_block(html, "function _formatRappenChf(rappen){")
    assert "currency" not in fn_src, (
        "Sanity: _formatRappenChf's signature/body changed shape -- update "
        "this extraction before trusting the assertion below"
    )

    script = fn_src + "\nconsole.log(_formatRappenChf(400000000));"
    result = _run_node(script)

    # Soll: a EUR-denominated mandate's cost amounts must render with "EUR",
    # never a hardcoded "CHF" regardless of the actual contract currency.
    assert "EUR" in result, (
        f"_formatRappenChf('CHF 400000000 Rappen') rendered {result!r} for what "
        "is actually a EUR-denominated amount -- the formatter hardcodes "
        "'CHF ' unconditionally and has no currency parameter at all"
    )


# ---------------------------------------------------------------------------
# COST-RENDER-SEMANTICS-001 (2/4) -- a null rate_bps (absolute retrocession,
# no rate) renders as "0.00%" instead of "no rate at all".
# 5eyes_v2.html:13293 -- Number(item.rate_bps||0).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-RENDER-SEMANTICS-001 -- CERT-COST-PUBLICATION-001 (null rate)")
def test_monolith_null_rate_bps_renders_as_zero_percent_not_absent():
    _require_node()
    html = _html()
    match = re.search(r"var rate=\(Number\(item\.rate_bps\|\|0\)/100\)\.toFixed\(2\)\+'%';", html)
    assert match, (
        "rate derivation statement in renderCostDisclosure() moved/changed "
        "shape -- update this extraction before trusting the assertion below"
    )

    # Real production shape: an absolute, disclosed-but-not-reimbursed
    # retrocession item as actually built by
    # services/cost_disclosure.py::calculate_cost_disclosure() for a
    # non-reimbursed inducement -- always rate_bps=None.
    disclosure = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_00,
        positions=[{"amount_rappen": 100_000_00, "ter_bps": 0}],
        fee_model={},
        transaction_cost_bps=0,
        inducements=[{
            "amount_rappen": 500_00,
            "frequency": "jährlich",
            "reimbursed_to_client": False,
            "provider": "Fondsanbieter X",
        }],
    )
    retro_item = next(
        item for item in disclosure["cost_items"] if item["key"] == "retrocession_disclosed"
    )
    assert retro_item["rate_bps"] is None, (
        "Sanity: real retrocession_disclosed item no longer has rate_bps=None "
        "-- update the fixture above before trusting the assertion below"
    )

    script = (
        "var item = " + json.dumps(retro_item) + ";\n"
        + match.group(0) + "\n"
        "console.log(rate);\n"
    )
    rendered_rate = _run_node(script)

    # Soll (spec 6.1): "rate_bps=null wird als '-' oder 'absoluter Betrag' "
    # dargestellt, nie 0 %" -- an absolute, rate-less cost item must never
    # be shown as if a 0.00% rate had been disclosed.
    assert rendered_rate != "0.00%", (
        f"an absolute retrocession with no rate_bps rendered as {rendered_rate!r} "
        "-- null is being displayed as a disclosed 0% rate instead of 'no rate'"
    )


# ---------------------------------------------------------------------------
# COST-RENDER-SEMANTICS-001 (3/4) -- any non-"einmalig" frequency is shown
# as "p.a." (including monthly/quarterly/unknown).
# 5eyes_v2.html:13295.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-RENDER-SEMANTICS-001 -- CERT-COST-PUBLICATION-001 (turnus)")
def test_monolith_frequency_collapses_non_einmalig_values_to_pa():
    _require_node()
    html = _html()
    match = re.search(
        r"var freq=String\(item\.frequency\|\|''\)\.toLowerCase\(\)===" r"'einmalig'\?'einmalig':'p\.a\.';",
        html,
    )
    assert match, (
        "frequency derivation statement in renderCostDisclosure() moved/"
        "changed shape -- update this extraction before trusting the "
        "assertion below"
    )

    script = (
        "var item = {frequency: 'monatlich'};\n"
        + match.group(0) + "\n"
        "console.log(freq);\n"
    )
    rendered_freq = _run_node(script)

    # Soll (spec 6.1): frequency is a typed code with central localization;
    # "monatlich" must render as "monatlich", not be silently reinterpreted
    # as annual.
    assert rendered_freq == "monatlich", (
        f"a cost item with frequency='monatlich' rendered Turnus={rendered_freq!r} "
        "-- every non-'einmalig' frequency (monthly, quarterly, unknown) is "
        "collapsed to 'p.a.'"
    )


# ---------------------------------------------------------------------------
# COST-RENDER-SEMANTICS-001 (4/4) -- the PDF's fixed intro paragraph claims
# "Schweizer Franken" even though the numeric amounts correctly use the
# dynamic payload currency. services/pdf/components/kostenausweis.py:50-57.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-RENDER-SEMANTICS-001 -- CERT-COST-PUBLICATION-001 (pdf fixtext)")
def test_pdf_intro_text_claims_chf_for_a_eur_mandate():
    disclosure = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_00,
        positions=[{"amount_rappen": 100_000_00, "ter_bps": 50}],
        fee_model={"default_advisory_fee_bps": 80},
        transaction_cost_bps=0,
        currency="EUR",
    )
    assert disclosure["currency"] == "EUR"  # sanity: numbers really are EUR

    pdf_bytes = _render_kostenausweis_pdf(disclosure)
    text = _pdf_text(pdf_bytes)
    assert "EUR" in text  # sanity: the dynamic amounts really do say EUR

    # Soll: for a EUR mandate, the explanatory text must not claim the
    # costs are denominated "in Schweizer Franken" -- numbers and prose must
    # agree on the currency.
    assert "Schweizer Franken" not in text, (
        "Kostenausweis PDF intro paragraph still says 'in Schweizer Franken' "
        "for a EUR-denominated mandate, even though the amounts/percentages "
        "correctly use EUR -- numbers and explanatory text disagree"
    )


# ---------------------------------------------------------------------------
# COST-PUBLICATION-GATE-001 (1/2) -- a pending (no recommendation yet)
# mandate's standalone cost-disclosure.pdf is exportable as a plain HTTP-200
# client PDF. routers/pdf_reports.py:2078-2112 (get_cost_disclosure_pdf)
# calls the live builder and always returns a PDF Response -- no gate.
#
# The existing positive control
# tests/test_cost_disclosure_pdf.py::test_endpoint_pending_liefert_valides_pdf
# asserts exactly this HTTP-200 behavior today and is NOT touched here; this
# test documents that the same behavior is a certification gap under the
# target "pending must never become client-ready" contract (spec Section 5.1).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-PUBLICATION-GATE-001 -- CERT-COST-PUBLICATION-001 (pending export)")
def test_pending_cost_disclosure_must_not_export_as_client_ready_pdf(auth_client, advisor_user, session_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/cost-disclosure.pdf")

    # Soll: pending/incomplete cost evidence must block a client-ready
    # export with a stable reason code (spec Section 5.2: 409/422), not
    # silently hand out a PDF indistinguishable from a certified one.
    assert resp.status_code in (409, 422), (
        f"pending-state mandate's cost-disclosure.pdf returned HTTP "
        f"{resp.status_code} (a plain client PDF) instead of being blocked "
        "as not-yet-client-ready"
    )


# ---------------------------------------------------------------------------
# COST-PUBLICATION-GATE-001 (2/2) -- a cost-disclosure calculation failure
# is caught and replaced with a degraded/unavailable section, and the full
# Advisory-Report PDF (incl. everything after it) still renders successfully.
# services/advisory_report.py::_build_cost_disclosure_section fails closed
# into a dict (NOT falsy), so
# services/pdf/documents/advisory_report.py:112-127's own fallback never
# even triggers -- the report is simply built with audit_degraded=True and
# handed out as a normal, complete, client-ready PDF regardless.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-PUBLICATION-GATE-001 -- CERT-COST-PUBLICATION-001 (degraded export)")
def test_degraded_cost_disclosure_must_not_produce_client_ready_advisory_pdf(de_session_factory, monkeypatch):
    from models.mandates import Mandate
    from services.advisory_report import compute_advisory_report
    from services.pdf.documents.advisory_report import render_advisory_report_pdf
    from services.portfolio_engine import generate_recommendation_run

    advisor_id, mid, _tenant_id = _seed_de_mandate(
        de_session_factory, suffix="gate-degraded", cma_status="committee_approved",
    )
    with de_session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_recommendation_run(s, mandate, advisor_id, preferences=None)
        s.commit()

    def _boom(db, mandate):
        raise RuntimeError("simulated cost-disclosure calculation failure")

    # Deterministically trigger the real except-and-degrade branch in
    # services/advisory_report.py::_build_cost_disclosure_section -- we are
    # not mocking the gate under test (there is none), only the upstream
    # calculation it wraps, to force the exact failure path the finding
    # documents.
    monkeypatch.setattr("services.cost_disclosure.build_cost_disclosure", _boom)

    with de_session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        payload = compute_advisory_report(s, mandate, advisor=None)
    assert payload["cost_disclosure"].get("audit_degraded") is True, (
        "Sanity: the induced failure no longer produces an audit_degraded "
        "cost_disclosure section -- update this test before trusting the "
        "assertion below"
    )

    with de_session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        pdf_bytes = render_advisory_report_pdf(s, mandate, advisor=None)

    # Soll: degraded cost evidence must block a client-ready Advisory-Report
    # export (there is no internal-draft vs client-ready distinction today),
    # not silently continue to a complete, signature-ready PDF.
    assert pdf_bytes is None, (
        f"render_advisory_report_pdf returned a full {len(pdf_bytes)}-byte "
        "client-ready PDF even though cost_disclosure.audit_degraded=True -- "
        "no gate separates an internal degraded draft from a client-ready "
        "document"
    )


# ---------------------------------------------------------------------------
# COST-DELIVERY-EVIDENCE-001 (1/2) -- the monolith's downloadCostDisclosurePdf()
# fires the PDF download without awaiting it, then immediately logs an
# AdvisoryLog entry claiming the document was "ausgehaendigt" -- regardless
# of whether the download ever succeeds. 5eyes_v2.html:13309-13347.
# The sibling React self-attestation assertion (free checkbox, no artifact
# reference) lives in the frontend reporting-app test file.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-DELIVERY-EVIDENCE-001 -- CERT-COST-PUBLICATION-001 (unawaited download)")
def test_monolith_download_cost_disclosure_pdf_logs_handed_over_before_download_settles():
    _require_node()
    html = _html()
    fn_src = _extract_balanced_block(html, "async function downloadCostDisclosurePdf(){")
    assert "downloadServerPdf('cost-disclosure')" in fn_src, (
        "Sanity: downloadCostDisclosurePdf() no longer calls "
        "downloadServerPdf('cost-disclosure') -- update this extraction "
        "before trusting the assertion below"
    )

    # Stub every global the real function body touches. downloadServerPdf is
    # stubbed as a Promise that NEVER resolves within this test -- a
    # correctly-awaited implementation would therefore never reach the
    # AdvisoryLog POST either.
    script = (
        "var __order = [];\n"
        "function getActiveMandateId(){ return 'mandate-evidence-001'; }\n"
        "function downloadServerPdf(reportType){\n"
        "  __order.push('download-started:' + reportType);\n"
        "  return new Promise(function(){ /* never resolves in this test */ });\n"
        "}\n"
        "var API = {\n"
        "  post: function(path, body){\n"
        "    __order.push('advisory-log-posted');\n"
        "    return Promise.resolve({});\n"
        "  }\n"
        "};\n"
        "var document = { getElementById: function(){ return null; } };\n"
        "var console = { warn: function(){} };\n"
        + fn_src + "\n"
        "downloadCostDisclosurePdf();\n"
        "setTimeout(function(){\n"
        "  console_real.log(JSON.stringify(__order));\n"
        "  process.exit(0);\n"
        "}, 50);\n"
    ).replace("console_real", "require('console')")
    result = _run_node(script)
    order = json.loads(result)

    # Soll (spec Section 10): "Ausgehaendigt" darf nie aus einem Buttonklick
    # oder fehlendem Fehler abgeleitet werden -- the AdvisoryLog POST must
    # never fire while the download it attests to is still pending/unsettled.
    assert "advisory-log-posted" not in order, (
        f"downloadCostDisclosurePdf() posted an AdvisoryLog entry claiming "
        f"the PDF was 'ausgehaendigt' (order={order!r}) while the download "
        "it was supposed to confirm never even resolved -- the download "
        "call is fired without 'await'"
    )


# ---------------------------------------------------------------------------
# COST-ARTIFACT-EVIDENCE-001 -- the standalone cost-disclosure PDF response
# carries no snapshot/document/byte-hash identity at all.
# routers/pdf_reports.py:2078-2112.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="COST-ARTIFACT-EVIDENCE-001 -- CERT-COST-PUBLICATION-001")
def test_cost_disclosure_pdf_response_carries_no_artifact_identity(auth_client, advisor_user, session_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/cost-disclosure.pdf")
    assert resp.status_code == 200, resp.text  # unchanged positive behavior

    # Soll: every client-ready cost PDF must carry a verifiable artifact
    # identity (snapshot id/hash, document id, byte hash) so it is provable
    # which exact bytes a client was shown. Today the response has nothing
    # beyond Content-Disposition.
    identity_headers = {
        k: v for k, v in resp.headers.items()
        if re.search(r"snapshot|artifact|document|sha256|hash", k, re.IGNORECASE)
    }
    assert identity_headers, (
        "cost-disclosure.pdf response carries no snapshot/artifact/document/"
        f"hash identity header at all -- full header set was: {dict(resp.headers)}"
    )
