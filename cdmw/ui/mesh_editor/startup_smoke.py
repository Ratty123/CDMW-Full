"""Feature-owned Mesh Editor startup smoke implementation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget


def _run_mesh_editor_startup_worker(worker: object, label: str) -> tuple[object, ...]:
    completed_payloads: list[tuple[object, ...]] = []
    errors: list[str] = []
    cancelled: list[str] = []
    worker.completed.connect(lambda _request_id, *payload: completed_payloads.append(tuple(payload)))
    worker.error.connect(lambda _request_id, message: errors.append(str(message)))
    cancel_signal = getattr(worker, "cancelled", None)
    if cancel_signal is not None:
        cancel_signal.connect(lambda _request_id, message: cancelled.append(str(message)))
    worker.run()
    if errors:
        raise RuntimeError(f"Mesh Editor startup smoke failed: {label} failed: {errors[-1]}")
    if cancelled:
        raise RuntimeError(f"Mesh Editor startup smoke failed: {label} cancelled: {cancelled[-1]}")
    if not completed_payloads:
        raise RuntimeError(f"Mesh Editor startup smoke failed: {label} did not complete.")
    return completed_payloads[-1]


def _verify_mesh_editor_asset_rebuild_startup_smoke(
    mesh_editor_tab: object,
    asset_path: Path,
) -> None:
    controller = getattr(mesh_editor_tab, "standalone_controller", None)
    service = getattr(controller, "mesh_service", None)
    session_id = str(getattr(controller, "active_session_id", "") or "")
    if service is None or not session_id:
        raise RuntimeError("Mesh Editor startup smoke failed: loaded file has no active service session.")

    from cdmw.workers.mesh_editor_workers import (
        MeshEditablePackageExportWorker,
        MeshEditablePackageImportWorker,
        MeshRebuildReportWorker,
    )

    with tempfile.TemporaryDirectory(prefix="cdmw-mesh-editor-startup-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        package_dir = temp_root / "editable_package"
        rebuilt_path = temp_root / f"{asset_path.stem}.rebuilt{asset_path.suffix or '.pac'}"

        export_payload = _run_mesh_editor_startup_worker(
            MeshEditablePackageExportWorker(1, service, session_id, package_dir),
            "editable package export",
        )
        export_result = export_payload[0] if export_payload else {}
        if not isinstance(export_result, dict):
            raise RuntimeError("Mesh Editor startup smoke failed: editable package export returned no result.")
        for key in ("mesh_path", "metadata_path", "original_asset_hash_path"):
            exported_path = Path(export_result.get(key, ""))
            if not exported_path.is_file():
                raise RuntimeError(f"Mesh Editor startup smoke failed: editable package missing {key}.")

        import_payload = _run_mesh_editor_startup_worker(
            MeshEditablePackageImportWorker(2, service, session_id, package_dir),
            "editable package import",
        )
        validation = import_payload[1] if len(import_payload) > 1 else None
        if validation is None:
            raise RuntimeError("Mesh Editor startup smoke failed: editable package import returned no validation.")
        if not bool(getattr(validation, "ok", False)):
            blockers = tuple(getattr(validation, "blockers", ()) or ())
            codes = ", ".join(str(getattr(issue, "code", issue)) for issue in blockers[:6])
            raise RuntimeError(
                "Mesh Editor startup smoke failed: imported editable package validation blocked rebuild"
                + (f": {codes}" if codes else ".")
            )

        rebuild_payload = _run_mesh_editor_startup_worker(
            MeshRebuildReportWorker(
                3,
                service,
                session_id,
                action_text="startup smoke patched asset rebuild",
                output_path=rebuilt_path,
            ),
            "patched asset rebuild",
        )
        rebuild_report = rebuild_payload[0] if rebuild_payload else None
        if not rebuilt_path.is_file() or rebuilt_path.stat().st_size <= 0:
            raise RuntimeError("Mesh Editor startup smoke failed: patched asset rebuild did not write output.")
        if str(getattr(rebuild_report, "validation_status", "") or "").lower() != "passed":
            raise RuntimeError("Mesh Editor startup smoke failed: patched asset rebuild report was not validation-passed.")


def _verify_mesh_editor_asset_dotnet_startup_smoke(mesh_editor_tab: object) -> None:
    controller = getattr(mesh_editor_tab, "standalone_controller", None)
    service = getattr(controller, "mesh_service", None)
    session_id = str(getattr(controller, "active_session_id", "") or "")
    if service is None or not session_id:
        raise RuntimeError("Mesh Editor startup smoke failed: .NET smoke has no active service session.")

    from cdmw.services.mesh_dotnet_experiment import (
        build_mesh_dotnet_experiment_package,
        find_mesh_dotnet_experiment_editor,
        import_mesh_dotnet_experiment_output,
        mesh_dotnet_experiment_command,
        write_mesh_dotnet_experiment_evaluation,
    )

    executable = find_mesh_dotnet_experiment_editor()
    if executable is None or not executable.is_file():
        raise RuntimeError("Mesh Editor startup smoke failed: .NET experiment executable is missing.")

    with tempfile.TemporaryDirectory(prefix="cdmw-mesh-editor-dotnet-startup-smoke-") as temp_dir:
        mesh = service.working_mesh(session_id, clone=True)
        package = build_mesh_dotnet_experiment_package(mesh, output_root=Path(temp_dir))
        program, arguments = mesh_dotnet_experiment_command(executable, package)
        result = subprocess.run(
            [program, *arguments, "--headless-smoke"],
            cwd=package.package_dir,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Mesh Editor startup smoke failed: .NET experiment exited {result.returncode}.")
        if not package.status_path.is_file():
            raise RuntimeError("Mesh Editor startup smoke failed: .NET experiment did not write status JSON.")
        payload = json.loads(package.status_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise RuntimeError("Mesh Editor startup smoke failed: .NET experiment status JSON is not an object.")
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            raise RuntimeError("Mesh Editor startup smoke failed: .NET experiment did not report metrics.")
        for metric_name in ("average_fps", "frame_time_ms"):
            try:
                metric_value = float(metrics.get(metric_name) or 0)
            except (TypeError, ValueError, OverflowError):
                metric_value = 0.0
            if metric_value <= 0.0:
                raise RuntimeError(
                    f"Mesh Editor startup smoke failed: .NET experiment metric {metric_name} was not positive."
                )
        if "responsiveness_ms" not in metrics:
            raise RuntimeError("Mesh Editor startup smoke failed: .NET experiment did not report responsiveness_ms.")
        edited_mesh = import_mesh_dotnet_experiment_output(package, payload)
        if edited_mesh is None:
            raise RuntimeError("Mesh Editor startup smoke failed: .NET experiment did not produce an edited mesh.")
        operations = tuple(getattr(edited_mesh, "_cdmw_edit_operations", ()) or ())
        if not any(
            callable(getattr(operation, "get", None))
            and operation.get("operation") == "replace_positions_same_count"
            for operation in operations
        ):
            raise RuntimeError(
                "Mesh Editor startup smoke failed: .NET experiment did not produce a same-count position operation."
            )
        updated = service.replace_working_mesh(session_id, edited_mesh)
        validation = service.validate_export(str(getattr(updated, "session_id", "") or session_id))
        evaluation_path = write_mesh_dotnet_experiment_evaluation(
            package,
            payload,
            validation_report=validation,
        )
        if not evaluation_path.is_file():
            raise RuntimeError("Mesh Editor startup smoke failed: .NET experiment did not write evaluation.")
        if not bool(getattr(validation, "ok", False)):
            blockers = tuple(getattr(validation, "blockers", ()) or ())
            codes = ", ".join(str(getattr(issue, "code", issue)) for issue in blockers[:6])
            raise RuntimeError(
                "Mesh Editor startup smoke failed: .NET experiment output validation blocked rebuild"
                + (f": {codes}" if codes else ".")
            )


def verify_mesh_editor_startup_smoke_target(window: object, app: QApplication) -> None:
    assets_tabs = getattr(window, "assets_tabs", None)
    mesh_editor_tab = getattr(window, "mesh_editor_tab", None)
    if assets_tabs is None or mesh_editor_tab is None:
        raise RuntimeError("Mesh Editor startup smoke failed: Mesh Editor tab is not registered.")
    index = int(assets_tabs.indexOf(mesh_editor_tab))
    if index < 0:
        raise RuntimeError("Mesh Editor startup smoke failed: Mesh Editor tab is not in the Assets tabs.")
    assets_tabs.setCurrentIndex(index)
    app.processEvents()
    workspace = getattr(mesh_editor_tab, "standalone_workspace", None)
    if workspace is None:
        workspace = mesh_editor_tab.findChild(QWidget, "MeshEditorStandaloneWorkspace")
    if workspace is None:
        raise RuntimeError("Mesh Editor startup smoke failed: standalone workspace is missing.")
    required_objects = (
        "MeshEditorStandalonePreviewStack",
        "MeshEditorExportEditablePackageButton",
        "MeshEditorImportEditedPackageButton",
        "MeshEditorRunValidationReportButton",
        "MeshEditorRebuildPatchedAssetButton",
        "MeshEditorPreviewRebuiltAssetButton",
        "MeshEditorPackageRebuiltAssetButton",
        "MeshEditorDotNetExperimentButton",
    )
    missing = [name for name in required_objects if workspace.findChild(QWidget, name) is None]
    if missing:
        raise RuntimeError("Mesh Editor startup smoke failed: missing " + ", ".join(missing))
    asset_text = os.environ.get("CDMW_GUI_STARTUP_SMOKE_MESH_ASSET", "").strip()
    if not asset_text:
        return
    asset_path = Path(asset_text).expanduser()
    if not asset_path.is_file():
        raise RuntimeError(f"Mesh Editor startup smoke failed: mesh asset not found: {asset_path}")
    open_file_session = getattr(mesh_editor_tab, "open_mesh_file_session", None)
    if not callable(open_file_session):
        raise RuntimeError("Mesh Editor startup smoke failed: file-session opener is missing.")
    open_file_session(asset_path, session_id="startup-smoke-mesh-editor-file", mode="edit")
    app.processEvents()
    has_session = getattr(mesh_editor_tab, "has_active_standalone_session", None)
    if callable(has_session) and not bool(has_session()):
        raise RuntimeError("Mesh Editor startup smoke failed: loaded file did not create an active session.")
    report = getattr(mesh_editor_tab, "standalone_last_export_validation_report", None)
    if report is None:
        raise RuntimeError("Mesh Editor startup smoke failed: loaded file did not produce validation status.")
    if not bool(getattr(report, "ok", False)):
        raise RuntimeError("Mesh Editor startup smoke failed: loaded file validation blocked rebuild.")
    if str(getattr(report, "no_op_roundtrip_status", "") or "").upper() != "PASS":
        raise RuntimeError("Mesh Editor startup smoke failed: loaded file no-op roundtrip did not pass.")
    if os.environ.get("CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD") == "1":
        _verify_mesh_editor_asset_rebuild_startup_smoke(mesh_editor_tab, asset_path)
    if os.environ.get("CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET") == "1":
        _verify_mesh_editor_asset_dotnet_startup_smoke(mesh_editor_tab)


__all__ = ["verify_mesh_editor_startup_smoke_target"]
