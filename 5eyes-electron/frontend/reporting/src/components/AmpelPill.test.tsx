import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AmpelPill } from './AmpelPill';

describe('AmpelPill', () => {
  it('rendert "OK" für gruen', () => {
    render(<AmpelPill status="gruen" />);
    expect(screen.getByText('OK')).toBeInTheDocument();
  });

  it('rendert "Achtung" für gelb', () => {
    render(<AmpelPill status="gelb" />);
    expect(screen.getByText('Achtung')).toBeInTheDocument();
  });

  it('rendert "Handeln" für rot', () => {
    render(<AmpelPill status="rot" />);
    expect(screen.getByText('Handeln')).toBeInTheDocument();
  });

  it('rendert "Pendant" für nicht_beurteilbar', () => {
    render(<AmpelPill status="nicht_beurteilbar" />);
    expect(screen.getByText('Pendant')).toBeInTheDocument();
  });

  it('fällt für unbekannten Status auf Pendant zurück', () => {
    render(<AmpelPill status="abracadabra" />);
    expect(screen.getByText('Pendant')).toBeInTheDocument();
  });

  it('respektiert label-Override (für Goal-Status)', () => {
    render(<AmpelPill status="gruen" label="Erreichbar" />);
    expect(screen.getByText('Erreichbar')).toBeInTheDocument();
    expect(screen.queryByText('OK')).not.toBeInTheDocument();
  });

  it('matte Status-Farbtoken, keine signal-Klassen', () => {
    const { container } = render(<AmpelPill status="rot" />);
    const pill = container.firstChild as HTMLElement;
    // Klasse muss text-status-rot enthalten (matter Token), NICHT text-red-500
    expect(pill.className).toContain('text-status-rot');
    expect(pill.className).not.toContain('text-red-');
  });
});
