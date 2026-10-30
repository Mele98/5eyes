"""Contract of scripts/ci_test_shard_gate.py (completeness gate of the sharded CI run).

The gate must pass only when every collected test was selected by exactly one
shard and appears in the merged JUnit output. The probe suite is executed by a
real pytest subprocess so the node-ID -> JUnit mapping is checked against
pytest's own JUnit writer (classes, parametrisation, module-level skip).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "ci_test_shard_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("ci_test_shard_gate", GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


gate = _load_gate()

_PROBE = """
import pytest


@pytest.mark.parametrize("value", [1, "a-b", "x y"])
def test_param(value):
    assert value


class TestGroup:
    def test_inside_class(self):
        pass

    @pytest.mark.xfail(reason="probe", strict=True)
    def test_expected_failure(self):
        raise AssertionError


def test_skipped():
    pytest.skip("probe")
"""


@pytest.fixture(scope="module")
def probe_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("gate_probe")
    (root / "tests" / "sub").mkdir(parents=True)
    (root / "tests" / "test_alpha.py").write_text(textwrap.dedent(_PROBE), encoding="utf-8")
    (root / "tests" / "sub" / "test_beta.py").write_text("def test_beta():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_modskip.py").write_text(
        "import pytest\npytest.importorskip('module_that_does_not_exist_probe')\n", encoding="utf-8"
    )
    base = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:randomly", "tests"]
    collect = subprocess.run(
        [*base, "--collect-only", "-q"], cwd=root, capture_output=True, text=True, timeout=120
    )
    junit_dir = root / "junit"
    junit_dir.mkdir()
    run = subprocess.run(
        [*base, "-q", "-o", "junit_family=xunit1", f"--junit-xml={junit_dir / 'all.xml'}"],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    collected = gate.parse_collect_output(collect.stdout)
    return root, collected, junit_dir


def _write_selection(root: Path, name: str, shards: list[list[str]]) -> Path:
    sel = root / name
    sel.mkdir()
    for index, ids in enumerate(shards, start=1):
        (sel / f"shard-{index}.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    return sel


def test_probe_collection_is_complete(probe_run):
    _root, collected, _junit = probe_run
    assert len(collected) == 7
    assert "tests/test_alpha.py::test_param[x y]" in collected
    assert "tests/test_alpha.py::TestGroup::test_inside_class" in collected


def test_gate_passes_for_a_complete_split(probe_run, tmp_path):
    root, collected, junit_dir = probe_run
    sel = _write_selection(tmp_path, "sel", [collected[:3], collected[3:]])
    collected_file = tmp_path / "collected.txt"
    collected_file.write_text("\n".join(collected) + "\n", encoding="utf-8")
    durations = tmp_path / "durations.json"

    rc = gate.main([
        "--collected", str(collected_file), "--selection-dir", str(sel), "--junit-dir", str(junit_dir),
        "--durations-out", str(durations), "--merged-junit-out", str(tmp_path / "merged.xml"),
        "--file-summary", "3",
    ])

    assert rc == 0
    assert set(json.loads(durations.read_text(encoding="utf-8"))) == set(collected)
    assert (tmp_path / "merged.xml").is_file()


def test_gate_fails_when_a_shard_lost_a_test(probe_run, tmp_path):
    _root, collected, junit_dir = probe_run
    junit = gate.read_junit(sorted(junit_dir.glob("*.xml")))
    problems = gate.check(collected, {"shard-1": collected[:3], "shard-2": collected[4:]}, junit)
    assert any("In keinem Shard selektiert" in p and collected[3] in p for p in problems)


def test_gate_fails_on_duplicate_selection(probe_run):
    _root, collected, junit_dir = probe_run
    junit = gate.read_junit(sorted(junit_dir.glob("*.xml")))
    problems = gate.check(collected, {"shard-1": collected, "shard-2": collected[:1]}, junit)
    assert any(p.startswith("Doppelt selektiert") for p in problems)


def test_gate_fails_when_a_selected_test_never_ran(probe_run):
    _root, collected, junit_dir = probe_run
    junit = gate.read_junit(sorted(junit_dir.glob("*.xml")))
    victim = gate.junit_key(collected[0])
    del junit.durations[victim]
    problems = gate.check(collected, {"shard-1": collected}, junit)
    assert any(p.startswith("Nicht ausgefuehrt") and collected[0] in p for p in problems)


def test_gate_reports_failed_test_cases(probe_run):
    _root, collected, junit_dir = probe_run
    junit = gate.read_junit(sorted(junit_dir.glob("*.xml")))
    junit.failed.add(gate.junit_key(collected[0]))
    problems = gate.check(collected, {"shard-1": collected}, junit)
    assert any(p.startswith("Fehlgeschlagen") for p in problems)


def test_module_level_skip_is_not_counted_as_a_test(probe_run):
    _root, _collected, junit_dir = probe_run
    junit = gate.read_junit(sorted(junit_dir.glob("*.xml")))
    assert junit.collection_skips == 1


# ---------------------------------------------------------------------------
# CI-ARTIFACT-UPLOAD-001: fehlendes Teilergebnis = Infrastruktur-Fehler
# ---------------------------------------------------------------------------
# Run 40775202093: Shard 7 bestand alle Tests, der Artefakt-Upload brach mit
# ECONNRESET ab. Das Aggregat meldete nur hunderte "In keinem Shard
# selektiert"/"Nicht ausgefuehrt" -- ohne Hinweis, dass ein ganzes Artefakt
# fehlte. Der Gate bleibt rot, nennt die Ursache aber zuerst und eindeutig.


def _gate_inputs(probe_run, tmp_path, runs_with_results):
    _root, collected, junit_dir = probe_run
    sel = tmp_path / "sel"
    junit = tmp_path / "junit"
    sel.mkdir()
    junit.mkdir()
    half = len(collected) // 2
    parts = {"shard-1": collected[:half], "shard-2": collected[half:]}
    junit_xml = (junit_dir / "all.xml").read_text(encoding="utf-8")
    for name in runs_with_results:
        (sel / f"{name}.txt").write_text("\n".join(parts[name]) + "\n", encoding="utf-8")
        (junit / f"{name}.xml").write_text(junit_xml if name == "shard-1" else "<testsuites/>", encoding="utf-8")
    collected_file = tmp_path / "collected.txt"
    collected_file.write_text("\n".join(collected) + "\n", encoding="utf-8")
    return [
        "--collected", str(collected_file), "--selection-dir", str(sel), "--junit-dir", str(junit),
        "--expected-runs", "shard-1,shard-2",
    ], sel, junit


def test_gate_passes_when_all_expected_runs_reported(probe_run, tmp_path, capsys):
    args, _sel, _junit = _gate_inputs(probe_run, tmp_path, ["shard-1", "shard-2"])
    assert gate.main(args) == 0
    assert "Infrastruktur-Fehler" not in capsys.readouterr().out


def test_gate_names_a_missing_run_artifact_as_infrastructure_error(probe_run, tmp_path, capsys):
    args, _sel, _junit = _gate_inputs(probe_run, tmp_path, ["shard-1"])

    rc = gate.main(args)

    out = capsys.readouterr().out
    assert rc == gate.EXIT_INFRASTRUCTURE
    assert rc not in (0, 1)
    assert "::error title=Infrastruktur-Fehler" in out
    assert "shard-2" in out and "Selektion" in out and "JUnit" in out
    # Die Ursache steht vor den Folgebefunden; die Folgebefunde bleiben sichtbar.
    assert out.index("Infrastruktur-Fehler") < out.index("In keinem Shard selektiert")


def test_gate_flags_missing_junit_even_when_selection_arrived(probe_run, tmp_path, capsys):
    args, _sel, junit = _gate_inputs(probe_run, tmp_path, ["shard-1", "shard-2"])
    (junit / "shard-2.xml").unlink()

    assert gate.main(args) == gate.EXIT_INFRASTRUCTURE
    out = capsys.readouterr().out
    assert "shard-2" in out and "JUnit" in out


def test_gate_keeps_real_test_failures_visible_next_to_missing_artifacts(probe_run, tmp_path, capsys):
    args, _sel, junit = _gate_inputs(probe_run, tmp_path, ["shard-1"])
    import xml.etree.ElementTree as ET

    tree = ET.parse(junit / "shard-1.xml")
    victim = next(case for case in tree.getroot().iter("testcase") if len(case) == 0)
    victim.append(ET.Element("failure", message="boom"))
    tree.write(junit / "shard-1.xml", encoding="utf-8")

    assert gate.main(args) == gate.EXIT_INFRASTRUCTURE
    out = capsys.readouterr().out
    assert "Infrastruktur-Fehler" in out and "Fehlgeschlagen:" in out


def test_gate_names_a_missing_reference_collection_as_infrastructure_error(probe_run, tmp_path, capsys):
    args, _sel, _junit = _gate_inputs(probe_run, tmp_path, ["shard-1", "shard-2"])
    (tmp_path / "collected.txt").unlink()

    assert gate.main(args) == gate.EXIT_INFRASTRUCTURE
    assert "::error title=Infrastruktur-Fehler" in capsys.readouterr().out
