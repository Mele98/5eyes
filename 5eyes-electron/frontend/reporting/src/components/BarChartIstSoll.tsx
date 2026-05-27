/**
 * U-FE-3: IST-vs-SOLL-Bar-Chart als reusable Component.
 *
 * Editorial-Stil mit dünnen, gleichlangen Bar-Spuren:
 * - IST in Petrol-Akzent
 * - SOLL in Petrol-Subtle (etwas heller)
 * - Drift rechts in monospace, threshold-basierte Farbe
 * - Optional Toleranzbänder hinter dem SOLL-Bar (Gold-Subtle)
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
  band_min_bps?: number;
  band_max_bps?: number;
}

export interface BarChartIstSollProps {
  items: BarChartItem[];
  /** Toleranzbänder anzeigen (nur bei Asset Allocation, nicht bei FX/Branchen). */
  showBands?: boolean;
  /** Drift-Schwelle in bps, ab der die Drift-Anzeige rot wird. Default 1500 (15 %). */
  driftThresholdBps?: number;
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
  const driftAbs = Math.abs(item.drift_bps);
  let driftClass = 'text-status-gruen';
  if (driftAbs >= driftThresholdBps) {
    driftClass = 'text-status-rot';
  } else if (driftAbs >= driftThresholdBps / 2) {
    driftClass = 'text-status-neutral';
  }

  const istPct = clamp01(item.ist_bps / 10000) * 100;
  const sollPct = clamp01(item.soll_bps / 10000) * 100;
  const bandMin = item.band_min_bps != null ? clamp01(item.band_min_bps / 10000) * 100 : null;
  const bandMax = item.band_max_bps != null ? clamp01(item.band_max_bps / 10000) * 100 : null;
  const bandSpan = bandMin != null && bandMax != null ? bandMax - bandMin : null;

  return (
    <div className="grid grid-cols-[minmax(6rem,9rem)_minmax(0,1fr)_minmax(4rem,5rem)] items-center gap-4">
      <div className="text-caption font-semibold text-ink">{item.label}</div>

      <div className="space-y-2">
        <Track
          label={`IST  ${formatBpsAsPct(item.ist_bps)}`}
          fillPct={istPct}
          fillClass="bg-accent"
        />
        <Track
          label={`SOLL ${formatBpsAsPct(item.soll_bps)}`}
          fillPct={sollPct}
          fillClass="bg-accent-subtle"
          bandStartPct={showBands && bandMin != null ? bandMin : null}
          bandSpanPct={showBands && bandSpan != null ? bandSpan : null}
        />
      </div>

      <div className={`text-right font-mono text-caption ${driftClass}`}>
        {formatBpsSignedPct(item.drift_bps)}
      </div>
    </div>
  );
}

interface TrackProps {
  label: string;
  fillPct: number;
  fillClass: string;
  /** Wenn gesetzt: Tolerance-Band als hellere Schicht. */
  bandStartPct?: number | null;
  bandSpanPct?: number | null;
}

function Track({
  label,
  fillPct,
  fillClass,
  bandStartPct,
  bandSpanPct,
}: TrackProps) {
  return (
    <div className="space-y-1">
      <div className="text-micro uppercase tracking-widest text-ink-subtle">
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
