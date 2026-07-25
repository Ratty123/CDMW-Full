import json
import os
import struct
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from cdmw.models import ModelPreviewRenderSettings, RunCancelled
from cdmw.services.mesh_dotnet_preview_package import validate_dotnet_preview_package
from cdmw.services.model_library_preview import (
    prepare_model_library_inline_preview,
    prepare_model_library_inline_preview_in_subprocess,
)
from tests.scene_gltf_test_support import valid_image_bytes


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
        (root / "texture.png").write_bytes(valid_image_bytes())
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
    def test_backend_prepares_dotnet_package_without_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            result = prepare_model_library_inline_preview(scene_path, model_name="Triangle")

            package_dir = Path(str(result["dotnet_preview_package_path"]))
            self.assertEqual(result["vertices"], 3)
            self.assertEqual(result["faces"], 1)
            self.assertTrue(validate_dotnet_preview_package(package_dir)[0])

    def test_backend_uses_high_quality_combined_material_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))
            package_dir = Path(tmp) / "package"

            package = type("Package", (), {"package_dir": package_dir})()
            with patch(
                "cdmw.services.model_library_preview.build_or_lookup_dotnet_preview_package_from_model",
                return_value=package,
            ) as writer:
                result = prepare_model_library_inline_preview(
                    scene_path,
                    model_name="Triangle",
                    high_quality_textures=True,
                )

            self.assertEqual(result["dotnet_preview_package_path"], str(package_dir))
            self.assertTrue(writer.called)
            self.assertEqual(writer.call_args.kwargs["cache_mode"], "balanced")
            self.assertGreater(int(writer.call_args.kwargs["max_bytes"]), 0)
            self.assertGreater(int(writer.call_args.kwargs["target_bytes"]), 0)
            self.assertEqual(writer.call_args.kwargs["metadata"]["surface"], "model_library")

    def test_backend_package_identity_is_stable_per_source_revision_and_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))
            package = type("Package", (), {"package_dir": Path(tmp) / "package"})()

            def identity_for(flip_v: bool) -> str:
                render_settings = ModelPreviewRenderSettings()
                render_settings.flip_texture_v = flip_v
                with patch(
                    "cdmw.services.model_library_preview.build_or_lookup_dotnet_preview_package_from_model",
                    return_value=package,
                ) as writer:
                    prepare_model_library_inline_preview(
                        scene_path,
                        model_name="Triangle",
                        render_settings=render_settings,
                    )
                return str(writer.call_args.kwargs["archive_identity"])

            self.assertEqual(identity_for(False), identity_for(False))
            self.assertNotEqual(identity_for(False), identity_for(True))

            before_touch = identity_for(False)
            touched_at = time.time() + 5.0
            os.utime(scene_path, (touched_at, touched_at))
            self.assertNotEqual(before_touch, identity_for(False))

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

            package_dir = Path(str(result["dotnet_preview_package_path"]))
            materials = json.loads((package_dir / "net_materials.json").read_text(encoding="utf-8"))
            self.assertEqual(result["vertices"], 3)
            self.assertGreaterEqual(int(result["textures"]), 1)
            self.assertFalse(result["high_quality_textures"])
            self.assertGreaterEqual(len(materials["resources"]), 1)

    def test_backend_rejects_legacy_qt_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            with self.assertRaisesRegex(ValueError, "Unsupported model preview renderer"):
                prepare_model_library_inline_preview(scene_path, model_name="Triangle", renderer_backend="qt")

    def test_backend_preview_skips_external_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            with patch(
                "cdmw.modding.scene_material_audit.audit_external_model",
                side_effect=AssertionError("audit should not run"),
            ):
                result = prepare_model_library_inline_preview(scene_path, model_name="Triangle")

            self.assertEqual(result["audit_category"], "")

    def test_legacy_qt_renderer_is_not_a_dense_mesh_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)

            with self.assertRaisesRegex(ValueError, "Unsupported model preview renderer"):
                prepare_model_library_inline_preview(scene_path, model_name="Dense", renderer_backend="qt")

    def test_native_fast_texture_preview_preserves_moderate_mesh_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)

            result = prepare_model_library_inline_preview(
                scene_path,
                model_name="Dense",
                high_quality_textures=False,
            )

            self.assertEqual(result["source_faces"], 1200)
            self.assertEqual(result["faces"], result["source_faces"])
            self.assertIsNone(result["quality_reduction"])

    def test_dotnet_package_contains_scene_and_material_authority_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)
            result = prepare_model_library_inline_preview(scene_path, model_name="Dense")
            package_dir = Path(str(result["dotnet_preview_package_path"]))
            self.assertTrue((package_dir / "dotnet_scene.json").is_file())
            self.assertTrue((package_dir / "net_materials.json").is_file())
            self.assertTrue(validate_dotnet_preview_package(package_dir)[0])

    def test_backend_preview_honors_pre_cancelled_stop_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))
            stop_event = threading.Event()
            stop_event.set()

            with self.assertRaises(RunCancelled):
                prepare_model_library_inline_preview(scene_path, model_name="Triangle", stop_event=stop_event)

    def test_subprocess_backend_prepares_dotnet_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp))

            result = prepare_model_library_inline_preview_in_subprocess(scene_path, model_name="Triangle")

            package_dir = Path(str(result["dotnet_preview_package_path"]))
            self.assertEqual(result["vertices"], 3)
            self.assertEqual(result["faces"], 1)
            self.assertTrue(validate_dotnet_preview_package(package_dir)[0])

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
        class _Receiver(QObject):
            def __init__(
                self,
                loop: QEventLoop,
                stop_event: threading.Event,
                start_gate: threading.Event,
                ticks: list[float],
            ) -> None:
                super().__init__()
                self.loop = loop
                self.stop_event = stop_event
                self.start_gate = start_gate
                self.ticks = ticks
                self.result: object | None = None
                self.error = ""
                self.finished = False
                self.timed_out = False

            @Slot()
            def handle_tick(self) -> None:
                self.ticks.append(time.perf_counter())
                if len(self.ticks) >= 3:
                    self.start_gate.set()

            @Slot(object)
            def handle_completed(self, result: object) -> None:
                self.result = result

            @Slot(str)
            def handle_failed(self, message: str) -> None:
                self.error = message

            @Slot()
            def handle_finished(self) -> None:
                self.finished = True
                self.loop.quit()

            @Slot()
            def handle_timeout(self) -> None:
                self.timed_out = True
                self.stop_event.set()
                self.start_gate.set()
                self.loop.quit()

        class _Worker(QObject):
            completed = Signal(object)
            failed = Signal(str)
            finished = Signal()

            def __init__(
                self,
                path: Path,
                stop_event: threading.Event,
                start_gate: threading.Event,
            ) -> None:
                super().__init__()
                self.path = path
                self.stop_event = stop_event
                self.start_gate = start_gate

            @Slot()
            def run(self) -> None:
                try:
                    while not self.start_gate.wait(0.01):
                        if self.stop_event.is_set():
                            raise RunCancelled("Preview probe cancelled before subprocess launch.")
                    self.completed.emit(
                        prepare_model_library_inline_preview_in_subprocess(
                            self.path,
                            model_name="Dense",
                            stop_event=self.stop_event,
                        )
                    )
                except Exception as exc:
                    self.failed.emit(str(exc))
                finally:
                    self.finished.emit()

        with tempfile.TemporaryDirectory() as tmp:
            scene_path = _write_triangle_gltf(Path(tmp), triangle_count=1200)
            app = QApplication.instance() or QApplication([])
            ticks: list[float] = []
            stop_event = threading.Event()
            start_gate = threading.Event()
            loop = QEventLoop()
            receiver = _Receiver(loop, stop_event, start_gate, ticks)
            timer = QTimer(receiver)
            timer.setInterval(25)
            timer.timeout.connect(receiver.handle_tick)
            watchdog = QTimer(receiver)
            watchdog.setSingleShot(True)
            watchdog.setInterval(30000)
            watchdog.timeout.connect(receiver.handle_timeout)
            thread = QThread()
            worker = _Worker(scene_path, stop_event, start_gate)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.completed.connect(receiver.handle_completed, Qt.ConnectionType.QueuedConnection)
            worker.failed.connect(receiver.handle_failed, Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            worker.finished.connect(receiver.handle_finished, Qt.ConnectionType.QueuedConnection)
            timer.start()
            watchdog.start()
            thread.start()
            loop.exec()
            timer.stop()
            watchdog.stop()
            if receiver.timed_out:
                stop_event.set()
            thread.quit()
            thread_stopped = thread.wait(5000)

        self.assertTrue(thread_stopped, "Preview probe worker thread did not stop within 5 seconds.")
        self.assertFalse(receiver.timed_out, "Preview probe did not finish within 30 seconds.")
        self.assertTrue(receiver.finished, "Preview probe did not deliver its queued completion.")
        self.assertFalse(receiver.error, receiver.error)
        self.assertIsInstance(receiver.result, dict)
        gaps_ms = [(b - a) * 1000.0 for a, b in zip(ticks, ticks[1:])]
        self.assertGreaterEqual(len(ticks), 3)
        self.assertLess(max(gaps_ms) if gaps_ms else 0.0, 500.0)


if __name__ == "__main__":
    unittest.main()
