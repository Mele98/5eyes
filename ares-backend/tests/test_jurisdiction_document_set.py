"""X3 (OPTIMIZATION): DocumentSet fuer Rechts- und Pflichttexte.

Belegt:
- Vorher == nachher je Schluessel: ``BEFORE_DIGESTS`` wurde auf dem
  Ausgangs-SHA (X1, 2706c349) aus den damaligen Kernkonstanten bzw.
  -Literalen erzeugt (footer.FIDLEG_DISCLAIMER, static_texts.*, Deckblatt-
  Literale von pdf/documents/cost_disclosure.py). Jeder Pack-Text muss
  diesen Digest byte-genau treffen, und es gibt keinen ungeprueften
  Schluessel.
- Die Kern-Komponenten lesen ueber das DocumentSet (Footer zur Laufzeit,
  Kostenausweis-Deckblatt zur Laufzeit, static_texts als Fassade mit
  unveraenderten Namen und Typen).
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
    "legal.disclaimer.title": "sha256:53fa1b5b6487d12fb5b8bab7379ddcbc6136608d7dd81da699a93ca575d209ef",
    "legal.disclaimer.paragraphs": "sha256:d8f235f1bd492cd1312bc9e28ff07f0ad5027c3d71d6081e8024594170d7fc28",
    "strategy_report.investment_approach.title": "sha256:ac84cb33490b0a619866f2dfc413512ffd0bca819a13d389ea357ba65d2cddfa",
    "strategy_report.investment_approach.paragraphs": "sha256:ebcf2494a2136a7e8f7fce418c3e45131ed0b0ff286582937a6abb3ee9b76337",
    "strategy_report.investment_universe.title": "sha256:ef4e33ff7da37a1447702b67056420282c70c6fc689ddc904a6325377ae54a49",
    "strategy_report.investment_universe.intro": "sha256:9015cb3576afec21c574e93f4299be79c8b0219ff93e0d45753d678bc0cb8700",
    "strategy_report.investment_universe.bullets": "sha256:7393ca22566e286fff6de516991078a042ce2b6cbdb88c2d22ac5538870f6056",
    "strategy_report.investment_universe.outro": "sha256:ee794ea9ee3923ded3c9fcdcae9f30ed0ff305653290e0e37d68ab96397d1cda",
    "strategy_report.summary.title": "sha256:36df2e104dc27be85b91da21dd4601145f3e5282644539579bdbaa86e56616b5",
    "strategy_report.summary.paragraphs": "sha256:c6a2be78c32979ae769e5c431ebbe903fc4557178368548e199d7979887c9558",
    "strategy_report.metrics.title": "sha256:48918e6ef7f0a9ed9a7cbf9bc635336d9bd96b56a3e06b4639359d7d4fb76bef",
    "strategy_report.metrics.definitions": "sha256:33367b59b9d7646f0a7a0ee4d41cbc1a4258380dfc2cee0cca5756c2c6e44d2e",
    "strategy_report.cover.tagline": "sha256:e46269bce46580f711a1f73faaff5d9c562b6ed0cac0858c6325db3886866e2d",
    "cost_disclosure.cover.title": "sha256:7c8051b8bf43178ae61344b0d6159b30467b99933987499186af79caa344485b",
    "cost_disclosure.cover.subtitle": "sha256:8de8dd79369239fdc7dac30ac43fcaf4774dcd3350e108bb336801a3d4d0e701",
    "cost_disclosure.cover.focus_points": "sha256:6b5ef1b1e47d3812287bf909a079d7620646e9e78640ef74b91f5ac323e0930a",
}

# Gepinnter Inhalts-Hash aller CH-Texte (jede Textaenderung ist sichtbar).
CH_DOCUMENTS_HASH = "sha256:bab9ec98226c9f67cf59709dc4286af8d4aca3292b3626b144395f5f2c152f2d"

# static_texts-Fassade: Name -> (Schluessel, bisheriger Typ).
STATIC_TEXTS = {
    "INVESTITIONSANSATZ_TITLE": ("strategy_report.investment_approach.title", "str"),
    "INVESTITIONSANSATZ_TEXT": ("strategy_report.investment_approach.paragraphs", "list[str]"),
    "ANLAGEUNIVERSUM_TITLE": ("strategy_report.investment_universe.title", "str"),
    "ANLAGEUNIVERSUM_INTRO": ("strategy_report.investment_universe.intro", "str"),
    "ANLAGEUNIVERSUM_BULLETS": ("strategy_report.investment_universe.bullets", "list[str]"),
    "ANLAGEUNIVERSUM_OUTRO": ("strategy_report.investment_universe.outro", "list[str]"),
    "ZUSAMMENFASSUNG_TITLE": ("strategy_report.summary.title", "str"),
    "ZUSAMMENFASSUNG_TEXT": ("strategy_report.summary.paragraphs", "list[str]"),
    "KENNZAHLEN_TITLE": ("strategy_report.metrics.title", "str"),
    "KENNZAHLEN_DEFINITIONS": ("strategy_report.metrics.definitions", "list[tuple]"),
    "DISCLAIMER_TITLE": ("legal.disclaimer.title", "str"),
    "DISCLAIMER_TEXT": ("legal.disclaimer.paragraphs", "list[str]"),
    "COVER_TAGLINE": ("strategy_report.cover.tagline", "str"),
}


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


def test_static_texts_facade_keeps_names_types_and_bytes():
    static_texts = importlib.import_module("services.pdf.components.static_texts")
    docs = default_documents()
    for name, (key, type_name) in STATIC_TEXTS.items():
        value = getattr(static_texts, name)
        assert _type_name(value) == type_name, name
        assert _norm(value) == _norm(docs.value(key)), name
        assert _digest(value) == BEFORE_DIGESTS[key], name


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
        docs.text("legal.disclaimer.paragraphs")  # Liste, kein Einzeltext
    with pytest.raises(DocumentKeyError):
        docs.paragraphs("legal.footer.disclaimer")
    with pytest.raises(DocumentKeyError):
        docs.pairs("legal.disclaimer.paragraphs")
    with pytest.raises(DocumentKeyError):
        documents_for("XX")
    with pytest.raises(NotImplementedError):
        docs.template("vertrag", "de-CH")


def test_text_parameters_are_formatted_only_when_given(tmp_path):
    pack, root = _copy_ch_pack(tmp_path)
    (root / "ch" / "documents" / "de-CH" / "extra.yaml").write_text(
        'namespace: extra\ntexts:\n  "greeting": "Guten Tag {name}"\n', encoding="utf-8"
    )
    docs = load_document_set(pack, root)
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
        'namespace: legal\ntexts:\n  "footer.disclaimer": "x"\n', encoding="utf-8"
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
