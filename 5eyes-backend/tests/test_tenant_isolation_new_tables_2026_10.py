"""TENANT-ISOLATION-NEW-TABLES-001 (2026-10-21): adversariale Mandanten-Trennung
fuer die seit 18.10. neuen Tabellen und Endpunkte.

Tabellen ohne tenant_id (risk_override_decisions, risk_profile_signoffs,
wealth_inflows.linked_position_id, Vorsorge-Felder auf wealth_positions)
werden -- wie goals/cashflows/risk_assessments -- transitiv ueber Mandat bzw.
Kunde isoliert (services/auth.py::get_mandate_for_user_or_404 /
get_client_for_user_or_404, inkl. Tenant-Filter). Dieser Test belegt das auf
Endpunkt-Ebene: ein Berater UND ein tenant-gebundener Admin von Firma A
koennen Decisions, Signoffs, Vorsorge-Positionen und Zufluss-Links von Firma B
weder lesen noch schreiben noch per ID-Raten referenzieren -- im
Kompatibilitaets- und im Strict-Modus.

Gefundene Luecke (rot gegen develop 4105776): PUT /wealth-inflows/{id} pruefte
linked_position_id nur, wenn der Zufluss nach dem Update aktiv war. Mit
``is_active=0`` liess sich eine FREMDE (auch tenant-fremde) Position-ID
ungeprueft persistieren.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import models.client_login  # noqa: F401  (Tabelle registrieren)
from config import settings
from models.client_login import ClientLogin
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskOverrideDecision, RiskProfileSignoff
from models.tenant import Tenant
from models.users import User
from models.wealth import WealthInflow, WealthPosition
from routers import client_portal as portal_router
from routers import pdf_reports as pdf_router
from routers import profiling as profiling_router
from routers import wealth as wealth_router
from schemas.profiling import RiskAssessmentOverride
from schemas.wealth import WealthInflowCreate, WealthInflowUpdate, WealthPositionUpdate
from services.risk_override_decision import resolve_assessment_decision
from services.risk_profile_signoff import resolve_assessment_signoff
from tests.test_risk_capacity_plausibility import (
    NOW,
    _FakeRequest,
    _seed,
    session_factory,  # noqa: F401 - pytest fixture re-export
)
from tests.test_risk_override_current_gate_decision_log import (
    VALID_REASON,
    _assessment,
    _override,
)

TENANT_A = "firm-A"
TENANT_B = "firm-B"
# Firma B = die Fixture aus test_risk_capacity_plausibility (_seed).
B_MANDATE, B_CLIENT, B_RA = "m-rcp", "cl-rcp", "ra-current"


def _tenant(tid: str) -> Tenant:
    return Tenant(id=tid, display_name=tid, slug=tid, created_at=NOW, updated_at=NOW)


def _external_pension(pid: str, client_id: str) -> WealthPosition:
    return WealthPosition(
        id=pid, client_id=client_id, label=pid, position_type="Vorsorge",
        assignment="Anderes Vermögen", pension_type="Säule 3a",
        current_value_rappen=10_000_000, currency="CHF",
        is_active=1, created_at=NOW, updated_at=NOW,
    )


def _inflow(iid: str, client_id: str, linked: str | None = None) -> WealthInflow:
    return WealthInflow(
        id=iid, client_id=client_id, label=iid, source_type="Andere",
        amount_rappen=5_000_000, expected_year=2030, is_recurring=0,
        frequency="einmalig", value_mode="nominal", linked_position_id=linked,
        is_active=1, created_at=NOW, updated_at=NOW,
    )


@pytest.fixture
def world(session_factory):  # noqa: F811
    """Firma B mit Override-Decision, Signoff, Vorsorge-Quelle + verknuepftem
    Zufluss; Firma A mit eigenem Mandat/Assessment/Position/Zufluss."""
    with session_factory() as s:
        s.add_all([_tenant(TENANT_A), _tenant(TENANT_B)])
        adv_b = _seed(s)
        adv_b.tenant_id = TENANT_B
        s.get(Client, B_CLIENT).tenant_id = TENANT_B
        s.get(Mandate, B_MANDATE).tenant_id = TENANT_B
        s.add(_assessment(B_RA, adv_b.id, version=1, is_current=1))
        s.commit()
        # Echte, hash-gueltige Evidence von Firma B ueber die echten Pfade.
        _override(s, adv_b, B_RA, score=40, profile="Defensiv")
        profiling_router.sign_risk_profile(
            mandate_id=B_MANDATE, request=_FakeRequest(), body=None, db=s, current_user=adv_b,
        )
        s.add_all([_external_pension("pos-b", B_CLIENT), _inflow("inf-b", B_CLIENT, "pos-b")])

        adv_a = User(id="adv-a", username="adv-a", password_hash="h", full_name="A",
                     role="advisor", is_active=1, tenant_id=TENANT_A,
                     created_at=NOW, updated_at=NOW)
        admin_a = User(id="admin-a", username="admin-a", password_hash="h", full_name="Admin A",
                       role="admin", is_active=1, tenant_id=TENANT_A,
                       created_at=NOW, updated_at=NOW)
        client_user_a = User(id="cu-a", username="cu-a", password_hash="h", full_name="Kunde A",
                             role="client", is_active=1, tenant_id=TENANT_A,
                             created_at=NOW, updated_at=NOW)
        s.add_all([adv_a, admin_a, client_user_a])
        s.add(Client(
            id="cl-a", client_number="C-A", first_name="Anna", last_name="A",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id="adv-a", tenant_id=TENANT_A,
            created_at=NOW, updated_at=NOW,
        ))
        s.add(Mandate(
            id="m-a", client_id="cl-a", mandate_number="M-A", tenant_id=TENANT_A,
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-01-01", created_at=NOW, updated_at=NOW,
        ))
        ra_a = _assessment("ra-a", "adv-a", version=1, is_current=1)
        ra_a.mandate_id = "m-a"
        s.add(ra_a)
        s.add(ClientLogin(id="cl-login-a", user_id="cu-a", client_id="cl-a",
                          created_by="adv-a", created_at=NOW, is_active=1))
        s.add_all([_external_pension("pos-a", "cl-a"), _inflow("inf-a", "cl-a")])
        s.commit()
        yield s, {"advisor": adv_a, "admin": admin_a, "client": client_user_a}


@pytest.fixture(params=[False, True], ids=["compat", "strict"])
def strict(request, monkeypatch):
    monkeypatch.setattr(settings, "strict_tenant_isolation", request.param)
    return request.param


@pytest.fixture(params=["advisor", "admin"])
def attacker(request, world, strict):
    session, users = world
    return session, users[request.param]


def _evidence_counts(s) -> tuple[int, int]:
    return (
        s.query(RiskOverrideDecision).count(),
        s.query(RiskProfileSignoff).count(),
    )


def _expect(status: int, fn, *args, **kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        fn(*args, **kwargs)
    assert exc.value.status_code == status, exc.value.detail
    return exc.value


# ---------------------------------------------------------------------------
# Risikoprofil: Decisions / Signoffs / Plausibilitaet / Reports
# ---------------------------------------------------------------------------


def test_foreign_tenant_risk_reads_are_404(attacker):
    s, user = attacker
    for fn in (
        profiling_router.list_risk_assessments,
        profiling_router.get_current_risk_assessment,
        profiling_router.get_risk_capacity_plausibility,
    ):
        _expect(404, fn, mandate_id=B_MANDATE, db=s, current_user=user)
    for fn in (pdf_router.get_risikoprofil_pdf, pdf_router.get_protokoll_pdf):
        _expect(404, fn, mandate_id=B_MANDATE, request=_FakeRequest(), db=s, current_user=user)


def test_foreign_tenant_override_writes_no_decision(attacker):
    s, user = attacker
    before = _evidence_counts(s)
    body = RiskAssessmentOverride(
        override_score_x10=30, override_profile="Defensiv", override_reason=VALID_REASON,
    )
    _expect(404, profiling_router.override_risk_assessment,
            mandate_id=B_MANDATE, ra_id=B_RA, body=body, request=_FakeRequest(),
            db=s, current_user=user)
    assert _evidence_counts(s) == before


def test_foreign_assessment_id_via_own_mandate_is_404(world, strict):
    """ID-Raten: eigenes Mandat + fremde Assessment-ID."""
    s, users = world
    before = _evidence_counts(s)
    body = RiskAssessmentOverride(
        override_score_x10=30, override_profile="Defensiv", override_reason=VALID_REASON,
    )
    _expect(404, profiling_router.override_risk_assessment,
            mandate_id="m-a", ra_id=B_RA, body=body, request=_FakeRequest(),
            db=s, current_user=users["advisor"])
    assert _evidence_counts(s) == before
    s.expire_all()
    assert s.get(RiskAssessment, B_RA).override_score_x10 == 40


def test_foreign_tenant_signoff_writes_nothing(attacker):
    s, user = attacker
    before = _evidence_counts(s)
    signoff_before = s.get(RiskAssessment, B_RA).signoff_id
    _expect(404, profiling_router.sign_risk_profile,
            mandate_id=B_MANDATE, request=_FakeRequest(), body=None, db=s, current_user=user)
    assert _evidence_counts(s) == before
    s.expire_all()
    assert s.get(RiskAssessment, B_RA).signoff_id == signoff_before


def test_client_portal_cannot_sign_foreign_tenant_mandate(world, strict):
    s, users = world
    before = _evidence_counts(s)
    _expect(404, portal_router.client_portal_sign_risk_profile,
            mandate_id=B_MANDATE, request=_FakeRequest(), db=s, current_user=users["client"])
    assert _evidence_counts(s) == before


def test_foreign_decision_or_signoff_pointer_never_verifies(world):
    """Defense in depth: selbst ein (z.B. per Bestandsdaten/Bug) auf fremde
    Evidence zeigender Pointer wird nie als verifiziert ausgegeben."""
    s, _users = world
    ra_b = s.get(RiskAssessment, B_RA)
    ra_a = s.get(RiskAssessment, "ra-a")
    assert ra_b.override_decision_id and ra_b.signoff_id
    # Kontrolle: bei Firma B selbst verifiziert die Evidence.
    assert resolve_assessment_decision(s, ra_b)[2] is True
    assert resolve_assessment_signoff(s, ra_b)[2] is True

    ra_a.override_decision_id = ra_b.override_decision_id
    ra_a.override_decision_hash = ra_b.override_decision_hash
    ra_a.override_score_x10 = ra_b.override_score_x10
    ra_a.override_profile = ra_b.override_profile
    ra_a.signoff_id = ra_b.signoff_id
    ra_a.signoff_hash = ra_b.signoff_hash
    assert resolve_assessment_decision(s, ra_a)[2] is False
    assert resolve_assessment_signoff(s, ra_a)[2] is False
    s.rollback()


# ---------------------------------------------------------------------------
# Vorsorge-Positionen + wealth_inflows.linked_position_id
# ---------------------------------------------------------------------------


def test_foreign_tenant_wealth_reads_are_404(attacker):
    s, user = attacker
    _expect(404, wealth_router.list_wealth_inflows, client_id=B_CLIENT, db=s, current_user=user)
    _expect(404, wealth_router.list_wealth_positions, client_id=B_CLIENT,
            include_inactive=True, db=s, current_user=user)


def test_foreign_tenant_vorsorge_fields_not_writable(attacker):
    s, user = attacker
    body = WealthPositionUpdate(pension_interest_rate_bps=900)
    _expect(404, wealth_router.update_wealth_position,
            client_id=B_CLIENT, wp_id="pos-b", body=body, db=s, current_user=user)
    # ID-Raten ueber den eigenen Kunden.
    _expect(404, wealth_router.update_wealth_position,
            client_id="cl-a", wp_id="pos-b", body=body, db=s, current_user=user)
    s.expire_all()
    assert s.get(WealthPosition, "pos-b").pension_interest_rate_bps is None


def test_foreign_tenant_inflow_not_writable(attacker):
    s, user = attacker
    _expect(404, wealth_router.update_wealth_inflow, inflow_id="inf-b",
            body=WealthInflowUpdate(linked_position_id=None), db=s, current_user=user)
    _expect(404, wealth_router.delete_wealth_inflow, inflow_id="inf-b", db=s, current_user=user)
    s.expire_all()
    inflow = s.get(WealthInflow, "inf-b")
    assert inflow.linked_position_id == "pos-b" and inflow.deleted_at is None


@pytest.mark.parametrize("role", ["advisor", "admin"])
def test_create_inflow_cannot_link_foreign_position(world, strict, role):
    s, users = world
    body = WealthInflowCreate(
        label="Bezug", source_type="Andere", amount_rappen=1_000_000,
        expected_year=2031, linked_position_id="pos-b",
    )
    _expect(422, wealth_router.create_wealth_inflow,
            client_id="cl-a", body=body, db=s, current_user=users[role])
    assert s.query(WealthInflow).filter(WealthInflow.linked_position_id == "pos-b").count() == 1


@pytest.mark.parametrize("role", ["advisor", "admin"])
def test_create_inflow_cannot_target_foreign_mandate(world, strict, role):
    s, users = world
    body = WealthInflowCreate(
        label="Bezug", source_type="Andere", amount_rappen=1_000_000,
        expected_year=2031, mandate_id=B_MANDATE,
    )
    _expect(404, wealth_router.create_wealth_inflow,
            client_id="cl-a", body=body, db=s, current_user=users[role])


@pytest.mark.parametrize("role", ["advisor", "admin"])
def test_update_active_inflow_cannot_link_foreign_position(world, strict, role):
    s, users = world
    _expect(422, wealth_router.update_wealth_inflow, inflow_id="inf-a",
            body=WealthInflowUpdate(linked_position_id="pos-b"), db=s, current_user=users[role])
    s.expire_all()
    assert s.get(WealthInflow, "inf-a").linked_position_id is None


@pytest.mark.parametrize("role", ["advisor", "admin"])
def test_update_inactive_inflow_cannot_store_foreign_position_link(world, strict, role):
    """ROT gegen develop: mit is_active=0 wurde der Link nicht geprueft und
    eine tenant-fremde Position-ID ungeprueft persistiert."""
    s, users = world
    _expect(422, wealth_router.update_wealth_inflow, inflow_id="inf-a",
            body=WealthInflowUpdate(is_active=0, linked_position_id="pos-b"),
            db=s, current_user=users[role])
    s.expire_all()
    inflow = s.get(WealthInflow, "inf-a")
    assert inflow.linked_position_id is None
    assert inflow.is_active == 1


def test_update_already_inactive_inflow_cannot_store_foreign_position_link(world, strict):
    s, users = world
    inflow = s.get(WealthInflow, "inf-a")
    inflow.is_active = 0
    s.commit()
    _expect(422, wealth_router.update_wealth_inflow, inflow_id="inf-a",
            body=WealthInflowUpdate(linked_position_id="pos-b"),
            db=s, current_user=users["advisor"])
    s.expire_all()
    assert s.get(WealthInflow, "inf-a").linked_position_id is None


def test_inactive_inflow_own_link_and_unrelated_edits_still_work(world, strict):
    """Kein Kollateralschaden: eigener Link auf inaktivem Zufluss bleibt
    erlaubt; ein inaktiver Zufluss mit verwaistem Alt-Link bleibt editierbar,
    solange der Link nicht geaendert wird."""
    s, users = world
    adv = users["advisor"]
    out = wealth_router.update_wealth_inflow(
        inflow_id="inf-a", body=WealthInflowUpdate(is_active=0, linked_position_id="pos-a"),
        db=s, current_user=adv,
    )
    assert out.linked_position_id == "pos-a" and out.is_active == 0
    # Quelle spaeter geloescht (Bestandsdaten) -> Label-Edit bleibt moeglich.
    s.get(WealthPosition, "pos-a").deleted_at = NOW
    s.commit()
    out = wealth_router.update_wealth_inflow(
        inflow_id="inf-a", body=WealthInflowUpdate(label="umbenannt"), db=s, current_user=adv,
    )
    assert out.label == "umbenannt" and out.linked_position_id == "pos-a"
