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

# Bekannte, nicht statisch aufloesbare Erzeugungsstellen ("Datei: Ausdruck").
# Ueberwiegend Durchreichungen (Code einer gefangenen Exception, Parameter,
# Werte aus Provider-Antworten oder gespeicherten Ergebnissen). Die dahinter
# liegenden Literale sind ueber ihre Ursprungsstelle im Katalog.
KNOWN_UNRESOLVED = frozenset({
    "core/reason_codes.py: reason_code.value if isinstance(reason_code, ReasonCode) else reason_code",
    "core/reason_codes.py: self.reason_code",
    "routers/client_portal.py: str(detail.get('reason_code') or 'RELEASE_BLOCKED')",
    "routers/eligibility_overrides.py: exc",
    "routers/eligibility_overrides.py: exc.code",
    "routers/onsite_signature.py: body.reason_code",
    "routers/onsite_signature.py: e.reason_code",
    "routers/review.py: cma_policy_block[0]",
    "routers/review.py: structured_reason",
    "services/advisory_report.py: resolution.reason_code",
    "services/cma_valuation_hold.py: reason_code",
    "services/house_matrix_benchmark.py: reason_code",
    "services/house_matrix_benchmark.py: str(resolution.reason_code)",
    "services/onsite_signature/service.py: None if delivered else result.reason_code or DELIVERY_PROOF_MISSING",
    "services/onsite_signature/service.py: event.reason_code",
    "services/onsite_signature/service.py: reason",
    "services/onsite_signature/service.py: reason_code",
    "services/product_eligibility_override.py: row.reason_code",
    "services/risk_capacity_evaluation_snapshot.py: result.get('reason_code')",
    "services/risk_capacity_evaluation_snapshot.py: stored_result.get('reason_code')",
    "services/risk_capacity_plausibility.py: result.get('reason_code')",
    "services/risk_capacity_plausibility_report.py: result.get('reason_code')",
    "services/suitability_cap_check.py: reason_code",
    "services/suitability_cap_check.py: resolution.reason_code",
})


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


def test_unresolved_producer_sites_are_known(backend):
    current = {e.split(":", 1)[0] + ":" + e.split(":", 2)[2] for e in backend.unresolved}
    new = sorted(current - KNOWN_UNRESOLVED)
    assert not new, (
        "Neue nicht statisch aufloesbare reason_code-Stelle(n). Literal/Konstante verwenden "
        "oder bewusst in KNOWN_UNRESOLVED aufnehmen:\n  " + "\n  ".join(new)
    )
    gone = sorted(KNOWN_UNRESOLVED - current)
    assert not gone, "KNOWN_UNRESOLVED enthaelt erledigte Stellen (entfernen):\n  " + "\n  ".join(gone)


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
