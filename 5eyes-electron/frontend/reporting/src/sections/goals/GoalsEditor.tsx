/**
 * Goal-Editor-Container (Track #64).
 *
 * Lädt die Ziele eines Mandats (GET /mandates/{id}/goals, vom Backend nach
 * rank sortiert), rendert sie als Tabelle und erlaubt Anlegen/Bearbeiten/
 * Löschen über den GoalWizard. Nach jeder Mutation wird neu geladen.
 *
 * Eigener Lade-State (idle/loading/ready/error) statt useAdvisoryReport —
 * dies ist ein Editor-Workflow, kein Report-Read-Model.
 */
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { deleteGoal, fetchGoals } from '@/api/goals';
import type { GoalRecord } from '@/api/types';
import { GoalWizard } from './GoalWizard';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

function formatChf(rappen: number | null): string {
  if (rappen == null) return '—';
  return `CHF ${Math.round(rappen / 100).toLocaleString('de-CH')}`;
}

function goalTargetSummary(goal: GoalRecord): string {
  if (goal.target_amount_rappen != null) return formatChf(goal.target_amount_rappen);
  if (goal.target_wealth_rappen != null) return formatChf(goal.target_wealth_rappen);
  if (goal.target_return_bps != null) return `${(goal.target_return_bps / 100).toFixed(2)} %`;
  if (goal.frequency) return goal.frequency;
  return '—';
}

interface GoalsEditorProps {
  mandateId: string;
}

export function GoalsEditor({ mandateId }: GoalsEditorProps) {
  const [state, setState] = useState<LoadState>('idle');
  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [error, setError] = useState<string>('');
  const [statusMsg, setStatusMsg] = useState<string>('');
  // GOAL-9 Fix: Löschfehler unabhängig vom LoadState sichtbar machen.
  const [actionError, setActionError] = useState<string>('');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [editing, setEditing] = useState<GoalRecord | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState('loading');
      setError('');
      try {
        const data = await fetchGoals(mandateId, { signal });
        setGoals(data);
        setState('ready');
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.detail : 'Ziele konnten nicht geladen werden.');
        setState('error');
      }
    },
    [mandateId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function onDelete(goal: GoalRecord) {
    setStatusMsg('');
    setActionError('');
    try {
      await deleteGoal(mandateId, goal.id);
      setStatusMsg(`Ziel „${goal.label}" gelöscht.`);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.detail : 'Löschen fehlgeschlagen.');
    }
  }

  function openCreate() {
    setEditing(null);
    setWizardOpen(true);
  }

  function openEdit(goal: GoalRecord) {
    setEditing(goal);
    setWizardOpen(true);
  }

  return (
    <article className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y">
      <header className="flex items-center justify-between">
        <div>
          <p className="text-micro uppercase tracking-widest text-ink-subtle">Ziele</p>
          <h1 className="mt-block font-serif text-h1 text-ink">Ziel-Erfassung</h1>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="rounded bg-ink px-4 py-2 text-caption text-paper"
        >
          Neues Ziel
        </button>
      </header>

      <p role="status" aria-live="polite" className="mt-2 min-h-[1.25rem] text-caption text-ink-muted">
        {statusMsg}
      </p>
      {actionError && (
        <p role="alert" aria-live="assertive" className="mt-1 text-caption text-status-rot">
          {actionError}
        </p>
      )}

      {state === 'loading' || state === 'idle' ? (
        <p aria-busy="true" className="mt-block text-body text-ink-muted">
          Ziele werden geladen…
        </p>
      ) : state === 'error' ? (
        <p role="alert" aria-live="assertive" className="mt-block text-body text-status-rot">
          {error}
        </p>
      ) : goals.length === 0 ? (
        <p className="mt-block text-body text-ink-muted">
          Noch keine Ziele erfasst. Mit „Neues Ziel" das erste Ziel anlegen.
        </p>
      ) : (
        <table className="mt-block w-full border-collapse text-body" aria-label="Ziele des Mandats">
          <caption className="sr-only">Liste der erfassten Ziele, sortiert nach Rang</caption>
          <thead>
            <tr className="border-b border-rule text-left text-caption text-ink-subtle">
              <th scope="col" className="py-2">Rang</th>
              <th scope="col" className="py-2">Bezeichnung</th>
              <th scope="col" className="py-2">Typ</th>
              <th scope="col" className="py-2">Ziel</th>
              <th scope="col" className="py-2">Härte</th>
              <th scope="col" className="py-2">
                <span className="sr-only">Aktionen</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {goals.map((goal) => (
              <tr key={goal.id} className="border-b border-rule/50">
                <td className="py-2">{goal.rank}</td>
                <td className="py-2">{goal.label}</td>
                <td className="py-2">{goal.goal_type.replace(/_/g, ' ')}</td>
                <td className="py-2">{goalTargetSummary(goal)}</td>
                <td className="py-2">{goal.hardness}</td>
                <td className="py-2 text-right">
                  <button
                    type="button"
                    onClick={() => openEdit(goal)}
                    className="rounded border border-rule px-2 py-1 text-caption text-ink"
                    aria-label={`Ziel „${goal.label}" bearbeiten`}
                  >
                    Bearbeiten
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(goal)}
                    className="ml-2 rounded border border-rule px-2 py-1 text-caption text-status-rot"
                    aria-label={`Ziel „${goal.label}" löschen`}
                  >
                    Löschen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <GoalWizard
        open={wizardOpen}
        mandateId={mandateId}
        editing={editing}
        onClose={() => setWizardOpen(false)}
        onSaved={() => {
          setStatusMsg(editing ? 'Ziel aktualisiert.' : 'Ziel angelegt.');
          void load();
        }}
      />
    </article>
  );
}
