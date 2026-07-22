"""Native preview-core helpers for archive preview workers."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import time
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtGui import QImageReader

from cdmw.core.archive import build_archive_asset_family_graph, build_archive_entry_metadata_summary
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ArchivePreviewResult,
    AssetFamilyGraph,
    AssetFamilyMember,
    AssetRelation,
    RelationConfidence,
    RelationKind,
    RunCancelled,
)
from cdmw.rendering.native_preview_core import (
    NativePreviewCoreAttempt,
    render_settings_to_native_preview_core_dict,
    run_native_preview_core_preview_job,
)
from cdmw.rendering.native_preview_package_cache import (
    create_native_preview_package_staging_dir,
    lookup_native_preview_package_cache,
    native_preview_package_cache_build_lock,
    release_native_preview_package_staging_dir,
    store_native_preview_package_cache,
)
from cdmw.services.mesh_dotnet_preview_package import build_or_lookup_dotnet_preview_package


NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS = {".pac", ".pam", ".pamlod"}


def _preserve_native_preview_core_staging_package(
    cache_root: Path,
    staging_entry_dir: Path,
) -> Optional[Path]:
    """Move a complete unpublished package out of the prunable staging lane."""

    staging_entry_dir = Path(staging_entry_dir)
    package_dir = staging_entry_dir / "package"
    if not package_dir.is_dir():
        return None
    fallback_entry_dir: Optional[Path] = None
    try:
        Path(cache_root).mkdir(parents=True, exist_ok=True)
        fallback_entry_dir = Path(
            tempfile.mkdtemp(prefix="cdmw_preview_core_", dir=str(Path(cache_root)))
        )
        fallback_entry_dir.rmdir()
        staging_entry_dir.replace(fallback_entry_dir)
        return fallback_entry_dir / "package"
    except OSError:
        if fallback_entry_dir is not None:
            try:
                fallback_entry_dir.rmdir()
            except OSError:
                pass
        return None


class ArchivePreviewNativeMixin:
    """Native preview-core package generation and metadata helpers."""

    def _native_preview_core_supported_for_entry(self) -> bool:
        if self.entry is None or self.include_loose_preview_assets or not self.native_preview_core_enabled:
            return False
        return str(getattr(self.entry, "extension", "") or "").strip().lower() in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS

    def _emit_native_preview_core_attempt(
        self,
        native_attempt: Optional[NativePreviewCoreAttempt],
        timings: Dict[str, float],
    ) -> bool:
        if native_attempt is None:
            return False
        timings["native_preview_core_s"] = max(0.0, float(native_attempt.elapsed_ms) / 1000.0)
        if native_attempt.succeeded:
            timings["progressive_full_s"] = timings["native_preview_core_s"]
            payload = self._native_preview_core_result(native_attempt, timings)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, payload)
            return True
        if self.native_preview_core_enabled:
            timings["progressive_full_s"] = timings["native_preview_core_s"]
            payload = self._native_preview_core_failure_result(native_attempt, timings)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, payload)
            return True
        return False

    def _try_native_preview_core(self) -> Optional[NativePreviewCoreAttempt]:
        if not self.native_preview_core_enabled or self.entry is None:
            return None
        if str(getattr(self.entry, "extension", "") or "").strip().lower() not in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS:
            return None
        cache_root = self.native_preview_core_cache_root
        if cache_root is None:
            return NativePreviewCoreAttempt(
                status="error",
                fallback_reason="native preview-core cache root unavailable",
            )
        cache_mode = str(self.native_preview_package_cache_mode or "off").strip().lower()
        durable_cache_enabled = (
            cache_mode in {"balanced", "aggressive"}
            and bool(self.native_preview_package_cache_key)
            and self.native_preview_package_cache_max_bytes > 0
        )
        staging_entry_dir: Optional[Path] = None
        output_root: Optional[Path] = None
        build_lock = None
        dds_cache_max_bytes = 96 * 1024 * 1024
        dds_cache_target_bytes = 64 * 1024 * 1024
        try:
            if durable_cache_enabled:
                build_lock = native_preview_package_cache_build_lock(
                    cache_root,
                    self.native_preview_package_cache_key,
                )
                build_lock.acquire()
                if self.stop_event.is_set():
                    raise RunCancelled("Native preview-core job cancelled.")
                hit = lookup_native_preview_package_cache(
                    cache_root,
                    self.native_preview_package_cache_key,
                    validate_package=self._validate_native_preview_core_package_basic,
                )
                if hit is not None:
                    diagnostics_source = hit.metadata.get("diagnostics") if isinstance(hit.metadata, Mapping) else {}
                    diagnostics = dict(diagnostics_source) if isinstance(diagnostics_source, Mapping) else {}
                    diagnostics.update(
                        {
                            "native_preview_package_cache": "hit_after_wait",
                            "native_preview_package_cache_key": self.native_preview_package_cache_key,
                            "package_path": str(hit.package_dir),
                        }
                    )
                    return NativePreviewCoreAttempt(
                        status="ok",
                        package_path=str(hit.package_dir),
                        diagnostics=diagnostics,
                    )
                dds_cache_max_bytes = 512 * 1024 * 1024 if cache_mode == "aggressive" else 192 * 1024 * 1024
                dds_cache_target_bytes = 384 * 1024 * 1024 if cache_mode == "aggressive" else 128 * 1024 * 1024
                try:
                    staging_entry_dir = create_native_preview_package_staging_dir(cache_root, leased=True)
                    output_root = staging_entry_dir / "package"
                except OSError:
                    staging_entry_dir = None
                    output_root = None
            native_attempt = run_native_preview_core_preview_job(
                self.entry,
                cache_root=cache_root,
                render_settings=self.render_settings,
                companion_entry=self.companion_entry,
                dependency_entries=getattr(self, "native_preview_dependency_entries", ()),
                dependency_entries_complete=bool(
                    getattr(self, "native_preview_dependency_entries_complete", False)
                ),
                enabled_prefab_component_paths=getattr(
                    self,
                    "enabled_prefab_component_paths",
                    (),
                ),
                package_root=self.native_preview_core_package_root,
                output_root=output_root,
                timeout_seconds=8.0,
                stop_event=self.stop_event,
                dds_cache_max_bytes=dds_cache_max_bytes,
                dds_cache_target_bytes=dds_cache_target_bytes,
            )
            if native_attempt.succeeded and durable_cache_enabled and staging_entry_dir is not None:
                metadata = {
                    "entry_path": str(getattr(self.entry, "path", "") or ""),
                    "companion_path": str(getattr(self.companion_entry, "path", "") or ""),
                    "cache_mode": cache_mode,
                    "render_settings": render_settings_to_native_preview_core_dict(self.render_settings),
                    "diagnostics": dict(native_attempt.diagnostics),
                }
                hit = store_native_preview_package_cache(
                    cache_root,
                    self.native_preview_package_cache_key,
                    staging_entry_dir,
                    metadata,
                    validate_package=self._validate_native_preview_core_package_basic,
                    max_bytes=self.native_preview_package_cache_max_bytes,
                    target_bytes=self.native_preview_package_cache_target_bytes,
                )
                diagnostics = dict(native_attempt.diagnostics)
                if hit is not None:
                    diagnostics["native_preview_package_cache"] = "stored"
                    diagnostics["native_preview_package_cache_key"] = self.native_preview_package_cache_key
                    return dataclasses.replace(
                        native_attempt,
                        package_path=str(hit.package_dir),
                        diagnostics=diagnostics,
                    )
                diagnostics["native_preview_package_cache"] = "store_failed"
                staging_package_dir = staging_entry_dir / "package"
                valid_staging, _missing = self._validate_native_preview_core_package_basic(
                    staging_package_dir
                )
                fallback_package_dir = (
                    _preserve_native_preview_core_staging_package(cache_root, staging_entry_dir)
                    if valid_staging
                    else None
                )
                if fallback_package_dir is not None:
                    diagnostics["package_path"] = str(fallback_package_dir)
                    diagnostics["native_preview_package_cache"] = "standalone_fallback"
                    return dataclasses.replace(
                        native_attempt,
                        package_path=str(fallback_package_dir),
                        diagnostics=diagnostics,
                        job_root_path=str(fallback_package_dir.parent),
                    )
                return NativePreviewCoreAttempt(
                    status="error",
                    fallback_reason="native preview-core package cache publication failed",
                    diagnostics=diagnostics,
                    elapsed_ms=native_attempt.elapsed_ms,
                )
            return native_attempt
        except RunCancelled:
            raise
        except Exception as exc:
            return NativePreviewCoreAttempt(
                status="error",
                fallback_reason=f"native preview-core failed before package generation: {exc}",
            )
        finally:
            if staging_entry_dir is not None:
                release_native_preview_package_staging_dir(staging_entry_dir, cleanup=True)
            if build_lock is not None:
                build_lock.release()

    @staticmethod
    def _validate_native_preview_core_package_basic(package_dir: Path) -> Tuple[bool, Tuple[str, ...]]:
        package_dir = Path(package_dir)
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.is_file():
            return False, (f"missing manifest:{manifest_path}",)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, (f"invalid manifest:{exc}",)
        if not isinstance(manifest, Mapping):
            return False, ("manifest is not a JSON object",)
        missing: List[str] = []

        def check_path(raw_value: object, *, package_relative: bool) -> None:
            text = str(raw_value or "").strip()
            if not text:
                return
            try:
                path = Path(text)
                if package_relative or not path.is_absolute():
                    path = package_dir / text
                if not path.is_file():
                    missing.append(str(path))
            except (OSError, ValueError) as exc:
                missing.append(f"{text}:{exc}")

        for batch in tuple(manifest.get("batches", ()) or ()):
            if not isinstance(batch, Mapping):
                continue
            check_path(batch.get("vertex_file"), package_relative=True)
            if bool(batch.get("cloth_enabled")):
                for key in ("cloth_particle_file", "cloth_pin_file", "cloth_constraint_file"):
                    check_path(batch.get(key), package_relative=True)
            textures = batch.get("textures")
            if isinstance(textures, Mapping):
                for value in textures.values():
                    check_path(value, package_relative=True)
            dds_textures = batch.get("dds_textures")
            if isinstance(dds_textures, Mapping):
                for descriptor in dds_textures.values():
                    if isinstance(descriptor, Mapping):
                        if not bool(descriptor.get("available", True)):
                            continue
                        if not bool(descriptor.get("direct_upload_candidate", True)):
                            continue
                        check_path(descriptor.get("source_path"), package_relative=False)
            if len(missing) >= 8:
                break
        return not missing, tuple(missing[:8])

    def _archive_entry_for_native_asset_path(self, path: str) -> Optional[ArchiveEntry]:
        normalized = str(path or "").replace("\\", "/").strip().lower()
        if not normalized:
            return None
        for candidate in tuple(self.texture_entries_by_normalized_path.get(normalized, ()) or ()):
            if str(getattr(candidate, "path", "") or "").replace("\\", "/").strip().lower() == normalized:
                return candidate
        basename = PurePosixPath(normalized).name
        for candidate in tuple(self.texture_entries_by_basename.get(basename, ()) or ()):
            if str(getattr(candidate, "path", "") or "").replace("\\", "/").strip().lower() == normalized:
                return candidate
        candidates = tuple(self.texture_entries_by_basename.get(basename, ()) or ())
        return candidates[0] if candidates else None

    def _native_preview_core_manifest_metadata(
        self,
        package_path: str,
    ) -> Tuple[Tuple[ArchiveModelTextureReference, ...], Optional[AssetFamilyGraph], Tuple[str, ...], int]:
        lines: List[str] = []
        package_dir = Path(str(package_path or ""))
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.is_file():
            return (), None, ("Native manifest metadata missing; D3D11 package remains native-only.",), 0
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return (), None, (f"Native manifest metadata read failed: {exc}",), 0
        schema_version = int(manifest.get("schema_version") or 0)
        asset_payload = manifest.get("asset_family")
        if not isinstance(asset_payload, dict):
            return (), None, ("Native manifest has no asset_family payload; D3D11 package remains native-only.",), schema_version

        source_entry = self.entry
        root_path = str(asset_payload.get("root_path") or getattr(source_entry, "path", "") or "").replace("\\", "/")
        family_key = str(asset_payload.get("family_key") or PurePosixPath(root_path).stem)
        summary = str(asset_payload.get("summary") or "").strip()

        references: List[ArchiveModelTextureReference] = []
        for item in list(asset_payload.get("references") or ()):
            if not isinstance(item, dict):
                continue
            resolved_path = str(item.get("resolved_archive_path") or item.get("path") or "").replace("\\", "/").strip()
            reference_name = str(item.get("reference_name") or PurePosixPath(resolved_path).name or "").strip()
            if not resolved_path and not reference_name:
                continue
            resolved_entry = self._archive_entry_for_native_asset_path(resolved_path)
            references.append(
                ArchiveModelTextureReference(
                    reference_name=reference_name or resolved_path,
                    material_name=str(item.get("material_name") or ""),
                    semantic_label=str(item.get("semantic_label") or ""),
                    semantic_hint=str(item.get("semantic_hint") or ""),
                    sidecar_parameter_name=str(item.get("sidecar_parameter_name") or ""),
                    sidecar_kind=str(item.get("sidecar_kind") or ""),
                    shader_family=str(item.get("shader_family") or ""),
                    texture_role=str(item.get("texture_role") or ""),
                    resolution_status=str(item.get("resolution_status") or ("resolved" if resolved_entry is not None else "missing")),
                    resolved_archive_path=resolved_path,
                    resolved_package_label=str(item.get("resolved_package_label") or getattr(resolved_entry, "package_label", "") or ""),
                    resolved_entry=resolved_entry,
                    usage_count=1,
                    reference_kind=str(item.get("reference_kind") or "metadata"),
                    relation_group=str(item.get("relation_group") or "Metadata / Other"),
                    relation_reason=str(item.get("relation_reason") or "Recovered by native preview-core."),
                    relation_confidence=str(item.get("relation_confidence") or RelationConfidence.DERIVED_SAME_STEM.value),
                    source_table=str(item.get("source_table") or ""),
                    source_field=str(item.get("source_field") or ""),
                )
            )

        member_rows: List[AssetFamilyMember] = []
        grouped_paths: Dict[str, List[str]] = defaultdict(list)
        members: List[str] = []
        seen_members: set[str] = set()
        for item in list(asset_payload.get("member_rows") or ()):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").replace("\\", "/").strip()
            display_name = str(item.get("display_name") or PurePosixPath(path).name or "").strip()
            if not path and not display_name:
                continue
            resolved_entry = self._archive_entry_for_native_asset_path(path)
            row = AssetFamilyMember(
                group=str(item.get("group") or "Other"),
                role=str(item.get("role") or "Related File"),
                display_name=display_name,
                path=path,
                status=str(item.get("status") or "Resolved"),
                confidence=str(item.get("confidence") or item.get("evidence") or "Hint"),
                source_evidence=str(item.get("evidence") or item.get("confidence") or "Hint"),
                include_policy=str(item.get("include_policy") or "manual"),
                reason=str(item.get("reason") or "Recovered by native preview-core."),
                warning=str(item.get("warning") or ""),
                resolved_entry=resolved_entry,
                source_table=str(item.get("source_table") or ""),
                source_field=str(item.get("source_field") or ""),
            )
            member_rows.append(row)
            if path and path.casefold() not in seen_members:
                seen_members.add(path.casefold())
                members.append(path)
            if path:
                grouped_paths[row.group].append(path)

        relations: List[AssetRelation] = []
        for reference in references:
            relations.append(
                AssetRelation(
                    source_path=root_path,
                    target_path=reference.resolved_archive_path or reference.reference_name,
                    relation_kind=reference.reference_kind,
                    confidence=reference.relation_confidence,
                    role_label=reference.semantic_label,
                    status=reference.resolution_status,
                    source_evidence=reference.relation_reason,
                    include_policy="required" if reference.resolution_status == "resolved" else "manual",
                    reason=reference.relation_reason,
                    source_entry=source_entry,
                    target_entry=reference.resolved_entry,
                    semantic_label=reference.semantic_label,
                    semantic_hint=reference.semantic_hint,
                    sidecar_parameter_name=reference.sidecar_parameter_name,
                    material_name=reference.material_name,
                    package_label=reference.resolved_package_label,
                    source_table=reference.source_table,
                    source_field=reference.source_field,
                )
            )

        graph = AssetFamilyGraph(
            root_path=root_path,
            family_key=family_key,
            members=tuple(members),
            member_rows=tuple(member_rows),
            relations=tuple(relations),
            attachment_evidence=(),
            grouped_paths={key: tuple(value) for key, value in grouped_paths.items()},
            summary=summary,
        )
        if isinstance(source_entry, ArchiveEntry):
            python_graph = build_archive_asset_family_graph(source_entry, tuple(references))
            graph.attachment_evidence = tuple(getattr(python_graph, "attachment_evidence", ()) or ())
        lines.append(
            f"Native Asset Family: schema=v{schema_version}; rows={len(member_rows):,}; references={len(references):,}; source=native-core."
        )
        return tuple(references), graph, tuple(lines), schema_version

    @staticmethod
    def _native_preview_core_shader_fidelity_lines(package_path: str) -> Tuple[str, ...]:
        package_dir = Path(str(package_path or ""))
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.is_file():
            return ()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return ()
        if not isinstance(manifest, Mapping):
            return ()
        status = manifest.get("shader_asset_fidelity_status")
        if not isinstance(status, Mapping):
            return ()
        summary = [
            str(line or "").strip()
            for line in tuple(status.get("ui_summary", ()) or ())
            if str(line or "").strip()
        ]
        if not summary:
            return ()
        lines = ["Shader Fidelity: " + summary[0]]
        lines.extend(f"Shader Fidelity: {line}" for line in summary[1:5])
        return tuple(lines)

    def _native_preview_core_result(
        self,
        native_attempt: NativePreviewCoreAttempt,
        timings: Mapping[str, float],
    ) -> ArchivePreviewResult:
        entry = self.entry
        metadata_summary = build_archive_entry_metadata_summary(entry) if entry is not None else "Native preview"
        cache_root = self.native_preview_core_cache_root
        if cache_root is None:
            return self._native_preview_core_failure_result(
                NativePreviewCoreAttempt(
                    status="error",
                    fallback_reason=".NET/Vortice preview cache root unavailable",
                    diagnostics=dict(native_attempt.diagnostics),
                    elapsed_ms=native_attempt.elapsed_ms,
                ),
                timings,
            )
        try:
            dotnet_package = build_or_lookup_dotnet_preview_package(
                native_attempt.package_path,
                cache_root=Path(cache_root),
                archive_identity=(
                    str(self.native_preview_package_cache_key or "").strip()
                    or str(getattr(entry, "path", "") or native_attempt.package_path)
                ),
                sidecar_generation=self.sidecar_generation,
                cache_mode=self.native_preview_package_cache_mode,
                max_bytes=self.native_preview_package_cache_max_bytes,
                target_bytes=self.native_preview_package_cache_target_bytes,
                cancelled=self.stop_event.is_set,
                metadata={
                    "entry_path": str(getattr(entry, "path", "") or ""),
                    "native_preview_core_package": native_attempt.package_path,
                },
            )
        except RunCancelled:
            raise
        except Exception as exc:
            diagnostics = dict(native_attempt.diagnostics)
            diagnostics["dotnet_preview_package_error"] = str(exc)
            return self._native_preview_core_failure_result(
                NativePreviewCoreAttempt(
                    status="error",
                    fallback_reason=f"canonical .NET preview package generation failed: {exc}",
                    diagnostics=diagnostics,
                    elapsed_ms=native_attempt.elapsed_ms,
                ),
                timings,
            )
        model_texture_references, asset_family_graph, metadata_lines, native_schema_version = (
            self._native_preview_core_manifest_metadata(native_attempt.package_path)
        )
        diagnostics = dict(native_attempt.diagnostics)
        diagnostics["dotnet_preview_package_path"] = str(dotnet_package.package_dir)
        notes = tuple(str(note) for note in tuple(diagnostics.get("notes", ()) or ()) if str(note).strip())
        base_quality_notes = tuple(
            str(note)
            for note in tuple(diagnostics.get("base_quality_notes", ()) or ())
            if str(note).strip()
        )
        selected_texture_examples = tuple(
            str(note)
            for note in tuple(diagnostics.get("selected_texture_examples", ()) or ())
            if str(note).strip()
        )
        rejected_texture_examples = tuple(
            str(note)
            for note in tuple(diagnostics.get("rejected_texture_examples", ()) or ())
            if str(note).strip()
        )
        diagnostic_lines = [
            "Preview Core decoded the archive model for the canonical .NET/Vortice preview package.",
            ".NET/Vortice package source: canonical Preview Core decode",
            native_attempt.diagnostic_line(),
            (
                "Native Material Quality: "
                f"safe={bool(diagnostics.get('material_quality_safe', False))}; "
                f"missing_base={int(diagnostics.get('base_missing_count', 0) or 0)}; "
                f"low_res_base={int(diagnostics.get('base_low_res_count', 0) or 0)}; "
                f"low_confidence_base={int(diagnostics.get('base_low_confidence_count', 0) or 0)}; "
                f"technical_base={int(diagnostics.get('base_technical_count', 0) or 0)}"
            ),
        ]
        shader_fidelity_lines = self._native_preview_core_shader_fidelity_lines(native_attempt.package_path)
        if shader_fidelity_lines:
            diagnostic_lines.extend(shader_fidelity_lines)
        if notes:
            diagnostic_lines.append("Native Material Notes: " + "; ".join(notes[:8]))
        if base_quality_notes:
            diagnostic_lines.append("Native Base Quality Notes: " + "; ".join(base_quality_notes[:8]))
        if selected_texture_examples:
            diagnostic_lines.append("Native Selected Textures: " + "; ".join(selected_texture_examples[:8]))
        if rejected_texture_examples:
            diagnostic_lines.append("Native Rejected Texture Candidates: " + "; ".join(rejected_texture_examples[:8]))
        if metadata_lines:
            diagnostic_lines.extend(metadata_lines)
        detail_text = "\n".join(
            part
            for part in diagnostic_lines
            if part
        )
        return ArchivePreviewResult(
            status="ok",
            title=entry.basename if entry is not None else "Native Preview",
            metadata_summary=metadata_summary,
            detail_text=detail_text,
            timings=dict(timings),
            preview_model=None,
            model_texture_references=model_texture_references,
            asset_family_graph=asset_family_graph,
            dotnet_preview_package_path=str(dotnet_package.package_dir),
            native_preview_diagnostics=diagnostics,
            preferred_view="model",
            sidecar_generation=self.sidecar_generation,
        )

    def _native_preview_core_failure_result(
        self,
        native_attempt: NativePreviewCoreAttempt,
        timings: Mapping[str, float],
    ) -> ArchivePreviewResult:
        entry = self.entry
        metadata_summary = build_archive_entry_metadata_summary(entry) if entry is not None else "Native preview"
        reason = str(getattr(native_attempt, "fallback_reason", "") or "native preview-core did not produce a D3D11 package")
        detail_text = "\n".join(
            part
            for part in (
                "Preview Core did not produce a canonical .NET/Vortice preview package.",
                "The legacy renderer is not used as a fallback; the .NET/Vortice preview will retry.",
                native_attempt.diagnostic_line(),
                f"Native failure reason: {reason}",
            )
            if part
        )
        diagnostics = dict(getattr(native_attempt, "diagnostics", {}) or {})
        diagnostics.setdefault("fallback_reason", reason)
        return ArchivePreviewResult(
            status="error",
            title=entry.basename if entry is not None else "Native Preview",
            metadata_summary=metadata_summary,
            detail_text=detail_text,
            timings=dict(timings),
            preview_model=None,
            native_preview_diagnostics=diagnostics,
            preferred_view="details",
            sidecar_generation=self.sidecar_generation,
        )

    @staticmethod
    def _attach_native_preview_core_note(
        payload: ArchivePreviewResult,
        native_attempt: NativePreviewCoreAttempt,
    ) -> ArchivePreviewResult:
        note = native_attempt.diagnostic_line()
        if not note:
            return payload
        detail_text = str(getattr(payload, "detail_text", "") or "")
        if note in detail_text:
            return payload
        updated_detail = f"{detail_text.rstrip()}\n\n{note}".strip()
        diagnostics = dict(getattr(payload, "native_preview_diagnostics", {}) or {})
        diagnostics.update(native_attempt.diagnostics)
        diagnostics.setdefault("fallback_reason", native_attempt.fallback_reason)
        return dataclasses.replace(
            payload,
            detail_text=updated_detail,
            native_preview_diagnostics=diagnostics,
        )


__all__ = ["ArchivePreviewNativeMixin", "NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS"]
