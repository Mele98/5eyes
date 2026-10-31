"""Architektur-Ratschen (F0-4 / A2 M1): Import-Zyklen, Lazy-Imports, Fan-out,
Schichtung Router -> Service -> Model und direkte Umgebungs-Leser.

Der eigentliche Gate ist ``test_backend_is_not_worse_than_baseline``: er
misst den heutigen Stand per AST und vergleicht ihn mit der committeten Basis
(``scripts/architecture_ratchets_baseline.json``). Die uebrigen Tests belegen
an einem Mini-Backend in ``tmp_path``, dass jede Verschlechterung mit
Datei:Zeile gemeldet und jede Verbesserung erkannt wird.

Das Skript wird per importlib geladen (wie test_engine_line_budget_gate.py);
die Datenbank wird nicht beruehrt.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
import time
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = BACKEND_ROOT / "scripts" / "check_architecture_ratchets.py"
BASELINE = BACKEND_ROOT / "scripts" / "architecture_ratchets_baseline.json"


@pytest.fixture(scope="module")
def gate():
    name = "check_architecture_ratchets_under_test"
    spec = importlib.util.spec_from_file_location(name, GATE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(name, None)


# --------------------------------------------------------------------------
# Gate auf dem echten Backend
# --------------------------------------------------------------------------


def test_gate_files_exist():
    assert GATE_SCRIPT.is_file()
    assert BASELINE.is_file()


def test_backend_is_not_worse_than_baseline(gate):
    started = time.perf_counter()
    scans = gate.scan_backend()
    current = gate.measure(scans)
    result = gate.compare(current, gate.load_baseline(), scans)
    elapsed = time.perf_counter() - started
    for line in result.improvements:
        print(f"VERBESSERT {line} -> Basis mit --update-baseline absenken")
    assert not result.regressions, (
        "Architektur-Ratsche verletzt (Basis wird nie angehoben):\n"
        + "\n".join(result.regressions)
    )
    assert elapsed < 10, f"Ratschen-Messung dauerte {elapsed:.1f}s (Budget 10s)"


def test_measurement_is_deterministic_and_paths_are_normalised(gate):
    first = gate.measure(gate.scan_backend())
    second = gate.measure(gate.scan_backend())
    assert gate.dump_baseline(first) == gate.dump_baseline(second)
    for path in first["env_readers"]:
        assert "\\" not in path and not Path(path).is_absolute()


def test_baseline_file_is_in_canonical_form(gate):
    text = BASELINE.read_text(encoding="utf-8")
    assert "\r" not in text
    assert gate.dump_baseline(json.loads(text)) == text
    assert set(json.loads(text)) == {
        "cycles_eager",
        "cycles_all",
        "lazy_imports",
        "fan_out",
        "layer_violations",
        "env_readers",
    }


def test_config_module_is_the_only_unrestricted_env_reader(gate):
    assert gate.CONFIG_MODULES == frozenset({"config"})
    assert "config.py" not in gate.load_baseline()["env_readers"]


# --------------------------------------------------------------------------
# Mini-Backend: Verschlechterungen werden mit Datei:Zeile gemeldet
# --------------------------------------------------------------------------


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")


@pytest.fixture()
def mini(tmp_path):
    root = tmp_path / "backend"
    _write(root, "config.py", "import os\nDB = os.environ.get('DB_PATH')\n")
    _write(root, "models/__init__.py", "")
    _write(root, "models/base.py", "import config\n")
    _write(root, "services/alpha.py", "from models import base\n")
    _write(
        root,
        "services/beta.py",
        """
        from typing import TYPE_CHECKING
        from services import alpha
        if TYPE_CHECKING:
            from routers import api
        def run():
            from services import gamma
            return gamma
        """,
    )
    _write(root, "services/gamma.py", "def f():\n    from services import beta\n    return beta\n")
    _write(root, "routers/__init__.py", "")
    _write(root, "routers/api.py", "from services import beta\n")
    _write(root, "tests/test_x.py", "from routers import api\nimport os\nos.getenv('X')\n")
    return root


def _check(gate, root: Path, baseline: dict):
    scans = gate.scan_backend(root)
    current = gate.measure(scans)
    return current, gate.compare(current, baseline, scans)


def _baseline(gate, root: Path) -> dict:
    return json.loads(gate.dump_baseline(gate.measure(gate.scan_backend(root))))


def test_mini_backend_measurement(gate, mini):
    current = gate.measure(gate.scan_backend(mini))
    assert current["cycles_eager"] == []
    assert current["cycles_all"] == [["services.beta", "services.gamma"]]
    assert current["lazy_imports"] == {"services.beta": 1, "services.gamma": 1}
    # TYPE_CHECKING-Import zaehlt nicht als Fan-out, wohl aber als Schichtverletzung
    assert current["fan_out"]["services.beta"] == ["services.alpha", "services.gamma"]
    assert current["layer_violations"] == ["services.beta -> routers.api"]
    # config.py ist erlaubt, tests/ wird nicht gescannt
    assert current["env_readers"] == {}
    assert "tests.test_x" not in gate.scan_backend(mini)


def test_unchanged_mini_backend_passes(gate, mini):
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert result.regressions == []
    assert result.improvements == []


def test_new_lazy_import_is_reported_with_file_and_line(gate, mini):
    base = _baseline(gate, mini)
    _write(mini, "services/alpha.py", "from models import base\ndef g():\n    import config\n")
    _, result = _check(gate, mini, base)
    assert any(
        r.startswith("[lazy_imports] services.alpha: 1 > Basis 0") and "services/alpha.py:3 -> config" in r
        for r in result.regressions
    ), result.regressions


def test_new_cycle_is_reported_with_closing_edge(gate, mini):
    base = _baseline(gate, mini)
    _write(mini, "models/base.py", "import config\nfrom services import alpha\n")
    _, result = _check(gate, mini, base)
    cycle = [r for r in result.regressions if r.startswith("[cycles_eager]")]
    assert cycle and "models/base.py:2" in cycle[0], result.regressions


def test_merging_existing_cycles_is_a_regression(gate, mini):
    base = _baseline(gate, mini)
    _write(mini, "services/alpha.py", "from models import base\ndef h():\n    from services import gamma\n")
    _write(mini, "services/gamma.py", "def f():\n    from services import beta, alpha\n    return beta, alpha\n")
    _, result = _check(gate, mini, base)
    assert any(r.startswith("[cycles_all]") for r in result.regressions), result.regressions


def test_fewer_but_larger_cycles_are_not_an_improvement(gate, mini):
    _write(mini, "services/delta.py", "def f():\n    from services import eps\n")
    _write(mini, "services/eps.py", "from services import delta\n")
    base = _baseline(gate, mini)
    assert len(base["cycles_all"]) == 2
    _write(mini, "services/eps.py", "from services import delta\ndef g():\n    from services import beta\n")
    _write(mini, "services/gamma.py", "def f():\n    from services import beta, delta\n    return beta\n")
    current, result = _check(gate, mini, base)
    assert len(current["cycles_all"]) == 1
    assert any(r.startswith("[cycles_all]") for r in result.regressions), result.regressions
    assert not any(i.startswith("[cycles_all]") for i in result.improvements), result.improvements


def test_new_layer_violation_is_reported(gate, mini):
    base = _baseline(gate, mini)
    _write(mini, "models/base.py", "import config\nfrom routers import api\n")
    _, result = _check(gate, mini, base)
    assert "[layer_violations] models.base -> routers.api (models/base.py:2)" in result.regressions


def test_models_must_not_import_services(gate, mini):
    base = _baseline(gate, mini)
    _write(mini, "models/base.py", "import config\n\ndef f():\n    from services import alpha\n")
    _, result = _check(gate, mini, base)
    assert "[layer_violations] models.base -> services.alpha (models/base.py:4)" in result.regressions


@pytest.mark.parametrize(
    "body, key",
    [
        ("import os\nX = os.getenv('NEW_KEY')\n", "NEW_KEY"),
        ("import os\nX = os.environ['NEW_KEY']\n", "NEW_KEY"),
        ("import os as _o\nX = _o.environ.get('NEW_KEY', '')\n", "NEW_KEY"),
        ("from os import environ\n", "<from os import environ>"),
    ],
)
def test_new_env_reader_outside_config_is_reported(gate, mini, body, key):
    base = _baseline(gate, mini)
    _write(mini, "services/alpha.py", "from models import base\n" + body)
    _, result = _check(gate, mini, base)
    assert any(
        r.startswith("[env_readers] services/alpha.py: 1 > Basis 0") and "services/alpha.py:" in r and key in r
        for r in result.regressions
    ), result.regressions


def test_fan_out_growth_is_reported(gate, mini):
    base = _baseline(gate, mini)
    _write(mini, "services/alpha.py", "from models import base\nimport config\n")
    _, result = _check(gate, mini, base)
    assert any(
        r.startswith("[fan_out] services.alpha: 2 > Basis 1") and "services/alpha.py:2 -> config" in r
        for r in result.regressions
    ), result.regressions


def test_new_module_fan_out_limit(gate, mini):
    for i in range(gate.NEW_MODULE_FAN_OUT_LIMIT + 1):
        _write(mini, f"services/leaf{i:02d}.py", "")
    base = _baseline(gate, mini)
    imports = "".join(f"from services import leaf{i:02d}\n" for i in range(gate.NEW_MODULE_FAN_OUT_LIMIT + 1))
    _write(mini, "services/hub.py", imports)
    _, result = _check(gate, mini, base)
    assert any(r.startswith("[fan_out] services.hub:") for r in result.regressions)


def test_improvement_is_reported_and_not_a_failure(gate, mini):
    base = _baseline(gate, mini)
    _write(mini, "services/gamma.py", "def f():\n    return None\n")
    _write(mini, "services/beta.py", "from services import alpha\n")
    _, result = _check(gate, mini, base)
    assert result.regressions == []
    joined = "\n".join(result.improvements)
    assert "[cycles_all]" in joined
    assert "[lazy_imports] services.beta" in joined
    assert "[layer_violations] services.beta -> routers.api entfernt" in joined


def test_update_baseline_refuses_to_raise(gate, mini, tmp_path, monkeypatch):
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(gate.dump_baseline(gate.measure(gate.scan_backend(mini))), encoding="utf-8")
    monkeypatch.setattr(gate, "BACKEND_ROOT", mini)
    monkeypatch.setattr(gate, "BASELINE_FILE", baseline_file)
    before = baseline_file.read_text(encoding="utf-8")

    _write(mini, "services/alpha.py", "from models import base\ndef g():\n    import config\n")
    assert gate.main(["--update-baseline"]) == 1
    assert baseline_file.read_text(encoding="utf-8") == before

    _write(mini, "services/alpha.py", "from models import base\n")
    _write(mini, "services/gamma.py", "def f():\n    return None\n")
    assert gate.main(["--update-baseline"]) == 0
    lowered = json.loads(baseline_file.read_text(encoding="utf-8"))
    assert lowered["cycles_all"] == []
    assert lowered["lazy_imports"] == {"services.beta": 1}
