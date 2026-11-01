/**
 * Digest-basierte Markenpruefung fuer Guard-Tests (nur Tests).
 *
 * Gegenstueck zu `ares-backend/tests/brand_digest_support.py`: Die Altmarken
 * LB-A, LB-B und LB-C stehen nicht im Klartext im Repo, sondern nur als
 * sha256 der normalisierten Stammform. Der Text wird normalisiert (Kleinschrift,
 * ohne Leerraum, `_`, `-`, `.`); jedes Teilstring-Fenster der Laengen aus der
 * Liste wird gehasht und verglichen. Treffer melden nur die Marken-ID.
 *
 * Die Liste muss mit der Python-Liste identisch sein;
 * `ares-backend/tests/test_brand_digest_support.py` erzwingt das.
 */
import { createHash } from 'node:crypto';

type BrandId = 'LB-A' | 'LB-B' | 'LB-C';

export const LEGACY_BRAND_STEM_DIGESTS: ReadonlyArray<readonly [BrandId, number, string]> = [
  ['LB-A', 5, '0b3e941a5b9ba6737e1ca686861781649750602fe7d7b7ea1b69f0f748a38d10'],
  ['LB-A', 9, '5368038931b4b7738a9414a5e44e2bb1b0634a5697e74367e8aec126c68bf686'],
  ['LB-A', 8, 'afe600a48993336a29ec7149fd5eaa40f624ca07607ed9482327aa8b821d52b6'],
  ['LB-A', 7, 'cbf143aa86f46c9b838b1dd39a44a351cfe7a854b36af4285bbb917fc3389144'],
  ['LB-A', 7, '3cb4e57e94e2e647cc9b8add3760c1e782d272a6b51874fd055d93fbe2edd3aa'],
  ['LB-A', 9, '14150de8f78b00e2f11ac18c3f0486cf40c515cc08d169621b847be93290f9a4'],
  ['LB-A', 9, '6388c06527a4bbf6c7bdbd92f2eefa400100f6c08ee4fcd0fd49475937dc87d5'],
  ['LB-A', 6, '6b09459ae231ff92ef88487a42ef6139e6611d6719033638000e2ce82825edc4'],
  ['LB-B', 5, '681aab74af1a2a039ff95a500da3f289290163115a70a2af7ee07521e73793bc'],
  ['LB-B', 8, 'ff70abe6ddd7cd7dd4745d7c406ba32cd02f50cd8e0b34afa4ab3f655032f97d'],
  ['LB-B', 7, '039012b91782665fc291837cfb12913f4127f2a8d4aafde62a33c1bfbed74c8f'],
  ['LB-B', 6, '2576b6daab292235425bf476d633e28d5392913bf679150ff0bb10c692a38c01'],
  ['LB-B', 10, '015234568dea9d0f9768a7b9a89290975e7bef330b89e14fa36e041ecdc1635b'],
  ['LB-B', 9, 'f75b1da0e9b9f0fa143654fd9526c094ce1382b0da18743197389b5199f78d4e'],
  ['LB-B', 9, 'e37c538c41ca211c0c508b14b8c980cf151d000e647f08357fddd9fc7d7d1e66'],
  ['LB-B', 6, 'be7e13c66160dc917e44d6ca6f590f5f6c7e339e95df4d127e79684002a3ab98'],
  ['LB-C', 15, 'bdff65fea8937f64d38ec27eb9c7b431ecd2d64771deaad58db4a69d994d4181'],
  ['LB-C', 16, '17658fd47e49afdf01f8c3dea7540b4e580fbdd1941a18031d9f1b3350b57231'],
];

export function normalizeText(text: string): string {
  return text.toLowerCase().replace(/[\s_.-]+/g, '');
}

/** Marken-IDs, deren Stammform-Digest im Text vorkommt (sortiert). */
export function legacyBrandIdsIn(text: string): BrandId[] {
  const byLength = new Map<number, Map<string, BrandId>>();
  for (const [brand, length, digest] of LEGACY_BRAND_STEM_DIGESTS) {
    if (!byLength.has(length)) byLength.set(length, new Map());
    byLength.get(length)!.set(digest, brand);
  }
  const haystack = Array.from(normalizeText(text));
  const found = new Set<BrandId>();
  for (const [length, table] of byLength) {
    for (let start = 0; start + length <= haystack.length; start += 1) {
      const window = haystack.slice(start, start + length).join('');
      const brand = table.get(createHash('sha256').update(window, 'utf8').digest('hex'));
      if (brand) found.add(brand);
    }
  }
  return Array.from(found).sort();
}
