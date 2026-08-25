/**
 * Sprint U-23 + U-24 (Roadmap-Punkte 23+24, 2026-06-04): Drawer-Draft +
 * Dirty-State Tests.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  buildDirtyCloseMessage,
  clearDraft,
  createDraftKey,
  dirtyFields,
  isDirty,
  loadDraft,
  saveDraft,
} from './drawerDraft';


beforeEach(() => {
  if (typeof window !== 'undefined' && window.sessionStorage) {
    window.sessionStorage.clear();
  }
});


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
// U-23: Draft-Key
// ---------------------------------------------------------------------------

describe('U-23 createDraftKey', () => {
  it('uses 5eyes:draft prefix', () => {
    expect(createDraftKey('MX-1', 'notes')).toBe('5eyes:draft:MX-1:notes');
  });

  it('sanitizes mandate-id', () => {
    expect(createDraftKey('mandate/with:slash', 'notes')).toMatch(
      /^5eyes:draft:mandate_with_slash:notes$/,
    );
  });

  it('sanitizes form-id', () => {
    expect(createDraftKey('MX-1', 'form/with spaces')).toMatch(
      /^5eyes:draft:MX-1:form_with_spaces$/,
    );
  });

  it('preserves alphanumeric + underscore + hyphen', () => {
    const key = createDraftKey('MX_1-test', 'form_2');
    expect(key).toBe('5eyes:draft:MX_1-test:form_2');
  });
});


// ---------------------------------------------------------------------------
// U-23: saveDraft / loadDraft / clearDraft (sessionStorage)
// ---------------------------------------------------------------------------

describe('U-23 saveDraft + loadDraft', () => {
  it('save then load returns same values', () => {
    const key = createDraftKey('MX-1', 'aa');
    saveDraft(key, { aa_anmerkungen: 'Test-Text' });
    const loaded = loadDraft(key);
    expect(loaded).not.toBeNull();
    expect(loaded!.values).toEqual({ aa_anmerkungen: 'Test-Text' });
  });

  it('loadDraft returns null for unknown key', () => {
    expect(loadDraft('5eyes:draft:nonexistent:x')).toBeNull();
  });

  it('savedAt is ISO timestamp', () => {
    const key = createDraftKey('MX-1', 'aa');
    saveDraft(key, { v: 1 });
    const loaded = loadDraft(key);
    expect(loaded!.savedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('overwrites existing draft', () => {
    const key = createDraftKey('MX-1', 'aa');
    saveDraft(key, { v: 'old' });
    saveDraft(key, { v: 'new' });
    expect(loadDraft(key)!.values).toEqual({ v: 'new' });
  });

  it('clearDraft removes entry', () => {
    const key = createDraftKey('MX-1', 'aa');
    saveDraft(key, { v: 1 });
    clearDraft(key);
    expect(loadDraft(key)).toBeNull();
  });

  it('loadDraft returns null for corrupted JSON', () => {
    const key = createDraftKey('MX-1', 'aa');
    window.sessionStorage.setItem(key, 'not valid json');
    expect(loadDraft(key)).toBeNull();
  });

  it('loadDraft returns null for missing values field', () => {
    const key = createDraftKey('MX-1', 'aa');
    window.sessionStorage.setItem(
      key, JSON.stringify({ savedAt: '2026-06-04T00:00:00Z' }),
    );
    expect(loadDraft(key)).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// U-23: saveDraft Robustheit (storage-Quota etc.)
// ---------------------------------------------------------------------------

describe('U-23 saveDraft robustness', () => {
  it('returns false when sessionStorage.setItem throws (Quota)', () => {
    const key = createDraftKey('MX-1', 'aa');
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => { throw new Error('QuotaExceeded'); });
    expect(saveDraft(key, { v: 'huge' })).toBe(false);
    setItemSpy.mockRestore();
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
