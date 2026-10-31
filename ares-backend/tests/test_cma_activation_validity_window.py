"""CMA-EFFECTIVE-DATE-001, Schreib- und Lesepfad.

Seit der Resolver nur noch Zeilen waehlt, deren valid_from/valid_until-
Fenster heute einschliesst, wuerde eine Aktivierung mit kuenftigem
valid_from die Vorgaengerin abloesen und bis zum Stichtag jede Allokation
sperren. Jeder Schreibpfad, der is_current umsetzt, lehnt das deshalb mit
422 + reason_code ab und laesst die Vorgaengerin unangetastet. Die Lesepfade
(Methodik-Audit, Risk-free-Rate) zeigen dieselbe CMA wie die Engine.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.allocation import CapitalMarketAssumption  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.backtest_strategy import _resolve_risk_free_bps  # noqa: E402
from services.cma_import import apply_cma_row  # noqa: E402
from services.jurisdiction.exceptions import CMAValidityWindowError  # noqa: E402
from services.methodology_audit import audit_engine_models  # noqa: E402

TODAY = datetime.date.today()
FUTURE = (TODAY + datetime.timedelta(days=30)).isoformat()
PAST = (TODAY - datetime.timedelta(days=30)).isoformat()
LONG_AGO = (TODAY - datetime.timedelta(days=400)).isoformat()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_activation_window.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    now = _now()
    with SF() as s:
        s.add(Tenant(
            id="main", display_name="main", slug="main", hosting_tier="tier1",
            license_status="active", is_active=1, created_at=now, updated_at=now,
        ))
        s.add(User(
            id="pm-a", username="pm-a", password_hash="h", full_name="PM A",
            role="portfolio_management", is_active=1, tenant_id="main",
            created_at=now, updated_at=now,
        ))
        s.commit()
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    user = User(id="pm-a", username="pm-a", password_hash="h", full_name="PM A",
                role="portfolio_management", is_active=1, tenant_id="main")
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _cma(row_id, *, valid_from=LONG_AGO, valid_until=None, is_current=1,
         jurisdiction="CH", status="committee_approved", created_at=None, **fields):
    stamp = created_at or _now()
    return CapitalMarketAssumption(
        id=row_id, assumption_set_name="Standard", version=1,
        valid_from=valid_from, valid_until=valid_until, is_current=is_current,
        jurisdiction=jurisdiction, tenant_id=None, status=status,
        created_by="pm-a", created_at=stamp, updated_at=stamp, **fields,
    )


def _current_ids(SF):
    with SF() as s:
        return sorted(
            r.id for r in s.query(CapitalMarketAssumption).filter(
                CapitalMarketAssumption.is_current == 1
            )
        )


# ── Schreibpfad: PUT /capital-market-assumptions ─────────────────────────────


@pytest.mark.parametrize(
    "payload, reason_code",
    [
        ({"valid_from": FUTURE}, "CMA_FUTURE_VALID_FROM_NOT_SUPPORTED"),
        ({"valid_from": LONG_AGO, "valid_until": PAST}, "CMA_VALID_UNTIL_IN_PAST"),
    ],
)
def test_update_cma_rejects_version_not_effective_today(client, session_factory, payload, reason_code):
    with session_factory() as s:
        s.add(_cma("cma-prev", equity_ch_return_bps=600))
        s.commit()

    resp = client.put("/capital-market-assumptions", json={**payload, "equity_ch_return_bps": 650})

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason_code"] == reason_code
    # Vorgaengerin unangetastet, keine neue Version.
    assert _current_ids(session_factory) == ["cma-prev"]
    with session_factory() as s:
        assert s.query(CapitalMarketAssumption).count() == 1


def test_update_cma_accepts_version_effective_today(client, session_factory):
    with session_factory() as s:
        s.add(_cma("cma-prev", equity_ch_return_bps=600))
        s.commit()

    resp = client.put("/capital-market-assumptions", json={
        "valid_from": TODAY.isoformat(), "equity_ch_return_bps": 650,
    })

    assert resp.status_code == 200, resp.text
    assert _current_ids(session_factory) == [resp.json()["id"]]


def test_update_cma_rejects_inherited_expired_valid_until(client, session_factory):
    """valid_until wird bei partiellem Update von der Vorgaengerin geerbt --
    auch die geerbte, bereits abgelaufene Grenze darf nicht aktiviert werden."""
    with session_factory() as s:
        s.add(_cma("cma-prev", valid_until=PAST, equity_ch_return_bps=600))
        s.commit()

    resp = client.put("/capital-market-assumptions", json={"valid_from": LONG_AGO})

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason_code"] == "CMA_VALID_UNTIL_IN_PAST"
    assert _current_ids(session_factory) == ["cma-prev"]


# ── Schreibpfad: Freigabe eines Kandidaten ──────────────────────────────────


def test_approve_rejects_candidate_with_future_valid_from(client, session_factory):
    with session_factory() as s:
        s.add(_cma("cma-de-prev", jurisdiction="DE", bonds_home_ig_return_bps=200))
        s.add(_cma("cma-de-future", jurisdiction="DE", valid_from=FUTURE, is_current=0,
                   status="data_derived", bonds_home_ig_return_bps=250))
        s.commit()

    resp = client.post("/capital-market-assumptions/cma-de-future/approve")

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason_code"] == "CMA_FUTURE_VALID_FROM_NOT_SUPPORTED"
    assert _current_ids(session_factory) == ["cma-de-prev"]
    with session_factory() as s:
        candidate = s.get(CapitalMarketAssumption, "cma-de-future")
        assert candidate.status == "data_derived"


# ── Schreibpfad: CSV-Import ─────────────────────────────────────────────────


def test_csv_apply_rejects_future_valid_from_and_keeps_predecessor(session_factory):
    with session_factory() as s:
        s.add(_cma("cma-prev", equity_ch_return_bps=600))
        s.commit()
        with pytest.raises(CMAValidityWindowError) as exc_info:
            apply_cma_row(s, {
                "assumption_set_name": "Standard", "valid_from": FUTURE,
                "equity_ch_return_bps": "650",
            }, "pm-a")
        assert exc_info.value.reason_code == "CMA_FUTURE_VALID_FROM_NOT_SUPPORTED"
        assert s.get(CapitalMarketAssumption, "cma-prev").is_current == 1


# ── Lesepfade zeigen dieselbe CMA wie die Engine ────────────────────────────


def _seed_expired_newer_and_valid_older(SF):
    """Abgelaufene Zeile ist juenger angelegt (created_at) und zuerst
    eingefuegt -- die alten Lesepfade (order_by created_at desc bzw.
    unsortiertes .first()) nahmen sie, die Engine nimmt die gueltige."""
    with SF() as s:
        s.add(_cma(
            "cma-expired", valid_from=PAST, valid_until=PAST,
            created_at="2026-02-01T00:00:00.000Z", liquidity_return_bps=300,
        ))
        s.commit()
        s.add(_cma(
            "cma-valid", created_at="2026-01-01T00:00:00.000Z",
            liquidity_return_bps=40,
        ))
        s.commit()


def test_methodology_audit_reports_the_effective_cma(session_factory):
    _seed_expired_newer_and_valid_older(session_factory)
    with session_factory() as s:
        assert audit_engine_models(s)["cma_id"] == "cma-valid"


def test_risk_free_rate_comes_from_the_effective_cma(session_factory):
    _seed_expired_newer_and_valid_older(session_factory)
    with session_factory() as s:
        assert _resolve_risk_free_bps(s) == 40
