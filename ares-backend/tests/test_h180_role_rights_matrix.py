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

Paket ROL (H-187, CTO-Entscheide H-180): ROL-03 Kundenportal-Token auf
Mitarbeiter-Routern 403; ROL-04 readonly = firmenweite Lesesicht, jede
Schreibroute 403 ``READONLY_SCOPE`` (isoliert, Sichtbarkeit gegeben, N-926-03);
ROL-05 Freigabe-Inbox; N-926-02 Handler-Rollenpruefungen (``handler_checks``),
GET-Routen nur mit Anmeldung/``require_staff`` (``weak_reads``) und generische
Fremdrollen-Probe.

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
    # ROL-03: Kundenportal-Token auf Mitarbeiter-Routern 403 (statt 200 leer).
    ("Kundenliste lesen", "GET", "/clients", None, False,
     "A A A A A - A - A A"),
    # ROL-04: readonly = firmenweite Lesesicht (Kunden, Mandate, Risikoprofile, PDFs).
    ("Kunde lesen", "GET", "/clients/c-a", None, True,
     "A A - A - - - - - -"),
    ("Mandat lesen", "GET", "/mandates/m-a", None, True,
     "A A - A - - - - - -"),
    ("Kunde anlegen", "POST", "/clients", {}, False,
     "A A A - - - - - A A"),
    ("Kunde aendern", "PUT", "/clients/c-a", {"first_name": "Eva"}, True,
     "A A - - - - - - - -"),
    # Nur das Rollen-Gate (leerer Body -> 422 vor der Sichtbarkeitspruefung im Handler);
    # die Sichtbarkeit belegt die Lesezeile darunter (gleiche Pruefung _get_client_or_404).
    ("KYC-Bestaetigung erfassen (Rollen-Gate)", "POST", "/clients/c-a/kyc-confirmations", {}, False,
     "A A A - - - - - A A"),
    ("KYC-Bestaetigungen lesen", "GET", "/clients/c-a/kyc-confirmations", None, True,
     "A A - A - - - - - -"),
    ("KYC-Zweitfreigabe entscheiden", "POST", "/compliance/kyc-approvals/x/decision", {}, False,
     "A - - - - A A - A -"),
    ("Risikoprofil lesen", "GET", "/mandates/m-a/risk-assessments", None, True,
     "A A - A - - - - - -"),
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
     "A A - A - - - - - -"),
    # ROL-05: Freigabe-Inbox nur fuer die Zweitperson (Admin der Firma, Pruefperson).
    ("Freigabe-Inbox lesen", "GET", "/publication-inbox", None, False,
     "A - - - - A - - A -"),
    ("Freigabe aus der Inbox", "POST", "/publication-inbox/m-a/approve",
     {"target_allocation_id": "x", "validation_hash": "0" * 64}, False,
     "A - - - - A - - A -"),
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
    # ROL-04 (CTO-Entscheid H-180): readonly sieht die ganze eigene Firma (nur
    # lesend), Portfolio Management bleibt ohne Kundensicht.
    ro = {c["id"] for c in _call(client, "readonly", "GET", "/clients", None).json()}
    assert "c-a" in ro and "c-b" not in ro
    assert _denied(_call(client, "readonly", "GET", "/clients/c-b", None), True)
    assert _call(client, "pm", "GET", "/clients", None).json() == []
    # ROL-03: Kundenportal-Token bekommt auf Mitarbeiter-Listen 403 statt [].
    assert _call(client, "client", "GET", "/clients", None).status_code == 403
    assert _call(client, "client", "GET", "/dashboard/summary", None).status_code == 403


# ---------------------------------------------------------------------------
# Routen-Inventar: keine unbemerkte Abschwaechung
# ---------------------------------------------------------------------------
INVENTORY_FILE = Path(__file__).resolve().parent / "fixtures" / "h180_route_auth_inventory.json"
_IDENTITY_DEPS = {"get_current_user", "get_current_tenant_id"}
# N-926-02: ``require_staff`` (seit ROL-03 global an den Mitarbeiter-Routern)
# ist nur "irgendeine Personal-Rolle" -- fuer das Inventar gleich schwach wie
# die blosse Anmeldung. Schreibende Routen mit nur diesen Abhaengigkeiten
# brauchen eine Begruendung UND eine belegte Rollenpruefung im Handler.
_WEAK_DEPS = _IDENTITY_DEPS | {"require_staff"}
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


def _api_routes() -> dict[str, object]:
    from fastapi.routing import APIRoute

    out = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                out[f"{method} {route.path}"] = route
    return out


def _resolve_call(node, scope):
    import ast

    if isinstance(node, ast.Name):
        return scope.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve_call(node.value, scope)
        return getattr(base, node.attr, None) if base is not None else None
    return None


def _handler_reach(func, max_depth: int = 6) -> set[str]:
    """N-926-02 (a): Namen aller Projektfunktionen, die ein Handler (transitiv,
    bis ``max_depth``) aufruft -- statisch per AST ueber die echten Funktions-
    objekte (Modul-Globals), damit eine entfernte Rollenpruefung im Handler oder
    in einem Helfer/Service das Inventar rot macht."""
    import ast
    import inspect
    import textwrap
    import types

    backend = str(BACKEND_ROOT.resolve())
    seen: set[int] = set()
    names: set[str] = set()
    queue = [(func, 0)]
    while queue:
        fn, depth = queue.pop()
        fn = inspect.unwrap(fn)
        if not isinstance(fn, types.FunctionType) or id(fn) in seen:
            continue
        seen.add(id(fn))
        source_file = getattr(fn.__code__, "co_filename", "") or ""
        if not str(Path(source_file).resolve()).startswith(backend):
            continue
        names.add(fn.__name__)
        if depth >= max_depth:
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        except (OSError, TypeError, SyntaxError):
            continue
        scope = dict(fn.__globals__)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = _resolve_call(node.func, scope)
                if target is not None:
                    queue.append((target, depth + 1))
    return names


def _snapshot():
    return json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))


def _weak_get_routes(current: dict[str, list[str]]) -> set[str]:
    return {
        key for key, deps in current.items()
        if key.startswith("GET ") and deps and set(deps) <= _WEAK_DEPS
    }


def test_route_auth_inventory_has_no_unreviewed_weakening():
    """Bekannte Routen behalten ihre Rollen-Dependency (Snapshot); neue Routen
    sind nie oeffentlich und schreiben nie nur mit Anmeldung bzw. nur mit
    ``require_staff``, ausser sie stehen mit Begruendung und belegter
    Handler-Pruefung im Snapshot (``identity_only_writes``/``handler_checks``).
    N-926-02 (b): jede GET-Route mit nur Anmeldung/``require_staff`` steht mit
    Begruendung in ``weak_reads`` -- eine neue ist rot, bis sie geprueft ist
    (Sichtbarkeitspruefung im Handler oder rein interne Personal-Daten).
    Aktualisieren nur nach Pruefung: ``ARES_H180_UPDATE_INVENTORY=1`` (schreibt
    nur ``routes``; Begruendungen werden von Hand gepflegt)."""
    import os

    current = _route_auth()
    if os.environ.get("ARES_H180_UPDATE_INVENTORY") == "1":
        previous = _snapshot() if INVENTORY_FILE.exists() else {}
        INVENTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        # /reporting ist nur mit gebauter Reporting-Sub-App gemountet: bekannte
        # Eintraege bleiben erhalten, auch wenn lokal nicht gebaut.
        reporting = {k: v for k, v in previous.get("routes", {}).items() if k.startswith("GET /reporting")}
        INVENTORY_FILE.write_text(json.dumps({
            "routes": {**reporting, **current},
            "identity_only_writes": previous.get("identity_only_writes", {}),
            "handler_checks": previous.get("handler_checks", {}),
            "weak_reads": previous.get("weak_reads", {}),
        }, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    snapshot = _snapshot()
    known: dict[str, list[str]] = snapshot["routes"]
    identity_only_writes: dict[str, str] = snapshot["identity_only_writes"]
    weak_reads: dict[str, str] = snapshot["weak_reads"]
    problems: list[str] = []
    for key, deps in current.items():
        method, path = key.split(" ", 1)
        if not deps and (method, path) not in PUBLIC_ROUTES:
            problems.append(f"neue oeffentliche Route ohne Anmeldung: {key}")
        if key in known and set(known[key]) - set(deps):
            problems.append(f"Rollenpruefung abgeschwaecht: {key} vorher {known[key]}, jetzt {deps}")
        if method != "GET" and deps and set(deps) <= _WEAK_DEPS and key not in identity_only_writes:
            problems.append(f"schreibende Route ohne Rollen-Dependency und ohne Eintrag: {key}")
    for key in sorted(_weak_get_routes(current) - set(weak_reads)):
        problems.append(f"neue GET-Route nur mit Anmeldung/require_staff (pruefen, eintragen): {key}")
    for key in sorted(set(weak_reads) - _weak_get_routes(current)):
        problems.append(f"veralteter weak_reads-Eintrag (Route weg oder verschaerft): {key}")
    for key in sorted(set(identity_only_writes) - set(current)):
        problems.append(f"veralteter identity_only_writes-Eintrag (Route weg): {key}")
    for method, path in PUBLIC_ROUTES:
        if path.startswith("/reporting"):
            continue  # nur gemountet, wenn die Reporting-Sub-App gebaut ist
        assert f"{method} {path}" in current, f"oeffentliche Route verschwunden/umbenannt: {method} {path}"
    assert not problems, "\n".join(problems)


def test_inventory_records_inline_checked_identity_only_writes_with_reason():
    snapshot = _snapshot()
    for section in ("identity_only_writes", "weak_reads"):
        for key, reason in snapshot[section].items():
            assert len(reason) >= 20, f"Begruendung fehlt fuer {section}/{key}"


def test_handler_role_checks_of_identity_only_writes_are_reached():
    """N-926-02 (a): jede schreibende Ausnahme nennt die Rollenpruefung, die ihr
    Handler (direkt oder ueber Helfer/Service) tatsaechlich aufruft. Fehlt der
    Aufruf -- z. B. ``_require_case_operator`` aus ``_subject_request``
    entfernt --, ist dieser Test rot. Leere Liste nur fuer die Selbstbedienung
    des eigenen Kontos und die zustandslose Steuerschaetzung (Begruendung)."""
    snapshot = _snapshot()
    checks: dict[str, list[str]] = snapshot["handler_checks"]
    routes = _api_routes()
    assert set(checks) == set(snapshot["identity_only_writes"]), (
        "handler_checks und identity_only_writes muessen dieselben Routen fuehren")
    problems = []
    for key, required in checks.items():
        if not required:
            assert key.startswith(("POST /auth/", "PUT /users/{user_id}/password", "POST /tax/estimate")), (
                f"{key}: ohne Handler-Pruefung nur Selbstbedienung/Steuerschaetzung")
            continue
        reached = _handler_reach(routes[key].endpoint)
        missing = [name for name in required if name not in reached]
        if missing:
            problems.append(f"{key}: Rollenpruefung nicht mehr erreicht: {missing}")
    assert not problems, "\n".join(problems)


def test_handler_reach_detects_removed_check():
    """Kontrolle des Werkzeugs: eine Funktion ohne den Aufruf erreicht ihn nicht."""
    def guarded():
        from services.auth import require_admin  # noqa: F401
        return _snapshot()

    reached = _handler_reach(test_handler_role_checks_of_identity_only_writes_are_reached)
    assert "_handler_reach" in reached and "_api_routes" in reached
    assert "_require_case_operator" not in _handler_reach(guarded)


_FOREIGN_PROBE_ROLES = ("advisor2", "pm", "reviewer", "client", "admin_b", "advisor_b")


def _is_data(resp) -> bool:
    if not (200 <= resp.status_code < 300):
        return False
    ctype = resp.headers.get("content-type", "")
    if not ctype.startswith("application/json"):
        return bool(resp.content)
    body = resp.json()
    return body not in ([], {}, None, "")


def test_weak_get_routes_never_return_foreign_client_data(client):
    """N-926-02 (b), generische Probe: jede GET-Route mit nur Anmeldung/
    ``require_staff`` und Kunden-/Mandatsbezug liefert einer fremden Rolle
    (anderer Berater, PM, Pruefperson, Kunde, Firma B) fuer Kunde ``c-a`` bzw.
    Mandat ``m-a`` der Firma A nie 2xx mit Daten."""
    import re

    current = _route_auth()
    leaks = []
    for key in sorted(_weak_get_routes(current)):
        _method, path = key.split(" ", 1)
        if "{client_id}" not in path and "{mandate_id}" not in path:
            continue
        concrete = re.sub(r"\{[^}]+\}", "x", path.replace("{client_id}", "c-a").replace("{mandate_id}", "m-a"))
        for role_key in _FOREIGN_PROBE_ROLES:
            resp = _call(client, role_key, "GET", concrete, None)
            assert resp.status_code < 500, f"{key} / {role_key}: {resp.status_code} {resp.text[:200]}"
            if _is_data(resp):
                leaks.append(f"{key} / {role_key}: {resp.status_code} {resp.text[:120]}")
    assert not leaks, "\n".join(leaks)


# ---------------------------------------------------------------------------
# N-926-03 / ROL-04: isoliertes Rollen-Gate fuer readonly
# ---------------------------------------------------------------------------
_READONLY_SELF_SERVICE = {
    "POST /auth/logout", "POST /auth/refresh", "POST /auth/change-password", "POST /auth/2fa/setup",
    "POST /auth/2fa/enable", "POST /auth/2fa/disable", "POST /auth/2fa/recovery/regenerate",
}


def test_readonly_sees_firm_but_every_write_route_is_denied_by_role(client):
    """readonly sieht Kunde/Mandat der eigenen Firma (Sichtbarkeit greift NICHT),
    damit ist jede Sperre hier allein die Rolle: JEDE nicht lesende Route der App
    (Pfadparameter = sichtbarer Kunde ``c-a``/Mandat ``m-a``) antwortet 403
    ``READONLY_SCOPE`` -- ausser die Selbstbedienung des eigenen Kontos und die
    oeffentlichen Routen."""
    import re

    assert _call(client, "readonly", "GET", "/clients/c-a", None).status_code == 200
    assert _call(client, "readonly", "GET", "/mandates/m-a", None).status_code == 200
    current = _route_auth()
    wrong = []
    for key, deps in sorted(current.items()):
        method, path = key.split(" ", 1)
        if method in ("GET", "HEAD", "OPTIONS") or not deps or key in _READONLY_SELF_SERVICE:
            continue
        concrete = re.sub(r"\{[^}]+\}", "x", path.replace("{client_id}", "c-a").replace("{mandate_id}", "m-a")
                          .replace("{user_id}", "h180-adm"))
        resp = _call(client, "readonly", method, concrete, {})
        detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else None
        code = detail.get("reason_code") if isinstance(detail, dict) else None
        if resp.status_code != 403 or code != "READONLY_SCOPE":
            wrong.append(f"{key}: {resp.status_code} {resp.text[:120]}")
    assert not wrong, "\n".join(wrong)
    # Eigenes Passwort bleibt Selbstbedienung (nicht READONLY_SCOPE).
    own = _call(client, "readonly", "PUT", "/users/h180-ro/password", {})
    assert own.status_code != 403 or "READONLY_SCOPE" not in own.text


def test_readonly_write_with_valid_body_on_visible_client_is_denied(client):
    """Gueltige Minimal-Bodies: die Sperre ist nicht nur eine 422-Folge."""
    cases = [
        ("PUT", "/clients/c-a", {"first_name": "Eva"}),
        ("POST", "/clients", {"client_number": "K-RO-1", "first_name": "Eva", "last_name": "Fiktiv",
                              "data_classification": "synthetic"}),
        ("POST", "/clients/c-a/wealth-positions", DEPOT),
        ("POST", "/clients/c-a/mandates", {"mandate_number": "M-RO-1", "data_classification": "synthetic"}),
    ]
    for method, path, body in cases:
        resp = _call(client, "readonly", method, path, body)
        assert resp.status_code == 403 and "READONLY_SCOPE" in resp.text, f"{method} {path}: {resp.status_code}"
    # Gegenkontrolle (ohne weitere Datensaetze): der Admin derselben Firma kommt durch.
    assert _call(client, "admin", "PUT", "/clients/c-a", {"first_name": "Eva"}).status_code == 200
