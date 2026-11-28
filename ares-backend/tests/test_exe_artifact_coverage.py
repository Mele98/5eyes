"""C-EXEPYZ-01/02: die Produkt-Hygiene deckt das ganze Artefakt ab.

``check_product_hygiene`` laeuft hier gegen ein kuenstliches Paket (Electron-
Verzeichnis, app.asar, CArchive mit Typcodes, PYZ). Statt einer Altmarke wird
ein Kunstwort ueber seinen Digest gesucht (gleiche Mechanik wie die echte
Digest-Liste, ohne Klartext im Repo).

Mutationen, die den Build sperren muessen:
- Kunstwort in einem ausfuehrbaren CArchive-Eintrag ausserhalb des PYZ,
- Kunstwort im Inhalt einer Electron-Zusatzressource (UTF-8 und UTF-16),
- Kunstwort in einem binaeren CArchive-Dateneintrag,
- unbekannter oder unlesbarer ausfuehrbarer Typ, kein Start-Eintrag.
Eine neutrale Mutation bleibt gruen.

Gegenprobe: die Fassung vor C-EXEPYZ (nur Namen unter win-unpacked, nur
Text-Endungen und PYZ im CArchive) laesst die Sperr-Mutationen durch.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
import struct
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "packaging_release_checks_artifact_test", ROOT / "scripts" / "packaging_release_checks.py"
)
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand_digest_support import brand_ids_in_text  # noqa: E402

KUNST = "kunstmarke"
DIGESTS = (("LB-X", len(KUNST), hashlib.sha256(KUNST.encode()).hexdigest()),)


class Blocked(Exception):
    pass


def _fail(msg):
    raise Blocked(msg)


def _code(source: str, filename: str = "main.py") -> bytes:
    return marshal.dumps(compile(source, filename, "exec"))


def _asar(files: dict[str, bytes]) -> bytes:
    offset, entries, blob = 0, {}, b""
    for name, data in files.items():
        entries[name] = {"offset": str(offset), "size": len(data)}
        offset += len(data)
        blob += data
    header = json.dumps({"files": entries}).encode()
    return struct.pack("<IIII", 4, len(header) + 8, len(header) + 4, len(header)) + header + blob


class FakePyz:
    def __init__(self, modules):
        self.toc = {name: None for name in modules}
        self._modules = modules

    def extract(self, name):
        return compile(self._modules[name], name + ".py", "exec")


def _artifact(tmp_path, monkeypatch, *, entries=None, resource=b"\x00\x01neutral resource\x00", pyz=None):
    unpacked = tmp_path / "win-unpacked"
    (unpacked / "resources" / "backend").mkdir(parents=True)
    (unpacked / "Ares.exe").write_bytes(b"MZ\x00\x00shell")
    (unpacked / "resources" / "app.asar").write_bytes(_asar({"package.json": b'{"productName": "Ares"}'}))
    (unpacked / "resources" / "backend" / "zusatz.bin").write_bytes(resource)
    exe = tmp_path / "ares-api.exe"
    exe.write_bytes(b"MZ")

    toc_entries = entries if entries is not None else {
        "pyiboot01_bootstrap": ("s", _code("x = 'bootstrap'", "pyiboot01_bootstrap.py")),
        "main": ("s", _code("print('Ares')")),
        "lib.dll": ("b", b"\x00\x02binary neutral\x00"),
        "PYZ.pyz": ("z", b""),
    }
    pyz_modules = pyz if pyz is not None else {"ares_module": "VALUE = 'neutral'"}

    class FakeCArchive:
        def __init__(self, _path):
            self.toc = {name: (0, 0, 0, 0, code) for name, (code, _data) in toc_entries.items()}

        def extract(self, name):
            return toc_entries[name][1]

        def open_embedded_archive(self, _name):
            return FakePyz(pyz_modules)

    readers = types.ModuleType("PyInstaller.archive.readers")
    readers.CArchiveReader = FakeCArchive
    monkeypatch.setitem(sys.modules, "PyInstaller.archive.readers", readers)
    monkeypatch.setattr(rc, "_brand_checker", lambda: lambda text: brand_ids_in_text(text, digests=DIGESTS))
    monkeypatch.setattr(rc, "desktop_package", lambda: {"version": "0.4.0", "productName": "Ares",
                                                        "build": {"productName": "Ares"}})
    monkeypatch.setattr(rc, "version_info", lambda path: {
        "ProductName": "Ares", "FileVersion": "0.4.0",
        "FileDescription": "Ares Backend" if path == exe else "Ares",
    })
    logs: list[str] = []
    return lambda: rc.check_product_hygiene(exe, unpacked, _fail, logs.append) or logs


def test_clean_artifact_passes_and_reports_coverage(tmp_path, monkeypatch):
    logs = _artifact(tmp_path, monkeypatch)()
    text = "\n".join(logs)
    assert "2 Code-Eintraege ausserhalb PYZ" in text
    assert "Electron-Paket: 3 Dateien (Name und Inhalt)" in text
    assert "1 Python-Module" in text


def test_neutral_mutation_stays_green(tmp_path, monkeypatch):
    entries = {
        "main": ("s", _code("print('kunstmerke')")),
        "PYZ.pyz": ("z", b""),
    }
    _artifact(tmp_path, monkeypatch, entries=entries, resource=b"\x00kunst/marke\x00")()


def test_marker_in_code_entry_outside_pyz_blocks(tmp_path, monkeypatch):
    entries = {
        "main": ("s", _code("NAME = ('a', ('Kunst-Marke',))")),
        "PYZ.pyz": ("z", b""),
    }
    with pytest.raises(Blocked, match="Code-Eintrag der Backend-EXE: main"):
        _artifact(tmp_path, monkeypatch, entries=entries)()


def test_marker_in_bootstrap_module_entry_blocks(tmp_path, monkeypatch):
    entries = {
        "pyimod99": ("m", _code("def f(kunstmarke): return 1", "pyimod99.py")),
        "main": ("s", _code("pass")),
        "PYZ.pyz": ("z", b""),
    }
    with pytest.raises(Blocked, match="pyimod99"):
        _artifact(tmp_path, monkeypatch, entries=entries)()


@pytest.mark.parametrize("payload", [
    b"\x00\x00\xffKUNSTMARKE\x00\x01",
    "Kunstmarke".encode("utf-16-le") + b"\x00\x00",
    b"\x10kunst.marke\x11",
])
def test_marker_in_electron_extra_resource_blocks(tmp_path, monkeypatch, payload):
    with pytest.raises(Blocked, match="Inhalt von <win-unpacked>"):
        _artifact(tmp_path, monkeypatch, resource=payload)()


def test_marker_in_binary_carchive_entry_blocks(tmp_path, monkeypatch):
    entries = {
        "main": ("s", _code("pass")),
        "data.bin": ("b", b"\x00\x00kunstmarke\x00"),
        "PYZ.pyz": ("z", b""),
    }
    with pytest.raises(Blocked, match="Backend-EXE:data.bin"):
        _artifact(tmp_path, monkeypatch, entries=entries)()


def test_unknown_typecode_blocks(tmp_path, monkeypatch):
    entries = {"main": ("s", _code("pass")), "eggs.zip": ("Z", b"PK"), "PYZ.pyz": ("z", b"")}
    with pytest.raises(Blocked, match="Unbekannter CArchive-Eintragstyp 'Z'"):
        _artifact(tmp_path, monkeypatch, entries=entries)()


def test_unreadable_code_entry_blocks(tmp_path, monkeypatch):
    entries = {"main": ("s", b"\x00not marshal"), "PYZ.pyz": ("z", b"")}
    with pytest.raises(Blocked, match="nicht lesbar: main"):
        _artifact(tmp_path, monkeypatch, entries=entries)()


def test_code_entry_without_code_object_blocks(tmp_path, monkeypatch):
    entries = {"main": ("s", marshal.dumps("nur ein Text")), "PYZ.pyz": ("z", b"")}
    with pytest.raises(Blocked, match="kein Code-Objekt"):
        _artifact(tmp_path, monkeypatch, entries=entries)()


def test_missing_entry_script_blocks(tmp_path, monkeypatch):
    entries = {"lib.dll": ("b", b"\x00"), "PYZ.pyz": ("z", b"")}
    with pytest.raises(Blocked, match="kein ausfuehrbarer Start-Eintrag"):
        _artifact(tmp_path, monkeypatch, entries=entries)()


def test_marker_in_pyz_module_still_blocks(tmp_path, monkeypatch):
    with pytest.raises(Blocked, match="Bytecode der Backend-EXE: ares_module"):
        _artifact(tmp_path, monkeypatch, pyz={"ares_module": "X = 'kunstmarke'"})()


# --- Vollstaendigkeit der Textabschnitte (Review-Befund P2) -------------------
from brand_digest_support import _SEPARATORS  # noqa: E402

SEPARATOR_CHARS = [chr(c) for c in range(0x10000)
                   if not 0xD800 <= c <= 0xDFFF and _SEPARATORS.fullmatch(chr(c))]


def _hit(data: bytes, digests=DIGESTS) -> bool:
    return bool(brand_ids_in_text(rc._binary_text(data), digests=digests))


def test_scanner_uses_the_same_separator_rule_as_the_digest_check():
    assert rc._NORM_SEPARATORS.pattern == _SEPARATORS.pattern


def test_every_normalization_separator_keeps_the_window_together():
    assert len(SEPARATOR_CHARS) > 25  # Positivkontrolle: Unicode-Leerraum dabei
    missed = []
    for sep in SEPARATOR_CHARS:
        word = f"kunst{sep}marke"
        encodings = [word.encode("utf-8"), word.encode("utf-16-le")]
        if ord(sep) <= 0xFF:
            encodings.append(word.encode("latin-1"))
        for data in encodings:
            if not _hit(b"\x00\x01" + data + b"\x00\x02"):
                missed.append((hex(ord(sep)), data[:12]))
    assert not missed, missed


def test_latin1_sharp_s_folds_like_the_normalization():
    digests = (("LB-Y", 6, hashlib.sha256(b"grosse").hexdigest()),)
    assert _hit(b"\x00gro\xdfe\x00", digests)          # Latin-1-Einzelbyte
    assert _hit("Große".encode("utf-8"), digests)
    assert _hit("GROSSE".encode("utf-16-le"), digests)


def test_non_separator_bytes_still_break_the_window():
    for data in (b"kunst/marke", b"kunst\x01marke", b"kunst\xffmarke", "kunst/marke".encode("utf-16-le")):
        assert not _hit(data), data
