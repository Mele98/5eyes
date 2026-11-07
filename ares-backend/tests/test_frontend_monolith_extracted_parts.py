"""H3/I-04: Vertrag fuer die aus ares.html ausgelagerten Teile.

Die Auslagerung ist nur verhaltensneutral, wenn
* jede Datei genau einmal, an der urspruenglichen Stelle, als klassisches
  synchrones Skript (kein defer/async/module) bzw. als Stylesheet eingebunden ist,
* sie in BEIDEN Ladewegen erreichbar ist: Electron (loadFile -> file://, die
  Datei muss im gepackten Build stecken = electron-builder ``files``) und
  Backend-Serving (/app/ = StaticFiles ueber das ganze Frontend-Verzeichnis),
* die Rekonstruktion (read_monolith_bundle) die Inline-Bloecke wiederherstellt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.monolith_source import (
    EXTRACTED_PARTS,
    FRONTEND_DIR,
    MONOLITH_PATH,
    include_tag,
    read_monolith_bundle,
)

PACKAGE_JSON = FRONTEND_DIR.parent / "package.json"


def _html() -> str:
    return MONOLITH_PATH.read_text(encoding="utf-8")


def _build_files() -> list[str]:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["build"]["files"]


def test_each_extracted_part_is_included_exactly_once_as_classic_resource():
    html = _html()
    for name, kind in EXTRACTED_PARTS:
        assert (FRONTEND_DIR / name).is_file(), name
        assert html.count(include_tag(name, kind)) == 1, name
        assert html.count(name) == 1, f"{name} zusaetzlich anders eingebunden"


def test_extracted_parts_keep_document_order():
    html = _html()
    positions = [html.index(include_tag(name, kind)) for name, kind in EXTRACTED_PARTS]
    assert positions == sorted(positions)
    # Stylesheet bleibt im <head>, vor dem ersten Inline-Skript der App.
    assert positions[0] < html.index("</head>")
    # Die Laufzeit-Bloecke bleiben vor </body> (spaete Overrides von cm()/renderStrategySummary).
    assert positions[-1] < html.rindex("</body>")


def test_extracted_parts_are_packaged_for_electron():
    files = _build_files()
    for name, _kind in EXTRACTED_PARTS:
        assert f"frontend/{name}" in files, name


def test_every_local_frontend_resource_of_the_monolith_is_packaged():
    """Generisch: jede lokale src/href-Datei von ares.html muss im Paket sein."""
    files = set(_build_files())
    # Keine in JS-Strings zusammengesetzten URLs ('+...+').
    refs = re.findall(r'<(?:script|link)\b[^>]*\b(?:src|href)="([^"\'+]+)"', _html())
    local = [r for r in refs if not re.match(r"^[a-z]+:|^//|^#", r)]
    assert local, "keine lokalen Ressourcen gefunden -- Regex pruefen"
    for ref in local:
        rel = ref[2:] if ref.startswith("./") else ref
        assert (FRONTEND_DIR / rel).is_file(), ref
        if rel.startswith("vendor/"):
            assert "frontend/vendor/**/*" in files
        else:
            assert f"frontend/{rel}" in files, f"{ref} fehlt in package.json build.files"


def test_extracted_parts_contain_no_raw_closing_tags():
    for name, kind in EXTRACTED_PARTS:
        text = (FRONTEND_DIR / name).read_text(encoding="utf-8").lower()
        closing = "</style" if kind == "css" else "</script"
        assert closing not in text, name


def test_bundle_reconstruction_restores_inline_blocks():
    bundle = read_monolith_bundle()
    for name, kind in EXTRACTED_PARTS:
        assert include_tag(name, kind) not in bundle
    assert "function goalFrequencyKey(" in bundle
    assert "window.replayIntro" in bundle


def test_backend_serves_whole_frontend_directory():
    main_py = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'StaticFiles(directory=str(_MAIN_FRONTEND_DIR)' in main_py
