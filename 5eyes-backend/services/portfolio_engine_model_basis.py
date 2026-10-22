"""Modell-Basis-Block: welche Methodik einen Lauf erzeugt hat.

ADR-014-Cluster-Submodul. Herausgeloest aus ``services/portfolio_engine.py``
(2026-10-11), weil das Zeilenbudget-Gate zum vierten Mal in drei Tagen
ansprang und sein eigener Hinweis verlangt, in diesem Fall die Extraktion zu
pruefen statt die Zahl erneut zu erhoehen.

Die Extraktion ist sauber: ``_build_allocation_model_basis()`` nimmt alles
ueber explizite Parameter, gibt ein dict zurueck und ruft ausserhalb nur die
fuenf ``_simulation_*``-Praeferenz-Leser des MC-Clusters sowie die drei
Nachweis-Funktionen auf. Keine Zirkularitaet: dieses Modul importiert
``portfolio_engine_mc_simulation`` und ``portfolio_engine_cma`` direkt, und
keines von beiden importiert ``portfolio_engine`` auf Modulebene.

Inhaltlich ist der Block der Nachweis darueber, unter WELCHER Methodik eine
Allokation und ihre Wahrscheinlichkeiten entstanden sind -- getrennt in zwei
Kanaele:

* ``optimization`` -- das Entscheidungsmodell (konstante Gewichte, Seed,
  Pfadzahl, Steuerbasis, Ziel-Gewichtung, Primaerterm der Zielfunktion).
  Wird in ``effective_constraints_json`` persistiert und beim Reload verbatim
  zurueckgespielt.
* ``reporting`` -- die Implementierungs-Projektion (Drift, Rebalancing,
  Transaktionskosten, Tail-Modell, Zeitgitter des Drawdown).

Die beiden duerfen legitim verschiedene Zielwahrscheinlichkeiten liefern; die
API darf sie deshalb nie als eine unbenannte Methodik praesentieren.
"""

from __future__ import annotations

from models.allocation import CapitalMarketAssumption, TargetAllocation
from models.mandates import Mandate
from services.cma_correlation_provenance import bucket_correlation_provenance
from services.drawdown_refinement import drawdown_time_grid_basis
from services.optimizer.scenario_engine import tail_moment_provenance
from services.portfolio_engine_cma import _sub_class_intra_correlation_x100
from services.portfolio_engine_mc_simulation import (
    _simulation_crisis_strength,
    _simulation_rebalance_mode,
    _simulation_stress_multiplier,
    _simulation_transaction_cost_bps,
    _simulation_use_tail_risk,
)


def _build_allocation_model_basis(
    *,
    optimizer_mode: str,
    optimizer_result,
    allocation: TargetAllocation | None,
    monte_carlo: dict,
    simulation_prefs: dict | None,
    mandate: Mandate,
    cma: CapitalMarketAssumption | None = None,
    stored_optimization_basis: dict | None = None,
    reporting_tax_cashflow_present: bool | None = None,
    forced_active_method: str | None = None,
) -> dict[str, dict]:
    """Describe decision and implementation models as two explicit views.

    The stochastic optimizer selects the allocation under a constant-weight
    decision model.  The reporting Monte Carlo then projects implementation
    behaviour (drift, optional rebalancing and transaction costs).  They may
    legitimately produce different goal probabilities, so the API must never
    present them as an unlabeled single methodology.

    ``forced_active_method`` ist die Methode, die der AUFRUFER fuer diese
    Allokation persistiert -- RISK-FALLBACK-CONTEXT-001. Sie gewinnt vor jeder
    Ableitung hier, weil sie der tatsaechlich gespeicherte Wert IST und nicht
    eine Rekonstruktion davon.

    Hintergrund: im Generierungspfad wird diese Funktion mit
    ``allocation=None`` aufgerufen -- die TargetAllocation existiert noch
    nicht. Loeste der Risikobudget-Fallback aus, hatte sie damit keine Quelle
    fuer die Methode und leitete ``"house_matrix"`` aus dem Modus ab, waehrend
    unmittelbar danach ``"fallback_house_matrix"`` persistiert wurde. Diese
    Divergenz war nicht nur kosmetisch: der Lesepfad prueft ueber
    ``_verified_persisted_allocation_context`` genau diese Gleichheit und wirft
    ``ValueError``, sobald sie verletzt ist -- eine FRISCH erzeugte
    Fallback-Allokation liess sich dadurch nicht mehr laden oder
    finalisieren. Ein Gate, das die eigene Ausgabe der Engine ablehnt, ist
    nicht fail-closed, sondern funktionsunfaehig.

    Der RELOAD-Pfad war unauffaellig, weil er ``allocation`` uebergibt und die
    Methode darueber findet. Nur der Generierungspfad brauchte die Angabe.
    """
    context = getattr(optimizer_result, "context", None)
    stored_method = (
        getattr(allocation, "optimization_method", None)
        if allocation is not None
        else None
    )
    active_method = str(
        forced_active_method
        or getattr(optimizer_result, "method", None)
        or stored_method
        or ("house_matrix" if optimizer_mode == "house_matrix" else optimizer_mode)
    )
    # RISK-FALLBACK-CONTEXT-001 (Rest): ein erzwungener Hausmatrix-Fallback
    # ersetzt die GESAMTE Auswahl-Herkunft. Der Kontext des gescheiterten
    # bzw. verworfenen Solver-Laufs hat diese Allokation nicht ausgewaehlt;
    # liesse man ihn stehen, trueg die Basis gleichzeitig
    # ``active_method=fallback_house_matrix`` und
    # ``basis_id=stochastic_decision_v2`` (samt Solver-Zielfunktion,
    # Liability-Pfaden und Importance-Sampling) -- ein Widerspruch im
    # Nachweis. Seed/Pfadzahl des verworfenen Laufs bleiben als Audit-Spur
    # ueber ``optimizer_result`` erhalten.
    if active_method == "fallback_house_matrix":
        context = None
    # A status/method string alone is not proof that a stochastic context ever
    # existed. In particular, an import/startup failure can produce an audited
    # House fallback with ``context=None`` and no stochastic analytics.
    has_stochastic_basis = context is not None
    legacy_stochastic = bool(
        context is None
        and stored_optimization_basis is None
        and allocation is not None
        and stored_method == "stochastic"
    )
    legacy_shadow = bool(
        context is None
        and stored_optimization_basis is None
        and allocation is not None
        and stored_method is None
        and getattr(allocation, "shadow_optimization_json", None)
    )
    if has_stochastic_basis and optimizer_mode == "shadow_stochastic":
        optimization_basis_id = "stochastic_shadow_candidate_v2"
        optimization_purpose = "candidate_comparison"
    elif has_stochastic_basis:
        optimization_basis_id = "stochastic_decision_v2"
        optimization_purpose = "allocation_selection"
    elif legacy_stochastic:
        optimization_basis_id = "stochastic_legacy_unverified_v0"
        optimization_purpose = "historical_provenance_unverified"
    elif legacy_shadow:
        optimization_basis_id = "stochastic_shadow_legacy_unverified_v0"
        optimization_purpose = "historical_provenance_unverified"
    elif active_method == "fallback_house_matrix":
        optimization_basis_id = "house_matrix_fallback_v1"
        optimization_purpose = "controlled_fallback"
    elif active_method == "manual_override":
        # MANUAL-SAVE-DEADEND-001: Quoten vom Berater gesetzt (begruendet,
        # Risikobudget serverseitig geprueft) -- weder Solver noch
        # Hausmatrix-Mitte; der Nachweis darf das nicht verschleiern.
        optimization_basis_id = "manual_override_v1"
        optimization_purpose = "advisor_manual_selection"
    else:
        optimization_basis_id = "house_matrix_policy_v1"
        optimization_purpose = "allocation_selection"
    optimizer_seed = getattr(optimizer_result, "seed", None)
    if optimizer_seed is None and allocation is not None:
        optimizer_seed = getattr(allocation, "optimization_seed", None)
    optimizer_n_paths = (
        int(getattr(context, "n_paths", 0) or 0)
        if context is not None
        else int(getattr(optimizer_result, "n_paths", 0) or 0)
    )
    optimizer_horizon = (
        int(getattr(context, "horizon_years", 0) or 0)
        if context is not None
        else int(monte_carlo.get("horizon_years", 0) or 0)
    )
    tax_regime = getattr(context, "tax_regime", None) if context is not None else None
    dividend_yields = (
        getattr(context, "dividend_yield_bps_per_bucket", None)
        if context is not None
        else None
    )
    has_dividend_tax_input = bool(
        dividend_yields is not None
        and any(float(value or 0) != 0.0 for value in dividend_yields)
    )
    has_effective_tax_component = bool(
        tax_regime is not None
        and (
            bool(getattr(tax_regime, "supports_wealth_tax", False))
            or has_dividend_tax_input
        )
    )
    legacy_context_unknown = legacy_stochastic or legacy_shadow
    reporting_tail = bool(_simulation_use_tail_risk(simulation_prefs))
    # CMA-CORRELATION-JURISDICTION-PROVENANCE-001: welche Bucket-Korrelations-
    # struktur gerechnet wurde und ob sie zur Jurisdiktion des Mandats passt.
    # Fehlt der CMA-Payload, ist es der Schweizer Default -- auch fuer ein
    # DE-Mandat; das stand bisher nirgends. Beide Kanaele fuehren denselben
    # Block, weil beide dieselbe CMA-Spalte lesen.
    bucket_correlation = bucket_correlation_provenance(cma)
    tail_moments = tail_moment_provenance(cma)

    optimization_basis = {
            "basis_id": optimization_basis_id,
            "purpose": optimization_purpose,
            "active_method": active_method,
            "portfolio_dynamics": (
                "annual_constant_weight"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "policy_matrix"
                )
            ),
            "return_measure": "gross_twr_pre_transaction_cost",
            "liquidity_yield": (
                "cma_total_return"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "not_applicable"
                )
            ),
            "tail_model": (
                "bounded_cornish_fisher_moment_calibrated_v2"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "not_applicable"
                )
            ),
            "importance_sampling": bool(
                context is not None
                and getattr(context, "scenario_weights", None) is not None
            ),
            "transaction_cost_bps": 0,
            "seed": int(optimizer_seed) if optimizer_seed is not None else None,
            "n_paths": optimizer_n_paths or None,
            "horizon_years": optimizer_horizon or None,
            "tax_basis": (
                f"median_rate_{type(tax_regime).__name__}"
                if has_effective_tax_component
                else (
                    f"none_effective_{type(tax_regime).__name__}"
                    if tax_regime is not None
                    else (
                        "historical_context_unavailable"
                        if legacy_context_unknown
                        else "none"
                    )
                )
            ),
            "liability_basis": (
                "goal_liability_paths"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "policy_only"
                )
            ),
            "real_estate_return_basis": (
                "listed_real_estate_total_return_including_distributions_v1"
            ),
            "cma_mean_semantics": "arithmetic_expected_total_return_v1",
            "return_moment_mapping": (
                "arithmetic_mean_and_volatility_preserved_v2"
            ),
            "tail_calibration": (
                "bounded_cornish_fisher_gauss_hermite_v2"
            ),
            # SUBRISK-CONTEXT-REPLAY-001: Risikobasis in die Evidenz binden.
            # Begruendung siehe _sub_class_intra_correlation_x100().
            "sub_class_intra_correlation_x100": _sub_class_intra_correlation_x100(),
            "bucket_correlation": bucket_correlation,
            # CMA-TAIL-MISSINGNESS-SEMANTICS-001: fuer welche Buckets nie
            # ein Tail-Moment geschaetzt wurde. Beide Kanaele lesen
            # dieselben Felder mit demselben NULL-oder-0-Ausdruck.
            "tail_moment_provenance": tail_moments,
            "foundation_model_version": "external_foundation_v2",
            "external_property_goal_basis": (
                "inflation_zero_real_plus_exact_liability_and_pledged_transfer_v2"
            ),
            "indirect_amortization_treatment": "pledged_asset_transfer_v1",
            "direct_real_estate_scope": "external_total_wealth",
            "external_rent_treatment": "cashflow_only",
        }
    # CERT-OPTIMIZER-OBJECTIVE-001 / OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001:
    # the goal-weighting mode changes the solver's objective mathematics by
    # up to 50x between a "hart" and an "opportunistisch" goal
    # (services.optimizer.objective.HARDNESS_WEIGHT), but was never part of
    # this model basis. Two runs that genuinely optimized different
    # objective functions therefore persisted an identical basis (and, via
    # effective_constraints_json, an identical allocation_context_hash) with
    # no way to prove which mathematics produced which allocation. Bind the
    # centrally validated mode (and its multipliers, when active) into the
    # FRESH basis only -- a replayed/stored basis (handled below) must stay
    # verbatim and must never be silently upgraded with the CURRENT
    # environment's mode.
    # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: wenn ein Solver-Context
    # existiert, kommen BEIDE Modi aus dessen eingefrorenem Vertrag -- nicht
    # aus der Umgebung. Vorher las diese Stelle live nach, waehrend der Solver
    # seine eigenen (moeglicherweise anderen) Werte benutzt hatte: der
    # Nachweis nannte dann einen Modus, der die Allokation nicht erzeugt
    # hatte. Ohne Context lief kein Solver (House-Matrix-Pfad); dann gibt es
    # keinen Lauf, mit dem der Nachweis kongruent sein muesste, und der
    # aktuelle Modus bleibt die ehrliche Antwort.
    from services.optimizer.objective import (
        HARDNESS_WEIGHT,
        resolve_goal_weighting_mode,
    )
    run_contract = None
    if context is not None:
        from services.optimizer.objective_contract import objective_contract_of

        run_contract = objective_contract_of(context)
    goal_weighting_mode = (
        run_contract.goal_weighting_mode
        if run_contract is not None
        else resolve_goal_weighting_mode()
    )
    optimization_basis["goal_weighting_mode"] = goal_weighting_mode
    optimization_basis["goal_weighting_hardness_multipliers"] = (
        dict(HARDNESS_WEIGHT) if goal_weighting_mode == "hardness" else None
    )
    # OPTIMIZER-OBJECTIVE-VARIANTS-001: derselbe Grund wie die Ziel-Gewichtung
    # direkt darueber -- der Primaerterm der Zielfunktion ist austauschbar, und
    # zwei Laeufe, die genuin verschiedene Zielfunktionen optimiert haben,
    # duerfen im Nachweis nicht identisch aussehen. Ebenfalls nur in die
    # FRISCHE Basis, nie in eine zurueckgespielte.
    from services.optimizer.objective_variants import objective_basis

    optimization_basis["objective"] = objective_basis(
        run_contract.objective_mode if run_contract is not None else None
    )
    # SAA-RESAMPLED-STABILITY-001: Stabilitaets-Audit des Resamplings
    # (Bags, Streuung je Bucket, Signifikanztest gegen die Hausmatrix,
    # Entscheid). Additiv und nur in der FRISCHEN stochastischen Basis --
    # eine zurueckgespielte Basis (unten) bleibt wortgetreu.
    if has_stochastic_basis:
        from services.optimizer.resampling import resampling_model_basis

        resampling_basis = resampling_model_basis(
            getattr(optimizer_result, "resampling", None)
        )
        if resampling_basis is not None:
            optimization_basis["resampling"] = resampling_basis
    if stored_optimization_basis is not None:
        if not isinstance(stored_optimization_basis, dict):
            raise ValueError(
                "Persistierte Optimizer-Modellbasis muss ein Objekt sein."
            )
        # This snapshot is part of effective_constraints_json and therefore of
        # allocation_context_hash. Returning it verbatim keeps persisted goal
        # probabilities tied to the exact model that produced them.
        optimization_basis = dict(stored_optimization_basis)

    return {
        "optimization": optimization_basis,
        "reporting": {
            "basis_id": "implementation_projection_v2",
            "purpose": "post_selection_projection",
            "portfolio_dynamics": _simulation_rebalance_mode(simulation_prefs),
            "return_measure": "gross_twr_pre_rebalancing_cost",
            "transaction_cost_bps": int(
                _simulation_transaction_cost_bps(simulation_prefs)
            ),
            "liquidity_yield": "zero_bucket_plus_position_interest_cashflow",
            "real_estate_return_basis": (
                "listed_real_estate_total_return_including_distributions_v1"
            ),
            "cma_mean_semantics": "arithmetic_expected_total_return_v1",
            "return_moment_mapping": (
                "arithmetic_mean_and_volatility_preserved_v2"
            ),
            "tail_calibration": (
                "bounded_cornish_fisher_gauss_hermite_v2"
                if reporting_tail
                else "not_applicable"
            ),
            # SUBRISK-CONTEXT-REPLAY-001: dieselbe Bindung wie im
            # Entscheidungskanal -- gemeinsame Momentquelle beider Kanaele.
            "sub_class_intra_correlation_x100": _sub_class_intra_correlation_x100(),
            "bucket_correlation": bucket_correlation,
            # CMA-TAIL-MISSINGNESS-SEMANTICS-001: fuer welche Buckets nie
            # ein Tail-Moment geschaetzt wurde. Beide Kanaele lesen
            # dieselben Felder mit demselben NULL-oder-0-Ausdruck.
            "tail_moment_provenance": tail_moments,
            # DRAWDOWN-TIME-GRID-001: Methode hinter mc_max_drawdown_bps.
            "max_drawdown_time_grid": drawdown_time_grid_basis(),
            "foundation_model_version": "external_foundation_v2",
            "total_scope_goal_basis": "exact_total_projection_path_v2",
            "indirect_amortization_treatment": "pledged_asset_transfer_v1",
            "direct_real_estate_scope": "external_total_wealth",
            "external_rent_treatment": "cashflow_only",
            "direct_real_estate_return_basis": (
                "position_price_appreciation_plus_explicit_rent_v2"
            ),
            "tail_model": (
                "bounded_cornish_fisher_moment_calibrated_v2"
                if reporting_tail
                else "lognormal_arithmetic_moments_v2"
            ),
            "stress_multiplier": float(
                _simulation_stress_multiplier(simulation_prefs)
            ),
            "crisis_strength": float(
                _simulation_crisis_strength(simulation_prefs)
            ),
            "seed": int(monte_carlo.get("seed", 0) or 0),
            "n_paths": int(monte_carlo.get("simulations", 0) or 0),
            "horizon_years": int(monte_carlo.get("horizon_years", 0) or 0),
            "tax_basis": (
                "estimated_wealth_tax_cashflow"
                if bool(reporting_tax_cashflow_present)
                else "configured_cashflows"
            ),
        },
    }


