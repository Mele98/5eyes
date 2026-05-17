"""RiskPremiumModel — Expected-Return = risk_free + Risiko-Premium.

Empirische Grundlage (CAPM-Erweiterung):
- Asset-Returns lassen sich zerlegen in: risikofreier Zins + Risiko-Premium
- Bei Zinsaenderungen aendert sich der absolute Return, das Premium bleibt
  vergleichsweise stabil
- Real Estate: typisch 150-250 bps Premium ueber Cash-Yield
- Alternatives (Gold, Liquid Alts): typisch 200-400 bps

Modell (vereinfacht):

    expected_return_bps = risk_free_bps + premium_bps

Wobei `risk_free_bps` typischerweise aus dem kurzen Ende der Yield-Curve
(short_rate aus Nelson-Siegel oder Cash-Yield) kommt.

Spec: docs/planning/2026-05-17-sprint-8-risk-premium.md
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPremiumModel:
    """Risiko-Premium ueber risikofreiem Zins.

    Beispiel:
        >>> model = RiskPremiumModel(asset_class="real_estate", premium_bps=200)
        >>> model.expected_return_bps(risk_free_bps=300)  # 3% RF + 2% Premium
        500.0
        >>> model.expected_return_bps(risk_free_bps=50)   # bei Niedrigzins
        250.0
    """

    asset_class: str
    """Asset-Klasse-Identifier: 'real_estate', 'alternatives', 'high_yield', ..."""

    premium_bps: float
    """Risiko-Premium in bps ueber risk_free_rate. Typische Werte:
    - real_estate: 150-250 bps
    - alternatives (Gold, Liquid Alts): 200-400 bps
    - High-Yield Bonds: 300-500 bps"""

    def __post_init__(self) -> None:
        if not isinstance(self.asset_class, str) or not self.asset_class:
            raise ValueError("asset_class must be a non-empty string")
        # Negative Premia sind theoretisch denkbar (Convenience-Yield, Insurance)
        # aber praktisch ungewoehnlich — wir erlauben sie aber.

    def expected_return_bps(self, risk_free_bps: float) -> float:
        """Returns expected Return = risk_free + premium in bps.

        risk_free_bps: typisch aus Nelson-Siegel short_rate oder Cash-Yield.
        """
        return float(risk_free_bps) + float(self.premium_bps)

    def to_dict(self) -> dict:
        return {
            "asset_class": self.asset_class,
            "premium_bps": float(self.premium_bps),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RiskPremiumModel":
        return cls(
            asset_class=str(d["asset_class"]),
            premium_bps=float(d["premium_bps"]),
        )
