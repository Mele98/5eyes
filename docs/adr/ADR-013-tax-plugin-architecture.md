# ADR-013: Tax Plugin Architecture

Status: Accepted
Date: 2026-06-19

## Context

5eyes needs a tax layer that can support Switzerland today and additional
countries later without changing optimizer core code for every jurisdiction.
The existing `TaxRegime` interface is optimizer-facing and path-level. It is
kept intact for backwards compatibility.

The new requirement is a read-only advisory/API layer:

- deterministic tax estimates for client profiles
- country plugins registered by strategy/registry pattern
- Switzerland as reference implementation
- global reference parameters, not tenant data
- no wiring into the optimizer objective in this PR

## Decision

We introduce a second interface, `TaxJurisdiction`, for country-level estimates.
It lives next to the existing `TaxRegime` contract and does not replace it.

Core pieces:

- `schemas.tax.TaxProfileInput`
- `schemas.tax.TaxEstimateResult`
- `services.tax.base.TaxJurisdiction`
- `services.tax.registry.register_jurisdiction`
- `services.tax.registry.get_jurisdiction`
- `services.tax.jurisdictions.ch.SwissTaxJurisdiction`
- `models.tax.TaxParameterSet`
- `routers.tax` read-only estimate endpoints
- `services.tax.after_tax.get_after_tax_return` as the future #90 adapter

Tax reference data is global. It contains no client data and is therefore
tenant-agnostic. Switzerland ships with conservative canton-level reference
parameters. Missing regions fall back to a conservative CH estimate and disclose
that in `assumptions[]`.

## Consequences

Positive:

- New countries can be added as plugins without touching the optimizer.
- The API returns transparent assumptions and deterministic results.
- Existing `TaxRegime` optimizer tests remain valid.
- SQLite remains supported through additive SQLAlchemy models.
- The future after-tax optimizer work has a documented, tested adapter.

Trade-offs:

- The Switzerland plugin is an advisory estimate, not an exact municipal tax
  filing calculator.
- Canton/municipality precision must be improved by adding parameter data, not
  by embedding ad-hoc logic in portfolio construction.
- Dividends, interest, withholding tax and product wrapper effects are not yet
  part of the after-tax adapter because the optimizer does not yet provide
  return decomposition.

## Extension Pattern

To add a country:

1. Add a module under `services/tax/jurisdictions/`.
2. Implement `TaxJurisdiction`.
3. Register it with `@register_jurisdiction`.
4. Add reference parameter sets if needed.
5. Add deterministic tests for known examples and assumptions.

No change to `services/optimizer/*` or `services/portfolio_engine.py` is needed
until the explicit #90 integration sprint.

