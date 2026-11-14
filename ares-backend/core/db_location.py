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


def normalize_db_target(path: str | os.PathLike[str]) -> Path:
    """EINE Normalisierung fuer alle Owner-/Live-DB-Pruefpunkte (H11 N-907-01):
    ``file:``-URI aufloesen, ``~``, Datenstroeme und Punkt/Leerzeichen am Ende,
    dann ``os.path.abspath`` + ``realpath`` (Junctions/Symlinks)."""
    raw = os.fspath(path)
    raw = str(raw).strip() if isinstance(raw, str) else os.fsdecode(raw)
    if raw.lower().startswith('file:'):
        raw = _file_uri_path(raw)
    raw = _windows_clean(os.path.expanduser(raw))
    absolute = os.path.abspath(raw)
    try:
        return Path(os.path.realpath(absolute))
    except (OSError, RuntimeError, ValueError):
        return Path(absolute)


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
    try:
        return os.path.samefile(cand_path, live_path)
    except OSError:
        # Mindestens eine Seite existiert nicht: dann kann es auch kein
        # Alias derselben Datei sein (der Namensvergleich oben greift).
        return False


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


def owner_db_refusal(candidate: str | os.PathLike[str] | None, environ) -> str | None:
    """Begruendung, warum ``candidate`` nicht geoeffnet werden darf, sonst ``None``."""
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


_ATTACH = re.compile(r"\bATTACH\s+(?:DATABASE\s+)?(?:'((?:[^']|'')*)'|\"([^\"]*)\")", re.IGNORECASE)


def attach_targets(statement: str, parameters=None) -> list[str]:
    """Dateiziele eines ``ATTACH``-Statements (Literal oder gebundener Parameter)."""
    if not statement or 'attach' not in statement.lower():
        return []
    out = [(m.group(1) or '').replace("''", "'") or m.group(2) for m in _ATTACH.finditer(statement)]
    if re.search(r'\bATTACH\s+(?:DATABASE\s+)?[?:]', statement, re.IGNORECASE) and parameters:
        values = parameters.values() if isinstance(parameters, dict) else parameters
        out += [v for v in values if isinstance(v, str)]
    return [t for t in out if t]


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
