"""PensionTransferLedgerV1 (PENSION-TRANSFER-LEDGER-001, 2026-10-19).

Folgefix zu PR #642 nach Codex-Review 2026-10-18. Ein Vorsorgebezug ist eine
UMBUCHUNG von gebundenem in freies Vermoegen. Damit sie genau einmal und
bilanziell sauber passiert, haelt dieser Ledger pro Quelle eine Zeile:

    opening + deterministisches Wachstum = gross_withdrawal + closing
    gross_withdrawal                      = lumpsum_tax + net_advisory_inflow

Aktuelles Modell = VOLLBEZUG (``transfer_mode = "full"``, closing = 0).
Teil- und Ratenbezuege sind bewusst NICHT implementiert: dafuer braeuchte es
einen persistierten Restbestand je Rate (siehe
docs/planning/2026-10-18-vorsorge-benefit-reconciliation.md, Abschnitt 6). Bis dahin ist ein
verknuepfter Zufluss fail-closed einmalig und nominal.

Der Ledger ist die EINZIGE Basis der Consumer im Engine-Pfad:
- ``payout_series_rappen`` (Netto in freies Vermoegen) fuer die Zufluss-Serie,
- ``linked_replacement_series_rappen`` ersetzt den frei erfassten Betrag des
  verknuepften Zuflusses (der Zufluss bestimmt nur das JAHR des Bezugs),
- Reasoning-Saetze werden aus den Zeilen formuliert.

Herkunft der Zeile: ``linked_inflow`` (Berater hat den Bezug als Zufluss mit
linked_position_id erfasst; hat IMMER Vorrang, auch wenn er hinter dem
Horizont liegt) oder ``auto`` (Bezugsjahr aus Faelligkeit/Verfuegbar ab/
Rentenalter). Der Horizont begrenzt nur die Sichtbarkeit
(``within_horizon``), nie die Quellenentscheidung -- Ledger-Zeilen und Hash
sind horizontinvariant.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

PENSION_TRANSFER_LEDGER_VERSION = "PensionTransferLedgerV1"

# Reason-Codes (API 409/422 und Engine-Fehler teilen dieselben Codes).
REASON_SOURCE_LINKED = "PENSION_SOURCE_LINKED"
REASON_SOURCE_ALREADY_LINKED = "PENSION_SOURCE_ALREADY_LINKED"
REASON_SOURCE_LINK_ORPHAN = "PENSION_SOURCE_LINK_ORPHAN"
REASON_SOURCE_MULTIPLE_LINKS = "PENSION_SOURCE_MULTIPLE_LINKS"
REASON_TRANSFER_NOT_ONE_TIME = "PENSION_TRANSFER_NOT_ONE_TIME"
REASON_TRANSFER_BEFORE_VALUATION = "PENSION_TRANSFER_BEFORE_VALUATION"

# Partieller Unique-Index: hoechstens ein aktiver, nicht geloeschter Link je
# Quelle. Dieselbe Definition in Model (Bootstrap), Runtime-Patch und Alembic.
ACTIVE_LINK_INDEX_NAME = "ux_wealth_inflow_one_active_pension_link"
ACTIVE_LINK_INDEX_PREDICATE = (
    "linked_position_id IS NOT NULL AND is_active = 1 AND deleted_at IS NULL"
)


class PensionTransferLedgerError(ValueError):
    """Inkonsistenter Transferzustand -- fail-closed statt still umgedeutet."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(f"{message} [{reason_code}]")
        self.reason_code = reason_code
        self.message = message


def linked_transfer_violation(*, is_recurring, frequency, duration_years, value_mode) -> str | None:
    """Warum ein verknuepfter Zufluss kein einmaliger nominaler Vollbezug ist
    (None = gueltig). Gemeinsame Regel fuer Schema (422) und Engine."""
    if int(is_recurring or 0) != 0 or str(frequency or "einmalig") != "einmalig" or duration_years not in (None, 0):
        return (
            "Ein mit einer Vorsorge-Position verknüpfter Zufluss ist der einmalige "
            "Kapitalbezug (Vollbezug) und darf nicht wiederkehrend sein. Teil- oder "
            "Ratenbezüge werden noch nicht unterstützt."
        )
    if str(value_mode or "nominal") != "nominal":
        return (
            "Ein mit einer Vorsorge-Position verknüpfter Kapitalbezug wird nominal "
            "gebucht (Wertmodus 'nominal')."
        )
    return None


@dataclass(frozen=True)
class PensionTransferRow:
    source_position_id: str
    source_label: str
    pension_type: str
    transfer_mode: str
    origin: str
    linked_inflow_id: str | None
    payout_year: int
    payout_offset: int
    within_horizon: bool
    opening_bound_balance_rappen: int
    gross_withdrawal_rappen: int
    lumpsum_tax_rappen: int
    tax_source: str
    net_advisory_inflow_rappen: int
    closing_bound_balance_rappen: int
    recorded_inflow_amount_rappen: int | None
    currency: str
    fx_basis: str

    def __post_init__(self):
        if self.transfer_mode != "full" or self.closing_bound_balance_rappen != 0:
            raise PensionTransferLedgerError(
                REASON_TRANSFER_NOT_ONE_TIME, "Nur Vollbezug (Restbestand 0) ist modelliert.",
            )
        amounts = (
            self.opening_bound_balance_rappen, self.gross_withdrawal_rappen,
            self.lumpsum_tax_rappen, self.net_advisory_inflow_rappen,
        )
        if any(type(value) is not int or value < 0 for value in amounts):
            raise ValueError("PensionTransferRow: Betraege muessen nicht-negative Rappen sein.")
        if self.gross_withdrawal_rappen != self.lumpsum_tax_rappen + self.net_advisory_inflow_rappen:
            raise ValueError("PensionTransferRow: Brutto != Steuer + Netto.")

    def identity(self) -> dict:
        """Horizontinvariante Felder fuer den Hash (ohne Sichtbarkeitsflag)."""
        data = asdict(self)
        data.pop("within_horizon")
        return data


@dataclass(frozen=True)
class PensionTransferLedgerV1:
    rows: tuple[PensionTransferRow, ...]
    valuation_year: int
    currency: str
    policy_version: str
    input_hash: str
    version: str = PENSION_TRANSFER_LEDGER_VERSION

    @classmethod
    def build(cls, rows, *, valuation_year: int, currency: str, policy_version: str):
        ordered = tuple(sorted(rows, key=lambda r: (r.payout_year, r.source_position_id)))
        payload = json.dumps(
            {
                "version": PENSION_TRANSFER_LEDGER_VERSION,
                "policy_version": policy_version,
                "valuation_year": int(valuation_year),
                "currency": currency,
                "rows": [row.identity() for row in ordered],
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return cls(
            rows=ordered,
            valuation_year=int(valuation_year),
            currency=currency,
            policy_version=policy_version,
            input_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )

    def net_payout_series(self, horizon: int) -> list[int]:
        series = [0] * max(0, int(horizon))
        for row in self.rows:
            if row.within_horizon:
                series[row.payout_offset] += row.net_advisory_inflow_rappen
        return series

    def linked_replacement_series(self, horizon: int) -> list[int]:
        """Was die allgemeine Zufluss-Serie fuer verknuepfte Zufluesse
        materialisiert (einmalig, nominal) -- wird durch das Ledger-Netto
        ersetzt."""
        series = [0] * max(0, int(horizon))
        for row in self.rows:
            if row.within_horizon and row.origin == "linked_inflow":
                series[row.payout_offset] += int(row.recorded_inflow_amount_rappen or 0)
        return series
