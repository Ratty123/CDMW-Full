from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import quote

from cdmw.rendering.qtquick3d_preview_package import (
    ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES,
    read_isolated_qtquick3d_preview_manifest,
)


_BACKEND_ENV = {
    "d3d11": "d3d11",
    "vulkan": "vulkan",
}
_BACKEND_ENUM = {
    "d3d11": "Direct3D11",
    "vulkan": "Vulkan",
}


def _emit(payload: Mapping[str, object]) -> None:
    print(json.dumps(dict(payload), separators=(",", ":")), flush=True)


def _write_status(status_file: Optional[Path], payload: Mapping[str, object]) -> None:
    if status_file is None:
        return
    try:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path = status_file.with_suffix(status_file.suffix + ".tmp")
        temp_path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
        temp_path.replace(status_file)
    except Exception:
        pass


def _configure_backend(backend: str) -> None:
    key = str(backend or "d3d11").strip().lower()
    if key not in _BACKEND_ENV:
        raise ValueError(f"Unsupported isolated renderer backend: {backend!r}")
    os.environ["QSG_RHI_BACKEND"] = _BACKEND_ENV[key]


def _self_test(backend: str) -> int:
    _configure_backend(backend)
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtQuick3D import QQuick3DGeometry

    enum_name = _BACKEND_ENUM[str(backend or "d3d11").strip().lower()]
    graphics_api = getattr(QSGRendererInterface.GraphicsApi, enum_name)
    QQuickWindow.setGraphicsApi(graphics_api)
    _emit(
        {
            "event": "self_test",
            "ok": True,
            "backend": backend,
            "rhi": os.environ.get("QSG_RHI_BACKEND", ""),
            "geometry": QQuick3DGeometry.__name__,
            "graphics_api": enum_name,
        }
    )
    return 0


def _run_qt_host(
    backend: str,
    *,
    preview_package: Optional[Path] = None,
    status_file: Optional[Path] = None,
    theme_background: str = "",
    theme_text: str = "",
) -> int:
    _configure_backend(backend)

    from PySide6.QtCore import QObject, Property, QTimer, QUrl, Qt, Signal, Slot
    from PySide6.QtGui import QColor, QGuiApplication, QVector3D
    from PySide6.QtQml import QQmlEngine
    from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface
    from PySide6.QtQuick3D import QQuick3DGeometry

    enum_name = _BACKEND_ENUM[str(backend or "d3d11").strip().lower()]
    QQuickWindow.setGraphicsApi(getattr(QSGRendererInterface.GraphicsApi, enum_name))

    def set_cpp_ownership(obj: QObject) -> None:
        try:
            QQmlEngine.setObjectOwnership(obj, QQmlEngine.ObjectOwnership.CppOwnership)
        except Exception:
            pass

    class _HostBatchGeometry(QQuick3DGeometry):
        def __init__(self, payload: Mapping[str, object]) -> None:
            super().__init__()
            set_cpp_ownership(self)
            vertex_blob = bytes(payload.get("vertex_blob", b"") or b"")
            self.setVertexData(vertex_blob)
            self.setStride(ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)
            self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
            self.setBounds(
                QVector3D(-1.0, -1.0, -1.0),
                QVector3D(1.0, 1.0, 1.0),
            )
            self.addAttribute(
                QQuick3DGeometry.Attribute.Semantic.PositionSemantic,
                0,
                QQuick3DGeometry.Attribute.ComponentType.F32Type,
            )
            self.addAttribute(
                QQuick3DGeometry.Attribute.Semantic.NormalSemantic,
                3 * 4,
                QQuick3DGeometry.Attribute.ComponentType.F32Type,
            )
            self.addAttribute(
                QQuick3DGeometry.Attribute.Semantic.TexCoordSemantic,
                9 * 4,
                QQuick3DGeometry.Attribute.ComponentType.F32Type,
            )
            self.addAttribute(
                QQuick3DGeometry.Attribute.Semantic.TangentSemantic,
                11 * 4,
                QQuick3DGeometry.Attribute.ComponentType.F32Type,
            )
            self.addAttribute(
                QQuick3DGeometry.Attribute.Semantic.BinormalSemantic,
                14 * 4,
                QQuick3DGeometry.Attribute.ComponentType.F32Type,
            )

    class _HostBridge(QObject):
        batchCountChanged = Signal()
        revisionChanged = Signal()
        cameraChanged = Signal()
        themeChanged = Signal()
        messageChanged = Signal()

        def __init__(self) -> None:
            super().__init__()
            set_cpp_ownership(self)
            self._payloads: list[Dict[str, object]] = []
            self._geometries: list[_HostBatchGeometry] = []
            self._revision = 0
            self._message = "Loading isolated preview package..."
            self._background_color = str(theme_background or "#080b0e")
            self._text_color = str(theme_text or "#c5ced8")
            self._yaw = -35.0
            self._pitch = 20.0
            self._distance = 3.25
            self._last_drag_x = 0.0
            self._last_drag_y = 0.0
            self._dragging = False

        @Property(int, notify=batchCountChanged)
        def batchCount(self) -> int:
            return len(self._payloads)

        @Property(int, notify=revisionChanged)
        def revision(self) -> int:
            return int(self._revision)

        @Property(str, notify=messageChanged)
        def message(self) -> str:
            return self._message

        @Property(str, notify=themeChanged)
        def backgroundColor(self) -> str:
            return self._background_color

        @Property(str, notify=themeChanged)
        def textColor(self) -> str:
            return self._text_color

        @Property(float, notify=cameraChanged)
        def yaw(self) -> float:
            return float(self._yaw)

        @Property(float, notify=cameraChanged)
        def pitch(self) -> float:
            return float(self._pitch)

        @Property(float, notify=cameraChanged)
        def cameraDistance(self) -> float:
            return float(self._distance)

        def set_message(self, message: str) -> None:
            self._message = str(message or "")
            self.messageChanged.emit()

        def set_theme(self, background: str, text: str) -> None:
            self._background_color = str(background or "#080b0e")
            self._text_color = str(text or "#c5ced8")
            self.themeChanged.emit()

        def set_payloads(self, payloads: Sequence[Mapping[str, object]]) -> None:
            self._payloads = [dict(payload) for payload in payloads]
            self._geometries = [_HostBatchGeometry(payload) for payload in self._payloads]
            self._revision += 1
            self.batchCountChanged.emit()
            self.revisionChanged.emit()

        def clear(self, message: str = "") -> None:
            self._payloads = []
            self._geometries = []
            self._revision += 1
            self.set_message(message or "No isolated preview loaded.")
            self.batchCountChanged.emit()
            self.revisionChanged.emit()

        def _payload(self, index: int) -> Mapping[str, object]:
            if 0 <= index < len(self._payloads):
                return self._payloads[index]
            return {}

        @Slot(int, int, result=QObject)
        def geometryFor(self, index: int, _revision: int) -> Optional[QObject]:
            if 0 <= index < len(self._geometries):
                return self._geometries[index]
            return None

        @Slot(int, int, result=QColor)
        def baseColorFor(self, index: int, _revision: int) -> QColor:
            values = self._payload(index).get("base_color", (0.78, 0.48, 0.34))
            if not isinstance(values, Sequence) or len(values) < 3:
                values = (0.78, 0.48, 0.34)
            return QColor.fromRgbF(float(values[0]), float(values[1]), float(values[2]), 1.0)

        @Slot(int, int, str, result=str)
        def textureSourceFor(self, index: int, _revision: int, slot_name: str) -> str:
            textures = self._payload(index).get("textures", {})
            if not isinstance(textures, Mapping):
                return ""
            source = str(textures.get(str(slot_name or ""), "") or "").strip()
            if not source:
                return ""
            return QUrl.fromLocalFile(str(Path(source).resolve())).toString()

        @Slot(int, int, str, result=bool)
        def textureEnabledFor(self, index: int, _revision: int, slot_name: str) -> bool:
            payload = self._payload(index)
            slot = str(slot_name or "").strip().lower()
            textures = payload.get("textures", {})
            if not isinstance(textures, Mapping) or not str(textures.get(slot, "") or "").strip():
                return False
            if slot in {"normal", "height", "occlusion", "roughness", "metalness", "specular"} and not bool(payload.get("has_texture_coordinates", False)):
                return False
            if slot == "normal" and not bool(payload.get("tangents_usable", False)):
                return False
            return True

        @Slot(int, int, result=bool)
        def textureFlipVFor(self, index: int, _revision: int) -> bool:
            return bool(self._payload(index).get("texture_flip_vertical", False))

        @Slot(int, int, result=float)
        def normalStrengthFor(self, index: int, _revision: int) -> float:
            return max(0.0, min(1.0, float(self._payload(index).get("normal_strength", 0.0) or 0.0)))

        @Slot(int, int, result=float)
        def heightAmountFor(self, index: int, _revision: int) -> float:
            return max(0.0, min(0.08, float(self._payload(index).get("height_amount", 0.0) or 0.0)))

        @Slot(float, float)
        def beginDrag(self, x: float, y: float) -> None:
            self._dragging = True
            self._last_drag_x = float(x)
            self._last_drag_y = float(y)

        @Slot(float, float)
        def dragTo(self, x: float, y: float) -> None:
            if not self._dragging:
                return
            dx = float(x) - self._last_drag_x
            dy = float(y) - self._last_drag_y
            self._last_drag_x = float(x)
            self._last_drag_y = float(y)
            self._yaw += dx * 0.25
            self._pitch = max(-89.0, min(89.0, self._pitch + dy * 0.20))
            self.cameraChanged.emit()

        @Slot()
        def endDrag(self) -> None:
            self._dragging = False

        @Slot(float)
        def zoomWheel(self, delta_y: float) -> None:
            factor = 0.88 if float(delta_y) > 0 else 1.14
            self._distance = max(0.35, min(25.0, self._distance * factor))
            self.cameraChanged.emit()

    class _HostController(QObject):
        def __init__(
            self,
            app: QGuiApplication,
            bridge: _HostBridge,
            view: QQuickView,
            backend_name: str,
            status_path: Optional[Path],
        ) -> None:
            super().__init__()
            self._app = app
            self._bridge = bridge
            self._view = view
            self._backend = backend_name
            self._status_file = status_path
            self._pending_loaded: Optional[Dict[str, object]] = None
            self._pending_frame_started = 0.0
            self._load_fallback_timer = QTimer(self)
            self._load_fallback_timer.setSingleShot(True)
            self._load_fallback_timer.timeout.connect(self._emit_pending_loaded)
            self._view.frameSwapped.connect(self._handle_frame_swapped)

        def _report_loading(self, stage: str, message: str, **extra: object) -> None:
            payload: Dict[str, object] = {
                "event": "loading",
                "backend": self._backend,
                "stage": str(stage or ""),
                "message": str(message or ""),
            }
            payload.update(extra)
            self._bridge.set_message(payload["message"])
            _write_status(self._status_file, payload)
            try:
                self._app.processEvents()
            except Exception:
                pass

        def load_package(self, package_path_text: str) -> None:
            package_dir = Path(package_path_text).expanduser()
            self._report_loading("checking_package", f"Checking isolated preview package: {package_dir}")
            if not package_dir.is_dir():
                self._report_error(f"package directory missing: {package_path_text}")
                return
            started = time.perf_counter()
            self._report_loading("reading_manifest", "Reading isolated preview manifest...", package=str(package_dir.resolve()))
            try:
                manifest = read_isolated_qtquick3d_preview_manifest(package_dir)
            except Exception as exc:
                self._report_error(f"manifest read failed: {exc}")
                return
            manifest_read_ms = max(0.0, (time.perf_counter() - started) * 1000.0)

            texture_started = time.perf_counter()
            batches: list[Dict[str, object]] = []
            notes: list[str] = []
            self._report_loading(
                "reading_assets",
                "Reading isolated preview geometry and texture references...",
                package=str(package_dir.resolve()),
                batch_count=len(tuple(manifest.get("batches", ()) or ())),
                vertex_count=int(manifest.get("vertex_count", 0) or 0),
            )
            for batch in tuple(manifest.get("batches", ()) or ()):
                if not isinstance(batch, Mapping):
                    continue
                vertex_file = str(batch.get("vertex_file", "") or "")
                try:
                    vertex_blob = (package_dir / vertex_file).read_bytes()
                except OSError as exc:
                    notes.append(f"vertex blob skipped:{vertex_file}:{exc}")
                    continue
                textures: Dict[str, str] = {}
                raw_textures = batch.get("textures", {})
                if isinstance(raw_textures, Mapping):
                    for slot_name, relative_path in raw_textures.items():
                        relative_text = str(relative_path or "").strip()
                        textures[str(slot_name)] = str((package_dir / relative_text).resolve()) if relative_text else ""
                payload = dict(batch)
                payload["vertex_blob"] = vertex_blob
                payload["textures"] = textures
                batches.append(payload)
                notes.extend(str(note) for note in tuple(batch.get("notes", ()) or ()) if note)
            texture_bind_ms = max(0.0, (time.perf_counter() - texture_started) * 1000.0)

            texture_counts = Counter()
            combiner_outputs = Counter()
            combiner_decode_modes = Counter()
            combiner_active_count = 0
            for batch in batches:
                textures = batch.get("textures", {})
                if not isinstance(textures, Mapping):
                    continue
                for slot_name, source in textures.items():
                    if str(source or "").strip():
                        texture_counts[str(slot_name)] += 1
                if bool(batch.get("material_combiner_active", False)):
                    combiner_active_count += 1
                for output in tuple(batch.get("material_combiner_outputs", ()) or ()):
                    if str(output or "").strip():
                        combiner_outputs[str(output)] += 1
                for mode in tuple(batch.get("material_combiner_decode_modes", ()) or ()):
                    if str(mode or "").strip():
                        combiner_decode_modes[str(mode)] += 1

            loaded_payload: Dict[str, object] = {
                "event": "loaded",
                "backend": self._backend,
                "package": str(package_dir.resolve()),
                "batch_count": len(batches),
                "vertex_count": sum(int(batch.get("vertex_count", 0) or 0) for batch in batches),
                "textures": dict(texture_counts),
                "manifest_read_ms": manifest_read_ms,
                "texture_bind_ms": texture_bind_ms,
                "geometry_upload_ms": 0.0,
                "first_frame_ms": 0.0,
                "skipped": tuple(dict.fromkeys(notes))[:12],
                "material_combiner_active": combiner_active_count,
                "material_combiner_outputs": dict(combiner_outputs),
                "material_combiner_decode_modes": dict(combiner_decode_modes),
            }
            self._report_loading(
                "publishing_geometry",
                "Publishing isolated preview geometry...",
                package=str(package_dir.resolve()),
                batch_count=loaded_payload["batch_count"],
                vertex_count=loaded_payload["vertex_count"],
                textures=dict(texture_counts),
            )
            geometry_started = time.perf_counter()
            self._bridge.set_payloads(batches)
            self._bridge.set_message(str(manifest.get("summary", "") or "Isolated preview loaded."))
            loaded_payload["geometry_upload_ms"] = max(0.0, (time.perf_counter() - geometry_started) * 1000.0)
            self._pending_loaded = loaded_payload
            self._pending_frame_started = time.perf_counter()
            self._load_fallback_timer.start(1000)
            self._view.requestUpdate()

        def _report_error(self, message: str) -> None:
            payload = {
                "event": "error",
                "backend": self._backend,
                "message": str(message or "Unknown isolated renderer error."),
            }
            self._bridge.clear(payload["message"])
            _write_status(self._status_file, payload)

        @Slot()
        def _handle_frame_swapped(self) -> None:
            if self._pending_loaded is None:
                return
            self._pending_loaded["first_frame_ms"] = max(0.0, (time.perf_counter() - self._pending_frame_started) * 1000.0)
            self._emit_pending_loaded()

        @Slot()
        def _emit_pending_loaded(self) -> None:
            if self._pending_loaded is None:
                return
            payload = self._pending_loaded
            self._pending_loaded = None
            self._load_fallback_timer.stop()
            _write_status(self._status_file, payload)

    qml = """
import QtQuick
import QtQuick3D

Item {
    id: root
    Rectangle {
        anchors.fill: parent
        color: previewBridge.backgroundColor
    }
    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            clearColor: previewBridge.backgroundColor
            backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }
        PerspectiveCamera {
            id: camera
            z: previewBridge.cameraDistance
            clipNear: 0.01
            clipFar: 1000.0
            fieldOfView: 45
        }
        DirectionalLight {
            eulerRotation.x: -35
            eulerRotation.y: -25
            brightness: 1.25
            ambientColor: "#68737f"
            castsShadow: false
        }
        DirectionalLight {
            eulerRotation.x: 48
            eulerRotation.y: 145
            brightness: 0.70
            ambientColor: "#323940"
            castsShadow: false
        }
        PointLight {
            position: Qt.vector3d(0, 110, 220)
            brightness: 38
            castsShadow: false
        }
        Node {
            id: sceneRoot
            eulerRotation: Qt.vector3d(previewBridge.pitch, previewBridge.yaw, 0)
            Repeater3D {
                model: previewBridge.batchCount
                delegate: Model {
                    geometry: previewBridge.geometryFor(index, previewBridge.revision)
                    materials: PrincipledMaterial {
                        baseColor: previewBridge.baseColorFor(index, previewBridge.revision)
                        baseColorMap: previewBridge.textureEnabledFor(index, previewBridge.revision, "base") ? baseTexture : null
                        normalMap: previewBridge.textureEnabledFor(index, previewBridge.revision, "normal") ? normalTexture : null
                        normalStrength: previewBridge.normalStrengthFor(index, previewBridge.revision)
                        heightMap: previewBridge.textureEnabledFor(index, previewBridge.revision, "height") ? heightTexture : null
                        heightAmount: previewBridge.heightAmountFor(index, previewBridge.revision)
                        occlusionMap: previewBridge.textureEnabledFor(index, previewBridge.revision, "occlusion") ? occlusionTexture : null
                        roughnessMap: previewBridge.textureEnabledFor(index, previewBridge.revision, "roughness") ? roughnessTexture : null
                        metalnessMap: previewBridge.textureEnabledFor(index, previewBridge.revision, "metalness") ? metalnessTexture : null
                        specularMap: previewBridge.textureEnabledFor(index, previewBridge.revision, "specular") ? specularTexture : null
                        roughness: previewBridge.textureEnabledFor(index, previewBridge.revision, "roughness") ? 1.0 : 0.52
                        metalness: previewBridge.textureEnabledFor(index, previewBridge.revision, "metalness") ? 1.0 : 0.0
                        specularAmount: previewBridge.textureEnabledFor(index, previewBridge.revision, "specular") ? 0.78 : 0.36
                        opacity: 1.0
                        alphaMode: PrincipledMaterial.Opaque
                        lighting: PrincipledMaterial.FragmentLighting
                        cullMode: Material.NoCulling
                    }
                    Texture {
                        id: baseTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision, "base")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: normalTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision, "normal")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: occlusionTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision, "occlusion")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: roughnessTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision, "roughness")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: metalnessTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision, "metalness")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: specularTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision, "specular")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: heightTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision, "height")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                }
            }
        }
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: previewBridge.beginDrag(mouse.x, mouse.y)
        onPositionChanged: previewBridge.dragTo(mouse.x, mouse.y)
        onReleased: previewBridge.endDrag()
        onWheel: function(wheel) { previewBridge.zoomWheel(wheel.angleDelta.y) }
    }
    Text {
        anchors.centerIn: parent
        width: Math.max(120, parent.width - 32)
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        color: previewBridge.textColor
        visible: previewBridge.batchCount <= 0
        text: previewBridge.message
    }
    Text {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 10
        color: previewBridge.textColor
        opacity: 0.72
        text: "Isolated D3D11 preview"
        visible: previewBridge.batchCount > 0
    }
}
"""

    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("CDMW Isolated D3D11 Preview")
    bridge = _HostBridge()
    view = QQuickView()
    view.setTitle("CDMW Isolated D3D11 Preview")
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.rootContext().setContextProperty("previewBridge", bridge)
    view.setSource(QUrl("data:text/plain;charset=utf-8," + quote(qml)))
    if view.status() == QQuickView.Status.Error:
        errors = "; ".join(error.toString() for error in view.errors())
        _write_status(status_file, {"event": "error", "backend": backend, "message": errors or "QML scene failed to load"})
        return 2
    controller = _HostController(app, bridge, view, backend, status_file)
    view.resize(820, 920)
    view.show()
    if preview_package is None:
        controller._report_error("missing --preview-package argument")
    else:
        QTimer.singleShot(0, lambda package_path=preview_package: controller.load_package(str(package_path)))
    exit_code = int(app.exec())
    _write_status(status_file, {"event": "closed", "backend": backend, "exit_code": exit_code})
    return exit_code


def run_isolated_renderer_host(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CDMW isolated D3D11 renderer host")
    parser.add_argument("--backend", default="d3d11", choices=sorted(_BACKEND_ENV))
    parser.add_argument("--preview-package", default="")
    parser.add_argument("--status-file", default="")
    parser.add_argument("--theme-background", default="")
    parser.add_argument("--theme-text", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test(args.backend)
    return _run_qt_host(
        args.backend,
        preview_package=Path(args.preview_package).expanduser() if args.preview_package else None,
        status_file=Path(args.status_file).expanduser() if args.status_file else None,
        theme_background=args.theme_background,
        theme_text=args.theme_text,
    )


if __name__ == "__main__":
    raise SystemExit(run_isolated_renderer_host())
