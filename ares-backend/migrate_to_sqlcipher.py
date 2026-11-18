#!/usr/bin/env python3
"""Ehemaliges Werkzeug SQLite -> SQLCipher. STILLGELEGT.

SEC-004 (Codex-Audit 2026-08-26) hatte das Tool gesperrt (Schluessel in
argv/stdout, Klartext-Kopie neben der DB, stille Trigger-Verluste durch
falsche Schema-Reihenfolge, unzureichende Erfolgspruefung). Der Bypass ueber
``--i-understand-this-tool-is-broken-and-unsafe`` legte trotzdem zuerst eine
vollstaendige Klartext-Kopie an und scheiterte danach an ``PRAGMA key = ?``
(Pruefrunde #864, S-3).

Seit S-3 gibt es keinen Bypass mehr: das Skript liest weder Konfiguration noch
Datenbank, legt keine Datei an und endet immer mit Exit-Code 1. Der Ersatz ist
der Ares-Migrator (separates Repository ``ares-migrator``), der Klartext- und
SQLCipher-Quellen mit Vollstaendigkeitspruefung behandelt. Siehe
docs/SQLCIPHER_PREP.md.
"""
import sys

LOCKED_MESSAGE = (
    'Dieses Werkzeug ist stillgelegt (SEC-004, Pruefrunde #864 S-3) und fuehrt '
    'keine Migration mehr aus.\n'
    'Es wurde nichts gelesen, kopiert oder veraendert.\n'
    'Fuer die Migration den Ares-Migrator (Repository ares-migrator) verwenden; '
    'siehe docs/SQLCIPHER_PREP.md.'
)


def main(argv: list[str] | None = None) -> int:
    _ = argv  # Argumente werden bewusst ignoriert: es gibt keinen Bypass.
    print(LOCKED_MESSAGE)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
