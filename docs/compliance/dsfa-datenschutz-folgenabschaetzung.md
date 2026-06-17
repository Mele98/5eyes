# Datenschutz-Folgenabschätzung (DSFA) — Vorlage

**Roadmap #18** · Status: Vorlage (vom Betreiber/Verantwortlichen auszufüllen & rechtlich prüfen)
**Stand:** 2026-06-15

> ⚠️ **Kein Rechtsrat.** Bezug: **revDSG/nDSG Art. 22** (Datenschutz-Folgenabschätzung bei
> voraussichtlich hohem Risiko). Bei EU-Betroffenen zusätzlich DSGVO Art. 35. Diese Vorlage
> ist auszufüllen und vor produktivem Echtdaten-Betrieb (T2/T3) durch eine Datenschutz-
> fachperson zu prüfen.

---

## 1. Beschreibung der Bearbeitung
- **Zweck:** Digitale Vermögensberatung (Ist-Analyse, zielbasierte Asset Allocation,
  Monte-Carlo-Projektionen, Vermögensverzehr) für Endkunden von Beratungsfirmen.
- **Datenkategorien:** Stammdaten, Vermögen/Verbindlichkeiten, Cashflows, Lebensziele,
  Risikoprofil. **Möglicherweise besonders schützenswert** (Vorsorge-/Gesundheitsbezug bei
  Lebenserwartung) → Datenminimierung, nur Geburtsjahr/Geschlecht statt Detail-Gesundheit.
- **Betroffene:** Endkunden + Haushalt/Partner.
- **Bearbeitungsumfang:** Speicherung, Berechnung, Visualisierung, PDF-Reports, Backups.

## 2. Notwendigkeit & Verhältnismässigkeit
- Daten sind für eine fundierte, FINMA-konforme Anlageberatung erforderlich
  (Eignungsprüfung, holistische Planung).
- **Datenminimierung:** keine unnötigen Gesundheitsdetails; Lebenserwartung wird aus
  Geburtsjahr + Geschlecht abgeleitet (Geburtsjahr +83 Mann / +85 Frau), nicht aus
  Gesundheitsdaten.

## 3. Risiken für die betroffenen Personen
| Risiko | Bewertung | Massnahme |
|---|---|---|
| Unbefugter Zugriff (extern) | hoch | Pflicht-2FA, TLS, WAF/Rate-Limit, Secret-Management |
| **Mandanten-Übergriff** (Daten anderer Firma) | hoch | `strict_tenant_isolation` (App), geplante Postgres-RLS, Cross-Tenant-404-Guards, CI-Security-Gate |
| Datenverlust | mittel | Verschlüsselte CH-Off-Site-Backups, Restore-Drills |
| Datenabfluss ins Ausland | mittel | CH-Datenstandort vertraglich + technisch (Provider-Wahl) |
| Profilbildung/Zweckentfremdung | mittel | Zweckbindung (AVV), keine Sekundärnutzung, kein Tracking ohne Opt-in |
| Verlust 2FA-Gerät (Lockout) | niedrig | Recovery-Codes (Roadmap #25) |

## 4. Technische & organisatorische Massnahmen
Siehe AVV-Anhang A ([avv-template.md](avv-template.md)). Kern: Pflicht-2FA, harte
Mandantentrennung (mehrschichtig), Verschlüsselung in Transit/at-rest, Audit-Logs,
CH-Datenstandort, Backups + Restore-Drills, Production-Config-Guards.

## 5. Restrisiko & Beurteilung
- Nach Massnahmen: Restrisiko **vertretbar** für T1/T3, **erhöht aber beherrschbar** für T2
  (geteilte Infrastruktur) — Mandantentrennung ist der kritische Kontrollpunkt
  (Defense-in-Depth: App-Filter + RLS + Tests).
- **Konsultation EDÖB** nur falls das Restrisiko trotz Massnahmen hoch bleibt (revDSG Art. 23).

## 6. Überprüfung
DSFA bei wesentlichen Änderungen aktualisieren (neue Datenkategorien, neuer Tier, neue
Unterauftragsverarbeiter, Sicherheitsvorfälle). Mindestens jährlich review.

## Offene technische Voraussetzungen (Roadmap-Verweise)
- Postgres-RLS (#9), per-Tenant-Encryption (#11), Off-Site-Backup (#15),
  Monitoring/Alerting (#14), 2FA-Recovery (#25), externer Pentest (#19).
