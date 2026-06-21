# Spec #5 — HttpOnly-Cookie-Migration statt JWT in localStorage

**Status:** offen (KRITISCH-Rest aus altem #7). Breaking-Change → eigener Sprint mit Migrationspfad.
**Erstellt:** 2026-06-21 (autonomer Spec-Sprint). Alle file:line per Read/Grep am echten Code verifiziert.
**Branch-Vorschlag:** `codex/u5-httponly-cookie`

---

## 1. Ziel
JWT von sessionStorage/localStorage in ein **HttpOnly+Secure+SameSite-Cookie** (`5eyes_access`) verschieben + lesbares `5eyes_csrf`-Cookie für **Double-Submit-CSRF-Schutz**. Backend liest Token aus Cookie ODER Bearer-Header (Fallback). FE-Fetch auf `credentials:'include'` + `X-CSRF-Token`. **Bestandssessions dürfen nicht brechen.**

## 2. Verifizierter IST-Zustand (file:line)
- Backend Auth: `services/auth.py:15` (bearer_scheme), `:29-45`, `:64-69`, `:72-120` (get_current_user, Decode/Exp/sub/Tenant-Cross-Check `:110-119`), `:268-306` (get_current_tenant_id).
- Auth-Router: `routers/auth.py:60-66`, `:112-173` (login), `:181-183` (logout), `:521-535` (invite accept).
- App/Middleware: `main.py:108-115` (CORS), `:190-202`. Config: `config.py:62-82`, Prod-Validator-Muster `:389-398`.
- Frontend: `5eyes_v2.html:4633-4719` (API.fetch), `:11037-11068` (Reporting-App-Öffnen), `:19895-19902` (PDF-Download); `desktop-api.js:18-30` (apiFetch).
- Electron: `main.js:182-228`, `:456-465`, `:502-504`; `preload.js:9-11` (safeStorage-Bridge).

## 3. SOLL-Design
- **Cookies:** `5eyes_access` (HttpOnly, Secure, SameSite) + `5eyes_csrf` (lesbar, nicht HttpOnly).
- **CSRF:** Double-Submit — Header `X-CSRF-Token` muss `5eyes_csrf`-Cookie matchen, nur bei POST/PUT/PATCH/DELETE; skip wenn nur Bearer-Header (kein Cookie) genutzt wird; skip Login/Bootstrap/Invite/Password-Reset.
- **Token-Quelle:** `_extract_token()` — Cookie zuerst, dann Bearer-Header (Übergangs-Fallback).
- **Electron-Spezifikum:** `file://` → `127.0.0.1` ist cross-origin → braucht `SameSite=None`+`Secure`; akzeptabel weil `127.0.0.1` als "trustworthy origin" gilt.

## 4. Implementierung (additiv, kein Bruch) — siehe Codex-Prompt
3-Phasen-Migration: Phase 0 = Cookie zusätzlich setzen, Token bleibt auch im Body + Header-Fallback bleibt → keine Bestandssession bricht. Phase 1 = FE primär Cookie. Phase 2 (später) = access_token aus Body entfernen.

Neue Dateien: `services/csrf.py`, `tests/test_httponly_cookie_auth.py`. Neue Config-Settings in `config.py`.

## 5. Test-Plan (14 Fälle, §8.1)
Cookie-only-Auth · Header-Fallback · CSRF required/match/mismatch/skip-bei-Header · login nicht CSRF-geschützt · logout clears cookies · tid-Cross-Check via Cookie · disabled-Flag · samesite=none erzwingt secure. Regression grün halten: test_auth_tenant_aware.py, test_2fa_login.py, test_login_guard.py, test_tenant_endpoint_leak_regression.py.

## 6. Edge-Cases (7)
Cookie+Header gleichzeitig (Cookie gewinnt) · abgelaufenes Cookie · CSRF-Cookie fehlt aber Header da · Electron file://-Origin · Reporting-Sub-App Token-Handoff · Logout ohne Cookie · disabled-Flag-Pfad.

## 7. OWNER-DECISIONS (5)
1. SameSite-Wert (None für Electron vs Strict/Lax). 2. Refresh-Token jetzt (→ siehe Spec #28) oder später. 3. Reporting-App Token-Handoff: Cookie vs Fragment (vorerst Fragment lassen). 4. Token aus Body entfernen — wann (Phase 2). 5. Server-Side-Token-Blocklist ja/nein.

## 8. NICHT TUN (v1)
Kein Refresh-Token (separat #28), keine Token-Blocklist, access_token NICHT aus Body entfernen (erst Phase 2). Vor jedem Commit: `git branch --show-current` prüfen.

---

## Codex-Prompt
```text
BRANCH: codex/u5-httponly-cookie
AUFGABE: Roadmap #5 HttpOnly-Cookie-Migration exakt nach docs/planning/2026-06-21-spec-05-httponly-cookie-auth.md.
REIHENFOLGE (additiv, kein Bruch):
1) config.py (~Z.62-69): auth_cookie_enabled, auth_cookie_name='5eyes_access', csrf_cookie_name='5eyes_csrf',
   csrf_header_name='X-CSRF-Token', cookie_secure, cookie_samesite, cookie_domain, csrf_protect_enabled,
   cookie_sliding_renew. Validator: production→secure=True; samesite='none'→secure=True (analog :389-398).
2) services/auth.py: Z.15 HTTPBearer(auto_error=False); _extract_token(request,credentials) Cookie zuerst dann Header;
   get_current_user (:72-120) + get_current_tenant_id (:268-306) auf _extract_token (Decode/Tenant-Check :110-119 unverändert);
   set_auth_cookies(response,token) (access HttpOnly, csrf lesbar, returnt csrf) + clear_auth_cookies(response).
3) services/csrf.py (NEU) + main.py NACH CORS (:108-115): BaseHTTPMiddleware, nur POST/PUT/PATCH/DELETE,
   skip wenn kein Auth-Cookie, skip /auth/login,/auth/bootstrap-admin,/auth/invite/accept,/auth/password-reset/*;
   sonst X-CSRF-Token==Cookie 5eyes_csrf sonst 403.
4) routers/auth.py: _issue_token_response(user,response) ruft set_auth_cookies wenn enabled, Token BLEIBT im Body;
   response: Response in bootstrap_admin(:88)/login(:112)/invite_accept(:521); logout(:181-183) clear_auth_cookies.
5) 5eyes_v2.html: API.fetch(:4662-4719) credentials:'include' + Header-Fallback + getCsrfToken() aus document.cookie
   + X-CSRF-Token bei Schreib-Methoden; downloadServerPdf(:19895-19902 + Retry) credentials:'include';
   openReportingApp(:11066) Fragment lassen (OWNER-DECISION-3).
6) desktop-api.js apiFetch(:18-30): credentials:'include'.
7) main.js/preload.js safeStorage-Bridge UNVERÄNDERT (Fallback); Electron-Start COOKIE_SAMESITE=none + COOKIE_SECURE=true.
TESTS: tests/test_httponly_cookie_auth.py 14 Fälle (§8.1). Regression grün:
test_auth_tenant_aware/test_2fa_login/test_login_guard/test_tenant_endpoint_leak_regression.
NICHT TUN: kein Refresh-Token (v1), keine Blocklist, access_token NICHT aus Body entfernen (Phase 2).
VOR COMMIT: git branch --show-current == codex/u5-httponly-cookie.
```
