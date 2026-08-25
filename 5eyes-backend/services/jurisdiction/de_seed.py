"""Deutschland-Anbindung (2026-07-31, Entscheid Auftraggeber): idempotenter
Boot-Seed fuer die deutsche Jurisdiktion.

Legt EINE JurisdictionProfile-Zeile (code="DE") und die Home-Bias-Default-
Zeilen (models/jurisdiction.py::JurisdictionHomeBiasDefault) an -- eine
MECHANISCHE 1:1-Uebersetzung der heute hartcodierten CH-Splits in
services/portfolio_engine.py::_build_sub_allocations (eq_splits/bond_splits/
re_splits, verifiziert per Read vor Erstellung dieser Datei). Nur die Labels
sind uebersetzt (Schweiz->Deutschland, CHF->EUR); die relativen Gewichte
(split_bps) sind EXAKT identisch zu den CH-Werten -- es wird KEINE neue,
fuer Deutschland spezifische Zahl erfunden (harter Constraint des gesamten
Vorhabens). Alle Zeilen sind is_provisional=1: eine mechanisch gespiegelte
Heimatmarkt-Gewichtung ist eine sinnvolle, dokumentierte Startannahme, aber
keine vom Investment Committee fuer Deutschland spezifisch gepruefte
Entscheidung -- das Portfolio-Management kann die Werte spaeter (Admin-UI,
spaeteres Arbeitspaket) anpassen, ohne dass Code geaendert werden muss.

Betrifft NUR die Home-Bias-Strukturdaten. Echte Kapitalmarktannahmen (Renditen/
Volatilitaeten) fuer Deutschland kommen ausschliesslich ueber
services/jurisdiction/data_pipeline.py (echte Marktdaten, status="data_derived")
oder eine manuelle IC-Eingabe -- diese Datei erzeugt NIEMALS eine
CapitalMarketAssumption-Zeile.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database import new_uuid
from models.jurisdiction import JurisdictionHomeBiasDefault, JurisdictionProfile

DE_CODE = "DE"
SEEDED_BY = "system:de_jurisdiction_seed"

# Mechanische Label-Uebersetzung der heutigen CH-Sub-Asset-Class-Strings
# (services/portfolio_engine.py, verifiziert per Read: Zeile ~3844-3951).
# NUR Labels uebersetzt, KEINE Zahl veraendert.
_DE_EQUITIES_GEO: dict[str, list[tuple[str, int, str]]] = {
    "Deutschland Fokus": [
        ("Aktien Deutschland", 4500, "Mandatierter Deutschland-Fokus"),
        ("Aktien Global", 4000, "Globaler Kernbaustein"),
        ("Aktien Europa", 1000, "Europa-Diversifikation"),
        ("Aktien Schwellenlaender", 500, "Wachstumsbaustein"),
    ],
    "Global": [
        ("Aktien Global", 6500, "Globaler Kernbaustein"),
        ("Aktien Deutschland", 1500, "Heimmarkt-Anker"),
        ("Aktien Europa", 1000, "Europa-Diversifikation"),
        ("Aktien Schwellenlaender", 1000, "Wachstumsbaustein"),
    ],
    "Europa": [
        ("Aktien Europa", 4000, "Europa-Fokus gemaess Mandat"),
        ("Aktien Global", 2500, "Globaler Kernbaustein"),
        ("Aktien Deutschland", 2500, "Heimmarkt-Anker"),
        ("Aktien Schwellenlaender", 1000, "Wachstumsbaustein"),
    ],
    "Schwellenlaender": [
        ("Aktien Global", 4000, "Globaler Kernbaustein"),
        ("Aktien Deutschland", 2000, "Heimmarkt-Anker"),
        ("Aktien Europa", 1500, "Europa-Diversifikation"),
        ("Aktien Schwellenlaender", 2500, "Mandatierter EM-Fokus"),
    ],
}

_DE_BONDS_DURATION: dict[str, list[tuple[str, int, str]]] = {
    "Langfristig": [
        ("Obligationen EUR IG", 5500, "Langfristiger EUR-Kern"),
        ("Obligationen Global EUR-Hedged", 3500, "Globale Diversifikation"),
        ("Obligationen High Yield", 500, "Renditebeimischung"),
        ("Obligationen Emerging", 500, "Diversifikation"),
    ],
    "Kurzfristig": [
        ("Obligationen EUR IG", 7000, "Kurzfristige EUR-Qualitaet"),
        ("Obligationen Global EUR-Hedged", 2500, "Ergaenzende Diversifikation"),
        ("Obligationen High Yield", 300, "Renditebeimischung"),
        ("Obligationen Emerging", 200, "Diversifikation"),
    ],
    "Gemischt": [
        ("Obligationen EUR IG", 6000, "Gemischter EUR-Kern"),
        ("Obligationen Global EUR-Hedged", 3000, "Globale Diversifikation"),
        ("Obligationen High Yield", 500, "Renditebeimischung"),
        ("Obligationen Emerging", 500, "Diversifikation"),
    ],
}

_DE_REALESTATE_MARKET: dict[str, list[tuple[str, int, str]]] = {
    "Deutschland": [
        ("Immobilien Deutschland", 8000, "Deutscher Immobilienfokus"),
        ("Immobilien Global", 2000, "Ergaenzende Diversifikation"),
    ],
    "Ausland": [
        ("Immobilien Global", 7000, "Auslandsfokus fuer Immobilien"),
        ("Immobilien Deutschland", 3000, "Heimmarkt-Stabilisator"),
    ],
    "Gemischt": [
        ("Immobilien Deutschland", 5000, "Gemischter Immobilienbaustein"),
        ("Immobilien Global", 5000, "Gemischter Immobilienbaustein"),
    ],
}

# preference_key -> preference_value -> splits. Wird von
# services/jurisdiction/resolve.py::resolve_home_bias_defaults() gelesen.
DE_HOME_BIAS_DEFAULTS: dict[str, dict[str, list[tuple[str, int, str]]]] = {
    "equitiesGeo": _DE_EQUITIES_GEO,
    "bondsDuration": _DE_BONDS_DURATION,
    "realestateMarket": _DE_REALESTATE_MARKET,
}

# Der Default-Wert, den WP2 verwenden muss, wenn ein DE-Mandat kein
# equitiesGeo explizit gesetzt hat (Entscheid Auftraggeber: "jedes Land soll
# seinen eigenen Fokus haben, eigenen Home-Bias" -- analog zum CH-Default
# "Schweiz Fokus"). Zentral hier definiert, damit WP2 nicht erneut raten muss.
DE_DEFAULT_EQUITIES_GEO = "Deutschland Fokus"
DE_DEFAULT_BONDS_DURATION = "Langfristig"
DE_DEFAULT_REALESTATE_MARKET = "Deutschland"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_de_jurisdiction_seed(db: Session) -> None:
    """Idempotent: legt die DE-JurisdictionProfile-Zeile und alle Home-Bias-
    Default-Zeilen an, falls sie noch nicht existieren. Kann bei jedem Boot
    gefahrlos wiederholt aufgerufen werden (analog zu
    database.py::ensure_default_ch_jurisdiction) -- aendert nichts, wenn
    bereits vorhanden, und beruehrt NIE eine CH-Zeile."""
    now = _now()
    profile = db.query(JurisdictionProfile).filter(
        JurisdictionProfile.code == DE_CODE,
    ).first()
    if profile is None:
        db.add(JurisdictionProfile(
            id=new_uuid(),
            code=DE_CODE,
            display_name="Deutschland",
            home_currency="EUR",
            is_active=1,
            # Strukturell angebunden, aber die Home-Bias-Zahlen sind eine
            # mechanische CH-Spiegelung -- noch nicht vom Investment
            # Committee fuer Deutschland spezifisch geprueft.
            is_provisional=1,
            status="pending_ic_review",
            notes=(
                "Automatisch angelegt (Deutschland-Anbindung, 2026-07-31). "
                "Home-Bias-Defaults sind eine mechanische 1:1-Spiegelung der "
                "CH-Gewichte (nur Labels uebersetzt) -- noch nicht IC-geprueft."
            ),
            created_by=SEEDED_BY,
            created_at=now,
            updated_at=now,
        ))
        db.flush()

    existing_keys = {
        (row.preference_key, row.preference_value, row.sub_asset_class)
        for row in db.query(JurisdictionHomeBiasDefault).filter(
            JurisdictionHomeBiasDefault.jurisdiction_code == DE_CODE,
        ).all()
    }

    sort_order = 0
    for preference_key, variants in DE_HOME_BIAS_DEFAULTS.items():
        for preference_value, splits in variants.items():
            for sub_asset_class, split_bps, rationale in splits:
                sort_order += 1
                key = (preference_key, preference_value, sub_asset_class)
                if key in existing_keys:
                    continue
                db.add(JurisdictionHomeBiasDefault(
                    id=new_uuid(),
                    jurisdiction_code=DE_CODE,
                    preference_key=preference_key,
                    preference_value=preference_value,
                    sub_asset_class=sub_asset_class,
                    split_bps=split_bps,
                    rationale_text=rationale,
                    is_provisional=1,
                    sort_order=sort_order,
                    created_by=SEEDED_BY,
                    created_at=now,
                    updated_at=now,
                ))
    db.flush()
