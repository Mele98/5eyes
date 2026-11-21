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
import os
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
MIN_OWN_MODULES = 300
TEXT_ARCHIVE_SUFFIXES = ('.json', '.yaml', '.yml', '.sql', '.html', '.txt', '.md', '.css', '.js')


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


def assert_no_degraded_modules(logtext: str, fail) -> None:
    if 'not importable' in logtext:
        fail('Backend-Log meldet ein nicht importierbares Modul ("not importable").')


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
_PS_VERSION = ("$v=(Get-Item -LiteralPath $env:ARES_PE).VersionInfo; "
               "[pscustomobject]@{ProductName=$v.ProductName;FileDescription=$v.FileDescription;"
               "CompanyName=$v.CompanyName;LegalCopyright=$v.LegalCopyright;FileVersion=$v.FileVersion;"
               "ProductVersion=$v.ProductVersion;InternalName=$v.InternalName;"
               "OriginalFilename=$v.OriginalFilename;Comments=$v.Comments} | ConvertTo-Json -Compress")


def version_info(path: Path) -> dict:
    env = dict(os.environ, ARES_PE=str(path))
    out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', _PS_VERSION],
                         capture_output=True, text=True, env=env, timeout=60)
    return json.loads(out.stdout or '{}')


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

    # Dateinamen unter resources und im Shell-Verzeichnis.
    for path in unpacked_dir.rglob('*'):
        rel = str(path.relative_to(unpacked_dir))
        if brand_ids(rel):
            fail(f'Altname gefunden im Dateinamen <win-unpacked>/{"/".join(path.relative_to(unpacked_dir).parts[:-1])}/…')

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

    # Backend-EXE: Namen aller Eintraege und Text-Dateneintraege.
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    names = list(archive.toc.keys())
    joined = '\n'.join(names)
    if brand_ids(joined):
        fail(f'Altname gefunden in Eintragsnamen der Backend-EXE (Marken-ID {sorted(brand_ids(joined))}).')
    text_entries = 0
    for name in names:
        if name.replace('\\', '/').lower().endswith(TEXT_ARCHIVE_SUFFIXES):
            data = archive.extract(name)
            if data is None:
                continue
            text_entries += 1
            hits = brand_ids(data.decode('utf-8', errors='replace'))
            if hits:
                fail(f'Altname gefunden in Backend-EXE:{name} (Marken-ID {sorted(hits)}).')
    log(f'OK EXE-02 Backend-EXE: {len(names)} Eintragsnamen und {text_entries} Text-Dateneintraege ohne Altnamen')


# ---------------------------------------------------------------------------
# EXE-05 Electron-Shell-Start im isolierten Profil
# ---------------------------------------------------------------------------
def _processes_under(directory: Path) -> list[str]:
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
              "$_.ExecutablePath.StartsWith($env:ARES_DIR, [System.StringComparison]::OrdinalIgnoreCase) } | "
              "ForEach-Object { \"$($_.ProcessId) $($_.Name)\" }")
    env = dict(os.environ, ARES_DIR=str(directory))
    out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                         capture_output=True, text=True, env=env, timeout=60)
    return [line for line in out.stdout.splitlines() if line.strip()]


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
        # Wie ein Benutzerstart: kein erzwungenes APP_ENV/DB-Verschluesselungs-Flag.
        for key in ('APP_ENV', 'DB_USE_SQLCIPHER', 'TENANT_MASTER_KEK_FILE'):
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
        for name in ('tenant-master-kek.dpapi',):
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
