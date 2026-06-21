"""Texture workflow breadcrumb state boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextureWorkflowBreadcrumb:
    key: str
    label: str


__all__ = ["TextureWorkflowBreadcrumb"]
