/**
 * Sprint U-24 (Roadmap-Punkt 24, 2026-06-04): Dirty-State Tests.
 * (Draft-Storage U-23 entfernt in W4-a3, kein Produktaufrufer.)
 */
import { describe, it, expect } from 'vitest';
import {
  buildDirtyCloseMessage,
  dirtyFields,
  isDirty,
} from './drawerDraft';


// ---------------------------------------------------------------------------
// U-24: Dirty-State
// ---------------------------------------------------------------------------

describe('U-24 isDirty', () => {
  it('returns false for equal objects', () => {
    expect(isDirty({ a: 1 }, { a: 1 })).toBe(false);
  });

  it('returns true when value differs', () => {
    expect(isDirty({ a: 1 }, { a: 2 })).toBe(true);
  });

  it('returns true when key added', () => {
    expect(isDirty({ a: 1, b: 2 }, { a: 1 })).toBe(true);
  });

  it('returns true when key removed', () => {
    expect(isDirty({ a: 1 }, { a: 1, b: 2 })).toBe(true);
  });

  it('compares nested objects via JSON-stringify', () => {
    expect(isDirty({ a: { b: 1 } }, { a: { b: 1 } })).toBe(false);
    expect(isDirty({ a: { b: 1 } }, { a: { b: 2 } })).toBe(true);
  });

  it('handles empty objects', () => {
    expect(isDirty({}, {})).toBe(false);
  });
});


describe('U-24 dirtyFields', () => {
  it('returns empty for equal objects', () => {
    expect(dirtyFields({ a: 1 }, { a: 1 })).toEqual([]);
  });

  it('lists changed field names', () => {
    const result = dirtyFields({ a: 1, b: 2 }, { a: 1, b: 3 });
    expect(result).toEqual(['b']);
  });

  it('lists multiple changed fields', () => {
    const result = dirtyFields(
      { a: 1, b: 2, c: 3 },
      { a: 1, b: 99, c: 99 },
    );
    expect(result.sort()).toEqual(['b', 'c']);
  });

  it('includes added fields', () => {
    const result = dirtyFields({ a: 1, b: 2 }, { a: 1 });
    expect(result).toContain('b');
  });

  it('includes removed fields', () => {
    const result = dirtyFields({ a: 1 }, { a: 1, b: 2 });
    expect(result).toContain('b');
  });
});


// ---------------------------------------------------------------------------
// U-24: buildDirtyCloseMessage
// ---------------------------------------------------------------------------

describe('U-24 buildDirtyCloseMessage', () => {
  it('returns empty string for no dirty fields', () => {
    expect(buildDirtyCloseMessage([])).toBe('');
  });

  it('singular message for one field', () => {
    const msg = buildDirtyCloseMessage(['aa_anmerkungen']);
    expect(msg).toContain('aa_anmerkungen');
    expect(msg).toContain('verloren');
    expect(msg).toContain('Schliessen');
  });

  it('plural message for multiple fields', () => {
    const msg = buildDirtyCloseMessage(['a', 'b', 'c']);
    expect(msg).toContain('3 Feldern');
    expect(msg).toContain('verloren');
  });

  it('message is non-empty and ends with question', () => {
    const msg = buildDirtyCloseMessage(['x']);
    expect(msg.length).toBeGreaterThan(0);
    expect(msg).toMatch(/\?$/);
  });
});
