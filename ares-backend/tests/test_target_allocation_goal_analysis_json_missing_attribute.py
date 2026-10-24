"""Red test for GOAL-REAL-SPENDING-INFLATION-PARITY-001 (round 40 audit).

Finding (sub-finding: missing model attribute):

``routers/pdf_reports.py`` builds the PDF's SOLL-Goal-Analysis section like
this (around line 672)::

    goal_json = getattr(ta_obj, "goal_analysis_json", None)
    if goal_json:
        parsed = json.loads(goal_json)
        ...

but ``models.allocation.TargetAllocation`` has NO column named
``goal_analysis_json`` at all -- see ``models/allocation.py``. Because the
read uses ``getattr(..., None)`` (a safe default) instead of a direct
attribute access, this never raises ``AttributeError``. It just silently
and *permanently* returns ``None`` for every real ``TargetAllocation`` row
that has ever existed or ever will exist, because nothing anywhere in the
codebase ever assigns to an attribute of that name (confirmed via
repository-wide grep: zero writers, zero ``Column`` definition, zero
migration).

Net effect: the "goal_analysis" list passed into the PDF template
(``routers/pdf_reports.py`` line ~800, ``goal_analysis=goal_analysis``) is
always an empty list. Whatever PDF section is supposed to render the
SOLL-goal-analysis from this value renders empty, in every report, for
every mandate, with no error surfaced to anyone -- a silent, permanent data
gap.

Likely intended fix: ``TargetAllocation`` already has a sibling column,
``goal_achievability_json`` (model line ~77, with a real DB column, a real
Alembic migration entry, and real writers in
``services/portfolio_engine.py``), which carries essentially the same kind
of payload (a JSON list of per-goal analysis/achievability entries) and is
read correctly via the identical ``getattr(ta_obj, "goal_achievability_json",
None)`` pattern a few lines below (line ~768) in the very same function.
That strongly suggests the ``goal_analysis_json`` read at line 672 is a
copy-paste/rename artifact that should have read
``goal_achievability_json`` (or a real ``goal_analysis_json`` column should
be added and populated) -- not a second, never-populated field.

This test is wrapped ``xfail(strict=True)`` so the suite stays green until
a human decides which of the two fixes is correct; see the audit doc
2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md (not
committed in this worktree).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: F401,E402 - importing registers full SQLAlchemy metadata
from models.allocation import TargetAllocation  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ta_goal_analysis_json_missing.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_target_allocation(**overrides) -> TargetAllocation:
    now = _utc_now_iso()
    defaults = dict(
        id="ta-goal-analysis-missing",
        mandate_id="mandate-goal-analysis-missing",
        version=1,
        is_current=1,
        target_equities_bps=4000,
        target_bonds_bps=4000,
        target_real_estate_bps=1000,
        target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=3000,
        band_equities_max_bps=5000,
        band_bonds_min_bps=3000,
        band_bonds_max_bps=5000,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=2000,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=1000,
        band_liquidity_min_bps=200,
        band_liquidity_max_bps=1000,
        policy_id="policy-goal-analysis-missing",
        set_by="user-goal-analysis-missing",
        set_at=now,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return TargetAllocation(**defaults)


def test_target_allocation_model_has_no_goal_analysis_json_column():
    """Introspection: confirm `goal_analysis_json` is not a real column.

    This is the root cause the PDF-reading code at
    `routers/pdf_reports.py:672` silently relies on `getattr(..., None)`
    for -- there genuinely is no such column on the ORM model.
    """
    column_names = {c.name for c in TargetAllocation.__table__.columns}

    assert "goal_analysis_json" not in column_names, (
        "goal_analysis_json now exists as a real column -- the round-40 "
        "finding GOAL-REAL-SPENDING-INFLATION-PARITY-001 may be fixed; "
        "re-check routers/pdf_reports.py line ~672 and remove/update this "
        "xfail if the PDF SOLL-goal-analysis section is now populated."
    )
    # The sibling field that IS a real, persisted, written-to column and
    # that already carries the equivalent payload (per-goal JSON list),
    # confirming a real data source exists -- it is simply not the one the
    # PDF SOLL-goal-analysis section reads from.
    assert "goal_achievability_json" in column_names


def test_pdf_goal_analysis_has_no_usable_source_in_the_persisted_row(session_factory):
    """Die Zielanalyse im PDF hat keine verwendbare Quelle -- und das Umbenennen
    des Feldes waere der FALSCHE Fix.

    GOAL-ANALYSIS-PDF-DEAD-SOURCE-001. Dieser Test hiess
    ``test_pdf_reports_goal_analysis_json_read_is_always_none_for_real_ta_row``
    und verlangte, dass ``goal_json is not None`` wird -- mit der Empfehlung,
    ersatzweise ``goal_achievability_json`` zu lesen. Seine Fixture schrieb
    dazu eine Nutzlast in der ZIELANALYSE-Form nach
    ``goal_achievability_json`` und unterstellte damit, die beiden Formen
    seien gleich.

    Sie sind es nicht. Produktion persistiert dort
    ``{goal_id, label, target_kind, probability, tau, status, hardness,
    lower_confidence_bound, effective_sample_size, validation_seed,
    reliability_verdict}`` (services/optimizer/objective.py). Der PDF-Leser
    erwartete ``{rank, label, achievement_score, target_text,
    shortfall_rappen}``. Nur ``label`` ueberlappt, und ``shortfall_rappen``
    kommt in der Quelle gar nicht vor.

    Der alte Test waere also mit einem Fix gruen geworden, der im PDF eine
    Tabelle mit durchgaengig Rang 0, Erreichungsgrad 0.0, leerem Zieltext und
    Fehlbetrag 0 erzeugt -- eine Falschaussage statt einer Luecke. Er haette
    den falschen Fix zertifiziert.

    Dieser Test haelt stattdessen die tatsaechliche Lage fest, damit sie
    nicht erneut falsch gelesen wird.
    """
    from services.optimizer.objective import chance_constraint_penalty  # noqa: F401

    # Die ECHTE Produktions-Nutzlast, nicht die der alten Fixture.
    production_payload = [
        {
            "goal_id": "g-1",
            "label": "Hauskauf",
            "target_kind": "wealth_at_t",
            "probability": 0.82,
            "tau": 0.8,
            "status": "erreichbar",
            "hardness": "primaer",
            "lower_confidence_bound": 0.79,
            "effective_sample_size": 2000.0,
            "validation_seed": 12345,
            "reliability_verdict": "robust",
        }
    ]

    with session_factory() as session:
        ta = _make_target_allocation(
            goal_achievability_json=json.dumps(production_payload),
        )
        session.add(ta)
        session.commit()
        session.refresh(ta)

        # 1) Die Spalte, die der PDF-Leser ansprach, existiert nicht.
        assert getattr(ta, "goal_analysis_json", None) is None

        # 2) Die Schwester-Spalte traegt echte Daten -- aber in einer anderen Form.
        raw = getattr(ta, "goal_achievability_json", None)
        assert raw is not None
        entry = json.loads(raw)[0]

        # 3) Genau diese Felder braeuchte der Zielanalyse-Abschnitt, und
        #    genau sie fehlen. Faellt dieser Test, weil ein Feld dazugekommen
        #    ist, dann ist ein echter Fix moeglich geworden -- und dieser Test
        #    soll dann neu geschrieben werden, nicht geloescht.
        for required in ("rank", "achievement_score", "target_text", "shortfall_rappen"):
            assert required not in entry, (
                f"{required!r} ist jetzt in goal_achievability_json vorhanden -- "
                "die Zielanalyse im PDF koennte echte Daten bekommen. Diesen "
                "Test neu fassen statt entfernen."
            )

        # 4) Nur das Label ueberlappt -- zu wenig fuer eine Tabelle mit vier
        #    weiteren Spalten.
        assert entry["label"] == "Hauskauf"


def test_pdf_reports_no_longer_reads_the_nonexistent_column():
    """Der tote Lesezugriff ist entfernt, nicht nur kommentiert.

    Solange er dastand, sah der Zielanalyse-Abschnitt funktionsfaehig aus und
    war in einem defensiven ``except`` begraben -- die naechste Person haette
    ihn fuer funktionierend gehalten.
    """
    source = (BACKEND_ROOT / "routers" / "pdf_reports.py").read_text(encoding="utf-8")
    code_lines = [
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert 'getattr(ta_obj, "goal_analysis_json"' not in code, (
        "pdf_reports.py liest wieder die nicht existierende Spalte "
        "goal_analysis_json"
    )
    assert "GOAL-ANALYSIS-PDF-DEAD-SOURCE-001" in source, (
        "Die Begruendung, warum der Abschnitt leer bleibt, fehlt"
    )
