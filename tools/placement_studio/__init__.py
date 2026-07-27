"""Placement & Animation Studio — Phase 0 ground-truth harness.

Phase 0 proves the operation vocabulary before any UI exists: every known-good mod
under the golden corpus must be expressible as an operation list, and replaying that
list against pinned vanilla bytes must reproduce the shipped mod byte-for-byte.

See docs/plans/active/placement-and-animation-studio.md.
"""

from __future__ import annotations

__all__ = ["PHASE"]

PHASE = 0
