"""2026-07-24: Review & Abschluss unterscheidet nach mandate_type.

User-Bug: Bandverletzungen bei Immobilien wurden als "Rebalancing
erforderlich" mit Handelsliste-CTA angezeigt -- unsinnig fuer reine
Anlageberatung (keine Ausfuehrungsbefugnis) UND fuer illiquide
Anlageklassen generell (eine Immobilie ist nicht per Handelsliste
umschichtbar, unabhaengig vom Mandatstyp).

Zwei unabhaengige Achsen:
1. Illiquide Anlageklassen (aktuell: Immobilien) bekommen NIE die
   operative Rebalancing-/Handelsliste-Sprache, auch nicht bei
   Vermoegensverwaltung.
2. Reine Anlageberatung/Finanzplanung/Reporting-only (mandate_type !=
   'Vermögensverwaltung') bekommt fuer liquide Anlageklassen eine
   Empfehlungs- statt Ausfuehrungs-Sprache, und nie den
   Handelsliste-Button.
"""
from __future__ import annotations

from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _function_body(text: str, signature_start: str) -> str:
    start = text.find(signature_start)
    assert start > 0, f"Funktion nicht gefunden: {signature_start}"
    end = text.find("\n}\n", start)
    assert end > start, f"Funktionsende nicht gefunden: {signature_start}"
    return text[start:end]


def test_illiquid_helper_exists_and_matches_immobilien():
    body = _function_body(_html(), "function _reviewIsIlliquidAssetClass(")
    assert "immob" in body.lower()


def test_discretionary_helper_checks_vermoegensverwaltung():
    body = _function_body(_html(), "function _reviewIsDiscretionaryMandate(")
    assert "mandate_type" in body
    assert "Vermögensverwaltung" in body


def test_review_band_state_meta_takes_asset_key_and_uses_both_helpers():
    body = _function_body(_html(), "function reviewBandStateMeta(")
    assert "assetKey" in body
    assert "_reviewIsIlliquidAssetClass(assetKey)" in body
    assert "_reviewIsDiscretionaryMandate()" in body
    # Illiquide + Beratung duerfen NIE 'Rebalancing erforderlich' liefern --
    # nur der discretionary+liquid-Zweig darf diesen String noch enthalten.
    assert "Rebalancing erforderlich" in body  # bleibt fuer discretionary+liquid
    assert "Empfehlung anpassen" in body
    assert "Bei naechster Transaktion" in body


def test_all_three_call_sites_pass_asset_key():
    html = _html()
    calls = [
        idx for idx in range(len(html))
        if html.startswith("reviewBandStateMeta(", idx)
    ]
    # Direkter String-Scan auf die Aufruf-Fragmente (nicht die Funktionsdefinition).
    call_sites = html.count("item.meta=reviewBandStateMeta(")
    assert call_sites == 3, f"Erwartet 3 Aufrufstellen, gefunden {call_sites}"
    # Jede Aufrufstelle muss mit ',item.assetKey);' schliessen.
    assert html.count(",item.assetKey);") >= 3


def test_hero_downgrades_illiquid_violations_out_of_red_bucket():
    body = _function_body(_html(), "function renderReviewHero(")
    assert "_reviewIsIlliquidAssetClass(r.assetKey)" in body
    # violated-Filter muss illiquide Verletzungen explizit ausschliessen.
    assert "tr2'&&!_reviewIsIlliquidAssetClass" in body.replace(" ", "")


def test_hero_branches_badge_headline_cta_on_mandate_type():
    body = _function_body(_html(), "function renderReviewHero(")
    assert "_reviewIsDiscretionaryMandate()" in body
    assert "EMPFEHLUNG PRÜFEN" in body
    assert "weicht vom vereinbarten Band ab" in body
    # Handelsliste-Button darf im Advisory-Zweig nicht mehr auftauchen --
    # aber im discretionary-Zweig weiterhin erlaubt sein.
    assert "openTradeList()" in body  # noch vorhanden (discretionary-Zweig)


def test_action_summary_trade_list_gated_by_discretionary():
    body = _function_body(_html(), "function renderReviewActionSummary(")
    assert "_reviewIsDiscretionaryMandate()&&!!(live" in body.replace(" ", "")


def test_sr_implementation_decision_trade_list_gated_and_verb_neutralized():
    body = _function_body(_html(), "function renderSrImplementationDecision(")
    assert "_reviewIsDiscretionaryMandate()&&!!(live" in body.replace(" ", "")
    assert "_reviewIsIlliquidAssetClass(item.assetKey)" in body
    assert "'Beobachten'" in body
