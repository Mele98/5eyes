"""Selbsttest fuer ``tests/brand_digest_support.py``.

Die Negativfixtures sind ROT13-kodiert und werden erst zur Laufzeit
dekodiert. Begruendung: Der Guard soll nachweislich echte Altnamen finden,
ohne dass ein Altname im Klartext im Repo steht. ROT13 verschiebt jeden
Buchstaben um 13 Stellen; die kodierten Zeichenfolgen sind weder ein Altname
noch eine Schreibvariante davon (Ziffern bleiben, Buchstaben werden andere).
Jeder dekodierte Vektor muss ausserdem einen Digest der Liste treffen, also
ist er an die Digest-Liste gebunden und kann nicht unbemerkt veralten.
"""
from __future__ import annotations

import codecs

import pytest

from tests.brand_digest_support import (
    ALL_BRANDS,
    LB_A_CORE_DIGEST,
    LEGACY_BRAND_STEM_DIGESTS,
    assert_no_legacy_brand,
    brand_ids_in_text,
    contains_digest,
    normalize_text,
)
from tests.test_brand_identifier_ast_guard import FORBIDDEN_STEM_DIGESTS

# (Marken-ID, ROT13-kodierte Schreibweise). Dekodiert nur zur Laufzeit.
_ROT13_VECTORS: tuple[tuple[str, str], ...] = (
    ("LB-A", "3rlrf"),
    ("LB-A", "3 Rlrf"),
    ("LB-A", "3-RLRF"),
    ("LB-A", "Guerr Rlrf"),
    ("LB-A", "qerv Nhtra"),
    ("LB-B", "5rlrf"),
    ("LB-B", "5_Rlrf"),
    ("LB-B", "Svir.Rlrf"),
    ("LB-C", "Jrnygu Nepuvgrxgra"),
    ("LB-C", "jrnygu-nepuvgrpgf"),
)


def _decode(encoded: str) -> str:
    return codecs.decode(encoded, "rot13")


def _vector_id(item: tuple[str, str]) -> str:
    brand, _ = item
    return f"{brand}-{_ROT13_VECTORS.index(item)}"


def test_digest_list_matches_ast_guard():
    """Eine einzige Wahrheit: gleiche Digests wie der AST-Guard (#815)."""
    assert LEGACY_BRAND_STEM_DIGESTS == FORBIDDEN_STEM_DIGESTS
    assert LB_A_CORE_DIGEST == LEGACY_BRAND_STEM_DIGESTS[0][2]


@pytest.mark.parametrize("item", _ROT13_VECTORS, ids=[_vector_id(v) for v in _ROT13_VECTORS])
@pytest.mark.parametrize("wrap", ["plain", "sentence", "html", "pdf_linebreak"])
def test_decoded_vector_is_caught(item, wrap):
    brand, encoded = item
    name = _decode(encoded)
    text = {
        "plain": name,
        "sentence": f"Bericht erstellt von {name} fuer den Kunden.",
        "html": f"<div class=\"brand\"><span>{name}</span></div>",
        # PDF-Extraktion bricht Zeilen gern mitten im Wort um
        "pdf_linebreak": f"Seite 1\n{name[:2]}\n{name[2:]}\nSeite 2",
    }[wrap]
    assert brand_ids_in_text(text) == {brand}
    with pytest.raises(AssertionError) as excinfo:
        assert_no_legacy_brand(text, "fixture")
    # Die Meldung nennt nur die Marken-ID, nie den Klartext.
    message = str(excinfo.value)
    assert brand in message
    assert normalize_text(name) not in normalize_text(message)


def test_core_vector_hits_core_digest_exactly():
    name = _decode("3rlrf")
    assert contains_digest(name, LB_A_CORE_DIGEST, 5, normalize=False)
    assert contains_digest(f"xx {name} yy", LB_A_CORE_DIGEST, 5, normalize=False)
    assert not contains_digest(_decode("3 rlrf"), LB_A_CORE_DIGEST, 5, normalize=False)
    assert contains_digest(_decode("3 rlrf"), LB_A_CORE_DIGEST, 5, normalize=True)


@pytest.mark.parametrize("text", [
    "Ares Strategische Portfolioanalyse",
    "eyes only, 3 keys, 5 years, wealth architecture",
    "Vier-Augen-Prinzip und drei Wochen",
    "",
])
def test_neutral_text_is_clean(text):
    assert brand_ids_in_text(text) == set()
    assert_no_legacy_brand(text, "neutral")


def test_brand_filter_restricts_to_selected_brands():
    text = _decode("5rlrf")
    assert brand_ids_in_text(text, ("LB-A",)) == set()
    assert brand_ids_in_text(text, ("LB-B",)) == {"LB-B"}
    assert brand_ids_in_text(text, ALL_BRANDS) == {"LB-B"}


def test_frontend_digest_list_matches_python():
    """Die TS-Kopie fuer die Reporting-Tests muss dieselben Digests tragen."""
    import re
    from pathlib import Path

    ts = (
        Path(__file__).resolve().parents[2]
        / "ares-desktop" / "frontend" / "reporting" / "src" / "test" / "brandDigest.ts"
    ).read_text(encoding="utf-8")
    entries = tuple(
        (brand, int(length), digest)
        for brand, length, digest in re.findall(
            r"\['(LB-[ABC])', (\d+), '([0-9a-f]{64})'\]", ts,
        )
    )
    assert entries == LEGACY_BRAND_STEM_DIGESTS
