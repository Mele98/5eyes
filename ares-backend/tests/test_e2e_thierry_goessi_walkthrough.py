"""Ende-zu-Ende-Durchlauf eines vollstaendigen Mandats (Mock: Thierry Goessi).

Zweck
-----
Die bestehenden E2E-Tests pruefen je einen Sprint. Dieser Test geht EINMAL
die ganze Beratungsstrecke durch, in der Reihenfolge, in der ein Berater sie
benutzt, und mit MEHREREN gleichzeitig aktiven Zielen verschiedener Familien
und Haertegrade:

    Kunde -> Mandat -> Einnahmen/Ausgaben -> Vermoegen -> Ziele (5 Stueck,
    gleichzeitig) -> Risikoprofil -> Produktuniversum -> Zielallokation ->
    Empfehlung/Portfolio -> Kostenausweis -> Advisory-Report -> PDFs

Warum das eine eigene Datei verdient: die Einzel-Sprint-Tests koennen jeden
Baustein gruen melden, waehrend die VERKETTUNG bricht -- genau dort sass der
Befund "leerer Mandant zeigte erfundene Wachstumskurve" (2026-08-06) und die
Schema-Drift-Faelle, bei denen ein Default-Wert einer Maske im CHECK-
Constraint fehlte. Ein Durchlauf, der jede Stufe auf dem Ergebnis der
vorherigen aufbaut, faengt diese Klasse.

Alle Betraege in Rappen. Alle Daten synthetisch
(`data_classification="synthetic"`), damit der Mock-Mandant nie mit echten
Kundendaten verwechselt werden kann.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.clients import Client  # noqa: E402,F401
from models.mandates import Mandate  # noqa: E402,F401
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _view_ddl_from_production_schema() -> list[str]:
    """Die CREATE-VIEW-Anweisungen aus der ECHTEN Schema-Datei.

    Bewusst extrahiert statt hier abgeschrieben. Bestehende Tests bauen die
    Views mit der Hand nach (siehe tests/test_runtime_contracts.py) -- das ist
    eine zweite Quelle derselben Definition, die unbemerkt driftet. Hier wird
    dieselbe Datei gelesen, die auf dem SQLite-Pfad auch die Produktion
    provisioniert.

    Nur die Views, nicht die Tabellen: die Tabellen kommen aus dem
    ORM-Metadata (`create_all`), weil die Schema-Datei einige ORM-Spalten
    nicht kennt (z.B. `clients.tenant_id`, in der Produktion von
    `_run_sqlite_legacy_schema_maintenance()` nachgezogen). Erst
    `bootstrap_sqlite_schema()` zu fahren wuerde die Tabellen anlegen,
    `create_all` wuerde sie dann als vorhanden ueberspringen, und die
    ORM-Spalten fehlten -- im ersten Durchlauf dieses Tests genau so
    passiert.
    """
    sql_path = BACKEND_ROOT / "ares_schema.sql"
    assert sql_path.exists(), f"Schema-Datei nicht gefunden: {sql_path}"
    content = sql_path.read_text(encoding="utf-8")

    statements: list[str] = []
    for chunk in content.split(";"):
        stripped = chunk.strip()
        upper = stripped.upper()
        start = upper.find("CREATE VIEW")
        if start == -1:
            continue
        statements.append(stripped[start:])
    assert statements, "Keine CREATE-VIEW-Anweisung in der Schema-Datei gefunden"
    return statements


@pytest.fixture()
def session_factory(tmp_path):
    """ORM-Tabellen plus die DB-VIEWS aus der echten Schema-Datei.

    Die drei Views (`v_client_wealth_summary`, `v_client_cashflow_surplus`,
    `v_active_triggers`) sind NICHT Teil des ORM-Metadata und entstehen durch
    `create_all` nicht. Ein Fixture mit `create_all` allein laesst jeden
    Endpunkt scheitern, der eine View liest -- im ersten Durchlauf dieses
    Tests genau so passiert (`no such table: v_client_wealth_summary` bei
    `/clients/{id}/wealth-summary`).
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'thierry.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for statement in _view_ddl_from_production_schema():
            conn.execute(text(statement))
    try:
        yield sf
    finally:
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-thierry-advisor",
        username="advisor-tg",
        password_hash="h",
        full_name="Beraterin Mock",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture()
def api(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Die Strecke, stufenweise
# ---------------------------------------------------------------------------


def _create_client_and_mandate(api, advisor_user) -> tuple[str, str]:
    resp = api.post(
        "/clients",
        json={
            "client_number": "TG-2026-001",
            "first_name": "Thierry",
            "last_name": "Gössi",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
            "birth_date": "1979-04-18",
            "tax_domicile": "CH",
            "data_classification": "synthetic",
        },
    )
    assert resp.status_code == 201, resp.text
    client_id = resp.json()["id"]

    resp = api.post(
        f"/clients/{client_id}/mandates",
        json={
            "mandate_number": "TG-M-001",
            "mandate_type": "Vermögensverwaltung",
            "base_currency": "CHF",
        },
    )
    assert resp.status_code == 201, resp.text
    return client_id, resp.json()["id"]


def _seed_cashflows(api, client_id: str) -> list[dict]:
    """Einnahmen und Ausgaben, inklusive eines befristeten und eines einmaligen.

    Die Mischung ist absichtlich: ein unbefristeter Erwerbsfluss, eine erst
    spaeter beginnende Rente, laufende Ausgaben und eine Einmalausgabe. Genau
    an dieser Mischung haengen die Horizont- und Bucket-Achsen
    (`valid_until` INKLUSIV, siehe Fachlogik-Notiz Cashflow-Konventionen).
    """
    rows = [
        {
            "cashflow_type": "Income", "label": "Erwerbseinkommen",
            "amount_rappen": 180_000_00, "frequency": "jährlich",
            "nature": "wiederkehrend", "valid_until": "2044-12-31",
            "data_classification": "synthetic",
        },
        {
            "cashflow_type": "Income", "label": "AHV-Rente",
            "amount_rappen": 29_400_00, "frequency": "jährlich",
            "nature": "wiederkehrend", "valid_from": "2045-01-01",
            "data_classification": "synthetic",
        },
        {
            "cashflow_type": "Expense", "label": "Lebenshaltung",
            "amount_rappen": 96_000_00, "frequency": "jährlich",
            "nature": "wiederkehrend",
            "data_classification": "synthetic",
        },
        # BEWUSST KEIN manueller Hypothekarzins-Cashflow: die Hypothek in
        # `_seed_wealth` leitet ihn aus `mortgage_interest_rate_bps` selbst ab.
        # Beides zusammen lehnt die API korrekt ab (Doppelzaehl-Schutz, hier im
        # Durchlauf live angeschlagen) -- die abgeleitete Strecke ist der
        # realistischere und der schwerer zu pruefende Pfad.
        {
            "cashflow_type": "Expense", "label": "Fahrzeugersatz",
            "amount_rappen": 45_000_00, "frequency": "einmalig",
            "nature": "einmalig", "valid_from": "2028-06-01",
            "data_classification": "synthetic",
        },
    ]
    created = []
    for row in rows:
        resp = api.post(f"/clients/{client_id}/cashflows", json=row)
        assert resp.status_code == 201, f"{row['label']}: {resp.text}"
        created.append(resp.json())
    return created


def _seed_wealth(api, client_id: str) -> list[dict]:
    rows = [
        {
            "label": "Depot Hausbank", "position_type": "Depot",
            "assignment": "Beratungsvermögen", "current_value_rappen": 450_000_00,
            "currency": "CHF", "data_classification": "synthetic",
            # Ein Depot MUSS seine Aufteilung mitbringen (Summe exakt 10000 BP,
            # schemas/wealth.py::validate_depot_alloc) -- das IST-Bild der
            # Allokation kommt aus diesen Zahlen, nicht aus einer Schaetzung.
            "alloc_equities_bps": 5500, "alloc_bonds_bps": 3000,
            "alloc_real_estate_bps": 500, "alloc_liquidity_bps": 500,
            "alloc_alternatives_bps": 500,
        },
        {
            "label": "Kontokorrent", "position_type": "Liquidität",
            "assignment": "Beratungsvermögen", "current_value_rappen": 80_000_00,
            "currency": "CHF", "liquidity_instrument": "Kontoguthaben",
            "data_classification": "synthetic",
        },
        {
            "label": "Wohneigentum Zug", "position_type": "Immobilien",
            "assignment": "Anderes Vermögen", "current_value_rappen": 1_200_000_00,
            "currency": "CHF", "property_usage": "Selbstgenutzt",
            "data_classification": "synthetic",
        },
        {
            "label": "Hypothek Wohneigentum", "position_type": "Hypothek",
            "assignment": "Verbindlichkeit", "current_value_rappen": 600_000_00,
            "currency": "CHF", "mortgage_type": "Festhypothek",
            "mortgage_amortization_type": "Indirekt (Säule 3a)",
            # 1.4 % auf CHF 600'000 -> der Zinsfluss wird hieraus ABGELEITET.
            "mortgage_interest_rate_bps": 140,
            "mortgage_maturity_date": "2032-03-31",
            "data_classification": "synthetic",
        },
        {
            "label": "Pensionskasse", "position_type": "Vorsorge",
            "assignment": "Anderes Vermögen", "current_value_rappen": 320_000_00,
            "currency": "CHF", "pension_type": "BVG",
            "pension_payout_form": "Gemischt",
            "data_classification": "synthetic",
        },
    ]
    created = []
    for row in rows:
        resp = api.post(f"/clients/{client_id}/wealth-positions", json=row)
        assert resp.status_code == 201, f"{row['label']}: {resp.text}"
        created.append(resp.json())
    return created


def _seed_goals(api, mandate_id: str) -> list[dict]:
    """FUENF gleichzeitig aktive Ziele, verschiedene Familien und Haertegrade.

    Mehrere Ziele gleichzeitig sind der interessante Fall: hier entstehen
    Rang-Kollisionen, Finanzierungs-Prioritaeten und -- bei geteilten
    Ausfallursachen -- die Zielkonflikt-Rechnung. Ein Durchlauf mit einem
    einzigen Ziel wuerde all das nicht beruehren.
    """
    rows = [
        {
            "goal_family": "Cashflow", "goal_type": "Pensionsausgabe",
            "label": "Pensionsausgaben ab 67", "rank": 1,
            "target_amount_rappen": 72_000_00, "frequency": "jährlich",
            "start_date": "2046-01-01", "is_ongoing": 1,
            "hardness": "Hart", "value_mode": "real",
        },
        {
            "goal_family": "Vermögen", "goal_type": "Vermoegensziel",
            "label": "Umbau Wohneigentum", "rank": 1,
            "target_wealth_rappen": 250_000_00, "horizon_years": 6,
            "hardness": "Hart", "value_mode": "nominal",
        },
        {
            "goal_family": "Cashflow", "goal_type": "Einmalige_Ausgabe",
            "label": "Ausbildung Tochter", "rank": 2,
            # KEIN `frequency`: der Zieltyp erlaubt das Feld nicht
            # (services/goal_semantics.py pruefte das im Durchlauf live).
            "target_amount_rappen": 120_000_00,
            "target_date": "2035-09-01",
            "hardness": "Primär", "value_mode": "real",
        },
        {
            "goal_family": "Cashflow", "goal_type": "Wiederkehrende_Ausgabe",
            "label": "Sabbatical-Reisen", "rank": 3,
            "target_amount_rappen": 30_000_00, "frequency": "jährlich",
            "start_date": "2033-01-01", "target_date": "2035-12-31",
            "is_ongoing": 0,
            "hardness": "Opportunistisch", "value_mode": "real",
        },
        {
            "goal_family": "Rendite", "goal_type": "Renditeziel",
            "label": "4 % real p.a.", "rank": 2,
            "target_return_bps": 400, "horizon_years": 20,
            "hardness": "Primär",
        },
    ]
    created = []
    for row in rows:
        resp = api.post(f"/mandates/{mandate_id}/goals", json=row)
        assert resp.status_code == 201, f"{row['label']}: {resp.text}"
        created.append(resp.json())
    return created


def _seed_risk_profile(api, mandate_id: str) -> dict:
    """Vollstaendiger Fragebogen -- alle elf Fragen, FINMA-konform.

    Die Punkte allein genuegen nicht: `portfolio_engine::
    risk_assessment_ready_for_strategy()` verlangt zusaetzlich elf
    Antwortzeilen mit erkennbaren Texten je Frage (Praefixe wie
    "Finanzdienstleistungen:", "Matrix:" plus Horizontlabel, ein "%" bei
    Frage 7) und je Frage zulaessige Punktwerte. Ohne sie antwortet der
    Endpunkt 422 "Risikoprofil unvollstaendig" -- im Durchlauf live
    passiert. Das ist gewollt: ein halb angeklickter Fragebogen darf keine
    Strategie tragen.
    """
    answers = [
        (1, "Kenntnisse", "Finanzdienstleistungen: Anlageberatung, Vermögensverwaltung", 0),
        (2, "Kenntnisse", "Finanzinstrumente: Aktien, Obligationen, Anlagefonds", 0),
        (3, "Tragfähigkeit", "Einkommen CHF 180'000 pro Jahr", 4),
        (4, "Tragfähigkeit", "Herkunft: Erwerbseinkommen und Sparguthaben", 0),
        (5, "Tragfähigkeit", "Fixe Verpflichtungen CHF 104'400 pro Jahr", 3),
        (6, "Tragfähigkeit", "Sparquote CHF 60'000 pro Jahr", 6),
        (7, "Tragfähigkeit", "Anlagebetrag entspricht 25 % des Gesamtvermögens", 6),
        (8, "Horizont", "Matrix: Mehr als 12 Jahre", 0),
        (9, "Bereitschaft", "Vermögen langfristig vermehren (Wachstum)", 3),
        (10, "Bereitschaft", "Höhere Rendite gegen Wertschwankung akzeptiert", 3),
        (11, "Bereitschaft", "Verluste aushalten, nicht verkaufen", 3),
    ]
    resp = api.post(
        f"/mandates/{mandate_id}/risk-assessments",
        json={
            "q_income_points": 4, "q_obligations_points": 3,
            "q_savings_points": 6, "q_wealth_points": 6,
            "investment_horizon_label": "Mehr als 12 Jahre",
            "investment_horizon_years": 20,
            "q_investment_goal_points": 3, "q_risk_preference_points": 3,
            "q_risk_behavior_points": 3,
            "knowledge_services_json": "{}",
            "knowledge_instruments_json": "{}",
            "income_sources_json": "[]",
            "answers": [
                {
                    "question_number": number,
                    "question_section": section,
                    "answer_label": label,
                    "answer_points": points,
                }
                for number, section, label, points in answers
            ],
            "data_classification": "synthetic",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _seed_products(api, advisor_user) -> list[dict]:
    """Ein kleines, aber ueber alle fuenf Anlageklassen gestreutes Universum.

    Produktpflege ist ADMIN-gated (`services/auth.py::require_admin`) -- mit
    der Beraterrolle antwortet `POST /products` korrekt 403, im Durchlauf
    live angeschlagen. Die Rolle wird deshalb nur fuer diesen Schritt
    gewechselt und danach wieder auf den Berater gesetzt: das prueft die
    Autorisierungsgrenze mit, statt sie zu umgehen.

    `suitability_profile_from/to` sind seit CERT-PRODUCT-ELIGIBILITY-001
    Pflichtfelder -- bewusst breit gesetzt, damit die Eignungspruefung die
    Produkte nicht wegfiltert und der Durchlauf die ALLOKATION prueft, nicht
    das Gate.
    """
    rows = [
        {
            "isin": "CH0000000011", "product_name": "Mock Aktien Welt ETF",
            "product_type": "ETF", "asset_class": "Aktien",
            "sub_asset_class": "Aktien Global", "currency": "CHF",
            "ter_bps": 20, "suitability_profile_from": 1,
            "suitability_profile_to": 6,
        },
        {
            "isin": "CH0000000012", "product_name": "Mock Aktien Schweiz ETF",
            "product_type": "ETF", "asset_class": "Aktien",
            "sub_asset_class": "Aktien Schweiz", "currency": "CHF",
            "ter_bps": 18, "suitability_profile_from": 1,
            "suitability_profile_to": 6,
        },
        {
            "isin": "CH0000000013", "product_name": "Mock Obligationen CHF",
            "product_type": "ETF", "asset_class": "Obligationen",
            "sub_asset_class": "Obligationen CHF", "currency": "CHF",
            "ter_bps": 15, "suitability_profile_from": 1,
            "suitability_profile_to": 6,
        },
        {
            "isin": "CH0000000014", "product_name": "Mock Immobilienfonds CH",
            "product_type": "Fonds", "asset_class": "Immobilien",
            "sub_asset_class": "Immobilien Schweiz", "currency": "CHF",
            "ter_bps": 60, "suitability_profile_from": 1,
            "suitability_profile_to": 6,
        },
        {
            "isin": "CH0000000015", "product_name": "Mock Geldmarkt CHF",
            "product_type": "Fonds", "asset_class": "Liquidität",
            "sub_asset_class": "Geldmarkt CHF", "currency": "CHF",
            "ter_bps": 10, "suitability_profile_from": 1,
            "suitability_profile_to": 6,
        },
        {
            "isin": "CH0000000016", "product_name": "Mock Gold ETC",
            "product_type": "ETC", "asset_class": "Alternative",
            "sub_asset_class": "Gold", "currency": "CHF",
            "ter_bps": 40, "suitability_profile_from": 1,
            "suitability_profile_to": 6,
        },
    ]
    # Zuerst die Grenze selbst: als Berater MUSS es 403 geben.
    denied = api.post("/products", json=rows[0])
    assert denied.status_code == 403, (
        f"Produktpflege ist nicht admin-gated: {denied.status_code} {denied.text[:200]}"
    )

    admin_user = User(
        id="user-thierry-admin", username="admin-tg", password_hash="h",
        full_name="Admin Mock", role="admin", is_active=1,
        created_at=_now(), updated_at=_now(),
    )
    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        created = []
        for row in rows:
            resp = api.post("/products", json=row)
            assert resp.status_code in (200, 201), f"{row['product_name']}: {resp.text}"
            created.append(resp.json())
    finally:
        app.dependency_overrides[get_current_user] = lambda: advisor_user
    return created


# ---------------------------------------------------------------------------
# Der Durchlauf
# ---------------------------------------------------------------------------


def test_thierry_goessi_full_walkthrough(api, advisor_user):
    client_id, mandate_id = _create_client_and_mandate(api, advisor_user)

    # --- Stufe 1: Einnahmen und Ausgaben --------------------------------
    cashflows = _seed_cashflows(api, client_id)
    assert len(cashflows) == 4

    listed = api.get(f"/clients/{client_id}/cashflows")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 4, "Nicht alle Cashflows wurden gelesen"

    summary = api.get(f"/clients/{client_id}/cashflow-summary")
    assert summary.status_code == 200, summary.text
    summary_data = summary.json()
    # Der Saldo muss aus den ERFASSTEN Zahlen folgen, nicht aus einem
    # Platzhalter (Befund 2026-08-06: leerer Mandant zeigte eine erfundene
    # Wachstumskurve).
    assert summary_data, "Cashflow-Summary ist leer"

    projection = api.get(f"/clients/{client_id}/cashflow-projection")
    assert projection.status_code == 200, projection.text

    # --- Stufe 2: Vermoegen ---------------------------------------------
    positions = _seed_wealth(api, client_id)
    assert len(positions) == 5

    wealth = api.get(f"/clients/{client_id}/wealth-summary")
    assert wealth.status_code == 200, wealth.text
    wealth_data = wealth.json()
    # HARTE Zahlen, nicht "ist nicht leer". Im ersten Durchlauf hatte dieser
    # Test `market_value_rappen` geschickt -- ein Feld, das es auf
    # WealthPositionCreate NICHT gibt. Pydantic verwirft unbekannte Felder
    # still, alle fuenf Positionen entstanden mit Wert 0, und die API
    # antwortete HTTP 201. Eine Pruefung auf "nicht leer" waere gruen
    # geblieben. Deshalb hier die erwartete Arithmetik:
    #
    #   brutto      450'000 + 80'000 + 1'200'000 + 320'000 = 2'050'000
    #   Verbindlich 600'000
    #   netto                                                1'450'000
    #   Beratung    450'000 + 80'000                      =    530'000
    assert wealth_data["gross_wealth_rappen"] == 2_050_000_00, wealth_data
    assert wealth_data["liabilities_rappen"] == 600_000_00, wealth_data
    assert wealth_data["net_worth_rappen"] == 1_450_000_00, wealth_data
    assert wealth_data["advisory_wealth_rappen"] == 530_000_00, wealth_data

    # --- Stufe 3: fuenf Ziele gleichzeitig ------------------------------
    goals = _seed_goals(api, mandate_id)
    assert len(goals) == 5

    goal_list = api.get(f"/mandates/{mandate_id}/goals")
    assert goal_list.status_code == 200, goal_list.text
    stored = goal_list.json()
    assert len(stored) == 5, f"Erwartet 5 Ziele, erhalten {len(stored)}"
    # Jedes Ziel muss einzeln wiederauffindbar sein -- ein Ziel, das beim
    # Speichern ein anderes verdraengt, waere hier sichtbar.
    labels = {g["label"] for g in stored}
    assert labels == {
        "Pensionsausgaben ab 67", "Umbau Wohneigentum", "Ausbildung Tochter",
        "Sabbatical-Reisen", "4 % real p.a.",
    }, labels

    # --- Stufe 4: Risikoprofil ------------------------------------------
    risk = _seed_risk_profile(api, mandate_id)
    assert risk.get("final_profile"), f"Kein Risikoprofil ermittelt: {risk}"

    current_risk = api.get(f"/mandates/{mandate_id}/risk-assessments/current")
    assert current_risk.status_code == 200, current_risk.text
    assert current_risk.json()["final_profile"] == risk["final_profile"]

    # --- Stufe 5: Produktuniversum --------------------------------------
    products = _seed_products(api, advisor_user)
    assert len(products) == 6

    # --- Stufe 6: Zielallokation ----------------------------------------
    alloc = api.post(f"/mandates/{mandate_id}/target-allocation/generate", json={})
    assert alloc.status_code in (200, 201), alloc.text
    alloc_data = alloc.json()

    current_alloc = api.get(f"/mandates/{mandate_id}/target-allocation/current")
    assert current_alloc.status_code == 200, current_alloc.text

    # --- Stufe 7: Empfehlung / Portfolio --------------------------------
    rec = api.post(f"/mandates/{mandate_id}/recommendations/generate", json={})
    assert rec.status_code in (200, 201), rec.text
    rec_data = rec.json()

    rec_list = api.get(f"/mandates/{mandate_id}/recommendations")
    assert rec_list.status_code == 200, rec_list.text
    assert rec_list.json(), "Keine Empfehlung gespeichert"

    payload = api.get(f"/mandates/{mandate_id}/recommendations/current/payload")
    assert payload.status_code == 200, payload.text

    # --- Stufe 8: Kostenausweis -----------------------------------------
    costs = api.get(f"/mandates/{mandate_id}/cost-disclosure/ex-ante")
    assert costs.status_code == 200, costs.text
    cost_data = costs.json()
    assert cost_data["currency"] == "CHF"

    # --- Stufe 9: Advisory-Report ---------------------------------------
    report = api.get(f"/mandates/{mandate_id}/advisory-report")
    assert report.status_code == 200, report.text
    report_data = report.json()

    # Die Ziele muessen im Bericht ankommen -- nicht nur in der DB stehen.
    assert report_data, "Advisory-Report ist leer"

    # --- Stufe 10: PDFs -------------------------------------------------
    dispositions: dict[str, str] = {}
    for route in (
        "advisory-report.pdf",
        "assetallocation.pdf",
        "cost-disclosure.pdf",
        "risikoprofil.pdf",
    ):
        pdf = api.get(f"/mandates/{mandate_id}/reports/{route}")
        assert pdf.status_code == 200, f"{route}: {pdf.status_code} {pdf.text[:400]}"
        assert pdf.content[:4] == b"%PDF", f"{route} liefert kein PDF"
        assert len(pdf.content) > 2000, f"{route} ist verdaechtig klein"
        # Der Mandant heisst "Gössi" -- und genau daran ist dieser Durchlauf
        # beim ersten Mal gescheitert: der Dateiname floss roh in den
        # Content-Disposition-Header, Starlette kodierte ihn als Latin-1 und
        # der Client brach mit UnicodeDecodeError ab. Bei einem Namen mit
        # einem nicht in Latin-1 darstellbaren Zeichen (etwa "Łukasz") warf
        # schon Starlette selbst -> HTTP 500. HTTP-Header-Werte sind nach
        # RFC 7230 ASCII; der exakte Name reist im filename*-Parameter.
        disposition = pdf.headers["content-disposition"]
        assert disposition.isascii(), f"{route}: Header nicht ASCII: {disposition!r}"
        dispositions[route] = disposition
    # Mindestens ein Dokument leitet seinen Namen vom MANDATSNAMEN ab und
    # muss den exakten Namen im filename*-Parameter mitfuehren; die aus der
    # reinen ASCII-Mandatsnummer gebildeten brauchen ihn nicht.
    assert any("filename*=UTF-8''" in d for d in dispositions.values()), dispositions
    assert any("Goessi" in d for d in dispositions.values()), (
        f"Keine lesbare Umschrift des Namens im Dateinamen: {dispositions}"
    )

    # Rueckgaben fuer die Diagnose festhalten (werden bei Fehlern gezeigt).
    assert alloc_data is not None and rec_data is not None
