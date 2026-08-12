"""Opt-in packaged proof for Archive Browser -> Mesh Editor textures."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.models import ArchiveEntry
from cdmw.services.modify_original_workspace_service import (
    ModifyOriginalWorkspacePreparationRequest,
    prepare_modify_original_workspace,
    read_modify_original_source_asset,
)
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
    configure_synthetic_archive_context,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt import (
    prompt_archive_static_replacement_options,
)
from cdmw.ui.archive_browser.static_replacement_prompt_preflight import (
    StaticReplacementPromptPreflightRequest,
    prepare_static_replacement_prompt_preflight,
)


_PACKAGED_TEXTURE_SAMPLE = (
    "character/model/1_pc/8_pdw/nude/cd_pdw_00_nude_00_0001.pac"
)


def _normalized_archive_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def _entry_indexes(
    entries: Sequence[ArchiveEntry],
) -> tuple[
    dict[str, tuple[ArchiveEntry, ...]],
    dict[str, tuple[ArchiveEntry, ...]],
    dict[str, tuple[ArchiveEntry, ...]],
]:
    by_path: dict[str, list[ArchiveEntry]] = {}
    by_basename: dict[str, list[ArchiveEntry]] = {}
    by_extension: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        by_path.setdefault(_normalized_archive_key(entry.path), []).append(entry)
        by_basename.setdefault(str(entry.basename or "").casefold(), []).append(entry)
        by_extension.setdefault(str(entry.extension or "").casefold(), []).append(entry)
    return (
        {key: tuple(values) for key, values in by_path.items()},
        {key: tuple(values) for key, values in by_basename.items()},
        {key: tuple(values) for key, values in by_extension.items()},
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pump_until(
    app: QApplication,
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float,
    label: str,
) -> float:
    started = time.perf_counter()
    deadline = started + max(0.1, float(timeout_seconds))
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return max(0.0, (time.perf_counter() - started) * 1000.0)
        time.sleep(0.01)
    app.processEvents()
    if predicate():
        return max(0.0, (time.perf_counter() - started) * 1000.0)
    raise RuntimeError(f"Packaged Mesh Editor texture smoke timed out: {label}.")


def _material_roles_ready(mesh_editor_tab: object) -> bool:
    ready = getattr(
        mesh_editor_tab,
        "standalone_dotnet_texture_resources_ready_by_role",
        {},
    )
    if not isinstance(ready, Mapping):
        return False
    return bool(
        ready.get("editable_imported") is True
        and ready.get("original_reference") is True
    )


def _renderer_texture_state(mesh_editor_tab: object) -> dict[str, object]:
    status = getattr(mesh_editor_tab, "standalone_dotnet_status_payload", {})
    renderer = status.get("renderer", {}) if isinstance(status, Mapping) else {}
    geometry = (
        renderer.get("geometry_resources", {})
        if isinstance(renderer, Mapping)
        else {}
    )
    if not isinstance(geometry, Mapping):
        geometry = {}
    result: dict[str, object] = {
        "display_mode": str(renderer.get("display_mode", "") or "")
        if isinstance(renderer, Mapping)
        else "",
        "textures_enabled": bool(renderer.get("textures_enabled", False))
        if isinstance(renderer, Mapping)
        else False,
    }
    for result_key, geometry_key in (
        ("live_texture_srvs", "live_texture_srvs"),
        ("texture_srv_creates", "texture_srv_creates"),
        ("textured_draw_calls", "textured_solid_batch_draws"),
    ):
        try:
            result[result_key] = max(0, int(geometry.get(geometry_key, 0) or 0))
        except (TypeError, ValueError, OverflowError):
            result[result_key] = 0
    return result


def _select_textured_mode(
    app: QApplication,
    mesh_editor_tab: object,
    viewport_combo: QComboBox,
    *,
    label: str,
) -> dict[str, object]:
    untextured_index = viewport_combo.findData("untextured_faces")
    if untextured_index < 0:
        untextured_index = viewport_combo.findData("untextured_wire")
    textured_index = viewport_combo.findData("textured")
    if untextured_index < 0 or textured_index < 0:
        raise RuntimeError(
            "Packaged Mesh Editor texture smoke could not find both textured and untextured modes."
        )
    viewport_combo.setCurrentIndex(untextured_index)
    app.processEvents()
    started = time.perf_counter()
    viewport_combo.setCurrentIndex(textured_index)
    settled_ms = _pump_until(
        app,
        lambda: (
            str(viewport_combo.currentData() or "") == "textured"
            and not bool(
                getattr(
                    mesh_editor_tab,
                    "standalone_dotnet_pending_textured_view",
                    False,
                )
            )
            and getattr(mesh_editor_tab, "standalone_dotnet_scene_pending", None)
            is None
            and getattr(
                mesh_editor_tab,
                "standalone_dotnet_presentation_pending",
                None,
            )
            is None
            and not bool(
                getattr(
                    mesh_editor_tab,
                    "standalone_dotnet_presentation_queued",
                    False,
                )
            )
            and not bool(mesh_editor_tab._standalone_dotnet_package_worker_active())
            and not bool(mesh_editor_tab._dotnet_material_compile_active())
            and _material_roles_ready(mesh_editor_tab)
        ),
        timeout_seconds=180.0,
        label=label,
    )
    controller = mesh_editor_tab._dotnet_target_controller()
    session_id = str(controller.session_view().session_id) if controller is not None else ""
    status_request_id = int(time.monotonic_ns() & 0x7FFFFFFF) or 1
    if not mesh_editor_tab._send_dotnet_protocol_message(
        {
            "event": "renderer_status_request",
            "request_id": status_request_id,
            "session_id": session_id,
            "process_generation": int(mesh_editor_tab.standalone_dotnet_process_generation),
            "protocol_version": 2,
        }
    ):
        raise RuntimeError(
            f"Packaged Mesh Editor texture smoke could not request renderer status for {label}."
        )
    _pump_until(
        app,
        lambda: (
            int(
                (
                    getattr(mesh_editor_tab, "standalone_dotnet_status_payload", {})
                    .get("renderer_status_response", {})
                    .get("request_id", 0)
                )
                or 0
            )
            == status_request_id
            and str(_renderer_texture_state(mesh_editor_tab)["display_mode"])
            == "textured"
            and _renderer_texture_state(mesh_editor_tab)["textures_enabled"] is True
            and int(_renderer_texture_state(mesh_editor_tab)["live_texture_srvs"] or 0)
            > 0
            and int(_renderer_texture_state(mesh_editor_tab)["textured_draw_calls"] or 0)
            > 0
        ),
        timeout_seconds=30.0,
        label=f"{label} renderer textured draw",
    )
    renderer = _renderer_texture_state(mesh_editor_tab)
    if int(renderer["live_texture_srvs"] or 0) <= 0:
        raise RuntimeError(
            f"Packaged Mesh Editor texture smoke reached {label} without a live texture SRV."
        )
    return {
        "label": label,
        "selected_mode": str(viewport_combo.currentData() or ""),
        "settled_ms": round(settled_ms, 3),
        "total_ms": round(max(0.0, (time.perf_counter() - started) * 1000.0), 3),
        "renderer_resources": renderer,
        "roles_ready": dict(
            getattr(
                mesh_editor_tab,
                "standalone_dotnet_texture_resources_ready_by_role",
                {},
            )
        ),
        "applied_generation_by_role": dict(
            getattr(
                mesh_editor_tab,
                "standalone_dotnet_applied_material_generation_by_role",
                {},
            )
        ),
    }


def verify_packaged_mesh_texture_smoke_target(
    window: object,
    app: QApplication,
) -> dict[str, object]:
    """Exercise the real user path inside the currently running packaged app."""

    source_text = os.environ.get("CDMW_GUI_STARTUP_SMOKE_MESH_ASSET", "").strip()
    if not source_text:
        raise RuntimeError(
            "Packaged Mesh Editor texture smoke requires CDMW_GUI_STARTUP_SMOKE_MESH_ASSET "
            "to name the game root or 0009/0.pamt."
        )
    source = Path(source_text).expanduser().resolve()
    pamt_path = source / "0009" / "0.pamt" if source.is_dir() else source
    if not pamt_path.is_file() or pamt_path.name.casefold() != "0.pamt":
        raise RuntimeError(
            f"Packaged Mesh Editor texture smoke could not read PAMT: {pamt_path}"
        )

    entries = tuple(parse_archive_pamt(pamt_path))
    by_path, by_basename, by_extension = _entry_indexes(entries)
    entry = next(iter(by_path.get(_normalized_archive_key(_PACKAGED_TEXTURE_SAMPLE), ())), None)
    if not isinstance(entry, ArchiveEntry):
        raise RuntimeError(
            f"Packaged Mesh Editor texture smoke sample was not found: {_PACKAGED_TEXTURE_SAMPLE}"
        )

    fingerprint_paths = tuple(
        path
        for path in (
            pamt_path,
            Path(entry.paz_file) if entry.paz_file is not None else None,
        )
        if isinstance(path, Path) and path.is_file()
    )
    fingerprints_before = {str(path): _sha256(path) for path in fingerprint_paths}
    result_path = Path(os.environ.get("CDMW_GUI_STARTUP_SMOKE_RESULT", "")).expanduser()
    output_root = (
        result_path.parent / "mesh-archive-texture-smoke"
        if str(result_path)
        else Path(os.environ.get("TEMP", ".")) / "mesh-archive-texture-smoke"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    source_data, source_hash = read_modify_original_source_asset(entry)
    prepared = prepare_modify_original_workspace(
        ModifyOriginalWorkspacePreparationRequest(
            entry=entry,
            workspace_dir=output_root / "workspace",
            create_workspace=False,
            include_family_files=False,
            open_workspace_after_create=False,
            cleanup_stale_sessions=False,
            archive_entries_by_normalized_path=by_path,
            archive_entries_by_basename=by_basename,
            source_asset_data=source_data,
            source_asset_sha256=source_hash,
        ),
        stop_event=threading.Event(),
    )
    preflight = prepare_static_replacement_prompt_preflight(
        StaticReplacementPromptPreflightRequest(
            request_id=1,
            entry=entry,
            obj_path=prepared["obj_path"],
            supplemental_files=tuple(prepared.get("supplemental_files", ())),
            scene_import_result=prepared["scene_import_result"],
            original_mesh=prepared["original_mesh"],
            archive_entries_by_normalized_path=by_path,
            archive_entries_by_basename=by_basename,
            archive_entries_by_extension=by_extension,
        ),
        stop_event=threading.Event(),
    )

    configure_synthetic_archive_context(window, entry)
    window.archive_entries = list(entries)
    window.archive_entries_by_normalized_path = by_path
    window.archive_entries_by_basename = by_basename
    window.archive_entries_by_extension = by_extension
    window._activate_tool_widget(window.archive_browser_tab)
    app.processEvents()

    events: list[tuple[str, dict[str, object]]] = []
    original_recorder = window._record_runtime_event

    def capture_runtime_event(event: str, **fields: object) -> object:
        events.append((event, dict(fields)))
        return original_recorder(event, **fields)

    window._record_runtime_event = capture_runtime_event
    existing_dialogs = set(window._modeless_alignment_dialogs)
    dialog = None
    mesh_editor_tab = window.mesh_editor_tab
    mesh_event_signal = getattr(mesh_editor_tab, "runtime_event_requested", None)

    def capture_mesh_runtime_event(event: str, fields: object) -> None:
        events.append(
            (
                str(event or ""),
                dict(fields) if isinstance(fields, Mapping) else {"payload": fields},
            )
        )

    if mesh_event_signal is not None:
        mesh_event_signal.connect(capture_mesh_runtime_event)
    try:
        prompt_archive_static_replacement_options(
            window,
            entry,
            prepared["obj_path"],
            supplemental_files=tuple(prepared.get("supplemental_files", ())),
            scene_import_result=prepared["scene_import_result"],
            original_mesh=prepared["original_mesh"],
            dialog_title="Packaged Mesh Editor texture smoke",
            placement_context_note="Read-only packaged texture verification.",
            defer_original_texture_preview=True,
            embedded_host=window.mesh_editor_tab.builder_host(),
            _prepared_prompt_preflight=preflight,
        )
        new_dialogs = set(window._modeless_alignment_dialogs) - existing_dialogs
        if len(new_dialogs) != 1:
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke did not open exactly one embedded Builder."
            )
        dialog = window._modeless_alignment_dialogs[next(iter(new_dialogs))]
        if str(QApplication.platformName() or "").strip().lower() == "offscreen":
            # The product's automatic launch intentionally stays disabled on
            # Qt's offscreen backend. The packaged smoke must explicitly make
            # the same request that the visible auto-launch callback makes.
            mesh_editor_tab._start_embedded_dotnet_editor_requested()
        _pump_until(
            app,
            lambda: (
                str(getattr(mesh_editor_tab, "standalone_dotnet_embedded_state", ""))
                == "ready"
                and bool(mesh_editor_tab._standalone_dotnet_editor_process_running())
            ),
            timeout_seconds=90.0,
            label="resident helper ready",
        )
        viewport_combo = dialog.findChild(
            QComboBox,
            "MeshAlignmentViewportDisplayModeCombo",
        )
        if viewport_combo is None:
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke found no Mesh view control."
            )
        normal_mode = _select_textured_mode(
            app,
            mesh_editor_tab,
            viewport_combo,
            label="normal Mesh Editor Solid (Textured)",
        )

        edit_checkbox = dialog.findChild(QCheckBox, "MeshEditModeCheckbox")
        if edit_checkbox is None:
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke found no Edit Mesh control."
            )
        edit_checkbox.setChecked(True)
        _pump_until(
            app,
            lambda: (
                edit_checkbox.isChecked()
                and str(dialog._mesh_editor_embedded_interaction_mode()) == "mesh_edit"
            ),
            timeout_seconds=30.0,
            label="Edit Mesh activation",
        )
        edit_mode = _select_textured_mode(
            app,
            mesh_editor_tab,
            viewport_combo,
            label="Edit Mesh Solid (Textured)",
        )

        material_updates = [
            dict(fields)
            for event, fields in events
            if event == "mesh_dotnet_material_state_update"
        ]
        material_failures = [
            dict(fields)
            for event, fields in events
            if event
            in {
                "mesh_dotnet_material_compile_failed",
                "mesh_dotnet_material_state_failed",
                "mesh_dotnet_textured_view_failed",
            }
        ]
        if not material_updates:
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke observed no resident material update."
            )
        latest_update = material_updates[-1]
        if int(latest_update.get("resource_count", 0) or 0) <= 0:
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke compiled zero texture resources."
            )
        if int(latest_update.get("resource_file_count", 0) or 0) != int(
            latest_update.get("resource_count", 0) or 0
        ):
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke compiled a missing texture resource."
            )
        if material_failures:
            raise RuntimeError(
                f"Packaged Mesh Editor texture smoke recorded material failures: {material_failures!r}"
            )
        lifecycle = dict(mesh_editor_tab.standalone_dotnet_lifecycle_counts)
        if int(lifecycle.get("material_state_failed_count", 0) or 0) != 0:
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke ended with material-state failures."
            )

        fingerprints_after = {str(path): _sha256(path) for path in fingerprint_paths}
        archives_unchanged = fingerprints_before == fingerprints_after
        if not archives_unchanged:
            raise RuntimeError(
                "Packaged Mesh Editor texture smoke changed a source archive."
            )
        return {
            "schema": "cdmw_packaged_mesh_texture_smoke_v1",
            "read_only": True,
            "model_path": entry.path,
            "pamt_path": str(pamt_path),
            "normal_mode": normal_mode,
            "edit_mode": edit_mode,
            "material_update": latest_update,
            "material_update_count": len(material_updates),
            "material_failures": material_failures,
            "lifecycle_counts": lifecycle,
            "runtime_diagnostics": mesh_editor_tab._embedded_dotnet_runtime_diagnostics(),
            "archive_fingerprints_before": fingerprints_before,
            "archive_fingerprints_after": fingerprints_after,
            "archive_sources_unchanged": archives_unchanged,
        }
    except Exception as exc:
        construction_context = (
            getattr(dialog, "_cdmw_builder_construction_context", {})
            if dialog is not None
            else {}
        )
        alignment_state = (
            construction_context.get("alignment_d3d11_state", {})
            if isinstance(construction_context, Mapping)
            else {}
        )
        if not isinstance(alignment_state, Mapping):
            alignment_state = {}
        try:
            runtime_diagnostics = mesh_editor_tab._embedded_dotnet_runtime_diagnostics()
        except (AttributeError, RuntimeError, TypeError, ValueError) as diagnostics_exc:
            runtime_diagnostics = {"diagnostics_error": str(diagnostics_exc)}
        from cdmw.core.texture_native import (
            directxtex_texture_failure_reports,
            find_directxtex_texture_binary,
        )

        fingerprints_after = {
            str(path): _sha256(path) for path in fingerprint_paths if path.is_file()
        }
        failure_diagnostics = {
            "schema": "cdmw_packaged_mesh_texture_failure_v1",
            "error": str(exc),
            "model_path": entry.path,
            "pamt_path": str(pamt_path),
            "embedded_state": str(
                getattr(mesh_editor_tab, "standalone_dotnet_embedded_state", "") or ""
            ),
            "process_running": bool(
                mesh_editor_tab._standalone_dotnet_editor_process_running()
            ),
            "package_worker_active": bool(
                mesh_editor_tab._standalone_dotnet_package_worker_active()
            ),
            "runtime_diagnostics": runtime_diagnostics,
            "texture_decoder": {
                "preview_deferred": bool(
                    os.environ.get("CDMW_DEFER_TEXTURE_PREVIEW", "").strip()
                ),
                "helper_path": str(find_directxtex_texture_binary() or ""),
                "recent_failures": list(
                    directxtex_texture_failure_reports()[-16:]
                ),
            },
            "status_payload": getattr(
                mesh_editor_tab, "standalone_dotnet_status_payload", {}
            ),
            "lifecycle_counts": getattr(
                mesh_editor_tab, "standalone_dotnet_lifecycle_counts", {}
            ),
            "texture_resources_ready_by_role": getattr(
                mesh_editor_tab,
                "standalone_dotnet_texture_resources_ready_by_role",
                {},
            ),
            "material_errors_by_role": getattr(
                mesh_editor_tab, "standalone_dotnet_material_error_by_role", {}
            ),
            "alignment_state": {
                str(key): alignment_state.get(key)
                for key in (
                    "request_id",
                    "preview_loaded",
                    "resources_loaded",
                    "preview_pipeline_stage",
                    "package_quality",
                    "active_package_quality",
                    "active_package_display_mode",
                    "last_cache_event",
                    "last_cache_reason",
                    "last_rebuild_reason",
                    "prepare_ms",
                    "package_ms",
                    "loading_percent",
                    "loading_stage",
                    "loading_message",
                )
            },
            "recent_runtime_events": [
                {"event": event, **fields} for event, fields in events[-160:]
            ],
            "archive_fingerprints_before": fingerprints_before,
            "archive_fingerprints_after": fingerprints_after,
            "archive_sources_unchanged": fingerprints_before == fingerprints_after,
        }
        failure_path = output_root / "failure-diagnostics.json"
        try:
            failure_path.write_text(
                json.dumps(failure_diagnostics, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except OSError as write_exc:
            raise RuntimeError(
                f"{exc} Failure diagnostics could not be written: {write_exc}"
            ) from exc
        raise RuntimeError(f"{exc} Failure diagnostics: {failure_path}") from exc
    finally:
        window._record_runtime_event = original_recorder
        if mesh_event_signal is not None:
            try:
                mesh_event_signal.disconnect(capture_mesh_runtime_event)
            except RuntimeError:
                pass
        if dialog is not None:
            try:
                dialog.reject()
                app.processEvents()
            except RuntimeError:
                pass


__all__ = ["verify_packaged_mesh_texture_smoke_target"]
