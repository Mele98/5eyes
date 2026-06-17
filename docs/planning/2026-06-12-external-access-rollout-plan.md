# Externer Zugriff & Multi-Firma-Rollout — Umsetzungsplan

- **Datum:** 2026-06-12
- **Autor:** Engine/Architektur-Audit (autonom)
- **Baut auf:** ADR-007 (Multi-Tenancy), ADR-009 (3-Tier-Hosting), Memory `project_5eyes_external_access`, `project_5eyes_3_tier_hosting`
- **Status:** Plan zur Freigabe — Implementierung phasenweise

> Ziel des Users: (1) verschiedene **Firmen-Accounts** (Treuhänder/VV) + **interne Mitarbeiter-Accounts** je Firma; (2) **externer Zugriff**, **anfangs nur Operator + Kollegen OHNE Kundendaten**, aber **architektonisch „ready"** für den echten Betrieb; (3) **harte Mandanten-Trennung** als oberste Maxime.

---

## 0. Ausgangslage — was bereits GEBAUT & getestet ist (verifiziert 2026-06-12)

Anders als ADR-007 (das den Single-Tenant-Status-quo hielt) ist das Fundament inzwischen weitgehend gebaut. Verifiziert im Code:

| Baustein | Status | Beleg |
|---|---|---|
| **Tenant-Modell** (`tenants`-Tabelle: tier, license_status, quotas, AVV/FINMA-Audit-Spalten) | ✅ | `models/tenant.py` |
| **`tenant_id`-Spalten** (nullable, BC) auf users/clients/mandates/protocol_bausteine + Runtime-Migration | ✅ | `models/*`, `database.py:176-282`, Default-Tenant „main" `database.py:744-816` |
| **JWT mit `tid`-Claim** + Token-Wandering-Schutz (Token-tid muss zu user.tenant_id passen) | ✅ | `services/auth.py:63-68, 103-112` |
| **Repo-Layer-Scoping** (`_apply_tenant_filter_*`, `get_*_for_user_or_404`, `get_accessible_*_ids`) auf ALLEN datenführenden Routern | ✅ | `services/auth.py:149-246`; clients/mandates/wealth/allocation/profiling/review/… |
| **Cross-Tenant-Leak-Regressionstests** (6 gefundene Leaks gefixt + Repo-Scoping-Tests) | ✅ | `tests/test_tenant_endpoint_leak_regression.py`, `tests/test_repository_tenant_scoping.py` |
| **Rollen**: advisor · admin (Firmen-Admin) · super_admin (Operator) · client (Portal) | ✅ | `services/auth.py:116-146, 308-320` |
| **Tenant-Admin-API** (Tenant anlegen/listen/ändern, User↔Tenant zuweisen) | ✅ | `routers/tenants.py` (require_super_admin + `tenant_admin_ui_enabled`) |
| **Tier-Configs** (`deployment_tier`, `tenancy_mode`, `tenant_admin_ui_enabled`) | ✅ | `config.py:206-218` |
| **Browser-Hosting** (Backend liefert `5eyes_v2.html` same-origin aus) | ✅ gated | `main.py:180-202` `serve_main_frontend` → `/app/5eyes_v2.html` |
| **Client-Portal** (Endkunde read-only, 1:1-Link) | ✅ | `models/client_login.py`, `routers/client_portal.py` |
| **Production-Config-Guards** (CORS ≠ `*`/localhost, secret_key-Pflicht, SQLCipher+Key-Pflicht, Token-Expiry-Cap) | ✅ | `config.py:354-429` |
| **DB-Verschlüsselung** SQLCipher (umschaltbar) | ✅ | `config.py:51`, `database.py:50-60` |

**Fazit:** Die *Isolation* und der *Serving-Mechanismus* existieren. Die offene Arbeit ist **Betrieb (Hosting/TLS/Ops), Härtung fürs offene Internet, Postgres-Skalierung, Daten-Backfill, Provisioning-UI und die Compliance-/Safe-Start-Schicht** — nicht das Tenant-Grundgerüst.

---

## 1. Account-Modell (Firmen, Mitarbeiter, Operator)

```
Operator (du)  = role: super_admin   — über allen Tenants, legt Firmen an
   │
   ├── Tenant "Firma A" (Treuhänder)          ── tenant_id = firm-a
   │     ├── role: admin    (Firmen-Admin)    — verwaltet Mitarbeiter + Mandate der Firma
   │     ├── role: advisor  (Mitarbeiter 1..n)— eigene Kunden/Mandate
   │     └── role: client   (Endkunde 1..n)   — read-only Portal auf EIGENES Mandat
   │
   └── Tenant "Firma B"  …  (vollständig isoliert von Firma A)
```

- **Firma = Tenant.** Eine Firma sieht **nie** Daten einer anderen (harte Trennung, mehrlagig erzwungen — siehe §2).
- **Mitarbeiter = User mit `advisor`** (eigene Kunden) **oder `admin`** (firmenweiter Zugriff innerhalb des Tenants).
- **Operator = `super_admin`** (du): legt Tenants an, weist erste Firmen-Admins zu, setzt Lizenz/Quota. Sieht **bewusst keine** Kundendaten der Firmen (nur Tenant-Metadaten) — sauber für Bankgeheimnis.
- **Endkunde = `client`** (optional, Tier-2-Mehrwert): sieht nur sein eigenes Mandat über das Client-Portal.

**Offen / zu bauen:** Self-Service-Provisioning-UI (heute nur API). Einladungs-/Onboarding-Flow (E-Mail-Invite + erstes Passwort + erzwungenes 2FA-Setup).

---

## 2. Sicherheitsmodell — harte Mandanten-Trennung (oberste Maxime)

**Defense-in-depth, drei unabhängige Schichten** (eine darf versagen, ohne dass Daten lecken):

1. **Auth-Schicht:** JWT `tid`-Claim, Token-Wandering-Schutz (vorhanden). 
2. **Applikations-Schicht:** Repo-Layer-Scoping in jeder Query (vorhanden, leak-getestet).
3. **DB-Schicht (NEU, Ziel):** **Postgres Row-Level-Security** — `CREATE POLICY tenant_isolation` pro Tabelle, `SET app.tenant_id` pro Connection. Damit ist ein vergessenes App-Filter **physisch wirkungslos**. (SQLite kann kein RLS → Treiber für die Postgres-Migration in Tier 2.)

**Weitere Pflicht-Härtung vor echten Daten:**
- `tenant_id` **NOT NULL** + **Backfill** aller Bestandszeilen (heute nullable, „NULL = main"). Ohne Backfill kein Multi-Firma-Echtbetrieb.
- **Per-Tenant-Encryption-Key** (Tier 2), serverseitig at-rest verschlüsselt.
- **Audit-Log tenant-partitioniert** + Streaming (heute nicht partitioniert — Review nötig).
- **Cross-Tenant-Leak-Tests im CI-Gate** (bei jedem PR, nicht nur ad-hoc).
- **Client-Portal:** zusätzlicher expliziter `client.tenant_id == user.tenant_id`-Check (heute implizit über 1:1-Link).

---

## 3. Architektur des externen Zugriffs

```
Browser (Berater, von überall)
   │  HTTPS
   ▼
Cloudflare (TLS, WAF, DDoS, Rate-Limit-Edge)         ← CH-Proxy
   │
   ▼
Reverse Proxy (Caddy/nginx, Let's-Encrypt)           ← CH-VPS (Infomaniak Genf / Exoscale Lausanne)
   │  same-origin
   ▼
FastAPI (uvicorn/gunicorn)  ── serve_main_frontend → /app/5eyes_v2.html  +  /…  API
   │
   ▼
PostgreSQL (RLS, per-tenant key, encrypted-at-rest)  ← CH, automat. Backups + Off-Site-Replikation (CH)
```

- **Ein Host, same-origin:** Frontend (`/app/5eyes_v2.html`) + API auf derselben Origin → kein CORS-Loch nötig.
- **TLS überall**, HSTS, sichere Header (CSP, X-Frame-Options, Referrer-Policy), `app_env=production` (aktiviert die bestehenden Config-Guards).
- **Auth-Härtung fürs Internet:** Login-Guard/Brute-Force (vorhanden) + **2FA/MFA-Pflicht** für advisor/admin + kurze Token-TTL + Refresh + Secret aus Env/Vault (nicht Default).
- **CH-Datenresidenz** (revDSG/Bankgeheimnis): ausschliesslich Schweizer Rechenzentrum.

---

## 4. Phase 0 — sicherer externer Zugriff (nur Operator + Kollegen, OHNE Kundendaten)

**Zweck:** Remote-Zugriff Ende-zu-Ende beweisen — **ohne jegliche echte PII / Bankgeheimnis-Exposition**, aber auf der **echten Ziel-Infrastruktur**, sodass der Sprung zu Echtbetrieb nur noch ein Dat/Compliance-Schritt ist.

**Setup:**
- 1× CH-VPS, `serve_main_frontend=on`, `app_env=staging`, HTTPS via Caddy + Let's Encrypt, Cloudflare davor.
- 2–3 **Demo-Tenants** (`5eyes-internal`, `demo-firma-a`, `demo-firma-b`) mit **ausschliesslich synthetischen** Kunden (wie Leart-Testdaten).
- **Harte Daten-Klassifizierungs-Sperre (NEU):** Setting `allow_real_client_data=false` →
  - blockiert Import/Anlage von als „real" markierten Mandaten,
  - zeigt persistentes „SYNTHETIC / TEST DATA ONLY"-Banner,
  - CI-Test, der sicherstellt, dass die Sperre greift.
  Das ist der technische Garant für „ready, aber sicher".
- **2FA** für die paar Accounts, Audit-Log an, tägliches Backup an.

**Ergebnis von Phase 0:** Du + Kollegen loggt euch **aus dem Browser von überall** in die volle App ein, mit synthetischen Daten, harte Tenant-Trennung live verifiziert — **Infrastruktur ready, Compliance-Exposition = null.**

---

## 5. Rollout-Phasen

| Phase | Inhalt | Vorbedingung | Aufwand (grob) |
|---|---|---|---|
| **E0** | Phase-0 (CH-VPS, TLS, Cloudflare, Demo-Tenants, `allow_real_client_data=false`, 2FA, Backups) | — | 3–5 Tage |
| **E1 — Härtung** | Postgres+RLS-Adapter, `tenant_id` Backfill + NOT NULL, Rate-Limit, Security-Header/CSP, Secret-Management, Monitoring/Alerting | E0 | 5–8 Tage |
| **E2 — Provisioning** | Super-Admin-UI: Firma anlegen, Mitarbeiter einladen (E-Mail-Invite + 2FA-Onboarding), Lizenz/Quota/Status | E1 | 4–6 Tage |
| **E3 — Compliance-Pack** | AVV-Template, DSFA (Operator), FINMA-Outsourcing-Anzeige, Incident-Response-Plan, DR-/Backup-Plan, revDSG/nDSG-Doku | E1 | parallel, 3–5 Tage |
| **E4 — Erste echte Firma** | Tier-2-Pilot mit ECHTEN Daten: Isolation-Re-Audit + externer Pentest, dann `allow_real_client_data=true` nur für diesen Tenant | E2+E3 | 3–4 Tage + Pentest |
| **E5 — Skalierung** | Tier-3-Dedicated-Option, Off-Site-Replikation, SLA/Monitoring-Ausbau | E4 | nach Bedarf |

---

## 6. Konkrete erste Schritte (sprint-ready)

1. **Daten-Klassifizierungs-Sperre** `allow_real_client_data` (Setting + Enforcement + Banner + CI-Test) — *der Phase-0-Enabler.*
2. **`tenant_id`-Backfill-Migration** (alle NULL → „main") + Vorbereitung NOT-NULL (BC-sicher, hinter Flag).
3. **Deployment-Rezept** (Caddyfile + systemd/gunicorn + `.env.staging` mit `app_env=staging`, `serve_main_frontend=on`, gesetztem `secret_key`/`db_key`) → in `docs/`.
4. **2FA (TOTP)** für advisor/admin (Login-Flow-Erweiterung) — Pflicht für externen Zugriff.
5. **CI-Gate:** Cross-Tenant-Leak-Tests bei jedem PR rot/grün.

---

## 7. Offene Entscheidungen (brauche User-Input)

1. **CH-Hosting-Provider:** Infomaniak (Genf) vs. Exoscale (Lausanne) vs. eigener Server? (Kosten/Compliance/Komfort)
2. **DB-Zeitpunkt:** Postgres+RLS schon in E0/E1 — oder Phase 0 noch auf SQLCipher-SQLite (schneller, reicht für wenige interne User)? *Empfehlung: Phase 0 auf SQLite, Postgres in E1 vor echten Daten.*
3. **2FA-Methode:** TOTP-App (Google/Microsoft Authenticator) — ok? (empfohlen, kostenlos, offline)
4. **Domain/Branding:** unter welcher Domain (z.B. `app.5eyes.ch`)?
5. **Pentest:** vor erstem Echt-Tenant (E4) — internes Budget/Anbieter?

---

## 7b. Umsetzungsstand (autonom, 2026-06-12/14)

Seit Planfreigabe umgesetzt + getestet (fokussierte Suites grün; voller Lauf grün nach 2 Test-Anpassungen):

- **§6.1 Daten-Klassifizierungs-Sperre `allow_real_client_data`** — von Codex übernommen (eigener Branch), hier bewusst nicht doppelt gebaut.
- **§6.2 `tenant_id`-Backfill** — `ensure_tenant_backfill()` (NULL→DEFAULT_TENANT_ID für users/clients/mandates/protocol_bausteine), in `init_db()` nach `ensure_default_tenant()`. NOT-NULL bewusst **nicht** als harte DB-Constraint (SQLite-Rebuild-Risiko) — stattdessen **App-Level-Strict-Mode** `strict_tenant_isolation` (Default False): `_apply_tenant_filter_*` filtert hart `==tenant_id` ohne `OR IS NULL`-BC. Create-Inheritance: neue Clients/Mandate/Users erben `tenant_id` des current_user. Tests: `test_tenant_backfill`, `test_strict_tenant_isolation`, `test_*_tenant_inheritance`.
- **§6.3 Deployment-Rezept** — `docs/deploy/` (README, Caddyfile, systemd-Unit, `.env.staging.example`, `promote_operator.py`) + **`docs/deploy/start-external.ps1`**: One-Click-Staging-Backend (APP_ENV=staging, SERVE_MAIN_FRONTEND=true, ALLOW_REAL_CLIENT_DATA=false, STRICT_TENANT_ISOLATION=true, REQUIRE_2FA=true, TENANT_ADMIN_UI_ENABLED=true, stabiles Secret) + Cloudflare-Quick-Tunnel (kein Account, kein Port-Forwarding).
- **§6.4 2FA (TOTP)** — vollständig: `services/totp.py` (RFC 6238, ohne pyotp, gegen RFC-Vektor verifiziert), Login-Gate (`X-2FA-Required`), `/auth/2fa/{status,setup,enable,disable}`. **Pflicht-Hard-Gate** via `require_2fa`: Frontend `enforce2faGate()` (doLogin + Reload) erzwingt Enrollment-Modal mit verstecktem ✕ + gesperrtem Backdrop (`dataset.locked`). Onboarding: `must_change_password` erzwingt PW-Wechsel beim 1. Login. Tests: `test_2fa_login`, `test_totp`, `test_onboarding_password`.
- **Audit-Log mandantengetrennt** (war Voll-Leak) + `shadow-comparison-aggregate` → `require_super_admin`; User-Admin (list/update/reset) tenant-ownership-gated. Tests: `test_audit_log_tenant_scoping`, `test_user_admin_tenant_scoping`.
- **Provisioning + Invite-Link-Onboarding (E2):** `#m-prov`-Modal (super_admin) — Firmen + Mitarbeiter über `/tenants`. Zwei Onboarding-Wege: (a) **Initial-PW** (`/users` + must_change_password=1), (b) **Einladungslink** (`/users/invite` → Account ohne Passwort; Token einmalig, 7 Tage, sha256-gespeichert, tenant-vererbt + assign). Mitarbeiter öffnet `<host>/app/5eyes_v2.html?invite=TOKEN` → Set-Passwort-Maske (`checkInviteParam`) → `/auth/invite/accept` (public, single-use, 404/410) → eingeloggt → 2FA-Hard-Gate erzwingt Enrollment. Tests: `test_invite_onboarding` (8).
- **2FA-QR (segno):** Setup-Modal zeigt QR-Bild + Text-Secret (graceful Fallback ohne Lib).
- **CI-Gate für Mandanten-Trennung & Auth (§6.5):** `scripts/security_gate.py` (Single Source of Truth, 16 Test-Dateien / 99 Tests, `--maxfail=1`) + eigener CI-Job „Security Gate" in `.github/workflows/test.yml` (läuft VOR der Vollsuite, failt PR sofort bei Isolations-Regression). Meta-Test `test_security_gate_manifest` schützt die Liste vor stillem Schrumpfen.

**Noch offen für E1/E2:** Postgres+RLS (DB-Schicht §2.3), E-Mail-Versand der Einladung (heute Link-Copy), firm-admin-eigene Invite-UI (Backend kann's bereits).

## 8. Konsequenzen / Compliance-Hinweise

- Tier 2 (Shared-Cloud) löst **FINMA-Outsourcing-Anzeigepflicht** (RS 2018/3) aus → Template aus ADR-009 liefern.
- **revDSG/nDSG:** AVV zwischen Operator und Firma Pflicht; DSFA für den Operator.
- **Art. 47 BankG (Bankgeheimnis):** Mitigation via Verschlüsselung (at-rest + per-tenant key) + Audit + CH-Residenz; Operator sieht keine Kundendaten.
- **Migrationspfad bleibt offen:** SQLAlchemy ist DB-agnostisch → SQLite→Postgres ohne Code-Fork (nur Settings + RLS-Policies).
