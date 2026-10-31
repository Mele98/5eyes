/**
 * ADVISORY-LOG-COST-RUN-BINDING (AUDIT-FIX 2026-10-31).
 *
 * Befund: der Editor schickte den gezeigten Kostenausweis-Lauf als
 * `cost_disclosure_snapshot_id` (+ `_currency`). `AdvisoryLogCreate` kennt
 * diese Felder nicht; Pydantic verwarf sie still. Ohne
 * `recommendation_run_id` rechnete das Backend den MANDATSWEITEN
 * Kostenausweis zum Speicherzeitpunkt statt des eingefrorenen Nachweises des
 * gezeigten Laufs (COST-EVIDENCE-001 / COST-CONTEXT-001b).
 *
 * Diese Tests rendern den echten Editor, stubben nur `fetch` (Netzgrenze)
 * und pruefen den echten POST-Body sowie die Fehleranzeige des
 * fail-closed-Pfads (409 COST_EVIDENCE_INVALID).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { AdvisoryLogEditor } from './AdvisoryLogEditor';
// Gespiegelter, ECHTER Editor-Body: der Backend-Test
// `test_cost_snapshot_frozen_binding.py::test_real_editor_json_body_*` schickt
// genau diese Datei durch das Schema (extra="forbid") und prueft die Bindung.
// Weicht der Editor-Payload ab, wird dieser Test rot.
import editorPayloadFixture from './__fixtures__/advisoryLogEditorCostPayload.json';

const RUN_ID = 'run-shown-in-editor-001';

type PostResponder = (body: Record<string, unknown>) => Response;

function stubFetch(postResponder: PostResponder) {
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes('/cost-disclosure/ex-ante')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            source_run_id: RUN_ID,
            currency: 'CHF',
            as_of: '2026-10-30',
            data_pending: false,
          }),
        } as Response);
      }
      const body = init?.body
        ? (JSON.parse(init.body as string) as Record<string, unknown>)
        : {};
      posts.push(body);
      return Promise.resolve(postResponder(body));
    }),
  );
  return posts;
}

async function fillAndSave({ tickCost }: { tickCost: boolean }) {
  render(<AdvisoryLogEditor open onClose={() => {}} mandateId="mandate-bind-001" />);
  if (tickCost) {
    // Snapshot-Referenz muss geladen sein, bevor gespeichert wird -- genau
    // der Zustand, in dem der Berater den Hinweis auf den Lauf gesehen hat.
    fireEvent.click(screen.getByRole('checkbox'));
    await screen.findByText(new RegExp(RUN_ID));
  }
  fireEvent.change(screen.getByPlaceholderText(/Detaillierte Dokumentation/), {
    target: { value: 'A'.repeat(40) },
  });
  fireEvent.click(screen.getAllByText('+ Eintrag hinzufügen')[0]);
  fireEvent.change(screen.getByPlaceholderText('z. B. Strategic Asset Allocation'), {
    target: { value: 'Kostenausweis' },
  });
  fireEvent.click(screen.getByText('Speichern'));
}

const created: PostResponder = (body) =>
  ({
    ok: true,
    status: 201,
    json: async () => ({ id: 'log-bind-001', ...body }),
  }) as Response;

describe('AdvisoryLogEditor: Kostenausweis an den gezeigten Lauf binden', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test('mit Kostenhaken: recommendation_run_id = source_run_id des gezeigten Snapshots, keine toten Felder', async () => {
    const posts = stubFetch(created);
    await fillAndSave({ tickCost: true });
    await waitFor(() => expect(posts).toHaveLength(1));
    const body = posts[0];
    expect(body.cost_disclosure_given).toBe(true);
    expect(body.recommendation_run_id).toBe(RUN_ID);
    expect(body).not.toHaveProperty('cost_disclosure_snapshot_id');
    expect(body).not.toHaveProperty('cost_disclosure_snapshot_currency');
  });

  test('ohne Kostenhaken: kein Lauf behauptet (Payload wie bisher)', async () => {
    const posts = stubFetch(created);
    await fillAndSave({ tickCost: false });
    await waitFor(() => expect(posts).toHaveLength(1));
    const body = posts[0];
    expect(body.cost_disclosure_given).toBe(false);
    expect(body).not.toHaveProperty('recommendation_run_id');
    expect(body).not.toHaveProperty('cost_disclosure_snapshot_id');
    expect(body).not.toHaveProperty('cost_disclosure_snapshot_currency');
  });

  test('409 COST_EVIDENCE_INVALID wird verstaendlich angezeigt, Editor bleibt offen', async () => {
    const onClose = vi.fn();
    const message =
      `Der eingefrorene Kostennachweis des Empfehlungslaufs ${RUN_ID} ist ungueltig ` +
      '(snapshot_hash_mismatch). Eine Kostenoffenlegung kann damit nicht belegt ' +
      'werden -- Strategie neu berechnen und finalisieren.';
    stubFetch(
      () =>
        ({
          ok: false,
          status: 409,
          json: async () => ({
            detail: {
              reason_code: 'COST_EVIDENCE_INVALID',
              evidence_error: 'snapshot_hash_mismatch',
              recommendation_run_id: RUN_ID,
              message,
            },
          }),
        }) as Response,
    );
    render(<AdvisoryLogEditor open onClose={onClose} mandateId="mandate-bind-001" />);
    fireEvent.click(screen.getByRole('checkbox'));
    await screen.findByText(new RegExp(RUN_ID));
    fireEvent.change(screen.getByPlaceholderText(/Detaillierte Dokumentation/), {
      target: { value: 'A'.repeat(40) },
    });
    fireEvent.click(screen.getAllByText('+ Eintrag hinzufügen')[0]);
    fireEvent.change(screen.getByPlaceholderText('z. B. Strategic Asset Allocation'), {
      target: { value: 'Kostenausweis' },
    });
    fireEvent.click(screen.getByText('Speichern'));

    const error = await screen.findByText(/Fehler beim Speichern:/);
    expect(error.textContent).toContain('Kostennachweis');
    expect(error.textContent).toContain('snapshot_hash_mismatch');
    expect(error.textContent).toContain('COST_EVIDENCE_INVALID');
    expect(error.textContent).not.toContain('[object Object]');
    expect(onClose).not.toHaveBeenCalled();
  });

  test('echter Editor-Body entspricht exakt der Backend-Fixture', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-30T09:15:00.000Z'));
    try {
      const posts = stubFetch(created);
      render(<AdvisoryLogEditor open onClose={() => {}} mandateId="mandate-bind-001" />);
      fireEvent.click(screen.getByRole('checkbox'));
      await screen.findByText(new RegExp(RUN_ID));
      fireEvent.change(screen.getByPlaceholderText(/Detaillierte Dokumentation/), {
        target: { value: editorPayloadFixture.description },
      });
      fireEvent.click(screen.getAllByText('+ Eintrag hinzufügen')[0]);
      fireEvent.change(screen.getByPlaceholderText('z. B. Strategic Asset Allocation'), {
        target: { value: 'Kostenausweis' },
      });
      fireEvent.click(screen.getByText('Speichern'));
      await waitFor(() => expect(posts).toHaveLength(1));
      expect(posts[0]).toEqual(editorPayloadFixture);
    } finally {
      vi.useRealTimers();
    }
  });
});
