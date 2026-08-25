"""Sprint U-19 (Roadmap-Punkt 19): Tests fuer den Aggregator-Cache.

Strategie
---------
- Unit-Tests fuer den TTL+LRU-Cache (Hit, Miss, TTL-Expiry, LRU-Eviction,
  Invalidation)
- Integration-Test: verifiziert dass compute_advisory_report() bei
  Cache-Hit NICHT erneut aufgerufen wird (per spy/patch)
- End-to-End: GET /advisory-report doppelt -> 2. Aufruf liefert
  identische Bytes ohne DB-Round-Trip
- PUT report-notes invalidiert den Cache -> naechstes GET liefert
  frischen Wert
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from services.advisory_report_cache import (
    cached_compute_advisory_report,
    clear_all,
    get_cache_stats,
    invalidate_mandate,
    reset_for_tests,
    _TTLCache,
)
from services.auth import get_current_user


_NOW = "2026-05-31T08:00:00.000Z"


@pytest.fixture(autouse=True)
def reset_cache():
    """Frischer Cache pro Test — Settings-Drift-Schutz."""
    reset_for_tests()
    yield
    reset_for_tests()


# ---------------------------------------------------------------------------
# _TTLCache Unit-Tests
# ---------------------------------------------------------------------------

def test_ttl_cache_basic_hit_miss():
    c = _TTLCache(ttl_seconds=10, max_size=100)
    assert c.get("k1") is None
    assert c.stats.misses == 1
    c.set("k1", "v1")
    assert c.get("k1") == "v1"
    assert c.stats.hits == 1


def test_ttl_cache_expires_after_ttl():
    c = _TTLCache(ttl_seconds=0.05, max_size=100)
    c.set("k1", "v1")
    assert c.get("k1") == "v1"
    time.sleep(0.08)
    assert c.get("k1") is None  # TTL abgelaufen
    assert c.stats.hits == 1
    assert c.stats.misses == 1


def test_ttl_cache_lru_evicts_oldest_when_full():
    c = _TTLCache(ttl_seconds=10, max_size=3)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    # Touch "a" -> es ist nicht mehr das aelteste
    c.get("a")
    c.set("d", 4)  # forciert Eviction von "b" (jetzt aeltestes)
    assert c.get("a") == 1
    assert c.get("b") is None  # evicted
    assert c.get("c") == 3
    assert c.get("d") == 4
    assert c.stats.evictions == 1


def test_ttl_cache_invalidate_single_key():
    c = _TTLCache(ttl_seconds=10, max_size=10)
    c.set("k1", "v1")
    assert c.invalidate("k1") is True
    assert c.get("k1") is None
    assert c.stats.invalidations == 1
    # Doppelte Invalidation = False
    assert c.invalidate("k1") is False


def test_ttl_cache_invalidate_prefix():
    c = _TTLCache(ttl_seconds=10, max_size=10)
    c.set(("M1", "adv1"), "v1")
    c.set(("M1", "adv2"), "v2")
    c.set(("M2", "adv1"), "v3")
    removed = c.invalidate_prefix(lambda key: key[0] == "M1")
    assert removed == 2
    assert c.get(("M1", "adv1")) is None
    assert c.get(("M1", "adv2")) is None
    assert c.get(("M2", "adv1")) == "v3"


# ---------------------------------------------------------------------------
# cached_compute_advisory_report
# ---------------------------------------------------------------------------

@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cache.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def seeded(session_factory):
    with session_factory() as s:
        advisor = User(
            id=str(uuid.uuid4()),
            username=f"adv-{uuid.uuid4().hex[:6]}",
            password_hash="h",
            full_name="Anna",
            role="advisor",
            is_active=1,
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(advisor)
        client = Client(
            id=str(uuid.uuid4()),
            client_number=f"C-{uuid.uuid4().hex[:6]}",
            first_name="Hans",
            last_name="Muster",
            advisor_id=advisor.id,
            country_of_residence="CH",
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(client)
        mandate = Mandate(
            id=str(uuid.uuid4()),
            client_id=client.id,
            mandate_number=f"M-{uuid.uuid4().hex[:6]}",
            mandate_type="Anlageberatung",
            opened_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(mandate)
        s.commit()
        return {
            "mandate_id": mandate.id,
            "client_id": client.id,
            "advisor_id": advisor.id,
            "advisor_full_name": advisor.full_name,
        }


def test_cached_compute_returns_cache_on_second_call(session_factory, seeded):
    """Zweiter Aufruf darf compute_advisory_report nicht erneut aufrufen."""
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == seeded["mandate_id"]).first()
        advisor = s.query(User).filter(User.id == seeded["advisor_id"]).first()
        with patch(
            "services.advisory_report_cache.compute_advisory_report",
            wraps=__import__("services.advisory_report", fromlist=["compute_advisory_report"]).compute_advisory_report,
        ) as spy:
            first = cached_compute_advisory_report(s, mandate, advisor=advisor)
            second = cached_compute_advisory_report(s, mandate, advisor=advisor)

    assert spy.call_count == 1, "2. Aufruf muss aus Cache kommen"
    assert first == second
    stats = get_cache_stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1


def test_invalidate_mandate_forces_fresh_compute(session_factory, seeded):
    """Nach invalidate() muss der naechste Aufruf wieder compute() rufen."""
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == seeded["mandate_id"]).first()
        advisor = s.query(User).filter(User.id == seeded["advisor_id"]).first()
        with patch(
            "services.advisory_report_cache.compute_advisory_report",
            wraps=__import__("services.advisory_report", fromlist=["compute_advisory_report"]).compute_advisory_report,
        ) as spy:
            cached_compute_advisory_report(s, mandate, advisor=advisor)
            invalidate_mandate(seeded["mandate_id"])
            cached_compute_advisory_report(s, mandate, advisor=advisor)

    assert spy.call_count == 2


def test_invalidate_mandate_clears_all_advisor_views(session_factory, seeded):
    """invalidate_mandate(mid) muss Eintraege fuer ALLE Berater entfernen."""
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == seeded["mandate_id"]).first()
        advisor = s.query(User).filter(User.id == seeded["advisor_id"]).first()
        # Zweiter Pseudo-Advisor
        other_advisor = SimpleNamespace(id="other-uuid", full_name="Bob")
        cached_compute_advisory_report(s, mandate, advisor=advisor)
        cached_compute_advisory_report(s, mandate, advisor=other_advisor)
        stats_before = get_cache_stats()
        assert stats_before["current_size"] >= 2

        removed = invalidate_mandate(seeded["mandate_id"])
        assert removed >= 2
        stats_after = get_cache_stats()
        assert stats_after["current_size"] == 0


def test_cache_can_be_disabled_via_setting(session_factory, seeded, monkeypatch):
    """Wenn aggregator_cache_enabled=False -> kein Caching, jeder Call
    geht durch."""
    from config import settings
    monkeypatch.setattr(settings, "aggregator_cache_enabled", False)
    reset_for_tests()

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == seeded["mandate_id"]).first()
        advisor = s.query(User).filter(User.id == seeded["advisor_id"]).first()
        with patch(
            "services.advisory_report_cache.compute_advisory_report",
            wraps=__import__("services.advisory_report", fromlist=["compute_advisory_report"]).compute_advisory_report,
        ) as spy:
            cached_compute_advisory_report(s, mandate, advisor=advisor)
            cached_compute_advisory_report(s, mandate, advisor=advisor)

    assert spy.call_count == 2


# ---------------------------------------------------------------------------
# End-to-End via HTTP-Endpoint
# ---------------------------------------------------------------------------

@pytest.fixture()
def http_client(session_factory, seeded):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    current = SimpleNamespace(
        id=seeded["advisor_id"],
        full_name=seeded["advisor_full_name"],
        username="adv",
        email="adv@test.local",
        role="advisor",
        is_active=1,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    try:
        with TestClient(app) as client:
            yield client, seeded
    finally:
        app.dependency_overrides.clear()


def test_http_advisory_report_second_call_is_cache_hit(http_client):
    """GET /advisory-report 2x — beim 2. Mal greift der Cache. Wir
    verifizieren das ueber hits-Counter in cache_stats."""
    client, seeded = http_client
    mid = seeded["mandate_id"]

    r1 = client.get(f"/mandates/{mid}/advisory-report")
    r2 = client.get(f"/mandates/{mid}/advisory-report")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    stats = get_cache_stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1


def test_put_report_notes_invalidates_cache(http_client):
    """U-19 + U-P28: PUT report-notes loescht den Cache-Eintrag, sodass
    das naechste GET den frischen Override sieht."""
    client, seeded = http_client
    mid = seeded["mandate_id"]

    # 1. Aufruf befuellt Cache
    r0 = client.get(f"/mandates/{mid}/advisory-report")
    initial_anm = r0.json()["asset_allocation"]["anmerkungen"]

    # PUT setzt Override
    custom = "OVERRIDE-NACH-PUT"
    put = client.put(f"/mandates/{mid}/report-notes", json={
        "aa_anmerkungen": custom,
    })
    assert put.status_code == 200

    # Naechster GET muss den NEUEN Wert sehen — nicht den gecachten alten
    r2 = client.get(f"/mandates/{mid}/advisory-report")
    assert r2.json()["asset_allocation"]["anmerkungen"] == custom
    assert r2.json()["asset_allocation"]["anmerkungen"] != initial_anm


def test_post_advisory_log_invalidates_cache(http_client):
    """POST advisory-log loescht den Cache; beratungsprotokoll-Sektion
    zeigt den neuen Eintrag sofort."""
    client, seeded = http_client
    mid = seeded["mandate_id"]

    r0 = client.get(f"/mandates/{mid}/advisory-report")
    assert r0.json()["beratungsprotokoll"]["total_active"] == 0

    post = client.post(f"/mandates/{mid}/advisory-log", json={
        "entry_type": "Sonstiges",
        "title": "Cache-Invalidation-Test",
        "description": "x" * 35,
        "entry_datetime": "2026-05-31T10:00:00Z",
        "duration_minutes": 5,
        "communication_channel": "telefon",
        "topics": ["Allgemein"],
        "risk_warnings_given": [],
        "cost_disclosure_given": False,
        "status": "Empfohlen",
    })
    assert post.status_code == 201

    r2 = client.get(f"/mandates/{mid}/advisory-report")
    assert r2.json()["beratungsprotokoll"]["total_active"] == 1
    assert r2.json()["beratungsprotokoll"]["latest_entry"]["title"] == "Cache-Invalidation-Test"


def test_cache_stats_endpoint_helper_exposes_health_metrics():
    """get_cache_stats() liefert ein normalisiertes dict mit allen
    Diagnose-Keys."""
    stats = get_cache_stats()
    expected_keys = {
        "enabled", "ttl_seconds", "max_size", "current_size",
        "hits", "misses", "hit_rate", "invalidations", "evictions",
        "last_invalidation_at",
    }
    assert set(stats.keys()) == expected_keys
    assert isinstance(stats["enabled"], bool)
    assert isinstance(stats["hit_rate"], float)
    assert 0.0 <= stats["hit_rate"] <= 1.0
