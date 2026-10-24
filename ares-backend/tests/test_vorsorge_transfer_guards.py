"""PENSION-TRANSFER-LEDGER-001 (Folgefix PR #642, Codex-Review 2026-10-18).

Uebernimmt die fuenf adversarialen Vertraege aus
docs/audits/reproducers/test_2026_10_18_vorsorge_transfer_ledger_pr642_adversarial.py
(Codex-Branch) als regulaere Tests und ergaenzt die Pflichtregressionen:

1. Quelle mit aktivem verknuepftem Zufluss kann nicht deaktiviert, geloescht
   oder semantisch umtypisiert werden (422 wie der Hypotheken-Guard,
   reason_code PENSION_SOURCE_LINKED; CIO-Entscheid 2026-10-19).
2. linked => einmalig + nominal (422).
3. hoechstens ein aktiver Link je Quelle (422; DB-Partial-Unique-Index haelt
   auch, wenn der applikationsseitige Precheck umgangen wird).
4. Link-Existenz != Horizont-Sichtbarkeit: ein verknuepfter Bezug hinter dem
   Horizont unterdrueckt den Auto-Bezug; die Quelle bleibt bis Horizontende
   gebunden. Link vor dem Bewertungsjahr, Orphan, Mehrfach- und
   Ratenlinks in Bestandsdaten sind fail-closed.
5. PensionTransferLedgerV1: Brutto = Steuer + Netto auf den Rappen,
   Restbestand 0 (Vollbezug), horizontinvarianter Hash, getrennte Zeilen je
   Quelle; die Netto-Bezuege des Ledgers sind die EINZIGE Basis der
   Zufluss-Serie. Betragsregel (CIO-Entscheid 2026-10-19): beim
   verknuepften Bezug ist der erfasste Betrag der massgebende Nettobezug
   (Steuer enthalten; Steuer nur abgeleitet, Rest = explizite
   Bewertungsanpassung, Hinweis ab 5 % Abweichung); die Positionssteuer gilt nur fuer den Auto-Bezug.
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.portfolio_engine_pension_positions import (  # noqa: E402
    build_pension_projection,
    with_pension_payouts,
)
from services.pension_transfer_ledger import (  # noqa: E402
    PENSION_TRANSFER_LEDGER_VERSION,
    PensionTransferLedgerError,
)

MONOLITH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"
START = 2026
HORIZON = 5


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vorsorge-transfer-guards.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-vguards", username="advisor-vguards", password_hash="h",
        full_name="Guard Advisor", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _create_client(auth_client, advisor_user, suffix: str) -> str:
    response = auth_client.post("/clients", json={
        "client_number": f"VG-{suffix}", "first_name": "Pension", "last_name": "Ledger",
        "advisor_id": advisor_user.id, "household_type": "Einzelperson",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_position(auth_client, client_id: str, **overrides) -> str:
    body = {
        "label": "3a Quelle", "position_type": "Vorsorge", "assignment": "Anderes Vermögen",
        "current_value_rappen": 10_000_000, "pension_type": "Säule 3a",
        "liquidity_available_from": "2028-06-30",
    }
    body.update(overrides)
    response = auth_client.post(f"/clients/{client_id}/wealth-positions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _inflow_payload(position_id, **overrides) -> dict:
    payload = {
        "label": "Kapitalbezug 3a", "source_type": "Saeule3b", "amount_rappen": 10_000_000,
        "expected_year": 2028, "linked_position_id": position_id,
    }
    payload.update(overrides)
    return payload


def _linked_pair(auth_client, advisor_user, suffix: str) -> tuple[str, str, str]:
    client_id = _create_client(auth_client, advisor_user, suffix)
    position_id = _create_position(auth_client, client_id)
    response = auth_client.post(f"/clients/{client_id}/wealth-inflows", json=_inflow_payload(position_id))
    assert response.status_code == 201, response.text
    return client_id, position_id, response.json()["id"]


def _reason(response) -> str:
    detail = response.json().get("detail")
    return detail.get("reason_code") if isinstance(detail, dict) else ""


# ---------------------------------------------------------------------------
# Codex-Vertraege 1+2 (+ Retyping): Quellen-Lifecycle
# ---------------------------------------------------------------------------


def test_linked_source_cannot_be_deactivated_while_inflow_is_active(auth_client, advisor_user):
    client_id, position_id, _ = _linked_pair(auth_client, advisor_user, "DEACT")
    response = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{position_id}", json={"is_active": False},
    )
    assert response.status_code == 422, response.text
    assert _reason(response) == "PENSION_SOURCE_LINKED"
    assert "Kapitalbezug 3a" in response.json()["detail"]["message"]
    listed = auth_client.get(f"/clients/{client_id}/wealth-positions").json()
    assert [p["id"] for p in listed] == [position_id]


def test_linked_source_cannot_be_deleted_while_inflow_is_active(auth_client, advisor_user):
    client_id, position_id, _ = _linked_pair(auth_client, advisor_user, "DELETE")
    response = auth_client.delete(f"/clients/{client_id}/wealth-positions/{position_id}")
    assert response.status_code == 422, response.text
    assert _reason(response) == "PENSION_SOURCE_LINKED"
    listed = auth_client.get(f"/clients/{client_id}/wealth-positions").json()
    assert [p["id"] for p in listed] == [position_id]


@pytest.mark.parametrize("update", [
    {"assignment": "Beratungsvermögen"},
])
def test_linked_source_cannot_be_retyped_out_of_link_contract(auth_client, advisor_user, update):
    client_id, position_id, _ = _linked_pair(auth_client, advisor_user, "RETYPE")
    response = auth_client.put(f"/clients/{client_id}/wealth-positions/{position_id}", json=update)
    assert response.status_code == 422, response.text
    assert _reason(response) == "PENSION_SOURCE_LINKED"


def test_linked_source_value_and_tax_stay_editable(auth_client, advisor_user):
    client_id, position_id, _ = _linked_pair(auth_client, advisor_user, "EDIT")
    response = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{position_id}",
        json={"current_value_rappen": 12_000_000, "pension_lumpsum_tax_bps": 700, "label": "3a neu"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("release", ["delete_inflow", "deactivate_inflow", "unlink_inflow"])
def test_released_link_no_longer_blocks_source_lifecycle(auth_client, advisor_user, release):
    client_id, position_id, inflow_id = _linked_pair(auth_client, advisor_user, f"REL-{release}")
    if release == "delete_inflow":
        assert auth_client.delete(f"/wealth-inflows/{inflow_id}").status_code == 204
    elif release == "deactivate_inflow":
        assert auth_client.put(f"/wealth-inflows/{inflow_id}", json={"is_active": 0}).status_code == 200
    else:
        assert auth_client.put(
            f"/wealth-inflows/{inflow_id}", json={"linked_position_id": None},
        ).status_code == 200
    response = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{position_id}", json={"is_active": False},
    )
    assert response.status_code == 200, response.text
    assert auth_client.delete(f"/clients/{client_id}/wealth-positions/{position_id}").status_code == 204


# ---------------------------------------------------------------------------
# Codex-Vertrag 3: linked => einmalig (Vollbezug), zusaetzlich nominal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("frequency", ["jaehrlich", "monatlich"])
def test_linked_pension_transfer_must_be_one_time(auth_client, advisor_user, frequency):
    client_id = _create_client(auth_client, advisor_user, f"RECUR-{frequency}")
    position_id = _create_position(auth_client, client_id)
    response = auth_client.post(
        f"/clients/{client_id}/wealth-inflows",
        json=_inflow_payload(position_id, is_recurring=True, frequency=frequency, duration_years=3),
    )
    assert response.status_code == 422, response.text
    assert "einmalig" in response.text


def test_linking_an_existing_recurring_inflow_is_rejected(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user, "RECUR-PUT")
    position_id = _create_position(auth_client, client_id)
    created = auth_client.post(
        f"/clients/{client_id}/wealth-inflows",
        json=_inflow_payload(None, is_recurring=1, frequency="jaehrlich", duration_years=3),
    )
    assert created.status_code == 201, created.text
    response = auth_client.put(
        f"/wealth-inflows/{created.json()['id']}", json={"linked_position_id": position_id},
    )
    assert response.status_code == 422, response.text


def test_linked_inflow_cannot_become_recurring(auth_client, advisor_user):
    _client_id, _position_id, inflow_id = _linked_pair(auth_client, advisor_user, "RECUR-UPD")
    response = auth_client.put(
        f"/wealth-inflows/{inflow_id}",
        json={"is_recurring": 1, "frequency": "jaehrlich", "duration_years": 2},
    )
    assert response.status_code == 422, response.text


def test_linked_transfer_must_be_nominal(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user, "REAL")
    position_id = _create_position(auth_client, client_id)
    response = auth_client.post(
        f"/clients/{client_id}/wealth-inflows", json=_inflow_payload(position_id, value_mode="real"),
    )
    assert response.status_code == 422, response.text
    assert "nominal" in response.text


# ---------------------------------------------------------------------------
# Codex-Vertrag 4: hoechstens ein aktiver Link je Quelle
# ---------------------------------------------------------------------------


def test_only_one_active_transfer_can_link_to_a_pension_source(auth_client, advisor_user):
    client_id, position_id, _ = _linked_pair(auth_client, advisor_user, "CARD")
    second = auth_client.post(
        f"/clients/{client_id}/wealth-inflows",
        json=_inflow_payload(position_id, label="Derselbe Kapitalbezug nochmals", expected_year=2029),
    )
    assert second.status_code == 422, second.text
    assert _reason(second) == "PENSION_SOURCE_ALREADY_LINKED"


def test_relinking_another_inflow_to_a_taken_source_is_rejected(auth_client, advisor_user):
    client_id, position_id, _ = _linked_pair(auth_client, advisor_user, "CARD-PUT")
    other = auth_client.post(f"/clients/{client_id}/wealth-inflows", json=_inflow_payload(None, label="Bonus"))
    assert other.status_code == 201, other.text
    response = auth_client.put(f"/wealth-inflows/{other.json()['id']}", json={"linked_position_id": position_id})
    assert response.status_code == 422, response.text
    assert _reason(response) == "PENSION_SOURCE_ALREADY_LINKED"


def test_resaving_the_same_linked_inflow_is_not_a_self_conflict(auth_client, advisor_user):
    _client_id, position_id, inflow_id = _linked_pair(auth_client, advisor_user, "SELF")
    response = auth_client.put(
        f"/wealth-inflows/{inflow_id}",
        json={"label": "Kapitalbezug 3a (neu)", "linked_position_id": position_id, "expected_year": 2029},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("release", ["delete_inflow", "deactivate_inflow"])
def test_inactive_or_deleted_old_link_does_not_block_new_transfer(auth_client, advisor_user, release):
    client_id, position_id, inflow_id = _linked_pair(auth_client, advisor_user, f"OLD-{release}")
    if release == "delete_inflow":
        assert auth_client.delete(f"/wealth-inflows/{inflow_id}").status_code == 204
    else:
        assert auth_client.put(f"/wealth-inflows/{inflow_id}", json={"is_active": 0}).status_code == 200
    response = auth_client.post(
        f"/clients/{client_id}/wealth-inflows", json=_inflow_payload(position_id, expected_year=2030),
    )
    assert response.status_code == 201, response.text
    if release == "deactivate_inflow":
        reactivated = auth_client.put(f"/wealth-inflows/{inflow_id}", json={"is_active": 1})
        assert reactivated.status_code == 422, reactivated.text
        assert _reason(reactivated) == "PENSION_SOURCE_ALREADY_LINKED"


def test_db_partial_unique_index_holds_when_precheck_is_bypassed(auth_client, advisor_user, monkeypatch):
    """Concurrency: zwei Requests passieren beide den SELECT-Precheck -- die
    DB-Constraint muss den zweiten Insert ablehnen (422, kein 500)."""
    import routers.wealth as wealth_router

    monkeypatch.setattr(wealth_router, "_block_if_pension_source_already_linked", lambda *a, **k: None)
    client_id, position_id, _ = _linked_pair(auth_client, advisor_user, "RACE")
    second = auth_client.post(
        f"/clients/{client_id}/wealth-inflows", json=_inflow_payload(position_id, expected_year=2029),
    )
    assert second.status_code == 422, second.text
    assert _reason(second) == "PENSION_SOURCE_ALREADY_LINKED"
    listed = auth_client.get(f"/clients/{client_id}/wealth-inflows").json()
    assert len(listed) == 1


def test_orm_insert_of_second_active_link_violates_unique_index(session_factory):
    from models.wealth import WealthInflow

    def _row(row_id, **overrides):
        values = dict(
            id=row_id, client_id="c1", label="Bezug", source_type="Andere", amount_rappen=100,
            expected_year=2030, is_recurring=0, value_mode="nominal", linked_position_id="p1",
            is_active=1, created_at=_now(), updated_at=_now(),
        )
        values.update(overrides)
        return WealthInflow(**values)

    from tests._wealth_link_legacy import legacy_link_guards_disabled

    with session_factory() as session:
        session.execute(text("PRAGMA foreign_keys=OFF"))
        # Links ohne Position: nur der Unique-Index ist hier Gegenstand
        # (PG-002-Link-Trigger wuerden sie sonst schon vorher ablehnen).
        with legacy_link_guards_disabled(session):
            session.add(_row("i1"))
            session.add(_row("i-inactive", is_active=0))
            session.add(_row("i-deleted", deleted_at=_now()))
            session.add(_row("i-unlinked", linked_position_id=None))
            session.add(_row("i-unlinked-2", linked_position_id=None))
            session.commit()
            session.add(_row("i2"))
            with pytest.raises(IntegrityError):
                session.commit()


# ---------------------------------------------------------------------------
# Schema: Bootstrap-DDL, Runtime-Patch, Alembic (genau ein Head)
# ---------------------------------------------------------------------------

_INDEX = "ux_wealth_inflow_one_active_pension_link"


def test_bootstrap_ddl_creates_partial_unique_index(session_factory):
    engine = session_factory.kw["bind"]
    indexes = {ix["name"]: ix for ix in inspect(engine).get_indexes("wealth_inflows")}
    assert _INDEX in indexes and indexes[_INDEX]["unique"]
    with engine.connect() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:n"), {"n": _INDEX},
        ).scalar_one()
    assert "linked_position_id IS NOT NULL" in ddl and "is_active = 1" in ddl and "deleted_at IS NULL" in ddl


def test_runtime_patch_adds_index_to_legacy_sqlite_db(tmp_path):
    from database import ensure_current_anchor_unique_indexes

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(f"DROP INDEX {_INDEX}"))
    assert _INDEX not in {ix["name"] for ix in inspect(engine).get_indexes("wealth_inflows")}
    ensure_current_anchor_unique_indexes(engine)
    assert _INDEX in {ix["name"] for ix in inspect(engine).get_indexes("wealth_inflows")}
    engine.dispose()


def test_alembic_has_single_head_with_partial_unique_index():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    # Die Index-Migration muss nicht der Head sein (spaetere Migrationen
    # haengen sich an); sie muss genau einmal in der Kette zum Head liegen.
    chain = [rev for rev in script.walk_revisions("base", heads[0])]
    carrying = [
        rev for rev in chain
        if _INDEX in Path(rev.path).read_text(encoding="utf-8")
        and "create_index" in Path(rev.path).read_text(encoding="utf-8")
    ]
    assert len(carrying) == 1, [rev.revision for rev in carrying]
    source = Path(carrying[0].path).read_text(encoding="utf-8")
    assert "sqlite_where" in source and "postgresql_where" in source


# ---------------------------------------------------------------------------
# Codex-Vertrag 5 + Ledger
# ---------------------------------------------------------------------------


def _position(**overrides):
    values = {
        "id": "p-outside", "label": "3a ausserhalb Horizont", "position_type": "Vorsorge",
        "assignment": "Anderes Vermögen", "current_value_rappen": 10_000_000, "currency": "CHF",
        "pension_type": "Säule 3a", "pension_vehicle": "Konto", "pension_interest_rate_bps": 0,
        "pension_maturity_value_rappen": None, "pension_maturity_date": None,
        "pension_retirement_age": None, "liquidity_available_from": "2028-06-30",
        "pension_lumpsum_tax_rappen": None, "pension_lumpsum_tax_bps": None,
        "is_active": 1, "deleted_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _linked(position_id="p-outside", **overrides):
    values = dict(
        id="i-outside", label="Expliziter Bezug", source_type="Saeule3b", amount_rappen=10_000_000,
        expected_year=2036, linked_position_id=position_id, is_active=1, is_recurring=0,
        frequency=None, duration_years=None, value_mode="nominal",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _project(positions, inflows, horizon=HORIZON):
    return build_pension_projection(
        positions, inflows, start_year=START, horizon_years=horizon,
        value_of=lambda item: item.current_value_rappen,
    )


def test_explicit_link_outside_horizon_still_suppresses_earlier_auto_payout():
    projection = _project([_position()], [_linked()])
    assert projection is not None
    assert projection.payout_series_rappen == [0] * HORIZON
    assert projection.series_rappen == [10_000_000] * (HORIZON + 1)
    (row,) = projection.ledger.rows
    assert row.origin == "linked_inflow" and row.payout_year == 2036 and not row.within_horizon
    assert any("2036" in note and "ausserhalb" in note for note in projection.notes)


def test_horizon_extension_shows_same_transfer_without_regime_change():
    position = _position(pension_vehicle="Wertschriften", pension_interest_rate_bps=None)
    short = _project([position], [_linked()], horizon=5)
    long = _project([position], [_linked()], horizon=15)
    (row_short,) = short.ledger.rows
    (row_long,) = long.ledger.rows
    assert row_long.within_horizon and not row_short.within_horizon
    for attr in ("payout_year", "gross_withdrawal_rappen", "lumpsum_tax_rappen",
                 "net_advisory_inflow_rappen", "closing_bound_balance_rappen", "origin"):
        assert getattr(row_short, attr) == getattr(row_long, attr), attr
    assert short.ledger.input_hash == long.ledger.input_hash
    assert long.payout_series_rappen[2036 - START] == row_long.net_advisory_inflow_rappen
    assert sum(long.payout_series_rappen) == row_long.net_advisory_inflow_rappen
    # gebunden bis inkl. Serie[k], ab k+1 ausgebucht
    assert long.series_rappen[2036 - START] > 0 and long.series_rappen[2036 - START + 1] == 0


def test_link_before_valuation_year_is_fail_closed():
    with pytest.raises(PensionTransferLedgerError) as exc:
        _project([_position()], [_linked(expected_year=START - 1)])
    assert exc.value.reason_code == "PENSION_TRANSFER_BEFORE_VALUATION"


def test_orphan_link_is_fail_closed():
    with pytest.raises(PensionTransferLedgerError) as exc:
        _project([_position(is_active=0)], [_linked()])
    assert exc.value.reason_code == "PENSION_SOURCE_LINK_ORPHAN"
    with pytest.raises(PensionTransferLedgerError):
        _project([], [_linked()])


def test_duplicate_or_recurring_links_in_legacy_data_are_fail_closed():
    with pytest.raises(PensionTransferLedgerError) as exc:
        _project([_position()], [_linked(), _linked(id="i-2", expected_year=2029)])
    assert exc.value.reason_code == "PENSION_SOURCE_MULTIPLE_LINKS"
    with pytest.raises(PensionTransferLedgerError) as exc:
        _project([_position()], [_linked(is_recurring=1, frequency="jaehrlich", duration_years=3)])
    assert exc.value.reason_code == "PENSION_TRANSFER_NOT_ONE_TIME"
    with pytest.raises(PensionTransferLedgerError) as exc:
        _project([_position()], [_linked(value_mode="real")])
    assert exc.value.reason_code == "PENSION_TRANSFER_NOT_ONE_TIME"
    # inaktive Bestands-Links zaehlen nicht
    projection = _project([_position()], [_linked(), _linked(id="i-old", is_active=0, expected_year=2027)])
    assert len(projection.ledger.rows) == 1


def test_linked_full_payout_books_recorded_net_and_discloses_implicit_tax():
    position = _position(pension_vehicle="Wertschriften", pension_interest_rate_bps=None,
                         pension_lumpsum_tax_bps=300)  # gilt NICHT fuer den verknuepften Bezug
    inflow = _linked(expected_year=2028, amount_rappen=9_999_999)
    projection = _project([position], [inflow])
    (row,) = projection.ledger.rows
    projected = round(10_000_000 * 1.03 ** 3)
    assert row.transfer_mode == "full"
    assert row.opening_bound_balance_rappen == 10_000_000
    assert row.projected_bound_balance_rappen == projected
    assert row.net_advisory_inflow_rappen == 9_999_999  # erfasster Betrag ist massgebend
    # PR-#651-Restbefund A: Steuer nur abgeleitet (Positionssatz 3 % auf die
    # Hochrechnung), der Rest der Luecke ist eine explizite Bewertungsanpassung.
    inferred_tax = round(projected * 300 / 10000)
    assert row.lumpsum_tax_rappen == inferred_tax
    assert row.tax_source == "erfasst_satz" and row.tax_provenance == "inferred"
    assert row.gross_withdrawal_rappen == 9_999_999 + inferred_tax
    assert row.valuation_adjustment_rappen == row.gross_withdrawal_rappen - projected < 0
    assert row.gross_withdrawal_rappen == row.lumpsum_tax_rappen + row.net_advisory_inflow_rappen
    assert (row.projected_bound_balance_rappen + row.valuation_adjustment_rappen
            == row.gross_withdrawal_rappen + row.closing_bound_balance_rappen)
    assert row.closing_bound_balance_rappen == 0
    assert projection.payout_series_rappen == [0, 0, 9_999_999, 0, 0]
    assert projection.linked_replacement_series_rappen == [0, 0, 9_999_999, 0, 0]
    # 9'999'999 vs. Hochrechnung 10'927'270 - 3 % = 10'599'452 -> 5.7 % Abweichung
    assert any("weicht" in note and "Bewertungsanpassung" in note for note in projection.notes)


def test_linked_payout_within_five_percent_gives_no_hint():
    position = _position()  # Konto 0 %, Default-Steuer 10 % -> erwartet 9'000'000
    projection = _project([position], [_linked(expected_year=2028, amount_rappen=8_700_000)])
    assert not any("weicht" in note or "höher als" in note for note in projection.notes)
    (row,) = projection.ledger.rows
    # Default-Steuer 10 % auf 10'000'000 = 1'000'000 (abgeleitet), Rest -300'000
    # ist Bewertungsanpassung -- nicht pauschal "Steuer".
    assert row.net_advisory_inflow_rappen == 8_700_000 and row.lumpsum_tax_rappen == 1_000_000
    assert row.tax_provenance == "inferred" and row.valuation_adjustment_rappen == -300_000


def test_linked_payout_above_projection_has_zero_tax_and_hint():
    projection = _project([_position()], [_linked(expected_year=2028, amount_rappen=10_500_000)])
    (row,) = projection.ledger.rows
    assert row.projected_bound_balance_rappen == 10_000_000
    assert row.net_advisory_inflow_rappen == row.gross_withdrawal_rappen == 10_500_000
    assert row.lumpsum_tax_rappen == 0 and row.tax_provenance == "unavailable"
    assert row.valuation_adjustment_rappen == 500_000
    assert any("höher als Hochrechnung" in note for note in projection.notes)


def test_inflow_series_consumer_uses_ledger_net_not_recorded_amount():
    from services.portfolio_engine import _wealth_inflow_series_rappen
    from services.portfolio_engine_pension_positions import pension_foundation_keys

    position = _position(pension_lumpsum_tax_rappen=500_000)
    inflow = _linked(expected_year=2028, amount_rappen=12_345_678)
    other = _linked(id="i-erbe", linked_position_id=None, amount_rappen=1_000, expected_year=2027,
                    source_type="Erbschaft", label="Erbe")
    inflows = [inflow, other]
    raw = _wealth_inflow_series_rappen(inflows, HORIZON, START, [0] * HORIZON)
    foundation = pension_foundation_keys(
        [position], inflows, start_year=START, horizon_years=HORIZON,
    )
    combined = with_pension_payouts(raw, foundation)
    # Bezug genau einmal, mit dem erfassten Nettobetrag (CIO-Entscheid);
    # die Positionssteuer gilt nicht fuer den verknuepften Bezug.
    assert combined == [0, 1_000, 12_345_678, 0, 0]
    # Roh-Konsumenten (Cashflow-Tab, Report-Reserve) sehen fuer den
    # verknuepften Bezug denselben Betrag wie der Ledger.
    assert raw == combined


def test_multiple_sources_in_same_year_stay_separate_ledger_rows():
    a = _position(id="pa", label="3a A", pension_lumpsum_tax_rappen=300_000)
    b = _position(id="pb", label="FZ B", pension_type="Freizügigkeit", current_value_rappen=5_000_000,
                  pension_lumpsum_tax_bps=500)
    projection = _project([a, b], [_linked(position_id="pb", expected_year=2028, id="ib",
                                           amount_rappen=4_600_000)])
    rows = {row.source_position_id: row for row in projection.ledger.rows}
    assert set(rows) == {"pa", "pb"}
    assert rows["pa"].origin == "auto" and rows["pb"].origin == "linked_inflow"
    assert rows["pa"].lumpsum_tax_rappen == 300_000 and rows["pa"].tax_source == "erfasst_betrag"
    assert rows["pa"].tax_provenance == "observed" and rows["pa"].valuation_adjustment_rappen == 0
    # 5 % von 5'000'000 = 250'000 abgeleitet; Luecke 400'000 -> -150'000 Anpassung
    assert rows["pb"].lumpsum_tax_rappen == 250_000
    assert rows["pb"].tax_source == "erfasst_satz" and rows["pb"].tax_provenance == "inferred"
    assert rows["pb"].valuation_adjustment_rappen == -150_000
    assert projection.payout_series_rappen[2] == (10_000_000 - 300_000) + 4_600_000


def test_ledger_identity_hash_binds_transfer_and_policy():
    base = _project([_position()], [_linked(expected_year=2028)])
    again = _project([_position()], [_linked(expected_year=2028)])
    taxed = _project([_position()], [_linked(expected_year=2028, amount_rappen=9_000_000)])
    moved = _project([_position()], [_linked(expected_year=2029)])
    assert base.ledger.version == PENSION_TRANSFER_LEDGER_VERSION
    assert base.ledger.policy_version.startswith("vorsorge-projektion-")
    assert re.fullmatch(r"[0-9a-f]{64}", base.ledger.input_hash)
    assert base.ledger.input_hash == again.ledger.input_hash
    assert len({base.ledger.input_hash, taxed.ledger.input_hash, moved.ledger.input_hash}) == 3


def test_fx_basis_and_currency_are_recorded():
    position = _position(currency="EUR")
    projection = build_pension_projection(
        [position], [], start_year=START, horizon_years=HORIZON,
        value_of=lambda item: 9_000_000, target_currency="CHF",
    )
    (row,) = projection.ledger.rows
    assert row.currency == "CHF" and row.fx_basis == "EUR->CHF"
    assert row.opening_bound_balance_rappen == 9_000_000


# ---------------------------------------------------------------------------
# Monolith: Guard-Meldungen verstaendlich, Regel gespiegelt
# ---------------------------------------------------------------------------


def _fn(html: str, name: str) -> str:
    start = html.index(f"function {name}(")
    end = html.index("\nfunction ", start + 10) if "\nfunction " in html[start + 10:] else len(html)
    return html[start:end]


def test_monolith_inflow_modal_mirrors_one_time_nominal_link_rule():
    html = MONOLITH.read_text(encoding="utf-8")
    sync = _fn(html, "syncInflowModalState")
    assert "awi-linked-position" in sync and "awi-recurring" in sync and "awi-value-mode" in sync
    save = html[html.index("async function saveInflow("):html.index("async function deleteInflow(")]
    assert "einmaliger Kapitalbezug" in save


def test_monolith_maps_pension_guard_reason_codes_to_readable_text():
    html = MONOLITH.read_text(encoding="utf-8")
    hints = html[html.index("var PENSION_TRANSFER_GUARD_HINTS"):]
    helper = _fn(html, "pensionTransferGuardMessage")
    for code in ("PENSION_SOURCE_LINKED", "PENSION_SOURCE_ALREADY_LINKED"):
        assert code in hints[:hints.index("function pensionTransferGuardMessage(")]
    assert "reason_code" in helper and "detail.message" in helper
    save = html[html.index("async function saveInflow("):html.index("async function deleteInflow(")]
    assert "pensionTransferGuardMessage(" in save
    delete = html[html.index("async function deleteCurrentWealthPosition("):]
    assert "pensionTransferGuardMessage(" in delete[:3000]
