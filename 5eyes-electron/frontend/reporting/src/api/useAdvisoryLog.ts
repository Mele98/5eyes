/**
 * Sprint U-FINMA-2.4: React-Hook für AdvisoryLog-Aktionen.
 *
 * Wrappt die zwei Schreib-Operationen:
 * - autoCreate(): POST /from-report-generation → liefert pre-filled Entry
 * - create(payload): POST /advisory-log → manueller Eintrag
 *
 * Plus saving/saveError-State analog useReportNotes.
 */
import { useCallback, useState } from 'react';
import { ApiError } from './client';
import type { BeratungsprotokollEntry } from './types';
import {
  createAdvisoryLog,
  createAutoLog,
  type AdvisoryLogCreatePayload,
} from './advisoryLog';

export interface UseAdvisoryLogResult {
  saving: boolean;
  saveError: ApiError | null;
  /** Auto-Log via POST /from-report-generation. */
  autoCreate: (
    onSuccess?: (entry: BeratungsprotokollEntry) => void,
  ) => Promise<BeratungsprotokollEntry | null>;
  /** Manueller Eintrag via POST /advisory-log. */
  create: (
    payload: AdvisoryLogCreatePayload,
    onSuccess?: (entry: BeratungsprotokollEntry) => void,
  ) => Promise<BeratungsprotokollEntry | null>;
  reset: () => void;
}

export function useAdvisoryLog(
  mandateId: string | undefined,
): UseAdvisoryLogResult {
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);

  const reset = useCallback(() => {
    setSaveError(null);
  }, []);

  const wrap = useCallback(
    async (op: () => Promise<BeratungsprotokollEntry>) => {
      setSaving(true);
      setSaveError(null);
      try {
        return await op();
      } catch (err) {
        if (err instanceof ApiError) {
          setSaveError(err);
        } else {
          setSaveError(new ApiError(0, (err as Error).message, err));
        }
        return null;
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  const autoCreate = useCallback<UseAdvisoryLogResult['autoCreate']>(
    async (onSuccess) => {
      if (!mandateId) return null;
      const result = await wrap(() => createAutoLog(mandateId));
      if (result) onSuccess?.(result);
      return result;
    },
    [mandateId, wrap],
  );

  const create = useCallback<UseAdvisoryLogResult['create']>(
    async (payload, onSuccess) => {
      if (!mandateId) return null;
      const result = await wrap(() => createAdvisoryLog(mandateId, payload));
      if (result) onSuccess?.(result);
      return result;
    },
    [mandateId, wrap],
  );

  return { saving, saveError, autoCreate, create, reset };
}
