#!/usr/bin/env python
"""ENGINE-LINE-BUDGET-RATCHET-001 (Kontrollrunde 2026-09-27).

ADR-014 (2026-08-03) reduzierte services/portfolio_engine.py von 8'820 auf
~3'671 Zeilen durch einen 8-Schritte-Modul-Split. Ohne einen Schutz-
mechanismus wuchs die Datei innerhalb von nur 7,5 Wochen wieder auf
7'215 Zeilen (+95%) an -- ausschliesslich durch reguläre fix(...)/feat(...)-
Commits, die die neuen Modulgrenzen ignorierten (Fund aus der ganzheitlichen
5eyes-Strategieanalyse, Codebase-Architektur-Review 2026-09-25). Der Split
selbst war handwerklich einwandfrei; es fehlte ein Mechanismus, der neue
Fachlogik in die richtigen Cluster-Submodule statt zurueck in die Kern-Datei
lenkt.

Dieses Gate ist ein RATCHET, kein Rueckbau-Zwang: der Budget-Wert liegt
knapp ueber dem Ist-Stand bei Einfuehrung (7'215 Zeilen), nicht beim
urspruenglichen ADR-014-Zielkorridor (~3'671). Es erzwingt keine sofortige
Schrumpfung, aber jede WEITERE Zunahme erfordert eine bewusste Entscheidung:
entweder den neuen Code in eines der 8 Cluster-Submodule verschieben
(services/portfolio_engine_{cma,gesamtvermoegen,house_matrix,
live_rebalancing,mc_simulation,optimizer_integration,payload,reserve}.py,
siehe docs/adr/ADR-014-engine-module-split-plan.md fuer die
Cluster-Zuordnung), oder MAX_LINES hier bewusst mit Begruendung im PR
anheben.

Single Source of Truth fuer CI (.github/workflows/test.yml) UND lokale
Nutzung. Keine Abhaengigkeiten ausserhalb der Standardbibliothek -- laeuft
als eigener, sekundenschneller CI-Job ohne pip install.

Aufruf (aus Repo-Root):
    python scripts/check_engine_line_budget.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_FILE = REPO_ROOT / "5eyes-backend" / "services" / "portfolio_engine.py"

# Ist-Stand bei Einfuehrung dieses Gates (2026-09-27, verifiziert per `wc -l`):
# 7'215 Zeilen. Kleiner Puffer bis 7'300 faengt triviale Kommentar-/Docstring-
# Ergaenzungen ab, ohne die eigentliche Absicht (kein unkontrolliertes
# Wachstum mehr) aufzuweichen.
#
# 2026-10-10 bewusst von 7'300 auf 7'320 angehoben (der Docstring oben nennt
# diesen Weg explizit als eine der zwei zulaessigen Antworten). Begruendung:
# SUBRISK-CONTEXT-REPLAY-001 bindet die Intra-Bucket-Korrelation in die drei
# Evidenz-Hash-Oberflaechen. Der Zuwachs in der Kern-Datei sind drei
# einzeilige Dict-Eintraege plus Kommentare -- KEINE neue Fachlogik: die
# eigentliche Helferfunktion `_sub_class_intra_correlation_x100()` liegt
# bereits im richtigen Cluster-Submodul (portfolio_engine_cma.py, direkt
# neben `_weighted_bucket_metrics()`, der einzigen Stelle, die die
# Einstellung auswertet) und wird von hier nur re-exportiert. Der Puffer von
# 7'300 war nach #575 praktisch aufgebraucht (7'293). Die Alternative waere
# gewesen, eigene Begruendungs-Kommentare so lange zu kuerzen, bis es knapp
# passt -- das haette das Gate umspielt statt respektiert.
#
# 2026-10-11 zwischenzeitlich auf 7'340 angehoben (Nachweis-Eintraege fuer
# CMA-CORRELATION-JURISDICTION-PROVENANCE-001 und DRAWDOWN-TIME-GRID-001 /
# REPORTING-BASIS-DURABILITY-001) -- mit dem Vermerk, dass die naechste
# Anhebung die Extraktion eines Cluster-Submoduls ausdruecklich pruefen soll
# statt die Zahl ein viertes Mal zu erhoehen.
#
# 2026-10-11, direkt danach: dieser Fall trat bei
# OPTIMIZER-OBJECTIVE-VARIANTS-001 ein. Die Pruefung ist ERFOLGT und das
# Ergebnis war eindeutig -- `_build_allocation_model_basis()` (288 Zeilen) ist
# nach services/portfolio_engine_model_basis.py extrahiert worden, statt das
# Budget wieder anzuheben. Die Extraktion war sauber: die Funktion nimmt alles
# ueber explizite Parameter, gibt ein dict zurueck und ruft ausserhalb nur die
# fuenf _simulation_*-Praeferenz-Leser des MC-Clusters und die drei
# Nachweis-Funktionen auf; keine Zirkularitaet. In portfolio_engine.py steht
# nur noch ein Re-Export, damit bestehende Aufrufstellen und Tests
# unveraendert bleiben.
#
# Damit faellt die Datei von 7'347 auf 7'059 Zeilen. Das Budget wird
# ENTSPRECHEND MITGESENKT (7'340 -> 7'100): ein Budget von 7'340 bei 7'059
# Zeilen waere kein Ratschen-Gate mehr, sondern 280 Zeilen Freibrief. Wer
# Platz schafft, zieht die Ratsche nach -- sonst ist die Extraktion nur eine
# Verschiebung des Problems in die Zukunft.
#
# Hinweis fuer das naechste Mal: der Modell-Basis-Block war der groesste
# zusammenhaengende Nicht-Orchestrator-Teil. Weitere Kandidaten mit
# vergleichbarem Profil (explizite Parameter, dict-Rueckgabe, wenige
# Fremdaufrufe) muessen erst identifiziert werden -- eine Anhebung ohne
# vorherige Suche ist weiterhin die falsche Antwort.
#
# 2026-10-14: zweiter solcher Kandidat gefunden und extrahiert --
# `_verified_persisted_allocation_context()` (206 Zeilen, Integritaets-Gate
# fuer persistierte Allokations-Artefakte) nach
# services/portfolio_engine_allocation_integrity.py (7'140 -> 6'937 Zeilen;
# develop stand nach den Merges #600-#607 mit 7'140 bereits UEBER Budget).
# Das Budget bleibt hier BEWUSST bei 7'100: der frei gewordene Platz ist fuer
# die noch offenen Audit-Fix-PRs (#606-#616, Asset-Allocation-Audit
# 2026-10-14) reserviert, deren Kern-Datei-Anteile auf das Minimum
# (Aufrufstellen + Ticket-Verweis) reduziert wurden. Sobald diese gemergt
# sind, ist die Ratsche auf den dann gueltigen Ist-Stand nachzuziehen.
MAX_LINES = 7_100


def count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def main() -> int:
    if not ENGINE_FILE.is_file():
        print(f"FEHLER: {ENGINE_FILE} nicht gefunden.", file=sys.stderr)
        return 1

    line_count = count_lines(ENGINE_FILE)
    relative_path = ENGINE_FILE.relative_to(REPO_ROOT)

    if line_count > MAX_LINES:
        print(
            f"ENGINE-ZEILENBUDGET UEBERSCHRITTEN: {relative_path} hat "
            f"{line_count} Zeilen (Budget: {MAX_LINES}).\n\n"
            "services/portfolio_engine.py ist seit ADR-014 (2026-08-03) "
            "bewusst auf die verbleibenden Orchestrator-Funktionen + "
            "Kern-Helfer reduziert. Neue Fachlogik gehoert in eines der "
            "8 Cluster-Submodule (services/portfolio_engine_*.py) -- siehe "
            "docs/adr/ADR-014-engine-module-split-plan.md fuer die "
            "Cluster-Zuordnung.\n\n"
            "Falls diese Zunahme bewusst und unvermeidbar ist: MAX_LINES "
            "in scripts/check_engine_line_budget.py anheben, mit "
            "Begruendung im Pull-Request.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {relative_path} hat {line_count}/{MAX_LINES} Zeilen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
