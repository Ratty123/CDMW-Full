"""Archive browser attachment-package loose file helpers."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from cdmw.core.archive import _is_material_sidecar_extension
from cdmw.core.archive_modding import MeshImportSupplementalFileSpec
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

    @staticmethod
    def _attachment_package_path_is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _attachment_package_raw_extract_root(self) -> Optional[Path]:
        widget = getattr(self, "archive_extract_root_edit", None)
        raw = widget.text().strip() if widget is not None else ""
        if not raw:
            return None
        try:
            path = Path(raw).expanduser().resolve()
        except OSError:
            return None
        return path if path.is_dir() else None

    def _attachment_package_output_loose_roots(self) -> List[Path]:
        roots: List[Path] = []
        seen: set[str] = set()

        def add_root(raw: object) -> None:
            if raw is None:
                return
            try:
                path = Path(str(raw)).expanduser().resolve()
            except OSError:
                return
            if not path.is_dir():
                return
            key = str(path).casefold()
            if key in seen:
                return
            seen.add(key)
            roots.append(path)

        output_widget = getattr(self, "output_root_edit", None)
        output_root = output_widget.text().strip() if output_widget is not None else ""
        add_root(output_root)
        return roots

    def _attachment_package_loose_target_roots_for_entry(self, entry: ArchiveEntry) -> List[Path]:
        normalized = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lstrip("/")
        if normalized.casefold().startswith("files/"):
            normalized = normalized[6:]
        if not normalized:
            return []
        roots: List[Path] = []
        seen: set[str] = set()
        raw_extract_root = self._attachment_package_raw_extract_root()

        def has_target_file(root: Path) -> bool:
            return (root / "files").joinpath(*PurePosixPath(normalized).parts).is_file() or root.joinpath(*PurePosixPath(normalized).parts).is_file()

        def looks_like_raw_archive_extract_chunk(root: Path) -> bool:
            try:
                resolved = root.expanduser().resolve()
            except OSError:
                return False
            return bool(
                re.fullmatch(r"\d{4}", resolved.name)
                and resolved.parent.name.strip().casefold() == "archive_extract"
            )

        def add_root(root: Path) -> None:
            try:
                resolved = root.expanduser().resolve()
            except OSError:
                return
            if raw_extract_root is not None and self._attachment_package_path_is_relative_to(resolved, raw_extract_root):
                return
            if looks_like_raw_archive_extract_chunk(resolved):
                return
            key = str(resolved).casefold()
            if key in seen or not resolved.is_dir() or not has_target_file(resolved):
                return
            seen.add(key)
            roots.append(resolved)

        for base_root in self._attachment_package_output_loose_roots():
            add_root(base_root)
            try:
                children = [child for child in base_root.iterdir() if child.is_dir()]
            except OSError:
                children = []
            for child in children:
                add_root(child)

        current_preview = getattr(self, "current_archive_preview_result", None)
        loose_file_path = str(getattr(current_preview, "loose_file_path", "") or "").strip()
        if loose_file_path:
            try:
                loose_file = Path(loose_file_path).expanduser().resolve()
            except OSError:
                loose_file = Path()
            if loose_file.is_file():
                for parent in loose_file.parents:
                    add_root(parent.parent if parent.name.casefold() == "files" else parent)

        roots.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
        return roots

    def _attachment_package_loose_target_specs(
        self,
        target_entry: ArchiveEntry,
        target_graph: AssetFamilyGraph,
        loose_root: Optional[Path],
    ) -> Tuple[MeshImportSupplementalFileSpec, ...]:
        if not isinstance(loose_root, Path) or not loose_root.exists():
            return ()
        files_root = loose_root / "files" if (loose_root / "files").is_dir() else loose_root
        specs: List[MeshImportSupplementalFileSpec] = []
        seen: set[str] = set()

        def normalize_virtual(raw_path: object) -> str:
            normalized = str(raw_path or "").replace("\\", "/").strip().lstrip("/")
            if normalized.casefold().startswith("files/"):
                normalized = normalized[6:]
            return normalized

        def local_path_for_virtual(virtual_path: str) -> Optional[Path]:
            normalized = normalize_virtual(virtual_path)
            if not normalized:
                return None
            relative = PurePosixPath(normalized)
            for root in (files_root, loose_root):
                candidate = root.joinpath(*relative.parts)
                if candidate.is_file():
                    return candidate
            return None

        def add_virtual(virtual_path: object, kind: str) -> Optional[Path]:
            normalized = normalize_virtual(virtual_path)
            if not normalized:
                return None
            key = normalized.casefold()
            if key in seen:
                return local_path_for_virtual(normalized)
            local_path = local_path_for_virtual(normalized)
            if local_path is None:
                return None
            seen.add(key)
            target = self._find_archive_entry_by_virtual_path(normalized)
            specs.append(
                MeshImportSupplementalFileSpec(
                    source_path=local_path,
                    target_path=normalized,
                    kind=kind,
                    target_entry=target if isinstance(target, ArchiveEntry) else None,
                    note=f"Preserve existing target loose file from {loose_root.name}.",
                )
            )
            return local_path

        def kind_for_support_action(action: object) -> str:
            normalized_action = str(action or "").casefold()
            if "prefab" in normalized_action:
                return "placement_target_prefab"
            if "hkx" in normalized_action or "hkt" in normalized_action or "physics" in normalized_action:
                return "placement_target_physics"
            if "paa" in normalized_action or "motion" in normalized_action:
                return "placement_target_motion"
            if "socket" in normalized_action:
                return "placement_target_socket"
            if "icon" in normalized_action:
                return "placement_target_icon"
            if "material" in normalized_action:
                return "placement_target_material"
            if "pac" in normalized_action or "model" in normalized_action:
                return "placement_target_model"
            return "placement_target_support"

        def add_local_path(local_path: Path, kind: str) -> None:
            try:
                if self._attachment_package_path_is_relative_to(local_path, files_root):
                    relative = local_path.resolve().relative_to(files_root.resolve())
                else:
                    relative = local_path.resolve().relative_to(loose_root.resolve())
            except (OSError, ValueError):
                return
            normalized = PurePosixPath(*relative.parts).as_posix().lstrip("/")
            if normalized.casefold().startswith("files/"):
                normalized = normalized[6:]
            key = normalized.casefold()
            if not normalized or key in seen:
                return
            seen.add(key)
            target = self._find_archive_entry_by_virtual_path(normalized)
            specs.append(
                MeshImportSupplementalFileSpec(
                    source_path=local_path,
                    target_path=normalized,
                    kind=kind,
                    target_entry=target if isinstance(target, ArchiveEntry) else None,
                    note=f"Preserve target-owned loose support file from {loose_root.name}.",
                )
            )

        target_path = normalize_virtual(target_entry.path)
        target_stem = PurePosixPath(target_path).stem
        add_virtual(target_path, "placement_target_model")

        sidecar_paths: List[str] = []
        if target_entry.extension in {".pac", ".pam", ".pamlod"}:
            sidecar_paths.append(target_path.replace("/model/", "/modelproperty/") + "_xml")
        target_model = self._attachment_visual_model_entry(target_entry, target_graph)
        sidecar_entry = self._attachment_package_material_sidecar_for_model(target_entry, target_graph, target_model)
        if isinstance(sidecar_entry, ArchiveEntry):
            sidecar_paths.append(sidecar_entry.path)
        sidecar_local_paths: List[Path] = []
        for sidecar_path in tuple(dict.fromkeys(sidecar_paths)):
            local = add_virtual(sidecar_path, "placement_target_material")
            if isinstance(local, Path):
                sidecar_local_paths.append(local)

        texture_pattern = re.compile(
            r"""(?:_path|path)\s*=\s*["'](?P<path>[^"']+\.(?:dds|png))["']""",
            re.IGNORECASE,
        )
        for sidecar_path in sidecar_local_paths:
            try:
                text = sidecar_path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            for match in texture_pattern.finditer(text):
                add_virtual(match.group("path"), "placement_target_texture")

        for icon_entry in self._attachment_package_item_icon_entries(target_entry, target_graph):
            add_virtual(icon_entry.path, "placement_target_icon")
        for icon_basename in (
            f"itemicon_prefab_{target_stem}.dds",
            f"itemicon_{target_stem}.dds",
            f"icon_prefab_{target_stem}.dds",
            f"icon_{target_stem}.dds",
        ):
            add_virtual(f"ui/texture/icon/{icon_basename}", "placement_target_icon")

        for action, support_entry, _note in self._attachment_package_target_support_entries(target_entry, target_graph):
            if isinstance(support_entry, ArchiveEntry):
                add_virtual(support_entry.path, kind_for_support_action(action))

        support_extensions = {
            ".prefab",
            ".hkx",
            ".hkt",
            ".paa",
            ".paa_metabin",
            ".motionblending",
            ".sockets.xml",
        }
        target_stem_key = target_stem.casefold()
        try:
            loose_files = list(files_root.rglob("*"))
        except OSError:
            loose_files = []
        for local_candidate in loose_files:
            if not local_candidate.is_file():
                continue
            candidate_name = local_candidate.name.casefold()
            candidate_stem = PurePosixPath(candidate_name).stem.casefold()
            suffix_key = ".sockets.xml" if candidate_name.endswith(".sockets.xml") else local_candidate.suffix.casefold()
            if suffix_key not in support_extensions:
                continue
            if (
                candidate_stem != target_stem_key
                and not candidate_stem.startswith(f"{target_stem_key}_")
                and not candidate_name.startswith(f"{target_stem_key}.")
            ):
                continue
            add_local_path(local_candidate, kind_for_support_action(suffix_key))

        return tuple(specs)
