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
