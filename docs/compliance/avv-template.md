# Auftragsverarbeitungsvertrag (AVV) — Vorlage

**Roadmap #16** · Status: Vorlage (vom Betreiber rechtlich prüfen zu lassen)
**Stand:** 2026-06-15

> ⚠️ **Kein Rechtsrat.** Diese Vorlage strukturiert die Auftragsverarbeitung
> zwischen dem **Betreiber von 5eyes** (Auftragsverarbeiter) und der **nutzenden
> Beratungsfirma** (Verantwortliche). Sie ist vor produktivem Einsatz durch eine
> Datenschutz-/Rechtsfachperson zu prüfen und an den konkreten Hosting-Tier
> anzupassen. Rechtsgrundlage: revDSG/nDSG (CH), bei EU-Kundendaten zusätzlich DSGVO Art. 28.

---

## 1. Parteien und Rollen

- **Verantwortliche** (bestimmt Zweck & Mittel der Bearbeitung): die Beratungsfirma («Mandantin»),
  die 5eyes für die Vermögensberatung ihrer Endkunden nutzt.
- **Auftragsverarbeiter** (bearbeitet im Auftrag): der **Betreiber der 5eyes-Plattform**.

Die Rollenteilung hängt vom Hosting-Tier ab (siehe [ADR-009](../adr/ADR-009-3-tier-hosting-architecture.md)):

| Tier | Hosting | Auftragsverarbeitung |
|---|---|---|
| **T1 Self-Hosted** | Firma betreibt selbst | **Kein AVV nötig** — die Firma ist allein Verantwortliche; Betreiber liefert nur Software |
| **T2 Shared-Cloud (CH)** | Betreiber, mandantengetrennt | **AVV zwingend** — Betreiber verarbeitet Kundendaten in geteilter Infrastruktur |
| **T3 Dedicated** | Betreiber, dedizierte Instanz | **AVV zwingend** — wie T2, zusätzlich Instanz-Isolation |

## 2. Gegenstand und Dauer
Bearbeitung von Personendaten der Endkunden der Mandantin (Stammdaten, Vermögen,
Cashflows, Ziele, Risikoprofil, Anlagestrategie) zum Zweck der digitalen
Vermögensberatung. Dauer = Laufzeit des Lizenz-/Nutzungsvertrags.

## 3. Art der Daten und Kategorien betroffener Personen
- **Datenkategorien:** Identifikationsdaten, Finanz-/Vermögensdaten, Vorsorgedaten,
  Risikoprofil-Antworten. Ggf. **besonders schützenswerte Daten** (Gesundheit nur falls
  für Lebenserwartung/Vorsorge relevant — möglichst vermeiden/aggregieren).
- **Betroffene Personen:** Endkunden der Mandantin und deren Partner/Haushalt.

## 4. Pflichten des Auftragsverarbeiters (Betreiber)
1. Bearbeitung **nur auf dokumentierte Weisung** der Mandantin.
2. **Vertraulichkeit** aller mit der Bearbeitung betrauten Personen.
3. **Technische & organisatorische Massnahmen (TOM)** gemäss Anhang A.
4. **Mandantentrennung**: strikte logische Trennung (App-Level `strict_tenant_isolation`
   + geplante DB Row-Level-Security, siehe [ADR-007](../adr/ADR-007-multi-tenancy-strategy.md)).
5. **Unterauftragsverarbeiter** (Hosting-Provider CH) nur mit vorheriger Genehmigung;
   Liste in Anhang B. Gleichwertige Pflichten werden weitergegeben.
6. **Unterstützung** der Mandantin bei Betroffenenrechten (Auskunft revDSG Art. 25 —
   Endpoint `/clients/{id}/data-export`; Löschung).
7. **Meldung von Verletzungen der Datensicherheit** an die Mandantin **unverzüglich**
   (Ziel: < 24 h nach Kenntnis), mit allen für eine EDÖB-Meldung nötigen Angaben.
8. **Löschung/Rückgabe** aller Daten nach Vertragsende (Wahl der Mandantin), inkl. Backups
   innerhalb der dokumentierten Backup-Retention.
9. **Nachweis** der Einhaltung (Audit-Recht der Mandantin, Audit-Logs, dieses Dokument).

## 5. Datenstandort
Alle produktiven Daten und Backups verbleiben in der **Schweiz** (CH-Rechenzentren).
Kein Transfer ins Ausland ohne separate, dokumentierte Grundlage.

## 6. Unterstützung & Audit
Die Mandantin darf die Einhaltung (auch vor Ort/remote) prüfen oder prüfen lassen.
Der Betreiber stellt Audit-Logs (mandanten-partitioniert, Roadmap #21) bereit.

---

## Anhang A — Technische & organisatorische Massnahmen (TOM)
- Authentifizierung mit **Pflicht-2FA** (TOTP) für Berater-Zugänge.
- Transport: TLS (Let's Encrypt), WAF/Edge-Rate-Limiting (Cloudflare) vor der App.
- **At-rest-Verschlüsselung** (Roadmap #11: per-Tenant-Key-Hierarchie).
- Mandantentrennung App-Level + (geplant) Postgres-RLS.
- **Backups** verschlüsselt, CH-Off-Site (Roadmap #15), dokumentierte Restore-Drills.
- Zugriffs- & Änderungs-Protokollierung (Audit-Log, `request_id`).
- Secret-Management ausserhalb des Codes (Roadmap #13), Production-Guards erzwingen Non-Defaults.
- Monitoring/Alerting inkl. Login-Fail-Spikes (Roadmap #14).

## Anhang B — Unterauftragsverarbeiter (auszufüllen)
| Unterauftragsverarbeiter | Leistung | Standort | Vertrag/AVV |
|---|---|---|---|
| _z. B. CH-Managed-Postgres-Provider_ | DB-Hosting | CH | _Datum_ |
| _z. B. Edge/CDN_ | WAF/DDoS | CH/Edge | _Datum_ |

## Anhang C — Weisungen (auszufüllen)
Standard-Weisung = vertragsgemässe Nutzung der Plattform. Abweichende Einzelweisungen
sind hier zu dokumentieren (Datum, Inhalt, verantwortliche Person).
