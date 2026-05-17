# Sprint 9 — Multi-Currency Support

**Datum:** 2026-05-17 (Nacht)
**Status:** Spec / Phase 1 aktiv
**Vorgaenger:** Standortanalyse §D.10 — internationale Mandate.

## 0. Problem

Aktuell ist 5eyes implizit **CHF-only**:
- Mandate.base_currency existiert (default CHF), wird aber nicht in der
  Engine genutzt
- CMA-Returns sind ohne Currency-Annotation (Annahme: CHF)
- Alle Vermoegenspositionen in CHF gerappen (multi-currency in
  WealthPosition existiert aber wird nur konvertiert beim Reporting)
- Reports und Optimizer rechnen ueber alles in CHF

**Konsequenz:** Berater mit EUR-Mandanten (oder USD-Kunden) kann 5eyes
nicht ernsthaft nutzen — alle Returns werden CHF-bewertet.

## 1. Loesung (Phase 1 = Foundation)

**Minimal-Scope:** FX-Rates + Konvertierungs-Service. Spaeter
Currency-Specific-CMAs.

### Architektur

```
services/currency/
├── __init__.py
├── fx_rates.py       # FXRateSource (statisch, default CH-rates)
└── converter.py      # convert(amount, from_ccy, to_ccy)
```

Default-FX-Rates (Stand 2026):
- EUR/CHF ≈ 0.95
- USD/CHF ≈ 0.88
- GBP/CHF ≈ 1.10
- JPY/CHF ≈ 0.0063

**Konzept:**
- Berater pflegt FX-Rates in einem Admin-Editor (analog CMA)
- Reports konvertieren End-Wealth in Mandate-Currency
- Engine selbst rechnet weiterhin in einer Basis-Currency (CHF), aber
  Display + Reports zeigen Mandate-Currency

### Phasen

**Phase 1 — Foundation (jetzt, 1.5h):**
- `FXRateSource` mit Default-Rates 2026
- `convert(amount_rappen, from_ccy, to_ccy)` Helper
- `format_currency(amount_rappen, ccy)` fuer Display
- ~12 Tests (Cross-Rate via CHF, Roundtrip, Edge-Cases)

**Phase 2 — DB-Persistenz + Admin-Editor (later, 2h):**
- `fx_rates`-Tabelle mit valid_from/until + base + quote + rate
- Admin-UI: Berater pflegt EUR/USD/GBP/JPY-Rates
- FXRateSource laedt aus DB statt Hardcode

**Phase 3 — Engine-Integration (later, 1-2h):**
- Mandate.base_currency wird in PDF-Reports respektiert
- Anlagestrategie-PDF zeigt Endwerte in Mandate-Currency
- Cashflow-Konvertierung wenn Position in anderer Waehrung

**Phase 4 — Currency-Specific CMA (later, 3-4h):**
- CMA hat optional per-Currency-Returns-Overrides
- Engine waehlt Currency-passende Returns

## 2. Out-of-Scope (bewusst)

- FX-Vol als zusaetzliche Risk-Quelle (Phase 5+)
- Currency-Hedging-Strategien
- Echtzeit-FX via API (yfinance ist da, aber bringt Komplexitaet)
- Multi-Currency-Portfolios mit FX-Forwards / Swaps

## 3. Erfolgskriterien Phase 1

- convert(100 CHF, 'CHF', 'EUR') ≈ 105 EUR (1/0.95)
- convert(100 EUR, 'EUR', 'CHF') ≈ 95 CHF
- Cross: convert(100 USD, 'USD', 'EUR') = 100*USD/CHF/EUR-CHF ≈ 92.6 EUR
- convert(x, 'X', 'X') = x (Identity)
- Unknown currency → ValueError
- format_currency(123450, 'EUR') → 'EUR 1\'234.50'
- ~12 Tests gruen
