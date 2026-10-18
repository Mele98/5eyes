"""PRODUCT-CREATE-SUITABILITY-001: das Fondsuniversum-Formular sendete beim
Erfassen keine Risikoband-Einstufung. ProductCreate verlangt sie seit
CERT-PRODUCT-ELIGIBILITY-001 (suitability_profile_from/to, kein Default) --
jede Erfassung aus dem Formular scheiterte mit 422.

Die Tests fuehren die ECHTE adminCreateFund() aus dem Monolith in node aus und
validieren die gesendete Nutzlast gegen das ECHTE ProductCreate-Schema.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from schemas.review import ProductCreate
from tests.test_esg_premium_criteria import _extract_js_function, _html

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfuegbar")

_BASE_VALUES = {
    "pf-name": "Neuer Fonds", "pf-provider": "", "pf-product-type": "Fonds", "pf-asset-class": "Aktien",
    "pf-sub-asset-class": "Aktien Global", "pf-currency": "CHF", "pf-isin": "", "pf-symbol": "",
    "pf-ter": "", "pf-error": "", "pf-sfdr": "", "pf-esg-rating": "", "pf-esg-score": "",
    "pf-climate-benchmark": "",
}


def _run(values: dict, editing_id: str | None = None) -> dict:
    script = """
    var values = %s;
    var errBox = {style:{}, textContent:''};
    var document = {
      getElementById: function(id){ if (id === 'pf-error') return errBox; return id in values ? {value: values[id], style:{}} : null; },
      querySelectorAll: function(){ return []; }
    };
    var sent = null;
    var API = {
      post: function(path, payload){ sent = {method:'POST', path: path, payload: payload}; return Promise.resolve({id:'x'}); },
      put: function(path, payload){ sent = {method:'PUT', path: path, payload: payload}; return Promise.resolve({id:'x'}); }
    };
    var adminFundEditingId = %s;
    var adminProductUniverseState = {products: []};
    function adminPopulateProductUniverseProductSelect(){}
    function adminToggleFundCreateForm(){}
    function adminSearchFunds(){}
    function parseApiError(e){ return String(e); }
    %s
    adminCreateFund().then(function(){ process.stdout.write(JSON.stringify({sent: sent, error: errBox.textContent})); });
    """ % (json.dumps(values), json.dumps(editing_id), "async " + _extract_js_function(_html(), "adminCreateFund"))
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_form_has_suitability_inputs():
    html = _html()
    assert 'id="pf-suit-from"' in html and 'id="pf-suit-to"' in html


def test_create_payload_is_accepted_by_the_real_product_create_schema():
    result = _run({**_BASE_VALUES, "pf-suit-from": "2", "pf-suit-to": "6"})
    assert result["sent"]["method"] == "POST"
    payload = result["sent"]["payload"]
    assert (payload["suitability_profile_from"], payload["suitability_profile_to"]) == (2, 6)
    model = ProductCreate.model_validate(payload)  # vorher: ValidationError -> 422
    assert (model.suitability_profile_from, model.suitability_profile_to) == (2, 6)


@pytest.mark.parametrize("suit_from,suit_to", [("", ""), ("3", ""), ("0", "5"), ("4", "11"), ("7", "3"), ("2.5", "6")])
def test_create_without_valid_suitability_is_blocked_client_side(suit_from, suit_to):
    result = _run({**_BASE_VALUES, "pf-suit-from": suit_from, "pf-suit-to": suit_to})
    assert result["sent"] is None
    assert "Eignung" in result["error"]


def test_edit_does_not_send_suitability():
    result = _run({**_BASE_VALUES, "pf-suit-from": "", "pf-suit-to": ""}, editing_id="p1")
    assert result["sent"]["method"] == "PUT"
    assert "suitability_profile_from" not in result["sent"]["payload"]
