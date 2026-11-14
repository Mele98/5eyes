"""Beratungsentscheid finalisieren: P1-Siegel mit P3-Bewertungsbindung.

Fassade fuer ``routers/review.py`` (CCX-P1 + CCX-P3): die Bewertung des
gesamten Bestands (``services.holdings_valuation``, Snapshot + Entscheid je
Position + FX-Basis) wird vorbereitet und als Daten an das unveraenderte
P1-Siegel (``services.advisory_decision_envelope``) uebergeben. Der Envelope
selbst bewertet nichts; er bindet Snapshot und Ledger per Kind-Hash, sperrt
typisiert bei nicht COMPLETE und prueft per Fence, dass sich Bestand, Preise
und Kurse waehrend der Versiegelung nicht geaendert haben.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from services.advisory_decision_envelope import (
    current_envelope_freshness,
    current_verified_envelope,
    seal_advisory_envelope,
)
from services.holdings_valuation import prepare_valuation_binding


def finalize_advisory_decision(
    db: Session,
    *,
    mandate: Any,
    run: Any,
    user: Any,
    ip_address: str | None = None,
    confirm_no_existing_holdings: bool = False,
    expected_manifest_hash: str | None = None,
) -> Any:
    """Bewertet, bindet und versiegelt (Transaktion des Aufrufers).

    ``expected_manifest_hash`` (CCX-P2): beim Start gelesener Manifest-Hash;
    weicht er beim Siegel ab -> ``CCX_RESULT_SUPERSEDED``."""
    valuation = prepare_valuation_binding(
        db, mandate, run, confirm_no_holdings=confirm_no_existing_holdings,
    )
    return seal_advisory_envelope(
        db, mandate=mandate, run=run, user=user, ip_address=ip_address, valuation=valuation,
        expected_manifest_hash=expected_manifest_hash,
    )


def current_advisory_envelope(db: Session, *, mandate: Any, user: Any, ip_address: str | None = None) -> Any:
    """Aktueller, integritaetsgepruefter Beratungsentscheid (P1)."""
    return current_verified_envelope(db, mandate=mandate, user=user, ip_address=ip_address)


__all__ = ["current_advisory_envelope", "current_envelope_freshness", "finalize_advisory_decision"]
