"""Material-source diagnostics for a usable geometry-only archive preview."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path

from cdmw.models import ArchivePreviewResult


def native_preview_missing_texture_reason(package_path: str | Path) -> str:
    """Recognize missing sources without relaxing material ownership validation."""

    try:
        manifest = json.loads((Path(package_path) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    conservation = manifest.get("material_conservation") if isinstance(manifest, Mapping) else None
    if not isinstance(conservation, Mapping) or conservation.get("conserved") is not False:
        return ""
    findings = conservation.get("findings")
    declared = conservation.get("declared_parameter_count")
    if (
        not isinstance(findings, list)
        or not findings
        or type(declared) is not int
        or declared < 0
        or declared != conservation.get("transported_parameter_count")
        or any(not isinstance(item, str) or not item.startswith("source_dds_unavailable:") for item in findings)
    ):
        return ""
    paths = tuple(dict.fromkeys(item.rsplit(":", 1)[-1] for item in findings))
    return "Missing material textures: " + "; ".join(paths[:3])


def with_preview_material_warning(result: ArchivePreviewResult) -> ArchivePreviewResult:
    reason = str(result.native_preview_diagnostics.get("texture_preparation_error", "") or "")
    if not reason:
        return result
    warning = "Showing geometry only. " + reason
    return dataclasses.replace(
        result,
        warning_badge="Textures unavailable",
        warning_text=warning,
        detail_text=result.detail_text.rstrip() + "\n\n" + warning,
    )
