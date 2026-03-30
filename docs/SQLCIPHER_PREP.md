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

```bash
cd 5eyes-backend
python migrate_to_sqlcipher.py --key "dein_starker_schluessel"
```

Danach `.env` setzen und Backend normal starten.
