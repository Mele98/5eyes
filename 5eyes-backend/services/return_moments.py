"""Canonical mapping from arithmetic CMA moments to log-return parameters.

Capital-market assumptions describe simple annual returns: ``mu`` is the
arithmetic expected return and ``sigma`` its standard deviation.  A lognormal
path therefore cannot use ``sigma`` directly as log-volatility.  This module
provides the single mapping consumed by optimizer and reporting simulations.

For Cornish-Fisher tails the polynomial expansion is clipped outside the range
where it is a meaningful approximation.  The resulting bounded innovation is
then calibrated by deterministic Gauss-Hermite quadrature so both requested
simple-return moments remain intact.
"""
from __future__ import annotations

from functools import lru_cache
import math

import numpy as np


RETURN_MOMENT_MODEL_VERSION = "arithmetic_lognormal_cf_v2"
_CF_INNOVATION_CLIP = 8.0
_QUADRATURE_ORDER = 128


class ReturnMomentError(ValueError):
    """Raised when a CMA moment cannot define a valid gross-return model."""


def _validated_moments(mu: float, sigma: float) -> tuple[float, float]:
    mean = float(mu)
    volatility = float(sigma)
    if not math.isfinite(mean) or not math.isfinite(volatility):
        raise ReturnMomentError("CMA return moments must be finite.")
    if mean <= -1.0:
        raise ReturnMomentError(
            "CMA expected return must be greater than -100 %."
        )
    if volatility < 0.0:
        raise ReturnMomentError("CMA volatility must not be negative.")
    return mean, volatility


def bounded_cornish_fisher(
    z,
    skew: float,
    excess_kurtosis: float,
):
    """Apply the shared, numerically bounded Cornish-Fisher innovation."""
    skew_value = np.asarray(skew, dtype=np.float64)
    kurtosis_value = np.asarray(excess_kurtosis, dtype=np.float64)
    value = (
        z
        + (skew_value / 6.0) * (z * z - 1.0)
        + (kurtosis_value / 24.0) * (z * z * z - 3.0 * z)
        - (skew_value ** 2 / 36.0) * (2.0 * z * z * z - 5.0 * z)
    )
    if np.isscalar(value):
        return max(-_CF_INNOVATION_CLIP, min(_CF_INNOVATION_CLIP, float(value)))
    return np.clip(value, -_CF_INNOVATION_CLIP, _CF_INNOVATION_CLIP)


@lru_cache(maxsize=128)
def _tail_quadrature(skew: float, excess_kurtosis: float) -> tuple[np.ndarray, np.ndarray]:
    nodes, weights = np.polynomial.hermite.hermgauss(_QUADRATURE_ORDER)
    standard_normal_nodes = nodes * math.sqrt(2.0)
    probabilities = weights / math.sqrt(math.pi)
    innovation = np.asarray(
        bounded_cornish_fisher(
            standard_normal_nodes,
            float(skew),
            float(excess_kurtosis),
        ),
        dtype=np.float64,
    )
    innovation.setflags(write=False)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    probabilities.setflags(write=False)
    return innovation, probabilities


def _log_weighted_exp_expectation(
    scale: float,
    innovation: np.ndarray,
    probabilities: np.ndarray,
) -> float:
    exponent = float(scale) * innovation
    maximum = float(np.max(exponent))
    expectation = float(
        np.sum(probabilities * np.exp(exponent - maximum))
    )
    return maximum + math.log(expectation)


@lru_cache(maxsize=2048)
def _tail_log_parameters_cached(
    mu: float,
    sigma: float,
    skew: float,
    excess_kurtosis: float,
) -> tuple[float, float]:
    gross_mean = 1.0 + mu
    if sigma == 0.0:
        return math.log(gross_mean), 0.0

    innovation, probabilities = _tail_quadrature(skew, excess_kurtosis)
    target_cv_squared = (sigma / gross_mean) ** 2

    def _cv_squared(scale: float) -> float:
        log_m1 = _log_weighted_exp_expectation(
            scale,
            innovation,
            probabilities,
        )
        log_m2 = _log_weighted_exp_expectation(
            2.0 * scale,
            innovation,
            probabilities,
        )
        log_ratio = log_m2 - 2.0 * log_m1
        if log_ratio > 700:
            return math.inf
        return math.expm1(log_ratio)

    low = 0.0
    high = max(0.05, sigma / gross_mean)
    while _cv_squared(high) < target_cv_squared and high < 8.0:
        high *= 2.0
    if _cv_squared(high) < target_cv_squared:
        raise ReturnMomentError(
            "Cornish-Fisher calibration cannot reproduce the requested CMA volatility."
        )
    for _ in range(80):
        middle = (low + high) / 2.0
        if _cv_squared(middle) < target_cv_squared:
            low = middle
        else:
            high = middle
    scale = (low + high) / 2.0
    log_mgf = _log_weighted_exp_expectation(
        scale,
        innovation,
        probabilities,
    )
    location = math.log(gross_mean) - log_mgf
    return location, scale


def arithmetic_moments_to_log_parameters(
    mu: float,
    sigma: float,
    *,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    use_cornish_fisher: bool = False,
) -> tuple[float, float]:
    """Return log-location and innovation scale preserving simple moments."""
    mean, volatility = _validated_moments(mu, sigma)
    skew_value = float(skew)
    kurtosis_value = float(excess_kurtosis)
    if not math.isfinite(skew_value) or not math.isfinite(kurtosis_value):
        raise ReturnMomentError("CMA tail moments must be finite.")
    if (
        use_cornish_fisher
        and (abs(skew_value) > 1e-15 or abs(kurtosis_value) > 1e-15)
    ):
        return _tail_log_parameters_cached(
            mean,
            volatility,
            skew_value,
            kurtosis_value,
        )

    gross_mean = 1.0 + mean
    variance_ratio = (volatility / gross_mean) ** 2
    log_variance = math.log1p(variance_ratio)
    log_scale = math.sqrt(log_variance)
    log_location = math.log(gross_mean) - 0.5 * log_variance
    return log_location, log_scale
