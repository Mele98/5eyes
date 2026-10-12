"""Sprint U-68 (Roadmap-Punkt 68, 2026-06-02): ConflictOfInterestDisclosure
im Advisory-Report-Aggregator.

Hintergrund
-----------
- ConflictOfInterestDisclosure Model + DB-Tabelle existieren seit
  Schema v4.0 FINAL.
- AdvisoryLog (Beratungsprotokoll) referenziert IDs via
  conflict_disclosure_ids_json.
- ABER: services/advisory_report.py hatte KEINE Aggregator-Sektion
  fuer Disclosures -> Tabelle war in keinem Bericht/PDF sichtbar.
- FIDLEG Art. 9 verlangt Offenlegung von Vermittlerentschaedigungen,
  Art. 26 organisatorische Massnahmen -> Disclosures MUESSEN in
  Berater-Report erscheinen.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.advisory_report import _build_conflict_disclosures  # noqa: E402


def _row(**overrides):
    base = {
        "id": "disc-001",
        "conflict_type": "retrozession",
        "description": "Standard-Retrozessions-Offenlegung",
        "inducement_provider": "Provider AG",
        "inducement_amount_rappen": 50000,
        "inducement_frequency": "annual",
        "disclosed_to_client": 1,
        "disclosed_at": "2026-05-01T10:00:00Z",
        "client_acknowledged": 1,
        "client_acknowledged_at": "2026-05-02T10:00:00Z",
        "mitigation_action": "weitergegeben an Kunde",
        "document_id": "doc-001",
        "deleted_at": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _stub_db_with(rows):
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.all.return_value = rows
    db.query.return_value = query_chain
    return db


def _stub_mandate(mid: str = "MX-TEST-01"):
    m = MagicMock()
    m.id = mid
    return m


def test_empty_mandate_returns_empty_schema():
    db = _stub_db_with([])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["entries"] == []
    assert result["counts"]["total"] == 0
    assert result["counts"]["by_type"] == {}
    assert result["has_unacknowledged"] is False
    assert result["has_undisclosed"] is False
    # Kein Konflikt vorhanden heisst wirklich "nichts offen" -- das ist der
    # einzige Fall, in dem die Flags ohne Nachweis False sein duerfen, und
    # er unterscheidet sich von "Daten nicht lesbar" (data_unavailable).
    assert result["data_unavailable"] is False
    assert result["fidleg_basis"] == "Art. 9 / Art. 26 FIDLEG"


def test_schema_keys_are_stable():
    db = _stub_db_with([])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert set(result.keys()) == {
        "entries", "counts", "has_unacknowledged", "has_undisclosed",
        "data_unavailable", "fidleg_basis",
    }
    assert set(result["counts"].keys()) == {"total", "by_type"}


def test_db_error_returns_degraded_schema():
    db = MagicMock()
    db.query.side_effect = RuntimeError("table does not exist")
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["entries"] == []
    assert result["counts"]["total"] == 0
    # CONFLICT-STATE-001 Zusatz (2026-10-12): dieser Zweig meldete vorher
    # `has_unacknowledged=False`, also "nichts offen" -- obwohl hier GAR
    # NICHTS bekannt ist. Ein Lesefehler ist keine Entwarnung.
    assert result["has_unacknowledged"] is True
    assert result["has_undisclosed"] is True
    assert result["data_unavailable"] is True


def test_degraded_and_normal_payloads_have_identical_keys():
    """Beide Rueckgabepfade muessen dieselbe Form haben.

    Driften sie auseinander, laeuft ein Konsument im Degradationsfall in
    einen KeyError -- genau in dem Moment, in dem er die Flags am
    dringendsten braucht.
    """
    normal = _build_conflict_disclosures(_stub_db_with([]), _stub_mandate())
    broken_db = MagicMock()
    broken_db.query.side_effect = RuntimeError("table does not exist")
    degraded = _build_conflict_disclosures(broken_db, _stub_mandate())
    assert set(normal.keys()) == set(degraded.keys())


def test_single_disclosure_full_payload():
    db = _stub_db_with([_row()])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["counts"]["total"] == 1
    assert result["counts"]["by_type"] == {"retrozession": 1}
    entry = result["entries"][0]
    assert entry["id"] == "disc-001"
    assert entry["conflict_type"] == "retrozession"
    assert entry["inducement_provider"] == "Provider AG"
    assert entry["inducement_amount_rappen"] == 50000
    assert entry["disclosed_to_client"] is True
    assert entry["client_acknowledged"] is True


def test_multi_disclosure_counts_by_type():
    db = _stub_db_with([
        _row(id="d1", conflict_type="retrozession"),
        _row(id="d2", conflict_type="retrozession"),
        _row(id="d3", conflict_type="boni"),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["counts"]["total"] == 3
    assert result["counts"]["by_type"]["retrozession"] == 2
    assert result["counts"]["by_type"]["boni"] == 1


def test_disclosed_without_ack_triggers_unacknowledged():
    db = _stub_db_with([
        _row(disclosed_to_client=1, client_acknowledged=0),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["has_unacknowledged"] is True


def test_disclosed_and_acked_clears_flag():
    db = _stub_db_with([
        _row(disclosed_to_client=1, client_acknowledged=1),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["has_unacknowledged"] is False


def test_never_disclosed_triggers_unacknowledged_and_undisclosed():
    """CONFLICT-STATE-001 (2026-10-12): dieser Test hiess bis heute
    `test_not_disclosed_does_not_trigger_unacknowledged` und verlangte
    `False` -- er hielt damit den Defekt als gewolltes Verhalten fest.

    Der schlimmste Fall (dem Kunden nie offengelegt) blieb dadurch
    unauffaellig, waehrend die blosse fehlende Kenntnisnahme Alarm gab. Die
    Assertion ist umgedreht, nicht geloescht: der Zustand, den sie prueft,
    ist derselbe, nur das Soll war falsch.
    """
    db = _stub_db_with([
        _row(disclosed_to_client=0, client_acknowledged=0),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["has_unacknowledged"] is True
    assert result["has_undisclosed"] is True
    assert result["entries"][0]["resolution_state"] == "undisclosed"


def test_acknowledged_without_disclosure_is_flagged_as_contradiction():
    """`client_acknowledged=1` bei `disclosed_to_client=0` ist kein Zustand.

    Der Kunde kann nicht bestaetigt haben, was ihm nie offengelegt wurde.
    Ohne diesen Test koennte eine Implementierung, die nur
    `client_acknowledged` prueft, den Fall als erledigt durchwinken.
    """
    db = _stub_db_with([
        _row(disclosed_to_client=0, client_acknowledged=1),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["has_unacknowledged"] is True
    assert result["has_undisclosed"] is True
    assert result["entries"][0]["resolution_state"] == "acknowledged_without_disclosure"


def test_resolved_entry_sets_neither_flag():
    """Gegenprobe: der vollstaendige Fall darf NICHT gemeldet werden.

    Ohne diese Zeile waere eine Implementierung, die `has_unacknowledged`
    konstant auf True setzt, von den Tests oben nicht zu unterscheiden.
    """
    db = _stub_db_with([
        _row(disclosed_to_client=1, client_acknowledged=1),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["has_unacknowledged"] is False
    assert result["has_undisclosed"] is False
    assert result["entries"][0]["resolution_state"] == "resolved"
    assert result["data_unavailable"] is False


def test_disclosed_unacknowledged_is_not_reported_as_undisclosed():
    """Die beiden Flags muessen verschiedene Dinge messen.

    Waeren sie identisch verdrahtet, bliebe die handlungsrelevante
    Unterscheidung ("offenlegen" vs. "Bestaetigung einholen") verloren.
    """
    db = _stub_db_with([
        _row(disclosed_to_client=1, client_acknowledged=0),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["has_unacknowledged"] is True
    assert result["has_undisclosed"] is False
    assert result["entries"][0]["resolution_state"] == "disclosed_unacknowledged"


def test_mixed_some_unacked_triggers_flag():
    db = _stub_db_with([
        _row(id="d1", disclosed_to_client=1, client_acknowledged=1),
        _row(id="d2", disclosed_to_client=1, client_acknowledged=0),
        _row(id="d3", disclosed_to_client=1, client_acknowledged=1),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["has_unacknowledged"] is True


def test_missing_conflict_type_defaults_to_unknown():
    db = _stub_db_with([_row(conflict_type=None)])
    result = _build_conflict_disclosures(db, _stub_mandate())
    assert result["entries"][0]["conflict_type"] == "unknown"
    assert "unknown" in result["counts"]["by_type"]


def test_nullable_inducement_fields_preserved():
    db = _stub_db_with([
        _row(
            inducement_provider=None,
            inducement_amount_rappen=None,
            inducement_frequency=None,
            mitigation_action=None,
            document_id=None,
        ),
    ])
    result = _build_conflict_disclosures(db, _stub_mandate())
    entry = result["entries"][0]
    assert entry["inducement_provider"] is None
    assert entry["inducement_amount_rappen"] is None
    assert entry["mitigation_action"] is None


def test_compute_advisory_report_includes_section():
    # Seit PR #110 (N+1-Cache-Refactor) ist compute_advisory_report nur ein
    # duenner Wrapper; die Sektions-Verdrahtung liegt in
    # _compute_advisory_report_inner.
    from services.advisory_report import _compute_advisory_report_inner
    import inspect
    source = inspect.getsource(_compute_advisory_report_inner)
    assert "conflict_disclosures" in source, (
        "_compute_advisory_report_inner verweist nicht auf conflict_disclosures."
    )


def test_section_number_is_18():
    import inspect
    from services.advisory_report import _compute_advisory_report_inner
    source = inspect.getsource(_compute_advisory_report_inner)
    assert "Sektion 18" in source
