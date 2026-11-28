"""Zero-Trace EXE-02: der PYZ-Bytecode-Scan muss jeden Text eines Moduls sehen.

``_code_strings`` liefert die Texte, die ``check_product_hygiene`` gegen die
Marken-Digests prueft. Ein Text, den die Funktion nicht liefert, kann eine
Altmarke unbemerkt in die ausgelieferte EXE tragen. Geprueft wird mit einem
neutralen Marker an allen Stellen, an denen Python Texte im Code-Objekt ablegt.

Gegenprobe: die alte Fassung las nur flache Tupel und keine freien Variablen;
die Faelle ``tief`` und ``frei`` werden mit ihr rot.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "packaging_release_checks_under_test", ROOT / "scripts" / "packaging_release_checks.py"
)
release_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_checks)

SOURCE = '''
FLACH = "marker_flach"
TIEF = (("a", ("marker_tief",)), 1)
MENGE = frozenset({"marker_menge"})
ROH = b"marker_bytes"

def aussen(marker_param):
    marker_frei = 1
    def innen():
        return marker_frei
    class Klasse:
        def methode(self):
            return marker_attr.marker_name
    return innen, Klasse

lam = lambda: "marker_lambda"
'''


def _strings() -> str:
    return "\n".join(release_checks._code_strings(compile(SOURCE, "marker_datei.py", "exec")))


def test_all_text_locations_are_scanned():
    text = _strings()
    for marker in (
        "marker_flach", "marker_tief", "marker_menge", "marker_bytes", "marker_param",
        "marker_frei", "marker_attr", "marker_name", "marker_lambda", "marker_datei.py",
        "Klasse", "methode",
    ):
        assert marker in text, marker


def test_absent_marker_is_not_reported():
    assert "marker_fehlt" not in _strings()
