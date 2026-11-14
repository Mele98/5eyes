"""E2 Nachtrag 2 (Pruefrunde 890982d7, N-901-01..05).

* N-901-01: Finalisierung mit einer Position, deren Nachweis nicht (mehr)
  gilt -> 409 SUSTAINABILITY_EVIDENCE_MISSING mit Audit (vorher 500, der
  Fehlerpfad las Product.name).
* N-901-02: manuelle Position ohne Nachweis ist bei aktivem Ausschluss nicht
  hinzufuegbar (409); der Beleg-Status wird immer HEUTE aus den Positionen des
  gezeigten Laufs bewertet (Protokoll, App, Kunden-PDFs, Handoff, Signatur);
  Gates und PDFs nutzen denselben Lauf-Resolver (Final vor Draft).
* N-901-04: Statuszeile nennt die Liquiditaetsausnahme.
* N-901-05: Slot-Regel der Abdeckung = Slot-Regel der Engine.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from tests.test_e2e_thierry_goessi_walkthrough import advisor_user, api, session_factory  # noqa: F401
from tests.sustainability_test_support import rc_release_preconditions  # noqa: F401 - RC-CH-1 autouse
from tests.test_sustainability_e2a_contract import _ok_capture
from tests.test_sustainability_e2b_n1_product_enforcement import (  # noqa: F401
    _non_liquid_positions, _retire, _run, _run_id, world,
)

CLAIM = "alle Produkte der Empfehlung ausser Liquidität mit belegtem Nachweis"


def _protocol_line(session_factory, mid):
    from models.mandates import Mandate
    from routers.pdf_reports import _build_protokoll_data

    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mid), s)
    return dict(data.sustainability_lines).get("Umsetzung in der Anlagestrategie") or ""


def _non_liquid_ids(session_factory):
    with session_factory() as s:
        return [r[0] for r in s.execute(text(
            "SELECT id FROM products WHERE is_active = 1 AND deleted_at IS NULL "
            "AND asset_class NOT IN ('Liquidität', 'Liquiditaet')"))]


def test_manual_unevidenced_position_is_rejected(world, api, session_factory):
    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    run_id = _run_id(_run(api, mid))
    bad = next(p for p in _non_liquid_ids(session_factory) if p not in world["evidence"])
    add = api.post(f"/mandates/{mid}/recommendations/{run_id}/positions",
                   json={"product_id": bad, "target_weight_bps": 100})
    assert add.status_code == 409, add.text
    assert add.json()["detail"]["reason_code"] == "SUSTAINABILITY_EVIDENCE_MISSING"
    assert CLAIM in _protocol_line(session_factory, mid)  # Lauf selbst bleibt belegt
    assert api.get(f"/mandates/{mid}/reports/portfolio.pdf").status_code == 200


def test_finalize_with_unevidenced_position_is_409_with_audit(world, api, session_factory):
    """Pfad aus N-901-01: Position im Lauf, Nachweis gilt nicht mehr ->
    Finalisierung 409 (nicht 500), Audit-Eintrag."""
    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    run_id = _run_id(_run(api, mid))
    shown = _non_liquid_positions(api, mid, session_factory, run_id)
    with session_factory() as s:  # nur empfehlbare Produkte (freigegebene Eignungsregel)
        governed = {r[0] for r in s.execute(text(
            "SELECT product_id FROM product_eligibility_rules WHERE status = 'approved'"))}
    extra = next(p for p in _non_liquid_ids(session_factory)
                 if p in world["evidence"] and p not in shown and p in governed)
    add = api.post(f"/mandates/{mid}/recommendations/{run_id}/positions",
                   json={"product_id": extra, "target_weight_bps": 100})
    assert add.status_code == 201, add.text
    _retire(session_factory, world["advisor_id"], world["evidence"][extra])
    assert CLAIM not in _protocol_line(session_factory, mid)
    fin = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert fin.status_code == 409, fin.text
    detail = fin.json()["detail"]
    assert detail["reason_code"] == "SUSTAINABILITY_EVIDENCE_MISSING"
    assert "Tabak" in detail["message"] and detail["detail"].startswith("Betroffen:")
    with session_factory() as s:
        audits = [json.loads(r[0]) for r in s.execute(text(
            "SELECT new_value FROM audit_log WHERE field_name = 'sustainability_floor_blocked'"))]
    assert any(a.get("event") == "sustainability_evidence_missing" and a.get("run_id") == run_id for a in audits)


def test_withdrawn_after_finalize_removes_claim_and_blocks_channels(world, api, session_factory):
    from core.reason_codes import DomainError
    from models.mandates import Mandate
    from models.review import RecommendationRun
    from services.recommendation_release_gate import assert_recommendation_release_eligible

    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    run_id = _run_id(_run(api, mid))
    assert api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize").status_code == 200
    assert CLAIM in _protocol_line(session_factory, mid)
    for pid in _non_liquid_positions(api, mid, session_factory, run_id):
        _retire(session_factory, world["advisor_id"], world["evidence"][pid])
    assert _protocol_line(session_factory, mid).startswith("Nicht eingehalten")
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert "nicht mehr belegt" in (state["allocation_stale_notice"] or "")
    for path in ("anlagestrategie.pdf", "portfolio.pdf", "cost-disclosure.pdf", "advisory-report.pdf"):
        resp = api.get(f"/mandates/{mid}/reports/{path}")
        assert resp.status_code in (409, 422), (path, resp.status_code)
    with session_factory() as s:
        for channel in ("handoff", "signature"):
            try:
                assert_recommendation_release_eligible(
                    s, s.get(Mandate, mid), channel=channel,
                    run=s.get(RecommendationRun, run_id) if channel == "handoff" else None)
            except DomainError as exc:
                assert exc.reason_code == "SUSTAINABILITY_EVIDENCE_MISSING"
            else:
                raise AssertionError(f"{channel} nicht gesperrt")


def test_gate_and_pdf_use_the_same_run_resolver(world, api, session_factory):
    """Gate-Abfrage (CURRENT_RUN_SQL) und PDF-Resolver liefern denselben Lauf:
    juengster Draft ohne Final; Final vor spaeterem Draft."""
    from models.mandates import Mandate
    from services.portfolio_engine import _current_target_allocation_or_none
    from services.recommendation_release_gate import current_run_id
    from services.recommendation_run_resolver import resolve_current_recommendation_run

    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    final_id = _run_id(_run(api, mid))
    with session_factory() as s:  # nur Drafts: juengster Draft, beide gleich
        ta = _current_target_allocation_or_none(s, mid)
        assert current_run_id(s, s.get(Mandate, mid), ta) == resolve_current_recommendation_run(s, mid, ta.id).id == final_id
    assert api.put(f"/mandates/{mid}/recommendations/{final_id}/finalize").status_code == 200
    assert _run(api, mid).status_code == 200  # neuer Draft
    with session_factory() as s:
        m = s.get(Mandate, mid)
        ta = _current_target_allocation_or_none(s, mid)
        assert current_run_id(s, m, ta) == resolve_current_recommendation_run(s, mid, ta.id).id == final_id


def test_slot_rule_is_shared_by_engine_and_coverage():
    import inspect
    from types import SimpleNamespace as P

    import services.portfolio_engine as pe
    import services.portfolio_engine_payload as payload
    import services.product_eligibility as elig

    run_src = inspect.getsource(pe.generate_recommendation_run)
    assert "slot_exact(eligible_products" in run_src and "slot_asset_fallback(eligible_products" in run_src
    assert "slot_candidates(" in inspect.getsource(payload.strategy_option_coverage)
    assert "slot_candidates(eligible_products" in inspect.getsource(elig.CustomerExclusionEvidence.raise_if_uncovered)
    products = [P(sub_asset_class="Aktien Global", asset_class="Aktien"),
                P(sub_asset_class="Immobilien Schweiz", asset_class="Immobilien")]
    assert payload.slot_candidates(products, "Aktien USA", "Aktien", pe._norm_text) == [products[0]]
    assert payload.slot_candidates(products, "Gold", "Alternative", pe._norm_text) == []
    umlaut = [P(sub_asset_class="Geldmarkt", asset_class="Liquidität")]
    assert payload.slot_candidates(umlaut, "Konto", "Liquiditaet", pe._norm_text) == umlaut


def test_exclusion_options_follow_the_running_selection(world, api, session_factory):
    """N-901-06: Bewertung gegen die laufende Auswahl, ohne zu speichern.
    Tabak auf den Alternativ-, Alkohol auf den Standardprodukten -> einzeln
    waehlbar, zusammen nicht (Grund nennt die Kombination)."""
    from tests.test_sustainability_e2b_n1_product_enforcement import _evidence

    mid = world["mid"]
    _evidence(session_factory, world["advisor_id"], sorted(world["picked"]), theme="alcohol")
    base = f"/mandates/{mid}/sustainability-preferences/exclusion-options"

    def opts(*selected):
        q = "&".join(f"selected={k}" for k in selected)
        resp = api.get(base + (f"?{q}" if q else ""))
        assert resp.status_code == 200, resp.text
        return {o["key"]: o for o in resp.json()}

    none = opts()
    assert none["tobacco"]["available"] and none["alcohol"]["available"]
    with_tobacco = opts("tobacco")
    assert with_tobacco["alcohol"]["available"] is False
    assert with_tobacco["alcohol"]["reason"].startswith("Nicht wählbar: Zusammen mit Tabak")
    with_alcohol = opts("alcohol")
    assert with_alcohol["tobacco"]["available"] is False
    assert "Zusammen mit Alkohol" in with_alcohol["tobacco"]["reason"]
    with session_factory() as s:  # nichts gespeichert
        assert s.execute(text("SELECT COUNT(*) FROM investment_preference_decisions")).scalar() == 0
    # Wechsel Tabak -> Alkohol direkt moeglich; Kombination abgelehnt.
    assert _ok_capture(api, mid, exclusions=["alcohol"])["current"]["exclusions"] == ["alcohol"]
    from tests.test_sustainability_e2a_contract import _capture

    cur = api.get(f"/mandates/{mid}/sustainability-preferences").json()["current"]["id"]
    both = _capture(api, mid, expected=cur, exclusions=["tobacco", "alcohol"])
    assert both.status_code == 422 and both.json()["detail"]["reason_code"] == "SUSTAINABILITY_OPTION_NOT_OFFERABLE"
    assert api.get(base + "?selected=weapons").status_code == 422


def test_finalized_run_losing_evidence_says_so(world, api, session_factory):
    """Text bei bereits finalisierter Empfehlung (Nachtrag 3)."""
    from core import sustainability_preference as sp

    mid = world["mid"]
    _ok_capture(api, mid, exclusions=["tobacco"])
    run_id = _run_id(_run(api, mid))
    assert api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize").status_code == 200
    for pid in _non_liquid_positions(api, mid, session_factory, run_id):
        _retire(session_factory, world["advisor_id"], world["evidence"][pid])
    expected = sp.FINAL_RUN_UNEVIDENCED_TEXT.format(labels="Tabak")
    assert expected == "Die finalisierte Empfehlung erfüllt die Ausschlüsse (Tabak) nicht mehr belegt – bitte neu berechnen."
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["allocation_stale_notice"] == expected
    pdf = api.get(f"/mandates/{mid}/reports/anlagestrategie.pdf")
    assert pdf.status_code == 409 and pdf.json()["detail"]["message"] == expected


def test_run_resolvers_break_ties_by_id(world, api, session_factory):
    """Gleicher Zeitstempel: beide Resolver waehlen den Lauf mit der hoechsten id."""
    from models.mandates import Mandate
    from services.portfolio_engine import _current_target_allocation_or_none
    from services.recommendation_release_gate import current_run_id
    from services.recommendation_run_resolver import resolve_current_recommendation_run

    mid = world["mid"]
    ids = [_run_id(_run(api, mid)) for _ in range(2)]
    with session_factory() as s:
        ta = _current_target_allocation_or_none(s, mid)
        s.execute(text("UPDATE recommendation_runs SET created_at = '2026-11-13T00:00:00.000Z' "
                       "WHERE target_allocation_id = :t AND result_status = 'Draft'"), {"t": ta.id})
        s.commit()
        drafts = [r[0] for r in s.execute(text(
            "SELECT id FROM recommendation_runs WHERE target_allocation_id = :t AND result_status = 'Draft'"),
            {"t": ta.id})]
        expected = max(drafts)
        assert set(ids) <= set(drafts)
        assert current_run_id(s, s.get(Mandate, mid), ta) == expected
        assert resolve_current_recommendation_run(s, mid, ta.id).id == expected
