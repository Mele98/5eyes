"""G7 -- gemeinsamer Rundungsformatter fuer Kundenevidenz (App + PDF).

Vertrag (Policy ``ares-rounding/1``), identisch umgesetzt in

* ``ares-backend/services/presentation_rounding.py``  (dieses Modul: PDF/Backend)
* ``ares-desktop/frontend/presentation-rounding.js``   (Classic-App, Standalone-Modul)
* ``ares-desktop/frontend/reporting/src/lib/presentationRounding.ts`` (React)

und gekoppelt ueber EINEN Golden-Vektor
``ares-backend/services/presentation_rounding_golden.json``, den die Python-,
Classic- und React-Tests lesen (Abweichung = roter Test).

Regeln
------
1. Rechenwerte bleiben Integer-bps bzw. Integer-Minor-Units. Gerundet wird
   nur hier, an der Praesentationsgrenze. Dieses Modul liest Werte, es
   aendert keine Fachwerte, Schwellen, Restriktionen oder Persistenz.
2. Rundung: Dezimalarithmetik, ``ROUND_HALF_UP`` symmetrisch (Gleichstand
   vom Nullpunkt weg): ``+12.25 -> +12.3`` und ``-12.25 -> -12.3``. Kein
   Float-``format``/``round`` (Banker's Rounding), kein ``toFixed``.
   Gleitkomma-Eingaben werden ueber ihre kuerzeste Round-trip-Darstellung
   (Python ``repr`` = JS ``String(n)``) gelesen, nie ueber die Binaerexpansion
   -- so ergibt ``12.35`` immer ``12.4`` (``toFixed``/``format`` lieferten 12.3).
3. Ein auf null gerundeter Wert traegt kein Vorzeichen (``-4 bps -> 0.0 %``).
4. Tausendertrennung: gerades Apostroph U+0027 (``1'250'000``), Dezimalpunkt.
5. "Keine Angabe" (None/leer/NaN/inf) -> ``NO_VALUE`` (U+2014); null ist ein
   Wert (``0.0 %``, ``CHF 0``). Beides wird nie vermischt.
6. Prozent: ``<zahl><sep>%``; Geld: ``<WAEHRUNG> <zahl>`` mit explizitem
   Minor-Unit-Exponenten (CHF/USD/EUR 2, JPY 0); signiert: ``+CHF 12``.
7. Typografie ist eine verlustfreie Glyphenschicht ueber derselben Zahl:
   ``plain`` (PDF): Minus ``-``, Leerzeichen vor ``%`` U+0020;
   ``screen`` (App): Minus U+2212, geschuetztes Leerzeichen U+00A0 vor ``%``
   (CIO-Entscheid AA-UX-FORMAT-001). Ziffern sind in beiden identisch.
8. Summenerhaltung (Largest Remainder / Hamilton): Anteile einer Gruppe
   werden gemeinsam apportioniert: floor auf Anzeigeeinheiten, die fehlenden
   Einheiten (Ziel = Half-up-Rundung der Gruppensumme bzw. vorgegebenes
   Ziel) gehen an die groessten Nachkommareste; Gleichstand in der
   uebergebenen kanonischen Reihenfolge (Anlageklassen
   ``equities, bonds, real_estate, alternatives, liquidity``; Unterklassen
   nach Name, Codepoint-Ordnung). Volle Allokation (10000 bps) -> exakt
   ``100.0 %``. Unterklassen werden auf den angezeigten Klassenwert
   apportioniert. Negative Gewichte sind kein Apportionierungsfall
   (``ValueError``).
"""
from __future__ import annotations

import json
import math
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

ROUNDING_POLICY_VERSION = "ares-rounding/1"
NO_VALUE = "—"
GOLDEN_PATH = Path(__file__).with_name("presentation_rounding_golden.json")

# Kanonische Reihenfolge der Anlageklassen (Gleichstandsregel der Apportionierung).
CANONICAL_ASSET_CLASS_ORDER: tuple[str, ...] = (
    "equities", "bonds", "real_estate", "alternatives", "liquidity",
)

_TYPOGRAPHY = {
    "plain": {"minus": "-", "pct_sep": " "},
    "screen": {"minus": "−", "pct_sep": " "},
}

# ISO-4217-Minor-Unit-Exponenten der in Ares vorkommenden Waehrungen.
CURRENCY_EXPONENTS: dict[str, int] = {
    "CHF": 2, "EUR": 2, "USD": 2, "GBP": 2, "SEK": 2, "NOK": 2, "DKK": 2,
    "CAD": 2, "AUD": 2, "JPY": 0,
}


def _glyphs(typography: str) -> dict[str, str]:
    try:
        return _TYPOGRAPHY[typography]
    except KeyError as exc:  # pragma: no cover - Programmierfehler
        raise ValueError(f"unbekannte Typografie: {typography!r}") from exc


def to_decimal(value: Any) -> Decimal | None:
    """Wert -> exakte Dezimalzahl; ``None`` = keine Angabe."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return None
        return parsed if parsed.is_finite() else None
    try:
        return to_decimal(float(value))
    except (TypeError, ValueError):
        return None


def round_half_up(value: Decimal, decimals: int) -> Decimal:
    """Symmetrisches Half-up auf ``decimals`` Nachkommastellen."""
    return value.quantize(Decimal(1).scaleb(-int(decimals)), rounding=ROUND_HALF_UP)


def _group(int_digits: str) -> str:
    out = []
    for i, ch in enumerate(reversed(int_digits)):
        if i and i % 3 == 0:
            out.append("'")
        out.append(ch)
    return "".join(reversed(out))


def _body(rounded: Decimal, decimals: int) -> tuple[bool, str]:
    """(negativ_und_nicht_null, Ziffernteil ohne Vorzeichen)."""
    negative = rounded < 0 and rounded != 0
    text = f"{abs(rounded):f}"
    if "." in text:
        int_part, frac = text.split(".", 1)
    else:
        int_part, frac = text, ""
    frac = (frac + "0" * decimals)[:decimals]
    body = _group(int_part or "0")
    if decimals > 0:
        body += "." + frac
    return negative, body


def format_decimal(value: Any, decimals: int = 0, *, signed: bool = False,
                   typography: str = "plain") -> str:
    """Zahl mit fester Nachkommastellenzahl, Apostroph-Gruppierung."""
    dec = to_decimal(value)
    if dec is None:
        return NO_VALUE
    rounded = round_half_up(dec, decimals)
    negative, body = _body(rounded, decimals)
    if negative:
        return _glyphs(typography)["minus"] + body
    if signed and rounded != 0:
        return "+" + body
    return body


def format_percent(value_pct: Any, decimals: int = 1, *, signed: bool = False,
                   typography: str = "plain") -> str:
    """Wert in Prozentpunkten -> ``12.3 %``."""
    core = format_decimal(value_pct, decimals, signed=signed, typography=typography)
    if core == NO_VALUE:
        return core
    return core + _glyphs(typography)["pct_sep"] + "%"


def format_percent_bps(bps: Any, decimals: int = 1, *, signed: bool = False,
                       typography: str = "plain") -> str:
    """Integer-bps -> ``12.3 %`` (``1225 -> 12.3 %``, ``-1225 -> -12.3 %``)."""
    dec = to_decimal(bps)
    if dec is None:
        return NO_VALUE
    return format_percent(dec.scaleb(-2), decimals, signed=signed, typography=typography)


def format_probability_pct(value_pct: Any, *, typography: str = "plain") -> str:
    """Wahrscheinlichkeit in Prozentpunkten -> ganzzahlig ``73 %``."""
    return format_percent(value_pct, 0, typography=typography)


def currency_exponent(currency: str) -> int:
    code = str(currency or "").upper().strip()
    if code not in CURRENCY_EXPONENTS:
        raise ValueError(f"Minor-Unit-Exponent fuer Waehrung {currency!r} unbekannt")
    return CURRENCY_EXPONENTS[code]


def _major(minor: Any, exponent: int) -> Decimal | None:
    dec = to_decimal(minor)
    if dec is None:
        return None
    return dec.scaleb(-int(exponent))


def format_money_minor(minor: Any, currency: str, exponent: int, decimals: int | None = None,
                       *, typography: str = "plain") -> str:
    """Minor-Units -> ``CHF 10.05`` / ``USD -10.05`` / ``JPY 5``.

    ``decimals`` = angezeigte Nachkommastellen (Default: Exponent der
    Waehrung; ganze Franken: ``decimals=0``, Half-up auf den Franken).
    """
    unit = str(currency or "").upper().strip()
    if not unit:
        raise ValueError("Waehrung ist Pflicht")
    major = _major(minor, exponent)
    if major is None:
        return NO_VALUE
    shown = int(exponent) if decimals is None else int(decimals)
    return f"{unit} {format_decimal(major, shown, typography=typography)}"


def format_signed_money_minor(minor: Any, currency: str, exponent: int,
                              decimals: int | None = None, *, typography: str = "plain") -> str:
    """Signierter Betrag (Delta): ``+CHF 12'346`` / ``-CHF 12'346`` / ``CHF 0``."""
    unit = str(currency or "").upper().strip()
    if not unit:
        raise ValueError("Waehrung ist Pflicht")
    major = _major(minor, exponent)
    if major is None:
        return NO_VALUE
    shown = int(exponent) if decimals is None else int(decimals)
    rounded = round_half_up(major, shown)
    _, body = _body(rounded, shown)
    if rounded == 0:
        return f"{unit} {body}"
    sign = "+" if rounded > 0 else _glyphs(typography)["minus"]
    return f"{sign}{unit} {body}"


def format_money_compact_minor(minor: Any, currency: str, exponent: int, *,
                               typography: str = "plain") -> str:
    """Ab 1 Mio. ``CHF 2.85 Mio.``, darunter ganze Einheiten ``CHF 850'000``."""
    unit = str(currency or "").upper().strip()
    major = _major(minor, exponent)
    if major is None:
        return NO_VALUE
    return f"{unit} {format_compact_amount(major, typography=typography)}"


def format_compact_amount(major: Any, *, typography: str = "plain") -> str:
    """Betrag in ganzen Einheiten kompakt (ohne Waehrung): ``2.85 Mio.``."""
    dec = to_decimal(major)
    if dec is None:
        return NO_VALUE
    if abs(dec) >= Decimal(1_000_000):
        return format_decimal(dec.scaleb(-6), 2, typography=typography) + " Mio."
    return format_decimal(dec, 0, typography=typography)


# ---------------------------------------------------------------------------
# Summenerhaltung
# ---------------------------------------------------------------------------

def apportion_units(values: Sequence[Any], quantum: Decimal, target_units: int | None = None) -> list[int]:
    """Largest-Remainder: Werte -> ganzzahlige Anzeigeeinheiten (je ``quantum``).

    Gleichstand: Reihenfolge der Eingabe (= kanonische Reihenfolge des Aufrufers).
    """
    decs: list[Decimal] = []
    for raw in values:
        dec = to_decimal(raw)
        if dec is None:
            raise ValueError("Apportionierung braucht Werte, keine leeren Angaben")
        if dec < 0:
            raise ValueError("Apportionierung ist nur fuer nicht-negative Gewichte definiert")
        decs.append(dec)
    scaled = [d / quantum for d in decs]
    units = [int(s.to_integral_value(rounding=ROUND_FLOOR)) for s in scaled]
    if target_units is None:
        target_units = int(round_half_up(sum(decs, Decimal(0)) / quantum, 0))
    missing = int(target_units) - sum(units)
    if missing < 0 or missing > sum(1 for s, u in zip(scaled, units) if s != u):
        raise ValueError("Ziel der Apportionierung ist mit den Werten unvereinbar")
    order = sorted(range(len(scaled)), key=lambda i: (-(scaled[i] - units[i]), i))
    for idx in order[:missing]:
        units[idx] += 1
    return units


def _bps_quantum(decimals: int) -> Decimal:
    # 1 Anzeigeeinheit bei ``decimals`` Prozent-Nachkommastellen in bps.
    return Decimal(1).scaleb(2 - int(decimals))


def apportion_percent_bps(values_bps: Sequence[Any], decimals: int = 1, *,
                          target_bps: Any = None, target_display: Any = None) -> list[Decimal]:
    """bps-Gewichte -> angezeigte Prozentwerte (Decimal), Summe erhalten.

    ``target_display``: vorgegebene Gruppensumme in Prozent (z. B. der
    angezeigte Klassenwert fuer ihre Unterklassen). ``target_bps``: Summe in
    bps, deren Half-up-Rundung das Ziel ist. Ohne beides: Summe der Werte.
    """
    quantum = _bps_quantum(decimals)
    target_units = None
    if target_display is not None:
        disp = to_decimal(target_display)
        if disp is None:
            raise ValueError("target_display fehlt")
        target_units = int(round_half_up(disp * 100 / quantum, 0))
    elif target_bps is not None:
        tb = to_decimal(target_bps)
        if tb is None:
            raise ValueError("target_bps fehlt")
        target_units = int(round_half_up(tb / quantum, 0))
    units = apportion_units(values_bps, quantum, target_units)
    step = quantum.scaleb(-2)
    return [round_half_up(Decimal(u) * step, decimals) for u in units]


def format_apportioned_percent_bps(values_bps: Sequence[Any], decimals: int = 1, *,
                                   typography: str = "plain", **kwargs: Any) -> list[str]:
    return [
        format_percent(v, decimals, typography=typography)
        for v in apportion_percent_bps(values_bps, decimals, **kwargs)
    ]


def ordered_for_apportionment(keys: Iterable[str]) -> list[str]:
    """Anlageklassen-Schluessel in kanonischer Reihenfolge (unbekannte zuletzt, stabil)."""
    keys = list(keys)
    rank = {k: i for i, k in enumerate(CANONICAL_ASSET_CLASS_ORDER)}
    return sorted(keys, key=lambda k: (rank.get(k, len(rank)), keys.index(k)))


def apportion_bucket_bps(allocation_bps: dict[str, Any], decimals: int = 1) -> dict[str, Decimal]:
    """Anlageklassen-Gewichte -> angezeigte Prozent je Klasse (kanonische Gleichstandsregel)."""
    keys = ordered_for_apportionment(
        k for k in allocation_bps if (to_decimal(allocation_bps.get(k)) or 0) > 0
    )
    shown = apportion_percent_bps([allocation_bps[k] for k in keys], decimals)
    return dict(zip(keys, shown))


def apportion_sub_bps(class_display: Decimal, subs: dict[str, Any], class_bps: Any,
                      decimals: int = 1) -> dict[str, Decimal]:
    """Unterklassen einer Klasse -> angezeigte Prozent.

    Unterklassen (Gleichstand nach Name, Codepoint-Ordnung) plus ggf. ein
    Rest "ohne Unterklasse" (Klasse minus Summe, zuletzt) werden auf den
    angezeigten Klassenwert apportioniert; der Rest wird nicht als
    Unterklasse ausgegeben. Uebersteigen die Unterklassen die Klasse
    (inkonsistente Daten), werden sie auf ihre eigene Summe apportioniert.
    Identisch zu aaChartPrepare (aa-chart.js).
    """
    names = sorted(k for k in subs if (to_decimal(subs.get(k)) or 0) > 0)
    if not names:
        return {}
    values: list[Any] = [subs[k] for k in names]
    total = sum((to_decimal(v) or Decimal(0)) for v in values)
    klass = to_decimal(class_bps) or Decimal(0)
    if total <= klass:
        if total < klass:
            values.append(klass - total)
        shown = apportion_percent_bps(values, decimals, target_display=class_display)
    else:
        shown = apportion_percent_bps(values, decimals)
    return dict(zip(names, shown[:len(names)]))


# ---------------------------------------------------------------------------
# Antwortartefakte + Golden-Vektor
# ---------------------------------------------------------------------------

def presentation_artifact(raw: Any, unit: str, display: str) -> dict[str, Any]:
    """Evidenzzeile: Rohwert, Einheit, Policy-Version, Anzeige."""
    return {
        "raw": raw,
        "unit": unit,
        "policy_version": ROUNDING_POLICY_VERSION,
        "display": display,
    }


@lru_cache(maxsize=1)
def load_golden() -> dict[str, Any]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if data.get("policy_version") != ROUNDING_POLICY_VERSION:
        raise RuntimeError("Golden-Vektor gehoert zu einer anderen Rundungs-Policy")
    return data


def golden_vectors() -> dict[str, str]:
    """Benannte Golden-Faelle -> erwartete Anzeige (Typografie ``plain``)."""
    return {case["id"]: case["plain"] for case in load_golden()["cases"]}


def run_case(fn: str, args: Sequence[Any], typography: str) -> Any:
    """Fuehrt einen Golden-Fall aus (dieselben Funktionsnamen in JS/TS)."""
    t = typography
    if fn == "number":
        return format_decimal(args[0], args[1] if len(args) > 1 else 0, typography=t)
    if fn == "signed_number":
        return format_decimal(args[0], args[1] if len(args) > 1 else 0, signed=True, typography=t)
    if fn == "percent_bps":
        return format_percent_bps(args[0], args[1] if len(args) > 1 else 1, typography=t)
    if fn == "signed_percent_bps":
        return format_percent_bps(args[0], args[1] if len(args) > 1 else 1, signed=True, typography=t)
    if fn == "percent":
        return format_percent(args[0], args[1] if len(args) > 1 else 1, typography=t)
    if fn == "probability_pct":
        return format_probability_pct(args[0], typography=t)
    if fn == "money_minor":
        return format_money_minor(args[0], args[1], args[2], args[3] if len(args) > 3 else None, typography=t)
    if fn == "signed_money_minor":
        return format_signed_money_minor(args[0], args[1], args[2], args[3] if len(args) > 3 else None, typography=t)
    if fn == "money_compact_minor":
        return format_money_compact_minor(args[0], args[1], args[2], typography=t)
    if fn == "apportion_percent_bps":
        target = args[2] if len(args) > 2 else None
        return format_apportioned_percent_bps(args[0], args[1], typography=t, target_display=target)
    if fn == "apportioned_sum":
        shown = apportion_percent_bps(args[0], args[1] if len(args) > 1 else 1)
        return format_percent(sum(shown, Decimal(0)), args[1] if len(args) > 1 else 1, typography=t)
    raise ValueError(f"unbekannte Golden-Funktion {fn!r}")


__all__ = [
    "CANONICAL_ASSET_CLASS_ORDER", "CURRENCY_EXPONENTS", "GOLDEN_PATH", "NO_VALUE",
    "ROUNDING_POLICY_VERSION", "apportion_bucket_bps", "apportion_percent_bps",
    "apportion_sub_bps", "apportion_units", "currency_exponent", "format_apportioned_percent_bps",
    "format_compact_amount", "format_decimal", "format_money_compact_minor", "format_money_minor",
    "format_percent", "format_percent_bps", "format_probability_pct",
    "format_signed_money_minor", "golden_vectors", "load_golden", "ordered_for_apportionment",
    "presentation_artifact", "round_half_up", "run_case", "to_decimal",
]
