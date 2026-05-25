import type { DisclaimerData } from '@/api/types';

interface DisclaimerProps {
  data: DisclaimerData;
}

export function Disclaimer({ data }: DisclaimerProps) {
  return (
    <article
      data-testid="report-page-disclaimer"
      className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y"
    >
      <p className="text-micro uppercase text-ink-subtle">Sektion 2</p>
      <header className="mt-block border-b border-rule pb-block">
        <h1 className="font-serif text-h1 text-ink">Rechtliche Hinweise</h1>
        <p className="mt-4 max-w-prose text-body text-ink-muted">
          Grundlage für die persönliche Beratung und die Dokumentation der
          wesentlichen Einschränkungen dieses Berichts.
        </p>
      </header>

      <ol className="mt-section space-y-6">
        {data.hinweise.map((hinweis, index) => (
          <li
            key={`${index}-${hinweis.slice(0, 16)}`}
            className="grid gap-4 border-b border-rule pb-6 md:grid-cols-[4rem_minmax(0,1fr)]"
          >
            <span className="font-mono text-caption text-accent">
              {String(index + 1).padStart(2, '0')}
            </span>
            <p className="max-w-prose text-body text-ink">{hinweis}</p>
          </li>
        ))}
      </ol>
    </article>
  );
}
