"""C-DSG-01: Verzeichnis der Bearbeitungstaetigkeiten als versionierte Daten.

Das Register liegt als Datendatei im Repository
(``config/processing_activities.json``) und wird mit dem Backend ausgeliefert.
Es beschreibt je Bearbeitung Zweck, betroffene Personen, Datenkategorien,
Tabellen, Empfaenger, ausgehende Kanaele (Egress-Manifest), Aufbewahrung und
technisch-organisatorische Massnahmen (TOM).

Angaben, die nur der Verantwortliche (die Firma) machen kann -- Identitaet und
Kontakt, Begruendung der Aufbewahrungsdauer, Staaten und Garantien --, stehen
im Register als Platzhalter ``{"owner_field": "<schluessel>", ...}``. Ares
erfindet diese Werte nicht. Sie werden je Mandant in
``privacy_owner_values`` erfasst (services/dsg_governance.py); ein offener
Pflichtwert sperrt die kundenwirksame Ausgabe, nicht den Start der App.

``register_problems`` ist das Vollstaendigkeits-Gate (CI-Test
``tests/test_h10_c_dsg_01_processing_register.py``): jede Tabelle des Schemas
ist entweder einer Bearbeitung zugeordnet oder begruendet als Tabelle ohne
Personendaten gefuehrt; jede Tabelle des Loeschinventars (Kunden-/
Mandatsbezug) gehoert zu einer Bearbeitung, deren Datenkategorien ihre
Nachweisarten abdecken.
"""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from services import privacy_erasure_inventory as erasure_inventory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
REGISTER_PATH = BACKEND_ROOT / "config" / "processing_activities.json"

OWNER_FIELD = "owner_field"
BLOCKING_CUSTOMER_OUTPUT = "customer_output"
BLOCKING_CHANNEL = "channel"
BLOCKING_INFORMATIONAL = "informational"
BLOCKING_LEVELS = (BLOCKING_CUSTOMER_OUTPUT, BLOCKING_CHANNEL, BLOCKING_INFORMATIONAL)
OWNER_FIELD_KINDS = ("text", "country_list", "guarantee", "hours")

REQUIRED_ACTIVITY_KEYS = (
    "id", "name", "purpose", "data_subjects", "data_categories", "tables", "recipients",
    "egress_channels", "retention", "toms",
)


class RegisterUnavailable(RuntimeError):
    """Registerdatei fehlt oder ist kein gueltiges JSON (fail-closed)."""


def _canonical(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def document_sha256(document: Any) -> str:
    return hashlib.sha256(_canonical(document)).hexdigest()


@lru_cache(maxsize=4)
def _load(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegisterUnavailable(f"Register nicht lesbar: {path.name}: {exc}") from exc


def load_register(path: Path | None = None) -> dict[str, Any]:
    """Kopie des Registers (Aufrufer duerfen sie veraendern)."""
    return copy.deepcopy(_load(str(path or REGISTER_PATH)))


def iter_owner_fields(document: Any, *, source: str) -> list[dict[str, Any]]:
    """Alle Platzhalter ``{"owner_field": ...}`` eines Dokuments, in
    Dokumentreihenfolge."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if OWNER_FIELD in node:
                found.append({
                    "key": node[OWNER_FIELD],
                    "label": node.get("label") or node[OWNER_FIELD],
                    "kind": node.get("kind", "text"),
                    "blocking": node.get("blocking", BLOCKING_CUSTOMER_OUTPUT),
                    "channel": node.get("channel"),
                    "source": source,
                })
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    return found


def resolve_owner_fields(document: Any, values: dict[str, str]) -> Any:
    """Kopie des Dokuments, in der jeder Platzhalter Status und ggf. Wert
    traegt (``CONFIRMED`` mit Wert oder ``OPEN`` ohne Wert)."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if OWNER_FIELD in node:
                key = node[OWNER_FIELD]
                resolved = {OWNER_FIELD: key, "label": node.get("label") or key}
                if values.get(key):
                    resolved.update(status="CONFIRMED", value=values[key])
                else:
                    resolved.update(status="OPEN", value=None)
                return resolved
            return {name: walk(value) for name, value in node.items()}
        if isinstance(node, list):
            return [walk(value) for value in node]
        return node

    return walk(copy.deepcopy(document))


def _tom_evidence_problems(register: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for tom_id, tom in sorted((register.get("toms") or {}).items()):
        if not str(tom.get("description") or "").strip():
            problems.append(f"{tom_id}: TOM ohne Beschreibung")
        evidence = tom.get("evidence") or []
        if not evidence:
            problems.append(f"{tom_id}: TOM ohne Code-Nachweis")
        for rel in evidence:
            if not (REPO_ROOT / rel).is_file():
                problems.append(f"{tom_id}: Nachweis {rel} existiert nicht")
    return problems


def register_problems(
    metadata_tables: dict, register: dict[str, Any] | None = None, *, check_evidence_files: bool = True,
) -> list[str]:
    """Widersprueche zwischen Register und Schema (leer = vollstaendig)."""
    reg = register if register is not None else load_register()
    problems: list[str] = []
    names = set(metadata_tables)
    activities = reg.get("activities") or []
    non_personal = reg.get("non_personal_tables") or {}
    subjects = set(reg.get("data_subject_categories") or {})
    categories = set(erasure_inventory.EVIDENCE_TYPES) | set(reg.get("additional_data_categories") or {})
    toms = set(reg.get("toms") or {})

    if not str(reg.get("register_version") or "").strip():
        problems.append("Register ohne register_version")
    if not activities:
        problems.append("Register ohne Bearbeitungen")

    seen_ids: set[str] = set()
    assigned: dict[str, set[str]] = {}
    for activity in activities:
        activity_id = str(activity.get("id") or "?")
        if activity_id in seen_ids:
            problems.append(f"{activity_id}: Bearbeitung doppelt")
        seen_ids.add(activity_id)
        for key in REQUIRED_ACTIVITY_KEYS:
            if key not in activity:
                problems.append(f"{activity_id}: Pflichtangabe {key} fehlt")
        for key in ("name", "purpose"):
            if not str(activity.get(key) or "").strip():
                problems.append(f"{activity_id}: {key} leer")
        for key in ("data_subjects", "data_categories", "tables", "recipients", "toms"):
            if not activity.get(key):
                problems.append(f"{activity_id}: {key} leer")
        for subject in activity.get("data_subjects") or []:
            if subject not in subjects:
                problems.append(f"{activity_id}: unbekannte Personenkategorie {subject}")
        for category in activity.get("data_categories") or []:
            if category not in categories:
                problems.append(f"{activity_id}: unbekannte Datenkategorie {category}")
        for tom in activity.get("toms") or []:
            if tom not in toms:
                problems.append(f"{activity_id}: unbekannte TOM {tom}")
        retention = activity.get("retention") or {}
        if not str(retention.get("source") or "").strip():
            problems.append(f"{activity_id}: Aufbewahrung ohne Quelle")
        if OWNER_FIELD not in (retention.get("basis") or {}):
            problems.append(f"{activity_id}: Aufbewahrungsbegruendung ist kein Owner-Feld")
        for evidence_type in retention.get("evidence_types") or []:
            if evidence_type not in erasure_inventory.EVIDENCE_TYPES:
                problems.append(f"{activity_id}: unbekannte Nachweisart {evidence_type} in der Aufbewahrung")
        for table in activity.get("tables") or []:
            assigned.setdefault(table, set()).add(activity_id)
            if table not in names:
                problems.append(f"{activity_id}: unbekannte Tabelle {table}")

    for table in sorted(set(assigned) & set(non_personal)):
        problems.append(f"{table}: zugleich einer Bearbeitung zugeordnet und als ohne Personendaten gefuehrt")
    for table, reason in sorted(non_personal.items()):
        if table not in names:
            problems.append(f"Register nennt unbekannte Tabelle ohne Personendaten: {table}")
        if not str(reason or "").strip():
            problems.append(f"{table}: ohne Begruendung als Tabelle ohne Personendaten gefuehrt")
    for table in sorted(names - set(assigned) - set(non_personal)):
        problems.append(f"Tabelle ohne Zuordnung im Bearbeitungsverzeichnis: {table}")

    by_id = {str(a.get("id")): a for a in activities}
    personal = set(erasure_inventory.PERSONAL_DATA_INVENTORY) | set(erasure_inventory.EXEMPT_TABLES)
    for table in sorted(personal & names):
        if table in non_personal:
            problems.append(f"{table}: im Loeschinventar (Personendaten), aber als ohne Personendaten gefuehrt")
            continue
        covering = assigned.get(table, set())
        if not covering:
            continue  # bereits oben als ohne Zuordnung gemeldet
        covered = set()
        for activity_id in covering:
            covered |= set(by_id[activity_id].get("data_categories") or [])
        for category in erasure_inventory.categories_for(table):
            if category.evidence_type not in covered:
                problems.append(
                    f"{table}: Nachweisart {category.evidence_type} von keiner zugeordneten Bearbeitung abgedeckt"
                )

    keys = [field["key"] for field in iter_owner_fields(reg, source="register")]
    for key in sorted({k for k in keys if keys.count(k) > 1}):
        problems.append(f"Owner-Feld {key} mehrfach definiert")
    for field in iter_owner_fields(reg, source="register"):
        if field["blocking"] not in BLOCKING_LEVELS:
            problems.append(f"Owner-Feld {field['key']}: unbekannte Sperrwirkung {field['blocking']}")
        if field["kind"] not in OWNER_FIELD_KINDS:
            problems.append(f"Owner-Feld {field['key']}: unbekannte Art {field['kind']}")
    if check_evidence_files:
        problems.extend(_tom_evidence_problems(reg))
    return problems


def register_summary(register: dict[str, Any]) -> dict[str, Any]:
    return {
        "register_version": register.get("register_version"),
        "schema_version": register.get("schema_version"),
        "register_sha256": document_sha256(register),
        "activities": len(register.get("activities") or []),
    }
