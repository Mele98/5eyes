"""#84 FE-Verdrahtung: Checkbox 'Miete teuerungsindexiert' im Vermoegens-Modal.

Sichert, dass die Checkbox existiert, beim Speichern in payload.property_rental_
inflation_linked geht, beim Bearbeiten aus der Position gesetzt und bei neuer Position
zurueckgesetzt wird.
"""
from pathlib import Path
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile

HTML = read_monolith_bundle()


def test_checkbox_present():
    assert 'id="maw-immo-rent-inflation"' in HTML


def test_save_maps_to_payload():
    assert "payload.property_rental_inflation_linked=getCheckboxValue('maw-immo-rent-inflation')?1:0;" in HTML


def test_edit_populates_from_position():
    assert "setCheckboxValue('maw-immo-rent-inflation',!!pos.property_rental_inflation_linked);" in HTML


def test_new_position_resets_checkbox():
    assert "setCheckboxValue('maw-immo-rent-inflation',false);" in HTML
