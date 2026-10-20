"""ESG-THEME-EXCLUSION-EFFECTIVE-001 (Audit 2026-10-14).

Befund (zwei unabhaengige Audit-Agenten, selbst nachverifiziert):

1. Die "Kontroverse Exposures"-Tilts (fossil/defense/tobacco/alcohol/gaming/
   nuclear) auf "exclude"/"underweight" hatten KEINE Wirkung.
   _product_score() las den Themen-Key aus der Sub-Anlageklasse des
   angefragten SLOTS -- ein Slot "Thema X" existiert aber nur, wenn X auf
   "overweight" steht (_build_sub_allocations). Ein Themenprodukt, das als
   Fallback fuer einen Kern-Slot (z.B. "Aktien Global") angeboten wurde,
   bekam einen normalen Score (1070) statt ausgeschlossen zu werden --
   waehrend das Anlagestrategie-PDF "Tabak ausschliessen" druckte.
2. policy.esg="negative_screening" schloss die Themen nur aus, wenn der
   Tilt-Key FEHLTE; die Monolith-UI sendet aber immer alle 6 Tilts mit
   "neutral" -> aus der UI heraus nie wirksam.
3. UI-Labels behaupteten "Dokumentation, kein Filter" fuer
   esg_integration (Engine filtert SFDR 8/9) und negative_screening,
   "SFDR 9" fuer impact (Engine laesst 8 und 9 zu) und "inkl. Alternative /
   kein zusaetzlicher Filter" fuer universe=extended (die standardmaessig
   angehakte Checkbox "Nur Fonds/ETFs" filtert weiterhin).

Fix-Semantik (siehe services/portfolio_engine_payload.py::
effective_theme_screening):
- "exclude" und "underweight" sind ein HARTER Produktfilter auf der eigenen
  Sub-Anlageklasse des PRODUKTS ("Thema ...") -- fuer jeden Slot, inkl.
  Anlageklassen-Fallback. "underweight" = kein Themenbaustein UND nie als
  Ersatz fuer einen anderen Slot (gleiche Produktwirkung wie exclude, eigenes
  Label im Dokument).
- negative_screening: "neutral" und "fehlt" sind gleichbedeutend (kein
  abweichender Berater-Entscheid) -> exclude. Nur ein expliziter
  "overweight"/"underweight"-Tilt uebersteuert den Policy-Default.
- Offenlegung: breit diversifizierte Indexprodukte werden nicht auf
  Themen-Exposure durchleuchtet (Warnung im Run + PDF-Hinweis).
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401

configure_mappers()

import services.portfolio_engine as pe  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import Product  # noqa: E402
from services.portfolio_engine import _normalize_preferences  # noqa: E402
from services.portfolio_engine_payload import (  # noqa: E402
    _product_matches_constraints,
    _product_score,
)
from test_optimizer_integration import _seed_realistic_mandate  # noqa: E402

THEMES = {
    "fossil": "Thema Fossile Energie",
    "defense": "Thema Verteidigung",
    "tobacco": "Thema Tabak",
    "alcohol": "Thema Alkohol",
    "gaming": "Thema Gluecksspiel",
    "nuclear": "Thema Kernenergie",
}
HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _product(**overrides) -> Product:
    data = {
        "id": "p-test",
        "product_name": "Test ETF",
        "provider": "X",
        "product_type": "ETF",
        "asset_class": "Aktien",
        "sub_asset_class": "Aktien Global",
        "currency": "CHF",
        "ter_bps": 20,
        "sfdr_class": "6",
        "is_active": 1,
        "created_at": "2026-01-01",
        "updated_at": "2026-01-01",
    }
    data.update(overrides)
    return Product(**data)


def _ui_prefs(**overrides) -> dict:
    """Exakt die Form, die collectAllocationPreferencesFromUI() mit Defaults
    sendet: alle 6 Tilts 'neutral', fundsOnly=true."""
    raw = {
        "policy": {"esg": "none", "universe": "funds_only", "homeBias": "ch_focus", "hedging": "none"},
        "tilts": {key: "neutral" for key in THEMES},
        "product": {"noDerivatives": False, "noLeverage": False, "noStructured": False,
                    "listedOnly": False, "fundsOnly": True},
        "geo": {"chFocus": True, "noEm": False, "hedgingRequired": False, "chfOnly": False, "noUsd": False},
    }
    for path, value in overrides.items():
        section, key = path.split(".")
        raw[section][key] = value
    return _normalize_preferences(raw)


# ---------------------------------------------------------------------------
# 1. Harter Produktfilter auf der Produkt-Sub-Anlageklasse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_key,theme_label", sorted(THEMES.items()))
@pytest.mark.parametrize("mode", ["exclude", "underweight"])
def test_screened_theme_product_fails_preference_filter(theme_key, theme_label, mode):
    product = _product(sub_asset_class=theme_label)
    prefs = _normalize_preferences({"tilts": {theme_key: mode}})
    assert _product_matches_constraints(product, prefs, 8) is False


@pytest.mark.parametrize("mode", [None, "neutral", "overweight"])
def test_unscreened_theme_product_passes_preference_filter(mode):
    product = _product(sub_asset_class="Thema Tabak")
    prefs = _normalize_preferences({"tilts": {"tobacco": mode}} if mode else None)
    assert _product_matches_constraints(product, prefs, 8) is True


def test_screening_one_theme_leaves_core_and_other_theme_products_alone():
    prefs = _normalize_preferences({"tilts": {"tobacco": "exclude"}})
    assert _product_matches_constraints(_product(sub_asset_class="Aktien Global"), prefs, 8) is True
    assert _product_matches_constraints(_product(sub_asset_class="Thema Alkohol"), prefs, 8) is True


def test_excluded_theme_product_scores_as_excluded_even_as_core_fallback():
    """Defense in depth: auch der Score haengt an der Produkt-Klassifikation,
    nicht am angefragten Slot."""
    tobacco = _product(sub_asset_class="Thema Tabak")
    for mode in ("exclude", "underweight"):
        prefs = _normalize_preferences({"tilts": {"tobacco": mode}})
        assert _product_score(tobacco, "Aktien Global", prefs) == -10000


def test_overweight_bonus_stays_slot_bound_and_does_not_promote_theme_as_core_fallback():
    tobacco = _product(sub_asset_class="Thema Tabak")
    neutral = _normalize_preferences({"tilts": {"tobacco": "neutral"}})
    over = _normalize_preferences({"tilts": {"tobacco": "overweight"}})
    assert _product_score(tobacco, "Aktien Global", over) == _product_score(tobacco, "Aktien Global", neutral)
    assert _product_score(tobacco, "Thema Tabak", over) > _product_score(tobacco, "Thema Tabak", neutral)


# ---------------------------------------------------------------------------
# 2. negative_screening: 'neutral' == 'fehlt'
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_label", sorted(THEMES.values()))
def test_negative_screening_applies_with_ui_payload_all_neutral(theme_label):
    prefs = _ui_prefs(**{"policy.esg": "negative_screening"})
    assert _product_matches_constraints(_product(sub_asset_class=theme_label), prefs, 8) is False


def test_negative_screening_same_result_whether_tilt_neutral_or_omitted():
    product = _product(sub_asset_class="Thema Tabak")
    ui = _ui_prefs(**{"policy.esg": "negative_screening"})
    api = _normalize_preferences({"policy": {"esg": "negative_screening"}})
    assert _product_matches_constraints(product, ui, 8) is _product_matches_constraints(product, api, 8) is False
    assert _product_score(product, "Aktien Global", ui) == _product_score(product, "Aktien Global", api) == -10000


def test_negative_screening_explicit_overweight_still_overrides():
    prefs = _ui_prefs(**{"policy.esg": "negative_screening", "tilts.tobacco": "overweight"})
    assert _product_matches_constraints(_product(sub_asset_class="Thema Tabak"), prefs, 8) is True
    assert _product_matches_constraints(_product(sub_asset_class="Thema Alkohol"), prefs, 8) is False


# ---------------------------------------------------------------------------
# 3. End-to-end: Generate-Lauf
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    engine = create_engine(f"sqlite:///{tmp_path / 'esg_theme.db'}", connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        engine.dispose()


def _run(SF, advisor_id, mandate_id, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = pe.generate_recommendation_run(s, mandate, advisor_id, prefs)
        positions = sorted(
            (p["product_name"], p["sub_asset_class"] if "sub_asset_class" in p else None, p["target_weight_bps"])
            for p in result["positions"]
        )
        warnings = list(result.get("warnings") or [])
        s.rollback()
        return positions, warnings


def _only_theme_products_for_equities(SF, advisor_id):
    """Alle Aktien-Kernprodukte deaktivieren -> jeder Aktien-Slot muss auf
    den Anlageklassen-Fallback ausweichen, und dort bleiben nur die
    Themenprodukte uebrig."""
    with SF() as s:
        pe.ensure_default_products(s, jurisdiction="CH")
        pe.ensure_hedged_product_variants(s)
        s.commit()
        for product in s.query(Product).filter(Product.asset_class == "Aktien").all():
            if not str(product.sub_asset_class or "").startswith("Thema "):
                product.is_active = 0
        s.commit()


def test_e2e_theme_product_used_as_fallback_when_neutral(session_factory):
    """Kontrolle: der Fallback-Pfad waehlt ohne Screening tatsaechlich ein
    Themenprodukt -- sonst waere der Ausschluss-Test unten bedeutungslos."""
    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(session_factory, "esg-ctl")
    _only_theme_products_for_equities(session_factory, advisor_id)
    positions, _warnings = _run(session_factory, advisor_id, mandate_id, None)
    names = [name for name, _sub, _w in positions]
    with session_factory() as s:
        theme_names = {
            p.product_name for p in s.query(Product).all()
            if str(p.sub_asset_class or "").startswith("Thema ")
        }
    assert theme_names & set(names), names


@pytest.mark.parametrize("mode", ["exclude", "underweight"])
def test_e2e_excluded_themes_never_selected_fail_closed(session_factory, mode):
    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(session_factory, f"esg-{mode}")
    _only_theme_products_for_equities(session_factory, advisor_id)
    with pytest.raises(ValueError, match="Produktselektion unvollstaendig"):
        _run(session_factory, advisor_id, mandate_id, {"tilts": {key: mode for key in THEMES}})


def test_e2e_negative_screening_from_ui_payload_fail_closed(session_factory):
    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(session_factory, "esg-ns")
    _only_theme_products_for_equities(session_factory, advisor_id)
    raw = {"policy": {"esg": "negative_screening"}, "tilts": {key: "neutral" for key in THEMES}}
    with pytest.raises(ValueError, match="Produktselektion unvollstaendig"):
        _run(session_factory, advisor_id, mandate_id, raw)


def test_e2e_screening_discloses_missing_look_through(session_factory):
    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(session_factory, "esg-disc")
    _base_positions, base_warnings = _run(session_factory, advisor_id, mandate_id, None)
    assert not any("Look-through" in w for w in base_warnings)
    _positions, warnings = _run(
        session_factory, advisor_id, mandate_id,
        {"tilts": {"tobacco": "exclude", "gaming": "underweight"}},
    )
    disclosure = [w for w in warnings if "Look-through" in w]
    assert len(disclosure) == 1, warnings
    assert "Tabak" in disclosure[0] and "Gluecksspiel" in disclosure[0]


# ---------------------------------------------------------------------------
# 4. UI-Labels muessen das Engine-Verhalten beschreiben
# ---------------------------------------------------------------------------


def _option_label(select_id: str, value: str) -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    select = re.search(r'id="%s"[^>]*>(.*?)</select>' % select_id, html)
    assert select, select_id
    option = re.search(r'<option value="%s"[^>]*>([^<]*)</option>' % value, select.group(1))
    assert option, (select_id, value)
    return option.group(1)


@pytest.mark.parametrize("value", ["best_in_class", "impact", "net_zero", "esg_integration"])
def test_ui_label_for_sfdr_gated_esg_values_states_a_filter(value):
    """ESG-PREMIUM-CRITERIA-001: jedes Label nennt jetzt sein EIGENES
    Kriterium (Matrix in tests/test_esg_premium_criteria.py); hier bleibt
    der urspruengliche Kern: kein Label behauptet 'kein Filter'."""
    prefs_ok = _ui_prefs(**{"policy.esg": value})
    assert _product_matches_constraints(_product(sfdr_class="9", esg_rating="AA", climate_benchmark="PAB"), prefs_ok, 8) is True
    assert _product_matches_constraints(_product(sfdr_class="6"), prefs_ok, 8) is False
    label = _option_label("aa-policy-esg", value)
    assert "SFDR" in label, label
    assert "kein Filter" not in label


def test_ui_label_for_negative_screening_does_not_claim_no_filter():
    label = _option_label("aa-policy-esg", "negative_screening")
    assert "kein Filter" not in label and "Dokumentation" not in label, label
    assert "ausgeschlossen" in label.lower(), label


@pytest.mark.parametrize("value", ["standard", "extended"])
def test_ui_universe_label_matches_the_single_universe_control(value):
    # STRATEGY-BLOCKS-PANEL-001: das Universum-Dropdown ist die EINZIGE
    # Steuerung; product.fundsOnly/listedOnly werden daraus abgeleitet (keine
    # separaten Checkboxen mehr). "Kein Zusatzfilter" ist damit wahr.
    label = _option_label("aa-policy-universe", value)
    assert "inkl. Alternative" not in label, label
    assert "kein Zusatzfilter" in label, label
    html = HTML_PATH.read_text(encoding="utf-8")
    collect = re.search(r"function collectAllocationPreferencesFromUI\(\)\{(.*?)\n\}", html, re.S).group(1)
    assert "fundsOnly:universeUi==='funds_only'" in collect
    assert "listedOnly:universeUi==='listed_only'" in collect
    prefs = _ui_prefs(**{"policy.universe": value, "product.fundsOnly": False})
    assert _product_matches_constraints(_product(product_type="Einzeltitel"), prefs, 8) is True
    # Engine unveraendert: ein (Alt-)fundsOnly filtert weiterhin.
    legacy = _ui_prefs(**{"policy.universe": value})
    assert _product_matches_constraints(_product(product_type="Einzeltitel"), legacy, 8) is False


def test_ui_documents_underweight_semantics_and_missing_look_through():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert 'id="aa-tilt-screening-note"' in html
    note = re.search(r'id="aa-tilt-screening-note"[^>]*>(.*?)</div>', html, re.S).group(1)
    assert "Untergewichten" in note and "Ersatz" in note
    assert "nicht" in note and "durchleuchtet" in note


# ---------------------------------------------------------------------------
# 5. Anlagestrategie-PDF: Dokument == Engine
# ---------------------------------------------------------------------------


def _pdf_preferences_text(preferences: dict) -> str:
    from reportlab.platypus import Paragraph, Table

    from services.pdf.documents.anlagestrategie import _make_preferences_section
    from services.pdf.styles import make_paragraph_styles

    chunks = []
    for flowable in _make_preferences_section(preferences, make_paragraph_styles()):
        if isinstance(flowable, Paragraph):
            chunks.append(flowable.getPlainText())
        elif isinstance(flowable, Table):
            for row in flowable._cellvalues:
                chunks.extend(cell.getPlainText() for cell in row if isinstance(cell, Paragraph))
    return "\n".join(chunks)


def test_pdf_lists_negative_screening_exclusions_from_ui_payload_and_discloses_look_through():
    text = _pdf_preferences_text({
        "policy": {"esg": "negative_screening"},
        "tilts": {key: "neutral" for key in THEMES} | {"alcohol": "overweight"},
    })
    assert "Tabak ausschliessen" in text and "Kernenergie ausschliessen" in text
    # ESG-PREMIUM-CRITERIA-001: Uebergewichten trotz Negativ-Screening ist
    # eine dokumentierte Abweichung von der ESG-Policy (eigene Zeile).
    assert "Alkohol uebergewichtet" in text and "Alkohol ausschliessen" not in text
    assert "Abweichungen von der ESG-Policy" in text
    assert "nicht durchleuchtet" in text


def test_pdf_describes_underweight_as_implemented():
    text = _pdf_preferences_text({"tilts": {"tobacco": "underweight"}})
    assert "Tabak untergewichten (kein Themenbaustein, nie als Ersatz)" in text
    assert "durchleuchtet" in text


def test_pdf_without_screening_has_no_screening_note():
    text = _pdf_preferences_text({"tilts": {key: "neutral" for key in THEMES}})
    assert "Themen-Screening" not in text
    assert "Keine aktiven Restriktionen" in text


def test_pdf_esg_integration_label_states_sfdr_filter():
    text = _pdf_preferences_text({"policy": {"esg": "esg_integration"}})
    # CIO-Entscheid 2026-10-18 (ESG-CLAIM-NEUTRAL-001): Kundendokument nennt
    # nur das Kriterium, nicht den Policy-Namen "ESG-Integration".
    assert "Kriterium der Produktauswahl: nur Produkte nach SFDR Art. 8 oder 9" in text
    assert "ESG-Integration" not in text
