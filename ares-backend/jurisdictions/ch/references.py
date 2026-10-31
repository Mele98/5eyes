"""CH-Pack, Schritt X1: Referenzen auf die bestehenden CH-Konstanten.

Die Konstanten bleiben, wo sie sind; dieses Modul importiert sie nur, damit
die Zuordnung Pack-Bereich -> Kernkonstante statisch sichtbar und testbar ist.
``REFERENCES`` muss exakt die ``references`` aus ``ch/pack.yaml`` enthalten
(Test: tests/test_jurisdiction_pack_registry.py).

Wird von ``jurisdictions.registry``/``jurisdictions.resolve`` NICHT importiert
(kein Laufzeit-Konsument in X1, keine Zyklusgefahr fuer spaetere Konsumenten).
"""
from __future__ import annotations

from typing import Any

from schemas.clients import SWISS_CANTON_CODES
from services.advisory_log_integrity import RETENTION_YEARS
from services.data_export import RETENTION_NOTES
from services.mortality.bfs import BFS_VINTAGE_END_YEAR, BFS_VINTAGE_START_YEAR
from services.pdf.components.eignungspruefung import QUESTION_CATALOG
from services.pdf.components.footer import FIDLEG_DISCLAIMER
from services.pdf.components.static_texts import DISCLAIMER_TEXT
from services.portfolio_engine_cma import INFLATION_BASELINE_BPS
from services.portfolio_engine_pension_positions import PENSION_LUMPSUM_TAX_DEFAULT_BPS
from services.risk_assessment_semantics import OVERRIDE_DOCUMENTATION_RULES_VERSION
from services.risk_capacity_plausibility import PLAUSIBILITY_RULES_VERSION
from services.risk_scoring import (
    CANONICAL_HORIZON_LABELS,
    CAPACITY_BAND,
    CAPACITY_TOTAL_TO_PROFILE,
    HORIZON_CAPACITY_MATRIX,
    HORIZON_YEARS,
    SCORE_TO_PROFILE,
    WILLINGNESS_SCORE_TO_PROFILE,
)
from services.suitability_audit import SUITABILITY_FRESHNESS_MAX_DAYS
from services.tax.regimes.ch import CANTON_CODES

REFERENCES: dict[str, Any] = {
    "schemas.clients:SWISS_CANTON_CODES": SWISS_CANTON_CODES,
    "services.suitability_audit:SUITABILITY_FRESHNESS_MAX_DAYS": SUITABILITY_FRESHNESS_MAX_DAYS,
    "services.risk_assessment_semantics:OVERRIDE_DOCUMENTATION_RULES_VERSION": OVERRIDE_DOCUMENTATION_RULES_VERSION,
    "services.risk_scoring:SCORE_TO_PROFILE": SCORE_TO_PROFILE,
    "services.risk_scoring:CAPACITY_TOTAL_TO_PROFILE": CAPACITY_TOTAL_TO_PROFILE,
    "services.risk_scoring:WILLINGNESS_SCORE_TO_PROFILE": WILLINGNESS_SCORE_TO_PROFILE,
    "services.risk_scoring:HORIZON_YEARS": HORIZON_YEARS,
    "services.risk_scoring:CANONICAL_HORIZON_LABELS": CANONICAL_HORIZON_LABELS,
    "services.risk_scoring:CAPACITY_BAND": CAPACITY_BAND,
    "services.risk_scoring:HORIZON_CAPACITY_MATRIX": HORIZON_CAPACITY_MATRIX,
    "services.pdf.components.eignungspruefung:QUESTION_CATALOG": QUESTION_CATALOG,
    "services.risk_capacity_plausibility:PLAUSIBILITY_RULES_VERSION": PLAUSIBILITY_RULES_VERSION,
    "services.tax.regimes.ch:CANTON_CODES": CANTON_CODES,
    "services.portfolio_engine_pension_positions:PENSION_LUMPSUM_TAX_DEFAULT_BPS": PENSION_LUMPSUM_TAX_DEFAULT_BPS,
    "services.mortality.bfs:BFS_VINTAGE_START_YEAR": BFS_VINTAGE_START_YEAR,
    "services.mortality.bfs:BFS_VINTAGE_END_YEAR": BFS_VINTAGE_END_YEAR,
    "services.portfolio_engine_cma:INFLATION_BASELINE_BPS": INFLATION_BASELINE_BPS,
    "services.pdf.components.footer:FIDLEG_DISCLAIMER": FIDLEG_DISCLAIMER,
    "services.pdf.components.static_texts:DISCLAIMER_TEXT": DISCLAIMER_TEXT,
    "services.advisory_log_integrity:RETENTION_YEARS": RETENTION_YEARS,
    "services.data_export:RETENTION_NOTES": RETENTION_NOTES,
}
