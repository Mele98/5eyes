"""Liste der Pfade fuer den Clean-Room-Export.

Liest ``docs/DOCS_MANIFEST.md`` und die getrackten Dateien eines Commits und
gibt alle Pfade aus, die nicht ``ARCHIVE`` sind: sortiert, einer pro Zeile,
UTF-8 mit LF. Gleicher Commit ergibt byte-identische Ausgabe.

Aufruf (vom Repo-Root oder von irgendwo im Repo):

    python scripts/clean_room_export_list.py              # Exportliste fuer HEAD
    python scripts/clean_room_export_list.py --rev <sha>  # fuer einen Commit
    python scripts/clean_room_export_list.py --check      # Manifest vollstaendig?

``--check`` endet mit Exit 1, wenn eine Datei im Manifest-Umfang (alles unter
``docs/`` und jede ``*.md``) weder in der Dateitabelle steht noch von einer
Regel erfasst ist, wenn ein Pfad doppelt gefuehrt ist oder wenn eine
KEEP-Zeile auf einen Pfad zeigt, den es im Commit nicht gibt. ARCHIVE-Zeilen
ohne Datei sind erlaubt, weil der Export sie weglaesst.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_PATH = "docs/DOCS_MANIFEST.md"
_ROW = re.compile(r"^\| `([^`]+)` \| (KEEP|ARCHIVE) \| .+ \|$")


class ManifestError(Exception):
    pass


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True
    ).stdout


def repo_root(start: Path | None = None) -> Path:
    here = start or Path(__file__).resolve().parent
    out = _git(here, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    return Path(out)


def tracked_files(repo: Path, rev: str) -> list[str]:
    raw = _git(repo, "ls-tree", "-r", "-z", "--name-only", rev)
    return sorted(p for p in raw.decode("utf-8").split("\0") if p)


def read_manifest(repo: Path, rev: str) -> str:
    return _git(repo, "show", f"{rev}:{MANIFEST_PATH}").decode("utf-8")


def parse_manifest(text: str) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """(Regeln in Reihenfolge, Dateieintraege) aus den Tabellen ``## Regeln``
    und ``## Dateien``."""
    rules: list[tuple[str, str]] = []
    files: dict[str, str] = {}
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = _ROW.match(line)
        if not m:
            continue
        path, status = m.group(1), m.group(2)
        if section == "Regeln":
            rules.append((path, status))
        elif section == "Dateien":
            if path in files:
                raise ManifestError(f"doppelt gefuehrt: {path}")
            files[path] = status
    if not rules and not files:
        raise ManifestError("Manifest ohne Regeln und Dateien")
    return rules, files


def _rule_matches(pattern: str, path: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    regex = "".join("[^/]*" if c == "*" else re.escape(c) for c in pattern)
    return re.fullmatch(regex, path) is not None


def in_scope(path: str) -> bool:
    return path.startswith("docs/") or path.endswith(".md")


def classify(path: str, rules, files) -> str | None:
    """KEEP, ARCHIVE oder None (im Umfang, aber nicht erfasst)."""
    if path in files:
        return files[path]
    for pattern, status in rules:
        if _rule_matches(pattern, path):
            return status
    return None if in_scope(path) else "KEEP"


def export_list(repo: Path, rev: str = "HEAD") -> list[str]:
    rules, files = parse_manifest(read_manifest(repo, rev))
    out = []
    for path in tracked_files(repo, rev):
        status = classify(path, rules, files)
        if status is None:
            raise ManifestError(f"nicht klassifiziert: {path}")
        if status != "ARCHIVE":
            out.append(path)
    return out


def check(repo: Path, rev: str = "HEAD") -> list[str]:
    errors: list[str] = []
    try:
        rules, files = parse_manifest(read_manifest(repo, rev))
    except ManifestError as exc:
        return [str(exc)]
    tree = tracked_files(repo, rev)
    present = set(tree)
    for path in tree:
        if classify(path, rules, files) is None:
            errors.append(f"nicht klassifiziert: {path}")
    for path, status in sorted(files.items()):
        if status == "KEEP" and path not in present:
            errors.append(f"KEEP ohne Datei: {path}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rev", default="HEAD", help="Commit (Default HEAD)")
    ap.add_argument("--check", action="store_true", help="nur Manifest pruefen")
    args = ap.parse_args(argv)
    repo = repo_root()
    if args.check:
        errors = check(repo, args.rev)
        for e in errors:
            print(e, file=sys.stderr)
        return 1 if errors else 0
    try:
        paths = export_list(repo, args.rev)
    except ManifestError as exc:
        print(exc, file=sys.stderr)
        return 1
    sys.stdout.buffer.write("".join(p + "\n" for p in paths).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
