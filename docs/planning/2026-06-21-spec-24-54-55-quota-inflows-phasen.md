# Claude Spec — #24 Quota-Enforcement · #54 Wealth-Inflows-UI · #55 Mehrjahres-Cashflow-Phasen-Editor

## Meta

- Titel: Lizenz-/Quota-Enforcement (Soft/Hard + Hint-UI), Wealth-Inflows-FE (first-class + Chart-Marker), Phasen-Editor für Mehrjahres-Cashflows
- Datum: 2026-06-21
- Owner: Emanuele
- Branch-Vorschlag: `codex/u24-quota-inflows`
- Geltungsbereich: 3 unabhängige, in EINEM Branch lieferbare Arbeitspakete. Reihenfolge egal; #54 und #55 berühren teils dieselben FE-Stellen (Cashflow-Tab) — bei parallelem Arbeiten Merge-Reihenfolge #55 vor #54 empfohlen.

> WICHTIG (verifiziert per Read, file:line): Große Teile der drei Tickets sind **bereits implementiert**. Diese Spec beschreibt nur die **echten Lücken**. Keine bestehenden, funktionierenden Pfade umbauen.

---

# Teil A — #24 [OPS] Lizenz-/Quota-Enforcement

## A.1 Ziel

Tenant-Quotas (`max_users`, `max_mandates`) durchsetzen und für den Berater/Admin sichtbar machen:
- **Hard-Limit** (Erstellen blockieren, 409) — IST bereits vorhanden.
- **Soft-Limit** (Warnung ab Schwelle, NICHT blockieren) — FEHLT.
- **Hint-UI** (Berater/Admin sieht Auslastung X/Y + Warnung) — FEHLT (Backend-Status-Endpoint + FE-Banner).

## A.2 IST-Zustand (verifiziert)

Datenmodell — Quotas sind **Einzel-Spalten** auf `tenants` (es gibt KEIN `quotas`-JSON-Feld):
- `models/tenant.py:80` `max_users = Column(Integer, default=1)`
- `models/tenant.py:82` `max_mandates = Column(Integer)` (NULL = unbegrenzt)
- `models/tenant.py:84` `storage_quota_mb = Column(Integer)` (NULL = unbegrenzt; NICHT Teil dieses Tickets)
- `models/users.py:14` `tenant_id` (FK, nullable, BC)
- `models/mandates.py:12` `tenant_id` (FK, nullable, BC)

Hard-Limit-Enforcement **existiert vollständig**:
- `services/quota.py:20-71` `assert_within_quota(db, tenant_id, kind)` — zählt aktive User/Mandate pro `tenant_id` und wirft **HTTP 409** bei `current >= limit`. `_quota_limit` (Zeile 57-62) behandelt `NULL` UND `0` als „unbegrenzt“.
- Aufrufstellen:
  - `routers/auth.py:386` `create_user` → `assert_within_quota(db, tenant_id, "users")`
  - `routers/auth.py:453` `invite_user` → `assert_within_quota(db, tenant_id, "users")`
  - `routers/mandates.py:55` `create_mandate` → `assert_within_quota(db, mandate_tenant_id, "mandates")` (tenant_id vererbt vom Client, Fallback User — Zeile 54)
- Tests vorhanden: `tests/test_tenant_quota_enforcement.py` (Hard-Limit users+mandates, per-tenant-Zählung, 0=unbegrenzt, NULL=unbegrenzt).

Tenant-Auflösung im Request (verifiziert):
- `services/auth.py:309-315` `user_tenant_id(user)` (Public) bzw. `services/auth.py:48-61` `_resolve_tenant_id_for_user(user)` → liefert `user.tenant_id` oder `'main'` (BC-Fallback).
- `services/auth.py:268-306` `get_current_tenant_id` (aus JWT-Claim `tid`).

FE-Fehler-Handling (verifiziert via 5eyes_v2.html):
- `showAppError(message, {title})` (~Zeile 15132) / `showAppWarn` (~15133) / `showAppNotice` (~15077) → Toast-Stack `#app-notice-stack`.
- 409 wird heute punktuell behandelt (z.B. Bootstrap ~Zeile 4990 username-Konflikt). `API.post/get` (~4720-4723) gibt `e.detail` durch.

**FAZIT #24:** Es fehlen nur (1) Soft-Limit-Schwellen-Logik, (2) ein read-only Quota-Status-Endpoint, (3) das FE-Auslastungs-/Warn-Banner. Hard-Limit NICHT anfassen.

## A.3 SOLL-Design

### A.3.1 Soft-Limit (Backend, neue Funktion in `services/quota.py`)

`assert_within_quota` bleibt unverändert (Hard-Gate). Zusätzlich eine **nicht-werfende** Status-Funktion:

```python
# services/quota.py — am Ende anfügen
from dataclasses import dataclass

# OWNER-DECISION (Default; siehe A.6): Soft-Warn ab 80% Auslastung.
SOFT_LIMIT_THRESHOLD_PCT = 80

@dataclass(frozen=True)
class QuotaStatus:
    kind: str            # "users" | "mandates"
    current: int
    limit: int | None    # None = unbegrenzt
    soft_threshold_pct: int
    at_hard_limit: bool   # current >= limit
    at_soft_limit: bool   # limit gesetzt UND current/limit >= threshold (aber < hard)

def quota_status(db: Session, tenant_id: str | None, kind: QuotaKind) -> QuotaStatus:
    """Read-only Auslastungs-Status. Wirft NIE. Spiegelt die Zähllogik von
    assert_within_quota (gleiche Filter: tenant_id == tid, deleted_at IS NULL)."""
    tid = str(tenant_id or "").strip()
    limit = None
    current = 0
    if tid:
        tenant = db.query(Tenant).filter(Tenant.id == tid, Tenant.deleted_at.is_(None)).first()
        if tenant is not None:
            if kind == "users":
                limit = _quota_limit(getattr(tenant, "max_users", None))
                current = db.query(User).filter(User.tenant_id == tid, User.deleted_at.is_(None)).count()
            elif kind == "mandates":
                limit = _quota_limit(getattr(tenant, "max_mandates", None))
                current = db.query(Mandate).filter(Mandate.tenant_id == tid, Mandate.deleted_at.is_(None)).count()
    at_hard = limit is not None and current >= limit
    at_soft = (limit is not None) and (not at_hard) and (current * 100 >= limit * SOFT_LIMIT_THRESHOLD_PCT)
    return QuotaStatus(kind=kind, current=current, limit=limit,
                       soft_threshold_pct=SOFT_LIMIT_THRESHOLD_PCT,
                       at_hard_limit=at_hard, at_soft_limit=at_soft)
```

Hinweis: `quota_status` nutzt **dieselben** Count-Filter wie `assert_within_quota` (Single-Source der Zähllogik). Wenn das stört → optionaler Refactor: gemeinsamen `_count(db, tid, kind)`-Helper extrahieren. NICHT zwingend.

### A.3.2 Status-Endpoint (Backend)

Neuer read-only Endpoint im bestehenden `routers/tenants.py` ODER — besser, weil für jeden Admin/Advisor erreichbar (nicht nur super_admin) — als **eigener Mini-Router** `routers/quota.py`:

```python
# routers/quota.py (NEU — nur falls Owner einen FE-sichtbaren Status will)
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.users import User
from services.auth import get_current_user, user_tenant_id
from services.quota import quota_status

router = APIRouter(prefix="/quota", tags=["Quota"])

@router.get("/status")
def get_quota_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tid = user_tenant_id(current_user)
    us = quota_status(db, tid, "users")
    ms = quota_status(db, tid, "mandates")
    def _dto(s):
        return {"kind": s.kind, "current": s.current, "limit": s.limit,
                "soft_threshold_pct": s.soft_threshold_pct,
                "at_soft_limit": s.at_soft_limit, "at_hard_limit": s.at_hard_limit}
    return {"tenant_id": tid, "users": _dto(us), "mandates": _dto(ms)}
```

Router registrieren in `main.py` (dort wo die anderen Router via `app.include_router(...)` eingehängt werden — Stelle per Read suchen, NICHT raten).

> Mandanten-Trennung: Endpoint liefert NUR den Tenant des eingeloggten Users (`user_tenant_id`). Kein Cross-Tenant-Leak. `super_admin` (tenant_id evtl. None/`main`) sieht nur seinen eigenen → akzeptabel; Tenant-übergreifende Sicht läuft über die bestehende `/tenants`-Admin-API (super_admin), die `max_*` ohnehin zurückgibt.

### A.3.3 Soft-Limit-Hinweis bei Create (optional, empfohlen)

Hard-Limit bleibt 409. Soft-Limit darf NICHT blockieren. Statt eines Response-Headers (kompliziert bei `response_model`) ist der **Status-Endpoint** der saubere Weg: FE pollt `/quota/status` nach jedem erfolgreichen Create und zeigt das Banner. Damit bleibt `create_user`/`create_mandate` unangetastet (kein Risiko).

### A.3.4 FE — Hint-UI (5eyes_v2.html)

- Beim Laden der Admin/Benutzer-Sektion und der Mandats-Liste: `API.get('/quota/status')`.
- Rendern:
  - `at_hard_limit` → `showAppError('User-/Mandats-Limit erreicht (X/Y). Bitte Lizenz erweitern.', {title:'Lizenz-Limit erreicht'})` + „+ Neuer User/Mandat“-Button `disabled`.
  - `at_soft_limit` → `showAppWarn('Auslastung X/Y (≥80%). Bald Lizenz-Limit erreicht.')` (nicht blockierend).
  - sonst: dezenter Text „X / Y“ (oder „X / unbegrenzt“ wenn `limit===null`).
- Bei 409 aus Create-Call (`e.status===409`, `e.detail` enthält `max_users`/`max_mandates`): bestehenden Toast-Pfad nutzen + Status neu laden.

## A.4 Test-Plan #24

Neue Datei `tests/test_quota_status.py` (analog zu `test_tenant_quota_enforcement.py`, gleiche Fixtures):
1. `limit=None` → `at_soft=False, at_hard=False, limit=None`.
2. `max_users=10`, 7 User → `at_soft=False` (70% < 80%).
3. `max_users=10`, 8 User → `at_soft=True, at_hard=False`.
4. `max_users=10`, 10 User → `at_hard=True, at_soft=False`.
5. `max_users=0` → unbegrenzt (`limit=None`).
6. Per-Tenant-Isolation: Tenant A 8/10, Tenant B 1/10 → A `at_soft`, B nicht.
7. Endpoint-Test (`TestClient`): `/quota/status` liefert beide Kinds, nur eigener Tenant.
- Eintrag in `tests/test_runtime_contracts.py` ergänzen (neuer Endpoint im Contract).

## A.5 Edge-Cases #24

- **Quota-Race** (zwei parallele Creates am Hard-Limit): Hard-Gate ist „check-then-insert“ ohne Lock → theoretisch kann Limit um 1 überschritten werden. IST-Verhalten unverändert lassen (kein Scope-Creep). Wenn Owner hartes No-Overshoot will: `SELECT ... FOR UPDATE` auf die Tenant-Zeile in `assert_within_quota` ODER UNIQUE-Constraint-basiertes Insert-and-Catch. → siehe OWNER-DECISION.
- **Soft-Schwelle bei kleinen Limits**: `max_users=1` → 0/1 = 0% (kein Soft), erstes Create geht, danach hard. Bei `limit=2`: 1/2 = 50% (kein Soft), 2/2 hard. Soft greift erst sinnvoll ab `limit>=5`. Akzeptiert; Banner zeigt trotzdem korrekte X/Y.
- **NULL vs 0**: beide = unbegrenzt (bestehende Semantik in `_quota_limit`, NICHT ändern).
- **Legacy-User ohne tenant_id**: `user_tenant_id` → `'main'`. Wenn kein Tenant `main` existiert, gibt `quota_status` `limit=None` (unbegrenzt) zurück — korrekt für Tier-1.
- **deleted_at**: Zählung ignoriert Soft-Deleted (Filter vorhanden) — konsistent mit Hard-Gate.

---

# Teil B — #54 [BE/FE] Wealth-Inflows-UI vervollständigen

## B.1 Ziel

Erbschaft/Bonus/Säule-3b/Verkaufserlös als **first-class FE-Eingabe** (Modell + CRUD + Engine-Konsum existieren) und als **Marker im Chart**.

## B.2 IST-Zustand (verifiziert)

Modell & Schema **vorhanden**:
- `models/wealth.py:91-118` `class WealthInflow` — Felder: `source_type` (`Erbschaft|Bonus|Saeule3b|Verkaufserloes|Andere`), `amount_rappen`, `expected_year`, `is_recurring`, `frequency` (`einmalig|jaehrlich|monatlich`), `duration_years`, `value_mode` (`nominal|real`), `mandate_id` (optional), `notes`, `is_active`.
- `schemas/wealth.py:259-314` `WEALTH_INFLOW_SOURCE_TYPES` + `WealthInflowCreate/Update/Response` (mit Validator `_validate_recurring` Zeile 276-283).

CRUD-Endpoints **vollständig** in `routers/wealth.py`:
- `GET /clients/{client_id}/wealth-inflows` (Zeile 951-961, sortiert nach `expected_year`)
- `POST /clients/{client_id}/wealth-inflows` (964-990, `require_advisor`, Ownership via Client + optional Mandate)
- `PUT /wealth-inflows/{inflow_id}` (993-1017)
- `DELETE /wealth-inflows/{inflow_id}` (1020-1038, soft-delete)

Engine-Konsum **vorhanden** (KORREKTUR ggü. Ticket-Annahme):
- `services/portfolio_engine.py:4278-4333` `_wealth_inflow_series_rappen(...)` — wandelt Inflows in Year-Series:
  - `is_recurring=0` → Einmalbeitrag im `expected_year` (Zeile 4330)
  - `is_recurring=1, frequency='jaehrlich'` → jährlich über `duration_years` (4324-4328)
  - `is_recurring=1, frequency='monatlich'` → `amount*12` p.a. (4325)
  - `value_mode='real'` → inflations-aufgezinst per Offset (4315-4322)
- Integriert in die Strategie-Projektion: `portfolio_engine.py:4420-4427` (addiert zu `cashflow_projection_series_rappen`) und im Rebuild-Pfad ~6904-6918.
- PDF konsumiert Inflows ebenfalls: `routers/pdf_reports.py:564-568`.

**LÜCKE (verifiziert):** 
1. **FE hat KEINE Wealth-Inflow-UI** (Agent-Suche in 5eyes_v2.html: `wealth-inflow`/`Zufluss`-Formular nicht vorhanden; „Erbschaft“ nur als Goal-Option ~Zeile 9003).
2. Der **live** Endpoint `GET /clients/{id}/cashflow-projection` (`routers/clients.py:397-455`) bezieht Inflows **NICHT** ein (nur Cashflows + abgeleitete + Hypothek-Adj.). Inflows fließen NUR in die Strategie-Engine-Projektion + PDF. Der Liquiditäts-/Verzehr-Chart (`#ch-ist`), der u.a. `cashflow-projection` nutzt, zeigt Inflows daher heute nicht.

## B.3 SOLL-Design

### B.3.1 FE — Inflow-Formular (5eyes_v2.html)

Neues Modal analog `m-acf` (Cashflow-Modal, HTML ~4131-4235; Speicher-JS `saveCashflow()` ~20897-20982). Modal-ID `m-awi` („add wealth inflow“):
- Felder:
  - `#awi-source` Select: Erbschaft / Bonus / Säule 3b / Verkaufserlös / Andere (Werte = `WEALTH_INFLOW_SOURCE_TYPES`: `Erbschaft|Bonus|Saeule3b|Verkaufserloes|Andere`).
  - `#awi-label` Text (Pflicht, 1-200).
  - `#awi-amount` Betrag CHF → `amount_rappen` (×100; `gt=0`).
  - `#awi-year` `expected_year` (Number, 1900-2200; Default aktuelles Jahr).
  - `#awi-recurring` Checkbox → `is_recurring`.
  - `#awi-frequency` Select (nur bei recurring sichtbar): jährlich/monatlich (`jaehrlich|monatlich`).
  - `#awi-duration` `duration_years` (nur bei recurring; 1-99).
  - `#awi-valuemode` Select nominal/real (Default `nominal`).
  - `#awi-notes` Text optional.
- Validierung clientseitig spiegeln (recurring ⇒ frequency≠einmalig + duration gesetzt), sonst zeigt Backend `WealthInflowCreate._validate_recurring` (schemas/wealth.py:276-283) ein 422.
- Speicher-JS `saveWealthInflow()`:
  - Create: `API.post('/clients/'+cid+'/wealth-inflows', payload)`
  - Edit: `API.put('/wealth-inflows/'+id, payload)`
  - Delete: `API.del('/wealth-inflows/'+id)`
- Liste rendern in der **Cashflow- oder Vermögens-Sektion** (Owner-Entscheid B.6): neuer Container `#inflow-rows` als Geschwister zu `#zufluss-rows`/`#abfluss-rows` (~2917-2927). Lade-Funktion `refreshInflowsUI(cid)` analog `refreshCashflowsUI` (~21058), aufgerufen aus demselben Tab-Refresh (`go('cf', …)` ~5357-5396).
- Öffnen-Buttons: „+ Vermögenszufluss“ neben den bestehenden Cashflow-Buttons; `om('m-awi')` / `cm('m-awi')` (~5651/5656).

### B.3.2 FE — Chart-Marker (grün) auf `#ch-ist`

- Datenquelle: `API.get('/clients/'+cid+'/wealth-inflows')` (bereits vorhanden) → pro Inflow ein Punkt im Jahr `expected_year` (bei recurring: Start-Jahr markieren; optional Spanne `expected_year … expected_year+duration-1`).
- Marker als zusätzliches Chart.js-Dataset bzw. Punkt-Overlay, analog zu den bestehenden Goal-/Depletion-Markern (`refreshIstGoalMarkers()` ~21208, `applyDepletionMarkerToDataset()` ~21206). Grün gemäß bestehender Palette (z.B. `borderColor:'rgba(22,101,52,0.9)'`, vgl. „verbesserte Situation“-Linie ~17773).
- Marker-Render in denselben Chart-Refresh-Pfaden einhängen, in denen Goal-Marker gesetzt werden: `updateProjectionChartsFromSimulation` (~17683/17792), `refreshBaselineChartFromClientDataForced` (~21221/21246).
- Tooltip: „Erbschaft 2031: CHF 250'000 (real)“.

### B.3.3 Backend — Inflows in die LIVE cashflow-projection (empfohlen, Owner-Entscheid B.6)

Damit der IST-Chart (ohne Strategie-Lauf) die Inflows ebenfalls zeigt, in `routers/clients.py:397-455` (`cashflow_projection`) die Inflows als `capital_inflow_rappen` pro Jahr addieren — **wiederverwenden** der Engine-Funktion statt Neu-Implementierung:

```python
# in cashflow_projection(), nach dem Laden von cashflows:
from models.wealth import WealthInflow
from services.portfolio_engine import _wealth_inflow_series_rappen
inflows = db.query(WealthInflow).filter(
    WealthInflow.client_id == client_id,
    WealthInflow.deleted_at.is_(None),
    WealthInflow.is_active == 1,
).all()
infl_series = _wealth_inflow_series_rappen(inflows, horizon, start_year, None)  # None = nominal-Pfad ohne Inflation
# ... in der Jahres-Schleife (offset):
infl = int(infl_series[offset]) if offset < len(infl_series) else 0
# auf capital_inflow_rappen + income_rappen + net_rappen addieren (rows.append(...))
```

> Achtung Import-Zyklus: `_wealth_inflow_series_rappen` ist „private“ (Unterstrich). Wenn ein direkter Import unerwünscht ist, eine **dünne, public Re-Export-Funktion** im selben Modul ergänzen (z.B. `def wealth_inflow_series_rappen(...)` als Alias) — NICHT die Logik duplizieren. Owner-Entscheid B.6.
> `value_mode='real'` exakt wie in der Engine wäre nur mit Inflations-Serie korrekt; im Live-Endpoint ohne Strategie ist nominaler Pfad (`inflation_series_bps=None`) eine bewusste Vereinfachung — dokumentieren.

## B.4 Test-Plan #54

Backend (falls B.3.3 umgesetzt) — neue Tests in `tests/test_cashflow_projection.py` (existiert):
1. Einmaliger Inflow im Jahr Y erscheint als `capital_inflow_rappen` in genau Y, sonst 0.
2. Recurring (jährlich, duration=3) erscheint in Y…Y+2.
3. Recurring monatlich → `amount*12` p.a.
4. Soft-deleted/`is_active=0`-Inflow erscheint nicht.
5. Inflow außerhalb Horizont → ignoriert.
FE: manueller Smoke (Modal anlegen → Liste → grüner Marker an richtiger Jahres-Position; Edit/Delete).

## B.5 Edge-Cases #54

- `expected_year` vor `start_year` (Vergangenheit): Engine-Func ignoriert (Offset<0, Zeile 4307) → kein Marker. FE: solche Inflows in Liste anzeigen, aber nicht im Chart.
- Recurring ohne `duration_years`: Backend 422 (`_validate_recurring`). FE muss Feld erzwingen.
- `value_mode='real'` im Live-Chart: bewusst nominal approximiert (siehe B.3.3) — Tooltip kennzeichnet „(real)“ trotzdem.
- Doppel-Erfassung Inflow vs. Income-Cashflow „einmalig“: fachlich beides möglich; KEINE automatische Dedup (Berater-Verantwortung). Hinweistext im Modal.
- Mandate-spezifischer Inflow (`mandate_id` gesetzt): Live-Endpoint ist client-weit → zeigt ihn (kein Mandate-Filter im IST-Chart). Konsistent mit Engine-Default (client-weit, falls mandate_id null).

---

# Teil C — #55 [ENG] Mehrjahres-Cashflow-Editor (Phasen)

## C.1 Ziel

Lohn endet / AHV beginnt **lückenlos und überlappungsfrei** modellieren (unter Beachtung `valid_until` INKLUSIV); Verzehrphasen (Ausgaben > Einkommen nach Pensionierung) sichtbar machen. Heute macht der Berater das manuell über zwei Cashflows — fehleranfällig (Off-by-one an der Inklusiv-Grenze, Lücken/Überlappungen).

## C.2 IST-Zustand (verifiziert)

Cashflow-Modell & Annualisierung:
- `models/wealth.py:65-88` `Cashflow` mit `valid_from`, `valid_until`, `frequency`, `nature`, `is_inflation_linked`.
- `schemas/wealth.py:171-203` `CashflowCreate/Update` (Datums-Strings).
- `routers/wealth.py:67-116` `_normalize_cashflow_payload`: normalisiert Daten (YYYY-MM → YYYY-MM-01 via `_normalize_cashflow_date` Zeile 31-49), erzwingt `valid_until >= valid_from` (Zeile 103-104), einmalig ⇒ `valid_until = valid_from` (Zeile 102).

**`valid_until` INKLUSIV — bestätigt** in `services/cashflow_timeline.py`:
- `contribution_for_year(...)` Zeile 92-156.
- Out-of-range-Check `if end and end < year_start: return 0` (Zeile 127) — strikt `<`, d.h. Endjahr selbst zählt.
- `effective_end = min(end or year_end, year_end)` (Zeile 140); Occurrence-Loop bricht bei `occ > effective_end` (Zeile 150) → Occurrence **auf** `valid_until` wird mitgezählt. (Bewiesen durch `tests/test_cashflow_timeline.py` „bis Juni = 6 Monate inkl. Juni“.)

Projektion/Horizont (live):
- `routers/clients.py:397-455` `GET /clients/{id}/cashflow-projection`; Horizont aus Stammdaten + erfassten Cashflows bis Lebensende (`_derive_cashflow_projection_horizon` Zeile 328-394, nutzt `valid_until` jeder CF + `life_expectancy_year_for`).
- Aggregation: `services/cashflow_timeline.py:225-298` `totals_for_year` (trennt `recurring_*` vs `capital_*`).

Pensionierung/AHV heute:
- `PlanningAssumption` (`models/wealth.py:163-184`) hat `retirement_age_primary/_partner`, `life_expectancy_primary/_partner` — aber **NICHT** automatisch in die Cashflow-Aktivierung verdrahtet. Engine liest PlanningAssumption (`portfolio_engine.py:~4522`), nutzt es für Inflation/Horizont, **nicht** zum Auto-Phasen von Cashflows.
- Heute: Berater legt 2 Cashflows an: Lohn `valid_until="JJJJ-12-31"` (Pensionsjahr), AHV `valid_from="(JJJJ+1)-01-01"`. Es gibt **kein** „Phase“-Konzept.

**LÜCKE:** Kein Phasen-UI; kein Validator gegen Lücken/Überlappungen; Inklusiv-Grenze ist für den Berater nicht sichtbar/automatisiert.

## C.3 SOLL-Design

**Bewusster Architektur-Entscheid:** KEIN neues DB-Modell für „Phasen“. Eine Phase = ein bestehender `Cashflow` mit `valid_from`/`valid_until`. Das Phasen-Konzept ist eine **FE-UX-Schicht + ein leichter Backend-Validator** über mehreren Cashflows desselben „Stroms“ (z.B. „Erwerbseinkommen“). Damit bleibt Engine/Projektion unverändert (Strategietreue, kein Engine-Umbau).

### C.3.1 FE — Phasen-Editor-UX (5eyes_v2.html, Cashflow-Tab)

„Phasen-Assistent“ als Erweiterung des Cashflow-Modals (`m-acf` ~4131). Zwei Modi:

1. **Erwerb→AHV-Assistent** (1 Klick): Eingabe „Pensionierungsjahr P“ + Lohn-Betrag + AHV-Betrag → erzeugt **zwei** Cashflows in einem Rutsch:
   - Lohn: `cashflow_type=Income`, `valid_until = "P-12-31"` (INKLUSIV → Lohn bis Jahresende P).
   - AHV: `cashflow_type=Income`, `valid_from = "(P+1)-01-01"`, `is_inflation_linked=1` (AHV typischerweise indexiert; Default an, abschaltbar).
   - Hinweistext direkt im UI: „Lohn läuft bis 31.12.{P} (inklusiv), AHV ab 01.01.{P+1} — lückenlos.“
2. **Freie Phasen-Liste**: pro „Strom“ (Label-Gruppe) eine Timeline mehrerer Segmente; FE prüft live auf:
   - **Lücke**: `next.valid_from` > `prev.valid_until + 1 Tag`.
   - **Überlappung**: `next.valid_from` <= `prev.valid_until`.
   Visuelle Warnung (gelb) bei Lücke/Überlappung; Speichern bleibt erlaubt (Berater kann bewusst Lücken wollen), aber bestätigungspflichtig.

Verzehrphase: keine Sonderlogik nötig — ergibt sich automatisch, wenn Ausgaben-Cashflows nach Pensionierung das (reduzierte) Einkommen übersteigen; der `#ch-ist`-Chart zeigt den Vermögensverzehr bereits (Horizont bis Lebensende, `_derive_cashflow_projection_horizon`). FE: optionaler Hinweis „Ab {Jahr X}: Verzehrphase (Netto-Cashflow negativ)“ aus der `cashflow-projection`-Antwort (erstes Jahr mit `net_rappen < 0` nach Pensionierung).

### C.3.2 Backend — Phasen-Validator (neu, optional aber empfohlen)

Endpoint, der die Cashflows eines Clients gruppiert (per `label` oder neuem optionalen Feld `phase_group`) und Lücken/Überlappungen meldet — **read-only**, blockiert nichts:

```python
# routers/wealth.py — neuer GET
@router.get("/clients/{client_id}/cashflow-phases-check")
def cashflow_phases_check(client_id, db=Depends(get_db), current_user=Depends(get_current_user)):
    get_client_for_user_or_404(client_id, db, current_user)
    cfs = db.query(Cashflow).filter(Cashflow.client_id==client_id,
        Cashflow.deleted_at.is_(None), Cashflow.is_active==1,
        Cashflow.nature != "einmalig").all()
    # gruppieren nach normalisiertem label, sortieren nach valid_from,
    # je Gruppe Lücken/Overlaps berechnen (valid_until INKLUSIV: gap wenn
    # next.from > until + 1 Tag; overlap wenn next.from <= until)
    return {"groups": [...]}  # {label, segments:[{from,until}], gaps:[...], overlaps:[...]}
```

`valid_until`-Inklusiv-Arithmetik exakt: Lücke ⇔ `date(next.valid_from) > date(prev.valid_until) + timedelta(days=1)`; Überlappung ⇔ `date(next.valid_from) <= date(prev.valid_until)`. (Datums-Parsing via `services/cashflow_timeline._parse_date`.)

> KEIN neues Pflicht-DB-Feld. Falls Owner saubere Gruppierung statt Label-Heuristik will: optionales nullable `phase_group = Column(String)` auf `Cashflow` + im Schema — additive Migration, BC. Owner-Entscheid C.6.

### C.3.3 Keine Engine-Änderung

`contribution_for_year`/`totals_for_year` bleiben unverändert (Inklusiv-Semantik ist bereits korrekt). Der Phasen-Editor produziert nur korrekt gesetzte `valid_from/valid_until` — die Engine rechnet sie schon richtig.

## C.4 Test-Plan #55

Backend `tests/test_cashflow_phases.py` (neu):
1. Lohn `valid_until=2038-12-31`, AHV `valid_from=2039-01-01` → keine Lücke, keine Überlappung; Lohn trägt in 2038 voll, 0 in 2039; AHV 0 in 2038, voll ab 2039 (via `totals_for_year` an der Grenze — schützt die Inklusiv-Semantik).
2. Lücke: AHV `valid_from=2040-01-01` → `gaps` enthält 2039.
3. Überlappung: AHV `valid_from=2038-06-01` → `overlaps` gemeldet; `totals_for_year(2038)` zählt beide (Doppelzählung sichtbar → rechtfertigt Warnung).
4. Inklusiv-Grenz-Regression: monatlicher Lohn `valid_until=2038-06-30`, Jahr 2038 → 6 Occurrences (Jan–Jun inkl.).
5. Einmalige Cashflows werden NICHT als Phase gewertet (Filter `nature != einmalig`).
FE: manueller Smoke des Assistenten (P=2038 → zwei korrekte Cashflows; Grenz-Hinweis sichtbar).

## C.5 Edge-Cases #55

- **valid_until INKLUSIV** (Kern-Risiko): Assistent MUSS Lohn-Ende auf `P-12-31` setzen, AHV-Start `(P+1)-01-01`. Falsch wäre Lohn `valid_until="P-12-31"` + AHV `valid_from="P-12-31"` (Überlappung im Dez P). Tests #1/#3 sichern das ab.
- **Überlappende Phasen**: erlaubt (Berater-Entscheid), aber führt zu Doppelzählung in `totals_for_year` → Warn-Banner zwingend, nie still.
- **Monats-Präzision**: `valid_from="JJJJ-MM"` wird zu `-01` normalisiert (`_normalize_cashflow_date`), `valid_until` Monat → erster Tag (Achtung: NICHT Monatsende!). Für saubere Inklusiv-Grenze im Monatsmodus Lohn-Ende explizit auf Monats-Ende setzen oder Assistent nur Jahres-Präzision (12-31) verwenden lassen. Owner-Entscheid C.6.
- **Schaltjahr/kurze Monate**: `_add_months` re-klemmt vom Original-Tag (cashflow_timeline.py:142-145 Kommentar) — Occurrence-Count an der Grenze korrekt. Kein Handlungsbedarf, nur in Tests abdecken.
- **Phase ohne valid_until** (offenes Ende, z.B. AHV bis Lebensende): erlaubt; `effective_end = year_end` pro Jahr → läuft bis Horizont. Horizont deckt via Lebenserwartung ab.
- **Mehrere Ströme gleichen Labels**: Label-Heuristik kann falsch gruppieren → Argument für optionales `phase_group` (C.3.2 / C.6).

---

# OWNER-DECISIONS (vor Implementierung bestätigen)

1. **#24 Soft-Limit-Schwelle**: Default `SOFT_LIMIT_THRESHOLD_PCT = 80`. Alternativen: 75 / 90. Pro Kind unterschiedlich? (Empfehlung: einheitlich 80.)
2. **#24 Hard-No-Overshoot bei Race**: IST-Verhalten (möglicher +1-Overshoot bei paralleler Erstellung) belassen ODER `FOR UPDATE`-Lock in `assert_within_quota` ergänzen? (Empfehlung: belassen — geringe Wahrscheinlichkeit, kein Datenleak.)
3. **#24 Quota-Status-Sichtbarkeit**: Eigener `/quota/status` für jeden Advisor/Admin (Empfehlung) ODER nur in der super_admin-`/tenants`-Admin-Sicht?
4. **#54 Live-Endpoint**: Inflows zusätzlich in `GET /cashflow-projection` einrechnen (Empfehlung ja, via Re-Export der Engine-Func) ODER Chart-Marker rein FE-seitig aus `/wealth-inflows` und Projektionslinie nur bei Strategie-Lauf?
5. **#54 Inflow-Liste Platzierung**: im Cashflow-Tab (neben Zu-/Abflüssen) ODER im Vermögens-Tab?
6. **#55 Phasen-Gruppierung**: Label-Heuristik (kein Schema-Change) ODER additives nullable `phase_group` auf `Cashflow`? Und: Phasen-Assistent nur Jahres-Präzision (12-31/01-01) erzwingen?

---

# Datei-Referenz-Index (alles per Read verifiziert)

| Bereich | Datei:Zeile |
|---|---|
| Tenant-Quota-Spalten | `models/tenant.py:80,82,84` |
| Hard-Quota-Service | `services/quota.py:20-71` |
| Quota-Aufrufe | `routers/auth.py:386,453`; `routers/mandates.py:55` |
| Quota-Tests (IST) | `tests/test_tenant_quota_enforcement.py` |
| Tenant-Auflösung | `services/auth.py:48-61,268-306,309-315` |
| Create User/Invite | `routers/auth.py:372-410,431-484` |
| Create Mandate | `routers/mandates.py:36-78` |
| Create Client (tenant-vererbt, keine Quota) | `routers/clients.py:71-101` |
| WealthInflow-Modell | `models/wealth.py:91-118` |
| WealthInflow-Schemas | `schemas/wealth.py:259-314` |
| WealthInflow-CRUD | `routers/wealth.py:951-1038` |
| Inflow-Engine-Konsum | `services/portfolio_engine.py:4278-4333,4420-4427` |
| Inflow im PDF | `routers/pdf_reports.py:564-568` |
| Cashflow-Modell | `models/wealth.py:65-88` |
| Cashflow-Normalisierung | `routers/wealth.py:31-116` |
| valid_until INKLUSIV | `services/cashflow_timeline.py:127,140,150` |
| totals_for_year | `services/cashflow_timeline.py:225-298` |
| Live cashflow-projection | `routers/clients.py:328-455` |
| Projection-Schema | `schemas/clients.py:161-175` |
| PlanningAssumption | `models/wealth.py:163-184` |
| FE Cashflow-Modal/Save | `5eyes_v2.html` ~4131-4235 / `saveCashflow()` ~20897 / `refreshCashflowsUI()` ~21058 |
| FE Wealth-Modal | `5eyes_v2.html` ~4393-4597 |
| FE Chart IST | `5eyes_v2.html` `#ch-ist` ~2972 / `initCharts()` ~6947 / Marker ~21206-21246,17790-17792 |
| FE API-Wrapper / Nav / Toast | `5eyes_v2.html` API ~4610-4724 / `go()` ~5357 / `showAppError/Warn` ~15132-15133 |

> Hinweis: FE-Zeilennummern (5eyes_v2.html, ~1.5 MB) per Such-Agent ermittelt; vor der Bearbeitung mit Grep auf Funktionsnamen/Modal-IDs gegenprüfen — Backend-Zeilennummern direkt per Read verifiziert.
