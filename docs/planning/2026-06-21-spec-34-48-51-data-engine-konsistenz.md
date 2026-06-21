# Spec: Marktdaten-/Engine-Konsistenz-Cluster (#34, #49, #50, #51, #48)

- **Datum:** 2026-06-21
- **Cluster:** Roadmap-Master 2026-06-14, Punkte #34, #48, #49, #50, #51
- **Branch (Vorschlag):** `codex/u34-rental-inflation-cma`
- **Scope-Charakter:** Dieser Cluster ist zu ~80% **Verifikation + kleine Härtung + Dokumentation**. Vier der fünf Punkte sind im Kern bereits implementiert. Diese Spec belegt den IST mit `file:line`, definiert die echten Restlücken und pinnt das gewünschte Verhalten mit Regressionstests.
- **Quellenmaxime:** Alle IST-Aussagen unten sind per Read-Tool gegen die aktuelle Repo-Kopie verifiziert (`file:line`). Keine Annahmen über nicht gelesenen Code.

> **WICHTIG für Codex:** NICHT refactoren, was funktioniert. Pro Punkt nur die unter „SOLL / konkrete Änderungen" gelisteten Deltas. Bestehende grüne Tests dürfen nicht brechen. Anlagephilosophie ADR-003 (kein Markt-Timing) ist für #48/#49/#50 hart bindend.

---

## Gesamt-Bewertung (Ampel pro Punkt)

| # | Titel | IST-Reife | Restarbeit |
|---|-------|-----------|------------|
| 34 | Miete inflationsindexiert | 🟢 **Vollständig implementiert** (BE+FE+DB+Tests) | Nur Pinned-Verifikations-Test + Doku |
| 49 | Rebalancing-Trigger-Konsistenz | 🟢 **Kein Market-Timing vorhanden** (belegt) | Audit-Doc + ein konsolidierter Anti-Trigger-Regressionstest |
| 50 | Provider-Health-Dashboard | 🟡 **Backend + UI vorhanden**, Event-Historie/Reset fehlt im UI | UI-Erweiterung (Recovered/Reset) + Test |
| 51 | CMA-Pflegeprozess | 🟡 **Versionierung + source/notes vorhanden**, keine konservative-Default-Leitplanke, kein Prozess-Doc | Prozess-Doc + optionale Plausibilitätswarnung + Test |
| 48 | Stochastic-Optimizer als Default | 🟡 **Aggregat + Kriterium + Admin-UI vorhanden** | Default-Switch-Kriterium formalisieren (Doc-Update) + Pinned-Test des Kriteriums |

---

## #34 — [ENG] Miete inflationsindexiert (optional)

### Ziel
Pro Immobilie ein Flag „Miete inflationsgebunden". Ist es gesetzt, trägt der
abgeleitete Mietertrag-Cashflow `is_inflation_linked=1` und wächst in der
Projektion mit der Teuerung; ohne Flag bleibt der Mietertrag nominal flach.

### IST (verifiziert)
Die Funktionalität ist **end-to-end bereits gebaut** (vermutlich aus dem
genannten `feat/rental-inflation-linked`-Branch heraus eingeflossen):

- **DB-Spalte (Migration):** `database.py:256`
  `('property_rental_inflation_linked', 'INTEGER NOT NULL DEFAULT 0')`
- **ORM-Modell:** `models/wealth.py:32`
  `property_rental_inflation_linked = Column(Integer, nullable=False, server_default="0", default=0)`
- **Pydantic-Schemas:** `schemas/wealth.py:31` (Create), `:94` (Update, Optional), `:142` (Response, default 0)
- **Ableitungslogik:** `services/wealth_cashflows.py:220-224` — bei `ptype == "Immobilien"` wird
  `_mk(..., inflation_linked=int(getattr(pos, "property_rental_inflation_linked", 0) or 0))`
  aufgerufen; `_mk` setzt `is_inflation_linked=1 if inflation_linked else 0` (`:208`).
- **Projektion respektiert das Flag:** `services/cashflow_timeline.py:252-254`
  inflationiert nur `is_inflation_linked`-Cashflows (B1-Konvention).
- **Frontend (Immobilien-Editor):**
  - Lesen/Vorbelegen: `5eyes_v2.html:15400`
    `setCheckboxValue('maw-immo-rent-inflation',!!pos.property_rental_inflation_linked);`
  - Speichern: `5eyes_v2.html:21363`
    `payload.property_rental_inflation_linked=getCheckboxValue('maw-immo-rent-inflation')?1:0;`
- **Bestehende Tests (grün):**
  - `tests/test_rental_inflation_linked.py` (Flag gesetzt→1, nicht gesetzt→0, fehlendes Attribut→0)
  - `tests/test_frontend_rental_inflation.py` (FE-Checkbox-Kontrakt)

### SOLL-Design
Kein neuer Code nötig. #34 wird als **erledigt verifiziert** und mit **einem
Integrations-Pinned-Test** gegen Regression abgesichert, der die heute fehlende
*Kette* prüft: Position mit Flag → `derive_wealth_cashflows` → `cashflow_timeline`
liefert in Zukunftsjahr einen *höheren* Mietertrag als ohne Flag.

### Konkrete Änderungen
1. **NEU `tests/test_rental_inflation_projection_chain.py`** (reiner Logik-Test, keine DB):
   - Baue zwei `SimpleNamespace`-Immobilienpositionen (Flag=1 vs Flag=0), je `property_rental_income_rappen=4_800_000`.
   - `derive_wealth_cashflows([pos])` → Mietertrag-Cashflow.
   - Reiche den Cashflow in `cashflow_timeline.totals_for_year(...)` / die existierende Inflationsfunktion (analog `tests/test_audit_b1_cashflow_inflation.py`, das das Muster vormacht) für ein Jahr `start_year + N` mit positivem Inflationspfad.
   - Assert: Flag=1 → Betrag in Jahr N **> nominal**; Flag=0 → Betrag == nominal.
2. **KEINE** Änderung an `wealth_cashflows.py`, Modell, Schema, DB oder Frontend.

### Test-Plan
- Neuer Chain-Test grün.
- Bestehende `test_rental_inflation_linked.py` + `test_frontend_rental_inflation.py` bleiben grün.

### Edge-Cases
- Position ohne Attribut (Legacy-Objekt) → `getattr(...,0)` → nominal flach (bereits getestet).
- `property_rental_income_rappen=0` → kein Cashflow erzeugt (`_mk` `amount<=0` Guard, `wealth_cashflows.py:198`); Flag irrelevant.
- Inaktive/gelöschte Position → kein Cashflow (`wealth_cashflows.py:185-187`).

### OWNER-DECISIONs
- **OD-34.1:** Wenn #34 als „erledigt" akzeptiert wird, kann er im Roadmap-Master 2026-06-14 (`:55`) auf `[✓]` gesetzt werden — Doku-Änderung außerhalb dieser Spec, separat.
- **OD-34.2:** Soll die Inflationsindexierung auch in der Doppelerfassungs-Warnung (#38, `_cashflowDuplicateHints`) als „indexiert" gekennzeichnet werden? (Standard: nein — Out-of-Scope.)

---

## #49 — [ENG] Rebalancing-Trigger-Konsistenz (Audit + Pinned-Test)

### Ziel
Beweisen, dass KEINE automatische Markt-Timing-Logik aktiv ist. Re-Balancing
darf ausschließlich über Eignungsprüfung / Kundenmeldung erfolgen
(Anlagephilosophie, ADR-003). Audit-Ergebnis dokumentieren + Regressionstest,
der eine künftige Auto-Trigger-Einführung verbietet.

### Audit-Ergebnis: **NEIN — es existiert kein Markt-Timing-Auto-Trigger.** (Beleg)

1. **ADR-003 ist die bindende Doktrin** (`docs/adr/ADR-003-anlagephilosophie-no-market-timing.md`):
   - `:24-26` „Keine Auto-Trigger: Es gibt keinen Cron-Job, keinen Watcher, keinen Notification-Endpoint der bei Marktbewegung feuert."
   - `:33-34` „Marktdaten nur als Bewertungs-Input … niemals als Trigger."
   - `:49-53` Konkrete Code-Regeln (kein Market-Watcher; PDF/Sub-App-Texte per Drift-Test geprüft).

2. **Alle Scheduler-Jobs sind ZEIT-getrieben, nicht PREIS-getrieben:**
   - `services/market_data/scheduled.py` enthält genau zwei Jobs:
     `daily_cache_purge_job` (`:22`, löscht abgelaufenen Cache) und
     `weekly_validation_job` (`:41`, Cross-Validation einer fixen Symbol-Liste).
     **Keiner** liest Preisbewegung und löst daraufhin eine Allokations-/Handelsaktion aus.
   - Der `weekly_validation_job`-Webhook (`:87-106`) feuert NUR bei *Datenqualitäts*-Alerts
     (Provider-Divergenz > `threshold_bps`), nicht bei Marktbewegung, und löst KEIN Rebalancing aus.
   - `routers/system.py` Refresh-Endpoints (`/market-data/refresh-now` `:505`,
     `/fx-rates/refresh-now` `:531`, `/market-data/purge-now` `:619`) sind **manuelle
     Berater-Trigger** (Recovery), kein Auto-Reagieren.
   - `routers/system.py:143-156` `recommendation-runs/cleanup` ist explizit als
     „Berater-Trigger, kein Cron (Anlagephilosophie ADR-003)" kommentiert.

3. **Das Review/Beratungsabschluss-UI enthält bewusst KEIN Rebalancing mehr** (Bug-#9):
   - `tests/test_bug9_review_no_rebalancing.py` pinnt: keine „Portfolio-Check"-Card,
     kein „IST vs. SOLL", kein „Handelsliste"/„Massnahme", kein Drift-Hotspot im Review-Tab
     (`:53-104`); die Renderer-Funktion ist No-op (`:79-104`).
   - Rebalancing-Trade-Sheets existieren NUR im **Depot-Check** (separater, Berater-getriebener
     Workflow), nicht als automatischer Marktreaktions-Pfad.

4. **„drift"-Treffer im Code sind harmlos:** Sie betreffen
   - Test-/Snapshot-„Drift-Wache" (CMA-Drift, Monolith-Inventory-Drift, Glossar-Drift) — also
     *Regressions*-Drift, nicht *Markt*-Drift, und
   - die Depot-Check-SOLL/IST-Abweichungsanzeige (Berater-Workflow).
   Keiner dieser Treffer ist ein automatischer Markt-Trigger.

**Fazit:** Die Anlagephilosophie ist heute technisch eingehalten. #49 reduziert sich auf
(a) ein konsolidiertes Audit-Doc und (b) einen **Anti-Regressions-Test**, der die Doktrin pinnt.

### SOLL-Design
Eine *einzige*, gut benannte Regressionstest-Datei, die strukturell verbietet, dass
in den marktdaten-/scheduler-nahen Modulen je ein preisgetriggerter Rebalancing-Pfad
entsteht. Plus ein knappes Audit-Markdown unter `docs/audits/`.

### Konkrete Änderungen
1. **NEU `tests/test_no_market_timing_rebalance_trigger.py`:**
   - **Test A (Scheduler-Job-Whitelist):** Importiere `services/market_data/scheduled.py`,
     sammle die definierten Job-Funktionsnamen und asserte, dass die Menge eine Teilmenge
     der erlaubten Zeit-Jobs ist (`{daily_cache_purge_job, weekly_validation_job}`). Schlägt
     fehl, sobald ein neuer Job hinzukommt → zwingt zu bewusster ADR-003-Prüfung.
   - **Test B (kein Preis→Rebalance-Kopplungsbegriff):** Grep über
     `services/market_data/*.py` + `price_updater.py` auf verbotene Kopplungs-Token
     (z.B. `auto_rebalance`, `rebalance_on_price`, `market_signal`, `trigger_rebalanc`).
     Assert: 0 Treffer. (Token-Liste im Test als Konstante + Kommentar mit ADR-003-Verweis.)
   - **Test C (Review bleibt rebalancing-frei):** Re-assert (oder delegiere an die schon
     vorhandenen Bug-#9-Invarianten) dass `page-rv` kein „Handelsliste"/„Massnahme" enthält —
     dünner Wrapper, der Bug-#9 als ADR-003-Garantie markiert.
2. **NEU `docs/audits/2026-06-21-rebalancing-trigger-konsistenz-audit.md`:**
   - Audit-Ergebnis (= obige Belege mit `file:line`), Verdikt „kein Market-Timing",
     Verweis auf den neuen Pinned-Test und ADR-003.
3. **KEINE** Produktivcode-Änderung.

### Test-Plan
- Neuer Test grün.
- Bestehende `test_bug9_review_no_rebalancing.py`, `test_glossar_consistency.py`,
  `test_adr_consistency.py` bleiben grün.

### Edge-Cases
- Token-Grep darf nicht auf Kommentare/Doc-Strings anschlagen, die das Verbot *beschreiben*
  (z.B. ADR-Zitate). Lösung: Test grept Produktivmodule, nicht `docs/` und nicht Testdateien;
  und sucht auf konkrete Identifier-Muster, nicht auf das Wort „rebalancing" allein.
- Neuer legitimer Zeit-Job (z.B. zusätzliche Reference-Data-Pflege) → Test A schlägt
  bewusst fehl; Entwickler erweitert die Whitelist NUR nach ADR-003-Prüfung (im Test-Kommentar dokumentiert).

### OWNER-DECISIONs
- **OD-49.1:** Whitelist-Ansatz (Test A) vs. reiner Token-Grep (Test B)? Empfehlung: **beide**
  (A fängt strukturelle Erweiterung, B fängt Inline-Kopplung).
- **OD-49.2:** Soll der `weekly_validation_job`-Webhook (Datenqualitäts-Alert) im Audit-Doc
  explizit als „erlaubt, weil nicht markt-, sondern datenqualitäts-getrieben" festgehalten
  werden? Empfehlung: **ja** (klärt die Grenze für künftige Reviewer).

---

## #50 — [DATA] Marktdaten-Provider-Health-Dashboard

### Ziel
Die bestehende `HealthState`/Provider-Validierung + persistente Provider-Health-Historie
in der Admin-UI sichtbar und steuerbar machen.

### IST (verifiziert)
**Backend ist vollständig; UI zeigt den Live-Status bereits, aber nicht Historie/Recovery/Reset.**

- **In-Memory HealthState:** `services/market_data/health.py` — `is_healthy/mark_healthy/mark_unhealthy`,
  TTL-Backoff (`:29-65`). Aggregator skippt unhealthy Provider.
- **Persistente Health-Events:** `services/market_data/provider_health_registry.py`
  - Tabelle `provider_health_events` (`:18-102`), idempotentes Schema/Upgrade (`ensure_provider_health_table` `:70`).
  - `mark_unhealthy` (`:111`) / `mark_healthy` (→ status `recovered`, `:158`).
  - `list_provider_health` (`:201`), `latest_provider_health_by_name` (`:230`), `reset_provider_health` (`:243`).
- **Admin-Status-Service:** `services/market_data/admin.py:155` `build_market_data_status`
  liefert `providers_health` (`collect_provider_health` `:29` merged In-Memory `is_healthy()`
  **mit** dem persistenten Registry-Event: `registry_status, reason, observed_at,
  unhealthy_until, recovered_at, consecutive_errors`, `:58-67`), plus `cache`, `recent_validations`,
  `scheduler_jobs`.
- **Endpoints:**
  - `GET /admin/market-data/status` (`routers/market_data.py:19`)
  - `GET /admin/system/market-data/provider-health` (`routers/system.py:563`) — reine Event-Liste.
  - `POST /admin/system/market-data/provider-health/reset` (`routers/system.py:578`) — auditierter Reset.
- **Frontend (Admin → „Datenpipeline"):**
  - Nav-Button `asec-market-data` (`5eyes_v2.html:23090`), Panel `sec-market-data` (`:23237`).
  - Loader `loadMarketDataStatus` (`:12846`) → `renderMarketDataStatus` (`:12871`).
  - Renderer zeigt **heute schon** je Provider: OK/Fehler-Badge, `reason`,
    `consecutive_errors`, `unhealthy_until` („gesperrt bis", `:12881-12888`); dazu Cache,
    Cross-Validation-Alerts, Scheduler-Jobs (`:12895-12936`).

### Echte Lücken (das ist #50)
1. **Recovery/Historie unsichtbar:** Der Renderer zeigt Detail nur `if (!p.healthy)`
   (`:12881`). `recovered_at`/`registry_status='recovered'` und `observed_at` werden NICHT angezeigt;
   ein zuletzt erholter Provider sieht aus wie „nie ein Problem".
2. **Kein Reset-Bedienelement:** Der auditierte Reset-Endpoint hat **kein UI**.
3. **Kein dedizierter Test**, dass die Provider-Health-Detailfelder im Panel gerendert werden.

### SOLL-Design
Minimal-invasive Erweiterung des bestehenden „Datenpipeline"-Panels — **keine** neue Section,
**kein** Polling (ADR-003: kein Live-Auto-Refresh), nur der vorhandene „Aktualisieren"-Button.

- Pro Provider zusätzlich anzeigen: `registry_status` (unhealthy/recovered/unknown),
  `observed_at` (letztes Event) und — bei `recovered` — `recovered_at`. Healthy-Provider mit
  vergangenem Problem bekommen einen dezenten „zuletzt erholt …"-Hinweis.
- Ein „Provider-Health zurücksetzen"-Button (optional je Provider oder global) → ruft
  `POST /admin/system/market-data/provider-health/reset` → danach `loadMarketDataStatus(true)`.
- Sprache strikt neutral/technisch (Glossar-Drift-Test, ADR-003): keine „Chance/jetzt
  handeln"-Begriffe.

### Konkrete Änderungen
1. **`5eyes_v2.html` `renderMarketDataStatus` (~`:12876-12889`):** Detail-Block auch für
   `p.healthy && p.recovered_at` rendern („zuletzt erholt: <recovered_at>"), und `registry_status`
   als kleines Meta-Label ergänzen. Bestehende Felder unverändert lassen.
2. **`5eyes_v2.html` `sec-market-data`-Panel (~`:23243`):** neben „Aktualisieren" einen Button
   `btn-admin-mdata-health-reset` mit `onclick="resetProviderHealth()"`.
3. **`5eyes_v2.html` neue JS-Funktion `resetProviderHealth()`:** `API.post('/admin/system/market-data/provider-health/reset', {})`
   → `showAdminResult(...)` → `loadMarketDataStatus(true)`; mit Bestätigungs-Guard (kein `setInterval`).
4. **NEU `tests/test_frontend_admin_provider_health_panel.py`:** asserte, dass `renderMarketDataStatus`
   die Felder `recovered_at` und `registry_status` referenziert, der Reset-Button-Anker
   (`btn-admin-mdata-health-reset`) und `resetProviderHealth` existieren, der Endpoint-String
   `'/admin/system/market-data/provider-health/reset'` vorkommt, und **kein** `setInterval`
   im Loader/Reset-Block steht (analog `test_frontend_admin_shadow_aggregate_panel.py:94-106`).

### Test-Plan
- Neuer FE-Kontrakt-Test grün.
- `tests/test_admin_market_data_status.py` (Backend-Status-Service) bleibt grün.
- `tests/test_provider_discovery.py`, `tests/test_market_data_aggregator.py` bleiben grün.

### Edge-Cases
- Registry-Tabelle leer/unavailable → `collect_provider_health` liefert `registry_status='unknown'`
  + leere Felder (`admin.py:54-67`); Renderer muss `recovered_at===null` tolerieren.
- Reset bei laufendem Backoff: setzt nur die *persistente Historie* zurück; In-Memory `HealthState`
  bleibt (das ist gewollt — In-Memory verfällt per TTL). Im Reset-Hinweis so formulieren
  („Historie zurückgesetzt; Laufzeit-Backoff verfällt automatisch").
- Mandanten-Trennung: Provider-Health ist **systemweit** (kein Tenant-Bezug) und admin-only —
  unproblematisch, aber im Reset-Handler bleibt `require_admin` (bereits so, `system.py:578`).

### OWNER-DECISIONs
- **OD-50.1:** Reset global ODER pro Provider? Endpoint kann beides (`provider_name` optional,
  `system.py:586`). Empfehlung: **global** als ein Button (einfachstes UI), pro-Provider später.
- **OD-50.2:** Soll die volle Event-Historie (`/admin/system/market-data/provider-health`,
  bis 500 Events) als ausklappbare Tabelle gezeigt werden, oder reicht der „letzte Status je
  Provider" im bestehenden Panel? Empfehlung: **letzter Status** jetzt; Volltabelle optional.

---

## #51 — [DATA] CMA-Werte-Pflegeprozess (konservative Defaults betonen)

### Ziel
Kapitalmarktannahmen (CMA) versioniert, mit **konservativen Defaults**
(**Maxime: im Zweifel den tieferen Renditewert nehmen**), Quelle und Datum
dokumentiert pflegen — als nachvollziehbarer, FINMA-tauglicher Prozess.

### IST (verifiziert)
**Versionierung + Source/Datum-Felder existieren. Es fehlt die konservative-Default-Leitplanke
und ein dokumentierter Pflegeprozess.**

- **Modell `CapitalMarketAssumption`** (`models/allocation.py:157`):
  - Versionierung: `version` (`:162`), `valid_from` (`:163`), `valid_until` (`:164`),
    `is_current` (`:165`).
  - Herkunft/Datum: `source` (`:223`, default `"Portfolio Management intern"`),
    `notes` (`:224`), `created_by` (`:225`), `created_at` (`:226`), `updated_at`, `deleted_at`.
  - Returns/Vols/Korrelationen/NS-Curve/KGV-MR/Risikoprämien je bps (`:166-222`).
- **DB:** Tabelle `capital_market_assumptions` (`5eyes_schema_v4.0_FINAL.sql:825`), Unique-Index
  auf `(assumption_set_name) WHERE is_current=1 AND deleted_at IS NULL` (`:860`),
  `updated_at`-Trigger (`:1348`). TargetAllocation/RecommendationRun snapshotten
  `capital_market_assumptions_id` (`models/allocation.py:61`, `models/review.py:259`).
- **Update-Endpoint = Versionierung:** `routers/allocation.py:322` `update_cma`
  - Archiviert die alte Version (`is_current=0`, `:347`), erhöht `version` (`:351`),
    merged fehlende Felder aus der Vorversion (`:344-349`, partial-update-safe),
    schreibt Audit-Log (`:360-361`).
- **Read-Endpoint:** `GET /capital-market-assumptions/current` (`allocation.py:307`).
- **Schemas:** `CapitalMarketAssumptionCreate` (`schemas/allocation.py:279`, inkl. `source`/`notes`),
  `...Response` (`:323`).
- **Konservativ-Maxime existiert bereits als Engine-Konvention an anderer Stelle:** z.B.
  risk-free = `liquidity_return_bps` (tiefer Wert) in #35. Es gibt aber **keine** Validierung,
  die beim CMA-Schreiben vor zu optimistischen Werten warnt.

### Echte Lücken (das ist #51)
1. **Keine konservative-Default-Leitplanke:** `update_cma` akzeptiert beliebige Renditewerte ohne
   Plausibilitäts-/Konservativitätsprüfung. Es gibt keine dokumentierte Default-CMA mit „tieferer Wert".
2. **`source` ist nicht erzwungen** und defaultet auf „Portfolio Management intern" — Quelle/Datum
   werden faktisch optional, was dem dokumentierten Pflegeprozess widerspricht.
3. **Kein Prozess-Doc** das den Pflege-Workflow + die Konservativ-Maxime festschreibt
   (`docs/cma_import_workflow.md` existiert — prüfen und ergänzen, nicht duplizieren).

### SOLL-Design
- **Prozess-Doc** (primäres Deliverable): wer pflegt wann, woher die Werte stammen, wie
  versioniert wird, und die **harte Maxime**: *bei mehreren plausiblen Renditeerwartungen immer
  den tieferen Wert (Ruhestandsgelder-konservativ)* — konsistent mit Memory `feedback_conservative_values.md`.
- **Optionale, nicht-blockierende Plausibilitäts-Warnung** beim CMA-Update: Wenn eine neue
  Return-Annahme die Vorversion um mehr als einen Schwellenwert (z.B. > 200 bps) nach OBEN
  abweicht, gibt der Endpoint eine `warnings`-Liste zurück (KEIN Hard-Block — der Berater
  entscheidet, aber die Abweichung wird sichtbar und auditierbar).
- **Source/Datum dokumentationspflichtig im UI** (Pflichtfeld im CMA-Editor), nicht im DB-Schema
  erzwungen (Backwards-Compat).

### Konkrete Änderungen
1. **NEU `docs/handbook/cma-pflegeprozess.md`** (oder Ergänzung in `docs/cma_import_workflow.md` —
   siehe OD-51.3):
   - Pflege-Rhythmus, Verantwortliche, Quellenangabe-Pflicht, Versionierungs-Schritte
     (archivieren→neue Version), und die **Konservativ-Maxime** prominent (mit Verweis
     `feedback_conservative_values.md`).
   - Verweis auf `feedback_conservative_values.md`-Logik (tieferer Wert) und ADR-005 (Datenpipeline).
2. **`routers/allocation.py` `update_cma` (~`:335-363`):** optionale, **nicht-blockierende**
   Konservativitäts-/Plausibilitäts-Prüfung:
   - Vergleiche je `*_return_bps`-Feld der neuen Version gegen die Vorversion (`prev`).
   - Sammle `warnings` für Felder, die > `CMA_RETURN_INCREASE_WARN_BPS` (Konstante, Default 200)
     nach oben springen.
   - Response um `warnings: list[str]` erweitern (Schema-Erweiterung in
     `CapitalMarketAssumptionResponse` als optionales Feld, default `[]`), Audit-Log-`new_value`
     um die Warn-Anzahl ergänzen. **Keine** Verhaltensänderung wenn keine Vorversion existiert.
3. **`5eyes_v2.html` CMA-Editor:** `source`/`valid_from` als Pflichtfeld markieren (clientseitige
   Validierung vor PUT) und die `warnings` aus der Response anzeigen (dezenter Hinweis-Block,
   neutrale Sprache). *(Nur falls ein CMA-Editor-Panel existiert; sonst OD-51.4.)*
4. **NEU `tests/test_cma_conservative_warning.py`:**
   - Vorversion mit `equity_intl_return_bps=500`, Update auf `=800` → Response enthält `warnings`
     mit Equity-Feld.
   - Update mit gleich/niedriger → `warnings == []`.
   - Erste Version (keine Vorversion) → `warnings == []` (kein Vergleich möglich).
   - Versionierung weiterhin korrekt (alte `is_current=0`, neue `version=prev+1`).

### Test-Plan
- Neuer Warn-Test grün.
- Bestehende CMA-Tests grün: `tests/test_audit_f3_cma_drift.py`,
  alle Tests die `update_cma`/`CapitalMarketAssumption` nutzen (Suche im Test-Ordner vor Merge).
- Doc-Konsistenz-Tests (falls ein `test_*_doc.py` Pfade prüft) anpassen, falls neues Doc verlinkt wird.

### Edge-Cases
- Partial-Update: Da `update_cma` fehlende Felder aus `prev` merged (`:349`), darf die Warn-Prüfung
  nur Felder vergleichen, die im *neuen* Payload tatsächlich gesetzt waren (`exclude_unset`, `:336`).
- Negative/Null-Returns (Bonds in Tiefzinsphase) → kein Warn (nur Anstieg > Schwelle warnt).
- `warnings` darf TA-Generierung niemals blockieren (nur informativ — ADR-konform, Berater entscheidet).
- Konservativ-Maxime ist eine **Prozess-Regel**, kein Hard-Clamp: die Engine soll keine Werte
  automatisch nach unten korrigieren (das wäre stille Datenmanipulation) — sie macht Abweichung sichtbar.

### OWNER-DECISIONs
- **OD-51.1:** Schwellwert `CMA_RETURN_INCREASE_WARN_BPS` — Default **200 bps**? Anpassbar.
- **OD-51.2:** Warnung nur informativ (empfohlen) ODER soll ein 4-Augen-Bestätigungsschritt
  (z.B. `confirm_optimistic=true` im Body) verlangt werden, bevor optimistischere Werte gespeichert
  werden? Empfehlung: **informativ jetzt**, 4-Augen optional später.
- **OD-51.3:** Neues Doc unter `docs/handbook/` ODER Ergänzung des vorhandenen
  `docs/cma_import_workflow.md`? Empfehlung: **vorhandenes Doc lesen und ergänzen**, kein Duplikat.
- **OD-51.4:** Existiert ein CMA-Editor-Panel im Frontend? (Vor Implementierung von FE-Punkt 3
  per Grep prüfen: `capital-market-assumptions` / `loadCma` in `5eyes_v2.html`.) Falls nein →
  FE-Teil entfällt, nur Backend-Warnung + Doc.

---

## #48 — [ENG] Stochastic-Optimizer als Default prüfen

### Ziel
Aus dem Shadow-Comparison-Aggregat (Methodology §4) ein klares, getestetes
**Default-Switch-Kriterium** ableiten und auswertbar machen: wann darf
`optimizer_mode` von `house_matrix` auf `shadow_stochastic`/`stochastic` wechseln?

### IST (verifiziert)
**Aggregat, Kriterium-Funktion, Admin-Endpoint und Admin-UI existieren bereits.**

- **Shadow-Vergleich pro Mandat:** `services/shadow_comparison.py:22` `build_shadow_comparison_payload`
  (Methodology §3 Metriken), Verdikt-Klassifizierung `classify_shadow_verdict` (`:137`,
  GREEN/YELLOW/RED-Schwellen).
- **Aggregat über alle Mandate:** `aggregate_shadow_comparisons` (`:264`) → `counts`, `percentages`,
  `examples`, `errors`, **`default_switch_ready`** + **`default_switch_reason`**.
- **Default-Switch-Kriterium (Methodology §4) ist bereits kodiert:** `_gesamt_verdikt` (`:378`):
  - `red > 0` → blockiert (`:392`).
  - `total < 3` → blockiert („mindestens 3 Mandate", `:394`).
  - `green/total < 2/3` → blockiert (`:396`).
  - sonst → freigegeben (`:400`).
- **Admin-Endpoint:** `GET /admin/system/shadow-comparison-aggregate` (`routers/system.py:295`,
  `require_super_admin`).
- **Setting + Umschalt-Endpoint:** `optimizer_mode` mit erlaubten Werten
  `{house_matrix, shadow_stochastic, stochastic}` (`routers/system.py:53`), GET/PUT
  (`:233`/`:241`, auditiert `OPTIMIZER_MODE_CHANGE`).
- **Admin-UI vorhanden:** Section `sec-shadow-comparison-aggregate`, Nav `asec-shadow-comparison-aggregate`,
  Loader `loadShadowAggregate`, Renderer `renderShadowAggregate`, zeigt `default_switch_ready`/
  `default_switch_reason`/Counts/Beispiele — gepinnt durch `tests/test_frontend_admin_shadow_aggregate_panel.py`
  (inkl. „kein Polling"-Guard, `:94-106`).
- **Decision-Doc:** `docs/decisions/SHADOW_STOCHASTIC_DEFAULT.md` (Optionen A/B/C, Trigger,
  Engineering-Empfehlung „Option A heute, Option B vorbereitet").
- **Methodology:** `docs/planning/2026-05-23-stochastic-shadow-comparison-methodology.md` (§4-Quelle).

### Echte Lücken (das ist #48)
1. **Kriterium ist im Code, aber das §4-Schwellenwerk ist nicht als eigenständiger,
   regressionssicherer Test gepinnt** (nur indirekt über Aggregator-Tests). Eine künftige
   Änderung an `_gesamt_verdikt` würde den Default-Switch-Entscheid still verschieben.
2. **`SHADOW_STOCHASTIC_DEFAULT.md` benennt den maschinellen Trigger nicht exakt** (Doc spricht
   von „>= 80% GREEN" für Option B, Code verlangt „>= 2/3 GREEN, 0 RED, >= 3 Mandate"). Doc
   und Code-Kriterium müssen **deckungsgleich** dokumentiert werden.
3. **Kein expliziter „Entscheid-Workflow"-Eintrag**, der Aggregat-Ergebnis → Owner-Freigabe →
   Setting-Change verkettet (heute drei lose Teile).

### SOLL-Design
- `_gesamt_verdikt`/`aggregate_shadow_comparisons` als **Single Source of Truth** des
  Default-Switch-Kriteriums festschreiben und mit einem dedizierten Pinned-Test absichern.
- Decision-Doc so aktualisieren, dass der dokumentierte Trigger **wörtlich** dem Code-Kriterium
  entspricht (>= 2/3 GREEN, 0 RED, >= 3 Mandate) und den Endpoint + UI + Setting-Change-Schritt
  als Workflow benennt.
- **Kein automatischer Default-Switch** (ADR-003 + Decision-Doc): Der Switch bleibt eine
  bewusste, auditierte Owner-/Admin-Aktion via `PUT /admin/system/optimizer-mode`. `default_switch_ready=true`
  ist nur ein *Vorschlag*, kein Auto-Trigger.

### Konkrete Änderungen
1. **NEU `tests/test_default_switch_criterion.py`** (reiner Logik-Test gegen `_gesamt_verdikt`,
   in-memory `counts`-Dicts, keine DB):
   - `red>=1` → `ready=False`, Reason enthält „RED".
   - `total<3` (z.B. 2 GREEN) → `ready=False`, Reason enthält „mindestens 3".
   - `green/total < 2/3` (z.B. 3 GREEN / 2 YELLOW = 0.6) → `ready=False`.
   - `green/total >= 2/3`, 0 RED, total>=3 (z.B. 4 GREEN / 1 YELLOW) → `ready=True`.
   - Boundary: exakt 2/3 (z.B. 2 GREEN / 1 YELLOW) → `ready=True` (>= ist inklusiv).
2. **`docs/decisions/SHADOW_STOCHASTIC_DEFAULT.md`:** Abschnitt „Maschinelles Default-Switch-Kriterium"
   ergänzen, der das **exakte** Code-Kriterium zitiert (mit `services/shadow_comparison.py:378`-Verweis),
   und den Workflow beschreibt: Aggregat-Endpoint prüfen → `default_switch_ready` → Owner-Freigabe →
   `PUT /admin/system/optimizer-mode` (auditiert). Die ältere „>= 80% GREEN"-Formulierung als
   Option-B-*Vorsicht*-Trigger kennzeichnen oder an das Code-Kriterium angleichen (OD-48.2).
3. **KEINE** Änderung an `_gesamt_verdikt`/`aggregate_shadow_comparisons`/Endpoint/UI (alles vorhanden),
   außer der Test pinnt das aktuelle Verhalten.

### Test-Plan
- Neuer Kriterium-Test grün.
- Bestehende `tests/test_shadow_comparison_aggregator.py`,
  `tests/test_shadow_stochastic_decision_doc.py`, `tests/test_frontend_admin_shadow_aggregate_panel.py`,
  `tests/test_optimizer_shadow_mode.py` bleiben grün. Falls `test_shadow_stochastic_decision_doc.py`
  Doc-Inhalte asserted → nach Doc-Update synchron halten.

### Edge-Cases
- `total == 0` (keine Shadow-Daten) → `ready=False, "Keine Shadow-Vergleiche persistiert."`
  (`shadow_comparison.py:390-391`) — im Test abdecken.
- Mandate mit kaputtem Shadow-JSON landen in `errors` und zählen NICHT in `counts`
  (`:321-330`) — Kriterium bleibt robust; ggf. Test, dass `errors` `ready` nicht auf True hebt.
- Division: `green/total` mit `total>=3` garantiert kein ZeroDiv (Guard `:390`).

### OWNER-DECISIONs
- **OD-48.1:** Ziel-Modus des ersten Switches — `shadow_stochastic` (vorsichtige Migration,
  Targets bleiben House-Matrix) ODER direkt `stochastic`? Decision-Doc empfiehlt **`shadow_stochastic` zuerst**.
- **OD-48.2:** Soll das dokumentierte Kriterium das Code-Kriterium (>= 2/3 GREEN) übernehmen,
  oder das strengere „>= 80% GREEN" aus dem Decision-Doc in den Code heben? Empfehlung: **Doc an Code
  angleichen** (2/3) + „>= 80% über mehrwöchigen Lauf" als zusätzlichen *Owner*-Vorsicht-Trigger lassen.
- **OD-48.3:** Soll `default_switch_ready` einen Mindest-Stichproben-Umfang > 3 verlangen
  (z.B. >= 5 reale Mandate) bevor in Produktion umgeschaltet wird? (Heute: >= 3.)

---

## Querschnitt: Gemeinsame Invarianten & Reihenfolge

- **ADR-003 ist für #48/#49/#50 bindend:** kein Polling/`setInterval`, kein preisgetriggerter
  Auto-Switch, neutrale Sprache (Glossar-Drift-Test).
- **Konservativ-Maxime (#51)** ist Prozess + Sichtbarkeit, **kein** stiller Auto-Clamp.
- **Empfohlene Umsetzungsreihenfolge:** #34 (Verifikations-Test) → #49 (Audit-Doc + Anti-Trigger-Test)
  → #48 (Kriterium-Test + Doc) → #50 (FE-Erweiterung + Test) → #51 (Backend-Warnung + Doc + Test).
  Punkte sind unabhängig; #50/#51 berühren beide `5eyes_v2.html` → Edits sauber trennen.
- **Keine bestehende grüne Test-Suite darf brechen.** Vor Merge: gezielte Suche nach Tests,
  die `update_cma`, `_gesamt_verdikt`, `renderMarketDataStatus`, `derive_wealth_cashflows` berühren.

## Akzeptanzkriterien (Definition of Done)
1. #34: Chain-Pinned-Test grün; keine Produktivänderung.
2. #49: Audit-Doc vorhanden (Verdikt „kein Market-Timing", belegt); Anti-Trigger-Regressionstest grün.
3. #50: Provider-Health-Recovery + Reset im Admin-Panel sichtbar/bedienbar; FE-Kontrakt-Test grün; kein Polling.
4. #51: Pflegeprozess-Doc mit Konservativ-Maxime; nicht-blockierende CMA-Plausibilitätswarnung + Test; Versionierung unverändert korrekt.
5. #48: Default-Switch-Kriterium als Pinned-Test; Decision-Doc deckungsgleich mit Code-Kriterium; kein Auto-Switch.
