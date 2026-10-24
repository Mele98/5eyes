"""Horizont-Altlabel: Frontend bildet Altlabels wie das Backend ab.

Die echten Funktionen des Monolithen laufen in Node gegen einen minimalen
DOM-Ersatz. Ein gespeichertes Altprofil wird beim Oeffnen auf die Option mit
denselben Jahren gesetzt wie im Backend (konservativ), insbesondere
"10 Jahre und mehr" -> "8 bis 11 Jahre" (9 Jahre) statt "Mehr als 12 Jahre"
(15 Jahre, aggressivster Matrixwert) -- sonst entsteht beim erneuten Speichern
still ein hoeherer Horizont.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.risk_scoring import HORIZON_YEARS
from tests.monolith_risk_js import DOM, NODE, monolith_js, run_node
from tests.risk_fixture_helpers import monolith_risk_questionnaire

pytestmark = pytest.mark.skipif(NODE is None, reason="node nicht verfuegbar")


@pytest.fixture(scope="module")
def questionnaire() -> dict:
    return monolith_risk_questionnaire()


# ── Horizont-Altlabel ───────────────────────────────────────────────────────────

def _frontend_selected_horizon_years(questionnaire, labels: list[str]) -> dict:
    script = monolith_js() + DOM + f"""
var texts = {json.dumps(questionnaire["options"]["rf-horizon"])};
var out = {{}};
{json.dumps(labels)}.forEach(function(label){{
  var sec = fakeSection(texts);
  // wie hydrateRiskQuestionnaire: Antwort zu Frage 8 inkl. Matrix-Suffix
  var hLabel = (label + ' · Matrix-Faktor').replace(' · Matrix-Faktor','').trim();
  selectRiskOptionByLabel(sec, hLabel);
  var idx = sec.opts.findIndex(function(o){{ return o.classList.contains('sel'); }});
  out[label] = idx < 0 ? null : RISK_HORIZON_OPTIONS[idx].years;
}});
process.stdout.write(JSON.stringify(out));
"""
    return json.loads(run_node(script))


def test_legacy_label_10_years_and_more_maps_conservatively_like_backend(questionnaire):
    selected = _frontend_selected_horizon_years(questionnaire, ["10 Jahre und mehr"])
    assert HORIZON_YEARS["10 Jahre und mehr"] == 9
    assert selected["10 Jahre und mehr"] == 9, (
        "Altlabel '10 Jahre und mehr' wird im Frontend auf "
        f"{selected['10 Jahre und mehr']} Jahre statt konservativ 9 Jahre gesetzt"
    )


def test_every_backend_horizon_label_selects_same_years_or_nothing(questionnaire):
    selected = _frontend_selected_horizon_years(questionnaire, sorted(HORIZON_YEARS))
    wrong = {label: (years, HORIZON_YEARS[label]) for label, years in selected.items()
             if years is not None and years != HORIZON_YEARS[label]}
    assert not wrong, f"Frontend waehlt andere Jahre als das Backend: {wrong}"
