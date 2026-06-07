# Tier 1: Self-Hosted Deployment-Recipe

**Wer:** Berater mit eigener IT-Infrastruktur, hoechste Compliance
**Hardware:** Berater-eigener PC / NAS / Home-Server
**Compliance:** FINMA-konform (kein Outsourcing), revDSG-konform
**Setup-Aufwand:** 1-2 Stunden

---

## Architektur

```
+---------------------+
| Berater-Hardware    |
|                     |
|  +---------------+  |
|  | Backend       |  |
|  | (FastAPI)     |  |
|  | localhost:8000|  |
|  +-------+-------+  |
|          |          |
|  +-------v-------+  |
|  | SQLite +      |  |
|  | SQLCipher     |  |
|  | (.sqlite-Datei)| |
|  +---------------+  |
|                     |
|  +---------------+  |
|  | Electron App  |  |
|  | (Frontend)    |  |
|  +---------------+  |
+---------------------+

Keine externen Verbindungen (ausser Markt-Daten-Updates via Cron).
```

---

## Setup

### 1. Backend-Konfiguration

```dotenv
# 5eyes-backend/.env
DEPLOYMENT_TIER=tier1
APP_ENV=production
APP_HOST=127.0.0.1
APP_PORT=8000

# DB-Verschluesselung
DB_USE_SQLCIPHER=true
DB_KEY=<32-byte-hex-key-aus-secrets-manager>
DB_PATH=C:\5eyes-data\production.sqlite

# JWT-Secret (NIE im Repository)
SECRET_KEY=<lange-zufaellige-string-mind-32-zeichen>
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Auto-derived:
# - tenancy_mode=single
# - tenant_admin_ui_enabled=false
```

### 2. Datenbank-Verschluesselung

SQLCipher verschluesselt die SQLite-Datei AT-REST. Berater-Hauptschluessel:

```powershell
# Generieren
python -c "import secrets; print(secrets.token_hex(32))"
```

Diesen Hex-String als `DB_KEY` in .env. **Verlust = Datenverlust** —
Backup-Strategie pflichtig.

### 3. Backup-Strategie (3-2-1-Regel)

3 Kopien, 2 verschiedene Medien, 1 off-site:

```powershell
# Beispiel-Backup-Script (Windows Task Scheduler taeglich)
$source = "C:\5eyes-data\production.sqlite"
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$local_dest = "D:\5eyes-backups\local\$timestamp.sqlite"
$nas_dest = "\\nas01\backups\5eyes\$timestamp.sqlite"

Copy-Item $source $local_dest
Copy-Item $source $nas_dest

# Off-Site: verschluesseltes Cloud-Backup (z.B. Tresorit, pCloud CH)
# Bitte SEPARATEN Schluessel fuer Off-Site-Verschluesselung!
```

### 4. Updates

```powershell
# Vor jedem Update: Backup machen!
cd C:\5eyes_stage9_release_ready
git pull origin develop
cd 5eyes-backend
pip install -r requirements.txt

# Schema-Migration (idempotent)
python -c "from database import init_db; init_db()"

# Backend neu starten
```

### 5. Electron-App starten

Frontend bleibt unveraendert. Electron startet Backend automatisch oder
verbindet sich auf `localhost:8000`.

---

## Pflicht-Compliance-Dokumente (Berater pflegt selber)

- [ ] **Installation-Guide** als PDF im Berater-Tresor
- [ ] **DSFA (Datenschutz-Folgeabschaetzung)** ausgefuellt nach Vorlage
  (siehe `docs/compliance/dsfa-template-tier1.md`)
- [ ] **Backup-Protokoll** mit Datum, Medium, Verifikation
- [ ] **Notfall-Wiederherstellung** dokumentiert (Schluesselverlust-Szenario)
- [ ] **Update-Log** pro Update-Datum, was geupdated wurde, Backup-Verifikation

---

## Sicherheits-Checkliste

- [ ] Backend nur auf `127.0.0.1` (KEIN externer Zugriff)
- [ ] Firewall blockt Port 8000 von extern
- [ ] DB-Datei nur fuer Berater-User lesbar (ACLs)
- [ ] SQLCipher aktiv mit starkem Key (32-byte hex)
- [ ] Backup-Schluessel separat verwahrt
- [ ] JWT-Secret aus Secrets-Manager (KeePass, Bitwarden, etc.)
- [ ] Update-Strategie dokumentiert
- [ ] Antivirus + automatische OS-Updates auf der Hardware

---

## Multi-Device-Workflow (optional)

Wenn Berater von Desktop UND Laptop arbeiten will (LAN-only, nicht Cloud):

1. Backend laeuft auf einem "Master"-Geraet (z.B. NAS)
2. Beide Laptops nutzen Electron mit `BACKEND_URL=http://master-nas:8000`
3. **Pflicht:** VPN oder LAN-only (NIE direkt uebers Internet)
4. Empfohlen: Tailscale fuer privates Mesh-VPN (Setup ~15 Min)

```dotenv
# Auf Master-Geraet
APP_HOST=0.0.0.0  # bindet auf alle interfaces
# Firewall regelt dass nur lokales Netz / Tailscale-Subnet zugreifen darf
```

---

## Migrations-Pfad zu Tier 2

Wenn der Berater spaeter zu Tier 2 wechseln will:

1. Aktuelles Backup machen
2. SQLite-DB-Export via `services.export.export_mandate_data()`
3. Bei 5eyes-Operator melden, Tier-2-Tenant wird angelegt
4. Daten-Import in Tier-2-Postgres
5. Tier-1-Backend deaktivieren (oder als Read-Only-Archive)

---

## Support + Wartung

Self-Hosted bedeutet: Berater ist verantwortlich fuer:
- Hardware-Verfuegbarkeit
- Updates installieren
- Backups verifizieren
- Sicherheits-Patches
- Notfall-Wiederherstellung

Empfehlung: **Wartungsvertrag mit 5eyes** kann diese Aufgaben uebernehmen
(monatliche Fee). Vertraglich geregelt, kein FINMA-Outsourcing-Risiko da
Berater Datenherr bleibt.
