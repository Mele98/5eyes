"""H-187 Fixrunde 1 (Pruefung N-935-01..06).

N-935-01 Der Server nimmt nie ein Testpaket an: kein Settings-Feld, die gepackte
EXE liest keine .env, eine Umgebungsvariable (jede Schreibweise) wirkt nicht.
Der Strategie-Nachweis laeuft als ``--self-test-strategy`` (eigener Prozess).
N-935-03/-04/-06 Gebuehren-Entwurf: Depotcheck, Advisory-Report (Header, Fuss).
N-935-05 Historische Jahresrenditen nur aus freigegebenem Paket (Produktion/EXE).
Die gepackte EXE wird ueber ``sys.frozen`` simuliert; den echten Lauf belegt der
Packaging-Smoke.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

import config
from config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "ares-backend"
SMOKE_PACKAGE = REPO_ROOT / "scripts" / "fixtures" / "packaging_smoke_test_reference_package.json"


# --------------------------------------------------------------------- N-935-01 b
def _frozen_install(tmp_path: Path, monkeypatch, lines: str) -> Path:
    """Simuliert die Installation: .env neben ares-api.exe, in _MEIPASS und im cwd."""
    install = tmp_path / "resources" / "backend"
    internal = install / "_internal"
    internal.mkdir(parents=True)
    for folder in (install, internal):
        (folder / ".env").write_text(lines, encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "ares-api.exe"))
    monkeypatch.chdir(install)
    return install / ".env"


def test_frozen_exe_reads_no_env_file_next_to_exe(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    env_file = _frozen_install(
        tmp_path, monkeypatch,
        f"APP_PORT=9876\nSMTP_FROM=fremd@example.invalid\ntest_reference_package_file={SMOKE_PACKAGE}\n")
    assert config.resolve_env_file() is None
    cfg = Settings()
    assert cfg.app_port == 8000 and cfg.smtp_from == ""
    # auch ein ausdruecklich uebergebener Pfad wird in der EXE nicht gelesen
    assert Settings(_env_file=str(env_file)).app_port == 8000
    assert cfg.ic_release_required and not cfg.runtime_reference_seed_allowed


def test_source_mode_still_reads_env_file(tmp_path, monkeypatch):
    """Gegenprobe: Quellbetrieb/Tests unveraendert."""
    monkeypatch.delenv("APP_PORT", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("APP_PORT=9876\n", encoding="utf-8")
    assert not getattr(sys, "frozen", False)
    assert Settings(_env_file=str(env_file)).app_port == 9876
    assert config.resolve_env_file() is not None


def test_market_data_setup_status_in_frozen_exe_names_no_env_file(tmp_path, monkeypatch):
    from services import market_data_stack

    _frozen_install(tmp_path, monkeypatch, "APP_PORT=9876\n")
    status = market_data_stack.get_market_data_setup_status(provider_roles={})
    assert status["env_file"] == "" and status["env_file_exists"] is False
    assert any("keine .env" in w for w in status["warnings"])


# --------------------------------------------------------------------- N-935-01 a/c
@pytest.fixture()
def empty_session(tmp_path):
    from sqlalchemy.orm import sessionmaker

    import database
    from models.users import User

    engine = database.create_app_engine(db_path=str(tmp_path / "ref.db"), db_key=None)
    database.init_db(target_engine=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        session.add(User(id="u-1", username="u-1", password_hash="h", full_name="Test", role="admin",
                         is_active=1, created_at="2026-11-21T00:00:00Z", updated_at="2026-11-21T00:00:00Z"))
        session.commit()
    yield factory
    engine.dispose()


@pytest.mark.parametrize("name", ["TEST_REFERENCE_PACKAGE_FILE", "test_reference_package_file",
                                  "Test_Reference_Package_File"])
def test_direct_start_with_variable_never_activates_a_test_package(empty_session, monkeypatch, name):
    """Direktstart von ares-api.exe ohne Desktop-Shell, Variable in beliebiger
    Schreibweise: kein Testpaket, kein Seeding, keine Berechnung."""
    import services.portfolio_engine as pe
    from core.risk_parameter_set import ReferenceDataPackageMissing

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv(name, str(SMOKE_PACKAGE))
    monkeypatch.setattr(pe, "settings", Settings())
    assert pe.settings.ic_release_required and not pe.settings.runtime_reference_seed_allowed
    with empty_session() as session:
        with pytest.raises(ReferenceDataPackageMissing, match="freigegebene Referenzdaten"):
            pe.ensure_runtime_reference_data(session, "u-1", jurisdiction="CH")


def test_only_the_self_test_module_activates_the_test_package():
    needle = "strategy_self_test_reference_package("
    users = sorted(
        str(path.relative_to(BACKEND)).replace("\\", "/")
        for path in BACKEND.rglob("*.py")
        if "tests" not in path.relative_to(BACKEND).parts
        and needle in path.read_text(encoding="utf-8", errors="replace")
    )
    assert users == ["config.py", "packaging_selftest_strategy.py"], users
    main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert "--self-test-strategy" in main_src and "packaging_selftest_strategy" in main_src
    build = (REPO_ROOT / "ares-desktop" / "scripts" / "build-backend.js").read_text(encoding="utf-8")
    assert "'packaging_selftest_strategy'" in build


def test_strategy_self_test_computes_optimizer_in_simulated_exe(monkeypatch):
    """--self-test-strategy: eigener Ablauf, temporaere DB, stochastischer
    Optimizer, Vermerk nicht IC-freigegeben, kein Kundendokument; danach ist
    nichts mehr aktiv und die eingestellte DB nie beruehrt."""
    import database
    import packaging_selftest_strategy as st
    from core.risk_parameter_set import IC_UNRELEASED_LABEL

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    engine_before = database.engine
    db_file = Path(config.settings.db_path)
    existed = db_file.exists()
    result = st.run_strategy_self_test(str(SMOKE_PACKAGE))
    assert result["ok"] is True, result
    assert result["optimizer"] == "stochastic" and result["constraints"] > 0
    assert result["ic_label"] == IC_UNRELEASED_LABEL and result["ic_release_status"] != "RELEASED"
    assert result["contract_documents"] == 0 and result["fallback_markers"] == []
    assert config.strategy_self_test_package() is None
    assert config.settings.ic_release_required is True
    assert database.engine is engine_before
    assert db_file.exists() == existed


def test_strategy_self_test_without_or_with_invalid_package_fails(tmp_path, capsys):
    import packaging_selftest_strategy as st

    assert st.run_strategy_self_test("")["ok"] is False
    bad = tmp_path / "pkg.json"
    bad.write_text('{"format": "x"}', encoding="utf-8")
    assert st.run_strategy_self_test(str(bad))["error"].startswith("TEST-Referenzpaket")
    assert st.main(["--self-test-strategy"]) == 2
    assert st.SELF_TEST_MARKER in capsys.readouterr().out


def test_strategy_self_test_without_activated_package_is_refused_in_exe(monkeypatch):
    """Gegenprobe: ohne aktiviertes Paket rechnet auch der Selbsttest nicht."""
    import contextlib

    import packaging_selftest_strategy as st

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(config, "strategy_self_test_reference_package", lambda package: contextlib.nullcontext())
    result = st.run_strategy_self_test(str(SMOKE_PACKAGE))
    assert result["ok"] is False and result.get("reason_code") == "REFERENCE_DATA_PACKAGE_MISSING", result


# --------------------------------------------------------------------- N-935-04/-06
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cost_disclosure_pdf import (  # noqa: E402,F401
    _full_payload, _seed_minimal_mandate, advisor_user, auth_client, session_factory,
)

_FULL_REF = {"envelope_hash": "abcdef0123456789", "fassung": 1, "ic_release_status": "UNRELEASED"}


def _payload_without_fee() -> dict:
    payload = _full_payload()
    payload["cost_items"] = [i for i in payload["cost_items"] if i.get("key") != "default_advisory_fee_bps"]
    return payload


def _payload_with_zero_fee() -> dict:
    payload = copy.deepcopy(_full_payload())
    for item in payload["cost_items"]:
        if item["key"] == "default_advisory_fee_bps":
            item.update(rate_bps=0, amount_rappen=0)
    return payload


class _Decision:
    applicable = False
    ok = True

    @staticmethod
    def footer_ref():
        return dict(_FULL_REF)


def _stub_advisory_gates(monkeypatch, cost_payload: dict) -> list[dict]:
    import routers.pdf_reports as pr
    import services.pdf.documents.advisory_report as ar

    calls: list[dict] = []
    monkeypatch.setattr(pr, "_assert_client_pdf_kyc_review", lambda *a, **k: None)
    monkeypatch.setattr("services.recommendation_release_gate.assert_recommendation_release_eligible",
                        lambda *a, **k: None)
    monkeypatch.setattr("services.portfolio_data_release_gate.assert_portfolio_data_release_eligible",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr, "_enforce_cma_currency_release", lambda *a, **k: None)
    monkeypatch.setattr(pr, "customer_document_watermark", lambda *a, **k: None)  # publiziert
    monkeypatch.setattr(pr, "evaluate_channel_envelope", lambda *a, **k: _Decision())
    monkeypatch.setattr(pr, "kyc_release_is_draft", lambda *a, **k: False)
    monkeypatch.setattr(ar, "compute_advisory_report", lambda db, mandate, advisor=None: {
        "cost_disclosure": copy.deepcopy(cost_payload)})

    def spy(payload, *, watermark_mode="none", decision_ref=None, **kw):
        calls.append({"watermark_mode": watermark_mode, "decision_ref": decision_ref})
        return b"%PDF-1.4 spy"

    monkeypatch.setattr(ar, "render_advisory_report_pdf_from_payload", spy)
    return calls


@pytest.mark.no_test_fee_model
def test_advisory_report_without_fee_agreement_is_a_draft_with_header_and_no_decision_number(
        auth_client, advisor_user, session_factory, monkeypatch):
    """N-935-06 (Endpunkt-Test des Pruefers, neu geschrieben) + N-935-04."""
    from models.review import ContractDocument

    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    calls = _stub_advisory_gates(monkeypatch, _payload_without_fee())
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/advisory-report.pdf")
    assert resp.status_code == 200, resp.text
    assert calls[-1]["watermark_mode"] == "gebuehren"
    assert resp.headers.get("X-Ares-Draft") == "gebuehren"
    # Wie jeder Entwurf: keine Pruefnummer im Fuss, nur der IC-Vermerk.
    assert calls[-1]["decision_ref"] == {"ic_release_status": "UNRELEASED"}
    with session_factory() as db:
        assert db.query(ContractDocument).count() == 0


@pytest.mark.no_test_fee_model
@pytest.mark.parametrize("payload_factory", [_full_payload, _payload_with_zero_fee], ids=["satz", "satz-0"])
def test_advisory_report_with_fee_agreement_is_final(auth_client, advisor_user, session_factory, monkeypatch,
                                                     payload_factory):
    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    calls = _stub_advisory_gates(monkeypatch, payload_factory())
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/advisory-report.pdf")
    assert resp.status_code == 200, resp.text
    assert calls[-1]["watermark_mode"] == "none"
    assert "X-Ares-Draft" not in resp.headers
    assert calls[-1]["decision_ref"] == _FULL_REF


def test_cost_pdf_fee_draft_footer_has_no_decision_number():
    """N-935-04: auch der Kostenausweis-Entwurf (veroeffentlichte Strategie)
    druckt keine Pruefnummer; ein bereits gesetzter Entwurf hat Vorrang."""
    import dataclasses

    from core.customer_terms import DECISION_NONE_TEXT, decision_footer_label
    from routers.pdf_reports import _mark_fee_draft
    from test_cost_disclosure_pdf import _ctx

    ctx = dataclasses.replace(_ctx(), decision_ref=dict(_FULL_REF))
    draft = _mark_fee_draft(ctx)
    assert draft.watermark_mode == "gebuehren"
    assert decision_footer_label(draft.decision_ref).startswith(DECISION_NONE_TEXT)
    assert "abcdef012345" not in decision_footer_label(draft.decision_ref)
    unpublished = dataclasses.replace(ctx, watermark_mode="unpublished")
    assert _mark_fee_draft(unpublished) is unpublished
    free = dataclasses.replace(_ctx(), decision_ref={"allocation_free": True})
    assert _mark_fee_draft(free).decision_ref == {"allocation_free": True}


# --------------------------------------------------------------------- N-935-03 Depotcheck
class _FakeRenderer:
    seen: list = []

    def render_depotcheck(self, ctx, data):
        _FakeRenderer.seen.append((ctx, data))
        return b"%PDF-1.4 depotcheck"


def _stub_depotcheck(monkeypatch, cost_payload: dict):
    from services.pdf.base import DepotCheckData

    import routers.pdf_reports as pr

    _FakeRenderer.seen = []
    monkeypatch.setattr(pr, "_assert_client_pdf_kyc_review", lambda *a, **k: None)
    monkeypatch.setattr(pr, "_mark_unpublished", lambda ctx, db, mandate: ctx)
    monkeypatch.setattr(pr, "_build_pdf_context",
                        lambda mandate, user, db, **k: __import__("test_cost_disclosure_pdf")._ctx())
    monkeypatch.setattr(pr, "_depotcheck_gate", lambda mandate, db: (None, None))
    monkeypatch.setattr("services.depot_check_snapshot.mandate_has_recorded_holdings", lambda db, m: False)
    monkeypatch.setattr(pr, "_build_depotcheck_data", lambda mandate, db, **k: DepotCheckData(
        mandate_number="M-PDF-CD", warnings=["bestehender Hinweis"], cost_disclosure=copy.deepcopy(cost_payload)))
    monkeypatch.setattr(pr, "ReportLabRenderer", _FakeRenderer)


@pytest.mark.no_test_fee_model
def test_depotcheck_cost_table_without_fee_agreement_is_a_draft(auth_client, advisor_user, session_factory,
                                                                monkeypatch):
    from routers.pdf_reports import FEE_NOT_AGREED_NOTE

    mandate_id = _seed_minimal_mandate(session_factory, advisor_user)
    _stub_depotcheck(monkeypatch, _payload_without_fee())
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/depotcheck.pdf")
    assert resp.status_code == 200, resp.text
    ctx, data = _FakeRenderer.seen[-1]
    assert ctx.watermark_mode == "gebuehren" and resp.headers.get("X-Ares-Draft") == "gebuehren"
    assert data.warnings[0] == FEE_NOT_AGREED_NOTE and "bestehender Hinweis" in data.warnings
    # Gegenfall: vereinbarter Satz -> kein Entwurf.
    _stub_depotcheck(monkeypatch, _full_payload())
    final = auth_client.get(f"/mandates/{mandate_id}/reports/depotcheck.pdf")
    ctx, data = _FakeRenderer.seen[-1]
    assert ctx.watermark_mode == "none" and "X-Ares-Draft" not in final.headers
    assert FEE_NOT_AGREED_NOTE not in data.warnings


# --------------------------------------------------------------------- N-935-05
def test_packaged_exe_does_not_seed_historic_annual_returns(tmp_path, monkeypatch):
    from sqlalchemy import text

    import database

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    engine = database.create_app_engine(db_path=str(tmp_path / "ret.db"), db_key=None)
    database.init_db(target_engine=engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM asset_class_annual_returns")).scalar() == 0
    engine.dispose()


def test_source_mode_still_seeds_historic_annual_returns(tmp_path):
    from sqlalchemy import text

    import database

    engine = database.create_app_engine(db_path=str(tmp_path / "ret.db"), db_key=None)
    database.init_db(target_engine=engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM asset_class_annual_returns")).scalar() > 0
    engine.dispose()


def test_backtest_without_released_annual_returns_is_typed_refusal_in_exe(tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    import database
    from core.middleware import typed_engine_error
    from core.risk_parameter_set import ReferenceDataPackageMissing
    from services.backtest_strategy import load_annual_returns_matrix

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    engine = database.create_app_engine(db_path=str(tmp_path / "bt.db"), db_key=None)
    database.init_db(target_engine=engine)
    with sessionmaker(bind=engine)() as db:
        with pytest.raises(ReferenceDataPackageMissing, match="Jahresrenditen") as exc:
            load_annual_returns_matrix(db)
    assert typed_engine_error(exc.value).status_code == 409
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with sessionmaker(bind=engine)() as db:
        assert load_annual_returns_matrix(db) == {}  # Quellbetrieb: unveraendert leer, keine Ablehnung
    engine.dispose()


def test_tax_parameter_seed_documents_its_source():
    import inspect

    from services.tax import parameters, reference_data

    assert "N-935-05" in inspect.getsource(parameters.seed_default_tax_parameter_sets)
    assert "N-935-05" in inspect.getsource(reference_data)
