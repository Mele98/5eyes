"""FXRateSource — liefert Wechselkurse zu CHF (Basis-Waehrung 5eyes).

Konvention: rate ist 'wie viele CHF pro 1 Einheit Fremdwaehrung'.
- EUR-Rate 0.95 → 1 EUR = 0.95 CHF
- USD-Rate 0.88 → 1 USD = 0.88 CHF

Cross-Rates werden via CHF berechnet (EUR → USD = EUR/CHF / USD/CHF).

Default-Rates sind empirische 2026-Mittelwerte. Phase 2 wird Berater
die Rates pflegen lassen (admin-UI + DB-Persistenz).

Spec: docs/planning/2026-05-17-sprint-9-multi-currency.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


# Default-Wechselkurse zu CHF (Stand 2026, approximative Mittelwerte).
# Format: {currency: rate_in_chf} d.h. 1 Einheit currency = rate CHF.
DEFAULT_FX_RATES: dict[str, float] = {
    "CHF": 1.0,        # Identity
    "EUR": 0.95,
    "USD": 0.88,
    "GBP": 1.10,
    "JPY": 0.0063,
    "CAD": 0.65,
    "AUD": 0.58,
    "SGD": 0.66,
    "HKD": 0.113,
    "CNY": 0.12,
    "SEK": 0.084,
    "NOK": 0.082,
    "DKK": 0.128,
}


@dataclass(frozen=True)
class FXRateSource:
    """Quelle fuer FX-Rates. Default: DEFAULT_FX_RATES (Hardcode 2026).

    Phase 2 wird das durch DB-getriebene Quelle ersetzt.
    """

    rates_in_chf: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_FX_RATES))
    """Rate je 1 Einheit Fremdwaehrung in CHF."""

    def __post_init__(self) -> None:
        for ccy, rate in self.rates_in_chf.items():
            if not isinstance(ccy, str) or len(ccy) != 3:
                raise ValueError(f"Invalid currency code '{ccy}' (must be 3 chars)")
            if not isinstance(rate, (int, float)) or rate <= 0:
                raise ValueError(f"Invalid rate for '{ccy}': {rate} (must be > 0)")
        if "CHF" not in self.rates_in_chf or self.rates_in_chf["CHF"] != 1.0:
            raise ValueError("CHF rate must be present and equal to 1.0 (base currency)")

    def rate_to_chf(self, currency: str) -> float:
        """Returns wie viele CHF 1 Einheit der Fremdwaehrung ist."""
        ccy = currency.upper().strip()
        if ccy not in self.rates_in_chf:
            raise ValueError(
                f"Unknown currency '{currency}'. Supported: {sorted(self.rates_in_chf.keys())}"
            )
        return float(self.rates_in_chf[ccy])

    def cross_rate(self, from_currency: str, to_currency: str) -> float:
        """Cross-Rate: wie viele to_currency-Einheiten ist 1 from_currency-Einheit.

        Formel: cross = rate_from / rate_to (beide in CHF)
        """
        from_chf = self.rate_to_chf(from_currency)
        to_chf = self.rate_to_chf(to_currency)
        return from_chf / to_chf

    def supported_currencies(self) -> tuple[str, ...]:
        return tuple(sorted(self.rates_in_chf.keys()))

    @classmethod
    def from_db(cls, db) -> "FXRateSource":
        """Lade FX-Rates aus der DB. Fallback auf Default-Rates wenn DB leer.

        Berater kann via Admin-Endpoint die Rates ueberschreiben — diese
        Klassen-Methode picked die aktuelle Version (is_current=1).
        Fehlt eine Major-Waehrung in der DB, wird der Default genutzt.
        """
        try:
            from models.fx_rate import FXRate
            rows = (
                db.query(FXRate)
                .filter(FXRate.is_current == 1, FXRate.valid_until.is_(None))
                .all()
            )
            if not rows:
                return cls()
            rates = dict(DEFAULT_FX_RATES)
            for row in rows:
                ccy = str(getattr(row, "currency", "") or "").upper().strip()
                if len(ccy) != 3:
                    continue
                rate_x10000 = int(getattr(row, "rate_x10000", 0) or 0)
                if rate_x10000 <= 0:
                    continue
                rates[ccy] = float(rate_x10000) / 10000.0
            # CHF muss 1.0 bleiben (auch wenn Berater es ueberschrieben hat)
            rates["CHF"] = 1.0
            return cls(rates_in_chf=rates)
        except Exception:
            return cls()
