from sqlalchemy import (
    BigInteger, DDL, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, event, inspect, text,
)
from sqlalchemy.orm import relationship
from database import (
    FINANCIAL_COVERAGE_ATTESTATION_SQLITE_TRIGGERS,
    GOAL_REVISION_DECISION_SQLITE_TRIGGERS,
    Base,
)


class WealthPosition(Base):
    __tablename__ = "wealth_positions"
    # PG-002 (Closure-Review PR #666): Zielschluessel der zusammengesetzten
    # Referenz wealth_inflows(linked_position_id, client_id). Gleicher Name wie
    # das Postgres-Migrationsobjekt (services/wealth_tenant_boundary.py).
    __table_args__ = (UniqueConstraint("id", "client_id", name="uq_wealth_positions_id_client"),)

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    # PG-002: direkte Mandantenbindung fuer RLS. Immer serverseitig aus
    # clients.tenant_id des Kunden abgeleitet (ORM-Event unten + DB-Trigger),
    # nie aus Request-Werten. Postgres: NOT NULL per Migration.
    tenant_id = Column(String, ForeignKey("tenants.id"), index=True)
    label = Column(String, nullable=False)
    position_type = Column(String, nullable=False)
    assignment = Column(String, nullable=False, default="Anderes Vermögen")
    current_value_rappen = Column(BigInteger, nullable=False, default=0)
    currency = Column(String, nullable=False, default="CHF")
    valuation_date = Column(String)
    depot_bank = Column(String)
    depot_account_number = Column(String)
    alloc_equities_bps = Column(Integer, nullable=False, default=0)
    alloc_bonds_bps = Column(Integer, nullable=False, default=0)
    alloc_real_estate_bps = Column(Integer, nullable=False, default=0)
    alloc_liquidity_bps = Column(Integer, nullable=False, default=0)
    alloc_alternatives_bps = Column(Integer, nullable=False, default=0)
    property_address = Column(String)
    property_zip_city = Column(String)
    property_usage = Column(String)
    property_rental_income_rappen = Column(BigInteger, nullable=False, default=0)
    # 2026-06-18 (#84): Miete teuerungsindexiert -> abgeleiteter Mietertrag-Cashflow
    # wird is_inflation_linked=1 (waechst in der Projektion mit der Teuerung).
    # server_default="0": DB-seitiger Default, damit auch rohe SQL-Inserts (ohne diese
    # Spalte) und Bestandszeilen 0 erhalten (nicht nur ORM-Inserts via Python-default).
    property_rental_inflation_linked = Column(Integer, nullable=False, server_default="0", default=0)
    pension_type = Column(String)
    pension_institution = Column(String)
    pension_technical_rate_bps = Column(Integer)
    pension_retirement_age = Column(Integer)
    pension_payout_form = Column(String)
    pension_wef_possible = Column(Integer, nullable=False, default=0)
    # VORSORGE-PROJECTION-001 (2026-10-18): deterministische Fortschreibung,
    # siehe services/portfolio_engine_pension_positions.py.
    pension_vehicle = Column(String)  # 'Konto' | 'Wertschriften' | 'Police'
    pension_interest_rate_bps = Column(Integer)  # nominal p.a.; NULL = Default
    pension_maturity_value_rappen = Column(BigInteger)  # garantierter Ablaufwert
    pension_maturity_date = Column(String)  # ISO, Faelligkeit der Police
    pension_lumpsum_tax_rappen = Column(BigInteger)  # Kapitalbezugssteuer CHF (Vorrang)
    pension_lumpsum_tax_bps = Column(Integer)  # oder Satz; beides NULL = Default
    mortgage_bank = Column(String)
    mortgage_type = Column(String)
    mortgage_interest_rate_bps = Column(Integer)
    mortgage_maturity_date = Column(String)
    mortgage_amortization_rappen = Column(BigInteger, nullable=False, default=0)
    mortgage_amortization_type = Column(String)
    mortgage_linked_property_id = Column(String)
    asset_subtype = Column(String)
    asset_expected_return_bps = Column(Integer)
    asset_liquidity = Column(String)
    asset_valuation_method = Column(String)
    asset_location = Column(String)
    liquidity_instrument = Column(String)
    liquidity_interest_rate_bps = Column(Integer)
    liquidity_available_from = Column(String)
    is_available_for_goal_funding = Column(Integer, nullable=False, default=0)
    goal_funding_method = Column(String)
    notes = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    client = relationship("Client", back_populates="wealth_positions")


class Cashflow(Base):
    __tablename__ = "cashflows"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    cashflow_type = Column(String, nullable=False)
    label = Column(String, nullable=False)
    amount_rappen = Column(BigInteger, nullable=False)
    gross_amount_rappen = Column(BigInteger)
    tax_amount_rappen = Column(BigInteger)
    timing_precision = Column(String)
    currency = Column(String, nullable=False, default="CHF")
    frequency = Column(String, nullable=False, default="jährlich")
    nature = Column(String, nullable=False, default="wiederkehrend")
    valid_from = Column(String)
    valid_until = Column(String)
    is_inflation_linked = Column(Integer, nullable=False, default=0)
    notes = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    # CASHFLOW-GOAL-INCLUDE-TOGGLE-001 (Audit-Feedback, 2026-10-08): bewusst
    # GETRENNT von is_active/deleted_at. is_active=0 bedeutet Soft-Delete
    # (Zeile bleibt in list_cashflows UNSICHTBAR); is_included=0 bedeutet
    # "Berater hat diesen Cashflow vorübergehend von allen Berechnungen
    # ausgeschlossen, Zeile bleibt aber in der Liste sichtbar (ausgegraut)".
    # Beide Flags sind unabhaengig: list_cashflows() filtert NUR is_active,
    # jede Geldberechnung (cashflow_summary/-projection, Advisory-Report,
    # portfolio_engine._load_allocation_inputs/build_target_payload_from_
    # allocation) filtert ZUSAETZLICH is_included. Default 1 (eingeschlossen,
    # rueckwaertskompatibel -- bestehende Zeilen aendern ihr Verhalten nicht).
    # server_default="1": DB-seitiger Default, damit auch rohe SQL-Inserts
    # (ohne diese Spalte, siehe property_rental_inflation_linked oben fuer
    # denselben Grund) und Bestandszeilen 1 erhalten, nicht nur ORM-Inserts.
    is_included = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    client = relationship("Client", back_populates="cashflows")


class WealthInflow(Base):
    """Erwarteter Vermögenszufluss (Erbschaft, Bonus, Saeule3b, Verkaufserlös, ...).

    Sprint A1 (2026-05-06): in Advisory-Methodik ein eigenes Konzept; bei uns vorher
    nur als pos-Cashflow modellierbar. First-class fuer:
    - Reserve-Berechnung: Inflow in Year T reduziert Reserve-Bedarf fuer
      Outflows ≤ T
    - cashflow_projection: positive Beitrag im erwarteten Jahr
    - FE-Visualisierung als gruener Marker
    """
    __tablename__ = "wealth_inflows"
    # PENSION-TRANSFER-LEDGER-001 (2026-10-19): hoechstens ein aktiver, nicht
    # geloeschter Zufluss je Vorsorge-Quelle (Vollbezug genau einmal). Der
    # Router prueft vorab per SELECT; der partielle Unique-Index haelt auch
    # bei parallelen Writes. Gleiche Definition: database.py
    # (_SQLITE_CURRENT_ANCHOR_INDEXES, Runtime-Patch) und
    # alembic/versions/a6d2e8f4c1b9_*.py (Postgres).
    __table_args__ = (
        Index(
            "ux_wealth_inflow_one_active_pension_link",
            "linked_position_id",
            unique=True,
            sqlite_where=text("linked_position_id IS NOT NULL AND is_active = 1 AND deleted_at IS NULL"),
            postgresql_where=text("linked_position_id IS NOT NULL AND is_active = 1 AND deleted_at IS NULL"),
        ),
        # PG-002 (Closure-Review PR #666): ein Link zeigt nur auf eine Position
        # DESSELBEN Kunden (damit desselben Mandanten). Zusammengesetzter FK
        # (Postgres + frische SQLite-DBs); Trigger in services/
        # wealth_tenant_boundary.py decken Alt-SQLite-DBs und die Soft-Delete-
        # Policy ab. MATCH SIMPLE: NULL-Link = kein Vorsorgebezug.
        ForeignKeyConstraint(
            ["linked_position_id", "client_id"],
            ["wealth_positions.id", "wealth_positions.client_id"],
            name="fk_wealth_inflows_linked_position_client",
        ),
    )

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    # PG-002: siehe WealthPosition.tenant_id.
    tenant_id = Column(String, ForeignKey("tenants.id"), index=True)
    mandate_id = Column(String, ForeignKey("mandates.id"))  # optional, falls Mandate-spezifisch
    label = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # 'Erbschaft' | 'Bonus' | 'Saeule3b' | 'Verkaufserloes' | 'Andere'
    amount_rappen = Column(BigInteger, nullable=False)
    expected_year = Column(Integer, nullable=False)
    is_recurring = Column(Integer, nullable=False, default=0)
    frequency = Column(String)  # 'einmalig' | 'jaehrlich' | 'monatlich'
    duration_years = Column(Integer)  # bei recurring
    value_mode = Column(String, nullable=False, default="nominal")  # 'nominal' | 'real'
    notes = Column(String)
    # VORSORGE-TRANSFER-001 (2026-10-18): optionaler Verweis auf die externe
    # Vorsorge-Position, aus der dieser Zufluss stammt (Kapitalbezug 2./3a-
    # Saeule/Freizuegigkeit). Dann ist der Zufluss eine Umbuchung innerhalb
    # des Gesamtvermoegens: die Position wird ab dem Bezugsjahr ausgebucht
    # (services/portfolio_engine_pension_positions.py). NULL = neues Vermoegen.
    linked_position_id = Column(String)
    # PG-002: nur fuer die Flush-Reihenfolge (Position vor Zufluss in derselben
    # Session); der Link wird weiterhin ueber linked_position_id gesetzt.
    linked_position = relationship(
        "WealthPosition",
        primaryjoin="WealthInflow.linked_position_id == WealthPosition.id",
        foreign_keys=[linked_position_id],
        lazy="noload",
    )
    # INFLOW-CERTAINTY-001 (2026-10-21): 'sicher' | 'unsicher'. NULL (Bestand
    # vor der Migration / Runtime-Patch) = 'sicher' -> unveraendertes Verhalten.
    # 'unsicher' senkt die Reserve nicht und fliesst nicht in die Simulation
    # (services/wealth_inflow_certainty.py). Verknuepfte Vorsorgebezuege sind
    # immer 'sicher'.
    certainty = Column(String, nullable=True, default="sicher", server_default="sicher")
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)


class Goal(Base):
    __tablename__ = "goals"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    goal_family = Column(String, nullable=False)
    goal_type = Column(String, nullable=False)
    label = Column(String, nullable=False)
    rank = Column(Integer, nullable=False)
    weight_bps = Column(Integer)
    goal_scope = Column(String, nullable=False, default="Beratungsvermögen")
    value_mode = Column(String, nullable=False, default="nominal")
    target_amount_rappen = Column(BigInteger)
    target_wealth_rappen = Column(BigInteger)
    target_return_bps = Column(Integer)
    success_probability_min_x100 = Column(Integer)
    start_date = Column(String)
    horizon_years = Column(Integer)
    target_date = Column(String)
    is_ongoing = Column(Integer, nullable=False, default=0)
    frequency = Column(String)
    hardness = Column(String, nullable=False, default="Primär")
    # Sprint B6 (2026-05-08): Bedingte Goals — Eintrittswahrscheinlichkeit 0-100.
    # NULL/None wird in Engine als 100 (sicher eintretend) interpretiert.
    probability_pct = Column(Integer, nullable=True, default=100)
    # Sprint B3 (2026-05-08): Vorsorge-Differenziert. Ordnet Pensionsausgabe-Goals
    # einer konkreten Saeule zu (AHV / BVG / 3a / 1e / FZG). NULL bei nicht-
    # Pensionsausgabe-Goals oder unspezifizierter Saeule (audit-konsistent zu pre-B3).
    pension_pillar = Column(String, nullable=True)
    linked_position_id = Column(String)
    notes = Column(String)
    is_active = Column(Integer, nullable=False, default=1)
    # CASHFLOW-GOAL-INCLUDE-TOGGLE-001: siehe identischer Kommentar auf
    # Cashflow.is_included (models/wealth.py, Klasse Cashflow) -- dieselbe
    # Semantik, getrennt von is_active/deleted_at. list_goals() filtert NUR
    # is_active; jede Geldberechnung filtert zusaetzlich is_included.
    # server_default="1": siehe identischer Kommentar auf Cashflow.is_included
    # (rohe SQL-Inserts ohne diese Spalte muessen 1 erhalten).
    is_included = Column(Integer, nullable=False, server_default="1", default=1)
    achievement_score = Column(Integer)
    last_scored_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    # GOAL-PAST-DATE-LIFECYCLE-001 / ADR-3 (Owner-Entscheid 2026-10-11):
    # persistierter Lifecycle-ENTSCHEID. NULL = der Berater hat (noch) nicht
    # entschieden; der Zeit-Zustand (planned/due/overdue) wird dann aus
    # target_date gegen den Bewertungsstichtag ABGELEITET
    # (services/goal_lifecycle.py).
    #
    # Nur Entscheidungen werden gespeichert, weil nur sie einen Actor und
    # einen Grund haben -- die beiden Pflichtfelder von ADR-3a/3c.
    # `planned -> due -> overdue` passiert durch Zeitablauf, hat also
    # keinen Actor; ein gespeichertes `planned` wuerde still veralten und
    # braeuchte einen Nachtjob.
    #
    # Zulaessige Werte: services.goal_lifecycle.DECIDED_STATES
    # (fulfilled | cancelled | accepted_as_due_now | historical_unknown).
    lifecycle_decision = Column(String)

    mandate = relationship("Mandate", back_populates="goals")


class GoalLifecycleTransition(Base):
    """Append-only Protokoll jeder Lifecycle-Entscheidung (ADR-3a/3c).

    ADR-3c verlangt Begruendungstext, Zeitstempel und Actor fuer jeden
    Uebergang in einen Terminal-Zustand. `audit_log` ist die
    manipulationssichere Spur (hash-verkettet ueber sequence +
    previous_hash), hat aber kein Begruendungsfeld -- deshalb diese eigene
    Tabelle fuer den Grund, UND zusaetzlich ein audit_log-Eintrag pro
    Transition.

    Append-only: kein `updated_at`, kein `deleted_at`. Ein Eintrag wird
    nie veraendert und nie geloescht; eine Korrektur ist ein neuer Eintrag.

    Mandanten-Trennung wie bei der Eltern-Tabelle `goals`: ueber
    `mandate_id`/`client_id`, NICHT ueber `tenant_id`. `goals` traegt keine
    `tenant_id`, und `services/postgres_rls.py::tenant_scoped_table_names()`
    sammelt genau die Tabellen MIT dieser Spalte fuer die RLS-Policies. Fuer
    eine Kind-Tabelle von `goals` ein abweichendes Scoping-Modell
    einzufuehren waere die ueberraschende Wahl.
    """

    __tablename__ = "goal_lifecycle_transitions"

    id = Column(String, primary_key=True)
    goal_id = Column(String, ForeignKey("goals.id"), nullable=False)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    # NULL bei der ersten Transition eines Ziels (vorher war nichts
    # entschieden, der Zustand war abgeleitet).
    from_state = Column(String)
    to_state = Column(String, nullable=False)
    # ADR-3c: Pflichtfeld. Kein Terminal-Zustand ohne Begruendung.
    reason = Column(String, nullable=False)
    actor_user_id = Column(String, nullable=False)
    created_at = Column(String, nullable=False)


class GoalRevisionDecision(Base):
    """GoalRevisionDecisionV1 -- unveraenderlicher Nachweis EINER Berater-
    Entscheidung, ein Ziel als nachrangiges Wunschziel einzustufen
    (GOAL-REVISION-DECISION-001, CIO-Entscheid 2026-10-21 nach Codex-Closure-
    Review zu PR #655).

    Die Engine stuft nie selbst herab (ein lokales Optimum ist kein globaler
    Unmoeglichkeitsnachweis); sie nutzt den Wunschziel-Mechanismus nur fuer
    Ziele mit gueltiger Decision, deren Ziel-Snapshot-Hash zum aktuellen Ziel
    passt (services/goal_revision_decision.py). Gebunden werden Ziel-Snapshot
    (Hash + JSON), bisheriger Haertegrad, neuer Status, Begruendung, die
    Engine-Evidenz zum Entscheidungszeitpunkt (Status, beste gefundene
    Wahrscheinlichkeit, Wilson-Obergrenze am besten Punkt, tau, Engine-
    Version, Allokation, Screening-Wuerfel), Akteur, Zeitpunkt, Regelversion
    und ein SHA-256 ueber den kanonischen Snapshot.

    Append-only: KEIN updated_at/deleted_at, UPDATE/DELETE per Trigger
    verboten (SQLite unten, PostgreSQL Alembic e3c7a91f5b28). Wie
    risk_override_decisions KEIN FK auf goals/mandates (Purge-fest).
    (goal_id, sequence_no) eindeutig.
    """

    __tablename__ = "goal_revision_decisions"
    __table_args__ = (
        Index(
            "ux_goal_revision_decision_sequence",
            "goal_id",
            "sequence_no",
            unique=True,
        ),
        Index("ix_goal_revision_decisions_mandate", "mandate_id"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="GoalRevisionDecisionV1")
    # Kein harter FK (Purge-fest, Muster audit_log/risk_override_decisions).
    goal_id = Column(String, nullable=False)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String)
    sequence_no = Column(Integer, nullable=False)
    previous_decision_id = Column(String)
    goal_snapshot_hash = Column(String, nullable=False)
    goal_snapshot_json = Column(String, nullable=False)
    previous_hardness = Column(String, nullable=False)
    new_status = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    evidence_status = Column(String, nullable=False)
    evidence_best_probability_bps = Column(Integer)
    evidence_wilson_upper_bps = Column(Integer)
    evidence_tau_bps = Column(Integer)
    evidence_engine_version = Column(String, nullable=False)
    evidence_allocation_id = Column(String)
    evidence_screening_cube_hash = Column(String)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False)
    decided_at = Column(String, nullable=False)
    rules_version = Column(String, nullable=False)
    decision_hash = Column(String(64), nullable=False)
    created_at = Column(String, nullable=False)


for _trigger_ddl in GOAL_REVISION_DECISION_SQLITE_TRIGGERS:
    event.listen(
        GoalRevisionDecision.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )


class PlanningAssumption(Base):
    __tablename__ = "planning_assumptions"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Integer, nullable=False, default=1)
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    supersedes_id = Column(String)
    retirement_age_primary = Column(Integer)
    retirement_age_partner = Column(Integer)
    life_expectancy_primary = Column(Integer)
    life_expectancy_partner = Column(Integer)
    inflation_assumption_bps = Column(Integer)
    # PENSION-INDEXATION-001: persistiert, aber aktuell von KEINEM
    # Simulations-/Projektions-/Reporting-Pfad konsumiert (repo-weiter Audit,
    # 2026-09). Siehe schemas/wealth.py::PlanningAssumptionCreate.pension_indexation_bps
    # fuer den vollen Hinweis. Nicht rechenwirksam, bis Phase 1 (Renten-
    # Indexierungsmethodik) umgesetzt ist.
    pension_indexation_bps = Column(Integer)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="planning_assumptions")


class FinancialCoverageAttestation(Base):
    """FinancialCoverageAttestationV1 -- unveraenderliche Berater-Bestaetigung,
    dass die Finanzdaten des Haushalts vollstaendig erfasst sind
    (RISK-CAPACITY-PLAUSIBILITY-001 Restbefund A, Codex-Closure-Review PR #653).

    Zeilenpraesenz ist keine Vollstaendigkeit: eine einzelne Ausgabenzeile
    beweist nicht, dass Wohnen, Versicherungen, Steuern, Unterhalt, Kredite
    und unregelmaessige Ausgaben erfasst sind. Erst eine gueltige Zeile hier
    erlaubt der Plausibilitaetspruefung, einen niedrigen Ausgabenwert als
    Konsistenzbeleg zu verwenden (services/financial_coverage_attestation.py).

    Gebunden: Haushalt (Mandat + Kunde + erfasste Personen), Kategorien
    (Einnahmen, Ausgaben, Verpflichtungen, unregelmaessige Ausgaben geprueft),
    Stichtag, Quelle, Akteur, Policy-Version und der SHA-256-Fingerprint der
    erfassten Cashflows -- jede spaetere Cashflow-Aenderung invalidiert die
    Bestaetigung. Append-only (Trigger), Korrektur = neue Zeile; die neueste
    Zeile gilt. Kein FK auf mandates/clients (Muster audit_log, Purge-fest).
    """

    __tablename__ = "financial_coverage_attestations"
    __table_args__ = (
        Index("ix_financial_coverage_attestations_mandate", "mandate_id", "attested_at"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="FinancialCoverageAttestationV1")
    mandate_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    # Versiegelt (services/pii_vault.py) ab Schema V2; Altbestand V1 Klartext.
    household_persons_json = Column(String, nullable=False)
    # V2: hash-gebundene Personenzahl (Gueltigkeit ohne Klartext-Namen);
    # NULL beim V1-Altbestand (DSG-ERASURE-NEW-EVIDENCE-001).
    household_person_count = Column(Integer)
    income_complete = Column(Integer, nullable=False)
    expenses_complete = Column(Integer, nullable=False)
    obligations_complete = Column(Integer, nullable=False)
    irregular_expenses_reviewed = Column(Integer, nullable=False)
    as_of_date = Column(String, nullable=False)
    source = Column(String, nullable=False)
    note = Column(String)  # versiegelt ab Schema V2
    cashflow_fingerprint = Column(String(64), nullable=False)
    cashflow_row_count = Column(Integer, nullable=False)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False)
    attested_at = Column(String, nullable=False)
    policy_version = Column(String, nullable=False)
    attestation_hash = Column(String(64), nullable=False)
    created_at = Column(String, nullable=False)


for _trigger_ddl in FINANCIAL_COVERAGE_ATTESTATION_SQLITE_TRIGGERS:
    event.listen(
        FinancialCoverageAttestation.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )


# --- PG-002: Datenbank-Mandantengrenze fuer Vermoegen/Zufluesse -------------
from services import wealth_tenant_boundary as _wtb  # noqa: E402


def _derive_wealth_tenant(mapper, connection, target) -> None:
    state = inspect(target)
    if state.persistent:
        changed = any(
            state.attrs[name].history.has_changes() for name in ("client_id", "tenant_id")
        )
        if not changed:
            return
    target.tenant_id = _wtb.derive_tenant_id(connection, target.client_id)


for _wealth_model in (WealthPosition, WealthInflow):
    event.listen(_wealth_model, "before_insert", _derive_wealth_tenant)
    event.listen(_wealth_model, "before_update", _derive_wealth_tenant)
    event.listen(_wealth_model.__table__, "after_create", _wtb.create_sqlite_triggers_after_create)
    for _function_ddl in _wtb.POSTGRES_FUNCTIONS:
        event.listen(
            _wealth_model.__table__, "after_create", DDL(_function_ddl).execute_if(dialect="postgresql")
        )
    for _trigger_ddl in _wtb.postgres_triggers(_wealth_model.__tablename__):
        event.listen(
            _wealth_model.__table__, "after_create", DDL(_trigger_ddl).execute_if(dialect="postgresql")
        )
