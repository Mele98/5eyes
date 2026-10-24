"""KNOWLEDGE-GAP-ASSET-CLASS-001: SAA-Anlageklassen <-> dokumentierte Kenntnisse.

Hinweis-Layer: Reason-Code KNOWLEDGE_GAP_ASSET_CLASS in Reasoning,
AA-Ansicht (Monolith) und Beratungsprotokoll-PDF; keine Allokationsaenderung.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
import models.allocation  # noqa: E402,F401
from models.allocation import OptimizerPolicy  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.tenant import Tenant  # noqa: E402,F401
import models.review  # noqa: E402,F401  (FK-Aufloesung)
import models.wealth  # noqa: E402,F401  (FK-Aufloesung)
import models.profiling  # noqa: E402,F401  (FK-Aufloesung)
from models.users import User  # noqa: E402
from services.knowledge_asset_class_gap import (  # noqa: E402
    COMPLIANCE_OPEN_QUESTION,
    QUESTIONNAIRE_INSTRUMENT_ROWS,
    REASON_CODE,
    attach_to_strategy_payload,
    evaluate_knowledge_gaps,
    protocol_hints_for_mandate,
    required_rows_for,
)

NOW = "2026-10-21T00:00:00.000Z"
HTML = (BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html").read_text(encoding="utf-8")

SAA = [
    {"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 2500},
    {"asset_class": "Aktien", "sub_asset_class": "Aktien Global", "target_weight_bps": 2000},
    {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 3000},
    {"asset_class": "Immobilien", "sub_asset_class": "Immobilien Schweiz", "target_weight_bps": 1000},
    {"asset_class": "Alternative", "sub_asset_class": "Gold / Rohstoffe", "target_weight_bps": 400},
    {"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 300},
    {"asset_class": "Liquiditaet", "sub_asset_class": "Kontoguthaben", "target_weight_bps": 800},
]


def _ki(**rows):
    return json.dumps({k: {"known": v[0], "informed": v[1]} for k, v in rows.items()})


# ---------------------------------------------------------------------------
# Mapping: aus dem Code abgeleitet
# ---------------------------------------------------------------------------

def test_questionnaire_rows_match_monolith_table():
    rows = set(re.findall(r'class="ke-ins" data-row="([^"]+)"', HTML))
    assert rows == set(QUESTIONNAIRE_INSTRUMENT_ROWS)


def test_every_default_sub_asset_class_has_a_mapping_decision():
    from services.portfolio_engine import _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS

    for sub, meta in _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS.items():
        rows = required_rows_for(meta["asset_class"], sub)
        # None = kein Finanzinstrument; () = keine Fragebogen-Zeile; sonst
        # ausschliesslich echte Fragebogen-Zeilen.
        assert rows is None or set(rows) <= set(QUESTIONNAIRE_INSTRUMENT_ROWS), sub


def test_mapping_core_cases():
    assert required_rows_for("Aktien", "Thema Verteidigung") == ("Aktien",)
    assert required_rows_for("Immobilien", "Immobilien Global") == ("Immobilien",)
    assert required_rows_for("Alternative", "Gold / Rohstoffe") == ("Edelmetalle",)
    assert required_rows_for("Alternative", "Private Equity") == ()
    assert required_rows_for("Alternative", "Unbekannt XY") == ()
    assert required_rows_for("Liquiditaet", "Kontoguthaben") is None
    assert required_rows_for("Liquidität", "Geldmarktfonds") == ("Geldmarktprodukte",)


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def test_empty_knowledge_reports_every_class_with_reason_code():
    result = evaluate_knowledge_gaps(SAA, "{}", client_classification="Privatkunde")
    assert result["status"] == "gap" and result["reason_code"] == REASON_CODE
    labels = [f["label"] for f in result["findings"]]
    # Gruppiert je Fragebogen-Zeile, sortiert nach Gewicht.
    assert labels == ["Aktien", "Obligationen", "Immobilien", "Edelmetalle", "Private Equity"]
    aktien = result["findings"][0]
    assert aktien["target_weight_bps"] == 4500
    assert aktien["sub_asset_classes"] == ["Aktien Schweiz", "Aktien Global"]
    pe = result["findings"][-1]
    assert pe["questionnaire_row_available"] is False
    assert pe["action"] == "Kunde über Private Equity informieren und dokumentieren."
    assert REASON_CODE in pe["message"] and "keine eigene Zeile" in pe["message"]
    assert result["advisory_only"] is True
    assert result["compliance_open_question"] == COMPLIANCE_OPEN_QUESTION


def test_known_or_informed_covers_the_class():
    knowledge = _ki(Aktien=(1, 0), Obligationen=(0, 1), Immobilien=(1, 1), Edelmetalle=(0, 1))
    result = evaluate_knowledge_gaps(SAA, knowledge, client_classification="Privatkunde")
    assert [f["label"] for f in result["findings"]] == ["Private Equity"]


def test_anlagefonds_does_not_cover_real_estate():
    knowledge = _ki(Anlagefonds=(1, 1), Aktien=(1, 1), Obligationen=(1, 1), Edelmetalle=(1, 1))
    result = evaluate_knowledge_gaps(SAA, knowledge, client_classification="Privatkunde")
    labels = [f["label"] for f in result["findings"]]
    assert "Immobilien" in labels


def test_all_documented_and_no_undocumentable_class_is_ok():
    saa = [s for s in SAA if s["sub_asset_class"] != "Private Equity"]
    knowledge = _ki(Aktien=(1, 1), Obligationen=(1, 1), Immobilien=(1, 1), Edelmetalle=(1, 1))
    result = evaluate_knowledge_gaps(saa, knowledge, client_classification="Privatkunde")
    assert result["status"] == "ok" and result["reason_code"] is None and result["findings"] == []


def test_zero_weight_sleeves_are_ignored():
    saa = [{"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 0}]
    assert evaluate_knowledge_gaps(saa, "{}")["status"] == "ok"


@pytest.mark.parametrize("classification,opt_out", [
    ("Professioneller Kunde", 0), ("Institutioneller Kunde", 0), ("Privatkunde", 1),
])
def test_professional_clients_presumed(classification, opt_out):
    result = evaluate_knowledge_gaps(
        SAA, "{}", client_classification=classification, is_professional_opt_out=opt_out,
    )
    assert result["status"] == "presumed" and result["findings"] == []


def test_invalid_json_counts_as_undocumented():
    result = evaluate_knowledge_gaps(SAA, "{kaputt", client_classification="Privatkunde")
    assert result["status"] == "gap"


# ---------------------------------------------------------------------------
# Payload: Reasoning + Feld, keine Allokationsaenderung
# ---------------------------------------------------------------------------

def _mandate(classification="Privatkunde"):
    return SimpleNamespace(
        id="m-x", client=SimpleNamespace(client_classification=classification, is_professional_opt_out=0),
    )


def test_attach_adds_field_and_reasoning_without_touching_weights():
    payload = {
        "reasoning": ["Ausgangspunkt ist die House Matrix fuer Score 7."],
        "sub_allocations": copy.deepcopy(SAA),
        "buckets": [{"asset_class": "Alternative", "target_weight_bps": 700}],
    }
    before = copy.deepcopy(payload)
    attach_to_strategy_payload(payload, _mandate(), SimpleNamespace(knowledge_instruments_json="{}"))
    assert payload["knowledge_asset_class_check"]["reason_code"] == REASON_CODE
    assert payload["reasoning"][0] == before["reasoning"][0]
    gap_lines = [r for r in payload["reasoning"] if REASON_CODE in r]
    assert len(gap_lines) == 5
    assert payload["sub_allocations"] == before["sub_allocations"]
    assert payload["buckets"] == before["buckets"]
    # idempotent (GET-Reload)
    attach_to_strategy_payload(payload, _mandate(), SimpleNamespace(knowledge_instruments_json="{}"))
    assert len([r for r in payload["reasoning"] if REASON_CODE in r]) == 5


def test_attach_never_raises(monkeypatch):
    import services.knowledge_asset_class_gap as mod

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(mod, "evaluate_for_payload", boom)
    payload = {"reasoning": ["a"], "sub_allocations": SAA}
    attach_to_strategy_payload(payload, _mandate(), None)
    assert payload["knowledge_asset_class_check"]["status"] == "not_evaluable"
    assert payload["reasoning"] == ["a"]


def test_generate_response_schema_exposes_field():
    from schemas.allocation import TargetAllocationGenerateResponse

    assert "knowledge_asset_class_check" in TargetAllocationGenerateResponse.model_fields


# ---------------------------------------------------------------------------
# Router-Integration (Generate + GET-Reload)
# ---------------------------------------------------------------------------

@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'knowledge_gap.db'}", connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FakeRequest:
    def __init__(self):
        self.headers = {}
        self.client = SimpleNamespace(host="127.0.0.1")


def _seed(session) -> User:
    advisor = User(
        id="adv-kg", username="adv-kg", password_hash="hash", full_name="Advisor KG",
        role="advisor", is_active=1, created_at=NOW, updated_at=NOW,
    )
    session.add(advisor)
    session.add(Client(
        id="cl-kg", client_number="C-KG", first_name="Max", last_name="Muster",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0,
        is_qualified_investor=0, advisor_id=advisor.id, created_at=NOW, updated_at=NOW,
    ))
    session.add(Mandate(
        id="m-kg", client_id="cl-kg", mandate_number="M-KG",
        mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
        advisory_language="DE", opened_at="2026-01-01", created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    return advisor


def test_generate_endpoint_reports_gap_without_blocking(session_factory, monkeypatch):
    import routers.allocation as allocation_router

    with session_factory() as session:
        advisor = _seed(session)
        ra = SimpleNamespace(id="ra-kg", knowledge_instruments_json=_ki(Aktien=(1, 1)))
        monkeypatch.setattr(
            allocation_router, "generate_target_allocation",
            lambda **kwargs: {
                "target_allocation": SimpleNamespace(id="ta-kg"),
                "risk_assessment": ra,
                "reasoning": ["Ausgangspunkt ist die House Matrix fuer Score 7."],
                "sub_allocations": copy.deepcopy(SAA),
            },
        )
        monkeypatch.setattr(allocation_router, "evaluate_mandate_safely", lambda *a, **k: None)
        monkeypatch.setattr(allocation_router, "refresh_system_review_triggers", lambda *a, **k: None)
        monkeypatch.setattr(session, "refresh", lambda obj: None)
        result = allocation_router.generate_target_allocation_endpoint(
            mandate_id="m-kg", body=allocation_router.TargetAllocationGenerateRequest(),
            request=_FakeRequest(), db=session, current_user=advisor,
        )
        check = result["knowledge_asset_class_check"]
        assert check["reason_code"] == REASON_CODE
        assert "Aktien" not in [f["label"] for f in check["findings"]]
        assert any("Kunde über Private Equity informieren und dokumentieren." in r
                   for r in result["reasoning"])
        assert result["sub_allocations"] == SAA


def test_get_payload_endpoint_reports_gap(session_factory, monkeypatch):
    import routers.allocation as allocation_router

    with session_factory() as session:
        advisor = _seed(session)
        session.add(OptimizerPolicy(
            id="pol-kg", policy_name="p", version=1, is_current=1, valid_from=NOW,
            created_by=advisor.id, created_at=NOW, updated_at=NOW,
        ))
        session.commit()
        ra = SimpleNamespace(id="ra-kg", knowledge_instruments_json="{}")
        monkeypatch.setattr(allocation_router, "_current_target_allocation_or_none",
                            lambda db, mid: SimpleNamespace(id="ta-kg", policy_id="pol-kg"))
        monkeypatch.setattr(allocation_router, "_current_risk_assessment_or_none", lambda db, mid: ra)
        monkeypatch.setattr(allocation_router, "ensure_runtime_reference_data",
                            lambda *a, **k: (None, None))
        monkeypatch.setattr(allocation_router, "evaluate_mandate_safely", lambda *a, **k: None)
        monkeypatch.setattr(
            allocation_router, "build_target_payload_from_allocation",
            lambda **kwargs: {"reasoning": ["x"], "sub_allocations": copy.deepcopy(SAA)},
        )
        result = allocation_router.get_current_allocation_payload(
            mandate_id="m-kg", db=session, current_user=advisor,
        )
        assert result["knowledge_asset_class_check"]["reason_code"] == REASON_CODE
        assert any(REASON_CODE in r for r in result["reasoning"])


# ---------------------------------------------------------------------------
# Beratungsprotokoll-PDF
# ---------------------------------------------------------------------------

def test_protocol_hints_from_persisted_target_allocation(monkeypatch):
    import services.portfolio_engine as pe

    monkeypatch.setattr(pe, "_current_risk_assessment_or_none",
                        lambda db, mid: SimpleNamespace(knowledge_instruments_json="{}"))
    ta = SimpleNamespace(sub_allocations_json=json.dumps(SAA))
    hints = protocol_hints_for_mandate(None, _mandate(), ta)
    assert len(hints) == 5 and all(REASON_CODE in h for h in hints)
    # Fallback auf Buckets ohne Sleeves: Alternative ohne Sub-Klasse -> keine Zeile.
    ta_buckets = SimpleNamespace(
        sub_allocations_json=None, target_equities_bps=0, target_bonds_bps=0,
        target_real_estate_bps=0, target_alternatives_bps=500, target_liquidity_bps=0,
    )
    assert len(protocol_hints_for_mandate(None, _mandate(), ta_buckets)) == 1
    assert protocol_hints_for_mandate(None, _mandate("Professioneller Kunde"), ta) == []


def test_protokoll_pdf_renders_knowledge_gap_section():
    from datetime import date

    from services.pdf.base import PDFContext, ProtokollData
    from services.pdf.documents.protokoll import build_protokoll_flowables

    ctx = PDFContext(
        mandate_name="M-1", report_date=date(2026, 10, 21),
        advisor_name="A", base_currency="CHF",
    )
    hint = ("Kenntnislücke [KNOWLEDGE_GAP_ASSET_CLASS]: Die SAA enthält Private Equity (3,0 %), "
            "… Kunde über Private Equity informieren und dokumentieren.")
    data = ProtokollData(mandate_number="M-1", knowledge_gap_hints=[hint])
    texts = [getattr(f, "text", "") for f in build_protokoll_flowables(ctx, data)]
    assert any("KENNTNISSE ZU DEN ANLAGEKLASSEN DER STRATEGIE" in t.upper() for t in texts)
    assert any("Kunde über Private Equity informieren und dokumentieren." in t for t in texts)
    assert any("Allokation wurde dadurch nicht" in t for t in texts)

    empty = [getattr(f, "text", "") for f in build_protokoll_flowables(ctx, ProtokollData())]
    assert not any("KENNTNISSE ZU DEN ANLAGEKLASSEN DER STRATEGIE" in t.upper() for t in empty)


def test_protokoll_data_builder_wires_hints():
    src = (BACKEND_ROOT / "routers" / "pdf_reports.py").read_text(encoding="utf-8")
    body = src.split("def _build_protokoll_data", 1)[1].split("\ndef ", 1)[0]
    assert "protocol_hints_for_mandate" in body and "knowledge_gap_hints=" in body


# ---------------------------------------------------------------------------
# Monolith: AA-Ansicht
# ---------------------------------------------------------------------------

def _js_function(name: str) -> str:
    marker = f"function {name}("
    assert marker in HTML, f"{name} fehlt"
    start = HTML.index(marker)
    return HTML[start:HTML.index("\n}\n", start)]


def test_monolith_aa_view_renders_knowledge_gap_card():
    fn = _js_function("renderActionCards")
    assert "knowledge_asset_class_check" in fn
    assert "KNOWLEDGE_GAP_ASSET_CLASS" in fn
    helper = _js_function("aaKnowledgeGapCardBody")
    assert "findings" in helper and "action" in helper
