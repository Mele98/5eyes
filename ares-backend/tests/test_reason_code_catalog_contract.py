"""K-2 Vertragstest: Reason-Code-Katalog <-> Backend / Monolith / Reporting / PDF.

``core.reason_codes.ReasonCode`` ist das Register aller Reason-Codes. Statisch
(AST fuer Python, Regex fuer JS/TS; kein App-Start, keine DB) wird geprueft:

1. Jeder im Backend erzeugte Reason-Code steht im Katalog.
2. Jeder im Backend ausgewertete Code (inkl. PDF-Erzeugung) steht im Katalog.
3. Jeder Code, den der Monolith (``ares.html`` + Begleit-JS) oder das
   Reporting (``reporting/src``, ohne Tests) auswertet, steht im Katalog UND
   wird vom Backend erzeugt (sonst: toter Frontend-Zweig).
4. Der Katalog enthaelt nur Codes, die das Backend erzeugt oder auswertet
   (Werte 1:1, nichts erfunden).
5. Nicht statisch aufloesbare Erzeugungsstellen sind eine bekannte, gepruefte
   Liste; neue dynamische Stellen muessen hier bewusst eingetragen werden.

Die Extraktion steht in ``reason_code_contract_support.py``; Positiv-
kontrollen auf Mini-Quellen belegen, dass jede Erkennungsregel greift.
"""
from __future__ import annotations

import json
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import reason_code_contract_support as rc  # noqa: E402
from core.reason_codes import DomainError, ReasonCode  # noqa: E402

CATALOG = {m.value for m in ReasonCode}

# Bekannte, nicht statisch aufloesbare Erzeugungsstellen:
# (Datei, Funktion, Ausdruck) -> Anzahl Zeilen mit genau diesem Ausdruck.
# Ueberwiegend Durchreichungen (Code einer gefangenen Exception, Parameter,
# Werte aus Provider-Antworten oder gespeicherten Ergebnissen). Die dahinter
# liegenden Literale sind ueber ihre Ursprungsstelle im Katalog. Schluessel
# mit Funktion und Anzahl: eine neue dynamische Stelle mit gleichem Text
# (andere Funktion oder zusaetzliche Zeile) faellt auf (K-2-Review N1).
KNOWN_UNRESOLVED: dict[tuple[str, str, str], int] = {
    ('core/reason_codes.py', 'DomainError.__init__',
     'reason_code.value if isinstance(reason_code, ReasonCode) else reason_code'): 1,
    ('core/reason_codes.py', 'DomainError.as_detail',
     'self.reason_code'): 1,
    ('routers/client_portal.py', '_assert_portal_report_releasable',
     "str(detail.get('reason_code') or 'RELEASE_BLOCKED')"): 1,
    ('routers/eligibility_overrides.py', '_conflict',
     'exc.code'): 1,
    ('routers/eligibility_overrides.py', 'approve_eligibility_override',
     'exc'): 1,
    ('routers/eligibility_overrides.py', 'request_eligibility_override',
     'exc'): 1,
    ('routers/onsite_signature.py', '_view',
     'e.reason_code'): 1,
    ('routers/onsite_signature.py', 'onsite_abort',
     'body.reason_code'): 1,
    ('routers/review.py', 'finalize_recommendation',
     'cma_policy_block[0]'): 1,
    ('routers/review.py', 'finalize_recommendation',
     'structured_reason'): 1,
    ('services/advisory_report.py', '_build_performance_attribution',
     'resolution.reason_code'): 1,
    ('services/cma_valuation_hold.py', 'assert_allocation_cma_without_adr12a_hold',
     'reason_code'): 1,
    ('services/house_matrix_benchmark.py', '_unavailable',
     'reason_code'): 1,
    ('services/house_matrix_benchmark.py', 'resolve_depotcheck_benchmark',
     'str(resolution.reason_code)'): 1,
    ('services/onsite_signature/service.py', '_new_event',
     'reason_code'): 1,
    ('services/onsite_signature/service.py', 'abort_transaction',
     'reason_code'): 1,
    ('services/onsite_signature/service.py', 'deliver_customer_copy',
     'reason'): 2,
    ('services/onsite_signature/service.py', 'issue_customer_challenge',
     'None if delivered else result.reason_code or DELIVERY_PROOF_MISSING'): 1,
    ('services/onsite_signature/service.py', 'issue_customer_challenge',
     'event.reason_code'): 1,
    ('services/product_eligibility_override.py', 'override_evidence_hash',
     'row.reason_code'): 1,
    ('services/risk_capacity_evaluation_snapshot.py', 'replay_snapshot',
     "stored_result.get('reason_code')"): 1,
    ('services/risk_capacity_evaluation_snapshot.py', 'structured_result',
     "result.get('reason_code')"): 1,
    ('services/risk_capacity_plausibility.py', 'audit_payload',
     "result.get('reason_code')"): 1,
    ('services/risk_capacity_plausibility_report.py', 'compact_view',
     "result.get('reason_code')"): 1,
    ('services/suitability_cap_check.py', '_unavailable',
     'reason_code'): 1,
    ('services/suitability_cap_check.py', 'evaluate_house_matrix_cap',
     'resolution.reason_code'): 1,
}


@pytest.fixture(scope="module")
def backend() -> rc.Extraction:
    return rc.extract_backend()


@pytest.fixture(scope="module")
def monolith() -> dict[str, set[str]]:
    return rc.extract_monolith()


@pytest.fixture(scope="module")
def reporting() -> dict[str, set[str]]:
    return rc.extract_reporting()


def _sites(sites, missing: set[str]) -> str:
    return "\n".join(f"  {s.value}  ({s.path}:{s.line})" for s in sites if s.value in missing)


# --------------------------------------------------------------------------
# Katalog selbst
# --------------------------------------------------------------------------


def test_catalog_is_a_str_enum_with_unique_canonical_members():
    values = [m.value for m in ReasonCode]
    assert len(values) == len(set(values))
    for m in ReasonCode:
        assert isinstance(m.value, str) and m.value
        assert m.name == "".join(c if c.isalnum() else "_" for c in m.value).strip("_").upper()
        # StrEnum: Formatierung/Vergleich/JSON wie der rohe String.
        assert m == m.value and f"{m}" == m.value and json.dumps(m) == json.dumps(m.value)


def test_catalog_module_is_sorted_and_free_of_fastapi():
    src = (BACKEND_ROOT / "core" / "reason_codes.py").read_text(encoding="utf-8")
    assert "fastapi" not in src.split('"""', 2)[2]
    names = [m.name for m in ReasonCode]
    assert names == sorted(names)


# --------------------------------------------------------------------------
# Backend <-> Katalog
# --------------------------------------------------------------------------


def test_every_backend_produced_code_is_in_catalog(backend):
    missing = backend.produced_codes() - CATALOG
    assert not missing, "Reason-Codes fehlen im Katalog core/reason_codes.py:\n" + _sites(backend.produced, missing)


def test_every_backend_consumed_code_incl_pdf_is_in_catalog(backend):
    missing = backend.consumed_codes() - CATALOG
    assert not missing, "Ausgewertete Codes fehlen im Katalog:\n" + _sites(backend.consumed, missing)
    assert backend.consumed_codes(pdf_only=True) <= CATALOG


def test_catalog_has_no_invented_codes(backend):
    dead = CATALOG - backend.produced_codes() - backend.consumed_codes()
    assert not dead, f"Katalog enthaelt Codes, die das Backend weder erzeugt noch auswertet: {sorted(dead)}"


def _unresolved_diff(keys, known: dict[tuple[str, str, str], int]) -> tuple[list, list]:
    """(neu/mehr, erledigt/weniger) zwischen gefundenen Stellen und ``known``."""
    current = Counter(keys)
    new = sorted(f"{k[0]}::{k[1]}: {k[2]}  ({n} statt {known.get(k, 0)})"
                 for k, n in current.items() if n > known.get(k, 0))
    gone = sorted(f"{k[0]}::{k[1]}: {k[2]}  ({current.get(k, 0)} statt {n})"
                  for k, n in known.items() if current.get(k, 0) < n)
    return new, gone


def test_unresolved_producer_sites_are_known(backend):
    new, gone = _unresolved_diff(backend.unresolved_keys, KNOWN_UNRESOLVED)
    assert not new, (
        "Neue nicht statisch aufloesbare reason_code-Stelle(n). Literal/Konstante verwenden "
        "oder bewusst in KNOWN_UNRESOLVED aufnehmen:\n  " + "\n  ".join(new)
    )
    assert not gone, "KNOWN_UNRESOLVED enthaelt erledigte Stellen (entfernen):\n  " + "\n  ".join(gone)


def _mini_backend(tmp_path: Path, extra: str = "") -> Path:
    root = tmp_path / "backend"
    for rel in ("core/reason_codes.py", "services/cma_valuation_hold.py"):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((BACKEND_ROOT / rel).read_text(encoding="utf-8") + (
            extra if rel.endswith("cma_valuation_hold.py") else ""), encoding="utf-8")
    return root


def _known_for(rel: str) -> dict[tuple[str, str, str], int]:
    return {k: n for k, n in KNOWN_UNRESOLVED.items() if k[0] == rel}


def test_negative_control_new_dynamic_domain_error_in_cma_valuation_hold_is_red(tmp_path):
    rel = "services/cma_valuation_hold.py"
    clean = rc.extract_backend(_mini_backend(tmp_path / "a"))
    keys = [k for k in clean.unresolved_keys if k[0] == rel]
    assert _unresolved_diff(keys, _known_for(rel)) == ([], [])  # unveraendert: gruen
    extra = textwrap.dedent(
        """

        def _new_dynamic_block(cma):
            # gleicher Ausdruckstext wie die bekannte Stelle, andere Funktion
            reason_code = cma.get("hold_reason")
            raise DomainError(reason_code, "Hold", http_status=409)
        """
    )
    mutated = rc.extract_backend(_mini_backend(tmp_path / "b", extra))
    keys = [k for k in mutated.unresolved_keys if k[0] == rel]
    new, _ = _unresolved_diff(keys, _known_for(rel))
    # vorher maskiert: Schluessel "Datei: reason_code" existierte schon
    assert f"{rel}::_new_dynamic_block: reason_code  (1 statt 0)" in new, new


def test_negative_control_same_expression_twice_is_counted(tmp_path):
    rel = "services/cma_valuation_hold.py"
    extra = textwrap.dedent(
        """

        def _new_double_block(cma, strict):
            reason_code = cma.get("hold_reason")
            if strict:
                raise DomainError(reason_code, "Hold", http_status=409)
            raise DomainError(reason_code, "Hold", http_status=422)
        """
    )
    mutated = rc.extract_backend(_mini_backend(tmp_path, extra))
    keys = [k for k in mutated.unresolved_keys if k[0] == rel]
    new, _ = _unresolved_diff(keys, _known_for(rel))
    assert f"{rel}::_new_double_block: reason_code  (2 statt 0)" in new, new


def test_onsite_signature_constants_come_from_catalog():
    from services.onsite_signature import service as svc

    names = [n for n in dir(svc) if n.isupper() and isinstance(getattr(svc, n), str)]
    codes = {getattr(svc, n) for n in names} & CATALOG
    assert len(codes) == 33
    for n in names:
        v = getattr(svc, n)
        if v in CATALOG:
            assert type(v) is str, n  # reine str, kein Enum-Mitglied (Persistenz/Hash unveraendert)
    assert svc.ABORT_REASONS == frozenset({"OFFLINE_ABORT", "CUSTOMER_DECLINED", "ADVISOR_CANCELLED"})
    assert issubclass(svc.OnsiteSignatureError, DomainError)


# --------------------------------------------------------------------------
# Frontend / Reporting <-> Katalog
# --------------------------------------------------------------------------


def test_monolith_evaluated_codes_exist(monolith, backend):
    found = set().union(*monolith.values()) if monolith else set()
    assert found, "Extraktion fand im Monolith keine Codes (Regel kaputt?)"
    missing = found - CATALOG
    assert not missing, f"Monolith wertet Codes aus, die nicht im Katalog stehen: {sorted(missing)}"
    assert found <= backend.produced_codes(), sorted(found - backend.produced_codes())


def test_reporting_evaluated_codes_exist(reporting, backend):
    found = set().union(*reporting.values()) if reporting else set()
    assert found, "Extraktion fand im Reporting keine Codes (Regel kaputt?)"
    missing = found - CATALOG
    assert not missing, f"Reporting wertet Codes aus, die nicht im Katalog stehen: {sorted(missing)}"
    assert found <= backend.produced_codes(), sorted(found - backend.produced_codes())


def test_known_frontend_evaluations_are_seen(monolith, reporting):
    """Positivkontrolle gegen eine stumm gewordene Extraktion."""
    mono = set().union(*monolith.values())
    rep = set().union(*reporting.values())
    assert {"RISK_BUDGET_VIOLATED", "PENSION_SOURCE_LINKED", "NO_HOLDINGS_CONFIRMATION_REQUIRED"} <= mono
    assert "NO_CURRENT_RISK_ASSESSMENT" in rep
    assert "string" not in rep  # typeof-Pruefung ist kein Code


# --------------------------------------------------------------------------
# Positivkontrollen der Backend-Extraktion (Mini-Backend)
# --------------------------------------------------------------------------


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")


def test_backend_extraction_rules_each_detect_a_code(tmp_path):
    root = tmp_path / "backend"
    _write(root, "services/__init__.py", "")
    _write(root, "services/consts.py", 'IMPORTED = "C_IMPORTED"\n')
    _write(root, "services/errors.py", """
        class MyError(Exception):
            def __init__(self, reason_code, message, *, status=409):
                self.reason_code = reason_code

        class KwError(Exception):
            def __init__(self, message, *, reason_code):
                self.reason_code = reason_code

        class Child(MyError):
            pass

        class CodeHolder(Exception):
            def __init__(self, code):
                self.code = code
    """)
    _write(root, "services/a.py", """
        from services.consts import IMPORTED
        from services.errors import Child, CodeHolder, KwError, MyError
        LOCAL = "C_MODULE_CONST"

        def kw():
            return dict(reason_code="C_KWARG")

        def dct():
            return {"reason_code": "C_DICT"}

        def positional():
            raise MyError(LOCAL, "x")

        def inherited():
            raise Child(IMPORTED, "x")

        def conditional(flag):
            return {"reason_code": "C_IF_A" if flag else "C_IF_B"}

        def default(x):
            return {"reason_code": x or "C_OR_DEFAULT"}

        def findings():
            return [("C_TUPLE", "msg")]

        def unpack():
            code, _msg = findings()[0]
            return {"reason_code": code}

        def helper(reason_code):
            return {"reason_code": reason_code}

        def caller():
            return helper("C_VIA_PARAM")

        def fstring():
            try:
                raise KwError("x", reason_code="C_INNER")
            except KwError as exc:
                return {"reason_code": f"pre_{exc.reason_code}"}

        def consumer(d):
            if d["reason_code"] in {"C_CONSUMED"}:
                return 1
    """)
    ex = rc.extract_backend(root)
    produced = ex.produced_codes()
    for code in ("C_KWARG", "C_DICT", "C_MODULE_CONST", "C_IMPORTED", "C_IF_A", "C_IF_B",
                 "C_OR_DEFAULT", "C_TUPLE", "C_VIA_PARAM", "C_INNER", "pre_C_INNER"):
        assert code in produced, (code, sorted(produced))
    assert ex.consumed_codes() == {"C_CONSUMED"}


def test_frontend_extraction_rules_each_detect_a_code():
    js = textwrap.dedent("""
        var HINTS={
          A_MAP:'Text, mit Komma: und Doppelpunkt',
          'B_MAP':'x'
        };
        var NO_HOLD='C_CONST';
        function f(d){
          if(HINTS[d.reason_code]) return 1;
          if(d.reason_code==='D_CMP') return 2;
          if('E_REV'===d.reason_code) return 3;
          if(d.reason_code===NO_HOLD) return 4;
          if(typeof d.reason_code==='string') return 5;
          switch(d.reason_code){
            case 'F_CASE': return 6;
          }
        }
    """)
    assert rc.extract_frontend_text(js) == {"A_MAP", "B_MAP", "C_CONST", "D_CMP", "E_REV", "F_CASE"}


# --------------------------------------------------------------------------
# K-2b: Services werfen strukturierte Fehler nur noch als DomainError
# --------------------------------------------------------------------------


def _structured_http_exceptions_in_services() -> list[str]:
    import ast

    hits = []
    for path in sorted((BACKEND_ROOT / "services").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None))
                    == "HTTPException"):
                continue
            for kw in node.keywords:
                if kw.arg == "detail" and isinstance(kw.value, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "reason_code" for k in kw.value.keys
                ):
                    hits.append(f"{path.relative_to(BACKEND_ROOT).as_posix()}:{node.lineno}")
    return hits


def test_services_raise_structured_errors_only_as_domain_error():
    hits = _structured_http_exceptions_in_services()
    assert not hits, "HTTPException mit reason_code-Detail in services/ -> DomainError verwenden:\n  " + "\n  ".join(hits)


def test_structured_http_exception_scan_detects_a_hit(tmp_path, monkeypatch):
    """Positivkontrolle fuer den Scan oben."""
    probe = tmp_path / "services" / "probe.py"
    probe.parent.mkdir(parents=True)
    probe.write_text('from fastapi import HTTPException\n'
                     'raise HTTPException(status_code=409, detail={"reason_code": "X", "message": "m"})\n',
                     encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "BACKEND_ROOT", tmp_path)
    assert _structured_http_exceptions_in_services() == ["services/probe.py:2"]
