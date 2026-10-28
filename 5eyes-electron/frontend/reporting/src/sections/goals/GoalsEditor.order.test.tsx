/**
 * GOAL-ORDER-REACT-001: Reihenfolge der Ziele im React-Editor.
 *
 * Rang = kanonische Prioritaet, Haerte ein getrenntes Feld (#753). Umsortiert
 * wird per Hoch/Runter-Buttons (barrierefrei, ohne Drag-and-drop) und atomar
 * ueber PUT /mandates/{id}/goals/order gespeichert (expected_goal_ids = zuletzt
 * gesehene Folge). Bei 409 wird die alte Folge sichtbar zurueckgesetzt und neu
 * geladen.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { GoalRecord } from '@/api/types';

vi.mock('@/api/goals', () => ({
  fetchGoals: vi.fn(),
  deleteGoal: vi.fn(),
  createGoal: vi.fn(),
  updateGoal: vi.fn(),
  reorderGoals: vi.fn(),
  calculateMaxPensionSpending: vi.fn(),
}));

import { fetchGoals, reorderGoals, updateGoal } from '@/api/goals';
import { GoalsEditor } from './GoalsEditor';

const fetchGoalsMock = vi.mocked(fetchGoals);
const reorderMock = vi.mocked(reorderGoals);

function goal(id: string, label: string, rank: number, hardness: string): GoalRecord {
  return {
    id,
    mandate_id: 'm1',
    client_id: 'c1',
    goal_family: 'Vermögen',
    goal_type: 'Vermögensziel',
    label,
    rank,
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
    hardness,
    probability_pct: 100,
    pension_pillar: null,
    linked_position_id: null,
    notes: null,
    is_active: 1,
    achievement_score: null,
    last_scored_at: null,
    created_at: '2026-10-01T00:00:00.000Z',
    updated_at: '2026-10-01T00:00:00.000Z',
  };
}

const A = goal('g1', 'Haus', 1, 'Opportunistisch');
const B = goal('g2', 'Vorsorge', 2, 'Hart');
const C = goal('g3', 'Reise', 3, 'Primär');

function rowLabels(): string[] {
  const table = screen.getByRole('table', { name: 'Ziele des Mandats' });
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[1].textContent ?? '');
}

beforeEach(() => {
  fetchGoalsMock.mockReset();
  reorderMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('GoalsEditor: Reihenfolge', () => {
  it('bietet beschriftete Hoch/Runter-Buttons, an den Enden deaktiviert', async () => {
    fetchGoalsMock.mockResolvedValue([A, B, C]);
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText('Haus');
    expect(screen.getByRole('button', { name: 'Ziel „Haus" nach oben verschieben' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Ziel „Haus" nach unten verschieben' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Ziel „Reise" nach unten verschieben' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Ziel „Reise" nach oben verschieben' })).toBeEnabled();
  });

  it('speichert die neue Folge atomar ueber den Reihenfolge-Endpunkt (Haerte bleibt getrennt)', async () => {
    fetchGoalsMock.mockResolvedValue([A, B, C]);
    reorderMock.mockResolvedValue([
      { ...B, rank: 1 },
      { ...A, rank: 2 },
      C,
    ]);
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText('Haus');
    fireEvent.click(screen.getByRole('button', { name: 'Ziel „Vorsorge" nach oben verschieben' }));
    await waitFor(() => expect(reorderMock).toHaveBeenCalledTimes(1));
    expect(reorderMock).toHaveBeenCalledWith('m1', ['g2', 'g1', 'g3'], ['g1', 'g2', 'g3']);
    expect(vi.mocked(updateGoal)).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Reihenfolge gespeichert.'));
    expect(rowLabels()).toEqual(['Vorsorge', 'Haus', 'Reise']);
    // Rang neu vom Server, Haerte unveraendert je Ziel.
    const firstRow = within(screen.getByRole('table', { name: 'Ziele des Mandats' })).getAllByRole('row')[1];
    const cells = within(firstRow).getAllByRole('cell');
    expect(cells[0]).toHaveTextContent('1');
    expect(cells[4]).toHaveTextContent('Hart');
  });

  it('setzt bei 409 sichtbar zurueck und laedt neu', async () => {
    fetchGoalsMock.mockResolvedValueOnce([A, B, C]);
    // Serverstand nach parallelem Edit:
    fetchGoalsMock.mockResolvedValueOnce([
      { ...C, rank: 1 },
      { ...A, rank: 2 },
      { ...B, rank: 3 },
    ]);
    let rejectReorder: (err: unknown) => void = () => {};
    reorderMock.mockReturnValue(
      new Promise((_, reject) => {
        rejectReorder = reject;
      }),
    );
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText('Haus');
    fireEvent.click(screen.getByRole('button', { name: 'Ziel „Haus" nach unten verschieben' }));
    // Optimistisch umsortiert, waehrend gespeichert wird keine weitere Verschiebung.
    expect(rowLabels()).toEqual(['Vorsorge', 'Haus', 'Reise']);
    expect(screen.getByRole('button', { name: 'Ziel „Reise" nach oben verschieben' })).toBeDisabled();
    rejectReorder(
      new ApiError(409, 'Die Ziel-Reihenfolge wurde inzwischen geaendert. Bitte neu laden und erneut sortieren.'),
    );
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/inzwischen geaendert/);
    expect(alert).toHaveTextContent(/zurückgesetzt/);
    await waitFor(() => expect(fetchGoalsMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(rowLabels()).toEqual(['Reise', 'Haus', 'Vorsorge']));
    expect(screen.getByRole('alert')).toHaveTextContent(/inzwischen geaendert/);
  });

  it('setzt bei anderen Fehlern zurueck, ohne neu zu laden', async () => {
    fetchGoalsMock.mockResolvedValue([A, B, C]);
    reorderMock.mockRejectedValue(new ApiError(422, 'Ungueltige Reihenfolge.'));
    render(<GoalsEditor mandateId="m1" />);
    await screen.findByText('Haus');
    fireEvent.click(screen.getByRole('button', { name: 'Ziel „Reise" nach oben verschieben' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ungueltige Reihenfolge.');
    expect(rowLabels()).toEqual(['Haus', 'Vorsorge', 'Reise']);
    expect(fetchGoalsMock).toHaveBeenCalledTimes(1);
  });
});
