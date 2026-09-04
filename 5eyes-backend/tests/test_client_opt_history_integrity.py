"""FIDLEG-STATE-001 (Audit 2026-08-27, docs/audits/2026-08-27-client-
classification-and-compliance-state-audit.md).

Reproduziert die im Audit dokumentierten Bypass-Pfade und beweist den Fix:

1. Der allgemeine Client-Update-Router (PUT /clients/{id}, routers/
   clients.py::update_client) kann client_classification/
   is_professional_opt_out/is_qualified_investor nicht mehr aendern --
   ClientUpdate besitzt diese Felder nicht mehr (schemas/clients.py).
2. Der dedizierte Uebergangspfad POST /clients/{id}/opt-history
   (routers/clients.py::add_opt_history) lehnt einen von der
   tatsaechlichen Client-Historie abweichenden from_classification-Wert
   mit 409 ab, statt ihn ungeprueft zu uebernehmen.
3. to_classification (und from_classification) sind auf die FIDLEG-
   Werteliste typisiert -- ein Wert ausserhalb des Enums (wie das im Audit
   reproduzierte 'BROKEN-CLASS') wird bereits beim Schema-Parsing (422)
   abgelehnt, bevor der Router ueberhaupt laeuft.
4. Der Golden Path (ein Berater aendert Stammdaten UND fuehrt separat einen
   korrekten, belegten Klassifikationsuebergang durch) bleibt unveraendert
   funktionsfaehig.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401 -- registers all mappers for Base.metadata.create_all
    allocation,
    client_login,
    clients,
    mandates,
    profiling,
    protocol_bausteine,
    refresh_token,
    review,
    snapshots,
    tenant,
    users,
    wealth,
)
from models.clients import Client, ClientOptHistory
from models.users import User
from routers.clients import add_opt_history, update_client
from schemas.clients import ClientUpdate, OptHistoryCreate

NOW = "2026-08-27T09:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'client_opt_history_integrity.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_advisor_and_client(session, *, classification="Privatkunde") -> tuple[User, Client]:
    advisor = User(
        id="advisor-optstate001",
        username="advisor-optstate001",
        password_hash="hash",
        full_name="Advisor OptState",
        role="advisor",
        is_active=1,
        created_at=NOW,
        updated_at=NOW,
    )
    client = Client(
        id="client-optstate001",
        client_number="C-OPTSTATE-001",
        first_name="Hans",
        last_name="Muster",
        country_of_residence="CH",
        language="DE",
        household_type="Einzelperson",
        client_classification=classification,
        is_professional_opt_out=0,
        is_qualified_investor=0,
        advisor_id=advisor.id,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(advisor)
    session.add(client)
    session.commit()
    return advisor, client


# ── 1. Bypass ueber den allgemeinen Client-Update-Router ist geschlossen ───────

def test_general_client_update_cannot_change_classification_or_optin(session_factory):
    with session_factory() as session:
        advisor, client = _seed_advisor_and_client(session)

        # Vor dem Fix akzeptierte ClientUpdate diese Felder direkt und der
        # Router wendete sie ohne jede Historie an (Audit-Reproduktion:
        # history_rows=0 nach einer erfolgreichen Privatkunde ->
        # Professioneller Kunde Aenderung). Die Felder existieren jetzt gar
        # nicht mehr auf ClientUpdate -- ein Body, der sie trotzdem mitschickt,
        # aendert an client_classification/opt-out/qualified NICHTS.
        body = ClientUpdate.model_validate({
            "first_name": "Hans-Ruedi",
            "client_classification": "Professioneller Kunde",
            "is_professional_opt_out": True,
            "is_qualified_investor": True,
        })
        updated = update_client(
            client_id=client.id, body=body, db=session, current_user=advisor,
        )

        assert updated.first_name == "Hans-Ruedi"  # normale Felder funktionieren weiterhin
        assert updated.client_classification == "Privatkunde"
        assert updated.is_professional_opt_out == 0
        assert updated.is_qualified_investor == 0
        history_rows = session.query(ClientOptHistory).filter(
            ClientOptHistory.client_id == client.id
        ).count()
        assert history_rows == 0


def test_general_client_update_normal_fields_unaffected(session_factory):
    """Regressionstest: der taegliche Stammdaten-Speicherpfad eines Beraters
    (Vorname/Nachname/Zivilstand etc., wie es die Electron-UI ueber
    saveClientData() tatsaechlich sendet -- OHNE Klassifikationsfelder) bleibt
    exakt gleich."""
    with session_factory() as session:
        advisor, client = _seed_advisor_and_client(session)
        body = ClientUpdate.model_validate({
            "first_name": "Erika",
            "last_name": "Musterfrau",
            "canton": "ZH",
            "civil_status": "verheiratet",
        })
        updated = update_client(
            client_id=client.id, body=body, db=session, current_user=advisor,
        )
        assert updated.first_name == "Erika"
        assert updated.last_name == "Musterfrau"
        assert updated.canton == "ZH"
        assert updated.civil_status == "verheiratet"
        assert updated.client_classification == "Privatkunde"


# ── 2. Opt-History validiert from_classification gegen den echten Zustand ─────

def test_opt_history_rejects_stale_from_classification(session_factory):
    with session_factory() as session:
        advisor, client = _seed_advisor_and_client(session, classification="Privatkunde")

        # Audit-Reproduktion: der Request behauptet einen Ausgangszustand
        # ('Institutioneller Kunde'), der nicht dem tatsaechlich gespeicherten
        # Zustand ('Privatkunde') entspricht.
        body = OptHistoryCreate(
            event_type="opt_up",
            from_classification="Institutioneller Kunde",
            to_classification="Professioneller Kunde",
            client_requested=True,
            document_id="doc-1",
        )
        with pytest.raises(HTTPException) as excinfo:
            add_opt_history(client_id=client.id, body=body, db=session, current_user=advisor)
        assert excinfo.value.status_code == 409

        session.refresh(client)
        assert client.client_classification == "Privatkunde"
        history_rows = session.query(ClientOptHistory).filter(
            ClientOptHistory.client_id == client.id
        ).count()
        assert history_rows == 0


def test_opt_history_rejects_out_of_enum_to_classification():
    # Audit-Reproduktion: 'BROKEN-CLASS' lag ausserhalb jedes Enums und wurde
    # zuvor direkt auf den Client geschrieben. Jetzt scheitert bereits das
    # Schema-Parsing (== 422 auf HTTP-Ebene), der Router laeuft nie an.
    with pytest.raises(ValidationError):
        OptHistoryCreate(
            event_type="opt_up",
            from_classification="Privatkunde",
            to_classification="BROKEN-CLASS",
            client_requested=True,
        )


def test_opt_history_valid_transition_updates_client_and_writes_history(session_factory):
    with session_factory() as session:
        advisor, client = _seed_advisor_and_client(session, classification="Privatkunde")

        body = OptHistoryCreate(
            event_type="opt_up",
            from_classification="Privatkunde",
            to_classification="Professioneller Kunde",
            client_requested=True,
            document_id="doc-signed-1",
            notes="Kundenantrag vom 2026-08-27, Beleg doc-signed-1 abgelegt",
        )
        entry = add_opt_history(client_id=client.id, body=body, db=session, current_user=advisor)

        assert entry.from_classification == "Privatkunde"
        assert entry.to_classification == "Professioneller Kunde"
        session.refresh(client)
        assert client.client_classification == "Professioneller Kunde"
        history_rows = session.query(ClientOptHistory).filter(
            ClientOptHistory.client_id == client.id
        ).all()
        assert len(history_rows) == 1
        assert history_rows[0].documented_by == advisor.id
