# 5eyes Deployment-Recipes

Diese Sammlung bietet **Schritt-fuer-Schritt-Anleitungen** fuer alle drei
Hosting-Tiers aus ADR-009.

## Uebersicht

| Tier | Datei | Wann |
|------|-------|------|
| Phase-1 Demo | [phase1-cloudflare-tunnel.md](phase1-cloudflare-tunnel.md) | Schnelle Demo aus Self-Hosted heraus |
| Tier 1 | [tier1-self-hosted.md](tier1-self-hosted.md) | Berater hostet auf eigener Hardware |
| Tier 2 | [tier2-shared-cloud.md](tier2-shared-cloud.md) | 5eyes-Operator hostet fuer mehrere Berater (Infomaniak/Exoscale) |
| Tier 3 | [tier3-dedicated.md](tier3-dedicated.md) | Premium: dedicated VPS pro Berater |

## Konfigurations-Cheatsheet

Alle Tier-spezifischen Settings werden via `.env`-Datei gesetzt. Das Backend
liest sie beim Start. Der `services.tier_config.get_effective_tenancy_config()`
leitet die uebrigen Settings automatisch ab.

```dotenv
# Minimal-Config pro Tier
DEPLOYMENT_TIER=tier1   # tier1 | tier2 | tier3

# Optional manuell uebersteuern:
# TENANCY_MODE=multi
# TENANT_ADMIN_UI_ENABLED=true
```

Auto-Derivation pro Tier:

| Setting | Tier 1 | Tier 2 | Tier 3 |
|---------|--------|--------|--------|
| `tenancy_mode` | single | multi | single |
| `tenant_admin_ui_enabled` | False | True | False |
| `recommended_db_engine` | sqlite | postgres | postgres |
| `external_backup_required` | False | True | True |
| `audit_log_streaming_required` | False | True | True |
| `finma_outsourcing_notification_required` | False | True | True |

## Compliance-Pflicht-Liefer-Items

Pro Tier sind unterschiedliche Compliance-Dokumente pflichtig (siehe
[ADR-009](../adr/ADR-009-3-tier-hosting-architecture.md) Kap. 5):

| Item | Tier 1 | Tier 2 | Tier 3 |
|------|--------|--------|--------|
| Installation-Guide | ✓ | ✓ | ✓ |
| Backup-Empfehlung | ✓ | – | – |
| Update-Process-Doku | ✓ | – | – |
| DSFA-Template fuer Berater | ✓ | – | – |
| AVV-Template | – | ✓ | ✓ |
| FINMA-Outsourcing-Anzeige-Template | – | ✓ | ✓ |
| SLA-Dokument | – | ✓ | ✓ |
| Incident-Response-Plan | – | ✓ | ✓ |
| Backup-/DR-Plan | – | ✓ | ✓ |
| Pentest-Berichte quartalsweise | – | optional | ✓ |
| SOC 2 Type 2 Audit-Bericht | – | optional | optional |
| BCM-Plan | – | – | ✓ |

## Quick-Decision-Hilfe fuer Lizenz-Nehmer

```
Wenn Berater fragt:
  "Ich will MAXIMUM Compliance, eigene Hardware, kein Cloud-Risiko"
  → Tier 1 Self-Hosted

  "Ich brauche minimal-Aufwand, akzeptiere managed Service, kleine Firma"
  → Tier 2 Shared-Cloud (Infomaniak Genf / Exoscale Lausanne)

  "Ich habe Premium-Compliance-Anforderungen (Bankgeheimnis, Mandate-Heavy)"
  → Tier 3 Dedicated VPS
```

## Allgemeine Sicherheits-Pflichten (alle Tiers)

- HTTPS in jedem Setup das uebers Internet erreichbar ist
- JWT-Secret in `.env` (NIE im Repository)
- Bcrypt-Hashed Passworter (default in 5eyes)
- Audit-Log-Integritaets-Hash (default aktiv)
- SQLCipher optional fuer SQLite-Verschluesselung-at-Rest
- Backups in jedem Tier (siehe tier-spezifische Empfehlungen)
