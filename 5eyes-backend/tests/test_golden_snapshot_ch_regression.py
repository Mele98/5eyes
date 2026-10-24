"""Golden-Snapshot-Baseline fuer den Schweiz-Pfad (jurisdiction IS NULL / "CH").

Die Baseline friert den fachlich freigegebenen stochastischen Kern inklusive
aktiver Methode/Status ein. Damit darf eine kuenftige Aenderung weder unbemerkt
auf die House Matrix zurueckfallen noch Ziel-, Suballokations- oder
Implementierungsgewichte verschieben.

Vorgehen: fuer 6 Kombinationen aus Risikoprofil-Score (unterschiedliche
_risk_score_bucket-Buckets) und Anlagepraeferenzen (equitiesGeo-Varianten,
chfOnly) wird ein frisches Test-Mandat geseedet, `generate_target_allocation`
und `generate_recommendation_run` End-to-End aufgerufen und das Ergebnis gegen
ein eingefrorenes JSON-Fixture unter tests/fixtures/golden_ch_recommendations/
verglichen (exakte Gleichheit, kein "similar enough").

Aus dem Vergleich ausgeschlossene/normalisierte Felder (nicht deterministisch
ueber getrennte Testlaeufe/DBs hinweg) -- Begruendung pro Feld:

- Alle Primary-/Foreign-Key-IDs (Mandate/Client/Assessment/Policy/CMA/Product/
  Position/Run-IDs) sowie created_at/updated_at/assessed_at/set_at-Zeitstempel:
  klassische Laufzeit-Artefakte (new_uuid()/_now()), nie Teil der Fachlogik.
  Wir bauen daher gezielt ein reduziertes, benanntes Snapshot-Dict aus den
  Ergebnis-Dicts von generate_target_allocation()/generate_recommendation_run()
  statt die rohen ORM-Objekte/Positions-Payloads zu dumpen.
- Monte-Carlo-abgeleitete Implementierungskennzahlen (TargetAllocation.mc_*,
  result["monte_carlo"]/result["goal_analysis"]): Sie besitzen eigene, breite
  statistische Vertrags-Suites und gehoeren nicht in diesen kompakten
  Produkt-/Gewichts-Snapshot. Die CMA-ID wird hier dennoch explizit fixiert,
  weil sie auch den aktiven stochastischen Entscheidungs-Seed bindet. Eingefroren
  werden Methode/Status/Engine-Version, targets_bps, bands_bps,
  risky_fraction_bps, limiting_factor, erwartete Momente sowie die komplette
  Produktselektion und -gewichtung.
- live_rebalancing / reasoning-Freitext: bewusst nicht Teil des Snapshots
  (siehe DEVIATIONS im Task-Report) -- Fokus liegt spec-gemaess auf
  sub_allocations, Produktgewichten und Gesamtsummen.

Sanity-Check (siehe Kommentar `SANITY_CHECK_INSTRUCTIONS` unten): dieser Test
wurde manuell verifiziert, dass er ROT wird, wenn man den CH-Default
"Schweiz Fokus" (equities_geo-Default in _build_sub_allocations) lokal
aendert. Die testweise Aenderung wurde NICHT committet.

WICHTIG (2026-08-19): Diese Fixtures sind SLSQP-Konvergenzergebnisse und
duerfen NUR auf dem Linux-CI-Runner regeneriert werden, nie lokal unter
Windows. Trotz exakt gepinnter numpy/scipy-Versionen (requirements.txt)
liefert der Solver auf Windows minimal andere Werte als auf Linux
(vermutlich unterschiedliche BLAS/LAPACK-Backends je Wheel-Plattform,
z.B. expected_return_bps 396 vs. 397) -- lokal unter Windows neu
eingefrorene Fixtures faellen daher reproduzierbar in CI durch. Zum
Regenerieren: temporaeren CI-Schritt einbauen, der _build_ch_snapshot()
fuer alle COMBOS aufruft und das Ergebnis als Artefakt hochlaedt (siehe
Git-Historie des Merge-Commits fuer ein Beispiel), dann das Artefakt
herunterladen und in tests/fixtures/golden_ch_recommendations/ kopieren.

Nachtrag (2026-09-16): trotz #425 (Thread-Pinning) UND #445
(OPENBLAS_CORETYPE=Haswell, erzwingt einen einzigen BLAS-Mikroarchitektur-
Kernel statt DYNAMIC_ARCH-Laufzeitauswahl) bleibt eine kleine residuale
CI-Flakiness auf genau `bucket5_ausgewogen_default_prefs` bestehen (kleine
bps-Differenzen, z.B. expected_return_bps 395 vs. 397) -- beide Fixes
reduzieren die Haeufigkeit nachweislich (mehrfach beobachtet gruen mit
#445), eliminieren sie aber nicht vollstaendig. Die genaue verbleibende
Quelle ist nicht abschliessend geklaert (numpy und scipy vendorn je eine
EIGENE OpenBLAS-Instanz -- scipy_openblas32 vs. scipy_openblas64 -- beide
ebenfalls DYNAMIC_ARCH; ob OPENBLAS_CORETYPE zuverlaessig auf beide wirkt,
ist nicht verifiziert). test_golden_ch_snapshot_matches_frozen_fixture
bekam deshalb einen bounded Retry (siehe @pytest.mark.flaky unten).

Nachtrag (2026-10-06): Der bounded Retry (#2026-09-16) hat das Problem
NICHT geloest -- er beruht auf einer falschen Annahme. Ueber mehrere
reale CI-Laeufe verifiziert: PYTHONHASHSEED-Variation aendert das
Ergebnis NICHT (6 verschiedene Seeds, identisches Resultat); dagegen
aendert OPENBLAS_CORETYPE das Ergebnis NACHWEISLICH und DETERMINISTISCH
(lokal reproduziert: "Haswell"/"Sandybridge"/"Zen" liefern den einen
Zahlensatz, "Nehalem"/"Prescott" den anderen -- exakt deckungsgleich mit
den beiden in CI beobachteten Auspraegungen). Die BLAS-Kernel-Auswahl
wird EINMAL PRO PROZESS beim ersten BLAS-Aufruf getroffen und bleibt
danach fuer die gesamte Prozesslaufzeit fix -- ein `pytest.mark.flaky`-
Retry laeuft im SELBEN Prozess und wiederholt deshalb garantiert densel-
ben (ggf. falschen) Kernel, kann also das eigentliche Problem strukturell
nie abfangen. Da der CI-Workflow OPENBLAS_CORETYPE=Haswell bereits fuer
BEIDE vendorten OpenBLAS-Instanzen setzt (siehe .github/workflows/test.yml)
und dies offenbar nicht fuer beide zuverlaessig wirkt, UND ein weiteres
env-var-Experiment ohne Linux-CI-Zugriff nicht verifizierbar waere, wird
das Problem stattdessen auf Test-Ebene korrekt eingeordnet: ein exakter
Bit-Vergleich auf Werten, die integraler Bestandteil eines iterativen
SLSQP-Solvers sind, ist eine UEBERSPEZIFIZIERTE Erwartung -- die fach-
liche Anforderung ist "Gewichte/Methode/Produktauswahl duerfen sich nicht
unbemerkt veraendern", NICHT "jede CPU/BLAS-Kombination muss bit-identische
Rundungsfehler der 15. Nachkommastelle produzieren". Der Vergleich prueft
daher ab sofort weiterhin EXAKT (Produktauswahl, Reihenfolge, Methode,
Status, engine_version, limiting_factor, Anzahl Positionen/Suballokationen,
alle Nicht-Solver-Felder), erlaubt aber eine empirisch hergeleitete,
schmale Toleranz (siehe _BPS_TOLERANCE/_RAPPEN_TOLERANCE unten) exakt auf
den Feldern, die im lokalen Haswell-vs-Nehalem-Repro nachweislich divergierten
(target_weight_bps, target_amount_rappen, expected_return_bps,
expected_volatility_bps, risky_fraction_bps, targets_bps.*, sowie der
CHF-Betrag in implementation_steps) -- siehe _assert_ch_snapshot_matches().
Jede andere Abweichung (Struktur, Reihenfolge, Produktauswahl, Methode,
oder eine Abweichung GROESSER als die Toleranz) bleibt ein echter Testfehler.

Nachtrag (2026-10-16, SAA-RESAMPLED-STABILITY-001): alle sechs Fixtures neu
eingefroren, weil sich die Methode bewusst geaendert hat (Inhalts-Seed,
Resampled Efficiency ueber 40 Bags, Signifikanztest gegen die Hausmatrix).
Ein Linux-Runner stand dafuer nicht zur Verfuegung (die Branch loest ohne PR
keinen CI-Lauf aus). Ersatz-Kontrolle: lokal mit OMP/OPENBLAS/MKL_NUM_THREADS=1
je einmal unter OPENBLAS_CORETYPE=Haswell UND =Nehalem erzeugt -- genau die
beiden Kernel-Familien, die frueher die zwei CI-Auspraegungen lieferten. Alle
sechs Dateien kamen byte-identisch zurueck (das Bag-Mittel glaettet das
SLSQP-Rundungsrauschen). Begruendung je Datei:
docs/planning/2026-10-14-saa-stability-resampling.md.

Nachtrag (2026-10-17, SAA-SIGNIFICANCE-LEXICOGRAPHIC-001 /
SAA-SEED-FLOAT-ROBUST-001): die am 16.10. eingefrorenen Fixtures fielen am
17.10. in CI durch (bucket3/5/7/equities_global; chfonly lief wegen
--maxfail=5 gar nicht mehr). Keine Plattform-Frage: lokal unter Windows kamen
am 17.10. exakt dieselben Werte wie auf dem Linux-Runner. Wurzel 1: das
Seeding unten setzte die Zieldaten auf "heute + N*365 Tage", der Inhalts-Seed
hasht die Zieldaten -> jeder Kalendertag zog andere Bag-Wuerfel (Beleg:
date.today() im Seeding auf den 16.10. gestellt -> alle Fixtures wieder
gruen). Die Daten sind jetzt kalenderjahr-relativ mit festem Monat/Tag, und
der Seed hasht sie relativ zum Bewertungsjahr. Wurzel 2 (Methodik): bei
Score 7 kippte der Hausmatrix-Signifikanzentscheid je nach Wuerfel (60 % vs.
68 % Aktien), weil die Skalar-Zielfunktion als Differenz zweier Allokationen
nicht monoton ist (Stufe-2-Volatilitaetsterm pro Allokation zugeschaltet);
der Test vergleicht jetzt lexikographisch. Fixtures danach neu eingefroren.

Nachtrag (2026-10-18, OBJECTIVE-NORMALIZATION-001): alle sechs Fixtures neu
eingefroren, weil sich die Zielfunktion bewusst geaendert hat (Tiebreak
immer aktiv und auf W0^2 normiert statt Stufen-Schalter; Chance-Strafe
linear und volumen-normiert statt 1e6 * Defizit^2; Engine
``saa_resampled_v3``). Vorher blieb der Bag-Solver auf diesen Mandaten in
37-40 von 40 Bags auf einem Startpunkt stehen (Zielfunktion ~1e-9, unter
SLSQP-ftol); jetzt entscheidet bei erfuellten Zielen die Volatilitaet.
Zahlen je Datei (Aktien/Obl/Immo/Alt/Liq in bps, erw. Rendite/Vola):
Score 3 0/8903/0/629/468 -> 0/8824/0/676/500 (207/344 -> 206/342);
Score 5 4616/3870/854/413/247 -> 4000/4453/567/680/300 (435/740 -> 398/647);
Score 5 global 4669/3783/891/418/239 -> 4000/4445/622/636/297 (451/776 -> 410/671);
Score 5 CHF/EM 4533/3945/890/382/250 -> 4000/4379/600/721/300 (445/770 -> 410/686);
Score 7 6000/2500/1000/300/200 -> 6000/2312/678/810/200 (501/953 -> 489/959);
Score 9 7500/1500/600/200/200 -> 7500/1387/389/524/200 (559/1171 -> 551/1174).
Kontrolle wie am 16.10.: lokal mit OMP/OPENBLAS/MKL_NUM_THREADS=1 unter
OPENBLAS_CORETYPE=Haswell UND =Nehalem erzeugt; 5 von 6 Dateien
byte-identisch, Score 5 Default weicht um 1 bps (Obl/Immo) bzw. CHF 50 in
einem Umsetzungsschritt ab -- weit innerhalb _BPS_TOLERANCE/_RAPPEN_TOLERANCE.
Eingefroren ist die Haswell-Fassung (CI-Kernel). Begruendung:
docs/planning/2026-10-18-objective-normalization.md.

Nachtrag (2026-10-18, IMPORTANCE-SAMPLING-ESS-001 +
TIEBREAK-PORTFOLIO-VARIANCE-001, Engine ``saa_resampled_v4``): alle sechs
Fixtures neu eingefroren. Importance Sampling als defensive Mischung mit
horizont-skaliertem Shift (Kish-ESS des Hauptwuerfels 14-85 -> ~1'650 von
2'000 Pfaden) und Tiebreak ``kappa * w' Sigma w`` (kappa = 1) statt
``Var(W_T)/W0^2``. Die Bag-Streuung faellt auf 0 (alle 40 Bags landen auf
derselben Bandecke). Aktien/Obl/Immo/Alt/Liq in bps, erw. Rendite/Vola:
Score 3 0/8824/0/676/500 -> 0/8700/0/800/500 (206/342 -> 205/341);
Score 5 4000/4453/567/680/300 -> 4000/4500/503/697/300 (398/647 -> 396/645);
Score 5 global 4000/4445/622/636/297 -> 4000/4500/500/700/300 (410/671 -> 407/668);
Score 5 CHF/EM 4000/4379/600/721/300 -> 4000/4500/500/700/300 (410/686 -> 408/682);
Score 7 6000/2312/678/810/200 -> 6000/2500/536/764/200 (489/959 -> 486/951);
Score 9 7500/1387/389/524/200 -> 7500/1500/300/500/200 (551/1174 -> 550/1169).
Unter OPENBLAS_CORETYPE=Haswell UND =Nehalem erzeugt: alle sechs Dateien
byte-identisch. Begruendung:
docs/planning/2026-10-18-importance-sampling-ess.md.

Nachtrag (2026-10-18, HOUSE-FIRST-SIGNIFICANCE-001, Engine
``saa_resampled_v5``): alle sechs Fixtures neu eingefroren, weil sich die
Methode bewusst geaendert hat (CIO-Entscheid "Hausmatrix, solange die Ziele
mit ihr gleich sicher erreicht sind"). Auf allen sechs Mandaten erreichen
Hausmatrix und Optimierer alle Ziele mit p = 1; der Signifikanztest
entschied bisher allein ueber den deterministischen Varianz-Tiebreak
(p = 0.0025) fuer Eckloesungen. Jetzt entscheidet er auf der Zielebene
(Ziel-Fehlbetrag + Chance-Strafe) -> nicht signifikant -> Hausmatrix.
Aktien/Obl/Immo/Alt/Liq in bps, erw. Rendite/Vola:
Score 3 0/8700/0/800/500 -> 0/9500/0/300/200 (205/341 -> 214/362);
Score 5 4000/4500/503/697/300 -> 4800/3500/1000/500/200 (396/645 -> 446/776);
Score 5 global 4000/4500/500/700/300 -> 4800/3500/1000/500/200 (407/668 -> 459/804);
Score 5 CHF/EM 4000/4500/500/700/300 -> 4800/3500/1000/500/200 (408/682 -> 460/821);
Score 7 6000/2500/536/764/200 -> 6800/1600/800/600/200 (486/951 -> 529/1081);
Score 9 7500/1500/300/500/200 -> 7900/800/700/400/200 (550/1169 -> 577/1245).
Unter OPENBLAS_CORETYPE=Haswell UND =Nehalem (OMP/OPENBLAS/MKL_NUM_THREADS=1)
erzeugt: alle sechs Dateien byte-identisch (die publizierte Quote ist die
projizierte Hausmatrix-Zielquote, kein SLSQP-Konvergenzpunkt); eingefroren
ist die Haswell-Fassung (CI-Kernel). Begruendung und Vorher/Nachher aller
Modi: docs/planning/2026-10-18-importance-sampling-ess.md.

Nachtrag (2026-10-18, HOUSE-PRIOR-001, Engine ``saa_resampled_v6``): die
Hausmatrix ist jetzt Prior im Optimierer (``kappa_H * (w - w_H)' Sigma
(w - w_H)``, kappa_H = 300) statt eines Signifikanzschalters; die Version geht
in den Seed, alle Wuerfel sind neu. Alle sechs Fixtures unter
OPENBLAS_CORETYPE=Haswell UND =Nehalem (OMP/OPENBLAS/MKL_NUM_THREADS=1) neu
erzeugt: beide Laeufe BYTE-IDENTISCH zu den v5-Fixtures, deshalb keine Datei
geaendert. Fachlich erwartet: auf allen sechs Mandaten sind alle Ziele mit
der Hausquote sicher erreicht (p = 1), der Gradient der Zielebene ist dort 0,
und das Optimum des Priors ist exakt die (projizierte) Hausquote (Tracking
Error 0, Entscheid ``house_prior`` /
``identical_to_house_anchor``). Begruendung:
docs/planning/2026-10-18-house-prior-v6.md.

Nachtrag (2026-10-18, Engine ``saa_resampled_v7``, Statistik-Vertraege):
Einheiten-Bootstrap, nullzentrierte p-Werte, B = 999, getrennte Auswahl-/
Final-Wuerfel, Survivor-Schwelle 90 %, Ridge-Prior-Metrik; neue Version im
Seed. Alle sechs Fixtures UNVERAENDERT gegen die neue Engine gruen, keine
Datei geaendert. Fachlich erwartet: die Ziele bleiben mit der Hausquote
sicher erreicht; das Optimum des (Ridge-)Priors ist weiter die projizierte
Hausquote. Eine Restabweichung des SLSQP-Mittels von <= 1 bp je Bucket
(Solver-Toleranz, ``within_solver_tolerance_of_house_anchor``) publiziert
ebenfalls exakt den Anker. Begruendung:
docs/planning/2026-10-18-resampling-statistics-contracts-v7.md.

Nachtrag (2026-10-19, MAXIMIZE-GOAL-001 / GOAL-HARDNESS-DEFAULT-001 /
GOAL-HIERARCHY-001/-002, Engine ``saa_resampled_v8``, auf v7 #649): Haertegrad
standardmaessig, erreichbare harte/primaere Ziele als Stufe 1
(Zielschutz-Schranke G1* + eps, eps = z * SE(Haus - Stufe-1) / h_max). Unter
OPENBLAS_CORETYPE=Haswell UND =Nehalem (OMP/OPENBLAS/MKL_NUM_THREADS=1) neu
erzeugt, beide Laeufe byte-identisch: vier Fixtures unveraendert (Score 3,
alle drei Score-5-Varianten). Geaendert, weil die Pension HART ist (h = 10:
nur ein Zehntel des Monte-Carlo-Rauschens als Erosion zugunsten der
Hausmatrix): Score 7 6800/1600/800/600/200 -> 6734/1674/810/582/200
(529/1081 -> 526/1071 bps, Risikoanteil 64.65 -> 64.22 %), Score 9
7900/800/700/400/200 -> 7799/959/670/372/200 (577/1245 -> 572/1227 bps,
Risikoanteil 69.17 -> 68.36 %). Nachweis der Ursache: mit Haertegrad-Teiler
1 statt 10 (Experiment) ergeben beide exakt die bisherigen Fixtures.
Begruendung: docs/planning/2026-10-18-maximize-goal-and-hardness.md.

Nachtrag (2026-10-19, GOAL-REACHABILITY-CERTIFICATE-001, Engine
``saa_resampled_v9``): Herabstufung nur noch bei zertifizierter
Unerreichbarkeit. Unter Haswell UND Nehalem (Threads = 1) neu erzeugt, beide
byte-identisch. Mit dem v8-Seed (Version erzwungen, Experiment) sind ALLE
sechs Fixtures byte-identisch zu v8 -- die neue Logik aendert hier nichts
(kein Golden-Mandat hat ein Screen-Miss-Ziel). Geaendert nur durch den
neuen Wuerfel (die Engine-Version geht in den Inhalts-Seed; harte Pension,
Stufe-1-Toleranz ein Zehntel des Rauschens): Score 7
6734/1674/810/582/200 -> 6770/1631/800/599/200 (526/1071 -> 528/1077 bps),
Score 9 7799/959/670/372/200 -> 7858/855/697/390/200 (572/1227 -> 575/1238
bps); Score 3 und alle drei Score-5-Varianten unveraendert.

Nachtrag (2026-10-19, GOAL-ATTRIBUTION-CASHFLOW-INVERSION-001 /
GOAL-OPTIMIZATION-PUBLICATION-SCOPE-SPLIT-001, Engine ``saa_resampled_v10``):
Prioritaets-Scopes per direktem Replay, Zielterme auf dem priorisierten
Scope. Unter Haswell UND Nehalem (Threads = 1) neu erzeugt, beide
byte-identisch. Mit dem v9-Seed (Version erzwungen, Experiment) sind ALLE
sechs Fixtures byte-identisch zu v9 -- die Scope-Logik aendert hier nichts.
Geaendert nur durch den neuen Wuerfel (Version im Inhalts-Seed): Score 7
6770/1631/800/599/200 -> 6768/1636/804/592/200 (528/1077 -> 528/1076 bps,
Risikoanteil 64.48 -> 64.44 %), Score 9 7858/855/697/390/200 ->
7821/912/704/363/200 (575/1238 -> 574/1232 bps, Risikoanteil 68.87 ->
68.54 %); Score 3 und alle drei Score-5-Varianten unveraendert.

Nachtrag (2026-10-21, GOAL-REVISION-DECISION-001, Engine
``saa_resampled_v11``): keine automatische Herabstufung mehr (nur per
Berater-Entscheidung GoalRevisionDecisionV1). Unter Haswell UND Nehalem
(Threads = 1) neu erzeugt, beide byte-identisch. Mit dem v10-Seed (Version
erzwungen, Experiment) sind ALLE sechs Fixtures byte-identisch zu v10 -- in
keiner Golden-Kombination wurde ein Ziel herabgestuft. Geaendert nur durch
den neuen Wuerfel (Version im Inhalts-Seed): Score 7
6768/1636/804/592/200 -> 6788/1613/797/602/200, Score 9
7821/912/704/363/200 -> 7819/900/700/381/200; Score 3 und alle drei
Score-5-Varianten unveraendert.

Nachtrag (2026-10-23, VARIANT-GOAL-PRESERVATION-GATE-001, Engine
``saa_resampled_v12`` = v11 plus Goal-Preservation-Gate): das Gate wirkt nur
in den Risikomass-Varianten; der Default-Pfad (House-Prior) ist unveraendert.
Auf dem Linux-CI-Runner (temporaerer Workflow, Threads = 1) unter Haswell UND
Nehalem neu erzeugt, beide byte-identisch. Geaendert nur durch den neuen
Wuerfel (Version im Inhalts-Seed), Aktien/Obligationen/Immobilien/
Alternative/Liquiditaet v11 -> v12: Score 7 6788/1613/797/602/200 ->
6768/1636/808/588/200 (Vola 1080 -> 1076 bps, Risikoanteil 64.59 ->
64.43 %), Score 9 7819/900/700/381/200 -> 7832/885/702/381/200 (Vola
1232 -> 1234 bps, Risikoanteil 68.62 -> 68.70 %); Score 3 und alle drei
Score-5-Varianten unveraendert.

Nachtrag (2026-10-24, SUB-SPLIT-ROUNDING-001, Engine ``saa_resampled_v13``):
eine kanonische Largest-Remainder-Aufteilung fuer Builder, Kanonisierung und
Materialisierung. Mit dem v12-Seed waren alle sechs Fixtures byte-identisch
(lokal erzeugt, gleich den eingecheckten Dateien bis auf Zeilenenden). Auf
dem Linux-CI-Runner (temporaerer Workflow, Threads = 1) unter Haswell UND
Nehalem neu erzeugt, beide byte-identisch. Geaendert nur durch den neuen
Wuerfel (Version im Inhalts-Seed), Aktien/Obligationen/Immobilien/
Alternative/Liquiditaet v12 -> v13: Score 7 6768/1636/808/588/200 ->
6780/1611/805/604/200 (Vola 1076 -> 1079 bps, Risikoanteil 64.43 ->
64.58 %), Score 9 7832/885/702/381/200 -> 7810/940/675/375/200 (Rendite
574 -> 573 bps, Vola 1234 -> 1229 bps, Risikoanteil 68.70 -> 68.45 %);
Score 3 und alle drei Score-5-Varianten unveraendert.

Nachtrag (2026-10-24, RESAMPLING-SUCCESS-SURVIVOR-BIAS-001 +
SIGNIFICANCE-MULTIPLICITY-001, Engine ``saa_resampled_v14``): Ausfall-
Schranke als identifizierter Bereich mit fail-closed, Holm/Bonferroni in den
Varianten. Fix-Effekt 0: mit erzwungenem v13-Seed alle sechs Fixtures
byte-identisch (Linux-CI, Haswell und Nehalem; alle Combos 40/40 Bags,
Default-Modus ohne Variantentest). Seed-Effekt (neuer Wuerfel durch die
Version im Inhalts-Seed), v13 -> v14, Haswell = Nehalem byte-identisch:
Score 7 6780/1611/805/604/200 -> 6774/1629/807/590/200 (Vola 1079 -> 1077
bps, Risikoanteil 64.58 -> 64.47 %), Score 9 7810/940/675/375/200 ->
7787/966/684/363/200 (Rendite 573 -> 572 bps, Vola 1229 -> 1225 bps,
Risikoanteil 68.45 -> 68.29 %); Score 3 und alle drei Score-5-Varianten
unveraendert.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from sqlalchemy.orm import configure_mappers

from database import Base
# Vollstaendiges Modell-Set importieren (analog test_optimizer_shadow_mode.py),
# damit Base.metadata.create_all() unabhaengig von der Testreihenfolge/Isolation
# alle per ForeignKey referenzierten Tabellen kennt (z.B. clients.tenant_id ->
# tenants.id). Ohne diesen Import schlaegt create_all() fehl, wenn diese Datei
# als einzige/erste Testdatei eines pytest-Laufs geladen wird.
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.risk_scoring import profile_for_score_x10

FIXTURES_DIR = TESTS_ROOT / "fixtures" / "golden_ch_recommendations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'golden_ch_snapshot.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ---------------------------------------------------------------------------
# 6 Kombinationen aus Risikoprofil-Score (-> unterschiedliche
# _risk_score_bucket-Buckets 1..10) und Anlagepraeferenzen.
# ---------------------------------------------------------------------------
COMBOS: list[dict] = [
    {"name": "bucket3_defensiv_default_prefs", "score_x10": 30, "preferences": None},
    {"name": "bucket5_ausgewogen_default_prefs", "score_x10": 50, "preferences": None},
    {"name": "bucket7_wachstum_default_prefs", "score_x10": 70, "preferences": None},
    {"name": "bucket9_dynamisch_default_prefs", "score_x10": 90, "preferences": None},
    {
        "name": "bucket5_ausgewogen_equities_global",
        "score_x10": 50,
        "preferences": {"assetClasses": {"equitiesGeo": "Global"}},
    },
    {
        "name": "bucket5_ausgewogen_chfonly_em_focus",
        "score_x10": 50,
        "preferences": {
            "geo": {"chfOnly": True},
            "assetClasses": {"equitiesGeo": "Schwellenlaender"},
        },
    },
]


def _seed_ch_mandate(session_factory, *, suffix: str, score_x10: int) -> tuple[str, str, str, str]:
    """Seedet ein realistisches CH-Mandat (Depot 500k + Sparen + Pension-/
    Vermoegensziel) mit deterministischen IDs (basierend auf `suffix`, keine
    uuid4()) und einem parametrisierbaren Risikoprofil-Score, analog zum
    Seeding-Pattern in tests/test_optimizer_shadow_mode.py::_seed_realistic_mandate.
    """
    advisor_id = f"golden-adv-{suffix}"
    cid = f"golden-client-{suffix}"
    mid = f"golden-mandate-{suffix}"
    aid = f"golden-assessment-{suffix}"
    gid_pension = f"golden-goal-pension-{suffix}"
    gid_wealth = f"golden-goal-wealth-{suffix}"
    now = _now()
    # SAA-SEED-FLOAT-ROBUST-001 (2026-10-17): Zieldaten KALENDERJAHR-relativ
    # mit festem Monat/Tag, nicht "heute + N*365 Tage". Die Goal-Daten gehen
    # (relativ zum Bewertungsjahr) in den Inhalts-Seed ein; mit tagesrelativen
    # Daten zog jeder Kalendertag einen anderen Wuerfel -- die am 16.10.
    # eingefrorenen Fixtures fielen am 17.10. in CI durch (reproduziert durch
    # blosses Umstellen von date.today() im Seeding). So bleiben Seed UND die
    # Kalenderjahr-Achse der Engine (date.today().year) ueber das ganze Jahr
    # und ueber Jahreswechsel hinweg gleich.
    base_year = date.today().year
    pension_start = date(base_year + 5, 6, 30).isoformat()
    pension_end = date(base_year + 30, 6, 30).isoformat()
    wealth_target_date = date(base_year + 10, 6, 30).isoformat()

    with session_factory() as s:
        s.add(User(
            id=advisor_id, username=f"golden-adv-{suffix}", password_hash="h",
            full_name="Golden Advisor", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-GOLD-{suffix}",
            first_name="Golden", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-GOLD-{suffix}",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=f"golden-pos-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"golden-cf-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=gid_pension, mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=gid_wealth, mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Eigenheim Anzahlung", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_wealth_rappen=300_000_00,
            target_date=wealth_target_date,
            is_ongoing=0, hardness="Primaer",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="Dynamisch",
            risk_capacity_score_x10=100,
            investment_horizon_years=15, investment_horizon_label="Mehr als 12 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=80,
            final_score_x10=80, final_profile="Wachstumsorientiert",
            # Golden cases need several effective score buckets. Keep one
            # truthful base questionnaire and express the case score through
            # the same documented override contract used in production.
            is_overridden=1,
            override_score_x10=score_x10,
            override_profile=profile_for_score_x10(score_x10),
            override_reason="Golden-Testfall mit ausdruecklich dokumentiertem Kundenwunsch",
            override_client_confirmed=1,
            override_warning_delivered=1,
            knowledge_services_json="{}",
            knowledge_instruments_json="{}",
            income_sources_json='["Berufliche Taetigkeit"]',
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        answers = [
            (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
            (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
            (3, "CHF 12'000 bis 20'000", 3),
            (4, "Herkunft: Berufliche Taetigkeit", 0),
            (5, "CHF 3'000 bis 5'000", 3),
            (6, "CHF 1'000'000 bis 2'000'000", 9),
            (7, "25 bis 50 %", 9),
            (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
            (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
            (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
            (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
        ]
        for q, label, points in answers:
            s.add(RiskAssessmentAnswer(
                id=f"golden-answer-{suffix}-{q}", assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points,
                created_at=now,
            ))
        s.commit()
        _policy, cma = ensure_runtime_reference_data(s, advisor_id)
        # Der stochastische Seed bindet die CMA-ID. Ein Golden-Test muss daher
        # auch diese fachliche Eingabe deterministisch halten; andernfalls
        # prueft er bloss zwei unterschiedliche Szenario-Stichproben.
        cma.id = f"golden-cma-{suffix}"
        s.commit()
    return advisor_id, cid, mid, aid


def _build_ch_snapshot(session_factory, combo: dict) -> dict:
    """Erzeugt das deterministische, sortierte Snapshot-Dict fuer einen Combo.

    Siehe Modul-Docstring fuer die vollstaendige Begruendung, welche Felder
    bewusst NICHT enthalten sind (IDs, Zeitstempel, Monte-Carlo-Kennzahlen).
    """
    suffix = combo["name"]
    score_x10 = combo["score_x10"]
    preferences = combo["preferences"]
    advisor_id, _cid, mid, _aid = _seed_ch_mandate(session_factory, suffix=suffix, score_x10=score_x10)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta_result = generate_target_allocation(s, mandate, advisor_id, preferences=preferences)
        allocation = ta_result["target_allocation"]
        assert allocation.optimization_method == "stochastic"
        assert allocation.optimization_status in {"converged", "converged_robustified"}
        effective_constraints = json.loads(allocation.effective_constraints_json or "{}")
        target_allocation_snapshot = {
            "score_bucket": ta_result["score_bucket"],
            "house_matrix_profile": ta_result["house_matrix_profile"],
            "optimization_method": allocation.optimization_method,
            "optimization_status": allocation.optimization_status,
            "engine_version": effective_constraints.get("engine_version"),
            "targets_bps": {
                "equities": allocation.target_equities_bps,
                "bonds": allocation.target_bonds_bps,
                "real_estate": allocation.target_real_estate_bps,
                "alternatives": allocation.target_alternatives_bps,
                "liquidity": allocation.target_liquidity_bps,
            },
            "bands_bps": {
                "equities": [allocation.band_equities_min_bps, allocation.band_equities_max_bps],
                "bonds": [allocation.band_bonds_min_bps, allocation.band_bonds_max_bps],
                "real_estate": [allocation.band_real_estate_min_bps, allocation.band_real_estate_max_bps],
                "alternatives": [allocation.band_alternatives_min_bps, allocation.band_alternatives_max_bps],
                "liquidity": [allocation.band_liquidity_min_bps, allocation.band_liquidity_max_bps],
            },
            "risky_fraction_bps": allocation.risky_fraction_bps,
            "limiting_factor": allocation.limiting_factor,
            "expected_return_bps": int(ta_result["expected_return_bps"]),
            "expected_volatility_bps": int(ta_result["expected_volatility_bps"]),
            "advisory_wealth_rappen": int(ta_result["advisory_wealth_rappen"]),
            "investable_advisory_wealth_rappen": int(ta_result["investable_advisory_wealth_rappen"]),
            "reserve_needed_rappen": int(ta_result["reserve_needed_rappen"]),
            "external_reserve_rappen": int(ta_result["external_reserve_rappen"]),
        }
        sub_allocations_snapshot = sorted(
            (
                {
                    "asset_class": item["asset_class"],
                    "sub_asset_class": item["sub_asset_class"],
                    "target_weight_bps": int(item["target_weight_bps"]),
                    "rationale": item["rationale"],
                }
                for item in ta_result["sub_allocations"]
            ),
            key=lambda item: (item["asset_class"], item["sub_asset_class"]),
        )
        target_allocation_warnings = sorted(
            (f"{w.get('code')}:{w.get('message')}" if isinstance(w, dict) else str(w))
            for w in (ta_result.get("warnings") or [])
        )
        allocation_id = allocation.id
        s.commit()

    with session_factory() as s2:
        mandate = s2.query(Mandate).filter(Mandate.id == mid).first()
        run_result = generate_recommendation_run(
            s2,
            mandate,
            advisor_id,
            preferences=preferences,
            target_allocation_id=allocation_id,
        )
        positions_snapshot = sorted(
            (
                {
                    "product_name": item["product_name"],
                    "provider": item["provider"],
                    "asset_class": item["asset_class"],
                    "sub_asset_class": item["sub_asset_class"],
                    "source_sub_asset_classes": sorted(item["source_sub_asset_classes"]),
                    "currency": item["currency"],
                    "ter_bps": item["ter_bps"],
                    "target_weight_bps": int(item["target_weight_bps"]),
                    "target_amount_rappen": int(item["target_amount_rappen"]),
                    "rationale": item["rationale"],
                }
                for item in run_result["positions"]
            ),
            key=lambda item: item["product_name"],
        )
        recommendation_warnings = sorted(str(w) for w in (run_result.get("warnings") or []))
        totals_snapshot = {
            "advisory_wealth_rappen": int(run_result["advisory_wealth_rappen"]),
            "investable_advisory_wealth_rappen": int(run_result["investable_advisory_wealth_rappen"]),
            "expected_return_bps": int(run_result["expected_return_bps"]),
            "expected_volatility_bps": int(run_result["expected_volatility_bps"]),
            "average_ter_bps": run_result["average_ter_bps"],
            "average_ter_coverage_bps": run_result["average_ter_coverage_bps"],
            "missing_ter_positions_count": run_result["missing_ter_positions_count"],
            "sum_target_weight_bps": sum(p["target_weight_bps"] for p in positions_snapshot),
            "sum_target_amount_rappen": sum(p["target_amount_rappen"] for p in positions_snapshot),
        }
        implementation_steps_snapshot = list(run_result.get("implementation_steps") or [])

    return {
        "combo": {
            "name": combo["name"],
            "score_x10": score_x10,
            "preferences": preferences,
        },
        "target_allocation": target_allocation_snapshot,
        "sub_allocations": sub_allocations_snapshot,
        "target_allocation_warnings": target_allocation_warnings,
        "positions": positions_snapshot,
        "recommendation_warnings": recommendation_warnings,
        "totals": totals_snapshot,
        "implementation_steps": implementation_steps_snapshot,
    }


# ---------------------------------------------------------------------------
# Solver-Rundungstoleranz (Nachtrag 2026-10-06, siehe Modul-Docstring).
#
# Empirisch hergeleitet aus einem lokalen Haswell-vs-Nehalem-OPENBLAS_CORETYPE-
# Repro (identischer Code, identische DB, nur der erzwungene BLAS-Kernel
# unterscheidet sich): die beobachtete maximale Abweichung lag bei 15 bps
# (targets_bps.alternatives 796 vs. 781) bzw. CHF 750 (positions[4].target_
# amount_rappen). Die hier gesetzten Werte liegen mit Sicherheitsmarge
# darueber, bleiben aber um GROESSENORDNUNGEN unter dem, was eine echte
# Fachlogik-Regression verursachen wuerde (typischerweise hunderte bis
# tausende bps Verschiebung, nicht einstellig/zweistellig).
# ---------------------------------------------------------------------------
#
# Nachtrag 2026-10-17 (SAA-RESAMPLED-STABILITY-001, v2): mit dem Bag-Mittel
# gibt es einen zweiten Rauschkanal -- unter einem anderen BLAS-Kernel landet
# gelegentlich EIN Bag (von 40) auf einer anderen, nahezu gleichwertigen Ecke
# und verschiebt das Mittel. Gemessen Haswell vs. Nehalem, identischer Code
# und identischer Inhalts-Seed (8371157439290704497): 5 von 6 Fixtures
# byte-identisch, bucket5_ausgewogen_default_prefs max. 22 bps
# (targets_bps.real_estate 854 vs. 832), Positionen max. 17 bps, CHF max.
# 1'100 (Immobilien-Schritt 42'700 vs. 41'600; deshalb CHF 1'500). Entscheid
# und Produktauswahl identisch. Toleranz daher 30 bps -- weiter weit unter dem
# 1-pp-Stabilitaetsziel und unter jeder fachlichen Regression.
_BPS_TOLERANCE = 30
_RAPPEN_TOLERANCE = 150_000  # = CHF 1'500 (Nachtrag 2026-10-17, siehe oben)

# Feldnamen, deren Wert direkt aus der kontinuierlichen SLSQP-Loesung
# abgeleitet ist und deshalb BLAS-Rundungsrauschen tragen kann -- unabhaengig
# davon, an welcher Stelle der verschachtelten Struktur sie auftreten.
_NOISY_BPS_FIELD_NAMES = {
    "target_weight_bps",
    "expected_return_bps",
    "expected_volatility_bps",
    "risky_fraction_bps",
}
_NOISY_RAPPEN_FIELD_NAMES = {"target_amount_rappen"}
# Dict-Felder, deren WERTE (nicht die Keys) bps-rauschbehaftet sind.
_NOISY_BPS_DICT_FIELD_NAMES = {"targets_bps"}

_IMPLEMENTATION_STEP_RE = re.compile(r"^(?P<prefix>.*CHF )(?P<amount>[\d']+)(?P<suffix>.*)$")


def _parse_implementation_step(step: str) -> tuple[str, int, str]:
    match = _IMPLEMENTATION_STEP_RE.match(step)
    assert match, (
        f"Unerwartetes implementation_steps-Format (Parser in "
        f"_parse_implementation_step muss angepasst werden): {step!r}"
    )
    amount = int(match.group("amount").replace("'", ""))
    return match.group("prefix"), amount, match.group("suffix")


def _assert_implementation_steps_match(actual_steps: list, expected_steps: list) -> None:
    assert len(actual_steps) == len(expected_steps), (
        f"implementation_steps-Anzahl weicht ab -- strukturelle Abweichung, "
        f"keine reine Solver-Rundung: {actual_steps!r} != {expected_steps!r}"
    )
    for i, (actual_step, expected_step) in enumerate(zip(actual_steps, expected_steps)):
        actual_prefix, actual_amount, actual_suffix = _parse_implementation_step(actual_step)
        expected_prefix, expected_amount, expected_suffix = _parse_implementation_step(expected_step)
        assert actual_prefix == expected_prefix and actual_suffix == expected_suffix, (
            f"implementation_steps[{i}] weicht strukturell ab (nicht nur im "
            f"CHF-Betrag): {actual_step!r} != {expected_step!r}"
        )
        amount_tolerance_chf = _RAPPEN_TOLERANCE // 100
        assert abs(actual_amount - expected_amount) <= amount_tolerance_chf, (
            f"implementation_steps[{i}] CHF-Betrag weicht um mehr als die "
            f"Solver-Rundungstoleranz (CHF {amount_tolerance_chf}) ab: "
            f"{actual_step!r} != {expected_step!r}"
        )


def _assert_numeric_close(actual_value, expected_value, tolerance, path: str) -> None:
    assert isinstance(actual_value, (int, float)) and isinstance(expected_value, (int, float)), (
        f"{path}: kein numerischer Wert ({actual_value!r} / {expected_value!r})"
    )
    delta = abs(actual_value - expected_value)
    assert delta <= tolerance, (
        f"{path}: Abweichung {delta} ueberschreitet die Solver-Rundungstoleranz "
        f"{tolerance} ({actual_value!r} != {expected_value!r})"
    )


def _assert_structure_matches(actual, expected, *, path: str) -> None:
    """Rekursiver Vergleich: EXAKT ueberall, ausser auf den oben benannten
    Solver-rauschbehafteten Feldern (dort gebundene Toleranz). Abweichende
    Keys, Typen oder Listenlaengen sind IMMER ein Fehler -- Toleranz gilt
    ausschliesslich fuer numerische Blaetter mit bekanntem Rauschprofil."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: Typ weicht ab (dict erwartet)"
        assert actual.keys() == expected.keys(), (
            f"{path}: Schluessel weichen ab: {sorted(actual.keys())} != {sorted(expected.keys())}"
        )
        for key in expected:
            child_path = f"{path}.{key}"
            if key in _NOISY_BPS_FIELD_NAMES:
                _assert_numeric_close(actual[key], expected[key], _BPS_TOLERANCE, child_path)
            elif key in _NOISY_RAPPEN_FIELD_NAMES:
                _assert_numeric_close(actual[key], expected[key], _RAPPEN_TOLERANCE, child_path)
            elif key in _NOISY_BPS_DICT_FIELD_NAMES:
                assert isinstance(expected[key], dict), f"{child_path}: dict erwartet"
                assert actual[key].keys() == expected[key].keys(), (
                    f"{child_path}: Schluessel weichen ab"
                )
                for subkey in expected[key]:
                    _assert_numeric_close(
                        actual[key][subkey], expected[key][subkey],
                        _BPS_TOLERANCE, f"{child_path}.{subkey}",
                    )
            else:
                _assert_structure_matches(actual[key], expected[key], path=child_path)
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: Typ weicht ab (list erwartet)"
        assert len(actual) == len(expected), (
            f"{path}: Laenge weicht ab -- strukturelle Abweichung, keine reine "
            f"Solver-Rundung: {len(actual)} != {len(expected)}"
        )
        for i, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            _assert_structure_matches(actual_item, expected_item, path=f"{path}[{i}]")
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def _assert_ch_snapshot_matches(actual: dict, expected: dict) -> None:
    """Vergleicht zwei CH-Snapshot-Dicts: EXAKT auf allen fachlichen Feldern
    (Produktauswahl, Reihenfolge, Methode/Status, Anzahl Positionen/
    Suballokationen, Warnungen, ...), mit einer schmalen, empirisch
    hergeleiteten Toleranz exakt auf den Feldern, die nachweislich BLAS/
    SLSQP-Rundungsrauschen tragen (siehe Modul-Docstring Nachtrag 2026-10-06)."""
    _assert_implementation_steps_match(
        actual.get("implementation_steps") or [],
        expected.get("implementation_steps") or [],
    )
    actual_rest = {k: v for k, v in actual.items() if k != "implementation_steps"}
    expected_rest = {k: v for k, v in expected.items() if k != "implementation_steps"}
    _assert_structure_matches(actual_rest, expected_rest, path="$")


@pytest.mark.parametrize("combo", COMBOS, ids=[c["name"] for c in COMBOS])
def test_golden_ch_snapshot_matches_frozen_fixture(session_factory, combo):
    """Diff-Gate: der frisch erzeugte CH-Empfehlungs-Snapshot muss (bis auf
    eine schmale, dokumentierte Solver-Rundungstoleranz, siehe
    _assert_ch_snapshot_matches) mit dem eingefrorenen Fixture-JSON
    uebereinstimmen. Jede strukturelle Abweichung (Produktauswahl,
    Reihenfolge, Methode/Status, Anzahl Eintraege) bleibt ein echter
    Testfehler; kein "similar enough" auf diesen Feldern.
    """
    fixture_path = FIXTURES_DIR / f"{combo['name']}.json"
    assert fixture_path.exists(), f"Fixture fehlt: {fixture_path}"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    actual = _build_ch_snapshot(session_factory, combo)

    _assert_ch_snapshot_matches(actual, expected)


def test_all_combos_have_a_frozen_fixture_file():
    """Verhindert stilles Auseinanderlaufen von COMBOS und den Fixture-Dateien."""
    expected_files = {f"{combo['name']}.json" for combo in COMBOS}
    actual_files = {p.name for p in FIXTURES_DIR.glob("*.json")}
    assert expected_files == actual_files
