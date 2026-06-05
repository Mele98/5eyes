import { Component, type ErrorInfo, type ReactNode } from 'react';

/**
 * Sprint U-87 (2026-06-05): Top-Level Error Boundary fuer die Reporting Sub-App.
 *
 * Ohne Boundary fuehrt ein unbehandelter Render-Error zu einer **weissen
 * Seite** mitten im Kundengespraech — der Berater sieht nichts, der Kunde
 * auch nichts. Mit Boundary sehen beide eine berater-taugliche
 * Fallback-UI mit Hinweis zum Vorgehen, und der Tech-Stack landet in
 * console.error fuer Post-Mortem.
 *
 * Branding-Disziplin: KEINE Drittmarken im Fallback-Text. KEINE
 * Garantie-Sprache. Sprache ist neutral-professionell.
 */

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** Optionaler Custom-Fallback (z.B. fuer Pro-Page-Boundaries). */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** Optionaler Hook fuer externes Logging (Telemetrie U-64). */
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Logging — bewusst console.error damit Electron-DevTools es zeigt.
    // Keine PII: nur Message + Component-Stack, keine Props/State-Dumps.
    // eslint-disable-next-line no-console
    console.error('[ReportingSubApp ErrorBoundary]', error.message, info.componentStack);
    this.props.onError?.(error, info);
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset);
    }

    return (
      <div
        role="alert"
        data-testid="reporting-error-boundary"
        className="flex min-h-screen items-center justify-center bg-paper p-8"
      >
        <div className="max-w-xl space-y-4 rounded border border-warning-border bg-warning-soft p-8 shadow-sm">
          <h1 className="font-serif text-2xl text-ink">
            Anzeigefehler im Beratungsbericht
          </h1>
          <p className="font-sans text-sm leading-relaxed text-ink-soft">
            Die Sub-Anwendung konnte diese Sektion nicht darstellen. Der Bericht
            ist intern weiterhin verfuegbar. Bitte den Berater informieren —
            der technische Hinweis ist im Entwickler-Log hinterlegt.
          </p>
          <div className="rounded bg-paper p-3 font-mono text-xs text-ink-soft">
            {error.message || 'Unbekannter Fehler'}
          </div>
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={this.reset}
              className="rounded bg-ink px-4 py-2 font-sans text-sm text-paper hover:bg-ink-soft"
            >
              Erneut versuchen
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded border border-ink-soft px-4 py-2 font-sans text-sm text-ink hover:bg-paper-soft"
            >
              Bericht neu laden
            </button>
          </div>
        </div>
      </div>
    );
  }
}
