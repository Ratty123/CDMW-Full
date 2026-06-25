import json
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal, Slot

from cdmw.services.model_library_preview import (
    prepare_model_library_inline_preview,
    prepare_model_library_inline_preview_in_subprocess,
)


def _pad4(data: bytes) -> bytes:
    return data + (b"\x00" * ((4 - (len(data) % 4)) % 4))


def _write_triangle_gltf(root: Path, *, triangle_count: int = 1) -> Path:
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
        "materials": [{"name": "Body"}],
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
            app = QCoreApplication.instance() or QCoreApplication([])
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
