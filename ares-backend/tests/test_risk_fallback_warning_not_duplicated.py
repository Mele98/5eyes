"""RISK-FALLBACK-WARNING-001 (Audit 2026-10-04, round 46, P2).

BEHOBEN am 2026-10-14.

Befund
------
Wenn die Stufe-3-Eskalation des Risikobudget-Fallbacks greift, wurde dieselbe
WARN_FALLBACK-Warnung ZWEIMAL an `warnings` angehaengt:

1. innerhalb der Stufe-3-Eskalation, direkt nachdem
   `_enforce_risk_budget(..., allow_best_effort=True)` die konservativste
   erreichbare Allokation zurueckgegeben hat;
2. unbedingt am Ende des GESAMTEN `except RiskBudgetExceeded:`-Blocks.

Die beiden liegen auf verschiedenen Einrueckungsebenen (20 bzw. 8), gehoeren
also zu verschiedenen Bloecken -- aber jeder Pfad, der (1) erreicht, laeuft
auch durch (2). Der Kommentar in der Stufe-4-Meldung sagte das sogar
ausdruecklich: "WARN_FALLBACK wird unten angefuegt". Der Append in der
Stufe-3-Eskalation war damit redundant.

Fix: der redundante Append ist ENTFERNT, nicht dedupliziert. Eine
Deduplizierung am Ende wuerde das doppelte Anhaengen weiter zulassen und nur
seine Folge verstecken. Die Stufe-3-spezifische BEGRUENDUNG im
Reasoning-Trail bleibt -- sie ist zusaetzliche Information, keine
Wiederholung.

Warum der urspruengliche Reproducer nichts gemessen hat
-------------------------------------------------------
Er baute ein Kapitalschutz-Mandat (Score 10) im `house_matrix`-Modus und
erwartete, dass dessen Bonds-Floor die Risky-Fraction strukturell ueber dem
Budget haelt. Nachgemessen am aktuellen Stand: dieses Szenario loest den
Fallback GAR NICHT mehr aus -- `result["warnings"]` ist leer, und der Test
scheiterte an seiner eigenen Vorbedingung ("Testszenario loest den
Risikobudget-Fallback nicht aus"), nicht am behaupteten Doppel-Append. Er war
also rot aus einem anderen Grund als dem dokumentierten; seine Roete war kein
Beleg fuer den Befund.

Auch das Szenario des Nachbar-Reproducers (RISK-FALLBACK-CONTEXT-001:
Aktienpraeferenz 7200 bps ueber einem 7000-bps-Cap) erreicht die Leiter
nicht: dort wird `_enforce_risk_budget` nachgemessen NIE aufgerufen, und
WARN_FALLBACK erscheint genau einmal. Beide Szenarien konnten den Defekt
strukturell nicht sehen.

Deshalb fahrt dieser Test die Eskalationsleiter jetzt DETERMINISTISCH an:
der innere und der aeussere `assert_risk_budget_ok` werfen je einmal (das
ist die EINTRITTSBEDINGUNG), und `_enforce_risk_budget` scheitert bei den
STRIKTEN Aufrufen (Stufe 1 und 2), waehrend der
`allow_best_effort`-Aufruf (Stufe 3) durchlaeuft.

Simuliert wird damit ausschliesslich der EINTRITT in die Leiter -- gemessen
wird, was die Stufe-3-Buchhaltung anhaengt, und das ist genau der Vertrag.
Dass die Leiter wirklich durchlaufen wird, prueft der Test selbst anhand der
beobachteten Aufrufreihenfolge; ohne diese Zusicherung koennte er gruen sein,
weil nichts passiert ist.

Gegenprobe gefahren: mit dem wieder eingesetzten Append meldet dieser Test
2 Warnungen, ohne ihn 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: F401
import models.client_login  # noqa: F401
import models.protocol_bausteine  # noqa: F401
configure_mappers()

from services import portfolio_engine
from services.portfolio_engine import generate_target_allocation
from services.risk_matrix import RiskBudgetExceeded

# Das Mandat/Policy/CMA-Setup des Nachbar-Reproducers wird wiederverwendet:
# es erzeugt nachweislich eine vollstaendig generierbare House-Matrix-
# Allokation, auf der die Leiter dann angefahren wird.
from test_risk_fallback_model_basis_active_method_mismatch import (  # noqa: E402,F401
    _prefs_for_equity,
    _seed_risk_cap_case,
    fast_monte_carlo,
    session_factory,
)


def _drive_escalation_to_stage_three(monkeypatch) -> list[str]:
    """Erzwingt den Eintritt in die Stufe-3-Eskalation.

    Gibt die beobachtete Aufrufreihenfolge zurueck, damit der Test belegen
    kann, dass die Leiter tatsaechlich durchlaufen wurde.
    """
    calls: list[str] = []
    real_enforce = portfolio_engine._enforce_risk_budget
    real_assert = portfolio_engine.assert_risk_budget_ok
    state = {"asserts": 0}

    def _assert(realized, budget, **kwargs):
        state["asserts"] += 1
        calls.append(f"assert#{state['asserts']}")
        # Aufruf 1 ist der AEUSSERE Budget-Check, Aufruf 2 der innere direkt
        # vor der Leiter. Beide muessen werfen, damit Stufe 1 ueberhaupt
        # betreten wird. Jeder spaetere Aufruf laeuft echt -- sonst wuerde der
        # Test auch einen Lauf durchlassen, der das Budget am Ende verletzt.
        if state["asserts"] <= 2:
            raise RiskBudgetExceeded(int(realized), int(budget))
        return real_assert(realized, budget, **kwargs)

    def _enforce(**kwargs):
        best_effort = bool(kwargs.get("allow_best_effort"))
        calls.append("enforce_best_effort" if best_effort else "enforce_strict")
        if not best_effort:
            # Stufe 1 und Stufe 2: strukturell unerreichbar.
            raise ValueError("strukturell unerreichbares Risikobudget (erzwungen)")
        return real_enforce(**kwargs)

    monkeypatch.setattr(portfolio_engine, "assert_risk_budget_ok", _assert)
    monkeypatch.setattr(portfolio_engine, "_enforce_risk_budget", _enforce)
    return calls


def test_fallback_warning_appears_exactly_once_when_structurally_unreachable(
    session_factory, monkeypatch
):
    """Stufe-3-Eskalation darf WARN_FALLBACK nur EINMAL anhaengen.

    Die Zahl ist kein Schoenheitsmerkmal: `warnings` ist die Liste, die der
    Berater in der Maske sieht und die in die Dokumentation geht. Dieselbe
    Warnung zweimal liest sich wie zwei Befunde.
    """
    monkeypatch.setattr(portfolio_engine.settings, "optimizer_mode", "house_matrix")
    calls = _drive_escalation_to_stage_three(monkeypatch)

    with session_factory() as session:
        mandate, _policy, _cma, _assessment = _seed_risk_cap_case(session)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=_prefs_for_equity(7200),
        )

    # Vorbedingung: die Leiter wurde wirklich bis Stufe 3 durchlaufen. Genau
    # diese Zusicherung fehlte dem urspruenglichen Reproducer -- er mass
    # nichts und war trotzdem rot.
    assert "enforce_best_effort" in calls, (
        f"Stufe-3-Eskalation nicht erreicht, Aufrufe: {calls}"
    )
    assert calls.count("enforce_strict") == 2, (
        f"Stufe 1 und 2 muessen beide versucht worden sein, Aufrufe: {calls}"
    )

    warnings = result.get("warnings") or []
    fallback_warnings = [w for w in warnings if w.get("code") == "WARN_FALLBACK"]

    assert fallback_warnings, (
        f"Der Fallback muss gewarnt haben -- warnings={warnings}"
    )
    assert len(fallback_warnings) == 1, (
        "WARN_FALLBACK darf nur EINMAL in den warnings erscheinen, nicht "
        f"{len(fallback_warnings)}x: {fallback_warnings}"
    )


def test_stage_three_still_explains_itself_in_the_reasoning_trail(
    session_factory, monkeypatch
):
    """Gegenprobe zum Fix: die Stufe-3-BEGRUENDUNG ist nicht mitentfernt.

    Entfernt wurde die doppelte Warnung, nicht die Information. Ohne diesen
    Test waere ein "Fix", der den ganzen Block loescht, nicht vom richtigen
    zu unterscheiden -- und der Berater wuesste nicht mehr, warum der
    Liquiditaetsanteil ueber dem SAA-Hard-Cap liegt.
    """
    monkeypatch.setattr(portfolio_engine.settings, "optimizer_mode", "house_matrix")
    _drive_escalation_to_stage_three(monkeypatch)

    with session_factory() as session:
        mandate, _policy, _cma, _assessment = _seed_risk_cap_case(session)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=_prefs_for_equity(7200),
        )

    reasoning = " ".join(result.get("reasoning") or [])
    assert "SAA-Hard-Cap" in reasoning, (
        "Die Stufe-3-Begruendung fehlt im Reasoning-Trail: "
        f"{result.get('reasoning')}"
    )
