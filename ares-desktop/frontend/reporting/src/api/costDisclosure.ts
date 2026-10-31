/**
 * CERT-COST-PUBLICATION-001 (COST-DELIVERY-EVIDENCE-001, 2026-10-09).
 *
 * Minimal read-only client for the EXISTING backend JSON preview endpoint
 * GET /mandates/{id}/cost-disclosure/ex-ante (the same single source of
 * truth the Standalone- and Advisory-PDF already use, see
 * services/cost_disclosure.py::build_cost_disclosure()).
 *
 * Used by AdvisoryLogEditor to attach a REAL, server-sourced cost-
 * disclosure snapshot reference to a cost-disclosure attestation instead
 * of sending a bare, evidence-free boolean (the self-attestation this
 * finding documents). This client never invents a snapshot id: if the
 * backend has no current snapshot (pending/unreachable), the reference
 * fields stay `null` -- an honest "no evidence" signal, not a fabricated
 * one.
 */
import { resolveAuthToken } from './client';

export interface CostDisclosureSnapshotRef {
  source_run_id: string | null;
  currency: string | null;
  as_of: string | null;
  data_pending: boolean;
}

/**
 * Best-effort fetch -- NEVER throws. A network/auth/schema failure yields
 * `null`, which callers must treat the same as "no snapshot available"
 * (fail-closed: no attestation evidence, not a fabricated one).
 */
export async function fetchCostDisclosureSnapshotRef(
  mandateId: string,
  options: { signal?: AbortSignal; baseUrl?: string } = {},
): Promise<CostDisclosureSnapshotRef | null> {
  const baseUrl = options.baseUrl ?? '';
  const token = await resolveAuthToken();
  try {
    const resp = await fetch(
      `${baseUrl}/mandates/${encodeURIComponent(mandateId)}/cost-disclosure/ex-ante`,
      {
        method: 'GET',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: options.signal,
      },
    );
    if (!resp.ok) return null;
    const body = (await resp.json()) as Partial<CostDisclosureSnapshotRef> | null;
    if (!body || typeof body !== 'object') return null;
    return {
      source_run_id: typeof body.source_run_id === 'string' ? body.source_run_id : null,
      currency: typeof body.currency === 'string' ? body.currency : null,
      as_of: typeof body.as_of === 'string' ? body.as_of : null,
      data_pending: Boolean(body.data_pending),
    };
  } catch {
    return null;
  }
}
