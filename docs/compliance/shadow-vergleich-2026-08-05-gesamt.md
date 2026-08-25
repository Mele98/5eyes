# Shadow-Vergleichs-Report — Gesamt (2026-08-05)

> Bezug: `docs/compliance/stage8-berater-runbook.md`, Methodology
> `docs/planning/2026-05-23-stochastic-shadow-comparison-methodology.md` §4/§6.
> Ausgeloest durch Nutzer-Anfrage 2026-08-05 ("Zielbewertung funktioniert nicht/nie").

## Abweichung vom Runbook — WICHTIG, zuerst lesen

Das Runbook (Schritt 2.2) verlangt 3 **reale** Mandate nach festen Archetypen
(Defensiv-Pensionaer mit hartem Cashflow-Ziel, Wachstumsorientiert mit
primaerem Vermoegensziel, Dynamisch-Akkumulation). Die aktuelle reale
Datenbasis hat das geprueft (`find_archetypes.py`, siehe Skript-Ordner) und
enthaelt **ausschliesslich Renditeziel-Goals** (`goal_family="Rendite"`) ueber
alle 6 aktiven Mandate hinweg — kein einziges Cashflow-/Pensions-Ziel
existiert aktuell im System. Die Defensiv-Pensionaer-Archetyp-Bedingung
("≥ 1 hartes Cashflow-Ziel") ist damit mit der heutigen Datenbasis nicht
erfuellbar.

**Vorgehen statt Abbruch:** alle 5 real generierbaren aktiven Mandate
(1 Mandat schlug fehl: "Bitte zuerst ein aktuelles Risikoprofil speichern")
wurden durch den Shadow-Vergleich geschickt statt nur 3 — mehr Signal als
die Methodology-Mindestanforderung, aber ohne die vorgeschriebene
Archetyp-Abdeckung. Der Foundation-Case-Lauf hatte einen Skript-Fehler beim
zweiten Ausfuehrungsversuch (Neuanlage-Pfad, Encoding-Artefakt) und ist NICHT
in diesem Report enthalten — sollte vor einer finalen Freigabe nachgeholt
werden.

**Ausfuehrungsumgebung:** Lief gegen eine ISOLIERTE KOPIE der Live-Datenbank
(`~/5eyes/5eyes.db` → temporaere Kopie), NICHT gegen die Live-DB selbst —
keine reale Mandatsdaten wurden veraendert. `OPTIMIZER_MODE` wurde nur
fuer diesen Analyse-Lauf in-process auf `shadow_stochastic` gesetzt, NIE
in der echten Konfiguration der laufenden Installation.

---

## Gesamt-Verdikt-Tabelle

| Mandat (pseudonymisiert) | Verdikt | Kernbefund |
|---|---|---|
| foundation | ⚠️ nicht erfasst (Skript-Fehler beim 2. Lauf) | nachzuholen |
| real-1 | 🟡 YELLOW | risky_drift_bps 853 (Schwelle 500-1000) |
| real-2 | 🟡 YELLOW | optimization_status=converged_robustified |
| real-3 | 🟡 YELLOW | robustified + Renditeziel als "nicht_erreichbar" erkannt (siehe unten) |
| real-4 | 🟡 YELLOW | risky_drift_bps 802 (Schwelle 500-1000) |
| real-5 | 🟢 GREEN | Methodology-Schwellen erfuellt |

**Aggregat (API `/admin/system/shadow-comparison-aggregate`):**
```json
{"counts": {"green": 1, "yellow": 4, "red": 0, "total": 5},
 "percentages": {"green": 20.0, "yellow": 80.0, "red": 0.0},
 "default_switch_ready": false,
 "default_switch_reason": "GREEN-Anteil 1/5 unter 2/3 — Owner-Review fuer YELLOW-Mandate noetig."}
```

**Default-Wechsel auf `OPTIMIZER_MODE=stochastic` freigegeben:** ☐ ja ☒ **nein**

**Begruendung:** 1/5 GREEN liegt weit unter der Methodology-Schwelle
(≥ 2/3 real GREEN, 0 RED). 0 RED ist positiv (keine harten Fehlschlaege,
kein Budget-Verstoss, keine unerreichbaren HARTEN Ziele) — die YELLOW-Faelle
sind grossteils plausible, erklaerbare methodische Unterschiede
zwischen den beiden Solvern (siehe Owner-Review unten), aber die
Mindest-GREEN-Quote ist nicht erreicht und die vorgeschriebene
Archetyp-Abdeckung fehlt. **Kein automatischer Grund zur Sorge (0 RED), aber
auch keine Freigabe nach Methodology §4.**

---

## Owner-Review der YELLOW-Faelle (fachliche Wuerdigung)

### real-1, real-4 (beide: "500 < risky_drift_bps <= 1000")

Beide Faelle: Stochastic verschiebt moderat von Aktien Richtung Immobilien
(real-1: Immobilien 5%→11.8%; real-4: Immobilien 5%→12.6%), bleibt aber
strikt innerhalb des Risikobudgets (`budget_compliance` beide True). Das ist
methodisch plausibel: der stochastische Solver optimiert unter expliziten
Zielwahrscheinlichkeits-Constraints und findet dabei andere, aber ebenfalls
budget-konforme Kombinationen als die tabellenbasierte House-Matrix.
**Drift ist fachlich erklaerbar; keine Fehlerklasse erkennbar.**

### real-2 ("optimization_status=converged_robustified")

Manuell auf "Dynamisch" uebersteuertes Risikoprofil (Warnung
`WARN_OVERRIDE` im Payload dokumentiert). Solver musste robustifizieren
(Solver mit Softening/Retry konvergiert, nicht beim ersten Versuch) —
per Methodology automatisch YELLOW, aber `optimization_status` ist ein
akzeptierter Endzustand, kein Fehler. Zielerreichbarkeit: 83% (komfortabel).
**Fachlich unauffaellig.**

### real-3 (robustified + Renditeziel "nicht_erreichbar", elapsed 12.7s)

**Wichtigster Einzelbefund dieses Laufs.** Der stochastische Solver stellt
fest, dass das primaere "Renditeziel" dieses Mandats bei heutigem Vermoegen,
geplanten Zufluessen und Zeithorizont **mathematisch nicht erreichbar ist**
(Wahrscheinlichkeit 11.1%, `status=nicht_erreichbar`, Meldung
`CONFLICT_DATA_INSUFFICIENT`) — **unabhaengig vom Risikoprofil**. Das ist
exakt die Art von Erkenntnis, die die deterministische House-Matrix-Engine
strukturell NICHT liefern kann (sie kennt keine Zielwahrscheinlichkeiten).
Die grosse Allokations-Drift (Aktien 25%→15%, Obligationen 59%→70%) ist eine
direkte Folge dieser Erkenntnis. Die lange Laufzeit (12.7s, > 8s-Schwelle)
liegt an der Robustifizierung bei diesem schwierigen Fall.

**Das ist inhaltlich kein Bug, sondern der Kernnutzen des stochastischen
Solvers — genau das fehlt heute (siehe Zielbewertung-Diagnose).** Ob dieses
konkrete Mandat auf GREEN reklassifiziert werden soll, ist eine fachliche
Entscheidung: der Owner sollte pruefen, ob "nicht_erreichbar" fuer dieses
Ziel tatsaechlich zutrifft (Eingaben plausibilisieren) und ob die
Allokations-Verschiebung im Beratungsgespraech vertretbar waere.

**Empfehlung:** vor einer Freigabe dieses konkreten Mandat-Falls im Detail
mit dem Berater durchsprechen (Reasoning-Trace via
`GET /admin/system/shadow-comparison/<mandate_id>`).

### real-5 (GREEN)

Keine Auffaelligkeiten. Referenzfall dafuer, dass GREEN unter realen
Bedingungen erreichbar ist.

---

## Empfehlung / naechste Schritte

1. **Kein Default-Switch jetzt.** Automatisches Methodology-§4-Verdikt ist
   eindeutig: `default_switch_ready=false`.
2. **0 RED ist ein gutes Signal** — keine der bisherigen Sorgen (Solver-
   Nichtkonvergenz, Budget-Verstoss, unerreichbare harte Ziele) trat auf.
   Die YELLOW-Faelle sind methodisch erklaerbar, nicht bugverdaechtig.
3. **Foundation-Case nachholen** (Skript-Fehler beim zweiten Lauf war ein
   Idempotenz-Artefakt des Analyse-Skripts selbst, kein Produktivcode-Bug —
   sollte trotzdem sauber erfasst werden, bevor final entschieden wird).
4. **Datenbasis fuer Defensiv-Pensionaer-Archetyp fehlt strukturell** — sobald
   ein reales Mandat mit hartem Cashflow-/Pensions-Ziel existiert, diesen
   Report um diesen Fall ergaenzen.
5. Bei Bedarf: `real-3` im Detail mit dem Berater besprechen (siehe oben) —
   unabhaengig vom Stage-8-Entscheid ein Fall, der heute schon zeigt, was
   die Zielbewertung leisten wuerde, wenn sie aktiv waere.

**Owner-Signatur + Datum:** _(noch ausstehend — dieser Report ist eine
Analyse-Grundlage, keine abgeschlossene Freigabe. Schritt 6 des Runbooks
["Default-Switch committen"] bleibt explizit eine manuelle Owner-Aktion.)_
