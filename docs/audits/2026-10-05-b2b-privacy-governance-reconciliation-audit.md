---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "b2b-privacy-governance-reconciliation-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core / 5eyes"
audited_repository_head: "<siehe git log dieser Branch — Reconciliation ueber die Rounds 1-5 plus bestehende Audits, kein eigener neuer Code-Scan>"
audit_mode: "read_only_synthesis_of_rounds_1_5_plus_existing_privacy_lifecycle_audits"
audit_mutated_product_code: false
scope: "Reconciliation von Dateninventar, Notice, DSFA, AVV, Subprocessor, Retention, DSAR und Loeschung ueber alle fuenf vorherigen B2B-Trust-Runden sowie die bestehenden Datenlebenszyklus-/Kosten-/Signatur-Audits"
---

# B2B-Privacy-Governance-Reconciliation-Audit (Runde 6)

## Zweck

Dies ist Runde 6 der im
[Pre-Implementation-Coverage-Audit](2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md)
festgelegten Reihenfolge. Sie reconciliert die Ergebnisse der Runden 1-5
(Vendor/Egress/Lizenz/SBOM, IAM-Lifecycle, Accessibility, Claims/Dark-Patterns,
Incident/Resilience) mit den bestehenden Datenschutz-Dokumenten
(`dsfa-datenschutz-folgenabschaetzung.md`, `avv-template.md`,
`finma-outsourcing-anzeige.md`) und dem bereits bestehenden
[Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md).

Dieses Dokument erstellt **keine** neue Rechts-, FINMA- oder Datenschutz-Freigabe.
Es stellt dar, wo die fuenf Vorrunden und die bestehenden Audits **zusammenpassen**
und wo sie sich **widersprechen** — als Grundlage fuer die juristische Pruefung,
nicht als Ersatz dafuer.

## Kurzurteil

Die fuenf Vorrunden bestaetigen und verschaerfen exakt die Luecken, die
`dsfa-datenschutz-folgenabschaetzung.md` und `avv-template.md` bereits als
unausgefuellte Vorlagen offen lassen. Keine der fuenf Runden widerlegt die
bestehenden P1-Funde aus dem Datenlebenszyklus-Audit (`PRIV-001/002/004/005`);
alle fuenf erweitern sie um bislang nicht dokumentierte Dimensionen (externe
Vendoren, IAM, Accessibility, Claims, Incident-Prozess). Ein einziger,
bereits vor dieser Runde bekannter Befund ist besonders kritisch, weil er
**Dokumentations-Drift gegenueber einer bereits behoerdenrelevanten Anzeige**
darstellt, nicht nur eine technische Luecke:

> `docs/compliance/finma-outsourcing-anzeige.md` behauptet, DSAR-Export und
> Loeschung seien nach revDSG Art. 25 bereits umgesetzt. Der tatsaechliche
> Code-Stand (Datenlebenszyklus-Audit, `PRIV-001/002/004/005`) widerlegt das:
> Export ist unvollstaendig, Tenant-/User-Offboarding fehlt, Restore kann
> geloeschte Personen reaktivieren. Diese Anzeige darf in ihrer aktuellen Form
> nicht an eine Behoerde oder einen Kunden weitergegeben werden.

## Reconciliation-Matrix

| Governance-Baustein | Bestehender Stand | Verschaerfung/Ergaenzung durch Runde 1-5 | Netto-Status |
|---|---|---|---|
| **Dateninventar / Bearbeitungsverzeichnis** | `CLIENT_DATA_STORAGE_AND_PROCESSING.md` deckt Kerndaten (Vermoegen, Ziele, Risikoprofil) ab | Runde 1 fand 18 externe Vendor-/Egress-Punkte (Marktdaten-Provider, SMTP, Sentry, Webhooks, Offsite-Backup, Auto-Update), die in KEINEM bestehenden Dateninventar erscheinen | **Luecke bestaetigt und erweitert** — Inventar ist unvollstaendig, nicht nur unfertig |
| **Privacy Notice** | Keine produktionsfertige Notice gefunden (TRUST-02, offen) | Keine neue Evidenz aus Runde 1-5, aber Runde 1's Vendor-Liste ist die fehlende Grundlage fuer eine korrekte Notice (Empfaenger-/Auftragsbearbeiter-Sektion kann ohne sie nicht geschrieben werden) | **Blockiert durch Runde 1**, bis Vendor-Register owner-geprueft ist |
| **DSFA** | `dsfa-datenschutz-folgenabschaetzung.md`: Status "Vorlage, auszufuellen" (eigener Status-Header, verifiziert Zeile 3) | Runde 1-5 liefern zusaetzliche Risiken, die die DSFA-Risikotabelle heute NICHT enthaelt: externe Vendor-Flaechen (Runde 1), IAM-Segregation-of-Duties-Luecken (Runde 2: `IAM-SOD-001`, `IAM-JML-002`), fehlende Incident-Eskalationskette (Runde 5: Kontaktkette ist woertlich "auszufuellen") | **DSFA muss materiell erweitert, nicht nur unterschrieben werden** |
| **AVV / Subprocessor-Register** | `avv-template.md` existiert als Vorlage; FINMA-Anzeige verspricht Subprocessor-Liste (Zeile 62), liefert aber nur einen Platzhalter (Zeile 53, verifiziert durch Runde 1) | Runde 1 identifiziert die REALEN Subprocessor-Kandidaten (SMTP-Host, Offsite-Backup-Ziel, optionaler Sentry-Betreiber, 10 Marktdaten-Provider) — das ist die fehlende Faktengrundlage fuer das Register | **Faktengrundlage jetzt vorhanden (Runde 1), Vertragsabschluss/Owner-Eintrag bleibt offen** |
| **Datenminimierung** | DSFA nennt Grundsatz (Geburtsjahr statt Gesundheitsdetails) | Keine Gegenevidenz aus Runde 1-5 | **Unveraendert, als Positivkontrolle zu erhalten** |
| **DSAR / Betroffenenrechte** | `PRIV-002` (Datenlebenszyklus-Audit): Export unvollstaendig und fail-soft | Keine neue Runde hat DSAR direkt erneut auditiert (ausserhalb Scope 1-5), aber Runde 4 bestaetigt den Drift zur FINMA-Anzeige, der DSAR als "umgesetzt" behauptet | **`PRIV-002` bleibt die massgebliche technische Quelle; Runde 4 bestaetigt den Publikations-/Claim-Fehler darueber** |
| **Loeschung / Offboarding / Restore-Erasure** | `PRIV-001`, `PRIV-004`, `PRIV-005` (Datenlebenszyklus-Audit): Tombstone unzureichend, kein Tenant-/User-Offboarding, Backup kann geloeschte Daten reaktivieren | Runde 2 (IAM) bestaetigt zusaetzlich: `update_user` deaktiviert keine stale `ClientLogin`-Zeile beim Rollenwechsel — ein eng verwandter, aber bisher nicht dokumentierter Teilaspekt von unvollstaendigem Offboarding. Runde 5 bestaetigt: Restore-Drill laeuft nur gegen SQLite-Sandbox, nie gegen reale Postgres-Infrastruktur — ein geloeschter Datensatz-Restore wurde nie in der Zielinfrastruktur verifiziert | **`PRIV-001/004/005` bleiben offen; Runde 2 und 5 liefern zusaetzliche, bisher nicht gezaehlte Facetten derselben Fehlerklasse (keine neue ID, siehe unten)** |
| **Retention / Legal Hold** | `PRIV-003` (Datenlebenszyklus-Audit): dokumentierte 10 Jahre vs. physische 90-Tage-Loeschung widersprechen sich | Keine neue Evidenz aus Runde 1-5 | **Unveraendert offen** |
| **Datenschutzverletzungsprozess** | DSFA nennt Massnahmen, aber kein operativer Prozess | Runde 5 bestaetigt: kein eigenstaendiges Incident-Runbook existiert; einziger Satz dazu steht im AVV-Template (Meldeziel <24h an EDOeB), ohne Rollen, Kontakte, Eskalation oder Beweissicherung | **Deutlich konkretisiert: nicht "unvollstaendig", sondern praktisch nicht vorhanden ausserhalb eines Vertragssatzes** |
| **Accessibility als Grundrechts-/Diskriminierungsrisiko** | Nicht Teil der DSFA (Datenschutz-DSFA deckt Accessibility nicht ab) | Runde 3 liefert eigenstaendige, schwere Befunde (61 interaktive Elemente ohne Tastatursemantik, FINMA-Fragebogen ohne native Formularelemente) | **Eigenstaendiges Trust-Risiko, nicht Teil der DSFA-Kette, aber Teil der B2B-Vertrauensgrundlage insgesamt** |
| **Claims/Dark-Patterns als Fairness-Risiko** | Nicht Teil der DSFA | Runde 4 bestaetigt den konkreten Dokumentations-Drift (FINMA-Anzeige vs. PRIV-Funde) als wichtigsten Einzelbefund dieser gesamten Reconciliation | **Siehe Kurzurteil oben — der schwerwiegendste uebergreifende Fund** |

## Keine neue Finding-ID fuer bereits bestehende Funde

Dieses Dokument vergibt bewusst **keine neuen IDs** fuer `PRIV-001/002/003/004/005`
(Datenlebenszyklus-Audit) — sie bleiben die massgebliche Quelle. Es referenziert
sie nur und ordnet die neuen Rounde-1-5-Funde (`VENDOR-EGRESS-001..004`,
`FINMA-SUBPROCESSOR-001`, `ASSET-LICENSE-001..004`, `SBOM-001`,
`IAM-JML-001/002`, `IAM-DORMANT-001`, `IAM-SOD-001`, `IAM-BREAKGLASS-001`,
`IAM-PAM-001`, `IAM-SUPPORT-001`, `IAM-RECERT-001`, `A11Y-GP-001`,
`A11Y-FORM-001/002`, `A11Y-ESIGN-001`, `A11Y-CHART-001`, `A11Y-PDF-001`,
`A11Y-REFLOW-001`, `A11Y-STATEMENT-001`, `CLAIM-REGISTER-001..003`,
`CLAIM-DRIFT-001`, `DARKPATTERN-003`, `IR-DRILL-001`, `IR-PG-RESTORE-001`,
`IR-OFFSITE-001`, `IR-DRP-SCOPE-001`, `IR-ESCALATION-CONTACT-001`,
`IR-BREACH-PROCESS-001`, `IR-RANSOMWARE-001`, `IR-VENDOR-OUTAGE-001`,
`IR-CREDENTIAL-COMPROMISE-001`, `IR-TENANT-LEAK-CONTAINMENT-001`,
`IR-MONITORING-001`, `IR-PENTEST-001`) diesen bestehenden Verträgen zu.

## Was diese Reconciliation NICHT leistet

- Keine rechtliche Einordnung, ob die aktuelle FINMA-Anzeige in ihrer Form
  einreichbar/zustellbar ist — das ist eine Entscheidung fuer
  Geschaeftsleitung/Recht.
- Keine neue DSFA-Version — die Reconciliation-Matrix oben ist der
  **Input** fuer eine materielle DSFA-Ueberarbeitung, nicht deren Ersatz.
- Keine Owner-Fakten fuer Vendor-Vertraege, Subprocessor-Eintraege oder
  SLA-Zeiten — diese bleiben `B2B-COVERAGE-007` und damit explizit fuer das
  Projektende vorgemerkt (User-Entscheidung).
- Keine Aussage, dass die Runden 1-5 vollstaendig sind — sie sind read-only
  Stichproben-/Vollinventuraudits nach bestem Wissen der jeweiligen Runde,
  keine zertifizierte Pruefung.

## Empfohlene naechste Schritte (unverbindlich, fuer Owner-Entscheidung)

1. **Sofort korrigierbar ohne Rechts-/Geschaeftsentscheidung** (technische
   Implementierungsarbeit, siehe separate Fix-Runde):
   - `IAM-JML-002`: `update_user` soll beim Rollenwechsel weg von `client` die
     zugehoerige `ClientLogin`-Zeile deaktivieren.
   - `A11Y-GP-001`/`A11Y-FORM-001`/`A11Y-ESIGN-001`: konkrete Tastatur-/ARIA-
     Nachruestung der schwersten Golden-Path-Elemente (Stepper, FINMA-
     Fragebogen, E-Signatur) — bereits etabliertes Muster (`tabindex`+`role`)
     existiert an anderer Stelle im selben File.
   - `CLAIM-REGISTER-002`: die rein dekorative "RISK BUDGET VALIDATED"-
     Splashanzeige widerspricht einem noch offenen Release-Hold-Finding;
     Entschaerfung (Text entfernen oder an echten Zustand binden) ist eine
     technische Korrektur, keine Rechtsfrage.
2. **Benoetigt Owner-/Rechts-Entscheidung vor Umsetzung:**
   - Ob und wie die FINMA-Anzeige korrigiert/zurueckgezogen wird, bis
     `PRIV-001/002/004/005` tatsaechlich geschlossen sind.
   - Finale DSFA-/AVV-Inhalte inklusive der neuen Vendor-/Subprocessor-Fakten.
   - Scope-Entscheid fuer `B2B-COVERAGE-007` (Owner-Facts fuer Rechtstexte) —
     bereits auf Projektende vertagt.

## Selbst-Audit und Nachweisgrenzen

- Produktcode veraendert: **nein** (reine Synthese bestehender Dokumente)
- Diese Runde hat keine neuen Code-Stellen selbst geprueft, sondern ausschliesslich
  die Findings-Register der Runden 1-5 sowie die realen Statustexte von
  `dsfa-datenschutz-folgenabschaetzung.md` (Zeile 3, direkt gelesen) und
  `avv-template.md` referenziert.
- Nicht behauptet: Vollstaendigkeit der Reconciliation ueber Themen hinaus, die
  in Runde 1-5 tatsaechlich untersucht wurden.
