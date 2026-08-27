# SQLCipher prep

## Aktivierung

In `5eyes-backend/.env`:

```env
DB_USE_SQLCIPHER=true
DB_KEY=dein_starker_schluessel
```

Das Backend schaltet dann zentral im bestehenden `database.py` auf SQLCipher um. Zusätzliche Import-Änderungen in Routern, Services oder Modellen sind nicht mehr nötig.

## Neu für Packaging

Für einen verschlüsselten Windows-Build:

```bat
cd 5eyes-electron
set BUILD_WITH_SQLCIPHER=1
npm run dist:win
```

## Migration bestehender DB

**Gesperrt (SEC-004, Codex-Audit 2026-08-26):** `migrate_to_sqlcipher.py` hat
nachgewiesene Sicherheits- und Korrektheitsluecken (Schluessel sichtbar in
Prozessliste/Stdout, hinterlaesst ein Klartext-Backup neben der DB, kann
Trigger wie die Audit-Log-Unveraenderlichkeit lautlos verlieren durch falsche
Schema-Erstellungsreihenfolge, unzureichende Erfolgspruefung). Es ist **kein**
produktiver Migrationspfad, bis ein sicherer Ersatz existiert -- siehe
Modul-Docstring der Datei fuer die Details.

Fuer eine NEUE Datenbank direkt mit SQLCipher starten (kein Migrationsschritt
noetig): einfach `DB_USE_SQLCIPHER=true` + `DB_KEY=...` VOR dem ersten Start
setzen, `database.py` legt das Schema dann direkt verschluesselt an.
