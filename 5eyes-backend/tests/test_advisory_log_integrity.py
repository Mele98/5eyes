"""Sprint U-FINMA-2.1 — Tests fuer Integrity-Hash + retain_until."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.advisory_log_integrity import (  # noqa: E402
    RETENTION_YEARS,
    compute_integrity_hash,
    compute_retain_until,
    verify_integrity_hash,
)


def _base_payload(**overrides):
    base = {
        "mandate_id": "m-1",
        "advisor_id": "a-1",
        "entry_type": "Jahresreview",
        "entry_datetime": "2026-05-28T14:00:00.000Z",
        "duration_minutes": 60,
        "communication_channel": "persoenlich",
        "language": "de",
        "location": "Buero Zuerich",
        "title": "Jahresreview 2026",
        "description": "Strategie besprochen, Allokation angepasst, Risiko diskutiert.",
        "decision": "Strategie angepasst",
        "status": "Empfohlen",
        "participants_json": '[{"role":"client","name":"Daniel Beispiel"}]',
        "topics_json": '["SAA","Risikoprofil"]',
        "risk_warnings_given_json": '["Marktrisiko","FX-Risiko"]',
        "cost_disclosure_given": 1,
        "conflict_disclosure_ids_json": "[]",
        "suitability_check_id": None,
        "recommendation_run_id": None,
        "client_signed": 0,
        "client_signed_at": None,
        "version": 1,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# compute_integrity_hash
# ---------------------------------------------------------------------------

def test_hash_is_64_hex_chars():
    h = compute_integrity_hash(payload=_base_payload())
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_deterministic():
    h1 = compute_integrity_hash(payload=_base_payload())
    h2 = compute_integrity_hash(payload=_base_payload())
    assert h1 == h2


def test_hash_changes_when_description_changes():
    h1 = compute_integrity_hash(payload=_base_payload())
    h2 = compute_integrity_hash(payload=_base_payload(description="Anders."))
    assert h1 != h2


def test_hash_changes_when_decision_changes():
    h1 = compute_integrity_hash(payload=_base_payload())
    h2 = compute_integrity_hash(payload=_base_payload(decision="Override bestätigt"))
    assert h1 != h2


def test_hash_changes_when_risk_warnings_change():
    h1 = compute_integrity_hash(payload=_base_payload())
    h2 = compute_integrity_hash(payload=_base_payload(risk_warnings_given_json='["Marktrisiko"]'))
    assert h1 != h2


def test_hash_changes_with_version_increment():
    """Versionierung muss im Hash sichtbar sein."""
    h1 = compute_integrity_hash(payload=_base_payload(version=1))
    h2 = compute_integrity_hash(payload=_base_payload(version=2))
    assert h1 != h2


def test_hash_robust_against_missing_fields():
    """Fehlende Felder werden als leere Strings behandelt — kein Crash."""
    minimal = {
        "mandate_id": "m-1",
        "advisor_id": "a-1",
        "entry_type": "Sonstiges",
        "title": "X",
        "version": 1,
    }
    h = compute_integrity_hash(payload=minimal)
    assert len(h) == 64


def test_hash_field_order_is_stable():
    """Hash muss feldorder-unabhängig vom dict-Iteration sein."""
    p = _base_payload()
    # Reverse dict order
    reversed_p = dict(reversed(list(p.items())))
    h1 = compute_integrity_hash(payload=p)
    h2 = compute_integrity_hash(payload=reversed_p)
    assert h1 == h2, "Hash darf nicht von dict-Iteration-Order abhängen"


# ---------------------------------------------------------------------------
# verify_integrity_hash
# ---------------------------------------------------------------------------

def test_verify_returns_true_for_matching_hash():
    p = _base_payload()
    h = compute_integrity_hash(payload=p)
    assert verify_integrity_hash(payload=p, expected_hash=h) is True


def test_verify_returns_false_for_tampered_content():
    p = _base_payload()
    h = compute_integrity_hash(payload=p)
    p["description"] = "Manipuliert!"
    assert verify_integrity_hash(payload=p, expected_hash=h) is False


def test_verify_returns_false_for_wrong_length():
    p = _base_payload()
    assert verify_integrity_hash(payload=p, expected_hash="too_short") is False


def test_verify_returns_false_for_empty_hash():
    p = _base_payload()
    assert verify_integrity_hash(payload=p, expected_hash="") is False


# ---------------------------------------------------------------------------
# compute_retain_until — FIDLEG Art. 17: 10 Jahre Aufbewahrung
# ---------------------------------------------------------------------------

def test_retain_until_is_10_years_later():
    assert RETENTION_YEARS == 10
    r = compute_retain_until("2026-05-28T14:00:00.000Z")
    assert r == "2036-05-28"


def test_retain_until_handles_iso_without_z_suffix():
    r = compute_retain_until("2026-05-28T14:00:00")
    assert r == "2036-05-28"


def test_retain_until_handles_leap_day():
    """29. Februar in Schaltjahr → 28. Februar im Zieljahr (kein Crash)."""
    r = compute_retain_until("2024-02-29T10:00:00Z")
    # 2034 ist KEIN Schaltjahr → 28.02.2034 (defensiver Fallback)
    assert r == "2034-02-28"


def test_retain_until_falls_back_to_today_for_invalid_input():
    from datetime import datetime, timedelta, timezone

    r = compute_retain_until("not-a-date")
    # Sollte ~heute + 10 Jahre sein
    expected_year = datetime.now(timezone.utc).year + RETENTION_YEARS
    assert r.startswith(str(expected_year)), (
        f"Erwartet Jahr {expected_year}, gefunden {r}"
    )


def test_retain_until_handles_empty_string():
    from datetime import datetime, timezone

    r = compute_retain_until("")
    expected_year = datetime.now(timezone.utc).year + RETENTION_YEARS
    assert r.startswith(str(expected_year))
