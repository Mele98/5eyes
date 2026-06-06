# Daily Market Data Refresh

Konfiguration und Lifecycle des taeglichen Marktdaten-Refresh-Cron.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #31 (DATA, ~4h)
**Status:** Implementiert via APScheduler in `price_updater.py`,
opt-in via Settings.

---

## Was wird taeglich aktualisiert?

Der Daily-Cron (`run_daily_market_data_refresh` in
`services/market_data_daily_refresh.py`) refresht **3 Datentypen**
in einer Transaktion:

| Datentyp | Quelle | Tabelle |
|----------|--------|---------|
| Produkt-Preise (aktiv gehaltene Positionen) | yfinance + Fallback-Cascade | `prices_history` |
| Asset-Class-Proxy-Preise | yfinance via factory.build_default_aggregator | `asset_class_price_history` |
| FX-Reihen Fremdwaehrung -> CHF | yfinance "CHF=X"-Symbole | `asset_class_fx_history` |

Plus seit U-99 (2026-06-05): **FX-only-Refresh** als separater
Admin-Trigger via `POST /admin/system/fx-rates/refresh-now`.

## Lifecycle

```
APScheduler BackgroundScheduler (price_updater.py)
        │
        ├── daily_price_refresh         (06:00 Europe/Zurich)
        ├── daily_market_data_refresh   (06:00 Europe/Zurich)
        ├── daily_cache_purge           (configurable hour)
        └── weekly_market_data_validation (configurable day_of_week)
```

Alle Jobs sind `coalesce=true` + `max_instances=1` — verpasste Runs
werden gebuendelt, parallele Runs verhindert.

## Settings

`5eyes-backend/config.py` (Defaults):

```python
market_data_daily_refresh_enabled: bool = True
market_data_daily_refresh_hour: int = 6
market_data_daily_refresh_minute: int = 0
market_data_daily_refresh_max_symbols: int = 500
```

Override via Environment-Variablen:

```
MARKET_DATA_DAILY_REFRESH_ENABLED=false  # global aus
MARKET_DATA_DAILY_REFRESH_HOUR=4         # 04:00 statt 06:00
MARKET_DATA_DAILY_REFRESH_MAX_SYMBOLS=100  # Limit reduzieren
```

## Admin-Recovery-Trigger

Wenn der Daily-Cron faellt oder Berater manuelles Refresh anstossen
will:

```
POST /admin/system/market-data/refresh-now
```

Audit-Log-Eintrag mit `action=MARKET_DATA_REFRESH` (U-102).

Fuer **nur FX-Refresh** ohne vollen Sweep:

```
POST /admin/system/fx-rates/refresh-now
```

(U-99, schneller, weniger API-Calls.)

## Health-Diagnose

- **Admin-Modal -> Datenpipeline-Status:** Live-Status pro Provider
- **`GET /admin/system/market-data/provider-health`:** Failure/Recovery-Events
- **`GET /admin/system/market-data/purge-history`:** Cache-Purge-Lauf-Log

## Fehler-Modi

| Symptom | Ursache | Recovery |
|---------|---------|----------|
| `provider-health` zeigt rote Events | yfinance rate-limited | Auf Stooq-Fallback warten oder AlphaVantage-Key setzen |
| FX-Reihen stagnieren | `CHF=X`-Symbol unverfuegbar | Manueller FX-Refresh-Trigger U-99 |
| Daily-Cron startet nicht | APScheduler nicht installiert | `pip install apscheduler` |
| `max_symbols` zu klein | viele aktive Positionen | Setting auf 1000 erhoehen |

## Cost-Disziplin

CHF 0/Jahr Hard-Constraint (ADR-005). Nur Gratis-Provider:
- **yfinance** (Primary, TOS-Grauzone fuer Einzel-Berater)
- **Stooq** (Backup, kein Rate-Limit)
- **AlphaVantage** (Backup #2, 500 Calls/Tag gratis)

Bei Skalierung jenseits Einzel-Berater siehe `MARKET_DATA_PROVIDER_STRATEGY.md`.

## Bewusst NICHT in Scope (U-31)

- Echtzeit-Streaming-Refresh (ADR-003: kein Markt-Timing)
- Intraday-Updates (heute nur EOD)
- Auto-Notification bei Provider-Ausfall (Folge-Sprint mit Telemetry
  U-64)
- Cross-Provider Median-Validation als Daily-Cron (wir haben
  weekly-validation)

## Weiterfuehrendes

- [data_pipeline_README.md](data_pipeline_README.md) — Master-Index
- [DATA_PIPELINE_STATUS.md](DATA_PIPELINE_STATUS.md) — Phasen-Status
- [MARKET_DATA_PROVIDER_STRATEGY.md](MARKET_DATA_PROVIDER_STRATEGY.md)
- `5eyes-backend/README_price_updater.md` — Scheduler-Setup
- ADR-005 — CHF-0-Hard-Constraint
