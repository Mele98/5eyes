"""H12 Hygienepaket (CCX P2-P4 + H11) -- Regressionen mit den P1/P2-Fixtures.

* N-910-11: Risikoprofil und allgemeiner Vertrag sind allokationsfrei; das
  Beratungsvermoegen kommt aus der Vermoegenserfassung. Das Risikoprofil wird
  auch bei nicht publizierter Soll-Allokation final archiviert und ist
  unterschreibbar.
* N-910-12: die WIRKUNG des Publish-Gates je gegateter Route (Verhalten + AST).
* N-909-21 E / Zusatz FRESH: die FX-Ausnahme versiegelter Laeufe verlangt
  Bewertungsbindung und einen FRESHen Entscheid.
* N-910-13/-14: ohne Schluessel gilt kein Hash; Schluesselversion im Entscheid
  und im HMAC, ``CCX_APPROVAL_KEY_ROTATED`` / ``..._VERSION_MISSING``.
* N-910-15: Plausibilisierung der Ein-Personen-Firma.
* N-910-16: OperationalError retryable, InternalError nur mit Guard-Text.
* N-908-07/-08: Laufzeitschutz nach einem Flush ohne Arbeit; Massen-Update
  per Parametersatz bricht fail-closed ab.
* Codex c: die Altbestands-Testhilfe ist im Produktivpfad weder importierbar
  noch erreichbar.

Die API-nahen Faelle (N-909-20, Mutationen G/K, FX-Quelleninventar) stehen in
``tests/test_h12_ccx_hygiene_api.py``.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.exc import InternalError, OperationalError

from core.reason_codes import DomainError
from tests.test_ccx_p1_snapshot_hash import BACKEND, session_factory  # noqa: F401
from tests.test_ccx_p2_invalidation import _envelope, _ids, _mutate_goal
from tests.test_ccx_p4_allocation_publish import (
    _finalized,
    _mandate,
    _overview,
    _publish,
    _published,
    _second_approver,
    _state,
)
from tests.test_finalize_mandate_lock import _FakeRequest

REPO = BACKEND.parent


def _text(body: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(body)).pages)


def _user(db, user_id):
    from models.users import User

    return db.query(User).filter(User.id == user_id).one()


def _risk_profile_docs(db, mid):
    from models.review import ContractDocument

    return db.query(ContractDocument).filter(
        ContractDocument.mandate_id == mid, ContractDocument.document_type == "Risikoprofilierung",
        ContractDocument.deleted_at.is_(None),
    ).all()


# ── N-910-11 ─────────────────────────────────────────────────────────────────


def test_risk_profile_is_final_archived_and_signable_while_allocation_unpublished(session_factory):
    """Vorher (69b30854): Entwurf "Soll-Allokation nicht publiziert", 0 Archiv,
    nicht signierbar. Jetzt: final, 1 Archiv, signierbar -- obwohl die Soll-
    Allokation nicht publiziert ist (Gegenprobe im Test: die Kunden-PDFs MIT
    Allokation bleiben Entwurf)."""
    import services.allocation_publication_gate as gate
    from routers.pdf_reports import get_risikoprofil_pdf
    from services.signature_artifact import assert_signable_artifact

    advisor_id, mid, _aid, _run = _finalized(session_factory, "h12-rp")
    with session_factory() as db:
        assert gate.customer_document_watermark(db, _mandate(db, mid)) == "unpublished"  # Vorbedingung
        assert _risk_profile_docs(db, mid) == []
        response = get_risikoprofil_pdf(mandate_id=mid, request=_FakeRequest(), db=db,
                                        current_user=_user(db, advisor_id))
        assert response.status_code == 200
        body = _text(response.body)
        assert "nicht publiziert" not in body and "ENTWURF" not in body.upper()
        docs = _risk_profile_docs(db, mid)
        assert len(docs) == 1
        assert_signable_artifact(docs[0])


def test_contract_and_risk_profile_print_advisory_wealth_from_capture(session_factory):
    """Beratungsvermoegen = aktive Positionen mit Zuordnung Beratungsvermoegen
    heute, nicht der Generierungs-Snapshot der Soll-Allokation. Eine Position
    "Anderes Vermoegen" zaehlt nicht; der Snapshot bleibt unveraendert."""
    from models.wealth import WealthPosition
    from routers.pdf_reports import get_risikoprofil_pdf, get_vertrag_pdf

    advisor_id, mid, _aid, _run = _finalized(session_factory, "h12-cap")
    with session_factory() as db:
        mandate = _mandate(db, mid)
        snapshot = db.execute(text("SELECT advisory_wealth_at_generation_rappen FROM target_allocations "
                                   "WHERE mandate_id = :m AND is_current = 1"), {"m": mid}).scalar()
        assert snapshot == 500_000_00  # Fixture: eine CHF-Position 500'000
        template = db.query(WealthPosition).filter(WealthPosition.client_id == mandate.client_id).first()
        for label, assignment, amount in (("Konto neu", "Beratungsvermögen", 123_456_00),
                                          ("Ferienwohnung", "Anderes Vermögen", 900_000_00)):
            clone = {c.name: getattr(template, c.name) for c in WealthPosition.__table__.columns}
            clone.update(id=f"h12-{label[:5]}-{mid[:6]}", label=label, assignment=assignment,
                         current_value_rappen=amount, currency="CHF")
            db.add(WealthPosition(**clone))
        db.commit()
    with session_factory() as db:
        user = _user(db, advisor_id)
        for call in (lambda: get_risikoprofil_pdf(mandate_id=mid, request=_FakeRequest(), db=db, current_user=user),
                     lambda: get_vertrag_pdf(mandate_id=mid, document_id=None, db=db, current_user=user)):
            body = _text(call().body)
            assert "Beratungsvermögen CHF 623'456" in body, body[:400]
            assert "500'000" not in body
        assert db.execute(text("SELECT advisory_wealth_at_generation_rappen FROM target_allocations "
                               "WHERE mandate_id = :m AND is_current = 1"), {"m": mid}).scalar() == snapshot


# ── N-910-12: Wirkung des Gates je gegateter Route ──────────────────────────


def _gated_calls():
    import routers.pdf_reports as pdf

    req = _FakeRequest
    return {
        "get_assetallocation_pdf": lambda mid, db, u: pdf.get_assetallocation_pdf(
            mandate_id=mid, db=db, current_user=u, expected_allocation_id=None),
        "get_portfolio_pdf": lambda mid, db, u: pdf.get_portfolio_pdf(
            mandate_id=mid, request=req(), db=db, current_user=u),
        "get_protokoll_pdf": lambda mid, db, u: pdf.get_protokoll_pdf(
            mandate_id=mid, request=req(), db=db, current_user=u),
        "get_contract_signoff_pdf": lambda mid, db, u: pdf.get_contract_signoff_pdf(
            mandate_id=mid, db=db, current_user=u),
    }


@pytest.mark.parametrize("route", [
    "get_assetallocation_pdf", "get_portfolio_pdf", "get_protokoll_pdf", "get_contract_signoff_pdf"])
def test_gated_route_marks_unpublished_draft_and_final_after_publish(session_factory, route):
    """N-910-12: je gegateter Route die WIRKUNG -- nicht publiziert: Wasserzeichen
    "Entwurf - Soll-Allokation nicht publiziert" (und damit kein Archiv); nach
    der Publikation ohne diese Markierung. Mutation N2f (Gate-Ergebnis
    verworfen, hier am Portfolio) wird rot."""
    call = _gated_calls()[route]
    advisor_id, mid, _aid, _run = _finalized(session_factory, f"h12-g-{route[4:12]}")
    with session_factory() as db:
        draft = _text(call(mid, db, _user(db, advisor_id)).body)
    assert "nicht publiziert" in draft and "ENTWURF" in draft.upper(), route
    _publish(session_factory, mid, _second_approver(session_factory, advisor_id))
    with session_factory() as db:
        final = _text(call(mid, db, _user(db, advisor_id)).body)
    assert "nicht publiziert" not in final, route


def test_every_gated_pdf_route_uses_the_gate_result():
    """N-910-12 (statisch, alle gegateten Routen): das Ergebnis von
    ``_mark_unpublished`` wird dem Kontext ``ctx`` zugewiesen -- ein verworfener
    Aufruf (Mutation N2f) faellt auf, auch fuer Routen ohne Verhaltenstest."""
    from tests.test_ccx_p4_allocation_publish import CUSTOMER_ENDPOINTS, _functions

    functions = _functions("routers/pdf_reports.py")

    def uses_result(fn) -> bool:
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "_mark_unpublished"]
        if not calls:
            return False
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "ctx" for t in node.targets):
                if any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_mark_unpublished"
                       for n in ast.walk(node.value)):
                    return True
        return False

    gated = [n for n in CUSTOMER_ENDPOINTS["routers/pdf_reports.py"] if n != "get_advisory_report_pdf"]
    for name in gated:
        assert uses_result(functions[name]), f"{name}: Ergebnis von _mark_unpublished nicht an ctx zugewiesen"
    mutant = ast.parse("def r(db, m):\n    ctx = build()\n    _mark_unpublished(ctx, db, m)\n").body[0]
    assert not uses_result(mutant)


# ── N-909-21 E + Zusatz: Ausnahme nur SEALED + FRESH + Bewertungsbindung ─────


def test_sealed_run_exemption_requires_fresh_decision_and_valuation_binding(session_factory, monkeypatch):
    """Ein invalidierter (STALE) versiegelter Lauf bekommt keine FX-Ausnahme --
    P2 laesst dabei ``status`` SEALED stehen und setzt nur ``freshness_status``
    (hier belegt). Ebenso nicht ohne Bewertungsbindung (P1-Altbestand)."""
    import services.print_fx_gate as gate
    from models.mandates import Mandate
    from services.currency.fx_rates import FxBasisError

    monkeypatch.setattr(gate, "mandate_amount_currencies", lambda db, m: {"CHF", "USD"})  # USD unbelegt
    ids = _ids(session_factory, "h12-fresh")
    with session_factory() as db:
        mandate = db.get(Mandate, ids["mid"])
        assert gate.run_is_sealed(db, mandate, ids["run"]) is True
        gate.assert_print_fx_basis_current(db, mandate, run_id=ids["run"])  # Ausnahme greift
    with session_factory() as db:
        db.info["ares_actor_user_id"] = ids["advisor"]
        _mutate_goal(db, ids)
        db.commit()
    with session_factory() as db:
        assert tuple(_envelope(db, ids["envelope"])[:2]) == ("SEALED", "STALE")
        mandate = db.get(Mandate, ids["mid"])
        assert gate.run_is_sealed(db, mandate, ids["run"]) is False
        with pytest.raises(FxBasisError) as exc:
            gate.assert_print_fx_basis_current(db, mandate, run_id=ids["run"])
        assert exc.value.reason_code == "CCX_FX_BASIS_MISSING"

    ids = _ids(session_factory, "h12-noval")
    with session_factory() as db:
        for trigger in db.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger' "
                                       "AND tbl_name = 'advisory_envelope_bindings'")).scalars().all():
            db.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
        db.execute(text("DELETE FROM advisory_envelope_bindings WHERE envelope_id = :e AND binding_kind = :k"),
                   {"e": ids["envelope"], "k": gate.VALUATION_BINDING_KIND})
        db.commit()
    with session_factory() as db:
        mandate = db.get(Mandate, ids["mid"])
        assert tuple(_envelope(db, ids["envelope"])[:2]) == ("SEALED", "FRESH")
        assert gate.run_is_sealed(db, mandate, ids["run"]) is False
        with pytest.raises(FxBasisError):
            gate.assert_print_fx_basis_current(db, mandate, run_id=ids["run"])


# ── N-910-13 / N-910-14: Schluessel und Schluesselversion ───────────────────


def _no_key(monkeypatch):
    import services.allocation_publication_approval as approval
    from services.tenant_crypto import TenantCryptoError

    def unavailable(*_a, **_k):
        raise TenantCryptoError("DEK nicht verfuegbar (Test)")

    monkeypatch.setattr(approval, "get_tenant_dek", unavailable)


def test_without_key_the_stored_hash_is_not_trusted(session_factory, monkeypatch):
    """N-910-13 (Pruefer-Probe uebernommen): ohne Schluessel ist eine bestehende
    Publikation ungueltig und ein neuer Publish wird abgelehnt (fail-closed).
    Mutation N2b ("ohne Schluessel gilt der gespeicherte Hash") wird rot."""
    advisor_id, _approver, mid, *_rest = _published(session_factory, "h12-nokey")
    assert _state(session_factory, mid).published
    _no_key(monkeypatch)
    state = _state(session_factory, mid)
    assert (state.status, state.reason_code) == ("PUBLICATION_INVALID", "CCX_APPROVAL_BINDING_MISSING")
    assert _state(session_factory, mid, deep=False).status == "PUBLICATION_INVALID"

    advisor2, mid2, _aid2, _run2 = _finalized(session_factory, "h12-nokey2")
    approver2 = _second_approver(session_factory, advisor2)
    with pytest.raises(DomainError) as exc:
        _publish(session_factory, mid2, approver2)
    assert exc.value.reason_code == "CCX_APPROVAL_BINDING_MISSING"


def test_dek_rotation_is_named_key_rotated_and_republish_binds_new_version(session_factory):
    from services.tenant_crypto import rotate_tenant_dek

    advisor_id, _approver, mid, *_rest, decision = _published(session_factory, "h12-rot")
    assert decision.approval_key_version >= 1
    with session_factory() as db:
        rotate_tenant_dek(db, decision.tenant_id)
        db.commit()
    state = _state(session_factory, mid)
    assert (state.status, state.reason_code) == ("PUBLICATION_INVALID", "CCX_APPROVAL_KEY_ROTATED")
    assert _state(session_factory, mid, deep=False).reason_code == "CCX_APPROVAL_KEY_ROTATED"


def test_legacy_publication_without_key_version_is_fail_closed(session_factory):
    advisor_id, _approver, mid, *_rest, decision = _published(session_factory, "h12-legacy")
    with session_factory() as db:
        db.execute(text("DROP TRIGGER IF EXISTS trg_allocation_publication_decisions_no_update"))
        db.execute(text("UPDATE allocation_publication_decisions SET approval_key_version = NULL WHERE id = :i"),
                   {"i": decision.id})
        db.commit()
    state = _state(session_factory, mid)
    assert (state.status, state.reason_code) == ("PUBLICATION_INVALID", "CCX_APPROVAL_KEY_VERSION_MISSING")


def test_key_version_is_part_of_the_hmac_record(session_factory):
    """Spalte und Tenant auf dieselbe (falsche) Version gesetzt, Schluessel
    unveraendert: die Versionen stimmen ueberein, der HMAC aber nicht (die
    Version steht im Record) -> ungueltig."""
    advisor_id, _approver, mid, *_rest, decision = _published(session_factory, "h12-inhash")
    forged = int(decision.approval_key_version) + 6
    with session_factory() as db:
        db.execute(text("DROP TRIGGER IF EXISTS trg_allocation_publication_decisions_no_update"))
        db.execute(text("UPDATE allocation_publication_decisions SET approval_key_version = :v WHERE id = :i"),
                   {"v": forged, "i": decision.id})
        db.execute(text("UPDATE tenants SET dek_version = :v WHERE id = :t"), {"v": forged, "t": decision.tenant_id})
        db.commit()
    state = _state(session_factory, mid)
    assert (state.status, state.reason_code) == ("PUBLICATION_INVALID", "CCX_APPROVAL_BINDING_MISSING")


def test_republish_after_rotation_binds_the_new_key_version(session_factory):
    from services.tenant_crypto import rotate_tenant_dek
    from tests.test_ccx_p1_snapshot_hash import _finalizable_run, _finalize

    advisor_id, approver, mid, aid, _run, decision = _published(session_factory, "h12-rerot")
    with session_factory() as db:
        rotate_tenant_dek(db, decision.tenant_id)
        db.commit()
    assert _state(session_factory, mid).reason_code == "CCX_APPROVAL_KEY_ROTATED"
    _a, _m, _aid, run2 = _finalizable_run(session_factory, "h12-rerot2", mandate=(advisor_id, mid, aid))
    _finalize(session_factory, advisor_id, mid, run2)
    fresh = _publish(session_factory, mid, approver)
    assert fresh.approval_key_version == int(decision.approval_key_version) + 1
    assert _state(session_factory, mid).published


# ── N-910-15: Ein-Personen-Firma plausibilisieren ───────────────────────────


def test_single_person_firm_needs_exactly_one_active_publisher(session_factory):
    from models.users import User
    from routers.tenants import update_my_tenant
    from schemas.tenants import TenantSelfServiceUpdate
    from tests.test_ccx_p1_snapshot_hash import _finalizable_run

    advisor_id, mid, _aid, _run = _finalizable_run(session_factory, "h12-spf")
    colleague = _second_approver(session_factory, advisor_id)
    with session_factory() as db:
        user = _user(db, advisor_id)
        tenant_id = _mandate(db, mid).tenant_id
        user.role, user.tenant_id = "admin", tenant_id
        db.query(User).filter(User.id == colleague).update({"tenant_id": tenant_id})
        others = [u.id for u in db.query(User).filter(User.role.in_(("admin", "advisor")), User.is_active == 1).all()
                  if u.id not in (advisor_id, colleague) and (u.tenant_id or "main") == (tenant_id or "main")]
        db.query(User).filter(User.id.in_(others)).update({"is_active": 0}, synchronize_session=False)
        db.commit()
    with session_factory() as db:
        with pytest.raises(DomainError) as exc:
            update_my_tenant(TenantSelfServiceUpdate(single_person_firm=True), _FakeRequest(), db=db,
                             current_user=_user(db, advisor_id))
        assert exc.value.reason_code == "CCX_SINGLE_PERSON_FIRM_IMPLAUSIBLE" and exc.value.http_status == 409
        assert exc.value.extra["eligible_approver_count"] == 2
    with session_factory() as db:
        assert db.execute(text("SELECT single_person_firm FROM tenants WHERE id = :t"), {"t": tenant_id}).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM audit_log WHERE field_name = 'tenant.single_person_firm'")
                          ).scalar() == 0
        db.query(User).filter(User.id == colleague).update({"is_active": 0})
        db.commit()
    with session_factory() as db:  # genau eine berechtigte Person -> zulaessig
        result = update_my_tenant(TenantSelfServiceUpdate(single_person_firm=True), _FakeRequest(), db=db,
                                  current_user=_user(db, advisor_id))
        assert result.single_person_firm == 1
    with session_factory() as db:  # Zuruecksetzen ist immer zulaessig
        db.query(User).filter(User.id == colleague).update({"is_active": 1})
        db.commit()
        result = update_my_tenant(TenantSelfServiceUpdate(single_person_firm=False), _FakeRequest(), db=db,
                                  current_user=_user(db, advisor_id))
        assert result.single_person_firm == 0


# ── N-910-16: enger Fehler-Fang ─────────────────────────────────────────────


def _fail_inside_publication(monkeypatch, exc):
    import services.allocation_publication_gate as gate

    original = gate._audit

    def audit(db, **kw):
        if kw.get("field_name") == gate.AUDIT_PUBLISHED:
            raise exc
        return original(db, **kw)

    monkeypatch.setattr(gate, "_audit", audit)


def test_operational_error_is_retryable_not_a_race(session_factory, monkeypatch):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "h12-op")
    approver = _second_approver(session_factory, advisor_id)
    overview = _overview(session_factory, mid)
    _fail_inside_publication(monkeypatch, OperationalError("UPDATE x", {}, Exception("database is locked")))
    with pytest.raises(DomainError) as exc:
        _publish(session_factory, mid, approver, overview=overview)
    assert exc.value.reason_code == "CCX_PUBLICATION_RETRYABLE"
    assert exc.value.http_status == 503 and exc.value.extra["retryable"] is True
    with session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM allocation_active_publications")).scalar() == 0


def test_internal_error_without_guard_text_is_not_masked_as_race(session_factory, monkeypatch):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "h12-int")
    approver = _second_approver(session_factory, advisor_id)
    overview = _overview(session_factory, mid)
    _fail_inside_publication(monkeypatch, InternalError("INSERT x", {}, Exception("server closed the connection")))
    with pytest.raises(InternalError):
        _publish(session_factory, mid, approver, overview=overview)


def test_internal_error_with_guard_text_maps_to_domain_code(session_factory, monkeypatch):
    advisor_id, mid, _aid, _run = _finalized(session_factory, "h12-guard")
    approver = _second_approver(session_factory, advisor_id)
    overview = _overview(session_factory, mid)
    _fail_inside_publication(monkeypatch, InternalError("INSERT x", {}, Exception("CCX_PUBLICATION_RACE")))
    with pytest.raises(DomainError) as exc:
        _publish(session_factory, mid, approver, overview=overview)
    assert exc.value.reason_code == "CCX_PUBLICATION_RACE"


# ── N-908-07 / N-908-08 ─────────────────────────────────────────────────────


def test_noop_flush_then_core_dml_in_same_transaction_invalidates(session_factory):
    """N-908-07 (Pruefer-Probe uebernommen): Flush ohne Arbeit, danach Core-DML
    am ORM vorbei in DERSELBEN Transaktion -> STALE im selben Commit (vorher
    blieb der gespeicherte Status FRESH, nur der Pull fing es ab)."""
    from sqlalchemy import update

    import models.snapshots as snapshots
    from models.users import User
    from models.wealth import Goal

    ids = _ids(session_factory, "h12-noop")
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
        db.get(User, ids["advisor"]).email = "h12-noop@example.invalid"
        db.flush(objects=[goal])
        assert snapshots._FLUSH_DEPTH.get() == 1  # Vorbedingung: der Zaehler haengt
        db.connection().execute(update(Goal).where(Goal.mandate_id == ids["mid"]).values(weight_bps=4300))
        db.commit()
    with session_factory() as db:
        assert _envelope(db, ids["envelope"])[1] == "STALE"


def test_sqlalchemy_sets_flushing_during_before_flush():
    """Kanarienvogel fuer N-908-07: der Schutz liest ``Session._flushing``."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session

    seen = []
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        event.listen(session, "before_flush", lambda s, *_a: seen.append(s._flushing))
        from models.users import User  # noqa: F401  (beliebiges gemapptes Objekt)
        session.add(User(id="canary", email="c@example.invalid", role="advisor"))
        with pytest.raises(Exception):  # Tabelle fehlt -- uns interessiert nur before_flush
            session.flush()
        assert seen == [True] and session._flushing is False


def test_bulk_update_mappings_on_dependency_table_fails_closed(session_factory):
    """N-908-08 (Info, kein Umbau): Massen-Update je Parametersatz auf einer
    Abhaengigkeitstabelle bricht im Laufzeitschutz ab -- keine stille
    Aenderung, der Entscheid bleibt nicht unbemerkt FRESH bei geaenderten Daten."""
    from sqlalchemy.exc import StatementError

    from models.wealth import Goal

    ids = _ids(session_factory, "h12-bulk")
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == ids["mid"], Goal.rank == 1).one()
        goal_id, before = goal.id, goal.target_amount_rappen
        with pytest.raises(StatementError):
            db.bulk_update_mappings(Goal, [{"id": goal_id, "target_amount_rappen": before + 1}])
        db.rollback()
    with session_factory() as db:
        assert db.get(Goal, goal_id).target_amount_rappen == before
        assert _envelope(db, ids["envelope"])[1] == "FRESH"


# ── Codex c: Altbestands-Testhilfe nie im Produktivpfad ─────────────────────


def _product_files():
    skip = {"tests", "node_modules", ".venv", "venv", "__pycache__"}
    for path in sorted(BACKEND.rglob("*.py")):
        if not skip & set(path.relative_to(BACKEND).parts):
            yield path


def test_legacy_publication_helper_is_unreachable_from_production():
    offenders = []
    for path in _product_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(n == "tests" or n.startswith("tests.") for n in names):
                offenders.append(path.relative_to(BACKEND).as_posix())
            if isinstance(node, ast.Constant) and node.value in ("assume_published_allocation",
                                                                  "ccx_p4_publication_support"):
                offenders.append(path.relative_to(BACKEND).as_posix())
    assert offenders == []
    build = (REPO / "ares-desktop" / "scripts" / "build-backend.js").read_text(encoding="utf-8")
    assert "'tests" not in build and '"tests' not in build  # PyInstaller sammelt das Paket nicht ein
    # Ausserhalb von pytest verweigert die Hilfe den Import.
    out = subprocess.run([sys.executable, "-c", "import tests.ccx_p4_publication_support"], cwd=str(BACKEND),
                         capture_output=True, text=True, timeout=120)
    assert out.returncode != 0 and "reine Testhilfe" in out.stderr, out.stderr[-500:]
