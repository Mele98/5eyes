"""OF-1 / Audit 2026-11/06 OF-a, OF-b: OpenFIGI-Apply-Haertung.

Befunde vor dem Fix:
- OF-a: ``/openfigi/auto-apply`` uebernahm ungeprueft ``candidates[0]``,
  obwohl eine ISIN in der Regel mehrere Listings hat. Im Audit-Log stand nur
  ``mapping_provider=openfigi``; die alten Werte (FIGI, Symbol, Boerse ...)
  fehlten.
- OF-b: ``_apply_openfigi_candidate`` ueberschrieb ``exchange_code``,
  ``security_type``, ``market_sector`` usw. auch mit ``None``.

Nach dem Fix: Mehrdeutigkeit -> kein Auto-Apply, sondern Status
``ambiguous`` mit Kandidatenliste zur Auswahl (``/openfigi/apply`` mit
``preferred_figi``). ``/openfigi/apply`` verlangt bei mehreren Kandidaten
eine explizite Wahl. Felder werden nie mit None ueberschrieben, jede
Aenderung steht mit Alt- und Neuwert im Audit-Log.

OpenFIGI ist durchgehend gefaked (kein Netz).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import routers.review as review_router
from database import Base
from models.review import AuditLog, Product
from models.users import User
from routers.review import apply_product_id_mapping, auto_apply_product_id_mappings
from schemas.review import ProductIdMappingApplyRequest, ProductIdMappingBatchApplyRequest


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'of1.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def admin_user():
    return User(
        id="admin-of1",
        username="admin",
        password_hash="hash",
        full_name="Admin OF1",
        role="admin",
        is_active=1,
        created_at="2026-10-01T00:00:00.000Z",
        updated_at="2026-10-01T00:00:00.000Z",
    )


def _candidate(figi: str, ticker: str, exch: str, **extra) -> dict:
    payload = {
        "figi": figi,
        "ticker": ticker,
        "name": "Vanguard FTSE All-World",
        "exch_code": exch,
        "composite_figi": None,
        "share_class_figi": None,
        "security_type": None,
        "security_type2": None,
        "market_sector": None,
        "security_description": None,
    }
    payload.update(extra)
    return payload


def _fake_preview(monkeypatch, candidates: list[dict]):
    monkeypatch.setattr(
        review_router,
        "preview_openfigi_mapping",
        lambda **kwargs: {
            "source": "openfigi",
            "api_key_used": False,
            "request_job": {"idType": "ID_ISIN", "idValue": kwargs.get("isin")},
            "resolved_from": kwargs.get("context") or {},
            "warning": None,
            "error": None,
            "candidates": [dict(c) for c in candidates],
        },
    )


def _add_product(session, **overrides) -> None:
    values = dict(
        id="p-of1",
        isin="IE00B3RBWM25",
        symbol=None,
        product_name="Vanguard FTSE All-World",
        provider="Vanguard",
        product_type="ETF",
        asset_class="Aktien",
        currency="CHF",
        is_active=1,
        created_at="2026-10-01T00:00:00.000Z",
        updated_at="2026-10-01T00:00:00.000Z",
    )
    values.update(overrides)
    session.add(Product(**values))
    session.commit()


LN = _candidate("BBG000LN0001", "VWRL", "LN")
SW = _candidate("BBG000SW0001", "VWRL", "SW")


# --------------------------------------------------------------------------- #
# OF-a: Mehrdeutigkeit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry_run", [False, True])
def test_auto_apply_does_not_pick_first_of_several_listings(session_factory, admin_user, monkeypatch, dry_run):
    _fake_preview(monkeypatch, [LN, SW])
    with session_factory() as session:
        _add_product(session)
        result = auto_apply_product_id_mappings(
            body=ProductIdMappingBatchApplyRequest(limit=10, dry_run=dry_run),
            db=session,
            current_user=admin_user,
        )
        stored = session.query(Product).filter(Product.id == "p-of1").one()

    assert result["applied"] == 0
    item = result["items"][0]
    assert item["status"] == "ambiguous"
    assert item.get("applied_candidate") is None
    assert {c["figi"] for c in item["candidates"]} == {"BBG000LN0001", "BBG000SW0001"}
    assert stored.figi is None and stored.symbol is None and stored.mapping_provider is None


def test_auto_apply_resolves_ambiguity_only_via_known_product_exchange(session_factory, admin_user, monkeypatch):
    """Eindeutig ueber die bereits gepflegte Boerse des Produkts (interner Code)."""
    _fake_preview(monkeypatch, [LN, SW])
    with session_factory() as session:
        _add_product(session, exchange_code="SW")
        result = auto_apply_product_id_mappings(
            body=ProductIdMappingBatchApplyRequest(limit=10, dry_run=False),
            db=session,
            current_user=admin_user,
        )
        stored = session.query(Product).filter(Product.id == "p-of1").one()

    assert result["applied"] == 1
    assert result["items"][0]["status"] == "applied"
    assert stored.figi == "BBG000SW0001"
    assert stored.exchange_code == "SW"


def test_auto_apply_single_candidate_still_applies(session_factory, admin_user, monkeypatch):
    """Positivkontrolle: genau ein Kandidat (auch doppelt geliefert) -> Apply."""
    _fake_preview(monkeypatch, [LN, dict(LN)])
    with session_factory() as session:
        _add_product(session)
        result = auto_apply_product_id_mappings(
            body=ProductIdMappingBatchApplyRequest(limit=10, dry_run=False),
            db=session,
            current_user=admin_user,
        )
        stored = session.query(Product).filter(Product.id == "p-of1").one()
    assert result["applied"] == 1
    assert stored.figi == "BBG000LN0001"
    assert stored.symbol == "VWRL"
    assert stored.exchange_code == "L"


def test_manual_apply_requires_explicit_choice_when_ambiguous(session_factory, admin_user, monkeypatch):
    _fake_preview(monkeypatch, [LN, SW])
    with session_factory() as session:
        _add_product(session)
        with pytest.raises(HTTPException) as exc:
            apply_product_id_mapping(
                body=ProductIdMappingApplyRequest(product_id="p-of1"),
                db=session,
                current_user=admin_user,
            )
        assert exc.value.status_code == 409
        assert session.query(Product).filter(Product.id == "p-of1").one().figi is None

        result = apply_product_id_mapping(
            body=ProductIdMappingApplyRequest(product_id="p-of1", preferred_figi="BBG000SW0001"),
            db=session,
            current_user=admin_user,
        )
        assert result["product"].figi == "BBG000SW0001"
        explicit = apply_product_id_mapping(
            body=ProductIdMappingApplyRequest(product_id="p-of1", candidate_index=0),
            db=session,
            current_user=admin_user,
        )
        assert explicit["product"].figi == "BBG000LN0001"


# --------------------------------------------------------------------------- #
# OF-b: kein Ueberschreiben mit None; OF-a: Altwerte im Audit-Log
# --------------------------------------------------------------------------- #


def test_apply_never_overwrites_with_none_and_audits_old_values(session_factory, admin_user, monkeypatch):
    _fake_preview(monkeypatch, [_candidate("BBG000NEW001", "VWRL", "LN", security_type="ETP")])
    with session_factory() as session:
        _add_product(
            session,
            symbol="VWRL_OLD",
            figi="BBG000OLD001",
            composite_figi="BBG000COMPOLD",
            share_class_figi="BBG000SHAREOLD",
            exchange_code="L",
            market_sector="Equity",
            security_type="Mutual Fund",
            security_type2="Open-End Fund",
        )
        apply_product_id_mapping(
            body=ProductIdMappingApplyRequest(product_id="p-of1", overwrite_symbol=True),
            db=session,
            current_user=admin_user,
        )
        stored = session.query(Product).filter(Product.id == "p-of1").one()
        audit = {
            row.field_name: (row.old_value, row.new_value)
            for row in session.query(AuditLog).filter(AuditLog.record_id == "p-of1").all()
        }

    # None im Kandidaten ueberschreibt nichts
    assert stored.composite_figi == "BBG000COMPOLD"
    assert stored.share_class_figi == "BBG000SHAREOLD"
    assert stored.market_sector == "Equity"
    assert stored.security_type2 == "Open-End Fund"
    # echte Aenderungen kommen an
    assert stored.figi == "BBG000NEW001"
    assert stored.symbol == "VWRL"
    assert stored.security_type == "ETP"
    # Alt- und Neuwerte im Audit-Log
    assert audit["figi"] == ("BBG000OLD001", "BBG000NEW001")
    assert audit["symbol"] == ("VWRL_OLD", "VWRL")
    assert audit["security_type"] == ("Mutual Fund", "ETP")
    assert audit["mapping_provider"] == (None, "openfigi")
    assert "composite_figi" not in audit and "market_sector" not in audit


def test_auto_apply_audits_old_values_per_field(session_factory, admin_user, monkeypatch):
    _fake_preview(monkeypatch, [_candidate("BBG000NEW002", "VWRL", "LN", market_sector="Equity")])
    with session_factory() as session:
        _add_product(session, figi="BBG000OLD002", security_type="Mutual Fund")
        result = auto_apply_product_id_mappings(
            body=ProductIdMappingBatchApplyRequest(limit=10, dry_run=False),
            db=session,
            current_user=admin_user,
        )
        stored = session.query(Product).filter(Product.id == "p-of1").one()
        audit = {
            row.field_name: (row.old_value, row.new_value)
            for row in session.query(AuditLog).filter(AuditLog.record_id == "p-of1").all()
        }
    assert result["applied"] == 1
    assert stored.security_type == "Mutual Fund"
    assert audit["figi"] == ("BBG000OLD002", "BBG000NEW002")
    assert audit["symbol"] == (None, "VWRL")
    assert audit["exchange_code"] == (None, "L")
    assert audit["mapping_provider"] == (None, "openfigi")
    assert "security_type" not in audit
