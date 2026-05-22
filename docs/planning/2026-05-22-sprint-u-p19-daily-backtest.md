# Claude Spec — U-P19: Daily-Resolution Strategie-Backtest

## Meta

- Titel: Strategie-Backtest auf täglicher Auflösung (price_history pro Asset-Klasse)
- Datum: 2026-05-22
- Owner: Emanuele Konzelmann
- Issue / Link: Folgesprint zu U-P17 (Annual-MVP) + U-P11a (Annual-Backfill)
- Branch-Vorschlag: `codex/sprint-u-p19-daily-backtest`

## Ziel

Der Strategie-Backtest (`services/backtest_strategy.py`) rechnet heute ausschließlich
auf **jährlichen** Asset-Klassen-Renditen aus `asset_class_annual_returns`. Diese Spec
hebt ihn auf **tägliche (EOD-)Auflösung**: pro Asset-Klasse wird eine persistierte
tägliche Index-/Preisserie geführt, daraus werden tägliche Bucket-Renditen abgeleitet,
und der Wealth-/Drawdown-Pfad wird täglich aufgezinst. Rebalancing bleibt fachlich
**jährlich** (entkoppelt von der Compounding-Frequenz). Ergebnis: glattere Wealth-Kurve,
realistischer Intra-Jahr-Max-Drawdown, korrekt annualisierte Volatilität/Sharpe.

Annual bleibt als Modus erhalten und ist Fallback, wenn keine täglichen Daten gepflegt sind.

## Problem

- Die Labels in Frontend (`m-bt`-Modal) und Service-`note` versprechen seit U-P17
  "Daily-Auflösung kommt mit U-P11". U-P11a hat nur den **Annual**-Backfill geliefert;
  die Daily-Auflösung im Backtest fehlt weiterhin. Das Versprechen ist offen.
- Jahres-Granularität unterschätzt den Max-Drawdown systematisch (Intra-Jahr-Tiefs wie
  März 2020 oder Q4 2008 sind unsichtbar) und liefert eine eckige, asset-manager-untypische
  Wealth-Kurve.
- Volatilität wird heute aus nur ~10–20 Jahres-Returns geschätzt (hohe Schätzunsicherheit,
  keine echte Annualisierung).

## Scope

- Neues persistiertes Datenmodell `asset_class_price_history` (tägliche EOD-Serie je
  Asset-Klasse), analog zu `asset_class_annual_returns`.
- Neuer Admin-Backfill `services/market_data/asset_class_price_backfill.py`, der via
  bestehendem `MarketDataAggregator` + `DEFAULT_SYMBOL_MAP` (URTH/AGG/VNQ/GLD/BIL,
  bzw. Override) tägliche Bars über ein Fenster zieht und persistiert. Idempotent
  (overwrite-Flag) wie der Annual-Backfill.
- Admin-Endpoint `POST /admin/system/asset-class-prices/backfill` + `GET .../status`
  (Jahre/Punkte-Abdeckung je Asset-Klasse), analog zu `annual-returns/backfill`.
- `backtest_strategy.py`: `resolution: "annual" | "daily"` Parameter. Bei `daily`:
  Daily-Serie laden, tägliche Bucket-Renditen bilden, Pfad täglich aufzinsen,
  Rebalancing nur am Jahreswechsel (konfigurierbar: `none|annual`).
- Metriken für Daily korrekt annualisieren: Vol × √252, CAGR aus echtem Datums-Span
  (`days/365.25`), Max-Drawdown über den täglichen Pfad, Best/Worst-**Jahr** und
  Win-Rate weiterhin auf **Jahres**-Aggregation (Asset-Manager-Konvention).
- Endpoint `GET /mandates/{id}/backtest/strategy` um `&resolution=daily` erweitern;
  Default bleibt `annual`. Fehlende Daily-Daten → automatischer Fallback auf annual
  mit klarer `warning`.
- **Benchmark ist First-Class, auch im Daily-Modus** (NICHT nur Edge-Case): Der
  bestehende Benchmark-Vergleich (alleine vs. vergleichend via Checkbox; eigene
  5-Asset-Allokation; Standard-Presets `100% Aktien` / `60/40` / `70/30`) muss im
  Daily-Modus **bit-gleich verfügbar** sein. Der Benchmark-Pfad durchläuft dieselbe
  tägliche Compounding-/Rebalance-/Annualisierungs-Logik wie der SOLL-Pfad
  (`_build_path_views` für Benchmark mit denselben `years_data`/Daily-Series-Daten).
- Frontend `m-bt`-Modal: Auflösungs-Umschalter (Jährlich / Täglich); stale
  "Annual MVP / Daily kommt mit U-P11"-Labels ersetzen.
- Backtest-PDF: Wealth-/Drawdown-Chart muss viele Punkte verkraften (Downsampling
  für das Rendering, Metriken unverändert).

## Nicht-Scope

- Stress-Backtest (`backtest_stress.py`) bleibt unverändert (eigener Sprint).
- A/B-HouseMatrix-Backtest (`backtest_ab.py`) bleibt unverändert.
- Keine Sub-Asset-Class-Auflösung (Backtest bleibt auf den 5 Top-Level-Buckets).
- Kein FX/Multi-Currency-Umbau des Backtests (läuft weiter in `base_currency`-Logik
  des bestehenden Pfads; Proxy-Returns sind TR in Proxy-Währung — als Approximation
  dokumentieren, nicht in dieser Spec lösen).
- Keine Cashflows/Spar-/Bezugspläne (wie U-P17).

## Fachlogik

- Quelle: U-P17 `backtest_strategy.py` (Methodik), U-P11a `annual_returns_backfill.py`
  (Aggregator + Proxy-Symbol-Map), `[[project_5eyes_data_pipeline]]`.
- Verbindliche Regeln:
  - Compounding-Frequenz (täglich) ist **entkoppelt** von der Rebalancing-Frequenz
    (jährlich, am ersten Handelstag des Folgejahres zurück auf Soll-Gewichte).
  - Tägliche Bucket-Rendite = `adjusted_close_t / adjusted_close_{t-1} - 1`
    (Total Return inkl. Dividenden, wenn `adjusted_close` vorhanden, sonst `close`).
  - Nur Handelstage, an denen **alle 5 Asset-Klassen** eine Bar haben, gehen in den
    Pfad (Kalender-Schnittmenge; analog zur "vollständige-Jahre"-Regel im Annual-Modus).
  - Initial-Wert: `advisory_wealth_at_generation_rappen` aus aktiver TargetAllocation,
    Fallback Beratungsvermögen-Summe, Fallback CHF 100'000 (wie U-P17).
  - Annualisierung: Vol_annual = Vol_daily × √252; CAGR = (end/start)^(365.25/Δdays) − 1;
    Sharpe = (CAGR − risk_free) / Vol_annual.
- Inferenz: Best/Worst-Jahr + Win-Rate aggregieren tägliche Pfadwerte auf Jahresende
  (Jahres-Return = Year-End_y / Year-End_{y-1} − 1).
- Owner-Decisions:
  - `OWNER-DECISION`: Default-Rebalancing im Daily-Modus = **jährlich** (Alternative
    quartalsweise erst, wenn nachgefragt).
  - `OWNER-DECISION`: `risk_free_bps` bleibt vorerst konservativ fix (80 bps);
    CMA-Anbindung ist separater Politur-Sprint, nicht hier.

## Betroffene Module / Dateien

- Backend:
  - `services/backtest_strategy.py` (resolution-Param, Daily-Loader, generalisiertes
    Compounding mit Rebalance-Trigger, Daily-Metriken)
  - `services/market_data/asset_class_price_backfill.py` (**neu**)
  - `routers/system.py` (Backfill-/Status-Endpoints für asset-class-prices)
  - `routers/allocation.py` (`resolution`-Query-Param im strategy-Endpoint durchreichen)
  - `services/pdf/components/wealth_chart.py` + `drawdown_chart.py` (Downsampling)
- Frontend:
  - `5eyes-electron/frontend/5eyes_v2.html` (`m-bt`-Modal: Resolution-Toggle,
    Label-Cleanup, `&resolution=` an `btRunBacktest`/`downloadBacktestPdf`)
- Datenmodell:
  - `models/snapshots.py` → `AssetClassPriceHistory` (**neu**)
  - `database.py` → `ensure_runtime_columns()`/Tabellen-Bootstrap für die neue Tabelle
- Tests:
  - `tests/test_backtest_strategy.py` (Daily-Pfad, Annual-Äquivalenz, Annualisierung,
    Fallback, Rebalance-Trigger)
  - `tests/test_asset_class_price_backfill.py` (**neu**, gemockter Aggregator)
  - `tests/test_backtest_pdf.py` (Daily-Resolution rendert, Downsampling)

## API / Schnittstellen

- neue Endpunkte:
  - `POST /admin/system/asset-class-prices/backfill` (Body: optional `symbol_map`,
    `from_year`, `to_year`, `overwrite`) — Admin-only.
  - `GET /admin/system/asset-class-prices/status` (Abdeckung je Asset-Klasse:
    erste/letzte Bar, Punktzahl).
- angepasste Endpunkte:
  - `GET /mandates/{mandate_id}/backtest/strategy?resolution=annual|daily`
    (Default `annual`). Response unverändert in Struktur; zusätzlich
    `resolution_used` + ggf. Fallback-`warning`.
- Request / Response Änderungen:
  - Response-Objekt erhält `resolution_used: "annual"|"daily"` und `note` wird
    daily-tauglich formuliert (kein "kommt mit U-P11" mehr).

## UI / UX

- neue Buttons: Resolution-Toggle (Segmented "Jährlich | Täglich") im `m-bt`-Modal-Kopf.
- neue States: bei `daily` ohne Daten → Hinweis-Badge "Tägliche Daten fehlen — auf
  Jährlich zurückgefallen" + automatischer Annual-Render.
- Fehlerverhalten: Backend-Fehler/Timeout wie bestehend (Status-Zeile, klare Meldung).
- Demo-/Offline-Verhalten: Backtest liest **nur** aus DB (`asset_class_price_history`),
  nie live aus dem Netz. Ohne gepflegte Daily-Daten bleibt Annual der Default — App
  funktioniert offline unverändert.

## Akzeptanzkriterien

1. `resolution=daily` liefert einen täglichen Wealth-Pfad, dessen Max-Drawdown ≥ dem
   Annual-Max-Drawdown desselben Zeitraums ist (Intra-Jahr-Tiefs werden sichtbar).
2. Eine Daily-Serie, die innerhalb jedes Jahres flach ist und nur am Jahresende den
   Annual-Return realisiert, reproduziert das Annual-Ergebnis (CAGR/Endwert) innerhalb
   Rundungstoleranz (≤ 1 bps).
3. Volatilität im Daily-Modus ist mit √252 annualisiert (Test gegen synthetische Serie).
4. Fehlende/unvollständige Daily-Daten → Endpoint fällt auf annual zurück, setzt
   `resolution_used="annual"` + Warning, kein 500.
5. Rebalancing greift nur am Jahreswechsel; No-Rebalance-Variante driftet täglich.
6. Backfill ist idempotent (zweiter Lauf mit `overwrite=False` ändert nichts).
7. Backtest-PDF rendert im Daily-Modus ohne Layout-Bruch (Downsampling aktiv).
8. Alle bestehenden Backtest-Tests bleiben grün; Annual-Default unverändert.
9. Benchmark funktioniert im Daily-Modus vollständig: SOLL allein (ohne Benchmark),
   SOLL + eigene Benchmark-Allokation, SOLL + Preset (100% Aktien / 60/40 / 70/30) —
   jeweils mit korrekten Daily-Metriken für beide Pfade. PDF zeigt den Benchmark im
   Daily-Modus genauso wie heute im Annual-Modus.

## Testfälle

- Unit: `compound_wealth_path` mit täglichen Perioden + jährlichem Rebalance-Trigger;
  `compute_metrics` Annualisierung (√252, CAGR aus Datums-Span); Year-End-Aggregation
  für Best/Worst-Jahr; leere/lückenhafte Serie.
- API: `?resolution=daily` happy path; Fallback ohne Daily-Daten; Admin-Backfill
  schreibt erwartete Punktzahl (gemockter Aggregator); Status-Endpoint-Abdeckung.
- GUI/E2E: Toggle Jährlich↔Täglich re-rendert Charts + Metriken; PDF-Download mit
  `&resolution=daily`.
- Edge Cases: nur 1 gemeinsamer Handelstag; Totalverlust-Pfad; Asset-Klasse mit Lücke
  (fällt aus Kalender-Schnittmenge); Benchmark-Mix im Daily-Modus.

## Risiken

- Datenvolumen: ~20 Jahre × 252 Tage × 5 Klassen ≈ 25k Rows — unkritisch für SQLite,
  aber Backfill-Laufzeit (Netz) kann Minuten dauern → als Hintergrund-Admin-Job,
  Status-Endpoint zum Pollen.
- Proxy-Symbol-Returns sind in Proxy-Währung (USD-ETFs) — als methodische Approximation
  dokumentieren; FX-Korrektheit ist explizit Nicht-Scope.
- Performance des Endpoints: täglicher Pfad über 20 Jahre = ~5k Schritte × 5 Buckets;
  rein arithmetisch, unkritisch. PDF-Rendering braucht Downsampling.
- Kalender-Schnittmenge kann bei heterogenen Provider-Kalendern (US vs. CH Feiertage)
  Tage verlieren → akzeptabel, da Proxy-Map einheitlich USD-ETFs nutzt.

## Offene Fragen an Owner

- Soll der Daily-Backfill automatisch beim App-Start / per Scheduler laufen, oder
  bleibt es ein manueller Admin-Knopf wie beim Annual-Backfill? (Vorschlag: manuell.)
- Quartalsweises Rebalancing als zusätzliche Option gewünscht, oder reicht jährlich +
  Buy-and-Hold? (Vorschlag: vorerst nur jährlich + Buy-and-Hold.)
