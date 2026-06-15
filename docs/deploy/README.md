# Phase-0 Deployment — externer Zugriff (Staging, nur synthetische Daten)

Ziel: die volle App im Browser von überall erreichbar, für Operator + Kollegen,
**ohne echte Kundendaten** (technisch via `allow_real_client_data=false` erzwungen,
Banner sichtbar). CH-Datenresidenz. Siehe `docs/planning/2026-06-12-external-access-rollout-plan.md`.

---

## 🚀 Schnellster Weg — von DEINEM PC (Quick-Tunnel, kein Server, kein Port-Forwarding)

Du willst dich extern einloggen, während es auf deinem Windows-PC läuft? **Ein Befehl:**

```powershell
# Vorher die normale Electron-App schliessen (sonst DB-Konflikt).
.\docs\deploy\start-external.ps1
```

Das Skript:
1. startet das Backend im **Staging-/Browser-Hosting-Modus** auf `127.0.0.1:8000`
   (stabiles Login-Secret in `~/5eyes/.external-secret.txt`, `allow_real_client_data=false`),
2. lädt einmalig **cloudflared** und öffnet einen **HTTPS-Quick-Tunnel** (kein Account).

Es erscheint eine URL `https://<zufall>.trycloudflare.com`. **Extern (Handy/anderer PC) öffnen mit `/app/5eyes_v2.html` dahinter:**

```
https://<zufall>.trycloudflare.com/app/5eyes_v2.html
```

→ Login wie gewohnt (inkl. 2FA, falls aktiviert). **Verifiziert:** Backend serviert die volle
App (1.4 MB) same-origin, `/auth/login` antwortet korrekt (401 bei falschen Credentials).

**Sicherheit Phase-0:** zufällige unguessbare URL · Login + Brute-Force-Guard + optional 2FA ·
nur synthetische Daten (Banner). Beenden: Tunnel-Fenster Strg+C, Backend-Fenster schliessen.
Für Dauerbetrieb/CH-Residenz später der VPS-Weg unten.

### Firmen & Mitarbeiter anlegen (Operator)
Das Provisioning (Firmen = Tenants + Mitarbeiter-Accounts) ist im Topbar-Button **„Firmen"**
— sichtbar nur für die Operator-Rolle **`super_admin`**. Einmalig dich zum Operator machen:

```powershell
# normale App vorher schliessen (DB-Lock), dann:
python docs\deploy\promote_operator.py <dein-username>
```

Danach neu einloggen → Button **„Firmen"** → Firma anlegen, Mitarbeiter anlegen & zuweisen.
Mitarbeiter erben automatisch den Firmen-`tenant_id` (harte Trennung). Das Start-Skript
`start-external.ps1` aktiviert dafür `TENANT_ADMIN_UI_ENABLED=true` + `tenancy_mode=multi`.

---

## Zielbild
```
Browser ──HTTPS──> Cloudflare (optional, WAF/DDoS) ──> Caddy (TLS, Reverse-Proxy)
                                                          └─> uvicorn (127.0.0.1:8000)
                                                                └─> SQLite (SQLCipher) — Phase-0
```
- **Ein Host, same-origin:** Caddy serviert `app.5eyes.ch`; FastAPI liefert Frontend (`/app/5eyes_v2.html`) **und** API auf derselben Origin → kein CORS-Loch.
- **Phase-0 DB:** SQLCipher-SQLite (reicht für wenige interne User). Postgres+RLS erst in E1 vor echten Daten.

## Voraussetzungen
- CH-VPS (Empfehlung: **Infomaniak** Genf oder **Exoscale** Lausanne), Ubuntu 22.04+, Python 3.11+.
- DNS: `app.5eyes.ch` → VPS-IP (A/AAAA). (Optional Cloudflare-Proxy „orange cloud".)
- Offene Ports: 80/443 (Caddy). Backend NUR auf 127.0.0.1 (nicht öffentlich).

## Schritte
1. **Code + venv**
   ```bash
   git clone <repo> /opt/5eyes && cd /opt/5eyes/5eyes-backend
   python3 -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   pip install gunicorn uvicorn
   ```
2. **Env-Datei** (siehe `.env.staging.example`): nach `/opt/5eyes/5eyes-backend/.env` kopieren und
   **`secret_key` + `db_key` mit echten Zufallswerten** füllen:
   ```bash
   python3 -c "import secrets;print('SECRET_KEY='+secrets.token_urlsafe(48))"
   python3 -c "import secrets;print('DB_KEY='+secrets.token_urlsafe(32))"
   ```
3. **Backend als Service** (`5eyes.service` → `/etc/systemd/system/`):
   ```bash
   sudo cp docs/deploy/5eyes.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now 5eyes
   sudo systemctl status 5eyes
   ```
4. **Caddy (Auto-TLS)** (`Caddyfile` → `/etc/caddy/Caddyfile`, Domain anpassen):
   ```bash
   sudo apt install -y caddy
   sudo cp docs/deploy/Caddyfile /etc/caddy/Caddyfile
   sudo systemctl reload caddy
   ```
5. **Demo-Tenants + Operator** anlegen (Super-Admin) und je 1 synthetischen Kunden (wie Leart).
6. **Smoke-Test:** `https://app.5eyes.ch/` → JSON mit `"allow_real_client_data": false`.
   `https://app.5eyes.ch/app/5eyes_v2.html` → App lädt, **gelbes Banner sichtbar**.

## Sicherheits-Checkliste Phase-0
- [ ] `app_env=staging`, `secret_key` ≠ Default, `db_use_sqlcipher=true` + `db_key` gesetzt.
- [ ] `allow_real_client_data=false` (Banner muss erscheinen).
- [ ] `cors_origins` enthält NUR `https://app.5eyes.ch` (kein `*`, kein localhost).
- [ ] Backend lauscht NUR auf 127.0.0.1 (`app_host=127.0.0.1`); öffentlich nur Caddy.
- [ ] 2FA (kommt in E1) — bis dahin: starke Passwörter + wenige Accounts.
- [ ] Tägliches verschlüsseltes Backup der `.db` + Off-Site (CH).
- [ ] Login-Rate-Limit aktiv (`login_rate_limit_enabled=true`, Default).

## E1 (nächste Stufe, vor echten Daten)
Postgres+RLS, `tenant_id` NOT NULL + Backfill, 2FA-Pflicht, Security-Header/CSP,
Secret-Vault, Monitoring/Alerting, Compliance-Pack (AVV/DSFA/FINMA-Outsourcing).
