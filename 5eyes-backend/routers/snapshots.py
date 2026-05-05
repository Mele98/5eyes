from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from services.audit import log
from services.auth import get_current_user, get_mandate_for_user_or_404
from models.snapshots import StrategySnapshot, AssetClassAnnualReturn
from models.mandates import Mandate
from models.users import User
from schemas.snapshots import StrategySnapshotCreate, StrategySnapshotResponse, DriftResult

router = APIRouter(prefix="/mandates/{mandate_id}/strategy-snapshots", tags=["snapshots"])

ASSET_CLASSES = ["Aktien", "Obligationen", "Immobilien", "Liquiditaet", "Alternative"]
SOLL_FIELDS = {
    "Aktien":       "soll_equities_bps",
    "Obligationen": "soll_bonds_bps",
    "Immobilien":   "soll_real_estate_bps",
    "Liquiditaet":  "soll_liquidity_bps",
    "Alternative":  "soll_alternatives_bps",
}
BAND_LO_FIELDS = {
    "Aktien":       "band_equities_lo_bps",
    "Obligationen": "band_bonds_lo_bps",
    "Immobilien":   "band_real_estate_lo_bps",
    "Liquiditaet":  "band_liquidity_lo_bps",
    "Alternative":  "band_alternatives_lo_bps",
}
BAND_HI_FIELDS = {
    "Aktien":       "band_equities_hi_bps",
    "Obligationen": "band_bonds_hi_bps",
    "Immobilien":   "band_real_estate_hi_bps",
    "Liquiditaet":  "band_liquidity_hi_bps",
    "Alternative":  "band_alternatives_hi_bps",
}

# Synthetische Benchmarks für Chart (Gewichte als Dezimalzahlen, Summe = 1.0)
SPI_PROXY = {"Aktien": 0.70, "Obligationen": 0.20, "Immobilien": 0.05, "Liquiditaet": 0.05, "Alternative": 0.00}
CONSERVATIVE_PROXY = {"Aktien": 0.20, "Obligationen": 0.55, "Immobilien": 0.15, "Liquiditaet": 0.10, "Alternative": 0.00}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_mandate(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


def _classify_status(ac: str, drifted_bps: dict, original_bps: dict, snapshot: StrategySnapshot) -> str:
    lo = getattr(snapshot, BAND_LO_FIELDS[ac])
    hi = getattr(snapshot, BAND_HI_FIELDS[ac])
    drifted_val = drifted_bps[ac]
    delta = drifted_val - original_bps[ac]
    if lo is None or hi is None:
        if abs(delta) <= 100:
            return "green"
        if abs(delta) <= 300:
            return "yellow"
        return "red"
    if lo <= drifted_val <= hi:
        return "green"
    band_width = hi - lo
    tolerance = max(200, round(band_width * 0.25))
    if (lo - tolerance) <= drifted_val <= (hi + tolerance):
        return "yellow"
    return "red"


@router.post("", response_model=StrategySnapshotResponse, status_code=201)
def create_snapshot(
    mandate_id: str,
    body: StrategySnapshotCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mandate = _get_mandate(mandate_id, db, current_user)
    now = _now()
    snap = StrategySnapshot(
        id=str(uuid4()),
        mandate_id=mandate_id,
        snapshot_date=body.snapshot_date,
        advisory_assets_rappen=body.advisory_assets_rappen,
        risk_profile_score=body.risk_profile_score,
        risk_profile_label=body.risk_profile_label,
        soll_equities_bps=body.soll_equities_bps,
        soll_bonds_bps=body.soll_bonds_bps,
        soll_real_estate_bps=body.soll_real_estate_bps,
        soll_liquidity_bps=body.soll_liquidity_bps,
        soll_alternatives_bps=body.soll_alternatives_bps,
        band_equities_lo_bps=body.band_equities_lo_bps,
        band_equities_hi_bps=body.band_equities_hi_bps,
        band_bonds_lo_bps=body.band_bonds_lo_bps,
        band_bonds_hi_bps=body.band_bonds_hi_bps,
        band_real_estate_lo_bps=body.band_real_estate_lo_bps,
        band_real_estate_hi_bps=body.band_real_estate_hi_bps,
        band_liquidity_lo_bps=body.band_liquidity_lo_bps,
        band_liquidity_hi_bps=body.band_liquidity_hi_bps,
        band_alternatives_lo_bps=body.band_alternatives_lo_bps,
        band_alternatives_hi_bps=body.band_alternatives_hi_bps,
        advisor_note=body.advisor_note,
        goals_summary_json=body.goals_summary_json,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(snap)
    log(
        db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        table_name="strategy_snapshots",
        record_id=snap.id,
        action="CREATE",
        mandate_id=mandate_id,
        client_id=mandate.client_id,
    )
    db.commit()
    db.refresh(snap)
    return snap


@router.get("", response_model=list[StrategySnapshotResponse])
def list_snapshots(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_mandate(mandate_id, db, current_user)
    return (
        db.query(StrategySnapshot)
        .filter(
            StrategySnapshot.mandate_id == mandate_id,
            StrategySnapshot.deleted_at.is_(None),
        )
        .order_by(StrategySnapshot.snapshot_date.desc())
        .all()
    )


@router.get("/latest/drift", response_model=DriftResult)
def get_drift(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_mandate(mandate_id, db, current_user)

    snapshot = (
        db.query(StrategySnapshot)
        .filter(
            StrategySnapshot.mandate_id == mandate_id,
            StrategySnapshot.deleted_at.is_(None),
        )
        .order_by(StrategySnapshot.snapshot_date.desc())
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="Kein Snapshot vorhanden")

    snapshot_year = int(snapshot.snapshot_date[:4])
    current_year = datetime.now(timezone.utc).year

    returns_rows = (
        db.query(AssetClassAnnualReturn)
        .filter(
            AssetClassAnnualReturn.year >= snapshot_year,
            AssetClassAnnualReturn.year < current_year,
        )
        .all()
    )

    # Jahres-Returns als Dict aufbauen
    returns_by_year: dict[int, dict[str, int]] = {}
    for row in returns_rows:
        if row.year not in returns_by_year:
            returns_by_year[row.year] = {}
        returns_by_year[row.year][row.asset_class] = row.return_bps

    has_drift_data = len(returns_by_year) > 0
    sorted_years = sorted(returns_by_year.keys())

    # Originale SOLL-Allokation
    original_bps = {ac: getattr(snapshot, SOLL_FIELDS[ac]) for ac in ASSET_CLASSES}

    # Theoretische Drift berechnen
    weights = {ac: original_bps[ac] / 10000.0 for ac in ASSET_CLASSES}
    for year in sorted_years:
        year_returns = returns_by_year[year]
        new_weights = {}
        for ac in ASSET_CLASSES:
            r = year_returns.get(ac, 0) / 10000.0
            new_weights[ac] = weights[ac] * (1 + r)
        total = sum(new_weights.values())
        weights = {ac: v / total for ac, v in new_weights.items()} if total > 0 else weights

    drifted_bps = {ac: round(weights[ac] * 10000) for ac in ASSET_CLASSES}
    delta_bps = {ac: drifted_bps[ac] - original_bps[ac] for ac in ASSET_CLASSES}

    # Bandgrenzen
    bands = {
        ac: {
            "lo": getattr(snapshot, BAND_LO_FIELDS[ac]),
            "hi": getattr(snapshot, BAND_HI_FIELDS[ac]),
        }
        for ac in ASSET_CLASSES
    }

    # Ampel-Status
    status = {ac: _classify_status(ac, drifted_bps, original_bps, snapshot) for ac in ASSET_CLASSES}

    # Chart: kumulierter Return, Startwert = 100
    # Y-Achse: index 0 = Snapshot-Jahr-Beginn, dann ein Wert pro Jahr
    chart_years = [snapshot_year] + sorted_years
    strat_weights = {ac: original_bps[ac] / 10000.0 for ac in ASSET_CLASSES}
    spi_weights = dict(SPI_PROXY)
    cons_weights = dict(CONSERVATIVE_PROXY)

    chart_strategy = [100.0]
    chart_spi = [100.0]
    chart_cons = [100.0]

    for year in sorted_years:
        yr = returns_by_year[year]

        def step(w):
            new_w = {ac: w.get(ac, 0.0) * (1 + yr.get(ac, 0) / 10000.0) for ac in ASSET_CLASSES}
            tot = sum(new_w.values())
            if tot > 0:
                new_w = {ac: v / tot for ac, v in new_w.items()}
            port_ret = sum(w.get(ac, 0.0) * yr.get(ac, 0) / 10000.0 for ac in ASSET_CLASSES)
            return new_w, port_ret

        strat_weights, r_s = step(strat_weights)
        spi_weights, r_p = step(spi_weights)
        cons_weights, r_c = step(cons_weights)

        chart_strategy.append(round(chart_strategy[-1] * (1 + r_s), 4))
        chart_spi.append(round(chart_spi[-1] * (1 + r_p), 4))
        chart_cons.append(round(chart_cons[-1] * (1 + r_c), 4))

    return DriftResult(
        snapshot_id=snapshot.id,
        snapshot_date=snapshot.snapshot_date,
        advisory_assets_rappen=snapshot.advisory_assets_rappen,
        risk_profile_label=snapshot.risk_profile_label,
        original=original_bps,
        drifted=drifted_bps,
        delta=delta_bps,
        bands=bands,
        status=status,
        chart_years=[str(y) for y in chart_years],
        chart_strategy=chart_strategy,
        chart_spi_proxy=chart_spi,
        chart_conservative=chart_cons,
        has_drift_data=has_drift_data,
    )
