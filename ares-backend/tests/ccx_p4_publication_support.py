"""CCX-P4: Testhilfe fuer Kanal-Tests, die VOR P4 entstanden sind.

Diese Tests pruefen andere Gates (Retro, KYC, Risikobudget, ESG, Idempotenz,
Handelsliste ...) mit Laeufen, die ohne echten Beratungsentscheid bzw. ohne
Publikation erzeugt werden. Der P4-Publish-Gate selbst ist in
``tests/test_ccx_p4_allocation_publish.py`` gegen den ECHTEN Zustand (Envelope,
Pointer, Approval-Hash) belegt -- dort wird nichts ersetzt.

``assume_published_allocation`` ersetzt in genau diesen Altbestands-Tests nur
die Publikations-Abfrage der Kanaele durch "die aktuelle Soll-Allokation ist
publiziert". Alle uebrigen Gates laufen unveraendert. Neue Tests duerfen die
Hilfe nicht verwenden, um den Gate zu umgehen (Waechter:
``test_publication_bypass_is_limited_to_the_documented_legacy_files``).
"""
from __future__ import annotations

import sys

# H12 (Codex CTO-Entscheid c): nur im Testlauf importierbar. Der Produktivpfad
# importiert das Paket ``tests`` nie (Waechter in tests/test_h12_ccx_hygiene.py),
# PyInstaller sammelt es nicht ein; diese Sperre greift zusaetzlich, falls die
# Datei doch neben dem Backend liegt.
if "pytest" not in sys.modules:  # pragma: no cover - im Testlauf immer geladen
    raise ImportError("tests.ccx_p4_publication_support ist eine reine Testhilfe (nur unter pytest).")

import pytest  # noqa: E402

# Altbestand, abschliessend. Neue Eintraege nur mit Begruendung im Handoff.
LEGACY_CHANNEL_TEST_FILES = frozenset({
    "test_audit_perm_hardening.py",
    "test_audit_quick_fixes.py",
    "test_cert_handoff_execution_001_reproducers.py",
    "test_data_classification_gate_coverage_2026_09_21.py",
    "test_handoff_new_product_zero_holding.py",
    "test_handoff_preview_parity_and_cash.py",
    "test_portfolio_handoff.py",
    "test_provisional_warning_json_and_client_portal.py",
    "test_runtime_contracts.py",
    "test_sustainability_e2a_contract.py",
    "test_sustainability_e2b_offer_and_floor.py",
    "test_zero_strategy_base_n858_11.py",
})


def _published_state(db, mandate):
    from services.allocation_publication_gate import (
        STATUS_PUBLISHED,
        PublicationState,
        current_target_allocation,
    )

    current = current_target_allocation(db, str(mandate.id))
    return PublicationState(STATUS_PUBLISHED, target_allocation_id=str(current.id) if current else None)


@pytest.fixture()
def assume_published_allocation(monkeypatch):
    import routers.client_portal as client_portal
    import routers.pdf_reports as pdf_reports
    import routers.portfolio_handoff as portfolio_handoff
    import routers.snapshots as snapshots

    def require(db, mandate, **_kw):
        return _published_state(db, mandate)

    monkeypatch.setattr(portfolio_handoff, "require_published_allocation", require)
    monkeypatch.setattr(snapshots, "require_published_allocation", require)
    monkeypatch.setattr(snapshots, "published_allocation_matches_snapshot", lambda *_a, **_k: True)
    monkeypatch.setattr(pdf_reports, "customer_document_watermark", lambda *_a, **_k: None)
    monkeypatch.setattr(client_portal, "customer_document_watermark", lambda *_a, **_k: None)
    # CCX P5: derselbe Altbestand ersetzt auch das Kanal-Gate (es baut auf der
    # Publikation auf); der P5-Gate selbst ist in tests/test_ccx_p5_channel_
    # envelope.py gegen den echten Zustand belegt.
    from services.allocation_publication_gate import ChannelDecision

    monkeypatch.setattr(pdf_reports, "evaluate_channel_envelope", lambda *_a, **_k: ChannelDecision(applicable=False))
    monkeypatch.setattr(client_portal, "evaluate_channel_envelope", lambda *_a, **_k: ChannelDecision(applicable=False))
    monkeypatch.setattr(portfolio_handoff, "require_channel_envelope",
                        lambda *_a, **_k: ChannelDecision(applicable=False))
    monkeypatch.setattr(portfolio_handoff, "record_channel_publication", lambda *_a, **_k: None)
    _bypass_signature_envelope(monkeypatch)
    yield


def _bypass_signature_envelope(monkeypatch):
    import routers.onsite_signature as onsite
    import routers.review as review

    monkeypatch.setattr(review, "require_signature_envelope", lambda *_a, **_k: None)
    monkeypatch.setattr(onsite, "require_signature_envelope", lambda *_a, **_k: None)


@pytest.fixture()
def assume_signable_decision(monkeypatch):
    """CCX P5: nur fuer den Altbestand dieser Dateien -- Signatur-Tests, die
    andere Gates (Signatur-Unveraenderlichkeit, Praeferenzbindung, ESG)
    pruefen, ersetzen das Envelope-/Artefakt-Gate der Signatur. Der P5-Gate
    selbst ist in tests/test_ccx_p5_channel_envelope.py gegen den echten
    Zustand belegt."""
    _bypass_signature_envelope(monkeypatch)
    yield
