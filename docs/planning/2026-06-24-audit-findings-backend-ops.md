# Audit-Findings 2026-06-24 — Backend-Engine + Ops/Security/PDF/Electron

Aus zwei Multi-Agent-Audits (18 + 12 Agenten, jeder Befund adversarial gegen den Code verifiziert)
am 2026-06-23/24. NOCH NICHT GEFIXT — priorisierter Backlog. Volle Roh-Outputs:
`tasks/w2ag4bcgn.output` (Backend-Engine), `tasks/wrqjme1ct.output` (Ops/Security).

> Bewusst nicht über die Mitternacht-Deadline + in Codex' aktiv-dirty Dateien gepatcht.
> **SEC-1 zuerst** (Tenant-Isolation) — ggf. schon von Codex' RLS-PR #299 abgedeckt: prüfen.

> ## RE-VERIFIKATION 2026-07-23 (Branch `fix/audit-2026-06-24-reverification`)
>
> Systematische Re-Verifikation ALLER Findings gegen den aktuellen Code-Stand.
> Status pro Finding (Kurzform, Details/Fundstellen siehe Bulletpoints unten):
>
> **ERLEDIGT (bereits gefixt, Doku war veraltet):** CF-1, AR-1, OPT-1 (=MC-1),
> SEC-1, SCHEMA-01, SCHEMA-02, SCHEMA-03, SCHEMA-04, SCHEMA-05, SCHEMA-06,
> AR-2, AR-3, MC-2, RT-1 (bewusst NICHT wie vorgeschlagen gefixt — konservativer
> Default ist die intendierte Safety-Net-Semantik, siehe risk_scoring.py:198-204),
> rls-1, AB-1, AB-2, AB-3 (durch AB-1/AB-2 abgeloest), AB-4, MD-02, MD-03, MD-04,
> MD-06, AUTH-01, AUTH-02, AUTH-04, AUTH-05, AUTH-06, EM-1, EM-2, EM-4, EM-5,
> EM-6, EM-7.
>
> **HEUTE GEFIXT (additiv, getestet, einzeln committet):**
> - CF-2 → `routers/clients.py` cashflow_summary (fx_source/target_currency
>   analog zur bereits gefixten cashflow_projection). Test: `tests/test_cf2_cashflow_summary_fx.py`.
> - SEC-2 → `routers/auth.py` (`_assert_user_visible_to`, `update_user`):
>   tenant-loser Admin ist im effektiv strikten/Multi-Tenant-Modus jetzt
>   restricted statt global sichtbar; Tier1-BC unveraendert. Test: `tests/test_sec2_tenantless_admin_visibility.py`.
> - rls-2 → `routers/protocol_bausteine.py` (`list_bausteine`,
>   `replace_mandate_selections`): Tenant-Filter auch fuer role=='admin'.
>   Test: `tests/test_rls2_baustein_tenant_isolation.py`.
> - rls-3 → `schemas/wealth.py` + `routers/wealth.py`: Phase-0-Gate
>   (`enforce_data_classification`) fuer Wealth-Position/-Inflow nachgezogen.
>   Test: `tests/test_data_classification_gate.py` (2 neue Tests).
> - MD-05 → `price_updater.py`: exponentielles Retry-Backoff + Jitter statt
>   fixer Sleep-Dauer (`_retry_backoff_seconds`). Test: `tests/test_price_updater_md05_retry_backoff.py`.
>   (Inter-Symbol-Throttle im Stooq-Batch-Loop bleibt OFFEN, siehe MD-05 unten.)
> - AB-5 → `services/maintenance.py` `build_compliance_status()`: Warnung +
>   `backups_colocated_with_db`-Flag wenn Backup-Verzeichnis == DB-Verzeichnis.
>   Test: `tests/test_ab5_backup_colocation_warning.py`.
> - AB-6 → `services/maintenance.py` `run_integrity_check()`: `PRAGMA
>   integrity_check(50)` statt unbeschraenkt. Test: `tests/test_maintenance.py`.
>
> **OFFEN, RISIKOREICH (bewusst NICHT gefixt — aendert reale Empfehlungs-/
> Berechnungsergebnisse, ausserhalb des sicheren additiven Scopes):**
> - **RES-1** — WIDERSPRICHT einer frueheren Session-Aussage ("bereits gefixt"):
>   `_compute_reserve_for_inputs` (portfolio_engine.py, aktuell ~Z.4664-4680)
>   verwendet WEITERHIN `max(0, -sum(near_term_cashflow_series) - max(0,
>   near_term_inflows))` statt jahresweiser kumulativer Running-Balance — der
>   im Audit beschriebene Bug ist am aktuellen Code-Stand VERIFIZIERT NOCH
>   OFFEN. Nicht gefixt, weil das direkt reserve_needed_rappen aendert (Kern
>   der SAA-Empfehlung).
> - **RES-2** — external_reserve_rappen/reserve_needed_rappen weiterhin
>   ungedeckelt gg. advisory_wealth_rappen (portfolio_engine.py `_compute_reserve_for_inputs`).
>   Aendert investable_advisory_wealth_rappen -> Kern-Empfehlungslogik.
> - **goals-1** — `_monte_carlo_goal_summary` (portfolio_engine.py ~Z.3036-3200)
>   ruft `_goal_pension_state_funded` NICHT auf (im Gegensatz zum
>   deterministischen Pfad und zu `_compute_reserve_for_inputs`), AHV-Goals
>   werden im MC-Pfad weiterhin wie normale Ausgaben-Goals bewertet.
>   Aendert Goal-Achievability-Scores, die im Bericht/Frontend angezeigt werden.
> - **OPT-2** — `bands_from_house_matrix_row` (services/optimizer/constraints.py)
>   nutzt weiterhin nur `equity_min_bps`, NICHT das staerkere `equity_minimum_bps`
>   (das der deterministische Pfad in portfolio_engine.py:4567 einrechnet) —
>   Divergenz zwischen Optimizer-Bounds und deterministischem Pfad bleibt.
>   Aendert die Solver-Loesungsmenge (reale Allokationsempfehlung).
> - **RT-2** — `services/tax/regimes/generic.py`: negative Overrides (z.B.
>   `wealth_tax_bps_pa=-500`) erzeugen weiterhin negative "Steuer"-Betraege
>   (Rate wird nicht bei 0 geflort). Explizit ausserhalb des Scopes (Tax-
>   Berechnungsformeln sind laut Auftrag tabu).
> - **MD-01** — `price_updater.py`: `symbol_points`-Tupel tragen weiterhin
>   KEINE Provider-Currency (3-Tupel `(date, rappen, source)`), `PricePoint.currency`
>   bleibt `product.currency or 'CHF'` in `fetch_latest_prices_batch` (Batch-Pfad).
>   `fetch_latest_price` (Single-Pfad) beruecksichtigt bereits `market_profile.get('currency')`
>   — Inkonsistenz zwischen Single- und Batch-Pfad bleibt. NICHT gefixt: mehrstelliger
>   Tuple-Shape-Refactor ueber 4 Provider-Fetch-Funktionen, reales Korrektheitsrisiko
>   fuer Preisdaten, zu gross fuer einen additiven Einzel-Commit in dieser Session.
> - **AUTH-03** — GEPRUEFT UND BEWUSST NICHT GEFIXT (Versuch gemacht + wieder
>   verworfen): `_login_guard_key` (routers/auth.py) vertraut X-Forwarded-For
>   weiterhin unbedingt (spoofbar). Ein Fix (Default auf `request.client.host`,
>   XFF nur bei explizitem `trusted_proxy_count`) wurde implementiert, brach
>   aber `tests/test_auth05_bootstrap_admin_rate_limit.py::test_bootstrap_admin_lockout_is_per_source_not_global`
>   (dieser Test verlangt aktuell explizit XFF-basierte Per-Source-Isolation)
>   und wurde deshalb verworfen. Ein echter Fix braucht eine bewusste
>   Entscheidung zur Deployment-Topologie (Reverse-Proxy ja/nein) und
>   Anpassung des AUTH-05-Tests — nicht mehr "sicher additiv".
>
> **Tests:** alle 54 neuen/betroffenen Tests gruen; siehe Commits auf diesem
> Branch fuer Details. Volle Suite lief zum Zeitpunkt der Uebergabe im
> Hintergrund (Ergebnis ggf. noch nachzutragen).

## Backend-Engine (w2ag4bcgn)

### HIGH (6)

- **CF-1** [cashflow/consistency] `routers/clients.py:439 vs services/portfolio_engine.py:4406-4417,6957-6965`
  - VERIFIED. cashflow_projection ruft `totals_for_year(cashflows, yr)` (clients.py:439) ohne inflation_series_bps und ohne start_year auf. _compound_inflation_factor (cashflow_timeline.py:176-177) gibt damit 1.0 zurueck -> alle is_inflation_linked Cashflows (AHV/Lohn/Miete) bleiben ueber den gesamten H
  - **Fix:** Im Router den CMA-Inflationspfad analog zur Engine laden und durchreichen: cma laden, infl = _inflation_path_series(cma, horizon, start_year), dann totals_for_year(cashflows, yr, inflation_series_bps=
- **AR-1** [report-builders/consistency] `services/advisory_report.py:1494-1510 (_check_zielkompatibilitaet)`
  - VERIFIED. Line 1498 classifies a hard/red-flag goal only when str(r.get('hardness','')).lower() in ('hart','hard'). The data source persisted into TargetAllocation.goal_achievability_json is the optimizer achievability list built in services/optimizer/objective.py:255-263, which writes 'hardness': _
  - **Fix:** Match the engine's canonical key set. Replace the membership test with: _hk = str(r.get('hardness','')).strip().lower(); ... and _hk in ('hart','hard','primaer','primär'). Best: import/share a single
- **OPT-1** [optimizer/correctness] `services/optimizer/objective.py:466-471 (combined_objective_two_phase)`
  - VERIFIED. combined_objective_two_phase forwards weights to shortfall_objective (L460-465, weights=weights) and volatility_objective (L472, weights=weights), but calls chance_constraint_penalty at L466-471 with positional args only and NO weights= kwarg. chance_constraint_penalty(L195-264) computes P
  - **Fix:** Forward weights into the penalty: `chance, _achievability = chance_constraint_penalty(wealth_paths, liability_list, int(initial_wealth_rappen), lambda_chance=lambda_chance, weights=weights)`. The keyw
- **SEC-1** [routers-security/security] `routers/clients.py:512-522`
  - VERIFIED. create_client_login constructs User(role="client", ...) with NO tenant_id kwarg (clients.py:512-522). The User.tenant_id column is nullable (models/users.py:14: tenant_id = Column(String, ForeignKey("tenants.id"))), so the client-user lands with tenant_id=NULL. Every other user-creation pa
  - **Fix:** Inherit the tenant on the created client User, mirroring create_mandate: tenant_id=getattr(client, 'tenant_id', None) or getattr(current_user, 'tenant_id', None), so a client-login User is never NULL-
- **SCHEMA-03** [schemas-validators/validation] `schemas/allocation.py:279-318`
  - VERIFIED and unconditional. CapitalMarketAssumptionCreate declares every return/vol/premium input as bare Optional[int] with no Field constraints (e.g. equity_intl_vol_bps:289-300, bonds_chf_ig_return_bps:283, liquidity_vol_bps:300, real_estate_risk_premium_bps:317). A negative volatility (e.g. equi
  - **Fix:** Add Field(ge=0) to all *_vol_bps fields (volatility cannot be negative); add sane upper bounds (e.g. le=100000) to return/vol/premium fields; add a model_validator asserting valid_until is None or >=
- **RT-2** [risk-tax/validation] `services/tax/overrides.py:37-46 and services/tax/regimes/generic.py:142-156`
  - VERIFIED. The live compute path portfolio_engine._build_tax_kwargs (line 4955-4957) calls apply_overrides(regime_instance, tax_overrides_json), which (overrides.py:43-46) parses the mandate JSON and calls regime.with_overrides(overrides) WITHOUT any validation. with_overrides (generic.py:153) applie
  - **Fix:** Floor each rate at 0.0 (max(0.0, bps)) inside the amount computations in generic.py (annual_wealth_tax/dividend_tax/interest_tax/capital_gains_tax/pension_lumpsum_tax/inheritance_tax) so a bad overrid

### MED (16)

- **RES-1** [reserve/correctness] `services/portfolio_engine.py:4586-4598`
  - VERIFIZIERT. near_term_shortfall_rappen = max(0, -sum(near_term_cashflow_series) - max(0, near_term_inflows)) (Z.4598). near_term_cashflow_series ist die recurring-Serie der ersten 3 Jahre (Z.4586, slice [:3]), near_term_inflows die Summe ALLER einmaligen Inflows der Jahre 0-2 (Z.4594-4597, slice [:
  - **Fix:** Jahresweise kumulative Running-Balance statt Summen-Differenz: cum=0; worst=0; for i in range(3): cum += series[i] + inflow[i]; worst=min(worst,cum); near_term_shortfall=max(0,-worst). Dazu inflow als
- **RES-2** [reserve/validation] `services/portfolio_engine.py:4578-4584, 4683, 4884-4885`
  - VERIFIZIERT (mit Korrektur am Einheiten-Detail). manual_reserve (limits.minReserve, Z.4579) und liquidity_target (assetClasses.liquidityReserveTarget, Z.4580) werden via _parse_rappen geparst und ungeprueft als reserve_candidates uebernommen (Z.4581-4584). Bei reserve_needed > saa_reserve wird exter
  - **Fix:** external_reserve_rappen = min(external_reserve_rappen, advisory_wealth_rappen) deckeln und bei reserve_needed_rappen > advisory_wealth_rappen ein Warn-Reasoning erzeugen; zusaetzlich manual_reserve/li
- **MC-1** [montecarlo/consistency] `services/optimizer/objective.py:466-471 (combined_objective_two_phase); called from solver.py:363-369 (_objective_from_array) and solver.py:386-392 (evaluate_weights) with weights=context.scenario_weights`
  - VERIFIED. In combined_objective_two_phase the inner chance_constraint_penalty call (objective.py:466-471) omits weights=, while shortfall_objective (line 464) and volatility_objective (line 472) both receive weights=weights. chance_constraint_penalty supports weights precisely to avoid a biased P(su
  - **Fix:** Pass weights into the inner call: chance, _ = chance_constraint_penalty(wealth_paths, liability_list, int(initial_wealth_rappen), lambda_chance=lambda_chance, weights=weights) at objective.py:466-471.
- **MC-2** [montecarlo/correctness] `services/optimizer/importance_sampling.py:65 (DEFAULT_TAIL_SHIFT_VECTOR), :203-205 (build_shift_vector default), and docstrings :42-48,:62-66,:182-185; vs scenario_engine.py:42 (BUCKET_ORDER); wired via solver.py:268-279`
  - VERIFIED. scenario_engine.py:42 defines BUCKET_ORDER=('equities'=0,'bonds'=1,'real_estate'=2,'alternatives'=3,'liquidity'=4). The IS default DEFAULT_TAIL_SHIFT_VECTOR=[0,0,-0.5,-0.5,0] and build_shift_vector default target_indices=[2,3] (importance_sampling.py:65,205) shift indices 2 and 3 = real_es
  - **Fix:** Drive target_indices by bucket name: target_indices=[BUCKET_ORDER.index('equities')] passed from solver.py:269, and fix DEFAULT_TAIL_SHIFT_VECTOR to [-0.5,0,0,0,0] plus the docstrings to the real ('eq
- **goals-1** [goals/consistency] `services/portfolio_engine.py:2616-2618, 2781-2796, 2958-3070, 3526-3531`
  - VERIFIED. State-funded pension (AHV) goals are only honored as '100% gedeckt' inconsistently across the three scoring paths. (a) _goal_reserve_for_goal returns the full target for state-funded goals (line 2616-2617). (b) In deterministic _build_goal_analysis the years<=3 branch sets available=_goal_
  - **Fix:** Centralize the state-funded rule. In _monte_carlo_goal_summary add, before the goal_type dispatch (~line 2982): if _goal_pension_state_funded(goal): return a fully-funded summary (score=100, success_r
- **CF-2** [cashflow/correctness] `routers/clients.py:283,298-300 (cashflow_summary) und :439 (projection); services/cashflow_timeline.py:207-209`
  - VERIFIED. cashflow_summary (clients.py:283) und cashflow_projection (clients.py:439) rufen totals_for_year ohne fx_source auf (Default None). _convert_cf_amount_to_target_currency (cashflow_timeline.py:207-209) liefert dann bei fx_source is None den Rohbetrag unveraendert zurueck (Backwards-Compat-P
  - **Fix:** Auch in den Routern FXRateSource.from_db(db) erzeugen und an totals_for_year(..., fx_source=fx, target_currency='CHF') uebergeben (analog Engine 4400-4401). Falls Multi-Currency im Cashflow-Erfassungs
- **AR-2** [report-builders/correctness] `services/advisory_report.py:667-680 (_build_key_metrics)`
  - VERIFIED. Even when a TargetAllocation exists (ta is not None, line 667), zielerreichung_bps (672), exp_vol_bps (676), exp_return_bps (677), max_drawdown_bps (678) and var_95_bps (679) are hardcoded to None; only risky_fraction_bps is populated. Inline comments admit this is a stub deferred to 'U-P2
  - **Fix:** Wire zielerreichung_bps to the already-computed goal_achievement_score_bps (pass it in or recompute via the shared helper) so the two sections agree. Populate exp_return/exp_vol/max_drawdown/var_95 fr
- **AR-3** [report-builders/correctness] `services/advisory_report.py:2657-2670 (_bucket_key_from_asset_class)`
  - VERIFIED. Line 2670: return aliases.get(raw, 'alternatives'). raw is (asset_class or '').strip().lower() (2659), so empty/whitespace-only and any mistyped/localized/unmapped asset_class is routed into the Alternatives bucket. This mis-files positions in Sektion 5 and inflates the equity-vs-other and
  - **Fix:** Add an explicit 'unknown'/'sonstige' bucket (or return None and exclude from the 5-bucket totals), or surface a data-quality warning when raw is non-empty and unmapped. Empty/whitespace asset_class mu
- **OPT-2** [optimizer/consistency] `services/optimizer/constraints.py:88-104 (bands_from_house_matrix_row) vs services/portfolio_engine.py:4489,4550`
  - VERIFIED. bands_from_house_matrix_row derives the equities lower band only from equity_min_bps (constraints.py L99 equities=_band("equity_min_bps","equity_max_bps")). The deterministic House-Matrix path enforces a stronger floor: portfolio_engine L4489 minimums["equities"]=max(int(house_matrix.equit
  - **Fix:** In bands_from_house_matrix_row, lift the equities lower bound: `eq_floor = max(int(getattr(row,'equity_min_bps',0) or 0), int(getattr(row,'equity_minimum_bps',0) or 0)); equities=(eq_floor/10000.0, eq
- **SEC-2** [routers-security/security] `routers/auth.py:629-642 (_assert_user_visible_to) and 568-576 (update_user)`
  - VERIFIED. The user-visibility guard short-circuits to 'visible' when the ACTING admin's tenant is empty. _assert_user_visible_to: utid = (tenant_id or '').strip(); if not utid: return (auth.py:634-636). update_user mirrors this: if getattr(...,'role') != 'super_admin': utid=...strip(); if utid: <do
  - **Fix:** Treat a tenant-less non-super_admin as restricted, not unrestricted: require super_admin for cross-tenant user mutation (or resolve the admin's effective tenant before comparing), so an empty utid nev
- **SCHEMA-01** [schemas-validators/validation] `schemas/profiling.py:68-77`
  - VERIFIED. RiskAssessmentCreate.validate_points implements all seven FINMA point-range checks with bare `assert` (lines 70-76: `assert 0 <= self.q_income_points <= 4`, etc.). Under pydantic v2.9.2 an AssertionError in a model_validator(mode='after') is converted to a 422 while assertions are enabled,
  - **Fix:** Replace each assert with explicit `if not (lo <= value <= hi): raise ValueError(...)`, or add Field(ge=..., le=...) directly to the int fields (q_income_points: int = Field(ge=0, le=4), etc.). Never r
- **SCHEMA-02** [schemas-validators/validation] `schemas/snapshots.py:29-40`
  - VERIFIED. StrategySnapshotCreate.check_bps_sum is the only SOLL-sum guard and uses a bare `assert abs(total - 10000) <= 50` (line 38), stripped under -O like SCHEMA-01. Additionally the five soll_*_bps fields (lines 11-15) are bare `int` with no ge=0, so even WITH assertions on, negative slices that
  - **Fix:** Convert the assert to `if abs(total - 10000) > 50: raise ValueError(...)`; add Field(ge=0, le=10000) to each soll_*_bps and band_*_bps field.
- **SCHEMA-04** [schemas-validators/validation] `schemas/allocation.py:6-22`
  - VERIFIED. TargetAllocationCreate target_*_bps (lines 7-11) and band_*_bps (12-21) are bare int with no ge=0/le=10000; risky_fraction_bps (22) is Optional[int] unbounded. validate_alloc (26-48) only checks the five targets sum to exactly 10000 and lo<=target<=hi per class. A payload with target_equit
  - **Fix:** Add Field(ge=0, le=10000) to each target_*_bps and band_*_bps field and to risky_fraction_bps.
- **SCHEMA-05** [schemas-validators/consistency] `schemas/clients.py:8,19,25,26 vs 37,48,54,55; schemas/mandates.py:16,20 vs 33,36`
  - VERIFIED. Create vs Update Literal-enum drift confirmed. ClientCreate.salutation is Optional[Literal['Herr','Frau','Divers']] (line 8) but ClientUpdate.salutation is Optional[str] (line 37). Same: ClientCreate.language Literal['DE','FR','IT','EN'] (19) vs ClientUpdate.language Optional[str] (48); ho
  - **Fix:** Make the Update fields use the same Literal types (kept Optional), e.g. salutation: Optional[Literal['Herr','Frau','Divers']]; mandate_type/advisory_language/household_type/client_classification/langu
- **SCHEMA-06** [schemas-validators/validation] `schemas/mandates.py:41-42,50 vs schemas/wealth.py:230-240`
  - VERIFIED. MandateUpdate.retirement_year (41), life_expectancy_year (42) and client_birth_year (50) are bare Optional[int] with no ge/le and no cross-field ordering check; MandateCreate.client_birth_year (mandates.py:27) is likewise unconstrained. The standalone MaxPensionSpendingRequest (wealth.py:2
  - **Fix:** Add Field(ge=1900, le=2200) to retirement_year/life_expectancy_year/client_birth_year on MandateUpdate (and to MandateCreate.client_birth_year), plus a model_validator enforcing birth_year < retiremen
- **RT-1** [risk-tax/robustness] `services/risk_scoring.py:198-199`
  - VERIFIED. canonicalize_horizon_label (line 156-158) returns the raw normalized string unchanged for any label not in CANONICAL_HORIZON_LABELS. Then HORIZON_YEARS.get(label, 1) (line 198) silently defaults an unknown/typo label to horizon_years=1. Every matrix row (1,1)..(1,5) is 0 (lines 90), and HO
  - **Fix:** Raise ValueError when canonicalize_horizon_label produces a label not in HORIZON_YEARS (the input is claimed pre-validated, so an unknown label is a real bug, not a tolerable default), and treat a mis

## Ops/Security/PDF/Electron (wrqjme1ct)

### HIGH (9)

- **EM-1** [electron-main/robustness] `main.js:369,383,517`
  - spawn() at lines 369 (packaged) and 383 (dev) gets only an 'exit' listener (line 517) plus stdout/stderr forwarding in attachBackendProcessLogging (244-259); NO 'error' listener is attached anywhere. If spawn cannot launch the executable (dev: python/python3 not on PATH -> ENOENT; packaged: exe bloc
  - **Fix:** Right after each spawn() in spawnBackendProcess(), attach backendProcess.on('error', (err) => { logLine('Backend spawn failed: '+(err.message||err)); }) and set a failure flag so waitForBackendReady()
- **MD-01** [market-data/correctness] `price_updater.py:412-417,420-429,348-353; symbol_points tuple at 215,234,243,254-259,276-281`
  - VERIFIED. symbol_points tuples carry only (price_date, price_rappen, source) — no currency — and every resolved PricePoint is built with currency=(product.currency or 'CHF') (lines 351, 415, 428) plus the synthetic path. The provider's real quotation currency is discarded: yfinance_provider._row_to_
  - **Fix:** Add a 4th element (currency) to symbol_points and propagate it into PricePoint.currency, falling back to product.currency only when the provider returns none. If provider currency and product.currency
- **MD-02** [market-data/correctness] `price_updater.py:257,280; upsert_price_history 450-481; to_rappen 76-78; vs daily_refresh 172,212`
  - VERIFIED with one correction. _fetch_twelvedata_symbol_points (257) and _fetch_aggregator_symbol_points (280) build int(payload.get('price_rappen') or 0); a 0 lands in symbol_points and is treated as RESOLVED. There is NO price_rappen>0 guard anywhere on the product path: to_rappen (76-78), twelveda
  - **Fix:** Drop points with price_rappen<=0 into symbol_errors instead of symbol_points (do not use 'or 0' to mask a missing value), and add a central price_rappen<=0 rejection in upsert_price_history / fetch_la
- **AUTH-01** [auth-2fa/security] `routers/auth.py:112-173 (login), 143 (only gate is per-user totp_enabled), 188-194 (/2fa/status only reports); services/auth.py:71-113 (get_current_user)`
  - Org-wide mandatory 2FA (settings.require_2fa) is NEVER enforced server-side. Verified: require_2fa appears only at config.py:226 (default False), auth.py:193 (status report), and in tests — no enforcement path exists. login() (auth.py:143) triggers the TOTP step ONLY when the individual user already
  - **Fix:** In login(), after password + is_active checks, if settings.require_2fa and not user.totp_enabled: do NOT call _issue_token_response(); instead return a restricted enrollment-only response (or 403 with
- **AUTH-02** [auth-2fa/security] `routers/auth.py:60-66 (_issue_token_response), 164-173 (login), 401 (create_user sets =1), 535 (invite_accept), 614 (admin reset sets =1); services/auth.py:71-113 (get_current_user never checks it); schemas/users.py:46`
  - must_change_password is enforced ONLY in the frontend. Verified: the column is set (auth.py:401 create_user=1, auth.py:614 admin reset=1) but get_current_user (services/auth.py:71-113) only validates exp, sub, is_active and the tid cross-check — it never inspects must_change_password. login()/invite
  - **Fix:** Enforce server-side: add a dependency (or check in get_current_user) that rejects all non-password-change endpoints with 403 while current_user.must_change_password is truthy, OR issue a scoped token
- **AUTH-03** [auth-2fa/security] `routers/auth.py:69-77 (_login_guard_key) used by login (114-115/128), password-reset (298), invite (490), resend (662); services/login_guard.py:17-93 (in-memory per-key deque)`
  - The brute-force lockout key is derived from the client-controlled X-Forwarded-For header (first hop) and only falls back to request.client.host when XFF is empty (auth.py:70-77). The header is trusted unconditionally — there is no trusted-proxy / hop-count setting (no trusted_proxy match in config).
  - **Fix:** Do not trust X-Forwarded-For by default. Default the key to request.client.host. Make XFF parsing opt-in via an explicit setting (e.g. trusted_proxy_count) and only read the Nth-from-right hop set by
- **AB-1** [admin-backup/correctness] `services/backup.py:233-242 (_perform_atomic_copy) + backup_scheduler.py:31-51`
  - VERIFIED. _perform_atomic_copy opens the source with plain `sqlite3.connect("file:...?mode=ro", uri=True)` (backup.py:234) and calls `src_conn.backup(dst_conn)` (backup.py:238) — using the stdlib `sqlite3` module, NOT sqlcipher3. In production the DB is SQLCipher-encrypted: config.py:442 hard-fails
  - **Fix:** Make the online backup SQLCipher-aware: detect encryption via database._sqlcipher_enabled() and, when enabled, connect via sqlcipher3 with `PRAGMA key` (+ the same cipher_page_size/kdf_iter/hmac/kdf p
- **AB-2** [admin-backup/consistency] `services/maintenance.py:52-55,105-168 vs services/backup.py:41-43,101-106 + backup_scheduler.py:37-42 + config.py:157`
  - VERIFIED. Two independent backup implementations write to two different directories with two different filename patterns. (1) Manual: POST /admin/system/db/backup (routers/system.py:190-195) -> maintenance.create_backup writes to ensure_backup_dir() = `<db_dir>/backups` (maintenance.py:53) with name
  - **Fix:** Unify on a single backup service, directory, and filename pattern. Either point maintenance.ensure_backup_dir() at settings.backup_dir, or have services.backup use `<db_dir>/backups`; adopt one strict
- **rls-1** [tenant-rls/security] `services/auth.py:167-173,189-193 + config.py:219-223,212-216`
  - VERIFIZIERT. config.py:223 setzt strict_tenant_isolation: bool = False als ausgelieferten Default. In auth.py:171-173 (_apply_tenant_filter_to_client_query) und 191-193 (_apply_tenant_filter_to_mandate_query) wird im non-strict Modus or_(tenant_id == user_tid, tenant_id.is_(None)) gefiltert. Folge:
  - **Fix:** strict_tenant_isolation in Tier-2/Shared-Cloud per Default erzwingen (z.B. aus deployment_tier=='tier2'/tenancy_mode=='multi' ableiten und beim Start setzen). NOT-NULL-Constraint + Backfill der tenant

### MED (18)

- **EM-4** [electron-main/correctness] `main.js:232-234,614`
  - When the single-instance lock is not acquired, app.quit() is called (line 233) but module execution continues with no return/guard. app.quit() is asynchronous; ipc handlers still register and app.whenReady().then(async () => { ... await bootstrap(); }) at line 614 still runs. Depending on timing whe
  - **Fix:** Capture const gotLock = app.requestSingleInstanceLock(); if (!gotLock) { app.quit(); return; } is not legal at module top-level, so guard the whenReady registration and ipc setup behind if (gotLock) {
- **EM-5** [electron-main/correctness] `main.js:189-195`
  - readStoredToken() calls clearStoredToken() (line 192, fs.unlinkSync of auth-token.bin) whenever safeStorage.isEncryptionAvailable() returns false. writeStoredToken() (203-218) refuses to persist plaintext and only ever writes ciphertext (encryptString at 211), so the on-disk file is ALWAYS encrypted
  - **Fix:** When encryption is merely unavailable, do NOT delete the file: just log and return null (the file stays for when safeStorage recovers). Only clear on a confirmed decryptString failure of an actually-r
- **EM-6** [electron-main/robustness] `main.js:277-289,344`
  - Two real issues in port selection. (1) TOCTOU: isTcpPortInUse() (277-289) opens-and-closes a listener to test occupancy, then later spawnBackendProcess() tells the backend to bind that same port; between close() (286) and the backend binding, another process can grab the port, after which the backen
  - **Fix:** Resolve a free ephemeral port up-front via resolveFreePort() and pass it to the backend (APP_PORT already supported), eliminating the TOCTOU window; or at minimum make isTcpPortInUse resolve(true) on
- **EM-7** [electron-main/robustness] `main.js:397-416`
  - terminateBackendProcess(): on win32 it runs spawnSync('taskkill', ['/pid', pid, '/t', '/f']) (line 406) but never inspects the spawnSync result/status; on non-win32 it sends only SIGTERM (408) with no SIGKILL escalation/timeout. The finally block (412-415) nulls backendProcess and backendManagedByAp
  - **Fix:** Check spawnSync's returned status/error and logLine on failure; on POSIX add SIGTERM-then-SIGKILL escalation with a short timeout. Only null backendProcess/backendManagedByApp after confirming termina
- **EM-2** [electron-main/robustness] `main.js:549-564`
  - The file:save-pdf ipcMain.handle body has no try/catch. It throws synchronously on missing data (line 553 throw new Error('PDF-Daten fehlen.')) and fs.writeFileSync (line 563) can throw (ENOSPC, EACCES/EPERM on chosen path). Inside ipcMain.handle these surface as a rejected invoke promise the render
  - **Fix:** Wrap the handler body in try/catch and return { ok:false, error:String(e.message||e) } instead of throwing. Validate base64 (reject on empty or round-trip mismatch). Prefer fs.promises.writeFile and s
- **MD-03** [market-data/robustness] `price_updater.py:776-812 (refresh_all_prices), 707-740 (refresh_prices_for_mandate); summarize_price_quality 584-594; yfinance get_eod 104-130`
  - VERIFIED. Staleness/age is evaluated ONLY in the price_point is None (failed-fetch) branch (lines 711-716, 780-785). A SUCCESSFUL but stale fetch is upserted unconditionally with its old price_date and counted as inserted/updated; no max-age comparison exists in the success path. yfinance get_eod /
  - **Fix:** After a successful fetch, compare price_point.price_date against today using stale_after_days; if older than threshold AND not newer than the existing latest, count as stale/failed and surface in summ
- **MD-04** [market-data/correctness] `services/market_data/providers/yfinance_provider.py:113-130; stooq_provider.py:114-131; base.py:76-85; cache.py:299-309`
  - VERIFIED. base.py contract (76-85) requires the last trading day <= on_date. yfinance get_eod uses df.iloc[-1] with end=on_date+timedelta(days=1) (Yahoo treats end loosely and can include an extra day) and never filters rows by date<=on_date. stooq get_eod requests [on_date-10d, on_date] and blindly
  - **Fix:** In both get_eod implementations, filter parsed rows/df to date<=on_date and take the max; raise SymbolNotFound if none remain. This enforces the documented contract and keeps the cache key consistent
- **MD-05** [market-data/robustness] `price_updater.py:99-132,236-246; services/market_data/aggregator.py:88-135; yfinance_provider.py:60-70`
  - VERIFIED. fetch_latest_price retries price_refresh_max_attempts with a fixed time.sleep(retry_delay_seconds), no jitter/exponential backoff, and on a rate-limit simply re-sleeps and hammers again (99-130). _fetch_stooq_symbol_points is a per-symbol urlopen loop (236-246) with no inter-symbol throttl
  - **Fix:** Add exponential backoff with jitter in fetch_latest_price and stop retrying a provider on RateLimitError; add a small inter-symbol delay in the per-symbol stooq loop; bound the batch symbol count per
- **MD-06** [market-data/robustness] `services/market_data_daily_refresh.py:166,202-229,245-250`
  - VERIFIED. _refresh_asset_class_prices (166) and _refresh_fx_rates (202) hardcode target_date = date.today() with no most-recent-business-day computation; both rely on providers honoring the <=on_date contract that MD-04 shows is not enforced. FX/asset-class paths guard close/rate>0 (172, 211-212) bu
  - **Fix:** Compute target_date as the most recent business day and apply the same >0 / freshness guards uniformly across product, asset-class and FX refresh paths.
- **AUTH-04** [auth-2fa/security] `routers/auth.py:181-183 (logout no-op), 230-245 (2fa/disable), 325-345 (password-reset/confirm), 597-626 (admin password reset); services/auth.py:28-44 (token), 71-113 (validate)`
  - No token revocation/refresh exists. Verified: logout() (auth.py:181-183) just returns a message; get_current_user (services/auth.py:81-113) validates only signature, exp (verify_exp disabled then checked manually), sub, is_active and tid — there is no token_version / password_changed_at / iat-vs-cha
  - **Fix:** Add a per-user invalidation signal: store password_changed_at / token_version on the user, embed it as a claim at issue time, and reject in get_current_user any token whose version/iat predates the la
- **AUTH-05** [auth-2fa/security] `routers/auth.py:50-57 (_bootstrap_required), 88-109 (bootstrap_admin)`
  - bootstrap_admin (auth.py:88-109) is unauthenticated and has NO rate limiting (unlike login, which calls login_attempt_guard). Verified: the only guard is _bootstrap_required (no non-deleted user exists), and the check (line 90) is separate from the insert+commit (105-106) with no transaction-level u
  - **Fix:** Enforce single-admin creation transactionally (rely on a unique constraint / SELECT-then-insert in one transaction, or a dedicated 'bootstrap done' flag with a unique row). Apply login_attempt_guard t
- **AUTH-06** [auth-2fa/security] `routers/auth.py:143-162 (2FA verify in login); services/totp.py:41-55 (window=1)`
  - TOTP verification uses window=1 (totp.py:42,52-54), accepting counter-1, counter, counter+1 => up to ~90s validity, and NO last-used counter is persisted anywhere (verified: no replay/counter column in the model or recovery service). A captured 6-digit code can be replayed within the window and reus
  - **Fix:** Persist the last accepted TOTP counter per user and reject codes whose counter <= last-used (single-use/replay prevention). Ensure 2FA failures are always counted by a non-bypassable rate limiter (fix
- **AB-3** [admin-backup/robustness] `services/maintenance.py:105-135 (create_backup)`
  - VERIFIED. create_backup does `shutil.copy2(db_file, backup_path)` on a live WAL-mode DB (maintenance.py:113) and only afterwards copies -wal/-shm in a separate loop (116-125). This is not an atomic snapshot: writes (and WAL checkpoints) occurring between copying the main .db and the -wal can yield a
  - **Fix:** Run `PRAGMA wal_checkpoint(TRUNCATE)` before the copy (so the -wal is empty/consistent), or route the manual path through a unified online-backup routine. Copying -wal after the main .db is not a fix;
- **AB-4** [admin-backup/robustness] `services/backup.py:108-114,167-201,221-242`
  - VERIFIED. backup_database writes the destination .db via _perform_atomic_copy and then writes the .sha256 sidecar (backup.py:110-114) with no temp-file + atomic rename. If the process is killed or the disk fills mid-backup or before the sidecar is written, a partial/zero-byte `5eyes-backup-*.db` (or
  - **Fix:** Write to a temp name (e.g. `*.db.partial`) and os.replace() to the final name only after both the backup() and the sidecar succeed. In restore_database, refuse (or loudly warn + require an explicit ov
- **AB-5** [admin-backup/validation] `backup_scheduler.py:75-96 + services/backup.py:97-106,18-21 + config.py:157`
  - VERIFIED. settings.backup_dir defaults to ~/5eyes/backups and backup_database creates it with mkdir(parents=True, exist_ok=True) (backup.py:102) with no guard that it differs from the DB directory. The module docstring (backup.py:18-21) explicitly warns that backups in the same directory as the DB a
  - **Fix:** On scheduler start (and/or in build_compliance_status) emit a warning when resolve_db_file(settings.db_path).parent == resolved backup_dir, and surface a 'backups co-located with DB' flag in /admin/sy
- **AB-6** [admin-backup/robustness] `services/maintenance.py:240-249 + routers/system.py:135-140 (db/integrity)`
  - VERIFIED. run_integrity_check executes `PRAGMA integrity_check` with no problem-count argument and `.fetchall()`s the entire result into memory (maintenance.py:242), then builds a Python list (243). On a corrupted large DB this PRAGMA can return a very large result set and run for a long time. The e
  - **Fix:** Use `PRAGMA integrity_check(50)` to cap reported problems, set a short busy_timeout, and cap the returned list length before JSON-serializing.
- **rls-2** [tenant-rls/security] `routers/protocol_bausteine.py:96-101,280-286,128 + models/protocol_bausteine.py:25`
  - VERIFIZIERT. ProtocolBaustein traegt eine tenant_id (models/protocol_bausteine.py:25, beim Anlegen gesetzt protocol_bausteine.py:128). list_bausteine (Z.96-101) filtert fuer non-admins NUR (advisor_id == current_user.id) | (advisor_id IS NULL) — KEIN tenant_id-Filter. Globale Bausteine (advisor_id=N
  - **Fix:** In list_bausteine und in der Validierung von replace_mandate_selections zusaetzlich nach tenant_id des current_user filtern (analog _apply_tenant_filter_to_client_query: tenant_id == user_tid, im non-
- **rls-3** [tenant-rls/validation] `routers/wealth.py:463-490,499-545,964-990,993-1017 vs. 599,649,697,735; schemas/wealth.py:8-77,78-121,264-285,286-298`
  - VERIFIZIERT mit Einschraenkung. enforce_data_classification wird in wealth.py bei create/update_cashflow (Z.599,649) und create/update_goal (Z.697,735) aufgerufen, FEHLT aber bei create_wealth_position (463-490), update_wealth_position (499-545), create_wealth_inflow (964-990) und update_wealth_infl
  - **Fix:** data_classification: Literal['synthetic','real']='synthetic' (Create) bzw. Optional[...] (Update) zu WealthPositionCreate/Update und WealthInflowCreate/Update hinzufuegen und in den vier Endpoints enf

