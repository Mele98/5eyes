"""Verdrahtung der Depot-Policy (PORTFOLIO-DATA-001, Teil 2).

Quelle der Frische ist der DepotSnapshotV1 (``services/depot_snapshot.py``)
plus die Liquiditaet des Beratungsvermoegens
(``services/portfolio_handoff_cash.py``) und die aktiven FX-Zeilen:

- ``holdings_as_of``: aeltester ``holding_as_of_date`` der Snapshot-Positionen;
- ``price_as_of``: aeltestes Preisdatum der Snapshot-Positionen;
- ``fx_as_of``: aeltestes ``valid_from`` der aktiven FX-Zeilen fuer die
  benoetigten Waehrungen; nur Basiswaehrung -> nicht anwendbar; versionierte
  Default-Kurse oder fehlende Zeile -> kein Stichtag;
- ``cash_as_of``: aeltester Bewertungsstichtag der Liquiditaetspositionen des
  Beratungsvermoegens; keine erfasste Liquiditaet -> kein Stichtag (nicht
  erfasst ist kein Beleg fuer null);
- ``corporate_actions_checked_at``: im System gibt es keine Quelle -> fehlt.

Den Abgleich Depot <-> Beratungsvermoegen gibt es noch nicht auf
Instrumentenebene (keine Beratungsseite mit Positionen je Titel); er wird als
``not_evaluated`` ausgewiesen.

Wirkung:
- ``assess_mandate_portfolio_data`` liefert die Auswertung immer (sichtbar).
- ``assert_portfolio_data_release_eligible`` greift nur mit aktiver Policy
  (Status APPROVED mit allen Freigaben). Ohne aktive Policy kehrt es sofort
  zurueck, ohne DB-Zugriff: der heutige Betrieb bleibt unveraendert.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from services.portfolio_data_freshness import FreshnessInputError, assess_freshness
from services.portfolio_data_policy import (
    GATE_ACTIONS,
    PortfolioDataPolicyError,
    evaluate_portfolio_data_gate,
    load_portfolio_data_policy,
)

PORTFOLIO_DATA_NOT_RELEASABLE = "PORTFOLIO_DATA_NOT_RELEASABLE"

RECONCILIATION_NOT_AVAILABLE = (
    "Abgleich Depot <-> Beratungsvermoegen ist noch nicht verfuegbar: es gibt "
    "keine Beratungsseite mit Positionen je Titel."
)

_ACTION_LABELS = {
    "finalize": "Die Empfehlung kann nicht finalisiert werden",
    "pdf": "Der Advisory-Report kann nicht exportiert werden",
    "signature": "Das Dokument kann nicht unterzeichnet werden",
    "handoff": "Die Handelsliste kann nicht weitergeleitet werden",
    "draft": "Der Entwurf kann nicht erstellt werden",
}


def load_policy_state():
    """``(policy | None, error | None)``; eine nicht ladbare Policy ist nie aktiv."""
    try:
        return load_portfolio_data_policy(), None
    except PortfolioDataPolicyError as exc:
        return None, str(exc)


def _oldest(values: list) -> str | None:
    """Aeltester Wert; fehlt einer, gibt es keinen belegten Stichtag."""
    if not values or any(not str(v or "").strip() for v in values):
        return None
    return min(str(v).strip() for v in values)


def _fx_component(db: Session, currencies: set[str], base: str) -> dict:
    from models.fx_rate import FXRate

    foreign = {c for c in currencies if c and c != base}
    if not foreign:
        return {"not_applicable": True, "reason": f"nur Basiswaehrung {base}"}
    needed = sorted((foreign | {base}) - {"CHF"})
    rows = (
        db.query(FXRate)
        .filter(FXRate.currency.in_(needed), FXRate.is_current == 1, FXRate.valid_until.is_(None))
        .all()
    )
    by_ccy = {str(r.currency).upper(): r for r in rows}
    if set(needed) - set(by_ccy):
        return {"as_of": None, "source": "fx_rates", "missing_currencies": sorted(set(needed) - set(by_ccy))}
    return {
        "as_of": _oldest([by_ccy[c].valid_from for c in needed]),
        "source": "fx_rates:" + ",".join(sorted({str(by_ccy[c].source or "unbekannt") for c in needed})),
    }


def freshness_components(db: Session, mandate, snapshot: dict) -> dict:
    """Komponenten mit Stichtag und Quelle aus Snapshot, Liquiditaet und FX."""
    from services.portfolio_handoff_cash import AdvisoryCashValuationError, advisory_cash_entries

    base = str(snapshot.get("currency") or "CHF").upper()
    positions = snapshot.get("positions") or []
    currencies = {str(p.get("product_currency") or "").upper() for p in positions}
    try:
        cash = advisory_cash_entries(db, mandate)
        cash_component = {
            "as_of": _oldest([c.get("holding_as_of_date") for c in cash]),
            "source": "wealth_positions" if cash else None,
        }
        currencies |= {str(c.get("product_currency") or "").upper() for c in cash}
    except AdvisoryCashValuationError as exc:
        cash_component = {"as_of": None, "source": "wealth_positions", "error": str(exc)}
    return {
        "holdings_as_of": {
            "as_of": _oldest([p.get("holding_as_of_date") for p in positions]),
            "source": snapshot.get("source"),
        },
        "cash_as_of": cash_component,
        "price_as_of": {
            "as_of": _oldest([p.get("price_date") for p in positions]),
            "source": "price_history",
        },
        "fx_as_of": _fx_component(db, currencies, base),
        "corporate_actions_checked_at": {"as_of": None, "source": None},
    }


def assess_mandate_portfolio_data(
    db: Session, mandate, *, snapshot: dict | None = None, advice_at: datetime | None = None,
    policy_state=None,
) -> dict:
    """Frische, Abgleich und Gate je Aktion fuer ein Mandat (immer sichtbar)."""
    from services.currency.fx_rates import FXRateLoadError
    from services.depot_snapshot import build_depot_snapshot

    policy, policy_error = policy_state or load_policy_state()
    advice_at = advice_at or datetime.now(timezone.utc)
    freshness, freshness_error, snapshot_id = None, None, None
    try:
        if snapshot is None:
            snapshot = build_depot_snapshot(db, mandate, as_of=advice_at.date())
        snapshot_id = snapshot.get("snapshot_id")
        if policy is not None:
            components = freshness_components(db, mandate, snapshot)
            freshness = assess_freshness(components, advice_at=advice_at, policy=policy)
    except (FXRateLoadError, FreshnessInputError, ValueError) as exc:
        freshness_error = str(exc)

    gates = {
        action: evaluate_portfolio_data_gate(
            policy, action=action, freshness=freshness, reconciliation=None, policy_error=policy_error,
        )
        for action in GATE_ACTIONS
    }
    return {
        "policy": policy.summary() if policy is not None else None,
        "policy_error": policy_error,
        "advice_at": advice_at.isoformat(),
        "snapshot_id": snapshot_id,
        "freshness": freshness,
        "freshness_error": freshness_error,
        "reconciliation": {"status": "not_evaluated", "message": RECONCILIATION_NOT_AVAILABLE},
        "gates": gates,
    }


def assert_portfolio_data_release_eligible(db: Session, mandate, *, action: str) -> None:
    """Gate fuer Finalisierung, PDF, Signatur und Handoff.

    Nur mit aktiver Policy wirksam (409 mit ``PORTFOLIO_DATA_NOT_RELEASABLE``).
    Ohne aktive Policy: sofortige Rueckkehr ohne DB-Zugriff.
    """
    if action not in GATE_ACTIONS:
        raise ValueError(f"Unbekannte Aktion: {action!r}")
    policy, policy_error = load_policy_state()
    if policy is None or not policy.is_active:
        return
    assessment = assess_mandate_portfolio_data(db, mandate, policy_state=(policy, policy_error))
    gate = assessment["gates"][action]
    if not gate["blocked"]:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "reason_code": PORTFOLIO_DATA_NOT_RELEASABLE,
            "message": (
                f"{_ACTION_LABELS[action]}: die Depotdaten erfuellen die Policy "
                f"{policy.version} nicht ({', '.join(gate['reasons'])})."
            ),
            "action": action,
            "reasons": gate["reasons"],
            "policy_version": policy.version,
            "freshness_error": assessment["freshness_error"],
        },
    )
