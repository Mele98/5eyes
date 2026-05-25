# Codex-Sprint U-P30 — Ausgangslage-Felder aus existierenden Daten ableiten

> **Adressat:** Codex (5eyes-Session).
> **Erstellt durch:** Claude (Opus 4.7), 2026-05-25.
> **Audit-Quelle:** §3.1 — 4 Felder im `client_info` sind heute 0/null
> obwohl die Quell-Daten in der DB existieren.
> **Voraussetzung:** U-P23 fertig (oder zumindest PR A gemerged, damit
> schema_version=2 da ist).
> **Größenordnung:** klein — ~3-5 Stunden, 1-2 PRs.

---

## Befund (aus Audit-Live-Test mit MX-FOUNDATION-01)

```json
"client_info": {
  "alter": 0,                       ← Quelle existiert: client.date_of_birth
  "anlagehorizont_jahre": 0,        ← Quelle existiert: mandate.retirement_year
  "anlageziel": "—",                ← Quelle existiert: Goal mit höchstem rank
  "liquiditaetsbedarf_rappen": 0,   ← Quelle ableitbar: Cashflow-Sum(Ausgaben) × 0.5J
  // OK
  "risikoprofil": "Defensiv",
  "steuerdomizil": "CH",
  "referenzwaehrung": "CHF"
}
```

**Schema-Realität (DB-Check):** Die Mandate-Tabelle hat KEINE Spalten
`investment_horizon_years`, `primary_goal_label`, `liquidity_need_rappen`
— sie existieren nur als optionale Attribute, die nie persistiert
wurden. Plus: `client.date_of_birth` ist da, aber nicht in `client.age`
übersetzt.

→ **Keine Schema-Migration nötig**, nur Code-Ableitung.

---

## Was zu ändern ist

### Datei `services/advisory_report.py::_build_ausgangslage()`

Aktuell:
```python
client_info = {
    "alter": _safe_int(getattr(client, "age", None)),
    "anlagehorizont_jahre": _safe_int(
        getattr(mandate, "investment_horizon_years", None)
    ),
    "risikoprofil": str(getattr(mandate, "risk_profile_label", "") or "")
        or _resolve_risk_profile_from_assessment(db, mandate),
    "anlageziel": str(getattr(mandate, "primary_goal_label", "") or "") or "—",
    "liquiditaetsbedarf_rappen": _safe_int(
        getattr(mandate, "liquidity_need_rappen", None)
    ),
    ...
}
```

Neue Logik mit Fallback-Cascade:

```python
client_info = {
    "alter": _derive_age(client),
    "anlagehorizont_jahre": _derive_investment_horizon(mandate),
    "risikoprofil": _resolve_risk_profile_from_assessment(db, mandate),
    "anlageziel": _derive_primary_goal_label(db, mandate),
    "liquiditaetsbedarf_rappen": _derive_liquidity_need(db, mandate),
    ...
}
```

### Helper-Funktionen (NEU im selben Modul)

```python
def _derive_age(client: Client) -> int:
    """Alter aus client.date_of_birth (ISO YYYY-MM-DD)."""
    dob = str(getattr(client, "date_of_birth", "") or "")
    if not dob or len(dob) < 10:
        return 0
    try:
        from datetime import date
        birth = date.fromisoformat(dob[:10])
        today = date.today()
        return today.year - birth.year - (
            (today.month, today.day) < (birth.month, birth.day)
        )
    except ValueError:
        return 0


def _derive_investment_horizon(mandate: Mandate) -> int:
    """Horizont aus mandate.retirement_year - aktuelles Jahr.
    Falls retirement_year nicht da: aus life_expectancy_year.
    Falls beide nicht: 10 (konservativer Default fuer Mittelfrist)."""
    from datetime import date
    today = date.today().year
    retirement = _safe_int(getattr(mandate, "retirement_year", None))
    if retirement and retirement > today:
        return retirement - today
    life_exp = _safe_int(getattr(mandate, "life_expectancy_year", None))
    if life_exp and life_exp > today:
        return life_exp - today
    return 10  # konservativer Default


def _derive_primary_goal_label(db: Session, mandate: Mandate) -> str:
    """Label des Goals mit niedrigstem rank (= wichtigstes Goal).
    Fallback '—' wenn keine Goals."""
    from models.wealth import Goal
    goal = (
        db.query(Goal)
        .filter(
            Goal.mandate_id == mandate.id,
            Goal.is_active == 1,
        )
        .order_by(Goal.rank.asc())
        .first()
    )
    if goal is None:
        return "—"
    return str(getattr(goal, "label", "") or "—")


def _derive_liquidity_need(db: Session, mandate: Mandate) -> int:
    """Liquiditätsbedarf = ca. 6 Monate Ausgaben aus Cashflows.
    Konservative Faustregel der Schweizer Beratung."""
    from models.wealth import Cashflow
    client_id = getattr(mandate, "client_id", None)
    if not client_id:
        return 0
    cashflows = (
        db.query(Cashflow)
        .filter(
            Cashflow.client_id == client_id,
            Cashflow.is_active == 1,
            Cashflow.cashflow_type == "Expense",
        )
        .all()
    )
    annual_expenses_rappen = 0
    for cf in cashflows:
        amount = _safe_int(getattr(cf, "amount_rappen", 0))
        freq = str(getattr(cf, "frequency", "") or "").lower()
        if "jährlich" in freq or "jahr" in freq:
            annual_expenses_rappen += amount
        elif "monatlich" in freq or "monat" in freq:
            annual_expenses_rappen += amount * 12
        elif "quartal" in freq:
            annual_expenses_rappen += amount * 4
    # 6 Monate = 0.5 Jahres-Ausgaben
    return int(annual_expenses_rappen * 0.5)
```

### Tests in `tests/test_advisory_report.py`

```python
def test_ausgangslage_derives_age_from_date_of_birth():
    # Client mit dob=1976-09-18 → erwartetes Alter ~49
    ...

def test_ausgangslage_derives_horizon_from_retirement_year():
    # Mandate mit retirement_year=2040 → erwartet 2040 - current_year
    ...

def test_ausgangslage_derives_primary_goal_label_from_lowest_rank():
    # Goals mit rank 1,2,3 → "Goal-1-Label"
    ...

def test_ausgangslage_derives_liquidity_need_from_expense_cashflows():
    # Cashflow Expense jährlich 120k → liquiditaetsbedarf = 60'000_00 (6 Monate)
    ...

def test_ausgangslage_falls_back_to_defaults_when_no_data():
    # Leeres Mandat → alle Felder 0 oder "—" oder 10 (Horizont-Default)
    ...
```

---

## Acceptance

1. Live-Test mit MX-FOUNDATION-01:
   - `alter` = 49 (statt 0) — aus client.date_of_birth abgeleitet
   - `anlagehorizont_jahre` = X (aus retirement_year - 2026)
   - `anlageziel` = Label des Goals mit rank=1
   - `liquiditaetsbedarf_rappen` = ~6 Monate Ausgaben aus Cashflows
2. Frontend Sektion 4 Ausgangslage zeigt diese Werte korrekt
3. Bei Mandat OHNE Goals/Cashflows: sinnvolle Defaults (—, 0, 10)
4. Tests grün (mind. 5 neue)

---

## Verboten

- KEIN Schema-Edit (alle Quell-Daten sind schon da)
- KEINE Datenbank-Migration nötig
- Keine Dritt-Marken
