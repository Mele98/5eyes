"""K2-Nachtrag 1 (Prüfbericht H-166, N-915-05/-07): reine Logik von
``advisor-guidance.js`` in Node gegen ein minimales DOM.

* N-915-05: Verzehr-Text richtet sich nach dem schwächsten negativen Verlauf
  (P90 vor P50 vor P10); ein Startwert 0 ist kein "aufgebraucht ab Startjahr".
* Kennzahl "Prognose": gleiche Logik (strikt < 0).
* N-915-07: keine Fachbegriffe "Manual"/"Attest" in der Oberfläche.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "advisor-guidance.js"

HARNESS = r"""
var EL={};
var document={readyState:'complete',addEventListener:function(){},
  getElementById:function(id){return EL[id]||null;},querySelector:function(){return null;},querySelectorAll:function(){return [];}};
var window={};
function monteCarloPayload(r){return r&&r.monte_carlo||null;}
function simulationPayload(r){return r&&r.simulation||null;}
"""


def _run(script: str):
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE.read_text(encoding="utf-8") + "\nvar F=window;\nconsole.log(JSON.stringify((function(){" + script + "})()));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        path = fh.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


L = ["2026", "2027", "2028", "2029", "2030"]


def test_median_negative_is_reported_even_if_p90_stays_positive():
    # Repro aus dem Prüfbericht: P50 ab 2029 negativ, P90 positiv.
    text = _run(f"return F.fanDepletionSentence({json.dumps(L)},[1,0,-1,-2,-3],[2,1,0.5,-0.5,-1],[3,3,3,3,2]);")
    assert "mittlerer Verlauf" in text and "ab 2029" in text and "1 von 10" not in text, text


def test_all_paths_negative_names_the_favourable_path():
    text = _run(f"return F.fanDepletionSentence({json.dumps(L)},[1,-1,-2,-3,-4],[2,1,-0.5,-1,-2],[3,2,1,-0.2,-0.5]);")
    assert text.startswith("Vermögen aufgebraucht ab 2028 (mittlerer Verlauf)") and "9 von 10" in text and "ab 2029" in text, text


def test_only_unfavourable_path_negative():
    text = _run(f"return F.fanDepletionSentence({json.dumps(L)},[1,0.5,0,-0.1,-0.4],[2,2,2,2,2],[3,3,3,3,3]);")
    assert text.startswith("Im ungünstigen Verlauf (1 von 10): Vermögen aufgebraucht ab 2029"), text


def test_start_value_zero_is_not_depletion_in_start_year():
    # Vermögensaufbau ab 0: nicht "aufgebraucht ab 2026", sondern Lücke ab dem ersten Jahr unter null.
    text = _run(f"return F.fanDepletionSentence({json.dumps(L)},[0,0,-0.2,-0.4,-0.6],[0,1,2,3,4],[0,2,4,6,8]);")
    assert "2026" not in text and text.startswith("Im ungünstigen Verlauf (1 von 10): Finanzierungslücke ab 2028"), text


def test_gegenprobe_positive_paths_have_no_text():
    assert _run(f"return F.fanDepletionSentence({json.dumps(L)},[1,1,1,1,1],[2,2,2,2,2],[3,3,3,3,3]);") == ""


def test_projection_tile_uses_strict_negative_and_start_value():
    out = _run("""
      EL['v']={previousElementSibling:{textContent:'Prognose Ende 2030'},title:''};
      var a=F.markProjectionDepletion('v',-1,{monte_carlo:{target_p50_series_rappen:[0,0,-5,-9,-12],year_labels:[2026,2027,2028,2029,2030]}});
      var la=EL['v'].previousElementSibling.textContent;
      EL['v'].previousElementSibling.textContent='Prognose';
      var b=F.markProjectionDepletion('v',-1,{monte_carlo:{target_p50_series_rappen:[9,5,1,-2,-4],year_labels:[2026,2027,2028,2029,2030]}});
      var lb=EL['v'].previousElementSibling.textContent;
      EL['v'].previousElementSibling.textContent='Prognose';
      var c=F.markProjectionDepletion('v',5,{});
      return {a:a,la:la,b:b,lb:lb,c:c,lc:EL['v'].previousElementSibling.textContent};""")
    assert out["a"] == "2028" and out["la"] == "Finanzierungslücke ab 2028", out
    assert out["b"] == "2029" and out["lb"] == "Vermögen aufgebraucht ab 2029", out
    assert out["c"] is None and out["lc"] == "Prognose", out


def test_ui_texts_without_technical_or_unusual_terms():
    src = MODULE.read_text(encoding="utf-8")
    assert "Quelle Manual" not in src and "Attest" not in src
    assert "Kurs geprüft (Quelle manuell, Datum heute)" in src
    assert "Einzelfreigabe mit Begründung" in src
    assert "Pensionierung:</span> <span" in src
