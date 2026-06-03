from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

from reportlab.pdfbase import pdfmetrics

from services.pdf.fonts import (
    FONT_FILES,
    editorial_font_names,
    register_editorial_fonts,
    resolve_font_asset_dir,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FONT_DIR = BACKEND_ROOT / "assets" / "fonts"

FONT_HASHES = {
    "CormorantGaramond-Italic.ttf": "297240eb62c618cfd30a295cc1055b1ea26be9a72dd762836d13b58bc8b918c6",
    "CormorantGaramond-Regular.ttf": "6692a7e7f324e71ec0be0c36d1aab340dbf1df0ce2e29ab1770082f28e45eb09",
    "CormorantGaramond-SemiBold.ttf": "dc4bc094dc3c55cf79ff2f6f0ba1e501b712fc3cf3742296cd8fdcc6e995127d",
    "Inter-Medium.ttf": "97ad806f526e41546d46365bb3a393145f75b7b1568913db74549ad8b8dba872",
    "Inter-Regular.ttf": "40d692fce188e4471e2b3cba937be967878f631ad3ebbbdcd587687c7ebe0c82",
    "Inter-SemiBold.ttf": "78a843fade9d4612a5567302fb595b56976eb5fcebf4fea5a5912d638bafcde3",
}


def test_editorial_ttf_files_exist():
    assert sorted(FONT_FILES.values()) == sorted(FONT_HASHES)
    for filename in FONT_HASHES:
        path = FONT_DIR / filename
        assert path.exists(), filename
        assert path.stat().st_size > 100_000


def test_editorial_ttf_hashes_are_stable():
    for filename, expected in FONT_HASHES.items():
        actual = hashlib.sha256((FONT_DIR / filename).read_bytes()).hexdigest()
        assert actual == expected


def test_register_editorial_fonts_is_idempotent():
    assert register_editorial_fonts() is True
    assert register_editorial_fonts() is True


def test_reportlab_registered_font_names_include_editorial_faces():
    assert register_editorial_fonts() is True
    names = set(pdfmetrics.getRegisteredFontNames())

    assert "CormorantGaramond" in names
    assert "CormorantGaramond-SemiBold" in names
    assert "CormorantGaramond-Italic" in names
    assert "Inter" in names
    assert "Inter-Medium" in names
    assert "Inter-SemiBold" in names


def test_editorial_font_names_return_registered_names():
    names = editorial_font_names()

    assert names.serif == "CormorantGaramond"
    assert names.serif_bold == "CormorantGaramond-SemiBold"
    assert names.serif_italic == "CormorantGaramond-Italic"
    assert names.sans == "Inter"
    assert names.sans_bold == "Inter-SemiBold"


def test_missing_ttf_files_degrade_without_crash(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="services.pdf.fonts")

    assert register_editorial_fonts(font_dir=tmp_path) is False

    assert "Falling back to stock fonts" in caplog.text
    assert "Inter-Regular.ttf" in caplog.text


def test_pyinstaller_font_path_resolution_prefers_meipass(monkeypatch, tmp_path):
    bundle_fonts = tmp_path / "5eyes-backend" / "assets" / "fonts"
    bundle_fonts.mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resolve_font_asset_dir() == bundle_fonts


def test_style_tokens_use_editorial_fonts_when_assets_exist():
    from services.pdf import styles
    from services.pdf.components import advisory_palette

    assert styles.FONT_DEFAULT == "Inter"
    assert styles.FONT_BOLD == "Inter-SemiBold"
    assert styles.FONT_SERIF_BOLD == "CormorantGaramond-SemiBold"
    assert advisory_palette.FONT_SANS == "Inter"
    assert advisory_palette.FONT_SERIF_BOLD == "CormorantGaramond-SemiBold"


def test_release_scripts_include_pdf_font_assets():
    release_check = (REPO_ROOT / "5eyes-electron" / "scripts" / "release-check.js").read_text(encoding="utf-8")
    build_backend = (REPO_ROOT / "5eyes-electron" / "scripts" / "build-backend.js").read_text(encoding="utf-8")

    for filename in FONT_HASHES:
        assert filename in release_check
    assert "assets/fonts;assets/fonts" in build_backend
    assert "assets/fonts:assets/fonts" in build_backend
