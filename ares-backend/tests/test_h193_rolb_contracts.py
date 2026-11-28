"""H-193 (ROL-b neu): N-939-01..-05 -- adversariale Vertraege.

* Finalitaet: nur ausdruecklich ``watermark_mode == "none"`` traegt
  Unterschriftsfelder; alles andere zeigt "Nicht zur Unterzeichnung" und eine
  Kennzeichnung auf jeder Seite, ohne Pruefnummer und ohne Archiv.
* Freigabe einer Eignungsregel ist an die gesehene Menge (rule_id, rule_hash)
  gebunden: Sperre, Vergleich, Freigabe und Audit sind eine Transaktion.
* Seed-Renditen zaehlen in Produktion weder fuer die Drift noch fuer den
  Sub-Asset-Benchmark.

Alle Namen/Werte sind fiktive Testwerte.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import re
import sqlite3
import sys
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
for _path in (BACKEND, BACKEND / "tests", BACKEND / "tests" / "pdf"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tests.test_rol_b_role_followups import (  # noqa: E402,F401 -- Fixtures
    AuditLog,
    ProductEligibilityRule,
    _approve,
    _clone_user,
    _finalized,
    _fund,
    _rule,
    _seen,
    elig,
    session_factory,
)
from tests.test_ccx_p4_allocation_publish import _mandate, _published, _signoff_pdf_text  # noqa: E402

REQUIRED = "PRODUCT_ELIGIBILITY_SEEN_VERSION_REQUIRED"
MISMATCH = "PRODUCT_ELIGIBILITY_SEEN_VERSION_MISMATCH"
SIGN_LINE = "Ort, Datum / Anlageberater"
NOT_FOR_SIGNATURE = "Nicht zur Unterzeichnung"


# ------------------------------------------------------ N-939-02 gesehene Fassung
def _approval_audits(factory, pid) -> list[str]:
    with factory() as db:
        return [a.new_value or "" for a in db.query(AuditLog).filter_by(
            table_name="product_eligibility_rules", record_id=pid).all()
            if "approved:" in (a.new_value or "")]


def _statuses(factory, pid) -> set:
    with factory() as db:
        return {r.status for r in db.query(ProductEligibilityRule).filter_by(product_id=pid)}


def _assert_blocked(factory, pid, resp, code):
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["reason_code"] == code
    assert _statuses(factory, pid) == {"draft"}
    assert _approval_audits(factory, pid) == []


def _rehash(rule) -> None:
    from services.product_eligibility import TENANT_PRODUCT_RULE_SOURCE
    from services.product_eligibility_governance import rule_hash_from_row

    rule.rule_hash = rule_hash_from_row(rule, source=TENANT_PRODUCT_RULE_SOURCE)


def _second_draft(factory, pid) -> None:
    """Zweite offene Regel desselben Produkts (gleicher Autor), gueltiger Hash."""
    with factory() as db:
        first = db.query(ProductEligibilityRule).filter_by(product_id=pid).first()
        values = {c.name: getattr(first, c.name) for c in ProductEligibilityRule.__table__.columns}
        values.update(id=str(uuid.uuid4()), profile_to=6, rule_hash="")
        row = ProductEligibilityRule(**values)
        _rehash(row)
        db.add(row)
        db.commit()


def test_reviewer_without_seen_rules_is_refused(elig):
    factory, api = elig
    pid = _fund(api)
    for body in ({}, {"seen_rules": None}, {"single_approver_attestation": True, "attestation_reason": "x" * 30}):
        _assert_blocked(factory, pid, _approve(api, "reviewer", pid, body), REQUIRED)


@pytest.mark.parametrize("change", ["empty", "duplicate", "extra", "unknown_id", "other_hash"])
def test_unequal_seen_set_is_refused(elig, change):
    factory, api = elig
    pid = _fund(api)
    (pair,) = _seen(api, pid)["seen_rules"]
    seen = {
        "empty": [],
        "duplicate": [pair, pair],
        "extra": [pair, {"rule_id": "fremd", "rule_hash": "0" * 64}],
        "unknown_id": [{**pair, "rule_id": "fremd"}],
        "other_hash": [{**pair, "rule_hash": "0" * 64}],
    }[change]
    _assert_blocked(factory, pid, _approve(api, "reviewer", pid, {"seen_rules": seen}), MISMATCH)


def test_partial_set_is_refused_and_full_set_accepted_in_any_order(elig):
    factory, api = elig
    pid = _fund(api)
    before = _seen(api, pid)
    _second_draft(factory, pid)
    _assert_blocked(factory, pid, _approve(api, "reviewer", pid, before), MISMATCH)
    full = {"seen_rules": list(reversed(_seen(api, pid)["seen_rules"]))}
    assert len(full["seen_rules"]) == 2
    assert _approve(api, "reviewer", pid, full).status_code == 200


def test_content_changed_without_new_hash_is_refused(elig):
    """Der Pruefwert muss zum gespeicherten Inhalt passen (nicht nur gleich lauten)."""
    factory, api = elig
    pid = _fund(api)
    seen = _seen(api, pid)
    with factory() as db:
        db.query(ProductEligibilityRule).filter_by(product_id=pid).update({"profile_to": 9})
        db.commit()
    _assert_blocked(factory, pid, _approve(api, "reviewer", pid, seen), MISMATCH)


def test_admin_seen_rules_bind_too_when_sent(elig):
    factory, api = elig
    pid = _fund(api)
    (pair,) = _seen(api, pid)["seen_rules"]
    attest = {"single_approver_attestation": True, "attestation_reason": "Einzelfirma (fiktiver Testgrund)."}
    stale = {**attest, "seen_rules": [{**pair, "rule_hash": "0" * 64}]}
    _assert_blocked(factory, pid, _approve(api, "admin", pid, stale), MISMATCH)
    assert _approve(api, "admin", pid, {**attest, "seen_rules": [pair]}).status_code == 200


def test_audit_binds_hash_of_sorted_seen_set_without_product_data(elig):
    from services.product_eligibility_governance import seen_rules_sha256

    factory, api = elig
    pid = _fund(api)
    _second_draft(factory, pid)
    seen = _seen(api, pid)
    pairs = [(r["rule_id"], r["rule_hash"]) for r in seen["seen_rules"]]
    assert seen_rules_sha256(pairs) == seen_rules_sha256(pairs[::-1])
    assert _approve(api, "reviewer", pid, seen).status_code == 200
    (audit,) = _approval_audits(factory, pid)
    assert f"seen_rules_sha256={seen_rules_sha256(pairs)}" in audit
    assert "Hausfonds" not in audit


def test_change_between_handler_read_and_claim_is_refused(elig, monkeypatch):
    """Eine andere Sitzung aendert die Regel, nachdem der Handler sie gelesen
    hat: verglichen wird am gesperrten, frisch gelesenen Stand."""
    import routers.review as review

    factory, api = elig
    pid = _fund(api)
    seen = _seen(api, pid)

    def concurrent_change(_user):
        with factory() as other:
            rule = other.query(ProductEligibilityRule).filter_by(product_id=pid).one()
            rule.profile_to = 9
            _rehash(rule)
            other.commit()

    monkeypatch.setattr(review, "assert_compliance_reviewer_ready", concurrent_change)
    _assert_blocked(factory, pid, _approve(api, "reviewer", pid, seen), MISMATCH)


def test_rule_added_between_handler_read_and_claim_is_refused(elig, monkeypatch):
    import routers.review as review

    factory, api = elig
    pid = _fund(api)
    seen = _seen(api, pid)
    monkeypatch.setattr(review, "assert_compliance_reviewer_ready", lambda _u: _second_draft(factory, pid))
    _assert_blocked(factory, pid, _approve(api, "reviewer", pid, seen), MISMATCH)


def test_rule_is_locked_between_compare_and_commit(elig, monkeypatch):
    """Zwischen Vergleich und Commit kann keine andere Verbindung schreiben."""
    import services.product_eligibility_governance as gov

    factory, api = elig
    pid = _fund(api)
    seen = _seen(api, pid)
    with factory() as db:
        path = db.get_bind().url.database
    outcome = []
    original = gov.approve_rule

    def probing(db, **kw):
        other = sqlite3.connect(path, timeout=0.2)
        try:
            other.execute("UPDATE product_eligibility_rules SET profile_to = 9 WHERE product_id = ?", (pid,))
            other.commit()
            outcome.append("geschrieben")
        except sqlite3.OperationalError as exc:
            outcome.append(str(exc))
        finally:
            other.close()
        return original(db, **kw)

    monkeypatch.setattr(gov, "approve_rule", probing)
    assert _approve(api, "reviewer", pid, seen).status_code == 200
    assert outcome and all("locked" in o for o in outcome), outcome
    assert _rule(factory, pid).profile_to == 7


def test_seen_rule_no_longer_open_is_a_mismatch_but_foreign_firm_stays_404(elig):
    factory, api = elig
    pid = _fund(api)
    seen = _seen(api, pid)
    assert _approve(api, "reviewer_b", pid, seen).status_code == 404
    assert _approve(api, "reviewer", pid, seen).status_code == 200
    again = _approve(api, "reviewer", pid, seen)
    assert again.status_code == 409 and MISMATCH in again.text
    assert _approve(api, "reviewer_b", pid, seen).status_code == 404
    assert len(_approval_audits(factory, pid)) == 1


def test_audit_failure_rolls_back_the_approval(elig, monkeypatch):
    import routers.review as review

    factory, api = elig
    pid = _fund(api)
    seen = _seen(api, pid)

    def broken(*_a, **_k):
        raise RuntimeError("Audit nicht schreibbar (Test)")

    monkeypatch.setattr(review, "log", broken)
    assert _approve(api, "reviewer", pid, seen).status_code == 500
    assert _statuses(factory, pid) == {"draft"} and _approval_audits(factory, pid) == []


def test_role_ui_sends_the_shown_snapshot_and_reloads_after_409():
    """Statisch; das Verhalten im Browser prueft test_livetest_c890_kyc_review_policy_ui."""
    source = (BACKEND.parent / "ares-desktop" / "frontend" / "role-ui.js").read_text(encoding="utf-8")
    click = source.split("async function onEligibilityClick")[1].split("function ensureEligibilityReviewerBox")[0]
    assert "seen_rules: shownRules[productId]" in click
    assert "err.status === 409" in click and "return loadEligibilityDrafts(message)" in click
    # Kein zweites Laden vor der Freigabe.
    assert "eligibility-drafts" not in click and "loadEligibilityDrafts" not in click.split("apiCall(")[0]


# ------------------------------------------------------ N-939-01 Finalitaet
def _text_of(value) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(_text_of(v) for v in value)
    cells = getattr(value, "_cellvalues", None)
    if cells is not None:
        return _text_of(cells)
    plain = getattr(value, "getPlainText", None)
    return plain() if callable(plain) else str(getattr(value, "text", ""))


NON_FINAL = ["vorvertrag", "unpublished", "vertragsvorlage", "depotbank", "gebuehren", "ansicht", "entwurf",
             "vertraulich", "future-mode", "", " ", "NONE", " none ", None, 0, False]


@pytest.mark.parametrize("mode", NON_FINAL)
def test_every_mode_except_explicit_none_is_not_for_signature_and_marked(mode):
    from services.pdf.components.unterschrift import make_signature_block
    from services.pdf.components.watermark import draft_headline, is_final_document

    assert not is_final_document(mode)
    assert draft_headline(mode)
    block = _text_of(make_signature_block(SimpleNamespace(watermark_mode=mode)))
    assert NOT_FOR_SIGNATURE in block and SIGN_LINE not in block


def test_missing_mode_is_not_final_and_explicit_none_is():
    from services.pdf.components.unterschrift import make_signature_block
    from services.pdf.components.watermark import draft_headline

    for ctx in (None, SimpleNamespace()):
        assert NOT_FOR_SIGNATURE in _text_of(make_signature_block(ctx))
    final = _text_of(make_signature_block(SimpleNamespace(watermark_mode="none")))
    assert SIGN_LINE in final and NOT_FOR_SIGNATURE not in final
    assert draft_headline("none") is None


@pytest.mark.parametrize("missing", [None, "", "future-mode"])
def test_not_final_context_is_never_archived(missing):
    import routers.pdf_reports as pr

    ctx = SimpleNamespace(watermark_mode=missing)
    assert pr._archive_final(ctx, None) is None
    assert pr._archive_final_unbound(ctx, None) is None
    assert pr._archive_final(SimpleNamespace(), None) is None
    assert pr._draft_headers(ctx)


@pytest.mark.parametrize("value,blocked", [("none", False), ("vorvertrag", True), (None, True), ("", True)])
def test_signature_gate_needs_explicit_none_if_a_marker_exists(value, blocked):
    from services.signature_artifact import _is_draft_artifact

    doc = SimpleNamespace(content_json=json.dumps({"watermark_mode": value}))
    assert _is_draft_artifact(doc) is blocked
    assert _is_draft_artifact(SimpleNamespace(content_json="{}")) is False


def _pages(pdf: bytes) -> list[str]:
    from pypdf import PdfReader

    return [p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages]


@pytest.mark.parametrize("mode,headline", [
    ("future-mode", "Entwurf – nicht final"),
    (None, "Entwurf – nicht final"),
    ("unpublished", "Entwurf – Soll-Allokation nicht publiziert"),
])
def test_advisory_report_marks_every_page_exactly_once(mode, headline):
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload
    from test_all_pdf_renderers_embed_only_own_fonts import _advisory_payloads

    payload = next(iter(_advisory_payloads().values()))()
    pages = _pages(render_advisory_report_pdf_from_payload(payload, watermark_mode=mode))
    assert pages and all(headline in p for p in pages)
    # Kopfzeile je Seite genau einmal (die letzte Seite nennt sie auch im Hinweis).
    assert all(p.count(headline) == 1 for p in pages[:-1])
    assert NOT_FOR_SIGNATURE in pages[-1] and SIGN_LINE not in pages[-1]
    final = _pages(render_advisory_report_pdf_from_payload(payload, watermark_mode="none"))
    assert SIGN_LINE in final[-1] and not any("Entwurf –" in p or "ENTWURF" in p for p in final)


@pytest.mark.parametrize("mode", ["future-mode", None, "ansicht"])
def test_standard_documents_mark_every_page(mode):
    """Footer-Pfad aller Einzeldokumente, am Risikoprofil gezeigt."""
    from services.pdf.base import RisikoprofilData
    from services.pdf.components.watermark import draft_headline
    from services.pdf.reportlab_renderer import ReportLabRenderer
    from test_cost_disclosure_pdf import _ctx

    data = RisikoprofilData("Testwert", 50, 50, mandate_number="M-TEST")
    ctx = dataclasses.replace(_ctx(), watermark_mode=mode)
    pages = _pages(ReportLabRenderer().render_risikoprofil(ctx, data))
    assert pages and all(draft_headline(mode) in p for p in pages)
    assert any(NOT_FOR_SIGNATURE in p for p in pages) and not any(SIGN_LINE in p for p in pages)


def test_no_customer_document_bypasses_the_signature_gate():
    """Statisches Inventar: Unterschriftsfelder nur ueber ``make_signature_block``."""
    offenders = [
        p.relative_to(BACKEND).as_posix() for base in ("routers", "services") for p in (BACKEND / base).rglob("*.py")
        if re.search(r"make_unterschrift_section|Ort, Datum / (Klient|Anlageberater)", p.read_text(encoding="utf-8"))
    ]
    assert offenders == ["services/pdf/components/unterschrift.py"]
    users = sorted(p.name for p in (BACKEND / "services/pdf/documents").glob("*.py")
                   if "make_signature_block(" in p.read_text(encoding="utf-8"))
    assert users == ["advisory_report.py", "anlagestrategie.py", "contract_signoff.py", "protokoll.py",
                     "risikoprofil.py", "vertrag.py"]


# ------------------------------------------------ N-939-01/-04/-05 readonly-Ansicht
def test_readonly_signoff_view_is_never_signable_and_names_the_draft_reason(session_factory):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "h193-view")
    readonly = _clone_user(session_factory, advisor_id, "readonly")
    body = _signoff_pdf_text(session_factory, mid, readonly)
    assert "Ansicht – nicht abgegeben" in body and "nicht publiziert" in body
    assert NOT_FOR_SIGNATURE in body and SIGN_LINE not in body


def _envelope_hash(session_factory, mid) -> str:
    from services.allocation_publication_gate import evaluate_channel_envelope

    with session_factory() as db:
        decision = evaluate_channel_envelope(db, _mandate(db, mid))
    assert decision.ok and decision.envelope_hash
    return decision.envelope_hash


def test_readonly_view_of_published_decision_has_no_pruefnummer(session_factory):
    """Mutation "_view_decision_ref gibt das Original zurueck" muss hier rot werden."""
    advisor_id, _approver, mid, *_rest = _published(session_factory, "h193-ref")
    readonly = _clone_user(session_factory, advisor_id, "readonly")
    envelope_hash = _envelope_hash(session_factory, mid)
    view = _signoff_pdf_text(session_factory, mid, readonly)
    assert envelope_hash[:12] not in view
    assert NOT_FOR_SIGNATURE in view and SIGN_LINE not in view
    # Gegenprobe: die abgegebene Fassung des Beraters traegt die Pruefnummer.
    final = _signoff_pdf_text(session_factory, mid, advisor_id)
    assert f"Beratungsentscheid: {envelope_hash[:12]}" in final and SIGN_LINE in final


def test_pre_contract_draft_of_published_decision_has_no_pruefnummer(session_factory, monkeypatch):
    import routers.pdf_reports as pr

    advisor_id, _approver, mid, *_rest = _published(session_factory, "h193-vor")
    envelope_hash = _envelope_hash(session_factory, mid)
    monkeypatch.setattr(pr, "kyc_release_is_draft", lambda *_a: True)
    body = _signoff_pdf_text(session_factory, mid, advisor_id)
    assert "vor Vertragsabschluss" in body and envelope_hash[:12] not in body
    assert NOT_FOR_SIGNATURE in body and SIGN_LINE not in body


def test_draft_reasons_drop_pruefnummer_and_view_keeps_mode():
    import routers.pdf_reports as pr
    from test_cost_disclosure_pdf import _ctx

    ref = {"envelope_hash": "a" * 64, "fassung": "1", "ic_release_status": "UNRELEASED"}
    final = dataclasses.replace(_ctx(), watermark_mode="none", decision_ref=ref)
    for mode in ("depotbank", "gebuehren", "vertragsvorlage"):
        draft = pr._with_draft_reason(final, mode)
        assert draft.watermark_mode == mode and draft.decision_ref == {"ic_release_status": "UNRELEASED"}
    view = dataclasses.replace(final, watermark_mode="ansicht")
    marked = pr._with_draft_reason(view, "gebuehren")
    assert (marked.watermark_mode, marked.view_reason) == ("ansicht", "gebuehren")
    assert pr._view_decision_ref({"allocation_free": True}, True) == {"allocation_free": True}


# ------------------------------------------------------------ N-939-03 Seed-Filter
BUCKETS = ("Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet")
STAMP = "2020-01-01T00:00:00.000Z"


def _returns(db, year, source, *, sub=None):
    from models.snapshots import AssetClassAnnualReturn

    for asset_class in (BUCKETS if sub is None else ("Aktien",)):
        db.add(AssetClassAnnualReturn(id=str(uuid.uuid4()), year=year, asset_class=asset_class, return_bps=300,
                                      sub_asset_class=sub, source=source, created_at=STAMP, updated_at=STAMP))
    db.commit()


def test_production_drift_never_uses_seed_returns(session_factory, monkeypatch):
    import config
    from models.snapshots import AssetClassAnnualReturn, StrategySnapshot
    from models.users import User
    from routers.snapshots import get_drift

    advisor_id, mid, _aid, _run = _finalized(session_factory, "h193-drift")
    with session_factory() as db:
        db.query(AssetClassAnnualReturn).delete()
        db.add(StrategySnapshot(
            id=str(uuid.uuid4()), mandate_id=mid, snapshot_date="2020-01-01", advisory_assets_rappen=10_000_000,
            risk_profile_score=50, risk_profile_label="Testwert", soll_equities_bps=4000, soll_bonds_bps=3000,
            soll_real_estate_bps=1500, soll_liquidity_bps=500, soll_alternatives_bps=1000, created_by=advisor_id,
            created_at=STAMP, updated_at=STAMP))
        db.commit()
        _returns(db, 2021, "seed")
        user = db.query(User).filter(User.id == advisor_id).one()
        monkeypatch.setattr(config.settings, "app_env", "development")
        assert get_drift(mid, db, user).has_drift_data is True  # Quellbetrieb unveraendert
        monkeypatch.setattr(config.settings, "app_env", "production")
        assert get_drift(mid, db, user).has_drift_data is False
        _returns(db, 2022, "test-freigabe")
        assert get_drift(mid, db, user).has_drift_data is True


def test_production_sub_asset_benchmark_never_uses_seed_returns(session_factory):
    from models.snapshots import AssetClassAnnualReturn
    from services.backtest_strategy import load_sub_asset_annual_returns_matrix, run_strategy_backtest

    _advisor, mid, _aid, _run = _finalized(session_factory, "h193-sub")
    with session_factory() as db:
        db.query(AssetClassAnnualReturn).delete()
        db.commit()
        for year in (2021, 2022):
            _returns(db, year, "test-freigabe")
            _returns(db, year, "seed", sub="equities_ch")
        assert sorted(load_sub_asset_annual_returns_matrix(db, production_mode=False)) == [2021, 2022]
        assert load_sub_asset_annual_returns_matrix(db, production_mode=True) == {}

        def benchmark_missing(production):
            result = run_strategy_backtest(db, _mandate(db, mid), production_mode=production,
                                           benchmark_sub_weights_bps={"equities_ch": 10000})
            return any("Sub-Asset-Benchmark konnte nicht" in w for w in result["warnings"])

        assert benchmark_missing(False) is False
        assert benchmark_missing(True) is True  # Durchreichung production_mode


def test_every_production_caller_states_the_finality_explicitly():
    """Dataclass-/Funktionsdefault "none" wird produktiv nie stillschweigend benutzt."""
    calls = []
    for base in ("routers", "services"):
        for path in (BACKEND / base).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "PDFContext(" not in source and "render_advisory_report_pdf" not in source:
                continue
            for node in ast.walk(ast.parse(source)):
                name = getattr(getattr(node, "func", None), "id", None)
                if name in ("PDFContext", "render_advisory_report_pdf", "render_advisory_report_pdf_from_payload"):
                    calls.append((path.name, name, "watermark_mode" in {k.arg for k in node.keywords}))
    assert len(calls) == 3 and all(explicit for *_rest, explicit in calls), calls


def test_contract_signoff_has_no_statement_after_return():
    source = (BACKEND / "services/pdf/documents/contract_signoff.py").read_text(encoding="utf-8")
    (func,) = [n for n in ast.walk(ast.parse(source))
               if isinstance(n, ast.FunctionDef) and n.name == "build_contract_signoff_flowables"]
    returns = [i for i, n in enumerate(func.body) if isinstance(n, ast.Return)]
    assert returns == [len(func.body) - 1]


def test_final_client_information_signature_block_is_unchanged(monkeypatch):
    """Vorlagen-Pin ARES-KI-FIDLEG-5: die finale Fassung bekommt genau den
    bisherigen Unterschriftsblock (gleiche Argumente, gleiche Flowables); nur
    Nicht-Final-Fassungen aendern sich. Deshalb keine neue Vorlagenversion."""
    from types import SimpleNamespace

    from services.pdf.components import unterschrift

    calls = []
    monkeypatch.setattr(unterschrift, "make_unterschrift_section", lambda **kw: calls.append(kw) or ["BLOCK"])
    kwargs = {"left_label": "Kunde", "right_label": "Berater"}
    assert unterschrift.make_signature_block(SimpleNamespace(watermark_mode="none"), **kwargs) == ["BLOCK"]
    assert calls == [kwargs]
    assert unterschrift.make_signature_block(SimpleNamespace(watermark_mode="gebuehren"), **kwargs) != ["BLOCK"]
    assert len(calls) == 1
