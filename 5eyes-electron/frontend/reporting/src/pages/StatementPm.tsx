/**
 * U-FE-4: Sektion 14 — Statement aus dem Portfoliomanagement.
 *
 * 7 Investmentgrundsätze als editoriale Liste — nummerierte Header mit
 * Gold-Akzent + Titel + Body. Statische Inhalte aus dem Aggregator.
 */
import type { StatementPmData } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';

interface StatementPmProps {
  data: StatementPmData;
}

export function StatementPm({ data }: StatementPmProps) {
  const principles = data.principles ?? [];
  return (
    <ReportPage
      nr={14}
      kicker="Statement Portfoliomanagement"
      title="Statement aus dem Portfoliomanagement"
      subtitle="Sieben Investmentgrundsätze, die die 5eyes-Beratungs- und Verwaltungslogik leiten."
    >
      {principles.length === 0 ? (
        <p className="italic text-caption text-ink-subtle">
          Keine Investmentgrundsätze erfasst.
        </p>
      ) : (
        <ol className="space-y-block">
          {principles.map((p, idx) => (
            <li
              key={p.key}
              className="grid gap-4 border-b border-rule pb-block last:border-b-0 lg:grid-cols-[3rem_minmax(0,1fr)]"
            >
              <span className="font-mono text-h2 text-gold">
                {String(idx + 1).padStart(2, '0')}
              </span>
              <div>
                <h2 className="font-serif text-h3 text-ink">{p.title}</h2>
                <p className="mt-2 text-body text-ink-muted">{p.body}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </ReportPage>
  );
}
