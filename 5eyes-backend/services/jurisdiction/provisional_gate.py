"""WP-Resolver (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Governance-Gate fuer provisorische (noch nicht IC-gepruefte)
Jurisdiktions-Referenzdaten.

Siehe models/allocation.py::CapitalMarketAssumption.status Docstring:
Kapitalmarkt-Zahlen fuer Nicht-CH-Jurisdiktionen duerfen NUR nach
IC-Freigabe (status == "committee_approved") in Kundendokumente
einfliessen. Dieses Modul stellt den Baustein bereit, der das durchsetzt --
das eigentliche Einbinden in Router/PDF-Generierung ist ein spaeteres,
noch nicht freigegebenes Arbeitspaket.

Rueckgabewert-Konvention (bewusste Design-Entscheidung dieses Arbeitspakets,
da die Aufgabenstellung hier explizit Wahlfreiheit einraeumt):
assert_jurisdiction_ready() gibt bool zurueck statt None -- `True` bedeutet
"is_provisional_preview", also: der Aufruf wurde nur durchgelassen, weil
allow_provisional_preview=True gesetzt war UND die Daten (noch) nicht
IC-geprueft sind (typischer Anwendungsfall: interne Vorschau/Draft-Ansicht
fuer den Berater, die deutlich als "provisorisch" zu kennzeichnen ist).
`False` bedeutet "keine Provisorik-Warnung notwendig" (CH ODER eine
bereits IC-gepruefte Nicht-CH-Zeile).
"""
from __future__ import annotations

from services.jurisdiction.exceptions import JurisdictionNotApprovedError

_COMMITTEE_APPROVED_STATUS = "committee_approved"


def assert_jurisdiction_ready(
    jurisdiction: str | None,
    cma,
    allow_provisional_preview: bool = False,
) -> bool:
    """Prueft, ob die CMA-Referenzdaten einer Jurisdiktion IC-freigegeben sind.

    - jurisdiction in (None, "CH"): IMMER kein Fehler, gibt False zurueck.
      CH ist im heutigen System implizit immer "approved" -- es gibt dort
      (noch) keine status-Spalten-Pflicht (Bestandszeilen wurden durch den
      WP1-Backfill zwar auf "committee_approved" gesetzt, aber der CH-Pfad
      soll unabhaengig vom Inhalt von cma.status NIE blockiert werden, um
      Constraint 1 [CH-Pfad byte-identisch] nicht zu verletzen).
    - andere jurisdiction, cma.status == "committee_approved": kein Fehler,
      gibt False zurueck.
    - andere jurisdiction, cma.status != "committee_approved":
        - allow_provisional_preview=False (Default): wirft
          JurisdictionNotApprovedError.
        - allow_provisional_preview=True: kein Fehler, gibt True zurueck
          (Signal "is_provisional_preview" fuer den Aufrufer, z.B. um eine
          "provisorisch/nicht IC-geprueft"-Warnung in der UI anzuzeigen).
    """
    if jurisdiction in (None, "CH"):
        return False

    status = getattr(cma, "status", None)
    if status == _COMMITTEE_APPROVED_STATUS:
        return False

    if not allow_provisional_preview:
        raise JurisdictionNotApprovedError(
            f"Jurisdiktion '{jurisdiction}': CMA-Status '{status}' ist nicht "
            f"'{_COMMITTEE_APPROVED_STATUS}' -- ohne IC-Freigabe darf diese "
            f"Jurisdiktion nicht verwendet werden (allow_provisional_preview=False)."
        )
    return True
