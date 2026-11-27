"""CCX-P2 Vollstaendigkeits-Waechter fuer den zentralen Mutation Hook.

Der Hook (models/snapshots.py) haengt an der ORM-Session: jede Einzel-
mutation (``after_flush``) und jedes Massen-UPDATE/-DELETE
(``do_orm_execute``) auf einer Abhaengigkeitstabelle invalidiert im selben
Commit. Umgehen laesst er sich nur durch rohes SQL, ORM-Massen-INSERT oder
``bulk_*``-Hilfen. Dieser Waechter

1. verbietet rohe Schreib-SQL-Anweisungen auf Abhaengigkeitstabellen ausserhalb
   einer begruendeten Allowlist (AST ueber alle Backend-Module);
2. verbietet ``bulk_save_objects``/``bulk_insert_mappings``/
   ``bulk_update_mappings`` und Core-``insert(Model)`` auf diesen Modellen;
3. fuehrt das Inventar aller schreibenden Routen auf Abhaengigkeitsmodellen
   (AST, gepinnt): eine neue schreibende Route faellt auf und muss bewusst
   aufgenommen werden; jede inventarisierte Route schreibt ausschliesslich
   ueber die Session (also ueber den Hook);
4. prueft dynamisch, dass jede registrierte Tabelle gemappt ist, ihr
   Reichweiten-Attribut besitzt und INSERT/UPDATE/DELETE als Aenderung
   erkannt wird.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
EXCLUDED = {"tests", "alembic", "scripts", "migrations", "node_modules", "venv", "__pycache__", "assets"}

# Rohes Schreib-SQL auf Abhaengigkeitstabellen: nur hier, mit Begruendung.
RAW_SQL_ALLOWLIST = {
    # Laufzeit-Schemapatches/Altdaten-Migrationen beim Start (keine Fachmutation,
    # laufen vor jedem Request; Bestand bleibt UNKNOWN/STALE, nie FRESH).
    "database.py": "Laufzeitpatch/Altdaten-Migration beim Start",
    # Loeschbegehren (DSG): Pseudonymisierung bzw. Purge eines Kunden. Die
    # zweite Linie greift: das Gate prueft vor jeder Auslieferung die Kanten
    # gegen die aktuellen Zeilen (envelope_freshness_defect) -> STALE.
    "services/client_erasure.py": "DSG-Loeschung, Pull-Pruefung im Gate",
    "services/foundation_purge.py": "Mandanten-Purge, Pull-Pruefung im Gate",
    # Mandantenbindung beim Start: tenant_id nur dort nachtragen, wo sie NULL
    # ist (kein Fachinhalt; die Kanten-Pull-Pruefung des Gates bleibt wirksam).
    "core/mandate_evidence_tenant_boundary.py": "tenant_id-Nachtrag (NULL) beim Start",
    "services/risk_evidence_tenant_boundary.py": "tenant_id-Nachtrag (NULL) beim Start",
    "services/wealth_tenant_boundary.py": "tenant_id-Nachtrag (NULL) und Fuell-Trigger beim Start",
    "services/postgres_rls.py": "tenant_id-Nachtrag (NULL) beim RLS-Boot",
    # Tabellen-Neuaufbau (Kopie identischer Zeilen) bzw. Login-Tabellen --
    # das generische "{}" trifft keine Abhaengigkeitstabelle.
    "core/product_eligibility_override_schema.py": "Neuaufbau product_eligibility_overrides",
    "services/login_guard.py": "Login-Sperrtabellen, keine Abhaengigkeit",
}

def _modules():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if set(rel.parts) & EXCLUDED:
            continue
        yield rel.as_posix(), ast.parse(path.read_text(encoding="utf-8-sig"))


def _dependency_tables():
    import main  # noqa: F401  (registriert alle Modelle)
    from models.snapshots import DEPENDENCY_SOURCES

    return DEPENDENCY_SOURCES


def _model_names(sources) -> set[str]:
    from database import Base

    return {m.class_.__name__ for m in Base.registry.mappers if m.local_table.name in sources}


def _string_constants(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
            yield node.lineno, text


def test_no_raw_write_sql_on_dependency_tables_outside_allowlist():
    sources = _dependency_tables()
    tables = "|".join(sorted(map(re.escape, sources), key=len, reverse=True))
    pattern = re.compile(
        rf"\b(UPDATE|INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|DELETE\s+FROM)\s+[\"`]?({tables})\b",
        re.IGNORECASE,
    )
    dynamic = re.compile(r"\b(UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+\{\}", re.IGNORECASE)
    offenders = []
    for rel, tree in _modules():
        if rel in RAW_SQL_ALLOWLIST:
            continue
        for lineno, value in _string_constants(tree):
            if pattern.search(value) or dynamic.search(value):
                offenders.append(f"{rel}:{lineno}: {value.strip()[:80]}")
    assert not offenders, "rohes Schreib-SQL umgeht den CCX-P2-Hook:\n" + "\n".join(offenders)


def test_allowlisted_raw_sql_files_exist_and_still_write():
    sources = _dependency_tables()
    tables = "|".join(sorted(map(re.escape, sources), key=len, reverse=True))
    pattern = re.compile(rf"\b(UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+({tables}|\{{\}})", re.IGNORECASE)
    for rel in RAW_SQL_ALLOWLIST:
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8-sig"))
        assert any(pattern.search(v) for _l, v in _string_constants(tree)), f"Allowlist veraltet: {rel}"


def test_no_bulk_helpers_or_core_insert_on_dependency_models():
    models = _model_names(_dependency_tables())
    offenders = []
    for rel, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in (
                    "bulk_save_objects", "bulk_insert_mappings", "bulk_update_mappings"):
                offenders.append(f"{rel}:{node.lineno}: {func.attr}")
            if (isinstance(func, ast.Name) and func.id == "insert" and node.args
                    and isinstance(node.args[0], ast.Name) and node.args[0].id in models):
                offenders.append(f"{rel}:{node.lineno}: insert({node.args[0].id})")
    assert not offenders, "\n".join(offenders)


_ROUTE_METHODS = {"post", "put", "patch", "delete"}
# Lade-Helfer der Router (``_get_goal_or_404`` ...) -> Modell.
_GETTER = re.compile(r"_?get_(\w+?)(?:_for_user)?_or_404")
_GETTER_MODELS = {
    "goal": "Goal", "cashflow": "Cashflow", "wealth_position": "WealthPosition", "position": "WealthPosition",
    "wealth_inflow": "WealthInflow", "inflow": "WealthInflow", "mandate": "Mandate", "client": "Client",
    "risk_assessment": "RiskAssessment", "assessment": "RiskAssessment", "cma": "CapitalMarketAssumption",
    "policy": "OptimizerPolicy", "optimizer_policy": "OptimizerPolicy", "target_allocation": "TargetAllocation",
    "allocation": "TargetAllocation",
}


def _write_routes(models: set[str]) -> dict[str, set[str]]:
    """Routen (Router-Dekorator POST/PUT/PATCH/DELETE), die ein
    Abhaengigkeitsmodell anlegen, per Massen-UPDATE/-DELETE aendern oder ein
    per ``query(Model)``/``get(Model, ...)`` geladenes Objekt aendern/loeschen."""
    found: dict[str, set[str]] = {}
    for rel, tree in _modules():
        if not rel.startswith("routers/"):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                       and d.func.attr in _ROUTE_METHODS for d in node.decorator_list):
                continue
            touched = set()
            loaded: dict[str, str] = {}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in models:
                    touched.add(sub.func.id)
                if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call):
                    getter = sub.value.func
                    name = getter.id if isinstance(getter, ast.Name) else getattr(getter, "attr", "")
                    match = _GETTER.fullmatch(name or "")
                    if match and match.group(1) in _GETTER_MODELS:
                        for target in sub.targets:
                            if isinstance(target, ast.Name):
                                loaded[target.id] = _GETTER_MODELS[match.group(1)]
                    for inner in ast.walk(sub.value):
                        if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                                and inner.func.attr in ("query", "get") and inner.args
                                and isinstance(inner.args[0], ast.Name) and inner.args[0].id in models):
                            for target in sub.targets:
                                if isinstance(target, ast.Name):
                                    loaded[target.id] = inner.args[0].id
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr in ("update", "delete")):
                    for inner in ast.walk(sub.func.value):
                        if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                                and inner.func.attr == "query" and inner.args
                                and isinstance(inner.args[0], ast.Name) and inner.args[0].id in models):
                            touched.add(inner.args[0].id)
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "setattr"
                        and sub.args and isinstance(sub.args[0], ast.Name) and sub.args[0].id in loaded):
                    touched.add(loaded[sub.args[0].id])
                if isinstance(sub, (ast.Assign, ast.AugAssign)):
                    targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                    for target in targets:
                        if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                                and target.value.id in loaded):
                            touched.add(loaded[target.value.id])
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "delete" and sub.args and isinstance(sub.args[0], ast.Name)
                        and sub.args[0].id in loaded):
                    touched.add(loaded[sub.args[0].id])
            if touched:
                found[f"{rel}::{node.name}"] = touched
    return found


INVENTORY_FILE = Path(__file__).with_name("ccx_p2_write_route_inventory.txt")


def test_write_route_inventory_is_pinned_and_hook_covered():
    sources = _dependency_tables()
    models = _model_names(sources)
    found = _write_routes(models)
    pinned = {line.strip() for line in INVENTORY_FILE.read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.startswith("#")}
    current = {f"{route} -> {','.join(sorted(touched))}" for route, touched in found.items()}
    assert current == pinned, (
        "Inventar schreibender Routen auf CCX-P2-Abhaengigkeiten geaendert -- pruefen, dass die "
        "neue Route ueber die ORM-Session schreibt, und tests/ccx_p2_write_route_inventory.txt "
        "nachfuehren.\nneu: " + "\n".join(sorted(current - pinned)) + "\nentfallen: "
        + "\n".join(sorted(pinned - current))
    )
    assert len(found) >= 20  # Kontrolle: der Scanner findet die bekannten Routen


def test_every_registered_table_is_mapped_with_its_scope_attribute():
    from database import Base

    sources = _dependency_tables()
    mapped = {m.local_table.name: m for m in Base.registry.mappers}
    for table, source in sources.items():
        assert table in mapped, table
        assert source.key in mapped[table].columns, (table, source.key)


@pytest.mark.parametrize("op", ["insert", "update", "delete"])
def test_hook_recognises_every_operation(op):
    from models.snapshots import DEPENDENCY_SOURCES, _change

    for table, source in DEPENDENCY_SOURCES.items():
        old = {"id": "row-1", source.key: "scope-1", "value": 1}
        new = {**old, "value": 2}
        change = _change(table, source, op, old if op != "insert" else {}, new if op != "delete" else {})
        assert change is not None and change.op == op and "scope-1" in change.scope_values, (table, op)
    noop = _change("goals", DEPENDENCY_SOURCES["goals"], "update", {"id": "g", "mandate_id": "m"},
                   {"id": "g", "mandate_id": "m"})
    assert noop is None  # Leermutation -> kein Ereignis


# ── N-908-02: Core-DML-Umgehungen (statisch + Laufzeit) ──────────────────────

_DML = {"update", "delete", "insert"}
_SESSION_NAMES = {"db", "session", "s", "sess"}


def _dml_target(node, models: set[str]) -> str | None:
    """``update(Goal)``/``update(Goal.__table__)``/``Goal.__table__.update()``
    -> Modellname, sonst None."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _DML and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id in models:
                return arg.id
            if (isinstance(arg, ast.Attribute) and arg.attr == "__table__"
                    and isinstance(arg.value, ast.Name) and arg.value.id in models):
                return arg.value.id + ".__table__"
        if (isinstance(func, ast.Attribute) and func.attr in _DML and isinstance(func.value, ast.Attribute)
                and func.value.attr == "__table__" and isinstance(func.value.value, ast.Name)
                and func.value.value.id in models):
            return func.value.value.id + ".__table__"
    return None


def core_dml_bypasses(tree, models: set[str]) -> list[tuple[int, str]]:
    """Statische Umgehungen: jede Core-Tabellen-DML (``X.__table__``) und jede
    DML auf ein Abhaengigkeitsmodell, die nicht ueber eine Session
    (``db/session.execute``) laeuft -- also ``.connection().execute(...)`` oder
    ``engine.begin()/connect()``-Verbindungen."""
    found = []
    for node in ast.walk(tree):
        target = _dml_target(node, models)
        if target and target.endswith(".__table__"):
            found.append((node.lineno, target))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
            receiver = node.func.value
            via_session = isinstance(receiver, ast.Name) and receiver.id in _SESSION_NAMES
            for arg in node.args[:1]:
                for inner in ast.walk(arg):
                    hit = _dml_target(inner, models)
                    if hit and not via_session:
                        found.append((node.lineno, f"execute({hit}) ohne Session"))
    return sorted(set(found))


def test_no_core_dml_bypass_on_dependency_tables():
    models = _model_names(_dependency_tables())
    offenders = []
    for rel, tree in _modules():
        if rel in RAW_SQL_ALLOWLIST:
            continue
        offenders.extend(f"{rel}:{line}: {what}" for line, what in core_dml_bypasses(tree, models))
    assert not offenders, "Core-DML umgeht den CCX-P2-Hook:\n" + "\n".join(offenders)


def test_static_guard_detects_both_known_bypasses():
    """Negativkontrolle: die beiden nachgewiesenen Umgehungen (N-908-02) und
    engine.begin() werden erkannt; der ORM-Weg ueber die Session nicht."""
    models = _model_names(_dependency_tables())
    snippet = (
        "def bad(db, engine):\n"
        "    db.execute(update(Goal.__table__).values(weight_bps=1))\n"
        "    db.connection().execute(update(Goal).values(weight_bps=1))\n"
        "    with engine.begin() as conn:\n"
        "        conn.execute(Goal.__table__.delete())\n"
        "def good(db):\n"
        "    db.execute(update(Goal).values(weight_bps=1))\n"
        "    db.query(Goal).update({'weight_bps': 1})\n"
    )
    found = core_dml_bypasses(ast.parse(snippet), models)
    assert {line for line, _ in found} == {2, 3, 5}, found
