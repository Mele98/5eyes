"""CCX-P3-FX (N-909-01) Testhilfe: belegte, heute beobachtete FX-Kurse.

Seit N-909-01 rechnen kundenwirksame Kanaele (Engine, Payload, PDFs, Depot,
Handoff, Plausibilitaet) nur noch mit belegten, frischen DB-Kursen; ein
Ersatzkurs (``DEFAULT_FX_RATES`` bzw. Quelle ``Default``) sperrt typisiert
``CCX_FX_BASIS_*``. Tests, deren Gegenstand nicht die FX-Sperre ist, die aber
Fremdwaehrungen verwenden, stuetzten sich bisher still auf den Ersatzkurs. Sie
erfassen den Kurs jetzt explizit wie ein Berater (Quelle ``Manual``, Stichtag
heute). Als Wert dient derselbe Zahlenwert wie der fruehere Ersatzkurs, damit
die fachlichen Erwartungen der Tests unveraendert bleiben -- er ist ein
Testvektor, kein Fachwert.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Iterable, Mapping

from models.fx_rate import FXRate
from services.currency.fx_rates import DEFAULT_FX_RATES, rate_x10000


def seed_attested_fx(db, currencies: Iterable[str] | Mapping[str, float], *, commit: bool = True) -> None:
    """Je Waehrung genau eine aktuelle, heute beobachtete ``Manual``-Zeile."""
    stamp = date.today().isoformat()
    items = currencies.items() if isinstance(currencies, Mapping) else (
        (c, DEFAULT_FX_RATES[str(c).upper()]) for c in currencies
    )
    for currency, rate in items:
        code = str(currency).upper()
        if code == "CHF":
            continue
        x10000 = rate_x10000(float(rate), code)
        current = db.query(FXRate).filter(FXRate.currency == code, FXRate.is_current == 1).all()
        if len(current) == 1 and current[0].rate_x10000 == x10000 and current[0].source == "Manual" \
                and str(current[0].valid_from or "")[:10] == stamp and current[0].valid_until is None:
            continue  # idempotent: derselbe belegte Kurs liegt schon vor
        db.query(FXRate).filter(FXRate.currency == code, FXRate.is_current == 1).update(
            {"is_current": 0, "valid_until": stamp}, synchronize_session=False,
        )
        db.add(FXRate(
            id=str(uuid.uuid4()), currency=code, rate_x10000=x10000,
            valid_from=stamp, is_current=1, source="Manual", notes="Testvektor (CCX-P3-FX)",
            created_at=stamp, updated_at=stamp,
        ))
    if commit:
        db.commit()
    else:
        db.flush()
