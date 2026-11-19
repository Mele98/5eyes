"""Live-Test 2026-11 H4 -- "Portfolio generieren" erzeugte nichts Neues.

Befund: Nach dem Eingrenzen des Fonds-Universums (CH-Positivliste) lud
"Portfolio generieren" nur den bestehenden Vorschlag
(``GET .../recommendations/current/payload``), es gab KEIN
``POST .../recommendations/generate``; die Statuszeile meldete trotzdem
"Portfolio generiert: 23:20", gezeigt wurden weiter drei nicht gelistete
CHF-hedged-Produkte.

Freigabe-Workflow (services/recommendation_run_resolver.py, routers/review.py):
Entwuerfe ('Draft') werden bei jedem Lauf ersetzt, ein freigegebener
Vorschlag ('Final') hat Vorrang. Soll:
- Entwurf / kein Vorschlag -> echter Neulauf (POST generate) mit der
  gespeicherten Soll-Allokation und dem aktuellen Universum;
- freigegeben -> kein stilles Ueberschreiben, klare Meldung "Kein Neulauf".

Ausgefuehrt wird die echte Monolith-Funktion ``refreshPortfolioFromStoredState``.
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js

PRELUDE = """
var __calls=[], __status=[], __applied=null, __existing=null;
var strategyState={loading:false,dirty:false,recommendation:null};
function getActiveMandateId(){return 'm1';}
function isDemoMandateId(){return false;}
async function ensureStrategyReadyRiskForMandate(){return {risk:{id:'r1'}};}
function updateStrategyStatus(m,e){__status.push([String(m),!!e]);}
function setPortfolioRefreshButtonState(){}
async function loadCurrentAllocationResult(){return {target_allocation:{id:'ta1',preferences_json:'{}'},warnings:[]};}
async function loadCurrentRecommendationResult(){__calls.push('GET current');return __existing;}
function clearPendingStrategyOutputs(){}
function applyAllocationEngineResult(){return true;}
function recommendationPreferencesForStoredAllocation(){return null;}
function getInputValue(){return '';}
function applyRecommendationEngineResult(r){__applied=r;}
function hasVisibleStrategyOutputs(){return true;}
function invalidateStrategyOutputs(){}
function renderPortfolioRebalancingSummary(){}
function renderRecommendationWarnings(){}
function renderPortfolioSections(){}
function renderPortfolioNeutralState(){}
var API={post:async function(url,body){__calls.push('POST '+url+' ta='+body.target_allocation_id);return {run:{id:'new',result_status:'Draft'},positions:[]};}};
"""

RUN = """
  return refreshPortfolioFromStoredState().then(function(ok){
    return {ok:ok,calls:__calls,status:__status,applied:__applied&&__applied.run&&__applied.run.id};
  });
"""


def test_draft_proposal_is_regenerated_with_current_universe():
    out = run_js(("refreshPortfolioFromStoredState",),
                 "__existing={run:{id:'old',result_status:'Draft'},positions:[{}]};" + RUN,
                 prelude=PRELUDE)
    assert "POST /mandates/m1/recommendations/generate ta=ta1" in out["calls"], out
    assert out["applied"] == "new"
    last = out["status"][-1][0]
    assert "neu generiert" in last


def test_missing_proposal_is_generated():
    out = run_js(("refreshPortfolioFromStoredState",), "__existing=null;" + RUN, prelude=PRELUDE)
    assert any(c.startswith("POST /mandates/m1/recommendations/generate") for c in out["calls"])
    assert out["applied"] == "new"


def test_released_proposal_is_not_silently_overwritten_and_says_so():
    out = run_js(("refreshPortfolioFromStoredState",),
                 "__existing={run:{id:'final1',result_status:'Final'},positions:[{}]};" + RUN,
                 prelude=PRELUDE)
    assert not any(c.startswith("POST") for c in out["calls"]), out
    assert out["applied"] == "final1"
    last = out["status"][-1][0]
    assert "Kein Neulauf" in last and "freigegeben" in last
    assert "Portfolio generiert" not in last
