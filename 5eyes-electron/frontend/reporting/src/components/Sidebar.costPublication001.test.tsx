/**
 * CERT-COST-PUBLICATION-001 -- permanent repository reproducer.
 *
 * Source of truth: the Ares/Codex audit worktree
 * `C:\Users\Emanuele\Documents\ChatGPT\5eyes wird zu Ares\asset-allocation-stochastic-core`
 * (branch `codex/asset-allocation-stochastic-core`),
 * `docs/audits/2026-10-09-cost-publication-channel-delivery-artifact-certification-spec.md`,
 * finding `COST-PUBLICATION-001` (1 xfail): the backend aggregator
 * (`services/advisory_report.py:407`) adds a real, non-empty
 * `cost_disclosure` section (the FIDLEG Art. 8/9 Kostenausweis) to the
 * SAME payload used for the PDF, but the React Reporting-App never
 * surfaces it -- no TypeScript type, no top-level schema-validation
 * requirement, no route, no Sidebar entry, no render branch.
 *
 * This test exercises the REAL, unmocked `REPORT_SECTIONS` constant
 * exported by `components/Sidebar.tsx`. `App.tsx` derives its entire
 * route table directly from this array
 * (`SECTION_ROUTES = REPORT_SECTIONS.map(...)`, `App.tsx:51-55`), and
 * `renderSection()` (`App.tsx:365-463`) is a closed `if (sectionId === ...)`
 * chain with no cost branch -- so the absence documented here is not just
 * a missing nav label, it is simultaneously the missing route and the
 * missing render branch (anything not in REPORT_SECTIONS falls through to
 * `PendingSection`, a dead end, never the backend's real Kostenausweis
 * table).
 *
 * Independently re-verified against this repo's actual current `develop`
 * HEAD (717ce3ab529d53c9fb355ee2b401932829ea0054):
 *  - `api/types.ts` has no `CostDisclosureData` / `cost_disclosure` field
 *    on `AdvisoryReport` (only the unrelated `cost_disclosure_given`
 *    boolean on the AdvisoryLog schema, `api/types.ts:495`);
 *  - `api/client.ts`'s `validateSchemaV2()` `expectedKeys` list
 *    (`api/client.ts:134-160`) never requires `cost_disclosure`, so a
 *    report missing it still validates successfully;
 *  - `REPORT_SECTIONS` (asserted below) has no Kosten/cost entry.
 *
 * Do not close this by only adding `cost_disclosure` to the TypeScript
 * type (spec Section 15: "nur `cost_disclosure` zum React-Type
 * ergaenzen" is explicitly an insufficient fix) -- closure requires a
 * typed Cost-Section with Pending/Blocked/Ready states, a protected route,
 * a Sidebar entry, and currency-/null-/frequency-safe rendering per
 * spec Section 6.3.
 *
 * FIXED (CERT-COST-PUBLICATION-001, 2026-10-09): `cost_disclosure` is now a
 * full TypeScript interface (api/types.ts), a required top-level key in
 * `validateSchemaV2()` (api/client.ts), a Sidebar/`REPORT_SECTIONS` entry
 * (id 'kosten', nr 17), a route + render branch in App.tsx, and a
 * currency-/null-/frequency-safe `Kostenausweis` page component -- not
 * just the type. `test.fails` -> plain `test`: strict `test.fails` would
 * otherwise report an unexpected pass as a failure.
 */
import { describe, expect, test } from 'vitest';
import { REPORT_SECTIONS } from './Sidebar';

describe('COST-PUBLICATION-001: React navigates to and renders the protected cost disclosure', () => {
  test(
    'REPORT_SECTIONS exposes a navigable Kostenausweis entry matching the backend-protected cost_disclosure section',
    () => {
      const costSection = REPORT_SECTIONS.find(
        (section) =>
          /kosten|cost/i.test(section.id) || /kosten/i.test(section.title),
      );

      // Soll: the Reporting-App must offer a protected, navigable cost
      // page -- exactly as it does for every other backend-delivered
      // section (conflict_disclosures -> 'beratungsprotokoll' nav entry,
      // suitability_compliance -> 'compliance' nav entry, etc.).
      expect(costSection).toBeDefined();
    },
  );
});
