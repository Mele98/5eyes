# 5eyes — DB-Backup-Strategie

> Roadmap-Punkt 8 (2026-05-30): SQLite-Online-Backup via `sqlite3.Connection.backup()`,
> atomar + WAL-aware, kein Server-Stop notwendig.

---

## Architektur (One-Pager)

```
                       /------- APScheduler (taeglich 03:00 lokal)
                      /
services/backup.py --+------- scripts/backup_now.py (CLI, on-demand)
        |             \
        |              \------ Future: HTTP-Endpoint /admin/backup/run (optional)
        v
sqlite3.Connection.backup()  ---> atomic WAL-aware copy
        |
        v
{backup_dir}/5eyes-backup-YYYYMMDD-HHMMSS.db
            + 5eyes-backup-YYYYMMDD-HHMMSS.db.sha256  (Integritaets-Sidecar)
        |
        v
Retention: aelter als backup_retain_days -> geloescht
           ausser die top-N (backup_keep_minimum) bleiben immer erhalten
```

---

## Konfiguration

Alle Settings in `config.py` (per `.env` ueberschreibbar):

| Setting | Default | Bedeutung |
|---|---|---|
| `backup_enabled` | `true` | Master-Schalter |
| `backup_dir` | `~/5eyes/backups` | Zielverzeichnis. **In Production auf separates Volume zeigen.** |
| `backup_retain_days` | `30` | Backups aelter werden geloescht. `0` = nie aufraeumen. |
| `backup_keep_minimum` | `3` | Mindestens N neueste bleiben immer erhalten (Katastrophen-Schutz). |
| `backup_scheduler_enabled` | `true` | Daily-Cron an/aus |
| `backup_scheduler_timezone` | `Europe/Zurich` | Zeitzone fuer den Cron |
| `backup_scheduler_hour` | `3` | 0-23 |
| `backup_scheduler_minute` | `0` | 0-59 |

### Beispiel `.env`

```bash
# Production: Backups auf eingehaengte externe Platte
BACKUP_DIR=/mnt/backup-volume/5eyes
BACKUP_RETAIN_DAYS=90
BACKUP_KEEP_MINIMUM=7
BACKUP_SCHEDULER_HOUR=2
BACKUP_SCHEDULER_MINUTE=30
```

---

## On-Demand-Backup (CLI)

Vor jeder Migration / vor jedem Major-Update:

```bash
cd 5eyes-backend
python scripts/backup_now.py
# -> BACKUP ok -> ~/5eyes/backups/5eyes-backup-20260530-081920.db
#    (1638400 bytes, sha256=64ec6f2a..., retained=1, pruned=0)
```

Mit explizitem Ziel:

```bash
python scripts/backup_now.py --target D:/secure-backups
```

Backup-Datei in einer anderen DB testen:

```bash
python scripts/backup_now.py --source ~/5eyes/5eyes.db --target /tmp/proben
```

---

## Restore

**Wichtig: Backend-Server vorher stoppen.** Schreibender Zugriff auf die
Ziel-DB waehrend des Restores wuerde die Konsistenz verletzen.

```bash
# Backend stoppen (Strg+C im uvicorn-Terminal, oder Electron-App schliessen)

cd 5eyes-backend
python scripts/backup_now.py \
    --restore ~/5eyes/backups/5eyes-backup-20260530-081920.db \
    --target  ~/5eyes/5eyes.db
# -> RESTORE ok -> ~/5eyes/5eyes.db (1638400 bytes, hash_verified=True)

# Backend wieder starten
uvicorn main:app --port 8000
```

Das Restore prueft per Default den SHA256-Sidecar gegen das Backup-File
und wirft einen `ValueError`, wenn etwas manipuliert wurde. Wenn der
Sidecar fehlt (z.B. manuelle Backup-Kopie), wird verifikationslos
restored. Mit `--no-verify-hash` ist die Pruefung explizit aus.

---

## Was bei laufendem Server passiert

Die `sqlite3.Connection.backup()`-API ist **WAL-aware**:

- Source-DB wird URI-mode read-only geoeffnet (`?mode=ro`)
- Schreibende Transaktionen anderer Verbindungen koennen WEITERLAUFEN
- Das Backup sieht einen konsistenten Snapshot zum Zeitpunkt-T des
  Backup-Beginns; spaetere Writes landen NICHT im Backup
- WAL-Journal wird mit-konsolidiert

Verifiziert durch `tests/test_backup.py::test_backup_works_with_concurrent_write_connection`.

---

## SQLCipher (verschluesselte DBs)

Wenn `db_use_sqlcipher=true` aktiv ist:

- Das Backup-File wird mit **demselben Key** verschluesselt wie das Original
- Der `sqlite3.Connection.backup()`-Aufruf kopiert die Bytes 1:1
- Restore funktioniert ohne Sonderbehandlung
- **Key-Rotation** erfordert ein separates Re-Encrypt-Verfahren (out-of-scope U-8)

---

## Was passiert wenn ein Backup fehlschlaegt

Im Scheduler-Pfad (`backup_scheduler._run_backup_job`):

- Exception wird ge`logger.exception()`et → landet in `electron.log` /
  Backend-Log
- Der Scheduler bleibt aktiv — naechster Lauf am naechsten Tag
- KEIN Crash des Backend-Servers

Im CLI-Pfad:

- Exception bubbled hoch -> Process exit != 0
- Der Berater sieht den Trace auf der Konsole

---

## Was U-8 NICHT abdeckt (Folge-Punkte)

| Feature | Status | Roadmap |
|---|---|---|
| Off-Site-Backup (S3/Azure) | manuell | offen — Punkt zur Aufnahme |
| Backup-Verschluesselung der Bytes (jenseits SQLCipher) | nicht implementiert | sinnvoll wenn `backup_dir` shared volume |
| Backup-Monitoring / Alert wenn ausgefallen | nur Log | siehe Punkt 64 (Telemetrie/Sentry) |
| GFS-Retention (Grandfather-Father-Son) | nicht implementiert | "retain_days + keep_minimum" reichen fuer V1 |
| Point-in-Time-Recovery via WAL-Replay | nicht implementiert | SQLite ist ein File-DB, kein Replication-Log |
| HTTP-Endpoint `/admin/backup/run` | nicht implementiert | Berater nutzt CLI + Scheduler |
| Restore-Endpoint via HTTP | bewusst nicht | Restore erfordert Server-Stop, also Out-of-Band |

---

## Test-Coverage

10 pytest-Cases in `tests/test_backup.py`, alle gruen (2026-05-30):

| Test | Verifiziert |
|---|---|
| `test_backup_creates_file_and_sidecar` | File + Sidecar entstehen, Filename-Pattern, Hash im Sidecar |
| `test_backup_restore_roundtrip_preserves_data` | Inhalt + Row-Count + Checksum 1:1 |
| `test_backup_works_with_concurrent_write_connection` | Live-Smoke: uncommitted Write ist NICHT im Backup |
| `test_retention_prunes_old_backups_but_keeps_minimum` | retain_days entfernt alte, keep_minimum schuetzt |
| `test_retention_zero_means_never_prune` | retain_days=0 = no-op |
| `test_backup_fails_when_source_missing` | Klarer `FileNotFoundError` |
| `test_restore_verifies_hash_and_rejects_tampered_backup` | SHA256-Mismatch -> `ValueError` |
| `test_restore_skips_hash_when_requested` | `verify_hash=False` Pfad |
| `test_list_backups_returns_newest_first` | Sort-Reihenfolge stabil |
| `test_list_backups_returns_empty_for_missing_dir` | Defensive |

**Live-Roundtrip:** `python scripts/backup_now.py` gegen die produktive
DB des laufenden Backends erzeugte ein 1.6 MB Backup mit gueltigem
SHA256-Sidecar, kein Konflikt mit dem aktiven Server.
