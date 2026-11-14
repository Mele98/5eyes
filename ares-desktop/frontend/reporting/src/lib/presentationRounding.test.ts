import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { POLICY_VERSION, runCase, type Typography } from './presentationRounding';
import { fmtPct, formatChfRappen } from './format';

// G7: derselbe Golden-Vektor wie Python (PDF) und Classic-App.
const here = dirname(fileURLToPath(import.meta.url));
const goldenPath = resolve(here, '../../../../../ares-backend/core/presentation_rounding_golden.json');
const golden = JSON.parse(readFileSync(goldenPath, 'utf8')) as {
  policy_version: string;
  cases: { id: string; fn: string; args: unknown[]; plain: string | string[]; screen: string | string[] }[];
};

describe('G7 presentationRounding (Policy ares-rounding/1)', () => {
  it('teilt die Policy-Version mit dem Golden-Vektor', () => {
    expect(POLICY_VERSION).toBe(golden.policy_version);
  });

  for (const typography of ['plain', 'screen'] as Typography[]) {
    it(`erfuellt alle Golden-Faelle (${typography})`, () => {
      for (const c of golden.cases) {
        expect([c.id, runCase(c.fn, c.args, typography)]).toEqual([c.id, c[typography]]);
      }
    });
  }

  it('Report-Formatter laufen ueber den gemeinsamen Formatter', () => {
    expect(fmtPct(1225)).toBe('12.3 %');
    expect(fmtPct(-1225)).toBe('−12.3 %');
    expect(fmtPct(1235)).toBe('12.4 %');
    expect(formatChfRappen(250, { currency: 'CHF' })).toBe('CHF 3');
    expect(formatChfRappen(-150, { currency: 'CHF' })).toBe('CHF −2');
  });
});
