"""Deterministic mortality-derived horizon (Kontrollrunde 2026-09-19).

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


def expected_death_year_offset_from_mandate(
    mandate, *, reference_year: int | None = None,
) -> int | None:
    """Erwartete Jahre-ab-reference_year bis zum Tod, oder None (kein Cutoff).

    Prioritaet 1: mandate.life_expectancy_year (Berater-Override, absolutes
        Kalenderjahr) -- muss nach reference_year liegen.
    Prioritaet 2: BFS-2020-2022 MEDIAN-Restlebenserwartung (erstes Alter, bei
        dem die Ueberlebenswahrscheinlichkeit unter 50% faellt) fuer
        CH-Mandate mit gueltigem client_birth_year/client_sex.
    Sonst: None (kein Cutoff -- konservativ unbefristeter Horizont).

    reference_year defaultet auf mandate_reference_year(mandate) wenn nicht
    explizit gesetzt.

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
    birth_year = int(getattr(mandate, "client_birth_year", 0) or 0)
    sex = str(getattr(mandate, "client_sex", "") or "")
    if jurisdiction != "CH" or not birth_year or sex not in ("M", "F"):
        return None

    from services.mortality.bfs import BFS_2020_2022

    current_age = max(0, reference_year - birth_year)
    survival = 1.0
    for age_offset in range(BFS_2020_2022.max_age - current_age):
        q = BFS_2020_2022.qx(current_age + age_offset, sex)
        survival *= max(0.0, 1.0 - float(q))
        if survival < 0.5:
            return max(1, age_offset + 1)
    return None
