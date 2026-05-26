/**
 * Sprint U-P28 PR C: floating "✎ Bearbeiten"-Button.
 *
 * Zeigt sich nur, wenn der eingeloggte User Editor-Rechte hat
 * (`useUserRole().canEdit`). Kunden / readonly sehen ihn nicht.
 *
 * Position: top-right der Sektion (`absolute`-positioniert; das Eltern-
 * `<section>` muss `relative` sein, damit der Button richtig sitzt).
 *
 * Pflegezustand: optional Prop `isEdited` (true wenn die Sektion einen
 * Berater-Override hat) ändert das Label auf „Bearbeitet" und zeigt
 * einen Petrol-Punkt — damit der Berater pro Sektion sieht, was schon
 * gepflegt ist.
 */
import { useUserRole } from '@/api/useUserRole';

export interface EditButtonProps {
  onClick: () => void;
  isEdited?: boolean;
  /** Aria-Label-Override für barrierearmes Lesen. */
  ariaLabel?: string;
}

export function EditButton({ onClick, isEdited, ariaLabel }: EditButtonProps) {
  const { canEdit, loading } = useUserRole();
  if (loading || !canEdit) return null;

  const label = isEdited ? 'Bearbeitet' : 'Bearbeiten';
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel ?? `Sektion ${label.toLowerCase()}`}
      className="
        absolute right-page-x top-block
        inline-flex items-center gap-2
        rounded-card border border-rule bg-canvas-panel
        px-3 py-1.5
        text-caption text-ink-muted
        shadow-sm transition
        hover:border-accent hover:text-accent
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
      "
    >
      <span aria-hidden="true">✎</span>
      <span>{label}</span>
      {isEdited ? (
        <span
          aria-hidden="true"
          className="ml-1 inline-block size-1.5 rounded-full bg-accent"
        />
      ) : null}
    </button>
  );
}
