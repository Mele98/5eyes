"""COST-CONTEXT-001b: der Kostenausweis eines zertifizierten Laufs ist fest.

CERT-COST-CONFLICT-001. Befund: `build_cost_disclosure()` rechnete bei JEDEM
Aufruf neu und las dabei live `Product.ter_bps`. Eine spaetere TER-Korrektur
-- ohne jeden neuen Lauf -- aenderte damit die Totale eines bereits
FINALISIERTEN Laufs rueckwirkend. Ein nach FIDLEG Art. 8/9 ausgehaendigtes
Dokument war nicht reproduzierbar: wer es nachrechnet, bekommt andere Zahlen
als der Kunde gesehen hat.

Loesung: `finalize_recommendation()` friert den vollen Payload samt SHA-256
auf `RecommendationRun.cost_disclosure_snapshot_json` ein; der Leser gibt ihn
zurueck statt neu zu rechnen.

Dieses Modul prueft die Raender, die der Cluster-Reproducer nicht abdeckt:
die Integritaetspruefung des Hashes, die Offenlegung bei fehlendem Snapshot,
und dass das Einfrieren den richtigen Lauf trifft.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.mandates import Mandate  # noqa: E402
from models.review import Product, RecommendationPosition, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from services.cost_disclosure import (  # noqa: E402
    REASON_SNAPSHOT_HASH_MISMATCH,
    REASON_SNAPSHOT_MALFORMED,
    build_cost_disclosure,
    cost_disclosure_content_hash,
    load_frozen_cost_disclosure,
)
from routers.review import finalize_recommendation  # noqa: E402

from test_finalize_mandate_lock import (  # noqa: E402,F401
    _FakeRequest, _add_full_position, _allocation_policy_and_cma,
    _current_allocation_id, _make_run as _make_finalize_run,
)
from test_optimizer_shadow_mode import (  # noqa: E402,F401
    _seed_realistic_mandate, session_factory,
)


def _certified_mandate(session_factory, *, suffix: str):
    """Ein Mandat mit EINEM ueber die Produktionsstrecke zertifizierten Lauf."""
    advisor_id, _client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(session_factory, suffix=suffix)
    )
    allocation_id = _current_allocation_id(session_factory, mandate_id, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, allocation_id)
    run_id = _make_finalize_run(
        session_factory, mandate_id, allocation_id, assessment_id,
        advisor_id, policy, cma,
    )
    _add_full_position(session_factory, run_id)
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        advisor = db.query(User).filter(User.id == advisor_id).first()
        finalize_recommendation(
            mandate_id=mandate_id, run_id=run_id, request=_FakeRequest(),
            db=db, current_user=advisor,
        )
    return advisor_id, mandate_id, run_id


def _payload(session_factory, mandate_id):
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        return build_cost_disclosure(db, mandate)


def _snapshot_raw(session_factory, run_id) -> str | None:
    with session_factory() as db:
        return (
            db.query(RecommendationRun)
            .filter(RecommendationRun.id == run_id)
            .first()
            .cost_disclosure_snapshot_json
        )


# ---------------------------------------------------------------------------
# Einfrieren bei der Zertifizierung
# ---------------------------------------------------------------------------


def test_finalization_freezes_a_hashed_snapshot_on_the_run(session_factory):
    _advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix="frz-a")

    raw = _snapshot_raw(session_factory, run_id)
    assert raw, "Die Finalisierung hat keinen Nachweis eingefroren"
    envelope = json.loads(raw)
    assert envelope["recommendation_run_id"] == run_id
    assert envelope["schema_version"] >= 1
    assert envelope["frozen_at"]
    # Der Hash muss zum Inhalt passen -- sonst ist er Dekoration.
    # COST-SNAPSHOT-BINDING-001: V2 hasht den GANZEN Umschlag (Version,
    # Lauf-/Mandats-/TA-Bindung, frozen_at, Payload) -- nicht nur den Payload.
    assert envelope["content_hash"] == cost_disclosure_content_hash(
        {k: v for k, v in envelope.items() if k != "content_hash"}
    )
    assert envelope["content_hash"] != cost_disclosure_content_hash(envelope["payload"])
    # Der Snapshot zertifiziert den Status, den er traegt.
    assert envelope["payload"]["source_run_status"] == "Final"


def test_reader_returns_the_frozen_snapshot_and_says_so(session_factory):
    _advisor_id, mandate_id, _run_id = _certified_mandate(session_factory, suffix="frz-b")
    payload = _payload(session_factory, mandate_id)
    assert payload["evidence_frozen"] is True
    assert payload["content_hash"]
    assert payload["frozen_at"]


def test_frozen_totals_survive_a_later_fee_model_change(session_factory):
    """Nicht nur TER: auch eine Aenderung am Gebuehrenmodell darf nicht wirken.

    Der Cluster-Reproducer korrigiert `Product.ter_bps`. Das Einfrieren muss
    aber JEDEN spaeteren Live-Eingang abschirmen -- sonst waere es ein Fix
    fuer genau einen gemessenen Weg.
    """
    _advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix="frz-c")
    before = _payload(session_factory, mandate_id)

    with session_factory() as db:
        db.query(RecommendationRun).filter(RecommendationRun.id == run_id).update(
            {"fee_assumptions_json": json.dumps({"default_advisory_fee_bps": 9999})}
        )
        db.commit()

    after = _payload(session_factory, mandate_id)
    assert after["totals"] == before["totals"]
    assert after["content_hash"] == before["content_hash"]


# ---------------------------------------------------------------------------
# Integritaet: ein Nachweis, der nicht zu seinem Hash passt, ist keiner
# ---------------------------------------------------------------------------


def test_tampered_snapshot_is_refused_not_served(session_factory):
    """Fail-closed statt stiller Live-Neuberechnung.

    Waere der Leser bei kaputtem Hash auf die Live-Rechnung zurueckgefallen,
    haette er genau die Substitution gemacht, die dieser Nachweis verhindern
    soll -- und sie waere unsichtbar, weil die Zahlen plausibel aussehen.
    """
    _advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix="frz-d")

    raw = _snapshot_raw(session_factory, run_id)
    envelope = json.loads(raw)
    # Betrag manipulieren, Hash unveraendert lassen.
    envelope["payload"]["totals"]["annual_rappen"] = 1
    with session_factory() as db:
        db.query(RecommendationRun).filter(RecommendationRun.id == run_id).update(
            {"cost_disclosure_snapshot_json": json.dumps(envelope)}
        )
        db.commit()

    payload = _payload(session_factory, mandate_id)
    assert payload["data_pending"] is True, payload
    assert payload["cost_items"] == []
    assert any(
        REASON_SNAPSHOT_HASH_MISMATCH in warning for warning in payload["warnings"]
    ), payload["warnings"]


def test_malformed_snapshot_is_refused_with_its_own_reason(session_factory):
    _advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix="frz-e")
    with session_factory() as db:
        db.query(RecommendationRun).filter(RecommendationRun.id == run_id).update(
            {"cost_disclosure_snapshot_json": "{kaputt"}
        )
        db.commit()

    payload = _payload(session_factory, mandate_id)
    assert payload["data_pending"] is True
    assert any(
        REASON_SNAPSHOT_MALFORMED in warning for warning in payload["warnings"]
    ), payload["warnings"]


@pytest.mark.parametrize(
    "envelope",
    [
        {"content_hash": "x"},                      # kein payload
        {"payload": {"a": 1}},                      # kein hash
        {"payload": "nicht-dict", "content_hash": "x"},
        {"payload": {"a": 1}, "content_hash": 42},  # hash kein String
        ["kein", "dict"],
    ],
)
def test_structurally_incomplete_envelopes_are_malformed(envelope):
    run = type("Run", (), {"cost_disclosure_snapshot_json": json.dumps(envelope)})()
    payload, reason = load_frozen_cost_disclosure(run)
    assert payload is None
    assert reason == REASON_SNAPSHOT_MALFORMED


def test_absent_snapshot_is_not_an_error():
    """Gegenprobe: KEIN Snapshot ist ein eigener, harmloser Zustand.

    Ohne diese Unterscheidung wuerde jeder Entwurf -- und jeder Altlauf --
    wie ein manipulierter Nachweis behandelt und blockiert.
    """
    for value in (None, ""):
        run = type("Run", (), {"cost_disclosure_snapshot_json": value})()
        payload, reason = load_frozen_cost_disclosure(run)
        assert payload is None
        assert reason is None


# ---------------------------------------------------------------------------
# Offenlegung, wo nichts eingefroren ist
# ---------------------------------------------------------------------------


def test_final_run_without_snapshot_is_disclosed_as_unfrozen(session_factory):
    """Altlaeufe werden NICHT rueckwirkend eingefroren, sondern offengelegt.

    Rueckwirkend einzufrieren hiesse, heutige Zahlen als den damaligen
    Nachweis zu etikettieren -- eine erfundene Herkunft, schlimmer als die
    Drift, die sie verdecken wuerde.
    """
    _advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix="frz-f")
    with session_factory() as db:
        db.query(RecommendationRun).filter(RecommendationRun.id == run_id).update(
            {"cost_disclosure_snapshot_json": None}
        )
        db.commit()

    payload = _payload(session_factory, mandate_id)
    assert payload["data_pending"] is False, payload
    assert payload["evidence_frozen"] is False
    assert payload["content_hash"] is None
    assert any(
        "keinen eingefrorenen" in warning for warning in payload["warnings"]
    ), payload["warnings"]


def test_draft_based_disclosure_is_unfrozen_without_a_warning(session_factory):
    """Fuer einen Entwurf ist "nicht eingefroren" der richtige Zustand.

    Gegenprobe zum Test darueber: die Warnung gilt nur fuer einen
    FREIGEGEBENEN Lauf ohne Nachweis. Sie auch bei Entwuerfen zu zeigen
    waere Dauerrauschen in der normalen Vorbereitung.
    """
    advisor_id, _client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(session_factory, suffix="frz-g")
    )
    allocation_id = _current_allocation_id(session_factory, mandate_id, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, allocation_id)
    run_id = _make_finalize_run(
        session_factory, mandate_id, allocation_id, assessment_id,
        advisor_id, policy, cma,
    )
    _add_full_position(session_factory, run_id)
    # NICHT finalisiert -- bleibt Draft.

    payload = _payload(session_factory, mandate_id)
    assert payload["source_run_status"] == "Draft"
    assert payload["evidence_frozen"] is False
    assert not any(
        "keinen eingefrorenen" in warning for warning in payload["warnings"]
    ), payload["warnings"]


def test_freezing_binds_the_certified_run_not_a_later_draft(session_factory):
    """Der Snapshot gehoert dem Lauf, der zertifiziert wurde.

    Ein spaeterer Entwurf darf weder den Nachweis ueberschreiben noch beim
    Lesen vorgezogen werden (Rangfolge aus COST-CONTEXT-001a).
    """
    advisor_id, mandate_id, final_run_id = _certified_mandate(
        session_factory, suffix="frz-h"
    )
    frozen_before = _snapshot_raw(session_factory, final_run_id)

    allocation_id = _current_allocation_id(session_factory, mandate_id, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, allocation_id)
    with session_factory() as db:
        assessment_id = (
            db.query(RecommendationRun)
            .filter(RecommendationRun.id == final_run_id)
            .first()
            .assessment_id
        )
    draft_run_id = _make_finalize_run(
        session_factory, mandate_id, allocation_id, assessment_id,
        advisor_id, policy, cma,
    )
    _add_full_position(session_factory, draft_run_id)

    payload = _payload(session_factory, mandate_id)
    assert payload["source_run_id"] == final_run_id
    assert payload["evidence_frozen"] is True
    assert _snapshot_raw(session_factory, final_run_id) == frozen_before
    assert _snapshot_raw(session_factory, draft_run_id) is None
