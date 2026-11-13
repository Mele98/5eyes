#!/usr/bin/env python3
"""Packaging-Smoke fuer das gepackte Windows-Backend (W1-803-03).

Prueft das Artefakt, das tatsaechlich ausgeliefert wird -- nicht den
Quellbaum:

1. Digests: sha256 von Backend-EXE und (falls --unpacked-dir) app.asar
   sowie der in ``resources/backend`` eingebetteten EXE; die eingebettete
   EXE muss byte-identisch mit dem Bundle sein.
2. Paketinhalt (statisch, PyInstaller-CArchive): ``ares_schema.sql``,
   alle PDF-Fonts (byte-identisch mit ``ares-backend/assets/fonts``) und
   die Reporting-Sub-App (``reporting_dist/index.html``) liegen IN der EXE.
   Laenderpakete (X1): jedes ``jurisdictions/<code>/pack.yaml`` des
   Quellbaums liegt byte-identisch im Paket und wird aus den Paket-Bytes
   mit dem produktiven Loader (``load_default_registry``) gelesen --
   inklusive Pflicht-Pack CH. Texte (X3): jede Textdatei
   ``jurisdictions/<code>/documents/<locale>/<namespace>.yaml`` liegt
   byte-identisch im Paket, und jeder Pack laedt sein DocumentSet aus den
   Paket-Bytes (``load_document_set``).
3. Start-Smoke (Laufzeit): die EXE wird als Kopie in einem frischen
   Temp-Verzeichnis gestartet. HOME/USERPROFILE/APPDATA/TEMP, DB_PATH und
   BACKUP_DIR zeigen ausschliesslich dorthin; Scheduler sind aus. Danach:
   ``/health/ready`` (200, app="Ares API", database="ok"),
   ``/health/live``, ``/reporting`` (SPA-index mit ``/reporting/assets/``)
   und ein referenziertes Asset muessen antworten.
4. Sauberes Beenden: CTRL_BREAK an die Prozessgruppe, Wartezeit, erst dann
   Zwangsabbruch (gilt als Fehler). Danach darf der Port nicht mehr
   belegt sein.
5. Schemafund (Laufzeit): alle in ``ares_schema.sql`` definierten Views
   existieren in der frisch angelegten Smoke-DB. Views entstehen NUR aus
   dem Rohschema (nicht aus dem ORM) -- fehlt das Schema im Paket, bleibt
   die DB ohne sie, obwohl ``/health/ready`` gruen waere.
6. Die produktiven Datenpfade (Default-DB, Datenordner) sind vor und nach
   dem Lauf unveraendert.
7. RB-1 Master-KEK: wie in der Desktop-Shell zeigt ``TENANT_MASTER_KEK_FILE``
   in den (temporaeren) userData-Ordner. Der Erststart erzeugt genau eine
   DPAPI-Ablage (Benutzer-Scope, Format-Kennung), der Schluessel steht in
   keinem Log; ein zweiter Start laedt dieselbe Ablage byte-identisch.
8. PDF-Render (B-9, Laufzeit): auf der frischen Smoke-DB werden ueber die
   HTTP-API ein Admin (Ersteinrichtung), ein synthetischer Kunde und ein
   Mandat angelegt; danach rendert die gepackte EXE Kunden-PDFs
   (``PDF_SMOKE_DOCUMENTS``). Jedes muss ein vollstaendiges PDF sein
   (``%PDF-`` ... ``%%EOF``, mit pypdf lesbar), die Fusszeile aus dem
   Laenderpaket-Text ``legal.footer.disclaimer`` tragen und die
   Editorial-Fonts (Inter, Cormorant Garamond) eingebettet verwenden.
   Geprueft wird jede Font-Resource, mit der tatsaechlich Text gezeigt wird
   (Seite, Form-XObjects rekursiv, Type0-Descendants): sie selbst braucht
   einen lesbaren, nichtleeren /FontFile*-Stream; auch ein nicht
   eingebetteter Standard-14-Font ist rot (C-853-02). Faellt
   der Renderer still auf Standard-Fonts zurueck (Fonts im Paket nicht
   gefunden), ist der Smoke rot -- ebenso bei einer Font-Warnung im Log.

Fail-closed: jede Abweichung, jede fehlende Pruefgrundlage (z.B. PyInstaller
nicht importierbar) und jeder Timeout fuehrt zu Exit 1. Nur Windows.

Aufruf (Repo-Root)::

    python scripts/packaging_smoke.py \
        --exe ares-desktop/bundle/backend/ares-api.exe \
        --unpacked-dir ares-desktop/dist/win-unpacked
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / 'ares-backend'
SCHEMA_SQL = BACKEND_ROOT / 'ares_schema.sql'
FONT_DIR = BACKEND_ROOT / 'assets' / 'fonts'
EXPECTED_APP = 'Ares API'
EXE_NAME = 'ares-api.exe'

# Archivnamen innerhalb der PyInstaller-EXE (siehe ares-desktop/scripts/build-backend.js).
ARCHIVE_SCHEMA = 'ares_schema.sql'
ARCHIVE_FONT_PREFIX = 'assets/fonts/'
ARCHIVE_REPORTING_INDEX = 'reporting_dist/index.html'
JURISDICTIONS_ROOT = BACKEND_ROOT / 'jurisdictions'
ARCHIVE_JURISDICTIONS_PREFIX = 'jurisdictions/'

# B-9: PDF-Render in der gepackten EXE. Risikoprofil und Vertrag brauchen nur
# ein Mandat (kein Risikoprofil, keine Empfehlung) und tragen die Fusszeile aus
# dem Laenderpaket-Text (services/pdf/components/footer.py).
PDF_SMOKE_DOCUMENTS = ('risikoprofil', 'vertrag')
FOOTER_DISCLAIMER_KEY = 'legal.footer.disclaimer'
# Die Fusszeile druckt den Disclaimer vollstaendig (umgebrochen, nie gekuerzt;
# footer.py, N-858-1). Geprueft wird deshalb der volle Laenderpaket-Text plus
# das Erstelldatum ("Erstellt am").
FOOTER_CREATED_MARKER = 'Erstellt am'
# services/pdf/fonts.py: eingebettete TrueType-Subsets heissen ``/ABCDEF+<Name>``.
EDITORIAL_FONT_FAMILIES = ('Inter', 'CormorantGaramond')
FONT_FALLBACK_LOG_MARKERS = ('Editorial PDF fonts missing', 'Editorial PDF font registration failed')

# RB-1: Vertrag der KEK-Ablage (ares-backend/config.py, KEK_STORE_*).
KEK_STORE_NAME = 'tenant-master-kek.dpapi'
KEK_STORE_MAGIC = b'ARES-KEK-DPAPI/1\n'
KEK_STORE_ENTROPY = b'ares.tenant-master-kek.store.v1'


class SmokeError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f'[packaging-smoke] {msg}', flush=True)


def fail(msg: str) -> None:
    raise SmokeError(msg)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 1. Digests
# ---------------------------------------------------------------------------
def check_digests(exe: Path, unpacked_dir: Path | None) -> None:
    if not exe.is_file():
        fail(f'Backend-EXE fehlt: {exe} (zuerst `npm run build:backend`).')
    exe_sha = sha256_file(exe)
    log(f'DIGEST sha256 {exe_sha}  {exe} ({exe.stat().st_size} bytes)')
    if unpacked_dir is None:
        log('Hinweis: --unpacked-dir nicht gesetzt, electron-builder-Ausgabe wird nicht geprueft.')
        return
    resources = unpacked_dir / 'resources'
    asar = resources / 'app.asar'
    embedded = resources / 'backend' / EXE_NAME
    if not asar.is_file():
        fail(f'app.asar fehlt im gepackten Verzeichnis: {asar}')
    if not embedded.is_file():
        fail(f'Eingebettete Backend-EXE fehlt (extraResources): {embedded}')
    asar_sha = sha256_file(asar)
    embedded_sha = sha256_file(embedded)
    log(f'DIGEST sha256 {asar_sha}  {asar} ({asar.stat().st_size} bytes)')
    log(f'DIGEST sha256 {embedded_sha}  {embedded}')
    if embedded_sha != exe_sha:
        fail('Eingebettete Backend-EXE weicht vom Bundle ab (sha256 ungleich).')
    shells = sorted(p for p in unpacked_dir.glob('*.exe') if p.is_file())
    if not shells:
        fail(f'Keine Electron-Shell-EXE in {unpacked_dir}.')
    if len(shells) != 1:
        fail(f'Erwartet genau eine Electron-Shell-EXE in {unpacked_dir}, gefunden: {len(shells)}.')
    # Dateiname stammt aus build.productName; geloggt wird nur der Digest.
    log(f'DIGEST sha256 {sha256_file(shells[0])}  <win-unpacked>/<productName>.exe')
    check_asar_frontend_resources(asar)


def _asar_file_paths(asar: Path) -> set[str]:
    """Pfade aller Dateien im asar-Header (Pickle: 4|hdr|payload|len|json)."""
    with asar.open('rb') as fh:
        head = fh.read(16)
        json_len = int.from_bytes(head[12:16], 'little')
        header = json.loads(fh.read(json_len).decode('utf-8'))
    paths: set[str] = set()

    def walk(node: dict, prefix: str) -> None:
        for name, child in (node.get('files') or {}).items():
            path = f'{prefix}{name}'
            if 'files' in child:
                walk(child, path + '/')
            else:
                paths.add(path)

    walk(header, '')
    return paths


def check_asar_frontend_resources(asar: Path) -> None:
    """H3/I-04: jede lokale Ressource von frontend/ares.html (ausgelagerte
    Skripte/Stylesheets, Vendor) muss im gepackten app.asar liegen -- Electron
    laedt ares.html per loadFile, eine fehlende Datei waere still kaputt."""
    html = (REPO_ROOT / 'ares-desktop' / 'frontend' / 'ares.html').read_text(encoding='utf-8')
    refs = re.findall(r'<(?:script|link)\b[^>]*\b(?:src|href)="([^"\'+]+)"', html)
    local = sorted({r[2:] if r.startswith('./') else r for r in refs
                    if not re.match(r'^[a-z]+:|^//|^#', r)})
    if not local:
        fail('ares.html: keine lokalen Skript-/Stylesheet-Referenzen gefunden (Regex pruefen).')
    packed = _asar_file_paths(asar)
    if 'frontend/ares.html' not in packed:
        fail('frontend/ares.html fehlt im app.asar.')
    missing = [ref for ref in local if f'frontend/{ref}' not in packed]
    if missing:
        fail(f'Frontend-Ressourcen fehlen im app.asar: {missing}')
    log(f'OK Frontend-Ressourcen im app.asar: ares.html + {len(local)} lokale Referenzen')


# ---------------------------------------------------------------------------
# 2. Paketinhalt der PyInstaller-EXE
# ---------------------------------------------------------------------------
def check_archive(exe: Path) -> None:
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError as exc:  # fail-closed: ohne Leser keine Inhaltspruefung
        fail(f'PyInstaller nicht importierbar, Paketinhalt nicht pruefbar: {exc}')
    archive = CArchiveReader(str(exe))
    names = set(archive.toc.keys())
    normalized = {name.replace('\\', '/'): name for name in names}

    if ARCHIVE_SCHEMA not in normalized:
        fail(f'{ARCHIVE_SCHEMA} fehlt im Paket.')
    schema_bytes = archive.extract(normalized[ARCHIVE_SCHEMA])
    if hashlib.sha256(schema_bytes).hexdigest() != sha256_file(SCHEMA_SQL):
        fail(f'{ARCHIVE_SCHEMA} im Paket weicht vom Quellstand ab.')
    log(f'OK Schema im Paket: {ARCHIVE_SCHEMA} ({len(schema_bytes)} bytes, identisch mit Quelle)')

    source_fonts = sorted(FONT_DIR.glob('*.ttf'))
    if not source_fonts:
        fail(f'Keine Quell-Fonts unter {FONT_DIR}.')
    for font in source_fonts:
        key = ARCHIVE_FONT_PREFIX + font.name
        if key not in normalized:
            fail(f'PDF-Font fehlt im Paket: {key}')
        data = archive.extract(normalized[key])
        if hashlib.sha256(data).hexdigest() != sha256_file(font):
            fail(f'PDF-Font im Paket weicht von der Quelle ab: {key}')
    log(f'OK PDF-Fonts im Paket: {len(source_fonts)} Dateien, alle identisch mit Quelle')

    if ARCHIVE_REPORTING_INDEX not in normalized:
        fail(f'Reporting-Sub-App fehlt im Paket ({ARCHIVE_REPORTING_INDEX}).')
    assets = [n for n in normalized if n.startswith('reporting_dist/assets/')]
    if not assets:
        fail('Reporting-Sub-App im Paket ohne Assets (reporting_dist/assets/).')
    log(f'OK Reporting-Sub-App im Paket: index.html + {len(assets)} Assets')

    check_jurisdiction_packs(normalized, archive.extract)
    check_jurisdiction_documents(normalized, archive.extract)


def _source_pack_manifests(source_root: Path) -> list[Path]:
    # Gleiche Auswahl wie jurisdictions.registry.builtin_manifest_paths.
    return sorted(p for p in source_root.glob('*/pack.yaml')
                  if not p.parent.name.startswith(('_', '.')))


def _load_jurisdiction_loader(module: str):
    """Produktiven Loader aus dem Quellbaum laden (nur Stdlib + PyYAML)."""
    backend = str(BACKEND_ROOT)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    try:
        return importlib.import_module(module)
    except ImportError as exc:  # fail-closed: ohne Loader keine Lesbarkeitspruefung
        fail(f'{module} nicht importierbar, Laenderpakete nicht pruefbar: {exc}')


def check_jurisdiction_packs(normalized: Mapping[str, str], extract: Callable[[str], bytes],
                             source_root: Path = JURISDICTIONS_ROOT) -> None:
    """X1: Pack-Manifeste liegen im Paket und sind aus den Paket-Bytes lesbar.

    Fehlt ``pack.yaml`` im Bundle, meldet das Backend erst beim ersten
    Allokations-/Evidence-Aufruf ``PackRegistryError`` -- ``/health/ready``
    bliebe gruen. Deshalb hier statisch: Vollstaendigkeit gegen den
    Quellbaum, Byte-Identitaet, und Laden der extrahierten Bytes mit
    ``jurisdictions.registry.load_default_registry`` (Pflicht-Pack CH).
    """
    manifests = _source_pack_manifests(source_root)
    if not manifests:
        fail(f'Keine Laenderpaket-Manifeste unter {source_root} -- Pruefgrundlage fehlt.')
    registry_mod = _load_jurisdiction_loader('jurisdictions.registry')
    packaged = sorted(n for n in normalized
                      if n.startswith(ARCHIVE_JURISDICTIONS_PREFIX) and n.endswith('/pack.yaml'))
    expected = sorted(ARCHIVE_JURISDICTIONS_PREFIX + m.relative_to(source_root).as_posix()
                      for m in manifests)
    missing = [k for k in expected if k not in normalized]
    if missing:
        fail(f'Laenderpaket-Manifest fehlt im Paket: {", ".join(missing)}')
    extra = [k for k in packaged if k not in expected]
    if extra:
        fail(f'Laenderpaket-Manifest im Paket ohne Quelle: {", ".join(extra)}')
    with tempfile.TemporaryDirectory(prefix='ares-packaging-smoke-packs-') as tmp:
        root = Path(tmp)
        for manifest, key in zip(manifests, expected):
            data = extract(normalized[key])
            if hashlib.sha256(data).hexdigest() != sha256_file(manifest):
                fail(f'Laenderpaket-Manifest im Paket weicht von der Quelle ab: {key}')
            target = root / key[len(ARCHIVE_JURISDICTIONS_PREFIX):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        try:
            registry = registry_mod.load_default_registry(root)
        except registry_mod.PackRegistryError as exc:
            fail(f'Laenderpaket-Manifest im Paket nicht lesbar: {exc}')
        codes = registry.codes()
    log(f'OK Laenderpakete im Paket: {len(expected)} Manifest(e), identisch mit Quelle, '
        f'mit dem produktiven Loader lesbar (Packs: {", ".join(codes)})')


def _source_document_files(source_root: Path) -> list[Path]:
    # Gleiche Auswahl wie jurisdictions.documents.document_paths.
    return sorted(p for p in source_root.glob('*/documents/*/*.yaml')
                  if not p.relative_to(source_root).parts[0].startswith(('_', '.')))


def check_jurisdiction_documents(normalized: Mapping[str, str], extract: Callable[[str], bytes],
                                 source_root: Path = JURISDICTIONS_ROOT) -> None:
    """X3: Rechts-/Pflichttexte liegen im Paket und sind aus den Paket-Bytes lesbar.

    Fehlt eine Textdatei im Bundle, scheitern Kostenausweis und Fusszeilen
    erst beim PDF-Aufruf. Pruefung: Vollstaendigkeit gegen den Quellbaum
    (keine Datei ohne Quelle), Byte-Identitaet, und jeder registrierte Pack
    laedt sein DocumentSet mit ``jurisdictions.documents.load_document_set``
    aus den extrahierten Paket-Bytes (Manifeste + Texte).
    """
    documents = _source_document_files(source_root)
    if not documents:
        fail(f'Keine Laenderpaket-Texte unter {source_root} -- Pruefgrundlage fehlt.')
    manifests = _source_pack_manifests(source_root)
    registry_mod = _load_jurisdiction_loader('jurisdictions.registry')
    documents_mod = _load_jurisdiction_loader('jurisdictions.documents')
    expected = sorted(ARCHIVE_JURISDICTIONS_PREFIX + d.relative_to(source_root).as_posix()
                      for d in documents)
    packaged = sorted(n for n in normalized
                      if n.startswith(ARCHIVE_JURISDICTIONS_PREFIX) and '/documents/' in n
                      and n.endswith('.yaml'))
    missing = [k for k in expected if k not in normalized]
    if missing:
        fail(f'Laenderpaket-Text fehlt im Paket: {", ".join(missing)}')
    extra = [k for k in packaged if k not in expected]
    if extra:
        fail(f'Laenderpaket-Text im Paket ohne Quelle: {", ".join(extra)}')
    with tempfile.TemporaryDirectory(prefix='ares-packaging-smoke-docs-') as tmp:
        root = Path(tmp)
        for source in [*manifests, *documents]:
            key = ARCHIVE_JURISDICTIONS_PREFIX + source.relative_to(source_root).as_posix()
            if key not in normalized:
                fail(f'Laenderpaket-Datei fehlt im Paket: {key}')
            data = extract(normalized[key])
            if hashlib.sha256(data).hexdigest() != sha256_file(source):
                fail(f'Laenderpaket-Datei im Paket weicht von der Quelle ab: {key}')
            target = root / key[len(ARCHIVE_JURISDICTIONS_PREFIX):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        loaded = []
        try:
            registry = registry_mod.load_default_registry(root)
            for pack in registry.all():
                document_set = documents_mod.load_document_set(pack, root)
                loaded.append(f'{pack.code}@{pack.version}: {len(document_set.sources)} Datei(en)')
        except Exception as exc:  # PackRegistryError, YAMLError, OSError ... -- fail-closed mit Ursache
            fail(f'Laenderpaket-Texte im Paket nicht lesbar: {type(exc).__name__}: {exc}')
    log(f'OK Laenderpaket-Texte im Paket: {len(expected)} Datei(en), identisch mit Quelle, '
        f'mit dem produktiven Loader lesbar ({"; ".join(loaded)})')


# ---------------------------------------------------------------------------
# 3.-5. Laufzeit-Smoke
# ---------------------------------------------------------------------------
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def http_request(url: str, *, method: str = 'GET', json_body: object | None = None,
                 headers: Mapping[str, str] | None = None,
                 timeout: float = 5.0) -> tuple[int, dict, bytes]:
    all_headers = {'Accept': '*/*', **(headers or {})}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode('utf-8')
        all_headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() or b''


def http_get(url: str, timeout: float = 5.0) -> tuple[int, dict, bytes]:
    return http_request(url, timeout=timeout)


# ---------------------------------------------------------------------------
# 8. PDF-Render (B-9)
# ---------------------------------------------------------------------------
# H7 N-884-03: Fusszeile je Mandatstyp (gleiche Zuordnung wie
# services/pdf/components/footer.py::footer_disclaimer_key).
FOOTER_KEY_SUFFIX_BY_MANDATE_TYPE = {
    'vermögensverwaltung': 'vermoegensverwaltung',
    'vermoegensverwaltung': 'vermoegensverwaltung',
    'anlageberatung': 'anlageberatung',
    'finanzplanung': 'finanzplanung',
    'reporting only': 'reporting',
}


def expected_footer_disclaimer(mandate_type: str | None = None) -> str:
    """Voller Fusszeilen-Text aus dem Quellbaum (produktiver Loader), fuer den
    Mandatstyp des gerenderten Mandats (ohne Typ: neutraler Text).

    Die Paket-Bytes derselben Datei sind in ``check_jurisdiction_documents``
    als byte-identisch belegt; der Text im gerenderten PDF stammt also aus der
    Datei im Paket."""
    documents_mod = _load_jurisdiction_loader('jurisdictions.documents')
    suffix = FOOTER_KEY_SUFFIX_BY_MANDATE_TYPE.get(str(mandate_type or '').strip().casefold())
    key = f'{FOOTER_DISCLAIMER_KEY}.{suffix}' if suffix else FOOTER_DISCLAIMER_KEY
    text = documents_mod.default_documents().text(key)
    if not isinstance(text, str) or not text.strip():
        fail(f'{key} im Quellbaum leer -- PDF-Pruefung hat keine Grundlage.')
    return text


def _squash(text: str) -> str:
    return ' '.join(text.split())


def check_pdf_bytes(pdf: bytes, label: str, required_texts: tuple[str, ...]) -> str:
    """Gerendertes PDF pruefen; liefert eine Kurzbeschreibung fuer das Log."""
    if not pdf.startswith(b'%PDF-'):
        fail(f'{label}: Antwort ist kein PDF (Anfang {pdf[:40]!r}).')
    if b'%%EOF' not in pdf[-1024:]:
        fail(f'{label}: PDF unvollstaendig (kein %%EOF am Ende, {len(pdf)} bytes).')
    try:
        import pypdf
    except ImportError as exc:  # fail-closed: ohne Leser keine Inhaltspruefung
        fail(f'pypdf nicht importierbar, PDF-Inhalt nicht pruefbar: {exc}')
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        pages = list(reader.pages)
        text = _squash(' '.join(page.extract_text() or '' for page in pages))
        used, declared = _font_resource_usage(pages)
    except Exception as exc:  # pypdf-Fehler jeder Art -- fail-closed mit Ursache
        fail(f'{label}: PDF nicht lesbar: {type(exc).__name__}: {exc}')
    if not pages:
        fail(f'{label}: PDF ohne Seiten.')
    for needle in required_texts:
        if _squash(needle) not in text:
            fail(f'{label}: Pflichttext fehlt im PDF: {needle[:80]!r}')
    for family in EDITORIAL_FONT_FAMILIES:
        if not any(_editorial_family(u.base_font) == family and u.embedded for u in used):
            # C-853-01/02: weder der Subset-Name noch eine nur deklarierte
            # (unbenutzte) eingebettete Resource belegt die Einbettung.
            fail(f'{label}: Editorial-Font {family} nicht eingebettet '
                 f'(Fallback auf Standard-Fonts?); verwendete Fonts: '
                 f'{sorted(u.describe() for u in used)}')
    # C-853-02: jede vom Inhalt TATSAECHLICH verwendete Font-Resource (Seite,
    # Form-XObjects beliebig tief, Annotation-Erscheinungsbilder) muss selbst
    # einen lesbaren, nichtleeren /FontFile*-Stream haben -- auch ein nicht
    # eingebetteter Standard-14-Font ist ein Befund. Kein Abgleich ueber den
    # /BaseFont-Namen: eine eingebettete Dublette belegt nichts.
    unembedded = [u for u in used if not u.embedded]
    if unembedded:
        fail(f'{label}: verwendete Font-Resource nicht eingebettet: '
             f'{[u.describe() for u in unembedded]}')
    # Konservativ (Codex C-853-02): auch jede deklarierte, unbenutzte
    # Editorial-Font-Resource muss eingebettet sein.
    broken = [d for d in declared if _editorial_family(d.base_font) and not d.embedded]
    if broken:
        fail(f'{label}: Editorial-Font-Resource nicht eingebettet: '
             f'{[d.describe() for d in broken]}')
    return (f'{label} ({len(pdf)} bytes, {len(pages)} Seite(n), '
            f'{len(used)} verwendete Font-Resource(n) eingebettet)')


FONT_FILE_KEYS = ('/FontFile', '/FontFile2', '/FontFile3')
# Textausgabe-Operatoren (PDF 1.7, 9.4.3): erst sie verwenden den aktuellen Font.
TEXT_SHOW_OPERATORS = (b'Tj', b'TJ', b"'", b'"')
# Grenze gegen pathologisch tiefe Form-XObject-Verschachtelung.
MAX_FORM_DEPTH = 32


def _editorial_family(base_font: str) -> str | None:
    """Editorial-Familie eines Subset-Namens (``ABCDEF+Inter-Bold`` -> ``Inter``)."""
    for family in EDITORIAL_FONT_FAMILIES:
        if re.fullmatch(r'[A-Z]{6}\+' + family + r'(-\w+)?', base_font):
            return family
    return None


class FontUse:
    """Eine Font-Resource an genau einer Stelle: Seite, Ort (Seite, Form-XObject-
    Pfad, Annotation), Resource-Key, /BaseFont und Einbettungszustand."""

    __slots__ = ('page', 'where', 'key', 'base_font', 'state')

    def __init__(self, page: int, where: str, key: str, base_font: str, state: str):
        self.page, self.where, self.key = page, where, key
        self.base_font, self.state = base_font, state

    @property
    def embedded(self) -> bool:
        return self.state.startswith('eingebettet')

    def describe(self) -> str:
        return f'Seite {self.page} {self.where} {self.key} {self.base_font or "?"}: {self.state}'


def _font_embedding_state(font) -> str:
    """C-853-01: Fontobjekt bis zum /FontDescriptor aufloesen (Type0 ueber
    /DescendantFonts, jeder Descendant) und den Font-Stream lesen. Liefert
    ``eingebettet (...)`` oder den Grund, warum nicht."""
    try:
        target = font.get_object()
        if not hasattr(target, 'get'):
            return f'keine Font-Resource ({type(target).__name__})'
        if target.get('/Subtype') == '/Type0':
            descendants = target.get('/DescendantFonts')
            descendants = descendants.get_object() if descendants is not None else None
            if not descendants or not isinstance(descendants, list):
                return 'Type0 ohne /DescendantFonts'
            states = [_descriptor_stream_state(d.get_object()) for d in descendants]
            bad = [st for st in states if not st.startswith('eingebettet')]
            return f'Type0-Descendant {bad[0]}' if bad else states[0]
        return _descriptor_stream_state(target)
    except Exception as exc:  # kaputter Stream/Verweis -- fail-closed mit Ursache
        return f'Font-Stream nicht lesbar ({type(exc).__name__}: {exc})'


def _descriptor_stream_state(target) -> str:
    try:
        if not hasattr(target, 'get'):
            return f'keine Font-Resource ({type(target).__name__})'
        descriptor = target.get('/FontDescriptor')
        if descriptor is None:
            return 'ohne /FontDescriptor'
        descriptor = descriptor.get_object()
        keys = [k for k in FONT_FILE_KEYS if k in descriptor]
        if not keys:
            return 'ohne Font-Stream'
        data = descriptor[keys[0]].get_object().get_data()
    except Exception as exc:  # kaputter Stream/Verweis -- fail-closed mit Ursache
        return f'Font-Stream nicht lesbar ({type(exc).__name__}: {exc})'
    if not data:
        return f'leerer Font-Stream ({keys[0]})'
    return f'eingebettet ({keys[0]}, {len(data)} bytes)'


def _font_resource_usage(pages) -> tuple[list[FontUse], list[FontUse]]:
    """C-853-02: (verwendet, deklariert) je Font-Resource -- ohne Faltung nach
    /BaseFont. ``verwendet`` = jede Font-Resource, mit der ein Textoperator
    (Tj, TJ, ', ") Text zeigt -- im Inhalt der Seite, der aufgerufenen
    Form-XObjects (rekursiv, gegen deren eigene /Resources, Font aus dem
    Grafikzustand des Aufrufers geerbt) und der Annotation-Erscheinungsbilder,
    aufgeloest gegen die beim ``Tf`` geltenden Resources. ``deklariert`` = jede Font-Resource in diesen Resource-Dicts.
    Unaufloesbare Verweise und Zyklen sind Fehler (fail-closed)."""
    from pypdf.generic import ContentStream

    used: list[FontUse] = []
    declared: list[FontUse] = []

    def get_dict(container, key):
        value = container.get(key) if container is not None else None
        return value.get_object() if value is not None else {}

    def record(target: list, page_no: int, where: str, key: str, ref) -> None:
        if ref is None:
            target.append(FontUse(page_no, where, key, '', 'Resource fehlt'))
            return
        obj = ref.get_object()
        base = obj.get('/BaseFont') if hasattr(obj, 'get') else None
        target.append(FontUse(page_no, where, key, str(base or '').lstrip('/'),
                              _font_embedding_state(ref)))

    def walk(stream, resources, page_no: int, where: str, active: frozenset, pdf, depth: int,
             font=None):
        """``font`` = (Ort, Key, Resource) des aktuellen Fonts im Grafikzustand;
        ein Form-XObject erbt ihn vom Aufrufer, q/Q sichern und stellen ihn her."""
        if depth > MAX_FORM_DEPTH:
            raise ValueError(f'Form-XObjects tiefer als {MAX_FORM_DEPTH} ({where})')
        resources = resources.get_object() if resources is not None else None
        fonts = get_dict(resources, '/Font')
        xobjects = get_dict(resources, '/XObject')
        for key, ref in fonts.items():
            record(declared, page_no, where, str(key), ref)
        stack: list = []
        content = stream if isinstance(stream, ContentStream) else ContentStream(stream, pdf)
        for operands, operator in content.operations:
            if operator == b'q':
                stack.append(font)
            elif operator == b'Q':
                font = stack.pop() if stack else font
            elif operator == b'Tf' and operands:
                key = str(operands[0])
                font = (where, key, fonts.get(key))
            elif operator in TEXT_SHOW_OPERATORS:
                # Verwendet ist ein Font erst, wenn mit ihm Text gezeigt wird
                # (ReportLab setzt z. B. je Seite ein ungenutztes /F1 Helvetica).
                ident = (page_no,) + (font[:2] if font else ('', ''))
                if ident not in seen_uses:
                    seen_uses.add(ident)
                    if font is None:
                        used.append(FontUse(page_no, where, '?', '', 'Textausgabe ohne Font (Tf)'))
                    else:
                        record(used, page_no, font[0], font[1], font[2])
            elif operator == b'Do' and operands:
                name = str(operands[0])
                ref = xobjects.get(name)
                if ref is None:
                    raise ValueError(f'XObject {name} fehlt in den Resources ({where})')
                xobj = ref.get_object()
                if xobj.get('/Subtype') != '/Form':
                    continue
                ident = getattr(ref, 'idnum', None) or id(xobj)
                if ident in active:
                    raise ValueError(f'Form-XObject-Zyklus bei {name} ({where})')
                # Form ohne eigene /Resources erbt die des Aufrufers (PDF 1.7, 8.10.1).
                walk(xobj, xobj.get('/Resources', resources), page_no, f'{where}>{name}',
                     active | {ident}, pdf, depth + 1, font)

    seen_uses: set[tuple] = set()
    for page_no, page in enumerate(pages, start=1):
        resources = page.get('/Resources')
        contents = page.get_contents()
        if contents is not None:
            walk(contents, resources, page_no, 'Seite', frozenset(), page.pdf, 0)
        else:
            for key, ref in get_dict(resources.get_object() if resources is not None else None,
                                     '/Font').items():
                record(declared, page_no, 'Seite', str(key), ref)
        for annot in (page.get('/Annots') or []):
            annot = annot.get_object()
            appearance = get_dict(annot, '/AP').get('/N') if hasattr(annot, 'get') else None
            if appearance is None:
                continue
            appearance = appearance.get_object()
            streams = ([appearance] if hasattr(appearance, 'get_data')
                       else [v.get_object() for v in appearance.values()])
            for ap in streams:
                walk(ap, ap.get('/Resources', resources), page_no, 'Annotation',
                     frozenset(), page.pdf, 1)
    return used, declared


def run_pdf_render_smoke(base: str, documents: tuple[str, ...] = PDF_SMOKE_DOCUMENTS) -> list[str]:
    """Admin, Kunde und Mandat ueber die API anlegen und PDFs rendern lassen."""
    password = 'Smoke-' + secrets.token_urlsafe(18) + '-9a'

    def call(method: str, path: str, body: object | None = None,
             token: str | None = None) -> tuple[int, dict, bytes]:
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        return http_request(base + path, method=method, json_body=body, headers=headers,
                            timeout=60.0)

    def created(step: str, status: int, body: bytes) -> dict:
        if status != 201:
            fail(f'PDF-Smoke: {step} antwortet HTTP {status}: {body[:300]!r}')
        return json.loads(body)

    status, _, body = call('POST', '/auth/bootstrap-admin', {
        'username': 'packaging-smoke', 'password': password, 'full_name': 'Packaging Smoke',
    })
    admin = created('Ersteinrichtung (/auth/bootstrap-admin)', status, body)
    token = admin['access_token']
    status, _, body = call('POST', '/clients', {
        'client_number': 'SMOKE-1', 'first_name': 'Smoke', 'last_name': 'Paket',
        'advisor_id': admin['user']['id'], 'data_classification': 'synthetic',
    }, token)
    client = created('Kunde anlegen (/clients)', status, body)
    status, _, body = call('POST', f"/clients/{client['id']}/mandates", {
        'mandate_number': 'SMOKE-M1', 'data_classification': 'synthetic',
    }, token)
    mandate = created('Mandat anlegen', status, body)
    footer = expected_footer_disclaimer(mandate.get('mandate_type'))
    rendered = []
    for name in documents:
        status, headers, pdf = call('GET', f"/mandates/{mandate['id']}/reports/{name}.pdf",
                                    token=token)
        ctype = {k.lower(): v for k, v in headers.items()}.get('content-type', '')
        if status != 200 or 'application/pdf' not in ctype:
            fail(f'PDF-Smoke: {name}.pdf antwortet HTTP {status} ({ctype}): {pdf[:300]!r}')
        rendered.append(check_pdf_bytes(pdf, f'{name}.pdf', (footer, FOOTER_CREATED_MARKER)))
    return rendered


def assert_no_font_fallback(logtext: str) -> None:
    hits = [m for m in FONT_FALLBACK_LOG_MARKERS if m in logtext]
    if hits:
        fail(f'Backend-Log meldet Font-Fallback beim PDF-Render: {", ".join(hits)}')


def _load_db_location():
    """core/db_location.py direkt laden (Standardbibliothek, ohne Paket-Init)."""
    spec = importlib.util.spec_from_file_location(
        '_ares_db_location', BACKEND_ROOT / 'core' / 'db_location.py')
    if spec is None or spec.loader is None:
        fail('core/db_location.py nicht ladbar -- produktiver Datenpfad unbekannt.')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def live_paths() -> list[Path]:
    """Produktive Datenpfade des ausfuehrenden Benutzers (nie beschreiben).

    Quelle ist ``core.db_location.default_db_path()`` -- dieselbe Funktion,
    aus der ``config.Settings.db_path`` seinen Default bezieht.
    """
    live_db = Path(_load_db_location().default_db_path())
    return [live_db, live_db.parent, Path.home() / 'ares']


def snapshot(paths: list[Path]) -> dict[str, tuple | None]:
    out: dict[str, tuple | None] = {}
    for p in paths:
        try:
            st = p.stat()
            out[str(p)] = (st.st_size, st.st_mtime_ns) if p.is_file() else ('dir', len(list(p.iterdir())))
        except FileNotFoundError:
            out[str(p)] = None
    return out


def isolated_env(root: Path, port: int, db_path: Path) -> dict[str, str]:
    home = root / 'home'
    for sub in ('home', 'home/AppData/Roaming', 'home/AppData/Local', 'tmp', 'backups', 'data'):
        (root / sub).mkdir(parents=True, exist_ok=True)
    keep = ('SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH',
            'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS')
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env.update({
        'HOME': str(home),
        'USERPROFILE': str(home),
        'HOMEDRIVE': home.drive or 'C:',
        'HOMEPATH': str(home)[len(home.drive):] if home.drive else str(home),
        'APPDATA': str(home / 'AppData' / 'Roaming'),
        'LOCALAPPDATA': str(home / 'AppData' / 'Local'),
        'TEMP': str(root / 'tmp'),
        'TMP': str(root / 'tmp'),
        'PYTHONUNBUFFERED': '1',
        'APP_ENV': 'development',
        'APP_HOST': '127.0.0.1',
        'APP_PORT': str(port),
        'DB_PATH': str(db_path),
        'DB_USE_SQLCIPHER': 'false',
        'BACKUP_DIR': str(root / 'backups'),
        'LOG_DIR': str(root / 'logs'),
        'BACKUP_ENABLED': 'false',
        'BACKUP_SCHEDULER_ENABLED': 'false',
        'PRICE_SCHEDULER_ENABLED': 'false',
        'MARKET_DATA_DAILY_REFRESH_ENABLED': 'false',
        'MARKET_DATA_CACHE_PURGE_ENABLED': 'false',
        'TELEMETRY_ENABLED': 'false',
        'SMTP_ENABLED': 'false',
        # RB-1: wie die Desktop-Shell -- Ablage im (temporaeren) userData-Ordner.
        'TENANT_MASTER_KEK_FILE': str(kek_store_path(root)),
    })
    return env


def kek_store_path(root: Path) -> Path:
    return root / 'home' / 'AppData' / 'Roaming' / 'Ares' / KEK_STORE_NAME


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_char))]


def dpapi_unprotect(blob: bytes, entropy: bytes) -> bytes:
    """CryptUnprotectData (Benutzer-Scope) -- nur auf der Wegwerf-Ablage des Smokes."""
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
    ]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    in_buf = ctypes.create_string_buffer(blob, len(blob))
    ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
    in_blob = _DataBlob(len(blob), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    ent_blob = _DataBlob(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    out = _DataBlob()
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
                                      None, None, 0x01, ctypes.byref(out)):
        fail(f'KEK-Ablage nicht mit DPAPI (Benutzer-Scope) entschluesselbar '
             f'(Windows-Fehler {ctypes.get_last_error()}).')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def check_kek_store(root: Path) -> tuple[bytes, str]:
    store = kek_store_path(root)
    if not store.is_file():
        fail(f'Erststart hat keine KEK-Ablage angelegt: {store}')
    others = [p.name for p in store.parent.iterdir() if p.name != KEK_STORE_NAME]
    if others:
        fail(f'Neben der KEK-Ablage liegen unerwartete Dateien (Temp-Reste?): {others}')
    raw = store.read_bytes()
    if not raw.startswith(KEK_STORE_MAGIC):
        fail('KEK-Ablage hat nicht die erwartete Format-Kennung.')
    kek = dpapi_unprotect(raw[len(KEK_STORE_MAGIC):], KEK_STORE_ENTROPY).decode('ascii')
    if len(kek) != 44:
        fail('KEK-Ablage enthaelt keinen Fernet-Key.')
    if kek.encode('ascii') in raw:
        fail('KEK steht im Klartext in der Ablage.')
    return raw, kek


def assert_kek_not_logged(kek: str, paths: list[Path]) -> None:
    for path in paths:
        files = [path] if path.is_file() else (sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [])
        for item in files:
            if kek.encode('ascii') in item.read_bytes():
                fail(f'Master-KEK steht im Klartext in {item}.')


def run_restart_smoke(exe_copy: Path, env: dict[str, str], port: int, log_file: Path,
                      timeout: float, grace: float) -> None:
    """Zweiter Start auf derselben DB und Ablage: laedt die KEK, erzeugt keine neue."""
    base = f'http://127.0.0.1:{port}'
    with log_file.open('wb') as out:
        proc = subprocess.Popen(
            [str(exe_copy)], cwd=str(exe_copy.parent), env=env,
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            started = time.monotonic()
            ready = False
            while time.monotonic() - started < timeout:
                if proc.poll() is not None:
                    fail(f'Zweiter Start beendete sich vor Readiness (Exit {proc.returncode}).\n'
                         f'--- backend.log ---\n{tail(log_file)}')
                try:
                    status, _, _ = http_get(base + '/health/ready', timeout=3)
                    if status == 200:
                        ready = True
                        break
                except (urllib.error.URLError, ConnectionError, socket.timeout, OSError):
                    pass
                time.sleep(1)
            if not ready:
                fail(f'Zweiter Start nicht innerhalb {timeout:.0f}s bereit.\n'
                     f'--- backend.log ---\n{tail(log_file)}')
        finally:
            graceful = stop_process(proc, port, grace) if proc.poll() is None else False
    if not graceful:
        fail('Zweiter Start liess sich nicht sauber per CTRL_BREAK beenden.')
    text = log_file.read_text(encoding='utf-8', errors='replace')
    if 'Master-KEK: loaded' not in text:
        fail(f'Zweiter Start hat die KEK nicht aus der Ablage geladen.\n--- backend.log ---\n{tail(log_file)}')


def assert_not_live(db_path: Path) -> None:
    resolved = os.path.normcase(str(db_path.resolve()))
    for live in live_paths():
        live_norm = os.path.normcase(str(live.resolve()))
        if resolved == live_norm or resolved.startswith(live_norm + os.sep):
            fail(f'Smoke-DB {db_path} liegt im produktiven Datenpfad {live} -- Abbruch.')


def schema_view_names() -> list[str]:
    sql = SCHEMA_SQL.read_text(encoding='utf-8')
    names = re.findall(r'CREATE\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?(\w+)', sql, re.I)
    if not names:
        fail('ares_schema.sql definiert keine Views -- Schemafund-Pruefung hat keine Grundlage.')
    return sorted(set(names))


def tail(path: Path, lines: int = 60) -> str:
    try:
        return '\n'.join(path.read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])
    except FileNotFoundError:
        return '<kein Log>'


def stop_process(proc: subprocess.Popen, port: int, grace: float) -> bool:
    """CTRL_BREAK an die Prozessgruppe; True = sauber beendet."""
    graceful = False
    if proc.poll() is None:
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ValueError) as exc:
            log(f'CTRL_BREAK nicht zustellbar: {exc}')
        try:
            proc.wait(timeout=grace)
            graceful = True
        except subprocess.TimeoutExpired:
            graceful = False
    if proc.poll() is None:
        subprocess.run(['taskkill', '/pid', str(proc.pid), '/t', '/f'],
                       capture_output=True, check=False)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
    deadline = time.monotonic() + 30
    while port_open(port) and time.monotonic() < deadline:
        time.sleep(0.5)
    return graceful


def run_start_smoke(exe: Path, timeout: float, grace: float, keep: bool) -> None:
    root = Path(tempfile.mkdtemp(prefix='ares-packaging-smoke-'))
    log(f'Isoliertes Temp-Verzeichnis: {root}')
    proc: subprocess.Popen | None = None
    port = free_port()
    try:
        run_dir = root / 'run'
        run_dir.mkdir()
        exe_copy = run_dir / EXE_NAME
        shutil.copy2(exe, exe_copy)
        if sha256_file(exe_copy) != sha256_file(exe):
            fail('Kopie der Backend-EXE ist nicht byte-identisch.')
        db_path = root / 'data' / 'smoke.db'
        env = isolated_env(root, port, db_path)
        assert_not_live(db_path)
        if port_open(port):
            fail(f'Port {port} ist bereits belegt.')

        before = snapshot(live_paths())
        log_file = root / 'backend.log'
        base = f'http://127.0.0.1:{port}'
        log(f'Starte {exe_copy} auf {base} (cwd={run_dir})')
        with log_file.open('wb') as out:
            proc = subprocess.Popen(
                [str(exe_copy)], cwd=str(run_dir), env=env,
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            try:
                started = time.monotonic()
                ready_payload = None
                last = ''
                while time.monotonic() - started < timeout:
                    if proc.poll() is not None:
                        fail(f'Backend beendete sich vor Readiness (Exit {proc.returncode}).\n'
                             f'--- backend.log ---\n{tail(log_file)}')
                    try:
                        status, _, body = http_get(base + '/health/ready', timeout=3)
                        last = f'HTTP {status}: {body[:300]!r}'
                        if status == 200:
                            ready_payload = json.loads(body)
                            break
                    except (urllib.error.URLError, ConnectionError, socket.timeout, OSError) as exc:
                        last = str(exc)
                    time.sleep(1)
                if ready_payload is None:
                    fail(f'/health/ready nicht innerhalb {timeout:.0f}s bereit (zuletzt: {last}).\n'
                         f'--- backend.log ---\n{tail(log_file)}')
                log(f'OK /health/ready nach {time.monotonic() - started:.1f}s: '
                    f'{json.dumps({k: ready_payload.get(k) for k in ("status", "app", "version", "database")})}')
                if ready_payload.get('app') != EXPECTED_APP:
                    fail(f'/health/ready meldet app={ready_payload.get("app")!r}, erwartet {EXPECTED_APP!r}.')
                if ready_payload.get('database') != 'ok':
                    fail(f'/health/ready meldet database={ready_payload.get("database")!r}.')

                status, _, body = http_get(base + '/health/live')
                if status != 200:
                    fail(f'/health/live antwortet HTTP {status}.')
                log('OK /health/live')

                status, headers, body = http_get(base + '/reporting')
                ctype = {k.lower(): v for k, v in headers.items()}.get('content-type', '')
                html = body.decode('utf-8', errors='replace')
                if status != 200 or 'text/html' not in ctype:
                    fail(f'Reporting-Mount /reporting antwortet HTTP {status} ({ctype}).\n'
                         f'--- backend.log ---\n{tail(log_file)}')
                asset_refs = re.findall(r'(/reporting/assets/[\w.\-]+\.(?:js|css))', html)
                if not asset_refs:
                    fail('Reporting-index.html referenziert keine /reporting/assets/-Dateien.')
                status, _, asset_body = http_get(base + asset_refs[0])
                if status != 200 or not asset_body:
                    fail(f'Reporting-Asset {asset_refs[0]} antwortet HTTP {status}.')
                status_spa, _, _ = http_get(base + '/reporting/mandates/smoke/report')
                if status_spa != 200:
                    fail(f'Reporting-SPA-Fallback antwortet HTTP {status_spa}.')
                log(f'OK Reporting-Mount: /reporting, {asset_refs[0]} ({len(asset_body)} bytes), SPA-Fallback')

                rendered = run_pdf_render_smoke(base)
                log('OK PDF-Render in der gepackten EXE: ' + '; '.join(rendered)
                    + ' -- Fusszeile aus dem Laenderpaket-Text, Editorial-Fonts eingebettet')
            finally:
                if proc.poll() is None:
                    graceful = stop_process(proc, port, grace)
                else:
                    graceful = False
        if port_open(port):
            fail(f'Port {port} nach dem Beenden weiterhin belegt (verwaister Prozess).')
        if not graceful:
            fail('Backend liess sich nicht sauber per CTRL_BREAK beenden (Zwangsabbruch noetig).\n'
                 f'--- backend.log ---\n{tail(log_file)}')
        log(f'OK CTRL_BREAK beantwortet (Exit {proc.returncode}), Port {port} frei')

        logtext = log_file.read_text(encoding='utf-8', errors='replace')
        if 'Application shutdown complete' not in logtext:
            fail('Lifespan-Shutdown nicht im Backend-Log ("Application shutdown complete" fehlt).\n'
                 f'--- backend.log ---\n{tail(log_file)}')
        if 'Reporting-Dist nicht gefunden' in logtext:
            fail('Backend-Log meldet fehlende Reporting-Dist.')
        assert_no_font_fallback(logtext)
        log('OK Lifespan-Shutdown sauber durchlaufen (Application shutdown complete)')

        if not db_path.is_file():
            fail(f'Smoke-DB wurde nicht angelegt: {db_path}')
        expected_views = schema_view_names()
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as conn:
            present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
        missing = [v for v in expected_views if v not in present]
        if missing:
            fail(f'Schema aus dem Paket nicht angewendet -- Views fehlen in der Smoke-DB: {", ".join(missing)}')
        log(f'OK Schemafund: {len(expected_views)}/{len(expected_views)} Schema-Views in frischer DB '
            f'({", ".join(expected_views)})')

        if 'Master-KEK: generated' not in logtext:
            fail('Erststart hat keine Master-KEK erzeugt ("Master-KEK: generated" fehlt).\n'
                 f'--- backend.log ---\n{tail(log_file)}')
        store_bytes, kek = check_kek_store(root)
        log_file_2 = root / 'backend-restart.log'
        run_restart_smoke(exe_copy, env, port, log_file_2, timeout, grace)
        if kek_store_path(root).read_bytes() != store_bytes:
            fail('Zweiter Start hat die KEK-Ablage veraendert (darf nie ueberschrieben werden).')
        assert_kek_not_logged(kek, [log_file, log_file_2, root / 'logs'])
        log('OK RB-1 Master-KEK: Erststart erzeugt genau eine DPAPI-Ablage (Benutzer-Scope), '
            'zweiter Start laedt sie byte-identisch, kein Klartext in Logs')

        after = snapshot(live_paths())
        if before != after:
            fail(f'Produktive Datenpfade veraendert! vorher={before} nachher={after}')
        log('OK produktive Datenpfade unveraendert')
    finally:
        if proc is not None and proc.poll() is None:
            subprocess.run(['taskkill', '/pid', str(proc.pid), '/t', '/f'], capture_output=True, check=False)
        if keep:
            log(f'Temp-Verzeichnis behalten: {root}')
        else:
            shutil.rmtree(root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--exe', type=Path,
                        default=REPO_ROOT / 'ares-desktop' / 'bundle' / 'backend' / EXE_NAME)
    parser.add_argument('--unpacked-dir', type=Path, default=None,
                        help='electron-builder --dir Ausgabe (z.B. ares-desktop/dist/win-unpacked)')
    parser.add_argument('--timeout', type=float, default=180.0, help='Readiness-Timeout in Sekunden')
    parser.add_argument('--grace', type=float, default=30.0, help='Wartezeit nach CTRL_BREAK')
    parser.add_argument('--keep-temp', action='store_true')
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    if sys.platform != 'win32':
        log('FEHLER: Der Packaging-Smoke ist Windows-only (Release ist Windows-only).')
        return 1
    try:
        exe = args.exe.resolve()
        unpacked = args.unpacked_dir.resolve() if args.unpacked_dir else None
        check_digests(exe, unpacked)
        check_archive(exe)
        run_start_smoke(exe, args.timeout, args.grace, args.keep_temp)
    except SmokeError as exc:
        log(f'FEHLER: {exc}')
        return 1
    log('PASS: Packaging-Smoke gruen')
    return 0


if __name__ == '__main__':
    sys.exit(main())
