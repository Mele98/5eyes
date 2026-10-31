"""2026-07-27 (Retrozessions-Feature): FIDLEG Art. 25/26 + BGE 132 III 460
verlangen Offenlegung von Vergütungen Dritter (Retrozessionen) UNABHAENGIG
davon, ob sie an den Kunden zurückerstattet werden. Der Kostenausweis
erfasste sie bisher gar nicht.

Regel:
- reimbursed_to_client=True  -> negativer Cost-Item (Rückerstattung),
  IM Total enthalten (Kunde zahlt netto weniger).
- reimbursed_to_client=False -> positiver Cost-Item (Transparenz), NICHT
  im Total enthalten (bereits Teil der andernorts ausgewiesenen Kosten,
  kein separater Zusatzposten -- sonst Doppelzählung).

PRAEZISIERUNG 2026-10-12 (INDUCEMENT-EVIDENCE-001): die Regel oben war
unvollstaendig, und aus genau dieser Luecke folgte der Defekt. `reimbursed`
allein entscheidet nur, OB der Betrag ins Total geht -- nicht, was ueber den
Rechtsgrund behauptet werden darf. Der einbehaltene Fall spaltet sich:

- einbehalten MIT Nachweis (offengelegt + Verzichts-Dokument abgelegt)
  -> key "retrocession_disclosed", "Verzicht dokumentiert".
- einbehalten OHNE Nachweis
  -> key "retrocession_retained_unwaived", requires_resolution=True, KEIN
     Verzicht-Claim. Der Posten bleibt sichtbar (FIDLEG Art. 26); nach
     BGE 132 III 460 steht der Betrag dem Kunden zu, bis ein gueltiger
     Verzicht belegt ist.

Beide bleiben ausserhalb des Totals -- aber aus verschiedenen Gruenden, und
nur der erste darf einen Verzicht behaupten.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cost_disclosure import calculate_cost_disclosure

_POSITIONS = [{"amount_rappen": 50_000_000, "ter_bps": 20}]
_FEE = {"default_advisory_fee_bps": 75}


def _retro_items(data):
    return [i for i in data["cost_items"] if i["category"] == "Vergütungen von Dritten"]


def test_reimbursed_retrocession_reduces_total_and_is_disclosed():
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    with_retro = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 50_000, "frequency": "jährlich",
                      "reimbursed_to_client": True, "provider": "Fonds AG"}],
    )
    items = _retro_items(with_retro)
    assert len(items) == 1
    assert items[0]["amount_rappen"] == -50_000
    assert items[0]["included_in_total"] is True
    assert "Fonds AG" in items[0]["label"]
    # Total sinkt um genau den zurückerstatteten Betrag.
    assert with_retro["totals"]["annual_rappen"] == baseline["totals"]["annual_rappen"] - 50_000


def test_retained_retrocession_with_documented_waiver_is_disclosed_not_double_counted():
    """Einbehalten MIT Nachweis: der Verzicht-Claim ist hier zulaessig.

    INDUCEMENT-EVIDENCE-001: dieser Test hiess bis 2026-10-12
    `test_retained_retrocession_disclosed_but_not_double_counted` und setzte
    KEINE Nachweisfelder -- er pinnte damit den Verzicht-Claim fuer einen
    Fall ohne jeden Nachweis als Kontrakt. Er blieb nach dem Fix gruen, weil
    `_retro_items` nach Kategorie statt nach Key filtert und das neue
    Warn-Wort ebenfalls "einbehalten" enthaelt: der Test lief unbemerkt auf
    dem anderen Pfad. Deshalb jetzt zwei Tests, beide mit Key-Assertion.
    """
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    with_retro = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 50_000, "frequency": "jährlich",
                      "reimbursed_to_client": False, "provider": "Fonds AG",
                      "disclosed_to_client": True,
                      "waiver_document_id": "doc-waiver-1"}],
    )
    items = _retro_items(with_retro)
    assert len(items) == 1
    assert items[0]["key"] == "retrocession_disclosed"
    assert items[0]["amount_rappen"] == 50_000
    assert items[0]["included_in_total"] is False
    assert items[0]["requires_resolution"] is False
    # Total bleibt UNVERAENDERT -- kein zusaetzlicher Kostenpunkt (Doppelzaehl-Schutz).
    assert with_retro["totals"]["annual_rappen"] == baseline["totals"]["annual_rappen"]
    assert any("dokumentiertem Kundenverzicht" in w for w in with_retro["warnings"])


def test_retained_retrocession_without_waiver_evidence_claims_no_waiver():
    """Einbehalten OHNE Nachweis: sichtbar, gekennzeichnet, kein Verzicht-Claim."""
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    with_retro = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 50_000, "frequency": "jährlich",
                      "reimbursed_to_client": False, "provider": "Fonds AG"}],
    )
    items = _retro_items(with_retro)
    assert len(items) == 1
    assert items[0]["key"] == "retrocession_retained_unwaived"
    assert items[0]["requires_resolution"] is True
    # Sichtbar (FIDLEG Art. 26), aber weder verrechnet noch als Verzicht erklaert.
    assert items[0]["amount_rappen"] == 50_000
    assert items[0]["included_in_total"] is False
    assert with_retro["totals"]["annual_rappen"] == baseline["totals"]["annual_rappen"]
    assert not any("Verzicht dokumentiert" in i["source"] for i in items)
    assert "Verzicht NICHT belegt" in items[0]["source"]
    assert any("BGE 132 III 460" in w for w in with_retro["warnings"])
    assert any("kein Verzichts-Dokument abgelegt" in w for w in with_retro["warnings"])


def test_no_inducements_leaves_output_unchanged():
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    explicit_empty = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[],
    )
    assert baseline["totals"] == explicit_empty["totals"]
    assert _retro_items(explicit_empty) == []


def test_zero_amount_inducement_is_skipped():
    data = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 0, "reimbursed_to_client": True}],
    )
    assert _retro_items(data) == []


def test_non_annual_reimbursed_retrocession_excluded_from_total_with_warning():
    data = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 10_000, "frequency": "einmalig",
                      "reimbursed_to_client": True, "provider": "X"}],
    )
    items = _retro_items(data)
    assert len(items) == 1
    assert items[0]["included_in_total"] is False
    assert any("nicht-jährlicher" in w or "verrechnet" in w for w in data["warnings"])


def test_missing_frequency_on_reimbursed_retrocession_excluded_from_total_with_warning():
    """Mega-Audit (2026-08-04): ein LEERER Frequenz-Wert wurde bisher als
    'jährlich' gewertet und mindert damit stillschweigend das Kosten-Total
    -- obwohl der Berater die Frequenz nie bestaetigt hat. Fix: nur eine
    EXPLIZIT jährliche Frequenz zaehlt; ein fehlender Wert bleibt konservativ
    aussen vor (analog zur bereits bestehenden 'einmalig'-Behandlung)."""
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    with_retro = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 10_000,
                      "reimbursed_to_client": True, "provider": "Y"}],
    )
    items = _retro_items(with_retro)
    assert len(items) == 1
    assert items[0]["included_in_total"] is False
    assert items[0]["frequency"] == "nicht erfasst"
    # Total bleibt UNVERAENDERT -- keine unbelegte Kostenreduktion.
    assert with_retro["totals"]["annual_rappen"] == baseline["totals"]["annual_rappen"]
    assert any("keine erfasste Frequenz" in w for w in with_retro["warnings"])


def test_absurdly_large_reimbursed_amount_excluded_from_total_with_warning():
    """TEN-COMP-003 Teil 2 (Codex-Audit 2026-08-27, Folgeaudit): Teil 1 blockierte nur
    einen direkt negativen inducement_amount_rappen (schemas/review.py Field(ge=0)).
    Der reproduzierte Angriff nutzt stattdessen einen absurd GROSSEN positiven Betrag
    (z.B. 999'999'999'999 Rappen) kombiniert mit reimbursed_to_client=True + jaehrlicher
    Frequenz -- das Total durfte dadurch NICHT beliebig negativ werden. Diese Ebene
    (calculate_cost_disclosure) ist Verteidigung in der Tiefe fuer Aufrufer, die die
    Pydantic-Schema-Schranke nicht durchlaufen."""
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    with_retro = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 999_999_999_999, "frequency": "jährlich",
                      "reimbursed_to_client": True, "provider": "Bogus AG"}],
    )
    items = _retro_items(with_retro)
    assert len(items) == 1
    assert items[0]["included_in_total"] is False
    # Insbesondere: das Total wird NICHT negativ / nicht absurd -- unveraendert
    # gegenueber der Baseline ohne Retrozession.
    assert with_retro["totals"]["annual_rappen"] == baseline["totals"]["annual_rappen"]
    assert with_retro["totals"]["annual_rappen"] >= 0
    assert with_retro["totals"]["first_year_rappen"] >= 0
    assert any("Höchstbetrag" in w for w in with_retro["warnings"])


def test_realistic_reimbursed_amount_still_reduces_total_regression():
    """Regression: ein realistischer Rückerstattungsbetrag (deutlich unter der
    Plausibilitäts-Obergrenze) muss weiterhin wie bisher vom Total abgezogen werden --
    der neue Deckel darf legitime Werte nicht betreffen."""
    baseline = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
    )
    with_retro = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[{"amount_rappen": 120_000, "frequency": "jährlich",
                      "reimbursed_to_client": True, "provider": "Fonds AG"}],
    )
    items = _retro_items(with_retro)
    assert len(items) == 1
    assert items[0]["amount_rappen"] == -120_000
    assert items[0]["included_in_total"] is True
    assert with_retro["totals"]["annual_rappen"] == baseline["totals"]["annual_rappen"] - 120_000
    assert not any("Höchstbetrag" in w for w in with_retro["warnings"])


def test_multiple_inducements_mixed_reimbursement():
    data = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000, positions=_POSITIONS, fee_model=_FEE,
        inducements=[
            {"amount_rappen": 30_000, "frequency": "jährlich",
             "reimbursed_to_client": True, "provider": "A"},
            {"amount_rappen": 20_000, "frequency": "jährlich",
             "reimbursed_to_client": False, "provider": "B"},
        ],
    )
    items = _retro_items(data)
    assert len(items) == 2
    reimbursed = [i for i in items if i["included_in_total"]]
    retained = [i for i in items if not i["included_in_total"]]
    assert len(reimbursed) == 1 and reimbursed[0]["amount_rappen"] == -30_000
    assert len(retained) == 1 and retained[0]["amount_rappen"] == 20_000
