/**
 * CERT-COST-PUBLICATION-001 -- permanent repository reproducer.
 *
 * Source of truth: the Ares/Codex audit worktree
 * `C:\Users\Emanuele\Documents\ChatGPT\5eyes wird zu Ares\asset-allocation-stochastic-core`
 * (branch `codex/asset-allocation-stochastic-core`),
 * `docs/audits/2026-10-09-cost-publication-channel-delivery-artifact-certification-spec.md`,
 * finding `COST-DELIVERY-EVIDENCE-001` (one of its 2 assertions -- the
 * sibling monolith-side assertion, the unawaited download that logs
 * "ausgehaendigt" before the PDF download settles, lives in
 * `5eyes-backend/tests/test_cert_cost_publication_001_reproducers.py`).
 *
 * Root cause, independently re-verified against this repo's actual
 * current `develop` HEAD (717ce3ab529d53c9fb355ee2b401932829ea0054):
 * `AdvisoryLogEditor.tsx:157-174` sends whatever boolean the advisor's
 * checkbox happens to hold as `cost_disclosure_given` and hardcodes
 * `conflict_disclosure_ids: []` -- there is no snapshot id, document id,
 * byte hash, presentation/transport event, or conflict-evidence reference
 * anywhere in the payload (`:320-333` is the free checkbox itself,
 * `"Ex-ante Kosten dem Kunden kommuniziert (FIDLEG-Pflicht)."`). An
 * advisor can tick this box and save with zero proof a cost-disclosure
 * artifact was ever rendered, let alone shown to the client.
 *
 * This test renders the REAL `AdvisoryLogEditor` component, fills in the
 * minimum required fields, ticks the real checkbox, clicks the real save
 * button, and inspects the REAL JSON body `createAdvisoryLog()`
 * (`api/advisoryLog.ts`) sends via `fetch`. `fetch` itself is stubbed
 * (the network boundary, not the logic under test) -- the same technique
 * `api/client.test.ts` already uses for `resolveAuthToken()`.
 *
 * Do not close this by only adding an optional `cost_disclosure_artifact_id`
 * field while keeping the checkbox freely editable (spec Section 15:
 * "Checkbox behalten und lediglich Snapshot-ID optional hinzufuegen" is
 * explicitly an insufficient fix). Closure requires the checkbox removed
 * and delivery/presentation evidence read-only from server-verified events
 * (spec Section 6.3 / 8.2).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { AdvisoryLogEditor } from './AdvisoryLogEditor';

describe('COST-DELIVERY-EVIDENCE-001: React self-attestation without artifact evidence', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test.fails(
    'ticking the cost-disclosure checkbox and saving sends no artifact/snapshot evidence at all',
    async () => {
      let capturedBody: Record<string, unknown> | null = null;
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
          capturedBody = init?.body
            ? (JSON.parse(init.body as string) as Record<string, unknown>)
            : null;
          return Promise.resolve({
            ok: true,
            status: 201,
            json: async () => ({ id: 'log-evidence-001', ...capturedBody }),
          } as Response);
        }),
      );

      render(
        <AdvisoryLogEditor open onClose={() => {}} mandateId="mandate-evidence-001" />,
      );

      // Minimum fields required by the real client-side validate().
      fireEvent.change(
        screen.getByPlaceholderText(/Detaillierte Dokumentation/),
        { target: { value: 'A'.repeat(40) } },
      );
      // "Themen" is the first DynList on the form (required, min 1 entry).
      fireEvent.click(screen.getAllByText('+ Eintrag hinzufügen')[0]);
      fireEvent.change(
        screen.getByPlaceholderText('z. B. Strategic Asset Allocation'),
        { target: { value: 'Kostenausweis' } },
      );

      // The exact self-attestation this finding documents: a free
      // checkbox, with no artifact/snapshot/hash reference anywhere on
      // the form.
      fireEvent.click(screen.getByRole('checkbox'));
      fireEvent.click(screen.getByText('Speichern'));

      await waitFor(() => expect(capturedBody).not.toBeNull());

      const body = capturedBody as Record<string, unknown>;
      expect(body.cost_disclosure_given).toBe(true); // sanity: the free flag really is set

      // Soll: a cost-disclosure attestation must reference a real,
      // server-verified artifact (snapshot/document/byte-hash) -- never a
      // bare boolean the advisor can tick freely with no evidence behind
      // it.
      const hasArtifactEvidence = Object.keys(body).some((key) =>
        /artifact|snapshot|document_id|byte_sha256/i.test(key),
      );
      expect(hasArtifactEvidence).toBe(true);
    },
  );
});
