"""K-2: ``import main`` registriert ``users`` (B-16).

K-2 hatte den Direktimport ``import models.users`` zunaechst aus ``main.py``
entfernt; seit K-2-Review M1 (``e101ed7d``) steht er dort wieder explizit.
Zusaetzlich registrieren Router, die ``main`` auf Modulebene vor der
App-Erzeugung importiert (``routers.auth`` u. a.), die Tabelle ``users``.
Damit weder ein kuenftiger Umbau von ``main.py`` noch ein Router-Umbau die
Registrierung still verliert, prueft dieser Test in einem frischen Interpreter:

1. Nach ``import main`` steht ``users`` in ``Base.metadata.tables``.
2. ``Base.metadata.sorted_tables`` (Tabellennamen in Reihenfolge) und
   ``app.openapi()`` (kanonisches JSON) haben exakt den Stand vor K-2
   (Golden-Hashes, berechnet auf ``origin/develop`` 1730911e und auf dem
   K-2-Head identisch; ``sorted_tables`` unveraendert seit 9e6b7dd9, der
   OpenAPI-Hash wurde beim Rebase auf 1730911e und mit OF-1 (Audit 2026-11/06,
   neue Felder exchange_code/exchange_code_status/candidates) nachgefuehrt). Aendert eine legitime Schema-/API-Aenderung einen
   Hash, wird der Golden-Wert bewusst im selben Commit nachgefuehrt.

Negativkontrolle: ``database`` allein registriert ``users`` nicht -- die
Pruefung ist also nicht trivial erfuellt.

Frischer Interpreter, damit bereits importierte Module anderer Tests das
Ergebnis nicht faerben; eigene ``DB_PATH`` unter ``tmp_path`` (der Import
oeffnet keine Datenbank, siehe test_openapi_artifact.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# H8 (2026-11-07): fuenf neue Tabellen (tenant_legal_profiles,
# client_information_deliveries, kyc_confirmations, kyc_confirmation_approvals,
# client_representations), keine bestehende Tabelle umbenannt/entfernt.
# C-890-01 (2026-11-11): zwei neue Tabellen (kyc_review_policies,
# kyc_review_policy_activations) und acht nullable Bindungsspalten an
# kyc_confirmations; keine bestehende Tabelle umbenannt/entfernt.
# C-890-01 Nachtrag 2: neue Tabelle kyc_confirmation_rejections.
GOLDEN_SORTED_TABLES_SHA256 = "8cc4d76454f92c7721a79d38f18a57c6ff1dfad247c9a1f5dadd1b9d5c2b3c21"
# N-869-0 (Pruefrunde #869): nachgefuehrt fuer GET /admin/system/audit-log/verify
# und die Schemas AuditChainGap/AuditChainSection/AuditChainVerification/
# AuditLegacySection (H-865-2). Kein bestehender Pfad, kein bestehendes Schema
# geaendert (Feld-Diff von api/openapi.json, vom Pruefer bestaetigt).
# N-869-2: AuditLegacySection + ambiguous/ambiguous_ids/unexpected_unhashed/
# unexpected_unhashed_ids (nur dieses Schema, Feld-Diff geprueft).
# N-869-4: nur die description von GET /admin/system/audit-log/verify
# (Docstring: Operator-Bypass unter PG-RLS), Feld-Diff geprueft.
# N-869-6: AuditChainSection + ambiguous/ambiguous_count, AuditLegacySection
# + field_shift/field_shift_ids (nur additiv, Feld-Diff geprueft).
# Bestandssiegel: AuditLegacySection + seal_present/seal_ok/seal_sequence/
# seal_count (nur additiv, Feld-Diff geprueft).
# N-869-8: AuditLegacySection + seal_missing (nur additiv, Feld-Diff geprueft).
# Integrationsprobe 2026-11-07: Pins aus #856, #862, #868 und #869 zusammen-
# gefuehrt; api/openapi.json (Git-Merge ohne Konflikt) besteht
# scripts/export_openapi.py --check.
# H7 C-1: nur description von POST /clients/{client_id}/erase (Direktpfad stillgelegt, 409), Feld-Diff geprueft.
# H7 C-6: neu POST /privacy/policies/baseline (+BaselineProposal); description GET/POST /clients/{client_id}/due-diligence (GwV-FINMA statt RS 2016/7), Feld-Diff geprueft.
# H8 (2026-11-07): neu GET/PUT /compliance/legal-profile, GET
# /mandates/{mandate_id}/client-onboarding/status, POST
# /mandates/{mandate_id}/client-information/deliveries, GET
# /mandates/{mandate_id}/reports/kundeninformation.pdf, GET/POST
# /clients/{client_id}/kyc-confirmations (+ /approve), GET/POST
# /clients/{client_id}/representations (+ /revoke) samt Schemas; geaendert nur
# ClientDueDiligenceUpdate/-Response (acting_for_own_account ohne Default, neu
# acting_for_own_account_answered) und OptHistoryCreate/-Response
# (opt_out_criteria, document_id, opt_out_criteria_json). Feld-Diff geprueft.
# H8 nach Merge H7 (N-890-07): Pins gemeinsam neu. N-890-02/03/12/13: Delivery
# (delivery_timing, backdating_reason), KYC (identification_*, requires_second_approval),
# OptHistoryCreate.event_type als FIDLEG-Werteliste. Feld-Diff geprueft.
# C-890-01: neu GET/POST /compliance/kyc-review-policies, POST
# /compliance/kyc-review-policies/{policy_row_id}/activate (+ KycReviewPolicy*-
# Schemas); Request-Body von POST /clients/{client_id}/kyc-confirmations heisst
# KycConfirmationRequest (Felder unveraendert; KycConfirmationCreate ist das
# policy-gebundene Fachobjekt); additiv: KycConfirmationResponse.review_*,
# ClientOnboardingFinding (kyc_review_status, policy_ref, binding_defect,
# bound_next_review_due, current_max_due), ClientOnboardingStatusResponse.
# kyc_review_policy. Feld-Diff geprueft.
# C-890-01 Nachtrag 1: Rolle "compliance_reviewer" in UserCreate/UserUpdate/
# Einladung (Literal erweitert) und description von POST
# /compliance/kyc-review-policies/{policy_row_id}/activate. Feld-Diff geprueft.
# C-890-01 Nachtrag 2: neu GET /compliance/kyc-approvals, POST
# /compliance/kyc-approvals/{confirmation_id}/decision (+ KycPendingApproval*,
# KycSecondApproval*-Schemas); kein bestehender Pfad, kein bestehendes Schema
# geaendert. Feld-Diff geprueft.
GOLDEN_OPENAPI_SHA256 = "19b4d3529adeec26392f4e876fe616d95ae9c1f4f39ba19e3c15c77576912847"

_PROBE = """
import hashlib, json
{imports}
from database import Base
tables = Base.metadata.tables
out = {{"users": "users" in tables, "count": len(tables)}}
if {with_app}:
    out["sorted_tables"] = hashlib.sha256(
        "\\n".join(t.name for t in Base.metadata.sorted_tables).encode("utf-8")
    ).hexdigest()
    out["openapi"] = hashlib.sha256(
        json.dumps(main.app.openapi(), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
print("PROBE=" + json.dumps(out))
"""


def _isolated_env(db_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["DB_PATH"] = str(db_path)
    for key in ("DATABASE_URL", "DB_KEY", "DB_USE_SQLCIPHER"):
        env.pop(key, None)
    return env


def _probe(tmp_path: Path, imports: str, with_app: bool) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(imports=imports, with_app=with_app)],
        cwd=BACKEND_DIR,
        env=_isolated_env(tmp_path / "probe.db"),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("PROBE=")][-1]
    return json.loads(line[len("PROBE="):])


def test_import_main_registers_users_and_keeps_pre_k2_schema(tmp_path):
    out = _probe(tmp_path, "import main", with_app=True)
    assert out["users"], "Tabelle users nach import main nicht registriert"
    assert out["sorted_tables"] == GOLDEN_SORTED_TABLES_SHA256, (
        "Base.metadata.sorted_tables weicht vom Stand vor K-2 ab"
    )
    assert out["openapi"] == GOLDEN_OPENAPI_SHA256, "app.openapi() weicht vom Stand vor K-2 ab"


def test_negative_control_database_alone_does_not_register_users(tmp_path):
    out = _probe(tmp_path, "", with_app=False)
    assert out["users"] is False, "users waere auch ohne main registriert -- Test waere trivial"
