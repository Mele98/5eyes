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

import pytest

# Altbestand, abschliessend. Neue Eintraege nur mit Begruendung im Handoff.
LEGACY_CHANNEL_TEST_FILES = frozenset()


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
    yield
