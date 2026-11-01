"""X3 (OPTIMIZATION): DocumentSet fuer Rechts- und Pflichttexte.

Belegt:
- Vorher == nachher je Schluessel: ``BEFORE_DIGESTS`` wurde auf dem
  Ausgangs-SHA (X1, 2706c349) aus den damaligen Kernkonstanten bzw.
  -Literalen erzeugt (footer.FIDLEG_DISCLAIMER, Deckblatt-Literale von
  pdf/documents/cost_disclosure.py). Jeder Pack-Text muss
  diesen Digest byte-genau treffen, und es gibt keinen ungeprueften
  Schluessel.
- Footer und Kostenausweis-Deckblatt lesen zur Laufzeit ueber das
  DocumentSet; static_texts bleibt Kern-Konstante (kein Fan-out 0->1).
- DocumentSet-Conformance: jede Locale vollstaendig, keine leeren Texte,
  unbekannte Schluessel/Locales fail-closed, Loader weist ungueltige
  Dateien ab, Inhalts-Hash gepinnt.
- ``legal_basis`` ist ein reiner Lese-Alias; Antworten/OpenAPI unveraendert.
- Desktop-Bundle enthaelt jede YAML-Datei des Pakets.

Keine Datenbank, kein App-Start.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from jurisdictions.documents import (
    DocumentKeyError,
    PackDocumentSet,
    default_documents,
    document_paths,
    documents_for,
    load_document_set,
)
from jurisdictions.registry import PACKS_ROOT, PackRegistryError, default_registry

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BUILD_BACKEND_SCRIPT = BACKEND_ROOT.parent / "ares-desktop" / "scripts" / "build-backend.js"

# Erzeugt auf X1 (2706c349) aus den bisherigen Konstanten/Literalen:
# sha256 ueber json.dumps(wert, ensure_ascii=False, separators=(",", ":")),
# Tupel als Listen. Nie anpassen, um einen Test gruen zu machen: ein
# abweichender Digest ist eine Textaenderung.
BEFORE_DIGESTS = {
    "legal.footer.disclaimer": "sha256:08b31b18f1330ba1154981b0b71c6f0734adb8d77b3b1b59516107977916b876",
    "cost_disclosure.cover.title": "sha256:7c8051b8bf43178ae61344b0d6159b30467b99933987499186af79caa344485b",
    "cost_disclosure.cover.subtitle": "sha256:8de8dd79369239fdc7dac30ac43fcaf4774dcd3350e108bb336801a3d4d0e701",
    "cost_disclosure.cover.focus_points": "sha256:6b5ef1b1e47d3812287bf909a079d7620646e9e78640ef74b91f5ac323e0930a",
}

# Gepinnter Inhalts-Hash aller CH-Texte (jede Textaenderung ist sichtbar).
CH_DOCUMENTS_HASH = "sha256:945c24f22efb710a0cb81ad9af3af3e41fa7144908df4307e6793b3de6777385"

def _norm(value):
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    return value


def _digest(value) -> str:
    raw = json.dumps(_norm(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _type_name(value) -> str:
    if isinstance(value, list):
        return f"list[{type(value[0]).__name__}]"
    return type(value).__name__


# --------------------------------------------------------------------------
# Vorher == nachher
# --------------------------------------------------------------------------


def test_every_pack_text_is_byte_identical_to_the_previous_constant():
    docs = default_documents()
    assert set(docs.keys()) == set(BEFORE_DIGESTS), "jeder Pack-Schluessel braucht einen Vorher-Digest"
    for key, expected in BEFORE_DIGESTS.items():
        assert _digest(docs.value(key)) == expected, key


def test_ch_documents_hash_is_pinned():
    assert default_documents().documents_hash == CH_DOCUMENTS_HASH


def test_static_texts_stay_core_constants_without_pack_import():
    # Entscheid zu X3: static_texts bleibt Kern-Konstante (kein Fan-out 0->1),
    # deshalb keine Kopie der Texte im Pack (keine zweite Wahrheit).
    import ast

    source = (BACKEND_ROOT / "services" / "pdf" / "components" / "static_texts.py").read_text(encoding="utf-8")
    imported = [
        node.module for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not any(m.startswith("jurisdictions") for m in imported), imported
    assert not any(key.startswith("strategy_report.") or key.startswith("legal.disclaimer.") for key in default_documents().keys())


def test_footer_constant_and_runtime_text_come_from_the_document_set(monkeypatch):
    footer = importlib.import_module("services.pdf.components.footer")
    assert footer.FIDLEG_DISCLAIMER == default_documents().text("legal.footer.disclaimer")
    assert _digest(footer.FIDLEG_DISCLAIMER) == BEFORE_DIGESTS["legal.footer.disclaimer"]

    class _Canvas:
        def __init__(self):
            self.strings = []

        def getPageNumber(self):
            return 1

        def drawString(self, _x, _y, text):
            self.strings.append(text)

        drawRightString = drawString

        def __getattr__(self, _name):
            return lambda *a, **k: None

    import datetime as _dt

    ctx = SimpleNamespace(audit_hash="ab" * 10, report_date=_dt.date(2026, 1, 15))
    expected = footer.FIDLEG_DISCLAIMER + " Erstellt am 15.01.2026."
    canvas = _Canvas()
    footer.make_footer_callback(ctx)(canvas, None)
    # Zeile 1 ist wie bisher (inkl. Kuerzung auf 220 Zeichen).
    assert canvas.strings[0] == (expected if len(expected) <= 220 else expected[:217] + "...")

    # Laufzeit-Lookup ueber das DocumentSet (nicht ueber die Modulkonstante).
    stub = SimpleNamespace(text=lambda key: f"<{key}>")
    monkeypatch.setattr(footer, "default_documents", lambda: stub)
    canvas = _Canvas()
    footer.make_footer_callback(ctx)(canvas, None)
    assert canvas.strings[0] == "<legal.footer.disclaimer> Erstellt am 15.01.2026."


def test_cost_disclosure_cover_reads_title_subtitle_and_articles_from_the_document_set(monkeypatch):
    module = importlib.import_module("services.pdf.documents.cost_disclosure")
    captured = {}

    def _cover(ctx, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(module, "make_single_report_cover", _cover)
    monkeypatch.setattr(module, "make_provisional_notice_flowables", lambda *a, **k: [])
    monkeypatch.setattr(module, "build_kostenausweis_flowables", lambda *a, **k: [])
    monkeypatch.setattr(module, "make_advisory_styles", lambda: {})
    ctx = SimpleNamespace(base_currency="CHF", provisional_notice=None)
    data = SimpleNamespace(advisory_wealth_rappen=0, mandate_number="M-1", payload={})
    module.build_cost_disclosure_flowables(ctx, data)

    assert _digest(captured["title"]) == BEFORE_DIGESTS["cost_disclosure.cover.title"]
    assert _digest(captured["subtitle"]) == BEFORE_DIGESTS["cost_disclosure.cover.subtitle"]
    assert _digest(captured["focus_points"]) == BEFORE_DIGESTS["cost_disclosure.cover.focus_points"]
    assert isinstance(captured["focus_points"], list)


    # Quelle (Vorpruefung B-8): der Digest-Vergleich allein bliebe auch mit
    # wieder eingesetzten Literalen gruen. Mit Sentinel-Texten im DocumentSet
    # muss das Deckblatt genau diese Sentinels zeigen.
    sentinel = SimpleNamespace(
        text=lambda key: f"<{key}>",
        paragraphs=lambda key: (f"<{key}#1>", f"<{key}#2>"),
    )
    monkeypatch.setattr(module, "default_documents", lambda: sentinel)
    captured.clear()
    module.build_cost_disclosure_flowables(ctx, data)
    assert captured["title"] == "<cost_disclosure.cover.title>"
    assert captured["subtitle"] == "<cost_disclosure.cover.subtitle>"
    assert captured["focus_points"] == [
        "<cost_disclosure.cover.focus_points#1>",
        "<cost_disclosure.cover.focus_points#2>",
    ]


def test_x1_reference_fingerprint_is_unchanged():
    # Die X1-Referenzen (u.a. FIDLEG_DISCLAIMER, DISCLAIMER_TEXT) zeigen
    # weiterhin auf dieselben Werte; der X1-Fingerprint bleibt gueltig.
    x1 = importlib.import_module("tests.test_jurisdiction_pack_registry")
    references = importlib.import_module("jurisdictions.ch.references").REFERENCES
    from jurisdictions.registry import content_hash

    assert content_hash(references) == x1.CH_REFERENCES_FINGERPRINT


# --------------------------------------------------------------------------
# DocumentSet-Conformance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("pack", default_registry().all(), ids=lambda p: f"{p.code}@{p.version}")
def test_every_registered_pack_has_complete_texts_for_each_locale(pack):
    docs = documents_for(pack.code, pack.version)
    assert isinstance(docs, PackDocumentSet)
    assert docs.locales == pack.locales
    reference = set(docs.keys(docs.locales[0]))
    for locale in docs.locales:
        assert set(docs.keys(locale)) == reference
        for key in docs.keys(locale):
            value = docs.value(key, locale)
            flat = [value] if isinstance(value, str) else [x for v in value for x in ([v] if isinstance(v, str) else v)]
            assert flat and all(isinstance(x, str) and x.strip() for x in flat), key
            assert not any(marker in x for x in flat for marker in ("TODO", "TBD")), key
    assert docs.locked_namespaces == {key.split(".", 1)[0] for key in reference}


def test_unknown_key_and_locale_fail_closed():
    docs = default_documents()
    with pytest.raises(DocumentKeyError):
        docs.text("legal.does_not_exist")
    with pytest.raises(DocumentKeyError):
        docs.text("legal.footer.disclaimer", "fr-CH")
    with pytest.raises(DocumentKeyError):
        docs.text("cost_disclosure.cover.focus_points")  # Liste, kein Einzeltext
    with pytest.raises(DocumentKeyError):
        docs.paragraphs("legal.footer.disclaimer")
    with pytest.raises(DocumentKeyError):
        docs.pairs("cost_disclosure.cover.focus_points")
    with pytest.raises(DocumentKeyError):
        documents_for("XX")
    with pytest.raises(NotImplementedError):
        docs.template("vertrag", "de-CH")


def test_text_parameters_are_formatted_only_when_given(tmp_path):
    pack, root = _copy_ch_pack(tmp_path)
    (root / "ch" / "documents" / "de-CH" / "extra.yaml").write_text(
        'namespace: extra\ntexts:\n  "greeting": "Guten Tag {name}"\n'
        '  "terms": [["A", "Erklaerung A"], ["B", "Erklaerung B"]]\n',
        encoding="utf-8",
    )
    docs = load_document_set(pack, root)
    assert docs.pairs("extra.terms") == (("A", "Erklaerung A"), ("B", "Erklaerung B"))
    assert docs.text("extra.greeting") == "Guten Tag {name}"
    assert docs.text("extra.greeting", name="Ares") == "Guten Tag Ares"


def _copy_ch_pack(tmp_path):
    root = tmp_path / "packs"
    shutil.copytree(PACKS_ROOT / "ch" / "documents", root / "ch" / "documents")
    return default_registry().latest("CH"), root


def _write(root, name, body):
    (root / "ch" / "documents" / "de-CH" / name).write_text(body, encoding="utf-8")


@pytest.mark.parametrize(
    "name, body, message",
    [
        ("other.yaml", 'namespace: legal\ntexts:\n  "x": "y"\n', "passt nicht zum Dateinamen"),
        ("empty.yaml", 'namespace: empty\ntexts:\n  "x": "  "\n', "leerer Text"),
        ("bad.yaml", 'namespace: bad\ntexts:\n  "x": 3\n', "Wert muss Text"),
        ("extra.yaml", 'namespace: extra\ntexts:\n  "x": "y"\nmore: 1\n', "Schluessel muessen genau"),
        ("none.yaml", "namespace: none\ntexts: {}\n", "nicht-leeres Mapping"),
    ],
)
def test_loader_rejects_invalid_text_files(tmp_path, name, body, message):
    pack, root = _copy_ch_pack(tmp_path)
    _write(root, name, body)
    with pytest.raises(PackRegistryError, match=message):
        load_document_set(pack, root)


def test_loader_requires_every_declared_locale_with_identical_keys(tmp_path):
    from dataclasses import replace

    pack, root = _copy_ch_pack(tmp_path)
    two_locales = replace(pack, locales=("de-CH", "fr-CH"))
    with pytest.raises(PackRegistryError, match="Locale 'fr-CH'"):
        load_document_set(two_locales, root)
    shutil.copytree(root / "ch" / "documents" / "de-CH", root / "ch" / "documents" / "fr-CH")
    assert load_document_set(two_locales, root).locales == ("de-CH", "fr-CH")
    (root / "ch" / "documents" / "fr-CH" / "legal.yaml").write_text(
        'namespace: legal\ntexts:\n  "footer.disclaimer": "x"\n  "only.in.fr": "y"\n', encoding="utf-8"
    )
    with pytest.raises(PackRegistryError, match="weicht in Schluesseln ab"):
        load_document_set(two_locales, root)


def test_documents_hash_ignores_yaml_formatting(tmp_path):
    pack, root = _copy_ch_pack(tmp_path)
    for path in (root / "ch" / "documents" / "de-CH").glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        path.write_text("# anderer Kommentar\n" + yaml.safe_dump(raw, allow_unicode=True, width=60), encoding="utf-8")
    assert load_document_set(pack, root).documents_hash == default_documents().documents_hash


# --------------------------------------------------------------------------
# legal_basis-Alias, Importgrenzen, Desktop-Bundle
# --------------------------------------------------------------------------


def test_legal_basis_is_a_read_alias_that_is_not_serialized():
    from schemas.cost_disclosure import CostDisclosureResponse

    assert "legal_basis" not in CostDisclosureResponse.model_fields
    assert "legal_basis" not in json.dumps(CostDisclosureResponse.model_json_schema())
    assert CostDisclosureResponse.legal_basis.fget is not None
    probe = SimpleNamespace(fidleg_basis="Art. 8/9 FIDLEG; Art. 8/14 FIDLEV")
    assert CostDisclosureResponse.legal_basis.fget(probe) == probe.fidleg_basis


@pytest.fixture(scope="module")
def ratchet_gate():
    name = "check_architecture_ratchets_for_documents"
    spec = importlib.util.spec_from_file_location(name, BACKEND_ROOT / "scripts" / "check_architecture_ratchets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(name, None)


def test_document_set_imports_nothing_outside_the_package(ratchet_gate):
    fan_out = ratchet_gate.measure(ratchet_gate.scan_backend())["fan_out"]
    targets = fan_out.get("jurisdictions.documents", [])
    assert targets and all(t.startswith("jurisdictions") for t in targets), targets
    assert "jurisdictions.ch.references" not in targets


def test_desktop_bundle_ships_every_pack_yaml():
    script = BUILD_BACKEND_SCRIPT.read_text(encoding="utf-8")
    yaml_files = sorted(
        p for p in PACKS_ROOT.rglob("*.yaml") if not any(part.startswith(("_", ".")) for part in p.relative_to(PACKS_ROOT).parts)
    )
    assert set(document_paths()) <= set(yaml_files)
    listed = re.search(r"const jurisdictionPackManifests = \[(.*?)\];", script, re.DOTALL)
    assert listed, "Liste jurisdictionPackManifests fehlt in build-backend.js"
    for path in yaml_files:
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        assert f"'{rel}'" in listed.group(1), f"{rel} fehlt als --add-data in build-backend.js"
