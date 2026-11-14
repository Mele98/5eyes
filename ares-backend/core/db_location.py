"""Produktiver Datenbankpfad -- eine Quelle -- und Waechter dagegen.

``default_db_path()`` ist die EINZIGE Stelle, die den Default-Datenpfad der
Desktop-/Server-Instanz kennt. ``config.Settings.db_path`` bezieht seinen
Default von hier, und alle Live-DB-Waechter (Test-Session, Analyse-Tools,
Deploy-Skripte) vergleichen gegen genau diese Funktion statt gegen ein
eigenes Pfad-Literal. Wird der Datenpfad umbenannt, wandern die Waechter
automatisch mit (Vorfall 2026-10-15: Tests liefen gegen die Live-DB).

Der Vergleich ist robust gegen Alternativschreibweisen: ``~``, relative
Pfade, ``..``-Segmente, Symlinks/Junctions (``resolve``), Gross-/Klein-
schreibung auf Windows (``normcase``) und Hardlinks bzw. sonstige Aliase
derselben Datei (``os.path.samefile`` ueber ``stat``; die Datei wird dabei
nie geoeffnet).

Nur Standardbibliothek und keine Import-Seiteneffekte: ``tests/conftest.py``
importiert dieses Modul, BEVOR ``config`` seine Settings baut.

H11 Nachtrag 1 (Vorfall 2026-11-14, ``~/ares/ares.db`` leer neu angelegt):
``owner_db_refusal`` ist die (reine) Regel; ``config`` wendet sie an: VOR
jedem SQLite-Connect (``Engine.do_connect``), im App-Start vor Logging/KEK/DB,
im Schema-Bootstrap (raw sqlite3) und in ``alembic/env.py``. Owner-Pfade sind
``~/ares/ares.db`` und ``~/5eyes/5eyes.db``. Verweigert wird
* immer unter pytest/CI/Testmodus (auch mit Opt-in),
* sonst ohne ausdrueckliche Freigabe ``ARES_OWNER_DB_OPT_IN=1``. Die setzen
  die Desktop-Shell beim Backend-Start und der Umstieg (Migrator/Runbook).

Kommandozeile (fuer PowerShell-Deploy-Skripte)::

    python core/db_location.py live-path        # gibt den Produktivpfad aus
    python core/db_location.py check <pfad>     # Exit 3 = Produktivpfad, 0 = nicht
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

LIVE_DB_EXIT_CODE = 3


def default_db_path() -> Path:
    """Default-Datenpfad der produktiven Instanz (Quelle fuer ``config``)."""
    return Path.home() / 'ares' / 'ares.db'


_DRIVE = re.compile(r'^[A-Za-z]:')


def _file_uri_path(raw: str) -> str:
    """``file:``-URI (SQLite ``uri=true``) -> Dateipfad: ``file:C:/x``,
    ``file:///C:/x``, ``file://localhost/C:/x``, Prozent-Kodierung, ohne
    ``?mode=...``. Fremde Hosts bleiben unveraendert (kein lokaler Pfad)."""
    parts = urlsplit(raw)
    if parts.netloc.lower() not in ('', 'localhost'):
        return raw
    path = unquote(parts.path)
    if re.match(r'^/[A-Za-z]:', path):
        path = path[1:]
    return path


def _windows_clean(path: str) -> str:
    """Windows-Semantik beim Oeffnen nachbilden: NTFS-Datenstroeme
    (``name:stream:$DATA``) abschneiden, Punkt/Leerzeichen am Ende jedes
    Namensteils entfernen. Auf allen Plattformen (fail-closed)."""
    drive = _DRIVE.match(path)
    head = path[:2] if drive else ''
    rest = path[2:] if drive else path
    parts = []
    for comp in re.split(r'([\\/])', rest):
        if comp in ('/', '\\', '', '.', '..'):
            parts.append(comp)
            continue
        comp = comp.split(':', 1)[0].rstrip(' .')
        parts.append(comp)
    return head + ''.join(parts)


_DEVICE_PREFIXES = ('\\\\?\\UNC\\', '\\\\?\\', '\\\\.\\', '//?/UNC/', '//?/', '//./')
_LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1', '[::1]', '.'}


def _local_host_names() -> set[str]:
    names = set(_LOCAL_HOSTS)
    try:
        import socket

        host = socket.gethostname()
        names |= {host.casefold(), host.split('.')[0].casefold(), socket.getfqdn().casefold()}
    except OSError:
        pass
    return names


def _strip_device_and_admin_share(raw: str) -> str:
    """N-907-11: Win32-Geraete-Namensraum (``\\\\?\\``, ``\\\\.\\``,
    ``\\\\?\\UNC\\``) abschneiden und UNC-Admin-Freigaben des eigenen
    Rechners (``\\\\localhost\\C$\\...``, ``127.0.0.1``, Rechnername) auf den
    lokalen Laufwerkspfad zurueckfuehren."""
    for prefix in _DEVICE_PREFIXES:
        if raw[:len(prefix)].upper() == prefix.upper():
            raw = ('\\\\' + raw[len(prefix):]) if 'UNC' in prefix.upper() else raw[len(prefix):]
            break
    m = re.match(r'^[\\/]{2}([^\\/]+)[\\/]([A-Za-z])\$(?:[\\/](.*))?$', raw)
    if m and m.group(1).casefold() in _local_host_names():
        raw = f'{m.group(2)}:\\' + (m.group(3) or '')
    return raw


def normalize_db_target(path: str | os.PathLike[str]) -> Path:
    """EINE Normalisierung fuer alle Owner-/Live-DB-Pruefpunkte (H11 N-907-01/-11):
    Geraete-Praefixe und lokale Admin-Freigaben, ``file:``-URI, ``~``,
    Datenstroeme und Punkt/Leerzeichen am Ende, dann ``os.path.abspath`` +
    ``realpath`` (Junctions/Symlinks/8.3)."""
    raw = os.fspath(path)
    raw = str(raw).strip() if isinstance(raw, str) else os.fsdecode(raw)
    raw = _strip_device_and_admin_share(raw)
    if raw.lower().startswith('file:'):
        raw = _strip_device_and_admin_share(_file_uri_path(raw))
    raw = _windows_clean(os.path.expanduser(raw))
    absolute = os.path.abspath(raw)
    try:
        return Path(os.path.realpath(absolute))
    except (OSError, RuntimeError, ValueError):
        return Path(absolute)


def _same_identity(cand: Path, live: Path) -> bool:
    """N-907-11: Identitaet statt Pfadtext -- dieselbe Datei (``samefile``)
    oder derselbe EXISTIERENDE Elternordner (st_dev + st_ino; unter Windows
    Volume-Seriennummer + File-ID) und derselbe Dateiname (casefold)."""
    try:
        if os.path.samefile(cand, live):
            return True
    except OSError:
        pass
    if cand.name.casefold() != live.name.casefold():
        return False
    try:
        a, b = os.stat(cand.parent), os.stat(live.parent)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) and a.st_ino != 0


def _normalize(path: str | os.PathLike[str]) -> Path:
    return normalize_db_target(path)


def sqlite_url_file(database_url: str | None) -> Path | None:
    """Dateipfad einer ``sqlite:///...``-URL (sonst ``None``), auch
    ``sqlite:///file:...?...&uri=true``."""
    if not database_url:
        return None
    raw = str(database_url).strip()
    if not raw.lower().startswith('sqlite'):
        return None
    _, sep, rest = raw.partition(':///')
    if not sep:
        return None
    if rest.lower().startswith('file:'):
        target = _file_uri_path(rest)
        return Path(target) if target and target != ':memory:' else None
    rest = rest.split('?', 1)[0]
    if not rest or rest == ':memory:':
        return None
    return Path(rest)


def is_live_db_path(
    candidate: str | os.PathLike[str] | None,
    live: str | os.PathLike[str] | None = None,
) -> bool:
    """True, wenn ``candidate`` dieselbe Datei wie der Produktivpfad bezeichnet."""
    if candidate is None or not str(os.fspath(candidate)).strip():
        return False
    live_path = _normalize(live if live is not None else default_db_path())
    cand_path = _normalize(candidate)
    if os.path.normcase(str(cand_path)) == os.path.normcase(str(live_path)):
        return True
    return _same_identity(cand_path, live_path)


def refuse_live_db(candidate: str | os.PathLike[str] | None, *, context: str) -> None:
    """Bricht mit ``SystemExit`` ab, wenn ``candidate`` der Produktivpfad ist."""
    if is_live_db_path(candidate):
        raise SystemExit(
            f'{context}: DB_PATH zeigt auf die produktive Datenbank '
            f'({default_db_path()}) -- abgebrochen.'
        )


OWNER_DB_OPT_IN_ENV = 'ARES_OWNER_DB_OPT_IN'
_TRUE = {'1', 'true', 'yes', 'on'}


class OwnerDatabaseRefused(RuntimeError):
    """Start/Anlegen einer DB unter dem Owner-Pfad verweigert (fail-closed)."""


def owner_db_paths() -> tuple[Path, ...]:
    """Owner-Datenbanken: Ares-Produktivpfad und die Alt-Live-DB."""
    return (default_db_path(), Path.home() / '5eyes' / '5eyes.db')


def is_owner_db_path(candidate: str | os.PathLike[str] | None) -> bool:
    return any(is_live_db_path(candidate, live) for live in owner_db_paths())


def test_or_ci_mode(environ) -> str | None:
    """Kennung des Test-/CI-Kontexts (pytest, CI, Testmodus) oder ``None``.
    ``environ`` reicht der Aufrufer herein (nur ``config`` liest die Umgebung)."""
    if 'pytest' in sys.modules or environ.get('PYTEST_CURRENT_TEST') or environ.get('PYTEST_XDIST_WORKER'):
        return 'pytest'
    if str(environ.get('CI', '')).strip().lower() in _TRUE or str(environ.get('GITHUB_ACTIONS', '')).strip().lower() in _TRUE:
        return 'CI'
    test_flags = (str(environ.get('ARES_TEST_MODE', '')).strip().lower() in _TRUE,
                  str(environ.get('ARES_TEST', '')).strip() == '1',
                  str(environ.get('NODE_ENV', '')).strip().lower() == 'test')
    if any(test_flags):
        return 'Testmodus'
    return None


_DEVICE_HEAD = re.compile(r'^[\\/]{2}[?.][\\/]')
_DEVICE_EMBEDDED = re.compile(r'[\\/][\\/]{2}[?.][\\/]')
_KNOWN_DEVICE_TAIL = re.compile(r'^(?:[A-Za-z]:(?:[\\/]|$)|UNC[\\/])', re.IGNORECASE)


def is_unresolvable_device_path(candidate) -> bool:
    """N-907-16: Win32-Geraete-Pfad (``\\\\?\\...``/``\\\\.\\...``), der sich NICHT auf
    die bekannten Formen (Laufwerk ``C:\\``, ``UNC\\``) zurueckfuehren laesst --
    z. B. ``\\\\?\\GLOBALROOT\\??\\C:\\``, ``\\\\?\\Volume{...}\\``,
    ``\\\\.\\HarddiskVolumeN\\``. Solche Ziele sind nicht pruefbar."""
    if candidate is None:
        return False
    raw = str(os.fspath(candidate)).strip()
    if raw.lower().startswith('file:'):
        raw = _file_uri_path(raw)
    if _DEVICE_HEAD.match(raw):
        return not _KNOWN_DEVICE_TAIL.match(raw[4:])
    # Eingebettet (z. B. nach os.path.abspath eines relativen Geraete-Pfads unter
    # POSIX: ``/cwd/\\\\?\\GLOBALROOT...``): nie pruefbar -> fail-closed.
    return _DEVICE_EMBEDDED.search(raw) is not None


def owner_db_refusal(candidate: str | os.PathLike[str] | None, environ) -> str | None:
    """Begruendung, warum ``candidate`` nicht geoeffnet werden darf, sonst ``None``."""
    if is_unresolvable_device_path(candidate):
        return (f'Geraete-Pfad {candidate} ist nicht auf einen pruefbaren Dateipfad '
                'zurueckfuehrbar -- verweigert (fail-closed).')
    if not is_owner_db_path(candidate):
        return None
    mode = test_or_ci_mode(environ)
    if mode:
        return (f'{mode}: Die Owner-Datenbank {candidate} wird nie geoeffnet oder angelegt '
                '(DB_PATH/HOME isolieren).')
    if str(environ.get(OWNER_DB_OPT_IN_ENV, '')).strip().lower() not in _TRUE:
        return (f'Start auf der Owner-Datenbank {candidate} ohne Freigabe {OWNER_DB_OPT_IN_ENV}=1 '
                'verweigert (setzt die Desktop-Shell bzw. der Umstieg; sonst DB_PATH setzen).')
    return None


def connect_target(cargs, cparams) -> str | None:
    """Ziel eines SQLite-DBAPI-Connects (``do_connect``-Argumente), roh --
    die Normalisierung (auch ``file:``-URIs) macht ``normalize_db_target``."""
    raw = cparams.get('database') if cparams else None
    if raw is None and cargs:
        raw = cargs[0]
    raw = str(raw or '').strip()
    if not raw or raw == ':memory:' or raw.lower().startswith('file::memory:'):
        return None
    return raw


SQLITE_ATTACH = 24
SQLITE_OK = 0
SQLITE_DENY = 1


def attach_decision(target: str | None, environ) -> int:
    """N-907-12: Entscheid des SQLite-Authorizers fuer ``SQLITE_ATTACH``.
    SQLite meldet das Ziel nur bei einem Literal; ist es nicht aufloesbar
    (Ausdruck, ``||``, Parameter) wird verweigert -- Ares nutzt ATTACH nicht."""
    if target is None:
        return SQLITE_DENY
    if target in ('', ':memory:') or str(target).lower().startswith('file::memory:'):
        return SQLITE_OK
    return SQLITE_DENY if owner_db_refusal(target, environ) else SQLITE_OK


def _main(argv: list[str]) -> int:
    if argv[:1] == ['live-path'] and len(argv) == 1:
        print(default_db_path())
        return 0
    if argv[:1] == ['check'] and len(argv) == 2:
        return LIVE_DB_EXIT_CODE if is_live_db_path(argv[1]) else 0
    print('Aufruf: db_location.py live-path | check <pfad>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(_main(sys.argv[1:]))
