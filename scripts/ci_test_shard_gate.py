#!/usr/bin/env python
"""Completeness gate for the sharded backend test run (CI).

The backend suite runs in several matrix shards (pytest-split) and, inside
each shard, in several worker processes (pytest-xdist). Splitting must never
lose a test. This script is the mandatory control step of the aggregate job:

1. Selection: the node IDs every shard selected (``pytest --collect-only -q``
   with the shard's own ``--splits/--group/-m`` arguments) must form exactly
   the full collection of ``pytest --collect-only -q tests/``: no missing node
   ID, no node ID in two shards, no unknown node ID.
2. Execution: every collected node ID must appear as a test case in the merged
   JUnit XML of all shards (reruns count once; module-level collection skips
   are not test items and are ignored).
3. No test case may be reported as failure or error.

As by-products it writes a merged JUnit file and a pytest-split durations
file (``.test_durations`` format) built from the measured JUnit times, which
CI uploads as artifacts so the committed durations can be refreshed.

Only the standard library is used; the aggregate job needs no pip install.

Usage (repo root):
    python scripts/ci_test_shard_gate.py --collected collected.txt \
        --selection-dir sel/ --junit-dir junit/ \
        --merged-junit-out junit-merged.xml --durations-out test_durations.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

COLLECTION_SKIP_MESSAGE = "collection skipped"


def parse_collect_output(text: str) -> list[str]:
    """Node IDs from ``pytest --collect-only -q`` output (one per line)."""
    ids = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("tests/") and "::" in line:
            ids.append(line)
    return ids


def junit_key(node_id: str) -> tuple[str, str]:
    """(classname, name) exactly as pytest's junitxml derives them from a node ID."""
    path, bracket, params = node_id.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


@dataclass
class JunitResult:
    durations: dict[tuple[str, str], float] = field(default_factory=dict)
    failed: set[tuple[str, str]] = field(default_factory=set)
    collection_skips: int = 0
    suites: list[ET.Element] = field(default_factory=list)


def read_junit(files: list[Path]) -> JunitResult:
    result = JunitResult()
    for path in sorted(files):
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        result.suites.extend(suites)
        for suite in suites:
            for case in suite.iter("testcase"):
                key = (case.get("classname", ""), case.get("name", ""))
                skipped = case.find("skipped")
                if skipped is not None and skipped.get("message") == COLLECTION_SKIP_MESSAGE:
                    result.collection_skips += 1
                    continue
                result.durations[key] = float(case.get("time") or 0.0)
                if case.find("failure") is not None or case.find("error") is not None:
                    result.failed.add(key)
                else:
                    # A later passing rerun supersedes an earlier failed attempt.
                    result.failed.discard(key)
    return result


def check(collected: list[str], selections: dict[str, list[str]], junit: JunitResult) -> list[str]:
    """All violations of the completeness contract (empty list = gate passes)."""
    problems: list[str] = []
    collected_set = set(collected)
    if len(collected_set) != len(collected):
        problems.append(f"Collect-Liste enthaelt {len(collected) - len(collected_set)} doppelte Node-IDs.")

    owner: dict[str, str] = {}
    for shard, ids in sorted(selections.items()):
        for node_id in ids:
            if node_id in owner:
                problems.append(f"Doppelt selektiert: {node_id} ({owner[node_id]} und {shard})")
            owner[node_id] = shard
    missing = sorted(collected_set - set(owner))
    unknown = sorted(set(owner) - collected_set)
    for node_id in missing[:50]:
        problems.append(f"In keinem Shard selektiert: {node_id}")
    if len(missing) > 50:
        problems.append(f"... und {len(missing) - 50} weitere nicht selektierte Tests")
    for node_id in unknown[:50]:
        problems.append(f"Selektiert, aber nicht in der Gesamt-Collection: {node_id}")

    keys = {junit_key(node_id): node_id for node_id in collected}
    if len(keys) != len(collected_set):
        problems.append("JUnit-Schluessel nicht eindeutig (classname/name-Kollision).")
    not_run = sorted(node_id for key, node_id in keys.items() if key not in junit.durations)
    for node_id in not_run[:50]:
        problems.append(f"Nicht ausgefuehrt (kein JUnit-Testfall): {node_id}")
    if len(not_run) > 50:
        problems.append(f"... und {len(not_run) - 50} weitere nicht ausgefuehrte Tests")
    extra = sorted(set(junit.durations) - set(keys))
    for key in extra[:50]:
        problems.append(f"JUnit-Testfall ohne gesammelten Test: {key}")
    for key in sorted(junit.failed)[:50]:
        problems.append(f"Fehlgeschlagen: {keys.get(key, key)}")
    return problems


def durations_by_node_id(collected: list[str], junit: JunitResult) -> dict[str, float]:
    out = {}
    for node_id in collected:
        key = junit_key(node_id)
        if key in junit.durations:
            out[node_id] = round(junit.durations[key], 4)
    return out


def print_file_summary(durations: dict[str, float], top: int) -> None:
    per_file: dict[str, float] = {}
    for node_id, seconds in durations.items():
        file_name = node_id.split("::", 1)[0]
        per_file[file_name] = per_file.get(file_name, 0.0) + seconds
    print(f"Summe gemessene Testzeit:   {sum(per_file.values()) / 60:.1f} min")
    for file_name, seconds in sorted(per_file.items(), key=lambda kv: -kv[1])[:top]:
        print(f"  {seconds:8.1f}s  {file_name}")


def merged_junit(junit: JunitResult) -> ET.ElementTree:
    root = ET.Element("testsuites")
    for suite in junit.suites:
        root.append(suite)
    return ET.ElementTree(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--collected", type=Path, required=True)
    parser.add_argument("--selection-dir", type=Path, required=True)
    parser.add_argument("--junit-dir", type=Path, required=True)
    parser.add_argument("--merged-junit-out", type=Path)
    parser.add_argument("--durations-out", type=Path)
    parser.add_argument("--file-summary", type=int, default=0, help="print the N slowest test files")
    args = parser.parse_args(argv)

    collected = parse_collect_output(args.collected.read_text(encoding="utf-8"))
    selection_files = sorted(args.selection_dir.rglob("*.txt"))
    selections = {
        path.stem: parse_collect_output(path.read_text(encoding="utf-8")) for path in selection_files
    }
    junit_files = sorted(args.junit_dir.rglob("*.xml"))
    junit = read_junit(junit_files)

    selected_total = sum(len(ids) for ids in selections.values())
    print(f"Gesamt-Collection:          {len(collected)} Tests")
    for name, ids in sorted(selections.items()):
        print(f"  Selektion {name}: {len(ids)}")
    print(f"Summe aller Selektionen:    {selected_total} ({len(selection_files)} Dateien)")
    print(f"JUnit-Testfaelle (eindeutig): {len(junit.durations)} aus {len(junit_files)} Dateien"
          f" (+{junit.collection_skips} Modul-Skips)")

    if args.merged_junit_out:
        merged_junit(junit).write(args.merged_junit_out, encoding="utf-8", xml_declaration=True)
    if args.durations_out:
        durations = durations_by_node_id(collected, junit)
        args.durations_out.write_text(json.dumps(durations, sort_keys=True, indent=4) + "\n", encoding="utf-8")
        print(f"Durations geschrieben:      {len(durations)} Eintraege -> {args.durations_out}")

    if args.file_summary:
        print_file_summary(durations_by_node_id(collected, junit), args.file_summary)

    if not collected:
        print("FEHLER: Gesamt-Collection ist leer.")
        return 1
    problems = check(collected, selections, junit)
    if problems:
        print(f"FEHLER: {len(problems)} Verletzung(en) der Vollstaendigkeit:")
        for line in problems:
            print(f"  - {line}")
        return 1
    print(f"OK: alle {len(collected)} Tests genau einmal selektiert und ausgefuehrt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
