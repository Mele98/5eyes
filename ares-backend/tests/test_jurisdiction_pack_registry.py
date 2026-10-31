"""X1 (OPTIMIZATION): Laenderpaket-Geruest, Registry und resolve_pack.

Belegt:
- CH-Pack laedt, Manifest-Hash ist gepinnt (append-only, Design 80 2.3).
- Die Pack-Referenzen zeigen auf exakt die bestehenden Kernkonstanten
  (nichts verschoben, nichts dupliziert); deren Inhalt ist per Fingerprint
  gepinnt.
- Registry-Conformance: Duplikate sind Fehler, ungueltige Manifeste werden
  abgewiesen, Versionen werden semantisch sortiert.
- resolve_pack(...).code == heutige Formel ``getattr(m, "jurisdiction", None)
  or "CH"`` fuer NULL, "", "CH", "ch" und unbekannte Codes.
- api/registry/resolve importieren kein Backend-Modul ausserhalb des Pakets.

Keine Datenbank, kein App-Start.
"""
from __future__ import annotations

import copy
import importlib
import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from jurisdictions.api import (
    PACK_AREAS,
    AreaSpec,
    JurisdictionPack,
    NotProvided,
    PendingExtraction,
    ResolvedPack,
)
from jurisdictions.registry import (
    PACKS_ROOT,
    PackRegistry,
    PackRegistryError,
    builtin_manifest_paths,
    canonical_json,
    content_hash,
    default_registry,
    load_builtin_packs,
    load_manifest,
    pack_from_manifest,
)
from jurisdictions.resolve import LEGACY_DEFAULT_CODE, resolve_pack

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CH_MANIFEST = PACKS_ROOT / "ch" / "pack.yaml"
BUILD_BACKEND_SCRIPT = BACKEND_ROOT.parent / "ares-desktop" / "scripts" / "build-backend.js"

# Gepinnt: jede inhaltliche Aenderung an ch/pack.yaml verlangt eine neue
# Pack-Version (und einen neuen Pin), nie ein stilles Umschreiben.
CH_PACK_VERSION = "1.0.0"
CH_PACK_HASH = "sha256:e0d83f27c5b0d943bfa671bcd168826ea9025a804b3219a54753776e15ca2c96"
# Fingerprint ueber die Werte der referenzierten Kernkonstanten. Aendert sich
# eine CH-Konstante, ist das eine Aenderung des Pack-Inhalts.
CH_REFERENCES_FINGERPRINT = "sha256:caf79a8f04c7a9fd964800a7944bc93869561a41f1ae0bd155b53acce3e06515"


def _legacy(mandate) -> object:
    """Die heutige Inline-Formel (services/jurisdiction/resolve.py)."""
    return getattr(mandate, "jurisdiction", None) or "CH"


def _ch_raw() -> dict:
    return yaml.safe_load(CH_MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# CH-Pack
# --------------------------------------------------------------------------


def test_ch_pack_hash_is_pinned():
    pack = default_registry().latest("CH")
    assert pack is not None
    assert (pack.code, pack.version, pack.status) == ("CH", CH_PACK_VERSION, "draft")
    assert pack.content_hash == CH_PACK_HASH
    assert pack.source == "ch/pack.yaml"


def test_ch_pack_hash_is_stable_across_loads_and_formatting(tmp_path):
    first = load_manifest(CH_MANIFEST).content_hash
    second = load_builtin_packs().latest("CH").content_hash
    assert first == second == CH_PACK_HASH
    # Kommentare/Formatierung/Schluesselreihenfolge aendern den Hash nicht.
    raw = _ch_raw()
    folder = tmp_path / "ch"
    folder.mkdir()
    reordered = dict(reversed(list(raw.items())))
    (folder / "pack.yaml").write_text(
        "# anderer Kommentar\n" + yaml.safe_dump(reordered, sort_keys=False, default_flow_style=True),
        encoding="utf-8",
    )
    assert load_manifest(folder / "pack.yaml", tmp_path).content_hash == CH_PACK_HASH


def test_ch_pack_hash_changes_with_content():
    raw = _ch_raw()
    changed = copy.deepcopy(raw)
    changed["areas"]["retention"]["references"].reverse()
    assert content_hash(changed) != content_hash(raw)
    changed = copy.deepcopy(raw)
    changed["version"] = "1.0.1"
    assert content_hash(changed) != content_hash(raw)


def test_ch_pack_declares_every_area():
    pack = default_registry().latest("CH")
    assert tuple(pack.areas) == PACK_AREAS
    assert isinstance(pack.areas["calendar"], NotProvided)
    assert isinstance(pack.areas["products"], PendingExtraction)
    assert isinstance(pack.areas["formatting"], PendingExtraction)
    assert pack.areas["tax"].parameters == {"tax_regime_patterns": ["CH", "CH-*"]}
    assert pack.home_currency == "CHF"
    assert pack.locales == ("de-CH",)
    assert pack.timezone == "Europe/Zurich"


def test_ch_pack_references_point_to_existing_core_constants():
    references = importlib.import_module("jurisdictions.ch.references").REFERENCES
    pack = default_registry().latest("CH")
    assert list(references) == list(pack.references)
    for ref, value in references.items():
        module_name, attr = ref.split(":")
        assert getattr(importlib.import_module(module_name), attr) is value, ref


def test_ch_pack_reference_values_are_pinned():
    references = importlib.import_module("jurisdictions.ch.references").REFERENCES
    assert content_hash(references) == CH_REFERENCES_FINGERPRINT


def test_ch_pack_moves_nothing():
    # Die Konstanten bleiben im Kern: references.py definiert keine eigenen Werte.
    import ast

    tree = ast.parse((PACKS_ROOT / "ch" / "references.py").read_text(encoding="utf-8"))
    assigned = [
        t.id
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(t, ast.Name)
    ]
    assert assigned == ["REFERENCES"]


# --------------------------------------------------------------------------
# Registry-Conformance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("pack", default_registry().all(), ids=lambda p: f"{p.code}@{p.version}")
def test_registered_pack_conformance(pack: JurisdictionPack):
    path = PACKS_ROOT / pack.source
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert pack.content_hash == content_hash(raw)
    assert path.parent.name == pack.code.lower()
    assert tuple(pack.areas) == PACK_AREAS
    for name, spec in pack.areas.items():
        assert isinstance(spec, (AreaSpec, NotProvided, PendingExtraction)), name
        if isinstance(spec, (NotProvided, PendingExtraction)):
            assert spec.reason.strip(), name
    with pytest.raises(Exception):
        pack.code = "XX"  # frozen


def test_builtin_manifests_exclude_template_folders(tmp_path):
    for name in ("ch", "_template", ".hidden"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "pack.yaml").write_text("x: 1\n", encoding="utf-8")
    assert [p.parent.name for p in builtin_manifest_paths(tmp_path)] == ["ch"]
    assert [p.parent.name for p in builtin_manifest_paths()] == ["ch"]


def _pack(version: str = "1.0.0", code: str = "CH") -> JurisdictionPack:
    raw = _ch_raw()
    raw["version"] = version
    raw["code"] = code
    return pack_from_manifest(raw, f"{code.lower()}/pack.yaml")


def test_registry_rejects_duplicates():
    reg = PackRegistry([_pack()])
    with pytest.raises(PackRegistryError, match="bereits registriert"):
        reg.register(_pack())
    assert reg.versions("CH") == ("1.0.0",)


def test_registry_orders_versions_semantically():
    reg = PackRegistry([_pack("1.9.0"), _pack("1.10.0"), _pack("1.2.3")])
    assert reg.versions("CH") == ("1.2.3", "1.9.0", "1.10.0")
    assert reg.latest("CH").version == "1.10.0"
    assert reg.get("CH", "1.9.0").version == "1.9.0"
    assert reg.get("CH", "2.0.0") is None
    assert reg.latest("DE") is None
    assert reg.latest("ch") is None  # exakter, unnormalisierter Vergleich


def _mutate(fn):
    raw = _ch_raw()
    fn(raw)
    return raw


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda r: r.update(code="che"), "ISO-3166"),
        (lambda r: r.update(code="ch"), "ISO-3166"),
        (lambda r: r.update(version="1.0"), "SemVer"),
        (lambda r: r.update(status="live"), "status"),
        (lambda r: r.update(home_currency="chf"), "ISO-4217"),
        (lambda r: r.update(locales=[]), "locales"),
        (lambda r: r.update(timezone="Mars/Olympus"), "IANA"),
        (lambda r: r.update(effective_from=None), "effective_from"),
        (lambda r: r.update(status="approved"), "Approval"),
        (lambda r: r.update(extra=1), "Schluessel"),
        (lambda r: r.pop("approvals"), "Schluessel"),
        (lambda r: r["areas"].pop("calendar"), "areas"),
        (lambda r: r["areas"].update(calendar={}), "leerer Bereich"),
        (lambda r: r["areas"].update(calendar={"not_provided": " "}), "Begruendung"),
        (lambda r: r["areas"].update(calendar={"not_provided": "x", "references": []}), "schliesst"),
        (lambda r: r["areas"].update(legal={"references": ["kein_doppelpunkt"]}), "modul:ATTRIBUT"),
        (lambda r: r["areas"].update(legal={"references": ["a:B", "a:B"]}), "doppelte"),
        (lambda r: r["areas"].update(legal={"unknown": 1}), "unbekannte"),
    ],
)
def test_invalid_manifest_is_rejected(mutation, message):
    with pytest.raises(PackRegistryError, match=message):
        pack_from_manifest(_mutate(mutation), "ch/pack.yaml")


def test_approved_pack_needs_all_three_approvals():
    def approve(raw):
        raw["status"] = "approved"
        raw["approvals"] = [
            {"kind": k, "reference": f"REF-{k}", "approved_on": "2026-10-31"}
            for k in ("legal", "compliance", "ic")
        ]

    pack = pack_from_manifest(_mutate(approve), "ch/pack.yaml")
    assert pack.status == "approved"
    assert {a.kind for a in pack.approvals} == {"legal", "compliance", "ic"}


def test_manifest_folder_must_match_code(tmp_path):
    folder = tmp_path / "de"
    folder.mkdir()
    (folder / "pack.yaml").write_text(CH_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(PackRegistryError, match="Ordner"):
        load_manifest(folder / "pack.yaml", tmp_path)


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": {2, 1}}) == canonical_json({"a": frozenset({1, 2}), "b": 1})
    assert canonical_json({(1, 2): "x", (0, 1): "y"}) == '[[[0,1],"y"],[[1,2],"x"]]'
    with pytest.raises(PackRegistryError):
        canonical_json(object())


# --------------------------------------------------------------------------
# resolve_pack: Code identisch zur heutigen Formel
# --------------------------------------------------------------------------

_MISSING = object()


@pytest.mark.parametrize(
    "raw, expected_code, expected_source, registered",
    [
        (None, "CH", "legacy_default", True),
        ("", "CH", "legacy_default", True),
        ("CH", "CH", "mandate", True),
        ("ch", "ch", "mandate", False),
        (" CH ", " CH ", "mandate", False),
        ("DE", "DE", "mandate", False),
        ("AT", "AT", "mandate", False),
        ("XX", "XX", "mandate", False),
        ("CH-ZH", "CH-ZH", "mandate", False),
        (_MISSING, "CH", "legacy_default", True),
    ],
)
def test_resolve_pack_code_equals_legacy_formula(raw, expected_code, expected_source, registered):
    mandate = SimpleNamespace() if raw is _MISSING else SimpleNamespace(jurisdiction=raw)
    resolved = resolve_pack(mandate)
    assert isinstance(resolved, ResolvedPack)
    assert resolved.code == _legacy(mandate) == expected_code
    assert resolved.source == expected_source
    assert resolved.is_registered is registered
    if registered:
        assert (resolved.version, resolved.content_hash) == (CH_PACK_VERSION, CH_PACK_HASH)
    else:
        assert resolved.pack is None and resolved.version is None and resolved.content_hash is None


def test_resolve_pack_without_mandate_is_legacy_default():
    assert resolve_pack(None).code == _legacy(None) == LEGACY_DEFAULT_CODE == "CH"
    assert resolve_pack().code == "CH"


@pytest.mark.parametrize("raw", [None, "", "CH", "ch", "DE", "XX", " CH "])
def test_resolve_pack_explicit_code_equals_inline_fallback(raw):
    # z.B. product.jurisdiction or "CH" / cma.jurisdiction or "CH"
    resolved = resolve_pack(code=raw)
    assert resolved.code == (raw or "CH")
    assert resolved.source == ("explicit" if raw else "legacy_default")


def test_resolve_pack_non_string_code_is_passed_through_unregistered():
    resolved = resolve_pack(SimpleNamespace(jurisdiction=7))
    assert resolved.code == 7 == _legacy(SimpleNamespace(jurisdiction=7))
    assert resolved.pack is None


def test_resolve_pack_tenant_fallback_only_when_tenant_given():
    tenant = SimpleNamespace(home_jurisdiction="DE")
    assert resolve_pack(SimpleNamespace(jurisdiction=None), tenant=tenant).code == "DE"
    assert resolve_pack(SimpleNamespace(jurisdiction=None), tenant=tenant).source == "tenant"
    assert resolve_pack(SimpleNamespace(jurisdiction="CH"), tenant=tenant).code == "CH"
    assert resolve_pack(SimpleNamespace(jurisdiction=None), tenant=SimpleNamespace(home_jurisdiction=None)).code == "CH"
    assert resolve_pack(SimpleNamespace(jurisdiction=None)).code == "CH"


def test_resolve_pack_uses_given_registry():
    reg = PackRegistry([_pack("2.0.0", code="DE")])
    assert resolve_pack(SimpleNamespace(jurisdiction="DE"), registry=reg).version == "2.0.0"
    assert resolve_pack(SimpleNamespace(jurisdiction=None), registry=reg).pack is None


# --------------------------------------------------------------------------
# Isolation und Auslieferung
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ratchet_gate():
    name = "check_architecture_ratchets_for_jurisdictions"
    spec = importlib.util.spec_from_file_location(name, BACKEND_ROOT / "scripts" / "check_architecture_ratchets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(name, None)


def test_core_modules_import_nothing_outside_the_package(ratchet_gate):
    fan_out = ratchet_gate.measure(ratchet_gate.scan_backend())["fan_out"]
    for module in ("jurisdictions", "jurisdictions.api", "jurisdictions.registry", "jurisdictions.resolve", "jurisdictions.ch"):
        targets = fan_out.get(module, [])
        assert all(t.startswith("jurisdictions") for t in targets), (module, targets)
    assert "jurisdictions.ch.references" not in fan_out.get("jurisdictions.registry", [])
    assert "jurisdictions.ch.references" not in fan_out.get("jurisdictions.resolve", [])


def test_desktop_bundle_ships_package_and_manifests():
    script = BUILD_BACKEND_SCRIPT.read_text(encoding="utf-8")
    collect = re.search(r"const collectSubmodules = \[(.*?)\];", script, re.DOTALL)
    assert collect and "'jurisdictions'" in collect.group(1)
    for path in builtin_manifest_paths():
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        assert rel in script, f"{rel} fehlt als --add-data in build-backend.js"
