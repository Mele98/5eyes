# Risk-Free Rate in CMA — Spec (Audit-Punkt #27)

**Datum:** 2026-05-06
**Owner:** Emanuele
**Status:** ENTWURF — implementieren erst wenn ein Konsumer da ist (Sharpe-Ratio o.ae.).

## Hintergrund

Aus Audit-Sprint 2026-04: CapitalMarketAssumption hat keine Risk-Free Rate.
Aktuell ist das kein Problem weil kein Backend-Code Sharpe-Ratio rechnet.
Bei den naechsten Audit-Erweiterungen (z.B. Sharpe in Goal-Analysis,
Risk-Adjusted Performance im Reporting) ist der Risk-Free aber Pflicht.

## Quellen

- Brunel "Goals-Based Wealth Management" (2015), Kap. 5: Sharpe-Ratio
- Vanguard "Vanguard 2024 Asset/Allocation Outlook": Risk-Free Schaetzungen
- SwissLife Asset Management Q1 2026 House View: Risk-Free CHF = SARON spot

## Vorschlag

### CMA-Schema-Erweiterung

```python
# 5eyes-backend/models/allocation.py / CapitalMarketAssumption
risk_free_rate_chf_bps = Column(Integer)  # SARON spot bzw. Mandat-naehe
risk_free_rate_eur_bps = Column(Integer)  # ESTR spot
risk_free_rate_usd_bps = Column(Integer)  # SOFR spot
risk_free_source = Column(String)         # 'SARON', 'ESTR', 'SOFR', 'Mandat'
risk_free_valid_from = Column(String)
```

Konservative Defaults (Stand 2026-05):
- CHF: 50 bps (0.5% — SARON Q1 2026)
- EUR: 250 bps (2.5%)
- USD: 425 bps (4.25%)

### Konsumer (zukuenftig, NICHT in dieser Spec implementiert)

1. **Sharpe-Ratio in Goal-Analysis**:
   ```
   sharpe = (expected_return_bps - risk_free_chf_bps) / expected_volatility_bps
   ```

2. **Risk-Adjusted Performance im Reporting**:
   - Treynor-Ratio
   - Information-Ratio
   - Sortino-Ratio (mit Downside-Vol)

3. **Optimizer-Erweiterung** (Phase 8?):
   - Mean-Variance-Constrained-Optimization mit Sharpe-Maximierung statt
     reiner Goal-Shortfall (Mulvey-Variante).

## Migration

```python
# database.py / ensure_runtime_columns()
'capital_market_assumptions': [
    ...
    ('risk_free_rate_chf_bps', 'INTEGER'),
    ('risk_free_rate_eur_bps', 'INTEGER'),
    ('risk_free_rate_usd_bps', 'INTEGER'),
    ('risk_free_source', 'TEXT'),
    ('risk_free_valid_from', 'TEXT'),
],
```

## API

`CapitalMarketAssumptionResponse` + `Create`: 5 neue optionale Felder ergaenzen.
Default-Updater (`ensure_runtime_reference_data` o.ae.): konservative Defaults
einsetzen wenn NULL.

## Tests

- 1 Migration-Test (Spalten existieren nach `ensure_runtime_columns()`)
- 1 Schema-Test (CMA-Response liefert die 5 Felder, default None)
- 1 Default-Test (`ensure_runtime_reference_data` setzt SARON=50bps wenn leer)

## Aufwand-Schaetzung

- Backend (Migration + Schema + Default): ~2h
- FE (Admin-Editor fuer CMA): ~1h (wenn ueberhaupt — kann via Direct-API gepflegt werden)
- Tests: ~1h
- **Gesamt: ~4h** — aber nur sinnvoll wenn ein Konsumer (Sharpe etc.) gleichzeitig kommt.

## Was NICHT in dieser Spec ist

- Sharpe-Ratio-Implementierung (eigene Spec, sobald Konsumer feststeht).
- Mehr-Waehrungs-FX-Hedge-Logik.
- Real vs nominal Risk-Free.
