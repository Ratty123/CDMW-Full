"""Cancellable Character Context discovery and native-package workers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, Signal

from cdmw.core.appearance_composite import (
    AppearanceCompositeComponent,
    appearance_model_body_family,
    appearance_model_dependency_entries,
    appearance_model_slot,
    build_appearance_composite_preview_plan,
    resolve_appearance_model_component,
)
from cdmw.core.archive_mesh_appearance import apply_archive_mesh_appearance_for_preview
from cdmw.core.archive import (
    build_archive_entry_basename_index,
    build_archive_entry_path_index,
    read_archive_entry_data,
)
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.character_context import (
    CharacterContextAppearance,
    CharacterContextDiscoveryRequest,
    CharacterContextDiscoveryResult,
    CharacterContextOption,
    NativePreviewContextComponent,
    character_context_entry_key,
)
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.models import ArchiveEntry
from cdmw.rendering.native_preview_core import (
    NativePreviewCoreServiceClient,
    find_native_preview_core_binary,
    render_settings_to_native_preview_core_dict,
    run_native_preview_core_preview_job,
)
from cdmw.core.skeleton_resolver import resolve_skeleton_descriptor_for_model
from cdmw.workers.archive_preview_native import _native_presentation_geometry_payload
from cdmw.workers.appearance_workers import (
    AppearanceExactMatchRequest,
    run_appearance_exact_match,
)


_MODEL_EXTENSIONS = {".pac", ".pam", ".pamlod"}
_MATERIAL_SIDECAR_EXTENSIONS = {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}
_CONTEXT_EXTENSION_GROUPS = ((".pab",), (".pabc",), (".pamt",))
_MAX_ALTERNATIVES_PER_SLOT = 24
_MAX_COMPATIBILITY_CANDIDATES_PER_SLOT = 48
_MAX_COMPATIBILITY_SECONDS_PER_SLOT = 4.0


def _normalized_slot(path: str) -> str:
    slot = appearance_model_slot(path)
    if slot in {"nude", "body"}:
        return "body"
    if slot in {"face", "beard"}:
        return "face"
    return slot


def _option_id(entry: ArchiveEntry, slot: str, authority: str) -> str:
    return f"{authority}:{slot}:{character_context_entry_key(entry)}"


def _entry_label(entry: ArchiveEntry) -> str:
    stem = PurePosixPath(str(entry.path or "").replace("\\", "/")).stem
    return stem or str(entry.basename or entry.path or "Character part")


def _friendly_face_contents(entry: ArchiveEntry, stop_event: object) -> tuple[str, ...]:
    raise_if_cancelled(stop_event, "Character Context discovery cancelled.")
    try:
        data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
        parsed = parse_mesh(data, entry.path)
    except Exception:
        return ()
    evidence = " ".join(
        f"{getattr(mesh, 'name', '')} {getattr(mesh, 'material', '')}".casefold()
        for mesh in tuple(getattr(parsed, "submeshes", ()) or ())
    )
    labels: list[str] = []
    for label, tokens in (
        ("Eyes", ("eyeleft", "eyeright", " eye", "_eye")),
        ("Brows", ("eyebrow", "brow")),
        ("Eyeline", ("eyeline", "eyeliner")),
        ("Teeth", ("tooth", "teeth")),
    ):
        if any(token in evidence for token in tokens):
            labels.append(label)
    return tuple(labels)


def _context_owner_tokens(entries: Sequence[ArchiveEntry], extensions: Sequence[str]) -> set[str]:
    owners: set[str] = set()
    wanted = {str(extension).casefold() for extension in extensions}
    for entry in entries:
        if str(entry.extension or "").casefold() not in wanted:
            continue
        stem = PurePosixPath(str(entry.path or "").replace("\\", "/")).stem.casefold()
        tokens = tuple(token for token in re.split(r"[^a-z0-9]+", stem) if token)
        if len(tokens) >= 2:
            owners.add("_".join(tokens[:2]))
    return owners


def _explicit_context_conflict(
    authored_dependencies: Sequence[ArchiveEntry],
    candidate_dependencies: Sequence[ArchiveEntry],
) -> bool:
    for extension_group in _CONTEXT_EXTENSION_GROUPS:
        authored = _context_owner_tokens(authored_dependencies, extension_group)
        candidate = _context_owner_tokens(candidate_dependencies, extension_group)
        if authored and candidate and authored.isdisjoint(candidate):
            return True
    return False


def _component_dependencies(
    entry: ArchiveEntry,
    component: AppearanceCompositeComponent,
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    skeleton_basename_index: Mapping[str, Sequence[ArchiveEntry]],
    stop_event: object,
) -> tuple[tuple[ArchiveEntry, ...], bool]:
    dependencies, missing = appearance_model_dependency_entries(
        entry,
        component,
        path_index=path_index,
        basename_index=basename_index,
    )
    resolved_entries: list[ArchiveEntry] = list(dependencies)
    try:
        def read_payload(candidate: ArchiveEntry) -> bytes:
            raise_if_cancelled(stop_event, "Character Context dependency resolution cancelled.")
            return read_archive_entry_data(candidate, stop_event=stop_event)[0]

        skeleton = resolve_skeleton_descriptor_for_model(
            entry,
            component.resolved_context_entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=skeleton_basename_index,
            read_entry_data=read_payload,
        )
        for field_name in (
            "descriptor_entry",
            "skeleton_descriptor_entry",
            "skeleton_entry",
            "skeleton_variation_entry",
            "morph_descriptor_entry",
            "morph_target_entry",
            "animation_constraint_entry",
            "socket_entry",
        ):
            candidate = getattr(skeleton, field_name, None)
            if isinstance(candidate, ArchiveEntry):
                resolved_entries.append(candidate)
    except RunCancelled:
        raise
    except Exception:
        pass
    dependencies = _dedupe_entries(resolved_entries)
    has_sidecar = any(
        str(candidate.extension or "").casefold() in _MATERIAL_SIDECAR_EXTENSIONS
        for candidate in dependencies
    )
    return dependencies, bool(has_sidecar and not missing)


def _dedupe_entries(entries: Sequence[ArchiveEntry]) -> tuple[ArchiveEntry, ...]:
    result: list[ArchiveEntry] = []
    seen: set[str] = set()
    for entry in entries:
        key = character_context_entry_key(entry)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return tuple(result)


def _appearance_source_scale(
    source_entry: ArchiveEntry,
    components: Sequence[AppearanceCompositeComponent],
) -> float:
    source_key = character_context_entry_key(source_entry)
    for component in components:
        if any(character_context_entry_key(entry) == source_key for entry in component.resolved_model_entries):
            scale = float(component.scale or 1.0)
            return scale if scale > 0.0 else 1.0
    return 1.0


def _authored_options(
    source_entry: ArchiveEntry,
    appearance_entry: ArchiveEntry,
    components: Sequence[AppearanceCompositeComponent],
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    skeleton_basename_index: Mapping[str, Sequence[ArchiveEntry]],
    stop_event: object,
    source_scale: float,
) -> tuple[CharacterContextOption, ...]:
    source_key = character_context_entry_key(source_entry)
    options: list[CharacterContextOption] = []
    seen: set[str] = set()
    for component in components:
        section = str(component.section or "").strip().casefold()
        model_entries: list[ArchiveEntry] = []
        slot = ""
        for model_entry in tuple(component.resolved_model_entries or ()):
            raise_if_cancelled(stop_event, "Character Context discovery cancelled.")
            if str(model_entry.extension or "").casefold() not in _MODEL_EXTENSIONS:
                continue
            if character_context_entry_key(model_entry) == source_key:
                continue
            path_slot = _normalized_slot(model_entry.path)
            if section in {"head", "face"}:
                entry_slot = "face" if path_slot == "face" else ""
            elif section == "hair":
                entry_slot = "hair" if path_slot == "hair" else ""
            elif section in {"nude", "body"}:
                entry_slot = "body" if path_slot == "body" else ""
            elif section in {"armor", "accessory"}:
                entry_slot = "gear"
            else:
                entry_slot = ""
            if not entry_slot:
                continue
            entry_key = character_context_entry_key(model_entry)
            if entry_key in seen:
                continue
            seen.add(entry_key)
            slot = entry_slot
            model_entries.append(model_entry)
        if not slot or not model_entries:
            continue
        dependency_entries: list[ArchiveEntry] = []
        dependencies_complete = True
        face_contents: list[str] = []
        for model_entry in model_entries:
            dependencies, entry_dependencies_complete = _component_dependencies(
                model_entry,
                component,
                path_index=path_index,
                basename_index=basename_index,
                skeleton_basename_index=skeleton_basename_index,
                stop_event=stop_event,
            )
            dependency_entries.extend(dependencies)
            dependencies_complete = dependencies_complete and entry_dependencies_complete
            if slot == "face":
                face_contents.extend(_friendly_face_contents(model_entry, stop_event))
        primary = model_entries[0]
        friendly_contents = tuple(dict.fromkeys(face_contents))
        label = "Face Set" if friendly_contents else _entry_label(primary)
        if len(model_entries) > 1 and slot != "face":
            label = f"{label} ({len(model_entries)} pieces)"
        options.append(
            CharacterContextOption(
                option_id=_option_id(primary, slot, "authored"),
                entry=primary,
                slot=slot,
                label=label,
                authority="authored",
                compatibility="Authored",
                scale=float(component.scale or 1.0) / max(0.01, float(source_scale or 1.0)),
                appearance_path=str(appearance_entry.path or ""),
                face_contents=friendly_contents,
                dependency_entries=_dedupe_entries(dependency_entries),
                dependencies_complete=dependencies_complete,
                component_entries=tuple(model_entries),
            )
        )
    return tuple(options)


def _compatible_options(
    source_entry: ArchiveEntry,
    archive_entries: Sequence[ArchiveEntry],
    authored_options: Sequence[CharacterContextOption],
    *,
    slot: str,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    skeleton_basename_index: Mapping[str, Sequence[ArchiveEntry]],
    stop_event: object,
    source_scale: float,
) -> tuple[CharacterContextOption, ...]:
    body_family = appearance_model_body_family(source_entry.path)
    authored_for_slot = tuple(option for option in authored_options if option.slot == slot)
    authored_dependencies = tuple(
        dependency
        for option in authored_for_slot
        for dependency in option.dependency_entries
    )
    existing = {character_context_entry_key(option.entry) for option in authored_options}
    compatible: list[CharacterContextOption] = []
    checked_candidates = 0
    deadline = time.perf_counter() + _MAX_COMPATIBILITY_SECONDS_PER_SLOT
    for entry in archive_entries:
        raise_if_cancelled(stop_event, "Character Context discovery cancelled.")
        if len(compatible) >= _MAX_ALTERNATIVES_PER_SLOT:
            break
        if str(entry.extension or "").casefold() not in _MODEL_EXTENSIONS:
            continue
        if _normalized_slot(entry.path) != slot:
            continue
        if not body_family or appearance_model_body_family(entry.path) != body_family:
            continue
        entry_key = character_context_entry_key(entry)
        if entry_key in existing:
            continue
        if (
            checked_candidates >= _MAX_COMPATIBILITY_CANDIDATES_PER_SLOT
            or time.perf_counter() >= deadline
        ):
            break
        checked_candidates += 1
        component = resolve_appearance_model_component(
            entry,
            path_index=path_index,
            basename_index=basename_index,
        )
        dependencies, dependencies_complete = _component_dependencies(
            entry,
            component,
            path_index=path_index,
            basename_index=basename_index,
            skeleton_basename_index=skeleton_basename_index,
            stop_event=stop_event,
        )
        if not dependencies_complete:
            continue
        if _explicit_context_conflict(authored_dependencies, dependencies):
            continue
        compatible.append(
            CharacterContextOption(
                option_id=_option_id(entry, slot, "compatible"),
                entry=entry,
                slot=slot,
                label=_entry_label(entry),
                authority="compatible",
                compatibility="Compatible — fit may vary",
                scale=1.0 / max(0.01, float(source_scale or 1.0)),
                dependency_entries=dependencies,
                dependencies_complete=True,
                component_entries=(entry,),
            )
        )
        existing.add(entry_key)
    compatible.sort(key=lambda option: str(option.entry.path or "").casefold())
    return tuple(compatible)


def run_character_context_discovery(
    request: CharacterContextDiscoveryRequest,
    *,
    stop_event: object = None,
    progress: object = None,
    authored_ready: object = None,
) -> CharacterContextDiscoveryResult:
    started = time.perf_counter()
    entries = tuple(request.archive_entries)
    path_index = request.path_index if isinstance(request.path_index, Mapping) else {}
    basename_index = request.basename_index if isinstance(request.basename_index, Mapping) else {}
    if entries and len(path_index) < max(1, len(entries) // 4):
        path_index = build_archive_entry_path_index(entries)
    if entries and len(basename_index) < max(1, len(entries) // 8):
        basename_index = build_archive_entry_basename_index(entries)
    skeleton_basename_index = {
        str(basename).casefold(): candidates
        for basename, candidates in basename_index.items()
        if "prefabdata" in str(basename).casefold()
    }
    emit_progress = progress if callable(progress) else (lambda _current, _total, _detail: None)
    emit_progress(0, 4, "Finding exact authored appearances...")
    app_entries = tuple(entry for entry in entries if str(entry.extension or "").casefold() == ".app_xml")
    exact = run_appearance_exact_match(
        AppearanceExactMatchRequest(request.source_entry, app_entries, request.request_id),
        stop_event=stop_event,
    )
    emit_progress(1, 4, "Resolving authored face, hair, body, and gear...")
    appearances: list[CharacterContextAppearance] = []
    for appearance_entry in exact.candidates:
        raise_if_cancelled(stop_event, "Character Context discovery cancelled.")
        plan = build_appearance_composite_preview_plan(
            appearance_entry,
            entries,
            appearance_entry=appearance_entry,
            path_index=path_index,
            basename_index=basename_index,
        )
        source_scale = _appearance_source_scale(request.source_entry, plan.components)
        options = _authored_options(
            request.source_entry,
            appearance_entry,
            plan.components,
            path_index=path_index,
            basename_index=basename_index,
            skeleton_basename_index=skeleton_basename_index,
            stop_event=stop_event,
            source_scale=source_scale,
        )
        essential_count = len({option.slot for option in options if option.slot in {"face", "hair", "body"}})
        appearances.append(
            CharacterContextAppearance(
                appearance_id=character_context_entry_key(appearance_entry),
                entry=appearance_entry,
                label=_entry_label(appearance_entry),
                options=options,
                resolved_essential_count=essential_count,
                source_scale=source_scale,
            )
        )
    appearances.sort(
        key=lambda appearance: (
            -int(appearance.resolved_essential_count),
            str(appearance.entry.path or "").casefold(),
        )
    )
    all_authored = tuple(option for appearance in appearances for option in appearance.options)
    primary_source_scale = appearances[0].source_scale if appearances else 1.0
    source_component = resolve_appearance_model_component(
        request.source_entry,
        path_index=path_index,
        basename_index=basename_index,
    )
    source_dependencies, source_missing = appearance_model_dependency_entries(
        request.source_entry,
        source_component,
        path_index=path_index,
        basename_index=basename_index,
    )
    source_complete = bool(
        any(str(entry.extension or "").casefold() in _MATERIAL_SIDECAR_EXTENSIONS for entry in source_dependencies)
        and not source_missing
    )
    warnings: list[str] = []
    if not appearances:
        warnings.append("No exact authored appearance references this model; heuristic matches were not auto-selected.")
    if not source_complete:
        warnings.append("The source material dependency snapshot is incomplete; native archive lookup remains authoritative.")
    publish_authored = authored_ready if callable(authored_ready) else None
    if publish_authored is not None:
        publish_authored(
            CharacterContextDiscoveryResult(
                request_id=request.request_id,
                source_entry=request.source_entry,
                archive_fingerprint=request.archive_fingerprint,
                appearances=tuple(appearances),
                compatible_hair=(),
                compatible_body=(),
                source_dependency_entries=source_dependencies,
                source_dependencies_complete=source_complete,
                warnings=tuple(warnings),
            )
        )
    emit_progress(2, 4, "Checking compatible hair styles...")
    compatible_hair = _compatible_options(
        request.source_entry,
        entries,
        all_authored,
        slot="hair",
        path_index=path_index,
        basename_index=basename_index,
        skeleton_basename_index=skeleton_basename_index,
        stop_event=stop_event,
        source_scale=primary_source_scale,
    ) if appearances else ()
    emit_progress(3, 4, "Checking compatible bodies...")
    compatible_body = _compatible_options(
        request.source_entry,
        entries,
        all_authored,
        slot="body",
        path_index=path_index,
        basename_index=basename_index,
        skeleton_basename_index=skeleton_basename_index,
        stop_event=stop_event,
        source_scale=primary_source_scale,
    ) if appearances else ()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    emit_progress(4, 4, f"Character Context ready in {elapsed_ms:.0f} ms.")
    return CharacterContextDiscoveryResult(
        request_id=request.request_id,
        source_entry=request.source_entry,
        archive_fingerprint=request.archive_fingerprint,
        appearances=tuple(appearances),
        compatible_hair=tuple(compatible_hair),
        compatible_body=tuple(compatible_body),
        source_dependency_entries=source_dependencies,
        source_dependencies_complete=source_complete,
        warnings=tuple(warnings),
    )


class CharacterContextDiscoveryWorker(QObject):
    progress = Signal(int, int, str)
    authored_ready = Signal(object)
    completed = Signal(object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: CharacterContextDiscoveryRequest) -> None:
        super().__init__()
        self.request = request
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            result = run_character_context_discovery(
                self.request,
                stop_event=self._stop_event,
                progress=self.progress.emit,
                authored_ready=lambda result: (
                    self.authored_ready.emit(result) if not self._stop_event.is_set() else None
                ),
            )
            if not self._stop_event.is_set():
                self.completed.emit(result)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self._stop_event.is_set():
                self.error.emit(self.request.request_id, str(exc))
        finally:
            self.finished.emit()


@dataclass(frozen=True, slots=True)
class CharacterContextPackageRequest:
    request_id: int
    source_entry: ArchiveEntry
    components: tuple[NativePreviewContextComponent, ...]
    source_dependency_entries: tuple[ArchiveEntry, ...]
    source_dependencies_complete: bool
    archive_fingerprint: str
    cache_root: Path
    package_root: Path | None
    render_settings: object


def prepare_character_context_presentation_components(
    components: Sequence[NativePreviewContextComponent],
    *,
    path_index: Mapping[str, Sequence[ArchiveEntry]],
    basename_index: Mapping[str, Sequence[ArchiveEntry]],
    context_entries: Sequence[ArchiveEntry] = (),
    stop_event: object = None,
) -> tuple[tuple[NativePreviewContextComponent, ...], tuple[str, ...]]:
    """Attach model-specific immutable PABC presentation geometry when resolvable."""

    prepared: list[NativePreviewContextComponent] = []
    notes: list[str] = []
    shared_context = _dedupe_entries(context_entries)
    for component in components:
        raise_if_cancelled(stop_event, "Character Context presentation preparation cancelled.")
        if str(component.entry.extension or "").casefold() != ".pac":
            prepared.append(component)
            continue
        try:
            payload, _decompressed, _note = read_archive_entry_data(
                component.entry,
                stop_event=stop_event,
            )
            parsed = parse_mesh(payload, component.entry.path)
            component_context = _dedupe_entries(
                shared_context + tuple(component.dependency_entries)
            )
            presentation, appearance_notes = apply_archive_mesh_appearance_for_preview(
                component.entry,
                parsed,
                payload,
                path_index,
                basename_index,
                component_context,
                stop_event,
            )
            notes.extend(str(note) for note in appearance_notes if str(note).strip())
            source = str(getattr(presentation, "_cdmw_skeleton_variation_source", "") or "").strip()
            if presentation is parsed or not source:
                prepared.append(component)
                continue
            source_entries = tuple(path_index.get(source.replace("\\", "/").strip().casefold(), ()) or ())
            prepared.append(
                replace(
                    component,
                    dependency_entries=_dedupe_entries(
                        tuple(component.dependency_entries) + source_entries
                    ),
                    presentation_geometry_payload=_native_presentation_geometry_payload(
                        presentation,
                        stop_event,
                    ),
                    presentation_geometry_source=source,
                )
            )
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(
                f"Character Context presentation deformation was unavailable for {component.entry.path}: {exc}"
            )
            prepared.append(component)
    return tuple(prepared), tuple(dict.fromkeys(notes))


def _package_cache_key(request: CharacterContextPackageRequest) -> str:
    binary = find_native_preview_core_binary()
    binary_signature = (
        NativePreviewCoreServiceClient.resolve_binary_signature(binary)
        if binary is not None
        else (0, 0)
    )
    payload = {
        "schema": 2,
        "source": character_context_entry_key(request.source_entry),
        "fingerprint": request.archive_fingerprint,
        "source_dependencies": sorted(
            _dependency_fingerprint(entry)
            for entry in request.source_dependency_entries
        ),
        "components": [
            {
                "entry": _dependency_fingerprint(component.entry),
                "slot": component.slot,
                "label": component.label,
                "authority": component.authority,
                "scale": round(float(component.scale), 6),
                "appearance_path": component.appearance_path,
                "dependencies": sorted(
                    _dependency_fingerprint(entry)
                    for entry in component.dependency_entries
                ),
                "presentation_geometry_sha256": hashlib.sha256(
                    bytes(component.presentation_geometry_payload or b"")
                ).hexdigest(),
                "presentation_geometry_source": component.presentation_geometry_source,
            }
            for component in request.components
        ],
        "binary": binary_signature,
        "render_settings": render_settings_to_native_preview_core_dict(request.render_settings),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _dependency_fingerprint(entry: ArchiveEntry) -> tuple[object, ...]:
    return (
        str(entry.path or "").replace("\\", "/").casefold(),
        str(entry.pamt_path or "").casefold(),
        str(entry.paz_file or "").casefold(),
        int(entry.offset or 0),
        int(entry.comp_size or 0),
        int(entry.orig_size or 0),
        int(entry.flags or 0),
        int(entry.paz_index or 0),
        str(entry.prepared_sha256 or "").casefold(),
    )


class CharacterContextPackageWorker(QObject):
    completed = Signal(int, str, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: CharacterContextPackageRequest) -> None:
        super().__init__()
        self.request = request
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        started = time.perf_counter()
        stage_root: Path | None = None
        try:
            dependency_entries = _dedupe_entries(
                tuple(self.request.source_dependency_entries)
                + tuple(component.entry for component in self.request.components)
                + tuple(
                    dependency
                    for component in self.request.components
                    for dependency in component.dependency_entries
                )
            )
            path_index = build_archive_entry_path_index(dependency_entries)
            basename_index = build_archive_entry_basename_index(dependency_entries)
            prepared_components, _presentation_notes = prepare_character_context_presentation_components(
                self.request.components,
                path_index=path_index,
                basename_index=basename_index,
                context_entries=dependency_entries,
                stop_event=self._stop_event,
            )
            request = replace(self.request, components=prepared_components)
            key = _package_cache_key(request)
            cache_parent = Path(request.cache_root) / "character_context_packages"
            final_package = cache_parent / key / "package"
            if (final_package / "manifest.json").is_file():
                self.completed.emit(self.request.request_id, str(final_package), (time.perf_counter() - started) * 1000.0)
                return
            cache_parent.mkdir(parents=True, exist_ok=True)
            stage_root = Path(tempfile.mkdtemp(prefix=f".{key[:12]}-", dir=cache_parent))
            stage_package = stage_root / "package"
            dependency_entries = _dedupe_entries(
                tuple(request.source_dependency_entries)
                + tuple(component.entry for component in request.components)
                + tuple(
                    dependency
                    for component in request.components
                    for dependency in component.dependency_entries
                )
            )
            dependencies_complete = bool(
                request.source_dependencies_complete
                and all(component.dependencies_complete for component in request.components)
            )
            attempt = run_native_preview_core_preview_job(
                request.source_entry,
                cache_root=Path(request.cache_root),
                render_settings=request.render_settings,
                dependency_entries=dependency_entries,
                dependency_entries_complete=dependencies_complete,
                preview_context_components=request.components,
                package_root=request.package_root,
                output_root=stage_package,
                timeout_seconds=30.0,
                stop_event=self._stop_event,
            )
            raise_if_cancelled(self._stop_event, "Character Context package cancelled.")
            if not attempt.succeeded or not (stage_package / "manifest.json").is_file():
                raise RuntimeError(attempt.fallback_reason or "Preview Core did not publish a Character Context package.")
            final_root = final_package.parent
            try:
                os.replace(stage_root, final_root)
            except FileExistsError:
                if (final_package / "manifest.json").is_file():
                    self.completed.emit(self.request.request_id, str(final_package), (time.perf_counter() - started) * 1000.0)
                    return
                raise RuntimeError("Character Context cache target already exists but is incomplete.")
            stage_root = None
            self.completed.emit(self.request.request_id, str(final_package), (time.perf_counter() - started) * 1000.0)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self._stop_event.is_set():
                self.error.emit(self.request.request_id, str(exc))
        finally:
            if stage_root is not None:
                shutil.rmtree(stage_root, ignore_errors=True)
            self.finished.emit()


__all__ = [
    "CharacterContextDiscoveryWorker",
    "CharacterContextPackageRequest",
    "CharacterContextPackageWorker",
    "run_character_context_discovery",
]
