"""Roadmap #49 — Rebalancing-Trigger-Konsistenz (ADR-003).

Invariante: Drift-/Bandbreiten-Erkennung (refresh_system_review_triggers)
darf AUSSCHLIESSLICH aus berater-initiierten Request-Handlern aufgerufen
werden — niemals aus dem Preis-/Marktdaten-Scheduler. Ein Market-Watcher,
der bei Marktbewegung ein Rebalancing/einen Trigger feuert, waere ein
Verstoss gegen ADR-003 (kein Markt-Timing, Re-Balancing nur via
Eignungspruefung/Kunden-Meldung).

Schuetzt vor stiller Aufweichung: falls jemand die Drift-Erkennung an einen
Cron/Scheduler-Job haengt, muss dieser Test rot werden.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Module, die als Scheduler-/Market-Watcher-Einstiegspunkte gelten.
SCHEDULER_MODULES = (
    BACKEND_ROOT / "price_updater.py",
    BACKEND_ROOT / "services" / "market_data" / "scheduled.py",
    BACKEND_ROOT / "services" / "market_data_daily_refresh.py",
    BACKEND_ROOT / "services" / "fx_rate_daily_refresh.py",
)

# Symbole, deren Aufruf aus dem Scheduler eine Markt-getriggerte
# Rebalancing-/Review-Ausloesung bedeuten wuerde.
FORBIDDEN_SYMBOLS = (
    "refresh_system_review_triggers",
    "build_live_rebalancing_payload",
)


def _referenced_names(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def test_scheduler_never_references_rebalancing_trigger_symbols():
    """ADR-003 sec.1: kein Scheduler-Job feuert Drift-/Rebalancing-Trigger."""
    for module_path in SCHEDULER_MODULES:
        assert module_path.exists(), f"Scheduler-Modul fehlt: {module_path}"
        referenced = _referenced_names(module_path)
        leaked = referenced & set(FORBIDDEN_SYMBOLS)
        assert not leaked, (
            f"{module_path.name} referenziert markt-getriggerte "
            f"Rebalancing-/Review-Ausloeser {sorted(leaked)} — Verstoss gegen "
            "ADR-003 (Re-Balancing nur via Eignungspruefung/Kunden-Meldung, "
            "nicht via Marktdaten-Scheduler)."
        )


def test_drift_trigger_only_called_from_advisor_request_handlers():
    """Whitelist der erlaubten Call-Sites von refresh_system_review_triggers.

    Erlaubt sind nur berater-initiierte Router/Workflow-Module. Taucht ein
    neuer Aufrufer ausserhalb dieser Whitelist auf, muss der Fund bewusst
    (mit ADR-Bezug) freigegeben werden.
    """
    allowed = {
        "routers/allocation.py",
        "routers/review.py",
        "services/foundation_example.py",  # Seed/Demo-Helper, kein Cron
    }
    callers = set()
    for py in BACKEND_ROOT.rglob("*.py"):
        if "tests" in py.parts:
            continue
        if py.name == "review_engine.py":  # Definitionsort
            continue
        text = py.read_text(encoding="utf-8")
        if "refresh_system_review_triggers" in text:
            callers.add(py.relative_to(BACKEND_ROOT).as_posix())
    unexpected = callers - allowed
    assert not unexpected, (
        f"Unerwartete Aufrufer von refresh_system_review_triggers: "
        f"{sorted(unexpected)}. Drift-/Review-Trigger duerfen nur aus "
        "berater-initiierten Workflows kommen (ADR-003)."
    )
