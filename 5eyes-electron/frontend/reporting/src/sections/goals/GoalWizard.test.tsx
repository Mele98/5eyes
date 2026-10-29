/**
 * Tests für GoalWizard (Track #64) — insbesondere GOAL-3-Regression-Lock:
 * Beim Bearbeiten eines Ziels dürfen pension_pillar / weight_bps /
 * success_probability_min_x100 NICHT still auf null überschrieben werden.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GoalRecord } from '@/api/types';

vi.mock('@/api/goals', () => ({
  createGoal: vi.fn(),
  updateGoal: vi.fn(),
  fetchGoals: vi.fn(),
  deleteGoal: vi.fn(),
  calculateMaxPensionSpending: vi.fn(),
}));

import { createGoal, updateGoal } from '@/api/goals';
import { ApiError } from '@/api/client';
import { GoalWizard } from './GoalWizard';

const updateMock = vi.mocked(updateGoal);
const createMock = vi.mocked(createGoal);

function makeGoal(overrides: Partial<GoalRecord> = {}): GoalRecord {
  return {
    id: 'g1',
    mandate_id: 'm1',
    client_id: 'c1',
    goal_family: 'Cashflow',
    goal_type: 'Pensionsausgabe',
    label: 'Pension',
    rank: 1,
    weight_bps: 3000,
    goal_scope: 'Beratungsvermögen',
    value_mode: 'nominal',
    target_amount_rappen: 4_000_000,
    target_wealth_rappen: null,
    target_return_bps: null,
    success_probability_min_x100: 8500,
    start_date: '2030-01-01',
    horizon_years: null,
    target_date: null,
    is_ongoing: 1,
    frequency: 'jaehrlich',
    hardness: 'Primär',
    probability_pct: 100,
    pension_pillar: 'BVG',
    linked_position_id: null,
    notes: null,
    is_active: 1,
    achievement_score: null,
    last_scored_at: null,
    created_at: '2026-06-22T00:00:00.000Z',
    updated_at: '2026-06-22T00:00:00.000Z',
    ...overrides,
  };
}

beforeEach(() => {
  updateMock.mockReset();
  createMock.mockReset();
  updateMock.mockResolvedValue(makeGoal());
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('GoalWizard — GOAL-3 Datenerhalt beim Edit', () => {
  it('erhält pension_pillar / weight_bps / success_probability_min_x100 beim Speichern', async () => {
    render(
      <GoalWizard
        open
        mandateId="m1"
        editing={makeGoal()}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    // Schritt 0 → 1 → 2
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    // updateGoal asynchron — auf den Call warten
    await vi.waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    const [, , payload] = updateMock.mock.calls[0];
    expect(payload.pension_pillar).toBe('BVG');
    expect(payload.weight_bps).toBe(3000);
    expect(payload.success_probability_min_x100).toBe(8500);
    expect(createMock).not.toHaveBeenCalled();
  });
});

describe('GoalWizard — GOAL-RECURRING-EDITOR-CONTRACT-001 Strom-Vertrag', () => {
  function openNewRecurring() {
    render(<GoalWizard open mandateId="m1" onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText('Zieltyp'), {
      target: { value: 'Wiederkehrende_Ausgabe' },
    });
    fireEvent.change(screen.getByLabelText('Bezeichnung'), { target: { value: 'Lebenshaltung' } });
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }));
  }

  function goToSaveAndSubmit() {
    fireEvent.click(screen.getByRole('button', { name: 'Weiter' }));
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
  }

  it('sendet Betrag, Startdatum und Enddatum eines endlichen Stroms (kein stiller Horizont)', async () => {
    createMock.mockResolvedValue(makeGoal());
    openNewRecurring();
    fireEvent.change(screen.getByLabelText(/^Betrag pro Zahlung/), { target: { value: '48000' } });
    fireEvent.change(screen.getByLabelText(/^Startdatum/), { target: { value: '2030-01-01' } });
    fireEvent.change(screen.getByLabelText(/^Enddatum/), { target: { value: '2040-01-01' } });
    goToSaveAndSubmit();

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const [, payload] = createMock.mock.calls[0];
    expect(payload.target_amount_rappen).toBe(4_800_000);
    expect(payload.start_date).toBe('2030-01-01');
    expect(payload.target_date).toBe('2040-01-01');
    expect(payload.is_ongoing).toBe(false);
    expect(payload.horizon_years).toBeNull();
  });

  it('laufend blendet das Enddatum aus und sendet target_date=null', async () => {
    createMock.mockResolvedValue(makeGoal());
    openNewRecurring();
    fireEvent.change(screen.getByLabelText(/^Betrag pro Zahlung/), { target: { value: '48000' } });
    fireEvent.change(screen.getByLabelText(/^Startdatum/), { target: { value: '2030-01-01' } });
    fireEvent.change(screen.getByLabelText(/^Enddatum/), { target: { value: '2040-01-01' } });
    fireEvent.click(screen.getByLabelText('laufend (ohne Enddatum)'));
    expect(screen.queryByLabelText(/^Enddatum/)).toBeNull();
    goToSaveAndSubmit();

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const [, payload] = createMock.mock.calls[0];
    expect(payload.is_ongoing).toBe(true);
    expect(payload.target_date).toBeNull();
  });

  it('blockiert fehlende Pflichtfelder und zeigt die Fehler am Feld in Schritt 2', () => {
    openNewRecurring();
    goToSaveAndSubmit();

    expect(createMock).not.toHaveBeenCalled();
    // Zurück auf dem Detail-Schritt, Fehler direkt an den Feldern.
    const amount = screen.getByLabelText(/^Betrag pro Zahlung/);
    const start = screen.getByLabelText(/^Startdatum/);
    const end = screen.getByLabelText(/^Enddatum/);
    expect(amount).toHaveAttribute('aria-invalid', 'true');
    expect(start).toHaveAttribute('aria-invalid', 'true');
    expect(end).toHaveAttribute('aria-invalid', 'true');
    expect(document.getElementById('goal-wizard-error-start_date')?.textContent).toMatch(/Startdatum/);
  });

  it('übernimmt einen 422-Fehler der API feldgenau (loc -> Feld) und springt zum Feld', async () => {
    createMock.mockRejectedValue(
      new ApiError(422, 'Startdatum ungültig', [
        { loc: ['body', 'start_date'], msg: 'Startdatum ungültig' },
      ]),
    );
    openNewRecurring();
    fireEvent.change(screen.getByLabelText(/^Betrag pro Zahlung/), { target: { value: '48000' } });
    fireEvent.change(screen.getByLabelText(/^Startdatum/), { target: { value: '2030-01-01' } });
    fireEvent.change(screen.getByLabelText(/^Enddatum/), { target: { value: '2040-01-01' } });
    goToSaveAndSubmit();

    await vi.waitFor(() =>
      expect(screen.getByLabelText(/^Startdatum/)).toHaveAttribute('aria-invalid', 'true'),
    );
    expect(document.getElementById('goal-wizard-error-start_date')?.textContent).toBe(
      'Startdatum ungültig',
    );
  });
});
