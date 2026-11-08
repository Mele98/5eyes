"""Ex-ante cost disclosure for the Advisory-Report.

The service keeps calculation and persistence access outside the PDF layer.
Amounts are stored in Rappen and rates in basis points. Unknown costs are never
silently treated as zero.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
from numbers import Real
from typing import Any, Iterable, Mapping

from sqlalchemy import text as _sql_text
from sqlalchemy.orm import Session


DEFAULT_TRANSACTION_COST_BPS = 15
# N-858-11: Hinweis, wenn die Liquiditaetsreserve das ganze Beratungsvermoegen
# beansprucht (Strategiebasis 0) -- kein Produktvolumen, nur Dienstleistungskosten.
ZERO_STRATEGY_BASE_COST_NOTE = (
    "Keine investierbare Strategiebasis: Die Liquiditätsreserve beansprucht das "
    "gesamte Beratungsvermögen. Es wird nichts investiert; Produktkosten "
    "(TER) fallen auf das Zielvolumen 0 nicht an. Die Dienstleistungskosten "
    "beziehen sich auf das Beratungsvermögen."
)


class CostDisclosureDomainError(ValueError):
    """Ein Modelleingang des Kostenausweises ist nicht verwertbar.

    COST-DOMAIN-001 (CERT-COST-CONFLICT-001). Erbt von `ValueError`, damit
    bestehende Aufrufer, die breit auf Wertfehler pruefen, unveraendert
    funktionieren; `reason_code` und `location` machen die Ablehnung
    maschinenlesbar und stabil zitierbar.
    """

    def __init__(self, message: str, *, reason_code: str, location: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.location = location


# Stabile Begruendungscodes -- bewusst Konstanten, damit ein Aufrufer sie
# vergleichen kann, ohne auf Meldungstexte zu matchen.
REASON_RATE_NOT_A_NUMBER = "fee_rate_not_a_number"
REASON_RATE_NOT_INTEGRAL = "fee_rate_not_integral"
REASON_RATE_NEGATIVE = "fee_rate_negative"


def _require_rate_bps(value: Any, *, location: str) -> int:
    """Typisierte Annahme eines Gebuehrensatzes in Basispunkten.

    COST-DOMAIN-001. Vorher lief jeder Satz durch
    `max(0, _safe_int(value))` -- zwei Stillschweige-Mechanismen
    uebereinander:

        "not-a-rate" -> _safe_int faengt den ValueError      -> 0
        -75          -> max(0, ...) verschluckt das Vorzeichen -> 0

    Beide ergaben einen Posten mit 0 bps, der als "konfiguriert" galt: das
    FIDLEG-Dokument wies eine KOSTENLOSE Dienstleistung aus, wo tatsaechlich
    ein unverwertbarer Wert hinterlegt war. Eine Null ist hier nicht die
    konservative Annahme, sondern die guenstigste -- und damit die falsche
    Richtung fuer einen Pflichtausweis.

    Gleiches Muster und gleiche Reihenfolge der Pruefungen wie
    `services/cma_validation.py::_integral_bps` (bool zuerst, dann
    Zahl/endlich, dann Ganzzahligkeit) -- kein neu erfundener Kontrakt.

    KEINE Obergrenze, bewusst: fuer Gebuehrensaetze existiert in diesem
    Repo kein Praezedenzfall (anders als `_INDUCEMENT_SANITY_CEILING_RAPPEN`
    fuer Betraege, der aus einem Audit stammt). Einen Plausibilitaetsdeckel
    zu erfinden, koennte legitime Konfigurationen ablehnen; ein absurd
    HOHER Satz ist im Dokument ausserdem sichtbar, waehrend die stille Null
    es nicht war. Der behobene Fehler ist das Verschweigen, nicht die
    Groesse.
    """
    if isinstance(value, bool):
        # `True` als Satz hiesse 1 bps -- Unsinn, und ein typischer
        # JSON-Unfall. Gleiche Ablehnung wie _integral_bps.
        raise CostDisclosureDomainError(
            f"{location} muss eine ganze Zahl in Basispunkten sein (bool erhalten).",
            reason_code=REASON_RATE_NOT_A_NUMBER,
            location=location,
        )
    if not isinstance(value, Real):
        raise CostDisclosureDomainError(
            f"{location} muss eine Zahl sein, erhalten: {value!r}.",
            reason_code=REASON_RATE_NOT_A_NUMBER,
            location=location,
        )
    number = float(value)
    if not math.isfinite(number):
        raise CostDisclosureDomainError(
            f"{location} muss endlich (finite) sein.",
            reason_code=REASON_RATE_NOT_A_NUMBER,
            location=location,
        )
    if not number.is_integer():
        raise CostDisclosureDomainError(
            f"{location} muss eine GANZE Zahl in Basispunkten sein, erhalten: {value!r}.",
            reason_code=REASON_RATE_NOT_INTEGRAL,
            location=location,
        )
    rate = int(number)
    if rate < 0:
        # Ein negativer Gebuehrensatz ist keine Gebuehr. Eine Verguetung AN
        # den Kunden hat ihren eigenen Kanal (Retrozessions-Rueckerstattung,
        # negativer Posten) -- sie durch ein Minuszeichen im Gebuehrenmodell
        # auszudruecken wuerde sie am Offenlegungsweg vorbeifuehren.
        raise CostDisclosureDomainError(
            f"{location} darf nicht negativ sein, erhalten: {rate}.",
            reason_code=REASON_RATE_NEGATIVE,
            location=location,
        )
    return rate

# TEN-COMP-003 Teil 2 (Codex-Audit 2026-08-27, Folgeaudit): Teil 1 (schemas/review.py
# Field(ge=0)) blockierte nur einen direkt negativen inducement_amount_rappen. Der
# reproduzierte Angriff nutzt stattdessen einen absurd GROSSEN positiven Betrag
# kombiniert mit reimbursed_to_client=True + jaehrlicher Frequenz: dieser Wert wurde
# unbegrenzt vom Total abgezogen und konnte den ausgewiesenen Kostenausweis beliebig
# negativ machen -- ohne jeden Zahlungsnachweis, dass die Rueckerstattung tatsaechlich
# stattgefunden hat. Die Schema-Schranke (le=) faengt das bereits an der API-Grenze ab;
# diese zweite, unabhaengige Pruefung hier ist Verteidigung in der Tiefe fuer jeden
# Aufrufer von calculate_cost_disclosure(), der die Schema-Validierung nicht
# durchlaeuft (z.B. interne Neuberechnung aus persistierten Altdaten). Gleiches
# konservatives Muster wie bei unbelegter Frequenz weiter unten: nicht stillschweigend
# vertrauen, sondern von included_in_total ausschliessen + Warnung ausgeben. Der volle
# Zahlungsnachweis-/Beleg-Datenmodell-Fix bleibt bewusst zurueckgestellt (Policy-
# Entscheid, siehe Audit-Dokument).
_INDUCEMENT_SANITY_CEILING_RAPPEN = 1_000_000_000  # CHF 10'000'000.00 je Position


def _has_documented_waiver(inducement: Mapping[str, Any]) -> bool:
    """Belegt diese Retrozession einen gueltigen Kundenverzicht?

    INDUCEMENT-EVIDENCE-001. BGE 132 III 460 / Art. 400 OR: eine Retrozession
    gehoert dem Kunden, AUSSER er hat vorgaengig und in Kenntnis der
    Groessenordnung gueltig verzichtet. Der Kostenausweis darf einen solchen
    Verzicht nur dann behaupten, wenn er auch belegt ist.

    Geprueft wird genau das, was das Etikett BEHAUPTET -- nicht mehr:

        "ist offengelegt"            -> `disclosed_to_client`
        "dokumentierter Verzicht"    -> `waiver_document_id`

    `client_acknowledged` wird hier ABSICHTLICH nicht mitgefordert. Das Feld
    protokolliert die Kenntnisnahme der KONFLIKT-Offenlegung, nicht den
    Verzicht; das unterschriebene Verzichts-Dokument ist der staerkere und
    der hier einschlaegige Nachweis. Beides zu verlangen hiesse, eine
    Bedingung zu erfinden, die das Etikett nicht aufstellt -- und ein
    korrekt abgelegtes Verzichts-Dokument an einem nicht gesetzten Haken
    scheitern zu lassen. Der Zustand von `client_acknowledged` wird ueber
    die Konflikt-Offenlegung berichtet (CONFLICT-STATE-001), nicht hier.

    GRENZE, ausdruecklich: `waiver_document_id` ist eine freie Spalte ohne
    Fremdschluessel auf eine Dokumententabelle (siehe models/review.py).
    Geprueft wird deshalb die VORHANDENHEIT einer Referenz, nicht die
    Existenz des Dokuments. Das schliesst die Luecke "Verzicht behauptet,
    nie offengelegt, nichts abgelegt"; es schliesst nicht "ID zeigt auf ein
    Dokument, das es nicht gibt". Letzteres braucht den Fremdschluessel und
    ist mit dieser Aenderung NICHT behoben.
    """
    if not bool(inducement.get("disclosed_to_client")):
        return False
    return bool(str(inducement.get("waiver_document_id") or "").strip())

_ANNUAL_RATE_KEYS = (
    (
        ("default_advisory_fee_bps", "advisory_fee_bps"),
        "Beratungs-/Verwaltungsgebühr",
    ),
    (
        ("management_fee_bps", "portfolio_management_fee_bps"),
        "Vermögensverwaltungsgebühr",
    ),
    (
        ("custody_fee_bps", "depot_fee_bps"),
        "Depot-/Verwahrgebühr",
    ),
    (
        ("platform_fee_bps",),
        "Plattformgebühr",
    ),
)
_ONE_TIME_RATE_KEYS = (
    (
        ("onboarding_fee_bps", "setup_fee_bps", "initial_fee_bps"),
        "Einrichtungs-/Startgebühr",
    ),
    (
        ("entry_fee_bps",),
        "Einstiegsgebühr",
    ),
)

# COST-CONTEXT-001a (CERT-COST-CONFLICT-001): Rangfolge der Kostenquelle.
#
# Vorher waehlte `build_cost_disclosure()` rein nach `created_at.desc()`, ohne
# jeden Status-Filter. Folgen, gemessen am Reproducer:
#
#   Ein spaeterer DRAFT (Gebuehrenmodell 999 bps) verdraengte den
#   zertifizierten FINAL-Lauf (25 bps) als Grundlage des FIDLEG-Dokuments --
#   das Dokument zeigte Kosten eines Entwurfs, den niemand freigegeben hat.
#
# Dazu zwei Zustaende, die der Reproducer nicht nennt, aber dieselbe Abfrage
# treffen: `result_status` erlaubt auch 'Rejected' und 'Superseded' (CHECK in
# ares_schema.sql). Ein ABGELEHNTER Lauf konnte damit die
# Kostengrundlage des Kunden sein, und ein durch einen neueren Final
# ERSETZTER ebenso.
#
# Rangfolge statt Datum:
#   'Final' -- der zertifizierte Lauf. Es gibt hoechstens einen; jeder
#              weitere Final setzt die uebrigen auf 'Superseded'
#              (routers/review.py::finalize_recommendation).
#   'Draft' -- waehrend der Vorbereitung legitim: der Berater will die
#              Kosten sehen, bevor er finalisiert. Darf einen Final aber
#              NICHT verdraengen, deshalb zweiter Rang.
#
# 'Rejected' und 'Superseded' sind BEWUSST keine Quelle. Beides stillschweigend
# zu verwenden waere die falsche Richtung: ein abgelehnter Entwurf ist keine
# Empfehlung, und ein ersetzter Lauf ist nicht der aktuelle Stand. Existieren
# nur solche, antwortet die Funktion `_pending_payload` mit Begruendung.
# COST-RUN-RESOLVER-001: die Rangfolge wird jetzt von
# services/recommendation_run_resolver.py durchgesetzt (zusaetzlich gebunden
# an die aktuelle TargetAllocation); hier nur noch als Alias dokumentiert.
from services.recommendation_run_resolver import (  # noqa: E402
    RESOLVABLE_STATUS_PRIORITY as _COST_SOURCE_STATUS_PRIORITY,
)


_CURRENT_TA_UNSET: Any = object()


def _current_target_allocation_id(db: Session, mandate: Any) -> tuple[Any, str | None]:
    """ID der AKTUELLEN TargetAllocation (wie routers.pdf_reports.
    _latest_target_allocation). Rueckgabe ``(id, fehlergrund)``."""
    from models.allocation import TargetAllocation

    rows = (
        db.query(TargetAllocation.id)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .order_by(TargetAllocation.version.desc(), TargetAllocation.created_at.desc())
        .limit(2)
        .all()
    )
    if len(rows) > 1:
        return None, (
            "Mehrere aktuelle Soll-Allokationen gefunden; der Kostenausweis "
            "kann erst nach Bereinigung des Strategie-Stands erstellt werden."
        )
    return (rows[0][0] if rows else None), None


def build_cost_disclosure(
    db: Session,
    mandate: Any,
    *,
    target_allocation_id: Any = _CURRENT_TA_UNSET,
) -> dict[str, Any]:
    """Build a stable ex-ante cost payload for one mandate.

    COST-RUN-RESOLVER-001: der Quelllauf ist der Lauf der AKTUELLEN
    TargetAllocation (``resolve_current_recommendation_run``: Final, sonst
    Draft, gebunden an die aktuelle TA) -- dieselbe Regel wie Anlagestrategie-,
    Portfolio-PDF und Beratungsentscheid. Dessen eingefrorener Nachweis
    (COST-CONTEXT-001b) bleibt pro Lauf. Ohne aktuellen Lauf: expliziter
    Zustand "keine aktuelle Produktempfehlung", nie die Zahlen eines Laufs
    einer ueberholten Allokation.

    ``target_allocation_id`` erlaubt Aufrufern mit bereits geladener
    aktueller TA (Advisory-Report-Cache), die TA-Abfrage zu sparen.
    """
    from models.review import RecommendationRun
    from services.recommendation_run_resolver import (
        NO_CURRENT_RECOMMENDATION_MARKER,
        resolve_current_recommendation_run,
    )

    currency = str(getattr(mandate, "base_currency", None) or "CHF").upper().strip() or "CHF"

    if target_allocation_id is _CURRENT_TA_UNSET:
        target_allocation_id, ta_problem = _current_target_allocation_id(db, mandate)
        if ta_problem is not None:
            return _pending_payload(ta_problem, currency=currency)

    # COST-CONTEXT-001a bleibt als Rangfolge erhalten (Final vor Draft,
    # Rejected/Superseded nie) -- sie steckt jetzt im gemeinsamen Resolver,
    # zusaetzlich gebunden an die aktuelle TA. Eine Abfrage, wie vorher
    # (N+1-Guard `test_specific_tables_are_queried_at_most_twice`).
    best_run = resolve_current_recommendation_run(db, mandate.id, target_allocation_id)

    if best_run is None:
        # Diagnose nur im Pending-Pfad (kein Einfluss auf den Normalfall):
        # "gar kein Lauf" und "Laeufe vorhanden, aber keiner taugt" sind
        # verschiedene Lagen, die der Berater unterscheiden muss.
        latest_any = (
            db.query(RecommendationRun)
            .filter(RecommendationRun.mandate_id == mandate.id)
            .order_by(RecommendationRun.created_at.desc())
            .first()
        )
        if latest_any is None:
            return _pending_payload(
                "Noch keine Portfolioempfehlung vorhanden "
                f"({NO_CURRENT_RECOMMENDATION_MARKER}); ein konkreter "
                "Ex-ante-Kostenausweis kann noch nicht berechnet werden.",
                currency=currency,
            )
        latest_status = str(getattr(latest_any, "result_status", "") or "")
        bound_to_current = bool(target_allocation_id) and (
            str(getattr(latest_any, "target_allocation_id", "") or "")
            == str(target_allocation_id)
        )
        if bound_to_current:
            detail = (
                f"letzter Status: {latest_status or 'unbekannt'}. Ein "
                "abgelehnter oder ersetzter Lauf ist keine Grundlage für den "
                "Kostenausweis"
            )
        else:
            detail = (
                f"letzter Lauf (Status: {latest_status or 'unbekannt'}) gehört "
                "zu einer überholten Soll-Allokation. Seine Kosten passen nicht "
                "zur aktuellen Strategie"
            )
        return _pending_payload(
            f"Zur aktuellen Soll-Allokation liegt {NO_CURRENT_RECOMMENDATION_MARKER} "
            f"vor ({detail}) -- Strategie neu berechnen und finalisieren.",
            currency=currency,
        )

    # COST-CONTEXT-001b: ein FINALISIERTER Lauf traegt seinen Nachweis mit
    # sich. Ihn zurueckzugeben statt neu zu rechnen ist der ganze Punkt --
    # live gerechnet aenderte eine spaetere TER-Korrektur die Totale eines
    # bereits ausgehaendigten Dokuments.
    frozen, snapshot_reason = load_frozen_cost_disclosure(best_run)
    if frozen is not None:
        return frozen
    if snapshot_reason is not None:
        # Snapshot vorhanden, aber unbrauchbar (kaputtes JSON oder Hash
        # passt nicht zum Inhalt). Hier NICHT live weiterrechnen: der Lauf
        # behauptet einen Nachweis, und ihn stillschweigend durch frische
        # Zahlen zu ersetzen waere genau die Substitution, die dieser
        # Nachweis verhindern soll.
        #
        # COST-SNAPSHOT-BINDING-001: der Fehler ist AUSGEWIESEN, nicht nur in
        # einem Freitext versteckt -- `evidence_status="blocked"` +
        # maschinenlesbarer `evidence_error`, und `audit_degraded=True`,
        # damit jedes bestehende Publikations-Gate (Advisory-Report-PDF,
        # React-Sektion) greift, ohne auf Meldungstexte zu matchen.
        return blocked_cost_disclosure_payload(
            snapshot_reason,
            currency=currency,
            source_run_id=_opt_str(getattr(best_run, "id", None)),
            source_run_status=_opt_str(getattr(best_run, "result_status", None)),
        )

    live = build_cost_disclosure_for_run(db, mandate, best_run, currency=currency)
    if not live.get("data_pending"):
        # Offenlegen, nicht behaupten: ohne Snapshot ist dieser Ausweis eine
        # Momentaufnahme. Fuer Entwuerfe ist das richtig und erwartet; bei
        # einem Final bedeutet es, dass der Lauf vor Einfuehrung der Spalte
        # finalisiert wurde.
        live["evidence_frozen"] = False
        live["content_hash"] = None
        live["frozen_at"] = None
        live["evidence_error"] = None
        live["evidence_status"] = (
            EVIDENCE_STATUS_LEGACY_UNVERIFIED
            if str(live.get("source_run_status") or "") == "Final"
            else EVIDENCE_STATUS_PREVIEW
        )
        if str(live.get("source_run_status") or "") == "Final":
            live.setdefault("warnings", []).append(
                "Dieser freigegebene Empfehlungslauf hat keinen eingefrorenen "
                "Kostenausweis (finalisiert vor Einführung des Nachweises). "
                "Die Zahlen sind live berechnet und können von den damals "
                "ausgewiesenen abweichen -- für einen belegbaren Ausweis die "
                "Strategie neu berechnen und finalisieren."
            )
    return live


def _position_amount_rappen(position: Any) -> int:
    """N-858-11: Zielbetrag 0 ist ein Volumen (Strategiebasis 0), keine
    fehlende Angabe. Nur ein fehlender Zielbetrag (``None``, Altbestand)
    faellt auf den Ist-Betrag zurueck."""
    target = getattr(position, "target_amount_rappen", None)
    if target is not None:
        return int(target)
    return int(getattr(position, "current_amount_rappen", None) or 0)


def build_cost_disclosure_for_run(
    db: Session,
    mandate: Any,
    run: Any,
    *,
    currency: str | None = None,
) -> dict[str, Any]:
    """Kostenausweis fuer EINEN bestimmten Empfehlungslauf.

    Herausgeloest aus `build_cost_disclosure()` (2026-10-13), damit ein
    Aufrufer den Lauf VORGEBEN kann statt ihn waehlen zu lassen. Zwei
    Stellen brauchen das:

      * das Einfrieren bei der Finalisierung (COST-CONTEXT-001b) -- dort
        steht der Lauf fest, und eine erneute Auswahl koennte einen
        anderen treffen;
      * der Beratungsprotokoll-Nachweis (COST-EVIDENCE-001), der an
        seinem EIGENEN `recommendation_run_id` haengt und bisher den
        mandatsweiten Bauer aufrief.

    Die Funktion waehlt nichts aus und liest keinen Snapshot -- sie
    rechnet. Das Einfrieren und das Zurueckgeben eines eingefrorenen
    Nachweises liegen in `build_cost_disclosure()`.
    """
    # Lazy Imports wie zuvor im Kopf von build_cost_disclosure() -- die
    # Begruendung (Zirkular-Import-Haertung) gilt unveraendert, nur die
    # Funktion hat sich geaendert.
    from models.allocation import OptimizerPolicy, TargetAllocation
    from models.review import (
        ConflictOfInterestDisclosure, Product, ProductUniverseEntry,
        RecommendationHolding, RecommendationPosition, RecommendationRun,
    )

    currency = str(
        currency or getattr(mandate, "base_currency", None) or "CHF"
    ).upper().strip() or "CHF"
    latest_run = run

    fee_model = _parse_fee_model(getattr(latest_run, "fee_assumptions_json", None))
    if not fee_model:
        policy = (
            db.query(OptimizerPolicy)
            .filter(OptimizerPolicy.id == latest_run.policy_id)
            .first()
        )
        fee_model = _parse_fee_model(getattr(policy, "fee_model_json", None))

    # PO-17 / N-856-3 / N-856-9: EINE Abfrage (Report-Query-Budget) liefert
    # die Positionen dieses Laufs UND aller frueheren Laeufe des Mandats (bis
    # zu diesem), jeweils mit ihren Holdings per Outer Join. Je Position dieses
    # Laufs zaehlt die juengste Holding (Regel des Live-Rebalancings, geloescht
    # = kein Bestand); aus den frueheren Laeufen je Produkt die juengste
    # Holding (Regel von holdings_not_carried_over).
    run_created_at = str(getattr(latest_run, "created_at", "") or "")
    joined_rows = (
        db.query(RecommendationPosition, Product, RecommendationHolding, RecommendationRun.created_at)
        .join(Product, Product.id == RecommendationPosition.product_id)
        .join(RecommendationRun, RecommendationRun.id == RecommendationPosition.run_id)
        .outerjoin(
            RecommendationHolding,
            (RecommendationHolding.recommendation_position_id == RecommendationPosition.id)
            & (RecommendationHolding.run_id == RecommendationPosition.run_id),
        )
        .filter(
            RecommendationRun.mandate_id == mandate.id,
            (RecommendationPosition.run_id == latest_run.id)
            | (RecommendationRun.created_at <= run_created_at),
        )
        .all()
    )
    rows = []
    latest_holding: dict[str, Any] = {}
    earlier_holdings: list[tuple[str, Any]] = []
    for position, product, holding, created_at in joined_rows:
        if position.run_id != latest_run.id:
            if holding is not None:
                earlier_holdings.append((str(created_at or ""), holding))
            continue
        if position.id not in latest_holding:
            rows.append((position, product))
            latest_holding[position.id] = None
        if holding is not None:
            current = latest_holding[position.id]
            if current is None or str(holding.updated_at or "") > str(current.updated_at or ""):
                latest_holding[position.id] = holding
    # 2026-07-27 (Fonds-Kuratierung): eine Verwaltung kann fuer ein Produkt
    # eine eigene, ausgehandelte Gebuehr hinterlegt haben (ProductUniverseEntry.
    # override_ter_bps) -- live nachgeschlagen (kein Snapshot), damit eine
    # spaetere Korrektur der Konditionen sofort im naechsten Kostenausweis
    # wirkt. Betrifft NUR diesen Tenant, das globale Produkt bleibt unveraendert.
    # mandate.tenant_id=NULL -> DEFAULT_TENANT_ID ('main'), gleiches Muster wie
    # services/auth.py::_resolve_tenant_id_for_user + portfolio_engine-Filter.
    ter_bps_overrides: dict[str, int] = {}
    if rows:
        from models.tenant import DEFAULT_TENANT_ID
        from jurisdictions.resolve import resolve_pack
        tenant_id = getattr(mandate, "tenant_id", None) or DEFAULT_TENANT_ID
        jurisdiction = resolve_pack(mandate).code
        product_ids = {product.id for _, product in rows}
        override_entries = (
            db.query(ProductUniverseEntry)
            .filter(
                ProductUniverseEntry.tenant_id == tenant_id,
                ProductUniverseEntry.jurisdiction == jurisdiction,
                ProductUniverseEntry.product_id.in_(product_ids),
                ProductUniverseEntry.deleted_at.is_(None),
                ProductUniverseEntry.override_ter_bps.is_not(None),
            )
            .all()
        )
        ter_bps_overrides = {
            entry.product_id: int(entry.override_ter_bps) for entry in override_entries
        }
    holding_values: dict[str, int | None] = {
        position_id: (int(h.market_value_rappen) if h.market_value_rappen is not None else None)
        for position_id, h in latest_holding.items()
        if h is not None and h.deleted_at is None
    }
    # N-856-3 / N-856-9: Bestaende frueherer Laeufe, deren Produkt dieser
    # Lauf nicht mehr enthaelt, werden verkauft und gehoeren in den Umschlag
    # -- unabhaengig davon, ob der Lauf selbst Bestaende traegt (N-856-9).
    uncarried_holdings: list[dict[str, Any]] = []
    run_products = {product.id for _, product in rows}
    latest_by_product: dict[str, Any] = {}
    for _created, holding in sorted(
        earlier_holdings, key=lambda item: (item[0], str(item[1].updated_at or "")), reverse=True,
    ):
        latest_by_product.setdefault(holding.product_id, holding)
    for product_id, holding in sorted(latest_by_product.items()):
        if product_id in run_products or holding.deleted_at is not None:
            continue
        if int(holding.units_milli or 0) <= 0 and int(holding.market_value_rappen or 0) <= 0:
            continue
        uncarried_holdings.append({
            "value_rappen": (
                int(holding.market_value_rappen)
                if holding.market_value_rappen is not None and int(holding.market_value_rappen) > 0
                else None
            ),
        })
    positions = [
        {
            "holding_present": position.id in holding_values,
            "holding_value_rappen": holding_values.get(position.id),
            "amount_rappen": _position_amount_rappen(position),
            "weight_bps": int(getattr(position, "target_weight_bps", 0) or 0),
            "ter_bps": (
                ter_bps_overrides[product.id]
                if product.id in ter_bps_overrides
                else (
                    int(product.ter_bps)
                    if getattr(product, "ter_bps", None) is not None
                    else None
                )
            ),
        }
        for position, product in rows
    ]
    # AUDIT-2026-11 P1 (L1): Retrozession am Produkt -- eigene Komponente,
    # siehe Abschnitt "AUDIT-2026-11 P1" am Dateiende.
    product_retrocessions = [
        {
            "product_id": product.id,
            "product_name": product.product_name,
            "isin": getattr(product, "isin", None),
            "provider": getattr(product, "provider", None),
            "amount_rappen": int(
                getattr(position, "target_amount_rappen", 0)
                or getattr(position, "current_amount_rappen", 0)
                or 0
            ),
            "retrocession_bps": getattr(product, "retrocession_bps", None),
            "retrocession_source": getattr(product, "retrocession_source", None),
        }
        for position, product in rows
    ]

    target_allocation = None
    target_allocation_id = getattr(latest_run, "target_allocation_id", None)
    if target_allocation_id:
        # COST-BASIS-001 (CERT-COST-CONFLICT-001): dieser Lookup war an NICHTS
        # gebunden -- nicht an das Mandat, nicht an deleted_at. Gemessen mit
        # einem Lauf von Mandat A, der auf die Allokation von Mandat B zeigt:
        #
        #     advisory_wealth_rappen = 999'900'000  (= CHF 9'999'000 aus B)
        #     waehrend Mandat A CHF 100'000 haelt
        #
        # Zwei Folgen gleichzeitig: die Vermoegenszahl eines ANDEREN Kunden
        # floss in dieses Kundendokument, und die Kostenquote wurde gegen
        # CHF 10 Mio statt CHF 100'000 gerechnet -- um Faktor 100 zu niedrig,
        # in einem FIDLEG-pflichtigen Ausweis (Art. 8/9 FIDLEG).
        target_allocation = (
            db.query(TargetAllocation)
            .filter(
                TargetAllocation.id == target_allocation_id,
                TargetAllocation.mandate_id == mandate.id,
                TargetAllocation.deleted_at.is_(None),
            )
            .first()
        )
        if target_allocation is None:
            # Der Lauf NENNT eine Allokation, aber sie gehoert nicht zu
            # diesem Mandat (oder ist geloescht/weg). Hier NICHT auf die
            # aktuelle Allokation zurueckfallen: der Lauf hat seine Basis
            # eingefroren, und wenn die nicht auffindbar ist, ist die Basis
            # dieses Ausweises unbekannt. Eine andere einzusetzen waere
            # dieselbe stille Substitution, nur innerhalb des Mandats.
            #
            # Fail-closed, Hausmuster wie an den uebrigen Unvollstaendigkeits-
            # Stellen dieser Funktion.
            return _pending_payload(
                "Der Empfehlungslauf verweist auf eine Zielallokation, die "
                "nicht zu diesem Mandat gehoert oder nicht mehr existiert. "
                "Die Vermoegensbasis des Kostenausweises ist damit "
                "unbestimmt -- Strategie neu berechnen.",
                currency=currency,
            )
    if target_allocation is None:
        target_allocation = (
            db.query(TargetAllocation)
            .filter(
                TargetAllocation.mandate_id == mandate.id,
                TargetAllocation.is_current == 1,
                TargetAllocation.deleted_at.is_(None),
            )
            .order_by(TargetAllocation.created_at.desc())
            .first()
        )

    advisory_wealth = int(
        getattr(target_allocation, "advisory_wealth_at_generation_rappen", 0)
        or 0
    )
    # 2026-07-27 (Retrozessions-Feature): offengelegte, nicht-geloeschte
    # Interessenkonflikte mit einer bezifferten Retrozession fliessen in den
    # Kostenausweis ein (Offenlegungspflicht, siehe calculate_cost_disclosure).
    disclosure_rows = (
        db.query(ConflictOfInterestDisclosure)
        .filter(
            ConflictOfInterestDisclosure.mandate_id == mandate.id,
            ConflictOfInterestDisclosure.deleted_at.is_(None),
            ConflictOfInterestDisclosure.inducement_amount_rappen.isnot(None),
        )
        .all()
    )
    # INDUCEMENT-EVIDENCE-001: die Nachweisfelder MUESSEN mitgereicht werden.
    # Vorher endete die Projektion bei `reimbursed_to_client`, womit
    # `calculate_cost_disclosure()` strukturell nicht wissen konnte, ob ein
    # Verzicht belegt ist -- und ihn trotzdem behauptete. Die Ursache lag also
    # nicht im ausgebenden Zweig allein, sondern hier an der Datengrenze.
    inducements = [
        {
            "amount_rappen": int(row.inducement_amount_rappen or 0),
            "frequency": row.inducement_frequency,
            "reimbursed_to_client": bool(row.reimbursed_to_client),
            "provider": row.inducement_provider,
            "disclosed_to_client": bool(row.disclosed_to_client),
            "waiver_document_id": row.waiver_document_id,
            # N-861-1: optionale Produktbindung (sonst Anbietername).
            "product_id": getattr(row, "product_id", None),
        }
        for row in disclosure_rows
    ]
    # COST-DOMAIN-001 / COST-COMPLETENESS-001: zwei Grenzen, bewusst
    # verschieden.
    #
    # `calculate_cost_disclosure()` ist eine reine Funktion; ein
    # unverwertbarer Satz ist dort ein kaputtes ARGUMENT und wird abgelehnt
    # (gleiche Trennung wie bei der Inflationsdomaene in ADR-6: der Parser
    # haelt kaputte DATEN draussen, die Argumentpruefung einen kaputten
    # ARGUMENT-Wert).
    #
    # HIER lesen wir dagegen PERSISTIERTE Daten eines Altlaufs. Eine
    # Exception bis zum Endpunkt durchzulassen hiesse, dass ein einziger
    # kaputter Wert in `fee_assumptions_json` das FIDLEG-Pflichtdokument mit
    # HTTP 500 abreisst -- der Berater saehe eine Fehlerseite statt des
    # Grundes. Deshalb fail-closed mit Begruendung, Hausmuster
    # `_pending_payload` (is_complete bleibt False) statt Absturz.
    try:
        return calculate_cost_disclosure(
            advisory_wealth_rappen=advisory_wealth,
            positions=positions,
            fee_model=fee_model,
            transaction_cost_bps=_first_int(
                fee_model,
                ("transaction_cost_bps", "estimated_transaction_cost_bps"),
                default=DEFAULT_TRANSACTION_COST_BPS,
            ),
            inducements=inducements,
            uncarried_holdings=uncarried_holdings,
            product_retrocessions=product_retrocessions,
            source_run_id=str(latest_run.id),
        source_run_status=str(getattr(latest_run, "result_status", "") or ""),
            as_of=str(getattr(latest_run, "created_at", "") or ""),
            currency=currency,
        )
    except CostDisclosureDomainError as exc:
        return _pending_payload(
            f"Das Gebührenmodell der Empfehlung enthält einen unverwertbaren "
            f"Wert ({exc.location}: {exc.reason_code}). Der Kostenausweis "
            "wird nicht mit einer angenommenen Null berechnet -- Gebühren "
            "im Gebührenmodell korrigieren und Strategie neu berechnen.",
            currency=currency,
        )


def calculate_cost_disclosure(
    *,
    advisory_wealth_rappen: int,
    positions: Iterable[Mapping[str, Any]],
    fee_model: Mapping[str, Any] | str | None,
    transaction_cost_bps: int = DEFAULT_TRANSACTION_COST_BPS,
    inducements: Iterable[Mapping[str, Any]] | None = None,
    uncarried_holdings: Iterable[Mapping[str, Any]] | None = None,
    product_retrocessions: Iterable[Mapping[str, Any]] | None = None,
    source_run_id: str | None = None,
    source_run_status: str | None = None,
    as_of: str | None = None,
    currency: str = "CHF",
) -> dict[str, Any]:
    """Calculate one-time, annual and first-year cost totals.

    Product TER is calculated on the invested product volume. Service fees are
    calculated on advisory wealth. Totals are expressed as amounts in
    `currency` (Mega-Audit 2026-08-04: vorher hartcodiert "CHF", unabhaengig
    von mandate.base_currency -- eine EUR-/USD-Mandats-Anzeige zeigte den
    korrekten Betrag mit falscher Waehrungs-Beschriftung) and as equivalent
    basis points of advisory wealth (bps sind waehrungsunabhaengig).
    """
    currency = str(currency or "CHF").upper().strip() or "CHF"
    fee_data = _parse_fee_model(fee_model)
    clean_positions = [
        {
            "amount_rappen": max(0, _safe_int(item.get("amount_rappen"))),
            "weight_bps": max(0, _safe_int(item.get("weight_bps"))),
            "ter_bps": _optional_non_negative_int(item.get("ter_bps")),
            "holding_present": bool(item.get("holding_present")),
            "holding_value_rappen": max(0, _safe_int(item.get("holding_value_rappen"))),
        }
        for item in positions
    ]
    invested_amount = sum(item["amount_rappen"] for item in clean_positions)
    # PO-17 (Audit 2026-11): Transaktionskosten fallen auf das GEHANDELTE
    # Volumen an. Ist fuer mindestens eine Position ein Bestand erfasst, ist
    # die Basis der Umschlag sum(|Ziel - Bestand|); ein Bestand ohne Marktwert
    # zaehlt konservativ als 0 (voller Kauf). Ohne jeden Bestand bleibt es die
    # Erstumsetzung des ganzen Volumens.
    holdings_recorded = any(item["holding_present"] for item in clean_positions)
    traded_amount = (
        sum(abs(item["amount_rappen"] - item["holding_value_rappen"]) for item in clean_positions)
        if holdings_recorded
        else invested_amount
    )
    # N-856-3: Verkaeufe nicht uebernommener Bestaende gehoeren zum Umschlag.
    # Ist ein solcher Bestand ohne Marktwert, ist sein Verkaufsvolumen
    # unbekannt -> konservativ mindestens das ganze Volumen.
    uncarried = list(uncarried_holdings or [])
    uncarried_unvalued = any(item.get("value_rappen") is None for item in uncarried)
    uncarried_notes: list[str] = []
    if uncarried:
        # N-856-9: auch ohne Bestand im Lauf (dann Kauf des ganzen Volumens
        # plus Verkauf der alten Bestaende).
        traded_amount += sum(max(0, _safe_int(item.get("value_rappen"))) for item in uncarried)
        uncarried_notes.append(
            f"{len(uncarried)} Bestand/Bestaende aus frueheren Laeufen ist/sind nicht in die "
            "Empfehlung uebernommen; deren Verkauf ist im gehandelten Volumen enthalten."
        )
        if uncarried_unvalued:
            traded_amount = max(traded_amount, invested_amount)
            uncarried_notes.append(
                "Mindestens ein nicht uebernommener Bestand ist ohne Marktwert erfasst; "
                "die Transaktionskosten werden konservativ mindestens auf das ganze "
                "Produktvolumen gerechnet."
            )
    advisory_wealth = max(0, _safe_int(advisory_wealth_rappen))
    # FIDLEG: ist das echte Beratungsvermögen nicht erfasst, wird als Näherung das
    # investierte Produktvolumen als Gebührenbasis genutzt. Dann darf die Basis NICHT
    # als "Beratungsvermögen" etikettiert werden (irreführend, und bei nicht
    # investiertem Barvermögen wäre die Jahresgebühr sonst zu tief ausgewiesen).
    advisory_wealth_provided = advisory_wealth > 0
    advisory_basis_label = (
        "Beratungsvermögen" if advisory_wealth_provided else "Empfohlenes Produktvolumen"
    )
    if advisory_wealth <= 0:
        advisory_wealth = invested_amount
    if invested_amount <= 0 and advisory_wealth <= 0:
        return _pending_payload(
            "Keine belastbare Anlagebasis vorhanden; Kosten können noch "
            "nicht als Betrag ausgewiesen werden.",
            currency=currency,
        )

    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    configured_annual_keys: set[str] = set()
    for keys, label in _ANNUAL_RATE_KEYS:
        key, rate = _first_present_rate(fee_data, keys)
        if key is None:
            continue
        configured_annual_keys.add(key)
        items.append(_rate_item(
            key=key,
            label=label,
            category="Dienstleistungskosten",
            frequency="jährlich",
            rate_bps=rate,
            basis_rappen=advisory_wealth,
            basis_label=advisory_basis_label,
            source="Gebührenmodell der Empfehlung",
            is_estimate=False,
        ))

    service_fee_known = bool(configured_annual_keys)
    if not service_fee_known:
        warnings.append(
            "Beratungs- oder Verwaltungsgebühren sind im Gebührenmodell "
            "nicht hinterlegt und deshalb nicht im Total enthalten."
        )
    elif not advisory_wealth_provided:
        warnings.append(
            "Beratungsvermögen war nicht erfasst; die jährlichen Dienstleistungs"
            "kosten sind auf das empfohlene Produktvolumen bezogen und können bei "
            "nicht investiertem Vermögen zu tief ausfallen."
        )

    for keys, label in _ONE_TIME_RATE_KEYS:
        key, rate = _first_present_rate(fee_data, keys)
        if key is None:
            continue
        items.append(_rate_item(
            key=key,
            label=label,
            category="Einmalige Dienstleistungskosten",
            frequency="einmalig",
            rate_bps=rate,
            basis_rappen=advisory_wealth,
            basis_label=advisory_basis_label,
            source="Gebührenmodell der Empfehlung",
            is_estimate=False,
        ))

    ter_known_amount = sum(
        item["amount_rappen"]
        for item in clean_positions
        if item["ter_bps"] is not None
    )
    ter_cost_rappen = sum(
        int(round(item["amount_rappen"] * int(item["ter_bps"]) / 10000))
        for item in clean_positions
        if item["ter_bps"] is not None
    )
    ter_coverage_bps = (
        int(round(ter_known_amount / invested_amount * 10000))
        if invested_amount > 0
        else 0
    )
    if ter_known_amount > 0:
        ter_rate_bps = int(round(ter_cost_rappen / invested_amount * 10000))
        items.append({
            "key": "product_ter",
            "label": "Produktkosten (gewichtete TER)",
            "category": "Produktkosten",
            "frequency": "jährlich",
            "rate_bps": ter_rate_bps,
            "amount_rappen": ter_cost_rappen,
            "basis_rappen": invested_amount,
            "basis_label": "Empfohlenes Produktvolumen",
            "source": "TER der empfohlenen Produkte",
            "is_estimate": ter_coverage_bps < 10000,
            "included_in_total": True,
        })
    elif clean_positions and invested_amount <= 0:
        # N-858-11: Positionen ohne Volumen (Strategiebasis 0) -- es gibt
        # keine Produkt- und Transaktionskosten; nicht "TER fehlt" melden.
        warnings.append(ZERO_STRATEGY_BASE_COST_NOTE)
    else:
        warnings.append(
            "Produktkosten (TER) sind für die empfohlenen Produkte nicht "
            "hinterlegt und deshalb nicht im Total enthalten."
        )
    if 0 < ter_coverage_bps < 10000:
        warnings.append(
            "Die TER-Abdeckung ist unvollständig; ausgewiesen werden nur "
            "die bekannten Produktkosten."
        )

    # COST-DOMAIN-001: auch der direkt uebergebene Transaktionskostensatz.
    # Er kommt bei `build_cost_disclosure()` aus dem Gebuehrenmodell, kann
    # aber von jedem Aufrufer gesetzt werden -- dieselbe Pruefung an der
    # Argumentgrenze.
    transaction_rate = _require_rate_bps(
        transaction_cost_bps, location="transaction_cost_bps"
    )
    warnings.extend(uncarried_notes if transaction_rate > 0 else [])
    turnover_mode = holdings_recorded or bool(uncarried)  # N-856-9
    if turnover_mode and transaction_rate > 0 and traded_amount > 0:
        items.append(_rate_item(
            key="initial_transaction_costs",
            label="Transaktionskosten Umsetzung (Umschlag)",
            category="Erwerbs-/Transaktionskosten",
            frequency="einmalig",
            rate_bps=transaction_rate,
            basis_rappen=traded_amount,
            basis_label="Gehandeltes Volumen (Käufe und Verkäufe gegenüber erfasstem Bestand)",
            source="Konservative Ex-ante-Annahme",
            is_estimate=True,
        ))
        warnings.append(
            "Transaktionskosten sind eine Ex-ante-Schätzung auf das gehandelte "
            "Volumen (Umschlag gegenüber dem erfassten Bestand); tatsächliche "
            "Spreads, Courtagen und Börsenabgaben können abweichen."
        )
    elif turnover_mode and transaction_rate > 0:
        warnings.append(
            "Keine Transaktionskosten ausgewiesen: der erfasste Bestand entspricht "
            "bereits der Empfehlung (kein Umschlag)."
        )
    elif invested_amount > 0 and transaction_rate > 0:
        items.append(_rate_item(
            key="initial_transaction_costs",
            label="Transaktionskosten Erstumsetzung",
            category="Erwerbs-/Transaktionskosten",
            frequency="einmalig",
            rate_bps=transaction_rate,
            basis_rappen=invested_amount,
            basis_label="Empfohlenes Produktvolumen",
            source="Konservative Ex-ante-Annahme",
            is_estimate=True,
        ))
        warnings.append(
            "Transaktionskosten sind eine Ex-ante-Schätzung für die "
            "Erstumsetzung des ganzen Produktvolumens (kein Bestand erfasst); "
            "tatsächliche Spreads, Courtagen und Börsenabgaben können abweichen."
        )

    # 2026-07-27 (Retrozessions-Feature): FIDLEG Art. 25/26 + BGE 132 III 460
    # verlangen Offenlegung von Vergütungen Dritter UNABHAENGIG davon, ob sie
    # an den Kunden zurückerstattet werden -- deshalb wird JEDE Retrozession
    # als Cost-Item ausgewiesen. Nur die tatsächliche RUECKERSTATTUNG (der
    # Kunde erhält netto weniger Kosten) fliesst als negativer Betrag ins
    # Total ein; eine vom Berater EINBEHALTENE Retrozession ist bereits Teil
    # der oben ausgewiesenen Produkt-/Dienstleistungskosten (kein separater
    # Kostenpunkt) und wird deshalb NICHT zusätzlich addiert (Doppelzähl-
    # Vermeidung), aber transparent als Warnung genannt.
    for inducement in (inducements or []):
        amount = _safe_int(inducement.get("amount_rappen"))
        if amount <= 0:
            continue
        frequency_raw = str(inducement.get("frequency") or "").strip().lower()
        # Mega-Audit (2026-08-04): ein LEERER Frequenz-Wert wurde bisher als
        # "jährlich" gewertet -- eine unbelegte Annahme, die die zurück-
        # erstattete Vergütung vom Total abzog (mindert die ausgewiesenen
        # Kosten), obwohl der Berater nie bestätigt hat, dass sie tatsächlich
        # jährlich wiederkehrt. Verstösst gegen das eigene "nie stillschweigend
        # Null/günstig"-Prinzip (Moduldocstring). Fix: nur eine EXPLIZIT als
        # jährlich erfasste Frequenz zählt als jährlich; ein leerer Wert wird
        # wie eine unbekannte Frequenz behandelt (konservativ NICHT ins Total
        # gerechnet, mit Warnung statt stillschweigender Annahme).
        frequency_unspecified = frequency_raw == ""
        is_annual = frequency_raw in ("jährlich", "jaehrlich", "annual", "annually", "yearly")
        frequency_display = "jährlich" if is_annual else (frequency_raw or "nicht erfasst")
        reimbursed = bool(inducement.get("reimbursed_to_client"))
        provider = str(inducement.get("provider") or "Produktanbieter").strip() or "Produktanbieter"
        if reimbursed:
            # TEN-COMP-003 Teil 2: ein unplausibel grosser "zurueckerstatteter" Betrag
            # wird nie stillschweigend abgezogen, unabhaengig von der Frequenz -- es
            # gibt in diesem Datenmodell (noch) keinen Zahlungsnachweis, der eine so
            # grosse Rueckerstattung belegen wuerde.
            amount_plausible = amount <= _INDUCEMENT_SANITY_CEILING_RAPPEN
            items.append({
                "key": "retrocession_reimbursed",
                "label": f"Rückerstattung Vergütung von Dritten ({provider})",
                "category": "Vergütungen von Dritten",
                "frequency": frequency_display,
                "rate_bps": None,
                "amount_rappen": -amount,
                "basis_rappen": advisory_wealth,
                "basis_label": advisory_basis_label,
                "source": "Interessenkonflikt-Offenlegung (Retrozession, zurückerstattet)",
                "is_estimate": False,
                "included_in_total": is_annual and amount_plausible,
                # Eine tatsaechlich zurueckerstattete Retrozession braucht
                # keinen Verzicht -- der Herausgabeanspruch ist erfuellt.
                "requires_resolution": False,
            })
            if not amount_plausible:
                warnings.append(
                    f"Eine zurückerstattete Vergütung von Dritten ({provider}) übersteigt "
                    "den plausiblen Höchstbetrag je Position und wird konservativ NICHT im "
                    "Total verrechnet, solange sie nicht durch einen Zahlungsnachweis "
                    "belegt ist (Betrag prüfen/korrigieren)."
                )
            elif frequency_unspecified:
                warnings.append(
                    f"Eine zurückerstattete Vergütung von Dritten ({provider}) hat keine "
                    "erfasste Frequenz -- konservativ NICHT im Total verrechnet "
                    "(Frequenz beim Produkt/Retrozession ergänzen)."
                )
            elif not is_annual:
                warnings.append(
                    f"Eine zurückerstattete Vergütung von Dritten ({provider}) mit "
                    "nicht-jährlicher Frequenz ist offengelegt, aber nicht im Total verrechnet."
                )
        elif _has_documented_waiver(inducement):
            items.append({
                "key": "retrocession_disclosed",
                "label": f"Vergütung von Dritten, einbehalten ({provider})",
                "category": "Vergütungen von Dritten",
                "frequency": frequency_display,
                "rate_bps": None,
                "amount_rappen": amount,
                "basis_rappen": advisory_wealth,
                "basis_label": advisory_basis_label,
                "source": "Interessenkonflikt-Offenlegung (Retrozession, Verzicht dokumentiert)",
                "is_estimate": False,
                "included_in_total": False,
                "requires_resolution": False,
            })
            warnings.append(
                f"Vergütung von Dritten ({provider}) ist offengelegt, wird gemäss "
                "dokumentiertem Kundenverzicht aber vom Berater einbehalten und ist "
                "bereits Teil der ausgewiesenen Kosten -- nicht zusätzlich im Total."
            )
        else:
            # INDUCEMENT-EVIDENCE-001: Hier stand bisher ein bedingungsloses
            # `else`, das "Verzicht dokumentiert" auch dann ins FIDLEG-Dokument
            # schrieb, wenn nie offengelegt und nichts abgelegt wurde -- die
            # Aussage war nicht bloss unbelegt, sondern das GEGENTEIL der
            # Datenlage, und zwar genau in der Konstellation, die
            # BGE 132 III 460 ohne gueltigen Verzicht unzulaessig macht.
            #
            # Der Posten verschwindet NICHT: FIDLEG Art. 26 verlangt die
            # Offenlegung der Verguetung, und ein stilles Weglassen waere fuer
            # den Kunden schlechter als eine ehrliche Kennzeichnung. Geaendert
            # wird, was behauptet wird.
            missing = []
            if not bool(inducement.get("disclosed_to_client")):
                missing.append("keine Offenlegung an den Kunden erfasst")
            if not str(inducement.get("waiver_document_id") or "").strip():
                missing.append("kein Verzichts-Dokument abgelegt")
            missing_text = "; ".join(missing)
            items.append({
                "key": "retrocession_retained_unwaived",
                "label": f"Vergütung von Dritten, einbehalten -- Verzicht NICHT belegt ({provider})",
                "category": "Vergütungen von Dritten",
                "frequency": frequency_display,
                "rate_bps": None,
                "amount_rappen": amount,
                "basis_rappen": advisory_wealth,
                "basis_label": advisory_basis_label,
                "source": (
                    "Interessenkonflikt-Offenlegung (Retrozession einbehalten, "
                    "Verzicht NICHT belegt -- Klärung erforderlich)"
                ),
                "is_estimate": False,
                # Der Betrag bleibt ausserhalb des Totals, aber aus einem
                # anderen Grund als beim belegten Verzicht: er steckt bereits
                # in den Produktkosten. Ihn als Minusposten zu fuehren wuerde
                # eine Rueckerstattung behaupten, die nicht stattgefunden hat;
                # ihn zu addieren waere Doppelzaehlung. Beides waere eine
                # Zahl, die es nicht gibt -- deshalb ausgewiesen und
                # gekennzeichnet, nicht verrechnet.
                "included_in_total": False,
                "requires_resolution": True,
            })
            warnings.append(
                f"Vergütung von Dritten ({provider}) wird vom Berater einbehalten, "
                f"ohne dass ein Kundenverzicht belegt ist ({missing_text}). "
                "Nach BGE 132 III 460 / Art. 400 OR steht sie damit dem Kunden zu; "
                "der Betrag ist offengelegt, aber NICHT im Total verrechnet (er ist "
                "bereits Teil der Produktkosten) und es wird kein Verzicht behauptet. "
                "Zu klären: Verzicht offenlegen und dokumentieren ODER Betrag "
                "zurückerstatten."
            )

    # AUDIT-2026-11 P1 (L1): produktgebundene Retrozessions-Offenlegung
    # (Art. 26 FIDLEG). Abgegrenzte Komponente (Abschnitt am Dateiende); fuehrt die manuelle
    # Mandatserfassung oben mit den Produkt-Stammdaten zusammen, ohne eine
    # Retrozession doppelt auszuweisen. Nie im Total (Teil der TER).
    retro_items, retro_warnings, retro_summary = apply_product_retrocessions(
        products=None if product_retrocessions is None else list(product_retrocessions),
        inducements=inducements,
        has_documented_waiver=_has_documented_waiver,
        currency=currency,
    )
    items.extend(retro_items)
    warnings.extend(retro_warnings)

    one_time_amount = sum(
        int(item.get("amount_rappen") or 0)
        for item in items
        if item.get("frequency") == "einmalig" and item.get("included_in_total", True)
    )
    annual_amount = sum(
        int(item.get("amount_rappen") or 0)
        for item in items
        if item.get("frequency") == "jährlich" and item.get("included_in_total", True)
    )
    first_year_amount = one_time_amount + annual_amount

    return {
        "data_pending": False,
        "currency": currency,
        "as_of": as_of,
        "source_run_id": source_run_id,
        # COST-CONTEXT-001a: welchen STATUS der Quelllauf hatte. Ein
        # Kostenausweis auf Entwurfsbasis ist legitim (der Berater will
        # die Kosten vor der Freigabe sehen), aber er ist vorlaeufig --
        # ohne dieses Feld ist er von einem freigegebenen nicht zu
        # unterscheiden.
        "source_run_status": source_run_status,
        # COST-CONTEXT-001b: Defaults. `build_cost_disclosure()` setzt sie
        # je nachdem, ob ein eingefrorener Nachweis vorliegt. Sie stehen
        # HIER, damit jede Payload-Form dieselben Schluessel hat -- ein
        # Konsument soll nicht raten muessen, ob das Feld fehlt oder False
        # ist.
        "evidence_frozen": False,
        "content_hash": None,
        "frozen_at": None,
        "fidleg_basis": "Art. 8/9 FIDLEG; Art. 8/14 FIDLEV",
        "advisory_wealth_rappen": advisory_wealth,
        "invested_amount_rappen": invested_amount,
        "product_cost_coverage_bps": ter_coverage_bps,
        "cost_items": items,
        "totals": {
            "one_time_rappen": one_time_amount,
            "one_time_bps": _equivalent_bps(one_time_amount, advisory_wealth),
            "annual_rappen": annual_amount,
            "annual_bps": _equivalent_bps(annual_amount, advisory_wealth),
            "first_year_rappen": first_year_amount,
            "first_year_bps": _equivalent_bps(first_year_amount, advisory_wealth),
        },
        # N-861-2: mit Produktbezug ist der Ausweis nur vollstaendig, wenn
        # jede Retrozession bekannt und geregelt ist (Art. 26 FIDLEG).
        "is_complete": (
            service_fee_known
            and ter_coverage_bps == 10000
            and (retro_summary is None or bool(retro_summary.get("complete")))
        ),
        "has_estimates": any(bool(item.get("is_estimate")) for item in items),
        "warnings": warnings,
        **({"product_retrocessions": retro_summary} if retro_summary is not None else {}),
    }


def _rate_item(
    *,
    key: str,
    label: str,
    category: str,
    frequency: str,
    rate_bps: int,
    basis_rappen: int,
    basis_label: str,
    source: str,
    is_estimate: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "category": category,
        "frequency": frequency,
        "rate_bps": rate_bps,
        "amount_rappen": int(round(basis_rappen * rate_bps / 10000)),
        "basis_rappen": basis_rappen,
        "basis_label": basis_label,
        "source": source,
        "is_estimate": is_estimate,
        "included_in_total": True,
    }


def _parse_fee_model(raw: Mapping[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _first_present_rate(
    fee_model: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, int]:
    for key in keys:
        if key not in fee_model or fee_model.get(key) is None:
            continue
        # COST-DOMAIN-001: typisiert statt geklemmt. Ein ABWESENDER Schluessel
        # bleibt ein eigener, bereits behandelter Fall (service_fee_known =
        # False mit Warnung) -- nur ein VORHANDENER, aber unverwertbarer Wert
        # wird abgelehnt.
        return key, _require_rate_bps(
            fee_model.get(key), location=f"fee_model[{key!r}]"
        )
    return None, 0


def _first_int(
    fee_model: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: int,
) -> int:
    for key in keys:
        if key in fee_model and fee_model.get(key) is not None:
            # COST-DOMAIN-001: gleiche Begruendung wie _first_present_rate.
            # Der `default` greift nur bei ABWESENHEIT, nie als Ersatz fuer
            # einen kaputten Wert.
            return _require_rate_bps(
                fee_model.get(key), location=f"fee_model[{key!r}]"
            )
    return default


def _equivalent_bps(amount_rappen: int, basis_rappen: int) -> int | None:
    if basis_rappen <= 0:
        return None
    return int(round(amount_rappen / basis_rappen * 10000))


def _optional_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    return max(0, _safe_int(value))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pending_payload(note: str, *, currency: str = "CHF") -> dict[str, Any]:
    return {
        "data_pending": True,
        "currency": str(currency or "CHF").upper().strip() or "CHF",
        "as_of": None,
        "source_run_id": None,
        "source_run_status": None,
        "evidence_frozen": False,
        "content_hash": None,
        "frozen_at": None,
        "fidleg_basis": "Art. 8/9 FIDLEG; Art. 8/14 FIDLEV",
        "advisory_wealth_rappen": 0,
        "invested_amount_rappen": 0,
        "product_cost_coverage_bps": 0,
        "cost_items": [],
        "totals": {
            "one_time_rappen": 0,
            "one_time_bps": None,
            "annual_rappen": 0,
            "annual_bps": None,
            "first_year_rappen": 0,
            "first_year_bps": None,
        },
        "is_complete": False,
        "has_estimates": False,
        "warnings": [note],
        "evidence_status": EVIDENCE_STATUS_PENDING,
        "evidence_error": None,
    }


def blocked_cost_disclosure_payload(
    reason: str,
    *,
    currency: str = "CHF",
    source_run_id: str | None = None,
    source_run_status: str | None = None,
) -> dict[str, Any]:
    """Payload fuer einen vorhandenen, aber ungueltigen Kostennachweis.

    COST-SNAPSHOT-BINDING-001: nie Zahlen (weder die ungueltigen noch live
    neu gerechnete), sondern ein ausgewiesener Fehlerzustand. Lauf-ID und
    -Status bleiben sichtbar, damit der Berater weiss, WELCHER Lauf neu zu
    finalisieren ist.
    """
    payload = _pending_payload(
        "Der eingefrorene Kostenausweis dieses Empfehlungslaufs ist "
        f"nicht verwertbar ({reason}). Die dem Kunden "
        "ausgehändigten Zahlen lassen sich damit nicht belegen -- "
        "Strategie neu berechnen und finalisieren.",
        currency=currency,
    )
    payload["source_run_id"] = source_run_id
    payload["source_run_status"] = source_run_status
    payload["evidence_status"] = EVIDENCE_STATUS_BLOCKED
    payload["evidence_error"] = reason
    payload["audit_degraded"] = True
    return payload


# ---------------------------------------------------------------------------
# COST-CONTEXT-001b / COST-EVIDENCE-001: eingefrorener Nachweis
# ---------------------------------------------------------------------------
# `build_cost_disclosure()` rechnete bei jedem Aufruf neu und las dabei live
# `Product.ter_bps`. Gemessen: eine spaetere TER-Korrektur von 50 auf 500 bps
# -- ohne jeden neuen Lauf -- aenderte die Totale eines bereits FINALISIERTEN
# Laufs rueckwirkend. Ein nach FIDLEG Art. 8/9 ausgehaendigtes Dokument war
# damit nicht reproduzierbar: wer es spaeter nachrechnet, bekommt andere
# Zahlen als der Kunde gesehen hat.

def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


# COST-SNAPSHOT-BINDING-001 (2026-10-21): V2 hasht den GANZEN Umschlag
# (Version, Lauf-, Mandats- und TA-Bindung, frozen_at, Payload) statt nur den
# inneren Payload. V1 (nur Payload gehasht) bleibt LESBAR, weil seit
# 2026-10-13 finalisierte Laeufe so eingefroren wurden -- aber auch V1 muss
# die Lauf-Bindung bestehen. Jede andere Version ist unbekannte Semantik und
# wird fail-closed verworfen, nie "wie V1" gelesen.
COST_SNAPSHOT_SCHEMA_VERSION = 2
COST_SNAPSHOT_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})

# Begruendungscodes fuer einen unbrauchbaren Snapshot -- maschinenlesbar,
# damit ein Aufrufer nicht auf Meldungstexte matchen muss. Werte stabil
# (Codex-Review 2026-10-14, Pflicht-Reason-Codes).
REASON_SNAPSHOT_MALFORMED = "snapshot_malformed"
REASON_SNAPSHOT_HASH_MISMATCH = "snapshot_hash_mismatch"
REASON_SNAPSHOT_SCHEMA_UNSUPPORTED = "snapshot_schema_unsupported"
REASON_SNAPSHOT_RUN_MISMATCH = "snapshot_run_mismatch"
REASON_SNAPSHOT_CONTEXT_MISMATCH = "snapshot_context_mismatch"

# Diskriminierter Evidence-Status jedes Kostenausweis-Payloads.
EVIDENCE_STATUS_CERTIFIED = "certified"          # eingefroren + verifiziert
EVIDENCE_STATUS_PREVIEW = "preview"              # Entwurf, live gerechnet
EVIDENCE_STATUS_LEGACY_UNVERIFIED = "legacy_unverified"  # Final ohne Snapshot
EVIDENCE_STATUS_BLOCKED = "blocked"              # Snapshot da, aber ungueltig
EVIDENCE_STATUS_PENDING = "pending"              # keine Empfehlung/Basis


def cost_disclosure_content_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 ueber den kanonisierten Kostenausweis-Payload.

    Gleiches Verfahren und gleiche Kanonisierung wie
    `services/document_archive.py::content_hash_for()` (`json.dumps` mit
    `sort_keys=True, default=str`, dann sha256). Jene Funktion nimmt eine
    Dataclass; hier ist der Payload ein Dict, deshalb eine eigene -- aber
    bewusst NICHT ein eigenes Verfahren.
    """
    canonical = json.dumps(dict(payload), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freeze_cost_disclosure_for_run(db: Session, mandate: Any, run: Any) -> str | None:
    """Den Kostenausweis dieses Laufs berechnen und als Nachweis einfrieren.

    Rueckgabe ist der JSON-String fuer
    `RecommendationRun.cost_disclosure_snapshot_json`, oder None, wenn kein
    verwertbarer Ausweis entsteht.

    Bewusst `build_cost_disclosure_for_run()` und nicht
    `build_cost_disclosure()`: der Lauf steht hier FEST. Die Auswahl erneut
    laufen zu lassen koennte einen anderen treffen -- und genau das
    Einfrieren des falschen Laufs waere der Fehler, den dieser Nachweis
    verhindern soll.

    Fail-soft, mit Absicht: liefert die Berechnung keinen Ausweis (etwa weil
    Positionen fehlen) oder wirft sie, wird NICHTS eingefroren und die
    Finalisierung laeuft weiter. Ein fehlender Snapshot ist ein offengelegter
    Zustand (`evidence_frozen=False`) -- die Finalisierung daran scheitern zu
    lassen waere eine Blockade, die dieser Befund nicht verlangt.
    """
    try:
        payload = build_cost_disclosure_for_run(db, mandate, run)
    except Exception:  # noqa: BLE001 -- siehe Docstring: fail-soft
        return None
    if payload.get("data_pending"):
        return None
    envelope = {
        "schema_version": COST_SNAPSHOT_SCHEMA_VERSION,
        "frozen_at": _utc_now_iso(),
        "recommendation_run_id": str(getattr(run, "id", "") or ""),
        "mandate_id": _opt_str(getattr(run, "mandate_id", None)),
        "target_allocation_id": _opt_str(getattr(run, "target_allocation_id", None)),
        "payload": payload,
    }
    envelope["content_hash"] = _envelope_hash_v2(envelope)
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True)


def _opt_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _envelope_hash_v2(envelope: Mapping[str, Any]) -> str:
    """V2-Hash: der ganze Umschlag ausser dem Hashfeld selbst.

    Damit sind Lauf-/Mandats-/TA-Bindung, Version und `frozen_at` nicht mehr
    ohne Hashbruch aenderbar (Codex-Befund 2: nur der innere Payload war
    gehasht).
    """
    return cost_disclosure_content_hash(
        {key: value for key, value in envelope.items() if key != "content_hash"}
    )


def load_frozen_cost_disclosure(run: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Den eingefrorenen Nachweis lesen und seine Integritaet pruefen.

    Rueckgabe `(payload, reason_code)`:

        (payload, None)  -- gueltiger Nachweis
        (None, None)     -- kein Snapshot vorhanden (Entwurf, oder Altlauf
                            aus der Zeit vor der Spalte)
        (None, code)     -- Snapshot vorhanden, aber unbrauchbar

    Der Hash wird NACHGERECHNET, nicht bloss mitgelesen. Ein Nachweis, dessen
    Inhalt nicht zu seinem Hash passt, ist kein Nachweis -- ihn trotzdem
    auszuliefern waere schlimmer als ihn zu verwerfen, weil das Dokument dann
    eine Reproduzierbarkeit behauptet, die es nicht hat.

    COST-SNAPSHOT-BINDING-001 (2026-10-21), Pruefreihenfolge:

    1. Struktur (Payload-Dict + Hash-String) -> ``snapshot_malformed``
    2. bekannte Schema-Version (1 oder 2, echtes int) ->
       ``snapshot_schema_unsupported``. Eine unbekannte Version wird NIE
       wie V1 interpretiert.
    3. Lauf-Bindung: Umschlag-Run-ID UND Payload-``source_run_id`` muessen
       beide gleich ``run.id`` sein -> ``snapshot_run_mismatch``. Ein
       kryptographisch korrekter Snapshot von Lauf A ist kein Nachweis fuer
       Lauf B.
    4. (V2) Mandats-/TA-Bindung gegen den Lauf -> ``snapshot_context_mismatch``
    5. Hash (V1: Payload, V2: ganzer Umschlag) -> ``snapshot_hash_mismatch``
    """
    raw = getattr(run, "cost_disclosure_snapshot_json", None)
    if not raw:
        return None, None
    try:
        envelope = json.loads(raw)
    except (TypeError, ValueError):
        return None, REASON_SNAPSHOT_MALFORMED
    if not isinstance(envelope, dict):
        return None, REASON_SNAPSHOT_MALFORMED
    payload = envelope.get("payload")
    stored_hash = envelope.get("content_hash")
    if not isinstance(payload, dict) or not isinstance(stored_hash, str):
        return None, REASON_SNAPSHOT_MALFORMED

    version = envelope.get("schema_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in COST_SNAPSHOT_SUPPORTED_SCHEMA_VERSIONS
    ):
        return None, REASON_SNAPSHOT_SCHEMA_UNSUPPORTED

    run_id = _opt_str(getattr(run, "id", None))
    if (
        run_id is None
        or _opt_str(envelope.get("recommendation_run_id")) != run_id
        or _opt_str(payload.get("source_run_id")) != run_id
    ):
        return None, REASON_SNAPSHOT_RUN_MISMATCH

    if version >= 2:
        for key in ("mandate_id", "target_allocation_id"):
            bound = _opt_str(envelope.get(key))
            actual = _opt_str(getattr(run, key, None))
            if bound != actual:
                return None, REASON_SNAPSHOT_CONTEXT_MISMATCH
        expected_hash = _envelope_hash_v2(envelope)
    else:
        expected_hash = cost_disclosure_content_hash(payload)
    if expected_hash != stored_hash:
        return None, REASON_SNAPSHOT_HASH_MISMATCH

    frozen = dict(payload)
    frozen["evidence_frozen"] = True
    frozen["evidence_status"] = EVIDENCE_STATUS_CERTIFIED
    frozen["evidence_error"] = None
    frozen["content_hash"] = stored_hash
    frozen["frozen_at"] = envelope.get("frozen_at")
    frozen["snapshot_schema_version"] = version
    return frozen, None


# ===========================================================================
# AUDIT-2026-11 P1 (L1): produktgebundene Retrozessions-Offenlegung.
# Abgegrenzter Abschnitt; calculate_cost_disclosure() ruft nur
# apply_product_retrocessions() auf. Im selben Modul statt eines eigenen,
# weil die Architektur-Ratsche keinen neuen Fan-out fuer
# services.cost_disclosure zulaesst.
#
# Produktgebundene Retrozessions-Offenlegung im Ex-ante-Kostenausweis.
#
# Audit 2026-11, Paket P1 (Luecke L1, Bericht 02/PO-12).
# Rechtsgrundlage: Art. 26 FIDLEG (Entschaedigungen Dritter), Art. 400 OR,
# BGE 132 III 460 (Herausgabepflicht), BGE 137 III 393 (Verzicht nur bei
# Kenntnis von Umfang und Berechnungsparametern).
#
# Bisher kannte der Kostenausweis Retrozessionen nur, wenn der Berater sie
# pro Mandat manuell als Interessenkonflikt erfasste (Retrozessions-Feature
# 2026-07-27). Ein empfohlenes Produkt mit Retrozession konnte deshalb ohne
# Offenlegungszeile im Kundendokument stehen. Diese Komponente bindet die
# Offenlegung an das PRODUKT:
#
# * Satz > 0  -> Offenlegungszeile mit geschaetztem Jahresbetrag (Satz x
#   investiertes Volumen des Produkts) und der Behandlung gemaess Mandat
#   (Weitergabe an den Kunden / dokumentierter Verzicht / nicht geregelt).
# * Satz NULL -> Pflichtwarnung an den Berater und Kennzeichnung im Dokument.
#   Das Produkt gilt NIE still als retrozessionsfrei.
# * Satz 0    -> ausdruecklich retrozessionsfrei (mit Quelle erfasst).
#
# Zusammenfuehrung mit der manuellen Erfassung pro Mandat (kein doppelter
# Ausweis): Eine manuelle Retrozessions-Zeile des Mandats, deren Anbieter dem
# Anbieter des Produkts entspricht (Vergleich ohne Gross-/Kleinschreibung und
# Leerraum), IST die Offenlegungszeile dieses Produkts. Ihre Behandlung
# (rueckerstattet / Verzicht belegt / nicht belegt) gilt fuer das Produkt;
# eine zweite Kostenzeile entsteht nicht. Nur ein Produkt ohne passende
# Mandatszeile bekommt eine eigene Kostenzeile -- stets AUSSERHALB des Totals
# (die Retrozession ist Teil der TER, Addieren waere Doppelzaehlung) und mit
# ``requires_resolution``, weil weder Verzicht noch Weitergabe erfasst ist.
#
# Bewusst eine eigene, abgegrenzte Komponente: ``services/cost_disclosure.py``
# ruft nur ``apply_product_retrocessions()`` auf. Die Auswahl- und
# Scoring-Logik der Engine bleibt unberuehrt.
# ===========================================================================
TREATMENT_REIMBURSED = "reimbursed"
TREATMENT_WAIVER_DOCUMENTED = "waiver_documented"
TREATMENT_UNRESOLVED = "unresolved"
TREATMENT_NOT_APPLICABLE = "not_applicable"
TREATMENT_UNKNOWN = "unknown"
TREATMENT_PARTIALLY_COVERED = "partially_covered"

TREATMENT_LABELS = {
    TREATMENT_REIMBURSED: "Weitergabe an den Kunden gemäss Mandat",
    TREATMENT_WAIVER_DOCUMENTED: "Verzicht des Kunden dokumentiert",
    TREATMENT_UNRESOLVED: "Weder Verzicht noch Weitergabe belegt – Klärung erforderlich",
    TREATMENT_NOT_APPLICABLE: "Keine Retrozession",
    TREATMENT_UNKNOWN: "Satz nicht erfasst – gilt nicht als retrozessionsfrei",
    TREATMENT_PARTIALLY_COVERED: "Verzicht/Weitergabe deckt nur einen Teil – Rest ungeregelt",
}

COST_ITEM_KEY = "retrocession_product"
DISCLOSURE_SCHEMA_VERSION = 1


def _norm_provider(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _format_amount(rappen: int, currency: str) -> str:
    whole, cents = divmod(abs(int(rappen)), 100)
    grouped = f"{whole:,}".replace(",", "'")
    sign = "-" if rappen < 0 else ""
    return f"{currency} {sign}{grouped}.{cents:02d}"


def _rate(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        rate = int(value)
    except (TypeError, ValueError):
        return None
    return rate if rate >= 0 else None


_ANNUAL_FREQUENCIES = ("jährlich", "jaehrlich", "annual", "annually", "yearly")
# N-861-7 (Entscheid Owner-Vertretung, BGE 137 III 393): KEINE Toleranz.
# Ein Verzicht wirkt nur im aufgeklaerten Umfang; eine geschaetzte
# Produkt-Retrozession ist nur gedeckt, wenn der geregelte Betrag sie voll
# erreicht. Wer eine Unschaerfe abbilden will, klaert im Mandat ausdruecklich
# einen Hoechstbetrag auf (dieser ist dann der Mandatsbetrag).
COVERAGE_TOLERANCE = 1.0


def _int_or_zero(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _mandate_groups(inducements, has_documented_waiver) -> dict[tuple[str, str], dict[str, Any]]:
    """N-861-1 (c): Mandatszeilen je Zuordnungsschluessel SUMMIEREN statt
    still auf die erste zu reduzieren. Schluessel: ('product', product_id),
    wenn die Zeile an ein Produkt gebunden ist, sonst ('provider', Anbieter).

    * ``disclosed`` -- Summe der ausdruecklich JAEHRLICH offengelegten
      Betraege (egal wie geregelt). N-861-8: ein einmalig oder ohne
      Frequenz offengelegter Betrag klaert eine laufende Retrozession nicht
      auf und landet separat in ``disclosed_other``.
    * ``resolved``  -- davon geregelt: zurueckerstattet oder Verzicht belegt
      (ebenfalls nur jaehrlich, weil die Produkt-Schaetzung ein Jahresbetrag
      ist).
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in inducements or []:
        amount = _int_or_zero(entry.get("amount_rappen"))
        if amount <= 0:
            continue
        product_id = str(entry.get("product_id") or "").strip()
        provider = _norm_provider(entry.get("provider"))
        if product_id:
            key = ("product", product_id)
        elif provider:
            key = ("provider", provider)
        else:
            continue
        group = groups.setdefault(key, {
            "disclosed": 0, "disclosed_other": 0, "reimbursed": 0, "waived": 0, "entries": 0,
        })
        group["entries"] += 1
        if str(entry.get("frequency") or "").strip().lower() not in _ANNUAL_FREQUENCIES:
            group["disclosed_other"] += amount
            continue
        group["disclosed"] += amount
        if bool(entry.get("reimbursed_to_client")):
            group["reimbursed"] += amount
        elif has_documented_waiver(entry):
            group["waived"] += amount
    for group in groups.values():
        group["resolved"] = group["reimbursed"] + group["waived"]
    return groups


def _within(estimate: int, covered: int) -> bool:
    return estimate <= covered * COVERAGE_TOLERANCE


def _share(total: int, part: int, whole: int) -> int:
    if whole <= 0:
        return 0
    return int(round(total * part / whole))


def build_product_retrocession_lines(
    products: Iterable[Mapping[str, Any]],
    inducements: Iterable[Mapping[str, Any]] | None,
    *,
    has_documented_waiver,
) -> list[dict[str, Any]]:
    """Eine Zeile je empfohlenem Produkt (Positionen desselben Produkts
    zusammengefasst), stabil nach Produktname sortiert.

    N-861-1 (BGE 137 III 393: ein Verzicht wirkt nur im Umfang der
    Aufklaerung): je Zuordnungsgruppe wird die SUMME der geschaetzten
    Produkt-Retrozessionen mit dem im Mandat offengelegten bzw. geregelten
    Betrag verglichen (Toleranz COVERAGE_TOLERANCE). Der nicht gedeckte Rest
    gilt als ungeregelt; ein nicht offengelegter Teil bekommt eine eigene
    Kostenzeile. Zuordnung: Produktbindung (product_id) vor Anbietername.
    """
    groups = _mandate_groups(inducements, has_documented_waiver)

    merged: dict[str, dict[str, Any]] = {}
    for item in products:
        product_id = str(item.get("product_id") or "")
        line = merged.get(product_id)
        amount = max(0, int(item.get("amount_rappen") or 0))
        if line is None:
            merged[product_id] = {
                "product_id": product_id or None,
                "product_name": str(item.get("product_name") or "Produkt"),
                "isin": item.get("isin") or None,
                "provider": item.get("provider") or None,
                "amount_rappen": amount,
                "rate_bps": _rate(item.get("retrocession_bps")),
                "source": item.get("retrocession_source") or None,
            }
        else:
            line["amount_rappen"] += amount

    def group_key(line):
        if line["product_id"] and ("product", line["product_id"]) in groups:
            return ("product", line["product_id"])
        provider = _norm_provider(line["provider"])
        if provider and ("provider", provider) in groups:
            return ("provider", provider)
        return None

    keys: dict[str, Any] = {}
    group_estimates: dict[tuple[str, str], int] = {}
    for pid, line in merged.items():
        rate = line["rate_bps"]
        line["estimated_annual_rappen"] = (
            None if rate is None else int(round(line["amount_rappen"] * rate / 10000))
        )
        key = group_key(line) if rate else None
        keys[pid] = key
        if key is not None:
            group_estimates[key] = group_estimates.get(key, 0) + line["estimated_annual_rappen"]

    lines: list[dict[str, Any]] = []
    for pid, line in merged.items():
        rate = line["rate_bps"]
        key = keys[pid]
        estimate = line["estimated_annual_rappen"]
        disclosed_share = resolved_share = other_share = 0
        if rate is None:
            status, treatment = "unknown", TREATMENT_UNKNOWN
        elif rate == 0:
            status, treatment = "none", TREATMENT_NOT_APPLICABLE
        else:
            status = "present"
            if key is None:
                treatment = TREATMENT_UNRESOLVED
            else:
                group = groups[key]
                group_estimate = group_estimates[key]
                # N-861-7: immer der tatsaechliche (anteilige) Mandatsbetrag,
                # nie auf die Schaetzung hochgesetzt.
                disclosed_share = _share(group["disclosed"], estimate, group_estimate)
                resolved_share = _share(group["resolved"], estimate, group_estimate)
                other_share = _share(group["disclosed_other"], estimate, group_estimate)
                if group["resolved"] > 0 and _within(group_estimate, group["resolved"]):
                    treatment = (
                        TREATMENT_REIMBURSED
                        if group["reimbursed"] >= group["waived"]
                        else TREATMENT_WAIVER_DOCUMENTED
                    )
                elif group["resolved"] > 0:
                    treatment = TREATMENT_PARTIALLY_COVERED
                else:
                    treatment = TREATMENT_UNRESOLVED
        present = status == "present"
        group_covers = key is not None and _within(group_estimates[key], groups[key]["resolved"])
        group_discloses = key is not None and _within(group_estimates[key], groups[key]["disclosed"])
        # Rundung der anteiligen Verteilung darf keinen Scheinrest erzeugen,
        # wenn die Gruppe als Ganzes gedeckt ist.
        unresolved = (0 if group_covers else max(0, estimate - resolved_share)) if present else None
        undisclosed = (0 if group_discloses else max(0, estimate - disclosed_share)) if present else None
        lines.append({
            **line,
            "status": status,
            "treatment": treatment,
            "treatment_label": TREATMENT_LABELS[treatment],
            # True = eine manuelle Retrozessions-Zeile des Mandats (Produkt-
            # bindung oder gleicher Anbieter) ist die Offenlegungszeile.
            "covered_by_mandate_entry": key is not None,
            "mandate_disclosed_rappen": disclosed_share if key is not None else None,
            "mandate_resolved_rappen": resolved_share if key is not None else None,
            # N-861-8: einmalig/ohne Frequenz offengelegt -- deckt die
            # jaehrliche Retrozession nicht (nie als "aufgeklaert" beschriftet).
            "mandate_disclosed_other_rappen": other_share if key is not None and other_share else None,
            "unresolved_rappen": unresolved,
            "undisclosed_rappen": undisclosed,
            "requires_resolution": present and unresolved > 0,
            "_group_key": key,
        })
    lines.sort(key=lambda row: (row["product_name"].casefold(), str(row["product_id"] or "")))
    return lines


def apply_product_retrocessions(
    *,
    products: Iterable[Mapping[str, Any]] | None,
    inducements: Iterable[Mapping[str, Any]] | None,
    has_documented_waiver,
    currency: str,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    """Zusaetzliche Kostenzeilen, Warnungen und die Offenlegungs-Uebersicht.

    ``products`` None = der Aufrufer kennt die Produkte nicht (z.B. eine
    reine Rechnung ohne Lauf) -> keine Aussage, Uebersicht None.
    """
    if products is None:
        return [], [], None
    lines = build_product_retrocession_lines(
        products, inducements, has_documented_waiver=has_documented_waiver,
    )
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    for line in lines:
        if line["status"] != "present" or not line["undisclosed_rappen"]:
            continue
        source = line["source"] or "nicht angegeben"
        partial = line["covered_by_mandate_entry"]
        items.append({
            "key": COST_ITEM_KEY,
            "label": (
                f"Vergütung von Dritten: {line['product_name']} "
                + (
                    "– über die Mandatsangabe hinausgehender Teil (Schätzung)"
                    if partial else f"({line['rate_bps']} bps p.a., Schätzung)"
                )
            ),
            "category": "Vergütungen von Dritten",
            "frequency": "jährlich",
            "rate_bps": None if partial else line["rate_bps"],
            "amount_rappen": line["undisclosed_rappen"],
            "basis_rappen": line["amount_rappen"],
            "basis_label": "Investiertes Volumen des Produkts",
            "source": f"Produkt-Stammdaten (Retrozessionssatz; Quelle: {source})",
            "is_estimate": True,
            # Teil der TER -- addieren waere Doppelzaehlung, abziehen wuerde
            # eine Rueckerstattung behaupten, die nicht erfasst ist.
            "included_in_total": False,
            "requires_resolution": True,
        })
        if not partial:
            warnings.append(
                f"Das empfohlene Produkt {line['product_name']} zahlt eine Retrozession "
                f"({line['rate_bps']} bps p.a., geschätzt "
                f"{_format_amount(line['estimated_annual_rappen'], currency)} pro Jahr). Im Mandat "
                "ist weder ein Verzicht des Kunden noch die Weitergabe erfasst. Interessenkonflikt "
                "«Retrozession / Inducement» für diesen Anbieter erfassen und Verzicht oder "
                "Rückerstattung dokumentieren (Art. 26 FIDLEG; BGE 132 III 460 / 137 III 393)."
            )

    # N-861-1 (a): Pflichtwarnung je Gruppe, wenn der geregelte Betrag die
    # geschaetzte Summe nicht deckt.
    by_group: dict[Any, list[dict[str, Any]]] = {}
    for line in lines:
        if line["status"] == "present" and line["_group_key"] is not None:
            by_group.setdefault(line["_group_key"], []).append(line)
    for members in by_group.values():
        unresolved_total = sum(int(m["unresolved_rappen"] or 0) for m in members)
        if unresolved_total <= 0:
            continue
        estimate_total = sum(int(m["estimated_annual_rappen"] or 0) for m in members)
        resolved_total = sum(int(m["mandate_resolved_rappen"] or 0) for m in members)
        names = ", ".join(m["product_name"] for m in members)
        warnings.append(
            f"Verzicht bzw. Weitergabe im Mandat deckt für {names} nur "
            f"{_format_amount(resolved_total, currency)} von geschätzt "
            f"{_format_amount(estimate_total, currency)} Retrozession pro Jahr. Der Rest "
            f"({_format_amount(unresolved_total, currency)}) ist ungeregelt: Ein Verzicht wirkt "
            "nur im Umfang der Aufklärung (BGE 137 III 393). Aufklärung und Verzicht auf den "
            "vollen Betrag erweitern oder den Rest zurückerstatten."
        )
    for line in lines:
        line.pop("_group_key", None)

    unknown = [line["product_name"] for line in lines if line["status"] == "unknown"]
    if unknown:
        listed = ", ".join(unknown[:6]) + (f" und {len(unknown) - 6} weitere" if len(unknown) > 6 else "")
        warnings.append(
            f"Retrozession unbekannt für {len(unknown)} empfohlene"
            f"{'s Produkt' if len(unknown) == 1 else ' Produkte'} ({listed}). Diese Produkte "
            "gelten NICHT als retrozessionsfrei. Satz und Quelle im Fondsuniversum erfassen, "
            "bevor das Dokument dem Kunden abgegeben wird (Art. 26 FIDLEG)."
        )

    summary = {
        "schema_version": DISCLOSURE_SCHEMA_VERSION,
        "lines": lines,
        "unknown_count": len(unknown),
        "present_count": sum(1 for line in lines if line["status"] == "present"),
        "unresolved_count": sum(1 for line in lines if line["requires_resolution"]),
        # Vollstaendig = jeder Satz bekannt UND jede Retrozession geregelt.
        "complete": not unknown and not any(line["requires_resolution"] for line in lines),
        "legal_reference": "Art. 26 FIDLEG; Art. 400 OR; BGE 132 III 460; BGE 137 III 393",
    }
    return items, warnings, summary


# --------------------------------------------------------------------------
# H7 C-4: Retro-Gate der Finalisierung
# --------------------------------------------------------------------------
# H7 C-4 (Compliance-Audit 2026-11-07, Luecke 4): Retro-Gate bei der
# Finalisierung.
#
# Der Kostenausweis setzt seit AUDIT-2026-11 P1 (L1) ``is_complete=False``,
# wenn eine Retrozession unbekannt (Satz NULL) oder ungeregelt ist bzw. der
# geregelte Betrag die Schaetzung nicht deckt (BGE 137 III 393: ein Verzicht
# wirkt nur im Umfang der Aufklaerung; BGE 143 III 348; Art. 26 FIDLEG;
# Art. 400 Abs. 1 OR). Durchgesetzt wurde das nirgends: die Finalisierung fror
# auch einen solchen Ausweis ein.
#
# Dieser Abschnitt liest nur das bestehende Urteil dieser Datei (keine
# zweite Retro-Logik) und liefert der Finalisierung einen Blockgrund:
#
# * ``RETROCESSION_DISCLOSURE_INCOMPLETE`` -- die Retro-Uebersicht des Laufs ist
#   unvollstaendig (unbekannter Satz, ungeregelt, Deckung zu klein) oder eine
#   manuell erfasste Verguetung von Dritten ist ohne Verzicht/Weitergabe.
# * ``RETROCESSION_EVIDENCE_UNAVAILABLE`` -- der Ausweis ist nicht berechenbar,
#   und der Lauf enthaelt Produkte mit unbekannter oder vorhandener
#   Retrozession. "Nicht pruefbar" gilt nicht als "geregelt".
#
# Kein Override (Dok. 10 L1: "Block ohne Override"). Heilung: Satz und Quelle
# im Fondsuniversum erfassen bzw. Offenlegung mit Verzicht (Beleg) oder
# Rueckerstattung im Mandat dokumentieren.

# Reason-Codes (Katalog core/reason_codes.py, Literale wie im Rest der Datei).
RETRO_INCOMPLETE = "RETROCESSION_DISCLOSURE_INCOMPLETE"
RETRO_UNAVAILABLE = "RETROCESSION_EVIDENCE_UNAVAILABLE"

_HEAL_HINT = (
    "Retrozessionssatz und Quelle im Fondsuniversum erfassen bzw. im Mandat "
    "die Offenlegung mit Verzicht (Beleg, Umfang mindestens der geschätzte "
    "Betrag) oder die Rückerstattung dokumentieren (Art. 26 FIDLEG; "
    "Art. 400 OR; BGE 137 III 393)."
)


def _retro_names(lines: list[dict[str, Any]], limit: int = 6) -> str:
    names = [str(line.get("product_name") or "Produkt") for line in lines]
    text = ", ".join(names[:limit])
    if len(names) > limit:
        text += f" und {len(names) - limit} weitere"
    return text


def _run_has_retro_relevant_products(db: Session, run: Any) -> bool:
    """True, wenn ein Produkt des Laufs eine unbekannte (NULL) oder positive
    Retrozession traegt."""
    rates = db.execute(
        _sql_text(
            "SELECT p.retrocession_bps FROM recommendation_positions rp "
            "JOIN products p ON p.id = rp.product_id WHERE rp.run_id = :run_id"
        ),
        {"run_id": str(run.id)},
    ).all()
    return any(rate is None or int(rate) > 0 for (rate,) in rates)


def retrocession_finalization_block(db: Session, mandate: Any, run: Any) -> dict[str, Any] | None:
    """Blockgrund fuer die Finalisierung oder None.

    Rueckgabe: ``{"reason_code", "message", "unknown", "unresolved",
    "unresolved_items"}``.
    """
    try:
        payload = build_cost_disclosure_for_run(db, mandate, run)
    except Exception:  # noqa: BLE001 -- nicht berechenbar = nicht nachgewiesen
        payload = None
    if payload is None or payload.get("data_pending"):
        if not _run_has_retro_relevant_products(db, run):
            return None
        return {
            "reason_code": RETRO_UNAVAILABLE,
            "message": (
                "Freigabe gesperrt: Der Kostenausweis dieser Empfehlung ist nicht "
                "berechenbar, und sie enthält Produkte mit unbekannter oder "
                "vorhandener Retrozession. Ob die Vergütungen von Dritten "
                "offengelegt und geregelt sind, ist damit nicht nachweisbar. "
                + _HEAL_HINT
            ),
            "unknown": [],
            "unresolved": [],
            "unresolved_items": [],
        }

    summary = payload.get("product_retrocessions") or None
    lines = list((summary or {}).get("lines") or [])
    unknown = [line for line in lines if line.get("status") == "unknown"]
    unresolved = [line for line in lines if line.get("requires_resolution")]
    retro_lines_ok = summary is None or bool(summary.get("complete"))
    unresolved_items = [
        str(item.get("label") or "Vergütung von Dritten")
        for item in (payload.get("cost_items") or [])
        if item.get("requires_resolution")
    ]
    if retro_lines_ok and not unresolved_items:
        return None
    parts: list[str] = []
    if unknown:
        parts.append(f"Retrozession unbekannt für {_retro_names(unknown)}")
    if unresolved:
        parts.append(f"Retrozession nicht oder nicht vollständig geregelt für {_retro_names(unresolved)}")
    if unresolved_items and not unresolved:
        parts.append(f"ungeregelte Vergütung von Dritten: {'; '.join(unresolved_items[:3])}")
    if not parts:
        parts.append("Retrozessions-Ausweis unvollständig")
    return {
        "reason_code": RETRO_INCOMPLETE,
        "message": (
            "Freigabe gesperrt: Der Retrozessions-Ausweis ist unvollständig ("
            + "; ".join(parts) + "). " + _HEAL_HINT
        ),
        "unknown": [line.get("product_id") for line in unknown],
        "unresolved": [line.get("product_id") for line in unresolved],
        "unresolved_items": unresolved_items,
    }
