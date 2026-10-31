"""SUITABILITY-DETECTOR-AVAILABILITY-001: HouseMatrix-Cap-Pruefung mit
explizitem Verfuegbarkeits-Status.

Befund (Codex-Reproducer 2026-10-16, ``suitability_detector_matrix_
availability``): ``detect_suitability_mismatches`` uebersprang den Cap-Check
still, wenn keine aktuelle Optimizer-Policy existierte oder die HouseMatrix
fuer den Score-Bucket des Risikoprofils keine Zeile hatte. Das Ergebnis war
eine leere Warnungsliste -- fuer jeden Verbraucher (Beratungsprotokoll-
Vorlage, Advisory-Report Sektion 16 / PDF) also "geeignet" (fail-open).

Dieses Modul liefert stattdessen einen expliziten Status:

- ``ok``            -- Cap geprueft, eingehalten
- ``violation``     -- Cap geprueft, ueberschritten
- ``unavailable``   -- Cap NICHT pruefbar (mit Reason-Code); zaehlt NIE als
                       geeignet und erzeugt einen Berater-Hinweis
- ``not_applicable``-- keine aktive Soll-Allokation, nichts zu pruefen

Die Reason-Codes sind stabil (Audit-/UI-Vertrag); die Meldungstexte enthalten
bewusst "HouseMatrix-Cap" und "nicht pruefbar", damit bestehende Banner
(React ``MismatchBanner``, PDF ``_bp_mismatch_banner``) sie ohne Sonderlogik
als aktiven Hinweis zeigen.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

STATUS_OK = "ok"
STATUS_VIOLATION = "violation"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NOT_APPLICABLE = "not_applicable"

REASON_RISK_PROFILE_MISSING = "RISK_PROFILE_MISSING"
REASON_RISK_PROFILE_INCONSISTENT = "RISK_PROFILE_INCONSISTENT"
REASON_SUITABILITY_POLICY_MISSING = "SUITABILITY_POLICY_MISSING"
REASON_SCORE_BUCKET_MISSING = "SCORE_BUCKET_MISSING"
REASON_SCORE_BUCKET_AMBIGUOUS = "SCORE_BUCKET_AMBIGUOUS"
REASON_RISKY_FRACTION_MISSING = "RISKY_FRACTION_MISSING"

_UNAVAILABLE_PREFIX = "HouseMatrix-Cap nicht pruefbar"
_ADVISOR_ACTION = (
    "Eignung gilt als NICHT bestaetigt -- bitte vor Abgabe der Empfehlung "
    "klaeren."
)


@dataclass(frozen=True)
class SuitabilityCapCheck:
    status: str
    reason_code: str | None = None
    message: str | None = None
    score_bucket: int | None = None
    cap_bps: int | None = None
    profile_name: str | None = None
    risky_fraction_bps: int | None = None

    @property
    def counts_as_suitable(self) -> bool:
        """Nur ein erfolgreich geprueftes, eingehaltenes Cap ist "geeignet"."""
        return self.status == STATUS_OK

    @property
    def requires_advisor_attention(self) -> bool:
        return self.status in (STATUS_VIOLATION, STATUS_UNAVAILABLE)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["counts_as_suitable"] = self.counts_as_suitable
        return payload


def _unavailable(reason_code: str, detail: str, **extra) -> SuitabilityCapCheck:
    return SuitabilityCapCheck(
        status=STATUS_UNAVAILABLE,
        reason_code=reason_code,
        message=f"{_UNAVAILABLE_PREFIX} ({reason_code}): {detail} {_ADVISOR_ACTION}",
        **extra,
    )


def not_applicable() -> SuitabilityCapCheck:
    return SuitabilityCapCheck(status=STATUS_NOT_APPLICABLE)


@dataclass(frozen=True)
class HouseMatrixResolution:
    """Eindeutige Aufloesung einer HouseMatrix-Zeile fuer (Policy, Bucket).

    ``row`` ist nur gesetzt, wenn genau EINE aktive Zeile passt; sonst
    tragen ``reason_code``/``detail`` den Grund (fail-closed, nie
    ``.first()`` nach DB-Reihenfolge).
    """

    row: object | None
    reason_code: str | None = None
    detail: str | None = None
    score_bucket: int | None = None

    @property
    def available(self) -> bool:
        return self.row is not None


def resolve_house_matrix_row(
    db: Session,
    *,
    policy_id: str | None,
    score_bucket: int,
) -> HouseMatrixResolution:
    """Gemeinsame Bucket-Aufloesung fuer Suitability-Detektor, Depotcheck-
    Benchmark und Performance-Attribution."""
    from models.allocation import HouseMatrix, OptimizerPolicy

    bucket = int(score_bucket)
    policy = None
    if policy_id:
        policy = (
            db.query(OptimizerPolicy)
            .filter(OptimizerPolicy.id == policy_id)
            .first()
        )
    if policy is None:
        return HouseMatrixResolution(
            row=None,
            reason_code=REASON_SUITABILITY_POLICY_MISSING,
            detail="Keine Optimizer-Policy (HouseMatrix) hinterlegt.",
            score_bucket=bucket,
        )
    rows = (
        db.query(HouseMatrix)
        .filter(
            HouseMatrix.policy_id == policy.id,
            HouseMatrix.score_from <= bucket,
            HouseMatrix.score_to >= bucket,
            HouseMatrix.is_active == 1,
        )
        .all()
    )
    if not rows:
        return HouseMatrixResolution(
            row=None,
            reason_code=REASON_SCORE_BUCKET_MISSING,
            detail=(
                "Die HouseMatrix hat keine aktive Zeile fuer "
                f"Score-Bucket {bucket}."
            ),
            score_bucket=bucket,
        )
    if len(rows) > 1:
        return HouseMatrixResolution(
            row=None,
            reason_code=REASON_SCORE_BUCKET_AMBIGUOUS,
            detail=(
                f"Die HouseMatrix ist fuer Score-Bucket {bucket} mehrdeutig "
                "(ueberlappende aktive Zeilen)."
            ),
            score_bucket=bucket,
        )
    return HouseMatrixResolution(row=rows[0], score_bucket=bucket)


def resolve_house_matrix_for_assessment(
    db: Session,
    *,
    assessment,
    policy_id: str | None,
) -> HouseMatrixResolution:
    """Wie ``resolve_house_matrix_row``, inkl. override-bewusster
    Bucket-Herleitung aus dem Risikoprofil (fehlend/inkonsistent -> Grund)."""
    from services.risk_assessment_semantics import RiskAssessmentInputError
    from services.risk_matrix import score_bucket_from_assessment

    if assessment is None:
        return HouseMatrixResolution(
            row=None,
            reason_code=REASON_RISK_PROFILE_MISSING,
            detail="Kein aktuelles Risikoprofil erfasst.",
        )
    try:
        bucket = int(score_bucket_from_assessment(assessment))
    except RiskAssessmentInputError as exc:
        return HouseMatrixResolution(
            row=None,
            reason_code=REASON_RISK_PROFILE_INCONSISTENT,
            detail=f"Risikoprofil ist nicht konsistent herleitbar ({exc}).",
        )
    return resolve_house_matrix_row(db, policy_id=policy_id, score_bucket=bucket)


def evaluate_house_matrix_cap(
    db: Session,
    *,
    assessment,
    risky_fraction_bps: int | None,
) -> SuitabilityCapCheck:
    """Prueft den Risiko-Anteil einer aktiven Soll-Allokation gegen das Cap
    der aktuellen HouseMatrix fuer den (override-bewussten) Score-Bucket.

    Fail-closed: jede fehlende oder mehrdeutige Grundlage ergibt
    ``unavailable`` mit Reason-Code, niemals ``ok``.
    """
    from models.allocation import OptimizerPolicy

    policy = (
        db.query(OptimizerPolicy)
        .filter(OptimizerPolicy.is_current == 1)
        .first()
    )
    resolution = resolve_house_matrix_for_assessment(
        db,
        assessment=assessment,
        policy_id=getattr(policy, "id", None),
    )
    score_bucket = resolution.score_bucket
    if resolution.row is None:
        detail = resolution.detail
        if resolution.reason_code == REASON_RISK_PROFILE_MISSING:
            detail = (
                "Zur aktiven Soll-Allokation existiert kein aktuelles "
                "Risikoprofil."
            )
        return _unavailable(
            resolution.reason_code,
            detail,
            score_bucket=score_bucket,
            risky_fraction_bps=risky_fraction_bps,
        )
    hm = resolution.row
    cap_bps = int(hm.max_risky_fraction_bps)
    profile_name = str(hm.profile_name or "")

    if risky_fraction_bps is None:
        return _unavailable(
            REASON_RISKY_FRACTION_MISSING,
            "Der Risiko-Anteil der aktiven Soll-Allokation ist nicht erfasst.",
            score_bucket=score_bucket,
            cap_bps=cap_bps,
            profile_name=profile_name,
        )
    risky = int(risky_fraction_bps)
    if risky > cap_bps:
        return SuitabilityCapCheck(
            status=STATUS_VIOLATION,
            message=(
                f"Aktueller Risiko-Anteil {risky / 100:.1f} % "
                f"überschreitet HouseMatrix-Cap {cap_bps / 100:.1f} % "
                f"({profile_name})."
            ),
            score_bucket=score_bucket,
            cap_bps=cap_bps,
            profile_name=profile_name,
            risky_fraction_bps=risky,
        )
    return SuitabilityCapCheck(
        status=STATUS_OK,
        score_bucket=score_bucket,
        cap_bps=cap_bps,
        profile_name=profile_name,
        risky_fraction_bps=risky,
    )
