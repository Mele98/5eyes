from fastapi import HTTPException

from config import settings


PHASE_ZERO_BLOCK_DETAIL = "Phase-0: nur synthetische Daten erlaubt"


def enforce_data_classification(data_classification: str | None) -> None:
    """Reject writes explicitly marked as real while Phase 0 is active."""
    classification = data_classification or "synthetic"
    if not settings.allow_real_client_data and classification == "real":
        raise HTTPException(status_code=403, detail=PHASE_ZERO_BLOCK_DETAIL)
