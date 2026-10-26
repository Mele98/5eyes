"""DEPOT-E2E-STRESS-001, Option 1 (CIO-Entscheid): ehrliche Stress-Labels.

``compute_stress_replays()`` rechnet ausschliesslich auf der SOLL-Gewichtung
der aktuellen TargetAllocation (``target_*_bps``), nie auf den IST-Bestaenden
des Kunden. Jede Oberflaeche, die den Stress-Replay anzeigt oder exportiert,
muss das ehrlich so benennen und darf nicht behaupten, das "aktuelle Depot"
bzw. "Ihr Depot" zu stressen.

Vertrag:
  * Monolith (Depot-Check-Modal), Depot-Check-PDF, Advisory-Report-PDF und
    die API-Antwort/-Beschreibung tragen das SOLL-Label
    ``STRESS_REPLAY_SCOPE_LABEL``.
  * Keine dieser Oberflaechen behauptet ausserhalb dieses (verneinenden)
    Labels ein "aktuelles Depot" / "Ihr Depot" als Stress-Basis.

Der IST-Stress selbst (Option 2) bleibt als xfail in
``test_depot_e2e_stress_001_current_holdings_insensitivity.py`` offen.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent
MONOLITH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"

EXPECTED_LABEL = (
    "Stress-Replay der empfohlenen SOLL-Allokation (nicht des aktuellen Depots)"
)

# Behauptungen, das echte Kundendepot werde gestresst.
_FORBIDDEN = re.compile(
    r"(aktuell\w*\s+Depot|Ihr\w*\s+Depot|aktuell\w*\s+Bucket-Gewichtung)",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "")


def _assert_honest(surface: str, text: str) -> None:
    flat = _norm(text)
    assert EXPECTED_LABEL in flat, (
        f"{surface}: SOLL-Label fehlt ({EXPECTED_LABEL!r})."
    )
    rest = flat.replace(EXPECTED_LABEL, "")
    hits = _FORBIDDEN.findall(rest)
    assert not hits, (
        f"{surface}: behauptet IST-Depot als Stress-Basis: {hits!r}"
    )


def test_service_label_constant_is_the_contract_label():
    from services.backtest_stress import (
        STRESS_REPLAY_SCOPE,
        STRESS_REPLAY_SCOPE_LABEL,
    )

    assert STRESS_REPLAY_SCOPE_LABEL == EXPECTED_LABEL
    assert STRESS_REPLAY_SCOPE == "approved_target_allocation"


def test_monolith_depot_check_stress_section_is_honest():
    html = MONOLITH.read_text(encoding="utf-8")

    start = html.index("function dcRenderStressReplays(")
    end = html.index("\nfunction ", start + 1)
    render_fn = html[start:end]
    _assert_honest("Monolith dcRenderStressReplays", render_fn)

    anchor = html.index('id="dc-stress-replays"')
    header_start = html.rfind("<!-- Stress-Replays", 0, anchor)
    assert header_start != -1
    header = re.sub(r"<[^>]+>", " ", html[header_start:anchor])
    assert not _FORBIDDEN.findall(_norm(header)), header
    assert "SOLL" in header, header


def test_api_stress_payload_and_description_are_honest():
    from routers.allocation import get_backtest_stress_replays
    from services.backtest_stress import compute_stress_replays

    _assert_honest(
        "API-Beschreibung GET /backtest/stress-replays",
        get_backtest_stress_replays.__doc__ or "",
    )

    class _Query:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, *a, **k):
            return _Query()

    class _Mandate:
        id = "m-1"

    payload = compute_stress_replays(_Db(), _Mandate())
    assert payload["scope"] == "approved_target_allocation"
    _assert_honest("API-Payload scope_label", payload["scope_label"])


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_depotcheck_pdf_stress_section_is_honest():
    from services.pdf.base import DepotCheckData, PDFContext
    from services.pdf.reportlab_renderer import ReportLabRenderer

    ctx = PDFContext(
        mandate_name="Muster Mandat",
        advisor_name="Anna Beratung",
        advisor_org="Beratungshaus",
        report_date=date(2026, 10, 25),
        audit_hash="stress-scope-test",
    )
    data = DepotCheckData(
        mandate_number="M-STRESS-01",
        total_advisory_wealth_rappen=1_000_000_00,
        target_allocation_bps={"equities": 6000, "bonds": 4000},
        stress_scenarios=[{
            "label": "Finanzkrise",
            "period": "2008-2009",
            "cumulative_return_bps": -1800,
            "max_drawdown_bps": 2400,
            "recovery_months": 28,
        }],
    )
    text = _pdf_text(ReportLabRenderer().render_depotcheck(ctx, data))
    start = text.index("HISTORISCHE STRESS-SZENARIEN")
    section = text[start:start + 600]
    _assert_honest("Depot-Check-PDF Stress-Abschnitt", section)


def test_advisory_report_pdf_stress_section_is_honest():
    from reportlab.platypus import Paragraph

    from services.pdf.documents import advisory_report as ar_pdf

    styles = ar_pdf.make_advisory_styles()
    flowables = ar_pdf._build_stress_replay_flowables(
        {
            "data_pending": False,
            "note": "",
            "scenarios": [{
                "id": "gfc",
                "label": "Finanzkrise",
                "period": "2008-2009",
                "cumulative_return_bps": -1800,
                "max_drawdown_bps": 2400,
                "recovery_months": 28,
            }],
        },
        styles,
    )
    text = " ".join(
        f.getPlainText() for f in flowables if isinstance(f, Paragraph)
    )
    _assert_honest("Advisory-Report-PDF Sektion 17", text)
