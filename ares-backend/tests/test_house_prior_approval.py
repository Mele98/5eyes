"""HOUSE-PRIOR-APPROVAL-001 (Audit 2026-11, Entscheid AA-4, Luecke L21, P12).

kappa_H = 300 ist als "Haus-Prior v1" vorlaeufig in Gebrauch (provisional,
docs/adr/ADR-015-...): Bestaetigungs-Holdout auf v18 not_confirmed.
Diese Tests pinnen:

* den unveraenderten WERT (300) und den Status "provisional" (statt
  "experimental"; nie "approved" ohne erfuellte Holdout-Regel),
* die reine Offenlegung der Abweichung SAA minus Hausquote je Klasse,
* den Reasoning-Satz in pp,
* das ADR (Herleitung, Wirkung, Grenzen, Review-Turnus, Release-Gate).

Rein und schnell: kein Solver-Lauf (der Lauf-Nachweis steht in
``test_house_prior_shrinkage.test_disclosure_fields_are_complete_and_in_the_model_basis``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer import house_prior as hp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "docs" / "adr" / "ADR-015-haus-prior-kappa-v1.md"


def test_kappa_value_is_unchanged_and_released_as_v1():
    assert hp.HOUSE_PRIOR_KAPPA == 300.0
    assert hp.HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS == "provisional_v1"
    assert hp.HOUSE_PRIOR_PARAMETER_RELEASE == "v1"
    assert hp.HOUSE_PRIOR_PARAMETER_STATUS == "provisional"
    assert "experimental" not in hp.HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS
    # Bestaetigungs-Holdout v18 not_confirmed -> kein "approved" (ADR-015).
    assert "approved" not in hp.HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS
    assert "approved" not in hp.HOUSE_PRIOR_PARAMETER_STATUS
    # Algorithmus-Version unberuehrt (Freigabe betrifft nur den Parameter).
    assert hp.HOUSE_PRIOR_VERSION == "house_prior_ridge_tracking_error_v2"
    assert (REPO_ROOT / hp.HOUSE_PRIOR_PARAMETER_ADR) == ADR


def test_prior_metric_audit_discloses_release():
    audit = hp.prior_metric_audit(np.diag([2.25e6, 1.2e5, 1.0e5, 4.0e5, 0.0]))
    assert audit["kappa_calibration_status"] == "provisional_v1"
    assert audit["kappa_release"] == "v1"
    assert audit["kappa_release_adr"] == hp.HOUSE_PRIOR_PARAMETER_ADR
    assert audit["ridge_bps2"] == hp.HOUSE_PRIOR_RIDGE_BPS2


def test_house_deviation_is_final_minus_house_per_class():
    final = {"equities": 4050, "bonds": 3950, "real_estate": 1000,
             "alternatives": 500, "liquidity": 500}
    house = {"equities": 4000, "bonds": 4000, "real_estate": 1000,
             "alternatives": 500, "liquidity": 500}
    deviation = hp.house_deviation_bps(final, house)
    assert deviation == {"equities": 50, "bonds": -50, "real_estate": 0,
                         "alternatives": 0, "liquidity": 0}
    assert sum(deviation.values()) == 0
    assert list(deviation) == list(final)


def test_house_deviation_without_house_quote_is_none():
    assert hp.house_deviation_bps({"equities": 10000}, None) is None
    assert hp.house_deviation_bps({"equities": 10000}, {}) is None


def test_house_deviation_counts_missing_classes_as_zero():
    deviation = hp.house_deviation_bps({"equities": 6000, "bonds": 4000},
                                       {"equities": 5000, "liquidity": 5000})
    assert deviation == {"equities": 1000, "bonds": 4000, "liquidity": -5000}


def test_deviation_sentence_in_pp():
    text = hp.house_deviation_sentence({
        "equities": 50, "bonds": -50, "real_estate": 0,
        "alternatives": 0, "liquidity": 0,
    })
    assert text == (
        "Abweichung zur Hausquote je Anlageklasse: Aktien +0.50 pp, "
        "Obligationen -0.50 pp, Immobilien +0.00 pp, Alternative +0.00 pp, "
        "Liquiditaet +0.00 pp."
    )
    assert hp.house_deviation_sentence({"equities": 0, "bonds": 0}) == (
        "Abweichung zur Hausquote: in allen Anlageklassen 0.00 pp."
    )
    assert hp.house_deviation_sentence(None) is None


def test_house_prior_sentence_carries_the_deviation():
    block = {
        "kappa": 300.0,
        "tracking_error_vs_house_bps": 12.5,
        "decision": hp.DECISION_HOUSE_PRIOR,
        "deviation_vs_house_bps": {"equities": 120, "bonds": -120},
    }
    text = hp.house_prior_sentence(block)
    assert "Hausmatrix als Anker des Optimierers" in text
    assert "Aktien +1.20 pp, Obligationen -1.20 pp" in text
    # Ohne Feld (Altbestand) unveraendert ohne Abweichungssatz.
    block.pop("deviation_vs_house_bps")
    assert "Abweichung zur Hausquote" not in hp.house_prior_sentence(block)


def test_deviation_is_disclosure_only_penalty_unchanged():
    """Die Offenlegung beruehrt den Prior-Term nicht (Wert 300 wirkt gleich)."""
    cov = np.diag([2.25e6, 1.2e5, 1.0e5, 4.0e5, 1.0e3])
    w = np.array([0.41, 0.39, 0.10, 0.05, 0.05])
    w_h = np.array([0.40, 0.40, 0.10, 0.05, 0.05])
    expected = 300.0 * float((w - w_h) @ (cov / 1e8 + 2500.0 / 1e8 * np.eye(5)) @ (w - w_h))
    assert hp.house_prior_penalty(w, w_h, cov) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("needle", [
    "kappa_H = 300",
    "Haus-Prior v1",
    "provisional_v1",
    "Vorläufig in Gebrauch (provisional)",
    "6d11f8ac",
    "854ee8e9",
    "## Herleitung und Kalibrierung",
    "## Wirkung",
    "±0.5 pp",
    "## Grenzen",
    "## Release-Gate",
    "## Review-Turnus",
    "nicht** kundenabhängig",
    "deviation_vs_house_bps",
    # N-857-2: Engine-Diskrepanz, Bestaetigungs-Holdout v18, Freigabevermerk.
    "d1ca3f99",
    "git log --follow",
    "saa_resampled_v18",
    "`not_confirmed`",
    "−0.010 pp",
    "kappa_holdout.py run",
    "## Freigabevermerk",
    "`<FREIGABE_OWNER>`",
    "Codex-Nachprüfung offen",
])
def test_adr_documents_derivation_effect_limits_and_review(needle):
    text = ADR.read_text(encoding="utf-8")
    assert needle in text
