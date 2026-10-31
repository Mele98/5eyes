"""COST-CONTEXT-001a: welcher Empfehlungslauf den Kostenausweis tragen darf.

CERT-COST-CONFLICT-001. Befund: `build_cost_disclosure()` waehlte den
Quelllauf rein nach `created_at.desc()`, ohne jeden Status-Filter.

Gemessen am Reproducer: ein spaeterer DRAFT mit Gebuehrenmodell 999 bps
verdraengte den zertifizierten FINAL-Lauf mit 25 bps als Grundlage des
FIDLEG-Dokuments -- das Dokument zeigte die Kosten eines Entwurfs, den
niemand freigegeben hat.

Zwei weitere Zustaende treffen dieselbe Abfrage, die der Reproducer nicht
nennt: `result_status` erlaubt laut CHECK-Constraint auch 'Rejected' und
'Superseded'. Ein ABGELEHNTER Lauf konnte damit die Kostengrundlage des
Kunden sein, ein durch einen neueren Final ERSETZTER ebenso.

Neue Regel -- Rangfolge statt Datum:

    'Final'      zertifiziert, erster Rang
    'Draft'      waehrend der Vorbereitung legitim, zweiter Rang
    'Rejected'   keine Quelle
    'Superseded' keine Quelle

Dieses Modul prueft die Rangfolge in beiden Richtungen: dass ein Final nicht
verdraengt wird, UND dass ein Draft weiterhin trAgt, wenn es keinen Final
gibt. Letzteres ist der Grund, warum hier keine blosse
`result_status == "Final"`-Bedingung steht: sie haette jedes Mandat in
Vorbereitung ohne Kostenausweis gelassen.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.mandates import Mandate  # noqa: E402
from services.cost_disclosure import build_cost_disclosure  # noqa: E402

# Dieselben Fixture-Helfer wie die Cluster-Reproducer -- kein zweiter
# Seeding-Pfad, der eigenstaendig driften kann.
from test_cert_cost_conflict_001_reproducers import (  # noqa: E402,F401
    _iso, _make_allocation, _make_policy, _make_position, _make_product,
    _make_run, _now, _seed_mandate, cc_session_factory,
)


def _setup(sf, *, suffix: str):
    advisor_id, client_id, mandate_id = _seed_mandate(sf, suffix=suffix)
    _make_product(sf, f"prd-{suffix}", ter_bps=50)
    _make_policy(sf, f"pol-{suffix}", advisor_id)
    _make_allocation(
        sf, f"ta-{suffix}", mandate_id, f"pol-{suffix}", advisor_id,
        advisory_wealth_rappen=1_000_000_00,
    )
    return advisor_id, client_id, mandate_id


def _add_run(sf, *, suffix, run_id, mandate_id, client_id, advisor_id,
             status, created_at, fee_bps):
    _make_run(
        sf, run_id, mandate_id, client_id,
        target_allocation_id=f"ta-{suffix}", policy_id=f"pol-{suffix}",
        created_by=advisor_id, result_status=status, created_at=created_at,
        fee_assumptions={"default_advisory_fee_bps": fee_bps},
    )
    _make_position(sf, run_id, f"prd-{suffix}", weight_bps=10000,
                   amount_rappen=1_000_000_00)


def _payload(sf, mandate_id):
    with sf() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        return build_cost_disclosure(db, mandate)


# ---------------------------------------------------------------------------
# Die Rangfolge
# ---------------------------------------------------------------------------


def test_final_wins_over_a_newer_draft(cc_session_factory):
    """Der gemessene Befund, mit dem Beweis am BETRAG statt nur an der ID.

    Der Reproducer prueft `source_run_id`. Dieser Test prueft zusaetzlich,
    dass auch die ZAHLEN aus dem Final kommen -- sonst waere ein Fix
    denkbar, der die richtige ID meldet und die Gebuehren des Entwurfs
    rechnet.
    """
    sf = cc_session_factory
    suffix = "sel-final"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    t0 = datetime.now(timezone.utc)
    _add_run(sf, suffix=suffix, run_id="run-final", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status="Final",
             created_at=_iso(t0), fee_bps=25)
    _add_run(sf, suffix=suffix, run_id="run-draft", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status="Draft",
             created_at=_iso(t0 + timedelta(minutes=5)), fee_bps=999)

    payload = _payload(sf, mandate_id)
    assert payload["source_run_id"] == "run-final"
    assert payload["source_run_status"] == "Final"

    rates = {
        item["key"]: item["rate_bps"]
        for item in payload["cost_items"]
        if item.get("rate_bps") is not None
    }
    assert rates.get("default_advisory_fee_bps") == 25, (
        f"Die Gebuehren stammen nicht aus dem Final-Lauf: {rates}"
    )


def test_draft_still_carries_the_disclosure_when_no_final_exists(cc_session_factory):
    """Gegenprobe -- und der Grund gegen eine blosse Final-Bedingung.

    Waehrend der Vorbereitung gibt es nur Entwuerfe. Sie auszuschliessen
    haette jedes Mandat in Arbeit ohne Kostenausweis gelassen; der Berater
    soll die Kosten VOR der Freigabe sehen.
    """
    sf = cc_session_factory
    suffix = "sel-draft"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    _add_run(sf, suffix=suffix, run_id="run-only-draft", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status="Draft",
             created_at=_now(), fee_bps=75)

    payload = _payload(sf, mandate_id)
    assert payload["data_pending"] is False
    assert payload["source_run_id"] == "run-only-draft"
    # Sichtbar vorlaeufig -- sonst ist er von einem freigegebenen nicht zu
    # unterscheiden.
    assert payload["source_run_status"] == "Draft"


def test_newest_final_wins_over_an_older_final(cc_session_factory):
    """Innerhalb desselben Rangs entscheidet weiterhin das Datum."""
    sf = cc_session_factory
    suffix = "sel-two-final"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    t0 = datetime.now(timezone.utc)
    _add_run(sf, suffix=suffix, run_id="run-final-old", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status="Final",
             created_at=_iso(t0), fee_bps=25)
    _add_run(sf, suffix=suffix, run_id="run-final-new", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status="Final",
             created_at=_iso(t0 + timedelta(hours=1)), fee_bps=30)

    payload = _payload(sf, mandate_id)
    assert payload["source_run_id"] == "run-final-new"


@pytest.mark.parametrize("dead_status", ["Rejected", "Superseded"])
def test_rejected_and_superseded_runs_are_no_source(cc_session_factory, dead_status):
    """Ein abgelehnter oder ersetzter Lauf ist keine Grundlage.

    Nicht im Reproducer, aber dieselbe Abfrage: beide Werte sind laut
    CHECK-Constraint erlaubt und waren per `created_at.desc()` erreichbar.
    """
    sf = cc_session_factory
    suffix = f"sel-{dead_status.lower()}"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    _add_run(sf, suffix=suffix, run_id=f"run-{suffix}", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status=dead_status,
             created_at=_now(), fee_bps=999)

    payload = _payload(sf, mandate_id)
    assert payload["data_pending"] is True, payload
    assert payload["source_run_id"] is None
    assert payload["cost_items"] == []
    # Die Begruendung muss den Zustand NENNEN -- "noch keine Empfehlung"
    # waere hier irrefuehrend, denn es gibt einen Lauf.
    assert any(dead_status in warning for warning in payload["warnings"]), (
        payload["warnings"]
    )


def test_dead_status_does_not_hide_an_existing_final(cc_session_factory):
    """Gegenprobe: ein abgelehnter NEUERER Lauf blockiert nicht.

    Ohne diesen Test waere eine Implementierung, die bei irgendeinem
    Rejected-Lauf auf pending geht, von den Tests oben nicht zu
    unterscheiden -- sie wuerde ein freigegebenes Mandat lahmlegen, weil
    daneben ein verworfener Entwurf liegt.
    """
    sf = cc_session_factory
    suffix = "sel-mixed"
    advisor_id, client_id, mandate_id = _setup(sf, suffix=suffix)
    t0 = datetime.now(timezone.utc)
    _add_run(sf, suffix=suffix, run_id="run-mixed-final", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status="Final",
             created_at=_iso(t0), fee_bps=25)
    _add_run(sf, suffix=suffix, run_id="run-mixed-rejected", mandate_id=mandate_id,
             client_id=client_id, advisor_id=advisor_id, status="Rejected",
             created_at=_iso(t0 + timedelta(minutes=5)), fee_bps=999)

    payload = _payload(sf, mandate_id)
    assert payload["data_pending"] is False
    assert payload["source_run_id"] == "run-mixed-final"


def test_mandate_without_any_run_keeps_its_own_reason(cc_session_factory):
    """"Gar kein Lauf" und "nur unbrauchbare Laeufe" sind verschiedene Lagen.

    Beide als "noch keine Empfehlung" zu melden waere irrefuehrend: im
    zweiten Fall GIBT es Laeufe, sie taugen nur nicht als Grundlage.
    """
    sf = cc_session_factory
    _advisor_id, _client_id, mandate_id = _setup(sf, suffix="sel-empty")

    payload = _payload(sf, mandate_id)
    assert payload["data_pending"] is True
    assert any(
        "Noch keine Portfolioempfehlung" in warning
        for warning in payload["warnings"]
    ), payload["warnings"]
    assert not any("Status" in warning for warning in payload["warnings"])
