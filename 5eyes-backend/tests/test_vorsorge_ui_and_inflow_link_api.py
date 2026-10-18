"""VORSORGE-PROJECTION-001 (2026-10-18): Erfassung.

1. API: Vorsorge-Positionen duerfen eine vollstaendige Anlageklassen-
   Aufteilung tragen (vorher 422 "ausschliesslich für Depot") und die neuen
   Fortschreibungs-Felder (Anlageform, Satz, Ablaufwert, Faelligkeit).
2. API: WealthInflow.linked_position_id -- nur auf eine aktive Vorsorge-
   Position "Anderes Vermoegen" desselben Kunden.
3. Monolith: Vorsorge-Dialog erfasst Anlageform/Satz/Ablaufwert/Faelligkeit
   und "Verfuegbar ab" als echtes Feld; dieselbe Aufteilungs-Komponente
   (sc-*) ist fuer Vorsorge sichtbar; Zufluss-Maske bietet die Verknuepfung
   an; die Frontend-Vorschau nutzt dieselben Default-Saetze wie das Backend.
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402

MONOLITH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vorsorge_ui.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-vorsorge", username="advisor-vorsorge", password_hash="h",
        full_name="Test Advisor", role="advisor", is_active=1,
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


def _client(auth_client, advisor_user, number="VOR-001") -> str:
    resp = auth_client.post("/clients", json={
        "client_number": number, "first_name": "Vor", "last_name": "Sorge",
        "advisor_id": advisor_user.id, "household_type": "Einzelperson",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _position(auth_client, client_id, **body):
    payload = {
        "label": "PK", "position_type": "Vorsorge", "assignment": "Anderes Vermögen",
        "current_value_rappen": 300_000_00, "pension_type": "BVG",
    }
    payload.update(body)
    return auth_client.post(f"/clients/{client_id}/wealth-positions", json=payload)


def _inflow_payload(**body):
    payload = {
        "label": "Kapitalbezug PK", "source_type": "Andere",
        "amount_rappen": 300_000_00, "expected_year": 2035,
    }
    payload.update(body)
    return payload


# ---------------------------------------------------------------------------
# 1) Aufteilung fuer Vorsorge
# ---------------------------------------------------------------------------


def test_api_accepts_split_for_vorsorge_position(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    resp = _position(
        auth_client, cid, pension_type="Säule 3a", label="3a Wertschriften",
        alloc_equities_bps=7000, alloc_bonds_bps=2500, alloc_liquidity_bps=500,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["alloc_equities_bps"] == 7000


def test_api_put_split_on_vorsorge_position(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    pid = _position(auth_client, cid).json()["id"]
    ok = auth_client.put(f"/clients/{cid}/wealth-positions/{pid}", json={
        "alloc_equities_bps": 2000, "alloc_bonds_bps": 8000,
        "alloc_real_estate_bps": 0, "alloc_liquidity_bps": 0, "alloc_alternatives_bps": 0,
    })
    assert ok.status_code == 200, ok.text
    partial = auth_client.put(f"/clients/{cid}/wealth-positions/{pid}", json={
        "alloc_equities_bps": 5000,
    })
    assert partial.status_code == 422


def test_api_still_rejects_split_for_liquidity(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    resp = auth_client.post(f"/clients/{cid}/wealth-positions", json={
        "label": "Konto", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
        "current_value_rappen": 10_000_00, "alloc_liquidity_bps": 10000,
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 2) linked_position_id auf WealthInflow
# ---------------------------------------------------------------------------


def test_inflow_link_to_external_pension_position_roundtrips(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    pid = _position(auth_client, cid).json()["id"]
    resp = auth_client.post(
        f"/clients/{cid}/wealth-inflows", json=_inflow_payload(linked_position_id=pid),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["linked_position_id"] == pid
    listed = auth_client.get(f"/clients/{cid}/wealth-inflows").json()
    assert listed[0]["linked_position_id"] == pid
    # Verknuepfung loesen
    cleared = auth_client.put(
        f"/wealth-inflows/{listed[0]['id']}", json={"linked_position_id": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["linked_position_id"] is None


@pytest.mark.parametrize(
    "position_body",
    [
        {"position_type": "Depot", "assignment": "Beratungsvermögen", "pension_type": None,
         "alloc_equities_bps": 10000},
        {"assignment": "Beratungsvermögen"},
    ],
)
def test_inflow_link_rejects_non_external_pension_positions(auth_client, advisor_user, position_body):
    cid = _client(auth_client, advisor_user)
    created = _position(auth_client, cid, **position_body)
    assert created.status_code == 201, created.text
    resp = auth_client.post(
        f"/clients/{cid}/wealth-inflows",
        json=_inflow_payload(linked_position_id=created.json()["id"]),
    )
    assert resp.status_code == 422, resp.text


def test_inflow_link_rejects_unknown_and_foreign_positions(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    other = _client(auth_client, advisor_user, number="VOR-002")
    foreign_pid = _position(auth_client, other).json()["id"]
    unknown = auth_client.post(
        f"/clients/{cid}/wealth-inflows", json=_inflow_payload(linked_position_id="nope"),
    )
    foreign = auth_client.post(
        f"/clients/{cid}/wealth-inflows", json=_inflow_payload(linked_position_id=foreign_pid),
    )
    assert unknown.status_code == 422
    assert foreign.status_code == 422


def test_inflow_put_link_is_validated(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    inflow_id = auth_client.post(
        f"/clients/{cid}/wealth-inflows", json=_inflow_payload(),
    ).json()["id"]
    resp = auth_client.put(f"/wealth-inflows/{inflow_id}", json={"linked_position_id": "nope"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 3) Monolith
# ---------------------------------------------------------------------------


def _html() -> str:
    return MONOLITH.read_text(encoding="utf-8")


def _function_source(html: str, name: str) -> str:
    match = re.search(r"function " + re.escape(name) + r"\s*\(", html)
    assert match, name
    start = match.start()
    depth = 0
    for idx in range(html.index("{", start), len(html)):
        if html[idx] == "{":
            depth += 1
        elif html[idx] == "}":
            depth -= 1
            if depth == 0:
                return html[start:idx + 1]
    raise AssertionError(name)


def test_monolith_split_component_is_shown_for_vorsorge():
    html = _html()
    assert 'id="aw-alloc-split"' in html
    show = _function_source(html, "showAwFields")
    assert "aw-alloc-split" in show and "Vorsorge" in show
    build = _function_source(html, "buildWealthPositionPayload")
    assert "posType==='Vorsorge'" in build.replace(" ", "")
    editor = _function_source(html, "openWealthPositionEditor")
    vorsorge_branch = editor[editor.index("pos.position_type==='Vorsorge'"):]
    assert "sc-akt" in vorsorge_branch[:1500]


def test_monolith_inflow_modal_offers_position_link():
    html = _html()
    assert 'id="awi-linked-position"' in html
    save = _function_source(html, "saveInflow")
    assert "linked_position_id" in save
    edit = _function_source(html, "openInflowEditor")
    assert "linked_position_id" in edit


def test_api_roundtrips_projection_fields(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    resp = _position(
        auth_client, cid, pension_type="Säule 3b", label="Police",
        pension_vehicle="Police", pension_interest_rate_bps=None,
        pension_maturity_value_rappen=80_000_00, pension_maturity_date="2034-12-31",
        liquidity_available_from="2034-12-31",
        pension_lumpsum_tax_rappen=4_500_00, pension_lumpsum_tax_bps=None,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pension_vehicle"] == "Police"
    assert body["pension_maturity_value_rappen"] == 80_000_00
    assert body["pension_maturity_date"] == "2034-12-31"
    assert body["liquidity_available_from"] == "2034-12-31"
    assert body["pension_lumpsum_tax_rappen"] == 4_500_00
    assert body["pension_lumpsum_tax_bps"] is None
    pid = body["id"]
    upd = auth_client.put(f"/clients/{cid}/wealth-positions/{pid}", json={
        "pension_vehicle": "Wertschriften", "pension_interest_rate_bps": 250,
    })
    assert upd.status_code == 200, upd.text
    assert upd.json()["pension_interest_rate_bps"] == 250


def test_api_rejects_invalid_projection_fields(auth_client, advisor_user):
    cid = _client(auth_client, advisor_user)
    assert _position(auth_client, cid, pension_vehicle="Fonds").status_code == 422
    assert _position(auth_client, cid, pension_interest_rate_bps=5000).status_code == 422
    assert _position(auth_client, cid, pension_maturity_date="31.12.2034").status_code == 422
    assert _position(auth_client, cid, pension_lumpsum_tax_rappen=-1).status_code == 422
    assert _position(auth_client, cid, pension_lumpsum_tax_bps=6000).status_code == 422


def test_monolith_pension_dialog_captures_projection_fields():
    html = _html()
    for element_id in ("maw-pension-vehicle", "maw-pension-interest",
                       "maw-pension-maturity-value", "maw-pension-maturity-date",
                       "maw-pension-tax-chf", "maw-pension-tax-pct"):
        assert f'id="{element_id}"' in html, element_id
    build = _function_source(html, "buildWealthPositionPayload").replace(" ", "")
    for field in ("pension_vehicle", "pension_interest_rate_bps",
                  "pension_maturity_value_rappen", "pension_maturity_date",
                  "pension_lumpsum_tax_rappen", "pension_lumpsum_tax_bps"):
        assert field in build, field
    assert "payload.liquidity_available_from=" in build
    editor = _function_source(html, "openWealthPositionEditor")
    assert "pension_vehicle" in editor and "liquidity_available_from" in editor
    assert "pension_lumpsum_tax_rappen" in editor and "pension_lumpsum_tax_bps" in editor
    assert "Steuerrechner" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfuegbar")
def test_monolith_preview_rate_matches_backend_defaults():
    from services import portfolio_engine_pension_positions as pp

    source = _function_source(_html(), "pensionProjectionRateBps")
    cases = [
        {"pension_type": "Säule 3a"},
        {"pension_type": "Freizügigkeit"},
        {"pension_type": "Säule 3a", "pension_vehicle": "Wertschriften"},
        {"pension_type": "Säule 3b"},
        {"pension_type": "BVG"},
        {"pension_type": "BVG", "pension_interest_rate_bps": 125},
        {"pension_type": "Säule 3a", "pension_vehicle": "Wertschriften", "pension_interest_rate_bps": 0},
    ]
    script = source + ";console.log(JSON.stringify(" + json.dumps(cases) + ".map(pensionProjectionRateBps)));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, encoding="utf-8")
    frontend = json.loads(out.stdout)
    for case, fe in zip(cases, frontend):
        pos = SimpleNamespace(
            pension_type=case["pension_type"], pension_vehicle=case.get("pension_vehicle"),
            pension_interest_rate_bps=case.get("pension_interest_rate_bps"),
        )
        assert fe == pp.pension_rate_bps(pos)[0], case


def test_monolith_preview_excludes_external_pension_from_buckets():
    source = _function_source(_html(), "inferPositionBucketMixBps")
    assert "isExternalPensionPosition" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfuegbar")
def test_monolith_lumpsum_tax_default_matches_backend():
    from services import portfolio_engine_pension_positions as pp

    source = _function_source(_html(), "pensionLumpsumTaxDefaultBps")
    types = ["Säule 3a", "Freizügigkeit", "BVG", "Säule 3b", "Lebensversicherung", None]
    cases = [{"pension_type": t} for t in types]
    script = source + ";console.log(JSON.stringify(" + json.dumps(cases) + ".map(pensionLumpsumTaxDefaultBps)));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, encoding="utf-8")
    frontend = json.loads(out.stdout)
    assert pp.PENSION_LUMPSUM_TAX_DEFAULT_BPS == 1000
    for pension_type, fe in zip(types, frontend):
        assert fe == pp.pension_lumpsum_tax_default_bps(SimpleNamespace(pension_type=pension_type)), pension_type
