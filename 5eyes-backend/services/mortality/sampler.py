"""Inverse-CDF-Sampler fuer Sterbe-Alter aus einer MortalityTable.

Idee:
1. Aus MortalityTable → Survival-Curve S(t) berechnen
2. F(t) = 1 - S(t) ist die CDF des Sterbe-Alters
3. Fuer jeden MC-Pfad: U ~ Uniform(0,1), finde t mit F(t-1) < U <= F(t)
4. Sterbe-Alter = current_age + t

Vektorisiert via numpy.searchsorted — sehr schnell auch fuer 100k Pfade.
"""
from __future__ import annotations

import numpy as np

from services.mortality.base import MortalityTable, Sex


def sample_age_at_death(
    n_paths: int,
    current_age: int,
    sex: Sex,
    table: MortalityTable,
    seed: int | None = None,
) -> np.ndarray:
    """Sample Sterbe-Alter fuer n_paths Pfade per Inverse-CDF.

    Args:
        n_paths: Anzahl MC-Pfade
        current_age: aktuelles Alter (zum Simulationsbeginn)
        sex: 'M' oder 'F'
        table: MortalityTable-Instanz (z.B. BFS_2020_2022)
        seed: optionaler RNG-Seed fuer Reproduzierbarkeit

    Returns:
        ndarray shape (n_paths,) mit Sterbe-Alter (int)
        Bereich: current_age+1 .. table.max_age+1

    Beispiel: current_age=65, sex='M' → 10k Samples → mean ~84.5
    """
    if n_paths < 1:
        raise ValueError(f"n_paths must be >= 1, got {n_paths}")

    survival = table.survival_curve(current_age, sex)
    # CDF des Sterbejahrs (relativ zu current_age):
    # P(stirbt im Intervall (t-1, t]) = S(t-1) - S(t)
    # Cumulative: F(t) = 1 - S(t)
    cdf = 1.0 - survival  # F[0]=0, F[end]=1

    rng = np.random.default_rng(seed)
    u = rng.uniform(0.0, 1.0, size=n_paths)

    # searchsorted gibt fuer jedes u den kleinsten Index t mit cdf[t] >= u
    # Da cdf monoton waechst, ist das genau das gewuenschte Sterbe-Jahr
    death_year_relative = np.searchsorted(cdf, u, side="left")
    # Clamp auf max_age (in seltenen Faellen koennte u > cdf[-1] sein, was
    # wegen Floatpoint passieren kann)
    max_relative = len(survival) - 1
    death_year_relative = np.clip(death_year_relative, 1, max_relative)

    death_age = current_age + death_year_relative.astype(np.int32)
    return death_age


def death_year_index_from_age(
    death_ages: np.ndarray,
    current_age: int,
    horizon_years: int,
) -> np.ndarray:
    """Konvertiert Sterbe-Alter zu year_index relativ zu Simulationsbeginn.

    Args:
        death_ages: shape (n_paths,) Sterbe-Alter
        current_age: Alter zu Simulationsbeginn
        horizon_years: Simulations-Horizont in Jahren

    Returns:
        ndarray shape (n_paths,), Werte in [1, horizon_years].
        Wenn Sterbe-Alter > current_age + horizon_years → horizon_years
        (= "Person lebt ueber den Horizont hinaus")
    """
    relative = death_ages - current_age
    return np.clip(relative, 1, horizon_years).astype(np.int32)
