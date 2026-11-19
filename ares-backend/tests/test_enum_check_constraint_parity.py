"""RC-CH-1-F1: Paritaet Eingabe-Enums <-> DB-CHECK-Wertelisten (generisch).

Bugklasse (mehrfach aufgetreten: Hypothek-Amortisationstyp, contract_documents-
Status, house_matrix, goal_type "Vermoegensziel"): ein Wert, den API-Schema
oder Maske anbieten, fehlt in der ``CHECK(col IN (...))``-Liste des echten
Schemas (``ares_schema.sql``). ``Base.metadata.create_all()`` kennt diese
CHECKs nicht, daher bleibt der Fehler in ORM-Tests unsichtbar und endet beim
Kunden als 500 beim Commit.

Geprueft wird ueber Modell-Metadaten, ohne DB:

1. Jedes Schreib-Schema (``*Create``/``*Update``/...) wird ueber den
   Klassennamen bzw. ``EXPLICIT_TARGETS`` einer ORM-Tabelle zugeordnet. Fuer
   jedes ``Literal``-Feld, dessen Spalte eine CHECK-Werteliste hat, gilt:
   jeder Literal-Wert -- nach der dokumentierten Kanonisierung an der API-
   Grenze (``CANONICALIZERS``) -- steht in der CHECK-Liste.
2. Vollstaendigkeit: ein Schreib-Schema mit ``Literal``-Feld, dessen Name
   eine CHECK-Spalte irgendeiner Tabelle ist, muss zugeordnet oder in
   ``NOT_PERSISTED`` begruendet sein. Ein neues Schema faellt so nicht still
   aus der Pruefung.
3. Ziele: die Werte, die Classic-Maske und React-Editor fuer goal_type
   anbieten, sind nach Kanonisierung CHECK-Werte; die DB-Wertelisten in
   ``core.goal_vocabulary`` sind exakt die CHECK-Listen.
4. CHECK-Quellen (N-903-01): ``ares_schema.sql`` (Desktop-Bootstrap), ORM-
   ``CheckConstraint`` (create_all/PG-Baseline, z.B. privacy_*,
   Sustainability) und Alembic-Revisionen; je Spalte gilt die Schnittmenge.
5. Freie ``str``-Felder auf CHECK-Spalten sind in ``STR_FIELD_POLICY``
   registriert (Vollstaendigkeit hier, Verhalten in
   ``test_check_free_text_fields_real_schema.py``).

Rueckname-Gegenprobe an fb83c8e7 (N-903-04): rot ist
``test_registered_goal_canonicalizers_are_applied_by_create_and_update``
(GoalCreate lehnte 'Vermoegen' ab, GoalUpdate speicherte roh). Die uebrigen
Tests sind bewusst STRUKTUR-Waechter (Quellen, Zuordnung, Vollstaendigkeit,
UI-Werte, Konstanten) und schon am alten Code gruen: sie schlagen an, sobald
ein neues Schema, eine neue CHECK-Liste oder ein neuer UI-Wert ohne
Gegenstueck dazukommt.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import sys
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import models  # noqa: E402
import schemas  # noqa: E402
import schemas.wealth as wealth_schemas  # noqa: E402
import core.goal_vocabulary as vocab  # noqa: E402
from database import Base  # noqa: E402
from services.risk_scoring import canonicalize_horizon_label  # noqa: E402
from services.sqlite_check_constraint_upgrade import reference_check_in_lists  # noqa: E402
from services.sqlite_check_ddl import DdlParseError, SupportedCheck, parse_table_ddl  # noqa: E402
from tests.monolith_source import read_monolith_bundle  # noqa: E402

for _mod in pkgutil.walk_packages(models.__path__, "models."):
    importlib.import_module(_mod.name)

WRITE_SUFFIX = re.compile(r"(Create|Update|Patch|Upsert|Base|In|Request|Body)$")

# Schreib-Schemas, deren Name nicht dem ORM-Klassennamen folgt.
EXPLICIT_TARGETS: dict[str, str] = {
    "schemas.profiling.KnowledgeCreate": "client_knowledge",
    "schemas.review.ConflictDisclosureCreate": "conflict_of_interest_disclosures",
    "schemas.review.ReviewTriggerFrequencyUpdate": "review_triggers",
    "schemas.review.RecommendationGenerateRequest": "recommendation_runs",
    # Einladungen legen spaeter einen users-Eintrag mit genau dieser Rolle an.
    "schemas.users.InviteCreate": "users",
    "schemas.clients.OptHistoryCreate": "client_opt_history",
    "schemas.review.ConflictMitigateRequest": "conflict_of_interest_disclosures",
    "schemas.protocol_bausteine.BausteinCreate": "protocol_bausteine",
    "schemas.protocol_bausteine.BausteinUpdate": "protocol_bausteine",
    # RC-CH-1 Teil 2b (E2 x F1): Erfassung der Nachhaltigkeitspraeferenz.
    "schemas.profiling.SustainabilityPreferenceCreate": "investment_preference_decisions",
}

# N-903-01: freie ``str``-Felder, die in eine CHECK-Spalte schreiben. Keine
# statische Werteliste -> Verhaltenspruefung auf dem echten Schema in
# ``test_check_free_text_fields_real_schema.py``: ein Wert ausserhalb der
# Liste ist 422 (nie 500), und zwar ueber genau den hier genannten Pfad:
#   schema      -> Pydantic lehnt ab,
#   router      -> der Router lehnt fachlich ab,
#   central_422 -> erst die DB; zentraler Handler (DB_CHECK_CONSTRAINT_VIOLATION),
#   derived     -> der Router leitet den Wert ab (normalize_nature); die Eingabe
#                  wird verworfen, gespeichert wird ein CHECK-Wert.
STR_FIELD_POLICY: dict[str, str] = {
    "schemas.clients.ClientCreate.civil_status": "central_422",
    "schemas.clients.ClientCreate.partner_salutation": "central_422",
    "schemas.clients.ClientUpdate.civil_status": "central_422",
    "schemas.clients.ClientUpdate.partner_salutation": "central_422",
    "schemas.review.ConflictDisclosureCreate.inducement_frequency": "central_422",
    "schemas.review.ConflictDisclosureCreate.mitigation_action": "central_422",
    "schemas.review.ConflictMitigateRequest.mitigation_action": "central_422",
    "schemas.review.ProductCreate.product_type": "central_422",
    "schemas.review.ProductUpdate.product_type": "router",
    "schemas.review.ReviewTriggerCreate.frequency": "schema",
    "schemas.users.AdviserRegistrationCreate.register_status": "central_422",
    "schemas.wealth.CashflowCreate.frequency": "schema",
    "schemas.wealth.CashflowUpdate.frequency": "schema",
    "schemas.wealth.CashflowUpdate.nature": "derived",
    "schemas.wealth.GoalCreate.frequency": "schema",
    "schemas.wealth.GoalCreate.hardness": "schema",
    "schemas.wealth.GoalUpdate.goal_family": "schema",
    "schemas.wealth.GoalUpdate.goal_type": "schema",
    "schemas.wealth.GoalUpdate.goal_scope": "schema",
    "schemas.wealth.GoalUpdate.value_mode": "schema",
    "schemas.wealth.GoalUpdate.frequency": "router",
    "schemas.wealth.GoalUpdate.hardness": "schema",
    "schemas.wealth.WealthPositionUpdate.assignment": "router",
}

# Literal-Felder, die nicht in die gleichnamige CHECK-Spalte geschrieben werden.
NOT_PERSISTED: dict[str, str] = {
    "schemas.wealth.MaxPensionSpendingRequest.value_mode":
        "Rechenparameter fuer eine Simulation, kein goals-Eintrag",
}

# Dokumentierte Kanonisierung an der API-Grenze: (Tabelle, Spalte) -> Funktion.
CANONICALIZERS: dict[tuple[str, str], typing.Callable[[str], str]] = {
    ("goals", "goal_type"): vocab.canonical_goal_type,
    ("goals", "goal_family"): vocab.canonical_goal_family,
    ("goals", "hardness"): vocab.canonical_goal_hardness,
    ("goals", "goal_scope"): vocab.canonical_goal_scope,
    ("risk_assessments", "investment_horizon_label"): canonicalize_horizon_label,
}


def _sql_check_lists() -> dict[tuple[str, str], set[str]]:
    raw = reference_check_in_lists((BACKEND_ROOT / "ares_schema.sql").read_text(encoding="utf-8"))
    return {key: {lit[1:-1].replace("''", "'") for lit in lits} for key, lits in raw.items()}


def _orm_check_lists() -> dict[tuple[str, str], set[str]]:
    """CHECK-Wertelisten aus den ORM-Modellen (``CheckConstraint``), z.B. privacy_*,
    Sustainability -- Quelle fuer create_all und die PG-Baseline."""
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.schema import CreateTable

    out: dict[tuple[str, str], set[str]] = {}
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=sqlite.dialect()))
        try:
            parsed = parse_table_ddl(ddl)
        except DdlParseError:
            continue
        for check in parsed.checks:
            if isinstance(check, SupportedCheck):
                out.setdefault((table.name, check.column), set()).update(check.values)
    return out


_ALEMBIC_TABLE = re.compile(r"""(?:create_table|batch_alter_table)\(\s*(?:["'](\w+)["']|([A-Za-z_]\w*)\s*[,)])""")
_ALEMBIC_IN = re.compile(r"""["'](\w+) IN \(((?:\s*'[^']*'\s*,?)+)\)["']""")


def _alembic_check_lists() -> dict[tuple[str, str], set[str]]:
    """``col IN ('a','b')``-CHECKs aus den Alembic-Revisionen (PostgreSQL-Pfad)."""
    out: dict[tuple[str, str], set[str]] = {}
    for path in sorted((BACKEND_ROOT / "alembic" / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _ALEMBIC_IN.finditer(text):
            constants = dict(re.findall(r"""^([A-Z_]+)\s*=\s*["'](\w+)["']""", text, re.M))
            tables = [
                literal or constants.get(name)
                for literal, name in _ALEMBIC_TABLE.findall(text[: match.start()])
            ]
            tables = [t for t in tables if t]
            if not tables:
                continue
            values = set(re.findall(r"'([^']*)'", match.group(2)))
            out.setdefault((tables[-1], match.group(1)), set()).update(values)
    return out


CHECK_SOURCES: dict[str, dict[tuple[str, str], set[str]]] = {
    "ares_schema.sql": _sql_check_lists(),
    "orm": _orm_check_lists(),
    "alembic": _alembic_check_lists(),
}


def _merged_checks() -> dict[tuple[str, str], set[str]]:
    """Pro Spalte die Werte, die JEDE Quelle mit einer Liste akzeptiert."""
    merged: dict[tuple[str, str], set[str]] = {}
    for lists in CHECK_SOURCES.values():
        for key, values in lists.items():
            merged[key] = merged[key] & values if key in merged else set(values)
    return merged


CHECKS = _merged_checks()
ORM_TABLES = {
    mapper.class_.__name__: mapper.local_table.name
    for mapper in Base.registry.mappers
    if getattr(mapper.local_table, "name", None)
}


def _literals(annotation) -> set[str]:
    if typing.get_origin(annotation) is typing.Literal:
        return {a for a in typing.get_args(annotation) if isinstance(a, str)}
    out: set[str] = set()
    for arg in typing.get_args(annotation):
        out |= _literals(arg)
    return out


def _write_schemas() -> list[tuple[str, type[BaseModel]]]:
    found: dict[type, str] = {}
    for info in pkgutil.walk_packages(schemas.__path__, "schemas."):
        module = importlib.import_module(info.name)
        for name, cls in vars(module).items():
            if (inspect.isclass(cls) and issubclass(cls, BaseModel)
                    and cls.__module__ == module.__name__ and WRITE_SUFFIX.search(name)):
                found.setdefault(cls, f"{module.__name__}.{name}")
    return sorted(((qual, cls) for cls, qual in found.items()), key=lambda item: item[0])


def _target_table(qualname: str) -> str | None:
    if qualname in EXPLICIT_TARGETS:
        return EXPLICIT_TARGETS[qualname]
    return ORM_TABLES.get(WRITE_SUFFIX.sub("", qualname.rsplit(".", 1)[1]))


def _literal_fields():
    for qualname, cls in _write_schemas():
        for field, info in cls.model_fields.items():
            values = _literals(info.annotation)
            if values:
                yield qualname, field, values


def test_reference_schema_has_check_lists():
    """Positivkontrolle: ohne geparste CHECK-Listen waere alles gruen ohne Aussage."""
    assert ("goals", "goal_type") in CHECKS
    assert "Vermögensziel" in CHECKS[("goals", "goal_type")]
    assert len(CHECKS) > 50


def test_orm_and_alembic_check_sources_are_read():
    """Positivkontrolle N-903-01: ORM- und Alembic-CHECKs fliessen ein."""
    for source in ("orm", "alembic"):
        tables = {table for table, _column in CHECK_SOURCES[source]}
        assert any(t.startswith("privacy_") for t in tables), (source, sorted(tables))
        assert any("sustainability" in t for t in tables), (source, sorted(tables))


def test_free_text_check_fields_are_registered():
    """Vollstaendigkeit N-903-01: jedes freie str-Feld eines Schreib-Schemas, das
    in eine CHECK-Spalte schreibt, hat eine gepruefte 422-Strategie."""
    found: set[str] = set()
    for qualname, cls in _write_schemas():
        table = _target_table(qualname)
        for field, info in cls.model_fields.items():
            args = typing.get_args(info.annotation) or (info.annotation,)
            if str not in args or _literals(info.annotation):
                continue
            if table is not None and (table, field) in CHECKS:
                found.add(f"{qualname}.{field}")
    assert found == set(STR_FIELD_POLICY), (
        f"neu/unregistriert: {sorted(found - set(STR_FIELD_POLICY))}; "
        f"veraltet: {sorted(set(STR_FIELD_POLICY) - found)}"
    )
    assert set(STR_FIELD_POLICY.values()) <= {"schema", "router", "central_422", "derived"}


def test_write_schema_literals_are_subset_of_db_check_lists():
    drifts: list[str] = []
    checked = 0
    for qualname, field, values in _literal_fields():
        table = _target_table(qualname)
        if table is None or (table, field) not in CHECKS:
            continue
        if f"{qualname}.{field}" in NOT_PERSISTED:
            continue
        canonical = CANONICALIZERS.get((table, field), lambda v: v)
        missing = sorted(v for v in values if canonical(v) not in CHECKS[(table, field)])
        checked += 1
        if missing:
            drifts.append(f"{qualname}.{field} -> {table}.{field}: {missing}")
    assert checked >= 50, f"nur {checked} Felder geprueft -- Zuordnung kaputt?"
    assert not drifts, "Enum-Werte ohne DB-CHECK-Gegenstueck (500 beim Commit):\n" + "\n".join(drifts)


def test_every_check_backed_literal_field_is_mapped_or_exempt():
    check_columns = {column for _table, column in CHECKS}
    unmapped: list[str] = []
    for qualname, field, _values in _literal_fields():
        if field not in check_columns or f"{qualname}.{field}" in NOT_PERSISTED:
            continue
        table = _target_table(qualname)
        if table is None:
            unmapped.append(f"{qualname}.{field}")
    assert not unmapped, (
        "Schreib-Schema ohne Tabellen-Zuordnung (EXPLICIT_TARGETS ergaenzen oder "
        "in NOT_PERSISTED begruenden):\n" + "\n".join(unmapped)
    )


def test_canonicalizers_drift_detection_positive_control():
    """Die Pruefung erkennt eine Drift: ohne Kanonisierung fehlt 'Vermoegensziel'."""
    assert "Vermoegensziel" in _literals(wealth_schemas.GoalCreate.model_fields["goal_type"].annotation)
    assert "Vermoegensziel" not in CHECKS[("goals", "goal_type")]
    assert vocab.canonical_goal_type("Vermoegensziel") == "Vermögensziel"


@pytest.mark.parametrize("constant, key", [
    ("GOAL_FAMILY_DB_VALUES", ("goals", "goal_family")),
    ("GOAL_TYPE_DB_VALUES", ("goals", "goal_type")),
    ("GOAL_HARDNESS_DB_VALUES", ("goals", "hardness")),
    ("GOAL_SCOPE_DB_VALUES", ("goals", "goal_scope")),
    ("GOAL_VALUE_MODE_DB_VALUES", ("goals", "value_mode")),
])
def test_goal_db_value_constants_equal_check_lists(constant, key):
    assert set(getattr(vocab, constant)) == CHECK_SOURCES["ares_schema.sql"][key]


def test_goal_family_type_map_is_db_consistent_after_canonicalization():
    for family, types in wealth_schemas.GOAL_FAMILY_TYPE_MAP.items():
        assert family in CHECKS[("goals", "goal_family")]
        for goal_type in types:
            assert vocab.canonical_goal_type(goal_type) in CHECKS[("goals", "goal_type")]


def _classic_goal_type_options() -> set[str]:
    html = read_monolith_bundle()
    select = re.search(r'<select[^>]*id="nz-type"[^>]*>(.*?)</select>', html, re.S)
    assert select, "Classic-Zieltyp-Auswahl (nz-type) nicht gefunden"
    return set(re.findall(r'<option value="([^"]+)"', select.group(1)))


def _react_goal_types() -> set[str]:
    src = REPO_ROOT / "ares-desktop" / "frontend" / "reporting" / "src"
    form = (src / "lib" / "goalForm.ts").read_text(encoding="utf-8")
    block = re.search(r"Vermögen:\s*\[(.*?)\],.*?Maximierung:\s*\[(.*?)\]", form, re.S)
    assert block, "GOAL_FAMILY_TYPE_MAP-Spiegel in goalForm.ts nicht gefunden"
    map_block = form[block.start():block.end()]
    values = set(re.findall(r"'([A-Za-zÄÖÜäöü_]+)'", map_block))
    wizard = (src / "sections" / "goals" / "GoalWizard.tsx").read_text(encoding="utf-8")
    values |= set(re.findall(r"goal_type:\s*'([^']+)'", wizard))
    return values


@pytest.mark.parametrize("source", ["classic", "react"])
def test_ui_goal_types_are_db_values_after_canonicalization(source):
    values = _classic_goal_type_options() if source == "classic" else _react_goal_types()
    assert len(values) >= 6, values
    allowed = CHECKS[("goals", "goal_type")]
    missing = sorted(v for v in values if vocab.canonical_goal_type(v) not in allowed)
    assert not missing, f"{source}-Maske bietet goal_type ohne DB-Gegenstueck an: {missing}"


def test_registered_goal_canonicalizers_are_applied_by_create_and_update():
    """Die Kanonisierer oben sind nicht nur registriert, sondern werden von
    GoalCreate UND GoalUpdate mit denselben Regeln angewendet (N-903-03/-04;
    an fb83c8e7 rot: GoalCreate lehnte 'Vermoegen' ab, GoalUpdate speicherte roh)."""
    aliases = {
        "goal_family": "Vermoegen", "goal_type": "Vermoegensziel",
        "goal_scope": "Gesamtvermoegen", "hardness": "Primaer",
    }
    expected = {
        "goal_family": "Vermögen", "goal_type": "Vermögensziel",
        "goal_scope": "Gesamtvermögen", "hardness": "Primär",
    }
    created = wealth_schemas.GoalCreate.model_validate({
        **aliases, "label": "Umbau Wohneigentum", "rank": 1,
        "target_wealth_rappen": 250_000_00, "horizon_years": 6,
    })
    updated = wealth_schemas.GoalUpdate.model_validate(aliases)
    for model in (created, updated):
        assert {field: getattr(model, field) for field in expected} == expected
    for (table, column), canonical in CANONICALIZERS.items():
        if table == "goals":
            assert canonical(aliases[column]) == expected[column]
