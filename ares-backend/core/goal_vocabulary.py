"""Kanonisches Ziel-Vokabular (RC-CH-1-F1, N-903-02/-03).

Die Tabelle ``goals`` (``ares_schema.sql``) erlaubt per CHECK nur genau die
Werte in ``GOAL_*_DB_VALUES``. Eingaben in Legacy-/ASCII-Schreibweise
("Vermoegensziel", "Primaer", "Gesamtvermoegen", ...) sind fachlich gleich
und werden an EINER Stelle auf den DB-Wert abgebildet:

* API-Grenze: ``GoalCreate`` und ``GoalUpdate`` rufen beide
  ``canonicalize_goal_payload`` (gleiche Regeln, N-903-03).
* Seed-Fingerabdruck des Optimierers (``solver.goal_economic_fingerprint``):
  eine reine Umschreibung zieht keinen neuen Wuerfel (N-903-02). Die DB-Form
  ist die kanonische Form, gespeicherte Daten behalten ihren Seed bitgleich.

Unbekannte Werte bleiben unveraendert (die Validierung lehnt sie ab; der
Fingerabdruck haengt dann am Rohwert). Stdlib-Blattmodul (FAN_OUT_EXEMPT_LEAVES).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

GOAL_FAMILY_DB_VALUES = ("Vermögen", "Cashflow", "Rendite", "Maximierung")
GOAL_TYPE_DB_VALUES = (
    "Kapitalerhalt", "Vermögensziel",
    "Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe",
    "Renditeziel", "Maximierung",
)
GOAL_HARDNESS_DB_VALUES = ("Hart", "Primär", "Opportunistisch")
GOAL_SCOPE_DB_VALUES = ("Beratungsvermögen", "Gesamtvermögen")
GOAL_VALUE_MODE_DB_VALUES = ("nominal", "real")


def _fold_umlauts(raw: str) -> str:
    return (
        raw.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ã¤", "ae")
        .replace("Ã¶", "oe")
        .replace("Ã¼", "ue")
    )


def goal_type_key(value: Any) -> str:
    """lowercase, Leerzeichen -> '_', Umlaute -> ae/oe/ue (auch Mojibake)."""
    return _fold_umlauts(str(value or "").strip().lower().replace(" ", "_"))


def goal_hardness_key(value: Any) -> str:
    return _fold_umlauts(str(value or "").strip().lower())


def _canonical_from(values: tuple[str, ...], value: Any, key: Callable[[Any], str]):
    if not isinstance(value, str):
        return value
    wanted = key(value)
    for candidate in values:
        if key(candidate) == wanted:
            return candidate
    return value


def canonical_goal_type(value):
    """'Vermoegensziel'/'vermögensziel' -> 'Vermögensziel'; unbekannt -> unveraendert."""
    return _canonical_from(GOAL_TYPE_DB_VALUES, value, goal_type_key)


def canonical_goal_family(value):
    return _canonical_from(GOAL_FAMILY_DB_VALUES, value, goal_type_key)


def canonical_goal_hardness(value):
    """'Primaer'/'primär'/'hart' -> 'Primär'/'Hart'; unbekannt -> unveraendert."""
    return _canonical_from(GOAL_HARDNESS_DB_VALUES, value, goal_hardness_key)


def canonical_goal_scope(value):
    """'Beratungsvermoegen'/'gesamtvermoegen' -> DB-Wert; unbekannt -> unveraendert."""
    return _canonical_from(GOAL_SCOPE_DB_VALUES, value, goal_hardness_key)


GOAL_FIELD_CANONICALIZERS: dict[str, Callable[[Any], Any]] = {
    "goal_family": canonical_goal_family,
    "goal_type": canonical_goal_type,
    "goal_scope": canonical_goal_scope,
    "hardness": canonical_goal_hardness,
}


def canonicalize_goal_payload(data: Any) -> Any:
    """Gemeinsame Kanonisierung fuer GoalCreate und GoalUpdate (vor der Pruefung)."""
    if not isinstance(data, Mapping):
        return data
    out = dict(data)
    for field, canonical in GOAL_FIELD_CANONICALIZERS.items():
        if field in out:
            out[field] = canonical(out[field])
    return out
