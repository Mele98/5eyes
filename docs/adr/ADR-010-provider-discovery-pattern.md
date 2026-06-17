# ADR-010: Provider-Discovery via Entry-Points (Bloomberg-Ready)

- **Status:** Accepted
- **Datum:** 2026-06-09
- **Sprint:** SMI-1988 + Sub-Anlageklassen Phase 5

## Kontext

ADR-005 etabliert die gratis Marktdaten-Pipeline mit yfinance / stooq /
FRED / SNB / ECB. Fuer fortgeschrittene Berater oder Tier-2/3-Lizenzkunden
besteht aber konkreter Bedarf nach professionellen Quellen:

- **Bloomberg** als Goldstandard fuer historische Sub-Anlageklassen
  (SMI seit 1988, MSCI EM seit 1988, Bloomberg Global Aggregate seit
  1990, etc.)
- **Refinitiv** als Bloomberg-Alternative
- **Morningstar Direct** fuer Funds-Coverage

Diese Quellen kosten 5'000-50'000 CHF/Jahr und sind nicht fuer alle 5eyes-
Nutzer relevant. ADR-005 bleibt strikt: KEINE Pflicht-Kosten fuer Daten.

Wie integrieren wir diese Provider, ohne dass:
- Sie als Default-Dependency mitgebaut werden (Bloomberg-Wheel nicht im PyPI)?
- Der Boot bei fehlender Lizenz crasht?
- Wir die Kerncodebasis bei jedem neuen Provider anfassen muessen?

## Entscheidung

**Provider-Discovery via Python-Entry-Points**, analog zum Tax-SDK-Pattern
aus ADR-006.

### Architektur

```
5eyes-backend/services/market_data/
  base.py                  # MarketDataProvider-Abstract
  factory.py               # build_aggregator() — Default-Provider
  provider_discovery.py    # Entry-Point-Loader (NEU, Phase 5)
  providers/
    yfinance_provider.py   # Default (gratis)
    stooq_provider.py      # Default (gratis)
    bloomberg_provider.py  # Stub (Phase 5), aktiv via blpapi + Lizenz
```

Externe pip-Pakete deklarieren in ihrer `pyproject.toml`:

```toml
[project.entry-points."5eyes.market_data_provider"]
bloomberg = "fivee_eyes_bloomberg:BloombergProvider"
refinitiv = "fivee_eyes_refinitiv:RefinitivProvider"
```

Beim Boot scannt 5eyes diese Entry-Group, instanziiert konforme Provider
und fuegt sie in die Aggregator-Cascade. Konformanz-Check:

1. Class erbt von `MarketDataProvider`
2. `get_eod` / `get_history` / `lookup_isin` vorhanden
3. `name` ist non-empty String und nicht kollisionierend
4. Zero-Arg-Constructor (`Provider()`)

Provider die nicht-konform sind werden **mit Warning geloggt aber NICHT
geraised** — damit ein kaputtes Drittpaket nicht den Boot abbricht.

### BloombergProvider als interner Stub

Wir liefern `BloombergProvider` als Skelett mit:
- Lazy-Import von `blpapi` (Bloomberg-eigenes Wheel, nicht im PyPI)
- Klare `pip install --index-url=https://blpapi.bloomberg.com/...`-Anleitung
- `is_healthy()` liefert False wenn blpapi nicht installiert -> Aggregator
  ueberspringt den Provider automatisch
- 3 Pflicht-Methoden liefern heute `SymbolNotFound` mit Hinweis auf
  Phase 5b (eigentliche Implementation nach Lizenz-Aktivierung)

Damit ist der `symbol_catalog` Bloomberg-Symbole konkret dokumentieren
kann (`SMI Index`, `SPXT Index`, `LF98TRUU Index`) ohne dass Bloomberg
fuer den Boot benoetigt wird.

## Konsequenzen

### Positiv

- **Cost-Disziplin ADR-005 bleibt**: Default-Installation traegt KEINE
  kostenpflichtigen Dependencies. Berater entscheiden bewusst pro
  Bloomberg-Aktivierung.
- **Modulare Erweiterung**: Bloomberg/Refinitiv/Morningstar koennen als
  separate pip-Pakete entwickelt + ausgeliefert werden, ohne 5eyes-Kern
  zu touchen.
- **Plugin-Konfusion klein**: Provider-Interface ist eng (3 Methoden +
  `name`), Konformanz-Check verhindert Wildwuchs.
- **Tier-2/3-Lizenz-Modell**: Lizenzkunden koennen 5eyes-Bloomberg-
  Adapter als Add-on lizensieren.

### Negativ

- **Test-Coverage von Stub-Provider niedrig**: `BloombergProvider` ist
  bis zur Lizenz-Aktivierung Stub. Phase 5b braucht Live-Tests gegen
  Bloomberg-Sandbox.
- **Discovery-Order ist nicht garantiert**: Externe Provider werden in
  Entry-Point-Reihenfolge geladen. Berater muss in factory.py die
  Cascade-Reihenfolge manuell mischen wenn Praeferenz spezifisch ist.
- **Entry-Point-Scope ist global**: Wenn zwei externe Pakete den
  gleichen `name` ("bloomberg") deklarieren, gewinnt First-Wins + Log-
  Warning. Berater muss wissen welche Pakete er installiert hat.

## Referenz-Implementation

- `services/market_data/provider_discovery.py` — Entry-Point-Loader
- `services/market_data/providers/bloomberg_provider.py` — Skelett
- `tests/test_provider_discovery.py` — Konformanz-Tests + Default-Provider
- `tests/test_bloomberg_provider_stub.py` — Stub-Tests (blpapi-Missing-Fall)
- Memory: `[[5eyes-roadmap-110-offene-punkte]]` Punkt SMI-1988-Sub-Asset

## Verwandt

- ADR-005: Gratis-Marktdaten-Pipeline (definiert was Default-installiert ist)
- ADR-006: Tax-SDK-Pattern (gleiches Entry-Point-Konzept fuer Steuer-Plugins)
- ADR-009: 3-Tier-Hosting (Tier-2/3-Lizenzkunden werden Bloomberg eher haben)
