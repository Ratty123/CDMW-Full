"""Profiles supported by the shared .NET/Vortice preview helper."""

from __future__ import annotations

from enum import Enum


class DotNetPreviewProfile(str, Enum):
    PREVIEW = "preview"
    AUTHORING = "authoring"

    @classmethod
    def normalize(cls, value: object) -> "DotNetPreviewProfile":
        if isinstance(value, cls):
            return value
        normalized = str(value or cls.PREVIEW.value).strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(".NET preview profile must be preview or authoring.") from exc


__all__ = ["DotNetPreviewProfile"]
