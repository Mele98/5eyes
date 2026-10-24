"""ALLOC-EDITOR-STALE-001 (Codex-Reproducer PR #656): Optimistic Concurrency
fuer den manuellen Speicherpfad der Soll-Allokation und fuer
Strategie-PDFs.

Befund: ``POST /mandates/{id}/target-allocation`` ueberschrieb jeden
neueren Stand (Last-Write-Wins). Zwei Editor-Sitzungen, die denselben
Stand geladen hatten, konnten sich gegenseitig still ueberschreiben; die
zweite Begruendung bezog sich dann auf Zahlen, die der Berater nie gesehen
hatte. Ebenso konnte ein Strategie-PDF aus einem Browser-Kontext erzeugt
werden, dessen angezeigte Allokation laengst nicht mehr die aktuelle war.

Vertrag:
* Der Client sendet die ID (und optional die Version) der Allokation, die er
  bearbeitet hat. Weicht der aktuelle Stand ab -> 409
  ``... [allocation_version_conflict]``; nichts wird geschrieben.
* Existiert bereits eine aktuelle Allokation, ist das Vorgaenger-Token
  Pflicht (fail-closed) -> 409 ``... [allocation_version_missing]``.
* PDF-Endpunkte akzeptieren ``expected_allocation_id``; Abweichung -> 409.

Fehlermeldungen im Format ``message [reason_code]`` (eine Zeichenkette, damit
Monolith und React sie unveraendert anzeigen).
"""
from __future__ import annotations

from typing import Any, Optional

REASON_VERSION_CONFLICT = "allocation_version_conflict"
REASON_VERSION_MISSING = "allocation_version_missing"
REASON_REPORT_CONTEXT_STALE = "allocation_report_context_stale"


class AllocationVersionConflict(ValueError):
    """Erwarteter Vorgaenger passt nicht zum aktuellen Stand."""

    def __init__(self, message: str, reason_code: str) -> None:
        self.reason_code = reason_code
        self.message = message
        super().__init__(f"{message} [{reason_code}]")


def _norm_id(value: Any) -> str:
    return str(value or "").strip()


def assert_expected_predecessor(
    current: Any,
    expected_id: Optional[str],
    expected_version: Optional[int] = None,
) -> None:
    """Prueft das Vorgaenger-Token eines manuellen Saves gegen den (unter
    Zeilensperre geladenen) aktuellen Stand. Wirft
    :class:`AllocationVersionConflict`."""
    exp_id = _norm_id(expected_id)
    if current is None:
        if exp_id:
            raise AllocationVersionConflict(
                "Die bearbeitete Soll-Allokation ist nicht mehr aktuell "
                "(inzwischen entfernt oder ersetzt). Bitte neu laden und "
                "erneut bearbeiten.",
                REASON_VERSION_CONFLICT,
            )
        return
    if not exp_id:
        raise AllocationVersionConflict(
            "Speichern ohne Angabe der bearbeiteten Version ist nicht "
            "zulaessig, weil bereits eine aktuelle Soll-Allokation besteht. "
            "Bitte Seite neu laden und erneut speichern.",
            REASON_VERSION_MISSING,
        )
    cur_id = _norm_id(getattr(current, "id", None))
    cur_version = int(getattr(current, "version", 0) or 0)
    if exp_id != cur_id or (
        expected_version is not None and int(expected_version) != cur_version
    ):
        raise AllocationVersionConflict(
            "Die Soll-Allokation wurde inzwischen in einer anderen Sitzung "
            f"geaendert (aktuelle Version {cur_version}). Ihr Stand ist "
            "veraltet - bitte neu laden und die Aenderung erneut erfassen.",
            REASON_VERSION_CONFLICT,
        )


def assert_report_allocation_matches(
    allocation: Any, expected_id: Optional[str]
) -> None:
    """PDF-Gate: der Browser-Kontext (angezeigte Allokation) muss der
    aktuellen Allokation entsprechen. Ohne Token keine Pruefung (Archiv-/
    Direktaufrufe); die Persistenz-Staleness prueft der Payload-Pfad."""
    exp_id = _norm_id(expected_id)
    if not exp_id:
        return
    cur_id = _norm_id(getattr(allocation, "id", None))
    if exp_id != cur_id:
        raise AllocationVersionConflict(
            "Die angezeigte Soll-Allokation ist nicht mehr aktuell; es wird "
            "kein Bericht aus einem veralteten Stand erzeugt. Bitte neu laden "
            "bzw. Strategie neu berechnen.",
            REASON_REPORT_CONTEXT_STALE,
        )
