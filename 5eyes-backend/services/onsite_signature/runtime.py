"""Laufzeit-Verdrahtung der Vor-Ort-Signatur (SIGN-001).

Produktiv: Policy aus der Datendatei und Null-Provider (kein QES-Anbieter,
kein Kundenkanal, keine verlaessliche Zeitquelle ausgewaehlt). Solange der
Owner nichts anderes anbindet, ist der Ablauf damit fail-closed gesperrt.
Tests ersetzen ``get_onsite_signature_runtime`` per FastAPI-Dependency-Override.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.onsite_signature.policy import OnsiteSignaturePolicy, load_policy
from services.onsite_signature.providers import (
    CustomerChannel,
    NullCustomerChannel,
    NullQesProvider,
    QesProvider,
    SystemTimeSource,
    TimeSource,
)


@dataclass(frozen=True)
class OnsiteSignatureRuntime:
    policy: OnsiteSignaturePolicy
    time_source: TimeSource
    qes_provider: QesProvider
    channel: CustomerChannel


def get_onsite_signature_runtime() -> OnsiteSignatureRuntime:
    return OnsiteSignatureRuntime(
        policy=load_policy(),
        time_source=SystemTimeSource(),
        qes_provider=NullQesProvider(),
        channel=NullCustomerChannel(),
    )
