# SQLCipher prep

## Aktivierung

In `ares-backend/.env`:

```env
DB_USE_SQLCIPHER=true
DB_KEY=<64 Hex-Zeichen, z. B. python -c "import secrets;print(secrets.token_hex(32))">
```

`DB_KEY` muss 32-512 Zeichen aus `A-Z a-z 0-9 . _ ~ -` haben, sonst startet das
Backend nicht (fail-closed, die Meldung nennt den Schluessel nicht).

Das Backend schaltet dann zentral im bestehenden `database.py` auf SQLCipher um. Zusätzliche Import-Änderungen in Routern, Services oder Modellen sind nicht mehr nötig.

## Neu für Packaging

Für einen verschlüsselten Windows-Build:

```bat
cd ares-backend
pip install --require-hashes --only-binary=:all: -r requirements-sqlcipher.txt
cd ..\ares-desktop
set BUILD_WITH_SQLCIPHER=1
npm run dist:win
```

## Migration bestehender DB

**Stillgelegt (SEC-004, Pruefrunde #864 S-3):** `migrate_to_sqlcipher.py` fuehrt
keine Migration mehr aus und endet immer mit Exit-Code 1 (kein Bypass-Flag mehr;
der fruehere Bypass legte eine Klartext-Kopie an und scheiterte danach).
Migrationen laufen ueber den Ares-Migrator (Repository `ares-migrator`).

Fuer eine NEUE Datenbank direkt mit SQLCipher starten (kein Migrationsschritt
noetig): einfach `DB_USE_SQLCIPHER=true` + `DB_KEY=...` VOR dem ersten Start
setzen, `database.py` legt das Schema dann direkt verschluesselt an.
