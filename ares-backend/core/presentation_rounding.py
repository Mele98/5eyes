"""G7 -- gemeinsamer Rundungsformatter fuer Kundenevidenz (App + PDF).

Vertrag (Policy ``ares-rounding/1``), identisch umgesetzt in

* ``ares-backend/core/presentation_rounding.py``  (dieses Modul: PDF/Backend)
* ``ares-desktop/frontend/presentation-rounding.js``   (Classic-App, Standalone-Modul)
* ``ares-desktop/frontend/reporting/src/lib/presentationRounding.ts`` (React)

und gekoppelt ueber EINEN Golden-Vektor
``ares-backend/core/presentation_rounding_golden.json``, den die Python-,
Classic- und React-Tests lesen (Abweichung = roter Test).
``services.presentation_rounding`` ist der Vertragsname (Codex-Reproducer) und
re-exportiert dieses Modul.

Reines Stdlib-Blattmodul (Architektur-Ratsche, FAN_OUT_EXEMPT_LEAVES): nur
``json``/``typing``; exakte Dezimalarithmetik ueber Python-Ganzzahlen
(Vorzeichen, Koeffizient, Exponent) -- dieselbe Darstellung wie die
BigInt-Implementierung der beiden JS-Kanaele.

Regeln
------
1. Rechenwerte bleiben Integer-bps bzw. Integer-Minor-Units. Gerundet wird
   nur hier, an der Praesentationsgrenze. Dieses Modul liest Werte, es
   aendert keine Fachwerte, Schwellen, Restriktionen oder Persistenz.
2. Rundung: exakte Dezimalarithmetik, ``ROUND_HALF_UP`` symmetrisch
   (Gleichstand vom Nullpunkt weg): ``+12.25 -> +12.3`` und ``-12.25 -> -12.3``.
   Kein Float-``format``/``round`` (Banker's Rounding), kein ``toFixed``.
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
   ``100.0 %``. Unterklassen (plus ggf. Rest "ohne Unterklasse") werden auf
   den angezeigten Klassenwert apportioniert. Negative Gewichte sind kein
   Apportionierungsfall (``ValueError``).

Apportionierte Werte werden als Dezimalstrings (``"33.4"``) geliefert.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

ROUNDING_POLICY_VERSION = "ares-rounding/1"
NO_VALUE = "—"
GOLDEN_FILENAME = "presentation_rounding_golden.json"

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

_DIGITS = "0123456789"


def _glyphs(typography: str) -> dict[str, str]:
    if typography not in _TYPOGRAPHY:
        raise ValueError(f"unbekannte Typografie: {typography!r}")
    return _TYPOGRAPHY[typography]


def _parse_text(text: str) -> tuple[bool, int, int] | None:
    """Dezimaltext (auch Exponentenschreibweise) -> (negativ, Koeffizient, Exponent)."""
    s = text.strip()
    if not s:
        return None
    neg = False
    if s[0] in "+-":
        neg = s[0] == "-"
        s = s[1:]
    exp = 0
    low = s.lower()
    if "e" in low:
        mant, _, exp_text = low.partition("e")
        body = exp_text[1:] if exp_text[:1] in "+-" else exp_text
        if not body or any(ch not in _DIGITS for ch in body):
            return None
        exp = int(exp_text)
        s = mant
    int_part, dot, frac = s.partition(".")
    if (not int_part and not frac) or any(ch not in _DIGITS for ch in int_part + frac):
        return None
    coef = int((int_part or "0") + frac)
    return (neg and coef != 0, coef, exp - len(frac))


def to_decimal(value: Any) -> tuple[bool, int, int] | None:
    """Wert -> exakte Dezimaldarstellung ``(negativ, Koeffizient, Exponent)``;
    ``None`` = keine Angabe. Floats ueber ``repr`` (kuerzeste Round-trip-Form)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, tuple) and len(value) == 3:
        return value
    if isinstance(value, int):
        return (value < 0, abs(value), 0)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return _parse_text(repr(value))
    if isinstance(value, str):
        return _parse_text(value)
    text = str(value)  # z. B. decimal.Decimal (ohne Import: Textform ist exakt)
    if text.lower() in ("nan", "snan", "inf", "-inf", "infinity", "-infinity"):
        return None
    return _parse_text(text)


def _scale(d: tuple[bool, int, int], k: int) -> tuple[bool, int, int]:
    return (d[0], d[1], d[2] + k)


def _round_units(d: tuple[bool, int, int], decimals: int) -> tuple[bool, int]:
    """Half-up vom Nullpunkt weg -> (negativ, Einheiten) mit Wert Einheiten*10^-decimals."""
    neg, coef, exp = d
    shift = exp + decimals
    if shift >= 0:
        units = coef * 10 ** shift
    else:
        p = 10 ** (-shift)
        q, r = divmod(coef, p)
        units = q + 1 if 2 * r >= p else q
    return (neg and units != 0, units)


def _group(int_digits: str) -> str:
    out = []
    for i, ch in enumerate(reversed(int_digits)):
        if i and i % 3 == 0:
            out.append("'")
        out.append(ch)
    return "".join(reversed(out))


def _digits(units: int, decimals: int) -> str:
    s = str(units)
    if decimals <= 0:
        return _group(s)
    s = s.rjust(decimals + 1, "0")
    return _group(s[:-decimals]) + "." + s[-decimals:]


def format_decimal(value: Any, decimals: int = 0, *, signed: bool = False,
                   typography: str = "plain") -> str:
    """Zahl mit fester Nachkommastellenzahl, Apostroph-Gruppierung."""
    d = to_decimal(value)
    if d is None:
        return NO_VALUE
    neg, units = _round_units(d, int(decimals))
    body = _digits(units, int(decimals))
    if neg:
        return _glyphs(typography)["minus"] + body
    if signed and units != 0:
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
    d = to_decimal(bps)
    if d is None:
        return NO_VALUE
    return format_percent(_scale(d, -2), decimals, signed=signed, typography=typography)


def format_probability_pct(value_pct: Any, *, typography: str = "plain") -> str:
    """Wahrscheinlichkeit in Prozentpunkten -> ganzzahlig ``73 %``."""
    return format_percent(value_pct, 0, typography=typography)


def currency_exponent(currency: str) -> int:
    code = str(currency or "").upper().strip()
    if code not in CURRENCY_EXPONENTS:
        raise ValueError(f"Minor-Unit-Exponent fuer Waehrung {currency!r} unbekannt")
    return CURRENCY_EXPONENTS[code]


def _unit(currency: str) -> str:
    unit = str(currency or "").upper().strip()
    if not unit:
        raise ValueError("Waehrung ist Pflicht")
    return unit


def format_money_minor(minor: Any, currency: str, exponent: int, decimals: int | None = None,
                       *, typography: str = "plain") -> str:
    """Minor-Units -> ``CHF 10.05`` / ``USD -10.05`` / ``JPY 5``.

    ``decimals`` = angezeigte Nachkommastellen (Default: Exponent der
    Waehrung; ganze Franken: ``decimals=0``, Half-up auf den Franken).
    """
    unit = _unit(currency)
    d = to_decimal(minor)
    if d is None:
        return NO_VALUE
    shown = int(exponent) if decimals is None else int(decimals)
    return f"{unit} {format_decimal(_scale(d, -int(exponent)), shown, typography=typography)}"


def format_signed_money_minor(minor: Any, currency: str, exponent: int,
                              decimals: int | None = None, *, typography: str = "plain") -> str:
    """Signierter Betrag (Delta): ``+CHF 12'346`` / ``-CHF 12'346`` / ``CHF 0``."""
    unit = _unit(currency)
    d = to_decimal(minor)
    if d is None:
        return NO_VALUE
    shown = int(exponent) if decimals is None else int(decimals)
    neg, units = _round_units(_scale(d, -int(exponent)), shown)
    body = _digits(units, shown)
    if units == 0:
        return f"{unit} {body}"
    sign = _glyphs(typography)["minus"] if neg else "+"
    return f"{sign}{unit} {body}"


def format_compact_amount(major: Any, *, typography: str = "plain") -> str:
    """Betrag in ganzen Einheiten kompakt (ohne Waehrung): ``2.85 Mio.``."""
    d = to_decimal(major)
    if d is None:
        return NO_VALUE
    _, coef, exp = d
    shift = exp - 6
    at_least_million = coef != 0 if shift >= 0 else coef >= 10 ** (-shift)
    if at_least_million:
        return format_decimal(_scale(d, -6), 2, typography=typography) + " Mio."
    return format_decimal(d, 0, typography=typography)


def format_money_compact_minor(minor: Any, currency: str, exponent: int, *,
                               typography: str = "plain") -> str:
    """Ab 1 Mio. ``CHF 2.85 Mio.``, darunter ganze Einheiten ``CHF 850'000``."""
    unit = str(currency or "").upper().strip()
    d = to_decimal(minor)
    if d is None:
        return NO_VALUE
    return f"{unit} {format_compact_amount(_scale(d, -int(exponent)), typography=typography)}"


# ---------------------------------------------------------------------------
# Summenerhaltung
# ---------------------------------------------------------------------------

def apportion_units(values: Sequence[Any], decimals: int, target_units: int | None = None) -> list[int]:
    """Largest Remainder: bps-Werte -> ganzzahlige Anzeigeeinheiten (10^-decimals %).

    Gleichstand: Reihenfolge der Eingabe (= kanonische Reihenfolge des Aufrufers).
    """
    ds = []
    for raw in values:
        d = to_decimal(raw)
        if d is None:
            raise ValueError("Apportionierung braucht Werte, keine leeren Angaben")
        if d[0]:
            raise ValueError("Apportionierung ist nur fuer nicht-negative Gewichte definiert")
        ds.append(_scale(d, int(decimals) - 2))
    e = min([0] + [d[2] for d in ds])
    p = 10 ** (-e)
    ints = [d[1] * 10 ** (d[2] - e) for d in ds]
    units = [v // p for v in ints]
    rems = [v % p for v in ints]
    if target_units is None:
        target_units = _round_units((False, sum(ints), e), 0)[1]
    missing = int(target_units) - sum(units)
    if missing < 0 or missing > sum(1 for r in rems if r):
        raise ValueError("Ziel der Apportionierung ist mit den Werten unvereinbar")
    order = sorted(range(len(units)), key=lambda i: (-rems[i], i))
    for idx in order[:missing]:
        units[idx] += 1
    return units


def _target_units(target_display: Any, decimals: int) -> int | None:
    if target_display is None:
        return None
    d = to_decimal(target_display)
    if d is None:
        raise ValueError("target_display fehlt")
    return _round_units(d, decimals)[1]


def apportion_percent_bps(values_bps: Sequence[Any], decimals: int = 1, *,
                          target_display: Any = None) -> list[str]:
    """bps-Gewichte -> angezeigte Prozentwerte als Dezimalstrings, Summe erhalten.

    ``target_display``: vorgegebene Gruppensumme in Prozent (z. B. der
    angezeigte Klassenwert fuer seine Unterklassen). Ohne: Summe der Werte.
    """
    n = int(decimals)
    units = apportion_units(values_bps, n, _target_units(target_display, n))
    return [_digits(u, n).replace("'", "") for u in units]


def format_apportioned_percent_bps(values_bps: Sequence[Any], decimals: int = 1, *,
                                   typography: str = "plain", target_display: Any = None) -> list[str]:
    return [format_percent(v, decimals, typography=typography)
            for v in apportion_percent_bps(values_bps, decimals, target_display=target_display)]


def ordered_for_apportionment(keys: Iterable[str]) -> list[str]:
    """Anlageklassen-Schluessel in kanonischer Reihenfolge (unbekannte zuletzt, stabil)."""
    keys = list(keys)
    rank = {k: i for i, k in enumerate(CANONICAL_ASSET_CLASS_ORDER)}
    return sorted(keys, key=lambda k: (rank.get(k, len(rank)), keys.index(k)))


def _positive(value: Any) -> bool:
    d = to_decimal(value)
    return d is not None and not d[0] and d[1] != 0


def apportion_bucket_bps(allocation_bps: Mapping[str, Any], decimals: int = 1) -> dict[str, str]:
    """Anlageklassen-Gewichte -> angezeigte Prozent je Klasse (kanonische Gleichstandsregel)."""
    keys = ordered_for_apportionment(k for k in allocation_bps if _positive(allocation_bps.get(k)))
    shown = apportion_percent_bps([allocation_bps[k] for k in keys], decimals)
    return dict(zip(keys, shown))


def apportion_sub_bps(class_display: Any, subs: Mapping[str, Any], class_bps: Any,
                      decimals: int = 1) -> dict[str, str]:
    """Unterklassen einer Klasse -> angezeigte Prozent.

    Unterklassen (Gleichstand nach Name, Codepoint-Ordnung) plus ggf. ein Rest
    "ohne Unterklasse" (Klasse minus Summe, zuletzt) werden auf den angezeigten
    Klassenwert apportioniert; der Rest wird nicht als Unterklasse ausgegeben.
    Uebersteigen die Unterklassen die Klasse (inkonsistente Daten), werden sie
    auf ihre eigene Summe apportioniert. Identisch zu aaChartPrepare (aa-chart.js).
    """
    names = sorted(k for k in subs if _positive(subs.get(k)))
    if not names:
        return {}
    values: list[Any] = [subs[k] for k in names]
    ds = [to_decimal(v) or (False, 0, 0) for v in values + [class_bps or 0]]
    e = min([0] + [d[2] for d in ds])
    ints = [(-1 if d[0] else 1) * d[1] * 10 ** (d[2] - e) for d in ds]
    total, klass = sum(ints[:-1]), ints[-1]
    if total <= klass:
        if total < klass:
            values.append((False, klass - total, e))
        shown = apportion_percent_bps(values, decimals, target_display=class_display)
    else:
        shown = apportion_percent_bps(values, decimals)
    return dict(zip(names, shown[:len(names)]))


_ASSET_CLASS_KEYS = {
    "aktien": "equities", "equities": "equities",
    "obligationen": "bonds", "anleihen": "bonds", "bonds": "bonds",
    "immobilien": "real_estate", "real_estate": "real_estate", "real estate": "real_estate",
    "alternative": "alternatives", "alternativen": "alternatives", "alternatives": "alternatives",
    "liquiditaet": "liquidity", "liquidität": "liquidity", "liquidity": "liquidity",
}


def asset_class_key(label: Any) -> str:
    """Anlageklassen-Bezeichnung (deutsch oder Engine-Schluessel) -> Engine-Schluessel."""
    raw = str(label or "").strip()
    return _ASSET_CLASS_KEYS.get(raw.lower(), raw)


def whole_units(minor: Any, exponent: int = 2) -> int:
    """Minor-Units -> ganze Waehrungseinheiten, Half-up (symmetrisch)."""
    d = to_decimal(minor)
    if d is None:
        return 0
    neg, units = _round_units(_scale(d, -int(exponent)), 0)
    return -units if neg else units


def split_largest_remainder(total: int, weights: Sequence[Any], labels: Sequence[Any]) -> list[int]:
    """Ganzzahlige Aufteilung nach Largest Remainder (Hamilton). Gleichstand:
    groesseres Gewicht, dann Label (Codepoint-Ordnung), dann Position."""
    clean = [max(0, int(w or 0)) for w in weights]
    weight_sum = sum(clean)
    total = int(total)
    if weight_sum <= 0 or total <= 0:
        return [0] * len(clean)
    floors = [total * w // weight_sum for w in clean]
    rems = [total * w % weight_sum for w in clean]
    order = sorted(range(len(clean)), key=lambda i: (-rems[i], -clean[i], str(labels[i]), i))
    for i in order[: total - sum(floors)]:
        floors[i] += 1
    return floors


def presentation_amounts(advisory_minor: Any, base_minor: Any, weights: Sequence[Any],
                         labels: Sequence[Any], exponent: int = 2) -> dict[str, Any]:
    """Betraege der Soll-Darstellung in ganzen Waehrungseinheiten (App + PDF identisch).

    Beratungsvermoegen und Strategiebasis Half-up auf ganze Einheiten, Reserve =
    Differenz, Klassenbetraege = Largest-Remainder-Aufteilung der Strategiebasis
    nach Gewicht -- so summieren Klassen exakt auf die Basis und Basis + Reserve
    exakt auf das Beratungsvermoegen. ``labels`` = Engine-Schluessel.
    """
    adv = max(0, int(advisory_minor or 0))
    base_raw = adv if base_minor is None else max(0, int(base_minor))
    base = whole_units(min(base_raw, adv), exponent)
    advisory = whole_units(adv, exponent)
    keys = [asset_class_key(lb) for lb in labels]
    buckets = split_largest_remainder(base, weights, keys) if base > 0 else [0] * len(keys)
    return {"advisory_units": advisory, "base_units": base,
            "reserve_units": max(0, advisory - base), "bucket_units": buckets}


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


def golden_path() -> str:
    """Pfad des gemeinsamen Golden-Vektors (neben diesem Modul)."""
    base = __file__.replace("\\", "/").rsplit("/", 1)[0]
    return base + "/" + GOLDEN_FILENAME


def load_golden() -> dict[str, Any]:
    with open(golden_path(), encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("policy_version") != ROUNDING_POLICY_VERSION:
        raise RuntimeError("Golden-Vektor gehoert zu einer anderen Rundungs-Policy")
    return data


def golden_vectors() -> dict[str, str]:
    """Benannte Golden-Faelle -> erwartete Anzeige (Typografie ``plain``)."""
    return {case["id"]: case["plain"] for case in load_golden()["cases"]}


def run_case(fn: str, args: Sequence[Any], typography: str) -> Any:
    """Fuehrt einen Golden-Fall aus (dieselben Funktionsnamen in JS/TS)."""
    t = typography

    def opt(i: int, default: int) -> int:
        return int(args[i]) if len(args) > i else default

    if fn == "number":
        return format_decimal(args[0], opt(1, 0), typography=t)
    if fn == "signed_number":
        return format_decimal(args[0], opt(1, 0), signed=True, typography=t)
    if fn == "percent_bps":
        return format_percent_bps(args[0], opt(1, 1), typography=t)
    if fn == "signed_percent_bps":
        return format_percent_bps(args[0], opt(1, 1), signed=True, typography=t)
    if fn == "percent":
        return format_percent(args[0], opt(1, 1), typography=t)
    if fn == "probability_pct":
        return format_probability_pct(args[0], typography=t)
    if fn == "money_minor":
        return format_money_minor(args[0], args[1], args[2], args[3] if len(args) > 3 else None, typography=t)
    if fn == "signed_money_minor":
        return format_signed_money_minor(args[0], args[1], args[2], args[3] if len(args) > 3 else None, typography=t)
    if fn == "money_compact_minor":
        return format_money_compact_minor(args[0], args[1], args[2], typography=t)
    if fn == "apportion_percent_bps":
        return format_apportioned_percent_bps(args[0], args[1], typography=t,
                                              target_display=args[2] if len(args) > 2 else None)
    if fn == "presentation_amounts":
        r = presentation_amounts(args[0], args[1], args[2], args[3], int(args[4]) if len(args) > 4 else 2)
        return [str(r["advisory_units"]), str(r["base_units"]), str(r["reserve_units"])] + [str(u) for u in r["bucket_units"]]
    if fn == "apportioned_sum":
        n = opt(1, 1)
        return format_percent((False, sum(apportion_units(args[0], n)), -n), n, typography=t)
    raise ValueError(f"unbekannte Golden-Funktion {fn!r}")


# ---------------------------------------------------------------------------
# PDF-Komfortfunktionen (Typografie ``plain``); services.pdf.components.swiss_numbers
# re-exportiert sie. Komponenten importieren direkt aus diesem Blattmodul.
# ---------------------------------------------------------------------------

def _exponent_or_default(currency: str) -> int:
    return CURRENCY_EXPONENTS.get(str(currency or "").upper().strip(), 2)


def format_bps_as_pct(bps: Any, *, decimals: int = 1) -> str:
    """``4250 -> 42.5 %``; keine Angabe -> ``NO_VALUE``."""
    return format_percent_bps(bps, decimals)


def format_bps_signed_pct(bps: Any, *, decimals: int = 1) -> str:
    """``450 -> +4.5 %`` (0 ohne Vorzeichen)."""
    return format_percent_bps(bps, decimals, signed=True)


def format_pct_value(value_pct: Any, *, decimals: int = 1) -> str:
    """Wert bereits in Prozentpunkten -> ``12.3 %``."""
    return format_percent(value_pct, decimals)


def format_number(value: Any, *, decimals: int = 0) -> str:
    return format_decimal(value, decimals)


def format_amount_minor(minor: Any, currency: str = "CHF", *, decimals: int = 0) -> str:
    """Minor-Units der Waehrung -> ``CHF 12'345`` (ganze Einheiten, Half-up)."""
    unit = str(currency or "CHF").upper().strip() or "CHF"
    return format_money_minor(minor, unit, _exponent_or_default(unit), decimals)


def format_minor_number(minor: Any, *, exponent: int = 2, decimals: int = 0) -> str:
    """Minor-Units -> Zahl ohne Waehrung (``1234550 -> 12'346``), Half-up."""
    d = to_decimal(minor)
    if d is None:
        return NO_VALUE
    return format_decimal(_scale(d, -int(exponent)), decimals)


def allocation_pct_texts(allocation_bps: Mapping[str, Any], *, decimals: int = 1) -> dict[str, str]:
    """Anlageklassen-Gewichte -> apportionierte Anzeige (Summe exakt 100.0 %)."""
    data = dict(allocation_bps or {})
    shown = apportion_bucket_bps(data, decimals)
    return {
        key: format_percent(shown[key], decimals) if key in shown else format_percent_bps(0, decimals)
        for key in data
    }


def sub_allocation_pct_texts(class_display_pct: str, subs: Mapping[str, Any], class_bps: Any,
                             *, decimals: int = 1) -> dict[str, str]:
    """Unterklassen -> Anzeige, summiert auf den angezeigten Klassenwert."""
    class_value = str(class_display_pct).replace("%", "").replace(" ", "").strip()
    if to_decimal(class_value) is None:
        raise ValueError("Klassenwert fehlt")
    shown = apportion_sub_bps(class_value, dict(subs or {}), class_bps, decimals)
    return {key: format_percent(value, decimals) for key, value in shown.items()}


__all__ = [
    "CANONICAL_ASSET_CLASS_ORDER", "CURRENCY_EXPONENTS", "GOLDEN_FILENAME", "NO_VALUE",
    "ROUNDING_POLICY_VERSION", "allocation_pct_texts", "apportion_bucket_bps",
    "apportion_percent_bps", "apportion_sub_bps", "apportion_units", "asset_class_key", "currency_exponent",
    "format_amount_minor", "format_apportioned_percent_bps", "format_bps_as_pct",
    "format_bps_signed_pct", "format_compact_amount", "format_decimal", "format_minor_number",
    "format_money_compact_minor", "format_money_minor", "format_number", "format_pct_value",
    "format_percent", "format_percent_bps", "format_probability_pct", "format_signed_money_minor",
    "golden_path", "golden_vectors", "load_golden", "ordered_for_apportionment",
    "presentation_amounts", "presentation_artifact", "run_case", "split_largest_remainder",
    "sub_allocation_pct_texts", "to_decimal", "whole_units",
]
