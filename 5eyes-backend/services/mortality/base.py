"""MortalityTable — Interface fuer Sterbetafeln.

Eine MortalityTable enthaelt die einjaehrigen Sterbewahrscheinlichkeiten
q(x) pro Alter und Geschlecht. Daraus laesst sich die Survival-Function
S(x) und CDF F(x) ableiten, was fuer das Inverse-CDF-Sampling im
sampler.py genutzt wird.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

import numpy as np


Sex = Literal["M", "F"]


@runtime_checkable
class MortalityTable(Protocol):
    """Universal-Interface fuer Sterbetafeln (Period oder Generation).

    Konvention:
    - Alter in vollen Jahren, 0..max_age (typisch 119)
    - q(x): Wahrscheinlichkeit dass eine x-jaehrige Person im naechsten
      Jahr stirbt. Schluss-Tafel: q(max_age) = 1.0
    - Geschlecht M/F binaer (BFS-Datenkonvention)
    """

    @property
    def name(self) -> str:
        """Quellen-Identifikation, z.B. 'BFS-2020-2022-Period'."""
        ...

    @property
    def max_age(self) -> int:
        """Hoechstes modelliertes Alter (inklusive). Typisch 119."""
        ...

    def qx(self, age: int, sex: Sex) -> float:
        """Einjaehrige Sterbewahrscheinlichkeit bei Alter x.

        Returns 1.0 fuer age >= max_age (Schluss-Tafel).
        """
        ...

    def survival_curve(self, current_age: int, sex: Sex) -> np.ndarray:
        """Returns S(t|current_age) — Wahrscheinlichkeit noch lebend nach
        t Jahren ab current_age.

        Returns: shape (max_age - current_age + 1,) — S[0]=1.0, S[end]=0.0.
        S(t) = prod_{x=current_age}^{current_age+t-1} (1 - q(x))
        """
        ...
