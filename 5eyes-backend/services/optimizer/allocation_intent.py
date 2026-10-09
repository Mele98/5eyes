"""Typed Allocation Intent primitives (CERT-ALLOCATION-INTENT-001).

Spec: ``docs/audits/2026-10-08-allocation-intent-effective-constraints-and-
publication-certification-spec.md`` (not committed in this repo; see
``docs/RELEASE_FINDING_CLOSURE_REGISTER.md`` -> "Aktives Unterpaket
CERT-ALLOCATION-INTENT-001").

This module is the shared root-cause fix for four coupled findings:

- ``MANUAL-TARGET-SEMANTICS-001``: a manual ``bands.<bucket>.target_bps``
  preference was never consumed by the converged stochastic solver -- only
  the derived min/max bounds reached it. Two contradictory manual targets
  with identical bounds produced the identical converged allocation.
- ``MANUAL-TARGET-PUBLICATION-001``: the Strategy PDF published that same
  functionally-ignored value under the word "Soll" (see
  ``services/pdf/documents/anlagestrategie.py``).
- ``BAND-PARTIAL-OVERRIDE-001``: a bucket's stale baseline target (never
  requested by the advisor in this call) blocked an unrelated, perfectly
  legitimate ``max_bps``-only override.
- ``AB-MODEL-001`` (extension): the Policy A/B comparison scored raw,
  unclamped House-Matrix targets that could lie outside the policy's own
  effective bounds.

The fix here supplies the piece shared by the first two findings: a real,
versioned Soft-Preference penalty that is orthogonal to hard bounds, plus
the extraction helper that reads an *explicit* manual target (never a
baseline fill-in) consistently wherever ``bands.<bucket>.target_bps`` is
read. ``BAND-PARTIAL-OVERRIDE-001`` and ``AB-MODEL-001`` are fixed directly
in ``services/portfolio_engine_house_matrix.py`` and
``services/backtest_ab.py`` using the already-existing deterministic
feasible projection ``_rebalance_to_total``.

Explicitly OUT of scope for this module (full spec Secs. 5-14 go further
and are tracked as follow-up, see the PR description for
CERT-ALLOCATION-INTENT-001): the discriminated
``AllocationIntent``/``EffectiveAllocationConstraintsV1`` persistence
artifact, a Hard-Target lock workflow, Initial-Guess/Reference-Only
publication types, a legacy-value quarantine/migration workflow, and a
versioned ``AllocationIntentPolicy`` approval table.
``ObjectiveContractV1``/lossless objective evidence belongs to the
parallel ``CERT-OPTIMIZER-OBJECTIVE-001`` package --
``services/optimizer/objective.py`` is deliberately not touched here.
"""
from __future__ import annotations

from typing import Mapping

# Mirrors services.optimizer.scenario_engine.BUCKET_ORDER. Duplicated (not
# imported) to keep this module free of any dependency on the scenario/
# solver machinery -- it is pure bucket-key/penalty-math plumbing reused by
# both the solver and non-solver consumers (reasoning text, evidence).
BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")

# Spec Sec. 5.3/7 call for a versioned, advisor-approved `AllocationIntentPolicy`
# that supplies lambda/alpha and is bound into the objective/model hash. A real
# policy table (with an approval workflow) is tracked as follow-up work; until
# it exists, every soft preference uses this single, EXPLICITLY VERSIONED
# default so a future policy migration has a named "legacy_default_policy"
# provenance value to replace, instead of a silent, unversioned constant.
SOFT_PREFERENCE_POLICY_VERSION = "soft-preference-default-v1"
SOFT_PREFERENCE_PENALTY_LAMBDA_DEFAULT = 2.0
SOFT_PREFERENCE_ALPHA_DEFAULT: dict[str, float] = {bucket: 1.0 for bucket in BUCKET_ORDER}


def extract_soft_preference_bps(bands: Mapping | None) -> dict[str, int]:
    """Pull EXPLICIT advisor-stated ``target_bps`` overrides out of a bands
    preferences mapping.

    Returns only buckets for which ``target_bps`` was explicitly provided
    (not ``None``) in THIS request -- never a baseline-filled value. A
    bucket missing from the result has NO Target Intent at all (spec
    Sec. 5.1: "Fehlendes Target Intent bedeutet keine Targetabsicht").
    Callers must not treat "absent" as "keep whatever the baseline target
    happened to be" -- that conflation is exactly
    ``MANUAL-TARGET-SEMANTICS-001``/``BAND-PARTIAL-OVERRIDE-001``.
    """
    # Lazy import: services.portfolio_engine imports services.optimizer.*
    # lazily throughout for the same circular-import reason (see e.g.
    # services/portfolio_engine_optimizer_integration.py); this module
    # mirrors that convention instead of introducing a module-level cycle.
    from services.portfolio_engine import _bucket_key, _coerce_band_bps

    if not isinstance(bands, Mapping):
        return {}
    preferred: dict[str, int] = {}
    for raw_key, override in bands.items():
        bucket = _bucket_key(raw_key)
        if not bucket or not isinstance(override, Mapping):
            continue
        value = _coerce_band_bps(override.get("target_bps"))
        if value is not None:
            preferred[bucket] = int(value)
    return preferred


def preference_loss_from_array(
    w,
    preferred_bps: Mapping[str, int] | None,
    *,
    lam: float = SOFT_PREFERENCE_PENALTY_LAMBDA_DEFAULT,
    alpha: Mapping[str, float] | None = None,
) -> float:
    """Soft-preference objective penalty for a solver weight array.

    ``preference_loss = lam * sum_b alpha_b * (w_b - preferred_b)^2`` (both
    ``w_b`` and ``preferred_b`` as fractions of 1.0), computed only over
    buckets that actually carry an explicit preference (spec Sec. 7). A
    bucket without a preference contributes exactly zero loss -- "missing
    Target Intent" is never silently treated as "target 0%".

    This is an additive penalty computed entirely in the solver layer
    (``services/optimizer/solver.py``), not inside
    ``services/optimizer/objective.py`` -- CERT-ALLOCATION-INTENT-001 is
    deliberately scoped to leave that module untouched.
    """
    if not preferred_bps:
        return 0.0
    weights = alpha or SOFT_PREFERENCE_ALPHA_DEFAULT
    total = 0.0
    for index, bucket in enumerate(BUCKET_ORDER):
        if bucket not in preferred_bps:
            continue
        preferred_fraction = float(preferred_bps[bucket]) / 10000.0
        deviation = float(w[index]) - preferred_fraction
        total += float(weights.get(bucket, 1.0)) * (deviation * deviation)
    return float(lam) * total


def preference_deviation_bps(
    weights_bps: Mapping[str, int],
    preferred_bps: Mapping[str, int] | None,
) -> dict[str, int]:
    """Per-bucket ``effective - preferred`` deviation in bps, for evidence
    (reasoning text, audit, future PDF disclosure) -- never used to
    influence Solver math. Only buckets that actually carried a preference
    are included, so an all-zero deviation is distinguishable from "this
    bucket had no stated preference".
    """
    if not preferred_bps:
        return {}
    return {
        bucket: int(weights_bps.get(bucket, 0) or 0) - int(preferred_bps[bucket])
        for bucket in preferred_bps
    }
