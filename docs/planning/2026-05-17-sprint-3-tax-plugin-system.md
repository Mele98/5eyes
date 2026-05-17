# Sprint 3 — Tax-Plugin-System (downscaled, Allocation-Fokus)

**Datum:** 2026-05-17
**Status:** Phase 1 + Phase 2-Light DONE. Phase 3 (UI-Dropdown + Mandate-FK)
offen — fuer naechste Session oder Codex.
**Commits:**
- Phase 1 Foundation: `4f201df` (Plugin-Architektur, Engine-Integration, 61 Tests)
- Phase 2-Light: `3c0b5d5` (CHTaxRegime + DETaxRegime + 20 Tests)
**Vorgaenger:** Sprint 2 (Steuern in CMA) wurde REVERTIERT (commit 02d2cc5).

## ⚠️ SCOPE-AENDERUNG (2026-05-17 nachmittag)

Nach dem Aufbau der Phase-1-Foundation (Plugin-Architektur, GenericFlatRate,
Engine-Integration) hat der User klargestellt:

> "fuer die endversion ist tax nicht so relevant wie die anderen funktionen.
> weil tax wuerde ja ein seperates modell machen im Assetmanagement ist.
> Wir brauchen es nur fuer asset allocation interessen falls wir irgendwie
> ein Yield portfolio machen wuerden"

**Konsequenz:**
- Phase 1 bleibt wie gebaut (Foundation ist gut und erweiterbar)
- **Phase 2** wird reduziert: 2 Mini-Regimes (CH-Light + DE-Light) mit
  Pauschal-Mittelwerten statt 26 Kantone progressiv
- **Phase 3** wird reduziert: Dropdown im Mandate-Form + 3 Override-Felder
  + Disclaimer — keine separate Audit-UI
- **Phasen 4-6 GESTRICHEN**: keine Asien/USA-Regimes, keine TaxJurisdiction-
  Tabelle, kein TaxCalculationLog, kein Tarif-Versioning, kein Multi-Tenant

**Rationale:** Echte WM-Tax-Engine ist ein separates Produkt (TaxCalc,
Avalara). 5eyes braucht Tax NUR damit Asset-Allocation-Optimierung die
echten Tax-Drag-Effekte beruecksichtigen kann (Yield- vs Capital-Gain-
Strategie, CH-Anleihen vs CH-Aktien).

## 0. Vision & Scope

5eyes soll **in Zukunft als Wealth-Management-System** nutzbar sein:
nicht nur fuer Schweizer Finanzberater, sondern fuer Vermoegensverwalter in
**jedem Land der Welt** (CH, EU, Asien, USA, Naher Osten, ...).

Das Steuer-Modell ist daher **kein hartcodiertes Lookup**, sondern eine
**Plugin-Architektur** (Strategy + Registry Pattern):
- Engine bleibt Steuer-agnostisch.
- Neue Laender = neue Python-Klasse + Registry-Eintrag, KEIN Engine-Refactor.
- Berater (Endkunde) kann pro Mandant Override-Werte setzen.
- Tarif-Aenderungen pro Jahr durch versionierte Tabellen.
- Voll auditierbar fuer Compliance (FINMA, BaFin, FCA, MAS, SEC, ...).

## 1. Architektur-Prinzipien

| Prinzip | Wie realisiert |
|---|---|
| **Open-Closed** | Engine geschlossen, Tax-Erweiterungen offen via Plugin |
| **Strategy Pattern** | TaxRegime-Interface, austauschbare Implementierungen |
| **Registry Pattern** | Decorator `@register_regime`, Lookup per ID |
| **Data-Driven** | Parameter (bps) in DB, Logik in Code |
| **Tax-Year-Aware** | valid_from/valid_until pro Tarif-Set |
| **Multi-Tenant-Ready** | Plugin-Set pro Tenant moeglich (Phase 4) |
| **Auditable** | TaxCalculationLog pro Mandant+Jahr+Tax-Typ |
| **Multi-Currency-Ready** | Regime weiss Lokalwaehrung, Engine konvertiert |
| **Validation** | Plausibilitaetspruefung (50% wealth tax → Warnung) |
| **Override-Safe** | Berater-Overrides werden separat geloggt |
| **Compliance-Disclaimer** | UI zeigt "Schaetzwerte, kein Steuergutachten" |

## 2. Modul-Struktur

```
5eyes-backend/
├── services/tax/
│   ├── __init__.py                    # Re-Exports
│   ├── base.py                        # TaxRegime-Protocol, TaxConfig, TaxResult
│   ├── registry.py                    # @register_regime, REGIME_REGISTRY
│   ├── resolver.py                    # resolve_regime(mandate) → TaxRegime
│   ├── validator.py                   # validate_parameters(...) Plausi-Check
│   ├── audit.py                       # log_tax_calculation(...)
│   ├── overrides.py                   # apply_mandate_overrides(regime, overrides)
│   └── regimes/
│       ├── __init__.py                # Auto-Import aller Regimes
│       ├── generic.py                 # GenericFlatRateRegime
│       ├── ch.py                      # CHTaxRegime (26 Kantone)
│       ├── de.py                      # DETaxRegime
│       ├── at.py                      # ATTaxRegime
│       ├── fr.py                      # FRTaxRegime
│       ├── it.py                      # ITTaxRegime
│       ├── es.py                      # ESTaxRegime
│       ├── nl.py                      # NLTaxRegime
│       ├── lu.py                      # LUTaxRegime
│       ├── uk.py                      # UKTaxRegime
│       ├── us.py                      # USTaxRegime (Federal + State)
│       ├── ca.py                      # CATaxRegime
│       ├── jp.py                      # JPTaxRegime
│       ├── sg.py                      # SGTaxRegime
│       ├── hk.py                      # HKTaxRegime
│       ├── cn.py                      # CNTaxRegime
│       ├── kr.py                      # KRTaxRegime
│       ├── in_.py                     # INTaxRegime (in_ wegen Reserved Word)
│       ├── ae.py                      # AETaxRegime (0% Income)
│       ├── au.py                      # AUTaxRegime
│       └── il.py                      # ILTaxRegime
├── models/
│   ├── tax_jurisdiction.py            # TaxJurisdiction
│   ├── tax_tariff_version.py          # TaxTariffVersion (Jahres-Versioning)
│   └── tax_calculation_log.py         # TaxCalculationLog (Audit)
├── schemas/tax.py                     # Pydantic-Schemas
├── api/tax.py                         # REST-Endpoints
└── seeds/tax/
    ├── ch_kantone.json                # 26 Kantone Default-Werte 2026
    ├── eu_countries.json              # 12 EU-Laender
    ├── asia_countries.json            # 8 Asien-Laender
    └── americas_countries.json        # 6 Amerika-Laender (US-States separat)
```

## 3. Core-Interface — TaxRegime

```python
# services/tax/base.py

from __future__ import annotations
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass(frozen=True)
class TaxContext:
    """Eingabe-Kontext fuer eine Steuer-Berechnung."""
    year_index: int                # 0..horizon-1
    calendar_year: int             # absolute Jahr, fuer Tariff-Versioning
    wealth_rappen: float           # aktuelles Vermoegen
    age: int | None                # fuer altersabhaengige Steuern
    is_retired: bool               # Phase = Akkumulation vs. Decumulation
    currency_code: str             # 'CHF', 'EUR', 'USD' fuer Multi-Currency

@dataclass(frozen=True)
class TaxResult:
    """Ausgabe einer Steuer-Berechnung mit Audit-Info."""
    amount_rappen: float           # absoluter Steuerbetrag
    effective_bps: float           # effektiver Satz in bps
    regime_id: str                 # 'CH-ZH'
    tariff_version: str            # '2026-CH-ZH-v1'
    breakdown: dict[str, float]    # {'kantonal': ..., 'gemeinde': ..., 'bund': ...}
    used_overrides: dict[str, float] | None  # falls Berater-Override aktiv

@runtime_checkable
class TaxRegime(Protocol):
    """Universal-Interface fuer jedes Land. Engine kennt nur diese Methoden."""
    
    @property
    def id(self) -> str: ...                 # 'CH-ZH', 'DE', 'US-NY'
    
    @property
    def country_code(self) -> str: ...       # ISO 3166: CH, DE, US
    
    @property
    def display_name(self) -> str: ...       # 'Schweiz — Zuerich'
    
    @property
    def local_currency(self) -> str: ...     # 'CHF', 'EUR', 'USD'
    
    @property
    def supports_wealth_tax(self) -> bool: ...    # CH=True, DE=False
    
    @property
    def supports_capital_gains_tax(self) -> bool: ... # CH=False, DE=True
    
    def annual_wealth_tax(self, ctx: TaxContext) -> TaxResult:
        """Vermoegenssteuer p.a. CH=kantonal-progressiv, DE/US=0."""
    
    def dividend_tax(self, ctx: TaxContext, dividend_income_rappen: float) -> TaxResult:
        """Steuer auf Dividenden-Income. CH=marginal-progressiv, DE=26.4% flat."""
    
    def interest_tax(self, ctx: TaxContext, interest_income_rappen: float) -> TaxResult:
        """Steuer auf Zins-Income. Oft = dividend_tax, kann aber abweichen (CH-Sparkonto-Pauschale, ...)"""
    
    def capital_gains_tax(self, ctx: TaxContext, gains_rappen: float, holding_years: int) -> TaxResult:
        """Steuer auf Kursgewinne. CH=0 (Privat), DE=26.4%, US=0/15/20% LTCG."""
    
    def pension_lumpsum_tax(self, ctx: TaxContext, amount_rappen: float) -> TaxResult:
        """Kapitalbezugssteuer (BVG/3a/401k-Bezug). CH=kantonal separat-Tarif."""
    
    def inheritance_tax(self, ctx: TaxContext, amount_rappen: float, relation: str) -> TaxResult:
        """Erbschaftssteuer. Phase 5+ — pro Jurisdiktion sehr verschieden."""
    
    def validate_parameters(self, params: dict) -> list[str]:
        """Plausibilitaets-Pruefung. Returns Warnings als List[str]."""
    
    def with_overrides(self, overrides: dict) -> "TaxRegime":
        """Returns neue Regime-Instanz mit ueberschriebenen Parametern."""
```

## 4. Registry

```python
# services/tax/registry.py

REGIME_REGISTRY: dict[str, type[TaxRegime]] = {}

def register_regime(id_pattern: str):
    """Decorator. id_pattern kann Glob ('CH-*') oder exakt ('DE') sein."""
    def wrapper(cls):
        REGIME_REGISTRY[id_pattern] = cls
        return cls
    return wrapper

def resolve_regime_class(jurisdiction_id: str) -> type[TaxRegime]:
    """Lookup mit Glob-Matching. Fallback: GenericFlatRateRegime."""
    for pattern, cls in REGIME_REGISTRY.items():
        if _matches(jurisdiction_id, pattern):
            return cls
    return GenericFlatRateRegime
```

## 5. Daten-Schicht

### 5.1 TaxJurisdiction

```sql
CREATE TABLE tax_jurisdictions (
    id TEXT PRIMARY KEY,                  -- 'CH-ZH', 'DE', 'US-NY'
    country_code TEXT NOT NULL,           -- ISO 3166: CH, DE, US, JP
    region_code TEXT,                     -- Kanton/State/Bundesland (NULL fuer Land-only)
    regime_class TEXT NOT NULL,           -- 'CHTaxRegime' (Registry-Lookup)
    display_name TEXT NOT NULL,           -- 'Schweiz — Zuerich'
    local_currency TEXT NOT NULL,         -- 'CHF', 'EUR', 'USD'
    is_seed BOOLEAN NOT NULL DEFAULT 0,   -- vom 5eyes-Team vs. Berater-eigen
    notes TEXT,                           -- Quellen, Annahmen
    created_at TIMESTAMP NOT NULL,
    created_by TEXT,
    updated_at TIMESTAMP NOT NULL,
    updated_by TEXT
);
```

### 5.2 TaxTariffVersion (Jahres-Versioning)

```sql
CREATE TABLE tax_tariff_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jurisdiction_id TEXT NOT NULL REFERENCES tax_jurisdictions(id),
    version_label TEXT NOT NULL,          -- '2026-CH-ZH-v1'
    valid_from DATE NOT NULL,
    valid_until DATE,                     -- NULL = aktuell
    parameters_json TEXT NOT NULL,        -- Regime-spezifische Werte
    source TEXT,                          -- Quelle, z.B. "ESTV-Verordnung 2026"
    created_at TIMESTAMP NOT NULL,
    created_by TEXT,
    UNIQUE(jurisdiction_id, valid_from)
);
```

Beispiel `parameters_json` fuer CH-ZH 2026:
```json
{
  "kantonsmult": 0.97,
  "gemeindemult": 1.19,
  "wealth_tax_tariff": [
    {"from_chf": 0, "to_chf": 80000, "rate_pm": 0.0},
    {"from_chf": 80000, "to_chf": 130000, "rate_pm": 0.5},
    {"from_chf": 130000, "to_chf": 280000, "rate_pm": 1.5},
    {"from_chf": 280000, "to_chf": 780000, "rate_pm": 2.0},
    {"from_chf": 780000, "to_chf": null, "rate_pm": 3.0}
  ],
  "dividend_income_marginal_rate": 0.30,
  "capital_gains_rate": 0.0,
  "pension_lumpsum_tariff": [
    {"from_chf": 0, "to_chf": 50000, "rate": 0.045},
    {"from_chf": 50000, "to_chf": 200000, "rate": 0.075},
    {"from_chf": 200000, "to_chf": null, "rate": 0.12}
  ]
}
```

### 5.3 TaxCalculationLog (Audit-Trail)

```sql
CREATE TABLE tax_calculation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mandate_id INTEGER NOT NULL REFERENCES mandates(id),
    calculation_run_id TEXT NOT NULL,     -- Gruppiert pro Simulations-Lauf
    jurisdiction_id TEXT NOT NULL,
    tariff_version TEXT NOT NULL,
    year_index INTEGER NOT NULL,
    calendar_year INTEGER NOT NULL,
    tax_type TEXT NOT NULL,               -- 'wealth' | 'dividend' | 'capital_gains' | 'pension_lumpsum'
    amount_rappen REAL NOT NULL,
    effective_bps REAL NOT NULL,
    breakdown_json TEXT,                  -- {'kantonal': X, 'gemeinde': Y, 'bund': Z}
    overrides_used_json TEXT,             -- NULL wenn kein Override
    timestamp TIMESTAMP NOT NULL,
    INDEX (mandate_id, calculation_run_id),
    INDEX (jurisdiction_id, calendar_year)
);
```

### 5.4 Mandate-Erweiterung

```python
class Mandate(Base):
    # ... existing fields ...
    tax_jurisdiction_id: str | None = Column(String, ForeignKey('tax_jurisdictions.id'))
    tax_overrides_json: str | None = Column(Text)  # JSON: {"wealth_tax_bps_pa": 25}
```

## 6. Engine-Integration

```python
# services/optimizer/scenario_engine.py

def simulate_wealth_paths(
    *, initial_wealth_rappen, weights, return_paths,
    cashflow_series_rappen, liability_path_rappen=None,
    tax_regime: TaxRegime | None = None,           # NEU
    dividend_yield_bps_per_bucket: np.ndarray | None = None,
    mandate_id: int | None = None,                 # fuer Audit-Log
    calculation_run_id: str | None = None,         # fuer Audit-Log
    base_calendar_year: int = 2026,                # fuer Tariff-Versioning
    log_audit: bool = False,                       # opt-in (Perf)
) -> np.ndarray:
    """
    Engine ist Steuer-agnostisch — ruft nur regime.*_tax() auf.
    Backwards-Compat: tax_regime=None → keine Steuern (wie vor Sprint 2).
    """
    ...
    for t in range(horizon):
        wealth_factor = ...  # Returns × Weights
        
        if tax_regime is not None:
            ctx = TaxContext(year_index=t, calendar_year=base_calendar_year+t,
                             wealth_rappen=wealth[t], age=..., is_retired=...,
                             currency_code='CHF')
            
            # Vermoegenssteuer
            if tax_regime.supports_wealth_tax:
                wt = tax_regime.annual_wealth_tax(ctx)
                wealth_factor *= (1 - wt.effective_bps / 10000.0)
                if log_audit:
                    log_tax_calculation(mandate_id, calculation_run_id, ctx, wt, 'wealth')
            
            # Dividenden-Steuer-Drag
            if dividend_yield_bps_per_bucket is not None:
                div_income_rappen = wealth[t] * (weights @ dividend_yield_bps_per_bucket / 10000.0)
                dt = tax_regime.dividend_tax(ctx, div_income_rappen)
                wealth_factor -= dt.effective_bps / 10000.0
                if log_audit:
                    log_tax_calculation(mandate_id, calculation_run_id, ctx, dt, 'dividend')
        
        wealth[t+1] = wealth[t] * wealth_factor + cashflow[t]
```

## 7. Migrations-Pfad

**Aktueller Zustand (post-Revert, commit 02d2cc5):**
- Keine Steuern in CMA mehr
- Engine hat keine `vermoegenssteuer_bps_pa` / `kapitalertrag_steuer_bps` Parameter
- Sauberer Tisch

**Forward:** Direkt Phase-1-Implementation, keine Migration noetig.

## 8. Phasen-Plan

### Status-Snapshot (Ende dieser Session)

| Phase | Inhalt | Status |
|---|---|---|
| 1 | Foundation (Protocol, Registry, Generic, Engine) | ✅ DONE `4f201df` |
| 2-light | CH+DE Mini-Regimes | ✅ DONE `3c0b5d5` |
| 3-light | Mandate-FK + UI-Dropdown | ⏳ open (1-2h) |
| 4-6 | Asien/USA/Audit-Trail/Tariff-Versioning | ❌ GESTRICHEN (Out-of-Scope) |

### Phase 1 — Foundation (diese Session, ~3-4h)
- [ ] services/tax/base.py: TaxRegime-Protocol + TaxContext + TaxResult (15 Tests)
- [ ] services/tax/registry.py: @register_regime + REGIME_REGISTRY + resolve (5 Tests)
- [ ] services/tax/regimes/generic.py: GenericFlatRateRegime (10 Tests)
- [ ] services/tax/validator.py: Plausi-Check (5 Tests)
- [ ] services/tax/overrides.py: apply_overrides (5 Tests)
- [ ] models/tax_jurisdiction.py + Migration (3 Tests)
- [ ] Engine: tax_regime-Parameter (8 Tests)
- [ ] **Σ ~50 Tests, sauberes Fundament**

### Phase 2 — CH + DE konkret (naechste Session, ~3-4h)
- [ ] services/tax/regimes/ch.py + 26 Kantone Seed (25 Tests)
- [ ] services/tax/regimes/de.py + Seed (12 Tests)
- [ ] Mandate.tax_jurisdiction_id + tax_overrides_json + Migration (5 Tests)
- [ ] services/tax/resolver.py: Mandate → TaxRegime mit Overrides (8 Tests)
- [ ] services/tax/audit.py + TaxCalculationLog-Tabelle (8 Tests)
- [ ] **Σ ~58 Tests**

### Phase 3 — UI + API (~2-3h)
- [ ] api/tax.py: GET /tax/jurisdictions, GET /tax/regimes, POST /mandate/{id}/tax (10 Tests)
- [ ] UI: Dropdown Steuersitz im Mandate-Formular
- [ ] UI: Override-Editor (Berater editiert pro Mandant)
- [ ] UI: Disclaimer-Box "Schaetzwerte"
- [ ] UI: Audit-Trail-Viewer pro Mandant

### Phase 4 — Asien + Amerika (~4-6h, on-demand)
- [ ] services/tax/regimes/{at,fr,it,es,nl,lu,uk}.py
- [ ] services/tax/regimes/{jp,sg,hk,cn,kr,in_,ae}.py
- [ ] services/tax/regimes/{us,ca,au}.py
- [ ] State-Stacking fuer US (Federal + State)

### Phase 5 — Tarif-Versioning + Spezialitaeten (spaeter)
- [ ] tax_tariff_versions-Tabelle aktiv nutzen
- [ ] Pension-Lumpsum-Steuer separat in Cashflow-Engine
- [ ] Erbschafts-/Schenkungssteuer fuer Multi-Generation-Planning
- [ ] Currency-Conversion fuer Multi-Currency-Mandate

### Phase 6 — Multi-Tenant (Production-WM-System)
- [ ] Tenant-spezifische Jurisdiction-Sets
- [ ] Whitelabel-Disclaimer (Berater-Kanzlei-Logo)
- [ ] Premium-Content-Lizenzierung pro Land

## 9. Test-Strategie

```
tests/tax/
├── test_base.py                # Protocol-Contract, Dataclass-Frozen
├── test_registry.py            # Decorator, Lookup, Glob-Pattern
├── test_resolver.py            # Mandate → Regime mit Overrides
├── test_validator.py           # Plausi-Warnungen
├── test_overrides.py           # apply_overrides
├── test_audit.py               # Log-Calls, Run-ID-Gruppierung
├── regimes/
│   ├── test_generic.py         # Flat-Rate-Logik
│   ├── test_ch.py              # alle 26 Kantone, Progression, 3a-Befreiung
│   ├── test_de.py              # Sparerpauschbetrag, Teilfreistellung, Soli
│   ├── test_us.py              # Federal+State, LTCG-Brackets
│   ├── test_sg.py              # 0% Capital Gains
│   ├── test_hk.py              # 0% Income Tax Privat
│   └── ...
└── test_engine_with_tax.py     # Engine-Integration end-to-end
```

## 10. Compliance & Disclaimer

**UI-Disclaimer (Pflicht-Anzeige im Steuersitz-Editor):**

> Die in 5eyes hinterlegten Steuersaetze sind **Schaetzwerte** zu
> Planungszwecken. Sie ersetzen **keine** persoenliche Steuerberatung.
> Tatsaechliche Steuern haengen ab von individuellen Faktoren (Einkommen,
> Familienstand, Abzuege, Stiftungen, etc.), die hier vereinfacht abgebildet
> sind. Fuer definitive Berechnungen ist ein qualifizierter Steuerberater
> zu konsultieren.

**Audit-Anforderungen (FINMA / BaFin / FCA-aequivalent):**
- Jede Steuer-Berechnung im Reporting muss reproduzierbar sein.
- TaxCalculationLog speichert: was-Mandant + was-Tarif-Version + was-Override.
- Reports zeigen Tariff-Version-Hash als Footer.

**Versionierung:**
- Tarif-Aenderungen werden NIE in-place mutiert.
- Neuer Tarif = neue Zeile in `tax_tariff_versions` mit `valid_from`.
- Alte Berechnungen bleiben mit altem Tarif reproduzierbar.

## 11. Out-of-Scope (explizit nicht in diesem Sprint)

- Vollumfaengliche Steuerveranlagung (das ist UBS Tax / Deloitte / TaxCalc Job)
- Optimierung Steuer-Asset-Location (Phase 6+)
- Realtime-Tax-API-Anbindungen (z.B. Avalara, TaxJar)
- Erbschafts-/Schenkungs-Planning-Engine (Phase 5)
- Doppelbesteuerungsabkommen-Resolution (Phase 6)

## 12. Erfolgskriterien

| Kriterium | Messbar |
|---|---|
| Engine bleibt Steuer-agnostisch | Grep: kein Land-Code in scenario_engine.py |
| Neues Land = 1 neue Datei | DETaxRegime in 1 PR isoliert hinzuf+gbar |
| Backwards-Compat | Bestehende 1260 Tests bleiben gruen |
| Tax-Year-Versioning funktioniert | Test: 2026 vs 2027 Tarif unterschiedlich |
| Audit-Trail vollstaendig | Test: log_audit=True → N Eintraege fuer N Jahre |
| Berater kann Override setzen | Test: Mandate.tax_overrides_json → Regime nutzt es |
| UI-Disclaimer sichtbar | Manuell + Cypress (spaeter) |
| Plausi-Warnung bei 50% Wealth Tax | Test: validate_parameters → Warning |

---

**Phase 1 startet jetzt.** Ziel: end-of-Session 1260 → ~1310 Tests, sauberes Fundament,
push grun, naechste Session direkt Phase 2.
