"""Gemeinsamer Harness der kappa_H-Kalibrierung (HOUSE-PRIOR-CALIBRATION-PROVENANCE-001).

KEIN Produktcode. Schreibt keine Datenbank: ``DB_PATH`` wird -- falls nicht
gesetzt -- auf eine Datei in einem frischen Temp-Verzeichnis gelegt; die
Live-Datenbank (``~/5eyes/5eyes.db``) wird abgelehnt. Die Optimizer-Module
oeffnen ohnehin keine Session.

Inputs: CMA und Hausmatrizen 1:1 aus ``tests/test_engine_reference_mandates.py``
(dieselben fuenf Referenzmandate A-E wie das Tuning vom 2026-10-18,
``tuning_2026_10_18/exp_common.py``). Zieldaten sind kalenderjahr-relativ mit
festem Monat/Tag: innerhalb eines Bewertungsjahres sind alle Seeds und damit
alle Ergebnisse bit-reproduzierbar (Bewertungsjahr steht im Manifest).
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

_LIVE_DB = (Path.home() / "5eyes" / "5eyes.db").resolve()
if not os.environ.get("DB_PATH"):
    os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="kappa_calib_")) / "calib.db")
if Path(os.environ["DB_PATH"]).expanduser().resolve() == _LIVE_DB:
    raise SystemExit("DB_PATH zeigt auf die Live-Datenbank -- abgebrochen.")
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_key, "1")

BACKEND = Path(__file__).resolve().parents[2] / "5eyes-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

CMA_BASE = {
    "id": "cma-shrink",
    "bonds_chf_ig_return_bps": 220, "bonds_chf_ig_vol_bps": 350,
    "bonds_fx_hedged_return_bps": 220, "bonds_fx_hedged_vol_bps": 430,
    "equity_ch_return_bps": 620, "equity_ch_vol_bps": 1450,
    "equity_intl_return_bps": 700, "equity_intl_vol_bps": 1600,
    "real_estate_ch_return_bps": 450, "real_estate_ch_vol_bps": 820,
    "alternatives_gold_return_bps": 300, "alternatives_gold_vol_bps": 1200,
    "liquidity_return_bps": 80, "liquidity_vol_bps": 20,
    "correlation_matrix_json": "",
    "equities_skewness_bps": -3000, "equities_excess_kurt_bps": 15000,
    "bonds_skewness_bps": 0, "bonds_excess_kurt_bps": 0,
    "real_estate_skewness_bps": 0, "real_estate_excess_kurt_bps": 0,
    "alternatives_skewness_bps": 0, "alternatives_excess_kurt_bps": 0,
    "liquidity_skewness_bps": 0, "liquidity_excess_kurt_bps": 0,
}

HM = {
    "wachstum": dict(
        profile_name="Wachstumsorientiert",
        equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
        bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200,
        max_risky_fraction_bps=7500),
    "konservativ": dict(
        profile_name="Konservativ",
        equity_min_bps=500, equity_max_bps=2500, equity_target_bps=1500,
        bonds_min_bps=5000, bonds_max_bps=8000, bonds_target_bps=6500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=500, alt_target_bps=200,
        liq_min_bps=500, liq_max_bps=2000, liq_target_bps=1000,
        max_risky_fraction_bps=3000),
    "ausgewogen": dict(
        profile_name="Ausgewogen",
        equity_min_bps=2500, equity_max_bps=5000, equity_target_bps=4000,
        bonds_min_bps=3500, bonds_max_bps=6000, bonds_target_bps=4500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=300, liq_max_bps=2000, liq_target_bps=500,
        max_risky_fraction_bps=5500),
}

# (Hausmatrix, Score x10, Vermoegen CHF, Cashflow CHF/J, Horizont, Ziel CHF,
# Zieljahre, Haerte) -- identisch zum Tuning.
MANDATES = {
    "A_ausg_spar": dict(hm="ausgewogen", score=50, wealth=500_000, cf=20_000, H=12, goal=900_000, gy=12, hard="Hart"),
    "B_kons_entn": dict(hm="konservativ", score=25, wealth=2_000_000, cf=-80_000, H=20, goal=900_000, gy=20, hard="Hart"),
    "C_wachs_entn": dict(hm="wachstum", score=70, wealth=1_500_000, cf=-60_000, H=20, goal=1_500_000, gy=20, hard="Primaer"),
    "D_wachs_spar": dict(hm="wachstum", score=70, wealth=300_000, cf=30_000, H=15, goal=1_100_000, gy=15, hard="Hart"),
    "E_ausg_entn": dict(hm="ausgewogen", score=50, wealth=1_000_000, cf=-50_000, H=15, goal=500_000, gy=15, hard="Hart"),
}

VALUATION_YEAR = date.today().year


def cma(**overrides):
    base = dict(CMA_BASE)
    base.update(overrides)
    return SimpleNamespace(**base)


def goal(gid: str, target_rappen: int, years: int, hardness: str = "Hart"):
    return SimpleNamespace(
        id=gid, label=gid, goal_type="Vermoegensziel",
        target_amount_rappen=int(target_rappen), target_wealth_rappen=int(target_rappen),
        target_return_bps=None, horizon_years=None,
        start_date=date(VALUATION_YEAR, 1, 1).isoformat(),
        target_date=date(VALUATION_YEAR + int(years), 12, 31).isoformat(),
        is_ongoing=0, frequency="jaehrlich", hardness=hardness, rank=1,
        weight_bps=5000, value_mode="real",
    )


def build_inputs(name: str, scale: float = 1.0) -> dict:
    m = MANDATES[name]
    return dict(
        cma=cma(),
        goals=[goal(f"{name}-ziel", round(m["goal"] * scale) * 100, m["gy"], m["hard"])],
        house_matrix_row=SimpleNamespace(**HM[m["hm"]]),
        score_x10=m["score"],
        advisory_wealth_rappen=m["wealth"] * 100,
        cashflow_series_rappen=[m["cf"] * 100] * m["H"],
        horizon_years=m["H"],
        n_paths=2000,
    )


def seed_of(*parts) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def bps_to_w(bps: dict) -> np.ndarray:
    from services.optimizer.scenario_engine import BUCKET_ORDER

    return np.array([int(bps[bucket]) / 10000.0 for bucket in BUCKET_ORDER])
