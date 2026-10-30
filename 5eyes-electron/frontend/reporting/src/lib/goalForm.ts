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
 *
 * GOAL-RECURRING-EDITOR-CONTRACT-001 (Frontend-Teil): wiederkehrende und
 * Pensionsziele brauchen Betrag, Frequenz, Startdatum und genau eine
 * Endsemantik (laufend ODER Enddatum) — wie services/goal_semantics.py und
 * routers/wealth.py:_normalize_goal_payload. Kein stiller Default-Horizont.
 * Fehler tragen das betroffene Feld (`GoalFieldError`), damit der Wizard sie
 * am Feld anzeigen kann; 422-Antworten der API ordnet
 * `goalFieldErrorsFromApi` ebenso feldgenau zu.
 */
import { formatApiErrorDetail } from '@/api/client';
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

/**
 * Obergrenze fuer Rappen-Betraege im Client. Das Backend deckelt bei INT64
 * (MAX_PERSISTABLE_RAPPEN); JS-Zahlen sind oberhalb von 2^53 - 1 nicht mehr
 * exakt, ein groesserer Wert koennte also nicht unverfaelscht gesendet werden.
 */
export const MAX_GOAL_RAPPEN = Number.MAX_SAFE_INTEGER;

/** Wiederkehrende Frequenzen (Backend SUPPORTED_FREQUENCIES ohne "einmalig"). */
const RECURRING_FREQUENCY_KEYS = new Set(['monatlich', 'quartalsweise', 'halbjaehrlich', 'jaehrlich']);

function isStreamTypeKey(key: string): boolean {
  return key === 'wiederkehrende_ausgabe' || key === 'pensionsausgabe';
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

export type GoalFormField = keyof GoalFormInput;

/** Ein Validierungsfehler; `field` = betroffenes Eingabefeld oder null (allgemein). */
export interface GoalFieldError {
  field: GoalFormField | null;
  message: string;
}

/**
 * Clientseitige Feld-Isolation, 1:1 zu _validate_goal_field_isolation
 * (require_targets=true), plus der Strom-Vertrag aus goal_semantics.py.
 * Leeres Array = gültig.
 */
export function validateGoalFormFields(input: GoalFormInput): GoalFieldError[] {
  const errors: GoalFieldError[] = [];
  const push = (field: GoalFormField | null, message: string): void => {
    errors.push({ field, message });
  };
  const key = goalTypeKey(input.goal_type);
  const hk = hardnessKey(input.hardness);

  if (!input.label || !input.label.trim()) {
    push('label', 'Bezeichnung ist erforderlich.');
  }
  if (!(typeof input.rank === 'number' && input.rank >= 1)) {
    push('rank', 'Rang muss mindestens 1 sein.');
  }
  if (hk && !['hart', 'primaer', 'opportunistisch'].includes(hk)) {
    push('hardness', "hardness muss 'Hart', 'Primär' oder 'Opportunistisch' sein");
  }

  const forbid = (...fields: GoalFormField[]): void => {
    for (const field of fields) {
      if (hasValue(input[field])) {
        push(field, `Feld '${field}' ist für Zieltyp '${input.goal_type}' nicht erlaubt`);
      }
    }
  };

  // Gesetzter Betrag: positive ganze Rappen unter der Obergrenze.
  const checkAmount = (field: 'target_amount_rappen' | 'target_wealth_rappen'): void => {
    const value = input[field];
    if (!hasValue(value)) return;
    if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) {
      push(field, 'Betrag muss eine positive Zahl sein.');
    } else if (value > MAX_GOAL_RAPPEN) {
      push(field, 'Betrag übersteigt die zulässige Obergrenze.');
    }
  };

  if (key === 'renditeziel') {
    forbid('target_amount_rappen', 'target_wealth_rappen', 'frequency');
    if (hk === 'hart') {
      push('hardness', "Renditeziel darf nicht als 'hart' definiert werden.");
    }
    if (!hasValue(input.target_return_bps)) {
      push('target_return_bps', 'Renditeziel benötigt target_return_bps');
    }
  } else if (key === 'einmalige_ausgabe') {
    forbid('target_return_bps', 'target_wealth_rappen', 'frequency');
    if (!hasValue(input.target_amount_rappen)) {
      push('target_amount_rappen', 'Einmalige_Ausgabe benötigt target_amount_rappen');
    }
    checkAmount('target_amount_rappen');
    if (!(hasValue(input.target_date) || hasValue(input.horizon_years))) {
      push('target_date', 'Einmalige_Ausgabe benötigt target_date oder horizon_years');
    }
  } else if (isStreamTypeKey(key)) {
    forbid('target_return_bps', 'target_wealth_rappen');
    if (!hasValue(input.frequency)) {
      push('frequency', 'Cashflow-Ziel benötigt frequency');
    } else if (!RECURRING_FREQUENCY_KEYS.has(hardnessKey(input.frequency))) {
      push('frequency', 'Häufigkeit muss monatlich, quartalsweise, halbjährlich oder jährlich sein.');
    }
    if (!hasValue(input.target_amount_rappen)) {
      push('target_amount_rappen', 'Wiederkehrendes Ziel benötigt einen positiven Betrag.');
    }
    checkAmount('target_amount_rappen');
    // Kein stiller Default-Horizont: der Strom braucht einen expliziten Beginn.
    if (!hasValue(input.start_date)) {
      push('start_date', 'Wiederkehrendes Ziel benötigt ein Startdatum.');
    }
    // Genau eine Endsemantik: laufend ODER Enddatum.
    if (input.is_ongoing && hasValue(input.target_date)) {
      push('target_date', 'Ein laufendes Ziel darf kein Enddatum haben.');
    } else if (!input.is_ongoing && !hasValue(input.target_date)) {
      push('target_date', 'Ein endliches wiederkehrendes Ziel benötigt ein Enddatum (sonst "laufend" wählen).');
    } else if (
      hasValue(input.start_date)
      && hasValue(input.target_date)
      && String(input.target_date) < String(input.start_date)
    ) {
      push('target_date', 'Enddatum darf nicht vor dem Startdatum liegen.');
    }
  } else if (key === 'kapitalerhalt' || key === 'vermoegensziel') {
    forbid('target_return_bps', 'target_amount_rappen', 'frequency');
    if (!hasValue(input.target_wealth_rappen)) {
      push('target_wealth_rappen', 'Vermögensziel benötigt target_wealth_rappen');
    }
    checkAmount('target_wealth_rappen');
    if (!(hasValue(input.target_date) || hasValue(input.horizon_years))) {
      push('target_date', 'Vermögensziel benötigt target_date oder horizon_years');
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

/** Wie `validateGoalFormFields`, nur die Meldungen (bestehende Aufrufer). */
export function validateGoalForm(input: GoalFormInput): string[] {
  return validateGoalFormFields(input).map((e) => e.message);
}

/**
 * Baut den POST/PUT-Payload: genau EIN Target-Feld gesetzt (Rest null).
 * value_mode wird bei Zieltypen mit Betrag (Vermögen + Cashflow) aus der
 * Eingabe übernommen (GOAL-VALUE-MODE-ROUNDTRIP-001), sonst "nominal".
 * Härte kommt nie aus dem Rang (Rang/Härte getrennt); Default "Primär" wie
 * im Backend. Laufende Ströme senden kein Enddatum.
 * data_classification immer "synthetic".
 */
export function buildGoalPayload(input: GoalFormInput): GoalCreatePayload {
  const goalType = input.goal_type;
  const key = goalTypeKey(goalType);
  const wealth = isWealthType(goalType);
  const isStream = isStreamTypeKey(key);
  const isCashflow = key === 'einmalige_ausgabe' || isStream;
  const isOngoing = isStream ? (input.is_ongoing ?? false) : false;

  return {
    goal_family: familyForType(goalType),
    goal_type: goalType,
    label: input.label.trim(),
    rank: input.rank,
    goal_scope: input.goal_scope ?? 'Beratungsvermögen',
    value_mode: wealth || isCashflow ? (input.value_mode ?? 'nominal') : 'nominal',
    hardness: input.hardness ?? 'Primär',
    probability_pct: input.probability_pct ?? 100,
    is_ongoing: isOngoing,
    data_classification: 'synthetic',
    target_amount_rappen: isCashflow ? (input.target_amount_rappen ?? null) : null,
    target_wealth_rappen: wealth ? (input.target_wealth_rappen ?? null) : null,
    target_return_bps: key === 'renditeziel' ? (input.target_return_bps ?? null) : null,
    frequency: isStream ? (input.frequency ?? null) : null,
    target_date: isOngoing ? null : (input.target_date ?? null),
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
  // Delegiert an den zentralen Formatter (api/client.ts).
  return formatApiErrorDetail(detail, 'Unbekannter Fehler beim Speichern des Ziels.');
}

// Feldzuordnung fuer Meldungstexte der API; massgebend ist die frueheste
// Fundstelle in der Meldung.
const API_FIELD_PATTERNS: Array<[GoalFormField, RegExp]> = [
  ['target_date', /target_date|enddatum|zieldatum/i],
  ['start_date', /start_date|startdatum/i],
  ['frequency', /frequency|frequenz|häufigkeit/i],
  ['target_amount_rappen', /target_amount_rappen|zielbetrag|\bbetrag\b/i],
  ['target_wealth_rappen', /target_wealth_rappen|zielverm(ö|oe)gen/i],
  ['target_return_bps', /target_return_bps|zielrendite/i],
  ['horizon_years', /horizon_years|zeithorizont/i],
  ['pension_pillar', /pension_pillar|s(ä|ae)ule/i],
  ['probability_pct', /probability_pct|eintrittswahrscheinlichkeit/i],
  ['value_mode', /value_mode|wertbasis/i],
  ['hardness', /hardness|h(ä|ae)rte|\bhart\b/i],
  ['rank', /\brank\b|\brang\b/i],
  ['label', /\blabel\b|bezeichnung/i],
  ['is_ongoing', /is_ongoing/i],
];

const API_FIELDS = new Set<string>(API_FIELD_PATTERNS.map(([field]) => field));

function fieldFromMessage(message: string): GoalFormField | null {
  let best: GoalFormField | null = null;
  let bestIndex = Number.POSITIVE_INFINITY;
  for (const [field, pattern] of API_FIELD_PATTERNS) {
    const idx = message.search(pattern);
    if (idx >= 0 && idx < bestIndex) {
      best = field;
      bestIndex = idx;
    }
  }
  return best;
}

function fieldFromLoc(item: unknown): GoalFormField | null {
  if (!item || typeof item !== 'object') return null;
  const loc = (item as { loc?: unknown }).loc;
  if (!Array.isArray(loc)) return null;
  for (let i = loc.length - 1; i >= 0; i -= 1) {
    const part = loc[i];
    if (typeof part === 'string' && API_FIELDS.has(part)) {
      return part as GoalFormField;
    }
  }
  return null;
}

/**
 * Ordnet ein FastAPI-Fehler-`detail` (422) den Formularfeldern zu:
 *  - Pydantic-Array: Feld aus `loc`, sonst aus dem Meldungstext;
 *  - String/Objekt: Feld aus dem Meldungstext (Feldname oder Fachbegriff).
 * Nicht zuordenbare Fehler bekommen `field: null` (allgemeiner Fehler).
 */
export function goalFieldErrorsFromApi(detail: unknown): GoalFieldError[] {
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => {
      const message = formatGoalError([item]);
      return { field: fieldFromLoc(item) ?? fieldFromMessage(message), message };
    });
  }
  const message = formatGoalError(detail);
  return [{ field: fieldFromMessage(message), message }];
}
