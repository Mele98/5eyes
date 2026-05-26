/**
 * Sprint U-P28 PR C: Edit-Forms, die in den NotesDrawer eingebettet werden.
 *
 * Zwei Varianten:
 *  - SingleFieldForm — 1 Textarea (für Asset Allocation / Risikowährungen /
 *    Branchen). Speichert das eine Feld, leerer String → Auto-Default
 *    greift wieder.
 *  - WeiteresVorgehenForm — 2 Textareas + Termin-Input + 3 dynamische
 *    Listen (offene Fragen / TODOs / Dokumente).
 *
 * Beide nutzen den `useReportNotes`-Hook. Nach Save wird optional ein
 * Caller-Callback ausgelöst, der den vollen Advisory-Report neu lädt
 * (damit die Sektion im DOM sofort den neuen Text zeigt).
 */
import { useEffect, useMemo, useState } from 'react';
import { NotesDrawer } from './NotesDrawer';
import { useReportNotes } from '@/api/useReportNotes';
import type { ReportNotes, ReportNotesUpdate } from '@/api/reportNotes';

// ---------------------------------------------------------------------------
// 1) Generische Single-Textarea-Variante
// ---------------------------------------------------------------------------

export type SingleField =
  | { kind: 'aa_anmerkungen'; title: 'Anmerkungen Asset Allocation' }
  | { kind: 'waehrungen_erklaerung'; title: 'Erklärung Risikowährungen' }
  | { kind: 'branchen_analyse'; title: 'Analyse Branchen-Diversifikation' };

export interface SingleFieldFormProps {
  open: boolean;
  onClose: () => void;
  mandateId: string;
  field: SingleField;
  /** Auto-Default-Text aus dem Aggregator (wird angezeigt, wenn nichts
      gepflegt ist — damit der Berater weiss, was er "ersetzt"). */
  autoDefaultText: string;
  /** Wird nach erfolgreichem Save ausgeloest; idealerweise Aufruf von
      useAdvisoryReport().reload, damit die Sektion sich aktualisiert. */
  onSaved?: () => void;
}

export function SingleFieldForm({
  open,
  onClose,
  mandateId,
  field,
  autoDefaultText,
  onSaved,
}: SingleFieldFormProps) {
  const { data, save, saving, saveError } = useReportNotes(mandateId);
  const persisted = data ? ((data[field.kind] ?? '') as string) : '';
  const [draft, setDraft] = useState<string>('');

  // Wenn der Drawer aufgemacht wird, neuesten persistierten Wert in den
  // Draft uebernehmen. Wenn nichts gepflegt -> leer (Berater sieht
  // Auto-Default-Text als Placeholder).
  useEffect(() => {
    if (open) setDraft(persisted);
  }, [open, persisted]);

  const dirty = draft !== persisted;

  const handleSave = async () => {
    const payload: ReportNotesUpdate = { [field.kind]: draft } as ReportNotesUpdate;
    await save(payload, () => {
      onSaved?.();
      onClose();
    });
  };

  const handleReset = async () => {
    // Leerer String beim Backend = Auto-Default wieder greifen lassen
    const payload: ReportNotesUpdate = { [field.kind]: '' } as ReportNotesUpdate;
    await save(payload, () => {
      onSaved?.();
      onClose();
    });
  };

  return (
    <NotesDrawer
      open={open}
      title={field.title}
      subtitle="Berater-Override. Leer lassen = Auto-Text aus den Engine-Daten."
      onClose={onClose}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={handleReset}
            disabled={saving || !persisted}
            className="
              text-caption text-ink-muted underline-offset-4
              hover:text-accent hover:underline
              disabled:cursor-not-allowed disabled:opacity-40
            "
          >
            Auf Auto-Default zurücksetzen
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="
                rounded-card border border-rule bg-canvas-panel
                px-4 py-2 text-caption text-ink-muted
                hover:border-rule-strong
              "
            >
              Abbrechen
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !dirty}
              className="
                rounded-card bg-accent px-4 py-2
                text-caption font-medium text-canvas-panel
                shadow-sm transition
                hover:bg-ink disabled:cursor-not-allowed disabled:opacity-40
              "
            >
              {saving ? 'Speichern…' : 'Speichern'}
            </button>
          </div>
        </div>
      }
    >
      <label className="block">
        <span className="text-micro uppercase tracking-widest text-ink-subtle">
          Auto-Default (Engine)
        </span>
        <p className="mt-2 whitespace-pre-wrap rounded-card border border-rule bg-canvas-subtle px-3 py-2 text-caption text-ink-muted">
          {autoDefaultText || '—'}
        </p>
      </label>
      <label className="mt-block block">
        <span className="text-micro uppercase tracking-widest text-ink-subtle">
          Berater-Text (überschreibt den Auto-Default)
        </span>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={8}
          className="
            mt-2 block w-full
            rounded-card border border-rule
            bg-canvas-panel px-3 py-2
            text-body text-ink
            placeholder:text-ink-subtle/70
            focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30
          "
          placeholder="Eigener Text… (leer lassen = Auto-Default greift wieder)"
        />
      </label>
      {saveError ? (
        <p className="mt-block text-caption text-status-rot">
          Fehler beim Speichern: {saveError.detail || saveError.message}
        </p>
      ) : null}
    </NotesDrawer>
  );
}

// ---------------------------------------------------------------------------
// 2) Weiteres-Vorgehen-Variante: mehrere Felder + dynamische Listen
// ---------------------------------------------------------------------------

interface DynListProps {
  label: string;
  items: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}

function DynList({ label, items, onChange, placeholder }: DynListProps) {
  const update = (idx: number, value: string) => {
    onChange(items.map((it, i) => (i === idx ? value : it)));
  };
  const remove = (idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  };
  const add = () => onChange([...items, '']);

  return (
    <fieldset className="mt-block">
      <legend className="text-micro uppercase tracking-widest text-ink-subtle">
        {label}
      </legend>
      <div className="mt-2 space-y-2">
        {items.length === 0 ? (
          <p className="text-caption text-ink-subtle/80">
            Noch keine Einträge.
          </p>
        ) : null}
        {items.map((item, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <input
              type="text"
              value={item}
              onChange={(e) => update(idx, e.target.value)}
              placeholder={placeholder}
              className="
                flex-1 rounded-card border border-rule
                bg-canvas-panel px-3 py-1.5 text-caption text-ink
                focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30
              "
            />
            <button
              type="button"
              onClick={() => remove(idx)}
              aria-label={`${label} Eintrag ${idx + 1} entfernen`}
              className="
                rounded-card border border-rule px-2 py-1
                text-caption text-ink-muted
                hover:border-status-rot hover:text-status-rot
              "
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={add}
          className="
            text-caption text-accent underline-offset-4
            hover:underline
          "
        >
          + Eintrag hinzufügen
        </button>
      </div>
    </fieldset>
  );
}

export interface WeiteresVorgehenFormProps {
  open: boolean;
  onClose: () => void;
  mandateId: string;
  /** Auto-Default-Texte aus dem Aggregator. */
  autoBlockOptimierungen: string;
  autoBlockZielstrategie: string;
  onSaved?: () => void;
}

export function WeiteresVorgehenForm({
  open,
  onClose,
  mandateId,
  autoBlockOptimierungen,
  autoBlockZielstrategie,
  onSaved,
}: WeiteresVorgehenFormProps) {
  const { data, save, saving, saveError } = useReportNotes(mandateId);
  const initial = useMemo(() => buildInitial(data), [data]);

  const [blockOpt, setBlockOpt] = useState('');
  const [blockZiel, setBlockZiel] = useState('');
  const [termin, setTermin] = useState('');
  const [fragen, setFragen] = useState<string[]>([]);
  const [todos, setTodos] = useState<string[]>([]);
  const [dokumente, setDokumente] = useState<string[]>([]);

  useEffect(() => {
    if (!open) return;
    setBlockOpt(initial.blockOpt);
    setBlockZiel(initial.blockZiel);
    setTermin(initial.termin);
    setFragen(initial.fragen);
    setTodos(initial.todos);
    setDokumente(initial.dokumente);
  }, [open, initial]);

  // Leere Strings in den Listen werden vor dem Save heraus gefiltert
  // (sonst speichern wir Phantom-Einträge mit "" als sichtbare Bullets).
  const clean = (xs: string[]) => xs.map((x) => x.trim()).filter(Boolean);

  const handleSave = async () => {
    const payload: ReportNotesUpdate = {
      vorgehen_block_optimierungen: blockOpt,
      vorgehen_block_zielstrategie: blockZiel,
      vorgehen_naechster_termin: termin,
      vorgehen_offene_fragen: clean(fragen),
      vorgehen_todos: clean(todos),
      vorgehen_dokumente: clean(dokumente),
    };
    await save(payload, () => {
      onSaved?.();
      onClose();
    });
  };

  const handleReset = async () => {
    await save(
      {
        vorgehen_block_optimierungen: '',
        vorgehen_block_zielstrategie: '',
        vorgehen_naechster_termin: '',
        vorgehen_offene_fragen: [],
        vorgehen_todos: [],
        vorgehen_dokumente: [],
      },
      () => {
        onSaved?.();
        onClose();
      },
    );
  };

  const anythingPersisted =
    !!data &&
    (!!data.vorgehen_block_optimierungen ||
      !!data.vorgehen_block_zielstrategie ||
      !!data.vorgehen_naechster_termin ||
      data.vorgehen_offene_fragen.length > 0 ||
      data.vorgehen_todos.length > 0 ||
      data.vorgehen_dokumente.length > 0);

  return (
    <NotesDrawer
      open={open}
      title="Weiteres Vorgehen"
      subtitle="Berater-Texte + Listen pro Mandat. Leere Felder fallen auf Auto-Default zurück."
      onClose={onClose}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={handleReset}
            disabled={saving || !anythingPersisted}
            className="
              text-caption text-ink-muted underline-offset-4
              hover:text-accent hover:underline
              disabled:cursor-not-allowed disabled:opacity-40
            "
          >
            Alles auf Auto-Default zurücksetzen
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="
                rounded-card border border-rule bg-canvas-panel
                px-4 py-2 text-caption text-ink-muted
                hover:border-rule-strong
              "
            >
              Abbrechen
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="
                rounded-card bg-accent px-4 py-2
                text-caption font-medium text-canvas-panel
                shadow-sm transition
                hover:bg-ink disabled:cursor-not-allowed disabled:opacity-40
              "
            >
              {saving ? 'Speichern…' : 'Speichern'}
            </button>
          </div>
        </div>
      }
    >
      <label className="block">
        <span className="text-micro uppercase tracking-widest text-ink-subtle">
          Optimierungsmassnahmen (Auto-Default sichtbar)
        </span>
        <p className="mt-2 whitespace-pre-wrap rounded-card border border-rule bg-canvas-subtle px-3 py-2 text-caption text-ink-muted">
          {autoBlockOptimierungen || '—'}
        </p>
        <textarea
          value={blockOpt}
          onChange={(e) => setBlockOpt(e.target.value)}
          rows={5}
          className="
            mt-2 block w-full
            rounded-card border border-rule
            bg-canvas-panel px-3 py-2 text-body text-ink
            focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30
          "
          placeholder="Eigener Text…"
        />
      </label>

      <label className="mt-block block">
        <span className="text-micro uppercase tracking-widest text-ink-subtle">
          Zielstrategie (Auto-Default sichtbar)
        </span>
        <p className="mt-2 whitespace-pre-wrap rounded-card border border-rule bg-canvas-subtle px-3 py-2 text-caption text-ink-muted">
          {autoBlockZielstrategie || '—'}
        </p>
        <textarea
          value={blockZiel}
          onChange={(e) => setBlockZiel(e.target.value)}
          rows={5}
          className="
            mt-2 block w-full
            rounded-card border border-rule
            bg-canvas-panel px-3 py-2 text-body text-ink
            focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30
          "
          placeholder="Eigener Text…"
        />
      </label>

      <label className="mt-block block">
        <span className="text-micro uppercase tracking-widest text-ink-subtle">
          Nächster Termin
        </span>
        <input
          type="text"
          value={termin}
          onChange={(e) => setTermin(e.target.value)}
          placeholder='z. B. 2026-08-15 oder „Quartals-Review September"'
          className="
            mt-2 block w-full
            rounded-card border border-rule
            bg-canvas-panel px-3 py-2 text-body text-ink
            focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30
          "
        />
      </label>

      <DynList
        label="Offene Fragen"
        items={fragen}
        onChange={setFragen}
        placeholder="z. B. Pillar-3a-Limit erreicht?"
      />
      <DynList
        label="To-Dos"
        items={todos}
        onChange={setTodos}
        placeholder="z. B. Vorsorgeauftrag aufsetzen"
      />
      <DynList
        label="Dokumente"
        items={dokumente}
        onChange={setDokumente}
        placeholder="z. B. Identifikationspapier"
      />

      {saveError ? (
        <p className="mt-block text-caption text-status-rot">
          Fehler beim Speichern: {saveError.detail || saveError.message}
        </p>
      ) : null}
    </NotesDrawer>
  );
}

function buildInitial(data: ReportNotes | null) {
  if (!data) {
    return {
      blockOpt: '',
      blockZiel: '',
      termin: '',
      fragen: [] as string[],
      todos: [] as string[],
      dokumente: [] as string[],
    };
  }
  return {
    blockOpt: data.vorgehen_block_optimierungen ?? '',
    blockZiel: data.vorgehen_block_zielstrategie ?? '',
    termin: data.vorgehen_naechster_termin ?? '',
    fragen: [...data.vorgehen_offene_fragen],
    todos: [...data.vorgehen_todos],
    dokumente: [...data.vorgehen_dokumente],
  };
}
