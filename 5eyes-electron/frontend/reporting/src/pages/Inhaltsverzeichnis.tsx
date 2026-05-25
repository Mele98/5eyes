import type { InhaltsverzeichnisData } from '@/api/types';

interface InhaltsverzeichnisProps {
  data: InhaltsverzeichnisData;
}

export function Inhaltsverzeichnis({ data }: InhaltsverzeichnisProps) {
  return (
    <article
      data-testid="report-page-toc"
      className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y"
    >
      <p className="text-micro uppercase text-ink-subtle">Sektion 3</p>
      <header className="mt-block">
        <h1 className="font-serif text-h1 text-ink">Inhaltsverzeichnis</h1>
      </header>

      <ol className="mt-section">
        {data.kapitel.map((kapitel) => (
          <li
            key={`${kapitel.nr}-${kapitel.title}`}
            className="group grid gap-4 border-t border-rule py-5 transition-colors duration-soft hover:border-rule-strong md:grid-cols-[4rem_minmax(0,1fr)]"
          >
            <span className="font-mono text-caption text-accent">
              {String(kapitel.nr).padStart(2, '0')}
            </span>
            <span className="font-serif text-h2 text-ink transition-colors duration-soft group-hover:text-accent">
              {kapitel.title}
            </span>
          </li>
        ))}
      </ol>
    </article>
  );
}
