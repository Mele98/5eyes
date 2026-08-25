# ADR-005: Gratis-Marktdaten-Pipeline (CHF 0/Jahr)

- **Status:** Accepted
- **Datum:** 2026-05-29 (Plan), 2026-06-XX (Implementation in 13 Phasen)
- **Sprint:** U-30 (DATA, Roadmap Punkt 30)

## Kontext

Marktdaten-Anbieter (Bloomberg, Refinitiv, Morningstar Direct) kosten
CHF 5'000–50'000/Jahr/Lizenz. Für eine kleine Beratungs-Software ist das
unverhältnismässig. Gleichzeitig brauchen wir Daten für:

- Portfolio-Bewertung (Tages-NAV)
- CMA-Updates (langfristige Risiko/Rendite-Erwartungen)
- Marktdaten-Snapshots für Stress-Replay
- Wechselkurse für Multi-Currency-Mandate

## Entscheidung

Die Pipeline nutzt **nur gratis Quellen**:

1. **yfinance** — Aktien/ETF-Tagespreise (Yahoo Finance Backend)
2. **stooq** — Europäische ETFs + Indizes (Backup für yfinance)
3. **FRED** (St. Louis Fed) — Makrodaten USA
4. **SNB** (Schweizerische Nationalbank) — Wechselkurse + CH-Zinsen
5. **ECB** — Euro-Wechselkurse + EZB-Zinsen

13-Phasen-Plan (Memory: `project_5eyes_data_pipeline.md`):
- Phase 1: Provider-Abstraktion (`MarketDataProvider`-Protocol)
- Phase 2-5: Adapter pro Quelle (mit Rate-Limiting + Cache)
- Phase 6: Fallback-Cascade (yfinance → stooq → cached)
- Phase 7: CMA-Aggregation (Multi-Source-Median)
- Phase 8: Daily Cron (Backend-Job)
- Phase 9-13: Monitoring, Drift-Tests, Schema-Versionierung

## Konsequenzen

**Positiv:**
- **CHF 0/Jahr Betriebskosten** (Hard-Constraint, User-Memory)
- Provider-Abstraktion erlaubt späteren Vendor-Wechsel ohne
  Geschäftslogik-Refactor
- Multi-Source-Median = robusterer CMA als Single-Source

**Negativ:**
- Yahoo Finance hat keine SLA — kann morgen sein API ändern
  → mitigiert via Fallback-Cascade + Daily-Cache
- Intraday-Daten haben Verzögerung (15-20 min) — irrelevant für
  langfristige Beratung, kritisch wäre nur bei Markt-Timing
  (ausgeschlossen via ADR-003)
- Wenig fancy: keine Optionsketten, keine Tick-Daten — bewusst

**Nicht akzeptiert (Alternativen):**
- Bezahlte Provider → Verstoss gegen CHF-0-Hard-Constraint
- Single-Source → Ausfall-Risiko ohne Fallback
- Live-WebSocket-Feed → ermöglicht Markt-Timing (ADR-003)

**Cross-Reference:**
- `docs/MARKET_DATA_PROVIDER_STRATEGY.md` — taktischer Plan
- `docs/data_pipeline_README.md` — Operations-Doku
- `5eyes-backend/README_price_updater.md` — Daily-Cron-Setup
