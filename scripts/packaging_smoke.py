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
   inklusive Pflicht-Pack CH.
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
import json
import os
import re
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


def http_get(url: str, timeout: float = 5.0) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={'Accept': '*/*'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() or b''


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
