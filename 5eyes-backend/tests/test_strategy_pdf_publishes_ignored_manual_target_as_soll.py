"""Round 46 red test -- MANUAL-TARGET-PUBLICATION-001.

Sibling finding to MANUAL-TARGET-SEMANTICS-001 (manual `target_bps` is never
actually consumed by the converged stochastic solver -- only the effective
min/max bounds matter; see services/portfolio_engine_house_matrix.py
`_apply_band_preferences`, which seeds `targets[bucket]` from the manual
override, and `_rebalance_to_total`, whose downstream solver only enforces
`minimums`/`maximums`). This finding is about PUBLICATION: the Strategy PDF
(services/pdf/documents/anlagestrategie.py `_make_preferences_section`)
prints the manual, functionally-ignored `allocation_preferences["bands"]
[bucket]["target_bps"]` value under the label "Soll" inside the
"Individuelle Bandbreiten" row of the "Anlagepraeferenzen" page -- the exact
same German word ("Soll") that the "Soll-Allokation" table a few pages later
uses to label the actually-effective, approved TargetAllocation bps
(services/pdf/components/saa_bar_table.py `make_saa_bar_table`, header
column "Soll", fed from `data.target_allocation_bps`).

Documented repro (mirrors the sibling finding's contradictory-target setup):
a mandate with a manual preference of "equities Soll 20%"
(`allocation_preferences["bands"]["equities"]["target_bps"] = 2000`) while
the actual, approved, effective TargetAllocation holds 65% equities
(`target_allocation_bps["equities"] = 6500`). The rendered PDF prints
"Soll 20.0%" for equities on the preferences page even though the mandate's
real approved strategy is 65% -- more than 3x away, nowhere near 20%. A
client or auditor reading the PDF has no way to tell that "Soll 20.0%" on
the preferences page is an ignored wish, while the "Soll" column a few
pages later is the number that actually governs the portfolio.

This test renders the REAL PDF binary via the production renderer
(`ReportLabRenderer.render_anlagestrategie`, the same entry point
`routers/pdf_reports.py` uses) and extracts its text with pypdf, exactly as
`tests/pdf/test_anlagestrategie_sollist_vergleich.py` does for the sibling
SOLL/IST section -- no shortcut through an intermediate dict.

Desired/correct behavior: the word "Soll" must denote the effective,
approved allocation ONLY. An ignored manual preference must either be
dropped from the PDF entirely, or published under a clearly distinct label
(e.g. "Gewünscht"/"Präferenz"/"Nicht umgesetzt") -- never the same "Soll"
used for the number that actually governs the portfolio.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer


@pytest.fixture
def ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        advisor_org="Muster & Partner AG",
        report_date=date(2026, 5, 23),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _data_with_contradictory_equities_target() -> AnlagestrategieData:
    """Manual preference 'equities Soll 20%' vs. effective/approved 65%.

    `target_allocation_bps` is the actually-effective, approved
    TargetAllocation (what `make_saa_bar_table` labels "Soll" and what the
    converged solver actually produced). `allocation_preferences["bands"]`
    is the advisor/client-entered manual preference, whose `target_bps` is
    never consumed by the converged solver (MANUAL-TARGET-SEMANTICS-001) --
    only `min_bps`/`max_bps` feed the solver's bounds.
    """
    return AnlagestrategieData(
        target_allocation_bps={
            "equities": 6500, "bonds": 2500, "real_estate": 500,
            "alternatives": 0, "liquidity": 500,
        },
        cma_expected_return_bps=485,
        cma_expected_vol_bps=1120,
        horizon_years=10,
        risk_profile_label="Wachstumsorientiert",
        risk_score_x10=75,
        mandate_number="M-100001",
        advisory_wealth_rappen=1_000_000_00,
        allocation_preferences={
            "bands": {
                "equities": {"min_bps": 1000, "target_bps": 2000, "max_bps": 8000},
            },
        },
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "MANUAL-TARGET-PUBLICATION-001 -- round 46 red test, see audit "
        "2026-10-04-manual-target-band-and-publication-semantics-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_strategy_pdf_does_not_label_ignored_manual_target_as_soll(ctx: PDFContext):
    data = _data_with_contradictory_equities_target()
    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF")

    # Sanity: the effective/approved allocation (65% equities) IS present
    # in the document -- this is the number that actually governs the
    # portfolio and the only one that should ever carry the "Soll" label.
    assert "65.0%" in text

    # TODAY's bug, confirmed live against the production PDF renderer: the
    # ignored manual preference (20%) is published under the exact same
    # "Soll" word, inside the "Individuelle Bandbreiten" row of the
    # "Anlagepraeferenzen" page -- even though it is functionally ignored by
    # the converged solver and the real approved strategy (65%) is more
    # than 3x away. Desired behavior: this must NOT happen -- the manual,
    # ignored preference must never be published under the "Soll" label.
    assert "Soll 20.0%" not in text, (
        "PDF labels the ignored manual target_bps preference (20.0%) as "
        "'Soll' on the Anlagepraeferenzen page, using the same word the "
        "Soll-Allokation table uses for the effective/approved allocation "
        "(65.0%) a few pages later. A reader cannot tell the ignored wish "
        "from the number that actually governs the portfolio."
    )
