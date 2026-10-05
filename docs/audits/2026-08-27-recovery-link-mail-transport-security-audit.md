---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "release-blocking-recovery-link-and-mail-transport-security-followup-audit"
status_as_of: "2026-08-27"
language: "de"
repository: "asset-allocation-stochastic-core"
backend_root: "5eyes-backend"
branch: "codex/asset-allocation-stochastic-core"
audited_repository_head: "497f19f276c2e1cb8f4e7ce64ffb50483db6d470"
covered_implementation_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
prior_release_audit_path: "docs/audits/2026-08-26-electron-runtime-release-security-audit.md"
prior_release_audit_commit: "497f19f276c2e1cb8f4e7ce64ffb50483db6d470"
document_commit_resolution: "external: git log -1 --format=%H -- docs/audits/2026-08-27-recovery-link-mail-transport-security-audit.md"
audit_mode: "read_only_static_local_request_settings_reproduction_and_selected_tests"
audit_mutated_product_code: false
tracked_worktree_clean_before_documentation: true
global_worktree_clean: false
git_status_acl_unreadable_pytest_temp_dirs: 53
documentation_manifest_paths: 5
scope: "Password-reset and invite link origin trust, Host-header handling, SMTP bearer transport and bounded outbound-network review"
release_decision: "blocked_confirmed_p1"
new_confirmed_p0: false
new_confirmed_p1: true
known_open_conditional_p0_from_prior_audits: true
latest_full_backend_gate_commit: "661fe73cdd8222e9e0c6b88a45f565abd9cc6ed4"
latest_full_backend_gate_passed: 6074
latest_full_backend_gate_failed: 0
required_next_action: "make recovery origins canonical and fail closed, require authenticated TLS for SMTP, then prove both contracts through real HTTP and transport-negative tests"
---

# Recovery-Link- und Mail-Transport-Sicherheitsaudit

## Geltung und Quellenrangfolge

Dieser additive Folgeaudit dokumentiert die fünfte Read-only-Kontrollrunde auf
Repository-Head `497f19f2`. Er ergänzt, ersetzt aber nicht:

1. den
   [Electron-Runtime-/Releaseartefakt-Audit](2026-08-26-electron-runtime-release-security-audit.md),
2. den
   [Datenlebenszyklus-/Krypto-/Browser-Folgeaudit](2026-08-26-data-lifecycle-crypto-browser-followup-audit.md),
3. den
   [Auth-/Execution-/Operations-Folgeaudit](2026-08-25-auth-execution-operations-followup-audit.md),
4. den
   [PostgreSQL-/RLS-/Publikationsaudit](2026-08-25-asset-allocation-post-commit-integrity-audit.md),
5. den
   [technischen Optimizer-Handoff](2026-08-20-asset-allocation-stochastic-core-handoff.md).

Bei Widersprüchen gelten aktueller Code und reproduzierte Tests zuerst, danach
dieser Audit und anschließend die fünf vorgenannten Dokumente in dieser
Reihenfolge. Historische Deployment-, SMTP- und Browser-Hosting-Anleitungen
sind keine Freigabequelle.

Die Analyse hat keine Produkt- oder Testdatei verändert. Der grüne vollständige
Backend-Gate bleibt ein Regressionsnachweis für den eingecheckten
Optimizerstand, beweist aber weder einen vertrauenswürdigen Recovery-Link-Origin
noch einen verschlüsselten Mailtransport.

## Kurzurteil

**Release bleibt hart blockiert.** Zwei neue P1-Verträge sind offen:

1. Fehlt `PUBLIC_BASE_URL`, baut der öffentliche Passwort-Reset-Endpunkt den
   versendeten Bearer-Link aus `request.base_url`. Ohne `TrustedHostMiddleware`
   stammt diese Origin direkt aus dem vom Client gesetzten `Host`-Header. Ein
   Angreifer kann dadurch einen gültigen Reset-Link auf seine Domain in die
   echte E-Mail an das Opfer schreiben lassen. Invite- und Resend-Invite-Links
   verwenden denselben Fallback.
2. Produktion akzeptiert zugleich `SMTP_ENABLED=true`,
   `SMTP_USE_TLS=false` und eine fehlende, unverschlüsselte oder syntaktisch
   beliebige `PUBLIC_BASE_URL`. Der Mailer authentisiert und sendet dann über
   Klartext-SMTP. Damit können SMTP-Credentials sowie Reset-/Invite-Bearer ohne
   Transportverschlüsselung übertragen werden.

Die bereits dokumentierte Ablage der Token in URL-Query beziehungsweise
Accesslogs bleibt `OPS-008` des Auth-/Execution-/Operations-Audits und wird hier
nicht als neues Finding doppelt gezählt. Die beiden neuen Findings betreffen
Origin-Vertrauen und Transport **vor** beziehungsweise **während** der
Zustellung.

## Stabiles Findings-Register

| ID | Priorität | Status | Vertrag |
|---|---:|---|---|
| `RECOV-001` | P1 | offen | Jeder versendete Reset-/Invite-Link verwendet eine kanonische, validierte und request-unabhängige öffentliche HTTPS-Origin |
| `RECOV-002` | P1 | offen | Produktion versendet Recovery-Bearer und SMTP-Credentials ausschließlich über zertifikatsgeprüftes TLS; unsichere oder unvollständige Mailkonfiguration stoppt fail-closed |

Ein Finding darf erst nach rotem Negativtest, Produktfix, echter
Transport-/Proxyprüfung und vollständigem Gate auf demselben Fixcommit
geschlossen werden. Eine sichere Default-Einstellung, ein Mock ohne
Negativpfad oder ein korrekt konfigurierter Einzeltest beweist den Vertrag
nicht.

## Reproduktions- und Evidenzledger

| Scope | Methode | Ergebnis |
|---|---|---|
| Link-Origin ohne `PUBLIC_BASE_URL` | echte Starlette-`Request` mit synthetischem `Host: evil-attacker.example` gegen die produktiven Link-Helper | Reset- und Invite-Link verwendeten exakt die Angreifer-Origin |
| Produktionskonfiguration | direkte `Settings`-Validierung mit synthetischen Secrets | `SMTP_ENABLED=true`, `SMTP_USE_TLS=false`, `PUBLIC_BASE_URL=None` wurde akzeptiert |
| URL-Domäne | direkte `Settings`-Matrix | `None`, `http://...`, `javascript:...` und HTTPS mit Pfad wurden unverändert akzeptiert |
| Mailtransport | statischer Callgraph `mailer._send()` | bei `smtp_use_tls=false` erfolgen Login und `send_message` ohne TLS |
| Host-Schutz | Middleware-/App-Inventar | CORS ist aktiv; `TrustedHostMiddleware` oder äquivalente Host-Allowlist fehlt |
| Bestehende Regressionen | isolierte Temp-DB, drei Recovery-/Invite-Tests plus vollständige Mailer-Datei | 8 von 8 Tests grün; sie kodieren den unsicheren Fallback beziehungsweise nur den positiven TLS-Default |

Die deterministische Link-Reproduktion ergab:

```json
{
  "base_url": "https://evil-attacker.example/",
  "reset": "https://evil-attacker.example/app/5eyes_v2.html?reset=RESET_CANARY",
  "invite": "https://evil-attacker.example/app/5eyes_v2.html?invite=INVITE_CANARY"
}
```

Die Produktionskonfigurationsprobe ergab:

```json
{
  "accepted": true,
  "app_env": "production",
  "smtp_enabled": true,
  "smtp_use_tls": false,
  "public_base_url": null
}
```

Es wurden ausschließlich synthetische Canary-Werte verwendet. Kein echter
SMTP-Server, Account, Token, Schlüssel oder Kundendatensatz wurde kontaktiert.

## Befunde und verbindliche Fixverträge

### `RECOV-001` – Der Request-Host bestimmt versendete Bearer-Links

`5eyes-backend/routers/auth.py:597-611` bevorzugt zwar eine konfigurierte
`public_base_url`, fällt bei leerem Wert aber auf `request.base_url` zurück.
`password_reset_request()` ist öffentlich erreichbar, erzeugt einen gültigen
Reset-Token und übergibt den so gebauten Link an den Mailer
(`auth.py:614-645`). `invite_user()` und `resend_invite()` verwenden denselben
Mechanismus (`auth.py:768-782,785-840,1040-1081`).

Starlette bildet `request.base_url` aus Scheme und `Host`. Der konkrete
Backend-Stack registriert in `5eyes-backend/main.py:121-131` Request-Context und
CORS, aber keine `TrustedHostMiddleware`. CORS validiert Browser-Origins, nicht
den HTTP-Host und schützt auch keinen serverseitig versendeten Link.

Die Kommentare behaupten, `request.base_url` sei ein sicherer Ersatz, weil
`X-Forwarded-Host` nicht mehr explizit gelesen wird. Das ist unvollständig:
Auch der normale `Host`-Header ist Clientinput. Der vorhandene Test
`test_reset_link_falls_back_to_host_header_when_public_base_url_unset` kodiert
diesen Fallback ausdrücklich als Backwards-Kompatibilität. Der Invite-Test ohne
öffentliche Basis prüft nur einen manipulierten `X-Forwarded-Host`, nicht einen
manipulierten echten `Host`.

Ein Angreifer benötigt kein Konto und kein Token. Er sendet die bekannte
Benutzerkennung des Opfers mit seiner Domain als `Host`. Ist SMTP aktiv und
leitet der Edge diesen Host weiter, erhält das Opfer eine authentisch vom System
versendete E-Mail, deren gültiger Bearer auf die Angreiferdomain zeigt. Der
Angreifer kann den Token dort abgreifen und anschließend am echten Backend
verwenden.

**Fixvertrag:** In Staging, Produktion, Browser-Hosting und bei aktiviertem
SMTP ist eine kanonische `PUBLIC_BASE_URL` zwingend. Sie wird als strukturierte
URL validiert: ausschließlich `https`, keine Credentials, kein Query, Fragment
oder unerwarteter Pfad und eine explizit allowlistete externe Hostname-Origin.
Reset-/Invite-Linkbuilder erhalten diese Origin aus Konfiguration und lesen
niemals Request-Host oder Forwarded-Header. Fehlt oder widerspricht sie der
Deployment-Origin, stoppt der Prozess beziehungsweise der Versand fail-closed.

Zusätzlich verwendet die App `TrustedHostMiddleware` mit der deploymentweit
expliziten Host-Allowlist. Reverse-Proxy-Vertrauen und Forwarded-Header werden
zentral konfiguriert; direkter Uvicorn-Zugriff bleibt lokal. Die Middleware ist
Defense-in-depth und ersetzt die request-unabhängige Link-Origin nicht.

**Rote Tests:** Ein vollständiger HTTP-Test ruft
`/auth/password-reset/request` mit vorhandenem Benutzer und
`Host: evil-attacker.example` auf. Mail-Capture darf entweder ausschließlich
die konfigurierte HTTPS-Origin sehen oder der Request muss vor Token-/Mail-
Erzeugung scheitern. Die Matrix umfasst fehlende Origin, HTTP, Userinfo, Query,
Fragment, Pfad, Unicode-/Punycode-Verwechslung, Forwarded-Header und direkten
Uvicorn-Zugriff. Invite und Resend-Invite erhalten denselben Negativvertrag.

### `RECOV-002` – Produktion erlaubt Klartext-SMTP für Recovery-Bearer

`5eyes-backend/config.py:296-306` modelliert `smtp_use_tls` als frei
abschaltbares Boolean. Der Produktionsvalidator `config.py:516-557` koppelt
weder SMTP an TLS noch SMTP an eine gültige öffentliche HTTPS-Origin. Die
ausgeführte Settings-Probe bestätigte, dass die unsichere Kombination akzeptiert
wird. Auch syntaktisch beliebige `public_base_url`-Werte bleiben unverändert.

`5eyes-backend/services/mailer.py:28-42` öffnet immer zunächst
`smtplib.SMTP`. Nur wenn `smtp_use_tls` truthy ist, wird `starttls()` ausgeführt.
Bei `false` folgen `login()` und `send_message()` direkt auf der
unverschlüsselten Verbindung. Die Mailtexte enthalten den vollständigen
Reset- beziehungsweise Invite-Bearer (`mailer.py:48-65,81-98`). Somit betrifft
die Lücke nicht nur Vertraulichkeit der Nachricht, sondern bei SMTP-Auth auch
das SMTP-Passwort.

Der positive Pfad ist sinnvoll: Bei aktiviertem TLS wird
`ssl.create_default_context()` verwendet, und ein STARTTLS-Fehler wird
geschluckt, ohne anschließend zu senden. Das ist kein Downgrade. Offen bleibt,
dass Produktion die unsichere Abzweigung ausdrücklich akzeptiert und
Konfigurations-/Versandfehler nur als Warnung behandelt. Der Reset-Endpunkt
ignoriert den Boolean-Rückgabewert vollständig; damit fehlt zusätzlich ein
operativ beweisbarer Zustellstatus.

**Fixvertrag:** SMTP erhält einen expliziten Transportmodus wie
`starttls` oder `smtps`; `plaintext` ist außerhalb isolierter Tests verboten.
Bei Staging/Produktion mit `SMTP_ENABLED=true` müssen Host, Absender,
authentifizierter Transport, kanonische HTTPS-Origin und ein zertifikatsprüfender
TLS-Kontext bereits beim Startup gültig sein. STARTTLS muss vor Login und
Nachrichtenversand erfolgreich abgeschlossen sein; fehlende Capability,
Zertifikatsfehler oder Downgrade führen zu keinem Login und keinem Mailbyte.
Für Port 465 wird `SMTP_SSL`, für Submission ein verpflichtendes STARTTLS
verwendet. TLS-Mindestversion und Zertifikatsprüfung sind explizit.

Versanderfolg und -fehler werden ohne Token, URL-Query, Passwort oder
Empfänger-Personendaten beobachtbar protokolliert beziehungsweise metrisiert.
Der Reset-Endpunkt behält seine enumeration-sichere Antwort, Operations muss
einen fehlgeschlagenen Recovery-Versand aber erkennen können. Ein stilles
`SMTP_ENABLED=true` bei unvollständiger Konfiguration ist unzulässig.

**Rote Tests:** Ein Fake-SMTP protokolliert die Aufrufreihenfolge und verlangt
`connect -> STARTTLS/SSL -> login -> send`. Produktion mit TLS `false`, fehlendem
Host/Absender oder nicht-HTTPS-Public-Origin muss bei Settings-/Startup-
Validierung scheitern. Ein Server ohne STARTTLS, ein ungültiges Zertifikat und
ein TLS-Handshake-Abbruch dürfen weder Credentials noch Nachricht empfangen.
Logs und Auditdaten werden mit Secret-Canaries geprüft.

## Positive Kontrollen und Abgrenzung

- Ist `public_base_url` gesetzt, ignorieren beide Linkhelper den Request-Host;
  die vorhandenen positiven Tests dafür sind grün.
- Bei `smtp_use_tls=true` verwendet der Mailer den Standard-Zertifikatskontext
  und sendet nach einem STARTTLS-Fehler nicht im Klartext weiter.
- Der Reset-Request antwortet generisch und verhindert damit unmittelbare
  Konto-Enumeration.
- Die untersuchte Market-Data-Webhook-URL ist nur über Operator-/Environment-
  Konfiguration erreichbar und versendet in diesem Pfad Validierungsmetadaten,
  keine Auth-Credentials oder Mandantendatensätze. Ohne einen unprivilegierten
  Mutationspfad wurde daraus in dieser Runde kein neuer P0/P1 abgeleitet.
- Die festen Market-Data-Provider-Endpunkte verwenden HTTPS; es wurde kein neuer
  bestätigter Provider-SSRF- oder TLS-P1 gefunden.

Diese Abgrenzung ist keine Aussage, dass frei konfigurierbare Outbound-URLs nie
gehärtet werden müssen. HTTPS-Allowlist, DNS-/Redirect-Revalidierung und Sperren
für Loopback, Link-Local, private Netze und Cloud-Metadaten bleiben sinnvolle
Defense-in-depth, sind aber nicht Teil des neuen P1-Registers dieser Runde.

## Verbindliche Umsetzungsreihenfolge für Claude

### Block A – Origin fail-closed machen

1. Strukturierte Validierung für `PUBLIC_BASE_URL` implementieren.
2. In Staging/Produktion, Browser-Hosting und bei SMTP-Aktivierung eine
   kanonische HTTPS-Origin zwingend verlangen.
3. Request-Host-Fallback aus allen versendeten Reset-/Invite-Pfaden entfernen.
4. `TrustedHostMiddleware` und Proxy-Vertrauensgrenzen explizit konfigurieren.

### Block B – Mailtransport härten

1. SMTP-Transportmodus explizit modellieren; Plaintext außerhalb von Tests
   verbieten.
2. STARTTLS/SMTPS einschließlich Zertifikatsprüfung vor Auth und Send erzwingen.
3. Unvollständige Mailkonfiguration beim Startup ablehnen.
4. Enumeration-sichere, aber operativ sichtbare Versandfehler etablieren.

### Block C – E2E-Vertrag und Dokumentation

1. Host-/Proxy-/Origin-Negativmatrix über echte HTTP-Requests testen.
2. SMTP-Handshake, Downgrade, Zertifikat und Secret-Redaction testen.
3. Deploymentvorlagen nur mit kanonischer Origin und sicherem SMTP-Beispiel
   freigeben.
4. Danach alle vorherigen Releaseblocker weiterhin separat abarbeiten; dieser
   Fix hebt keinen PostgreSQL-, Auth-, Crypto-, Advisory- oder Desktopblocker
   auf.

## Verbindlicher Testvertrag

Neue oder erweiterte Suites mindestens:

- `5eyes-backend/tests/test_recovery_link_origin_security.py`
- `5eyes-backend/tests/test_mailer_transport_security.py`
- `5eyes-backend/tests/test_deployment_config_matrix.py`
- `5eyes-backend/tests/test_account_recovery.py`
- `5eyes-backend/tests/test_invite_onboarding.py`

Der Recovery-Test muss den kompletten Endpoint mit realem Mail-Capture und
synthetischem existierendem Benutzer ausführen. Ein direkter Helper-Test allein
reicht nicht. Der Mailtransport-Test braucht einen protokollierenden lokalen
SMTP-Testserver beziehungsweise ein kontrolliertes Transportdouble, das
Capability, TLS-Zustand und Byte-Reihenfolge beweist.

## Definition of Done

Dieser Block ist erst geschlossen, wenn:

- [ ] kein Request- oder Forwarded-Header einen versendeten Link beeinflusst;
- [ ] Staging/Produktion und SMTP-Betrieb ohne kanonische HTTPS-Origin nicht
      starten beziehungsweise nicht senden;
- [ ] ungültige Scheme-, Userinfo-, Pfad-, Query-, Fragment- und Hostwerte
      fail-closed abgelehnt werden;
- [ ] die App nur explizit erlaubte HTTP-Hosts annimmt und direkte
      Backendexposition weiterhin gesperrt ist;
- [ ] SMTP-Credentials und Recovery-Bearer niemals vor erfolgreichem,
      zertifikatsgeprüftem TLS übertragen werden;
- [ ] STARTTLS-/Zertifikats-/Konfigurationsfehler ohne Secret-Leak beobachtbar
      sind und keinen Klartext-Fallback auslösen;
- [ ] Reset, Invite und Resend-Invite dieselbe Origin-/Transportmatrix erfüllen;
- [ ] URL-Query-/Accesslog-Secrets aus `OPS-008` zusätzlich geschlossen sind;
- [ ] fokussierter Auth-/Mailer-/Config-Ring und vollständiger Backend-Gate auf
      demselben Fixcommit grün sind;
- [ ] Security und Operations die echte Proxy-/SMTP-Zielumgebung abgenommen
      haben.

## Claude-Startcheckliste

1. Dieses Dokument und danach alle fünf Vorgängeraudits vollständig lesen.
2. Zuerst rote Endpoint-Tests mit echtem `Host`-Header und Mail-Capture schreiben.
3. Keine request-abgeleitete Origin in E-Mail-, Signatur- oder Recovery-Links
   verwenden.
4. Kein SMTP-Login und kein Mailbyte vor nachgewiesenem TLS zulassen.
5. `PUBLIC_BASE_URL` als Origin, nicht als beliebigen String behandeln.
6. Den generischen Reset-Response nicht zur Konto-Enumeration öffnen; Fehler
   intern secretfrei beobachtbar machen.
7. Keine vorhandenen P0/P1 aus früheren Audits durch diesen begrenzten Fix als
   geschlossen markieren.
8. Pro Finding roten Test, Produktfix, fokussierten Ring und vollständigen Gate
   auf demselben Commit dokumentieren.

## Dokumentationsmanifest dieser Runde

Dieses Dokumentationsbatch umfasst exakt:

1. `docs/audits/2026-08-27-recovery-link-mail-transport-security-audit.md`
2. `docs/ASSET_ALLOCATION_OPTIMIZER_HANDOFF.md`
3. `docs/CLAUDE_HANDOFF.md`
4. `docs/deploy/README.md`
5. `docs/deploy/provisioning-runbook.md`

Der Commit dieses Dokuments wird nicht in den eigenen Inhalt eingebettet.
Auflösung ausschließlich extern über `document_commit_resolution`.

## Dokumentations-QA vor Commit

- reine Link-Reproduktion mit synthetischem Host: bestätigt;
- Produktions-Settings-Matrix: unsichere Kombination bestätigt;
- isolierter Recovery-/Invite-/Mailer-Ring: 8 von 8 Tests grün;
- Finding-Register: 2 eindeutige IDs, 2 zugehörige Detailsektionen;
- Produkt- und Testdateien: unverändert;
- lokale Links, Markdown-Fences, Manifest und `git diff --check`: vor Commit
  vollständig zu prüfen;
- die 53 bekannten ACL-unlesbaren `.pytest_tmp_*`-Verzeichnisse wurden weder
  gelesen noch verändert; deshalb kein globaler Clean-Claim.
