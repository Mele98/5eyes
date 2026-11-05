"""C-860-01-Folgebefund: Nachgetragene Konflikt-Zeitpunkte (disclosed_at /
acknowledged_at) werden als echte UTC-Zeitpunkte gegen Serverzeit und
Erfassungszeitpunkt geprueft, nicht als Text.

Vorher (routers/review.py, _validated_event_timestamp): ``candidate > now``
und ``candidate < created_at`` als Stringvergleich. Ein Zeitpunkt mit einem
Offset ungleich UTC wurde damit falsch eingeordnet -- ein vergangener
Zeitpunkt in '+05:00' galt als Zukunft, ein zukuenftiger in '-05:00' wurde
angenommen. Gegenprobe: mit dem Textvergleich sind die Offset-Faelle rot.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import time_machine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from test_cost_disclosure_endpoint import (  # noqa: E402,F401
    _now, _seed_mandate, advisor_user, auth_client, session_factory,
)
from test_conflict_resolution_endpoints import _create_conflict  # noqa: E402

# Konflikt wird um 10:00:00Z erfasst, die Uhr steht danach still.
FROZEN = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(("raw", "status", "reason"), [
    # 10:00:00Z, gleiche Sekunde wie die Erfassung, in '+00:00' statt '.000Z':
    # als Text '...00+00:00' < '...00.000Z' -> faelschlich "vor der Erfassung".
    ("2026-11-05T10:00:00+00:00", 200, None),
    # 11:00+01:00 = 10:00Z: gleichzeitig mit der Erfassung, zulaessig.
    ("2026-11-05T11:00:00+01:00", 200, None),
    # 14:00+05:00 = 09:00Z: vor der Erfassung -> 422 (als Text galt es als Zukunft).
    ("2026-11-05T14:00:00+05:00", 422, "vor der Erfassung"),
    # 09:30-05:00 = 14:30Z: Zukunft -> 422 (als Text faelschlich angenommen,
    # denn '...T09' < '...T10').
    ("2026-11-05T09:30:00-05:00", 422, "Zukunft"),
    # 10:30+02:00 = 08:30Z: vor der Erfassung -> 422 (als Text galt es als Zukunft).
    ("2026-11-05T10:30:00+02:00", 422, "vor der Erfassung"),
])
def test_disclosed_at_with_offset_is_judged_in_utc(auth_client, advisor_user, session_factory, raw, status, reason):
    with time_machine.travel(FROZEN, tick=False):
        mandate_id = _seed_mandate(session_factory, advisor_user)
        conflict_id = _create_conflict(auth_client, mandate_id)
        resp = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
            json={"disclosed_at": raw},
        )
    assert resp.status_code == status, resp.text
    if reason is not None:
        # Der GRUND muss stimmen: als Text kamen diese Faelle mit dem
        # falschen Grund (Zukunft statt vor der Erfassung und umgekehrt) durch.
        assert reason in resp.json()["detail"], resp.text
    if status == 200:
        # Gespeichert wird weiterhin der erfasste Wert, unveraendert.
        assert resp.json()["disclosed_at"] == raw


def test_future_with_offset_detail_and_past_with_offset_accepted_later(
    auth_client, advisor_user, session_factory,
):
    with time_machine.travel(FROZEN, tick=False):
        mandate_id = _seed_mandate(session_factory, advisor_user)
        conflict_id = _create_conflict(auth_client, mandate_id)
        future = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
            json={"disclosed_at": "2026-11-05T09:30:00-05:00"},
        )
    assert future.status_code == 422 and "Zukunft" in future.json()["detail"]
    # Eine Stunde spaeter ist 15:00+05:00 (= 10:00Z) Vergangenheit und gleich
    # dem Erfassungszeitpunkt -- zulaessig, obwohl '15' > '11' als Text.
    with time_machine.travel(datetime(2026, 11, 5, 11, 0, 0, tzinfo=timezone.utc), tick=False):
        ok = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
            json={"disclosed_at": "2026-11-05T15:00:00+05:00"},
        )
        assert ok.status_code == 200, ok.text
        ack = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge",
            json={"acknowledged_at": "2026-11-05T15:30:00+05:00"},
        )
    assert ack.status_code == 200, ack.text


@pytest.mark.parametrize("raw", ["kein Datum", "2026-13-45T00:00:00Z", "2026-11"])
def test_unreadable_timestamp_is_refused(auth_client, advisor_user, session_factory, raw):
    with time_machine.travel(FROZEN, tick=False):
        mandate_id = _seed_mandate(session_factory, advisor_user)
        conflict_id = _create_conflict(auth_client, mandate_id)
        resp = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
            json={"disclosed_at": raw},
        )
    assert resp.status_code == 422, resp.text
    assert "kein gueltiger Zeitpunkt" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# C-867-01: Kenntnisnahme nie vor der Offenlegung
# ---------------------------------------------------------------------------

from models.review import AuditLog, ConflictOfInterestDisclosure  # noqa: E402

T_CREATE = datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc)
T_ACK_CALL = datetime(2026, 11, 5, 13, 0, 0, tzinfo=timezone.utc)


def _disclosed_conflict(auth_client, advisor_user, session_factory, disclosed_at="2026-11-05T12:00:00.000Z"):
    with time_machine.travel(T_CREATE, tick=False):
        mandate_id = _seed_mandate(session_factory, advisor_user)
        conflict_id = _create_conflict(auth_client, mandate_id)
    with time_machine.travel(T_ACK_CALL, tick=False):
        resp = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/disclose",
            json={"disclosed_at": disclosed_at},
        )
    assert resp.status_code == 200, resp.text
    return mandate_id, conflict_id


def _ack_state(session_factory, conflict_id):
    with session_factory() as db:
        row = db.query(ConflictOfInterestDisclosure).filter(
            ConflictOfInterestDisclosure.id == conflict_id,
        ).first()
        audits = db.query(AuditLog).filter(
            AuditLog.record_id == conflict_id,
            AuditLog.field_name == "client_acknowledged",
        ).count()
        return int(row.client_acknowledged or 0), row.client_acknowledged_at, audits


@pytest.mark.parametrize(("acknowledged_at", "status"), [
    # Codex-Reproducer: erstellt 10:00, offengelegt 12:00, Kenntnisnahme 11:00.
    ("2026-11-05T11:00:00.000Z", 422),
    ("2026-11-05T11:59:59.999Z", 422),
    # Exakt an der Offenlegung, auch in anderer Schreibweise/Offset.
    ("2026-11-05T12:00:00.000Z", 200),
    ("2026-11-05T12:00:00+00:00", 200),
    ("2026-11-05T13:00:00+01:00", 200),
    # Gemischte Offsets: 12:30+01:00 = 11:30Z -> vor der Offenlegung;
    # als Text ('12:30' > '12:00') waere es durchgegangen.
    ("2026-11-05T12:30:00+01:00", 422),
    # 07:30-05:00 = 12:30Z -> nach der Offenlegung (als Text '07' < '12').
    ("2026-11-05T07:30:00-05:00", 200),
    ("2026-11-05T12:00:01Z", 200),
])
def test_acknowledgement_is_never_before_disclosure(
    auth_client, advisor_user, session_factory, acknowledged_at, status,
):
    mandate_id, conflict_id = _disclosed_conflict(auth_client, advisor_user, session_factory)
    with time_machine.travel(T_ACK_CALL, tick=False):
        resp = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge",
            json={"acknowledged_at": acknowledged_at},
        )
    assert resp.status_code == status, resp.text
    acknowledged, stored_at, audits = _ack_state(session_factory, conflict_id)
    if status == 200:
        assert (acknowledged, stored_at, audits) == (1, acknowledged_at, 1)
    else:
        assert "vor der Offenlegung" in resp.json()["detail"]
        assert (acknowledged, stored_at, audits) == (0, None, 0), "keine Mutation, kein Audit"


def test_acknowledgement_with_disclosure_offset_mixed(auth_client, advisor_user, session_factory):
    # Offenlegung als 13:00+01:00 (= 12:00Z), Kenntnisnahme 11:30Z -> davor.
    mandate_id, conflict_id = _disclosed_conflict(
        auth_client, advisor_user, session_factory, disclosed_at="2026-11-05T13:00:00+01:00",
    )
    with time_machine.travel(T_ACK_CALL, tick=False):
        before = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge",
            json={"acknowledged_at": "2026-11-05T11:30:00.000Z"},
        )
        assert before.status_code == 422, before.text
        assert _ack_state(session_factory, conflict_id) == (0, None, 0)
        after = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge",
            json={"acknowledged_at": "2026-11-05T12:00:00.000Z"},
        )
    assert after.status_code == 200, after.text


def test_acknowledgement_without_timestamp_uses_server_time_after_disclosure(
    auth_client, advisor_user, session_factory,
):
    mandate_id, conflict_id = _disclosed_conflict(auth_client, advisor_user, session_factory)
    with time_machine.travel(T_ACK_CALL, tick=False):
        resp = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge", json={},
        )
    assert resp.status_code == 200, resp.text
    assert _ack_state(session_factory, conflict_id) == (1, "2026-11-05T13:00:00.000Z", 1)


@pytest.mark.parametrize("broken", [None, "", "kein Datum"])
def test_acknowledgement_fails_closed_without_readable_disclosure_time(
    auth_client, advisor_user, session_factory, broken,
):
    mandate_id, conflict_id = _disclosed_conflict(auth_client, advisor_user, session_factory)
    with session_factory() as db:
        row = db.query(ConflictOfInterestDisclosure).filter(
            ConflictOfInterestDisclosure.id == conflict_id,
        ).first()
        row.disclosed_at = broken
        db.commit()
    with time_machine.travel(T_ACK_CALL, tick=False):
        resp = auth_client.post(
            f"/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge",
            json={"acknowledged_at": "2026-11-05T12:30:00.000Z"},
        )
    assert resp.status_code == 409, resp.text
    assert "Offenlegungszeitpunkt" in resp.json()["detail"]
    assert _ack_state(session_factory, conflict_id) == (0, None, 0)
