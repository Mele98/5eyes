"""Regression-Lock fuer den Risikoprofil-Override-Hinweis (2026-08-25,
Live-Fund Holger Mueller Nachtrag).

Nachdem der hedgingRequired-Katalogluecke-Bug geschlossen war (siehe
test_hedged_product_catalog_coverage.py), blieb Holgers Themen-Tilts
(Verteidigung/Tabak/Gluecksspiel/etc.) trotzdem im generischen Core-Fallback
haengen: die Produkte existieren jetzt im Katalog, werden aber durch die
Eignungspruefung blockiert (Risikoband 6-10, Holger ist Bucket 4/Defensiv).
Die alte Fallback-Meldung ("Core-Fallback verwendet") machte keinen
Unterschied zwischen einer echten Katalogluecke und einem reinen
Eignungs-Block -- der Berater konnte nicht erkennen, OB und WIE stark ein
dokumentierter Risikoprofil-Override (services/risk_assessment_semantics.py::
_risk_assessment_has_documented_override) das Problem loesen wuerde.

Fix: _suitability_block_hint() (services/portfolio_engine_payload.py) prueft
bei einer leeren exakten Kandidatenliste, ob ein Produkt existiert, das NUR
an score_bucket scheitert, und nennt das dafuer minimal benoetigte Bucket +
den dafuer noetigen Score (score_x10 >= 10*bucket-5, siehe
risk_score_bucket_from_validated_score()). Eine echte Katalogluecke (kein
Produkt fuer diese Sub-Asset-Class ueberhaupt) liefert weiterhin None -- die
harte Eignungspruefung selbst bleibt unveraendert (kein Auto-Override).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, client_login, fx_rate, mandates, profiling,
    protocol_bausteine, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.review import Product, ProductSuitability  # noqa: E402
from services.portfolio_engine import (  # noqa: E402
    _normalize_preferences,
    _suitability_block_hint,
    ensure_default_products,
)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_hint_names_required_bucket_and_score_when_only_suitability_blocks(session_factory):
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        products = s.query(Product).filter(Product.is_active == 1).all()
        prefs = _normalize_preferences(None)

        hint = _suitability_block_hint(products, "Thema Tabak", prefs, score_bucket=4)

        assert hint is not None
        assert "Bucket 4" in hint
        assert "benoetigt mind. Bucket 6" in hint
        assert "Score >= 55" in hint


def test_hint_is_none_when_score_bucket_already_satisfies_the_band(session_factory):
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        products = s.query(Product).filter(Product.is_active == 1).all()
        prefs = _normalize_preferences(None)

        hint = _suitability_block_hint(products, "Thema Tabak", prefs, score_bucket=8)

        assert hint is None


def test_hint_is_none_for_a_genuine_catalog_gap(session_factory):
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        products = s.query(Product).filter(Product.is_active == 1).all()
        prefs = _normalize_preferences(None)

        hint = _suitability_block_hint(products, "Sub-Asset-Class die es nicht gibt", prefs, score_bucket=4)

        assert hint is None


def test_hint_picks_the_lowest_required_bucket_across_multiple_candidates(session_factory):
    """Existieren mehrere Produkte fuer dieselbe Sub-Asset-Class mit
    unterschiedlichen Risikobaendern, muss der Hinweis das GUENSTIGSTE
    (niedrigste) Override-Ziel nennen -- nicht irgendeines."""
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        base = s.query(Product).filter(Product.sub_asset_class == "Thema Tabak").first()
        assert base is not None

        now = datetime.now(timezone.utc).isoformat()
        easier = Product(
            id="test-easier-band-product",
            product_name="Test Tabak Easier Band",
            provider="Test",
            product_type="ETF",
            asset_class=base.asset_class,
            sub_asset_class="Thema Tabak",
            currency="CHF",
            ter_bps=50,
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        s.add(easier)
        s.flush()
        s.add(ProductSuitability(
            id="test-easier-band-suitability",
            product_id=easier.id,
            profile_from=5,
            profile_to=10,
            advisory_allowed=1,
            created_at=now,
            updated_at=now,
        ))
        s.commit()

        products = s.query(Product).filter(Product.is_active == 1).all()
        prefs = _normalize_preferences(None)

        hint = _suitability_block_hint(products, "Thema Tabak", prefs, score_bucket=4)

        assert hint is not None
        assert "benoetigt mind. Bucket 5" in hint
        assert "Score >= 45" in hint
