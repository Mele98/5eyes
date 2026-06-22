/**
 * a11y-Tests für den GoalsEditor (Track #64), Muster App.a11y.test.tsx.
 *
 * Prüft: Status-Live-Region, benannte Tabelle, beschriftete Aktions-Buttons,
 * und dass der Wizard als modaler Dialog mit Label öffnet.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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

function makeGoal(): GoalRecord {
  return {
    id: 'g1',
    mandate_id: 'm1',
    client_id: 'c1',
    goal_family: 'Rendite',
    goal_type: 'Renditeziel',
    label: 'Wachstum',
    rank: 2,
    weight_bps: null,
    goal_scope: 'Beratungsvermögen',
    value_mode: 'nominal',
    target_amount_rappen: null,
    target_wealth_rappen: null,
    target_return_bps: 450,
    success_probability_min_x100: null,
    start_date: null,
    horizon_years: null,
    target_date: null,
    is_ongoing: 0,
    frequency: null,
    hardness: 'Primär',
    probability_pct: 100,
    pension_pillar: null,
    linked_position_id: null,
    notes: null,
    is_active: 1,
    achievement_score: null,
    last_scored_at: null,
    created_at: '2026-06-22T00:00:00.000Z',
    updated_at: '2026-06-22T00:00:00.000Z',
  };
}

beforeEach(() => {
  fetchGoalsMock.mockReset();
});

describe('GoalsEditor a11y', () => {
  it('hat eine Status-Live-Region (role=status)', async () => {
    fetchGoalsMock.mockResolvedValue([]);
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText(/Noch keine Ziele erfasst/);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('beschriftet die Tabelle und die Zeilen-Aktionen', async () => {
    fetchGoalsMock.mockResolvedValue([makeGoal()]);
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText('Wachstum');
    expect(screen.getByRole('table', { name: 'Ziele des Mandats' })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Ziel „Wachstum" bearbeiten' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Ziel „Wachstum" löschen' }),
    ).toBeInTheDocument();
  });

  it('öffnet den Wizard als modalen Dialog mit aria-label', async () => {
    fetchGoalsMock.mockResolvedValue([]);
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText(/Noch keine Ziele erfasst/);
    fireEvent.click(screen.getByRole('button', { name: 'Neues Ziel' }));
    const dialog = screen.getByRole('dialog', { name: 'Neues Ziel anlegen' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });
});
