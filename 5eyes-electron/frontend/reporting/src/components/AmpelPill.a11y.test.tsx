import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AmpelPill } from './AmpelPill';

/**
 * Sprint U-90 (2026-06-06): a11y-Tests fuer AmpelPill.
 *
 * Pruefen WCAG 1.4.1 'Use of Color':
 *   - Pill hat role='status' (verbalisierbar)
 *   - aria-label enthaelt Status-Beschreibung in Worten, nicht nur Farbe
 *   - 4 Status-Varianten (gruen/gelb/rot/nicht_beurteilbar) sind unterschiedlich
 *     verbal beschrieben
 */

describe('AmpelPill a11y (U-90)', () => {
  it('rendert role="status"', () => {
    const { container } = render(<AmpelPill status="gruen" />);
    const pill = container.querySelector('[role="status"]');
    expect(pill).not.toBeNull();
  });

  it('aria-label fuer gruen enthaelt Wort-Beschreibung', () => {
    render(<AmpelPill status="gruen" />);
    const pill = screen.getByRole('status');
    expect(pill.getAttribute('aria-label')).toMatch(/gruen/i);
    expect(pill.getAttribute('aria-label')).toMatch(/keine Massnahme/i);
  });

  it('aria-label fuer gelb verbalisert Achtung', () => {
    render(<AmpelPill status="gelb" />);
    const pill = screen.getByRole('status');
    expect(pill.getAttribute('aria-label')).toMatch(/gelb/i);
    expect(pill.getAttribute('aria-label')).toMatch(/Achtung|Pruefung/i);
  });

  it('aria-label fuer rot verbalisert Handlungsbedarf', () => {
    render(<AmpelPill status="rot" />);
    const pill = screen.getByRole('status');
    expect(pill.getAttribute('aria-label')).toMatch(/rot/i);
    expect(pill.getAttribute('aria-label')).toMatch(/Handlungsbedarf/i);
  });

  it('aria-label fuer nicht_beurteilbar verbalisert fehlende Daten', () => {
    render(<AmpelPill status="nicht_beurteilbar" />);
    const pill = screen.getByRole('status');
    expect(pill.getAttribute('aria-label')).toMatch(/nicht beurteilbar/i);
    expect(pill.getAttribute('aria-label')).toMatch(/Daten unvollstaendig/i);
  });

  it('unbekannter Status faellt auf "unbekannt" zurueck', () => {
    render(<AmpelPill status="bogus" />);
    const pill = screen.getByRole('status');
    expect(pill.getAttribute('aria-label')).toMatch(/unbekannt/i);
  });

  it('alle 4 Standard-Stati haben unterschiedliche aria-labels', () => {
    const labels = new Set<string>();
    for (const status of ['gruen', 'gelb', 'rot', 'nicht_beurteilbar'] as const) {
      const { container, unmount } = render(<AmpelPill status={status} />);
      const pill = container.querySelector('[role="status"]');
      labels.add(pill?.getAttribute('aria-label') || '');
      unmount();
    }
    expect(labels.size).toBe(4);
  });
});
