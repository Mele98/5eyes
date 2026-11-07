"""N-888-01..06 (Pruefrunde ESG @ 99784e5a, Dok. 86): Untergrenze an ALLEN Wegen.

Regression exakt nach dem Ablauf des Pruefers (echte Engine, Seed-Katalog):

1. Soll-Allokation VOR der Erfassung mit ``tobacco=overweight`` (+ Lauf mit
   Themenprodukt Tabak, Positivkontrolle).
2. Kunde erfasst Ausschluss Tabak -> Allokation gilt als veraltet
   (``allocation_floor_status=violated``, Hinweis).
3. ``POST /recommendations/generate`` -> 422 statt 200.
4. ``PUT .../finalize`` des alten Laufs -> 422 statt 200.
5. Manuelles ``POST /target-allocation`` (erbt ``overweight``) -> 422 statt 201.
6. Protokoll-PDF: KEIN "werden bei der Produktauswahl nicht verwendet",
   sondern die Abweichung.
Jeder Block hinterlaesst einen Audit-Eintrag. Danach Heilung: Allokation mit
"Ausschliessen" neu -> Produktlauf ohne Themenprodukt Tabak, Protokoll mit dem
Katalog-Satz.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from database import Base, get_db  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401

configure_mappers()

import services.portfolio_engine as pe  # noqa: E402
from core import sustainability_preference as sp  # noqa: E402
from main import app  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import Product, RecommendationPosition  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from test_optimizer_integration import _seed_realistic_mandate  # noqa: E402
from tests.test_sustainability_preferences_e1 import _payload  # noqa: E402

FLOOR = "SUSTAINABILITY_PREFERENCE_FLOOR_VIOLATED"
TOBACCO_SUB = "Thema Tabak"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    import routers.allocation as allocation_router
    import routers.review as review_router

    for module in (allocation_router, review_router):
        monkeypatch.setattr(module.settings, "require_suitability_before_recommendation", False)
    engine = create_engine(f"sqlite:///{tmp_path / 'floor.db'}", connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(SF, "floor")
    with SF() as s:
        pe.ensure_default_products(s, jurisdiction="CH")
        pe.ensure_hedged_product_variants(s)
        advisor = s.get(User, advisor_id)
        s.commit()

    def override_db():
        with SF() as session:
            yield session

    from tests.test_risk_questionnaire_integrity import noop_lifespan

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor
    with TestClient(app) as tc:
        yield {"SF": SF, "client": tc, "mandate_id": mandate_id, "advisor_id": advisor_id}
    app.dependency_overrides.clear()
    engine.dispose()


def _generate_ta(world, tilts) -> str:
    with world["SF"]() as s:
        mandate = s.get(Mandate, world["mandate_id"])
        result = pe.generate_target_allocation(s, mandate, world["advisor_id"], {"tilts": tilts})
        s.commit()
        return result["target_allocation"].id


def _run_with_positions(world) -> tuple[str, set[str]]:
    with world["SF"]() as s:
        mandate = s.get(Mandate, world["mandate_id"])
        result = pe.generate_recommendation_run(s, mandate, world["advisor_id"], None)
        s.commit()
        run_id = result["run"].id
        subs = {
            str(s.get(Product, pos.product_id).sub_asset_class or "")
            for pos in s.query(RecommendationPosition).filter(RecommendationPosition.run_id == run_id)
        }
    return run_id, subs


def _floor_audits(world) -> list[dict]:
    with world["SF"]() as s:
        rows = s.execute(text(
            "SELECT new_value FROM audit_log WHERE field_name = 'sustainability_floor_blocked' "
            "ORDER BY created_at"
        )).all()
    return [json.loads(r[0]) for r in rows]


def _protocol_notes(world) -> tuple:
    from routers.pdf_reports import _build_protokoll_data

    with world["SF"]() as s:
        data = _build_protokoll_data(s.get(Mandate, world["mandate_id"]), s)
    return data.sustainability_notes, dict(data.sustainability_lines)


def _manual_body(world) -> dict:
    with world["SF"]() as s:
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == world["mandate_id"], TargetAllocation.is_current == 1,
        ).one()
        body = {"policy_id": ta.policy_id, "based_on_assessment_id": ta.based_on_assessment_id,
                "override_reason": "Manuelle Anpassung nach Kundengespraech zur Liquiditaetsreserve.",
                "expected_current_allocation_id": ta.id,
                "expected_current_allocation_version": ta.version}
        for bucket in pe.BUCKET_FIELDS:
            body[f"target_{bucket}_bps"] = int(getattr(ta, f"target_{bucket}_bps"))
            body[f"band_{bucket}_min_bps"] = int(getattr(ta, f"band_{bucket}_min_bps"))
            body[f"band_{bucket}_max_bps"] = int(getattr(ta, f"band_{bucket}_max_bps"))
    return body


def test_reviewer_flow_is_blocked_on_every_path_and_protocol_states_deviation(world):
    client, mid = world["client"], world["mandate_id"]
    # 1. Allokation + Lauf VOR der Erfassung, Positivkontrolle Themenprodukt Tabak.
    _generate_ta(world, {"tobacco": "overweight"})
    run_id, subs = _run_with_positions(world)
    assert TOBACCO_SUB in subs, subs
    # 2. Ausschluss Tabak erfassen -> Allokation veraltet (Hinweis).
    resp = client.post(f"/mandates/{mid}/sustainability-preferences", json=_payload(exclusions=["tobacco"]))
    assert resp.status_code == 201, resp.text
    state = resp.json()
    assert state["allocation_floor_status"] == "violated"
    assert state["allocation_floor_themes"] == ["tobacco"]
    assert "Tabak" in state["allocation_stale_notice"]
    assert sp.EXCLUSION_LIMIT_TEXT not in state["current"]["limit_texts"]
    # 3. Produktlauf auf der bestehenden Allokation.
    resp = client.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason_code"] == FLOOR
    assert resp.json()["detail"]["channel"] == "recommendation"
    # 4. Finalize des alten Laufs.
    resp = client.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason_code"] == FLOOR
    # 5. Manuelles POST erbt overweight.
    resp = client.post(f"/mandates/{mid}/target-allocation", json=_manual_body(world))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason_code"] == FLOOR
    # 5b. Generate mit gelockertem Tilt (Pruefer: mit Risikoprofil).
    resp = client.post(f"/mandates/{mid}/target-allocation/generate",
                       json={"preferences": {"tilts": {"tobacco": "neutral"}}})
    assert resp.status_code == 422 and resp.json()["detail"]["reason_code"] == FLOOR
    # Audit je Block.
    channels = [a["channel"] for a in _floor_audits(world)]
    assert channels == ["recommendation", "finalize", "manual_allocation", "generate"]
    assert all(a["themes"] == ["tobacco"] for a in _floor_audits(world))
    # 6. Protokoll: keine Produktzusicherung, sondern Abweichung.
    notes, lines = _protocol_notes(world)
    flat = " ".join(notes)
    assert sp.EXCLUSION_LIMIT_TEXT not in flat
    assert "berücksichtigt die Ausschlusswünsche (Tabak) noch nicht" in flat
    assert lines["Umsetzung in der Anlagestrategie"].startswith("Nicht eingehalten")

    # Heilung: Allokation mit Ausschliessen -> Lauf ohne Themenprodukt Tabak.
    _generate_ta(world, {"tobacco": "exclude"})
    resp = client.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert resp.status_code == 200, resp.text
    with world["SF"]() as s:
        healed = {
            str(s.get(Product, p["product_id"]).sub_asset_class or "") for p in resp.json()["positions"]
        }
    assert TOBACCO_SUB not in healed
    notes, lines = _protocol_notes(world)
    assert sp.EXCLUSION_LIMIT_TEXT in " ".join(notes)
    assert lines["Umsetzung in der Anlagestrategie"].startswith("Ausschlusswünsche in der aktuellen")
    state = client.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["allocation_floor_status"] == "ok" and state["allocation_stale_notice"] is None


def test_release_channels_block_via_central_gate(world):
    from core.reason_codes import DomainError
    from services.recommendation_release_gate import (
        CHANNEL_ADVISORY_PDF, CHANNEL_HANDOFF, CHANNEL_SIGNATURE, assert_recommendation_release_eligible,
    )

    _generate_ta(world, {"tobacco": "overweight"})
    run_id, _ = _run_with_positions(world)
    assert world["client"].post(
        f"/mandates/{world['mandate_id']}/sustainability-preferences", json=_payload(exclusions=["tobacco"]),
    ).status_code == 201
    from models.review import RecommendationRun

    with world["SF"]() as s:
        mandate = s.get(Mandate, world["mandate_id"])
        run = s.get(RecommendationRun, run_id)
        seen = []
        for channel, kwargs in ((CHANNEL_ADVISORY_PDF, {}), (CHANNEL_SIGNATURE, {}), (CHANNEL_HANDOFF, {"run": run})):
            with pytest.raises(DomainError) as exc:
                assert_recommendation_release_eligible(
                    s, mandate, channel=channel, audit=lambda payload, result: seen.append(payload), **kwargs,
                )
            assert exc.value.reason_code == FLOOR and exc.value.http_status == 422
        assert [json.loads(p)["channel"] for p in seen] == [CHANNEL_ADVISORY_PDF, CHANNEL_SIGNATURE, CHANNEL_HANDOFF]


def test_waiver_loses_effect_when_mandate_becomes_discretionary(world):
    client, mid = world["client"], world["mandate_id"]
    _generate_ta(world, {"tobacco": "overweight"})
    reason = "Kunde akzeptiert Tabak im Themenfonds nach Besprechung der Alternativen."
    resp = client.post(f"/mandates/{mid}/sustainability-preferences",
                       json=_payload(exclusions=["tobacco"], waivers={"tobacco": reason}))
    assert resp.status_code == 201, resp.text
    assert resp.json()["allocation_floor_status"] == "none"  # Verzicht wirkt (Anlageberatung)
    with world["SF"]() as s:
        s.execute(text("UPDATE mandates SET mandate_type = 'Vermögensverwaltung' WHERE id = :id"), {"id": mid})
        s.commit()
    state = client.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["waiver_void"] is True and state["waiver_void_notice"] == sp.WAIVER_VOID_TEXT
    assert state["allocation_floor_status"] == "violated"
    resp = client.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert resp.status_code == 422 and resp.json()["detail"]["reason_code"] == FLOOR
    notes, lines = _protocol_notes(world)
    assert sp.WAIVER_VOID_TEXT in notes
    assert "unwirksam" in lines["Kundenverzicht"]


def test_suitability_audit_and_review_trigger_show_preference_status(world, monkeypatch):
    from services.suitability_audit import audit_mandate_suitability, suitability_gate_blocks
    import services.review_engine as review_engine

    with world["SF"]() as s:
        mandate = s.get(Mandate, world["mandate_id"])
        audit = audit_mandate_suitability(s, mandate)
    assert audit["sustainability_preference"]["status"] == "missing"
    assert "nicht erfasst" in audit["sustainability_preference"]["notice"]
    assert world["client"].post(
        f"/mandates/{world['mandate_id']}/sustainability-preferences", json=_payload(exclusions=[]),
    ).status_code == 201
    with world["SF"]() as s:
        mandate = s.get(Mandate, world["mandate_id"])
        before = audit_mandate_suitability(s, mandate)
        assert before["sustainability_preference"] == {"status": "current", "notice": None}
        monkeypatch.setattr(review_engine, "_today", lambda: "2999-01-01")
        review_engine._refresh_sustainability_trigger(s, mandate, now="2999-01-01T00:00:00Z", today="2999-01-01")
        trigger = review_engine._get_system_trigger(
            s, mandate.id, "Ereignis", review_engine.SYSTEM_TRIGGER_SUSTAINABILITY,
        )
        assert trigger is not None and trigger.status == "Ausgelöst"
        assert "Eignungsprüfung fällig" in trigger.triggered_notes
        review_engine._refresh_sustainability_trigger(s, mandate, now="2026-11-08T00:00:00Z", today="2026-11-08")
        assert trigger.status == "Erledigt"
    # Hinweis aendert das Eignungs-Gate nicht (kein stilles Sperren).
    assert suitability_gate_blocks(before, creates_target_allocation=True) == suitability_gate_blocks(
        {**before, "sustainability_preference": {"status": "due", "notice": "x"}}, creates_target_allocation=True,
    )


def test_recommendation_run_warns_when_preference_missing(world):
    _generate_ta(world, {})
    resp = world["client"].post(f"/mandates/{world['mandate_id']}/recommendations/generate", json={})
    assert resp.status_code == 200, resp.text
    assert any("Nachhaltigkeitspräferenz nicht erfasst" in w for w in resp.json()["warnings"])


def test_protocol_claim_guard_blocks_at_runtime(world, monkeypatch):
    assert world["client"].post(
        f"/mandates/{world['mandate_id']}/sustainability-preferences", json=_payload(exclusions=[]),
    ).status_code == 201
    from core.reason_codes import DomainError

    monkeypatch.setitem(sp.PROFILE_TEXTS, sp.PROFILE_ESG_FACTORS, "Ihr Portfolio ist nachhaltig.")
    with pytest.raises(DomainError) as exc:
        _protocol_notes(world)
    assert exc.value.reason_code == "SUSTAINABILITY_CLAIM_TEXT_BLOCKED"
