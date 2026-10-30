"""ELIG-OVERRIDE-CAPTURE-001 -- capture path for product eligibility overrides.

A governed rule with requires_override=1 blocks Finalize until a valid,
four-eyes-approved override bound to the CURRENT eligibility decision
exists. Before this change no endpoint could create one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from test_elig_finalization_eligibility import _eligibility_findings, _setup_run  # noqa: E402

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.product_eligibility import ProductEligibilityOverride, ProductEligibilityRule  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402

REASON = "Kunde verlangt das Produkt ausdruecklich; Risiken besprochen und dokumentiert."


def _user(user_id: str, role: str, tenant_id: str | None = None) -> User:
    return User(id=user_id, username=user_id, password_hash="h", full_name=user_id,
                role=role, is_active=1, tenant_id=tenant_id)


@pytest.fixture()
def session_factory(tmp_path):
    # File DB (not :memory:): the TestClient serves requests from another thread.
    engine = create_engine(f"sqlite:///{tmp_path / 'override.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def api(session_factory):
    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    state = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    with TestClient(app) as client:
        def call(method, path, user, **kwargs):
            state["user"] = user
            return client.request(method, path, **kwargs)
        yield call
    app.dependency_overrides.clear()


def _base(ctx) -> str:
    return f"/mandates/{ctx['mandate']}/recommendations/{ctx['run']}/eligibility-overrides"


def _override_ctx(session_factory, monkeypatch, suffix):
    ctx = _setup_run(session_factory, monkeypatch, suffix=suffix, rule_kwargs={"requires_override": 1})
    ctx["advisor_user"] = _user(ctx["advisor"], "advisor")
    ctx["admin_user"] = _user(f"{suffix}-admin", "admin")
    return ctx


def _request_and_approve(api, ctx):
    created = api("POST", _base(ctx), ctx["advisor_user"],
                  json={"product_id": ctx["product"], "reason_text": REASON})
    assert created.status_code == 201, created.text
    approved = api("POST", _base(ctx) + f"/{created.json()['id']}/approve", ctx["admin_user"])
    assert approved.status_code == 201, approved.text
    return created.json(), approved.json()


def _blocked(session_factory, ctx) -> bool:
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    return any("OVERRIDE_EVIDENCE_MISSING" in e for e in errors)


def test_without_override_finalize_is_blocked(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "no-ovr")
    assert _blocked(session_factory, ctx)
    listing = api("GET", _base(ctx), ctx["advisor_user"])
    assert listing.status_code == 200
    [item] = listing.json()["items"]
    assert item["product_id"] == ctx["product"] and item["has_valid_override"] is False


def test_approved_override_unblocks_finalize(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "ok-ovr")
    request, approval = _request_and_approve(api, ctx)
    assert request["state"] == "pending" and approval["approved_by"] == ctx["admin_user"].id
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    assert errors == []
    [item] = api("GET", _base(ctx), ctx["advisor_user"]).json()["items"]
    assert item["has_valid_override"] is True
    assert sorted(o["state"] for o in item["overrides"]) == ["approved", "valid"]
    again = api("POST", _base(ctx) + f"/{request['id']}/approve", _user("second-admin", "admin"))
    assert again.status_code == 409
    assert again.json()["detail"]["reason_code"] == "OVERRIDE_NOT_PENDING"
    with session_factory() as s:
        rows = s.query(ProductEligibilityOverride).filter(
            ProductEligibilityOverride.recommendation_run_id == ctx["run"]).all()
        assert len(rows) == 2  # append-only: request row + approval row
        trail = s.query(AuditLog).filter(AuditLog.table_name == "product_eligibility_overrides").all()
        assert {r.record_id for r in trail} == {r.id for r in rows}


def test_pending_request_alone_is_no_evidence(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "pending")
    created = api("POST", _base(ctx), ctx["advisor_user"],
                  json={"product_id": ctx["product"], "reason_text": REASON})
    assert created.status_code == 201
    assert _blocked(session_factory, ctx)


def test_requester_cannot_approve_own_override(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "self")
    created = api("POST", _base(ctx), ctx["advisor_user"],
                  json={"product_id": ctx["product"], "reason_text": REASON}).json()
    response = api("POST", _base(ctx) + f"/{created['id']}/approve", ctx["advisor_user"])
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "FOUR_EYES_REQUIRED"
    assert _blocked(session_factory, ctx)


@pytest.mark.parametrize("reason", ["", "   ", "zu kurz"])
def test_missing_reason_is_rejected(session_factory, monkeypatch, api, reason):
    ctx = _override_ctx(session_factory, monkeypatch, f"reason-{len(reason)}")
    response = api("POST", _base(ctx), ctx["advisor_user"],
                   json={"product_id": ctx["product"], "reason_text": reason})
    assert response.status_code == 422
    with session_factory() as s:
        assert s.query(ProductEligibilityOverride).count() == 0


def test_foreign_mandate_is_not_found(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "foreign")
    stranger = _user("foreign-advisor", "advisor")
    for method, path, kwargs in (
        ("GET", _base(ctx), {}),
        ("POST", _base(ctx), {"json": {"product_id": ctx["product"], "reason_text": REASON}}),
    ):
        response = api(method, path, stranger, **kwargs)
        assert response.status_code in (403, 404), response.text
    request = api("POST", _base(ctx), ctx["advisor_user"],
                  json={"product_id": ctx["product"], "reason_text": REASON}).json()
    response = api("POST", _base(ctx) + f"/{request['id']}/approve", stranger)
    assert response.status_code in (403, 404)
    assert _blocked(session_factory, ctx)


def test_foreign_tenant_admin_is_not_found(session_factory, monkeypatch, api):
    from config import settings

    from models.mandates import Mandate

    ctx = _override_ctx(session_factory, monkeypatch, "tenant")
    with session_factory() as s:
        s.get(Mandate, ctx["mandate"]).tenant_id = "firm-a"
        s.commit()
    monkeypatch.setattr(settings, "strict_tenant_isolation", True, raising=False)
    # Positive control: the admin of the mandate's own firm is admitted.
    own = api("GET", _base(ctx), _user("own-admin", "admin", tenant_id="firm-a"))
    assert own.status_code == 200, own.text
    response = api("GET", _base(ctx), _user("other-admin", "admin", tenant_id="other-firm"))
    assert response.status_code in (403, 404), response.text


def test_client_role_is_forbidden(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "client-role")
    response = api("POST", _base(ctx), _user("some-client", "client"),
                   json={"product_id": ctx["product"], "reason_text": REASON})
    assert response.status_code == 403


def test_override_is_stale_after_new_eligibility_decision(session_factory, monkeypatch, api):
    """A new rule version (new rule hash) is a new eligibility decision: the
    old override no longer verifies, Finalize blocks again."""
    ctx = _override_ctx(session_factory, monkeypatch, "stale")
    _request_and_approve(api, ctx)
    assert not _blocked(session_factory, ctx)
    with session_factory() as s:
        rule = s.get(ProductEligibilityRule, ctx["rule"])
        rule.version = int(rule.version or 1) + 1
        rule.rule_hash = f"{rule.rule_hash}-v2"
        s.commit()
    assert _blocked(session_factory, ctx)
    [item] = api("GET", _base(ctx), ctx["advisor_user"]).json()["items"]
    assert item["has_valid_override"] is False
    assert sorted(o["state"] for o in item["overrides"]) == ["approved", "stale"]


def test_request_with_outdated_decision_hash_is_conflict(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "hash")
    response = api("POST", _base(ctx), ctx["advisor_user"], json={
        "product_id": ctx["product"], "reason_text": REASON, "expected_decision_hash": "outdated"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "ELIGIBILITY_DECISION_CHANGED"


def test_request_changed_before_approval_cannot_be_approved(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "stale-req")
    created = api("POST", _base(ctx), ctx["advisor_user"],
                  json={"product_id": ctx["product"], "reason_text": REASON}).json()
    with session_factory() as s:
        rule = s.get(ProductEligibilityRule, ctx["rule"])
        rule.rule_hash = f"{rule.rule_hash}-v2"
        s.commit()
    response = api("POST", _base(ctx) + f"/{created['id']}/approve", ctx["admin_user"])
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "ELIGIBILITY_DECISION_CHANGED"


def test_tampered_override_row_is_no_evidence(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "tamper")
    _request_and_approve(api, ctx)
    with session_factory() as s:
        # ELIG-OVERRIDE-APPEND-ONLY-001: the table is append-only; tampering
        # needs DDL rights below the app (drop the trigger first).
        s.execute(text("DROP TRIGGER trg_product_eligibility_overrides_no_update"))
        row = s.query(ProductEligibilityOverride).filter(
            ProductEligibilityOverride.approved_by != "").one()
        row.expires_at = "2999-01-01T00:00:00+00:00"
        s.commit()
    assert _blocked(session_factory, ctx)


def test_product_without_override_duty_is_conflict(session_factory, monkeypatch, api):
    ctx = _setup_run(session_factory, monkeypatch, suffix="no-duty")
    response = api("POST", _base(ctx), _user(ctx["advisor"], "advisor"),
                   json={"product_id": ctx["product"], "reason_text": REASON})
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "OVERRIDE_NOT_REQUIRED"
