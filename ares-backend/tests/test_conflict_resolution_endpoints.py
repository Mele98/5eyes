"""CONFLICT-RESOLUTION-001: Interessenkonflikte produktiv aufloesen.

Codex-Review zu PR #585, Punkt 3 -- im Code verifiziert: es gab nur
`GET /mandates/{id}/conflicts` und `POST /mandates/{id}/conflicts`, und das
CREATE setzte `disclosed_to_client=0, client_acknowledged=0` HART. Kein
Endpunkt hat diese Flags je geaendert. Ein Konflikt liess sich also erfassen,
aber niemals aufloesen.

Das war nicht bloss eine fehlende Bequemlichkeit: mit CONFLICT-STATE-001
meldet der Report jeden nicht vollstaendig belegten Konflikt als offen, und
ein Finalisierungs-Gate darauf (COST-FINALIZATION-001) haette jedes Mandat
mit einer einzigen Konfliktzeile unaufloesbar blockiert -- fail-closed waere
nicht sicher gewesen, sondern funktionsunfaehig. Deshalb kommen die
Endpunkte VOR dem Gate.

Geprueft wird hier besonders, was NICHT erzeugbar sein darf:
der Widerspruch "bestaetigt, aber nie offengelegt", und das Ueberschreiben
eines bereits erfassten Zeitpunkts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.review import ConflictOfInterestDisclosure  # noqa: E402

from test_cost_disclosure_endpoint import (  # noqa: E402,F401
    _now, _seed_mandate, advisor_user, auth_client, session_factory,
)


def _create_conflict(auth_client, mandate_id: str, **overrides) -> str:
    body = {
        "conflict_type": "Retrozession / Inducement",
        "description": "Vertriebsentschaedigung Fondsanbieter",
        "inducement_provider": "Fund Provider AG",
        "inducement_amount_rappen": 50_000_00,
        "inducement_frequency": "jährlich",
        "data_classification": "synthetic",
    }
    body.update(overrides)
    resp = auth_client.post(f"/mandates/{mandate_id}/conflicts", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Der Ausgangszustand, als eigener Test
# ---------------------------------------------------------------------------


def test_new_conflict_starts_undisclosed(auth_client, advisor_user, session_factory):
    """Vorbedingung der Tests darunter -- und der Befund selbst.

    CREATE erzwingt 0/0. Ohne diesen Anker waere bei einer spaeteren
    Aenderung des Defaults nicht erkennbar, ob die Tests unten noch den
    gemeinten Uebergang pruefen.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    resp = auth_client.get(f"/mandates/{mandate_id}/conflicts")
    assert resp.status_code == 200, resp.text
    row = next(item for item in resp.json() if item["id"] == conflict_id)
    assert row["disclosed_to_client"] == 0
    assert row["client_acknowledged"] == 0


# ---------------------------------------------------------------------------
# Die drei Uebergaenge
# ---------------------------------------------------------------------------


def test_disclose_records_timestamp_actor_and_document(
    auth_client, advisor_user, session_factory,
):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
        json={"document_id": "doc-offenlegung-1"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["disclosed_to_client"] == 1
    assert data["disclosed_at"]
    assert data["document_id"] == "doc-offenlegung-1"
    assert data["disclosed_by"] == advisor_user.id
    # Offengelegt, aber noch nicht bestaetigt -- und der Endpunkt SAGT das.
    assert data["resolution_state"] == "disclosed_unacknowledged"
    assert "conflict_not_acknowledged" in data["missing_evidence"]


def test_full_resolution_reaches_resolved(auth_client, advisor_user, session_factory):
    """Der Weg bis zum Ende -- die Gegenprobe zu allem Blockieren.

    Ohne diesen Test waere eine Implementierung, die jeden Uebergang
    ablehnt, von den Blockade-Tests unten nicht zu unterscheiden.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
        json={"document_id": "doc-offenlegung-2"},
    )
    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge", json={},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["client_acknowledged"] == 1
    assert data["client_acknowledged_at"]
    assert data["resolution_state"] == "resolved", data
    assert data["missing_evidence"] == []


def test_disclosure_without_document_stays_evidence_incomplete(
    auth_client, advisor_user, session_factory,
):
    """Ohne Dokument wird die Offenlegung erfasst, aber nicht als belegt.

    Das Dokument zu VERLANGEN waere die naheliegende Verschaerfung und
    falsch: der Berater soll das Gespraech protokollieren koennen, auch wenn
    die Ablage noch aussteht. Der Zustand bleibt dann sichtbar unvollstaendig
    statt die Offenlegung ganz zu verweigern.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose", json={},
    )
    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge", json={},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["resolution_state"] == "evidence_incomplete", data
    assert "conflict_disclosure_document_missing" in data["missing_evidence"]


def test_mitigate_records_the_measure(auth_client, advisor_user, session_factory):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/mitigate",
        json={"mitigation_action": "Retrozession wird vollumfänglich erstattet"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["mitigation_action"] == (
        "Retrozession wird vollumfänglich erstattet"
    )


@pytest.mark.parametrize("action", ["", "  ", "ok"])
def test_mitigate_rejects_an_empty_placeholder(
    auth_client, advisor_user, session_factory, action,
):
    """Eine Massnahme muss etwas aussagen.

    Ohne Mindestlaenge waere ein Leerzeichen eine dokumentierte Massnahme --
    dieselbe Klasse wie eine Begruendung, die niemand gelesen hat.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/mitigate",
        json={"mitigation_action": action},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Was NICHT erzeugbar sein darf
# ---------------------------------------------------------------------------


def test_acknowledge_without_disclosure_is_refused(
    auth_client, advisor_user, session_factory,
):
    """Der Kunde kann nicht bestaetigen, was ihm nie offengelegt wurde.

    CONFLICT-STATE-001 meldet genau diesen Widerspruch als
    `acknowledged_without_disclosure`. Hier wird er von vornherein
    verhindert, statt ihn erzeugbar zu lassen und nachtraeglich zu beklagen.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge", json={},
    )
    assert resp.status_code == 409, resp.text
    assert "offengelegt" in resp.json()["detail"]

    # Und der Zustand ist unveraendert -- kein Teileffekt.
    with session_factory() as db:
        row = db.query(ConflictOfInterestDisclosure).filter(
            ConflictOfInterestDisclosure.id == conflict_id,
        ).first()
        assert row.client_acknowledged == 0
        assert row.client_acknowledged_at is None


def test_second_disclosure_does_not_overwrite_the_first_timestamp(
    auth_client, advisor_user, session_factory,
):
    """Der urspruengliche Zeitpunkt IST der Nachweis.

    Ihn durch einen neuen zu ersetzen wuerde ihn vernichten -- deshalb 409
    statt eines stillen Updates.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    first = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose", json={},
    )
    assert first.status_code == 200, first.text
    original = first.json()["disclosed_at"]

    second = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose", json={},
    )
    assert second.status_code == 409, second.text

    listed = auth_client.get(f"/mandates/{mandate_id}/conflicts").json()
    row = next(item for item in listed if item["id"] == conflict_id)
    assert row["disclosed_at"] == original


def test_second_acknowledgement_is_refused(
    auth_client, advisor_user, session_factory,
):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)
    auth_client.post(f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose", json={})
    auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge", json={},
    )
    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge", json={},
    )
    assert resp.status_code == 409, resp.text


def test_future_timestamp_is_refused(auth_client, advisor_user, session_factory):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
        json={"disclosed_at": "2099-01-01T00:00:00.000Z"},
    )
    assert resp.status_code == 422, resp.text
    assert "Zukunft" in resp.json()["detail"]


def test_timestamp_before_the_conflict_existed_is_refused(
    auth_client, advisor_user, session_factory,
):
    """Ein Nachtrag ja, eine Erfindung nein.

    Ein Gespraech von gestern nachzutragen ist der Normalfall. Ein Datum,
    das VOR der Erfassung des Konflikts liegt, ist kein Nachtrag mehr.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
        json={"disclosed_at": "2000-01-01T00:00:00.000Z"},
    )
    assert resp.status_code == 422, resp.text
    assert "vor der Erfassung" in resp.json()["detail"]


def test_backdated_timestamp_within_bounds_is_accepted(
    auth_client, advisor_user, session_factory,
):
    """Gegenprobe zu den beiden Grenzen: der legitime Nachtrag geht durch.

    Ohne diesen Test waere eine Implementierung, die JEDE Angabe ablehnt und
    immer die Serverzeit nimmt, von den Grenz-Tests nicht zu unterscheiden --
    und der Berater koennte den tatsaechlichen Zeitpunkt nie erfassen.
    """
    mandate_id = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_id)

    with session_factory() as db:
        created_at = db.query(ConflictOfInterestDisclosure).filter(
            ConflictOfInterestDisclosure.id == conflict_id,
        ).first().created_at

    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
        json={"disclosed_at": created_at},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["disclosed_at"] == created_at


def test_conflict_of_a_foreign_mandate_is_not_reachable(
    auth_client, advisor_user, session_factory,
):
    """Mandatsbindung, gleiche Haertung wie COST-BASIS-001.

    Das zweite Mandat wird direkt angelegt und nicht ueber `_seed_mandate`:
    jener Helfer legt denselben Kunden erneut an und bricht an der
    Unique-Constraint auf `client_number`.
    """
    from models.mandates import Mandate

    mandate_a = _seed_mandate(session_factory, advisor_user)
    conflict_id = _create_conflict(auth_client, mandate_a)

    mandate_b = "mdt-foreign"
    with session_factory() as db:
        source = db.query(Mandate).filter(Mandate.id == mandate_a).first()
        db.add(Mandate(
            id=mandate_b, client_id=source.client_id, mandate_number="M-FOREIGN",
            mandate_type=source.mandate_type, status=source.status,
            base_currency=source.base_currency, opened_at=_now(),
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()

    resp = auth_client.post(
        f"/mandates/{mandate_b}/conflicts/{conflict_id}/disclose", json={},
    )
    assert resp.status_code == 404, resp.text

    # Und der Konflikt des eigenen Mandats ist unveraendert.
    with session_factory() as db:
        row = db.query(ConflictOfInterestDisclosure).filter(
            ConflictOfInterestDisclosure.id == conflict_id,
        ).first()
        assert row.disclosed_to_client == 0


def test_unknown_conflict_is_404(auth_client, advisor_user, session_factory):
    mandate_id = _seed_mandate(session_factory, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/conflicts/gibtsnicht/disclose", json={},
    )
    assert resp.status_code == 404, resp.text
