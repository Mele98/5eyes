"""Sprint U-44 (2026-06-04): HouseMatrix-Defaults YAML-Loader.

Liest config/house_matrix_defaults.yaml und liefert die Tuple-Liste
im selben Format wie portfolio_engine._normalize_house_matrix_defaults
sie konsumiert.

Architektur
-----------
- portfolio_engine ruft load_house_matrix_default_tuples() auf.
- Bei YAML-Fehler / Missing-File: fallback auf hardcoded Defaults.
- Hardcoded-Defaults sind weiterhin im Source als Backup-of-Last-Resort.

Schema-Validation: ein paar harte Asserts. Wenn YAML kaputt
(score_to < score_from, min > target etc.) -> Loader rejecten.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


HOUSE_MATRIX_YAML_FIELDS = (
    "score_from", "score_to", "name",
    "liquidity_min", "liquidity_target", "liquidity_max",
    "bonds_min", "bonds_target", "bonds_max",
    "equities_min", "equities_target", "equities_max",
    "real_estate_min", "real_estate_target", "real_estate_max",
    "alternatives_min", "alternatives_target", "alternatives_max",
    "max_risky_fraction_bps",
    "equity_minimum_bps",
)


# Hardcoded-Fallback identisch zu portfolio_engine. Wird bei YAML-Missing /
# Error genutzt. NICHT entfernen — Last-Resort fuer Boot-Recovery.
_HARDCODED_FALLBACK: tuple[tuple, ...] = (
    (1, 2, "Kapitalschutz", 0, 300, 800, 6500, 7500, 8500, 500, 1200, 2000, 0, 500, 2000, 0, 500, 500, 3000, 0),
    (3, 4, "Defensiv", 0, 200, 500, 5000, 6000, 7000, 1500, 2500, 3000, 500, 1000, 2000, 0, 300, 800, 4500, 0),
    (5, 6, "Ausgewogen", 0, 200, 300, 2500, 3500, 4500, 4000, 4800, 5500, 500, 1000, 2000, 300, 500, 800, 6000, 0),
    (7, 8, "Wachstumsorientiert", 0, 150, 200, 1000, 1600, 2500, 6000, 6800, 7500, 500, 800, 2000, 300, 600, 1000, 8000, 6000),
    (9, 9, "Dynamisch", 0, 100, 200, 500, 800, 1500, 7500, 8000, 8500, 300, 700, 2000, 200, 400, 600, 9000, 7500),
    (10, 10, "Aktien", 0, 100, 200, 0, 200, 500, 8500, 9000, 9500, 200, 500, 2000, 0, 200, 500, 10000, 8500),
)


def _default_yaml_path() -> Path:
    """config/house_matrix_defaults.yaml — relativ zu Backend-Root."""
    backend_root = Path(__file__).resolve().parents[1]
    return backend_root / "config" / "house_matrix_defaults.yaml"


def _validate_entry(entry: dict[str, Any], idx: int) -> None:
    """Schema + Sanity-Check pro Profil."""
    for field in HOUSE_MATRIX_YAML_FIELDS:
        if field not in entry:
            raise ValueError(
                f"HouseMatrix YAML Profil {idx}: Pflichtfeld {field!r} fehlt."
            )

    if entry["score_from"] > entry["score_to"]:
        raise ValueError(
            f"HouseMatrix YAML Profil {idx}: score_from > score_to."
        )

    for bucket in ("liquidity", "bonds", "equities", "real_estate", "alternatives"):
        mn = entry[f"{bucket}_min"]
        tg = entry[f"{bucket}_target"]
        mx = entry[f"{bucket}_max"]
        if not (mn <= tg <= mx):
            raise ValueError(
                f"HouseMatrix YAML Profil {idx} ({entry.get('name')}): "
                f"{bucket} min/target/max-Inversion ({mn}, {tg}, {mx})."
            )


def _entry_to_tuple(entry: dict[str, Any]) -> tuple:
    return tuple(entry[field] for field in HOUSE_MATRIX_YAML_FIELDS)


def load_house_matrix_default_tuples(
    yaml_path: Optional[Path] = None,
) -> tuple[tuple, ...]:
    """Liefert HouseMatrix-Defaults aus YAML, mit Fallback auf
    Hardcoded-Defaults bei jedem Fehler.

    Returns
    -------
    tuple of tuples mit jeweils 20 Werten — identisch zu
    portfolio_engine._normalize_house_matrix_defaults Input.
    """
    path = yaml_path or _default_yaml_path()
    if not path.exists():
        logger.debug(
            "HouseMatrix YAML %s nicht gefunden, fallback Hardcoded.", path,
        )
        return _HARDCODED_FALLBACK

    try:
        import yaml
    except ImportError:
        logger.warning(
            "PyYAML nicht installiert, fallback Hardcoded HouseMatrix-Defaults.",
        )
        return _HARDCODED_FALLBACK

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:  # noqa: BLE001
        logger.exception(
            "HouseMatrix YAML %s konnte nicht geladen werden, fallback Hardcoded.",
            path,
        )
        return _HARDCODED_FALLBACK

    if not isinstance(data, dict) or "profiles" not in data:
        logger.error(
            "HouseMatrix YAML %s: Schema-Fehler ('profiles' fehlt), fallback Hardcoded.",
            path,
        )
        return _HARDCODED_FALLBACK

    profiles = data["profiles"]
    if not isinstance(profiles, list) or len(profiles) != 6:
        logger.error(
            "HouseMatrix YAML %s: erwartet 6 Profile (gefunden: %s), fallback.",
            path, len(profiles) if isinstance(profiles, list) else "?",
        )
        return _HARDCODED_FALLBACK

    try:
        result: list[tuple] = []
        for idx, entry in enumerate(profiles):
            _validate_entry(entry, idx)
            result.append(_entry_to_tuple(entry))
    except (ValueError, KeyError, TypeError) as exc:
        logger.error(
            "HouseMatrix YAML %s: Validation-Fehler (%s), fallback Hardcoded.",
            path, exc,
        )
        return _HARDCODED_FALLBACK

    return tuple(result)
