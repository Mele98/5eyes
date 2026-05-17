"""Sprint 9 Phase 2: FXRateSource.from_db Tests + Upsert-API."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
import models.allocation  # noqa
import models.clients  # noqa
import models.fx_rate  # noqa
import models.mandates  # noqa
import models.profiling  # noqa
import models.review  # noqa
import models.snapshots  # noqa
import models.users  # noqa
import models.wealth  # noqa
from models.fx_rate import FXRate
from services.currency.fx_rates import DEFAULT_FX_RATES, FXRateSource


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fx_test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = SF()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_from_db_empty_returns_defaults(db_session):
    """Wenn DB leer → Default-Rates."""
    source = FXRateSource.from_db(db_session)
    assert source.rate_to_chf("EUR") == DEFAULT_FX_RATES["EUR"]


def test_from_db_with_one_override(db_session):
    """1 Custom-Rate in DB → Default plus dieser Override."""
    now = _now()
    db_session.add(FXRate(
        id="fx-1", currency="EUR", rate_x10000=9700,  # 0.97
        valid_from=now, valid_until=None, is_current=1,
        source="Manual", created_at=now, updated_at=now,
    ))
    db_session.commit()

    source = FXRateSource.from_db(db_session)
    assert source.rate_to_chf("EUR") == 0.97
    # Defaults bleiben fuer andere Currencies
    assert source.rate_to_chf("USD") == DEFAULT_FX_RATES["USD"]


def test_from_db_chf_always_one_even_if_in_db(db_session):
    """Wenn jemand CHF auf 0.5 setzt: wird ignoriert, bleibt 1.0."""
    now = _now()
    db_session.add(FXRate(
        id="fx-chf", currency="CHF", rate_x10000=5000,  # 0.5 (FALSCH)
        valid_from=now, is_current=1, source="Manual",
        created_at=now, updated_at=now,
    ))
    db_session.commit()
    source = FXRateSource.from_db(db_session)
    assert source.rate_to_chf("CHF") == 1.0


def test_from_db_ignores_non_current(db_session):
    """is_current=0 wird ignoriert (historische Versionen)."""
    now = _now()
    db_session.add(FXRate(
        id="fx-old", currency="EUR", rate_x10000=8000,  # 0.80 (alt)
        valid_from=now, valid_until=now, is_current=0,
        source="Manual", created_at=now, updated_at=now,
    ))
    db_session.add(FXRate(
        id="fx-new", currency="EUR", rate_x10000=9500,  # 0.95 (neu)
        valid_from=now, valid_until=None, is_current=1,
        source="Manual", created_at=now, updated_at=now,
    ))
    db_session.commit()
    source = FXRateSource.from_db(db_session)
    assert source.rate_to_chf("EUR") == 0.95


def test_from_db_invalid_rate_ignored(db_session):
    """rate_x10000=0 oder negativ wird uebersprungen → Default."""
    now = _now()
    db_session.add(FXRate(
        id="fx-bad", currency="EUR", rate_x10000=0,
        valid_from=now, is_current=1, source="Manual",
        created_at=now, updated_at=now,
    ))
    db_session.commit()
    source = FXRateSource.from_db(db_session)
    assert source.rate_to_chf("EUR") == DEFAULT_FX_RATES["EUR"]


def test_from_db_invalid_currency_ignored(db_session):
    """2-stelliger Code wird uebersprungen (defensive)."""
    now = _now()
    db_session.add(FXRate(
        id="fx-bad-ccy", currency="XX", rate_x10000=10000,
        valid_from=now, is_current=1, source="Manual",
        created_at=now, updated_at=now,
    ))
    db_session.commit()
    source = FXRateSource.from_db(db_session)
    # Source initialisiert ohne XX
    assert "XX" not in source.supported_currencies()


def test_from_db_returns_valid_source(db_session):
    """from_db ist FXRateSource-Instanz mit funktionierender Cross-Rate."""
    now = _now()
    db_session.add(FXRate(
        id="fx-eur", currency="EUR", rate_x10000=9500,
        valid_from=now, is_current=1, source="Manual",
        created_at=now, updated_at=now,
    ))
    db_session.commit()
    source = FXRateSource.from_db(db_session)
    cross = source.cross_rate("EUR", "USD")
    assert cross > 0


def test_from_db_db_error_falls_back_to_defaults():
    """Bei DB-Crash → Default-Source (defensive)."""
    class _BrokenDB:
        def query(self, *_):
            raise RuntimeError("DB down")

    source = FXRateSource.from_db(_BrokenDB())
    assert source.rate_to_chf("EUR") == DEFAULT_FX_RATES["EUR"]
