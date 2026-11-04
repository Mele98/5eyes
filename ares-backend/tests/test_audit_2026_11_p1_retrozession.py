"""Audit 2026-11, Paket P1: Retrozessions-Offenlegung am Produkt (Luecke L1).

Art. 26 FIDLEG, Art. 400 OR, BGE 132 III 460 / 137 III 393. Satz > 0 ->
Offenlegungszeile (nie im Total); Satz NULL -> Pflichtwarnung + Kennzeichnung;
manuelle Mandatserfassung desselben Anbieters wird zusammengefuehrt, nicht
doppelt ausgewiesen. PDF-Baustein eigenstaendig.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from main import app  # noqa: E402
from models.review import ConflictOfInterestDisclosure, Product  # noqa: E402
from schemas.review import (  # noqa: E402
    declared_hedge_currency,
    isin_is_valid,
    isin_status,
    master_data_gaps,
    normalize_isin,
)
from services.cost_disclosure import build_cost_disclosure, calculate_cost_disclosure  # noqa: E402
from test_product_universe_fee_override import _mandate, _seed  # noqa: E402
from test_product_universe_fee_override import session_factory as cost_session_factory  # noqa: E402,F401
from test_products_fund_universe import _add_product, _client_for, _seed_tenants  # noqa: E402
from test_optimizer_shadow_mode import session_factory  # noqa: E402,F401

REVISION = "a8d3c5e7f9b1"
DOWN_REVISION = "f6a2c8e4b1d7"
NEW_COLUMNS = (
    "domicile", "is_hedged", "hedge_currency", "ter_source", "ter_as_of",
    "retrocession_bps", "retrocession_source", "is_house_product",
    "distribution_policy", "valor", "minimum_investment_minor_units",
)
VALID_ISIN = "ZZEXAMPLE019"  # gueltige Pruefziffer, nicht vergebenes Praefix


def _create_payload(**overrides):
    payload = {
        "product_name": "P1 Testfonds", "product_type": "ETF", "asset_class": "Aktien",
        "currency": "CHF", "suitability_profile_from": 3, "suitability_profile_to": 10,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 3. Retrozession im Kostenausweis (reine Rechnung)
# ---------------------------------------------------------------------------


def _calc(products, inducements=None):
    return calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000,
        positions=[{"amount_rappen": p["amount_rappen"], "ter_bps": 30} for p in products],
        fee_model={"default_advisory_fee_bps": 50},
        inducements=inducements,
        product_retrocessions=products,
    )


def _product(name="Fonds A", *, rate=None, provider="Anbieter A", amount=100_000_000, source=None):
    return {
        "product_id": f"id-{name}", "product_name": name, "isin": None, "provider": provider,
        "amount_rappen": amount, "retrocession_bps": rate,
        "retrocession_source": source if source is not None else ("Vertrag" if rate is not None else None),
    }


def test_retro_present_without_mandate_entry_gets_disclosure_line_outside_total():
    without = _calc([_product(rate=0)])
    payload = _calc([_product(rate=40)])
    lines = [i for i in payload["cost_items"] if i["key"] == "retrocession_product"]
    assert len(lines) == 1, payload["cost_items"]
    line = lines[0]
    assert line["amount_rappen"] == 400_000  # 40 bps auf CHF 1 Mio.
    assert line["included_in_total"] is False
    assert line["requires_resolution"] is True
    assert "Fonds A" in line["label"]
    # nie im Total: Totale identisch zum retrofreien Fall
    assert payload["totals"] == without["totals"]
    retro = payload["product_retrocessions"]
    assert retro["present_count"] == 1 and retro["unresolved_count"] == 1 and not retro["complete"]
    assert any("zahlt eine Retrozession" in w for w in payload["warnings"])


def test_retro_unknown_gives_mandatory_warning_and_marking():
    payload = _calc([_product("Fonds A"), _product("Fonds B", rate=0)])
    retro = payload["product_retrocessions"]
    by_name = {line["product_name"]: line for line in retro["lines"]}
    assert by_name["Fonds A"]["status"] == "unknown"
    assert by_name["Fonds A"]["estimated_annual_rappen"] is None
    assert "nicht als retrozessionsfrei" in by_name["Fonds A"]["treatment_label"]
    assert by_name["Fonds B"]["status"] == "none"
    assert retro["unknown_count"] == 1 and not retro["complete"]
    assert any("Retrozession unbekannt" in w and "Fonds A" in w for w in payload["warnings"])
    assert not [i for i in payload["cost_items"] if i["key"] == "retrocession_product"]


def test_all_retro_free_products_are_complete_without_warning():
    payload = _calc([_product("Fonds A", rate=0), _product("Fonds B", rate=0)])
    assert payload["product_retrocessions"]["complete"] is True
    assert not any("Retrozession" in w for w in payload["warnings"])


@pytest.mark.parametrize("entry, treatment", [
    ({"reimbursed_to_client": True}, "reimbursed"),
    ({"disclosed_to_client": True, "waiver_document_id": "doc-1"}, "waiver_documented"),
    ({}, "unresolved"),
])
def test_mandate_entry_same_provider_is_merged_not_double_disclosed(entry, treatment):
    inducement = {
        "amount_rappen": 400_000, "frequency": "jährlich", "provider": "  anbieter a ",
        "reimbursed_to_client": False, "disclosed_to_client": False, "waiver_document_id": None,
        **entry,
    }
    payload = _calc([_product(rate=40)], inducements=[inducement])
    retro_lines = [i for i in payload["cost_items"] if i["category"] == "Vergütungen von Dritten"]
    # genau EINE Zeile: die manuelle Mandatszeile, keine zusaetzliche Produktzeile
    assert len(retro_lines) == 1, retro_lines
    assert retro_lines[0]["key"] != "retrocession_product"
    line = payload["product_retrocessions"]["lines"][0]
    assert line["covered_by_mandate_entry"] is True
    assert line["treatment"] == treatment
    assert line["requires_resolution"] is (treatment == "unresolved")


def test_mandate_entry_other_provider_does_not_cover_product():
    inducement = {"amount_rappen": 350_000, "frequency": "jährlich", "provider": "Anbieter B",
                  "reimbursed_to_client": True}
    payload = _calc([_product(rate=40)], inducements=[inducement])
    keys = [i["key"] for i in payload["cost_items"] if i["category"] == "Vergütungen von Dritten"]
    assert sorted(keys) == ["retrocession_product", "retrocession_reimbursed"]


def test_calculation_without_product_context_is_unchanged():
    payload = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000,
        positions=[{"amount_rappen": 100_000_000, "ter_bps": 30}],
        fee_model={"default_advisory_fee_bps": 50},
    )
    assert "product_retrocessions" not in payload


# ---------------------------------------------------------------------------
# 4. Retrozession im Kostenausweis (DB-Pfad, Lauf mit Produkt)
# ---------------------------------------------------------------------------


def _set_product_retro(SF, rate, source="Vertrag", provider="Anbieter A"):
    with SF() as s:
        product = s.get(Product, "prod-puf")
        product.retrocession_bps = rate
        product.retrocession_source = source if rate is not None else None
        product.provider = provider
        s.commit()


def test_build_cost_disclosure_reads_retro_from_product(cost_session_factory):
    _seed(cost_session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20)
    with cost_session_factory() as db:
        unknown = build_cost_disclosure(db, _mandate(cost_session_factory))
    _set_product_retro(cost_session_factory, 40)
    with cost_session_factory() as db:
        present = build_cost_disclosure(db, _mandate(cost_session_factory))
    assert unknown["product_retrocessions"]["lines"][0]["status"] == "unknown"
    assert any("Retrozession unbekannt" in w for w in unknown["warnings"])
    items = [i for i in present["cost_items"] if i["key"] == "retrocession_product"]
    assert len(items) == 1 and items[0]["amount_rappen"] == 400_000
    assert present["totals"] == unknown["totals"]


def test_build_cost_disclosure_merges_manual_mandate_entry(cost_session_factory):
    _seed(cost_session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20)
    _set_product_retro(cost_session_factory, 40)
    with cost_session_factory() as s:
        s.add(ConflictOfInterestDisclosure(
            id="coi-1", mandate_id="mandate-puf", conflict_type="Retrozession / Inducement",
            description="Bestandespflege", inducement_provider="Anbieter A",
            inducement_amount_rappen=400_000, inducement_frequency="jährlich",
            disclosed_to_client=1, reimbursed_to_client=0, waiver_document_id="doc-1",
            client_acknowledged=1, disclosed_by="advisor-puf",
            created_at="2026-11-03T00:00:00Z", updated_at="2026-11-03T00:00:00Z",
        ))
        s.commit()
    with cost_session_factory() as db:
        payload = build_cost_disclosure(db, _mandate(cost_session_factory))
    retro_items = [i for i in payload["cost_items"] if i["category"] == "Vergütungen von Dritten"]
    assert [i["key"] for i in retro_items] == ["retrocession_disclosed"]
    line = payload["product_retrocessions"]["lines"][0]
    assert line["covered_by_mandate_entry"] and line["treatment"] == "waiver_documented"
    assert payload["product_retrocessions"]["complete"] is True


def test_cost_disclosure_response_schema_keeps_retro_block():
    from schemas.cost_disclosure import CostDisclosureResponse

    payload = _calc([_product(rate=40)])
    dumped = CostDisclosureResponse(**payload).model_dump()
    assert dumped["product_retrocessions"]["lines"][0]["status"] == "present"
    assert dumped["product_retrocessions"]["lines"][0]["treatment"] == "unresolved"


# ---------------------------------------------------------------------------
# 5. PDF: eigener Baustein im Kostenausweis
# ---------------------------------------------------------------------------


def _pdf_text(payload) -> str:
    from reportlab.platypus import Paragraph, Table

    from services.pdf.components.kostenausweis import build_retrocession_flowables
    from services.pdf.components.advisory_palette import make_advisory_styles as build_styles

    def walk(flowables):
        for flowable in flowables:
            if isinstance(flowable, Paragraph):
                yield flowable.getPlainText()
            elif isinstance(flowable, Table):
                for row in flowable._cellvalues:
                    for cell in row:
                        yield from walk(cell if isinstance(cell, list) else [cell])

    return "\n".join(walk(build_retrocession_flowables(payload, build_styles())))


def test_pdf_component_lists_retro_per_product():
    payload = _calc([_product("Fonds A", rate=40), _product("Fonds B")])
    text = _pdf_text(payload)
    assert "Fonds A" in text and "Fonds B" in text
    assert "unbekannt" in text
    assert "Klärung erforderlich" in text
    assert "Art. 26 FIDLEG" in text


def test_pdf_component_renders_nothing_without_product_context():
    assert _pdf_text({"cost_items": [], "currency": "CHF"}) == ""


def test_kostenausweis_includes_retro_component():
    from services.pdf.components.kostenausweis import build_kostenausweis_flowables
    from services.pdf.components.advisory_palette import make_advisory_styles as build_styles
    from reportlab.platypus import Paragraph

    payload = _calc([_product("Fonds A", rate=40)])
    flow = build_kostenausweis_flowables(payload, build_styles())
    titles = [f.getPlainText() for f in flow if isinstance(f, Paragraph)]
    assert any("RETROZESSIONEN" in t for t in titles), titles



# ---------------------------------------------------------------------------
# N-861-1 (Pruefrunde #861): Verzicht wirkt nur im Umfang der Aufklaerung
# (BGE 137 III 393) -- Summe je Anbieter, mehrere Mandatszeilen, product_id.
# ---------------------------------------------------------------------------


def _entry(amount, *, provider="Anbieter A", product_id=None, waiver=True, reimbursed=False,
           frequency="jährlich"):
    return {
        "amount_rappen": amount, "frequency": frequency, "provider": provider,
        "product_id": product_id, "reimbursed_to_client": reimbursed,
        "disclosed_to_client": waiver, "waiver_document_id": "doc-1" if waiver else None,
    }


def test_small_waiver_does_not_cover_large_product_retrocessions():
    """Reproducer aus der Pruefrunde: Verzicht CHF 10 deckte zwei Produkte
    (CHF 500 + CHF 1'000) vollstaendig ab, complete=True, keine Warnung."""
    products = [
        _product("Fonds A", rate=50, amount=10_000_000),   # CHF 500 p.a.
        _product("Fonds B", rate=100, amount=10_000_000),  # CHF 1'000 p.a.
    ]
    payload = _calc(products, inducements=[_entry(1_000)])  # CHF 10 Verzicht
    retro = payload["product_retrocessions"]
    by_name = {line["product_name"]: line for line in retro["lines"]}
    for line in by_name.values():
        assert line["covered_by_mandate_entry"] is True
        assert line["treatment"] == "partially_covered"
        assert line["requires_resolution"] is True
    assert sum(line["unresolved_rappen"] for line in by_name.values()) == 150_000 - 1_000
    assert sum(line["mandate_resolved_rappen"] for line in by_name.values()) == 1_000
    assert retro["complete"] is False and retro["unresolved_count"] == 2
    assert any("deckt für Fonds A, Fonds B nur CHF 10.00 von geschätzt CHF 1'500.00" in w
               for w in payload["warnings"]), payload["warnings"]
    # Der nicht offengelegte Teil erscheint als eigene Kostenzeile, nie im Total.
    rest = [i for i in payload["cost_items"] if i["key"] == "retrocession_product"]
    assert sum(i["amount_rappen"] for i in rest) == 149_000
    assert all(i["included_in_total"] is False and i["requires_resolution"] for i in rest)


def test_full_waiver_within_tolerance_covers_all_products_of_provider():
    products = [_product("Fonds A", rate=50, amount=10_000_000), _product("Fonds B", rate=100, amount=10_000_000)]
    payload = _calc(products, inducements=[_entry(140_000)])  # 1'400 vs 1'500 -> innerhalb 10 %
    retro = payload["product_retrocessions"]
    assert retro["complete"] is True
    assert {line["treatment"] for line in retro["lines"]} == {"waiver_documented"}
    assert not [i for i in payload["cost_items"] if i["key"] == "retrocession_product"]


def test_multiple_mandate_entries_of_same_provider_are_summed():
    products = [_product("Fonds A", rate=100, amount=10_000_000)]  # CHF 1'000
    one = _calc(products, inducements=[_entry(50_000)])
    two = _calc(products, inducements=[_entry(50_000), _entry(50_000, reimbursed=True, waiver=False)])
    assert one["product_retrocessions"]["lines"][0]["treatment"] == "partially_covered"
    line = two["product_retrocessions"]["lines"][0]
    assert line["mandate_resolved_rappen"] == 100_000 and line["requires_resolution"] is False
    assert two["product_retrocessions"]["complete"] is True


def test_non_annual_mandate_amount_does_not_cover_annual_retrocession():
    products = [_product("Fonds A", rate=100, amount=10_000_000)]
    payload = _calc(products, inducements=[_entry(100_000, frequency="einmalig")])
    line = payload["product_retrocessions"]["lines"][0]
    assert line["treatment"] == "unresolved" and line["requires_resolution"] is True
    assert line["mandate_disclosed_rappen"] == 100_000  # offengelegt, aber nicht geregelt


def test_product_bound_entry_wins_over_provider_and_covers_only_its_product():
    products = [
        _product("Fonds A", rate=100, amount=10_000_000),
        _product("Fonds B", rate=100, amount=10_000_000),
    ]
    payload = _calc(products, inducements=[_entry(100_000, product_id="id-Fonds A", provider="Anders AG")])
    by_name = {line["product_name"]: line for line in payload["product_retrocessions"]["lines"]}
    assert by_name["Fonds A"]["treatment"] == "waiver_documented"
    assert by_name["Fonds A"]["requires_resolution"] is False
    assert by_name["Fonds B"]["covered_by_mandate_entry"] is False
    assert by_name["Fonds B"]["treatment"] == "unresolved"


def test_conflict_product_id_must_be_visible_to_tenant(session_factory):
    from test_products_fund_universe import _add_product, _client_for, _seed_tenants
    from models.clients import Client
    from models.mandates import Mandate
    from models.users import User

    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    own = _add_product(session_factory, product_name="Eigen", tenant_id="firm-a")
    foreign = _add_product(session_factory, product_name="Fremd", tenant_id="firm-b")
    now = "2026-11-04T00:00:00Z"
    with session_factory() as s:
        if s.get(User, "u-a") is None:
            s.add(User(id="u-a", username="u-a", password_hash="h", full_name="A", role="admin",
                       is_active=1, tenant_id="firm-a", created_at=now, updated_at=now))
        s.add(Client(id="c-a", client_number="C-A", first_name="T", last_name="X", advisor_id="u-a",
                     tenant_id="firm-a", created_at=now, updated_at=now))
        s.add(Mandate(id="m-a", client_id="c-a", tenant_id="firm-a", mandate_number="M-A",
                      mandate_type="Anlageberatung", opened_at=now, created_at=now, updated_at=now))
        s.commit()
    body = {"conflict_type": "Retrozession / Inducement", "description": "Bestandespflege",
            "inducement_provider": "Anbieter", "inducement_amount_rappen": 10_000,
            "inducement_frequency": "jährlich"}
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            ok = client.post("/mandates/m-a/conflicts", json={**body, "product_id": own})
            leak = client.post("/mandates/m-a/conflicts", json={**body, "product_id": foreign})
    finally:
        app.dependency_overrides.clear()
    assert ok.status_code == 201, ok.text
    assert ok.json()["product_id"] == own
    assert leak.status_code == 404, leak.text


# ---------------------------------------------------------------------------
# N-861-2: is_complete beruecksichtigt die Produkt-Retrozession
# ---------------------------------------------------------------------------


def test_is_complete_false_when_retro_unknown_or_unresolved():
    unknown = _calc([_product("Fonds A")])
    unresolved = _calc([_product("Fonds A", rate=40)])
    partial = _calc([_product("Fonds A", rate=100, amount=10_000_000)], inducements=[_entry(1_000)])
    free = _calc([_product("Fonds A", rate=0)])
    assert unknown["is_complete"] is False
    assert unresolved["is_complete"] is False
    assert partial["is_complete"] is False
    assert free["is_complete"] is True  # Gebuehr + TER vollstaendig, Retro bekannt und frei
    # Ohne Produktbezug unveraendert (keine Retro-Aussage moeglich)
    plain = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000,
        positions=[{"amount_rappen": 100_000_000, "ter_bps": 30}],
        fee_model={"default_advisory_fee_bps": 50},
    )
    assert plain["is_complete"] is True


# ---------------------------------------------------------------------------
# N-861-3: Kunden-PDF -- Grammatik und beschriftete Betraege
# ---------------------------------------------------------------------------


def test_pdf_note_grammar_and_labelled_amounts():
    payload = _calc([_product("Fonds A", rate=100, amount=10_000_000)], inducements=[_entry(1_000)])
    text = _pdf_text(payload)
    assert "ausdrücklich verzichtet haben" in text
    assert "verzichtet hat" not in text
    assert "geschätzt CHF 1'000 / aufgeklärt CHF 10" in text.replace("\u2019", "'"), text


def test_ui_module_has_no_dead_module_reference_and_labels_amounts():
    module = (BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "product-master-data.js").read_text(encoding="utf-8")
    assert "services/retrocession_disclosure.py" not in module
    assert "' / aufgeklärt '" in module and "'geschätzt '" in module
