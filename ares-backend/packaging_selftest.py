"""Import-Selbsttest der gepackten Backend-EXE (Release-Readiness H-180).

Aufruf: ``ares-api.exe --self-test-imports`` (oder ``python main.py
--self-test-imports``). Importiert jedes Modul der eigenen Pakete und die
Laufzeit-Abhaengigkeiten, die nur lazy geladen werden (Optimizer, PDF,
Statistik). Gibt eine JSON-Zeile aus und endet mit Exit 0 (alles importierbar)
bzw. 1 (mindestens ein Modul fehlt).

Hintergrund (Befund EXE-01, 2026-11-21): PyInstaller uebersah
``scipy._external.array_api_compat.numpy.fft`` (neu in scipy 1.18). Die
gepackte EXE fiel dadurch beim Strategielauf still vom stochastischen
Optimizer auf den House-Matrix-Default zurueck ("Stochastic optimizer module
not importable"), waehrend alle Quelltests gruen waren. Lazy Imports in
``try/except ImportError`` sind fuer die statische Analyse unsichtbar; nur ein
Import im gepackten Artefakt selbst deckt sie auf.

Keine Datenbank, kein Netz, kein Schreibzugriff: nur ``importlib``.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import sys

# Eigene Pakete: jedes Untermodul muss im Paket liegen und importierbar sein.
OWN_PACKAGES: tuple[str, ...] = ("core", "services", "routers", "models", "schemas", "jurisdictions")

# Lazy geladene Fremdmodule, ohne die die Kernkette still degradiert.
RUNTIME_MODULES: tuple[str, ...] = (
    "numpy.linalg",
    "numpy.fft",
    "scipy.optimize",
    "scipy.stats",
    "scipy.linalg",
    "scipy.special",
    "scipy.interpolate",
    "services.optimizer.solver",
    "services.optimizer.constraints",
    "reportlab.pdfgen.canvas",
    "reportlab.platypus",
)

# Nur im gepackten Artefakt Pflicht (Quell-/Test-Umgebungen haben den Treiber nicht immer).
FROZEN_RUNTIME_MODULES: tuple[str, ...] = ("sqlcipher3",)

# Module, die eine optionale, nicht gebuendelte Abhaengigkeit brauchen und das
# selbst sauber abfangen. Leer: jede Ausnahme braucht eine Begruendung hier.
OPTIONAL_MODULES: dict[str, str] = {}


def _own_module_names() -> list[str]:
    names: list[str] = []
    for package in OWN_PACKAGES:
        module = importlib.import_module(package)
        names.append(package)
        for info in pkgutil.walk_packages(module.__path__, package + "."):
            names.append(info.name)
    return names


def run_self_test() -> dict:
    failures: dict[str, str] = {}
    checked: list[str] = []
    try:
        candidates = _own_module_names()
    except BaseException as exc:  # noqa: BLE001 - jede Ausnahme ist ein Befund
        return {"ok": False, "checked": 0, "failures": {"<walk>": f"{type(exc).__name__}: {exc}"}}
    # EXE-P (H-187): die gepackte EXE startet nur mit SQLCipher -- im Artefakt Pflicht.
    frozen_only = list(FROZEN_RUNTIME_MODULES) if getattr(sys, "frozen", False) else []
    for name in list(RUNTIME_MODULES) + frozen_only + candidates:
        if name in checked:
            continue
        checked.append(name)
        try:
            importlib.import_module(name)
        except BaseException as exc:  # noqa: BLE001 - jede Ausnahme ist ein Befund
            if name not in OPTIONAL_MODULES:
                failures[name] = f"{type(exc).__name__}: {exc}"[:300]
    own = sum(1 for n in checked if n.split(".", 1)[0] in OWN_PACKAGES)
    return {"ok": not failures, "checked": len(checked), "own_modules": own,
            "frozen": bool(getattr(sys, "frozen", False)), "failures": failures}


def main() -> int:
    result = run_self_test()
    print("ARES_SELF_TEST_IMPORTS " + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
