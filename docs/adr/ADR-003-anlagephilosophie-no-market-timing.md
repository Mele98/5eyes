# ADR-003: Anlagephilosophie ohne Markt-Timing

- **Status:** Accepted
- **Datum:** 2026-05-20 (formalisiert 2026-06-05)
- **Sprint:** Kerndoktrin — durchgehend gepflegt

## Kontext

Viele Wealth-Tech-Plattformen bieten Live-Marktdaten + automatische
Trigger ("Verkaufs-Signal", "Kaufgelegenheit"). Das suggeriert dass die
Software den Markt schlägt — was empirisch nicht belegt und regulatorisch
gefährlich ist (kann als Anlageempfehlung gelten, FIDLEG-relevant).

Die 5eyes-Beratung folgt einer **regelbasierten, langfristigen**
Philosophie:
- SAA pro Risikoprofil
- Re-Balancing nur bei Eignungsprüfung oder Kunden-Anfrage
- Keine Markt-Reaktion auf Tagesbewegungen

## Entscheidung

Die Software setzt diese Philosophie **technisch** durch:

1. **Keine Auto-Trigger:** Es gibt keinen Cron-Job, keinen Watcher, keinen
   Notification-Endpoint der bei Marktbewegung feuert
2. **Re-Balancing-Vorschläge nur bei Eignungsprüfung:** Die Sub-App
   zeigt SAA-Drift nur im Eignungsprüfungs-Workflow oder auf expliziten
   Kunden-Wunsch
3. **Keine "Markt-Chance"-Sprache:** Glossar (siehe `GLOSSAR.md`)
   verbietet Begriffe wie "jetzt einsteigen", "garantiert",
   "Markt-Chance" — auch im Code-Kommentar, PDF-Text, UI-Label
4. **Marktdaten nur als Bewertungs-Input:** Marktdaten-Pipeline
   (siehe ADR-005) liefert Preise für Portfolio-Bewertung und CMA-
   Updates — niemals als Trigger

## Konsequenzen

**Positiv:**
- Regulatorisch sauber — keine implizite Anlageempfehlung durch UI
- Berater bleibt im Driver-Seat — Software unterstützt, entscheidet nicht
- Klare Software-Grenze: was nicht im Aggregator-Output steht, wird auch
  nicht dem Kunden gezeigt

**Negativ:**
- Verlust gegen Konkurrenz die "Smart Alerts" bietet — bewusster Trade-off
- Berater muss bei Marktstress proaktiv kontakten — kein Pull-Modus

**Konkrete Regeln im Code:**
- `core/scheduler.py` darf keinen Market-Watcher anlegen
- `services/notifications.py` (falls je gebaut) darf nicht auf
  Preisänderungen reagieren
- PDF + Sub-App-Texte werden von Drift-Test
  `test_no_forbidden_customer_facing_phrases` geprüft
- GLOSSAR.md hat eine Verbots-Sektion die in
  `test_glossar_consistency.py` getestet wird

## Ist-Stand-Ergänzung (2026-07-23) — Eignungsprüfungs-Audit wird scharf geschaltet

Punkt 2 der Entscheidung ("Re-Balancing-Vorschläge nur bei Eignungsprüfung")
stand bislang auf einem **blinden** Audit: `services/suitability_audit.py`
(Sprint U-66, 2026-06-03) prüfte pro `AdvisoryLog`-Eintrag ein `duty_type`/
`suitability_check_id`-Feld — beide Spalten existieren auf `AdvisoryLog` gar
nicht, weshalb `audit_mandate_suitability()` **immer** `is_compliant=True`
meldete, unabhängig vom tatsächlichen Zustand.

Umstellung am 2026-07-19 (Commit `8a867f8`, "Option A"): Die Funktion
`audit_mandate_suitability(db, mandate)` prüft jetzt **mandatsbezogen** nach
FIDLEG Art. 10 (Prüfpflicht) + Art. 12 (Eignungsprüfung): existiert ein
aktuelles `RiskAssessment` für das Mandat und ist es nicht älter als
`SUITABILITY_FRESHNESS_MAX_DAYS` (365 Tage, Industriepraxis)? Execution-only-
Mandate (`_mandate_requires_suitability()`) bleiben nach Art. 13 ausgenommen.
Damit ist die Voraussetzung für re-balancing-relevante Eignungsprüfungen
erstmals tatsächlich (statt nur behauptet) auditierbar.

Ergänzend (Commit `6ef4f94`, 2026-07-19): Kunden-Signatur des Risikoprofils
— `POST /mandates/{mandate_id}/risk-profile/sign` (Berater-Fallback,
`routers/profiling.py:338`, setzt `client_signed_method="advisor_recorded"`)
und die Kunden-Portal-Variante (`routers/client_portal.py:116`, setzt
`client_signed_method="portal"`) schreiben beide auf
`RiskAssessment.client_signed_at`/`.client_signed_method`. Die Signatur ist
reine Dokumentation der Bestätigung und verändert `is_compliant` im Audit
nicht — sie beantwortet nur "wann/wie hat der Kunde bestätigt", nicht "ist
das Profil aktuell".
