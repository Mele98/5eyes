"""PREF-LEAK-NEW-CLIENT-001 (Assetallocation-Audit 2026-10-14).

``collectAllocationPreferencesFromUI()`` reads the LIVE DOM of the
Anlagepraeferenzen / Restriktionen & Tilts panel. Opening a client via the
sidebar re-syncs that DOM (loadClientById -> syncAllocationPreferences), but
the new-client flow (createNewMandate -> showNewClientScreen) did not.

Measured live (Playwright, 2026-10-14): after client A had ESG
"best_in_class", Tabak "exclude" and Mindestreserve CHF 250'000, the brand-new
mandate's stored preferences were the defaults (none / neutral / empty), but
the payload the first "Anlagestrategie berechnen" would send carried A's
values -- another client's restrictions on a new client's strategy.

Second defect on the same path: the two fallback branches (backend down; client
created but mandate failed) opened the new client screen with
``currentMandateId`` still pointing at the PREVIOUS client's mandate.

Static-source regression test (same convention as
test_a11y_gp_001_golden_path_stepper_keyboard.py).
"""
from __future__ import annotations

from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"


def _function_body(src: str, signature: str) -> str:
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def test_new_client_screen_resyncs_preference_dom_after_state_reset():
    body = _function_body(
        HTML_PATH.read_text(encoding="utf-8"),
        "function showNewClientScreen(firstName, lastName, mType, meta) {",
    )
    assert "syncAllocationPreferences()" in body, (
        "showNewClientScreen must re-sync the Anlagepraeferenzen DOM, otherwise "
        "the previous client's ESG/tilts/limits are sent for the new mandate"
    )
    # The resync must run AFTER the new mandate context exists, i.e. after the
    # strategy state is reset to the new currentMandateId.
    assert body.index("strategyState={") < body.index("syncAllocationPreferences()")


def test_fallback_branches_never_reuse_the_previous_clients_mandate():
    body = _function_body(
        HTML_PATH.read_text(encoding="utf-8"),
        "async function createNewMandate() {",
    )
    def first_call_after(marker: str) -> int:
        return body.index("showNewClientScreen(", body.index(marker))

    demo_call = first_call_after("} catch(ce) {")          # backend down
    no_mandate_call = first_call_after("} catch(me) {")    # mandate failed
    success_call = first_call_after("// Schritt 3: Erfolg")
    # Success branch sets the NEW mandate id before opening the screen.
    assert body.rfind("currentMandateId = mandateData.id", 0, success_call) != -1
    # Both fallback branches must clear the stale id right before the screen.
    for call in (demo_call, no_mandate_call):
        window = body[max(0, call - 600):call]
        assert "currentMandateId = null;" in window, (
            "fallback branch opens the new client screen with the previous "
            "client's currentMandateId"
        )
