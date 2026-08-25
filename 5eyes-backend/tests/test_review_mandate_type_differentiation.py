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
    """2026-08-06 (User-Direktive, 'komplett verschiedene HUDS'):
    renderReviewHero() ist jetzt ein reiner Dispatcher, der je nach
    isDiscretionary eine von zwei eigenstaendigen Builder-Funktionen
    aufruft, statt intern zu verzweigen."""
    dispatcher = _function_body(_html(), "function renderReviewHero(")
    assert "_reviewIsDiscretionaryMandate()" in dispatcher
    assert "_rvHeroWealthmanagementHtml(" in dispatcher
    assert "_rvHeroConsultingHtml(" in dispatcher
    consulting_body = _function_body(_html(), "function _rvHeroConsultingHtml(")
    assert "ANPASSUNG EMPFOHLEN" in consulting_body
    assert "weicht von der Zielallokation ab" in consulting_body
    # Handelsliste/Entscheidungsvorlage (Ausfuehrungs-Optionen) duerfen im
    # Consulting-Builder gar nicht mehr auftauchen -- aber im
    # Wealthmanagement-Builder weiterhin erlaubt sein.
    assert "openTradeList()" not in consulting_body
    assert "openDecisionTemplateModal(" not in consulting_body
    wm_body = _function_body(_html(), "function _rvHeroWealthmanagementHtml(")
    assert "openTradeList()" in wm_body


# ===========================================================================
# 2026-08-05/06 (User-Direktive, HUD-Fix + Masken-Neugestaltung): der
# Alarm-Rot-Zustand ("aktive Rebalancing"-Framing) erschien bisher auch fuer
# Consulting/reine Anlageberatung -- Consulting hat aber keine aktive
# Depot-Ueberwachung (Anlagephilosophie) und sollte "keine aktive
# anzusehende Rebalancings" zeigen. Fix (05.08.): der rote 'violated'-Zweig
# war EXPLIZIT auf isDiscretionary&&violated.length>0 gegated. Fix (06.08.,
# "komplett verschiedene HUDS"): diese Gate-Logik ist jetzt keine
# if/else-Verzweigung mehr INNERHALB einer Funktion, sondern die
# Funktionsauswahl selbst im Dispatcher -- der Consulting-Builder kennt den
# roten Alarm-Zustand technisch gar nicht (kein 'var bg=...--neg-lt' Zweig).
# ===========================================================================


def test_hero_red_alarm_branch_only_reachable_via_wealthmanagement_builder():
    dispatcher = _function_body(_html(), "function renderReviewHero(")
    flat = dispatcher.replace(" ", "").replace("\n", "")
    assert "isDiscretionary?_rvHeroWealthmanagementHtml(" in flat
    assert ":_rvHeroConsultingHtml(" in flat
    wm_body = _function_body(_html(), "function _rvHeroWealthmanagementHtml(")
    assert "HANDLUNGSBEDARF" in wm_body
    assert "neg-lt" in wm_body  # roter Alarm-Hintergrund existiert nur hier
    consulting_body = _function_body(_html(), "function _rvHeroConsultingHtml(")
    assert "HANDLUNGSBEDARF" not in consulting_body
    assert "neg-lt" not in consulting_body  # Consulting-Builder kann NIE rot/alarmierend sein


def test_action_summary_trade_list_gated_by_discretionary():
    body = _function_body(_html(), "function renderReviewActionSummary(")
    assert "_reviewIsDiscretionaryMandate()&&!!(live" in body.replace(" ", "")


def test_sr_implementation_decision_trade_list_gated_and_verb_neutralized():
    body = _function_body(_html(), "function renderSrImplementationDecision(")
    assert "isDiscretionary=_reviewIsDiscretionaryMandate()" in body.replace(" ", "")
    assert "isDiscretionary&&!!(live" in body.replace(" ", "")
    assert "_reviewIsIlliquidAssetClass(item.assetKey)" in body
    assert "'Beobachten'" in body


def test_sr_implementation_decision_verb_gated_by_discretionary_not_just_illiquid():
    """2026-08-05 (HUD-Konsistenz, User-Direktive: "Consulting hat keine
    aktive anzusehende Rebalancings"): auch bei LIQUIDEN Anlageklassen darf
    im Consulting-Modus (keine Ausfuehrungsbefugnis) nie 'Reduzieren'/
    'Aufstocken' erscheinen. 2026-08-06 (Masken-Neugestaltung): Consulting
    zeigt fuer diese Karten inzwischen gar keinen Handelsverb-Zweig mehr,
    sondern eine eigene Empfehlungszeile mit reviewBandStateMeta().action --
    die Gate-Bedingung ist jetzt die Wahl zwischen den beiden Kartentypen
    (if(isDiscretionary){...}else{...}), nicht mehr ein Verb-Ternary."""
    body = _function_body(_html(), "function renderSrImplementationDecision(")
    assert "if(isDiscretionary){" in body.replace(" ", "")
    assert "item.meta.action" in body  # Consulting-Zweig nutzt die mandatstyp-bewusste Beschreibung


# ===========================================================================
# 2026-08-03 (User-Direktive): _reviewIsDiscretionaryMandate() beruecksichtigt
# zusaetzlich den Wealthmanagement/Consulting-Praesentationsmodus. mandate_type
# bleibt die Compliance-Untergrenze (UND, nie ODER) -- Consulting-Modus zeigt
# am Review-Ende immer die Ziel-/Empfehlungssprache ("wie es sein sollte"),
# auch bei einem Vermoegensverwaltungsmandat; Wealthmanagement-Modus zeigt bei
# einem Vermoegensverwaltungsmandat zusaetzlich die operative Rebalancing-/
# Handelsliste-Schnittstelle.
# ===========================================================================


def test_discretionary_helper_also_requires_wealthmanagement_presentation_mode():
    body = _function_body(_html(), "function _reviewIsDiscretionaryMandate(")
    assert "getCurrentPresentationMode()" in body
    assert "'wealthmanagement'" in body
    # UND-Verknuepfung: Praesentationsmodus darf Ausfuehrungsbefugnis nur
    # zusaetzlich einschraenken, nie mandate_type ueberschreiben/ersetzen.
    assert "hasExecutionAuthority&&getCurrentPresentationMode()==='wealthmanagement'" in body.replace(" ", "")


def test_discretionary_helper_still_checks_mandate_type_as_floor():
    """Regressionsschutz: die Compliance-Untergrenze (mandate_type) darf beim
    Hinzufuegen des Praesentationsmodus-Checks nicht verloren gehen -- sonst
    koennte eine reine Anlageberatung (keine Ausfuehrungsbefugnis) im
    Wealthmanagement-Praesentationsmodus faelschlich eine Handelsliste zeigen."""
    body = _function_body(_html(), "function _reviewIsDiscretionaryMandate(")
    assert "mandate_type" in body
    assert "Vermögensverwaltung" in body
    assert "hasExecutionAuthority=mandateType==='Vermögensverwaltung'" in body.replace(" ", "")
