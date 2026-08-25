"""KGV-Mean-Reversion-Modell fuer Equity-Return-Adjustment.

Empirische Grundlage: Shiller-CAPE (Robert Shiller, 1981+):
- KGV (Price/Earnings ratio) ist mean-reverting auf langen Horizonten
- Aktuelles KGV >> langfristiger Mittelwert → niedrigere kuenftige Returns
- Aktuelles KGV << langfristiger Mittelwert → hoehere kuenftige Returns

Modell (vereinfacht):

    return_adjustment_pa_bps = alpha * (kgv_fair - kgv_current) / kgv_fair * 10000
                              * dampening(horizon_years)

dampening(t) = max(0.3, 1 - 0.03*t) — laengere Horizonte: schwaecheres Signal
weil Mean-Reversion im Long-Run abgeschlossen ist.

Spec: docs/planning/2026-05-17-sprint-7-kgv-mean-reversion.md
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KGVMeanReversionModel:
    """KGV-basiertes Mean-Reversion-Adjustment fuer Equity-Returns.

    Beispiel:
        >>> model = KGVMeanReversionModel(
        ...     kgv_current=22.0, kgv_fair=17.0, alpha=0.15
        ... )
        >>> model.expected_annual_return_adjustment_bps(horizon_years=10)
        -312.74...  # negativ, weil Overvaluation
    """

    kgv_current: float
    """Aktuelles Markt-KGV (z.B. SPX ca. 22 in 2026)."""

    kgv_fair: float
    """Langfristiger fair value (Shiller-CAPE Mittel ueber 100J: ~16-18)."""

    alpha: float = 0.15
    """Jaehrliche Reversion-Speed [0..1]. Typisch 0.1-0.2.
    Bei alpha=0.15: ein Drittel der Overvaluation reduziert sich pro Jahr."""

    def __post_init__(self) -> None:
        if self.kgv_current <= 0:
            raise ValueError(f"kgv_current must be > 0, got {self.kgv_current}")
        if self.kgv_fair <= 0:
            raise ValueError(f"kgv_fair must be > 0, got {self.kgv_fair}")
        if not (0 <= self.alpha <= 1):
            raise ValueError(f"alpha must be in [0, 1], got {self.alpha}")

    def current_overvaluation_pct(self) -> float:
        """Returns Overvaluation in % gegen fair value.
        Positive: ueberbewertet, negative: unterbewertet."""
        return (self.kgv_current - self.kgv_fair) / self.kgv_fair * 100.0

    def expected_annual_return_adjustment_bps(self, horizon_years: int) -> float:
        """Erwartete jaehrliche Return-Anpassung in bps fuer gegebenen Horizont.

        Negative Werte = niedrigerer erwarteter Return (Overvaluation).
        Positive Werte = hoeherer erwarteter Return (Undervaluation).

        Formel:
            adj = alpha * (kgv_fair - kgv_current) / kgv_fair * 10000 * dampening(t)
            dampening(t) = max(0.3, 1 - 0.03*t)

        Begruendung dampening: Mean-Reversion findet im Long-Run statt;
        bei 30+ Jahren Horizont ist das Signal stark verwaessert weil
        meiste Reversion schon stattgefunden hat.
        """
        if horizon_years <= 0:
            return 0.0
        if self.alpha == 0:
            return 0.0

        # Basis-Adjustment: alpha * relative_undervaluation * 10000 bps
        relative_undervaluation = (self.kgv_fair - self.kgv_current) / self.kgv_fair
        base_adjustment_bps = self.alpha * relative_undervaluation * 10000.0

        # Dampening fuer lange Horizonte (Sandbox: minimum 30% Wirkung)
        dampening = max(0.3, 1.0 - 0.03 * horizon_years)

        return base_adjustment_bps * dampening

    def to_dict(self) -> dict:
        return {
            "kgv_current": float(self.kgv_current),
            "kgv_fair": float(self.kgv_fair),
            "alpha": float(self.alpha),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KGVMeanReversionModel":
        return cls(
            kgv_current=float(d["kgv_current"]),
            kgv_fair=float(d["kgv_fair"]),
            alpha=float(d.get("alpha", 0.15)),
        )
