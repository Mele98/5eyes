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
from core.db_integrity import raise_if_check_violation
from sqlalchemy.orm import Session

from database import get_db, new_uuid
from models.fx_rate import FXRate
from models.users import User
from services.audit import log
# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Quell-IP fuer FX-Rate-Aenderungen
# (wirken global auf ALLE Tenants).
from services.advisory_report_cache import clear_all as clear_advisory_report_cache
from services.auth import extract_client_ip as _extract_client_ip
from services.auth import get_current_user, require_advisor_or_platform_scope_for_global_reference_data
from services.currency.fx_rates import DEFAULT_FX_RATES, FXRateSource, is_substitute_source, rate_x10000

router = APIRouter(tags=["FX Rates"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class FXRateEntry(BaseModel):
    currency: str
    rate: float  # rate-to-CHF (1 unit currency = rate CHF)
    source: Optional[str] = "Manual"
    notes: Optional[str] = None
    # CCX-P3-FX (N-909-11): ausdrueckliche Bestaetigung "Kurs geprueft" je
    # Zeile. Noetig, um einen unveraenderten Kurs neu zu beobachten (Frist)
    # oder einen Kurs anzunehmen, der exakt dem Ersatzkurs entspricht.
    confirm_current: bool = False

    @field_validator("confirm_current", mode="before")
    @classmethod
    def _strict_confirm_flag(cls, value: object) -> object:
        if not isinstance(value, bool):
            raise ValueError("confirm_current must be a boolean")
        return value

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
        rate_scaled = int(round(value * 10000))
        if rate_scaled < 1 or rate_scaled > 10_000_000:
            raise ValueError(
                "rate quantizes out of the valid domain "
                f"(rate_x10000={rate_scaled}); must resolve to 1..10000000 "
                "after *10000 rounding"
            )
        # CCX-P3-FX (N-909-08): kein stilles Runden. Mehr als vier Dezimalen
        # sind in diesem Speicherformat kein belegter Kurs (wie rate_x10000()).
        try:
            rate_x10000(value, "FX")
        except ValueError as exc:
            raise ValueError(
                "rate hat mehr als vier Dezimalen; das Speicherformat (x10000) "
                "würde still runden"
            ) from exc
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
    """Listet alle aktuellen FX-Rates: DB-gepflegte Kurse (is_current=1) je
    Waehrung, ergaenzt um Default-Kurse fuer jede Waehrung, die (noch) keine
    DB-Zeile hat.

    FX-CURRENT-LIST-DEFAULT-DROP-001 (Kontrollrunde 2026-09-24): vorher war
    dies ein reines Entweder-Oder -- sobald AUCH NUR EINE Waehrung eine
    DB-Zeile hatte, verschwanden alle uebrigen (noch nie manuell gepflegten)
    Default-Waehrungen komplett aus der Liste, obwohl fuer sie weiterhin ein
    gueltiger Default-Kurs existiert (und in der tatsaechlichen Konvertierung,
    FXRateSource.from_db_for_model, bereits korrekt als Fallback verwendet
    wird -- nur diese Listen-Ansicht war inkonsistent). Live reproduziert:
    nach dem Setzen NUR einer einzelnen Waehrung zeigte das Beratertool
    fuer alle anderen 12 Default-Waehrungen keinen Kurs mehr an."""
    rows = (
        db.query(FXRate)
        .filter(FXRate.is_current == 1, FXRate.valid_until.is_(None))
        .all()
    )
    now = _now_iso()
    by_currency: dict[str, FXRateResponse] = {
        ccy: FXRateResponse(
            currency=ccy, rate=rate, source="Default",
            valid_from=now, updated_at=now,
        )
        for ccy, rate in DEFAULT_FX_RATES.items()
    }
    for r in rows:
        ccy = str(r.currency)
        by_currency[ccy] = FXRateResponse(
            currency=ccy,
            rate=float(r.rate_x10000) / 10000.0,
            source=str(r.source or "Manual"),
            valid_from=str(r.valid_from),
            updated_at=str(r.updated_at),
        )
    return [by_currency[ccy] for ccy in sorted(by_currency)]


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
    actor = str(getattr(current_user, "id", None) or "")

    # CCX-P3-FX (N-909-11): ein Kurs gilt nur als belegt, wenn ihn jemand
    # bewusst erfasst oder bestaetigt hat. Pass 1 entscheidet je Zeile und
    # prueft den ganzen Batch, BEVOR irgendetwas geschrieben wird.
    plan: list[tuple] = []
    for entry in payload.rates:
        ccy = entry.currency.upper().strip()
        if len(ccy) != 3:
            raise HTTPException(
                status_code=422, detail=f"Invalid currency '{entry.currency}'"
            )
        source = str(entry.source or "").strip() or "Manual"
        substitute = is_substitute_source(source)
        scaled = rate_x10000(float(entry.rate), ccy)
        # 2026-07-25 (Generalaudit, Wave 13): with_for_update() -- zwei nahezu
        # gleichzeitige Upserts fuer dieselbe Waehrung duerfen keine zwei
        # is_current=1-Zeilen erzeugen.
        old_rows = db.query(FXRate).filter(
            FXRate.currency == ccy,
            FXRate.is_current == 1,
        ).with_for_update().all()
        current = old_rows[0] if len(old_rows) == 1 else None
        unchanged = (
            current is not None
            and int(current.rate_x10000) == scaled
            and str(current.source or "").strip().casefold() == source.casefold()
        )
        if entry.confirm_current and substitute:
            raise HTTPException(status_code=422, detail=(
                f"{ccy}: ein Ersatzkurs (Quelle Default) kann nicht als geprüft "
                "bestätigt werden."
            ))
        if unchanged and not entry.confirm_current:
            continue  # No-op: kein neuer Beobachtungszeitpunkt ohne Bestaetigung
        default_rate = DEFAULT_FX_RATES.get(ccy)
        if (
            ccy != "CHF" and not substitute and not entry.confirm_current and default_rate is not None
            and rate_x10000(default_rate, ccy) == scaled
        ):
            raise HTTPException(status_code=422, detail=(
                f"{ccy}: der Kurs entspricht exakt dem Ersatzkurs. Er wird nur "
                "mit ausdrücklicher Bestätigung 'Kurs geprüft' "
                "(confirm_current) als belegt angenommen."
            ))
        plan.append((entry, ccy, source, scaled, old_rows, unchanged))

    for entry, ccy, source, scaled, old_rows, unchanged in plan:
        old_rate_display = None
        for old in old_rows:
            old_rate_display = f"{float(old.rate_x10000) / 10000.0:.4f}"
            old.is_current = 0
            old.valid_until = now
            old.updated_at = now

        row = FXRate(
            id=new_uuid(),
            currency=ccy,
            rate_x10000=scaled,
            valid_from=now,
            valid_until=None,
            is_current=1,
            source=source,
            notes=entry.notes,
            created_at=now,
            updated_at=now,
            created_by=actor,
        )
        db.add(row)
        affected_currencies.add(ccy)
        # 2026-07-24 (Generalaudit): FX-Rate-Aenderungen wirken global auf
        # ALLE Tenants (kein tenant_id auf FXRate) -> zentraler AuditLog.
        # CCX-P3-FX (N-909-11): eine Bestaetigung ohne Kursaenderung ist ein
        # eigener, auditierter Vorgang (APPROVE), keine stille Neubeobachtung.
        confirmed_only = unchanged and entry.confirm_current
        log(
            db, user_id=current_user.id, user_name=current_user.full_name,
            table_name="fx_rates", record_id=row.id,
            action="APPROVE" if confirmed_only else "UPSERT",
            field_name=ccy, old_value=old_rate_display,
            new_value=(
                f"{scaled / 10000.0:.4f} geprueft ({source}, {now[:10]})"
                if entry.confirm_current else f"{scaled / 10000.0:.4f}"
            ),
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
    except IntegrityError as exc:
        db.rollback()
        # RC-CH-1-F1: CHECK-Verstoss -> zentraler Handler (422), kein Konflikt.
        raise_if_check_violation(exc)
        raise HTTPException(
            status_code=409,
            detail=(
                "Concurrent FX-rate update detected for one of the "
                "requested currencies; please retry."
            ),
        )
    # CCX-P3-FX (N-909-05): Kurse sind global; jeder gecachte Bericht traegt
    # eine FX-Basis -> nach einem Kurswechsel alle Berichte neu berechnen.
    clear_advisory_report_cache()
    return list_current_fx_rates(db=db, current_user=current_user)
