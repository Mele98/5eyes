import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AllocationApprovalNotice, AllocationDraftNotice, DecisionEnvelopeNotice } from './App';

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

describe('DecisionEnvelopeNotice', () => {
  it('P5b / N-925-04: Pruefnummer und Fassung nur fuer einen auslieferbaren Entscheid', () => {
    const { rerender } = render(
      <DecisionEnvelopeNotice reference={{ state: 'deliverable', pruefnummer: 'abcdef012345', fassung: 2 }} />,
    );
    expect(screen.getByTestId('decision-envelope-notice').textContent).toBe(
      'Beratungsentscheid · Prüfnummer abcdef012345 · Fassung 2',
    );
    rerender(<DecisionEnvelopeNotice reference={{ state: 'sealed_not_deliverable' }} />);
    expect(screen.getByTestId('decision-envelope-notice').textContent).toBe(
      'Beratungsentscheid versiegelt, derzeit nicht auslieferbar',
    );
    rerender(<DecisionEnvelopeNotice reference={{ state: 'none' }} />);
    expect(screen.queryByTestId('decision-envelope-notice')).toBeNull();
  });
});
