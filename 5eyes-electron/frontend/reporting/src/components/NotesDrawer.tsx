/**
 * Sprint U-P28 PR C: rechtsseitiger Edit-Drawer.
 *
 * Slide-in von rechts, max 28rem breit, mit Backdrop. ESC schließt.
 * Generisches Layout — die Sektion-spezifischen Forms werden als
 * `children` injiziert (siehe `SingleFieldForm` und `WeiteresVorgehenForm`).
 *
 * Visueller Stil: dezent, Editorial, gleiche Design-Tokens wie der Rest
 * der Sub-App (offwhite, navy, Petrol-Akzent).
 */
import { useEffect, type ReactNode } from 'react';

export interface NotesDrawerProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  /** Footer-Slot (Speichern/Abbrechen + Auto-Default-Reset). */
  footer: ReactNode;
}

export function NotesDrawer({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
}: NotesDrawerProps) {
  // ESC-Handler nur registrieren, solange der Drawer offen ist
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex"
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Drawer schliessen"
        onClick={onClose}
        className="flex-1 cursor-default bg-ink/30 backdrop-blur-sm transition-opacity"
      />
      {/* Panel */}
      <aside
        className="
          flex h-full w-full max-w-[28rem]
          flex-col bg-canvas-panel
          shadow-[-12px_0_32px_-16px_rgba(15,28,46,0.18)]
          border-l border-rule
        "
      >
        <header className="border-b border-rule px-page-x py-block">
          <p className="text-micro uppercase tracking-widest text-ink-subtle">
            Berater-Bearbeitung
          </p>
          <h2 className="mt-1 font-serif text-h3 text-ink">{title}</h2>
          {subtitle ? (
            <p className="mt-1 text-caption text-ink-muted">{subtitle}</p>
          ) : null}
        </header>
        <div className="flex-1 overflow-y-auto px-page-x py-block">
          {children}
        </div>
        <footer className="border-t border-rule bg-canvas-subtle px-page-x py-block">
          {footer}
        </footer>
      </aside>
    </div>
  );
}
