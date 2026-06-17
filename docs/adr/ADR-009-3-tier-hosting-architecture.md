# ADR-009: 3-Tier-Hosting-Architektur fuer Lizenz-Modell

- **Status:** Accepted (Strategie), Implementation: in-progress
- **Datum:** 2026-06-08
- **Sprint:** T1 (Foundation)
- **Trigger:** Strategischer Geschaeftsentscheid: 5eyes wird an Treuhaender + Vermoegensverwalter lizenziert. Verschiedene Lizenz-Nehmer haben verschiedene Compliance-Anforderungen und Risikoneigungen.

---

## Kontext

5eyes ist heute (siehe ADR-007) eine **Desktop-App** mit lokaler SQLite-DB. Multi-User innerhalb einer Installation funktioniert via JWT. Multi-Tenant (mehrere Beratungsfirmen am gleichen Server) ist deferred.

**Geschaeftliche Realitaet 2026-06-08:** User plant Lizenz-Verkauf an Dritt-Berater (Treuhaender, Vermoegensverwalter). Diese haben verschiedene Bedarfe:
- Manche wollen volle Kontrolle (on-premise, "Cloud kommt nicht in Frage")
- Manche wollen Convenience (managed SaaS)
- Manche brauchen Compliance-Premium (dedicated Hardware fuer Banking-Geheimnis)

**Schweiz-spezifische Constraints:**
- **revDSG (2023):** Auftragsverarbeitungsvertrag pflichtig fuer alle Cloud-Setups
- **FINMA RS 2018/3:** Outsourcing-Meldepflicht bei "wesentlichen Diensten"
- **Art. 47 BankG:** Bankgeheimnis bindet Kundendaten
- **FIDLEG:** Beratungsprotokoll-Pflicht (haben wir bereits)

---

## Entscheidung

**3-Tier-Hosting-Modell mit gemeinsamer Code-Base.** Tier-Spezifika via Deployment-Configuration, NICHT via Code-Forks.

### Tier 1 — SELF-HOSTED

**Wer:** Berater mit eigener IT-Infrastruktur, hoechste Compliance-Anforderungen, Anti-Cloud-Praeferenz.

**Setup:**
- 5eyes laeuft auf Berater-eigener Hardware (Desktop, NAS, Home-Server)
- SQLite-DB lokal, optional mit SQLCipher verschluesselt
- KEIN externer Cloud-Zugriff
- Update-Mechanismus via signiertes Installer-Paket
- Tenant_id ist effektiv konstant (= "self")

**Compliance:**
- ✅ FINMA-konform (kein Outsourcing)
- ✅ revDSG-konform (Berater = Datenherr)
- ✅ Bankgeheimnis-Maximum-Schutz
- ❌ Keine Multi-Device-Synchronisation (es sei denn LAN-VPN)
- ❌ Berater traegt Backup-/DR-Verantwortung selbst

**Preis (Skizze):**
- One-time Lizenzgebuehr CHF 5'000-15'000
- Optional Wartungsvertrag CHF 1'000-3'000/Jahr

### Tier 2 — SHARED-CLOUD (5eyes-managed)

**Wer:** Kleine Beratungsfirmen ohne IT-Abteilung, akzeptieren managed Service mit klar dokumentierter Compliance.

**Setup:**
- Schweizer VPS (Infomaniak Genf / Exoscale Lausanne)
- PostgreSQL mit Row-Level-Security (RLS) fuer Tenant-Isolation
- Per-Tenant Encryption-Key (clientseitig generiert, serverseitig encrypted-at-rest)
- HTTPS-Endpoint, Cloudflare-Schutz vor DDoS
- Automatisierte Backups + Off-Site-Replication innerhalb CH
- Tenant_id ist real und JWT-claim-basiert

**Compliance:**
- ✅ Schweizer Hosting (CH-Datacenter)
- ✅ AVV-Template fuer Berater
- ✅ ISO 27001 (Infomaniak/Exoscale-Zertifizierung)
- ⚠️ Outsourcing-Meldung an FINMA pflichtig (5eyes liefert Template)
- ⚠️ Bankgeheimnis-Risiko: Daten verlassen Berater-Geraet — Mitigation via Encryption + Audit-Logs

**Preis (Skizze):**
- Setup-Gebuehr CHF 2'000
- Monatliche Subscription CHF 200-500/Berater
- Pro-Tenant-Storage-Limit (z.B. 10GB) im Basis-Tarif

### Tier 3 — DEDICATED

**Wer:** Premium-Berater mit hoher Mandate-Anzahl oder besonderen Compliance-Anforderungen.

**Setup:**
- Dedicated VPS pro Lizenz-Nehmer (Schweizer Provider)
- KEIN Daten-Sharing mit anderen Tenants (physische Isolation)
- Berater kann zusaetzlich Hardware-Encryption-Key managen
- Optional: SOC 2 Type 2 Audit-Bereitschaft
- Multi-User innerhalb der Firma via JWT
- Tenant_id technisch vorhanden, faktisch konstant pro Instance

**Compliance:**
- ✅ Schweizer Hosting
- ✅ Dedicated Hardware (kein Shared-Tenant-Risk)
- ✅ Pentest-Bericht pro Quartal optional
- ✅ Off-Site Backup mit Berater-Schluessel
- ✅ FINMA-Compliance-Audit-Trail

**Preis (Skizze):**
- Setup-Gebuehr CHF 5'000-10'000
- Monatliche Subscription CHF 1'500-5'000/Firma (inkl. Hardware-Kosten)
- SLA: 99.9% Uptime, 4h Response-Time

---

## Gemeinsame Code-Base — Architektur

**Prinzip:** ALLE Tiers nutzen die gleiche Code-Base. Tier-Spezifika via:
1. `settings.deployment_tier` (`'tier1' | 'tier2' | 'tier3'`)
2. `settings.tenancy_mode` (`'single' | 'multi'`)
3. DB-Schema-Konfiguration

### Tenant-Modell (universell)

Auch in Tier 1 + 3 existiert das `tenants`-Table — mit genau einem Eintrag. Damit:
- Code-Pfade sind konsistent
- Migration Tier 1 → Tier 2 ist "nur Daten in shared-Cloud importieren"
- Cross-Tenant-Leak-Tests laufen in jeder Konfiguration

### Configuration-Matrix

| Setting | Tier 1 | Tier 2 | Tier 3 |
|---------|--------|--------|--------|
| `deployment_tier` | `tier1` | `tier2` | `tier3` |
| `tenancy_mode` | `single` | `multi` | `single` |
| `db_engine` | sqlite | postgres | postgres |
| `tenant_admin_ui_enabled` | False | True (super-admin) | False |
| `external_backup_enabled` | optional | True | True |
| `audit_log_streaming` | optional | True | True |

### Migration-Pfad

```
Tier 1 (Self-Hosted) ──upgrade──> Tier 2 (Shared-Cloud)
                              \─> Tier 3 (Dedicated)

Tier 2 ──upgrade──> Tier 3 (eigene VPS, Daten-Export+Import)
```

---

## Implementation-Phasen (T1-T5)

| Phase | Was | Aufwand | Status |
|-------|-----|---------|--------|
| **T1** | ADR-009 + Tenant-Model + tenant_id-Columns (nullable, BC) | 1 Tag | **in progress** |
| T2 | Tenant-Aware JWT + Auth | 1-2 Tage | pending |
| T3 | Repository-Layer scoped by tenant_id + Cross-Leak-Tests | 2-3 Tage | pending |
| T4 | Tenant-Admin-API (Tier 2 only) | 1-2 Tage | pending |
| T5 | Tier-Specific Configs + Deployment-Doku | 2-3 Tage | pending |

**Total geschaetzt:** 7-12 Tage (parallel zur normalen Sprint-Arbeit moeglich).

---

## Compliance-Liefer-Items pro Tier

### Tier 1 (Self-Hosted) — Pflicht-Dokumente fuer Lizenz-Nehmer

- [ ] Installation-Guide mit Sicherheits-Hinweisen
- [ ] Backup-Empfehlung (3-2-1-Regel)
- [ ] Update-Process-Doku
- [ ] DSFA-Template fuer Berater (zu fuellen)

### Tier 2 + 3 (Cloud) — Zusaetzlich

- [ ] AVV-Template (zwischen 5eyes-Operator und Berater)
- [ ] DSFA fuer 5eyes-Operator (zentral gepflegt)
- [ ] FINMA-Outsourcing-Anzeige-Template
- [ ] SLA-Dokument
- [ ] Incident-Response-Plan
- [ ] Backup-/DR-Plan

### Tier 3 — Zusaetzlich Premium

- [ ] Optional SOC 2 Type 2 Audit-Bericht
- [ ] Pentest-Berichte Quartalsweise
- [ ] BCM-Plan (Business Continuity Management)

---

## Out-of-Scope (Stage 9)

| Punkt | Begruendung |
|-------|------------|
| Mobile-Apps (iOS/Android) | Kommt nach Tier 2 stabilisiert |
| White-Label-Branding | Lizenz-Nehmer behaelt 5eyes-Branding initial |
| Multi-Region (DE/AT/FR) | Erst nach CH-Markt-Etablierung |
| API-Marketplace fuer Drittanbieter | Phase 3 nach Konsolidierung |

---

## Konsequenzen

**Positiv:**
- Geschaeftsmodell offen fuer 3 verschiedene Berater-Profile
- Code-Base bleibt single-source-of-truth
- Migration zwischen Tiers moeglich
- Compliance-Story klar pro Tier

**Negativ:**
- Mehraufwand fuer Multi-Tenant-Code (T1-T5)
- Operations-Verantwortung fuer Tier 2 + 3 (Cloud-Operator-Rolle entsteht)
- Premium-Tier-Pricing muss gerechtfertigt werden via klare Mehrwerte
- FINMA-Outsourcing-Anzeige-Pflicht (Tier 2 + 3)

---

## Referenzen

- ADR-007 (Multi-Tenancy-Strategie) — wurde im Status-Quo gehalten, jetzt durch ADR-009 ueberholt
- ADR-008 (HTML-Monolith-Migration) — Frontend-Strategie bleibt unabhaengig vom Tier
- ADR-005 (Free-Data-Pipeline) — gilt fuer alle Tiers
- ADR-003 (Anti-Market-Timing) — Methodik-Disziplin tier-unabhaengig
- Memory: `project_5eyes_audit.md` — Lizenz-Geschaeftsmodell-Stand

---

## Implementations-Tracking

- **T1 (heute):** Tenant-Model + tenant_id-Columns, ADR (dieses Doc)
- T2 (folgt): JWT mit tenant_id-claim
- T3 (folgt): Repository-Layer-Scoping
- T4 (folgt): Tenant-Admin-API
- T5 (folgt): Tier-Specific-Configs + Deployment-Recipes

---

## Update 2026-06-15 — Stand T1–T5 + externer Zugriff

- [✓] **T1–T5 Foundation** gebaut: Tenant-Model + `tenant_id`-claim/Scoping, Tenant-Admin-Flow
  (Firmen-/Team-UI + Invite), Tier-Felder (`hosting_tier`, `license_status`, `quotas`).
- [✓] **Externer Zugriff** (Browser-Hosting/Remote-Test) inkl. Pflicht-2FA, harte
  Mandantentrennung (App-Level), Invite-Onboarding, `start-external.ps1`.
- [✓] **Compliance-Vorlagen** erstellt: AVV (#16), FINMA-Outsourcing (#17), DSFA (#18),
  Provisioning-Runbook (#23) unter `docs/compliance/` + `docs/deploy/`.
- [ ] **Produktiv-Hosting** offen: CH-VPS (#12), Postgres-Provider-Entscheid (#7) +
  Adapter (#8) + RLS (#9), Secret-Management (#13), Monitoring (#14), Off-Site-Backup (#15).
- [ ] **Gate vor Echtdaten:** `allow_real_client_data` bleibt `false` bis Compliance je
  Tenant abgeschlossen (Runbook §0/§5).

Kurz: **Software- + Tenant-Schicht produktiv-reif**; offen ist die **Betriebs-/Infra-Schicht**
(CH-Hosting, Postgres/RLS, Secrets, Monitoring, Backups) — braucht Provider-Entscheid (#7).
