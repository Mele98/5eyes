/**
 * Sprint U-P28 PR C: React-Hook für Berater-Overrides.
 *
 * Pattern wie `useAdvisoryReport`: idle → loading → (ready | error).
 * Bei mandateId-Wechsel automatisches Reload, vorheriger Request wird
 * abgebrochen.
 *
 * Plus eine `save(payload)`-Aktion, die PUT triggert und nach Erfolg
 * (a) den lokalen State updated und (b) optional einen Caller-Callback
 * für Refetch des Reports auslöst.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './client';
import {
  fetchReportNotes,
  putReportNotes,
  type ReportNotes,
  type ReportNotesUpdate,
} from './reportNotes';

export type NotesState = 'idle' | 'loading' | 'ready' | 'error';

export interface UseReportNotesResult {
  state: NotesState;
  data: ReportNotes | null;
  error: ApiError | null;
  reload: () => void;
  saving: boolean;
  saveError: ApiError | null;
  /**
   * Schreibt das Override per PUT. Nach Erfolg wird der lokale State
   * aktualisiert. Optional kann der Caller einen Callback übergeben,
   * der nach Erfolg ausgelöst wird (z. B. um den vollen Advisory-Report
   * neu zu laden, damit die geänderte Sektion sofort sichtbar wird).
   */
  save: (
    payload: ReportNotesUpdate,
    onSuccess?: (notes: ReportNotes) => void,
  ) => Promise<void>;
}

export function useReportNotes(
  mandateId: string | undefined,
): UseReportNotesResult {
  const [state, setState] = useState<NotesState>('idle');
  const [data, setData] = useState<ReportNotes | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [reloadCounter, setReloadCounter] = useState(0);

  const reload = useCallback(() => {
    setReloadCounter((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!mandateId) {
      setState('idle');
      setData(null);
      setError(null);
      return;
    }
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState('loading');
    setError(null);

    fetchReportNotes(mandateId, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setState('ready');
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err as ApiError);
        setState('error');
      });

    return () => controller.abort();
  }, [mandateId, reloadCounter]);

  const save = useCallback<UseReportNotesResult['save']>(
    async (payload, onSuccess) => {
      if (!mandateId) return;
      setSaving(true);
      setSaveError(null);
      try {
        const fresh = await putReportNotes(mandateId, payload);
        setData(fresh);
        onSuccess?.(fresh);
      } catch (err) {
        if (err instanceof ApiError) {
          setSaveError(err);
        } else {
          setSaveError(new ApiError(0, (err as Error).message, err));
        }
      } finally {
        setSaving(false);
      }
    },
    [mandateId],
  );

  return { state, data, error, reload, saving, saveError, save };
}
