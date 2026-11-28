"""Release-Pruefungen des gepackten Artefakts (H-180, Teil von ``packaging_smoke.py``).

Ergaenzt den Packaging-Smoke um die Punkte des Release-Readiness-Pakets:

* EXE-01 Import-Selbsttest: ``ares-api.exe --self-test-imports`` importiert im
  gepackten Artefakt jedes eigene Modul und die lazy geladenen Laufzeitmodule
  (Optimizer/scipy, PDF). Ein fehlendes Modul ist rot -- frueher fiel die EXE
  dann still auf den House-Matrix-Default zurueck.
* EXE-02 Produkt-Hygiene: Windows-Dateieigenschaften beider EXEs (Produktname
  ``Ares``, Version = ``package.json``), keine Fremdmarke in Firma/Copyright/
  Beschreibung, keine Altmarke (Digest-Pruefung ``brand_digest_support``, nie
  Klartext) im app.asar, in den Paket-Metadaten (App-ID, Artefaktnamen,
  Verknuepfung), in den Dateinamen unter ``resources`` und in den Daten- und
  Namenseintraegen der Backend-EXE.
* EXE-03 Build-Kennung: ``/health`` der gepackten EXE meldet die Version aus
  ``package.json`` und den Git-SHA des Builds.
* EXE-05 Electron-Shell-Start: ``<productName>.exe`` startet in einem
  isolierten Profil (``--user-data-dir``, eigenes HOME/APPDATA/TEMP, eigene
  DB, freier Port), startet sein Backend, zeigt das Fenster ohne
  Renderer-Fehler und beendet sich auf WM_CLOSE samt Backend ohne
  verbleibende Prozesse.

Fail-closed wie der Smoke: jede Abweichung -> ``SmokeError``.
"""
from __future__ import annotations

import json
import marshal
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ROOT = REPO_ROOT / 'ares-desktop'
BACKEND_TESTS = REPO_ROOT / 'ares-backend' / 'tests'
PRODUCT_NAME = 'Ares'
# Fremdmarken/Geruest-Texte, die in sichtbaren Datei-Eigenschaften nie stehen duerfen.
THIRD_PARTY_MARKERS = ('openai', 'build skeleton', 'electron shell', 'github', 'microsoft')
SELF_TEST_MARKER = 'ARES_SELF_TEST_IMPORTS '
# EXE-04 (behoben in H-187): die CSP-Meta von ares.html enthaelt weder 'app://.'
# noch frame-ancestors mehr (test_electron_csp_meta_tag.py). Der Shell-Smoke laesst
# darum KEINEN Renderer-Fehler mehr zu.
# N-926-01 (H-187): Hinweise auf einen stillen Optimizer-Rueckfall im Backend-Log.
DEGRADED_LOG_MARKERS = ('not importable', 'Stochastic optimizer crashed', 'House-Matrix-Default bleibt aktiv')
MIN_OWN_MODULES = 300
TEXT_ARCHIVE_SUFFIXES = ('.json', '.yaml', '.yml', '.sql', '.html', '.txt', '.md', '.css', '.js')
# C-EXEPYZ-01: CArchive-Typcodes (PyInstaller). Ausfuehrbarer Python-Code
# ausserhalb des PYZ (Bootstrap, Runtime-Hooks, Entry-Script) liegt als
# marshal-Code-Objekt vor; jeder andere oder unbekannte Typ sperrt.
CARCHIVE_CODE_TYPES = frozenset('mMs')   # PYMODULE, PYPACKAGE, PYSOURCE
CARCHIVE_PYZ_TYPES = frozenset('z')      # eingebettetes PYZ (eigener Scan)
CARCHIVE_DATA_TYPES = frozenset('bxdln')  # BINARY, DATA, DEPENDENCY, SPLASH, SYMLINK
CARCHIVE_OPTION_TYPES = frozenset('o')   # Laufzeitoption ohne Inhalt (nur Name)
# C-EXEPYZ-02: Textabschnitte in Binaerdaten (wie ``strings``). Die Zeichen-
# klassen werden aus der Markennormalisierung abgeleitet (casefold, Entfernen
# von [\s_.\-], tests/brand_digest_support.normalize_text): relevant ist jedes
# BMP-Zeichen, das die Normalisierung entfernt oder das zu ASCII-Wortzeichen
# faltet. Kodierungen: ASCII/Latin-1-Einzelbyte, gueltiges UTF-8, UTF-16LE.
# Ein Marken-Fenster liegt deshalb vollstaendig in einem Abschnitt. Andere
# Einzel-Hochbytes gelten als Binaerrauschen (sonst waere fast jede Binaer-
# datei "Text"); die Stammformen selbst sind ASCII.
_NORM_SEPARATORS = re.compile(r'[\s_.\-]+')


def _normalization_relevant(ch: str) -> bool:
    if _NORM_SEPARATORS.fullmatch(ch):
        return True
    return any(c.isascii() and c.isalnum() for c in ch.casefold())


_RELEVANT_CHARS = tuple(
    chr(c) for c in range(0x10000) if not 0xD800 <= c <= 0xDFFF and _normalization_relevant(chr(c))
)
_LATIN1_LONE = {chr(0xDC00 + ord(ch)): ch for ch in _RELEVANT_CHARS if 0x80 <= ord(ch) <= 0xFF}
_TEXT_RUN_8 = re.compile(
    b'(?:[' + b''.join(re.escape(bytes([ord(ch)])) for ch in _RELEVANT_CHARS if ord(ch) <= 0xFF) + b']'
    + rb'|[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3}){5,}'
)
_TEXT_RUN_16 = re.compile(
    b'(?:' + b'|'.join(re.escape(ch.encode('utf-16-le')) for ch in _RELEVANT_CHARS) + b'){5,}'
)


def desktop_package() -> dict:
    return json.loads((DESKTOP_ROOT / 'package.json').read_text(encoding='utf-8'))


def git_head() -> str:
    out = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(REPO_ROOT), capture_output=True, text=True)
    return out.stdout.strip()


def _brand_checker() -> Callable[[str], set[str]]:
    sys.path.insert(0, str(BACKEND_TESTS))
    try:
        from brand_digest_support import brand_ids_in_text
    finally:
        sys.path.remove(str(BACKEND_TESTS))
    return brand_ids_in_text


# ---------------------------------------------------------------------------
# EXE-01 Import-Selbsttest
# ---------------------------------------------------------------------------
def check_self_test_imports(exe_copy: Path, env: dict[str, str], fail, log, timeout: float = 600.0) -> None:
    proc = subprocess.run([str(exe_copy), '--self-test-imports'], cwd=str(exe_copy.parent), env=env,
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    lines = [line for line in (proc.stdout or '').splitlines() if line.startswith(SELF_TEST_MARKER)]
    if not lines:
        fail(f'Import-Selbsttest ohne Ergebniszeile (Exit {proc.returncode}).\n'
             f'--- stdout ---\n{(proc.stdout or "")[-3000:]}\n--- stderr ---\n{(proc.stderr or "")[-3000:]}')
    result = json.loads(lines[-1][len(SELF_TEST_MARKER):])
    if not result.get('frozen'):
        fail('Import-Selbsttest lief nicht im gepackten Artefakt (frozen=false).')
    if proc.returncode != 0 or not result.get('ok') or result.get('failures'):
        fail('Import-Selbsttest der gepackten EXE rot -- fehlende Module: '
             + json.dumps(result.get('failures'), ensure_ascii=False))
    if int(result.get('own_modules') or 0) < MIN_OWN_MODULES:
        fail(f'Import-Selbsttest: nur {result.get("own_modules")} eigene Module gefunden '
             f'(erwartet >= {MIN_OWN_MODULES}); Paketinhalt unvollstaendig.')
    log(f'OK EXE-01 Import-Selbsttest im Artefakt: {result["checked"]} Module '
        f'({result["own_modules"]} eigene) importierbar, inkl. Optimizer/scipy und PDF')


# ---------------------------------------------------------------------------
# N-935-01 Strategie-Selbsttest (ersetzt das Testpaket im Server)
# ---------------------------------------------------------------------------
STRATEGY_SELF_TEST_MARKER = 'ARES_SELF_TEST_STRATEGY '


def check_self_test_strategy(exe_copy: Path, env: dict[str, str], package: Path, ic_label: str,
                             fallback_markers: tuple[str, ...], fail, log, timeout: float = 900.0) -> None:
    """``ares-api.exe --self-test-strategy <paket>``: eigener Prozess mit temporaerer
    DB, ohne Server und ohne Kundendokument. Verlangt den stochastischen Optimizer
    ohne Rueckfall und den vollen Vermerk ``ic_label`` (N-935-02)."""
    proc = subprocess.run([str(exe_copy), '--self-test-strategy', str(package)], cwd=str(exe_copy.parent),
                          env=env, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout)
    output = (proc.stdout or '') + '\n' + (proc.stderr or '')
    lines = [line for line in (proc.stdout or '').splitlines() if line.startswith(STRATEGY_SELF_TEST_MARKER)]
    if not lines:
        fail(f'Strategie-Selbsttest ohne Ergebniszeile (Exit {proc.returncode}).\n'
             f'--- stdout ---\n{(proc.stdout or "")[-3000:]}\n--- stderr ---\n{(proc.stderr or "")[-3000:]}')
    result = json.loads(lines[-1][len(STRATEGY_SELF_TEST_MARKER):])
    if not result.get('frozen'):
        fail('Strategie-Selbsttest lief nicht im gepackten Artefakt (frozen=false).')
    if proc.returncode != 0 or not result.get('ok'):
        fail('Strategie-Selbsttest der gepackten EXE rot: ' + json.dumps(result, ensure_ascii=False)
             + f'\n--- stderr ---\n{(proc.stderr or "")[-3000:]}')
    if result.get('optimizer') != 'stochastic' or int(result.get('constraints') or 0) < 1:
        fail('Strategie-Selbsttest: kein stochastischer Optimizer-Lauf: ' + json.dumps(result, ensure_ascii=False))
    if result.get('ic_label') != ic_label or result.get('ic_release_status') == 'RELEASED':
        fail(f'Strategie-Selbsttest: Vermerk {ic_label!r} fehlt: ' + json.dumps(result, ensure_ascii=False))
    if result.get('contract_documents'):
        fail('Strategie-Selbsttest hat Kundendokumente angelegt.')
    hits = [m for m in tuple(fallback_markers) + DEGRADED_LOG_MARKERS if m in output]
    if hits:
        fail(f'Strategie-Selbsttest meldet einen Rueckfall/ein fehlendes Modul: {hits}')
    log(f'OK N-926-01/N-935-01 Strategie-Selbsttest im Artefakt: stochastischer Optimizer '
        f'({result.get("status")}), {result["constraints"]} Constraints, kein Rueckfall, '
        f'Vermerk "{ic_label}", Datenbank {result.get("database")}, keine Kundendokumente')


def assert_no_degraded_modules(logtext: str, fail) -> None:
    hits = [marker for marker in DEGRADED_LOG_MARKERS if marker in logtext]
    if hits:
        fail(f'Backend-Log meldet einen degradierten Optimizer/ein fehlendes Modul: {hits}.')


# ---------------------------------------------------------------------------
# EXE-03 Build-Kennung
# ---------------------------------------------------------------------------
def check_build_identity(ready_payload: dict, fail, log) -> None:
    pkg = desktop_package()
    version = ready_payload.get('version')
    sha = ready_payload.get('build_sha')
    if version != pkg['version']:
        fail(f'/health meldet Version {version!r}, package.json {pkg["version"]!r} (eine Quelle verlangt).')
    head = git_head()
    if not sha or sha != head:
        fail(f'/health meldet build_sha {sha!r}, gebaut wurde {head!r}.')
    log(f'OK EXE-03 Build-Kennung: Version {version}, Build {sha[:12]}')


# ---------------------------------------------------------------------------
# EXE-02 Produkt-Hygiene
# ---------------------------------------------------------------------------
def version_info(path: Path) -> dict:
    """Windows-Versions-Ressource (StringFileInfo) ohne Shell -- ``pefile``
    (Abhaengigkeit von PyInstaller, requirements-build.txt)."""
    import pefile

    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        out: dict[str, str] = {}
        for info in getattr(pe, 'FileInfo', None) or []:
            for entry in info if isinstance(info, list) else [info]:
                for table in getattr(entry, 'StringTable', []) or []:
                    for key, value in table.entries.items():
                        out[key.decode('utf-8', 'replace')] = value.decode('utf-8', 'replace')
        return out
    finally:
        pe.close()


def _asar_entries(asar: Path):
    with asar.open('rb') as fh:
        head = fh.read(16)
        header_size = int.from_bytes(head[4:8], 'little')
        json_len = int.from_bytes(head[12:16], 'little')
        header = json.loads(fh.read(json_len).decode('utf-8'))
        base = 8 + header_size
        stack = [(header, '')]
        while stack:
            node, prefix = stack.pop()
            for name, child in (node.get('files') or {}).items():
                path = prefix + name
                if 'files' in child:
                    stack.append((child, path + '/'))
                elif not child.get('unpacked'):
                    fh.seek(base + int(child['offset']))
                    yield path, fh.read(int(child['size']))


def check_product_hygiene(exe: Path, unpacked_dir: Path, fail, log) -> None:
    brand_ids = _brand_checker()
    pkg = desktop_package()
    version = pkg['version']
    build = pkg.get('build') or {}

    # Paket-Metadaten (bestimmen Installer, Verknuepfung, App-ID, Artefaktnamen).
    meta = {
        'productName': pkg.get('productName'), 'build.productName': build.get('productName'),
        'build.appId': build.get('appId'), 'author': pkg.get('author'), 'description': pkg.get('description'),
        'build.copyright': build.get('copyright'),
        'win.artifactName': (build.get('win') or {}).get('artifactName'),
        'nsis.artifactName': (build.get('nsis') or {}).get('artifactName'),
        'nsis.shortcutName': (build.get('nsis') or {}).get('shortcutName'),
        'nsis.uninstallDisplayName': (build.get('nsis') or {}).get('uninstallDisplayName'),
        'portable.artifactName': (build.get('portable') or {}).get('artifactName'),
    }
    for key in ('productName', 'build.productName', 'nsis.shortcutName', 'nsis.uninstallDisplayName'):
        if meta[key] not in (None, PRODUCT_NAME):
            fail(f'package.json {key}={meta[key]!r}, erwartet {PRODUCT_NAME!r}.')
    for key, value in meta.items():
        if value and brand_ids(str(value)):
            fail(f'Altname gefunden in package.json {key} (Marken-ID {sorted(brand_ids(str(value)))}).')
        if value and any(m in str(value).lower() for m in THIRD_PARTY_MARKERS):
            fail(f'Fremdmarke/Geruesttext in package.json {key}.')

    # Windows-Dateieigenschaften beider EXEs.
    shells = sorted(p for p in unpacked_dir.glob('*.exe') if p.is_file())
    for label, path, description in (('Shell', shells[0], None), ('Backend', exe, f'{PRODUCT_NAME} Backend')):
        info = version_info(path)
        if info.get('ProductName') != PRODUCT_NAME:
            fail(f'{label}-EXE: ProductName={info.get("ProductName")!r}, erwartet {PRODUCT_NAME!r}.')
        if str(info.get('FileVersion') or '').split('+')[0] not in (version, version + '.0'):
            fail(f'{label}-EXE: FileVersion={info.get("FileVersion")!r}, erwartet {version!r}.')
        if description and info.get('FileDescription') != description:
            fail(f'{label}-EXE: FileDescription={info.get("FileDescription")!r}, erwartet {description!r}.')
        for field, value in info.items():
            text = str(value or '')
            if brand_ids(text):
                fail(f'Altname gefunden in Dateieigenschaft {label}-EXE/{field}.')
            if any(m in text.lower() for m in THIRD_PARTY_MARKERS):
                fail(f'Fremdmarke/Geruesttext in Dateieigenschaft {label}-EXE/{field}.')
        log(f'OK EXE-02 Dateieigenschaften {label}-EXE: ProductName={info.get("ProductName")}, '
            f'FileVersion={info.get("FileVersion")}, FileDescription={info.get("FileDescription")!r}')

    # C-EXEPYZ-02: jede Datei des finalen Electron-Pakets mit Name UND Inhalt
    # (Zusatzressourcen, Shell, Framework); Binaerdaten ueber ihre Textabschnitte.
    files = 0
    seen_runs: set[bytes] = set()
    for path in unpacked_dir.rglob('*'):
        rel = str(path.relative_to(unpacked_dir))
        if brand_ids(rel):
            fail(f'Altname gefunden im Dateinamen <win-unpacked>/{"/".join(path.relative_to(unpacked_dir).parts[:-1])}/…')
        if path.is_symlink():
            fail(f'Symlink im Electron-Paket nicht pruefbar: <win-unpacked>/{rel} (fail-closed).')
        if not path.is_file():
            continue
        files += 1
        hits = brand_ids(_binary_text(path.read_bytes(), seen_runs))
        if hits:
            fail(f'Altname gefunden im Inhalt von <win-unpacked>/{rel} (Marken-ID {sorted(hits)}).')
    if not files:
        fail('Electron-Paket ohne Dateien (Zero-Trace-Pruefung nicht moeglich).')
    log(f'OK EXE-02 Electron-Paket: {files} Dateien (Name und Inhalt) ohne Altnamen')

    # app.asar: jede Datei (Inhalt und Pfad).
    asar = unpacked_dir / 'resources' / 'app.asar'
    count = 0
    for path, data in _asar_entries(asar):
        count += 1
        hits = brand_ids(path + '\n' + data.decode('utf-8', errors='replace'))
        if hits:
            fail(f'Altname gefunden in app.asar:{path} (Marken-ID {sorted(hits)}).')
        if path == 'package.json':
            packaged = json.loads(data)
            for field in ('author', 'description', 'productName'):
                if any(m in str(packaged.get(field) or '').lower() for m in THIRD_PARTY_MARKERS):
                    fail(f'Fremdmarke/Geruesttext in app.asar:package.json {field}.')
    log(f'OK EXE-02 app.asar: {count} Dateien ohne Altnamen, Paket-Metadaten ohne Fremdmarke')
    # EXE-09 (H-187): keine Source-Maps im ausgelieferten asar.
    maps = [path for path, _data in _asar_entries(asar) if path.lower().endswith('.map')]
    if maps:
        fail(f'Source-Maps im app.asar ausgeliefert (EXE-09): {maps[:10]}')
    log('OK EXE-09 app.asar ohne Source-Maps')

    # Backend-EXE: Namen aller Eintraege und Text-Dateneintraege.
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    names = list(archive.toc.keys())
    joined = '\n'.join(names)
    if brand_ids(joined):
        fail(f'Altname gefunden in Eintragsnamen der Backend-EXE (Marken-ID {sorted(brand_ids(joined))}).')
    # C-EXEPYZ-01: jeder Eintrag nach Typcode. Code ausserhalb des PYZ wird
    # entpackt und rekursiv geprueft; Daten ueber Inhalt; Unbekanntes sperrt.
    text_entries = code_entries = data_entries = 0
    pyz_names: list[str] = []
    for name, entry in archive.toc.items():
        typecode = entry[-1]
        if typecode in CARCHIVE_CODE_TYPES:
            try:
                code = marshal.loads(archive.extract(name))
            except Exception as exc:  # noqa: BLE001 -- unlesbarer Code ist ein Befund
                fail(f'Ausfuehrbarer CArchive-Eintrag nicht lesbar: {name} (Typ {typecode!r}, {type(exc).__name__}).')
                continue
            if not hasattr(code, 'co_consts'):
                fail(f'Ausfuehrbarer CArchive-Eintrag ist kein Code-Objekt: {name} (Typ {typecode!r}).')
                continue
            code_entries += 1
            hits = brand_ids(_valid_text('\n'.join([name, *_code_strings(code)])))
            if hits:
                fail(f'Altname gefunden im Code-Eintrag der Backend-EXE: {name} (Marken-ID {sorted(hits)}).')
        elif typecode in CARCHIVE_PYZ_TYPES:
            pyz_names.append(name)
        elif typecode in CARCHIVE_DATA_TYPES:
            try:
                data = archive.extract(name) or b''
            except Exception as exc:  # noqa: BLE001 -- unlesbare Daten sind ein Befund
                fail(f'CArchive-Dateneintrag nicht lesbar: {name} (Typ {typecode!r}, {type(exc).__name__}).')
                continue
            data_entries += 1
            if name.replace('\\', '/').lower().endswith(TEXT_ARCHIVE_SUFFIXES):
                text_entries += 1
                # UTF-8 vollstaendig, UTF-16 ueber die Textabschnitte.
                text = data.decode('utf-8', errors='replace') + '/' + _binary_text(data)
            else:
                text = _binary_text(data, seen_runs)
            hits = brand_ids(text)
            if hits:
                fail(f'Altname gefunden in Backend-EXE:{name} (Marken-ID {sorted(hits)}).')
        elif typecode in CARCHIVE_OPTION_TYPES:
            continue
        else:
            fail(f'Unbekannter CArchive-Eintragstyp {typecode!r} in der Backend-EXE: {name} (fail-closed).')
    if not code_entries:
        fail('Backend-EXE: kein ausfuehrbarer Start-Eintrag ausserhalb des PYZ gefunden (Pruefung nicht moeglich).')
    log(f'OK EXE-02 Backend-EXE: {len(names)} Eintragsnamen, {code_entries} Code-Eintraege ausserhalb PYZ, '
        f'{data_entries} Dateneintraege ({text_entries} Text) ohne Altnamen')

    # Zero-Trace: Python-Bytecode im PYZ (String-Konstanten, Namen, Quellpfade).
    modules = 0
    for pyz_name in pyz_names:
        pyz = archive.open_embedded_archive(pyz_name)
        for module in pyz.toc:
            try:
                code = pyz.extract(module)
            except Exception as exc:  # noqa: BLE001 -- jeder unlesbare Eintrag ist ein Befund
                fail(f'PYZ-Eintrag der Backend-EXE nicht lesbar: {module} ({type(exc).__name__}).')
                continue
            if code is None:
                continue
            modules += 1
            hits = brand_ids(_valid_text('\n'.join([module, *_code_strings(code)])))
            if hits:
                fail(f'Altname gefunden im Bytecode der Backend-EXE: {module} (Marken-ID {sorted(hits)}).')
    if not modules:
        fail('Backend-EXE: kein Python-Modul im PYZ gefunden (Zero-Trace-Pruefung nicht moeglich).')
    log(f'OK EXE-02 Backend-EXE: {modules} Python-Module (Bytecode-Konstanten, Namen, Quellpfade) ohne Altnamen')


def _valid_text(text: str) -> str:
    """Konstanten koennen einzelne Surrogate enthalten (z. B. Emoji-Haelften in
    Bibliotheken): vor dem Hashen in gueltiges UTF-8 bringen."""
    return text.encode('utf-8', errors='replace').decode('utf-8')


def _decode_run8(run: bytes) -> str:
    """UTF-8 dekodieren; ein ungueltiges Einzelbyte, das in Latin-1 ein
    normalisierungsrelevantes Zeichen ist (z. B. NBSP), behaelt diese Bedeutung;
    jedes andere wird zum Ersatzzeichen (bricht das Fenster)."""
    text = run.decode('utf-8', errors='surrogateescape')
    return ''.join(_LATIN1_LONE.get(ch, '\ufffd') if '\udc80' <= ch <= '\udcff' else ch for ch in text)


def _binary_text(data: bytes, seen: set[bytes] | None = None) -> str:
    """Alle Textabschnitte einer Binaerdatei (UTF-8 und UTF-16LE), dedupliziert.

    ``seen`` (optional, ueber mehrere Dateien geteilt) ueberspringt Abschnitte,
    die bereits geprueft wurden: gleicher Text, gleiches Ergebnis.
    """
    runs8 = set(_TEXT_RUN_8.findall(data))
    runs16 = set(_TEXT_RUN_16.findall(data))
    if seen is not None:
        runs8 -= seen
        runs16 -= seen
        seen |= runs8
        seen |= runs16
    parts = [_decode_run8(run) for run in runs8]
    parts += [run.decode('utf-16-le', errors='replace') for run in runs16]
    # ``/`` wird nicht normalisiert: kein Fenster ueberspannt zwei Abschnitte.
    return '/'.join(parts)


def _code_strings(code) -> list[str]:
    """Alle Texte eines Code-Objekts samt verschachtelter Code-Objekte und Konstanten."""
    out: list[str] = []
    stack: list = [code]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            out.append(current)
        elif isinstance(current, bytes):
            out.append(current.decode('utf-8', errors='replace'))
        elif isinstance(current, (tuple, frozenset)):
            stack.extend(current)
        elif hasattr(current, 'co_consts'):
            out += [current.co_filename, current.co_name, getattr(current, 'co_qualname', ''),
                    *current.co_names, *current.co_varnames, *current.co_freevars, *current.co_cellvars]
            stack.extend(current.co_consts)
    return out


# ---------------------------------------------------------------------------
# EXE-05 Electron-Shell-Start im isolierten Profil
# ---------------------------------------------------------------------------
def _processes_under(directory: Path) -> list[str]:
    """Laufende Prozesse, deren Programmdatei unter ``directory`` liegt (Win32-API, ohne Shell)."""
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL('psapi')
    kernel32 = ctypes.WinDLL('kernel32')
    kernel32.OpenProcess.restype = wintypes.HANDLE
    pids = (wintypes.DWORD * 8192)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(needed)):
        raise OSError('EnumProcesses fehlgeschlagen')
    prefix = os.path.normcase(str(directory.resolve())) + os.sep
    found: list[str] = []
    for pid in pids[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                if os.path.normcase(buf.value).startswith(prefix):
                    found.append(f'{pid} {Path(buf.value).name}')
        finally:
            kernel32.CloseHandle(handle)
    return found


def run_shell_smoke(unpacked_dir: Path, *, isolated_env, free_port, http_get, port_open, fail, log,
                    timeout: float = 180.0, keep: bool = False) -> None:
    shells = sorted(p for p in unpacked_dir.glob('*.exe') if p.is_file())
    shell = shells[0]
    if _processes_under(unpacked_dir):
        fail(f'Vor dem Shell-Smoke laufen bereits Prozesse aus {unpacked_dir}: {_processes_under(unpacked_dir)}')
    root = Path(tempfile.mkdtemp(prefix='ares-shell-smoke-'))
    port = free_port()
    user_data = root / 'userData'
    proc = None
    try:
        env = isolated_env(root, port, root / 'data' / 'shell.db')
        # Wie ein Benutzerstart: kein erzwungenes APP_ENV/DB-Verschluesselungs-Flag;
        # die Ablageorte (KEK, Datenbankschluessel) setzt die Shell selbst.
        for key in ('APP_ENV', 'DB_USE_SQLCIPHER', 'TENANT_MASTER_KEK_FILE', 'DB_KEY_FILE'):
            env.pop(key, None)
        log(f'Starte Shell {shell.name} isoliert (userData={user_data}, Port {port})')
        proc = subprocess.Popen([str(shell), f'--user-data-dir={user_data}'], cwd=str(root), env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started = time.monotonic()
        ready = None
        while time.monotonic() - started < timeout:
            if proc.poll() is not None:
                fail(f'Shell beendete sich vor Readiness (Exit {proc.returncode}).')
            try:
                status, _, body = http_get(f'http://127.0.0.1:{port}/health/ready', timeout=3)
                if status == 200:
                    ready = json.loads(body)
                    break
            except OSError:
                pass
            time.sleep(1)
        if ready is None:
            fail(f'Shell startete kein bereites Backend auf Port {port} innerhalb {timeout:.0f}s.')
        log(f'OK EXE-05 Shell startet Backend: bereit nach {time.monotonic() - started:.1f}s')
        electron_log = user_data / 'logs' / 'electron.log'
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            text = electron_log.read_text(encoding='utf-8', errors='replace') if electron_log.is_file() else ''
            if 'Main window shown' in text:
                break
            time.sleep(1)
        else:
            fail('Shell: Hauptfenster nicht angezeigt ("Main window shown" fehlt im electron.log).')
        time.sleep(8)  # Intro und erste Requests laufen lassen
        subprocess.run(['taskkill', '/PID', str(proc.pid)], capture_output=True, check=False)  # WM_CLOSE
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            fail('Shell beendet sich nicht auf WM_CLOSE (haengt).')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and (_processes_under(unpacked_dir) or port_open(port)):
            time.sleep(1)
        left = _processes_under(unpacked_dir)
        if left:
            fail(f'Nach dem Beenden laufen noch Prozesse: {left}')
        if port_open(port):
            fail(f'Backend-Port {port} nach dem Beenden weiterhin belegt.')
        text = electron_log.read_text(encoding='utf-8', errors='replace')
        renderer_errors = [line for line in text.splitlines() if 'Renderer error' in line]
        if renderer_errors:
            fail('Renderer-Fehler beim Start:\n' + '\n'.join(renderer_errors[:20]))
        if 'Terminating managed backend process' not in text and 'Backend process exited' not in text:
            fail('Shell hat das Backend beim Beenden nicht sichtbar gestoppt (electron.log).')
        for name in ('tenant-master-kek.dpapi', 'db-key.dpapi'):
            if not (user_data / name).is_file():
                fail(f'Shell: {name} nicht im isolierten userData-Ordner angelegt (Profil-Umlenkung unwirksam?).')
        log('OK EXE-05 Shell: Fenster ohne Renderer-Fehler, WM_CLOSE beendet Shell und Backend, '
            'keine verbleibenden Prozesse, Port frei, userData isoliert')
    finally:
        if proc is not None and proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, check=False)
        for line in _processes_under(unpacked_dir):
            subprocess.run(['taskkill', '/PID', line.split()[0], '/T', '/F'], capture_output=True, check=False)
        if keep:
            log(f'Shell-Temp behalten: {root}')
        else:
            shutil.rmtree(root, ignore_errors=True)
