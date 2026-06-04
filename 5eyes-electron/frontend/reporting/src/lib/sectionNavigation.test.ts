/**
 * Sprint U-51 (Roadmap-Punkt 51, 2026-06-04): Section-Navigation Tests.
 */
import { describe, it, expect } from 'vitest';
import type { ReportSectionLink } from '@/components/Sidebar';
import {
  KEYBOARD_SHORTCUTS,
  findSectionIndex,
  getFirstSection,
  getLastSection,
  getNextSection,
  getPrevSection,
  getSectionByNumber,
  isTypingInInput,
  sectionHref,
} from './sectionNavigation';


const SECTIONS: ReportSectionLink[] = [
  { id: 'cover', nr: 1, title: 'Titelblatt', path: '' },
  { id: 'disclaimer', nr: 2, title: 'Disclaimer', path: 'disclaimer' },
  { id: 'toc', nr: 3, title: 'Inhalt', path: 'toc' },
];


// ---------------------------------------------------------------------------
// findSectionIndex
// ---------------------------------------------------------------------------

describe('U-51 findSectionIndex', () => {
  it('returns -1 for unknown id', () => {
    expect(findSectionIndex(SECTIONS, 'nonexistent')).toBe(-1);
  });

  it('returns correct index for known id', () => {
    expect(findSectionIndex(SECTIONS, 'cover')).toBe(0);
    expect(findSectionIndex(SECTIONS, 'disclaimer')).toBe(1);
    expect(findSectionIndex(SECTIONS, 'toc')).toBe(2);
  });
});


// ---------------------------------------------------------------------------
// getNextSection / getPrevSection
// ---------------------------------------------------------------------------

describe('U-51 getNextSection', () => {
  it('returns next section', () => {
    expect(getNextSection(SECTIONS, 'cover')?.id).toBe('disclaimer');
    expect(getNextSection(SECTIONS, 'disclaimer')?.id).toBe('toc');
  });

  it('returns null when at last section', () => {
    expect(getNextSection(SECTIONS, 'toc')).toBeNull();
  });

  it('returns first section for unknown active id', () => {
    expect(getNextSection(SECTIONS, 'unknown')?.id).toBe('cover');
  });

  it('returns null for empty sections', () => {
    expect(getNextSection([], 'cover')).toBeNull();
  });
});


describe('U-51 getPrevSection', () => {
  it('returns previous section', () => {
    expect(getPrevSection(SECTIONS, 'disclaimer')?.id).toBe('cover');
    expect(getPrevSection(SECTIONS, 'toc')?.id).toBe('disclaimer');
  });

  it('returns null when at first section', () => {
    expect(getPrevSection(SECTIONS, 'cover')).toBeNull();
  });

  it('returns first section for unknown active id', () => {
    expect(getPrevSection(SECTIONS, 'unknown')?.id).toBe('cover');
  });
});


// ---------------------------------------------------------------------------
// getFirstSection / getLastSection / getSectionByNumber
// ---------------------------------------------------------------------------

describe('U-51 getFirstSection / getLastSection', () => {
  it('returns first section', () => {
    expect(getFirstSection(SECTIONS)?.id).toBe('cover');
  });

  it('returns last section', () => {
    expect(getLastSection(SECTIONS)?.id).toBe('toc');
  });

  it('returns null for empty array', () => {
    expect(getFirstSection([])).toBeNull();
    expect(getLastSection([])).toBeNull();
  });
});


describe('U-51 getSectionByNumber', () => {
  it('returns section by nr', () => {
    expect(getSectionByNumber(SECTIONS, 1)?.id).toBe('cover');
    expect(getSectionByNumber(SECTIONS, 2)?.id).toBe('disclaimer');
  });

  it('returns null for nonexistent nr', () => {
    expect(getSectionByNumber(SECTIONS, 99)).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// sectionHref
// ---------------------------------------------------------------------------

describe('U-51 sectionHref', () => {
  it('returns base path for empty section path (cover)', () => {
    expect(sectionHref('mx-1', { id: 'cover', nr: 1, title: 't', path: '' }))
      .toBe('/mandates/mx-1/report');
  });

  it('appends section path', () => {
    expect(sectionHref('mx-1', { id: 'goals', nr: 11, title: 't', path: 'goals' }))
      .toBe('/mandates/mx-1/report/goals');
  });
});


// ---------------------------------------------------------------------------
// KEYBOARD_SHORTCUTS Constant
// ---------------------------------------------------------------------------

describe('U-51 KEYBOARD_SHORTCUTS', () => {
  it('includes j/k navigation', () => {
    const keys = KEYBOARD_SHORTCUTS.map((s) => s.key);
    expect(keys).toContain('j');
    expect(keys).toContain('k');
  });

  it('includes g/G first/last', () => {
    const keys = KEYBOARD_SHORTCUTS.map((s) => s.key);
    expect(keys).toContain('g');
    expect(keys).toContain('G');
  });

  it('includes ? for help and Escape for close', () => {
    const keys = KEYBOARD_SHORTCUTS.map((s) => s.key);
    expect(keys).toContain('?');
    expect(keys).toContain('Escape');
  });

  it('all shortcuts have label + description', () => {
    for (const s of KEYBOARD_SHORTCUTS) {
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.description.length).toBeGreaterThan(5);
    }
  });
});


// ---------------------------------------------------------------------------
// isTypingInInput
// ---------------------------------------------------------------------------

describe('U-51 isTypingInInput', () => {
  it('returns false for null', () => {
    expect(isTypingInInput(null)).toBe(false);
  });

  it('returns true for INPUT element', () => {
    expect(isTypingInInput({ tagName: 'INPUT' } as any)).toBe(true);
  });

  it('returns true for TEXTAREA element', () => {
    expect(isTypingInInput({ tagName: 'TEXTAREA' } as any)).toBe(true);
  });

  it('returns true for SELECT element', () => {
    expect(isTypingInInput({ tagName: 'SELECT' } as any)).toBe(true);
  });

  it('returns true for contentEditable element', () => {
    expect(isTypingInInput({ tagName: 'DIV', isContentEditable: true } as any)).toBe(true);
  });

  it('returns false for normal DIV', () => {
    expect(isTypingInInput({ tagName: 'DIV' } as any)).toBe(false);
  });

  it('handles lowercase tagName', () => {
    expect(isTypingInInput({ tagName: 'input' } as any)).toBe(true);
  });
});
