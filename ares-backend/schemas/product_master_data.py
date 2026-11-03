"""Produkt-Stammdaten (Audit 2026-11, Paket P1; Entscheid PO-6, Luecke L1).

Validierung und Normalisierung der neuen Stammdatenfelder im Fondsuniversum.
Bewusst eine Leaf-Schicht (nur Standardbibliothek), damit ``schemas/review.py``
sie ohne Zirkularimport nutzen kann.

Grundsatz "nichts erfinden": Jedes Feld ist optional und NULL bedeutet
"nicht erfasst". Insbesondere gilt ein Produkt ohne erfassten
Retrozessionssatz NIE als retrozessionsfrei (``retrocession_bps`` NULL =
unbekannt, 0 = ausdruecklich retrozessionsfrei mit Quelle).

Die Auswahl- und Scoring-Logik der Engine liest diese Felder in P1 nicht.
Sie werden erfasst, validiert, importiert/exportiert und angezeigt; die
lexikografische Auswahl folgt in P13.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

# ── ISIN (ISO 6166) ───────────────────────────────────────────────────────────
# Aufbau: 2 Buchstaben Laenderpraefix, 9 alphanumerische Zeichen (NSIN),
# 1 Pruefziffer. Pruefziffer: Buchstaben werden zu Zahlen (A=10 ... Z=35)
# expandiert, auf die entstehende Ziffernfolge wird Luhn (Modulus 10)
# angewendet.
_ISIN_SHAPE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def isin_is_valid(value: Any) -> bool:
    """True, wenn ``value`` eine formal gueltige ISIN mit korrekter
    Pruefziffer ist. Erwartet die normalisierte Form (Grossbuchstaben, ohne
    Leerzeichen)."""
    if not isinstance(value, str) or not _ISIN_SHAPE.match(value):
        return False
    expanded = "".join(
        str(ord(char) - 55) if char.isalpha() else char for char in value
    )
    return _luhn_valid(expanded)


def normalize_isin(value: Any) -> Optional[str]:
    """trim + Grossschreibung + Pruefziffer. Leer -> None (keine ISIN,
    z.B. nicht kotierter Fonds). Ungueltig -> ValueError (422)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("isin muss eine Zeichenkette sein")
    normalized = value.strip().upper().replace(" ", "")
    if not normalized:
        return None
    if not _ISIN_SHAPE.match(normalized):
        raise ValueError(
            f"isin {value!r} hat nicht das ISIN-Format nach ISO 6166 "
            "(2 Buchstaben Land, 9 Zeichen, 1 Pruefziffer; 12 Zeichen)"
        )
    if not isin_is_valid(normalized):
        raise ValueError(f"isin {value!r}: Pruefziffer ungueltig (ISO 6166, Luhn)")
    return normalized


def isin_status(value: Any) -> str:
    """'missing' | 'invalid' | 'valid' -- fuer die Kennzeichnung von
    Altbestand. Altbestand ohne oder mit formal ungueltiger ISIN wird nicht
    blockiert, aber sichtbar gekennzeichnet."""
    text = str(value or "").strip().upper()
    if not text:
        return "missing"
    return "valid" if isin_is_valid(text) else "invalid"


# ── Domizil, Waehrung, Valor, Ausschuettungsart, Stichtag ────────────────────

def normalize_country_code(value: Any, *, field_name: str, valid_codes) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} muss ein Laendercode (ISO 3166-1 alpha-2) sein")
    normalized = value.strip().upper()
    if not normalized:
        return None
    if normalized not in valid_codes:
        raise ValueError(
            f"{field_name} {value!r} ist kein gueltiger Laendercode (ISO 3166-1 alpha-2)"
        )
    return normalized


_CURRENCY_SHAPE = re.compile(r"^[A-Z]{3}$")


def normalize_currency_code(value: Any, *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} muss ein Waehrungscode (ISO 4217) sein")
    normalized = value.strip().upper()
    if not normalized:
        return None
    if not _CURRENCY_SHAPE.match(normalized):
        raise ValueError(f"{field_name} {value!r} ist kein Waehrungscode (ISO 4217, 3 Buchstaben)")
    return normalized


_VALOR_SHAPE = re.compile(r"^[0-9]{1,12}$")


def normalize_valor(value: Any) -> Optional[str]:
    """Valorennummer: nur Ziffern. Tausendertrenner (Apostroph, Punkt,
    Leerzeichen) werden entfernt, fuehrende Nullen bleiben erhalten."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = re.sub(r"[\s'’.]", "", text)
    if not _VALOR_SHAPE.match(compact):
        raise ValueError(f"valor {value!r} ist keine Valorennummer (nur Ziffern, max. 12)")
    return compact


DISTRIBUTION_POLICIES = ("accumulating", "distributing")
_DISTRIBUTION_ALIASES = {
    "accumulating": "accumulating",
    "thesaurierend": "accumulating",
    "acc": "accumulating",
    "distributing": "distributing",
    "ausschuettend": "distributing",
    "ausschüttend": "distributing",
    "dist": "distributing",
}


def normalize_distribution_policy(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text not in _DISTRIBUTION_ALIASES:
        raise ValueError(
            f"distribution_policy {value!r} unbekannt (erlaubt: accumulating/thesaurierend, "
            "distributing/ausschuettend)"
        )
    return _DISTRIBUTION_ALIASES[text]


def normalize_as_of_date(value: Any, *, field_name: str) -> Optional[str]:
    """Stichtag als ISO-Datum (YYYY-MM-DD), nicht in der Zukunft."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = _dt.date.fromisoformat(text[:10]) if len(text) >= 10 else None
    except ValueError:
        parsed = None
    if parsed is None or (len(text) > 10 and text[10] not in "T "):
        raise ValueError(f"{field_name} {value!r} ist kein Datum (YYYY-MM-DD)")
    if parsed > _dt.date.today():
        raise ValueError(f"{field_name} {value!r} liegt in der Zukunft")
    return parsed.isoformat()


_SOURCE_MAX_LEN = 200


def normalize_source(value: Any, *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > _SOURCE_MAX_LEN:
        raise ValueError(f"{field_name} ist zu lang (max. {_SOURCE_MAX_LEN} Zeichen)")
    return text


def normalize_optional_bool(value: Any, *, field_name: str) -> Optional[bool]:
    """CSV-tauglich: ja/nein, true/false, 1/0. Leer -> None (nicht erfasst)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return None
    if text in ("1", "true", "ja", "yes", "j", "y", "wahr"):
        return True
    if text in ("0", "false", "nein", "no", "n", "falsch"):
        return False
    raise ValueError(f"{field_name} {value!r} ist kein Ja/Nein-Wert")


def master_data_consistency_errors(fields: dict) -> list[str]:
    """Querpruefungen ueber mehrere Felder (Erfassen und gemergter Stand
    beim Bearbeiten)."""
    errors: list[str] = []
    if fields.get("retrocession_bps") is not None and not fields.get("retrocession_source"):
        errors.append(
            "retrocession_source ist Pflicht, sobald ein Retrozessionssatz erfasst ist "
            "(auch fuer 0 = retrozessionsfrei)"
        )
    if fields.get("hedge_currency") and fields.get("is_hedged") is False:
        errors.append("hedge_currency ist nur bei abgesicherten Anteilsklassen (is_hedged=true) zulaessig")
    if fields.get("ter_as_of") and fields.get("ter_bps") is None:
        errors.append("ter_as_of ohne ter_bps: Stichtag nur zusammen mit einer TER erfassen")
    return errors


# ── Kennzeichnung im Katalog ──────────────────────────────────────────────────

# Felder, die PO-6 fuer empfehlbare Produkte verlangt. In P1 werden Luecken
# nur gekennzeichnet (keine Sperre der Auswahl; die folgt mit P13).
REQUIRED_MASTER_DATA_FIELDS = (
    "isin",
    "domicile",
    "is_hedged",
    "ter_bps",
    "ter_source",
    "ter_as_of",
    "retrocession_bps",
    "is_house_product",
)


def retrocession_status(rate_bps: Any) -> str:
    """'unknown' (NULL) | 'none' (0, ausdruecklich retrozessionsfrei) |
    'present' (> 0)."""
    if rate_bps is None or isinstance(rate_bps, bool):
        return "unknown"
    try:
        rate = int(rate_bps)
    except (TypeError, ValueError):
        return "unknown"
    return "present" if rate > 0 else "none"


def master_data_gaps(product: Any) -> list[str]:
    """Fehlende oder ungueltige Pflicht-Stammdaten (PO-6), stabil sortiert."""
    gaps: list[str] = []
    for field in REQUIRED_MASTER_DATA_FIELDS:
        value = getattr(product, field, None)
        if field == "isin":
            if isin_status(value) != "valid":
                gaps.append("isin")
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            gaps.append(field)
    return gaps


def declared_hedge_currency(product: Any) -> Optional[str]:
    """Erfasste Absicherungswaehrung aus den Stammdaten, sonst None.

    Anbindungspunkt fuer die Waehrungs-Exposure-Rangfolge
    (``currency_exposure_with_source``, PR #856): dort soll nach dem
    gepflegten Exposure-JSON zuerst dieses Stammdatum gelten und erst danach
    die Namensheuristik. Rueckgabe:
      * ISO-4217-Code, wenn ``is_hedged`` wahr ist (``hedge_currency``, sonst
        die Anteilsklassen-Waehrung ``currency``);
      * None, wenn ``is_hedged`` falsch ist ODER nicht erfasst -- der Aufrufer
        unterscheidet beides ueber ``getattr(product, "is_hedged", None)``.
    """
    flag = getattr(product, "is_hedged", None)
    if flag is None or not bool(flag):
        return None
    code = str(getattr(product, "hedge_currency", None) or getattr(product, "currency", None) or "").strip().upper()
    return code or None
