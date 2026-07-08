/**
 * Render-Tests für den GoalsEditor (Track #64).
 *
 * Mockt den API-Client und prüft Lade-/Empty-/Fehler-States, die Zielliste
 * und das Öffnen des Wizards.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { GoalRecord } from '@/api/types';

vi.mock('@/api/goals', () => ({
  fetchGoals: vi.fn(),
  deleteGoal: vi.fn(),
  createGoal: vi.fn(),
  updateGoal: vi.fn(),
  calculateMaxPensionSpending: vi.fn(),
}));

import { fetchGoals } from '@/api/goals';
import { GoalsEditor } from './GoalsEditor';

const fetchGoalsMock = vi.mocked(fetchGoals);

function makeGoal(overrides: Partial<GoalRecord> = {}): GoalRecord {
  return {
    id: 'g1',
    mandate_id: 'm1',
    client_id: 'c1',
    goal_family: 'Vermögen',
    goal_type: 'Vermögensziel',
    label: 'Altersvorsorge',
    rank: 1,
    weight_bps: null,
    goal_scope: 'Beratungsvermögen',
    value_mode: 'nominal',
    target_amount_rappen: null,
    target_wealth_rappen: 1_000_000_00,
    target_return_bps: null,
    success_probability_min_x100: null,
    start_date: null,
    horizon_years: 10,
    target_date: null,
    is_ongoing: 0,
    frequency: null,
    hardness: 'Hart',
    probability_pct: 100,
    pension_pillar: null,
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
  fetchGoalsMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('GoalsEditor', () => {
  it('zeigt einen Empty-State, wenn keine Ziele existieren', async () => {
    fetchGoalsMock.mockResolvedValue([]);
    render(<GoalsEditor mandateId="m1" />);
    expect(await screen.findByText(/Noch keine Ziele erfasst/)).toBeInTheDocument();
  });

  it('rendert die geladenen Ziele in einer Tabelle', async () => {
    fetchGoalsMock.mockResolvedValue([makeGoal({ label: 'Altersvorsorge' })]);
    render(<GoalsEditor mandateId="m1" />);
    expect(await screen.findByText('Altersvorsorge')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Ziele des Mandats' })).toBeInTheDocument();
  });

  it('zeigt eine Fehlermeldung bei ApiError', async () => {
    fetchGoalsMock.mockRejectedValue(new ApiError(500, 'Backend kaputt'));
    render(<GoalsEditor mandateId="m1" />);
    expect(await screen.findByText('Backend kaputt')).toBeInTheDocument();
  });

  it('öffnet den Wizard-Dialog über "Neues Ziel"', async () => {
    fetchGoalsMock.mockResolvedValue([]);
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText(/Noch keine Ziele erfasst/);
    fireEvent.click(screen.getByRole('button', { name: 'Neues Ziel' }));
    expect(screen.getByRole('dialog', { name: 'Neues Ziel anlegen' })).toBeInTheDocument();
  });
});
