/**
 * AA-UX-HONEST-FAN-001 (UX-Audit „Signature-Verbesserungen", Punkt 1):
 * Beschriftung des Vermoegensfaechers -- EIN Vertrag fuer App (Chart.js im
 * Monolithen 5eyes_v2.html, gleichnamige Funktionen) und Report (SVG).
 *
 *  - Endwerte direkt am rechten Rand: „2.41 Mio. · Median"
 *  - Zielmarker als Pille mit Erfolgswahrscheinlichkeit: „Ruhestand · 82 %"
 *  - Ziel oberhalb der Skala: „▲ CHF 5.00 Mio. über Skala"
 *  - Klartext aus P10/P90 des Endjahres: „In 8 von 10 Verläufen liegt Ihr
 *    Vermögen 2050 zwischen CHF 1.60 und 3.40 Mio."
 *
 * Die Falltabelle fanAnnotations.contract.json wird gegen BEIDE
 * Implementierungen ausgefuehrt (vitest + 5eyes-backend/tests/
 * test_monolith_fan_annotations_contract.py). Keine Zusicherung: der Satz
 * beschreibt nur die simulierte Verteilung (8 von 10 Verlaeufen).
 */
import { fmtChfCompactAmount, fmtProbPct } from './format';

export type FanEndKey = 'p90' | 'p50' | 'p10';

const END_SUFFIX: Record<FanEndKey, string> = {
  p90: 'P90',
  p50: 'Median',
  p10: 'P10',
};

function finite(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** „2.41 Mio. · Median" -- leer bei nicht-endlichem Wert. */
export function fanEndLabelText(chf: number | null | undefined, key: FanEndKey): string {
  if (!finite(chf)) return '';
  return `${fmtChfCompactAmount(chf)} · ${END_SUFFIX[key] ?? END_SUFFIX.p50}`;
}

/**
 * „Ruhestand · 82 %". Ohne belastbare Wahrscheinlichkeit (null/undefined/
 * nicht-endlich) nur das Label -- nie eine erfundene Prozentzahl.
 */
export function fanGoalPillText(
  label: string | null | undefined,
  probPct: number | null | undefined,
): string {
  const l = String(label ?? '').trim() || 'Ziel';
  if (!finite(probPct)) return l;
  return `${l} · ${fmtProbPct(probPct)}`;
}

/** „▲ CHF 5.00 Mio. über Skala" (Ziel liegt oberhalb der y-Skala). */
export function fanAboveScaleText(targetChf: number | null | undefined): string {
  if (!finite(targetChf)) return '';
  return `▲ CHF ${fmtChfCompactAmount(targetChf)} über Skala`;
}

/**
 * Klartext aus P10/P90 des Endjahres. Leer, wenn Jahr oder Werte fehlen
 * oder P10 > P90 (inkonsistente Daten -> lieber kein Satz als ein falscher).
 */
export function fanRangeSentence(
  year: string | number | null | undefined,
  p10Chf: number | null | undefined,
  p90Chf: number | null | undefined,
): string {
  const y = String(year ?? '').trim();
  if (!y || !finite(p10Chf) || !finite(p90Chf) || p10Chf > p90Chf) return '';
  const lo = fmtChfCompactAmount(p10Chf);
  const hi = fmtChfCompactAmount(p90Chf);
  const MIO = ' Mio.';
  const range =
    lo.endsWith(MIO) && hi.endsWith(MIO)
      ? `CHF ${lo.slice(0, -MIO.length)} und ${hi}`
      : `CHF ${lo} und CHF ${hi}`;
  const end = range.endsWith('.') ? '' : '.';
  return `In 8 von 10 Verläufen liegt Ihr Vermögen ${y} zwischen ${range}${end}`;
}

/**
 * Entzerrt Beschriftungen am rechten Rand: Rueckgabe in Eingabereihenfolge,
 * Mindestabstand `gap` (Pixel, y waechst nach unten), moeglichst innerhalb
 * [top, bottom]. Reihenfolge der Labels bleibt erhalten.
 */
export function fanSpreadLabelYs(
  ys: number[],
  gap: number,
  top: number,
  bottom: number,
): number[] {
  const order = ys.map((y, i) => ({ y: Number(y), i })).sort((a, b) => a.y - b.y || a.i - b.i);
  const out = order.map((o) => o.y);
  for (let k = 0; k < out.length; k++) {
    if (k === 0) out[k] = Math.max(out[k], top);
    else out[k] = Math.max(out[k], out[k - 1] + gap);
  }
  for (let k = out.length - 1; k >= 0; k--) {
    if (k === out.length - 1) out[k] = Math.min(out[k], bottom);
    else out[k] = Math.min(out[k], out[k + 1] - gap);
  }
  if (out.length && out[0] < top) {
    const shift = top - out[0];
    for (let k = 0; k < out.length; k++) out[k] += shift;
  }
  const result = new Array<number>(ys.length);
  order.forEach((o, k) => {
    result[o.i] = out[k];
  });
  return result;
}
