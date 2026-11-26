"""P5c (H-186, CTO-Entscheide 2026-11-21) -- Zielstatus aus EINER Quelle.

* N-930-01: M-3 ist die einzige Quelle des Zielstatus. Wort und Farbe kommen
  aus ``core/goal_metric_contract.GOAL_STATUS_DISPLAY``; ohne M-3 fuer ein Ziel
  "nicht bewertbar" (fail-closed), nie Ampel 70/45 oder Faecherquantile.
* N-930-03: ``goal_revision`` bindet ``pension_pillar`` und
  ``lifecycle_decision``; die Feldliste steht nur in ``GOAL_REVISION_FIELDS``
  (= "id" + ``GOAL_ECONOMIC_FIELDS`` des Optimierers). Querschnitt: eine
  irrelevante Aenderung laesst den Entscheid FRESH.
* N-930-04: Status konservativ -- ungerundete Werte und gespeicherte Zeile;
  bei Abweichung gilt die vorsichtigere Einstufung (ESS 29.995..30, < 0.5 ppm).
* N-930-05: App, Beratungsbericht(-PDF) und Anlagestrategie-PDF zeigen fuer
  jedes Ziel denselben Status (Wort, Wert, Payload-Hash).
* CCX_CHANNEL_SEQUENCE_RACE: typisierter 409, nie 500.

Gegenprobe (alter Code, ca5da413): N-930-03 (Feldliste ohne die zwei Felder),
N-930-04 (Grenzfaelle "erreichbar"), N-930-01 (unzertifiziert -> gespeicherter
Status, Ampel im App-Payload) und der Race-Fall (roher IntegrityError) sind rot.
"""
from __future__ import annotations

import inspect
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.goal_metric_contract import (
    GOAL_REVISION_FIELDS,
    GOAL_STATUS_DISPLAY,
    build_goal_metric_payload,
    canonical_goal_rows,
    goal_revision,
    goal_status_display,
)
from core.reason_codes import DomainError
from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401
from tests.test_ccx_p4_allocation_publish import _mandate, _published
from tests.test_ccx_p5_channel_envelope import _anlagestrategie, _decision
from tests.test_ccx_p5b_goal_metric import _row, _ta
from tests.test_h12_ccx_hygiene import _user

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "ares-desktop" / "frontend"


# ── N-930-01: eine Tabelle, fail-closed ─────────────────────────────────────


def test_unknown_or_missing_status_is_not_assessable():
    for value in (None, "", "On Track", "gut", "data_pending", "unknown"):
        assert goal_status_display(value)["status"] == "nicht_bewertbar", value
        assert goal_status_display(value)["status_label"] == "nicht bewertbar"


def test_uncertified_metric_never_shows_the_stored_optimizer_status():
    ta, _goal, _mandate_ns = _ta([_row(status="erreichbar")], cube=None)  # Validierung unvollstaendig
    row = canonical_goal_rows([_row(status="erreichbar")], ta)[0]
    assert row["status"] == "nicht_bewertbar"
    assert (row["status_label"], row["status_color"]) == (GOAL_STATUS_DISPLAY["nicht_bewertbar"][0],
                                                          GOAL_STATUS_DISPLAY["nicht_bewertbar"][2])


def test_certified_row_carries_word_and_colour_from_the_one_table():
    ta, _goal, _mandate_ns = _ta([_row()])
    row = canonical_goal_rows([_row()], ta)[0]
    label, tone, color, background = GOAL_STATUS_DISPLAY[row["status"]]
    assert (row["status_label"], row["status_tone"], row["status_color"], row["status_bg"]) == (
        label, tone, color, background)


def test_legacy_row_keeps_its_raw_status_but_shows_altbewertung():
    raw = {**_row(), "evaluation_scope": ""}
    ta, _goal, _mandate_ns = _ta([raw])
    row = canonical_goal_rows([raw], ta)[0]
    assert row["status"] == "erreichbar" and row["status_label"] == "Altbewertung"


def test_no_second_status_table_or_ampel_remains():
    """Statisch: keine eigene Status-Wort-/Farbtabelle und keine Ampel 70/45
    mehr in den Anzeige-Schichten (Gegenprobe: alter Stand hat alle)."""
    pdf_sources = {p.name: p.read_text(encoding="utf-8") for p in [
        BACKEND / "services/pdf/documents/advisory_report.py",
        BACKEND / "services/pdf/components/goal_achievability.py",
        BACKEND / "services/pdf/components/mc_paths_chart.py",
        BACKEND / "services/pdf/components/ziele_table.py",
        BACKEND / "services/pdf/styles.py",
    ]}
    for name, src in pdf_sources.items():
        assert "Schwierig" not in src, name
        assert "_GOAL_STATUS_PILL = {" not in src and "_AMPEL_STATUS_COLORS: dict" not in src, name
        assert "_STATUS_DISPLAY: dict" not in src, name
        assert "def goal_color" not in src, name
        assert "MC-Status\", styles" not in src, name
    classic = "\n".join((FRONTEND / n).read_text(encoding="utf-8") for n in (
        "ares.html", "goal-review-runtime.js", "goal-analysis-integrity.js", "p5c-ui.js"))
    for pattern in (r"pct>=70", r"success>=70", r"p>=0\.70", r"n>=70", r"g\.prob>=70", r"score\|\|0\)\)>=70",
                    r"'On Track'", r"function goalSuccessAmpel\(", r"function rvGoalProbBadge\("):
        assert not re.search(pattern, classic), pattern
    react = (FRONTEND / "reporting/src/components/MonteCarloPathsChart.tsx").read_text(encoding="utf-8")
    assert "STATUS_COLOR[" not in react and "Schwierig" not in react
    goals_page = (FRONTEND / "reporting/src/pages/Goals.tsx").read_text(encoding="utf-8")
    assert "Schwierig" not in goals_page


# ── N-930-03: goal_revision ─────────────────────────────────────────────────


def _goal(**over):
    base = {name: None for name in GOAL_REVISION_FIELDS}
    base.update(id="g1", goal_type="Pensionsausgabe", target_amount_rappen=100_000_00, rank=1,
                label="Ruhestand", notes="", updated_at="2026-11-01")
    base.update(over)
    return SimpleNamespace(**base)


def test_revision_fields_are_id_plus_the_optimizer_economic_fields():
    from services.optimizer.solver import GOAL_ECONOMIC_FIELDS

    assert set(GOAL_REVISION_FIELDS) == {"id"} | set(GOAL_ECONOMIC_FIELDS)
    assert len(GOAL_REVISION_FIELDS) == len(set(GOAL_REVISION_FIELDS))
    assert {"pension_pillar", "lifecycle_decision"} <= set(GOAL_REVISION_FIELDS)
    # Feldliste nur einmal: goal_revision liest die Konstante (keine zweite Liste).
    src = inspect.getsource(goal_revision)
    assert "_GOAL_REVISION_READERS" in src and '"target_amount_rappen"' not in src
    from core.goal_metric_contract import _GOAL_REVISION_READERS

    probe = SimpleNamespace(**{name: f"v-{name}" for name in GOAL_REVISION_FIELDS})
    assert all(read(probe) == f"v-{name}" for name, read in _GOAL_REVISION_READERS.items())


@pytest.mark.parametrize("field,value", [("pension_pillar", "3a"), ("lifecycle_decision", "fulfilled")])
def test_revision_changes_with_pension_pillar_and_lifecycle_decision(field, value):
    assert goal_revision(_goal(**{field: value})) != goal_revision(_goal())


def test_revision_ignores_irrelevant_fields():
    """Querschnitt (Unit): Label, Notizen und Zeitstempel aendern die Revision nicht."""
    before = goal_revision(_goal())
    assert goal_revision(_goal(label="Anders", notes="neu", updated_at="2026-11-21T10:00:00")) == before


def test_gate_crosscheck_irrelevant_change_stays_fresh_relevant_goal_field_does_not(session_factory):
    """Querschnitt am echten Gate: Beruehrung (updated_at) und Beruf bleiben FRESH
    mit unveraendertem M-3-Hash; pension_pillar sperrt (CCX_INPUT_STALE)."""
    from models.clients import Client
    from models.wealth import Goal

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5c-x")
    first = _decision(session_factory, mid)
    assert first.ok, first
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == mid, Goal.deleted_at.is_(None)).first()
        assert goal is not None
        goal.updated_at = "2026-11-21T10:00:00+00:00"
        client = db.get(Client, _mandate(db, mid).client_id)
        client.profession = "Schreinerin"
        db.commit()
    second = _decision(session_factory, mid)
    assert second.ok, second
    assert second.goal_metric_payload_hash == first.goal_metric_payload_hash
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.mandate_id == mid, Goal.deleted_at.is_(None)).first()
        goal.pension_pillar = "3a"
        db.commit()
    third = _decision(session_factory, mid)
    assert not third.ok and "STALE" in str(third.reason_code), third


# ── N-930-04: konservativ an den Grenzen ────────────────────────────────────


def _status(n_paths=2000, **row):
    ta, goal, mandate = _ta([_row(**row)], n_paths=n_paths)
    return build_goal_metric_payload([goal], mandate=mandate, target_allocation=ta)["goals"][0]["status"]


def test_ess_just_below_30_is_not_sufficient():
    # ESS 29.996 rundet auf 3000 (x100) -> frueher "erreichbar". 200 Pfade: die
    # Anteils-Untergrenze (10 % = 20) greift nicht, nur die absolute (30).
    assert _status(n_paths=200, effective_sample_size=29.996, lower_confidence_bound=0.85,
                   status="erreichbar") == "unreliable"
    assert _status(n_paths=200, effective_sample_size=29.995, lower_confidence_bound=0.85,
                   status="unreliable") == "unreliable"
    assert _status(n_paths=200, effective_sample_size=30.0, lower_confidence_bound=0.85,
                   status="erreichbar") == "erreichbar"


def test_lower_bound_below_tau_by_less_than_half_a_ppm_is_knapp():
    # 0.7999996 rundet auf 800000 ppm = tau -> frueher "erreichbar".
    assert _status(lower_confidence_bound=0.7999996, status="erreichbar") == "knapp"


def test_stored_row_more_cautious_than_the_recomputation_wins():
    assert _status(lower_confidence_bound=0.85, status="knapp") == "knapp"
    assert _status(lower_confidence_bound=0.85, status="nicht_erreichbar") == "nicht_erreichbar"


def test_clear_cases_are_unchanged():
    assert _status(lower_confidence_bound=0.85, status="erreichbar") == "erreichbar"
    assert _status(lower_confidence_bound=0.78, status="erreichbar") == "knapp"
    # Genau auf der Anteils-Untergrenze (10 % von 2000 Pfaden) ist die Stichprobe ausreichend.
    assert _status(effective_sample_size=200.0, lower_confidence_bound=0.85, status="erreichbar") == "erreichbar"


# ── N-930-05: App = Bericht = PDF ───────────────────────────────────────────


def _pdf_text(response) -> str:
    pypdf = pytest.importorskip("pypdf")
    body = response if isinstance(response, (bytes, bytearray)) else (getattr(response, "body", None) or b"")
    reader = pypdf.PdfReader(io.BytesIO(body))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


_STATUS_WORDS = {label for label, *_rest in GOAL_STATUS_DISPLAY.values()}


def _status_words_after_label(text: str, label: str, labels: set[str]) -> list[str]:
    """N-933-06: Statuswort je Tabellenzeile im gerenderten PDF. pypdf liefert je
    Zelle eine Zeile; nach der Zeile «Ziel-Label» folgt (vor dem naechsten Ziel)
    die Zelle mit dem Statuswort. Verglichen wird die GANZE Zelle (Zeilenanker),
    ein umbrochenes «nicht / erreichbar» wird zusammengesetzt -- «erreichbar»
    passt so nie auf «nicht erreichbar»."""
    lines = [line.strip() for line in text.splitlines()]
    found: list[str] = []
    for i, line in enumerate(lines):
        if line != label:
            continue
        for j in range(i + 1, min(i + 12, len(lines))):
            if lines[j] in labels:
                break
            joined = f"{lines[j - 1]} {lines[j]}"
            if j - 1 > i and joined in _STATUS_WORDS:
                found.append(joined)
                break
            if re.fullmatch(r"(?:" + "|".join(map(re.escape, _STATUS_WORDS)) + r")", lines[j]):
                found.append(lines[j])
                break
    return found


def test_pdf_status_reader_distinguishes_erreichbar_from_nicht_erreichbar():
    """Selbstpruefung des Lesers: Wortgrenze und Zeilenumbruch."""
    labels = {"Pension", "Haus"}
    assert _status_words_after_label("Pension\nhart\nnicht erreichbar\nHaus\nerreichbar",
                                     "Pension", labels) == ["nicht erreichbar"]
    assert _status_words_after_label("Pension\nhart\nnicht\nerreichbar\nHaus\nerreichbar",
                                     "Pension", labels) == ["nicht erreichbar"]
    assert _status_words_after_label("Pension\nhart\nnicht\nerreichbar\nHaus\nerreichbar",
                                     "Haus", labels) == ["erreichbar"]
    assert _status_words_after_label("Pension\nhart\nHaus\nerreichbar", "Pension", labels) == []


def test_app_report_and_strategy_pdf_show_the_same_status_per_goal(session_factory):
    from routers.allocation import get_current_allocation_payload
    from routers.pdf_reports import _build_anlagestrategie_data
    from services.advisory_report import _build_goal_based_investing, _load_goal_achievability_view
    from services.pdf.components.goal_achievability import make_goal_achievability_table
    from services.portfolio_engine_payload import _stored_goal_achievability

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5c-par")
    with session_factory() as db:
        mandate = _mandate(db, mid)
        user = _user(db, advisor_id)
        app = get_current_allocation_payload(mandate_id=mid, db=db, current_user=user)
        app = app if isinstance(app, dict) else app.model_dump()
        from models.allocation import TargetAllocation

        ta = db.query(TargetAllocation).filter(TargetAllocation.mandate_id == mid,
                                               TargetAllocation.is_current == 1).one()
        canonical = {r["goal_id"]: r for r in _stored_goal_achievability(ta)
                     if r.get("evaluation_scope") == "priority_funded"}
        assert canonical, "Fixture ohne zielindividuelle M-3-Zeilen"
        app_goals = {str(g["goal_id"]): g for g in app["goal_analysis"]}
        app_rows = {r["goal_id"]: r for r in app["goal_achievability"] if r.get("evaluation_scope") == "priority_funded"}
        report_rows, _plan = _load_goal_achievability_view(ta)
        report_rows = {r["goal_id"]: r for r in report_rows}
        report_goals = {g["goal_id"]: g for g in _build_goal_based_investing(db, mandate)["goals"]}
        pdf_rows = {r["goal_id"]: r for r in _build_anlagestrategie_data(mandate, db).goal_achievability
                    if r.get("evaluation_scope") == "priority_funded"}
        strategy_pdf = _pdf_text(_anlagestrategie(db, mid, user))
        from services.pdf.documents.advisory_report import render_advisory_report_pdf

        advisory_bytes = render_advisory_report_pdf(db, mandate, user)
        assert advisory_bytes, "Beratungsbericht-PDF nicht gerendert"
        advisory_pdf = _pdf_text(advisory_bytes)
        goal_labels = {str(r.get("label")) for r in canonical.values()}
        for goal_id, row in canonical.items():
            expected = (row["status"], row["status_label"], row["status_color"])
            assert row["goal_metric_payload_hash"]
            for channel, other in (("app.goal_analysis", app_goals), ("app.goal_achievability", app_rows),
                                   ("bericht", report_rows), ("bericht.goals", report_goals),
                                   ("anlagestrategie-pdf", pdf_rows)):
                got = other[goal_id]
                assert (got["status"], got["status_label"], got["status_color"]) == expected, (channel, got)
            assert app_rows[goal_id]["probability"] == report_rows[goal_id]["probability"] == pdf_rows[goal_id]["probability"]
            assert report_goals[goal_id]["probability_bps"] == round(row["probability"] * 10000)
            assert (app_rows[goal_id]["goal_metric_payload_hash"] == report_rows[goal_id]["goal_metric_payload_hash"]
                    == pdf_rows[goal_id]["goal_metric_payload_hash"])
            # N-933-06: gerendert -- je Ziel die Zeile «Ziel-Label ... Statuswort» im
            # Anlagestrategie-PDF UND im Beratungsbericht-PDF, ganze Zelle (Wortgrenze).
            for channel, text in (("anlagestrategie-pdf", strategy_pdf), ("beratungsbericht-pdf", advisory_pdf)):
                words = _status_words_after_label(text, str(row["label"]), goal_labels)
                assert words and set(words) == {row["status_label"]}, (channel, row["label"], words)
            table = make_goal_achievability_table(list(pdf_rows.values()))
            cell = json.dumps([str(getattr(c, "text", c)) for r in table._cellvalues for c in r], ensure_ascii=False)
            assert row["status_label"] in cell


# ── CCX_CHANNEL_SEQUENCE_RACE -> 409 ─────────────────────────────────────────


def test_lost_channel_sequence_is_a_typed_409_not_a_500(session_factory):
    from sqlalchemy import event

    from models.snapshots import AdvisoryChannelPublication
    from services.allocation_publication_gate import evaluate_channel_envelope, record_channel_publication

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5c-race")
    with session_factory() as db:
        _anlagestrategie(db, mid, _user(db, advisor_id))  # erste Kanalzeile (Nummer 1)
        db.commit()

    def lose_the_race(_mapper, _conn, target):
        target.channel_sequence = 1  # ein paralleles Schreiben hat die Nummer schon belegt

    event.listen(AdvisoryChannelPublication, "before_insert", lose_the_race)
    try:
        with session_factory() as db:
            mandate = _mandate(db, mid)
            decision = evaluate_channel_envelope(db, mandate)
            assert decision.ok
            with pytest.raises(DomainError) as exc:
                record_channel_publication(db, decision, mandate=mandate, channel="PDF", artifact_id="p5c-race-2",
                                           channel_payload_hash="a" * 64, render_hash="b" * 64,
                                           user=_user(db, advisor_id))
            assert exc.value.reason_code == "CCX_CHANNEL_SEQUENCE_RACE"
            assert exc.value.status_code == 409
            # Die umgebende Transaktion bleibt nutzbar (SAVEPOINT).
            assert db.query(AdvisoryChannelPublication).filter(
                AdvisoryChannelPublication.mandate_id == mid).count() >= 1
    finally:
        event.remove(AdvisoryChannelPublication, "before_insert", lose_the_race)


def test_other_integrity_errors_on_the_channel_row_are_not_reported_as_a_race(session_factory):
    """Fixrunde 1 / N-933-05 (CTO): nur die Verletzung der laufenden Nummer ist
    ein Wettlauf (409). Ein anderer Integritaetsfehler (hier CHECK auf
    render_hash) wird unveraendert weitergeworfen. Gegenprobe: alter Code ->
    DomainError CCX_CHANNEL_SEQUENCE_RACE -> rot."""
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError

    from models.snapshots import AdvisoryChannelPublication
    from services.allocation_publication_gate import evaluate_channel_envelope, record_channel_publication

    advisor_id, _approver, mid, *_rest = _published(session_factory, "p5c-check")

    def break_a_check(_mapper, _conn, target):
        target.render_hash = "kurz"  # verletzt ck_advisory_channel_publications_render_hash

    event.listen(AdvisoryChannelPublication, "before_insert", break_a_check)
    try:
        with session_factory() as db:
            mandate = _mandate(db, mid)
            decision = evaluate_channel_envelope(db, mandate)
            assert decision.ok
            with pytest.raises(IntegrityError) as exc:
                record_channel_publication(db, decision, mandate=mandate, channel="PDF", artifact_id="p5c-check-1",
                                           channel_payload_hash="a" * 64, render_hash="b" * 64,
                                           user=_user(db, advisor_id))
            assert not isinstance(exc.value, DomainError)
            assert "render_hash" in str(exc.value.orig)
    finally:
        event.remove(AdvisoryChannelPublication, "before_insert", break_a_check)


@pytest.mark.parametrize("message,race", [
    ("CCX_CHANNEL_SEQUENCE_RACE", True),  # SQLite-/PostgreSQL-Trigger
    ('duplicate key value violates unique constraint "ux_advisory_channel_publications_sequence"', True),
    ("UNIQUE constraint failed: advisory_channel_publications.mandate_id, "
     "advisory_channel_publications.channel_sequence", True),
    ("CCX_CHANNEL_BINDING_MISSING", False),
    ("FOREIGN KEY constraint failed", False),
    ("NOT NULL constraint failed: advisory_channel_publications.channel", False),
    # KN9 / N-933R-03: NOT NULL auf der Nummernspalte ist kein Wettlauf.
    ("NOT NULL constraint failed: advisory_channel_publications.channel_sequence", False),
    ('null value in column "channel_sequence" of relation "advisory_channel_publications" '
     "violates not-null constraint", False),
    ('new row violates check constraint "ck_advisory_channel_publications_sequence"', False),
    ("UNIQUE constraint failed: advisory_channel_publications.envelope_id, "
     "advisory_channel_publications.channel, advisory_channel_publications.artifact_id", False),
    ('new row violates check constraint "ck_advisory_channel_publications_payload"', False),
])
def test_only_the_channel_sequence_violation_counts_as_race(message, race):
    from sqlalchemy.exc import IntegrityError

    from services.allocation_publication_gate import is_channel_sequence_race

    assert is_channel_sequence_race(IntegrityError("INSERT", {}, Exception(message))) is race


def test_channel_sequence_race_code_is_catalogued():
    from core.reason_codes import ReasonCode

    assert ReasonCode.CCX_CHANNEL_SEQUENCE_RACE.value == "CCX_CHANNEL_SEQUENCE_RACE"
