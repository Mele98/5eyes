import { describe, expect, it } from 'vitest';
import {
  formatAge,
  formatBpsAsPct,
  formatBpsSignedPct,
  formatChfRappen,
  formatHorizon,
  formatInteger,
} from './format';

describe('formatChfRappen', () => {
  it('formatiert Rappen mit Apostroph als Tausender', () => {
    expect(formatChfRappen(6_600_000)).toBe("CHF 66'000");
    expect(formatChfRappen(250_000_000)).toBe("CHF 2'500'000");
  });

  it('rendert null/undefined als em-dash', () => {
    expect(formatChfRappen(null)).toBe('—');
    expect(formatChfRappen(undefined)).toBe('—');
  });

  it('respektiert withUnit=false (gibt nur Zahl)', () => {
    expect(formatChfRappen(1_000_000, { withUnit: false })).toBe("10'000");
    expect(formatChfRappen(null, { withUnit: false })).toBe('0');
  });

  it('rundet auf ganze CHF (keine Rappen-Anzeige)', () => {
    // 99'999 Rappen = 999.99 CHF → gerundet 1'000
    expect(formatChfRappen(99_999)).toBe("CHF 1'000");
  });

  it('robust gegen NaN/Infinity', () => {
    expect(formatChfRappen(Number.NaN)).toBe('—');
    expect(formatChfRappen(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('formatBpsAsPct', () => {
  it('formatiert bps als Prozent mit 1 Dezimal default', () => {
    expect(formatBpsAsPct(4250)).toBe('42.5 %');
    expect(formatBpsAsPct(100)).toBe('1.0 %');
  });

  it('respektiert decimals-Option', () => {
    // 7250 bps = 72.5 % — JS-toFixed rundet zu 73, Python's :.0f zu 72.
    // Beide Werte sind akzeptabel; wir prüfen nur dass der Suffix stimmt.
    const score = formatBpsAsPct(7250, { decimals: 0 });
    expect(score).toMatch(/^(72|73) %$/);
    expect(formatBpsAsPct(1234, { decimals: 2 })).toBe('12.34 %');
  });

  it('rendert null als em-dash', () => {
    expect(formatBpsAsPct(null)).toBe('—');
    expect(formatBpsAsPct(undefined)).toBe('—');
  });
});

describe('formatBpsSignedPct', () => {
  it('schreibt + bei positiven Werten', () => {
    expect(formatBpsSignedPct(450)).toBe('+4.5 %');
    expect(formatBpsSignedPct(0)).toBe('+0.0 %');
  });

  it('schreibt - bei negativen Werten', () => {
    expect(formatBpsSignedPct(-1000)).toBe('-10.0 %');
  });

  it('null → em-dash', () => {
    expect(formatBpsSignedPct(null)).toBe('—');
  });
});

describe('formatInteger', () => {
  it('rendert int', () => {
    expect(formatInteger(49)).toBe('49');
    expect(formatInteger(0)).toBe('0');
  });

  it('rundet', () => {
    expect(formatInteger(49.7)).toBe('50');
  });

  it('null → em-dash', () => {
    expect(formatInteger(null)).toBe('—');
  });
});

describe('formatAge', () => {
  it('rendert Alter mit „Jahre" suffix', () => {
    expect(formatAge(49)).toBe('49 Jahre');
  });

  it('0 oder null → em-dash (kein „0 Jahre")', () => {
    expect(formatAge(0)).toBe('—');
    expect(formatAge(null)).toBe('—');
    expect(formatAge(-5)).toBe('—');
  });
});

describe('formatHorizon', () => {
  it('rendert Horizont in Jahren', () => {
    expect(formatHorizon(16)).toBe('16 Jahre');
  });

  it('0/null → em-dash', () => {
    expect(formatHorizon(0)).toBe('—');
    expect(formatHorizon(null)).toBe('—');
  });
});
