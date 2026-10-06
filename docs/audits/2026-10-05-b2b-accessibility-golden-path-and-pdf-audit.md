---
handoff_schema: "ares.optimizer-handoff/v1"
document_role: "b2b-accessibility-golden-path-and-pdf-audit"
status_as_of: "2026-10-05"
language: "de"
repository: "asset-allocation-stochastic-core"
branch: "codex/b2b-accessibility-golden-path-audit"
audited_repository_head: "8dfd6cc13a7869e1996331e5d226551fc441a6ee"
prior_coverage_audit_path: "docs/audits/2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md"
prior_coverage_finding_closed: "B2B-COVERAGE-004"
audit_mode: "read_only_static_code_and_existing_test_review"
audit_mutated_product_code: false
scope: "accessibility of the login -> client/mandate -> risk profile -> goals -> asset allocation -> review -> PDF golden path in the Classic monolith (5eyes_v2.html) and the React reporting app, plus PDF/UA tagging posture of ReportLab-based PDF generation"
release_decision: "not_a_release_gate_this_round_evidence_and_fix_backlog_only"
---

# Accessibility-Golden-Path- und PDF-Audit

**Kontrollrunde: B2B-Trust-Track Runde 3 (Accessibility Golden Path/PDF) ·
Stand 05.10.2026 · Status: Evidenz- und Fixbacklog, kein Release-Gate**

## Kurzfazit

Dieser Audit schliesst `B2B-COVERAGE-004` aus dem
[B2B-Trust-/Compliance-Pre-Implementation-Coverage-Audit](2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md):
Accessibility war bisher nur punktuell durch React-A11y-Tests und einen
statischen Chart-Contract-Test belegt, nicht als vollstaendiger Golden Path.

Die vorhandene Abdeckung ist echt und nicht trivial: fünf React-A11y-Testdateien
(Skip-Link, Live-Regions, verbalisierte Ampel-Stati, Sidebar-Landmarken,
beschriftete Formulare, Dialog-Fokus) und ein 130-Zeilen-Contract-Test fuer
sechs Chart.js-Canvases im Monolith sind vorhanden und wurden in dieser Runde
gelesen bzw. (beim Backend-Test) erneut ausgefuehrt. Sie werden hier **nicht**
erneut auditiert, sondern als Bestand uebernommen.

Zusaetzlich zu dieser bestehenden Abdeckung bestaetigt dieser Audit acht neue,
konkrete technische Befunde entlang des Golden Path
`Login -> Kunde/Mandat -> Risikoprofil -> Ziele -> Asset Allocation -> Review -> PDF`:

1. Die komplette Schritt-Navigation des Golden Path (`div.tstep`, 7 Schritte)
   sowie 61 weitere klickbare `<div onclick>`-Elemente im Monolith (u.a.
   `div.qopt`, `div.qcb`, `div.kpi`, `div.rtab`, `div.client`) besitzen **kein**
   `role`, **kein** `tabindex` und **keinen** Keydown-Handler — 0 von 61 Treffern
   in beiden Attributen.
2. Der FINMA-Eignungspruefungs-Fragebogen (Risikoprofil-Schritt, Zeilen
   3082-3200) ist vollstaendig aus diesen nicht-semantischen `div.qopt`/`div.qcb`
   gebaut — keine `<input type=radio/checkbox>`, kein `<label>`, kein
   `role="radiogroup"`, kein `<fieldset>`/`<legend>`.
3. Systemweit existieren 391 `<label>`-Tags, aber nur 10 mit `for=`; nur 1
   `required`-Attribut auf einem `<input>`; 0 `aria-required`, 0
   `aria-invalid`, 0 `aria-describedby` im gesamten Monolith.
4. Die E-Signatur (Review-&-Abschluss-Schritt) erzwingt eine mit Maus/Touch
   gezeichnete Unterschrift ohne jedes Tastatur-Äquivalent; die Fehlermeldung
   ist kein Live-Bereich.
5. Zwei React-SVG-Chart-Komponenten (`MonteCarloPathsChart`,
   `BarChartIstSoll`) sind inhaltlich gut gebaut (role="img", `<title>`/`<desc>`,
   textuelle statt rein farbliche Kodierung), liegen aber ausserhalb des
   bestehenden Backend-Contract-Tests und sind nicht regressionsgesichert.
6. Die PDF-Erzeugung nutzt ReportLab ohne jede Spur von PDF/UA-, Tagging-,
   `StructTreeRoot`- oder Alt-Text-Konzepten; ein vorhandenes `locale`-Feld
   wird nicht als PDF-Sprachmetadatum gesetzt.
7. Das Monolith-CSS hat einen Viewport-Meta-Tag und 14 Media Queries, basiert
   aber fast vollstaendig auf Pixel-Einheiten (5999 `px`-Treffer gegen 0 `rem`).
8. Es wurde kein Accessibility Statement im Repository gefunden.

Dieser Audit stellt **keine** WCAG-2.2-Konformitaetsaussage, keine
Rechtsfreigabe und keinen durchgefuehrten Screenreader-Test dar. Alle Befunde
sind statische Code- und Testbefunde mit Datei:Zeile-Beleg; wo ein manueller
Nachweis (Screenreader, echte Tastaturbedienung im laufenden Programm) fehlt,
ist das explizit vermerkt.

## Auditbasis und Scope

Auditiert wurde Commit `8dfd6cc13a7869e1996331e5d226551fc441a6ee` auf Branch
`codex/b2b-accessibility-golden-path-audit` (= `origin/develop`-HEAD).

Gelesen/durchsucht wurden:

- `5eyes-electron/frontend/5eyes_v2.html` (28'228 Zeilen, Classic-Monolith);
- `5eyes-electron/frontend/reporting/src/**` (React-Reporting-App);
- `5eyes-backend/tests/test_frontend_chart_accessibility.py` (vollstaendig);
- `5eyes-electron/frontend/reporting/src/App.a11y.test.tsx`,
  `components/AmpelPill.a11y.test.tsx`, `components/Sidebar.a11y.test.tsx`,
  `sections/goals/GoalsEditor.a11y.test.tsx`,
  `sections/profiling/profiling.a11y.test.tsx` (vollstaendig);
- `5eyes-backend/services/pdf/**` (Renderer-Protocol, Komponenten,
  Bibliotheksnutzung);
- `5eyes-backend/requirements*.txt` (PDF-Engine-Abhaengigkeit).

Produktcode, Tests und Konfiguration wurden **nicht** veraendert. Der
Backend-Chart-Test wurde read-only erneut ausgefuehrt (siehe
„Verifikation dieser Runde"); die React-A11y-Tests wurden vollstaendig
gelesen, aber in diesem Worktree nicht ausgefuehrt, weil `node_modules` nicht
installiert ist und eine Installation ausserhalb des read-only-Scopes dieser
Runde liegt (siehe „Selbst-Audit und Nachweisgrenzen").

Kein manueller Screenreader-Test (NVDA/JAWS/VoiceOver) wurde durchgefuehrt.
Alle Aussagen zu Screenreader-Verhalten sind aus Markup/Code abgeleitete
Erwartungen, keine beobachteten Ergebnisse.

## Was bereits belegt ist und hier nicht neu auditiert wird

| Bereich | Beleg | Bewertung |
|---|---|---|
| Chart.js-Canvases im Monolith (6 Daten-Charts + 1 dekorativ) | `test_frontend_chart_accessibility.py`, in dieser Runde erneut ausgefuehrt: 7/7 grün | `role="img"`, `aria-label`, sr-only-Tabellenfallback fuer die 3 wichtigsten Charts, dekorativer Canvas korrekt `aria-hidden` |
| React-App-Shell | `App.a11y.test.tsx` | Skip-Link, `tabIndex={-1}`-Sprungziel, `aria-busy`/`aria-live="polite"` beim Laden, `role="alert"`/`aria-live="assertive"` bei Fehlern |
| Ampel-Status-Komponente (React) | `AmpelPill.a11y.test.tsx` | `role="status"`, 4 unterschiedlich verbalisierte `aria-label` statt reiner Farbe |
| Reporting-Sidebar-Navigation | `Sidebar.a11y.test.tsx` | `aria-label` auf `aside`/`nav`, `aria-current="page"`, `aria-expanded`/`aria-controls` am Hamburger, `focus-visible`-Ring |
| Ziele-Editor (React) | `GoalsEditor.a11y.test.tsx` | `role="status"`-Live-Region, benannte Tabelle, beschriftete Zeilen-Aktionen, modaler Dialog mit `aria-modal` |
| Risikoprofil-Seite (React-Beta-Editor) | `profiling.a11y.test.tsx` | Alle 8 Fragen ueber `getByLabelText` auffindbar, Live-Region fuer Speicherstatus |

Diese Abdeckung betrifft **nicht** den Classic-Monolith-Risikofragebogen
(siehe `A11Y-FORM-001`) und **nicht** die React-SVG-Charts (siehe
`A11Y-CHART-001`).

## Findings-Register

| ID | Prioritaet | Bereich | Befund |
|---|---:|---|---|
| `A11Y-GP-001` | P1 | Monolith-weit | Golden-Path-Stepper und 61 klickbare `<div onclick>`-Bausteine ohne `role`/`tabindex`/Keydown |
| `A11Y-FORM-001` | P1 | Risikoprofil | FINMA-Eignungspruefungs-Fragebogen vollstaendig ohne native Formularsemantik |
| `A11Y-FORM-002` | P1 | Monolith-weit | Label-`for`-Bindung, Pflichtfeld- und Fehler-Feld-Assoziation fehlen systemweit |
| `A11Y-ESIGN-001` | P1 | Review & Abschluss | E-Signatur nur per Maus/Touch, Fehlermeldung nicht live |
| `A11Y-CHART-001` | P2 | React-Reporting | Zwei gute SVG-Chart-Komponenten ohne Regressionstest-Analogon zum Backend-Contract-Test |
| `A11Y-PDF-001` | P1 | PDF-Erzeugung | Kein PDF/UA-/Tagging-/Alt-Text-Konzept; `locale` nicht als PDF-Sprachmetadatum gesetzt |
| `A11Y-REFLOW-001` | P2 | Monolith-CSS | Fast ausschliesslich Pixel-Einheiten trotz Viewport-Meta und Media Queries |
| `A11Y-STATEMENT-001` | P2 | Repository-weit | Kein Accessibility Statement gefunden |

Keine bestehende Finding-ID (aus anderen Audits) wird hier geschlossen oder
umbenannt; dieser Audit schliesst ausschliesslich `B2B-COVERAGE-004` aus dem
Coverage-Audit vom 05.10.2026 im Sinne von „bearbeitet", nicht „technisch
behoben".

---

## `A11Y-GP-001` — Golden-Path-Stepper und Interaktionsbausteine ohne native Tastatursemantik

### Repository-Beleg

- Die Schritt-Navigation des gesamten Golden Path ist sieben `<div
  class="tstep">` mit `onclick="go(...)"`, ohne `role`, `tabindex` oder
  Keydown-Handler (`5eyes-electron/frontend/5eyes_v2.html:2091-2103`):

  ```html
  <div class="tstep active" data-page="sd" onclick="go('sd',this)"><div class="sn">1</div>Stammdaten</div>
  <div class="tstep" data-page="vg" onclick="go('vg',this)"><div class="sn">2</div>Vermögen</div>
  <div class="tstep" data-page="cf" onclick="go('cf',this)"><div class="sn">3</div>Cashflows &amp; Ziele</div>
  <div class="tstep" data-page="rp" onclick="go('rp',this)"><div class="sn">4</div>Risikoprofil</div>
  <div class="tstep" data-page="al" onclick="go('al',this)"><div class="sn">5</div>Asset Allokation</div>
  <div class="tstep" data-page="po" onclick="go('po',this)"><div class="sn">6</div>Portfolio</div>
  <div class="tstep" data-page="rv" onclick="go('rv',this)"><div class="sn">7</div>Review &amp; Abschluss</div>
  ```

  Diese sieben Elemente sind exakt die sieben Stationen des in diesem Audit
  untersuchten Golden Path.
- Eine repo-weite Suche ueber alle `<div ...onclick="...">`-Treffer ergibt 61
  Elemente; 0 davon tragen `role=`, 0 davon tragen `tabindex=` (statische
  Regex-Zaehlung ueber die gesamte Datei, nicht nur den Stepper).
- Betroffene Interaktionsklassen neben `div.tstep` (mit Zeilenbeleg):
  - `div.qopt` (38×, Zeilen 3082-3200) — Einzelauswahl-„Radiobuttons" im
    Risikoprofil-Fragebogen, siehe `A11Y-FORM-001`;
  - `div.qcb` (5×, Zeilen 3099-3103) — Mehrfachauswahl-„Checkboxen"
    (Einkommensquellen) im selben Fragebogen;
  - `div.kpi` (3×, Zeilen 3239-3241) — anklickbare Dashboard-Kacheln, die zu
    `go('vg')`/`go('cf')` navigieren (z.B. Zeile 3239:
    `<div class="kpi" onclick="go('vg')" ... style="cursor:pointer">`);
  - `div.rtab` (2×, Zeilen 2997-2999) — Unter-Tabs innerhalb des
    Risikoprofil-Schritts (`Kenntnisse & Erfahrungen` /
    `Risikofähigkeit` / `Risikobereitschaft`);
  - `div.client` (3×, Zeilen 2858-2868) — Mandanten-/Kunden-Switcher in der
    Seitenleiste (`onclick="selC(this);loadPersona('HH-001')"`);
  - `div.prow-main` (Zeile 20865) — anklickbare Portfolio-Positionszeile
    (`onclick="togglePortfolioPositionDetail(...)"`).
- Gegenbeispiel, das zeigt, dass das Pattern im selben File bekannt ist: die
  dynamisch erzeugte Allocation-Bar bei Zeile 22793 besitzt `tabindex="0"` und
  `aria-label` (`<div class="'+barClass+'" ... aria-label="'+hoverLabel+'"
  tabindex="0" ...>`). Diese Bar hat kein `onclick` (nur Hover-Tooltip) und
  zaehlt daher nicht zu den 61 Treffern oben, beweist aber, dass dieselbe
  Codebasis an anderer Stelle bereits fokussierbare, beschriftete
  Custom-Controls kennt — das Pattern wurde beim Stepper/den Fragebogen-Optionen
  nur nicht angewendet.

### Wirkung

- Ein Tastatur-only-Nutzer kann die sieben Golden-Path-Schritte nicht per
  `Tab`/`Enter`/`Space` erreichen, da `div.tstep` nicht im Tab-Index-Fluss
  liegt (kein natives interaktives Element, kein `tabindex`).
- Dasselbe gilt fuer den Mandanten-Switcher (`div.client`), die
  Risikoprofil-Unter-Tabs (`div.rtab`) und die Dashboard-KPI-Kacheln
  (`div.kpi`), die ebenfalls Navigationsziele sind.
- Relevantes Kriterium zur Einordnung (keine Konformitätsaussage): WCAG 2.2
  SC 2.1.1 „Keyboard" und SC 4.1.2 „Name, Role, Value" beschreiben exakt diese
  Eigenschaftsklasse (operabel per Tastatur, programmatisch bestimmbare
  Rolle).

### Erforderliche Loesung

1. Jedes klickbare, nicht-native `<div onclick>`-Element im Golden Path durch
   ein natives `<button>` ersetzen **oder** mit `role="button"` (bzw.
   `role="tab"`/`role="radio"`/`role="checkbox"` je nach Semantik),
   `tabindex="0"` und einem Keydown-Handler fuer `Enter`/`Space` ausstatten.
2. Fuer den Stepper (`div.tstep`) `role="tablist"`/`role="tab"` mit
   `aria-selected` und Pfeiltasten-Navigation oder eine native
   `<nav><ol><li><button>`-Struktur verwenden.
3. Fuer `div.client` (Mandanten-Switcher) und `div.kpi`
   (Dashboard-Navigationskacheln) native `<button>`- oder `<a>`-Elemente
   verwenden, da sie reine Navigationsaktionen ohne visuelles
   Formular-Element sind.
4. Automatisierten Regressionstest analog zu
   `test_frontend_chart_accessibility.py` anlegen, der fuer jede definierte
   Interaktionsklasse (`tstep`, `kpi`, `rtab`, `client`, `prow-main`)
   `role`/`tabindex` oder nativen Tag-Namen verlangt.

---

## `A11Y-FORM-001` — FINMA-Eignungspruefungs-Fragebogen ohne native Formularsemantik

### Repository-Beleg

- Der komplette Risikoprofil-Fragebogen (`id="r-rf"` ff., Golden-Path-Schritt
  „Risikoprofil") ist ausschliesslich aus `div.qopt`/`div.qcb` gebaut, z.B.
  Frage 3 „Regelmässiges Einkommen" (`5eyes_v2.html:3081-3087`):

  ```html
  <div class="qopts">
    <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">Bis CHF 6'000</span></div>
    <div class="qopt" onclick="sq(this,'rf-income')"><div class="qrad"></div><span class="qtxt">CHF 6'000 bis 9'000</span></div>
    ...
  </div>
  ```

  und Frage 4 „Herkunft des Einkommens" (Mehrfachauswahl,
  `5eyes_v2.html:3098-3104`):

  ```html
  <div class="qcbs">
    <div class="qcb" onclick="this.classList.toggle('sel');riskAssessmentUiDirty=true;"><div class="qbox"></div>Berufliche Tätigkeit (selbstständig oder unselbstständig)</div>
    ...
  </div>
  ```

- Es existiert kein `<input type="radio">`/`<input type="checkbox">`, kein
  `<label>`, kein `role="radiogroup"`/`role="radio"`/`role="checkbox"`, kein
  `<fieldset>`/`<legend>` fuer diese 38 (`qopt`) + 5 (`qcb`) Options-Elemente
  (Zeilen 3082-3200, siehe `A11Y-GP-001` fuer die Zaehlmethode).
- Die visuelle „Radiobutton"/„Checkbox"-Optik entsteht ausschliesslich aus
  `div.qrad`/`div.qbox` plus CSS-Klassen (`.sel`), nicht aus semantischem
  Markup.
- Die Fragetexte selbst (z.B. Zeile 3079: „Regelmässiges Einkommen – Wie hoch
  ist Ihr regelmässiges Bruttoeinkommen...") stehen in `<span>` innerhalb
  `div.ql`, nicht in einem programmatisch mit der Optionsgruppe verknuepften
  `<legend>` oder `aria-labelledby`.
- Kontrast zum React-Beta-Editor derselben Fachlogik: die React-Variante
  (`profiling.a11y.test.tsx`, s.o.) nutzt echte beschriftete Formularelemente
  (`getByLabelText('Einkommenssituation')` etc.) — das belegt, dass eine
  zugaengliche Umsetzung dieser Fachlogik im Code bereits existiert, aber nur
  im React-Beta-Pfad, nicht im Classic-Monolith, der laut Produkthistorie der
  produktiv genutzte Pfad ist.

### Wirkung

- Keine der 43 Fragebogen-Optionen ist per Tastatur erreichbar (siehe
  `A11Y-GP-001`: 0/61 onclick-Divs mit `tabindex`).
- Ein Screenreader kann die Optionsgruppen nicht als Radiogruppe/Checkboxgruppe
  ankuendigen und den Auswahlstatus nicht ueber `aria-checked`/`:checked`
  verbalisieren, da kein entsprechendes Attribut gesetzt wird; der visuelle
  Auswahlstatus existiert nur als CSS-Klasse `.sel`.
- Relevantes Kriterium zur Einordnung: WCAG 2.2 SC 1.3.1 „Info and
  Relationships", SC 2.1.1 „Keyboard", SC 4.1.2 „Name, Role, Value".

### Erforderliche Loesung

1. Jede Frage als `<fieldset>` mit `<legend>` = Fragetext umsetzen.
2. Jede Einzelauswahl-Frage als Gruppe nativer `<input type="radio"
   name="...">` mit `<label>` je Option (oder `role="radiogroup"` +
   `role="radio"` + `aria-checked`, falls das visuelle Design beibehalten
   werden soll) umsetzen; analog Checkboxen fuer Mehrfachauswahl.
3. Tastaturbedienung (Pfeiltasten fuer Radiogruppen, Space fuer Checkboxen)
   sicherstellen, bevor das bestehende `sq(this,...)`-Click-Handling
   wiederverwendet wird.
4. Den React-Beta-Editor-Ansatz (`profiling.a11y.test.tsx`) als Referenz fuer
   die Zielsemantik nutzen, nicht neu erfinden.
5. Regressionstest analog `test_frontend_chart_accessibility.py` fuer den
   Monolith-Fragebogen: jede `qopts`/`qcbs`-Gruppe muss native Inputs oder
   vollstaendige ARIA-Rollen + Tastaturpfad besitzen.

---

## `A11Y-FORM-002` — Label-Bindung, Pflichtfeld- und Fehler-Feld-Assoziation fehlen systemweit

### Repository-Beleg

- Repo-weite Zaehlung im Monolith: 391 `<label`-Tags gesamt, davon nur 10 mit
  `for=`-Attribut; 225 Treffer fuer `class="fl"` (das generische
  Feld-Label-Pattern der Modals).
- Beispiel „Ziel erfassen"-Modal (`id="m-nz"`, Golden-Path-Schritt „Ziele"),
  Pflichtfeld „Bezeichnung *" (`5eyes_v2.html:4758-4761`):

  ```html
  <div class="fg m-acf-field" id="nz-label-field" data-goal-field="label">
    <label class="fl">Bezeichnung *</label>
    <input class="fi" id="nz-label" type="text" autocomplete="off" spellcheck="true" placeholder="Finanzielle Unabhängigkeit">
  </div>
  ```

  `<label>` und `<input>` sind Geschwister-Elemente ohne `for`/`id`-Bindung
  und ohne Verschachtelung — es besteht **keine** programmatische Assoziation.
  Das Pflichtfeld-Sternchen `*` ist reiner Text im Label, kein
  `required`/`aria-required` auf dem `<input>`.
- Gegenbeispiel im selben Modal, Zeile 4765-4766 (`nz-notes`): dort **ist**
  `for="nz-notes"` gesetzt — das Pattern ist also bekannt, wird aber
  inkonsistent angewendet (10 von 391 Labels).
- Repo-weit: 1 `<input ... required>`-Treffer, 0 `aria-required`, 0
  `aria-invalid`, 0 `aria-describedby` im gesamten Monolith.
- Fehleranzeige-Mechanismus: ein globaler Toast-Bereich existiert
  (`5eyes_v2.html:1989`):

  ```html
  <div id="app-notice-stack" class="app-notice-stack" role="region" aria-live="polite" aria-label="Hinweise"></div>
  ```

  Das ist ein echter, korrekt deklarierter `aria-live`-Bereich fuer globale
  Hinweise — aber er bindet Fehlermeldungen nicht an das konkrete Feld
  (kein `aria-describedby` vom Input zur Fehlermeldung, keine
  feldbezogene `aria-invalid`-Markierung).

### Wirkung

- Screenreader-Nutzer, die ein Eingabefeld fokussieren, hoeren den
  zugehoerigen Labeltext in den allermeisten Faellen nicht automatisch
  vorgelesen, weil die programmatische Zuordnung fehlt (Ausnahme: visuell
  erkennbare, aber fuer Screenreader nicht nutzbare Naehe im DOM).
- Pflichtfelder sind nur visuell (Sternchen) markiert, nicht programmatisch
  (`required`/`aria-required`) — assistive Technologie kann das nicht
  ankuendigen.
- Validierungsfehler werden, soweit ueber `app-notice-stack` angezeigt,
  global angesagt, aber nicht mit dem fehlerhaften Feld verknuepft.
- Relevantes Kriterium zur Einordnung: WCAG 2.2 SC 1.3.1, SC 3.3.1 „Error
  Identification", SC 3.3.2 „Labels or Instructions", SC 4.1.2.

### Erforderliche Loesung

1. Jedes `<label class="fl">` mit `for="<input-id>"` versehen oder das
   `<input>`/`<select>`/`<textarea>` in das `<label>` verschachteln; Lint-Regel
   oder Contract-Test, der `class="fl"`-Labels ohne Bindung blockiert.
2. Pflichtfelder zusaetzlich zum visuellen Sternchen mit `required` bzw.
   `aria-required="true"` markieren.
3. Bei Validierungsfehlern das betroffene Feld mit `aria-invalid="true"` und
   `aria-describedby` auf eine feldnahe Fehlermeldung versehen, zusaetzlich
   zum bestehenden globalen `app-notice-stack`-Hinweis (nicht als Ersatz).
4. Regressionstest, der fuer eine definierte Stichprobe von Kernformularen
   (Ziel erfassen, Cashflow erfassen, Risikoprofil, Stammdaten) vollstaendige
   Label-Bindung und Pflichtfeld-Markierung verlangt.

---

## `A11Y-ESIGN-001` — E-Signatur nur per Maus/Touch, Fehlermeldung nicht live

### Repository-Beleg

- Das Signatur-Modal (`id="m-esign"`, Golden-Path-Schritt „Review &
  Abschluss") verlangt eine mit Maus oder Finger gezeichnete Unterschrift auf
  einem `<canvas>` (`5eyes_v2.html:5113`, Ausschnitt):

  ```html
  <label class="fl">Unterschrift (mit Maus oder Finger zeichnen)</label>
  <canvas id="esign-canvas" width="480" height="160" style="...;cursor:crosshair;touch-action:none"></canvas>
  ...
  <div id="esign-error" style="display:none;color:var(--neg);font-size:10px;margin-top:6px"></div>
  ```

- Die Event-Bindung auf den Canvas registriert ausschliesslich Maus- und
  Touch-Events, keine Tastatur-Events (`5eyes_v2.html:25486-25491`):

  ```js
  canvas.addEventListener('mousedown',start);
  canvas.addEventListener('mousemove',move);
  canvas.addEventListener('touchstart',start,{passive:false});
  canvas.addEventListener('touchmove',move,{passive:false});
  canvas.addEventListener('touchend',end,{passive:false});
  ```

  Der Canvas hat kein `tabindex` und kein `role`.
- Die Absendefunktion blockiert ohne gezeichnete Signatur hart
  (`5eyes_v2.html:25515-25525`):

  ```js
  async function submitEsignSignature(){
    ...
    if(!name){showErr('Bitte den Namen des Unterzeichners eingeben.');return;}
    if(!esignState.hasDrawn){showErr('Bitte zuerst unterschreiben.');return;}
    ...
  }
  ```

  `esignState.hasDrawn` wird ausschliesslich durch die oben genannten
  Maus-/Touch-Handler gesetzt — es gibt im gelesenen Code keinen alternativen
  Pfad, der ohne Zeichnen auf dem Canvas zu `hasDrawn=true` fuehrt.
- `#esign-error` hat kein `role="alert"` und kein `aria-live` — die
  Fehlermeldung „Bitte zuerst unterschreiben." wird nur durch
  `showErr()`/`textContent` sichtbar gesetzt, nicht als Live-Region
  angesagt.

### Wirkung

- Ein Nutzer, der ausschliesslich Tastatur oder ein Eingabegeraet ohne
  Zeige-/Zeichenfunktion verwenden kann, kann den Abschluss-Schritt des
  Golden Path an dieser Stelle nicht abschliessen (kein Alternativpfad
  gefunden).
- Ein Screenreader-Nutzer erhaelt beim fehlgeschlagenen Submit keine
  automatische Sprachausgabe der Fehlermeldung.
- Relevantes Kriterium zur Einordnung: WCAG 2.2 SC 2.1.1 „Keyboard"
  (kein Tastaturpfad fuer eine erforderliche Aktion), SC 3.3.1
  „Error Identification".

### Erforderliche Loesung

1. Einen expliziten Tastatur-/Alternativpfad fuer die Signaturbestaetigung
   definieren (z.B. getippter Name plus explizite Checkbox „Ich bestaetige,
   dass dies meine rechtsguetige elektronische Unterschrift ist" als
   gleichwertige, protokollierte Willensbekundung) — fachlich/rechtlich mit
   Compliance abzustimmen, da dies die E-Signatur-Semantik beruehrt.
2. `#esign-error` mit `role="alert"` oder `aria-live="assertive"` versehen.
3. Canvas-Status (gezeichnet/nicht gezeichnet) zusaetzlich textuell/als
   `aria-live`-Status spiegeln, nicht nur visuell.

---

## `A11Y-CHART-001` — React-SVG-Charts ausserhalb des bestehenden Chart-Contract-Tests

### Repository-Beleg

- Der bestehende Backend-Contract-Test
  (`5eyes-backend/tests/test_frontend_chart_accessibility.py`) prueft
  ausschliesslich Chart.js-`<canvas>`-Elemente im Monolith
  (`5eyes_v2.html`); er kennt die React-Reporting-App nicht.
- Eine Suche nach Canvas-/SVG-Visualisierungen in
  `5eyes-electron/frontend/reporting/src` findet zwei eigene
  SVG-Chart-Komponenten ausserhalb von Chart.js:
  - `components/MonteCarloPathsChart.tsx` — SVG-Wealth-Trajectory mit
    p5/p50/p75-Band und Goal-Markern (Golden-Path-Schritt „Ziele"/"Asset
    Allocation"-Reporting);
  - `components/BarChartIstSoll.tsx` — IST/SOLL-Balken fuer Asset Allocation,
    Risikowaehrungen und Branchen (`pages/AssetAllocation.tsx`,
    `pages/Risikowaehrungen.tsx`).
- Beide sind inhaltlich bereits gut gebaut, nicht nur „fehlend getestet":
  - `MonteCarloPathsChart.tsx:118-137` nutzt `<figure aria-label="...">`,
    `<svg role="img">`, `<title>` und `<desc>` mit konkreten Werten
    (Horizont, Pfadanzahl), und eine textuelle `<figcaption>`-Legende statt
    reiner Farbcodierung.
  - `BarChartIstSoll.tsx` zeigt IST-/SOLL-/Drift-Werte als Text neben jedem
    Balken (`formatBpsAsPct`/`formatBpsSignedPct`); die Drift-Farbe
    (`text-status-rot` etc.) begleitet, ersetzt aber nicht den Zahlenwert.
  - Dekorative Legenden-Swatches sind korrekt `aria-hidden="true"`.
- Es existiert jedoch **kein** Analogon zum Backend-Contract-Test, das diese
  Eigenschaften (role="img", `<title>`/`<desc>`, Text-statt-Farbe-Kodierung)
  gegen Regression schuetzt.

### Wirkung

- Aktuell kein akuter Nutzerschaden belegt (die Implementierung ist
  inhaltlich a11y-bewusst) — das Risiko ist Regression ohne Warnung, falls
  diese Komponenten spaeter geaendert werden, ohne dass ein Test das
  `role="img"`/`<title>`/`<desc>`-Kontrakt durchsetzt.

### Erforderliche Loesung

1. Vitest-Contract-Test fuer `MonteCarloPathsChart` und `BarChartIstSoll`
   anlegen, analog zum Backend-Test: `role="img"` + nicht-leeres `<title>`
   fuer `MonteCarloPathsChart`; textuelle Werte (nicht nur Farbklasse) fuer
   jede Bar in `BarChartIstSoll`.
2. Pruefen, ob weitere, spaeter hinzukommende React-Visualisierungen
   (`pages/Goals.tsx` u.ae.) denselben Kontrakt erfuellen muessen, und das im
   Test explizit als Liste (analog `DATA_CHART_IDS`) fuehren statt implizit.

---

## `A11Y-PDF-001` — Keine PDF/UA-, Tagging- oder Alt-Text-Konzepte in der PDF-Erzeugung

### Repository-Beleg

- Die PDF-Engine ist ReportLab, nicht WeasyPrint:
  `5eyes-backend/requirements*.txt:42`: `reportlab>=4.0,<5`.
  `services/pdf/base.py:1-5` dokumentiert explizit ein
  Renderer-Protocol, das einen spaeteren Wechsel auf WeasyPrint vorbereiten
  soll, aber aktuell ist ReportLab die einzige implementierte Engine
  (`services/pdf/components/*.py` importieren durchgehend aus `reportlab.*`).
- Eine repo-weite Suche nach `PDF/UA`, `tagged`, `/MarkInfo`,
  `StructTreeRoot` in `5eyes-backend` und `5eyes-electron` ergibt **0**
  Treffer. Es gibt keinen Code-Pfad, der eine Tagged-PDF-Struktur erzeugt.
- `services/pdf/base.py:14-23` definiert `PDFContext` mit einem
  `locale: str = "de-CH"`-Feld, aber eine Suche nach `setTitle`, `setAuthor`,
  `setLang`/`set_lang`, `.lang` oder `/Lang` im `services/pdf`-Baum ergibt
  **0** Treffer — das `locale`-Feld wird (soweit in diesem Audit geprueft)
  nicht als PDF-Dokumentsprache (`/Lang`-Katalogeintrag) gesetzt.
- Diagramme in PDFs werden als reine Vektor-Shapes gezeichnet
  (`services/pdf/components/advisory_bar_chart.py` nutzt
  `reportlab.graphics.shapes.Drawing/Rect`); eine Suche nach
  `alt_text`/`alttext`/„image description" in `services/pdf` ergibt **0**
  Treffer — es gibt keinen textuellen Alternativ-Inhalt fuer diese Grafiken,
  der ueber die sichtbaren Zahlen/Labels im selben Layout hinausgeht.
- Fachlich-methodischer Kontext: ReportLab (`platypus`/`canvas`-API in der
  hier verwendeten Version) erzeugt standardmaessig keinen
  `StructTreeRoot`/Tag-Baum; ein PDF/UA-konformes Dokument erfordert eine
  explizite Tagging-Schicht, die in diesem Code nicht vorhanden ist.

### Wirkung

- Kundenreports (Risikoprofil-PDF, Asset-Allocation-PDF, Portfolio-PDF,
  Kostenausweis, Anlagestrategie) sind dauerhafte, teils regulatorisch
  relevante Dokumente (vgl. `A11Y-07` im Readiness-Plan), aber visuell
  korrekt heisst hier nicht automatisch zugaenglich: ohne Tag-Baum kann ein
  Screenreader Leseordnung, Ueberschriften, Tabellenkoepfe und
  Bildbeschreibungen nicht zuverlaessig rekonstruieren.
- Ohne gesetztes `/Lang`-Attribut kann assistive Technologie die
  Dokumentsprache nicht zuverlaessig erkennen, obwohl die fachliche
  Locale (`de-CH` oder andere) im Code bereits bekannt ist.

### Erforderliche Loesung

1. Zielniveau fuer PDF-Barrierefreiheit (z.B. PDF/UA-1) explizit und bewusst
   festlegen — das ist eine Produktentscheidung, keine impliziert aus dem
   Code ableitbare Tatsache.
2. Pruefen, ob die genutzte ReportLab-Version/-Konfiguration
   Tagging unterstuetzt (ggf. ueber zusaetzliche Nachbearbeitung oder einen
   Wechsel der Engine, wie im `PDFRenderer`-Protocol bereits als Option
   vorgesehen) und das Ergebnis dokumentieren, bevor eine Umsetzung
   beauftragt wird.
3. `locale`/Sprachinformation tatsaechlich in die PDF-Katalog-Metadaten
   (`/Lang`) schreiben.
4. Fuer jede im PDF gezeichnete Grafik eine textuelle Alternative/Daten-Tabelle
   im selben Dokument vorsehen, analog zum sr-only-Tabellenfallback-Muster
   aus `test_frontend_chart_accessibility.py` fuer die Web-UI.
5. Manuellen Screenreader-Test eines exportierten PDFs einplanen — in
   diesem Audit nicht durchgefuehrt.

---

## `A11Y-REFLOW-001` — Monolith-CSS fast ausschliesslich in Pixel-Einheiten

### Repository-Beleg

- Viewport-Meta-Tag ist vorhanden: `5eyes_v2.html:5`
  `<meta name="viewport" content="width=device-width, initial-scale=1.0">`.
- 14 `@media`-Regeln existieren, u.a. `5eyes_v2.html:321,333,510,516,754,
  1017,1021,1025` fuer Breakpoints bis 780px sowie zwei `@media print`-Bloecke
  (Zeilen 991, 1001).
- Repo-weite Zaehlung im selben File: 5999 Treffer fuer ein Pixelmass
  (`\d+px`), 0 Treffer fuer `rem`, 209 Treffer fuer `em`. Schrift-, Abstand-
  und Layoutgroessen sind damit ueberwiegend fest in Pixel kodiert statt
  relativ zu einer Basis-Schriftgroesse.
- Im Vergleich dazu nutzt die React-Reporting-App Tailwind-Responsive-Praefixe
  (`sm:`/`md:`/`lg:`/`xl:`) aktiv in 18 Quelldateien — die React-Seite ist
  damit strukturell auf Reflow vorbereitet, der Monolith nur punktuell
  (14 Breakpoints auf 28'228 Zeilen Markup/CSS).

### Wirkung

- Browser-Zoom (Strg +) skaliert `px`-Werte in modernen Browsern/Electron in
  der Regel mit; diese Prüfmethode (statische Zaehlung) kann das tatsaechliche
  Zoom-/Reflow-Verhalten bei 200% jedoch nicht beweisen oder widerlegen — das
  erfordert einen manuellen Test, der in dieser Runde nicht durchgefuehrt
  wurde.
- Das Fehlen jeder `rem`-Einheit bedeutet, dass eine vom Nutzer im
  Betriebssystem/Browser gesetzte Standard-Schriftgroesse (nicht Zoom) auf
  Text in diesem Monolith keinen Effekt hat, da keine Groesse relativ zur
  Root-Schriftgroesse definiert ist.
- Relevantes Kriterium zur Einordnung: WCAG 2.2 SC 1.4.4 „Resize Text", SC
  1.4.10 „Reflow" — hier nicht als Verstoss behauptet, sondern als
  ungeprueftes Risiko mit konkretem quantitativem Befund markiert.

### Erforderliche Loesung

1. Manuellen 200%-Zoom-/Reflow-Test des Monoliths auf den sieben
   Golden-Path-Schritten durchfuehren und dokumentieren (nicht Teil dieser
   Runde).
2. Schrittweise Migration der Kern-Typografie (Fliesstext, Formularlabels,
   Fehlermeldungen) von `px` auf `rem` pruefen, beginnend bei den in diesem
   Audit identifizierten Formular- und Fragebogen-Bereichen.
3. Die bereits vorhandenen 14 Breakpoints inventarisieren und gegen die
   sieben Golden-Path-Schritte abgleichen, ob jeder Schritt bei schmaler
   Fensterbreite ohne Funktionsverlust nutzbar bleibt.

---

## `A11Y-STATEMENT-001` — Kein Accessibility Statement veroeffentlicht

### Repository-Beleg

- Eine Suche nach `*accessibility-statement*`, `*barrierefreiheit*` sowie
  nach den Texten „accessibility statement" und „Erklärung zur
  Barrierefreiheit"/„Barrierefreiheitserklärung" im gesamten Repository und
  insbesondere unter `docs/` ergibt **0** Treffer.
- Es existiert damit kein Dokument, das Zielniveau, Testdatum, bekannte
  Einschraenkungen oder einen Feedback-/Support-Weg fuer Barrierefreiheit
  benennt.

### Wirkung

- Ohne ein solches Dokument kann 5eyes gegenueber Kunden oder Aufsicht keine
  transparente, versionierte Aussage zum eigenen Barrierefreiheitsstand
  machen; das ist unabhaengig vom tatsaechlichen technischen Reifegrad ein
  Transparenzdefizit.

### Erforderliche Loesung

1. Accessibility Statement erst **nach** Bearbeitung der oben genannten
   technischen Befunde (`A11Y-GP-001`, `A11Y-FORM-001/002`, `A11Y-ESIGN-001`,
   `A11Y-PDF-001`) verfassen, damit es den tatsaechlichen Stand beschreibt
   statt unbelegte Claims zu erzeugen (vgl. `B2B-COVERAGE-005`/`FAIR-07` im
   Readiness-Plan zu Claim-Governance).
2. Scope (Monolith, React-Reporting-App, PDF), Testmethode, Testdatum,
   bekannte Luecken und einen konkreten Feedback-Kanal aufnehmen.

---

## Verifikation dieser Runde

### Durchgefuehrte Pruefungen

- `5eyes-backend/tests/test_frontend_chart_accessibility.py` read-only erneut
  ausgefuehrt: **7 passed** (keine Aenderung am Test oder am Monolith).
- Alle 5 React-A11y-Testdateien vollstaendig gelesen (nicht nur Namen/Pfade),
  Inhalte oben im Abschnitt „Was bereits belegt ist" zusammengefasst.
- Statische Regex-/Grep-Auszaehlungen fuer: `div onclick` mit/ohne
  `role`/`tabindex` (0/61 in beiden Faellen), `aria-*`-Attributverteilung in
  Monolith und React, `<label>`-Gesamtzahl vs. `for=`-Bindung (10/391),
  `required`/`aria-required`/`aria-invalid`/`aria-describedby` (1/0/0/0),
  Canvas-/SVG-Inventar in Monolith und React, PDF/UA-/Tagging-/Alt-Text-Suche
  in `services/pdf`, Viewport-Meta/`@media`/`px`-vs-`rem`-Zaehlung, Suche nach
  einem Accessibility-Statement-Dokument.
- Code-Lesung der E-Signatur-Implementierung (Markup, Event-Bindung,
  Submit-Validierung) zur Bestaetigung des fehlenden Tastaturpfads.
- Code-Lesung von `MonteCarloPathsChart.tsx` und `BarChartIstSoll.tsx`
  vollstaendig zur Bewertung der bestehenden (guten) a11y-Eigenschaften.

### Nicht durchgefuehrte Pruefungen (explizit)

- Kein manueller Screenreader-Test (NVDA/JAWS/VoiceOver) in der laufenden
  Electron-App oder im Browser.
- Keine manuelle Tastatur-Durchquerung der laufenden Anwendung (alle
  Tastatur-Aussagen sind aus Markup/Event-Listener-Code abgeleitet, nicht
  live beobachtet).
- Kein manueller 200%-Zoom-/Reflow-Test.
- Keine automatisierte axe-core-/Lighthouse-Pruefung durchgefuehrt oder
  referenziert — alle Befunde stammen aus gezielter Code-Inspektion, nicht aus
  einem generischen a11y-Scanner.
- Die 5 React-A11y-Testdateien wurden gelesen, aber in diesem Worktree **nicht
  ausgefuehrt** (siehe „Selbst-Audit und Nachweisgrenzen").
- Kein echtes PDF gerendert und in einem PDF-Screenreader/Accessibility-
  Checker (z.B. PAC) geprueft; die PDF-Aussagen beruhen auf Code- und
  Bibliotheksanalyse, nicht auf einem gerenderten Artefakt.

## Selbst-Audit und Nachweisgrenzen

- Produktcode, Tests und Konfiguration veraendert: **nein**.
- Ausgefuehrt wurde ausschliesslich der bereits bestehende, unveraenderte
  Backend-Test `test_frontend_chart_accessibility.py` (7 passed). Die
  React-A11y-Tests wurden nicht ausgefuehrt, weil `node_modules` in
  `5eyes-electron/frontend/reporting` in diesem Worktree nicht installiert
  ist; eine Installation wurde als ausserhalb des read-only-Scopes dieser
  Runde bewusst unterlassen. Ihre Aussagekraft wird ausschliesslich aus dem
  gelesenen Testquellcode abgeleitet, nicht aus einem beobachteten
  Testlauf dieser Runde.
- Keine WCAG-2.2-Konformitaetsaussage, keine Zertifizierungs- oder
  Rechtsaussage wird getroffen. Jede WCAG-Kriteriumsnennung dient nur der
  fachlichen Einordnung eines konkreten, reproduzierbaren Codebefunds.
- Kein Screenreader- oder manueller Zoom-/Reflow-Test wurde durchgefuehrt;
  entsprechende Aussagen sind als Erwartung aus dem Code, nicht als
  beobachtetes Ergebnis, gekennzeichnet.
- Dieser Audit bewertet nicht die fachliche Richtigkeit der
  Risikoprofil-/Ziel-/Allocation-Logik selbst (dazu existieren eigene,
  umfangreiche Integritaetsaudits in diesem Verzeichnis), sondern
  ausschliesslich deren Zugaenglichkeit.
- Ergebnis: `B2B-COVERAGE-004` ist mit diesem Dokument bearbeitet im Sinne
  von „als eigenstaendiger Audit mit WCAG-Matrix, reproduzierten Befunden und
  priorisiertem Fixpaket geliefert" — nicht im Sinne von „technisch
  behoben". Die acht oben genannten Findings sind offen und benoetigen
  Umsetzung, Regressionstests und einen manuellen Screenreader-/Zoom-Nachweis,
  bevor eine Konformitaetsaussage oder ein Accessibility Statement sinnvoll
  waere.
