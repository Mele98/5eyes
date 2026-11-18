"""FXRateSource — liefert Wechselkurse zu CHF (Basis-Waehrung Ares).

Konvention: rate ist 'wie viele CHF pro 1 Einheit Fremdwaehrung'.
- EUR-Rate 0.95 → 1 EUR = 0.95 CHF
- USD-Rate 0.88 → 1 USD = 0.88 CHF

Cross-Rates werden via CHF berechnet (EUR → USD = EUR/CHF / USD/CHF).

Default-Rates sind empirische 2026-Mittelwerte. Phase 2 wird Berater
die Rates pflegen lassen (admin-UI + DB-Persistenz).

Spec: docs/planning/2026-05-17-sprint-9-multi-currency.md
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping

from datetime import date, timedelta

from sqlalchemy import text

from core.evidence import SCHEME_V1_ASCII_STR_DEFAULT, evidence_hash
from core.presentation_rounding import CURRENCY_EXPONENTS, STORAGE_EXPONENT
from core.reason_codes import DomainError, ReasonCode


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


RATE_SCALE = 10_000


def half_up_div(numerator: int, denominator: int) -> int:
    """``ares-rounding/1``: half-up symmetrisch vom Nullpunkt weg (exakt)."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    quotient, remainder = divmod(abs(int(numerator)), int(denominator))
    if 2 * remainder >= denominator:
        quotient += 1
    return -quotient if numerator < 0 and quotient else quotient


def currency_exponent(currency: str) -> int:
    """ISO-4217-Minor-Unit-Exponent (G7-Tabelle); unbekannt -> ValueError."""
    code = str(currency or "").upper().strip()
    if code not in CURRENCY_EXPONENTS:
        raise ValueError(f"Kein Minor-Unit-Exponent fuer Waehrung {code or '(leer)'}")
    return CURRENCY_EXPONENTS[code]


def convert_storage_amount(
    amount_minor: int, *, rate_from_x10000: int, rate_to_x10000: int, target_currency: str,
) -> int:
    """CCX-P3-FX: Speicherbetrag (Faktor 100) -> Speicherbetrag der Zielwaehrung.

    Exakt ueber das ganzzahlige Kursverhaeltnis (x10000 zu CHF); Zielwert in
    ISO-Minor-Units = amount/100 * rate_from/rate_to * 10^e, gerundet nach
    ``ares-rounding/1`` (half-up symmetrisch), dann zurueck auf Exponent 2.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise ValueError("amount_minor must be an int")
    exponent = currency_exponent(target_currency)
    numerator = int(amount_minor) * int(rate_from_x10000) * 10 ** exponent
    denominator = 10 ** STORAGE_EXPONENT * int(rate_to_x10000)
    return half_up_div(numerator, denominator) * 10 ** (STORAGE_EXPONENT - exponent)


def rate_x10000(rate: float, currency: str) -> int:
    """Kurs (CHF je Einheit) als exakte Ganzzahl x10000; mehr als vier
    Dezimalen sind kein belegter Kurs dieser Quelle."""
    from_text = Decimal(repr(float(rate))) * RATE_SCALE
    if from_text != from_text.to_integral_value() or from_text <= 0:
        raise ValueError(f"FX-Kurs fuer {currency} ist nicht auf vier Dezimalen belegt: {rate!r}")
    return int(from_text)


# CCX-P3-FX (N-909-07): Frische eines Kurses. Default 5 Kalendertage, dieselbe
# Regel wie fuer Marktpreise (price_updater.summarize_price_quality,
# stale_after_days=5); je Tenant ueber ``tenants.fx_max_age_days`` (1..31)
# konfigurierbar.
DEFAULT_FX_MAX_AGE_DAYS = 5
DEFAULT_RATE_SOURCE = "Default"
FX_STATUS_OK = "OK"
FX_STATUS_MISSING = "MISSING"
FX_STATUS_STALE = "STALE"
FX_STATUS_MISMATCH = "MISMATCH"


class FxBasisError(DomainError):
    """Keine gueltige, gebundene FX-Basis (``CCX_FX_BASIS_*``)."""

    channel = "fx_basis"


def fx_status_reason(status: str) -> ReasonCode:
    """Katalogisierter Reason-Code eines Kursstatus (statisch aufloesbar)."""
    if status == FX_STATUS_STALE:
        return ReasonCode.CCX_FX_BASIS_STALE
    if status == FX_STATUS_MISMATCH:
        return ReasonCode.CCX_FX_BASIS_MISMATCH
    return ReasonCode.CCX_FX_BASIS_MISSING


def tenant_fx_max_age_days(db, tenant_id) -> int:
    """Tenant-Policy der Kursfrische; ohne Wert der dokumentierte Default 5."""
    if not tenant_id:
        return DEFAULT_FX_MAX_AGE_DAYS
    try:
        value = db.execute(
            text("SELECT fx_max_age_days FROM tenants WHERE id = :t"), {"t": str(tenant_id)},
        ).scalar()
    except Exception:  # noqa: BLE001 - Spalte fehlt (Altschema): Default
        return DEFAULT_FX_MAX_AGE_DAYS
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 31:
        return value
    return DEFAULT_FX_MAX_AGE_DAYS


def quote_status(source, observed_at, *, as_of: date, max_age_days: int) -> str:
    """Status eines beobachteten Kurses: Ersatzkurs/ohne Datum MISSING, nach dem
    Stichtag MISMATCH, aelter als die Frist STALE."""
    if str(source or DEFAULT_RATE_SOURCE) == DEFAULT_RATE_SOURCE:
        return FX_STATUS_MISSING
    raw = str(observed_at or "").strip()
    try:
        observed = date.fromisoformat(raw[:10]) if len(raw) >= 10 else None
    except ValueError:
        observed = None
    if observed is None:
        return FX_STATUS_MISSING
    if observed > as_of:
        return FX_STATUS_MISMATCH
    if observed < as_of - timedelta(days=int(max_age_days)):
        return FX_STATUS_STALE
    return FX_STATUS_OK


class StrictFXRateSource:
    """Kundenwirksame Kursquelle (CCX-P3-FX, N-909-01): dieselben Kurse wie die
    Modellquelle, aber nur belegte, frische DB-Kurse. Ein Ersatzkurs
    (``DEFAULT_FX_RATES`` bzw. Quelle ``Default``), ein fehlender, abgelaufener
    oder nach dem Stichtag beobachteter Kurs wirft ``FxBasisError`` mit
    ``CCX_FX_BASIS_*`` -- vor jeder Umrechnung, also vor Rendern/Archivieren.

    Die Kursstatus werden erst bei der ersten echten Fremdwaehrung geladen; ein
    reines Basiswaehrungsmandat loest keine zusaetzliche Query aus. Die
    Modell-Signatur (``canonical_model_signature``) bleibt die der Modellquelle,
    damit bestehende Kontext-Hashes stabil bleiben -- sie wird nur fuer strikt
    belegte Waehrungen ausgestellt."""

    def __init__(self, model: "FXRateSource", db, *, tenant_id=None, as_of: date | None = None) -> None:
        self.model = model
        self._db = db
        self._tenant_id = tenant_id
        self._as_of = as_of
        self._statuses: dict[str, str] | None = None

    def __deepcopy__(self, memo):
        """Wertkopie wie bei ``FXRateSource``: Modell und Kursstatus werden
        kopiert, die DB-Session ist eine Ressource und wird geteilt (eine
        Session ist nicht kopierbar)."""
        import copy as _copy

        clone = StrictFXRateSource(
            _copy.deepcopy(self.model, memo), self._db,
            tenant_id=self._tenant_id, as_of=self._as_of,
        )
        clone._statuses = dict(self._statuses) if self._statuses is not None else None
        memo[id(self)] = clone
        return clone

    @property
    def basis_id(self) -> str:
        return self.model.basis_id

    @property
    def uses_versioned_defaults(self) -> bool:
        return self.model.uses_versioned_defaults

    @property
    def rates_in_chf(self):
        return self.model.rates_in_chf

    def statuses(self) -> dict[str, str]:
        if self._statuses is None:
            as_of = self._as_of or date.today()
            max_age = tenant_fx_max_age_days(self._db, self._tenant_id)
            rows = self._db.execute(text(
                "SELECT currency, source, valid_from FROM fx_rates "
                "WHERE is_current = 1 AND valid_until IS NULL"
            )).all()
            statuses: dict[str, str] = {}
            for currency, source, valid_from in rows:
                code = str(currency or "").upper().strip()
                status = quote_status(source, valid_from, as_of=as_of, max_age_days=max_age)
                statuses[code] = FX_STATUS_MISMATCH if code in statuses else status
            self._statuses = statuses
        return self._statuses

    def require(self, currency: str) -> None:
        code = str(currency or "").upper().strip()
        if code == "CHF":
            return
        if code and code not in self.model.rates_in_chf:
            # Unbekannter Code: wie die Modellquelle ein Eingabefehler (ValueError),
            # nie ein Kurs -- bestehende fail-closed-Pfade bleiben unveraendert.
            raise ValueError(f"Unbekannte Waehrung: {code}")
        status = self.statuses().get(code, FX_STATUS_MISSING) if code else FX_STATUS_MISSING
        if status != FX_STATUS_OK:
            raise FxBasisError(
                fx_status_reason(status),
                f"Fuer {code or '(ohne Waehrung)'} liegt kein belegter, aktueller Kurs vor ({status}); "
                "Ersatzkurse werden nie kundenwirksam.",
                extra={"currencies": [code], "fx_status": status},
            )

    def rate_to_chf(self, currency: str) -> float:
        self.require(currency)
        return self.model.rate_to_chf(currency)

    def cross_rate(self, from_currency: str, to_currency: str) -> float:
        source = str(from_currency or "").upper().strip()
        target = str(to_currency or "").upper().strip()
        if source and source == target:
            # Identitaet: keine Umrechnung, also kein Kurs noetig (ein reines
            # EUR-Mandat braucht keinen EUR/CHF-Kurs). Die Modellquelle prueft
            # weiterhin, dass der Code bekannt ist, und liefert exakt 1.0.
            return self.model.cross_rate(source, target)
        self.require(source)
        self.require(target)
        return self.model.cross_rate(source, target)

    def convert_storage_amount(self, amount_minor: int, source_currency: str, target_currency: str) -> int:
        source = str(source_currency or "").upper().strip()
        target = str(target_currency or "").upper().strip()
        amount = int(amount_minor or 0)
        if source == target or amount == 0:
            return amount
        self.require(source)
        self.require(target)
        return self.model.convert_storage_amount(amount, source, target)

    def supported_currencies(self) -> tuple[str, ...]:
        return tuple(sorted(c for c, s in self.statuses().items() if s == FX_STATUS_OK) + ["CHF"])

    def canonical_model_signature(self, currencies, *, target_currency: str) -> dict[str, object]:
        target = str(target_currency or "").upper().strip()
        needed = {str(c or "").upper().strip() for c in currencies} | {target}
        if needed - {target}:
            for currency in sorted(needed):
                self.require(currency)
        return self.model.canonical_model_signature(currencies, target_currency=target_currency)


class FXRateLoadError(ValueError):
    """The effective FX basis required by a model run cannot be established."""


def _fingerprint(payload: object) -> str:
    return evidence_hash(payload, scheme=SCHEME_V1_ASCII_STR_DEFAULT)


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

    def convert_storage_amount(self, amount_minor: int, source_currency: str, target_currency: str) -> int:
        """CCX-P3-FX: exakte Konversion eines Speicherbetrags (gleiche Regel wie
        ``services.fx_basis.FxBasis.convert``); unbekannte Waehrung -> ValueError."""
        source = str(source_currency or "").upper().strip()
        target = str(target_currency or "").upper().strip()
        amount = int(amount_minor or 0)
        if amount == 0 or source == target:
            return amount
        return convert_storage_amount(
            amount,
            rate_from_x10000=rate_x10000(self.rate_to_chf(source), source),
            rate_to_x10000=rate_x10000(self.rate_to_chf(target), target),
            target_currency=target,
        )

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
    def from_db_strict_for_model(cls, db, *, tenant_id=None, as_of: date | None = None) -> StrictFXRateSource:
        """Kundenwirksame Modellquelle (siehe ``StrictFXRateSource``)."""
        return StrictFXRateSource(cls.from_db_for_model(db), db, tenant_id=tenant_id, as_of=as_of)

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
