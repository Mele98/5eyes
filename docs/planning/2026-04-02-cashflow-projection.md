# Claude Spec — Cashflow-Projektion Panel

## Meta

- Titel: 5-Jahres-Netto-Cashflow-Projektion pro Mandat
- Datum: 2026-04-02
- Owner: Emanuele
- Branch-Vorschlag: `codex/cashflow-projection`

## Ziel

Der Berater sieht im Cashflow-Bereich eine 5-Jahres-Projektion der Netto-Cashflows.
`cashflow_timeline.py` existiert bereits vollständig — nur Endpoint und UI fehlen.

## Ist-Zustand

- `cashflow_timeline.py`: `totals_for_year()` und `net_cashflow_series()` vorhanden ✓
- `GET /clients/{id}/cashflow-summary`: liefert nur laufendes Jahr
- `refreshCashflowsUI(cid)`: lädt cashflows + summary, rendert Zuflüsse/Abflüsse-Liste
- `Cashflow` Modell: in `models/wealth.py` (NICHT models/clients.py)
- `_get_client_or_404()` ist die Zugriffsguard in `routers/clients.py`
- `totals_for_year` ist bereits in `routers/clients.py` importiert (Zeile 17)

## Scope

### Backend
- Neuer Endpoint `GET /clients/{id}/cashflow-projection` direkt nach `cashflow_summary()`
- Neue Schemas `CashflowYearRow` + `CashflowProjectionResponse` in `schemas/clients.py`
- 3 Tests in neuer Datei `tests/test_cashflow_projection.py`
- Neuer Eintrag in `tests/test_runtime_contracts.py`

### Frontend
- Neue Funktion `renderCashflowProjection(data)` nach `refreshCashflowsUI`
- `refreshCashflowsUI()` um separaten (non-blocking) Projection-Call ergänzen
- HTML-Container `<div id="cf-projection">` als Geschwister-Element nach `#abfluss-rows`

---

## Backend

### Schema (`schemas/clients.py`, am Ende einfügen)

```python
class CashflowYearRow(BaseModel):
    year: int
    income_rappen: int
    expense_rappen: int
    net_rappen: int


class CashflowProjectionResponse(BaseModel):
    client_id: str
    start_year: int
    years: list[CashflowYearRow]
```

### Endpoint (`routers/clients.py`, direkt nach `cashflow_summary()`)

```python
@router.get("/{client_id}/cashflow-projection", response_model=CashflowProjectionResponse)
def cashflow_projection(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import date as _date
    _get_client_or_404(client_id, db, current_user)
    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()
    start_year = _date.today().year
    rows = []
    for offset in range(5):
        yr = start_year + offset
        t = totals_for_year(cashflows, yr)
        rows.append(CashflowYearRow(
            year=yr,
            income_rappen=t["income_rappen"],
            expense_rappen=t["expense_rappen"],
            net_rappen=t["net_rappen"],
        ))
    return CashflowProjectionResponse(
        client_id=client_id,
        start_year=start_year,
        years=rows,
    )
```

**Schema-Import erweitern** (Zeile 9-14 in clients.py):
```python
from schemas.clients import (
    ClientCreate, ClientUpdate, ClientResponse,
    NationalityCreate, NationalityResponse,
    OptHistoryCreate, OptHistoryResponse,
    WealthSummaryResponse, CashflowSummaryResponse,
    CashflowYearRow, CashflowProjectionResponse,  # neu
)
```

---

## Tests (`tests/test_cashflow_projection.py` — neue Datei)

```python
from __future__ import annotations
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.clients import Client
from models.wealth import Cashflow          # Cashflow ist in models.wealth, nicht models.clients
from models.users import User
from services.auth import get_current_user
import uuid, datetime


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_cf_proj.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-cfp-1", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at="2026-04-02T00:00:00.000Z",
        updated_at="2026-04-02T00:00:00.000Z",
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client(session_factory, advisor_id: str) -> str:
    cid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat() + "Z"
    with session_factory() as s:
        s.add(Client(
            id=cid, client_number="CF-001", first_name="Hans", last_name="Muster",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


def _add_cashflow(session_factory, client_id: str, amount_rappen: int,
                  cf_type: str = "Income", frequency: str = "Jährlich") -> None:
    now = datetime.datetime.utcnow().isoformat() + "Z"
    with session_factory() as s:
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client_id,
            cashflow_type=cf_type, label="Test CF",
            amount_rappen=amount_rappen, frequency=frequency,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()


def test_cashflow_projection_returns_5_years(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    _add_cashflow(session_factory, cid, 12_000_000)  # CHF 120k Income

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["years"]) == 5
    assert all(row["income_rappen"] == 12_000_000 for row in data["years"])


def test_cashflow_projection_net_calculation(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    _add_cashflow(session_factory, cid, 10_000_000, "Income")
    _add_cashflow(session_factory, cid, 4_000_000, "Expense")

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    rows = resp.json()["years"]
    assert rows[0]["net_rappen"] == 6_000_000


def test_cashflow_projection_empty_client_returns_zeros(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    rows = resp.json()["years"]
    assert all(r["net_rappen"] == 0 for r in rows)
```

**`test_runtime_contracts.py`** — Eintrag hinzufügen:
```python
assert ("/clients/{client_id}/cashflow-projection", ("GET",)) in route_map
```

---

## Frontend

### HTML — `#cf-projection` Container

**Position:** Nach dem schliessenden `</div>` von `id="abfluss-rows"`, noch INNERHALB
der übergeordneten `<div class="card mb">`. NICHT innerhalb von `#abfluss-rows`
(dessen innerHTML wird von `refreshCashflowsUI` überschrieben).

Suchstring (eindeutig):
```
              </div>
            </div>
            <div class="card">
              <div class="chd"><span class="cht">Ziele
```

Ersetzen durch:
```
              </div>
              <div id="cf-projection" style="padding:10px 12px;display:none"></div>
            </div>
            <div class="card">
              <div class="chd"><span class="cht">Ziele
```

### JS — `renderCashflowProjection(data)` (neue Funktion nach `refreshCashflowsUI`)

```javascript
function renderCashflowProjection(data) {
  var el = document.getElementById('cf-projection');
  if (!el) return;
  if (!data || !Array.isArray(data.years) || !data.years.length) {
    el.style.display = 'none';
    return;
  }
  var maxAbs = data.years.reduce(function(m, r) {
    return Math.max(m, Math.abs(r.net_rappen));
  }, 1);
  var fmt = function(r) {
    var chf = Math.round(Math.abs(r) / 100);
    var sign = r < 0 ? '\u2212' : '+';
    if (chf >= 1000000) return sign + 'CHF\u00a0' + (chf / 1000000).toFixed(1).replace('.0','') + '\u00a0Mio.';
    if (chf >= 1000)    return sign + 'CHF\u00a0' + Math.round(chf / 1000) + 'k';
    return sign + 'CHF\u00a0' + chf;
  };
  var html = '<div style="font-size:10px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;'
    + 'color:var(--n4);margin-bottom:8px">Netto-Cashflow Projektion (5 Jahre)</div>';
  data.years.forEach(function(row) {
    var pct = Math.round(Math.abs(row.net_rappen) / maxAbs * 100);
    var pos = row.net_rappen >= 0;
    var color = pos ? 'var(--pos)' : 'var(--neg)';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
      + '<span style="font-size:10px;color:var(--n4);width:32px;flex-shrink:0">'
      + escapeHtml(String(row.year)) + '</span>'
      + '<div style="flex:1;background:var(--b1);border-radius:2px;height:8px;overflow:hidden">'
      + '<div style="width:' + pct + '%;height:100%;background:' + color + ';border-radius:2px"></div>'
      + '</div>'
      + '<span style="font-size:10px;color:' + color + ';width:74px;text-align:right;flex-shrink:0">'
      + escapeHtml(fmt(row.net_rappen)) + '</span>'
      + '</div>';
  });
  el.innerHTML = html;
  el.style.display = '';
}
```

### JS — `refreshCashflowsUI(cid)` erweitern

Die Projektion wird als **separater, non-blocking Call** am Ende der Funktion ergänzt.
Das bestehende `Promise.all` mit 2 Calls NICHT anfassen.

**Vor (Ende der Funktion, letzten 2 Zeilen):**
```javascript
  }catch(e){console.warn('refreshCashflowsUI:',e);}
}
```

**Nach:**
```javascript
  }catch(e){console.warn('refreshCashflowsUI:',e);}
  try{
    var proj=await API.get('/clients/'+cid+'/cashflow-projection');
    renderCashflowProjection(proj);
  }catch(e2){renderCashflowProjection(null);}
}
```

---

## Akzeptanzkriterien

1. Endpoint liefert exakt 5 Einträge ab `date.today().year`
2. `net_rappen = income_rappen − expense_rappen` stimmt für jedes Jahr
3. Kein Cashflow → alle 0, kein 500-Fehler
4. Bestehende `refreshCashflowsUI` Funktionalität bleibt unverändert
5. Bei Projection-Fehler (z.B. 404): `renderCashflowProjection(null)` → Panel `display:none`
6. Panel sichtbar nach Laden eines Clients mit Cashflows

---

## Implementierungs-Checkliste für Codex

1. `grep -n "from schemas.clients import" 5eyes-backend/routers/clients.py`
   → Schema-Import-Zeile finden und CashflowYearRow, CashflowProjectionResponse ergänzen
2. `grep -n "totals_for_year" 5eyes-backend/routers/clients.py`
   → Bereits importiert (Zeile 17) — kein doppelter Import
3. `grep -n "^class Cashflow" 5eyes-backend/models/wealth.py`
   → Cashflow ist in models.wealth (NICHT models.clients) — Test-Import entsprechend
4. HTML-Container: nach `id="abfluss-rows"` schliessen, NICHT darin
5. `node --check 5eyes-electron/frontend/5eyes_v2.html` muss grün sein
6. `python -m pytest tests/test_cashflow_projection.py tests/test_runtime_contracts.py -q`
   muss grün sein
