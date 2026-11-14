"""H11 (Hygiene-Folgepunkt H10, N-899-21): Exec-Scan auch fuer dynamische Formen,
Ausnahmen pro Aufrufstelle statt pro Funktion.

Befund (Pruefrunde H10 ba6dd951): nicht gemeldet wurden ``getattr(os,
"system")``, ``__import__("os").system``, ``importlib.import_module(
"subprocess")``, ``from os import *``, ``pty.spawn``, ``webbrowser.open(<URL>)``,
``os.startfile(<URL-Literal>)``. Ausserdem deckte eine Ausnahme die ganze
Funktion: ein weiterer Aufruf mit variablem Programm in einer Ausnahme-Funktion
blieb verdeckt.
"""
from __future__ import annotations

import pytest

from tests.h10_exec_scan import scan_source
from tests.test_h10_nachtrag5_review import EXEC_EXCEPTIONS


@pytest.mark.parametrize("source, kind", [
    ("import os\ngetattr(os, 'system')('dir')\n", "dynamisch"),
    ("import subprocess as sp\nname = 'run'\ngetattr(sp, name)(['x'])\n", "dynamisch"),
    ("__import__('os').system('dir')\n", "dynamisch"),
    ("import importlib\nimportlib.import_module('subprocess').run(['x'])\n", "dynamisch"),
    ("from importlib import import_module as im\nim('os.path')\n", "dynamisch"),
    ("from os import *\n", "dynamisch"),
    ("import pty\npty.spawn('/bin/bash')\n", "extern-oeffnen"),
    ("import webbrowser\nwebbrowser.open('https://example.org')\n", "extern-oeffnen"),
    ("from webbrowser import open_new_tab as tab\ntab('https://example.org')\n", "extern-oeffnen"),
    ("import os\nos.startfile('https://example.org')\n", "extern-oeffnen"),
])
def test_dynamic_and_external_open_forms_are_reported(source, kind):
    assert [f[2] for f in scan_source(source, "svc/x.py")] == [kind]


@pytest.mark.parametrize("source", [
    "import os\nflags = os.O_WRONLY | getattr(os, 'O_BINARY', 0)\n",  # Konstante, keine Ausfuehrung
    "import importlib\nimportlib.import_module('services.tax.ch')\n",
    "import importlib\nfor name in mods:\n    importlib.import_module(name)\n",  # dokumentierte Restform
])
def test_harmless_dynamic_lookups_pass(source):
    assert scan_source(source, "svc/x.py") == []


def test_exception_covers_exactly_one_call_site():
    """Ein zweiter Aufruf mit variablem Programm in der Ausnahme-Funktion
    replicate_offsite ist NICHT gedeckt (vorher: Ausnahme je Funktion)."""
    source = ("import subprocess\n\ndef replicate_offsite(cmd, other):\n"
              "    subprocess.run(cmd)\n    subprocess.run(other)\n")
    findings = scan_source(source, "ares-backend/services/backup.py")
    assert [f[0] for f in findings] == ["ares-backend/services/backup.py::replicate_offsite#1",
                                        "ares-backend/services/backup.py::replicate_offsite#2"]
    uncovered = [f for f in findings if f[0] not in EXEC_EXCEPTIONS]
    assert [f[1] for f in uncovered] == [5]


def test_every_exception_names_one_call_site():
    assert EXEC_EXCEPTIONS and all(key.rsplit("#", 1)[-1].isdigit() for key in EXEC_EXCEPTIONS)
