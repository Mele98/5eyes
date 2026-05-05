from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from database import new_uuid
from models.allocation import TargetAllocation
from models.clients import Client, ClientNationality, ClientOptHistory
from models.mandates import Mandate
from models.profiling import ClientKnowledge, RiskAssessment, RiskAssessmentAnswer, SuitabilityCheck
from models.review import (
    AdvisoryLog,
    ConflictOfInterestDisclosure,
    ContractDocument,
    RecommendationPosition,
    RecommendationRun,
    ReviewTrigger,
)
from models.users import User
from models.wealth import Cashflow, Goal, PlanningAssumption, WealthPosition
from services.portfolio_engine import (
    build_recommendation_payload_from_run,
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.review_engine import refresh_system_review_triggers
from services.risk_scoring import compute_scores


FOUNDATION_CLIENT_NUMBER = "EX-5E-FOUNDATION"
FOUNDATION_MANDATE_NUMBER = "MX-FOUNDATION-01"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today() -> str:
    return date.today().isoformat()


def _rappen(chf: int | float) -> int:
    return int(round(float(chf) * 100))


def _delete_foundation_example_if_present(db: Session) -> None:
    clients = db.query(Client).filter(
        Client.client_number == FOUNDATION_CLIENT_NUMBER,
        Client.deleted_at.is_(None),
    ).all()
    if not clients:
        return

    client_ids = [client.id for client in clients]
    mandate_ids = [
        row[0]
        for row in db.query(Mandate.id).filter(
            Mandate.client_id.in_(client_ids),
            Mandate.deleted_at.is_(None),
        ).all()
    ]
    assessment_ids = []
    run_ids = []
    if mandate_ids:
        assessment_ids = [
            row[0]
            for row in db.query(RiskAssessment.id).filter(RiskAssessment.mandate_id.in_(mandate_ids)).all()
        ]
        run_ids = [
            row[0]
            for row in db.query(RecommendationRun.id).filter(RecommendationRun.mandate_id.in_(mandate_ids)).all()
        ]

    if run_ids:
        db.query(RecommendationPosition).filter(RecommendationPosition.run_id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.query(RecommendationRun).filter(RecommendationRun.id.in_(run_ids)).delete(synchronize_session=False)

    if assessment_ids:
        db.query(RiskAssessmentAnswer).filter(RiskAssessmentAnswer.assessment_id.in_(assessment_ids)).delete(
            synchronize_session=False
        )
        db.query(RiskAssessment).filter(RiskAssessment.id.in_(assessment_ids)).delete(synchronize_session=False)

    if mandate_ids:
        db.query(TargetAllocation).filter(TargetAllocation.mandate_id.in_(mandate_ids)).delete(synchronize_session=False)
        db.query(ReviewTrigger).filter(ReviewTrigger.mandate_id.in_(mandate_ids)).delete(synchronize_session=False)
        db.query(AdvisoryLog).filter(AdvisoryLog.mandate_id.in_(mandate_ids)).delete(synchronize_session=False)
        db.query(ContractDocument).filter(ContractDocument.mandate_id.in_(mandate_ids)).delete(
            synchronize_session=False
        )
        db.query(ConflictOfInterestDisclosure).filter(
            ConflictOfInterestDisclosure.mandate_id.in_(mandate_ids)
        ).delete(synchronize_session=False)
        db.query(SuitabilityCheck).filter(SuitabilityCheck.mandate_id.in_(mandate_ids)).delete(
            synchronize_session=False
        )
        db.query(Goal).filter(Goal.mandate_id.in_(mandate_ids)).delete(synchronize_session=False)
        db.query(PlanningAssumption).filter(PlanningAssumption.mandate_id.in_(mandate_ids)).delete(
            synchronize_session=False
        )
        db.query(Mandate).filter(Mandate.id.in_(mandate_ids)).delete(synchronize_session=False)

    db.query(Cashflow).filter(Cashflow.client_id.in_(client_ids)).delete(synchronize_session=False)
    db.query(WealthPosition).filter(WealthPosition.client_id.in_(client_ids)).delete(synchronize_session=False)
    db.query(ClientKnowledge).filter(ClientKnowledge.client_id.in_(client_ids)).delete(synchronize_session=False)
    db.query(ClientNationality).filter(ClientNationality.client_id.in_(client_ids)).delete(synchronize_session=False)
    db.query(ClientOptHistory).filter(ClientOptHistory.client_id.in_(client_ids)).delete(synchronize_session=False)
    db.query(Client).filter(Client.id.in_(client_ids)).delete(synchronize_session=False)
    db.flush()


def _existing_foundation_example(db: Session) -> tuple[Client | None, Mandate | None]:
    client = db.query(Client).filter(
        Client.client_number == FOUNDATION_CLIENT_NUMBER,
        Client.deleted_at.is_(None),
    ).first()
    if not client:
        return None, None
    mandate = db.query(Mandate).filter(
        Mandate.client_id == client.id,
        Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER,
        Mandate.deleted_at.is_(None),
    ).first()
    return client, mandate


def _build_foundation_summary(db: Session, user: User, client: Client, mandate: Mandate) -> dict:
    positions = db.query(WealthPosition).filter(
        WealthPosition.client_id == client.id,
        WealthPosition.deleted_at.is_(None),
    ).all()
    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == client.id,
        Cashflow.deleted_at.is_(None),
    ).all()
    goals = db.query(Goal).filter(
        Goal.mandate_id == mandate.id,
        Goal.deleted_at.is_(None),
    ).all()
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate.id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise ValueError("Foundation Case unvollstaendig: aktuelles Risikoprofil fehlt.")

    policy, cma = ensure_runtime_reference_data(db, user.id)
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate.id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).first()
    if allocation:
        allocation_result = build_target_payload_from_allocation(
            db=db,
            mandate=mandate,
            allocation=allocation,
            policy=policy,
            cma=cma,
            assessment=assessment,
            preferences=None,
        )
    else:
        allocation_result = generate_target_allocation(db=db, mandate=mandate, user_id=user.id, preferences=None)
        allocation = allocation_result["target_allocation"]

    recommendation = db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate.id,
    ).order_by(RecommendationRun.created_at.desc()).first()
    if not recommendation:
        recommendation_result = generate_recommendation_run(
            db=db,
            mandate=mandate,
            user_id=user.id,
            preferences=None,
            target_allocation_id=allocation.id,
            depot_bank=mandate.depot_bank,
        )
        recommendation = recommendation_result["run"]
    recommendation_payload = build_recommendation_payload_from_run(
        db=db,
        mandate=mandate,
        run=recommendation,
        user_id=user.id,
        preferences=None,
    )

    triggers = refresh_system_review_triggers(db, mandate, user.id, allocation_payload=allocation_result)
    db.flush()
    goal_analysis = allocation_result.get("goal_analysis") or []
    goal_weight_total = sum(max(1, int(item.get("weight_bps") or 0)) for item in goal_analysis)
    goal_score_weighted_pct = int(round(
        sum(max(1, int(item.get("weight_bps") or 0)) * int(item.get("achievement_score") or 0) for item in goal_analysis)
        / goal_weight_total
    )) if goal_weight_total else 0
    goal_path_at_risk_count = len([item for item in goal_analysis if int(item.get("achievement_score") or 0) < 45])
    monte_carlo = allocation_result.get("monte_carlo") or {}
    mc_target_series = monte_carlo.get("target_p50_series_rappen") or []
    mc_year_labels = monte_carlo.get("year_labels") or []

    return {
        "client_id": client.id,
        "mandate_id": mandate.id,
        "client_name": f"{client.first_name} {client.last_name}",
        "client_number": client.client_number,
        "mandate_number": mandate.mandate_number,
        "risk_profile": assessment.final_profile,
        "risk_score": round((assessment.final_score_x10 or 0) / 10, 1),
        "advisory_wealth_rappen": int(allocation_result["advisory_wealth_rappen"] or 0),
        "total_wealth_rappen": int(allocation_result["total_wealth_rappen"] or 0),
        "annual_net_cashflow_rappen": int(allocation_result["annual_net_cashflow_rappen"] or 0),
        "positions_count": len(positions),
        "cashflows_count": len(cashflows),
        "goals_count": len(goals),
        "review_trigger_count": len(triggers),
        "target_allocation_id": allocation.id,
        "recommendation_run_id": recommendation.id,
        "house_matrix_profile": allocation_result["house_matrix_profile"],
        "projection_years": len(allocation_result["cashflow_projection_series_rappen"]),
        "projection_end_year": int(mc_year_labels[-1]) if mc_year_labels else date.today().year,
        "monte_carlo_simulations": int(monte_carlo.get("simulations") or 0),
        "target_downside_probability_pct": int(monte_carlo.get("target_downside_probability_pct") or 0),
        "target_terminal_p50_rappen": int(mc_target_series[-1]) if mc_target_series else 0,
        "goal_score_weighted_pct": goal_score_weighted_pct,
        "goal_path_at_risk_count": goal_path_at_risk_count,
        "market_data_fresh_coverage_pct": int((recommendation_payload.get("market_data_quality") or {}).get("fresh_coverage_pct") or 0),
        "market_data_missing_price_count": int((recommendation_payload.get("market_data_quality") or {}).get("missing_price_count") or 0),
    }


def upsert_foundation_example_case(db: Session, user: User) -> dict:
    now = _now()
    today = _today()

    existing_client, existing_mandate = _existing_foundation_example(db)
    if existing_client and existing_mandate:
        existing_positions = db.query(WealthPosition.id).filter(
            WealthPosition.client_id == existing_client.id,
            WealthPosition.deleted_at.is_(None),
        ).count()
        existing_cashflows = db.query(Cashflow.id).filter(
            Cashflow.client_id == existing_client.id,
            Cashflow.deleted_at.is_(None),
        ).count()
        existing_goals = db.query(Goal.id).filter(
            Goal.mandate_id == existing_mandate.id,
            Goal.deleted_at.is_(None),
        ).count()
        existing_assessment = db.query(RiskAssessment.id).filter(
            RiskAssessment.mandate_id == existing_mandate.id,
            RiskAssessment.is_current == 1,
            RiskAssessment.deleted_at.is_(None),
        ).first()
        if existing_positions and existing_cashflows and existing_goals and existing_assessment:
            return _build_foundation_summary(db, user, existing_client, existing_mandate)

    if existing_client:
        _delete_foundation_example_if_present(db)

    client = Client(
        id=new_uuid(),
        client_number=FOUNDATION_CLIENT_NUMBER,
        salutation="Herr",
        first_name="Daniel",
        last_name="Beispiel",
        date_of_birth="1976-09-18",
        country_of_residence="CH",
        canton="ZH",
        civil_status="Verheiratet",
        profession="Unternehmer",
        employer="Beispiel Holding AG",
        language="DE",
        partner_salutation="Frau",
        partner_first_name="Claudia",
        partner_last_name="Beispiel",
        partner_date_of_birth="1978-04-05",
        partner_profession="Rechtsanw\u00e4ltin",
        household_type="Paar",
        client_classification="Privatkunde",
        is_professional_opt_out=0,
        is_qualified_investor=1,
        advisor_id=user.id,
        notes=(
            "Systemischer Foundation Case: Gesamtverm\u00f6gen vs. Beratungsverm\u00f6gen, datierte Cashflows, "
            "Ziele, Risikoprofil und direkt generierbare Allokation."
        ),
        created_at=now,
        updated_at=now,
    )
    db.add(client)
    db.flush()

    db.add(
        ClientNationality(
            id=new_uuid(),
            client_id=client.id,
            country_code="CH",
            is_primary=1,
            created_at=now,
        )
    )
    db.add(
        ClientKnowledge(
            id=new_uuid(),
            client_id=client.id,
            version=1,
            is_current=1,
            valid_from=today,
            knowledge_level="Hoch",
            exp_equities="> 5 Jahre",
            exp_bonds="> 5 Jahre",
            exp_funds="> 5 Jahre",
            exp_derivatives="2\u20135 Jahre",
            exp_alternatives="2\u20135 Jahre",
            exp_structured="2\u20135 Jahre",
            confirmed_at=now,
            confirmed_by=user.id,
            next_review_at="2027-03-31",
            created_at=now,
            updated_at=now,
        )
    )

    mandate = Mandate(
        id=new_uuid(),
        client_id=client.id,
        mandate_number=FOUNDATION_MANDATE_NUMBER,
        mandate_type="Anlageberatung",
        status="Aktiv",
        base_currency="CHF",
        advisory_language="DE",
        depot_bank="UBS AG Z\u00fcrich",
        depot_account_number="CH93 0024 0024 0000 5501 T",
        opened_at=today,
        created_at=now,
        updated_at=now,
    )
    db.add(mandate)
    db.flush()

    db.add(
        PlanningAssumption(
            id=new_uuid(),
            mandate_id=mandate.id,
            client_id=client.id,
            version=1,
            is_current=1,
            valid_from=today,
            retirement_age_primary=63,
            retirement_age_partner=64,
            life_expectancy_primary=92,
            life_expectancy_partner=94,
            inflation_assumption_bps=150,
            pension_indexation_bps=100,
            notes="Foundation Case f\u00fcr dated cashflows, Zielprojektion und Advisory-vs-Total-Wealth-Logik.",
            created_at=now,
            updated_at=now,
        )
    )

    property_position = WealthPosition(
        id=new_uuid(),
        client_id=client.id,
        label="Eigentumswohnung Zuerichberg",
        position_type="Immobilien",
        assignment="Anderes Verm\u00f6gen",
        current_value_rappen=_rappen(2400000),
        currency="CHF",
        valuation_date=today,
        property_address="Dolderstrasse 88",
        property_zip_city="8032 Zuerich",
        property_usage="Selbstgenutzt",
        property_rental_income_rappen=0,
        is_available_for_goal_funding=0,
        created_at=now,
        updated_at=now,
    )
    db.add(property_position)
    db.flush()

    positions = [
        WealthPosition(
            id=new_uuid(),
            client_id=client.id,
            label="UBS Advisory Depot",
            position_type="Depot",
            assignment="Beratungsverm\u00f6gen",
            current_value_rappen=_rappen(2250000),
            currency="CHF",
            valuation_date=today,
            depot_bank="UBS AG Z\u00fcrich",
            depot_account_number="DEP-FOUNDATION-01",
            alloc_equities_bps=6200,
            alloc_bonds_bps=2400,
            alloc_real_estate_bps=0,
            alloc_liquidity_bps=800,
            alloc_alternatives_bps=600,
            is_available_for_goal_funding=1,
            goal_funding_method="Verkauf",
            notes="Beratungsverm\u00f6gen fuer die Engine und Produktauswahl.",
            created_at=now,
            updated_at=now,
        ),
        WealthPosition(
            id=new_uuid(),
            client_id=client.id,
            label="ZKB Liquiditaetsreserve",
            position_type="Liquidit\u00e4t",
            assignment="Beratungsverm\u00f6gen",
            current_value_rappen=_rappen(450000),
            currency="CHF",
            valuation_date=today,
            liquidity_instrument="Festgeld",
            liquidity_interest_rate_bps=110,
            liquidity_available_from="2026-06-30",
            is_available_for_goal_funding=1,
            goal_funding_method="Automatisch",
            notes="Reserve fuer kurzfristige Ziele, Steuer und Rebalancing.",
            created_at=now,
            updated_at=now,
        ),
        property_position,
        WealthPosition(
            id=new_uuid(),
            client_id=client.id,
            label="Freizuegigkeitsdepot",
            position_type="Vorsorge",
            assignment="Anderes Verm\u00f6gen",
            current_value_rappen=_rappen(1650000),
            currency="CHF",
            valuation_date=today,
            pension_type="Freiz\u00fcgigkeit",
            pension_institution="Pensionskasse Beispiel Holding",
            pension_technical_rate_bps=175,
            pension_retirement_age=63,
            pension_payout_form="Gemischt",
            pension_wef_possible=0,
            is_available_for_goal_funding=0,
            notes="Gesamtvermoegen relevant, aber nicht Advisory-umschichtbar.",
            created_at=now,
            updated_at=now,
        ),
        WealthPosition(
            id=new_uuid(),
            client_id=client.id,
            label="Saeule 3a Bestand",
            position_type="Vorsorge",
            assignment="Anderes Verm\u00f6gen",
            current_value_rappen=_rappen(320000),
            currency="CHF",
            valuation_date=today,
            pension_type="S\u00e4ule 3a",
            pension_institution="VIAC",
            pension_retirement_age=63,
            pension_payout_form="Kapital",
            pension_wef_possible=1,
            is_available_for_goal_funding=1,
            goal_funding_method="Automatisch",
            notes="Der k\u00fcnftige Bezug wird zus\u00e4tzlich als datierter Cashflow modelliert.",
            created_at=now,
            updated_at=now,
        ),
        WealthPosition(
            id=new_uuid(),
            client_id=client.id,
            label="Festhypothek Hauptwohnsitz",
            position_type="Hypothek",
            assignment="Verbindlichkeit",
            current_value_rappen=_rappen(900000),
            currency="CHF",
            valuation_date=today,
            mortgage_bank="UBS AG Z\u00fcrich",
            mortgage_type="Festhypothek",
            mortgage_interest_rate_bps=185,
            mortgage_maturity_date="2031-12-31",
            mortgage_amortization_rappen=_rappen(30000),
            mortgage_amortization_type="Direkt",
            mortgage_linked_property_id=property_position.id,
            notes="Verbindlichkeit mit echtem Immobilien-Link fuer die Stammdaten-Logik.",
            created_at=now,
            updated_at=now,
        ),
    ]
    for position in positions:
        if position is property_position:
            continue
        db.add(position)

    cashflows = [
        Cashflow(
            id=new_uuid(),
            client_id=client.id,
            cashflow_type="Income",
            label="Daniel Lohn",
            amount_rappen=_rappen(24000),
            currency="CHF",
            frequency="monatlich",
            nature="wiederkehrend",
            valid_from="2026-01-01",
            valid_until="2032-12-31",
            is_inflation_linked=0,
            notes="Aktiver Unternehmerlohn bis geplantem Rueckzug.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Cashflow(
            id=new_uuid(),
            client_id=client.id,
            cashflow_type="Income",
            label="Claudia Einkommen",
            amount_rappen=_rappen(9000),
            currency="CHF",
            frequency="monatlich",
            nature="wiederkehrend",
            valid_from="2026-01-01",
            valid_until="2030-12-31",
            is_inflation_linked=0,
            notes="Teilzeit-Einkommen der Partnerin bis 2030.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Cashflow(
            id=new_uuid(),
            client_id=client.id,
            cashflow_type="Income",
            label="Mietertrag Zweitobjekt",
            amount_rappen=_rappen(4500),
            currency="CHF",
            frequency="monatlich",
            nature="wiederkehrend",
            valid_from="2026-01-01",
            valid_until=None,
            is_inflation_linked=0,
            notes="Laufender Mietertrag ausserhalb des Beratungsvermoegens.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Cashflow(
            id=new_uuid(),
            client_id=client.id,
            cashflow_type="Income",
            label="3a Kapitalbezug",
            amount_rappen=_rappen(350000),
            currency="CHF",
            frequency="einmalig",
            nature="einmalig",
            valid_from="2028-06-30",
            valid_until="2028-06-30",
            is_inflation_linked=0,
            notes="Einmaliger Zufluss im Jahr 2028.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Cashflow(
            id=new_uuid(),
            client_id=client.id,
            cashflow_type="Expense",
            label="Lebenshaltung",
            amount_rappen=_rappen(14000),
            currency="CHF",
            frequency="monatlich",
            nature="wiederkehrend",
            valid_from="2026-01-01",
            valid_until=None,
            is_inflation_linked=1,
            notes="Haushaltskosten des Paares.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Cashflow(
            id=new_uuid(),
            client_id=client.id,
            cashflow_type="Expense",
            label="Steuern und Versicherungen",
            amount_rappen=_rappen(6000),
            currency="CHF",
            frequency="monatlich",
            nature="wiederkehrend",
            valid_from="2026-01-01",
            valid_until=None,
            is_inflation_linked=0,
            notes="Nicht verhandelbarer Sockelabfluss.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Cashflow(
            id=new_uuid(),
            client_id=client.id,
            cashflow_type="Expense",
            label="Ausbildungsunterstuetzung Tochter",
            amount_rappen=_rappen(3000),
            currency="CHF",
            frequency="monatlich",
            nature="wiederkehrend",
            valid_from="2026-01-01",
            valid_until="2028-12-31",
            is_inflation_linked=0,
            notes="Datiertes Familien-Cashflow-Thema bis Ende 2028.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
    ]
    for cashflow in cashflows:
        db.add(cashflow)

    goals = [
        Goal(
            id=new_uuid(),
            mandate_id=mandate.id,
            client_id=client.id,
            goal_family="Cashflow",
            goal_type="Einmalige_Ausgabe",
            label="Eigenmittel Ferienhaus 2028",
            rank=1,
            weight_bps=10000,
            goal_scope="Gesamtverm\u00f6gen",
            value_mode="nominal",
            target_amount_rappen=_rappen(600000),
            start_date="2028-09-30",
            target_date="2028-09-30",
            horizon_years=2,
            is_ongoing=0,
            frequency=None,
            hardness="Hart",
            notes="Kurzfristiger Liquiditaetsbedarf, der die Reserve-Logik sichtbar triggern soll.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Goal(
            id=new_uuid(),
            mandate_id=mandate.id,
            client_id=client.id,
            goal_family="Verm\u00f6gen",
            goal_type="Verm\u00f6gensziel",
            label="Familienvermoegen 2035",
            rank=2,
            weight_bps=7000,
            goal_scope="Gesamtverm\u00f6gen",
            value_mode="real",
            target_wealth_rappen=_rappen(8500000),
            start_date="2026-01-01",
            target_date="2035-12-31",
            horizon_years=10,
            is_ongoing=0,
            hardness="Prim\u00e4r",
            notes="Langfristiges Vermoegensziel auf Gesamtvermoegensbasis.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Goal(
            id=new_uuid(),
            mandate_id=mandate.id,
            client_id=client.id,
            goal_family="Cashflow",
            goal_type="Pensionsausgabe",
            label="Einkommensbruecke Pension",
            rank=3,
            weight_bps=6000,
            goal_scope="Gesamtverm\u00f6gen",
            value_mode="real",
            target_amount_rappen=_rappen(180000),
            start_date="2033-01-01",
            target_date="2042-12-31",
            horizon_years=7,
            is_ongoing=1,
            frequency="j\u00e4hrlich",
            hardness="Prim\u00e4r",
            notes="Datierter Ausgabenstrom nach Rueckzug aus dem Erwerbsleben.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
        Goal(
            id=new_uuid(),
            mandate_id=mandate.id,
            client_id=client.id,
            goal_family="Rendite",
            goal_type="Renditeziel",
            label="Mindestrendite Advisory",
            rank=4,
            weight_bps=2500,
            goal_scope="Beratungsverm\u00f6gen",
            value_mode="nominal",
            target_return_bps=450,
            start_date="2026-01-01",
            target_date="2035-12-31",
            horizon_years=10,
            is_ongoing=0,
            hardness="Opportunistisch",
            notes="Explizites Renditeziel fuer die Strategieauswertung.",
            is_active=1,
            created_at=now,
            updated_at=now,
        ),
    ]
    for goal in goals:
        db.add(goal)

    scoring = compute_scores(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
    )
    assessment = RiskAssessment(
        id=new_uuid(),
        mandate_id=mandate.id,
        version=1,
        is_current=1,
        valid_from=today,
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        risk_capacity_total=scoring.risk_capacity_total,
        risk_capacity_profile=scoring.risk_capacity_profile,
        investment_horizon_years=15,
        investment_horizon_label="Mehr als 12 Jahre",
        risk_capacity_score_x10=scoring.risk_capacity_score_x10,
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
        risk_willingness_total=scoring.risk_willingness_total,
        risk_willingness_profile=scoring.risk_willingness_profile,
        risk_willingness_score_x10=scoring.risk_willingness_score_x10,
        final_score_x10=scoring.final_score_x10,
        final_profile=scoring.final_profile,
        is_overridden=0,
        assessed_at=now,
        assessed_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(assessment)
    db.flush()

    answers = [
        ("Risikof\u00e4higkeit", 3, "Regelmaessiges Einkommen hoch", 4),
        ("Risikof\u00e4higkeit", 4, "Herkunft: Berufliche Taetigkeit, Vermoegensanlagen", 0),
        ("Risikof\u00e4higkeit", 5, "Verpflichtungen tief", 4),
        ("Risikof\u00e4higkeit", 6, "Freies Vermoegen hoch", 12),
        ("Risikof\u00e4higkeit", 7, "Sparquote hoch", 12),
        ("Risikof\u00e4higkeit", 8, "Mehr als 12 Jahre", 0),
        ("Risikobereitschaft", 9, "Wachstum mit klaren Leitplanken", 3),
        ("Risikobereitschaft", 10, "Zeitweise Schwankungen akzeptiert", 3),
        ("Risikobereitschaft", 11, "Verhaelt sich in Rueckgaengen diszipliniert", 3),
    ]
    for section, number, label, points in answers:
        db.add(
            RiskAssessmentAnswer(
                id=new_uuid(),
                assessment_id=assessment.id,
                question_number=number,
                question_section=section,
                answer_label=label,
                answer_points=points,
                created_at=now,
            )
        )

    db.flush()

    return _build_foundation_summary(db, user, client, mandate)
