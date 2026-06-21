# Spec — Tax-aware Engine Cluster (#39 / #46 / #40)

Datum: 2026-06-21
Branch: `codex/u39-tax-aware-engine`
Status: implementierungsfertig
Scope: 3 Issues, EINE neue Datei `services/tax/cashflow_tax.py` + minimal-additive Hooks (Wiring-Fix + opt-in Flags)

> Konventionen: Alle Beträge in **Rappen** (int). Steuersätze in **bps** (1 bps = 0.01 %).
> Alle Angaben unten sind per Read am echten Code verifiziert (file:line, Stand 2026-06-21).

---

## 1. Ziel

| # | Titel | Ziel |
|---|---|------|
| #39 [TAX] | Steuer in Netto-Cashflow | Vermögens- + Einkommenssteuer-Schätzung (CH-Plugin vorhanden) als **wiederkehrende jährliche Ausgabe** in die Cashflow-**Projektion** einrechnen — additiv, analog Hypothek-Amortisation (#31), **opt-in, default off**. |
| #46 [ENG] | Tax-aware Optimizer-Objective | Nach-Steuer-Wealth-Pfade in die Zielfunktion. **Bereits gebaut** in `simulate_wealth_paths` (Sprint U-P2 C9 / B2). Aufgabe: **kaputtes Wiring reparieren** (`TaxConfig`-Bug) + sauberen **opt-in Flag** + konservative Defaults. |
| #40 [TAX] | Tax-SDK weitere Länder | **Nur** das Plugin-Conformance-Contract-Gerüst spezifizieren (FR/US/IT/AT als Stub-Skelett nach Contract), **nicht** jedes Land ausimplementieren. |

Leitprinzip (OWNER-DECISION, siehe §7): **konservative** Steuer-Annahmen (höhere Steuer im Cashflow / niedrigere Nach-Steuer-Rendite), **opt-in default off**, kein bestehender Pfad ändert Verhalten ohne explizites Flag.

---

## 2. IST-Zustand (verifiziert)

### 2.1 Tax-SDK (Strategy + Registry + Conformance)

- **Protocol / Datentypen** — `services/tax/base.py`
  - `TaxContext` (frozen dataclass): `year_index`, `calendar_year`, `wealth_rappen`, `age`, `is_retired`, `currency_code="CHF"`, `marital_status`, `children_count` — `base.py:11-46`
  - `TaxResult` (frozen): `amount_rappen`, `effective_bps`, `regime_id`, `tariff_version`, `breakdown`, `used_overrides`, `warnings` — `base.py:49-83`
  - `TaxRegime` (`@runtime_checkable Protocol`) — `base.py:86-235`. Methoden: `annual_wealth_tax(ctx)` `:145`, `dividend_tax(ctx, income)` `:154`, `interest_tax(ctx, income)` `:166`, `capital_gains_tax(ctx, gains, holding_years)` `:173`, `pension_lumpsum_tax(ctx, amount)` `:188`, `inheritance_tax(ctx, amount, relation)` `:200`, `validate_parameters(params)->tuple[str,...]` `:215`, `with_overrides(overrides)->TaxRegime` `:226`. Properties: `id`, `country_code`, `region_code`, `display_name`, `local_currency`, `supports_wealth_tax`, `supports_capital_gains_tax`, `supports_inheritance_tax`.
  - **WICHTIG: kein `TaxConfig` in base.py.** (Siehe Bug §2.3.)
- **Registry (Pattern-Matching)** — `services/tax/registry.py`
  - `register_regime(id_pattern)` Decorator `:26`; `resolve_regime_class(jid)` exact > glob > `*`-Fallback `:43`; `REGIME_REGISTRY` `:21`; `clear_registry()` TEST-only `:78`.
- **Regimes (Implementierungen)** — `services/tax/regimes/`
  - `GenericFlatRateRegime` (`@register_regime("*")`, frozen dataclass) — `generic.py:22`. Felder: `wealth_tax_bps_pa`, `dividend_tax_bps`, `interest_tax_bps`, `capital_gains_tax_bps`, `pension_lumpsum_tax_bps`, `inheritance_tax_bps_default`, `overrides` (`generic.py:44-51`). Rechenmethoden `generic.py:69-121`, `validate_parameters` `:125`, `with_overrides` (immutable via `replace`) `:142`, `_make_result` `:160`. **Konstruktor nimmt nur dataclass-Keyword-Felder, KEIN Positional-Arg.**
  - `CHTaxRegime(GenericFlatRateRegime)` (`@register_regime("CH")`, `("CH-*")`) — `ch.py:22-87`. Defaults: `wealth_tax_bps_pa=40`, `dividend_tax_bps=2800`, `capital_gains_tax_bps=0` (Privatvermögen!), `pension_lumpsum_tax_bps=600`. `for_canton(...)` Factory `:55`, Kanton-Mittelwerte `_CANTON_AVG_WEALTH_TAX_BPS` `:94`.
  - `DETaxRegime(GenericFlatRateRegime)` (`@register_regime("DE")`) — `de.py:21-40`. `wealth_tax=0`, `dividend=capital_gains=2637.5` (26.375 %).
- **Discovery (Entry-Points)** — `services/tax/discovery.py`. Group `5eyes.tax_regime` `:33`; `discover_external_regimes(skip_plugins, raise_on_error)` `:67`; `DiscoveryResult` `:38`.
- **Conformance-Contract** — `services/tax/conformance.py`. `ConformanceContract` `VERSION="1.0.0"` `:78/87`, `.run(regime)->ConformanceReport` `:92`. 10 Built-in-Requirements R001–R010 `:222-236` (R001-id, R002-country, R003-name, R004-currency, R005-wealth-nonneg, R006-capgains-result, R007-dividend-result, R008-overrides-immutable, R009-validate-tuple, R010-tariff-version[recommended]).
- **Overrides-Helper** — `services/tax/overrides.py`. `parse_overrides_json` `:17`, `apply_overrides(regime, json)` `:37`, `validate_all` `:49`.
- **Public-API** — `services/tax/sdk.py`. `SDK_PUBLIC_API` `:83`, `TAX_SDK_VERSION="1.0.0"` `:65`, `TAX_SDK_CONFORMANCE_CONTRACT_VERSION="1.0.0"` `:76`. Drift-Test: `tests/tax/test_sdk_public_api.py`.
- **Mandate-Felder** — `models/mandates.py`: `tax_jurisdiction` (String) `:47`, `tax_overrides_json` (String) `:50`, `retirement_year` `:25`. **Kein** opt-in-Tax-Flag, **kein** `valid_from_year`-Column (Engine liest es defensiv via getattr, default 2026).

### 2.2 Cashflow-Projektions-Pfad (Einhängepunkt für #39)

Innerhalb des Aggregator-Blocks in `services/portfolio_engine.py`:

1. Horizont: `projection_years = _simulation_horizon_years(...)` — `portfolio_engine.py:4403` (Def `:1879`).
2. Inflations-Pfad: `cf_inflation_series_bps = _inflation_path_series(cma, projection_years, start_year)` — `:4406` (Def `:2028`).
3. Basis-Serie: `cashflow_projection_series_rappen = net_cashflow_series(cashflows, projection_years, start_year=..., inflation_series_bps=..., fx_source=..., target_currency=...)` — `:4410`. `net_cashflow_series` Def in `services/cashflow_timeline.py:301` (liefert `list[int]`, `net_rappen` pro Jahr).
4. Inflows additiv: `inflow_projection_series_rappen` `:4420`, addiert `:4423-4427`.
5. **VORBILD #31 — Hypothek-Adjustment (additiv):** `:4428-4439`
   ```python
   _mortgage_interest_adj = mortgage_interest_adjustment_series(
       all_positions, projection_years, cashflow_totals["year"],
   )
   if any(_mortgage_interest_adj):
       cashflow_projection_series_rappen = [
           int(cf) + int(adj)
           for cf, adj in zip(cashflow_projection_series_rappen, _mortgage_interest_adj)
       ]
   ```
   `mortgage_interest_adjustment_series(positions, horizon_years, start_year) -> list[int]` Def in `services/wealth_cashflows.py:141` — pro Jahr ein additiver Rappen-Delta-Wert, **ändert NICHT die heutige Cashflow-Summe** (Jahr 0 = statischer Posten). Import: `portfolio_engine.py:46`.
6. Return-Dict: `"cashflow_projection_series_rappen": ...` — `:4470`. Diese Serie wird downstream von MC, Goal-Analysis, Reserve und **vom Optimizer** (`cashflow_series_rappen`, §2.3) konsumiert.

> **#39 hängt sich exakt zwischen Schritt 5 und 6 ein** (nach Mortgage, vor Return) — als weitere additive Serie `tax_adjustment_series`, opt-in.

### 2.3 Optimizer-Objective + Tax-Wiring (Einhängepunkt für #46)

- **Objective:** `_objective_from_array(context, w)` ruft `combined_objective_two_phase(liabilities, wealth, ...)` — `solver.py:353-369`. Eingang ist `wealth` = simulierte Pfade aus `_simulate_context_wealth` `:181`.
- **Tax wird BEREITS in der Simulation angewandt:** `simulate_wealth_paths(..., tax_regime=context.tax_regime, dividend_yield_bps_per_bucket=..., base_calendar_year=..., mandate_age_at_start=..., is_retired=...)` — `solver.py:182-194`. In `scenario_engine.py`:
  - Dividenden-Steuer-Drag pro Jahr `:503-515`
  - Vermögenssteuer pro Pfad (`_compute_per_path_wealth_tax_drag`, tax_mode median/binned/per_path) `:517-527` (Def `:268`).
- `OptimizerContext.tax_regime` Feld `solver.py:146`; `build_optimizer_context(..., tax_regime=None, ...)` `:216`; an Context durchgereicht `:344-349`.
- **Damit ist das Objective faktisch tax-aware, SOBALD `tax_regime` gesetzt ist** (es optimiert auf Nach-Steuer-Endvermögens-Verteilung). #46 = das Setzen zuverlässig + opt-in machen.

- **BUG — Wiring derzeit tot** (`portfolio_engine.py:5004-5030`):
  ```python
  from services.tax.base import TaxConfig                 # :5013  -> ImportError (TaxConfig existiert nicht in base.py)
  regime_cls = resolve_regime_class(jurisdiction)         # :5014  -> ok
  regime_instance = regime_cls(TaxConfig(jurisdiction_id=jurisdiction))  # :5016 -> TypeError (Regime ist frozen dataclass ohne Positional-Arg)
  ```
  Der ganze Block ist in `try/except Exception` `:5029` → **schluckt den Fehler still** und der Solver läuft **immer tax-naiv** trotz gesetztem `mandate.tax_jurisdiction`. `tax_kwargs` an `run_solver` `:5047`.
- **OPTIMIZER_MODE:** `_run_stochastic_optimizer_pass(..., optimizer_mode, ...)` `portfolio_engine.py:4924-4961`. Werte: `stochastic` (apply), `shadow_stochastic` (compute only), `iterative` (reserviert). Tax-Aktivierung ist **orthogonal** zu OPTIMIZER_MODE.

---

## 3. SOLL-Design

### 3.0 Neue Datei (die EINZIGE neue Datei)

`services/tax/cashflow_tax.py` — kapselt (a) die Cashflow-Tax-Serie (#39) und (b) den Regime-Resolver/Builder für Engine + Optimizer (#46-Wiring-Fix). Damit bleibt `portfolio_engine.py` minimal (nur additive Hooks), und der Resolver ist an EINER Stelle testbar.

### 3.1 (#39) `tax_adjustment_series` — additive Cashflow-Steuer (opt-in)

**Semantik (konservativ):** Pro Projektionsjahr `i` eine **negative** Rappen-Größe (Ausgabe), additiv auf die Netto-Cashflow-Serie — analog Mortgage. Bezieht zwei Komponenten:

1. **Vermögenssteuer** auf das projizierte Vermögen: `regime.annual_wealth_tax(ctx).amount_rappen`. Da die Cashflow-Serie selbst kein Pfad-Vermögen kennt, nutzt #39 eine **deterministische Wealth-Schätzung** = `advisory_wealth_rappen` konstant über den Horizont (KONSERVATIV: kein Verzehr-Discount → Steuer wird nicht zu niedrig angesetzt; OWNER-DECISION D3). Optional spätere Erweiterung: Wealth-Approximation via kumulierter Netto-Cashflow (out of scope, als Hook vorgesehen).
2. **Einkommenssteuer** auf wiederkehrendes steuerbares Einkommen: aus der **recurring income**-Komponente (`recurring_income_rappen`, vorhanden im Aggregator `portfolio_engine.py:4463`) als Bemessungsgrundlage → `regime.dividend_tax(ctx, taxable_income_rappen)` als **Proxy für den marginalen Einkommensteuersatz** (CH-Regime modelliert Einkommen via `dividend_tax_bps=2800` = ~28 % Grenzsatz; siehe `ch.py:34`). Default-Bemessung KONSERVATIV: nur explizit als steuerbar markierte Income-Cashflows; ohne Markierung → 0 (kein Phantom-Einkommen). (OWNER-DECISION D4.)

**Signatur** (in `services/tax/cashflow_tax.py`):
```python
def tax_adjustment_series(
    regime: "TaxRegime",
    *,
    horizon_years: int,
    start_calendar_year: int,
    wealth_rappen: int,                  # deterministische Wealth-Schätzung (konservativ: konstant)
    taxable_income_series_rappen: list[int] | None = None,  # pro Jahr; None -> 0
    mandate_age_at_start: int | None = None,
    retired_from_year_index: int | None = None,
    include_wealth_tax: bool = True,
    include_income_tax: bool = True,
) -> list[int]:
    """Liefert pro Jahr die additive Steuer-AUSGABE in Rappen (<= 0, Vorzeichen
    wie Expense im Netto-Cashflow). Analog mortgage_interest_adjustment_series:
    rein additiv, ändert die heutige Cashflow-Summe NICHT (separate Serie).

    Jahr i:
        ctx = TaxContext(year_index=i, calendar_year=start+i,
                         wealth_rappen=wealth_rappen, age=age_i,
                         is_retired=(retired_from_year_index is not None and i>=...),
                         currency_code=regime.local_currency)
        wt = regime.annual_wealth_tax(ctx).amount_rappen      if include_wealth_tax and regime.supports_wealth_tax else 0
        it = regime.dividend_tax(ctx, income_i).amount_rappen if include_income_tax else 0
        adj[i] = -(round(wt) + round(it))
    """
```

**Hook in `portfolio_engine.py`** (additiv, **zwischen** Mortgage-Block `:4439` und Return `:4448`):
```python
# 2026-06-21 (#39): Steuer (Vermögens-/Einkommenssteuer) als wiederkehrende
# Ausgabe in die Projektion. Opt-in via mandate.tax_in_cashflow == 1. Additiv,
# heutige Cashflow-Summe unberührt (analog #31 Mortgage).
_tax_adj = tax_adjustment_series_for_mandate(
    mandate,
    horizon_years=projection_years,
    start_calendar_year=cashflow_totals["year"],
    advisory_wealth_rappen=advisory_wealth_rappen,
    recurring_income_rappen=cashflow_totals["recurring_income_rappen"],
)  # -> list[int], leer/zeros wenn opt-out oder kein Regime
if any(_tax_adj):
    cashflow_projection_series_rappen = [
        int(cf) + int(adj)
        for cf, adj in zip(cashflow_projection_series_rappen, _tax_adj)
    ]
```
`tax_adjustment_series_for_mandate(...)` lebt ebenfalls in `cashflow_tax.py`: liest `mandate.tax_in_cashflow` (neues opt-in Flag, default 0 → gibt `[0]*horizon` zurück), resolved das Regime (§3.3), baut `taxable_income_series` (konstant `recurring_income_rappen`, optional inflationiert über denselben `cf_inflation_series_bps`), ruft `tax_adjustment_series`. **Komplett in try/except → bei jedem Fehler `[0]*horizon`** (Cashflow darf nie crashen).

Return-Dict zusätzlich (Audit/FE, neben `:4470`):
```python
"tax_adjustment_series_rappen": _tax_adj,
"tax_in_cashflow_active": bool(any(_tax_adj)),
```

### 3.2 (#46) Tax-aware Objective — Wiring-Fix + opt-in

**Fix des Bugs (`portfolio_engine.py:5009-5030`):** Block ersetzen durch Aufruf des zentralen Resolvers (§3.3). Konkret:
```python
# Sprint U-P2 C9 / #46: tax-aware Solver. Opt-in via mandate.tax_aware_objective.
tax_kwargs: dict = {}
regime_instance = build_regime_for_mandate(mandate)   # None wenn opt-out/kein jurisdiction/Fehler
if regime_instance is not None:
    tax_kwargs["tax_regime"] = regime_instance
    current_year = int(getattr(mandate, "valid_from_year", 0) or 0) or 2026
    tax_kwargs["base_calendar_year"] = current_year
    cby = int(getattr(mandate, "client_birth_year", 0) or 0)
    if cby:
        tax_kwargs["mandate_age_at_start"] = max(0, current_year - cby)
    rty = int(getattr(mandate, "retirement_year", 0) or 0)
    if rty and current_year >= rty:
        tax_kwargs["is_retired"] = True
```
Damit verschwindet `TaxConfig` (existiert nicht) und der frozen-dataclass-Konstruktor wird korrekt keyword-frei aufgerufen. `tax_kwargs` weiterhin an `run_solver(...)` `:5047`.

**Opt-in:** Neues Mandate-Flag `tax_aware_objective` (default 0). `build_regime_for_mandate` gibt `None` zurück wenn Flag ≠ 1 → Solver läuft tax-naiv (Backwards-Compat 1:1). Kein Verhaltenswechsel ohne explizites Opt-in.

> Hinweis: Die per-path Tax-Maschinerie in `scenario_engine.py:477-527` bleibt **unverändert** — sie funktioniert bereits korrekt. #46 ist reines Wiring + Gate.

**`dividend_yield_bps_per_bucket`** (optional, KONSERVATIV default off): wenn nicht geliefert, greift nur Vermögenssteuer-Drag — das ist die konservative Untergrenze. Dividenden-Drag erst aktiv wenn der Aufrufer ein Yield-Array liefert (`scenario_engine.py:465`). Out of scope, als Hook dokumentiert.

### 3.3 Zentraler Resolver (`cashflow_tax.py`)

```python
def build_regime_for_mandate(
    mandate,
    *,
    require_opt_in_flag: str | None = "tax_aware_objective",
) -> "TaxRegime | None":
    """Resolved + konfiguriert das TaxRegime für ein Mandat.

    - jurisdiction = str(getattr(mandate, "tax_jurisdiction", "")).strip(); leer -> None
    - require_opt_in_flag gesetzt und Flag != 1 -> None
    - regime_cls = resolve_regime_class(jurisdiction)           # registry.py:43
    - regime = regime_cls()                                     # KEYWORD-frei (frozen dc), KEIN TaxConfig
    - if getattr(mandate, "tax_overrides_json", None):
          regime = apply_overrides(regime, mandate.tax_overrides_json)  # overrides.py:37
    - jeder Fehler -> None (defensiv geloggt)
    """
```
`tax_adjustment_series_for_mandate(...)` (§3.1) nutzt denselben Resolver mit `require_opt_in_flag="tax_in_cashflow"`.

Beide opt-in-Flags sind unabhängig: Cashflow-Steuer (#39) und Objective-Steuer (#46) können getrennt aktiviert werden.

### 3.4 (#40) Plugin-Conformance-Contract-Gerüst (KEINE Länder-Logik)

Das Contract-Gerüst **existiert vollständig** (`conformance.py`, R001–R010). #40 = es als **kanonischen Aufnahme-Vertrag** dokumentieren + ein **Stub-Skelett-Template** liefern, das neue Länder (FR/US/IT/AT) ausfüllen. **Spezifiziert wird NUR das Skelett**, nicht die Tarife.

**Conformance-Pflicht für ein neues Länder-Plugin** (MUSS, aus `conformance.py:222-236`):

| Req | Pflicht |
|-----|---------|
| R001 | `id` nicht-leerer String, Format `<COUNTRY>[-<REGION>]` |
| R002 | `country_code` ISO 3166-1 alpha-2 |
| R003 | `display_name` gesetzt |
| R004 | `local_currency` ISO 4217 |
| R005 | `annual_wealth_tax(ctx)` → `TaxResult`, `amount_rappen >= 0` |
| R006 | `capital_gains_tax(ctx, gains, holding_years)` → `TaxResult >= 0` |
| R007 | `dividend_tax(ctx, income)` → `TaxResult >= 0` |
| R008 | `with_overrides` immutable (mutiert Original nicht) |
| R009 | `validate_parameters` → `tuple[str,...]` |
| R010 (SOLL) | `TaxResult.tariff_version` gesetzt |

**Empfohlenes Implementierungs-Muster** (wie CH/DE): von `GenericFlatRateRegime` erben, nur die Pauschal-bps + Metadaten als dataclass-Felder überschreiben. Damit sind R005–R010 automatisch erfüllt.

**Skelett-Template** (NICHT als Code-Datei in diesem Branch erstellen — als Doku-Block; konkrete Länder kommen in eigenen Branches):
```python
@register_regime("FR")              # bzw. "US", "US-*", "IT", "AT"
@dataclass(frozen=True)
class FRTaxRegime(GenericFlatRateRegime):
    id: str = "FR"
    country_code: str = "FR"
    display_name: str = "France"
    local_currency: str = "EUR"
    tariff_version: str = "FR-LIGHT-v1-2026"
    wealth_tax_bps_pa: float = 0.0        # FR: nur IFI (Immobilien > 1.3 Mio) — Default 0, Override
    dividend_tax_bps: float = 3000.0      # PFU "Flat Tax" 30% — als Default-Pauschale
    capital_gains_tax_bps: float = 3000.0
    pension_lumpsum_tax_bps: float = 0.0
```
**Conformance-Check als CI-Gate** (3rd-Party + inhouse): `ConformanceContract().run(FRTaxRegime()).passed` (`conformance.py:92`). Distribution extern via Entry-Point-Group `5eyes.tax_regime` (`discovery.py:33`).

**SDK-Versionierung:** Keine neuen Pflicht-Methoden → `TAX_SDK_VERSION` bleibt `1.0.0` (`sdk.py:65`). Neue Länder sind reine Registry-Additionen, kein Breaking-Change.

---

## 4. Konkrete Funktionen / Signaturen (Zusammenfassung)

Neu in `services/tax/cashflow_tax.py`:
- `build_regime_for_mandate(mandate, *, require_opt_in_flag="tax_aware_objective") -> TaxRegime | None`
- `tax_adjustment_series(regime, *, horizon_years, start_calendar_year, wealth_rappen, taxable_income_series_rappen=None, mandate_age_at_start=None, retired_from_year_index=None, include_wealth_tax=True, include_income_tax=True) -> list[int]`
- `tax_adjustment_series_for_mandate(mandate, *, horizon_years, start_calendar_year, advisory_wealth_rappen, recurring_income_rappen) -> list[int]`

Additive Hooks (kein Umbau bestehender Logik):
- `portfolio_engine.py` ~`:4439-4448`: Cashflow-Hook (#39) + 2 Return-Keys.
- `portfolio_engine.py` `:5009-5030`: Wiring-Block durch `build_regime_for_mandate` ersetzen (#46-Fix). `TaxConfig`-Referenzen `:5013/:5016` entfernen.

Mandate-Schema (additiv, default 0):
- `tax_in_cashflow` (Integer, #39 opt-in)
- `tax_aware_objective` (Integer, #46 opt-in)
- `models/mandates.py` + `schemas/mandates.py`. (Migration: nullable/Default 0 → Backwards-Compat. Bestehende `5eyes_schema_*.sql` NICHT editieren — neue Migration-Datei separat, gehört NICHT in diesen Branch wenn DB-Migrations gesondert laufen; sonst additive `ALTER TABLE` mit Default 0.)

---

## 5. Test-Plan

Neue Datei `tests/tax/test_cashflow_tax.py`:
- **#39 additive Serie:**
  - `tax_adjustment_series` mit `CHTaxRegime()`, wealth=1 Mio CHF, `include_income_tax=False` → jedes Jahr `-(1e6*40/10000)` Rappen (= -4'000 CHF); Länge == horizon.
  - `include_wealth_tax=False`, income=100k → `dividend_tax`-Betrag negativ, Vorzeichen Expense.
  - DE-Regime (`supports_wealth_tax=False`) + `include_wealth_tax=True` → Vermögenssteuer-Anteil 0 (kein Crash).
  - `horizon_years=0` → `[]`.
  - **Additivität / Summen-Invarianz:** Engine-Serie OHNE Hook == Serie MIT Hook wenn `tax_in_cashflow=0` (default off).
- **#39 Engine-Integration** (analog `tests/test_mortgage_interest_schedule.py` + `test_sprint_b_batch*`):
  - Mandat mit `tax_in_cashflow=1`, CH-jurisdiction → `tax_adjustment_series_rappen` nicht-leer, `cashflow_projection_series_rappen` um Steuer reduziert; mit Flag=0 → identisch zur Baseline (Regression).
- **#46 Wiring-Fix:**
  - `build_regime_for_mandate(mandate)` mit `tax_aware_objective=1` + `tax_jurisdiction="CH"` → `CHTaxRegime`-Instanz (KEIN `TaxConfig`-ImportError). Regressions-Anker für den bisherigen `:5016`-Bug.
  - Flag=0 → `None` (tax-naiv).
  - `tax_overrides_json='{"wealth_tax_bps_pa":80}'` → Regime hat 80 (via `apply_overrides`).
  - **Objective-Effekt:** zwei `OptimizerContext` (mit/ohne `tax_regime`); mit CH-Vermögenssteuer → niedrigere Nach-Steuer-Terminal-Wealth-Quantile in `evaluate_weights` (`solver.py:372`). (Vorhandener Vorlage-Test: `tests/test_per_path_tax_integration.py`.)
- **#40 Conformance:**
  - Skelett-Template-Regime (im Test definiert, z.B. ein Inline-`FRTaxRegime`) → `ConformanceContract().run(...).passed is True` (alle R001–R009). Bestätigt, dass das Vererbungs-Muster den Contract erfüllt. (Vorlage: `tests/tax/test_conformance.py`.)
- **SDK-Stabilität:** `tests/tax/test_sdk_public_api.py` bleibt grün (kein API-Change).

Edge-Case-Tests siehe §6.

---

## 6. Edge-Cases

| Fall | Verhalten |
|------|-----------|
| **Kein Plugin / leeres `tax_jurisdiction`** | `resolve_regime_class` fällt auf `GenericFlatRateRegime` (`*`) `registry.py:55-70`; dessen Defaults = alle 0 → Steuer-Serie = `[0]*horizon`, Objective tax-neutral. Kein Crash. |
| **`tax_jurisdiction` gesetzt, opt-in Flag 0** | Resolver gibt `None` → Cashflow-Hook & Objective bleiben Baseline. (Beide Features default off.) |
| **Gemischte Währungen** | Regime rechnet in `local_currency` (`base.py:125`); `wealth_rappen`/income kommen aus dem Aggregator bereits in `target_currency` (CHF) konvertiert (`net_cashflow_series(..., fx_source, target_currency)` `cashflow_timeline.py:307`). KONSERVATIV: #39 nutzt die CHF-konvertierten Beträge und das Mandats-Regime; **keine** zusätzliche FX-Umrechnung der Steuer (OWNER-DECISION D5). EUR/USD-Regime auf CHF-Basis = akzeptierte Näherung; Warnung in `breakdown`/Audit wenn `regime.local_currency != target_currency`. |
| **Negatives Vermögen** | `GenericFlatRateRegime.annual_wealth_tax` clamped `max(wealth,0)` `generic.py:70` → keine negative Steuer. |
| **`with_overrides` mit unbekannten Keys** | ignoriert (`generic.py:148-156`); Tippfehler-tolerant. |
| **Malformed `tax_overrides_json`** | `parse_overrides_json` → `{}` `overrides.py:22-34`; Regime unverändert. |
| **Discovery: kaputtes externes Plugin** | `discover_external_regimes` schluckt Load-Fehler, Boot überlebt `discovery.py:113`. |
| **Horizont 0 / leere Cashflows** | Serie `[]`; `if any(...)`-Guard verhindert Mutation (analog Mortgage `:4435`). |
| **Doppelte Aktivierung Mortgage + Tax** | beide Serien additiv & unabhängig → addieren sich korrekt; keine Doppelzählung (Steuer ≠ Hypothekarzins). |

---

## 7. OWNER-DECISIONs

- **D1 (opt-in default OFF):** `tax_in_cashflow` und `tax_aware_objective` default 0. Kein bestehender Mandant ändert sein Ergebnis ohne explizites Setzen. Bestätigen?
- **D2 (zwei getrennte Flags vs. ein gemeinsames):** Vorschlag zwei unabhängige Flags (Cashflow-Anzeige ≠ Optimizer-Objective). Alternative ein `tax_aware`-Master-Flag. Empfehlung getrennt.
- **D3 (Wealth-Schätzung für #39):** KONSERVATIV = `advisory_wealth_rappen` konstant über Horizont (kein Verzehr-Discount → Steuer nicht zu niedrig). Alternative (genauer, niedriger) kumulierte Netto-Cashflow-Approximation. Empfehlung konstant (konservativ), Approximation als späterer Hook.
- **D4 (Einkommensteuer-Bemessung):** KONSERVATIV-eng = nur explizit als steuerbar markierte recurring-Income-Cashflows; ohne Markierung 0 (kein Phantom-Einkommen). Alternative gesamte `recurring_income_rappen` als steuerbar (höhere Steuer, aber unrealistisch für AHV/steuerfreie Posten). Empfehlung enge Bemessung. → Klärung mit Owner welche Income-Typen steuerbar.
- **D5 (Multi-Currency):** Steuer auf CHF-konvertierten Beträgen + Mandats-Regime, keine separate FX-Steuer-Umrechnung; Audit-Warnung bei `local_currency != target_currency`. Bestätigen?
- **D6 (CH-Steuersatz-Annahmen):** CH-Defaults bleiben Pauschal-Mittelwerte (`wealth=40bps`, `income≈2800bps`), Berater override pro Mandant via `tax_overrides_json`. Bei Unsicherheit den **höheren** Satz nehmen (konservativ, Memory-Direktive). Bestätigen?
- **D7 (#40 Scope):** Nur Contract-Gerüst + Skelett-Template in dieser Spec; FR/US/IT/AT-Tarife in separaten Branches je Land. Bestätigt?

---

## 8. Definition of Done

- [ ] `services/tax/cashflow_tax.py` mit 3 Funktionen (§4), voll typisiert, defensiv (nie crashen).
- [ ] `portfolio_engine.py`: #39-Hook additiv eingehängt + #46-`TaxConfig`-Bug entfernt, beide opt-in.
- [ ] Mandate-Flags `tax_in_cashflow`, `tax_aware_objective` (default 0) + Schema.
- [ ] `tests/tax/test_cashflow_tax.py` grün (§5), bestehende Suite grün (Regression).
- [ ] #40 Contract + Skelett dokumentiert; `TAX_SDK_VERSION` unverändert `1.0.0`.
- [ ] Keine bestehende Datei außer den genannten additiven Hooks geändert.
