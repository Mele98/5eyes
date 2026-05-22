# Claude handoff / review request

## Claude→Codex 2026-05-22: U-P19 Daily-Backtest — Frontend fertigstellen

Codex: Mein Backend für den **Daily-Strategie-Backtest** ist fertig, getestet und
gegen echte Marktdaten validiert (Commits `5dddcbc` Backend, `10fee38` Netz-Test,
`07c1293` Regression). Es fehlt **nur noch das Frontend in `5eyes_v2.html`**. Bitte
übernimm das — du bist ohnehin in der Datei.

### A) WICHTIG zuerst: meine Toggle-Änderungen sind schon im Working-Tree (uncommitted)
Ich habe den Auflösungs-Umschalter bereits geschrieben. **NICHT löschen/duplizieren** —
beim Committen erhalten. Vorhandene Marker in `5eyes_v2.html`:
- `bt-fallback-badge` Div (≈ Zeile 2078) — Hinweis bei Fallback auf Jährlich.
- Radios `bt-res-annual` / `bt-res-daily` (name=`bt-resolution`, ≈ 2099/2100) im
  Zeitraum-Panel des `m-bt`-Modals, mit `onchange="btRunBacktest()"`.
- `btReadResolution()` (≈ 8842) — liest 'daily'|'annual'.
- `resolution=`-Param in `btRunBacktest` (≈ 8897) und `downloadBacktestPdf` (≈ 9076).
- Reset auf 'annual' in `openStrategyBacktest` (≈ 8811).
- Fallback-Badge-Logik in `btRender` (≈ 8926: zeigt Badge wenn
  `btReadResolution()==='daily' && data.resolution_used==='annual'`).
- `btRenderLineChart` X-Achsen-Ticks: leitet ganzzahlige Jahre aus der numerischen
  Domäne ab (funktioniert für Annual=ganze Jahre und Daily=float-Labels wie 2020.5).
Falls dein Header-Umbau diese Stellen überschrieben hat: bitte wieder einbauen.

### B) NEU zu bauen: Admin-UI für den Daily-Price-Backfill
Ohne tägliche Kursdaten fällt der Daily-Modus immer auf Jährlich zurück. Es braucht
ein Admin-Panel (Berater muss die Daten einmal befüllen). **Spiegle 1:1 das
bestehende Jahresrenditen-Panel** `sec-returns` (HTML ≈ 18294, Buttons
`loadAdminAnnualReturns`/`backfillAdminAnnualReturns` ≈ 18303-18305, JS ≈ 9205-9265).

Neues Panel (z.B. `sec-acprices`, Nav-Button daneben), zwei Aktionen:
1. **Status laden:** `GET /admin/system/asset-class-prices/status`
   → `{ coverage: { "<Asset-Klasse>": {first, last, points} }, complete: bool }`.
   Anzeigen: pro Klasse erste/letzte Bar + Punktzahl; Badge "vollständig" wenn
   `complete`. Asset-Klassen-Keys sind deutsch: Aktien, Obligationen, Immobilien,
   Alternative, Liquiditaet.
2. **Aus Marktdaten füllen:** `POST /admin/system/asset-class-prices/backfill`
   (optional Query `from_year`, `to_year`, `overwrite`; Defaults: aktuelles Jahr-20
   bis aktuelles Jahr, overwrite=true). Response:
   `{ summary: {rows_written, rows_skipped, error_count}, coverage:{…}, errors:[…] }`.
   Nach Erfolg Status neu laden. Achtung: Backfill ist netz-/laufzeitintensiv
   (≈25k Rows über 20 J.) — Button disablen + Spinner, danach Status refreshen.

### C) UI-Guardrails (Handoff 2026-05-16 beachten)
- Bestehende Admin-Klassen nutzen: `admin-section-title`, `admin-section-sub`,
  `admin-primary-btn` etc. Kein neues Navy-Gold/Inline-CSS.
- Backtest-Modal-Kopf bleibt schlank; der Toggle gehört ins Zeitraum-Panel (ist schon dort).

### D) Verifikation
- `node`-Inline-JS-Parse muss 0 Fehler ergeben (INLINE_JS_OK).
- Optionaler Static-Contract-Test analog `test_frontend_admin_market_data_panel.py`
  für das neue Panel.
- Manuell: Daily-Backfill drücken → Status zeigt 5 Klassen; im Mandate Backtest-Modal
  auf "Täglich" → glattere Kurve + Intra-Jahr-Drawdown; ohne Daten → Fallback-Badge.

Backend-Verträge sind stabil; bitte nichts am Backend ändern (resolution-Param +
Endpoints stehen). Bei Fragen: Spec `docs/planning/2026-05-22-sprint-u-p19-daily-backtest.md`.


## Codex-Update 2026-05-18: Asset-Allocation-Methodik-Audit

Claude: Das ist ein fachlich kritischer Bereich. Bitte ab jetzt keine UI-Praeferenz, keinen Risiko-Override und keine Allocation-Kennzahl anfassen, ohne den End-to-End-Vertrag Frontend -> Backend -> Persistenz -> Reload -> Report mitzudenken.

Codex hat im Asset-Allocation-Prozess folgende harte Punkte korrigiert:
- `build_target_payload_from_allocation(..., preferences=None)` nutzt nun die bei der Zielallokation gespeicherte `preferences_json`. Vorher konnte ein Reload die Sub-Allokation mit Default-Praeferenzen rekonstruieren; dadurch wirkten z.B. Schwellenlaender-Praeferenzen nachtraeglich verloren.
- `expected_volatility_bps` wird jetzt als Portfolio-Volatilitaet via `sqrt(w' Sigma w)` berechnet, nicht mehr als lineare gewichtete Volatilitaetssumme. Monte-Carlo und Headline-Risiko sind damit methodisch konsistenter.
- Produktrestriktionen sind haerter: `funds_only`, `listed_only`, `chf_only`, `hedgingRequired`, strukturierte Produkte, Leverage und Konzentrationslimiten werden nicht mehr nur kosmetisch gescored.
- Praeferenzfelder duerfen nicht still verpuffen: nicht umsetzbare oder leere Segmentwahlen bei Aktien, Obligationen, Immobilien und Alternativen Anlagen brechen nun mit klarer Fehlermeldung ab.
- `bondsInvestmentGrade` wirkt jetzt auf die Sub-Allokation. Wenn IG, HY und EM alle ausgeschlossen sind, stoppt die Engine.

Methodik-Vertrag, den du beachten musst:
- Top-Level-Quoten entstehen aus Risikoprofil/House-Matrix, Zielen, Reserve, bestehenden Gesamtvermoegens-Exposures, manuellen Bandbreiten und Risikobudget.
- Anlagepraeferenzen steuern primar die Sub-Allokation und die Produktselektion innerhalb der Top-Level-Quote. Sie duerfen nur Top-Level-Quoten aendern, wenn das explizit als Band-/Target-Override modelliert ist.
- Reload-Pfade muessen reproduzierbar sein: gespeicherte Allocation darf nicht mit aktuellen lokalen UI-Defaults neu interpretiert werden.
- Sichtbare Controls muessen eine Engine-Wirkung haben oder hart blockieren. Kein "sieht klickbar aus, macht aber nichts".
- Risikobudget ist subanlagenbasiert: BuildingBlock-Risky-Fractions sind massgeblich, nicht nur grobe Asset-Class-Labels.

Offene fachliche Entscheidung:
- `OPTIMIZER_MODE` ist weiterhin `house_matrix`. Der stochastische Solver kann shadow/aktiv laufen, ist aber nicht Standard. Das ist eine bewusste Produktentscheidung und darf nicht beilaufig geaendert werden.

Verifikation:
- `python -m pytest -p no:cacheprovider tests\test_portfolio_engine_regressions.py tests\test_audit_z4_weighted_metrics.py tests\test_audit_z3_split_normalize.py tests\test_runtime_contracts.py::test_current_payload_rebuild_uses_stored_allocation_preferences -q`
- `python -m pytest -p no:cacheprovider tests\test_risk_override_endpoint.py tests\test_runtime_contracts.py::test_current_payload_rebuild_uses_stored_allocation_preferences -q`
- Frontend-Script-Parse OK, `git diff --check` OK.

## Codex-Update 2026-05-18: Anlagepraeferenzen / Schwellenlaender

Claude: Beim Review der Anlagepraeferenzen war ein echter Contract-Bug drin:
- Frontend sendet fuer Aktien-Fokus teilweise `Schwellenländer` mit Umlaut.
- Backend verglich in `_build_sub_allocations()` nur gegen `Schwellenlaender`.
- Folge: Auswahl sah aktiv aus, die Engine fiel aber still auf Schweiz-Fokus zurueck; EM blieb damit z.B. bei 5% des Aktienbuckets statt 25%.

Fix:
- Backend normalisiert Preference-Choices via `_norm_text()` vor dem Vergleich.
- Tests sichern ab, dass `Schwellenländer` und `Schwellenlaender` denselben EM-Fokus ergeben.
- Widerspruch `Kein EM-Exposure` + `Schwellenlaender-Fokus` oder `Obligationen Emerging` wird jetzt als Fehler blockiert und nicht mehr still glattgebuegelt.

Wichtig fuer kuenftige UI-/Engine-Aenderungen:
- Anlagepraeferenzen fuer Aktien/Obligationen/Immobilien wirken aktuell als Sub-Allokationssteuerung innerhalb des bestehenden Asset-Class-Buckets.
- Sie erhoehen nicht automatisch die Top-Level-Quote `Aktien`, `Obligationen` usw.; diese kommt aus Risikoprofil, House-Matrix, Zielen, Reserve, Bandbreiten und Risikobudget.
- Wenn eine sichtbare Kunden-/Beraterzahl reagieren soll, muss entweder die Sub-Allokation sichtbar gemacht werden oder fachlich bewusst ein Target-/Band-Override gesetzt werden. Nicht still Controls anzeigen, die keine Engine-Wirkung haben.

## UI-Guardrail ab 2026-05-16

Claude: Der Admin-P17/Datenpipeline-Block hat den alten Navy-Gold/Inline-Card-Stil wieder in die App gebracht. Das war ein klarer Rueckfall gegen die aktuelle UI-Richtung und darf nicht wieder passieren.

Ab jetzt gilt fuer alle sichtbaren Frontend-Aenderungen:
- Cashflow und Asset Allocation sind der Referenzstil: ruhig, schlicht, helle Flaechen, wenig Gold, keine dekorativen Mini-Karten.
- Asset-Allocation-Kopfzeile bleibt bewusst schlank: sichtbar nur `Anlagepraeferenzen`, `Anlagestrategie berechnen`, `PDF` und bei verfuegbarer Strategie `Portfolio umsetzen`. Interne Bedienelemente wie Parameter, Mandat-Einstellungen und Soll-Quoten gehoeren hinter den kleinen Optionspunkt und nicht mehr als dominante Header-Buttons in die Kundenmaske.
- Keine neuen `style="color:var(--g3)"`, `style="color:var(--g4)"`, schweren Navy-Gold-Header oder isolierten Inline-Statuskarten in neuen UI-Bloecken.
- Neue Admin-Bereiche muessen die vorhandenen Klassen nutzen: `admin-section-title`, `admin-section-sub`, `admin-summary-panel`, `admin-metric-panel`, `admin-metric-label`, `admin-metric-value`, `admin-metric-meta`, `admin-code-input`.
- Wenn ein neuer Bereich eigene Struktur braucht, zuerst eine kleine wiederverwendbare Klasse im Admin-Komponentenlayer anlegen, nicht Inline-CSS kopieren.
- Vor Abgabe per Suche pruefen:
  - `font-size:13px;font-weight:600;color:var(--g3)`
  - `color:var(--g4)`
  - `font-family:Consolas,monospace`
  - `background:var(--bg2);border-radius:6px;padding`
Neue Treffer in Admin/Frontend sind nur mit begruendetem Ausnahmefall ok.

## Dokument-/Vorlagen-Guardrail ab 2026-05-16

Claude: Vorlagen-PDFs duerfen nur als Struktur-, Text- und Designreferenz dienen. Kundennamen, Kontaktangaben, Marken oder andere personenbezogene Beispielangaben aus einer Vorlage niemals uebernehmen, hardcoden oder in generische Reports schreiben.

Fuer die Anlagestrategie gilt:
- Branding aus Vorlagen wie Referenzanbieter/Banken/Beispielberater nie kopieren. Fuer diesen Report ist `Emanuele Konzelmann` der Absender/Brand.
- Das Report-Template darf keine Namen hardcoden. Im echten kundenspezifischen Export darf der aktive Kunde aus der App (`currentPersona`/API-Daten) in Titel, Kopfzeile, Signatur und Kundendaten erscheinen.
- Namen aus einer PDF-Vorlage bleiben verboten. Beispielkundennamen duerfen weder als Fallback noch als Demo-Default verwendet werden.

Aktueller Standard fuer neue Arbeitsbloecke:
- Spezifikationen liegen jetzt in [docs/planning](C:/5eyes/5eyes_stage9_release_ready/docs/planning)
- neue Claude-Specs bitte aus [CLAUDE_SPEC_TEMPLATE.md](C:/5eyes/5eyes_stage9_release_ready/docs/planning/CLAUDE_SPEC_TEMPLATE.md) ableiten
- Codex startet Umsetzungsbranches ueber [start_codex_branch.ps1](C:/5eyes/5eyes_stage9_release_ready/scripts/start_codex_branch.ps1)
- Review bitte gegen [REVIEW_CHECKLIST.md](C:/5eyes/5eyes_stage9_release_ready/docs/planning/REVIEW_CHECKLIST.md) ausrichten

## Bereits umgesetzt

### Backend
- Preis-Service mit `price_history`
- APScheduler-Start im FastAPI-Prozess
- Admin-Endpunkte:
  - `POST /admin/prices/refresh`
  - `GET /admin/prices/status`
  - `GET /admin/prices/mapping-gaps`
- Health-Endpunkte:
  - `GET /health`
  - `GET /health/ready`
  - `GET /health/db`
- robusteres DB-Bootstrapping über `sqlite3.executescript()`
- zentrales DB-Modul, das per `DB_USE_SQLCIPHER=true` automatisch SQLCipher aktiviert
- `.env`-Suche für Dev und packaged Backend
- Logging-Bootstrap und `.env.example`
- `setup.py` für First-Run Admin-User
- `migrate_to_sqlcipher.py` für bestehende Klartext-DBs

### Electron
- Backend-Prozessstart
- Readiness-Wait auf `/health/ready`
- `contextBridge` mit Backend-Base-URL
- Navigation-Hardening
- Single-instance lock
- `frontend/desktop-api.js` als Helfer für API-Calls
- `npm start` / `npm run dist:win`
- Packaging-Script mit optionalem `BUILD_WITH_SQLCIPHER=1`

## Was Claude jetzt am meisten reviewen / ergänzen soll

### Codex-Update 2026-05-19: PDF-Prozess

Claude: Bitte bei allen Report-/PDF-Aenderungen diese Punkte hart beachten:
- Server-PDFs duerfen keine alten Modellfelder lesen. `TargetAllocation` nutzt `target_*_bps`, `band_*_min_bps`/`band_*_max_bps` und `advisory_wealth_at_generation_rappen`.
- `RecommendationPosition` enthaelt keine IST-Felder. Portfolio-IST kommt aus `RecommendationHolding.market_value_rappen`; fehlen Holdings, darf keine falsche Drift simuliert werden.
- Risikoprofil-PDF nutzt `final_profile`, `risk_capacity_score_x10`, `risk_willingness_score_x10`, `investment_horizon_years` und die Knowledge-JSONs.
- Es gibt jetzt einen echten Server-Endpunkt `GET /mandates/{mandate_id}/reports/protokoll.pdf`. Browserdruck ist nur Fallback fuer Demo/Legacy.
- PDF-Branding kommt aus dem Berater-/Organisationsprofil, nicht aus Referenzvorlagen und nicht aus hardcodierten Beispielmarken.
- Die Anlagestrategie hat wieder eine harte 19-Seiten-Struktur in Vorlagen-Reihenfolge: Strategieblock Seite 1-9, Ausgangslage Seite 10-15, Kennzahlen/Fonds/Disclaimer Seite 16-19.
- Tests muessen Struktur/Quelle pruefen, nicht nur `%PDF`-Magic-Bytes.
- Codex-Fix 2026-05-20: Bitte nicht wieder die alte PDF-Struktur einfuehren. Inhaltsseiten haben eigene Header-Titel; "Anlagestrategie" darf nicht als generischer Dauertitel auf jeder Seite stehen.
- Codex-Fix 2026-05-20: Vermoegensstruktur muss von gross nach klein laufen: zuerst High-Level Asset Allocation / Soll-Allokation, danach Subanlageklassen mit IST/SOLL-Visualisierung.
- Codex-Fix 2026-05-20: Eignungspruefung muss den Risikofragebogen 1:1 als Frage-Antwort-Dokumentation zeigen. Fragen 1-11 immer rendern, fehlende Antworten sichtbar als "Nicht beantwortet"; Frage und Antwort muessen in jeder Zeile vorhanden sein.
- Codex-Fix 2026-05-20: Punkte/Scorewerte des Risikoprofils sind intern und duerfen im Kunden-PDF nicht ausgewiesen werden. Frage/Antwort ja, Punkte nein.
- Codex-Fix 2026-05-20: Wenn das Risikoprofil manuell uebersteuert wurde, muss der Kundenbericht dies sichtbar erwaehnen und die dokumentierte Begruendung anzeigen.
- Codex-Fix 2026-05-20: Band Min-Max / Toleranzbaender nur anzeigen, wenn der Kunde explizit von Standardbandbreiten abweicht bzw. `allocation_preferences.bands` echte Overrides enthaelt.
- Codex-Fix 2026-05-20: Asset-Allocation-Maske exportiert nur `assetallocation.pdf`; Portfolio-Maske exportiert nur `portfolio.pdf`; das volle 19-Seiten-Gesamtdokument bleibt im Review/Abschluss via `anlagestrategie.pdf`.
- Codex-Fix 2026-05-21: Einzel-PDFs bleiben nach Titelblatt und Haftungs-Disclaimer strikt rubrikrein. Asset Allocation zeigt inhaltlich nur Kuchen/Soll-Allokation plus Subanlageklassen. Portfolio zeigt inhaltlich nur Portfolio-Positionen. Keine Risikoprofil-, Vermoegens-, Review-, Signatur- oder Zusatzsektionen in diesen Einzel-PDFs.
- Codex-Fix 2026-05-21: Portfolio-Einzel-PDF gruppiert Produktpositionen wie das Frontend-HUD nach Assetklasse (`Aktien:`, `Obligationen:` usw.) und listet darunter ausschliesslich Produkte mit Subklasse, Sollgewicht, Zielwert, Waehrung und TER. Die PDF-Datenquelle muss dafuer `asset_class` aus dem Produktuniversum mitgeben; bitte nicht wieder auf eine flache Produktliste ohne Gruppentitel zurueckbauen.
- Codex-Fix 2026-05-21: Portfolio-Empfehlungen duerfen nicht mehr gegen eine neuere Asset Allocation angezeigt oder gedruckt werden. `recommendations/current/payload` und `portfolio.pdf` muessen eine RecommendationRun verwenden, deren `target_allocation_id` zur aktuell gueltigen `TargetAllocation` passt. Stale Runs muessen blockiert bzw. im Frontend aus dem State geloescht werden; sonst entstehen fachlich falsche Faelle wie Liquiditaet 3% in der SAA, aber Geldmarktfonds 22.2% im Portfolio.
- Codex-Fix 2026-05-20: PDF-Download im Frontend nutzt Timeout, Base-URL-Refresh und klare Backend-Fehlermeldung. Neue PDF-Dokumentmodule muessen im Windows-/PyInstaller-Build explizit enthalten bleiben (`services.pdf` collect-submodules + Dokument-Hidden-Imports).

### Codex-Update 2026-05-18: Review & Abschluss

Claude: Die finale Kundenansicht bleibt eine einzige Seite `Review & Abschluss`. Bitte keine separate sichtbare `Zusammenfassung` wieder einfuehren.

Aktuelle UI-Regeln fuer diesen Bereich:
- Minimalistisch wie Cashflow / Asset Allocation: helle Flaechen, 1px Borders, keine schweren Navy-Kacheln.
- Dokumente erscheinen als schlanke Aktionsliste, nicht als vier dominante Card-Kacheln.
- Entscheid/Empfehlung und Governance/Dokumente sind in ruhigen Grid-Gruppen gebuendelt, nicht als lange vertikale Card-Serie.
- Die vier Ausgabegruppen bleiben fachlich erhalten: Portfolio-/Umsetzungsplan, Anlagestrategie / Vertrag, Beratungsprotokoll, Weitere Dokumente.
- Risikoprofil-KPI nicht mehr als dunkle Sonderkachel stylen.
- Trigger/Wiedervorlagen sind interne Beratungslogik. In der Kunden-/Point-of-Sales-Ansicht keine Trigger-Sektion, keinen Trigger-CTA und keinen Trigger-Counter anzeigen.
- Alte `sr`-Routen duerfen nur Legacy-Alias auf `rv` sein; keine eigene Top-Navigation und keine sichtbare zweite Seite.

1. **Frontend-API-Wiring final prüfen**
   - Login / Token-Flows auf Race Conditions prüfen
   - Offline-Fallback sauber nur dann nutzen, wenn Backend wirklich nicht erreichbar ist
   - Fehlerzustände im UI explizit anzeigen

2. **SQLCipher-Review**
   - Prüfen, ob das zentrale Umschalten via `database.py` für seine Branch am saubersten ist
   - Validieren, ob noch irgendwo direkte Klartext-Annahmen im Code existieren

3. **Offline-Fähigkeit finalisieren**
   - `vendor_assets.py` einmal wirklich laufen lassen
   - prüfen, ob danach keinerlei CDN-Abhängigkeit mehr im HTML verbleibt

4. **Packaging-Review**
   - prüfen, ob zusätzliche PyInstaller hidden imports nötig sind
   - später App-Icon, Signierung und finalen Installer-Feinschliff ergänzen

## Review-Fragen an Claude

- Siehst du noch CORS-, Session- oder Token-Fallen bei `file://` / `Origin: null`?
- Möchtest du vor dem finalen Build einen separaten `ticker_symbol` / Override-Mechanismus im Produktuniversum ergänzen?
- Sollen wir noch einen kleinen lokalen Admin-Guard für `POST /admin/prices/refresh` ergänzen?
