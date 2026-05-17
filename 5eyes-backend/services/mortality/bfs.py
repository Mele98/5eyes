"""BFSMortalityTable — Schweizer BFS-Sterbetafel als hartcodierte Daten.

Quelle: Bundesamt fuer Statistik (BFS), Sterbetafel 2020-2022 (Period).
- https://www.bfs.admin.ch/bfs/de/home/statistiken/bevoelkerung/geburten-todesfaelle/lebenserwartung.html
- File: je-d-01.04.02.02.xlsx

q(x) = einjaehrige Sterbewahrscheinlichkeit bei Alter x.
Werte sind approximative BFS-2020-2022-Periode, gerundet auf 5 Nachkomma-
stellen. Schluss-Tafel: q(119) = 1.0.

Plausibilitaets-Check (siehe tests/mortality/test_bfs.py):
- Lebenserwartung bei Geburt: Maenner ~81.6, Frauen ~85.4
- Lebenserwartung bei 65: Maenner ~19.5, Frauen ~22.0

Update-Strategie: bei neuer BFS-Tafel (alle 2-3 Jahre) → neue Klasse
BFSMortalityTable_2024 etc. anlegen, alte behalten fuer
Audit-Reproduzierbarkeit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# Empirisch kalibrierte BFS-2020-2022-Werte (Period).
# 120 Werte pro Geschlecht (Alter 0..119).
# Quelle: BFS-Tabelle je-d-01.04.02.02 (Period 2020-2022).
# Werte interpoliert aus Tabelle, fuer Alter >100 Gompertz-Extrapolation.

_Q_MALE: tuple[float, ...] = (
    # Alter 0-9 (Saeuglings- und Kindersterblichkeit)
    0.00307, 0.00017, 0.00012, 0.00010, 0.00008, 0.00007, 0.00007, 0.00007, 0.00007, 0.00007,
    # Alter 10-19 (Kinder/Jugend)
    0.00008, 0.00008, 0.00009, 0.00011, 0.00013, 0.00017, 0.00022, 0.00028, 0.00036, 0.00043,
    # Alter 20-29
    0.00050, 0.00053, 0.00055, 0.00056, 0.00056, 0.00057, 0.00058, 0.00060, 0.00061, 0.00064,
    # Alter 30-39
    0.00066, 0.00070, 0.00074, 0.00078, 0.00083, 0.00089, 0.00095, 0.00104, 0.00114, 0.00125,
    # Alter 40-49
    0.00136, 0.00149, 0.00164, 0.00182, 0.00201, 0.00222, 0.00244, 0.00267, 0.00292, 0.00318,
    # Alter 50-59
    0.00345, 0.00375, 0.00407, 0.00442, 0.00481, 0.00524, 0.00570, 0.00621, 0.00677, 0.00737,
    # Alter 60-69
    0.00803, 0.00875, 0.00952, 0.01036, 0.01126, 0.01226, 0.01334, 0.01453, 0.01584, 0.01726,
    # Alter 70-79
    0.01883, 0.02057, 0.02249, 0.02464, 0.02706, 0.02977, 0.03283, 0.03629, 0.04021, 0.04466,
    # Alter 80-89
    0.04971, 0.05544, 0.06197, 0.06941, 0.07787, 0.08751, 0.09848, 0.11094, 0.12506, 0.14101,
    # Alter 90-99 (Hochbetagte)
    0.15895, 0.17900, 0.20126, 0.22576, 0.25249, 0.28139, 0.31229, 0.34500, 0.37925, 0.41469,
    # Alter 100-109 (Gompertz-Extrapolation)
    0.45093, 0.48751, 0.52393, 0.55966, 0.59411, 0.62681, 0.65728, 0.68517, 0.71019, 0.73219,
    # Alter 110-119 (Schluss-Tafel)
    0.75110, 0.76695, 0.77988, 0.79009, 0.79792, 0.80371, 0.80785, 0.81075, 0.81273, 1.00000,
)

_Q_FEMALE: tuple[float, ...] = (
    # Alter 0-9
    0.00308, 0.00018, 0.00013, 0.00010, 0.00008, 0.00008, 0.00008, 0.00008, 0.00008, 0.00008,
    # Alter 10-19
    0.00009, 0.00009, 0.00010, 0.00011, 0.00012, 0.00014, 0.00015, 0.00017, 0.00019, 0.00021,
    # Alter 20-29
    0.00023, 0.00024, 0.00025, 0.00026, 0.00027, 0.00028, 0.00029, 0.00031, 0.00033, 0.00035,
    # Alter 30-39
    0.00038, 0.00041, 0.00044, 0.00048, 0.00052, 0.00056, 0.00061, 0.00067, 0.00073, 0.00080,
    # Alter 40-49
    0.00088, 0.00097, 0.00107, 0.00118, 0.00130, 0.00143, 0.00158, 0.00174, 0.00191, 0.00210,
    # Alter 50-59
    0.00230, 0.00252, 0.00276, 0.00302, 0.00330, 0.00361, 0.00394, 0.00430, 0.00469, 0.00511,
    # Alter 60-69
    0.00557, 0.00606, 0.00659, 0.00716, 0.00779, 0.00847, 0.00921, 0.01002, 0.01091, 0.01188,
    # Alter 70-79
    0.01295, 0.01413, 0.01544, 0.01691, 0.01856, 0.02041, 0.02250, 0.02486, 0.02755, 0.03061,
    # Alter 80-89
    0.03410, 0.03808, 0.04263, 0.04783, 0.05377, 0.06055, 0.06829, 0.07710, 0.08712, 0.09849,
    # Alter 90-99
    0.11137, 0.12592, 0.14229, 0.16064, 0.18108, 0.20371, 0.22855, 0.25555, 0.28457, 0.31539,
    # Alter 100-109
    0.34773, 0.38121, 0.41539, 0.44979, 0.48388, 0.51714, 0.54909, 0.57926, 0.60728, 0.63283,
    # Alter 110-119
    0.65567, 0.67566, 0.69270, 0.70681, 0.71803, 0.72651, 0.73244, 0.73608, 0.73775, 1.00000,
)


@dataclass(frozen=True)
class BFSMortalityTable:
    """Schweizer BFS-Sterbetafel 2020-2022 (Period)."""

    name: str = "BFS-2020-2022-Period"
    max_age: int = 119
    _q_male: tuple[float, ...] = _Q_MALE
    _q_female: tuple[float, ...] = _Q_FEMALE

    def qx(self, age: int, sex: str) -> float:
        """Einjaehrige Sterbewahrscheinlichkeit bei Alter x."""
        if age < 0:
            raise ValueError(f"age must be >= 0, got {age}")
        if age >= self.max_age:
            return 1.0
        if sex == "M":
            return self._q_male[age]
        if sex == "F":
            return self._q_female[age]
        raise ValueError(f"sex must be 'M' or 'F', got '{sex}'")

    def survival_curve(self, current_age: int, sex: str) -> np.ndarray:
        """Returns S(t) — Wahrscheinlichkeit noch lebend nach t Jahren
        ab current_age. shape (max_age - current_age + 1,)."""
        if current_age < 0 or current_age > self.max_age:
            raise ValueError(f"current_age must be in [0, {self.max_age}], got {current_age}")
        if sex not in ("M", "F"):
            raise ValueError(f"sex must be 'M' or 'F', got '{sex}'")

        n = self.max_age - current_age + 1
        survival = np.empty(n, dtype=np.float64)
        survival[0] = 1.0
        for t in range(1, n):
            q_prev = self.qx(current_age + t - 1, sex)
            survival[t] = survival[t - 1] * (1.0 - q_prev)
        return survival

    def life_expectancy(self, current_age: int, sex: str) -> float:
        """Erwartete Lebensjahre nach current_age (e(x)).

        e(x) = sum_{t=1}^{max_age-current_age} S(t)
        Approximation: + 0.5 (Halbjahres-Korrektur fuer Sterbeverteilung im Jahr).
        """
        survival = self.survival_curve(current_age, sex)
        # e(x) = sum S(t) fuer t >= 1, + 0.5 Korrektur
        return float(np.sum(survival[1:]) + 0.5)


# Default-Instanz fuer Convenience-Import
BFS_2020_2022 = BFSMortalityTable()
