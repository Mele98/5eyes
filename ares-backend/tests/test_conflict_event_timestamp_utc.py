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
