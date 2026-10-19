import { describe, expect, it } from 'vitest';
import {
  formatAge,
  formatBpsAsPct,
  formatBpsSignedPct,
  formatChfRappen,
  formatHorizon,
  formatInteger,
  fmtChfCompact,
  fmtNumber,
  formatChfFromRappen,
  parseNumberInputCH,
  fmtPct,
  fmtProbPct,
  fmtSharpe,
  fmtSignedPct,
} from './format';
import contract from './format.contract.json';

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
  it('formatiert bps als Prozent mit 1 Dezimal default (AA-UX-FORMAT-001)', () => {
    expect(formatBpsAsPct(4250)).toBe('42.5\u00a0%');
    expect(formatBpsAsPct(100)).toBe('1.0\u00a0%');
  });

  it('respektiert decimals-Option', () => {
    // 7250 bps = 72.5 % — JS-toFixed rundet zu 73, Python's :.0f zu 72.
    // Beide Werte sind akzeptabel; wir prüfen nur dass der Suffix stimmt.
    const score = formatBpsAsPct(7250, { decimals: 0 });
    expect(score).toMatch(/^(72|73)\u00a0%$/);
    expect(formatBpsAsPct(1234, { decimals: 2 })).toBe('12.34\u00a0%');
  });

  it('rendert null als em-dash', () => {
    expect(formatBpsAsPct(null)).toBe('—');
    expect(formatBpsAsPct(undefined)).toBe('—');
  });
});

describe('formatBpsSignedPct', () => {
  it('schreibt + bei positiven Werten, 0 ohne Vorzeichen', () => {
    expect(formatBpsSignedPct(450)).toBe('+4.5\u00a0%');
    expect(formatBpsSignedPct(0)).toBe('0.0\u00a0%');
  });

  it('schreibt U+2212 (nie Bindestrich) bei negativen Werten', () => {
    expect(formatBpsSignedPct(-1000)).toBe('\u221210.0\u00a0%');
    expect(formatBpsSignedPct(-1000)).not.toContain('-');
  });

  it('null → em-dash', () => {
    expect(formatBpsSignedPct(null)).toBe('—');
  });
});

describe('AA-UX-FORMAT-001: gemeinsamer Vertrag (format.contract.json)', () => {
  const fns: Record<string, (...args: never[]) => string> = {
    fmtPct, fmtSignedPct, fmtProbPct, fmtSharpe, fmtNumber,
  } as unknown as Record<string, (...args: never[]) => string>;
  for (const [fn, args, expected] of contract.cases as Array<[string, unknown[], string]>) {
    it(`${fn}(${JSON.stringify(args)}) -> ${JSON.stringify(expected)}`, () => {
      expect((fns[fn] as (...a: unknown[]) => string)(...args)).toBe(expected);
    });
  }
  for (const [rappenChf, expected] of contract.compact_chf_cases as Array<[number, string]>) {
    it(`fmtChfCompact(${rappenChf})`, () => {
      expect(fmtChfCompact(rappenChf)).toBe(expected);
    });
  }
  for (const [rappen, expected] of contract.chf_rappen_cases as Array<[number, string]>) {
    it(`formatChfRappen(${rappen}) -> gerades Apostroph`, () => {
      expect(formatChfRappen(rappen)).toBe(expected);
    });
  }
  for (const [input, expected] of contract.parse_cases as Array<[string, number]>) {
    it(`parseNumberInputCH(${JSON.stringify(input)})`, () => {
      expect(parseNumberInputCH(input)).toBe(expected);
    });
  }
  it('kein typografisches Apostroph (U+2019) in CHF-Ausgaben', () => {
    expect(formatChfFromRappen(125_000_000)).toBe("CHF 1'250'000");
    expect(fmtChfCompact(850_000)).not.toContain('’');
  });
  it('negative CHF mit U+2212', () => {
    expect(formatChfRappen(-123_400)).toBe("CHF \u22121'234");
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
