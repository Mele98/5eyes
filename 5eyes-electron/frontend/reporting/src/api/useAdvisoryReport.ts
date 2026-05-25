/**
 * React Hook für asynchrones Laden des Advisory-Reports.
 *
 * State-Machine: idle → loading → (ready | error). Bei mandateId-Wechsel
 * wird automatisch reloaded; vorheriger Request wird abgebrochen (AbortController).
 *
 * Verwendung:
 *   const { state, data, error, reload } = useAdvisoryReport(mandateId);
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAdvisoryReport, ApiError, SchemaError } from './client';
import type { AdvisoryReport } from './types';

export type ReportState = 'idle' | 'loading' | 'ready' | 'error';

export interface UseAdvisoryReportResult {
  state: ReportState;
  data: AdvisoryReport | null;
  error: ApiError | SchemaError | null;
  reload: () => void;
}

export function useAdvisoryReport(
  mandateId: string | undefined,
): UseAdvisoryReportResult {
  const [state, setState] = useState<ReportState>('idle');
  const [data, setData] = useState<AdvisoryReport | null>(null);
  const [error, setError] = useState<ApiError | SchemaError | null>(null);
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
    // Vorherigen Request abbrechen, falls mandateId noch lädt
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setState('loading');
    setError(null);

    fetchAdvisoryReport(mandateId, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setState('ready');
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        // AbortError nicht als „Fehler" anzeigen
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err as ApiError | SchemaError);
        setState('error');
      });

    return () => controller.abort();
  }, [mandateId, reloadCounter]);

  return { state, data, error, reload };
}
