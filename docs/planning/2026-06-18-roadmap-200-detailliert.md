# 5eyes — Detaillierte Master-Roadmap (200 Punkte, „Fleisch am Knochen")

- **Datum:** 2026-06-18
- **Zweck:** Jeder Punkt mit **Ziel/Was**, **Können (Verhalten/Anforderung)**, **Umsetzung (wie, Dateien)**, **Verknüpft mit**, **Definition of Done (DoD/Test)**.
- **Methodik:** überlegen → planen → umsetzen → prüfen+testen → anpassen.
- **Status:** [ ] offen · [~] in Arbeit · [✓] erledigt · [⏸] wartet auf User-Entscheid
- **Skala:** 🔴 blockierend · 🟠 hoch · 🟡 mittel · 🟢 nice-to-have

---

## TEIL 0 — Holistisches Denkmodell (das „verknüpfte Denken")

### 0.1 Die drei Produkt-Wahrheiten, an denen alles hängt
1. **Harte Mandanten-Trennung ist die oberste Maxime.** Jede Architekturentscheidung wird daran gemessen. Ein Datenleck zwischen Firmen ist existenzbedrohend (Bankgeheimnis Art. 47 BankG, revDSG). → Treibt: RLS (#34), per-Tenant-Key (#37), CI-Leak-Gate (#169), Pentest (#73).
2. **„Ready, aber sicher": extern testbar OHNE Compliance-Exposition.** Die Daten-Klassifizierungs-Sperre (`allow_real_client_data=false`) ist der technische Garant. Sie entkoppelt *Infrastruktur-Reife* von *Daten-Reife* → wir können extern testen, lange bevor wir echte Daten dürfen.
3. **Fachliche Korrektheit vor UX-Glanz.** Die Engine produziert FINMA-relevante Zahlen. Erst korrekt (Engine/3eyes-Parität, Determinismus, Tests), dann schön. „Solche Sachen sind verdammt gefährlich" (User) = jede falsche Kurve ist ein Haftungsrisiko.

### 0.2 Der kritische Pfad (was blockiert was)
```
                       ┌─────────────────────────────────────────────┐
                       │  allow_real_client_data=false (GEBAUT) ✅     │
                       └───────────────┬─────────────────────────────┘
                                       │ entkoppelt Infra von Daten
            ┌──────────────────────────┴───────────────────────────┐
            ▼                                                        ▼
   A: Extern testen (Quick-Tunnel)                        G: Engine-Korrektheit
   → SOFORT, synth. Daten                                 (läuft parallel, kein Infra-Block)
            │                                                        │
            ▼                                                        │
   B: CH-VPS stabil (E0)                                             │
            │                                                        │
            ▼                                                        │
   C: Härtung (Postgres+RLS, Secrets, Rate-Limit) ◄── Voraussetzung für ECHTE Daten
            │                                                        │
            ├──────────────┐                                        │
            ▼              ▼                                         │
   D: Provisioning   E: Compliance (AVV/DSFA/FINMA — Docs ✅,       │
   (Self-Service)        rechtl. Prüfung offen)                     │
            │              │                                         │
            └──────┬───────┘                                        │
                   ▼                                                 │
   F: Pentest → erster Echt-Tenant (allow_real_client_data=true gated)
                   │                                                 │
                   └────────────────► PRODUKTIV ◄───────────────────┘
```
**Lesart:** A ist sofort offen (kein Block). C ist das Nadelöhr vor echten Daten (RLS = DB-Schicht der Trennung). G (Engine) läuft unabhängig parallel — kein Infra-Block, aber Voraussetzung für *Vertrauen* in die Zahlen.

### 0.3 Architektur-Schichten (wo greift welche Anforderung)
| Schicht | Verantwortung | Trennungs-Mechanismus | offene Härtung |
|---|---|---|---|
| Edge (Cloudflare) | TLS, WAF, DDoS, Rate-Limit | — | #24, #41 |
| Reverse Proxy (Caddy) | TLS-Term, Header, same-origin | — | #22, #27 |
| App (FastAPI) | AuthN/Z, Repo-Scoping | JWT `tid` + `_apply_tenant_filter_*` (✅) | #39, #40 |
| Daten (Postgres) | Persistenz | **RLS-Policy (offen!)** | #33–#37 |
| Krypto | at-rest | SQLCipher (✅) → per-Tenant-Key | #37 |

**Verknüpfung:** Solange die DB-Schicht (RLS) fehlt, ruht die Trennung auf 2 statt 3 Säulen — für synthetische Daten ok (A/B), für echte Daten NICHT (deshalb C vor F).

### 0.4 Leitprinzipien für jede Aufgabe
- **Determinismus:** gleiche Eingabe → gleiche Zahl (Seeds, gerundete Reihenfolge). Test pflicht bei Engine-Änderungen.
- **Additiv & rückwärtskompatibel:** neue Felder nullable, Defaults sicher, alte Daten funktionieren weiter.
- **Konservativ bei Unsicherheit:** tieferer Renditewert, höhere Kostenschätzung, strengere Reserve.
- **Keine Dritt-Marken** (Swiss Life/3eyes) in Code/PDF/Texten.
- **Branch-Hygiene:** `git branch --show-current` vor jedem Commit (Dual-Agent mit Codex).
- **Monolith-Snapshot** nach jedem HTML-Edit regenerieren (`audit_html_monolith.py`).

---

## A. EXTERNER ZUGRIFF PHASE 0 — sofort testbar (synthetische Daten) (1–18)

> **Holistik:** Diese Phase beweist den *Remote-Zugriff Ende-zu-Ende auf der echten App* — ohne PII. Sie ist der schnellste Vertrauensgewinn und liefert Kollegen-Feedback, das die Priorisierung von G/J schärft.

### [ ] 1. 🔴 Quick-Tunnel-Erststart + Remote-Login beweisen
- **Ziel:** Du loggst dich vom Handy/fremden Netz in die volle App ein.
- **Können:** App über HTTPS-URL erreichbar, Login + 2FA funktioniert, Mandant ladbar, Strategie rechenbar — alles remote.
- **Umsetzung:** `docs/deploy/start-external.ps1` ausführen (setzt APP_ENV=staging, SERVE_MAIN_FRONTEND=true, ALLOW_REAL_CLIENT_DATA=false, STRICT_TENANT_ISOLATION=true, REQUIRE_2FA=true + Cloudflare-Quick-Tunnel). URL aus Konsole an Handy.
- **Verknüpft:** Voraussetzung für #5–#7; nutzt #3 (Sperre), #6 (2FA).
- **DoD:** Login + ein voller Strategielauf von einem Gerät ausserhalb des LAN; Screenshot.

### [ ] 2. 🔴 Demo-Tenants mit ausschliesslich synthetischen Kunden
- **Ziel:** 2–3 isolierte Firmen-Sandboxes (`5eyes-internal`, `demo-firma-a`, `demo-firma-b`).
- **Können:** Jeder Tenant hat eigene Berater + synthetische Mandanten; keine Überschneidung sichtbar.
- **Umsetzung:** `routers/tenants.py` (super_admin) Tenants anlegen; Seed-Skript für synthetische Personas (analog Leart-Stil, klar als TEST markiert).
- **Verknüpft:** #7 (Trennungstest), #17 (Reset-Skript), #184 (Klassifizierung).
- **DoD:** 3 Tenants in DB, je ≥2 synthetische Mandanten; Audit-Log zeigt saubere tenant_id.

### [ ] 3. 🔴 `allow_real_client_data=false` blockt echte Mandate — verifizieren
- **Ziel:** Technischer Garant „keine echten Daten im Test".
- **Können:** Anlegen/Import eines als „real" markierten Mandats wird hart abgelehnt; Banner „SYNTHETIC / TEST DATA ONLY" persistent sichtbar.
- **Umsetzung:** Setting (Codex gebaut) + Enforcement-Pfad prüfen; manueller Negativtest + CI-Test.
- **Verknüpft:** #75 (späteres gezieltes true), #184.
- **DoD:** Negativtest schlägt fehl wie erwartet; CI-Test grün; Banner sichtbar.

### [ ] 4. 🟠 „TEST DATA ONLY"-Banner UX
- **Ziel:** Kein Berater verwechselt Test mit Echtbetrieb.
- **Können:** Banner immer sichtbar (oben fixiert), farblich eindeutig, nicht wegklickbar im Staging.
- **Umsetzung:** FE-Header-Element gated an `app_env`/Setting.
- **DoD:** Banner auf jeder Seite sichtbar; verschwindet nur bei `allow_real_client_data=true`.

### [ ] 5. 🟠 Kollegen-Accounts + Invite-Link je Demo-Tenant
- **Ziel:** Kollegen onboarden ohne manuelle Passwort-Weitergabe.
- **Können:** Operator lädt per Link ein → Kollege setzt PW → 2FA-Pflicht greift.
- **Umsetzung:** `/users/invite` (Token 7 Tage, single-use, sha256, tenant-vererbt) → `?invite=TOKEN` → `checkInviteParam` → `/auth/invite/accept`.
- **Verknüpft:** #6, #53 (E-Mail-Versand), #54 (firm-admin invite).
- **DoD:** Kollege ist eingeloggt, in korrektem Tenant, mit aktivem 2FA.

### [ ] 6. 🟠 2FA-Enrollment mit echtem Authenticator
- **Ziel:** Pflicht-2FA für advisor/admin extern.
- **Können:** QR scannen (segno) → Code → enrolled; Recovery-Codes einmalig angezeigt.
- **Umsetzung:** `services/totp.py`, Hard-Gate `enforce2faGate()`, `/auth/2fa/*`, Recovery via `account_recovery.py`.
- **Verknüpft:** #25 (Recovery), #28 (Token-TTL).
- **DoD:** Login ohne 2FA blockiert; Recovery-Code-Login funktioniert single-use.

### [ ] 7. 🟠 Cross-Tenant-Trennung LIVE beweisen
- **Ziel:** Firma A sieht NICHTS von Firma B — sichtbar demonstriert.
- **Können:** Als A-Advisor: Mandanten-/Audit-/User-Listen enthalten nur A; B-IDs liefern 404.
- **Umsetzung:** manuelle Tests + `test_tenant_endpoint_leak_regression`, `test_strict_tenant_isolation` als Beleg.
- **Verknüpft:** #34 (RLS verstärkt das), #169 (CI-Gate).
- **DoD:** Dokumentierter Test (jede datenführende Route) zeigt 0 Fremdzugriff.

### [ ] 8. 🟡 Stabile Tunnel-URL (Named Tunnel)
- **Ziel:** URL ändert sich nicht bei jedem Start (Quick-Tunnel ist ephemer).
- **Können:** Feste Subdomain für die Testphase.
- **Umsetzung:** Cloudflare Named Tunnel (benötigt Account) ODER Übergang zu #19 (VPS).
- **DoD:** gleiche URL über mehrere Tage.

### [ ] 9. 🟡 Tägliches Backup + Restore-Test im Staging
- **Ziel:** Kein Datenverlust der Test-Konfiguration.
- **Können:** Automatisches verschlüsseltes Backup; getesteter Restore.
- **Umsetzung:** `backup_scheduler.py` (läuft) + manueller Restore-Drill.
- **Verknüpft:** #15, #44 (Off-Site), #68 (DR-Plan).
- **DoD:** Backup-Datei vorhanden; Restore in leere DB erfolgreich.

### [ ] 10. 🟡 Audit-Log im Staging prüfen
- **Ziel:** Nachvollziehbarkeit aller Zugriffe.
- **Können:** Logins, Mandats-Zugriffe, Admin-Aktionen mit tenant_id + request_id.
- **Verknüpft:** #21 (Partitionierung), #43.
- **DoD:** Stichprobe zeigt vollständige, tenant-korrekte Einträge.

### [ ] 11. 🟡 Browser-Kompatibilität Smoke (Chrome/Edge/Safari)
- **Ziel:** Kollegen nutzen verschiedene Browser.
- **Können:** Charts, Modals, PDF-Vorschau funktionieren überall.
- **DoD:** Checkliste je Browser grün.

### [ ] 12. 🟢 Mobile/Tablet grobe Darstellung
- **DoD:** Hauptseiten lesbar, kein Layout-Bruch.

### [ ] 13. 🟠 Kollegen-Kurzanleitung (1 Seite)
- **Ziel:** Reibungsloser Start ohne Rückfragen.
- **Können:** Login → 2FA → Demo-Mandant → Strategie → SOLL/IST in ≤10 Schritten.
- **DoD:** PDF/MD an Kollegen verteilt.

### [ ] 14. 🟡 Logout/Session-Ablauf testen
- **Verknüpft:** #28, #40.
- **DoD:** Token-Ablauf erzwingt Re-Login; Logout invalidiert FE-State.

### [ ] 15. 🟡 Passwort-vergessen-Flow im Staging
- **Können:** `/auth/password-reset/request|confirm` (Token 2h, single-use) + FE-Maske.
- **Verknüpft:** #26 (SMTP), #27 (✅ Code).
- **DoD:** Reset per Link funktioniert (oder Link-Copy ohne SMTP).

### [ ] 16. 🟠 Feedback-Kanal für Kollegen
- **Ziel:** Bugs/Wünsche strukturiert sammeln.
- **DoD:** Kanal (Issue-Liste/Sheet) + Triage-Routine.

### [ ] 17. 🟡 „Demo-Daten reset"-Skript
- **Ziel:** Saubere Sandbox per Knopfdruck.
- **Können:** Löscht synthetische Mandanten, lässt Tenants/User stehen.
- **Verknüpft:** #186.
- **DoD:** Skript läuft idempotent; Audit zeigt 0 Orphans danach.

### [ ] 18. 🟢 Demo-Personas realistischer (CH-Profile)
- **DoD:** ≥5 Personas (Akkumulation, Verzehr, Immobilien-lastig, Paar, Selbständig).

---

## B. E0 STABIL — CH-VPS Dauerbetrieb (19–32)

> **Holistik:** Der Übergang von ephemer (Quick-Tunnel) zu fest. Hier wird die *Ziel-Infrastruktur* real — danach ist der Sprung zu Echtbetrieb nur noch Daten+Compliance (C–F).

### [⏸] 19. 🟠 CH-Hosting-Provider entscheiden
- **Ziel:** CH-Datenresidenz (revDSG/Bankgeheimnis).
- **Optionen:** Infomaniak (Genf) · Exoscale (Lausanne) · eigener Server. Kriterien: Managed-Postgres, Kosten, ISO-27001, Standort.
- **Verknüpft:** #33 (Postgres), #95 Compliance. **Wartet auf dich.**

### [⏸] 20. 🟠 Domain + Branding-Entscheid
- **Ziel:** z.B. `app.5eyes.ch`.
- **Verknüpft:** #27 TLS, #59 Branding. **Wartet auf dich.**

### [ ] 21. 🟠 VPS-Grundhärtung
- **Können:** SSH-Key-only, Firewall (nur 443/22), Auto-Updates, fail2ban.
- **DoD:** Port-Scan zeigt nur 443; root-Login deaktiviert.

### [ ] 22. 🟠 Caddy + Let's-Encrypt
- **Umsetzung:** `docs/deploy/Caddyfile`; same-origin (Frontend `/app` + API).
- **DoD:** A+ bei SSL-Labs; Auto-Renewal.

### [ ] 23. 🟠 systemd-Service + Auto-Restart
- **Umsetzung:** `docs/deploy/5eyes.service`; gunicorn/uvicorn workers.
- **DoD:** Reboot → App automatisch online; Crash → Restart.

### [ ] 24. 🟠 Cloudflare (WAF/DDoS/Rate-Limit-Edge)
- **Verknüpft:** #41.
- **DoD:** WAF-Regeln aktiv; Rate-Limit auf Login/Invite.

### [ ] 25. 🟠 `app_env=production` Guards scharf
- **Können:** CORS ≠ *, Secret-Pflicht, SQLCipher+Key-Pflicht, Token-Cap (Guards vorhanden in `config.py:354-429`).
- **DoD:** Start ohne gesetztes Secret/Key schlägt fehl (gewollt).

### [ ] 26. 🟠 Secrets gesetzt (nie Default)
- **Verknüpft:** #42 (Vault).
- **DoD:** SECRET_KEY/DB_KEY aus Env; Guard akzeptiert keine Defaults.

### [ ] 27. 🟡 Security-Header verifizieren
- **Können:** HSTS, CSP, X-Frame-Options, Referrer-Policy.
- **DoD:** securityheaders.com ≥ A.

### [ ] 28. 🟡 Health-Endpoint + externes Uptime-Monitoring
- **Verknüpft:** #45.
- **DoD:** `/health` (DB+Scheduler-Status) + externer Ping-Alert.

### [ ] 29. 🟡 Log-Rotation + zentrale Logs
- **DoD:** Logs rotiert, durchsuchbar nach request_id/tenant_id.

### [ ] 30. 🟡 Staging↔Prod getrennt
- **DoD:** zwei Umgebungen, getrennte DB/Secrets/Domain.

### [ ] 31. 🟢 Wartungsseite
### [ ] 32. 🟢 Deploy-Skript/CD (push→deploy mit grüner Suite als Gate)

---

## C. E1 HÄRTUNG — DB & Security vor Echtdaten (33–52)

> **Holistik:** Das Nadelöhr. Erst wenn die DB-Schicht der Trennung steht (RLS), dürfen echte Daten rein. Jede Aufgabe hier ist ein „muss" vor F.

### [ ] 33. 🔴 Postgres-Adapter verifizieren
- **Ziel:** DB-agnostisch (SQLite-Dev → Postgres-Prod) ohne Code-Fork.
- **Können:** `DATABASE_URL` schaltet Dialekt; SQLite-spezifisches (ensure_runtime_columns, PRAGMA, sqlite3.backup) hinter Dialekt-Switch; gleiche Tests grün auf beiden.
- **Umsetzung:** SQLAlchemy-Dialekt-Erkennung; Migrations-Pfad Alembic erwägen.
- **Verknüpft:** #34–#37 bauen darauf; #38 Test-Matrix.
- **DoD:** Voll-Suite grün gegen Postgres-Container.

### [ ] 34. 🔴 Row-Level-Security-Policies
- **Ziel:** Vergessenes App-Filter wird *physisch* wirkungslos.
- **Können:** Pro mandantenführender Tabelle `CREATE POLICY tenant_isolation USING (tenant_id = current_setting('app.tenant_id')::uuid)`.
- **Verknüpft:** #35 (Session-Var), #33 (Postgres), #74 (Re-Audit).
- **DoD:** Test: Query ohne App-Filter liefert via RLS trotzdem 0 Fremdzeilen.

### [ ] 35. 🔴 `SET app.tenant_id` pro Connection
- **Ziel:** RLS kennt den aktiven Tenant je Request.
- **Umsetzung:** Request-Middleware/Session-Hook setzt `app.tenant_id` aus JWT `tid`; reset bei Connection-Rückgabe (Pool-Sicherheit!).
- **Verknüpft:** #34, #52 (Pooling).
- **DoD:** Test: zwei parallele Requests verschiedener Tenants leaken nicht über den Pool.

### [ ] 36. 🔴 `tenant_id` NOT NULL nach Backfill
- **Umsetzung:** `ensure_tenant_backfill()` (NULL→main, ✅) → unter Postgres `ALTER … SET NOT NULL`.
- **Verknüpft:** #33.
- **DoD:** Constraint aktiv; Insert ohne tenant_id schlägt fehl.

### [ ] 37. 🟠 Per-Tenant-Encryption-Key (at-rest)
- **Ziel:** Bankgeheimnis-Mitigation.
- **Können:** Master-KEK → per-Tenant-DEK; PII-Felder/DB at-rest verschlüsselt; Key-Rotation dokumentiert.
- **Verknüpft:** #11, #95.
- **DoD:** Key-Hierarchie dokumentiert; Rotation getestet.

### [ ] 38. 🟠 Test-Matrix SQLite+Postgres im CI
- **DoD:** beide grün bei jedem PR.

### [ ] 39. 🟠 HttpOnly-Cookie statt JWT in localStorage
- **Ziel:** XSS-Token-Diebstahl verhindern.
- **Können:** Token in HttpOnly+Secure+SameSite-Cookie; CSRF-Token-Pattern; FE-API-Layer umgestellt.
- **Risiko:** Breaking-Change → eigener Sprint mit Migrationspfad.
- **Verknüpft:** #40.
- **DoD:** kein Token mehr in localStorage; CSRF-Test grün.

### [ ] 40. 🟠 Kurze Access-Token-TTL + Refresh-Rotation
- **Verknüpft:** #28, #39; Token-Wandering-Schutz beibehalten.
- **DoD:** abgelaufener Access-Token → Refresh; gestohlener Refresh erkennbar (Rotation).

### [ ] 41. 🟠 Globales Rate-Limiting (Edge + App)
- **Können:** alle schreibenden/öffentlichen Endpoints (über Login/Invite hinaus).
- **DoD:** Lasttest zeigt Drosselung; legit Nutzung unbeeinträchtigt.

### [ ] 42. 🟠 Secret-Management (Vault/verschlüsselte Env) + Rotation
- **DoD:** kein Klartext-Secret auf Platte; Rotation ohne Downtime.

### [ ] 43. 🟡 Audit-Log tenant-partitioniert + Retention (+SIEM-Stream)
- **DoD:** Partition/Index pro Tenant; Retention-Policy aktiv.

### [ ] 44. 🟡 Off-Site-Backup-Replikation (2. CH-RZ)
- **Verknüpft:** #9, #68.
- **DoD:** verschlüsselte Off-Site-Kopie + Restore-Drill dokumentiert.

### [ ] 45. 🟡 Monitoring/Alerting
- **Können:** Fehlerquote, Latenz, Login-Fail-Spikes, DB-Health.
- **DoD:** Alert feuert im Testfall.

### [ ] 46. 🟡 Brute-Force/Account-Lockout schärfen
- **DoD:** N Fehlversuche → temporäre Sperre + Audit-Eintrag.

### [ ] 47. 🟡 Lizenz-/Quota-Enforcement
- **Können:** `tenants.quotas` (max User/Mandate) als Soft/Hard-Limit + Hinweis-UI.
- **DoD:** Überschreiten blockiert/warnt korrekt.

### [ ] 48. 🟡 Client-Portal Tenant-Check im RLS-Modell doppeln
- **DoD:** `client.tenant_id==user.tenant_id` + RLS greifen beide.

### [ ] 49. 🟢 Dependency-/CVE-Scan (pip-audit) im CI
### [ ] 50. 🟢 SBOM/Lizenz-Audit
### [ ] 51. 🟢 Secrets-Scan im CI
### [ ] 52. 🟢 Postgres-Pooling/Tuning (verknüpft #35: Reset der Session-Var!)

---

## D. E2 PROVISIONING & SELF-SERVICE (53–63)

> **Holistik:** Skaliert den Betrieb von „Operator klickt API" zu „Firmen verwalten sich selbst". Ohne D bleibt jeder neue Kunde Handarbeit.

### [⏸] 53. 🟠 E-Mail-Versand der Einladung aktiv
- **Können:** Invite verschickt echte Mail (Code fertig `services/mailer.py`).
- **Umsetzung:** SMTP-Zugang in Env/`start-external.ps1`.
- **DoD:** Test-Invite landet im Postfach. **Wartet auf SMTP-Zugang.**

### [ ] 54. 🟠 Firm-Admin-eigene Invite-UI
- **Ziel:** Firma lädt eigene Mitarbeiter ein (Operator nicht im Loop).
- **Umsetzung:** Backend kann's; FE-Maske für role=admin freischalten (tenant-gescoped).
- **DoD:** Firm-Admin lädt Mitarbeiter NUR im eigenen Tenant ein.

### [ ] 55. 🟡 Operator-Provisioning-UI ausbauen
- **Können:** Firma anlegen, Status (aktiv/suspendiert), Quota, Tier setzen — alles in `#m-prov`.
- **DoD:** Voller Tenant-Lebenszyklus ohne API-Tool.

### [ ] 56. 🟡 Invite-Lebenszyklus-UI (Resend/Revoke)
- **DoD:** abgelaufene/zurückgezogene Invites klar sichtbar + steuerbar.

### [ ] 57. 🟡 Tenant-Offboarding (revDSG-Export + Löschung)
- **Verknüpft:** #187/#188.
- **DoD:** Export-Paket + harte Löschung mit Audit.

### [ ] 58. 🟡 Rollen-/Rechte-Matrix-UI
- **DoD:** advisor/admin/super_admin/client transparent + änderbar.

### [ ] 59. 🟢 Mandanten-Branding pro Firma (Logo/Farben)
### [ ] 60. 🟢 Mehrsprachigkeit FE (DE/FR/IT/EN — Felder existieren)
### [ ] 61. 🟢 Benutzer-Aktivitätsübersicht je Firma
### [ ] 62. 🟢 Bulk-User-Import (CSV)
### [ ] 63. 🟢 API-Keys/Service-Accounts

---

## E. E3 COMPLIANCE (64–72)

> **Holistik:** Tier 2 (Shared-Cloud) löst FINMA-Outsourcing-Anzeigepflicht aus; revDSG verlangt AVV+DSFA. Docs sind erstellt — offen ist die *rechtliche Prüfung* + Betriebsprozesse.

### [✓] 64–68 AVV · FINMA-Outsourcing · DSFA · Provisioning-Runbook · DR-Plan (Docs erstellt 2026-06-15)
### [ ] 69. 🟠 Incident-Response-Plan (Daten-Leak-Szenario + Meldepflichten EDÖB/FINMA)
- **DoD:** Eskalationskette, Fristen, Kommunikationsvorlagen.
### [⏸] 70. 🟠 revDSG/nDSG-Doku anwaltlich prüfen lassen
### [ ] 71. 🟡 Retention-/Löschkonzept je Datentyp
### [ ] 72. 🟡 Verarbeitungsverzeichnis (Art. 12 revDSG)

---

## F. E4 ECHT-TENANT + PENTEST (73–78)

> **Holistik:** Der Gate zwischen „Test" und „Produktiv". `allow_real_client_data` wird NUR hier, NUR für den Pilot, auf true gesetzt — nach bestandenem Pentest.

### [⏸] 73. 🔴 Externer Pentest
- **Fokus:** Auth, Tenant-Isolation, öffentliche Endpoints (Invite/Reset/Portal).
- **DoD:** Bericht; kritische/hohe Findings = 0 vor Go-Live. **Budget/Anbieter wartet auf dich.**
### [ ] 74. 🔴 Isolation-Re-Audit vor erstem Echt-Tenant (App + RLS)
### [ ] 75. 🟠 `allow_real_client_data=true` NUR für Pilot-Tenant (gated)
### [ ] 76. 🟠 Pilot-Firma begleiten + Feedback
### [ ] 77. 🟡 Pentest-Findings als Sprint
### [ ] 78. 🟡 Go-Live-Checkliste (Technik + Compliance abgehakt)

---

## G. ENGINE & 3eyes-FACHLOGIK (79–110)

> **Holistik:** Die Engine ist das Herz — sie produziert die Zahlen, denen Berater + FINMA vertrauen. Parität zu 3eyes = Methodik-Glaubwürdigkeit. Determinismus + Tests = Haftungssicherheit. Läuft parallel zu A–F (kein Infra-Block).

### [✓] 79–82 Zielerreichung P25 · Ziel-Gleichgewichtung (Härtegrad opt-in) · maxIlliquid=PE · Itô-Hauptpfad=MC-Median (diese Session)

### [✓] 83. 🟠 `goal_scope="Gesamtvermögen"` engine-seitig (2026-06-19)
- **Ziel:** Ziele gegen Gesamtvermögen statt nur Beratungsvermögen bewerten.
- **Können:** Bei Scope=Gesamtvermögen Hochrechnung gegen total_wealth; Wachstumsannahmen externer Assets (Immobilien etc.) konservativ + dokumentiert.
- **Verknüpft:** #84 (Miete), #97 (CMA).
- **DoD:** Test: Ziel mit Scope Gesamtvermögen nutzt total-Pfad; Determinismus.
- **UMGESETZT (User-Entscheid: real 0 %):** Für Vermögensziele (Kapitalerhalt/Vermoegensziel) mit `goal_scope="Gesamtvermögen"` werden externe Assets (Gesamt- minus Beratungsvermögen) **konservativ nur mit Teuerung** (realer Zuwachs 0 %, keine Vola) zur Projektion addiert — in deterministischem UND MC-Pfad **identisch** (kein Drift, B4-Falle vermieden). Default-Scope (Beratungsvermögen) unverändert. Ausgaben-/Renditeziele bleiben scope-neutral (Ausgaben liquiditätsgetrieben — illiquide Eigenheime zahlen keine kurzfristige Ausgabe). Helfer `_external_assets_inflation_value` + `_goal_uses_total_scope` in `portfolio_engine.py`. Locks: `test_goal_scope_gesamtvermoegen.py` (6), B4-Tests auf Default-Scope umgestellt.

### [ ] 84. 🟠 Miete inflationsindexiert (optional)
- **Können:** Flag pro Immobilie „Miete inflationsgebunden" → abgeleiteter Mietertrag `is_inflation_linked=1`.
- **Verknüpft:** #100/#101 (Inflation), #34 derived cashflows.
- **DoD:** Test: indexierte Miete wächst mit Teuerung in Projektion.

### [ ] 85–88. 🟠 Engine-Hardening P2–P5 (CTO-Audit-Plan)
- **Ziel:** offene Härtungspunkte des 3-Phasen-Plans (Verifikation, Sub-Alloc+Tax+Currency, UX).
- **Umsetzung:** je Punkt Pinned-Test vor Refactor.
- **DoD:** je Phase: Tests grün + Doku im Whitepaper.

### [ ] 89. 🟡 Sub-Asset-Klassen-Tiefe im Optimizer
- **Können:** Intra-Bucket-Allokation (CH↔EM-Equity) mit Block-Diagonal-Korrelation.
- **DoD:** Optimizer wählt Sub-Klassen; Korrelations-Matrix positiv-definit.

### [ ] 90. 🟡 Tax-aware Optimizer-Objective (opt-in)
- **Verknüpft:** #111.
- **DoD:** Nach-Steuer-Rendite in Zielfunktion togglebar.

### [ ] 91. 🟡 Currency-aware Optimizer
- **Können:** FX-Risiko/Hedging-Kosten in Scenario-Engine; base_currency-Konsistenz.
- **DoD:** Test: Fremdwährungsquote erhöht Risiko korrekt.

### [ ] 92. 🟡 Stochastic-Optimizer als Default prüfen
- **Umsetzung:** Shadow-Comparison-Aggregat auswerten → ab ≥3 Mandaten + GREEN-Mehrheit Default-Switch erwägen.
- **DoD:** datenbasierte Entscheidung dokumentiert.

### [ ] 93. 🟡 Rebalancing-Trigger-Konsistenz
- **Ziel:** kein automatisches Markt-Timing (Anlagephilosophie: Re-Balancing nur via Eignungsprüfung/Kundenmeldung).
- **DoD:** Code-Audit: keine Timing-Logik aktiv; Test.

### [⏸] 94. 🟠 Decumulation-Glidepath (Aktienquote sinkt mit Horizont)
- **Ziel:** Sequence-of-Returns-Risiko im Verzehr senken.
- **Können:** opt-in: Aktienquote reduziert sich mit kürzer werdendem Horizont innerhalb der Risikoprofil-Bänder.
- **Verknüpft:** #95, #96; Chileru-Analyse. **Wartet auf deine Feature-Entscheidung.**
- **DoD:** Test: Glidepath bleibt in Bändern; ohne Flag unverändert.

### [⏸] 95. 🟠 Verzehr-Liquiditätsreserve (Pflicht 2–3 Jahresausgaben)
- **Ziel:** Schutz vor Verkauf in Krise.
- **Können:** im Decumulation-Mandat Reserve = N×Netto-Jahresausgabe; reagiert auf Cashflow-Profil (heute: Reserve springt nur bei Liquiditätsbedarf).
- **Verknüpft:** Reserve-Logik `_reserve_decay_factor`, #94.
- **DoD:** Test: Reserve ≥ N×Ausgabe bei Verzehr; konservativ.

### [ ] 96. 🟡 Sequence-of-Returns-Kennzahl (Verzehr)
- **DoD:** Kennzahl im SOLL/IST-Vergleich sichtbar.

### [ ] 97. 🟡 CMA-Werte gegen konservative CH-Annahmen prüfen
- **Können:** Renditen/Vols/Korrelationen je Assetklasse plausibilisieren (konservativ, Ruhestandsgelder).
- **Verknüpft:** #121–#124 (Marktdaten), #98/#99.
- **DoD:** dokumentierte Quelle + Review; Default-CMA konservativ.

### [ ] 98. 🟡 Korrelationsmatrix-Review (Krisen-Regime)
- **DoD:** Krisen-Korrelation (→1 im Stress) parametrisiert + getestet.

### [ ] 99. 🟡 Cornish-Fisher Skew/Kurtosis pro Sub-Klasse kalibrieren
- **DoD:** Fat-Tails realistisch; Test gegen RFC/Referenz.

### [ ] 100. 🟡 Inflations-Pfad pro Szenario konfigurierbar
- **DoD:** `inflation_path_json` je CMA editierbar.

### [ ] 101. 🟡 „Real (inflationsbereinigt)"-Toggle im SOLL/IST-Chart prominenter
- **Verknüpft:** vorhandene `_real_series_from_nominal`.
- **DoD:** Toggle nominal/real direkt am Chart.

### [ ] 102. 🟠 IST-Depot-Illiquidität an „PE+Direktimmobilien=illiquid" angleichen (Codex)
- **DoD:** `depot_check` klassifiziert konsistent zur SOLL-Definition.

### [ ] 103. 🟢 Goal-Achievement-Ordinalskala 3eyes-exakt (heute kontinuierlich) — bewusst optional
### [ ] 104. 🟢 Serielle Renditeziele sauber im Optimizer
### [ ] 105. 🟢 Liquid-Alts vs Hedge-Funds Liquiditäts-Klassifikation feinjustieren
### [ ] 106. 🟡 Engine-Whitepaper aktuell halten (Methodik-Transparenz für FINMA)
### [ ] 107. 🟢 Backtesting gegen historische Daten erweitern
### [ ] 108. 🟢 Stress-Szenarien-Presets (2008/2020/Zinsschock)
### [ ] 109. 🟢 Goal-Priorisierung bei Konflikt transparenter
### [ ] 110. 🟡 Engine-Performance (MC-Runs) profilen + cachen (Scenario-Cache vorhanden)

---

## H. STEUERN (111–120)
> **Holistik:** Nach-Steuer-Sicht macht Projektionen ehrlich; Plugin-Architektur erlaubt Länder-Ausbau ohne Engine-Fork.
- [ ] 111. 🟠 Steuer in Netto-Cashflow (CH-Plugin in Projektion, opt-in) — **DoD:** Vermögens-/Einkommenssteuer als wiederkehrende Ausgabe; Test.
- [ ] 112. 🟡 Vermögenssteuer pro Kanton verfeinern
- [ ] 113. 🟡 Einkommenssteuer in Verzehr-Phase
- [ ] 114. 🟡 Verrechnungssteuer/DA-1 auf Erträge
- [ ] 115–119. 🟢 Tax-SDK Plugins FR/US/IT/DE/AT (Conformance-Contract)
- [ ] 120. 🟢 Tax-Conformance-Tests pro Land

## I. MARKTDATEN-PIPELINE (121–130)
> **Holistik:** Speist die CMA (#97) — Datenqualität = Engine-Qualität. Gratis-Stack (yfinance+stooq+macro), CHF 0/Jahr.
- [ ] 121. 🟡 Multi-Source-Aggregator finalisieren — **DoD:** 3 Quellen, Fallback, deterministisch.
- [ ] 122. 🟡 Tägliche Preis-Aktualisierung im Staging verifizieren
- [ ] 123. 🟡 Cache-Purge + Quellen-Ausfall-Fallback
- [ ] 124. 🟡 CMA-Auto-Update aus Marktdaten (opt-in, Review-Gate) — **verknüpft #97**
- [ ] 125–130. 🟢 Datenqualität · Benchmarks · FX · TER · ESG/SFDR · Historie

## J. FRONTEND / UX-POLITUR (131–155)
> **Holistik:** Erst Korrektheit (G), dann Glanz. Aber: schlechte UX kostet Beratervertrauen → mittlere Prio. Monolith (1.4 MB) braucht mittelfristig Modul-Split.
- [✓] 131–133 Cashflow-Hänger · Heimmarkt single-source · Horizont-Control+X-Achse (diese Session)
- [ ] 134. 🔴 #20 Validierung Design & Politur durchgehen — **DoD:** Checkliste je Hauptseite.
- [⏸] 135. 🔴 Crash-Wurzel „Maximum call stack" — **braucht deine Konsolenzeile** `CHART_RENDER_FAILED [step]`.
- [ ] 136. 🟠 Visual-Smoke-Checkliste (Login→2FA→Mandat→Cashflow→Strategie→PDF)
- [ ] 137. 🟠 Horizont-Diagnose-`[x:A→B]` nach erfolgreichem Test wieder entfernen
- [ ] 138–155. 🟡/🟢 Ladezustände · Fehler-Toasts · Empty States · A11y · Responsive · Zahlenformate · Tooltips · Dark-Mode · Cashflow-Gruppierung · Ziel-Editor · AA-Präferenzen-UX · Onboarding-Wizard · Suche/Filter · Modul-Split (#U-35) · Inline-Validierung · Undo

## K. PDF / REPORTING (156–168)
> **Holistik:** Das PDF ist das *rechtliche Artefakt* (FIDLEG/Eignungsprüfung). Muss 1:1 zur UI passen + deterministisch sein.
- [ ] 156. 🟠 FIDLEG Kostenausweis Ex-ante (Codex, PR offen) — verifizieren+mergen
- [ ] 157. 🟠 PDF End-to-End im Staging (Rendering/poppler)
- [ ] 158. 🟡 Report-Horizont = gewählter Chart-Horizont
- [ ] 159–168. 🟡/🟢 Risikoprofil-PDF · SOLL/IST im PDF · Kosten ex-post · Mehrsprachig · Branding · Anlagerezept · Protokoll · Excel/CSV · PDF-Determinismus-Test · „Test"-Wasserzeichen

## L. TESTING / QA (169–180)
> **Holistik:** Das Sicherheitsnetz. Leak-Gate + Determinismus sind nicht verhandelbar (FINMA/Trennung).
- [ ] 169. 🟠 Cross-Tenant-Leak-Tests bei JEDEM PR (Gate steht — grün halten)
- [ ] 170. 🟠 E2E/Visual-Regression (Playwright) für Hauptflows
- [ ] 171–180. 🟡/🟢 Postgres-Matrix · Last-Test · Property-Tests · Determinismus · Mutation-Testing · A11y-Autotest · Daten-Integritäts-Audit in Cron · Post-Deploy-Smoke · Coverage-Schwelle · Flaky-Monitoring

## M. DATEN-HYGIENE / FINMA (181–188)
> **Holistik:** „Keine synthetischen Daten zwischen echten" — Audit-getrieben, kein Vertrauen ohne Beleg.
- [✓] 181–182 Leart-Seeds bereinigt · Daniel-Beispiel soft-deleted
- [ ] 183. 🟠 27 verwaiste recommendation_runs bereinigen (Codex cascade-safe purge, PR #271) — verifizieren+mergen
- [ ] 184–188. 🟡/🟢 Klassifizierung real/synthetic überall · Audit-Script in Cron · Demo-Daten resetbar · revDSG-Export pro Mandant · revDSG-Löschung pro Mandant

## N. ADMIN-MENÜ REDESIGN (189–194)
> **Holistik:** 17 Sektionen, teils Platzhalter (Auftrag 2026-06-10). Erst auditieren (works vs placeholder), dann userfriendlich.
- [ ] 189. 🟡 System-Administration auditieren + redesignen
- [ ] 190–194. 🟡/🟢 Platzhalter funktional/entfernen · Dashboard mit echten KPIs · CMA-Admin · Audit-Viewer · Feature-Flags-UI

## O. REPO / DOKU / WARTUNG (195–200)
- [ ] 195. 🟠 Merge-Koordination mit Codex (geteilte Dateien, Snapshot nach HTML-Merge)
- [ ] 196. 🟡 Diese Liste ist dieses Doc (persistiert ✓)
- [ ] 197–200. 🟡/🟢 ADRs aktuell · README/Setup · alte Branches aufräumen · Changelog

---

## ANHANG — Empfohlene nächste 7 Tage (verknüpft priorisiert)
1. **Tag 1:** #1–#7 (Quick-Tunnel-Extern-Test mit Kollegen) — sofortiger Vertrauensgewinn + Feedback.
2. **Tag 1–2:** #19/#20 entscheiden (Provider+Domain) — entsperrt B+C.
3. **Tag 2–3:** #134/#135 (Design-Politur + Crash-Wurzel) — App-Stabilität für Demo.
4. **Tag 3–5:** #21–#28 (CH-VPS stabil) — fester Testserver.
5. **Parallel:** #97/#102/#156 (CMA-Review, IST-Illiquidität, FIDLEG-PDF) — Engine/Report-Vertrauen.
6. **Danach:** #33–#37 (Postgres+RLS) als Tor zu echten Daten.
7. **Vor Echtdaten:** #73 Pentest beauftragen.
