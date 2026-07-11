"""Native D3D11 preview process helpers for archive preview hosts."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QWidget

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_TEXT_COLOR
from cdmw.services.preview_rendering_service import (
    find_native_d3d11_host,
    is_durable_native_preview_package_path,
)
from cdmw.services.workspace_layout import workspace_paths


class ArchivePreviewD3D11ProcessMixin:
    """QProcess and command-line helpers for native D3D11 archive previews."""

    def _archive_isolated_renderer_process_running(self) -> bool:
        process = getattr(self, "archive_isolated_renderer_process", None)
        if process is None:
            return False
        try:
            return process.state() != QProcess.NotRunning
        except RuntimeError:
            return False

    def _archive_isolated_renderer_sender_is_current(self) -> bool:
        try:
            sender = self.sender()
        except RuntimeError:
            sender = None
        if sender is None:
            return True
        return sender is getattr(self, "archive_isolated_renderer_process", None)

    def _archive_qprocess_state(self, process: Optional[QProcess]) -> object:
        if process is None:
            return QProcess.NotRunning
        try:
            return process.state()
        except RuntimeError:
            return QProcess.NotRunning

    def _archive_qprocess_pid(self, process: Optional[QProcess]) -> object:
        if process is None:
            return ""
        try:
            return int(process.processId())
        except RuntimeError:
            return "deleted"

    def _delete_archive_qprocess_later(self, process: Optional[QProcess]) -> None:
        if process is None:
            return
        try:
            process.deleteLater()
        except RuntimeError:
            pass

    def _release_archive_d3d11_package_leases(self) -> None:
        release_leases = getattr(
            getattr(self, "archive_d3d11_preview_host", None),
            "release_native_preview_package_cache_leases",
            None,
        )
        if callable(release_leases):
            release_leases()

    def _cleanup_archive_isolated_renderer_packages(self, *, include_active: bool = False) -> None:
        retired = list(getattr(self, "archive_isolated_renderer_retired_packages", []) or [])
        if include_active and getattr(self, "archive_isolated_renderer_active_package", None) is not None:
            retired.append(self.archive_isolated_renderer_active_package)
            self.archive_isolated_renderer_active_package = None
            self.archive_isolated_renderer_active_process = None
            self.archive_isolated_renderer_status_file = None
            self.archive_isolated_renderer_status_signature = (0, 0)
            self.archive_isolated_renderer_status_payload_text = ""
            self.archive_isolated_renderer_last_status_payload = {}
            self.archive_isolated_renderer_package_source = ""
            self.archive_d3d11_active_model_key = ""
        if include_active and getattr(self, "archive_isolated_renderer_pending_package", None) is not None:
            retired.append(self.archive_isolated_renderer_pending_package)
            self.archive_isolated_renderer_pending_package = None
            self.archive_isolated_renderer_pending_status_file = None
            self.archive_isolated_renderer_pending_package_source = ""
            self.archive_d3d11_pending_model_key = ""
        self.archive_isolated_renderer_retired_packages = []
        for package_dir in retired:
            try:
                shutil.rmtree(package_dir, ignore_errors=True)
            except OSError:
                pass

    def _set_archive_d3d11_pending_package(
        self,
        package_dir: Path,
        status_file: Path,
        source: str,
        model_key: str = "",
    ) -> None:
        self.archive_isolated_renderer_pending_package = Path(package_dir)
        self.archive_isolated_renderer_pending_status_file = Path(status_file)
        self.archive_isolated_renderer_pending_package_source = str(source or "").strip()
        self.archive_d3d11_pending_model_key = str(model_key or "").strip()

    def _promote_archive_d3d11_pending_package_if_loaded(self, status_file: Path) -> None:
        pending_status = getattr(self, "archive_isolated_renderer_pending_status_file", None)
        pending_package = getattr(self, "archive_isolated_renderer_pending_package", None)
        if pending_status is None or pending_package is None or Path(pending_status) != Path(status_file):
            return
        previous = getattr(self, "archive_isolated_renderer_active_package", None)
        if previous is not None and Path(previous) != Path(pending_package):
            self.archive_isolated_renderer_retired_packages.append(previous)
        self.archive_isolated_renderer_active_package = Path(pending_package)
        pending_source = str(getattr(self, "archive_isolated_renderer_pending_package_source", "") or "").strip()
        if pending_source:
            self.archive_isolated_renderer_package_source = pending_source
        pending_model_key = str(getattr(self, "archive_d3d11_pending_model_key", "") or "").strip()
        if not pending_model_key:
            pending_model_key = self._d3d11_preview_package_model_key(Path(pending_package))
        if pending_model_key:
            self.archive_d3d11_active_model_key = pending_model_key
        self.archive_isolated_renderer_pending_package = None
        self.archive_isolated_renderer_pending_status_file = None
        self.archive_isolated_renderer_pending_package_source = ""
        self.archive_d3d11_pending_model_key = ""
        retain_package = getattr(
            getattr(self, "archive_d3d11_preview_host", None),
            "retain_native_preview_package_cache_lease",
            None,
        )
        if callable(retain_package):
            retain_package(Path(pending_package))

    def _discard_archive_d3d11_pending_package(self, status_file: Optional[Path] = None) -> bool:
        pending_status = getattr(self, "archive_isolated_renderer_pending_status_file", None)
        pending_package = getattr(self, "archive_isolated_renderer_pending_package", None)
        if pending_package is None:
            return False
        if status_file is not None and pending_status is not None and Path(pending_status) != Path(status_file):
            return False
        self.archive_isolated_renderer_pending_package = None
        self.archive_isolated_renderer_pending_status_file = None
        self.archive_isolated_renderer_pending_package_source = ""
        self.archive_d3d11_pending_model_key = ""
        release_package = getattr(
            getattr(self, "archive_d3d11_preview_host", None),
            "release_native_preview_package_cache_lease",
            None,
        )
        if callable(release_package):
            release_package(Path(pending_package))
        self._remove_archive_isolated_package_dir(Path(pending_package))
        return True

    def _remove_archive_isolated_package_dir(self, package_dir: Optional[Path]) -> None:
        if package_dir is None:
            return
        package_dir = Path(package_dir)
        cache_root = getattr(self, "_native_preview_package_cache_root", lambda: None)()
        if cache_root is not None and is_durable_native_preview_package_path(Path(cache_root), package_dir):
            return
        removable_root = package_dir
        try:
            parent = package_dir.parent
            if package_dir.name == "package" and parent.name.startswith("cdmw_preview_core_"):
                removable_root = parent
        except Exception:
            removable_root = package_dir
        try:
            shutil.rmtree(removable_root, ignore_errors=True)
        except OSError:
            pass

    def _kill_archive_isolated_renderer_process_if_running(self, process: QProcess) -> None:
        try:
            if self._archive_qprocess_state(process) != QProcess.NotRunning:
                recorder = getattr(self, "_record_runtime_event", None)
                if callable(recorder):
                    recorder(
                        "d3d11_process_kill",
                        process_pid=self._archive_qprocess_pid(process),
                    )
                process.kill()
        except RuntimeError:
            pass

    def _clear_archive_isolated_renderer_surface_for_request(self) -> None:
        self._clear_archive_d3d11_part_visibility_menu()
        if not self._archive_isolated_renderer_process_running():
            self.archive_d3d11_preview_status_label.setText("Preparing native D3D11 preview package...")
            return
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(
                "d3d11_preview_clear_for_new_request",
                request_id=self.archive_preview_request_id,
                active_package=str(getattr(self, "archive_isolated_renderer_active_package", "") or ""),
                status_file=str(getattr(self, "archive_isolated_renderer_status_file", "") or ""),
            )
        self.archive_d3d11_preview_status_label.setText("Preparing native D3D11 preview package...")
        self._set_archive_isolated_renderer_debug(
            "Native D3D11 Preview: keeping the current model visible while the next package is prepared."
        )

    def _show_archive_d3d11_hard_failure(self, reason: str) -> bool:
        message = str(reason or "Native D3D11 preview failed.").strip()
        self.archive_d3d11_preview_status_label.setText(message)
        self._set_archive_isolated_renderer_debug(message)
        self.set_status_message(message, error=True)
        return False

    def _cleanup_finished_archive_isolated_renderer_process(
        self,
        process: Optional[QProcess],
        package_dir: Optional[Path],
    ) -> None:
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(
                "d3d11_process_cleanup_finished",
                package_dir=str(package_dir or ""),
                process_pid=self._archive_qprocess_pid(process),
            )
        self._remove_archive_isolated_package_dir(package_dir)
        self._delete_archive_qprocess_later(process)

    def _native_d3d11_renderer_command(
        self,
        package_dir: Path,
        status_file: Path,
        *,
        host_widget: QWidget,
        theme_payload: Mapping[str, str],
    ) -> Tuple[str, List[str]]:
        host_binary = find_native_d3d11_host()
        if host_binary is None:
            raise FileNotFoundError(
                "Native D3D11 preview host is not built. Build native/cdmw_d3d11_preview or set CDMW_D3D11_PREVIEW_BIN."
            )
        settings_parent = Path(getattr(self, "settings_file_path", Path.cwd())).parent
        crash_dir = Path(os.environ.get("CDMW_CRASH_DIR", str(workspace_paths(settings_parent)["crash_reports_dir"])))
        diagnostic_log = Path(
            os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", str(crash_dir / "native_events_current.jsonl"))
        )
        arguments = [
            "--backend",
            "d3d11",
            "--preview-package",
            str(package_dir),
            "--status-file",
            str(status_file),
            "--theme-background",
            theme_payload["background"],
            "--theme-text",
            theme_payload["text"],
            "--crash-dir",
            str(crash_dir),
            "--diagnostic-log",
            str(diagnostic_log),
        ]
        try:
            host_widget.setAttribute(Qt.WA_NativeWindow, True)
            parent_hwnd = int(host_widget.winId())
        except Exception:
            parent_hwnd = 0
        if parent_hwnd:
            arguments.extend(["--parent-hwnd", str(parent_hwnd)])
        hold_package = getattr(host_widget, "hold_native_preview_package_cache_lease", None)
        if callable(hold_package):
            hold_package(Path(package_dir))
        return str(host_binary), arguments

    def _archive_isolated_renderer_command(self, package_dir: Path, status_file: Path) -> Tuple[str, List[str]]:
        return self._native_d3d11_renderer_command(
            package_dir,
            status_file,
            host_widget=self.archive_d3d11_preview_host,
            theme_payload=self._archive_isolated_renderer_theme_payload(),
        )

    def _archive_isolated_renderer_theme_payload(self) -> Dict[str, str]:
        return {
            "background": MODEL_PREVIEW_BACKGROUND_COLOR,
            "text": MODEL_PREVIEW_TEXT_COLOR,
        }

    def _archive_material_channel_debug_from_package(self, package_dir: object) -> str:
        try:
            manifest_path = Path(package_dir).expanduser() / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        batches = manifest.get("batches", ()) if isinstance(manifest, Mapping) else ()
        if not isinstance(batches, Sequence) or isinstance(batches, (str, bytes)):
            return ""
        lines: List[str] = []

        def _compact_float(value: object) -> str:
            try:
                return f"{float(value):.2f}"
            except (TypeError, ValueError):
                return "?"

        for batch_index, batch in enumerate(tuple(batches)[:12]):
            if not isinstance(batch, Mapping):
                continue
            contract = batch.get("material_channel_contract")
            analysis = batch.get("material_analysis")
            category = str(batch.get("material_category", "") or "").strip()
            confidence_text = _compact_float(batch.get("material_category_confidence"))
            reason = str(batch.get("material_category_reason", "") or "").strip()
            if isinstance(analysis, Mapping):
                category = str(analysis.get("category", "") or category).strip()
                confidence_text = _compact_float(analysis.get("confidence", batch.get("material_category_confidence")))
                reason = str(analysis.get("reason", "") or reason).strip()
            tint_applied = bool(batch.get("visible_layer_tint_applied", False))
            tint_strength = _compact_float(batch.get("base_tint_strength", 0.0))
            response = str(batch.get("material_response_disposition", "") or "").strip()
            material_suffix = ""
            if category or reason or response or tint_applied:
                material_suffix = (
                    f"; material={category or 'generic'}:{confidence_text}; "
                    f"reason={reason or 'unknown'}; tint={'yes' if tint_applied else 'no'}:{tint_strength}; "
                    f"response={response or 'none'}"
                )
            if isinstance(contract, Mapping):
                channels = contract.get("channels", ())
                channel_labels: List[str] = []
                if isinstance(channels, Sequence) and not isinstance(channels, (str, bytes)):
                    for channel in tuple(channels)[:8]:
                        if isinstance(channel, Mapping):
                            label = str(channel.get("sketchfab_channel", "") or channel.get("channel", "") or "").strip()
                            slot = str(channel.get("source_slot", "") or "").strip()
                            confidence = str(channel.get("confidence", "") or "").strip()
                            if label:
                                channel_labels.append(f"{label}:{slot or '?'}:{confidence or '?'}")
                unresolved = contract.get("unresolved", ())
                unresolved_slots: List[str] = []
                if isinstance(unresolved, Sequence) and not isinstance(unresolved, (str, bytes)):
                    for item in tuple(unresolved)[:6]:
                        if isinstance(item, Mapping):
                            slot = str(item.get("slot", "") or "").strip()
                            if slot:
                                unresolved_slots.append(slot)
                material_policy = str(batch.get("material_combiner_policy", "") or "").strip()
                combiner_state = "combiner=on" if bool(batch.get("material_combiner_active", False)) else "combiner=off"
                if material_policy:
                    combiner_state = f"{material_policy}:{combiner_state}"
                lines.append(
                    f"batch {batch_index} {contract.get('workflow', 'unknown')}: "
                    f"{', '.join(channel_labels) or 'no material channels'}; "
                    f"unresolved={', '.join(unresolved_slots) or 'none'}; "
                    f"{combiner_state}{material_suffix}"
                )
            elif material_suffix:
                lines.append(f"batch {batch_index} material: {material_suffix.lstrip('; ')}")
        return "Material Channel Contract: " + " | ".join(lines) if lines else ""

    def _format_archive_isolated_renderer_debug(self, payload: Mapping[str, object]) -> str:
        backend = str(payload.get("backend", "d3d11") or "d3d11").upper()
        package_source = str(getattr(self, "archive_isolated_renderer_package_source", "") or "").strip()

        def _yes_no(value: object) -> str:
            return "yes" if bool(value) else "no"

        textures = payload.get("textures", {})
        if isinstance(textures, Mapping):
            texture_text = " ".join(
                f"{slot}:{int(count)}"
                for slot, count in sorted(textures.items())
                if int(count or 0) > 0
            ) or "none"
        else:
            texture_text = "none"
        skipped = tuple(str(item) for item in tuple(payload.get("skipped", ()) or ()) if str(item))
        skipped_text = "; ".join(skipped[:8]) if skipped else "none"
        texture_details = tuple(
            str(item)
            for item in tuple(payload.get("texture_details", ()) or ())
            if str(item).strip()
        )
        texture_details_text = "; ".join(texture_details[:10]) if texture_details else "none"
        failed_textures_raw = payload.get("failed_textures", ())
        failed_texture_lines: List[str] = []
        if isinstance(failed_textures_raw, Sequence) and not isinstance(failed_textures_raw, (str, bytes)):
            for item in tuple(failed_textures_raw)[:8]:
                if isinstance(item, Mapping):
                    slot = str(item.get("slot", "") or "?")
                    source_kind = str(item.get("source_kind", "") or "?")
                    stage = str(item.get("stage", "") or "?")
                    hresult = str(item.get("hresult", "") or "")
                    required = "required" if bool(item.get("required", False)) else "optional"
                    path = Path(str(item.get("path", "") or "")).name
                    failed_texture_lines.append(f"{slot}:{source_kind}:{stage}:{hresult}:{required}:{path}")
                elif str(item).strip():
                    failed_texture_lines.append(str(item).strip())
        failed_texture_text = "; ".join(failed_texture_lines) if failed_texture_lines else "none"
        texture_failure_count = int(payload.get("texture_failures", 0) or 0)
        required_texture_failure_count = int(payload.get("required_texture_failures", 0) or 0)
        texture_integrity = str(payload.get("texture_integrity", "ok") or "ok")
        cache_hits = int(payload.get("texture_cache_hits", 0) or 0)
        cache_entries = int(payload.get("texture_cache_entries", 0) or 0)
        texture_bytes = int(payload.get("estimated_texture_bytes", 0) or 0)
        private_bytes = int(payload.get("process_private_bytes", 0) or 0)
        low_res_base_count = int(payload.get("low_resolution_base_textures", 0) or 0)
        cloth_batch_count = int(payload.get("cloth_batch_count", 0) or 0)
        cloth_particle_count = int(payload.get("cloth_particle_count", 0) or 0)
        cloth_constraint_count = int(payload.get("cloth_constraint_count", 0) or 0)
        cloth_collider_count = int(payload.get("cloth_collider_count", 0) or 0)
        pbd_hint_count = int(payload.get("pbd_hint_count", 0) or 0)
        pbd_soft_hint_count = int(payload.get("pbd_soft_hint_count", 0) or 0)
        pbd_cloth_hint_count = int(payload.get("pbd_cloth_hint_count", 0) or 0)
        cloth_step_count = int(payload.get("cloth_simulation_steps", 0) or 0)
        srgb_color_uploads = int(payload.get("srgb_color_uploads", 0) or 0)
        linear_data_uploads = int(payload.get("linear_data_uploads", 0) or 0)
        sampler_max_anisotropy = int(payload.get("sampler_max_anisotropy", 0) or 0)
        sampler_recreate_count = int(payload.get("sampler_recreate_count", 0) or 0)
        sampler_mip_lod_bias = float(payload.get("sampler_mip_lod_bias", 0.0) or 0.0)
        device_lost = bool(payload.get("device_lost", False))
        device_loss_stage = str(payload.get("device_loss_stage", payload.get("stage", "")) or "")
        device_loss_hresult = str(payload.get("device_loss_hresult", "") or "")
        device_removed_reason = str(payload.get("device_removed_reason", "") or "")
        material_contract_schema = int(payload.get("material_contract_schema", 0) or 0)
        material_channel_contract_schema = int(payload.get("material_channel_contract_schema", 0) or 0)
        texture_quality_schema = int(payload.get("texture_quality_schema", 0) or 0)
        cloth_runtime_schema = int(payload.get("cloth_runtime_schema", 0) or 0)
        render_diagnostic_mode = str(payload.get("render_diagnostic_mode", "") or "lit")
        lighting_preset = str(payload.get("lighting_preset", "") or "neutral_studio")
        physics_overlay_enabled = bool(payload.get("physics_overlay_enabled", False))
        physics_overlay_cloth = bool(payload.get("physics_overlay_cloth", False))
        physics_shape_count = int(payload.get("physics_shape_count", 0) or 0)
        physics_anchor_count = int(payload.get("physics_anchor_count", 0) or 0)
        physics_constraint_count = int(payload.get("physics_constraint_count", 0) or 0)
        skeleton_bone_count = int(payload.get("skeleton_bone_count", 0) or 0)
        editable_value_group_count = int(payload.get("editable_value_group_count", 0) or 0)
        semantic_writes_enabled = bool(payload.get("semantic_writes_enabled", False))
        combiner_outputs = payload.get("material_combiner_outputs", {})
        if isinstance(combiner_outputs, Mapping):
            combiner_output_text = " ".join(
                f"{slot}:{int(count)}"
                for slot, count in sorted(combiner_outputs.items())
                if int(count or 0) > 0
            ) or "none"
        else:
            combiner_output_text = "none"
        combiner_modes = payload.get("material_combiner_decode_modes", {})
        if isinstance(combiner_modes, Mapping):
            combiner_mode_text = ",".join(
                str(mode)
                for mode, count in sorted(combiner_modes.items())
                if int(count or 0) > 0
            ) or "none"
        else:
            combiner_mode_text = "none"
        layer_roles = payload.get("material_layer_roles", {})
        if isinstance(layer_roles, Mapping):
            layer_role_text = " ".join(
                f"{role}:{int(count)}"
                for role, count in sorted(layer_roles.items())
                if int(count or 0) > 0
            ) or "none"
        else:
            layer_role_text = "none"
        material_channel_text = self._archive_material_channel_debug_from_package(
            getattr(self, "archive_isolated_renderer_active_package", None)
        )
        if cloth_batch_count > 0:
            pbd_runtime_status = "runtime"
        elif pbd_hint_count > 0:
            pbd_runtime_status = "metadata-only"
        else:
            pbd_runtime_status = "none"
        return (
            "Native D3D11 Preview: embedded child process; "
            f"backend={backend}; batches={int(payload.get('batch_count', 0) or 0):,}; "
            f"vertices={int(payload.get('vertex_count', 0) or 0):,}; textures={texture_text}\n"
            f"D3D11 package source: {package_source or 'unknown'}\n"
            "Native D3D11 Timing: "
            f"manifest={float(payload.get('manifest_read_ms', 0.0) or 0.0):.1f} ms; "
            f"textures={float(payload.get('texture_bind_ms', 0.0) or 0.0):.1f} ms; "
            f"geometry={float(payload.get('geometry_upload_ms', 0.0) or 0.0):.1f} ms; "
            f"first_frame={float(payload.get('first_frame_ms', 0.0) or 0.0):.1f} ms; "
            f"cache_hits={cache_hits:,}; cache_entries={cache_entries:,}; low_res_base={low_res_base_count:,}\n"
            "Native D3D11 Memory: "
            f"texture_est={texture_bytes / (1024 * 1024):.1f} MiB; "
            f"private={private_bytes / (1024 * 1024):.1f} MiB\n"
            "Native D3D11 Texture Space: "
            f"base_srgb={srgb_color_uploads:,}; data_linear={linear_data_uploads:,}\n"
            "Native D3D11 Sampler: "
            f"anisotropy={sampler_max_anisotropy}; mip_lod_bias={sampler_mip_lod_bias:.2f}; recreates={sampler_recreate_count}\n"
            "Native D3D11 Preview Contract: "
            f"device_lost={_yes_no(device_lost)}; stage={device_loss_stage or 'none'}; hresult={device_loss_hresult or 'none'}; removed={device_removed_reason or 'none'}; "
            f"material_schema={material_contract_schema}; material_channel_schema={material_channel_contract_schema}; "
            f"texture_schema={texture_quality_schema}; "
            f"cloth_schema={cloth_runtime_schema}; diagnostic={render_diagnostic_mode}; lighting={lighting_preset}\n"
            + (f"{material_channel_text}\n" if material_channel_text else "")
            +
            f"Native D3D11 Texture Details: {texture_details_text}\n"
            f"Native D3D11 Texture Integrity: {texture_integrity}; required_failures={required_texture_failure_count:,}\n"
            f"Native D3D11 Texture Failures: {texture_failure_count:,}; {failed_texture_text}\n"
            "Native D3D11 Material Layers: "
            f"active_batches={int(payload.get('material_layer_active', 0) or 0):,}; "
            f"layers={int(payload.get('material_layer_count', 0) or 0):,}; roles={layer_role_text}\n"
            "Native D3D11 Material Combiner: "
            f"active_batches={int(payload.get('material_combiner_active', 0) or 0):,}; "
            f"outputs={combiner_output_text}; decode={combiner_mode_text}\n"
            "Native D3D11 PBD Physics Preview: "
            f"status={pbd_runtime_status}; hints={pbd_hint_count:,}; soft_hints={pbd_soft_hint_count:,}; cloth_hints={pbd_cloth_hint_count:,}; "
            f"batches={cloth_batch_count:,}; particles={cloth_particle_count:,}; "
            f"constraints={cloth_constraint_count:,}; colliders={cloth_collider_count:,}; steps={cloth_step_count:,}\n"
            "Native D3D11 Overlay Metadata: "
            f"physics_enabled={_yes_no(physics_overlay_enabled)}; cloth={_yes_no(physics_overlay_cloth)}; "
            f"shapes={physics_shape_count:,}; anchors={physics_anchor_count:,}; hkx_constraints={physics_constraint_count:,}; "
            f"skeleton_bones={skeleton_bone_count:,}; editable_groups={editable_value_group_count:,}; "
            f"semantic_writes={_yes_no(semantic_writes_enabled)}\n"
            f"Native D3D11 Material Notes: skipped={skipped_text}"
        )
