/**
 * U-1 (A3 P1-1): Typ-Abgleich handgeschriebener API-Typen gegen die aus
 * `api/openapi.json` generierten Schemas.
 *
 * Reiner Compile-Zeit-Test: `tsc --noEmit` (Teil von `npm run build` und
 * damit des CI-Jobs "Frontend Reporting Tests") prueft diese Datei. Vitest
 * sammelt sie nicht (Endung `.test-d.ts`), und nichts importiert sie, sie
 * landet also nicht im Bundle.
 *
 * Richtung:
 *  - Antworten: generiertes Schema muss dem handgeschriebenen Typ genuegen
 *    (was der Server sendet, muss der Client-Typ abdecken).
 *  - Requests: handgeschriebener Payload muss dem generierten Schema genuegen
 *    (was der Client sendet, muss der Server annehmen).
 *
 * Bekannte Abweichungen stehen unter `@ts-expect-error` mit Begruendung.
 * Wird eine davon behoben, meldet tsc die unbenutzte Direktive; dann die
 * Zeile auf eine normale Zusicherung umstellen. Neue Abweichungen machen den
 * Build rot.
 */
import type {
  AdvisoryLogCreatePayload,
  AdvisoryParticipant,
} from './advisoryLog';
import type { ReportNotes, ReportNotesUpdate } from './reportNotes';
import type { ApiRequest, ApiResponse } from './schema';
import type * as T from './types';

type Assert<Ok extends true> = Ok;
type Assignable<From, To> = [From] extends [To] ? true : false;
/** Request-Felder, die das Server-Schema nicht kennt (Pydantic verwirft sie stillschweigend). */
type NoUnknownFields<Payload, Schema> = [Exclude<keyof Payload, keyof Schema>] extends [never]
  ? true
  : false;
/** Payload passt zum Schema: zuweisbar und ohne Felder, die der Server verwirft. */
type RequestFits<Payload, Schema> = Assignable<Payload, Schema> extends true
  ? NoUnknownFields<Payload, Schema>
  : false;

// ---------------------------------------------------------------------------
// Abgeloester Bereich (Aliase auf generierte Typen): Selbstkontrolle.
// ---------------------------------------------------------------------------
export type MandateAliases = [
  Assert<Assignable<ApiResponse<'MandateResponse'>, T.MandateRecord>>,
  Assert<RequestFits<T.MandateCreatePayload, ApiRequest<'MandateCreate'>>>,
  Assert<RequestFits<T.MandateUpdatePayload, ApiRequest<'MandateUpdate'>>>,
  Assert<Assignable<ApiResponse<'ClientResponse'>, T.ClientRecord>>,
  Assert<RequestFits<T.ClientCreatePayload, ApiRequest<'ClientCreate'>>>,
  Assert<RequestFits<T.ClientUpdatePayload, ApiRequest<'ClientUpdate'>>>,
  Assert<Assignable<ApiResponse<'NationalityResponse'>, T.NationalityRecord>>,
];

// ---------------------------------------------------------------------------
// Noch handgeschrieben: Antworten (generiert -> handgeschrieben).
// ---------------------------------------------------------------------------
export type ResponsesCompatible = [
  Assert<Assignable<ApiResponse<'OptHistoryResponse'>, T.OptHistoryRecord>>,
  Assert<Assignable<ApiResponse<'GoalResponse'>, T.GoalRecord>>,
  Assert<Assignable<ApiResponse<'CashflowResponse'>, T.CashflowRecord>>,
  Assert<Assignable<ApiResponse<'TargetAllocationResponse'>, T.TargetAllocationRecord>>,
  Assert<Assignable<ApiResponse<'MaxPensionSpendingResponse'>, T.MaxPensionSpendingResponse>>,
  Assert<Assignable<ApiResponse<'ReportNotesResponse'>, ReportNotes>>,
  Assert<Assignable<ApiResponse<'TargetAllocationGenerateResponse'>, T.AllocationGenerateResult>>,
];

// U1-D1: WealthInflowResponse.certainty ist im Schema `string`, der
// handgeschriebene Typ verengt auf 'sicher' | 'unsicher'.
// @ts-expect-error U1-D1 bekannte Abweichung
export type D1 = Assert<Assignable<ApiResponse<'WealthInflowResponse'>, T.WealthInflowRecord>>;

// U1-D2: AllocationSensitivityResponse.target_amount_rappen_baseline/_new
// sind im Schema `number | null`, handgeschrieben nur `number`
// (laufzeitrelevant: ein `null` vom Server ist im Client-Typ nicht vorgesehen).
// @ts-expect-error U1-D2 bekannte Abweichung
export type D2 = Assert<Assignable<ApiResponse<'AllocationSensitivityResponse'>, T.AllocationSensitivityResult>>;

// U1-D3: AdvisoryParticipant.note ist im Schema `string | null`,
// handgeschrieben `string | undefined`.
// @ts-expect-error U1-D3 bekannte Abweichung
export type D3 = Assert<Assignable<ApiResponse<'AdvisoryParticipant'>, AdvisoryParticipant>>;

// ---------------------------------------------------------------------------
// Noch handgeschrieben: Requests (handgeschrieben -> generiert).
// ---------------------------------------------------------------------------
export type RequestsCompatible = [
  Assert<RequestFits<T.OptHistoryCreatePayload, ApiRequest<'OptHistoryCreate'>>>,
  Assert<RequestFits<T.GoalCreatePayload, ApiRequest<'GoalCreate'>>>,
  Assert<RequestFits<T.GoalUpdatePayload, ApiRequest<'GoalUpdate'>>>,
  Assert<RequestFits<T.CashflowCreatePayload, ApiRequest<'CashflowCreate'>>>,
  Assert<RequestFits<T.CashflowUpdatePayload, ApiRequest<'CashflowUpdate'>>>,
  Assert<RequestFits<T.WealthInflowCreatePayload, ApiRequest<'WealthInflowCreate'>>>,
  Assert<RequestFits<T.WealthInflowUpdatePayload, ApiRequest<'WealthInflowUpdate'>>>,
  Assert<RequestFits<T.TargetAllocationCreatePayload, ApiRequest<'TargetAllocationCreate'>>>,
  Assert<RequestFits<T.AllocationSensitivityRequestPayload, ApiRequest<'AllocationSensitivityRequest'>>>,
  Assert<RequestFits<T.MaxPensionSpendingRequest, ApiRequest<'MaxPensionSpendingRequest'>>>,
  Assert<RequestFits<ReportNotesUpdate, ApiRequest<'ReportNotesUpdate'>>>,
];

// U1-D4: AdvisoryLogCreatePayload.decision ist handgeschrieben `string`,
// das Schema erlaubt nur die AdvisoryDecision-Werte (reine Typ-Weite).
// @ts-expect-error U1-D4 bekannte Abweichung
export type D4 = Assert<Assignable<AdvisoryLogCreatePayload, ApiRequest<'AdvisoryLogCreate'>>>;

// U1-D5 (behoben durch #838): AdvisoryLogCreatePayload sendet keine dem
// Server unbekannten Felder mehr; AdvisoryLogCreate lehnt unbekannte Felder
// ab (extra="forbid"). Diese Pruefung haelt das fest.
export type D5 = Assert<NoUnknownFields<AdvisoryLogCreatePayload, ApiRequest<'AdvisoryLogCreate'>>>;
