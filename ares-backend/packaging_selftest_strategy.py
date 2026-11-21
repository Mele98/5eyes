"""Strategie-Selbsttest der gepackten Backend-EXE (N-935-01, H-187 Fixrunde 1).

Aufruf: ``ares-api.exe --self-test-strategy <TEST-Referenzpaket.json>`` (oder
``python main.py --self-test-strategy <pfad>``). Belegt fuer den
Packaging-Smoke, dass der stochastische Optimizer im gepackten Artefakt
rechnet (kein stiller Rueckfall auf die House-Matrix, Befund EXE-01).

Warum ein eigener Prozess: Die gepackte EXE rechnet ohne freigegebenes
Referenzpaket nicht (CTO-Entscheid H-187). Der Server nimmt deshalb NIE ein
Testpaket an -- es gibt dort keinen Ladepfad (kein Settings-Feld, keine
Umgebungsvariable, keine .env). Nur dieser Selbsttest laedt das TEST-Paket,
und nur in seinem eigenen Prozess:

* temporaere Datenbank in einem eigenen Temp-Ordner (in der EXE mit SQLCipher
  und einem Wegwerf-Schluessel, der nie gespeichert wird), danach geloescht;
* kein HTTP-Server, kein Port, kein Kundendokument, kein Archiv;
* synthetische Eingaben (ein Testmandat), keine Kundendaten;
* Ergebnis als eine JSON-Zeile (``ARES_SELF_TEST_STRATEGY {...}``),
  Exit 0 = Optimizer gerechnet, 1 = Befund, 2 = Aufruf falsch.

Die Werte bleiben "Vorlagewerte – nicht IC-freigegeben"; das Paket behauptet
keine Freigabe und enthaelt kein Gebuehrenmodell.
"""
from __future__ import annotations

import json
import logging
import secrets
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

SELF_TEST_MARKER = "ARES_SELF_TEST_STRATEGY "
# Antworttexte eines stillen Optimizer-Rueckfalls
# (services/portfolio_engine_optimizer_integration.py); gleiche Liste wie im Smoke.
OPTIMIZER_FALLBACK_MARKERS = ("House-Matrix-Default bleibt aktiv", "Optimizer-Modul nicht verfuegbar",
                              "fallback_house_matrix", "Stochastic Optimizer Fehler")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _isolated_engine(root: Path):
    """Temporaere Engine; ``database.engine``/``SessionLocal`` zeigen waehrend
    des Selbsttests darauf, damit kein Pfad die eingestellte Datenbank oeffnet."""
    import database
    from config import PACKAGED_BUILD, settings

    saved = (settings.database_url, settings.db_use_sqlcipher, settings.db_key, database.engine)
    settings.database_url = None
    key = None
    if PACKAGED_BUILD:
        # Die EXE oeffnet nie eine Klartext-Datei: Wegwerf-Schluessel nur im Speicher.
        key = secrets.token_hex(32)
        settings.db_use_sqlcipher = True
        settings.db_key = key
    engine = database.create_app_engine(db_path=str(root / "strategy-selftest.db"), db_key=key)
    database.engine = engine
    database.SessionLocal.configure(bind=engine)

    def restore() -> None:
        engine.dispose()
        settings.database_url, settings.db_use_sqlcipher, settings.db_key, old_engine = saved
        database.engine = old_engine
        database.SessionLocal.configure(bind=old_engine)

    return engine, ("SQLCipher, temporaer" if key else "temporaer"), restore


def _seed_synthetic_mandate(session) -> tuple[str, str]:
    """Synthetisches Testmandat (Depot CHF 500'000, Risikoprofil
    Wachstumsorientiert; wie der fruehere HTTP-Smoke) -- nur im temporaeren Speicher."""
    from models.clients import Client
    from models.mandates import Mandate
    from models.profiling import RiskAssessment, RiskAssessmentAnswer
    from models.users import User
    from models.wealth import WealthPosition

    advisor_id, cid, mid, aid = (str(uuid.uuid4()) for _ in range(4))
    now = _now()
    session.add(User(id=advisor_id, username=f"selftest-{advisor_id[:8]}", password_hash="-",
                     full_name="Selbsttest", role="advisor", is_active=1, created_at=now, updated_at=now))
    session.add(Client(id=cid, client_number=f"SELFTEST-{cid[:6]}", first_name="Selbsttest",
                       last_name="Synthetisch", advisor_id=advisor_id, created_at=now, updated_at=now))
    session.add(Mandate(id=mid, client_id=cid, mandate_number=f"SELFTEST-{mid[:6]}",
                        mandate_type="Anlageberatung", opened_at=now, created_at=now, updated_at=now))
    session.add(WealthPosition(
        id=str(uuid.uuid4()), client_id=cid, label="Depot (synthetisch)", position_type="Depot",
        assignment="Beratungsvermögen", current_value_rappen=500_000_00, currency="CHF",
        alloc_equities_bps=4000, alloc_bonds_bps=3000, alloc_real_estate_bps=0,
        alloc_liquidity_bps=2000, alloc_alternatives_bps=1000, is_active=1, created_at=now, updated_at=now))
    session.add(RiskAssessment(
        id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
        q_income_points=2, q_obligations_points=3, q_savings_points=8, q_wealth_points=8,
        risk_capacity_total=21, risk_capacity_profile="Dynamisch", risk_capacity_score_x10=100,
        investment_horizon_years=15, investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
        risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
        risk_willingness_score_x10=80, final_score_x10=80, final_profile="Wachstumsorientiert",
        is_overridden=0, knowledge_services_json="{}", knowledge_instruments_json="{}",
        income_sources_json='["Berufliche Taetigkeit"]', assessed_at=now, assessed_by=advisor_id,
        created_at=now, updated_at=now))
    answers = [
        (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
        (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
        (3, "CHF 12'000 bis 20'000", 3),
        (4, "Herkunft: Berufliche Taetigkeit", 0),
        (5, "CHF 3'000 bis 5'000", 3),
        (6, "CHF 1'000'000 bis 2'000'000", 9),
        (7, "25 bis 50 %", 9),
        (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
        (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
        (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
        (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
    ]
    for number, label, points in answers:
        section = ("Kenntnisse & Erfahrungen" if number <= 2
                   else "Risikofähigkeit" if number <= 8 else "Risikobereitschaft")
        session.add(RiskAssessmentAnswer(
            id=str(uuid.uuid4()), assessment_id=aid, question_number=number,
            question_section=section, answer_label=label, answer_points=points, created_at=now))
    session.commit()
    return advisor_id, mid


def _evaluate(result: dict, contract_documents: int) -> dict:
    from core.risk_parameter_set import IC_UNRELEASED_LABEL

    ta = result["target_allocation"]
    texts = json.dumps({k: result.get(k) for k in ("reasoning", "warnings", "messages")},
                       ensure_ascii=False, default=str)
    labels = [m.get("title") for m in (result.get("messages") or []) if isinstance(m, dict)]
    ic_status = (result.get("risk_parameter_set") or {}).get("ic_release_status")
    findings: list[str] = []
    method = getattr(ta, "optimization_method", None)
    if method != "stochastic":
        findings.append(f"Optimizer-Methode {method!r} statt 'stochastic' (Rueckfall).")
    hits = [m for m in OPTIMIZER_FALLBACK_MARKERS if m in texts]
    if hits:
        findings.append(f"Rueckfall-Texte im Ergebnis: {hits}")
    constraints = result.get("optimizer_constraints") or []
    if not constraints:
        findings.append("Keine Optimizer-Constraints (Solver lief nicht).")
    if IC_UNRELEASED_LABEL not in labels or ic_status == "RELEASED":
        findings.append(f"Vermerk {IC_UNRELEASED_LABEL!r} fehlt (Status {ic_status!r}).")
    if contract_documents:
        findings.append(f"{contract_documents} Kundendokument(e) angelegt -- der Selbsttest erzeugt keine.")
    return {
        "optimizer": method,
        "status": getattr(ta, "optimization_status", None),
        "constraints": len(constraints),
        "ic_label": IC_UNRELEASED_LABEL if IC_UNRELEASED_LABEL in labels else None,
        "ic_release_status": ic_status,
        "fallback_markers": hits,
        "contract_documents": contract_documents,
        "findings": findings,
    }


def run_strategy_self_test(package_path: str) -> dict:
    from config import load_test_reference_package, strategy_self_test_reference_package

    out: dict = {"ok": False, "frozen": bool(getattr(sys, "frozen", False))}
    package = load_test_reference_package(package_path) if package_path else None
    if package is None:
        out["error"] = "TEST-Referenzpaket fehlt oder ist ungueltig."
        return out
    out["package_marker"] = package.get("marker")
    with tempfile.TemporaryDirectory(prefix="ares-strategy-selftest-", ignore_cleanup_errors=True) as tmp:
        try:
            import database
            from models.mandates import Mandate
            from models.review import ContractDocument
            from services.portfolio_engine import generate_target_allocation

            engine, out["database"], restore = _isolated_engine(Path(tmp))
            try:
                database.init_db(target_engine=engine)
                with strategy_self_test_reference_package(package):
                    with database.SessionLocal() as session:
                        advisor_id, mandate_id = _seed_synthetic_mandate(session)
                        mandate = session.get(Mandate, mandate_id)
                        result = generate_target_allocation(session, mandate, advisor_id, preferences=None)
                        session.commit()
                        documents = session.query(ContractDocument).count()
                        out.update(_evaluate(result, documents))
            finally:
                restore()
        except Exception as exc:  # noqa: BLE001 - jede Ausnahme ist ein Befund
            out["error"] = f"{type(exc).__name__}: {exc}"[:600]
            reason = getattr(exc, "reason_code", None) or getattr(exc.__cause__, "reason_code", None)
            if reason:
                out["reason_code"] = reason
            return out
    out["ok"] = not out.get("findings")
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    args = [a for a in args if a != "--self-test-strategy"]
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    if len(args) != 1:
        print(SELF_TEST_MARKER + json.dumps({"ok": False, "error": "Aufruf: --self-test-strategy <TEST-Paket>"}),
              flush=True)
        return 2
    result = run_strategy_self_test(args[0])
    print(SELF_TEST_MARKER + json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
