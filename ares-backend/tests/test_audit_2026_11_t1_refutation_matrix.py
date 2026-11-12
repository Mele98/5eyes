"""Audit 2026-11 / 05, T1, Delta-Pruefung #863 N-863-11: Pruefmatrix der
Widerlegungsregel mit unabhaengigem Orakel.

Das Orakel ist bewusst einfach und getrennt vom Produktcode formuliert
(eigene Hierarchie, eigene Regel in wenigen Zeilen):

* Ein Nachweis zaehlt nur, wenn er freigegeben ist.
* Fuer die Abfrage Q kommen als erfuellende Nachweise nur Zeilen der
  Kategorie Q oder ihrer Oberkategorie in Frage; erfuellend ist eine
  Richtlinie mit Grenze <= Hausschwelle oder eine Messung mit Exposure 0 und
  Grenze <= Hausschwelle.
* Ein erfuellender Nachweis der Kategorie X mit Grenze L ist widerlegt, wenn
  eine freigegebene Messung mit Exposure > 0 in X oder einer Unterkategorie
  von X eine Grenze >= L hat.
* Q ist erfuellt, wenn mindestens ein erfuellender Nachweis nicht widerlegt ist.

Matrix: Kategorie x Grenze (kleiner/gleich/groesser als die Hausschwelle) x
Exposure 0/>0 x Status freigegeben/Entwurf/zurueckgezogen, dazu Paare von
Unterkategorie-Messungen; Abfragen Waffen / kontrovers / konventionell.
Ausgewertet ohne DB ueber den ``attributes``-Parameter.
"""
from __future__ import annotations

import itertools
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.product_eligibility_governance import evaluate_criterion  # noqa: E402

TODAY = date(2026, 11, 6)
HOUSE = 500
LIMITS = (400, 500, 600)              # kleiner / gleich / groesser als die Hausschwelle
EXPOSURES = (0, 100)
STATUSES = ("approved", "draft", "retired")
QUERIES = ("weapons", "controversial_weapons", "conventional_weapons")

# --- Orakel (unabhaengig vom Produktcode) ----------------------------------
ORACLE_CHILDREN = {"weapons": {"controversial_weapons", "conventional_weapons"}}
ORACLE_PARENT = {"controversial_weapons": "weapons", "conventional_weapons": "weapons"}


def oracle(rows, query) -> bool:
    approved = [r for r in rows if r.status == "approved"]
    for r in approved:
        if r.category not in (query, ORACLE_PARENT.get(query)):
            continue
        if r.revenue_threshold_bps > HOUSE:
            continue
        if r.kind == "measured_exposure" and r.measured_exposure_bps != 0:
            continue
        family = {r.category} | ORACLE_CHILDREN.get(r.category, set())
        refuted = any(
            m.kind == "measured_exposure" and m.measured_exposure_bps > 0
            and m.category in family and m.revenue_threshold_bps >= r.revenue_threshold_bps
            for m in approved
        )
        if not refuted:
            return True
    return False


# --- Fixtures --------------------------------------------------------------
_COUNTER = itertools.count()


def _row(category, kind, limit, exposure, status):
    n = next(_COUNTER)
    return SimpleNamespace(
        id=f"r{n:05d}", product_id="p1", tenant_id=None, category=category, kind=kind,
        revenue_threshold_bps=limit, measured_exposure_bps=exposure if kind == "measured_exposure" else None,
        value=None, status=status, as_of="2026-06-30", valid_until="2027-06-30",
    )


def _product(rows, query) -> bool:
    return evaluate_criterion(None, "p1", query, HOUSE, TODAY, attributes=rows).satisfied


def _check(cases):
    mismatches = []
    for rows, query in cases:
        expected, actual = oracle(rows, query), _product(rows, query)
        if expected != actual:
            mismatches.append((query, [(r.category, r.kind, r.revenue_threshold_bps, r.measured_exposure_bps,
                                        r.status) for r in rows], expected, actual))
    assert not mismatches, f"{len(mismatches)} Abweichungen, z. B. {mismatches[:3]}"
    return len(cases)


EVIDENCE = [(cat, kind) for cat in QUERIES for kind in ("exclusion_policy", "measured_exposure")]


@pytest.mark.parametrize("query", QUERIES)
@pytest.mark.parametrize("evidence_category,evidence_kind", EVIDENCE)
def test_matrix_evidence_against_single_measurement(query, evidence_category, evidence_kind):
    cases = []
    for e_limit in LIMITS:
        evidence = _row(evidence_category, evidence_kind, e_limit, 0, "approved")
        cases.append(([evidence], query))
        for m_cat, m_limit, m_exp, m_status in itertools.product(QUERIES, LIMITS, EXPOSURES, STATUSES):
            cases.append(([evidence, _row(m_cat, "measured_exposure", m_limit, m_exp, m_status)], query))
    assert _check(cases) == len(LIMITS) * (1 + len(QUERIES) * len(LIMITS) * len(EXPOSURES) * len(STATUSES))


@pytest.mark.parametrize("query", QUERIES)
@pytest.mark.parametrize("evidence_status", STATUSES)
def test_matrix_parent_policy_against_pairs_of_child_measurements(query, evidence_status):
    cases = []
    children = ("controversial_weapons", "conventional_weapons")
    variants = list(itertools.product(LIMITS, EXPOSURES, ("approved", "draft")))
    for e_limit in LIMITS:
        evidence = _row("weapons", "exclusion_policy", e_limit, 0, evidence_status)
        for (l1, x1, s1), (l2, x2, s2) in itertools.product(variants, variants):
            rows = [evidence, _row(children[0], "measured_exposure", l1, x1, s1),
                    _row(children[1], "measured_exposure", l2, x2, s2)]
            cases.append((rows, query))
            # zusaetzlich eine eigene Richtlinie der abgefragten Unterkategorie
            if query in children:
                cases.append((rows + [_row(query, "exclusion_policy", 0, 0, "approved")], query))
    assert _check(cases) > 0


def test_oracle_is_not_trivial():
    """Das Orakel unterscheidet erfuellt/nicht erfuellt in beide Richtungen."""
    policy = _row("weapons", "exclusion_policy", 400, 0, "approved")
    sibling = _row("conventional_weapons", "measured_exposure", 400, 100, "approved")
    assert oracle([policy], "controversial_weapons") is True
    assert oracle([policy, sibling], "controversial_weapons") is False
    assert oracle([policy, _row("conventional_weapons", "measured_exposure", 300, 100, "approved")],
                  "controversial_weapons") is True


# --- H-7 (Dok. 86, Pruefrunde #863 Delta): weitere Matrix-Dimensionen --------
# Das Orakel oben kennt eine einzige Hausschwelle (500), keine Grenze 0 und
# weder Gueltigkeit noch Tenant-Scope. Hier dieselbe Regel, erweitert um:
# * unterschiedliche Hausschwellen je Abfrage (z. B. kontroverse Waffen 0),
# * Grenze 0,
# * Gueltigkeit (abgelaufen / noch nicht gueltig zaehlt nicht, auch nicht als
#   Widerlegung),
# * Tenant-Scope (Plattform-Nachweis fuer alle, Tenant-Nachweis nur fuer den
#   eigenen Tenant; ein fremder zaehlt nicht, auch nicht als Widerlegung).
TENANT = "t-own"
H7_HOUSES = {"weapons": 500, "controversial_weapons": 0, "conventional_weapons": 500}
H7_LIMITS = (0, 400, 500, 600)
H7_VALIDITY = {
    "valid": ("2026-06-30", "2027-06-30"),
    "expired": ("2025-06-30", "2026-06-30"),
    "not_yet_valid": ("2026-12-01", "2027-12-01"),
}
H7_TENANTS = (None, TENANT, "t-foreign")


def oracle_h7(rows, query, house, today, tenant) -> bool:
    def counts(r) -> bool:
        return (
            r.status == "approved"
            and date.fromisoformat(r.as_of) <= today <= date.fromisoformat(r.valid_until)
            and r.tenant_id in (None, tenant)
        )

    usable = [r for r in rows if counts(r)]
    for r in usable:
        if r.category not in (query, ORACLE_PARENT.get(query)):
            continue
        if r.revenue_threshold_bps > house:
            continue
        if r.kind == "measured_exposure" and r.measured_exposure_bps != 0:
            continue
        family = {r.category} | ORACLE_CHILDREN.get(r.category, set())
        refuted = any(
            m.kind == "measured_exposure" and m.measured_exposure_bps > 0
            and m.category in family and m.revenue_threshold_bps >= r.revenue_threshold_bps
            for m in usable
        )
        if not refuted:
            return True
    return False


def _row_h7(category, kind, limit, exposure, validity, tenant_id):
    row = _row(category, kind, limit, exposure, "approved")
    row.as_of, row.valid_until = H7_VALIDITY[validity]
    row.tenant_id = tenant_id
    return row


@pytest.mark.parametrize("query", QUERIES)
def test_h7_matrix_house_thresholds_validity_and_tenant(query):
    house = H7_HOUSES[query]
    combos = list(itertools.product(H7_LIMITS, H7_VALIDITY, H7_TENANTS))
    mismatches, total, satisfied = [], 0, 0
    for e_cat, e_kind in EVIDENCE:
        for e_limit, e_valid, e_tenant in combos:
            evidence = _row_h7(e_cat, e_kind, e_limit, 0, e_valid, e_tenant)
            for m_cat, (m_limit, m_valid, m_tenant), m_exp in itertools.product(QUERIES, combos, EXPOSURES):
                rows = [evidence, _row_h7(m_cat, "measured_exposure", m_limit, m_exp, m_valid, m_tenant)]
                expected = oracle_h7(rows, query, house, TODAY, TENANT)
                actual = evaluate_criterion(
                    None, "p1", query, house, TODAY, tenant_id=TENANT, attributes=rows,
                ).satisfied
                total += 1
                satisfied += expected
                if expected != actual:
                    mismatches.append((e_cat, e_kind, e_limit, e_valid, e_tenant,
                                       m_cat, m_limit, m_exp, m_valid, m_tenant, expected, actual))
    assert not mismatches, f"{len(mismatches)} Abweichungen, z. B. {mismatches[:3]}"
    # Die Matrix unterscheidet in beide Richtungen.
    assert 0 < satisfied < total


def test_h7_oracle_dimensions_are_not_trivial():
    policy = _row_h7("weapons", "exclusion_policy", 0, 0, "valid", None)
    hit = _row_h7("conventional_weapons", "measured_exposure", 0, 100, "valid", None)
    assert oracle_h7([policy], "controversial_weapons", 0, TODAY, TENANT) is True
    assert oracle_h7([policy, hit], "controversial_weapons", 0, TODAY, TENANT) is False
    for validity in ("expired", "not_yet_valid"):
        assert oracle_h7([policy, _row_h7("conventional_weapons", "measured_exposure", 0, 100, validity, None)],
                         "controversial_weapons", 0, TODAY, TENANT) is True
    assert oracle_h7([policy, _row_h7("conventional_weapons", "measured_exposure", 0, 100, "valid", "t-foreign")],
                     "controversial_weapons", 0, TODAY, TENANT) is True
    assert oracle_h7([_row_h7("weapons", "exclusion_policy", 0, 0, "valid", "t-foreign")],
                     "weapons", 500, TODAY, TENANT) is False
    assert oracle_h7([_row_h7("controversial_weapons", "exclusion_policy", 400, 0, "valid", None)],
                     "controversial_weapons", 0, TODAY, TENANT) is False
