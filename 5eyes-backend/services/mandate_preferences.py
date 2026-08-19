"""Strict persisted mandate preferences used by the stochastic sub-model."""
from __future__ import annotations

import json


class MandatePreferenceError(ValueError):
    """A configured building-block preference cannot be modelled exactly."""


BOOLEAN_KEYS = frozenset(
    {
        "altsGold",
        "altsLiquidAlts",
        "altsHedge",
        "altsPe",
        "altsCrypto",
        "bondsHighYield",
        "bondsEmerging",
        "equitiesSmid",
        "noEm",
    }
)
CHOICE_KEYS = frozenset(
    {"equitiesGeo", "bondsDuration", "realestateMarket"}
)
SUPPORTED_KEYS = BOOLEAN_KEYS | CHOICE_KEYS

_CH_EQUITY_CHOICES = frozenset(
    {"Schweiz Fokus", "Global", "Europa", "Schwellenlaender"}
)
_BOND_DURATION_CHOICES = frozenset(
    {"Langfristig", "Kurzfristig", "Gemischt"}
)
_REAL_ESTATE_CHOICES = frozenset({"Schweiz", "Ausland", "Gemischt"})


def _validate_defaults_object(defaults: object, *, jurisdiction: str) -> dict:
    if not isinstance(defaults, dict):
        raise MandatePreferenceError(
            "default_building_blocks_json muss ein JSON-Objekt sein."
        )
    unknown = sorted(set(defaults) - SUPPORTED_KEYS)
    if unknown:
        raise MandatePreferenceError(
            "Unbekannte Building-Block-Praeferenzschluessel: "
            + ", ".join(unknown)
            + "."
        )
    for key in BOOLEAN_KEYS.intersection(defaults):
        if type(defaults[key]) is not bool:
            raise MandatePreferenceError(
                f"Building-Block-Praeferenz {key} muss true oder false sein."
            )
    for key in CHOICE_KEYS.intersection(defaults):
        value = defaults[key]
        if not isinstance(value, str) or not value.strip():
            raise MandatePreferenceError(
                f"Building-Block-Praeferenz {key} muss eine nichtleere Auswahl sein."
            )
        defaults[key] = value.strip()

    normalized_jurisdiction = str(jurisdiction or "CH").strip().upper()
    if normalized_jurisdiction == "CH":
        equities = defaults.get("equitiesGeo")
        if equities is not None and equities not in _CH_EQUITY_CHOICES:
            raise MandatePreferenceError(
                f"Unbekannte CH-Aktienpraeferenz {equities!r}."
            )
        duration = defaults.get("bondsDuration")
        if duration is not None and duration not in _BOND_DURATION_CHOICES:
            raise MandatePreferenceError(
                f"Unbekannte Obligationen-Laufzeitpraeferenz {duration!r}."
            )
        real_estate = defaults.get("realestateMarket")
        if real_estate is not None and real_estate not in _REAL_ESTATE_CHOICES:
            raise MandatePreferenceError(
                f"Unbekannte CH-Immobilienpraeferenz {real_estate!r}."
            )
    return dict(defaults)


def parse_default_building_blocks_json(
    raw: str | None,
    *,
    jurisdiction: str | None,
) -> dict:
    """Parse configured defaults without silently dropping malformed input."""
    if raw is None or str(raw).strip() == "":
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MandatePreferenceError(
            "default_building_blocks_json enthaelt kein gueltiges JSON."
        ) from exc
    return _validate_defaults_object(
        parsed,
        jurisdiction=str(jurisdiction or "CH"),
    )
