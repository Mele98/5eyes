# System-Administration-Menue der 5eyes-App — Konsolidierter Audit-Report

**Datum:** 2026-06-10 | **Erstellt von:** Multi-Agent-Audit (5 Auditoren + Synthese) | **Adressat:** Product-Owner
**Audit-Umfang:** 17 Sektionen, 6 Navigations-Gruppen | **Codebasis:** `frontend/5eyes_v2.html` + FastAPI-Router

---

## 1. Executive Summary

Das Admin-Menue ist im Kern **gesund und produktiv**: 16 von 17 Sektionen sind voll funktionsfaehig (WORKS) mit echtem, DB-gestuetztem Backend — keine einzige Sektion ist ein reiner Platzhalter (PLACEHOLDER) oder kaputt (BROKEN). Es gibt **keine** Fake-Buttons oder Stub-Endpoints; jede Aktion ruft einen realen, auditierten Endpoint auf. Die **einzige Einschraenkung** ist die Update-Sektion (PARTIAL): sie funktioniert nur im installierten Electron-Release und enthaelt toten Legacy-Code sowie doppelte Buttons. Der dringendste Handlungsbedarf liegt nicht in der Funktion, sondern in **Konsistenz, Datenintegritaet-Schutz (CMA/Policy-Versionierung) und Benutzerfreundlichkeit** (rohe JSON-Eingaben, fehlende Validierungs-Blocker, ungenutzte bereits gelieferte Backend-Daten).

**Status-Verteilung:** WORKS: 16 | PARTIAL: 1 | PLACEHOLDER: 0 | BROKEN: 0

---

## 2. Status-Tabelle (alle 17 Sektionen, nach Nav-Gruppe)

| Sektion | Verdict | Backend | Kern-Befund |
|---|---|---|---|
| **Status + Audit** | | | |
| Uebersicht (Systemzustand) | WORKS | echt (compliance/backups/paths) | Eager-Load aller Karten beim Oeffnen; Action-Plan hart auf 4 Eintraege gekappt, kein Auto-Refresh-Aging |
| Shadow-Aggregat | WORKS | echt (aggregate_shadow_comparisons) | Korrekt; bei total=0 keine Erklaerung warum leer; mandate_id ohne Deep-Link |
| Protokoll (Audit-Log) | WORKS | echt (AuditLog-Query, Injection-sicher) | Filter ohne Auto-Reload; Summary zaehlt nur sichtbare Seite; zwei konkurrierende Filtermechanismen |
| **Daten** | | | |
| Kurse & Mapping | WORKS | echt (price_updater, OpenFIGI, EODHD) | Doppelter Erfolgs-Toast; 4 Dry-Run/Apply-Buttons ohne Trennung; Checkboxen wirken nur bei EODHD |
| Datenpipeline-Status | WORKS | echt (provider/cache/scheduler) | `recent_validations` vom Backend geliefert, aber **im Frontend nicht gerendert** (verschenkte Daten) |
| Override (Produkt-Lookup) | WORKS | echt (market-override + Audit) | Kein „Override entfernen"-Button trotz expliziter Risk-Note; keine Autocomplete; Volllast bei jedem onblur |
| Jahresrenditen | WORKS | echt (AssetClassAnnualReturn) | Button-Label-Bug; bis zu 100 Einzel-PUTs statt Batch; Backfill ueberschreibt manuelle Werte by default |
| Tageskurse | WORKS | echt (AssetClassPriceHistory) | 120s-Client-Timeout-Risiko bei langem Backfill; kein Datumsbereich-Picker trotz Backend-Support |
| **Annahmen** | | | |
| Annahmen (CMA Set-Verwaltung) | WORKS | echt (versionierte CMA-Zeile) | Button-Label-Bug (Laden/Speichern); Versions-Historie unsichtbar trotz Backend-Versionierung |
| Rendite & Vol. | WORKS | echt (CMA + FX-Rates) | 20 rohe Zahlen-Inputs (9px Labels); FX getrennter Save-Pfad → inkonsistentes Speicher-Modell |
| Inflation & Korr. | WORKS | echt (inflation/correlation JSON) | **Korrelationsmatrix als rohe JSON-Textarea** — sehr fehleranfaellig; keine PSD-/Symmetrie-Validierung |
| Sub-Anlageklassen | WORKS | echt (sub_asset JSON, Engine-konsumiert) | Neue Klassen nur ueber versteckte JSON-Textarea; asset_class nicht im Grid editierbar |
| House-Matrix & Policy | WORKS | echt (5 Endpoints, DB-Lock) | **Aktive Policy editierbar ohne neue Version** (widerspricht UI-Versprechen); Validierung blockiert Speichern nicht; native confirm/prompt/alert |
| **Zugriff** | | | |
| Benutzerliste | WORKS | echt (User-CRUD + Audit) | Kein Soft-Delete im UI trotz Backend-Support; kein Such-/Filterfeld; Passwort-Reset ohne Mindestlaengen-Check |
| Neuer Benutzer | WORKS | echt (POST /users + Audit) | Keine Inline-Validierung; keine Passwort-Staerke/-Sichtbarkeit |
| **Wartung** | | | |
| Backups (DB & Wartung) | WORKS | echt (alle Maintenance-Ops real) | **Kein Restore/Download im UI**; Logs als roher Textblob; Menue-Label ≠ Panel-Titel |
| Update (Software-Update) | **PARTIAL** | Electron-IPC (kein HTTP) | Toter Legacy-Platzhalter; doppelte Buttons; No-Op ausserhalb installierter Releases |

---

## 3. Platzhalter & kaputte Stellen (Prioritaets-Liste)

Es gibt **keine PLACEHOLDER- oder BROKEN-Sektionen**. Folgendes ist konkret zu beheben:

### 3.1 PARTIAL — Update-Sektion (einzige nicht-vollwertige Sektion)
- **Toter Legacy-Anker:** `<div id="update-section" style="display:none">` (`5eyes_v2.html:20425`) — wird von `applyUpdateState()` (`:3592`) referenziert, bleibt aber dauerhaft leer/unsichtbar. Reines Altlast-Element.
- **Doppelte/redundante Buttons fuer dieselbe Funktion:**
  - „Auf Updates pruefen" `btn-check-updates` / `adminCheckUpdates` (`:3619`) **vs.** „Nach Updates suchen" `btn-admin-update-check` / `adminCheckForUpdates` (`:11022`)
  - „Update installieren" `btn-install-update` / `adminInstallUpdate` (`:3634`, startet `display:none` `:20415`) **vs.** „Heruntergeladenes Update installieren" `btn-admin-update-install` / `adminInstallDownloadedUpdate` (`:11039`)
- **No-Op ausserhalb gepackter Releases:** Im Browser/Dev fehlt `window.FiveEyesAPI` → Else-Zweige „Auto-Update ist in diesem Modus nicht verfuegbar." (`:11030`, `:11049`). Das ist **by design** (Electron-updater statt FastAPI), aber die klickbaren No-Op-Buttons sind irrefuehrend. `currentVersion` bleibt „n/a".

### 3.2 Datenintegritaets-Risiken (WORKS, aber gefaehrlich)
- **Aktive Policy ueberschreibbar ohne Versionierung** (`sec-policy`): `adminPolicyOpen` zeigt „Baender speichern" auch fuer die `is_current`-Policy (`:8913`), `PUT .../house-matrix` (`allocation.py:988`) ueberschreibt Rows in-place. **Widerspricht dem UI-Versprechen „Jeder Edit erzeugt eine neue Version"** (`:20335`). Versionierung passiert nur via Klonen.
- **Policy-Validierung blockiert Speichern nicht** (`sec-policy`): `adminPolicyValidateRow` (`:8970`) warnt nur visuell, `adminPolicySaveRows` (`:8976`) sendet auch bei Σtarget ≠ 100% oder min>target → fachlich inkonsistente Baender persistierbar.
- **Backfill ueberschreibt manuelle Werte** (`sec-returns` `system.py:318`, `sec-acprices` `system.py:443`): `overwrite=True` als Default; Backend kann `overwrite=False`, UI bietet aber keinen „nur Luecken fuellen"-Schalter. Keine Quelle-Unterscheidung (admin vs. backfill) im Grid trotz `source`-Feld (`system.py:309`).

### 3.3 Verschenkte / nicht gerenderte echte Daten (WORKS)
- **Datenpipeline:** `recent_validations` wird vom Backend geliefert (`admin.py:162`), aber **gar nicht gerendert** — die letzten 10 Cross-Validierungslogs (Symbol, diff_bps, Alerts) gehen verloren. Auch Provider-Health-Details (`reason`, `unhealthy_until`, `consecutive_errors`, `admin.py:62-66`) werden auf ein OK/Fehler-Pill reduziert.
- **CMA Set-Verwaltung:** Backend versioniert vollstaendig (`version`, `is_current`, `valid_from/until`), aber die Versions-Historie ist im UI unsichtbar.
- **Backups:** `/backups`-Daten liegen in `adminSystemState.backups`, werden aber nur als Zaehler in der Health-Karte (`:7726`) gezeigt — **kein Restore-, kein Download-, kein „Ordner oeffnen"-Button**.

### 3.4 Roh-Eingaben mit hohem Fehlerrisiko (WORKS)
- **Korrelationsmatrix als rohe JSON-Textarea** (`sec-cma-inf` `:20300`): nur 5x5-Formpruefung (`adminCorrelationMatrixPayload :8142`), **keine** Symmetrie-/Wertebereich-[-1,1]-/PSD-Validierung im Frontend → ungueltige Matrix scheitert erst im Cholesky/Monte-Carlo-Schritt.
- **Sub-Anlageklassen** (`sec-cma-sub`): neue Klassen nur ueber versteckte JSON-Textarea (`:20319-20323`), `asset_class` im Grid nicht editierbar (`:8248`).

### 3.5 Kosmetische Bugs (Quick-Fix)
- **Button-Label springt um nach erster Aktion:** HTML „Laden"/„Speichern" → JS setzt im `finally` „Annahmen laden" (`:8558`) / „Annahmen speichern" (`:8712`) (`sec-cma`); analog „Speichern" → „Alle speichern" (`:10660`, `sec-returns`).
- **Doppelter Erfolgs-Toast** in `adminRefreshMarketStatus` (`:8003` und `:8004`) — zwei Meldungen fuer eine Aktion.
- **Menue-Label ≠ Panel-Titel:** Menue „Backups" vs. Panel „Datenbank & Wartung" (`:20391`).

---

## 4. Redesign-Plan („interaktiver, schoener, userfriendlicher")

### Quick-Wins (Stunden, kein Backend noetig)
1. **Button-Label-Bugs fixen** — `finally`-Texte an HTML-Labels angleichen (`sec-cma`, `sec-returns`).
2. **Doppelten Toast entfernen** (`adminRefreshMarketStatus`, eine der Zeilen `:8003/:8004`).
3. **Menue-Label/Panel-Titel angleichen** (Backups → „Datenbank & Wartung").
4. **Toten `#update-section`-Platzhalter entfernen** + doppelte Update-Handler/-Buttons auf je einen konsolidieren (Install-Button nur bei `state.downloaded`, Logik existiert `:3605-3607`).
5. **Empty-States mit Erklaerung** statt stiller Nullen: Shadow-Aggregat bei `total=0` („Noch keine Shadow-Laeufe persistiert — Optimizer im stochastic-Mode ausfuehren").
6. **„Override entfernen"-Button** ergaenzen (`sec-override`) — setzt mode+symbol auf null.
7. **Audit-Filter mit debounced onchange/Enter** auto-reloaden statt separatem Laden-Button; einen der zwei redundanten Filtermechanismen entfernen.

### Mittlere Massnahmen (Frontend-Render, Daten bereits vorhanden)
8. **Datenpipeline-Sektion ausbauen:** `recent_validations` als Tabelle (Symbol, Datum, diff_bps vs. threshold, Alert-Badge) rendern; Provider-Health-Kachel klickbar → Popover mit `reason/consecutive_errors`. (Daten kommen schon vom Backend.)
9. **CMA-Versions-Historie sichtbar machen:** Dropdown/Timeline „Aktive Version vX vom …" mit Diff zur Vorversion.
10. **Backup-Historie als Tabelle** (Datum, Groesse, SHA) mit „Ordner oeffnen" und — falls fachlich erlaubt — „Wiederherstellen"; dedizierter scrollbarer Log-Viewer statt Textblob in der globalen Bar.
11. **Health-Action-Plan:** harten `slice(0,4)` ersetzen durch collapsible Liste mit „+N weitere Befunde"; Auto-Refresh-Toggle (60s) mit relativer Zeit + Ausgrauen bei >5 Min.
12. **mandate_id als Deep-Link** im Shadow-Aggregat; GREEN/YELLOW/RED als gestapelter Balken/Donut; Gesamt-Verdikt als Kriterien-Checkliste.

### Groessere Massnahmen (Datenintegritaet + Backend-Anpassung)
13. **Policy-Versionierungs-Schutz (hohe Prioritaet):** Speichern auf aktiver Policy hart blocken oder automatisch klonen; Save-Button disablen solange `adminPolicyValidateRow` Probleme meldet (Σtarget/min<=target<=max). `max_real_estate_bps/max_alternatives_bps/min_liquidity_bps` editierbar machen (`PUT /admin/optimizer-policies/{id}` existiert).
14. **Editierbare 5x5-Korrelations-Matrix** als Number-Input-Grid (gesperrte Diagonale 1.0, Auto-Spiegelung, Live-Validierung [-1,1] + PSD-Check vor Speichern); JSON-Textarea als Experten-Modus behalten.
15. **„Nur Luecken fuellen"-Schalter** (overwrite=False) + Datumsbereich-Picker fuer beide Backfills; Quelle-Indikator (admin/backfill) pro Zelle; manuelle Werte beim Backfill schuetzen.
16. **Asynchroner Backfill mit Job-ID + Progress** statt blockierendem 120s-Request (`sec-acprices`).
17. **Batch-Save-Endpoint** fuer Jahresrenditen (Dirty-Tracking, nur geaenderte Zellen) statt bis zu 100 Einzel-PUTs; %-Eingabe mit BPS-Konvertierung (Helfer `adminBpsToPercentValue` existiert).
18. **Mapping Dry-Run/Apply als ein Workflow:** Dry-Run-Ergebnis in Tabelle (Produkt → Kandidat), dann pro Zeile bestaetigen — statt vier separater Buttons.
19. **Benutzerliste als sortier-/filterbare Tabelle** (Name, Rolle, Status, Letzter Login), Rollen als Badges, Soft-Delete-Aktion, Passwort-Staerke-Anzeige (konsistent zu Neu-Anlage).
20. **Native confirm/prompt/alert** in der Policy-Sektion durch das App-Notice-System (`showAppSuccess/showAppError`) ersetzen.

---

## 5. Empfohlene Umsetzungs-Reihenfolge mit Aufwandsschaetzung

| # | Massnahmen | Aufwand | Nutzen |
|---|---|---|---|
| **Sprint 1 — Quick-Wins & Konsistenz** | Punkte 1-7 | ~1-1.5 Tage | Hoch: sofort sichtbare Politur, beseitigt Verwirrung & toten Code |
| **Sprint 2 — Datenintegritaet (kritisch)** | Punkte 13, 15 | ~2-3 Tage | **Sehr hoch:** verhindert stilles Ueberschreiben aktiver Policies & manueller Marktdaten |
| **Sprint 3 — Verschenkte Daten rendern** | Punkte 8, 9, 10 | ~3-4 Tage | Hoch: Daten liegen schon vor, nur Frontend-Render |
| **Sprint 4 — Fehleranfaellige Eingaben** | Punkte 14, 11, 18 | ~4-5 Tage | Hoch: reduziert Beraterfehler bei mathematisch heiklen Eingaben |
| **Sprint 5 — Skalierung & UX-Feinschliff** | Punkte 16, 17, 19, 12, 20 | ~5-7 Tage | Mittel: Performance & Komfort |

**Gesamtaufwand grob:** ~15-20 Personentage fuer das volle Programm. **Empfehlung:** Sprint 1 + 2 zuerst (~3-4 Tage) — groesster Sicherheits- und Wahrnehmungsgewinn bei geringstem Risiko.

---

**Fazit:** Das Admin-Backend ist solide gebaut — kein Bluff, keine Stubs. Die echten Schwachstellen sind (a) zwei Datenintegritaets-Fallen (aktive Policy ohne Versionierung, Backfill-Overwrite), (b) bereits berechnete Daten, die das Frontend wegwirft, und (c) eine zu rohe, fehleranfaellige Eingabe-Ergonomie. Nichts davon ist „kaputt", aber Punkt (a) sollte vor dem naechsten Beratungs-Release adressiert werden.
