"""Regression-Lock fuer den hedgingRequired-Katalogluecke-Bug (2026-08-22,
Live-Fund Holger Mueller): jedes Mandat mit `preferences.geo.hedgingRequired
= true` verlor stillschweigend die Diversifikation/Themen-Tilts seiner
sub_allocations_json, weil _product_matches_constraints() alle unhedged
(USD/EUR) Kandidaten hart ausschloss und der Default-Produktkatalog fuer
mehrere Sub-Asset-Classes (Aktien Global/Europa/Schwellenlaender, 5 Themen-
Tilts, Obligationen Emerging, Immobilien Global) ausschliesslich unhedged
Produkte enthielt. Fix: services/portfolio_engine.py::HEDGED_PRODUCT_VARIANTS
+ ensure_hedged_product_variants() (additiver Backfill fuer bereits
bestehende Installationen).

Diese Suite deckt zwei Ebenen ab:
1. Katalog-Vollstaendigkeit: jede betroffene Sub-Asset-Class hat jetzt
   mindestens ein CHF-/hedged-Pendant (verhindert, dass genau diese
   Bugklasse fuer eine dieser 10 Klassen zurueckkehrt).
2. Backfill-Mechanik: additiver Nachtrag auf einer bereits (aelter)
   geseedeten Installation funktioniert idempotent und vollstaendig.
3. End-to-End-Produktauswahl: mit hedgingRequired=true UND dem echten,
   geseedeten Katalog waehlt _product_matches_constraints()/candidate-
   Selektion jetzt das hedged Pendant statt in den Asset-Class-Fallback zu
   fallen.
"""
from __future__ import annotations

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
    allocation, clients, client_login, fx_rate, mandates, profiling,
    protocol_bausteine, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.review import Product, ProductSuitability  # noqa: E402
from services.portfolio_engine import (  # noqa: E402
    HEDGED_PRODUCT_VARIANTS,
    _normalize_preferences,
    _product_matches_constraints,
    ensure_default_products,
    ensure_hedged_product_variants,
)

# Die 10 Sub-Asset-Classes, die vor dem Fix ausschliesslich unhedged
# (USD/EUR) Produkte im Default-Katalog hatten.
AFFECTED_SUB_ASSET_CLASSES = [
    "Aktien Global",
    "Aktien Europa",
    "Aktien Schwellenlaender",
    "Thema Verteidigung",
    "Thema Fossile Energie",
    "Thema Tabak",
    "Thema Gluecksspiel",
    "Thema Kernenergie",
    "Obligationen Emerging",
    "Immobilien Global",
]


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


def test_hedged_product_variants_cover_all_affected_sub_asset_classes():
    covered = {entry[4] for entry in HEDGED_PRODUCT_VARIANTS}
    missing = [cls for cls in AFFECTED_SUB_ASSET_CLASSES if cls not in covered]
    assert not missing, f"Sub-Asset-Classes ohne CHF-gehedgtes Pendant: {missing}"


def test_hedged_product_variants_are_all_chf():
    non_chf = [entry[0] for entry in HEDGED_PRODUCT_VARIANTS if entry[5] != "CHF"]
    assert not non_chf, f"CHF-Hedged-Varianten mit falscher Waehrung: {non_chf}"


def test_fresh_install_seeds_hedged_variants(session_factory):
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        names = {p.product_name for p in s.query(Product).all()}
        for entry in HEDGED_PRODUCT_VARIANTS:
            assert entry[0] in names, f"{entry[0]} fehlt im Frisch-Seed"


def test_backfill_restores_missing_hedged_variants_on_old_install(session_factory):
    """Simuliert eine Installation, die vor diesem Fix bereits geseedet
    wurde (Holger Muellers echte Situation): die hedged Varianten fehlen,
    obwohl der restliche Katalog vollstaendig ist."""
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        hedged_names = [entry[0] for entry in HEDGED_PRODUCT_VARIANTS]
        old_products = s.query(Product).filter(Product.product_name.in_(hedged_names)).all()
        for p in old_products:
            s.query(ProductSuitability).filter(ProductSuitability.product_id == p.id).delete()
            s.delete(p)
        s.commit()
        assert s.query(Product).filter(Product.product_name.in_(hedged_names)).count() == 0

        ensure_hedged_product_variants(s)
        s.commit()

        restored = s.query(Product).filter(Product.product_name.in_(hedged_names)).all()
        assert len(restored) == len(hedged_names)
        for product in restored:
            suitability_count = s.query(ProductSuitability).filter(
                ProductSuitability.product_id == product.id,
            ).count()
            assert suitability_count == 1, f"{product.product_name} ohne Suitability-Zeile nach Backfill"


def test_backfill_is_idempotent(session_factory):
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        before = s.query(Product).count()
        ensure_hedged_product_variants(s)
        ensure_hedged_product_variants(s)
        s.commit()
        after = s.query(Product).count()
        assert after == before


@pytest.mark.parametrize("sub_asset_class", AFFECTED_SUB_ASSET_CLASSES)
def test_hedging_required_selects_hedged_product_not_fallback(session_factory, sub_asset_class):
    """End-to-End-Kern des Bugs: mit hedgingRequired=true muss die exakte
    Sub-Asset-Class ein Produkt finden, das die Constraint-Pruefung besteht
    -- ohne den Fix gab es fuer diese Klassen KEIN einziges passendes
    Produkt und die Selektion fiel auf den Asset-Class-Fallback zurueck."""
    with session_factory() as s:
        ensure_default_products(s, jurisdiction="CH")
        s.commit()
        prefs = _normalize_preferences({"geo": {"hedgingRequired": True}})
        candidates = s.query(Product).filter(
            Product.sub_asset_class == sub_asset_class,
            Product.is_active == 1,
        ).all()
        matching = [
            p for p in candidates
            if _product_matches_constraints(p, prefs, score_bucket=8)
        ]
        assert matching, (
            f"Kein hedgingRequired-konformes Produkt fuer {sub_asset_class} -- "
            "genau der Bug, den dieser Fix schliesst."
        )
        assert any(p.currency == "CHF" for p in matching)
