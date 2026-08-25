# Tier 3: Dedicated Deployment-Recipe

**Wer:** Premium-Berater mit Banking-Secret-Anforderungen
**Setup:** Dedicated VPS pro Lizenz-Nehmer
**Compliance:** Maximum (CH-Hardware, SOC 2 Type 2 optional)
**Setup-Aufwand:** 1-2 Tage

---

## Architektur

```
+--------------------------------------+
| Dedicated VPS pro Berater            |
| (Init7 / Quickline / Infomaniak)     |
|                                      |
|  +-----------------+                 |
|  | 5eyes Backend   |                 |
|  | (FastAPI Docker)|                 |
|  +--------+--------+                 |
|           |                          |
|  +--------v--------+                 |
|  | PostgreSQL      |                 |
|  | (single-tenant) |                 |
|  +-----------------+                 |
|                                      |
|  Nur dieser Berater hat Zugriff      |
+--------------------------------------+
```

**Kein Daten-Sharing mit anderen Tenants** (im Gegensatz zu Tier 2).
Berater verwaltet ggf. eigenen Encryption-Master-Key (Hardware-Token).

---

## Provider-Empfehlungen

| Provider | Datacenter | Stark in |
|----------|-----------|----------|
| Init7 | Winterthur | KMU, CH-only, dediziert |
| Quickline | Bern, Basel | Voll-Dedicated mit Support |
| Infomaniak Dedicated | Genf | KMU-tauglich, gut Console |
| Exoscale Dedicated | Lausanne | Cloud-Native, Premium |

Bevorzuge dediziertes Eisen, nicht Shared-VPS.

---

## Setup (vergleichbar zu Tier 2, mit Premium-Extras)

Folge dem [Tier 2 Setup](tier2-shared-cloud.md) mit diesen Aenderungen:

1. **Eigene VPS pro Lizenz-Nehmer** (kein Shared-Resource)
2. **`DEPLOYMENT_TIER=tier3`** in .env
3. **Single-Tenant Modus** (auto-derived: `tenancy_mode=single`)
4. **Hardware-Token fuer Encryption-Key** optional (Yubikey, Trezor)
5. **Pentest-Berichte quartalsweise** vertraglich vereinbart
6. **SOC 2 Type 2 Audit-Vorbereitung** auf Wunsch

```dotenv
# /home/fivE/5eyes/.env
DEPLOYMENT_TIER=tier3
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000

# Postgres
DATABASE_URL=postgresql://postgres:<PASSWORD>@localhost:5432/fiveyes

# Tier 3 = single-tenant, kein Admin-UI
TENANCY_MODE=single
TENANT_ADMIN_UI_ENABLED=false

# Berater-eigener Encryption-Master-Key
APP_ENCRYPTION_KEY_SOURCE=hardware-token  # oder 'env'
```

---

## Pflicht-Compliance-Items (Tier 3)

Zusaetzlich zu allen Tier 2 Items:

- [ ] **Pentest quartalsweise** (extern, dokumentiert)
- [ ] **SOC 2 Type 2 Audit-Bericht** (auf Wunsch)
- [ ] **BCM-Plan** (Business Continuity Management)
- [ ] **Hardware-Inventar** dokumentiert
- [ ] **Chain-of-Custody** fuer Hardware-Token (wenn Encryption-Key dort)
- [ ] **Versicherung** fuer Cyber-Vorfaelle

---

## SLA-Standards

| Metrik | Tier 2 | Tier 3 |
|--------|--------|--------|
| Uptime | 99.5% | 99.9% |
| Response-Time | 24h | 4h |
| Backup-RPO | 24h | 4h |
| Recovery-RTO | 4h | 1h |
| Pentest-Frequenz | optional | quartalsweise |
| Incident-Response | Best-effort | dediziert 24/7 |

---

## Preis-Skizze pro Tier-3-Lizenz

```
Setup-Gebuehr: CHF 5'000 - 10'000
  - Dedicated VPS bestellen + konfigurieren
  - 2-3 Tage Onboarding mit Berater-Team
  - Compliance-Vollpaket (alle Templates)
  - Erstpentest

Monatlich: CHF 1'500 - 5'000
  - VPS-Kosten (CH-Dedicated): ~CHF 300-800
  - Wartung + Patches: ~CHF 300
  - SLA-Premium-Support: ~CHF 500
  - Pentest-Quartalsweise (umgelegt): ~CHF 200
  - Operator-Marge: CHF 200-3'200
```

---

## Wann lohnt sich Tier 3?

- Berater hat **> 50 aktive Mandate**
- Berater hat **Mandate > CHF 10 Mio AUM**
- Berater hat **regulatorische Anforderungen** ueber FINRG-Mindeststandard
- Berater will **Maximum-Compliance-Story** als Wettbewerbsvorteil

Bei kleinerem Setup ist Tier 2 wirtschaftlich sinnvoller.
