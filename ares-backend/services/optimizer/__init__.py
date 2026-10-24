"""Goal-Based Stochastic Optimizer (Mulvey/Ziemba-light).

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md

Phasen-Plan:
1. Foundation (this directory) - distributions, goal_liabilities, audit_trace
2. Engine - vectorized scenario generator (NumPy)
3. Solver - SLSQP + multi-start over bucket weights
4. Integration - feature-flag dispatch in portfolio_engine

Nicht-Scope (Phase 1): Solver, Engine, Integration. Hier nur die Bausteine
fuer Distributions und Goal->Liability-Konversion.
"""
from __future__ import annotations

__all__ = [
    "OPTIMIZER_VERSION",
]

OPTIMIZER_VERSION = "0.1.0"
