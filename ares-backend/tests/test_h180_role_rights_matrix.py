"""H-180 Teil B: Rechte-Matrix Rolle x Aktion als Regressionsnetz (echte HTTP-Aufrufe).

Jede Zeile von ``MATRIX`` ist eine Aktion der Beratungskette oder der
Administration, je Rolle steht ``A`` (erlaubt) oder ``-`` (gesperrt). Der Test
ruft die echte App per HTTP (TestClient, Wegwerf-SQLite) mit einem Token der
jeweiligen Rolle auf:

* gesperrt  = HTTP 401/403, bei mandats-/kundengebundenen Aktionen auch 404
  mit der Sichtbarkeitsmeldung ("Kunde/Mandat nicht gefunden");
* erlaubt   = jede andere Antwort unter 500 (z. B. 200, 409 fachliche Sperre,
  422 bei bewusst unvollstaendigem Body -- die Rollenpruefung liegt in FastAPI
  vor der Body-Validierung bzw. im Handler vor der Fachlogik).

Rollen (alle im Mandanten ``t-a``, ausser ``admin_b``/``advisor_b`` in ``t-b``):
admin, advisor (Kundenbetreuer), advisor2 (anderer Berater derselben Firma),
readonly, portfolio_management (pm), compliance_reviewer (externe
Pruefperson, per Einladung aktiviert, 2FA selbst gesetzt), super_admin
(Plattform-Betreiber, ohne Mandant), client (Kundenportal-Login).

Ergaenzend: Mandantentrennung (Firma B sieht nichts von Firma A) und das
Routen-Inventar (``test_route_auth_inventory_has_no_unreviewed_weakening``):
keine neue oeffentliche Route, keine schreibende Route ohne Rollenpruefung,
keine Abschwaechung einer bekannten Route ohne Eintrag hier.

Alle Namen/Werte sind fiktive Testwerte.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import create_access_token, hash_password  # noqa: E402

NOW = "2026-11-21T09:00:00.000Z"
PW = "Testpasswort-H180-Matrix-1"

# role-key -> (user id, DB-Rolle, tenant)
ROLES: dict[str, tuple[str, str, str | None]] = {
    "admin": ("h180-adm", "admin", "t-a"),
    "advisor": ("h180-adv", "advisor", "t-a"),
    "advisor2": ("h180-adv2", "advisor", "t-a"),
    "readonly": ("h180-ro", "readonly", "t-a"),
    "pm": ("h180-pm", "portfolio_management", "t-a"),
    "reviewer": ("h180-rev", "compliance_reviewer", "t-a"),
    "super_admin": ("h180-sa", "super_admin", None),
    "client": ("h180-cl", "client", "t-a"),
    "admin_b": ("h180-adm-b", "admin", "t-b"),
    "advisor_b": ("h180-adv-b", "advisor", "t-b"),
}
COLUMNS = tuple(ROLES)
SCOPE_404 = ("Kunde nicht gefunden", "Mandat nicht gefunden")

DEPOT = {"label": "Depot CHF (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
         "current_value_rappen": 100_000_00, "currency": "CHF", "depot_bank": "Testbank Fiktiv",
         "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000}

# (Aktion, Methode, Pfad, Body, scoped, Erwartung je Spalte in COLUMNS-Reihenfolge)
#               admin adv adv2 ro  pm  rev  sa  cl  admB advB
MATRIX: list[tuple[str, str, str, object, bool, str]] = [
    ("Kundenliste lesen", "GET", "/clients", None, False,
     "A A A A A - A A A A"),
    ("Kunde lesen", "GET", "/clients/c-a", None, True,
     "A A - - - - - - - -"),
    ("Kunde anlegen", "POST", "/clients", {}, False,
     "A A A - - - - - A A"),
    ("Kunde aendern", "PUT", "/clients/c-a", {"first_name": "Eva"}, True,
     "A A - - - - - - - -"),
    ("KYC-Bestaetigung erfassen", "POST", "/clients/c-a/kyc-confirmations", {}, False,
     "A A A - - - - - A A"),
    ("KYC-Zweitfreigabe entscheiden", "POST", "/compliance/kyc-approvals/x/decision", {}, False,
     "A - - - - A A - A -"),
    ("Risikoprofil lesen", "GET", "/mandates/m-a/risk-assessments", None, True,
     "A A - - - - - - - -"),
    ("Vermoegensposition erfassen", "POST", "/clients/c-a/wealth-positions", DEPOT, True,
     "A A - - - - - - - -"),
    ("Strategie berechnen", "POST", "/mandates/m-a/target-allocation/generate", {"preferences": {}}, True,
     "A A - - - - - - - -"),
    ("Portfolio generieren", "POST", "/mandates/m-a/recommendations/generate", {}, True,
     "A A - - - - - - - -"),
    ("Publizieren (Freigabe)", "POST", "/mandates/m-a/allocation-publication",
     {"target_allocation_id": "x", "validation_hash": "0" * 64}, True,
     "A A - - - - - - - -"),
    ("Empfehlung finalisieren", "PUT", "/mandates/m-a/recommendations/run-x/finalize", None, True,
     "A A - - - - - - - -"),
    ("Kunden-PDF Risikoprofil", "GET", "/mandates/m-a/reports/risikoprofil.pdf", None, True,
     "A A - - - - - - - -"),
    ("FX-Kurse pflegen (Tier 1)", "PUT", "/fx-rates", {}, False,
     "A A A - A - A - A A"),
    ("CMA aendern (Tier 1)", "PUT", "/capital-market-assumptions", {}, False,
     "A - - - A - A - A -"),
    ("Optimizer-Policies lesen", "GET", "/optimizer-policies", None, False,
     "A A A - A - A - A A"),
    ("Produkte lesen", "GET", "/products", None, False,
     "A A A A A - A - A A"),
    ("Produkt anlegen", "POST", "/products", {}, False,
     "A - - - - - A - A -"),
    ("Benutzer auflisten", "GET", "/users", None, False,
     "A - - - - - A - A -"),
    ("Benutzer anlegen", "POST", "/users", {}, False,
     "A - - - - - A - A -"),
    ("Benutzer einladen", "POST", "/users/invite", {}, False,
     "A - - - - - A - A -"),
    ("Mandanteneinstellungen aendern", "PUT", "/tenants/me", {}, False,
     "A - - - - - A - A -"),
    ("Rechtliche Angaben lesen", "GET", "/compliance/legal-profile", None, False,
     "A A A A A - A - A A"),
    ("Audit-Log lesen", "GET", "/admin/system/audit-log", None, False,
     "A - - - - - A - A -"),
    ("Audit-Kette pruefen (Tier 1)", "GET", "/admin/system/audit-log/verification-status", None, False,
     "A - - - - - A - A -"),
    ("Backups auflisten", "GET", "/admin/system/backups", None, False,
     "A - - - - - A - A -"),
    ("Marktdaten-Cache leeren (global)", "POST", "/admin/system/market-data/purge-now", None, False,
     "A - - - A - A - A -"),
    ("Datenschutz-Anfragen lesen", "GET", "/privacy/subject-requests", None, False,
     "A - - - - - A - A -"),
    ("KYC-Wiedervorlage-Policy erfassen", "POST", "/compliance/kyc-review-policies", {}, False,
     "A - - - - - A - A -"),
    ("KYC-Wiedervorlage-Policy freigeben", "POST", "/compliance/kyc-review-policies/x/activate", {}, False,
     "A - - - - A A - A -"),
]


@pytest.fixture(scope="module")
def session_factory(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("h180") / "h180.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as db:
        for tid in ("t-a", "t-b"):
            db.add(Tenant(id=tid, display_name=f"Testfirma {tid} Fiktiv", slug=tid, max_users=50,
                          created_at=NOW, updated_at=NOW))
        for uid, role, tid in ROLES.values():
            extra = {}
            if role == "compliance_reviewer":
                extra = dict(invited_by="h180-adm", invited_at=NOW, activated_at=NOW, credentials_set_by="self",
                             totp_enabled=1, totp_set_by="self", reviewer_organisation="TEST-H180 Org",
                             reviewer_reference="TEST-H180 Mandat")
            db.add(User(id=uid, username=uid, password_hash=hash_password(PW), full_name=uid.upper(),
                        role=role, is_active=1, tenant_id=tid, created_at=NOW, updated_at=NOW, **extra))
        for cid, mid, advisor, tid in (("c-a", "m-a", "h180-adv", "t-a"), ("c-b", "m-b", "h180-adv-b", "t-b")):
            db.add(Client(id=cid, tenant_id=tid, client_number=f"K-{cid}", first_name="Eva",
                          last_name="Muster-Fiktiv", advisor_id=advisor, created_at=NOW, updated_at=NOW))
            db.add(Mandate(id=mid, tenant_id=tid, client_id=cid, mandate_number=f"M-{mid}",
                           mandate_type="Anlageberatung", opened_at=NOW, created_at=NOW, updated_at=NOW))
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _app_client(session_factory):
    """Ein App-Start je Modul (Lifespan), Daten in der Wegwerf-DB oben."""
    import services.market_data.cache_purge as cache_purge

    mp = pytest.MonkeyPatch()
    # Ein erlaubter Cache-Purge soll nichts loeschen, nur die Rollenpruefung durchlaufen.
    mp.setattr(cache_purge, "run_daily_cache_purge", lambda db: {"run_id": "h180", "status": "ok"})

    def override_db():
        with session_factory() as s:
            yield s

    try:
        with TestClient(app) as c:
            yield c, override_db
    finally:
        mp.undo()


@pytest.fixture()
def client(_app_client):
    c, override_db = _app_client
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _headers(role_key: str) -> dict:
    uid, _role, tid = ROLES[role_key]
    claims = {"sub": uid}
    if tid:
        claims["tid"] = tid
    return {"Authorization": "Bearer " + create_access_token(claims)}


def _call(client, role_key, method, path, body):
    kwargs = {"headers": _headers(role_key)}
    if body is not None:
        kwargs["json"] = body
    return client.request(method, path, **kwargs)


def _denied(resp, scoped: bool) -> bool:
    if resp.status_code in (401, 403):
        return True
    if scoped and resp.status_code == 404:
        detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else ""
        return isinstance(detail, str) and detail in SCOPE_404
    return False


def _cases():
    for action, method, path, body, scoped, row in MATRIX:
        marks = row.split()
        assert len(marks) == len(COLUMNS), action
        for role_key, mark in zip(COLUMNS, marks):
            yield pytest.param(action, method, path, body, scoped, role_key, mark == "A",
                               id=f"{action}|{role_key}")


@pytest.mark.parametrize("action,method,path,body,scoped,role_key,allowed", list(_cases()))
def test_role_rights_matrix(client, action, method, path, body, scoped, role_key, allowed):
    resp = _call(client, role_key, method, path, body)
    assert resp.status_code < 500, f"{action} / {role_key}: Serverfehler {resp.status_code} {resp.text[:300]}"
    if allowed:
        assert not _denied(resp, scoped), (
            f"{action} / {role_key}: erwartet erlaubt, erhalten {resp.status_code} {resp.text[:300]}")
    else:
        assert _denied(resp, scoped), (
            f"{action} / {role_key}: erwartet gesperrt, erhalten {resp.status_code} {resp.text[:300]}")


def test_matrix_detects_denial_and_permission(client):
    """Positiv-/Negativkontrolle des Klassifizierers selbst."""
    assert _denied(_call(client, "advisor", "GET", "/users", None), False)
    assert not _denied(_call(client, "admin", "GET", "/users", None), False)
    assert _denied(_call(client, "advisor2", "GET", "/clients/c-a", None), True)
    assert not _denied(_call(client, "advisor", "GET", "/clients/c-a", None), True)


def test_tenant_separation_firm_b_sees_nothing_of_firm_a(client):
    for role_key in ("admin_b", "advisor_b"):
        listed = _call(client, role_key, "GET", "/clients", None)
        assert listed.status_code == 200
        assert "c-a" not in {c["id"] for c in listed.json()}
        for path in ("/clients/c-a", "/mandates/m-a", "/clients/c-a/wealth-positions",
                     "/mandates/m-a/risk-assessments", "/mandates/m-a/reports/risikoprofil.pdf"):
            resp = _call(client, role_key, "GET", path, None)
            assert _denied(resp, True), f"{role_key} {path}: {resp.status_code} {resp.text[:200]}"
    users_b = _call(client, "admin_b", "GET", "/users", None).json()
    assert {u["id"] for u in users_b}.isdisjoint({uid for uid, _r, tid in ROLES.values() if tid == "t-a"})
    # Gegenprobe: Firma A sieht ihren eigenen Kunden.
    own = _call(client, "admin", "GET", "/clients", None).json()
    assert "c-a" in {c["id"] for c in own} and "c-b" not in {c["id"] for c in own}


def test_advisor_sees_only_own_clients_admin_sees_all_of_firm(client):
    assert {c["id"] for c in _call(client, "advisor", "GET", "/clients", None).json()} == {"c-a"}
    assert {c["id"] for c in _call(client, "advisor2", "GET", "/clients", None).json()} == set()
    # Befund ROL-05 (Owner-Entscheid): readonly und Portfolio Management sehen keine Kunden.
    assert _call(client, "readonly", "GET", "/clients", None).json() == []
    assert _call(client, "pm", "GET", "/clients", None).json() == []


# ---------------------------------------------------------------------------
# Routen-Inventar: keine unbemerkte Abschwaechung
# ---------------------------------------------------------------------------
INVENTORY_FILE = Path(__file__).resolve().parent / "fixtures" / "h180_route_auth_inventory.json"
_IDENTITY_DEPS = {"get_current_user", "get_current_tenant_id"}
# Oeffentliche Routen (ohne Anmeldung) -- abschliessend.
PUBLIC_ROUTES = {
    ("GET", "/"), ("GET", "/health"), ("GET", "/health/live"), ("GET", "/health/ready"), ("GET", "/health/db"),
    ("GET", "/auth/bootstrap-status"), ("POST", "/auth/bootstrap-admin"), ("POST", "/auth/login"),
    ("POST", "/auth/refresh"), ("POST", "/auth/password-reset/request"), ("POST", "/auth/password-reset/confirm"),
    ("GET", "/auth/invite/{token}"), ("POST", "/auth/invite/accept"), ("GET", "/calendar/reviews.ics"),
    ("GET", "/reporting"), ("GET", "/reporting/{full_path:path}"),
}


def _route_auth() -> dict[str, list[str]]:
    from fastapi.routing import APIRoute

    def walk(dependant, acc):
        for dep in dependant.dependencies:
            name = getattr(dep.call, "__name__", "")
            if name.startswith("require_") or name in _IDENTITY_DEPS:
                acc.add(name)
            walk(dep, acc)
        return acc

    out: dict[str, list[str]] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            deps = sorted(walk(route.dependant, set()))
            for method in sorted(route.methods):
                out[f"{method} {route.path}"] = deps
    return out


def test_route_auth_inventory_has_no_unreviewed_weakening():
    """Bekannte Routen behalten ihre Rollen-Dependency (Snapshot); neue Routen
    sind nie oeffentlich und schreiben nie nur mit Anmeldung, ausser sie stehen
    mit Begruendung im Snapshot (``identity_only_writes``). Aktualisieren nur
    nach Pruefung: ``ARES_H180_UPDATE_INVENTORY=1``."""
    import os

    current = _route_auth()
    if os.environ.get("ARES_H180_UPDATE_INVENTORY") == "1":
        previous = json.loads(INVENTORY_FILE.read_text(encoding="utf-8")) if INVENTORY_FILE.exists() else {}
        INVENTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        INVENTORY_FILE.write_text(json.dumps({
            "routes": current,
            "identity_only_writes": previous.get("identity_only_writes", {}),
        }, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    snapshot = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
    known: dict[str, list[str]] = snapshot["routes"]
    identity_only_writes: dict[str, str] = snapshot["identity_only_writes"]
    problems: list[str] = []
    for key, deps in current.items():
        method, path = key.split(" ", 1)
        if not deps and (method, path) not in PUBLIC_ROUTES:
            problems.append(f"neue oeffentliche Route ohne Anmeldung: {key}")
        if key in known:
            if set(known[key]) - set(deps):
                problems.append(f"Rollenpruefung abgeschwaecht: {key} vorher {known[key]}, jetzt {deps}")
        elif method != "GET" and deps and set(deps) <= _IDENTITY_DEPS and key not in identity_only_writes:
            problems.append(f"neue schreibende Route nur mit Anmeldung (Rollenpruefung fehlt): {key}")
    for method, path in PUBLIC_ROUTES:
        assert f"{method} {path}" in current, f"oeffentliche Route verschwunden/umbenannt: {method} {path}"
    assert not problems, "\n".join(problems)


def test_inventory_records_inline_checked_identity_only_writes_with_reason():
    snapshot = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
    for key, reason in snapshot["identity_only_writes"].items():
        assert len(reason) >= 20, f"Begruendung fehlt fuer {key}"
