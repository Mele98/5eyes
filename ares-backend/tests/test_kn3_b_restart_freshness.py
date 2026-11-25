"""KN3-B / N-917R2-01: Der erste Neustart nach der Ersteinrichtung entwertet
keine Publikation.

Befund (H-167 R2): In der ersten Sitzung hatte der Bootstrap-Admin keine
``tenant_id``; Kunde und (abgeleitet) Positionen entstanden mit NULL und wurden
so versiegelt. Beim naechsten Start zogen die Start-Backfills
(``database.ensure_tenant_backfill``, ``wealth_tenant_boundary``) sie per
Roh-SQL auf ``'main'`` -- die Pull-Pruefung sah Drift bei ``client`` und
``positions``, die Publikation war ``PUBLICATION_INVALID``.

Fix (CTO-Entscheid):
1. Ursache: Kunden und Protokoll-Bausteine bekommen schon beim Anlegen den
   Default-Mandanten (``services.auth.tenant_id_for_new_record``), auch wenn der
   anlegende Bootstrap-Admin noch keinen hat; Positionen erben ihn vom Kunden,
   Mandate hatten ihn schon (routers/mandates.py). Der Bootstrap-Admin selbst
   bleibt bewusst unveraendert (Benutzer sind keine Freshness-Kante; eine
   Aenderung wuerde die Lizenzzaehlung ``max_users`` schon in der ersten
   Sitzung scharf schalten -- Owner-Entscheid, siehe H-170).
2. ``tenant_id`` ist in den Freshness-Kanten Mandantengrenze, kein
   Beratungsinhalt (``ADVISORY_TENANT_BOUNDARY_COLUMNS``): volatil im Hook und
   nicht in der Manifest-Projektion. Bestehende Siegel (mit ``tenant_id``, auch
   NULL vor dem Backfill) bleiben ueber Uebergangs-Hashes aktuell.

Querschnitt: Einrichtung -> Kunde -> Publikation -> Start-Pfad erneut
(``database.init_db``) -> FRESH. Gegenprobe: eine relevante Aenderung nach dem
Neustart macht die Publikation weiterhin STALE.

Gegenproben (Fix zurueck -> rot):
* ``ADVISORY_TENANT_BOUNDARY_COLUMNS`` leer -> Neustart-Tests rot.
* ``_legacy_hashes`` liefert ``()`` -> Uebergangstest rot.
* ``tenant_id_for_new_record`` ohne Default-Rueckfall -> Anlage-Test rot.
"""
from __future__ import annotations

from sqlalchemy import text

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p2_invalidation import _envelope
from tests.test_ccx_p4_allocation_publish import _published, _state


def _restart(session_factory):
    """App-Start-Pfad erneut: dieselbe Funktion wie der Lifespan (main.py)."""
    import database

    engine = session_factory.kw["bind"]
    database.init_db(target_engine=engine)


def _tenants(session_factory, mid):
    with session_factory() as db:
        client_id = db.execute(text("SELECT client_id FROM mandates WHERE id = :m"), {"m": mid}).scalar()
        client = db.execute(text("SELECT tenant_id FROM clients WHERE id = :c"), {"c": client_id}).scalar()
        positions = {row[0] for row in db.execute(
            text("SELECT tenant_id FROM wealth_positions WHERE client_id = :c"), {"c": client_id})}
    return client_id, client, positions


def _fresh(session_factory, mid, envelope_id):
    with session_factory() as db:
        env = tuple(_envelope(db, envelope_id)[:2])
    state = _state(session_factory, mid)
    return env, state.status, state.reason_code


def test_publication_from_first_session_stays_fresh_after_restart(session_factory):
    _a, _b, mid, _aid, _run, decision = _published(session_factory, "kn3-rs")
    client_id, client_tenant, position_tenants = _tenants(session_factory, mid)
    # Ausgangslage wie in der ersten Sitzung (Altdaten): ohne Mandant versiegelt.
    assert client_tenant is None and position_tenants == {None}
    before = _fresh(session_factory, mid, decision.envelope_id)
    assert before == (("SEALED", "FRESH"), "PUBLISHED", None), before

    _restart(session_factory)
    _restart(session_factory)
    # Der Backfill hat gewirkt (sonst prueft der Test nichts) ...
    _cid, client_tenant, position_tenants = _tenants(session_factory, mid)
    assert client_tenant == "main" and position_tenants == {"main"}
    # ... und die Publikation bleibt gueltig.
    assert _fresh(session_factory, mid, decision.envelope_id) == before

    # Gegenprobe: eine relevante Aenderung nach dem Neustart entwertet weiterhin.
    from models.clients import Client

    with session_factory() as db:
        db.get(Client, client_id).date_of_birth = "1961-02-03"
        db.commit()
    env, status, code = _fresh(session_factory, mid, decision.envelope_id)
    assert env == ("SEALED", "STALE") and status == "PUBLICATION_INVALID" and code == "CCX_INPUT_STALE"


def test_position_value_change_after_restart_is_still_stale(session_factory):
    _a, _b, mid, _aid, _run, decision = _published(session_factory, "kn3-rs-pos")
    _restart(session_factory)
    assert _fresh(session_factory, mid, decision.envelope_id)[1] == "PUBLISHED"
    from models.wealth import WealthPosition

    client_id, _c, _p = _tenants(session_factory, mid)
    with session_factory() as db:
        pos = db.query(WealthPosition).filter(WealthPosition.client_id == client_id).first()
        pos.current_value_rappen = int(pos.current_value_rappen or 0) + 100_00
        db.commit()
    assert _fresh(session_factory, mid, decision.envelope_id)[1] == "PUBLICATION_INVALID"


def test_orm_tenant_only_change_does_not_invalidate(session_factory):
    """Hook: eine reine Mandantenzuordnung (ORM) ist kein Beratungsinhalt."""
    from models.clients import Client
    from models.wealth import WealthPosition

    _a, _b, mid, _aid, _run, decision = _published(session_factory, "kn3-orm")
    client_id, _c, _p = _tenants(session_factory, mid)
    with session_factory() as db:
        db.get(Client, client_id).tenant_id = "main"
        for pos in db.query(WealthPosition).filter(WealthPosition.client_id == client_id).all():
            pos.tenant_id = "main"
        db.commit()
    assert _fresh(session_factory, mid, decision.envelope_id) == (("SEALED", "FRESH"), "PUBLISHED", None)


def test_seal_made_before_the_boundary_rule_survives_the_backfill(session_factory, monkeypatch):
    """Uebergang: ein Altsiegel band ``tenant_id`` (hier NULL) mit. Nach dem
    Backfill auf 'main' bleibt es aktuell; eine echte Aenderung entwertet es."""
    import services.effective_input_manifest as manifest

    original = manifest._columns
    # KN4-B / N-917R3-06: Uebergang nur fuer Altsiegel -- hier wird ein Altsiegel
    # simuliert, also gilt es als vor dem Stichtag versiegelt.
    monkeypatch.setattr(manifest, "LEGACY_PROJECTION_SEALED_BEFORE", "9999-12-31T00:00:00.000Z")
    monkeypatch.setattr(manifest, "_columns", lambda model, include_exempt=False, include_boundary=False:
                        original(model, include_exempt=include_exempt, include_boundary=True))
    _a, _b, mid, _aid, _run, decision = _published(session_factory, "kn3-leg")
    monkeypatch.setattr(manifest, "_columns", original)
    assert _fresh(session_factory, mid, decision.envelope_id)[1] == "PUBLISHED"
    _restart(session_factory)
    assert _fresh(session_factory, mid, decision.envelope_id) == (("SEALED", "FRESH"), "PUBLISHED", None)

    from models.clients import Client

    client_id, _c, _p = _tenants(session_factory, mid)
    with session_factory() as db:
        db.get(Client, client_id).canton = "BE" if db.get(Client, client_id).canton != "BE" else "ZH"
        db.commit()
    assert _fresh(session_factory, mid, decision.envelope_id)[1] == "PUBLICATION_INVALID"


def test_boundary_rule_is_the_same_in_hook_and_manifest():
    from models.clients import ADVISORY_TENANT_BOUNDARY_COLUMNS
    from models.snapshots import DEPENDENCY_SOURCES
    from services.effective_input_manifest import _EXCLUDED_COLUMNS

    assert ADVISORY_TENANT_BOUNDARY_COLUMNS == {"tenant_id"}
    assert ADVISORY_TENANT_BOUNDARY_COLUMNS <= _EXCLUDED_COLUMNS
    for table, source in DEPENDENCY_SOURCES.items():
        assert ADVISORY_TENANT_BOUNDARY_COLUMNS <= source.volatile, table


def test_hook_keeps_the_tenant_of_a_change_for_its_reach():
    """``tenant_id`` ist volatil, bleibt aber fuer die Reichweite (globale
    CMA eines Mandanten) massgeblich."""
    from sqlalchemy import inspect as sa_inspect

    from models.allocation import CapitalMarketAssumption
    from models.snapshots import DEPENDENCY_SOURCES, _change, _old_new, _state_tenant

    row = CapitalMarketAssumption(id="cma-kn3", tenant_id="firma-x", is_current=1)
    state = sa_inspect(row)
    source = DEPENDENCY_SOURCES["capital_market_assumptions"]
    old, new = _old_new(state, source.volatile)
    assert "tenant_id" not in new
    change = _change("capital_market_assumptions", source, "insert", old, new, tenant=_state_tenant(state))
    assert change.tenant_id == "firma-x" and change.global_current is True


def test_new_records_get_the_default_tenant_only_in_single_tenant_mode(monkeypatch):
    from config import settings
    from models.users import User
    from services.auth import tenant_id_for_new_record

    legacy = User(id="u-kn3", username="u-kn3", password_hash="h", full_name="X", role="admin", tenant_id=None)
    monkeypatch.setattr(settings, "strict_tenant_isolation", False, raising=False)
    monkeypatch.setattr(settings, "tenancy_mode", "single", raising=False)
    monkeypatch.setattr(settings, "deployment_tier", "tier1", raising=False)
    assert tenant_id_for_new_record(legacy) == "main"
    assert tenant_id_for_new_record(User(id="u2", tenant_id="firma-a")) == "firma-a"
    # Mehrmandanten-Betrieb: nie raten (wie der Start-Backfill).
    monkeypatch.setattr(settings, "tenancy_mode", "multi", raising=False)
    assert tenant_id_for_new_record(legacy) is None


def test_first_client_and_position_after_bootstrap_carry_the_default_tenant(tmp_path):
    """Ursache: Ersteinrichtung ueber die echte API -> Kunde und Position tragen
    sofort 'main', obwohl der Bootstrap-Admin noch keinen Mandanten hat (kein
    spaeterer Backfill auf beratungsrelevanten Daten noetig)."""
    import datetime as _dt

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base, get_db
    from main import app
    from models.tenant import DEFAULT_TENANT_ID, Tenant

    engine = create_engine(f"sqlite:///{tmp_path / 'kn3_bootstrap.db'}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    now = _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")
    with sf() as s:
        s.add(Tenant(id=DEFAULT_TENANT_ID, display_name="Testfirma Fiktiv", slug="main", hosting_tier="tier1",
                     license_status="active", is_active=1, created_at=now, updated_at=now))
        s.commit()

    def override_db():
        with sf() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as api:
            resp = api.post("/auth/bootstrap-admin", json={
                "username": "kn3admin", "password": "StrongPass1234!", "full_name": "Erika Testberaterin",
                "company_name": "Testfirma Fiktiv",
            })
            assert resp.status_code == 201, resp.text
            headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
            me = api.get("/auth/me", headers=headers).json()
            client = api.post("/clients", headers=headers, json={
                "client_number": "KN3-1", "first_name": "Anna", "last_name": "Testkundin-Fiktiv",
                "advisor_id": me["id"], "data_classification": "synthetic",
            })
            assert client.status_code in (200, 201), client.text
            cid = client.json()["id"]
            pos = api.post(f"/clients/{cid}/wealth-positions", headers=headers, json={
                "label": "Depot", "position_type": "Depot", "assignment": "Beratungsvermögen",
                "current_value_rappen": 400_000_00, "currency": "CHF", "data_classification": "synthetic",
                "alloc_equities_bps": 4000, "alloc_bonds_bps": 5000, "alloc_liquidity_bps": 1000,
            })
            assert pos.status_code in (200, 201), pos.text
    finally:
        app.dependency_overrides.clear()
    with sf() as s:
        admin = s.execute(text("SELECT tenant_id FROM users WHERE username = 'kn3admin'")).scalar()
        client_tenant = s.execute(text("SELECT tenant_id FROM clients WHERE id = :c"), {"c": cid}).scalar()
        position_tenant = s.execute(
            text("SELECT tenant_id FROM wealth_positions WHERE client_id = :c"), {"c": cid}).scalar()
    engine.dispose()
    # OWN-LIC-01 (H-187, CTO-Entscheid): der Bootstrap-Admin bekommt sofort den
    # Standard-Mandanten (H-170), nicht erst beim Start-Backfill.
    assert (admin, client_tenant, position_tenant) == ("main", "main", "main")
