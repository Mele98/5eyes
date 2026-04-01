# Claude Spec — Benutzerverwaltung (Admin)

## Meta

- Titel: Benutzerverwaltung — Liste, Bearbeiten, Deaktivieren, Passwort-Reset
- Datum: 2026-04-01
- Owner: Emanuele
- Branch-Vorschlag: `codex/user-management`

## Ziel

Der Admin kann im Admin-Modal bestehende Benutzer auflisten, bearbeiten (Name, E-Mail, Rolle), deaktivieren/reaktivieren und das Passwort zurücksetzen. Heute existiert nur "Neuer Benutzer anlegen" — sobald ein User angelegt ist, gibt es keine Verwaltungsmöglichkeit im UI. Die App muss im Produktionsbetrieb wartbar sein ohne direkten DB-Zugriff.

## Problem

- `GET /users` und `PUT /users/{id}` existieren im Backend, sind aber nicht im Frontend verdrahtet.
- Kein Endpoint für Passwort-Reset durch Admin (`PUT /users/{id}/password` fehlt).
- Admin kann Benutzer nicht sehen, deaktivieren oder dessen Passwort ändern.
- `is_active`-Toggle ist im `UserUpdate`-Schema vorhanden, aber nicht erreichbar per UI.

## Scope

- **Backend:** Neuer Endpoint `PUT /users/{user_id}/password` (admin-only, setzt neues Passwort-Hash)
- **Backend:** Neues Schema `UserPasswordReset` (ein Feld: `new_password: str`, min. 10 Zeichen)
- **Frontend:** Benutzerliste im Admin-Modal (unterhalb "Neuer Benutzer anlegen")
- **Frontend:** Inline-Bearbeitung pro User: Name, E-Mail, Rolle, Aktiv-Toggle
- **Frontend:** Passwort-Reset-Formular pro User (Inline-Expand oder Mini-Formular)
- **Frontend:** Eigenes Konto kann nicht deaktiviert oder gelöscht werden (Guard: `user.id === currentUserId`)
- **Backend-Tests:** 4 neue Testfälle für den neuen Endpoint

## Nicht-Scope

- Self-service Passwort-Änderung (Benutzer ändert eigenes Passwort) — separates Feature
- Soft-Delete von Benutzern — separates Feature
- E-Mail-Versand oder Benachrichtigungen

## Fachlogik

- **Verbindliche Regeln:**
  - Admin kann nie sein eigenes Konto deaktivieren (`is_active = 0`) — 400 mit "Eigenes Konto kann nicht deaktiviert werden"
  - Admin kann eigene Rolle nicht ändern — 400 mit "Eigene Rolle kann nicht geändert werden"  
  - Passwort-Reset erfordert `new_password` mit min. 10 Zeichen — 422 falls kürzer
  - Nur `role=admin` darf `PUT /users/{id}/password` aufrufen (`require_admin`)
  - Passwort-Reset auf soft-gelöschten oder nicht gefundenen User → 404
- **Inferenz:** `is_active == 0` bedeutet deaktiviert (Login schlägt fehl, User bleibt in DB)
- **Owner-Decisions:**
  - OWNER-DECISION 1: Darf Admin auch seine eigene Rolle auf "readonly" setzen? (Claude-Empfehlung: Nein, gleiche Guard wie für is_active)
  - OWNER-DECISION 2: Soll deaktivierter Benutzer sofort ausgeloggt werden (Token invalidiert), oder läuft laufende Session bis zum Ablauf? (Claude-Empfehlung: Läuft bis Ablauf — kein Token-Blacklist, Desktop-App, simpler)

## Betroffene Module / Dateien

- **Backend:**
  - `5eyes-backend/schemas/users.py` — neues `UserPasswordReset`
  - `5eyes-backend/routers/auth.py` — neuer `PUT /users/{user_id}/password` Endpoint; Guards in `PUT /users/{user_id}` für eigene-Rolle und eigene-Deaktivierung
  - `5eyes-backend/tests/test_user_management.py` — neue Testdatei (neu anlegen)
  - `5eyes-backend/tests/test_runtime_contracts.py` — neuer Route-Eintrag prüfen
- **Frontend:**
  - `5eyes-electron/frontend/5eyes_v2.html` — neuer Abschnitt im Admin-Modal (unter "Neuer Benutzer anlegen")
- **Datenmodell:** Keine Änderung (Felder bereits vorhanden)

## API / Schnittstellen

### Neuer Endpoint

```
PUT /users/{user_id}/password
Requires: admin
Body:   { "new_password": "mindestens10zeichen" }
200:    UserResponse  (wie PUT /users/{id})
400:    "Passwort muss mindestens 10 Zeichen lang sein"  [falls Schema-Validator nicht greift]
404:    "Benutzer nicht gefunden"
422:    Pydantic-Validierungsfehler bei zu kurzem Passwort
```

### Guards in bestehendem Endpoint

```
PUT /users/{user_id}
Zusätzliche Guards (vor dem Update):
  - if user_id == current_user.id and body.is_active == False → 400 "Eigenes Konto kann nicht deaktiviert werden"
  - if user_id == current_user.id and body.role is not None → 400 "Eigene Rolle kann nicht geändert werden"
```

### Neues Schema

```python
# in schemas/users.py
class UserPasswordReset(BaseModel):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError('password must be at least 10 characters long')
        return value
```

## UI / UX

### Benutzerliste im Admin-Modal

Position: Im `<div class="mfooter">` des Admin-Modals (`id="m-admin"`), **vor** dem "Neuer Benutzer anlegen"-Block.

```
┌────────────────────────────────────────────────┐
│ BENUTZER                                        │
│ ┌──────────────────────────────────────────┐   │
│ │ Max Muster · admin · aktiv  [Bearbeiten] │   │
│ │ Anna Meier · advisor · aktiv [Bearbeiten]│   │
│ │ Tom Huber  · readonly · inaktiv [Bearb.] │   │
│ └──────────────────────────────────────────┘   │
│ [Laden...]                                      │
└────────────────────────────────────────────────┘
```

- Jede Zeile: `full_name · role · aktiv/inaktiv` + Button "Bearbeiten"
- Eigene Zeile: kein Deaktivieren/Rollenwechsel (Button trotzdem sichtbar, aber diese Felder disabled)
- "Bearbeiten" öffnet Inline-Expand (div unter der Zeile, nicht Modal-in-Modal):
  ```
  [Vollständiger Name] [E-Mail] [Rolle ▼] [Aktiv ✓]  [Speichern] [Passwort zurücksetzen ▼]
  ```
- "Passwort zurücksetzen ▼" klappt ein Mini-Formular auf:
  ```
  Neues Passwort: [__________]  [Setzen]
  ```

### Ladeverhalten

- Benutzerliste lädt beim Öffnen des Admin-Modals (analog zu `loadAdminMarketStatus`)
- Funktion: `loadAdminUserList()` → `GET /users`
- Nach erfolgreichem Speichern/Passwort-Reset: Liste neu laden

### Fehlermeldungen

- Fehler pro User-Zeile in einem `<div id="ul-error-{userId}">` (nicht globaler Error)
- Eigene-Konto-Guard: Felder `rolle` und `aktiv` sind `disabled`, Tooltip "Eigenes Konto"

### XSS-Sicherheit

- Alle Benutzer-Strings (full_name, username, email) via `escapeHtml()` (definiert auf Zeile 4785 im HTML)
- Keine `innerHTML` mit User-Daten — `textContent` oder `escapeHtml()` in HTML-Template-Strings

## Akzeptanzkriterien

1. `PUT /users/{id}/password` setzt neuen Passwort-Hash; Login mit neuem Passwort funktioniert
2. `PUT /users/{id}` mit `is_active: false` auf eigenem Account → 400
3. `PUT /users/{id}` mit `role: "readonly"` auf eigenem Account → 400
4. Benutzerliste im Admin-Modal zeigt alle aktiven User korrekt an
5. Deaktivieren eines anderen Users via Toggle → `is_active = 0` in DB, Login schlägt danach fehl (401)
6. Passwort-Reset per Admin auf anderen User funktioniert

## Testfälle

**Neue Datei: `5eyes-backend/tests/test_user_management.py`**

- `test_admin_can_reset_password` — PUT /users/{id}/password → 200, Login mit neuem PW erfolgreich
- `test_password_reset_requires_min_length` — PUT /users/{id}/password mit 9-Zeichen-PW → 422
- `test_password_reset_returns_404_for_unknown_user` — PUT /users/unknown/password → 404
- `test_cannot_deactivate_own_account` — PUT /users/{own_id} mit `is_active: false` → 400
- `test_cannot_change_own_role` — PUT /users/{own_id} mit `role: "readonly"` → 400
- `test_can_deactivate_other_user` — PUT /users/{other_id} mit `is_active: false` → 200
- `test_deactivated_user_cannot_login` — nach Deaktivierung → POST /auth/login → 401

**`5eyes-backend/tests/test_runtime_contracts.py`** (bestehend):
- Eintrag hinzufügen: `assert ("/users/{user_id}/password", ("PUT",)) in route_map`

## Implementierungsdetails für Codex

### Backend: `schemas/users.py`

Neues Schema am Ende der Datei einfügen (vor oder nach `TokenResponse`):

```python
class UserPasswordReset(BaseModel):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError('password must be at least 10 characters long')
        return value
```

### Backend: `routers/auth.py`

**1. Import ergänzen:**
```python
from schemas.users import (
    UserCreate, UserUpdate, UserResponse, UserPasswordReset,
    AdviserRegistrationCreate, AdviserRegistrationResponse,
    BootstrapStatusResponse, BootstrapAdminRequest, LoginRequest, TokenResponse
)
```

**2. Guards in `update_user` (Funktion bei Zeile ~171) am Anfang des Funktionskörpers einfügen, nach dem `if not user:` Check:**
```python
    # Eigenes Konto: Deaktivierung und Rollenwechsel verboten
    if user_id == current_user.id:
        if body.is_active is not None and not body.is_active:
            raise HTTPException(status_code=400, detail="Eigenes Konto kann nicht deaktiviert werden")
        if body.role is not None:
            raise HTTPException(status_code=400, detail="Eigene Rolle kann nicht geändert werden")
```

**3. Neuer Endpoint nach `update_user`, vor `get_adviser_registration`:**
```python
@users_router.put("/{user_id}/password", response_model=UserResponse)
def reset_user_password(
    user_id: str,
    body: UserPasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    user.password_hash = hash_password(body.new_password)
    user.updated_at = _now()
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="users", record_id=user_id, action="PASSWORD_RESET")
    db.commit()
    db.refresh(user)
    return user
```

### Frontend: `5eyes-electron/frontend/5eyes_v2.html`

**Position für neuen HTML-Block:**
Im Admin-Modal `<div id="m-admin">`, im `<div class="mfooter">`, **direkt vor** dem Block mit `id="nu-"` Inputs (Zeile ~7830). Neuen Abschnitt einfügen:

```html
<div style="border-top:1px solid var(--b1);margin-top:12px;padding-top:12px">
  <div style="font-size:10px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--n5);margin-bottom:8px">Benutzerverwaltung</div>
  <div id="ul-list" style="font-size:11px;color:var(--n4)">Wird geladen…</div>
</div>
```

**Neue JS-Funktionen (im letzten `<script>`-Block oder in einem neuen vor `</body>`):**

```javascript
// ─── ADMIN USER MANAGEMENT ─────────────────────────────────────
async function loadAdminUserList() {
  var container = document.getElementById('ul-list');
  if (!container) return;
  container.textContent = 'Wird geladen…';
  var currentUserId = (currentUser && currentUser.id) || null;
  try {
    var users = await API.get('/users');
    if (!users || !users.length) { container.textContent = 'Keine Benutzer gefunden.'; return; }
    container.innerHTML = '';
    users.forEach(function(u) {
      var isSelf = String(u.id) === String(currentUserId);
      var row = document.createElement('div');
      row.dataset.userId = u.id;
      row.style.cssText = 'border:1px solid var(--b1);border-radius:6px;padding:8px 10px;margin-bottom:6px;background:var(--bg2)';
      var activeLabel = u.is_active ? '<span style="color:var(--pos)">aktiv</span>' : '<span style="color:var(--neg)">inaktiv</span>';
      row.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px">'
        + '<span style="font-size:11px">' + escapeHtml(u.full_name) + ' · <em style="color:var(--n4)">' + escapeHtml(u.role) + '</em> · ' + activeLabel + '</span>'
        + '<button class="btn-p" style="font-size:10px;padding:3px 8px" onclick="toggleAdminUserEdit(\'' + escapeHtml(u.id) + '\')">Bearbeiten</button>'
        + '</div>'
        + '<div id="ul-edit-' + escapeHtml(u.id) + '" style="display:none;margin-top:8px">'
        + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px">'
        + '<div><label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">Name</label><input class="fi" id="ul-name-' + escapeHtml(u.id) + '" value="' + escapeHtml(u.full_name) + '" style="font-size:11px"></div>'
        + '<div><label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">E-Mail</label><input class="fi" id="ul-email-' + escapeHtml(u.id) + '" value="' + escapeHtml(u.email || '') + '" style="font-size:11px"></div>'
        + '<div><label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">Rolle</label><select class="fsel" id="ul-role-' + escapeHtml(u.id) + '" style="font-size:11px"' + (isSelf ? ' disabled title="Eigene Rolle kann nicht geändert werden"' : '') + '>'
        + '<option value="advisor"' + (u.role==='advisor'?' selected':'') + '>Berater</option>'
        + '<option value="readonly"' + (u.role==='readonly'?' selected':'') + '>Lesend</option>'
        + '<option value="admin"' + (u.role==='admin'?' selected':'') + '>Admin</option>'
        + '</select></div>'
        + '<div style="display:flex;align-items:flex-end;gap:6px"><label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">Aktiv</label>'
        + '<input type="checkbox" id="ul-active-' + escapeHtml(u.id) + '"' + (u.is_active ? ' checked' : '') + (isSelf ? ' disabled title="Eigenes Konto kann nicht deaktiviert werden"' : '') + ' style="margin-bottom:4px"></div>'
        + '</div>'
        + '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">'
        + '<button class="btn-p" style="font-size:10px;padding:3px 10px" onclick="saveAdminUser(\'' + escapeHtml(u.id) + '\')">Speichern</button>'
        + '<button class="btn" style="font-size:10px;padding:3px 10px" onclick="toggleAdminPasswordReset(\'' + escapeHtml(u.id) + '\')">Passwort zurücksetzen</button>'
        + '</div>'
        + '<div id="ul-pw-' + escapeHtml(u.id) + '" style="display:none;margin-top:6px;display:flex;gap:6px;align-items:center">'
        + '<input class="fi" id="ul-newpw-' + escapeHtml(u.id) + '" type="password" placeholder="Neues Passwort (min. 10)" style="font-size:11px;flex:1">'
        + '<button class="btn-p" style="font-size:10px;padding:3px 10px" onclick="doAdminPasswordReset(\'' + escapeHtml(u.id) + '\')">Setzen</button>'
        + '</div>'
        + '<div id="ul-error-' + escapeHtml(u.id) + '" style="color:var(--neg);font-size:10px;margin-top:4px;display:none"></div>'
        + '</div>';
      container.appendChild(row);
    });
  } catch(e) {
    container.textContent = 'Fehler beim Laden: ' + String(e.detail || e.message || e);
  }
}

function toggleAdminUserEdit(userId) {
  var panel = document.getElementById('ul-edit-' + userId);
  if (!panel) return;
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

function toggleAdminPasswordReset(userId) {
  var panel = document.getElementById('ul-pw-' + userId);
  if (!panel) return;
  panel.style.display = panel.style.display === 'none' ? 'flex' : 'none';
}

async function saveAdminUser(userId) {
  var nameEl  = document.getElementById('ul-name-' + userId);
  var emailEl = document.getElementById('ul-email-' + userId);
  var roleEl  = document.getElementById('ul-role-' + userId);
  var activeEl = document.getElementById('ul-active-' + userId);
  var errEl   = document.getElementById('ul-error-' + userId);
  if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
  var body = {};
  if (nameEl)   body.full_name  = nameEl.value.trim() || undefined;
  if (emailEl)  body.email      = emailEl.value.trim() || null;
  if (roleEl && !roleEl.disabled)   body.role = roleEl.value;
  if (activeEl && !activeEl.disabled) body.is_active = activeEl.checked;
  try {
    await API.put('/users/' + userId, body);
    await loadAdminUserList();
  } catch(e) {
    if (errEl) { errEl.textContent = String(e.detail || e.message || e); errEl.style.display = 'block'; }
  }
}

async function doAdminPasswordReset(userId) {
  var pwEl  = document.getElementById('ul-newpw-' + userId);
  var errEl = document.getElementById('ul-error-' + userId);
  if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
  var newPassword = pwEl ? pwEl.value : '';
  try {
    await API.put('/users/' + userId + '/password', { new_password: newPassword });
    if (pwEl) pwEl.value = '';
    var panel = document.getElementById('ul-pw-' + userId);
    if (panel) panel.style.display = 'none';
  } catch(e) {
    if (errEl) { errEl.textContent = String(e.detail || e.message || e); errEl.style.display = 'block'; }
  }
}
```

**`loadAdminUserList()` beim Öffnen des Admin-Modals aufrufen:**

`openAdminModal()` liegt auf Zeile ~4087. Dort `loadAdminUserList()` zu `Promise.allSettled([...])` hinzufügen:

```javascript
async function openAdminModal() {
  om('m-admin');
  try {
    await Promise.allSettled([
      adminRefreshMarketStatus(false),
      adminUpdateStatus(),
      loadAdminUserList(),          // NEU
    ]);
  } catch(e) {}
}
```

**WICHTIG:** Im Frontend existiert bereits `let currentUser = null;` (Zeile ~1949) — diese Variable wird nach Login auf `data.user` gesetzt. In `loadAdminUserList()` muss `currentUser` (nicht `API._currentUser`) für den Self-Guard verwendet werden:
```javascript
var currentUserId = (currentUser && currentUser.id) || null;
```

## Risiken

- `currentUser` (globale Variable, Zeile ~1949) muss korrekt gesetzt sein für den Self-Guard im Frontend. Das Backend-Guard ist die letzte Sicherheitslinie.
- `innerHTML` in der User-Liste: alle User-Strings konsequent durch `escapeHtml()` schützen (full_name, email, role, id).
- User-ID als DOM-Element-ID: IDs sind UUIDs (keine Sonderzeichen), safe für `getElementById`.

## Offene Fragen an Owner

- OWNER-DECISION 1: Darf Admin eigene Rolle ändern? (Empfehlung: Nein)
- OWNER-DECISION 2: Läuft deaktivierter User bis JWT-Ablauf weiter, oder sofortiger Logout? (Empfehlung: Läuft bis Ablauf)
