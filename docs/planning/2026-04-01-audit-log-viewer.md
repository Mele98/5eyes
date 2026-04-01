# Claude Spec — Audit-Log-Viewer (Admin)

## Meta

- Titel: Audit-Log-Viewer — lesender Endpoint + Admin-UI-Tabelle
- Datum: 2026-04-01
- Owner: Emanuele
- Branch-Vorschlag: `codex/audit-log-viewer`

## Ziel

Der Admin kann im Admin-Modal die gespeicherten Audit-Log-Einträge einsehen: wer hat wann was geändert. Die `audit_log`-Tabelle wird bereits über `services.audit.log()` mit 41 Calls befüllt — es gibt aber keinen Endpoint und keine UI zum Lesen. Für eine Schweizer Vermögensverwaltungs-App (FINMA-Umfeld) ist ein lesbares Audit-Trail ein Compliance-Grundbaustein.

## Problem

- `GET`-Endpoint für `audit_log` fehlt vollständig
- Admin hat keine Möglichkeit, Mutationen nachzuverfolgen (wer hat welchen Client angelegt, wer hat ein Passwort zurückgesetzt etc.)
- `EXPORT`-Action existiert im CHECK-Constraint, wird aber nirgends ausgelöst — kein Scope-Problem, bleibt wie es ist

## Scope

- **Backend:** Neuer Endpoint `GET /admin/audit-log` (admin-only, paginiert, filterbar)
- **Backend:** Neues Pydantic-Schema `AuditLogEntry` (Response)
- **Backend:** Neues Pydantic-Schema `AuditLogPage` (Response-Wrapper mit `total`, `entries`)
- **Frontend:** Neuer Abschnitt "Audit-Log" im Admin-Modal (in `<div class="mbody">` des Admin-Modals, als eigener Tab-Bereich oder Abschnitt)
- **Frontend:** Filter: Action-Dropdown + Freitext-Suche (user_name oder table_name), Seiten-Navigation (Prev/Next)
- **Backend-Tests:** 5 neue Tests

## Nicht-Scope

- Schreiben/Löschen von Audit-Log-Einträgen (Audit-Log ist immutable)
- Export als CSV/PDF
- Mandate- oder Client-spezifisches Log (separates Feature)
- Suche nach `record_id` im UI (zu spezifisch für Phase 1)

## Fachlogik

- **Verbindliche Regeln:**
  - Nur `role=admin` kann `GET /admin/audit-log` aufrufen
  - Einträge werden absteigend nach `created_at` sortiert (neueste zuerst)
  - `limit` max. 200, default 50
  - `offset` default 0
  - Optionaler Filter: `action` (einer der gültigen Werte oder leer für alle)
  - Optionaler Filter: `q` (case-insensitive LIKE-Suche auf `user_name` OR `table_name`)
  - Response enthält `total` (Gesamtzahl gefiltert), `entries` (die aktuelle Seite)
- **Inferenz:** `AuditLog.user_id` kann NULL sein (Bootstrap-Admin hat kein `user_id`), UI muss damit umgehen
- **Owner-Decisions:**
  - OWNER-DECISION 1: Soll `record_id` im UI angezeigt werden? (Empfehlung: Ja, als kleine ID-Spalte — nützlich für Debugging)

## Betroffene Module / Dateien

- **Backend:**
  - `5eyes-backend/schemas/review.py` — neue Schemas `AuditLogEntry`, `AuditLogPage`
  - `5eyes-backend/routers/system.py` — neuer Endpoint `GET /admin/audit-log`
  - `5eyes-backend/tests/test_audit_log_viewer.py` — neue Testdatei (neu anlegen)
  - `5eyes-backend/tests/test_runtime_contracts.py` — neuer Route-Eintrag
- **Frontend:**
  - `5eyes-electron/frontend/5eyes_v2.html` — Audit-Log-Abschnitt im Admin-Modal
- **Datenmodell:** Keine Änderung

## API / Schnittstellen

### Neuer Endpoint

```
GET /admin/audit-log
Requires: admin
Query params:
  limit    int     default=50, max=200
  offset   int     default=0
  action   str     optional — einer von: CREATE, UPDATE, DELETE, LOGIN, EXPORT, PASSWORD_RESET
  q        str     optional — LIKE-Suche auf user_name OR table_name (case-insensitive)

200: AuditLogPage
```

### Neue Schemas (in `schemas/review.py` anhängen)

```python
class AuditLogEntry(BaseModel):
    id: str
    user_id: Optional[str]
    user_name: str
    table_name: str
    record_id: str
    action: str
    field_name: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    mandate_id: Optional[str]
    client_id: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    total: int
    limit: int
    offset: int
    entries: list[AuditLogEntry]
```

### Implementierung `GET /admin/audit-log` (in `routers/system.py`)

```python
from schemas.review import AuditLogEntry, AuditLogPage
from models.review import AuditLog

AUDIT_LOG_VALID_ACTIONS = frozenset(
    {'CREATE', 'UPDATE', 'DELETE', 'LOGIN', 'EXPORT', 'PASSWORD_RESET'}
)

@router.get('/audit-log', response_model=AuditLogPage)
def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    if offset < 0:
        offset = 0

    query = db.query(AuditLog)

    if action and action.upper() in AUDIT_LOG_VALID_ACTIONS:
        query = query.filter(AuditLog.action == action.upper())

    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                AuditLog.user_name.ilike(pattern),
                AuditLog.table_name.ilike(pattern),
            )
        )

    total = query.count()
    entries = (
        query
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return AuditLogPage(
        total=total,
        limit=limit,
        offset=offset,
        entries=entries,
    )
```

Imports die in `routers/system.py` neu gebraucht werden:
```python
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi import Depends
from database import get_db
from models.review import AuditLog
from schemas.review import AuditLogEntry, AuditLogPage
from services.auth import require_admin
```

Prüfen ob diese bereits importiert sind — nur fehlende ergänzen. `or_` aus `sqlalchemy` ist neu.

## UI / UX

### Position im Admin-Modal

Im Admin-Modal (`<div id="m-admin">`) im `<div class="mbody">` — **neuer Abschnitt** ganz oben, vor dem Marktdaten-Block. Eigener `<div>` mit Header "Audit-Log" und einem Button "Laden".

```
┌──────────────────────────────────────────────────────────┐
│ AUDIT-LOG                                                 │
│  Action: [Alle ▼]  Suche: [__________]  [Laden]         │
│  ┌──────────────────────────────────────────────────────┐│
│  │ Zeitpunkt       | Benutzer  | Tabelle  | Aktion | ID ││
│  │ 2026-04-01 14:… | Admin     | users    | CREATE | …  ││
│  │ 2026-04-01 13:… | Admin     | clients  | UPDATE | …  ││
│  └──────────────────────────────────────────────────────┘│
│  Einträge 1–50 von 312   [← Zurück] [Weiter →]          │
└──────────────────────────────────────────────────────────┘
```

### Details

- Tabelle mit Spalten: `created_at` (formatiert via `formatIsoLocal()` falls vorhanden, sonst raw), `user_name`, `table_name`, `action`, `record_id` (gekürzt auf 8 Zeichen + `…`), optional `field_name`/`new_value` wenn belegt
- Pagination: Prev/Next-Buttons, angezeigt als "Einträge {offset+1}–{offset+limit} von {total}"
- "Laden"-Button triggert `loadAdminAuditLog(0)` mit aktuellen Filter-Werten
- Filter-Änderung setzt `offset` zurück auf 0
- Laden-Indikator: Button text "Lädt…" während Request
- Fehler: in einem `<div id="al-error">` anzeigen
- Keine Auto-Load beim Öffnen des Modals (expliziter "Laden"-Button) — Log kann gross sein

### XSS

- Alle Server-Strings via `escapeHtml()` schützen (user_name, table_name, record_id, action, field_name, new_value)
- Keine `innerHTML` mit unescapten Daten

## Akzeptanzkriterien

1. `GET /admin/audit-log` ohne Filter liefert neueste 50 Einträge, `total` korrekt
2. Filter `action=LOGIN` liefert nur LOGIN-Einträge
3. Filter `q=admin` liefert Einträge mit "admin" in user_name oder table_name
4. `limit=201` wird auf 200 gecappt
5. Nicht-Admin → 403
6. Admin-Modal zeigt Audit-Log-Tabelle nach Klick auf "Laden"

## Testfälle

**Neue Datei: `5eyes-backend/tests/test_audit_log_viewer.py`**

Fixture-Pattern: analog `test_user_management.py` — `session_factory`, `admin_client`, `forbidden_client`.

Seed-Funktion: `seed_audit_entry(session_factory, **overrides)` — direkt `AuditLog`-Objekte in DB einfügen.

- `test_audit_log_returns_entries_sorted_desc` — 3 Einträge angelegt (verschiedene Timestamps), GET → erster Eintrag ist der neueste
- `test_audit_log_filter_by_action` — 2x LOGIN, 1x CREATE geseedet → `?action=LOGIN` → 2 Einträge, total=2
- `test_audit_log_filter_by_q` — user_name="Admin", user_name="Berater" → `?q=admin` → nur Admin-Eintrag (case-insensitive)
- `test_audit_log_limit_capped_at_200` — `?limit=999` → response.limit == 200
- `test_audit_log_requires_admin` — 403 für Nicht-Admin

**`test_runtime_contracts.py`:** Neuen Eintrag hinzufügen:
```python
assert ("/admin/audit-log", ("GET",)) in route_map
```

## Implementierungsdetails für Codex

### `schemas/review.py`

Am Ende der Datei einfügen (nach der letzten bestehenden Klasse), vor dem letzten `__all__` falls vorhanden:

```python
class AuditLogEntry(BaseModel):
    id: str
    user_id: Optional[str] = None
    user_name: str
    table_name: str
    record_id: str
    action: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    mandate_id: Optional[str] = None
    client_id: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    total: int
    limit: int
    offset: int
    entries: list[AuditLogEntry]
```

### `routers/system.py`

Vollständige Implementierung gemäss API-Abschnitt oben. Route-Prefix ist `/admin/system` — der neue Endpoint wird also unter `/admin/system/audit-log` erreichbar. Das ist korrekt so (kein neues Prefix nötig).

### `5eyes-electron/frontend/5eyes_v2.html`

**HTML-Block** im Admin-Modal `<div class="mbody">` (den es bereits hat, mit `id="m-admin"`), **als erster** neuer Abschnitt oben im `mbody`, VOR dem bestehenden Marktdaten-Block.

Position finden: In `<div id="m-admin">` das erste `<div class="mbody">` suchen und ganz oben einfügen:

```html
<div style="border-bottom:1px solid var(--b1);padding-bottom:12px;margin-bottom:12px">
  <div style="font-size:10px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--n5);margin-bottom:8px">Audit-Log</div>
  <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
    <select id="al-action-filter" class="fsel" style="font-size:11px;padding:3px 6px">
      <option value="">Alle Aktionen</option>
      <option value="CREATE">CREATE</option>
      <option value="UPDATE">UPDATE</option>
      <option value="DELETE">DELETE</option>
      <option value="LOGIN">LOGIN</option>
      <option value="PASSWORD_RESET">PASSWORD_RESET</option>
      <option value="EXPORT">EXPORT</option>
    </select>
    <input id="al-q-filter" class="fi" placeholder="Benutzer oder Tabelle" style="font-size:11px;width:160px">
    <button class="btn-p" id="btn-al-load" onclick="loadAdminAuditLog(0)" style="font-size:10px;padding:3px 10px">Laden</button>
  </div>
  <div id="al-error" style="color:var(--neg);font-size:10px;margin-bottom:6px;display:none"></div>
  <div id="al-table" style="font-size:10px;overflow-x:auto"></div>
  <div id="al-pagination" style="display:flex;gap:8px;align-items:center;margin-top:6px;font-size:10px;color:var(--n4)"></div>
</div>
```

**JS-Funktionen** (in letztem `<script>`-Block, nach den Benutzerverwaltungs-Funktionen):

```javascript
// ─── ADMIN AUDIT LOG ────────────────────────────────────────────
var _auditLogOffset = 0;
var _auditLogTotal = 0;
var _auditLogLimit = 50;

async function loadAdminAuditLog(offset) {
  var btn = document.getElementById('btn-al-load');
  var tableEl = document.getElementById('al-table');
  var paginationEl = document.getElementById('al-pagination');
  var errEl = document.getElementById('al-error');
  if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
  if (btn) { btn.disabled = true; btn.textContent = 'Lädt…'; }
  if (tableEl) tableEl.textContent = '';
  if (paginationEl) paginationEl.textContent = '';

  var action = (document.getElementById('al-action-filter') || {}).value || '';
  var q = ((document.getElementById('al-q-filter') || {}).value || '').trim();

  var params = 'limit=' + _auditLogLimit + '&offset=' + (offset || 0);
  if (action) params += '&action=' + encodeURIComponent(action);
  if (q) params += '&q=' + encodeURIComponent(q);

  try {
    var data = await API.get('/admin/system/audit-log?' + params);
    _auditLogOffset = data.offset || 0;
    _auditLogTotal = data.total || 0;
    _auditLogLimit = data.limit || 50;
    renderAuditLogTable(data.entries || [], tableEl);
    renderAuditLogPagination(paginationEl);
  } catch(e) {
    if (errEl) { errEl.textContent = parseApiError(e, 'Audit-Log konnte nicht geladen werden.'); errEl.style.display = 'block'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Laden'; }
  }
}

function renderAuditLogTable(entries, container) {
  if (!container) return;
  if (!entries.length) { container.textContent = 'Keine Einträge.'; return; }
  var html = '<table style="width:100%;border-collapse:collapse;font-size:10px">'
    + '<thead><tr style="border-bottom:1px solid var(--b2);color:var(--n4)">'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Zeitpunkt</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Benutzer</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Tabelle</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Aktion</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">ID</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Feld / Wert</th>'
    + '</tr></thead><tbody>';
  entries.forEach(function(e) {
    var ts = e.created_at ? (typeof formatIsoLocal === 'function' ? formatIsoLocal(e.created_at) : e.created_at.slice(0, 16).replace('T', ' ')) : '—';
    var shortId = escapeHtml(String(e.record_id || '').slice(0, 8)) + (String(e.record_id || '').length > 8 ? '…' : '');
    var fieldVal = e.field_name ? escapeHtml(String(e.field_name)) + (e.new_value ? ' → ' + escapeHtml(String(e.new_value).slice(0, 30)) : '') : '';
    var actionColor = {CREATE:'var(--pos)',UPDATE:'var(--warn)',DELETE:'var(--neg)',LOGIN:'var(--g4)',PASSWORD_RESET:'var(--warn)',EXPORT:'var(--n6)'}[e.action] || 'var(--n6)';
    html += '<tr style="border-bottom:1px solid var(--b1)">'
      + '<td style="padding:3px 6px;color:var(--n5)">' + escapeHtml(ts) + '</td>'
      + '<td style="padding:3px 6px">' + escapeHtml(e.user_name || '—') + '</td>'
      + '<td style="padding:3px 6px;color:var(--n4)">' + escapeHtml(e.table_name || '—') + '</td>'
      + '<td style="padding:3px 6px;font-weight:500;color:' + actionColor + '">' + escapeHtml(e.action || '—') + '</td>'
      + '<td style="padding:3px 6px;color:var(--n4);font-family:monospace">' + shortId + '</td>'
      + '<td style="padding:3px 6px;color:var(--n4)">' + fieldVal + '</td>'
      + '</tr>';
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

function renderAuditLogPagination(container) {
  if (!container) return;
  var from = _auditLogOffset + 1;
  var to = Math.min(_auditLogOffset + _auditLogLimit, _auditLogTotal);
  var label = _auditLogTotal > 0 ? ('Einträge ' + from + '–' + to + ' von ' + _auditLogTotal) : 'Keine Einträge';
  var prevDisabled = _auditLogOffset <= 0;
  var nextDisabled = (_auditLogOffset + _auditLogLimit) >= _auditLogTotal;
  container.innerHTML = '<button class="btn" style="font-size:10px;padding:2px 8px"' + (prevDisabled ? ' disabled' : '') + ' onclick="loadAdminAuditLog(' + Math.max(0, _auditLogOffset - _auditLogLimit) + ')">&larr; Zurück</button>'
    + '<span style="padding:0 6px">' + escapeHtml(label) + '</span>'
    + '<button class="btn" style="font-size:10px;padding:2px 8px"' + (nextDisabled ? ' disabled' : '') + ' onclick="loadAdminAuditLog(' + (_auditLogOffset + _auditLogLimit) + ')">Weiter &rarr;</button>';
}
```

**`formatIsoLocal`-Check:** Diese Funktion existiert bereits im Frontend (wird für Preishistorie verwendet). Im `renderAuditLogTable` via `typeof formatIsoLocal === 'function'` defensiv aufrufen — kein Import nötig.

## Risiken

- `AuditLog`-Tabelle kann bei produktiver Nutzung sehr gross werden — `limit=200` ist hard cap, kein Problem
- `or_()` Volltextsuche mit LIKE ist performant genug für SQLite mit <100k Zeilen
- `action`-Filter: ungültiger Wert wird ignoriert (kein 422) — sicher, nur bekannte Actions im Dropdown

## Offene Fragen an Owner

- OWNER-DECISION 1: record_id anzeigen (8 Zeichen)? (Empfehlung: Ja, nützlich für Support)
