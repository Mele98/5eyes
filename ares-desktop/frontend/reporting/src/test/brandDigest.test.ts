import { describe, expect, it } from 'vitest';
import { legacyBrandIdsIn, normalizeText } from './brandDigest';

/**
 * Selbsttest fuer den digest-basierten Marken-Guard.
 *
 * Die Negativfixtures sind ROT13-kodiert und werden erst zur Laufzeit
 * dekodiert: So beweist der Test, dass echte Altnamen gefunden werden, ohne
 * dass ein Altname im Klartext im Repo steht (Ziffern bleiben, Buchstaben
 * werden um 13 Stellen verschoben).
 */
function rot13(value: string): string {
  return value.replace(/[a-z]/gi, (ch) => {
    const base = ch <= 'Z' ? 65 : 97;
    return String.fromCharCode(((ch.charCodeAt(0) - base + 13) % 26) + base);
  });
}

const VECTORS: ReadonlyArray<readonly [string, string]> = [
  ['LB-A', '3rlrf'],
  ['LB-A', '3 Rlrf'],
  ['LB-A', 'Guerr-Rlrf'],
  ['LB-B', '5_Rlrf'],
  ['LB-C', 'Jrnygu Nepuvgrxgra'],
];

describe('brandDigest', () => {
  it.each(VECTORS.map((v, i) => [i, v[0], v[1]] as const))(
    'Vektor %i (%s) wird in Text und HTML erkannt',
    (_i, brand, encoded) => {
      const name = rot13(encoded);
      expect(legacyBrandIdsIn(name)).toEqual([brand]);
      expect(legacyBrandIdsIn(`<p>Erstellt von <b>${name}</b></p>`)).toEqual([brand]);
      expect(legacyBrandIdsIn(`Zeile\n${name.slice(0, 2)}\n${name.slice(2)}`)).toEqual([brand]);
    },
  );

  it('neutraler Text bleibt sauber', () => {
    expect(legacyBrandIdsIn('Ares Reporting, eyes only, 3 keys, 5 years')).toEqual([]);
    expect(normalizeText('A-b_c.d e')).toBe('abcde');
  });
});
