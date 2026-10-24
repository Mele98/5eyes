/**
 * Sprint U-P28 PR D — Sektion 15: Weiteres Vorgehen.
 *
 * Berater-Inhalt: Optimierungsmassnahmen + Zielstrategie (Textbloecke)
 * plus Liste der offenen Fragen, To-Dos, Dokumente und der naechste
 * Termin. Pflege ueber den NotesDrawer (Edit-Button rechts-oben).
 *
 * Wenn nichts gepflegt ist, zeigt die Sektion den Auto-Default-
 * Platzhalter („Vom Berater zu ergänzen…") aus dem Aggregator.
 *
 * Eigene Article-Struktur (statt eines geteilten ReportPage-Wrappers),
 * damit die Sektion auch dann funktioniert, wenn das Sub-App-Layout
 * sich weiterentwickelt (Sektionen 4-14 kommen separat).
 */
import type { WeiteresVorgehenData } from '@/api/types';
import { WeiteresVorgehenEditWrapper } from '@/components/SectionEditWrapper';

interface WeiteresVorgehenProps {
  data: WeiteresVorgehenData;
  mandateId: string;
  onReload: () => void;
}

const PLACEHOLDER_PREFIX = '(Vom Berater zu ergänzen';

function looksPersisted(text: string): boolean {
  return !!text && !text.startsWith(PLACEHOLDER_PREFIX);
}

export function WeiteresVorgehen({
  data,
  mandateId,
  onReload,
}: WeiteresVorgehenProps) {
  const hasOverride =
    looksPersisted(data.block_optimierungen) ||
    looksPersisted(data.block_zielstrategie) ||
    !!data.naechster_termin ||
    data.offene_fragen.length > 0 ||
    data.todos.length > 0 ||
    data.dokumente.length > 0;

  return (
    <article className="relative mx-auto min-h-screen max-w-editorial px-page-x py-page-y print:min-h-0">
      <div className="no-print print:hidden">
        <WeiteresVorgehenEditWrapper
          mandateId={mandateId}
          autoBlockOptimierungen={data.block_optimierungen}
          autoBlockZielstrategie={data.block_zielstrategie}
          isEdited={hasOverride}
          onSaved={onReload}
        />
      </div>

      <p className="text-micro uppercase text-ink-subtle">
        Sektion 15 · Weiteres Vorgehen
      </p>
      <header className="mt-block border-b border-rule pb-block">
        <h1 className="font-serif text-h1 text-ink">Weiteres Vorgehen</h1>
        <p className="mt-3 max-w-3xl font-serif text-h3 italic text-ink-muted">
          Konkrete Massnahmen, offene Fragen und nächster Termin.
        </p>
      </header>

      <div className="mt-section grid gap-block lg:grid-cols-2">
        <Block title="Optimierungsmassnahmen" body={data.block_optimierungen} />
        <Block title="Zielstrategie" body={data.block_zielstrategie} />
      </div>

      <div className="mt-section grid gap-block md:grid-cols-3">
        <ListBox label="Offene Fragen" items={data.offene_fragen} />
        <ListBox label="To-Dos" items={data.todos} />
        <ListBox label="Dokumente" items={data.dokumente} />
      </div>

      <div className="mt-section border-t border-rule pt-block">
        <p className="text-micro uppercase tracking-widest text-ink-subtle">
          Nächster Termin
        </p>
        <p className="mt-2 text-body text-ink">
          {data.naechster_termin || (
            <span className="text-ink-subtle">Noch nicht vereinbart.</span>
          )}
        </p>
      </div>
    </article>
  );
}

function Block({ title, body }: { title: string; body: string }) {
  const persisted = looksPersisted(body);
  return (
    <section className="border border-rule bg-canvas-panel p-5">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        {title}
      </p>
      <p
        className={[
          'mt-3 whitespace-pre-wrap text-body',
          persisted ? 'text-ink' : 'text-ink-muted italic',
        ].join(' ')}
      >
        {body}
      </p>
    </section>
  );
}

function ListBox({ label, items }: { label: string; items: string[] }) {
  return (
    <section className="border border-rule bg-canvas-panel p-5">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        {label}
      </p>
      {items.length === 0 ? (
        <p className="mt-3 text-caption italic text-ink-subtle">
          Keine Einträge.
        </p>
      ) : (
        <ul className="mt-3 space-y-2 text-caption text-ink">
          {items.map((item, idx) => (
            <li key={idx} className="flex gap-2">
              <span aria-hidden="true" className="select-none text-ink-subtle">
                ·
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
