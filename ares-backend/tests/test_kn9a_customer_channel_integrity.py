"""KN9a (H-188-Pruefung, CTO-Entscheide): eine Integritaetsregel fuer alle
Kundenkanaele mit Beratungsprotokoll-Inhalt.

* N-934-01: Beratungsprotokoll-PDF (alle gezeigten Eintraege) und
  Beratungsentscheid (Tabelle «Beratungsinhalt») sperren wie der
  Advisory-Report: 409 ``ADVISORY_LOG_INTEGRITY_FAILED`` mit deutscher Ursache
  (Dokument und Eintrag), VOR jeder Archivierung. Gemeinsame Regel:
  ``services.advisory_log_service.assert_shown_entries_intact``.
* N-934-02: Kundenportal-Bericht: dieselbe Regel, der Kunde sieht nur die
  neutrale Meldung, der Code steht in Log und Audit.
* Folgefund zu N-934-05: der Systemeintrag der Portal-Signatur steht in den
  Kunden-PDFs in Kundensprache (kein «RiskProfileSignoffV1», «SHA-256», «Signoff»).

Gegenproben: je Kanal ohne die Pruefung -> der veraenderte Text erreicht den
Kunden (``test_counterprobe_*``).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.test_kn8_protocol_integrity_display import _payload, _service_entry

TAMPER = " Nachträglich geändert (fiktiv)."


def _tampered_entry():
    entry = _service_entry()
    entry.description = entry.description + TAMPER
    return entry


# --- gemeinsame Regel ------------------------------------------------------------


def test_shared_rule_checks_every_shown_entry_and_only_false_blocks():
    from services.advisory_log_service import AdvisoryLogIntegrityFailed, assert_shown_entries_intact

    good, legacy, bad = _service_entry(), _service_entry(), _tampered_entry()
    legacy.integrity_hash = None
    bad.id = "kn9a-bad"
    assert_shown_entries_intact([good, legacy], document="Beratungsprotokoll")
    assert_shown_entries_intact([], document="Beratungsprotokoll")
    with pytest.raises(AdvisoryLogIntegrityFailed) as exc:
        assert_shown_entries_intact([good, legacy, bad], document="Beratungsprotokoll")
    assert exc.value.entry_id == "kn9a-bad"
    message = str(exc.value)
    assert message.startswith("Beratungsprotokoll kann nicht als Kunden-PDF erzeugt werden: Die Prüfsumme "
                              "des Beratungsprotokoll-Eintrags vom 20.11.2026 («Jahresgespräch (fiktiv)»)")
    assert "verändert oder ist beschädigt" in message
    for word in ("Hash", "integrity", "False", "des letzten"):
        assert word not in message
    # Serialisierte Eintraege (Report/Portal) nach derselben Regel.
    with pytest.raises(AdvisoryLogIntegrityFailed):
        assert_shown_entries_intact([{"id": "x", "integrity_verified": False}], document="Advisory-Report")
    assert_shown_entries_intact([{"integrity_verified": None}, {"integrity_verified": True}],
                                document="Advisory-Report")


def test_advisory_report_keeps_its_message_and_uses_the_same_rule():
    from services.advisory_log_service import advisory_log_integrity_message
    from services.pdf.documents.advisory_report import (
        ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE, AdvisoryLogIntegrityFailed, assert_advisory_log_integrity)

    assert ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE == advisory_log_integrity_message("Advisory-Report")
    assert "des letzten Beratungsprotokoll-Eintrags" in ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE
    with pytest.raises(AdvisoryLogIntegrityFailed) as exc:
        assert_advisory_log_integrity(_payload(False))
    assert str(exc.value) == ADVISORY_LOG_INTEGRITY_FAILED_MESSAGE


# --- N-934-01: Beratungsprotokoll / Beratungsentscheid ------------------------------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def all(self):
        return list(self._rows)


def _fake_db(rows):
    from models.review import AdvisoryLog

    return SimpleNamespace(query=lambda model, *a: _FakeQuery(rows if model is AdvisoryLog else []))


@pytest.mark.parametrize("document", ["Beratungsprotokoll", "Beratungsentscheid"])
def test_protocol_data_refuses_a_tampered_entry(monkeypatch, document):
    """Echte Kette: Hash beim Erfassen -> Zeile veraendert -> _build_protokoll_data
    wirft (das ``except Exception`` darf die Sperre nicht schlucken)."""
    import routers.pdf_reports as pr
    from services.advisory_log_service import AdvisoryLogIntegrityFailed

    monkeypatch.setattr(pr, "_latest_target_allocation", lambda *a, **k: None)
    rows = [_service_entry(), _tampered_entry()]
    with pytest.raises(AdvisoryLogIntegrityFailed) as exc:
        pr._build_protokoll_data(SimpleNamespace(id="m-kn9a"), _fake_db(rows), document=document)
    assert str(exc.value).startswith(f"{document} kann nicht als Kunden-PDF erzeugt werden")


def test_counterprobe_without_the_rule_the_tampered_text_reaches_the_protocol(monkeypatch):
    """Gegenprobe: ohne Pruefung geht der veraenderte Text in die PDF-Eintraege
    (Befund N-934-01). Abgefangen an der Stelle, die die Eintraege baut."""
    import routers.pdf_reports as pr
    from services.advisory_log_service import customer_protocol_entry

    monkeypatch.setattr(pr, "_latest_target_allocation", lambda *a, **k: None)
    monkeypatch.setattr(pr, "assert_shown_entries_intact", lambda *a, **k: None)
    seen = []

    class _Stop(Exception):
        pass

    def _record(row):
        seen.append(customer_protocol_entry(row))
        raise _Stop

    monkeypatch.setattr(pr, "customer_protocol_entry", _record)
    monkeypatch.setattr(pr, "resolve_current_recommendation_run", lambda *a, **k: None)
    try:
        pr._build_protokoll_data(SimpleNamespace(id="m-kn9a"), _fake_db([_tampered_entry()]))
    except Exception:  # noqa: BLE001 -- _Stop wird vom Builder geloggt oder durchgereicht
        pass
    assert seen and TAMPER.strip() in seen[0]["description"]


def _neutral_pdf_gates(monkeypatch, pr):
    for name in ("_assert_client_pdf_kyc_review", "_assert_client_pdf_fx_basis",
                 "_assert_client_pdf_signoff", "_assert_client_pdf_cma_hold"):
        monkeypatch.setattr(pr, name, lambda *a, **k: None)
    monkeypatch.setattr(pr, "get_mandate_for_user_or_404",
                        lambda mid, db, user: SimpleNamespace(id=mid, mandate_number="M-KN9A"))
    monkeypatch.setattr(pr, "_build_pdf_context", lambda *a, **k: SimpleNamespace(watermark_mode="none"))
    monkeypatch.setattr(pr, "_mark_unpublished", lambda ctx, db, mandate: ctx)
    archived = []
    monkeypatch.setattr(pr, "_archive_final", lambda *a, **k: archived.append(k))
    monkeypatch.setattr(pr, "_archive_final_unbound", lambda *a, **k: archived.append(k))
    return archived


def _raise_tampered(document):
    def _raise(*_a, **_k):
        from services.advisory_log_service import AdvisoryLogIntegrityFailed

        raise AdvisoryLogIntegrityFailed("log-kn9a", document=document,
                                         entry_label="des Beratungsprotokoll-Eintrags vom 20.11.2026")
    return _raise


def test_protocol_route_answers_409_before_archiving(monkeypatch):
    import routers.pdf_reports as pr

    archived = _neutral_pdf_gates(monkeypatch, pr)
    monkeypatch.setattr(pr, "_build_protokoll_data", _raise_tampered("Beratungsprotokoll"))
    with pytest.raises(HTTPException) as exc:
        pr.get_protokoll_pdf("m-kn9a", request=SimpleNamespace(), db=None,
                             current_user=SimpleNamespace(id="u"))
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "ADVISORY_LOG_INTEGRITY_FAILED"
    assert exc.value.detail["advisory_log_id"] == "log-kn9a"
    assert exc.value.detail["message"].startswith("Beratungsprotokoll kann nicht als Kunden-PDF erzeugt werden")
    assert archived == []


def test_contract_signoff_route_answers_409(monkeypatch):
    import routers.pdf_reports as pr

    archived = _neutral_pdf_gates(monkeypatch, pr)
    monkeypatch.setattr(pr, "_build_contract_signoff_data", _raise_tampered("Beratungsentscheid"))
    with pytest.raises(HTTPException) as exc:
        pr.get_contract_signoff_pdf("m-kn9a", db=None, current_user=SimpleNamespace(id="u"))
    assert exc.value.status_code == 409
    assert exc.value.detail["reason_code"] == "ADVISORY_LOG_INTEGRITY_FAILED"
    assert exc.value.detail["message"].startswith("Beratungsentscheid kann nicht als Kunden-PDF erzeugt werden")
    assert archived == []


def test_reason_code_is_catalogued():
    from core.reason_codes import ReasonCode

    assert ReasonCode.ADVISORY_LOG_INTEGRITY_FAILED.value == "ADVISORY_LOG_INTEGRITY_FAILED"


# --- N-934-02: Kundenportal ---------------------------------------------------------


def _portal(monkeypatch, report):
    import routers.client_portal as cp

    mandate = SimpleNamespace(id="m-kn9a", client_id="c-kn9a")
    client = SimpleNamespace(id="c-kn9a")
    monkeypatch.setattr(cp, "get_linked_client_for_user_or_404", lambda user, db: client)
    monkeypatch.setattr(cp, "_assert_portal_report_releasable", lambda *a, **k: None)
    monkeypatch.setattr(cp, "compute_advisory_report", lambda db, m, client_facing=False: report)
    audits = []
    monkeypatch.setattr(cp, "audit_log", lambda db, **k: audits.append(k))
    commits = []
    db = SimpleNamespace(query=lambda *a: SimpleNamespace(filter=lambda *a, **k: SimpleNamespace(first=lambda: mandate)),
                         commit=lambda: commits.append(1))
    user = SimpleNamespace(id="u-client", full_name="Kunde (fiktiv)", username="kunde")
    return cp, db, user, audits, commits


def _tampered_report():
    from services.advisory_log_service import serialize_response

    report = _payload()
    report["beratungsprotokoll"]["latest_entry"] = serialize_response(_tampered_entry())
    return report


def test_portal_blocks_a_tampered_entry_with_the_neutral_message(monkeypatch):
    from services.recommendation_release_gate import CLIENT_PORTAL_UNAVAILABLE_MESSAGE

    cp, db, user, audits, commits = _portal(monkeypatch, _tampered_report())
    with pytest.raises(HTTPException) as exc:
        cp.client_portal_mandate_report("m-kn9a", db=db, current_user=user)
    assert exc.value.status_code == 409
    assert exc.value.detail == CLIENT_PORTAL_UNAVAILABLE_MESSAGE
    text = json.dumps(exc.value.detail, ensure_ascii=False)
    for word in ("ADVISORY_LOG", "Prüfsumme", "verändert", TAMPER.strip()):
        assert word not in text
    # Code nur im Audit.
    assert [a["new_value"] for a in audits] == ["ADVISORY_LOG_INTEGRITY_FAILED"]
    assert audits[0]["field_name"] == "client_portal_report_blocked" and commits


def test_portal_delivers_an_intact_report(monkeypatch):
    from services.advisory_log_service import serialize_response

    report = _payload()
    report["beratungsprotokoll"]["latest_entry"] = serialize_response(_service_entry())
    cp, db, user, audits, _ = _portal(monkeypatch, report)
    out = cp.client_portal_mandate_report("m-kn9a", db=db, current_user=user)
    assert out["beratungsprotokoll"]["latest_entry"]["integrity_verified"] is True
    assert audits == []


def test_counterprobe_portal_without_the_rule_delivers_the_tampered_text(monkeypatch):
    cp, db, user, _, _ = _portal(monkeypatch, _tampered_report())
    monkeypatch.setattr(cp, "assert_report_advisory_log_integrity", lambda *a, **k: None)
    out = cp.client_portal_mandate_report("m-kn9a", db=db, current_user=user)
    assert TAMPER.strip() in out["beratungsprotokoll"]["latest_entry"]["description"]


# --- Folgefund N-934-05: Systemeintrag der Portal-Signatur in Kundensprache ------------


def test_signoff_system_entry_is_shown_in_customer_language():
    from services import risk_profile_signoff as rs
    from services.advisory_log_service import (
        CUSTOMER_SIGNOFF_ENTRY_TEXT, RISK_PROFILE_SIGNOFF_SYSTEM_EVENT, customer_protocol_entry)

    assert RISK_PROFILE_SIGNOFF_SYSTEM_EVENT == rs.ADVISORY_SYSTEM_EVENT
    signoff = SimpleNamespace(
        effective_profile="Ausgewogen", assessment_id="a" * 36, assessment_version=2,
        method=rs.METHOD_PORTAL, id="b" * 36, signoff_hash="c" * 64,
        override_binding=rs.BINDING_NO_OVERRIDE, override_decision_id=None, override_decision_hash=None)
    raw = SimpleNamespace(entry_date="2026-11-21", entry_type="Eignungsprüfung",
                          title="Risikoprofil-Signoff (Version 2)",
                          description=rs.advisory_log_description(signoff), decision=None,
                          status="Empfohlen", system_event=rs.ADVISORY_SYSTEM_EVENT)
    view = customer_protocol_entry(raw)
    shown = " ".join(str(v) for v in view.values())
    assert view["title"] == "Signatur des Risikoprofils"
    assert view["description"] == CUSTOMER_SIGNOFF_ENTRY_TEXT
    for word in ("signoff", "sha-256", "hash", "override", "riskprofile", "systemeintrag"):
        assert word not in shown.lower(), word
    # Gegenprobe: ohne Kennzeichnung bleibt der Rohtext (genau das war der Fund).
    raw.system_event = None
    assert "RiskProfileSignoffV1" in customer_protocol_entry(raw)["description"]
