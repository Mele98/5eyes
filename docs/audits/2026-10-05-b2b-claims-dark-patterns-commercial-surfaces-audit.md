---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "b2b-claims-dark-patterns-commercial-surfaces-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "5eyes-b2b-04"
branch: "codex/b2b-claims-dark-patterns-audit"
audited_repository_head: "8dfd6cc13a7869e1996331e5d226551fc441a6ee"
audit_mode: "read_only_claim_inventory_dark_pattern_and_commercial_surface_review"
audit_mutated_product_code: false
scope: "Starke Compliance-/Rechtsclaims in UI, React-Reporting und PDF; Dark-Pattern-Heuristik (Button-Symmetrie, vorangekreuzte Optionen, Loeschpfade, Drucksprache); Bestaetigung der Abwesenheit von Review-/Testimonial- und Checkout-/Payment-Funktionen; Trennung Transaktions-/Marketing-E-Mail"
---

# Claims-, Dark-Pattern- und Commercial-Surface-Audit

**Runde 4 von B2B-Trust-Pre-Implementation-Coverage-Audit · Antwort auf `B2B-COVERAGE-005` · Stand 05.10.2026**

## Kurzfazit

Dieser Audit bestaetigt den Kernbefund von `B2B-COVERAGE-005`: Es existiert
**kein zentrales Claim-Register**. Mehrere starke, kanalgleich wiederholte
Aussagen (`FINMA-konforme Eignungspruefung`, `FINMA-konformes PDF-Layout`,
`RISK BUDGET VALIDATED`, eine konkrete Gesetzesartikel-/Literaturzitat-Zeile)
sind im Classic-Frontend, in der React-Reporting-App und im PDF-Generator
verstreut, ohne Evidenzpfad, Owner oder Ablaufdatum. Ein bereits vom
Meta-Audit benannter Dokumentationsdrift wurde **eigenstaendig nachvollzogen
und bestaetigt**: `docs/compliance/finma-outsourcing-anzeige.md` behauptet
Datenexport/-loeschung nach revDSG Art. 25 seien „bereits umgesetzt“, waehrend
derselbe Code-Stand im Datenlebenszyklus-Folgeaudit sechs offene P1-Vertraege
zu genau diesem Thema ausweist.

Fuer Dark Patterns ergibt die Stichprobe ein **gemischtes, ueberwiegend
unauffaelliges Bild**: Abbrechen-/Bestaetigen-Buttons sind in Groesse,
Schriftgroesse und Padding identisch (nur Fuellfarbe unterscheidet sich),
destruktive Aktionen laufen durch native, nicht stylebare
`window.confirm()`-Dialoge, und es wurden **keine** vorangekreuzten
Marketing-, Tracking- oder Datenweitergabe-Checkboxen gefunden. Ein konkreter,
dokumentationswuerdiger Befund wurde dennoch gefunden: Der Kunden-Hard-Delete
(`DELETE /clients/{id}`) existiert nur im Backend — im gesamten
Classic-Frontend ruft keine Funktion diesen Endpunkt auf. Waehrend das
Anlegen eines Kunden ein Formular plus Speichern ist, gibt es fuer das
Loeschen/Beenden eines Mandatsverhaeltnisses **keinen einzigen UI-Pfad**.

Die beiden „kein Fund“-Behauptungen des Meta-Audits wurden eigenstaendig per
Grep bestaetigt: Es existiert weder ein Kundenbewertungs-/Testimonial-System
noch ein Checkout-/Payment-Code-Pfad (Stripe/PayPal/Kreditkarte) im Repository.
Ebenso bestaetigt: `services/mailer.py` versendet ausschliesslich
Einladungs- und Passwort-Reset-Mails; beide sind transaktional, keine
Marketing-/Newsletter-Logik vorhanden.

Dieses Dokument faellt **kein Rechtsurteil**, ob eine der genannten
Formulierungen „FINMA-konform“, „irrefuehrend“ oder rechtlich unzulaessig ist.
Es dokumentiert nur Fundort, Wortlaut und das konkrete Code-/Audit-Gegenstueck.

## Auditbasis und Scope

Auditiert wurde Commit `8dfd6cc13a7869e1996331e5d226551fc441a6ee` auf Branch
`codex/b2b-claims-dark-patterns-audit` (HEAD = `origin/develop`). Es wurden
**keine** Produktionsdateien, Tests oder Konfigurationen veraendert — nur
dieses eine neue Audit-Dokument wurde erstellt.

Quellen fuer die Auftragsdefinition:
- `docs/audits/2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md`
  (externes Referenzdokument, Finding `B2B-COVERAGE-005`)
- `docs/compliance/2026-10-05-trust-compliance-accessibility-readiness-plan.md`
  (externes Referenzdokument, Arbeitspaket 7 / `FAIR-04`, `FAIR-07`)

Durchsucht wurden:
- `5eyes-electron/frontend/5eyes_v2.html` (Classic-Monolith-Frontend)
- `5eyes-electron/frontend/reporting/src/**` (React-Reporting-Sub-App)
- `5eyes-backend/services/pdf/**` (PDF-Generator)
- `5eyes-backend/services/mailer.py` (E-Mail-Versand)
- `5eyes-backend/routers/clients.py` (Kunden-CRUD inkl. Delete/Erasure)
- `docs/compliance/**` (Rechts-/Compliance-Vorlagen)
- `docs/audits/**` (Dateinamen-Inventar; zwei einschlaegige Folgeaudits im
  Volltext: `2026-08-26-data-lifecycle-crypto-browser-followup-audit.md` und
  `2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md`)
- `docs/CLAUDE_HANDOFF.md` (oberste ~220 Zeilen, als laufendes
  Fach-/Entscheidungsprotokoll, nicht als P0/P1-Statusliste — siehe
  Einschraenkung unten)

## Findings-Register

| ID | Prioritaet | Thema | Status |
|---|---:|---|---|
| `CLAIM-REGISTER-001` | P1 | Kein zentrales Register fuer `FINMA-konform`/`FIDLEG-konform`-Aussagen in UI/Reporting/PDF | offen |
| `CLAIM-DRIFT-001` | P0 | `finma-outsourcing-anzeige.md` behauptet DSAR-Export/-Loeschung als umgesetzt; Datenlebenszyklus-Audit widerspricht mit 5 offenen P1 | offen, bestaetigt |
| `CLAIM-REGISTER-002` | P1 | Intro-Splash wirbt mit `RISK BUDGET VALIDATED`/`VALID`, waehrend ein eigener Release-Hold-Audit zum Risikobudget-Fallback offen ist | offen, bestaetigt |
| `CLAIM-REGISTER-003` | P2 | Gesetzesartikel- und Literaturzitat (`FINMA Art. 6 FIDLEG`, Brinson/Hood/Beebower 1986) in Tooltip-Text ohne Quellenbeleg/Versionierung | offen |
| `DARKPATTERN-001` | — (kein Befund) | Abbrechen-/Bestaetigen-Buttons in Modals sind groessen-/schriftgleich; keine asymmetrische Gewichtung gefunden | geprueft, kein Fund |
| `DARKPATTERN-002` | — (kein Befund) | Keine vorangekreuzte Marketing-/Tracking-/Datenweitergabe-Checkbox gefunden; alle vorangehakten Boxen sind Produktdefaults | geprueft, kein Fund |
| `DARKPATTERN-003` | P1 | `DELETE /clients/{id}` existiert nur im Backend; kein einziger Frontend-Aufruf — Kundenloeschung hat keinen UI-Pfad | offen, bestaetigt |
| `COMMERCIAL-001` | — (kein Befund) | Kein Review-/Testimonial-/Rating-System im Code gefunden | bestaetigt per Grep |
| `COMMERCIAL-002` | — (kein Befund) | Kein Checkout-/Payment-Code (Stripe/PayPal/Kreditkarte) im Code gefunden | bestaetigt per Grep |
| `COMMERCIAL-003` | — (kein Befund) | `services/mailer.py` versendet ausschliesslich transaktionale Mails (Invite, Passwort-Reset); keine Marketing-/Newsletter-Logik | bestaetigt |

## `CLAIM-REGISTER-001` — Kein zentrales Register fuer starke Konformitaetsaussagen

**Repository-Beleg:**

Classic-Frontend (`5eyes-electron/frontend/5eyes_v2.html`):
- Zeile 2985: `<div class="ph-t">Risikoprofilierung (FINMA Eignungspruefung)</div>`
  — Seitentitel der Risikoprofil-Maske, jedem Berater bei jedem Mandat sichtbar.
- Zeile 2991: `<span class="cht">Fragebogen FINMA Eignungspruefung</span>`
  — Kartentitel direkt ueber dem Risikofragebogen.
- Zeile 9482: `riskPdfBody.innerHTML='...Das Risikoprofil-Dokument wird als
  serverseitiges PDF mit stabilem FINMA-Layout generiert.'` — Text in einem
  Druck-Dialog, direkt im UI sichtbar.
- Zeile 8389/8667-8668: Code-Kommentare bezeichnen die aktive PDF-Variante als
  „FINMA-konforme Version“ bzw. verweisen auf eine Vorgabe „Risikoprofil ist
  FINMA-konform, nicht UX-refactorn“ (interne Leitplanke, kein Nutzertext).
- Zeile 4804-4809: Tooltip-Box `nz-saa-info` zitiert explizit
  „FINMA Art. 6 FIDLEG“ neben einer akademischen Quellenangabe
  (siehe `CLAIM-REGISTER-003`).

React-Reporting-App (`5eyes-electron/frontend/reporting/src/pages/`):
- `Risikoprofil.tsx:25`: `subtitle="FINMA-konforme Eignungsprüfung — Score,
  Profil, Begründung."`
- `Eignung.tsx:57`: `subtitle="FINMA-/FIDLEG-konforme Pruefung der
  Anlagestrategie gegen Risikoprofil, Kenntnisse und Erfahrung."`
- `Eignung.tsx:258-259` / identisch `advisory_report.py:3063-3065` (PDF):
  „Vor der Umsetzung der Anlagestrategie ist eine FINMA-konforme
  Eignungspruefung (Suitability nach FIDLEG) durchzufuehren...“ — derselbe
  Text erscheint wortgleich im React-Empty-State und im Backend-PDF-Code,
  ohne gemeinsame Quelle/Konstante (zwei unabhaengig gepflegte Kopien).
- `Compliance.tsx:64`: `subtitle="Übersicht der FIDLEG/FINMA-relevanten
  Audit-Pruefungen für dieses Mandat."`

Backend-PDF (`5eyes-backend/services/pdf/`):
- `documents/advisory_report.py:2034`: Docstring „FINMA-konforme
  Beratungsprotokoll-Übersicht im PDF.“
- `documents/advisory_report.py:3063-3065`: tatsaechlich gedruckter
  Fliesstext (siehe oben) im Kunden-PDF, nicht nur Code-Kommentar.
- `documents/risikoprofil.py:1`: Moduldocstring „vollständige
  FINMA-taugliche Kundendokumentation“.
- `components/compliance_audit.py:53`: „Kompakte FINMA-Audit-Sicht auf
  Geeignetheitspruefung...“.

**Befund:** Mindestens drei unabhaengige Code-/Dokumentlager (Classic-HTML,
React-Reporting, PDF-Python) fuehren denselben Claim-Typ
(„FINMA-konform“/„FIDLEG-konform“) in eigenen, unkoordinierten Textkopien.
Es gibt keine gemeinsame Konstante, kein Owner-Feld, kein Ablaufdatum und
keinen automatisierten Phrasen-Gate-Test, der verhindert, dass dieser
Claim-Typ unbemerkt in weiteren Bildschirmen auftaucht oder veraltet. Eine
positive Teilkontrolle existiert: `reporting/DESIGN_SYSTEM.md:16/211-212`
definiert explizit „FINMA-bewusst: Keine Garantieversprechen. Keine
Emotionalisierung“ und `ErrorBoundary.test.tsx:70` prueft automatisiert, dass
Fehlermeldungen nie das Wort „garantiert“ enthalten — das ist jedoch ein
punktueller Lint, kein Register fuer die hier gefundenen „konform“-Aussagen
selbst.

**Auditvertrag:** Siehe `B2B-COVERAGE-005`/`FAIR-07` im Referenzdokument: ein
zentrales Claim-Register mit exaktem Text, Kanal (Classic-UI/React/PDF),
Evidenzpfad, Rechts-/Fachowner und Gueltigkeitsdatum pro Formulierung.
Mehrfachkopien desselben Claims muessen auf eine gemeinsame Quelle
zurueckgefuehrt werden, damit eine Aenderung/Ruecknahme nicht an einer Stelle
vergessen werden kann.

## `CLAIM-DRIFT-001` — Bestaetigter Dokumentationsdrift DSAR/Loeschung

**Repository-Beleg:**

`docs/compliance/finma-outsourcing-anzeige.md:57`:
```
| Exit-Strategie | Datenexport (revDSG Art. 25), Rückgabe/Löschung nach Vertragsende |
```
`docs/compliance/finma-outsourcing-anzeige.md:64`:
```
- Datenexport-/Lösch-Funktion (revDSG Art. 25 bereits umgesetzt).
```

Dieselbe Codebasis dokumentiert im selbenrepository, nur sechs Wochen
frueher datiert, `docs/audits/2026-08-26-data-lifecycle-crypto-browser-followup-audit.md`:
- Zeile 79: `PRIV-001 | P1 | offen | Client-Löschung sperrt Zugriff und
  verarbeitet alle Kinddaten nach einem expliziten Lifecycle`
- Zeile 80: `PRIV-002 | P1 | offen | DSAR-/Portabilitätsexport ist
  vollständig, versioniert und fail-closed`
- Zeile 82: `PRIV-004 | P1 | offen | Tenant- und User-Offboarding besitzt
  Export-, Sperr-, Lösch- und Bestätigungsworkflow`
- Zeile 83: `PRIV-005 | P1 | offen | Restore reaktiviert kein bereits
  gelöschtes oder anonymisiertes Subjekt`
- Detailabschnitte `PRIV-001` (Zeile 130: „Client-DELETE hinterlässt aktive
  Subjektdaten und sperrt den Export“), `PRIV-002` (Zeile 147: „DSAR-
  /Portabilitätsexport ist unvollständig und fail-soft“) und `PRIV-005`
  (Zeile 191: „Altes Restore reaktiviert gelöschte Personen“) beschreiben die
  konkreten technischen Luecken.

**Befund:** Die Vorlage behauptet uneingeschraenkt, die Lösch-/Exportfunktion
sei „bereits umgesetzt“. Der unabhaengige Folgeaudit zur selben Funktion
dokumentiert zum Zeitpunkt dieses Audits fünf noch offene P1-Vertraege genau
in diesem Bereich (unvollstaendiger Export, Kinddaten-Lifecycle, fehlendes
Offboarding, reaktivierbare geloeschte Personen). Dies ist der vom Meta-Audit
benannte Drift — hier mit eigenen Zeilenbelegen aus beiden Dokumenten
bestaetigt, nicht nur uebernommen.

**Auditvertrag:** `docs/compliance/finma-outsourcing-anzeige.md` darf nicht
als freigegebene Evidenz fuer eine bereits umgesetzte Exit-/Loeschfunktion an
Kunden, Pruefer oder FINMA weitergegeben werden, solange `PRIV-001/002/004/005`
offen sind. Die Vorlage benoetigt eine klare Kennzeichnung
(„Platzhalter — technischer Stand siehe `PRIV-00x`“) oder eine Korrektur des
Satzes „bereits umgesetzt“, bis die referenzierten Findings geschlossen sind.

## `CLAIM-REGISTER-002` — „RISK BUDGET VALIDATED“ im Intro-Splash vs. offener Release-Hold

**Repository-Beleg:**

`5eyes-electron/frontend/5eyes_v2.html:1190`:
```html
<div class="intro-signal"><span>RISK BUDGET</span><em>VALID</em></div>
```
`5eyes-electron/frontend/5eyes_v2.html:1196-1197` (Laufband, zweifach
wiederholt fuer Endlosschleife):
```html
<span>RISK BUDGET VALIDATED</span>
```
`5eyes-electron/frontend/5eyes_v2.html:1228`:
```js
var steps=['Wealth structure mapping','Strategic allocation synchronized',
  'Private markets and liquidity mapped','Risk budget and goals validated',
  'Advisory environment ready'];
```

Dies ist eine rein dekorative Ladebildschirm-Animation (`intro-screen`), die
bei jedem Session-Start einmalig gezeigt wird (`sessionStorage.introShown`).
Sie ist an keinen echten Berechnungszustand gebunden — die Badges
„VALID“/„VALIDATED“ erscheinen unabhaengig davon, ob fuer das aktuell
geoeffnete Mandat tatsaechlich ein valides Risikobudget vorliegt.

Zeitgleich dokumentiert
`docs/audits/2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md:1-3`:
```
# Risikobudget-Fallback-, Context- und Finalisierungs-Integritätsaudit
**Kontrollrunde 43 · Stand 04.10.2026 · Status: Release-Hold**
```
— ein eigenstaendiger, zum Zeitpunkt dieses Audits offener Release-Hold zum
Risikobudget-Fallback-Verhalten.

**Befund:** Die App zeigt bei jedem Start eine App-weite, generische
Marketing-/Statusanimation mit dem Wortlaut „RISK BUDGET VALIDATED“, die
nichts mit dem tatsaechlichen, mandatsspezifischen Pruefzustand zu tun hat.
Dieser Text ist unabhaengig vom Risikoprofil-/Risikobudget-Zustand des
aktiven Mandats immer gleich und erscheint zufaellig im selben Produkt, das
andernorts einen offenen Release-Hold zu exakt diesem Thema fuehrt. Es handelt
sich nicht um einen Daten-Bug (die Animation liest keine echten Werte), aber
um einen Wortlaut, der als Zusicherung gelesen werden kann.

**Auditvertrag:** Marketing-/Ambiente-Text, der Fachbegriffe wie „risk
budget“, „validated“ in einer Kompetenz-/Statusaussage verwendet, gehoert in
dasselbe Claim-Register wie fachliche FINMA-Aussagen und muss gegen den
realen Pruefzustand abgeglichen oder als rein dekorativ/nicht-faktisch
gekennzeichnet werden.

## `CLAIM-REGISTER-003` — Gesetzes- und Literaturzitat in Tooltip ohne Belegpfad

**Repository-Beleg:** `5eyes-electron/frontend/5eyes_v2.html:4804-4809`:
```html
<div id="nz-saa-info" ...>
  <strong>Wissenschaftliche Logik:</strong> Goal-Änderungen beeinflussen die
  <strong>Zielerreichungs-Wahrscheinlichkeit</strong>, nicht die strategische
  Asset-Allocation. Die SAA wird durch dein <strong>Risikoprofil</strong>
  definiert (FINMA Art. 6 FIDLEG &middot; Strategietreue &middot;
  Brinson/Hood/Beebower 1986).
</div>
```

**Befund:** Dieser Infotext zitiert eine konkrete Gesetzesnorm
(„FINMA Art. 6 FIDLEG“ — Anm.: FIDLEG ist ein Bundesgesetz, nicht eine
FINMA-Verordnung; die Quellenbezeichnung selbst ist damit bereits
uneinheitlich) sowie eine akademische Publikation (Brinson, Hood, Beebower
1986) als Begruendung fuer ein Produktverhalten. Weder im Code noch in
`docs/compliance/` wurde ein Beleg, eine Versionierung oder eine
Rechtspruefung dieser spezifischen Zeile gefunden. Anders als die
generischen „FINMA-konform“-Claims ist dies ein **spezifisches Zitat**, das
bei einer Rechts- oder Kundenpruefung direkt nachgeschlagen werden kann.

**Auditvertrag:** Jedes Gesetzes- oder Literaturzitat in Kunden-/Beratersicht
braucht einen nachvollziehbaren Beleg (korrekte Fundstelle, Pruefdatum,
Fachowner) im selben Claim-Register wie `CLAIM-REGISTER-001`.

## `DARKPATTERN-001` — Button-Symmetrie Abbrechen/Bestaetigen (kein Befund)

**Repository-Beleg:** CSS-Definitionen in `5eyes_v2.html`:
```css
.btn{background:none;border:1px solid var(--b2);border-radius:var(--r);
  font-family:var(--f-s);font-size:11px;color:var(--n6);padding:6px 13px;...}
.btn-p{background:var(--chrome-n6);color:#fff;border:none;border-radius:var(--r);
  font-family:var(--f-s);font-size:11px;font-weight:500;padding:6px 13px;...}
.btn-g{background:var(--g4);color:var(--chrome-n8);border:none;border-radius:var(--r);
  font-family:var(--f-s);font-size:11px;font-weight:600;padding:6px 13px;...}
```
(Zeilen 173/175/177). Alle drei Klassen teilen `font-size:11px` und
`padding:6px 13px`; nur Fuellfarbe/Fontgewicht unterscheiden sich. In
Modal-Footern (z.B. Zeile 5113, 9778-9781) steht `Abbrechen` (`.btn`) stets
gleichwertig neben der primaeren Aktion (`.btn-p`/`.btn-g`), nicht grau
abgeblendet oder verkleinert.

Eine Ausnahme mit geringerer Tragweite wurde notiert: Die
Goal-Loeschen-Aktion in der Cashflow-Karte ist kleiner skaliert
(`.goal-actions .btn{padding:5px 8px;font-size:9px}`,
`.goal-delete-action{...color:var(--n4);font-size:9px}`, Zeilen 482-483) —
also bewusst unauffaelliger als Standardbuttons. Das ist eine uebliche
Massnahme gegen Fehlklicks bei destruktiven Inline-Aktionen und nicht
automatisch ein Dark Pattern; es wird hier nur als Randnotiz dokumentiert,
nicht als eigener Finding gefuehrt.

Destruktive Aktionen (Positionen/Cashflows/Ziele loeschen, Zeilen 13222,
17369, 20779, 20795) laufen durchgaengig ueber native `window.confirm()` mit
sachlichem Fragetext („... wirklich löschen?“), nicht ueber eigene Modals mit
gestalteter Button-Hierarchie — ein natives OS-Dialogfeld kann nicht
asymmetrisch gestylt werden.

**Befund:** Keine Evidenz fuer ein klassisches Confirmshaming-/
Button-Groessen-Dark-Pattern im untersuchten UI.

## `DARKPATTERN-002` — Vorangekreuzte Checkboxen (kein Befund fuer Consent/Marketing)

**Repository-Beleg:** Alle in `5eyes_v2.html` gefundenen standardmaessig
`checked`-Checkboxen/Radios wurden einzeln geprueft, u.a.:
- Zeile 3318-3319 `cf-indexation-toggle` (Cashflow-Indexierung an/aus) —
  fachlicher Rechenmodus, kein Consent.
- Zeilen 3642-3782 (`aa-product-funds-only`, `aa-equities-large-cap`,
  `aa-bonds-investment-grade`, `aa-realestate-funds`, `aa-alts-gold` u.a.) —
  vorbelegte Anlagepraeferenzen im Asset-Allocation-Formular, vom Berater
  editierbar, keine Datenweitergabe/Marketing.
- Zeile 17438 `ev-calendar` („Kalendereintrag für den Review mitgeben (.ics)“)
  — Komfort-Default, keine Datenweitergabe an Dritte.
- Zeile 26666 `ul-show-inactive` — Admin-Anzeigefilter.

Es wurde **keine** Checkbox gefunden, die einen optionalen
Marketing-/Tracking-/Datenweitergabe-Zweck vorbelegt aktiviert. Die
Telemetrie selbst besitzt im Backend keinen UI-Schalter und ist per
`config.py:218` (`telemetry_enabled: bool = False`) serverseitig
default-deaktiviert; es gibt dafuer keine Frontend-Checkbox ueberhaupt
(weder vorangekreuzt noch leer).

**Befund:** Keine Evidenz fuer vorangekreuzte optionale Consent-/
Marketing-Checkboxen. Alle gefundenen Default-`checked`-Felder betreffen
fachliche Produktdefaults, keine datenschutz- oder marketingrelevanten
Einwilligungen.

## `DARKPATTERN-003` — Kundenloeschung ohne UI-Pfad

**Repository-Beleg:** `5eyes-backend/routers/clients.py:154-167`:
```python
@router.delete("/{client_id}", status_code=204)
def delete_client(
    client_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    ...
    client.deleted_at = _now()
    log(db, ..., action="DELETE", ...)
    db.commit()
```
Der Endpunkt existiert und ist ein Soft-Delete (`deleted_at`-Zeitstempel,
auditiert). Eine gezielte Suche im kompletten Classic-Frontend nach jedem
Aufruf von `API.del('/clients/...')` ergab ausschliesslich:
```
5eyes-electron/frontend/5eyes_v2.html:17377: API.del('/clients/'+cid+'/wealth-positions/'+positionId)
5eyes-electron/frontend/5eyes_v2.html:20782: API.del('/clients/'+cid+'/cashflows/'+cfId)
```
— also Loeschaufrufe fuer einzelne Vermoegenspositionen und Cashflows,
**aber keiner** fuer `DELETE /clients/{client_id}` selbst. Ebenso wurde keine
Frontend-Funktion mit Namen wie `deleteClient`, `archiveClient` o.ae.
gefunden, und auch der separate Erasure-Pfad (`services/client_erasure.py`,
von `clients.py` importiert) hat keine erkennbare UI-Anbindung in
`5eyes_v2.html` (keine Treffer fuer „erasure“/„anonymisieren“ im Frontend).

Im Vergleich dazu ist das Anlegen eines Kunden ein einzelnes Formular plus
`API.post('/clients', ...)` (Zeile 76 in `clients.py`, direkt per UI
erreichbar über die Kundenliste).

**Befund:** Es gibt einen funktionierenden, auditierten Backend-Endpunkt zum
Loeschen eines Kunden, aber **keinen** Weg, ihn aus der Beratersicht heraus
aufzurufen. Das Anlegen eines Mandatsverhaeltnisses ist trivial einfach; das
Beenden/Loeschen eines Kundenverhaeltnisses ist aus der UI schlicht nicht
erreichbar — nicht weil es absichtlich erschwert waere (kein
Mehrklick-Labyrinth, keine versteckte Untermenue-Kette wurde gefunden),
sondern weil der Pfad **komplett fehlt**. Das ist dieselbe Luecke, die
`B2B-COVERAGE-003` (operativer Lifecycle) und `TRUST-08`
(Loeschung/Offboarding) aus anderer Richtung schon beschreiben; hier wird sie
zusaetzlich aus der reinen UI-Erreichbarkeits-Perspektive bestaetigt.

**Auditvertrag:** Sobald `TRUST-08`/`PRIV-001` fachlich entschieden ist (Soft-
Delete, Anonymisierung oder vollstaendige Erasure als Zielzustand), braucht es
einen sichtbaren, auditierten UI-Einstiegspunkt dafuer — nicht primaer, um
„Loeschen leicht zu machen“, sondern damit Berater/Compliance den bestehenden
Backend-Vertrag ueberhaupt nutzen koennen. Bis dahin ist zu dokumentieren,
dass Kundenloeschung derzeit nur per direktem API-Zugriff moeglich ist.

## `COMMERCIAL-001`/`COMMERCIAL-002` — Bestaetigte Abwesenheit von Review- und Payment-Funktionen

**Vorgehen:** Repository-weite Grep-Suche (case-insensitive) nach
`testimonial`, `stripe`, `paypal`, `credit.?card`, `checkout`,
`payment_intent`, `star.?rating`, `kundenbewertung` in
`5eyes-electron/**` und `5eyes-backend/**` (ausserhalb von `docs/`, `.git`,
Node-/Build-Artefakten).

**Ergebnis:** Keine Treffer in Produktcode. (Eine breitere, undifferenzierte
Suche nach dem blossen Wort „review“ liefert zahlreiche Treffer, aber
ausschliesslich fuer das Produktfeature „Review & Abschluss“ — die
Abschlussseite des Beratungsprozesses — und fuer Code-Review-/Audit-Doku;
keiner davon ist ein Kundenbewertungs-/Testimonial-System.)

**Befund:** Die Behauptung des Meta-Audits („kein Kundenreview-/
Bewertungssystem, kein oeffentlicher Checkout im Produktcode“) wird
eigenstaendig bestaetigt.

## `COMMERCIAL-003` — Mailer sendet ausschliesslich Transaktions-Mails

**Repository-Beleg:** `5eyes-backend/services/mailer.py` definiert genau zwei
Versandfunktionen:
- `send_invite_email` (Zeile 102-111) — Betreff „Ihr Zugang zu 5eyes — Konto
  aktivieren“ (Zeile 83), Text mit Aktivierungslink, 7 Tage gueltig.
- `send_password_reset_email` (Zeile 134-143) — Betreff „5eyes — Passwort
  zuruecksetzen“ (Zeile 116), Text mit Reset-Link, 2 Stunden gueltig.

Beide Funktionen liefern `False` zurueck, wenn SMTP nicht konfiguriert ist
(`mail_configured()`, Zeile 52-58) oder die Zieladresse das defensive
Einzelempfaenger-Format nicht erfuellt (Zeile 45/109/141) — der Aufrufer
faellt dann auf einen manuellen Link-Copy-Flow zurueck; es gibt laut Code
keinen dritten E-Mail-Typ.

**Befund:** Bestaetigt — ausschliesslich transaktionale Mails, keine
Marketing-/Newsletter-Logik, kein Massenversand-Pfad im Code gefunden. Ein
Unsubscribe-Link waere hier sachlich fehl am Platz (deckt sich mit `FAIR-10`
im Referenzdokument).

## Verifikation dieser Runde

- Grep-Suche (case-insensitive) nach `FINMA`, `konform`, `compliant`,
  `validated`, `garantiert`, `zertifiziert`, `geprueft`/`geprüft`,
  `BANKING STANDARD`, `bank-grade`, `sicher` ueber
  `5eyes-electron/frontend/` und `5eyes-backend/services/pdf/`, Treffer
  einzeln gegen den jeweiligen Datei-Kontext gelesen (nicht nur
  Treffer-Zeile).
- `docs/compliance/finma-outsourcing-anzeige.md` vollstaendig gelesen;
  Zeile 57/64 gegen `docs/audits/2026-08-26-data-lifecycle-crypto-browser-followup-audit.md`
  (Findings-Tabelle + Detailabschnitte `PRIV-001/002/004/005`) abgeglichen.
- `docs/audits/2026-10-04-risk-budget-fallback-context-and-finalization-integrity-audit.md`
  Kopfzeilen gelesen zur Bestaetigung des offenen Release-Hold-Status.
- CSS-Definitionen `.btn`/`.btn-p`/`.btn-g` und alle `checked`-Treffer in
  `5eyes_v2.html` einzeln gesichtet.
- `routers/clients.py` vollstaendig fuer CRUD- und Erasure-Pfade gelesen;
  gezielte Gegen-Suche nach `API.del('/clients/...')`-Aufrufen im Frontend,
  um einen UI-Pfad fuer den Delete-Endpunkt zu finden oder auszuschliessen.
- `services/mailer.py` vollstaendig gelesen.
- Repository-weite Grep-Suche nach Review-/Testimonial-/Payment-Begriffen in
  `5eyes-electron/` und `5eyes-backend/` (ausserhalb `docs/`).
- `docs/CLAUDE_HANDOFF.md` oberste ~220 Zeilen gelesen (fachliches
  Entscheidungs-/Uebergabeprotokoll, keine P0/P1-Statusliste — siehe
  Einschraenkung unten).
- `git rev-parse HEAD` bestaetigt `8dfd6cc13a7869e1996331e5d226551fc441a6ee`;
  keine weiteren Dateien als dieses Audit-Dokument wurden erzeugt oder
  veraendert.

## Selbst-Audit und Nachweisgrenzen

- Produktcode, Tests, Konfiguration: **nicht veraendert**. Es wurde genau
  eine neue Datei erstellt: dieses Dokument.
- `docs/CLAUDE_HANDOFF.md` ist ein chronologisches Codex/Claude-Uebergabe-
  protokoll, keine kuratierte P0/P1-Statusliste. Die in diesem Audit
  verwendete Aussage „welche Themenbereiche offene Release-Blocker haben“
  stuetzt sich daher primaer auf die Dateinamen/Statuszeilen der
  `docs/audits/*.md`-Dokumente selbst (z.B. „Status: Release-Hold“) und auf
  das explizit benannte Referenzdokument `2026-08-26-...followup-audit.md`,
  nicht auf eine Vollanalyse von `CLAUDE_HANDOFF.md`.
- Die Grep-Suchen sind so breit wie sinnvoll gewaehlt, aber nicht
  erschoepfend fuer jede denkbare Umschreibung eines Claims (z.B. englische
  Synonyme ausserhalb der vorgegebenen Begriffsliste, Bilddateien mit
  eingebranntem Text, PDF-Rohbinaerdaten ausserhalb der Python-Quellzeilen).
  Gefundene Beispiele sind repraesentativ, nicht garantiert vollstaendig.
- Die Dark-Pattern-Pruefung ist eine Stichprobe entlang der im Auftrag
  genannten vier Muster (Button-Asymmetrie, vorangekreuzte Boxen, Forced
  Continuity, Loeschpfad-Tiefe) anhand von Code-/CSS-Lektuere, nicht ein
  vollstaendiger manueller Klickdurchlauf jeder Maske in einer laufenden
  Instanz.
- „Keine Treffer gefunden“ bei `COMMERCIAL-001`/`COMMERCIAL-002` bedeutet
  Abwesenheit im durchsuchten Quellcode zu diesem Commit, nicht eine
  rechtliche Freigabe, zukuenftige Funktionen zu unterlassen.
- Dieses Dokument faellt bewusst **keine** rechtliche Bewertung, ob eine der
  zitierten Formulierungen gegen ein konkretes Gesetz oder eine FINMA-Norm
  verstoesst, ob sie „false advertising“ darstellt, oder ob der
  Dokumentationsdrift in `finma-outsourcing-anzeige.md` eine Melde- oder
  Korrekturpflicht auslöst. Diese Einordnung bleibt Eigentuemer/Rechts-
  /Compliance-Team vorbehalten.
- Ergebnis: Die Claim-/Dark-Pattern-/Commercial-Surface-Runde aus der
  verbindlichen Audit-Reihenfolge des Coverage-Audits ist mit diesem
  Dokument durchgefuehrt; das zugrunde liegende Claim-Register, die
  Korrektur von `finma-outsourcing-anzeige.md` und ein UI-Pfad fuer
  Kundenloeschung bleiben offene Umsetzungsarbeit, nicht Teil dieses
  read-only Audits.
