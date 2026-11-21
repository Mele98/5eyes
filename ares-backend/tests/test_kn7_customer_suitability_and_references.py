"""KN7 (H-181-Pruefung, CTO-Nachtrag): Pruefgrundlage und kurze Referenzen im Kunden-PDF.

* Punkt 1 -- Beratungsentscheid (contract_signoff): Bestaetigungstexte je
  ``suitability_basis`` ueber ``customer_suitability_text``. Execution-only und
  institutionelle Kunden bestaetigen nie «Geeignetheit geprueft».
* Punkt 2 / N-928-01 -- Advisory-Report: Leerzustand von Sektion 27 je
  Pruefgrundlage; Waechter: Sektion 19 und Sektion 27 widersprechen sich nie
  (alle Grundlagen, mit und ohne erfassten Pruefdatensatz).
* Punkt 3 -- Risikoprofil-PDF bei Override: «Entscheid-Nr. <8 Zeichen>»; volle
  Decision-ID/SHA-256 nur in der Berater-/Audit-Fassung.
* Punkt 4 / N-928-02 -- Beratungsprotokoll: 8-stellige Pruefsumme statt voller
  SHA-256; allgemeine Regel ``internal_id_hits`` (keine UUID, keine Hex-Folge ab
  16 Zeichen) -- auch vom KN3-B-Kunden-PDF-Waechter genutzt.
* Punkt 5 -- ``_suitability_block`` (Berater-Fassung): Ausnahmekunden nicht
  gruen/«konform», gleiche Funktion.
"""
from __future__ import annotations

import io
import re
from datetime import date
from types import SimpleNamespace

import pytest

from services.pdf.components.compliance_audit import customer_suitability_text

DECISION_ID = "3f1c2b9a-7d4e-4c21-9a8b-0c5d6e7f8a9b"
DECISION_HASH = "9b2e4f6a8c0d1e3f5a7b9c1d3e5f7a9b2c4d6e8f0a1b3c5d7e9f1a2b4c6d8e0f"

# -- allgemeine Regel fuer Kunden-PDFs (auch KN3-B-Waechter) -----------------

_INTERNAL_ID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"  # UUID
    r"|\b[0-9a-fA-F]{16,}\b"                                                          # Hash/Hex >= 16
)


def internal_id_hits(text: str) -> list[str]:
    """UUIDs und Hex-Folgen ab 16 Zeichen (volle Hashes, interne Kennungen)."""
    return _INTERNAL_ID.findall(" ".join(str(text).split()))


def test_internal_id_rule_detects_the_old_output():
    """Gegenprobe mit den Befund-Texten (H-181-Pruefung, gerendert auf 4eff5d0b)."""
    old = [
        "Nachweis – Definition 2b875932aa31c0de9f5b1e7a4c2d8f6b0e3a5c7d9f1b3d5e7a9c1e3f5a87f8fd · "
        "Erfassung 1de748de",
        f"Override-Entscheid {DECISION_ID} · SHA-256 {DECISION_HASH} · Hash verifiziert",
        "Datenstand: Depot-Snapshot 0f3e2d1c-4b5a-4968-8776-655443322110 (Hash 4154c79c0a1b2c3d)",
    ]
    for line in old:
        assert internal_id_hits(line), line
    clean = ("Datenstand: Bestandsstichtag 21.11.2026, Prüfsumme 4154c79c. Entscheid-Nr. 3f1c2b9a · "
             "Nachweis geprüft. CHF 1'227'410, M-2026-0001, Seite 3 von 12, ISIN CH0012345678")
    assert internal_id_hits(clean) == []


def test_customer_reference_text_shortens_ids_and_hashes():
    from core.customer_terms import customer_reference_text, short_reference

    out = customer_reference_text(f"{DECISION_ID} · SHA-256 {DECISION_HASH} · Hash verifiziert")
    assert out == f"{DECISION_ID[:8]} · Prüfsumme {DECISION_HASH[:8]} · Hash verifiziert"
    assert internal_id_hits(out) == []
    assert short_reference(None) == "-" and short_reference(DECISION_HASH) == DECISION_HASH[:8]


# -- Hilfen --------------------------------------------------------------------


def _audit(mandate_type: str, classification: str | None = None) -> dict:
    """Echter Audit (services.suitability_audit) fuer die Ausnahmepfade."""
    from services.suitability_audit import audit_mandate_suitability

    class _NoLogs:
        def query(self, *_a, **_k):
            raise RuntimeError("keine Datenbank im Unit-Test")

    mandate = SimpleNamespace(id="m-kn7", mandate_type=mandate_type,
                              client=SimpleNamespace(client_classification=classification or "Privatkunde"))
    return audit_mandate_suitability(_NoLogs(), mandate, include_sustainability_preference=False)


def _flat(pdf: bytes) -> str:
    from pypdf import PdfReader

    return " ".join(" ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages).split())


def _ctx():
    from services.pdf.base import PDFContext

    return PDFContext(mandate_name="Kundin Beispiel", advisor_name="Berater Beispiel",
                      advisor_org="Beratungshaus", report_date=date(2026, 11, 21), audit_hash="kn7")


# Alle Pruefgrundlagen: (Name, suitability_compliance-Payload)
BASES = {
    "geeignetheit_ok": {"suitability_basis": "risk_assessment", "is_compliant": True},
    "geeignetheit_fehlt": {"suitability_basis": "risk_assessment", "is_compliant": False},
    "angemessenheit_ok": {"suitability_basis": "appropriateness", "is_compliant": True},
    "angemessenheit_fehlt": {"suitability_basis": "appropriateness", "is_compliant": False},
    "execution_only": "AUDIT:Execution-only",
    "institutionell": "AUDIT:Institutionell",
    "unbekannt": {"suitability_basis": None, "is_compliant": True},
    "fremd": {"suitability_basis": "irgendwas", "is_compliant": True},
    "degraded": {"suitability_basis": "degraded", "audit_degraded": True, "is_compliant": None},
}


def _basis(name: str) -> dict:
    spec = BASES[name]
    if spec == "AUDIT:Execution-only":
        return _audit("Execution-only")
    if spec == "AUDIT:Institutionell":
        return _audit("Anlageberatung", "Institutioneller Kunde")
    return dict(spec)


# -- Punkt 1: Beratungsentscheid ----------------------------------------------

CHECK_CLAIM = "die Geeignetheit geprüft"
ACK_CLAIM = "Die Geeignetheit der Empfehlung"


def _signoff_pdf(suitability: dict) -> str:
    from services.pdf.base import ContractSignoffData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    data = ContractSignoffData(
        mandate_number="M-KN7", advisory_wealth_rappen=500_000_00, risk_profile_label="Ausgewogen",
        target_allocation_bps={"equities": 5000, "bonds": 4500, "liquidity": 500},
        bucket_bands_bps={"equities": (4500, 5500), "bonds": (4000, 5000), "liquidity": (200, 1000)},
        suitability_basis=suitability.get("suitability_basis"),
        suitability_is_compliant=suitability.get("is_compliant"),
        suitability_audit_degraded=bool(suitability.get("audit_degraded")),
    )
    return _flat(ReportLabRenderer().render_contract_signoff(_ctx(), data))


@pytest.mark.parametrize("name", sorted(BASES))
def test_contract_signoff_confirms_only_the_check_that_took_place(name):
    suitability = _basis(name)
    text = _signoff_pdf(suitability)
    status, customer_text = customer_suitability_text(suitability)
    if name == "geeignetheit_ok":
        assert CHECK_CLAIM in text and ACK_CLAIM in text
        return
    assert CHECK_CLAIM not in text and ACK_CLAIM not in text, name
    if name == "angemessenheit_ok":
        assert "die Angemessenheit geprüft" in text
        return
    # Keine (gueltige) Geeignetheitspruefung: der Grund steht im Dokument --
    # derselbe Kundentext wie in Sektion 19 des Advisory-Reports.
    assert " ".join(customer_text.split()) in text, (name, status)


def test_contract_signoff_exempt_clients_from_real_audit():
    for suitability, phrase in ((_audit("Execution-only"), "reine Auftragsausführung"),
                                (_audit("Anlageberatung", "Institutioneller Kunde"), "institutioneller Kunde")):
        text = _signoff_pdf(suitability)
        assert CHECK_CLAIM not in text and ACK_CLAIM not in text
        assert "Keine Geeignetheit" in text and phrase in text


def test_contract_signoff_builder_passes_the_audit_basis(monkeypatch):
    """Verdrahtung: der Router liest die Pruefgrundlage aus demselben Audit wie
    Sektion 19 (services.pdf.documents.advisory_report.suitability_compliance_for_mandate
    -> services.advisory_report._build_suitability_compliance)."""
    import routers.pdf_reports as pr

    strategy = SimpleNamespace(
        recommendation_status=None, optimizer_reasoning="Ausrichtung", allocation_preferences={},
        advisory_wealth_rappen=1, risk_profile_label="Ausgewogen", risk_is_overridden=False,
        risk_override_reason=None, limiting_factor=None, target_allocation_bps={}, bucket_bands_bps={},
        products=[], band_house_deviations=[], band_house_profile=None, band_deviation_reason=None,
    )
    monkeypatch.setattr(pr, "_build_anlagestrategie_data", lambda *_a, **_k: strategy)
    monkeypatch.setattr(pr, "_build_protokoll_data",
                        lambda *_a, **_k: SimpleNamespace(entries=[], latest_recommendation_summary=None))
    monkeypatch.setattr(pr, "_latest_target_allocation", lambda *_a, **_k: None)
    monkeypatch.setattr(pr, "suitability_compliance_for_mandate", lambda *_a, **_k: _audit("Execution-only"))
    data = pr._build_contract_signoff_data(SimpleNamespace(mandate_number="M-1"), None)
    assert (data.suitability_basis, data.suitability_is_compliant, data.suitability_audit_degraded) == (
        "execution_only_exempt", True, False)


# -- Punkt 2 / N-928-01: Sektion 19 vs. Sektion 27 ----------------------------

_OK = "liegt die erforderliche Geeignetheitsprüfung vor"
_MISSING = ("Noch keine Eignungsprüfung dokumentiert", "Noch keine gültige Eignungsprüfung",
            "fehlt eine gültige Geeignetheitsprüfung")
_NONE_DONE = ("Keine Geeignetheitsprüfung durchgeführt", "Keine Geeignetheits- oder Angemessenheitsprüfung",
              "Keine Eignungsprüfung vorgesehen")
_NOT_CONFIRMED = ("Prüfgrundlage nicht dokumentiert", "Prüfung nicht möglich")


def suitability_contradictions(flat: str) -> list[str]:
    """Widerspruechliche Aussagen zur Eignungspruefung im selben Kunden-PDF."""
    has = lambda phrases: any(p in flat for p in phrases)  # noqa: E731
    found = []
    if _OK in flat and has(_MISSING):
        found.append("liegt vor + fehlt/noch keine")
    if _OK in flat and has(_NONE_DONE):
        found.append("liegt vor + keine durchgeführt")
    if "Eignung gegeben" in flat and has(_MISSING + _NONE_DONE + _NOT_CONFIRMED):
        found.append("Eignung gegeben + keine/fehlende/unbestätigte Prüfung")
    if has(_NONE_DONE) and ("durchzuführen" in flat or has(_MISSING)):
        found.append("keine vorgesehen + Prüfung verlangt")
    return found


def test_contradiction_rule_detects_the_old_output():
    """Gegenprobe: genau der Befund N-928-01 (verzehr/advisory-report.txt)."""
    old = ("Noch keine Eignungsprüfung dokumentiert Vor der Umsetzung der Anlagestrategie ist eine "
           "FINMA-konforme Eignungsprüfung (Suitability nach FIDLEG) durchzuführen und im System zu "
           "hinterlegen. … Für die dokumentierten Beratungen liegt die erforderliche Geeignetheitsprüfung vor.")
    assert suitability_contradictions(old)
    exempt_old = ("Noch keine Eignungsprüfung dokumentiert … durchzuführen … Keine Geeignetheits- oder "
                  "Angemessenheitsprüfung durchgeführt")
    assert suitability_contradictions(exempt_old)


def _advisory_text(suitability: dict, *, with_check: bool) -> str:
    from services.pdf.documents.advisory_report import render_advisory_report_pdf_from_payload
    from tests.test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    payload["suitability_compliance"] = suitability
    if not with_check:
        payload["suitability_summary"] = {"has_check": False}
    return _flat(render_advisory_report_pdf_from_payload(payload))


@pytest.mark.parametrize("with_check", [False, True], ids=["ohne_pruefdatensatz", "mit_pruefdatensatz"])
@pytest.mark.parametrize("name", sorted(BASES))
def test_sections_19_and_27_never_contradict(name, with_check):
    suitability = _basis(name)
    status, customer_text = customer_suitability_text(suitability)
    text = _advisory_text(suitability, with_check=with_check)
    assert suitability_contradictions(text) == [], (name, with_check)
    assert "im System zu hinterlegen" not in text and "Suitability nach FIDLEG" not in text
    if with_check:
        # «Eignung gegeben» nur, wenn Sektion 19 die Pruefung bestaetigt.
        assert ("Eignung gegeben" in text) == (status == "ok"), (name, status)
    else:
        # Leerzustand: dieselbe Kundenaussage wie Sektion 19 (mindestens zweimal).
        assert text.count(" ".join(customer_text.split())) >= 2, (name, status)


# -- Punkt 5: Berater-Fassung --------------------------------------------------


def _advisor_text(suitability: dict) -> str:
    from tests.test_pdf_compliance_audit_section import _advisor_text as render
    from tests.test_advisory_report_pdf import _make_minimal_payload

    payload = _make_minimal_payload()
    payload["suitability_compliance"] = suitability
    return render(payload)


def test_advisor_block_never_marks_exempt_clients_green():
    for suitability in (_audit("Execution-only"), _audit("Anlageberatung", "Institutioneller Kunde")):
        text = _advisor_text(suitability)
        block = text.split("Geeignetheitsprüfung", 1)[1].split("Methodology-Modelle", 1)[0]
        assert "nicht erforderlich" in block and "grün" not in block, block[:400]
    ok = _advisor_text({"suitability_basis": "risk_assessment", "is_compliant": True})
    assert "grün" in ok.split("Geeignetheitsprüfung", 1)[1].split("Methodology-Modelle", 1)[0]


# -- Punkt 3: Risikoprofil-PDF bei Override ------------------------------------


def _risk_data(**kw):
    from services.pdf.base import RisikoprofilData

    base = dict(risk_profile_label="Ausgewogen", risk_capacity_score=50, risk_tolerance_score=50,
                is_overridden=True, override_reason="Kundenwunsch nach Besprechung",
                override_client_confirmed=True, override_warning_delivered=True,
                override_decision_id=DECISION_ID, override_decision_hash=DECISION_HASH,
                override_decision_verified=True)
    base.update(kw)
    return RisikoprofilData(**base)


def _risk_pdf(data, **kw) -> str:
    from services.pdf.reportlab_renderer import ReportLabRenderer

    return _flat(ReportLabRenderer().render_risikoprofil(_ctx(), data, **kw))


def test_risk_profile_customer_pdf_shows_short_decision_number_only():
    text = _risk_pdf(_risk_data())
    compact = text.replace(" ", "")
    assert f"Entscheid-Nr. {DECISION_ID[:8]} · Nachweis geprüft" in text
    assert DECISION_ID not in compact and DECISION_HASH not in compact
    assert "SHA-256" not in text and "RiskOverrideDecisionV1" not in text and "Override-Entscheid" not in text
    assert internal_id_hits(text) == []
    unverified = _risk_pdf(_risk_data(override_decision_verified=False))
    assert "Nachweis nicht bestätigt" in unverified
    legacy = _risk_pdf(_risk_data(override_decision_id=None, override_decision_hash=None))
    assert "Kein Entscheid-Nachweis" in legacy and "RiskOverrideDecisionV1" not in legacy


def test_risk_profile_audit_version_keeps_full_reference():
    text = _risk_pdf(_risk_data(), advisor_annex=True).replace(" ", "")
    assert DECISION_ID in text and DECISION_HASH in text and "Hashverifiziert" in text


def test_risk_profile_archive_hash_input_is_unchanged():
    """Der Archiv-/Audit-Nachweis haengt an den Daten, nicht am Kundentext: die
    Daten tragen weiterhin die volle ID und den vollen Hash."""
    data = _risk_data()
    assert (data.override_decision_id, data.override_decision_hash) == (DECISION_ID, DECISION_HASH)


# -- Punkt 4 / N-928-02: Beratungsprotokoll --------------------------------------


def test_protocol_shows_eight_char_checksum_instead_of_full_hashes():
    from services.pdf.base import ProtokollData
    from services.pdf.reportlab_renderer import ReportLabRenderer

    definition, decision = "2b" * 32, "1d" * 32
    data = ProtokollData(
        mandate_number="M-KN7", entries=[],
        sustainability_lines=(("Ergebnis", "Präferenz erfasst"),
                              ("Nachweis", f"Definition {definition} · Erfassung {decision}")),
        risk_signoff_lines=(("Signoff-Referenz", f"{DECISION_ID} · SHA-256 {DECISION_HASH} · geprüft"),),
    )
    text = _flat(ReportLabRenderer().render_protokoll(_ctx(), data))
    assert f"Prüfsumme Definition {definition[:8]} · Erfassung {decision[:8]}" in text
    assert f"{DECISION_ID[:8]} · Prüfsumme {DECISION_HASH[:8]}" in text
    compact = text.replace(" ", "")
    assert definition not in compact and decision not in compact and DECISION_ID not in compact
    assert internal_id_hits(text) == []
