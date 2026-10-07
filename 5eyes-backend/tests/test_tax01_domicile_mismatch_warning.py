"""TAX-01 (Audit-Finding, 2026-10-07): kein Abgleich zwischen
Client.country_of_residence (im Advisory-Report als "Steuerdomizil"
angezeigt, services/advisory_report.py::_build_ausgangslage) und
Mandate.tax_jurisdiction (vom steuer-bewussten Monte-Carlo-/Cashflow-Pfad
unabhaengig genutzt). Zieht ein Kunde um, aktualisiert sich das angezeigte
Steuerdomizil sofort, waehrend die Projektions-Engine die alte
tax_jurisdiction unveraendert weiterverwendet, bis ein Berater sie manuell
nachzieht.

Testet den neuen, rein informativen/nicht-blockierenden Top-Level-Key
"tax_domicile_mismatch_warning" im Advisory-Report-Aggregator
(services/advisory_report.py::_build_tax_domicile_mismatch_warning):
- NULL wenn tax_jurisdiction NULL ist (steuer-naiv, Backwards-Compat).
- NULL wenn Laender-Praefix von tax_jurisdiction == country_of_residence
  (auch fuer kantonale Codes wie "CH-ZH").
- Gesetzt (klarer Hinweistext) bei einem echten Mismatch (z.B. Wohnsitz DE,
  Mandat "CH-ZH").
- tax_jurisdiction selbst wird NIE automatisch veraendert (advisor-
  gesteuert bleibt advisor-gesteuert).
- Immer im PROTECTED_REPORT_SECTIONS-Set (nicht per hidden_report_sections
  ausblendbar), analog zu provisional_data_warning.

Wiederverwendet dieselbe Seed-Helper-Struktur wie test_advisory_report.py
(_seed_minimal_mandate-Analogon), minimal gehalten fuer diesen einen Fund.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
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
from services.advisory_report import (
    PROTECTED_REPORT_SECTIONS,
    _build_tax_domicile_mismatch_warning,
    compute_advisory_report,
)

_NOW = "2026-10-07T09:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tax01.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(s, *, country: str = "CH", tax_jurisdiction: str | None = None) -> tuple[Mandate, Client, User]:
    advisor = User(
        id=str(uuid.uuid4()), username=f"adv-{uuid.uuid4().hex[:6]}", password_hash="h",
        full_name="Advisor Tax01", role="advisor", is_active=1,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(advisor)
    client = Client(
        id=str(uuid.uuid4()), client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Hans", last_name="Muster", advisor_id=advisor.id,
        country_of_residence=country, created_at=_NOW, updated_at=_NOW,
    )
    s.add(client)
    mandate = Mandate(
        id=str(uuid.uuid4()), client_id=client.id, mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung", opened_at=_NOW,
        tax_jurisdiction=tax_jurisdiction,
        created_at=_NOW, updated_at=_NOW,
    )
    s.add(mandate)
    s.flush()
    return mandate, client, advisor


# ---------------------------------------------------------------------------
# Unit-level: _build_tax_domicile_mismatch_warning
# ---------------------------------------------------------------------------

def test_no_warning_when_tax_jurisdiction_is_null():
    client = Client(country_of_residence="DE")
    mandate = Mandate(tax_jurisdiction=None)
    assert _build_tax_domicile_mismatch_warning(client, mandate) is None


def test_no_warning_when_countries_match_exactly():
    client = Client(country_of_residence="CH")
    mandate = Mandate(tax_jurisdiction="CH")
    assert _build_tax_domicile_mismatch_warning(client, mandate) is None


def test_no_warning_when_cantonal_jurisdiction_prefix_matches():
    client = Client(country_of_residence="CH")
    mandate = Mandate(tax_jurisdiction="CH-ZH")
    assert _build_tax_domicile_mismatch_warning(client, mandate) is None


def test_warning_set_on_genuine_mismatch():
    client = Client(country_of_residence="DE")
    mandate = Mandate(tax_jurisdiction="CH-ZH")
    warning = _build_tax_domicile_mismatch_warning(client, mandate)
    assert warning is not None
    assert "DE" in warning
    assert "CH-ZH" in warning
    assert "Steuersitz" in warning


def test_warning_case_insensitive_normalized():
    client = Client(country_of_residence="de")
    mandate = Mandate(tax_jurisdiction="ch-zh")
    warning = _build_tax_domicile_mismatch_warning(client, mandate)
    assert warning is not None
    assert "DE" in warning
    assert "CH-ZH" in warning


def test_no_warning_when_country_of_residence_missing():
    client = Client(country_of_residence=None)
    mandate = Mandate(tax_jurisdiction="CH-ZH")
    assert _build_tax_domicile_mismatch_warning(client, mandate) is None


# ---------------------------------------------------------------------------
# Integration: compute_advisory_report top-level field
# ---------------------------------------------------------------------------

def test_report_has_no_mismatch_for_consistent_domicile(session_factory):
    with session_factory() as s:
        mandate, client, advisor = _seed(s, country="CH", tax_jurisdiction="CH-ZH")
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["tax_domicile_mismatch_warning"] is None


def test_report_surfaces_mismatch_warning(session_factory):
    with session_factory() as s:
        mandate, client, advisor = _seed(s, country="DE", tax_jurisdiction="CH-ZH")
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    warning = report["tax_domicile_mismatch_warning"]
    assert warning is not None
    assert "DE" in warning and "CH-ZH" in warning


def test_mismatch_check_does_not_mutate_tax_jurisdiction(session_factory):
    """Advisory-only: der Check darf tax_jurisdiction NIE automatisch
    anpassen -- das bleibt bewusst advisor-gesteuert."""
    with session_factory() as s:
        mandate, client, advisor = _seed(s, country="DE", tax_jurisdiction="CH-ZH")
        s.commit()
        compute_advisory_report(s, mandate, advisor=advisor)
        s.refresh(mandate)
        assert mandate.tax_jurisdiction == "CH-ZH"


def test_tax_domicile_warning_is_protected_from_hiding(session_factory):
    assert "tax_domicile_mismatch_warning" in PROTECTED_REPORT_SECTIONS
    with session_factory() as s:
        mandate, client, advisor = _seed(s, country="DE", tax_jurisdiction="CH-ZH")
        mandate.hidden_report_sections = json.dumps(["tax_domicile_mismatch_warning"])
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    assert report["tax_domicile_mismatch_warning"] is not None
