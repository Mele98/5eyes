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
    target_amount_rappen: null,
    target_wealth_rappen: null,
    target_return_bps: null,
    success_probability_min_x100: 8500,
    start_date: null,
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
