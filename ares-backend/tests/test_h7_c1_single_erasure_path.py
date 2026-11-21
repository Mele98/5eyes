"""H7 C-1 (Compliance-Audit 2026-11-07, Luecke 1): ein einziger Loeschpfad.

Befund: ``POST /clients/{id}/erase`` redigierte sofort -- ohne Pruefung von
Aufbewahrungsfrist, Legal Hold oder aktivem Mandat -- auch die KYC-Belege
(``client_due_diligence``) und vernichtete die Kundenschluessel. Das umging
GwG Art. 7 Abs. 3 (Belege mindestens 10 Jahre nach Ende der
Geschaeftsbeziehung) und die Beweissicherung (OR 127).

Soll: der Direktpfad ist fail-closed (409, Reason-Code, Verweis auf den
Datenschutz-Workflow ``/privacy/erasure-cases``) und veraendert nichts. Nur
der Workflow entscheidet je Nachweisart nach genehmigter Aufbewahrungsmatrix
und Legal Hold. An der Basis 2e5dfcc3 sind diese Tests rot (200 + Redaktion).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from test_client_erasure import (  # noqa: F401
    NOW,
    _exec,
    _scalar,
    _seed_full_client_chain,
    admin_client,
    session_factory,
)
from services import privacy_erasure as pe

REASON = "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."


def _seed_kyc(session, client_id: str) -> None:
    _exec(
        session,
        """
        INSERT INTO client_due_diligence (
            id, client_id, pep_status, pep_details, acting_for_own_account,
            beneficial_owner_name, source_of_wealth, id_document_type,
            id_document_number, id_document_issuing_country, id_document_expiry,
            fatca_crs_self_certified, created_at, updated_at
        ) VALUES (
            'dd-c1', :cid, 1, 'Gemeinderat 2010-2018', 0,
            'Erika Muster', 'Erbschaft', 'Pass',
            'X1234567', 'CH', '2030-01-01', 1, :now, :now
        )
        """,
        {"cid": client_id, "now": NOW},
    )


def _kyc_row(session):
    return session.execute(
        __import__("sqlalchemy").text(
            "SELECT pep_details, beneficial_owner_name, source_of_wealth, id_document_number "
            "FROM client_due_diligence WHERE id='dd-c1'"
        )
    ).one()


def _assert_nothing_erased(session_factory, client_id: str) -> None:
    with session_factory() as session:
        assert _scalar(session, "SELECT first_name FROM clients WHERE id=:id", {"id": client_id}) == "Hans"
        assert _scalar(session, "SELECT erased_at FROM clients WHERE id=:id", {"id": client_id}) is None
        kyc = _kyc_row(session)
        assert tuple(kyc) == ("Gemeinderat 2010-2018", "Erika Muster", "Erbschaft", "X1234567")
        assert _scalar(session, "SELECT depot_bank FROM mandates WHERE id='mandate-e1'") != "[ERASED-DSG-ART-32]"


def _post_erase(admin_client, client_id: str):
    return admin_client.post(f"/clients/{client_id}/erase", json={"reason": REASON})


def test_legacy_erase_with_active_mandate_is_refused_and_keeps_kyc_evidence(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)
        _seed_kyc(session, ids["client_id"])
        session.commit()
        assert _scalar(session, "SELECT closed_at FROM mandates WHERE id='mandate-e1'") is None

    response = _post_erase(admin_client, ids["client_id"])

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["reason_code"] == "LEGACY_ERASURE_DISABLED"
    assert detail["workflow"] == "/privacy/erasure-cases"
    assert "Datenschutz-Workflow" in detail["message"]
    _assert_nothing_erased(session_factory, ids["client_id"])


def test_legacy_erase_with_active_legal_hold_is_refused(admin_client, session_factory):
    with session_factory() as session:
        ids = _seed_full_client_chain(session)
        _seed_kyc(session, ids["client_id"])
        _exec(
            session,
            """
            INSERT INTO privacy_legal_holds (
                id, tenant_id, client_id, case_reference, legal_reason, scope_json,
                set_by, approved_by, approved_at, review_date, status,
                extension_count, created_at, updated_at
            ) VALUES (
                'hold-c1', NULL, :cid, 'FALL-C1', 'Hängiges Verfahren',
                '["kyc_due_diligence"]', 'legal-a', 'priv-b', :now, '2099-12-31',
                'ACTIVE', 0, :now, :now
            )
            """,
            {"cid": ids["client_id"], "now": NOW},
        )
        session.commit()
        holds = pe.active_legal_holds(
            session, tenant_id=None, client_id=ids["client_id"], now=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )
        assert [h.id for h in holds] == ["hold-c1"]

    response = _post_erase(admin_client, ids["client_id"])

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason_code"] == "LEGACY_ERASURE_DISABLED"
    _assert_nothing_erased(session_factory, ids["client_id"])


def test_legacy_erase_is_refused_even_after_retention_period_single_path(admin_client, session_factory):
    """Auch wenn die Beziehung lange beendet ist (Frist abgelaufen), gibt es
    keinen zweiten Weg: die Loeschung laeuft ueber den Workflow, der die
    Frist aus der genehmigten Matrix entscheidet und einen Loeschbeleg
    schreibt."""
    with session_factory() as session:
        ids = _seed_full_client_chain(session)
        _seed_kyc(session, ids["client_id"])
        _exec(
            session,
            "UPDATE mandates SET closed_at='2010-01-31', status='Archiviert' WHERE id='mandate-e1'",
        )
        session.commit()

    response = _post_erase(admin_client, ids["client_id"])

    assert response.status_code == 409, response.text
    _assert_nothing_erased(session_factory, ids["client_id"])


def test_privacy_workflow_without_approved_matrix_keeps_kyc_pending(session_factory):
    """Gegenprobe zum einzigen verbleibenden Pfad: ohne genehmigte
    Aufbewahrungsmatrix bleibt die KYC-Nachweisart "Entscheid ausstehend"
    und die Ausfuehrung wird verweigert."""
    with session_factory() as session:
        ids = _seed_full_client_chain(session)
        _seed_kyc(session, ids["client_id"])
        session.commit()
        pe.ensure_privacy_tables(session)
        case = pe.open_erasure_case(
            session, client_id=ids["client_id"], opened_by="admin-erasure",
            now=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )
        assert case.status == "DECISION_PENDING"
        kyc_lines = [
            line for line in pe._case_lines(session, case.id) if line.evidence_type == "kyc_due_diligence"
        ]
        with_data = [line for line in kyc_lines if line.row_count]
        assert with_data and all(line.decision_status == "DECISION_PENDING" for line in with_data)
        try:
            pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-erasure")
        except Exception as exc:  # noqa: BLE001
            assert getattr(exc, "status_code", None) == 409
        else:  # pragma: no cover
            raise AssertionError("Ausfuehrung trotz offener Entscheide")
        session.rollback()
    _assert_nothing_erased(session_factory, ids["client_id"])
