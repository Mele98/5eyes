# ADR-015: Haus-Prior v1 – Freigabe von kappa_H = 300

- **Status:** Accepted, provisional. Vorläufig in Gebrauch; die Produktivfreigabe durch `<FREIGABE_OWNER>` steht aus, siehe Freigabevermerk.
- **Datum:** 2026-11-02
- **Sprint:** Audit 2026-11, Welle 0, Paket P12 (Entscheid AA-4, Lücke L21)

## Kontext

Seit HOUSE-PRIOR-001 verankert der Optimierer die SAA an der Hausmatrix.
Er löst je Bag

    w_b = argmin_w  G_b(w) + P_pref(w) + kappa_H * (w - w_H)' (Sigma + eps I) (w - w_H)

Dabei ist `G` die Zielebene (Ziel-Fehlbetrag plus Chance-Strafe), `w_H` die zulässig
projizierte Hausquote, `Sigma` die CMA-Kovarianz des Laufs und `eps = 2'500 bps²`
die Ridge der Prior-Metrik (HOUSE-PRIOR-PSD-NULLSPACE-001). Eine Abweichung von
der Hausmatrix kostet ihren Tracking Error. Sind die Ziele mit der Hausmatrix
sicher erreicht, ist das Optimum genau die Hausquote.

Für den Gewichtungsfaktor `kappa_H = 300` gab es eine Herleitung, eine
Kalibrierung und einen Holdout. Im Code stand er aber nur als
`HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS = "experimental_tuned_holdout_checked"`.
Eine Freigabe durch den Modellowner fehlte. Für eine Organisation mit
dokumentierten Methoden (Art. 9 FINIG) ist das eine formelle Lücke: ein
Modellparameter, der jede Allokation bestimmt, muss freigegeben und
versioniert sein. Materiell ist die Lücke unkritisch, weil der Wert geprüft ist.

Im Audit 2026-11 (Befund B2) wurde zudem gemessen: Ohne Zieldruck bleibt die SAA
innerhalb von ±0.5 pp der Hausquote. Kundenvariablen wirken dann kaum.
Der Owner hatte zwei Möglichkeiten: den Wert freigeben oder kappa_H
kundenabhängig machen.

## Entscheidung

1. **Vorläufig in Gebrauch (provisional).** `kappa_H = 300` bleibt als
   **Haus-Prior v1** in Gebrauch. **Auflage vor Produktivfreigabe:**
   Re-Kalibrierung auf v18 mit erweitertem Holdout (mehr Welten bzw. Seeds, um
   den Standardfehler zu senken) oder begründete Anpassung der Regel R1 durch
   den Owner. **Freigabe `<FREIGABE_OWNER>`.**

   Der Wert 300 bleibt, obwohl der Bestätigungs-Holdout auf v18 nach der vorab
   festgelegten Regel `not_confirmed` ergibt (Owner-Entscheid 2026-11-03,
   getroffen von Claude als Owner-Vertretung im Rahmen des autonomen
   Owner-Auftrags). Begründung:
   - R2 (nicht dominiert) ist erfüllt.
   - Die Zielebene ist für κ = 300 deutlich besser als die Hausquote
     (−0.034, se 0.009, rund 3.8 se).
   - R1 ist nur knapp verfehlt: Die einseitige 95-%-Untergrenze liegt bei
     −0.010 pp, der Mittelwert bei +0.202 pp.
   - Ein anderer Wert würde alle Allokationen ändern, ohne bessere Evidenz:
     κ = 100 liegt innerhalb von 1 se, κ = 1000 ist schwächer.

   Ein Status "approved" wäre bei `not_confirmed` eine falsche
   Methodendokumentation (Art. 9 FINIG). Deshalb lautet der Status
   `provisional`.
2. Code-Status:
   - `HOUSE_PRIOR_KAPPA_CALIBRATION_STATUS = "provisional_v1"` (vorher
     `experimental_tuned_holdout_checked`)
   - `HOUSE_PRIOR_PARAMETER_RELEASE = "v1"`
   - `HOUSE_PRIOR_PARAMETER_STATUS = "provisional"`. Ein Wechsel auf
     "approved" erfolgt erst nach erfüllter Auflage und ausgefülltem
     Freigabevermerk.
   - `HOUSE_PRIOR_PARAMETER_ADR` verweist auf dieses ADR.

   Der Algorithmus bleibt separat über `HOUSE_PRIOR_VERSION` und die
   Engine-Version versioniert. Der Status betrifft den Parameter, nicht den
   Algorithmus.
3. kappa_H wird **nicht** kundenabhängig. Ein kundenabhängiges kappa wäre ein
   weiterer frei getunter Parameter ohne Validierungsdaten. Kleine Abweichungen
   im Monte-Carlo-Rauschen würden dann als Individualität erscheinen.
   Kundenvariablen sollen über fachliche Kanäle wirken: Feinscore (AA-2),
   Kosten (AA-3) und Eigenheim (AA-6).
4. Offenlegung: Der Audit-Block `resampling.house_prior` und die Modellbasis
   weisen die Abweichung des Ergebnisses je Anlageklasse aus, und zwar in zwei
   Feldern:
   - `deviation_vs_house_bps` misst gegen die projizierte Hausquote, also gegen
     den Anker des Priors.
   - `deviation_vs_house_raw_bps` misst gegen die rohe Hausmatrix-Zielquote.

   Das Reasoning nennt die Abweichung in pp. `prior_metric` enthält
   `kappa_calibration_status`, `kappa_release` und `kappa_release_adr`.

## Herleitung und Kalibrierung

Quelle ist `git log --follow` auf `ares-backend/services/optimizer/house_prior.py`.
Ohne `--follow` zeigt der aktuelle Pfad nur den Rebranding-Commit. git blame
liefert die Zeilen `HOUSE_PRIOR_KAPPA` und `..._CALIBRATION_STATUS`.

| Commit | Datum | Inhalt |
|---|---|---|
| `6d11f8ac` (#640) | 2026-10-18 | HOUSE-PRIOR-001: Prior statt binärem Signifikanzschalter (Engine v6). `HOUSE_PRIOR_KAPPA = 300.0` als CIO-Entscheid eingeführt |
| `854ee8e9` (#649) | 2026-10-19 | SAA-STAT-V7: Ridge-Metrik, Einheiten-Bootstrap, Status `experimental_tuned_holdout_checked`, Kalibrierungspaket commitgebunden |
| `7fab6168` (#695) | 2026-10-24 | Kalibrierungsskripte mit pfadunabhängigem Live-DB-Wächter (keine fachliche Änderung) |
| `d1ca3f99` (#737) | 2026-10-25 | Zielhierarchie in allen Modi (Engine v15): ändert die Default-Zielfunktion (objective/solver). In `house_prior.py` nur der Docstring (Tiebreak heisst jetzt Risikoterm). Fachlich relevant für die Gültigkeit des Holdouts, siehe unten |

- **Design und Experiment:** `docs/planning/2026-10-18-house-prior-v6.md`.
  - Ausgangslage Engine v5: Bei +1 % Zielbetrag sprang die Allokation um bis zu
    20.9 pp Turnover. Die Aktienquote streute über Seeds bis 7.4 pp.
  - Mit Prior: Seed-σ der Aktienquote ≤ 0.13 pp. Der maximale Sprung je 2 %
    Zielbetrag fiel von 22.2 auf 4.0 pp.
- **Tuning:** Raster κ ∈ {10, 30, 100, 300, 1000, 3000} mit Schätzfehler-Test.
  Die Engine sieht μ̂ = μ + Lz/√20, bewertet wird unter der wahren CMA:
  150 Welten aus 5 Referenzmandaten.
  - κ = 300: ΔP(Ziel) +1.31 pp gegen v5 (se 0.18).
  - κ = 100 bis 1000 liegen innerhalb von 1 se.
  - Die Auswahl war post hoc.
- **Holdout** mit vorab festgelegter Regel auf unberührten Welten. Quellen:
  `tools/house_prior_calibration/kappa_holdout.py` und
  `docs/planning/2026-10-18-house-prior-kappa-calibration.md` §3.
  - Engine v7, 150 Welten.
  - κ = 300: ΔP(Ziel) gegen die reine Hausquote +0.307 pp (se 0.070).
  - R1 (kein Schaden): Untergrenze +0.192 pp > 0, erfüllt.
  - R2 (nicht dominiert gegen 100/1000): erfüllt.
  - Entscheid: `confirmed`.
- **Engine-Stand:** Tuning und Holdout liefen auf `saa_resampled_v5` bzw.
  `saa_resampled_v7`. Produktiv läuft `saa_resampled_v18` (`OPTIMIZER_ENGINE_VERSION`).
  Dazwischen hat unter anderem #737 die Zielhierarchie im Default geändert. Nach
  dem eigenen Release-Gate verlangt das einen neuen Holdout.
- **Bestätigungs-Holdout auf v18** (2026-11-03, vorbereitet durch Claude,
  Codex-Nachprüfung offen). Unverändertes Werkzeug mit vorab festgelegter Regel
  und denselben Seeds und Welten wie der v7-Holdout. Bewertungsjahr 2026,
  seriell, BLAS-Threads 1, isolierte Umgebung, Windows. Rohdaten und Zusammenfassung:
  `docs/planning/2026-10-18-house-prior-kappa-calibration/holdout-v18/`. Alle
  450 Läufe tragen `engine_version = saa_resampled_v18`.

  ```bash
  # je Mandat A_ausg_spar B_kons_entn C_wachs_entn D_wachs_spar E_ausg_entn (je ~5 min):
  python tools/house_prior_calibration/kappa_holdout.py run <MANDAT> <OUT_DIR>
  python tools/house_prior_calibration/kappa_holdout.py summarize <OUT_DIR>
  ```

  | κ_H | mean ΔP(Ziel) vs. Haus | se | Welten besser / schlechter | mean ΔZielebene | se |
  |---|---|---|---|---|---|
  | 100 | +0.219 pp | 0.136 | 67.3 % / 31.3 % | −0.0343 | 0.0092 |
  | **300** | **+0.202 pp** | 0.128 | 68.7 % / 30.0 % | −0.0338 | 0.0089 |
  | 1000 | +0.131 pp | 0.135 | 64.0 % / 32.0 % | −0.0319 | 0.0087 |

  - R1 (kein Schaden gegenüber der Hausquote): Die einseitige
    95-%-Untergrenze von ΔP(κ = 300) liegt bei **−0.010 pp**. Damit ist R1
    **nicht erfüllt**, wenn auch knapp. Der Mittelwert bleibt positiv, die
    Streuung ist aber fast doppelt so gross wie auf v7 (se 0.128 statt 0.070).
  - R2 (nicht dominiert): erfüllt. Gegen 100: −0.017 pp (se 0.029). Gegen 1000:
    +0.071 pp (se 0.024).
  - Die Zielebene (Fehlbetrag plus Chance-Strafe) ist für alle drei κ deutlich
    besser als die Hausquote: −0.034, also rund 3.8 se.
  - **Entscheid nach der vorab festgelegten Regel: `not_confirmed`.** Die Regel
    sieht dann keine automatische Änderung vor; der Modellowner entscheidet.
    Der Wert 300 bleibt unverändert. Ein anderer κ ist nicht besser belegt:
    100 liegt innerhalb von 1 se, 1000 ist schwächer.
  - **Folge:** Status `provisional_v1`, siehe Entscheidung Punkt 1. Die
    Auflage vor der Produktivfreigabe ist ein Release-Gate: entweder ein
    erweiterter Holdout auf v18 oder eine begründete Anpassung von R1 durch
    `<FREIGABE_OWNER>`.
- **Seed-Stabilität im Produktivpfad** (Audit 2026-11): Die Aktienquote lag vor
  dem Prior je nach Seed zwischen 63 und 75 %. Mit dem Prior beträgt die
  Spannweite 0.34 pp.

## Wirkung

- Ohne Zieldruck (Gradient der Zielebene an der Hausquote = 0) publiziert der
  Optimierer die Hausquote. Die Solver-Toleranz
  `HOUSE_ANCHOR_NUMERICAL_TOLERANCE_BPS` beträgt **1 bp** je Anlageklasse. Liegt
  das Ergebnis innerhalb dieser Toleranz, wird exakt der Anker publiziert.
- Die ±0.5 pp stammen aus der Messung im Audit 01/B2. Dort galten sie für alle
  Fälle, die nicht unter Druck stehen. Sie sind eine obere Schranke und gehen
  nicht auf die Solver-Toleranz zurück. Reproduzierbar gemessen mit
  `ares-backend/tests/test_house_prior_no_pressure_deviation.py` (pytest
  `-s` druckt die Tabelle). Grundlage: Default-Hausmatrix, Profile 1–10,
  CHF 500'000, 12 Jahre, ohne Cashflows. Gemessen wurde gegen die projizierte
  Hausquote:

  | Fall | max. Abweichung je Klasse | Test-Schranke |
  |---|---|---|
  | ohne Ziele, Profile 1–10 | 2 bp (Profile 1–2), sonst 0 bp | 5 bp |
  | Ziel sicher (20 % des Vermögens, P = 1), Profile 1–10 | 2 bp (Profile 1–2), sonst 0 bp | 5 bp |
  | Gegenprobe: Entnahmemandat E, Ziel fast sicher (P ≈ 0.998) | 610 bp | > 50 bp |

  - Die 1–2 bp über der Toleranz stammen aus dem Bag-Mittel des Optimierers
    (SLSQP-Rest). Zieldruck ist nicht die Ursache.
  - Ergänzende Einzelmessung, lokal (Windows): Bei einem Ziel von 40 % des
    Vermögens wird gerundet P = 1 ausgewiesen, trotzdem kommen bis 38 bp
    (Profil 9) zustande. Bei Profil 10 (P = 0.998) sind es 55 bp. "Fast
    sicher" ist also nicht dasselbe wie "ohne Zieldruck". Die Chance-Strafe
    wirkt schon vorher.
  - Gegen die **rohe** Hausmatrix-Zielquote weicht bereits der Anker ab (Profile
    9–10: 100 bp), weil er auf die zulässige Menge projiziert wird. Das ist keine
    Optimierer-Abweichung und wird getrennt als `deviation_vs_house_raw_bps`
    ausgewiesen.
  - Ab diesem Release belegen `deviation_vs_house_bps` und
    `deviation_vs_house_raw_bps` die Abweichung für jeden Lauf.
- Mit Zieldruck nimmt der Optimierer 1 % Tracking Error nur dann, wenn sich die
  Zielebene um mindestens `kappa_H · (1 %)² = 0.03` verbessert.
- Mit diesem Status ändert sich keine Allokation. Die Golden-Snapshots
  (`tests/fixtures/golden_ch_recommendations/`) bleiben bitgleich. Neu sind nur
  die Offenlegungsfelder und ein Reasoning-Satz.

## Grenzen

- Kalibriert auf 5 Referenzmandaten mit 150 Welten. Die Heterogenität der Mandate
  ist nicht separat modelliert.
- Variiert wurde nur der Drift-Schätzfehler. Fehler in Σ, Tails, Regimen und
  Cashflows wurden nicht variiert. Bewertet wurde innerhalb derselben
  Modellfamilie.
- Der Wert gilt für die Default-Zielfunktion `goal_shortfall` mit projizierbarem
  Anker. Die Risikomass-Varianten (min_volatility, max_drawdown, cvar_return,
  max_return) verwenden den Prior nicht. Sie bräuchten eine eigene Kalibrierung.
- Die Brutto-Simulation bleibt bis P2b (Netto-Simulation) bestehen. Eine
  Rekalibrierung nach P2b ist Pflicht, siehe Release-Gate.
- κ = 300 und κ = 1000 lassen sich im Holdout nicht trennen (1.4 se). Die Wahl
  ist robust, aber nicht eindeutig optimal.

## Release-Gate für Änderungen

Jede Änderung des Werts, der Prior-Metrik (eps) oder der Zielfunktion im
Default verlangt vor dem Merge drei Dinge:

1. einen neuen Holdout auf unberührten Welten mit vorab festgelegter Regel, in
   derselben Form wie `kappa_holdout.py`;
2. Seed-Stabilität: Spannweite der Aktienquote ≤ 0.5 pp;
3. keine Verschlechterung der Zielerreichung gegen die reine Hausquote im
   Holdout (einseitige 95-%-Untergrenze von ΔP(Ziel) > 0).

Dazu gehören ein neuer Release-Stand (`HOUSE_PRIOR_PARAMETER_RELEASE`), ein
Nachtrag oder Nachfolge-ADR sowie ein eigener Golden-Snapshot-Commit mit
Vorher/Nachher-Tabelle.

## Review-Turnus

- **Ordentlich:** jährlich, zusammen mit der CMA-Freigabe des Anlagekomitees.
  Geprüft werden der Holdout-Befund und die Seed-Stabilität auf den aktuellen
  Referenzmandaten.
- **Ausserordentlich** bei jedem Wechsel von CMA-Methodik, Hausmatrizen,
  Prior-Metrik oder Default-Zielfunktion sowie bei der Aktivierung der
  Netto-Simulation (P2b).
- **Verantwortlich:** Modellowner (CIO).
- Die Prüfung jedes SHA durch Codex ist eine Entwicklungskontrolle. Eine
  unabhängige Modellvalidierung ersetzt sie nicht. Für die
  Vermögensverwaltung gilt Art. 21 FINIG (Risikomanagement, IKS) **[prüft Compliance]**.

## Freigabevermerk

| Feld | Eintrag |
|---|---|
| Freigegeben durch | `<FREIGABE_OWNER>` (Name und Funktion offen, nicht ausgefüllt) |
| Datum | offen (Vorbereitung: 2026-11-03) |
| Referenz | Audit 2026-11, Dok. 10, Entscheid AA-4 und Lücke L21. Pruefrunde #857 (Dok. 86). Holdout v7 (`holdout/`) und Bestätigungs-Holdout v18 (`holdout-v18/`, `not_confirmed`) |
| Vorbereitet durch | Claude, 2026-11-03. Codex-Nachprüfung offen |
| Status | `provisional_v1`: vorläufig in Gebrauch. Owner-Entscheid 2026-11-03 (Claude als Owner-Vertretung, autonomer Owner-Auftrag): Wert 300 bleibt, Status nicht "approved" |
| Auflage vor Produktivfreigabe | Re-Kalibrierung auf v18 mit erweitertem Holdout (mehr Welten bzw. Seeds) oder begründete Anpassung von R1 durch den Owner |

## Konsequenzen

- L21 ist vorbereitet: Der Parameter ist versioniert, begründet und ausgewiesen.
  Formell geschlossen ist L21 erst mit dem ausgefüllten Freigabevermerk und dem
  Owner-Entscheid zur v18-Auflage.
- Neue Allokationen tragen in der Modellbasis `provisional_v1`. Bereits
  gespeicherte Allokationen behalten ihren gespeicherten Status, weil die
  Modellbasis wortgetreu abgespielt wird.
- **Release-Hinweis (N-857-4).** Das erste Regenerate nach dem Deploy erzeugt
  bei unveränderten Eingaben einmalig eine neue Allokationsversion je
  stochastischem Mandat. Bereits zertifizierte Final-Empfehlungen können dabei
  verwaisen und mit 409 "basiert nicht auf der aktuellen Soll-Allokation"
  abgewiesen werden.
  - Ursache: Der geänderte Status (`provisional_v1`), `kappa_release` und
    `kappa_release_adr` in `prior_metric` sowie die Abweichungsfelder liegen in
    der Modellbasis und damit im `allocation_context_hash`.
    `REGENERATE-IDEMPOTENT-001` vergleicht diesen Hash.
  - Vermeiden liesse sich das nicht, ohne die Evidence-Integrität zu schwächen.
    Der Freigabestatus ist Teil der Modellbeschreibung, die der Hash bindet.
    Nimmt man ihn heraus, wäre er unsigniert und veränderbar.
  - Nur die Abweichungsfelder liessen sich aus den gebundenen Feldern
    (`final_bps`, `house_anchor_*`) ableiten. Sie allein herauszunehmen,
    verhindert die Hash-Änderung aber nicht, weil der Status-String sie
    ohnehin auslöst. Ausserdem müsste dafür die Hashbildung in
    `portfolio_engine_allocation_integrity` geändert werden.
  - Entscheid: Die Hash-Änderung wird belassen und im Release dokumentiert.
    Vorgehen: vor dem Deploy offene Final-Empfehlungen abschliessen oder nach
    dem Regenerate neu zertifizieren.
  - Dasselbe Muster gilt für jede Erweiterung der Modellbasis.
- Die Spannung zur Direktive "alle Kundenvariablen" (B2) bleibt bewusst
  bestehen. Gelöst wird sie über fachliche Kanäle, nicht über kappa.

## Code-Referenzen

- `ares-backend/services/optimizer/house_prior.py`: Konstanten,
  `prior_metric_audit`, `house_deviation_bps`, `house_deviation_sentence`
- `ares-backend/services/optimizer/solver.py`: `_house_prior_disclosure`
- `ares-backend/services/optimizer/resampling.py`: `_HOUSE_PRIOR_BASIS_FIELDS`
- `ares-backend/tests/test_house_prior_approval.py`
