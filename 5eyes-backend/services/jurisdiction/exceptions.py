"""WP-Resolver (Home-Bias/CMA-Parametrisierung pro Jurisdiktion, 2026-07-30):
Exceptions fuer die Jurisdiktions-Resolver in services/jurisdiction/resolve.py
und services/jurisdiction/provisional_gate.py.

Diese Exceptions werden bewusst NIRGENDS aus der bestehenden Engine
(services/portfolio_engine.py, services/cost_disclosure.py) geworfen oder
gefangen -- das Wiring ist ein spaeteres Arbeitspaket (WP2).
"""
from __future__ import annotations


class JurisdictionReferenceDataMissingError(ValueError):
    """Fuer eine Jurisdiktion existieren KEINE Referenzdaten (CMA-Zeile
    oder Building-Block-Zeilen). Wird geworfen statt eine erfundene Zahl
    oder None zurueckzugeben (harte Vorgabe des Arbeitspakets)."""


class JurisdictionNotApprovedError(Exception):
    """Fuer eine Jurisdiktion existieren Referenzdaten, aber ihr Status ist
    nicht 'committee_approved' -- und der Aufrufer verlangt entweder
    require_committee_approved=True (resolve.py) oder hat
    allow_provisional_preview nicht gesetzt (provisional_gate.py)."""


class JurisdictionReferenceDataConflictError(ValueError):
    """Mehrere aktive Referenzzeilen machen die Modellauswahl mehrdeutig."""


class CMAValidityWindowError(ValueError):
    """CMA-EFFECTIVE-DATE-001: eine neu zu aktivierende CMA-Version waere am
    Aktivierungstag nicht wirksam (kuenftiges valid_from, bereits abgelaufenes
    valid_until oder unlesbares Datum). Solange koexistierende Versionen nicht
    gebaut sind, wuerde die Aktivierung die Vorgaengerin abloesen und bis zum
    Stichtag jede Allokation sperren -- deshalb wird sie abgelehnt."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
