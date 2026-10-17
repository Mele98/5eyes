"""STALE-ALLOCATION-HIDE-TARGETS-001 (Owner-Entscheid 2026-10-14).

ALLOCATION-INPUT-STALENESS-001 hat Sektion 8 (Asset Allocation) und
Sektion 13 (Building Blocks) des Beratungsreports einen Hinweis "Soll-
Allokation veraltet" gegeben -- die alten Zielgewichte, Bandbreiten und
Drifts wurden aber weiterhin daneben gedruckt. Owner-Entscheid: ist die
Soll-Allokation veraltet (Risikoprofil ODER geaenderte Inputs), werden die
alten Zielzahlen AUSGEBLENDET; Payload, PDF und React zeigen nur den
Hinweis.

Erwartungen:
- Payload: Zielfelder (soll/drift/band/in_band, target_bps, Constraints aus
  der TA) sind None bzw. leer, ``soll_ausgeblendet`` ist True.
- Nicht-veraltet: unveraendert (Positivkontrolle gegen ein immer-
  ausgeblendet).
- PDF: kein IST/SOLL-Chart, keine Building-Blocks-Tabelle, keine
  Zielprozente -- nur der Hinweis.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from reportlab.platypus import Paragraph, Table  # noqa: E402

from services.advisory_report import (  # noqa: E402
    _build_asset_allocation,
    compute_advisory_report,
)
from tests.test_allocation_input_staleness_surfaces import (  # noqa: E402,F401
    _current_ta,
    _reduce_largest_position,
    _seed,
    session,
)

_BUCKET_KEYS = ("liquidity", "bonds", "equities", "real_estate", "alternatives")


def _dc(*, stale: bool, inputs_stale: bool = False) -> dict:
    return {
        "target_allocation_stale": stale,
        "target_allocation_inputs_stale": inputs_stale,
        "buckets": {
            "equities": {
                "ist_bps": 4000, "soll_bps": 5300,
                "band_min_bps": 4500, "band_max_bps": 5500, "in_band": False,
            },
            "bonds": {
                "ist_bps": 6000, "soll_bps": 4700,
                "band_min_bps": 4000, "band_max_bps": 5000, "in_band": False,
            },
        },
    }


# ---------------------------------------------------------------------------
# Sektion 8 -- Payload (Unit)
# ---------------------------------------------------------------------------

def test_section8_not_stale_keeps_target_numbers():
    aa = _build_asset_allocation(_dc(stale=False))
    assert aa["soll_ausgeblendet"] is False
    eq = next(it for it in aa["items"] if it["key"] == "equities")
    assert eq["soll_bps"] == 5300
    assert eq["drift_bps"] == -1300
    assert eq["band_min_bps"] == 4500
    assert aa["soll_bps"]["Aktien"] == 5300


def test_section8_stale_nulls_all_target_fields():
    aa = _build_asset_allocation(_dc(stale=True, inputs_stale=True))
    assert aa["target_allocation_stale"] is True
    assert aa["soll_ausgeblendet"] is True
    for it in aa["items"]:
        assert it["soll_bps"] is None, it
        assert it["drift_bps"] is None, it
        assert it["band_min_bps"] is None, it
        assert it["band_max_bps"] is None, it
        assert it["in_band"] is None, it
    assert aa["soll_bps"] is None
    assert aa["drift_bps"] is None
    # Echte IST-Werte bleiben (keine Zielzahl).
    eq = next(it for it in aa["items"] if it["key"] == "equities")
    assert eq["ist_bps"] == 4000
    assert "Vermoegen, Cashflows oder Ziele" in aa["staleness_hinweis"]


def test_section8_stale_shows_only_notice_not_drift_text_or_advisor_note():
    """Auto-Drift-Text ("Aktien Untergewicht 13 pp") und Berater-Anmerkung
    beziehen sich auf die alten Zielgewichte -> nur der Hinweis bleibt."""
    notes = MagicMock()
    notes.aa_anmerkungen = "Aktien liegen 13 pp unter dem Soll von 53 %."
    aa = _build_asset_allocation(_dc(stale=True), notes=notes)
    assert aa["anmerkungen"] == aa["staleness_hinweis"]
    assert "53" not in aa["anmerkungen"]
    assert "Risikoprofil" in aa["anmerkungen"]


def test_section8_stale_with_ist_from_soll_hides_ist_too():
    """ist_basiert_auf_soll: IST ist selbst aus den alten Empfehlungswerten
    abgeleitet -- also ebenfalls eine alte Zielzahl."""
    aa = _build_asset_allocation(_dc(stale=True), ist_basiert_auf_soll=True)
    for it in aa["items"]:
        assert it["ist_bps"] is None, it
    assert aa["ist_bps"] is None


# ---------------------------------------------------------------------------
# Integration (Foundation-Mandat): Sektion 8 + 13
# ---------------------------------------------------------------------------

def test_report_not_stale_keeps_building_block_targets(session):  # noqa: F811
    adv, mandate = _seed(session)
    rep = compute_advisory_report(session, mandate, advisor=adv)
    bb = rep["building_blocks"]
    assert bb["soll_ausgeblendet"] is False
    assert any((b["target_bps"] or 0) > 0 for b in bb["blocks"])
    assert rep["asset_allocation"]["soll_ausgeblendet"] is False


def test_report_stale_inputs_hides_section8_and_13_targets(session):  # noqa: F811
    adv, mandate = _seed(session)
    _reduce_largest_position(session, mandate)
    for client_facing in (False, True):
        rep = compute_advisory_report(
            session, mandate, advisor=adv, client_facing=client_facing,
        )
        bb = rep["building_blocks"]
        assert bb["target_allocation_stale"] is True
        assert bb["soll_ausgeblendet"] is True
        assert "Vermoegen, Cashflows oder Ziele" in bb["staleness_hinweis"]
        for b in bb["blocks"]:
            assert b["target_bps"] is None, b
            assert b["band_min_bps"] is None, b
            assert b["band_max_bps"] is None, b
        # Risikoquote der alten TA ist ebenfalls eine alte Zielgroesse.
        assert bb["constraints"] == []

        aa = rep["asset_allocation"]
        assert aa["soll_ausgeblendet"] is True
        assert all(it["soll_bps"] is None for it in aa["items"])
        assert aa["anmerkungen"] == aa["staleness_hinweis"]


def test_report_stale_risk_profile_hides_targets(session, monkeypatch):  # noqa: F811
    """Zweiter Staleness-Grund (Risikoprofil) blendet genauso aus."""
    adv, mandate = _seed(session)
    import services.risk_assessment_semantics as ras
    monkeypatch.setattr(
        ras, "target_allocation_predates_current_assessment",
        lambda ta, ra_id, *_a, **_k: True,
    )
    rep = compute_advisory_report(session, mandate, advisor=adv)
    bb = rep["building_blocks"]
    assert bb["soll_ausgeblendet"] is True
    assert "Risikoprofil" in bb["staleness_hinweis"]
    assert all(b["target_bps"] is None for b in bb["blocks"])
    assert rep["asset_allocation"]["soll_ausgeblendet"] is True


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _all_texts(flowables) -> list[str]:
    out: list[str] = []

    def walk(obj):
        if isinstance(obj, Paragraph):
            out.append(obj.text)
        elif isinstance(obj, Table):
            for row in obj._cellvalues:
                for cell in row:
                    if isinstance(cell, (list, tuple)):
                        for c in cell:
                            walk(c)
                    else:
                        walk(cell)
        elif isinstance(obj, str):
            out.append(obj)

    for f in flowables:
        walk(f)
    return out


def test_pdf_section13_stale_renders_notice_without_target_table():
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.documents.advisory_report import _build_building_blocks_flowables

    hinweis = "Hinweis: Soll-Allokation ist veraltet. Strategie neu berechnen."
    bb = {
        "blocks": [{"key": "equities", "label": "Aktien", "target_bps": None,
                    "band_min_bps": None, "band_max_bps": None}],
        "constraints": [],
        "methodologie": "",
        "target_allocation_stale": True,
        "soll_ausgeblendet": True,
        "staleness_hinweis": hinweis,
    }
    texts = _all_texts(_build_building_blocks_flowables(bb, make_advisory_styles()))
    assert any("Soll-Allokation ist veraltet" in t for t in texts), texts
    assert not any("Aktien" in t for t in texts), texts
    assert not any("Target" in t for t in texts), texts
    assert not any("Keine Building Blocks erfasst" in t for t in texts), texts


def test_pdf_section8_stale_renders_notice_without_chart():
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.documents.advisory_report import _build_asset_allocation_flowables

    aa = _build_asset_allocation(_dc(stale=True, inputs_stale=True))
    flowables = _build_asset_allocation_flowables(aa, make_advisory_styles())
    texts = _all_texts(flowables)
    assert any("Vermoegen, Cashflows oder Ziele" in t for t in texts), texts
    # Kein Chart (Tabelle mit Anlageklassen-Labels / Prozenten).
    assert not any("Aktien" in t for t in texts), texts
    assert not any("%" in t for t in texts), texts


def test_pdf_section8_not_stale_still_renders_chart():
    from services.pdf.components.advisory_palette import make_advisory_styles
    from services.pdf.documents.advisory_report import _build_asset_allocation_flowables

    aa = _build_asset_allocation(_dc(stale=False))
    texts = _all_texts(_build_asset_allocation_flowables(aa, make_advisory_styles()))
    assert any("Aktien" in t for t in texts), texts


def test_full_pdf_renders_with_hidden_targets(session):  # noqa: F811
    """Die gesamte PDF-Pipeline darf an None-Zielfeldern nicht crashen."""
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload

    adv, mandate = _seed(session)
    _reduce_largest_position(session, mandate)
    payload = compute_advisory_report(session, mandate, advisor=adv)
    assert payload["building_blocks"]["soll_ausgeblendet"] is True
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Depot-Check (API-Payload, PDF, Monolith-UI)
# ---------------------------------------------------------------------------

_TARGET_FIELDS = ("soll_bps", "drift_bps", "band_min_bps", "band_max_bps", "in_band")


def test_depot_check_not_stale_keeps_bucket_targets(session):  # noqa: F811
    """Positivkontrolle gegen ein immer-ausgeblendet."""
    from services.depot_check import compute_depot_check

    _adv, mandate = _seed(session)
    dc = compute_depot_check(session, mandate)
    assert dc["soll_ausgeblendet"] is False
    assert any((b["soll_bps"] or 0) > 0 for b in dc["buckets"].values())
    assert all(b["band_max_bps"] is not None for b in dc["buckets"].values())


def test_depot_check_stale_inputs_hides_bucket_targets(session):  # noqa: F811
    from services.depot_check import compute_depot_check

    _adv, mandate = _seed(session)
    _reduce_largest_position(session, mandate)
    dc = compute_depot_check(session, mandate)
    assert dc["target_allocation_inputs_stale"] is True
    assert dc["soll_ausgeblendet"] is True
    assert set(dc["buckets"]) == set(_BUCKET_KEYS)
    for key, b in dc["buckets"].items():
        for field in _TARGET_FIELDS:
            assert b[field] is None, (key, field, b)
        # IST ist keine Zielzahl und bleibt.
        assert isinstance(b["ist_bps"], int)
    # Keine Band-Warnungen gegen die alten Baender, aber der Hinweis.
    assert not any("Toleranzband" in w for w in dc["warnings"]), dc["warnings"]
    assert any("Strategie neu berechnen" in w for w in dc["warnings"])


def test_depot_check_stale_risk_profile_hides_bucket_targets(session, monkeypatch):  # noqa: F811
    import services.risk_assessment_semantics as ras
    from services.depot_check import compute_depot_check

    _adv, mandate = _seed(session)
    monkeypatch.setattr(
        ras, "target_allocation_predates_current_assessment",
        lambda ta, ra_id, *_a, **_k: True,
    )
    dc = compute_depot_check(session, mandate)
    assert dc["soll_ausgeblendet"] is True
    assert all(b["soll_bps"] is None for b in dc["buckets"].values())


def test_depotcheck_pdf_blocked_when_risk_profile_stale(session, monkeypatch):  # noqa: F811
    """Der Depot-Check-PDF ist ein Soll/Ist-Vergleich: ohne gueltige
    Zielzahlen 409 (ValueError) mit klarem "neu berechnen"-Hinweis --
    nicht die alten Ziele drucken."""
    import pytest

    import routers.pdf_reports as pdf
    import services.risk_assessment_semantics as ras

    _adv, mandate = _seed(session)
    monkeypatch.setattr(
        ras, "target_allocation_predates_current_assessment",
        lambda ta, ra_id, *_a, **_k: True,
    )
    with pytest.raises(ValueError) as exc:
        pdf._build_depotcheck_data(mandate, session)
    assert "neu berechnen" in str(exc.value)
    assert "Risikoprofil" in str(exc.value)


def test_depotcheck_pdf_blocked_when_inputs_stale(session):  # noqa: F811
    import pytest

    import routers.pdf_reports as pdf

    _adv, mandate = _seed(session)
    _reduce_largest_position(session, mandate)
    with pytest.raises(ValueError) as exc:
        pdf._build_depotcheck_data(mandate, session)
    assert "Strategie neu berechnen" in str(exc.value)


def _monolith_render_bucket_drift(data: dict) -> str:
    import json
    import shutil
    import subprocess

    import pytest

    if shutil.which("node") is None:
        pytest.skip("node nicht verfuegbar")
    html_path = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"
    html = html_path.read_text(encoding="utf-8")
    sig = "function dcRenderBucketDrift("
    start = html.index(sig)
    i = html.index("{", start)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(html[j], 0)
        j += 1
    fn_src = html[start:j]
    script = (
        "var out={innerHTML:''};var document={getElementById:function(){return out;}};"
        "var DC_BUCKET_COLORS={};function escapeHtml(s){return String(s);}\n"
        + fn_src
        + f"\nvar d={json.dumps(data)};dcRenderBucketDrift(d.buckets,d);"
        "process.stdout.write(out.innerHTML);"
    )
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _monolith_buckets(*, hidden: bool) -> dict:
    out = {}
    for key in _BUCKET_KEYS:
        out[key] = {
            "label": key, "ist_bps": 2000,
            "soll_bps": None if hidden else 5300,
            "drift_bps": None if hidden else -3300,
            "band_min_bps": None if hidden else 4500,
            "band_max_bps": None if hidden else 5500,
            "in_band": None if hidden else False,
        }
    return out


def test_monolith_depot_check_hides_targets_when_stale():
    html = _monolith_render_bucket_drift({
        "buckets": _monolith_buckets(hidden=True),
        "soll_ausgeblendet": True,
        "target_allocation_inputs_stale": True,
    })
    assert "Strategie neu berechnen" in html
    assert "Vermögen, Cashflows oder Ziele" in html
    assert "SOLL" not in html
    assert "Toleranzband" not in html.split("</div></div>", 1)[1]
    assert ">0.0%<" not in html  # keine genullten Soll-/Drift-Spalten
    assert "Drift</th>" not in html
    assert "20.0%" in html  # IST bleibt sichtbar


def test_monolith_depot_check_shows_targets_when_current():
    html = _monolith_render_bucket_drift({
        "buckets": _monolith_buckets(hidden=False),
        "soll_ausgeblendet": False,
    })
    assert "SOLL" in html
    assert "53.0%" in html
    assert "neu berechnen" not in html
