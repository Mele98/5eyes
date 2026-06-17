# Provisioning- & Onboarding-Runbook (Betreiber)

**Roadmap #23** · Status: Runbook (Ist-Stand 2026-06-15)

Schritt-für-Schritt für den **Betreiber**, um eine neue Beratungsfirma (Tenant)
aufzunehmen — von der Firma anlegen bis zum einsatzbereiten Berater-Login.
Bezug: [ADR-007 Multi-Tenancy](../adr/ADR-007-multi-tenancy-strategy.md),
[ADR-009 3-Tier-Hosting](../adr/ADR-009-3-tier-hosting-architecture.md).

---

## 0. Voraussetzungen
- Hosting-Tier entschieden (T1/T2/T3). Bei T2/T3: AVV + ggf. FINMA-Outsourcing geklärt
  (siehe [compliance/](../compliance/)).
- Produktiv-Umgebung: `app_env=production` (aktiviert Config-Guards: non-default Secrets,
  CORS-Härtung, Token-TTL-Cap), TLS + Edge (Caddyfile/Cloudflare), Backups aktiv.
- **Daten-Klassifizierungs-Sperre:** `allow_real_client_data` bleibt `false`, bis Compliance
  (AVV/Outsourcing/DSFA) für diesen Tenant abgeschlossen ist (Roadmap #29/#91).

## 1. Firma (Tenant) anlegen
- Über Operator-Werkzeug `docs/deploy/promote_operator.py` bzw. das Operator-/Admin-Menü.
- Pflichtfelder: `display_name`, `slug`, `hosting_tier` (t1/t2/t3), `license_status`.
- Ergebnis: neuer Tenant mit eigener `tenant_id`; alle Folge-Objekte erben sie automatisch
  (Create-Inheritance, strenge Isolation `strict_tenant_isolation`).

## 2. Firmen-Admin einladen
- Im Firmen-/Team-UI **Einladung erstellen** (Invite-Link, sha256-Token, Ablauf, single-use).
- Versand:
  - **E-Mail** automatisch, falls SMTP konfiguriert (`services/mailer.py`, Roadmap #26) — sonst
  - **Link manuell** kopieren und sicher übermitteln.
- Lebenszyklus: **Resend** (rate-limited, 429+Retry-After) und **Revoke** verfügbar.

## 3. Firmen-Admin: Onboarding abschliessen
- Admin öffnet Invite-Link → setzt Passwort → **Pflicht-2FA-Enrollment** (TOTP, QR via segno
  oder Secret-Copy-Button) ist erzwungen (Hard-Gate).
- Admin lädt anschliessend seine **Berater** über dasselbe Invite-Flow ein.

## 4. Lizenz / Quota
- `tenants.quotas` setzen (max User / max Mandate). Enforcement: Soft-/Hard-Limits
  (Roadmap #24 — falls noch offen, manuell überwachen).

## 5. Verifikation vor Freigabe (Checkliste)
- [ ] Login + 2FA für Firmen-Admin funktioniert.
- [ ] **Mandantentrennung** stichprobenartig geprüft (Admin sieht nur eigene Firma) —
      automatisiert durch Tenant-Isolation-Tests + CI-Security-Gate abgesichert.
- [ ] Health: `/health/live` (200) + `/health/ready` (200, DB ok).
- [ ] Backup läuft (Scheduler aktiv, letzter Lauf < 24 h).
- [ ] `allow_real_client_data` erst **nach** Compliance-Abschluss auf `true`.

## 6. Laufender Betrieb
- Monitoring/Alerting (Login-Fail-Spikes, Fehlerquote, Latenz — Roadmap #14).
- Audit-Logs mandanten-partitioniert (Roadmap #21).
- Off-Site-Backup + periodischer **Restore-Drill** (Roadmap #15/#109).

## 7. Offboarding / Vertragsende
- Datenexport an die Firma (revDSG Art. 25, `/clients/{id}/data-export`).
- Löschung/Rückgabe inkl. Backups gemäss AVV §4 + Retention.
- Tenant deaktivieren (`license_status`), Zugänge sperren.

---

## Referenzen (Ist-Stand-Tooling)
- `docs/deploy/start-external.ps1` — externer Start (Browser-Hosting/Remote-Test).
- `docs/deploy/Caddyfile`, `docs/deploy/5eyes.service` — TLS-Reverse-Proxy + systemd-Unit.
- `docs/deploy/promote_operator.py` — Operator-/Tenant-Provisionierung.
- Offen (Roadmap): CH-VPS-Setup (#12), Secret-Management (#13), RLS (#9), Promotion-Pfad (#29).
