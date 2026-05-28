/**
 * Test-Fixtures für Vitest-Suite.
 *
 * Liefert minimale Aggregator-Payloads, die der Backend-Output entsprechen
 * (Schema v2). Spiegelt das Pendant `_make_minimal_payload` aus
 * `5eyes-backend/tests/test_advisory_report_pdf.py` — wenn das Backend-
 * Schema ändert, hier nachziehen.
 */
import type {
  AdvisoryReport,
  AssetAllocationData,
  AusgangslageData,
  BranchenData,
  BuildingBlocksData,
  CoverData,
  DisclaimerData,
  ErkenntnisseData,
  GoalBasedInvestingData,
  InhaltsverzeichnisData,
  PositionenData,
  PruefpunkteData,
  RisikoprofilierungData,
  RisikowaehrungenData,
  StatementPmData,
  WeiteresVorgehenData,
} from '@/api/types';

export function makeCover(): CoverData {
  return {
    title: 'Depotcheck',
    subtitle: 'Strategische Portfolioanalyse',
    client_name: 'Hans Muster',
    mandate_number: 'MX-FOUNDATION-01',
    report_date: '2026-05-27',
    advisor_name: 'Anna Beispiel',
  };
}

export function makeDisclaimer(): DisclaimerData {
  return {
    hinweise: [
      'Dieser Bericht dient ausschliesslich Beratungszwecken.',
      'Vergangene Performance ist kein Indikator fuer kuenftige Renditen.',
      'Monte-Carlo-Simulationen sind Modellrechnungen mit Modell-Risiken.',
    ],
  };
}

export function makeInhaltsverzeichnis(): InhaltsverzeichnisData {
  return {
    kapitel: [
      { nr: 1, title: 'Ausgangslage' },
      { nr: 2, title: 'Übersicht Ihrer Positionen' },
      { nr: 3, title: 'Was wir im Depotcheck prüfen' },
    ],
  };
}

export function makeAusgangslage(): AusgangslageData {
  return {
    client_info: {
      alter: 49,
      anlagehorizont_jahre: 16,
      risikoprofil: 'Defensiv',
      anlageziel: 'Frühpension mit 60',
      liquiditaetsbedarf_rappen: 6_600_000,
      steuerdomizil: 'CH',
      referenzwaehrung: 'CHF',
    },
    wealth_summary: {
      gesamtvermoegen_rappen: 250_000_000,
      beratungsvermoegen_rappen: 180_000_000,
      immobilien_rappen: 50_000_000,
      vorsorge_rappen: 20_000_000,
      kredite_rappen: 0,
      cashflows: [],
      ziele: [],
    },
    key_metrics: {
      risky_fraction_bps: 4250,
      zielerreichung_bps: 8500,
      exp_vol_bps: 1100,
      exp_return_bps: 380,
      max_drawdown_bps: 1620,
      var_95_bps: 980,
    },
  };
}

export function makePositionen(): PositionenData {
  return {
    groups: [
      {
        key: 'equities',
        label: 'Aktien',
        share_bps: 2500,
        total_rappen: 45_000_000,
        positions: [
          {
            isin: 'CH0244767585',
            product_name: 'Test-ETF SPI Schweiz',
            product_type: 'ETF',
            sub_asset_class: 'Aktien Schweiz',
            currency: 'CHF',
            market_value_rappen: 30_000_000,
            ter_bps: 10,
            provider: 'Anbieter A',
            share_bps: 1665,
          },
        ],
      },
    ],
    total_rappen: 45_000_000,
    has_recommendation_run: true,
    hinweis: 'Daten basieren auf der aktuellen Empfehlung.',
  };
}

export function makePruefpunkte(): PruefpunkteData {
  return {
    bloecke: [
      {
        key: 'diversifikation',
        title: 'Diversifikation',
        beschreibung: 'Streuung über Anlageklassen und Regionen.',
      },
      {
        key: 'waehrungsrisiken',
        title: 'Währungsrisiken',
        beschreibung: 'Anteil Fremdwährungen zur Referenzwährung.',
      },
    ],
  };
}

export function makeErkenntnisse(): ErkenntnisseData {
  return {
    checks: [
      {
        pruefpunkt: 'Diversifikation',
        bewertung: 'gruen',
        beurteilung: 'Portfolio ist breit gestreut.',
        handlungsempfehlung: 'Beibehalten.',
      },
      {
        pruefpunkt: 'Währungsrisiken',
        bewertung: 'gelb',
        beurteilung: 'CHF-Anteil bei 55 %.',
        handlungsempfehlung: 'Hedge prüfen.',
      },
      {
        pruefpunkt: 'Risikobudget',
        bewertung: 'rot',
        beurteilung: 'Über dem Cap.',
        handlungsempfehlung: 'Risiko reduzieren.',
      },
      {
        pruefpunkt: 'Liquidität',
        bewertung: 'nicht_beurteilbar',
        beurteilung: 'Daten unvollständig.',
        handlungsempfehlung: 'Cashflow-Erfassung nachpflegen.',
      },
    ],
  };
}

export function makeAssetAllocation(): AssetAllocationData {
  return {
    items: [
      {
        key: 'equities',
        label: 'Aktien',
        ist_bps: 2500,
        soll_bps: 3500,
        drift_bps: -1000,
        band_min_bps: 3000,
        band_max_bps: 4000,
        in_band: false,
      },
      {
        key: 'bonds',
        label: 'Obligationen',
        ist_bps: 6000,
        soll_bps: 5000,
        drift_bps: 1000,
        band_min_bps: 4000,
        band_max_bps: 6000,
        in_band: true,
      },
    ],
    ist_bps: {},
    soll_bps: {},
    drift_bps: {},
    ist_basiert_auf_soll: true,
    anmerkungen: 'Aktien-Anteil unter dem Toleranzband — Rebalancing prüfen.',
  };
}

export function makeRisikowaehrungen(): RisikowaehrungenData {
  return {
    items: [
      { label: 'CHF', ist_bps: 5500, soll_bps: 6000, drift_bps: -500 },
      { label: 'USD', ist_bps: 3000, soll_bps: 2500, drift_bps: 500 },
    ],
    ist_bps: {},
    soll_bps: {},
    drift_bps: {},
    ist_basiert_auf_soll: false,
    erklaerung: 'CHF-Anteil leicht unter SOLL — kein Handlungsbedarf.',
  };
}

export function makeBranchen(): BranchenData {
  return {
    items: [
      { label: 'Tech', ist_bps: 2500, soll_bps: 2000, drift_bps: 500 },
      { label: 'Health', ist_bps: 1500, soll_bps: 1800, drift_bps: -300 },
    ],
    ist_bps: {},
    soll_bps: {},
    drift_bps: {},
    anteil_aktien_bps: 2500,
    hinweis: 'Basis für die Sektor-Drift sind die Aktien-Positionen.',
    ist_basiert_auf_soll: false,
    analyse: 'Tech-Übergewicht — Konzentrationsrisiko prüfen.',
  };
}

export function makeGoals(): GoalBasedInvestingData {
  return {
    goals: [
      {
        goal_id: 'g1',
        label: 'Frühpension mit 60',
        goal_type: 'Pension',
        target_amount_rappen: 1_500_000_00,
        target_date: '2042-09-18',
        hardness: 'Primaer',
        probability_bps: 7800,
        status: 'erreichbar',
      },
      {
        goal_id: 'g2',
        label: 'Haus-Umbau',
        goal_type: 'Liquidität',
        target_amount_rappen: 250_000_00,
        target_date: '2030-01-01',
        hardness: 'Opportunistisch',
        probability_bps: 5500,
        status: 'knapp',
      },
    ],
    goal_achievement_score_bps: 7250,
    monte_carlo_paths: {
      data_pending: true,
      note: 'Pfade werden live berechnet.',
    },
  };
}

export function makeRisikoprofil(): RisikoprofilierungData {
  return {
    risky_fraction_bps: 4250,
    risk_capacity_score_x10: 68,
    risk_willingness_score_x10: 55,
    final_score_x10: 62,
    final_profile: 'Defensiv',
    is_overridden: true,
    override_reason: 'Kunde wünscht defensiveres Profil als Score impliziert.',
    questions: [
      { key: 'anlagehorizont', frage: 'Anlagehorizont', points: 8 },
      { key: 'risikopraeferenz', frage: 'Risikopräferenz', points: 5 },
    ],
  };
}

export function makeBuildingBlocks(): BuildingBlocksData {
  return {
    blocks: [
      {
        key: 'equities',
        label: 'Aktien',
        target_bps: 3500,
        band_min_bps: 3000,
        band_max_bps: 4000,
      },
      {
        key: 'bonds',
        label: 'Obligationen',
        target_bps: 5000,
        band_min_bps: 4000,
        band_max_bps: 6000,
      },
    ],
    constraints: [
      {
        key: 'max_risky_fraction',
        label: 'Maximale Risikoquote',
        value_bps: 4500,
        beschreibung: 'FINMA-Eignungsprüfung Obergrenze.',
      },
    ],
    methodologie: 'Institutionelle SAA-Logik mit Monte-Carlo-Überprüfung.',
  };
}

export function makeStatementPm(): StatementPmData {
  return {
    principles: [
      {
        key: 'langfristigkeit',
        title: 'Langfristigkeit',
        body: 'Strategische Allokation auf den Anlagehorizont.',
      },
      {
        key: 'diversifikation',
        title: 'Diversifikation',
        body: 'Streuung reduziert idiosynkratisches Risiko.',
      },
    ],
  };
}

export function makeWeiteresVorgehen(): WeiteresVorgehenData {
  return {
    block_optimierungen: 'Quartals-Review im September.',
    block_zielstrategie: 'Vorsorge-Aufbau bis 65.',
    offene_fragen: ['Pillar 3a-Limit erreicht?'],
    naechster_termin: '2026-08-15',
    todos: ['Vorsorgeauftrag aufsetzen'],
    dokumente: ['Identifikationspapier'],
  };
}

export function makeAdvisoryReport(): AdvisoryReport {
  return {
    schema_version: 2,
    mandate_id: 'test-mandate-id',
    generated_at: '2026-05-27T14:32:00.000Z',
    cover: makeCover(),
    disclaimer: makeDisclaimer(),
    inhaltsverzeichnis: makeInhaltsverzeichnis(),
    ausgangslage: makeAusgangslage(),
    positionen: makePositionen(),
    pruefpunkte: makePruefpunkte(),
    erkenntnisse: makeErkenntnisse(),
    asset_allocation: makeAssetAllocation(),
    risikowaehrungen: makeRisikowaehrungen(),
    branchen: makeBranchen(),
    goal_based_investing: makeGoals(),
    risikoprofilierung: makeRisikoprofil(),
    building_blocks: makeBuildingBlocks(),
    statement_pm: makeStatementPm(),
    weiteres_vorgehen: makeWeiteresVorgehen(),
  };
}
