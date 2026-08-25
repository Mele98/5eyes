# Data Pipeline — Status-Tracker

Snapshot des aktuellen Implementierungs-Stands der Multi-Source-Datenpipeline.
Komplementaer zu `data_pipeline_README.md` (Aktivierung) und
`MARKET_DATA_PROVIDER_STRATEGY.md` (Strategie). Hier: was läuft, was nicht,
und was als naechstes.

**Stand:** 2026-06-05
**Roadmap-Punkte:** #30 (Master), #31 (Tages-Refresh), #99 (FX-Cron),
#100 (Nelson-Siegel)
**Architektur-Doktrin:** [ADR-005](adr/ADR-005-free-data-pipeline.md) — CHF 0/Jahr

---

## Phasen-Status

Skala: ✅ produktiv · 🟡 implementiert/inaktiv · ⏳ in Arbeit · ❌ offen · 🚫 verworfen

### Provider-Stack (P1-P12)

| Phase | Komponente | Status | Sprint |
|------:|------------|:------:|-------|
| P1 | Provider-Adapter-Pattern (ABC + Dataclasses) | ✅ | — |
| P2 | YFinanceProvider (Primary) | ✅ | — |
| P3 | StooqProvider (Backup) | ✅ | — |
| P4 | AlphaVantageProvider (Backup #2) | 🟡 | — |
| P5 | MarketDataAggregator + Fallback-Chain | ✅ | — |
| P5.1 | Provider-Health-Registry (persistiert) | ✅ | — |
| P6 | Smart Cache (TTL pro cache_kind) | ✅ | — |
| P7 | Cross-Validation (Median-Diff, ValidationLog) | ✅ | — |
| P8 | OpenFIGIProvider (ISIN-Lookup) | ✅ | — |
| P9 | Macro-Pipeline (FRED + ECB + SNB) | ✅ | — |
| P10 | CMA-CSV-Import (Quartals-Workflow) | ✅ | — |
| P11 | ETF-Scraper (Justetf + Swissfunddata) | 🟡 opt-in | — |
| P12 | TwelveDataProvider (Tier-2, ~CHF 80/Mo) | 🚫 | — |

### Operations (P13-P22)

| Phase | Komponente | Status | Sprint |
|------:|------------|:------:|-------|
| P13 | Daily-Cron Asset-Class-Prices | ✅ | U-31 |
| P14 | Daily-Cron Annual-Returns | ✅ | — |
| P15 | Backfill-Endpoints (Admin) | ✅ | U-P11a/P19 |
| P16 | Cache-Purge (health-aware) | ✅ | — |
| P17 | Smoketest-Script | ✅ | — |
| P18 | Admin-Modal: Pipeline-Status | ✅ | — |
| P19 | Asset-Class-Prices-Backfill | ✅ | — |
| P20 | Reference-Data via Mapping-Provider | ✅ | — |
| P21 | Audit-Trail Admin-Actions | ✅ | U-102 |
| P22 | Recovery-Triggers (manual refresh/purge) | ✅ | U-31 |

### Roadmap-Offene (>P22)

| Roadmap-Nr | Punkt | Status | Aufwand |
|---:|-------|:------:|---------|
| #30 | 13-Phasen-Master-Plan (gesamt) | ⏳ | 24 Tage |
| #31 | Tagesaktuelle Marktdaten-Updates | ❌ | ~4 h |
| #99 | FX-Rate-History Auto-Refresh-Cron | ❌ | ~1 h |
| #100 | Bond-Yields Nelson-Siegel-Kalibrierung 2024 | ❌ | ~2 h |

---

## Live-Diagnose

| Quelle | Pfad | Was sehe ich |
|--------|------|--------------|
| Admin-Modal | `Admin → Datenpipeline-Status` | letzte Refresh/Purge/Validation pro Provider |
| API | `GET /admin/system/market-data/provider-health` | Health-Events-Liste |
| API | `GET /admin/system/market-data/purge-history` | letzte Cache-Purges |
| Script | `python scripts/smoketest_market_data.py` | End-to-End-Roundtrip |
| Script | `python scripts/check_env_for_pipeline.py` | .env-Validation |

---

## Aktive Bekannte Limits

- **YFinance TOS:** Yahoo Finance verbietet kommerzielle Nutzung; OK fuer
  Einzel-Berater. Bei Skalierung Tier-2 erforderlich.
- **AlphaVantage:** Gratis-Tier 500 Calls/Tag — reicht fuer Snapshot-Backup,
  nicht fuer Daily-Backfill.
- **Stooq:** Kein offizielles Rate-Limit, aber 1 Request/Sek empfehlenswert.
- **ETF-Scraper (P11):** TOS-grenzwertig, daher opt-in via Settings-Flag.

## Cost-Disziplin

CHF 0/Jahr ist Hard-Constraint ([ADR-005](adr/ADR-005-free-data-pipeline.md)).
Bezahlte Provider sind **nicht** akzeptierbar ohne explizite User-Decision.
TwelveData (P12) als Tier-2-Option dokumentiert aber bewusst inaktiv.

---

## Wie diesen Doc aktualisieren?

Bei Sprint-Abschluss der einen Phase betrifft, hier den Status-Marker
umstellen. Nutze `git log -- docs/DATA_PIPELINE_STATUS.md` als Audit-Spur.
Bei groesseren Aenderungen (Status-Wechsel produktiv → verworfen oder
umgekehrt) zusaetzlich ADR-005 aktualisieren.
