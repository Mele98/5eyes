# Tier 2: Shared-Cloud Deployment-Recipe

**Wer:** Kleine Beratungsfirmen ohne IT-Abteilung
**Hosting:** 5eyes-Operator hostet auf Schweizer Cloud
**Empfohlen:** Infomaniak Public Cloud (Genf) / Exoscale (Lausanne)
**Compliance:** Schweizer DSGVO-/revDSG-konform, FINMA-Outsourcing meldepflichtig

---

## Architektur

```
+--------------------------------------+
| Schweizer Cloud (Infomaniak/Exoscale)|
|                                      |
|  +-----------------+                 |
|  | 5eyes Backend   |                 |
|  | (FastAPI Docker)|                 |
|  +--------+--------+                 |
|           |                          |
|  +--------v--------+                 |
|  | PostgreSQL      |                 |
|  | Row-Level-      |                 |
|  | Security (RLS)  |                 |
|  +-----------------+                 |
|                                      |
|  Mehrere Tenants:                    |
|  - Firma Mueller (tenant_id='m-vv')  |
|  - Firma Schmid  (tenant_id='s-vv')  |
|  - ...                               |
+--------------------------------------+
        | HTTPS via Cloudflare
        v
   Berater-Browsers
```

---

## Provider-Vergleich (CH-Hosting)

| Provider | Datacenter | KMU-tauglich | Compliance | Preis ab |
|----------|-----------|--------------|------------|----------|
| **Infomaniak Public Cloud** | Genf | ✓ einfache Console | ISO 27001, GDPR | ~CHF 25/Monat fuer Basis-VPS |
| **Exoscale** | Lausanne, Zuerich | ✓ moderne API | ISO 27001, SOC 2 | ~CHF 30/Monat fuer Basis |
| **Init7** | Winterthur | ✓ KMU-Spezialist | CH-only | ~CHF 50/Monat fuer Dedicated-VPS |
| **Hetzner** | DE | ⚠ nicht CH | GDPR ja, CH-Geheimnis ⚠ | ~CHF 10/Monat |

**Empfehlung:** Infomaniak fuer 1-3 Tenants, Exoscale bei Premium-Anspruch.

---

## Setup-Schritte

### 1. VPS bestellen (Infomaniak-Beispiel)

- Account bei [infomaniak.com](https://www.infomaniak.com) anlegen
- Public Cloud → VPS bestellen:
  - Image: Ubuntu 22.04 LTS oder Debian 12
  - Groesse: 4 vCPU / 8 GB RAM / 80 GB SSD (Starter)
  - Region: Genf
  - Backup: aktivieren (taeglich, 7 Tage Retention)

### 2. VPS Hardening

```bash
# Connect
ssh root@<vps-ip>

# Ubuntu/Debian Update
apt update && apt upgrade -y

# Nicht-Root-User
adduser fivE
usermod -aG sudo fivE

# SSH-Hardening
nano /etc/ssh/sshd_config
# PermitRootLogin no
# PasswordAuthentication no
# Port 12345  (Custom-Port)
systemctl restart sshd

# Firewall
ufw allow 12345/tcp
ufw allow 443/tcp
ufw enable

# Fail2Ban
apt install -y fail2ban
systemctl enable --now fail2ban
```

### 3. Docker + Compose installieren

```bash
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-v2
usermod -aG docker fivE
```

### 4. Postgres aufsetzen

```yaml
# /home/fivE/postgres/docker-compose.yml
version: "3.8"
services:
  postgres:
    image: postgres:16
    container_name: 5eyes-postgres
    restart: always
    environment:
      POSTGRES_PASSWORD: <STARK_RANDOM_PASSWORD>
      POSTGRES_DB: fiveyes
    volumes:
      - ./data:/var/lib/postgresql/data
      - ./backups:/backups
    ports:
      - "127.0.0.1:5432:5432"  # nur localhost
```

```bash
cd /home/fivE/postgres
docker compose up -d
```

### 5. 5eyes Backend in Container

```yaml
# /home/fivE/5eyes/docker-compose.yml
version: "3.8"
services:
  backend:
    image: 5eyes-backend:latest
    container_name: 5eyes-backend
    restart: always
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      - postgres
    networks:
      - default
networks:
  default:
    external:
      name: postgres_default
```

```dotenv
# /home/fivE/5eyes/.env
DEPLOYMENT_TIER=tier2
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000

# Postgres
# +psycopg (nicht bare postgresql://) ist Pflicht: requirements.txt installiert
# psycopg[binary] v3, kein psycopg2. SQLAlchemy versucht bei bare postgresql://
# per Default psycopg2 zu laden -> Verbindung schlaegt beim ersten Deploy fehl.
DATABASE_URL=postgresql+psycopg://postgres:<PASSWORD>@5eyes-postgres:5432/fiveyes

# Multi-Tenancy
TENANCY_MODE=multi
TENANT_ADMIN_UI_ENABLED=true

# JWT
SECRET_KEY=<MIND_64_ZEICHEN_RANDOM>
ACCESS_TOKEN_EXPIRE_MINUTES=480

# CORS — nur deine Frontend-Domain
CORS_ORIGINS=https://app.5eyes-mueller.ch,https://app.5eyes-schmid.ch
```

### 6. HTTPS via Caddy / Cloudflare

**Variante A: Caddy (einfach):**

```caddy
# /home/fivE/caddy/Caddyfile
app.5eyes-mueller.ch {
    reverse_proxy localhost:8000
}
app.5eyes-schmid.ch {
    reverse_proxy localhost:8000
}
```

Caddy macht Let's Encrypt automatisch.

**Variante B: Cloudflare-Tunnel** (kein offener Port):

```bash
cloudflared tunnel login
cloudflared tunnel create 5eyes-prod
# DNS Records via Cloudflare Dashboard
cloudflared tunnel route dns 5eyes-prod app.5eyes-mueller.ch
```

### 7. Default-Tenant + Super-Admin anlegen

```bash
docker compose exec backend python -c "
from database import ensure_default_tenant
from models.tenant import Tenant, TIER_2_SHARED_CLOUD
from models.users import User
from services.auth import hash_password
from database import SessionLocal, new_uuid
from datetime import datetime, timezone

ensure_default_tenant()
db = SessionLocal()
super_admin = User(
    id=new_uuid(),
    username='5eyes-operator',
    password_hash=hash_password('<DEIN_PASSWORD>'),
    full_name='5eyes Operator',
    role='super_admin',
    tenant_id='main',
    is_active=1,
    created_at=datetime.now(timezone.utc).isoformat(),
    updated_at=datetime.now(timezone.utc).isoformat(),
)
db.add(super_admin)
db.commit()
print('Super-Admin angelegt:', super_admin.id)
"
```

### 8. Neue Lizenz onboarden

Berater "Mueller VV" will Lizenz:

```bash
# Login als Super-Admin via /auth/login → JWT erhalten

# Tenant erstellen
curl -X POST https://app.5eyes-mueller.ch/tenants \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "Mueller Vermoegensverwaltung AG",
    "slug": "mueller-vv",
    "hosting_tier": "tier2",
    "license_status": "active",
    "max_users": 5
  }'

# Tenant-Admin-User erstellen (via existing /users POST)
# ...

# User dem Tenant zuweisen
curl -X PUT https://app.5eyes-mueller.ch/tenants/<TENANT_ID>/users/<USER_ID>/assign \
  -H "Authorization: Bearer <JWT>"
```

---

## Pflicht-Compliance-Items (Tier 2 Operator)

- [ ] **AVV-Template** mit jedem Berater unterschreiben
- [ ] **FINMA-Outsourcing-Anzeige** einreichen
- [ ] **DSFA (Datenschutz-Folgeabschaetzung)** dokumentieren
- [ ] **SLA-Dokument** mit Berater vereinbaren (Uptime, Response-Time)
- [ ] **Incident-Response-Plan** (was bei Breach?)
- [ ] **Backup-/DR-Plan** dokumentiert + getestet
- [ ] **Audit-Log-Streaming** zu externem System (z.B. ELK, Splunk)

---

## Operations-Checkliste

### Taeglich
- Backup-Status checken
- Audit-Log auf Anomalien
- Resource-Usage (Cloud-Console)

### Woechentlich
- Sicherheits-Updates (apt update / docker image pull)
- Backup-Restore-Test (auf separater VM)

### Monatlich
- Performance-Review
- Cost-Review
- Berater-Feedback einholen

### Quartalsweise (Tier-2-Premium)
- Pentest extern beauftragen
- Disaster-Recovery-Drill
- Compliance-Audit-Review

---

## Preis-Skizze pro Tenant

```
Setup-Gebuehr Tenant: CHF 2'000
  - VPS + Postgres-Setup
  - Tenant-Anlegen
  - Onboarding (2-3 Termine)
  - Compliance-Dokumente

Monatlich:
  - Basis-Lizenz: CHF 200 (1 Berater, 10 Mandate, 5GB Storage)
  - Pro zusaetzlichem Berater: CHF 50
  - Storage-Erweiterung 10GB: CHF 30/Monat
  - Premium-SLA (4h Response, 99.9% Uptime): CHF 200/Monat
```

VPS-Kosten (1 Server fuer mehrere Tenants):
- Infomaniak 4 vCPU / 8 GB: ~CHF 25
- Skaliert: 10 Tenants × CHF 200 = CHF 2'000/Monat - CHF 25 Hosting
  → 5eyes-Operator-Marge ~CHF 1'900/Monat fuer ~5h Wartung/Woche
