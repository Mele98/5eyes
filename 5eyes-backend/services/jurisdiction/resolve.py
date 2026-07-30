"""WP-Resolver (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Freistehende Jurisdiktions-Resolver.

Baut auf dem additiven Schema aus WP1 auf (models/allocation.py::
CapitalMarketAssumption.jurisdiction/status, models/allocation.py::
BuildingBlock.jurisdiction, models/jurisdiction.py). Zentralisiert die
heute doppelt vorhandene CH-Fallback-Formel
(getattr(mandate, "jurisdiction", None) or "CH"), siehe:
  - services/portfolio_engine.py::_filter_products_by_universe
  - services/cost_disclosure.py::build_cost_disclosure

WICHTIG: Dieses Modul wird bewusst NIRGENDS aus der bestehenden Engine
aufgerufen -- das Wiring in services/portfolio_engine.py/cost_disclosure.py
ist ein spaeteres, noch nicht freigegebenes Arbeitspaket (WP2), das
exklusiven Schreibzugriff auf diese Dateien braucht.

Harte Vorgabe (gilt fuer beide resolve_*_for_jurisdiction-Funktionen):
Es wird NIEMALS eine erfundene Zahl oder None zurueckgegeben. Fehlen
Referenzdaten fuer eine Jurisdiktion, wird JurisdictionReferenceDataMissingError
geworfen -- der Aufrufer muss den fehlenden Fall explizit behandeln (z.B.
Beratungsprozess fuer diese Jurisdiktion sperren), statt versehentlich mit
CH-Zahlen fuer ein anderes Land weiterzurechnen.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from models.allocation import BuildingBlock, CapitalMarketAssumption
from services.jurisdiction.exceptions import (
    JurisdictionNotApprovedError,
    JurisdictionReferenceDataMissingError,
)

# Governance-Status, der fuer require_committee_approved=True Pflicht ist
# (siehe models/allocation.py::CapitalMarketAssumption.status Docstring).
_COMMITTEE_APPROVED_STATUS = "committee_approved"


def resolve_mandate_jurisdiction(mandate) -> str:
    """Zentrale CH-Fallback-Formel fuer die Jurisdiktion eines Mandats.

    NULL/fehlendes Attribut -> "CH" (Backwards-Compat, siehe
    models/mandates.py::Mandate.jurisdiction). Identisch zur heute doppelt
    vorhandenen Inline-Formel in services/portfolio_engine.py::
    _filter_products_by_universe und services/cost_disclosure.py::
    build_cost_disclosure -- diese Aufrufstellen werden in diesem
    Arbeitspaket bewusst NICHT umgestellt (spaeteres WP2).
    """
    return getattr(mandate, "jurisdiction", None) or "CH"


def _ch_current_cma_query(db: Session):
    """Exakte heutige Query aus
    services/portfolio_engine.py::ensure_runtime_reference_data (verifiziert
    per Read vor Implementierung dieses Moduls) -- KEIN jurisdiction-Filter,
    damit Bestandszeilen mit jurisdiction IS NULL weiterhin gefunden werden."""
    return db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    )


def resolve_cma_for_jurisdiction(
    db: Session,
    jurisdiction: str | None,
    require_committee_approved: bool = False,
) -> CapitalMarketAssumption:
    """Loest die aktuelle CapitalMarketAssumption-Zeile fuer eine Jurisdiktion auf.

    - jurisdiction in (None, "CH"): exakt die heutige Query (siehe
      _ch_current_cma_query), CH-Bestandsverhalten bleibt unveraendert.
    - andere jurisdiction: zusaetzlich nach
      CapitalMarketAssumption.jurisdiction == jurisdiction gefiltert.

    Wirft:
    - JurisdictionReferenceDataMissingError, wenn keine passende Zeile
      existiert (fuer KEINE Jurisdiktion, auch nicht CH -- die Funktion
      gibt niemals None zurueck).
    - JurisdictionNotApprovedError, wenn require_committee_approved=True
      und die gefundene Zeile status != "committee_approved" hat.
    """
    label = jurisdiction or "CH"
    if jurisdiction in (None, "CH"):
        cma = _ch_current_cma_query(db).first()
    else:
        cma = _ch_current_cma_query(db).filter(
            CapitalMarketAssumption.jurisdiction == jurisdiction,
        ).first()

    if cma is None:
        raise JurisdictionReferenceDataMissingError(
            f"Keine aktuelle CapitalMarketAssumption-Referenzzeile fuer Jurisdiktion "
            f"'{label}' gefunden (is_current=1, deleted_at IS NULL"
            + ("" if jurisdiction in (None, "CH") else f", jurisdiction='{jurisdiction}'")
            + "). Es wird bewusst keine erfundene Zahl zurueckgegeben."
        )

    if require_committee_approved and cma.status != _COMMITTEE_APPROVED_STATUS:
        raise JurisdictionNotApprovedError(
            f"CapitalMarketAssumption fuer Jurisdiktion '{label}' hat Status "
            f"'{cma.status}', nicht '{_COMMITTEE_APPROVED_STATUS}' -- ohne IC-Freigabe "
            f"darf sie nicht verwendet werden (require_committee_approved=True)."
        )

    return cma


def _ch_building_block_rows(
    db: Session,
    policy_id: str,
    investment_universe: str | None,
) -> list[BuildingBlock]:
    """Exakte heutige Query/Fallback-Logik aus
    services/portfolio_engine.py::_building_block_rows_for_policy (verifiziert
    per Read vor Implementierung dieses Moduls). Gibt bewusst auch eine leere
    Liste zurueck (kein Fehler) -- das ist das heutige, unveraenderte
    CH-Verhalten (Constraint: CH-Pfad bleibt byte-identisch)."""
    base_query = db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy_id,
        BuildingBlock.is_active == 1,
    )
    universe = (investment_universe or "").strip() or None
    rows: list[BuildingBlock] = []
    if universe:
        rows = base_query.filter(BuildingBlock.universe == universe).all()
    if not rows:
        rows = base_query.all()
    return rows


def resolve_building_blocks_for_jurisdiction(
    db: Session,
    policy_id: str,
    jurisdiction: str | None,
    investment_universe: str | None = None,
) -> list[BuildingBlock]:
    """Loest die aktiven BuildingBlock-Zeilen einer Policy fuer eine
    Jurisdiktion auf.

    - jurisdiction in (None, "CH"): exakt die heutige Query/Fallback-Logik
      (siehe _ch_building_block_rows) -- leeres Ergebnis ist hier ein
      gueltiger, unveraenderter Bestandsfall und wirft KEINEN Fehler
      (Constraint: CH-Pfad bleibt byte-identisch zum heutigen Verhalten).
    - andere jurisdiction: zusaetzlich nach BuildingBlock.jurisdiction ==
      jurisdiction gefiltert. Ein leeres Ergebnis wirft hier
      JurisdictionReferenceDataMissingError (fuer ein neues Land duerfen
      nie unbemerkt 0 Bausteine verwendet werden).
    """
    if jurisdiction in (None, "CH"):
        return _ch_building_block_rows(db, policy_id, investment_universe)

    base_query = db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy_id,
        BuildingBlock.is_active == 1,
        BuildingBlock.jurisdiction == jurisdiction,
    )
    universe = (investment_universe or "").strip() or None
    rows: list[BuildingBlock] = []
    if universe:
        rows = base_query.filter(BuildingBlock.universe == universe).all()
    if not rows:
        rows = base_query.all()

    if not rows:
        raise JurisdictionReferenceDataMissingError(
            f"Keine aktiven BuildingBlock-Referenzzeilen fuer Jurisdiktion "
            f"'{jurisdiction}' (policy_id='{policy_id}') gefunden. Es wird bewusst "
            f"keine erfundene Zusammensetzung zurueckgegeben."
        )
    return rows
