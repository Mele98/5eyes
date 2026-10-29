"""Austauschbare Schnittstellen der Vor-Ort-Signatur (SIGN-001).

Kein echter Provider wird hier angebunden -- die Auswahl von QES-Anbieter,
Zustellkanal (SMS/E-Mail/Portal) und verlaesslicher Zeitquelle ist ein
Owner-Entscheid. Die Produktiv-Defaults sind deshalb Null-Implementierungen,
die ehrlich "nicht konfiguriert" melden und damit jeden betroffenen Schritt
fail-closed sperren:

* :class:`NullQesProvider` -- jede QES-Pruefung ungueltig;
* :class:`NullCustomerChannel` -- keine Zustellung (Challenge-Code und
  Kundenkopie), also auch kein Zustellnachweis;
* :class:`SystemTimeSource` -- Betriebssystemuhr, als nicht verlaesslich
  gekennzeichnet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

REASON_QES_PROVIDER_NOT_CONFIGURED = "QES_PROVIDER_NOT_CONFIGURED"
REASON_CHANNEL_NOT_CONFIGURED = "CUSTOMER_CHANNEL_NOT_CONFIGURED"


@dataclass(frozen=True)
class QesVerification:
    valid: bool
    provider: str
    reason_code: str | None = None
    receipt_hash: str | None = None
    certificate_chain_hash: str | None = None
    qualified_timestamp: str | None = None
    validation_result: str | None = None


class QesProvider(Protocol):
    name: str
    configured: bool

    def verify_receipt(
        self,
        receipt: Mapping[str, Any] | None,
        *,
        document_hash: str,
        customer_id: str,
        transaction_id: str,
    ) -> QesVerification: ...


class NullQesProvider:
    name = "none"
    configured = False

    def verify_receipt(self, receipt, *, document_hash, customer_id, transaction_id) -> QesVerification:
        return QesVerification(
            valid=False,
            provider=self.name,
            reason_code=REASON_QES_PROVIDER_NOT_CONFIGURED,
        )


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    channel: str
    reference: str | None = None
    reason_code: str | None = None


class CustomerChannel(Protocol):
    """Kundeneigener Kanal: stellt den Einmalcode und die Kundenkopie zu.

    Der Code geht ausschliesslich an diesen Kanal -- nie in eine API-Antwort
    an den Berater und nie im Klartext in die Datenbank.
    """

    name: str

    def send_challenge_code(
        self,
        *,
        client_id: str,
        transaction_id: str,
        challenge_id: str,
        code: str,
        document_hash: str,
        expires_at: str,
    ) -> DeliveryResult: ...

    def send_signed_copy(
        self,
        *,
        client_id: str,
        transaction_id: str,
        document_id: str,
        document_hash: str,
        evidence_hash: str,
    ) -> DeliveryResult: ...


class NullCustomerChannel:
    name = "none"

    def send_challenge_code(self, **_kwargs) -> DeliveryResult:
        return DeliveryResult(False, self.name, reason_code=REASON_CHANNEL_NOT_CONFIGURED)

    def send_signed_copy(self, **_kwargs) -> DeliveryResult:
        return DeliveryResult(False, self.name, reason_code=REASON_CHANNEL_NOT_CONFIGURED)


@dataclass(frozen=True)
class TimeReading:
    instant: datetime
    source: str
    timezone: str
    reliable: bool


class TimeSource(Protocol):
    def now(self) -> TimeReading: ...


class SystemTimeSource:
    """Betriebssystemuhr -- ohne Synchronisationsnachweis nicht verlaesslich."""

    source = "os_clock_unverified"

    def now(self) -> TimeReading:
        return TimeReading(
            instant=datetime.now(timezone.utc),
            source=self.source,
            timezone="UTC",
            reliable=False,
        )
