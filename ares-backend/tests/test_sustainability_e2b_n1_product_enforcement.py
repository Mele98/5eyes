"""E2b Nachtrag 1 (Owner-Vertretung 2026-11-12):

1. Durchsetzung am Produkt: ist ein Kundenausschluss erfasst, waehlt die
   Produktselektion ausserhalb der Liquiditaet NUR Produkte mit
   freigegebenem, gueltigem Ausschlussnachweis. Katalog-Zuordnung ohne
   Nachweis zaehlt nicht. Nachweis abgelaufen/zurueckgezogen -> fail-closed
   (Produktlauf, Finalisierung, Kunden-PDF) mit kurzer Meldung. Kunden-
   aussagen (App, PDF, Protokoll) behaupten die Umsetzung nur bei belegter
   Produktauswahl. Rueckname-Gegenprobe: ohne Durchsetzung waehlt die Engine
   die unbelegten Standardprodukte.
2. Pflichtfrage: Frage 1 muss vor der Finalisierung beantwortet sein
   ("Keine Angabe" zaehlt); "noch nicht beantwortet" sperrt mit
   SUSTAINABILITY_PREFERENCE_REQUIRED.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from core import sustainability_preference as sp
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401 - pytest fixtures
    _create_client_and_mandate,
    _now,
    _seed_goals,
    _seed_products,
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)
from tests.sustainability_test_support import rc_release_preconditions  # noqa: F401 - RC-CH-1 autouse
from tests.test_sustainability_e2a_contract import DECLINED, _ok_capture

def _evidence(session_factory, advisor_id, product_ids, theme="tobacco"):
    from datetime import date, timedelta

    from database import new_uuid
    from models.product_eligibility import ProductSustainabilityAttribute

    today = date.today()
    now = today.isoformat() + "T00:00:00.000Z"
    ids = {}
    with session_factory() as s:
        for pid in product_ids:
            row = ProductSustainabilityAttribute(
                id=new_uuid(), product_id=pid, tenant_id=None, category=sp.EXCLUSION_EVIDENCE_CATEGORIES[theme],
                kind="exclusion_policy", revenue_threshold_bps=0, source_type="prospectus",
                source_reference="Synthetischer Prospekt", as_of=(today - timedelta(days=1)).isoformat(),
                valid_until=(today + timedelta(days=300)).isoformat(), status="approved",
                created_by=advisor_id, created_at=now, updated_at=now, approved_by=advisor_id,
                approved_at=now, approval_mode="single_approver_attested",
            )
            s.add(row)
            ids[pid] = row.id
        s.commit()
    return ids


def _retire(session_factory, advisor_id, evidence_id):
    now = _now()
    with session_factory() as s:
        s.execute(text(
            "UPDATE product_sustainability_attributes SET status = 'retired', retired_by = :u, "
            "retired_at = :n, updated_at = :n WHERE id = :id"
        ), {"u": advisor_id, "n": now, "id": evidence_id})
        s.commit()


@pytest.fixture()
def world(api, advisor_user, session_factory):
    """Nachweise auf allen Produkten des Universums AUSSER denen, die die
    Engine ohne Ausschluss waehlt (wo es Alternativen gibt) -- so muss die
    Durchsetzung eine andere, belegte Auswahl treffen."""
    client_id, mid = _create_client_and_mandate(api, advisor_user)
    _seed_wealth(api, client_id)
    _seed_goals(api, mid)
    _seed_risk_profile(api, mid)
    _seed_products(api, advisor_user)
    assert api.post(f"/mandates/{mid}/target-allocation/generate",
                    json={"preferences": {"tilts": {"tobacco": "exclude"}}}).status_code in (200, 201)
    baseline = _run(api, mid)
    assert baseline.status_code == 200, baseline.text
    picked = set(_non_liquid_positions(api, mid, session_factory, _run_id(baseline)))
    with session_factory() as s:
        universe = [r[0] for r in s.execute(text(
            "SELECT id FROM products WHERE is_active = 1 AND deleted_at IS NULL "
            "AND asset_class NOT IN ('Liquidität', 'Liquiditaet')"
        ))]
    evidence = _evidence(session_factory, advisor_user.id, [pid for pid in universe if pid not in picked])
    coverage = {o["key"]: o for o in api.get(f"/mandates/{mid}/strategy-option-coverage").json()["options"]}
    if not coverage["exclusion:tobacco"]["available"]:
        # Slots ohne Alternative: dort ist das gewaehlte Produkt selbst belegt.
        with session_factory() as s:
            subs = set(coverage["exclusion:tobacco"]["missing_sub_asset_classes"])
            extra = [r[0] for r in s.execute(text("SELECT id, sub_asset_class FROM products")) if r[1] in subs and r[0] in picked]
        evidence.update(_evidence(session_factory, advisor_user.id, extra))
    return {"mid": mid, "picked": picked, "evidence": evidence, "advisor_id": advisor_user.id}


def _run(api, mid):
    resp = api.post(f"/mandates/{mid}/recommendations/generate", json={})
    return resp


def _non_liquid_positions(api, mid, session_factory, run_id):
    with session_factory() as s:
        return {r[0]: r[1] for r in s.execute(text(
            "SELECT p.id, p.product_name FROM recommendation_positions rp JOIN products p ON p.id = rp.product_id "
            "WHERE rp.run_id = :r AND p.asset_class NOT IN ('Liquidität', 'Liquiditaet')"
        ), {"r": run_id})}


def _run_id(resp):
    body = resp.json()
    return body["run"]["id"] if isinstance(body.get("run"), dict) else body["run_id"]


def test_tobacco_exclusion_selects_only_evidenced_products_and_counterprobe(world, api, session_factory, monkeypatch):
    mid = world["mid"]
    state = _ok_capture(api, mid, exclusions=["tobacco"])
    assert state["allocation_floor_status"] == "ok"
    resp = _run(api, mid)
    assert resp.status_code == 200, resp.text
    run_id = _run_id(resp)
    positions = _non_liquid_positions(api, mid, session_factory, run_id)
    assert positions and set(positions) <= set(world["evidence"]), positions
    assert set(positions) != world["picked"], "Durchsetzung muss eine andere, belegte Auswahl treffen"
    with session_factory() as s:
        snap = s.execute(text("SELECT sustainability_evidence_json FROM recommendation_runs WHERE id = :r"),
                         {"r": run_id}).scalar()
    assert '"complete": true' in snap and state["current"]["decision_hash"] in snap
    # Kundenaussage: belegt -> "eingehalten" + Regeltext.
    from models.mandates import Mandate
    from routers.pdf_reports import _build_protokoll_data

    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mid), s)
    assert "alle Produkte der Empfehlung ausser Liquidität mit belegtem Nachweis" in dict(data.sustainability_lines)[
        "Umsetzung in der Anlagestrategie"]
    assert sp.EXCLUSION_LIMIT_TEXT in data.sustainability_notes
    assert api.get(f"/mandates/{mid}/reports/anlagestrategie.pdf").status_code == 200
    # Gegenprobe: Durchsetzung zurueckgenommen -> Engine nimmt Standardprodukte,
    # und keine Kundenaussage behauptet die Umsetzung.
    import services.product_eligibility as pe_mod

    monkeypatch.setattr(pe_mod, "customer_exclusion_evidence", lambda db, mandate, as_of=None: None)
    resp = _run(api, mid)
    assert resp.status_code == 200, resp.text
    positions = _non_liquid_positions(api, mid, session_factory, _run_id(resp))
    assert set(positions) == world["picked"], "Gegenprobe: ohne Durchsetzung die Standardauswahl"
    monkeypatch.undo()  # Bewertung der Kundenaussagen wieder mit echter (Live-)Pruefung
    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mid), s)
    assert dict(data.sustainability_lines)["Umsetzung in der Anlagestrategie"].startswith("Nicht eingehalten")
    assert sp.EXCLUSION_LIMIT_TEXT not in data.sustainability_notes
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert "nicht belegt" in (state["allocation_stale_notice"] or "")
    assert sp.EXCLUSION_LIMIT_TEXT not in state["current"]["limit_texts"]
    blocked = api.get(f"/mandates/{mid}/reports/anlagestrategie.pdf")
    assert blocked.status_code == 409 and blocked.json()["detail"]["reason_code"] == "SUSTAINABILITY_EVIDENCE_MISSING"


def test_expired_evidence_blocks_finalization_and_new_selection(world, api, session_factory):
    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    resp = _run(api, mid)
    assert resp.status_code == 200, resp.text
    run_id = _run_id(resp)
    positions = _non_liquid_positions(api, mid, session_factory, run_id)
    for pid in positions:  # alle Nachweise der gewaehlten Produkte zurueckgezogen
        _retire(session_factory, world["advisor_id"], world["evidence"][pid])
    fin = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert fin.status_code == 409, fin.text
    detail = fin.json()["detail"]
    assert detail["reason_code"] == "SUSTAINABILITY_EVIDENCE_MISSING"
    assert "Tabak" in detail["message"] and detail["detail"]
    again = _run(api, mid)
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["reason_code"] == "SUSTAINABILITY_EVIDENCE_MISSING"
    assert len(again.json()["detail"]["message"]) < 220


def test_finalize_requires_question_one_answered(api, advisor_user, session_factory):
    client_id, mid = _create_client_and_mandate(api, advisor_user)
    _seed_wealth(api, client_id)
    _seed_risk_profile(api, mid)
    _seed_products(api, advisor_user)
    assert api.post(f"/mandates/{mid}/target-allocation/generate", json={}).status_code in (200, 201)
    run_id = _run_id(_run(api, mid))
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["state"] == "unanswered" and sp.REQUIRED_ANSWER_TEXT in state["state_notice"]
    fin = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert fin.status_code == 409, fin.text
    assert fin.json()["detail"]["reason_code"] == "SUSTAINABILITY_PREFERENCE_REQUIRED"
    assert sp.REQUIRED_ANSWER_TEXT in fin.json()["detail"]["message"]
    with session_factory() as s:
        assert s.execute(text("SELECT COUNT(*) FROM investment_preference_decisions")).scalar() == 0
    _ok_capture(api, mid, **DECLINED)  # "Keine Angabe" zaehlt als beantwortet
    assert api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize").status_code == 200
