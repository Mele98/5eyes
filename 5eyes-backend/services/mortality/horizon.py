"""Deterministic mortality-derived horizon (Kontrollrunde 2026-09-19).

Kontrollrunde 2026-09-21/23 (Phase 1, Mortalitaetsmodell-Vereinheitlichung)
----------------------------------------------------------------------------
Ein Audit fand ZWEI unabhaengige, um bis zu 6 Jahre voneinander abweichende
Lebenserwartungs-Modelle im selben Bericht fuer denselben Mandanten:
services.planning_horizon (flach: Geburtsjahr + fixe Konstante 83/85 Jahre,
KEIN Alters-Bezug) und dieses Modul (BFS-2020-2022-Sterbetafel, alters-
bedingte Median-Restlebenserwartung). Das flache Modell unterschaetzt die
Restlaufzeit ausgerechnet bei aelteren Klienten am staerksten -- die
falsche Richtung fuer ein Entnahme-/Drawdown-Tool (laengerer Horizont =
konservativer, nie kuerzerer).

Phase 1 (diese Aenderung): expected_death_year_offset_from_mandate() nimmt
jetzt optional ein `client`-Objekt entgegen und deckt damit die beiden
Faehigkeiten ab, die services.planning_horizon bisher exklusiv hatte:
- Tagesgenaues Geburtsdatum (client.date_of_birth) statt nur
  mandate.client_birth_year (Jahresgenauigkeit) -- Bevorzugt, faellt aber
  weiterhin auf client_birth_year zurueck, wenn date_of_birth fehlt.
- Partner-Beruecksichtigung (client.partner_date_of_birth/
  partner_salutation) -- Haushalts-Horizont = das SPAETERE der beiden
  Sterbejahre (das Geld muss fuer den laenger lebenden Partner reichen),
  identisch zur bisherigen services.planning_horizon-Semantik.

Vollstaendig rueckwaertskompatibel: `client` defaultet auf None, jeder
bestehende Aufruf (services/portfolio_engine_payload.py,
services/mandate_model_inputs.py) verhaelt sich exakt wie vorher. Der
CH-Jurisdiktions-Gate bleibt unveraendert (siehe Kommentar unten) -- ein
Client-only-Aufruf OHNE Mandat (routers/clients.py hat einen solchen Pfad)
bleibt bewusst AUSSERHALB des Scopes dieser Funktion: ohne Mandat gibt es
keine jurisdiction, kein reference_year-Anker (mandate.opened_at) -- dieser
eine Aufrufer bleibt dauerhaft bei services.planning_horizon (siehe dortige
Kontrollrunde-2026-09-21-Analyse).

Vorgeschichte: services.optimizer.solver sampelte bisher pro Monte-Carlo-Pfad
ein STOCHASTISCHES Sterbealter (services.mortality.sampler.sample_age_at_death).
Nach dem simulierten Tod wurde der Cashflow eines Pfads auf 0 gesetzt, das
Vermoegen wuchs aber unveraendert weiter (Erbschafts-Fiktion). Fuer
outflow_stream/cashflow_in_year-Ziele ("reicht das Geld fuer die geplanten
Entnahmen") genuegt seither jeder fruehe simulierte Tod automatisch als
Zielerreichung -- ein Pfad der bei Jahr 2 "stirbt" endet zwangslaeufig
nicht-negativ, unabhaengig davon ob der Entnahmeplan tatsaechlich trug. Der
Zielerreichungs-Score im Report erklaerte diese Bedeutung nirgends.

User-Entscheid (Kontrollrunde 2026-09-19): die Sterbetafel dient dazu, einen
DEFAULT-Zeitpunkt zu liefern; der Berater kann ihn manuell verkuerzen/
verlaengern (Mandate.life_expectancy_year), und die Zielerreichung soll sich
mit diesem Zeitpunkt aendern (bis 70 vs. bis 100 -> unterschiedliches
Ergebnis). Das entspricht KEINER Pfad-individuellen Zufallsstreuung, sondern
EINEM einzigen, fuer alle Pfade identischen Horizont -- exakt das Modell, das
_expected_death_year_offset_from_mandate (services/portfolio_engine_payload.py)
fuer die Report-Chart-Markierung bereits nutzte, nur bisher nie an die
tatsaechliche Solver-Rechnung gekoppelt war (Divergenz Report vs. Rechnung).

Diese Datei ist die EINE Quelle fuer beide Konsumenten (Report-Anzeige UND
Solver-Rechnung), um genau diese Divergenz-Bugklasse zu vermeiden.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any


def mandate_reference_year(mandate) -> int:
    """Das Bewertungsjahr des Mandats: mandate.opened_at, sonst heute.

    Analog zum bereits gefixten Tax-Pfad (TAX-2,
    services/portfolio_engine_optimizer_integration.py::_build_tax_solver_kwargs):
    date.today() als alleinige Basis wuerde dasselbe Mandat an zwei
    verschiedenen Kalendertagen mit unterschiedlichem current_age neu
    berechnen, statt konsistent auf den Bewertungsstichtag des Mandats zu
    beziehen.
    """
    opened = str(getattr(mandate, "opened_at", "") or "").strip()
    if len(opened) >= 4 and opened[:4].isdigit():
        return int(opened[:4])
    return _date.today().year


def _normalize_bfs_sex(value: Any) -> str | None:
    """Bildet sowohl mandate.client_sex ("M"/"F") als auch
    client.salutation/partner_salutation ("Herr"/"Frau"-Freitext, siehe
    services.planning_horizon._is_male) auf das von BFS_2020_2022.qx()
    erwartete "M"/"F" ab. Unbekannt/leer -> None (kein Cutoff fuer diese
    Person statt einer geratenen Annahme)."""
    normalized = str(value or "").strip().casefold()
    if normalized in ("m", "herr") or normalized.startswith("herr "):
        return "M"
    if normalized in ("f", "w", "frau") or normalized.startswith("frau "):
        return "F"
    return None


def _bfs_death_age_offset(current_age: int, sex: str) -> int | None:
    """BFS-2020-2022 MEDIAN-Restlebenserwartung: kleinste Anzahl weiterer
    Jahre, bei der die kumulierte Ueberlebenswahrscheinlichkeit unter 50%
    faellt. None wenn current_age bereits >= der Tafel-Obergrenze liegt."""
    from services.mortality.bfs import BFS_2020_2022

    survival = 1.0
    for age_offset in range(BFS_2020_2022.max_age - current_age):
        q = BFS_2020_2022.qx(current_age + age_offset, sex)
        survival *= max(0.0, 1.0 - float(q))
        if survival < 0.5:
            return max(1, age_offset + 1)
    return None


def _person_birth_year_and_sex(
    *, date_of_birth: Any, salutation: Any, fallback_birth_year: Any,
    fallback_sex: Any,
) -> tuple[int | None, str | None]:
    """Tagesgenaues client.date_of_birth wird bevorzugt, faellt aber auf
    mandate.client_birth_year zurueck (Jahresgenauigkeit) -- identische
    Prioritaet wie services.planning_horizon._person_life_expectancy_year.
    Analog fuer salutation vs. client_sex."""
    birth_year = None
    dob = str(date_of_birth or "").strip()
    if len(dob) >= 4 and dob[:4].isdigit():
        birth_year = int(dob[:4])
    if birth_year is None:
        fb = int(fallback_birth_year or 0)
        birth_year = fb if fb > 0 else None

    sex = _normalize_bfs_sex(salutation)
    if sex is None:
        sex = _normalize_bfs_sex(fallback_sex)
    return birth_year, sex


def expected_death_year_offset_from_mandate(
    mandate, *, reference_year: int | None = None, client: Any = None,
) -> int | None:
    """Erwartete Jahre-ab-reference_year bis zum Tod, oder None (kein Cutoff).

    Prioritaet 1: mandate.life_expectancy_year (Berater-Override, absolutes
        Kalenderjahr) -- muss nach reference_year liegen.
    Prioritaet 2: BFS-2020-2022 MEDIAN-Restlebenserwartung (erstes Alter, bei
        dem die Ueberlebenswahrscheinlichkeit unter 50% faellt) fuer
        CH-Mandate mit gueltigem client_birth_year/client_sex (bzw., wenn
        `client` uebergeben wird, client.date_of_birth/salutation
        bevorzugt, siehe _person_birth_year_and_sex). Ist zusaetzlich ein
        Partner erfasst (client.partner_date_of_birth/partner_salutation),
        ist das Ergebnis das SPAETERE der beiden Sterbejahre (Haushalts-
        Horizont -- das Geld muss fuer den laenger lebenden Partner
        reichen, identische Semantik zu services.planning_horizon).
    Sonst: None (kein Cutoff -- konservativ unbefristeter Horizont).

    reference_year defaultet auf mandate_reference_year(mandate) wenn nicht
    explizit gesetzt. `client` ist optional und vollstaendig
    rueckwaertskompatibel (Default None: identisches Verhalten wie vor
    Kontrollrunde 2026-09-21).

    Wirft Exceptions durch statt sie zu verschlucken (Bugfix 2026-09-19: die
    vorherige Implementierung fing pauschal `except Exception: pass` und gab
    bei JEDEM Fehler still None zurueck -- fuer die reine Report-Anzeige ein
    akzeptabler konservativer Fallback, aber fuer den Solver-Pfad ein
    Fail-Open-Risiko, wenn ein aktiviertes, bereits validiertes
    Mortalitaets-Feature durch einen unerwarteten Fehler still auf
    "kein Cutoff" zurueckfaellt. Aufrufer, die den alten Report-Fallback
    wollen, faengen die Exception selbst (siehe portfolio_engine_payload.py).
    """
    if reference_year is None:
        reference_year = mandate_reference_year(mandate)

    life_expectancy_year = int(getattr(mandate, "life_expectancy_year", 0) or 0)
    if life_expectancy_year and life_expectancy_year > reference_year:
        return life_expectancy_year - reference_year

    jurisdiction = str(getattr(mandate, "jurisdiction", None) or "CH")
    if jurisdiction != "CH":
        return None

    fallback_birth_year = getattr(mandate, "client_birth_year", None)
    fallback_sex = getattr(mandate, "client_sex", None)

    primary_birth_year, primary_sex = _person_birth_year_and_sex(
        date_of_birth=getattr(client, "date_of_birth", None) if client is not None else None,
        salutation=getattr(client, "salutation", None) if client is not None else None,
        fallback_birth_year=fallback_birth_year,
        fallback_sex=fallback_sex,
    )

    offsets: list[int] = []
    if primary_birth_year is not None and primary_sex is not None:
        current_age = max(0, reference_year - primary_birth_year)
        offset = _bfs_death_age_offset(current_age, primary_sex)
        if offset is not None:
            offsets.append(offset)

    if client is not None:
        partner_birth_year, partner_sex = _person_birth_year_and_sex(
            date_of_birth=getattr(client, "partner_date_of_birth", None),
            salutation=getattr(client, "partner_salutation", None),
            fallback_birth_year=None,
            fallback_sex=None,
        )
        if partner_birth_year is not None and partner_sex is not None:
            partner_age = max(0, reference_year - partner_birth_year)
            partner_offset = _bfs_death_age_offset(partner_age, partner_sex)
            if partner_offset is not None:
                offsets.append(partner_offset)

    return max(offsets) if offsets else None
