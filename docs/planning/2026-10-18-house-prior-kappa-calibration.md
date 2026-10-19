# κ_H-Kalibrierung des Hausmatrix-Priors – commitgebundenes Paket

Stand 2026-10-18 · HOUSE-PRIOR-CALIBRATION-PROVENANCE-001 (Codex-Review `2026-10-18-house-prior-v6-pr640-current-review.md`, §9)
Produktparameter: `services/optimizer/house_prior.py` – `HOUSE_PRIOR_KAPPA = 300.0`, `HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS = "experimental_tuned_holdout_checked"` (im Audit unter `house_prior.prior_metric.kappa_calibration_status`).

## 1. Inhalt

| Teil | Ort | Rolle |
|---|---|---|
| Tuning-Skripte (unverändert, Stand der Auswahl) | `tools/house_prior_calibration/tuning_2026_10_18/` | `exp_common.py`, `exp_main.py` (Sweep/Seeds), `exp_kappa.py` (κ-Raster), `exp_misspec.py` + `exp_misspec300.py` (Schätzfehler-Welten), `analyze.py`, `analyze2.py`, `calib.py` |
| Tuning-Rohdaten | `2026-10-18-house-prior-kappa-calibration/tuning_raw/*.jsonl.gz` | 50 Dateien, gzip; SHA-256 der unkomprimierten JSONL in `tuning_manifest.json` |
| Tuning-Auswertungen | `…/results_main.txt`, `…/results_kappa_misspec.txt` | Ausgabe von `analyze.py`/`analyze2.py` (Hash im Manifest) |
| Holdout-Skript (vorab registrierte Regel) | `tools/house_prior_calibration/kappa_holdout.py`, `calibration_common.py` | neuer, unberührter Test mit der Produktions-Engine v7 |
| Holdout-Rohdaten + Entscheid | `…/holdout/holdout_*.jsonl`, `…/holdout/holdout_summary.json` | 150 Welten; Hashes im Summary |

## 2. Tuning (2026-10-18, Auswahl von κ_H = 300)

* **Engine:** `saa_resampled_v5` (Worktree `C:/tmp/5eyes-shrink-design`, Branch `origin/fix/importance-sampling-ess`), Prior per Monkeypatch des Tiebreaks (`exp_common.run_prior`), Bag-Konfiguration Produktion (40 × 500), Signifikanztest aus. Die Skripte importieren diesen Worktree-Pfad – sie sind Provenienz, nicht mehr ausführbar gegen `develop` ohne Anpassung des `BACKEND`-Pfads.
* **Inputs:** CMA/Hausmatrizen 1:1 aus `tests/test_engine_reference_mandates.py`, fünf Referenzmandate A–E (`MANDATES`), Zielbetrag-Skalen 0.80–1.20.
* **Seeds:** Inhalts-Seed der Engine bzw. `sha256("|".join(parts))` (`_seed_of`): Welten `(mandat, "misspec", k)`, OOS-Würfel `(mandat, "oos")`, Welt-Pfade `(mandat, "world-paths")`.
* **Raster:** κ ∈ {10, 30, 100, 300, 1000, 3000}; Schätzfehler-Test (Engine sieht μ̂ = μ + Lz/√20, Bewertung unter wahrer CMA auf 20'000 Pfaden) für κ ∈ {30, 100, 300, 1000}, 15 Mandat/Skala-Zellen × 10 Welten = 150.
* **Ergebnis** (`results_kappa_misspec.txt`, gepaart gegen v5 je Welt): κ 300 ΔP(Ziel) +1.31 pp (se 0.18), κ 100 +1.16, κ 1000 +1.15, κ 30 +1.16; reine Hausquote +0.82; reiner Optimierer −2.21. OOS-Zielebene (κ-Raster, Summe) 0.6017 bei 300 vs. 0.6009 bei 100.
* **Einschränkungen (offen benannt):** Auswahlregel post hoc (kein vorab registriertes Kriterium); dieselben 150 Welten für Auswahl und Ausweis (Winner's Curse); keine Multiple-Comparison-Korrektur über 4–6 κ; 100–1000 innerhalb 1 se gleichwertig.

## 3. Holdout (vorab festgelegt, unberührte Welten)

Regel und Seeds stehen im Docstring von `kappa_holdout.py` und wurden **vor** dem ersten Lauf festgelegt:

* Engine `saa_resampled_v7` (Ridge-Metrik Σ + εI, Einheiten-Bootstrap, B = 999), Produktionskonfiguration, κ per `solver.HOUSE_PRIOR_KAPPA` gesetzt.
* Neue Welten-Domäne `kappa-holdout-v1` (das Tuning nutzte `misspec`), neuer OOS-Würfel `kappa-holdout-oos-v1` (20'000 Pfade, antithetisch), 5 Mandate × Skalen {0.90, 1.00, 1.10} × 10 Welten = 150; T_EST = 20.
* Referenz: projizierte Hausquote. Primärer Endpunkt: ΔP(Ziel) = P(κ) − P(Haus), gepaart je Welt.
* **R1** (kein Schaden ggü. Haus): einseitige 95-%-Untergrenze (t) von mean ΔP(κ = 300) > 0.
* **R2** (nicht dominiert): mean ΔP(300) ≥ max(mean ΔP(100), mean ΔP(1000)) − 1 se der gepaarten Differenz.
* Entscheid `confirmed` ⇔ R1 ∧ R2; sonst `not_confirmed` (keine automatische Änderung).

**Ergebnis** (`holdout/holdout_summary.json`, Bewertungsjahr 2026):

| κ_H | mean ΔP(Ziel) vs. Haus | se | Welten besser / schlechter | mean ΔZielebene | se |
|---|---|---|---|---|---|
| 100 | +0.222 pp | 0.079 | 70.0 % / 20.0 % | −0.0253 | 0.0088 |
| **300** | **+0.307 pp** | 0.070 | 70.7 % / 13.3 % | −0.0258 | 0.0086 |
| 1000 | +0.256 pp | 0.053 | 60.0 % / 12.0 % | −0.0261 | 0.0075 |

* R1: Untergrenze +0.192 pp > 0 → erfüllt.
* R2: κ300 − κ100 = +0.086 pp (se 0.034), κ300 − κ1000 = +0.052 pp (se 0.037) → erfüllt.
* **Entscheid: `confirmed`.**

Lesart: Der Vorteil gegenüber der reinen Hausquote ist auf unberührten Welten deutlich kleiner als im Tuning ausgewiesen (Tuning κ300 vs. Haus ≈ +0.49 pp = 1.31 − 0.82; Holdout +0.31 pp) – erwartbar bei Auswahl auf denselben Welten. κ = 300 bleibt die beste der drei Stufen; 300 und 1000 sind innerhalb von 1.4 se nicht trennbar, 100 ist signifikant schwächer (2.5 se). Die Zielebene (Fehlbetrag + Chance-Strafe) ist für alle drei κ gleich gut (Unterschiede < 0.1 se).

Grenzen: 150 Welten aus 5 Mandaten (Standardfehler über Welten, Mandat-Heterogenität nicht separat modelliert); nur Drift-Schätzfehler (Σ, Tails, Regime, Cashflow-Fehler nicht variiert); Bewertung unter derselben Modellfamilie. Gültigkeitsbereich: Default `goal_shortfall` mit projizierbarem Anker. Re-Kalibrierung, wenn sich CMA-Methodik, Hausmatrizen, Prior-Metrik (ε) oder Zielfunktion ändern.

## 4. Reproduktion

```bash
# DB_PATH wird ohne Vorgabe auf eine Temp-Datei gelegt; die Live-DB wird abgelehnt.
python tools/house_prior_calibration/kappa_holdout.py run A_ausg_spar docs/planning/2026-10-18-house-prior-kappa-calibration/holdout
# … je Mandat (parallelisierbar, ~15 min je Mandat) …
python tools/house_prior_calibration/kappa_holdout.py summarize docs/planning/2026-10-18-house-prior-kappa-calibration/holdout
```

Deterministisch innerhalb eines Bewertungsjahres (Zieldaten kalenderjahr-relativ; `VALUATION_YEAR` im Summary), Threads je BLAS = 1. Kontrolle: Mandat B erneut gerechnet → JSONL byte-identisch (SHA-256 wie im Summary).

## 5. Status und Freigabe

`HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS = "experimental_tuned_holdout_checked"`: getunt (post hoc) und auf unberührten Welten nach vorab festgelegter Regel bestätigt. Die Modellowner-Freigabe (Gültigkeitsbereich, Re-Kalibrierungstrigger, Sensitivität gegen Σ-/Tail-/Regimefehler) steht aus; bis dahin ist κ_H kein belegter CIO-Parameter im Sinne einer Model Card.
