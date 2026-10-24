"""GOAL-REACHABILITY-FIELD-HONESTY-001 (CIO-Entscheid, Engine ``saa_resampled_v15``).

Befund: ``goal_achievability[].feasible_set_reachable`` war True, sobald auf
der Pruefmenge (oder von der lokalen Suche) eine zulaessige Allokation mit
OBERER Wilson-Grenze >= tau/2 gefunden wurde. Der Name behauptete
Erreichbarkeit -- bei tau = 80 % genuegte eine obere Grenze von 40 %.

Neu, auf jeder gepruefen Zielzeile:

* ``screen_upper_bound_meets_half_tau`` -- dieselbe Groesse, ehrlich benannt
  (Screening-Kriterium, keine Erreichbarkeit).
* ``reachable_at_tau`` -- untere Wilson-Grenze >= tau der publizierten
  Allokation, deckungsgleich mit ``status == "erreichbar"``.

Konsumenten: kein UI-, PDF-, Report- oder TS-Typ-Konsument las das alte Feld
(statischer Nachweis unten); alte persistierte Zeilen behalten ihren Namen.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer import goal_reachability as reachability  # noqa: E402
from services.optimizer.objective import certify_success_indicator  # noqa: E402


def _screen(*, reachable: bool, certificate_status: str | None = None) -> dict:
    return {
        "version": reachability.GOAL_REACHABILITY_SCREEN_VERSION,
        "objective_mode": "goal_shortfall",
        "screening_cube_hash": "cube",
        "goals": [{
            "goal_id": "g", "label": "G", "tau": 0.8,
            "max_probability": 0.35, "max_upper_bound": 0.41,
            "reachable": reachable,
            "certificate": (
                {"status": certificate_status} if certificate_status else None
            ),
        }],
    }


def _published_row(probability: float, *, n_paths: int = 2_000, tau: float = 0.8) -> dict:
    successes = int(round(probability * n_paths))
    per_path = np.zeros(n_paths, dtype=np.int8)
    per_path[:successes] = 1
    estimate = certify_success_indicator(
        per_path, tau=tau, weights_arr=None, weight_sum=None, validation_seed=1,
    )
    return {"goal_id": "g", "tau": tau, **estimate}


def test_half_tau_screen_hit_is_not_reported_as_reachable():
    """Gegenbeispiel: obere Grenze 41 % >= tau/2 = 40 % auf der Pruefmenge,
    die publizierte Allokation erreicht 35 % gegen tau 80 %. Bis v14 stand
    auf der Zeile ``feasible_set_reachable = True``."""
    row = _published_row(0.35)
    assert row["status"] == "nicht_erreichbar"
    (annotated,) = reachability.annotate_rows([row], _screen(reachable=True))
    assert annotated["screen_upper_bound_meets_half_tau"] is True
    assert annotated["reachable_at_tau"] is False
    assert "feasible_set_reachable" not in annotated


def test_local_search_hit_sets_only_the_screen_criterion():
    row = _published_row(0.35)
    (annotated,) = reachability.annotate_rows(
        [row], _screen(reachable=False,
                       certificate_status=reachability.CERTIFICATE_STATUS_REACHABLE),
    )
    assert annotated["screen_upper_bound_meets_half_tau"] is True
    assert annotated["reachable_at_tau"] is False


@pytest.mark.parametrize("n_paths", [40, 400, 4_000])
def test_reachable_at_tau_is_congruent_with_status(n_paths):
    """Property: fuer jede publizierte Wahrscheinlichkeit gilt
    ``reachable_at_tau == (status == "erreichbar")`` und daraus folgt
    ``lower_confidence_bound >= tau``."""
    for probability in np.linspace(0.0, 1.0, 101):
        row = _published_row(float(probability), n_paths=n_paths)
        for reachable in (True, False):
            (annotated,) = reachability.annotate_rows([row], _screen(reachable=reachable))
            assert annotated["reachable_at_tau"] is (row["status"] == "erreichbar")
            if annotated["reachable_at_tau"]:
                assert annotated["lower_confidence_bound"] >= annotated["tau"]


def test_unscreened_rows_stay_untouched():
    row = {"goal_id": "other", "probability": 0.9}
    (annotated,) = reachability.annotate_rows([row], _screen(reachable=True))
    assert annotated == row


def test_no_frontend_or_report_consumer_reads_the_reachability_fields():
    """Statischer Nachweis: weder Monolith noch React-Report noch PDF-Schicht
    lesen das alte oder die neuen Felder (reine API-/Audit-Offenlegung)."""
    names = ("feasible_set_reachable", "screen_upper_bound_meets_half_tau", "reachable_at_tau")
    sources = [REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"]
    sources += sorted((REPO_ROOT / "5eyes-electron" / "frontend" / "reporting" / "src").rglob("*.ts*"))
    sources += sorted((BACKEND_ROOT / "services" / "pdf").rglob("*.py"))
    sources += sorted((BACKEND_ROOT / "routers").rglob("*.py"))
    readers = [
        str(path.relative_to(REPO_ROOT))
        for path in sources
        if path.is_file() and any(name in path.read_text(encoding="utf-8", errors="ignore")
                                  for name in names)
    ]
    assert len(sources) > 10
    assert readers == []
