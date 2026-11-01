"""X1 (H-097 offen): Packaging-Smoke prueft die Laenderpaket-Manifeste im EXE.

``scripts/packaging_smoke.py`` liest die PyInstaller-EXE. Fehlt
``jurisdictions/<code>/pack.yaml`` im Bundle, waere ``/health/ready`` weiter
gruen; erst der erste Allokations-/Evidence-Aufruf wuerde mit
``PackRegistryError`` scheitern. Diese Tests belegen die Pruefung ohne
gebaute EXE: ein Archiv-Ersatz (Name -> Bytes) aus dem Quellbaum ist gruen,
jede Abweichung (fehlt, abweichende Bytes, ohne Quelle, nicht lesbar) ist rot.
"""
from __future__ import annotations

import importlib.util
import inspect
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PACKS = REPO_ROOT / "ares-backend" / "jurisdictions"


def _load_smoke():
    name = "_ares_packaging_smoke_under_test"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "packaging_smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()


def _archive_from(source_root: Path) -> dict[str, bytes]:
    """Archiv-Ersatz wie ihn build-backend.js erzeugt: Ziel = jurisdictions/<rel>."""
    return {
        "jurisdictions/" + p.relative_to(source_root).as_posix(): p.read_bytes()
        for p in source_root.rglob("*.yaml")
    }


def _check(archive: dict[str, bytes], source_root: Path = SOURCE_PACKS) -> None:
    # Wie im echten CArchive: Windows-Trenner im TOC, normalisiert auf "/".
    toc = {name.replace("/", "\\"): data for name, data in archive.items()}
    normalized = {name.replace("\\", "/"): name for name in toc}
    smoke.check_jurisdiction_packs(normalized, toc.__getitem__, source_root=source_root)


def test_packaged_manifests_identical_with_source_pass(capsys):
    _check(_archive_from(SOURCE_PACKS))
    out = capsys.readouterr().out
    assert "OK Laenderpakete im Paket" in out
    assert "CH" in out


def test_missing_pack_manifest_fails():
    archive = _archive_from(SOURCE_PACKS)
    del archive["jurisdictions/ch/pack.yaml"]
    with pytest.raises(smoke.SmokeError, match="fehlt im Paket: jurisdictions/ch/pack.yaml"):
        _check(archive)


def test_packaged_manifest_with_different_bytes_fails():
    archive = _archive_from(SOURCE_PACKS)
    archive["jurisdictions/ch/pack.yaml"] += b"\n# drift\n"
    with pytest.raises(smoke.SmokeError, match="weicht von der Quelle ab"):
        _check(archive)


def test_packaged_manifest_without_source_fails():
    archive = _archive_from(SOURCE_PACKS)
    archive["jurisdictions/zz/pack.yaml"] = archive["jurisdictions/ch/pack.yaml"]
    with pytest.raises(smoke.SmokeError, match="ohne Quelle: jurisdictions/zz/pack.yaml"):
        _check(archive)


def test_unreadable_manifest_fails_even_if_identical(tmp_path):
    source = tmp_path / "jurisdictions"
    shutil.copytree(SOURCE_PACKS / "ch", source / "ch")
    (source / "ch" / "pack.yaml").write_bytes(b"code: [CH\n")  # kaputtes YAML
    with pytest.raises(smoke.SmokeError, match="nicht lesbar"):
        _check(_archive_from(source), source_root=source)


def test_without_required_ch_pack_fails(tmp_path):
    source = tmp_path / "jurisdictions"
    source.mkdir()
    with pytest.raises(smoke.SmokeError, match="Pruefgrundlage fehlt"):
        _check({}, source_root=source)


def test_check_archive_runs_the_pack_check():
    assert "check_jurisdiction_packs(normalized, archive.extract)" in inspect.getsource(smoke.check_archive)
