"""FIDLEG-Eignungspruefung: Kunden-Signatur des Risikoprofils (2026-07-19).

Deckt den Signatur-Kontrakt ab:
  - Modell B (Kundenportal):  POST /client-portal/mandates/{id}/risk-profile/sign
    -> method='portal', ref=<client user id>; nur EIGENES Mandat (fremdes -> 404).
  - Fallback A (Berater erfasst): POST /mandates/{id}/risk-profile/sign
    -> method='advisor_recorded', ref=<note>; 404 wenn kein aktuelles Profil.
  - Audit weist risk_assessment_signed_at/_method aus.
  - Die Signatur ist reine DOKUMENTATION -> is_compliant bleibt unveraendert
    (signiert vs. unsigniert identisch).

Test-Strategie (wie tests/test_sec1_client_login_tenant.py): Router-Funktionen
direkt mit seed-DB + injiziertem current_user aufrufen (kein HTTP-Stack). Fuer die
Audit-Invarianten pure-Unit mit MagicMock (wie tests/test_suitability_fidleg_audit.py).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: E402,F401  (registriert alle Models fuer FK-Aufloesung)
from models.users import User  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.client_login import ClientLogin  # noqa: E402
from routers.profiling import RiskProfileSignRequest, sign_risk_profile  # noqa: E402
from routers.client_portal import client_portal_sign_risk_profile  # noqa: E402
from services.suitability_audit import audit_mandate_suitability  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = _FakeClient(host)


def _days_ago(days: int) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat()


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rp_signing.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _advisor(uid="adv"):
    return User(id=uid, username=uid, password_hash="h", full_name="Advisor", role="advisor",
                is_active=1, tenant_id=None, created_at=_now(), updated_at=_now())


def _client_user(uid, tid=None):
    return User(id=uid, username=uid, password_hash="h", full_name="Kunde", role="client",
                is_active=1, tenant_id=tid, created_at=_now(), updated_at=_now())


def _client(cid, advisor_id="adv", tid=None):
    return Client(id=cid, client_number=cid, first_name=cid, last_name="T", advisor_id=advisor_id,
                  tenant_id=tid, household_type="Einzelperson", client_classification="Privatkunde",
                  country_of_residence="CH", language="DE", created_at=_now(), updated_at=_now())


def _mandate(mid, client_id, mandate_type="Anlageberatung"):
    return Mandate(id=mid, client_id=client_id, mandate_number=mid, mandate_type=mandate_type,
                   status="Aktiv", base_currency="CHF", opened_at=_now(),
                   created_at=_now(), updated_at=_now())


def _risk_assessment(rid, mandate_id, assessed_at=None):
    """Aktuelles Risikoprofil mit allen NOT-NULL-Feldern (Score-Felder = Dummies)."""
    ts = assessed_at or _days_ago(30)
    return RiskAssessment(
        id=rid, mandate_id=mandate_id, version=1, is_current=1, valid_from=ts[:10],
        q_income_points=1, q_obligations_points=1, q_savings_points=1, q_wealth_points=1,
        risk_capacity_total=4, risk_capacity_profile="Ausgewogen",
        investment_horizon_years=10, investment_horizon_label="Langfristig",
        risk_capacity_score_x10=50,
        q_investment_goal_points=1, q_risk_preference_points=1, q_risk_behavior_points=1,
        risk_willingness_total=3, risk_willingness_profile="Ausgewogen",
        risk_willingness_score_x10=50,
        final_score_x10=50, final_profile="Ausgewogen",
        assessed_at=ts, assessed_by="adv", created_at=ts, updated_at=ts,
    )


# ---------------------------------------------------------------------------
# (a) Berater-Sign (Fallback A)
# ---------------------------------------------------------------------------

def test_advisor_sign_sets_three_fields(session_factory):
    with session_factory() as db:
        adv = _advisor()
        db.add_all([adv, _client("c1"), _mandate("m1", "c1"),
                    _risk_assessment("ra1", "m1")])
        db.commit()

        res = sign_risk_profile(
            mandate_id="m1", request=_FakeRequest(),
            body=RiskProfileSignRequest(note="Kunde hat unterschrieben"),
            db=db, current_user=adv,
        )
        assert res["risk_assessment_id"] == "ra1"
        assert res["client_signed_method"] == "advisor_recorded"
        assert res["client_signed_at"] is not None

        ra = db.query(RiskAssessment).filter(RiskAssessment.id == "ra1").one()
        assert ra.client_signed_at is not None
        assert ra.client_signed_method == "advisor_recorded"
        assert ra.client_signed_ref == "Kunde hat unterschrieben"


def test_advisor_sign_without_body_ref_is_none(session_factory):
    with session_factory() as db:
        adv = _advisor()
        db.add_all([adv, _client("c1"), _mandate("m1", "c1"),
                    _risk_assessment("ra1", "m1")])
        db.commit()

        res = sign_risk_profile(mandate_id="m1", request=_FakeRequest(), body=None, db=db, current_user=adv)
        assert res["client_signed_method"] == "advisor_recorded"
        ra = db.query(RiskAssessment).filter(RiskAssessment.id == "ra1").one()
        assert ra.client_signed_ref is None


def test_advisor_sign_404_without_current_profile(session_factory):
    with session_factory() as db:
        adv = _advisor()
        db.add_all([adv, _client("c1"), _mandate("m1", "c1")])  # kein RiskAssessment
        db.commit()
        with pytest.raises(HTTPException) as ei:
            sign_risk_profile(mandate_id="m1", request=_FakeRequest(), body=None, db=db, current_user=adv)
        assert ei.value.status_code == 404


def test_advisor_sign_404_for_foreign_mandate(session_factory):
    """Berater sieht nur eigene Mandate (Client.advisor_id) -> fremdes -> 404."""
    with session_factory() as db:
        adv = _advisor("adv")
        other = _advisor("adv-other")
        db.add_all([adv, other, _client("c2", advisor_id="adv-other"),
                    _mandate("m2", "c2"), _risk_assessment("ra2", "m2")])
        db.commit()
        with pytest.raises(HTTPException) as ei:
            sign_risk_profile(mandate_id="m2", request=_FakeRequest(), body=None, db=db, current_user=adv)
        assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# (b) Portal-Sign (Modell B) — nur eigenes Mandat
# ---------------------------------------------------------------------------

def test_portal_sign_own_mandate_sets_portal_method(session_factory):
    with session_factory() as db:
        cu = _client_user("cu1")
        db.add_all([
            _advisor(), cu, _client("c1"), _mandate("m1", "c1"),
            _risk_assessment("ra1", "m1"),
            ClientLogin(id="lnk1", user_id="cu1", client_id="c1", is_active=1,
                        created_by="adv", created_at=_now()),
        ])
        db.commit()

        res = client_portal_sign_risk_profile(mandate_id="m1", request=_FakeRequest(), db=db, current_user=cu)
        assert res["risk_assessment_id"] == "ra1"
        assert res["client_signed_method"] == "portal"

        ra = db.query(RiskAssessment).filter(RiskAssessment.id == "ra1").one()
        assert ra.client_signed_method == "portal"
        assert ra.client_signed_ref == "cu1"  # Portal-User-ID
        assert ra.client_signed_at is not None


def test_portal_sign_foreign_mandate_blocked(session_factory):
    """Kunde ist mit c1 verknuepft, versucht Mandat von c2 (fremd) zu signieren
    -> 404 (kein Leak), und fremdes Profil bleibt unsigniert."""
    with session_factory() as db:
        cu = _client_user("cu1")
        db.add_all([
            _advisor(), cu,
            _client("c1"), _mandate("m1", "c1"), _risk_assessment("ra1", "m1"),
            _client("c2"), _mandate("m2", "c2"), _risk_assessment("ra2", "m2"),
            ClientLogin(id="lnk1", user_id="cu1", client_id="c1", is_active=1,
                        created_by="adv", created_at=_now()),
        ])
        db.commit()

        with pytest.raises(HTTPException) as ei:
            client_portal_sign_risk_profile(mandate_id="m2", request=_FakeRequest(), db=db, current_user=cu)
        assert ei.value.status_code == 404

        foreign = db.query(RiskAssessment).filter(RiskAssessment.id == "ra2").one()
        assert foreign.client_signed_at is None
        assert foreign.client_signed_method is None


def test_portal_sign_404_without_current_profile(session_factory):
    with session_factory() as db:
        cu = _client_user("cu1")
        db.add_all([
            _advisor(), cu, _client("c1"), _mandate("m1", "c1"),  # kein RiskAssessment
            ClientLogin(id="lnk1", user_id="cu1", client_id="c1", is_active=1,
                        created_by="adv", created_at=_now()),
        ])
        db.commit()
        with pytest.raises(HTTPException) as ei:
            client_portal_sign_risk_profile(mandate_id="m1", request=_FakeRequest(), db=db, current_user=cu)
        assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# (c)+(d) Audit weist Signatur aus, is_compliant bleibt unveraendert
# ---------------------------------------------------------------------------

def _stub_mandate(mandate_type="Anlageberatung"):
    m = MagicMock()
    m.id = "MX"
    m.mandate_type = mandate_type
    return m


def _stub_db_with_ra(ra):
    """RiskAssessment-Query spiegelt den Kern-Resolver (services.portfolio_engine.
    _current_risk_assessment_or_none: .filter(...).all()), den suitability_audit.
    _current_risk_assessment seit FIDLEG-STATE-003 wiederverwendet."""
    db = MagicMock()
    log_query = MagicMock()
    log_query.filter.return_value = log_query
    log_query.count.return_value = 0
    ra_query = MagicMock()
    ra_query.filter.return_value = ra_query
    ra_query.all.return_value = [ra] if ra is not None else []

    def router(model):
        name = getattr(model, "__name__", str(model))
        if "AdvisoryLog" in name:
            return log_query
        if "RiskAssessment" in name:
            return ra_query
        return MagicMock()
    db.query.side_effect = router
    return db


def _mock_ra(*, signed_at=None, signed_method=None, age_days=30):
    return MagicMock(
        id="ra-x", version=1, is_current=1,
        assessed_at=_days_ago(age_days), valid_from=_days_ago(age_days)[:10],
        final_profile="Ausgewogen",
        client_signed_at=signed_at, client_signed_method=signed_method,
    )


def test_audit_exposes_signed_fields_when_signed():
    ra = _mock_ra(signed_at="2026-07-19T10:00:00Z", signed_method="portal")
    result = audit_mandate_suitability(_stub_db_with_ra(ra), _stub_mandate())
    assert result["risk_assessment_signed_at"] == "2026-07-19T10:00:00Z"
    assert result["risk_assessment_signed_method"] == "portal"


def test_audit_signed_fields_none_when_unsigned():
    ra = _mock_ra(signed_at=None, signed_method=None)
    result = audit_mandate_suitability(_stub_db_with_ra(ra), _stub_mandate())
    assert result["risk_assessment_signed_at"] is None
    assert result["risk_assessment_signed_method"] is None


def test_audit_is_compliant_unaffected_by_signature():
    """Signatur ist Dokumentation: is_compliant identisch fuer signiert/unsigniert."""
    unsigned = audit_mandate_suitability(
        _stub_db_with_ra(_mock_ra(age_days=30)), _stub_mandate())
    signed = audit_mandate_suitability(
        _stub_db_with_ra(_mock_ra(age_days=30, signed_at="2026-07-19T10:00:00Z",
                                  signed_method="advisor_recorded")),
        _stub_mandate())
    assert unsigned["is_compliant"] is True
    assert signed["is_compliant"] is True
    assert unsigned["is_compliant"] == signed["is_compliant"]


# ---------------------------------------------------------------------------
# (e) FIDLEG-STATE-003: soft-deleted RiskAssessment darf nicht als 'aktuelles'
#     Profil durchgehen (Kern-Resolver-Wiederverwendung, real-DB-Regression)
# ---------------------------------------------------------------------------

def test_audit_ignores_soft_deleted_current_risk_assessment(session_factory):
    """Ein RiskAssessment mit is_current=1 aber gesetztem deleted_at (soft-
    deleted) darf NICHT als gueltiges/aktuelles Profil gewertet werden -- sonst
    meldet der FIDLEG-Audit is_compliant=True auf Basis geloeschter Daten
    (FIDLEG-STATE-003). Die DB erlaubt das bewusst (der partielle Unique-Index
    ux_risk_one_current greift nur WHERE deleted_at IS NULL), das ist also ein
    realistischer Zustand, kein Konstruktionsartefakt."""
    with session_factory() as db:
        adv = _advisor()
        ra = _risk_assessment("ra-deleted", "m1")
        ra.deleted_at = _now()
        db.add_all([adv, _client("c1"), _mandate("m1", "c1"), ra])
        db.commit()

        mandate = db.query(Mandate).filter_by(id="m1").one()
        result = audit_mandate_suitability(db, mandate)

        assert result["is_compliant"] is False
        assert result["risk_assessment_id"] is None
        assert len(result["logs_without_suitability"]) == 1
        assert result["logs_without_suitability"][0]["reason"] == "no_current_risk_assessment"


def test_audit_uses_current_risk_assessment_when_older_one_is_soft_deleted(session_factory):
    """Wenn NEBEN einer soft-deleted 'aktuellen' Zeile ein echtes aktuelles
    Profil existiert, muss der Audit dieses (nicht-geloeschte) Profil finden --
    reine Bestaetigung, dass der Fix nicht zu ueberkonservativ ist."""
    with session_factory() as db:
        adv = _advisor()
        deleted_ra = _risk_assessment("ra-old-deleted", "m1", assessed_at=_days_ago(500))
        deleted_ra.deleted_at = _now()
        deleted_ra.is_current = 0
        live_ra = _risk_assessment("ra-live", "m1", assessed_at=_days_ago(10))
        db.add_all([adv, _client("c1"), _mandate("m1", "c1"), deleted_ra, live_ra])
        db.commit()

        mandate = db.query(Mandate).filter_by(id="m1").one()
        result = audit_mandate_suitability(db, mandate)

        assert result["risk_assessment_id"] == "ra-live"
        assert result["is_compliant"] is True
