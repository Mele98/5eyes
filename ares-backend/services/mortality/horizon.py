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
keine jurisdiction, kein Mandats-Stichtag (Soll-Allokation) -- dieser
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
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:  # nur Annotation; zaehlt nicht als Laufzeit-Import (Ratsche)
    from config import RunContext


# MORTALITY-HORIZON-P80-LS-001 (CIO-Entscheid 2026-10-18), Version
# "2026-10-18.v1": Planungshorizont bei aktivierter Mortalitaets-Simulation
# (Mandate.use_mortality_simulation) = 80-%-Quantil der Lebensdauer, d.h.
# kleinstes t mit S(t) <= 1 - 0.80 = 0.20 -- nur 20 % der Personen (bzw.
# Paare) leben laenger als der Plan. Vorher: Median (50 % leben laenger), fuer
# einen Vermoegensverzehr die falsche, langlebigkeits-unterschaetzende
# Richtung. Bei einem Paar gilt das Quantil fuer den Tod der
# LETZTVERSTERBENDEN Person (joint-life last-survivor). Eine Aenderung dieses
# Werts ist ein Methodik-Entscheid (CIO/Data-Owner) und verlangt eine neue
# Version. Ein mandats-individuelles Quantil-Feld gibt es nicht; der
# Berater-Override bleibt Mandate.life_expectancy_year (absolutes Jahr).
# Ist die Mortalitaets-Simulation AUS, bleibt der bisherige Median-Pfad
# (inkl. "max der Einzel-Mediane" fuer Paare) unveraendert.
MORTALITY_PLANNING_QUANTILE: float = 0.80
MORTALITY_PLANNING_QUANTILE_VERSION: str = "2026-10-18.v1"


def mandate_reference_year(mandate) -> int:
    """Das Bewertungsjahr des Laufs (t = 0 der Steuer-, Alters- und
    Mortalitaetsachse).

    GOAL-AXIS-VALUATION-YEAR-001 (CIO-Entscheid a, konsistent zu ADR-2): das
    Jahr des gebundenen Bewertungsstichtags (``services.valuation_clock``),
    dieselbe Uhr wie Cashflow-, Ziel- und Reserve-Achse; Reload, Replay und
    Bericht lesen damit den gespeicherten Stichtag. Vorher galt
    ``mandate.opened_at``: bei einem Mandat aus einem Vorjahr lagen Steuerjahr,
    Alter und Sterbe-Cutoff um (Bewertungsjahr - Eroeffnungsjahr) Jahre
    versetzt zur Spalte t. ``mandate`` bleibt Parameter der Aufrufer-Signatur.
    """
    from services.valuation_clock import valuation_date

    return valuation_date().year


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
    run_context: RunContext | None = None,
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
        NUR bei Mandate.use_mortality_simulation AUS. Ist sie AN, gilt
        stattdessen MORTALITY_PLANNING_QUANTILE (80 %) der Lebensdauer, fuer
        Paare joint-life last-survivor, Partner auch via mandate.client
        (MORTALITY-HORIZON-P80-LS-001).
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

    # X2b: im Engine-Lauf kommt die Jurisdiktion aus dem RunContext
    # (== mandate.jurisdiction or "CH"); ausserhalb eines Laufs Fallback.
    if run_context is not None:
        jurisdiction = str(run_context.jurisdiction)
    else:
        jurisdiction = str(getattr(mandate, "jurisdiction", None) or "CH")
    if jurisdiction != "CH":
        return None

    if mortality_simulation_enabled(mandate):
        # MORTALITY-HORIZON-P80-LS-001: aktiviertes Feature -> 80-%-Quantil,
        # Paar als last survivor. Der Partner wird auch ohne explizites
        # `client`-Argument ueber mandate.client gelesen, damit Solver-Cutoff
        # (mandate_model_inputs), Report-Marker (portfolio_engine_payload) und
        # Projektionshorizont (portfolio_engine_mc_simulation) identisch sind.
        return _planning_quantile_offset(
            mandate, reference_year=reference_year,
            client=_resolve_client(mandate, client),
        )

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


MORTALITY_MODE_DISABLED = "disabled"
MORTALITY_MODE_FIXED_OVERRIDE = "fixed_override"
MORTALITY_MODE_PLANNING_QUANTILE = "planning_quantile"


def resolve_mortality_cutoff(
    mandate, *, reference_year: int | None = None, client: Any = None,
    run_context: RunContext | None = None,
) -> tuple[str, int | None]:
    """MORT-CHANNEL-001 (Codex-Review PR #644, Vertrag 2): EINE Entscheidung
    ueber den Mortalitaets-Cutoff fuer alle Consumer.

    Rueckgabe ``(mode, offset_years)``:

    * ``("disabled", None)`` -- Mortalitaets-Simulation aus. Der Solver
      (``mortality_solver_kwargs_from_mandate`` -> ``{}``) wendet dann KEINE
      Todesmaske an; deterministische Zielanalyse, Report-MC, API und PDF
      duerfen deshalb ebenfalls keinen Cutoff anwenden -- auch nicht den
      BFS-Median oder einen gepflegten ``life_expectancy_year``. Frueher
      schnitt die Report-Zielanalyse hier am Median ab (zwei Modelle fuer
      denselben Mandatszustand).
    * ``("fixed_override", n)`` -- aktiviert, Berater-Vorgabe
      ``life_expectancy_year``.
    * ``("planning_quantile", n | None)`` -- aktiviert, 80-%-Quantil /
      Last-Survivor (MORTALITY-HORIZON-P80-LS-001).

    Der Offset ist exakt der Wert, den der Solver als
    ``mortality_fixed_offset_years`` erhaelt (gleicher Resolver, Partner via
    ``mandate.client``). Fehler propagieren (Solver-Semantik); Report-
    Aufrufer fangen sie selbst.
    """
    if not mortality_simulation_enabled(mandate):
        return MORTALITY_MODE_DISABLED, None
    if reference_year is None:
        reference_year = mandate_reference_year(mandate)
    offset = expected_death_year_offset_from_mandate(
        mandate, reference_year=reference_year,
        client=_resolve_client(mandate, client), run_context=run_context,
    )
    life_expectancy_year = int(getattr(mandate, "life_expectancy_year", 0) or 0)
    if life_expectancy_year and life_expectancy_year > reference_year:
        return MORTALITY_MODE_FIXED_OVERRIDE, offset
    return MORTALITY_MODE_PLANNING_QUANTILE, offset


def mortality_simulation_enabled(mandate) -> bool:
    """True nur fuer den exakt persistierten Ein-Wert (1/True), identisch zur
    True-Branch von services.mandate_model_inputs._feature_enabled. Alles
    andere behaelt das unveraenderte Legacy-Verhalten; die fail-closed-
    Validierung ungueltiger Werte bleibt in mandate_model_inputs."""
    value = getattr(mandate, "use_mortality_simulation", 0)
    return value is True or (type(value) is int and value == 1)


def _resolve_client(mandate, client: Any) -> Any:
    return client if client is not None else getattr(mandate, "client", None)


def person_survival_curve(current_age: int, sex: str) -> list[float]:
    """Diskrete Ueberlebensfunktion S(t), t = 0..(max_age - current_age + 1).

    S(0) = 1, S(t) = prod_{k<t} (1 - q(current_age + k)). Der letzte Punkt
    liegt nach der Schluss-Tafel (q(max_age) = 1) und ist damit 0 -- jedes
    Quantil existiert also innerhalb der Kurve."""
    from services.mortality.bfs import BFS_2020_2022

    max_age = int(BFS_2020_2022.max_age)
    age = max(0, min(int(current_age), max_age))
    survival = [1.0]
    for k in range(max_age - age + 1):
        q = float(BFS_2020_2022.qx(age + k, sex))
        survival.append(survival[-1] * max(0.0, 1.0 - q))
    return survival


def last_survivor_survival(curves: Sequence[Sequence[float]]) -> list[float]:
    """Joint-life last-survivor: P(mindestens eine Person lebt in t).

    S_LS(t) = 1 - prod_i (1 - S_i(t)). ANNAHME: die Sterblichkeiten der
    Personen sind UNABHAENGIG (je Person die BFS-Periodentafel ihres
    Geschlechts; keine Paar-Abhaengigkeit wie gemeinsamer Lebensstil oder
    erhoehte Sterblichkeit nach Verwitwung modelliert). Kuerzere Kurven
    werden nach ihrem Ende mit 0 fortgesetzt."""
    if not curves:
        return []
    length = max(len(curve) for curve in curves)
    combined: list[float] = []
    for t in range(length):
        p_all_dead = 1.0
        for curve in curves:
            s = float(curve[t]) if t < len(curve) else 0.0
            p_all_dead *= 1.0 - s
        combined.append(1.0 - p_all_dead)
    return combined


def quantile_offset_from_survival(
    survival: Sequence[float], quantile: float = MORTALITY_PLANNING_QUANTILE,
) -> int:
    """Kleinstes t >= 1 mit S(t) <= 1 - quantile (Quantil der Lebensdauer).

    Erreicht die Kurve die Schwelle nie, ist das Ergebnis len(survival) --
    das erste Jahr nach dem letzten tabellierten Punkt (konservativ lang)."""
    threshold = 1.0 - float(quantile)
    for t in range(1, len(survival)):
        if float(survival[t]) <= threshold + 1e-12:
            return t
    return max(1, len(survival))


def _planning_persons(
    mandate, *, reference_year: int, client: Any,
) -> tuple[list[tuple[int, str]], bool]:
    """(Personen als (Alter, Geschlecht), partner_incomplete).

    partner_incomplete: es gibt Hinweise auf einen Partner (Name, Anrede oder
    Geburtsdatum), aber Geburtsjahr oder Geschlecht fehlen. Der Horizont
    faellt dann auf die Einzelperson zurueck (CIO-Entscheid) und das
    Reasoning sagt es (mortality_planning_horizon_note)."""
    persons: list[tuple[int, str]] = []
    primary_birth_year, primary_sex = _person_birth_year_and_sex(
        date_of_birth=getattr(client, "date_of_birth", None) if client is not None else None,
        salutation=getattr(client, "salutation", None) if client is not None else None,
        fallback_birth_year=getattr(mandate, "client_birth_year", None),
        fallback_sex=getattr(mandate, "client_sex", None),
    )
    if primary_birth_year is not None and primary_sex is not None:
        persons.append((max(0, reference_year - primary_birth_year), primary_sex))

    partner_incomplete = False
    if client is not None:
        partner_birth_year, partner_sex = _person_birth_year_and_sex(
            date_of_birth=getattr(client, "partner_date_of_birth", None),
            salutation=getattr(client, "partner_salutation", None),
            fallback_birth_year=None,
            fallback_sex=None,
        )
        if partner_birth_year is not None and partner_sex is not None:
            persons.append((max(0, reference_year - partner_birth_year), partner_sex))
        else:
            partner_incomplete = any(
                str(getattr(client, field, None) or "").strip()
                for field in (
                    "partner_date_of_birth", "partner_salutation",
                    "partner_first_name", "partner_last_name",
                )
            )
    return persons, partner_incomplete


def _planning_quantile_offset(
    mandate, *, reference_year: int, client: Any,
) -> int | None:
    persons, _ = _planning_persons(
        mandate, reference_year=reference_year, client=client,
    )
    if not persons:
        return None
    curves = [person_survival_curve(age, sex) for age, sex in persons]
    return quantile_offset_from_survival(
        last_survivor_survival(curves), MORTALITY_PLANNING_QUANTILE,
    )


def mortality_planning_horizon_note(
    mandate, *, reference_year: int | None = None, client: Any = None,
) -> str | None:
    """Erklaerender Reasoning-Satz zum Mortalitaets-Horizont, oder None wenn
    die Mortalitaets-Simulation nicht aktiv ist (kein Cutoff, kein Hinweis)."""
    if not mortality_simulation_enabled(mandate):
        return None
    if reference_year is None:
        reference_year = mandate_reference_year(mandate)
    client = _resolve_client(mandate, client)
    offset = expected_death_year_offset_from_mandate(
        mandate, reference_year=reference_year, client=client,
    )
    consequence = (
        "Cashflows und Ausgabenziele enden danach; Vermoegensziele werden "
        "weiter bewertet."
    )
    if offset is None:
        return (
            "Mortalitaets-Horizont: keine Sterbetafel anwendbar -- kein "
            "Cutoff (unbefristeter Horizont)."
        )
    end_year = reference_year + offset
    life_expectancy_year = int(getattr(mandate, "life_expectancy_year", 0) or 0)
    if life_expectancy_year and life_expectancy_year > reference_year:
        return (
            f"Mortalitaets-Horizont bis {end_year}: Berater-Vorgabe "
            f"(Mandat-Lebenserwartung). {consequence}"
        )
    quantile_pct = int(round(MORTALITY_PLANNING_QUANTILE * 100))
    persons, partner_incomplete = _planning_persons(
        mandate, reference_year=reference_year, client=client,
    )
    if len(persons) >= 2:
        basis = (
            f"{quantile_pct}-%-Quantil bis zum Tod der Letztversterbenden "
            "Person des Paares (BFS 2020-2022, Unabhaengigkeitsannahme "
            "zwischen den beiden Sterblichkeiten)"
        )
    else:
        basis = (
            f"{quantile_pct}-%-Quantil der Lebensdauer, Einzelperson "
            "(BFS 2020-2022)"
        )
        if partner_incomplete:
            basis += (
                "; Partner erfasst, aber ohne vollstaendiges Geburtsdatum/"
                "Anrede -- Horizont ohne Partner gerechnet"
            )
    return (
        f"Mortalitaets-Horizont bis {end_year}: {basis} "
        f"[{MORTALITY_PLANNING_QUANTILE_VERSION}]. {consequence}"
    )


def life_expectancy_year_from_mandate(
    mandate, *, client: Any = None, reference_year: int | None = None,
) -> int | None:
    """Kontrollrunde 2026-09-23 (Phase 2, Mortalitaetsmodell-Vereinheitlichung):
    liefert dasselbe Rueckgabe-Format wie services.planning_horizon.
    life_expectancy_year_for() (absolutes Kalenderjahr statt Offset-ab-
    reference_year), damit interne Aufrufer, die bisher planning_horizon
    nutzten, per Drop-in auf die genauere BFS-Sterbetafel umgestellt werden
    koennen. Duenner Wrapper um expected_death_year_offset_from_mandate() --
    keine eigene Logik, kein Verhaltensunterschied ausser der Rueckgabeform."""
    if reference_year is None:
        reference_year = mandate_reference_year(mandate)
    offset = expected_death_year_offset_from_mandate(
        mandate, reference_year=reference_year, client=client,
    )
    return reference_year + offset if offset is not None else None
