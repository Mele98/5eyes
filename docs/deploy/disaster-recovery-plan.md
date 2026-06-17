# Disaster-Recovery-Plan (DRP)

**Roadmap #109** · Status: Plan (Ist-Stand 2026-06-15) · gilt für T2/T3 (betreiber-gehostet)

> Ziel: definierte Wiederherstellung nach Datenverlust/Ausfall, mit messbaren
> RTO/RPO und einem **regelmässig geübten** Restore. Ergänzt
> [provisioning-runbook.md](provisioning-runbook.md) und die Compliance-Vorlagen.

---

## 1. Schutzziele (RTO / RPO)
| Szenario | RTO (Wiederanlauf) | RPO (max. Datenverlust) |
|---|---|---|
| App-/Prozess-Absturz | < 15 min (Auto-Restart, systemd) | 0 |
| VPS-/Host-Ausfall | < 4 h (Neuaufsatz aus Backup) | ≤ 24 h (tägliches Backup) bzw. ≤ letzte WAL/Replikation |
| RZ-/Region-Ausfall | < 24 h (Off-Site-Restore CH) | ≤ 24 h |
| Datenkorruption/Fehlbedienung | < 4 h (Point-in-Time aus Backup) | ≤ 24 h |

> RPO ≤ 24 h gilt für das tägliche Backup; mit Postgres-WAL-Archivierung (#8/#15)
> auf nahe 0 senkbar. Werte mit der Mandantin im AVV/SLA bestätigen.

## 2. Was gesichert wird
- **Datenbank** (SQLite heute via `sqlite3.Connection.backup()` 03:00 lokal +
  On-Demand-Endpoint; Postgres-Ziel: `pg_dump`/PITR, Roadmap #8/#15).
- **Secrets/Config** (separat, verschlüsselt; nie im DB-Backup).
- **Anwendungsartefakte** (Code = Git; Build reproduzierbar).

## 3. Backup-Strategie
- Täglich automatisiert (Scheduler vorhanden) + vor Deploys ad-hoc.
- **Verschlüsselt**, **CH-Off-Site** (zweites CH-RZ, Roadmap #15).
- Retention dokumentieren (z. B. 7 täglich / 4 wöchentlich / 12 monatlich).
- Integrität: Backup-Datei nach Erstellung verifizieren (Öffnen/Checksumme).

## 4. Restore-Prozedur (Kurz)
1. Ausfall feststellen, Incident eröffnen (Zeit, Umfang, betroffene Tenants).
2. App in Wartung/Read-Only setzen (falls erreichbar).
3. Jüngstes integres Backup wählen (Off-Site falls primär verloren).
4. DB wiederherstellen (Ziel-Host), Secrets/Config einspielen.
5. App starten, **Health prüfen**: `/health/live` + `/health/ready` (DB ok).
6. **Mandantentrennung-Stichprobe** + Login/2FA für einen Test-Account.
7. Incident schliessen, betroffene Mandantinnen informieren (AVV §4.7 — Meldepflicht
   bei Datensicherheitsverletzung).

## 5. Restore-Drill (PFLICHT, sonst ist das Backup nur eine Hoffnung)
- **Frequenz:** mindestens quartalsweise + nach jeder grösseren Infra-Änderung.
- **Ablauf:** Backup in eine **isolierte** Umgebung restoren, Health + Stichprobe,
  RTO/RPO messen, Abweichungen als Findings.
- **Protokoll:** Datum, Backup-Stand, gemessene RTO/RPO, Befunde, Massnahmen.

| Datum | Backup-Stand | RTO gemessen | RPO gemessen | Befunde |
|---|---|---|---|---|
| _…_ | _…_ | _…_ | _…_ | _…_ |

## 6. Rollen & Eskalation
- **Betreiber:** Restore-Durchführung, Health-Check, Drill-Protokoll.
- **Mandantin:** Information der Endkunden falls erforderlich.
- **Eskalation:** definierte Kontaktkette (auszufüllen), EDÖB-Meldung bei
  Datensicherheitsverletzung mit hohem Risiko (revDSG).

## 7. Offene technische Voraussetzungen (Roadmap)
Off-Site-Replikation (#15), Postgres + PITR (#8), Monitoring/Alerting (#14),
Secret-Management (#13). Bis dahin: tägliches lokales Backup + manuelle Off-Site-Kopie
+ dokumentierter Drill.
