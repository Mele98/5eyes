"""CCX P5 / M-2: Testvektor fuer direkte Optimierer-Aufrufe in Tests.

Seit P5 hat der Optimierer keinen Code-Fallback mehr fuer den Risikoanteil je
Anlageklasse (``CCX_PARAMETER_SET_MISSING``); jeder Aufrufer liefert den
kanonischen Vektor (IC-Unterklassenwerte x Suballokation). Tests, die den
Solver direkt -- ohne Engine und ohne BuildingBlocks -- aufrufen, uebergeben
diesen Vektor ausdruecklich. Die Werte sind die frueheren Vorlagewerte des
Optimierers (Methodik-Folie 17), damit die bestehenden Erwartungen gelten; sie
sind KEIN Produktionswert und werden von keinem produktiven Pfad gelesen
(Waechter: tests/test_ccx_p5_parameter_set.py).
"""
from __future__ import annotations

import sys

if "pytest" not in sys.modules:  # pragma: no cover - nur im Testlauf
    raise ImportError("tests.p5_test_vectors ist eine reine Testhilfe (nur unter pytest).")

P5_TEST_RISKY_FRACTION = {
    "equities": 0.80,
    "bonds": 0.25,
    "real_estate": 0.60,
    "alternatives": 0.60,
    "liquidity": 0.00,
}
