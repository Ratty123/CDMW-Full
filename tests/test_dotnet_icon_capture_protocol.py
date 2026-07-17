from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab_dotnet_protocol import MeshEditorDotNetProtocolMixin


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


def _source_family(stem: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_EDITOR.glob(f"{stem}*.cs"))
    )


class _Harness(MeshEditorDotNetProtocolMixin, QObject):
    def __init__(self, output_dir: Path) -> None:
        QObject.__init__(self)
        self.standalone_dotnet_experiment_package = SimpleNamespace(output_dir=output_dir)
        self.standalone_dotnet_target_embedded = True
        self.standalone_dotnet_process_generation = 7
        self.standalone_dotnet_capture_request_id = 0
        self.standalone_dotnet_capture_callbacks = {}
        self.sent: list[dict[str, object]] = []
        self.events: list[tuple[str, dict[str, object]]] = []
        self.statuses: list[tuple[str, bool]] = []

    @staticmethod
    def _standalone_dotnet_editor_process_running() -> bool:
        return True

    @staticmethod
    def _dotnet_target_controller() -> object:
        return SimpleNamespace(session_view=lambda: SimpleNamespace(session_id="session", revision=4))

    def _send_dotnet_protocol_message(self, payload) -> bool:  # type: ignore[no-untyped-def]
        self.sent.append(dict(payload))
        return True

    def _record_mesh_dotnet_event(self, name: str, **payload: object) -> None:
        self.events.append((name, dict(payload)))

    def _set_dotnet_status(self, message: str, *, error: bool = False) -> None:
        self.statuses.append((message, error))


def test_resident_icon_capture_is_correlated_and_accepts_only_the_requested_package_path(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    harness = _Harness(output_dir)
    captured: list[object] = []

    assert harness.request_resident_dotnet_icon_capture(captured.append)
    request = harness.sent[-1]
    assert request["event"] == "capture_request"
    assert request["session_id"] == "session"
    assert request["process_generation"] == 7
    assert request["output_path"] == "icon_capture_1.png"
    assert request["width"] == 1024
    assert request["height"] == 1024
    expected_path = output_dir / str(request["output_path"])
    image = QImage(16, 16, QImage.Format.Format_RGBA8888)
    image.fill(QColor("red"))
    assert image.save(str(expected_path), "PNG")

    assert harness._handle_dotnet_capture_result(
        {
            "event": "capture_result",
            "session_id": "session",
            "request_id": request["request_id"],
            "process_generation": 7,
            "status": "captured",
            "output_path": str(expected_path),
            "sha256": "abc",
            "visible_view_mutated": False,
        }
    )

    assert len(captured) == 1 and captured[0] is not None and not captured[0].isNull()
    assert harness.standalone_dotnet_capture_callbacks == {}
    assert harness.events[-1][0] == "mesh_dotnet_icon_capture"
    harness.deleteLater()
    app.processEvents()


def test_resident_icon_capture_timeout_removes_late_output(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    harness = _Harness(output_dir)
    captured: list[object] = []
    assert harness.request_resident_dotnet_icon_capture(captured.append)
    output_path = output_dir / "icon_capture_1.png"
    output_path.write_bytes(b"incomplete")

    harness._handle_dotnet_capture_timeout(1)

    assert captured == [None]
    assert not output_path.exists()
    harness.deleteLater()
    app.processEvents()


def test_resident_icon_capture_rejects_a_mismatched_reported_path(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    harness = _Harness(output_dir)
    captured: list[object] = []
    assert harness.request_resident_dotnet_icon_capture(captured.append)
    request = harness.sent[-1]

    assert not harness._handle_dotnet_capture_result(
        {
            "request_id": request["request_id"],
            "status": "captured",
            "output_path": tmp_path / "outside.png",
        }
    )
    assert captured == [None]
    assert harness.statuses[-1][1] is True
    harness.deleteLater()
    app.processEvents()


def test_dotnet_capture_resolves_relative_output_and_rejects_reparse_leaf() -> None:
    source = Path("tools/dotnet_mesh_editor_experiment/ExperimentForm.Protocol.cs").read_text(
        encoding="utf-8"
    )

    assert "Path.GetFullPath(Path.Combine(outputRoot, requestedPath))" in source
    assert "return IsReparsePoint(outputPath);" in source


def test_icon_capture_uses_deterministic_offscreen_d3d_target_without_visible_state_mutation() -> None:
    capture = _source("D3D11MaterialViewport.Capture.cs")
    targets = _source("D3D11MaterialViewport.RenderTargets.cs")
    renderer = _source_family("D3D11MaterialViewport")
    protocol = _source("ExperimentForm.Protocol.cs")

    assert "BindFlags.RenderTarget" in targets
    assert "ResourceUsage.Staging" in capture
    assert "CpuAccessFlags.Read" in capture
    assert "CurrentRenderSampleDescription" in capture
    assert "resolvedTexture" in capture
    assert "ResolveSubresource(" in capture
    assert "CopyResource(stagingTexture, captureSource)" in capture
    assert "_offscreenMultisampleResolveCount++;" in capture
    assert "RenderFrame(present: false, includeOverlays: false, replacementOnly: true)" in capture
    assert "CameraForCaptureViewport(visibleCamera, width, height)" in capture
    assert "Math.Min(width / sourceWidth, height / sourceHeight)" in capture
    assert "camera.Zoom * uniformScale" in capture
    assert "camera.PanX * uniformScale" in capture
    assert "_camera = visibleCamera;" in capture
    assert "_renderTargetView = previousTarget;" in capture
    assert "_depthStencilView = previousDepth;" in capture
    assert "bitmap.Save(temporaryPath, ImageFormat.Png)" in capture
    assert "screen.grabWindow" not in capture
    assert "replacementOnly && _scene.IsReference" in renderer
    assert 'case "capture_request"' in protocol
    assert '"visible_view_mutated"] = false' in protocol
    assert "Capture output must remain inside the package output directory" in protocol
