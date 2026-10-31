"""K-1 (A2 M4): Byte-Gleichheit der Bestands-Kanonisierungen mit core.evidence.

Jede im Backend vorkommende Kanonisierung fuer Evidence-/Integritaets-Hashes
ist hier inventarisiert und einem benannten Schema aus ``core.evidence``
zugeordnet -- oder ausdruecklich als abweichend ("bespoke") gefuehrt.

Drei Nachweise:

1. Laufzeit: fuer jede aufrufbare Bestands-Variante wird die Ausgabe der
   heutigen Produktionsfunktion mit ``core.evidence`` auf einem breiten
   Eingabe-Set verglichen (Unicode/Umlaute/Emoji/Steuerzeichen, Floats inkl.
   -0.0/NaN/Inf/Subnormal, grosse Ints, None, Bool, leere und tief
   verschachtelte Strukturen, Datums-Strings, Tupel, Decimal/datetime) plus
   ein deterministischer Zufallskorpus. Gleich muessen Bytes UND
   Ausnahmetyp sein.
2. Quelltext: fuer jede inventarisierte Aufrufstelle (auch funktionsinterne,
   nicht separat aufrufbare) werden die ``json.dumps``-Argumente per AST
   gelesen und mit dem Schema verglichen. Identische Argumente an
   ``json.dumps`` erzeugen identische Bytes; der Test pinnt zugleich, dass
   keine Stelle still ihre Kanonisierung aendert.
3. Optional ``hypothesis`` (nicht in den Requirements; wird nur genutzt,
   wenn installiert).
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import math
import random
from decimal import Decimal
from pathlib import Path

import pytest

from core import evidence
from core.evidence import (
    SCHEME_LEGACY_SPACED,
    SCHEME_LEGACY_SPACED_STR_DEFAULT,
    SCHEME_LEGACY_UNSORTED_UTF8,
    SCHEME_V1,
    SCHEME_V1_ASCII,
    SCHEME_V1_ASCII_STR_DEFAULT,
    SCHEME_V1_STR_DEFAULT,
    canonical_json,
    evidence_hash,
    scheme_dumps_kwargs,
)

BACKEND = Path(__file__).resolve().parents[1]

_STR_DEFAULT_SCHEMES = {
    SCHEME_V1_STR_DEFAULT,
    SCHEME_V1_ASCII_STR_DEFAULT,
    SCHEME_LEGACY_SPACED_STR_DEFAULT,
}


# ---------------------------------------------------------------------------
# Eingabe-Korpus
# ---------------------------------------------------------------------------

_STRINGS = [
    "", " ", "a", "Zürich", "Genève", "Graubünden", "Straße", "ÄÖÜäöüéèàç",
    "CHF 1'250'000.50", "💶 Vermögen", "日本語", "  ", "\x00\x1f\x7f",
    "tab\tnew\nline\rret", 'quote " backslash \\ slash /', "</script>",
    "2026-10-31", "2026-10-31T12:34:56.789Z", "2026-10-31T12:34:56+02:00",
    "퟿￿", "NaN", "null", "0", "-0", "1e309",
]

_FLOATS = [
    0.0, -0.0, 1.0, -1.5, 0.1, 0.1 + 0.2, 1 / 3, 2.5e-308, 5e-324, 1.7976931348623157e308,
    1e16, 1e-7, 123456789.123456789, 0.5, 100.0, float("nan"), float("inf"), float("-inf"),
]

_INTS = [0, 1, -1, 2**31, -(2**53) - 1, 2**70, 10**30]

_EDGE_PAYLOADS = [
    None, True, False, {}, [], "", 0, 0.0,
    {"": None}, {"a": {}}, {"a": []}, [[]], [{}], [[[[[]]]]],
    {"z": 1, "a": 2, "Ä": 3, "a ": 4, "A": 5, "10": 6, "9": 7, "ä": 8, "é": 9},
    {"nested": {"deep": {"deeper": {"deepest": ["Zürich", 1.5, None, True]}}}},
    (1, 2, (3, "vier")),
    {"tuple": ("x", 1.25, None), "list": [None, False, -0.0]},
    {"dates": ["2026-01-01", "2026-12-31T23:59:59.999Z"]},
    {"amount_rappen": 125000050, "weight_bps": 10000, "ratio": 0.6667},
    {k: v for k, v in zip(_STRINGS, _FLOATS + _INTS)},
    list(_STRINGS), list(_FLOATS), list(_INTS),
    {"mixed": [1, "1", 1.0, True, None, [], {}]},
]

# Werte, die json ohne ``default`` nicht serialisieren kann.
_NON_JSON_PAYLOADS = [
    {"amount": Decimal("1250000.50")},
    {"exact": Decimal("0.1"), "neg": Decimal("-0"), "big": Decimal("1E+30")},
    {"at": dt.date(2026, 10, 31)},
    {"ts": dt.datetime(2026, 10, 31, 12, 0, 0, 123000, tzinfo=dt.timezone.utc)},
    {"nested": [{"d": Decimal("3.14159")}, {"t": dt.time(8, 30)}]},
    {"set_like": frozenset({1})},
    [Decimal("1"), dt.date(2000, 1, 1)],
]


def _random_scalar(rng: random.Random, *, allow_non_json: bool):
    kind = rng.randrange(9 if allow_non_json else 7)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.choice(_INTS + [rng.randint(-(10**12), 10**12)])
    if kind == 3:
        return rng.choice(_FLOATS + [rng.uniform(-1e6, 1e6), rng.random()])
    if kind in (4, 5):
        base = rng.choice(_STRINGS)
        extra = "".join(chr(rng.choice([rng.randint(32, 126), rng.randint(0xA0, 0x24F),
                                         rng.randint(0x1F300, 0x1F64F)]))
                        for _ in range(rng.randint(0, 6)))
        return base + extra
    if kind == 6:
        return f"{rng.randint(1900, 2100):04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    if kind == 7:
        return Decimal(f"{rng.randint(-10**8, 10**8)}.{rng.randint(0, 99):02d}")
    return dt.date(rng.randint(1950, 2080), rng.randint(1, 12), rng.randint(1, 28))


def _random_payload(rng: random.Random, depth: int = 0, *, allow_non_json: bool = False):
    roll = rng.random()
    if depth >= 4 or roll < 0.35:
        return _random_scalar(rng, allow_non_json=allow_non_json)
    if roll < 0.7:
        return {
            str(_random_scalar(rng, allow_non_json=False)): _random_payload(
                rng, depth + 1, allow_non_json=allow_non_json
            )
            for _ in range(rng.randint(0, 6))
        }
    seq = [_random_payload(rng, depth + 1, allow_non_json=allow_non_json)
           for _ in range(rng.randint(0, 6))]
    return tuple(seq) if rng.random() < 0.2 else seq


def _corpus(seed: int, n: int, *, allow_non_json: bool = False) -> list:
    rng = random.Random(seed)
    return [_random_payload(rng, allow_non_json=allow_non_json) for _ in range(n)]


JSON_CORPUS = _EDGE_PAYLOADS + _corpus(20261031, 1500)
MIXED_CORPUS = _NON_JSON_PAYLOADS + _corpus(4711, 400, allow_non_json=True)


def _outcome(fn, payload):
    """(\"ok\", Ergebnis) oder (\"err\", Ausnahmetyp) -- beides muss gleich sein."""
    try:
        return ("ok", fn(payload))
    except (TypeError, ValueError) as exc:
        return ("err", type(exc))


def _same(a, b) -> bool:
    if a[0] != b[0]:
        return False
    if a[0] == "err":
        return a[1] is b[1]
    return a[1] == b[1]


# ---------------------------------------------------------------------------
# 1. Laufzeit-Vergleich je aufrufbarer Bestands-Variante
# ---------------------------------------------------------------------------


def _dict_only(payload):
    return payload if isinstance(payload, dict) else {"value": payload}


def _variants():
    """(Name, alte Implementierung, neue Implementierung, nur-Dict-Eingabe)."""
    from services import (
        allocation_evidence_replay,
        backtest_stress,
        cost_disclosure,
        depot_snapshot,
        financial_coverage_attestation,
        goal_analysis_snapshot,
        goal_revision_decision,
        pension_transfer_ledger_snapshot,
        portfolio_data_policy,
        portfolio_handoff,
        portfolio_reconciliation,
        preference_snapshot,
        privacy_erasure,
        product_eligibility,
        reserve_funding_ledger,
        reserve_funding_ledger_snapshot,
        risk_capacity_evaluation_snapshot,
        risk_override_decision,
        risk_profile_signoff,
    )
    from services.currency import fx_rates
    from services.onsite_signature import service as onsite_service

    def canon(scheme):
        return lambda p: canonical_json(p, scheme=scheme)

    def digest(scheme):
        return lambda p: evidence_hash(p, scheme=scheme)

    def without_contract_hash(scheme):
        return lambda p: evidence_hash(
            {k: v for k, v in p.items() if k != "contract_hash"}, scheme=scheme
        )

    def shadow_new(p):
        return canonical_json(p, scheme=SCHEME_V1) if p else None

    def shadow_old(p):
        out = goal_analysis_snapshot.serialize_shadow_optimization(p)
        if out is None and p:
            # Bestand faengt TypeError/ValueError ab und liefert None.
            raise TypeError("serialize_shadow_optimization -> None")
        return out

    def handoff_snapshot_new(p):
        text = canonical_json(p, scheme=SCHEME_LEGACY_UNSORTED_UTF8)
        return text, evidence.sha256_hex(text)

    return [
        # SCHEME_V1
        ("risk_profile_signoff._sha256", risk_profile_signoff._sha256, digest(SCHEME_V1), False),
        ("goal_revision_decision._sha256", goal_revision_decision._sha256, digest(SCHEME_V1), False),
        ("risk_override_decision.compute_decision_hash",
         lambda p: risk_override_decision.compute_decision_hash(
             {n: p for n in risk_override_decision.HASHED_FIELDS}),
         lambda p: evidence_hash({n: p for n in risk_override_decision.HASHED_FIELDS}),
         False),
        ("financial_coverage_attestation._canonical",
         financial_coverage_attestation._canonical, canon(SCHEME_V1), False),
        ("risk_capacity_evaluation_snapshot._canonical",
         risk_capacity_evaluation_snapshot._canonical, canon(SCHEME_V1), False),
        ("reserve_funding_ledger_snapshot._canonical",
         reserve_funding_ledger_snapshot._canonical, canon(SCHEME_V1), False),
        ("allocation_evidence_replay._canonical_json",
         allocation_evidence_replay._canonical_json, canon(SCHEME_V1), False),
        ("onsite_signature.service._canonical", onsite_service._canonical, canon(SCHEME_V1), True),
        ("goal_analysis_snapshot.serialize_shadow_optimization", shadow_old, shadow_new, False),
        # SCHEME_V1_ASCII
        ("depot_snapshot._canonical", depot_snapshot._canonical, canon(SCHEME_V1_ASCII), False),
        ("depot_snapshot._sha256", depot_snapshot._sha256, digest(SCHEME_V1_ASCII), False),
        ("pension_transfer_ledger_snapshot._canonical",
         pension_transfer_ledger_snapshot._canonical, canon(SCHEME_V1_ASCII), False),
        ("pension_transfer_ledger_snapshot._sha256",
         pension_transfer_ledger_snapshot._sha256, digest(SCHEME_V1_ASCII), False),
        ("portfolio_reconciliation._canonical",
         portfolio_reconciliation._canonical, canon(SCHEME_V1_ASCII), False),
        ("portfolio_reconciliation._sha256",
         portfolio_reconciliation._sha256, digest(SCHEME_V1_ASCII), False),
        ("portfolio_data_policy._canonical",
         portfolio_data_policy._canonical, canon(SCHEME_V1_ASCII), False),
        ("privacy_erasure._canonical", privacy_erasure._canonical, canon(SCHEME_V1_ASCII), False),
        ("reserve_funding_ledger._hash_payload",
         reserve_funding_ledger._hash_payload, without_contract_hash(SCHEME_V1_ASCII), True),
        # SCHEME_V1_STR_DEFAULT
        ("portfolio_handoff.handoff_business_key_hash",
         lambda p: portfolio_handoff.handoff_business_key_hash(
             mandate_id="M-1", run_id="R-1", trades=[p], total_value_rappen=125000050,
             recipient_name="  Bank  Zürich "),
         lambda p: evidence_hash({
             "schema": "PortfolioHandoffBusinessKeyV1", "mandate_id": "M-1",
             "recommendation_run_id": "R-1", "live_total_value_rappen": 125000050,
             "recipient": "bank zürich", "trades": [p]}, scheme=SCHEME_V1_STR_DEFAULT),
         False),
        # SCHEME_V1_ASCII_STR_DEFAULT
        ("currency.fx_rates._fingerprint", fx_rates._fingerprint,
         digest(SCHEME_V1_ASCII_STR_DEFAULT), False),
        # SCHEME_LEGACY_SPACED_STR_DEFAULT
        ("cost_disclosure.cost_disclosure_content_hash",
         cost_disclosure.cost_disclosure_content_hash,
         digest(SCHEME_LEGACY_SPACED_STR_DEFAULT), True),
        ("product_eligibility.canonical_hash", product_eligibility.canonical_hash,
         digest(SCHEME_LEGACY_SPACED_STR_DEFAULT), False),
        ("preference_snapshot._canonical", preference_snapshot._canonical,
         canon(SCHEME_LEGACY_SPACED_STR_DEFAULT), False),
        # SCHEME_LEGACY_UNSORTED_UTF8
        ("portfolio_handoff.snapshot_json_and_sha256",
         portfolio_handoff.snapshot_json_and_sha256, handoff_snapshot_new, False),
        # Konstante: der Stress-Katalog
        ("backtest_stress.stress_catalog_hash",
         lambda _p: backtest_stress.stress_catalog_hash(),
         lambda _p: evidence_hash(backtest_stress._SCENARIOS, scheme=SCHEME_V1_ASCII),
         False),
    ]


_VARIANTS = _variants()


@pytest.mark.parametrize(
    "name,old,new,dict_only", _VARIANTS, ids=[v[0] for v in _VARIANTS]
)
def test_runtime_variant_is_byte_identical_to_core_evidence(name, old, new, dict_only):
    checked = 0
    for corpus in (JSON_CORPUS, MIXED_CORPUS):
        for payload in corpus:
            if dict_only:
                payload = _dict_only(payload)
            a, b = _outcome(old, payload), _outcome(new, payload)
            assert _same(a, b), f"{name}: Abweichung fuer {payload!r}: alt={a!r} neu={b!r}"
            checked += 1
    assert checked > 1800


# ---------------------------------------------------------------------------
# Eigenschaften der Schemata selbst
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", evidence.SCHEMES)
def test_scheme_equals_literal_json_dumps(scheme):
    """Schema == die frozen json.dumps-Argumente (Bytes), auch fuer Non-JSON."""
    kwargs = scheme_dumps_kwargs(scheme)
    for payload in JSON_CORPUS + MIXED_CORPUS:
        a = _outcome(lambda p: json.dumps(p, **kwargs), payload)
        b = _outcome(lambda p: canonical_json(p, scheme=scheme), payload)
        assert _same(a, b)


def test_scheme_kwargs_are_frozen():
    """Die Bytes der Schemata sind ein Vertrag: Argumente nie umdefinieren."""
    compact = (",", ":")
    assert {s: scheme_dumps_kwargs(s) for s in evidence.SCHEMES} == {
        SCHEME_V1: {"sort_keys": True, "separators": compact, "ensure_ascii": False},
        SCHEME_V1_ASCII: {"sort_keys": True, "separators": compact, "ensure_ascii": True},
        SCHEME_V1_STR_DEFAULT: {"sort_keys": True, "separators": compact,
                                "ensure_ascii": False, "default": str},
        SCHEME_V1_ASCII_STR_DEFAULT: {"sort_keys": True, "separators": compact,
                                      "ensure_ascii": True, "default": str},
        SCHEME_LEGACY_SPACED: {"sort_keys": True, "ensure_ascii": True},
        SCHEME_LEGACY_SPACED_STR_DEFAULT: {"sort_keys": True, "ensure_ascii": True,
                                           "default": str},
        SCHEME_LEGACY_UNSORTED_UTF8: {"sort_keys": False, "ensure_ascii": False},
    }


def test_known_answers():
    payload = {"b": [1, 2.5, None], "a": "Zürich 💶", "c": {"y": True, "x": -0.0}}
    assert canonical_json(payload) == '{"a":"Zürich 💶","b":[1,2.5,null],"c":{"x":-0.0,"y":true}}'
    assert canonical_json(payload, scheme=SCHEME_V1_ASCII) == (
        '{"a":"Z\\u00fcrich \\ud83d\\udcb6","b":[1,2.5,null],"c":{"x":-0.0,"y":true}}'
    )
    assert canonical_json(payload, scheme=SCHEME_LEGACY_SPACED) == (
        '{"a": "Z\\u00fcrich \\ud83d\\udcb6", "b": [1, 2.5, null], "c": {"x": -0.0, "y": true}}'
    )
    assert evidence_hash({}) == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    assert evidence_hash(payload) == evidence.sha256_hex(canonical_json(payload))


def test_non_json_values_raise_without_str_default_and_stringify_with_it():
    for scheme in evidence.SCHEMES:
        if scheme in _STR_DEFAULT_SCHEMES:
            assert canonical_json({"d": Decimal("1.10")}, scheme=scheme).replace(" ", "") == '{"d":"1.10"}'
        else:
            with pytest.raises(TypeError):
                canonical_json({"d": Decimal("1.10")}, scheme=scheme)


def test_nan_is_kept_as_in_the_legacy_serialisation():
    assert canonical_json([math.nan, math.inf, -math.inf]) == "[NaN,Infinity,-Infinity]"


def test_unknown_scheme_is_rejected():
    with pytest.raises(ValueError):
        canonical_json({}, scheme="v2")


# ---------------------------------------------------------------------------
# 2. Quelltext-Inventar: jede Evidence-Stelle -> Schema (oder bespoke)
# ---------------------------------------------------------------------------

# (Datei, Funktions-Qualname, Anzahl json.dumps-Aufrufe darin) -> Schema
INVENTORY: dict[tuple[str, str], tuple[str, int]] = {
    # SCHEME_V1 -- sortiert, kompakt, UTF-8
    ("services/allocation_evidence_replay.py", "_canonical_json"): (SCHEME_V1, 1),
    ("services/cma_policy.py", "compute_content_hash"): (SCHEME_V1, 1),
    ("services/financial_coverage_attestation.py", "_canonical"): (SCHEME_V1, 1),
    ("services/goal_analysis_snapshot.py", "serialize_shadow_optimization"): (SCHEME_V1, 1),
    ("services/goal_revision_decision.py", "_sha256"): (SCHEME_V1, 1),
    ("services/goal_revision_decision.py", "record_goal_revision_decision"): (SCHEME_V1, 1),
    ("services/onsite_signature/service.py", "_canonical"): (SCHEME_V1, 1),
    ("services/portfolio_engine.py", "evaluate_goal_sensitivity._model_input_hash"): (SCHEME_V1, 1),
    ("services/reserve_funding_ledger_snapshot.py", "_canonical"): (SCHEME_V1, 1),
    ("services/risk_capacity_evaluation_snapshot.py", "_canonical"): (SCHEME_V1, 1),
    ("services/risk_override_decision.py", "compute_decision_hash"): (SCHEME_V1, 1),
    ("services/risk_profile_signoff.py", "_sha256"): (SCHEME_V1, 1),
    # SCHEME_V1_ASCII -- sortiert, kompakt, ASCII
    ("services/backtest_stress.py", "stress_catalog_hash"): (SCHEME_V1_ASCII, 1),
    ("services/depot_snapshot.py", "_canonical"): (SCHEME_V1_ASCII, 1),
    ("services/market_data/cache.py", "_hash_args"): (SCHEME_V1_ASCII, 1),
    ("services/optimizer/solver.py", "goal_economic_fingerprint"): (SCHEME_V1_ASCII, 1),
    ("services/pension_transfer_ledger_snapshot.py", "_canonical"): (SCHEME_V1_ASCII, 1),
    ("services/portfolio_data_policy.py", "_canonical"): (SCHEME_V1_ASCII, 1),
    ("services/portfolio_engine_cma.py", "_sub_asset_class_code_default_evidence"): (SCHEME_V1_ASCII, 1),
    ("services/portfolio_engine_gesamtvermoegen.py", "total_wealth_projection_basis"): (SCHEME_V1_ASCII, 1),
    ("services/portfolio_reconciliation.py", "_canonical"): (SCHEME_V1_ASCII, 1),
    ("services/privacy_erasure.py", "_canonical"): (SCHEME_V1_ASCII, 1),
    ("services/reserve_funding_ledger.py", "_hash_payload"): (SCHEME_V1_ASCII, 1),
    ("services/reserve_split_snapshot.py", "split_contract_hash"): (SCHEME_V1_ASCII, 1),
    # SCHEME_V1_STR_DEFAULT -- sortiert, kompakt, UTF-8, default=str
    ("services/portfolio_handoff.py", "handoff_business_key_hash"): (SCHEME_V1_STR_DEFAULT, 1),
    ("services/risk_capacity_plausibility.py", "_evaluation_hash"): (SCHEME_V1_STR_DEFAULT, 1),
    # SCHEME_V1_ASCII_STR_DEFAULT -- sortiert, kompakt, ASCII, default=str
    ("services/currency/fx_rates.py", "_fingerprint"): (SCHEME_V1_ASCII_STR_DEFAULT, 1),
    ("services/portfolio_engine_allocation_integrity.py", "allocation_context_hash_for"):
        (SCHEME_V1_ASCII_STR_DEFAULT, 1),
    # SCHEME_LEGACY_SPACED -- sortiert, Standardtrennzeichen, ASCII
    ("routers/pdf_reports.py", "_audit_hash_for_mandate"): (SCHEME_LEGACY_SPACED, 1),
    ("services/pension_transfer_ledger.py", "PensionTransferLedgerV1.build"): (SCHEME_LEGACY_SPACED, 1),
    ("services/portfolio_engine_mc_simulation.py", "_run_allocation_monte_carlo"): (SCHEME_LEGACY_SPACED, 2),
    # SCHEME_LEGACY_SPACED_STR_DEFAULT -- sortiert, Standardtrennzeichen, ASCII, default=str
    ("schemas/allocation.py", "preferences_json_without_ignored_keys"): (SCHEME_LEGACY_SPACED_STR_DEFAULT, 1),
    ("services/cost_disclosure.py", "cost_disclosure_content_hash"): (SCHEME_LEGACY_SPACED_STR_DEFAULT, 1),
    ("services/document_archive.py", "content_hash_for"): (SCHEME_LEGACY_SPACED_STR_DEFAULT, 1),
    ("services/preference_snapshot.py", "_canonical"): (SCHEME_LEGACY_SPACED_STR_DEFAULT, 1),
    ("services/product_eligibility.py", "canonical_hash"): (SCHEME_LEGACY_SPACED_STR_DEFAULT, 1),
    ("services/portfolio_engine.py", "build_target_payload_from_allocation"):
        (SCHEME_LEGACY_SPACED_STR_DEFAULT, 2),
    # SCHEME_LEGACY_UNSORTED_UTF8 -- die gespeicherten Bytes sind der Beleg
    ("services/portfolio_handoff.py", "snapshot_json_and_sha256"): (SCHEME_LEGACY_UNSORTED_UTF8, 1),
}

# Stellen mit gemischten Schemata in EINER Funktion: Schema je Aufruf (Quelltext-Reihenfolge).
INVENTORY_MULTI: dict[tuple[str, str], tuple[str, ...]] = {
    ("services/manual_target_allocation.py", "build_manual_target_allocation"): (
        SCHEME_V1,                         # sub_allocations_json
        SCHEME_V1,                         # effective_constraints_json
        SCHEME_LEGACY_SPACED_STR_DEFAULT,  # preferences_json-Snapshot
        "bespoke:unsorted-compact-utf8",   # optimizer_reasoning_json
        SCHEME_V1,                         # effective_constraints_json nach Ledger-Bindung
    ),
    ("services/portfolio_engine.py", "_compute_input_snapshot_hash"): (
        "bespoke:sort-key-only",  # Sortierschluessel der Ziel-Items, kein Hash-Text
        SCHEME_LEGACY_SPACED,     # C8 input_snapshot_hash
    ),
    ("services/portfolio_engine.py", "generate_target_allocation"): (
        SCHEME_LEGACY_SPACED_STR_DEFAULT,  # preferences_json-Snapshot
        SCHEME_V1_ASCII,                   # stress_evaluations_json
        "bespoke:unsorted-compact-utf8",   # goal_achievability_json (siehe goal_analysis_snapshot)
        SCHEME_V1,                         # sub_allocations_json
        SCHEME_V1,                         # effective_constraints_json
    ),
}

# Abweichende Kanonisierungen, die KEINEM Schema entsprechen (unangetastet).
BESPOKE: dict[tuple[str, str], str] = {
    ("services/goal_analysis_snapshot.py", "serialize_goal_achievability"):
        "unsortiert, kompakt, UTF-8: der Hash bindet die gespeicherten Bytes",
    ("services/cma_correlation_provenance.py", "correlation_matrix_digest"):
        "unsortiert, kompakt, ASCII, Digest auf 16 Hex gekuerzt",
    ("services/optimizer/solver.py", "build_optimizer_context"):
        "allow_nan=False (NaN wirft), Digest auf 12 Hex gekuerzt (Cache-Schluessel)",
    ("services/optimizer/solver.py", "optimizer_content_seed"):
        "unsortiert, kompakt, ASCII (Seed-Material)",
}


def _normalize_kwargs(call: ast.Call) -> dict:
    out = {"sort_keys": False, "separators": None, "ensure_ascii": True, "default": None,
           "allow_nan": True, "indent": None}
    for kw in call.keywords:
        assert kw.arg is not None, "**kwargs an json.dumps ist nicht inventarisierbar"
        if kw.arg == "default":
            assert isinstance(kw.value, ast.Name)
            out["default"] = kw.value.id
        else:
            out[kw.arg] = ast.literal_eval(kw.value)
    if out["separators"] is not None:
        out["separators"] = tuple(out["separators"])
    if out["separators"] == (", ", ": ") and out["indent"] is None:
        out["separators"] = None
    return out


def _scheme_normalized(scheme: str) -> dict:
    kwargs = scheme_dumps_kwargs(scheme)
    out = {"sort_keys": False, "separators": None, "ensure_ascii": True, "default": None,
           "allow_nan": True, "indent": None}
    for key, value in kwargs.items():
        out[key] = value.__name__ if key == "default" else value
    return out


def _dumps_calls_by_function(rel: str) -> dict[str, list[ast.Call]]:
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    found: dict[str, list[ast.Call]] = {}
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def _scoped(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

        def visit_Call(self, node):
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == "dumps"
                    and isinstance(f.value, ast.Name) and f.value.id in {"json", "_json"}):
                found.setdefault(".".join(stack) or "<module>", []).append(node)
            self.generic_visit(node)

    Visitor().visit(tree)
    for calls in found.values():
        calls.sort(key=lambda c: (c.lineno, c.col_offset))
    return found


def _scheme_of(call: ast.Call) -> str | None:
    norm = _normalize_kwargs(call)
    matches = [s for s in evidence.SCHEMES if _scheme_normalized(s) == norm]
    return matches[0] if matches else None


@pytest.mark.parametrize("site", sorted(INVENTORY), ids=lambda s: f"{s[0]}::{s[1]}")
def test_inventoried_site_uses_exactly_its_scheme(site):
    rel, qualname = site
    scheme, count = INVENTORY[site]
    calls = _dumps_calls_by_function(rel).get(qualname, [])
    assert len(calls) == count, f"{rel}::{qualname}: {len(calls)} json.dumps statt {count}"
    for call in calls:
        assert _normalize_kwargs(call) == _scheme_normalized(scheme), (
            f"{rel}:{call.lineno} weicht von {scheme} ab"
        )


@pytest.mark.parametrize("site", sorted(INVENTORY_MULTI), ids=lambda s: f"{s[0]}::{s[1]}")
def test_inventoried_multi_site_schemes(site):
    rel, qualname = site
    expected = INVENTORY_MULTI[site]
    calls = _dumps_calls_by_function(rel).get(qualname, [])
    assert len(calls) == len(expected), f"{rel}::{qualname}: {len(calls)} json.dumps"
    for call, scheme in zip(calls, expected):
        actual = _scheme_of(call)
        if scheme.startswith("bespoke:"):
            assert actual is None or scheme == "bespoke:sort-key-only", (
                f"{rel}:{call.lineno} ist inzwischen Schema {actual}"
            )
        else:
            assert actual == scheme, f"{rel}:{call.lineno}: {actual} statt {scheme}"


@pytest.mark.parametrize("site", sorted(BESPOKE), ids=lambda s: f"{s[0]}::{s[1]}")
def test_bespoke_sites_exist_and_match_no_scheme(site):
    rel, qualname = site
    calls = _dumps_calls_by_function(rel).get(qualname, [])
    assert calls, f"{rel}::{qualname} nicht mehr gefunden -- Inventar nachfuehren"
    for call in calls:
        assert _scheme_of(call) is None, (
            f"{rel}:{call.lineno} entspricht jetzt {_scheme_of(call)} -- Inventar nachfuehren"
        )


def test_core_evidence_is_a_stdlib_leaf():
    """Blatt im Import-Graph: kein interner Import, also kein Zyklus moeglich."""
    tree = ast.parse((BACKEND / "core" / "evidence.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "types", "typing"}


# ---------------------------------------------------------------------------
# 3. Optional: Property-Test mit hypothesis (nur wenn installiert)
# ---------------------------------------------------------------------------


def test_hypothesis_property_v1_and_ascii_match_legacy_helpers():
    hypothesis = pytest.importorskip("hypothesis")
    st = pytest.importorskip("hypothesis.strategies")
    from services import depot_snapshot, risk_profile_signoff

    scalars = (st.none() | st.booleans() | st.integers() | st.floats(allow_nan=True)
               | st.text())
    payloads = st.recursive(
        scalars,
        lambda children: st.lists(children, max_size=5)
        | st.dictionaries(st.text(max_size=8), children, max_size=5),
        max_leaves=30,
    )

    @hypothesis.settings(max_examples=400, deadline=None)
    @hypothesis.given(payloads)
    def check(payload):
        assert risk_profile_signoff._sha256(payload) == evidence_hash(payload)
        assert depot_snapshot._canonical(payload) == canonical_json(payload, scheme=SCHEME_V1_ASCII)

    check()


def test_corpus_is_broad():
    """Selbstkontrolle des Korpus (sonst waere die Gleichheit wenig wert)."""
    flat = json.dumps(JSON_CORPUS[:40], ensure_ascii=False, default=str)
    for needle in ("Zürich", "💶", "NaN", "Infinity", "-0.0", "null", "2026-10-31T"):
        assert needle in flat
    assert any(isinstance(p, tuple) for p in JSON_CORPUS)
    assert any(isinstance(p, dict) and not p for p in JSON_CORPUS)
    assert any(isinstance(p, dict) and any(isinstance(v, Decimal) for v in p.values())
               for p in MIXED_CORPUS)
