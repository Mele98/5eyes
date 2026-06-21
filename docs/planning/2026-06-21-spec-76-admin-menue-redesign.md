# Spec #76 — Admin-Menue-Redesign (Auftrag 2026-06-10)

- **Roadmap-Punkt:** #76 "Admin-Menue-Redesign — System-Administration auditieren (works vs. placeholder) + userfreundlicher gruppieren/redesignen"
- **Datum:** 2026-06-21
- **Scope:** Frontend-Monolith `5eyes-electron/frontend/5eyes_v2.html` (Admin-Modal `#m-admin`); keine Backend-Pflichtaenderung (alle Sektionen sind bereits gebunden).
- **Branch (Codex):** `codex/u76-admin-redesign`
- **Drift-Test:** `scripts/audit_html_monolith.py` (Inventory-Snapshot, kein Gate — siehe Abschnitt 7).

> Verifikation: Jede `file:line`-Angabe wurde per Read-Tool gegen den IST-Stand geprueft. Backend-Bindungen sind gegen die tatsaechlichen Router (`@router.<verb>`) verifiziert.

---

## 1. Architektur-IST (verifiziert)

Das Admin-Modal ist EIN Overlay `#m-admin` (`5eyes_v2.html:23068`). Layout = Sidebar + Content (`:23076`).
Navigation: Sidebar-Buttons rufen `adminShowSection('sec-...')` (`:23079-23109`); Content = `.admin-sec-panel`-Divs (`:23114-23633`). Default-aktiv ist `sec-health` (`:23082`, `admin-active`).

Sidebar-Gruppen IST (6 Labels):
- Status (`:23081`): Uebersicht, Shadow-Aggregat
- Audit (`:23085`): Protokoll
- Daten (`:23088`): Kurse & Mapping, Datenpipeline, Override, Jahresrenditen, Tageskurse
- Annahmen (`:23095`): Annahmen, Rendite & Vol., Inflation & Korr., Sub-Anlageklassen, House-Matrix
- Zugriff (`:23102`): Benutzerliste, Neuer Benutzer
- Wartung (`:23106`): Datenbank, Update

Backend-Router-Praefixe (verifiziert):
- `/admin/system/*` -> `routers/system.py:36`
- `/admin/optimizer-policies/*` -> `routers/allocation.py:867+`
- `/admin/market-data/*` -> `routers/market_data.py:15`
- `/admin/prices/*` -> `routers/prices.py:13`
- `/fx-rates`, `/fx-rates/current` -> `routers/fx_rates.py:46,84`
- `/users` (GET/POST) -> `routers/auth.py:38` (`users_router`, `:350` GET, `:372` POST)
- `/products/openfigi/auto-apply`, `/products/eodhd/auto-apply`, `/products/{id}/market-override` -> `routers/review.py:48` (`products_router`, `:1178`, `:1356`)
- Software-Update -> KEIN HTTP-Endpoint, Electron-IPC `window.FiveEyesAPI.updates.*` (`5eyes_v2.html:5268,5283`)

---

## 2. Audit-Tabelle — alle 17 Sektionen

Status-Legende: WORKS = vollstaendig an echten Endpoint/IPC gebunden und funktional · PARTIAL = gebunden, aber abhaengig von externer Konfiguration / nur in installiertem Release aktiv · PLACEHOLDER = keine echte Bindung / nur statisch.

| # | Sidebar-Titel | Section-ID (file:line) | JS-Handler (file:line) | Backend-Endpoint (file:line) | Status |
|---|---------------|------------------------|------------------------|------------------------------|--------|
| 1 | Uebersicht (Systemzustand) | `sec-health` `:23116` | `adminLoadSystemHealth` `:9542` | `GET /admin/system/compliance` `system.py:228`; `GET /admin/system/backups` `:61`; `GET /admin/system/paths` `:56` | WORKS |
| 2 | Shadow-Aggregat | `sec-shadow-comparison-aggregate` `:23124` | `loadShadowAggregate` `:12970` | `GET /admin/system/shadow-comparison-aggregate` `system.py:295` | PARTIAL (leer bis Optimizer im stochastic-Modus >=3 Mandate persistiert hat — Empty-State `:23135`) |
| 3 | Protokoll (Audit-Log) | `sec-audit` `:23182` | `loadAdminAuditLog` `:14919` | `GET /admin/system/audit-log` `system.py:74` | WORKS |
| 4 | Kurse & Mapping | `sec-markt` `:23204` | `adminRefreshMarketStatus` `:9795`, `adminRefreshPricesNow` `:10772`, `adminRunOpenfigiAutoApply` `:10629`, `adminRunEodhdAutoApply` `:10653` | `GET /admin/prices/status`; `GET /products/market-data/status`; `POST /admin/prices/refresh`; `GET /admin/prices/mapping-gaps`; `POST /products/openfigi/auto-apply` `review.py:1178`; `POST /products/eodhd/auto-apply` `review.py:1356` | PARTIAL (OpenFIGI/EODHD brauchen API-Keys) |
| 5 | Datenpipeline | `sec-market-data` `:23237` | `loadMarketDataStatus` `:12846` | `GET /admin/market-data/status` `market_data.py:18` | WORKS |
| 6 | Override (Produkt Lookup) | `sec-override` `:23272` | `adminSetProductOverride` `:10719`, `adminClearProductOverride` | `GET /products`; `PUT /products/{id}/market-override` `review.py` | WORKS |
| 7 | Jahresrenditen | `sec-returns` `:23304` | `loadAdminAnnualReturns` `:12555`, `backfillAdminAnnualReturns` `:12593` | `GET /admin/system/annual-returns` `system.py:314`; `POST /admin/system/annual-returns/backfill` `:333`; `PUT /admin/system/annual-returns/{year}/{ac}` `:382` | PARTIAL (Backfill braucht Marktdaten-Provider-Netz) |
| 8 | Tageskurse | `sec-acprices` `:23327` | `loadAdminAssetClassPriceStatus` `:12693`, `backfillAdminAssetClassPrices` `:12727` | `GET /admin/system/asset-class-prices/status` `system.py:432`; `POST /admin/system/asset-class-prices/backfill` `:458` | PARTIAL (netzintensiver Backfill via Provider) |
| 9 | Annahmen (CMA) | `sec-cma` `:23350` | `loadAdminCapitalMarketAssumptions` `:10454`, `saveAdminCapitalMarketAssumptions` `:10605`, `loadAdminFxRates` `:10530`, `saveAdminFxRates` `:10557` | CMA-Endpoints (load/save) + `GET /fx-rates/current` `fx_rates.py:46`; `PUT /fx-rates` `:84` | WORKS |
| 10 | Rendite & Vol. | `sec-cma-rv` `:23378` | shared `saveAdminCapitalMarketAssumptions` | CMA-Endpoints (shared) | WORKS |
| 11 | Inflation & Korr. | `sec-cma-inf` `:23457` | shared `saveAdminCapitalMarketAssumptions` | CMA-Endpoints (shared) | WORKS |
| 12 | Sub-Anlageklassen | `sec-cma-sub` `:23492` | shared `saveAdminCapitalMarketAssumptions` | CMA-Endpoints (shared) | WORKS |
| 13 | House-Matrix | `sec-policy` `:23513` | `adminPolicyCloneActive` `:12535`, `adminPolicySaveRows`, `adminPolicyActivate` | `GET /admin/optimizer-policies` `allocation.py:867`; `/{id}` `:879`; `/{id}/house-matrix` `:988`; `/{id}/activate` `:1031`; `/{id}/clone` `:1064` | WORKS |
| 14 | Benutzerliste | `sec-users` `:23543` | `loadAdminUserList` `:14706` | `GET /users` `auth.py:350` | WORKS |
| 15 | Neuer Benutzer | `sec-newuser` `:23573` | `createNewUser` `:15017` | `POST /users` `auth.py:372` | WORKS |
| 16 | Datenbank & Wartung | `sec-db` `:23604` | `adminBackup` `:13128`, `adminIntegrity` `:13143`, `adminOptimize` `:13160`, `adminLogs` `:13172`, `adminSupportBundle` `:13183` | `POST /admin/system/db/backup` `system.py:190`; `GET /admin/system/db/integrity` `:135`; `POST /admin/system/db/optimize` `:642`; `GET /admin/system/logs/recent` `:66`; `POST /admin/system/support-bundle` `:209` | WORKS |
| 17 | Software-Update | `sec-update` `:23620` | `adminCheckUpdates` `:5264`, `adminInstallUpdate` `:5279`, `adminUpdateStatus` `:13196` | KEIN HTTP — Electron-IPC `window.FiveEyesAPI.updates.check/install/getState` `:5268,5283,5301` | PARTIAL (Auto-Update nur in installiertem Release; im Dev/Browser inaktiv — vom Code dokumentiert `:23624`) |

### Zaehlung
- **WORKS: 12** -> #1, #3, #5, #6, #9, #10, #11, #12, #13, #14, #15, #16
- **PARTIAL: 5** -> #2 (Shadow leer bis Daten), #4 (FIGI/EODHD-Keys), #7 (Backfill-Netz), #8 (Backfill-Netz), #17 (nur installiertes Release)
- **PLACEHOLDER: 0**

> Befund: Es gibt KEINE echten toten Placeholder. Jede der 17 Sektionen ist an einen realen Endpoint bzw. Electron-IPC gebunden. Die 5 PARTIAL-Sektionen sind funktional korrekt, aber von externen Voraussetzungen (Daten, API-Keys, Provider-Netz, installiertes Release) abhaengig — kein Bug, sondern erwartetes Verhalten, im UI bereits durch Risk-Notes/Empty-States kommuniziert.

---

## 3. Was den 5 PARTIAL-Sektionen zum vollen WORKS fehlt (Implementierungsweg)

Keine ist kaputt. Massnahmen = reine UX-/Transparenz-Verbesserungen, kein neuer Endpoint noetig:

1. **#2 Shadow-Aggregat** — Empty-State existiert (`:23135`). Fehlt: deutlicher Voraussetzungs-Badge im Sidebar-Eintrag (graues `n/a`-Pill) wenn `count==0`. Optionaler Deep-Link "Optimizer-Modus pruefen" -> oeffnet #13. Kein Backend-Bedarf.
2. **#4 Kurse & Mapping (OpenFIGI/EODHD)** — Fehlt: Pre-Flight "API-Key konfiguriert: ja/nein". `GET /admin/prices/status` (bereits aufgerufen `:9498/9798`) sollte ein Feld `providers_configured` liefern; FE gated Apply-Buttons disabled + Hinweis wenn kein Key. (Backend-Erweiterung optional.)
3. **#7 / #8 Backfill** — braucht Provider-Netz. Fehlt: einheitlicher Lauf-/Progress-Hinweis + Fehler-Reason-Anzeige bei Netzfehler (FE-only). Endpoints existieren (`:333/:458`).
4. **#17 Software-Update** — Fehlt: sichtbarer Badge "nur in installiertem Release" wenn `updates.getState().enabled === false` (`:9547`). Buttons disabled statt klickbar-ohne-Wirkung. FE-only.

---

## 4. Vorgeschlagene neue Gruppierung (UX-Redesign)

IST mischt Unverwandtes (Annahmen + House-Matrix; "Daten" enthaelt 5 heterogene Sektionen). Neuvorschlag — 7 fachliche Gruppen, gemappt auf die 17 Sektionen:

| Neue Gruppe | Sektionen (IDs) | Begruendung |
|-------------|-----------------|-------------|
| **Betrieb & Monitoring** | `sec-health` (1), `sec-audit` (3) | Tagesgeschaeft: was laeuft, wer hat was getan. |
| **Sicherheit & Zugriff** | `sec-users` (14), `sec-newuser` (15) | Konten/Rollen — `sec-newuser` als Inline-Aktion (s. 5). |
| **Marktdaten & Preise** | `sec-markt` (4), `sec-market-data` (5), `sec-override` (6) | Kurse, Provider-Pipeline, Produkt-Mapping. |
| **Historische Daten** | `sec-returns` (7), `sec-acprices` (8) | Backfill/Zeitreihen (Drift/Backtest-Foundation). |
| **Kapitalmarktannahmen (CMA)** | `sec-cma` (9), `sec-cma-rv` (10), `sec-cma-inf` (11), `sec-cma-sub` (12) | Vier Reiter EINES Datensatzes (shared `saveAdminCapitalMarketAssumptions`) -> Tab-Set. |
| **Engine & Optimizer** | `sec-policy` (13), `sec-shadow-comparison-aggregate` (2) | House-Matrix-Policy + Shadow-Vergleich = Optimizer-Steuerung. |
| **Wartung & Updates** | `sec-db` (16), `sec-update` (17) | Backup/Integrity/Optimize + Software-Update. |

Kernideen:
- **CMA als Tab-Set:** 9-12 teilen denselben Save-Handler -> ein Editor mit 4 internen Tabs statt 4 Sidebar-Eintraegen. Reduziert Sidebar von 17 auf ~10 Top-Level-Eintraege.
- **Neuer Benutzer als Aktion:** `sec-newuser` (15) wird "+ Benutzer anlegen"-Inline-Panel in `sec-users` (14).
- **Sidebar bleibt Navigationsmechanismus** (`adminShowSection`), nur Labels/Reihenfolge/Gruppierung + leichter Tab-Switcher in CMA-Gruppe.

---

## 5. Konkrete FE-Aenderungen (Monolith-sicher)

> Prinzip (Monolith): KEINE Section-IDs umbenennen/entfernen, KEINE JS-Handler-Namen aendern, KEINE bestehenden `onclick`-Strings aendern. Nur (a) Sidebar-Markup `:23079-23109` umsortieren/neu-labeln, (b) optional Tab-Wrapper ergaenzen. Inventory-Snapshot (IDs/Handler/JS-Funktionen) bleibt damit maximal stabil — neue IDs erlaubt, geloeschte/umbenannte nicht.

### 5.1 Sidebar neu strukturieren (`5eyes_v2.html:23079-23109`)
Ersetze die 6 `admin-nav-label`-Bloecke durch die 7 Gruppen aus 4. Reihenfolge/`id`/`onclick` der Buttons unveraendert lassen, nur Position + Gruppen-Label aendern:

```
Betrieb & Monitoring -> #asec-health, #asec-audit
Sicherheit & Zugriff -> #asec-users  (Neuer Benutzer = Inline-Aktion, #asec-newuser entfaellt als Nav-Button)
Marktdaten & Preise  -> #asec-markt, #asec-market-data, #asec-override
Historische Daten    -> #asec-returns, #asec-acprices
Kapitalmarktannahmen -> #asec-cma  (rv/inf/sub als Tabs darin)
Engine & Optimizer   -> #asec-policy, #asec-shadow-comparison-aggregate
Wartung & Updates    -> #asec-db, #asec-update
```

### 5.2 CMA-Tab-Set (ohne IDs zu loeschen)
Panels `sec-cma` `:23350`, `sec-cma-rv` `:23378`, `sec-cma-inf` `:23457`, `sec-cma-sub` `:23492` behalten ihre IDs. Ergaenze OBERHALB von `sec-cma` eine Tab-Leiste mit 4 Buttons, die `adminShowSection('sec-cma'|'sec-cma-rv'|'sec-cma-inf'|'sec-cma-sub')` aufrufen (existierende Funktion wiederverwenden). Sidebar-Buttons `#asec-cma-rv/-inf/-sub` werden aus der Sidebar entfernt (nur Nav-Buttons), die Panels & deren IDs bleiben. Optional duenner Wrapper `adminShowCmaTab(id)` (ruft `adminShowSection` + setzt Tab-active-Klasse).

### 5.3 Neuer Benutzer als Inline-Aktion (`sec-users` `:23543`)
"+ Neuer Benutzer"-Toggle in `sec-users`, der das bestehende `sec-newuser`-Formular sichtbar macht (`adminShowSection('sec-newuser')` oder Inline-`display`-Toggle). `createNewUser` `:15017` unveraendert.

### 5.4 PARTIAL-Transparenz-Badges (FE-only, s. 3)
- `#asec-shadow-comparison-aggregate`: graues Pill solange count==0.
- `#asec-update`: "nur installiertes Release"-Hinweis + disabled-Buttons wenn `updates.getState().enabled===false` (`:9547`).
- `#asec-markt`: OpenFIGI/EODHD-Buttons disabled + Hinweis wenn Provider nicht konfiguriert (sofern Status-Feld vorhanden).

### 5.5 CSS
Wiederverwende `.admin-section-head` `:631`, `.admin-section-title` `:632`, `.admin-pill`, `.admin-sec-btn`. Fuer Tabs neue additive Klasse `.admin-cma-tab` (kein Edit bestehender Selektoren).

---

## 6. Test-Plan

1. **Inventory-Drift (vor/nach):** `python scripts/audit_html_monolith.py --stdout > before.json` (auf `develop`), nach Umbau erneut -> `after.json`. Erwartung: `ids`/`js_functions`/`event_handlers` sind Obermenge des Vorher-Standes (neue Tab-Buttons/Badges duerfen hinzukommen). KEINE der 17 `sec-*`-IDs und KEINE in 2 gelisteten Handler-Namen duerfen verschwinden. Deterministisch sortiertes JSON (`:330`).
2. **Manueller Smoke (alle 17):** Modal oeffnen (`btn-admin-open` `:1952`), jede Gruppe durchklicken, jedes Panel sichtbar + Load-Handler feuert (Netzwerk-Tab gegen Endpoints aus 2).
3. **CMA-Tabs:** alle 4 Tabs umschalten; einmal speichern (`saveAdminCapitalMarketAssumptions`), verifizieren dass alle 4 Panels denselben Set speichern.
4. **Neuer Benutzer inline:** Toggle in `sec-users` -> Formular -> `createNewUser` -> User erscheint in Liste (`POST /users` -> `GET /users`).
5. **PARTIAL-States:** ohne Optimizer-Daten -> #2 Empty + graues Pill; Dev-Modus -> #17 Buttons disabled mit Hinweis.
6. **Regression Default-Section:** beim Oeffnen weiterhin `sec-health` aktiv (`admin-active` `:23082`).
7. **Rollen-Gate:** mit `advisor`-Login erscheint Admin-Button nicht (`display:none` `:1952` + Backend `require_admin` auf `/admin/system/*`). Redesign aendert daran nichts.

---

## 7. Hinweis zum Drift-Test

`scripts/audit_html_monolith.py` ist ein Inventory-Snapshot-Generator (Sprint U-35, `:1-6`), KEIN failing CI-Gate. Output nach `docs/audits/2026-06-02-monolith-inventory.json` (`:21`). Vorgehen: Snapshot vor/nach erzeugen, Diff im PR dokumentieren (nur additive Aenderungen). Falls Snapshot committet ist, neuen Snapshot mit-aktualisieren.

---

## 8. OWNER-DECISIONS

1. **CMA-Tab-Set statt 4 Sidebar-Eintraege** — verkleinert Sidebar deutlich. Bestaetigen? (Default: ja.)
2. **"Neuer Benutzer" als Inline-Aktion** statt eigener Nav-Eintrag. Bestaetigen? (Default: ja.)
3. **Shadow-Aggregat (#2) zu "Engine & Optimizer" verschieben** (weg von "Status"). Bestaetigen? (Default: ja.)
4. **Software-Update (#17) behalten** obwohl im Browser-/Tier-2-Hosting nutzlos? (a) behalten mit "nur installiertes Release"-Badge; (b) ausblenden wenn nicht-Electron-Kontext. Owner-Entscheid (relevant fuers 3-Tier-Hosting-Lizenzmodell).
5. **OpenFIGI/EODHD Provider-Status-Feld** — Backend `GET /admin/prices/status` um `providers_configured` erweitern (kleine Backend-Aenderung), damit FE Apply-Buttons sauber gaten kann? Owner-Entscheid (Default: ja).
6. **Keine Sektion entfernen** — Audit ergab 0 echte Placeholder. Bestaetigen, dass keine der 17 gestrichen wird (Default: ja, alle behalten).

---

## 9. Akzeptanzkriterien

- Sidebar zeigt 7 fachliche Gruppen statt 6 gemischter; Top-Level-Eintraege von 17 auf ~10 reduziert (CMA-Tabs + Inline-Neuer-Benutzer).
- Alle 17 Section-Panels weiterhin erreichbar und funktional (Test-Plan 6 gruen).
- Inventory-Snapshot zeigt nur additive Diffs (keine geloeschten IDs/Handler).
- 5 PARTIAL-Sektionen haben sichtbare Voraussetzungs-Hinweise (Badges/disabled-States).
- Keine Backend-Pflichtaenderung; optionale Backend-Erweiterung (#5 OWNER) separat.
