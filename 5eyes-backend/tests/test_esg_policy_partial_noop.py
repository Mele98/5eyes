"""ESG-POLICY-PARTIAL-NOOP-001 (Kontrollrunde 2026-09-27).

policy.esg kennt sechs gueltige Werte (schemas/allocation.py
_VALID_POLICY_VALUES["esg"]), von denen zwei -- "esg_integration" und
"negative_screening" -- im PDF mit Klartext-Label angezeigt wurden
(services/pdf/documents/anlagestrategie.py), aber in
services/portfolio_engine_payload.py::_product_matches_constraints() /
_product_score() KEINE Wirkung auf die tatsaechliche Produktauswahl hatten.
Ein Berater, der einen dieser beiden Werte fuer einen Kunden waehlte, bekam
ein Dokument, das eine ESG-Umsetzung behauptete, die nicht stattfand.

Fix (User-Entscheid 2026-09-27):
- "esg_integration" wird wie die drei bestehenden Werte (best_in_class,
  impact, net_zero) behandelt -- SFDR Art. 8/9 als Gate. Inhaltlich am
  naechsten dran (Beruecksichtigung von E/S-Merkmalen), keine neue Kategorie.
- "negative_screening" ist konzeptionell kein SFDR-Artikel, sondern ein
  Sektor-Ausschluss. Dafuer existiert bereits das Themen-Tilt-System
  (fossil/defense/tobacco/alcohol/gaming/nuclear, je exclude/underweight/
  overweight). "negative_screening" setzt jetzt automatisch alle sechs
  Themen auf "exclude" -- AUSSER der Berater hat fuer ein Thema bereits
  explizit einen abweichenden Tilt gesetzt (expliziter Berater-Entscheid
  geht dem Policy-Default immer vor).
"""
from __future__ import annotations

import pytest

from models import clients as _clients_models  # noqa: F401
from models import mandates as _mandates_models  # noqa: F401
from models import profiling as _profiling_models  # noqa: F401
from models import snapshots as _snapshots_models  # noqa: F401
from models import tenant as _tenant_models  # noqa: F401
from models import wealth as _wealth_models  # noqa: F401
from models.review import Product
from models.users import User  # noqa: F401
import services.portfolio_engine as portfolio_engine


def _make_product(**overrides) -> Product:
    defaults = {
        "id": "product-test",
        "product_name": "Test Product",
        "provider": "Test Issuer",
        "product_type": "ETF",
        "asset_class": "Aktien",
        "sub_asset_class": "Aktien Global",
        "currency": "CHF",
        "ter_bps": 20,
        "sfdr_class": "6",
        "is_active": 1,
        "created_at": "2026-04-20T00:00:00.000Z",
        "updated_at": "2026-04-20T00:00:00.000Z",
    }
    defaults.update(overrides)
    return Product(**defaults)


# ============================================================================
# esg_integration -- jetzt gleich wie best_in_class/impact/net_zero
# ============================================================================


@pytest.mark.parametrize("esg_value", ["best_in_class", "impact", "net_zero", "esg_integration"])
def test_esg_gated_values_reject_non_sfdr_product(esg_value):
    prefs = portfolio_engine._normalize_preferences({"policy": {"esg": esg_value}})
    non_esg_product = _make_product(sfdr_class="6")
    assert portfolio_engine._product_matches_constraints(non_esg_product, prefs, score_bucket=8) is False


@pytest.mark.parametrize("esg_value", ["best_in_class", "impact", "net_zero", "esg_integration"])
@pytest.mark.parametrize("sfdr_class", ["8", "9"])
def test_esg_gated_values_accept_sfdr_8_or_9(esg_value, sfdr_class):
    prefs = portfolio_engine._normalize_preferences({"policy": {"esg": esg_value}})
    esg_product = _make_product(sfdr_class=sfdr_class)
    assert portfolio_engine._product_matches_constraints(esg_product, prefs, score_bucket=8) is True


def test_esg_none_does_not_filter_by_sfdr():
    prefs = portfolio_engine._normalize_preferences({"policy": {"esg": "none"}})
    non_esg_product = _make_product(sfdr_class="6")
    assert portfolio_engine._product_matches_constraints(non_esg_product, prefs, score_bucket=8) is True


# ============================================================================
# negative_screening -- neu: automatischer Themen-Ausschluss
# ============================================================================


_THEMATIC_SUB_ASSET_CLASSES = (
    "Thema Fossile Energie",
    "Thema Verteidigung",
    "Thema Tabak",
    "Thema Alkohol",
    "Thema Gluecksspiel",
    "Thema Kernenergie",
)


@pytest.mark.parametrize("sub_asset_class", _THEMATIC_SUB_ASSET_CLASSES)
def test_negative_screening_excludes_all_six_themes_by_default(sub_asset_class):
    prefs = portfolio_engine._normalize_preferences({"policy": {"esg": "negative_screening"}})
    product = _make_product(sub_asset_class=sub_asset_class, asset_class="Alternative")
    score = portfolio_engine._product_score(product, sub_asset_class, prefs)
    assert score == -10000


def test_negative_screening_leaves_non_thematic_products_unaffected():
    prefs = portfolio_engine._normalize_preferences({"policy": {"esg": "negative_screening"}})
    product = _make_product(sub_asset_class="Aktien Global", asset_class="Aktien")
    score = portfolio_engine._product_score(product, "Aktien Global", prefs)
    assert score > 0


def test_negative_screening_respects_explicit_advisor_override():
    """Ein Berater, der 'negative_screening' waehlt, aber fuer ein einzelnes
    Thema explizit 'overweight' setzt, muss diese explizite Wahl behalten --
    der Policy-Default darf eine bewusste Berater-Entscheidung nicht
    stillschweigend ueberschreiben."""
    prefs = portfolio_engine._normalize_preferences(
        {"policy": {"esg": "negative_screening"}, "tilts": {"tobacco": "overweight"}}
    )
    overridden_product = _make_product(sub_asset_class="Thema Tabak", asset_class="Alternative")
    overridden_score = portfolio_engine._product_score(overridden_product, "Thema Tabak", prefs)
    assert overridden_score != -10000
    assert overridden_score > 1000  # Basis-Score 1000 + 250 Overweight-Bonus, siehe _product_score

    still_excluded_product = _make_product(sub_asset_class="Thema Alkohol", asset_class="Alternative")
    still_excluded_score = portfolio_engine._product_score(still_excluded_product, "Thema Alkohol", prefs)
    assert still_excluded_score == -10000


def test_without_negative_screening_themes_are_unaffected_by_default():
    """Regression: ohne negative_screening bleibt das Verhalten unveraendert
    -- ein Themen-Produkt ohne expliziten Tilt wird normal bewertet, nicht
    ausgeschlossen."""
    prefs = portfolio_engine._normalize_preferences({"policy": {"esg": "none"}})
    product = _make_product(sub_asset_class="Thema Tabak", asset_class="Alternative")
    score = portfolio_engine._product_score(product, "Thema Tabak", prefs)
    assert score != -10000
