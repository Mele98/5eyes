"""Sprint U-33 (2026-06-06): CH->EU Wegzugsbesteuerung (Exit-Tax) Calculator.

WICHTIG: Dies ist KEIN Steuer-Berater-Ersatz. Die Berechnung ist eine
vereinfachte Schaetzung fuer Beratungsgespraeche. Berater MUSS bei
tatsaechlichem Wegzug Steuerberater und das EU-Eingangsland konsultieren.

Schweiz-Spezifika:
  - CH erhebt KEINE laufende Kapitalgewinnsteuer auf privates
    Vermoegen -> keine 'Exit-Tax' auf unrealisierte Aktien-Gewinne
  - Bei Wegzug: Steuerpflicht endet am Wegzugs-Datum (Brutto-Lohn)
  - Quellensteuer auf CH-Dividenden + CH-Real-Estate bleibt erhalten

EU-Eingangsland-Spezifika (Beispiele):
  - DE: § 6 AStG Wegzugsbesteuerung greift nur beim VERLASSEN der
    unbeschraenkten deutschen Steuerpflicht (Wegzug AUS Deutschland),
    bei wesentlichen Beteiligungen (>= 1% an Kapitalgesellschaft,
    >= 7 Jahre dort ansaessig). Fuer den CH->EU-Fall dieser Datei
    (Zuzug NACH DE, nie zuvor deutsch steuerpflichtig) daher NIEMALS
    einschlaegig -- kein DE-Exit-Tax-Posten in dieser Richtung.
  - DE: Marktwert bei Zuzug = neue Anschaffungskosten (Step-Up)
  - FR/IT/AT: aehnliche Step-Up-Regeln, aber Pruefung pro Land

Praxis-Schaetzung:
  - Bei Wegzug aus CH: NULL CH-Exit-Tax fuer privates Vermoegen
    (Beratungskunden-Realitaet, keine 'wesentlichen Beteiligungen')
  - Administrative Kosten ~CHF 5'000 (Steuerberater pro Land)
  - Doppelbesteuerung pro Asset-Class moeglich (Detail-Pruefung
    notwendig)
"""
from __future__ import annotations

from dataclasses import dataclass


# Default-Schaetzung fuer Wegzugs-Begleitkosten (CHF 5'000 in Rappen)
DEFAULT_ADMINISTRATIVE_COSTS_RAPPEN = 500_000

# Schwelle fuer 'wesentliche Beteiligung' DE-Wegzugsbesteuerung § 6 AStG
DE_SUBSTANTIAL_PARTICIPATION_PCT = 1.0

# Mindestaufenthalt in CH fuer Wegzugsbesteuerung in DE
DE_MIN_RESIDENCE_YEARS = 7

# EU-Laender mit klar dokumentierter Step-Up-Regel (vereinfacht)
EU_STEP_UP_COUNTRIES = frozenset({"DE", "FR", "IT", "AT", "ES", "PT", "NL", "BE"})


@dataclass(frozen=True)
class WegzugTaxEstimate:
    """Geschaetzte Wegzugsbesteuerung CH->EU.

    Alle Betraege in Rappen (1 CHF = 100 Rappen).
    """

    estimated_ch_exit_tax_rappen: int
    """Geschaetzte CH-Exit-Tax. Default 0 fuer privates Vermoegen ohne
    wesentliche Beteiligung."""

    estimated_target_country_first_year_tax_rappen: int
    """Geschaetzte Steuerbelastung im EU-Eingangsland fuer das erste
    Steuerjahr (laufende Vermoegens-/Kapital-Steuer, sehr grob)."""

    administrative_costs_rappen: int
    """Steuerberater-Honorar in beiden Laendern (default CHF 5'000)."""

    total_estimated_burden_rappen: int
    """Summe der 3 Posten."""

    target_country: str
    """ISO-2 Code des EU-Eingangslandes."""

    has_step_up_basis: bool
    """True wenn das Eingangsland eine dokumentierte Step-Up-Regel hat
    (= Marktwert bei Zuzug ist neue Anschaffungsbasis)."""

    notes: tuple[str, ...]
    """Berater-Hinweise pro Schaetzung (Pflicht-Verweis auf Steuerberater)."""

    def to_dict(self) -> dict:
        return {
            "estimated_ch_exit_tax_rappen": self.estimated_ch_exit_tax_rappen,
            "estimated_target_country_first_year_tax_rappen": self.estimated_target_country_first_year_tax_rappen,
            "administrative_costs_rappen": self.administrative_costs_rappen,
            "total_estimated_burden_rappen": self.total_estimated_burden_rappen,
            "target_country": self.target_country,
            "has_step_up_basis": self.has_step_up_basis,
            "notes": list(self.notes),
        }


def estimate_ch_eu_wegzug(
    *,
    wealth_rappen: int,
    target_country: str,
    unrealized_gains_rappen: int = 0,
    has_substantial_participation: bool = False,
    ch_residence_years: int = 0,
    target_country_annual_wealth_tax_bps: int = 0,
    administrative_costs_rappen: int = DEFAULT_ADMINISTRATIVE_COSTS_RAPPEN,
) -> WegzugTaxEstimate:
    """Schaetzt Wegzugsbesteuerung CH -> EU-Land.

    Args:
        wealth_rappen: Gesamtvermoegen vor Wegzug in Rappen
        target_country: ISO-2 Code (DE/FR/IT/AT/ES/PT/NL/BE/CH/...)
        unrealized_gains_rappen: unrealisierte Gewinne auf Aktien-Beteiligungen
        has_substantial_participation: True wenn Kunde wesentliche
            Beteiligung haelt (>= 1% an einer Kapitalgesellschaft)
        ch_residence_years: Anzahl Jahre in CH (relevant fuer DE-§-6-AStG)
        target_country_annual_wealth_tax_bps: jaehrliche Vermoegenssteuer
            im Eingangsland in bps (z.B. ES 100 = 1%)
        administrative_costs_rappen: Steuerberater-Honorar Default CHF 5'000

    Returns:
        WegzugTaxEstimate mit Posten + Notes + Step-Up-Flag.
    """
    target_country = target_country.strip().upper()
    notes: list[str] = []

    # CH-Exit-Tax: CH kennt fuer diese Richtung (Wegzug AUS der Schweiz)
    # KEINE Exit-Tax auf unrealisierte Gewinne aus Privatvermoegen -- das
    # gilt unabhaengig von Beteiligungshoehe/Aufenthaltsdauer, siehe
    # Modul-Docstring. IMMER 0 in dieser Funktion.
    #
    # WEGZUG-DIRECTION-001: fruehere Versionen berechneten hier faelschlich
    # eine "DE § 6 AStG Exit-Tax", ausgeloest durch ch_residence_years (Jahre
    # in der SCHWEIZ) bei Zuzug NACH DE. § 6 AStG greift jedoch nur, wenn die
    # UNBESCHRAENKTE DEUTSCHE Steuerpflicht endet -- also beim Wegzug AUS
    # Deutschland, nie beim Zuzug. Eine Person, die von CH nach DE zieht, war
    # nie deutsch steuerpflichtig und kann § 6 AStG damit gar nicht ausloesen.
    # Diese Funktion modelliert ausschliesslich CH->EU (nie DE->X), daher gibt
    # es in dieser Richtung keinen gueltigen DE-Exit-Tax-Fall zu berechnen.
    ch_exit_tax = 0
    if has_substantial_participation:
        notes.append(
            "Wesentliche Beteiligung (>=1%) vorhanden: CH erhebt auch dafuer "
            "keine Exit-Tax beim Wegzug. § 6 AStG (DE-Wegzugsbesteuerung) "
            "greift nur beim Verlassen Deutschlands, nicht beim Zuzug -- "
            "fuer diesen CH->EU-Fall nicht einschlaegig. Pruefen: allfaellige "
            "EINGANGSSEITIGE Regeln des Zuziehlandes fuer wesentliche "
            "Beteiligungen mit dem dortigen Steuerberater."
        )

    # Eingangsland: jaehrliche Vermoegenssteuer (sehr grobe Schaetzung)
    target_annual = (wealth_rappen * target_country_annual_wealth_tax_bps) // 10000

    # Step-Up-Basis-Flag
    has_step_up = target_country in EU_STEP_UP_COUNTRIES
    if has_step_up:
        notes.append(
            f"{target_country}: Step-Up-Basis bei Zuzug — Marktwert wird "
            "neue Anschaffungsbasis fuer Kapitalgewinne."
        )
    else:
        notes.append(
            f"{target_country}: Step-Up-Regel nicht dokumentiert — "
            "Detail-Pruefung mit Steuerberater im Eingangsland erforderlich."
        )

    # Generische Pflicht-Verweise
    notes.append(
        "WICHTIG: Diese Schaetzung ersetzt KEINEN Steuerberater. "
        "Berater muss bei tatsaechlichem Wegzug Steuerberater "
        "in beiden Laendern konsultieren."
    )
    notes.append(
        "Quellensteuer auf CH-Dividenden + CH-Real-Estate bleibt nach "
        "Wegzug erhalten (keine Eliminierung durch Wegzug)."
    )

    total = int(ch_exit_tax) + int(target_annual) + int(administrative_costs_rappen)

    return WegzugTaxEstimate(
        estimated_ch_exit_tax_rappen=int(ch_exit_tax),
        estimated_target_country_first_year_tax_rappen=int(target_annual),
        administrative_costs_rappen=int(administrative_costs_rappen),
        total_estimated_burden_rappen=total,
        target_country=target_country,
        has_step_up_basis=has_step_up,
        notes=tuple(notes),
    )
