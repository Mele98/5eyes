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

from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy import or_

from models.allocation import BuildingBlock, CapitalMarketAssumption
from models.jurisdiction import JurisdictionHomeBiasDefault
from services.jurisdiction.exceptions import (
    CMAValidityWindowError,
    JurisdictionNotApprovedError,
    JurisdictionReferenceDataConflictError,
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


def _current_cma_query(db: Session):
    """Unscoped active-CMA base query; jurisdiction is added by callers."""
    return db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    )


def _ch_current_cma_query(db: Session):
    """Current CH CMA, including legacy rows where jurisdiction is NULL."""
    return _current_cma_query(db).filter(
        or_(
            CapitalMarketAssumption.jurisdiction.is_(None),
            CapitalMarketAssumption.jurisdiction == "CH",
        ),
        CapitalMarketAssumption.tenant_id.is_(None),
    )


def _validity_date(raw, *, field: str, row_id) -> date | None:
    """ISO-Datum (YYYY-MM-DD, optional mit Zeitanteil) -> date.

    CMA-EFFECTIVE-DATE-001: ein nicht lesbares Gueltigkeitsdatum macht die
    Modellauswahl unentscheidbar -> fail-closed statt stillem Ein-/Ausschluss.
    """
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError as exc:
        raise JurisdictionReferenceDataConflictError(
            f"CMA-Zeile {row_id}: {field}='{raw}' ist kein gueltiges ISO-Datum; "
            "die Gueltigkeit ist nicht bestimmbar."
        ) from exc


def _effective_on(rows: list[CapitalMarketAssumption], as_of: date) -> list[CapitalMarketAssumption]:
    """CMA-EFFECTIVE-DATE-001 (ADR-6b): nur Zeilen, deren Gueltigkeitsfenster
    ``as_of`` einschliesst (valid_from <= as_of <= valid_until, valid_until
    leer = offen). Eine vorab erfasste (kuenftige) oder abgelaufene Zeile ist
    nie die wirksame CMA, auch wenn is_current=1 gesetzt ist. Fehlt
    valid_from (NOT NULL im Modell), ist die Zeile nicht wirksam."""
    effective: list[CapitalMarketAssumption] = []
    for row in rows:
        valid_from = _validity_date(row.valid_from, field="valid_from", row_id=row.id)
        valid_until = _validity_date(row.valid_until, field="valid_until", row_id=row.id)
        if valid_from is None or valid_from > as_of:
            continue
        if valid_until is not None and valid_until < as_of:
            continue
        effective.append(row)
    return effective


CMA_FUTURE_VALID_FROM_NOT_SUPPORTED = "CMA_FUTURE_VALID_FROM_NOT_SUPPORTED"
CMA_VALID_UNTIL_IN_PAST = "CMA_VALID_UNTIL_IN_PAST"
CMA_VALIDITY_DATE_INVALID = "CMA_VALIDITY_DATE_INVALID"


def assert_cma_activatable_on(valid_from, valid_until, as_of: date | None = None) -> None:
    """Schreibpfad-Gate (CMA-EFFECTIVE-DATE-001): eine Version, die beim
    Aktivieren is_current=1 bekommt und ihre Vorgaengerin abloest, muss am
    Aktivierungstag wirksam sein. Vorab erfasste (kuenftige) Versionen sind
    erst mit koexistierenden Versionen (ADR-6b) moeglich."""
    today = as_of or date.today()
    try:
        start = _validity_date(valid_from, field="valid_from", row_id="neu")
        end = _validity_date(valid_until, field="valid_until", row_id="neu")
    except JurisdictionReferenceDataConflictError as exc:
        raise CMAValidityWindowError(CMA_VALIDITY_DATE_INVALID, str(exc)) from exc
    if start is None:
        raise CMAValidityWindowError(
            CMA_VALIDITY_DATE_INVALID, "valid_from fehlt; die Gueltigkeit ist nicht bestimmbar."
        )
    if start > today:
        raise CMAValidityWindowError(
            CMA_FUTURE_VALID_FROM_NOT_SUPPORTED,
            f"valid_from {start.isoformat()} liegt nach dem Aktivierungstag "
            f"{today.isoformat()}. Vorab erfasste CMA-Versionen werden noch nicht "
            "unterstuetzt; die bisherige Version bleibt aktiv.",
        )
    if end is not None and end < today:
        raise CMAValidityWindowError(
            CMA_VALID_UNTIL_IN_PAST,
            f"valid_until {end.isoformat()} liegt vor dem Aktivierungstag "
            f"{today.isoformat()}; die Version waere sofort abgelaufen.",
        )


def resolve_effective_cma_or_none(
    db: Session,
    jurisdiction: str | None = None,
    tenant_id: str | None = None,
) -> CapitalMarketAssumption | None:
    """Lesepfad-Variante fuer Anzeigen, die "keine CMA" bereits behandeln:
    derselbe Resolver wie die Engine, fehlende Referenzdaten -> None.
    Mehrdeutigkeit/unlesbare Daten werden NICHT verschluckt."""
    try:
        return resolve_cma_for_jurisdiction(db, jurisdiction, tenant_id=tenant_id)
    except JurisdictionReferenceDataMissingError:
        return None


def resolve_cma_for_jurisdiction(
    db: Session,
    jurisdiction: str | None,
    require_committee_approved: bool = False,
    tenant_id: str | None = None,
    as_of: date | None = None,
) -> CapitalMarketAssumption:
    """Loest die aktuelle CapitalMarketAssumption-Zeile fuer eine Jurisdiktion auf.

    - jurisdiction in (None, "CH"): exakt die heutige Query (siehe
      _ch_current_cma_query), CH-Bestandsverhalten bleibt unveraendert.
      tenant_id wird fuer CH IGNORIERT (kein Tenant-Override auf dem
      CH-Pfad in dieser Ausbaustufe).
    - andere jurisdiction: zusaetzlich nach
      CapitalMarketAssumption.jurisdiction == jurisdiction gefiltert.
      2026-07-31 (Tenant-Override): wenn tenant_id gesetzt ist, wird ZUERST
      eine Zeile mit CapitalMarketAssumption.tenant_id == tenant_id gesucht
      (Tenant-spezifischer Override, gleiches Prinzip wie ProductUniverseEntry).
      Existiert keine solche Zeile, faellt die Suche auf die firmenweite
      Zeile (tenant_id IS NULL) derselben Jurisdiktion zurueck.

    - CMA-EFFECTIVE-DATE-001 (ADR-6b): beruecksichtigt werden nur Zeilen,
      deren valid_from/valid_until-Fenster ``as_of`` (Default: heute)
      einschliesst. Kuenftige oder abgelaufene is_current-Zeilen zaehlen
      nicht; bleibt keine Zeile uebrig, gilt das als "keine Referenzdaten".

    Wirft:
    - JurisdictionReferenceDataMissingError, wenn keine passende Zeile
      existiert (fuer KEINE Jurisdiktion, auch nicht CH -- die Funktion
      gibt niemals None zurueck).
    - JurisdictionNotApprovedError, wenn require_committee_approved=True
      und die gefundene Zeile status != "committee_approved" hat.
    """
    label = jurisdiction or "CH"
    effective_date = as_of or date.today()
    if jurisdiction in (None, "CH"):
        candidates = _effective_on(_ch_current_cma_query(db).all(), effective_date)
        if len(candidates) > 1:
            raise JurisdictionReferenceDataConflictError(
                "Mehrere aktuelle CH-CMA-Referenzzeilen gefunden; die "
                "Modellauswahl ist nicht eindeutig."
            )
        cma = candidates[0] if candidates else None
    else:
        jurisdiction_query = _current_cma_query(db).filter(
            CapitalMarketAssumption.jurisdiction == jurisdiction,
        )
        cma = None
        if tenant_id:
            tenant_candidates = _effective_on(jurisdiction_query.filter(
                CapitalMarketAssumption.tenant_id == tenant_id,
            ).all(), effective_date)
            if len(tenant_candidates) > 1:
                raise JurisdictionReferenceDataConflictError(
                    f"Mehrere aktuelle {jurisdiction}-CMA-Zeilen fuer Tenant "
                    f"{tenant_id} gefunden."
                )
            cma = tenant_candidates[0] if tenant_candidates else None
        if cma is None:
            firmwide_candidates = _effective_on(jurisdiction_query.filter(
                CapitalMarketAssumption.tenant_id.is_(None),
            ).all(), effective_date)
            if len(firmwide_candidates) > 1:
                raise JurisdictionReferenceDataConflictError(
                    f"Mehrere aktuelle firmenweite {jurisdiction}-CMA-Zeilen gefunden."
                )
            cma = firmwide_candidates[0] if firmwide_candidates else None

    if cma is None:
        raise JurisdictionReferenceDataMissingError(
            f"Keine aktuelle CapitalMarketAssumption-Referenzzeile fuer Jurisdiktion "
            f"'{label}' gefunden (is_current=1, deleted_at IS NULL, "
            f"gueltig am {effective_date.isoformat()}"
            + ("" if jurisdiction in (None, "CH") else f", jurisdiction='{jurisdiction}'")
            + (f", tenant_id='{tenant_id}' oder firmenweit" if tenant_id and jurisdiction not in (None, "CH") else "")
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
        or_(
            BuildingBlock.jurisdiction.is_(None),
            BuildingBlock.jurisdiction == "CH",
        ),
    )
    universe = (investment_universe or "").strip() or None
    rows: list[BuildingBlock] = []
    if universe:
        rows = base_query.filter(BuildingBlock.universe == universe).all()
        if not rows:
            raise JurisdictionReferenceDataMissingError(
                "Keine aktiven BuildingBlock-Referenzzeilen fuer das explizit "
                f"gewaehlte Universum '{universe}' und Jurisdiktion 'CH' "
                f"(policy_id='{policy_id}') gefunden."
            )
    else:
        rows = base_query.all()
    return _prefer_exact_jurisdiction_rows(rows, "CH")


def _prefer_exact_jurisdiction_rows(
    rows: list[BuildingBlock],
    jurisdiction: str,
) -> list[BuildingBlock]:
    """Merge shared and country-specific sleeves without order dependence.

    ``jurisdiction IS NULL`` is the shared universe used by every country for
    generic sleeves.  An explicit country row replaces the shared row with
    the same economic identity; foreign country rows never reach this helper.
    """
    grouped: dict[tuple[str, str, str], list[BuildingBlock]] = {}
    for row in rows:
        key = (
            str(getattr(row, "asset_class", "") or ""),
            str(getattr(row, "sub_asset_class", "") or ""),
            str(getattr(row, "universe", "") or ""),
        )
        grouped.setdefault(key, []).append(row)

    selected: dict[tuple[str, str, str], BuildingBlock] = {}
    for key, candidates in grouped.items():
        exact = [
            row for row in candidates
            if getattr(row, "jurisdiction", None) == jurisdiction
        ]
        shared = [
            row for row in candidates
            if getattr(row, "jurisdiction", None) is None
        ]
        preferred = exact if exact else shared
        if len(preferred) > 1:
            scope = f"Jurisdiktion {jurisdiction}" if exact else "shared/NULL"
            raise JurisdictionReferenceDataConflictError(
                "Mehrere gleichrangige BuildingBlock-Zeilen fuer "
                f"{key!r} im Scope {scope}; Risky-Fraction und Submix sind "
                "nicht eindeutig."
            )
        if preferred:
            selected[key] = preferred[0]
    return list(selected.values())


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
    - andere jurisdiction: shared rows (jurisdiction IS NULL) plus exact
      country rows. Exact country rows deterministically override shared rows
      with the same asset/sub-asset/universe identity. At least one exact row
      is required, so an unsupported country cannot silently run on shared
      data alone. Ein leeres Ergebnis wirft hier
      JurisdictionReferenceDataMissingError (fuer ein neues Land duerfen
      nie unbemerkt 0 Bausteine verwendet werden).
    """
    if jurisdiction in (None, "CH"):
        return _ch_building_block_rows(db, policy_id, investment_universe)

    base_query = db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy_id,
        BuildingBlock.is_active == 1,
        or_(
            BuildingBlock.jurisdiction.is_(None),
            BuildingBlock.jurisdiction == jurisdiction,
        ),
    )
    universe = (investment_universe or "").strip() or None
    rows: list[BuildingBlock] = []
    if universe:
        rows = base_query.filter(BuildingBlock.universe == universe).all()
        if not rows:
            raise JurisdictionReferenceDataMissingError(
                "Keine aktiven BuildingBlock-Referenzzeilen fuer das explizit "
                f"gewaehlte Universum '{universe}' und Jurisdiktion "
                f"'{jurisdiction}' (policy_id='{policy_id}') gefunden."
            )
    else:
        rows = base_query.all()

    if not rows or not any(
        getattr(row, "jurisdiction", None) == jurisdiction for row in rows
    ):
        raise JurisdictionReferenceDataMissingError(
            f"Keine aktiven BuildingBlock-Referenzzeilen fuer Jurisdiktion "
            f"'{jurisdiction}' (policy_id='{policy_id}') gefunden. Es wird bewusst "
            f"keine erfundene Zusammensetzung zurueckgegeben."
        )
    return _prefer_exact_jurisdiction_rows(rows, jurisdiction)


def resolve_home_bias_defaults(
    db: Session,
    jurisdiction: str | None,
    preference_key: str,
    preference_value: str,
) -> list[tuple[str, int, str]]:
    """Loest die Home-Bias-Split-Zeilen (sub_asset_class, split_bps, rationale)
    fuer eine Jurisdiktion + Praeferenz-Kombination auf, sortiert nach
    sort_order (NULL zuletzt).

    2026-07-31 (Deutschland-Anbindung): liest models/jurisdiction.py::
    JurisdictionHomeBiasDefault -- die generische Gegenstelle zu den heute
    hartcodierten eq_splits/bond_splits/re_splits-Tupeln in
    services/portfolio_engine.py::_build_sub_allocations (z.B.
    preference_key="equitiesGeo", preference_value="Deutschland Fokus").

    - jurisdiction in (None, "CH"): wirft ValueError -- CH liest weiterhin
      NIE aus dieser Tabelle, die hartcodierten Python-Tupel in
      _build_sub_allocations bleiben fuer CH die alleinige Quelle
      (Constraint: CH-Pfad bleibt byte-identisch). Ein Aufruf mit
      jurisdiction in (None, "CH") ist ein Programmierfehler des Aufrufers,
      kein normaler Laufzeitfall.
    - andere jurisdiction: leeres Ergebnis -> JurisdictionReferenceDataMissingError
      (nie eine erfundene Zusammensetzung zurueckgeben).
    """
    if jurisdiction in (None, "CH"):
        raise ValueError(
            "resolve_home_bias_defaults() darf fuer jurisdiction in (None, 'CH') "
            "nicht aufgerufen werden -- der CH-Pfad nutzt weiterhin ausschliesslich "
            "die hartcodierten Splits in services/portfolio_engine.py::_build_sub_allocations."
        )

    rows = (
        db.query(JurisdictionHomeBiasDefault)
        .filter(
            JurisdictionHomeBiasDefault.jurisdiction_code == jurisdiction,
            JurisdictionHomeBiasDefault.preference_key == preference_key,
            JurisdictionHomeBiasDefault.preference_value == preference_value,
            JurisdictionHomeBiasDefault.deleted_at.is_(None),
        )
        .order_by(JurisdictionHomeBiasDefault.sort_order.asc().nulls_last())
        .all()
    )
    if not rows:
        raise JurisdictionReferenceDataMissingError(
            f"Keine Home-Bias-Default-Zeilen fuer Jurisdiktion '{jurisdiction}' "
            f"(preference_key='{preference_key}', preference_value='{preference_value}') "
            f"gefunden. Es wird bewusst keine erfundene Zusammensetzung zurueckgegeben."
        )
    return [(row.sub_asset_class, row.split_bps, row.rationale_text or "") for row in rows]
