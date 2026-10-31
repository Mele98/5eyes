"""X4 (OPTIMIZATION): RetentionPolicy im Laenderpaket.

Belegt:
- Vorher == nachher: ``RETENTION_YEARS`` (bisher Literal 10 in
  services/advisory_log_integrity.py) kommt aus ``ch/retention/policy.yaml``
  und ist byte-/wertgleich; ``compute_retain_until`` liefert fuer eine feste
  Randfall-Tabelle (inkl. 29. Februar) exakt die bisherigen Daten.
- ``years(category)`` ist fail-closed (unbekannte Kategorie = Fehler).
- DSG-Regime-Kennung ``ch_dsg`` gesetzt; ``notes`` und ``erasure_rules``
  sind begruendet ``PendingExtraction`` (bleiben im Kern, siehe PR).
- ``RETENTION_NOTES`` und der Export bleiben unveraendert (Digest der Werte
  auf X3-Stand gepinnt; G5 deckt das Export-JSON ab).
- Loader weist ungueltige Regeln ab; Policy-Hash gepinnt; Desktop-Bundle
  enthaelt policy.yaml; ``jurisdictions.retention`` importiert nur das Paket.

Keine Datenbank, kein App-Start.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from jurisdictions.api import PendingExtraction
from jurisdictions.registry import PACKS_ROOT, PackRegistryError, default_registry
from jurisdictions.retention import (
    PackRetentionPolicy,
    RetentionCategoryError,
    default_retention,
    load_retention_policy,
    retention_for,
    retention_policy_paths,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Vorher-Werte (X3-Stand, vor der Umstellung erzeugt).
BEFORE_RETENTION_YEARS = 10
# sha256 ueber json.dumps(RETENTION_NOTES, ensure_ascii=False, separators=(",", ":"))
BEFORE_RETENTION_NOTES_DIGEST = "sha256:4b966aa7fb116adcfe0c59373f3651f0d16116b88f85312d4e48b56758b8b1b3"
# compute_retain_until vor der Umstellung (Eingabe -> Ergebnis).
BEFORE_RETAIN_UNTIL = {
    "2024-02-29": "2034-02-28",
    "2024-02-29T10:15:00Z": "2034-02-28",
    "2026-01-15T08:00:00+01:00": "2036-01-15",
    "2020-12-31": "2030-12-31",
    "2023-06-30T23:59:59": "2033-06-30",
}

CH_POLICY_HASH = "sha256:c98f2279a28508e5dbbb181a2e7a89abcfb3524e7a55c739d50ea77f53d0c673"


def test_retention_years_come_from_the_pack_and_equal_the_previous_literal():
    integrity = importlib.import_module("services.advisory_log_integrity")
    assert default_retention().years("advisory_log") == BEFORE_RETENTION_YEARS
    assert integrity.RETENTION_YEARS == BEFORE_RETENTION_YEARS
    assert type(integrity.RETENTION_YEARS) is int


def test_retain_until_is_unchanged_for_edge_dates():
    from services.advisory_log_integrity import compute_retain_until

    for raw, expected in BEFORE_RETAIN_UNTIL.items():
        assert compute_retain_until(raw) == expected, raw


def test_retention_notes_and_export_constant_are_unchanged():
    from services.data_export import RETENTION_NOTES

    raw = json.dumps(RETENTION_NOTES, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == BEFORE_RETENTION_NOTES_DIGEST


def test_ch_policy_shape_and_hash():
    policy = default_retention()
    assert isinstance(policy, PackRetentionPolicy)
    assert (policy.code, policy.privacy_regime) == ("CH", "ch_dsg")
    assert dict(policy.retention_years) == {"advisory_log": 10}
    assert isinstance(policy.notes, PendingExtraction) and "RETENTION_NOTES" in policy.notes.reason
    assert isinstance(policy.erasure_rules, PendingExtraction)
    assert policy.policy_hash == CH_POLICY_HASH
    assert policy.source == "ch/retention/policy.yaml"


@pytest.mark.parametrize("pack", default_registry().all(), ids=lambda p: f"{p.code}@{p.version}")
def test_every_registered_pack_has_a_valid_retention_policy(pack):
    policy = retention_for(pack.code, pack.version)
    assert policy.retention_years and all(type(v) is int and v > 0 for v in policy.retention_years.values())
    assert policy.privacy_regime


def test_unknown_category_and_pack_fail_closed():
    with pytest.raises(RetentionCategoryError):
        default_retention().years("does_not_exist")
    with pytest.raises(RetentionCategoryError):
        retention_for("XX")


def _copy(tmp_path):
    root = tmp_path / "packs"
    shutil.copytree(PACKS_ROOT / "ch" / "retention", root / "ch" / "retention")
    return default_registry().latest("CH"), root, root / "ch" / "retention" / "policy.yaml"


def _raw():
    return yaml.safe_load((PACKS_ROOT / "ch" / "retention" / "policy.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda r: r.pop("privacy_regime"), "Pflicht"),
        (lambda r: r.update(privacy_regime="CH DSG"), "privacy_regime"),
        (lambda r: r.update(retention_years={}), "nicht-leeres Mapping"),
        (lambda r: r["retention_years"].update(advisory_log=0), "positive ganze Zahl"),
        (lambda r: r["retention_years"].update(advisory_log=True), "positive ganze Zahl"),
        (lambda r: r["retention_years"].update(advisory_log="10"), "positive ganze Zahl"),
        (lambda r: r["pending_extraction"].pop("notes"), "notes und erasure_rules"),
        (lambda r: r["pending_extraction"].update(notes=" "), "Begruendung"),
        (lambda r: r.update(extra=1), "Teilmenge"),
    ],
)
def test_loader_rejects_invalid_policies(tmp_path, mutate, message):
    pack, root, path = _copy(tmp_path)
    raw = _raw()
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(PackRegistryError, match=message):
        load_retention_policy(pack, root)


def test_missing_policy_is_rejected(tmp_path):
    pack, root, path = _copy(tmp_path)
    path.unlink()
    with pytest.raises(PackRegistryError, match="fehlen"):
        load_retention_policy(pack, root)


def test_policy_hash_ignores_yaml_formatting(tmp_path):
    pack, root, path = _copy(tmp_path)
    path.write_text("# anders\n" + yaml.safe_dump(_raw(), allow_unicode=True, default_flow_style=True), encoding="utf-8")
    assert load_retention_policy(pack, root).policy_hash == CH_POLICY_HASH


@pytest.fixture(scope="module")
def ratchet_gate():
    name = "check_architecture_ratchets_for_retention"
    spec = importlib.util.spec_from_file_location(name, BACKEND_ROOT / "scripts" / "check_architecture_ratchets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(name, None)


def test_retention_module_imports_nothing_outside_the_package(ratchet_gate):
    fan_out = ratchet_gate.measure(ratchet_gate.scan_backend())["fan_out"]
    targets = fan_out.get("jurisdictions.retention", [])
    assert targets and all(t.startswith("jurisdictions") for t in targets), targets
    assert fan_out.get("services.advisory_log_integrity") == ["jurisdictions.retention"]


def test_policy_file_is_listed_for_the_desktop_bundle():
    script = (BACKEND_ROOT.parent / "ares-desktop" / "scripts" / "build-backend.js").read_text(encoding="utf-8")
    paths = retention_policy_paths()
    assert paths
    for path in paths:
        assert f"'{path.relative_to(BACKEND_ROOT).as_posix()}'" in script
