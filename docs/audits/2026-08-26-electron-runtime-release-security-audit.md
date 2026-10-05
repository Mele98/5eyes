---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-electron-runtime-and-artifact-security-followup-audit"
status_as_of: "2026-08-26"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
desktop_root: "5eyes-electron"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "632a7fa6778844adc37a51e11da9d2ae13bfed27"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-26-data-lifecycle-crypto-browser-followup-audit.md"
prior_release_audit_commit: "632a7fa6778844adc37a51e11da9d2ae13bfed27"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-26-electron-runtime-release-security-audit.md"
audit_mode: "read_only_static_mocked_electron_main_localhost_service_selected_tests_and_primary_vendor_documentation"
audit_mutated_product_code: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 6
scope: "Electron backend identity, desktop token release, installer secret hygiene, Linux credential storage and native cross-platform packaging"
release_decision: "blocked_confirmed_conditional_p0_and_p1"
known_open_conditional_p0: true
known_open_p1: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "disable unauthenticated backend reuse and runtime-env packaging, then prove credential storage and native artifacts on every advertised platform"
---

# Electron-Runtime- und Releaseartefakt-Sicherheitsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die vierte Read-only-Kontrollrunde auf
Repository-Head `632a7fa6`. Er ergänzt, ersetzt aber nicht:

1. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
2. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
3. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
4. den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die vier vorgenannten Dokumente in dieser Reihenfolge.
Historische Packaging-, Multi-Platform-, Deployment- und Releaseanleitungen sind
keine Freigabequelle.

Die Analyse hat keine Produkt- oder Testdatei verändert. Der grüne vollständige
Backend-Gate bleibt ein Regressionsnachweis für den eingecheckten Optimizerstand,
deckt die hier beschriebenen Desktop-, Installer- und Betriebssystemgrenzen aber
nicht ab.

## Kurzurteil

**Release bleibt hart blockiert.** Vier Verträge sind offen:

1. Electron akzeptiert einen beliebigen lokalen HTTP-Dienst als eigenes Backend,
   wenn dieser auf `/health/ready` den öffentlich bekannten App-Namen ausgibt.
   Danach gibt der Main-Prozess gespeicherte Access- und Refresh-Tokens an den
   Renderer frei; der Renderer sendet sie automatisch an den übernommenen Dienst.
2. Der Release-Build kopiert die lokale Backend-`.env` ausdrücklich in das
   auszuliefernde Backend-Bundle. Existiert sie in einer realen Buildumgebung,
   können JWT-, DB-, Provider- und sonstige Betriebssecrets im Installer landen.
   Das ist ein bedingter P0 und unabhängig davon ein P1-Releaseblocker.
3. Unter Linux reicht `safeStorage.isEncryptionAvailable()` nicht als Nachweis
   eines sicheren Secret Stores. Electron kann den schwachen Backendmodus
   `basic_text` wählen; der aktuelle Code erkennt und sperrt ihn nicht.
4. Die Scripts werben mit macOS- und Linux-Artefakten, bauen und starten aber auf
   jeder Plattform ausschließlich `5eyes-api.exe`. Die grünen Tests kontrollieren
   nur Konfigurationsstrings, nicht ein natives Paket oder dessen Startfähigkeit.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `DESK-001` | P1 | offen | Electron übernimmt und autorisiert ausschließlich den von ihm gestarteten, kryptografisch gebundenen Backendprozess |
| `DESK-002` | P0 konditional / P1 | offen | Releaseartefakte enthalten weder Runtime-`.env` noch Secrets, Datenbanken oder maschinengebundene Konfiguration |
| `DESK-003` | P1 konditional Linux | offen | Persistierte Desktop-Tokens verwenden einen nachweislich sicheren OS-Credential-Store; `basic_text` ist fail-closed |
| `DESK-004` | P1 | offen | Jede beworbene Plattform baut, paketiert und startet ein natives, geprüftes Backendartefakt |

Ein Finding darf erst nach rotem Negativtest, Produktfix, Artefaktinspektion und
vollständigem Gate auf demselben Fixcommit geschlossen werden. Ein geändertes
Testorakel, eine statische Package-Prüfung oder ein grüner Windows-only-Smoke
allein schließt keinen dieser Verträge.

## Reproduktions- und Evidenzledger

| Scope | Methode | Ergebnis |
|---|---|---|
| Backend-Identität | tatsächliches `main.js` mit gemocktem Electron und lokalem Fake-HTTP-Dienst | Fake-Service mit richtigem öffentlichem `app`-String wurde als `ready` übernommen |
| Token-Datenfluss | statischer Callgraph vom IPC-Store bis zum ersten Browserrequest | gespeicherter Bearer wird beim Start automatisch an `/auth/me` des übernommenen Dienstes gesendet |
| Installer-Inhalt | direkte Build-/electron-builder-Datenflussprüfung | vorhandene `5eyes-backend/.env` wird nach `bundle/backend/.env` kopiert und vollständig als `extraResources` ausgeliefert |
| Linux Secret Store | Codeaudit plus offizielle Electron-API-Dokumentation | Code prüft nur Verfügbarkeit; `basic_text`/`unknown` werden nicht unterschieden |
| Native Artefakte | Package-/Build-/Runtime-Callgraph | macOS-/Linux-Scripts erwarten, kopieren und starten denselben Windows-Dateinamen `5eyes-api.exe` |
| Electron-Smoke | `node tests/main.smoke.test.js` | 13 von 13 Checks grün; keine Backend-Identitäts- oder `basic_text`-Abdeckung |
| Plattform-/Update-/CSP-/Signing-Ring | vier fokussierte Pytest-Dateien | 42 von 42 Tests grün; keine native Build-/Boot-Abnahme |

Die Fake-Service-Reproduktion verwendete ausschließlich synthetische Werte und
einen temporären Loopback-Port. Das beobachtete Ergebnis war:

```json
{"fake_service_adopted":true,"baseUrl":"http://127.0.0.1:56367","matchesApp":true,"statusCode":200}
```

Kein realer Token, Schlüssel, Installer oder Kundendatensatz wurde verwendet.

## Befunde und verbindliche Fixverträge

### `DESK-001` – Öffentlicher Health-String authentisiert ein fremdes Backend

`5eyes-electron/main.js:363-393` ruft unauthentisiert `/health/ready` auf und
vergleicht ausschließlich `payload.app` mit `EXPECTED_BACKEND_APP`. Dieser Wert
ist kein Secret: `5eyes-backend/routers/health.py:30-37,58-86` veröffentlicht ihn
auf dem Health-Endpunkt. Ist der Default-Port belegt und antwortet der fremde
Dienst passend, verwendet `pickBackendRuntime()` ihn ohne Spawn oder
Prozessbindung weiter.

Danach exponieren `main.js:621-628` Access- und Refresh-Token aus dem persistenten
Store per IPC. `5eyes-electron/frontend/5eyes_v2.html:4983-5100,9320-9357` liest
den Token beim Start, übernimmt die Backend-URL und sendet automatisch
`Authorization: Bearer ...` an `/auth/me`; ein Refresh kann zusätzlich den
Refresh-Token an `/auth/refresh` senden. Beim manuellen Login gehen Benutzername,
Passwort und gegebenenfalls TOTP gemäß `:5333-5356` ebenfalls an diese URL.

Auch die Auswahl eines vermeintlich freien Ports ist nicht identitätsstark:
`resolveFreePort()` schließt den Prüfsocket, bevor der Childprozess bindet. Ein
anderer Prozess kann das Zeitfenster übernehmen und denselben öffentlichen
Health-String liefern.

**Fixvertrag:** Der Parent erzeugt pro Start einen kryptografisch zufälligen,
einmaligen Launch-Nonce und übergibt ihn nur über einen prozessgebundenen Kanal,
zum Beispiel geerbten Socket, Named Pipe oder geschützte Child-Umgebung. Der
Backendprozess muss den Besitz in einem nicht öffentlich wiederverwendbaren
Handshake beweisen. Noch besser bindet der Parent den Listening-Socket und
vererbt ihn an das Child. Ein bereits laufender Prozess darf nicht allein anhand
von Name, Port oder Versionsstring übernommen werden. IPC für Token und
Backend-URL bleibt gesperrt, bis Prozessidentität und Handshake bestätigt sind.

**Rote Tests:** Ein Fake-Dienst mit exakt passendem App-Namen wird abgelehnt;
der echte gestartete Childprozess wird akzeptiert. In Occupied-Port- und
Bind-Race-Tests empfängt der Fake-Dienst weder `/auth/me`, `/auth/refresh` noch
`/auth/login` und kein Credential-Byte. Ein Neustart darf einen alten Nonce
nicht wiederverwenden.

### `DESK-002` – Build kopiert die echte `.env` in jeden Installer

`5eyes-electron/scripts/build-backend.js:196-199` kopiert eine vorhandene
`5eyes-backend/.env` ausdrücklich nach `bundle/backend/.env`.
`5eyes-electron/package.json:49-56` nimmt anschließend den vollständigen
Bundlebaum als `extraResources` in das auslieferbare Artefakt auf. Die Datei ist
zwar in Git ignoriert, enthält in einer normalen Betriebsumgebung aber gerade die
lokalen Runtimewerte wie `SECRET_KEY`, `DB_KEY`, Provider-Keys und DB-URLs.

Der vorhandene Release-Preflight scannt dieses Ergebnis nicht. Zusätzlich läuft
er in `package.json:14-18` vor `build:backend`, kann also selbst bei späterer
Erweiterung das frisch erzeugte Bundle in dieser Reihenfolge nicht prüfen.
`5eyes-electron/README.md:127-131` dokumentiert das Kopieren bislang sogar als
normalen Packaging-Schritt.

Im geprüften Checkout existierte keine produktive `.env` und kein fertiges
Installerartefakt. Der konkrete Datenfluss ist dennoch deterministisch: Sobald
ein Releaseoperator mit realer `.env` baut, wird diese kopiert. Deshalb gilt der
Pfad als bedingter P0 und sofortiger P1-Releaseblocker.

**Fixvertrag:** Runtime-`.env` wird niemals gebaut, kopiert oder ausgeliefert.
Erlaubt ist ausschließlich eine secretfreie Vorlage. Die Erstkonfiguration
erzeugt maschinenindividuelle Secrets außerhalb des Programmartefakts mit
restriktiven Rechten beziehungsweise im OS-Credential-Store. Der Build läuft aus
einem sauberen, minimalen Environment; nach dem Build wird das echte Paket
entpackt und auf `.env`, Datenbanken, Token-, Schlüssel-, Credential- und
Canary-Muster geprüft. Manifest, SBOM, Hash und Signatur binden genau den
geprüften Inhalt.

**Incident-Regel:** Wurde bereits irgendein Installer mit diesem Buildpfad und
einer echten `.env` erzeugt oder verteilt, ist er als potenzieller Secret-Incident
zu behandeln. Betroffene JWT-, DB-, Verschlüsselungs-, Provider- und Webhook-
Secrets sind zu inventarisieren und zu rotieren; bloßes Löschen des Installers
reicht nicht.

**Rote Tests:** Build mit synthetischer `.env`-Canary muss vor Paketierung
abbrechen und das finale Artefakt darf die Canary nicht enthalten. Ein Clean-
Build enthält genau die erlaubte, secretfreie Runtimekonfiguration. Der Test
prüft das entpackte NSIS-/DMG-/AppImage-Artefakt, nicht nur den Staging-Ordner.

### `DESK-003` – Linux kann Tokens mit dem schwachen `basic_text`-Backend speichern

`5eyes-electron/main.js:196-234` behandelt
`safeStorage.isEncryptionAvailable() === true` als hinreichenden Schutz und
persistiert dann Access- und Refresh-Token. Der Code fragt
`safeStorage.getSelectedStorageBackend()` nicht ab. Die vorhandene Smoke-Suite
stubbt nur den Boolean und besitzt keinen Linux-`basic_text`-Fall.

Die [offizielle Electron-safeStorage-Dokumentation](https://www.electronjs.org/docs/latest/api/safe-storage)
erklärt für Linux, dass ohne verfügbaren Secret Store ein fest hinterlegter
Fallbackschutz möglich ist und dieser über den Rückgabewert `basic_text`
erkannt werden kann. `unknown` ist vor App-Ready ebenfalls kein positiver
Sicherheitsnachweis. Electron empfiehlt inzwischen außerdem die asynchrone API,
die Rotation und temporäre Nichtverfügbarkeit ausdrücken kann.

**Fixvertrag:** Unter Linux dürfen `basic_text`, `unknown` und nicht explizit
allowlistete Provider keine persistente Tokenablage ermöglichen. Bereits unter
einem schwachen Backend erzeugte Dateien werden nicht entschlüsselt oder
weiterverwendet; sie werden kontrolliert verworfen und ein neues Login verlangt.
Alternativ ist ein explizit unterstützter OS-Secret-Service zwingend. Die
asynchrone API mit Re-Encryption-/Rotationstatus ist zu bevorzugen.

Unter Windows schützt DPAPI gegen andere OS-Benutzer, nicht pauschal gegen
Prozesse im selben Userkontext. Daher ersetzt dieser Fix die Prozessbindung aus
`DESK-001` nicht.

**Rote Tests:** Linux-Provider `basic_text` und `unknown` führen zu keinem
Tokenfile und keinem gelesenen Alttoken; `gnome_libsecret`, `kwallet*` und jeder
bewusst unterstützte Provider erfüllen den positiven Vertrag. Providerwechsel,
temporäre Nichtverfügbarkeit, Key-Rotation und korrupte Ciphertexte werden
separat geprüft.

### `DESK-004` – macOS-/Linux-Releasepfade bauen und starten eine Windows-EXE

`5eyes-electron/package.json:17-18,77-102` bewirbt DMG- und AppImage-Builds.
`5eyes-electron/scripts/build-backend.js:8,191-200` erwartet und kopiert jedoch
immer `dist/5eyes-api.exe`. `5eyes-electron/main.js:269-270,404-416` löst und
startet im paketierten Betrieb ebenfalls auf jeder Plattform ausschließlich
`5eyes-api.exe` auf.

Ein nativer PyInstaller-Onefile-Build heißt unter macOS/Linux normalerweise
`5eyes-api` ohne `.exe`. Ein sauberer Build scheitert deshalb entweder bereits
an der Dateiprüfung oder ein erzeugtes Paket erwartet zur Laufzeit ein
Windows-Binary. `tests/test_multi_platform_build.py` prüft nur, ob Scripts,
Targets und Dokumentbegriffe vorhanden sind; es baut und startet kein natives
Artefakt. Zugleich bezeichnet die Electron-README das Produkt als „Windows only“,
während Package-Scripts und `docs/MULTI_PLATFORM_BUILD.md` reale macOS-/Linux-
Kommandos versprechen.

**Fixvertrag:** Entweder wird der freigegebene Produktscope ehrlich auf Windows
begrenzt und alle macOS-/Linux-Scripts, Targets und Erfolgsaussagen werden bis zu
einem echten Nachweis entfernt, oder jede Zielplattform baut auf einem nativen
Runner das korrekte PyInstaller-Binary. Dateiname, Spawnlogik, Rechte und
electron-builder-Ressource sind plattformabhängig. Cross-Builds dürfen nicht als
belegt gelten, wenn das Backend nicht nativ gebaut und gebootet wurde.

**Rote Tests:** CI-Matrix Windows x64, macOS x64/arm64 und Linux x64 baut jeweils
aus einem Clean Clone, entpackt das Paket, startet es und beweist Health,
Bootstrap/Login sowie sauberes Beenden. Tests prüfen Dateiname, Execute-Bit,
Codesign/Notarization, Architektur, gebundene Runtimebibliotheken und dass kein
fremdplattformiges Binary enthalten ist.

## Positive Kontrollen und Abgrenzung

Die Electron-BrowserWindow-Konfiguration besitzt bereits sinnvolle Grundlagen:
`contextIsolation`, `sandbox` und deaktiviertes `nodeIntegration`; Navigation,
Window-Open, WebViews, Permissions und externe URL-Schemes werden begrenzt.
PDF-Dateinamen werden auf den Basename reduziert. In der fokussierten Prüfung
wurde kein zusätzlicher bestätigter Path-Traversal- oder Stored-XSS-P1 gefunden.

Diese positiven Kontrollen ändern die vier Befunde nicht: Eine gehärtete
Renderer-Sandbox authentisiert weder den lokalen HTTP-Prozess noch bereinigt sie
Installerinhalte oder OS-Credential-Provider.

## Verbindliche Umsetzungsreihenfolge für Claude

### Block A – Sofortige Eindämmung

1. `DESK-002`: Kopieren der Runtime-`.env` entfernen; Releaseartefakt-Scan vor
   jedem weiteren Build verpflichtend machen.
2. `DESK-001`: Wiederverwendung eines nur per Health-String erkannten Backends
   deaktivieren. Bis zum echten Handshake immer einen eigenen Childprozess mit
   geschütztem Kanal starten und Tokens vor Identitätsnachweis sperren.
3. Bereits gebaute oder verteilte Installer inventarisieren und gegebenenfalls
   Secret-Rotation als Incidentmaßnahme auslösen.

### Block B – Prozess- und Credential-Vertrag

1. Prozessgebundenen Nonce-/Socket-Handshake implementieren.
2. Token-IPC erst nach bestätigter Backendidentität freigeben.
3. Linux-Provider allowlisten; `basic_text`/`unknown` fail-closed behandeln.
4. Providerrotation und Re-Login-Verhalten end-to-end testen.

### Block C – Ehrliche Releaseplattformen

1. Produktentscheidung Windows-only oder echter Drei-Plattform-Support treffen.
2. Package-Scripts, Buildscript, Runtimeauflösung, Dokumentation und CI auf diese
   eine Entscheidung ausrichten.
3. Pro Zielplattform natives, signiertes Artefakt bauen und aus dem entpackten
   Paket booten.
4. Releaseabfolge auf `build → unpack/scan/smoke → sign/attest → publish`
   umstellen; ein Preflight vor dem eigentlichen Build reicht nicht.

## Verbindlicher Test- und Artefaktvertrag

Neue oder erweiterte Suites mindestens:

- `5eyes-electron/tests/backend_identity_handshake.test.js`
- `5eyes-electron/tests/safe_storage_provider.test.js`
- `5eyes-electron/tests/release_artifact_secret_scan.test.js`
- `5eyes-backend/tests/test_native_electron_artifacts.py`
- `5eyes-backend/tests/test_multi_platform_build.py`

Der Backend-Identitätstest muss einen echten konkurrierenden Loopback-Server
starten und den vollständigen Renderer-Datenfluss beobachten. Reine
Funktionsstubs ohne Netzwerk und reine Stringtests reichen nicht.

Der Releaseartefakttest entpackt das tatsächlich publizierbare Format, scannt
alle enthaltenen Dateien und startet genau dieses Artefakt. Ein Scan von Git,
Source-Tree oder `bundle/backend` allein ist kein Auslieferungsnachweis.

## Definition of Done

Der Electron-/Releaseartefakt-Block ist erst geschlossen, wenn:

- [ ] ein fremder lokaler Dienst trotz identischem App-/Versionsstring nie
      Backend-URL, Access-Token, Refresh-Token oder Login-Credentials erhält;
- [ ] die Backendidentität an den gestarteten Prozess und einen einmaligen,
      nicht öffentlich erratbaren Handshake gebunden ist;
- [ ] Portbelegungs- und Bind-Races deterministisch fail-closed enden;
- [ ] kein Installer eine Runtime-`.env`, Datenbank, Token, Schlüssel oder
      synthetische Secret-Canary enthält;
- [ ] jedes möglicherweise früher exponierte Buildartefakt inventarisiert und
      betroffene Secrets nachweisbar rotiert wurde;
- [ ] Linux `basic_text`/`unknown` nie für persistente Tokens verwendet und ein
      Providerwechsel verlustfrei beziehungsweise mit sicherem Re-Login endet;
- [ ] jede beworbene Plattform ein natives Artefakt aus einem Clean Clone baut,
      entpackt, scannt, startet und signatur-/architekturprüft;
- [ ] Windows-only-Aussagen und Plattform-Scripts nicht mehr widersprüchlich sind;
- [ ] vollständiger Electron-, Backend-, Installer- und Zielplattform-Gate auf
      demselben Fixcommit grün ist;
- [ ] Security, Release Engineering und Operations das Artefaktmanifest samt
      Hash, SBOM, Signatur und Testevidenz freigegeben haben.

## Claude-Startcheckliste

1. Dieses Dokument und danach alle drei Vorgängeraudits vollständig lesen.
2. Zuerst rote Tests für `DESK-001` und `DESK-002` schreiben; keine Packaging-
   Dokumentation als Beweis verwenden.
3. Keine gespeicherten Tokens ausgeben, bevor die Backendidentität bestätigt ist.
4. Niemals Runtime-`.env`, DB oder Secretmaterial in Staging-/Installerpfade
   kopieren, auch nicht „nur lokal“.
5. OS-Credential-Provider explizit prüfen; ein Verfügbarkeits-Boolean genügt nicht.
6. Multi-Platform nur für ein nativ gebautes und gestartetes Artefakt behaupten.
7. Pro Finding einen atomaren Fixcommit, fokussierten Ring und anschließend den
   vollständigen Releasegate auf exakt demselben Commit dokumentieren.
8. Releaseentscheidung bleibt `blocked`, bis diese und sämtliche früheren
   Definition-of-Done-Verträge erfüllt und extern freigegeben sind.

## Dokumentationsmanifest dieser Runde

Dieses Dokumentationsbatch umfasst exakt:

1. `docs/audits/2026-08-26-electron-runtime-release-security-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `5eyes-electron/README.md`
5. `5eyes-electron/PACKAGING.md`
6. `docs/MULTI_PLATFORM_BUILD.md`

Der Commit dieses Dokuments wird nicht in den eigenen Inhalt eingebettet.
Auflösung ausschließlich extern über `document_commit_resolution`.

## Dokumentations-QA vor Commit

- Electron-Smoke: 13 von 13 Checks grün;
- fokussierter Plattform-/Update-/CSP-/Signing-Ring: 42 von 42 Tests grün;
- Finding-Register: 4 eindeutige IDs, 4 zugehörige Detailsektionen;
- lokale Links im Sechs-Pfade-Batch: 23 geprüft, 23 gültig;
- primäre Electron-safeStorage-Quelle: am 26.08.2026 direkt geprüft;
- Markdown-Codefences: in allen sechs Pfaden paarig;
- `git diff --check`: grün;
- sichtbares Dokumentmanifest: exakt sechs Pfade;
- die 53 bekannten ACL-unlesbaren `.pytest_tmp_*`-Verzeichnisse wurden weder
  gelesen noch verändert; deshalb kein globaler Clean-Claim.
