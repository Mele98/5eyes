"""PREF-CONTEXT-001: der Praeferenz-Snapshot der Soll-Allokation ist die
einzige Praeferenzquelle fuer die Produktselektion.

Befund (ESG-Architektur-Review 18.10.2026, C1/I): ``generate_recommendation_run``
normalisierte bisher die REQUEST-Praeferenzen und nutzte sie fuer Matcher,
Score, ESG-Gap-Hinweis, Themen-Offenlegung und Konzentrationslimits, waehrend
der TA-Rebuild den gespeicherten Snapshot (``TargetAllocation.preferences_json``,
im ``allocation_context_hash`` gebunden) las. Eine TA mit ``policy.esg=impact``
plus Recommendation ohne Request-Praeferenzen erzeugte so Produkte OHNE
ESG-Filter, das PDF zeigte trotzdem das Kriterium aus dem Snapshot.

Vertrag (CIO-Entscheid 2026-10-18):

* Aktuelle TA MIT Snapshot -> der Snapshot ist die einzige Quelle.
  ``preferences=None`` -> Snapshot. Ein mitgesendeter Request, der kanonisch
  (``_normalize_preferences`` + Mandats-Building-Block-Defaults,
  schluesselreihenfolge-unabhaengig) vom Snapshot abweicht ->
  :class:`PreferenceSnapshotMismatchError` (Reason-Code
  ``PREFERENCE_SNAPSHOT_MISMATCH``, HTTP 409, kein Run, keine Position).
* Legacy-TA OHNE Snapshot (``preferences_json IS NULL``) -> bisheriges
  Verhalten (Request bzw. Defaults), aber mit sichtbarer Run-Warnung
  ``PREFERENCE_SNAPSHOT_LEGACY``.
* TA-Neuberechnung mit ``preferences=None`` (React ``generateAllocation``
  sendet ``{preferences: null}``) uebernimmt die Praeferenzen der aktuellen
  TA statt sie still durch Defaults zu ersetzen ("Neuberechnung = gleiche
  Praeferenzen"). Wer bewusst auf Defaults zuruecksetzen will, sendet
  explizit ``{}``.

Bewusst ohne Schema-/Migrationsaenderung; Run-Hashes folgen separat (PR-E).
"""
from __future__ import annotations

import json

PREFERENCE_SNAPSHOT_MISMATCH = "PREFERENCE_SNAPSHOT_MISMATCH"
PREFERENCE_SNAPSHOT_LEGACY = "PREFERENCE_SNAPSHOT_LEGACY"

LEGACY_SNAPSHOT_WARNING = (
    f"{PREFERENCE_SNAPSHOT_LEGACY}: Die Soll-Allokation stammt aus einer Phase "
    "ohne gespeicherten Praeferenz-Snapshot. Die Produktselektion nutzt die mit "
    "dieser Anfrage gesendeten Praeferenzen (bzw. Standardwerte) und ist nicht "
    "an die Strategie gebunden. Bitte Strategie neu berechnen."
)
INHERITED_PREFERENCES_NOTE = (
    "Neuberechnung ohne mitgesendete Praeferenzen: die festgehaltenen "
    "Praeferenzen der bisherigen Soll-Allokation (inkl. ESG-Vorgaben) wurden "
    "unveraendert uebernommen."
)


class PreferenceSnapshotMismatchError(ValueError):
    """Request-Praeferenzen weichen vom verifizierten TA-Snapshot ab."""

    reason_code = PREFERENCE_SNAPSHOT_MISMATCH

    def __init__(self, differing_sections: list[str]):
        self.differing_sections = list(differing_sections)
        sections = ", ".join(self.differing_sections) or "unbekannt"
        self.message = (
            "Die gesendeten Anlagepraeferenzen weichen von den in der aktuellen "
            f"Soll-Allokation festgehaltenen Praeferenzen ab (Abschnitte: {sections}). "
            "Eine Empfehlung wird nur aus den Praeferenzen der Strategie erzeugt; "
            "bitte zuerst die Strategie mit den neuen Praeferenzen neu berechnen."
        )
        super().__init__(f"{PREFERENCE_SNAPSHOT_MISMATCH}: {self.message}")

    def http_detail(self) -> dict:
        return {
            "reason_code": self.reason_code,
            "message": self.message,
            "differing_sections": self.differing_sections,
        }


def effective_preferences(preferences: dict | None, mandate) -> dict:
    """Kanonische, wirksame Praeferenzen: Vokabular-Validierung plus
    Mandats-Building-Block-Defaults -- exakt die Form, die
    ``generate_target_allocation`` als Snapshot persistiert."""
    from services.portfolio_engine import (
        _merge_mandate_defaults_into_prefs,
        _normalize_preferences,
    )

    return _merge_mandate_defaults_into_prefs(_normalize_preferences(preferences), mandate)


def _canonical(prefs: dict) -> str:
    return json.dumps(prefs, sort_keys=True, default=str)


def resolve_recommendation_preferences(
    allocation, request_preferences: dict | None, mandate,
) -> tuple[dict | None, str | None]:
    """Liefert ``(rohe Praeferenzen fuer Produktselektion + TA-Rebuild,
    optionale Legacy-Warnung)``. Wirft :class:`PreferenceSnapshotMismatchError`
    bei kanonischer Abweichung des Requests vom Snapshot."""
    from services.portfolio_engine import _allocation_snapshot_preferences

    snapshot = _allocation_snapshot_preferences(allocation)
    if snapshot is None:
        return request_preferences, LEGACY_SNAPSHOT_WARNING
    if request_preferences is not None:
        stored = effective_preferences(snapshot, mandate)
        sent = effective_preferences(request_preferences, mandate)
        if _canonical(stored) != _canonical(sent):
            differing = sorted(
                key for key in set(stored) | set(sent)
                if _canonical({"v": stored.get(key)}) != _canonical({"v": sent.get(key)})
            )
            raise PreferenceSnapshotMismatchError(differing)
    return snapshot, None


def inherit_current_allocation_preferences(
    db, mandate, preferences: dict | None,
) -> tuple[dict | None, bool]:
    """TA-Neuberechnung: ``None`` -> Praeferenzen der aktuellen TA (falls ein
    Snapshot existiert). Liefert ``(Praeferenzen, uebernommen?)``."""
    if preferences is not None:
        return preferences, False
    from services.portfolio_engine import (
        _allocation_snapshot_preferences,
        _current_target_allocation_or_none,
    )

    snapshot = _allocation_snapshot_preferences(
        _current_target_allocation_or_none(db, mandate.id)
    )
    if snapshot is None:
        return None, False
    return snapshot, True
