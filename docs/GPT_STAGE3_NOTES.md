# GPT Stage 3 notes

## Was in dieser Runde zusätzlich verbessert wurde

- **SQLCipher zentralisiert**: `database.py` schaltet jetzt selbst auf SQLCipher um, sobald `DB_USE_SQLCIPHER=true` und `DB_KEY=...` gesetzt sind. Dadurch müssen Router, Services und Modelle nicht mehr auf ein anderes Modul umgebaut werden.
- **Packaged `.env`-Suche ergänzt**: Das Backend sucht in einem packaged Build zuerst neben der EXE nach `.env`.
- **`setup.py` und `migrate_to_sqlcipher.py` bereinigt**: können nun direkt mit dem zentralen DB-Modul arbeiten.
- **Electron-Scripts korrigiert**: `npm start` ist jetzt vorhanden. Vorher war nur `npm run dev` definiert, obwohl die Setup-Anleitung `npm start` sagte.
- **Build-Script erweitert**: PyInstaller-Kopie umfasst jetzt zusätzlich `.env`, `.env.example` und optional SQLCipher via `BUILD_WITH_SQLCIPHER=1`.

## Wichtigster Punkt für Claude

Die frühere Idee "in `main.py` einfach einen Import austauschen" hätte nicht gereicht, weil im Code an vielen Stellen direkt `from database import ...` verwendet wird. Das ist jetzt sauber abgefangen.

## Noch offen

- `vendor_assets.py` wurde hier nicht wirklich online ausgeführt. Das HTML enthält im ZIP weiterhin CDN-Referenzen, bis das Script einmal mit Internetzugang gelaufen ist.
- Kein echter Windows-Build und kein echter SQLCipher-Lauf wurden in dieser Umgebung ausgeführt.
- App-Icon, Code-Signing, Notarisierung und Auto-Update sind weiterhin nicht Teil dieses Pakets.
