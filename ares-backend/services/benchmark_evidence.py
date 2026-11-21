"""CCX-06 / CCX-P2: Benchmark-Lineage eines Beratungsentscheids.

Die Benchmark-Referenz eines Entscheids ist die Hausmatrix der Policy, mit der
die Soll-Allokation erzeugt wurde (services/house_matrix_benchmark.py). Ihre
Identitaet und Version ist eine wirkende Abhaengigkeit: die Versiegelung bindet
sie als Kante ``benchmark`` (Objekt = Policy, ``dependency_hash`` = Kind-Hash
ueber alle Hausmatrix-Zeilen, services/effective_input_manifest.py), jede
Mutation einer Hausmatrix-Zeile invalidiert den Entscheid (zentraler Mutation
Hook, models/snapshots.py). Ein Wechsel der Benchmark-Version macht eine
gebundene Ausgabe damit nicht-aktuell; unbekannt ist nie aktuell.
"""
from __future__ import annotations


def benchmark_identity(policy_id: str | None, version: int | None, rows_hash: str | None) -> str | None:
    """Kanonische Benchmark-Identitaet ``house-matrix:<policy>@<version>#<hash>``
    (``None``, sobald ein Bestandteil fehlt -- unknown != current)."""
    if not policy_id or version is None or isinstance(version, bool) or not rows_hash:
        return None
    return f"house-matrix:{policy_id}@{int(version)}#{rows_hash}"


def is_benchmark_current(bound: str | None, current: str | None) -> bool:
    """True genau dann, wenn die gebundene und die aktuelle Benchmark-
    Identitaet bekannt und gleich sind."""
    return bool(bound) and bool(current) and str(bound) == str(current)


__all__ = ["benchmark_identity", "is_benchmark_current"]
