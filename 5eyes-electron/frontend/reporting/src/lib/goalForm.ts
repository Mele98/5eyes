/**
 * Reine Form-Logik für den Goal-Editor (Track #64, ohne React → isoliert testbar).
 *
 * Spiegelt die Backend-Invarianten aus `5eyes-backend/schemas/wealth.py`:
 *  - GOAL_FAMILY_TYPE_MAP (319-324) → familyForType
 *  - hardnessMap der Monolith-saveGoal (5eyes_v2.html:24208) → hardnessForRank
 *  - _validate_goal_field_isolation (369-408) → validateGoalForm (require_targets=true)
 *  - goalSaveErrorText (5eyes_v2.html:24144) → formatGoalError
 *
 * Ziel: Der Berater bekommt die gleiche Feld-Isolation clientseitig gemeldet,
 * die das Backend hart erzwingt — Fehler werden vor dem POST sichtbar.
 */
import type {
  GoalCreatePayload,
  GoalFamily,
  GoalType,
  GoalScope,
  GoalValueMode,
  PensionPillar,
} from '@/api/types';

/** Erlaubte goal_type je goal_family (Backend GOAL_FAMILY_TYPE_MAP). */
export const GOAL_FAMILY_TYPE_MAP: Record<GoalFamily, GoalType[]> = {
  Vermögen: ['Kapitalerhalt', 'Vermögensziel', 'Vermoegensziel'],
  Cashflow: ['Einmalige_Ausgabe', 'Wiederkehrende_Ausgabe', 'Pensionsausgabe'],
  Rendite: ['Renditeziel'],
  Maximierung: ['Maximierung'],
};

/** Leitet die goal_family aus dem goal_type ab (Backend erzwingt Konsistenz). */
export function familyForType(type: GoalType): GoalFamily {
  for (const family of Object.keys(GOAL_FAMILY_TYPE_MAP) as GoalFamily[]) {
    if (GOAL_FAMILY_TYPE_MAP[family].includes(type)) {
      return family;
    }
  }
  // Defensiv — durch das GoalType-Literal nicht erreichbar.
  return 'Maximierung';
}

const HARDNESS_BY_RANK: Record<number, string> = {
  1: 'Hart',
  2: 'Primär',
  3: 'Opportunistisch',
};

/** Mappt Prio-Rang → Härtegrad (Monolith hardnessMap); Default "Primär". */
export function hardnessForRank(rank: number): string {
  return HARDNESS_BY_RANK[rank] ?? 'Primär';
}

/** Spiegelt _goal_type_key: lowercase, Leerzeichen→_, Umlaute→ae/oe/ue. */
export function goalTypeKey(type: string): string {
  return String(type ?? '')
    .trim()
    .toLowerCase()
    .replace(/ /g, '_')
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue');
}

function hardnessKey(hardness: string | null | undefined): string {
  return String(hardness ?? '')
    .trim()
    .toLowerCase()
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue');
}

function hasValue(value: unknown): boolean {
  return value !== null && value !== undefined && value !== '';
}

const WEALTH_TYPE_KEYS = new Set(['kapitalerhalt', 'vermoegensziel']);

function isWealthType(type: GoalType): boolean {
  return WEALTH_TYPE_KEYS.has(goalTypeKey(type));
}

/** Eingabe des Wizards (UI-nah; rappen/bps sind bereits umgerechnet). */
export interface GoalFormInput {
  goal_type: GoalType;
  label: string;
  rank: number;
  hardness?: string;
  goal_scope?: GoalScope;
  value_mode?: GoalValueMode;
  target_amount_rappen?: number | null;
  target_wealth_rappen?: number | null;
  target_return_bps?: number | null;
  frequency?: string | null;
  target_date?: string | null;
  horizon_years?: number | null;
  start_date?: string | null;
  weight_bps?: number | null;
  success_probability_min_x100?: number | null;
  probability_pct?: number;
  pension_pillar?: PensionPillar | null;
  is_ongoing?: boolean;
  notes?: string | null;
}

/**
 * Clientseitige Feld-Isolation, 1:1 zu _validate_goal_field_isolation
 * (require_targets=true). Gibt eine Liste menschenlesbarer Fehler zurück;
 * leeres Array = gültig.
 */
export function validateGoalForm(input: GoalFormInput): string[] {
  const errors: string[] = [];
  const key = goalTypeKey(input.goal_type);
  const hk = hardnessKey(input.hardness);

  if (!input.label || !input.label.trim()) {
    errors.push('Bezeichnung ist erforderlich.');
  }
  if (!(typeof input.rank === 'number' && input.rank >= 1)) {
    errors.push('Rang muss mindestens 1 sein.');
  }
  if (hk && !['hart', 'primaer', 'opportunistisch'].includes(hk)) {
    errors.push("hardness muss 'Hart', 'Primär' oder 'Opportunistisch' sein");
  }

  const forbid = (...fields: Array<keyof GoalFormInput>): void => {
    for (const field of fields) {
      if (hasValue(input[field])) {
        errors.push(`Feld '${field}' ist für Zieltyp '${input.goal_type}' nicht erlaubt`);
      }
    }
  };

  if (key === 'renditeziel') {
    forbid('target_amount_rappen', 'target_wealth_rappen', 'frequency');
    if (hk === 'hart') {
      errors.push("Renditeziel darf nicht als 'hart' definiert werden.");
    }
    if (!hasValue(input.target_return_bps)) {
      errors.push('Renditeziel benötigt target_return_bps');
    }
  } else if (key === 'einmalige_ausgabe') {
    forbid('target_return_bps', 'target_wealth_rappen', 'frequency');
    if (!hasValue(input.target_amount_rappen)) {
      errors.push('Einmalige_Ausgabe benötigt target_amount_rappen');
    }
    if (!(hasValue(input.target_date) || hasValue(input.horizon_years))) {
      errors.push('Einmalige_Ausgabe benötigt target_date oder horizon_years');
    }
  } else if (key === 'wiederkehrende_ausgabe' || key === 'pensionsausgabe') {
    forbid('target_return_bps', 'target_wealth_rappen');
    if (!hasValue(input.frequency)) {
      errors.push('Cashflow-Ziel benötigt frequency');
    }
  } else if (key === 'kapitalerhalt' || key === 'vermoegensziel') {
    forbid('target_return_bps', 'target_amount_rappen', 'frequency');
    if (!hasValue(input.target_wealth_rappen)) {
      errors.push('Vermögensziel benötigt target_wealth_rappen');
    }
    if (!(hasValue(input.target_date) || hasValue(input.horizon_years))) {
      errors.push('Vermögensziel benötigt target_date oder horizon_years');
    }
  } else if (key === 'maximierung') {
    forbid(
      'target_amount_rappen',
      'target_wealth_rappen',
      'target_return_bps',
      'target_date',
      'frequency',
    );
  }

  return errors;
}

/**
 * Baut den POST/PUT-Payload: genau EIN Target-Feld gesetzt (Rest null),
 * value_mode nur bei Vermögenszielen aus der Eingabe, sonst "nominal"
 * (Monolith saveGoal-Verhalten). data_classification immer "synthetic".
 */
export function buildGoalPayload(input: GoalFormInput): GoalCreatePayload {
  const goalType = input.goal_type;
  const key = goalTypeKey(goalType);
  const wealth = isWealthType(goalType);
  const isCashflow = key === 'einmalige_ausgabe'
    || key === 'wiederkehrende_ausgabe'
    || key === 'pensionsausgabe';

  return {
    goal_family: familyForType(goalType),
    goal_type: goalType,
    label: input.label.trim(),
    rank: input.rank,
    goal_scope: input.goal_scope ?? 'Beratungsvermögen',
    value_mode: wealth ? (input.value_mode ?? 'nominal') : 'nominal',
    hardness: input.hardness ?? hardnessForRank(input.rank),
    probability_pct: input.probability_pct ?? 100,
    is_ongoing: input.is_ongoing ?? false,
    data_classification: 'synthetic',
    target_amount_rappen: key === 'einmalige_ausgabe' ? (input.target_amount_rappen ?? null) : null,
    target_wealth_rappen: wealth ? (input.target_wealth_rappen ?? null) : null,
    target_return_bps: key === 'renditeziel' ? (input.target_return_bps ?? null) : null,
    frequency: isCashflow && key !== 'einmalige_ausgabe' ? (input.frequency ?? null) : null,
    target_date: input.target_date ?? null,
    horizon_years: input.horizon_years ?? null,
    start_date: input.start_date ?? null,
    weight_bps: input.weight_bps ?? null,
    success_probability_min_x100: input.success_probability_min_x100 ?? null,
    pension_pillar: input.pension_pillar ?? null,
    notes: input.notes ?? null,
  };
}

/**
 * Flacht FastAPI-Fehler-Details zu einem String (Monolith goalSaveErrorText):
 *  - string → unverändert
 *  - Array (422 validation) → join der `.msg`-Felder
 *  - Objekt mit `.msg` → dessen msg
 */
export function formatGoalError(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        return String((item as { msg: unknown }).msg);
      }
      return String(item);
    });
    return parts.join('; ');
  }
  if (detail && typeof detail === 'object' && 'msg' in detail) {
    return String((detail as { msg: unknown }).msg);
  }
  return 'Unbekannter Fehler beim Speichern des Ziels.';
}
