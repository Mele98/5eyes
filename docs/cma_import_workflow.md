# CMA-Quartals-Update — Workflow

Capital Market Assumptions (erwartete Renditen, Volatilitaeten, Korrelationen
pro Asset-Klasse) sind die Grundlage fuer den 5eyes Stochastic Optimizer.
Sie werden quartalsweise von Asset-Managern publiziert und muessen in
5eyes manuell gepflegt werden — das Skript `scripts/import_cma_from_csv.py`
automatisiert das Schreiben in die Datenbank.

## Quellen (gratis, public)

| Asset-Manager | Frequenz | Coverage |
|---|---|---|
| BlackRock Capital Market Assumptions | quartalsweise | 30+ Asset-Klassen, 10/30J Horizont |
| JP Morgan Long-Term CMA | jaehrlich | 200+ Asset-Klassen |
| Vanguard Capital Markets Model | quartalsweise | 15 Asset-Klassen |
| Robeco 5-Year Expected Returns | jaehrlich | fundiert |
| Pictet | jaehrlich | CH-relevant |

Konservative Memory-Empfehlung: **bei mehreren Quellen den tieferen
Renditewert nehmen** (Ruhestandsgelder, Vorsicht vor zu optimistischen
Annahmen).

## CSV-Format

Eine Zeile = ein vollstaendiges CMA-Set. Header-Spalten:

```
assumption_set_name,valid_from,source,notes,valid_until,
bonds_chf_ig_return_bps,bonds_chf_ig_vol_bps,
bonds_fx_hedged_return_bps,bonds_fx_hedged_vol_bps,
bonds_hy_return_bps,bonds_hy_vol_bps,
equity_ch_return_bps,equity_ch_vol_bps,
equity_intl_return_bps,equity_intl_vol_bps,
equity_em_return_bps,equity_em_vol_bps,
real_estate_ch_return_bps,real_estate_ch_vol_bps,
alternatives_gold_return_bps,alternatives_gold_vol_bps,
liquidity_return_bps,liquidity_vol_bps
```

**Beispiel** (`cma_q2_2026.csv`):

```csv
assumption_set_name,valid_from,source,bonds_chf_ig_return_bps,bonds_chf_ig_vol_bps,equity_ch_return_bps,equity_ch_vol_bps,equity_intl_return_bps,equity_intl_vol_bps,liquidity_return_bps,liquidity_vol_bps
BlackRock Q2-2026,2026-04-01,BlackRock LTCMA Q2 2026 PDF p.12,220,350,620,1450,700,1600,80,20
```

Werte in **bps** (1% = 100 bps). Erlaubte Bereiche:
- `_return_bps` in `[-5000, 5000]` (entspricht -50% bis +50% p.a.)
- `_vol_bps` in `[0, 10000]` (0% bis 100% p.a.)

Optional-Spalten (`source`, `notes`, `valid_until`) duerfen leer sein.
Numerische Spalten duerfen einzeln leer sein — dann wird der Wert in der
DB `NULL`.

## Schritt-fuer-Schritt

### 1. Excel-Vorbereitung

1. Asset-Manager-PDF oeffnen (z.B. BlackRock LTCMA Q2 2026).
2. Werte fuer die 5eyes-Buckets ablesen:
   - **Bonds CHF IG**: Schweizer Staats-/Untern.-Bonds Investment Grade
   - **Bonds FX-Hedged**: globale Bonds CHF-hedged
   - **Bonds HY**: High Yield (USD oder global)
   - **Equity CH**: Schweizer Aktien
   - **Equity Intl**: Welt-Aktien ex-CH (oder DM)
   - **Equity EM**: Emerging Markets Equity
   - **Real Estate CH**: Schweizer Immobilien (SXI Real Estate)
   - **Alternatives Gold**: Gold-Spot
   - **Liquidity**: Schweizer Geldmarkt
3. In Excel-Sheet eintragen, als CSV exportieren.

Tipp: aus mehreren Quellen den **Min** der Renditen nehmen (konservativ).

### 2. Dry-Run

```bash
cd C:\5eyes\5eyes_stage9_release_ready
python scripts/import_cma_from_csv.py cma_q2_2026.csv
```

Ausgabe zeigt:
- alle Validation-Issues (Fehler vorher beheben)
- Diff gegen aktuelles `is_current=1` Set (was sich aendert)

### 3. Apply

```bash
python scripts/import_cma_from_csv.py cma_q2_2026.csv --apply --user-id ${YOUR_USER_ID}
```

- bestehender `is_current=1` Eintrag fuer denselben Namen wird auf `is_current=0` gesetzt
- neue Zeile mit `version = previous + 1`, `is_current=1`

### 4. Verification

```bash
# Backend-Test-Suite
cd 5eyes-backend
.venv/Scripts/python.exe -m pytest tests/test_cma_import.py -q
```

Plus optional: in der App auf einer Allocation-Generation pruefen, dass
die neuen Werte greifen (Reasoning-Trace zeigt CMA-Source).
