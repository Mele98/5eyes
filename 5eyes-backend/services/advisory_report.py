"""Sprint U-P21 (2026-05-24): Advisory-Report-Aggregator.

Liefert die vollständige Daten-Struktur für den 15-Seiten institutionellen
Depotcheck-Report. Konsumiert die bestehenden 5eyes-Engines (portfolio_engine,
depot_check, foundation_example, risk_matrix etc.) und aggregiert sie in
ein stabiles JSON-Schema, das sowohl die React-Sub-App (5eyes-electron/
frontend/reporting/) als auch das Server-PDF (services/pdf/documents/
advisory_report.py, kommt in U-P26) konsumieren.

Architektur-Prinzipien:
- 1 Funktion pro Sektion (private `_build_<sektion>`), das Modul bleibt
  modular ohne aufgeblähten Single-Page-Code.
- Daten kommen primär aus Engine-Berechnungen. Berater-Texte (Anmerkungen,
  Vorgehen) sind Override-Punkte: heute Default-Platzhalter, später per
  `MandateReportOverrides`-Tabelle persistierbar (folgt in eigenem Sprint).
- Statische Inhalte (Pruefpunkte-Beschreibungen, Investmentgrundsaetze,
  Disclaimer) leben in Konstanten am Modul-Ende — der Berater darf sie
  per Admin-UI editieren, default ist 5eyes-Hauspruefung.

Branding-Disziplin (per Memory): KEINE Dritt-Marken in Code/Texten/PDF.
Alle Bezeichnungen sind 5eyes-eigen.

Bezug: docs/planning/2026-05-24-sprint-u-p21-advisory-report-backend.md
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from models.clients import Client
from models.mandates import Mandate
from models.users import User


# ---------------------------------------------------------------------------
# Entry-Point
# ---------------------------------------------------------------------------

_CACHE_KEY = "_advisory_aggregator_call_cache"


def _aggregator_cache_get(db: Session, key: Any, factory) -> Any:
    """Sprint U-18: Call-scoped Cache fuer Sub-Queries innerhalb eines
    compute_advisory_report()-Aufrufs.

    Wenn der Aufruf-Cache nicht gesetzt ist (Funktion direkt aufgerufen
    ohne compute() drumherum -> z.B. in Helper-Tests), faellt der Helper
    auf factory() zurueck — kein Crash, nur kein Caching.
    """
    cache = db.info.get(_CACHE_KEY)
    if cache is None:
        return factory()
    if key not in cache:
        cache[key] = factory()
    return cache[key]


def _cached_latest_recommendation_run(db: Session, mandate: Mandate) -> Any:
    """U-18: einmal pro compute() statt 4x (Sektionen 5, 8-10, 13)."""
    from models.review import RecommendationRun
    return _aggregator_cache_get(
        db,
        ("latest_run", mandate.id),
        lambda: (
            db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        ),
    )


def _cached_latest_rec_positions(db: Session, mandate: Mandate) -> list[Any]:
    """U-18: einmal pro compute() statt 4x."""
    from models.review import RecommendationPosition
    def _factory():
        run = _cached_latest_recommendation_run(db, mandate)
        if run is None:
            return []
        return (
            db.query(RecommendationPosition)
            .filter(RecommendationPosition.run_id == run.id)
            .all()
        )
    return _aggregator_cache_get(db, ("rec_positions", mandate.id), _factory)


def _cached_rec_products_by_id(db: Session, mandate: Mandate) -> dict[str, Any]:
    """U-18: einmal pro compute() statt 3x. Liefert dict id -> Product."""
    from models.review import Product
    def _factory():
        positions = _cached_latest_rec_positions(db, mandate)
        product_ids = [p.product_id for p in positions if p.product_id]
        if not product_ids:
            return {}
        products = (
            db.query(Product).filter(Product.id.in_(product_ids)).all()
        )
        return {p.id: p for p in products}
    return _aggregator_cache_get(db, ("rec_products_by_id", mandate.id), _factory)


def _cached_current_ta(db: Session, mandate: Mandate) -> Any:
    """U-18: einmal pro compute() statt 5+ Lookups (Sektionen 4, 7, 11, 12, 13)."""
    from models.allocation import TargetAllocation
    return _aggregator_cache_get(
        db,
        ("current_ta", mandate.id),
        lambda: (
            db.query(TargetAllocation)
            .filter(
                TargetAllocation.mandate_id == mandate.id,
                TargetAllocation.is_current == 1,
                TargetAllocation.deleted_at.is_(None),
            )
            .first()
        ),
    )


def _cached_current_ra(db: Session, mandate: Mandate) -> Any:
    """U-18: einmal pro compute() statt 4x (Sektionen 4, 7, 12)."""
    from models.profiling import RiskAssessment
    def _factory():
        # Wir laden die JUENGSTE (created_at DESC), die _build_risikoprofilierung
        # nutzt, UND fallen darunter auf is_current=1 zurueck wenn die juengste
        # nicht current ist (Edge-Case wenn alte aktive Zeile noch da).
        return (
            db.query(RiskAssessment)
            .filter(RiskAssessment.mandate_id == mandate.id)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
    return _aggregator_cache_get(db, ("current_ra_latest", mandate.id), _factory)


def _cached_current_ra_is_current(db: Session, mandate: Mandate) -> Any:
    """Spezial-Variante mit is_current=1 + deleted_at IS NULL Filter.
    _build_risikoprofilierung nutzt diese, _check_risikoprofil + _resolve
    nutzen `_cached_current_ra`. Beide Wege werden gecached.
    """
    from models.profiling import RiskAssessment
    def _factory():
        return (
            db.query(RiskAssessment)
            .filter(
                RiskAssessment.mandate_id == mandate.id,
                RiskAssessment.is_current == 1,
                RiskAssessment.deleted_at.is_(None),
            )
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
    return _aggregator_cache_get(db, ("current_ra_is_current", mandate.id), _factory)


def _cached_active_goals(db: Session, mandate: Mandate) -> list[Any]:
    """U-18: einmal pro compute() statt 3x (Sektionen 4, 4-Header, 11)."""
    from models.wealth import Goal
    def _factory():
        return (
            db.query(Goal)
            .filter(Goal.mandate_id == mandate.id, Goal.is_active == 1)
            .all()
        )
    return _aggregator_cache_get(db, ("active_goals", mandate.id), _factory)


def _cached_active_cashflows(db: Session, client_id: str) -> list[Any]:
    """U-18: einmal pro compute() statt 2x (Sektionen 4, 4-Header)."""
    from models.wealth import Cashflow
    def _factory():
        return (
            db.query(Cashflow)
            .filter(Cashflow.client_id == client_id, Cashflow.is_active == 1)
            .all()
        )
    return _aggregator_cache_get(db, ("active_cashflows", client_id), _factory)


def compute_advisory_report(
    db: Session,
    mandate: Mandate,
    *,
    advisor: User | None = None,
) -> dict[str, Any]:
    """Aggregate the full 15-section advisory report payload for a mandate.

    Parameter
    ---------
    db
        Active SQLAlchemy session.
    mandate
        The mandate the report is generated for. Must be a loaded ORM
        instance with `client_id` set.
    advisor
        Optional. The advisor on record (used for cover.advisor_name).
        Falls back to "—" when None.

    Returns
    -------
    dict
        Stable JSON-Schema (see `advisory_report_schema_v2` in
        docs/planning/2026-05-24-sprint-u-p21-advisory-report-backend.md).
        All values are either primitive types, lists, or dicts — directly
        JSON-serializable.
    """
    # U-18 (Roadmap-Punkt 18): Call-scoped Cache aktivieren. Ohne den
    # Cache werden TargetAllocation 7x, RecommendationRun 4x, RiskAssessment
    # 4x, Goals 3x etc. abgefragt — die Call-Helper unten greifen auf
    # db.info[_CACHE_KEY] zu und liefern jeden Eintrag nur 1x pro compute().
    # Try/Finally garantiert dass der Cache am Ende sauber abgeraeumt wird,
    # auch im Exception-Pfad.
    db.info[_CACHE_KEY] = {}
    try:
        return _compute_advisory_report_inner(db, mandate, advisor=advisor)
    finally:
        db.info.pop(_CACHE_KEY, None)


def _compute_advisory_report_inner(
    db: Session,
    mandate: Mandate,
    *,
    advisor: User | None = None,
) -> dict[str, Any]:
    """Innere Implementierung — Cache-Lifecycle wird vom Wrapper gemanagt."""
    client = _load_client_or_raise(db, mandate)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # Depot-Check einmal berechnen, an mehrere Sektionen weiterreichen
    # (Erkenntnisse-Ampel, Asset Allocation, Währungen, Branchen).
    from services.depot_check import compute_depot_check
    dc = compute_depot_check(db, mandate) or {}
    ist_basiert_auf_soll = _current_amounts_missing_for_latest_run(db, mandate)
    equity_sector_context = _build_equity_sector_context(db, mandate)
    # Sprint U-P28 PR B: Berater-Overrides werden EINMAL geladen und an die
    # vier betroffenen Sektion-Builder weitergegeben. Leere/fehlende Felder
    # fallen automatisch auf den Auto-Default-Text der jeweiligen Sektion
    # zurück (Default-Disziplin, siehe `_override_or_default`).
    notes = _load_report_notes(db, mandate)

    return {
        "schema_version": 2,
        "mandate_id": str(getattr(mandate, "id", "") or ""),
        "generated_at": generated_at,
        # --- Sektion 1
        "cover": _build_cover(mandate, client, advisor, generated_at),
        # --- Sektion 2
        "disclaimer": _build_disclaimer(),
        # --- Sektion 3
        "inhaltsverzeichnis": _build_inhaltsverzeichnis(),
        # --- Sektion 4
        "ausgangslage": _build_ausgangslage(db, mandate, client),
        # --- Sektion 5
        "positionen": _build_positionen(db, mandate),
        # --- Sektion 6
        "pruefpunkte": _build_pruefpunkte(),
        # --- Sektion 7
        "erkenntnisse": _build_erkenntnisse(db, mandate, dc=dc),
        # --- Sektion 8
        "asset_allocation": _build_asset_allocation(
            dc, notes=notes, ist_basiert_auf_soll=ist_basiert_auf_soll
        ),
        # --- Sektion 9
        "risikowaehrungen": _build_risikowaehrungen(
            dc, notes=notes, ist_basiert_auf_soll=ist_basiert_auf_soll
        ),
        # --- Sektion 10
        "branchen": _build_branchen(
            dc,
            notes=notes,
            equity_sector_context=equity_sector_context,
            ist_basiert_auf_soll=ist_basiert_auf_soll,
        ),
        # --- Sektion 11
        "goal_based_investing": _build_goal_based_investing(db, mandate),
        # --- Sektion 12
        "risikoprofilierung": _build_risikoprofilierung(db, mandate),
        # --- Sektion 13
        "building_blocks": _build_building_blocks(db, mandate),
        # --- Sektion 14
        "statement_pm": _build_statement_pm(),
        # --- Sektion 15
        "weiteres_vorgehen": _build_weiteres_vorgehen(notes=notes),
        # --- Sektion 16 (additiv, U-FINMA-2.2)
        "beratungsprotokoll": _build_beratungsprotokoll(db, mandate),
        # --- Sektion 17 (additiv, U-70)
        "stress_replay": _build_stress_replay(db, mandate),
        # --- Sektion 18 (additiv, U-68): FIDLEG Art. 9/26 Interessenkonflikte
        "conflict_disclosures": _build_conflict_disclosures(db, mandate),
        # --- Kostenausweis Ex-ante (FIDLEG Art. 8/9): bisher nur im PDF-Renderer
        # (self-populate). Jetzt auch im Aggregator-Payload, damit ALLE Konsumenten
        # (React-Reporting, API) den Kostenausweis konsistent erhalten.
        "cost_disclosure": _build_cost_disclosure_section(db, mandate),
        # --- Sektion 19 (additiv, U-66): FIDLEG-Suitability-Compliance-Audit
        "suitability_compliance": _build_suitability_compliance(db, mandate),
        # --- Sektion 20 (additiv, U-73+U-74): Engine-Modell-Audit
        "methodology_models": _build_methodology_models(db),
        # --- Sektion 21 (additiv, U-69): Recommendation-Methodology-Audit
        "recommendation_methodology": _build_recommendation_methodology(db, mandate),
        # --- Sektion 22 (additiv, U-22): Mandate-Lock-Status
        "mandate_lock_status": _build_mandate_lock_status(db, mandate),
        # --- Sektion 23 (additiv, U-21): Liquidity-Cascade Stage-3 Warning
        "liquidity_cascade": _build_liquidity_cascade(db, mandate),
        # --- Sektion 28 (additiv, Roadmap #61): Reserve-Erklaerbarkeit
        "reserve_explainability": _build_reserve_explainability(db, mandate),
        # --- Sektion 24 (additiv, U-94): Optimizer-Run-History
        "optimizer_run_history": _build_optimizer_run_history(db, mandate),
        # --- Sektion 25 (additiv, U-97): Performance-Attribution (Brinson)
        "performance_attribution": _build_performance_attribution(db, mandate),
        # --- Sprint C2 (2026-06-08): Engine-Configuration
        "engine_configuration": _build_engine_configuration(db, mandate),
        # --- Sektion 26 (additiv, U-71): Policy-A/B-Backtest
        "ab_backtest": _build_ab_backtest(db, mandate),
        # --- Sektion 27 (additiv, U-FINMA-3, re-architektiert 2026-06-09):
        # SuitabilityCheck-Summary fuer Berater-Sicht (vs. suitability_compliance
        # in Sektion 19, das eine Aggregat-Statistik aller AdvisoryLogs ist).
        "suitability_summary": _build_suitability_summary(db, mandate),
    }


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def _load_client_or_raise(db: Session, mandate: Mandate) -> Client:
    client_id = getattr(mandate, "client_id", None)
    if not client_id:
        raise ValueError(f"Mandat {getattr(mandate, 'id', '?')!r} ohne client_id.")
    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise ValueError(f"Client {client_id!r} fuer Mandat nicht gefunden.")
    return client


# ---------------------------------------------------------------------------
# Sprint U-P28 PR B — Berater-Overrides für die 4 betroffenen Sektionen.
# ---------------------------------------------------------------------------

def _load_report_notes(db: Session, mandate: Mandate) -> Any | None:
    """Lädt die `MandateReportNotes`-Zeile für ein Mandat, oder None.

    Lazy-Import, damit der Aggregator auch in Test-Szenarien funktioniert,
    in denen die Tabelle nicht angelegt wurde. Das ist konsistent zu den
    anderen Sektion-Buildern, die ihre Modelle ebenfalls lazy importieren.
    """
    try:
        from models.review import MandateReportNotes

        return (
            db.query(MandateReportNotes)
            .filter(MandateReportNotes.mandate_id == mandate.id)
            .first()
        )
    except Exception:  # noqa: BLE001 — robust gegen Schema-Mismatch in alten DBs
        return None


def _override_or_default(value: Any, default: str) -> str:
    """Wenn `value` (Berater-Override) gesetzt und nicht leer ist → nutzen.

    Sonst Auto-Default (Status-Quo-Verhalten vor U-P28). Leerzeichen-only
    gilt als „nicht gepflegt" und triggert ebenfalls den Default.
    """
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return str(value)


def _parse_notes_json_list(raw: Any) -> list[str]:
    """Defensiv: kaputtes JSON in der DB → leere Liste, kein Crash.

    Identisches Verhalten wie `routers.allocation._parse_json_list`, hier
    lokal um zirkuläre Imports zu vermeiden.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item is not None]


def _latest_recommendation_positions(db: Session, mandate: Mandate) -> list[Any]:
    # U-18: Cache-aware; vorher 3 separate Aufrufe, jetzt 1 Lookup.
    return _cached_latest_rec_positions(db, mandate)


def _latest_recommendation_positions_with_products(
    db: Session,
    mandate: Mandate,
) -> list[tuple[Any, Any]]:
    # U-18: Beide Sub-Queries (rec_positions + Products) sind cached.
    rec_positions = _cached_latest_rec_positions(db, mandate)
    if not rec_positions:
        return []
    products_by_id = _cached_rec_products_by_id(db, mandate)
    return [
        (pos, products_by_id[pos.product_id])
        for pos in rec_positions
        if pos.product_id in products_by_id
    ]


def _current_or_target_amount_rappen(rec_pos: Any) -> int:
    current_amount = _safe_int(getattr(rec_pos, "current_amount_rappen", 0))
    if current_amount > 0:
        return current_amount
    return _safe_int(getattr(rec_pos, "target_amount_rappen", 0))


def _current_amounts_missing_for_latest_run(db: Session, mandate: Mandate) -> bool:
    """True when current values are absent and IST is therefore SOLL-backed."""
    rec_positions = _latest_recommendation_positions(db, mandate)
    if not rec_positions:
        return False
    return all(getattr(pos, "current_amount_rappen", None) is None for pos in rec_positions)


def _build_equity_sector_context(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Sector distribution normalized within the equity sleeve only."""
    from services.product_exposures import aggregate_exposures, sector_exposure_for_product

    rows = _latest_recommendation_positions_with_products(db, mandate)
    total_amount = 0
    equity_amount = 0
    equity_rows: list[tuple[Any, Any, int]] = []
    for rec_pos, product in rows:
        amount = _current_or_target_amount_rappen(rec_pos)
        if amount <= 0:
            continue
        total_amount += amount
        if _bucket_key_from_asset_class(str(getattr(product, "asset_class", "") or "")) != "equities":
            continue
        equity_amount += amount
        equity_rows.append((rec_pos, product, amount))

    if total_amount <= 0 or equity_amount <= 0:
        return {
            "ist": {},
            "soll": {},
            "anteil_aktien_bps": 0,
        }

    sector_inputs: dict[str, dict[str, int]] = {}
    ist_weights: dict[str, int] = {}
    soll_weights: dict[str, int] = {}
    target_equity_amount = sum(
        _safe_int(getattr(rec_pos, "target_amount_rappen", 0))
        for rec_pos, _product, _amount in equity_rows
    )

    for rec_pos, product, amount in equity_rows:
        row_id = str(getattr(rec_pos, "id", "") or "")
        sector_inputs[row_id] = sector_exposure_for_product(
            getattr(product, "sector_exposure_json", None),
            getattr(product, "sub_asset_class", None),
        )
        ist_weights[row_id] = int(round(amount / equity_amount * 10000))
        target_amount = _safe_int(getattr(rec_pos, "target_amount_rappen", 0))
        if target_equity_amount > 0 and target_amount > 0:
            soll_weights[row_id] = int(round(target_amount / target_equity_amount * 10000))

    return {
        "ist": aggregate_exposures(ist_weights, sector_inputs) if ist_weights else {},
        "soll": aggregate_exposures(soll_weights, sector_inputs) if soll_weights else {},
        "anteil_aktien_bps": int(round(equity_amount / total_amount * 10000)),
    }


def _build_cover(
    mandate: Mandate,
    client: Client,
    advisor: User | None,
    generated_at: str,
) -> dict[str, Any]:
    """Sektion 1 — Cover. Minimalistisch, keine Marketing-Elemente."""
    client_name = " ".join(
        part for part in (
            str(getattr(client, "first_name", "") or "").strip(),
            str(getattr(client, "last_name", "") or "").strip(),
        ) if part
    ) or "—"
    return {
        "title": "Strategische Portfolioanalyse",
        "subtitle": "Persoenlicher Advisory-Report",
        "client_name": client_name,
        "mandate_number": str(getattr(mandate, "mandate_number", "") or ""),
        "report_date": generated_at[:10],  # YYYY-MM-DD
        "advisor_name": (
            str(getattr(advisor, "full_name", "") or "").strip() or "—"
        ),
    }


def _build_inhaltsverzeichnis() -> dict[str, Any]:
    """Inhaltsverzeichnis entlang der aktuellen PDF-Render-Reihenfolge.
    U-13 (2026-06-02) + Aggregator-Sprint #163 + Bug-#7 Contract-Signoff.
    Wird via TocCollector mit echten Seitenzahlen versorgt."""
    return {
        "kapitel": [
            {"nr": 1, "title": "Rechtliche Hinweise"},
            {"nr": 2, "title": "Inhaltsverzeichnis"},
            {"nr": 3, "title": "Ausgangslage"},
            {"nr": 4, "title": "Übersicht Ihrer Positionen"},
            {"nr": 5, "title": "Was wir im Depotcheck prüfen"},
            {"nr": 6, "title": "Erkenntnisse aus dem Depotcheck"},
            {"nr": 7, "title": "Asset Allocation"},
            {"nr": 8, "title": "Risikowährungen"},
            {"nr": 9, "title": "Diversifikation Branchen"},
            {"nr": 10, "title": "Zielbasierte Optimierung"},
            {"nr": 11, "title": "Risikoprofilierung"},
            {"nr": 12, "title": "Building Blocks / iSAA"},
            {"nr": 13, "title": "Statement aus dem Portfoliomanagement"},
            {"nr": 14, "title": "Weiteres Vorgehen"},
            {"nr": 15, "title": "Beratungsprotokoll"},
            {"nr": 16, "title": "Historische Stress-Szenarien"},
            {"nr": 17, "title": "A/B-Backtest"},
            {"nr": 18, "title": "Ex-ante Kostenausweis"},
            {"nr": 19, "title": "Compliance-Audit"},
            {"nr": 20, "title": "Unterschrift"},
        ],
    }


def _build_ausgangslage(
    db: Session,
    mandate: Mandate,
    client: Client,
) -> dict[str, Any]:
    """Sektion 4 — Ausgangslage. Kundeninformation links, Vermögen rechts,
    Key Metrics unten. Daten kommen aus dem Mandat selbst plus aus den
    bestehenden Aggregations-Helpern (portfolio_engine, depot_check).

    Sprint U-P30: 4 Felder werden jetzt aus existierenden Quell-Daten
    abgeleitet, statt aus nicht-persistierten Mandate-Attributen zu lesen
    (siehe _derive_age / _derive_investment_horizon / _derive_primary_goal_label
    / _derive_liquidity_need).
    """
    # Linke Spalte: Kundeninformation
    client_info = {
        "alter": _derive_age(client),
        "anlagehorizont_jahre": _derive_investment_horizon(mandate, client, db),
        "risikoprofil": str(getattr(mandate, "risk_profile_label", "") or "")
            or _resolve_risk_profile_from_assessment(db, mandate),
        "anlageziel": _derive_primary_goal_label(db, mandate),
        "liquiditaetsbedarf_rappen": _derive_liquidity_need(db, mandate),
        "steuerdomizil": str(getattr(client, "country_of_residence", "") or "CH"),
        "referenzwaehrung": str(getattr(mandate, "base_currency", "") or "CHF"),
    }
    # Rechte Spalte: Zusammenfassung des Vermögens. Lazy-Imports vermeiden
    # zirkuläre Abhängigkeiten zum portfolio_engine (das wiederum advisory_report
    # nie konsumiert).
    wealth_summary = _build_wealth_summary(db, mandate, client)
    # Unten: Key Metrics — aus dem aktuellen TargetAllocation-Stand.
    key_metrics = _build_key_metrics(db, mandate)
    return {
        "client_info": client_info,
        "wealth_summary": wealth_summary,
        "key_metrics": key_metrics,
    }


def _build_wealth_summary(
    db: Session,
    mandate: Mandate,
    client: Client,
) -> dict[str, Any]:
    """Aggregiert WealthPositions des Kunden in die Berichts-Kategorien.

    Kategorien gemäss Spec §3:
    - gesamtvermoegen_rappen (alle Positionen, alle Zuordnungen)
    - beratungsvermoegen_rappen (assignment="Beratungsvermögen")
    - immobilien_rappen (position_type contains "Immobilie")
    - vorsorge_rappen (position_type contains "Vorsorge"/"Pensionskasse"/"3a")
    - kredite_rappen (negative Verbindlichkeiten)
    Plus Listen für cashflows und ziele (Goals).

    U-18: cashflows + goals kommen aus dem call-scoped Cache. WealthPosition
    bleibt direkter Query (wird nur in dieser einen Sektion gebraucht).
    """
    from models.wealth import WealthPosition
    wp_rows = (
        db.query(WealthPosition)
        .filter(
            WealthPosition.client_id == client.id,
            WealthPosition.is_active == 1,
            WealthPosition.deleted_at.is_(None),
        )
        .all()
    )
    gesamtvermoegen = 0
    beratungsvermoegen = 0
    immobilien = 0
    vorsorge = 0
    kredite = 0
    for wp in wp_rows:
        amount = _safe_int(getattr(wp, "current_value_rappen", 0))
        gesamtvermoegen += amount
        assignment = str(getattr(wp, "assignment", "") or "").strip()
        position_type = str(getattr(wp, "position_type", "") or "").strip().lower()
        if assignment == "Beratungsvermögen":
            beratungsvermoegen += amount
        if "immobilie" in position_type:
            immobilien += amount
        if any(key in position_type for key in ("vorsorge", "pensionskasse", "3a", "saeule")):
            vorsorge += amount
        if any(key in position_type for key in ("kredit", "hypothek", "darlehen")) and amount < 0:
            kredite += abs(amount)

    cashflow_rows = _cached_active_cashflows(db, str(client.id))
    cashflows = [
        {
            "label": str(getattr(cf, "label", "") or ""),
            "type": str(getattr(cf, "cashflow_type", "") or ""),
            "amount_rappen": _safe_int(getattr(cf, "amount_rappen", 0)),
            "frequency": str(getattr(cf, "frequency", "") or ""),
        }
        for cf in cashflow_rows
    ]

    goal_rows = _cached_active_goals(db, mandate)
    ziele = [
        {
            "label": str(getattr(g, "label", "") or ""),
            "goal_type": str(getattr(g, "goal_type", "") or ""),
            "target_amount_rappen": _safe_int(getattr(g, "target_amount_rappen", 0)),
            "target_date": str(getattr(g, "target_date", "") or ""),
            "hardness": str(getattr(g, "hardness", "") or ""),
        }
        for g in goal_rows
    ]

    return {
        "gesamtvermoegen_rappen": gesamtvermoegen,
        "beratungsvermoegen_rappen": beratungsvermoegen,
        "immobilien_rappen": immobilien,
        "vorsorge_rappen": vorsorge,
        "kredite_rappen": kredite,
        "cashflows": cashflows,
        "ziele": ziele,
    }


def _compute_goal_achievement_score_bps(db: Session, mandate: Mandate) -> int | None:
    """AR-2: einzige Quelle für den Zielerreichungs-Score (gewichteter Mittelwert der
    Goal-Wahrscheinlichkeiten aus goal_achievability_json, weight_bps-gewichtet bzw.
    gleichgewichtet). Genutzt von _build_key_metrics (Karte) UND der Goal-Based-Sektion,
    damit beide denselben Wert zeigen. None = keine TA/keine bewertbaren Goals → Karte '—'.
    """
    import json

    ta = _cached_current_ta(db, mandate)
    if ta is None or not getattr(ta, "goal_achievability_json", None):
        return None
    try:
        parsed = json.loads(ta.goal_achievability_json) or []
    except (TypeError, ValueError):
        return None
    rows = [r for r in parsed if isinstance(r, dict)] if isinstance(parsed, list) else []
    if not rows:
        return None
    goal_by_id = {str(g.id): g for g in _cached_active_goals(db, mandate)}
    weighted_sum = 0.0
    weight_total = 0.0
    for r in rows:
        meta = goal_by_id.get(str(r.get("goal_id", "") or ""))
        probability = float(r.get("probability", 0) or 0)  # 0..1
        weight = float(getattr(meta, "weight_bps", 0) or 0) if meta else 0.0
        if weight <= 0:
            weight = 1.0  # gleichgewichtet, falls Goal keine weight_bps hat
        weighted_sum += probability * weight
        weight_total += weight
    if weight_total <= 0:
        return None
    return int(round(weighted_sum / weight_total * 10000))


def _build_key_metrics(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Aggregiert die 6 Key-Metric-Karten aus dem aktuellen TA-Snapshot.

    Risky-Fraction, erwartete Vol/Return, MaxDD und VaR kommen aus den
    persistierten Audit-Feldern der TargetAllocation. Wenn keine TA
    existiert, sind alle Werte None — die UI rendert dann ein „—".

    U-18: TA aus call-scoped Cache.
    """
    ta = _cached_current_ta(db, mandate)
    if ta is None:
        return {
            "risky_fraction_bps": None,
            "zielerreichung_bps": None,
            "exp_vol_bps": None,
            "exp_return_bps": None,
            "max_drawdown_bps": None,
            "var_95_bps": None,
        }
    return {
        "risky_fraction_bps": _safe_int(getattr(ta, "risky_fraction_bps", 0)) or None,
        # AR-2: Zielerreichung aus dem geteilten Helper — identisch zum Wert der
        # Goal-Based-Sektion (vorher hartkodiert None → Karte zeigte immer '—',
        # obwohl die Sektion einen echten Score auswies = Inkonsistenz im Bericht).
        "zielerreichung_bps": _compute_goal_achievement_score_bps(db, mandate),
        # AR-2: Erwartete Vola/Return, Max-Drawdown und VaR95 aus den beim
        # Strategie-Lauf persistierten Monte-Carlo-KPIs (Beratungsvermoegens-
        # Ebene, target_*). Alt-TAs ohne diese Spalten -> None (Karte zeigt "—",
        # kein Bruch). Werte sind bereits in bps; _safe_int-Wrapper hier robust
        # gegen fehlende Attribute (getattr default None) und 0-Werte -> None.
        "exp_vol_bps": _safe_int(getattr(ta, "mc_exp_vol_bps", None)) or None,
        "exp_return_bps": _safe_int(getattr(ta, "mc_exp_return_bps", None)) or None,
        "max_drawdown_bps": _safe_int(getattr(ta, "mc_max_drawdown_bps", None)) or None,
        "var_95_bps": _safe_int(getattr(ta, "mc_var_95_bps", None)) or None,
    }


def _derive_age(client: Client) -> int:
    """Sprint U-P30: Alter aus `client.date_of_birth` (ISO YYYY-MM-DD).

    Robust gegen leeres / kaputtes Format → 0 (Frontend zeigt "—" wenn 0).
    """
    dob = str(getattr(client, "date_of_birth", "") or "")
    if not dob or len(dob) < 10:
        return 0
    try:
        from datetime import date

        birth = date.fromisoformat(dob[:10])
    except ValueError:
        return 0
    today = date.today()
    age = today.year - birth.year - (
        (today.month, today.day) < (birth.month, birth.day)
    )
    return max(0, age)


def _derive_investment_horizon(
    mandate: Mandate, client: Client, db: Session
) -> int:
    """Sprint U-P30 (2026-05-28 Live-Smoke-Fix):
    Horizont aus dem Pensionierungs-Zeitpunkt minus aktuelles Jahr.

    Fallback-Cascade:
    1. `mandate.retirement_year` (direkt gesetzt) — beste Quelle
    2. `PlanningAssumption.retirement_age_primary` + `client.date_of_birth`
       → Pensions-Jahr abgeleitet (Foundation-Case nutzt diesen Pfad)
    3. `mandate.life_expectancy_year` — wenn Pension nicht definiert
    4. 10 — konservativer Mittelfrist-Default

    Bezug: Live-Smoke 2026-05-28 mit MX-FOUNDATION-01 zeigte Horizont = 10
    statt 14 (Daniel 49 + Pension 63), weil U-P30 nur `Mandate.retirement_year`
    abfragte, aber Foundation seedet `PlanningAssumption.retirement_age_primary`.
    """
    from datetime import date

    today_year = date.today().year

    # 1. Direkt am Mandate gesetzt
    retirement = _safe_int(getattr(mandate, "retirement_year", None))
    if retirement and retirement > today_year:
        return retirement - today_year

    # 2. Via PlanningAssumption + Geburtsdatum ableiten
    derived = _retirement_year_from_planning(db, mandate, client)
    if derived and derived > today_year:
        return derived - today_year

    # 3. Lebenserwartung am Mandate als letzte konkrete Quelle
    life_exp = _safe_int(getattr(mandate, "life_expectancy_year", None))
    if life_exp and life_exp > today_year:
        return life_exp - today_year

    # 4. Konservativer Default
    return 10


def _retirement_year_from_planning(
    db: Session, mandate: Mandate, client: Client
) -> int | None:
    """Errechnet das Pensions-Jahr aus `PlanningAssumption.retirement_age_primary`
    + Geburtsjahr des Kunden. Returns None wenn eines der Felder fehlt.
    """
    from models.wealth import PlanningAssumption

    pa = (
        db.query(PlanningAssumption)
        .filter(
            PlanningAssumption.mandate_id == mandate.id,
            PlanningAssumption.is_current == 1,
        )
        .order_by(PlanningAssumption.valid_from.desc())
        .first()
    )
    if pa is None:
        return None
    age_primary = _safe_int(getattr(pa, "retirement_age_primary", 0))
    if age_primary <= 0:
        return None

    dob = str(getattr(client, "date_of_birth", "") or "")
    if not dob or len(dob) < 4:
        return None
    try:
        birth_year = int(dob[:4])
    except ValueError:
        return None
    return birth_year + age_primary


def _derive_primary_goal_label(db: Session, mandate: Mandate) -> str:
    """Sprint U-P30: Label des Goals mit niedrigstem `rank` (= wichtigstes Ziel).

    Fallback "—" wenn keine aktiven Goals. Nutzt `goal_type` als Sub-Default,
    falls `label` leer ist (Backwards-Compat zu alten Datensätzen).

    U-18: nutzt _cached_active_goals — kein eigener DB-Roundtrip.
    """
    goals = _cached_active_goals(db, mandate)
    if not goals:
        return "—"
    # In-memory min nach rank ist O(N) und vermeidet die separate ORDER BY-Query
    goal = min(goals, key=lambda g: _safe_int(getattr(g, "rank", 0) or 0))
    label = str(getattr(goal, "label", "") or "").strip()
    if label:
        return label
    fallback = str(getattr(goal, "goal_type", "") or "").strip()
    return fallback or "—"


def _derive_liquidity_need(db: Session, mandate: Mandate) -> int:
    """Sprint U-P30: Liquiditätsbedarf ≈ 6 Monate Ausgaben aus Cashflows.

    Konservative Schweizer-Beratungs-Faustregel (Notgroschen 3-6 Monate;
    wir nehmen 6 als oberen Wert für Wealth-Architecture-Mandate).

    Summiert alle aktiven Expense-Cashflows des Kunden, normalisiert auf
    Jahreswerte (jährlich/monatlich/quartalsweise erkannt) und nimmt die
    Hälfte als 6-Monats-Notgroschen.

    U-18: nutzt _cached_active_cashflows (kein eigener DB-Roundtrip);
    Expense-Filter wird in-memory angewandt.
    """
    client_id = getattr(mandate, "client_id", None)
    if not client_id:
        return 0
    all_cashflows = _cached_active_cashflows(db, str(client_id))
    rows = [cf for cf in all_cashflows if str(getattr(cf, "cashflow_type", "")) == "Expense"]
    annual_expenses_rappen = 0
    for cf in rows:
        amount = _safe_int(getattr(cf, "amount_rappen", 0))
        if amount <= 0:
            continue
        freq = str(getattr(cf, "frequency", "") or "").lower()
        if "jährlich" in freq or "jahr" in freq:
            annual_expenses_rappen += amount
        elif "monatlich" in freq or "monat" in freq:
            annual_expenses_rappen += amount * 12
        elif "quartal" in freq:
            annual_expenses_rappen += amount * 4
        else:
            # Unbekannte Frequenz: konservativ als Jahresbetrag annehmen
            annual_expenses_rappen += amount
    return int(annual_expenses_rappen * 0.5)


def _resolve_risk_profile_from_assessment(db: Session, mandate: Mandate) -> str:
    """Lookup risk profile label from the mandate's latest RiskAssessment.

    U-18: nutzt _cached_current_ra (kein eigener DB-Roundtrip).
    """
    ra = _cached_current_ra(db, mandate)
    if ra is None:
        return "—"
    label = str(
        getattr(ra, "risk_willingness_profile", None)
        or getattr(ra, "final_profile_label", None)
        or "—"
    )
    return label


def _build_positionen(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Sektion 5 — Übersicht der EMPFOHLENEN Positionen (SOLL, nicht IST).

    Quelle: aktueller RecommendationRun + RecommendationPositions + Products.
    Falls kein Run vorhanden: leere Liste + klarer Hinweis. Berater pflegt
    den IST extern (per User-Entscheid, 2026-05-24).

    Gruppierung gemäss Spec §4 in 5 Anlageklassen, sortiert nach Marktwert
    absteigend innerhalb der Gruppe.
    """
    # U-18: latest_run + rec_positions + products kommen alle aus dem
    # call-scoped Cache (kein Sektion-spezifischer DB-Roundtrip mehr).
    # Initial-Struktur mit allen 5 Gruppen (auch wenn leer — UI rendert
    # konsistent, keine Sprünge).
    bucket_order = [
        ("liquidity", "Liquidität"),
        ("bonds", "Obligationen"),
        ("equities", "Aktien"),
        ("real_estate", "Immobilien"),
        ("alternatives", "Alternative Anlagen"),
    ]
    groups: list[dict[str, Any]] = [
        {"key": key, "label": label, "positions": [], "total_rappen": 0}
        for key, label in bucket_order
    ]

    latest_run = _cached_latest_recommendation_run(db, mandate)
    if latest_run is None:
        return {
            "groups": groups,
            "total_rappen": 0,
            "has_recommendation_run": False,
            "hinweis": (
                "Noch keine Empfehlung generiert. Bitte Asset Allokation "
                "berechnen und Produktauswahl im Portfolio-Tab vornehmen."
            ),
        }

    rec_positions = _cached_latest_rec_positions(db, mandate)
    products_map = _cached_rec_products_by_id(db, mandate)
    groups_by_key = {g["key"]: g for g in groups}
    total_rappen = 0
    for rp in rec_positions:
        prod = products_map.get(rp.product_id)
        if prod is None:
            continue
        amount = _safe_int(getattr(rp, "target_amount_rappen", 0))
        if amount <= 0:
            continue
        bucket_key = _bucket_key_from_asset_class(
            str(getattr(prod, "asset_class", "") or "")
        )
        # AR-3: nicht zugeordnete Anlageklasse -> sichtbare 'Sonstige'-Gruppe
        # (lazy, nur wenn tatsächlich eine solche Position existiert, damit die
        # Standard-5-Gruppen-Struktur unverändert bleibt). So wird die fehlende
        # Klassifizierung als Datenqualitäts-Hinweis sichtbar statt in Alternatives
        # verschleiert.
        if bucket_key not in groups_by_key:
            sonstige = {
                "key": "unknown",
                "label": "Sonstige / nicht zugeordnet",
                "positions": [],
                "total_rappen": 0,
            }
            groups.append(sonstige)
            groups_by_key["unknown"] = sonstige
            bucket_key = "unknown"
        groups_by_key[bucket_key]["positions"].append({
            "isin": str(getattr(prod, "isin", "") or ""),
            "product_name": str(getattr(prod, "product_name", "") or "—"),
            "product_type": str(getattr(prod, "product_type", "") or ""),
            "sub_asset_class": str(getattr(prod, "sub_asset_class", "") or ""),
            "currency": str(getattr(prod, "currency", "") or ""),
            "market_value_rappen": amount,
            "ter_bps": _safe_int(getattr(prod, "ter_bps", 0)) or None,
            "provider": str(getattr(prod, "provider", "") or ""),
        })
        groups_by_key[bucket_key]["total_rappen"] += amount
        total_rappen += amount

    # Anteils-Prozent + Sortierung innerhalb Gruppe
    for group in groups:
        for pos in group["positions"]:
            pos["share_bps"] = (
                int(round(pos["market_value_rappen"] / total_rappen * 10000))
                if total_rappen > 0 else 0
            )
        group["positions"].sort(
            key=lambda p: -p["market_value_rappen"]
        )
        group["share_bps"] = (
            int(round(group["total_rappen"] / total_rappen * 10000))
            if total_rappen > 0 else 0
        )

    return {
        "groups": groups,
        "total_rappen": total_rappen,
        "has_recommendation_run": True,
        "hinweis": (
            "Empfohlenes Portfolio gemäss aktueller Anlagestrategie. "
            "IST-Bestände werden ausserhalb des Systems geführt."
        ),
    }


def _build_pruefpunkte() -> dict[str, Any]:
    """Sektion 6 — Was wir im Depotcheck prüfen. 10 statische Beschreibungs-
    Blöcke. Berater-Override-Mechanismus folgt in eigenem Sprint (kein
    blockierendes Element für U-P21).
    """
    return {
        "bloecke": [
            {
                "key": "diversifikation",
                "title": "Diversifikation",
                "beschreibung": (
                    "Streuung über Anlageklassen, Regionen und Branchen, "
                    "damit kein einzelnes Ereignis das gesamte Portfolio "
                    "überproportional belastet."
                ),
            },
            {
                "key": "waehrungsrisiken",
                "title": "Währungsrisiken",
                "beschreibung": (
                    "Anteil Fremdwährungen in Bezug auf die "
                    "Referenzwährung des Mandats. Bewertung mit Blick "
                    "auf Sicherungsmöglichkeiten und langfristige "
                    "Tragbarkeit."
                ),
            },
            {
                "key": "konzentrationsrisiken",
                "title": "Konzentrationsrisiken",
                "beschreibung": (
                    "Identifikation von Einzeltitel-, Themen- und "
                    "Emittentenklumpen, die die Portfolio-Robustheit "
                    "beeinträchtigen können."
                ),
            },
            {
                "key": "branchenrisiken",
                "title": "Branchenrisiken",
                "beschreibung": (
                    "Verteilung der Aktien-Allokation über GICS-Sektoren. "
                    "Übergewichtungen in einzelnen Sektoren werden "
                    "im Kontext der Anlagestrategie eingeordnet."
                ),
            },
            {
                "key": "home_bias",
                "title": "Home Bias",
                "beschreibung": (
                    "Übergewichtung des Heimmarkts gegenüber der "
                    "globalen Marktkapitalisierung. Hinweis auf "
                    "mögliche Renditeeinbusse durch fehlende "
                    "internationale Streuung."
                ),
            },
            {
                "key": "liquiditaetsquote",
                "title": "Liquiditätsquote",
                "beschreibung": (
                    "Anteil täglich, wöchentlich, monatlich verfügbarer "
                    "und illiquider Mittel im Verhältnis zum "
                    "Liquiditätsbedarf des Kunden."
                ),
            },
            {
                "key": "strategische_aa",
                "title": "Strategische Asset Allocation",
                "beschreibung": (
                    "Abgleich der Ist-Allokation mit der zielbasiert "
                    "optimierten Soll-Allokation, inklusive Toleranz"
                    "bändern und Risikobudget."
                ),
            },
            {
                "key": "gebuehrenstruktur",
                "title": "Gebührenstruktur",
                "beschreibung": (
                    "Gewichtete Gesamtkostenquote (TER) sowie Vergleich "
                    "mit institutionellen Benchmarks für vergleichbare "
                    "Anlageklassen."
                ),
            },
            {
                "key": "zielkompatibilitaet",
                "title": "Zielkompatibilität",
                "beschreibung": (
                    "Bewertung, ob die Anlagestrategie die "
                    "definierten Vermögens- und Lebensziele unter "
                    "stochastischen Markt-Szenarien erreichen kann."
                ),
            },
            {
                "key": "risiko_passung",
                "title": "Risikofähigkeit vs. Risikobereitschaft",
                "beschreibung": (
                    "Vergleich der finanziellen Tragfähigkeit von "
                    "Schwankungen (Risikofähigkeit) mit der "
                    "psychologischen Akzeptanz (Risikobereitschaft). "
                    "Massgebend ist das schwächere von beidem."
                ),
            },
        ],
    }


def _build_erkenntnisse(
    db: Session,
    mandate: Mandate,
    *,
    dc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sektion 7 — Erkenntnisse mit Ampel-Bewertung pro Prüfpunkt.

    Liefert pro Prüfpunkt:
        {pruefpunkt, bewertung, beurteilung, handlungsempfehlung}
    wobei bewertung ∈ {"gruen","gelb","rot","nicht_beurteilbar"}.

    „nicht_beurteilbar" wird wann immer die nötigen Daten fehlen verwendet —
    die UI rendert dann einen neutralen Status statt einer falschen Ampel.
    Schwellen siehe Sprint-Doc §"Klassifizierungs-Schwellen".

    `dc` kann vom Aufrufer vorberechnet übergeben werden, um doppeltes
    Anstoßen von compute_depot_check zu vermeiden.
    """
    if dc is None:
        from services.depot_check import compute_depot_check
        dc = compute_depot_check(db, mandate) or {}

    checks: list[dict[str, Any]] = [
        _check_risikoprofil(db, mandate),
        _check_asset_allocation(dc, mandate),
        _check_waehrungsstruktur(dc),
        _check_waehrungsabsicherung(db, mandate, dc),
        _check_diversifikation(dc),
        _check_branchen_konzentration(dc),
        _check_liquiditaet(dc),
        _check_alternative_anlagen(dc),
        _check_gebuehren(dc),
        _check_zielkompatibilitaet(db, mandate),
    ]
    return {"checks": checks}


def _verdict(
    pruefpunkt: str,
    bewertung: str,
    beurteilung: str,
    handlungsempfehlung: str,
) -> dict[str, Any]:
    """Strukturiert ein Erkenntnis-Item. bewertung ∈
    {gruen, gelb, rot, nicht_beurteilbar}."""
    assert bewertung in ("gruen", "gelb", "rot", "nicht_beurteilbar")
    return {
        "pruefpunkt": pruefpunkt,
        "bewertung": bewertung,
        "beurteilung": beurteilung,
        "handlungsempfehlung": handlungsempfehlung,
    }


def _check_risikoprofil(db: Session, mandate: Mandate) -> dict[str, Any]:
    """GRÜN: Assessment vorhanden und < 12 Monate alt.
    GELB: Assessment vorhanden, älter.
    ROT: kein Assessment.

    U-18: nutzt _cached_current_ra (kein eigener DB-Roundtrip).
    """
    from datetime import date
    ra = _cached_current_ra(db, mandate)
    if ra is None:
        return _verdict(
            "Risikoprofil", "rot",
            "Es liegt kein Risikoprofil zum Mandat vor.",
            "Risikoprofil erfassen, bevor weitere Schritte erfolgen.",
        )
    created_at = str(getattr(ra, "created_at", "") or "")
    try:
        created_date = date.fromisoformat(created_at[:10])
        age_days = (date.today() - created_date).days
    except (ValueError, TypeError):
        age_days = 0
    if age_days > 365:
        return _verdict(
            "Risikoprofil", "gelb",
            f"Risikoprofil ist {age_days} Tage alt.",
            "Aktualisierung des Risikoprofils empfohlen (Standard-Intervall 12 Monate).",
        )
    return _verdict(
        "Risikoprofil", "gruen",
        "Risikoprofil aktuell und vollständig erfasst.",
        "Keine Massnahme erforderlich.",
    )


def _erkenntnisse_is_illiquid_bucket(bucket_key: str) -> bool:
    """2026-07-24: Immobilien sind fuer NIEMANDEN kurzfristig per Rebalancing
    loesbar -- spiegelt _reviewIsIlliquidAssetClass() im Frontend
    (5eyes_v2.html), das denselben Fund fuer die Live-Review-UI behoben hat."""
    return bucket_key == "real_estate"


def _erkenntnisse_is_discretionary_mandate(mandate: Mandate) -> bool:
    """Spiegelt _reviewIsDiscretionaryMandate() im Frontend: nur Vermoegens-
    verwaltung hat Ausfuehrungsbefugnis fuer eine Rebalancing-Empfehlung."""
    return str(getattr(mandate, "mandate_type", "") or "") == "Vermögensverwaltung"


def _check_asset_allocation(dc: dict[str, Any], mandate: Mandate) -> dict[str, Any]:
    """2026-07-24 (Formel-/Sprach-Audit): Bandverletzungen bei Immobilien
    (illiquide Anlageklasse) UND bei reiner Anlageberatung (mandate_type !=
    'Vermögensverwaltung', keine Ausfuehrungsbefugnis) duerfen nicht als
    'Rebalancing'-Handlungsempfehlung erscheinen -- exakt derselbe Bug, der
    heute Nacht in der Live-Review-UI (reviewBandStateMeta) behoben wurde,
    bestand unabhaengig davon auch im gedruckten Beratungsprotokoll."""
    buckets = dc.get("buckets") or {}
    if not buckets:
        return _verdict(
            "Asset Allocation", "nicht_beurteilbar",
            "Keine Soll-Allokation hinterlegt.",
            "Strategische Asset Allocation berechnen und freigeben.",
        )
    out_of_band = [
        (key, b) for key, b in buckets.items()
        if b.get("in_band") is False
    ]
    if not out_of_band:
        return _verdict(
            "Asset Allocation", "gruen",
            "Alle Anlageklassen liegen innerhalb des Toleranzbandes.",
            "Keine Massnahme erforderlich.",
        )
    liquid_out = [item for item in out_of_band if not _erkenntnisse_is_illiquid_bucket(item[0])]
    labels = ", ".join(str(b.get("label", "")) for _, b in out_of_band)
    discretionary = _erkenntnisse_is_discretionary_mandate(mandate)
    if not liquid_out:
        # Nur illiquide (Immobilien-)Abweichungen: nie 'rot', keine
        # Rebalancing-Sprache -- unabhaengig vom Mandatstyp.
        return _verdict(
            "Asset Allocation", "gelb",
            f"{len(out_of_band)} Anlageklasse(n) ausserhalb des Bandes: {labels}.",
            "Bei nächster Transaktion oder im Kundengespräch berücksichtigen — "
            "keine kurzfristige Rebalancing-Massnahme möglich.",
        )
    if discretionary:
        rebalance_gelb = "Rebalancing prüfen, sofern keine fachliche Begründung vorliegt."
        rebalance_rot = "Rebalancing planen, Eignungsprüfung dokumentieren."
    else:
        rebalance_gelb = "Empfehlung zur Anpassung prüfen und mit dem Kunden besprechen, sofern keine fachliche Begründung vorliegt."
        rebalance_rot = "Empfehlung zur Anpassung mit dem Kunden besprechen, Eignungsprüfung dokumentieren."
    if len(liquid_out) <= 2:
        return _verdict(
            "Asset Allocation", "gelb",
            f"{len(out_of_band)} Anlageklasse(n) ausserhalb des Bandes: {labels}.",
            rebalance_gelb,
        )
    return _verdict(
        "Asset Allocation", "rot",
        f"{len(out_of_band)} Anlageklassen liegen ausserhalb des Bandes: {labels}.",
        rebalance_rot,
    )


def _check_waehrungsstruktur(dc: dict[str, Any]) -> dict[str, Any]:
    fx = dc.get("currency_exposure_bps") or {}
    if not fx:
        return _verdict(
            "Währungsstruktur", "nicht_beurteilbar",
            "Keine Währungs-Daten verfügbar.",
            "Produkte mit Währungs-Exposure pflegen.",
        )
    chf_bps = int(fx.get("CHF", 0) or 0)
    dominant_fx = max(
        ((k, int(v or 0)) for k, v in fx.items() if k != "CHF"),
        default=("—", 0),
    )
    if chf_bps >= 5000:
        return _verdict(
            "Währungsstruktur", "gruen",
            f"CHF-Anteil {chf_bps/100:.1f}%. Fremdwährungsrisiko begrenzt.",
            "Keine Massnahme erforderlich.",
        )
    if chf_bps >= 3000 and dominant_fx[1] < 5000:
        return _verdict(
            "Währungsstruktur", "gelb",
            f"CHF-Anteil {chf_bps/100:.1f}%, dominanter FX {dominant_fx[0]} "
            f"= {dominant_fx[1]/100:.1f}%.",
            "Währungsabsicherung diskutieren, insbesondere bei kurzem Horizont.",
        )
    return _verdict(
        "Währungsstruktur", "rot",
        f"CHF-Anteil nur {chf_bps/100:.1f}%, dominanter FX {dominant_fx[0]} "
        f"= {dominant_fx[1]/100:.1f}%.",
        "Hedging-Strategie für Fremdwährungs-Exposure prüfen.",
    )


def _suggest_hedge_ratio_bps(fx_total_bps: int, horizon_years: int | None) -> tuple[int, str]:
    """Sprint U-98 (2026-06-05): konservative Hedge-Ratio-Empfehlung.

    Heuristik (3eyes-light, konservative Variante — Berater bleibt Richter):
      Horizont < 3 J:  hedge 80% der Fremdwaehrungs-Position
      Horizont 3-7 J:  hedge 50%
      Horizont 7-15 J: hedge 25%
      Horizont > 15 J: hedge 0% (Mean-Reversion-Argument fuer Long-Term)
    Kappung:
      FX-Exposure < 15% -> Hedge optional (geringer Impact)
      Kein Horizont bekannt -> konservative Default-Quote 50%

    Returns:
        (hedge_bps, rationale): hedge_bps in 0..10000, Berater-tauglicher Text.
    """
    # 0 oder negative FX-Exposure: nichts zu hedgen
    if fx_total_bps <= 0:
        return 0, "Keine Fremdwaehrungs-Exposition vorhanden."
    # Sehr kleine FX-Exposure: Hedging selten wirtschaftlich
    if fx_total_bps < 1500:
        return 0, (
            f"Fremdwaehrungs-Anteil {fx_total_bps/100:.1f}% — Hedging wirtschaftlich "
            "wenig sinnvoll bei dieser Groesse."
        )
    if horizon_years is None:
        return 5000, (
            "Kein Anlagehorizont bekannt — konservative Default-Hedge-Quote 50% "
            "der Fremdwaehrungs-Exposition empfohlen."
        )
    if horizon_years < 3:
        ratio_bps = 8000
        rationale = (
            f"Kurzer Horizont ({horizon_years} J): Wechselkurs-Volatilitaet "
            "dominiert vor Mean-Reversion. Hohe Hedge-Quote angezeigt."
        )
    elif horizon_years < 7:
        ratio_bps = 5000
        rationale = (
            f"Mittelfristiger Horizont ({horizon_years} J): Hedge-Quote "
            "ausgewogen — schuetzt vor Drawdowns ohne Long-Term-Mean-Reversion zu vereiteln."
        )
    elif horizon_years < 15:
        ratio_bps = 2500
        rationale = (
            f"Langer Horizont ({horizon_years} J): teilweise Absicherung "
            "reicht, Mean-Reversion mittelt einen Teil des Risikos."
        )
    else:
        ratio_bps = 0
        rationale = (
            f"Sehr langer Horizont ({horizon_years} J): Hedge nicht zwingend, "
            "Mean-Reversion-Argument tragend, Hedge-Kosten ueberwiegen oft."
        )
    return ratio_bps, rationale


def _check_waehrungsabsicherung(
    db: Session,
    mandate: Mandate,
    dc: dict[str, Any],
) -> dict[str, Any]:
    """Sprint U-98 (2026-06-05): konkreter Hedge-Ratio-Vorschlag pro Mandat
    statt nur generisches 'Hedging pruefen'. Beraeter-Entscheidung bleibt
    unberuehrt — der Vorschlag ist Diskussions-Grundlage."""
    from models.profiling import RiskAssessment

    fx = dc.get("currency_exposure_bps") or {}
    if not fx:
        return _verdict(
            "Waehrungsabsicherung", "nicht_beurteilbar",
            "Keine Waehrungs-Daten verfuegbar.",
            "Produkte mit Waehrungs-Exposure pflegen, anschliessend Hedge-Quote berechnen.",
        )

    fx_total_bps = sum(int(v or 0) for k, v in fx.items() if k != "CHF")
    if fx_total_bps <= 0:
        return _verdict(
            "Waehrungsabsicherung", "gruen",
            "Keine Fremdwaehrungs-Exposition vorhanden.",
            "Keine Massnahme erforderlich.",
        )

    horizon_years: int | None = None
    ra = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.mandate_id == mandate.id)
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )
    if ra is not None:
        horizon_raw = getattr(ra, "investment_horizon_years", None)
        if horizon_raw is not None:
            try:
                horizon_years = int(horizon_raw)
            except (ValueError, TypeError):
                horizon_years = None

    hedge_bps, rationale = _suggest_hedge_ratio_bps(fx_total_bps, horizon_years)

    fx_pct = fx_total_bps / 100
    hedge_pct = hedge_bps / 100
    beurteilung = (
        f"Fremdwaehrungs-Exposition {fx_pct:.1f}%. "
        + rationale
    )
    if hedge_bps == 0:
        handlung = (
            "Hedge aktuell nicht empfohlen. Mit Kunde besprechen — Entscheidung dokumentieren."
        )
        bewertung = "gruen" if fx_total_bps < 1500 else "gelb"
    else:
        handlung = (
            f"Empfohlene Hedge-Quote: {hedge_pct:.0f}% der Fremdwaehrungs-Position "
            f"(~{(fx_total_bps * hedge_bps // 10000)/100:.1f}% des Beratungsvermoegens). "
            "Mit Kunde besprechen — Hedge-Kosten gegen Volatilitaets-Reduktion abwaegen."
        )
        # Gelb wenn Hedge mittel/klein, rot wenn hohe Quote bei kurzem Horizont noetig
        bewertung = "rot" if hedge_bps >= 6000 else "gelb"

    return _verdict(
        "Waehrungsabsicherung", bewertung, beurteilung, handlung,
    )


def _check_diversifikation(dc: dict[str, Any]) -> dict[str, Any]:
    hhi = int(dc.get("concentration_hhi", {}).get("country", 0) or 0)
    if hhi == 0:
        return _verdict(
            "Diversifikation", "nicht_beurteilbar",
            "Länder-Verteilung kann nicht ermittelt werden.",
            "Produkte mit Country-Exposure pflegen.",
        )
    if hhi < 1500:
        return _verdict(
            "Diversifikation", "gruen",
            f"Länder-HHI {hhi}. Breite Streuung über Regionen.",
            "Keine Massnahme erforderlich.",
        )
    if hhi <= 2500:
        return _verdict(
            "Diversifikation", "gelb",
            f"Länder-HHI {hhi}. Erkennbare Übergewichtung einzelner Märkte.",
            "Globalere Streuung im Aktien-Sleeve prüfen.",
        )
    return _verdict(
        "Diversifikation", "rot",
        f"Länder-HHI {hhi}. Hohe Konzentration auf wenige Märkte.",
        "Globale Diversifikation erweitern.",
    )


def _check_branchen_konzentration(dc: dict[str, Any]) -> dict[str, Any]:
    hhi = int(dc.get("concentration_hhi", {}).get("sector", 0) or 0)
    if hhi == 0:
        return _verdict(
            "Branchenkonzentration", "nicht_beurteilbar",
            "Branchen-Verteilung kann nicht ermittelt werden.",
            "Produkte mit Sektor-Exposure pflegen.",
        )
    if hhi < 1800:
        return _verdict(
            "Branchenkonzentration", "gruen",
            f"Sektor-HHI {hhi}. Breite Sektor-Streuung.",
            "Keine Massnahme erforderlich.",
        )
    if hhi <= 2500:
        return _verdict(
            "Branchenkonzentration", "gelb",
            f"Sektor-HHI {hhi}. Einzelne Sektoren leicht übergewichtet.",
            "Sektor-Balance über Indextracker prüfen.",
        )
    return _verdict(
        "Branchenkonzentration", "rot",
        f"Sektor-HHI {hhi}. Starke Übergewichtung einzelner Sektoren.",
        "Sektor-Reduktion auf institutionelle Zielstruktur einleiten.",
    )


def _check_liquiditaet(dc: dict[str, Any]) -> dict[str, Any]:
    lp = dc.get("liquidity_profile") or {}
    if not lp:
        return _verdict(
            "Liquidität", "nicht_beurteilbar",
            "Keine Liquiditäts-Daten verfügbar.",
            "Produkt-Liquidity-Tier pflegen.",
        )
    daily = int(lp.get("daily_bps", 0) or 0)
    illiquid = int(lp.get("illiquid_bps", 0) or 0)
    if daily >= 8000 and illiquid <= 1000:
        return _verdict(
            "Liquidität", "gruen",
            f"Täglich liquide {daily/100:.1f}%, illiquid {illiquid/100:.1f}%.",
            "Keine Massnahme erforderlich.",
        )
    if illiquid > 3000:
        return _verdict(
            "Liquidität", "rot",
            f"Illiquider Anteil {illiquid/100:.1f}%. Liquiditätsbedarf gefährdet.",
            "Illiquide Anlagen reduzieren oder Liquiditätsreserve aufstocken.",
        )
    if daily >= 5000:
        return _verdict(
            "Liquidität", "gelb",
            f"Täglich liquide {daily/100:.1f}%. Komfortzone leicht angespannt.",
            "Liquiditätsreserve gegen erwartete Cashflows prüfen.",
        )
    return _verdict(
        "Liquidität", "rot",
        f"Täglich liquide nur {daily/100:.1f}%.",
        "Liquiditätsbuffer prüfen, illiquide Anteile abbauen.",
    )


def _check_alternative_anlagen(dc: dict[str, Any]) -> dict[str, Any]:
    buckets = dc.get("buckets") or {}
    alt = buckets.get("alternatives") or {}
    ist_bps = int(alt.get("ist_bps", 0) or 0)
    if not alt:
        return _verdict(
            "Alternative Anlagen", "nicht_beurteilbar",
            "Anteil Alternative Anlagen unbekannt.",
            "Allokation generieren.",
        )
    if ist_bps < 1500:
        return _verdict(
            "Alternative Anlagen", "gruen",
            f"Anteil {ist_bps/100:.1f}%, innerhalb üblicher Bandbreite.",
            "Keine Massnahme erforderlich.",
        )
    if ist_bps <= 2500:
        return _verdict(
            "Alternative Anlagen", "gelb",
            f"Anteil {ist_bps/100:.1f}%, leicht über Mittelmass.",
            "Liquidität und Bewertungslogik der Alternatives prüfen.",
        )
    return _verdict(
        "Alternative Anlagen", "rot",
        f"Anteil {ist_bps/100:.1f}% überschreitet 25%.",
        "Reduktion zugunsten liquider Anlageklassen prüfen.",
    )


def _check_gebuehren(dc: dict[str, Any]) -> dict[str, Any]:
    ter = int(dc.get("fund_characteristics", {}).get("weighted_ter_bps", 0) or 0)
    covered = int(dc.get("fund_characteristics", {}).get("covered_share_bps", 0) or 0)
    if covered < 5000:
        return _verdict(
            "Gebühren", "nicht_beurteilbar",
            f"Nur {covered/100:.1f}% der Positionen mit gepflegtem TER.",
            "Produkt-TER vervollständigen, bevor Aussage möglich ist.",
        )
    if ter < 50:
        return _verdict(
            "Gebühren", "gruen",
            f"Gewichtete TER {ter/100:.2f}%, institutionelles Niveau.",
            "Keine Massnahme erforderlich.",
        )
    if ter <= 100:
        return _verdict(
            "Gebühren", "gelb",
            f"Gewichtete TER {ter/100:.2f}%, über institutionellem Mittel.",
            "Günstigere Produktalternativen prüfen.",
        )
    return _verdict(
        "Gebühren", "rot",
        f"Gewichtete TER {ter/100:.2f}% deutlich über Markt.",
        "Hochkostige Positionen identifizieren und umschichten.",
    )


def _check_zielkompatibilitaet(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Liest goal_achievability_json aus aktueller TA. Wenn keine TA oder
    keine Goal-Daten: nicht_beurteilbar.

    U-18: nutzt _cached_current_ta (kein eigener DB-Roundtrip).
    """
    import json
    ta = _cached_current_ta(db, mandate)
    if ta is None or not getattr(ta, "goal_achievability_json", None):
        return _verdict(
            "Zielkompatibilität", "nicht_beurteilbar",
            "Keine Zielerreichungs-Daten verfügbar.",
            "Anlagestrategie mit stochastischer Engine berechnen.",
        )
    try:
        rows = json.loads(ta.goal_achievability_json) or []
    except (TypeError, ValueError):
        rows = []
    if not isinstance(rows, list) or not rows:
        return _verdict(
            "Zielkompatibilität", "nicht_beurteilbar",
            "Zielerreichungs-Daten leer oder ungültig.",
            "Anlagestrategie neu berechnen.",
        )
    # AR-1: Engine (services/optimizer/objective.py:_PRIMARY_HARDNESS_KEYS) behandelt
    # SOWOHL "hart" ALS AUCH "primär"/"primaer" als penalty-tragende (bindende) Ziele
    # und persistiert sie via _display_hardness als "hart"/"primär". Der Report flaggte
    # bisher nur ("hart","hard") rot — ein nicht erreichbares primäres Ziel blieb damit
    # unauffällig, obwohl es in der Optimierung bindend ist. Kanonisches Set spiegeln.
    _PRIMARY_HARDNESS = ("hart", "hard", "primaer", "primär", "primary")
    n_hart_unreachable = sum(
        1 for r in rows
        if isinstance(r, dict)
        and str(r.get("status", "")).lower() == "nicht_erreichbar"
        and str(r.get("hardness", "")).strip().lower() in _PRIMARY_HARDNESS
    )
    n_knapp = sum(
        1 for r in rows
        if isinstance(r, dict)
        and str(r.get("status", "")).lower() == "knapp"
    )
    if n_hart_unreachable > 0:
        return _verdict(
            "Zielkompatibilität", "rot",
            f"{n_hart_unreachable} bindend (hart/primär) definiertes Ziel nicht erreichbar.",
            "Zieldefinition oder Anlagestrategie anpassen.",
        )
    if n_knapp > 0:
        return _verdict(
            "Zielkompatibilität", "gelb",
            f"{n_knapp} Ziel(e) knapp erreichbar.",
            "Reserven oder Beitragsdisziplin diskutieren.",
        )
    return _verdict(
        "Zielkompatibilität", "gruen",
        "Alle definierten Ziele werden komfortabel erreicht.",
        "Keine Massnahme erforderlich.",
    )


# ---------------------------------------------------------------------------
# Sektionen 8-10: Visualisierungs-Daten (gleicher Bauplan: IST | SOLL | Drift)
# ---------------------------------------------------------------------------

# Stabile Reihenfolge der Bucket-Keys für Sektion 8 — entspricht Spec §7.
_ASSET_ALLOCATION_ORDER: tuple[tuple[str, str], ...] = (
    ("liquidity",   "Liquidität"),
    ("bonds",       "Obligationen"),
    ("equities",    "Aktien"),
    ("real_estate", "Immobilien"),
    ("alternatives", "Alternative Anlagen"),
)

# Stabile Reihenfolge der Berichts-Währungs-Kategorien für Sektion 9.
_CURRENCY_DISPLAY_ORDER: tuple[str, ...] = (
    "CHF", "USD", "EUR", "GBP", "JPY", "EM FX", "Andere",
)
# EM-FX Bucket fasst Schwellenländer-Währungen zusammen
_EM_FX_CODES: frozenset[str] = frozenset({
    "BRL", "MXN", "INR", "CNY", "ZAR", "IDR", "TRY", "RUB",
    "ARS", "PHP", "MYR", "THB", "PLN", "HUF", "CZK", "TWD", "KRW", "CLP",
})

# Stabile Reihenfolge der GICS-Sektoren für Sektion 10 (10 + 1 institutionelle
# Hand-Kategorie für Alternative-Sektoren ausserhalb GICS).
_GICS_SECTOR_ORDER: tuple[str, ...] = (
    "Information Technology",
    "Financials",
    "Industrials",
    "Health Care",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Materials",
    "Real Estate",
    "Communication Services",
)


def _build_asset_allocation(
    dc: dict[str, Any],
    *,
    notes: Any | None = None,
    ist_basiert_auf_soll: bool = False,
) -> dict[str, Any]:
    """Sektion 8 — Asset Allocation. IST | SOLL | Drift pro Anlageklasse.

    Sprint U-P28 PR B: `notes.aa_anmerkungen` überschreibt den Auto-Drift-
    Text falls vom Berater gepflegt.
    """
    buckets = dc.get("buckets") or {}
    ist_bps: dict[str, int] = {}
    soll_bps: dict[str, int] = {}
    drift_bps: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for key, label in _ASSET_ALLOCATION_ORDER:
        b = buckets.get(key) or {}
        i = int(b.get("ist_bps", 0) or 0)
        s = int(b.get("soll_bps", 0) or 0)
        ist_bps[label] = i
        soll_bps[label] = s
        drift_bps[label] = i - s
        items.append({
            "key": key,
            "label": label,
            "ist_bps": i,
            "soll_bps": s,
            "drift_bps": i - s,
            "band_min_bps": int(b.get("band_min_bps", 0) or 0),
            "band_max_bps": int(b.get("band_max_bps", 0) or 0),
            "in_band": b.get("in_band"),
        })
    default_anm = _default_anmerkungen_asset_allocation(items)
    anmerkungen = _override_or_default(
        getattr(notes, "aa_anmerkungen", None) if notes is not None else None,
        default_anm,
    )
    return {
        "items": items,
        "ist_bps": ist_bps,
        "soll_bps": soll_bps,
        "drift_bps": drift_bps,
        "ist_basiert_auf_soll": bool(ist_basiert_auf_soll),
        "anmerkungen": anmerkungen,
    }


def _build_risikowaehrungen(
    dc: dict[str, Any],
    *,
    notes: Any | None = None,
    ist_basiert_auf_soll: bool = False,
) -> dict[str, Any]:
    """Sektion 9 — Risikowährungen. Aggregiert raw FX-Exposures in die
    7 Berichts-Kategorien (CHF, USD, EUR, GBP, JPY, EM FX, Andere).

    Sprint U-P28 PR B: `notes.waehrungen_erklaerung` überschreibt den
    Auto-CHF-Anteil-Text falls vom Berater gepflegt.
    """
    ist = _aggregate_fx_into_display_buckets(
        dc.get("currency_exposure_bps") or {}
    )
    soll = _aggregate_fx_into_display_buckets(
        dc.get("soll_currency_exposure_bps") or {}
    )
    items: list[dict[str, Any]] = []
    for code in _CURRENCY_DISPLAY_ORDER:
        i = int(ist.get(code, 0) or 0)
        s = int(soll.get(code, 0) or 0)
        items.append({
            "label": code,
            "ist_bps": i,
            "soll_bps": s,
            "drift_bps": i - s,
        })
    default_erkl = _default_erklaerung_waehrungen(items)
    erklaerung = _override_or_default(
        getattr(notes, "waehrungen_erklaerung", None) if notes is not None else None,
        default_erkl,
    )
    return {
        "items": items,
        "ist_bps": {it["label"]: it["ist_bps"] for it in items},
        "soll_bps": {it["label"]: it["soll_bps"] for it in items},
        "drift_bps": {it["label"]: it["drift_bps"] for it in items},
        "ist_basiert_auf_soll": bool(ist_basiert_auf_soll),
        "erklaerung": erklaerung,
    }


def _build_branchen(
    dc: dict[str, Any],
    *,
    notes: Any | None = None,
    equity_sector_context: dict[str, Any] | None = None,
    ist_basiert_auf_soll: bool = False,
) -> dict[str, Any]:
    """Sektion 10 — Diversifikation Branchen. GICS-Reihenfolge + Hand-
    Kategorie für nicht-GICS-Sektoren ("Andere/Alternativen").

    Sprint U-P28 PR B: `notes.branchen_analyse` überschreibt die Auto-
    Sektor-Drift-Analyse falls vom Berater gepflegt.
    """
    if equity_sector_context is None:
        ist_raw = dc.get("sector_exposure_bps") or {}
        soll_raw = dc.get("soll_sector_exposure_bps") or {}
        anteil_aktien_bps = 0
    else:
        ist_raw = equity_sector_context.get("ist") or {}
        soll_raw = equity_sector_context.get("soll") or {}
        anteil_aktien_bps = int(equity_sector_context.get("anteil_aktien_bps", 0) or 0)
    items: list[dict[str, Any]] = []
    covered_keys: set[str] = set()
    for sector in _GICS_SECTOR_ORDER:
        i = int(ist_raw.get(sector, 0) or 0)
        s = int(soll_raw.get(sector, 0) or 0)
        covered_keys.add(sector)
        items.append({
            "label": sector,
            "ist_bps": i,
            "soll_bps": s,
            "drift_bps": i - s,
        })
    # Restliche, nicht-GICS-Sektoren in einer Sammel-Kategorie
    other_ist = sum(
        int(v or 0) for k, v in ist_raw.items() if k not in covered_keys
    )
    other_soll = sum(
        int(v or 0) for k, v in soll_raw.items() if k not in covered_keys
    )
    if other_ist > 0 or other_soll > 0:
        items.append({
            "label": "Übrige",
            "ist_bps": other_ist,
            "soll_bps": other_soll,
            "drift_bps": other_ist - other_soll,
        })
    default_analyse = _default_analyse_branchen(items)
    analyse = _override_or_default(
        getattr(notes, "branchen_analyse", None) if notes is not None else None,
        default_analyse,
    )
    return {
        "items": items,
        "ist_bps": {it["label"]: it["ist_bps"] for it in items},
        "soll_bps": {it["label"]: it["soll_bps"] for it in items},
        "drift_bps": {it["label"]: it["drift_bps"] for it in items},
        "anteil_aktien_bps": anteil_aktien_bps,
        "hinweis": _sector_basis_note(anteil_aktien_bps),
        "ist_basiert_auf_soll": bool(ist_basiert_auf_soll),
        "analyse": analyse,
    }


def _aggregate_fx_into_display_buckets(
    raw_fx: Mapping[str, int],
) -> dict[str, int]:
    """Mappt Roh-Currency-Codes auf die 7 Berichts-Kategorien.
    Alles ausser CHF/USD/EUR/GBP/JPY/EM landet in „Andere"."""
    if not raw_fx:
        return {}
    out: dict[str, int] = {code: 0 for code in _CURRENCY_DISPLAY_ORDER}
    for code, value in raw_fx.items():
        amount = int(value or 0)
        if amount <= 0:
            continue
        normalized = str(code or "").strip().upper()
        if normalized in {"CHF", "USD", "EUR", "GBP", "JPY"}:
            out[normalized] += amount
        elif normalized in _EM_FX_CODES:
            out["EM FX"] += amount
        else:
            out["Andere"] += amount
    return out


def _default_anmerkungen_asset_allocation(items: list[dict[str, Any]]) -> str:
    """Generisch-neutrale Default-Anmerkung. Berater überschreibt später."""
    out_of_band = [
        it["label"] for it in items
        if it.get("in_band") is False
    ]
    if not out_of_band:
        return (
            "Die aktuelle Allokation liegt innerhalb der definierten "
            "Toleranzbänder. Es besteht aus Sicht der strategischen "
            "Allokation kein unmittelbarer Handlungsbedarf."
        )
    return (
        "Folgende Anlageklassen liegen ausserhalb des Toleranzbandes: "
        + ", ".join(out_of_band)
        + ". Eine Eignungsprüfung im Rahmen des Rebalancings ist sinnvoll."
    )


def _default_erklaerung_waehrungen(items: list[dict[str, Any]]) -> str:
    """Neutrale Erklärung mit Bezug auf CHF-Heimatanteil."""
    chf = next((it for it in items if it["label"] == "CHF"), None)
    if chf is None or chf["ist_bps"] == 0:
        return (
            "Die Währungsstruktur kann nicht beurteilt werden, solange "
            "keine Produkt-Währungs-Exposures gepflegt sind."
        )
    return (
        f"Der CHF-Anteil beträgt {chf['ist_bps']/100:.1f}%. "
        "Fremdwährungs-Exposure wirkt auf Volatilität und Kaufkraft. "
        "Eine Absicherung kann je nach Anlagehorizont und "
        "Liquiditätsbedarf sinnvoll sein."
    )


def _sector_basis_note(anteil_aktien_bps: int) -> str:
    if anteil_aktien_bps <= 0:
        return (
            "Sektor-Verteilung basiert auf Aktien-Positionen. "
            "Aktuell sind keine Aktien-Positionen mit Sektor-Daten vorhanden."
        )
    return (
        "Sektor-Verteilung basiert auf "
        f"{anteil_aktien_bps / 100:.1f}% Aktien-Allokation."
    )


def _default_analyse_branchen(items: list[dict[str, Any]]) -> str:
    """Hebt grösste Sektor-Übergewichtung hervor (institutionell-knapp)."""
    if not items or all(it["ist_bps"] == 0 for it in items):
        return (
            "Die Sektor-Struktur kann nicht beurteilt werden, solange "
            "keine Produkt-Sektor-Exposures gepflegt sind."
        )
    drift_sorted = sorted(items, key=lambda it: -abs(it["drift_bps"]))
    top = drift_sorted[0]
    if abs(top["drift_bps"]) < 500:
        return (
            "Die Sektor-Verteilung folgt im Wesentlichen der "
            "Zielstruktur. Es bestehen keine wesentlichen Klumpen."
        )
    direction = "Übergewicht" if top["drift_bps"] > 0 else "Untergewicht"
    label = top["label"]
    drift_pp = abs(top["drift_bps"]) / 100
    return (
        f"Grösste Abweichung im Sektor {label}: "
        f"{direction} von {drift_pp:.1f} Prozentpunkten "
        "gegenüber der Zielstruktur. Sektor-Balance prüfen."
    )


# ---------------------------------------------------------------------------
# Sektionen 10-12
# ---------------------------------------------------------------------------

def _build_goal_based_investing(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Sektion 11 — Goal-Based Investing.

    Liest goal_achievability aus aktueller TA. MC-Pfade (p5/p50/p75 über Zeit)
    sind heute nicht persistiert — Resultat-Struktur enthält dafür einen
    `data_pending`-Flag, damit die UI einen Platzhalter rendern kann statt
    eines leeren Charts.

    Goal-Achievement-Score wird aus den Wahrscheinlichkeiten der einzelnen
    Goals abgeleitet (gewichteter Durchschnitt, gewichtet mit `weight_bps`
    falls vorhanden — sonst gleichgewichtet).

    U-18: TA + Goals aus call-scoped Cache.
    """
    import json

    ta = _cached_current_ta(db, mandate)
    rows: list[dict[str, Any]] = []
    if ta is not None and getattr(ta, "goal_achievability_json", None):
        try:
            parsed = json.loads(ta.goal_achievability_json) or []
            if isinstance(parsed, list):
                rows = [r for r in parsed if isinstance(r, dict)]
        except (TypeError, ValueError):
            rows = []

    # Goal-Metadaten ergänzen (Label, Ziel-Datum) aus Goal-Tabelle, falls
    # die persistierte JSON-Zeile keinen Namen mitbringt.
    goal_rows = _cached_active_goals(db, mandate)
    goal_by_id = {str(g.id): g for g in goal_rows}

    goals: list[dict[str, Any]] = []
    if not rows and goal_rows:
        for meta in goal_rows:
            target_amount = _safe_int(
                getattr(meta, "target_amount_rappen", 0)
                or getattr(meta, "target_wealth_rappen", 0)
            )
            goals.append({
                "goal_id": str(getattr(meta, "id", "") or ""),
                "label": str(getattr(meta, "label", "") or "") or "—",
                "goal_type": str(getattr(meta, "goal_type", "") or ""),
                "target_amount_rappen": target_amount,
                "target_date": str(getattr(meta, "target_date", "") or ""),
                "hardness": str(getattr(meta, "hardness", "") or ""),
                "probability_bps": None,
                "status": "data_pending",
            })
        return {
            "goals": goals,
            "goal_achievement_score_bps": 0,
            "monte_carlo_paths": _build_monte_carlo_paths_section(db, mandate),
        }

    for r in rows:
        gid = str(r.get("goal_id", "") or "")
        meta = goal_by_id.get(gid)
        probability = float(r.get("probability", 0) or 0)  # 0..1
        # Goal-Typ-spezifisches Zielmass: Vermögensziele nutzen
        # target_wealth_rappen, Cashflow-/Pension-Ziele target_amount_rappen,
        # Rendite-Ziele target_return_bps (= None hier, da kein Rappen-Wert).
        target_amount = 0
        if meta is not None:
            target_amount = _safe_int(
                getattr(meta, "target_amount_rappen", 0)
                or getattr(meta, "target_wealth_rappen", 0)
            )
        goals.append({
            "goal_id": gid,
            "label": str(
                r.get("label")
                or (getattr(meta, "label", "") if meta else "")
                or "—"
            ),
            "goal_type": str(getattr(meta, "goal_type", "") or ""),
            "target_amount_rappen": target_amount,
            "target_date": str(getattr(meta, "target_date", "") or ""),
            "hardness": str(r.get("hardness", "") or ""),
            "probability_bps": int(round(probability * 10000)),
            "status": str(r.get("status", "") or ""),
        })
    # AR-2: Score aus dem geteilten Helper (single source of truth, identisch zur
    # Key-Metric-Karte). None (keine bewertbaren Goals) -> 0 für die Sektion.
    _score = _compute_goal_achievement_score_bps(db, mandate)
    goal_achievement_score_bps = _score if _score is not None else 0

    return {
        "goals": goals,
        "goal_achievement_score_bps": goal_achievement_score_bps,
        # U-11 (2026-05-31): echte Monte-Carlo-Pfade via stochastische
        # Engine (services.optimizer.scenario_engine). Bei fehlender TA /
        # CMA / Beratungsvermoegen faellt die Funktion auf data_pending=True
        # mit klarer Begruendung zurueck — UI rendert dann Platzhalter.
        "monte_carlo_paths": _build_monte_carlo_paths_section(db, mandate),
    }


def _build_monte_carlo_paths_section(
    db: Session, mandate: Mandate
) -> dict[str, Any]:
    """U-11 helper — kapselt die Monte-Carlo-Berechnung fuer Sektion 11.

    Holt die Input-Daten (initial_wealth, horizon) und delegiert an
    services.monte_carlo_paths.compute_quantile_paths. Bei jedem Fehler
    in der Pipeline (z.B. defekte CMA, kein TA) gibt das innere Modul
    ein stabiles data_pending=True-Schema zurueck — wir reichen das
    1:1 durch.
    """
    from services.monte_carlo_paths import compute_quantile_paths

    client = _load_client_or_raise(db, mandate)
    initial_wealth = _compute_beratungsvermoegen_rappen(db, client)
    horizon = _derive_investment_horizon(mandate, client, db)
    return compute_quantile_paths(
        db,
        mandate,
        initial_wealth_rappen=initial_wealth,
        horizon_years=horizon,
    )


def _compute_beratungsvermoegen_rappen(db: Session, client: Client) -> int:
    """Summiert WealthPositions des Kunden mit assignment="Beratungsvermögen".

    V1 Implementation: direkte Query, kein Cache. WealthPositions werden
    sonst nur in _build_wealth_summary geladen — Drift-Risk gering, da
    beide Stellen denselben Filter haben.
    """
    from models.wealth import WealthPosition

    rows = (
        db.query(WealthPosition)
        .filter(
            WealthPosition.client_id == client.id,
            WealthPosition.is_active == 1,
            WealthPosition.deleted_at.is_(None),
            WealthPosition.assignment == "Beratungsvermögen",
        )
        .all()
    )
    return sum(_safe_int(getattr(wp, "current_value_rappen", 0)) for wp in rows)


def _build_risikoprofilierung(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Sektion 12 — Risikoprofilierung.

    Liest:
    - aktuelle RiskAssessment (Score Risikofähigkeit/-bereitschaft, Override)
    - aktuelle TA für risky_fraction_bps

    Default-Fragen (für UI-Score-Bar-Rendering) sind die 7 Standard-Fragen
    aus der Spec §11 + ihre Mapping zu den persistierten Punkten.

    U-18: RA + TA aus call-scoped Cache.
    """
    ra = _cached_current_ra_is_current(db, mandate)
    ta = _cached_current_ta(db, mandate)

    if ra is None:
        return {
            "risky_fraction_bps": None,
            "risk_capacity_score_x10": None,
            "risk_willingness_score_x10": None,
            "final_score_x10": None,
            "final_profile": "—",
            "is_overridden": False,
            "override_reason": None,
            "questions": _default_risk_questions(),
        }

    return {
        "risky_fraction_bps": (
            _safe_int(getattr(ta, "risky_fraction_bps", 0)) or None
            if ta else None
        ),
        "risk_capacity_score_x10": _safe_int(
            getattr(ra, "risk_capacity_score_x10", 0)
        ),
        "risk_willingness_score_x10": _safe_int(
            getattr(ra, "risk_willingness_score_x10", 0)
        ),
        "final_score_x10": _safe_int(getattr(ra, "final_score_x10", 0)),
        "final_profile": str(getattr(ra, "final_profile", "") or "—"),
        "is_overridden": bool(_safe_int(getattr(ra, "is_overridden", 0))),
        "override_reason": str(getattr(ra, "override_reason", "") or "") or None,
        "questions": _default_risk_questions(ra=ra),
    }


def _build_building_blocks(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Sektion 13 — Building Blocks / iSAA.

    Liefert die 5 Allokations-Buckets der aktuellen TA plus die statische
    Erklärung der institutionellen Portfolio-Konstruktion. Granulare
    Sub-Block-Auflösung (z.B. Aktien-CH vs Aktien-Global) kommt in einem
    späteren Sprint, wenn der Sub-Asset-Class-Mix konfigurierbar wird.

    U-18: TA aus call-scoped Cache.
    """
    ta = _cached_current_ta(db, mandate)
    blocks: list[dict[str, Any]] = []
    for key, label in _ASSET_ALLOCATION_ORDER:
        target_bps = (
            _safe_int(getattr(ta, f"target_{key}_bps", 0))
            if ta else 0
        )
        band_min = (
            _safe_int(getattr(ta, f"band_{key}_min_bps", 0))
            if ta else 0
        )
        band_max = (
            _safe_int(getattr(ta, f"band_{key}_max_bps", 0))
            if ta else 0
        )
        blocks.append({
            "key": key,
            "label": label,
            "target_bps": target_bps,
            "band_min_bps": band_min,
            "band_max_bps": band_max,
        })
    return {
        "blocks": blocks,
        "constraints": _default_isaa_constraints(ta),
        "methodologie": (
            "Die Portfolio-Konstruktion folgt einer institutionellen "
            "Strategic-Asset-Allocation-Logik (iSAA): Allokation auf "
            "Anlageklassen-Ebene, restringiert durch das Risikobudget "
            "des Mandats und multiperiodisch geprüft mittels Monte-Carlo-"
            "Simulation. Die konkreten Building Blocks werden aus dem "
            "definierten Produkt-Universum gewählt."
        ),
    }


def _default_risk_questions(*, ra: Any = None) -> list[dict[str, Any]]:
    """7 Standard-Fragen aus Spec §11, optional mit echten Punkten aus RA."""
    def _pts(field: str) -> int | None:
        return _safe_int(getattr(ra, field, None)) if ra is not None else None
    return [
        {"key": "anlagehorizont", "frage": "Anlagehorizont", "points": _pts("investment_horizon_years")},
        {"key": "liquiditaetsreserve", "frage": "Liquiditätsreserve", "points": _pts("q_obligations_points")},
        {"key": "sparquote", "frage": "Sparquote", "points": _pts("q_savings_points")},
        {"key": "vermoegen", "frage": "Vermögen", "points": _pts("q_wealth_points")},
        {"key": "einkommen", "frage": "Einkommen", "points": _pts("q_income_points")},
        {"key": "anlageziel", "frage": "Anlageziel", "points": _pts("q_investment_goal_points")},
        {"key": "risikopraeferenz", "frage": "Risikopräferenz", "points": _pts("q_risk_preference_points")},
        {"key": "marktverlust", "frage": "Reaktion auf Marktverluste", "points": _pts("q_risk_behavior_points")},
    ]


def _default_isaa_constraints(ta: Any) -> list[dict[str, Any]]:
    """Constraints aus aktueller TA (max risky fraction, Bandbreiten).
    Wenn keine TA: leere Liste."""
    if ta is None:
        return []
    out: list[dict[str, Any]] = []
    risky = _safe_int(getattr(ta, "risk_budget_bps_at_generation", 0))
    if risky:
        out.append({
            "key": "max_risky_fraction",
            "label": "Maximale Risikoquote",
            "value_bps": risky,
            "beschreibung": (
                "Obergrenze für den Anteil risikobehafteter Anlagen "
                "gemäss FINMA-Eignungsprüfung."
            ),
        })
    return out


# ---------------------------------------------------------------------------
# Sektionen 13-14
# ---------------------------------------------------------------------------

def _build_statement_pm() -> dict[str, Any]:
    """Sektion 14 — Statement aus dem Portfoliomanagement.

    7 institutionelle Investmentgrundsätze. Statisch — Berater-Override
    via Admin-UI folgt in eigenem Sprint. Texte FINMA-konform, ohne
    Renditeversprechen, ohne Dritt-Marken.
    """
    return {
        "principles": [
            {
                "key": "langfristigkeit",
                "title": "Langfristigkeit",
                "body": (
                    "Die strategische Allokation ist auf den definierten "
                    "Anlagehorizont des Mandats ausgerichtet. Kurzfristige "
                    "Markt-Bewegungen werden bewusst nicht im Tagesgeschäft "
                    "umgesetzt."
                ),
            },
            {
                "key": "diversifikation",
                "title": "Diversifikation",
                "body": (
                    "Streuung über Anlageklassen, Regionen und Sektoren "
                    "reduziert das idiosynkratische Einzelrisiko und "
                    "stabilisiert die Pfadverläufe."
                ),
            },
            {
                "key": "disziplin",
                "title": "Disziplin",
                "body": (
                    "Die Allokation wird über das definierte Toleranzband "
                    "kontrolliert. Rebalancing erfolgt regelgebunden, nicht "
                    "stimmungsabhängig."
                ),
            },
            {
                "key": "markt_timing",
                "title": "Markt-Timing",
                "body": (
                    "Aktives Timing einzelner Markt-Phasen liefert empirisch "
                    "keinen verlässlichen Mehrwert. Der Fokus liegt auf "
                    "Allokations-Treue und Kostenkontrolle."
                ),
            },
            {
                "key": "waehrungsabsicherung",
                "title": "Währungsabsicherung",
                "body": (
                    "Fremdwährungs-Exposure wird im Verhältnis zur "
                    "Referenzwährung und zum Anlagehorizont des Mandats "
                    "geführt. Hedging ist nicht selbstzweckhaft, sondern "
                    "abwägende Entscheidung."
                ),
            },
            {
                "key": "effiziente_maerkte",
                "title": "Effiziente Märkte",
                "body": (
                    "Globale Aktien- und Anleihen-Märkte sind weitgehend "
                    "informationseffizient. Faktorprämien und Sub-Asset-"
                    "Class-Strukturen werden dort eingesetzt, wo eine "
                    "fundierte Begründung vorliegt."
                ),
            },
            {
                "key": "verhaltensfehler",
                "title": "Verhaltensfehler",
                "body": (
                    "Systematische Verzerrungen (z.B. Home Bias, "
                    "Recency Bias) werden im Prozess explizit benannt "
                    "und durch regelgebundene Allokations-Disziplin "
                    "adressiert."
                ),
            },
        ],
    }


def _build_weiteres_vorgehen(*, notes: Any | None = None) -> dict[str, Any]:
    """Sektion 15 — Weiteres Vorgehen.

    Sprint U-P28 PR B: 6 Override-Felder aus `MandateReportNotes`. Jede
    Lücke fällt auf den Default-Platzhalter zurück, sodass alte Mandate
    ohne gepflegte Notizen unverändert weiterlaufen.
    """
    placeholder = (
        "(Vom Berater zu ergänzen — wird beim Druck des Berichts "
        "konkretisiert.)"
    )
    block_optimierungen = _override_or_default(
        getattr(notes, "vorgehen_block_optimierungen", None) if notes is not None else None,
        placeholder,
    )
    block_zielstrategie = _override_or_default(
        getattr(notes, "vorgehen_block_zielstrategie", None) if notes is not None else None,
        placeholder,
    )
    offene_fragen = (
        _parse_notes_json_list(getattr(notes, "vorgehen_offene_fragen_json", None))
        if notes is not None
        else []
    )
    todos = (
        _parse_notes_json_list(getattr(notes, "vorgehen_todos_json", None))
        if notes is not None
        else []
    )
    dokumente = (
        _parse_notes_json_list(getattr(notes, "vorgehen_dokumente_json", None))
        if notes is not None
        else []
    )
    naechster_termin_raw = (
        getattr(notes, "vorgehen_naechster_termin", None) if notes is not None else None
    )
    naechster_termin = (
        str(naechster_termin_raw).strip()
        if naechster_termin_raw and str(naechster_termin_raw).strip()
        else None
    )
    return {
        "block_optimierungen": block_optimierungen,
        "block_zielstrategie": block_zielstrategie,
        "offene_fragen": offene_fragen,
        "naechster_termin": naechster_termin,
        "todos": todos,
        "dokumente": dokumente,
    }


# ---------------------------------------------------------------------------
# Sektion 16 — Beratungsprotokoll (Sprint U-FINMA-2.2, FIDLEG)
# ---------------------------------------------------------------------------

def _build_beratungsprotokoll(db: Session, mandate: Mandate) -> dict[str, Any]:
    """FINMA-konforme Beratungsprotokoll-Übersicht.

    Liefert:
    - total_active: Anzahl aktiver AdvisoryLog-Köpfe (non-superseded)
    - latest_entry: serialisierter letzter Eintrag oder None
    - last_review_date: Datum des letzten Eintrags (ISO YYYY-MM-DD)
    - suitability_mismatches: aktive Mismatches (Risikobudget, Bands)
    - has_active_mismatches: True wenn mindestens ein Mismatch
    - days_since_last_review: Anzahl Tage seit letzem Eintrag
    - retention_audit_ok: True wenn keine Einträge ablaufen in den nächsten
      30 Tagen (FIDLEG-Aufbewahrungspflicht)
    """
    from datetime import date

    from services.advisory_log_service import (
        count_active_entries,
        detect_suitability_mismatches,
        get_latest_active_entry,
        serialize_response,
    )

    total_active = count_active_entries(db, mandate_id=mandate.id)
    latest = get_latest_active_entry(db, mandate_id=mandate.id)
    mismatches = detect_suitability_mismatches(db, mandate)

    last_review_date: str | None = None
    days_since: int | None = None
    if latest is not None:
        last_review_date = (
            (latest.entry_datetime or "")[:10] or latest.entry_date or None
        )
        if last_review_date:
            try:
                ref = date.fromisoformat(last_review_date)
                days_since = (date.today() - ref).days
            except ValueError:
                days_since = None

    # Retention-Audit: schauen ob ältester ablaufender Eintrag in <30 Tagen
    retention_audit_ok = _check_retention_audit(db, mandate.id)

    return {
        "total_active": total_active,
        "latest_entry": serialize_response(latest) if latest else None,
        "last_review_date": last_review_date,
        "days_since_last_review": days_since,
        "suitability_mismatches": mismatches,
        "has_active_mismatches": bool(mismatches),
        "retention_audit_ok": retention_audit_ok,
    }


# ---------------------------------------------------------------------------
# Sektion 17 — Eignungspruefung (Sprint U-FINMA-3, Roadmap-Punkt 3)
# ---------------------------------------------------------------------------

def _build_suitability_summary(db: Session, mandate: Mandate) -> dict[str, Any]:
    """FINMA-Eignungspruefung im Advisory-Report sichtbar referenziert.

    Liest den juengsten SuitabilityCheck zum Mandat und liefert die
    Felder, die im Web-Sub-App + PDF Sektion 17 dargestellt werden:
    - Wer hat wann was geprueft
    - Ergebnis-Status + Notes
    - Liste fehlender Informationen
    - Warnungs-/Bestaetigungs-Workflow falls Client trotz Mismatch
      fortgefuehrt hat (FINMA Art. 12 FIDLEG)
    - Querverweise auf RiskAssessment, ClientKnowledge, AdvisoryLog,
      RecommendationRun, Document

    Wenn kein Check existiert: stabiles leeres Schema mit has_check=False.
    """
    from models.profiling import SuitabilityCheck

    check = (
        db.query(SuitabilityCheck)
        .filter(SuitabilityCheck.mandate_id == mandate.id)
        .order_by(SuitabilityCheck.checked_at.desc())
        .first()
    )

    if check is None:
        return {
            "has_check": False,
            "check_id": None,
            "performed_at": None,
            "duty_type": None,
            "result": None,
            "result_notes": None,
            "missing_information": [],
            "client_proceeded_despite": False,
            "warning_delivered": False,
            "warning_delivered_at": None,
            "client_acknowledged": False,
            "client_acknowledged_at": None,
            "references": {
                "risk_assessment_id": None,
                "knowledge_assessment_id": None,
                "advisory_log_id": None,
                "recommendation_run_id": None,
                "document_id": None,
            },
            "checked_by_id": None,
            "checked_by_name": "—",
            "linked_log_present": False,
        }

    missing = _parse_notes_json_list(getattr(check, "missing_information_json", None))
    checked_by_name = _resolve_user_full_name(db, getattr(check, "checked_by", None))
    advisory_log_id = getattr(check, "advisory_log_id", None) or None
    linked_log_present = _advisory_log_exists(db, advisory_log_id)

    return {
        "has_check": True,
        "check_id": str(getattr(check, "id", "") or "") or None,
        "performed_at": str(getattr(check, "checked_at", "") or "") or None,
        "duty_type": str(getattr(check, "duty_type", "") or "") or None,
        "result": str(getattr(check, "result", "") or "") or None,
        "result_notes": str(getattr(check, "result_notes", "") or "") or None,
        "missing_information": missing,
        "client_proceeded_despite": bool(
            _safe_int(getattr(check, "client_proceeding_despite", 0))
        ),
        "warning_delivered": bool(
            _safe_int(getattr(check, "warning_delivered", 0))
        ),
        "warning_delivered_at": (
            str(getattr(check, "warning_delivered_at", "") or "") or None
        ),
        "client_acknowledged": bool(
            _safe_int(getattr(check, "client_acknowledged", 0))
        ),
        "client_acknowledged_at": (
            str(getattr(check, "client_acknowledged_at", "") or "") or None
        ),
        "references": {
            "risk_assessment_id": (
                str(getattr(check, "risk_assessment_id", "") or "") or None
            ),
            "knowledge_assessment_id": (
                str(getattr(check, "knowledge_assessment_id", "") or "") or None
            ),
            "advisory_log_id": str(advisory_log_id) if advisory_log_id else None,
            "recommendation_run_id": (
                str(getattr(check, "recommendation_run_id", "") or "") or None
            ),
            "document_id": (
                str(getattr(check, "document_id", "") or "") or None
            ),
        },
        "checked_by_id": str(getattr(check, "checked_by", "") or "") or None,
        "checked_by_name": checked_by_name,
        "linked_log_present": linked_log_present,
    }


def _resolve_user_full_name(db: Session, user_id: Any) -> str:
    """Sicherer Lookup eines Berater-Namens. Fallback "—" wenn nicht da."""
    if not user_id:
        return "—"
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return "—"
    name = str(getattr(user, "full_name", "") or "").strip()
    return name or "—"


def _advisory_log_exists(db: Session, advisory_log_id: Any) -> bool:
    """True wenn referenzierter AdvisoryLog tatsaechlich existiert (nicht
    geloescht). Erlaubt der UI den Tieftext „Verknuepfter Log nicht
    gefunden" zu zeigen, statt eine falsche Sicherheit zu suggerieren.
    """
    if not advisory_log_id:
        return False
    try:
        from models.review import AdvisoryLog
        row = (
            db.query(AdvisoryLog)
            .filter(AdvisoryLog.id == advisory_log_id)
            .first()
        )
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def _check_retention_audit(db: Session, mandate_id: str) -> bool:
    """True wenn kein aktiver Eintrag in den nächsten 30 Tagen abläuft.

    FIDLEG verlangt 10-Jahres-Aufbewahrung — wenn ein Eintrag ablaufen
    soll, muss vorher Archiv-Pflicht erfüllt sein.
    """
    from datetime import date, timedelta

    from models.review import AdvisoryLog

    threshold = (date.today() + timedelta(days=30)).isoformat()
    expiring = (
        db.query(AdvisoryLog)
        .filter(
            AdvisoryLog.mandate_id == mandate_id,
            AdvisoryLog.retain_until.isnot(None),
            AdvisoryLog.retain_until < threshold,
        )
        .first()
    )
    return expiring is None


# ---------------------------------------------------------------------------
# Sektion 17 — Historische Stress-Szenarien (Sprint U-70)
# ---------------------------------------------------------------------------

def _build_stress_replay(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Historische Stress-Replays für den Advisory-Report.

    Konsumiert den bestehenden U-P13-Service unverändert und mappt dessen
    Ergebnis auf ein stabiles, PDF-/Frontend-taugliches Schema. Fehler sind
    report-tauglich fail-soft: der Bericht bleibt erzeugbar, der Abschnitt
    zeigt dann einen Hinweis statt einer Tabelle.
    """
    try:
        from services.backtest_stress import compute_stress_replays

        raw = compute_stress_replays(db, mandate) or {}
    except Exception as exc:  # pragma: no cover - defensive report boundary
        return {
            "data_pending": True,
            "note": f"Stress-Replay aktuell nicht verfügbar: {exc}",
            "weights_bps": {},
            "scenarios": [],
        }

    raw_scenarios = raw.get("scenarios") or []
    if not raw_scenarios:
        return {
            "data_pending": True,
            "note": str(
                raw.get("warning")
                or raw.get("note")
                or "Stress-Replay aktuell nicht verfügbar.",
            ),
            "weights_bps": dict(raw.get("weights_bps") or {}),
            "scenarios": [],
        }

    scenarios: list[dict[str, Any]] = []
    for scenario in raw_scenarios:
        if not isinstance(scenario, Mapping):
            continue
        scenarios.append({
            "id": str(scenario.get("id") or ""),
            "label": str(
                scenario.get("scenario_name")
                or scenario.get("label")
                or scenario.get("id")
                or "Szenario",
            ),
            "period": str(scenario.get("period") or ""),
            "cumulative_return_bps": int(scenario.get("cumulative_return_bps") or 0),
            "max_drawdown_bps": int(scenario.get("max_drawdown_bps") or 0),
            "recovery_months": scenario.get("recovery_months"),
            "annual_breakdown": list(scenario.get("annual_breakdown") or []),
        })

    return {
        "data_pending": len(scenarios) == 0,
        "note": str(raw.get("note") or ""),
        "weights_bps": dict(raw.get("weights_bps") or {}),
        "scenarios": scenarios,
    }


# ---------------------------------------------------------------------------
# Sektion 18 — A/B-HouseMatrix-Backtest (Sprint U-71)
# ---------------------------------------------------------------------------

def _build_ab_backtest(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Read-only Policy-Vergleich für den Advisory-Report.

    Der bestehende A/B-Service verlangt zwei Policy-IDs. Für den Report wählen
    wir konservativ die aktuelle Policy als B und die jüngste andere Policy als
    A. Gibt es keine Vergleichs-Policy, bleibt die Sektion fail-soft pending.
    """
    from models.allocation import OptimizerPolicy
    from services.backtest_ab import run_ab_backtest

    current = (
        db.query(OptimizerPolicy)
        .filter(OptimizerPolicy.is_current == 1)
        .order_by(OptimizerPolicy.valid_from.desc(), OptimizerPolicy.created_at.desc())
        .first()
    )
    if current is None:
        return {
            "data_pending": True,
            "note": "Keine aktuelle OptimizerPolicy gefunden.",
            "policy_a": None,
            "policy_b": None,
            "buckets_diff": [],
            "risk_metrics_diff": {},
            "stress_diff": [],
            "warnings": [],
        }

    comparison = (
        db.query(OptimizerPolicy)
        .filter(OptimizerPolicy.id != current.id)
        .order_by(
            OptimizerPolicy.valid_from.desc(),
            OptimizerPolicy.version.desc(),
            OptimizerPolicy.created_at.desc(),
        )
        .first()
    )
    if comparison is None:
        return {
            "data_pending": True,
            "note": "Keine zweite OptimizerPolicy für einen A/B-Vergleich vorhanden.",
            "policy_a": _ab_policy_reference(comparison),
            "policy_b": _ab_policy_reference(current),
            "buckets_diff": [],
            "risk_metrics_diff": {},
            "stress_diff": [],
            "warnings": [],
        }

    try:
        raw = run_ab_backtest(db, mandate, str(comparison.id), str(current.id)) or {}
    except Exception as exc:  # pragma: no cover - defensive report boundary
        return {
            "data_pending": True,
            "note": f"A/B-Backtest aktuell nicht verfügbar: {exc}",
            "policy_a": _ab_policy_reference(comparison),
            "policy_b": _ab_policy_reference(current),
            "buckets_diff": [],
            "risk_metrics_diff": {},
            "stress_diff": [],
            "warnings": [],
        }

    policy_a = _ab_policy_summary(raw.get("policy_a") or {})
    policy_b = _ab_policy_summary(raw.get("policy_b") or {})
    return {
        "data_pending": False,
        "note": str(raw.get("note") or ""),
        "score_bucket": raw.get("score_bucket"),
        "cma_id": str(raw.get("cma_id") or ""),
        "cma_version": int(raw.get("cma_version") or 0),
        "policy_a": policy_a,
        "policy_b": policy_b,
        "buckets_diff": _ab_bucket_diff_list(raw.get("buckets_diff") or {}),
        "risk_metrics_diff": dict(raw.get("risk_metrics_diff") or {}),
        "stress_diff": _ab_stress_diff_list(raw.get("stress_diff") or []),
        "warnings": list(raw.get("warnings") or []),
    }


def _ab_policy_reference(policy) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "policy_id": str(getattr(policy, "id", "") or ""),
        "policy_name": str(getattr(policy, "policy_name", "") or ""),
        "version": int(getattr(policy, "version", 0) or 0),
        "is_current": bool(getattr(policy, "is_current", 0)),
    }


def _ab_policy_summary(view: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "policy_id": str(view.get("policy_id") or ""),
        "policy_name": str(view.get("policy_name") or ""),
        "version": int(view.get("version") or 0),
        "is_current": bool(view.get("is_current")),
        "profile_name": str(view.get("profile_name") or ""),
        "max_risky_fraction_bps": int(view.get("max_risky_fraction_bps") or 0),
        "weights_bps": dict(view.get("weights_bps") or {}),
        "expected_return_bps": int(view.get("expected_return_bps") or 0),
        "expected_volatility_bps": int(view.get("expected_volatility_bps") or 0),
        "expected_ter_bps": int(view.get("expected_ter_bps") or 0),
        "sharpe_ratio_x100": int(view.get("sharpe_ratio_x100") or 0),
    }


def _ab_bucket_diff_list(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    preferred = ("liquidity", "bonds", "equities", "real_estate", "alternatives")
    rows: list[dict[str, Any]] = []
    for key in preferred:
        item = raw.get(key) or {}
        rows.append({
            "key": key,
            "label": str(item.get("label") or key),
            "a_bps": int(item.get("a_bps") or 0),
            "b_bps": int(item.get("b_bps") or 0),
            "delta_bps": int(item.get("delta_bps") or 0),
        })
    return rows


def _ab_stress_diff_list(raw: list[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        rows.append({
            "id": str(item.get("id") or ""),
            "label": str(item.get("label") or item.get("id") or "Szenario"),
            "period": str(item.get("period") or ""),
            "a_cumulative_return_bps": int(item.get("a_cumulative_return_bps") or 0),
            "b_cumulative_return_bps": int(item.get("b_cumulative_return_bps") or 0),
            "delta_cumulative_return_bps": int(
                item.get("delta_cumulative_return_bps") or 0
            ),
            "a_max_drawdown_bps": int(item.get("a_max_drawdown_bps") or 0),
            "b_max_drawdown_bps": int(item.get("b_max_drawdown_bps") or 0),
            "delta_max_drawdown_bps": int(item.get("delta_max_drawdown_bps") or 0),
            "a_recovery_months": int(item.get("a_recovery_months") or 0),
            "b_recovery_months": int(item.get("b_recovery_months") or 0),
        })
    return rows


def _bucket_key_from_asset_class(asset_class: str) -> str:
    """Mappt Product.asset_class auf die 5 Berichts-Buckets.

    AR-3: Leere/whitespace-only oder nicht gemappte (vertippte/lokalisierte)
    Anlageklassen NICHT mehr still nach 'alternatives' kippen — das verfälschte
    Sektion 5 und blähte die Alternatives-Quote auf. Stattdessen 'unknown'; der
    Caller weist solche Positionen einer sichtbaren 'Sonstige'-Gruppe zu.
    """
    raw = (asset_class or "").strip().lower()
    aliases = {
        "aktien": "equities", "equities": "equities",
        "obligationen": "bonds", "anleihen": "bonds", "bonds": "bonds",
        "immobilien": "real_estate",
        "real estate": "real_estate", "real_estate": "real_estate",
        "alternative": "alternatives", "alternativen": "alternatives",
        "alternatives": "alternatives",
        "liquidität": "liquidity", "liquiditaet": "liquidity",
        "cash": "liquidity", "liquidity": "liquidity",
    }
    return aliases.get(raw, "unknown")


def _build_disclaimer() -> dict[str, Any]:
    """Sektion 2 — Rechtliche Hinweise. Statisch, FINMA-konform formuliert.

    Bestehender Single-Report-Disclaimer wird wiederverwendet, hier nur
    der Aggregator-Struktur-Wrapper.
    """
    return {
        "hinweise": [
            "Dieser Bericht ist keine Anlageempfehlung im Sinne von FIDLEG. "
            "Er beschreibt strategische Überlegungen auf Basis der aktuellen "
            "Markt- und Kundendaten und ersetzt keine individuelle Beratung.",
            "Es wird keine Garantie für die in diesem Bericht enthaltenen "
            "Aussagen, Projektionen oder Modell-Resultate übernommen. "
            "Vergangene Performance ist kein Indikator für künftige Erträge.",
            "Monte-Carlo-Simulationen basieren auf stochastischen "
            "Markt-Annahmen (Capital Market Assumptions). Die Annahmen "
            "spiegeln die Einschätzung zum Stichtag des Berichts wider und "
            "können sich ändern. Modell-Risiken sind nicht vollständig "
            "ausschliessbar.",
            "Sämtliche Anlageklassen sind mit Risiken behaftet, einschliesslich "
            "Marktrisiko, Bonitätsrisiko, Liquiditätsrisiko, Währungsrisiko "
            "und Inflationsrisiko. Eine vollständige Liste wird in den "
            "Produktdokumenten der einzelnen Anlageinstrumente offengelegt.",
            "Dieser Bericht ist vertraulich und ausschliesslich für den "
            "genannten Kunden bestimmt. Weitergabe an Dritte nur mit "
            "ausdrücklicher Zustimmung.",
            "Der Bericht ersetzt keine steuerliche oder rechtliche "
            "Beratung. Für individuelle Steuer- und Rechtsfragen sind "
            "qualifizierte Spezialisten beizuziehen.",
            "Die Umsetzung der im Bericht skizzierten Vorschläge erfolgt "
            "ausschliesslich nach expliziter Freigabe durch den Kunden. "
            "Es findet keine automatische Transaktion statt.",
        ],
    }


# ---------------------------------------------------------------------------
# Sprint U-68 (2026-06-02): FIDLEG Art. 9/26 Interessenkonflikte.
# ---------------------------------------------------------------------------

def _build_conflict_disclosures(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Aggregiert aktive Interessenkonflikt-Offenlegungen pro Mandat.

    FIDLEG Art. 9 verlangt Offenlegung von Vermittlerentschaedigungen
    (Provisionen, Retrozessionen, Boni). Art. 26 verlangt
    organisatorische Massnahmen zur Vermeidung. Diese Sektion
    aggregiert die ConflictOfInterestDisclosure-Eintraege fuer den
    Berater-Report.
    """
    try:
        from models.review import ConflictOfInterestDisclosure
        rows = (
            db.query(ConflictOfInterestDisclosure)
            .filter(
                ConflictOfInterestDisclosure.mandate_id == mandate.id,
                ConflictOfInterestDisclosure.deleted_at.is_(None),
            )
            .order_by(ConflictOfInterestDisclosure.disclosed_at.desc())
            .all()
        )
    except Exception:  # noqa: BLE001 — robust gegen Schema-Mismatch
        return {
            "entries": [],
            "counts": {"total": 0, "by_type": {}},
            "has_unacknowledged": False,
            "fidleg_basis": "Art. 9 / Art. 26 FIDLEG",
        }

    entries = []
    counts_by_type: dict[str, int] = {}
    has_unacknowledged = False
    for row in rows:
        ctype = str(getattr(row, "conflict_type", "") or "unknown")
        counts_by_type[ctype] = counts_by_type.get(ctype, 0) + 1
        ack = bool(_safe_int(getattr(row, "client_acknowledged", 0)))
        disclosed = bool(_safe_int(getattr(row, "disclosed_to_client", 0)))
        if disclosed and not ack:
            has_unacknowledged = True
        entries.append({
            "id": getattr(row, "id", None),
            "conflict_type": ctype,
            "description": getattr(row, "description", "") or "",
            "inducement_provider": getattr(row, "inducement_provider", None),
            "inducement_amount_rappen": getattr(row, "inducement_amount_rappen", None),
            "inducement_frequency": getattr(row, "inducement_frequency", None),
            "disclosed_to_client": disclosed,
            "disclosed_at": getattr(row, "disclosed_at", None),
            "client_acknowledged": ack,
            "client_acknowledged_at": getattr(row, "client_acknowledged_at", None),
            "mitigation_action": getattr(row, "mitigation_action", None),
            "document_id": getattr(row, "document_id", None),
        })

    return {
        "entries": entries,
        "counts": {"total": len(entries), "by_type": counts_by_type},
        "has_unacknowledged": has_unacknowledged,
        "fidleg_basis": "Art. 9 / Art. 26 FIDLEG",
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Sprint U-66 (2026-06-03): FIDLEG-Suitability-Compliance-Audit-Wrapper.
# ---------------------------------------------------------------------------

def _build_cost_disclosure_section(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Wrapper um services/cost_disclosure.build_cost_disclosure (FIDLEG Art. 8/9
    Kostenausweis Ex-ante) fuer den Advisory-Report-Aggregator. Der Service selbst
    liefert bei fehlender Empfehlung bereits ein 'pending'-Payload; hier zusaetzlich
    fail-closed gegen Import-/Schema-Fehler (degraded, NIE stille 0-Kosten)."""
    try:
        from services.cost_disclosure import build_cost_disclosure
        return build_cost_disclosure(db, mandate)
    except Exception:  # noqa: BLE001
        return {
            "available": False,
            "audit_degraded": True,
            "fidleg_basis": "Art. 8 / Art. 9 FIDLEG",
            "note": "Kostenausweis konnte nicht erstellt werden (degraded).",
        }


def _build_suitability_compliance(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Dünner Wrapper über services/suitability_audit.audit_mandate_suitability.

    Liefert pro Mandat einen FIDLEG-Audit-Befund (welche AdvisoryLog-
    Eintraege haben keine Geeignetheitspruefung, welche sind stale,
    welche haben Result-Inkonsistenzen). Read-only, non-breaking.

    Default-Verhalten: bei jedem Schema-/Import-Fehler -> degraded
    leeres Schema, Aggregator crasht NIE.

    Fail-closed (2026-07-18): im Fehlerfall NIE 'is_compliant: True' — ein
    fehlgeschlagenes Audit darf keine Konformitaet behaupten. Stattdessen
    is_compliant=None + audit_degraded=True -> Renderer zeigt 'Pruefung nicht
    moeglich' (amber) statt Gruen.
    """
    try:
        from services.suitability_audit import audit_mandate_suitability
        return audit_mandate_suitability(db, mandate)
    except Exception:  # noqa: BLE001
        return {
            "total_advisory_logs": 0,
            "logs_requiring_suitability": 0,
            "logs_with_suitability": 0,
            "logs_without_suitability": [],
            "freshness_issues": [],
            "result_issues": [],
            "is_compliant": None,
            "audit_degraded": True,
            "fidleg_basis": "Art. 10 / Art. 12 FIDLEG",
        }


# ---------------------------------------------------------------------------
# Sprint U-73+U-74 (2026-06-03): Engine-Modell-Audit-Wrapper.
# ---------------------------------------------------------------------------

def _build_methodology_models(db: Session) -> dict[str, Any]:
    """Wrapper über services/methodology_audit.audit_engine_models.

    Liefert pro Engine-Modell (Nelson-Siegel, KGV-MR, Risikopraemien)
    den Aktivierungs-Status fuer die aktuelle CMA-Version. Read-only,
    non-breaking.

    Robust gegen Schema-/Import-Fehler -> degraded leeres Schema.
    """
    try:
        from services.methodology_audit import audit_engine_models
        return audit_engine_models(db)
    except Exception:  # noqa: BLE001
        return {
            "cma_id": None,
            "cma_version": None,
            "models": [],
            "active_count": 0,
            "methodology_notes": [],
        }


# ---------------------------------------------------------------------------
# Sprint U-69 (2026-06-03): Recommendation-Methodology-Audit-Wrapper.
# ---------------------------------------------------------------------------

def _build_recommendation_methodology(
    db: Session, mandate: Mandate,
) -> dict[str, Any]:
    """Wrapper über services/recommendation_audit.audit_recommendation_methodology.

    Liefert pro Mandat die Methodology-Box (welcher Optimizer-Run lieferte
    die produktive Allokation, mit welchem Status, Seed, n_paths etc.).
    Read-only, non-breaking. Robust gegen Schema-Mismatch -> degraded.
    """
    try:
        from services.recommendation_audit import audit_recommendation_methodology
        return audit_recommendation_methodology(db, mandate)
    except Exception:  # noqa: BLE001
        # Fail-closed (2026-07-18): kein falsches 'compliant' bei Audit-Fehler.
        return {
            "latest_run": None,
            "latest_active_run": None,
            "total_runs": 0,
            "shadow_count": 0,
            "active_count": 0,
            "fallback_count": 0,
            "is_compliant": None,
            "audit_degraded": True,
            "fidleg_basis": "Art. 16 FIDLEG",
        }


# ---------------------------------------------------------------------------
# Sprint U-22 (2026-06-03): Mandate-Lock-Status-Audit Wrapper.
# ---------------------------------------------------------------------------

def _build_mandate_lock_status(
    db: Session, mandate: Mandate,
) -> dict[str, Any]:
    """Wrapper über services/mandate_lock_audit.audit_mandate_editability.

    Liefert pro Mandat: is_editable + lock_reasons[] + reason-Labels.
    Read-only, non-breaking. Robust gegen Schema-Mismatch -> degraded
    is_editable=True.
    """
    try:
        from services.mandate_lock_audit import audit_mandate_editability
        return audit_mandate_editability(db, mandate)
    except Exception:  # noqa: BLE001
        return {
            "is_editable": True,
            "lock_reasons": [],
            "lock_reason_labels": {},
            "mandate_status": None,
            "latest_optimizer_status": None,
            "fidleg_basis": "Art. 16 / Art. 11 FIDLEG",
        }


# ---------------------------------------------------------------------------
# Sprint U-21 (2026-06-03): Liquidity-Cascade-Audit Wrapper.
# ---------------------------------------------------------------------------

def _build_liquidity_cascade(
    db: Session, mandate: Mandate,
) -> dict[str, Any]:
    """Wrapper über services/liquidity_cascade_audit.

    Liefert Stage-Classification fuer die aktive TargetAllocation
    (normal/hard_cap/emergency/unknown) + Berater-Hint bei
    Stage-3-Eskalation. Read-only, non-breaking.
    """
    try:
        from services.liquidity_cascade_audit import audit_mandate_liquidity_cascade
        return audit_mandate_liquidity_cascade(db, mandate)
    except Exception:  # noqa: BLE001
        return {
            "stage": "unknown",
            "stage_label": "Liquidity-Cascade-Stage kann nicht bestimmt werden.",
            "liquidity_bps": None,
            "hard_cap_bps": 300,
            "emergency_cap_bps": 1000,
            "over_hard_cap_by_bps": None,
            "warning_required": False,
            "beratungsgespraech_pruefen": False,
            "fidleg_basis": "Art. 11 / Art. 13 FIDLEG",
        }


# ---------------------------------------------------------------------------
# Roadmap #61 (2026-07-22): Reserve-Erklaerbarkeit im Report.
# ---------------------------------------------------------------------------
#
# Ziel: die Reserve-Herleitung (near-term-shortfall, Ziel-Reserven, SAA-
# Liquiditaets-Ceiling, externe Reserve, "Anderes Vermoegen"-Absorption),
# die services.portfolio_engine._compute_reserve_for_inputs bereits bei der
# Allokations-Generierung berechnet, als Berater-Narrativ im Report sichtbar
# machen. Rein additiv/erklaerend — die angezeigten Reserve-Betraege sind
# IMMER die bei der Allokations-Generierung persistierten Werte
# (reserve_needed_at_generation_rappen / external_reserve_at_generation_rappen)
# und werden hier NIE veraendert.
#
# Luecke (verifiziert 2026-07-22): der Read-/Rebuild-Pfad
# (build_target_payload_from_allocation) ruft _compute_reserve_for_inputs mit
# reasoning=None auf — die granularen Erklaerungstexte, die die Funktion bei
# der Generierung produziert, werden also aktuell NICHT persistiert und
# landen NICHT im Advisory-Report-Payload. Diese Sektion schliesst die
# Luecke, indem sie _compute_reserve_for_inputs — die Single Source of Truth
# fuer die Reserve-Logik — ein zweites Mal rein lesend mit denselben Inputs
# wie der Read-Pfad aufruft, um die reasoning-Liste zu ernten (nicht um neue
# Zahlen zu erzeugen). Nur wenn das frische Ergebnis exakt mit den
# persistierten Totalen uebereinstimmt, wird die Komposition angezeigt
# (fail-closed bei Datendrift seit Generierung — nie eine falsche Herleitung).


def _recompute_reserve_reasoning(
    db: Session, mandate: Mandate, ta: Any, saa_ceiling_bps: int,
) -> dict[str, Any] | None:
    """Ruft die Engine-Funktion `_compute_reserve_for_inputs` (Single Source
    of Truth, services/portfolio_engine.py) mit frischer reasoning-Liste auf,
    unter Verwendung derselben Inputs wie `build_target_payload_from_allocation`
    (Cashflows inkl. vermoegensgetriebener Ableitungen, Ziele, Wealth-Inflows,
    Mandats-Praeferenzen-Snapshot der TA). Reine Lese-Operation ohne DB-Writes.

    Gibt None bei jeglichem Fehler zurueck — der Aufrufer faellt dann auf die
    persistierten Totale ohne granulare Komposition zurueck (fail-closed).
    """
    from models.allocation import CapitalMarketAssumption
    from models.wealth import WealthInflow, WealthPosition
    from services.cashflow_timeline import recurring_net_cashflow_series, totals_for_year
    from services.portfolio_engine import (
        _allocation_snapshot_preferences,
        _compute_reserve_for_inputs,
        _inflation_path_series,
        _normalize_preferences,
        _simulation_horizon_years,
        _wealth_inflow_series_rappen,
    )
    from services.wealth_cashflows import derive_wealth_cashflows

    prefs = _normalize_preferences(_allocation_snapshot_preferences(ta))
    goals = list(_cached_active_goals(db, mandate))

    positions = (
        db.query(WealthPosition)
        .filter(
            WealthPosition.client_id == mandate.client_id,
            WealthPosition.deleted_at.is_(None),
            WealthPosition.is_active == 1,
        )
        .all()
    )
    advisory_wealth_rappen = sum(
        int(getattr(pos, "current_value_rappen", 0) or 0)
        for pos in positions
        if str(getattr(pos, "assignment", "")) == "Beratungsvermögen"
    )
    # Sprint B2 (portfolio_engine): Anderes-Vermoegen-Schloss-Pool, der die
    # externe Reserve reduzieren kann.
    unlocked_other_assets_rappen = sum(
        int(getattr(pos, "current_value_rappen", 0) or 0)
        for pos in positions
        if int(getattr(pos, "is_available_for_goal_funding", 0) or 0) == 1
        and str(getattr(pos, "assignment", "")) == "Anderes Vermögen"
    )

    cashflows = list(_cached_active_cashflows(db, str(mandate.client_id)))
    cashflows = cashflows + derive_wealth_cashflows(positions)

    # 2026-07-24 (Generalaudit): Fallback auf FXRateSource() statt None --
    # FXRateSource.from_db() faengt intern schon jeden Fehler ab und faellt
    # selbst auf Default-Kurse zurueck; dieser aeussere except greift
    # praktisch nie. fx_source=None wuerde die Konvertierung komplett
    # deaktivieren statt eine Naeherung zu zeigen.
    from services.currency.fx_rates import FXRateSource
    fx_source = None
    try:
        fx_source = FXRateSource.from_db(db)
    except Exception:  # noqa: BLE001
        fx_source = FXRateSource()
    target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()

    cma = (
        db.query(CapitalMarketAssumption)
        .filter(CapitalMarketAssumption.is_current == 1)
        .order_by(CapitalMarketAssumption.valid_from.desc())
        .first()
    )
    if cma is None:
        return None

    cashflow_totals = totals_for_year(cashflows, fx_source=fx_source, target_currency=target_currency)
    recurring_net_cashflow_rappen = (
        cashflow_totals["recurring_income_rappen"] - cashflow_totals["recurring_expense_rappen"]
    )
    projection_years = _simulation_horizon_years(prefs["simulation"], goals, mandate)
    cf_inflation_series_bps = _inflation_path_series(cma, projection_years, cashflow_totals["year"])
    recurring_cashflow_projection_series_rappen = recurring_net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
    )

    inflows = (
        db.query(WealthInflow)
        .filter(
            WealthInflow.client_id == mandate.client_id,
            WealthInflow.deleted_at.is_(None),
            WealthInflow.is_active == 1,
        )
        .all()
    )
    inflow_projection_series_rappen = _wealth_inflow_series_rappen(
        inflows, projection_years, cashflow_totals["year"], cf_inflation_series_bps,
    )

    reasoning: list[str] = []
    fresh_needed_rappen, fresh_external_rappen = _compute_reserve_for_inputs(
        goals=goals,
        limits_prefs=prefs["limits"],
        asset_class_prefs=prefs["assetClasses"],
        recurring_net_cashflow_rappen=recurring_net_cashflow_rappen,
        recurring_cashflow_projection_series_rappen=recurring_cashflow_projection_series_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        saa_liquidity_ceiling_bps=saa_ceiling_bps,
        reasoning=reasoning,
        unlocked_other_assets_rappen=unlocked_other_assets_rappen,
        inflow_projection_series_rappen=inflow_projection_series_rappen,
    )
    return {
        "reserve_needed_rappen": fresh_needed_rappen,
        "external_reserve_rappen": fresh_external_rappen,
        "advisory_wealth_rappen": advisory_wealth_rappen,
        "reasoning": reasoning,
    }


def _build_reserve_explainability(db: Session, mandate: Mandate) -> dict[str, Any]:
    """Sektion 28 (additiv, Roadmap #61) — Reserve-Erklaerbarkeit.

    Zeigt, WARUM die aktuelle Soll-Allokation eine Liquiditaetsreserve
    ausweist (near-term-Cashflow-Shortfall, Nahziele, manuelle Vorgabe) und
    ob/warum eine externe Reserve empfohlen wird (SAA-Liquiditaets-Ceiling
    ueberschritten), inkl. "Anderes Vermoegen"-Absorption falls zutreffend.

    Zahlen-Ground-Truth sind ausschliesslich die bei Allokations-Generierung
    persistierten Felder `reserve_needed_at_generation_rappen` /
    `external_reserve_at_generation_rappen` der aktuellen TargetAllocation —
    diese werden hier NIE neu berechnet oder ueberschrieben. Die granulare
    Komposition (Narrativ) wird nur gezeigt, wenn eine frische, rein lesende
    Nachrechnung ueber dieselbe Engine-Funktion exakt dieselben Totale
    liefert (sonst: Datendrift, Komposition wird unterdrueckt, Hinweis statt
    falscher Herleitung).

    Fail-closed: jeder Fehler (fehlende TA, Schema-Mismatch, Exception in der
    Nachrechnung) degradiert auf ein leeres/neutrales Schema statt zu
    crashen oder falsche Zahlen zu zeigen.
    """
    empty: dict[str, Any] = {
        "available": False,
        "reserve_needed_rappen": None,
        "external_reserve_rappen": None,
        "saa_liquidity_ceiling_bps": None,
        "external_reserve_recommended": False,
        "external_reserve_reason": None,
        "other_assets_absorption_rappen": None,
        "composition_available": False,
        "narrative": [],
        "drift_detected": False,
        "hinweis": "Keine Reserve-Herleitung verfuegbar (keine aktive Soll-Allokation).",
        "fidleg_basis": "Art. 8 / Art. 9 FIDLEG (Transparenz Kosten- und Anlageentscheid)",
    }
    try:
        ta = _cached_current_ta(db, mandate)
        if ta is None:
            return empty

        raw_needed = getattr(ta, "reserve_needed_at_generation_rappen", None)
        raw_external = getattr(ta, "external_reserve_at_generation_rappen", None)
        if raw_needed is None or raw_external is None:
            return {
                **empty,
                "hinweis": (
                    "Diese Soll-Allokation stammt aus einer Phase ohne persistierte "
                    "Reserve-Audit-Felder (Legacy). Bitte Strategie neu berechnen, "
                    "damit eine Reserve-Herleitung angezeigt werden kann."
                ),
            }

        reserve_needed_rappen = _safe_int(raw_needed)
        external_reserve_rappen = _safe_int(raw_external)

        from services.portfolio_engine import _SAA_LIQUIDITY_HARD_CAP_BPS
        band_liquidity_max_bps = getattr(ta, "band_liquidity_max_bps", None)
        saa_ceiling_bps = min(
            int(band_liquidity_max_bps) if band_liquidity_max_bps is not None
            else int(_SAA_LIQUIDITY_HARD_CAP_BPS),
            int(_SAA_LIQUIDITY_HARD_CAP_BPS),
        )

        if reserve_needed_rappen <= 0:
            return {
                **empty,
                "available": True,
                "reserve_needed_rappen": 0,
                "external_reserve_rappen": 0,
                "saa_liquidity_ceiling_bps": saa_ceiling_bps,
                "composition_available": True,
                "narrative": ["Fuer dieses Mandat besteht aktuell kein zusaetzlicher Liquiditaetsreserve-Bedarf."],
                "hinweis": None,
            }

        composition_available = False
        drift_detected = False
        narrative: list[str] = []
        other_assets_absorption_rappen: int | None = None

        try:
            fresh = _recompute_reserve_reasoning(db, mandate, ta, saa_ceiling_bps)
        except Exception:  # noqa: BLE001
            fresh = None

        if fresh is not None and (
            fresh["reserve_needed_rappen"] == reserve_needed_rappen
            and fresh["external_reserve_rappen"] == external_reserve_rappen
        ):
            composition_available = True
            narrative = list(fresh["reasoning"])
            advisory_wealth_rappen = int(fresh["advisory_wealth_rappen"] or 0)
            saa_reserve_rappen = int(round(saa_ceiling_bps * advisory_wealth_rappen / 10000))
            pre_absorption_external_rappen = max(0, reserve_needed_rappen - saa_reserve_rappen)
            other_assets_absorption_rappen = max(
                0, pre_absorption_external_rappen - external_reserve_rappen,
            )
        elif fresh is not None:
            drift_detected = True

        external_reserve_recommended = external_reserve_rappen > 0
        external_reserve_reason = (
            "Der Liquiditaetsbedarf uebersteigt die strategische SAA-Liquiditaets-"
            f"Obergrenze von {saa_ceiling_bps / 100:.1f}%. Der Ueberschuss wird als "
            "externe Reserve ausserhalb des Beratungsmandats empfohlen."
            if external_reserve_recommended else None
        )

        hinweis = None
        if drift_detected:
            hinweis = (
                "Hinweis: Die Reserve-Zusammensetzung konnte nicht im Detail "
                "hergeleitet werden, weil sich Cashflows, Ziele oder Praeferenzen "
                "seit der letzten Allokations-Generierung geaendert haben. Die "
                "angezeigten Reserve-Betraege sind unveraendert die bei der "
                "Generierung persistierten Werte. Strategie neu berechnen, um die "
                "Herleitung zu aktualisieren."
            )
        elif not composition_available:
            hinweis = (
                "Hinweis: Reserve-Zusammensetzung konnte nicht ermittelt werden."
            )

        return {
            "available": True,
            "reserve_needed_rappen": reserve_needed_rappen,
            "external_reserve_rappen": external_reserve_rappen,
            "saa_liquidity_ceiling_bps": saa_ceiling_bps,
            "external_reserve_recommended": external_reserve_recommended,
            "external_reserve_reason": external_reserve_reason,
            "other_assets_absorption_rappen": other_assets_absorption_rappen,
            "composition_available": composition_available,
            "narrative": narrative,
            "drift_detected": drift_detected,
            "hinweis": hinweis,
            "fidleg_basis": "Art. 8 / Art. 9 FIDLEG (Transparenz Kosten- und Anlageentscheid)",
        }
    except Exception:  # noqa: BLE001
        return empty


# ---------------------------------------------------------------------------
# Sprint U-94 (2026-06-05): Optimizer-Run-History (Sektion 24).
# ---------------------------------------------------------------------------

# Anzahl der zuletzt persistierten Runs die in der Berater-Sicht
# aufgelistet werden. Mehr als 10 wird unuebersichtlich; Compliance kann
# via Admin-Endpoint die volle Liste abrufen.
_OPTIMIZER_RUN_HISTORY_LIMIT = 10


def _build_optimizer_run_history(
    db: Session, mandate: Mandate,
) -> dict[str, Any]:
    """Liefert die letzten N Solver-Laufe fuer das Mandat als Audit-Trace.

    Quelle: models.allocation.OptimizerRun (persistiert vom
    portfolio_engine bei shadow_stochastic/stochastic-Modus). House-Matrix
    laeuft kein Solver -> kein Run persistiert.

    Liefert pro Run die Berater-relevanten Felder (run_at/mode/role/method/
    status/seed/iterations/objective_value_milli) — *keine* der
    JSON-Reasoning-Payloads, da fuer die Sektion 24 zu lang.

    Robust gegen Schema-Mismatch (Tabelle fehlt/leere FK) -> leere Liste.
    """
    try:
        from models.allocation import OptimizerRun

        runs = (
            db.query(OptimizerRun)
            .filter(OptimizerRun.mandate_id == mandate.id)
            .order_by(OptimizerRun.run_at.desc())
            .limit(_OPTIMIZER_RUN_HISTORY_LIMIT)
            .all()
        )
        items = [
            {
                "id": str(getattr(r, "id", "") or ""),
                "run_at": str(getattr(r, "run_at", "") or ""),
                "optimizer_mode": str(getattr(r, "optimizer_mode", "") or ""),
                "role": str(getattr(r, "role", "") or ""),
                "method": str(getattr(r, "method", "") or ""),
                "status": str(getattr(r, "status", "") or ""),
                "seed": _safe_int(getattr(r, "seed", 0)),
                "n_iterations": _safe_int(getattr(r, "n_iterations", 0)),
                "n_paths": _safe_int(getattr(r, "n_paths", 0)),
                "objective_value_milli": _safe_int(getattr(r, "objective_value_milli", 0)) or None,
                "target_allocation_id": (
                    str(getattr(r, "target_allocation_id", "") or "") or None
                ),
            }
            for r in runs
        ]
        total = (
            db.query(OptimizerRun)
            .filter(OptimizerRun.mandate_id == mandate.id)
            .count()
        )
        return {
            "items": items,
            "limit": _OPTIMIZER_RUN_HISTORY_LIMIT,
            "total_persisted": total,
            "fidleg_basis": "Art. 9 / Art. 14 FIDLEG (Nachvollziehbarkeit Empfehlungs-Methodik)",
        }
    except Exception:  # noqa: BLE001
        return {
            "items": [],
            "limit": _OPTIMIZER_RUN_HISTORY_LIMIT,
            "total_persisted": 0,
            "fidleg_basis": "Art. 9 / Art. 14 FIDLEG (Nachvollziehbarkeit Empfehlungs-Methodik)",
            "error": "Optimizer-Run-History konnte nicht geladen werden.",
        }


# ---------------------------------------------------------------------------
# Sprint C2-Wiring (2026-06-08): Engine-Configuration fuer Compliance-Audit-PDF.
# ---------------------------------------------------------------------------

_IS_AKTIV_PATTERNS = ("importance sampling aktiv", "is aktiv", "is-aktiv")
_IS_INAKTIV_PATTERNS = ("importance sampling inaktiv", "is inaktiv", "is-inaktiv")


def _detect_is_status_from_reasoning(reasoning_text: str) -> tuple[bool, str]:
    """Sprint C2 (2026-06-08): Parst die OptimizerRun.reasoning_json (lowercased)
    nach IS-Status. Konvention aus P1: solver.py schreibt entweder
    'Importance Sampling AKTIV (...)' oder 'Importance Sampling INAKTIV (...)'.

    Returns (is_active, reason_excerpt). reason_excerpt ist der erste relevante
    Reasoning-Eintrag fuer das Audit-Display.
    """
    lower = reasoning_text.lower()
    if any(p in lower for p in _IS_AKTIV_PATTERNS):
        return True, "Importance Sampling aktiv (Tail-Schutz fuer Shortfall-Berechnung)"
    if any(p in lower for p in _IS_INAKTIV_PATTERNS):
        return False, "Standard-MC (uniformer Sample-Mean)"
    return False, ""


def _detect_tax_mode_from_settings() -> str:
    """Sprint C2: liest Tax-Mode aus Settings/Defaults.

    Aktuell: scenario_engine default 'median' (Backwards-Compat). HNW-Caller
    koennen 'binned' setzen — sichtbar machen ob ein anderes Mode aktiv ist.
    """
    try:
        from config import settings
        # Settings-Hooks falls in Zukunft pro-Mandate-Tax-Mode-Konfiguration
        # eingefuehrt wird. Aktuell: konservativer Default 'median'.
        return str(getattr(settings, "mc_default_tax_mode", "median") or "median")
    except Exception:
        return "median"


def _detect_sub_allocation_aware(db: Session, mandate: Mandate) -> bool:
    """Sprint C2: True wenn das Mandate eine Sub-Allocation gepflegt hat
    (`SubAllocation`-Tabelle oder TargetAllocation-Sub-Felder). False sonst.

    Defensive: bei Schema-Mismatch / Tabelle fehlt -> False, kein Crash.
    """
    try:
        from models.allocation import TargetAllocation
        ta = (
            db.query(TargetAllocation)
            .filter(
                TargetAllocation.mandate_id == mandate.id,
                TargetAllocation.is_active == 1,
            )
            .order_by(TargetAllocation.created_at.desc())
            .first()
        )
        if not ta:
            return False
        sub_json = getattr(ta, "sub_allocation_json", "") or ""
        if sub_json and sub_json.strip() not in ("", "[]", "{}", "null"):
            return True
        return False
    except Exception:
        return False


def _build_engine_configuration(
    db: Session, mandate: Mandate,
) -> dict[str, Any]:
    """Sprint C2-Wiring (2026-06-08): Engine-Configuration fuer
    Compliance-Audit-Block.

    Extrahiert den IS-Status aus der LETZTEN OptimizerRun.reasoning_json.
    Falls keine OptimizerRun existiert (House-Matrix-Mode), wird das mit
    optimizer_mode='house_matrix' kommuniziert.

    Felder im Output (gelesen von services.pdf.components.compliance_audit
    ._engine_configuration_block):
    - importance_sampling_active: bool
    - importance_sampling_reason: str (menschen-lesbar)
    - tax_mode: 'median'|'binned'|'per_path'
    - sub_allocation_aware: bool
    - optimizer_mode: 'house_matrix'|'stochastic'|'shadow_stochastic'
    """
    is_active = False
    is_reason = ""
    optimizer_mode = "house_matrix"
    try:
        from models.allocation import OptimizerRun
        latest_run = (
            db.query(OptimizerRun)
            .filter(OptimizerRun.mandate_id == mandate.id)
            .order_by(OptimizerRun.run_at.desc())
            .first()
        )
        if latest_run is not None:
            optimizer_mode = str(getattr(latest_run, "optimizer_mode", "") or "stochastic")
            reasoning_raw = str(getattr(latest_run, "reasoning_json", "") or "")
            if reasoning_raw:
                # reasoning_json kann list[str] sein — wir suchen text-basiert
                is_active, is_reason = _detect_is_status_from_reasoning(reasoning_raw)
    except Exception:
        # Defensive: Schema-Mismatch / fehlende OptimizerRun-Tabelle -> Defaults
        pass

    tax_mode = _detect_tax_mode_from_settings()
    sub_alloc_aware = _detect_sub_allocation_aware(db, mandate)

    return {
        "importance_sampling_active": is_active,
        "importance_sampling_reason": is_reason,
        "tax_mode": tax_mode,
        "sub_allocation_aware": sub_alloc_aware,
        "optimizer_mode": optimizer_mode,
        "audit_basis": "Risiko-Engine-Konfiguration zum Zeitpunkt der letzten Strategie-Berechnung.",
    }


# ---------------------------------------------------------------------------
# Sprint U-97 (2026-06-06): Performance-Attribution (Brinson) als Sektion 25.
# ---------------------------------------------------------------------------

def _build_performance_attribution(
    db: Session, mandate: Mandate,
) -> dict[str, Any]:
    """Liefert Brinson-Attribution (Allocation/Selection/Interaction) der
    aktuellen TargetAllocation vs House-Matrix-Default fuer das Mandat.

    Quelle Portfolio-Weights: aktive TargetAllocation (target_*_bps Felder).
    Quelle Benchmark-Weights: HouseMatrix-Default fuer den Risk-Score des
    Mandat-Risikoprofils.
    Quelle Returns: aktuelle CMA-Erwartungen pro Bucket.

    In 5eyes' forward-looking Framework sind benchmark_returns == portfolio_returns
    pro Bucket (gleiche CMA). Daher Selection ≈ 0, Interaction ≈ 0; nur
    Allocation-Effekt zeigt den Wert der SAA-Tilts vs Benchmark.

    Robust gegen Schema-Mismatch -> degraded mit `error`-Key.
    """
    try:
        from models.allocation import (
            CapitalMarketAssumption,
            HouseMatrix,
            OptimizerPolicy,
            TargetAllocation,
        )
        from models.profiling import RiskAssessment
        from services.performance_attribution import (
            BUCKET_KEYS,
            compute_brinson_attribution,
        )

        ta = (
            db.query(TargetAllocation)
            .filter(
                TargetAllocation.mandate_id == mandate.id,
                TargetAllocation.is_current == 1,
                TargetAllocation.deleted_at.is_(None),
            )
            .first()
        )
        if ta is None:
            return _performance_attribution_empty("Keine aktive TargetAllocation.")

        # Portfolio-Weights aus TA
        portfolio_weights = {
            "equities": _safe_int(getattr(ta, "target_equities_bps", 0)),
            "bonds": _safe_int(getattr(ta, "target_bonds_bps", 0)),
            "real_estate": _safe_int(getattr(ta, "target_real_estate_bps", 0)),
            "alternatives": _safe_int(getattr(ta, "target_alternatives_bps", 0)),
            "liquidity": _safe_int(getattr(ta, "target_liquidity_bps", 0)),
        }

        # Benchmark-Weights aus HouseMatrix fuer den Risk-Score des Mandats
        ra = (
            db.query(RiskAssessment)
            .filter(
                RiskAssessment.mandate_id == mandate.id,
                RiskAssessment.is_current == 1,
            )
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        risk_score = _safe_int(getattr(ra, "final_score_x10", 0)) if ra else 0
        policy_id = getattr(ta, "policy_id", None)
        hm_row = None
        if policy_id and risk_score > 0:
            hm_row = (
                db.query(HouseMatrix)
                .filter(
                    HouseMatrix.policy_id == policy_id,
                    HouseMatrix.is_active == 1,
                    HouseMatrix.score_from <= risk_score,
                    HouseMatrix.score_to >= risk_score,
                )
                .first()
            )
        if hm_row is None:
            return _performance_attribution_empty(
                "Keine House-Matrix-Default fuer das Risikoprofil gefunden."
            )
        benchmark_weights = {
            "equities": _safe_int(getattr(hm_row, "equity_target_bps", 0)),
            "bonds": _safe_int(getattr(hm_row, "bonds_target_bps", 0)),
            "real_estate": _safe_int(getattr(hm_row, "real_estate_target_bps", 0)),
            "alternatives": _safe_int(getattr(hm_row, "alt_target_bps", 0)),
            "liquidity": _safe_int(getattr(hm_row, "liq_target_bps", 0)),
        }

        # Returns aus aktueller CMA (gleich fuer Portfolio + Benchmark)
        cma = (
            db.query(CapitalMarketAssumption)
            .filter(CapitalMarketAssumption.is_current == 1)
            .order_by(CapitalMarketAssumption.valid_from.desc())
            .first()
        )
        if cma is None:
            return _performance_attribution_empty(
                "Keine aktuelle CMA verfuegbar."
            )
        returns_bps = {
            "equities": _safe_int(getattr(cma, "equity_ch_return_bps", 0)),
            "bonds": _safe_int(getattr(cma, "bonds_chf_ig_return_bps", 0)),
            "real_estate": _safe_int(getattr(cma, "real_estate_ch_return_bps", 0)),
            "alternatives": _safe_int(getattr(cma, "alternatives_gold_return_bps", 0)),
            "liquidity": _safe_int(getattr(cma, "liquidity_return_bps", 0)),
        }

        result = compute_brinson_attribution(
            portfolio_weights_bps=portfolio_weights,
            benchmark_weights_bps=benchmark_weights,
            portfolio_returns_bps=returns_bps,
        )
        payload = result.to_dict()
        payload["method"] = "brinson_fachler_hood_1986"
        payload["benchmark_source"] = "house_matrix_default_for_risk_score"
        payload["fidleg_basis"] = (
            "Art. 9 / Art. 14 FIDLEG (Methoden-Transparenz vs Benchmark)"
        )
        return payload
    except Exception as exc:  # noqa: BLE001
        return _performance_attribution_empty(
            f"Performance-Attribution konnte nicht berechnet werden: {exc}"
        )


def _performance_attribution_empty(reason: str) -> dict[str, Any]:
    """Default-Payload wenn keine Berechnung moeglich (UI zeigt 'nicht beurteilbar')."""
    return {
        "buckets": [],
        "total_portfolio_return_bps": 0,
        "total_benchmark_return_bps": 0,
        "total_excess_return_bps": 0,
        "total_allocation_effect_bps": 0,
        "total_selection_effect_bps": 0,
        "total_interaction_effect_bps": 0,
        "method": "brinson_fachler_hood_1986",
        "benchmark_source": "house_matrix_default_for_risk_score",
        "fidleg_basis": (
            "Art. 9 / Art. 14 FIDLEG (Methoden-Transparenz vs Benchmark)"
        ),
        "error": reason,
    }
