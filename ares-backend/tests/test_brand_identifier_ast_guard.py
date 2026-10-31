"""AST-Guard: keine Altmarken in Python-Identifiern (Audit-Befund W2-804-05).

Prueft repo-weit jeden Python-Identifier (Namen, Attribute, Funktions- und
Klassennamen, Argumente, Keyword-Argumente, Imports inkl. Modulpfade,
global/nonlocal, except-/match-Bindungen) gegen eine Liste verbotener
Stammformen der Altmarken LB-A, LB-B und LB-C.

Damit dieser Guard selbst keine Altnamen im Klartext enthaelt, stehen die
Stammformen nur als sha256-Digests im Code. Jeder Identifier wird normalisiert
(casefold, ohne ``_``, ``-`` und ``.``); danach wird jedes Teilstring-Fenster
der Laengen, die in der Digest-Liste vorkommen, gehasht und gegen die Liste
geprueft. Ein Treffer meldet nur Datei:Zeile und die Marken-ID.

Fail-closed:
- Eine Datei, die nicht geparst werden kann, ist ein Fehler (kein Skip).
- Die Negativfixture beweist, dass ein Digest-Treffer in jeder unterstuetzten
  AST-Knotenart gefunden wird; sie benutzt einen Kunstnamen, dessen Digest nur
  in einer test-only-Liste steht.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
from typing import Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]

# (Marken-ID, Fensterlaenge, sha256 der normalisierten Stammform).
# Die Klartexte stehen bewusst nirgends im Repo.
FORBIDDEN_STEM_DIGESTS: tuple[tuple[str, int, str], ...] = (
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

# Nur fuer die Negativfixture: Digest eines Kunstnamens ohne Markenbezug.
# Der Kunstname wird in der Fixture zur Laufzeit in wechselnder Schreibweise
# zusammengesetzt; der Guard kennt ihn nur ueber diesen Digest.
_FIXTURE_STEM = ("zorb", "lax", "quux")
TEST_ONLY_DIGESTS: tuple[tuple[str, int, str], ...] = (
    ("FIXTURE", 11, "7da77b6606a4c25793bb72e29c78591a29dde9b06021923643799da20f617bb2"),
)

_SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
    ".tox", "site-packages",
})


def normalize(identifier: str) -> str:
    return identifier.casefold().replace("_", "").replace("-", "").replace(".", "")


def iter_identifiers(tree: ast.AST) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name):
            yield line, node.id
        elif isinstance(node, ast.Attribute):
            yield line, node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield line, node.name
        elif isinstance(node, ast.arg):
            yield line, node.arg
        elif isinstance(node, ast.keyword) and node.arg:
            yield line, node.arg
        elif isinstance(node, ast.alias):
            yield line, node.name
            if node.asname:
                yield line, node.asname
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield line, node.module
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                yield line, name
        elif isinstance(node, ast.ExceptHandler) and node.name:
            yield line, node.name
        elif isinstance(node, ast.MatchAs) and node.name:
            yield line, node.name
        elif isinstance(node, ast.MatchStar) and node.name:
            yield line, node.name
        elif isinstance(node, ast.MatchMapping) and node.rest:
            yield line, node.rest
        elif isinstance(node, ast.MatchClass):
            for attr in node.kwd_attrs:
                yield line, attr


def brand_ids_in(identifier: str, digests: Iterable[tuple[str, int, str]]) -> set[str]:
    by_digest: dict[str, str] = {}
    lengths: set[int] = set()
    for brand, length, digest in digests:
        by_digest[digest] = brand
        lengths.add(length)
    norm = normalize(identifier)
    found: set[str] = set()
    for length in lengths:
        for start in range(0, len(norm) - length + 1):
            window = norm[start:start + length].encode("utf-8")
            brand = by_digest.get(hashlib.sha256(window).hexdigest())
            if brand:
                found.add(brand)
    return found


def iter_python_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def scan(root: Path, digests: Iterable[tuple[str, int, str]]) -> tuple[list[str], list[str], int]:
    digests = tuple(digests)
    hits: list[str] = []
    parse_errors: list[str] = []
    files = 0
    for path in iter_python_files(root):
        files += 1
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            parse_errors.append(f"{rel}: {type(exc).__name__}")
            continue
        for line, identifier in iter_identifiers(tree):
            for brand in sorted(brand_ids_in(identifier, digests)):
                hits.append(f"{rel}:{line} {brand}")
    return sorted(set(hits)), parse_errors, files


def test_digest_list_is_well_formed():
    assert len(FORBIDDEN_STEM_DIGESTS) == 18
    digests = [d for _, _, d in FORBIDDEN_STEM_DIGESTS]
    assert len(set(digests)) == len(digests)
    for brand, length, digest in FORBIDDEN_STEM_DIGESTS + TEST_ONLY_DIGESTS:
        assert brand in {"LB-A", "LB-B", "LB-C", "FIXTURE"}
        assert length >= 5
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert not set(digests) & {d for _, _, d in TEST_ONLY_DIGESTS}


def test_no_python_identifier_contains_legacy_brand_stem():
    hits, parse_errors, files = scan(REPO_ROOT, FORBIDDEN_STEM_DIGESTS)
    # Plausibilitaet: der Scan muss das Backend tatsaechlich erfassen.
    assert files > 500, f"Scan erfasste nur {files} Python-Dateien unter {REPO_ROOT}"
    # Fail-closed: nicht parsebare Dateien sind ein Fehler, kein stiller Skip.
    assert not parse_errors, "Nicht parsebare Python-Dateien:\n" + "\n".join(parse_errors)
    assert not hits, (
        "Python-Identifier mit Altmarken-Stamm gefunden (Datei:Zeile Marke):\n"
        + "\n".join(hits)
    )


def _fixture_variant(style: str) -> str:
    a, b, c = _FIXTURE_STEM
    return {
        "upper": f"{a}_{b}_{c}".upper(),
        "camel": f"{a.capitalize()}{b.capitalize()}{c.capitalize()}",
        "snake": f"{a}_{b}{c}",
        "embedded": f"get_{a}{b}_{c}_value",
        "plain": f"{a}{b}{c}",
    }[style]


def test_negative_fixture_is_caught_in_every_node_kind(tmp_path):
    """Synthetische Negativfixture: der Guard muss einen Digest-Treffer finden.

    Der Kunstname wird zur Laufzeit zusammengesetzt und in jede unterstuetzte
    Identifier-Position geschrieben. Mit der test-only-Digestliste muss jede
    Position gemeldet werden; mit der Produktivliste allein darf sie es nicht
    (beweist, dass der Treffer genau ueber den Digest zustande kommt).
    """
    v = _fixture_variant
    source = "\n".join([
        f"import os as {v('snake')}_mod",                                   # 1 alias.asname
        f"from pkg.{v('plain')} import thing",                              # 2 ImportFrom.module
        f"from pkg import {v('embedded')}",                                 # 3 alias.name
        f"{v('upper')} = 1",                                                # 4 Name
        f"def {v('embedded')}_fn({v('snake')}_arg, *, other=None):",        # 5 def + arg
        f"    global {v('snake')}_g",                                       # 6 Global
        f"    return os.{v('camel')}",                                      # 7 Attribute
        f"class {v('camel')}Model:",                                        # 8 ClassDef
        "    pass",                                                         # 9
        f"call(x, {v('snake')}_kw=1)",                                      # 10 keyword
        "try:",                                                             # 11
        "    pass",                                                         # 12
        f"except Exception as {v('snake')}_exc:",                           # 13 ExceptHandler
        "    pass",                                                         # 14
        "match value:",                                                     # 15
        f"    case {{'k': 1, **{v('snake')}_rest}}:",                       # 16 MatchMapping.rest
        "        pass",                                                     # 17
        f"    case [first, *{v('snake')}_star]:",                           # 18 MatchStar
        "        pass",                                                     # 19
        f"    case Point({v('snake')}_attr=1):",                            # 20 MatchClass kwd
        "        pass",                                                     # 21
        f"    case {v('snake')}_bound:",                                    # 22 MatchAs
        "        pass",                                                     # 23
        "neutral_name = other_value",                                       # 24 kein Treffer
    ]) + "\n"
    (tmp_path / "fixture_module.py").write_text(source, encoding="utf-8")

    hits, parse_errors, files = scan(tmp_path, FORBIDDEN_STEM_DIGESTS + TEST_ONLY_DIGESTS)
    assert files == 1 and not parse_errors
    hit_lines = {int(h.split(":")[1].split()[0]) for h in hits}
    expected = {1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 16, 18, 20, 22}
    assert hit_lines == expected, f"fehlend={sorted(expected - hit_lines)} extra={sorted(hit_lines - expected)}"
    assert all(h.endswith(" FIXTURE") for h in hits)

    prod_hits, _, _ = scan(tmp_path, FORBIDDEN_STEM_DIGESTS)
    assert prod_hits == []


def test_unparseable_file_is_reported_not_skipped(tmp_path):
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    hits, parse_errors, files = scan(tmp_path, FORBIDDEN_STEM_DIGESTS)
    assert files == 1
    assert parse_errors == ["broken.py: SyntaxError"]
    assert hits == []


def test_normalization_folds_case_and_separators():
    a, b, c = _FIXTURE_STEM
    for spelled in (f"{a}-{b}-{c}", f"{a}.{b}.{c}", f"{a.upper()}_{b}_{c.title()}"):
        assert brand_ids_in(spelled, TEST_ONLY_DIGESTS) == {"FIXTURE"}
    assert brand_ids_in(f"{a}_{b}", TEST_ONLY_DIGESTS) == set()
