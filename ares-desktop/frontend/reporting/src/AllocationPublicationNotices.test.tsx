import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AllocationApprovalNotice, AllocationDraftNotice } from './App';

/**
 * CCX-P4: Berater-Ansicht des React-Berichts.
 * - Entwurfshinweis, solange die Soll-Allokation nicht (gueltig) publiziert ist.
 * - N-910-02: eine Einzelfreigabe ist sichtbar gekennzeichnet; Vier-Augen bleibt ruhig.
 */
describe('AllocationDraftNotice', () => {
  it('zeigt den Serverhinweis und sonst nichts', () => {
    const { rerender } = render(<AllocationDraftNotice notice="Entwurf" />);
    expect(screen.getByTestId('allocation-draft-notice').textContent).toBe('Entwurf');
    rerender(<AllocationDraftNotice notice={null} />);
    expect(screen.queryByTestId('allocation-draft-notice')).toBeNull();
  });
});

describe('AllocationApprovalNotice', () => {
  it('kennzeichnet eine publizierte Einzelfreigabe', () => {
    render(
      <AllocationApprovalNotice
        publication={{ status: 'PUBLISHED', approval_mode_label: 'Einzelfreigabe (eine berechtigte Person)' }}
      />,
    );
    expect(screen.getByTestId('allocation-approval-notice').textContent).toBe(
      'Publiziert · Einzelfreigabe (eine berechtigte Person)',
    );
  });

  it('bleibt bei Vier-Augen, Entwurf oder ungueltiger Publikation leer', () => {
    const { rerender } = render(
      <AllocationApprovalNotice publication={{ status: 'PUBLISHED', approval_mode_label: 'Vier-Augen-Freigabe' }} />,
    );
    expect(screen.queryByTestId('allocation-approval-notice')).toBeNull();
    rerender(
      <AllocationApprovalNotice
        publication={{ status: 'PUBLICATION_INVALID', approval_mode_label: 'Einzelfreigabe (eine berechtigte Person)' }}
      />,
    );
    expect(screen.queryByTestId('allocation-approval-notice')).toBeNull();
    rerender(<AllocationApprovalNotice publication={null} />);
    expect(screen.queryByTestId('allocation-approval-notice')).toBeNull();
  });
});
