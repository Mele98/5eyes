# 5eyes Multi-Source-Datenpipeline — Master-Index

**Stand:** 2026-05-14 — P1-P22 fertig, in Merge-Queue.
**Kosten Tier 1:** CHF 0/Jahr.
**Status:** Code, Tests, Doku, CI komplett. Wartet auf User-Merge.

---

## "Ich will X" → "Lies Y"

| Was du tun willst | Dokument |
|---|---|
| Pipeline zum ersten Mal aktivieren | [data_pipeline_activation.md](data_pipeline_activation.md) |
| Pruefen, ob meine `.env` ok ist | `python scripts/check_env_for_pipeline.py` |
| End-to-End-Test laufen lassen | `python scripts/smoketest_market_data.py` |
| Live-Diagnose im Browser sehen | Admin-Modal → Section "Datenpipeline-Status" |
| Live-Diagnose via API | `GET /admin/market-data/status` |
| CMA-Werte quartalsweise importieren | [cma_import_workflow.md](cma_import_workflow.md) |
| Provider-Strategie verstehen | [MARKET_DATA_PROVIDER_STRATEGY.md](MARKET_DATA_PROVIDER_STRATEGY.md) |
| Merge-Reihenfolge der PRs | `docs/status_snapshot_2026-05-14.md` (parallele Branch, PR #39) |
| Untracked-Dateien aufraeumen | `docs/wip_cleanup_2026-05-13.md` (parallele Branch, PR #37) |

---

## Phasen-Uebersicht (P1-P22)

### Provider-Stack (P1-P12)
- **P1** Provider-Adapter-Pattern · ABC, Dataclasses, Exceptions
- **P2** YFinanceProvider · Primary (gratis, TOS-Grauzone fuer Einzel-Berater)
- **P3** StooqProvider · Backup, CSV-basiert, keine Rate-Limits
- **P4** AlphaVantageProvider · Backup #2, 500 Calls/Tag (gratis Key)
- **P5** MarketDataAggregator + HealthState · Fallback-Chain, TTL-Backoff
- **P6** Smart Cache · SQLite, TTL pro `cache_kind` (eod=24h, history=7d, isin=180d)
- **P7** Cross-Validation · Median-Diff, Alert > Threshold, ValidationLog
- **P8** OpenFIGIProvider · ISIN ↔ Yahoo-Ticker
- **P9** Macro-Pipeline · FRED + ECB + SNB (alle gratis)
- **P10** CMA-CSV-Import · Quartals-Workflow fuer BlackRock/JPM/Vanguard
- **P11** ETF-Scraper · Justetf + Swissfunddata (opt-in, TOS-grenzwertig)
- **P12** TwelveDataProvider · Tier-2-Option (~CHF 80/Mo)

### Integration (P13-P15)
- **P13** Legacy-Compat · drop-in fuer `twelvedata_client`
- **P14** `price_updater` Migration · `PRICE_REFRESH_PRIMARY_PROVIDER=aggregator`
- **P15** APScheduler-Hooks · daily Cache-Purge + weekly Cross-Validation

### Diagnose (P16-P17)
- **P16** Admin-Endpoint · `GET /admin/market-data/status`
- **P17** Admin-FE-Panel · 3 Karten + Scheduler-Jobs, 60s-Polling

### Operational-Toolkit (P18-P22)
- **P18** Aktivierungs-Doku · 3 `.env`-Zeilen → Live
- **P19** Smoketest-CLI · live oder `--no-network`, Markdown-Report
- **P20** GitHub Action · weekly + on-PR, Path-Filter, Live-Mode via secrets
- **P21** `.env.example` + Pre-Flight-Check · Exit-Codes 0/1/2
- **P22** Webhook-Notifier · Slack/Discord-kompatibel, opt-in via URL

---

## .env-Cheatsheet

```env
# Minimum (3 Zeilen aktivieren die Pipeline)
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,stooq,alphavantage
ALPHAVANTAGE_API_KEY=<dein-key-vom-gratis-signup>

# Cross-Validation (optional, opt-in)
MARKET_DATA_VALIDATION_ENABLED=true
MARKET_DATA_VALIDATION_SYMBOLS=UBSG.SW,AAPL,MSFT,NESN.SW
MARKET_DATA_VALIDATION_THRESHOLD_BPS=300

# Alert-Webhook (optional, opt-in, Slack/Discord)
MARKET_DATA_ALERT_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
MARKET_DATA_ALERT_WEBHOOK_TIMEOUT_SECONDS=5.0
```

---

## Tier-Modell

| Tier | Provider | Kosten | Best fuer |
|---|---|---|---|
| **1** (heute, default) | yfinance + stooq + alphavantage | CHF 0/Jahr | Einzel-Berater |
| **2** (Skalierung) | twelvedata + yfinance + stooq | ~CHF 960/Jahr | 5+ Firmen |
| **3** (FINIG-Lizenz) | SIX Financial Information | CHF 8'000-10'000/Jahr | regulierter VV |

Wechsel: 1 `.env`-Zeile.

---

## CLI-Tools

```bash
# .env-Validierung vor Live-Switch
python scripts/check_env_for_pipeline.py

# End-to-End-Smoketest (Default: --no-network)
python scripts/smoketest_market_data.py
python scripts/smoketest_market_data.py --no-network
python scripts/smoketest_market_data.py --symbols UBSG.SW,AAPL --report-file out.md

# CMA-CSV-Import (Quartal)
python scripts/import_cma_from_csv.py cma_q2_2026.csv          # dry-run
python scripts/import_cma_from_csv.py cma_q2_2026.csv --apply  # live
```

---

## CI

`.github/workflows/market_data_smoketest.yml`:
- Schedule: Sonntag 04:30 UTC (nach `weekly_validation_job`)
- On PR: wenn `market_data/`, `price_updater.py`, `smoketest_market_data.py` oder `requirements.txt` geaendert
- workflow_dispatch: manueller Trigger mit live=true (nutzt GitHub Secrets)
- Artifact: `smoketest_report.md` (30 Tage Retention)

---

## Architektur in einem Bild

```
User-Request: refresh_all_prices()
  ↓
price_updater._fetch_primary_symbol_points()
  ↓
(Modus = "aggregator")
  ↓
legacy_compat.fetch_latest_prices_via_aggregator()
  ↓
MarketDataAggregator.get_eod(symbol)
  ↓                ↓                ↓
  yfinance →    stooq    →    alphavantage    (Fallback-Chain)
  ↓ (Cache-Miss)
CachedAggregator (TTL 24h für EOD)
  ↓
SQLite market_data_cache

Sonntag 04:00:
  scheduled.weekly_validation_job()
    ↓ Median über alle Provider
    ↓ Diff > 300bps?
    ↓ ja → market_data_validation_log + notifier.post_alert(slack_url)
```

---

## Phase-PR-Mapping

| Phase | PR-Nummer | Branch |
|---|---|---|
| P1 | #18 | `codex/data-pipeline-p01-base` |
| P2 | #19 | `codex/data-pipeline-p02-yfinance` |
| P3 | #20 | `codex/data-pipeline-p03-stooq` |
| P4 | #21 | `codex/data-pipeline-p04-alphavantage` |
| P5 | #22 | `codex/data-pipeline-p05-fallback` |
| P6 | #23 | `codex/data-pipeline-p06-cache` |
| P7 | #24 | `codex/data-pipeline-p07-validation` |
| P8 | #25 | `codex/data-pipeline-p08-openfigi` |
| P9 | #26 | `codex/data-pipeline-p09-macro` |
| P10 | #27 | `codex/data-pipeline-p10-cma-import` |
| P11 | #28 | `codex/data-pipeline-p11-etf-scraper` |
| P12 | #29 | `codex/data-pipeline-p12-twelvedata` |
| P13 | #30 | `codex/data-pipeline-p13-integration` |
| P14 | #31 | `codex/data-pipeline-p14-price-updater-migration` |
| P15 | #32 | `codex/data-pipeline-p15-scheduler-hooks` |
| P16 | #33 | `codex/data-pipeline-p16-admin-status` |
| P17 | #34 | `codex/data-pipeline-p17-admin-fe-panel` |
| P18 | #35 | `codex/data-pipeline-p18-activation-doc` |
| P19 | #36 | `codex/data-pipeline-p19-smoketest` |
| P20 | #38 | `codex/data-pipeline-p20-ci-smoketest` |
| P21 | #40 | `codex/data-pipeline-p21-env-helpers` |
| P22 | #41 | `codex/data-pipeline-p22-alert-webhook` |

Merge in numerischer Reihenfolge.

---

## Test-Coverage

| Modul | Test-File | # Tests |
|---|---|---|
| Aggregator-Core | `test_market_data_aggregator.py`, `test_market_data_cache.py` | ~30 |
| Provider | `test_market_data_yfinance.py`, `_stooq.py`, `_alphavantage.py`, `_twelvedata.py`, `_openfigi.py` | ~80 |
| Cross-Validation | `test_market_data_validation.py` | ~15 |
| Macro | `test_market_data_macro_*.py` | ~25 |
| Legacy-Compat (P13) | `test_market_data_integration.py` | 10 |
| Migration (P14) | `test_price_updater_aggregator_migration.py` | 8 |
| Scheduler (P15) | `test_price_updater_scheduler_hooks.py` | 10 |
| Admin (P16) | `test_admin_market_data_status.py` | 11 |
| FE-Panel (P17) | `test_frontend_admin_market_data_panel.py` | 8 |
| Smoketest (P19) | `test_smoketest_market_data.py` | 16 |
| CI-Workflow (P20) | `test_ci_market_data_workflow.py` | 11 |
| .env-Check (P21) | `test_env_preflight_check.py` | 14 |
| Webhook (P22) | `test_market_data_alert_webhook.py` | 14 |

**Voller Suite-Lauf 2026-05-14:** 442 passed, 3 skipped.

---

## Wann ist Phase abgeschlossen?

| Definition | Status | Verantwortlich |
|---|---|---|
| Code fertig | ✅ Heute | Claude/Codex |
| Live deployt | ⏳ Nach Merge-Sprint | **User** |
| Produktiv ueberwacht | ⏳ 1 Woche danach | CI-Action + Logs |

Naechster Step: **Merge der 38 offenen PRs**. Siehe `docs/status_snapshot_2026-05-14.md` auf PR #39.
