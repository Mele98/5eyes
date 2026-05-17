# Sprint 2 Spec: Steuern + Dividenden-Split

Stand: 2026-05-17
Quelle: docs/planning/2026-05-17-standortanalyse-vs-3eyes.md §5.A (P0 Compliance-Gap)

## Ziel

Schliesse die 2 grössten 3eyes-Gaps (laut Standortanalyse) — Steuern und
Dividenden-Split — als Engine-Mathematik mit Backwards-Compat:
- Beide Features default OFF (alle Sätze 0, alle dividend_yield 0)
- Wenn aktiv: Wealth-Pfad rechnet realistischer
- Tests: ohne Aktivierung 100% identisch zu vorher

## Item 1: Steuern-Modell

### Scope
Schweizer Vermögensberatung-Pauschal-Modell:
- **Vermögenssteuer p.a.**: jährlich abgezogener Prozentsatz vom End-Wealth
  pro Jahr. Default 0 bps (= 0%). Realistisch CH: 20-50 bps (0.2-0.5%).
- **Kapitalertragssteuer**: prozentualer Abzug auf Dividenden/Zinsen.
  Default 0 bps (= 0%). Realistisch CH: 25-35% Verrechnungssteuer.
- **Kapitalbezugssteuer** ist bereits in Cashflow-Modell vorhanden
  (`gross_amount_rappen`, `tax_amount_rappen`) — kein Touch nötig.

### Schema-Erweiterung CMA
```python
vermoegenssteuer_bps_pa: int = 0   # CH typisch 20-50 bps
kapitalertrag_steuer_bps: int = 0  # CH typisch 2500-3500 bps
```

### Engine-Erweiterung
Wealth-Pfad: jährliche `wealth *= (1 - vermoegenssteuer_bps_pa / 10000)` nach Return.

### Backwards-Compat
- CMA-Default beide Steuersätze = 0 → keine Verhaltens-Änderung
- Existierende Tests laufen unverändert
- Migration via ensure_runtime_columns mit Default 0

## Item 2: Dividenden-Split CMA-Erweiterung

### Scope
Trennung Total Return = Dividend Yield + Price Appreciation (3eyes Slide 20).

### Schema-Erweiterung CMA
```python
dividend_yield_bps_equity_ch: int = 0   # SPI ~ 250-300 bps
dividend_yield_bps_equity_intl: int = 0  # MSCI World ~ 150-200 bps
dividend_yield_bps_real_estate: int = 0  # CH-REITs ~ 250-300 bps
```

### Engine-Erweiterung
Optional Income-Stream wenn `dividend_yield_bps > 0` und Kapitalertragssteuer aktiv.

## Tests pro Item

- CMA-Roundtrip mit neuen Feldern
- Migration läuft sauber (ensure_runtime_columns)
- Engine: ohne aktive Steuer/Dividende identisches Wealth-Path-Ergebnis
- Engine: mit Steuer X% → Wealth < ohne Steuer

## Nicht-Scope (eigene Specs)

- Kantonsspezifische Tax-Tables
- DA-1-Verrechnungssteuer-Rückforderung
- Dividenden-Pfad-Modell mit Mean-Reversion (3eyes Slide 20 Aktien-Bewertungsmodell)
- BVG-/AHV-spezifische Steuerlogik

## Reihenfolge

1. Spec (dieser File)
2. Item 1 CMA-Schema + Migration
3. Item 1 Engine
4. Item 1 Tests
5. Item 1 Commit
6. Item 2 CMA-Schema
7. Item 2 Engine
8. Item 2 Tests
9. Item 2 Commit
10. Status-Update Standortanalyse §5.A
