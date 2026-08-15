"""Canonical domain rules for wealth-position classification.

The investable real-estate bucket represents listed funds/companies and REITs.
A ``WealthPosition`` with ``position_type='Immobilien'`` is instead a direct
property: it belongs to total wealth, has its own price-appreciation input and
may emit a separate rent cashflow.  Treating it as advised/investable wealth
would apply the listed-real-estate total return and the explicit rent at the
same time.
"""
from __future__ import annotations

import unicodedata


DIRECT_REAL_ESTATE_POSITION_TYPE = "Immobilien"
EXTERNAL_WEALTH_ASSIGNMENT = "Anderes Vermögen"
MORTGAGE_POSITION_TYPE = "Hypothek"
LIABILITY_ASSIGNMENT = "Verbindlichkeit"
LIQUIDITY_POSITION_TYPE = "Liquidität"

# Historical fixtures and early SQLite installations used these labels before
# the v4 API vocabulary was frozen.  They are accepted only as explicit,
# one-way read aliases; new API writes remain constrained to the canonical
# values in ``schemas/wealth.py``.
LEGACY_DIRECT_REAL_ESTATE_POSITION_TYPES = frozenset(
    {"Immobilie", "Liegenschaft"}
)
LEGACY_LIQUIDITY_POSITION_TYPES = frozenset(
    {"Bankkonto", "Konto", "Liquiditaet"}
)
LEGACY_DEPOT_POSITION_TYPES = frozenset(
    {"Aktienportfolio", "Wertschriftendepot"}
)
LEGACY_PENSION_POSITION_TYPES = frozenset({"Pensionskasse"})
LEGACY_ADVISORY_WEALTH_ASSIGNMENTS = frozenset({"Beratungsvermoegen"})
LEGACY_EXTERNAL_WEALTH_ASSIGNMENTS = frozenset(
    {"Eigenvermögen", "Gesamtvermögen", "Vorsorge"}
)

SUPPORTED_POSITION_TYPES = frozenset(
    {
        "Depot",
        LIQUIDITY_POSITION_TYPE,
        DIRECT_REAL_ESTATE_POSITION_TYPE,
        "Vorsorge",
        "Alternative",
        MORTGAGE_POSITION_TYPE,
        "Custom",
    }
)
SUPPORTED_ASSIGNMENTS = frozenset(
    {"Beratungsvermögen", EXTERNAL_WEALTH_ASSIGNMENT, LIABILITY_ASSIGNMENT}
)


class WealthPositionSemanticsError(ValueError):
    """Raised when a position classification contradicts the model contract."""


def _canonical_text(value) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().casefold()


def _require_exact_supported(value, supported: frozenset[str], label: str) -> str:
    raw = unicodedata.normalize("NFC", str(value or "")).strip()
    if raw not in supported:
        allowed = ", ".join(sorted(supported))
        raise WealthPositionSemanticsError(
            f"Ungültige {label} {value!r}; erlaubt sind: {allowed}."
        )
    return raw


def canonical_position_type(value) -> str:
    """Return the canonical engine type for an explicitly known legacy label."""
    raw = unicodedata.normalize("NFC", str(value or "")).strip()
    if raw in LEGACY_DIRECT_REAL_ESTATE_POSITION_TYPES:
        return DIRECT_REAL_ESTATE_POSITION_TYPE
    if raw in LEGACY_LIQUIDITY_POSITION_TYPES:
        return LIQUIDITY_POSITION_TYPE
    if raw in LEGACY_DEPOT_POSITION_TYPES:
        return "Depot"
    if raw in LEGACY_PENSION_POSITION_TYPES:
        return "Vorsorge"
    return raw


def canonical_assignment(value) -> str:
    """Return the canonical engine assignment for a known historical label."""
    raw = unicodedata.normalize("NFC", str(value or "")).strip()
    if raw in LEGACY_ADVISORY_WEALTH_ASSIGNMENTS:
        return "Beratungsvermögen"
    if raw in LEGACY_EXTERNAL_WEALTH_ASSIGNMENTS:
        return EXTERNAL_WEALTH_ASSIGNMENT
    return raw


def is_direct_real_estate_position(position_type) -> bool:
    return canonical_position_type(position_type) == DIRECT_REAL_ESTATE_POSITION_TYPE


def is_mortgage_position(position_type) -> bool:
    return _canonical_text(position_type) == _canonical_text(
        MORTGAGE_POSITION_TYPE
    )


def is_liquidity_position(position_type) -> bool:
    return canonical_position_type(position_type) == LIQUIDITY_POSITION_TYPE


def is_external_wealth_assignment(assignment) -> bool:
    return canonical_assignment(assignment) == EXTERNAL_WEALTH_ASSIGNMENT


def is_liability_assignment(assignment) -> bool:
    return _canonical_text(assignment) == _canonical_text(LIABILITY_ASSIGNMENT)


def mortgage_amortization_mode(value) -> str:
    """Return the only amortization modes the projection can account for."""
    raw = _canonical_text(value)
    if raw in {"", "keine", "none"}:
        return "none"
    if "indirekt" in raw or "indirect" in raw:
        return "indirect"
    if "direkt" in raw or "direct" in raw:
        return "direct"
    raise WealthPositionSemanticsError(
        "Unbekannter Amortisationstyp. Erlaubt sind 'Direkt', "
        "'Indirekt (Säule 3a)' oder 'Keine'."
    )


def require_supported_mortgage_amortization(
    position_type,
    amount_rappen,
    amortization_type,
) -> None:
    if not is_mortgage_position(position_type):
        return
    try:
        amount = int(amount_rappen or 0)
    except (TypeError, ValueError) as exc:
        raise WealthPositionSemanticsError(
            "Amortisation muss als ganzzahliger Rappenbetrag erfasst werden."
        ) from exc
    if amount < 0:
        raise WealthPositionSemanticsError(
            "Amortisation darf nicht negativ sein."
        )
    mode = mortgage_amortization_mode(amortization_type)
    if amount > 0 and mode == "none":
        raise WealthPositionSemanticsError(
            "Bei positiver Amortisation muss der Typ 'Direkt' oder "
            "'Indirekt (Säule 3a)' gewählt werden."
        )


def require_supported_position_assignment(position_type, assignment) -> None:
    """Fail closed for classifications the allocation engine cannot model.

    Listed real-estate exposure belongs in a depot allocation.  The dedicated
    ``Immobilien`` position type is a direct property and must remain outside
    the tradable/advised SAA.
    """
    supported_type = _require_exact_supported(
        canonical_position_type(position_type),
        SUPPORTED_POSITION_TYPES,
        "Positionsart",
    )
    supported_assignment = _require_exact_supported(
        canonical_assignment(assignment),
        SUPPORTED_ASSIGNMENTS,
        "Zuordnung",
    )
    if (
        supported_type == DIRECT_REAL_ESTATE_POSITION_TYPE
        and supported_assignment != EXTERNAL_WEALTH_ASSIGNMENT
    ):
        raise WealthPositionSemanticsError(
            "Direktimmobilien müssen als 'Anderes Vermögen' geführt werden. "
            "Kotierte Immobilienfonds oder REITs bitte als Depot-Exposure "
            "in der Anlageklasse Immobilien erfassen."
        )
    if (
        supported_type == MORTGAGE_POSITION_TYPE
        and supported_assignment != LIABILITY_ASSIGNMENT
    ):
        raise WealthPositionSemanticsError(
            "Hypotheken müssen als 'Verbindlichkeit' geführt werden."
        )
