"""Gemeinsame Hilfsfunktion fuer handgebaute Mutations-Tests (Roadmap #86).

Hintergrund
-----------
``mutmut`` (das in ``mutmut.cfg`` konfigurierte Mutation-Testing-Tool) verweigert
auf Windows den Dienst nativ:

    C:\\...\\5eyes-backend> python -m mutmut --help
    To run mutmut on Windows, please use the WSL. Native windows support is
    tracked in issue https://github.com/boxed/mutmut/issues/397

Da die Entwicklungsumgebung hier natives Windows (kein WSL) ist, ist ein echter
``mutmut run`` nicht durchfuehrbar. Dieses Modul liefert stattdessen die
Kern-Mechanik fuer HANDGEBAUTE Mutations-Tests, die denselben Zweck erfuellen:
zeigen, dass die bestehende Test-Suite eine gezielte, plausible Formel-Aenderung
tatsaechlich als Fehler erkennen wuerde (nicht nur, dass die Zeile ausgefuehrt
wurde -- das waere reine Line-Coverage).

Methodik
--------
``mutate(module, func_name, old, new)`` nimmt den ECHTEN Quellcode der
Zielfunktion via ``inspect.getsource`` (keine separat gepflegte Kopie!),
ersetzt einen exakt einmal vorkommenden Teilausdruck (``old``) durch eine
bewusst falsche Variante (``new`` -- z.B. Vorzeichen-Fehler, Off-by-One,
falscher Operator, vertauschter Vergleich) und kompiliert das Ergebnis zu einer
neuen Funktion im Namespace-Klon des Original-Moduls (gleiche Imports/Helper
wie das Original, z.B. ``math``, ``_parse_date``, ``_add_months``).

Damit testen wir eine echte, minimale Mutation des AKTUELLEN Produktivcodes --
nicht eine Nacherzaehlung der Formel, die bei einer echten Code-Aenderung
stillschweigend veraltet.

Drift-Schutz: kommt ``old`` nicht GENAU EINMAL im Quelltext der Funktion vor
(0x oder >=2x Treffer), wirft ``mutate()`` einen ``AssertionError``. Das ist
gewollt -- es zeigt an, dass sich die Zielfunktion seit dem Schreiben dieses
Mutations-Tests strukturell veraendert hat und der Test-Anker ueberprueft
werden muss, statt leise ins Leere zu laufen (kein stiller No-Op-Test).

Was das NICHT abdeckt
----------------------
- Kein echter mutmut-Lauf, also keine automatische Exploration ALLER
  moeglichen Mutationen (nur die hier bewusst ausgewaehlten).
- Keine Mutationen in der grossen Monte-Carlo-Simulation selbst (bewusst
  ausgeschlossen laut Auftrag -- nur kleine, reine Helper-Funktionen).
- Ein "survivor" (Mutation, die keine bestehende Assertion bricht) hier
  bedeutet nur: diese SPEZIFISCHE Mutation waere nicht aufgefallen -- nicht,
  dass die Funktion frei von Test-Luecken ist.
"""
from __future__ import annotations

import inspect
import textwrap
from types import ModuleType
from typing import Callable


def mutate(module: ModuleType, func_name: str, old: str, new: str) -> Callable:
    """Erzeugt eine mutierte Variante von ``module.<func_name>``.

    :param module: das Modul, das die zu mutierende Funktion definiert
        (z.B. ``services.cashflow_timeline``).
    :param func_name: Name der Funktion im Modul.
    :param old: exakter Teilstring im (dedented) Quelltext der Funktion, der
        ersetzt werden soll. Muss GENAU EINMAL vorkommen.
    :param new: der bewusst falsche Ersatz-Ausdruck (die "Mutation").
    :raises AssertionError: wenn ``old`` nicht genau einmal im echten
        Quelltext der Funktion vorkommt (Drift-Schutz, siehe Modul-Docstring).
    :returns: eine neue, unabhaengige Funktion mit der Mutation -- die
        Original-Funktion im Modul bleibt unveraendert.
    """
    func = getattr(module, func_name)
    source = textwrap.dedent(inspect.getsource(func))
    occurrences = source.count(old)
    assert occurrences == 1, (
        f"Mutations-Anker nicht eindeutig in {module.__name__}.{func_name}: "
        f"{occurrences}x gefunden fuer alte Formulierung {old!r}. "
        "Quellcode hat sich vermutlich veraendert -- Test-Anker in diesem "
        "Mutations-Test pruefen/aktualisieren, nicht ignorieren."
    )
    mutated_source = source.replace(old, new, 1)
    namespace = dict(vars(module))
    exec(  # noqa: S102 -- bewusst: Mutation-Testing-Infrastruktur, kein Produktivcode
        compile(mutated_source, f"<mutant:{module.__name__}.{func_name}>", "exec"),
        namespace,
    )
    mutant = namespace[func_name]
    assert mutant is not func, "Mutation hat keine neue Funktion erzeugt (Bug im Harness)"
    return mutant
