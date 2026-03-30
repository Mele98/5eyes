# GPT Stage 4 Notes

Zusätzlich umgesetzt:

1. Sichere Token-Speicherung im Electron-Wrapper
   - Token läuft in Electron über `safeStorage`, sofern auf dem System verfügbar.
   - Fallback bleibt `localStorage`, wenn nur die HTML-Datei im Browser geöffnet wird.

2. Persistente Logfiles
   - Logs laufen nun zusätzlich in `<DB-Verzeichnis>/logs/5eyes-app.log`.

3. Lokale System-/DB-Wartungsendpunkte
   - `GET /admin/system/paths`
   - `GET /admin/system/db/integrity`
   - `POST /admin/system/db/backup`
   - `POST /admin/system/db/optimize`

Empfehlung für Claude-Review:
- Prüfen, ob Frontend noch irgendwo direkt auf `localStorage` für Auth zugreift.
- Prüfen, ob im finalen Installer ein dediziertes User-Data-Verzeichnis dokumentiert werden soll.
- Prüfen, ob für die DB-Backups ein UI-Button sinnvoll ist.
