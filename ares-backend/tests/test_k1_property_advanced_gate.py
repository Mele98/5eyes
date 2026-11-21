"""K1 Property-Gate (Codex-Entscheid 2026-11-19, Dok. 116 PROP-1/2/5).

Belegt:

1. API: deaktivierte Funktionen enden mit 409 ``PROPERTY_ADVANCED_FEATURE_DISABLED``
   (Collateral-Flag auf illiquiden Werten, Verwertungsmethode, Amortisations-
   betrag, Immobilien-Wertsteigerung); "Gemischt" fuer neue Hypotheken 422
   ``MORTGAGE_TYPE_MIXED_REJECTED``, unveraenderter Altbestand speicherbar.
2. CH-Normalfall Eigenheim + Hypothek bleibt voll erfassbar; Brutto/
   Verbindlichkeiten/Netto ohne Doppelzaehlung.
3. Keine stille Luecke und keine Doppelzaehlung: die Automatik leitet keinen
   Hypothekarzins und keine Amortisation mehr ab; der manuell erfasste
   Ausgaben-Cashflow ist erlaubt und zaehlt genau einmal.
4. Engine: keine Collateral-Anrechnung der Immobilie, keine Wertsteigerung,
   keine Amortisations-/Refinanzierungsprojektion.
5. Migration: Altwerte neutralisiert, Owner-Review-Fall je Position,
   idempotent; Alembic-Kette und Spaltenparitaet ORM = Bootstrap = Laufzeit =
   Alembic.
6. PROP-5: Duplikat-Schutz auch im Positions-Update.

Alle Werte sind synthetische Testvektoren.
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

import core.property_gate as gate
from database import neutralize_legacy_property_values
from services import portfolio_engine as pe
from services.wealth_cashflows import (
    derive_wealth_cashflows,
    mortgage_amortization_adjustment_series,
    mortgage_interest_adjustment_series,
)
from tests.h10_support import alembic_cfg
from tests.property_gate_support import property_advanced_mechanics_enabled  # noqa: F401
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    advisor_user,
    api,
    session_factory,
)
from tests.test_g7_full_api_path_parity import _create_client_and_mandate

K1_REV = "63332bb56098"
P4_REV = "24e7606245d3"
# Integration H12+K1: K1 haengt hinter H12 (Schluesselversion), H12 hinter P4.
K1_DOWN_REV = "b3f1c9d2e4a7"

HOME = {
    "label": "Synthetic home", "position_type": "Immobilien", "assignment": "Anderes Vermögen",
    "current_value_rappen": 1_200_000_00, "currency": "CHF", "valuation_date": "2026-11-18",
    "asset_valuation_method": "Fachgutachten", "property_usage": "Selbstgenutzt",
    "data_classification": "synthetic",
}


def _mortgage(linked_id=None, **extra):
    row = {
        "label": "Synthetic mortgage", "position_type": "Hypothek", "assignment": "Verbindlichkeit",
        "current_value_rappen": 600_000_00, "currency": "CHF", "mortgage_type": "Festhypothek",
        "mortgage_interest_rate_bps": 140, "mortgage_maturity_date": "2032-03-31",
        "mortgage_amortization_type": "Indirekt (Säule 3a)", "data_classification": "synthetic",
    }
    if linked_id:
        row["mortgage_linked_property_id"] = linked_id
    row.update(extra)
    return row


def _code(resp):
    body = resp.json()
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail.get("reason_code") if isinstance(detail, dict) else None


def _client(api, advisor_user):
    client_id, _mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    return client_id


# ── 1. API-Sperren ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("extra,feature", [
    ({"is_available_for_goal_funding": True}, "goal_funding_collateral"),
    ({"goal_funding_method": "Belehnung"}, "goal_funding_method"),
    ({"goal_funding_method": "Verkauf"}, "goal_funding_method"),
    ({"goal_funding_method": "Automatisch"}, "goal_funding_method"),
    ({"asset_expected_return_bps": 150}, "property_return_input"),
])
def test_property_advanced_writes_are_rejected_typed(api, advisor_user, extra, feature):
    client_id = _client(api, advisor_user)
    resp = api.post(f"/clients/{client_id}/wealth-positions", json={**HOME, **extra})
    assert resp.status_code == 409, resp.text[:300]
    assert _code(resp) == "PROPERTY_ADVANCED_FEATURE_DISABLED"
    assert feature in resp.json()["detail"]["features"]
    # Nichts angelegt (kein stiller Teil-Write).
    assert api.get(f"/clients/{client_id}/wealth-positions").json() == []


def test_amortization_amount_is_allowed_and_update_paths_are_gated(api, advisor_user):
    """K1-Nachtrag 1 (N-913-01): Amortisation ist wieder erfassbar (konstante
    Ausgabe); die uebrigen deaktivierten Funktionen bleiben auch im Update 409."""
    client_id = _client(api, advisor_user)
    home = api.post(f"/clients/{client_id}/wealth-positions", json=HOME).json()
    resp = api.post(f"/clients/{client_id}/wealth-positions",
                    json=_mortgage(home["id"], mortgage_amortization_rappen=20_000_00))
    assert resp.status_code == 201, resp.text[:300]
    upd = api.put(f"/clients/{client_id}/wealth-positions/{resp.json()['id']}",
                  json={"mortgage_amortization_rappen": 10_000_00})
    assert upd.status_code == 200, upd.text[:300]
    upd = api.put(f"/clients/{client_id}/wealth-positions/{home['id']}",
                  json={"is_available_for_goal_funding": True})
    assert upd.status_code == 409 and _code(upd) == "PROPERTY_ADVANCED_FEATURE_DISABLED"
    upd = api.put(f"/clients/{client_id}/wealth-positions/{home['id']}",
                  json={"asset_expected_return_bps": 100})
    assert upd.status_code == 409
    # Neutrale Werte bleiben schreibbar.
    ok = api.put(f"/clients/{client_id}/wealth-positions/{home['id']}",
                 json={"is_available_for_goal_funding": False, "goal_funding_method": "Ignorieren",
                       "asset_expected_return_bps": 0})
    assert ok.status_code == 200, ok.text[:300]


def test_pension_vehicle_change_to_police_is_gated_on_merged_state(api, advisor_user):
    """N-913-05: Vorsorge-Konto mit Goal-Funding-Flag (zulaessig) darf nicht per
    Vehikelwechsel zur Police mit gesetztem Flag werden."""
    client_id = _client(api, advisor_user)
    konto = api.post(f"/clients/{client_id}/wealth-positions", json={
        "label": "Synthetic vested account", "position_type": "Vorsorge", "assignment": "Anderes Vermögen",
        "current_value_rappen": 100_000_00, "currency": "CHF", "pension_type": "Freizügigkeit",
        "pension_vehicle": "Konto", "is_available_for_goal_funding": True, "data_classification": "synthetic",
    })
    assert konto.status_code == 201, konto.text[:300]
    upd = api.put(f"/clients/{client_id}/wealth-positions/{konto.json()['id']}", json={"pension_vehicle": "Police"})
    assert upd.status_code == 409 and _code(upd) == "PROPERTY_ADVANCED_FEATURE_DISABLED", upd.text[:300]
    assert upd.json()["detail"]["features"] == ["goal_funding_collateral"]
    both = api.put(f"/clients/{client_id}/wealth-positions/{konto.json()['id']}",
                   json={"pension_vehicle": "Police", "is_available_for_goal_funding": False})
    assert both.status_code == 200, both.text[:300]


def test_liquid_positions_keep_goal_funding_flag(api, advisor_user):
    client_id = _client(api, advisor_user)
    resp = api.post(f"/clients/{client_id}/wealth-positions", json={
        "label": "Synthetic savings", "position_type": "Liquidität", "assignment": "Anderes Vermögen",
        "current_value_rappen": 50_000_00, "currency": "CHF", "is_available_for_goal_funding": True,
        "goal_funding_method": "Automatisch", "data_classification": "synthetic",
    })
    assert resp.status_code == 201, resp.text[:300]


def test_mixed_mortgage_type_rejected_for_new_values_legacy_kept(api, advisor_user, session_factory):
    client_id = _client(api, advisor_user)
    resp = api.post(f"/clients/{client_id}/wealth-positions", json=_mortgage(mortgage_type="Gemischt"))
    assert resp.status_code == 422 and _code(resp) == "MORTGAGE_TYPE_MIXED_REJECTED", resp.text[:300]
    fixed = api.post(f"/clients/{client_id}/wealth-positions", json=_mortgage()).json()
    upd = api.put(f"/clients/{client_id}/wealth-positions/{fixed['id']}", json={"mortgage_type": "Gemischt"})
    assert upd.status_code == 422 and _code(upd) == "MORTGAGE_TYPE_MIXED_REJECTED"
    # Altbestand (direkt in der DB, wie vor K1 erfasst) bleibt unveraendert speicherbar.
    with session_factory() as s:
        s.execute(text("UPDATE wealth_positions SET mortgage_type = 'Gemischt' WHERE id = :id"),
                  {"id": fixed["id"]})
        s.commit()
    keep = api.put(f"/clients/{client_id}/wealth-positions/{fixed['id']}",
                   json={"mortgage_type": "Gemischt", "label": "Altbestand"})
    assert keep.status_code == 200, keep.text[:300]


# ── 2./3. CH-Normalfall, keine Luecke, keine Doppelzaehlung ─────────────────


def test_ch_home_and_mortgage_fully_capturable_without_double_count(api, advisor_user):
    client_id = _client(api, advisor_user)
    home = api.post(f"/clients/{client_id}/wealth-positions", json=HOME)
    assert home.status_code == 201, home.text[:300]
    home = home.json()
    assert (home["current_value_rappen"], home["currency"], home["valuation_date"],
            home["asset_valuation_method"]) == (1_200_000_00, "CHF", "2026-11-18", "Fachgutachten")
    mortgage = api.post(f"/clients/{client_id}/wealth-positions",
                        json=_mortgage(home["id"], mortgage_amortization_rappen=10_000_00))
    assert mortgage.status_code == 201, mortgage.text[:300]
    mortgage = mortgage.json()
    assert (mortgage["mortgage_type"], mortgage["mortgage_interest_rate_bps"],
            mortgage["mortgage_maturity_date"], mortgage["mortgage_linked_property_id"]) == (
        "Festhypothek", 140, "2032-03-31", home["id"])
    api.post(f"/clients/{client_id}/wealth-positions", json={
        "label": "Synthetic depot", "position_type": "Depot", "assignment": "Beratungsvermögen",
        "current_value_rappen": 450_000_00, "currency": "CHF", "alloc_equities_bps": 5000,
        "alloc_bonds_bps": 5000, "data_classification": "synthetic",
    })
    summary = api.get(f"/clients/{client_id}/wealth-summary").json()
    assert summary["gross_wealth_rappen"] == 1_650_000_00
    assert summary["liabilities_rappen"] == 600_000_00
    assert summary["net_worth_rappen"] == 1_050_000_00
    assert summary["advisory_wealth_rappen"] == 450_000_00

    # N-913-01: Zins (Satz x heutige Schuld) und Amortisation werden abgeleitet ...
    derived = {d["label"]: d["amount_rappen"] for d in api.get(f"/clients/{client_id}/cashflows-derived").json()
               if d["origin_position_type"] == "Hypothek"}
    assert derived == {"Hypothekarzins: Synthetic mortgage": 8_400_00,
                       "Amortisation: Synthetic mortgage": 10_000_00}, derived
    # ... eine manuelle Doppelerfassung ist gesperrt ...
    for label in ("Hypothekarzins", "Amortisation Hypothek"):
        blocked = api.post(f"/clients/{client_id}/cashflows", json={
            "cashflow_type": "Expense", "label": label, "amount_rappen": 8_400_00,
            "frequency": "jährlich", "nature": "wiederkehrend", "data_classification": "synthetic",
        })
        assert blocked.status_code == 422, (label, blocked.text[:300])
    # ... und die Belastung zaehlt genau einmal (konstant, kein Schuldabbau).
    totals = api.get(f"/clients/{client_id}/cashflow-summary").json()
    assert totals["recurring_expense_rappen"] == 18_400_00, totals


def test_guard_counterproof_manual_mortgage_interest_double_counts_without_guard(api, advisor_user, monkeypatch):
    """Gegenprobe Guard: ohne die Hypothekarzins-Erkennung wird der manuelle
    Eintrag angenommen und die Belastung doppelt gezaehlt (8'400 + 8'400)."""
    import routers.wealth as wealth_router

    monkeypatch.setattr(wealth_router, "_is_mortgage_interest_label", lambda _label: False)
    client_id = _client(api, advisor_user)
    api.post(f"/clients/{client_id}/wealth-positions", json=_mortgage())
    manual = api.post(f"/clients/{client_id}/cashflows", json={
        "cashflow_type": "Expense", "label": "Hypothekarzins", "amount_rappen": 8_400_00,
        "frequency": "jährlich", "nature": "wiederkehrend", "data_classification": "synthetic",
    })
    assert manual.status_code == 201
    assert api.get(f"/clients/{client_id}/cashflow-summary").json()["recurring_expense_rappen"] == 16_800_00


def test_mortgage_without_interest_rate_blocks_generate(api, advisor_user):
    """N-913-01: kein stilles 0 % -- Generate sperrt typisiert mit Wegweiser."""
    from tests.test_e2e_thierry_goessi_walkthrough import (
        _seed_cashflows, _seed_goals, _seed_products, _seed_risk_profile, _seed_wealth,
    )

    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    _seed_cashflows(api, client_id)
    _seed_wealth(api, client_id)
    _seed_goals(api, mandate_id)
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    _seed_products(api, advisor_user)
    norate = api.post(f"/clients/{client_id}/wealth-positions",
                      json={**_mortgage(), "label": "Hypothek ohne Satz", "mortgage_interest_rate_bps": None})
    assert norate.status_code == 201, norate.text[:300]
    blocked = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert blocked.status_code == 409 and _code(blocked) == "MORTGAGE_INTEREST_RATE_MISSING", blocked.text[:300]
    assert "Hypothek ohne Satz" in blocked.json()["detail"]["message"]
    # Satz nachgetragen -> Generate laeuft.
    fixed = api.put(f"/clients/{client_id}/wealth-positions/{norate.json()['id']}",
                    json={"mortgage_interest_rate_bps": 150})
    assert fixed.status_code == 200
    ok = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={"preferences": {}})
    assert ok.status_code in (200, 201), ok.text[:300]


# ── 4. Engine ──────────────────────────────────────────────────────────────


def _pos(**kwargs):
    base = dict(id="p", client_id="c", label="x", currency="CHF", is_active=1, deleted_at=None,
                current_value_rappen=0, mortgage_amortization_rappen=0, mortgage_amortization_type=None,
                mortgage_interest_rate_bps=0, mortgage_type=None, mortgage_maturity_date=None,
                mortgage_linked_property_id=None, asset_expected_return_bps=None,
                is_available_for_goal_funding=0, goal_funding_method=None, pension_type=None,
                pension_retirement_age=None, pension_payout_form=None, pension_vehicle=None,
                liquidity_available_from=None, property_rental_income_rappen=0,
                property_rental_inflation_linked=0, liquidity_interest_rate_bps=None)
    base.update(kwargs)
    return SimpleNamespace(**base)


HOME_POS = dict(id="home", position_type="Immobilien", assignment="Anderes Vermögen",
                current_value_rappen=1_000_000_00, asset_expected_return_bps=200,
                is_available_for_goal_funding=1)
MORTGAGE_POS = dict(id="mort", position_type="Hypothek", assignment="Verbindlichkeit",
                    current_value_rappen=400_000_00, mortgage_interest_rate_bps=150,
                    mortgage_amortization_rappen=10_000_00, mortgage_amortization_type="Direkt",
                    mortgage_type="Festhypothek", mortgage_maturity_date="2028-12-31",
                    mortgage_linked_property_id="home")


def test_engine_ignores_collateral_growth_debt_reduction_and_refinancing():
    home, mortgage = _pos(**HOME_POS), _pos(**MORTGAGE_POS)
    savings = _pos(id="sav", position_type="Liquidität", assignment="Anderes Vermögen",
                   current_value_rappen=30_000_00, is_available_for_goal_funding=1)
    # Collateral: nur die liquide Position speist den Pool.
    assert pe._unlocked_other_assets_rappen([home, mortgage, savings]) == 30_000_00
    # Foundation: Immobilie flach, Schuld konstant, keine verpfaendete Serie.
    foundation = pe._build_external_foundation_projection([home, mortgage], horizon_years=5)
    assert foundation["property_series_rappen"] == [1_000_000_00] * 6
    assert foundation["liability_series_rappen"] == [400_000_00] * 6
    assert foundation["pledged_asset_series_rappen"] == [0] * 6
    # Cashflows: laufende Belastung konstant abgeleitet (N-913-01), keine
    # Refinanzierungs- und keine Schuldabbau-Korrektur des Zinses.
    flows = {d.label: d.amount_rappen for d in derive_wealth_cashflows([home, mortgage])
             if d.origin_position_type == "Hypothek"}
    assert flows == {"Hypothekarzins: x": 6_000_00, "Amortisation: x": 10_000_00}
    assert mortgage_interest_adjustment_series([mortgage], 6, 2026) == [0] * 6
    # KN-B / E2E2-09 (CTO-Entscheid): die Amortisation endet, sobald die kumulierte
    # Amortisation die heutige Schuld (400'000 / 10'000 = 40 Jahre) erreicht.
    assert mortgage_amortization_adjustment_series([mortgage], 60) == [0] * 40 + [10_000_00] * 20


def test_derived_mortgage_flows_disappear_when_derivation_is_removed(monkeypatch):
    """Gegenprobe Ableitung: ohne Hypothekar-Zweig in derive_wealth_cashflows
    (Stand K1 vor Nachtrag 1) fehlt die Belastung -- der Test oben wird rot."""
    import services.wealth_cashflows as wc

    mortgage = _pos(**MORTGAGE_POS)
    monkeypatch.setattr(wc, "is_mortgage_position", lambda _ptype: False)
    assert [d for d in wc.derive_wealth_cashflows([mortgage]) if d.origin_position_type == "Hypothek"] == []


def test_rate_check_blocks_only_missing_rates():
    from core.reason_codes import DomainError
    from services.wealth_cashflows import require_mortgage_interest_rates

    ok = [_pos(**MORTGAGE_POS), _pos(id="zero", position_type="Hypothek", current_value_rappen=0,
                                     mortgage_interest_rate_bps=None)]
    assert require_mortgage_interest_rates(ok) is ok
    with pytest.raises(DomainError) as exc:
        require_mortgage_interest_rates([_pos(**{**MORTGAGE_POS, "mortgage_interest_rate_bps": None, "label": "M"})])
    assert exc.value.reason_code == "MORTGAGE_INTEREST_RATE_MISSING"
    assert exc.value.as_detail()["positions"] == ["M"]


def test_engine_mechanics_differ_when_dormant_path_is_enabled(property_advanced_mechanics_enabled):
    """Gegenprobe: dieselben Eingaben MIT der dormanten Mechanik zeigen genau
    die Claims, die das Gate abschaltet."""
    home, mortgage = _pos(**HOME_POS), _pos(**MORTGAGE_POS)
    assert pe._unlocked_other_assets_rappen([home, mortgage]) == 600_000_00
    foundation = pe._build_external_foundation_projection([home, mortgage], horizon_years=2)
    assert foundation["property_series_rappen"][2] > 1_000_000_00
    assert foundation["liability_series_rappen"][2] < 400_000_00
    assert any(d.origin_position_type == "Hypothek" for d in derive_wealth_cashflows([mortgage]))


def test_model_basis_labels_bind_gate_state():
    labels = gate.model_basis_labels()
    assert labels["property_advanced_features"] == "disabled_until_p1_closure_v1"
    assert labels["mortgage_cashflow_treatment"] == "derived_flat_interest_and_amortization_v1"


# ── 5. Migration ───────────────────────────────────────────────────────────


def _legacy_db(tmp_path):
    from database import Base

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    now = "2026-11-18T00:00:00Z"
    rows = [
        dict(id="home", position_type="Immobilien", assignment="Anderes Vermögen",
             is_available_for_goal_funding=1, goal_funding_method="Belehnung",
             asset_expected_return_bps=200, mortgage_amortization_rappen=0, mortgage_type=None),
        dict(id="mort", position_type="Hypothek", assignment="Verbindlichkeit",
             is_available_for_goal_funding=0, goal_funding_method=None,
             asset_expected_return_bps=None, mortgage_amortization_rappen=30_000_00,
             mortgage_type="Gemischt"),
        dict(id="mixed-only", position_type="Hypothek", assignment="Verbindlichkeit",
             is_available_for_goal_funding=0, goal_funding_method=None,
             asset_expected_return_bps=None, mortgage_amortization_rappen=0, mortgage_type="Gemischt"),
        dict(id="cash", position_type="Liquidität", assignment="Anderes Vermögen",
             is_available_for_goal_funding=1, goal_funding_method="Automatisch",
             asset_expected_return_bps=None, mortgage_amortization_rappen=0, mortgage_type=None),
    ]
    from sqlalchemy.orm import Session

    from models.clients import Client

    with Session(engine) as session:
        session.add(Client(id="c1", client_number="C1", first_name="A", last_name="B",
                           advisor_id="adv", created_at=now, updated_at=now))
        session.commit()
    from models.wealth import WealthPosition

    with Session(engine) as session:
        for row in rows:
            session.add(WealthPosition(client_id="c1", label=row["id"], current_value_rappen=100000,
                                       currency="CHF", is_active=1, created_at=now, updated_at=now, **row))
        session.commit()
    return engine


def test_migration_neutralizes_and_logs_owner_review_idempotently(tmp_path):
    engine = _legacy_db(tmp_path)
    with engine.begin() as conn:
        cases = neutralize_legacy_property_values(conn, recorded_at="2026-11-19T00:00:00Z")
    assert sorted(c["position_id"] for c in cases) == ["home", "mixed-only", "mort"]
    with engine.connect() as conn:
        rows = {r["id"]: dict(r) for r in conn.execute(text(
            "SELECT id, is_available_for_goal_funding, goal_funding_method, asset_expected_return_bps, "
            "mortgage_amortization_rappen, mortgage_type, property_gate_review_json FROM wealth_positions"
        )).mappings()}
    assert (rows["home"]["is_available_for_goal_funding"], rows["home"]["goal_funding_method"],
            rows["home"]["asset_expected_return_bps"]) == (0, "Ignorieren", None)
    review = json.loads(rows["home"]["property_gate_review_json"])
    assert review["reason_code"] == "PROPERTY_ADVANCED_FEATURE_DISABLED" and review["status"] == "OPEN"
    assert {(f["field"], f["previous"]) for f in review["findings"]} == {
        ("is_available_for_goal_funding", 1), ("goal_funding_method", "Belehnung"),
        ("asset_expected_return_bps", 200)}
    # Amortisation neutralisiert, "Gemischt" bleibt (offen gemeldet).
    # N-913-01: Amortisation bleibt (konstante Ausgabe); "Gemischt" bleibt, offen gemeldet.
    assert rows["mort"]["mortgage_amortization_rappen"] == 30_000_00
    assert rows["mort"]["mortgage_type"] == "Gemischt"
    mort_features = {f["feature"] for f in json.loads(rows["mort"]["property_gate_review_json"])["findings"]}
    assert mort_features == {"mortgage_type_mixed_legacy"}
    assert json.loads(rows["mixed-only"]["property_gate_review_json"])["findings"][0]["action"] == "keep_open"
    # Liquide Position unveraendert, kein Fall.
    assert (rows["cash"]["is_available_for_goal_funding"], rows["cash"]["goal_funding_method"],
            rows["cash"]["property_gate_review_json"]) == (1, "Automatisch", None)
    # Idempotent.
    with engine.begin() as conn:
        assert neutralize_legacy_property_values(conn) == []
    engine.dispose()


def test_alembic_k1_single_head_upgrade_downgrade_and_column_parity(tmp_path, monkeypatch):
    from alembic import command
    from alembic.script import ScriptDirectory

    import database as db_module

    script = ScriptDirectory.from_config(alembic_cfg("sqlite://"))
    # CCX-P5 haengt hinter K1 (c2546c196134 -> 63332bb56098).
    assert script.get_heads() == ["c2546c196134"]
    assert script.get_revision("c2546c196134").down_revision == K1_REV
    assert script.get_revision(K1_REV).down_revision == K1_DOWN_REV
    assert script.get_revision(K1_DOWN_REV).down_revision == P4_REV

    db = tmp_path / "k1.db"
    cfg = alembic_cfg(f"sqlite:///{db}")

    def columns(path):
        with sqlite3.connect(path) as conn:
            return [r[1] for r in conn.execute("PRAGMA table_info(wealth_positions)")]

    command.upgrade(cfg, "head")
    assert "property_gate_review_json" in columns(db)
    command.downgrade(cfg, K1_DOWN_REV)
    assert "property_gate_review_json" not in columns(db)
    command.upgrade(cfg, "head")
    alembic_cols = set(columns(db))

    orm_db = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{orm_db}")
    db_module.Base.metadata.create_all(engine)
    engine.dispose()
    boot_db = tmp_path / "boot.db"
    db_module.bootstrap_sqlite_schema(db_path=boot_db, schema_path=db_module.resolve_schema_path())
    # Bestands-DB ohne die neue Spalte: der SQLite-Laufzeitpatch ergaenzt sie.
    patched_db = tmp_path / "patched.db"
    db_module.bootstrap_sqlite_schema(db_path=patched_db, schema_path=db_module.resolve_schema_path())
    with sqlite3.connect(patched_db) as conn:
        conn.execute("ALTER TABLE wealth_positions DROP COLUMN property_gate_review_json")
    assert "property_gate_review_json" not in columns(patched_db)
    engine = create_engine(f"sqlite:///{patched_db}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    engine.dispose()
    assert "property_gate_review_json" in set(columns(orm_db)) & set(columns(boot_db)) & alembic_cols
    assert "property_gate_review_json" in columns(patched_db)
    # Bootstrap-SQL kennt tenant_id/property_rental_inflation_linked bekanntlich erst
    # ueber den Laufzeitpatch; ORM und Alembic sind spaltengleich.
    assert set(columns(orm_db)) == alembic_cols


def test_postgres_offline_ddl_adds_column_and_guards_legacy_values():
    """N-913-06: Offline-SQL legt die Spalte an und bricht ab, falls
    neutralisierungspflichtige Altwerte existieren (kein stilles Ueberspringen)."""
    from tests.h10_support import postgres_offline_ddl

    ddl = postgres_offline_ddl(K1_DOWN_REV, K1_REV)
    assert "ALTER TABLE wealth_positions ADD COLUMN property_gate_review_json VARCHAR" in ddl
    assert "RAISE EXCEPTION 'K1 63332bb56098" in ddl and "goal_funding_method = 'Belehnung'" in ddl


def test_migration_has_no_app_imports_and_matches_runtime_neutralization(tmp_path):
    """N-913-06: Revision ohne App-Importe (Regeln eingefroren) und mit
    demselben Ergebnis wie der SQLite-Startpfad (database + core.property_gate)."""
    import ast
    import shutil
    from pathlib import Path

    from alembic import command

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / f"{K1_REV}_k1_property_advanced_gate.py"
    imported = {n.module.split(".")[0] for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name.split(".")[0] for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.Import) for a in n.names}
    assert imported <= {"__future__", "json", "datetime", "typing", "sqlalchemy", "alembic"}, imported

    # Legacy-Zeilen im Head-Schema anlegen, Revision zurueck und wieder vor:
    # die Revision neutralisiert dieselben Zeilen wie der Laufzeitpfad.
    engine = _legacy_db(tmp_path)
    engine.dispose()
    alembic_db = tmp_path / "alembic_legacy.db"
    cfg = alembic_cfg(f"sqlite:///{alembic_db}")
    command.upgrade(cfg, "head")
    src = sqlite3.connect(tmp_path / "legacy.db")
    dst = sqlite3.connect(alembic_db)
    cols = [r[1] for r in src.execute("PRAGMA table_info(wealth_positions)") if r[1] != "property_gate_review_json"]
    dst_cols = {r[1] for r in dst.execute("PRAGMA table_info(wealth_positions)")}
    cols = [c for c in cols if c in dst_cols]
    dst.execute("PRAGMA foreign_keys = OFF")
    for name, in dst.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='wealth_positions'").fetchall():
        dst.execute(f"DROP TRIGGER {name}")
    for row in src.execute(f"SELECT {', '.join(cols)} FROM wealth_positions"):
        dst.execute(f"INSERT INTO wealth_positions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", row)
    dst.commit()
    src.close()
    dst.close()
    command.downgrade(cfg, K1_DOWN_REV)
    command.upgrade(cfg, "head")
    runtime_copy = tmp_path / "runtime.db"
    shutil.copy(tmp_path / "legacy.db", runtime_copy)
    runtime = create_engine(f"sqlite:///{runtime_copy}")
    with runtime.begin() as conn:
        neutralize_legacy_property_values(conn, recorded_at="T")
    runtime.dispose()

    def state(db_path):
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT id, is_available_for_goal_funding, goal_funding_method, asset_expected_return_bps, "
                "mortgage_amortization_rappen, mortgage_type, property_gate_review_json FROM wealth_positions "
                "ORDER BY id").fetchall()
        return [(r[:6], json.loads(r[6])["findings"] if r[6] else None) for r in rows]

    assert state(alembic_db) == state(runtime_copy)


# ── 6. PROP-5: Duplikat-Schutz im Update-Pfad ──────────────────────────────


def test_position_update_that_starts_rent_is_checked_against_manual_rent(api, advisor_user):
    client_id = _client(api, advisor_user)
    prop = api.post(f"/clients/{client_id}/wealth-positions", json={
        **HOME, "label": "Synthetic rental", "property_usage": "Renditeobjekt", "current_value_rappen": 0,
    })
    assert prop.status_code == 201, prop.text[:300]
    rent = api.post(f"/clients/{client_id}/cashflows", json={
        "cashflow_type": "Income", "label": "Mieteinnahmen", "amount_rappen": 24_000_00,
        "frequency": "jährlich", "data_classification": "synthetic",
    })
    assert rent.status_code == 201, rent.text[:300]
    # Wert 0 -> > 0 mit Mietertrag: die Position wuerde dieselbe Miete ableiten.
    upd = api.put(f"/clients/{client_id}/wealth-positions/{prop.json()['id']}", json={
        "current_value_rappen": 800_000_00, "property_rental_income_rappen": 24_000_00,
    })
    assert upd.status_code == 422, upd.text[:300]
    # Eine Aenderung, die keine Miete neu entstehen laesst, bleibt erlaubt.
    ok = api.put(f"/clients/{client_id}/wealth-positions/{prop.json()['id']}", json={"label": "Umbenannt"})
    assert ok.status_code == 200, ok.text[:300]
