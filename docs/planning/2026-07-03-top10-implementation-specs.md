# Top-10 Implementierungs-Specs (2026-07-03)

**Zweck:** Umsetzungs-fertige, code-freie Specs für die 10 wichtigsten offenen Punkte
(Audit-Findings + eigene Funde). Jeder Bericht: Ist-Zustand (file:line-verifiziert auf
`develop`), Risiko, Soll/Anforderungen, Umsetzungs-Schritte (ohne Code), Akzeptanz­kriterien
& Tests, Konflikt/Koordination. Umsetzung erfolgt danach durch Claude oder Codex.

**Grounding:** Alle file:line-Belege gegen `origin/develop` verifiziert.

---

## Prioritäts-Übersicht

| # | Punkt | Schwere | Status | Reihenfolge |
|---|-------|---------|--------|-------------|
| 1 | **SEC-1** — Client-Login erbt keinen tenant_id (NULL-Tenant) | 🔴 HIGH sec | ✅ **konfliktfrei — jetzt** | Zuerst (Wurzel) |
| 2 | **rls-1** — strict_tenant_isolation nicht erzwungen | 🔴 HIGH sec | ⛔ #299 (services/auth.py, config.py) | nach #299 |
| 3 | **AUTH-01** — org-weite 2FA nie serverseitig erzwungen | 🔴 HIGH sec | ⛔ #299 | nach #299 (mit AUTH-02) |
| 4 | **AUTH-02** — must_change_password nie erzwungen | 🔴 HIGH sec | ⛔ #299 | nach #299 (mit AUTH-01) |
| 5 | **AB-1/AB-2** — Backup nicht atomar + 2 divergente Verzeichnisse | 🔴 HIGH data | ✅ AB-1 frei / AB-2 config.py ⛔ | AB-1 jetzt |
| 6 | **AUTH-03** — Login-Rate-Limit nur in-memory (Brute-Force) | 🟠 HIGH sec | 🟡 login_guard.py frei, Aufrufer #299 | koordiniert |
| 7 | **CF-1/CF-2** — Cashflow-Serie Endpoint vs. Engine divergiert | 🟠 HIGH/MED | 🟡 Endpoint frei, Engine ⛔ #299/#305 | teilw. jetzt |
| 8 | **RES-1/RES-2** — Reserve-Berechnung + Validierung | 🟡 MED | ⛔ portfolio_engine (#299/#305) | nach Merges |
| 9 | **RT-2 + SEC-2** — Tax-Override-Validierung + update_user-Scope | 🟡 MED | ⛔ #305 / #299 | nach Merges |
| 10 | **Report-Fallback** — „Anderes Vermögen" ohne Fallback im PDF | 🟡 MED UX | ✅ **konfliktfrei — jetzt** | jetzt |

**Sofort machbar (konfliktfrei):** #1 SEC-1, #5 AB-1, #10 Report-Fallback (+ CF-1/CF-2 Endpoint-Teil, AUTH-03 login_guard-Teil).
**Blockiert bis Codex mergt (#299 RLS/auth/config, #305 tax/portfolio_engine):** #2, 3, 4, 8, 9 und die Engine-Teile von #6/#7.

**Empfohlene Reihenfolge Security:** SEC-1 → rls-1 → SEC-2 (SEC-1 ist die Wurzel der herrenlosen NULL-Tenant-User; rls-1 und SEC-2 verschärfen sie).

---

## 1. SEC-1 — Client-Login-User erbt keinen `tenant_id` (NULL-Tenant)

- **Ist-Zustand (verifiziert):** In `routers/clients.py`, `create_client_login`, wird der User mit `role="client"` gebaut, ohne `tenant_id`-Kwarg (clients.py:512-522). Das Model setzt keinen Default (`models/users.py:14` — `tenant_id = Column(String, ForeignKey("tenants.id"))`, nullable) → Client-Login-User landet mit `tenant_id=NULL`. Alle anderen User-Creation-Pfade setzen den Tenant explizit: `create_user`/Provisioning erbt `tenant_id = getattr(current_user, "tenant_id", None)` (routers/auth.py:385, 398), Invite-Accept ebenso (auth.py:467), `create_mandate` erbt vom Parent-Client mit Fallback auf den User (routers/mandates.py:54, 59). Nur der Client-Login-Pfad fehlt. Folge: NULL-Tenant-Rows sind im Non-Strict-Modus für JEDEN Tenant sichtbar (Filter `or_(tenant_id==user_tid, tenant_id.is_(None))`, services/auth.py:171-173, 191-193); im Strict-Modus wird der Client-User für seinen eigenen Berater unsichtbar. Die Defense-in-depth-Prüfung `get_linked_client_for_user_or_404` (services/auth.py:370-379) greift NICHT, wenn `user.tenant_id` NULL ist.
- **Risiko/Warum wichtig:** Verletzung der harten Mandantentrennung (FINMA/FIDLEG, DSG). Ein Client-Login-User ohne Tenant ist eine „herrenlose" Identität: im BC-Modus in tenant-gefilterten User-Listen fremder Firmen-Admins sichtbar und administrierbar. Zudem blockiert jede solche NULL-Row die geplante NOT-NULL-Migration (Voraussetzung für Tier-2). Der bestehende Backfill (database.py:854) würde die Row nach `'main'` ziehen — **falsch**, wenn der anlegende Berater zu Firma B gehört.
- **Soll / Anforderungen:**
  - Der neue `User(role="client", …)` MUSS `tenant_id` erhalten, primär vom Parent-`client.tenant_id`, Fallback `current_user.tenant_id` (analog `create_mandate`).
  - Ist danach immer noch kein Tenant bestimmbar (beide NULL, Legacy-Tier-1-Single), ist NULL nur bei `tenancy_mode == "single"`/non-strict zulässig; im Multi-/Strict-Kontext MUSS die Erstellung mit 409/422 abgelehnt werden.
  - 1:1-Linkage unverändert; nur der Tenant des User-Objekts wird gesetzt.
  - Bestehende Client-Login-User mit NULL-Tenant per Backfill auf den Tenant ihres verlinkten Clients ziehen — nicht pauschal `'main'`. Idempotent.
- **Umsetzung (Schritte, ohne Code):**
  1. In `create_client_login` vor dem `User(...)`-Aufbau (nach `client = _get_client_or_404(...)`) `client_user_tenant_id = getattr(client, "tenant_id", None) or getattr(current_user, "tenant_id", None)` bilden (Formel aus mandates.py:54).
  2. `tenant_id=client_user_tenant_id` in den `User(...)`-Konstruktor (clients.py:512-522) aufnehmen.
  3. Guard: Wenn leer UND (`settings.strict_tenant_isolation` ODER `tenancy_mode == "multi"`) → `HTTPException(409/422, "Tenant nicht bestimmbar")`.
  4. Neue idempotente Backfill-Funktion in `database.py` (z.B. `ensure_client_login_user_tenant_backfill`): per JOIN `client_logins → clients` alle `users` mit `role='client'` und `tenant_id IS NULL` auf `clients.tenant_id` setzen. VOR dem generischen `ensure_tenant_backfill` (database.py:948) aufrufen.
  5. Keine Schema-Änderung nötig; kein neuer Config-Key.
- **Akzeptanzkriterien & Tests:**
  - Berater A (tenant `firma-a`) legt Client-Login an → erzeugter User hat `tenant_id == "firma-a"` (nicht NULL).
  - Client mit eigenem Tenant → User erbt Client-Tenant (Vorrang vor Berater-Tenant).
  - Legacy (beide NULL, single, non-strict) → erlaubt, NULL bleibt (BC).
  - `tenancy_mode="multi"`/strict + kein Tenant ableitbar → 409/422, kein User in DB.
  - Backfill: NULL-User + Client `firma-b` → nach Backfill `firma-b` (NICHT `main`); 2. Lauf idempotent; fehlende Tabelle crasht nicht.
  - Regression: fremder Firmen-Admin (`firma-b`) sieht den neuen Client-User von `firma-a` nicht mehr.
- **Konflikt/Koordination:** Berührt `routers/clients.py` + `database.py` — von #299 **nicht** angefasst (#299 = services/auth.py, config.py). **Standalone-sicher.** Der Guard liest nur `settings.tenancy_mode`/`strict_tenant_isolation`. Empfehlung: SEC-1 zuerst mergen (klein, konfliktfrei); Voraussetzung für die NOT-NULL-Constraint aus rls-1.

---

## 2. rls-1 — Strikte Mandantentrennung erzwingen (NULL-Tenant-Leak im Non-Strict-Modus)

- **Ist-Zustand (verifiziert):** `strict_tenant_isolation: bool = False` ist ein statischer Default (config.py:219-223), unabhängig von `deployment_tier` (config.py:212) und `tenancy_mode` (config.py:216) — keine Ableitung. Non-Strict filtern `_apply_tenant_filter_to_client_query` (services/auth.py:171-173) und `_mandate_query` (auth.py:191-193) mit `or_(tenant_id == user_tid, tenant_id.is_(None))` → jede NULL-Row für JEDEN Tenant sichtbar. Zusätzlich: hat der User selbst keinen `tenant_id`, wird gar nicht gefiltert (auth.py:161-163, 183-185 „Legacy-User: kein Filter"). Dieselbe NULL-sichtbar-Logik in User-Sichtbarkeit (routers/auth.py:574; services/auth.py:640) und Client-Login-Zugriff (auth.py:378). Spalten alle nullable (models/users.py:14, clients.py:12, mandates.py:12, protocol_bausteine.py:25). Backfill NULL→`'main'` existiert (database.py:837-867), aber keine NOT-NULL-Constraint, kein Strict-Zwang für Tier-2.
- **Risiko/Warum wichtig:** Im Shared-Cloud-Betrieb (Tier-2) ist der Default unsicher: eine einzige NULL-Row ist cross-tenant sichtbar → Bruch der Mandantentrennung (FINMA/FIDLEG, DSG). Ein Advisor ohne eigenen `tenant_id` umgeht die Filterung komplett und sieht ALLE Firmen. Sicherheit hängt an Ops-Konfiguration statt am Code.
- **Soll / Anforderungen:**
  - Multi-Tenant: strikte Isolation automatisch aktiv — effektiver Strict = explizit `strict_tenant_isolation` ODER `deployment_tier == "tier2"` ODER `tenancy_mode == "multi"`.
  - Strict: nur exakter Tenant-Match; NULL-Rows unsichtbar.
  - User OHNE `tenant_id` darf im Strict-/Multi-Modus KEINEN globalen Zugriff mehr haben (heutiger „kein Filter"-Zweig schliessen).
  - Vor Aktivierung: vollständiger Backfill, dann NOT-NULL-Constraint (mind. clients, mandates, users; protocol_bausteine analog). Danach `OR IS NULL`-Klausel entfernbar.
  - Tier-1-Single: bleibt non-strict, ein Tenant `'main'`, keine Verhaltensänderung.
- **Umsetzung (Schritte, ohne Code):**
  1. Effektiven Strict-Wert zentralisieren: `config.py`-Property/Helper `effective_strict_tenant_isolation` (True wenn explizit True ODER tier2 ODER multi). Direkte `getattr(_settings, "strict_tenant_isolation", False)`-Lookups in services/auth.py:168, 189; routers/auth.py:573; services/auth.py:639, 378 durch den Helper ersetzen.
  2. NULL-User-Zweig absichern: frühen `return query` bei `not user_tid` (auth.py:162-163, 184-185) im Strict-Modus auf leere Ergebnismenge (unmögliche Bedingung) umstellen. Non-strict/Tier-1 = BC.
  3. Backfill vervollständigen & vorziehen: SEC-1-Client-Login-Backfill (korrekter Firma-Tenant) VOR `ensure_tenant_backfill` (database.py:948).
  4. NOT-NULL-Migration: idempotente Runtime-Migration (SQLite Table-Rebuild-Muster wie database.py:184/257/283); nur bei 0 NULL-Rows ausführen, sonst überspringen+warnen (Boot nie abbrechen).
  5. `OR IS NULL` entfernen: erst NACH bestätigter NOT-NULL-Migration (`.is_(None)`-Zweige auth.py:172, 192).
  6. Config-Defaults unverändert (Tier-1 Default non-strict).
- **Akzeptanzkriterien & Tests:**
  - `deployment_tier="tier2"`/`tenancy_mode="multi"` + `strict=False` → effektiv strict True; NULL-Row unsichtbar.
  - Tier-1-Default → effektiv non-strict; NULL-Row sichtbar (BC); bestehende `test_auth_tenant_aware.py` grün.
  - User ohne `tenant_id` im Strict → sieht 0 Clients/Mandate.
  - Backfill+NOT-NULL: keine NULL mehr; NULL-Insert schlägt fehl; Migration idempotent + Boot-safe.
  - Cross-Tenant: Advisor `firma-a` sieht nie `firma-b` und nie NULL-Rows im Strict.
- **Konflikt/Koordination:** DIREKTER Überlapp mit #299 (services/auth.py, config.py). Postgres-RLS (DB-seitig) und dieser ORM-Filter (Defense-in-depth) sind komplementär, editieren aber dieselben Funktionen. NICHT parallel: rls-1 nach #299 aufsetzen; effektiven-Strict-Helper + NOT-NULL/Backfill beisteuern, die `_apply_tenant_filter_*`-Änderungen ggf. verwerfen, falls #299 sie durch RLS ersetzt. config.py-Property + database.py-Migration sind weitgehend konfliktarm.

---

## 3. AUTH-01 — Org-weite Pflicht-2FA (`require_2fa`) serverseitig erzwingen

- **Ist-Zustand (verifiziert):** Login triggert 2FA nur, wenn der User bereits `totp_enabled` hat: `routers/auth.py:143` (`if getattr(user, "totp_enabled", 0):`) — sonst direkt `_issue_token_response(user)` (auth.py:164-173). `settings.require_2fa` (Default False, config.py:226) wird beim Login nirgends gelesen; einziger Konsument ist `GET /auth/2fa/status` (auth.py:190-194, nur Report). `get_current_user` (services/auth.py:71-113) prüft weder `totp_enabled` noch `require_2fa`. Bei `require_2fa=True` kann jeder User ohne TOTP normal einloggen — Pflicht rein kosmetisch.
- **Risiko/Warum wichtig:** Admin aktiviert org-weite 2FA und glaubt alle Zugänge MFA-geschützt — tatsächlich alle Bestands-/Neu-User nur passwortgeschützt. Für extern erreichbare Wealth-App = falsche Sicherheitszusage, direkter Kompromittierungspfad (Credential-Stuffing, Phishing).
- **Soll / Anforderungen:**
  - Bei `require_2fa=True` kein voll nutzbares Token an User ohne `totp_enabled=1`.
  - Login bei `require_2fa=True` + `totp_enabled=0`: Passwort normal prüfen (inkl. Guard), aber Enrollment-erzwingenden Zustand liefern → Client muss zu `/auth/2fa/setup`+`/enable`, bevor er fachliche Endpoints erreicht.
  - Empfohlene Variante: „Enrollment-Ticket" (eingeschränktes Token mit Claim `scope="2fa_enroll"`), das nur Setup/Enable erlaubt (konsistent zum bestehenden `X-2FA-Required`-Muster).
  - Edge Cases: enrollter User → unverändert (auth.py:143-162). `require_2fa=False` → unverändert (Tier-1). Bootstrap-Admin muss initial einloggen und danach zum Enrollment gezwungen werden. Client-Portal-User (`role='client'`): Policy explizit (empfohlen: gleiche Pflicht, getrennt schaltbar).
  - `/2fa/status` liefert zusätzlich `enrollment_required: bool` (`required and not enabled`).
- **Umsetzung (Schritte, ohne Code):**
  1. In `login` (auth.py:112-173) nach Passwort-/`is_active`-Prüfung, VOR `_issue_token_response`: wenn `settings.require_2fa` UND nicht `totp_enabled` → Enrollment-Pfad statt Token. Bestehender `totp_enabled`-Block (Zeile 143) bleibt.
  2. Enrollment-Ticket: Helper in services/auth.py (`issue_enrollment_token`) mit Claim `scope="2fa_enroll"`. `get_current_user` liest den Scope; neue Dependency `require_enrolled_user` blockt Scope-Requests auf allen Endpoints AUSSER `/auth/2fa/setup|enable|status`, `/auth/logout` (403). Setup/Enable (auth.py:197-227) akzeptieren das Ticket.
  3. Nach `/2fa/enable` (auth.py:210-227, setzt `totp_enabled=1`): volles Token via Re-Login oder direkt aus dem Endpoint (analog `invite_accept`).
  4. `twofa_status` (auth.py:188-194) um `enrollment_required` ergänzen.
  5. Bootstrap-Ausnahme: normales Token in `bootstrap_admin` genügt; nächster Login greift Pflicht automatisch.
  6. **Keine** DB-Migration — `totp_secret`/`totp_enabled` existieren (models/users.py:26-27; database.py:186-187).
- **Akzeptanzkriterien & Tests:**
  - `require_2fa=True`, `totp_enabled=0`: Login liefert kein volles Token; fachlicher Endpoint → 403.
  - Enrollment-Ticket erlaubt Setup+Enable; danach volles Token, fachlich 200.
  - `require_2fa=True`, `totp_enabled=1`: unveränderter TOTP-Flow.
  - `require_2fa=False`: sofort volles Token (Regression, Tier-1).
  - Ticket erlaubt keinen Nicht-Enrollment-Endpoint (403).
- **Konflikt/Koordination:** Hoher Überlapp mit #299 (routers/auth.py `login` + services/auth.py `get_current_user`). **Koordination:** AUTH-01/-02/-03 gemeinsam nach #299-Merge; Scope-Claim-/Gate-Logik in `get_current_user` in EINER koordinierten Änderung mit den `must_change_password`-Checks (AUTH-02) bauen.

---

## 4. AUTH-02 — `must_change_password` serverseitig erzwingen

- **Ist-Zustand (verifiziert):** Flag wird gesetzt: `create_user`→1 (auth.py:401), Admin-Reset fremder PW→1 (auth.py:614 `0 if is_self else 1`), 0 bei Self-Reset/`invite_accept`(529)/`password_reset_confirm`(340)/`invite_user`(468). Aber NIE erzwungen: `get_current_user` (services/auth.py:71-113) liest es nicht; `_issue_token_response`/`issue_token_for_user` (auth.py:60-66; services/auth.py:63-68) nehmen es nicht in den Claim; nach `login` (auth.py:164-173) volles Token trotz Flag. Nur im Response-Schema exponiert (schemas/users.py:46). Client, der die UI umgeht, behält vollen Zugriff.
- **Risiko/Warum wichtig:** Admin-gesetzte Initial-Passwörter (create_user, Admin-Reset) sind bekannt/schwach. Zwangswechsel nur clientseitig „empfohlen" → dauerhaft kompromittierbare Zugänge, Bruch des FIDLEG-/Governance-Erwartungswerts.
- **Soll / Anforderungen:**
  - Solange `must_change_password=1`: Server blockt ALLE Endpoints ausser Passwort-Änderung + minimalem Auth-Housekeeping.
  - Zugelassen: `PUT /users/{own}/password` (Self), `POST /auth/logout`, `GET /auth/me`, `GET /auth/2fa/status`. Rest → 403 mit `X-Password-Change-Required: 1`.
  - Nach Self-Wechsel Flag→0 (passiert bereits auth.py:614) → voller Zugriff.
  - Edge: Self-Wechsel darf nicht dasselbe PW setzen (neu ≠ alt). Wechselwirkung mit AUTH-01: beide Gates unabhängig, Passwort-Endpoint auch im 2FA-Enrollment erreichbar.
- **Umsetzung (Schritte, ohne Code):**
  1. Zentrales Gate: neue Dependency `require_password_changed` (baut auf `get_current_user`), die fachliche Router schützt; Whitelist-Endpoints bleiben bei `get_current_user`. Alternativ (invasiver) Gate direkt in `get_current_user` mit `request.url.path`-Whitelist.
  2. Empfohlen (geringster Blast-Radius): Dependency in services/auth.py; in fachlichen Routern (clients, mandates, wealth, allocation, recommendations, dashboard, users-Mutationen) `get_current_user` → `require_password_changed`, bzw. Router-weite `dependencies=[...]` in main.py:120-138. `/auth/*` bleibt bei `get_current_user`. **Achtung:** `require_admin`/`require_advisor`/`require_client` (services/auth.py:116-142, 315-327) hängen an `get_current_user` → ebenfalls einschliessen.
  3. Optional: Flag als Token-Claim (Vorsicht: nach Wechsel neues Token nötig). **DB-basierte Prüfung empfohlen** (get_current_user lädt den User ohnehin → Read gratis).
  4. `UserPasswordReset`-Schema (schemas/users.py:119-127) optional um „neu ≠ alt" erweitern.
  5. **Keine** Migration — Spalte existiert (models/users.py:30; database.py:189).
- **Akzeptanzkriterien & Tests:**
  - `create_user` → Login → `GET /clients` = 403 + `X-Password-Change-Required: 1`.
  - `PUT /users/{own}/password` erfolgreich → danach `GET /clients` = 200.
  - Admin-Reset fremd → Ziel-User bis Self-Wechsel 403.
  - `invite_accept`/`password_reset_confirm`: Flag 0, sofort voller Zugriff (Regression).
  - Whitelist funktioniert im must-change-Zustand.
- **Konflikt/Koordination:** Direkter Überlapp mit #299 (services/auth.py `get_current_user`, `require_*`). Mit AUTH-01 im selben `get_current_user`-Umbau bündeln, nach #299 rebasen. Router-Dependencies in main.py mit Codex abstimmen.

---

## 5. AB-1 / AB-2 — Backup atomar + zwei divergente Implementierungen vereinheitlichen

### AB-1 — Nicht wirklich atomares SQLite-Backup
- **Ist-Zustand (verifiziert):** `_perform_atomic_copy` (services/backup.py:221-242) öffnet Quelle read-only (Zeile 233-234), öffnet als Ziel **direkt die endgültige Backup-Datei** (Zeile 236) und ruft `src_conn.backup(dst_conn)` (Zeile 238). **Keine Temp-Datei, kein `os.replace`, kein `fsync`.** SHA256/Sidecar erst NACH dem Kopieren (Zeile 110-114); keine `PRAGMA integrity_check`. `restore_database` (145-201) nutzt dieselbe nicht-atomare Funktion für die produktive DB (Zeile 186) → abgebrochener Restore hinterlässt halb überschriebene DB. Scheduler (backup_scheduler.py:37-42) erbt die Schwäche.
- **Risiko/Warum wichtig:** Abbruch während `src_conn.backup(...)` → unvollständige, aber gültig benannte `.db`. `list_backups`/`_prune_old_backups` gehen nur übers Glob `5eyes-backup-*.db` → Ruine gilt als reguläres Backup. Kein Sidecar → späterer `verify_hash` (172-182) liefert still `hash_verified=False` (kein Fehler) → korruptes Backup wird kommentarlos restauriert. Für FINMA/DSG-Aufbewahrung: stiller Datenverlust.
- **Soll / Anforderungen:**
  1. Atomarität: erst in eindeutige Temp-Datei im selben Zielverzeichnis, dann `os.replace` in den Endnamen. Getöteter Prozess hinterlässt höchstens erkennbare Temp-Datei.
  2. Durabilität: `fsync` auf Datei-FD vor `os.replace`, `fsync` auf Directory-FD danach.
  3. Integritätsverifikation: nach Schreiben (noch Temp) `PRAGMA integrity_check`; nur „ok" → finaler `os.replace`. SHA256 erst nach erfolgreichem `replace`; Sidecar erst nach Backup-Rename.
  4. Verwaiste Temp-Dateien beim Start jedes Laufs entfernen.
  5. Restore-Sicherheit: `verify_hash` verpflichtend (strict-Modus: fehlendes/mismatchtes Sidecar → Abbruch); Einspielen in produktive DB ebenfalls Temp+`os.replace`.
- **Umsetzung (Schritte, ohne Code):**
  - `_perform_atomic_copy` (221-242) umbauen: Ziel der `backup(...)`-Op = Temp-Datei (`target.with_name(target.name + ".partial")` oder `tempfile.mkstemp(dir=...)`); nach `close()` Temp read-only wiederöffnen, `PRAGMA integrity_check`; bei „ok" `fsync` + `os.replace` + Directory-`fsync`; bei Fehler Temp entfernen + Exception.
  - `backup_database` (67-142): Integritätsprüfung vor sichtbarem Rename; Sidecar (113-114) nach Rename, ebenfalls Temp+Replace. Zu Beginn verwaiste `*.partial` löschen.
  - `restore_database` (145-201): `_perform_atomic_copy(src, target)` (186) auf Temp+`os.replace`; `verify_hash` strict.
  - `_prune_old_backups` (261-295): `*.partial` ausschliessen.
  - `backup_scheduler.py` unverändert (profitiert automatisch).
- **Akzeptanzkriterien & Tests:** (1) Abbruch zwischen Temp-Schreiben und Rename → keine finale `5eyes-backup-*.db`. (2) Normal: Backup+Sidecar existieren, SHA256 match, `integrity_check`=ok. (3) Korruptes Backup → `restore(..., verify_hash=True)` wirft ValueError, produktive DB unverändert. (4) `*.partial` werden aufgeräumt. (5) Manueller + geplanter Pfad strukturgleich.
- **Konflikt/Koordination:** backup.py/backup_scheduler.py **nicht** in #299 → **standalone-sicher**, kein config.py nötig.

### AB-2 — Zwei unabhängige Backup-Implementierungen (Verzeichnis + Namensmuster)
- **Ist-Zustand (verifiziert):** Pfad A (`services/backup.py:backup_database`, 67-142): Verzeichnis aus `settings.backup_dir` (Default `~/5eyes/backups`, config.py:157); Name `5eyes-backup-{ts}.db` mit `%Y%m%d-%H%M%S` (backup.py:41/43/105); `.sha256`-Sidecar; WAL-konsistent via `sqlite3.backup()`. Pfad B (`services/maintenance.py:create_backup`, 105-143): Verzeichnis aus `ensure_backup_dir()` = `db_path.parent / 'backups'` (maintenance.py:52-55); Name `5eyes-backup-{stamp}.db` mit `%Y%m%dT%H%M%SZ` (111-112); **`shutil.copy2`** (113, keine Online-Backup-API); JSON-Manifest (127-135). Bei Defaults fallen die Verzeichnisse zufällig zusammen; sobald `db_path` ODER `backup_dir` überschrieben wird, **divergieren** sie. Beide Globs `5eyes-backup-*.db` (backup.py:42, maintenance.py:149) identisch → jeder Pfad listet/pruned die Dateien des anderen.
- **Risiko/Warum wichtig:** Zwei Wahrheiten für „wo liegen die Backups". Berater legt `backup_dir` auf externes Volume → Scheduler (A) korrekt extern, aber jedes manuelle „Backup jetzt" (B) schreibt neben die DB. Beim Restore falsches Verzeichnis → Restore-Failure/veralteter Stand. B nutzt `shutil.copy2` (bei WAL nicht garantiert konsistent). Bei gemeinsamem Verzeichnis pruned A fremde Backups mit → Verlust regulatorisch aufzubewahrender Snapshots.
- **Soll / Anforderungen:** (1) Single Source of Truth: nur eine Backup-Engine (`backup.py:backup_database`, WAL-aware); Maintenance delegiert. (2) Ein Verzeichnis (`settings.backup_dir`); `ensure_backup_dir()` respektiert es. (3) Ein Namensmuster (`5eyes-backup-%Y%m%d-%H%M%S.db`). (4) Konsistente Metadatei (Sidecar ODER Manifest). (5) Retention nur eigene Dateien.
- **Umsetzung (Schritte, ohne Code):**
  - `config.py`: `settings.backup_dir` (157) einziger kanonischer Ort (Default unverändert `~/5eyes/backups`). — von #299 berührt (siehe Koordination).
  - `maintenance.ensure_backup_dir()` (52-55): aus `settings.backup_dir` ableiten (`Path(...).expanduser().resolve()`, `mkdir(parents=True, exist_ok=True)`) statt `db_path.parent/'backups'`. Aufrufer (99, 147, 227) erben.
  - `maintenance.create_backup()` (105-143): `shutil.copy2`-Block (113) + manuelle WAL/SHM-Kopie (116-125) entfernen; stattdessen `services.backup.backup_database(target_dir=settings.backup_dir, ...)` aufrufen; Rückgabe-`dict` aus `BackupResult` (backup.py:46-56); Manifest ggf. daraus ableiten.
  - `maintenance.list_backups()` (146-168): an `backup.list_backups(settings.backup_dir)` delegieren oder gleiches Muster nutzen.
  - `backup_scheduler.py` (37-42) unverändert; `THHMMSSZ`-Muster entfällt.
- **Akzeptanzkriterien & Tests:** (1) `create_backup()` + Scheduler schreiben ins selbe Verzeichnis (Test mit `backup_dir` ≠ `db_path.parent/'backups'`). (2) Beide Namen matchen `5eyes-backup-YYYYMMDD-HHMMSS.db`; kein `T…Z` mehr. (3) Beide `list_backups` liefern dieselbe Menge. (4) Pruning nur eigenes Muster. (5) Manuelles Backup WAL-konsistent (`integrity_check`=ok).
- **Konflikt/Koordination:** backup.py/maintenance.py/scheduler **nicht** in #299 → Kernvereinheitlichung frei. **config.py IST von #299 berührt** (backup_dir in Settings, 157). AB-2 fügt keinen neuen Default hinzu, aber vor dem Merge mit #299 koordinieren: `ensure_backup_dir()`-Umstellung nach #299-Merge rebasen.

---

## 6. AUTH-03 — Brute-Force-Guard persistent/geteilt statt in-memory

- **Ist-Zustand (verifiziert):** `LoginAttemptGuard` hält `self._failures: dict[str, deque[datetime]]` + `self._locked_until` (services/login_guard.py:17-21); eine Modul-globale Instanz `login_attempt_guard` (login_guard.py:93). Key = Client-IP (erste `x-forwarded-for`-Hop) bzw. Username-Fallback (routers/auth.py:69-77). Genutzt in `login` (auth.py:115,128,160,164), `password_reset_request` (299-303), `_resolve_invite_guarded` (497-510), `resend_invite` (663-670). Zähler nur im RAM → bei Neustart weg, pro Worker eigener Zähler → effektives Limit × Worker-Zahl, Restart-Timing umgeht Lockout.
- **Risiko/Warum wichtig:** Auf gehosteter App (mehrere Worker) faktisch bypassbar: N Worker → N-faches Budget; Neustart (Deploy/Crash) reset. Credential-Stuffing/Brute-Force gegen Berater-/Kundenkonten praktikabel.
- **Soll / Anforderungen:** Zähler + Lockout prozess-/worker-übergreifend geteilt und restart-fest (persistent). Identische Semantik: Fenster (`login_window_seconds` 60), Max (`login_max_attempts` 5), Lockout (`login_lockout_seconds` 600), Flag `login_rate_limit_enabled` (config.py:65-68). `LoginGuardDecision`-Interface + `check`/`register_failure`/`register_success` unverändert (Aufrufer nicht anfassen). Key-Normalisierung (`strip().lower()`) bleibt. Atomares Zählen unter Nebenläufigkeit. Ablaufendes Housekeeping (kein unbegrenztes Wachstum). Fallback bei nicht verfügbarem Backend definieren (empfohlen fail-open + Log, um Total-Aussperrung zu vermeiden — dokumentieren).
- **Umsetzung (Schritte, ohne Code):**
  1. DB-gestützter Guard (keine Redis-Abhängigkeit erkennbar) — neue Tabelle `login_attempts(key, event_at)` + Lockout-Ablage (`locked_until` pro Key) über neues Modell `models/login_attempt.py`.
  2. `LoginAttemptGuard` (login_guard.py) so umbauen, dass `check`/`register_failure`/`register_success` gegen DB arbeiten; Interface unverändert. Session pro Aufruf über `database.get_bind()`/eigene Connection (Muster analog `services/account_recovery.py:31-58`, separate Connection).
  3. `check`: Einträge im Fenster zählen, abgelaufene löschen, `locked_until` lesen.
  4. `register_failure`: Eintrag einfügen; bei `>= max` `locked_until` upsert. Transaktions-Nebenläufigkeit absichern.
  5. `register_success`: alle Einträge + Lockout für den Key löschen.
  6. Tabellen-Anlage: Modell zu `Base.metadata` → `create_all` (database.py:930). Keine neuen `users`-Spalten.
  7. Lazy-Cleanup in `check`/`register_failure` (kein Scheduler nötig).
  8. `login_rate_limit_enabled=False` weiter kompletter Bypass (Tests/Tier-1).
- **Akzeptanzkriterien & Tests:** (1) Nach `max` Fehlversuchen `allowed=False`; zweiter Guard-/Session-Kontext (simuliert 2. Worker) sieht denselben Lockout (Shared-State). (2) Restart-Fest (neue Instanz gegen dieselbe DB). (3) Fenster-Ablauf → wieder `allowed=True`. (4) `register_success` = Zähler 0. (5) `login_rate_limit_enabled=False` → nie Lockout. (6) Aufruf-Signaturen in auth.py unverändert. (7) parallele `register_failure` zählen korrekt.
- **Konflikt/Koordination:** Aufrufstellen in routers/auth.py (von #299 angefasst), aber Interface stabil → Konflikte auf login_guard.py beschränkt (nicht in #299). Neues Modell + `create_all` mit Codex' etwaigem database.py-Refactor abstimmen. Interface bewusst unverändert → AUTH-03 unabhängig von #299 mergebar.

---

## 7. CF-1 / CF-2 — Cashflow-Serie Endpoint vs. Engine + Korrektheit

### CF-1 — Divergierende Cashflow-Serie zwischen Projektions-Endpoint und Engine
- **Ist-Zustand (verifiziert):** `cashflow_projection` (routers/clients.py:397-455) baut die Jahres-Serie selbst: Schleife `for offset in range(horizon)` (437-450) ruft `totals_for_year(cashflows, yr)` (439) **rein positional** — OHNE `inflation_series_bps`, OHNE `fx_source`/`target_currency` (Import nur `totals_for_year`, clients.py:25; kein `net_cashflow_series`). Default-Pfad: `inflation_factor_universal = 1.0` (nominal, cashflow_timeline.py:244-255) und `_convert_cf_amount_to_target_currency` = Rohbetrag (cashflow_timeline.py:208-209). Engine baut über `net_cashflow_series(...)` MIT `inflation_series_bps` + `fx_source`/`target_currency` (portfolio_engine.py:4400-4417 / Rebuild 6945-6965), addiert `_wealth_inflow_series_rappen` (4420-4427) + `mortgage_interest_adjustment_series` (4432-4439). Endpoint rechnet Hypothek ein (`_mort_adj`, clients.py:435), aber ohne Inflation/FX/WealthInflows. Zudem bezieht der Endpoint `_derived_cashflows_for_client` ein (424) → potenzielle **Doppelzählung** Hypothekarzins (derived Cashflow + `_mort_adj`).
- **Risiko/Warum wichtig:** Berater sieht in der Projektions-Ansicht andere Zahlen als die Engine (SAA/MC/Zielerreichung/Reserve). Endpoint zeigt real (heutige Rappen), Engine nominal (inflationiert) → über 30-40 J massiver Drift (1.5% Inflation ≈ +50% nach 27 J). FX-Cashflows unkonvertiert; Erbschaften/Boni fehlen im Endpoint. FIDLEG-Dokumentationsrisiko + Doppelansatz Hypothekarzins.
- **Soll / Anforderungen:** EINE Quelle (SSOT) für die Jahres-Netto-Serie, von Endpoint UND Engine identisch aufgerufen. Sie MUSS: (a) Inflation gemäss `is_inflation_linked` + CMA-Pfad, (b) FX auf `base_currency`, (c) WealthInflows, (d) Hypothek-Adjustment **genau einmal** (derived Cashflow ODER `_mort_adj`), (e) Vorzeichen/one-off-vs-recurring konsistent. Endpoint vs. Engine dürfen sich nur im Präsentations-Wrapping (real vs. nominal) unterscheiden — bewusst + dokumentiert.
- **Umsetzung (Schritte, ohne Code):**
  1. Neue gemeinsame Funktion in `services/cashflow_timeline.py` (z.B. `build_projection_series(...)`), die die in portfolio_engine.py:4400-4447 + 6945-6973 duplizierte Sequenz zentralisiert (Netto + Recurring inkl. Inflation, FX, Hypothek, optional WealthInflows).
  2. `cashflow_projection` (clients.py:397) darauf umstellen; CMA/Inflation + FX laden (`_inflation_path_series`, `FXRateSource.from_db`) — oder bewusst real anzeigen mit klar benanntem Deflator im Response-Schema.
  3. Doppelpfad Hypothek klären: `_derived_cashflows_for_client` (clients.py:304-312) NICHT einspeisen wenn `mortgage_interest_adjustment_series` greift (oder umgekehrt). In `services/wealth_cashflows.py` dokumentieren.
  4. Engine (`_load_allocation_inputs` ~4400, Rebuild ~6945) auf dieselbe Funktion umstellen.
- **Akzeptanzkriterien & Tests:** (1) Testklient mit inflations-verlinktem AHV + FX-Cashflow: Endpoint-Serie = Engine-Serie (nach def. real/nominal-Wrapping). (2) USD-Cashflow im Endpoint CHF-konvertiert. (3) Erbschaft Jahr 5 in Endpoint-`capital_inflow`/`net`. (4) Hypothekarzins nur einmal. (5) Snapshot-Test Endpoint vs. Engine über 40 J.
- **Konflikt/Koordination:** portfolio_engine.py von #299 UND #305 stark umgeschrieben (Bereich 4400-4447/6945-6973) → Engine-Umstellung (Schritt 4) MUSS auf Merges warten/koordinieren. Neue Funktion in cashflow_timeline.py + Endpoint in clients.py sind **nicht** in den PRs → unabhängig vorziehbar.

### CF-2 — Korrektheit Cashflow-Summary & -Projection (Inflation, one-off/recurring, Vorzeichen)
- **Ist-Zustand (verifiziert):** `cashflow_summary` (clients.py:267-301) ruft `totals_for_year(cashflows)` OHNE Jahr/Inflation (283) → nur laufendes Jahr, nominal (`target_year = date.today().year`, cashflow_timeline.py:243). `cashflow_projection` (439) ebenso ohne Inflation. Klassifikation via `_is_one_off_flow` (cashflow_timeline.py:273-286): Income one-off→`capital_inflow`, recurring→`recurring_income` (analog Expense). Vorzeichen: alle positiv, `net = income - expense` (287-297). `contribution_for_year` (92-156): `valid_until` **inklusiv** (150), `inflation_factor` auf Periodenbetrag (109). Summary bezieht derived Cashflows ein (282).
- **Risiko/Warum wichtig:** (a) Summary laufendes Jahr korrekt (Faktor 1.0), aber Projektion (437-450) zeigt inflations-verlinkte Cashflows über 40 J **nominal unverändert** → systematische Unterschätzung + Drift zur Engine. (b) `is_inflation_linked` greift in `totals_for_year` nur mit `inflation_series_bps` (252-255) → im Endpoint **wirkungslos** (Berater glaubt sie sei aktiv). (c) Cashflow mit unbekanntem `cashflow_type` fällt still aus der Aggregation (277-286) → Betrag verschwindet.
- **Soll / Anforderungen:** (1) Projektion MUSS inflations-verlinkte Cashflows nominal wachsen lassen (konsistent zur Engine, CF-1). (2) Summary darf nominal bleiben, aber als „heutige Rappen" dokumentiert. (3) Unbekannter/leerer `cashflow_type` erkennbar behandeln (Fehler/Log/Default), nicht still verschwinden. (4) `valid_until`-Inklusivität + one-off unverändert (korrekt + testabgedeckt, cashflow_timeline.py:142-145).
- **Umsetzung (Schritte, ohne Code):**
  1. `cashflow_projection` (397-455) an CF-1-Funktion koppeln (Inflation); alternativ minimal `inflation_series_bps` + `start_year` in `totals_for_year` (439) durchreichen (CMA laden).
  2. `cashflow_summary` (283) belassen (laufendes Jahr nominal), im `CashflowSummaryResponse` als „heutige Werte" kennzeichnen.
  3. In `totals_for_year` (277-286) expliziten Zweig für unbekannten `cashflow_type` (Summenerhalt).
- **Akzeptanzkriterien & Tests:** (1) AHV mit `is_inflation_linked=1` wächst (Jahr 10 > Jahr 0). (2) `=0`-Bonus konstant. (3) one-off→`capital_inflow`, recurring→`recurring_income`. (4) `valid_until`=31.12. mitgezählt, 01.01. Folgejahr nicht. (5) leerer `cashflow_type` → definierter Pfad (Summenerhalt-Assertion).
- **Konflikt/Koordination:** portfolio_engine.py nicht direkt betroffen (nur über CF-1-Funktion). clients.py + cashflow_timeline.py **nicht** in #299/#305 → unabhängig; Engine-Kopplung wartet auf Merges.

---

## 8. RES-1 / RES-2 — Reserve-Berechnung + Validierung (services/portfolio_engine.py)

### RES-1 — Korrektheit der Liquiditätsreserve
- **Ist-Zustand (verifiziert):** `_compute_reserve_for_inputs` (portfolio_engine.py:4555-4703) → `max(reserve_candidates)` (4675). Near-Term nur aus ersten 3 Jahren: `near_term_cashflow_series = (...recurring...)[:3]` (4586), `near_term_shortfall = max(0, -sum(...) - max(0, near_term_inflows))` (4598). Fallback `abs(recurring_net) * 3` nur wenn `near_term_inflows <= 0` (4603-4606). Spending-Goals summiert (`goal_reserve_sum`, 4613-4674) mit Stufenfunktion (≤3 J voll, ≤7 J halb, sonst 0; 4665-4671), AHV-gedeckte ausgelassen (4620-4627), bedingte mit Wahrscheinlichkeit skaliert (4634-4635). Goal-Block als eigener Kandidat in `max()` (4673-4674) → konkurriert mit Cashflow-Shortfall statt zu addieren.
- **Risiko/Warum wichtig:** (a) `max()` mischt recurring + near-term: Kunde mit Verzehr UND Nahziel → nur der grössere zählt → systematische **Unterreservierung**. (b) `[:3]` ignoriert Verzehr ab Jahr 5+ (typisch Pension) → Shortfall 0 trotz absehbarem Bedarf. (c) Fallback greift nicht sobald ein kleiner Inflow in den ersten 3 J liegt (4603) → Kleinbetrag hebelt 3-J-Verzehrsreserve aus. (d) Inflows doppelt gegengerechnet (4598 + 4603). Alle → zu niedrige Reserve → Zwangsverkäufe bei Marktstress; Beratungs-/Haftungsfrage.
- **Soll / Anforderungen:** (1) Cashflow-Shortfall + Goal-Bedarf desselben Zeitraums **additiv**, nicht `max()`. (2) Near-Term-Horizont bildet echten Verzehrsbeginn ab (nicht starre 3 J). (3) WealthInflows reduzieren nur **einmal**. (4) Fallback nicht binär abschaltbar durch Kleinst-Inflow — Betrag verrechnen. (5) Reserve = Floor-Kandidaten (manuell/Liquiditätsziel) via `max()`, Bedarfs-Kandidaten (Shortfall + Goals) additiv (konsistent zum `#AA-8`-Prinzip 4608-4612).
- **Umsetzung (Schritte, ohne Code):**
  1. Kombinationslogik trennen: Floor-Kandidaten (`manual_reserve`, `liquidity_target`) `max()`; separater Bedarfsbetrag = `near_term_shortfall + goal_reserve_sum` gegen Floors ge-`max()`t (4675). Doppelzählung Inflow/Goal prüfen.
  2. `[:3]` (4586) durch bedarfsgerechten Horizont ersetzen (Fenster bis erstes nachhaltig-negatives Jahr oder konfigurierbarer Reserve-Horizont), koordiniert mit Decay/Bucket-Logik (4644-4664).
  3. Fallback-Gate (4603) von binär auf betragsverrechnend; doppelte Inflow-Gegenrechnung (4598 + 4603) auf eine Stelle konsolidieren.
- **Akzeptanzkriterien & Tests:** (1) Verzehr + Nahziel → `shortfall + goal`, nicht `max`. (2) Verzehr ab Jahr 5 → Reserve > 0. (3) Kleinst-Inflow (1'000) bei starkem Verzehr → Reserve nicht 0. (4) Inflow reduziert exakt um seinen Betrag (nicht doppelt). (5) Floor bleibt greifbar wenn > Bedarf.
- **Konflikt/Koordination:** portfolio_engine.py (4555-4703) von #299 UND #305 stark umgeschrieben → **auf Merges warten**; danach gegen gemergten Stand real re-verifizieren.

### RES-2 — Validierungslücken bei Reserve-Inputs/-Verwendung
- **Ist-Zustand (verifiziert):** `reserve_candidates` startet `[0]` (4578); `manual_reserve`/`liquidity_target` via `_parse_rappen` (4579-4580), nur bei truthy angehängt (4581-4584) — **keine Negativ-Prüfung**. Serien defensiv `int(value or 0)` (4586, 4594-4597), aber **keine Längen-Prüfung** (< 3 Elemente → unvollständiger Bedarf, ohne Hinweis). Bei `reserve_needed <= 0 or advisory_wealth <= 0` früher Return `(reserve_needed, 0)` (4677-4678) → bei Null/negativem Beratungsvermögen keine externe Reserve trotz realem Bedarf. `saa_reserve_rappen` (4682) = `saa_liquidity_ceiling_bps * advisory_wealth / 10000` ohne Range-Prüfung [0..10000]. `_investable_advisory_wealth_rappen` (4884-4885) klemmt `max(0,...)`, aber keine Prüfung `external_reserve <= advisory_wealth`.
- **Risiko/Warum wichtig:** Fehlerhafte/fehlende Eingaben (negatives `minReserve`, unplausibles Ceiling, leere Serie, Null-Beratungsvermögen) → **still** falsche Reserve-Zahlen. Diese fliessen in SAA-Liquiditätsquote (4861-4880) + `_investable_advisory_wealth_rappen` → verfälschen die gesamte Zielallokation. Keine Fehlermeldung → Berater bemerkt Fehleingabe nicht.
- **Soll / Anforderungen:** (1) `manual_reserve`/`liquidity_target` auf `>= 0`; negative verwerfen + loggen/`reasoning`. (2) `saa_liquidity_ceiling_bps` auf [0..10000] klemmen. (3) Serien-Länge prüfen; kürzere dokumentieren. (4) `advisory_wealth <= 0` bei `reserve_needed > 0` → volle externe Reserve statt stillem 0 + `reasoning`. (5) `external_reserve <= advisory_wealth` gelten oder Sonderfall melden.
- **Umsetzung (Schritte, ohne Code):**
  1. Nach `_parse_rappen` (4578-4584) Negativ-Guard (`max(0,...)`), Verwerfen ins `reasoning`.
  2. `saa_liquidity_ceiling_bps` beim Eintritt klemmen (4680-4682 absichern).
  3. Früher Return (4677-4678): bei `reserve_needed > 0` + `advisory_wealth <= 0` vollen Bedarf als externe Reserve + `reasoning`.
  4. Bei `_investable_advisory_wealth_rappen` (4884-4885) Guard `external_reserve <= advisory_wealth`, sonst definierter Sonderfall (0 investierbar + Hinweis).
  5. Längen-Guard für near-term-Serie (4586).
- **Akzeptanzkriterien & Tests:** (1) Negatives `minReserve` verworfen + `reasoning`. (2) Ceiling 12000 → 10000 geklemmt. (3) `advisory_wealth=0` + `reserve_needed>0` → (reserve_needed, reserve_needed) + `reasoning`. (4) 1-Element-Serie → dokumentiert, kein IndexError. (5) `external_reserve > advisory_wealth` → investierbar 0 + Hinweis, kein negativer Zwischenwert.
- **Konflikt/Koordination:** Alle Stellen in portfolio_engine.py (#299/#305) → **auf Merges warten**, danach real re-verifizieren.

---

## 9. RT-2 + SEC-2 — Tax-Override-Validierung + update_user-Scope

### RT-2 — Plausibilitäts-/Wertebereichs-Validierung von Tax-Overrides erzwingen
- **Ist-Zustand (verifiziert):** `apply_overrides()` (services/tax/overrides.py:37-46) ruft direkt `regime.with_overrides(parsed_dict)`, sobald `parse_overrides_json()` (17-34) ein nicht-leeres Dict liefert. `parse_overrides_json` filtert nur Typ (`isinstance(v,(int,float))`) + String-Keys — **keine Wertebereichs-Prüfung**. `with_overrides()` (regimes/generic.py:142-156) übernimmt jeden bekannten Key ungeprüft via `replace(self, **applied, ...)`; z.B. `wealth_tax_bps_pa = -5000` fliesst in `annual_wealth_tax()` (generic.py:69-72). `validate_parameters()` (generic.py:125-138) + `validate_all()` (overrides.py:49-57) existieren, sind aber rein **advisory** (nur `tuple[str,...]` Warnungen) und werden von `apply_overrides()` nie aufgerufen. Unbekannte Keys werden von `with_overrides` still geschluckt (Tippfehler bleibt wirkungslos, unbemerkt).
- **Risiko/Warum wichtig:** Tax-Overrides fliessen in Netto-Renditen, Verzehr, Zielerreichung. Negativer Satz = fiktiver Ertrag (schönt Projektion); >100% = Steuer > Vermögen (unbrauchbare Verzehr-Kurve). Vertippter Key wird still ignoriert → Berater glaubt Override aktiv. Stille Fehlberatung ohne Audit-Spur.
- **Soll / Anforderungen:** Kein Wert ausserhalb plausiblem Bereich anwendbar. Hart (Reject): negative `*_bps*`; > 10000 bps (>100%); NaN/Inf. Weich (Warnung, anwendbar): > 5000 bps (>50%). Unbekannte Keys erkennbar melden (nicht still). Edge: leerer/`None` → unverändert; malformed JSON → nicht crashen, aber Verwerfung sichtbar; `interest_tax_bps=None` bleibt gültig (Fallback). Validierung an EINER unumgehbaren Stelle.
- **Umsetzung (Schritte, ohne Code):**
  1. `generic.py` `validate_parameters()` (125-138) um Klassifikation *hart ungültig* vs. *nur ungewöhnlich* erweitern (oder Schwester `classify_parameters()`). Signatur in `services/tax/base.py` spiegeln.
  2. `overrides.py` `apply_overrides()` (37-46) VOR `with_overrides` harte Validierung aufrufen. Bei hart ungültig: empfohlen **Reject des gesamten Sets** (Exception `TaxOverrideValidationError` mit Verstoss-Liste), keine halbgültigen Regimes.
  3. `parse_overrides_json()` (17-34): bei malformed JSON Verwerfung dem Aufrufer melden (Warnliste/Log), nicht still `{}`. Echtes leeres Input → `{}` beibehalten.
  4. Persistierungs-Endpoint (nutzt `validate_all`): hart ungültige Overrides → HTTP 422; unbekannte Keys → 422 oder sichtbare Warnung. Endpoint via Grep `validate_all`/`tax_overrides_json` lokalisieren.
  5. Nach zentraler Validierung kann `with_overrides` (142-156) von validen Keys ausgehen; Tippfehler-Toleranz → explizite Meldung.
- **Akzeptanzkriterien & Tests:** `wealth_tax_bps_pa=-100` nicht angewendet (Default 0.0). `dividend_tax_bps=20000` abgelehnt. `dividend_tax_bps=6000` angewendet + Warnung. `wealth_tax_bpps_pa=100` (Tippfehler) → nicht angewendet + „unbekannter Key". `None`/`''` → identisches Regime, keine Warnung. `'not json'` → kein Crash, Verwerfung beobachtbar. NaN/Inf abgelehnt. Endpoint → 422 mit Keys. `interest_tax_bps: null` gültig.
- **Konflikt/Koordination:** Vollständig in services/tax/* (#305) → **auf #305 warten**; fachliche Anforderung (hart/weich, Bereiche) auf die neue Regime-Struktur übertragen.

### SEC-2 — Advisor-übergreifende Sichtbarkeit/Änderung von Usern
- **Ist-Zustand (verifiziert):** `update_user` (routers/auth.py:560, `Depends(require_admin)`) lädt Ziel-User ohne Scope (562), prüft inline (568-576): `visible = (ttid == utid) or ((not strict) and ttid == "")` → 404 wenn nicht sichtbar. `_assert_user_visible_to` (services/auth.py:629-642, genutzt in `resend_invite` auth.py:657) hat dieselbe Logik. **Zwei Lücken:** (1) User-OHNE-Tenant-Bypass: ist `utid` leer (Legacy-Admin), Prüfung komplett übersprungen (auth.py:570 `if utid:`; services/auth.py:635-636 `if not utid: return`) → tenantloser Admin darf JEDEN ändern. (2) NULL-Ziel im Non-Strict: `(not strict) and ttid == ""` erlaubt Änderung herrenloser NULL-User. `reset_user_password` (auth.py:597-626) prüft Rolle, ruft `_assert_user_visible_to` **nicht** → Admin-Reset fremder Tenant-User möglich.
- **Risiko/Warum wichtig:** Privilege-/Mandantentrennungs-Bruch. Tenantloser Admin kann firmenübergreifend Rollen/Status ändern (Privilege-Escalation auf `super_admin`). Fehlender Reset-Guard → Firmen-Admin resettet Passwörter fremder Firmen (Account-Takeover). FINMA/FIDLEG: schwerer Kontrollmangel.
- **Soll / Anforderungen:** Nicht-`super_admin`-Admin nur User des EIGENEN Tenants sehen/ändern/resetten. Admin OHNE `tenant_id` im Strict/Multi → kein fremder User. NULL-Ziel im Strict nicht sichtbar/änderbar (konsistent rls-1). `reset_user_password` MUSS denselben Scope-Guard durchlaufen. Rollen-Eskalations-Schutz: `admin` darf keinem User `super_admin` zuweisen (nur `super_admin`). Einheitliche 404 (kein Existenz-Leak).
- **Umsetzung (Schritte, ohne Code):**
  1. Inline-Prüfung in `update_user` (568-576) durch `_assert_user_visible_to(current_user, user)` ersetzen (eine Quelle).
  2. In `_assert_user_visible_to` frühen `return` bei leerem `utid` (services/auth.py:635-636) so anpassen, dass im effektiven Strict-Modus (Helper aus rls-1) tenantloser Admin keinen Nicht-eigenen User sieht (404).
  3. NULL-Ziel härten: `(not strict) and ttid == ""` (services/auth.py:640; routers/auth.py:574) an effektiven-Strict-Helper koppeln.
  4. Reset-Guard: in `reset_user_password` (597) nach Laden (608-610) im Nicht-Self-Fall `_assert_user_visible_to(current_user, user)` vor `password_hash`-Set.
  5. Rollen-Eskalation: in Feld-Schleife (582-589) bei `field=="role"` + `value=="super_admin"` → 403 wenn `current_user.role != "super_admin"`.
  6. Keine Migration; nutzt effektiven-Strict-Helper aus rls-1.
- **Akzeptanzkriterien & Tests:** Admin `firma-a` → `update_user` fremd (`firma-b`) = 404, keine Änderung. Tenantloser Admin im Strict → 404 fremd; Non-Strict-Tier-1 unverändert. `reset_user_password` fremd → 404, `password_hash` unverändert; Self-Reset erlaubt. Admin setzt `super_admin` → 403; `super_admin` darf. Konsistenz: `update_user`/`resend_invite`/`reset` identisch 404 (gemeinsamer Helper).
- **Konflikt/Koordination:** services/auth.py ist #299-Territorium; `_assert_user_visible_to` + effektiver-Strict-Helper überschneiden rls-1 + #299. SEC-2 NACH rls-1 + koordiniert mit #299. Reine routers/auth.py-Teile (Reset-Guard, Rollen-Check, Zentralisierung) konfliktarm; `_assert_user_visible_to`-Änderung mit #299/rls-1 abstimmen.

---

## 10. Report-Fallback — Symmetrischer Fallback für „Anderes Vermögen" (Frontend)

- **Ist-Zustand (verifiziert):** Im Report-Builder „Vermögensübersicht" (5eyes-electron/frontend/5eyes_v2.html) kommen die Buckets aus `wealthPositions()` (7799-7804) → gefiltert nach `assignment` (7809-7811). Beratungsvermögen hat Fallback, die anderen nicht: `advisoryTotalRappen = sumPositions(advisoryPositions) || Math.round(Number(allocation && allocation.advisory_wealth_rappen || 0))` (7812); `otherTotalRappen = sumPositions(otherPositions)` (7813, **kein Fallback**); `liabilitiesRappen = sumPositions(liabilities)` (7814, **kein Fallback**). Positionen aus `activeClientWealthPositions()` → `clientScopedItems(currentWealthPositions, currentClientId)` (6174-6181, 6197-6199), harter Filter `client_id === activeId` (6178-6179). Bei Client-Wechsel vor Reload (async in `loadClient`, 5093-5100/5140) oder `client_id`-Mismatch → leere Liste → `otherTotalRappen=0`, während advisory dank Fallback eine Zahl zeigt. Ausgabe: `Total Beratungsvermögen` (8031) vs. `Total Anderes Vermögen netto = Math.max(0, otherTotalRappen - liabilitiesRappen)` (8034) → Beratung plausibel, Anderes CHF 0. Das `allocation`-Objekt hat **kein** `other_wealth`-Feld (schemas/allocation.py:749). Das `wealth-summary`-Endpoint liefert `gross_wealth_rappen`, `liabilities_rappen`, `advisory_wealth_rappen` (schemas/clients.py:133-145), wird in `loadClient` (5095) + `refreshWealthUI` (21479) gefetcht, aber das Ergebnis wird **nirgends** in eine persistente Variable gecacht (nur KPI-DOM, 5124-5131 / 21484-21496); es gibt kein `currentWealthSummary`-Global.
- **Risiko/Warum wichtig:** Der PDF-Bericht ist ein kundenverbindliches FIDLEG-Dokument. Beratungsvermögen korrekt, „Anderes Vermögen" fälschlich CHF 0 → intern inkonsistent (`totalGrossRappen = advisory + other`, 7815, zu niedrig), potenziell irreführend. Tritt in Race Client-Wechsel-dann-Report auf → nicht offensichtlich, kann in unterschriebenen Bericht gelangen.
- **Soll / Anforderungen:** „Anderes Vermögen" + Verbindlichkeiten gleicher Robustheits-Grad wie Beratungsvermögen (symmetrischer Fallback). Geladene Positionen bleiben Primärquelle (Normalfall unverändert). Leere/nicht geladene Liste → „Anderes Vermögen" aus `gross_wealth_rappen − advisory_wealth_rappen − liabilities_rappen` (wealth-summary, `Math.max(0,…)`). Edge: kein Summary → keinen positiven Wert erfinden (konsistent 0). Client-Mismatch (`clientScopedSummary`=null, 6183-6188) respektieren. Verbindlichkeiten positiv abziehen.
- **Umsetzung (Schritte, ohne Code):**
  1. Wealth-Summary cachen: in `loadClient` (5124-5131) + `refreshWealthUI` (21484-21497) das Summary-Objekt zusätzlich in neues Global `currentWealthSummary` schreiben (analog `currentCashflowSummary`, 5132-5134). Beim Client-Wechsel/Reset `currentWealthSummary = null`.
  2. Accessor `activeClientWealthSummary()` (analog `activeClientCashflowSummary()`, 6205-6207) → `clientScopedSummary(currentWealthSummary, currentClientId)` (erbt Client-Mismatch-Schutz, 6183-6188).
  3. Im Report-Builder (7812-7815) symmetrisch: `otherTotalRappen = sumPositions(otherPositions) || max(0, gross − advisory − liabilities)` via `activeClientWealthSummary()`; `liabilitiesRappen`-Fallback auf `summary.liabilities_rappen`. Fallback nur bei wirklich leerer `otherPositions` (gleiche `||`-Semantik).
  4. `advisoryTotalRappen`-Fallback (7812) optional konsistent aus derselben Summary-Quelle speisen (statt `allocation` vs. Positionen zu mischen).
  5. `totalGrossRappen` (7815) + Ausgabezeilen (8031-8034) profitieren automatisch — verifizieren.
- **Akzeptanzkriterien & Tests:** (1) Geladene Positionen → Report unverändert (Positionswerte bevorzugt). (2) Client-Wechsel-dann-Report: `otherTotalRappen = gross − advisory − liabilities` (>0), nicht 0; konsistent mit KPI-Reinvermögen. (3) `currentWealthSummary=null` ODER fremder Client → kein positiver „Anderes"-Wert. (4) Verbindlichkeiten korrekt abgezogen, nie negativ (`Math.max(0,…)`). (5) `activeClientWealthSummary()` für falschen Client = null.
- **Konflikt/Koordination:** Vollständig im Frontend-Monolith (Report-Builder + loadClient/refreshWealthUI + Accessor). **Konfliktfrei** (keine Backend-/Schema-Änderung; wealth-summary liefert alle Felder bereits).

---

## Zusammenfassung Umsetzungs-Reihenfolge

1. **Jetzt (konfliktfrei):** SEC-1 (#1) → AB-1 (#5a) → Report-Fallback (#10). Zusätzlich vorziehbar: CF-1/CF-2 **Endpoint-Teil** (neue Funktion in cashflow_timeline.py + clients.py), AUTH-03 **login_guard-Teil**.
2. **Nach #299-Merge (RLS/auth/config):** rls-1 (#2) → SEC-2 (#9b) ; AUTH-01 (#3) + AUTH-02 (#4) gebündelt ; AB-2 (#5b, config.py) ; AUTH-03 Aufrufer-Verifikation.
3. **Nach #305-Merge (tax/portfolio_engine):** RT-2 (#9a) ; CF-1/CF-2 **Engine-Teil** ; RES-1 (#8a) ; RES-2 (#8b).

**Wurzel-Prinzip:** SEC-1 zuerst — es erzeugt die herrenlosen NULL-Tenant-User, die rls-1 (Leak) und SEC-2 (Bypass) verschärfen. NOT-NULL-Migration (rls-1) setzt voraus, dass SEC-1 + Backfill keine neuen NULL-Rows mehr erzeugen.
