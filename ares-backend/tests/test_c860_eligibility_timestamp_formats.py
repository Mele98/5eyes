"""Codex C-860-01: Gueltigkeitsfenster der governed Eignung als echte UTC-Zeitpunkte.

Befund: services.portfolio_engine._now() schreibt die Bootstrap-Zeitpunkte des
Default-Katalogs als Millisekunden mit ``Z`` (``...SS.000Z``),
services.product_eligibility._now_iso() erzeugt den Vergleichsstichtag mit
``+00:00`` (``...SS+00:00``), und der Resolver verglich beide als Text
(``valid_from <= as_of``). Innerhalb derselben Sekunde sortiert ``+`` vor
``.`` -- eine eben geseedete Regel galt als noch nicht gueltig, der
unmittelbar folgende Empfehlungslauf fand kein einziges geeignetes Produkt
("Produktselektion unvollstaendig ... Gesamt-Luecke: 100.0%").

Fix: verglichen wird geparst (parse_utc_timestamp / instant_within_validity);
die gespeicherten Werte bleiben unveraendert, damit auch jeder Hash, in den
sie einfliessen (rule_hash ueber valid_from/valid_to, override evidence_hash
ueber valid_from/expires_at), unveraendert reproduzierbar bleibt.

Gegenprobe: mit dem frueheren Textvergleich im Resolver ist
``test_seed_then_generate_in_the_same_frozen_second`` rot (ValueError
Produktselektion unvollstaendig), ebenso die Format-Matrix-Faelle.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import time_machine
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.mandates import Mandate
from models.product_eligibility import ProductEligibilityRule, ProductEligibilityRuleSet
from models.review import Product
from services import product_eligibility as pe
from services.product_eligibility import (
    DEFAULT_CATALOG_BOOTSTRAP_IDENTITY,
    canonical_hash,
    resolve_active_rules_for_product,
)
from services.product_eligibility_governance import (
    RULE_POLICY_FIELDS,
    compute_rule_hash,
    instant_within_validity,
    parse_utc_timestamp,
)

FROZEN = datetime(2027, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'c860.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ---------------------------------------------------------------------------
# Parser und Fenster
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "2027-01-15T10:00:00.000Z",
    "2027-01-15T10:00:00Z",
    "2027-01-15T10:00:00+00:00",
    "2027-01-15T10:00:00.000000+00:00",
    "2027-01-15T11:00:00+01:00",
    "2027-01-15T10:00:00",
    "2027-01-15 10:00:00",
])
def test_both_stored_formats_parse_to_the_same_instant(text):
    assert parse_utc_timestamp(text) == FROZEN


@pytest.mark.parametrize("text", [None, "", "   ", "None", "kein Datum", "2027-13-01"])
def test_unreadable_values_parse_to_none(text):
    assert parse_utc_timestamp(text) is None


@pytest.mark.parametrize(("valid_from", "valid_to", "as_of", "expected"), [
    # Der Befund: Regel in derselben Sekunde mit "Z" geschrieben, Stichtag mit
    # "+00:00" -- als Text "noch nicht gueltig", tatsaechlich gleichzeitig.
    ("2027-01-15T10:00:00.000Z", None, "2027-01-15T10:00:00+00:00", True),
    ("2027-01-15T10:00:00+00:00", None, "2027-01-15T10:00:00.000Z", True),
    # Millisekunde spaeter geschrieben als der Stichtag: noch nicht gueltig,
    # obwohl "Z" > "4" als Text gueltig waere.
    ("2027-01-15T10:00:00.500Z", None, "2027-01-15T10:00:00.400000+00:00", False),
    ("2027-01-15T10:00:00.400Z", None, "2027-01-15T10:00:00.400000+00:00", True),
    # valid_to exklusiv und formatunabhaengig.
    ("2027-01-01T00:00:00Z", "2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00+00:00", False),
    ("2027-01-01T00:00:00Z", "2027-01-15T10:00:00.001Z", "2027-01-15T10:00:00+00:00", True),
    ("2027-01-01T00:00:00Z", "2027-01-15T10:00:00+00:00", "2027-01-15T09:59:59.999Z", True),
    # Zeitzonen: 11:00+01:00 ist 10:00Z.
    ("2027-01-15T11:00:00+01:00", None, "2027-01-15T10:00:00Z", True),
    ("2027-01-15T11:00:01+01:00", None, "2027-01-15T10:00:00Z", False),
    # fail-closed bei nicht lesbaren Werten.
    ("kaputt", None, "2027-01-15T10:00:00Z", False),
    ("2027-01-01T00:00:00Z", "", "2027-01-15T10:00:00Z", False),
    ("2027-01-01T00:00:00Z", "kaputt", "2027-01-15T10:00:00Z", False),
    ("2027-01-01T00:00:00Z", None, "kaputt", False),
])
def test_validity_window_compares_instants_not_text(valid_from, valid_to, as_of, expected):
    assert instant_within_validity(valid_from, valid_to, as_of) is expected


# ---------------------------------------------------------------------------
# Resolver mit gemischten gespeicherten Formaten
# ---------------------------------------------------------------------------


def _seed_rule(db, *, rule_valid_from, set_valid_from, rule_valid_to=None, set_valid_to=None):
    product = Product(
        id="c860-product", product_name="C860 Fonds", provider="Test",
        product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Schweiz",
        currency="CHF", is_active=1, created_at="2027-01-01T00:00:00Z",
        updated_at="2027-01-01T00:00:00Z",
    )
    rule_set = ProductEligibilityRuleSet(
        id="c860-set", tenant_scope="global", tenant_id=None, jurisdiction="CH",
        version=1, status="approved", valid_from=set_valid_from, valid_to=set_valid_to,
        created_by="c860", approved_by="c860", approved_at=set_valid_from,
        rule_set_hash="x", created_at=set_valid_from, updated_at=set_valid_from,
    )
    rule = ProductEligibilityRule(
        id="c860-rule", rule_set_id="c860-set", version=1, product_id="c860-product",
        tenant_scope="global", tenant_id=None, jurisdiction="CH",
        client_classifications_json="[]", service_modes_json="[]",
        profile_from=1, profile_to=10, requires_knowledge_categories_json="[]",
        valid_from=rule_valid_from, valid_to=rule_valid_to, status="approved",
        created_by="c860", approved_by="c860", approved_at=rule_valid_from,
        rule_hash="x", created_at=rule_valid_from, updated_at=rule_valid_from,
    )
    db.add_all([product, rule_set, rule])
    db.flush()
    return product


@pytest.mark.parametrize(("rule_from", "set_from", "as_of", "expected"), [
    ("2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00+00:00", 1),
    ("2027-01-15T10:00:00+00:00", "2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00+00:00", 1),
    ("2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00+00:00", "2027-01-15T10:00:00.000Z", 1),
    ("2027-01-15T10:00:00.001Z", "2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00+00:00", 0),
    ("2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00.001Z", "2027-01-15T10:00:00+00:00", 0),
])
def test_resolver_accepts_both_stored_formats(session_factory, rule_from, set_from, as_of, expected):
    with session_factory() as db:
        product = _seed_rule(db, rule_valid_from=rule_from, set_valid_from=set_from)
        rules = resolve_active_rules_for_product(
            db, product, jurisdiction="CH", tenant_id=None, as_of=as_of,
        )
        assert len(rules) == expected


@pytest.mark.parametrize(("rule_to", "set_to", "expected"), [
    ("2027-01-15T10:00:00.000Z", None, 0),
    (None, "2027-01-15T10:00:00.000Z", 0),
    ("2027-01-15T10:00:00.001Z", "2027-01-15T10:00:00.001Z", 1),
])
def test_resolver_valid_to_is_exclusive_across_formats(session_factory, rule_to, set_to, expected):
    with session_factory() as db:
        product = _seed_rule(
            db, rule_valid_from="2027-01-01T00:00:00Z", set_valid_from="2027-01-01T00:00:00+00:00",
            rule_valid_to=rule_to, set_valid_to=set_to,
        )
        rules = resolve_active_rules_for_product(
            db, product, jurisdiction="CH", tenant_id=None, as_of="2027-01-15T10:00:00+00:00",
        )
        assert len(rules) == expected


# ---------------------------------------------------------------------------
# Seed + Generate in exakt derselben, eingefrorenen Sekunde
# ---------------------------------------------------------------------------


def test_seed_then_generate_in_the_same_frozen_second(session_factory):
    from services.portfolio_engine import generate_recommendation_run, generate_target_allocation
    from tests.test_golden_snapshot_ch_regression import _seed_ch_mandate

    with time_machine.travel(FROZEN, tick=False):
        advisor_id, _cid, mid, _aid = _seed_ch_mandate(
            session_factory, suffix="c860", score_x10=50,
        )
        with session_factory() as s:
            mandate = s.query(Mandate).filter(Mandate.id == mid).first()
            allocation = generate_target_allocation(s, mandate, advisor_id, preferences=None)["target_allocation"]
            allocation_id = allocation.id
            s.commit()
        with session_factory() as s:
            mandate = s.query(Mandate).filter(Mandate.id == mid).first()
            run = generate_recommendation_run(
                s, mandate, advisor_id, preferences=None, target_allocation_id=allocation_id,
            )
            # Beleg, dass der Test den Befund wirklich trifft: Katalog-Regeln
            # in derselben Sekunde mit "Z" geschrieben, Stichtag mit "+00:00".
            rules = s.query(ProductEligibilityRule).all()
            stichtag = pe._now_iso()

    assert rules, "der Lauf muss den Default-Katalog samt Regeln geseedet haben"
    assert {rule.valid_from for rule in rules} == {"2027-01-15T10:00:00.000Z"}
    assert stichtag == "2027-01-15T10:00:00+00:00"
    assert stichtag < "2027-01-15T10:00:00.000Z", "als Text waere die Regel noch nicht gueltig"
    positions = run["positions"]
    assert positions, "frisch geseedeter Katalog muss sofort geeignet sein"
    assert sum(int(p["target_weight_bps"]) for p in positions) == 10000


# ---------------------------------------------------------------------------
# Hash-Reproduzierbarkeit: gespeicherte Werte und Hashes unveraendert
# ---------------------------------------------------------------------------

# Known-Answer: am Basis-SHA a947e89c (vor dem Fix) berechnet. Der Fix aendert
# weder compute_rule_hash/canonical_hash noch die geschriebenen Zeitstempel.
_KAT_RULE_VALUES = {
    "rule_set_id": "c860-set", "version": 1, "product_id": "c860-product",
    "product_category_selector": None, "tenant_scope": "global", "tenant_id": None,
    "jurisdiction": "CH", "client_classifications_json": "[]",
    "service_modes_json": '["advisory", "discretionary"]', "profile_from": 3,
    "profile_to": 7, "requires_knowledge_categories_json": "[]",
    "minimum_experience_level": None, "requires_appropriateness": 0,
    "requires_suitability": 0, "requires_override": 0, "max_position_bps": 2500,
    "prohibited": 0, "valid_from": "2027-01-15T10:00:00.000Z", "valid_to": None,
    "supersedes_id": None,
}
_KAT_RULE_HASH = "9c6c79c0cb9c3fd219fff6a182336a3ceb6fd66e690e6fc72fe4182c625dce8e"


def test_rule_hash_known_answer_is_unchanged():
    assert compute_rule_hash(_KAT_RULE_VALUES, source=DEFAULT_CATALOG_BOOTSTRAP_IDENTITY) == _KAT_RULE_HASH


def test_valid_from_is_bound_verbatim_into_the_rule_hash():
    """Belegt, warum die Schreibweise NICHT kanonisiert wurde: valid_from geht
    textgenau in rule_hash ein -- eine Umstellung haette jeden gespeicherten
    Hash unreproduzierbar gemacht."""
    other = dict(_KAT_RULE_VALUES, valid_from="2027-01-15T10:00:00+00:00")
    assert compute_rule_hash(other, source=DEFAULT_CATALOG_BOOTSTRAP_IDENTITY) != _KAT_RULE_HASH


def test_seeded_rule_hashes_recompute_from_stored_values(session_factory):
    from services.portfolio_engine import ensure_default_products

    with time_machine.travel(FROZEN, tick=False):
        with session_factory() as db:
            ensure_default_products(db)
            db.flush()
            rules = db.query(ProductEligibilityRule).all()
            rule_sets = db.query(ProductEligibilityRuleSet).all()
            assert rules and rule_sets
            for rule in rules:
                values = {field: getattr(rule, field) for field in RULE_POLICY_FIELDS}
                assert compute_rule_hash(values, source=DEFAULT_CATALOG_BOOTSTRAP_IDENTITY) == rule.rule_hash
                assert rule.valid_from == "2027-01-15T10:00:00.000Z"
            for rule_set in rule_sets:
                assert rule_set.rule_set_hash == canonical_hash({
                    "source": rule_set.created_by,
                    "tenant_scope": rule_set.tenant_scope,
                    "tenant_id": rule_set.tenant_id,
                    "jurisdiction": rule_set.jurisdiction,
                })


# ---------------------------------------------------------------------------
# Override-Gueltigkeit: dieselbe Vergleichsregel
# ---------------------------------------------------------------------------


def _override_row(valid_from, expires_at):
    return SimpleNamespace(
        requested_by="a", approved_by="b", approval_mode=None, rule_id="r",
        valid_from=valid_from, expires_at=expires_at, evidence_hash=None,
    )


@pytest.mark.parametrize(("valid_from", "expires_at", "now", "expected"), [
    ("2027-01-15T10:00:00.000Z", "2027-02-15T10:00:00.000Z", "2027-01-15T10:00:00+00:00", True),
    ("2027-01-15T10:00:00+00:00", "2027-02-15T10:00:00+00:00", "2027-01-15T10:00:00.000Z", True),
    ("2027-01-15T10:00:00+00:00", "2027-01-15T10:00:00+00:00", "2027-01-15T10:00:00+00:00", False),
    ("2026-12-15T10:00:00+00:00", "2027-01-15T10:00:00.000Z", "2027-01-15T10:00:00+00:00", False),
    ("2027-01-15T10:00:00+00:00", None, "2027-01-15T10:00:00+00:00", False),
])
def test_override_window_compares_instants(monkeypatch, valid_from, expires_at, now, expected):
    from services import product_eligibility_override as override

    row = _override_row(valid_from, expires_at)
    monkeypatch.setattr(override, "override_evidence_hash", lambda r, b: None)
    assert override.is_valid_override(row, binding_hash="h", matched_rule_id="r", now=now) is expected


def test_override_evidence_hash_binds_stored_strings_unchanged():
    from services.product_eligibility_override import override_evidence_hash

    row = SimpleNamespace(
        id="o", recommendation_run_id="run", product_id="p", rule_id="r",
        original_decision="indeterminate", overridden_dimension="override",
        reason_code="X", reason_text="t", policy_basis="b", requested_by="a",
        approved_by="b", valid_from="2027-01-15T10:00:00+00:00",
        expires_at="2027-02-14T10:00:00+00:00", approval_mode=None,
    )
    expected = canonical_hash({
        "id": "o", "decision_binding_hash": "bind", "recommendation_run_id": "run",
        "product_id": "p", "rule_id": "r", "original_decision": "indeterminate",
        "overridden_dimension": "override", "reason_code": "X", "reason_text": "t",
        "policy_basis": "b", "requested_by": "a", "approved_by": "b",
        "valid_from": "2027-01-15T10:00:00+00:00", "expires_at": "2027-02-14T10:00:00+00:00",
    })
    assert override_evidence_hash(row, "bind") == expected
