"""Archive attachment material-sidecar matching helpers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from cdmw.domain.archives.format import is_material_sidecar_extension as _is_material_sidecar_extension
from cdmw.models import ArchiveEntry, AssetFamilyGraph


class ArchiveAttachmentLooseFileMixin:
    def _attachment_package_material_sidecar_for_model(
        self,
        entry: ArchiveEntry,
        graph: AssetFamilyGraph,
        model_entry: Optional[ArchiveEntry],
    ) -> Optional[ArchiveEntry]:
        material_extensions = {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}
        model_path = str(getattr(model_entry, "path", "") or "").replace("\\", "/").strip()
        model_lower = model_path.casefold()
        model_stem = PurePosixPath(model_lower).stem.casefold()
        model_family_stem = re.sub(r"(?:_(?:r|l|in|out|[0-9]{1,2}))+$", "", model_stem)
        model_folder = PurePosixPath(model_lower).parent.as_posix().casefold()

        candidates: List[Tuple[int, int, ArchiveEntry]] = []
        seen: set[Tuple[str, str, int]] = set()
        for candidate in self._attachment_package_graph_entries(entry, graph):
            candidate_path = str(getattr(candidate, "path", "") or "").replace("\\", "/").strip()
            candidate_lower = candidate_path.casefold()
            candidate_name = PurePosixPath(candidate_lower).name
            candidate_extension = str(candidate.extension or "").lower()
            if candidate_extension not in material_extensions and not _is_material_sidecar_extension(candidate_extension, candidate_name):
                continue
            key = self._attachment_package_entry_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidate_stem = PurePosixPath(candidate_lower).stem.casefold()
            candidate_family_stem = re.sub(r"(?:_(?:r|l|in|out|[0-9]{1,2}))+$", "", candidate_stem)
            score = 20
            if model_stem and candidate_stem == model_stem:
                score += 220
            elif model_family_stem and candidate_family_stem == model_family_stem:
                score += 150
            elif model_stem and (candidate_stem.startswith(model_stem) or model_stem.startswith(candidate_stem)):
                score += 100
            if model_folder and PurePosixPath(candidate_lower).parent.as_posix().casefold().replace("/modelproperty/", "/model/") == model_folder:
                score += 70
            if "/modelproperty/" in candidate_lower:
                score += 25
            if model_lower and model_lower.replace("/model/", "/modelproperty/") in candidate_lower:
                score += 120
            candidates.append((score, len(candidates), candidate))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1]))
        best_score, _order, best_entry = candidates[0]
        return best_entry if best_score >= 45 else None


__all__ = ["ArchiveAttachmentLooseFileMixin"]
