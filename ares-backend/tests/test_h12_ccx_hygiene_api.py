"""H12 Hygienepaket -- API-nahe Faelle (Fixtures des Thierry-Walkthroughs).

* N-909-20 / route-spezifisches FX-Quelleninventar: Risikoprofil und Vertrag
  pruefen nur die FX-Basis der Betraege, die sie drucken (Beratungsvermoegen);
  eine unbelegte Fremdwaehrung in einer anderen Quelle sperrt sie nicht mehr,
  sperrt aber weiterhin die laufbasierten Dokumente.
* N-909-21 G: die Druckpruefung erfasst Cashflows und Zufluesse.
* N-909-21 K: eine leere bzw. NULL-Quelle gilt nie als belegter Kurs.
* Inventar ``services.print_fx_gate.ROUTE_FX_SOURCES`` deckt jede Kunden-PDF-
  Route ab und stimmt mit dem Code der Route ueberein (AST).
"""
from __future__ import annotations

import ast

import pytest
from sqlalchemy import text

from tests.test_ccx_p3_n2_pdf_sweep import _set_usd, _text
from tests.test_ccx_p3_strict_fx_channels import USD_DEPOT, _code
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    _seed_risk_profile,
    _seed_wealth,
    advisor_user,
    api,
    session_factory,
)
from tests.test_g7_full_api_path_parity import _create_client_and_mandate

USD_OTHER = dict(USD_DEPOT, label="Depot USD extern", assignment="Anderes Vermögen")
USD_CASHFLOW = {"cashflow_type": "Income", "label": "Rente USD", "amount_rappen": 12_000_00, "currency": "USD",
                "frequency": "jährlich", "nature": "wiederkehrend", "data_classification": "synthetic"}
USD_INFLOW = {"label": "Erbschaft USD", "source_type": "Erbschaft", "amount_rappen": 50_000_00,
              "expected_year": 2031, "currency": "USD", "data_classification": "synthetic"}


def _advisory_chf(rows) -> int:
    return sum(int(r["current_value_rappen"]) for r in rows
               if r.get("assignment") == "Beratungsvermögen" and r.get("currency", "CHF") == "CHF"
               and int(r["current_value_rappen"]) > 0)


def _chf(rappen: int) -> str:
    return "CHF " + f"{rappen // 100:,}".replace(",", "'")


def _client_with_usd_source(api, advisor_user, kind):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    rows = _seed_wealth(api, client_id)
    if kind == "position_other":
        resp = api.post(f"/clients/{client_id}/wealth-positions", json=USD_OTHER)
    elif kind == "cashflow":
        resp = api.post(f"/clients/{client_id}/cashflows", json=USD_CASHFLOW)
    else:
        resp = api.post(f"/clients/{client_id}/wealth-inflows", json=dict(USD_INFLOW))
    assert resp.status_code == 201, resp.text[:300]
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    return client_id, mandate_id, rows


@pytest.mark.parametrize("kind", ["position_other", "cashflow", "inflow"])
def test_risk_profile_and_contract_only_check_the_fx_they_print(api, advisor_user, session_factory, kind):
    """N-909-20: USD (Ersatzkurs, nicht belegt) nur in einer nicht gedruckten
    Quelle -> Risikoprofil und Vertrag liefern (vorher 409 CCX_FX_BASIS_MISSING)
    mit dem CHF-Beratungsvermoegen. Die laufbasierte Druckpruefung sperrt
    dieselbe Lage weiterhin (Mutation G: Cashflows/Zufluesse zaehlen)."""
    from models.mandates import Mandate
    from services.currency.fx_rates import FxBasisError
    from services.print_fx_gate import assert_print_fx_basis_current, mandate_amount_currencies

    _client_id, mandate_id, rows = _client_with_usd_source(api, advisor_user, kind)
    expected = _chf(_advisory_chf(rows))
    for report in ("risikoprofil.pdf", "vertrag.pdf"):
        resp = api.get(f"/mandates/{mandate_id}/reports/{report}")
        assert resp.status_code == 200, (report, resp.text[:300])
        assert f"Beratungsvermögen {expected}" in _text(resp), report
    with session_factory() as db:
        mandate = db.get(Mandate, mandate_id)
        assert "USD" in mandate_amount_currencies(db, mandate)
        with pytest.raises(FxBasisError) as exc:
            assert_print_fx_basis_current(db, mandate)
        assert exc.value.reason_code == "CCX_FX_BASIS_MISSING"


def test_risk_profile_blocks_when_the_printed_wealth_needs_an_unattested_rate(api, advisor_user, session_factory):
    """Gegenprobe zu N-909-20: steckt die USD-Position im gedruckten
    Beratungsvermoegen, sperren Risikoprofil und Vertrag typisiert; mit
    belegtem Kurs liefern sie den umgerechneten Betrag."""
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user, "CHF")
    rows = _seed_wealth(api, client_id)
    assert api.post(f"/clients/{client_id}/wealth-positions", json=USD_DEPOT).status_code == 201
    assert _seed_risk_profile(api, mandate_id).get("final_profile")
    for report in ("risikoprofil.pdf", "vertrag.pdf"):
        resp = api.get(f"/mandates/{mandate_id}/reports/{report}")
        assert resp.status_code == 409 and _code(resp) == "CCX_FX_BASIS_MISSING", (report, resp.text[:300])
    _set_usd(api, "Manual")  # 0.88, ausdruecklich geprueft
    expected = _chf(_advisory_chf(rows) + 88_000_04)  # 100'000.05 USD x 0.88
    for report in ("risikoprofil.pdf", "vertrag.pdf"):
        resp = api.get(f"/mandates/{mandate_id}/reports/{report}")
        assert resp.status_code == 200, (report, resp.text[:300])
        assert f"Beratungsvermögen {expected}" in _text(resp), report


@pytest.mark.parametrize("source", ["", "   ", None])
def test_empty_or_null_rate_source_is_never_attested(api, session_factory, source):
    """N-909-21 K: ``fx_rates.source`` ist nullable; eine leere/NULL-Quelle
    (Altzeile) gilt wie der Ersatzkurs als fehlend -- auch mit frischem Datum."""
    from services.currency.fx_rates import FxBasisError, FXRateSource
    from services.fx_basis import load_fx_basis

    assert api.put("/fx-rates", json={"rates": [{"currency": "USD", "rate": 0.9123}]}).status_code == 200
    with session_factory() as db:
        assert load_fx_basis(db, "CHF", ["USD"]).status("USD") == "OK"  # Vorbedingung
        db.execute(text("UPDATE fx_rates SET source = :s WHERE currency = 'USD' AND is_current = 1"), {"s": source})
        db.commit()
    with session_factory() as db:
        assert load_fx_basis(db, "CHF", ["USD"]).status("USD") == "MISSING"
        with pytest.raises(FxBasisError) as exc:
            FXRateSource.from_db_strict_for_model(db).convert_storage_amount(100_00, "USD", "CHF")
        assert exc.value.reason_code == "CCX_FX_BASIS_MISSING"


# ── Route-spezifisches FX-Quelleninventar ───────────────────────────────────

# Strikte Live-Basis im Aufrufgraph: direkt (load_fx_basis/from_db_strict_for_model)
# oder ueber die Builder, die sie nutzen; der Beratungsbericht delegiert an den
# Aggregator (services.advisory_report, strikt; Verhaltensbeleg im 12-PDF-Sweep
# tests/test_ccx_p3_n2_pdf_sweep.py: 409 CCX_FX_BASIS_MISSING bei Ersatzkurs).
LIVE_STRICT_MARKERS = {"load_fx_basis", "from_db_strict_for_model", "_advisory_wealth_positions",
                       "_build_anlagestrategie_data", "render_advisory_report_pdf"}


def test_route_fx_inventory_covers_every_customer_pdf_route_and_matches_the_code():
    from services.print_fx_gate import (
        FX_ADVISORY_POSITIONS_LIVE,
        FX_LIVE_STRICT_BUILDER,
        FX_RUN_AMOUNTS,
        ROUTE_FX_SOURCES,
    )
    from services.recommendation_release_gate import REPORT_CLIENT_FACING, REPORT_ROUTE_CLASSIFICATION
    from tests.test_ccx_p4_allocation_publish import _functions, _referenced_names

    functions = _functions("routers/pdf_reports.py")
    route_to_function = {}
    for node in functions.values():
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call) and deco.args and isinstance(deco.args[0], ast.Constant):
                route_to_function[f"GET {deco.args[0].value}"] = node.name
    # Alle Kunden-PDFs des Moduls (inkl. Kundeninformation, die nicht in der
    # Strategie-Klassifikation steht); die klassifizierten sind darin enthalten.
    client_pdf = {fn for route, fn in route_to_function.items() if route.endswith(".pdf")}
    classified = {route_to_function[r] for r, (klass, _w) in REPORT_ROUTE_CLASSIFICATION.items()
                  if klass == REPORT_CLIENT_FACING and r in route_to_function}
    assert classified <= client_pdf
    assert len(client_pdf) == 12
    assert client_pdf == set(ROUTE_FX_SOURCES), sorted(client_pdf ^ set(ROUTE_FX_SOURCES))

    def hull(entry):
        seen, stack = set(), [entry]
        while stack:
            name = stack.pop()
            if name in seen or name not in functions:
                continue
            seen.add(name)
            stack.extend(_referenced_names(functions[name]) & set(functions))
        names = set()
        for name in seen:
            names |= _referenced_names(functions[name])
        return names

    for name, (klass, printed) in ROUTE_FX_SOURCES.items():
        assert printed.strip(), name
        direct = _referenced_names(functions[name])
        if klass == FX_RUN_AMOUNTS:
            assert "_assert_client_pdf_fx_basis" in direct, f"{name}: Druckpruefung fehlt"
        elif klass == FX_ADVISORY_POSITIONS_LIVE:
            assert "_assert_client_pdf_fx_basis" not in direct, f"{name}: Uebersperrung (N-909-20)"
            assert "_advisory_wealth_from_capture" in hull(name), name
        else:
            assert klass == FX_LIVE_STRICT_BUILDER, name
            assert "_assert_client_pdf_fx_basis" not in direct, name
            assert hull(name) & LIVE_STRICT_MARKERS, f"{name}: keine strikte Live-Basis im Aufrufgraph"
