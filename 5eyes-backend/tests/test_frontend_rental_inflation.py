"""#84 FE-Verdrahtung: Checkbox 'Miete teuerungsindexiert' im Vermoegens-Modal.

Sichert, dass die Checkbox existiert, beim Speichern in payload.property_rental_
inflation_linked geht, beim Bearbeiten aus der Position gesetzt und bei neuer Position
zurueckgesetzt wird.
"""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html").read_text(encoding="utf-8")


def test_checkbox_present():
    assert 'id="maw-immo-rent-inflation"' in HTML


def test_save_maps_to_payload():
    assert "payload.property_rental_inflation_linked=getCheckboxValue('maw-immo-rent-inflation')?1:0;" in HTML


def test_edit_populates_from_position():
    assert "setCheckboxValue('maw-immo-rent-inflation',!!pos.property_rental_inflation_linked);" in HTML


def test_new_position_resets_checkbox():
    assert "setCheckboxValue('maw-immo-rent-inflation',false);" in HTML
