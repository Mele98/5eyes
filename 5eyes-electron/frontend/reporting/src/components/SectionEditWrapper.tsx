/**
 * Sprint U-P28 PR D: Vereinfachter Einbau des EditButton + Drawer in
 * eine Report-Sektion.
 *
 * Statt 5+ Zeilen pro Sektion (useState + Button + Form-Komponente)
 * wird das hier in einem einzigen Render-Slot zusammengefasst:
 *
 *   <SingleFieldEditWrapper
 *     mandateId={mandateId}
 *     field={{ kind: 'aa_anmerkungen', title: '...' }}
 *     autoDefaultText={data.asset_allocation.anmerkungen}
 *     onSaved={reloadReport}
 *   />
 *
 * Wird typischerweise in den `toolbar`-Slot der `ReportPage` gegeben.
 */
import { useState } from 'react';
import { EditButton } from './EditButton';
import {
  SingleFieldForm,
  WeiteresVorgehenForm,
  type SingleField,
} from './NotesEditForms';

interface SingleFieldEditWrapperProps {
  mandateId: string;
  field: SingleField;
  /** Auto-Default-Text aus dem Aggregator-Output. */
  autoDefaultText: string;
  /** Heuristik: Sektion hat einen Berater-Override falls Text != Default.
      Wird für die „Bearbeitet"-Marke am Button benutzt. */
  isEdited?: boolean;
  /** Nach erfolgreichem Save → meist `reload` von useAdvisoryReport. */
  onSaved: () => void;
}

export function SingleFieldEditWrapper({
  mandateId,
  field,
  autoDefaultText,
  isEdited,
  onSaved,
}: SingleFieldEditWrapperProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {/* comp-4: aussagekräftiges aria-label statt generischem "Sektion bearbeiten". */}
      <EditButton onClick={() => setOpen(true)} isEdited={isEdited} ariaLabel={`${field.title} bearbeiten`} />
      <SingleFieldForm
        open={open}
        onClose={() => setOpen(false)}
        mandateId={mandateId}
        field={field}
        autoDefaultText={autoDefaultText}
        onSaved={onSaved}
      />
    </>
  );
}

interface WeiteresVorgehenEditWrapperProps {
  mandateId: string;
  autoBlockOptimierungen: string;
  autoBlockZielstrategie: string;
  isEdited?: boolean;
  onSaved: () => void;
}

export function WeiteresVorgehenEditWrapper({
  mandateId,
  autoBlockOptimierungen,
  autoBlockZielstrategie,
  isEdited,
  onSaved,
}: WeiteresVorgehenEditWrapperProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <EditButton onClick={() => setOpen(true)} isEdited={isEdited} ariaLabel="Weiteres Vorgehen bearbeiten" />
      <WeiteresVorgehenForm
        open={open}
        onClose={() => setOpen(false)}
        mandateId={mandateId}
        autoBlockOptimierungen={autoBlockOptimierungen}
        autoBlockZielstrategie={autoBlockZielstrategie}
        onSaved={onSaved}
      />
    </>
  );
}
