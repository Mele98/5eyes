/**
 * U-FE-4: Sektion 12 — Risikoprofilierung.
 *
 * Drei-Spalten-Summary (Profil · Score · Risikobudget), Score-Bars für
 * Risikofähigkeit + Risikobereitschaft, Override-Hinweis falls aktiv,
 * Fragen-Liste am Ende.
 *
 * FINMA-Disziplin: §2 Risikoprofil ist nur ANGEZEIGT, nicht editierbar
 * in der Sub-App. Override geht über die Hauptapp 5eyes_v2.html.
 */
import type { RisikoprofilierungData, RiskQuestion } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct, formatInteger } from '@/lib/format';

interface RisikoprofilProps {
  data: RisikoprofilierungData;
}

export function Risikoprofil({ data }: RisikoprofilProps) {
  return (
    <ReportPage
      nr={12}
      kicker="Risikoprofilierung"
      title="Risikoprofilierung"
      subtitle="FINMA-konforme Eignungsprüfung — Score, Profil, Begründung."
    >
      <SummaryBox data={data} />

      <section className="mt-section">
        <h2 className="font-serif text-h2 text-ink">Score-Komponenten</h2>
        <div className="mt-3 space-y-3">
          <ScoreBar label="Risikofähigkeit" score={data.risk_capacity_score_x10} />
          <ScoreBar label="Risikobereitschaft" score={data.risk_willingness_score_x10} />
        </div>
      </section>

      {data.is_overridden ? <OverrideNotice reason={data.override_reason} /> : null}

      {data.questions && data.questions.length > 0 ? (
        <section className="mt-section">
          <h2 className="font-serif text-h2 text-ink">Fragen der Risikoprofilierung</h2>
          <QuestionsTable questions={data.questions} />
        </section>
      ) : null}
    </ReportPage>
  );
}

// ---------------------------------------------------------------------------

function SummaryBox({ data }: { data: RisikoprofilierungData }) {
  const profile = data.final_profile || '—';
  const scoreText =
    data.final_score_x10 && data.final_score_x10 > 0
      ? `${data.final_score_x10} / 100`
      : '—';
  const riskyText = formatBpsAsPct(data.risky_fraction_bps);

  return (
    <section className="grid grid-cols-1 gap-block border-l-4 border-accent bg-canvas-subtle p-6 md:grid-cols-3">
      <SummaryCell label="Profil" value={profile} />
      <SummaryCell label="Score" value={scoreText} />
      <SummaryCell label="Risikobudget" value={riskyText} />
    </section>
  );
}

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        {label}
      </p>
      <p className="mt-2 font-serif text-h2 text-ink">{value}</p>
    </div>
  );
}

function ScoreBar({ label, score }: { label: string; score: number | null }) {
  const normalized = Math.max(0, Math.min(100, Number(score ?? 0)));
  const scoreText = normalized > 0 ? `${formatInteger(normalized)} / 100` : '—';
  return (
    <div className="grid grid-cols-[minmax(8rem,12rem)_minmax(0,1fr)_minmax(4rem,5rem)] items-center gap-4 border-b border-rule pb-3 last:border-b-0">
      <div className="text-caption font-semibold text-ink">{label}</div>
      <div className="h-1.5 overflow-hidden rounded-full bg-canvas-subtle">
        <div
          className="h-full bg-accent"
          style={{ width: `${normalized}%` }}
        />
      </div>
      <div className="text-right font-mono text-caption text-ink-muted">
        {scoreText}
      </div>
    </div>
  );
}

function OverrideNotice({ reason }: { reason: string | null }) {
  return (
    <section className="mt-section border-l-4 border-status-neutral bg-canvas-subtle px-5 py-4">
      <p className="text-micro uppercase tracking-widest text-status-neutral">
        Manuelle Übersteuerung
      </p>
      <p className="mt-2 text-body text-ink">
        {reason && reason.trim() ? reason : 'Ohne dokumentierte Begründung.'}
      </p>
    </section>
  );
}

function QuestionsTable({ questions }: { questions: RiskQuestion[] }) {
  return (
    <table className="mt-3 w-full text-caption">
      <thead>
        <tr className="border-b border-rule">
          <th className="pb-2 pr-4 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
            Frage
          </th>
          <th className="pb-2 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">
            Punkte
          </th>
        </tr>
      </thead>
      <tbody>
        {questions.map((q) => (
          <tr key={q.key} className="border-b border-rule last:border-b-0">
            <td className="py-2 pr-4 text-ink-muted">{q.frage || '—'}</td>
            <td className="py-2 text-right font-mono text-ink">
              {formatInteger(q.points)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
