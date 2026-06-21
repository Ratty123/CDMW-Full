"""Mesh editor workflow coordinator boundary."""

from __future__ import annotations


class MeshEditorController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context


__all__ = ["MeshEditorController"]
