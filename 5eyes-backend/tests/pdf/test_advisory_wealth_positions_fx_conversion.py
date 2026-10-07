"""Regression fuer FX-DRIFT-001 + P2-3 (Audit-Finding, 2026-10-07).

routers/pdf_reports.py::_advisory_wealth_positions() und der "Other Wealth"-
Block fuetterten die Anlagestrategie-PDF's Vermoegensuebersicht-Tabelle
bisher mit UNKONVERTIERTEN WealthPosition.current_value_rappen-Betraegen,
obwohl die Spalte als "Betrag ({base_currency})" beschriftet ist. Seit
BASE-CURRENCY-HARDCODED-001 (2026-09-27) koennen Mandate eine Nicht-CHF
base_currency haben, wodurch eine Position in einer anderen Waehrung real
vorkommen kann. Ausserdem verglich beide Bloecke `assignment` per exaktem
String statt per canonical_assignment() (Legacy-Alias-Normalisierung).

Diese Tests decken beide Baustellen ab.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.tenant  # noqa: F401
configure_mappers()

from models.clients import Client
from models.mandates import Mandate
from models.users import User
from models.wealth import WealthPosition
from routers.pdf_reports import _advisory_wealth_positions, _other_wealth_positions


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'advisory_wealth_positions_fx.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate(session_factory, *, base_currency: str) -> tuple[str, str]:
    advisor_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(
            id=advisor_id, username=f"adv-{advisor_id[:6]}", password_hash="h",
            full_name="Adv Test", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-{cid[:6]}", first_name="Fx", last_name="Wealth",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
            mandate_type="Anlageberatung", opened_at=now,
            base_currency=base_currency,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return cid, mid


def test_advisory_wealth_positions_converts_non_base_currency_position(session_factory):
    """Mandat in EUR, Position in CHF -> Total muss FX-konvertiert sein,
    nicht der rohe CHF-Rappen-Betrag."""
    cid, mid = _seed_mandate(session_factory, base_currency="EUR")
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Depot CHF", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_00, currency="CHF",
            alloc_equities_bps=10000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        positions, current_bps, total = _advisory_wealth_positions(mandate, s)

    # CHF 100'000 darf NICHT 1:1 als "total" (EUR) erscheinen -- das wuerde
    # bedeuten, dass gar keine Konvertierung stattgefunden hat.
    assert total != 100_000_00
    # Erwartete Konvertierung: cross_rate(CHF->EUR) = 1.0/0.95 (DEFAULT_FX_RATES).
    expected = round(100_000_00 * (1.0 / 0.95))
    assert total == expected
    assert len(positions) == 1
    assert positions[0]["current_amount_rappen"] == expected


def test_advisory_wealth_positions_identity_when_same_currency(session_factory):
    """Mandat in CHF, Position in CHF -> keine Konvertierung noetig,
    Betrag bleibt unveraendert (Identity-Fall, Backwards-Compat)."""
    cid, mid = _seed_mandate(session_factory, base_currency="CHF")
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Depot CHF", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_00, currency="CHF",
            alloc_equities_bps=10000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        _, _, total = _advisory_wealth_positions(mandate, s)

    assert total == 100_000_00


def test_advisory_wealth_positions_recognizes_legacy_assignment_alias(session_factory):
    """P2-3: eine Position mit dem fruehen Legacy-Label 'Beratungsvermoegen'
    (ohne Umlaut) muss trotzdem in der Beratungsvermoegen-Tabelle erscheinen
    -- exaktes String-Match wuerde sie faelschlich ausschliessen, obwohl die
    SAA-Engine (canonical_assignment) sie korrekt zuordnet."""
    cid, mid = _seed_mandate(session_factory, base_currency="CHF")
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Legacy Depot", position_type="Depot",
            assignment="Beratungsvermoegen",  # Legacy-Alias ohne Umlaut
            current_value_rappen=50_000_00, currency="CHF",
            alloc_equities_bps=10000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        positions, _, total = _advisory_wealth_positions(mandate, s)

    assert total == 50_000_00
    assert len(positions) == 1


def test_other_wealth_positions_converts_non_base_currency_position(session_factory):
    """Mandat in EUR, 'Anderes Vermoegen'-Position in CHF -> Betrag muss
    FX-konvertiert sein, nicht der rohe CHF-Rappen-Betrag."""
    cid, mid = _seed_mandate(session_factory, base_currency="EUR")
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Externes Depot CHF", position_type="Depot",
            assignment="Eigenvermögen",
            current_value_rappen=200_000_00, currency="CHF",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        other = _other_wealth_positions(mandate, s)

    assert len(other) == 1
    expected = round(200_000_00 * (1.0 / 0.95))
    assert other[0]["amount_rappen"] == expected


def test_other_wealth_positions_recognizes_legacy_assignment_alias(session_factory):
    """P2-3: eine Position mit einem fruehen Legacy-Assignment-Label
    ('Vorsorge' aus LEGACY_EXTERNAL_WEALTH_ASSIGNMENTS) muss weiterhin als
    'Other Wealth' erscheinen -- canonical_assignment() normalisiert sie
    korrekt, exaktes String-Match wuerde nichts aendern (schliesst hier aber
    nicht aus, nur die Beratungsvermoegen-Ausschluss-Seite ist betroffen)."""
    cid, mid = _seed_mandate(session_factory, base_currency="CHF")
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Vorsorge-Depot", position_type="Vorsorge",
            assignment="Vorsorge",
            current_value_rappen=75_000_00, currency="CHF",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        other = _other_wealth_positions(mandate, s)

    assert len(other) == 1
    assert other[0]["amount_rappen"] == 75_000_00


def test_other_wealth_positions_excludes_advisory_legacy_alias(session_factory):
    """Umkehrfall zu test_advisory_wealth_positions_recognizes_legacy_assignment_
    alias: eine Position mit dem Beratungsvermoegen-Legacy-Label (ohne Umlaut)
    darf NICHT in 'Other Wealth' auftauchen -- canonical_assignment() muss sie
    als Beratungsvermoegen erkennen und damit hier ausschliessen."""
    cid, mid = _seed_mandate(session_factory, base_currency="CHF")
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Legacy Depot", position_type="Depot",
            assignment="Beratungsvermoegen",  # Legacy-Alias ohne Umlaut
            current_value_rappen=50_000_00, currency="CHF",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        other = _other_wealth_positions(mandate, s)

    assert other == []
