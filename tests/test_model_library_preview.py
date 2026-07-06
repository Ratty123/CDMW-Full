import base64
import json
import os
import shutil
import struct
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from cdmw.models import RunCancelled
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
from cdmw.services.model_library_preview import (
    prepare_model_library_inline_preview,
    prepare_model_library_inline_preview_in_subprocess,
)


def _pad4(data: bytes) -> bytes:
    return data + (b"\x00" * ((4 - (len(data) % 4)) % 4))


def _write_triangle_gltf(root: Path, *, triangle_count: int = 1, with_texture: bool = False) -> Path:
    chunks: list[bytes] = []
    views: list[dict[str, object]] = []

    def add_view(data: bytes, target: int) -> int:
        offset = sum(len(chunk) for chunk in chunks)
        chunks.append(_pad4(data))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        return len(views) - 1

    positions: list[float] = []
    normals: list[float] = []
    uvs: list[float] = []
    indices: list[int] = []
    for index in range(int(triangle_count)):
        base = index * 3
        x = float(index % 40)
        y = float(index // 40)
        positions.extend([x, y, 0.0, x + 1.0, y, 0.0, x, y + 1.0, 0.0])
        normals.extend([0.0, 0.0, 1.0] * 3)
        uvs.extend([0.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        indices.extend([base, base + 1, base + 2])
    position_view = add_view(struct.pack(f"<{len(positions)}f", *positions), 34962)
    normal_view = add_view(struct.pack(f"<{len(normals)}f", *normals), 34962)
    uv_view = add_view(struct.pack(f"<{len(uvs)}f", *uvs), 34962)
    index_view = add_view(struct.pack(f"<{len(indices)}H", *indices), 34963)
    (root / "triangle.bin").write_bytes(b"".join(chunks))
    materials: list[dict[str, object]] = [{"name": "Body"}]
    if with_texture:
        (root / "texture.png").write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        )
        materials = [{"name": "Body", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "triangle.bin", "byteLength": sum(len(chunk) for chunk in chunks)}],
        "bufferViews": views,
        "accessors": [
            {"bufferView": position_view, "componentType": 5126, "count": len(positions) // 3, "type": "VEC3"},
            {"bufferView": normal_view, "componentType": 5126, "count": len(normals) // 3, "type": "VEC3"},
            {"bufferView": uv_view, "componentType": 5126, "count": len(uvs) // 2, "type": "VEC2"},
            {"bufferView": index_view, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
        ],
        "materials": materials,
        "meshes": [
            {
                "name": "Triangle",
                "primitives": [
                    {"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0}
                ],
            }
        ],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if with_texture:
        document["images"] = [{"uri": "texture.png"}]
        document["textures"] = [{"source": 0}]
    path = root / "scene.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class ModelLibraryPreviewServiceTests(unittest.TestCase):
    def test_backend_prepares_d3d11_package_without_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            result = prepare_model_library_inline_preview(scene_path, model_name="Triangle")

            package_dir = Path(str(result["d3d11_package_dir"]))
            self.assertEqual(result["vertices"], 3)
            self.assertEqual(result["faces"], 1)
            self.assertTrue((package_dir / "manifest.json").is_file())

    def test_backend_uses_high_quality_combined_material_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))
            package_dir = Path(tmp) / "package"

            with patch(
                "cdmw.services.model_library_preview.write_isolated_d3d11_preview_package",
                return_value=package_dir,
            ) as writer:
                result = prepare_model_library_inline_preview(
                    scene_path,
                    model_name="Triangle",
                    high_quality_textures=True,
                )

            self.assertEqual(result["d3d11_package_dir"], str(package_dir))
            self.assertTrue(writer.called)
            self.assertTrue(writer.call_args.kwargs["high_quality_textures"])
            self.assertTrue(writer.call_args.kwargs["enable_material_combiner"])

    def test_backend_prepares_fast_d3d11_package_from_gltf_zip_with_texture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset_dir = root / "asset"
            asset_dir.mkdir()
            _write_triangle_gltf(asset_dir, with_texture=True)
            archive_path = root / "wolf_like.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for path in asset_dir.rglob("*"):
                    archive.write(path, path.relative_to(asset_dir).as_posix())

            result = prepare_model_library_inline_preview(
                archive_path,
                extract_root=root / "extract",
                model_name="Zip Texture",
                high_quality_textures=False,
            )

            package_dir = Path(str(result["d3d11_package_dir"]))
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["vertices"], 3)
            self.assertGreaterEqual(int(result["textures"]), 1)
            self.assertFalse(manifest["high_quality_textures"])
            self.assertGreaterEqual(manifest["texture_manifest"]["texture_count"], 1)

    def test_backend_prepares_qt_preview_without_d3d11_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            result = prepare_model_library_inline_preview(scene_path, model_name="Triangle", renderer_backend="qt")

            self.assertEqual(result["vertices"], 3)
            self.assertEqual(result["faces"], 1)
            self.assertEqual(result["d3d11_package_dir"], "")
            self.assertIsNotNone(result["preview_model"])
            self.assertIsNotNone(result["prepared_preview"])

    def test_backend_preview_skips_external_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            with patch(
                "cdmw.modding.scene_material_audit.audit_external_model",
                side_effect=AssertionError("audit should not run"),
            ):
                result = prepare_model_library_inline_preview(scene_path, model_name="Triangle")

            self.assertEqual(result["audit_category"], "")

    def test_backend_preview_reduces_dense_mesh_for_package_speed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)

            result = prepare_model_library_inline_preview(scene_path, model_name="Dense")

            self.assertEqual(result["source_faces"], 1200)
            self.assertLess(result["faces"], result["source_faces"])
            self.assertIsNotNone(result["quality_reduction"])

    def test_native_high_quality_preview_preserves_moderate_mesh_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)

            result = prepare_model_library_inline_preview(
                scene_path,
                model_name="Dense",
                high_quality_textures=True,
            )

            self.assertEqual(result["source_faces"], 1200)
            self.assertEqual(result["faces"], result["source_faces"])
            self.assertIsNone(result["quality_reduction"])

    def test_qprocess_native_host_loads_model_library_package(self) -> None:
        host = find_native_d3d11_host()
        if host is None:
            self.skipTest("native D3D11 host is not built")
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)
            result = prepare_model_library_inline_preview(scene_path, model_name="Dense")
            package_dir = Path(str(result["d3d11_package_dir"]))
            status_file = package_dir / "qprocess_host_status.json"
            app = QApplication.instance() or QApplication([])
            process = QProcess()
            process.setProgram(str(host))
            process.setArguments(
                [
                    "--backend",
                    "d3d11",
                    "--preview-package",
                    str(package_dir),
                    "--status-file",
                    str(status_file),
                ]
            )
            errors: list[str] = []
            process.errorOccurred.connect(lambda error: errors.append(str(error)))
            loaded_payload: dict[str, object] = {}
            try:
                process.start()
                deadline = time.perf_counter() + 12.0
                while time.perf_counter() < deadline:
                    app.processEvents()
                    if status_file.is_file():
                        payload = json.loads(status_file.read_text(encoding="utf-8"))
                        event = str(payload.get("event", "") or "")
                        if event == "loaded":
                            loaded_payload = payload
                            break
                        if event == "error":
                            self.fail(str(payload.get("message", "native host reported error")))
                    if process.state() == QProcess.NotRunning and not loaded_payload:
                        break
                    time.sleep(0.02)
            finally:
                if process.state() != QProcess.NotRunning:
                    process.terminate()
                    if not process.waitForFinished(2000):
                        process.kill()
                        process.waitForFinished(2000)
                shutil.rmtree(package_dir, ignore_errors=True)

        self.assertFalse(errors)
        self.assertEqual(loaded_payload.get("event"), "loaded")
        self.assertGreater(int(loaded_payload.get("vertex_count", 0) or 0), 0)

    def test_backend_preview_honors_pre_cancelled_stop_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))
            stop_event = threading.Event()
            stop_event.set()

            with self.assertRaises(RunCancelled):
                prepare_model_library_inline_preview(scene_path, model_name="Triangle", stop_event=stop_event)

    def test_subprocess_backend_prepares_d3d11_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            result = prepare_model_library_inline_preview_in_subprocess(scene_path, model_name="Triangle")

            package_dir = Path(str(result["d3d11_package_dir"]))
            self.assertEqual(result["vertices"], 3)
            self.assertEqual(result["faces"], 1)
            self.assertTrue((package_dir / "manifest.json").is_file())

    def test_subprocess_backend_passes_cancel_event_and_timeout_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stop_event = threading.Event()
            progress_messages: list[str] = []

            def fake_run_process(command: object, **kwargs: object) -> tuple[int, str, str]:
                self.assertIs(kwargs.get("stop_event"), stop_event)
                self.assertEqual(kwargs.get("timeout_seconds"), 300)
                timeout_warning = kwargs.get("on_timeout_warning")
                self.assertTrue(callable(timeout_warning))
                if callable(timeout_warning):
                    timeout_warning(16.0)
                command_parts = [str(part) for part in tuple(command)]  # type: ignore[arg-type]
                output_path = Path(command_parts[command_parts.index("--output") + 1])
                output_path.write_text(json.dumps({"request_id": 7}), encoding="utf-8")
                return 0, "", ""

            with patch("cdmw.services.model_library_preview.run_process_with_cancellation", side_effect=fake_run_process):
                result = prepare_model_library_inline_preview_in_subprocess(
                    Path(tmp) / "missing.gltf",
                    request_id=7,
                    stop_event=stop_event,
                    progress=progress_messages.append,
                )

            self.assertEqual(result["request_id"], 7)
            self.assertIn("Preparing preview in isolated worker...", progress_messages)
            self.assertIn("Still preparing preview in isolated worker (16s)...", progress_messages)

    def test_subprocess_backend_keeps_qt_event_loop_responsive(self) -> None:
        class _Worker(QObject):
            completed = Signal(object)
            failed = Signal(str)
            finished = Signal()

            def __init__(self, path: Path) -> None:
                super().__init__()
                self.path = path

            @Slot()
            def run(self) -> None:
                try:
                    self.completed.emit(prepare_model_library_inline_preview_in_subprocess(self.path, model_name="Dense"))
                except Exception as exc:
                    self.failed.emit(str(exc))
                finally:
                    self.finished.emit()

        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)
            app = QApplication.instance() or QApplication([])
            ticks: list[float] = []
            result_box: dict[str, object] = {}
            error_box: dict[str, str] = {}
            timer = QTimer()
            timer.setInterval(25)
            timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
            thread = QThread()
            worker = _Worker(scene_path)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.completed.connect(lambda result: result_box.setdefault("result", result))
            worker.failed.connect(lambda message: error_box.setdefault("error", message))
            worker.finished.connect(thread.quit)
            worker.finished.connect(app.quit)
            timer.start()
            thread.start()
            QTimer.singleShot(15000, app.quit)
            app.exec()
            timer.stop()
            if thread.isRunning():
                thread.quit()
                thread.wait(2000)

        self.assertFalse(error_box, error_box.get("error", ""))
        self.assertIsInstance(result_box.get("result"), dict)
        gaps_ms = [(b - a) * 1000.0 for a, b in zip(ticks, ticks[1:])]
        self.assertGreaterEqual(len(ticks), 3)
        self.assertLess(max(gaps_ms) if gaps_ms else 0.0, 500.0)


if __name__ == "__main__":
    unittest.main()
