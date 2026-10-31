"""Equity-Bewertungs-Modelle (KGV-Mean-Reversion, Shiller-CAPE, etc.).

Spec: docs/planning/2026-05-17-sprint-7-kgv-mean-reversion.md
"""
from __future__ import annotations

from services.equity_valuation.mean_reversion import KGVMeanReversionModel

__all__ = ["KGVMeanReversionModel"]
