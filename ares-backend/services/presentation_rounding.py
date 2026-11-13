"""G7: Vertragsname ``services.presentation_rounding`` (Codex-Reproducer 2026-11-11).

Die Implementierung liegt im reinen Stdlib-Blattmodul ``core.presentation_rounding``
(Architektur-Ratsche: FAN_OUT_EXEMPT_LEAVES, nur json/typing, Ganzzahl-Dezimal-
arithmetik). Dieses Modul re-exportiert sie; nur ``apportion_percent_bps`` liefert
hier -- wie im Vertrag verlangt -- ``decimal.Decimal`` statt Dezimalstrings
(identische Werte). PDF-Komponenten importieren direkt aus ``core.presentation_rounding``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from core import presentation_rounding as _core
from core.presentation_rounding import *  # noqa: F401,F403
from core.presentation_rounding import __all__  # noqa: F401


def apportion_percent_bps(values_bps: Sequence[Any], decimals: int = 1, *,
                          target_display: Any = None) -> list[Decimal]:
    """Wie ``core.presentation_rounding.apportion_percent_bps``, als ``Decimal``."""
    return [Decimal(v) for v in _core.apportion_percent_bps(values_bps, decimals, target_display=target_display)]
