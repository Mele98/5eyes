# GPT Stage 5 Notes

Diese Runde geht bewusst die Extrameile in Richtung Produktionsreife und Supportfähigkeit.

## Neu ergänzt

1. **Request-/Fehler-Layer im Backend**
   - `core/middleware.py`
   - vergibt `X-Request-ID`
   - setzt Security-Header
   - loggt Dauer pro Request
   - fängt ungehandelte Exceptions zentral ab

2. **Login-Schutz gegen Fehlversuche**
   - `services/login_guard.py`
   - in-memory Lockout nach konfigurierbarer Anzahl Fehlversuche
   - in `routers/auth.py` integriert

3. **Operative Support-Funktionen**
   - rotierende Logfiles im Backend
   - Backup-Manifest mit SHA256
   - neue Endpunkte:
     - `GET /admin/system/backups`
     - `GET /admin/system/logs/recent?lines=120`

4. **Electron robuster**
   - eigener `electron.log`
   - nutzt laufendes Backend wieder, statt blind ein zweites zu starten

## Claude soll besonders prüfen

- ob der Login-Lockout für euren lokalen Use Case passend ist
- ob die Frontend-Fehleranzeige mit `429` sauber genug umgeht
- ob für den finalen Installer UI-Zugriffe auf Backup/Logs gewünscht sind
- ob `electron.log` und Backend-Logs in der Doku für Support klar genug beschrieben sind
