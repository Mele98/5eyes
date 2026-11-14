"""CCX-11 / CCX-P1: Snapshot-Fencing beim Versiegeln eines Beratungsentscheids.

Ein Envelope bindet die Hashes aller wirkenden Inputs (Effective-Input-
Manifest). Liest der Versiegelungslauf die Inputs zu Beginn (``before``) und
unmittelbar vor dem Siegel erneut (``after``), darf das Ergebnis nur eine
konsistente Sicht sein -- entweder durchgehend der alte oder durchgehend der
neue Stand, niemals eine Mischung. Eine Abweichung zwischen beiden Lesungen
heisst ``RETRY``: es wird NICHTS versiegelt (Reason-Code
``CCX_INPUT_MANIFEST_MISMATCH``), der Aufrufer muss neu lesen.

``sealed`` ist der Komponentenstand des zuletzt versiegelten Envelopes des
Mandats (falls vorhanden): eine konsistente Sicht, die ihm gleicht, ist
``OLD`` (nichts hat sich geaendert), jede andere konsistente Sicht ``NEW``.
Ohne Referenz ist jede konsistente Sicht ``NEW``.

Unbekannte Werte sind nie konsistent: ``None`` oder ein leerer Wert in einer
der beiden Lesungen ergibt ``RETRY`` (``unknown`` ist nie ``complete``).
"""
from __future__ import annotations

from typing import Any, Mapping

OLD = "OLD"
NEW = "NEW"
RETRY = "RETRY"


def _known(view: Mapping[str, Any]) -> bool:
    return bool(view) and all(value is not None and value != "" for value in view.values())


def classify_snapshot_consistency(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    sealed: Mapping[str, Any] | None = None,
) -> str:
    """``OLD`` | ``NEW`` | ``RETRY`` fuer zwei Lesungen derselben Abhaengigkeiten."""
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return RETRY
    if not _known(before) or not _known(after):
        return RETRY
    if set(before) != set(after) or any(before[key] != after[key] for key in before):
        return RETRY
    if sealed is not None and set(sealed) == set(after) and all(
        sealed[key] == after[key] for key in after
    ):
        return OLD
    return NEW


__all__ = ["NEW", "OLD", "RETRY", "classify_snapshot_consistency"]
