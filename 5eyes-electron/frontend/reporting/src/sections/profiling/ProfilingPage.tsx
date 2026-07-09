import { useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import {
  createRiskAssessment,
  fetchCurrentRiskAssessment,
} from '@/api/profiling';
import type {
  InvestmentHorizonLabel,
  RiskAssessment,
  RiskAssessmentAnswerCreate,
  RiskAssessmentCreate,
} from '@/api/types';
import { RiskSummary } from './RiskSummary';

type Option = {
  label: string;
  value: number;
};

type HorizonOption = {
  label: InvestmentHorizonLabel;
  years: number;
};

const INCOME_OPTIONS: Option[] = [
  { label: 'Einkommen deckt Verpflichtungen knapp', value: 1 },
  { label: 'Einkommen deckt Verpflichtungen solide', value: 2 },
  { label: 'Einkommen bietet deutlichen Spielraum', value: 3 },
  { label: 'Einkommen bietet sehr hohen Spielraum', value: 4 },
];

const OBLIGATION_OPTIONS: Option[] = [
  { label: 'Verpflichtungen sind hoch', value: 1 },
  { label: 'Verpflichtungen sind tragbar', value: 2 },
  { label: 'Verpflichtungen sind tief', value: 3 },
  { label: 'Verpflichtungen sind sehr tief', value: 4 },
];

const SAVINGS_OPTIONS: Option[] = [
  { label: 'Kaum freie Sparquote', value: 0 },
  { label: 'Moderate Sparquote', value: 3 },
  { label: 'Solide Sparquote', value: 6 },
  { label: 'Hohe Sparquote', value: 9 },
  { label: 'Sehr hohe Sparquote', value: 12 },
];

const WEALTH_OPTIONS: Option[] = [
  { label: 'Tiefe freie Vermoegensbasis', value: 0 },
  { label: 'Moderate freie Vermoegensbasis', value: 3 },
  { label: 'Solide freie Vermoegensbasis', value: 6 },
  { label: 'Hohe freie Vermoegensbasis', value: 9 },
  { label: 'Sehr hohe freie Vermoegensbasis', value: 12 },
];

const HORIZON_OPTIONS: HorizonOption[] = [
  { label: 'Bis 2 Jahre', years: 1 },
  { label: '2 bis 3 Jahre', years: 2 },
  { label: '4 bis 5 Jahre', years: 4 },
  { label: '6 bis 7 Jahre', years: 6 },
  { label: '8 bis 11 Jahre', years: 9 },
  { label: 'Mehr als 12 Jahre', years: 15 },
];

const WILLINGNESS_OPTIONS: Option[] = [
  { label: 'Kapital erhalten', value: 1 },
  { label: 'Kaufkraft erhalten', value: 2 },
  { label: 'Vermoegen ausgewogen vermehren', value: 3 },
  { label: 'Wachstum priorisieren', value: 4 },
];

const RISK_PREFERENCE_OPTIONS: Option[] = [
  { label: 'Risiko moeglichst vermeiden', value: 1 },
  { label: 'Geringe Wertschwankungen akzeptieren', value: 2 },
  { label: 'Rendite und Risiko ausbalancieren', value: 3 },
  { label: 'Hoehere Schwankungen fuer Rendite akzeptieren', value: 4 },
];

const RISK_BEHAVIOR_OPTIONS: Option[] = [
  { label: 'Bei Verlust verkaufen', value: 1 },
  { label: 'Bei Schwankung vorsichtig bleiben', value: 2 },
  { label: 'Verluste zeitweise aushalten', value: 3 },
  { label: 'Starke Schwankung langfristig tragen', value: 4 },
];

type ProfilingFormState = {
  q_income_points: number;
  q_obligations_points: number;
  q_savings_points: number;
  q_wealth_points: number;
  investment_horizon_label: InvestmentHorizonLabel;
  investment_horizon_years: number;
  q_investment_goal_points: number;
  q_risk_preference_points: number;
  q_risk_behavior_points: number;
};

const DEFAULT_STATE: ProfilingFormState = {
  q_income_points: 2,
  q_obligations_points: 2,
  q_savings_points: 6,
  q_wealth_points: 6,
  investment_horizon_label: '6 bis 7 Jahre' as InvestmentHorizonLabel,
  investment_horizon_years: 6,
  q_investment_goal_points: 3,
  q_risk_preference_points: 3,
  q_risk_behavior_points: 3,
};

function optionLabel(options: Option[], value: number): string {
  return options.find((option) => option.value === value)?.label ?? options[0].label;
}

// Vollstaendiges Label->Jahre-Mapping, gespiegelt aus dem Backend
// (services/risk_scoring.HORIZON_YEARS). Das Dropdown (HORIZON_OPTIONS) zeigt nur
// die 6 kanonischen Kategorien, aber ein bereits gespeichertes Legacy-Label MUSS
// beim Speichern die korrekten Jahre behalten — sonst wurde investment_horizon_years
// beim reinen Re-Save still auf 6 defaultet (Verstuemmelung der Risikofaehigkeit).
const HORIZON_YEARS_BY_LABEL: Record<InvestmentHorizonLabel, number> = {
  'Bis 2 Jahre': 1,
  '2 bis 3 Jahre': 2,
  '4 bis 5 Jahre': 4,
  '6 bis 7 Jahre': 6,
  '8 bis 11 Jahre': 9,
  'Mehr als 12 Jahre': 15,
  '0 bis 4 Jahre': 2,
  '5 bis 7 Jahre': 6,
  '12 Jahre und mehr': 15,
  '1 bis 3 Jahre': 2,
  '3 bis 5 Jahre': 4,
  '5 bis 10 Jahre': 6,
  '10 Jahre und mehr': 15,
};

function horizonYears(label: InvestmentHorizonLabel): number {
  return HORIZON_YEARS_BY_LABEL[label] ?? 6;
}

// Ein geladenes (evtl. Legacy-)Label auf die passende kanonische Dropdown-Kategorie
// abbilden (ueber die Jahre-Aequivalenz), damit das <select> die korrekte Auswahl
// zeigt statt optisch auf die erste Option zu fallen. Jahre bleiben identisch.
function canonicalHorizonLabel(label: InvestmentHorizonLabel): InvestmentHorizonLabel {
  const years = HORIZON_YEARS_BY_LABEL[label] ?? 6;
  return HORIZON_OPTIONS.find((option) => option.years === years)?.label ?? label;
}

export function buildRiskAssessmentPayload(
  state: ProfilingFormState,
): RiskAssessmentCreate {
  const horizonLabel = state.investment_horizon_label;
  const answers: RiskAssessmentAnswerCreate[] = [
    {
      question_number: 1,
      question_section: 'Kenntnisse',
      answer_label: 'Finanzdienstleistungen: dokumentiert im Beratungsgespraech',
      answer_points: 0,
    },
    {
      question_number: 2,
      question_section: 'Kenntnisse',
      answer_label: 'Finanzinstrumente: dokumentiert im Beratungsgespraech',
      answer_points: 0,
    },
    {
      question_number: 3,
      question_section: 'Risikofaehigkeit',
      answer_label: `${optionLabel(INCOME_OPTIONS, state.q_income_points)} in CHF`,
      answer_points: state.q_income_points,
    },
    {
      question_number: 4,
      question_section: 'Risikofaehigkeit',
      answer_label: 'Herkunft: Einkommen und Vermoegen plausibilisiert',
      answer_points: 0,
    },
    {
      question_number: 5,
      question_section: 'Risikofaehigkeit',
      answer_label: `${optionLabel(OBLIGATION_OPTIONS, state.q_obligations_points)} in CHF`,
      answer_points: state.q_obligations_points,
    },
    {
      question_number: 6,
      question_section: 'Risikofaehigkeit',
      answer_label: `${optionLabel(SAVINGS_OPTIONS, state.q_savings_points)} in CHF`,
      answer_points: state.q_savings_points,
    },
    {
      question_number: 7,
      question_section: 'Risikofaehigkeit',
      answer_label: `${optionLabel(WEALTH_OPTIONS, state.q_wealth_points)} in % des Vermoegens`,
      answer_points: state.q_wealth_points,
    },
    {
      question_number: 8,
      question_section: 'Risikofaehigkeit',
      answer_label: `Matrix Anlagehorizont: ${horizonLabel}`,
      answer_points: 0,
    },
    {
      question_number: 9,
      question_section: 'Risikobereitschaft',
      answer_label: optionLabel(WILLINGNESS_OPTIONS, state.q_investment_goal_points),
      answer_points: state.q_investment_goal_points,
    },
    {
      question_number: 10,
      question_section: 'Risikobereitschaft',
      answer_label: optionLabel(RISK_PREFERENCE_OPTIONS, state.q_risk_preference_points),
      answer_points: state.q_risk_preference_points,
    },
    {
      question_number: 11,
      question_section: 'Risikobereitschaft',
      answer_label: optionLabel(RISK_BEHAVIOR_OPTIONS, state.q_risk_behavior_points),
      answer_points: state.q_risk_behavior_points,
    },
  ];

  return {
    ...state,
    investment_horizon_years: horizonYears(horizonLabel),
    answers,
    knowledge_services_json: JSON.stringify({
      source: 'react_profiling_editor',
      status: 'documented',
    }),
    knowledge_instruments_json: JSON.stringify({
      source: 'react_profiling_editor',
      status: 'documented',
    }),
    income_sources_json: JSON.stringify(['Beratungsgespraech']),
  };
}

export function ProfilingPage() {
  const { mandateId } = useParams<{ mandateId: string }>();
  const [assessment, setAssessment] = useState<RiskAssessment | null>(null);
  const [form, setForm] = useState(DEFAULT_STATE);
  const [status, setStatus] = useState('Bereit.');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!mandateId) return;
    let cancelled = false;
    // #306-Review #2 (Mandanten-Trennung): den Editor beim Mandatswechsel SOFORT
    // leeren, bevor die neuen Daten (oder der 404-Leerzustand) stehen. Sonst blieben
    // Profil + Antworten des VORIGEN Mandats sichtbar und koennten faelschlich unter
    // dem neuen Mandat gespeichert werden.
    setAssessment(null);
    setForm(DEFAULT_STATE);
    setError(null);
    fetchCurrentRiskAssessment(mandateId)
      .then((data) => {
        if (!cancelled) {
          setAssessment(data);
          setForm({
            q_income_points: data.q_income_points,
            q_obligations_points: data.q_obligations_points,
            q_savings_points: data.q_savings_points,
            q_wealth_points: data.q_wealth_points,
            // #306-Review #1: Legacy-Label auf die kanonische Dropdown-Kategorie
            // normalisieren (gleiche Jahre), damit das <select> die korrekte Auswahl
            // zeigt statt optisch auf die erste Option zu fallen.
            investment_horizon_label: canonicalHorizonLabel(
              data.investment_horizon_label as InvestmentHorizonLabel,
            ),
            investment_horizon_years: data.investment_horizon_years,
            q_investment_goal_points: data.q_investment_goal_points,
            q_risk_preference_points: data.q_risk_preference_points,
            q_risk_behavior_points: data.q_risk_behavior_points,
          });
          setStatus('Aktuelles Risikoprofil geladen.');
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const maybeApiError = err as { status?: number; message?: string };
          setStatus('Neues Risikoprofil vorbereiten.');
          if (maybeApiError.status && maybeApiError.status !== 404) {
            setError(maybeApiError.message ?? 'Risikoprofil konnte nicht geladen werden.');
          }
        }
      });
    return () => {
      cancelled = true;
    };
  }, [mandateId]);

  const payload = useMemo(() => buildRiskAssessmentPayload(form), [form]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mandateId) {
      setError('Mandat fehlt in der URL.');
      return;
    }
    setIsSaving(true);
    setError(null);
    setStatus('Risikoprofil wird gespeichert.');
    try {
      const saved = await createRiskAssessment(mandateId, payload);
      setAssessment(saved);
      setStatus('Risikoprofil gespeichert.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Speichern fehlgeschlagen.');
      setStatus('Speichern fehlgeschlagen.');
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <main className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Risikoprofil-Editor
      </p>
      <h1 className="mt-block font-serif text-h1 text-ink">
        Risikoprofil erfassen
      </h1>
      <p className="mt-3 max-w-prose text-body text-ink-muted">
        Dokumentation der Risikofaehigkeit und Risikobereitschaft fuer das Mandat.
      </p>

      <div className="mt-section grid gap-section lg:grid-cols-[minmax(0,1fr)_20rem]">
        <form onSubmit={handleSubmit} className="space-y-section">
          <QuestionBlock title="Risikofaehigkeit">
            <SelectField
              id="q-income"
              label="Einkommenssituation"
              value={form.q_income_points}
              options={INCOME_OPTIONS}
              onChange={(value) => setForm((prev) => ({ ...prev, q_income_points: value }))}
            />
            <SelectField
              id="q-obligations"
              label="Verpflichtungen"
              value={form.q_obligations_points}
              options={OBLIGATION_OPTIONS}
              onChange={(value) => setForm((prev) => ({ ...prev, q_obligations_points: value }))}
            />
            <SelectField
              id="q-savings"
              label="Sparquote"
              value={form.q_savings_points}
              options={SAVINGS_OPTIONS}
              onChange={(value) => setForm((prev) => ({ ...prev, q_savings_points: value }))}
            />
            <SelectField
              id="q-wealth"
              label="Freie Vermoegensbasis"
              value={form.q_wealth_points}
              options={WEALTH_OPTIONS}
              onChange={(value) => setForm((prev) => ({ ...prev, q_wealth_points: value }))}
            />
            <label className="block">
              <span className="text-caption font-semibold text-ink">
                Anlagehorizont
              </span>
              <select
                className="mt-2 w-full border border-rule bg-canvas px-3 py-2 text-body text-ink"
                value={form.investment_horizon_label}
                onChange={(event) => {
                  const label = event.target.value as InvestmentHorizonLabel;
                  setForm((prev) => ({
                    ...prev,
                    investment_horizon_label: label,
                    investment_horizon_years: horizonYears(label),
                  }));
                }}
              >
                {HORIZON_OPTIONS.map((option) => (
                  <option key={option.label} value={option.label}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </QuestionBlock>

          <QuestionBlock title="Risikobereitschaft">
            <SelectField
              id="q-goal"
              label="Anlageziel"
              value={form.q_investment_goal_points}
              options={WILLINGNESS_OPTIONS}
              onChange={(value) => setForm((prev) => ({ ...prev, q_investment_goal_points: value }))}
            />
            <SelectField
              id="q-preference"
              label="Umgang mit Risiko"
              value={form.q_risk_preference_points}
              options={RISK_PREFERENCE_OPTIONS}
              onChange={(value) => setForm((prev) => ({ ...prev, q_risk_preference_points: value }))}
            />
            <SelectField
              id="q-behavior"
              label="Verhalten bei Verlusten"
              value={form.q_risk_behavior_points}
              options={RISK_BEHAVIOR_OPTIONS}
              onChange={(value) => setForm((prev) => ({ ...prev, q_risk_behavior_points: value }))}
            />
          </QuestionBlock>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={isSaving}
              className="border border-accent bg-accent px-5 py-2 text-caption font-semibold text-paper disabled:opacity-60"
            >
              {isSaving ? 'Speichern...' : 'Risikoprofil speichern'}
            </button>
            <p
              role="status"
              aria-live="polite"
              className="text-caption text-ink-muted"
            >
              {status}
            </p>
          </div>
          {error ? (
            <div
              role="alert"
              aria-live="assertive"
              className="border-l-4 border-status-rot bg-canvas-subtle px-4 py-3 text-caption text-ink"
            >
              {error}
            </div>
          ) : null}
        </form>

        <aside className="space-y-block">
          <RiskSummary assessment={assessment} />
          <section className="border border-rule bg-canvas-subtle p-5">
            <p className="text-micro uppercase tracking-widest text-ink-subtle">
              Methodik
            </p>
            <p className="mt-2 text-caption text-ink-muted">
              Fuer die Strategie gilt der konservativere Wert aus
              Risikofaehigkeit und Risikobereitschaft. Bei Override gilt
              weiterhin der tiefere Wert.
            </p>
          </section>
        </aside>
      </div>
    </main>
  );
}

function QuestionBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <fieldset className="border border-rule bg-canvas-panel p-5">
      <legend className="px-1 font-serif text-h2 text-ink">{title}</legend>
      <div className="mt-4 grid gap-4 md:grid-cols-2">{children}</div>
    </fieldset>
  );
}

function SelectField({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  options: Option[];
  onChange: (value: number) => void;
}) {
  return (
    <label htmlFor={id} className="block">
      <span className="text-caption font-semibold text-ink">{label}</span>
      <select
        id={id}
        className="mt-2 w-full border border-rule bg-canvas px-3 py-2 text-body text-ink"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {options.map((option) => (
          <option key={`${id}-${option.value}`} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
