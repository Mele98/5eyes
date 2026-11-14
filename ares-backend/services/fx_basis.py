"""CCX-P3-FX: eine gebundene FX-Basis je Berechnung (Vertrag 2026-11-13 §6 Nachtrag P3-FX).

Grundregeln
-----------
* Betrag und Waehrung bleiben untrennbar. Eine Summe ueber Betraege
  verschiedener Waehrungen entsteht nur aus zeilenweise konvertierten
  Minor-Unit-Werten derselben Basis (``FxBasis.convert``) -- nie vor der
  Konversion.
* Die Basis ist unveraenderlich: Zielwaehrung, Bewertungsstichtag und je
  benoetigter Waehrung Kurs (``rate_x10000`` zu CHF), Quelle, Beobachtungs-
  zeitpunkt und Kurs-ID. ``fx_basis_hash`` ist der domaenenseparierte
  Kind-Hash (``.../fx-basis``) ueber genau diese Felder.
* Fehlend ist fehlend: keine aktive Zeile **oder** eine Zeile mit Quelle
  ``Default`` (Ersatzkurs, ``DEFAULT_FX_RATES``) ergibt
  ``CCX_FX_BASIS_MISSING`` -- ein Ersatzkurs wird nie kundenwirksam.
  Ein Kurs, der nach dem Stichtag beobachtet wurde, ist eine zeitlich
  inkonsistente Basis (``CCX_FX_BASIS_MISMATCH``); ein Kurs, der aelter als
  ``MARKET_DATA_STALE_AFTER_DAYS`` Kalendertage vor dem Stichtag ist,
  ist abgelaufen (``CCX_FX_BASIS_STALE``).
* Konversion exakt mit Ganzzahl-Arithmetik ueber das rationale
  Kursverhaeltnis ``rate_from / rate_to`` (beide x10000 zu CHF, also
  verlustfrei aus der DB), Rundung nach ``ares-rounding/1`` (half-up,
  symmetrisch vom Nullpunkt weg) auf den ISO-Exponenten der Zielwaehrung
  (JPY 0, sonst 2) und Rueckskalierung auf den Speicher-Exponenten 2.

Die Kurse in Tests sind synthetische Testvektoren, keine Fachwerte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, Iterable, Mapping

from core.advisory_envelope_codec import child_hash
from core.presentation_rounding import CURRENCY_EXPONENTS
from core.reason_codes import DomainError, ReasonCode
from models.fx_rate import FXRate
from services.currency.fx_rates import (
    DEFAULT_FX_MAX_AGE_DAYS,
    FxBasisError,
    FXRateSource,
    convert_storage_amount,
    half_up_div,
    quote_status,
    tenant_fx_max_age_days,
)

FX_BASIS_KIND = "fx-basis"
FX_BASIS_SCHEMA = "ares/fx-basis/1"
FX_BASE_CURRENCY = "CHF"
CHF_UNIT_X10000 = 10_000
DEFAULT_SOURCE = "Default"

# Dieselbe Frischeregel wie fuer Marktpreise (price_updater.summarize_price_quality,
# stale_after_days=5; Handelsliste/Depot-Snapshot): ein Kurs, der mehr als fuenf
# Kalendertage vor dem Bewertungsstichtag beobachtet wurde, ist abgelaufen.
MARKET_DATA_STALE_AFTER_DAYS = DEFAULT_FX_MAX_AGE_DAYS  # Tenant-Policy, Default 5

STATUS_OK = "OK"
STATUS_MISSING = "MISSING"
STATUS_STALE = "STALE"
STATUS_MISMATCH = "MISMATCH"



def status_reason(status: str) -> ReasonCode:
    """Katalogisierter Reason-Code eines Kursstatus (statisch aufloesbar)."""
    if status == STATUS_STALE:
        return ReasonCode.CCX_FX_BASIS_STALE
    if status == STATUS_MISMATCH:
        return ReasonCode.CCX_FX_BASIS_MISMATCH
    return ReasonCode.CCX_FX_BASIS_MISSING


# FxBasisError lebt in services.currency.fx_rates (auch die strikte
# Engine-Quelle wirft ihn) und wird hier re-exportiert.


def normalize_currency(value: Any) -> str:
    return str(value or "").upper().strip()


def currency_exponent(currency: str) -> int:
    """ISO-4217-Minor-Unit-Exponent; unbekannte Waehrung ist kein Rechenfall."""
    code = normalize_currency(currency)
    if code not in CURRENCY_EXPONENTS:
        raise FxBasisError(
            ReasonCode.CCX_FX_BASIS_MISSING,
            f"Fuer die Waehrung {code or '(leer)'} ist kein Minor-Unit-Exponent hinterlegt.",
            extra={"currencies": [code]},
        )
    return CURRENCY_EXPONENTS[code]


def _rate_text(numerator: int, denominator: int) -> str:
    with localcontext() as ctx:
        ctx.prec = 34
        value = Decimal(numerator) / Decimal(denominator)
        return format(value.quantize(Decimal("0.000000000001")), "f")


def _date_part(value: Any) -> date | None:
    raw = str(value or "").strip()
    if len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


@dataclass(frozen=True)
class FxQuote:
    """Ein beobachteter Kurs: 1 Einheit ``currency`` = rate_x10000/10000 CHF."""

    currency: str
    rate_x10000: int
    source: str
    observed_at: str
    rate_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "rate_x10000": int(self.rate_x10000),
            "source": self.source,
            "observed_at": self.observed_at,
            "rate_id": self.rate_id,
        }


@dataclass(frozen=True)
class ConversionLine:
    """Provenienz je Originalbetrag (Vertrag P3-FX)."""

    source_currency: str
    source_amount_minor: int
    target_currency: str
    converted_amount_minor: int
    fx_rate: str
    fx_rate_ratio: str
    fx_rate_ppm: int
    fx_source: str
    source_observed_at: str | None
    fx_basis_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_currency": self.source_currency,
            "source_amount_minor": self.source_amount_minor,
            "target_currency": self.target_currency,
            "converted_amount_minor": self.converted_amount_minor,
            "fx_rate": self.fx_rate,
            "fx_rate_ratio": self.fx_rate_ratio,
            "fx_rate_ppm": self.fx_rate_ppm,
            "fx_source": self.fx_source,
            "source_observed_at": self.source_observed_at,
            "fx_basis_hash": self.fx_basis_hash,
        }


def _canonical_basis_bytes(target_currency: str, as_of: str, quotes: Iterable[FxQuote]) -> bytes:
    body = {
        "schema": FX_BASIS_SCHEMA,
        "target_currency": target_currency,
        "as_of": as_of,
        "base_currency": FX_BASE_CURRENCY,
        "quotes": [q.as_dict() for q in sorted(quotes, key=lambda q: q.currency)],
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def compute_fx_basis_hash(target_currency: str, as_of: str, quotes: Iterable[FxQuote]) -> str:
    return child_hash(FX_BASIS_KIND, _canonical_basis_bytes(target_currency, as_of, quotes))


@dataclass(frozen=True)
class FxBasis:
    """Unveraenderliche FX-Basis einer Berechnung (genau eine Zielwaehrung)."""

    target_currency: str
    as_of: str
    quotes: tuple[FxQuote, ...]
    fx_basis_hash: str
    statuses: Mapping[str, str] = field(default_factory=dict)

    def quote(self, currency: str) -> FxQuote | None:
        code = normalize_currency(currency)
        for item in self.quotes:
            if item.currency == code:
                return item
        return None

    def status(self, currency: str) -> str:
        """Status des Kurses von ``currency`` (CHF ist die Einheit). Die
        Zielwaehrung hat einen eigenen Status (N-909-04): ein abgelaufener
        EUR-Kurs eines EUR-Mandats ist STALE, nicht MISSING."""
        code = normalize_currency(currency)
        if code == FX_BASE_CURRENCY:
            return STATUS_OK
        if code == self.target_currency and code not in self.statuses:
            return STATUS_OK  # nur Basiswaehrung im Spiel: kein Kurs noetig
        return self.statuses.get(code, STATUS_MISSING)

    def _rate_x10000(self, currency: str) -> int:
        if currency == FX_BASE_CURRENCY:
            return CHF_UNIT_X10000
        quote = self.quote(currency)
        if quote is None:
            raise FxBasisError(
                ReasonCode.CCX_FX_BASIS_MISSING,
                f"Fuer {currency} liegt kein belegter Kurs vor; ohne Kurs wird nicht addiert.",
                extra={"currencies": [currency], "fx_basis_hash": self.fx_basis_hash},
            )
        return int(quote.rate_x10000)

    def convert(self, amount_minor: int, source_currency: Any) -> ConversionLine:
        """Konvertiert genau einen Originalbetrag in die Zielwaehrung (fail-closed)."""
        source = normalize_currency(source_currency)
        target = self.target_currency
        if not source:
            raise FxBasisError(
                ReasonCode.CCX_FX_BASIS_MISSING,
                "Ein Betrag ohne Waehrung kann nicht umgerechnet werden; die Waehrung wird nie geraten.",
                extra={"currencies": [""], "fx_basis_hash": self.fx_basis_hash},
            )
        amount = int(amount_minor or 0)
        if source == target:
            currency_exponent(source)
            return ConversionLine(
                source, amount, target, amount, "1.000000000000", "1/1", 1_000_000,
                "identity", None, self.fx_basis_hash,
            )
        status = self.status(source)
        if status != STATUS_OK:
            raise FxBasisError(
                status_reason(status),
                f"Der Kurs {source}/{target} ist nicht verwendbar ({status}).",
                extra={"currencies": [source], "fx_basis_hash": self.fx_basis_hash},
            )
        if target != FX_BASE_CURRENCY and self.statuses.get(target, STATUS_MISSING) != STATUS_OK:
            pivot = self.statuses.get(target, STATUS_MISSING)
            raise FxBasisError(
                status_reason(pivot),
                f"Der Kurs der Zielwaehrung {target} ist nicht verwendbar ({pivot}).",
                extra={"currencies": [target], "fx_basis_hash": self.fx_basis_hash},
            )
        rate_from = self._rate_x10000(source)
        rate_to = self._rate_x10000(target)
        converted = convert_storage_amount(
            amount, rate_from_x10000=rate_from, rate_to_x10000=rate_to, target_currency=target,
        )
        quotes = [q for q in (self.quote(source), self.quote(target)) if q is not None]
        observed = min(q.observed_at for q in quotes) if quotes else None
        return ConversionLine(
            source_currency=source,
            source_amount_minor=amount,
            target_currency=target,
            converted_amount_minor=converted,
            fx_rate=_rate_text(rate_from, rate_to),
            fx_rate_ratio=f"{rate_from}/{rate_to}",
            fx_rate_ppm=half_up_div(rate_from * 1_000_000, rate_to),
            fx_source=",".join(sorted({q.source for q in quotes})) or "identity",
            source_observed_at=observed,
            fx_basis_hash=self.fx_basis_hash,
        )

    def require_convertible(self, currencies: Iterable[Any]) -> None:
        """Jede Waehrung ist in die Zielwaehrung konvertierbar -- sonst der
        typisierte ``FxBasisError`` der ersten blockierten Waehrung."""
        for currency in sorted({normalize_currency(c) for c in currencies}):
            self.convert(0, currency)

    # Duck-Typing als strikte ``FXRateSource`` fuer bestehende Engine-Helfer
    # (``convert_with_source``): nur verwendbare, gebundene Kurse.
    def rate_to_chf(self, currency: str) -> float:
        code = normalize_currency(currency)
        if code == FX_BASE_CURRENCY:
            return 1.0
        if code != self.target_currency and self.status(code) != STATUS_OK:
            raise ValueError(f"Kein verwendbarer Kurs fuer {code} ({self.status(code)}).")
        return self._rate_x10000(code) / CHF_UNIT_X10000

    def cross_rate(self, from_currency: str, to_currency: str) -> float:
        return self.rate_to_chf(from_currency) / self.rate_to_chf(to_currency)

    def convert_storage_amount(self, amount_minor: int, source_currency: str, target_currency: str) -> int:
        """Duck-Typing zu ``FXRateSource.convert_storage_amount`` (strikt)."""
        if normalize_currency(target_currency) != self.target_currency:
            raise ValueError("FxBasis: andere Zielwaehrung als die gebundene Basis")
        try:
            return self.convert(int(amount_minor or 0), source_currency).converted_amount_minor
        except FxBasisError as exc:
            raise ValueError(exc.message) from exc

    def canonical_model_signature(self, currencies: Iterable[Any], *, target_currency: str) -> dict[str, Any]:
        """Wie ``FXRateSource.canonical_model_signature`` -- Provenienz ist hier
        die gebundene Basis (``fx_basis_hash``), nie ein Ersatzkurs."""
        target = normalize_currency(target_currency)
        effective: list[list[Any]] = []
        for currency in sorted({normalize_currency(c) for c in currencies} | {target}):
            self.require_convertible([currency, target])
            effective.append([
                currency,
                half_up_div(self._rate_x10000(currency) * 100_000_000, self._rate_x10000(target)),
            ])
        return {
            "basis_id": f"ccx_fx_basis:{self.fx_basis_hash}",
            "uses_versioned_defaults": False,
            "target_currency": target,
            "effective_rates_x1e8": effective,
        }

    def blocked_currencies(self, currencies: Iterable[Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        for currency in currencies:
            code = normalize_currency(currency)
            if not code:
                out[""] = STATUS_MISSING
                continue
            if code == self.target_currency:
                continue
            for needed in (code, self.target_currency):
                if needed == FX_BASE_CURRENCY:
                    continue
                status = self.status(needed) if needed != self.target_currency else self.statuses.get(
                    needed, STATUS_MISSING)
                if status != STATUS_OK:
                    out[needed] = status
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": FX_BASIS_SCHEMA,
            "target_currency": self.target_currency,
            "as_of": self.as_of,
            "fx_basis_hash": self.fx_basis_hash,
            "quotes": [q.as_dict() for q in self.quotes],
            "statuses": dict(sorted(self.statuses.items())),
        }


def _quote_status(quote: FxQuote | None, as_of: date, max_age_days: int = MARKET_DATA_STALE_AFTER_DAYS) -> str:
    if quote is None:
        return STATUS_MISSING
    return quote_status(quote.source, quote.observed_at, as_of=as_of, max_age_days=max_age_days)


def build_fx_basis(
    target_currency: Any,
    needed_currencies: Iterable[Any],
    quotes_by_currency: Mapping[str, FxQuote | None],
    *,
    as_of: date,
    max_age_days: int = MARKET_DATA_STALE_AFTER_DAYS,
) -> FxBasis:
    """Basis ueber alle benoetigten Waehrungen. Nicht verwendbare Kurse werden
    nicht verworfen, sondern mit Status gefuehrt -- ``convert`` blockiert dann
    typisiert. Nur verwendbare Kurse gehen in den Hash ein."""
    target = normalize_currency(target_currency)
    currency_exponent(target)
    needed = {normalize_currency(c) for c in needed_currencies if normalize_currency(c)}
    pivots = (needed | {target}) - {FX_BASE_CURRENCY}
    if needed <= {target}:
        pivots = set()
    statuses: dict[str, str] = {}
    usable: list[FxQuote] = []
    for currency in sorted(pivots):
        quote = quotes_by_currency.get(currency)
        status = _quote_status(quote, as_of, max_age_days)
        statuses[currency] = status
        if status == STATUS_OK and quote is not None:
            usable.append(quote)
    as_of_text = as_of.isoformat()
    return FxBasis(
        target_currency=target,
        as_of=as_of_text,
        quotes=tuple(sorted(usable, key=lambda q: q.currency)),
        fx_basis_hash=compute_fx_basis_hash(target, as_of_text, usable),
        statuses=statuses,
    )


def load_quotes(db: Any, currencies: Iterable[Any]) -> dict[str, FxQuote | None]:
    """Aktive FX-Zeilen je Waehrung; mehrere aktive Zeilen sind keine Basis."""
    wanted = sorted({normalize_currency(c) for c in currencies} - {"", FX_BASE_CURRENCY})
    if not wanted:
        return {}
    rows = (
        db.query(FXRate)
        .filter(FXRate.currency.in_(wanted), FXRate.is_current == 1, FXRate.valid_until.is_(None))
        .all()
    )
    out: dict[str, FxQuote | None] = {currency: None for currency in wanted}
    seen: set[str] = set()
    for row in rows:
        currency = normalize_currency(row.currency)
        rate = getattr(row, "rate_x10000", None)
        if currency in seen:
            raise FxBasisError(
                ReasonCode.CCX_FX_BASIS_MISMATCH,
                f"Mehrere aktive Kurse fuer {currency}; die FX-Basis ist nicht eindeutig.",
                extra={"currencies": [currency]},
            )
        seen.add(currency)
        if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
            continue
        out[currency] = FxQuote(
            currency=currency,
            rate_x10000=int(rate),
            source=str(getattr(row, "source", "") or DEFAULT_SOURCE),
            observed_at=str(getattr(row, "valid_from", "") or ""),
            rate_id=str(getattr(row, "id", "") or ""),
        )
    return out


def resolve_as_of(as_of: date | datetime | str | None = None) -> date:
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    parsed = _date_part(as_of)
    if parsed is not None:
        return parsed
    # Bewusst die Wanduhr (nicht der gebundene Strategie-Stichtag): die
    # aktiven Kurse gelten heute; ein Reprint mit altem Stichtag waere sonst
    # gegen jeden spaeter erfassten Kurs "zeitlich inkonsistent".
    return date.today()


def load_fx_basis(
    db: Any, target_currency: Any, needed_currencies: Iterable[Any], *, as_of: Any = None,
    tenant_id: Any = None,
) -> FxBasis:
    """Strikte Basis; die Kursfrische folgt der Tenant-Policy (Default 5 Tage).
    Ohne Fremdwaehrung keine Query."""
    needed = [normalize_currency(c) for c in needed_currencies]
    target = normalize_currency(target_currency)
    foreign = (set(needed) | {target}) - {"", FX_BASE_CURRENCY}
    if set(needed) - {""} <= {target}:
        foreign = set()
    max_age = tenant_fx_max_age_days(db, tenant_id) if foreign else DEFAULT_FX_MAX_AGE_DAYS
    return build_fx_basis(
        target, needed, load_quotes(db, set(needed) | {target}), as_of=resolve_as_of(as_of),
        max_age_days=max_age,
    )


def assert_same_fx_basis(expected_hash: str | None, basis: FxBasis) -> None:
    """Eine Aussage darf nur eine Basis tragen: abweichend -> MISMATCH."""
    if expected_hash and expected_hash != basis.fx_basis_hash:
        raise FxBasisError(
            ReasonCode.CCX_FX_BASIS_MISMATCH,
            "Die FX-Basis hat sich gegenueber der gebundenen Basis geaendert.",
            extra={"expected_fx_basis_hash": expected_hash, "fx_basis_hash": basis.fx_basis_hash},
        )


def convert_sum(basis: FxBasis, items: Iterable[tuple[int, Any]]) -> tuple[int, list[ConversionLine]]:
    """Zeilenweise konvertieren, erst danach summieren."""
    lines = [basis.convert(int(amount or 0), currency) for amount, currency in items]
    return sum(line.converted_amount_minor for line in lines), lines


__all__ = [
    "ConversionLine",
    "FxBasis",
    "FxBasisError",
    "FxQuote",
    "MARKET_DATA_STALE_AFTER_DAYS",
    "assert_same_fx_basis",
    "build_fx_basis",
    "compute_fx_basis_hash",
    "convert_storage_amount",
    "convert_sum",
    "convert_with_source",
    "strict_model_fx_source",
    "load_fx_basis",
    "load_quotes",
]



def convert_with_source(amount_minor: int, source_currency: Any, target_currency: Any, fx_source: Any) -> int:
    """Konversion ueber eine Kursquelle (Modell-``FXRateSource`` oder strikte
    ``FxBasis``) -- dieselbe exakte Regel."""
    return fx_source.convert_storage_amount(
        int(amount_minor or 0), normalize_currency(source_currency), normalize_currency(target_currency),
    )


def strict_model_fx_source(db: Any, *, tenant_id: Any = None):
    """Kundenwirksame Kursquelle fuer Engine-Spiegel im Bericht (strikt, typisiert)."""
    return FXRateSource.from_db_strict_for_model(db, tenant_id=tenant_id)
