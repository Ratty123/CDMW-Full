from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cdmw.models import ArchivePreviewResult, ModelPreviewData, ModelPreviewMesh, RunCancelled
from cdmw.rendering.static_model_thumbnail import (
    StaticModelThumbnailPlan,
    prepare_static_model_thumbnail,
    render_static_model_comparison_image,
    render_static_model_thumbnail_image,
    render_static_model_thumbnail_plan_image,
)
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


def test_solid_fills_faces_while_wire_only_draws_edges_over_solid_meshes() -> None:
    triangle = ((40.0, 40.0, 0.0), (280.0, 40.0, 0.0), (160.0, 220.0, 0.0))
    plan = StaticModelThumbnailPlan(320, 260, ((180, 180, 180, 255),), ((0, triangle),), ())
    solid = render_static_model_thumbnail_plan_image(plan, text_color="", mesh_display_modes=("solid",))
    wire = render_static_model_thumbnail_plan_image(plan, text_color="", mesh_display_modes=("wireframe",))
    assert solid.pixel(160, 100) != solid.pixel(0, 0)
    assert wire.pixel(160, 100) == wire.pixel(0, 0)
    assert wire.pixel(160, 40) != wire.pixel(0, 0)

    # The farther wire mesh must remain legible over the opaque body.
    overlay = replace(plan, mesh_colors=(*plan.mesh_colors, (245, 176, 84, 255)), triangles=(
        (1, ((80.0, 90.0, -1.0), (240.0, 90.0, -1.0), (160.0, 180.0, -1.0))),
        *plan.triangles,
    ))
    combined = render_static_model_thumbnail_plan_image(
        overlay, text_color="", mesh_display_modes=("solid", "wireframe"),
    )
    edge = combined.pixelColor(160, 90)
    assert edge.red() > edge.blue()
    assert combined.pixel(160, 110) == solid.pixel(160, 110)


def test_combined_preview_restores_both_meshes_original_scale_and_position() -> None:
    target = ModelPreviewData(meshes=[ModelPreviewMesh(
        positions=[(-2.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 4.0, 0.0)], indices=[0, 1, 2],
    )])
    source = ModelPreviewData(meshes=[ModelPreviewMesh(
        positions=[(1.0, 1.0, 0.0), (3.0, 1.0, 0.0), (2.0, 3.0, 0.0)], indices=[0, 1, 2],
    )])

    def normalized(model, center, scale):
        return replace(model, normalization_center=center, normalization_scale=scale, meshes=[
            replace(mesh, positions=[
                tuple((position[axis] - center[axis]) * scale for axis in range(3))
                for position in mesh.positions
            ]) for mesh in model.meshes
        ])

    original = render_static_model_comparison_image(target, source, width=480, height=640)
    restored = render_static_model_comparison_image(
        normalized(target, (0.0, 2.0, 0.0), 0.5),
        normalized(source, (2.0, 2.0, 0.0), 2.0), width=480, height=640,
    )
    assert original is not None and restored == original
    assert target.meshes[0].positions[0] == (-2.0, 0.0, 0.0)
    assert source.meshes[0].positions[0] == (1.0, 1.0, 0.0)


def test_combined_solid_preview_keeps_faces_omitted_by_thumbnail_sampling() -> None:
    # Face 1 is the only triangle on the right. Ordinary thumbnail sampling
    # skips it at this triangle count; a solid comparison must keep it.
    model = ModelPreviewData(meshes=[ModelPreviewMesh(
        positions=[(-3.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (-2.0, 2.0, 0.0),
                   (1.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 2.0, 0.0)],
        indices=[0, 1, 2, 3, 4, 5] + [0, 1, 2] * 9000,
    )])
    plan = prepare_static_model_thumbnail(model, width=480, height=320, sample_triangles=False)
    marker = max((triangle for _, triangle in plan.triangles), key=lambda t: sum(p[0] for p in t))
    x, y = (round(sum(p[axis] for p in marker) / 3) for axis in (0, 1))
    sampled = render_static_model_thumbnail_image(model, width=480, height=320, text_color="")
    combined = render_static_model_comparison_image(model, None, width=480, height=320)
    assert sampled.pixel(x, y) == sampled.pixel(0, 0)
    assert combined.pixel(x, y) != combined.pixel(0, 0)


def test_static_thumbnail_painting_checks_cancellation_between_batches() -> None:
    class CancelAfterFirstBatch:
        checks = 0

        def is_set(self):
            self.checks += 1
            return self.checks > 1

    triangle = ((40.0, 40.0, 0.0), (280.0, 40.0, 0.0), (160.0, 220.0, 0.0))
    plan = StaticModelThumbnailPlan(320, 260, ((180, 180, 180, 255),), ((0, triangle),) * 1000, ())
    with pytest.raises(RunCancelled):
        render_static_model_thumbnail_plan_image(plan, text_color="", stop_event=CancelAfterFirstBatch())
