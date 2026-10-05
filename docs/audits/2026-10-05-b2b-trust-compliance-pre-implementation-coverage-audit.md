---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "b2b-trust-compliance-pre-implementation-coverage-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "06dbb6ccc537e352367b08dfcbe7125ff70cd56f"
audit_mode: "read_only_audit_inventory_static_code_document_and_test_evidence_review"
audit_mutated_product_code: false
existing_audit_documents_count: 64
scope: "B2B trust, privacy governance, vendor and supply chain, accessibility, privileged access, claims, incident response, resilience and commercial evidence"
decision: "close six missing evidence audits before implementing the B2B trust backlog; obtain owner facts in parallel"
---

# B2B-Trust-/Compliance-Pre-Implementation-Coverage-Audit

## Zweck und Quellenrangfolge

Dieser Audit beantwortet vor der Umsetzung des
[B2B-Trust-/Compliance-/Accessibility-Plans](../compliance/2026-10-05-trust-compliance-accessibility-readiness-plan.md)
drei Fragen:

1. Welche Risiken sind durch die bestehenden 64 Audits bereits belastbar
   untersucht?
2. Welche Themen sind nur durch Vorlagen, Einzeltests oder Absichtserklaerungen
   abgedeckt?
3. Welche eigenstaendigen Audits fehlen, bevor Claude Produktcode oder
   Rechtstext-Platzhalter umsetzt?

Bei Widerspruechen gelten aktueller Produktcode und reproduzierte Tests zuerst,
danach die juengeren fachlichen Audits. Planning-Dokumente, Templates und
Runbooks beweisen keine Umsetzung. Dieses Dokument erteilt keine Rechts-,
FINMA-, Security-, Accessibility- oder Produktionsfreigabe.

## Kurzurteil

**Ja, vor der Umsetzung fehlen wichtige Audits.** Die mathematische und
fachliche Kernlogik ist aussergewoehnlich tief untersucht. Auch Auth,
Tenant-Isolation, Datenlebenszyklus, Releaseartefakte, Kosten, E-Signatur und
Publikationsintegritaet besitzen bereits belastbare Folgeaudits. Der neue
B2B-Trust-Track ist dagegen in sechs Bereichen nur teilweise oder gar nicht
evidenzbasiert:

1. Drittanbieter, Datenabfluesse, Unterauftragsbearbeiter, Lizenzen und SBOM;
2. Joiner/Mover/Leaver, privilegierte Zugriffe, Rezertifizierung und Supportzugriff;
3. Accessibility des vollstaendigen Golden Path und der Kunden-PDFs;
4. Claims, Dark Patterns und kanalgleiche rechtliche/commercial Aussagen;
5. Incident Response, Breach-Entscheidung und praktisch geuebte Resilienz;
6. Privacy-Governance-Abgleich aus Dateninventar, Notice, DSFA, AVV,
   Subprocessor, Retention, DSAR und Loeschung.

Diese sechs Audits sollen vor Produktimplementierung geschlossen werden. Die
Ausarbeitung finaler AGB, Datenschutzerklaerungen, SLA- und Preistexte benoetigt
zusaetzlich reale Betreiber- und Vertragsdaten und darf nicht aus Code erfunden
werden.

## Bestehende Abdeckung

| Domaene | Evidenzstand | Bewertung fuer den neuen Track |
|---|---|---|
| Stochastik, Monte Carlo, Asset Allocation, Ziele und Publikation | zahlreiche reproduzierte Integritaetsaudits bis Kontrollrunde 51 | **tief abgedeckt**, Findings bleiben offen; kein erneuter generischer Audit noetig |
| Tenant, Auth, Sessions, RLS, Secrets und Desktop-Release | Folgeaudits vom 25./26.08.2026 mit konkreten P0/P1 und Reproduktionen | **technisch breit abgedeckt**, aber organisatorischer Access-Lifecycle fehlt |
| DSAR, Loeschung, Retention, Restore-Erasure und Offboarding | `2026-08-26-data-lifecycle-crypto-browser-followup-audit.md` | **technische Luecken belegt**, Governance-/Vertragsabgleich fehlt |
| Kosten, Retrozessionen und Konflikte | `2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md` | **fachlich abgedeckt**, offene Vertrage in Trust-Umsetzung uebernehmen |
| Signatur und Vertragsdokumente | `2026-09-03-contract-document-e-signature-and-signed-publication-integrity-audit.md` | **technisch abgedeckt**, B2B-Vertragstexte und Acceptance-Evidence separat |
| Accessibility | einzelne React-A11y-Tests und statischer Chart-/Fallback-Test | **fragmentiert**, keine Gesamtfreigabe |
| Disaster Recovery | DR-Plan mit RTO/RPO und Restore-Drill-Vorgabe | **Plan vorhanden**, PostgreSQL-Restore und Drillnachweis fehlen |
| DSFA, AVV und FINMA-Outsourcing | Vorlagen in `docs/compliance` | **Vorlage, nicht Freigabe oder Umsetzungsevidence** |
| SBOM, Vendor-/Subprocessor- und Asset-Lizenzen | Fixvertraege in aelteren Audits, keine Releaseartefakte/Register gefunden | **nicht umgesetzt und nicht eigenstaendig auditiert** |

## Neues Findings-Register

### `B2B-COVERAGE-001` – Kein kanonisches Vendor-/Datenabfluss-/Subprocessor-Register

**Prioritaet:** P0 fuer T2/T3, P1 fuer T1

Der Code enthaelt mehrere externe oder optional externe Grenzen: SMTP,
optionales Sentry, Marktdatenprovider, Webhooks, Update-Feed, Offsite-Backup,
Hosting und spaetere Tax-Plugins. `services/telemetry.py` setzt
`send_default_pii=False`, kann aber beliebigen `context` als Sentry-Extras
uebermitteln. Ein Konfigurations-Opt-in ersetzt keine Datenklassifikation,
Vertrags-, Standort-, Transfer- oder Subprocessor-Evidence. Das
FINMA-Outsourcing-Template fordert eine Unterauftragsbearbeiterliste, eine
kanonische Liste wurde jedoch nicht gefunden.

**Auditvertrag:** Jede ausgehende Verbindung und jeder Anbieter wird aus Code,
Konfiguration, Build und Betrieb inventarisiert. Pro Eintrag sind Zweck,
Datenklassen, Trigger, Ziel/Region, Transport, Credential, Retention, Vertrag,
AVV/DPA, Subprocessor, Owner, Exit und T1/T2/T3-Anwendbarkeit zu belegen. Eine
Netzwerk-Allowlist und Tests muessen nicht inventarisierte Ziele blockieren.

### `B2B-COVERAGE-002` – Lizenz-/Asset-Provenienz und Release-SBOM fehlen

**Prioritaet:** P0 vor Distribution

Das Electron-Paket steht auf `"license": "UNLICENSED"`; gebuendelt sind
mindestens Chart.js, ein Country-Outline-Datensatz, Inter-,
Cormorant-Garamond-Schriften, Icons und zahlreiche Designbilder. Im Repository
wurde keine `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES`- oder aequivalente
Provenienzdatei gefunden. Aeltere Releaseaudits verlangen SBOM, Digest,
Signatur und Attestation, aber ein erzeugtes SBOM-/Notice-Artefakt wurde nicht
gefunden. `UNLICENSED` beschreibt nur die eigene Paketpublikation und beweist
keine Nutzungsrechte an Drittassets.

**Auditvertrag:** Vollstaendige Dependency- und Asset-BOM mit Quelle, Version,
Hash, Lizenz, Copyright, Modifikationen, Attribution, Redistribution-Pflichten
und Verwendung im finalen Installer. Unknown-Provenance-Assets blockieren den
Build. CycloneDX/SPDX-SBOM, Third-Party Notices, Digest und Signatur muessen auf
dasselbe gepruefte Releaseartefakt zeigen.

### `B2B-COVERAGE-003` – Operativer Identity- und Privileged-Access-Lifecycle fehlt

**Prioritaet:** P1, P0 bei produktivem T2/T3-Operatorzugriff

Der Produktcode besitzt Rollen, Aktivierung, Einladungen, `last_login_at`,
2FA und `super_admin`. Die vorhandenen Security-Audits pruefen viele
Autorisierungsgrenzen. Fuer Joiner/Mover/Leaver, periodische
Zugriffsrezertifizierung, ruhende Accounts, SoD, Notfall-/Break-Glass-Zugriff,
Support-Session-Freigabe, zeitliche Begrenzung privilegierter Rechte und
regelmaessige Super-Admin-Pruefung wurde jedoch kein kanonischer Vertrag oder
Audit gefunden.

**Auditvertrag:** Rollen-/Berechtigungsmatrix aus realen Endpoints ableiten;
Erstellung, Rollenaenderung, Tenant-Wechsel, Deaktivierung und Ausscheiden
End-to-End pruefen. Privilegierte Aktionen benoetigen Actor, Anlass, Freigabe,
Zeitfenster, Tenant, Auditspur und Rezertifizierungsdatum. Verwaiste oder
ueberfaellige Rechte muessen sichtbar und sperrbar sein.

### `B2B-COVERAGE-004` – Accessibility ist nur punktuell, nicht als Golden Path belegt

**Prioritaet:** P1

Positiv sind React-A11y-Tests sowie der statische Test fuer Chart-Labels und
Screenreader-Tabellen. Sie pruefen jedoch nicht den gesamten Ablauf
`Login -> Kunde -> Mandat -> Risikoprofil -> Ziele -> Asset Allocation ->
Review -> PDF`. Im Monolith existieren weiterhin klickbare `div.qcb`-Elemente
ohne native Tastatursemantik. Ein WCAG-2.2-AA-Bericht, manueller
Screenreader-/Keyboard-Nachweis, Kontrast-/Reflow-Gate, Accessibility Statement
oder PDF/UA-/Tagged-PDF-Nachweis wurde nicht gefunden.

**Auditvertrag:** Automatisierte und manuelle Matrix je Hauptworkflow,
Light/Dark Theme, Zoom/Reflow, Tastatur/Fokus, Screenreader, Status/Fehler,
Charts und PDF. Jeder Befund bekommt reproduzierbaren Schritt, WCAG-Kriterium,
Schwere, betroffene Rolle und konkreten Fix-/Regressionstest.

### `B2B-COVERAGE-005` – Claims und Dark Patterns besitzen kein Register

**Prioritaet:** P0 fuer Rechts-/Konformitaetsclaims, sonst P1

Mehrere sichtbare oder publizierte Texte verwenden starke Aussagen wie
`FINMA-konforme Eignungspruefung`, `FINMA-konformes PDF` und
`RISK BUDGET VALIDATED`. Gleichzeitig dokumentieren die aktuellen Audits offene
Release- und Risikobudgetluecken. Ein Disclaimer oder der interne Begriff
`FINMA-bewusst` ist kein Nachweis fuer eine konkrete Konformitaetsbehauptung.
Ein zentrales Claim-Register, Evidence-Owner, Ablaufdatum und Dark-Pattern-
Review wurden nicht gefunden.

Besonders kritisch ist ein bereits belegter Dokumentationsdrift:
`docs/compliance/finma-outsourcing-anzeige.md` behauptet, Datenexport und
Loeschung seien nach revDSG Art. 25 bereits umgesetzt. Der spaetere
Datenlebenszyklus-Audit belegt dagegen offene P1 in Vollstaendigkeit,
Fail-Closed-Semantik, Kinddaten, Offboarding und Restore-Erasure.

**Auditvertrag:** Alle Kunden-, Sales-, UI-, PDF-, Vertrag-, Website- und
Runbook-Claims erfassen. Jede starke Aussage benoetigt exakten Scope,
Rechts-/Fachowner, Evidenzpfad, Gueltigkeitsdatum und erlaubte Varianten.
Automatisierte Phrase-Gates helfen, ersetzen aber kein fachliches Signoff.
Veraltete Templates duerfen nicht als Kunden- oder Compliance-Evidence
ausgeliefert werden.

### `B2B-COVERAGE-006` – Incident Response und Resilienz sind geplant, nicht geuebt

**Prioritaet:** P0 fuer T2/T3, P1 fuer T1

Der DR-Plan definiert RTO/RPO und verlangt quartalsweise Restore-Drills. Seine
Protokolltabelle ist leer, die Kontaktkette ist auszufuellen, PostgreSQL besitzt
keinen belegten Restorepfad und Offsite-Backup ist nicht aktiviert. Ein
vollstaendiger Breach-Entscheidungsbaum, forensische Beweissicherung,
Kommunikationsvorlagen, Subprocessor-Eskalation und gemeinsam geuebtes
Ransomware-/Datenleck-/Vendor-Ausfall-Szenario wurden nicht gefunden.

**Auditvertrag:** Code, Konfiguration, Runbooks und reale Operations-Evidence
abgleichen. Mindestens Backupverlust, Datenkorruption, Tenant-Leak,
Credential-Kompromittierung, Ransomware, Provider-Ausfall und fehlerhaftes
Update durchspielen. RTO/RPO, Rollen, Kontakte, Meldeentscheidung,
Betroffenen-/Kundeninformation und Recovery-/Erasure-Reconciliation messen.

### `B2B-COVERAGE-007` – B2B-Rechtstexte benoetigen reale Owner-Fakten

**Prioritaet:** P0 vor verbindlichem Angebot, externer Input erforderlich

Der Code kann Betreiberidentitaet, Rechtsform, Handelsregister-/UID-/MWST-Daten,
Vertragspartner, Gerichtsstand, Supportzeiten, SLA, Preise, Laufzeit,
Kuendigung, Service Credits, Haftungsentscheidungen, Versicherungsdeckung und
Beschwerde-/Ombudsweg nicht verlaesslich ableiten. Ohne diese Fakten waeren
AGB, Privacy Notice, Impressum/Anbieterangaben und SLA nur plausible, aber
potenziell falsche Mustertexte.

**Loesungsvertrag:** Eine Owner-Facts-Vorlage wird ausgefuellt und von
Geschaeftsleitung/Recht freigegeben. Erst danach werden Rechtstextentwuerfe
erstellt. Im Repository bleiben sie bis zur Freigabe klar als `DRAFT – NOT
APPROVED` markiert; Code oder KI darf keine fehlenden Firmendaten erfinden.

## Was bewusst kein neuer Audit ist

- Cookie-Banner: erst relevant, wenn der Vendor-/Storage-Audit optionale
  Tracker oder entsprechende Webtechnologien bestaetigt.
- Consumer-Widerruf, Kinder-Consumer-Consent und B2C-Checkout: ausserhalb des
  bestaetigten B2B-Scopes.
- Newsletter-Abmeldung: erst bei Marketing-E-Mails; Invite und Reset bleiben
  transaktional.
- Fake Reviews: keine Review-/Testimonial-Funktion gefunden; Aktivierung
  benoetigt einen neuen Triggeraudit.
- PCI DSS, PSD2/Open Banking und DORA: erst bei realem Payment-,
  Bankkonto-/API- oder EU-Regulated-Trigger.
- Weitere generische Optimizer-Audits: die offenen konkreten Kernfindings sind
  bereits wesentlich praeziser und duerfen nicht durch einen neuen
  Sammelaudit verwischt werden.

## Verbindliche Audit-Reihenfolge vor Umsetzung

| Runde | Audit | Warum zuerst | Hauptoutput fuer Claude |
|---:|---|---|---|
| 1 | Third-Party/Data-Egress/License/SBOM | Grundlage fuer Notice, AVV, DSFA, Security und Distribution | kanonisches Vendor-/Egress-/Asset-Inventar, konkrete Findings und Build-/Runtime-Gates |
| 2 | IAM Lifecycle/Privileged Access/Support | schliesst die organisatorische Luecke hinter den technischen Rollenchecks | Rollenmatrix, JML-/PAM-/Rezertifizierungsvertrag und negative Tests |
| 3 | Accessibility Golden Path/PDF | Nutzer- und Kundenartefakte koennen danach gezielt statt punktuell korrigiert werden | WCAG-Matrix, reproduzierte Befunde, priorisierte Fixpakete und manuelle Testskripte |
| 4 | Claims/Dark Patterns/Commercial Surfaces | verhindert, dass Rechtstexte und UI offene technische Findings ueberversprechen | Claim-Register, verbotene/bedingte Formulierungen, Evidence-Bindung und UX-Fairness-Funde |
| 5 | Incident/Breach/Resilience | prueft, ob dokumentierte Kontrollen im Ernstfall wirklich funktionieren | Szenarien, Messwerte, Luecken, Owner-/Kontakt-/Melde- und Drillvertrag |
| 6 | Privacy Governance Reconciliation | verwendet die Ergebnisse 1 bis 5 und reconciliert sie mit DSFA/AVV/Notice/DSAR/Retention | vollstaendige Evidence-Matrix und freigabefaehige Inputs fuer juristische Pruefung |

Owner-Fakten fuer `B2B-COVERAGE-007` koennen parallel gesammelt werden. Sie
duerfen die read-only Audits 1 bis 5 nicht blockieren.

## Claude-Handoff-Regeln

Claude soll vor jeder Umsetzung:

1. diesen Coverage-Audit und den B2B-Readiness-Plan lesen;
2. nur die jeweils aktive Auditrunde bearbeiten, keine generischen
   Rechtstexte oder Cookie-/B2C-Funktionen vorziehen;
3. bestehende Findings per ID referenzieren statt sie umzubenennen;
4. zuerst rote/negative Nachweise und kanonische Datenvertraege definieren;
5. technische Umsetzung, Policy, Vertrag, Auditspur, Test und Betrieb als
   zusammengehoerige Abnahmekette behandeln;
6. Rechts-, FINMA-, ISO-, SOC-2-, WCAG- oder Security-Konformitaet nie aus
   einem gruenen Einzeltest ableiten;
7. keine fremden oder vorbestehenden Worktree-Aenderungen anfassen.

## Selbst-Audit und Nachweisgrenzen

- Produktcode veraendert: **nein**
- Tests veraendert oder ausgefuehrt: **nein**; diese Runde war ein
  read-only Evidenz- und Coverage-Audit
- Quellen: alle 64 Auditdateien als Inventar, selektive Volltexte der
  einschlaegigen Folgeaudits, aktuelle Compliance-/DR-/Signing-/Update-Dokumente,
  Dependency-Manifeste, Netzwerk-/Provider-/Role-Surfaces und vorhandene
  Accessibility-Tests
- Nicht behauptet: Vollstaendigkeit externer Betriebs-, Vertrags-, Hosting-,
  Personal- oder Versicherungsnachweise ausserhalb des Repositories
- Ergebnis: sechs fehlende interne Auditrunden plus ein externer Owner-Facts-
  Block sind vor der eigentlichen Trust-Implementierung transparent geplant
