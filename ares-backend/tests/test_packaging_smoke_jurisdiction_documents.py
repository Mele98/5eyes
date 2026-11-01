"""X3 (H-097 offen): Packaging-Smoke prueft die Text-YAMLs im EXE.

Fehlt eine ``jurisdictions/<code>/documents/<locale>/<namespace>.yaml`` im
PyInstaller-Bundle, waere ``/health/ready`` gruen; erst Kostenausweis bzw.
Fusszeile im PDF wuerden scheitern. Archiv-Ersatz (Name -> Bytes) aus dem
Quellbaum ist gruen; fehlt / abweichende Bytes / ohne Quelle / nicht lesbar
ist rot.
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
COST_KEY = "jurisdictions/ch/documents/de-CH/cost_disclosure.yaml"


def _load_smoke():
    name = "_ares_packaging_smoke_documents_under_test"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "packaging_smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()


def _archive_from(source_root: Path) -> dict[str, bytes]:
    return {
        "jurisdictions/" + p.relative_to(source_root).as_posix(): p.read_bytes()
        for p in source_root.rglob("*.yaml")
    }


def _check(archive: dict[str, bytes], source_root: Path = SOURCE_PACKS) -> None:
    toc = {name.replace("/", "\\"): data for name, data in archive.items()}
    normalized = {name.replace("\\", "/"): name for name in toc}
    smoke.check_jurisdiction_documents(normalized, toc.__getitem__, source_root=source_root)


def test_source_has_text_yamls_to_check():
    assert COST_KEY in _archive_from(SOURCE_PACKS)
    assert "jurisdictions/ch/documents/de-CH/legal.yaml" in _archive_from(SOURCE_PACKS)


def test_packaged_texts_identical_with_source_pass(capsys):
    _check(_archive_from(SOURCE_PACKS))
    out = capsys.readouterr().out
    assert "OK Laenderpaket-Texte im Paket: 2 Datei(en)" in out
    assert "CH@" in out


@pytest.mark.parametrize("key", [COST_KEY, "jurisdictions/ch/documents/de-CH/legal.yaml"])
def test_missing_text_yaml_fails(key):
    archive = _archive_from(SOURCE_PACKS)
    del archive[key]
    with pytest.raises(smoke.SmokeError, match=f"Text fehlt im Paket: {key}"):
        _check(archive)


def test_missing_manifest_fails_document_check():
    archive = _archive_from(SOURCE_PACKS)
    del archive["jurisdictions/ch/pack.yaml"]
    with pytest.raises(smoke.SmokeError, match="Datei fehlt im Paket: jurisdictions/ch/pack.yaml"):
        _check(archive)


def test_packaged_text_with_different_bytes_fails():
    archive = _archive_from(SOURCE_PACKS)
    archive[COST_KEY] += b"\n# drift\n"
    with pytest.raises(smoke.SmokeError, match="weicht von der Quelle ab"):
        _check(archive)


def test_packaged_text_without_source_fails():
    archive = _archive_from(SOURCE_PACKS)
    extra = "jurisdictions/ch/documents/de-CH/extra.yaml"
    archive[extra] = archive[COST_KEY]
    with pytest.raises(smoke.SmokeError, match=f"ohne Quelle: {extra}"):
        _check(archive)


def test_unreadable_text_fails_even_if_identical(tmp_path):
    source = tmp_path / "jurisdictions"
    shutil.copytree(SOURCE_PACKS / "ch", source / "ch")
    (source / "ch" / "documents" / "de-CH" / "legal.yaml").write_text(
        "namespace: legal\ntexts: {}\n", encoding="utf-8")  # leeres texts-Mapping
    with pytest.raises(smoke.SmokeError, match="Texte im Paket nicht lesbar"):
        _check(_archive_from(source), source_root=source)


def test_broken_yaml_text_fails(tmp_path):
    source = tmp_path / "jurisdictions"
    shutil.copytree(SOURCE_PACKS / "ch", source / "ch")
    (source / "ch" / "documents" / "de-CH" / "legal.yaml").write_bytes(b"namespace: [legal\n")
    with pytest.raises(smoke.SmokeError, match="Texte im Paket nicht lesbar"):
        _check(_archive_from(source), source_root=source)


def test_without_text_yamls_fails(tmp_path):
    source = tmp_path / "jurisdictions"
    (source / "ch").mkdir(parents=True)
    shutil.copy2(SOURCE_PACKS / "ch" / "pack.yaml", source / "ch" / "pack.yaml")
    with pytest.raises(smoke.SmokeError, match="Pruefgrundlage fehlt"):
        _check(_archive_from(source), source_root=source)


def test_check_archive_runs_the_document_check():
    assert "check_jurisdiction_documents(normalized, archive.extract)" in inspect.getsource(smoke.check_archive)
