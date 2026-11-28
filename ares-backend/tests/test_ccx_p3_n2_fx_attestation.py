"""CCX-P3 Nachtrag 2 -- belegte Kurse nur durch bewusste Erfassung/Bestaetigung.

N-909-11: Der Wechselkurs-Editor zeigt Ersatzkurse nur als Platzhalter
("Ersatzkurs – nicht belegt") und sendet nur geaenderte oder je Zeile als
"Kurs geprueft" bestaetigte Zeilen. Der Server macht aus einem unveraenderten
Kurs ohne Bestaetigung keinen neuen Beobachtungszeitpunkt (No-op), verlangt
fuer einen Kurs gleich dem Ersatzkurs die ausdrueckliche Bestaetigung und
auditiert die Bestaetigung ohne Aenderung (APPROVE).
N-909-14: Quelle ``Default`` wird normalisiert erkannt. N-909-08: mehr als
vier Dezimalen werden abgelehnt statt still gerundet. N-909-17: Identitaet
nur mit bekanntem, nicht leerem Code. N-909-19: Tenant-Frist wirkt.

Der UI-Weg laeuft ueber die echte Payload-Funktion ``fxRatesSavePayload`` aus
``fx-rates-editor.js`` (Node) und den echten Speicherweg ``PUT /fx-rates``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from core.reason_codes import DomainError
from services.currency.fx_rates import FxBasisError, FXRateSource
from services.fx_basis import load_fx_basis
from tests.test_e2e_thierry_goessi_walkthrough import (  # noqa: F401  (Fixtures)
    advisor_user,
    api,
    session_factory,
)

EDITOR = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "fx-rates-editor.js"


def _ui_payload(rows: list[dict]) -> dict:
    """Payload exakt wie der Editor ihn baut (Node, echte Funktion)."""
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    script = EDITOR.read_text(encoding="utf-8") + (
        "\nprocess.stdout.write(JSON.stringify(fxRatesSavePayload(" + json.dumps(rows) + ")));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _grid_rows(current: list[dict]) -> list[dict]:
    """So belegt der Editor das Grid: Ersatzkurs -> leerer Wert (Platzhalter)."""
    rows = []
    for entry in current:
        if entry["currency"] == "CHF":
            continue
        substitute = str(entry["source"]).strip().lower() in ("", "default")
        shown = f"{float(entry['rate']):.4f}"
        rows.append({"currency": entry["currency"], "value": "" if substitute else shown,
                     "original": "" if substitute else shown, "confirmed": False})
    return rows


def _current(api) -> dict[str, dict]:
    resp = api.get("/fx-rates/current")
    assert resp.status_code == 200, resp.text[:300]
    return {e["currency"]: e for e in resp.json()}


def _rows(session_factory, currency):
    with session_factory() as db:
        return db.execute(text(
            "SELECT id, rate_x10000, source, valid_from, is_current FROM fx_rates WHERE currency = :c ORDER BY created_at"
        ), {"c": currency}).all()


def _set_valid_from(session_factory, currency, days_old):
    stamp = (date.today() - timedelta(days=days_old)).isoformat() + "T08:00:00.000Z"
    with session_factory() as db:
        db.execute(text("UPDATE fx_rates SET valid_from = :v WHERE currency = :c AND is_current = 1"),
                   {"v": stamp, "c": currency})
        db.commit()
    return stamp


# ── N-909-11: UI-Payload ─────────────────────────────────────────────────────

def test_editor_payload_sends_only_changed_or_confirmed_rows():
    rows = [
        {"currency": "USD", "value": "0.9123", "original": "", "confirmed": False},      # neu erfasst
        {"currency": "EUR", "value": "", "original": "", "confirmed": False},            # Ersatzkurs-Platzhalter
        {"currency": "GBP", "value": "1.1000", "original": "1.1000", "confirmed": False},  # unveraendert
        {"currency": "JPY", "value": "0.0063", "original": "0.0063", "confirmed": True},   # bestaetigt
        {"currency": "CAD", "value": "", "original": "", "confirmed": True},             # nichts zu bestaetigen
    ]
    assert _ui_payload(rows) == {"rates": [
        {"currency": "USD", "rate": 0.9123, "source": "Manual"},
        {"currency": "JPY", "rate": 0.0063, "source": "Manual", "confirm_current": True},
    ]}


def test_ui_save_of_usd_does_not_attest_or_refresh_other_currencies(api, session_factory):
    """Prueferfall N-909-11 ueber den echten Speicherweg: nur USD wird geaendert."""
    api.put("/fx-rates", json={"rates": [
        {"currency": "EUR", "rate": 0.9412, "source": "Manual", "notes": "Testvektor"}]})
    eur_stamp = _set_valid_from(session_factory, "EUR", 3)
    eur_rows_before = _rows(session_factory, "EUR")

    rows = _grid_rows(list(_current(api).values()))
    for row in rows:
        if row["currency"] == "USD":
            row["value"] = "0.9123"
    payload = _ui_payload(rows)
    assert [e["currency"] for e in payload["rates"]] == ["USD"]
    resp = api.put("/fx-rates", json=payload)
    assert resp.status_code == 200, resp.text[:300]

    after = _current(api)
    assert after["USD"]["source"] == "Manual" and after["USD"]["rate"] == pytest.approx(0.9123)
    for ccy in ("GBP", "JPY", "CAD"):
        assert after[ccy]["source"] == "Default", (ccy, after[ccy])
    assert _rows(session_factory, "EUR") == eur_rows_before  # Frist nicht erneuert
    assert after["EUR"]["valid_from"] == eur_stamp
    with session_factory() as db:
        strict = FXRateSource.from_db_strict_for_model(db)
        assert strict.convert_storage_amount(100_00, "USD", "CHF") == 91_23
        for ccy in ("GBP", "JPY"):
            with pytest.raises(FxBasisError) as exc:
                strict.convert_storage_amount(100_000_00, ccy, "CHF")
            assert exc.value.reason_code == "CCX_FX_BASIS_MISSING"
            basis = load_fx_basis(db, "CHF", [ccy])
            assert basis.status(ccy) == "MISSING"


def test_resend_unchanged_is_noop_and_confirmation_is_audited(api, session_factory):
    assert api.put("/fx-rates", json={"rates": [{"currency": "USD", "rate": 0.9123}]}).status_code == 200
    stamp = _set_valid_from(session_factory, "USD", 4)
    before = _rows(session_factory, "USD")

    # Gleicher Kurs, gleiche Quelle, ohne Bestaetigung: keine neue Zeile, Frist bleibt.
    for source in ("Manual", " manual "):
        resp = api.put("/fx-rates", json={"rates": [{"currency": "USD", "rate": 0.9123, "source": source}]})
        assert resp.status_code == 200, resp.text[:300]
    assert _rows(session_factory, "USD") == before
    assert _current(api)["USD"]["valid_from"] == stamp

    # Bestaetigung ohne Aenderung: neue Beobachtung, eigener Audit-Eintrag.
    resp = api.put("/fx-rates", json={"rates": [
        {"currency": "USD", "rate": 0.9123, "source": "Manual", "confirm_current": True}]})
    assert resp.status_code == 200, resp.text[:300]
    rows = _rows(session_factory, "USD")
    assert len(rows) == len(before) + 1 and rows[-1].is_current == 1
    assert rows[-1].valid_from[:10] == datetime.now(timezone.utc).date().isoformat()
    with session_factory() as db:
        audit = db.execute(text(
            "SELECT action, new_value FROM audit_log WHERE table_name = 'fx_rates' AND field_name = 'USD' "
            "ORDER BY sequence"
        )).all()
    assert [a.action for a in audit] == ["UPSERT", "APPROVE"]
    assert "geprueft" in audit[-1].new_value and "Manual" in audit[-1].new_value


def test_substitute_value_needs_explicit_confirmation(api):
    resp = api.put("/fx-rates", json={"rates": [{"currency": "EUR", "rate": 0.95, "source": "Manual"}]})
    assert resp.status_code == 422 and "Ersatzkurs" in resp.text, resp.text[:300]
    assert _current(api)["EUR"]["source"] == "Default"
    # Bestaetigung eines Ersatzkurses als Quelle Default ist unzulaessig.
    resp = api.put("/fx-rates", json={"rates": [
        {"currency": "EUR", "rate": 0.95, "source": "Default", "confirm_current": True}]})
    assert resp.status_code == 422, resp.text[:300]
    resp = api.put("/fx-rates", json={"rates": [
        {"currency": "EUR", "rate": 0.95, "source": "Manual", "confirm_current": True}]})
    assert resp.status_code == 200, resp.text[:300]
    assert _current(api)["EUR"]["source"] == "Manual"


def test_batch_is_validated_before_any_write(api, session_factory):
    resp = api.put("/fx-rates", json={"rates": [
        {"currency": "USD", "rate": 0.9123, "source": "Manual"},
        {"currency": "EUR", "rate": 0.95, "source": "Manual"}]})  # Ersatzkurs ohne Bestaetigung
    assert resp.status_code == 422
    assert _rows(session_factory, "USD") == []


@pytest.mark.parametrize("rate", [0.00584, 0.91234])
def test_more_than_four_decimals_is_rejected_not_rounded(api, session_factory, rate):
    """N-909-08: kein stilles Runden im Router (Speicherformat x10000)."""
    resp = api.put("/fx-rates", json={"rates": [{"currency": "JPY", "rate": rate, "source": "Manual"}]})
    assert resp.status_code == 422, resp.text[:300]
    assert _rows(session_factory, "JPY") == []


# ── N-909-14: Quelle normalisiert ────────────────────────────────────────────

@pytest.mark.parametrize("source", ["default", "DEFAULT", " Default", "Default "])
def test_substitute_source_in_any_spelling_is_missing(api, session_factory, source):
    resp = api.put("/fx-rates", json={"rates": [{"currency": "USD", "rate": 0.9123, "source": source}]})
    assert resp.status_code == 200, resp.text[:300]
    with session_factory() as db:
        with pytest.raises(FxBasisError) as exc:
            FXRateSource.from_db_strict_for_model(db).convert_storage_amount(100_00, "USD", "CHF")
        assert exc.value.reason_code == "CCX_FX_BASIS_MISSING"
        assert load_fx_basis(db, "CHF", ["USD"]).status("USD") == "MISSING"


# ── N-909-17: Identitaet ─────────────────────────────────────────────────────

def test_identity_requires_known_non_empty_code(session_factory):
    with session_factory() as db:
        strict = FXRateSource.from_db_strict_for_model(db)
        assert strict.convert_storage_amount(5_00, "eur", "EUR") == 5_00
        assert strict.cross_rate("JPY", "jpy") == 1.0
        for code in ("", None):
            with pytest.raises(FxBasisError):
                strict.convert_storage_amount(5_00, code, code)
            with pytest.raises(FxBasisError):
                strict.cross_rate(code, code)
        with pytest.raises(ValueError):
            strict.convert_storage_amount(5_00, "XXX", "XXX")
        with pytest.raises(ValueError):
            strict.cross_rate("XXX", "XXX")


# ── N-909-16: Kurs und Status aus denselben Zeilen ───────────────────────────

def test_rate_and_status_come_from_the_same_rows(api, session_factory):
    assert api.put("/fx-rates", json={"rates": [{"currency": "USD", "rate": 0.9123}]}).status_code == 200
    with session_factory() as db:
        strict = FXRateSource.from_db_strict_for_model(db)
        # Paralleler Wechsel NACH dem Laden: die Quelle bleibt bei ihren Zeilen
        # (alter Kurs + alter Status), kombiniert nie alt mit neu.
        db.execute(text("UPDATE fx_rates SET source = 'Default' WHERE currency = 'USD'"))
        assert strict.convert_storage_amount(100_00, "USD", "CHF") == 91_23
        db.rollback()


# ── N-909-19: Tenant-Frist ───────────────────────────────────────────────────

def _tenant(session_factory, days):
    from models.tenant import Tenant

    now = datetime.now(timezone.utc).isoformat()
    with session_factory() as db:
        db.add(Tenant(id=f"t-{days}", display_name=f"t-{days}", slug=f"t-{days}",
                      fx_max_age_days=days, created_at=now, updated_at=now))
        db.commit()
    return f"t-{days}"


@pytest.mark.parametrize("max_age,days_old,expected", [
    (2, 2, "OK"), (2, 3, "STALE"), (10, 10, "OK"), (10, 11, "STALE"), (None, 5, "OK"), (None, 6, "STALE"),
])
def test_tenant_fx_max_age_days_drives_strict_source_and_basis(api, session_factory, max_age, days_old, expected):
    assert api.put("/fx-rates", json={"rates": [{"currency": "USD", "rate": 0.9123}]}).status_code == 200
    _set_valid_from(session_factory, "USD", days_old)
    tenant_id = _tenant(session_factory, max_age) if max_age is not None else None
    with session_factory() as db:
        assert load_fx_basis(db, "CHF", ["USD"], tenant_id=tenant_id).status("USD") == expected
        strict = FXRateSource.from_db_strict_for_model(db, tenant_id=tenant_id)
        if expected == "OK":
            assert strict.convert_storage_amount(100_00, "USD", "CHF") == 91_23
        else:
            with pytest.raises(DomainError) as exc:
                strict.convert_storage_amount(100_00, "USD", "CHF")
            assert exc.value.reason_code == "CCX_FX_BASIS_STALE"
