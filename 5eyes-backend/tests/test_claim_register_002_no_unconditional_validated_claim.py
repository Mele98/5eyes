"""CLAIM-REGISTER-002 (B2B-Trust-Audit Runde 4, 2026-10-05): the decorative
login/intro splash screen in 5eyes_v2.html showed "RISK BUDGET" / "VALID" and
a ticker item "RISK BUDGET VALIDATED" unconditionally on every app start --
purely decorative marketing copy with no link to any actual computation,
while the real risk-budget-fallback finalization contract
(docs/audits/2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md)
remains Status: Release-Hold. A hardcoded "VALIDATED" claim on a splash
screen that cannot possibly reflect per-mandate reality is exactly the kind
of claim/evidence mismatch the B2B claims-and-dark-patterns audit
(docs/audits/2026-10-05-b2b-claims-dark-patterns-commercial-surfaces-audit.md,
finding CLAIM-REGISTER-002) flagged.

Fix: the decorative text no longer claims "VALIDATED"/"VALID" -- it was
replaced with "AWARE" (same decorative purpose and layout, no implied
completed validation). This regression test locks in the absence of the
old claim text rather than re-asserting a specific new wording, so future
copy changes remain free as long as they don't reintroduce an unconditional
validation claim.
"""
from __future__ import annotations

from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def test_splash_screen_does_not_claim_unconditional_risk_budget_validation():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "RISK BUDGET VALIDATED" not in html, (
        "the decorative splash screen must not claim an unconditional "
        "'RISK BUDGET VALIDATED' state -- this contradicts the still-open "
        "risk-budget-fallback release-hold finding and is not tied to any "
        "real per-mandate computation"
    )
    assert "<span>RISK BUDGET</span><em>VALID</em>" not in html, (
        "the decorative intro-signal rail must not claim 'RISK BUDGET: VALID' "
        "unconditionally on every app start"
    )
