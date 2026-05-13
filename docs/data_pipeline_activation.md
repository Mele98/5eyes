# Multi-Source-Datenpipeline aktivieren (P1-P17)

**Stand:** 2026-05-12 — Multi-Source-Aggregator vollstaendig implementiert
(PRs #18-34). Diese Anleitung beschreibt, wie der User die Pipeline in
Produktion aktiviert.

## TL;DR

Drei Zeilen in `.env` aktivieren den Multi-Source-Pfad mit Fallback,
Caching und Health-Backoff — Kosten **CHF 0/Jahr**:

```env
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator
MARKET_DATA_PROVIDERS=yfinance,stooq,alphavantage
ALPHAVANTAGE_API_KEY=<dein-key>
```

Backend neustarten, fertig. Diagnose: Admin-Modal in der App, Panel
"Datenpipeline-Status".

---

## 1. Voraussetzungen

### Python-Pakete

Seit P2 (yfinance), P3 (stooq), P11 (BeautifulSoup fuer ETF-Scraper) in
`requirements.txt`. Nichts manuell zu installieren — `pip install -r
requirements.txt` reicht.

### API-Keys (gratis-Tier)

| Provider | Signup | Key noetig? | Kostenlos-Limit |
|---|---|---|---|
| **yfinance** | – | nein | unbegrenzt (TOS-Grauzone, OK fuer Einzel-Berater) |
| **stooq** | – | nein | unbegrenzt |
| **alphavantage** | alphavantage.co/support/#api-key | ja | 500 Calls/Tag |
| **twelvedata** (opt.) | twelvedata.com/pricing | ja | 800 Calls/Tag |
| **OpenFIGI** (opt.) | openfigi.com/api | ja | 25 Symbole/Min (gratis) |
| **FRED** (Makro, opt.) | fred.stlouisfed.org/docs/api/api_key.html | ja | unbegrenzt |

Mindestens fuer **alphavantage** Key besorgen (gratis Signup, kein
Bezahlweg hinterlegen).

---

## 2. .env-Schalter

### Pflichtfelder fuer Aktivierung

```env
# Primary-Pfad fuer Preisabruf: 'aggregator' aktiviert P13 Multi-Source.
PRICE_REFRESH_PRIMARY_PROVIDER=aggregator

# Reihenfolge der Aggregator-Provider (Fallback-Chain links->rechts).
MARKET_DATA_PROVIDERS=yfinance,stooq,alphavantage

# Alphavantage-Key (gratis).
ALPHAVANTAGE_API_KEY=ABCDEFG1234567
```

### Optional: Cross-Validation

```env
# Wochen-Job (sonntags 04:00) prueft Median-Diff zwischen Providern.
MARKET_DATA_VALIDATION_ENABLED=true

# Symbol-Liste fuer die Validation (sonst skipped).
MARKET_DATA_VALIDATION_SYMBOLS=UBSG.SW,AAPL,MSFT,NESN.SW,NOVN.SW

# Alert-Schwelle: 300 = 3% Diff zwischen min und max.
MARKET_DATA_VALIDATION_THRESHOLD_BPS=300
```

### Optional: Cache-Purge anpassen

```env
# Default: taeglich 03:00 lokal (Europe/Zurich).
MARKET_DATA_CACHE_PURGE_ENABLED=true
MARKET_DATA_CACHE_PURGE_HOUR=3
MARKET_DATA_CACHE_PURGE_MINUTE=0
```

### Optional: TwelveData als Tier-2-Provider

```env
MARKET_DATA_PROVIDERS=twelvedata,yfinance,stooq
TWELVEDATA_API_KEY=<dein-twelvedata-key>
```

---

## 3. Tier-Modell

| Tier | Provider-Stack | Kosten | Best fuer |
|---|---|---|---|
| **1** (heute) | yfinance + stooq + alphavantage | CHF 0/Jahr | Einzel-Berater ohne Lizenz |
| **2** (Skalierung) | twelvedata + yfinance + stooq | ~CHF 960/Jahr | 5+ Beratungsfirmen |
| **3** (FINIG-Lizenz) | SIX Financial Information | CHF 8'000-10'000/Jahr | regulierter Vermoegensverwalter |

Wechsel zwischen Tiers = 1 `.env`-Aenderung. Kein Code-Refactor noetig.

---

## 4. Diagnose

### Frontend (P17 Admin-Panel)

1. App starten, Admin-Modal oeffnen.
2. Section "Datenpipeline-Status" zeigt:
   - **Provider-Karte:** Name + Ampel (gruen=healthy, rot=unhealthy).
   - **Cache-Karte:** pro `cache_kind` valid/expired/total Counter.
   - **Cross-Validation-Karte:** Alert-Counter aus letzten 10 Logs.
   - **Scheduler-Jobs-Liste:** ID + next_run_at.
3. Polling alle 60s, manueller Refresh-Button.

### Backend-Endpoint (P16)

```bash
curl -H "Authorization: Bearer <admin-token>" \
  http://localhost:8000/admin/market-data/status
```

Liefert JSON mit allen oben genannten Sektionen plus `generated_at`-Timestamp.

### Logs

```
daily_cache_purge_job: 47 expired entries removed
weekly_validation_job: checked=12 alerts=1 on_date=2026-05-10
```

---

## 5. Migration aus dem Legacy-Pfad

Bestehende Konfiguration mit `PRICE_REFRESH_PRIMARY_PROVIDER=yfinance` oder
`twelvedata` bleibt funktionsfaehig. Empfohlener Migrationspfad:

1. `.env` testen mit `PRICE_REFRESH_PRIMARY_PROVIDER=aggregator` und
   `PRICE_REFRESH_FALLBACK_PROVIDER=yfinance` (alter Pfad bleibt sichernd).
2. Eine Woche beobachten via Admin-Panel.
3. Wenn stabil: `PRICE_REFRESH_FALLBACK_PROVIDER` entfernen.

Rollback jederzeit moeglich: `PRICE_REFRESH_PRIMARY_PROVIDER=yfinance`
wieder setzen.

---

## 6. Was ist eingebaut

| Phase | Inhalt | PR |
|---|---|---|
| P1-P12 | Provider-Adapter (yfinance, stooq, alphavantage, twelvedata), OpenFIGI, FRED/ECB/SNB, ETF-Scraper, CMA-Import | #18-#29 |
| P13 | Legacy-Compat-Layer (drop-in fuer twelvedata_client) | #30 |
| P14 | price_updater.py-Routing auf `aggregator`-Pfad | #31 |
| P15 | APScheduler-Hooks (Cache-Purge daily, Cross-Validation weekly) | #32 |
| P16 | Admin-Endpoint `/admin/market-data/status` | #33 |
| P17 | Admin-FE-Panel "Datenpipeline-Status" | #34 |

---

## 7. Haeufige Probleme

**Provider rot in Admin-Panel:**
- alphavantage rot: Key fehlt oder Limit (500/Tag) erreicht.
- twelvedata rot: Key fehlt.
- yfinance/stooq rot: temporaer (kein Key noetig, Netzwerk pruefen).

**Cache leer:**
- Erster Lauf nach Aktivierung — wird mit jedem Preisabruf gefuellt.

**Validation-Alerts > 0:**
- Provider zeigen >3% Diff fuer dasselbe Symbol. Pruefen, ob Symbol fuer
  alle Provider gleich aussieht (Yahoo: UBSG.SW, Stooq: ubsg.ch wird
  automatisch konvertiert, aber manuelle Overrides koennten kollidieren).

**Scheduler inaktiv:**
- `PRICE_SCHEDULER_ENABLED=true` setzen (Default ist `true`).
- APScheduler installiert? `pip install apscheduler`.
