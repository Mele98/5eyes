"""E2b: Uebernahme der Kundenausschluesse in die Strategiebausteine und
"nur Erfuellbares anbieten" (Fachvertrag E2b im Handoff H-151).

* Ohne qualifizierende Produkte (kein freigegebener, gueltiger Ausschluss-
  nachweis je benoetigter Sub-Anlageklasse) wird KEINE Ausschluss-Option
  angeboten, die Erfassung lehnt ab und die Engine bleibt unveraendert.
* Mit belegter Abdeckung (Quelle, Stichtag, Freigabe) ist die Option
  waehlbar; Entwurf, abgelaufen, zurueckgezogen oder nur Katalog-/Seed-Feld
  zaehlen nie (Negativfall 8).
* Wirkung nur ueber den bestehenden Restriktionsmechanismus: der Tilt
  "Ausschliessen" ist Untergrenze an allen Kanaelen; "Untergewichten",
  "Neutral" oder "Bewusst zulassen" lockern und sperren (422, kurze Meldung
  mit Detail). Abdeckung entfallen -> Finalisierung gesperrt (409).
* Restriktionen der Strategiebausteine (chfOnly, Absicherung, keine
  Strukturierten/Hebel, Themen) werden mit derselben Abdeckungspruefung
  angeboten bzw. ausgegraut.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from core import sustainability_preference as sp
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401 - pytest fixtures
    _create_client_and_mandate,
    _seed_goals,
    _seed_products,
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)
from tests.sustainability_test_support import rc_release_preconditions  # noqa: F401 - RC-CH-1 autouse
from tests.test_sustainability_e2a_contract import _capture, _ok_capture, _results


@pytest.fixture()
def scenario(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    _seed_risk_profile(api, mandate_id)
    _seed_products(api, advisor_user)
    # Strategie + Produktlauf: legt den Standard-Produktkatalog (empfehlbare
    # Produkte mit freigegebenen Eignungsregeln) an; ohne ihn ist nichts belegbar.
    assert api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={}).status_code in (200, 201)
    assert api.post(f"/mandates/{mandate_id}/recommendations/generate", json={}).status_code == 200
    return {"client_id": client_id, "mandate_id": mandate_id, "advisor_id": advisor_user.id}


def _coverage(api, mid) -> dict:
    resp = api.get(f"/mandates/{mid}/strategy-option-coverage")
    assert resp.status_code == 200, resp.text
    return {o["key"]: o for o in resp.json()["options"]} | {"_needed": resp.json()["needed_sub_asset_classes"]}


def _seed_evidence(session_factory, advisor_id, mandate_id, theme, *, status="approved", days_valid=365,
                   threshold_bps=0, skip_subs=()):
    """Je benoetigter Sub-Anlageklasse EIN Produkt mit Ausschlussnachweis
    (synthetisch, Quelle Prospekt, Stichtag heute)."""
    from database import new_uuid
    from models.mandates import Mandate
    from models.product_eligibility import ProductSustainabilityAttribute
    from services.portfolio_engine_payload import (
        _coverage_needed_sub_asset_classes,
        _filter_products_by_universe,
        _tenant_visible_products_query,
    )

    today = date.today()
    now = today.isoformat() + "T00:00:00.000Z"
    ids = []
    with session_factory() as s:
        mandate = s.get(Mandate, mandate_id)
        products = _filter_products_by_universe(s, mandate, _tenant_visible_products_query(s, mandate).all())
        needed = dict(_coverage_needed_sub_asset_classes(s, mandate, products))
        skip_assets = {needed[sub] for sub in skip_subs if sub in needed}
        for product in products:  # alle Nicht-Liquiditaetsprodukte (Lauf waehlt nur empfehlbare)
            sub = str(product.sub_asset_class or "").strip()
            if str(product.asset_class or "") in ("Liquidität", "Liquiditaet") or sub in skip_subs:
                continue
            if skip_subs and str(product.asset_class or "") in skip_assets:
                continue
            row = ProductSustainabilityAttribute(
                id=new_uuid(), product_id=product.id, tenant_id=None,
                category=sp.EXCLUSION_EVIDENCE_CATEGORIES[theme], kind="exclusion_policy",
                revenue_threshold_bps=threshold_bps, source_type="prospectus",
                source_reference="Synthetischer Prospekt, Abschnitt Ausschluesse",
                as_of=(today - timedelta(days=2)).isoformat(),
                valid_until=(today + timedelta(days=days_valid)).isoformat(),
                status=status, created_by=advisor_id, created_at=now, updated_at=now,
                approved_by=advisor_id if status == "approved" else None,
                approved_at=now if status == "approved" else None,
                approval_mode="single_approver_attested" if status == "approved" else None,
            )
            s.add(row)
            ids.append(row.id)
        s.commit()
    return ids


def test_without_qualifying_products_no_exclusion_is_offered_and_engine_is_unchanged(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    _results(api, mid)
    baseline = _results(api, mid)
    coverage = _coverage(api, mid)
    assert coverage["_needed"], "Vorbedingung: benoetigte Sub-Anlageklassen"
    for theme in sp.EXCLUSION_KEYS:
        option = coverage["exclusion:" + theme]
        assert option["available"] is False
        assert option["reason"].startswith("Nicht wählbar: kein belegtes Produkt")
        assert option["missing_sub_asset_classes"] == coverage["_needed"]
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert not any(o["available"] for o in state["exclusion_options"])
    for theme in sp.EXCLUSION_KEYS:
        resp = _capture(api, mid, exclusions=[theme])
        assert resp.status_code == 422
        assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_OPTION_NOT_OFFERABLE"
    # Katalog-/Seed-Felder (theme_tags, SFDR, Rating) belegen nichts.
    with session_factory() as s:
        s.execute(text("UPDATE products SET theme_tags = '[]', sfdr_class = '9', esg_rating = 'AAA'"))
        s.commit()
    assert not _coverage(api, mid)["exclusion:tobacco"]["available"]
    with session_factory() as s:
        assert s.execute(text("SELECT COUNT(*) FROM investment_preference_decisions")).scalar() == 0
    _ok_capture(api, mid)  # Erhebung ohne Ausschluss bleibt moeglich
    after = _results(api, mid)
    assert after["allocation"] == baseline["allocation"] and after["positions"] == baseline["positions"]


@pytest.mark.parametrize("status,days_valid,threshold,offered", [
    ("approved", 365, 0, True),
    ("draft", 365, 0, False),          # Entwurf belegt nichts
    ("approved", -1, 0, False),        # abgelaufen
    ("approved", 365, 9000, False),    # Umsatzschwelle ueber dem Hausstandard
])
def test_only_approved_valid_evidence_makes_an_exclusion_offerable(
    api, scenario, session_factory, status, days_valid, threshold, offered,
):
    mid = scenario["mandate_id"]
    _seed_evidence(session_factory, scenario["advisor_id"], mid, "tobacco",
                   status=status, days_valid=days_valid, threshold_bps=threshold)
    coverage = _coverage(api, mid)
    assert coverage["exclusion:tobacco"]["available"] is offered
    assert coverage["exclusion:alcohol"]["available"] is False
    if offered:
        assert _capture(api, mid, exclusions=["tobacco"]).status_code == 201
    else:
        assert _capture(api, mid, exclusions=["tobacco"]).status_code == 422


def test_one_missing_sub_asset_class_blocks_the_option(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    needed = _coverage(api, mid)["_needed"]
    _seed_evidence(session_factory, scenario["advisor_id"], mid, "tobacco", skip_subs=(needed[0],))
    option = _coverage(api, mid)["exclusion:tobacco"]
    assert option["available"] is False and needed[0] in option["missing_sub_asset_classes"]
    assert needed[0] in option["reason"]


def _generate(api, mid, mode):
    return api.post(f"/mandates/{mid}/target-allocation/generate",
                    json={"preferences": {"tilts": {"tobacco": mode}} if mode else {}})


def test_customer_exclusion_is_a_floor_only_via_the_restriction_mechanism(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    _seed_evidence(session_factory, scenario["advisor_id"], mid, "tobacco")
    state = _ok_capture(api, mid, exclusions=["tobacco"])
    assert state["current"]["exclusions"] == ["tobacco"]
    assert state["allocation_floor_status"] == "violated"
    for mode in ("neutral", "underweight", "overweight"):
        resp = _generate(api, mid, mode)
        assert resp.status_code == 422, (mode, resp.text)
        detail = resp.json()["detail"]
        assert detail["reason_code"] == "SUSTAINABILITY_PREFERENCE_FLOOR_VIOLATED"
        assert detail["message"].count(".") <= 3 and "Strategiebausteine" in detail["message"]
        assert "Untergrenze" in detail["detail"]
    ok = _generate(api, mid, "exclude")
    assert ok.status_code in (200, 201), ok.text
    state = api.get(f"/mandates/{mid}/sustainability-preferences").json()
    assert state["allocation_floor_status"] == "ok" and state["allocation_stale_notice"] is None
    with session_factory() as s:
        audits = [json.loads(r[0]) for r in s.execute(text(
            "SELECT new_value FROM audit_log WHERE field_name = 'sustainability_floor_blocked'"
        ))]
    assert [a["channel"] for a in audits] == ["generate"] * 3


def test_strategy_before_capture_becomes_stale_and_blocks_every_channel(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    assert _generate(api, mid, "overweight").status_code in (200, 201)
    rec = api.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert rec.status_code == 200, rec.text
    run_id = rec.json()["run"]["id"] if isinstance(rec.json().get("run"), dict) else rec.json()["run_id"]
    _seed_evidence(session_factory, scenario["advisor_id"], mid, "tobacco")
    state = _ok_capture(api, mid, exclusions=["tobacco"])
    assert state["allocation_floor_status"] == "violated"
    assert "Anlagestrategie veraltet" in state["allocation_stale_notice"]
    assert api.post(f"/mandates/{mid}/recommendations/generate", json={}).status_code == 422
    assert api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize").status_code == 422
    for path in ("anlagestrategie.pdf", "portfolio.pdf", "cost-disclosure.pdf"):
        assert api.get(f"/mandates/{mid}/reports/{path}").status_code == 422, path
    assert api.get(f"/mandates/{mid}/reports/advisory-report.pdf").status_code == 422
    # Protokoll weist die Abweichung aus, keine Produktzusicherung.
    from routers.pdf_reports import _build_protokoll_data
    from models.mandates import Mandate

    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mid), s)
    lines = dict(data.sustainability_lines)
    assert lines["Umsetzung in der Anlagestrategie"].startswith("Nicht eingehalten")
    assert sp.EXCLUSION_LIMIT_TEXT not in data.sustainability_notes
    # Heilung: Ausschliessen -> Kanaele wieder offen, Protokoll mit Katalog-Satz.
    assert _generate(api, mid, "exclude").status_code in (200, 201)
    rec = api.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert rec.status_code == 200, rec.text
    with session_factory() as s:
        data = _build_protokoll_data(s.get(Mandate, mid), s)
    assert sp.EXCLUSION_LIMIT_TEXT in data.sustainability_notes
    assert dict(data.sustainability_lines)["Umsetzung in der Anlagestrategie"].startswith("Ausschlusswünsche")


def test_lapsed_coverage_blocks_finalization(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    ids = _seed_evidence(session_factory, scenario["advisor_id"], mid, "tobacco")
    _ok_capture(api, mid, exclusions=["tobacco"])
    assert _generate(api, mid, "exclude").status_code in (200, 201)
    rec = api.post(f"/mandates/{mid}/recommendations/generate", json={})
    assert rec.status_code == 200, rec.text
    run_id = rec.json()["run"]["id"] if isinstance(rec.json().get("run"), dict) else rec.json()["run_id"]
    with session_factory() as s:
        now = date.today().isoformat() + "T00:00:00.000Z"
        for evidence_id in ids:  # Nachweise zurueckgezogen (Vier-Augen-Lebenszyklus)
            s.execute(text(
                "UPDATE product_sustainability_attributes SET status = 'retired', retired_by = :u, "
                "retired_at = :now, updated_at = :now WHERE id = :id"
            ), {"u": scenario["advisor_id"], "now": now, "id": evidence_id})
        s.commit()
    resp = api.put(f"/mandates/{mid}/recommendations/{run_id}/finalize")
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    # Nachtrag 2: zuerst die Positionen des Laufs (heute nicht mehr belegt).
    assert detail["reason_code"] == "SUSTAINABILITY_EVIDENCE_MISSING"
    assert "Tabak" in detail["message"] and detail["detail"]


def test_restriction_options_follow_the_product_matcher(api, scenario, session_factory):
    mid = scenario["mandate_id"]
    coverage = _coverage(api, mid)
    for key in ("chfOnly", "hedgingRequired", "noStructured", "noLeverage", "theme:tobacco"):
        assert key in coverage
        option = coverage[key]
        assert option["available"] is (not option["missing_sub_asset_classes"])
    needed = coverage["_needed"]
    # Unbekannter Produkttyp zaehlt nie als "nicht strukturiert" (auch nicht
    # im Fallback-Slot der Anlageklasse).
    with session_factory() as s:
        asset = s.execute(text(
            "SELECT asset_class FROM products WHERE sub_asset_class = :sub LIMIT 1"
        ), {"sub": needed[0]}).scalar()
        if asset is None:
            asset = s.execute(text("SELECT asset_class FROM products LIMIT 1")).scalar()
        s.execute(text("UPDATE products SET product_type = '' WHERE asset_class = :a OR sub_asset_class = :sub"),
                  {"a": asset, "sub": needed[0]})
        s.commit()
    option = _coverage(api, mid)["noStructured"]
    assert option["available"] is False and needed[0] in option["missing_sub_asset_classes"]


def test_protocol_bound_to_a_violating_strategy_stays_unsignable_after_healing(api, scenario, session_factory):
    """N-888-09 (uebernommen): Signatur prueft den GEBUNDENEN Strategie-Inhalt,
    nicht die (geheilte) aktuelle Allokation."""
    from tests.test_sustainability_e2a_contract import _protocol_doc, _sign

    mid = scenario["mandate_id"]
    assert _generate(api, mid, "overweight").status_code in (200, 201)
    _seed_evidence(session_factory, scenario["advisor_id"], mid, "tobacco")
    _ok_capture(api, mid, exclusions=["tobacco"])
    violating = _protocol_doc(api, session_factory, mid)  # Protokoll weist Abweichung aus
    assert violating["bound_target_allocation_id"]
    assert _generate(api, mid, "exclude").status_code in (200, 201)
    resp = _sign(api, mid, violating["id"])
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason_code"] == "SUSTAINABILITY_PREFERENCE_FLOOR_VIOLATED"
    healed = _protocol_doc(api, session_factory, mid)
    assert healed["id"] != violating["id"]
    assert _sign(api, mid, healed["id"]).status_code == 200


def test_protocol_without_strategy_is_bound_to_the_capture_and_signable(api, scenario, session_factory):
    """N-888-15 (uebernommen): Erstgespraech mit Ausschluss, noch ohne Strategie."""
    from tests.test_sustainability_e2a_contract import _protocol_doc, _sign

    # Zweites Mandat ohne Strategie (Katalog existiert aus dem Szenario).
    client = api.post("/clients", json={
        "client_number": "TG-2026-002", "first_name": "Erst", "last_name": "Gespraech",
        "advisor_id": scenario["advisor_id"], "household_type": "Einzelperson",
        "birth_date": "1980-01-01", "tax_domicile": "CH", "data_classification": "synthetic",
    })
    assert client.status_code == 201, client.text
    mandate = api.post(f"/clients/{client.json()['id']}/mandates", json={
        "mandate_number": "TG-M-002", "mandate_type": "Vermögensverwaltung", "base_currency": "CHF"})
    assert mandate.status_code == 201, mandate.text
    mid = mandate.json()["id"]
    _seed_risk_profile(api, mid)  # Eignung der Produkte haengt am Risikoprofil
    _seed_evidence(session_factory, scenario["advisor_id"], mid, "tobacco")
    state = _ok_capture(api, mid, exclusions=["tobacco"])
    assert state["allocation_floor_status"] == "no_strategy"
    doc = _protocol_doc(api, session_factory, mid)
    assert doc["bound_target_allocation_id"] is None
    assert _sign(api, mid, doc["id"]).status_code == 200, state


def test_coverage_endpoint_is_mandate_and_tenant_bound(api, scenario, session_factory, advisor_user):
    from main import app
    from models.users import User
    from services.auth import get_current_user

    mid = scenario["mandate_id"]
    stranger = User(id="user-stranger-e2b", username="stranger-e2b", password_hash="h", full_name="Fremd",
                    role="advisor", is_active=1, created_at="x", updated_at="x")
    with session_factory() as s:
        s.add(User(id="user-stranger-e2b", username="stranger-e2b", password_hash="h", full_name="Fremd",
                   role="advisor", is_active=1, created_at="x", updated_at="x"))
        s.commit()
    app.dependency_overrides[get_current_user] = lambda: stranger
    try:
        resp = api.get(f"/mandates/{mid}/strategy-option-coverage")
        assert resp.status_code in (403, 404), resp.text
        assert "needed_sub_asset_classes" not in resp.text
    finally:
        app.dependency_overrides[get_current_user] = lambda: advisor_user
