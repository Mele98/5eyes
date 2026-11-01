"""Digest-basierte Markenpruefung fuer Guard-Tests (nur Tests, kein Produktcode).

Mehrere Guard-Tests stellen sicher, dass Altmarken (LB-A, LB-B, LB-C) weder in
PDFs noch in Texten, HTML oder Quelldateien auftauchen. Frueher standen dafuer
die verbotenen Namen als Klartext-Liste im Test. Dieses Modul ersetzt die
Klartext-Listen durch sha256-Digests der normalisierten Stammformen, analog
zum AST-Guard ``test_brand_identifier_ast_guard.py``:

1. Der zu pruefende Text wird normalisiert (casefold, ohne Leerraum, ``_``,
   ``-`` und ``.``).
2. Jedes Teilstring-Fenster der Laengen aus der Digest-Liste wird gehasht und
   gegen die Liste geprueft.
3. Ein Treffer meldet nur die Marken-ID, nie den Klartext.

Weil die Normalisierung nur Zeichen entfernt, bleibt jeder zusammenhaengende
Teilstring ohne Trennzeichen erhalten: Was ein frueherer Klartext-Vergleich
(``name in text.lower()``) fand, findet diese Pruefung ebenfalls; zusaetzlich
findet sie Schreibvarianten mit Leerzeichen, Bindestrich, Punkt, Unterstrich,
Zeilenumbruch und anderer Gross-/Kleinschreibung.

Die Digest-Liste ist mit der des AST-Guards identisch;
``test_brand_digest_support.py`` erzwingt das.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

# (Marken-ID, Fensterlaenge, sha256 der normalisierten Stammform).
# Die Klartexte stehen bewusst nirgends im Repo.
LEGACY_BRAND_STEM_DIGESTS: tuple[tuple[str, int, str], ...] = (
    ("LB-A", 5, "0b3e941a5b9ba6737e1ca686861781649750602fe7d7b7ea1b69f0f748a38d10"),
    ("LB-A", 9, "5368038931b4b7738a9414a5e44e2bb1b0634a5697e74367e8aec126c68bf686"),
    ("LB-A", 8, "afe600a48993336a29ec7149fd5eaa40f624ca07607ed9482327aa8b821d52b6"),
    ("LB-A", 7, "cbf143aa86f46c9b838b1dd39a44a351cfe7a854b36af4285bbb917fc3389144"),
    ("LB-A", 7, "3cb4e57e94e2e647cc9b8add3760c1e782d272a6b51874fd055d93fbe2edd3aa"),
    ("LB-A", 9, "14150de8f78b00e2f11ac18c3f0486cf40c515cc08d169621b847be93290f9a4"),
    ("LB-A", 9, "6388c06527a4bbf6c7bdbd92f2eefa400100f6c08ee4fcd0fd49475937dc87d5"),
    ("LB-A", 6, "6b09459ae231ff92ef88487a42ef6139e6611d6719033638000e2ce82825edc4"),
    ("LB-B", 5, "681aab74af1a2a039ff95a500da3f289290163115a70a2af7ee07521e73793bc"),
    ("LB-B", 8, "ff70abe6ddd7cd7dd4745d7c406ba32cd02f50cd8e0b34afa4ab3f655032f97d"),
    ("LB-B", 7, "039012b91782665fc291837cfb12913f4127f2a8d4aafde62a33c1bfbed74c8f"),
    ("LB-B", 6, "2576b6daab292235425bf476d633e28d5392913bf679150ff0bb10c692a38c01"),
    ("LB-B", 10, "015234568dea9d0f9768a7b9a89290975e7bef330b89e14fa36e041ecdc1635b"),
    ("LB-B", 9, "f75b1da0e9b9f0fa143654fd9526c094ce1382b0da18743197389b5199f78d4e"),
    ("LB-B", 9, "e37c538c41ca211c0c508b14b8c980cf151d000e647f08357fddd9fc7d7d1e66"),
    ("LB-B", 6, "be7e13c66160dc917e44d6ca6f590f5f6c7e339e95df4d127e79684002a3ab98"),
    ("LB-C", 15, "bdff65fea8937f64d38ec27eb9c7b431ecd2d64771deaad58db4a69d994d4181"),
    ("LB-C", 16, "17658fd47e49afdf01f8c3dea7540b4e580fbdd1941a18031d9f1b3350b57231"),
)

# Kernform von LB-A (Kurzform aus Ziffer und Wort). Frueher als einzelnes
# Klartext-Literal in den Guard-Listen; hier nur als Digest.
LB_A_CORE_DIGEST = LEGACY_BRAND_STEM_DIGESTS[0][2]

ALL_BRANDS: tuple[str, ...] = ("LB-A", "LB-B", "LB-C")

_SEPARATORS = re.compile(r"[\s_.\-]+")


def normalize_text(text: str) -> str:
    """casefold und alle Trennzeichen (Leerraum, ``_``, ``-``, ``.``) entfernen."""
    return _SEPARATORS.sub("", text.casefold())


def _select(brands: Iterable[str] | None,
            digests: Iterable[tuple[str, int, str]] | None) -> tuple[tuple[str, int, str], ...]:
    pool = tuple(LEGACY_BRAND_STEM_DIGESTS if digests is None else digests)
    if brands is None:
        return pool
    wanted = set(brands)
    return tuple(entry for entry in pool if entry[0] in wanted)


def brand_ids_in_text(
    text: str,
    brands: Iterable[str] | None = None,
    *,
    digests: Iterable[tuple[str, int, str]] | None = None,
    normalize: bool = True,
) -> set[str]:
    """Marken-IDs, deren Stammform-Digest in ``text`` vorkommt."""
    selected = _select(brands, digests)
    by_length: dict[int, dict[str, str]] = {}
    for brand, length, digest in selected:
        by_length.setdefault(length, {})[digest] = brand
    haystack = normalize_text(text) if normalize else text
    found: set[str] = set()
    for length, table in by_length.items():
        for start in range(0, len(haystack) - length + 1):
            window = haystack[start:start + length].encode("utf-8")
            brand = table.get(hashlib.sha256(window).hexdigest())
            if brand:
                found.add(brand)
    return found


def contains_digest(text: str, digest: str, length: int, *, normalize: bool = True) -> bool:
    """True, wenn ein Fenster der Laenge ``length`` den sha256 ``digest`` hat."""
    return bool(brand_ids_in_text(
        text, digests=(("X", length, digest),), normalize=normalize,
    ))


def assert_no_legacy_brand(text: str, where: str, brands: Iterable[str] = ALL_BRANDS) -> None:
    """Fail, wenn eine Altmarke in ``text`` vorkommt. Meldet nur die Marken-ID."""
    hits = brand_ids_in_text(text, brands)
    assert not hits, f"Altmarke {sorted(hits)} in {where} gefunden (Branding-Disziplin)"
