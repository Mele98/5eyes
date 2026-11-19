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

Kommandozeile (fuer PowerShell-Deploy-Skripte)::

    python core/db_location.py live-path        # gibt den Produktivpfad aus
    python core/db_location.py check <pfad>     # Exit 3 = Produktivpfad, 0 = nicht
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LIVE_DB_EXIT_CODE = 3


def default_db_path() -> Path:
    """Default-Datenpfad der produktiven Instanz (Quelle fuer ``config``)."""
    return Path.home() / 'ares' / 'ares.db'


def _normalize(path: str | os.PathLike[str]) -> Path:
    candidate = Path(os.fspath(path)).expanduser()
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(os.path.abspath(candidate))


def sqlite_url_file(database_url: str | None) -> Path | None:
    """Dateipfad einer ``sqlite:///...``-URL (sonst ``None``)."""
    if not database_url:
        return None
    raw = str(database_url).strip()
    if not raw.lower().startswith('sqlite'):
        return None
    _, sep, rest = raw.partition(':///')
    if not sep:
        return None
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
