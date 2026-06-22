/**
 * Goal-Wizard (Track #64) — Anlegen/Bearbeiten eines Ziels.
 *
 * 3 Schritte: (0) Zieltyp + Bezeichnung + Rang/Härte, (1) typabhängige
 * Felder (Feld-Isolation gemäss Backend), (2) Wahrscheinlichkeit + Notizen.
 * Vor dem Speichern validiert `validateGoalForm` clientseitig dieselbe
 * Feld-Isolation, die das Backend erzwingt.
 *
 * Als Drawer umgesetzt (role="dialog"/aria-modal, Esc schliesst) — Muster
 * analog components/SectionEditWrapper.tsx.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { createGoal, updateGoal } from '@/api/goals';
import {
  buildGoalPayload,
  goalTypeKey,
  validateGoalForm,
  type GoalFormInput,
} from '@/lib/goalForm';
import type {
  GoalHardnessInput,
  GoalRecord,
  GoalScope,
  GoalType,
  GoalValueMode,
  PensionPillar,
} from '@/api/types';
import { MaxPensionSpendingPanel } from './MaxPensionSpendingPanel';

const GOAL_TYPES: GoalType[] = [
  'Kapitalerhalt',
  'Vermögensziel',
  'Einmalige_Ausgabe',
  'Wiederkehrende_Ausgabe',
  'Pensionsausgabe',
  'Renditeziel',
  'Maximierung',
];

const HARDNESS_OPTIONS: GoalHardnessInput[] = ['Hart', 'Primär', 'Opportunistisch'];

interface WizardState {
  goal_type: GoalType;
  label: string;
  rank: number;
  hardness: GoalHardnessInput;
  goal_scope: GoalScope;
  value_mode: GoalValueMode;
  amountChf: string;
  wealthChf: string;
  returnPct: string;
  frequency: string;
  targetDate: string;
  horizonYears: string;
  probabilityPct: string;
  notes: string;
  // GOAL-3 Fix: beim Bearbeiten erhalten (sonst still auf null überschrieben).
  pensionPillar: '' | PensionPillar;
  weightBps: string;
  successProbX100: string;
}

function emptyState(): WizardState {
  return {
    goal_type: 'Vermögensziel',
    label: '',
    rank: 1,
    hardness: 'Primär',
    goal_scope: 'Beratungsvermögen',
    value_mode: 'nominal',
    amountChf: '',
    wealthChf: '',
    returnPct: '',
    frequency: 'jaehrlich',
    targetDate: '',
    horizonYears: '',
    probabilityPct: '100',
    notes: '',
    pensionPillar: '',
    weightBps: '',
    successProbX100: '',
  };
}

function stateFromRecord(rec: GoalRecord): WizardState {
  const base = emptyState();
  return {
    ...base,
    goal_type: (rec.goal_type as GoalType) ?? base.goal_type,
    label: rec.label ?? '',
    rank: rec.rank ?? 1,
    hardness: (HARDNESS_OPTIONS.includes(rec.hardness as GoalHardnessInput)
      ? (rec.hardness as GoalHardnessInput)
      : 'Primär'),
    goal_scope: (rec.goal_scope as GoalScope) ?? base.goal_scope,
    value_mode: (rec.value_mode as GoalValueMode) ?? base.value_mode,
    amountChf: rec.target_amount_rappen != null ? String(rec.target_amount_rappen / 100) : '',
    wealthChf: rec.target_wealth_rappen != null ? String(rec.target_wealth_rappen / 100) : '',
    returnPct: rec.target_return_bps != null ? String(rec.target_return_bps / 100) : '',
    frequency: rec.frequency ?? base.frequency,
    targetDate: rec.target_date ?? '',
    horizonYears: rec.horizon_years != null ? String(rec.horizon_years) : '',
    probabilityPct: rec.probability_pct != null ? String(rec.probability_pct) : '100',
    notes: rec.notes ?? '',
    pensionPillar: (rec.pension_pillar as PensionPillar) ?? '',
    weightBps: rec.weight_bps != null ? String(rec.weight_bps) : '',
    successProbX100: rec.success_probability_min_x100 != null ? String(rec.success_probability_min_x100) : '',
  };
}

function toFormInput(s: WizardState): GoalFormInput {
  const key = goalTypeKey(s.goal_type);
  const num = (v: string): number | null => (v.trim() === '' ? null : Number(v));
  const chfToRappen = (v: string): number | null => {
    const n = num(v);
    return n == null ? null : Math.round(n * 100);
  };
  const pctToBps = (v: string): number | null => {
    const n = num(v);
    return n == null ? null : Math.round(n * 100);
  };
  return {
    goal_type: s.goal_type,
    label: s.label,
    rank: s.rank,
    hardness: s.hardness,
    goal_scope: s.goal_scope,
    value_mode: s.value_mode,
    target_amount_rappen: key === 'einmalige_ausgabe' ? chfToRappen(s.amountChf) : null,
    target_wealth_rappen:
      key === 'kapitalerhalt' || key === 'vermoegensziel' ? chfToRappen(s.wealthChf) : null,
    target_return_bps: key === 'renditeziel' ? pctToBps(s.returnPct) : null,
    frequency:
      key === 'wiederkehrende_ausgabe' || key === 'pensionsausgabe' ? s.frequency : null,
    target_date: s.targetDate || null,
    horizon_years: num(s.horizonYears),
    probability_pct: s.probabilityPct.trim() === '' ? 100 : Number(s.probabilityPct),
    notes: s.notes || null,
    // GOAL-3 Fix: erhalten statt nullen (Wizard schickte sie vorher gar nicht).
    pension_pillar: s.pensionPillar || null,
    weight_bps: num(s.weightBps),
    success_probability_min_x100: num(s.successProbX100),
  };
}

interface GoalWizardProps {
  open: boolean;
  mandateId: string;
  editing?: GoalRecord | null;
  onClose: () => void;
  onSaved: () => void;
}

export function GoalWizard({ open, mandateId, editing, onClose, onSaved }: GoalWizardProps) {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>(emptyState);
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setState(editing ? stateFromRecord(editing) : emptyState());
      setStep(0);
      setErrors([]);
      setSaving(false);
    }
  }, [open, editing]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const set = <K extends keyof WizardState>(field: K, value: WizardState[K]): void => {
    setState((prev) => ({ ...prev, [field]: value }));
  };

  // Beim Typwechsel die typ-spezifischen Felder zurücksetzen (Feld-Isolation).
  const onTypeChange = (goal_type: GoalType): void => {
    setState((prev) => ({
      ...prev,
      goal_type,
      amountChf: '',
      wealthChf: '',
      returnPct: '',
      targetDate: '',
      horizonYears: '',
    }));
    setErrors([]);
  };

  const typeKey = goalTypeKey(state.goal_type);
  const isWealth = typeKey === 'kapitalerhalt' || typeKey === 'vermoegensziel';
  const isCashflowRecurring = typeKey === 'wiederkehrende_ausgabe' || typeKey === 'pensionsausgabe';

  async function onSubmit() {
    const input = toFormInput(state);
    const validationErrors = validateGoalForm(input);
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setErrors([]);
    try {
      const payload = buildGoalPayload(input);
      if (editing) {
        await updateGoal(mandateId, editing.id, payload);
      } else {
        await createGoal(mandateId, payload);
      }
      onSaved();
      onClose();
    } catch (err) {
      setErrors([err instanceof ApiError ? err.detail : 'Speichern fehlgeschlagen.']);
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    'mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink';

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={editing ? 'Ziel bearbeiten' : 'Neues Ziel anlegen'}
        className="h-full w-full max-w-lg overflow-y-auto bg-canvas-panel p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-h2 text-ink">
            {editing ? 'Ziel bearbeiten' : 'Neues Ziel'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Schliessen"
            className="rounded px-2 py-1 text-ink-muted hover:text-ink"
          >
            ✕
          </button>
        </div>

        <ol className="mt-block flex gap-2 text-micro uppercase tracking-widest text-ink-subtle">
          <li aria-current={step === 0 ? 'step' : undefined}>1 Zieltyp</li>
          <li aria-current={step === 1 ? 'step' : undefined}>2 Details</li>
          <li aria-current={step === 2 ? 'step' : undefined}>3 Feinheiten</li>
        </ol>

        <div className="mt-block space-y-3">
          {step === 0 && (
            <>
              <label className="block text-caption text-ink-muted">
                Zieltyp
                <select
                  value={state.goal_type}
                  onChange={(e) => onTypeChange(e.target.value as GoalType)}
                  className={inputClass}
                >
                  {GOAL_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-caption text-ink-muted">
                Bezeichnung
                <input
                  type="text"
                  value={state.label}
                  onChange={(e) => set('label', e.target.value)}
                  className={inputClass}
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-caption text-ink-muted">
                  Rang
                  <input
                    type="number"
                    min={1}
                    value={state.rank}
                    onChange={(e) => set('rank', Number(e.target.value))}
                    className={inputClass}
                  />
                </label>
                <label className="block text-caption text-ink-muted">
                  Härtegrad
                  <select
                    value={state.hardness}
                    onChange={(e) => set('hardness', e.target.value as GoalHardnessInput)}
                    className={inputClass}
                  >
                    {HARDNESS_OPTIONS.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </>
          )}

          {step === 1 && (
            <>
              {typeKey === 'renditeziel' && (
                <label className="block text-caption text-ink-muted">
                  Renditeziel (% p.a.)
                  <input
                    type="number"
                    step="0.1"
                    value={state.returnPct}
                    onChange={(e) => set('returnPct', e.target.value)}
                    className={inputClass}
                  />
                </label>
              )}
              {typeKey === 'einmalige_ausgabe' && (
                <label className="block text-caption text-ink-muted">
                  Zielbetrag (CHF)
                  <input
                    type="number"
                    value={state.amountChf}
                    onChange={(e) => set('amountChf', e.target.value)}
                    className={inputClass}
                  />
                </label>
              )}
              {isWealth && (
                <>
                  <label className="block text-caption text-ink-muted">
                    Zielvermögen (CHF)
                    <input
                      type="number"
                      value={state.wealthChf}
                      onChange={(e) => set('wealthChf', e.target.value)}
                      className={inputClass}
                    />
                  </label>
                  <label className="block text-caption text-ink-muted">
                    Wertbasis
                    <select
                      value={state.value_mode}
                      onChange={(e) => set('value_mode', e.target.value as GoalValueMode)}
                      className={inputClass}
                    >
                      <option value="nominal">nominal</option>
                      <option value="real">real</option>
                    </select>
                  </label>
                </>
              )}
              {isCashflowRecurring && (
                <label className="block text-caption text-ink-muted">
                  Häufigkeit
                  <select
                    value={state.frequency}
                    onChange={(e) => set('frequency', e.target.value)}
                    className={inputClass}
                  >
                    <option value="jaehrlich">jährlich</option>
                    <option value="monatlich">monatlich</option>
                  </select>
                </label>
              )}
              {(typeKey === 'einmalige_ausgabe' || isWealth) && (
                <div className="grid grid-cols-2 gap-3">
                  <label className="block text-caption text-ink-muted">
                    Zieldatum
                    <input
                      type="date"
                      value={state.targetDate}
                      onChange={(e) => set('targetDate', e.target.value)}
                      className={inputClass}
                    />
                  </label>
                  <label className="block text-caption text-ink-muted">
                    oder Horizont (Jahre)
                    <input
                      type="number"
                      min={1}
                      value={state.horizonYears}
                      onChange={(e) => set('horizonYears', e.target.value)}
                      className={inputClass}
                    />
                  </label>
                </div>
              )}
              {typeKey === 'pensionsausgabe' && (
                <>
                  <label className="block text-caption text-ink-muted">
                    Vorsorge-Säule
                    <select
                      value={state.pensionPillar}
                      onChange={(e) => set('pensionPillar', e.target.value as '' | PensionPillar)}
                      className={inputClass}
                    >
                      <option value="">—</option>
                      <option value="AHV">AHV</option>
                      <option value="BVG">BVG</option>
                      <option value="3a">3a</option>
                      <option value="1e">1e</option>
                      <option value="FZG">FZG</option>
                    </select>
                  </label>
                  <MaxPensionSpendingPanel mandateId={mandateId} />
                </>
              )}
              {typeKey === 'maximierung' && (
                <p className="text-caption text-ink-muted">
                  Maximierungsziele benötigen keine weiteren Felder.
                </p>
              )}
            </>
          )}

          {step === 2 && (
            <>
              <label className="block text-caption text-ink-muted">
                Eintrittswahrscheinlichkeit (%)
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={state.probabilityPct}
                  onChange={(e) => set('probabilityPct', e.target.value)}
                  className={inputClass}
                />
              </label>
              <label className="block text-caption text-ink-muted">
                Notizen
                <textarea
                  value={state.notes}
                  onChange={(e) => set('notes', e.target.value)}
                  rows={3}
                  className={inputClass}
                />
              </label>
            </>
          )}
        </div>

        {errors.length > 0 && (
          <ul
            role="alert"
            aria-live="assertive"
            className="mt-block list-disc rounded border border-status-rot/40 bg-status-rot/5 p-3 pl-8 text-caption text-status-rot"
          >
            {errors.map((msg, idx) => (
              <li key={idx}>{msg}</li>
            ))}
          </ul>
        )}

        <div className="mt-block flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="rounded border border-rule px-4 py-2 text-caption text-ink disabled:opacity-40"
          >
            Zurück
          </button>
          {step < 2 ? (
            <button
              type="button"
              onClick={() => setStep((s) => Math.min(2, s + 1))}
              className="rounded bg-ink px-4 py-2 text-caption text-paper"
            >
              Weiter
            </button>
          ) : (
            <button
              type="button"
              onClick={onSubmit}
              disabled={saving}
              className="rounded bg-ink px-4 py-2 text-caption text-paper disabled:opacity-50"
            >
              {saving ? 'Speichere…' : 'Speichern'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
