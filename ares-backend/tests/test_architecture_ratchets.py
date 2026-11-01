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
        "leaf_content_sha256",
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
            import json
            return json.dumps
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
            import json
            return hashlib.sha256(text.encode()).hexdigest() + json.dumps(scheme)
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


# --------------------------------------------------------------------------
# N-K1 (Dok. 86, Pruefrunde K-1/K-2): Code aus dem eigenen Modul beim Import
# und Stdlib-Negativliste. Jeder Fall war vor dem Fix rc=0; fail-closed.
# --------------------------------------------------------------------------

_N_K1_CASES = [
    # 1. Metaklasse bzw. __init_subclass__ aus dem eigenen Modul
    ("class _M(type):\n    def __new__(mcs, name, bases, ns):\n"
     "        open('side_effect.txt', 'w').write('x')\n"
     "        return super().__new__(mcs, name, bases, ns)\n"
     "class _A(metaclass=_M):\n    pass\n",
     "<Klasse _A: Klassen-Keyword nicht erlaubt: metaclass>"),
    ("class _M(type):\n    pass\n", "<Klasse _M: Basis nicht erlaubt: type>"),
    ("class _B:\n    def __init_subclass__(cls, **kw):\n"
     "        open('side_effect.txt', 'w').write('x')\n"
     "class _C(_B):\n    pass\n",
     "<Hook-Methode in Klasse _B nicht erlaubt: __init_subclass__>"),
    ("def _hook(cls):\n    open('side_effect.txt', 'w').write('x')\n"
     "class _B:\n    __init_subclass__ = _hook\nclass _C(_B):\n    pass\n",
     "<Hook-Name in Klasse _B zugewiesen: __init_subclass__>"),
    ("import json\nclass _C(json.JSONEncoder):\n    pass\n",
     "<Klasse _C: Basis nicht erlaubt: json.JSONEncoder>"),
    # 2. __class_getitem__ ueber Subscript (Subscript auf eigene Namen ist unrein)
    ("class _G:\n    def __class_getitem__(cls, item):\n"
     "        open('side_effect.txt', 'w').write('x')\n"
     "        return cls\n_X = _G[int]\n",
     "<Hook-Methode in Klasse _G nicht erlaubt: __class_getitem__>"),
    ("class _G:\n    pass\n_X = _G[int]\n", "<Seiteneffekt auf Modulebene: _X = _G[int]>"),
    ("class _G:\n    pass\n_X: _G[int] = 1\n", "<Seiteneffekt auf Modulebene: _X: _G[int] = 1>"),
    ("class _G:\n    pass\ndef f(x: _G[int]):\n    return x\n",
     "<Seiteneffekt auf Modulebene: def f(x: _G[int]):>"),
    ("_T = {1: 2}\n_X = _T[1]\n", "<Seiteneffekt auf Modulebene: _X = _T[1]>"),
    # 3. Stdlib-Positivliste statt Negativliste (auch funktionslokal)
    ("import pydoc\ndef f():\n    return pydoc.locate('services.alpha')\n",
     "<Stdlib-Modul nicht auf Blatt-Positivliste: import pydoc>"),
    ("def f(b):\n    import pickle\n    return pickle.loads(b)\n",
     "<Stdlib-Modul nicht auf Blatt-Positivliste: import pickle>"),
    ("from logging import config\n",
     "<Stdlib-Modul nicht auf Blatt-Positivliste: from logging import ...>"),
    ("def f():\n    import decimal\n    return decimal\n",
     "<Stdlib-Modul nicht auf Blatt-Positivliste: import decimal>"),
    ("import typing\ndef f(o):\n    return typing.get_type_hints(o)\n",
     "<dynamisch: .get_type_hints>"),
    # 4. setattr/delattr auf importierte Module (auch mit Literal-Namen)
    ("import json\ndef f():\n    setattr(json, 'dumps', repr)\n",
     "<Modul-Attribut veraendert: setattr(json, ...)>"),
    ("import json as j\ndef f():\n    delattr(j, 'dumps')\n",
     "<Modul-Attribut veraendert: delattr(j, ...)>"),
    ("from json import dumps\ndef f():\n    setattr(dumps, 'x', 1)\n",
     "<Modul-Attribut veraendert: setattr(dumps, ...)>"),
    # Flankierend: Dunder-Zugriffe und Modul-/Enum-Hooks
    ("def f():\n    return ().__class__.__base__\n", "<dynamisch: .__class__>"),
    ("def f(o):\n    return getattr(o, '__globals__')\n", "<dynamisch: getattr(...)>"),
    ("def f(d):\n    return d['__builtins__']\n", "<dynamisch: ['__builtins__']>"),
    ("def __getattr__(name):\n    return name\n",
     "<Hook-Methode auf Modulebene nicht erlaubt: __getattr__>"),
    ("from enum import Enum\nclass E(Enum):\n    A = 1\n    def __init__(self, v):\n"
     "        open('side_effect.txt', 'w').write('x')\n",
     "<Hook-Methode in Klasse E nicht erlaubt: __init__>"),
]


@pytest.mark.parametrize(
    "body,needle",
    _N_K1_CASES,
    ids=[
        "metaclass_keyword", "metaclass_base_type", "init_subclass_method",
        "init_subclass_assigned", "base_outside_allowlist",
        "class_getitem_method", "subscript_on_own_class", "subscript_in_annotation",
        "subscript_in_def_annotation", "subscript_on_own_dict",
        "pydoc_locate", "pickle_in_function", "logging_config", "decimal_in_function",
        "typing_get_type_hints",
        "setattr_module_literal_name", "delattr_module_alias", "setattr_imported_name",
        "dunder_attribute", "getattr_dunder_literal", "dunder_subscript_key",
        "module_getattr_hook", "enum_init_runs_at_class_creation",
    ],
)
def test_n_k1_import_time_code_and_stdlib_allowlist_are_red(
    gate, mini, monkeypatch, body, needle
):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core.leaf:")]
    assert hits and needle in hits[0], result.regressions


def test_n_k1_leaf_stdlib_allowlist_is_explicit(gate):
    """Positivliste, so eng wie moeglich; jede Erweiterung ist ein Review-Entscheid."""
    assert gate.LEAF_ALLOWED_STDLIB == frozenset(
        {
            "__future__", "abc", "collections.abc", "dataclasses", "enum", "functools",
            "hashlib", "json", "types", "typing",
        }
    )


def test_n_k1_real_leaves_only_use_allowlisted_stdlib(gate):
    """Positivkontrolle: die echten Blaetter importieren nur Positivlisten-Module
    und erfuellen den verschaerften Vertrag (Klassenkoepfe, Subscripts, Hooks)."""
    import ast

    scans = gate.scan_backend()
    for module in sorted(gate.FAN_OUT_EXEMPT_LEAVES):
        tree = ast.parse((BACKEND_ROOT / scans[module].path).read_text(encoding="utf-8"))
        imported = {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        } | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert imported and imported <= gate.LEAF_ALLOWED_STDLIB, (module, imported)
        assert gate.leaf_contract_violations(tree) == [], module


def test_n_k1_allowed_class_shapes_stay_green(gate, mini, monkeypatch):
    """Positivkontrolle: erlaubte Klassenformen (Enum, Exception-Hierarchie mit
    eigener Unterklasse, TypedDict(total=False), NamedTuple, Protocol, dataclass)."""
    _mini_with_leaf(
        gate, mini, monkeypatch,
        '''
        from __future__ import annotations
        import enum
        from dataclasses import dataclass
        from enum import StrEnum
        from typing import Any, Mapping, NamedTuple, Protocol, TypedDict
        class Code(StrEnum):
            A = "a"
        class Level(enum.IntEnum):
            LOW = 1
        class Base(Exception):
            channel: str | None = None
            _RESERVED = frozenset({"a"})
            def __init__(self, code: Code | str, extra: Mapping[str, Any] | None = None) -> None:
                super().__init__(code)
                self.extra = dict(extra or {})
            @property
            def status(self) -> int:
                return 409
        class Onsite(Base):
            channel = "onsite"
        class Row(TypedDict, total=False):
            a: int
        class Pair(NamedTuple):
            a: int
            b: dict[str, Any]
        class Port(Protocol):
            def run(self) -> None: ...
        @dataclass(frozen=True)
        class Box:
            value: tuple[int, ...] = ()
            def __post_init__(self) -> None:
                pass
        ''',
    )
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert result.regressions == []


# --------------------------------------------------------------------------
# Pruefrunde #842 (Dok. 86): N-842-1 (Properties auf Enum-Mitgliedern bzw.
# classmethod+property), N-842-2 (Attributketten ueber importierte Module,
# Stern-Importe) und Inhalts-Pin je Blatt. Jeder Fall war vor dem Fix rc=0.
# --------------------------------------------------------------------------

_N_842_CASES = [
    # N-842-1: Getter laeuft beim Attributzugriff auf Modulebene
    ("from enum import Enum\nclass E(Enum):\n    A = 1\n    @property\n    def boom(self):\n"
     "        open('side_effect.txt', 'w').write('x')\n        return 1\nX = E.A.boom\n",
     "<Property in Klasse E nicht erlaubt (N-842-1): boom>"),
    ("import functools\nfrom enum import Enum\nclass E(Enum):\n    A = 1\n"
     "    @functools.cached_property\n    def boom(self):\n        return 1\nX = E.A.boom\n",
     "<Property in Klasse E nicht erlaubt (N-842-1): boom>"),
    ("from functools import cached_property\nfrom enum import Enum\nclass E(Enum):\n    A = 1\n"
     "    @cached_property\n    def boom(self):\n        return 1\nX = E.A.boom\n",
     "<Property in Klasse E nicht erlaubt (N-842-1): boom>"),
    ("from dataclasses import dataclass\nfrom enum import Enum\nclass E(Enum):\n    A = 1\n"
     "    @property\n    def boom(self):\n        return 1\n"
     "@dataclass\nclass D:\n    x: int = E.A.boom\n",
     "<Property in Klasse E nicht erlaubt (N-842-1): boom>"),
    ("class C:\n    @classmethod\n    @property\n    def boom(cls):\n"
     "        open('side_effect.txt', 'w').write('x')\n        return 1\nX = C.boom\n",
     "<Property in Klasse C nicht erlaubt (N-842-1): boom>"),
    ("class C:\n    @property\n    @classmethod\n    def boom(cls):\n        return 1\n",
     "<Property in Klasse C nicht erlaubt (N-842-1): boom>"),
    ("from functools import cached_property\nclass C:\n    @cached_property\n"
     "    def boom(self):\n        return 1\n",
     "<Property in Klasse C nicht erlaubt (N-842-1): boom>"),
    # N-842-2: Attributketten ueber erlaubte Module
    ("import enum\ndef run():\n    return enum.bltns.eval(\"__import__('os').getpid()\")\n",
     "<Attributkette ueber importierten Namen: enum.bltns.eval>"),
    ("import enum\nfrom enum import Enum\n"
     "def run():\n    return enum.bltns.eval(\"__import__('os').name\")\n"
     "class E(Enum):\n    A = 1\n    @property\n    def boom(self):\n        return run()\n"
     "X = E.A.boom\n",
     "<Attributkette ueber importierten Namen: enum.bltns.eval>"),
    ("import typing\ndef f():\n    return typing.sys._getframe(0).f_builtins['exec']('1')\n",
     "<Attributkette ueber importierten Namen: typing.sys._getframe>"),
    ("import typing\ndef f():\n    typing.sys.path.insert(0, '/tmp')\n",
     "<Attributkette ueber importierten Namen: typing.sys.path>"),
    ("import dataclasses\ndef f():\n"
     "    return dataclasses.inspect.importlib.machinery.SourceFileLoader('c', 'config.py')\n",
     "<Attributkette ueber importierten Namen: dataclasses.inspect.importlib>"),
    ("from typing import *\ndef g(x: \"__import__('os').getcwd()\"):\n    return x\n"
     "def f():\n    return get_type_hints(g)\n",
     "<Stern-Import: from typing import *>"),
    ("from json import *\n", "<Stern-Import: from json import *>"),
    ("import collections.abc\ndef f():\n    return collections.Counter\n",
     "<import ohne as bindet Elternpaket: import collections.abc>"),
    ("import typing\ndef f(o):\n    return typing._eval_type(o, {}, {})\n",
     "<Unterstrich-Attribut auf importiertem Namen: typing._eval_type>"),
    ("import typing\nX = typing.sys\n", "<Modulobjekt ueber Attribut: typing.sys>"),
    ("from typing import sys as s\ndef f():\n    return s.argv\n",
     "<Modulobjekt importiert: from typing import sys>"),
    ("import enum\nB = enum\ndef f():\n    return B.bltns.eval('1')\n",
     "<Modulobjekt als Wert: enum>"),
]


@pytest.mark.parametrize(
    "body,needle",
    _N_842_CASES,
    ids=[
        "enum_property_at_import", "enum_functools_cached_property", "enum_cached_property",
        "enum_property_as_dataclass_default", "classmethod_property", "property_classmethod",
        "cached_property_any_class",
        "enum_bltns_eval", "enum_bltns_eval_at_import", "typing_sys_getframe",
        "typing_sys_path", "dataclasses_inspect_importlib", "star_import_get_type_hints",
        "star_import_json", "import_dotted_binds_parent", "underscore_attribute",
        "module_object_via_attribute", "module_object_via_from_import", "module_alias_as_value",
    ],
)
def test_n_842_import_time_code_and_attribute_chains_are_red(
    gate, mini, monkeypatch, body, needle
):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[fan_out_exempt_leaves] core.leaf:")]
    assert hits and needle in hits[0], result.regressions


def test_n_842_allowed_attribute_use_stays_green(gate, mini, monkeypatch):
    """Positivkontrolle: einstufige Attribute, Methoden auf Aufrufergebnissen,
    Enum-Mitglied ``.value``/``.name`` und ``property`` in Nicht-Enum-Klassen."""
    _mini_with_leaf(
        gate, mini, monkeypatch,
        '''
        from __future__ import annotations
        import hashlib
        import json
        import typing
        from enum import StrEnum
        from types import MappingProxyType
        class Code(StrEnum):
            A = "a"
        DEFAULT = Code.A.value
        NAME = Code.A.name
        TABLE = MappingProxyType({"a": 1})
        class Err(Exception):
            @property
            def status(self) -> int:
                return 409
        def digest(obj: typing.Any) -> str:
            return hashlib.sha256(json.dumps(obj).encode("utf-8")).hexdigest()
        ''',
    )
    _, result = _check(gate, mini, _baseline(gate, mini))
    assert result.regressions == []


def _pin_regressions(result) -> list[str]:
    return [r for r in result.regressions if r.startswith("[leaf_content_sha256]")]


def test_real_leaves_are_pinned_and_match(gate):
    scans = gate.scan_backend()
    pins = gate.load_baseline()["leaf_content_sha256"]
    for module in sorted(gate.FAN_OUT_EXEMPT_LEAVES):
        assert pins.get(module), f"{module}: kein Inhalts-Pin in der Basis"
        assert scans[module].content_sha256 == pins[module], module
    assert set(pins) == {m for m in gate._pinned_modules() if m in scans}


def test_leaf_hash_is_identical_for_lf_and_crlf(gate, tmp_path):
    """Windows-Checkout mit CRLF und Linux-CI mit LF liefern denselben Pin, und
    der Pin entspricht dem Git-Blob-Inhalt (LF, ``.gitattributes`` eol=lf)."""
    import hashlib

    pins = gate.load_baseline()["leaf_content_sha256"]
    for module in sorted(gate.FAN_OUT_EXEMPT_LEAVES):
        src = (BACKEND_ROOT / module.replace(".", "/")).with_suffix(".py").read_bytes()
        lf = src.replace(b"\r\n", b"\n")
        (tmp_path / "lf.py").write_bytes(lf)
        (tmp_path / "crlf.py").write_bytes(lf.replace(b"\n", b"\r\n"))
        h_lf = gate.leaf_content_sha256(tmp_path / "lf.py")
        assert h_lf == gate.leaf_content_sha256(tmp_path / "crlf.py")
        assert h_lf == hashlib.sha256(lf).hexdigest() == pins[module], module


def test_changed_leaf_content_is_red_even_if_ast_rules_pass(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    assert set(base["leaf_content_sha256"]) == {"core", "core.leaf"}
    _write(mini, "core/leaf.py", "import json\nX = 1\n")  # AST-rein, aber geaendert
    _, result = _check(gate, mini, base)
    pins = _pin_regressions(result)
    assert pins == result.regressions, result.regressions
    assert len(pins) == 1 and "core.leaf (core/leaf.py): Inhalt weicht vom Pin ab" in pins[0]
    assert "--update-leaf-pins" in pins[0]


def test_changed_parent_package_content_is_red(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/__init__.py", '"""Paket."""\n')
    _, result = _check(gate, mini, base)
    pins = _pin_regressions(result)
    assert len(pins) == 1 and pins[0].startswith("[leaf_content_sha256] core (core/__init__.py)")


def test_new_leaf_without_pin_is_red(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/other.py", "import json\n")
    base = _baseline(gate, mini)
    monkeypatch.setattr(gate, "FAN_OUT_EXEMPT_LEAVES", frozenset({"core.leaf", "core.other"}))
    _, result = _check(gate, mini, base)
    pins = _pin_regressions(result)
    assert len(pins) == 1 and "core.other (core/other.py): kein Inhalts-Pin" in pins[0], pins


def test_baseline_without_pins_is_red(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    del base["leaf_content_sha256"]
    _, result = _check(gate, mini, base)
    assert {r.split(" (")[0] for r in _pin_regressions(result)} == {
        "[leaf_content_sha256] core", "[leaf_content_sha256] core.leaf"
    }


def test_update_leaf_pins_is_explicit_and_refuses_other_violations(
    gate, mini, monkeypatch, tmp_path
):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(
        gate.dump_baseline(gate.measure(gate.scan_backend(mini))), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "BACKEND_ROOT", mini)
    monkeypatch.setattr(gate, "BASELINE_FILE", baseline_file)
    before = baseline_file.read_text(encoding="utf-8")

    # Inhalt geaendert: Lauf und --update-baseline rot, Basis unveraendert
    _write(mini, "core/leaf.py", "import json\nX = 1\n")
    assert gate.main([]) == 1
    assert gate.main(["--update-baseline"]) == 1
    assert baseline_file.read_text(encoding="utf-8") == before

    # Blattvertrag verletzt: auch --update-leaf-pins verweigert
    _write(mini, "core/leaf.py", "from json import *\n")
    assert gate.main(["--update-leaf-pins"]) == 1
    assert baseline_file.read_text(encoding="utf-8") == before

    # bewusst nachgefuehrt: nur der Pin aendert sich, danach gruen
    _write(mini, "core/leaf.py", "import json\nX = 1\n")
    assert gate.main(["--update-leaf-pins"]) == 0
    after = json.loads(baseline_file.read_text(encoding="utf-8"))
    old = json.loads(before)
    assert after["leaf_content_sha256"]["core.leaf"] != old["leaf_content_sha256"]["core.leaf"]
    assert {k: v for k, v in after.items() if k != "leaf_content_sha256"} == {
        k: v for k, v in old.items() if k != "leaf_content_sha256"
    }
    assert gate.main([]) == 0


# --------------------------------------------------------------------------
# Pruefrunde #844 (Dok. 86): N-844-1 Schatten-Dateien/-Pakete neben einem
# Blatt, N-844-2 exakte Pins (geloeschtes Elternpaket), N-844-3 Dekorator-
# und Aufruf-Aliase. Jeder Negativfall war auf d78a1af4 rc=0.
# --------------------------------------------------------------------------


def _leaf_regressions(result, module: str = "core.leaf") -> str:
    return "\n".join(
        r for r in result.regressions if r.startswith(f"[fan_out_exempt_leaves] {module}:")
    )


def test_real_leaves_resolve_exactly_to_the_pinned_file(gate):
    scans = gate.scan_backend()
    for module in sorted(gate.FAN_OUT_EXEMPT_LEAVES):
        assert scans[module].resolution_problems == [], (module, scans[module].resolution_problems)
    assert all(not s.collisions for s in scans.values())


def test_shadow_package_next_to_leaf_is_red(gate, mini, monkeypatch):
    """N-844-1: ``core/leaf/__init__.py`` schlaegt ``core/leaf.py``; vorher
    wurde die alte Datei gehasht und geprueft, Python lud aber das Paket."""
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf/__init__.py", "open('PWNED.txt', 'w').write('x')\n")
    _, result = _check(gate, mini, base)
    assert any(
        r.startswith("[module_collisions] core.leaf:") and "core/leaf/__init__.py" in r
        for r in result.regressions
    ), result.regressions
    leaf = _leaf_regressions(result)
    assert "weiterer Eintrag mit gleichem Modulnamen: core/leaf" in leaf, leaf
    assert "Python wuerde core/leaf/__init__.py laden statt core/leaf.py" in leaf, leaf


@pytest.mark.parametrize(
    "rel",
    [
        "core/leaf.cp312-win_amd64.pyd",
        "core/leaf.pyd",
        "core/leaf.cpython-312-x86_64-linux-gnu.so",
        "core/leaf.so",
        "core/leaf.pyc",
        "core/LEAF.pyc",
    ],
    ids=["pyd_tagged", "pyd", "so_tagged", "so", "sourceless_pyc", "other_case_pyc"],
)
def test_shadow_file_next_to_leaf_is_red(gate, mini, monkeypatch, rel):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    (mini / rel).write_bytes(b"\x00not a real extension\x00")
    _, result = _check(gate, mini, base)
    leaf = _leaf_regressions(result)
    assert f"weiterer Eintrag mit gleichem Modulnamen: {rel}" in leaf, result.regressions


@pytest.mark.parametrize("with_module", [True, False], ids=["with_submodule", "empty"])
def test_namespace_directory_next_to_leaf_is_red(gate, mini, monkeypatch, with_module):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    (mini / "core" / "leaf").mkdir()
    if with_module:
        _write(mini, "core/leaf/x.py", "")
    _, result = _check(gate, mini, base)
    assert "weiterer Eintrag mit gleichem Modulnamen: core/leaf" in _leaf_regressions(result)


def test_shadow_next_to_parent_package_is_red(gate, mini, monkeypatch):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core.py", "")
    _, result = _check(gate, mini, base)
    leaf = _leaf_regressions(result)
    assert "core: weiterer Eintrag mit gleichem Modulnamen: core.py" in leaf, leaf
    assert any(r.startswith("[module_collisions] core:") for r in result.regressions)


@pytest.mark.parametrize(
    "rel",
    [
        "core/__init__.pyd",
        "core/__init__.cp312-win_amd64.pyd",
        "core/__init__.cpython-312-x86_64-linux-gnu.so",
        "core/__init__.pyc",
        "core/__INIT__.PYD",
    ],
    ids=["pyd", "pyd_tagged", "so_tagged", "pyc", "other_case_pyd"],
)
def test_extra_init_file_in_parent_package_is_red(gate, mini, monkeypatch, rel):
    """N-844-4: ``find_spec`` sieht nur die Endungen des laufenden Interpreters;
    die Pruefung muss auf jeder Plattform rot sein, nicht nur unter Windows."""
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    (mini / rel).write_bytes(b"\x00not a real extension\x00")
    _, result = _check(gate, mini, base)
    assert f"core: weitere Paket-Init-Datei: {rel}" in _leaf_regressions(result), result.regressions


def test_init_pyw_in_parent_package_is_red(gate, mini, monkeypatch):
    """``__init__.pyw`` wird heute nicht geladen, ist aber eine ladbare Endung
    und hat im Paket nichts zu suchen (fail-closed)."""
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/__init__.pyw", "")
    _, result = _check(gate, mini, base)
    assert "core: weitere Paket-Init-Datei: core/__init__.pyw" in _leaf_regressions(result)


def test_module_name_collision_outside_leaves_is_red(gate, mini):
    """N-844-1 generell: zwei Dateien fuer einen Modulnamen sind ueberall rot."""
    base = _baseline(gate, mini)
    _write(mini, "services/alpha/__init__.py", "")
    _, result = _check(gate, mini, base)
    hits = [r for r in result.regressions if r.startswith("[module_collisions] services.alpha:")]
    assert hits and "services/alpha.py" in hits[0] and "services/alpha/__init__.py" in hits[0]


def test_deleted_parent_package_init_is_red(gate, mini, monkeypatch):
    """N-844-2: ohne ``core/__init__.py`` waere ``core`` ein Namespace-Paket;
    der verwaiste Pin galt vorher als Verbesserung."""
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    (mini / "core" / "__init__.py").unlink()
    _, result = _check(gate, mini, base)
    assert any(
        r.startswith("[leaf_content_sha256] core: gepinnt, aber keine Datei mehr")
        for r in result.regressions
    ), result.regressions
    assert "core: erwartete Datei fehlt: core/__init__.py" in _leaf_regressions(result)
    assert not any("[leaf_content_sha256] core" in i for i in result.improvements)


def test_stale_pin_is_red_until_removed_explicitly(gate, mini, monkeypatch, tmp_path):
    """N-844-2: Pins sind exakt; ein nicht mehr gebrauchter Pin wird nur ueber
    ``--update-leaf-pins`` entfernt, nie still ueber ``--update-baseline``."""
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    _write(mini, "core/other.py", "import json\n")
    monkeypatch.setattr(gate, "FAN_OUT_EXEMPT_LEAVES", frozenset({"core.leaf", "core.other"}))
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(
        gate.dump_baseline(gate.measure(gate.scan_backend(mini))), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "BACKEND_ROOT", mini)
    monkeypatch.setattr(gate, "BASELINE_FILE", baseline_file)
    monkeypatch.setattr(gate, "FAN_OUT_EXEMPT_LEAVES", frozenset({"core.leaf"}))
    before = baseline_file.read_text(encoding="utf-8")

    _, result = _check(gate, mini, json.loads(before))
    assert any(
        r.startswith("[leaf_content_sha256] core.other: gepinnt, aber") for r in result.regressions
    ), result.regressions
    assert gate.main(["--update-baseline"]) == 1
    assert baseline_file.read_text(encoding="utf-8") == before
    assert gate.main(["--update-leaf-pins"]) == 0
    assert "core.other" not in json.loads(baseline_file.read_text(encoding="utf-8"))[
        "leaf_content_sha256"
    ]
    assert gate.main([]) == 0


_N_844_3_CASES = [
    ("from enum import Enum\nfrom enum import property as unique\nclass E(Enum):\n    A = 1\n"
     "    @unique\n    def p(self):\n        return 1\nX = E.A.p\n",
     "<Seiteneffekt in Klasse E: @unique>"),
    ("from enum import Enum\nfrom functools import cached_property as staticmethod\n"
     "class E(Enum):\n    A = 1\n    @staticmethod\n    def p(self):\n        return 1\nX = E.A.p\n",
     "<Property in Klasse E nicht erlaubt (N-842-1): p>"),
    ("import enum as abc\nfrom enum import Enum\nclass E(Enum):\n    A = 1\n"
     "    @abc.property\n    def p(self):\n        return 1\nX = E.A.p\n",
     "<Seiteneffekt in Klasse E: @abc.property>"),
    ("from enum import Enum\nfrom enum import property as classmethod\nclass E(Enum):\n    A = 1\n"
     "    @classmethod\n    def p(self):\n        return 1\nX = E.A.p\n",
     "<Seiteneffekt in Klasse E: @classmethod>"),
    ("from enum import Enum\nfrom types import DynamicClassAttribute as final\n"
     "class E(Enum):\n    A = 1\n    @final\n    def p(self):\n        return 1\nX = E.A.p\n",
     "<Seiteneffekt in Klasse E: @final>"),
    ("from enum import Enum\nclass E(Enum):\n    A = 1\n    @property\n    def p(self):\n"
     "        return 1\nproperty = 1\n", "<Seiteneffekt in Klasse E: @property>"),
    ("from functools import reduce as tuple\ndef f(a, b):\n    return a\nX = tuple(f, [1, 2])\n",
     "<Seiteneffekt auf Modulebene: X = tuple(f, [1, 2])>"),
    ("def f(x):\n    return x\nX = [tuple(1) for tuple in [f]]\n",
     "<Seiteneffekt auf Modulebene: X = [tuple(1) for tuple in [f]]>"),
]


@pytest.mark.parametrize(
    "body,needle",
    _N_844_3_CASES,
    ids=["enum_property_as_unique", "cached_property_as_staticmethod",
         "enum_module_as_abc", "enum_property_as_classmethod", "dynamic_class_attribute_as_final",
         "rebound_builtin_decorator", "call_alias_reduce_as_tuple",
         "comprehension_rebinds_constructor"],
)
def test_n_844_3_decorator_and_call_aliases_are_red(gate, mini, monkeypatch, body, needle):
    _mini_with_leaf(gate, mini, monkeypatch, "import json\n")
    base = _baseline(gate, mini)
    _write(mini, "core/leaf.py", body)
    _, result = _check(gate, mini, base)
    leaf = _leaf_regressions(result)
    assert leaf and needle in leaf, result.regressions
