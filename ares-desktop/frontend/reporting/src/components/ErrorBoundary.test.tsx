import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { ErrorBoundary } from './ErrorBoundary';

/**
 * Sprint U-87 — Tests fuer Top-Level Error Boundary.
 *
 * Wir muessen console.error stummschalten waehrend die Tests laufen, weil
 * React in JSDOM standardmaessig komponentenweise Errors auf der Konsole
 * ausgibt was die Test-Ausgabe vermuellt. Wir bewahren aber den Aufruf-
 * Spy fuer Assertions.
 */

function Boom({ message = 'Bumm!' }: { message?: string }): JSX.Element {
  throw new Error(message);
}

function Ok(): JSX.Element {
  return <div data-testid="ok-child">Alles gut</div>;
}

describe('ErrorBoundary', () => {
  let consoleSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  it('rendert Children wenn kein Fehler', () => {
    render(
      <ErrorBoundary>
        <Ok />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('ok-child')).toBeInTheDocument();
  });

  it('zeigt Fallback-UI wenn Child wirft', () => {
    render(
      <ErrorBoundary>
        <Boom message="Render-Pannen" />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('reporting-error-boundary')).toBeInTheDocument();
    expect(screen.getByText('Anzeigefehler im Beratungsbericht')).toBeInTheDocument();
    expect(screen.getByText('Render-Pannen')).toBeInTheDocument();
  });

  it('Fallback-UI hat role=alert fuer a11y', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('Fallback-UI hat keine Garantie-Sprache', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    const txt = screen.getByTestId('reporting-error-boundary').textContent ?? '';
    const lower = txt.toLowerCase();
    expect(lower).not.toContain('garantiert');
    expect(lower).not.toContain('sicher,');
    expect(lower).not.toContain('risikofrei');
  });

  it('Fallback-UI hat keine Drittmarken', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    const txt = (screen.getByTestId('reporting-error-boundary').textContent ?? '').toLowerCase();
    for (const brand of ['ubs', 'pictet', 'julius', 'swiss life', '3eyes', 'ppc']) {
      expect(txt).not.toContain(brand);
    }
  });

  it('logged Fehler via console.error', () => {
    render(
      <ErrorBoundary>
        <Boom message="Logged-Pannen" />
      </ErrorBoundary>,
    );
    expect(consoleSpy).toHaveBeenCalled();
    const firstCallArgs = consoleSpy.mock.calls[0];
    expect(firstCallArgs[0]).toContain('ErrorBoundary');
  });

  it('ruft onError-Callback wenn gesetzt', () => {
    const onError = vi.fn();
    render(
      <ErrorBoundary onError={onError}>
        <Boom message="Callback-Pannen" />
      </ErrorBoundary>,
    );
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
    expect(onError.mock.calls[0][0].message).toBe('Callback-Pannen');
  });

  it('Custom-Fallback wird genutzt wenn uebergeben', () => {
    const customFallback = (err: Error): JSX.Element => (
      <div data-testid="custom-fallback">CUSTOM: {err.message}</div>
    );
    render(
      <ErrorBoundary fallback={customFallback}>
        <Boom message="Custom-Pannen" />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('custom-fallback')).toBeInTheDocument();
    expect(screen.getByText('CUSTOM: Custom-Pannen')).toBeInTheDocument();
    expect(screen.queryByTestId('reporting-error-boundary')).not.toBeInTheDocument();
  });

  it('Reset-Button setzt error-state zurueck', () => {
    let throwIt = true;
    function Maybe(): JSX.Element {
      if (throwIt) throw new Error('Erstmal kaputt');
      return <div data-testid="recovered">Wiederhergestellt</div>;
    }
    const { rerender } = render(
      <ErrorBoundary>
        <Maybe />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('reporting-error-boundary')).toBeInTheDocument();

    throwIt = false;
    fireEvent.click(screen.getByText('Erneut versuchen'));
    rerender(
      <ErrorBoundary>
        <Maybe />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('recovered')).toBeInTheDocument();
  });

  it('Reload-Button ist sichtbar', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Bericht neu laden')).toBeInTheDocument();
  });
});
