/**
 * U-FE-3: IST-vs-SOLL-Bar-Chart als reusable Component.
 *
 * Editorial-Stil mit dünnen, gleichlangen Bar-Spuren:
 * - IST in Ink (Design-Token `chartPalette.ist`)
 * - SOLL in Petrol-Akzent (Design-Token `chartPalette.soll`)
 * - Drift rechts in monospace, tabellarische Ziffern
 * - Optional Toleranzbänder hinter dem SOLL-Bar (Gold-Subtle)
 *
 * REPORT-DRIFT-BAND-COLOR-001 (2026-10-18): Die Drift-Farbe richtet sich
 * nach der TATSAECHLICHEN Bandbreite der Anlageklasse (band_min_bps /
 * band_max_bps bzw. das Backend-Flag `in_band`): ausserhalb = Warnfarbe
 * plus Klartext, innerhalb = neutral. Vorher galt eine fixe 15-pp-Schwelle
 * -- Liquiditaet mit Band 0–10 % und IST 18 % (Drift +8 pp) erschien
 * gruen, obwohl die Position ausserhalb der Bandbreite lag. Die fixe
 * Schwelle bleibt nur fuer Datenreihen OHNE Bandbreite (Sektion 9/10).
 *
 * Wiederverwendet in Sektion 8 (Asset Allocation), 9 (Risikowährungen),
 * 10 (Branchen) — alle drei haben identische Daten-Form.
 */
import { formatBpsAsPct, formatBpsSignedPct } from '@/lib/format';

export interface BarChartItem {
  label: string;
  ist_bps: number;
  soll_bps: number;
  drift_bps: number;
  band_min_bps?: number | null;
  band_max_bps?: number | null;
  /** Backend-Bandstatus (depot_check: band_min <= ist <= band_max). */
  in_band?: boolean | null;
}

export interface BarChartIstSollProps {
  items: BarChartItem[];
  /** Toleranzbänder anzeigen (nur bei Asset Allocation, nicht bei FX/Branchen). */
  showBands?: boolean;
  /**
   * Nur fuer Items OHNE Bandbreite: Drift-Schwelle in bps, ab der die
   * Drift-Anzeige rot wird. Default 1500 (15 pp).
   */
  driftThresholdBps?: number;
}

export type BandStatus = 'inside' | 'outside';

/**
 * Bandstatus eines Items: 'inside' / 'outside' oder null, wenn keine
 * Bandbreite definiert ist. Das Backend-Flag `in_band` hat Vorrang (eine
 * Quelle der Wahrheit); fehlt es, wird mit derselben Regel wie
 * services/depot_check.py gerechnet: Grenzen inklusive, Band 0/0 = "kein
 * Band definiert".
 */
export function bandStatus(item: BarChartItem): BandStatus | null {
  if (item.in_band === true) return 'inside';
  if (item.in_band === false) return 'outside';
  const lo = item.band_min_bps;
  const hi = item.band_max_bps;
  if (lo == null || hi == null || !Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  if (lo === 0 && hi === 0) return null;
  return lo <= item.ist_bps && item.ist_bps <= hi ? 'inside' : 'outside';
}

export function BarChartIstSoll({
  items,
  showBands = false,
  driftThresholdBps = 1500,
}: BarChartIstSollProps) {
  if (items.length === 0) {
    return (
      <p className="italic text-caption text-ink-subtle">
        Keine Datenpunkte erfasst.
      </p>
    );
  }
  return (
    <div className="space-y-block">
      {items.map((item) => (
        <BarRow
          key={item.label}
          item={item}
          showBands={showBands}
          driftThresholdBps={driftThresholdBps}
        />
      ))}
    </div>
  );
}

interface BarRowProps {
  item: BarChartItem;
  showBands: boolean;
  driftThresholdBps: number;
}

function BarRow({ item, showBands, driftThresholdBps }: BarRowProps) {
  const status = bandStatus(item);
  let driftClass: string;
  if (status === 'outside') {
    driftClass = 'text-status-rot';
  } else if (status === 'inside') {
    driftClass = 'text-ink-muted';
  } else {
    // Kein Band (Sektion 9/10): bisherige Schwellen-Logik
    const driftAbs = Math.abs(item.drift_bps);
    driftClass = 'text-status-gruen';
    if (driftAbs >= driftThresholdBps) {
      driftClass = 'text-status-rot';
    } else if (driftAbs >= driftThresholdBps / 2) {
      driftClass = 'text-status-neutral';
    }
  }

  const istPct = clamp01(item.ist_bps / 10000) * 100;
  const sollPct = clamp01(item.soll_bps / 10000) * 100;
  const hasBand =
    item.band_min_bps != null &&
    item.band_max_bps != null &&
    !(item.band_min_bps === 0 && item.band_max_bps === 0);
  const bandMin = hasBand ? clamp01(item.band_min_bps! / 10000) * 100 : null;
  const bandMax = hasBand ? clamp01(item.band_max_bps! / 10000) * 100 : null;
  const bandSpan = bandMin != null && bandMax != null ? bandMax - bandMin : null;
  const bandText =
    showBands && hasBand
      ? ` · Band ${formatBpsAsPct(item.band_min_bps)} – ${formatBpsAsPct(item.band_max_bps)}`
      : '';

  return (
    <div
      className="grid grid-cols-[minmax(6rem,9rem)_minmax(0,1fr)_minmax(4rem,6rem)] items-center gap-4"
      data-testid={`bar-row-${item.label}`}
      data-band-status={status ?? 'none'}
    >
      <div className="text-caption font-semibold text-ink">{item.label}</div>

      <div className="space-y-2">
        <Track
          label={`IST  ${formatBpsAsPct(item.ist_bps)}`}
          fillPct={istPct}
          fillClass="bg-ink dark:bg-canvas"
          testId="bar-ist-fill"
        />
        <Track
          label={`SOLL ${formatBpsAsPct(item.soll_bps)}${bandText}`}
          fillPct={sollPct}
          fillClass="bg-accent dark:bg-accent-subtle"
          testId="bar-soll-fill"
          bandStartPct={showBands && bandMin != null ? bandMin : null}
          bandSpanPct={showBands && bandSpan != null ? bandSpan : null}
        />
      </div>

      <div className={`text-right font-mono tabular-nums text-caption ${driftClass}`}>
        <div data-testid="bar-drift">{formatBpsSignedPct(item.drift_bps)}</div>
        {status === 'outside' ? (
          <div className="font-sans text-micro uppercase tracking-wider">
            ausserhalb Band
          </div>
        ) : null}
      </div>
    </div>
  );
}

interface TrackProps {
  label: string;
  fillPct: number;
  fillClass: string;
  testId: string;
  /** Wenn gesetzt: Tolerance-Band als hellere Schicht. */
  bandStartPct?: number | null;
  bandSpanPct?: number | null;
}

function Track({
  label,
  fillPct,
  fillClass,
  testId,
  bandStartPct,
  bandSpanPct,
}: TrackProps) {
  return (
    <div className="space-y-1">
      <div className="text-micro uppercase tracking-widest tabular-nums text-ink-subtle">
        {label}
      </div>
      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-canvas-subtle">
        {bandStartPct != null && bandSpanPct != null && bandSpanPct > 0 ? (
          <div
            aria-hidden="true"
            className="absolute inset-y-0 bg-gold-subtle/40"
            style={{
              left: `${bandStartPct}%`,
              width: `${bandSpanPct}%`,
            }}
          />
        ) : null}
        <div
          data-testid={testId}
          className={`absolute inset-y-0 left-0 ${fillClass}`}
          style={{ width: `${fillPct}%` }}
        />
      </div>
    </div>
  );
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}
