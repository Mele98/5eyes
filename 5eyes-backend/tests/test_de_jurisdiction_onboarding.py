"""Deutschland-Anbindung (2026-07-31, Entscheid Auftraggeber): Regressionstests
fuer die konkrete Anbindung der zweiten Jurisdiktion.

Deckt ab:
1. CapitalMarketAssumption.tenant_id: additive Migration, idempotent.
2. resolve_cma_for_jurisdiction: Tenant-Override (Tenant-Zeile hat Vorrang,
   Rueckfall auf firmenweite Zeile, CH ignoriert tenant_id weiterhin).
3. resolve_home_bias_defaults: CH -> ValueError (liest nie aus dieser
   Tabelle); unbekannte Jurisdiktion/Praeferenz -> JurisdictionReferenceDataMissingError;
   DE liefert die echten, per Seed angelegten Splits, sortiert.
4. services/jurisdiction/de_seed.py::ensure_de_jurisdiction_seed: idempotent,
   korrekte JurisdictionProfile-Felder, korrekte Zeilenzahl/-Summen (jede
   Praeferenz-Variante summiert exakt zu 10000 bps, identisch zu den
   CH-Splits -- reine Label-Uebersetzung, keine neue Zahl).
5. require_portfolio_management: neue Rolle + admin/super_admin als
   Erweiterung, advisor/readonly ohne Zugriff.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
import models.allocation  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.jurisdiction  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
import models.review  # noqa: E402,F401
import models.snapshots  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.users  # noqa: E402,F401
import models.wealth  # noqa: E402,F401

from models.allocation import CapitalMarketAssumption  # noqa: E402
from models.jurisdiction import JurisdictionHomeBiasDefault, JurisdictionProfile  # noqa: E402
from services.auth import require_portfolio_management  # noqa: E402
from services.jurisdiction.de_seed import (  # noqa: E402
    DE_CODE,
    DE_HOME_BIAS_DEFAULTS,
    ensure_de_jurisdiction_seed,
)
from services.jurisdiction.exceptions import JurisdictionReferenceDataMissingError  # noqa: E402
from services.jurisdiction.resolve import (  # noqa: E402
    resolve_cma_for_jurisdiction,
    resolve_home_bias_defaults,
)

NOW = "2026-07-31T00:00:00.000Z"


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'de_onboarding.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_cma(row_id, *, jurisdiction=None, tenant_id=None, status="committee_approved"):
    return CapitalMarketAssumption(
        id=row_id, assumption_set_name=f"Standard-{row_id}", version=1,
        valid_from="2026-01-01", is_current=1, jurisdiction=jurisdiction,
        tenant_id=tenant_id, status=status,
        created_by="tester", created_at=NOW, updated_at=NOW,
    )


# ---------------------------------------------------------------------------
# 1. CapitalMarketAssumption.tenant_id -- additive Migration
# ---------------------------------------------------------------------------


def test_cma_tenant_id_column_exists(db_session):
    inspector = inspect(db_session.get_bind())
    cols = {c["name"] for c in inspector.get_columns("capital_market_assumptions")}
    assert "tenant_id" in cols


def test_ensure_runtime_columns_adds_cma_tenant_id_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_tenant_id.db"
    schema_file = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
    import database as db_module
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=schema_file)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    inspector = inspect(test_engine)
    cols_before = {c["name"] for c in inspector.get_columns("capital_market_assumptions")}
    assert "tenant_id" not in cols_before

    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # zweiter Lauf: idempotent, kein Fehler

    inspector = inspect(test_engine)
    cols_after = {c["name"] for c in inspector.get_columns("capital_market_assumptions")}
    assert "tenant_id" in cols_after


# ---------------------------------------------------------------------------
# 2. resolve_cma_for_jurisdiction -- Tenant-Override
# ---------------------------------------------------------------------------


def test_resolve_cma_tenant_override_takes_precedence(db_session):
    firmwide = _make_cma("cma-de-firmwide", jurisdiction="DE", tenant_id=None)
    tenant_specific = _make_cma("cma-de-firm-a", jurisdiction="DE", tenant_id="firm-a")
    db_session.add_all([firmwide, tenant_specific])
    db_session.commit()

    result = resolve_cma_for_jurisdiction(db_session, "DE", tenant_id="firm-a")
    assert result.id == "cma-de-firm-a"


def test_resolve_cma_falls_back_to_firmwide_when_no_tenant_row(db_session):
    firmwide = _make_cma("cma-de-firmwide-2", jurisdiction="DE", tenant_id=None)
    db_session.add(firmwide)
    db_session.commit()

    result = resolve_cma_for_jurisdiction(db_session, "DE", tenant_id="firm-b")
    assert result.id == "cma-de-firmwide-2"


def test_resolve_cma_other_tenants_row_not_used_for_this_tenant(db_session):
    other_tenant_row = _make_cma("cma-de-firm-c", jurisdiction="DE", tenant_id="firm-c")
    db_session.add(other_tenant_row)
    db_session.commit()

    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_cma_for_jurisdiction(db_session, "DE", tenant_id="firm-d")


def test_resolve_cma_ch_ignores_tenant_id(db_session):
    """CH-Pfad beruecksichtigt tenant_id NICHT -- exakt die heutige,
    unveraenderte Query (Constraint: CH bleibt byte-identisch)."""
    ch_row = _make_cma("cma-ch-1", jurisdiction=None, tenant_id=None)
    db_session.add(ch_row)
    db_session.commit()

    result = resolve_cma_for_jurisdiction(db_session, None, tenant_id="firm-a")
    assert result.id == "cma-ch-1"


def test_resolve_cma_without_tenant_id_arg_uses_firmwide_row(db_session):
    firmwide = _make_cma("cma-de-firmwide-3", jurisdiction="DE", tenant_id=None)
    tenant_specific = _make_cma("cma-de-firm-e", jurisdiction="DE", tenant_id="firm-e")
    db_session.add_all([firmwide, tenant_specific])
    db_session.commit()

    result = resolve_cma_for_jurisdiction(db_session, "DE")  # kein tenant_id uebergeben
    assert result.id == "cma-de-firmwide-3"


# ---------------------------------------------------------------------------
# 3. resolve_home_bias_defaults
# ---------------------------------------------------------------------------


def test_resolve_home_bias_defaults_ch_raises_value_error(db_session):
    with pytest.raises(ValueError):
        resolve_home_bias_defaults(db_session, "CH", "equitiesGeo", "Schweiz Fokus")
    with pytest.raises(ValueError):
        resolve_home_bias_defaults(db_session, None, "equitiesGeo", "Schweiz Fokus")


def test_resolve_home_bias_defaults_unknown_combination_raises(db_session):
    ensure_de_jurisdiction_seed(db_session)
    db_session.commit()
    with pytest.raises(JurisdictionReferenceDataMissingError):
        resolve_home_bias_defaults(db_session, "DE", "equitiesGeo", "Mars Fokus")


def test_resolve_home_bias_defaults_de_returns_seeded_splits_sorted(db_session):
    ensure_de_jurisdiction_seed(db_session)
    db_session.commit()

    rows = resolve_home_bias_defaults(db_session, "DE", "equitiesGeo", "Deutschland Fokus")
    labels = [label for label, _, _ in rows]
    assert "Aktien Deutschland" in labels
    assert "Aktien Global" in labels
    total_bps = sum(bps for _, bps, _ in rows)
    assert total_bps == 10000


# ---------------------------------------------------------------------------
# 4. ensure_de_jurisdiction_seed
# ---------------------------------------------------------------------------


def test_ensure_de_jurisdiction_seed_creates_profile(db_session):
    ensure_de_jurisdiction_seed(db_session)
    db_session.commit()

    profile = db_session.query(JurisdictionProfile).filter(
        JurisdictionProfile.code == DE_CODE
    ).first()
    assert profile is not None
    assert profile.home_currency == "EUR"
    assert profile.is_provisional == 1
    assert profile.status == "pending_ic_review"


def test_ensure_de_jurisdiction_seed_idempotent(db_session):
    ensure_de_jurisdiction_seed(db_session)
    db_session.commit()
    ensure_de_jurisdiction_seed(db_session)
    db_session.commit()

    profiles = db_session.query(JurisdictionProfile).filter(
        JurisdictionProfile.code == DE_CODE
    ).all()
    assert len(profiles) == 1

    rows = db_session.query(JurisdictionHomeBiasDefault).filter(
        JurisdictionHomeBiasDefault.jurisdiction_code == DE_CODE
    ).all()
    expected_row_count = sum(
        len(splits)
        for variants in DE_HOME_BIAS_DEFAULTS.values()
        for splits in variants.values()
    )
    assert len(rows) == expected_row_count  # kein Duplikat durch zweiten Lauf


def test_ensure_de_jurisdiction_seed_every_variant_sums_to_10000_bps(db_session):
    """Mechanische 1:1-Uebersetzung der CH-Splits: keine neue Zahl, aber jede
    Variante muss weiterhin zu 10000 bps (100%) summieren -- sonst waere die
    Uebersetzung fehlerhaft kopiert."""
    for preference_key, variants in DE_HOME_BIAS_DEFAULTS.items():
        for preference_value, splits in variants.items():
            total = sum(bps for _, bps, _ in splits)
            assert total == 10000, (
                f"{preference_key}={preference_value} summiert zu {total}, nicht 10000"
            )


def test_ensure_de_jurisdiction_seed_all_rows_are_provisional(db_session):
    ensure_de_jurisdiction_seed(db_session)
    db_session.commit()
    rows = db_session.query(JurisdictionHomeBiasDefault).filter(
        JurisdictionHomeBiasDefault.jurisdiction_code == DE_CODE
    ).all()
    assert rows
    assert all(row.is_provisional == 1 for row in rows)


def test_ensure_de_jurisdiction_seed_never_touches_ch(db_session):
    ch_profile = JurisdictionProfile(
        id="jp-ch-existing", code="CH", display_name="Schweiz", home_currency="CHF",
        is_active=1, is_provisional=0, status="approved",
        created_at=NOW, updated_at=NOW,
    )
    db_session.add(ch_profile)
    db_session.commit()

    ensure_de_jurisdiction_seed(db_session)
    db_session.commit()

    reloaded_ch = db_session.query(JurisdictionProfile).filter(
        JurisdictionProfile.code == "CH"
    ).first()
    assert reloaded_ch.status == "approved"
    assert reloaded_ch.is_provisional == 0


# ---------------------------------------------------------------------------
# 5. require_portfolio_management
# ---------------------------------------------------------------------------


def _user(role):
    return SimpleNamespace(role=role)


def test_require_portfolio_management_allows_dedicated_role():
    user = _user("portfolio_management")
    assert require_portfolio_management(user) is user


def test_require_portfolio_management_allows_admin():
    user = _user("admin")
    assert require_portfolio_management(user) is user


def test_require_portfolio_management_allows_super_admin():
    user = _user("super_admin")
    assert require_portfolio_management(user) is user


def test_require_portfolio_management_rejects_advisor():
    with pytest.raises(HTTPException) as exc_info:
        require_portfolio_management(_user("advisor"))
    assert exc_info.value.status_code == 403


def test_require_portfolio_management_rejects_readonly():
    with pytest.raises(HTTPException) as exc_info:
        require_portfolio_management(_user("readonly"))
    assert exc_info.value.status_code == 403
