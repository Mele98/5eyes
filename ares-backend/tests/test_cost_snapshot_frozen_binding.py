"""COST-SNAPSHOT-BINDING-001 (2026-10-21): eingefrorener FIDLEG-Kostennachweis
ist an Lauf, Schema-Version und Hash gebunden -- und ein ungueltiger
Final-Nachweis ist ein AUSGEWIESENER Fehler, nie ein stiller Live-Ersatz.

Teil 1 uebernimmt die drei Codex-Reproducer
(`docs/audits/reproducers/test_2026_10_14_cost_frozen_snapshot_adversarial_replay.py`
auf `codex/asset-allocation-stochastic-core`) als regulaere Tests ohne xfail.
Gegen develop 4105776 waren alle drei rot (`--runxfail`: 3 failed):

- Snapshot von Lauf A wurde fuer Lauf B akzeptiert (keine Run-Bindung);
- `schema_version=999` wurde wie V1 gelesen;
- AdvisoryLog ersetzte einen korrupten Final-Nachweis still durch heute live
  gerechnete Zahlen (mit eigenem, gueltigem Hash).

Teil 2 prueft die Konsumenten ueber die Produktionsstrecke: API-Payload,
Standalone-Kostenausweis-PDF (409), AdvisoryLog-Router (409), PDF-Komponente.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from services import cost_disclosure as cost_service  # noqa: E402
from services.advisory_log_service import (  # noqa: E402
    _build_cost_disclosure_snapshot,
)


# ---------------------------------------------------------------------------
# Teil 1: Codex-Reproducer (vormals strict xfail), unveraenderte Assertions
# ---------------------------------------------------------------------------


def _payload(*, run_id: str) -> dict:
    return {
        "data_pending": False,
        "is_complete": True,
        "currency": "CHF",
        "source_run_id": run_id,
        "source_run_status": "Final",
        "advisory_wealth_rappen": 10_000_000,
        "invested_amount_rappen": 9_500_000,
        "cost_items": [
            {
                "code": "advisory_fee",
                "label": "Beratungsgebuehr",
                "category": "service",
                "period": "annual",
                "amount_rappen": 25_000,
                "included_in_total": True,
            }
        ],
        "totals": {
            "one_time_rappen": 0,
            "annual_rappen": 25_000,
            "first_year_rappen": 25_000,
        },
        "warnings": [],
    }


def _envelope(*, payload: dict, run_id: str, schema_version: int = 1) -> str:
    return json.dumps(
        {
            "schema_version": schema_version,
            "frozen_at": "2026-10-13T18:12:00.000Z",
            "recommendation_run_id": run_id,
            "content_hash": cost_service.cost_disclosure_content_hash(payload),
            "payload": payload,
        },
        sort_keys=True,
    )


def test_frozen_snapshot_cannot_be_transplanted_to_another_run() -> None:
    """A valid snapshot from run A must not authenticate as evidence for B."""
    payload = _payload(run_id="run-a")
    run_b = SimpleNamespace(
        id="run-b",
        cost_disclosure_snapshot_json=_envelope(payload=payload, run_id="run-a"),
    )

    frozen, reason = cost_service.load_frozen_cost_disclosure(run_b)

    assert frozen is None
    assert reason == "snapshot_run_mismatch"


def test_unknown_snapshot_schema_version_is_rejected() -> None:
    """An unknown envelope version must fail closed, not be treated as V1."""
    payload = _payload(run_id="run-a")
    run = SimpleNamespace(
        id="run-a",
        cost_disclosure_snapshot_json=_envelope(
            payload=payload,
            run_id="run-a",
            schema_version=999,
        ),
    )

    frozen, reason = cost_service.load_frozen_cost_disclosure(run)

    assert frozen is None
    assert reason == "snapshot_schema_unsupported"


class _QueryReturning:
    def __init__(self, value) -> None:
        self.value = value

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.value


class _DbReturning:
    def __init__(self, value) -> None:
        self.value = value

    def query(self, _model):
        return _QueryReturning(self.value)


def test_advisory_log_must_not_replace_corrupt_final_evidence_with_live_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt named Final snapshot must not become a fresh live snapshot."""
    run = SimpleNamespace(
        id="run-final",
        mandate_id="mandate-a",
        result_status="Final",
    )
    live_payload = _payload(run_id="run-final")
    live_payload.update(
        evidence_frozen=False,
        content_hash=None,
        frozen_at=None,
    )

    monkeypatch.setattr(
        cost_service,
        "load_frozen_cost_disclosure",
        lambda _run: (None, "snapshot_hash_mismatch"),
    )
    monkeypatch.setattr(
        cost_service,
        "build_cost_disclosure_for_run",
        lambda *_args, **_kwargs: live_payload,
    )

    snapshot_json = _build_cost_disclosure_snapshot(
        _DbReturning(run),
        SimpleNamespace(id="mandate-a", base_currency="CHF"),
        recommendation_run_id="run-final",
    )

    # A named Final run with corrupt evidence must be rejected/blocked.  It
    # must never be silently substituted with numbers calculated today.
    assert snapshot_json is None


# ---------------------------------------------------------------------------
# Teil 1b: Leser-Raender (ohne DB)
# ---------------------------------------------------------------------------


def _v2_raw(*, run_id="run-a", mandate_id="m-a", ta_id="ta-a", **overrides) -> str:
    envelope = {
        "schema_version": 2,
        "frozen_at": "2026-10-21T08:00:00Z",
        "recommendation_run_id": run_id,
        "mandate_id": mandate_id,
        "target_allocation_id": ta_id,
        "payload": _payload(run_id=run_id),
    }
    envelope["content_hash"] = cost_service._envelope_hash_v2(envelope)
    envelope.update(overrides)
    return json.dumps(envelope)


def _run(raw, *, run_id="run-a", mandate_id="m-a", target_allocation_id="ta-a"):
    return SimpleNamespace(
        id=run_id, mandate_id=mandate_id, target_allocation_id=target_allocation_id,
        cost_disclosure_snapshot_json=raw,
    )


def test_valid_v2_envelope_is_certified():
    frozen, reason = cost_service.load_frozen_cost_disclosure(_run(_v2_raw()))
    assert reason is None
    assert frozen["evidence_status"] == "certified"
    assert frozen["evidence_frozen"] is True
    assert frozen["snapshot_schema_version"] == 2


def test_valid_v1_envelope_bound_to_its_run_stays_readable():
    """Gegenprobe: seit 2026-10-13 eingefrorene V1-Laeufe bleiben gueltig."""
    raw = _envelope(payload=_payload(run_id="run-a"), run_id="run-a")
    frozen, reason = cost_service.load_frozen_cost_disclosure(_run(raw))
    assert reason is None
    assert frozen["evidence_status"] == "certified"
    assert frozen["snapshot_schema_version"] == 1


@pytest.mark.parametrize("version", [0, 3, 999, "1", 1.0, True, None])
def test_any_non_supported_schema_version_is_unsupported(version):
    raw = json.loads(_envelope(payload=_payload(run_id="run-a"), run_id="run-a"))
    raw["schema_version"] = version
    frozen, reason = cost_service.load_frozen_cost_disclosure(_run(json.dumps(raw)))
    assert frozen is None
    assert reason == "snapshot_schema_unsupported"


def test_payload_run_id_mismatch_is_rejected_even_if_envelope_matches():
    """Envelope-Run-ID passt, Payload gehoert aber einem anderen Lauf."""
    raw = _envelope(payload=_payload(run_id="run-x"), run_id="run-a")
    frozen, reason = cost_service.load_frozen_cost_disclosure(_run(raw))
    assert frozen is None
    assert reason == "snapshot_run_mismatch"


@pytest.mark.parametrize("field,value", [
    ("frozen_at", "2020-01-01T00:00:00Z"),
    ("schema_version", 2),  # Kontrolle: unveraendert -> bleibt gueltig
])
def test_v2_hash_covers_envelope_metadata(field, value):
    envelope = json.loads(_v2_raw())
    envelope[field] = value
    frozen, reason = cost_service.load_frozen_cost_disclosure(_run(json.dumps(envelope)))
    if field == "schema_version":
        assert reason is None
    else:
        assert frozen is None
        assert reason == "snapshot_hash_mismatch"


@pytest.mark.parametrize("attr", ["mandate_id", "target_allocation_id"])
def test_v2_context_mismatch_is_rejected(attr):
    kwargs = {attr: "fremd"}
    frozen, reason = cost_service.load_frozen_cost_disclosure(_run(_v2_raw(), **kwargs))
    assert frozen is None
    assert reason == "snapshot_context_mismatch"


def test_kostenausweis_pdf_component_shows_blocked_error_not_pending():
    from io import BytesIO

    from pypdf import PdfReader
    from reportlab.platypus import SimpleDocTemplate

    from services.pdf.components.advisory_palette import PAGE_SIZE
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.components.kostenausweis import build_kostenausweis_flowables

    payload = cost_service.blocked_cost_disclosure_payload("snapshot_run_mismatch")
    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=PAGE_SIZE).build(
        build_kostenausweis_flowables(payload, make_advisory_styles())
    )
    text = " ".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(buffer.getvalue())).pages
    )
    text = " ".join(text.split())
    assert "Kostennachweis ung" in text, text
    assert "snapshot_run_mismatch" in text.replace(" ", "")
    assert "Daten ausstehend" not in text


# ---------------------------------------------------------------------------
# Teil 2: Produktionsstrecke (finalisierter Lauf, dann Snapshot verfaelscht)
# ---------------------------------------------------------------------------

from models.review import AdvisoryLog, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from schemas.review import AdvisoryLogCreate  # noqa: E402

from test_cost_disclosure_frozen_evidence import (  # noqa: E402
    _certified_mandate, _payload as _disclosure, _snapshot_raw,
)
from test_finalize_mandate_lock import _FakeRequest  # noqa: E402
from test_optimizer_shadow_mode import session_factory  # noqa: E402,F401


def _overwrite_snapshot(session_factory, run_id, raw):
    with session_factory() as db:
        db.query(RecommendationRun).filter(RecommendationRun.id == run_id).update(
            {"cost_disclosure_snapshot_json": raw}
        )
        db.commit()


def test_finalization_writes_a_bound_v2_envelope(session_factory):
    _advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix="bind-a")
    envelope = json.loads(_snapshot_raw(session_factory, run_id))
    assert envelope["schema_version"] == 2
    assert envelope["recommendation_run_id"] == run_id
    assert envelope["mandate_id"] == mandate_id
    assert envelope["target_allocation_id"]
    payload = _disclosure(session_factory, mandate_id)
    assert payload["evidence_status"] == "certified"
    assert payload["evidence_frozen"] is True


def _corrupt_unknown_version(session_factory, suffix):
    advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix=suffix)
    envelope = json.loads(_snapshot_raw(session_factory, run_id))
    envelope["schema_version"] = 999
    _overwrite_snapshot(session_factory, run_id, json.dumps(envelope))
    return advisor_id, mandate_id, run_id


def test_api_payload_reports_blocked_evidence_without_numbers(session_factory):
    _advisor_id, mandate_id, run_id = _corrupt_unknown_version(session_factory, "bind-b")
    payload = _disclosure(session_factory, mandate_id)
    assert payload["evidence_status"] == "blocked"
    assert payload["evidence_error"] == "snapshot_schema_unsupported"
    assert payload["audit_degraded"] is True
    assert payload["data_pending"] is True
    assert payload["cost_items"] == []
    assert payload["totals"]["first_year_rappen"] == 0
    assert payload["source_run_id"] == run_id
    # Pydantic-Vertrag laesst die neuen Felder durch.
    from schemas.cost_disclosure import CostDisclosureResponse
    dumped = CostDisclosureResponse(**payload).model_dump()
    assert dumped["evidence_status"] == "blocked"
    assert dumped["evidence_error"] == "snapshot_schema_unsupported"


def test_transplanted_snapshot_on_real_run_is_blocked(session_factory):
    """Snapshot eines anderen finalisierten Laufs in den aktuellen kopiert."""
    _a, _mandate_a, run_a = _certified_mandate(session_factory, suffix="bind-c1")
    _b, mandate_b, run_b = _certified_mandate(session_factory, suffix="bind-c2")
    _overwrite_snapshot(session_factory, run_b, _snapshot_raw(session_factory, run_a))
    payload = _disclosure(session_factory, mandate_b)
    assert payload["evidence_status"] == "blocked"
    assert payload["evidence_error"] == "snapshot_run_mismatch"
    assert payload["cost_items"] == []


def test_standalone_cost_pdf_refuses_blocked_evidence_with_own_reason(session_factory):
    from routers.pdf_reports import get_cost_disclosure_pdf

    advisor_id, mandate_id, _run_id = _corrupt_unknown_version(session_factory, "bind-d")
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        with pytest.raises(HTTPException) as exc_info:
            get_cost_disclosure_pdf(
                mandate_id=mandate_id, request=_FakeRequest(), db=db,
                current_user=advisor,
            )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reason_code"] == "COST_EVIDENCE_INVALID"
    assert exc_info.value.detail["evidence_error"] == "snapshot_schema_unsupported"


def _log_body(**overrides):
    defaults = dict(
        entry_type="Initialer Beratungsabschluss",
        title="Kostenbesprechung",
        description="Kostenausweis mit dem Kunden besprochen und erlaeutert.",
        entry_datetime="2026-10-21T09:00:00.000Z",
        duration_minutes=30,
        communication_channel="persoenlich",
        language="de",
        topics=["Kosten"],
        risk_warnings_given=[],
        cost_disclosure_given=True,
        conflict_disclosure_ids=[],
    )
    defaults.update(overrides)
    return AdvisoryLogCreate(**defaults)


@pytest.mark.parametrize("name_run", [True, False])
def test_advisory_log_with_corrupt_final_evidence_is_409_and_not_persisted(
    session_factory, name_run,
):
    from routers.review import create_advisory_log_entry

    advisor_id, mandate_id, run_id = _corrupt_unknown_version(
        session_factory, f"bind-e{int(name_run)}"
    )
    body = _log_body(recommendation_run_id=run_id if name_run else None)
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        with pytest.raises(HTTPException) as exc_info:
            create_advisory_log_entry(
                mandate_id=mandate_id, body=body, request=_FakeRequest(),
                db=db, current_user=advisor,
            )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reason_code"] == "COST_EVIDENCE_INVALID"
    assert exc_info.value.detail["evidence_error"] == "snapshot_schema_unsupported"
    with session_factory() as db:
        assert db.query(AdvisoryLog).filter(
            AdvisoryLog.mandate_id == mandate_id
        ).count() == 0


def test_advisory_log_with_valid_frozen_evidence_still_works(session_factory):
    """Gegenprobe: gueltiger Nachweis -> Protokoll mit eingefrorenen Zahlen."""
    from routers.review import create_advisory_log_entry

    advisor_id, mandate_id, run_id = _certified_mandate(session_factory, suffix="bind-f")
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        create_advisory_log_entry(
            mandate_id=mandate_id, body=_log_body(recommendation_run_id=run_id),
            request=_FakeRequest(), db=db, current_user=advisor,
        )
    with session_factory() as db:
        entry = db.query(AdvisoryLog).filter(AdvisoryLog.mandate_id == mandate_id).one()
        stored = json.loads(entry.cost_disclosure_snapshot_json)
    assert stored["evidence_frozen"] is True
    assert stored["recommendation_run_id"] == run_id


# ---------------------------------------------------------------------------
# Teil 3: ADVISORY-LOG-COST-RUN-BINDING (AUDIT-FIX 2026-10-31)
# ---------------------------------------------------------------------------
# Der React-Editor schickte den gezeigten Lauf als `cost_disclosure_snapshot_id`
# -- ein Feld, das AdvisoryLogCreate nicht kennt und still verwarf. Jetzt geht
# er als `recommendation_run_id`. Diese Tests pinnen beide Seiten am echten
# Router: mit Lauf-ID genau dessen eingefrorener Nachweis, auch wenn der
# mandatsweite Bauer inzwischen einen ANDEREN Lauf waehlen wuerde; ohne
# Lauf-ID weiterhin mandatsweit (Bestandsverhalten).


def _add_newer_final_run(session_factory, run_id: str) -> str:
    """Ein juengerer Final-Lauf derselben TA (ohne eingefrorenen Nachweis):
    der mandatsweite Resolver waehlt ab jetzt IHN statt des gezeigten Laufs."""
    import uuid
    from datetime import datetime, timedelta

    from sqlalchemy import inspect as sa_inspect

    with session_factory() as db:
        src = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        cols = {c.key: getattr(src, c.key) for c in sa_inspect(RecommendationRun).mapper.column_attrs}
        newer_id = str(uuid.uuid4())
        created = str(cols.get("created_at") or "")
        try:
            newer_created = (
                datetime.fromisoformat(created.replace("Z", "+00:00")) + timedelta(hours=1)
            ).isoformat()
        except ValueError:
            newer_created = "2999-01-01T00:00:00+00:00"
        cols.update(
            id=newer_id,
            created_at=newer_created,
            cost_disclosure_snapshot_json=None,
        )
        db.add(RecommendationRun(**cols))
        db.commit()
    return newer_id


def _stored_snapshot(session_factory, mandate_id) -> dict:
    with session_factory() as db:
        entry = db.query(AdvisoryLog).filter(AdvisoryLog.mandate_id == mandate_id).one()
        return {
            "snapshot": json.loads(entry.cost_disclosure_snapshot_json),
            "entry_run_id": entry.recommendation_run_id,
            "integrity_hash": entry.integrity_hash,
        }


def test_advisory_log_binds_to_the_shown_run_even_if_mandate_wide_moved_on(session_factory):
    from routers.review import create_advisory_log_entry

    advisor_id, mandate_id, shown_run = _certified_mandate(session_factory, suffix="bind-g")
    frozen_envelope = json.loads(_snapshot_raw(session_factory, shown_run))
    newer_run = _add_newer_final_run(session_factory, shown_run)
    # Vorbedingung: der mandatsweite Bauer zeigt inzwischen auf den anderen Lauf.
    assert _disclosure(session_factory, mandate_id)["source_run_id"] == newer_run

    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        create_advisory_log_entry(
            mandate_id=mandate_id,
            body=_log_body(recommendation_run_id=shown_run),
            request=_FakeRequest(), db=db, current_user=advisor,
        )
    stored = _stored_snapshot(session_factory, mandate_id)
    snap = stored["snapshot"]
    assert stored["entry_run_id"] == shown_run
    assert snap["recommendation_run_id"] == shown_run
    assert snap["evidence_frozen"] is True
    # Genau DIESER eingefrorene Nachweis: Hash des Umschlags des gezeigten Laufs.
    assert snap["source_content_hash"] == frozen_envelope["content_hash"]
    assert snap["content_hash"] == cost_service.cost_disclosure_content_hash(
        {k: v for k, v in snap.items() if k != "content_hash"}
    )
    assert stored["integrity_hash"]


def test_advisory_log_without_run_id_stays_mandate_wide(session_factory):
    """Bestandsverhalten unveraendert: ohne Lauf-ID der mandatsweite Bauer."""
    from routers.review import create_advisory_log_entry

    advisor_id, mandate_id, shown_run = _certified_mandate(session_factory, suffix="bind-h")
    frozen_envelope = json.loads(_snapshot_raw(session_factory, shown_run))
    newer_run = _add_newer_final_run(session_factory, shown_run)
    mandate_wide = _disclosure(session_factory, mandate_id)
    assert mandate_wide["source_run_id"] == newer_run

    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        create_advisory_log_entry(
            mandate_id=mandate_id, body=_log_body(),
            request=_FakeRequest(), db=db, current_user=advisor,
        )
    stored = _stored_snapshot(session_factory, mandate_id)
    snap = stored["snapshot"]
    assert stored["entry_run_id"] is None
    assert snap["recommendation_run_id"] == newer_run
    assert snap["source_content_hash"] != frozen_envelope["content_hash"]


def test_legacy_editor_fields_are_dropped_and_never_bind_a_run(session_factory):
    """Dokumentiert die Ursache: die frueheren Editor-Felder
    `cost_disclosure_snapshot_id`/`_currency` kennt das Schema nicht -- sie
    verschwinden still, der Nachweis landet beim mandatsweiten Lauf statt beim
    gezeigten. Nur `recommendation_run_id` bindet (Test oben)."""
    from routers.review import create_advisory_log_entry

    advisor_id, mandate_id, shown_run = _certified_mandate(session_factory, suffix="bind-i")
    newer_run = _add_newer_final_run(session_factory, shown_run)
    body = _log_body(
        cost_disclosure_snapshot_id=shown_run,
        cost_disclosure_snapshot_currency="CHF",
    )
    assert "cost_disclosure_snapshot_id" not in body.model_dump()
    assert body.recommendation_run_id is None
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        create_advisory_log_entry(
            mandate_id=mandate_id, body=body,
            request=_FakeRequest(), db=db, current_user=advisor,
        )
    assert _stored_snapshot(session_factory, mandate_id)["snapshot"][
        "recommendation_run_id"
    ] == newer_run
