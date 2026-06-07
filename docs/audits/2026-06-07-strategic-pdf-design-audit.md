# Strategic PDF Design Audit - 2026-06-07

## Scope

This audit covers the customer-facing standalone PDFs for:

1. Depot-Check / target-portfolio analysis
2. Final advisory decision and customer sign-off
3. Asset Allocation detail extract
4. Backtest comparison readiness
5. Advisory protocol readiness

Existing unrelated working-tree changes were preserved.

## Depot-Check

### Before

- Four-page current-vs-target drift report.
- Current holdings, target holdings and exposure diagnostics mixed together.
- Three small donuts compressed country, sector and currency information.
- Costs, benchmark performance and a target-only qualitative conclusion were absent.

### After

- Eleven-page target-only analysis.
- Current-vs-target drift is not rendered in the customer document.
- Separate pages for:
  - main asset classes and strategic bands
  - subasset classes
  - country allocation
  - sector allocation
  - currency allocation
  - risk and historical stress scenarios
  - diversification and concentration
  - ex-ante costs
  - historical performance versus strategic benchmark
  - qualitative assessment and methodology
- Existing target exposure, recommendation, cost and backtest services remain the data sources.
- Missing cost or performance data degrades to an explicit pending state instead of crashing.

## Advisory Sign-Off

### New document

Endpoint:

`GET /mandates/{mandate_id}/reports/contract-signoff.pdf`

Seven pages:

1. Cover
2. Risk profile, selected strategy and override status
3. Target allocation and min/max bands
4. Subasset classes and portfolio orientation
5. Consultation summary and final recommendation
6. FIDLEG/revDSG acknowledgements
7. Customer and advisor signatures

The override reason is printed when an override exists. The no-override state
is also explicit. Signature wording documents suitability, costs, risks,
conflicts and the absence of performance guarantees.

## Asset Allocation

The standalone extract now contains:

- visual target allocation
- written structure explanation
- target weight per main asset class
- band minimum and maximum
- target amount
- separate subasset-class detail page

The report remains a focused extract and does not duplicate risk-profile or
portfolio-product pages.

## Conditional Items

### Backtest KPI

The current backtest contract contains portfolio and benchmark metrics but no
separate gross/net return series. A gross/net comparison table would therefore
invent data. The PDF change remains gated until the backend provides explicit
gross and net metrics. The existing historical chart and metric table remain
unchanged.

### Advisory Protocol Blocks

The database supports structured FINMA fields, but the current main-app save
payload still submits the legacy title/description/decision fields. No stable
block-menu payload is available yet. The final block-based PDF remains gated
until that UI contract is persisted end to end.

## Verification

- `tests/pdf/`: 153 passed
- PDF integration suites: 114 passed
- `git diff --check`: passed
- Synthetic render results:
  - Depot-Check: 11 pages, no drift section, no spill page
  - Advisory sign-off: 7 pages, dedicated signature page
  - Asset Allocation: 4 pages, main allocation table no longer spills
- Real-data render against a migrated copy of `MX-FOUNDATION-01`:
  - Depot-Check: exactly 11 A4 landscape pages
  - 12 country rows, 12 sector rows and 9 target positions remain on their
    dedicated section pages
  - no continuation pages without a section header and no clipped body content

Focused drift tests:

- `tests/pdf/test_depotcheck_soll_analysis.py`
- `tests/pdf/test_contract_signoff.py`
- updated Asset Allocation assertions in `tests/pdf/test_renderer.py`
- dense Depot-Check regression requiring exactly 11 pages

## Residual Review

The integrated browser preview was unavailable in this session. PDFs were
rendered through ReportLab and inspected through page rasterization, text-block
bounds, page counts and extracted structural anchors. The Depot-Check was also
rendered from a migrated copy of the real Foundation mandate. Final human
approval of typography and print colour should still use the application print
flow once the local preview connection is available.

A complete `tests/` run was also attempted. It was not a valid release signal
in the sandbox because many unrelated API fixtures started the application
against `C:\Users\Emanuele\5eyes\5eyes.db`; schema bootstrap then failed with
`sqlite3.OperationalError: attempt to write a readonly database`. The focused
PDF and PDF-integration suites above were rerun separately and passed.
