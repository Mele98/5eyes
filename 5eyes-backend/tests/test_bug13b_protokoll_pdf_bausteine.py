"""Bug-#13b (2026-06-08): Beratungsprotokoll-PDF rendert ausgewaehlte Bausteine.

Pendant zu PR #244 (Backend-CRUD) + PR #245 (Frontend-Modal). Diese PR
verbindet die Selektion mit dem Protokoll-PDF.

Tests:
- ProtokollData-Dataclass akzeptiert selected_bausteine
- pdf_reports._build_protokoll_data laedt Mandate-Selektion (Override-Vorrang)
- protokoll.build_protokoll_flowables rendert die Bausteine-Sektion nur
  wenn Bausteine vorhanden sind
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from models.clients import Client
from models.mandates import Mandate
from models.protocol_bausteine import (
    MandateBausteinSelection,
    ProtocolBaustein,
)
from models.users import User
from services.pdf.base import ProtokollData


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


def test_protokoll_data_hat_selected_bausteine_feld():
    fields = {f.name for f in ProtokollData.__dataclass_fields__.values()}
    assert "selected_bausteine" in fields


def test_protokoll_data_default_ist_leere_liste():
    d = ProtokollData()
    assert d.selected_bausteine == []


# ---------------------------------------------------------------------------
# _build_protokoll_data: Selektion + Override-Vorrang
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bug13b.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def seeded_mandate(session_factory):
    with session_factory() as db:
        advisor = User(
            id="advisor-pdf", username="advisor-pdf", password_hash="h",
            full_name="A", role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        )
        db.add(advisor)
        db.add(Client(
            id="cli-pdf", client_number="C-PDF", first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor.id,
            created_at=_now(), updated_at=_now(),
        ))
        mandate = Mandate(
            id="mdt-pdf", client_id="cli-pdf", mandate_number="M-PDF",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-06-08",
            created_at=_now(), updated_at=_now(),
        )
        db.add(mandate)
        # Bibliotheks-Bausteine
        db.add(ProtocolBaustein(
            id="b-1", advisor_id="advisor-pdf", title="Risikoaufklaerung",
            content_md="Standard-Risikoaufklaerung-Text", category="Risiko",
            sort_order=10, is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(ProtocolBaustein(
            id="b-2", advisor_id="advisor-pdf", title="Anlagephilosophie",
            content_md="Strategietreue, keine aktive Ueberwachung",
            category="Strategie", sort_order=20, is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        # Selektion mit Override-Test
        db.add(MandateBausteinSelection(
            id=str(uuid.uuid4()), mandate_id="mdt-pdf", baustein_id="b-1",
            sort_order=0, custom_override_md=None,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(MandateBausteinSelection(
            id=str(uuid.uuid4()), mandate_id="mdt-pdf", baustein_id="b-2",
            sort_order=1,
            custom_override_md="Lokal angepasste Anlagephilosophie",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
        # Refetch
        m = db.query(Mandate).filter(Mandate.id == "mdt-pdf").first()
        db.expunge_all()
    return m


def test_build_protokoll_data_lieft_bausteine_mit_override(seeded_mandate, session_factory):
    from routers.pdf_reports import _build_protokoll_data

    with session_factory() as db:
        # Re-fetch im offenen Session-Scope
        mandate = db.query(Mandate).filter(Mandate.id == "mdt-pdf").first()
        data = _build_protokoll_data(mandate, db)

    assert len(data.selected_bausteine) == 2
    by_title = {b["title"]: b for b in data.selected_bausteine}
    # Override-Vorrang: Anlagephilosophie hat custom_override_md
    assert by_title["Anlagephilosophie"]["content_md"] == "Lokal angepasste Anlagephilosophie"
    # Kein Override: Risikoaufklaerung -> Bibliotheks-Default
    assert by_title["Risikoaufklaerung"]["content_md"] == "Standard-Risikoaufklaerung-Text"
    # Category durchgereicht
    assert by_title["Risikoaufklaerung"]["category"] == "Risiko"


def test_build_protokoll_data_leere_liste_bei_keiner_selektion(session_factory):
    """Mandat ohne Selektion -> leere selected_bausteine, kein Crash."""
    from routers.pdf_reports import _build_protokoll_data

    with session_factory() as db:
        advisor = User(
            id="a2", username="a2", password_hash="h", full_name="A2",
            role="advisor", is_active=1, created_at=_now(), updated_at=_now(),
        )
        db.add(advisor)
        db.add(Client(
            id="c2", client_number="C-2", first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor.id,
            created_at=_now(), updated_at=_now(),
        ))
        m = Mandate(
            id="m2", client_id="c2", mandate_number="M-2",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-06-08",
            created_at=_now(), updated_at=_now(),
        )
        db.add(m)
        db.commit()
        data = _build_protokoll_data(m, db)
        assert data.selected_bausteine == []


# ---------------------------------------------------------------------------
# Flowables: Sektion erscheint nur bei Bausteinen
# ---------------------------------------------------------------------------


def _flowable_text_blob(flowables) -> str:
    out = []
    for f in flowables:
        txt = getattr(f, "text", None)
        if txt:
            out.append(str(txt))
        elif hasattr(f, "_text"):
            out.append(str(f._text))
    return "\n".join(out)


def test_pdf_keine_bausteine_sektion_wenn_leer():
    from services.pdf.base import PDFContext
    from services.pdf.documents.protokoll import build_protokoll_flowables
    ctx = PDFContext(
        mandate_name="Test", advisor_name="A",
        report_date=datetime.date(2026, 6, 8), base_currency="CHF",
    )
    data = ProtokollData(mandate_number="M-1", selected_bausteine=[])
    flow = build_protokoll_flowables(ctx, data)
    blob = _flowable_text_blob(flow)
    assert "BAUSTEINE ZUM BERATUNGSPROTOKOLL" not in blob


def test_pdf_bausteine_sektion_wird_gerendert():
    from services.pdf.base import PDFContext
    from services.pdf.documents.protokoll import build_protokoll_flowables
    ctx = PDFContext(
        mandate_name="Test", advisor_name="A",
        report_date=datetime.date(2026, 6, 8), base_currency="CHF",
    )
    data = ProtokollData(
        mandate_number="M-1",
        selected_bausteine=[
            {"title": "Risikoaufklaerung", "content_md": "Standard-Text",
             "category": "Risiko", "sort_order": 0, "custom_override_md": None},
            {"title": "Anlagephilosophie", "content_md": "Override-Text",
             "category": "Strategie", "sort_order": 1,
             "custom_override_md": "Override-Text"},
        ],
    )
    flow = build_protokoll_flowables(ctx, data)
    blob = _flowable_text_blob(flow)
    # Section-Title-Funktion uppercased den String.
    assert "BAUSTEINE ZUM BERATUNGSPROTOKOLL" in blob
    assert "Risikoaufklaerung" in blob
    assert "Anlagephilosophie" in blob
    assert "Standard-Text" in blob
    assert "Override-Text" in blob


def test_pdf_bausteine_respektieren_sort_order():
    from services.pdf.base import PDFContext
    from services.pdf.documents.protokoll import build_protokoll_flowables
    ctx = PDFContext(
        mandate_name="Test", advisor_name="A",
        report_date=datetime.date(2026, 6, 8), base_currency="CHF",
    )
    # Bewusst rueckwaerts uebergeben — sort_order soll die Reihenfolge
    # erzwingen.
    data = ProtokollData(
        mandate_number="M-1",
        selected_bausteine=[
            {"title": "ZWEITER", "content_md": "x", "category": None,
             "sort_order": 5, "custom_override_md": None},
            {"title": "ERSTER", "content_md": "y", "category": None,
             "sort_order": 1, "custom_override_md": None},
        ],
    )
    flow = build_protokoll_flowables(ctx, data)
    blob = _flowable_text_blob(flow)
    assert blob.index("ERSTER") < blob.index("ZWEITER")
