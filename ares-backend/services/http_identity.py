"""HTTP-Identitaet des Backends gegenueber externen Diensten.

Ein einziger Ort fuer den User-Agent ausgehender Requests
(Marktdaten-Provider, Referenzdaten, Alert-Webhook). Format laut
Rebranding-Spezifikation: ``Ares/<version>``.
"""
from __future__ import annotations

from config import settings

PRODUCT_TOKEN = "Ares"


def user_agent() -> str:
    """``Ares/<app_version>`` fuer API-Clients und Webhooks."""
    return f"{PRODUCT_TOKEN}/{settings.app_version}"


def browser_compatible_user_agent() -> str:
    """User-Agent fuer HTML-Quellen, die einen Browser-Praefix erwarten.

    Der ``Mozilla/5.0``-Praefix bleibt wie bisher erhalten; nur das
    Produkt-Token in Klammern folgt dem ``Ares/<version>``-Format.
    """
    return f"Mozilla/5.0 ({user_agent()})"
