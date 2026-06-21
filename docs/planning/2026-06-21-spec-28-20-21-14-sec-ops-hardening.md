# Spec: Security/Ops-Betriebshärtungs-Cluster (#28, #20, #21, #14)

## Meta

- **Titel:** Session-/Token-TTL+Refresh, Globales Rate-Limiting, Audit-Log tenant-partitioniert + Streaming, Monitoring/Alerting
- **Datum:** 2026-06-21
- **Owner:** Emanuele (Produkt) / Codex (Implementierung)
- **Issue / Link:** Roadmap-Master 2026-06-14 — Punkte #28, #20, #21, #14
- **Branch-Vorschlag:** `codex/u28-token-refresh-ratelimit`
- **Repo:** `C:\5eyes\5eyes_stage9_release_ready\5eyes-backend`
- **Querverweise:**
  - #5 (HttpOnly-Cookie für Token-Storage) → **separate Spec**, hier nur referenziert.
  - U-59 (Bearer-Token-TTL hard cap 1440 min) → `config.py:456-466`.
  - U-7 (CSP/Permissions-Policy) → `core/middleware.py:30-51`.
  - U-63 (Health Readiness/Liveness-Split) → `routers/health.py`.
  - U-64 (Telemetrie-Adapter Sentry opt-in) → `services/telemetry.py`.

---

## Ziel (Gesamtcluster)

Den Betrieb der Plattform für externen/Browser-Zugriff (Tier-2 Shared-Cloud) härten,
ohne die bestehende Tenant-Isolation oder Token-Wandering-Schutz zu schwächen. Vier
Bausteine: (1) kurzlebige Access-Tokens mit rotierendem Refresh-Token, (2) app-seitiges
Rate-Limiting auf allen schreibenden/öffentlichen Endpoints, (3) FINMA-konformes,
tenant-partitioniertes Audit-Log mit SIEM-Export-Stream und Retention pro Tenant,
(4) Monitoring/Alerting-Hooks (Health bereits da, Metriken + Login-Fail-Spike-Alerts
fehlen). Alle vier sind opt-in/config-gated und brechen Tier-1/Electron-Betrieb nicht.

---

## Gemeinsame Leitplanken (gelten für alle 4 Punkte)

- **Keine harten neuen Dependencies.** Stdlib + bereits installierte Pakete
  (`fastapi`, `starlette`, `sqlalchemy`, `python-jose`, `pydantic-settings`). Optionale
  Stacks (Prometheus, Sentry) bleiben Lazy-Import + config-gated wie `services/telemetry.py`.
- **Backwards-Compat Tier-1.** Default-Settings müssen die heutige Electron-Self-Hosted-App
  unverändert lassen (kein Refresh-Zwang, Rate-Limits großzügig, Export-Endpoint admin-only).
- **Tenant-Isolation ist nicht verhandelbar.** Jeder neue Query-Pfad respektiert das
  `strict_tenant_isolation`-Muster aus `services/auth.py:174-180` (Strict = exakter Match,
  BC = Match ODER NULL).
- **Migrations idempotent + additiv.** Spalten/Indizes werden via `ensure_*`-Helfer additiv
  ergänzt (Muster: `services/account_recovery.py:ensure_account_recovery_columns`), kein
  destruktives ALTER, SQLite-kompatibel.
- **Audit-Hash-Chain darf nie brechen.** Änderungen an `services/audit.py` müssen die
  bestehende SHA-256-Chain (`integrity_hash`, `services/audit.py:9-99`) erhalten.

---

# #28 [SEC] Session-/Token-TTL + Refresh

## Ziel

Access-Token-Lebensdauer drastisch verkürzen (Diebstahl-Window klein) und über ein
rotierendes Refresh-Token die UX (kein Re-Login alle 15 min) erhalten. Refresh-Token-
Rotation mit Reuse-Detection schützt gegen gestohlene Refresh-Tokens. Token-Wandering-
Schutz (tenant cross-check) bleibt vollständig erhalten und wird auf das Refresh-Token
ausgeweitet.

## IST (file:line)

- **Access-Token-Erzeugung:** `services/auth.py:29-45` `create_access_token(data, expires_delta)` —
  setzt `exp` (now + `settings.access_token_expire_minutes`) und `iat` (now), encodet HS256.
- **Token-Ausgabe mit Tenant-Claim:** `services/auth.py:64-69` `issue_token_for_user(user)` →
  `create_access_token({"sub": user.id, "tid": tid})`.
- **Default-TTL:** `config.py:65` `access_token_expire_minutes: int = 480` (= 8 h).
- **TTL-Hard-Cap (U-59):** `config.py:456-466` — in `production` Fehler wenn TTL > 1440 (24 h).
- **Validierung + Token-Wandering-Schutz:** `services/auth.py:72-120` `get_current_user`:
  - decodet mit `options={"verify_exp": False}` und prüft `exp` manuell (`:90-94`),
  - lädt User, prüft `is_active`/`deleted_at` (`:101-103`),
  - **Token-Wandering-Schutz:** `:110-113` — wenn `token.tid` und `user.tenant_id` beide
    gesetzt und ungleich → 401.
  - setzt RLS-Tenant-Kontext (`:114-119`).
- **Login:** `routers/auth.py:112-173` `login()` → `_issue_token_response(user)` (`:60-66`).
  Response-Modell `TokenResponse` enthält `access_token` + `user`.
- **Logout:** `routers/auth.py:181-183` — reiner Client-Side-Discard, **kein Server-State**.
- **KEIN Refresh-Token vorhanden.** Grep über `routers/` + `services/` nach `refresh`:
  keine Refresh-Logik, kein Refresh-Endpoint, kein Refresh-Claim, keine Token-Familie/Jti.
- **Token-Storage Frontend:** Bearer im sessionStorage (laut `docs/PENTEST_PREPARATION.md:20-25`,
  `core/middleware.py:17-22`) → HttpOnly-Cookie ist **#5, separate Spec**.

## SOLL-Design

Zwei-Token-Modell:

1. **Access-Token (kurzlebig):** Claim `typ="access"`, TTL aus neuer Setting
   `access_token_ttl_minutes` (Default heute 480 belassen für BC; OWNER-DECISION für
   Tier-2-Default, Vorschlag 15). Behält `sub`, `tid`, `iat`, `exp`. `get_current_user`
   akzeptiert nur `typ in (None, "access")` (None = Legacy-Token BC).
2. **Refresh-Token (langlebig, rotierend):** Claim `typ="refresh"`, zusätzliche Claims
   `jti` (uuid), `fam` (Token-Familie-uuid), `sub`, `tid`. TTL aus
   `refresh_token_ttl_minutes` (Vorschlag 8 h = 480, Tier-2; OWNER-DECISION). Server-seitig
   wird **nur der Hash** des aktiven `jti` + Familie + Status in einer neuen Tabelle
   `refresh_tokens` gehalten (Reuse-Detection + Revocation).

**Rotation + Reuse-Detection (Token-Theft-Schutz):**
- `/auth/refresh` nimmt das Refresh-Token (aus Body — Cookie-Variante kommt mit #5),
  validiert Signatur/exp/`typ=="refresh"`, prüft Token-Wandering (tid-Cross-Check wie
  `get_current_user:110-113`), schlägt nach in `refresh_tokens`:
  - **gültig + aktiv:** alten `jti` als `rotated` markieren, neues Access+Refresh-Paar
    ausgeben, neuen `jti` (gleiche `fam`) speichern.
  - **bereits rotiert (Reuse!):** **gesamte Familie `fam` revoken** (alle aktiven jti),
    401, Audit-Event `TOKEN_REUSE_DETECTED`. Das ist der Kern-Diebstahl-Schutz.
  - **revoked/expired/unbekannt:** 401.
- `login`/`invite_accept`/`bootstrap_admin` geben künftig ein **Token-Paar** zurück
  (neue Familie). BC: `access_token` bleibt im Response, `refresh_token` additiv.
- `logout` revoked die Familie des aktuellen Tokens (Server-State!) → echtes Logout.

**Token-Wandering-Schutz bleibt:** Refresh-Token trägt `tid`; bei Refresh wird `tid` gegen
`user.tenant_id` geprüft (gleiche Logik wie `services/auth.py:110-113`) und in das neue
Access-Token übernommen — kein Tenant-Wechsel über Refresh möglich.

## Konkrete Code-Änderungen

**Neue Datei `services/refresh_tokens.py`:**
```python
# Pseudocode — Stdlib + sqlalchemy + jose
ACCESS = "access"; REFRESH = "refresh"

def create_token_pair(user) -> tuple[str, str, str]:
    """Returns (access_token, refresh_token, family_id). Neue Familie."""
    tid = _resolve_tenant_id_for_user(user)
    fam = new_uuid(); jti = new_uuid()
    access = create_access_token({"sub": user.id, "tid": tid, "typ": ACCESS},
                                timedelta(minutes=settings.access_token_ttl_minutes))
    refresh = create_access_token({"sub": user.id, "tid": tid, "typ": REFRESH,
                                   "jti": jti, "fam": fam},
                                  timedelta(minutes=settings.refresh_token_ttl_minutes))
    return access, refresh, fam, jti  # persist jti/fam by caller

def persist_refresh(db, *, user_id, tid, jti, fam, expires_at): ...  # hash(jti) only
def rotate(db, refresh_token) -> tuple[str, str]:
    payload = _decode_refresh(refresh_token)        # signature+exp+typ==refresh
    _assert_tenant_match(payload, db)               # token-wandering guard
    row = lookup_active(db, hash(payload["jti"]))
    if row is None and family_known(db, payload["fam"]):   # reuse!
        revoke_family(db, payload["fam"]); audit("TOKEN_REUSE_DETECTED"); raise 401
    if row is None: raise 401
    mark_rotated(db, row)
    return issue new pair on same fam
def revoke_family(db, fam): ...
```

**Neues Model (additiv) — `models/refresh_token.py` oder in `models/users.py`:**
```python
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(String, primary_key=True)        # = jti
    jti_hash = Column(String(64), nullable=False, index=True)
    family_id = Column(String, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(String, index=True)       # token-wandering audit
    status = Column(String, nullable=False, default="active")  # active|rotated|revoked
    expires_at = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    rotated_at = Column(String)
    __table_args__ = (Index("ix_refresh_tokens_user_status", "user_id", "status"),)
```
Import in `main.py:18-30` (Model-Registrierung) ergänzen; idempotenter `ensure_*`-Migrationshelfer wie `account_recovery`.

**`config.py` (additiv, im Auth-Block bei `:62-69`):**
```python
access_token_ttl_minutes: int = 480     # BC; Tier-2 OWNER-DECISION (Vorschlag 15)
refresh_token_ttl_minutes: int = 480    # OWNER-DECISION (Vorschlag 480 = 8h)
refresh_token_rotation_enabled: bool = False   # opt-in; Tier-1 bleibt single-token
```
`access_token_expire_minutes` (`:65`) als Alias/Fallback beibehalten (Legacy-Validatoren
`:318-333` + U-59-Cap `:461` weiterhin greifen; neue Felder in `validate_positive_numbers`
aufnehmen, U-59-Cap auch auf `access_token_ttl_minutes` anwenden).

**`services/auth.py`:**
- `create_access_token` (`:29-45`): unverändert (nimmt beliebige Claims).
- `get_current_user` (`:72-120`): nach `exp`-Check (`:94`) hinzufügen:
  `if payload.get("typ") not in (None, "access"): raise credentials_exception`
  (Refresh-Token darf nie als Access-Token gelten).

**`routers/auth.py`:**
- `_issue_token_response` (`:60-66`): auf `create_token_pair` umstellen, beide Tokens
  persistieren + im Response zurückgeben (Schema `TokenResponse` um optionales
  `refresh_token: str | None` erweitern in `schemas/users.py`).
- Neuer Endpoint `@router.post("/refresh", response_model=TokenResponse)` → `rotate(...)`.
- `logout` (`:181-183`): Familie des aktuellen Users revoken.

## Test-Plan (#28)

- Unit: `create_token_pair` setzt `typ`, `jti`, `fam`, korrekte TTLs; `rotate` gibt neues
  Paar gleicher `fam`; Reuse eines rotierten `jti` revoked die Familie + 401.
- API: Login liefert access+refresh; `/auth/refresh` mit gültigem Refresh → neues Paar;
  zweiter Refresh mit altem (rotiertem) Token → 401 + alle Familie-Tokens tot.
- Token-Wandering: Refresh-Token mit `tid=A`, User in DB `tenant_id=B` → 401 (analog
  bestehendem `test_bearer_token_ttl_audit.py`).
- Access-Token als Refresh (`typ=access` an `/auth/refresh`) → 401; Refresh-Token an
  geschütztem Endpoint (`typ=refresh`) → 401.
- BC: `refresh_token_rotation_enabled=False` → Verhalten wie heute (single token,
  Legacy-Token ohne `typ` weiter akzeptiert).
- U-59: `access_token_ttl_minutes > 1440` in production → Settings-ValidationError.

## Edge-Cases (#28)

- Legacy-Token ohne `typ`-Claim: weiter als Access akzeptiert (BC, `:110-113` greift).
- Uhr-Skew: `exp`-Check unverändert manuell (`:90-94`).
- Parallel-Refresh (Race, zwei Tabs): erste rotiert, zweite trifft `rotated` → Reuse-
  Detection würde Familie killen. **Mitigation/OWNER-DECISION:** kurzes Grace-Window
  (z.B. rotiertes Token bleibt 10 s gültig, gibt dasselbe neue Paar zurück) statt sofortigem
  Family-Revoke. Default-Vorschlag: Grace-Window an.
- User deaktiviert/soft-deleted zwischen Login und Refresh: `rotate` lädt User, prüft
  `is_active`/`deleted_at` → 401.
- DB-Wachstum: abgelaufene `refresh_tokens`-Rows per Cleanup-Job purgen (Hook in
  bestehenden Scheduler, analog `backup_scheduler`).

---

# #20 [SEC] Globales Rate-Limiting

## Ziel

App-seitiges Throttling auf **alle** schreibenden (POST/PUT/PATCH/DELETE) und öffentlichen
Endpoints — über die heute punktuell abgesicherten Login/Invite/Reset hinaus — als
Defense-in-Depth gegen Brute-Force, Enumeration, DoS und Mass-Assignment-Fuzzing. Edge
(Cloudflare) bleibt erste Verteidigungslinie; App-Layer schützt auch bei direktem
Backend-Zugriff (Tunnel/intern).

## IST (file:line)

- **Login-Brute-Force-Guard:** `services/login_guard.py` — In-Memory `LoginAttemptGuard`
  (Sliding-Window pro Key, Lockout). Settings `config.py:66-69`
  (`login_rate_limit_enabled`, `login_max_attempts=5`, `login_window_seconds=60`,
  `login_lockout_seconds=600`). Singleton `login_attempt_guard` (`:93`).
- **Punktuell verwendet** (alles über denselben Guard, NICHT global):
  - `/auth/login` `routers/auth.py:114-137`
  - `/auth/password-reset/request` `routers/auth.py:296-303`
  - `/auth/invite/{token}` + `/auth/invite/accept` via `_resolve_invite_guarded`
    `routers/auth.py:493-511`
  - `/users/{id}/invite/resend` `routers/auth.py:662-670`
- **KEIN globales Middleware-Rate-Limit.** Grep nach `slowapi`, `limiter`, `throttle`,
  `RateLimit` im Backend (außer Login-Guard): nichts. `slowapi` ist **nicht** in den
  Dependencies.
- **Schreibende Endpoints ohne Throttling:** alle `clients/mandates/profiling/wealth/
  allocation/review/recommendations/prices/snapshots/market_data/fx_rates/pdf_reports/
  admin-system/tenants/protocol_bausteine/cost_disclosure` POST/PUT/PATCH/DELETE
  (`main.py:117-138`).
- **Request-Context-Middleware vorhanden:** `core/middleware.py:54-110`
  `RequestContextMiddleware` (request_id, Timing, Security-Header) — idealer Ort für ein
  Rate-Limit-Gate; registriert in `main.py:107`.
- **Client-IP-Auflösung** existiert bereits robust: `routers/auth.py:69-77`
  `_login_guard_key` (X-Forwarded-For first hop → `request.client.host`).

## SOLL-Design

In-Memory **Per-Route-Bucket Rate-Limiter** als eigene Middleware (kein neues Paket),
wiederverwendet das bewährte Sliding-Window-Muster aus `login_guard.py`. Vier Bucket-Klassen
mit eigenen Schwellen (OWNER-DECISION für Werte):

| Bucket | Geltungsbereich | Vorschlag (req/Fenster) |
|---|---|---|
| `auth` | öffentliche Auth-/Invite-/Reset-Pfade | 10 / 60 s (zusätzlich zum Login-Guard) |
| `write` | alle POST/PUT/PATCH/DELETE (authentifiziert) | 120 / 60 s pro User |
| `read` | GET (authentifiziert) | 600 / 60 s pro User (sehr großzügig) |
| `public` | sonstige unauth. GET (health ausgenommen) | 60 / 60 s pro IP |

- **Key:** authentifiziert → `sub`+`tid` aus Token (Decode ohne DB, analog
  `get_current_tenant_id:268-306`); unauth. → Client-IP (`_login_guard_key`-Logik
  extrahiert in geteilten Helfer `core/client_ip.py`).
- **Bucket-Zuordnung** per HTTP-Methode + Pfad-Präfix; `/health*` und statische Mounts
  (`/reporting`, `/app`) **ausgenommen** (Liveness/Readiness dürfen nie 429en).
- **429 + `Retry-After`-Header** + `X-RateLimit-*`-Header, deutsche Detail-Message
  (konsistent mit Login-Guard).
- **Config-gated:** `rate_limit_enabled` Default **False** in Tier-1 (Electron lokal),
  True empfohlen Tier-2. Schwellen pro Bucket als Settings.
- **Login-Guard bleibt unverändert** (engerer, account-spezifischer Brute-Force-Schutz)
  — die globale Middleware ist additiv, nicht ersetzend.

## Konkrete Code-Änderungen

**Neue Datei `core/rate_limit.py`:**
```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not settings.rate_limit_enabled: return await call_next(request)
        if _is_exempt(request.url.path): return await call_next(request)  # /health,/app,/reporting
        bucket, key = _classify(request)          # (auth|write|read|public, sub|ip)
        decision = _windows[bucket].check_and_register(key)  # sliding window like login_guard
        if not decision.allowed:
            return JSONResponse(status_code=429,
                content={"detail": "Zu viele Anfragen. Bitte später erneut.",
                         "request_id": getattr(request.state,"request_id",None)},
                headers={"Retry-After": str(decision.retry_after_seconds),
                         "X-RateLimit-Limit": str(decision.limit),
                         "X-RateLimit-Remaining": str(decision.remaining)})
        return await call_next(request)
```
Wiederverwendet ein generalisiertes Sliding-Window (gleiche `deque`-Mechanik wie
`login_guard.py:30-85`), parametrisiert pro Bucket.

**`core/client_ip.py` (neu):** `client_ip(request)` aus `routers/auth.py:69-77` extrahiert
(dort dann importieren — aber `auth.py` editiert Codex, nicht diese Spec-Phase; Helfer ist
additiv und kann von beiden genutzt werden).

**`config.py` (additiv):**
```python
rate_limit_enabled: bool = False
rate_limit_auth_max: int = 10;   rate_limit_auth_window_s: int = 60
rate_limit_write_max: int = 120; rate_limit_write_window_s: int = 60
rate_limit_read_max: int = 600;  rate_limit_read_window_s: int = 60
rate_limit_public_max: int = 60; rate_limit_public_window_s: int = 60
rate_limit_trust_forwarded_for: bool = True   # hinter Cloudflare/Proxy
```

**`main.py:107`** (Reihenfolge): `RateLimitMiddleware` **vor** `RequestContextMiddleware`
hinzufügen, damit request_id schon gesetzt ist? — Nein: Starlette ruft zuletzt
hinzugefügte Middleware zuerst. RateLimit soll request_id im 429-Body haben → daher
RateLimit **nach** RequestContext registrieren (= läuft innerhalb). Konkret: nach `:107`
`app.add_middleware(RateLimitMiddleware)`.

**Cloudflare-Edge-Hinweis (Doku-Block in der Spec / Runbook, kein Code):**
- Cloudflare-Rate-Limiting-Rule auf `/auth/*` (z.B. 20 req/min/IP) + WAF-Managed-Rules
  als erste Schicht.
- `CF-Connecting-IP` als vertrauenswürdige Client-IP-Quelle (vor X-Forwarded-For) wenn
  hinter Cloudflare → optional in `client_ip()` berücksichtigen (OWNER-DECISION ob CF im
  Einsatz).
- App-Layer-Limit ist Defense-in-Depth für Tunnel-/Direktzugriff ohne Edge.

## Test-Plan (#20)

- Unit: Sliding-Window pro Bucket (N erlaubt, N+1 → 429 + Retry-After); Fenster-Reset.
- API: 121 schnelle POSTs als ein User → letzte 429; GETs bis 600 ok; `/health/live`
  nie 429 (Exempt); `/health/ready` nie 429.
- Key-Trennung: zwei verschiedene User/IPs teilen sich keinen Bucket.
- BC: `rate_limit_enabled=False` → kein 429 (Tier-1).
- Forwarded-For: Spoofing-Schutz — nur first hop, `trust_forwarded_for=False` ⇒ nur
  `request.client.host`.

## Edge-Cases (#20)

- In-Memory-State ist **pro Prozess** — bei Multi-Worker (Tier-2 uvicorn `--workers>1`)
  ist das Limit pro Worker. OWNER-DECISION: Tier-2 single-worker ODER später Redis-Backend
  (für jetzt dokumentieren; Cloudflare deckt globales Limit ab).
- Health-/Static-Exempt-Liste muss `/`, `/health`, `/health/*`, `/app`, `/reporting`,
  `/docs`, `/openapi.json` enthalten.
- OPTIONS-Preflight (CORS) nie limitieren.
- Memory-Leak-Schutz: Buckets periodisch von leeren Keys bereinigen (wie
  `login_guard._cleanup:30-42`).

---

# #21 [FINMA] Audit-Log tenant-partitioniert + Streaming

## Ziel

Das Audit-Log mandantenfähig machen (tenant_id-Spalte + Index, Hash-Chain **pro Tenant**),
einen optionalen Export-Stream für SIEM bereitstellen (NDJSON, append-only, ab Cursor) und
eine Retention-Policy pro Tenant ermöglichen — unter Wahrung der FINMA-10-Jahres-
Aufbewahrung und der Integritäts-Hash-Chain.

## IST (file:line)

- **Audit-Model:** `models/review.py:328-343` `class AuditLog` — Spalten: `id, user_id,
  user_name, table_name, record_id, action, field_name, old_value, new_value, mandate_id,
  client_id, integrity_hash(64), created_at`. **KEINE `tenant_id`-Spalte. KEIN Index.**
- **Schreib-Service:** `services/audit.py:44-101` `log(...)` — baut SHA-256 Hash-Chain:
  `previous_entry` = **global** letzter Eintrag (`:60-64`, `order_by created_at desc, id desc`),
  `integrity_hash` über Payload inkl. `previous_hash` (`:69-84`). **Chain ist global, nicht
  tenant-partitioniert.** Kein `db.commit()` (Caller committet).
- **Hash-Payload-Felder:** `services/audit.py:9-41` `_audit_integrity_payload` — enthält
  **kein** tenant_id.
- **Audit-Log-Viewer-Endpoint:** `routers/system.py:74-130` `GET /admin/system/audit-log`
  (admin-only). Tenant-Scope heute **indirekt** über accessible client/mandate IDs
  (`:85-99`) — explizit kommentiert: *"audit_log hat keine tenant_id -> Scope ueber
  accessible IDs"* (`:87`). Pagination, Action-Filter, Suche.
- **Schreib-Aufrufer:** ~25 `audit_log(...)`/`log(...)`-Calls über `routers/auth.py` +
  `routers/system.py` (Grep), keiner übergibt tenant_id.
- **Tenant-Modell:** `models/tenant.py:55-94` (`tenant_id` als String, `DEFAULT_TENANT_ID="main"`
  `:52`). Retention-relevante Felder existieren bereits für Lizenz, aber **keine
  audit_retention-Setting**.
- **AdvisoryLog** (`models/review.py:57-137`) hat bereits `retain_until` (`:124`,
  entry+10y) + eigene Hash-Chain — Vorbild-Muster für Retention.

## SOLL-Design

1. **tenant_id-Spalte + Index** auf `audit_log` (additiv, nullable für BC). Backfill: aus
   `mandate_id`/`client_id` → Tenant ableiten wo möglich, sonst `DEFAULT_TENANT_ID`.
2. **Hash-Chain pro Tenant:** `previous_entry`-Query in `services/audit.py:60-64` um
   `filter(AuditLog.tenant_id == tid)` erweitern; tenant_id in `_audit_integrity_payload`
   aufnehmen (am Ende anhängen → Reihenfolge-Kompatibilität für Altdaten via Migrations-
   Marker; siehe Edge-Cases). Jeder Tenant hat eine eigene, unabhängige, lückenlose Kette.
3. **`tenant_id` als Pflicht-Parameter** in `services.audit.log(...)` (Default ableitbar
   aus mandate/client/current_user — Helfer `_resolve_audit_tenant`). Alle ~25 Caller
   ergänzen tid (aus `current_user.tenant_id`).
4. **SIEM-Export-Stream:** neuer Endpoint `GET /admin/system/audit-log/export` →
   `StreamingResponse` NDJSON, ab `since`-Cursor (created_at oder Sequenz), tenant-scoped,
   admin-only (super_admin: alle/parametrisierbar). Append-only, deterministisch sortiert
   (`created_at asc, id asc`). Optional: `format=ndjson|csv`. Liefert `integrity_hash` mit,
   damit SIEM die Kette extern verifizieren kann.
5. **Retention pro Tenant:** Setting/Tenant-Feld `audit_retention_days` (Default 3650 =
   10 Jahre, FINMA-Minimum — **darf nie unterschritten werden**). Cleanup-Job (Scheduler-
   Hook) löscht ausschließlich Einträge **älter als** Retention **und** über FINMA-Minimum.
   Löschung selbst wird auditiert (Aktion `AUDIT_RETENTION_PURGE`). Hash-Chain-Bruch durch
   Löschung wird via „Sealing"-Eintrag (Hash des gelöschten Segments) dokumentiert
   (OWNER-DECISION: Sealing vs. nie-löschen).

## Konkrete Code-Änderungen

**`models/review.py` `AuditLog` (`:328-343`) additiv:**
```python
    tenant_id = Column(String)   # FINMA: tenant-partitionierte Hash-Chain
    __table_args__ = (
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_log_tenant_action", "tenant_id", "action"),
    )
```
Idempotenter `ensure_audit_log_tenant_column(db)` (Muster `account_recovery`), in
`init_db`/Startup aufgerufen; Backfill-Skript unter `scripts/`.

**`services/audit.py`:**
- `log(...)` Signatur (`:44-57`): `tenant_id: str | None = None` ergänzen; falls None →
  `_resolve_audit_tenant(mandate_id, client_id, db)` (lookup Mandate/Client.tenant_id,
  sonst `DEFAULT_TENANT_ID`).
- `previous_entry` (`:60-64`): `.filter(AuditLog.tenant_id == tid)`.
- `_audit_integrity_payload` (`:9-41`): `tenant_id` als letztes Feld anhängen.
- `entry = AuditLog(... tenant_id=tid ...)` (`:85-98`).

**`routers/system.py`:**
- `get_audit_log` (`:74-130`): Tenant-Scope auf `AuditLog.tenant_id` umstellen (direkter,
  performanter als accessible-IDs-Subquery `:90-99`); BC/Strict-Muster wie `auth.py:174-180`.
  Super_admin: optional `tenant_id`-Query-Param.
- Neuer Endpoint:
```python
@router.get('/audit-log/export')
def export_audit_log(since: str | None = None, fmt: str = "ndjson",
                     db=Depends(get_db), current_user=Depends(require_admin)):
    tid = _scope_tenant(current_user)             # super_admin -> param/all
    q = (db.query(AuditLog).filter(AuditLog.tenant_id == tid)
         .order_by(AuditLog.created_at.asc(), AuditLog.id.asc()))
    if since: q = q.filter(AuditLog.created_at > since)
    def gen():
        for e in q.yield_per(500):
            yield json.dumps(_serialize(e), ensure_ascii=False) + "\n"
    audit_log(db, ..., action="EXPORT", tenant_id=tid); db.commit()
    return StreamingResponse(gen(), media_type="application/x-ndjson")
```
- `'AUDIT_RETENTION_PURGE'` + `'EXPORT'` (existiert) in `AUDIT_LOG_VALID_ACTIONS`
  (`:37-52`) ergänzen.

**`config.py` (additiv):** `audit_retention_days: int = 3650` (Validator: `>= 3650`,
FINMA-Minimum); `audit_retention_purge_enabled: bool = False`.

**Retention-Job:** Funktion in `services/audit.py` (`purge_expired_audit(db, tenant_id)`),
Scheduler-Hook analog `backup_scheduler`.

## Test-Plan (#21)

- Migration: `ensure_audit_log_tenant_column` idempotent (zweimal aufrufbar), Index existiert.
- Hash-Chain pro Tenant: Einträge für tid=A und tid=B verschränkt schreiben → jede Kette
  für sich verifizierbar (jeder `integrity_hash` == sha256(payload mit prev_hash desselben
  Tenants)); Cross-Tenant beeinflusst Hash nicht.
- Export: NDJSON parsebar, ab `since` korrekt, nur eigener Tenant; super_admin sieht alle.
- Tenant-Scope: Firmen-Admin A sieht keine B-Einträge (Viewer + Export).
- Retention: Eintrag < 10 Jahre wird NIE gelöscht; Validator lehnt
  `audit_retention_days < 3650` ab; Purge schreibt `AUDIT_RETENTION_PURGE`.
- BC: Altdaten ohne tenant_id (NULL) bleiben im Viewer für super_admin sichtbar; Backfill
  setzt `main`.

## Edge-Cases (#21)

- **Hash-Chain-Verifikation Altdaten:** Bestehende `integrity_hash` wurden OHNE tenant_id
  im Payload berechnet. Neue Payload-Variante darf Altdaten nicht „brechen". Lösung:
  Verifier kennt zwei Payload-Formate (pre-/post-#21) anhand eines Migrations-Cutoff-
  Timestamps; neue Einträge nutzen das neue Format. **OWNER-DECISION** bestätigen.
- Eintrag ohne ableitbaren Tenant (System-Aktion ohne client/mandate, z.B. Market-Data-
  Refresh): `DEFAULT_TENANT_ID="main"` → landet in main-Kette.
- Export großer Logs: `StreamingResponse` + `yield_per` verhindert Memory-Spike.
- Concurrency: `log()` committet nicht selbst (`:101`) — Chain-Konsistenz hängt an
  serialisierten Writes; bei Multi-Worker OWNER-DECISION zu DB-Lock/Single-Writer für
  Audit (heute SQLite single-file ⇒ unkritisch; PostgreSQL Tier-2 ⇒ `SELECT ... FOR UPDATE`
  auf letzten Tenant-Eintrag).

---

# #14 [OPS] Monitoring/Alerting

## Ziel

Betriebs-Observability bereitstellen: Metriken-Endpoint (Fehlerquoten, Latenz, Request-
Counts), strukturierte Alert-Events für Login-Fail-Spikes und Fehlerquoten, Aufsetzen auf
die vorhandene request_id-Logaggregation und die Health-Probes. Stack-Wahl bleibt opt-in
(Prometheus-Scrape ODER nur strukturierte Log-Events).

## IST (file:line)

- **Health-Endpoints (U-63):** `routers/health.py` — `/health` (`:40-44`), `/health/live`
  (`:47-55`, kein DB-Hit), `/health/ready` (`:58-86`, DB-Check → 503), `/health/db`
  (`:89-93`). Zusätzlich Root `/` (`main.py:205-215`).
- **request_id + Timing-Middleware:** `core/middleware.py:54-110`
  `RequestContextMiddleware` — generiert/propagiert `X-Request-ID` (`:56`), misst
  `duration_ms` (`:79`), setzt `X-Process-Time-Ms` (`:81`), loggt strukturiert
  „Request completed | request_id=… method=… path=… status=… duration_ms=…" (`:102-109`)
  und Exceptions (`:64-70`). **Aber: keine Aggregation/Counter, kein Metrics-Export.**
- **Telemetrie-Adapter (U-64):** `services/telemetry.py` — Sentry opt-in, Lazy-Import,
  `configure_telemetry()`, `capture_exception`, `capture_message`. **NICHT in `main.py`
  Lifespan (`:59-98`) verdrahtet und NICHT in der Middleware-Exception-Behandlung
  (`core/middleware.py:62-70`) aufgerufen.**
- **Webhook-Notifier (Markdaten):** `config.py:136-138` `market_data_alert_webhook_url` —
  existiert nur für Validation-Alerts, nicht generisch.
- **Login-Fail-Logging:** `routers/auth.py:129-135` `logger.warning("Login failed | …
  request_id=…")` — vorhanden, aber **kein Spike-Alert** (Aggregation fehlt).
- **Log-Rotation:** `config.py:44-45,60` + `core/logging_setup.py` (RotatingFileHandler).

## SOLL-Design

1. **In-Process-Metriken-Sammler** (`services/metrics.py`, stdlib, thread-safe): zählt pro
   `(method, path-template, status_class)` Request-Count, Error-Count (5xx/4xx getrennt),
   Latenz-Histogramm (Buckets), Login-Fail-Counter, Token-Reuse-Counter, Rate-Limit-429-
   Counter. Gespeist aus `RequestContextMiddleware` (Hook nach `:107`) — kein Code-
   Duplikat, nur ein `metrics.observe(...)`-Call.
2. **`GET /admin/system/metrics`** (admin-only): JSON-Snapshot (immer verfügbar) — Fehler-
   quoten, p50/p95/p99-Latenz, Top-Fehler-Pfade, Login-Fails letzte N min.
3. **Optional Prometheus:** `GET /metrics` im OpenMetrics-Textformat, **nur** wenn
   `metrics_prometheus_enabled=True` (Lazy, kein neues Pflicht-Paket — eigenes Text-
   Rendering aus dem Sammler, kein `prometheus_client`-Zwang). Exempt vom Rate-Limit (#20).
4. **Alert-Events (strukturierte Logs + optional Webhook/Sentry):**
   - **Login-Fail-Spike:** Schwelle `alert_login_fail_threshold` pro
     `alert_login_fail_window_s` global/pro IP → `logger.error("ALERT login_fail_spike …")`
     + `telemetry.capture_message(level="error")` + optional Webhook.
   - **Error-Rate-Spike:** 5xx-Quote über Schwelle in Fenster → gleicher Alert-Pfad.
   - **Latenz-Spike:** p95 > Schwelle → Alert.
   - **Token-Reuse (#28):** sofort-Alert (Sicherheits-kritisch).
5. **Telemetrie verdrahten:** `configure_telemetry()` in `main.py`-Lifespan (`:62`)
   aufrufen; `capture_exception` im Middleware-`except` (`core/middleware.py:62-70`)
   ergänzen (so kommen unhandled 500er an Sentry, mit request_id-Kontext).
6. **Logaggregation:** request_id ist bereits in jeder Log-Zeile → Doku-Runbook
   (Empfehlung: Loki/CloudWatch/ELK, Filter auf `ALERT `-Prefix + `request_id`).

## Konkrete Code-Änderungen

**Neue Datei `services/metrics.py`:**
```python
class MetricsRegistry:
    def observe_request(self, method, path_template, status, duration_ms): ...
    def observe_login_fail(self, key): ...     # feeds spike detector
    def observe_rate_limit(self): ...
    def observe_token_reuse(self): ...
    def snapshot(self) -> dict: ...            # counts, error_rate, p50/p95/p99
    def render_prometheus(self) -> str: ...    # OpenMetrics text
metrics = MetricsRegistry()                    # singleton, thread-safe (Lock)
```

**Neue Datei `services/alerts.py`:**
```python
def maybe_alert_login_fail_spike(key): ...     # sliding window like login_guard
def maybe_alert_error_rate(): ...
def _emit(kind, detail):
    logger.error("ALERT %s | %s", kind, detail)
    telemetry.capture_message(f"ALERT {kind}: {detail}", level="error")
    _post_webhook_if_configured(kind, detail)  # settings.alert_webhook_url
```

**`core/middleware.py`:**
- nach `:107` (response da, duration berechnet): `metrics.observe_request(request.method,
  request.scope.get("route").path if route else request.url.path, response.status_code,
  duration_ms)` + `alerts.maybe_alert_error_rate()` (günstig, gated).
- im `except` (`:62-70`): `telemetry.capture_exception(exc, context={"request_id": …,
  "path": …})`.
- Path-Template (nicht raw path) nutzen, damit `/clients/{id}` nicht kardinalitäts-
  explodiert.

**`routers/auth.py`** (Codex-Edit, additiv): nach `register_failure` (`:128`)
`metrics.observe_login_fail(guard_key); alerts.maybe_alert_login_fail_spike(guard_key)`.

**`routers/system.py`:** `GET /admin/system/metrics` (`metrics.snapshot()`).
**`main.py`:** optional `@app.get("/metrics")` (gated) → `metrics.render_prometheus()`;
`configure_telemetry()` in Lifespan (`:62`); ggf. eigener Router. `/metrics` + `/admin/
system/metrics` in Rate-Limit-Exempt (#20).

**`config.py` (additiv):**
```python
metrics_enabled: bool = True
metrics_prometheus_enabled: bool = False
alert_webhook_url: str = ''            # generisch (separat von market_data_*)
alert_login_fail_threshold: int = 20
alert_login_fail_window_s: int = 300
alert_error_rate_threshold: float = 0.10   # 10% 5xx im Fenster
alert_error_rate_window_s: int = 300
alert_latency_p95_ms: int = 2000
```

## Test-Plan (#14)

- Unit: `MetricsRegistry` zählt Requests/Errors korrekt; p50/p95/p99 plausibel;
  `render_prometheus` valides OpenMetrics-Format.
- API: `/admin/system/metrics` admin-only (403 ohne Admin), liefert Snapshot;
  `/metrics` 404 wenn `metrics_prometheus_enabled=False`, 200 sonst, Rate-Limit-exempt.
- Health: `/health/live` ohne DB 200; `/health/ready` 503 bei DB-Down (bestehender
  `test_health_readiness_liveness_split.py` bleibt grün).
- Alert: > threshold Login-Fails in Fenster → genau ein `ALERT login_fail_spike`-Log;
  unter threshold → kein Alert.
- Telemetrie: unhandled Exception → `capture_exception` aufgerufen (mit request_id im
  context); ohne DSN no-op (bestehender `test_telemetry_opt_in.py` bleibt grün).

## Edge-Cases (#14)

- Metriken pro Prozess (Multi-Worker Tier-2): Prometheus scraped jeden Worker einzeln
  (multiprocess-Mode dokumentieren) oder Aggregation am Edge.
- Path-Kardinalität: immer Route-Template, nie roher Pfad mit IDs/Query.
- Alert-Sturm-Schutz: pro Alert-Art Cooldown (z.B. max. 1 Alert/Art/5 min).
- `/metrics` darf nie PII enthalten (nur Counter/Pfad-Templates).
- DB-Outage: `/health/ready` 503, aber `/admin/system/metrics` (kein DB-Hit) muss weiter
  antworten, damit Monitoring während Outage funktioniert.

---

## Betroffene Module / Dateien (Gesamt)

- **Neu:** `services/refresh_tokens.py`, `models/refresh_token.py`, `core/rate_limit.py`,
  `core/client_ip.py`, `services/metrics.py`, `services/alerts.py`, `scripts/backfill_audit_tenant.py`.
- **Editiert (Codex):** `config.py`, `services/auth.py`, `services/audit.py`,
  `models/review.py`, `routers/auth.py`, `routers/system.py`, `routers/health.py`
  (ggf. nur Doku), `core/middleware.py`, `main.py`, `schemas/users.py`, `schemas/review.py`.
- **Tests:** neue Dateien in `tests/` pro Punkt (siehe Test-Pläne).

## Akzeptanzkriterien (Gesamt)

1. `/auth/refresh` rotiert Token-Paar; Reuse eines rotierten Refresh-Tokens revoked die
   Familie + 401; Token-Wandering-Schutz greift auf Refresh-Token.
2. Mit `rate_limit_enabled=True` liefern überzogene Schreib-/Auth-Requests 429+Retry-After;
   `/health*` nie 429.
3. `audit_log` hat tenant_id+Index; Hash-Chain ist pro Tenant lückenlos verifizierbar;
   `/admin/system/audit-log/export` streamt tenant-scoped NDJSON; Retention < 10 Jahre wird
   abgelehnt.
4. `/admin/system/metrics` liefert Fehlerquoten/Latenz; Login-Fail-Spike erzeugt
   strukturiertes `ALERT`-Event; unhandled 500 → `capture_exception`.
5. Alle Defaults lassen Tier-1/Electron unverändert (alle neuen Schalter opt-in/BC).
6. Bestehende Tests bleiben grün (`test_bearer_token_ttl_audit.py`, `test_login_guard.py`,
   `test_health_readiness_liveness_split.py`, `test_telemetry_opt_in.py`,
   `test_csp_security_headers.py`).

## OWNER-DECISIONs

- **#28 TTL-Werte:** Access-Token-TTL Tier-2 (Vorschlag **15 min**; Tier-1 bleibt 480),
  Refresh-Token-TTL (Vorschlag **480 min/8 h**). Soll `refresh_token_rotation_enabled` in
  Tier-2 default True sein?
- **#28 Parallel-Refresh:** Grace-Window (Vorschlag **10 s**) gegen Reuse-False-Positive
  bei Multi-Tab — ja/nein?
- **#20 Rate-Limit-Schwellen:** Werte je Bucket (auth 10/60s, write 120/60s, read 600/60s,
  public 60/60s) — bestätigen/anpassen. In Tier-2 default aktivieren? Cloudflare im Einsatz
  (→ `CF-Connecting-IP` als IP-Quelle)?
- **#21 Retention-Dauer:** Default **3650 Tage (10 Jahre)** als FINMA-Minimum-Floor; längere
  pro Tenant erlaubt? Bei Löschung: **Sealing-Eintrag** vs. **nie löschen** (nur Archiv-
  Export)? Legacy-Hash-Format-Cutoff (zwei Payload-Varianten) bestätigen.
- **#14 Monitoring-Stack-Wahl:** Nur strukturierte Log-Events + `/admin/system/metrics`
  JSON, ODER zusätzlich Prometheus `/metrics`? Sentry (U-64) für Tier-2 aktivieren? Alert-
  Ziel: Log/Loki, Webhook (Slack/Teams) oder beides?
- **Multi-Worker (alle Punkte):** Tier-2 single-worker (In-Memory-State korrekt) ODER
  Redis/DB-Backend für Rate-Limit + Metriken einplanen?

## Risiken

- Refresh-Reuse-Detection kann bei aggressivem Multi-Tab False-Positives erzeugen
  (Mitigation: Grace-Window).
- Audit-Hash-Payload-Änderung gefährdet Verifikation von Altdaten (Mitigation: Format-
  Cutoff + Zwei-Format-Verifier).
- In-Memory-Rate-Limit/Metriken sind pro Prozess — bei Multi-Worker inkonsistent.
- Rate-Limiting zu eng → legitime Berater-Workflows (Bulk-Edits) blockiert (großzügige
  write-Schwelle + Tier-1 default off).
