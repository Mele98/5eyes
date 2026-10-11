"""NS-BOND-SLEEVE-COLLAPSE-001 -- Laufzeit-Zuordnung und Referenzlaufzeit.

``services/rates/bond_duration.py`` traegt zwei Festlegungen, an denen der
Termstruktur-Tilt haengt:

* die **Referenzlaufzeit**, gegen die der Tilt gerechnet wird -- sie bestimmt,
  wann der Tilt null ist und damit, ob eine aktive Kurve das Niveau der
  CMA-Bond-Returns unangetastet laesst;
* die Uebersetzung der drei ``bondsDuration``-Werte in Kurvenpunkte.

Beides sind definitorische Festlegungen, keine Marktannahmen. Genau deshalb
gehoeren sie festgenagelt: sie sind unauffaellig aenderbar und wuerden
stillschweigend jede Obligationen-Rendite verschieben.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from services.cma_validation import NELSON_SIEGEL_DEFAULT_MATURITY_YEARS
from services.rates.bond_duration import (
    BOND_DURATION_MATURITY_YEARS,
    CMA_REFERENCE_MATURITY_YEARS,
    BondDurationError,
    resolve_bond_maturity_years,
)


def test_reference_is_the_maturity_the_code_already_used() -> None:
    """Die Referenz ist keine neue Annahme, sondern die bisher einzige gelesene.

    Vor dem Fix war ``NELSON_SIEGEL_DEFAULT_MATURITY_YEARS`` der einzige
    Kurvenpunkt, der ueberhaupt abgefragt wurde. Die Referenz darauf zu legen
    heisst: die implizite Annahme wird ausgesprochen, nicht ersetzt. Weicht
    sie eines Tages ab, ist das eine echte Modellaenderung und soll hier
    auffallen.
    """
    assert CMA_REFERENCE_MATURITY_YEARS == NELSON_SIEGEL_DEFAULT_MATURITY_YEARS


def test_mapping_covers_exactly_the_allowed_preference_values() -> None:
    """Die Zuordnung deckt genau die vom Schema erlaubten Werte ab.

    Laufen die beiden Mengen auseinander, gibt es entweder eine Praeferenz
    ohne Laufzeit (die dann fail-closed abbricht) oder eine Laufzeit ohne
    waehlbare Praeferenz (toter Code, der eine Abdeckung vortaeuscht).
    """
    from schemas.allocation import _VALID_ASSET_CLASS_CHOICES

    assert set(BOND_DURATION_MATURITY_YEARS) == set(
        _VALID_ASSET_CLASS_CHOICES["bondsDuration"]
    )


def test_mapping_is_ordered_and_contains_the_reference() -> None:
    """Kurz < mittel < lang, und der mittlere Punkt IST die Referenz.

    Letzteres ist die Eigenschaft, die "Gemischt" zum neutralen Fall macht --
    ein solches Mandat bekommt exakt keinen Termstruktur-Tilt.
    """
    short = BOND_DURATION_MATURITY_YEARS["Kurzfristig"]
    mixed = BOND_DURATION_MATURITY_YEARS["Gemischt"]
    long = BOND_DURATION_MATURITY_YEARS["Langfristig"]
    assert short < mixed < long
    assert mixed == CMA_REFERENCE_MATURITY_YEARS


def test_mapping_stays_within_conventional_bond_market_bands() -> None:
    """Die Punkte bleiben in den ueblichen Baendern (kurz 1-3, mittel 3-7, lang 7-15).

    Eine Schranke gegen stillen Drift ins Extreme: ein "Langfristig" von 30
    Jahren wuerde bei normal steigender Kurve einen deutlich groesseren
    positiven Tilt erzeugen, ohne dass sich an der Praeferenz des Kunden
    etwas geaendert haette.
    """
    assert 1.0 <= BOND_DURATION_MATURITY_YEARS["Kurzfristig"] <= 3.0
    assert 3.0 <= BOND_DURATION_MATURITY_YEARS["Gemischt"] <= 7.0
    assert 7.0 <= BOND_DURATION_MATURITY_YEARS["Langfristig"] <= 15.0


@pytest.mark.parametrize("preference", ["Kurzfristig", "Gemischt", "Langfristig"])
def test_resolve_returns_the_mapped_maturity(preference: str) -> None:
    assert resolve_bond_maturity_years(preference) == (
        BOND_DURATION_MATURITY_YEARS[preference]
    )


@pytest.mark.parametrize("preference", ["  Langfristig  ", "Kurzfristig "])
def test_resolve_trims_whitespace(preference: str) -> None:
    assert resolve_bond_maturity_years(preference) == (
        BOND_DURATION_MATURITY_YEARS[preference.strip()]
    )


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_absent_preference_resolves_to_the_neutral_reference(absent) -> None:
    """Keine Praeferenz heisst neutral, nicht "vorsichtshalber kurz".

    Es gibt keine sichere Laufzeit, die man hier annehmen koennte: jede Wahl
    ausser der Referenz unterstellt dem Mandat eine Termstruktur-Meinung, die
    niemand geaeussert hat. Der Tilt ist dann exakt 0 und das Mandat rechnet
    wie ohne NS-Bond-Anpassung.
    """
    assert resolve_bond_maturity_years(absent) == CMA_REFERENCE_MATURITY_YEARS


@pytest.mark.parametrize(
    "bad", ["kurzfristig", "Kurz", "Mittel", "Lang", "5", "Langfristigg"]
)
def test_unknown_preference_raises_instead_of_falling_back(bad: str) -> None:
    """Ein Tippfehler ist ein Fehler, nicht stillschweigend "keine Praeferenz".

    Sonst waere ein falsch geschriebener Wert von "nicht gesetzt" nicht
    unterscheidbar -- dieselbe Klasse stiller Normalisierung wie bei
    OPTIMIZER_GOAL_WEIGHTING vor CERT-OPTIMIZER-OBJECTIVE-001. Beachte, dass
    auch die Kleinschreibung abgelehnt wird: die Praeferenzwerte sind
    Schema-Enums, keine freie Eingabe.
    """
    with pytest.raises(BondDurationError, match="Laufzeitpraeferenz"):
        resolve_bond_maturity_years(bad)


def test_house_matrix_uses_the_same_preference_vocabulary() -> None:
    """Dieselben drei Werte, die der Sleeve-Mix bereits kennt.

    Der Sleeve-Mix in portfolio_engine_house_matrix.py verzweigt ueber genau
    diese Strings. Liefen die Vokabulare auseinander, wuerde dieselbe
    Praeferenz in einem Kanal wirken und im anderen abbrechen.
    """
    source = (
        BACKEND_ROOT / "services" / "portfolio_engine_house_matrix.py"
    ).read_text(encoding="utf-8")
    for preference in BOND_DURATION_MATURITY_YEARS:
        assert f'"{preference}"' in source, (
            f"{preference!r} kommt im Sleeve-Mix nicht vor"
        )
