/**
 * Sprint U-FINMA-2.4: Editor-Drawer für AdvisoryLog-Einträge.
 *
 * Modi:
 * - 'manual': leerer Form, Berater füllt alle FIDLEG-Pflichtfelder
 * - 'auto-prefilled': Pre-filled aus Auto-Log-Response (Topics + Warnings
 *   sind schon da), Berater editiert nur description/decision/Dauer
 *
 * Pflichtfelder (Validation client-side + server-side):
 * - description ≥ 30 Zeichen
 * - topics ≥ 1
 * - communication_channel enum
 * - duration_minutes 1-600
 * - entry_datetime ISO
 */
import { useState, useEffect } from 'react';
import { NotesDrawer } from './NotesDrawer';
import { useAdvisoryLog } from '@/api/useAdvisoryLog';
import type {
  AdvisoryEntryType,
  AdvisoryLogCreatePayload,
  AdvisoryLogStatus,
  CommunicationChannel,
} from '@/api/advisoryLog';
import type { BeratungsprotokollEntry } from '@/api/types';

const ENTRY_TYPES: AdvisoryEntryType[] = [
  'Jahresreview',
  'Quartalscheck',
  'Strategie-Anpassung',
  'Override-Entscheid',
  'Ereignis-Reaktion',
  'Drift-Entscheid',
  'Zieländerung',
  'Restriktionsänderung',
  'Initialer Beratungsabschluss',
  'Eignungsprüfung',
  'Sonstiges',
];

const CHANNELS: CommunicationChannel[] = [
  'persoenlich',
  'video',
  'telefon',
  'schriftlich',
  'hybrid',
];

const STATUSES: AdvisoryLogStatus[] = [
  'Empfohlen',
  'Beschlossen',
  'Umgesetzt',
  'Abgelehnt',
  'Überarbeitung nötig',
];

const CHANNEL_LABELS: Record<CommunicationChannel, string> = {
  persoenlich: 'Persönlich',
  video: 'Video',
  telefon: 'Telefon',
  schriftlich: 'Schriftlich',
  hybrid: 'Hybrid',
};

export interface AdvisoryLogEditorProps {
  open: boolean;
  onClose: () => void;
  mandateId: string;
  /** Wenn aus Auto-Log: pre-filled mit Topics+Warnings, sonst leer. */
  preFilled?: BeratungsprotokollEntry | null;
  onSaved?: (entry: BeratungsprotokollEntry) => void;
}

interface FormState {
  entry_type: AdvisoryEntryType;
  title: string;
  description: string;
  entry_datetime: string;
  duration_minutes: number;
  communication_channel: CommunicationChannel;
  location: string;
  topics: string[];
  risk_warnings_given: string[];
  cost_disclosure_given: boolean;
  status: AdvisoryLogStatus;
}

function buildInitialState(pre?: BeratungsprotokollEntry | null): FormState {
  const nowIso = new Date().toISOString().replace(/\.\d+Z$/, '.000Z');
  return {
    entry_type: (pre?.entry_type as AdvisoryEntryType) || 'Jahresreview',
    title: pre?.title || `Beratungsprotokoll ${nowIso.slice(0, 10)}`,
    description: pre?.description || '',
    entry_datetime: pre?.entry_datetime || nowIso,
    duration_minutes: pre?.duration_minutes ?? 60,
    communication_channel:
      (pre?.communication_channel as CommunicationChannel) || 'persoenlich',
    location: pre?.location || '',
    topics: pre?.topics?.length ? [...pre.topics] : [],
    risk_warnings_given: pre?.risk_warnings_given?.length
      ? [...pre.risk_warnings_given]
      : [],
    cost_disclosure_given: pre?.cost_disclosure_given === 1 || false,
    status: (pre?.status as AdvisoryLogStatus) || 'Empfohlen',
  };
}

export function AdvisoryLogEditor({
  open,
  onClose,
  mandateId,
  preFilled,
  onSaved,
}: AdvisoryLogEditorProps) {
  const { saving, saveError, create, reset } = useAdvisoryLog(mandateId);
  const [form, setForm] = useState<FormState>(() => buildInitialState(preFilled));
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(buildInitialState(preFilled));
      setValidationError(null);
      reset();
    }
  }, [open, preFilled, reset]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const validate = (): string | null => {
    if (form.description.trim().length < 30) {
      return 'Description muss mindestens 30 Zeichen lang sein (FIDLEG-Pflicht).';
    }
    const cleanTopics = form.topics.map((t) => t.trim()).filter(Boolean);
    if (cleanTopics.length === 0) {
      return 'Mindestens ein Thema muss angegeben werden.';
    }
    if (cleanTopics.some((t) => t.length < 3)) {
      return 'Jedes Thema muss mindestens 3 Zeichen lang sein.';
    }
    if (form.duration_minutes < 1 || form.duration_minutes > 600) {
      return 'Dauer muss zwischen 1 und 600 Minuten liegen.';
    }
    if (form.title.trim().length < 3) {
      return 'Titel muss mindestens 3 Zeichen lang sein.';
    }
    return null;
  };

  const handleSave = async () => {
    const err = validate();
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    const payload: AdvisoryLogCreatePayload = {
      entry_type: form.entry_type,
      title: form.title.trim(),
      description: form.description.trim(),
      entry_datetime: form.entry_datetime,
      duration_minutes: form.duration_minutes,
      communication_channel: form.communication_channel,
      language: 'de',
      location: form.location.trim() || null,
      participants: [],
      topics: form.topics.map((t) => t.trim()).filter(Boolean),
      risk_warnings_given: form.risk_warnings_given
        .map((w) => w.trim())
        .filter(Boolean),
      cost_disclosure_given: form.cost_disclosure_given,
      conflict_disclosure_ids: [],
      status: form.status,
    };
    await create(payload, (entry) => {
      onSaved?.(entry);
      onClose();
    });
  };

  return (
    <NotesDrawer
      open={open}
      title="Beratungsprotokoll erfassen"
      subtitle="FIDLEG Art. 16+17 — alle Pflichtfelder ausfüllen."
      onClose={onClose}
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-card border border-rule bg-canvas-panel px-4 py-2 text-caption text-ink-muted hover:border-rule-strong"
          >
            Abbrechen
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-card bg-accent px-4 py-2 text-caption font-medium text-canvas-panel shadow-sm transition hover:bg-ink disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? 'Speichern…' : 'Speichern'}
          </button>
        </div>
      }
    >
      {/* Eintragstyp + Status */}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Eintragstyp">
          <select
            value={form.entry_type}
            onChange={(e) => update('entry_type', e.target.value as AdvisoryEntryType)}
            className={inputClass}
          >
            {ENTRY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Status">
          <select
            value={form.status}
            onChange={(e) => update('status', e.target.value as AdvisoryLogStatus)}
            className={inputClass}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="Titel" className="mt-block">
        <input
          type="text"
          value={form.title}
          onChange={(e) => update('title', e.target.value)}
          className={inputClass}
        />
      </Field>

      <Field label="Beschreibung (min 30 Zeichen)" className="mt-block">
        <textarea
          value={form.description}
          onChange={(e) => update('description', e.target.value)}
          rows={5}
          className={inputClass}
          placeholder="Detaillierte Dokumentation der besprochenen Themen, Argumente, Entscheide…"
        />
        <p className="mt-1 text-micro text-ink-subtle">
          {form.description.trim().length} Zeichen ·{' '}
          {form.description.trim().length >= 30 ? '✓ ok' : 'Mindestlänge nicht erreicht'}
        </p>
      </Field>

      {/* Zeit + Dauer + Channel */}
      <div className="mt-block grid grid-cols-1 gap-3 md:grid-cols-3">
        <Field label="Zeitpunkt (ISO)">
          <input
            type="text"
            value={form.entry_datetime}
            onChange={(e) => update('entry_datetime', e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Dauer (Minuten)">
          <input
            type="number"
            min={1}
            max={600}
            value={form.duration_minutes}
            onChange={(e) =>
              update('duration_minutes', Number.parseInt(e.target.value || '0', 10))
            }
            className={inputClass}
          />
        </Field>
        <Field label="Kanal">
          <select
            value={form.communication_channel}
            onChange={(e) =>
              update('communication_channel', e.target.value as CommunicationChannel)
            }
            className={inputClass}
          >
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {CHANNEL_LABELS[c]}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="Ort (optional)" className="mt-block">
        <input
          type="text"
          value={form.location}
          onChange={(e) => update('location', e.target.value)}
          className={inputClass}
        />
      </Field>

      <DynList
        label="Themen (Pflicht, min 1, je min 3 Zeichen)"
        items={form.topics}
        onChange={(items) => update('topics', items)}
        placeholder="z. B. Strategic Asset Allocation"
      />

      <DynList
        label="Erteilte Risiko-Hinweise"
        items={form.risk_warnings_given}
        onChange={(items) => update('risk_warnings_given', items)}
        placeholder="z. B. Marktrisiko, Fremdwährungsrisiko"
      />

      <label className="mt-block flex items-center gap-2 text-caption text-ink">
        <input
          type="checkbox"
          checked={form.cost_disclosure_given}
          onChange={(e) => update('cost_disclosure_given', e.target.checked)}
          className="size-4 rounded border-rule text-accent focus:ring-accent"
        />
        Ex-ante Kosten dem Kunden kommuniziert (FIDLEG-Pflicht).
      </label>

      {validationError ? (
        <p className="mt-block text-caption text-status-rot">{validationError}</p>
      ) : null}
      {saveError ? (
        <p className="mt-block text-caption text-status-rot">
          Fehler beim Speichern: {saveError.detail || saveError.message}
        </p>
      ) : null}
    </NotesDrawer>
  );
}

// ---------------------------------------------------------------------------

const inputClass =
  'mt-1 block w-full rounded-card border border-rule bg-canvas-panel px-3 py-1.5 text-caption text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30';

function Field({
  label,
  children,
  className = '',
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="text-micro uppercase tracking-widest text-ink-subtle">
        {label}
      </span>
      {children}
    </label>
  );
}

interface DynListProps {
  label: string;
  items: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}

function DynList({ label, items, onChange, placeholder }: DynListProps) {
  const update = (idx: number, value: string) =>
    onChange(items.map((it, i) => (i === idx ? value : it)));
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, '']);

  return (
    <fieldset className="mt-block">
      <legend className="text-micro uppercase tracking-widest text-ink-subtle">
        {label}
      </legend>
      <div className="mt-2 space-y-2">
        {items.length === 0 ? (
          <p className="text-caption text-ink-subtle/80">Noch keine Einträge.</p>
        ) : null}
        {items.map((item, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <input
              type="text"
              value={item}
              onChange={(e) => update(idx, e.target.value)}
              placeholder={placeholder}
              className={`${inputClass} flex-1`}
            />
            <button
              type="button"
              onClick={() => remove(idx)}
              aria-label={`${label} Eintrag ${idx + 1} entfernen`}
              className="rounded-card border border-rule px-2 py-1 text-caption text-ink-muted hover:border-status-rot hover:text-status-rot"
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={add}
          className="text-caption text-accent underline-offset-4 hover:underline"
        >
          + Eintrag hinzufügen
        </button>
      </div>
    </fieldset>
  );
}
