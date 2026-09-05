"""FX-Rates-Endpoints — Berater pflegt Wechselkurse zu CHF.

Spec: docs/planning/2026-05-17-sprint-9-multi-currency.md Phase 2
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db, new_uuid
from models.fx_rate import FXRate
from models.users import User
from services.audit import log
# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Quell-IP fuer FX-Rate-Aenderungen
# (wirken global auf ALLE Tenants).
from routers.auth import _extract_client_ip
from services.auth import get_current_user, require_advisor_or_platform_scope_for_global_reference_data
from services.currency.fx_rates import DEFAULT_FX_RATES, FXRateSource

router = APIRouter(tags=["FX Rates"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class FXRateEntry(BaseModel):
    currency: str
    rate: float  # rate-to-CHF (1 unit currency = rate CHF)
    source: Optional[str] = "Manual"
    notes: Optional[str] = None

    # FX-REF-001 (2026-09-04, Marktpreis-/FX-Referenzintegritaetsaudit):
    # Pydantics laxe float-Koerzion akzeptiert `rate: true` unbemerkt als
    # 1.0 -- ein Bool traegt keine Kurs-Semantik. Muss mode="before" laufen,
    # weil der urspruengliche Typ nach der eingebauten Koerzion bereits
    # verloren ist.
    @field_validator("rate", mode="before")
    @classmethod
    def _reject_bool_rate(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("rate must be a number, not a boolean")
        return value

    # FX-REF-001: rate wird sowohl VOR als auch NACH der Integer-
    # Quantisierung geprueft (rate_x10000 = round(rate * 10000) ist der
    # kanonische, in der DB persistierte Wert). Die alte Pruefung
    # ("> 0 und <= 1000" auf dem reinen Float) liess z.B. rate=0.00001
    # durch -- das quantisiert aber zu rate_x10000=0 und wurde bislang mit
    # HTTP 200 als neue globale Current-Zeile persistiert (der strikte
    # Solver-Loader blockierte danach global, der aeltere Reporting-Loader
    # ueberlas dieselbe Nullzeile still und rechnete mit Defaults weiter --
    # zwei effektive FX-Wahrheiten fuer denselben DB-Stand). NaN/Infinity
    # bestehen den reinen `<= 0`-Vergleich (Vergleiche mit NaN sind immer
    # False) und liessen `round()` bislang mit HTTP 500 crashen statt einer
    # stabilen 422-Domainantwort.
    @field_validator("rate")
    @classmethod
    def _validate_rate_domain(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("rate must be a finite number (no NaN/Infinity)")
        if value <= 0:
            raise ValueError("rate must be > 0")
        # 2026-07-25 (Generalaudit, Wave 13): keine Obergrenze -- ein
        # Tippfehler wirkt global auf ALLE Tenants/Mandate (kein tenant_id
        # auf FXRate). Bounds grosszuegig (kein reales Waehrungspaar liegt
        # annaehernd in dieser Groessenordnung).
        if value > 1000:
            raise ValueError("rate unplausibel hoch (>1000)")
        rate_x10000 = int(round(value * 10000))
        if rate_x10000 < 1 or rate_x10000 > 10_000_000:
            raise ValueError(
                "rate quantizes out of the valid domain "
                f"(rate_x10000={rate_x10000}); must resolve to 1..10000000 "
                "after *10000 rounding"
            )
        return value

    @model_validator(mode="after")
    def _validate_chf_identity(self) -> "FXRateEntry":
        ccy = self.currency.upper().strip()
        if ccy == "CHF":
            if abs(self.rate - 1.0) > 1e-6:
                raise ValueError("CHF rate must be 1.0 (base currency)")
            if int(round(self.rate * 10000)) != 10000:
                raise ValueError("CHF rate must quantize to exactly 10000")
        return self


class FXRatesPayload(BaseModel):
    rates: list[FXRateEntry]

    # FX-REF-001: doppelte Waehrungen im selben Batch duerfen nicht still
    # zwei aufeinanderfolgende Rollover-Zyklen in derselben Transaktion
    # ausloesen. Diese Payload-Validierung laeuft VOR dem Endpoint-Body,
    # sodass ein Fehler alle alten Current-Zeilen unveraendert laesst
    # (kanonischer Fix-Vertrag Punkt 3: vollstaendige Batch-Prevalidation
    # vor jeder Mutation).
    @model_validator(mode="after")
    def _reject_duplicate_currencies(self) -> "FXRatesPayload":
        seen: set[str] = set()
        for entry in self.rates:
            ccy = entry.currency.upper().strip()
            if ccy in seen:
                raise ValueError(f"Duplicate currency '{ccy}' in batch")
            seen.add(ccy)
        return self


class FXRateResponse(BaseModel):
    currency: str
    rate: float
    source: str
    valid_from: str
    updated_at: str


@router.get("/fx-rates/current", response_model=list[FXRateResponse])
def list_current_fx_rates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Listet alle aktuellen FX-Rates (is_current=1). Fallback auf Default
    wenn DB leer."""
    rows = (
        db.query(FXRate)
        .filter(FXRate.is_current == 1, FXRate.valid_until.is_(None))
        .order_by(FXRate.currency)
        .all()
    )
    if rows:
        return [
            FXRateResponse(
                currency=str(r.currency),
                rate=float(r.rate_x10000) / 10000.0,
                source=str(r.source or "Manual"),
                valid_from=str(r.valid_from),
                updated_at=str(r.updated_at),
            )
            for r in rows
        ]
    # DB leer → Defaults zurueckgeben (Berater sieht was er pflegen koennte)
    now = _now_iso()
    return [
        FXRateResponse(
            currency=ccy,
            rate=rate,
            source="Default",
            valid_from=now,
            updated_at=now,
        )
        for ccy, rate in sorted(DEFAULT_FX_RATES.items())
    ]


def _sanitized_validation_detail(exc: ValidationError) -> list[dict]:
    """Build a JSON-safe 422 detail from a pydantic ValidationError.

    FX-REF-001: FastAPI's default request-body validation normally lets
    ``payload: FXRatesPayload`` be parsed and validated automatically, and
    turns a ``ValidationError`` into a 422 via its own generic handler. That
    generic handler echoes the raw offending value back in each error's
    ``input`` field. When the offending value is a non-finite float
    (``rate: NaN`` / ``rate: Infinity`` in the request JSON -- pydantic's
    JSON parser accepts these non-standard tokens the same way Python's
    ``json.loads`` does), Starlette's ``JSONResponse`` renders with
    ``allow_nan=False`` and crashes with an unrelated HTTP 500 while trying
    to serialize the *error response itself* -- reproducing exactly the
    "NaN reaches quantization and answers 500" symptom the audit describes,
    just one layer up. This endpoint therefore parses/validates the body
    itself and returns a minimal, always-JSON-safe detail (loc/msg/type
    only, never the raw offending value) instead of relying on FastAPI's
    generic handler for this one route.
    """
    return [
        {
            "loc": list(err.get("loc", ())),
            "msg": str(err.get("msg", "Invalid value")),
            "type": str(err.get("type", "value_error")),
        }
        for err in exc.errors()
    ]


@router.put("/fx-rates", response_model=list[FXRateResponse])
async def upsert_fx_rates(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor_or_platform_scope_for_global_reference_data),
):
    """Upsert mehrere FX-Rates. Alte is_current=1 Werte werden auf
    is_current=0 + valid_until=now gesetzt (Versionierung)."""
    raw_body = await request.body()
    try:
        payload = FXRatesPayload.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=_sanitized_validation_detail(exc)
        )
    if not payload.rates:
        raise HTTPException(status_code=400, detail="No rates provided")

    now = _now_iso()
    affected_currencies: set[str] = set()

    # FX-REF-001: rate-Domain (Bool/NaN/Infinity/Bounds/Quantisierung) und
    # CHF-Identitaet werden jetzt vollstaendig in FXRateEntry validiert
    # (siehe Pydantic-Validatoren oben) -- bevor dieser Endpoint-Body je
    # ausgefuehrt wird. Nur die Currency-Code-Form bleibt hier, weil sie
    # reine String-Hygiene ist, keine Kurs-Domain.
    for entry in payload.rates:
        ccy = entry.currency.upper().strip()
        if len(ccy) != 3:
            raise HTTPException(
                status_code=422, detail=f"Invalid currency '{entry.currency}'"
            )

        # Alte is_current=1 invalidieren
        # 2026-07-25 (Generalaudit, Wave 13): with_for_update() ergaenzt --
        # gleiches Race-Condition-Muster wie der in Wave 11 gefixte
        # update_cma-Fund. Zwei nahezu gleichzeitige Upserts fuer dieselbe
        # Waehrung haetten zwei is_current=1-Zeilen erzeugen koennen.
        old_rows = db.query(FXRate).filter(
            FXRate.currency == ccy,
            FXRate.is_current == 1,
        ).with_for_update().all()
        old_rate_display = None
        for old in old_rows:
            old_rate_display = f"{float(old.rate_x10000) / 10000.0:.4f}"
            old.is_current = 0
            old.valid_until = now
            old.updated_at = now

        # Neue Zeile
        row = FXRate(
            id=new_uuid(),
            currency=ccy,
            rate_x10000=int(round(float(entry.rate) * 10000)),
            valid_from=now,
            valid_until=None,
            is_current=1,
            source=str(entry.source or "Manual"),
            notes=entry.notes,
            created_at=now,
            updated_at=now,
            created_by=str(getattr(current_user, "id", None) or ""),
        )
        db.add(row)
        affected_currencies.add(ccy)
        # 2026-07-24 (Generalaudit): FX-Rate-Aenderungen wirken global auf
        # ALLE Tenants (kein tenant_id auf FXRate) und verzerren sonst
        # unbemerkt Fremdwaehrungs-Betraege in Beratungsdokumenten -- bisher
        # nicht im zentralen AuditLog nachvollziehbar (nur die versionierte
        # FXRate-Tabelle selbst zeigt den neuen Wert, kein "wer/wann").
        log(
            db, user_id=current_user.id, user_name=current_user.full_name,
            table_name="fx_rates", record_id=row.id, action="UPSERT",
            field_name=ccy, old_value=old_rate_display,
            new_value=f"{float(entry.rate):.4f}",
            ip_address=_extract_client_ip(request),
        )

    # FX-REF-001: ``ux_fx_rate_one_current`` (models/fx_rate.py) macht das
    # "hoechstens eine Current-Zeile pro Waehrung"-Invariant jetzt DB-seitig
    # atomar. with_for_update() oben schuetzt den haeufigen Fall (bestehende
    # Zeile wird gesperrt), deckt aber nicht zwei echte parallele
    # Erstwrites fuer eine Waehrung ohne existierende Current-Zeile ab --
    # dort gibt es fuer FOR UPDATE nichts zu sperren. Der Unique-Index faengt
    # genau diesen Fall beim Commit; der Verlierer bekommt einen stabilen
    # 409 statt eines rohen 500 oder zweier effektiver Current-Zeilen.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Concurrent FX-rate update detected for one of the "
                "requested currencies; please retry."
            ),
        )
    return list_current_fx_rates(db=db, current_user=current_user)
