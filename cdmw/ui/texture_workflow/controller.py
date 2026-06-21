"""Texture workflow interaction coordinator boundary."""

from __future__ import annotations


class TextureWorkflowController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context


__all__ = ["TextureWorkflowController"]
