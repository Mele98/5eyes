"""Mortality-Service — BFS-Sterbetafel + Sampler fuer mortalitaetsadjustierte
Cashflow-Simulation.

Spec: docs/planning/2026-05-17-sprint-4-bfs-mortality.md
"""
from __future__ import annotations

from services.mortality.base import MortalityTable
from services.mortality.bfs import BFS_2020_2022, BFSMortalityTable
from services.mortality.sampler import sample_age_at_death

__all__ = [
    "MortalityTable",
    "BFSMortalityTable",
    "BFS_2020_2022",
    "sample_age_at_death",
]
