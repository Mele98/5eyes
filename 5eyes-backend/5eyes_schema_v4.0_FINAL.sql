PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA encoding = 'UTF-8';
PRAGMA busy_timeout = 5000;
PRAGMA recursive_triggers = OFF;

-- ============================================================
-- 5EYES · WEALTHARCHITEKTEN
-- Datenbankschema v4.0 — FINAL PRODUCTION
-- ============================================================
-- Changelog v4.0 (gegenüber v3.0):
--
-- KRITISCHE FIXES (GPT-Review):
--   · goals: Composite FK (linked_position_id, client_id) → wealth_positions
--   · goals: Trigger trg_goals_position_validate_insert/update hinzugefügt
--   · goals: CHECK verschärft — pro goal_type dürfen nur passende Felder gesetzt sein
--   · goals: goal_family/goal_type Konsistenz-CHECK (kein Drift)
--   · target_allocations: Composite FK based_on_assessment_id + mandate_id
--   · recommendation_runs: Composite FKs für assessment_id + target_allocation_id
--   · contract_documents: Composite FK supersedes_id + mandate_id
--   · advisory_log: FK document_id → contract_documents
--   · 15 fehlende Indexes auf FK-Kinder-Spalten ergänzt
--   · contract_documents: Signatur-CHECK verschärft
--   · risk_assessments: override_reason NOT NULL wenn overridden
--   · cashflows: 'abgeleitet' aus nature entfernt (konzeptionell unklar)
--   · recommendation_positions: asset_class entfernt (redundant zu products)
--
-- REGULATORISCHE ERGÄNZUNGEN (FIDLEG/FinSA):
--   · clients: client_classification, is_professional_opt_out
--   · NEW TABLE: client_opt_in_out (Opt-in/out-History)
--   · NEW TABLE: suitability_checks (FIDLEG-Nachweis pro Beratungssitzung)
--   · risk_assessments: override_client_confirmed, override_warning_delivered
--   · NEW TABLE: conflict_of_interest_disclosures
--   · NEW TABLE: adviser_registrations (Berater-Registereinträge in users)
-- ============================================================

-- ============================================================
-- 1. BENUTZER & BERATER-REGISTRIERUNG
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    username            TEXT NOT NULL COLLATE NOCASE,
    password_hash       TEXT NOT NULL,
    full_name           TEXT NOT NULL,
    email               TEXT COLLATE NOCASE,
    role                TEXT NOT NULL DEFAULT 'advisor'
                        CHECK(role IN ('admin', 'advisor', 'readonly')),
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    last_login_at       TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at          TEXT,
    CHECK(email IS NULL OR instr(email, '@') > 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username_active
    ON users(username) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_active
    ON users(email) WHERE email IS NOT NULL AND deleted_at IS NULL;

-- Berater-Registrierung (FIDLEG: Beraterregister, Ombudsstelle)
CREATE TABLE IF NOT EXISTS adviser_registrations (
    id                          TEXT PRIMARY KEY,
    user_id                     TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    -- Beraterregister
    register_body               TEXT NOT NULL DEFAULT 'FINMA Beraterregister',
    register_number             TEXT,
    register_status             TEXT NOT NULL DEFAULT 'Aktiv'
                                CHECK(register_status IN ('Aktiv','Suspendiert','Gelöscht','Ausstehend')),
    registered_at               TEXT,
    register_valid_until        TEXT,
    -- Ombudsstelle (FIDLEG Art. 74 ff.)
    ombudsman_body              TEXT,
    ombudsman_affiliated_since  TEXT,
    ombudsman_membership_number TEXT,
    -- Qualifikationen
    qualifications_json         TEXT CHECK(qualifications_json IS NULL OR json_valid(qualifications_json)),
    notes                       TEXT,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at                  TEXT
);
CREATE INDEX IF NOT EXISTS idx_adviser_reg_user ON adviser_registrations(user_id);

-- ============================================================
-- 2. KUNDEN (mit Klassifizierung)
-- ============================================================

CREATE TABLE IF NOT EXISTS clients (
    id                      TEXT PRIMARY KEY,
    client_number           TEXT NOT NULL,
    salutation              TEXT CHECK(salutation IN ('Herr','Frau','Divers')),
    first_name              TEXT NOT NULL,
    last_name               TEXT NOT NULL,
    date_of_birth           TEXT,
    country_of_residence    TEXT NOT NULL DEFAULT 'CH' CHECK(length(country_of_residence) = 2),
    canton                  TEXT,
    civil_status            TEXT CHECK(civil_status IN (
                                'Ledig','Verheiratet','Eingetragene Partnerschaft',
                                'Geschieden','Verwitwet','Getrennt')),
    profession              TEXT,
    employer                TEXT,
    language                TEXT NOT NULL DEFAULT 'DE' CHECK(language IN ('DE','FR','IT','EN')),
    partner_salutation      TEXT CHECK(partner_salutation IN ('Herr','Frau','Divers')),
    partner_first_name      TEXT,
    partner_last_name       TEXT,
    partner_date_of_birth   TEXT,
    partner_profession      TEXT,
    household_type          TEXT NOT NULL DEFAULT 'Einzelperson'
                            CHECK(household_type IN ('Einzelperson','Paar','Familie')),
    -- FIDLEG Klassifizierung (Art. 4/5 FinSA)
    client_classification   TEXT NOT NULL DEFAULT 'Privatkunde'
                            CHECK(client_classification IN (
                                'Privatkunde',
                                'Professioneller Kunde',
                                'Institutioneller Kunde')),
    -- Opt-out: Professioneller Kunde wählt Privatkundenschutz (Art. 5 Abs. 6 FinSA)
    is_professional_opt_out INTEGER NOT NULL DEFAULT 0 CHECK(is_professional_opt_out IN (0,1)),
    -- Qualifizierter Anleger (KAG)
    is_qualified_investor   INTEGER NOT NULL DEFAULT 0 CHECK(is_qualified_investor IN (0,1)),
    -- Beratung
    advisor_id              TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at              TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_clients_number_active
    ON clients(client_number) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_clients_advisor ON clients(advisor_id);
CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(last_name, first_name);

-- Nationalitäten
CREATE TABLE IF NOT EXISTS client_nationalities (
    id              TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE,
    country_code    TEXT NOT NULL CHECK(length(country_code) = 2),
    is_primary      INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(client_id, country_code)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_nationality_one_primary
    ON client_nationalities(client_id) WHERE is_primary = 1;
CREATE INDEX IF NOT EXISTS idx_nationalities_client ON client_nationalities(client_id);

-- Opt-in / Opt-out History (FIDLEG Klassifizierungsänderungen)
CREATE TABLE IF NOT EXISTS client_opt_history (
    id                  TEXT PRIMARY KEY,
    client_id           TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE,
    event_type          TEXT NOT NULL CHECK(event_type IN (
                            'Klassifizierung initial',
                            'Opt-out zu Privatkunde',
                            'Opt-in zu Professionell',
                            'Qualifizierter Anleger bestätigt',
                            'Klassifizierung überprüft')),
    from_classification TEXT NOT NULL,
    to_classification   TEXT NOT NULL,
    client_requested    INTEGER NOT NULL DEFAULT 1 CHECK(client_requested IN (0,1)),
    documented_by       TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    documented_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    document_id         TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_opt_history_client ON client_opt_history(client_id);

-- ============================================================
-- 3. MANDATE
-- ============================================================

CREATE TABLE IF NOT EXISTS mandates (
    id                  TEXT PRIMARY KEY,
    client_id           TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE,
    mandate_number      TEXT NOT NULL,
    mandate_type        TEXT NOT NULL DEFAULT 'Anlageberatung'
                        CHECK(mandate_type IN (
                            'Vermögensverwaltung','Anlageberatung',
                            'Finanzplanung','Reporting only')),
    status              TEXT NOT NULL DEFAULT 'Aktiv'
                        CHECK(status IN ('Aktiv','Inaktiv','Archiviert')),
    base_currency       TEXT NOT NULL DEFAULT 'CHF' CHECK(length(base_currency) = 3),
    advisory_language   TEXT NOT NULL DEFAULT 'DE' CHECK(advisory_language IN ('DE','FR','IT','EN')),
    depot_bank          TEXT,
    depot_account_number TEXT,
    opened_at           TEXT NOT NULL DEFAULT (date('now')),
    closed_at           TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at          TEXT,
    CHECK(closed_at IS NULL OR closed_at >= opened_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_mandates_number_active
    ON mandates(mandate_number) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_mandates_id_client
    ON mandates(id, client_id);
CREATE INDEX IF NOT EXISTS idx_mandates_client ON mandates(client_id);
CREATE INDEX IF NOT EXISTS idx_mandates_status ON mandates(status);

-- ============================================================
-- 4. FIDLEG KENNTNISSE (historisiert)
-- ============================================================

CREATE TABLE IF NOT EXISTS client_knowledge (
    id                  TEXT PRIMARY KEY,
    client_id           TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE,
    version             INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    is_current          INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    valid_from          TEXT NOT NULL DEFAULT (date('now')),
    valid_to            TEXT,
    supersedes_id       TEXT REFERENCES client_knowledge(id) ON UPDATE CASCADE,
    knowledge_level     TEXT NOT NULL DEFAULT 'Mittel'
                        CHECK(knowledge_level IN ('Keine','Gering','Mittel','Hoch')),
    exp_equities        TEXT NOT NULL DEFAULT 'Keine'
                        CHECK(exp_equities IN ('Keine','< 2 Jahre','2–5 Jahre','> 5 Jahre')),
    exp_bonds           TEXT NOT NULL DEFAULT 'Keine'
                        CHECK(exp_bonds IN ('Keine','< 2 Jahre','2–5 Jahre','> 5 Jahre')),
    exp_funds           TEXT NOT NULL DEFAULT 'Keine'
                        CHECK(exp_funds IN ('Keine','< 2 Jahre','2–5 Jahre','> 5 Jahre')),
    exp_derivatives     TEXT NOT NULL DEFAULT 'Keine'
                        CHECK(exp_derivatives IN ('Keine','< 2 Jahre','2–5 Jahre','> 5 Jahre')),
    exp_alternatives    TEXT NOT NULL DEFAULT 'Keine'
                        CHECK(exp_alternatives IN ('Keine','< 2 Jahre','2–5 Jahre','> 5 Jahre')),
    exp_structured      TEXT NOT NULL DEFAULT 'Keine'
                        CHECK(exp_structured IN ('Keine','< 2 Jahre','2–5 Jahre','> 5 Jahre')),
    confirmed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    confirmed_by        TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    next_review_at      TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at          TEXT,
    CHECK(valid_to IS NULL OR valid_to >= valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_knowledge_id_client ON client_knowledge(id, client_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_knowledge_one_current
    ON client_knowledge(client_id) WHERE is_current = 1 AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_knowledge_client ON client_knowledge(client_id, valid_from DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_confirmed_by ON client_knowledge(confirmed_by);

-- ============================================================
-- 5. RISIKOPROFILIERUNG (historisiert)
-- ============================================================

CREATE TABLE IF NOT EXISTS risk_assessments (
    id                          TEXT PRIMARY KEY,
    mandate_id                  TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    version                     INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    is_current                  INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    valid_from                  TEXT NOT NULL DEFAULT (date('now')),
    valid_to                    TEXT,
    supersedes_id               TEXT,
    -- Risikofähigkeit
    q_income_points             INTEGER NOT NULL CHECK(q_income_points BETWEEN 0 AND 4),
    q_obligations_points        INTEGER NOT NULL CHECK(q_obligations_points BETWEEN 0 AND 4),
    q_savings_points            INTEGER NOT NULL CHECK(q_savings_points BETWEEN 0 AND 12),
    q_wealth_points             INTEGER NOT NULL CHECK(q_wealth_points BETWEEN 0 AND 12),
    risk_capacity_total         INTEGER NOT NULL CHECK(risk_capacity_total BETWEEN 0 AND 32),
    risk_capacity_profile       TEXT NOT NULL CHECK(risk_capacity_profile IN (
                                    'Risikoarm','Sicherheitsorientiert','Ausgewogen',
                                    'Wachstumsorientiert','Dynamisch')),
    investment_horizon_years    INTEGER NOT NULL CHECK(investment_horizon_years BETWEEN 0 AND 100),
    investment_horizon_label    TEXT NOT NULL CHECK(investment_horizon_label IN (
                                    'Bis 2 Jahre','2 bis 3 Jahre','4 bis 5 Jahre',
                                    '6 bis 7 Jahre','8 bis 11 Jahre','Mehr als 12 Jahre')),
    risk_capacity_score_x10     INTEGER NOT NULL CHECK(risk_capacity_score_x10 BETWEEN 0 AND 100),
    -- Risikobereitschaft
    q_investment_goal_points    INTEGER NOT NULL CHECK(q_investment_goal_points BETWEEN 1 AND 4),
    q_risk_preference_points    INTEGER NOT NULL CHECK(q_risk_preference_points BETWEEN 1 AND 4),
    q_risk_behavior_points      INTEGER NOT NULL CHECK(q_risk_behavior_points BETWEEN 1 AND 4),
    risk_willingness_total      INTEGER NOT NULL CHECK(risk_willingness_total BETWEEN 3 AND 12),
    risk_willingness_profile    TEXT NOT NULL CHECK(risk_willingness_profile IN (
                                    'Sicherheitsorientiert','Ausgewogen','Wachstumsorientiert','Dynamisch')),
    risk_willingness_score_x10  INTEGER NOT NULL CHECK(risk_willingness_score_x10 BETWEEN 0 AND 100),
    -- Gesamtergebnis
    final_score_x10             INTEGER NOT NULL CHECK(final_score_x10 BETWEEN 0 AND 100),
    final_profile               TEXT NOT NULL CHECK(final_profile IN (
                                    'Kapitalschutz','Defensiv','Ausgewogen',
                                    'Wachstumsorientiert','Dynamisch','Aktien')),
    -- Override (FIX v4: override_reason jetzt NOT NULL wenn overridden)
    is_overridden               INTEGER NOT NULL DEFAULT 0 CHECK(is_overridden IN (0,1)),
    override_score_x10          INTEGER CHECK(override_score_x10 BETWEEN 0 AND 100),
    override_profile            TEXT CHECK(override_profile IN (
                                    'Kapitalschutz','Defensiv','Ausgewogen',
                                    'Wachstumsorientiert','Dynamisch','Aktien')),
    override_by                 TEXT REFERENCES users(id) ON UPDATE CASCADE,
    override_at                 TEXT,
    override_reason             TEXT,
    -- NEU v4: FIDLEG Override-Compliance-Nachweis
    override_client_confirmed   INTEGER DEFAULT 0 CHECK(override_client_confirmed IN (0,1)),
    override_warning_delivered  INTEGER DEFAULT 0 CHECK(override_warning_delivered IN (0,1)),
    override_warning_document_id TEXT,
    assessed_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    assessed_by                 TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at                  TEXT,
    -- Arithmetic integrity
    CHECK(valid_to IS NULL OR valid_to >= valid_from),
    CHECK(risk_capacity_total = q_income_points + q_obligations_points + q_savings_points + q_wealth_points),
    CHECK(risk_willingness_total = q_investment_goal_points + q_risk_preference_points + q_risk_behavior_points),
    -- Override: entweder vollständig oder gar nicht (inkl. reason jetzt pflicht)
    CHECK(
        (is_overridden = 0
         AND override_score_x10 IS NULL AND override_profile IS NULL
         AND override_by IS NULL AND override_at IS NULL AND override_reason IS NULL)
        OR
        (is_overridden = 1
         AND override_score_x10 IS NOT NULL AND override_profile IS NOT NULL
         AND override_by IS NOT NULL AND override_at IS NOT NULL AND override_reason IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_id_mandate ON risk_assessments(id, mandate_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_one_current
    ON risk_assessments(mandate_id) WHERE is_current = 1 AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_risk_mandate ON risk_assessments(mandate_id, assessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_assessed_by ON risk_assessments(assessed_by);
CREATE INDEX IF NOT EXISTS idx_risk_override_by ON risk_assessments(override_by);

CREATE TABLE IF NOT EXISTS risk_assessment_answers (
    id                  TEXT PRIMARY KEY,
    assessment_id       TEXT NOT NULL REFERENCES risk_assessments(id) ON UPDATE CASCADE,
    question_number     INTEGER NOT NULL CHECK(question_number BETWEEN 1 AND 9),
    question_section    TEXT NOT NULL CHECK(question_section IN ('Risikofähigkeit','Risikobereitschaft')),
    answer_label        TEXT NOT NULL,
    answer_points       INTEGER NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(assessment_id, question_number)
);
CREATE INDEX IF NOT EXISTS idx_risk_answers ON risk_assessment_answers(assessment_id);

-- ============================================================
-- 6. SUITABILITY CHECKS — NEU v4
-- Pro Beratungssitzung / Empfehlung: FIDLEG Eignungs-/Angemessenheitsnachweis
-- ============================================================

CREATE TABLE IF NOT EXISTS suitability_checks (
    id                          TEXT PRIMARY KEY,
    mandate_id                  TEXT NOT NULL,
    client_id                   TEXT NOT NULL,
    -- Verknüpfung mit Beratungssitzung
    recommendation_run_id       TEXT,
    advisory_log_id             TEXT,
    -- Welche Pflicht gilt? (FIDLEG Art. 12/13)
    duty_type                   TEXT NOT NULL CHECK(duty_type IN (
                                    'Eignungsprüfung',
                                    'Angemessenheitsprüfung',
                                    'Keine Prüfung')),
    -- Grundlage der Prüfung
    knowledge_assessment_id     TEXT,
    risk_assessment_id          TEXT,
    -- Ergebnis
    result                      TEXT NOT NULL CHECK(result IN (
                                    'Geeignet',
                                    'Nicht geeignet',
                                    'Angemessen',
                                    'Nicht angemessen',
                                    'Unvollständige Information',
                                    'Geeignet mit Einschränkung')),
    result_notes                TEXT,
    -- Fehlende Informationen (wenn result = 'Unvollständige Information')
    missing_information_json    TEXT CHECK(missing_information_json IS NULL OR json_valid(missing_information_json)),
    -- Wenn Ergebnis negativ aber Kunde will trotzdem
    client_proceeding_despite   INTEGER NOT NULL DEFAULT 0 CHECK(client_proceeding_despite IN (0,1)),
    warning_delivered           INTEGER NOT NULL DEFAULT 0 CHECK(warning_delivered IN (0,1)),
    warning_delivered_at        TEXT,
    client_acknowledged         INTEGER NOT NULL DEFAULT 0 CHECK(client_acknowledged IN (0,1)),
    client_acknowledged_at      TEXT,
    -- Unterschrift / Dokumentation
    document_id                 TEXT,
    checked_by                  TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    checked_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (mandate_id, client_id) REFERENCES mandates(id, client_id) ON UPDATE CASCADE,
    CHECK(
        (client_proceeding_despite = 0)
        OR (client_proceeding_despite = 1 AND warning_delivered = 1)
    ),
    CHECK(
        (warning_delivered = 0 AND warning_delivered_at IS NULL)
        OR (warning_delivered = 1 AND warning_delivered_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_suitability_mandate ON suitability_checks(mandate_id);
CREATE INDEX IF NOT EXISTS idx_suitability_client ON suitability_checks(client_id);
CREATE INDEX IF NOT EXISTS idx_suitability_checked_by ON suitability_checks(checked_by);

-- ============================================================
-- 7. INTERESSENKONFLIKTE & INDUCEMENTS — NEU v4
-- ============================================================

CREATE TABLE IF NOT EXISTS conflict_of_interest_disclosures (
    id                          TEXT PRIMARY KEY,
    mandate_id                  TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    -- Art des Interessenkonflikts
    conflict_type               TEXT NOT NULL CHECK(conflict_type IN (
                                    'Retrozession / Inducement',
                                    'Eigenhandel / Eigenbestand',
                                    'Konzernverbindung',
                                    'Persönliches Interesse Berater',
                                    'Sonstiger Interessenkonflikt')),
    description                 TEXT NOT NULL,
    -- Retrozession / Inducement Details
    inducement_provider         TEXT,
    inducement_amount_rappen    INTEGER,
    inducement_frequency        TEXT CHECK(inducement_frequency IN ('einmalig','jährlich','laufend')),
    -- Offenlegung
    disclosed_to_client         INTEGER NOT NULL DEFAULT 0 CHECK(disclosed_to_client IN (0,1)),
    disclosed_at                TEXT,
    client_acknowledged         INTEGER NOT NULL DEFAULT 0 CHECK(client_acknowledged IN (0,1)),
    client_acknowledged_at      TEXT,
    -- Behandlung
    mitigation_action           TEXT CHECK(mitigation_action IN (
                                    'Weitergabe an Kunden',
                                    'Ablehnung',
                                    'Offenlegung ohne Mitigation',
                                    'Strukturelle Massnahme')),
    -- Dokumentation
    document_id                 TEXT,
    disclosed_by                TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at                  TEXT,
    CHECK(
        (disclosed_to_client = 0 AND disclosed_at IS NULL)
        OR (disclosed_to_client = 1 AND disclosed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_coi_mandate ON conflict_of_interest_disclosures(mandate_id);
CREATE INDEX IF NOT EXISTS idx_coi_disclosed_by ON conflict_of_interest_disclosures(disclosed_by);

-- ============================================================
-- 8. ANLAGEPRÄFERENZEN & RESTRIKTIONEN (historisiert)
-- ============================================================

CREATE TABLE IF NOT EXISTS investment_preferences (
    id                      TEXT PRIMARY KEY,
    mandate_id              TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    version                 INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    is_current              INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    valid_from              TEXT NOT NULL DEFAULT (date('now')),
    valid_to                TEXT,
    supersedes_id           TEXT,
    esg_approach            TEXT NOT NULL DEFAULT 'Kein ESG'
                            CHECK(esg_approach IN ('Kein ESG','ESG-Integration','Best-in-Class',
                                'Negativ-Screening','Impact Investing','SDG-Fokus','Paris-aligned')),
    home_bias               TEXT NOT NULL DEFAULT 'Kein Heimmarkt-Bias'
                            CHECK(home_bias IN ('Kein Heimmarkt-Bias','CH-Fokus','Europa-Fokus','USA-Fokus')),
    universe                TEXT NOT NULL DEFAULT 'Standard'
                            CHECK(universe IN ('Standard','Erweitert','Nur Fonds/ETFs')),
    fx_hedging              INTEGER NOT NULL DEFAULT 0 CHECK(fx_hedging IN (0,1)),
    max_foreign_currency_bps INTEGER CHECK(max_foreign_currency_bps BETWEEN 0 AND 10000),
    allowed_currencies      TEXT CHECK(allowed_currencies IS NULL OR json_valid(allowed_currencies)),
    min_liquidity_reserve_rappen INTEGER NOT NULL DEFAULT 0 CHECK(min_liquidity_reserve_rappen >= 0),
    max_illiquid_pct_bps    INTEGER NOT NULL DEFAULT 2000 CHECK(max_illiquid_pct_bps BETWEEN 0 AND 10000),
    max_single_position_bps INTEGER CHECK(max_single_position_bps BETWEEN 0 AND 10000),
    max_single_issuer_bps   INTEGER CHECK(max_single_issuer_bps BETWEEN 0 AND 10000),
    max_sector_weight_bps   INTEGER CHECK(max_sector_weight_bps BETWEEN 0 AND 10000),
    no_derivatives          INTEGER NOT NULL DEFAULT 0 CHECK(no_derivatives IN (0,1)),
    no_leverage             INTEGER NOT NULL DEFAULT 0 CHECK(no_leverage IN (0,1)),
    no_structured           INTEGER NOT NULL DEFAULT 0 CHECK(no_structured IN (0,1)),
    listed_only             INTEGER NOT NULL DEFAULT 0 CHECK(listed_only IN (0,1)),
    funds_etf_only          INTEGER NOT NULL DEFAULT 0 CHECK(funds_etf_only IN (0,1)),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at              TEXT,
    CHECK(valid_to IS NULL OR valid_to >= valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_pref_id_mandate
    ON investment_preferences(id, mandate_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_pref_one_current
    ON investment_preferences(mandate_id) WHERE is_current = 1 AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_inv_pref_mandate
    ON investment_preferences(mandate_id, valid_from DESC);

CREATE TABLE IF NOT EXISTS investment_restrictions (
    id              TEXT PRIMARY KEY,
    preference_id   TEXT NOT NULL,
    mandate_id      TEXT NOT NULL,
    category        TEXT NOT NULL CHECK(category IN (
                        'ESG','Sektor','Geografie','Währung','Produkt','Konzentration','Custom')),
    restriction_key TEXT NOT NULL,
    restriction_label TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at      TEXT,
    FOREIGN KEY (preference_id, mandate_id) REFERENCES investment_preferences(id, mandate_id) ON UPDATE CASCADE,
    UNIQUE(preference_id, restriction_key)
);
CREATE INDEX IF NOT EXISTS idx_restrictions_preference ON investment_restrictions(preference_id);
CREATE INDEX IF NOT EXISTS idx_restrictions_mandate ON investment_restrictions(mandate_id);

CREATE TABLE IF NOT EXISTS asset_class_focus (
    id              TEXT PRIMARY KEY,
    preference_id   TEXT NOT NULL,
    mandate_id      TEXT NOT NULL,
    asset_class     TEXT NOT NULL CHECK(asset_class IN (
                        'Aktien','Obligationen','Immobilien','Alternative','Liquidität')),
    equity_geo_focus TEXT CHECK(equity_geo_focus IN ('Schweiz Fokus','Global','Europa','Schwellenländer')),
    equity_large_cap INTEGER NOT NULL DEFAULT 1 CHECK(equity_large_cap IN (0,1)),
    equity_small_mid INTEGER NOT NULL DEFAULT 0 CHECK(equity_small_mid IN (0,1)),
    bond_duration   TEXT CHECK(bond_duration IN ('Langfristig','Kurzfristig','Gemischt')),
    bond_inv_grade  INTEGER NOT NULL DEFAULT 1 CHECK(bond_inv_grade IN (0,1)),
    bond_high_yield INTEGER NOT NULL DEFAULT 0 CHECK(bond_high_yield IN (0,1)),
    bond_em         INTEGER NOT NULL DEFAULT 0 CHECK(bond_em IN (0,1)),
    real_estate_geo TEXT CHECK(real_estate_geo IN ('Schweiz','Ausland','Gemischt')),
    real_estate_funds INTEGER NOT NULL DEFAULT 1 CHECK(real_estate_funds IN (0,1)),
    real_estate_direct INTEGER NOT NULL DEFAULT 0 CHECK(real_estate_direct IN (0,1)),
    alt_gold        INTEGER NOT NULL DEFAULT 0 CHECK(alt_gold IN (0,1)),
    alt_liquid_alt  INTEGER NOT NULL DEFAULT 0 CHECK(alt_liquid_alt IN (0,1)),
    alt_hedge_funds INTEGER NOT NULL DEFAULT 0 CHECK(alt_hedge_funds IN (0,1)),
    alt_private_equity INTEGER NOT NULL DEFAULT 0 CHECK(alt_private_equity IN (0,1)),
    alt_crypto      INTEGER NOT NULL DEFAULT 0 CHECK(alt_crypto IN (0,1)),
    liq_instrument  TEXT CHECK(liq_instrument IN ('Geldmarktfonds','Kontoguthaben','Festgeld')),
    liq_reserve_rappen INTEGER NOT NULL DEFAULT 0 CHECK(liq_reserve_rappen >= 0),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (preference_id, mandate_id) REFERENCES investment_preferences(id, mandate_id) ON UPDATE CASCADE,
    UNIQUE(preference_id, asset_class)
);
CREATE INDEX IF NOT EXISTS idx_acf_preference ON asset_class_focus(preference_id);

-- ============================================================
-- 9. VERMÖGENSPOSITIONEN
-- ============================================================

CREATE TABLE IF NOT EXISTS wealth_positions (
    id                          TEXT PRIMARY KEY,
    client_id                   TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE,
    label                       TEXT NOT NULL,
    position_type               TEXT NOT NULL CHECK(position_type IN (
                                'Depot','Liquidität','Immobilien','Vorsorge',
                                'Alternative','Hypothek','Custom')),
    assignment                  TEXT NOT NULL DEFAULT 'Anderes Vermögen'
                                CHECK(assignment IN ('Beratungsvermögen','Anderes Vermögen','Verbindlichkeit')),
    current_value_rappen        INTEGER NOT NULL DEFAULT 0 CHECK(current_value_rappen >= 0),
    currency                    TEXT NOT NULL DEFAULT 'CHF' CHECK(length(currency) = 3),
    valuation_date              TEXT,
    depot_bank                  TEXT,
    depot_account_number        TEXT,
    alloc_equities_bps          INTEGER NOT NULL DEFAULT 0 CHECK(alloc_equities_bps BETWEEN 0 AND 10000),
    alloc_bonds_bps             INTEGER NOT NULL DEFAULT 0 CHECK(alloc_bonds_bps BETWEEN 0 AND 10000),
    alloc_real_estate_bps       INTEGER NOT NULL DEFAULT 0 CHECK(alloc_real_estate_bps BETWEEN 0 AND 10000),
    alloc_liquidity_bps         INTEGER NOT NULL DEFAULT 0 CHECK(alloc_liquidity_bps BETWEEN 0 AND 10000),
    alloc_alternatives_bps      INTEGER NOT NULL DEFAULT 0 CHECK(alloc_alternatives_bps BETWEEN 0 AND 10000),
    property_address            TEXT,
    property_zip_city           TEXT,
    property_usage              TEXT CHECK(property_usage IN (
                                'Selbstgenutzt','Renditeobjekt','Ferienimmobilie','Gemischt')),
    property_rental_income_rappen INTEGER NOT NULL DEFAULT 0 CHECK(property_rental_income_rappen >= 0),
    pension_type                TEXT CHECK(pension_type IN (
                                'BVG','Säule 3a','Freizügigkeit','Säule 3b','Lebensversicherung')),
    pension_institution         TEXT,
    pension_technical_rate_bps  INTEGER,
    pension_retirement_age      INTEGER CHECK(pension_retirement_age BETWEEN 0 AND 100),
    pension_payout_form         TEXT CHECK(pension_payout_form IN ('Rente','Kapital','Gemischt','Offen')),
    pension_wef_possible        INTEGER NOT NULL DEFAULT 0 CHECK(pension_wef_possible IN (0,1)),
    mortgage_bank               TEXT,
    mortgage_type               TEXT CHECK(mortgage_type IN ('Festhypothek','SARON','Gemischt')),
    mortgage_interest_rate_bps  INTEGER,
    mortgage_maturity_date      TEXT,
    mortgage_amortization_rappen INTEGER NOT NULL DEFAULT 0 CHECK(mortgage_amortization_rappen >= 0),
    mortgage_amortization_type  TEXT CHECK(mortgage_amortization_type IN ('Direkt','Indirekt (3a)','Keine')),
    mortgage_linked_property_id TEXT,
    asset_subtype               TEXT,
    asset_expected_return_bps   INTEGER,
    asset_liquidity             TEXT CHECK(asset_liquidity IN (
                                'Liquide (< 30 Tage)','Eingeschränkt (30–180 Tage)',
                                'Illiquid (> 180 Tage)','Gebunden')),
    asset_valuation_method      TEXT CHECK(asset_valuation_method IN (
                                'Selbstschätzung','Fachgutachten',
                                'Versicherungswert','Marktpreis','PK-Ausweis')),
    asset_location              TEXT,
    liquidity_instrument        TEXT CHECK(liquidity_instrument IN (
                                'Kontoguthaben','Sparkonto','Festgeld',
                                'Kassenobligation','Geldmarktfonds')),
    liquidity_interest_rate_bps INTEGER,
    liquidity_available_from    TEXT,
    is_available_for_goal_funding INTEGER NOT NULL DEFAULT 0 CHECK(is_available_for_goal_funding IN (0,1)),
    goal_funding_method         TEXT CHECK(goal_funding_method IN (
                                'Verkauf','Belehnung','Ignorieren','Automatisch')),
    notes                       TEXT,
    is_active                   INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at                  TEXT,
    CHECK(position_type <> 'Hypothek' OR assignment = 'Verbindlichkeit'),
    CHECK(position_type <> 'Depot' OR (
        alloc_equities_bps + alloc_bonds_bps + alloc_real_estate_bps
        + alloc_liquidity_bps + alloc_alternatives_bps = 10000
    ))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wealth_id_client ON wealth_positions(id, client_id);
CREATE INDEX IF NOT EXISTS idx_wealth_client ON wealth_positions(client_id);
CREATE INDEX IF NOT EXISTS idx_wealth_assignment ON wealth_positions(assignment);
CREATE INDEX IF NOT EXISTS idx_wealth_type ON wealth_positions(position_type);

-- ============================================================
-- 10. CASHFLOWS (FIX v4: 'abgeleitet' entfernt)
-- ============================================================

CREATE TABLE IF NOT EXISTS cashflows (
    id              TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE,
    cashflow_type   TEXT NOT NULL CHECK(cashflow_type IN ('Income','Expense')),
    label           TEXT NOT NULL,
    amount_rappen   INTEGER NOT NULL CHECK(amount_rappen >= 0),
    currency        TEXT NOT NULL DEFAULT 'CHF' CHECK(length(currency) = 3),
    frequency       TEXT NOT NULL DEFAULT 'jährlich'
                    CHECK(frequency IN ('monatlich','quartalsweise','halbjährlich','jährlich','einmalig')),
    nature          TEXT NOT NULL DEFAULT 'wiederkehrend'
                    CHECK(nature IN ('wiederkehrend','einmalig')),
    valid_from      TEXT,
    valid_until     TEXT,
    is_inflation_linked INTEGER NOT NULL DEFAULT 0 CHECK(is_inflation_linked IN (0,1)),
    notes           TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at      TEXT,
    CHECK(valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);
CREATE INDEX IF NOT EXISTS idx_cashflows_client ON cashflows(client_id);
CREATE INDEX IF NOT EXISTS idx_cashflows_type ON cashflows(client_id, cashflow_type);

-- ============================================================
-- 11. ZIELE (FIX v4: Composite FK + strenge CHECKs + goal_family/type Konsistenz)
-- ============================================================

CREATE TABLE IF NOT EXISTS goals (
    id                  TEXT PRIMARY KEY,
    mandate_id          TEXT NOT NULL,
    client_id           TEXT NOT NULL,
    -- FIX v4: goal_family/goal_type Mapping via CHECK (kein Drift möglich)
    goal_family         TEXT NOT NULL CHECK(goal_family IN ('Vermögen','Cashflow','Rendite','Maximierung')),
    goal_type           TEXT NOT NULL CHECK(goal_type IN (
                            'Kapitalerhalt','Vermögensziel',
                            'Einmalige_Ausgabe','Wiederkehrende_Ausgabe','Pensionsausgabe',
                            'Renditeziel','Maximierung')),
    label               TEXT NOT NULL,
    rank                INTEGER NOT NULL CHECK(rank >= 1),
    weight_bps          INTEGER CHECK(weight_bps BETWEEN 0 AND 10000),
    goal_scope          TEXT NOT NULL DEFAULT 'Beratungsvermögen'
                        CHECK(goal_scope IN ('Beratungsvermögen','Gesamtvermögen')),
    value_mode          TEXT NOT NULL DEFAULT 'nominal' CHECK(value_mode IN ('nominal','real')),
    target_amount_rappen INTEGER CHECK(target_amount_rappen >= 0),
    target_wealth_rappen INTEGER CHECK(target_wealth_rappen >= 0),
    target_return_bps   INTEGER,
    start_date          TEXT,
    horizon_years       INTEGER CHECK(horizon_years BETWEEN 0 AND 100),
    target_date         TEXT,
    is_ongoing          INTEGER NOT NULL DEFAULT 0 CHECK(is_ongoing IN (0,1)),
    frequency           TEXT CHECK(frequency IN ('monatlich','quartalsweise','halbjährlich','jährlich')),
    hardness            TEXT NOT NULL DEFAULT 'Primär' CHECK(hardness IN ('Hart','Primär','Opportunistisch')),
    -- FIX v4: Composite FK für linked_position_id
    linked_position_id  TEXT,
    notes               TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    achievement_score   INTEGER CHECK(achievement_score BETWEEN 0 AND 100),
    last_scored_at      TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at          TEXT,
    FOREIGN KEY (mandate_id, client_id) REFERENCES mandates(id, client_id) ON UPDATE CASCADE,
    -- FIX v4: Composite FK schützt vor cross-client Position-Zuweisung
    FOREIGN KEY (linked_position_id, client_id) REFERENCES wealth_positions(id, client_id) ON UPDATE CASCADE,
    -- FIX v4: goal_family/goal_type Konsistenz
    CHECK(
        (goal_family = 'Vermögen'      AND goal_type IN ('Kapitalerhalt','Vermögensziel'))
        OR (goal_family = 'Cashflow'   AND goal_type IN ('Einmalige_Ausgabe','Wiederkehrende_Ausgabe','Pensionsausgabe'))
        OR (goal_family = 'Rendite'    AND goal_type = 'Renditeziel')
        OR (goal_family = 'Maximierung' AND goal_type = 'Maximierung')
    ),
    -- FIX v4: Pflichtfelder streng — andere Felder müssen NULL sein
    CHECK(
        (goal_type = 'Renditeziel'
         AND target_return_bps IS NOT NULL
         AND target_amount_rappen IS NULL AND target_wealth_rappen IS NULL)
        OR
        (goal_type IN ('Einmalige_Ausgabe','Wiederkehrende_Ausgabe','Pensionsausgabe')
         AND target_amount_rappen IS NOT NULL
         AND target_return_bps IS NULL AND target_wealth_rappen IS NULL)
        OR
        (goal_type IN ('Kapitalerhalt','Vermögensziel')
         AND target_wealth_rappen IS NOT NULL
         AND target_return_bps IS NULL AND target_amount_rappen IS NULL)
        OR
        (goal_type = 'Maximierung'
         AND target_return_bps IS NULL AND target_amount_rappen IS NULL AND target_wealth_rappen IS NULL)
    ),
    CHECK(target_date IS NULL OR start_date IS NULL OR target_date >= start_date)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_goals_rank_active
    ON goals(mandate_id, rank) WHERE is_active = 1 AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_goals_mandate ON goals(mandate_id);
CREATE INDEX IF NOT EXISTS idx_goals_client ON goals(client_id);
CREATE INDEX IF NOT EXISTS idx_goals_linked_position ON goals(linked_position_id);

-- ============================================================
-- 12. PLANUNGSANNAHMEN
-- ============================================================

CREATE TABLE IF NOT EXISTS planning_assumptions (
    id                      TEXT PRIMARY KEY,
    mandate_id              TEXT NOT NULL,
    client_id               TEXT NOT NULL,
    version                 INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    is_current              INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    valid_from              TEXT NOT NULL DEFAULT (date('now')),
    valid_to                TEXT,
    supersedes_id           TEXT,
    retirement_age_primary  INTEGER CHECK(retirement_age_primary BETWEEN 0 AND 100),
    retirement_age_partner  INTEGER CHECK(retirement_age_partner BETWEEN 0 AND 100),
    life_expectancy_primary INTEGER CHECK(life_expectancy_primary BETWEEN 0 AND 130),
    life_expectancy_partner INTEGER CHECK(life_expectancy_partner BETWEEN 0 AND 130),
    inflation_assumption_bps INTEGER,
    pension_indexation_bps  INTEGER,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at              TEXT,
    FOREIGN KEY (mandate_id, client_id) REFERENCES mandates(id, client_id) ON UPDATE CASCADE,
    CHECK(valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_planning_one_current
    ON planning_assumptions(mandate_id) WHERE is_current = 1 AND deleted_at IS NULL;

-- ============================================================
-- 13. OPTIMIZER POLICIES
-- ============================================================

CREATE TABLE IF NOT EXISTS optimizer_policies (
    id                      TEXT PRIMARY KEY,
    policy_name             TEXT NOT NULL,
    version                 INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    is_current              INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    valid_from              TEXT NOT NULL DEFAULT (date('now')),
    valid_to                TEXT,
    optimizer_engine        TEXT NOT NULL DEFAULT 'goal_based_v1',
    max_real_estate_bps     INTEGER NOT NULL DEFAULT 2000 CHECK(max_real_estate_bps BETWEEN 0 AND 10000),
    max_alternatives_bps    INTEGER NOT NULL DEFAULT 1000 CHECK(max_alternatives_bps BETWEEN 0 AND 10000),
    min_liquidity_bps       INTEGER NOT NULL DEFAULT 0 CHECK(min_liquidity_bps BETWEEN 0 AND 10000),
    allow_other_assets_for_goals INTEGER NOT NULL DEFAULT 1 CHECK(allow_other_assets_for_goals IN (0,1)),
    fee_model_json          TEXT CHECK(fee_model_json IS NULL OR json_valid(fee_model_json)),
    notes                   TEXT,
    created_by              TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_optimizer_one_current
    ON optimizer_policies(policy_name) WHERE is_current = 1;

-- ============================================================
-- 14. SOLL-ALLOKATION (FIX v4: Composite FK für based_on_assessment_id)
-- ============================================================

CREATE TABLE IF NOT EXISTS target_allocations (
    id                      TEXT PRIMARY KEY,
    mandate_id              TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    version                 INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    is_current              INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    target_equities_bps     INTEGER NOT NULL DEFAULT 0 CHECK(target_equities_bps BETWEEN 0 AND 10000),
    target_bonds_bps        INTEGER NOT NULL DEFAULT 0 CHECK(target_bonds_bps BETWEEN 0 AND 10000),
    target_real_estate_bps  INTEGER NOT NULL DEFAULT 0 CHECK(target_real_estate_bps BETWEEN 0 AND 10000),
    target_alternatives_bps INTEGER NOT NULL DEFAULT 0 CHECK(target_alternatives_bps BETWEEN 0 AND 10000),
    target_liquidity_bps    INTEGER NOT NULL DEFAULT 0 CHECK(target_liquidity_bps BETWEEN 0 AND 10000),
    band_equities_min_bps   INTEGER NOT NULL CHECK(band_equities_min_bps BETWEEN 0 AND 10000),
    band_equities_max_bps   INTEGER NOT NULL CHECK(band_equities_max_bps BETWEEN 0 AND 10000),
    band_bonds_min_bps      INTEGER NOT NULL CHECK(band_bonds_min_bps BETWEEN 0 AND 10000),
    band_bonds_max_bps      INTEGER NOT NULL CHECK(band_bonds_max_bps BETWEEN 0 AND 10000),
    band_real_estate_min_bps INTEGER NOT NULL CHECK(band_real_estate_min_bps BETWEEN 0 AND 10000),
    band_real_estate_max_bps INTEGER NOT NULL CHECK(band_real_estate_max_bps BETWEEN 0 AND 10000),
    band_alternatives_min_bps INTEGER NOT NULL CHECK(band_alternatives_min_bps BETWEEN 0 AND 10000),
    band_alternatives_max_bps INTEGER NOT NULL CHECK(band_alternatives_max_bps BETWEEN 0 AND 10000),
    band_liquidity_min_bps  INTEGER NOT NULL CHECK(band_liquidity_min_bps BETWEEN 0 AND 10000),
    band_liquidity_max_bps  INTEGER NOT NULL CHECK(band_liquidity_max_bps BETWEEN 0 AND 10000),
    risky_fraction_bps      INTEGER CHECK(risky_fraction_bps BETWEEN 0 AND 10000),
    -- FIX v4: Composite FK für based_on_assessment_id
    based_on_assessment_id  TEXT,
    policy_id               TEXT NOT NULL REFERENCES optimizer_policies(id) ON UPDATE CASCADE,
    set_by                  TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    set_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    approved_by             TEXT REFERENCES users(id) ON UPDATE CASCADE,
    approved_at             TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at              TEXT,
    FOREIGN KEY (based_on_assessment_id, mandate_id) REFERENCES risk_assessments(id, mandate_id) ON UPDATE CASCADE,
    CHECK(target_equities_bps + target_bonds_bps + target_real_estate_bps + target_alternatives_bps + target_liquidity_bps = 10000),
    CHECK(band_equities_min_bps <= target_equities_bps AND target_equities_bps <= band_equities_max_bps),
    CHECK(band_bonds_min_bps <= target_bonds_bps AND target_bonds_bps <= band_bonds_max_bps),
    CHECK(band_real_estate_min_bps <= target_real_estate_bps AND target_real_estate_bps <= band_real_estate_max_bps),
    CHECK(band_alternatives_min_bps <= target_alternatives_bps AND target_alternatives_bps <= band_alternatives_max_bps),
    CHECK(band_liquidity_min_bps <= target_liquidity_bps AND target_liquidity_bps <= band_liquidity_max_bps),
    CHECK((approved_by IS NULL AND approved_at IS NULL) OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_target_alloc_id_mandate ON target_allocations(id, mandate_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_target_alloc_one_current
    ON target_allocations(mandate_id) WHERE is_current = 1 AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_target_alloc_mandate ON target_allocations(mandate_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_target_alloc_policy ON target_allocations(policy_id);
CREATE INDEX IF NOT EXISTS idx_target_alloc_assessment ON target_allocations(based_on_assessment_id);

-- ============================================================
-- 15. KAPITALMARKTANNAHMEN
-- ============================================================

CREATE TABLE IF NOT EXISTS capital_market_assumptions (
    id                          TEXT PRIMARY KEY,
    assumption_set_name         TEXT NOT NULL DEFAULT 'Standard',
    version                     INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    valid_from                  TEXT NOT NULL,
    valid_until                 TEXT,
    is_current                  INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    bonds_chf_ig_return_bps     INTEGER,
    bonds_chf_ig_vol_bps        INTEGER CHECK(bonds_chf_ig_vol_bps IS NULL OR bonds_chf_ig_vol_bps >= 0),
    bonds_fx_hedged_return_bps  INTEGER,
    bonds_fx_hedged_vol_bps     INTEGER CHECK(bonds_fx_hedged_vol_bps IS NULL OR bonds_fx_hedged_vol_bps >= 0),
    bonds_hy_return_bps         INTEGER,
    bonds_hy_vol_bps            INTEGER CHECK(bonds_hy_vol_bps IS NULL OR bonds_hy_vol_bps >= 0),
    equity_ch_return_bps        INTEGER,
    equity_ch_vol_bps           INTEGER CHECK(equity_ch_vol_bps IS NULL OR equity_ch_vol_bps >= 0),
    equity_intl_return_bps      INTEGER,
    equity_intl_vol_bps         INTEGER CHECK(equity_intl_vol_bps IS NULL OR equity_intl_vol_bps >= 0),
    equity_em_return_bps        INTEGER,
    equity_em_vol_bps           INTEGER CHECK(equity_em_vol_bps IS NULL OR equity_em_vol_bps >= 0),
    real_estate_ch_return_bps   INTEGER,
    real_estate_ch_vol_bps      INTEGER CHECK(real_estate_ch_vol_bps IS NULL OR real_estate_ch_vol_bps >= 0),
    alternatives_gold_return_bps INTEGER,
    alternatives_gold_vol_bps   INTEGER CHECK(alternatives_gold_vol_bps IS NULL OR alternatives_gold_vol_bps >= 0),
    liquidity_return_bps        INTEGER,
    liquidity_vol_bps           INTEGER CHECK(liquidity_vol_bps IS NULL OR liquidity_vol_bps >= 0),
    inflation_path_json         TEXT CHECK(inflation_path_json IS NULL OR json_valid(inflation_path_json)),
    source                      TEXT DEFAULT 'Portfolio Management intern',
    notes                       TEXT,
    created_by                  TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at                  TEXT,
    CHECK(valid_until IS NULL OR valid_until >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cma_one_current
    ON capital_market_assumptions(assumption_set_name) WHERE is_current = 1 AND deleted_at IS NULL;

-- ============================================================
-- 16. BUILDING BLOCKS & HOUSE MATRIX
-- ============================================================

CREATE TABLE IF NOT EXISTS building_blocks (
    id                          TEXT PRIMARY KEY,
    policy_id                   TEXT NOT NULL REFERENCES optimizer_policies(id) ON UPDATE CASCADE,
    asset_class                 TEXT NOT NULL,
    sub_asset_class             TEXT NOT NULL,
    universe                    TEXT NOT NULL DEFAULT 'Standard' CHECK(universe IN ('Standard','Alternativ')),
    advisory                    INTEGER NOT NULL DEFAULT 1 CHECK(advisory IN (0,1)),
    risky_fraction_bps          INTEGER NOT NULL CHECK(risky_fraction_bps BETWEEN 0 AND 10000),
    contribution_standard_bps   INTEGER CHECK(contribution_standard_bps IS NULL OR contribution_standard_bps BETWEEN 0 AND 10000),
    contribution_alternative_bps INTEGER CHECK(contribution_alternative_bps IS NULL OR contribution_alternative_bps BETWEEN 0 AND 10000),
    is_active                   INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(policy_id, sub_asset_class, universe, advisory)
);
CREATE INDEX IF NOT EXISTS idx_building_blocks_policy ON building_blocks(policy_id);

CREATE TABLE IF NOT EXISTS house_matrix (
    id                      TEXT PRIMARY KEY,
    policy_id               TEXT NOT NULL REFERENCES optimizer_policies(id) ON UPDATE CASCADE,
    score_from              INTEGER NOT NULL CHECK(score_from BETWEEN 1 AND 10),
    score_to                INTEGER NOT NULL CHECK(score_to BETWEEN 1 AND 10),
    profile_name            TEXT NOT NULL CHECK(profile_name IN (
                                'Kapitalschutz','Defensiv','Ausgewogen','Wachstum','Dynamisch','Aktien')),
    liq_min_bps             INTEGER NOT NULL CHECK(liq_min_bps BETWEEN 0 AND 10000),
    liq_target_bps          INTEGER NOT NULL CHECK(liq_target_bps BETWEEN 0 AND 10000),
    liq_max_bps             INTEGER NOT NULL CHECK(liq_max_bps BETWEEN 0 AND 10000),
    bonds_min_bps           INTEGER NOT NULL CHECK(bonds_min_bps BETWEEN 0 AND 10000),
    bonds_target_bps        INTEGER NOT NULL CHECK(bonds_target_bps BETWEEN 0 AND 10000),
    bonds_max_bps           INTEGER NOT NULL CHECK(bonds_max_bps BETWEEN 0 AND 10000),
    equity_min_bps          INTEGER NOT NULL CHECK(equity_min_bps BETWEEN 0 AND 10000),
    equity_target_bps       INTEGER NOT NULL CHECK(equity_target_bps BETWEEN 0 AND 10000),
    equity_max_bps          INTEGER NOT NULL CHECK(equity_max_bps BETWEEN 0 AND 10000),
    real_estate_min_bps     INTEGER NOT NULL CHECK(real_estate_min_bps BETWEEN 0 AND 10000),
    real_estate_target_bps  INTEGER NOT NULL CHECK(real_estate_target_bps BETWEEN 0 AND 10000),
    real_estate_max_bps     INTEGER NOT NULL CHECK(real_estate_max_bps BETWEEN 0 AND 10000),
    alt_min_bps             INTEGER NOT NULL CHECK(alt_min_bps BETWEEN 0 AND 10000),
    alt_target_bps          INTEGER NOT NULL CHECK(alt_target_bps BETWEEN 0 AND 10000),
    alt_max_bps             INTEGER NOT NULL CHECK(alt_max_bps BETWEEN 0 AND 10000),
    equity_minimum_bps      INTEGER NOT NULL DEFAULT 0 CHECK(equity_minimum_bps BETWEEN 0 AND 10000),
    max_risky_fraction_bps  INTEGER NOT NULL CHECK(max_risky_fraction_bps BETWEEN 0 AND 10000),
    is_active               INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(score_from <= score_to),
    CHECK(liq_min_bps <= liq_target_bps AND liq_target_bps <= liq_max_bps),
    CHECK(bonds_min_bps <= bonds_target_bps AND bonds_target_bps <= bonds_max_bps),
    CHECK(equity_min_bps <= equity_target_bps AND equity_target_bps <= equity_max_bps),
    CHECK(real_estate_min_bps <= real_estate_target_bps AND real_estate_target_bps <= real_estate_max_bps),
    CHECK(alt_min_bps <= alt_target_bps AND alt_target_bps <= alt_max_bps),
    CHECK(liq_target_bps + bonds_target_bps + equity_target_bps + real_estate_target_bps + alt_target_bps = 10000),
    UNIQUE(policy_id, score_from, score_to)
);
CREATE INDEX IF NOT EXISTS idx_house_matrix_policy ON house_matrix(policy_id);

-- ============================================================
-- 17. REVIEW TRIGGER & ADVISORY LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS review_triggers (
    id              TEXT PRIMARY KEY,
    mandate_id      TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    trigger_type    TEXT NOT NULL CHECK(trigger_type IN ('Zeit','Markt','Ereignis')),
    trigger_name    TEXT NOT NULL,
    threshold_bps   INTEGER,
    frequency       TEXT CHECK(frequency IN (
                        'monatlich','quartalsweise','halbjährlich',
                        'jährlich','einmalig','bei Ereignis')),
    status          TEXT NOT NULL DEFAULT 'Aktiv'
                    CHECK(status IN ('Aktiv','Ausgelöst','Erledigt','Übersprungen','Inaktiv')),
    next_due_at     TEXT,
    last_triggered_at TEXT,
    triggered_value TEXT,
    triggered_at    TEXT,
    triggered_notes TEXT,
    calendar_exported INTEGER NOT NULL DEFAULT 0 CHECK(calendar_exported IN (0,1)),
    calendar_exported_at TEXT,
    is_system       INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0,1)),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_triggers_id_mandate ON review_triggers(id, mandate_id);
CREATE INDEX IF NOT EXISTS idx_triggers_mandate ON review_triggers(mandate_id);
CREATE INDEX IF NOT EXISTS idx_triggers_status ON review_triggers(status);

-- ============================================================
-- 18. VERTRAGSDOKUMENTE
-- FIX v4: Composite FK supersedes_id, Signatur-CHECK verschärft
-- ============================================================

CREATE TABLE IF NOT EXISTS contract_documents (
    id              TEXT PRIMARY KEY,
    mandate_id      TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    document_type   TEXT NOT NULL CHECK(document_type IN (
                        'Beratungsvertrag','Anlagestrategie','Anlagerezept',
                        'Beratungsprotokoll','Risikoprofilierung',
                        'Override-Zustimmung','Eignungsprüfung','Sonstiges')),
    title           TEXT NOT NULL,
    content_json    TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    pdf_path        TEXT,
    checksum_sha256 TEXT,
    pdf_generated_at TEXT,
    status          TEXT NOT NULL DEFAULT 'Entwurf'
                    CHECK(status IN ('Entwurf','Bereit','Unterzeichnet','Archiviert')),
    signed_by_advisor INTEGER NOT NULL DEFAULT 0 CHECK(signed_by_advisor IN (0,1)),
    signed_by_client  INTEGER NOT NULL DEFAULT 0 CHECK(signed_by_client IN (0,1)),
    signed_at       TEXT,
    version         INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    -- FIX v4: Composite FK für supersedes_id
    supersedes_id   TEXT,
    created_by      TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at      TEXT,
    -- FIX v4: Verschärft — signed_at erfordert mind. einen Unterzeichner
    CHECK(
        (signed_at IS NULL AND signed_by_advisor = 0 AND signed_by_client = 0)
        OR
        (signed_at IS NOT NULL AND (signed_by_advisor = 1 OR signed_by_client = 1))
    ),
    FOREIGN KEY (supersedes_id, mandate_id) REFERENCES contract_documents(id, mandate_id) ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_docs_id_mandate ON contract_documents(id, mandate_id);
CREATE INDEX IF NOT EXISTS idx_documents_mandate ON contract_documents(mandate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_created_by ON contract_documents(created_by);

-- Advisory Log (FIX v4: document_id als FK)
CREATE TABLE IF NOT EXISTS advisory_log (
    id              TEXT PRIMARY KEY,
    mandate_id      TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    entry_type      TEXT NOT NULL CHECK(entry_type IN (
                        'Jahresreview','Quartalscheck','Strategie-Anpassung',
                        'Override-Entscheid','Ereignis-Reaktion','Drift-Entscheid',
                        'Zieländerung','Restriktionsänderung',
                        'Initialer Beratungsabschluss','Eignungsprüfung','Sonstiges')),
    title           TEXT NOT NULL,
    description     TEXT,
    decision        TEXT CHECK(decision IN (
                        'Keine Transaktion','Transaktion empfohlen','Strategie angepasst',
                        'Profil angepasst','Override bestätigt','Kein Handlungsbedarf')),
    trigger_id      TEXT,
    advisor_id      TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    client_signed   INTEGER NOT NULL DEFAULT 0 CHECK(client_signed IN (0,1)),
    client_signed_at TEXT,
    -- FIX v4: document_id jetzt als Composite FK
    document_id     TEXT,
    entry_date      TEXT NOT NULL DEFAULT (date('now')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (trigger_id, mandate_id) REFERENCES review_triggers(id, mandate_id) ON UPDATE CASCADE,
    FOREIGN KEY (document_id, mandate_id) REFERENCES contract_documents(id, mandate_id) ON UPDATE CASCADE,
    CHECK((client_signed = 0 AND client_signed_at IS NULL) OR (client_signed = 1 AND client_signed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_advisory_log_mandate ON advisory_log(mandate_id, entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_advisory_log_trigger ON advisory_log(trigger_id);
CREATE INDEX IF NOT EXISTS idx_advisory_log_document ON advisory_log(document_id);

-- ============================================================
-- 19. PRODUKTE & SUITABILITY
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id              TEXT PRIMARY KEY,
    isin            TEXT COLLATE NOCASE,
    symbol          TEXT,
    product_name    TEXT NOT NULL,
    provider        TEXT,
    product_type    TEXT NOT NULL CHECK(product_type IN (
                        'ETF','Fonds','Einzeltitel','Strukturiertes Produkt',
                        'Anleihe','Cash','Immobilienfonds','Alternative Anlage','Sonstiges')),
    asset_class     TEXT NOT NULL CHECK(asset_class IN (
                        'Aktien','Obligationen','Immobilien','Alternative','Liquidität')),
    sub_asset_class TEXT,
    currency        TEXT NOT NULL DEFAULT 'CHF' CHECK(length(currency) = 3),
    ter_bps         INTEGER CHECK(ter_bps IS NULL OR ter_bps >= 0),
    sfdr_class      TEXT CHECK(sfdr_class IN ('6','8','9')),
    esg_rating      TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deleted_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_products_isin_active
    ON products(isin) WHERE isin IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS product_suitability (
    id                      TEXT PRIMARY KEY,
    product_id              TEXT NOT NULL REFERENCES products(id) ON UPDATE CASCADE,
    profile_from            INTEGER NOT NULL CHECK(profile_from BETWEEN 1 AND 10),
    profile_to              INTEGER NOT NULL CHECK(profile_to BETWEEN 1 AND 10),
    advisory_allowed        INTEGER NOT NULL DEFAULT 1 CHECK(advisory_allowed IN (0,1)),
    discretionary_allowed   INTEGER NOT NULL DEFAULT 1 CHECK(discretionary_allowed IN (0,1)),
    requires_appropriateness INTEGER NOT NULL DEFAULT 0 CHECK(requires_appropriateness IN (0,1)),
    requires_override       INTEGER NOT NULL DEFAULT 0 CHECK(requires_override IN (0,1)),
    max_position_bps        INTEGER CHECK(max_position_bps IS NULL OR max_position_bps BETWEEN 0 AND 10000),
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(profile_from <= profile_to),
    UNIQUE(product_id, profile_from, profile_to)
);
CREATE INDEX IF NOT EXISTS idx_product_suitability_product ON product_suitability(product_id);

-- ============================================================
-- 20. EMPFOHLENE PORTFOLIOS
-- FIX v4: Composite FKs für assessment_id + target_allocation_id
-- ============================================================

CREATE TABLE IF NOT EXISTS recommendation_runs (
    id                          TEXT PRIMARY KEY,
    mandate_id                  TEXT NOT NULL,
    client_id                   TEXT NOT NULL,
    -- FIX v4: Composite FKs
    assessment_id               TEXT,
    target_allocation_id        TEXT,
    policy_id                   TEXT NOT NULL REFERENCES optimizer_policies(id) ON UPDATE CASCADE,
    capital_market_assumptions_id TEXT REFERENCES capital_market_assumptions(id) ON UPDATE CASCADE,
    run_type                    TEXT NOT NULL CHECK(run_type IN ('Initial','Review','WhatIf','Optimizer')),
    objective_summary           TEXT,
    optimizer_version           TEXT,
    -- Optimizer-Methodik für Dokumentation
    weighting_regime            TEXT CHECK(weighting_regime IN ('Equal-Weight','Ranked-Weight','Custom')),
    fee_assumptions_json        TEXT CHECK(fee_assumptions_json IS NULL OR json_valid(fee_assumptions_json)),
    other_assets_included       INTEGER NOT NULL DEFAULT 0 CHECK(other_assets_included IN (0,1)),
    result_status               TEXT NOT NULL DEFAULT 'Draft'
                                CHECK(result_status IN ('Draft','Final','Rejected','Superseded')),
    created_by                  TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (mandate_id, client_id) REFERENCES mandates(id, client_id) ON UPDATE CASCADE,
    FOREIGN KEY (assessment_id, mandate_id) REFERENCES risk_assessments(id, mandate_id) ON UPDATE CASCADE,
    FOREIGN KEY (target_allocation_id, mandate_id) REFERENCES target_allocations(id, mandate_id) ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rec_runs_mandate ON recommendation_runs(mandate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rec_runs_assessment ON recommendation_runs(assessment_id);
CREATE INDEX IF NOT EXISTS idx_rec_runs_allocation ON recommendation_runs(target_allocation_id);

CREATE TABLE IF NOT EXISTS recommendation_positions (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL REFERENCES recommendation_runs(id) ON UPDATE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products(id) ON UPDATE CASCADE,
    -- FIX v4: asset_class entfernt (redundant zu products.asset_class)
    target_weight_bps   INTEGER NOT NULL CHECK(target_weight_bps BETWEEN 0 AND 10000),
    target_amount_rappen INTEGER CHECK(target_amount_rappen IS NULL OR target_amount_rappen >= 0),
    rationale           TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(run_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_rec_positions_run ON recommendation_positions(run_id);
CREATE INDEX IF NOT EXISTS idx_rec_positions_product ON recommendation_positions(product_id);

-- ============================================================
-- 21. REPORT ARCHIV
-- ============================================================

CREATE TABLE IF NOT EXISTS report_archive (
    id              TEXT PRIMARY KEY,
    mandate_id      TEXT NOT NULL REFERENCES mandates(id) ON UPDATE CASCADE,
    run_id          TEXT REFERENCES recommendation_runs(id) ON UPDATE CASCADE,
    document_id     TEXT,
    report_type     TEXT NOT NULL CHECK(report_type IN (
                        'Beratungsreport','Anlagevorschlag','Risikoprofil',
                        'Review','Eignungsprüfung','Sonstiges')),
    file_path       TEXT NOT NULL,
    checksum_sha256 TEXT,
    generated_by    TEXT NOT NULL REFERENCES users(id) ON UPDATE CASCADE,
    generated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    delivered_at    TEXT,
    deleted_at      TEXT,
    FOREIGN KEY (document_id, mandate_id) REFERENCES contract_documents(id, mandate_id) ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_report_archive_mandate ON report_archive(mandate_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_report_archive_run ON report_archive(run_id);
CREATE INDEX IF NOT EXISTS idx_report_archive_document ON report_archive(document_id);

-- ============================================================
-- 22. AUDIT LOG (immutable)
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    user_id     TEXT REFERENCES users(id) ON UPDATE CASCADE,
    user_name   TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    record_id   TEXT NOT NULL,
    action      TEXT NOT NULL CHECK(action IN ('CREATE','UPDATE','DELETE','LOGIN','EXPORT','PASSWORD_RESET')),
    field_name  TEXT,
    old_value   TEXT,
    new_value   TEXT,
    mandate_id  TEXT,
    client_id   TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_record ON audit_log(table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_mandate ON audit_log(mandate_id);

-- ============================================================
-- 23. SYSTEM KONFIGURATION
-- ============================================================

CREATE TABLE IF NOT EXISTS system_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    description TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_by  TEXT REFERENCES users(id) ON UPDATE CASCADE
);

INSERT OR IGNORE INTO system_config (key, value, description, updated_at, updated_by) VALUES
('version',                '4.0.0',    '5Eyes App Version',                                              strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('schema_version',         '4.0.0',    'Datenbankschema Version',                                        strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('default_currency',       'CHF',      'Standard-Währung',                                               strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('default_language',       'DE',       'Standard-Sprache',                                               strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('knowledge_review_months','24',       'Monate bis FIDLEG Kenntnisse neu bestätigt werden müssen',        strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('drift_threshold_bps',    '500',      'Standard Drift-Schwelle in Basispunkten (5%)',                    strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('annual_review_month',    '9',        'Monat für Jahresreview (1-12)',                                   strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('backup_enabled',         '1',        'Automatisches Backup aktiviert',                                 strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('encryption_enabled',     '1',        'Datenbankverschlüsselung aktiviert',                             strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('ombudsman_body',         'OFD',      'Standardmässige Ombudsstelle (OFD oder SwissFinO)',               strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL),
('adviser_register_body',  'FINMA',    'Beraterregister-Stelle',                                         strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL);

-- ============================================================
-- 24. VIEWS
-- ============================================================

CREATE VIEW IF NOT EXISTS v_client_wealth_summary AS
SELECT
    c.id AS client_id,
    c.first_name || ' ' || c.last_name AS client_name,
    c.client_classification,
    COALESCE(SUM(CASE WHEN wp.assignment != 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS gross_wealth_rappen,
    COALESCE(SUM(CASE WHEN wp.assignment = 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS liabilities_rappen,
    COALESCE(SUM(CASE WHEN wp.assignment != 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0)
    - COALESCE(SUM(CASE WHEN wp.assignment = 'Verbindlichkeit' THEN wp.current_value_rappen ELSE 0 END),0) AS net_worth_rappen,
    COALESCE(SUM(CASE WHEN wp.assignment = 'Beratungsvermögen' THEN wp.current_value_rappen ELSE 0 END),0) AS advisory_wealth_rappen
FROM clients c
LEFT JOIN wealth_positions wp ON wp.client_id = c.id AND wp.deleted_at IS NULL AND wp.is_active = 1
WHERE c.deleted_at IS NULL
GROUP BY c.id;

CREATE VIEW IF NOT EXISTS v_client_cashflow_surplus AS
SELECT
    c.id AS client_id,
    c.first_name || ' ' || c.last_name AS client_name,
    COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Income' THEN cf.amount_rappen ELSE 0 END),0) AS total_income_rappen,
    COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Expense' THEN cf.amount_rappen ELSE 0 END),0) AS total_expense_rappen,
    COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Income' THEN cf.amount_rappen ELSE 0 END),0)
    - COALESCE(SUM(CASE WHEN cf.cashflow_type = 'Expense' THEN cf.amount_rappen ELSE 0 END),0) AS surplus_rappen
FROM clients c
LEFT JOIN cashflows cf ON cf.client_id = c.id AND cf.deleted_at IS NULL AND cf.is_active = 1
WHERE c.deleted_at IS NULL
GROUP BY c.id;

CREATE VIEW IF NOT EXISTS v_active_triggers AS
SELECT rt.*, c.first_name || ' ' || c.last_name AS client_name, m.mandate_number
FROM review_triggers rt
JOIN mandates m ON m.id = rt.mandate_id
JOIN clients c ON c.id = m.client_id
WHERE rt.status IN ('Aktiv','Ausgelöst') AND rt.deleted_at IS NULL
  AND m.deleted_at IS NULL AND c.deleted_at IS NULL
ORDER BY CASE rt.status WHEN 'Ausgelöst' THEN 0 ELSE 1 END, rt.next_due_at;

-- ============================================================
-- 25. TRIGGER: IMMUTABILITY
-- ============================================================

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
BEFORE UPDATE ON audit_log FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END;

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
BEFORE DELETE ON audit_log FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END;

-- ============================================================
-- 26. TRIGGER: CROSS-REFERENCE VALIDATION
-- ============================================================

CREATE TRIGGER IF NOT EXISTS trg_mortgage_validate_insert
BEFORE INSERT ON wealth_positions FOR EACH ROW
WHEN NEW.mortgage_linked_property_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wealth_positions wp
        WHERE wp.id = NEW.mortgage_linked_property_id
          AND wp.client_id = NEW.client_id
          AND wp.position_type = 'Immobilien'
          AND wp.is_active = 1
          AND wp.deleted_at IS NULL
    ) THEN RAISE(ABORT, 'mortgage_linked_property_id muss auf eine aktive Immobilien-Position desselben Kunden zeigen') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_mortgage_validate_update
BEFORE UPDATE OF mortgage_linked_property_id, client_id ON wealth_positions FOR EACH ROW
WHEN NEW.mortgage_linked_property_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wealth_positions wp
        WHERE wp.id = NEW.mortgage_linked_property_id
          AND wp.client_id = NEW.client_id
          AND wp.position_type = 'Immobilien'
          AND wp.is_active = 1
          AND wp.deleted_at IS NULL
    ) THEN RAISE(ABORT, 'mortgage_linked_property_id muss auf eine aktive Immobilien-Position desselben Kunden zeigen') END;
END;

-- ============================================================
-- 27. TRIGGER: AUTO updated_at
-- ============================================================

CREATE TRIGGER IF NOT EXISTS trg_users_uat AFTER UPDATE ON users FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE users SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_clients_uat AFTER UPDATE ON clients FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE clients SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_mandates_uat AFTER UPDATE ON mandates FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE mandates SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_client_knowledge_uat AFTER UPDATE ON client_knowledge FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE client_knowledge SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_risk_assessments_uat AFTER UPDATE ON risk_assessments FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE risk_assessments SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_investment_preferences_uat AFTER UPDATE ON investment_preferences FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE investment_preferences SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_investment_restrictions_uat AFTER UPDATE ON investment_restrictions FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE investment_restrictions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_asset_class_focus_uat AFTER UPDATE ON asset_class_focus FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE asset_class_focus SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_wealth_positions_uat AFTER UPDATE ON wealth_positions FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE wealth_positions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_cashflows_uat AFTER UPDATE ON cashflows FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE cashflows SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_goals_uat AFTER UPDATE ON goals FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE goals SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_planning_assumptions_uat AFTER UPDATE ON planning_assumptions FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE planning_assumptions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_optimizer_policies_uat AFTER UPDATE ON optimizer_policies FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE optimizer_policies SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_target_allocations_uat AFTER UPDATE ON target_allocations FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE target_allocations SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_capital_market_assumptions_uat AFTER UPDATE ON capital_market_assumptions FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE capital_market_assumptions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_building_blocks_uat AFTER UPDATE ON building_blocks FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE building_blocks SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_house_matrix_uat AFTER UPDATE ON house_matrix FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE house_matrix SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_review_triggers_uat AFTER UPDATE ON review_triggers FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE review_triggers SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_advisory_log_uat AFTER UPDATE ON advisory_log FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE advisory_log SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_contract_documents_uat AFTER UPDATE ON contract_documents FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE contract_documents SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_suitability_checks_uat AFTER UPDATE ON suitability_checks FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE suitability_checks SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_coi_disclosures_uat AFTER UPDATE ON conflict_of_interest_disclosures FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE conflict_of_interest_disclosures SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_adviser_reg_uat AFTER UPDATE ON adviser_registrations FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE adviser_registrations SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_products_uat AFTER UPDATE ON products FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE products SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_product_suitability_uat AFTER UPDATE ON product_suitability FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE product_suitability SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_runs_uat AFTER UPDATE ON recommendation_runs FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE recommendation_runs SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_recommendation_positions_uat AFTER UPDATE ON recommendation_positions FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at BEGIN UPDATE recommendation_positions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = NEW.id; END;

-- ============================================================
-- PRICE HISTORY (added for automated market data refresh)
-- ============================================================
CREATE TABLE IF NOT EXISTS price_history (
    id              TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL REFERENCES products(id) ON UPDATE CASCADE ON DELETE CASCADE,
    price_date      TEXT NOT NULL,
    price_rappen    INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'CHF',
    source          TEXT NOT NULL DEFAULT 'yfinance',
    fetched_at      TEXT NOT NULL,
    UNIQUE(product_id, price_date, source)
);

CREATE INDEX IF NOT EXISTS ix_price_history_product_date
    ON price_history(product_id, price_date);
