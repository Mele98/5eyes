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
def mini(tmp_path, gate, monkeypatch):
    # Das Mini-Backend hat keine echten Blattmodule; Regel 6 meldet gelistete,
    # aber fehlende Module, deshalb startet die Allowlist hier leer.
    monkeypatch.setattr(gate, "FAN_OUT_EXEMPT_LEAVES", frozenset())
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


# --------------------------------------------------------------------------
# Regel 6: Stdlib-Blattmodule (FAN_OUT_EXEMPT_LEAVES)
# --------------------------------------------------------------------------


def test_exempt_leaves_allowlist_is_explicit_and_versioned(gate):
    """Explizite Liste, keine Mustererkennung; jede Aufnahme ist ein Review-Entscheid."""
    assert gate.FAN_OUT_EXEMPT_LEAVES == frozenset({"core.evidence", "core.reason_codes"})


def test_every_exempt_leaf_exists_and_is_a_pure_stdlib_leaf(gate):
    scans = gate.scan_backend()
    for module in sorted(gate.FAN_OUT_EXEMPT_LEAVES):
        assert module in scans, f"{module} in FAN_OUT_EXEMPT_LEAVES, aber nicht im Backend"
        scan = scans[module]
        assert scan.non_stdlib_imports == [], (module, scan.non_stdlib_imports)
        assert scan.runtime_targets() == {} and scan.typeonly == {}, module


def _mini_with_leaf(gate, mini, monkeypatch, leaf_body: str):
    _write(mini, "core/__init__.py", "")
    _write(mini, "core/leaf.py", leaf_body)
    monkeypatch.setattr(gate, "FAN_OUT_EXEMPT_LEAVES", frozenset({"core.leaf"}))


def test_valid_stdlib_leaf_passes_and_does_not_count_as_fan_out(gate, mini, monkeypatch):
    _mini_with_leaf(
        gate, mini, monkeypatch,
        """
        from __future__ import annotations
        import hashlib
        import json
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from collections.abc import Mapping
        def f():
            import decimal
            return decimal
        """,
    )
    base = _baseline(gate, mini)
    _write(mini, "services/alpha.py", "from models import base\nfrom core import leaf\n")
    current, result = _check(gate, mini, base)
    assert result.regressions == []
    assert current["fan_out"]["services.alpha"] == ["models.base"]
    assert "core.leaf" not in current["fan_out"]


def test_module_outside_the_allowlist_still_counts(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/other.py", "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "services/alpha.py", "from models import base\nfrom core import other\n")
    _, result = _check(gate, mini, base)
    assert any(r.startswith("[fan_out] services.alpha: 2 > Basis 1") for r in result.regressions)


@pytest.mark.parametrize(
    "body,needle",
    [
        ("import config\n", "core/leaf.py:1 -> config"),
        ("def f():\n    from services import alpha\n    return alpha\n", "services"),
        ("import sys\nif sys.version_info > (3,):\n    import config\n", "config"),
        ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from models import base\n", "models"),
        ("from . import other\n", ".other" if False else "core/leaf.py:1 -> ."),
        ("import numpy\n", "numpy"),
        ("import importlib\nm = importlib.import_module('config')\n", "<dynamisch: import_module>"),
        ("m = __import__('config')\n", "<dynamisch: __import__>"),
    ],
    ids=["eager", "lazy", "conditional", "type_checking", "relative", "third_party",
         "import_module", "dunder_import"],
)
def test_listed_leaf_with_non_stdlib_import_is_red(gate, mini, monkeypatch, body, needle):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/other.py", "")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core.leaf:")]
    assert hits and needle in hits[0], result.regressions


def test_shadowed_stdlib_name_is_not_stdlib(gate, mini, monkeypatch):
    """Ein Projektmodul mit Stdlib-Namen (hier ``json.py``) zaehlt als Projektimport."""
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "json.py", "")
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert any(r.startswith("[fan_out_exempt_leaves] core.leaf:") for r in result.regressions)


# --------------------------------------------------------------------------
# Regel 6, Blattvertrag: keine Modul-Seiteneffekte, keine dynamischen Importe
# (Dok. 83: "keine Modul-Seiteneffekte"; Vorpruefung B-13/B-14)
# --------------------------------------------------------------------------


def test_every_exempt_leaf_fulfils_the_leaf_contract(gate):
    scans = gate.scan_backend()
    for module in sorted(gate.FAN_OUT_EXEMPT_LEAVES):
        assert scans[module].leaf_violations == [], (module, scans[module].leaf_violations)


def test_rich_valid_leaf_passes_the_leaf_contract(gate, mini, monkeypatch):
    """Positivkontrolle: alles, was die Positivliste erlaubt, bleibt gruen."""
    _mini_with_leaf(
        gate, mini, monkeypatch,
        '''
        """Docstring."""
        from __future__ import annotations
        import hashlib
        from dataclasses import dataclass
        from enum import StrEnum, unique
        from types import MappingProxyType
        from typing import TYPE_CHECKING, Any
        if TYPE_CHECKING:
            from collections.abc import Mapping
        SCHEME = "v1"
        _PAIR: tuple[str, ...] = (",", ":")
        _TABLE = MappingProxyType({SCHEME: MappingProxyType({"sort_keys": True})})
        NAMES = tuple(_TABLE)
        KEYS = frozenset(k for k in NAMES if k)
        SIZE = len  # Referenz, kein Aufruf
        LIMIT = 2 ** 8 - 1
        CODE = lambda x=1: x
        @unique
        class Code(StrEnum):
            """Codes."""
            A = "a"
            B: str = "b"
        @dataclass(frozen=True)
        class Box:
            value: Any = None
            @property
            def double(self):
                return getattr(self, "value") * 2
        def digest(text: str, *, scheme: str = SCHEME) -> str:
            import decimal
            return hashlib.sha256(text.encode()).hexdigest() + str(decimal)
        __all__ = ["Box", "Code", "digest"]
        ''',
    )
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert result.regressions == []


@pytest.mark.parametrize(
    "body,needle",
    [
        # die vier Faelle aus B-13
        ('open("side_effect.txt", "w").write("x")\n', "<Seiteneffekt auf Modulebene: open("),
        ('exec("import services.alpha")\n', "<dynamisch: exec>"),
        ('import runpy\nrunpy.run_module("services.alpha")\n', "<dynamisch: import runpy>"),
        ('import importlib\ngetattr(importlib, "import_module")("services.alpha")\n',
         "<dynamisch: importlib>"),
        # B-14: dynamische Importe/Codeausfuehrung auch in Funktionen
        ('def f():\n    return eval("1")\n', "<dynamisch: eval>"),
        ('def f():\n    return compile("x", "f", "exec")\n', "<dynamisch: compile>"),
        ('def f():\n    import importlib.util\n'
         '    return importlib.util.spec_from_file_location("m", "m.py")\n',
         "<dynamisch: import importlib.util>"),
        ('from importlib import import_module\n', "<dynamisch: from importlib import ...>"),
        ('import sys\ndef f():\n    return sys.modules["services.alpha"]\n',
         "<dynamisch: sys.modules>"),
        ('def f(o, n):\n    return getattr(o, n)\n', "<dynamisch: getattr(...)>"),
        ('def f(o):\n    return getattr(o, "__import__")\n', "<dynamisch: getattr(...)>"),
        ('def f():\n    return globals()\n', "<dynamisch: globals>"),
        # weitere Modul-Seiteneffekte
        ('print("x")\n', "<Seiteneffekt auf Modulebene: print("),
        ('import os\nos.environ["X"] = "1"\n', "<Seiteneffekt auf Modulebene: os.environ"),
        ('import logging\nlogging.basicConfig()\n', "<Seiteneffekt auf Modulebene: logging"),
        ('import hashlib\nH = hashlib.sha256(b"x").hexdigest()\n', "<Seiteneffekt auf Modulebene: H ="),
        ('for i in range(2):\n    pass\n', "<Seiteneffekt auf Modulebene: for "),
        ('try:\n    import json\nexcept ImportError:\n    json = None\n',
         "<Seiteneffekt auf Modulebene: try:"),
        ('import sys\nif sys.platform:\n    X = 1\n', "<Seiteneffekt auf Modulebene: if "),
        ('def deco(f):\n    return f\n@deco\ndef g():\n    pass\n', "<Seiteneffekt auf Modulebene: @deco"),
        ('def g(x=print("x")):\n    return x\n', "<Seiteneffekt auf Modulebene: def g("),
        ('class C:\n    print("x")\n', "<Seiteneffekt in Klasse C: print("),
        ('X = [print(i) for i in (1, 2)]\n', "<Seiteneffekt auf Modulebene: X ="),
        ('import json\njson.x = 1\n', "<Seiteneffekt auf Modulebene: json.x = 1"),
        ('X: int\nX += 1\n', "<Seiteneffekt auf Modulebene: X += 1"),
    ],
    ids=[
        "b13_open_write", "b13_exec", "b13_runpy", "b13_getattr_importlib",
        "eval_in_function", "compile_in_function", "importlib_util_in_function",
        "from_importlib_import_module", "sys_modules", "getattr_dynamic_name",
        "getattr_dunder_import", "globals",
        "module_level_print", "environ_assignment", "logging_config", "non_constructor_call",
        "for_loop", "try_block", "non_type_checking_if", "impure_decorator",
        "impure_default", "class_body_call", "impure_comprehension", "attribute_assignment",
        "augmented_assignment",
    ],
)
def test_listed_leaf_with_side_effect_or_dynamic_import_is_red(
    gate, mini, monkeypatch, body, needle
):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core.leaf:")]
    assert hits and needle in hits[0], result.regressions


def test_side_effect_outside_the_allowlist_is_not_rule_6(gate, mini, monkeypatch):
    """Der Blattvertrag gilt nur fuer gelistete Module (exakte Pfade)."""
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/other.py", 'open("x", "w")\n')
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert not any(r.startswith("[fan_out_exempt_leaves]") for r in result.regressions)


def test_listed_module_that_does_not_exist_is_red(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    monkeypatch.setattr(gate, "FAN_OUT_EXEMPT_LEAVES", frozenset({"core.leaf", "core.missing"}))
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert any(
        r.startswith("[fan_out_exempt_leaves] core.missing: gelistet, aber kein Modul")
        for r in result.regressions
    ), result.regressions


# Die 11 Faelle aus dem zweiten Review des K-1-Stapels, die das Gate vor dem
# Blattvertrag nicht erkannte -- jeder einzeln rot, mit konkretem Grund.
@pytest.mark.parametrize(
    "body,needle",
    [
        ("from importlib import import_module as load\nload('config')\n",
         "<dynamisch: from importlib import ...>"),
        ("import importlib\ngetattr(importlib, 'imp' + 'ort_module')('config')\n",
         "<dynamisch: getattr(...)>"),
        ("exec('import config')\n", "<dynamisch: exec>"),
        ("import runpy\nrunpy.run_module('config')\n", "<dynamisch: .run_module>"),
        ("import sys\ndef f():\n    return sys.modules.get('config')\n", "<dynamisch: sys.modules>"),
        ("import pkgutil\ndef f():\n    return pkgutil.resolve_name('config')\n",
         "<dynamisch: pkgutil>"),
        ("import importlib.util\ndef f():\n"
         "    return importlib.util.spec_from_file_location('c', 'config.py')\n",
         "<dynamisch: .spec_from_file_location>"),
        ("open('side_effect.txt', 'w').write('x')\n", "<Seiteneffekt auf Modulebene: open("),
        ("import json\njson.dumps = lambda *a, **k: ''\n",
         "<Modul-Attribut veraendert: json.dumps>"),
        ("import sys\ndef f():\n    sys.path.insert(0, '/tmp')\n", "<dynamisch: sys.path>"),
        ("import builtins\ndef f():\n    builtins.open = None\n", "<dynamisch: builtins>"),
    ],
    ids=[f"review_{i:02d}" for i in range(1, 12)],
)
def test_review_cases_are_red(gate, mini, monkeypatch, body, needle):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core.leaf:")]
    assert hits and needle in hits[0], result.regressions


@pytest.mark.parametrize(
    "body,needle",
    [
        ("from importlib import import_module as load\ndef f():\n    return load('config')\n",
         "core/leaf.py:3 -> <dynamisch: load>"),
        ("import sys as s\ndef f():\n    return s.path\n", "<dynamisch: sys.path>"),
        ("from sys import modules as m\ndef f():\n    return m\n", "<dynamisch: m>"),
        ("import json as j\ndef f():\n    j.dumps = None\n", "<Modul-Attribut veraendert: j.dumps>"),
        ("import os\ndef f():\n    del os.sep\n", "<Modul-Attribut veraendert: os.sep>"),
    ],
    ids=["alias_call_site", "sys_alias_path", "from_sys_import_modules",
         "aliased_module_attribute_assignment_in_function", "module_attribute_delete"],
)
def test_aliases_of_forbidden_imports_are_followed(gate, mini, monkeypatch, body, needle):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core.leaf:")]
    assert hits and needle in hits[0], result.regressions


def test_local_object_attribute_assignment_is_allowed(gate, mini, monkeypatch):
    """Nur Attribute importierter Module sind tabu, nicht eigene Objekte."""
    _mini_with_leaf(
        gate, mini, monkeypatch,
        "import json\nclass E(Exception):\n    def __init__(self, c):\n"
        "        self.code = c\n        self.text = json.dumps(c)\n",
    )
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert result.regressions == []


# Elternpakete: import core.leaf fuehrt core/__init__.py aus.
def test_parent_package_importing_project_modules_is_red(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/__init__.py", "import config\nfrom services import alpha\n")
    _, result = _check(gate, mini, _baseline(gate, mini))
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core (Elternpaket")]
    assert hits and "core/__init__.py:1 -> config" in hits[0] and "services.alpha" in hits[0], (
        result.regressions
    )


def test_parent_package_with_side_effect_is_red(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/__init__.py", "print('boot')\n")
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert any(
        r.startswith("[fan_out_exempt_leaves] core (Elternpaket") and "print(" in r
        for r in result.regressions
    ), result.regressions


@pytest.mark.parametrize(
    "init_body", ["", '"""Paket."""\nfrom __future__ import annotations\n__all__ = []\n'],
    ids=["empty", "pure"],
)
def test_empty_or_pure_parent_package_passes(gate, mini, monkeypatch, init_body):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/__init__.py", init_body)
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert result.regressions == []


def test_real_parent_packages_of_listed_leaves_are_clean(gate):
    scans = gate.scan_backend()
    for pkg in sorted(gate._leaf_parent_packages()):
        if pkg in scans:
            s = scans[pkg]
            assert s.non_stdlib_imports == [] and s.leaf_violations == [], (pkg, s)
            assert s.runtime_targets() == {} and s.typeonly == {}, pkg


# K-2-Review N2 (= B-13 fuer core.reason_codes): Seiteneffekte im Blatt.
@pytest.mark.parametrize(
    "body,needle",
    [
        ("import pathlib\npathlib.Path('x.txt').write_text('x')\n",
         "<Seiteneffekt auf Modulebene: pathlib.Path("),
        ("from pathlib import Path\nMARKER = Path('x.txt').write_text('x')\n",
         "<Seiteneffekt auf Modulebene: MARKER ="),
        ("exec('import config')\n", "<dynamisch: exec>"),
        ("import sqlite3\nCONN = sqlite3.connect('x.db')\n",
         "<Seiteneffekt auf Modulebene: CONN = sqlite3.connect("),
        ("import sqlite3\nsqlite3.connect('x.db').close()\n",
         "<Seiteneffekt auf Modulebene: sqlite3.connect("),
    ],
    ids=["pathlib_write_text", "pathlib_write_text_assigned", "exec", "sqlite3_connect_assigned",
         "sqlite3_connect_call"],
)
def test_k2_review_n2_side_effects_are_red(gate, mini, monkeypatch, body, needle):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core.leaf:")]
    assert hits and needle in hits[0], result.regressions
