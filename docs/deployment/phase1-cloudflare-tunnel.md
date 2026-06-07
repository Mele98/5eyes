# Phase 1: Demo via Cloudflare-Tunnel

**Status:** Quick & Dirty fuer Demos (Lizenz-Vorstellung)
**Compliance:** NUR mit Demo-/Testdaten, NICHT mit echten Kunden-Daten
**Aufwand:** 10-15 Minuten

---

## Wann das genug ist

- Du willst potentiellen Lizenz-Kunden 5eyes vorstellen
- Demo laeuft auf deinem Laptop, Kunde sieht via Browser
- Kein echtes Kunden-Daten-Material im System
- Nach der Demo wird die Demo-DB geloescht oder isoliert

## Wann NICHT

- Echte Kundendaten — dann brauchst du Tier 1/2/3 mit Compliance-Setup
- Mehrere gleichzeitige Berater — dann brauchst du Tier 2
- Permanenter Zugriff fuer Drittparteien — dann brauchst du Tier 3

---

## Setup-Schritte

### 1. Cloudflared installieren

```powershell
# Windows (winget)
winget install --id Cloudflare.cloudflared
```

Auf macOS/Linux: `brew install cloudflare/cloudflare/cloudflared` oder
[Download von cloudflared](https://github.com/cloudflare/cloudflared/releases).

### 2. Backend extern erreichbar machen

5eyes-Backend bindet standardmaessig auf `127.0.0.1` (nur localhost).
Fuer Tunnel-Zugriff: auf `0.0.0.0` umstellen via `.env`-Variable:

```dotenv
# In 5eyes-backend/.env (oder via PowerShell-Env-Variable)
APP_HOST=0.0.0.0
APP_PORT=8000

# Demo-Modus: erlaubt unverschluesselte Verbindungen (Tunnel macht TLS).
# In Production niemals so. Hier OK weil Tunnel-Layer schon TLS macht.
APP_ENV=development
```

### 3. CORS-Origin oeffnen (Demo-Phase)

In `5eyes-backend/.env`:

```dotenv
CORS_ORIGINS=*
# Production: CORS_ORIGINS=https://app.5eyes.example
```

### 4. Backend starten

```powershell
cd C:\5eyes\5eyes_stage9_release_ready\5eyes-backend
python main.py
```

Backend laeuft jetzt auf `http://0.0.0.0:8000` (= alle Interfaces).
Du erreichst es lokal weiterhin als `http://localhost:8000`.

### 5. Tunnel starten

In einer **zweiten PowerShell**:

```powershell
cloudflared tunnel --url http://localhost:8000
```

Output sieht so aus:

```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://random-words-here.trycloudflare.com                                                |
+--------------------------------------------------------------------------------------------+
```

Diese **HTTPS-URL** kannst du in deinem Demo-Termin teilen — der Kunde
oeffnet die URL im Browser, sieht 5eyes.

### 6. Frontend anpassen (falls separat gehostet)

Wenn das Frontend (`5eyes_v2.html`) lokal lebt und gegen das Backend
geht: setze die Backend-URL in der HTML oder via JS-Konfiguration auf
die Tunnel-URL.

Falls du Electron als Demo-Frontend nutzt: aktuell ist Backend-URL
hartcodiert auf `localhost:8000`. Workaround:

- Variante A: Demo-Kunde nutzt eigenen Browser, oeffnet Tunnel-URL
- Variante B: Setze Electron `BACKEND_URL` env-Variable auf Tunnel-URL

---

## Demo-User anlegen (Schritte fuer Demo-Termin)

Damit der Demo-Kunde direkt einloggen kann, leg vorher einen
Demo-Account an:

```powershell
# In Backend-Console
python -c "
from database import SessionLocal, ensure_default_tenant
from models.users import User
from services.auth import hash_password
from datetime import datetime, timezone
import uuid

ensure_default_tenant()
db = SessionLocal()
demo = User(
    id=str(uuid.uuid4()),
    username='demo',
    password_hash=hash_password('demo2026'),
    full_name='Demo Lizenz-Kunde',
    role='advisor',
    is_active=1,
    created_at=datetime.now(timezone.utc).isoformat(),
    updated_at=datetime.now(timezone.utc).isoformat(),
)
db.add(demo)
db.commit()
print('Demo-User angelegt:', demo.id)
"
```

Login: `demo / demo2026`

---

## Sicherheits-Hinweise (Pflicht-Lesen)

- **Tunnel-URL ist oeffentlich erreichbar** — wer die URL kennt kommt rein
- **Kein DDoS-Schutz** fuer dein Backend ausser Cloudflares Default
- **Nicht laenger als Demo-Dauer aktiv lassen** — STRG+C beendet Tunnel
- **Vor Demo: Backend mit FRESH SQLite-DB starten** (alte Daten loeschen)
- **Nach Demo: Demo-User-Account und Demo-Daten loeschen**

## Wenn die Demo gut lief

→ Lizenz-Vertrag verhandeln
→ Kunde waehlt Tier (1, 2 oder 3)
→ Setup nach den entsprechenden tier-spezifischen Recipes

---

## Troubleshooting

**"Backend nicht erreichbar via Tunnel"**

Pruefe ob `APP_HOST=0.0.0.0` gesetzt ist und Backend wirklich darauf bindet:

```powershell
netstat -an | findstr 8000
```

Sollte zeigen: `0.0.0.0:8000` (nicht `127.0.0.1:8000`).

**"CORS-Fehler im Browser"**

`CORS_ORIGINS=*` in .env setzen (nur fuer Demo OK).

**"Tunnel-URL aendert sich bei jedem Restart"**

Das ist by-design fuer Quick-Tunnels. Fuer permanente URL:
[Cloudflare-Tunnel mit eigener Domain](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/),
braucht Cloudflare-Account + DNS-Setup (~30 Min einmalig).
