"""N-862-1 (Pruefrunde #862): Das feldweise Audit von OpenFIGI-Apply und
Auto-Apply schreibt mehrere Eintraege pro Transaktion. Vor dem Basis-Fix in
``services/audit.py::log`` (r5/audit-chain-flush: Flush nach jedem Eintrag)
fand der zweite Eintrag seinen ungeflushten Vorgaenger nicht, und
``verify_audit_chain`` meldete ``ok=False``.

Dieser Test pinnt die Kette nach beiden Pfaden mit mehreren geaenderten
Feldern. OpenFIGI ist gefaked (kein Netz).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import routers.review as review_router
from database import Base
from models.review import AuditLog, Product
from models.users import User
from routers.review import apply_product_id_mapping, auto_apply_product_id_mappings
from schemas.review import ProductIdMappingApplyRequest, ProductIdMappingBatchApplyRequest
from services.audit import verify_audit_chain


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'n862_1.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


ADMIN = dict(
    id="admin-n862-1", username="admin", password_hash="hash", full_name="Admin", role="admin",
    is_active=1, created_at="2026-10-01T00:00:00.000Z", updated_at="2026-10-01T00:00:00.000Z",
)


def _fake_preview(monkeypatch, figi: str):
    candidate = {
        "figi": figi, "ticker": "VWRL", "name": "X", "exch_code": "LN",
        "composite_figi": figi + "C", "share_class_figi": figi + "S",
        "security_type": "ETP", "security_type2": "ETF", "market_sector": "Equity",
    }
    monkeypatch.setattr(
        review_router,
        "preview_openfigi_mapping",
        lambda **kwargs: {
            "source": "openfigi", "api_key_used": False, "request_job": {}, "resolved_from": {},
            "warning": None, "error": None, "candidates": [dict(candidate)],
        },
    )


def _add_product(session, pid: str, **overrides):
    values = dict(
        id=pid, isin="IE00B3RBWM25", symbol=None, product_name=pid, provider="T", product_type="ETF",
        asset_class="Aktien", currency="CHF", is_active=1,
        created_at="2026-10-01T00:00:00.000Z", updated_at="2026-10-01T00:00:00.000Z",
    )
    values.update(overrides)
    session.add(Product(**values))
    session.commit()


def test_audit_chain_intact_after_openfigi_apply_and_auto_apply(session_factory, monkeypatch):
    user = User(**ADMIN)
    with session_factory() as session:
        _add_product(session, "p-apply", figi="OLD1", security_type="Mutual Fund")
        _add_product(session, "p-auto-1")
        _add_product(session, "p-auto-2")

        _fake_preview(monkeypatch, "BBG000NEW01")
        apply_product_id_mapping(
            body=ProductIdMappingApplyRequest(product_id="p-apply", overwrite_symbol=True),
            db=session, current_user=user,
        )
        _fake_preview(monkeypatch, "BBG000NEW02")
        result = auto_apply_product_id_mappings(
            body=ProductIdMappingBatchApplyRequest(limit=10, dry_run=False), db=session, current_user=user,
        )
        assert result["applied"] == 2

        per_record = {}
        for row in session.query(AuditLog).all():
            per_record[row.record_id] = per_record.get(row.record_id, 0) + 1
        # mehrere Eintraege je Transaktion -> genau der Fall aus N-862-1
        assert min(per_record.values()) >= 5

        verdict = verify_audit_chain(session)
    assert verdict["ok"] is True, verdict
