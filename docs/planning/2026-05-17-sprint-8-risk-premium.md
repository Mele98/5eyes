# Sprint 8 — Risikoprämien-Modell für RE / Alternatives

**Datum:** 2026-05-17 (Nacht)
**Status:** Spec / aktiv
**Vorgaenger:** Standortanalyse §B.6 — letzter Engine-Tiefe-Gap zu 3eyes.

## 0. Problem

Real Estate + Alternatives-Returns aktuell als fixe Werte in CMA:
- `real_estate_ch_return_bps = 400`
- `alternatives_gold_return_bps = 300`

Das ignoriert die fundamentale Beziehung: **Risiko-Asset-Returns sind das
Risiko-Premium ueber dem risikofreien Zins.**

Bei Zinsaenderungen:
- Heute (5eyes): RE-Return bleibt 400 bps egal wo Zinsen stehen
- Realitaet: bei 4% risk-free + 200 bps Premium = 6% RE-Return
  bei 1% risk-free + 200 bps Premium = 3% RE-Return

Konsequenz: Aktuelle Engine ueberbewertet RE/Alts in Niedrigzins-Phasen.

**3eyes-Aequivalent:** Risikopraemien-Aufbau ueber Yield-Curve (NS).

**Allocation-Wirkung:**
- Bei Zinsanstieg: RE und Alts werden relativ attraktiver
  (mehr absolute Rendite-Erwartung)
- Bei Zinssenkung: weniger attraktiv
- SAA passt sich automatisch an Zinsumfeld an

## 1. Loesung

**Modell:** RiskPremiumModel mit Premium ueber risk-free rate.

```
expected_return_bps = risk_free_rate_bps + premium_bps + size_adjustment_bps
```

Wobei:
- `risk_free_rate_bps` = NS-Curve.short_rate oder Cash-Yield (≈ 6M-Yield)
- `premium_bps` = empirisches Premium pro Asset-Klasse
  (RE ~150-250 bps, Alts ~200-400 bps)
- `size_adjustment_bps` = Mandatsgroessen-Bonus (optional Phase 3)

## 2. Modul-Struktur

```
5eyes-backend/
├── services/risk_premium/
│   ├── __init__.py
│   └── model.py                  # RiskPremiumModel
└── tests/risk_premium/
    └── test_model.py
```

## 3. Phasen

### Phase 1 — Foundation + CMA + Engine (jetzt, 2h)
- `RiskPremiumModel(asset_class, premium_bps)` dataclass
- `.expected_return_bps(risk_free_bps)` -> bps
- CMA-Felder: `real_estate_risk_premium_bps`, `alternatives_risk_premium_bps`
- Engine-Integration: wenn Premium gesetzt UND NS-Curve aktiv:
  re_return = NS.short_rate + premium
  Fallback: fixe alte Werte
- ~15 Tests

### Phase 2 — UI im CMA-Editor (jetzt, 20 min)
- 2 neue Felder in der "Engine-Modelle" Section (collapsible)
- collect + apply analog NS/KGV

### Phase 3 (spaeter, on-demand)
- Pro Sub-Asset-Class eigene Premia (RE-CH vs RE-Intl)
- Stochastische Premium-Schwankung
- Size-Adjustment fuer Mandate > X Mio

## 4. Erfolgskriterien

- Premium=0 -> return = risk_free (kein Premium)
- Premium gesetzt + NS aktiv -> return = NS.short_rate + Premium
- Premium gesetzt + KEIN NS -> Fallback auf fixe Werte (Backwards-Compat)
- Andere Buckets (equities, bonds, liquidity) unveraendert
- Bei Zinsanstieg: RE-Return steigt mit
