"""KN6 (CI 44840465176): Waechter gegen Import-Uhren ohne feste Wanduhr.

Ein Testmodul, das auf Modulebene die Uhr liest (``TODAY = date.today()``,
``NOW = datetime.now(...)``), bindet ``tests.import_day_clock.fixed_import_clock``.
Sonst kippt der Test, wenn zwischen Import (Sammelphase) und Testlauf
Mitternacht liegt.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_MODULE_LEVEL_CLOCK = re.compile(
    r"^[A-Za-z_][A-Za-z_0-9]*[ \t]*(?::[^=\n]+)?=.*(?:\btoday\(\)|\.now\(|\butcnow\()", re.MULTILINE)


def module_level_clock_reads(source: str) -> list[str]:
    return _MODULE_LEVEL_CLOCK.findall(source)


def test_every_module_level_clock_read_is_pinned():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name in ("import_day_clock.py", Path(__file__).name):
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if module_level_clock_reads(source) and "fixed_import_clock(" not in source:
            offenders.append(str(path.relative_to(TESTS)))
    assert not offenders, offenders


def test_guard_pattern_controls():
    assert module_level_clock_reads("TODAY = date.today()\n")
    assert module_level_clock_reads("NOW = datetime.now(timezone.utc).isoformat()\n")
    assert module_level_clock_reads("_X = (date.today() + timedelta(days=3)).isoformat()\n")
    assert not module_level_clock_reads("    today = date.today()\n")
    assert not module_level_clock_reads("def f():\n    return datetime.now()\n")
    # Fehlalarm aus einem Docstring (Doppelpunkt ... Gleichheitszeichen ueber Zeilen).
    assert not module_level_clock_reads('Teil B: Kurse\nliefern = x\nNOW wird mit .now( gelesen\n')
