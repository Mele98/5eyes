/**
 * Sprint U-51 (Roadmap-Punkt 51, 2026-06-04): Section-Navigation Helpers.
 *
 * Pure-Functions fuer Tastatur-Shortcut-Logik. React-frei und damit
 * direkt unit-testbar.
 */
import type { ReportSectionLink } from '@/components/Sidebar';


export function findSectionIndex(
  sections: readonly ReportSectionLink[],
  activeId: string,
): number {
  return sections.findIndex((s) => s.id === activeId);
}


export function getNextSection(
  sections: readonly ReportSectionLink[],
  activeId: string,
): ReportSectionLink | null {
  if (sections.length === 0) return null;
  const idx = findSectionIndex(sections, activeId);
  if (idx === -1) return sections[0];
  const next = idx + 1;
  return next < sections.length ? sections[next] : null;
}


export function getPrevSection(
  sections: readonly ReportSectionLink[],
  activeId: string,
): ReportSectionLink | null {
  if (sections.length === 0) return null;
  const idx = findSectionIndex(sections, activeId);
  if (idx === -1) return sections[0];
  const prev = idx - 1;
  return prev >= 0 ? sections[prev] : null;
}


export function getFirstSection(
  sections: readonly ReportSectionLink[],
): ReportSectionLink | null {
  return sections[0] ?? null;
}


export function getLastSection(
  sections: readonly ReportSectionLink[],
): ReportSectionLink | null {
  return sections[sections.length - 1] ?? null;
}


export function getSectionByNumber(
  sections: readonly ReportSectionLink[],
  nr: number,
): ReportSectionLink | null {
  return sections.find((s) => s.nr === nr) ?? null;
}


/**
 * Erzeugt absolute Route fuer eine Section innerhalb eines Mandate.
 * Mirror von Sidebar.tsx sectionHref damit der Hook unabhaengig
 * navigieren kann.
 */
export function sectionHref(
  mandateId: string,
  section: ReportSectionLink,
): string {
  const base = `/mandates/${mandateId}/report`;
  return section.path ? `${base}/${section.path}` : base;
}


// ---------------------------------------------------------------------------
// Shortcut-Definitionen (Single-Source-of-Truth)
// ---------------------------------------------------------------------------

export interface ShortcutDefinition {
  key: string;
  label: string;
  description: string;
}


export const KEYBOARD_SHORTCUTS: ReadonlyArray<ShortcutDefinition> = [
  { key: 'j', label: 'J', description: 'Naechste Sektion' },
  { key: 'k', label: 'K', description: 'Vorherige Sektion' },
  { key: 'g', label: 'G', description: 'Zum Titelblatt (erste Sektion)' },
  { key: 'G', label: 'Shift+G', description: 'Zur letzten Sektion' },
  { key: '?', label: '?', description: 'Tastatur-Shortcuts anzeigen' },
  { key: 'Escape', label: 'Esc', description: 'Overlay schliessen' },
];


/**
 * True wenn das Event in einem aktiven Input-Element passiert (Search-
 * Felder, Drawer-Textareas etc.). Shortcuts werden dann ignoriert
 * damit der User normal tippen kann.
 */
export function isTypingInInput(target: EventTarget | null): boolean {
  if (!target) return false;
  const el = target as Partial<HTMLElement> & { tagName?: string; isContentEditable?: boolean };
  const tag = el.tagName?.toUpperCase?.() ?? '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (el.isContentEditable) return true;
  return false;
}
