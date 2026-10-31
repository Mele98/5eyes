"""Die eine Aufloesung des Laendercodes (Design 80, Abschnitt 2.4).

``resolve_pack(mandate)`` liefert ein eingefrorenes ``ResolvedPack``. Der Code
ist in X1/X2 exakt der Wert der heutigen Formel

    getattr(mandate, "jurisdiction", None) or "CH"

(siehe ``services/jurisdiction/resolve.py::resolve_mandate_jurisdiction``):
keine Normalisierung, kein ``strip``/``upper``, unbekannte Codes bleiben wie
sie sind (``pack=None``). Der Rueckgriff auf ``"CH"`` ist ausschliesslich die
Altsemantik "NULL = CH". Fail-closed fuer unbekannte oder nicht freigegebene
Codes kommt erst mit X14.

Reihenfolge: ``Mandate.jurisdiction`` (bzw. ``code=``) -> optional
``Tenant.home_jurisdiction`` (nur wenn ``tenant`` uebergeben wird; deckt sich
mit ``routers/mandates.py``) -> ``"CH"``.

Dieses Modul importiert kein Backend-Modul ausserhalb von ``jurisdictions``.
"""
from __future__ import annotations

from typing import Any

from jurisdictions.api import ResolvedPack
from jurisdictions.registry import PackRegistry, default_registry

LEGACY_DEFAULT_CODE = "CH"

_UNSET: Any = object()


def resolve_pack(
    mandate: Any = None,
    *,
    code: Any = _UNSET,
    tenant: Any = None,
    registry: PackRegistry | None = None,
) -> ResolvedPack:
    """Loest den Laendercode auf und haengt den registrierten Pack an.

    - ``mandate``: Objekt mit optionalem Attribut ``jurisdiction``.
    - ``code``: expliziter Rohwert statt ``mandate.jurisdiction`` (z.B.
      ``product.jurisdiction``); ``None``/``""`` gelten wie NULL.
    - ``tenant``: optionaler Tenant; dessen ``home_jurisdiction`` greift nur,
      wenn der Rohwert leer ist.
    """
    if code is _UNSET:
        raw = getattr(mandate, "jurisdiction", None)
        source = "mandate"
    else:
        raw = code
        source = "explicit"
    if not raw and tenant is not None:
        raw = getattr(tenant, "home_jurisdiction", None)
        source = "tenant"
    if not raw:
        raw = LEGACY_DEFAULT_CODE
        source = "legacy_default"
    reg = registry if registry is not None else default_registry()
    pack = reg.latest(raw) if isinstance(raw, str) else None
    return ResolvedPack(code=raw, pack=pack, source=source)
