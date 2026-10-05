---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "b2b-vendor-data-egress-license-sbom-inventory-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "5eyes"
branch: "codex/b2b-vendor-egress-license-sbom-audit"
audited_repository_head: "8dfd6cc13a7869e1996331e5d226551fc441a6ee"
prior_meta_audit_path: "docs/audits/2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md"
prior_meta_audit_findings_covered: ["B2B-COVERAGE-001", "B2B-COVERAGE-002"]
related_readiness_plan_path: "docs/compliance/2026-10-05-trust-compliance-accessibility-readiness-plan.md"
audit_mode: "read_only_static_code_config_dependency_metadata_and_font_binary_inventory_review"
audit_mutated_product_code: false
audit_mutated_tests: false
audit_mutated_config: false
scope: "jede ausgehende/externe Verbindung des Produktcodes, Lizenz-/Provenienzstatus aller gebuendelten Drittanbieter-Assets, Abwesenheit eines Netzwerk-Allowlist-Tests, Abwesenheit eines kanonischen Subprocessor-Registers"
release_decision: "not_applicable_inventory_audit"
findings_count: 10
---

# B2B-Vendor-/Datenabfluss-/Lizenz-/SBOM-Inventaraudit

## Geltung und Quellenrangfolge

Dieser Audit ist **Runde 1** der im
[B2B-Trust-/Compliance-Pre-Implementation-Coverage-Audit](2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md)
festgelegten Reihenfolge und schliesst dessen Findings `B2B-COVERAGE-001`
(Vendor-/Datenabfluss-/Subprocessor-Register) und `B2B-COVERAGE-002`
(Lizenz-/Asset-Provenienz und Release-SBOM) ab, indem er die dort nur
behauptete Lage selbst reproduziert und mit exakten Repository-Belegen
unterlegt. Er ersetzt keine rechtliche, FINMA-aufsichtsrechtliche oder
Security-Freigabe und erteilt keine.

Bei Widersprüchen gelten aktueller Produktcode und reproduzierte Befunde
zuerst, danach dieser Audit, danach der Coverage-Audit. Dieser Audit hat
**keinen Produktcode, keine Tests und keine Konfiguration verändert** — er
ist reines Lesen, Grep, statische Auswertung von `package-lock.json` und
binäres Auslesen der `name`-Tabelle der gebündelten TTF-Schriften.

## Kurzfazit

Der Code enthält **mindestens 15 unterschiedliche ausgehende/externe
Verbindungsarten** zu mindestens 13 verschiedenen Drittanbieter-Domains bzw.
-Mechanismen (SMTP, optionales Sentry, zehn Marktdaten-/Referenzdaten-Hosts,
zwei Opt-in-Webhooks, Offsite-Backup via rsync/SSH und ein Electron-
Update-Feed). Für **keinen** davon existiert im Repository ein kanonisches
Eintrag mit Datenklassifikation, Vertrag, Subprocessor-Status oder Exit-Pfad.
`docs/CLIENT_DATA_STORAGE_AND_PROCESSING.md` erwähnt keinen einzigen dieser
Hosts. `docs/compliance/finma-outsourcing-anzeige.md` fordert in Abschnitt 5
eine „Liste Unterauftragsverarbeiter“, enthält selbst aber nur eine
unausgefüllte Platzhalterzeile (`_CH-Hosting-Provider, …_`). Ein Test, der
ausgehende Netzwerkziele gegen eine Allowlist prüft, wurde **nicht
gefunden**.

Auf der Lizenzseite ist die Lage gemischt: Die gebündelten Fonts (Inter,
Cormorant Garamond) sind bei direkter Prüfung der TTF-`name`-Tabelle
tatsächlich korrekt SIL-OFL-1.1-lizenziert und mit Copyright/Designer/
Lizenztext im Binary selbst dokumentiert. Chart.js v4.4.1 trägt im
Dateikopf selbst einen MIT-Lizenzhinweis. Der Natural-Earth-
Länderumriss-Datensatz ist im Dateikopf selbst als „public domain“
deklariert. Alle drei liegen aber **ausserhalb** jeder maschinenlesbaren
Lizenzerfassung: Chart.js und die Länderumrisse sind statische
`vendor/`-Dateien ohne npm-Eintrag, die Fonts sind Binärdateien ohne
Repository-Metadaten-Pendant. `5eyes-electron/package.json` trägt
`"license": "UNLICENSED"` — das betrifft nachweislich nur das eigene
Root-Paket (per `package-lock.json` eindeutig identifizierbar), nicht die
425 übrigen npm-Pakete, die alle ein Lizenzfeld im Lockfile tragen. Für die
23 Python-Abhängigkeiten in `requirements.txt` existiert **keine**
vergleichbare Lizenzerfassung irgendwo im Repository. Keine `LICENSE`-,
`NOTICE`-, `THIRD_PARTY_NOTICES`-, SPDX- oder CycloneDX-Datei wurde
irgendwo im Repository gefunden; keiner der Build-Skripte
(`pack`, `dist:win`, `dist:mac`, `dist:linux`) erzeugt ein SBOM-Artefakt.

## Findings-Register

| ID | Priorität | Status | Thema |
|---|---:|---|---|
| `VENDOR-EGRESS-001` | P0 | offen | Kein kanonisches Vendor-/Datenabfluss-Register für die mindestens 13 gefundenen externen Verbindungen |
| `VENDOR-EGRESS-002` | P1 | offen | Kein Test erzwingt eine Allowlist für ausgehende Netzwerkziele |
| `VENDOR-EGRESS-003` | P1 | offen | Electron-Update-Feed zeigt auf eine nicht-reale Platzhalter-Domain, Mechanismus selbst ist aktivierbar und auto-installierend |
| `VENDOR-EGRESS-004` | P2 | offen | Sentry-Telemetrie kann beliebigen `context` als Extras senden; Mechanismus aktuell ohne produktiven Call-Site, aber scharf verdrahtet |
| `FINMA-SUBPROCESSOR-001` | P0 (für T2/T3) | offen | FINMA-Outsourcing-Vorlage fordert Subprocessor-Liste, enthält nur unausgefüllten Platzhalter; kein Register sonst im Repository |
| `ASSET-LICENSE-001` | P1 | teilweise offen | `package.json` `UNLICENSED` betrifft nur das Root-Paket; 425 npm-Drittpakete tragen Lockfile-Lizenzmetadaten, aber kein aggregiertes Notices-Artefakt |
| `ASSET-LICENSE-002` | P2 | geklärt (gutartig), aber nicht erfasst | Chart.js v4.4.1 MIT, Natural-Earth-Länderumrisse public domain — beide selbstdokumentiert im Dateikopf, aber ausserhalb jeder Lizenzerfassung (kein npm-Eintrag) |
| `ASSET-LICENSE-003` | P2 | geklärt (gutartig), aber nicht erfasst | Inter + Cormorant Garamond via TTF-`name`-Tabelle verifiziert SIL OFL 1.1, korrekt attribuiert im Binary, aber nicht in einem Repository-Notices-Dokument reproduziert |
| `ASSET-LICENSE-004` | P2 | offen | 22 UUID-benannte Bilder in `docs/design/` ohne jede Provenienz-/Lizenzangabe; nicht referenziert von Produktcode, daher nicht im Distributionsscope, aber ungeklärt |
| `SBOM-001` | P0 (vor Distribution) | offen | Keine `LICENSE`/`NOTICE`/`THIRD_PARTY_NOTICES`/SPDX/CycloneDX-Datei im Repository; kein Build-Skript erzeugt ein SBOM; Python-Abhängigkeiten ohne jede Lizenzerfassung |

## Repository-Belege auf dem auditierten Head

### Vendor-/Egress-Inventar (Codeanker)

| # | Vendor/Mechanismus | Zweck | Trigger/Gate | Codeanker |
|---:|---|---|---|---|
| 1 | SMTP (beliebiger konfigurierter Host) | Einladungs-/Onboarding-Mail (aktuell einzige Mail-Art) | `smtp_enabled` + `smtp_host` + `smtp_from` gesetzt, sonst Fallback Link-Copy | `5eyes-backend/services/mailer.py:52-78`; Settings `5eyes-backend/config.py:337-344` |
| 2 | Sentry (`sentry.io` oder selbstgehostet, je DSN) | Exception-/Message-Telemetrie | `telemetry_enabled` + `telemetry_dsn` gesetzt + `sentry-sdk` installiert | `5eyes-backend/services/telemetry.py:44-98`; Settings `5eyes-backend/config.py:217-221` |
| 3 | Stooq (`stooq.com`) | Tages-/Rangekurse | immer aktiv (kein Opt-in-Flag im Provider selbst) | `5eyes-backend/services/market_data/providers/stooq_provider.py:7-34`; zweiter Call-Pfad `5eyes-backend/price_updater.py:209` |
| 4 | Twelve Data (`api.twelvedata.com`) | Kursdaten (Fallback-Provider) | Provider-Registrierung in `factory.py`, API-Key-Konfiguration | `5eyes-backend/services/market_data/providers/twelvedata_provider.py:8-30`; `5eyes-backend/services/twelvedata_client.py:14` |
| 5 | Alpha Vantage (`www.alphavantage.co`) | Kursdaten (Fallback-Provider) | wie oben | `5eyes-backend/services/market_data/providers/alphavantage_provider.py:6-39,93-95` |
| 6 | OpenFIGI (`api.openfigi.com`) | ISIN/FIGI-Mapping | wie oben | `5eyes-backend/services/market_data/providers/openfigi_provider.py:7-30`; `5eyes-backend/services/openfigi_client.py:10` |
| 7 | EZB SDMX-API (`data-api.ecb.europa.eu`) | Makrodaten (Zinsen/Inflation) | Makro-Provider-Pfad | `5eyes-backend/services/market_data/macro/providers/ecb.py:3-28` |
| 8 | FRED / St. Louis Fed (`api.stlouisfed.org`) | Makrodaten (US-Zinsreihen) | wie oben | `5eyes-backend/services/market_data/macro/providers/fred.py:3-31` |
| 9 | SNB Datenportal (`data.snb.ch`) | Makrodaten (CH-Referenzzinsen) | wie oben | `5eyes-backend/services/market_data/macro/providers/snb.py:3-28` |
| 10 | EODHD (`eodhd.com`) | Symbolsuche/Kursdaten | API-Key-Konfiguration | `5eyes-backend/services/eodhd_client.py:13` |
| 11 | justETF (`www.justetf.com`) | ETF-Stammdaten-Scraping | ETF-Provider-Pfad | `5eyes-backend/services/market_data/etf/providers/justetf.py:7-24` |
| 12 | SwissFundData (`www.swissfunddata.ch`) | CH-Fonds-Stammdaten-Scraping | wie oben | `5eyes-backend/services/market_data/etf/providers/swissfunddata.py:5-22` |
| 13 | Yahoo Finance (via `yfinance`-Library) | **Primary-Provider für Tier 1** (Solo-Berater) | Standard-Provider, kein explizites Opt-out-Flag im Provider | `5eyes-backend/services/market_data/providers/yfinance_provider.py:1-18`; Pin `5eyes-backend/requirements.txt:21` |
| 14 | Bloomberg (Server-API/B-PIPE) | Sub-Anlageklassen-Gold-Quelle | **Stub/inaktiv**: braucht externe `blpapi`-Lizenz+Wheel, nicht in `requirements.txt`, nicht automatisch registriert | `5eyes-backend/services/market_data/providers/bloomberg_provider.py:1-24` |
| 15 | Konfigurierbarer Webhook (Slack/Discord/generisch) — Markdaten-Validierung | Alert bei Cross-Validation-Abweichung | `market_data_alert_webhook_url` gesetzt, sonst No-op | `5eyes-backend/services/market_data/notifier.py:7-73`; Settings `5eyes-backend/config.py:188-190` |
| 16 | Konfigurierbarer Webhook (Slack/Discord/generisch) — Backup-Fehler | Alert bei Backup-/Scheduler-Fehlschlag | `backup_alert_webhook_url` gesetzt, sonst No-op | `5eyes-backend/backup_scheduler.py:31-55`; Settings `5eyes-backend/config.py:257-258` |
| 17 | Offsite-Backup-Ziel (beliebiger `user@host:/pfad` via rsync/SSH) | Zweitstandort-Kopie des SQLCipher-Backups | `backup_offsite_enabled=true` + `backup_offsite_target` gesetzt, sonst No-op | `5eyes-backend/services/backup.py:603-689`; Settings `5eyes-backend/config.py:233-245` |
| 18 | Electron-Update-Feed (`electron-updater`, `provider: generic`) | Auto-Update-Download/Install | `app.isPackaged && ENABLE_AUTO_UPDATE=1` | `5eyes-electron/main.js:118-120,127-166`; Ziel-URL `5eyes-electron/package.json:121-126` |

**Keiner** dieser 18 Zeilen ist in `docs/CLIENT_DATA_STORAGE_AND_PROCESSING.md`,
`docs/compliance/dsfa-datenschutz-folgenabschaetzung.md`,
`docs/compliance/avv-template.md` oder
`docs/compliance/finma-outsourcing-anzeige.md` namentlich erwähnt (per
Volltextsuche auf alle Host-/Produktnamen in dieser Tabelle: keine Treffer).

## `VENDOR-EGRESS-001` – Kein kanonisches Vendor-/Datenabfluss-Register

### Ist-Zustand

Die 18 oben belegten Verbindungen sind über mindestens 12 verschiedene
Python-Module und eine Electron-`main.js` verteilt. Jede einzelne Stelle ist
für sich genommen sauber dokumentiert (Docstrings erklären Zweck,
Opt-in-Bedingung, Fail-Modus), aber es gibt **keine einzige Datei**, die alle
Verbindungen gemeinsam mit Datenklasse, Zielregion, Transportverschlüsselung,
Retention, Vertragsstatus (AVV/DPA), Subprocessor-Einordnung und Exit-Pfad
auflistet. `docs/CLIENT_DATA_STORAGE_AND_PROCESSING.md` — das nach dem
Readiness-Plan (`docs/compliance/2026-10-05-trust-compliance-accessibility-readiness-plan.md`,
Abschnitt 6) der "gute technische Start" für `TRUST-03` sein soll — enthält
keinen der 13 externen Hostnamen und keinen der beiden Webhook-Mechanismen.

Die Datenklassifikation der Marktdaten-Provider (1-14 in der Tabelle) ist
fachlich risikoarm (öffentliche Kurs-/Referenzdaten, keine Kunden-PII), aber
das ist eine Beobachtung dieses Audits, kein im Code hinterlegter,
versionierter Datenklassifikations-Vertrag. SMTP (1) verarbeitet dagegen
Empfänger-E-Mail-Adressen und Namen echter Nutzer — ein PII-Fluss an einen
beliebigen, vom Betreiber konfigurierten SMTP-Host ohne jede im Repository
dokumentierte Vertrags-/Subprocessor-Bindung.

### Auditvertrag

Ein einziges, owner-geprüftes Dokument (oder maschinenlesbares Register)
listet jede der 18 Verbindungen mit: Zweck, Datenklassen, Trigger/Gate,
Ziel-Host/Region, Transportverschlüsselung, Credential-Typ, Retention beim
Dritten (soweit bekannt/vertraglich), Vertrags-/AVV-Status, Subprocessor-
Klassifikation, Owner, Exit-Pfad und T1/T2/T3-Anwendbarkeit. Das Register
wird bei jeder neuen ausgehenden Verbindung im selben PR aktualisiert; ein
CI-Grep-Gate (siehe `VENDOR-EGRESS-002`) verhindert unregistrierte neue
Hosts.

## `VENDOR-EGRESS-002` – Kein Test erzwingt eine Netzwerk-Allowlist

### Ist-Zustand

Eine gezielte Suche nach einer Allowlist-/Egress-Testabdeckung in
`5eyes-backend/tests/` und `5eyes-electron/tests/` ergab zwei False
Positives und keinen echten Treffer:

- `5eyes-backend/tests/test_bearer_token_ttl_audit.py:238` prüft eine
  **JWT-Algorithmus-Allowlist** (Anti-alg-confusion), keine Netzwerkziele.
- `5eyes-backend/tests/test_allocation_preferences_fail_closed_contracts.py:332`
  prüft eine **Optimizer-Feld-Allowlist**, ebenfalls kein Netzwerkbezug.
- Eine Suche nach dem Wortstamm „egress“ traf ausschliesslich auf das
  deutsche Wort „Regression“ (zufällige Teilzeichenkette), kein Treffer mit
  fachlichem Netzwerkbezug.

`5eyes-electron/tests/bundle-secret-scan.test.js` prüft, dass keine Secrets
im gepackten Bundle landen — das ist eine verwandte, aber andersartige
Kontrolle (Secret-Leak, nicht Ziel-Allowlist) und deckt diesen Befund nicht.

Es existiert damit kein automatisierter Nachweis, dass eine künftige, nicht
im Register erfasste `requests.get()`/`httpx`/`urlopen()`-Zeile gegen einen
neuen, nicht genehmigten Drittanbieter-Host zuverlässig auffällt.

### Auditvertrag

Ein Test (Backend: Statische Quellcode-Analyse der Host-Literale/Settings-
Felder; Electron: Analyse der gepackten `main.js`/Konfiguration) vergleicht
jedes gefundene ausgehende Ziel gegen das Register aus `VENDOR-EGRESS-001`
und schlägt fehl, sobald ein nicht gelisteter Host auftaucht. Der Test läuft
im selben Gate wie die übrige Testsuite.

## `VENDOR-EGRESS-003` – Electron-Update-Feed zeigt auf eine nicht-reale Platzhalter-Domain

### Ist-Zustand

`5eyes-electron/package.json:121-126` konfiguriert `electron-updater` mit:

```json
"publish": [
  { "provider": "generic", "url": "https://updates.example.invalid/5eyes/windows" }
]
```

`example.invalid` ist eine nach RFC 2606 reservierte, bewusst nicht
auflösbare Testdomain — dieses Ziel kann in keinem realen Deployment
funktionieren. Der Mechanismus selbst ist nicht deaktiviert: `main.js:118-120`
aktiviert Auto-Updates, sobald `app.isPackaged && ENABLE_AUTO_UPDATE=1`, und
`main.js:134-135` setzt `autoDownload=true` sowie
`autoInstallOnAppQuit=true`. Das Gate ist damit vorhanden und sinnvoll
defensiv (kein Auto-Update im Dev-Betrieb), aber der eigentliche Zielhost ist
im Repository nie durch einen echten, betreiberkontrollierten Endpunkt
ersetzt worden — es ist offen, ob dies ein bewusst noch nicht finalisierter
Platzhalter oder ein versehentlich produktionsreif erscheinender Dummy-Wert
ist.

### Auditvertrag

Vor jedem Release mit `ENABLE_AUTO_UPDATE=1` wird `publish.url` auf einen
realen, vom Betreiber kontrollierten, TLS-gesicherten Endpunkt gesetzt und
dessen Vertrags-/Hosting-Status im Vendor-Register (`VENDOR-EGRESS-001`)
erfasst. Ein Preflight-Check verhindert ein Release-Artefakt mit einer
`*.invalid`/Platzhalter-Update-URL, wenn `ENABLE_AUTO_UPDATE` produktiv
gesetzt werden könnte.

## `VENDOR-EGRESS-004` – Sentry kann beliebigen `context` als Extras senden; aktuell ohne Call-Site

### Ist-Zustand

`5eyes-backend/services/telemetry.py:87` initialisiert Sentry explizit mit
`send_default_pii=False`. `capture_exception()` (Zeilen 101-119) akzeptiert
jedoch einen beliebigen `context: dict`, der verlustfrei über
`scope.set_extra(str(k), v)` (Zeile 114) an Sentry weitergereicht wird, bevor
`capture_exception(exc)` aufgerufen wird. `send_default_pii=False` schützt
also nur vor SDK-automatischen PII-Feldern (IP, Request-Header etc.), nicht
vor PII, die ein Aufrufer bewusst oder versehentlich in `context` steckt.

Eine repository-weite Suche nach echten Aufrufern ausserhalb von Tests ergab
**keinen einzigen Call-Site** von `capture_exception(...)` oder
`capture_message(...)` in `routers/`, `services/` (ausser der Definition
selbst) oder sonstigem Produktcode — nur
`5eyes-backend/tests/test_telemetry_opt_in.py:137,152,170,207` ruft die
Funktionen auf, u. a. mit `context={"mandate_id": "MX-1"}` (Zeile 170). Der
Mechanismus ist damit heute **nicht produktiv verdrahtet**: Ohne Call-Site
kann aktuell keine PII tatsächlich abfliessen. Das ist jedoch kein
struktureller Schutz — sobald ein künftiger Aufrufer `context` mit
Kunden-/Mandats-Feldern befüllt, fliesst das ohne weitere Prüfung ab, sofern
`telemetry_enabled` + `telemetry_dsn` gesetzt sind.

### Auditvertrag

Vor der ersten produktiven Verdrahtung eines `capture_exception`/
`capture_message`-Call-Sites wird eine Allowlist erlaubter `context`-Schlüssel
(oder eine Redaction-Funktion) eingeführt, die Freitext-/Kundendatenfelder
aktiv ausschliesst, nicht nur implizit über Aufrufer-Disziplin. Sentry wird
im Vendor-Register (`VENDOR-EGRESS-001`) mit Datenklasse „potenziell PII via
context, aktuell kein Call-Site“ erfasst.

## `FINMA-SUBPROCESSOR-001` – Subprocessor-Liste gefordert, aber nicht vorhanden

### Ist-Zustand

`docs/compliance/finma-outsourcing-anzeige.md` Abschnitt 5 verspricht:

> „Nachweis CH-Datenstandort + Liste Unterauftragsverarbeiter.“ (Zeile 62)

Die Anzeige-/Inventar-Vorlage selbst (Abschnitt 4, Zeilen 44-58) enthält für
„Weiterauslagerungen“ nur den unausgefüllten Platzhalter
`_CH-Hosting-Provider, …_` (Zeile 53). Eine Volltextsuche nach jedem der 13
in diesem Audit identifizierten externen Hostnamen in `docs/compliance/`
ergab keinen Treffer. `docs/compliance/avv-template.md` ist ebenfalls eine
Vorlage ohne konkrete Unterauftragsbearbeiter-Einträge (bereits durch den
Coverage-Audit als Vorlage, nicht Umsetzung, eingeordnet; hier unabhängig
durch Volltextsuche bestätigt). Es existiert damit **keine** Stelle im
Repository, an der die tatsächlich im Code aktiven Drittanbieter als
Unterauftragsbearbeiter gelistet sind — die vom Betreiber laut eigener
Vorlage „bereitzustellende“ Liste fehlt an der Quelle.

### Auditvertrag

Das Register aus `VENDOR-EGRESS-001` wird explizit als Grundlage für die
Subprocessor-Spalte der FINMA-Outsourcing-Vorlage referenziert bzw. in sie
übernommen, bevor ein erster produktiver T2/T3-Tenant live geht.

## `ASSET-LICENSE-001` – `package.json` `UNLICENSED` betrifft nur das Root-Paket

### Ist-Zustand

`5eyes-electron/package.json:7` trägt `"license": "UNLICENSED"`. Eine
strukturierte Auswertung von `5eyes-electron/package-lock.json`
(`lockfileVersion: 3`, 426 Paket-Einträge inkl. Root) ergab: **genau ein**
Eintrag mit `license: "UNLICENSED"` — der Root-Eintrag `""` (Version
`0.4.0`, identisch mit dem eigenen Produktpaket). Alle **425** übrigen
Einträge (Drittabhängigkeiten, u. a. `electron@33.4.11` MIT,
`electron-builder@25.1.8` MIT, `electron-updater@6.8.3` MIT) tragen ein
eigenes Lizenzfeld. Verteilung der 426 Lizenzfelder: 317× MIT, 75× ISC, 10×
Apache-2.0, 7× BlueOak-1.0.0, 6× BSD-2-Clause, 5× BSD-3-Clause, je 1×
Python-2.0, `WTFPL OR ISC`, `WTFPL`, `(MIT OR CC0-1.0)`, `(WTFPL OR MIT)` und
das genannte eine `UNLICENSED` (Root).

Diese Lizenzfelder sind von npm aus den jeweiligen Paket-`package.json`-
Dateien übernommene **Selbstangaben** der Paket-Autoren, keine unabhängig
geprüfte Rechtsauskunft, und sie liegen ausschliesslich im Lockfile — es
gibt kein daraus generiertes, redistribuierbares Notices-Dokument, und kein
Build-Skript liest dieses Feld aus (siehe `SBOM-001`).

### Auditvertrag

`UNLICENSED` im Root-Paket wird in jeder künftigen Lizenz-/Vendor-
Kommunikation explizit als „eigene Paketpublikation, keine
Drittnutzungsrechte“ erklärt. Ein generierter Third-Party-Notices-Bericht
aus `package-lock.json` (z. B. per `license-checker`/vergleichbarem Tool)
wird vor Distribution erzeugt, geprüft und versioniert abgelegt.

## `ASSET-LICENSE-002` – Chart.js und Länderumrisse: Lizenz im Dateikopf geklärt, aber nicht erfasst

### Ist-Zustand

`5eyes-electron/frontend/vendor/chart.min.js` trägt in den ersten Zeilen
einen unminifizierten Banner-Kommentar:

```
/*! Chart.js v4.4.1
 * https://www.chartjs.org
 * (c) 2023 Chart.js Contributors
 * Released under the MIT License
 */
```

sowie einen vorangestellten jsDelivr-Hinweis `Original file:
/npm/chart.js@4.4.1/dist/chart.umd.js`. Die Lizenz ist damit MIT und im File
selbst dokumentiert.

`5eyes-electron/frontend/vendor/intro-country-outlines.js` trägt als ersten
Kommentar:

```
/* Natural Earth 1:110m Admin-0 countries, v5.1.1, public domain.
   Simplified and quantized for the 5eyes intro globe. Generated file. */
```

ebenfalls selbstdokumentiert und unproblematisch (public domain).

Beide Dateien liegen jedoch als **statische Vendor-Dateien** ausserhalb des
npm-Abhängigkeitsbaums — sie erscheinen nicht in `package.json` oder
`package-lock.json` und sind damit auch nicht in der 426-Paket-Auswertung
aus `ASSET-LICENSE-001` enthalten. Ein automatisierter Lizenzbericht über
die npm-Abhängigkeiten würde diese beiden Assets strukturell übersehen.

### Auditvertrag

Beide Dateien werden mit Quelle, Version, Lizenz und Abrufdatum explizit in
das Asset-/Notices-Register (`SBOM-001`) aufgenommen, unabhängig davon, dass
sie korrekt lizenziert sind — Vollständigkeit des Registers, nicht nur
Korrektheit der einzelnen Lizenz, ist der Prüfpunkt.

## `ASSET-LICENSE-003` – Inter + Cormorant Garamond: SIL OFL 1.1 im Font-Binary verifiziert

### Ist-Zustand

Die `name`-Tabelle (TrueType `name`-Table, Platform-ID 3) jeder der sechs
Dateien in `5eyes-backend/assets/fonts/` wurde direkt binär ausgelesen
(nicht aus einer Sekundärquelle übernommen). Ergebnis für alle drei
Cormorant-Garamond-Dateien (`CormorantGaramond-{Italic,Regular,SemiBold}.ttf`):

- Copyright: „Copyright 2015 The Cormorant Project Authors
  (github.com/CatharsisFonts/Cormorant)“
- Designer: „Christian Thalmann (Catharsis Fonts)“
- License: „This Font Software is licensed under the SIL Open Font
  License, Version 1.1. … http://scripts.sil.org/OFL“

Für alle drei Inter-Dateien (`Inter-{Medium,Regular,SemiBold}.ttf`):

- Copyright: „Copyright 2016 The Inter Project Authors“
- Designer: „Rasmus Andersson“ (VendorURL `https://rsms.me/`)
- License: identischer SIL-OFL-1.1-Text wie oben.

Beide Fonts sind damit korrekt lizenziert für Bündelung und Modifikation
(SIL OFL erlaubt beides unter Namensreservierungsauflagen). Es existiert
jedoch **keine** Datei im Repository, die diese Attribution für Menschen
lesbar reproduziert — ein Reviewer oder Kunde, der das Produkt prüft, kann
diese Lizenzinformation aktuell nur durch dieselbe Binary-Analyse erhalten,
die dieser Audit durchgeführt hat.

### Auditvertrag

Copyright-, Designer- und Lizenztext beider Font-Familien werden wortgleich
(keine Umformulierung, keine Neuerfindung) in das Notices-Register
(`SBOM-001`) übernommen, zusammen mit der Quelle (GitHub-Repository) und dem
Abruf-/Bündelungsdatum, sofern feststellbar.

## `ASSET-LICENSE-004` – 22 nicht referenzierte Design-Bilder ohne Provenienz

### Ist-Zustand

`docs/design/` enthält 22 UUID-benannte `.jpg`-Dateien (z. B.
`08f319d0-a9ec-4983-adbb-79888a9c80dc.jpg`). Eine Volltextsuche nach dem
Pfad `docs/design` in jeglichem Produktcode (`5eyes-backend/`,
`5eyes-electron/`) ergab **keinen Treffer** — die Bilder werden von keinem
Code referenziert und landen damit nicht im Distributions-/Installer-
Artefakt. Eine Stichprobe der ersten 4000 Byte dreier Dateien enthielt keine
auslesbaren EXIF-/XMP-Textmarker zur Provenienz (Quelle, Urheber, Tool).
Herkunft und Lizenzstatus dieser Bilder sind damit aus dem Repository allein
nicht feststellbar.

### Auditvertrag

Da diese Dateien nicht ausgeliefert werden, blockieren sie keine
Distribution. Vor einer etwaigen späteren Verwendung in Produkt-, Marketing-
oder Kundenunterlagen wird ihre Provenienz (eigene Erstellung,
lizenzpflichtiges Material oder KI-generiert mit entsprechender
Tool-Nutzungsbedingung) geklärt und dokumentiert; ungeklärte Bilder werden
nicht in kundenwirksame Artefakte übernommen.

## `SBOM-001` – Keine Notices-/SBOM-Datei, keine SBOM-Erzeugung im Build

### Ist-Zustand

Eine repository-weite Suche nach `LICENSE*`, `NOTICE*`, `THIRD_PARTY*` und
`*OFL*` als Dateinamen ergab **keinen Treffer** ausserhalb der in diesem
Audit zitierten Lizenztexte, die ausschliesslich innerhalb der TTF-Binaries
und des `chart.min.js`-Headers existieren — keine davon ist eine eigene
Notices-Datei. Eine Suche nach `*sbom*`, `*spdx*`, `*cyclonedx*` als
Dateinamen ergab ebenfalls **keinen Treffer**. Der einzige scheinbare
Treffer für „spdx“ (case-insensitive) in `package-lock.json` ist eine
zufällige Teilzeichenkette innerhalb eines Base64-kodierten
`sha512`-Integritäts-Hashs (`...anSpDXZa...`) und kein echtes SPDX-Tag.

Die einzigen Build-/Package-Skripte in
`5eyes-electron/package.json:8-21` sind `start`, `dev`, `test`,
`build:backend`, `build:reporting`, `pack`, `dist:win`, `dist:win:portable`,
`dist:mac`, `dist:linux`, `preflight:release` und `scan:bundle-secrets`.
Keines davon ruft ein SBOM- oder Lizenzreport-Tool (`license-checker`,
`pip-licenses`, `cyclonedx-bom` o. ä.) auf.

Für die 23 Python-Abhängigkeiten in `5eyes-backend/requirements.txt`
existiert zusätzlich **keine** dem npm-Lockfile vergleichbare
Lizenz-Metadatenquelle irgendwo im Repository — `requirements.txt` listet
nur Paketnamen und Versions-Constraints, kein Lockfile mit Lizenzfeldern und
kein generierter Lizenzbericht.

### Auditvertrag

Vor dem ersten distribuierten Release: ein generiertes, versioniertes
`THIRD_PARTY_NOTICES`-Dokument (npm-Lockfile-Lizenzen + die drei
binär-/dateikopf-verifizierten Assets aus `ASSET-LICENSE-002`/`003`) sowie
ein CycloneDX- oder SPDX-SBOM für sowohl die npm- als auch die Python-
Abhängigkeitsbäume, erzeugt als fester Schritt in `pack`/`dist:*` und an
dasselbe geprüfte Release-Artefakt (Digest/Signatur) gebunden wie in den
älteren Release-Audits verlangt. Unbekannte-Provenienz-Assets (aktuell
keine ausser `ASSET-LICENSE-004`, die aber nicht ausgeliefert werden)
blockieren den Build.

## Verifikation dieser Runde

Jeder Befund in diesem Dokument wurde wie folgt reproduziert, nicht
angenommen:

- Jeder der 18 Egress-Codeanker wurde einzeln per `Grep`/`Read` auf dem
  auditierten Head gelesen und mit Zeilennummern zitiert.
- Die 426-Paket-Lizenzverteilung und der eine `UNLICENSED`-Treffer wurden
  durch ein kleines, nur-lesendes Python-Skript über
  `5eyes-electron/package-lock.json` (JSON-Parsing, keine Mutation)
  erzeugt, nicht aus Dokumentation übernommen.
- Die SIL-OFL-1.1-Lizenz der sechs TTF-Dateien wurde durch direktes,
  binäres Parsen der TrueType-`name`-Tabelle jeder Datei ausgelesen (kein
  externes Tool, keine Internet-Recherche über die Fontnamen).
- Die MIT-Lizenz von Chart.js und die Public-Domain-Deklaration der
  Länderumrisse wurden durch Lesen der ersten Dateizeilen der jeweiligen
  Vendor-Datei bestätigt.
- Die Abwesenheit von `LICENSE`/`NOTICE`/`THIRD_PARTY_NOTICES`/SPDX/
  CycloneDX-Dateien wurde durch eine repository-weite Dateinamensuche
  bestätigt (kein Treffer).
- Die Abwesenheit eines Netzwerk-Allowlist-Tests wurde durch gezielte
  Suche in `tests/`-Verzeichnissen bestätigt; die beiden tatsächlichen
  „Allowlist“-Treffer wurden einzeln gelesen und als themenfremd (JWT-
  Algorithmus, Optimizer-Felder) identifiziert.
- Die Behauptung des Coverage-Audits zu `docs/compliance/finma-
  outsourcing-anzeige.md` wurde durch eigenes Lesen der Datei verifiziert
  (Platzhalterzeile Zeile 53, Zusicherung Zeile 62).

## Selbst-Audit und Nachweisgrenzen

- **Produktcode verändert:** nein.
- **Tests verändert oder ausgeführt:** nein — dies ist ein reiner
  Lese-/Inventaraudit; keine Testsuite wurde ausgeführt, da keine
  funktionale Korrektheit, sondern Vorhandensein/Abwesenheit von Dateien,
  Code-Mustern und Metadaten geprüft wurde.
- **Konfiguration verändert:** nein.
- **Was geprüft wurde:** Backend-Python-Quellcode (`5eyes-backend/`,
  insbesondere `services/`, `routers/`, `config.py`, `backup_scheduler.py`,
  `price_updater.py`), Electron-Hauptprozess (`5eyes-electron/main.js`,
  `package.json`, `package-lock.json`), gebündelte Vendor-Assets
  (`5eyes-electron/frontend/vendor/`), gebündelte Fonts
  (`5eyes-backend/assets/fonts/*.ttf`, binär geparst), `docs/compliance/*`,
  `docs/CLIENT_DATA_STORAGE_AND_PROCESSING.md`, sowie eine
  repository-weite Dateinamen- und Musterrecherche für Lizenz-/SBOM-/
  Allowlist-Artefakte.
- **Was NICHT geprüft wurde:** `node_modules` war in diesem Worktree nicht
  installiert (0 Pakete) — Aussagen zu `electron`/`electron-builder`/
  `electron-updater`-Lizenzen stützen sich ausschliesslich auf
  `package-lock.json`-Metadaten, nicht auf eine Installation der Pakete
  selbst oder deren tatsächliche `LICENSE`-Dateien. Python-Abhängigkeiten
  (`requirements.txt`) wurden nicht gegen ihre echten PyPI-Lizenzmetadaten
  abgeglichen — es wurde nur die **Abwesenheit** einer Lizenzerfassung im
  Repository festgestellt, keine eigene Lizenzrecherche pro Paket
  durchgeführt. Die 22 Bilder in `docs/design/` wurden nur stichprobenhaft
  (3 von 22, erste 4000 Byte) auf Metadaten geprüft, nicht vollständig
  oder visuell inhaltlich analysiert. Es wurde nicht geprüft, ob
  Marktdaten-Provider tatsächlich zur Laufzeit erreichbar sind oder reale
  Netzwerk-Requests auslösen (reine statische Codeanalyse, kein Live-
  Traffic-Capture). Vertragliche Realität (bestehen echte AVV/DPA mit
  diesen Anbietern ausserhalb des Repositories) wurde nicht und kann nicht
  aus dem Code ermittelt werden.
- **Nicht behauptet:** Vollständigkeit über jede denkbare externe
  Verbindung in zukünftigem oder nicht in diesem Repository enthaltenem
  Code (z. B. eine separate Marketing-Website); Rechtswirksamkeit oder
  FINMA-Konformität der beschriebenen Lage; dass die 10 Marktdaten-
  Provider tatsächlich alle in jeder Konfiguration aktiv sind (mehrere sind
  Fallback-/Alternativpfade, deren tatsächliche Aktivierung von
  Admin-Konfiguration/Provider-Registrierung abhängt, die hier nicht pro
  Tenant nachvollzogen wurde).
- **Ergebnis:** Dieser Audit liefert das in
  `B2B-COVERAGE-001`/`B2B-COVERAGE-002` verlangte kanonische Rohmaterial
  (18 Egress-Codeanker, 426-Paket-Lizenzverteilung, verifizierte Font-/
  Chart.js-/Länderumriss-Lizenzen, bestätigte Abwesenheit von Notices/SBOM/
  Allowlist-Test/Subprocessor-Register) als Grundlage für die in Runde 6
  des Coverage-Audits vorgesehene Evidence-Matrix. Er erteilt selbst keine
  Freigabe und schliesst keines der zehn Findings — das bleibt
  Implementierungs-/Owner-Arbeit.
