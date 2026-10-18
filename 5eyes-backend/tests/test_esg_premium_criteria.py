"""ESG-PREMIUM-CRITERIA-001 (Owner-Entscheid 2026-10-14, "premium, best approach").

Baut auf ESG-THEME-EXCLUSION-EFFECTIVE-001 auf (harter Themen-Filter).

1. Vierter Tilt-Zustand "allow" ("bewusst zulassen"):
   - "neutral" folgt der ESG-Policy (negative_screening -> ausgeschlossen).
   - "allow" uebersteuert das Negativ-Screening fuer dieses Thema, VERLANGT
     aber eine dokumentierte Begruendung (prefs.tiltReasons[theme], gleiche
     Qualitaetspruefung wie jeder andere Override:
     services.override_reason_quality) und erscheint im Anlagestrategie-PDF
     als dokumentierte Abweichung von der ESG-Policy.
2. Unterscheidbare, datengetriebene ESG-Policy-Kriterien:
   - esg_integration: SFDR Art. 8 oder 9.
   - best_in_class: SFDR 8/9 UND (esg_rating in AAA/AA ODER
     esg_score_x10 >= 714). Fehlende Daten -> nicht zulaessig.
     (CIO-Entscheid 2026-10-18: nur die Leader-Klasse; "A" zaehlt nicht.)
   - impact: NUR SFDR Art. 9.
   - net_zero: SFDR 8/9 UND climate_benchmark in {PAB, CTB}, beides
     PFLICHT; SFDR 9 allein reicht nicht, Art. 6 + Benchmark auch nicht
     (CIO-Entscheide 2026-10-18).
   Leere Slots laufen in den fail-closed-Pfad, dessen Meldung jetzt das
   verletzte Kriterium UND die betroffene Sub-Anlageklasse nennt.
3. Zweistufige Themen-Erkennung:
   a) Katalogfeld theme_tags (Liste von Themen-Keys) zusaetzlich zur
      Sub-Anlageklasse "Thema X"; Backfill fuer bestehende Themenprodukte.
   b) Look-through NUR fuer Fossile Energie ueber den gepflegten GICS-Sektor
      "Energy" (> 10 % = 1000 bps). Andere Themen sind Sub-Industrien und
      aus GICS-Sektoren nicht ableitbar -> kein Look-through, Offenlegung
      themenspezifisch.
"""
from __future__ import annotations

import ast
import csv
import io
import json
import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

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
from schemas.allocation import AllocationPreferencesPayload  # noqa: E402
from schemas.review import ProductCreate, ProductResponse, ProductUpdate  # noqa: E402
from services.portfolio_engine import _normalize_preferences  # noqa: E402
from services.portfolio_engine_payload import (  # noqa: E402
    CLIMATE_BENCHMARKS,
    ESG_BEST_IN_CLASS_MIN_SCORE_X10,
    ESG_BEST_IN_CLASS_RATINGS,
    ESG_POLICY_CRITERIA,
    FOSSIL_LOOK_THROUGH_SECTOR,
    FOSSIL_LOOK_THROUGH_THRESHOLD_BPS,
    _product_matches_constraints,
    _product_score,
    effective_theme_screening,
    product_meets_esg_policy,
    product_theme_keys,
    theme_policy_deviations,
    theme_screening_disclosure,
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
GOOD_REASON = (
    "Kunde haelt Tabakaktien bewusst aus Familientradition, schriftlich im "
    "Beratungsgespraech vom 14.10.2026 bestaetigt"
)


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
        "sfdr_class": "8",
        "is_active": 1,
        "created_at": "2026-01-01",
        "updated_at": "2026-01-01",
    }
    data.update(overrides)
    return Product(**data)


def _prefs(**sections) -> dict:
    return _normalize_preferences(sections)


# ---------------------------------------------------------------------------
# 1. Vierter Tilt-Zustand "allow"
# ---------------------------------------------------------------------------


def test_allow_requires_documented_reason():
    with pytest.raises(ValidationError, match="Begruendung"):
        AllocationPreferencesPayload.model_validate({"tilts": {"tobacco": "allow"}})


@pytest.mark.parametrize("reason", ["", "   ", "ok", "kundenwunsch", "Kunde will das so"])
def test_allow_rejects_low_quality_reason(reason):
    with pytest.raises(ValidationError):
        AllocationPreferencesPayload.model_validate(
            {"tilts": {"tobacco": "allow"}, "tiltReasons": {"tobacco": reason}}
        )


def test_allow_with_quality_reason_is_accepted_and_preserved():
    prefs = _prefs(tilts={"tobacco": "allow"}, tiltReasons={"tobacco": GOOD_REASON})
    assert prefs["tilts"]["tobacco"] == "allow"
    assert prefs["tiltReasons"]["tobacco"] == GOOD_REASON


def test_tilt_reasons_reject_unknown_theme_and_non_string():
    with pytest.raises(ValidationError):
        AllocationPreferencesPayload.model_validate({"tiltReasons": {"tabacco": GOOD_REASON}})
    with pytest.raises(ValidationError):
        AllocationPreferencesPayload.model_validate({"tiltReasons": {"tobacco": 42}})


def test_normalized_prefs_without_reasons_have_no_tilt_reasons_key():
    """Drift-Stabilitaet: der gespeicherte preferences_json-Snapshot wird per
    Stringvergleich gegen den aktuellen verglichen -- ein neuer, leerer Key
    wuerde JEDE bestehende Allokation als 'Praeferenzen geaendert' melden."""
    assert "tiltReasons" not in _normalize_preferences(None)
    assert "tiltReasons" not in _normalize_preferences({"tilts": {"tobacco": "exclude"}})


def test_allow_overrides_negative_screening_only_for_that_theme():
    prefs = _prefs(
        policy={"esg": "negative_screening"},
        tilts={key: "neutral" for key in THEMES} | {"tobacco": "allow"},
        tiltReasons={"tobacco": GOOD_REASON},
    )
    assert _product_matches_constraints(_product(sub_asset_class="Thema Tabak", sfdr_class="6"), prefs, 8) is True
    assert _product_matches_constraints(_product(sub_asset_class="Thema Alkohol", sfdr_class="6"), prefs, 8) is False
    screened = effective_theme_screening(prefs)
    assert "tobacco" not in screened and screened["alcohol"] == "exclude"


def test_neutral_follows_negative_screening():
    prefs = _prefs(policy={"esg": "negative_screening"}, tilts={"tobacco": "neutral"})
    assert _product_matches_constraints(_product(sub_asset_class="Thema Tabak"), prefs, 8) is False


def test_allow_without_negative_screening_behaves_like_neutral():
    allow = _prefs(tilts={"tobacco": "allow"}, tiltReasons={"tobacco": GOOD_REASON})
    neutral = _prefs(tilts={"tobacco": "neutral"})
    tobacco = _product(sub_asset_class="Thema Tabak")
    assert _product_matches_constraints(tobacco, allow, 8) is _product_matches_constraints(tobacco, neutral, 8) is True
    assert _product_score(tobacco, "Aktien Global", allow) == _product_score(tobacco, "Aktien Global", neutral)
    assert effective_theme_screening(allow) == {}


def test_policy_deviations_list_allow_and_overweight_under_negative_screening():
    prefs = _prefs(
        policy={"esg": "negative_screening"},
        tilts={"tobacco": "allow", "alcohol": "overweight", "gaming": "neutral"},
        tiltReasons={"tobacco": GOOD_REASON},
    )
    deviations = theme_policy_deviations(prefs)
    assert deviations["tobacco"] == {"mode": "allow", "reason": GOOD_REASON}
    assert deviations["alcohol"]["mode"] == "overweight"
    assert "gaming" not in deviations
    # Ohne Negativ-Screening ist "overweight" keine Abweichung von einer
    # Ausschluss-Policy; "allow" bleibt als bewusster Entscheid dokumentiert.
    no_policy = _prefs(tilts={"tobacco": "allow", "alcohol": "overweight"}, tiltReasons={"tobacco": GOOD_REASON})
    assert set(theme_policy_deviations(no_policy)) == {"tobacco"}


def test_run_disclosure_names_the_documented_deviation():
    prefs = _prefs(
        policy={"esg": "negative_screening"},
        tilts={"tobacco": "allow"},
        tiltReasons={"tobacco": GOOD_REASON},
    )
    disclosure = theme_screening_disclosure(prefs)
    assert disclosure is not None
    assert "Tabak bewusst zugelassen" in disclosure
    assert "Abweichung" in disclosure


# ---------------------------------------------------------------------------
# 2. ESG-Policy-Kriterien
# ---------------------------------------------------------------------------


def test_documented_thresholds():
    assert ESG_BEST_IN_CLASS_RATINGS == ("AAA", "AA")
    assert ESG_BEST_IN_CLASS_MIN_SCORE_X10 == 714
    assert CLIMATE_BENCHMARKS == ("PAB", "CTB")
    assert FOSSIL_LOOK_THROUGH_SECTOR == "Energy"
    assert FOSSIL_LOOK_THROUGH_THRESHOLD_BPS == 1000


@pytest.mark.parametrize(
    "policy,product_kwargs,expected",
    [
        # esg_integration: SFDR 8 oder 9
        ("esg_integration", {"sfdr_class": "8"}, True),
        ("esg_integration", {"sfdr_class": "9"}, True),
        ("esg_integration", {"sfdr_class": "6"}, False),
        ("esg_integration", {"sfdr_class": None}, False),
        # best_in_class: SFDR 8/9 UND Qualitaetsschwelle
        ("best_in_class", {"sfdr_class": "8", "esg_rating": "A"}, False),
        ("best_in_class", {"sfdr_class": "9", "esg_rating": "A"}, False),
        ("best_in_class", {"sfdr_class": "8", "esg_rating": "AA"}, True),
        ("best_in_class", {"sfdr_class": "9", "esg_rating": "AAA"}, True),
        ("best_in_class", {"sfdr_class": "8", "esg_rating": " aa "}, True),
        ("best_in_class", {"sfdr_class": "8", "esg_rating": "BBB"}, False),
        ("best_in_class", {"sfdr_class": "8", "esg_rating": None}, False),
        ("best_in_class", {"sfdr_class": "8", "esg_rating": "BBB", "esg_score_x10": 714}, True),
        ("best_in_class", {"sfdr_class": "8", "esg_rating": "A", "esg_score_x10": 713}, False),
        ("best_in_class", {"sfdr_class": "8", "esg_rating": None, "esg_score_x10": 600}, False),
        ("best_in_class", {"sfdr_class": "8", "esg_score_x10": 850}, True),
        ("best_in_class", {"sfdr_class": "6", "esg_rating": "AAA", "esg_score_x10": 900}, False),
        # impact: NUR SFDR 9
        ("impact", {"sfdr_class": "9"}, True),
        ("impact", {"sfdr_class": "8", "esg_rating": "AAA"}, False),
        ("impact", {"sfdr_class": "6"}, False),
        # net_zero: SFDR 8/9 UND EU-Klima-Benchmark, beides PFLICHT
        ("net_zero", {"sfdr_class": "9"}, False),
        ("net_zero", {"sfdr_class": "9", "climate_benchmark": None}, False),
        ("net_zero", {"sfdr_class": "9", "climate_benchmark": "PAB"}, True),
        ("net_zero", {"sfdr_class": "9", "climate_benchmark": "CTB"}, True),
        ("net_zero", {"sfdr_class": "8", "climate_benchmark": "PAB"}, True),
        ("net_zero", {"sfdr_class": "8", "climate_benchmark": " ctb "}, True),
        # CIO-Entscheid 2026-10-18: Art. 6 + Transition-Benchmark ist KEIN Net Zero.
        ("net_zero", {"sfdr_class": "6", "climate_benchmark": "CTB"}, False),
        ("net_zero", {"sfdr_class": "6", "climate_benchmark": "PAB"}, False),
        ("net_zero", {"sfdr_class": None, "climate_benchmark": "PAB"}, False),
        ("net_zero", {"sfdr_class": "8"}, False),
        ("net_zero", {"sfdr_class": "8", "climate_benchmark": "ESG"}, False),
    ],
)
def test_esg_policy_criteria(policy, product_kwargs, expected):
    product = _product(**product_kwargs)
    assert product_meets_esg_policy(product, policy) is expected
    prefs = _prefs(policy={"esg": policy})
    assert _product_matches_constraints(product, prefs, 8) is expected


@pytest.mark.parametrize("policy", ["esg_integration", "best_in_class", "impact", "net_zero"])
def test_liquidity_stays_exempt_from_esg_criteria(policy):
    cash = _product(asset_class="Liquidität", sub_asset_class="Kontoguthaben", product_type="Cash", sfdr_class=None)
    assert _product_matches_constraints(cash, _prefs(policy={"esg": policy}), 8) is True


def test_no_esg_policy_does_not_filter():
    for policy in ("none", "negative_screening"):
        assert _product_matches_constraints(_product(sfdr_class="6"), _prefs(policy={"esg": policy}), 8) is True


@pytest.mark.parametrize("policy", ["esg_integration", "best_in_class", "impact", "net_zero"])
def test_every_sfdr_policy_has_a_documented_criterion(policy):
    assert ESG_POLICY_CRITERIA[policy]


# ---------------------------------------------------------------------------
# 3a. theme_tags
# ---------------------------------------------------------------------------


def test_theme_tag_marks_core_product_as_theme_product():
    tagged = _product(sub_asset_class="Aktien Global", theme_tags=json.dumps(["tobacco"]))
    assert product_theme_keys(tagged) == frozenset({"tobacco"})
    prefs = _prefs(tilts={"tobacco": "exclude"})
    assert _product_matches_constraints(tagged, prefs, 8) is False
    assert _product_score(tagged, "Aktien Global", prefs) == -10000
    assert _product_matches_constraints(tagged, _prefs(tilts={"alcohol": "exclude"}), 8) is True


def test_sub_asset_class_and_tags_combine():
    product = _product(sub_asset_class="Thema Kernenergie", theme_tags=json.dumps(["defense"]))
    assert product_theme_keys(product) == frozenset({"nuclear", "defense"})


def test_malformed_theme_tags_do_not_crash_and_do_not_classify():
    product = _product(theme_tags="not-json")
    assert product_theme_keys(product) == frozenset()


# ---------------------------------------------------------------------------
# 3b. Look-through Fossile Energie ueber GICS "Energy"
# ---------------------------------------------------------------------------


def _sectors(energy_bps: int) -> str:
    return json.dumps({"Energy": energy_bps, "Information Technology": 10000 - energy_bps})


@pytest.mark.parametrize(
    "energy_bps,expected_fossil",
    [(450, False), (999, False), (1000, False), (1001, True), (2500, True)],
)
def test_fossil_look_through_threshold(energy_bps, expected_fossil):
    product = _product(sector_exposure_json=_sectors(energy_bps))
    assert ("fossil" in product_theme_keys(product)) is expected_fossil
    prefs = _prefs(tilts={"fossil": "exclude"})
    assert _product_matches_constraints(product, prefs, 8) is (not expected_fossil)


def test_look_through_needs_maintained_sector_data():
    """Ohne gepflegte Sektordaten KEIN Look-through -- auch nicht ueber den
    Sub-Klassen-Proxy aus services/product_exposures.py (der ist eine
    Schaetzung, keine Produktdaten)."""
    product = _product(sub_asset_class="Aktien Global", sector_exposure_json=None)
    assert product_theme_keys(product) == frozenset()


def test_energy_look_through_applies_only_to_fossil():
    product = _product(sector_exposure_json=_sectors(4000))
    assert _product_matches_constraints(product, _prefs(tilts={"nuclear": "exclude"}), 8) is True


def test_look_through_respects_underweight_and_allow():
    product = _product(sector_exposure_json=_sectors(3000))
    assert _product_matches_constraints(product, _prefs(tilts={"fossil": "underweight"}), 8) is False
    allow = _prefs(
        policy={"esg": "negative_screening"},
        tilts={"fossil": "allow"},
        tiltReasons={"fossil": "Rohstoffnahe Unternehmerfamilie, bewusster Entscheid laut Gespraech 14.10."},
    )
    assert _product_matches_constraints(product, allow, 8) is True


@pytest.mark.parametrize(
    "sub_asset_class",
    ["Aktien Global", "Aktien Schweiz", "Aktien Europa", "Aktien Schwellenlaender"],
)
def test_broad_core_equity_proxies_stay_below_fossil_threshold(sub_asset_class):
    """Kontrolle mit den realistischen Index-Sektorgewichten aus
    services/product_exposures.py: ein breiter Kern-ETF (Welt ~4.5 %,
    Schweiz ~0.5 %, Europa/EM ~6 % Energy) wird bei 10 % NICHT ausgeschlossen."""
    from services.product_exposures import _SECTOR_PROXIES_BY_SUB_CLASS

    weights = _SECTOR_PROXIES_BY_SUB_CLASS[sub_asset_class]
    product = _product(sub_asset_class=sub_asset_class, sector_exposure_json=json.dumps(weights))
    assert "fossil" not in product_theme_keys(product)


def test_disclosure_is_theme_specific():
    disclosure = theme_screening_disclosure(_prefs(tilts={"fossil": "exclude", "tobacco": "exclude"}))
    assert "Fossile Energie" in disclosure
    assert "Energie-Sektoranteil > 10 %" in disclosure
    assert "Look-through" in disclosure
    assert "Tabak" in disclosure and "nur als Themenprodukt" in disclosure
    tobacco_only = theme_screening_disclosure(_prefs(tilts={"tobacco": "exclude"}))
    assert "Energie-Sektoranteil" not in tobacco_only
    assert "nicht durchleuchtet" in tobacco_only


# ---------------------------------------------------------------------------
# 4. End-to-end: fail-closed-Meldung + Kern-Universum unter Fossil-Ausschluss
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    engine = create_engine(f"sqlite:///{tmp_path / 'esg_premium.db'}", connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        engine.dispose()


def _run(SF, mandate_id, advisor_id, prefs):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = pe.generate_recommendation_run(s, mandate, advisor_id, prefs)
        positions = [(p["product_name"], p["target_weight_bps"]) for p in result["positions"]]
        warnings = list(result.get("warnings") or [])
        s.rollback()
        return positions, warnings


def test_e2e_impact_fails_closed_naming_criterion_and_sub_asset_class(session_factory):
    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(session_factory, "esg-impact")
    with pytest.raises(ValueError) as excinfo:
        _run(session_factory, mandate_id, advisor_id, {"policy": {"esg": "impact"}})
    message = str(excinfo.value)
    assert "Produktselektion unvollstaendig" in message
    assert "Impact Investing" in message
    assert "SFDR Art. 9" in message
    assert re.search(r"Aktien \w+", message), message


def test_gap_hint_only_when_criterion_is_the_blocker():
    from services.portfolio_engine_payload import esg_policy_gap_hint

    prefs = _prefs(policy={"esg": "impact"})
    sfdr8 = _product(id="a", sub_asset_class="Aktien Global", sfdr_class="8")
    sfdr9_other = _product(id="b", sub_asset_class="Aktien Europa", sfdr_class="9")
    hint = esg_policy_gap_hint([sfdr8], "Aktien Global", "Aktien", prefs, 8)
    assert "Impact Investing (nur Produkte nach SFDR Art. 9)" in hint
    assert "0 von 1" in hint and "Aktien Global" in hint
    # Exakte Klasse hat ein Art.-9-Produkt -> Kriterium ist nicht der Grund.
    assert esg_policy_gap_hint([_product(sfdr_class="9")], "Aktien Global", "Aktien", prefs, 8) is None
    # Reine Katalogluecke in der Sub-Klasse, Ersatz moeglich -> kein Hinweis.
    assert esg_policy_gap_hint([sfdr9_other], "Aktien Global", "Aktien", prefs, 8) is None
    # Keine ESG-Policy -> nie ein Hinweis.
    assert esg_policy_gap_hint([sfdr8], "Aktien Global", "Aktien", _prefs(), 8) is None


def test_e2e_seed_catalog_core_universe_implementable_under_fossil_exclusion(session_factory):
    """Der Kern-Katalog muss unter Fossil-Ausschluss umsetzbar bleiben --
    auch wenn die Kern-ETFs gepflegte (realistische) Sektordaten tragen."""
    from services.product_exposures import _SECTOR_PROXIES_BY_SUB_CLASS

    advisor_id, _cid, mandate_id, _aid = _seed_realistic_mandate(session_factory, "esg-fossil")
    with session_factory() as s:
        pe.ensure_default_products(s, jurisdiction="CH")
        pe.ensure_hedged_product_variants(s)
        for product in s.query(Product).filter(Product.asset_class == "Aktien").all():
            proxy = _SECTOR_PROXIES_BY_SUB_CLASS.get(str(product.sub_asset_class))
            if proxy and not str(product.sub_asset_class).startswith("Thema "):
                product.sector_exposure_json = json.dumps(proxy)
        s.commit()
    positions, warnings = _run(session_factory, mandate_id, advisor_id, {"tilts": {"fossil": "exclude"}})
    names = [name for name, _w in positions]
    assert names
    assert not any("Energy" in name for name in names)
    assert sum(w for _n, w in positions) >= 9950


def test_seed_catalog_tags_theme_products():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(bind=engine)
    with SF() as s:
        pe.ensure_default_products(s, jurisdiction="CH")
        pe.ensure_hedged_product_variants(s)
        s.commit()
        for product in s.query(Product).all():
            key = {label: k for k, label in THEMES.items()}.get(str(product.sub_asset_class))
            if key:
                assert json.loads(product.theme_tags) == [key], product.product_name
            else:
                assert product.theme_tags is None, product.product_name


# ---------------------------------------------------------------------------
# 5. Katalogfelder: ORM, Runtime-Ensurer, Alembic, Schemas, CSV
# ---------------------------------------------------------------------------


def test_product_model_has_new_columns():
    columns = {c.name for c in Product.__table__.columns}
    assert {"theme_tags", "climate_benchmark"} <= columns


def test_fresh_bootstrap_gets_columns_and_backfills_theme_tags(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql")
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    columns = {c["name"] for c in inspect(test_engine).get_columns("products")}
    assert {"theme_tags", "climate_benchmark"} <= columns
    with test_engine.begin() as conn:
        for idx, sub in enumerate(["Thema Tabak", "Aktien Global"]):
            conn.execute(text(
                "INSERT INTO products (id, product_name, product_type, asset_class, sub_asset_class, "
                "currency, is_active, created_at, updated_at) VALUES "
                "(:id, :name, 'ETF', 'Aktien', :sub, 'CHF', 1, '2026', '2026')"
            ), {"id": f"p{idx}", "name": f"P{idx}", "sub": sub})
        conn.execute(text(
            "INSERT INTO products (id, product_name, product_type, asset_class, sub_asset_class, "
            "currency, is_active, created_at, updated_at, theme_tags) VALUES "
            "('p2', 'P2', 'ETF', 'Aktien', 'Thema Alkohol', 'CHF', 1, '2026', '2026', '[\"alcohol\", \"gaming\"]')"
        ))
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    with test_engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, theme_tags FROM products")).fetchall())
    assert json.loads(rows["p0"]) == ["tobacco"]
    assert rows["p1"] is None
    assert json.loads(rows["p2"]) == ["alcohol", "gaming"]  # gepflegte Tags nie ueberschreiben


def _migration_files() -> dict[str, ast.Module]:
    out = {}
    for path in (BACKEND_ROOT / "alembic" / "versions").glob("*.py"):
        out[path.name] = ast.parse(path.read_text(encoding="utf-8"))
    return out


def _assigned(module: ast.Module, name: str):
    for node in module.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target == name and isinstance(value, ast.Constant):
            return value.value
    return None


def test_alembic_migration_adds_columns_as_single_head():
    modules = _migration_files()
    revisions = {name: _assigned(mod, "revision") for name, mod in modules.items()}
    downs = {_assigned(mod, "down_revision") for mod in modules.values()}
    heads = [name for name, rev in revisions.items() if rev not in downs]
    assert len(heads) == 1, heads
    # Die ESG-Migration muss nicht der Head sein (spaetere Migrationen haengen
    # sich an); sie muss genau einmal existieren und in der Kette liegen.
    esg = [
        name for name in modules
        if "theme_tags" in (BACKEND_ROOT / "alembic" / "versions" / name).read_text(encoding="utf-8")
        and "add_column" in (BACKEND_ROOT / "alembic" / "versions" / name).read_text(encoding="utf-8")
    ]
    assert len(esg) == 1, esg
    esg_src = (BACKEND_ROOT / "alembic" / "versions" / esg[0]).read_text(encoding="utf-8")
    assert "theme_tags" in esg_src and "climate_benchmark" in esg_src
    assert "Thema Fossile Energie" in esg_src  # Backfill
    chain, cursor = set(), revisions[heads[0]]
    by_rev = {rev: name for name, rev in revisions.items()}
    while cursor in by_rev:
        chain.add(by_rev[cursor])
        cursor = _assigned(modules[by_rev[cursor]], "down_revision")
    assert esg[0] in chain


def test_product_create_accepts_and_canonicalizes_theme_tags():
    base = {
        "product_name": "X", "product_type": "ETF", "asset_class": "Aktien",
        "suitability_profile_from": 1, "suitability_profile_to": 10,
    }
    body = ProductCreate(**base, theme_tags=["nuclear", "fossil", "fossil"], climate_benchmark="pab")
    assert body.theme_tags == '["fossil", "nuclear"]'
    assert body.climate_benchmark == "PAB"
    assert ProductCreate(**base, theme_tags='["tobacco"]').theme_tags == '["tobacco"]'
    assert ProductCreate(**base, theme_tags="tobacco;gaming").theme_tags == '["gaming", "tobacco"]'
    assert ProductCreate(**base, theme_tags=[]).theme_tags == "[]"
    with pytest.raises(ValidationError):
        ProductCreate(**base, theme_tags=["tabacco"])
    with pytest.raises(ValidationError):
        ProductCreate(**base, climate_benchmark="ESG")
    assert ProductUpdate(theme_tags=["defense"]).theme_tags == '["defense"]'
    with pytest.raises(ValidationError):
        ProductUpdate(climate_benchmark="Paris")


def test_product_response_returns_theme_tags_as_list():
    product = _product(theme_tags='["defense"]', climate_benchmark="CTB")
    response = ProductResponse.model_validate(product, from_attributes=True)
    assert response.theme_tags == ["defense"]
    assert response.climate_benchmark == "CTB"
    assert ProductResponse.model_validate(_product(), from_attributes=True).theme_tags is None


def test_csv_import_accepts_new_fields(tmp_path):
    from fastapi.testclient import TestClient  # noqa: F401
    from main import app
    from test_products_fund_universe import _client_for, _seed_tenants

    engine = create_engine(f"sqlite:///{tmp_path / 'csv.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _seed_tenants(SF, ["firm-a"])
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "product_name", "product_type", "asset_class", "sub_asset_class", "currency", "sfdr_class",
        "esg_rating", "esg_score_x10", "climate_benchmark", "theme_tags",
        "suitability_profile_from", "suitability_profile_to",
    ])
    writer.writerow(["Paris ETF", "ETF", "Aktien", "Aktien Global", "CHF", "8", "BBB", "640", "PAB", "", "3", "10"])
    writer.writerow(["Mixed ETF", "ETF", "Aktien", "Aktien Global", "CHF", "6", "", "", "", "fossil;nuclear", "3", "10"])
    try:
        with _client_for(SF, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import/csv", files={"file": ("f.csv", buffer.getvalue().encode(), "text/csv")})
            assert resp.status_code == 201, resp.text
            assert resp.json()["created"] == 2, resp.json()
            listed = {p["product_name"]: p for p in client.get("/products").json()}
            template = client.get("/products/import/csv/template").text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
    assert listed["Paris ETF"]["climate_benchmark"] == "PAB"
    assert listed["Paris ETF"]["esg_score_x10"] == 640
    assert listed["Mixed ETF"]["theme_tags"] == ["fossil", "nuclear"]
    header = template.splitlines()[0].split(",")
    assert {"esg_score_x10", "climate_benchmark", "theme_tags"} <= set(header)
    for line in template.splitlines()[1:]:
        assert len(next(csv.reader([line]))) == len(header), line


# ---------------------------------------------------------------------------
# 6. Monolith-UI und PDF: Dokument == Engine
# ---------------------------------------------------------------------------


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _option_label(select_id: str, value: str) -> str:
    select = re.search(r'id="%s"[^>]*>(.*?)</select>' % select_id, _html())
    assert select, select_id
    option = re.search(r'<option value="%s"[^>]*>([^<]*)</option>' % value, select.group(1))
    assert option, (select_id, value)
    return option.group(1)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_ui_tilt_select_offers_allow_with_reason_input(theme):
    assert _option_label(f"aa-tilt-{theme}", "allow") == "Bewusst zulassen"
    assert "ESG-Policy" in _option_label(f"aa-tilt-{theme}", "neutral")
    assert f'id="aa-tilt-reason-{theme}"' in _html()


def test_ui_sends_tilt_reasons_and_persists_them():
    html = _html()
    collect = re.search(r"function collectAllocationPreferencesFromUI\(\)\{(.*?)\n\}", html, re.S).group(1)
    assert "prefs.tiltReasons=collectTiltReasonsFromUI(live.tilts)" in collect
    helper = re.search(r"function collectTiltReasonsFromUI\(tilts\)\{(.*?)\n\}", html, re.S).group(1)
    assert "aa-tilt-reason-" in helper and "'allow'" in helper
    merge = re.search(r"function mergeAllocationPreferences\(base,override\)\{(.*?)\n\}", html, re.S).group(1)
    assert "'tiltReasons'" in merge
    apply_ = re.search(r"function applyAllocationPreferencesToUI\(prefs\)\{(.*?)\n\}", html, re.S).group(1)
    assert "tiltReasons" in apply_


@pytest.mark.parametrize(
    "policy,fragments",
    [
        ("esg_integration", ["SFDR 8/9"]),
        ("best_in_class", ["SFDR 8/9", "AAA", "AA", "71.4"]),
        ("impact", ["nur SFDR 9"]),
        ("net_zero", ["PAB", "CTB", "Pflicht"]),
    ],
)
def test_ui_esg_labels_state_exact_criterion(policy, fragments):
    label = _option_label("aa-policy-esg", policy)
    for fragment in fragments:
        assert fragment in label, label
    if policy == "impact":
        assert "8/9" not in label
    if policy == "best_in_class":
        assert "AAA–A " not in label and "AAA/AA/A" not in label and "≥ 60" not in label
    if policy == "net_zero":
        assert "SFDR 9 oder" not in label


def test_ui_screening_note_is_theme_specific():
    note = re.search(r'id="aa-tilt-screening-note"[^>]*>(.*?)</div>', _html(), re.S).group(1)
    assert "Energie-Sektoranteil" in note and "10 %" in note
    assert "Bewusst zulassen" in note and "Begründung" in note


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


@pytest.mark.parametrize("policy", ["esg_integration", "best_in_class", "impact", "net_zero"])
def test_pdf_esg_label_states_exact_engine_criterion(policy):
    text_ = _pdf_preferences_text({"policy": {"esg": policy}})
    assert ESG_POLICY_CRITERIA[policy] in text_


def test_pdf_documents_allow_as_deviation_with_reason():
    text_ = _pdf_preferences_text(_prefs(
        policy={"esg": "negative_screening"},
        tilts={key: "neutral" for key in THEMES} | {"tobacco": "allow"},
        tiltReasons={"tobacco": GOOD_REASON},
    ))
    assert "Tabak ausschliessen" not in text_
    assert "Alkohol ausschliessen" in text_
    assert "Abweichungen von der ESG-Policy" in text_
    assert "Tabak bewusst zugelassen" in text_
    assert GOOD_REASON in text_


def test_pdf_flags_overweight_under_negative_screening_as_deviation():
    text_ = _pdf_preferences_text(_prefs(
        policy={"esg": "negative_screening"}, tilts={"alcohol": "overweight"},
    ))
    assert "Abweichungen von der ESG-Policy" in text_
    assert "Alkohol uebergewichtet" in text_


def test_pdf_screening_note_is_theme_specific():
    text_ = _pdf_preferences_text({"tilts": {"fossil": "exclude"}})
    assert "Energie-Sektoranteil > 10 %" in text_


def test_duplicated_vocabularies_stay_in_sync():
    """schemas/ und database.py duplizieren das Vokabular bewusst (Leaf-
    Schichten) -- hier gegen die Engine-Quelle gepinnt."""
    import database as db_module
    import schemas.review as review_schema
    from schemas.allocation import _VALID_TILT_KEYS, _VALID_TILT_VALUES
    from services.portfolio_engine_payload import THEME_SUB_ASSET_CLASSES, THEME_TILT_ALLOW

    assert set(review_schema._THEME_TAG_KEYS) == set(THEME_SUB_ASSET_CLASSES) == set(_VALID_TILT_KEYS)
    assert tuple(review_schema._CLIMATE_BENCHMARKS) == CLIMATE_BENCHMARKS
    assert THEME_TILT_ALLOW in _VALID_TILT_VALUES
    assert dict(db_module.THEME_TAG_BACKFILL) == {
        label: json.dumps([key]) for key, label in THEME_SUB_ASSET_CLASSES.items()
    }


def _extract_js_function(html: str, name: str) -> str:
    marker = f"function {name}("
    start = html.index(marker)
    depth = 0
    i = html.index("{", start)
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start : i + 1]
        i += 1
    raise AssertionError(name)


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node nicht verfuegbar")
def test_real_monolith_js_sends_reason_only_for_allow_or_overweight_and_toggles_input():
    import subprocess

    html = _html()
    script = """
    var values = %s;
    function getInputValue(id){ return values[id]; }
    var inputs = ['fossil','tobacco','alcohol'].map(function(key){
      return {key:key, style:{display:'none'}, required:false, getAttribute:function(){ return key; }};
    });
    var document = {querySelectorAll: function(){ return inputs; }};
    %s
    %s
    syncTiltReasonVisibility();
    var reasons = collectTiltReasonsFromUI({fossil:'allow', tobacco:'neutral', alcohol:'overweight'});
    process.stdout.write(JSON.stringify({reasons: reasons, inputs: inputs.map(function(i){
      return {key:i.key, display:i.style.display, required:i.required};
    })}));
    """ % (
        json.dumps({
            "aa-tilt-fossil": "allow", "aa-tilt-tobacco": "neutral", "aa-tilt-alcohol": "overweight",
            "aa-tilt-reason-fossil": "  Begruendung fossil  ", "aa-tilt-reason-tobacco": "stale",
            "aa-tilt-reason-alcohol": "",
        }),
        _extract_js_function(html, "collectTiltReasonsFromUI"),
        _extract_js_function(html, "syncTiltReasonVisibility"),
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["reasons"] == {"fossil": "Begruendung fossil"}
    by_key = {item["key"]: item for item in result["inputs"]}
    assert by_key["fossil"] == {"key": "fossil", "display": "", "required": True}
    assert by_key["tobacco"]["display"] == "none"
    assert by_key["alcohol"] == {"key": "alcohol", "display": "", "required": False}


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node nicht verfuegbar")
def test_real_admin_fund_form_sends_esg_criteria_data():
    """Fondsuniversum-Formular: die Daten der ESG-Kriterien (SFDR, Rating,
    Score, EU-Klima-Benchmark) und die Themen-Zuordnung werden erfasst und an
    POST /products gesendet -- ohne diese Felder waere jedes im Formular
    erfasste Produkt fuer jede ESG-Policy fail-closed unzulaessig."""
    import subprocess

    html = _html()
    for element_id in ("pf-sfdr", "pf-esg-rating", "pf-esg-score", "pf-climate-benchmark"):
        assert f'id="{element_id}"' in html
    for theme in THEMES:
        assert f'class="pf-theme-tag" value="{theme}"' in html
    script = """
    var values = %s;
    var boxes = [{value:'fossil', checked:true}, {value:'tobacco', checked:false}, {value:'nuclear', checked:true}];
    var document = {
      getElementById: function(id){ return id in values ? {value: values[id], style:{}} : null; },
      querySelectorAll: function(){ return boxes; }
    };
    var sent = null;
    var API = {post: function(path, payload){ sent = {path: path, payload: payload}; return Promise.resolve({id:'x'}); }};
    var adminFundEditingId = null;
    var adminProductUniverseState = {products: []};
    function adminPopulateProductUniverseProductSelect(){}
    function adminToggleFundCreateForm(){}
    function adminSearchFunds(){}
    function parseApiError(e){ return String(e); }
    %s
    adminCreateFund().then(function(){ process.stdout.write(JSON.stringify(sent)); });
    """ % (
        json.dumps({
            "pf-name": "Paris ETF", "pf-provider": "", "pf-product-type": "ETF", "pf-asset-class": "Aktien",
            "pf-sub-asset-class": "Aktien Global", "pf-currency": "CHF", "pf-isin": "", "pf-symbol": "",
            "pf-ter": "", "pf-error": "", "pf-sfdr": "8", "pf-esg-rating": "BBB", "pf-esg-score": "64.5",
            "pf-climate-benchmark": "PAB", "pf-suit-from": "3", "pf-suit-to": "7",
        }),
        # _extract_js_function beginnt bei "function" -- die Funktion ist async.
        "async " + _extract_js_function(html, "adminCreateFund"),
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    sent = json.loads(proc.stdout)
    assert sent["path"] == "/products"
    payload = sent["payload"]
    assert payload["sfdr_class"] == "8"
    assert payload["esg_rating"] == "BBB"
    assert payload["esg_score_x10"] == 645
    assert payload["climate_benchmark"] == "PAB"
    assert payload["theme_tags"] == ["fossil", "nuclear"]


# ---------------------------------------------------------------------------
# 7. Self-Review-Nachtrag: Dokument behauptet nie mehr, als die Daten tragen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("policy", ["esg_integration", "best_in_class", "impact", "net_zero"])
def test_pdf_esg_label_discloses_liquidity_exemption(policy):
    """Die Engine nimmt die gesamte Anlageklasse Liquiditaet vom Kriterium
    aus (test_liquidity_stays_exempt_from_esg_criteria). Ohne diesen Hinweis
    behauptete das PDF z.B. 'nur Produkte nach SFDR Art. 9', obwohl jedes
    Portfolio eine Liquiditaetsposition traegt."""
    from services.portfolio_engine_payload import ESG_POLICY_LIQUIDITY_EXEMPTION

    text_ = _pdf_preferences_text({"policy": {"esg": policy}})
    assert ESG_POLICY_LIQUIDITY_EXEMPTION in text_
    assert ESG_POLICY_LIQUIDITY_EXEMPTION not in _pdf_preferences_text({"policy": {"esg": "none"}})


def test_product_update_can_clear_esg_evidence_fields(tmp_path):
    """Ein einmal gesetzter Nachweis (z.B. climate_benchmark='PAB', der ein
    Produkt fuer net_zero zulaessig macht) muss sich per PUT wieder entfernen
    lassen -- vorher verwarf exclude_none ein explizites null, das Produkt
    blieb fuer immer 'Paris-aligned'. Nicht gesendete Felder bleiben."""
    from main import app
    from test_products_fund_universe import _client_for, _seed_tenants

    engine = create_engine(f"sqlite:///{tmp_path / 'put.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _seed_tenants(SF, ["firm-a"])
    try:
        with _client_for(SF, user_id="u-a", tenant_id="firm-a") as client:
            created = client.post("/products", json={
                "product_name": "Paris ETF", "product_type": "ETF", "asset_class": "Aktien",
                "sub_asset_class": "Aktien Global", "currency": "CHF", "sfdr_class": "8",
                "esg_rating": "AA", "esg_score_x10": 700, "climate_benchmark": "PAB",
                "suitability_profile_from": 1, "suitability_profile_to": 10,
            })
            assert created.status_code == 201, created.text
            pid = created.json()["id"]
            kept = client.put(f"/products/{pid}", json={"product_name": "Paris ETF 2"})
            assert kept.status_code == 200, kept.text
            assert kept.json()["climate_benchmark"] == "PAB"
            assert kept.json()["esg_rating"] == "AA"
            cleared = client.put(f"/products/{pid}", json={
                "climate_benchmark": None, "esg_rating": None,
                "esg_score_x10": None, "sfdr_class": None,
            })
            assert cleared.status_code == 200, cleared.text
            body = cleared.json()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
    assert body["climate_benchmark"] is None
    assert body["esg_rating"] is None
    assert body["esg_score_x10"] is None
    assert body["sfdr_class"] is None
    assert body["product_name"] == "Paris ETF 2"


def test_ui_fund_edit_sends_null_to_clear_esg_evidence():
    body = _extract_js_function(_html(), "adminCreateFund")
    for field in ("sfdr_class", "esg_rating", "climate_benchmark", "esg_score_x10"):
        assert re.search(r"payload\." + field + r"\s*=\s*null", body), field


# ---------------------------------------------------------------------------
# 8. CIO-Entscheid 2026-10-18 (konservativ, gegen Greenwashing)
# ---------------------------------------------------------------------------


def test_best_in_class_criterion_text_names_only_leader_class():
    text_ = ESG_POLICY_CRITERIA["best_in_class"]
    assert "AAA oder AA" in text_
    assert "71.4" in text_
    assert "AA oder A " not in text_ and "60.0" not in text_


def test_net_zero_criterion_text_requires_climate_benchmark():
    text_ = ESG_POLICY_CRITERIA["net_zero"]
    assert "PAB" in text_ and "CTB" in text_
    assert "SFDR Art. 9 oder" not in text_
    assert "SFDR Art. 9 allein genuegt nicht" in text_
    # CIO-Entscheid 2026-10-18: Text nennt beide Pflichtbedingungen.
    assert "nur Produkte nach SFDR Art. 8 oder 9 mit EU-Klima-Benchmark" in text_
    assert "beides Pflicht" in text_


@pytest.mark.parametrize("policy,fragment", [
    ("best_in_class", "AAA oder AA"),
    ("net_zero", "SFDR Art. 9 allein genuegt nicht"),
])
def test_pdf_label_states_cio_criterion(policy, fragment):
    text_ = _pdf_preferences_text({"policy": {"esg": policy}})
    assert fragment in text_


def test_ui_summary_labels_and_admin_note_state_cio_criteria():
    html = _html()
    assert "AAA–A " not in html and "Score ≥ 60" not in html
    assert "ESG-Rating AAA/AA/A" not in html
    assert "SFDR 9 oder PAB/CTB" not in html
    assert "Net Zero = SFDR Art. 9 oder" not in html


# Geschlossenes Vokabular der ESG-Kriterientexte (Kundendokument). Jedes
# neue Wort muss hier bewusst aufgenommen werden -- so gelangt kein
# unbeabsichtigter Begriff (z.B. ein Anbieter- oder Produktname) in den
# Kriterientext oder das PDF-Label (Branding-Regel, Greenwashing-Schutz).
_ESG_CRITERIA_VOCABULARY = frozenset({
    # Regulierung / Kennzahlen
    "SFDR", "Art", "EU", "PAB", "CTB", "ESG", "Rating", "Score", "Skala",
    "AAA", "AA", "CCC", "Leader", "Klasse", "Klassifikation", "Benchmark",
    "Klima", "Pflicht", "beides",
    # Kunden-Label (CIO-Entscheid 2026-10-18: nur Kriterium, kein Claim-Name)
    "Produktauswahl",
    # Liquiditaets-Ausnahme
    "Liquiditaet", "Konto", "Festgeld", "Geldmarktfonds", "Kriterium",
    "ausgenommen", "die", "gesamte", "Anlageklasse", "und", "unabhaengig",
    "deren",
    # Funktionswoerter
    "Produkte", "nur", "nach", "oder", "mit", "von", "vom", "der", "in",
    "ist", "sind", "nicht", "ohne", "allein", "genuegt", "mindestens",
    "zulaessig",
})
# Policy-Namen duerfen NUR im Berater-Label stehen (nie im Kundendokument).
_ESG_POLICY_NAME_VOCABULARY = frozenset({
    "ESG", "Integration", "Best", "in", "Class", "Impact", "Investing",
    "Paris", "aligned", "Net", "Zero",
})


def _pdf_esg_label(policy: str) -> str:
    lines = _pdf_preferences_text({"policy": {"esg": policy}}).splitlines()
    return lines[lines.index("ESG-Vorgabe") + 1]


@pytest.mark.parametrize("policy", ["esg_integration", "best_in_class", "impact", "net_zero"])
def test_esg_criteria_texts_use_only_whitelisted_vocabulary(policy):
    """Kriterientext und PDF-Label bestehen nur aus dem freigegebenen
    Vokabular; jedes unbekannte Wort ist ein Fehler."""
    import services.portfolio_engine_payload as payload

    customer_texts = [
        ESG_POLICY_CRITERIA[policy],
        payload.esg_policy_customer_label(policy),
        payload.ESG_POLICY_LIQUIDITY_EXEMPTION,
        _pdf_esg_label(policy),
    ]
    for text_ in customer_texts:
        unknown = set(re.findall(r"[A-Za-zÄÖÜäöüß]+", text_)) - _ESG_CRITERIA_VOCABULARY
        assert not unknown, (policy, sorted(unknown), text_)
    advisor_label = payload.esg_policy_criterion_label(policy)
    unknown = set(re.findall(r"[A-Za-zÄÖÜäöüß]+", advisor_label)) - (
        _ESG_CRITERIA_VOCABULARY | _ESG_POLICY_NAME_VOCABULARY
    )
    assert not unknown, (policy, sorted(unknown), advisor_label)
    assert ESG_POLICY_CRITERIA[policy] in _pdf_esg_label(policy)


# ---------------------------------------------------------------------------
# 9. CIO-Entscheid 2026-10-18: Liquiditaets-Ausnahmetext == Code-Bedingung
# ---------------------------------------------------------------------------


_SFDR_POLICIES = ["esg_integration", "best_in_class", "impact", "net_zero"]


def test_liquidity_exemption_text_and_matcher_share_one_asset_class_constant():
    import inspect

    import services.portfolio_engine_payload as payload

    assert payload.ESG_POLICY_EXEMPT_ASSET_CLASS == "Liquiditaet"
    assert f"gesamte Anlageklasse {payload.ESG_POLICY_EXEMPT_ASSET_CLASS}" in payload.ESG_POLICY_LIQUIDITY_EXEMPTION
    source = inspect.getsource(payload._product_matches_constraints)
    assert "asset_class != ESG_POLICY_EXEMPT_ASSET_CLASS" in source
    assert 'asset_class != "Liquiditaet" and not product_meets_esg_policy' not in source


@pytest.mark.parametrize("policy", _SFDR_POLICIES)
@pytest.mark.parametrize("sub_asset_class,product_type,sfdr", [
    ("Geldmarktfonds", "Fonds", "8"),   # Seed-Geldmarktfonds (SFDR Art. 8)
    ("Geldmarktfonds", "Fonds", "6"),
    ("Geldmarktfonds", "Fonds", None),
    ("Kontoguthaben", "Cash", None),
    ("Festgeld", "Cash", None),
])
def test_whole_liquidity_asset_class_is_exempt_as_the_text_states(policy, sub_asset_class, product_type, sfdr):
    """Der Kundentext nennt Konto, Festgeld UND Geldmarktfonds unabhaengig von
    der SFDR-Klasse -- genau das nimmt die Engine aus. Gegenprobe: ein Art.-6-
    Produkt ausserhalb der Liquiditaet erfuellt das Kriterium nicht."""
    from services.portfolio_engine_payload import ESG_POLICY_LIQUIDITY_EXEMPTION

    liquid = _product(asset_class="Liquidität", sub_asset_class=sub_asset_class,
                      product_type=product_type, sfdr_class=sfdr)
    assert _product_matches_constraints(liquid, _prefs(policy={"esg": policy}), 8) is True
    other = _product(asset_class="Obligationen", sub_asset_class="Obligationen CHF",
                     product_type="ETF", sfdr_class="6")
    assert _product_matches_constraints(other, _prefs(policy={"esg": policy}), 8) is False
    named = {"Geldmarktfonds": "Geldmarktfonds", "Kontoguthaben": "Konto", "Festgeld": "Festgeld"}
    assert named[sub_asset_class] in ESG_POLICY_LIQUIDITY_EXEMPTION
    if sfdr:
        assert "unabhaengig von deren SFDR-Klassifikation" in ESG_POLICY_LIQUIDITY_EXEMPTION


def test_every_seed_liquidity_product_kind_is_named_in_exemption_text():
    from services.portfolio_engine_payload import ESG_POLICY_LIQUIDITY_EXEMPTION

    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(bind=engine)
    with SF() as s:
        pe.ensure_default_products(s, jurisdiction="CH")
        s.commit()
        subs = {
            str(p.sub_asset_class) for p in s.query(Product).all()
            if pe._norm_text(p.asset_class) == "Liquiditaet"
        }
    engine.dispose()
    assert subs
    named = {"Geldmarktfonds": "Geldmarktfonds", "Kontoguthaben": "Konto", "Festgeld": "Festgeld"}
    for sub in subs:
        assert sub in named, sub
        assert named[sub] in ESG_POLICY_LIQUIDITY_EXEMPTION


# ---------------------------------------------------------------------------
# 10. CIO-Entscheid 2026-10-18: Kundendokument nennt nur das Kriterium
# ---------------------------------------------------------------------------


def _claim_hits(text_: str) -> list[str]:
    from services.portfolio_engine_payload import ESG_CUSTOMER_CLAIM_LABELS

    lowered = text_.lower()
    return [label for label in ESG_CUSTOMER_CLAIM_LABELS if label.lower() in lowered]


def test_claim_label_guard_covers_every_policy_name():
    """Jeder Berater-Policy-Name ist als Claim gesperrt -- ein neuer Name
    ohne Waechter-Eintrag faellt hier auf."""
    from services.portfolio_engine_payload import ESG_POLICY_NAMES

    for name in ESG_POLICY_NAMES.values():
        assert _claim_hits(name), name


@pytest.mark.parametrize("policy", ["none", "negative_screening", *_SFDR_POLICIES])
def test_customer_documents_contain_no_esg_claim_labels(policy):
    """Anlagestrategie-PDF (Praeferenzabschnitt, inkl. Themen-Zeilen und
    dokumentierter Abweichung) enthaelt keinen Claim-Namen."""
    text_ = _pdf_preferences_text(_prefs(
        policy={"esg": policy},
        tilts={"fossil": "exclude", "tobacco": "allow", "alcohol": "underweight"},
        tiltReasons={"tobacco": GOOD_REASON},
    ))
    assert "ESG-Vorgabe" in text_
    assert not _claim_hits(text_), (policy, _claim_hits(text_), text_)


@pytest.mark.parametrize("policy", _SFDR_POLICIES)
def test_customer_label_states_only_the_checked_criterion(policy):
    from services.portfolio_engine_payload import (
        ESG_POLICY_LIQUIDITY_EXEMPTION,
        ESG_POLICY_NAMES,
        esg_policy_criterion_label,
        esg_policy_customer_label,
    )

    customer = esg_policy_customer_label(policy)
    assert customer == f"Kriterium der Produktauswahl: {ESG_POLICY_CRITERIA[policy]}"
    assert ESG_POLICY_NAMES[policy] not in customer
    for text_ in (customer, ESG_POLICY_CRITERIA[policy], ESG_POLICY_LIQUIDITY_EXEMPTION):
        assert not _claim_hits(text_), (policy, text_)
    assert _pdf_esg_label(policy) == f"{customer}; {ESG_POLICY_LIQUIDITY_EXEMPTION}"
    # Berater-UI/-Hinweise duerfen Name + Kriterium zeigen.
    assert esg_policy_criterion_label(policy) == f"{ESG_POLICY_NAMES[policy]} ({ESG_POLICY_CRITERIA[policy]})"


def test_customer_label_is_none_without_sfdr_policy():
    from services.portfolio_engine_payload import esg_policy_customer_label

    for policy in ("none", "negative_screening", None, "unknown"):
        assert esg_policy_customer_label(policy) is None
