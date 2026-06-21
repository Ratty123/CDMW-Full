"""Mesh editor action descriptors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeshEditorAction:
    key: str
    text: str


__all__ = ["MeshEditorAction"]
