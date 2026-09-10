from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cdmw.models import ArchivePreviewResult, ModelPreviewData, ModelPreviewMesh, RunCancelled
from cdmw.rendering.static_model_thumbnail import prepare_static_model_thumbnail
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker


def _point_cloud(count: int) -> ModelPreviewData:
    positions = [
        (float(index % 1000), float((index // 1000) % 1000), float(index % 17) * 0.01)
        for index in range(count)
    ]
    return ModelPreviewData(
        path="large.pac",
        mesh_count=1,
        vertex_count=count,
        meshes=[ModelPreviewMesh(material_name="body", positions=positions)],
    )


class _GeneratedPositions:
    def __init__(self, count: int) -> None:
        self.count = count
        self.read_count = 0

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> tuple[float, float, float]:
        if index < 0 or index >= self.count:
            raise IndexError(index)
        self.read_count += 1
        return (float(index % 1000), float((index // 1000) % 1000), float(index % 17) * 0.01)


def test_million_vertex_static_thumbnail_worker_keeps_main_heartbeat_under_200ms() -> None:
    app = QApplication.instance() or QApplication([])
    result = ArchivePreviewResult(status="ok", preview_model=_point_cloud(1_000_000))

    class Owner:
        static_thumbnail_size = (480, 320)
        static_thumbnail_text_color = "#c0c0c0"
        static_thumbnail_point_cloud = True
        stop_event = threading.Event()

    rendered: dict[str, object] = {}

    def render() -> None:
        rendered["result"] = ArchivePreviewWorker._with_static_thumbnail(Owner(), result)

    worker = threading.Thread(target=render)
    heartbeat = [time.perf_counter()]
    worker.start()
    while worker.is_alive():
        app.processEvents()
        heartbeat.append(time.perf_counter())
        time.sleep(0.005)
    worker.join(1.0)
    heartbeat.append(time.perf_counter())

    rendered_result = rendered["result"]
    assert isinstance(rendered_result, ArchivePreviewResult)
    assert isinstance(rendered_result.static_preview_image, QImage)
    assert not rendered_result.static_preview_image.isNull()
    assert max(b - a for a, b in zip(heartbeat, heartbeat[1:])) < 0.2


def test_million_vertex_point_cloud_bounds_use_rendered_sample_only() -> None:
    positions = _GeneratedPositions(1_000_000)
    preview = ModelPreviewData(
        path="large.pac",
        mesh_count=1,
        vertex_count=len(positions),
        meshes=[ModelPreviewMesh(material_name="body", positions=positions)],  # type: ignore[arg-type]
    )

    plan = prepare_static_model_thumbnail(
        preview,
        width=480,
        height=320,
        draw_point_cloud_when_no_triangles=True,
    )

    assert plan is not None
    assert 0 < len(plan.points) < 7000
    assert positions.read_count == len(plan.points)


def test_static_thumbnail_projection_checks_cancellation() -> None:
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(RunCancelled):
        prepare_static_model_thumbnail(
            _point_cloud(10),
            width=480,
            height=320,
            draw_point_cloud_when_no_triangles=True,
            stop_event=cancelled,
        )


def test_static_thumbnail_projects_indexed_triangles_without_full_vertex_copy() -> None:
    preview = ModelPreviewData(
        path="triangle.pac",
        mesh_count=1,
        vertex_count=3,
        face_count=1,
        meshes=[
            ModelPreviewMesh(
                material_name="body",
                positions=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                indices=[0, 1, 2],
            )
        ],
    )

    plan = prepare_static_model_thumbnail(preview, width=480, height=320)

    assert plan is not None
    assert len(plan.triangles) == 1
    assert plan.points == ()


def test_archive_pickers_request_worker_rendered_static_images() -> None:
    for relative_path in (
        "cdmw/ui/archive_browser/source_picker_dialog.py",
        "cdmw/ui/archive_browser/attachment_donor_picker_dialog.py",
    ):
        source = Path(relative_path).read_text(encoding="utf-8")
        assert "static_thumbnail_size=" in source
        assert 'getattr(payload, "static_preview_image"' in source or 'getattr(result_payload, "static_preview_image"' in source
        assert "render_static_model_preview_pixmap(" not in source
