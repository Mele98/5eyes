# Price updater integration

This backend extension adds daily market-data refresh support for active products and prepares the backend for the next hardening steps.

## Included changes

- `price_updater.py`
  - fetches the latest daily close via Yahoo Finance (`yfinance`)
  - prefers `products.symbol`, falls back to `products.isin`
  - writes data into `price_history`
  - retries failed market-data fetches
  - keeps per-run runtime status in memory
  - exposes mapping gaps for products that still miss a ticker symbol
- `routers/prices.py`
  - `GET /admin/prices/status`
  - `GET /admin/prices/mapping-gaps`
  - `POST /admin/prices/refresh`
- `routers/health.py`
  - `GET /health`
  - `GET /health/ready`
  - `GET /health/db`
- `routers/system.py`
  - `GET /admin/system/backups`
  - `GET /admin/system/logs/recent`
  - `POST /admin/system/db/backup`
  - `POST /admin/system/db/optimize`
  - `GET /admin/system/db/integrity`
- `main.py`
  - adds logging bootstrap
  - starts APScheduler at app startup
  - shuts it down cleanly on app stop
  - enables Electron-safe CORS for `Origin: null`
- `database.py`
  - introduces a stronger engine factory with a future `db_key` hook for SQLCipher
  - replaces naive SQL splitting with `sqlite3.executescript()` during schema bootstrap
  - attaches SQLite PRAGMAs to every created engine
- `config.py`
  - adds environment and scheduler settings
  - blocks default JWT secret outside development/test
- `tests/test_price_updater.py`
  - covers insert/update/unchanged flows
  - covers manual admin refresh endpoint
  - covers runtime status and mapping-gap endpoints

## Scheduler behavior

- runs at `06:00 Europe/Zurich` by default
- runs only while the app / FastAPI process is open
- no OS-level Task Scheduler integration is included

## Important operational note

Yahoo Finance is ticker-centric. In practice you should maintain `products.symbol` for every active product. Pure ISIN-only rows may fail, depending on whether Yahoo can resolve them. Use `GET /admin/prices/mapping-gaps` to identify weak spots before going live.

## Extra hardening included

- rotating backend log files
- request IDs and security headers on every response
- in-memory login throttling / temporary lockout after repeated failed logins
- backup manifests with SHA256 for basic restore verification
- `smoke_test.py` for quick post-setup validation
