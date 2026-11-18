"""Inventory customer-visible rounding/formatting sites at an immutable SHA."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_SHA = "53437853a5b3cbce08e6484eba30e4bfc1aa6d8c"
PATTERN = re.compile(
    r"(?:\.toFixed\(|Intl\.NumberFormat|toLocaleString\(|Math\.round\(|"
    r"\bround\(|\.quantize\(|ROUND_HALF|(?:fmt|format)[A-Za-z_]*(?:Money|Currency|Chf|CHF|Pct|Percent|Bps|Rappen|Number)|"
    r":\.[0-9]+[f%])"
)


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _files(root: Path) -> dict[str, list[Path]]:
    classic = [root / "ares-desktop" / "frontend" / "ares.html"]
    react_root = root / "ares-desktop" / "frontend" / "reporting" / "src"
    react = [
        path for path in react_root.rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name and ".spec." not in path.name
        and "test" not in path.parts
    ]
    backend = root / "ares-backend"
    pdf = [backend / "routers" / "pdf_reports.py"]
    pdf.extend((backend / "services" / "pdf").rglob("*.py"))
    return {"classic": classic, "react": sorted(react), "pdf": sorted(set(pdf))}


def inventory(root: Path) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for channel, paths in _files(root).items():
        rows: list[dict[str, object]] = []
        for path in paths:
            if not path.is_file():
                raise ValueError(f"required source missing: {path.relative_to(root)}")
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if PATTERN.search(line):
                    rows.append({
                        "file": path.relative_to(root).as_posix(),
                        "line": number,
                        "source": line.strip()[:240],
                    })
        result[channel] = rows
    return result


def self_test() -> None:
    assert PATTERN.search("return (bps / 100).toFixed(1)")
    assert PATTERN.search('return f"{bps / 100:.1f}%"')
    assert PATTERN.search("return Math.round(value)")
    assert PATTERN.search("value.quantize(step, rounding=ROUND_HALF_UP)")
    assert not PATTERN.search("return value")
    print("SELF_TEST=PASS positive=4 negative=1")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--expected-sha", default=EXPECTED_SHA)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.self_test:
        self_test()
    if _head(root) != args.expected_sha:
        raise SystemExit("immutable SHA mismatch")
    data = inventory(root)
    payload = {
        "schema_version": 1,
        "head_sha": args.expected_sha,
        "counts": {channel: len(rows) for channel, rows in data.items()},
        "sites": data,
    }
    # ASCII JSON is deliberate: Windows audit shells may use cp1252.
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
