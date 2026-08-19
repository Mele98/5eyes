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

import hashlib
import json
import math
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

# A hard-coded rate set is only admissible in model calculations if its exact
# version is exposed to (and therefore can be included in) the model-input
# hash.  Changing any default rate requires a new version identifier.
DEFAULT_FX_RATE_SET_VERSION = "default_fx_rates_2026_v1"


class FXRateLoadError(ValueError):
    """The effective FX basis required by a model run cannot be established."""


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class FXRateSource:
    """Quelle fuer FX-Rates. Default: DEFAULT_FX_RATES (Hardcode 2026).

    Phase 2 wird das durch DB-getriebene Quelle ersetzt.
    """

    rates_in_chf: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_FX_RATES))
    """Rate je 1 Einheit Fremdwaehrung in CHF."""

    basis_id: str = ""
    """Stable provenance identifier suitable for model-input hashing."""

    uses_versioned_defaults: bool = False
    """Whether at least one rate originates from the versioned default set."""

    def __post_init__(self) -> None:
        for ccy, rate in self.rates_in_chf.items():
            if not isinstance(ccy, str) or len(ccy) != 3:
                raise ValueError(f"Invalid currency code '{ccy}' (must be 3 chars)")
            if (
                isinstance(rate, bool)
                or not isinstance(rate, (int, float))
                or not math.isfinite(float(rate))
                or rate <= 0
            ):
                raise ValueError(f"Invalid rate for '{ccy}': {rate} (must be > 0)")
        if "CHF" not in self.rates_in_chf or self.rates_in_chf["CHF"] != 1.0:
            raise ValueError("CHF rate must be present and equal to 1.0 (base currency)")
        if not self.basis_id:
            exact_rates = {
                str(currency): float(rate)
                for currency, rate in sorted(self.rates_in_chf.items())
            }
            if exact_rates == DEFAULT_FX_RATES:
                object.__setattr__(self, "basis_id", DEFAULT_FX_RATE_SET_VERSION)
                object.__setattr__(self, "uses_versioned_defaults", True)
            else:
                object.__setattr__(
                    self,
                    "basis_id",
                    f"explicit_fx_rates:{_fingerprint(exact_rates)}",
                )

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

    def canonical_model_signature(
        self,
        currencies: list[str] | tuple[str, ...] | set[str],
        *,
        target_currency: str,
    ) -> dict[str, object]:
        """Return provenance plus exact effective cross-rates for hashing.

        The source identifier alone is not sufficient: this signature also
        commits the exact conversion factors used by the requested model
        inputs.  Unknown/non-finite rates fail closed.
        """
        target = str(target_currency or "").upper().strip()
        if not target:
            raise ValueError("Target currency is required for FX signature")
        effective_rates: list[list[object]] = []
        for currency in sorted(
            {str(value or "").upper().strip() for value in currencies} | {target}
        ):
            if not currency:
                raise ValueError("Empty currency cannot be signed")
            rate = float(self.cross_rate(currency, target))
            if not math.isfinite(rate) or rate <= 0.0:
                raise ValueError(
                    f"Invalid effective FX rate for {currency}->{target}: {rate}"
                )
            effective_rates.append(
                [currency, int(round(rate * 100_000_000))]
            )
        return {
            "basis_id": self.basis_id,
            "uses_versioned_defaults": bool(self.uses_versioned_defaults),
            "target_currency": target,
            "effective_rates_x1e8": effective_rates,
        }

    @classmethod
    def from_db_for_model(cls, db) -> "FXRateSource":
        """Load the effective, auditable FX basis for a model calculation.

        Empty tables deliberately use ``DEFAULT_FX_RATE_SET_VERSION``.  A DB
        error, malformed active row, duplicate active currency, or invalid
        rate is a model-input error and is never replaced silently.
        """
        try:
            from models.fx_rate import FXRate

            rows = (
                db.query(FXRate)
                .filter(FXRate.is_current == 1, FXRate.valid_until.is_(None))
                .all()
            )
        except Exception as exc:  # noqa: BLE001 - stable domain translation
            raise FXRateLoadError(
                "Die effektiven FX-Rates konnten nicht aus der Datenbank "
                "geladen werden."
            ) from exc

        if not rows:
            return cls(
                basis_id=DEFAULT_FX_RATE_SET_VERSION,
                uses_versioned_defaults=True,
            )

        rates = dict(DEFAULT_FX_RATES)
        seen: set[str] = set()
        canonical_rows: list[dict[str, object]] = []
        for row in rows:
            ccy = str(getattr(row, "currency", "") or "").upper().strip()
            raw_rate = getattr(row, "rate_x10000", None)
            if (
                len(ccy) != 3
                or isinstance(raw_rate, bool)
                or not isinstance(raw_rate, int)
                or raw_rate <= 0
                or raw_rate > 10_000_000  # API contract: rate <= 1000
                or (ccy == "CHF" and raw_rate != 10_000)
            ):
                raise FXRateLoadError(
                    "Eine aktive FX-Rate ist ungueltig; die Modellrechnung "
                    "wird nicht mit einem Default-Kurs fortgesetzt."
                )
            if ccy in seen:
                raise FXRateLoadError(
                    f"Mehrere aktive FX-Rates fuer {ccy}; die effektive "
                    "Modellbasis ist nicht eindeutig."
                )
            seen.add(ccy)
            rates[ccy] = raw_rate / 10000.0
            canonical_rows.append(
                {
                    "id": str(getattr(row, "id", "") or ""),
                    "currency": ccy,
                    "rate_x10000": raw_rate,
                    "valid_from": str(getattr(row, "valid_from", "") or ""),
                    "source": str(getattr(row, "source", "") or ""),
                }
            )
        # CHF is the unit basis and cannot be changed by a market-data row.
        rates["CHF"] = 1.0
        basis_payload = {
            "default_rate_set_version": DEFAULT_FX_RATE_SET_VERSION,
            "active_db_rows": sorted(
                canonical_rows,
                key=lambda row: (str(row["currency"]), str(row["id"])),
            ),
        }
        return cls(
            rates_in_chf=rates,
            basis_id=(
                f"db_current_plus_{DEFAULT_FX_RATE_SET_VERSION}:"
                f"{_fingerprint(basis_payload)}"
            ),
            uses_versioned_defaults=(set(rates) - seen - {"CHF"}) != set(),
        )

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
