from __future__ import annotations

from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
from typing import Optional, Sequence, Tuple
from urllib.parse import quote

from PySide6.QtCore import (
    QObject,
    Property,
    QEvent,
    QPointF,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QImage, QImageReader, QVector3D
from PySide6.QtQml import QQmlEngine, QQmlError
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtQuick3D import QQuick3DGeometry
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from cdmw.models import (
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PreparedModelPreviewData,
    PreviewMaterialTextureInput,
    clamp_model_preview_render_settings,
)
from cdmw.ui.model_preview_material_combiner import (
    QtQuick3DMaterialCombinerSettings,
    combine_qtquick3d_material,
    synthesize_material_texture_inputs,
)
from cdmw.ui.themes import get_theme

try:
    import shiboken6
except Exception:  # pragma: no cover - shiboken ships with PySide6, this is defensive.
    shiboken6 = None


ARCHIVE_MODEL_RENDERER_LEGACY_OPENGL = "legacy_opengl"
ARCHIVE_MODEL_RENDERER_QTQUICK3D = "qtquick3d_experimental"
ARCHIVE_MODEL_RENDERER_DEFAULT = ARCHIVE_MODEL_RENDERER_LEGACY_OPENGL
ARCHIVE_MODEL_RENDERER_LABELS = {
    ARCHIVE_MODEL_RENDERER_LEGACY_OPENGL: "Legacy OpenGL",
    ARCHIVE_MODEL_RENDERER_QTQUICK3D: "Qt Quick 3D Experimental",
}

_FLOATS_PER_PREVIEW_VERTEX = 23
_PREVIEW_VERTEX_STRIDE_BYTES = _FLOATS_PER_PREVIEW_VERTEX * 4
_VERTEX_STRUCT = struct.Struct("<23f")


def _experimental_pbr_env_enabled(name: str, *, default: bool = True) -> bool:
    value = str(os.environ.get(name, "") or "").strip().lower()
    if not value:
        return bool(default)
    return value in {"1", "true", "yes", "on"}


_ENABLE_EXPERIMENTAL_MATERIAL_PBR_MAPS = _experimental_pbr_env_enabled("CDMW_QTQUICK3D_ENABLE_MATERIAL_PBR_MAPS")
_ENABLE_EXPERIMENTAL_HEIGHT_PBR_MAPS = _experimental_pbr_env_enabled("CDMW_QTQUICK3D_ENABLE_HEIGHT_PBR_MAPS")
_ENABLE_EXPERIMENTAL_NORMAL_PBR_MAPS = _experimental_pbr_env_enabled("CDMW_QTQUICK3D_ENABLE_NORMAL_PBR_MAPS")


def configure_experimental_qtquick3d_rhi() -> None:
    """Force Qt Quick 3D to the OpenGL RHI before any QQuickWidget exists."""
    current = str(os.environ.get("QSG_RHI_BACKEND", "") or "").strip()
    if current and current.lower() != "opengl":
        os.environ.setdefault("CDMW_PREVIOUS_QSG_RHI_BACKEND", current)
    os.environ["QSG_RHI_BACKEND"] = "opengl"
    try:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    except Exception:
        pass


def normalize_archive_model_renderer_backend(value: object) -> str:
    key = str(value or "").strip().lower()
    if key in ARCHIVE_MODEL_RENDERER_LABELS:
        return key
    return ARCHIVE_MODEL_RENDERER_DEFAULT


@dataclass(frozen=True, slots=True)
class QtQuick3DPreviewBatchPayload:
    material_name: str = ""
    texture_name: str = ""
    vertex_blob: bytes = b""
    vertex_count: int = 0
    bounds_min: Tuple[float, float, float] = (-1.0, -1.0, -1.0)
    bounds_max: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    base_color: Tuple[float, float, float] = (0.78, 0.48, 0.34)
    base_texture_quality: str = ""
    texture_source: str = ""
    texture_prepare_note: str = ""
    normal_texture_source: str = ""
    material_texture_source: str = ""
    occlusion_texture_source: str = ""
    roughness_texture_source: str = ""
    metalness_texture_source: str = ""
    specular_texture_source: str = ""
    height_texture_source: str = ""
    height_texture_amount: float = 0.0
    texture_flip_vertical: bool = False
    normal_texture_strength: float = 0.0
    material_texture_type: str = ""
    material_texture_subtype: str = ""
    material_texture_packed_channels: Tuple[str, ...] = ()
    material_texture_slots: Tuple[str, ...] = ()
    material_texture_inputs: Tuple[PreviewMaterialTextureInput, ...] = ()
    material_combiner_active: bool = False
    material_combiner_notes: Tuple[str, ...] = ()
    material_combiner_decode_modes: Tuple[str, ...] = ()
    material_combiner_outputs: Tuple[str, ...] = ()
    has_texture_coordinates: bool = False
    tangents_usable: bool = False


def _finite_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _clamp_color(values: Sequence[object], fallback: Tuple[float, float, float]) -> Tuple[float, float, float]:
    if len(values) < 3:
        return fallback
    return (
        max(0.0, min(1.0, _finite_float(values[0], fallback[0]))),
        max(0.0, min(1.0, _finite_float(values[1], fallback[1]))),
        max(0.0, min(1.0, _finite_float(values[2], fallback[2]))),
    )


def _color_to_qml(value: Tuple[float, float, float]) -> str:
    red = max(0, min(255, int(round(float(value[0]) * 255.0))))
    green = max(0, min(255, int(round(float(value[1]) * 255.0))))
    blue = max(0, min(255, int(round(float(value[2]) * 255.0))))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _texture_source_url(path_text: str) -> str:
    normalized = str(path_text or "").strip()
    if not normalized or normalized.lower().startswith("in_memory"):
        return ""
    try:
        path = Path(normalized)
    except (OSError, ValueError):
        return ""
    if not path.is_file():
        return ""
    return QUrl.fromLocalFile(str(path.resolve())).toString()


def _qobject_alive(value: object) -> bool:
    if value is None:
        return False
    if shiboken6 is not None:
        try:
            return bool(shiboken6.isValid(value))
        except Exception:
            return False
    try:
        value.objectName()  # type: ignore[attr-defined]
    except RuntimeError:
        return False
    except Exception:
        return True
    return True


def _set_cpp_qml_ownership(value: QObject) -> None:
    try:
        QQmlEngine.setObjectOwnership(value, QQmlEngine.ObjectOwnership.CppOwnership)
    except Exception:
        pass


def _normalized_texture_channels(values: Sequence[object]) -> Tuple[str, ...]:
    return tuple(str(value or "").strip().lower() for value in values if str(value or "").strip())


def _material_texture_slots(
    texture_type: object,
    semantic_subtype: object,
    packed_channels: Sequence[object],
) -> Tuple[str, ...]:
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    channels = _normalized_texture_channels(packed_channels)
    if normalized_subtype in {"opacity", "opacity_mask", "alpha"}:
        return ()
    if normalized_subtype == "ao":
        return ("occlusion",)
    if normalized_subtype in {"roughness", "gloss_or_smoothness"} or normalized_type == "roughness":
        return ("roughness",)
    if normalized_subtype == "metallic" or normalized_type == "metallic":
        return ("metalness",)
    if normalized_subtype == "specular" or normalized_type == "specular":
        return ("specular",)
    if normalized_subtype in {"orm", "arm", "rma", "mra"} or channels[:3] in {
        ("ao", "roughness", "metallic"),
        ("roughness", "metallic", "ao"),
        ("metallic", "roughness", "ao"),
    }:
        return ("occlusion", "roughness", "metalness")
    if normalized_subtype in {"material_mask", "material_response", "packed_mask"} or "mask" in normalized_type:
        return ("roughness", "specular")
    if channels:
        slots: list[str] = []
        channel_slot_names = {
            "ao": "occlusion",
            "ambient_occlusion": "occlusion",
            "roughness": "roughness",
            "gloss": "roughness",
            "gloss_or_smoothness": "roughness",
            "metallic": "metalness",
            "metalness": "metalness",
            "specular": "specular",
        }
        for channel in channels:
            slot_name = channel_slot_names.get(channel)
            if slot_name and slot_name not in slots:
                slots.append(slot_name)
        if slots:
            return tuple(slots)
    return ("roughness", "specular")


def _iter_preview_vertices(vertex_blob: bytes):
    usable_length = (len(vertex_blob) // _PREVIEW_VERTEX_STRIDE_BYTES) * _PREVIEW_VERTEX_STRIDE_BYTES
    for offset in range(0, usable_length, _PREVIEW_VERTEX_STRIDE_BYTES):
        yield _VERTEX_STRUCT.unpack_from(vertex_blob, offset)


def _vector_length(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def build_qtquick3d_preview_payloads(
    prepared_preview: Optional[PreparedModelPreviewData],
) -> Tuple[QtQuick3DPreviewBatchPayload, ...]:
    if not isinstance(prepared_preview, PreparedModelPreviewData):
        return ()
    payloads: list[QtQuick3DPreviewBatchPayload] = []
    fallback_palette = (
        (201 / 255.0, 111 / 255.0, 81 / 255.0),
        (94 / 255.0, 133 / 255.0, 168 / 255.0),
        (156 / 255.0, 167 / 255.0, 98 / 255.0),
        (198 / 255.0, 176 / 255.0, 92 / 255.0),
        (147 / 255.0, 112 / 255.0, 166 / 255.0),
    )
    for batch_index, batch in enumerate(tuple(getattr(prepared_preview, "batches", ()) or ())):
        raw_blob = bytes(getattr(batch, "vertex_blob", b"") or b"")
        vertex_count = max(0, min(int(getattr(batch, "index_count", 0) or 0), len(raw_blob) // _PREVIEW_VERTEX_STRIDE_BYTES))
        if vertex_count <= 0:
            continue
        usable_blob = raw_blob[: vertex_count * _PREVIEW_VERTEX_STRIDE_BYTES]
        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")
        first_color: Tuple[float, float, float] = ()
        tangents_checked = 0
        tangents_valid = 0
        for vertex in _iter_preview_vertices(usable_blob):
            x, y, z = vertex[0], vertex[1], vertex[2]
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            min_z = min(min_z, z)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            max_z = max(max_z, z)
            if not first_color:
                first_color = (vertex[6], vertex[7], vertex[8])
            normal = vertex[3:6]
            uv = vertex[9:11]
            tangent = vertex[11:14]
            bitangent = vertex[14:17]
            tangents_checked += 1
            if (
                all(math.isfinite(float(value)) for value in (*normal, *uv, *tangent, *bitangent))
                and _vector_length(normal) > 0.05
                and _vector_length(tangent) > 0.05
                and _vector_length(bitangent) > 0.05
            ):
                tangents_valid += 1
        if not all(math.isfinite(value) for value in (min_x, min_y, min_z, max_x, max_y, max_z)):
            continue
        fallback_color = fallback_palette[batch_index % len(fallback_palette)]
        base_color = _clamp_color(first_color, fallback_color)
        material_texture_type = str(getattr(batch, "preview_material_texture_type", "") or "").strip().lower()
        material_texture_subtype = str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower()
        material_texture_channels = _normalized_texture_channels(
            tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ())
        )
        material_texture_source = _texture_source_url(str(getattr(batch, "preview_material_texture_path", "") or ""))
        texture_flip_value = getattr(batch, "preview_texture_flip_vertical", None)
        material_inputs = synthesize_material_texture_inputs(batch)
        payloads.append(
            QtQuick3DPreviewBatchPayload(
                material_name=str(getattr(batch, "material_name", "") or "").strip(),
                texture_name=str(getattr(batch, "texture_name", "") or "").strip(),
                vertex_blob=usable_blob,
                vertex_count=vertex_count,
                bounds_min=(float(min_x), float(min_y), float(min_z)),
                bounds_max=(float(max_x), float(max_y), float(max_z)),
                base_color=base_color,
                base_texture_quality=str(getattr(batch, "preview_base_texture_quality", "") or "").strip().lower(),
                texture_source=_texture_source_url(str(getattr(batch, "preview_texture_path", "") or "")),
                normal_texture_source=_texture_source_url(str(getattr(batch, "preview_normal_texture_path", "") or "")),
                material_texture_source=material_texture_source,
                height_texture_source=_texture_source_url(str(getattr(batch, "preview_height_texture_path", "") or "")),
                texture_flip_vertical=True if texture_flip_value is None else bool(texture_flip_value),
                normal_texture_strength=max(0.0, _finite_float(getattr(batch, "preview_normal_texture_strength", 0.0), 0.0)),
                material_texture_type=material_texture_type,
                material_texture_subtype=material_texture_subtype,
                material_texture_packed_channels=material_texture_channels,
                material_texture_slots=(
                    _material_texture_slots(
                        material_texture_type,
                        material_texture_subtype,
                        material_texture_channels,
                    )
                    if material_texture_source
                    else ()
                ),
                material_texture_inputs=material_inputs,
                has_texture_coordinates=bool(getattr(batch, "has_texture_coordinates", False)),
                tangents_usable=bool(tangents_checked > 0 and tangents_valid / float(tangents_checked) >= 0.80),
            )
        )
    return tuple(payloads)


class _PreviewBatchGeometry(QQuick3DGeometry):
    def __init__(self, payload: QtQuick3DPreviewBatchPayload, parent: Optional[QObject] = None) -> None:
        super().__init__()
        if parent is not None:
            self.setParent(parent)
        _set_cpp_qml_ownership(self)
        self.setVertexData(payload.vertex_blob)
        self.setStride(_PREVIEW_VERTEX_STRIDE_BYTES)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.setBounds(
            QVector3D(*payload.bounds_min),
            QVector3D(*payload.bounds_max),
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


class _QtQuick3DPreviewBridge(QObject):
    batchCountChanged = Signal()
    revisionChanged = Signal()
    cameraChanged = Signal()
    messageChanged = Signal()
    themeChanged = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        _set_cpp_qml_ownership(self)
        self._payloads: Tuple[QtQuick3DPreviewBatchPayload, ...] = ()
        self._geometries: Tuple[_PreviewBatchGeometry, ...] = ()
        self._retired_geometries: list[_PreviewBatchGeometry] = []
        self._retired_cleanup_pending = False
        self._revision = 0
        self._message = "Select an archive model to preview it here."
        self._background_color = "#20252b"
        self._text_color = "#c5ced8"
        self._textures_enabled = False
        self._support_maps_enabled = False
        self._normal_maps_enabled = True
        self._material_maps_enabled = True
        self._height_maps_enabled = True
        self._normal_pbr_maps_enabled = _ENABLE_EXPERIMENTAL_NORMAL_PBR_MAPS
        self._material_pbr_maps_enabled = _ENABLE_EXPERIMENTAL_MATERIAL_PBR_MAPS
        self._height_pbr_maps_enabled = _ENABLE_EXPERIMENTAL_HEIGHT_PBR_MAPS
        self._normal_strength_floor = 0.5
        self._normal_strength_cap = 1.0
        self._height_amount = 0.04
        self._yaw = -35.0
        self._pitch = 20.0
        self._distance = 3.25
        self._pan = (0.0, 0.0, 0.0)

    @Property(int, notify=batchCountChanged)
    def batchCount(self) -> int:
        return len(self._payloads)

    @Property(int, notify=revisionChanged)
    def revision(self) -> int:
        return self._revision

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
        return self._yaw

    @Property(float, notify=cameraChanged)
    def pitch(self) -> float:
        return self._pitch

    @Property(float, notify=cameraChanged)
    def cameraDistance(self) -> float:
        return self._distance

    @Property(float, notify=cameraChanged)
    def panX(self) -> float:
        return self._pan[0]

    @Property(float, notify=cameraChanged)
    def panY(self) -> float:
        return self._pan[1]

    @Property(float, notify=cameraChanged)
    def panZ(self) -> float:
        return self._pan[2]

    def set_payloads(self, payloads: Sequence[QtQuick3DPreviewBatchPayload]) -> None:
        old_geometries = self._geometries
        self._payloads = tuple(payloads)
        self._geometries = tuple(_PreviewBatchGeometry(payload, self) for payload in self._payloads)
        self._revision += 1
        self.batchCountChanged.emit()
        self.revisionChanged.emit()
        self._retire_geometries(old_geometries)

    def _retire_geometries(self, geometries: Sequence[_PreviewBatchGeometry]) -> None:
        alive = [geometry for geometry in geometries if _qobject_alive(geometry)]
        if not alive:
            return
        self._retired_geometries.extend(alive)
        if self._retired_cleanup_pending:
            return
        self._retired_cleanup_pending = True
        QTimer.singleShot(500, self._release_retired_geometries)

    def _release_retired_geometries(self) -> None:
        self._retired_cleanup_pending = False
        retired = self._retired_geometries
        self._retired_geometries = []
        for geometry in retired:
            if not _qobject_alive(geometry):
                continue
            try:
                geometry.setParent(None)
                geometry.deleteLater()
            except RuntimeError:
                pass
        if self._retired_geometries and not self._retired_cleanup_pending:
            self._retired_cleanup_pending = True
            QTimer.singleShot(500, self._release_retired_geometries)

    def set_message(self, message: str) -> None:
        normalized = str(message or "").strip()
        if normalized == self._message:
            return
        self._message = normalized
        self.messageChanged.emit()

    def set_theme_colors(self, *, background: QColor, text: QColor) -> None:
        self._background_color = background.name(QColor.HexRgb)
        self._text_color = text.name(QColor.HexRgb)
        self.themeChanged.emit()

    def set_textures_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._textures_enabled:
            return
        self._textures_enabled = enabled
        self._revision += 1
        self.revisionChanged.emit()

    def set_support_map_options(
        self,
        *,
        enabled: bool,
        normal_enabled: bool,
        material_enabled: bool,
        height_enabled: bool,
        normal_strength_floor: float,
        normal_strength_cap: float,
        height_amount: float,
    ) -> None:
        values = (
            bool(enabled),
            bool(normal_enabled),
            bool(material_enabled),
            bool(height_enabled),
            max(0.0, _finite_float(normal_strength_floor, 0.5)),
            max(0.0, _finite_float(normal_strength_cap, 1.0)),
            max(0.0, min(0.12, _finite_float(height_amount, 0.04))),
        )
        current = (
            self._support_maps_enabled,
            self._normal_maps_enabled,
            self._material_maps_enabled,
            self._height_maps_enabled,
            self._normal_strength_floor,
            self._normal_strength_cap,
            self._height_amount,
        )
        if values == current:
            return
        (
            self._support_maps_enabled,
            self._normal_maps_enabled,
            self._material_maps_enabled,
            self._height_maps_enabled,
            self._normal_strength_floor,
            self._normal_strength_cap,
            self._height_amount,
        ) = values
        self._revision += 1
        self.revisionChanged.emit()

    def material_pbr_maps_enabled(self) -> bool:
        return bool(self._material_pbr_maps_enabled)

    def height_pbr_maps_enabled(self) -> bool:
        return bool(self._height_pbr_maps_enabled)

    def normal_pbr_maps_enabled(self) -> bool:
        return bool(self._normal_pbr_maps_enabled)

    def set_camera(self, *, yaw: float, pitch: float, distance: float, pan: Tuple[float, float, float]) -> None:
        self._yaw = float(yaw)
        self._pitch = max(-89.0, min(89.0, float(pitch)))
        self._distance = max(0.1, float(distance))
        self._pan = (float(pan[0]), float(pan[1]), float(pan[2]))
        self.cameraChanged.emit()

    @Slot(int, int, result=QObject)
    def geometryFor(self, index: int, _revision: int) -> Optional[QObject]:
        if 0 <= int(index) < len(self._geometries):
            return self._geometries[int(index)]
        return None

    @Slot(int, int, result=str)
    def baseColorFor(self, index: int, _revision: int) -> str:
        if 0 <= int(index) < len(self._payloads):
            payload = self._payloads[int(index)]
            if self._textures_enabled and payload.has_texture_coordinates and payload.texture_source:
                return "#ffffff"
            return _color_to_qml(payload.base_color)
        return "#c97851"

    @Slot(int, int, result=bool)
    def textureEnabledFor(self, index: int, _revision: int) -> bool:
        if 0 <= int(index) < len(self._payloads):
            payload = self._payloads[int(index)]
            return bool(self._textures_enabled and payload.has_texture_coordinates and payload.texture_source)
        return False

    @Slot(int, int, result=str)
    def textureSourceFor(self, index: int, _revision: int) -> str:
        if 0 <= int(index) < len(self._payloads):
            return self._payloads[int(index)].texture_source
        return ""

    @Slot(int, int, result=bool)
    def textureFlipVFor(self, index: int, _revision: int) -> bool:
        if 0 <= int(index) < len(self._payloads):
            return bool(self._payloads[int(index)].texture_flip_vertical)
        return False

    def _support_texture_enabled(self, payload: QtQuick3DPreviewBatchPayload, source: str) -> bool:
        return bool(
            self._textures_enabled
            and self._support_maps_enabled
            and payload.has_texture_coordinates
            and source
        )

    @Slot(int, int, result=bool)
    def normalTextureEnabledFor(self, index: int, _revision: int) -> bool:
        if 0 <= int(index) < len(self._payloads):
            payload = self._payloads[int(index)]
            return bool(
                self._normal_maps_enabled
                and self._normal_pbr_maps_enabled
                and payload.tangents_usable
                and self._support_texture_enabled(payload, payload.normal_texture_source)
            )
        return False

    @Slot(int, int, result=str)
    def normalTextureSourceFor(self, index: int, _revision: int) -> str:
        if 0 <= int(index) < len(self._payloads):
            return self._payloads[int(index)].normal_texture_source
        return ""

    @Slot(int, int, result=float)
    def normalStrengthFor(self, index: int, _revision: int) -> float:
        strength = 0.0
        if 0 <= int(index) < len(self._payloads):
            strength = float(self._payloads[int(index)].normal_texture_strength or 0.0)
        if strength <= 0.0:
            strength = self._normal_strength_floor
        lower = min(self._normal_strength_floor, self._normal_strength_cap)
        upper = max(self._normal_strength_floor, self._normal_strength_cap)
        return max(lower, min(upper, strength))

    @staticmethod
    def _material_slot_source(payload: QtQuick3DPreviewBatchPayload, slot_name: str) -> str:
        normalized_slot = str(slot_name or "").strip().lower()
        if normalized_slot == "occlusion":
            return payload.occlusion_texture_source
        if normalized_slot == "roughness":
            return payload.roughness_texture_source
        if normalized_slot == "metalness":
            return payload.metalness_texture_source
        if normalized_slot == "specular":
            return payload.specular_texture_source
        return ""

    @Slot(int, int, str, result=bool)
    def materialTextureEnabledFor(self, index: int, _revision: int, slot_name: str) -> bool:
        if 0 <= int(index) < len(self._payloads):
            payload = self._payloads[int(index)]
            normalized_slot = str(slot_name or "").strip().lower()
            source = self._material_slot_source(payload, normalized_slot)
            return bool(
                self._material_maps_enabled
                and self._material_pbr_maps_enabled
                and normalized_slot in payload.material_texture_slots
                and self._support_texture_enabled(payload, source)
            )
        return False

    @Slot(int, int, str, result=str)
    def materialTextureSourceFor(self, index: int, _revision: int, slot_name: str) -> str:
        if 0 <= int(index) < len(self._payloads):
            return self._material_slot_source(self._payloads[int(index)], slot_name)
        return ""

    @Slot(int, int, result=bool)
    def heightTextureEnabledFor(self, index: int, _revision: int) -> bool:
        if 0 <= int(index) < len(self._payloads):
            payload = self._payloads[int(index)]
            return bool(
                self._height_maps_enabled
                and self._height_pbr_maps_enabled
                and self._support_texture_enabled(payload, payload.height_texture_source)
            )
        return False

    @Slot(int, int, result=str)
    def heightTextureSourceFor(self, index: int, _revision: int) -> str:
        if 0 <= int(index) < len(self._payloads):
            return self._payloads[int(index)].height_texture_source
        return ""

    @Slot(int, int, result=float)
    def heightAmountFor(self, index: int, _revision: int) -> float:
        if 0 <= int(index) < len(self._payloads):
            payload = self._payloads[int(index)]
            return max(0.0, min(self._height_amount, float(payload.height_texture_amount or self._height_amount)))
        return 0.0


class ExperimentalQtQuick3DModelPreviewWidget(QWidget):
    view_state_changed = Signal(float, bool)
    debug_details_changed = Signal(str)

    _FIT_DISTANCE = 3.25
    _VERTICAL_FOV_DEGREES = 45.0
    _ZOOM_STEPS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0)

    def __init__(self, title: str, *, theme_key: str, parent: Optional[QWidget] = None) -> None:
        configure_experimental_qtquick3d_rhi()
        super().__init__(parent)
        self.setMinimumSize(280, 220)
        self.setMouseTracking(True)
        self._message = str(title or "")
        self._theme_key = theme_key
        self._dark_background_enabled = True
        self._current_model: Optional[ModelPreviewData] = None
        self._prepared_preview: Optional[PreparedModelPreviewData] = None
        self._payloads: Tuple[QtQuick3DPreviewBatchPayload, ...] = ()
        self._texture_cache_root = Path(tempfile.mkdtemp(prefix="cdmw_qtquick3d_preview_"))
        self._texture_cache_generation = 0
        self._active_texture_dir: Optional[Path] = None
        self._retired_texture_dirs: list[Path] = []
        self._retired_texture_cleanup_pending = False
        self._render_settings = clamp_model_preview_render_settings()
        self._use_textures = False
        self._high_quality_textures = True
        self._support_maps_disabled_override = False
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._distance = self._FIT_DISTANCE
        self._yaw = -35.0
        self._pitch = 20.0
        self._pan = (0.0, 0.0, 0.0)
        self._drag_active = False
        self._pan_drag_active = False
        self._pan_drag_button = Qt.NoButton
        self._last_mouse_pos = QPointF()
        self._last_apply_ms = 0.0
        self._last_payload_ms = 0.0
        self._available = False
        self._failure_reason = ""
        self._last_debug_details = ""
        self._bridge = _QtQuick3DPreviewBridge(self)
        self._sync_texture_options_to_bridge()
        self._apply_theme_to_bridge()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._quick_widget = QQuickWidget(self)
        self._quick_widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._quick_widget.installEventFilter(self)
        self._quick_widget.setMouseTracking(True)
        self._quick_widget.rootContext().setContextProperty("previewBridge", self._bridge)
        layout.addWidget(self._quick_widget, stretch=1)
        self._load_scene()
        self.clear_model(self._message)

    def _load_scene(self) -> None:
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
            brightness: 1.35
            ambientColor: "#5a6470"
            castsShadow: false
        }
        DirectionalLight {
            eulerRotation.x: 45
            eulerRotation.y: 140
            brightness: 0.55
            ambientColor: "#38414a"
            castsShadow: false
        }
        Node {
            id: sceneRoot
            position: Qt.vector3d(previewBridge.panX, previewBridge.panY, previewBridge.panZ)
            eulerRotation: Qt.vector3d(previewBridge.pitch, previewBridge.yaw, 0)
            Repeater3D {
                model: previewBridge.batchCount
                delegate: Model {
                    geometry: previewBridge.geometryFor(index, previewBridge.revision)
                    materials: PrincipledMaterial {
                        baseColor: previewBridge.baseColorFor(index, previewBridge.revision)
                        baseColorMap: previewBridge.textureEnabledFor(index, previewBridge.revision) ? baseTexture : null
                        normalMap: previewBridge.normalTextureEnabledFor(index, previewBridge.revision) ? normalTexture : null
                        normalStrength: previewBridge.normalStrengthFor(index, previewBridge.revision)
                        heightMap: previewBridge.heightTextureEnabledFor(index, previewBridge.revision) ? heightTexture : null
                        heightAmount: previewBridge.heightAmountFor(index, previewBridge.revision)
                        occlusionMap: previewBridge.materialTextureEnabledFor(index, previewBridge.revision, "occlusion") ? occlusionTexture : null
                        roughnessMap: previewBridge.materialTextureEnabledFor(index, previewBridge.revision, "roughness") ? roughnessTexture : null
                        metalnessMap: previewBridge.materialTextureEnabledFor(index, previewBridge.revision, "metalness") ? metalnessTexture : null
                        specularMap: previewBridge.materialTextureEnabledFor(index, previewBridge.revision, "specular") ? specularTexture : null
                        roughness: previewBridge.materialTextureEnabledFor(index, previewBridge.revision, "roughness") ? 1.0 : 0.58
                        metalness: previewBridge.materialTextureEnabledFor(index, previewBridge.revision, "metalness") ? 1.0 : 0.0
                        specularAmount: previewBridge.materialTextureEnabledFor(index, previewBridge.revision, "specular") ? 0.68 : 0.34
                        opacity: 1.0
                        alphaMode: PrincipledMaterial.Opaque
                        lighting: PrincipledMaterial.FragmentLighting
                        cullMode: Material.NoCulling
                    }
                    Texture {
                        id: baseTexture
                        source: previewBridge.textureSourceFor(index, previewBridge.revision)
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: normalTexture
                        source: previewBridge.normalTextureSourceFor(index, previewBridge.revision)
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: occlusionTexture
                        source: previewBridge.materialTextureSourceFor(index, previewBridge.revision, "occlusion")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: roughnessTexture
                        source: previewBridge.materialTextureSourceFor(index, previewBridge.revision, "roughness")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: metalnessTexture
                        source: previewBridge.materialTextureSourceFor(index, previewBridge.revision, "metalness")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: specularTexture
                        source: previewBridge.materialTextureSourceFor(index, previewBridge.revision, "specular")
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                    Texture {
                        id: heightTexture
                        source: previewBridge.heightTextureSourceFor(index, previewBridge.revision)
                        flipV: previewBridge.textureFlipVFor(index, previewBridge.revision)
                        autoOrientation: false
                    }
                }
            }
        }
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
        text: "Qt Quick 3D experimental"
        visible: previewBridge.batchCount > 0
    }
}
"""
        self._quick_widget.setSource(QUrl("data:text/plain;charset=utf-8," + quote(qml)))
        errors = self._quick_widget.errors()
        if self._quick_widget.status() == QQuickWidget.Status.Error or errors:
            self._available = False
            self._failure_reason = self._format_qml_errors(errors)
        else:
            self._available = True
            self._failure_reason = ""

    @staticmethod
    def _format_qml_errors(errors: Sequence[QQmlError]) -> str:
        text = "; ".join(error.toString() for error in errors)
        return text or "Qt Quick 3D scene could not be initialized."

    def is_available(self) -> bool:
        return bool(self._available)

    def failure_reason(self) -> str:
        return str(self._failure_reason or "")

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = str(theme_key or self._theme_key)
        self._apply_theme_to_bridge()

    def set_dark_background_enabled(self, enabled: bool) -> None:
        self._dark_background_enabled = bool(enabled)
        self._apply_theme_to_bridge()

    def dark_background_enabled(self) -> bool:
        return bool(self._dark_background_enabled)

    def _apply_theme_to_bridge(self) -> None:
        theme = get_theme(self._theme_key)
        background = QColor(theme["preview_bg"]) if self._dark_background_enabled else QColor("#f4f6f8")
        text = QColor(theme["text_muted"])
        self._bridge.set_theme_colors(background=background, text=text)

    def _retire_active_texture_dir(self) -> None:
        if self._active_texture_dir is None:
            return
        self._retired_texture_dirs.append(self._active_texture_dir)
        self._active_texture_dir = None
        if not self._retired_texture_cleanup_pending:
            self._retired_texture_cleanup_pending = True
            QTimer.singleShot(15000, self._release_retired_texture_dirs)

    def _release_retired_texture_dirs(self) -> None:
        self._retired_texture_cleanup_pending = False
        retired_dirs = self._retired_texture_dirs
        self._retired_texture_dirs = []
        retry_dirs: list[Path] = []
        for directory in retired_dirs:
            try:
                shutil.rmtree(directory, ignore_errors=False)
            except OSError:
                retry_dirs.append(directory)
        if retry_dirs:
            self._retired_texture_dirs.extend(retry_dirs)
            if not self._retired_texture_cleanup_pending:
                self._retired_texture_cleanup_pending = True
                QTimer.singleShot(15000, self._release_retired_texture_dirs)

    def _cleanup_texture_cache(self) -> None:
        self._retire_active_texture_dir()
        for directory in tuple(self._retired_texture_dirs):
            try:
                shutil.rmtree(directory, ignore_errors=True)
            except OSError:
                pass
        self._retired_texture_dirs = []
        try:
            shutil.rmtree(self._texture_cache_root, ignore_errors=True)
        except OSError:
            pass

    @staticmethod
    def _source_url_local_path(source_url: str) -> str:
        normalized = str(source_url or "").strip()
        if not normalized:
            return ""
        try:
            path = QUrl(normalized).toLocalFile()
        except Exception:
            path = ""
        return path or normalized

    def _prepare_qtquick3d_texture_url(
        self,
        source_url: str,
        output_dir: Path,
        stem: str,
        *,
        flip_vertical: bool,
        force_opaque: bool,
    ) -> Tuple[str, str, bool]:
        source_path = self._source_url_local_path(source_url)
        if not source_path:
            return "", "", False
        reader = QImageReader(source_path)
        image = reader.read()
        if image.isNull():
            source_name = Path(source_path).name if source_path else "texture"
            return source_url, f"raw:{source_name}; prepare=unreadable", False
        if force_opaque:
            image = image.convertToFormat(QImage.Format.Format_RGB888)
        else:
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        if image.isNull():
            source_name = Path(source_path).name if source_path else "texture"
            return source_url, f"raw:{source_name}; prepare=format-failed", False
        if flip_vertical:
            image = image.flipped(Qt.Orientation.Vertical)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{stem}.png"
        if not image.save(str(output_path), "PNG"):
            source_name = Path(source_path).name if source_path else "texture"
            return source_url, f"raw:{source_name}; prepare=save-failed", False
        note_parts = [f"prepared:{Path(source_path).name}"]
        if flip_vertical:
            note_parts.append("mirrored-v")
        if force_opaque:
            note_parts.append("opaque-rgb")
        return QUrl.fromLocalFile(str(output_path.resolve())).toString(), "; ".join(note_parts), True

    def _prepare_payload_textures(
        self,
        payloads: Sequence[QtQuick3DPreviewBatchPayload],
    ) -> Tuple[QtQuick3DPreviewBatchPayload, ...]:
        payload_tuple = tuple(payloads)
        self._retire_active_texture_dir()
        if not payload_tuple:
            return ()
        self._texture_cache_generation += 1
        output_dir = self._texture_cache_root / f"preview_{self._texture_cache_generation:06d}"
        prepared_payloads: list[QtQuick3DPreviewBatchPayload] = []
        any_prepared = False
        settings = self.render_settings()
        combiner_settings = QtQuick3DMaterialCombinerSettings(
            normal_strength_floor=float(getattr(settings, "normal_strength_floor", 0.5) or 0.5),
            normal_strength_cap=float(getattr(settings, "normal_strength_cap", 1.0) or 1.0),
            height_amount=max(0.0, min(0.12, float(getattr(settings, "height_effect_max", 0.35) or 0.0) * 0.12)),
            support_map_max_dimension=min(256, int(getattr(settings, "low_quality_texture_max_dimension", 256) or 256)),
        )
        for batch_index, payload in enumerate(payload_tuple):
            combined = combine_qtquick3d_material(
                payload,
                output_dir,
                batch_index,
                settings=combiner_settings,
            )
            generated_sources = (
                combined.base_source,
                combined.normal_source,
                combined.occlusion_source,
                combined.roughness_source,
                combined.metalness_source,
                combined.specular_source,
                combined.height_source,
            )
            payload_prepared_any = any(bool(source) for source in generated_sources)
            any_prepared = any_prepared or payload_prepared_any
            prepared_payloads.append(
                replace(
                    payload,
                    texture_source=combined.base_source,
                    texture_prepare_note=combined.base_note,
                    normal_texture_source=combined.normal_source,
                    normal_texture_strength=combined.normal_strength or payload.normal_texture_strength,
                    occlusion_texture_source=combined.occlusion_source,
                    roughness_texture_source=combined.roughness_source,
                    metalness_texture_source=combined.metalness_source,
                    specular_texture_source=combined.specular_source,
                    height_texture_source=combined.height_source,
                    height_texture_amount=combined.height_amount,
                    material_texture_slots=combined.material_slots,
                    material_combiner_active=combined.active,
                    material_combiner_notes=combined.notes,
                    material_combiner_decode_modes=combined.decode_modes,
                    material_combiner_outputs=combined.outputs,
                    texture_flip_vertical=combined.texture_flip_vertical,
                )
            )
        if any_prepared:
            self._active_texture_dir = output_dir
        elif output_dir.exists():
            try:
                shutil.rmtree(output_dir, ignore_errors=True)
            except OSError:
                pass
        return tuple(prepared_payloads)

    def clear_model(self, message: str, *, release_gl: bool = False) -> None:
        del release_gl
        self._retire_active_texture_dir()
        self._message = str(message or "")
        self._current_model = None
        self._prepared_preview = None
        self._payloads = ()
        self._bridge.set_message(self._message)
        self._bridge.set_payloads(())
        self._last_apply_ms = 0.0
        self._last_payload_ms = 0.0
        self._refresh_debug_details()

    def set_model(self, model) -> None:
        from cdmw.ui.widgets import ModelPreviewWidget

        prepared_model, prepared_preview = ModelPreviewWidget.prepare_model_preview(model)
        self.set_prepared_model(prepared_model, prepared_preview)

    def set_prepared_model(self, model, prepared_preview: Optional[PreparedModelPreviewData]) -> None:
        started = time.perf_counter()
        if not isinstance(model, ModelPreviewData):
            self.clear_model("No model preview available.")
            return
        if not isinstance(prepared_preview, PreparedModelPreviewData):
            self.set_model(model)
            return
        payload_started = time.perf_counter()
        payloads = self._prepare_payload_textures(build_qtquick3d_preview_payloads(prepared_preview))
        self._last_payload_ms = max(0.0, (time.perf_counter() - payload_started) * 1000.0)
        self._current_model = self._clone_model_preview(model)
        self._prepared_preview = prepared_preview
        self._payloads = payloads
        self._bridge.set_message(str(getattr(model, "summary", "") or "Model preview ready."))
        self._bridge.set_payloads(payloads)
        self._yaw = -35.0
        self._pitch = 20.0
        self._fit_to_view = True
        self._zoom_factor = 1.0
        self._distance = self._FIT_DISTANCE
        self._pan = (0.0, 0.0, 0.0)
        self._sync_camera_to_bridge()
        self._last_apply_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)
        self._refresh_debug_details()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._cleanup_texture_cache()
        super().closeEvent(event)

    @staticmethod
    def _clone_model_preview(model: ModelPreviewData) -> ModelPreviewData:
        meshes: list[object] = []
        for mesh in getattr(model, "meshes", ()) or ():
            if isinstance(mesh, ModelPreviewMesh):
                from dataclasses import fields

                meshes.append(ModelPreviewMesh(**{field.name: getattr(mesh, field.name) for field in fields(ModelPreviewMesh)}))
            else:
                meshes.append(mesh)
        from dataclasses import fields

        return ModelPreviewData(
            **{
                field.name: meshes if field.name == "meshes" else getattr(model, field.name)
                for field in fields(ModelPreviewData)
            }
        )

    def current_model_preview(self) -> Optional[ModelPreviewData]:
        return self._current_model

    def set_render_settings(self, settings: Optional[ModelPreviewRenderSettings]) -> None:
        self._render_settings = clamp_model_preview_render_settings(settings)
        self._sync_texture_options_to_bridge()
        self._refresh_debug_details()

    def render_settings(self) -> ModelPreviewRenderSettings:
        return clamp_model_preview_render_settings(self._render_settings)

    def set_use_textures(self, use_textures: bool) -> None:
        self._use_textures = bool(use_textures)
        self._sync_texture_options_to_bridge()
        self._refresh_debug_details()

    def set_high_quality_textures(self, enabled: bool) -> None:
        self._high_quality_textures = bool(enabled)
        self._sync_texture_options_to_bridge()
        self._refresh_debug_details()

    def textures_available(self) -> bool:
        return any(
            payload.has_texture_coordinates
            and (
                payload.texture_source
                or payload.normal_texture_source
                or payload.material_texture_source
                or payload.height_texture_source
            )
            for payload in self._payloads
        )

    def support_maps_available(self) -> bool:
        return any(
            payload.has_texture_coordinates
            and (payload.normal_texture_source or payload.material_texture_source or payload.height_texture_source)
            for payload in self._payloads
        )

    def debug_overrides_active(self) -> bool:
        return False

    def base_flip_override_enabled(self) -> bool:
        return False

    def support_maps_disabled(self) -> bool:
        settings = self.render_settings()
        return bool(self._support_maps_disabled_override or getattr(settings, "disable_all_support_maps", False))

    def reset_preview_overrides(self) -> None:
        if self._support_maps_disabled_override:
            self._support_maps_disabled_override = False
            self._sync_texture_options_to_bridge()
            self._refresh_debug_details()

    def set_base_texture_flip_override_enabled(self, enabled: bool) -> None:
        del enabled

    def set_support_maps_disabled(self, enabled: bool) -> None:
        self._support_maps_disabled_override = bool(enabled)
        self._sync_texture_options_to_bridge()
        self._refresh_debug_details()

    def _support_maps_globally_enabled(self) -> bool:
        settings = self.render_settings()
        return bool(
            self._use_textures
            and self._high_quality_textures
            and not self._support_maps_disabled_override
            and not getattr(settings, "disable_all_support_maps", False)
        )

    def _sync_texture_options_to_bridge(self) -> None:
        settings = self.render_settings()
        height_amount = max(0.0, min(0.12, float(getattr(settings, "height_effect_max", 0.35) or 0.0) * 0.12))
        self._bridge.set_textures_enabled(self._use_textures)
        self._bridge.set_support_map_options(
            enabled=self._support_maps_globally_enabled(),
            normal_enabled=not bool(getattr(settings, "disable_normal_map", False)),
            material_enabled=not bool(getattr(settings, "disable_material_map", False)),
            height_enabled=not bool(getattr(settings, "disable_height_map", False)),
            normal_strength_floor=float(getattr(settings, "normal_strength_floor", 0.5) or 0.5),
            normal_strength_cap=float(getattr(settings, "normal_strength_cap", 1.0) or 1.0),
            height_amount=height_amount,
        )

    def debug_details_text(self) -> str:
        return self._last_debug_details

    def set_zoom_factor(self, zoom_factor: float) -> None:
        self._zoom_factor = min(max(float(zoom_factor), 0.1), 16.0)
        if not self._fit_to_view:
            self._distance = self._FIT_DISTANCE / self._zoom_factor
        self._sync_camera_to_bridge()
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def set_fit_to_view(self, fit_to_view: bool) -> None:
        self._fit_to_view = bool(fit_to_view)
        self._distance = self._FIT_DISTANCE if self._fit_to_view else self._FIT_DISTANCE / self._zoom_factor
        self._sync_camera_to_bridge()
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)

    def current_display_scale(self) -> float:
        return max(0.1, self._FIT_DISTANCE / max(self._distance, 0.01))

    def _sync_camera_to_bridge(self) -> None:
        self._bridge.set_camera(yaw=self._yaw, pitch=self._pitch, distance=self._distance, pan=self._pan)

    def _world_units_per_pixel(self) -> float:
        viewport_height = max(1, self.height())
        visible_height = 2.0 * max(self._distance, 0.1) * math.tan(math.radians(self._VERTICAL_FOV_DEGREES) * 0.5)
        return visible_height / float(viewport_height)

    def _apply_pan_delta(self, delta_x: float, delta_y: float) -> None:
        settings = self.render_settings()
        units_per_pixel = self._world_units_per_pixel()
        horizontal_sign = -1.0 if settings.invert_pan_x else 1.0
        vertical_sign = 1.0 if settings.invert_pan_y else -1.0
        pan_scale = float(settings.pan_sensitivity)
        self._pan = (
            self._pan[0] + float(delta_x) * units_per_pixel * pan_scale * horizontal_sign,
            self._pan[1] + float(delta_y) * units_per_pixel * pan_scale * vertical_sign,
            self._pan[2],
        )
        self._sync_camera_to_bridge()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if watched is not self._quick_widget:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonPress:
            return self._handle_mouse_press(event)
        if event.type() == QEvent.Type.MouseMove:
            return self._handle_mouse_move(event)
        if event.type() == QEvent.Type.MouseButtonRelease:
            return self._handle_mouse_release(event)
        if event.type() == QEvent.Type.Wheel:
            return self._handle_wheel(event)
        return super().eventFilter(watched, event)

    def _handle_mouse_press(self, event) -> bool:
        if not self._payloads:
            return False
        pan_requested = (
            event.button() == Qt.MouseButton.MiddleButton
            or event.button() == Qt.MouseButton.RightButton
            or (event.button() == Qt.MouseButton.LeftButton and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        )
        if pan_requested:
            self._pan_drag_active = True
            self._pan_drag_button = event.button()
            self._last_mouse_pos = QPointF(event.position())
            self._quick_widget.setCursor(Qt.CursorShape.SizeAllCursor)
            self._quick_widget.grabMouse()
            event.accept()
            return True
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._last_mouse_pos = QPointF(event.position())
            self._quick_widget.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._quick_widget.grabMouse()
            event.accept()
            return True
        return False

    def _handle_mouse_move(self, event) -> bool:
        if self._drag_active:
            current = QPointF(event.position())
            delta = current - self._last_mouse_pos
            self._last_mouse_pos = current
            settings = self.render_settings()
            orbit_sign_x = -1.0 if settings.invert_orbit_x else 1.0
            orbit_sign_y = -1.0 if settings.invert_orbit_y else 1.0
            orbit_scale = float(settings.orbit_sensitivity)
            self._yaw += float(delta.x()) * orbit_scale * orbit_sign_x
            self._pitch = max(-89.0, min(89.0, self._pitch + float(delta.y()) * orbit_scale * orbit_sign_y))
            self._sync_camera_to_bridge()
            event.accept()
            return True
        if self._pan_drag_active:
            current = QPointF(event.position())
            delta = current - self._last_mouse_pos
            self._last_mouse_pos = current
            self._apply_pan_delta(float(delta.x()), float(delta.y()))
            event.accept()
            return True
        return False

    def _handle_mouse_release(self, event) -> bool:
        if self._drag_active and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._quick_widget.releaseMouse()
            self._quick_widget.unsetCursor()
            event.accept()
            return True
        if self._pan_drag_active and event.button() == self._pan_drag_button:
            self._pan_drag_active = False
            self._pan_drag_button = Qt.MouseButton.NoButton
            self._quick_widget.releaseMouse()
            self._quick_widget.unsetCursor()
            event.accept()
            return True
        return False

    def _handle_wheel(self, event) -> bool:
        if not self._payloads:
            return False
        step = 1 if event.angleDelta().y() > 0 else -1
        current_zoom = self.current_display_scale() if self._fit_to_view else self._zoom_factor
        closest_index = min(range(len(self._ZOOM_STEPS)), key=lambda index: abs(self._ZOOM_STEPS[index] - current_zoom))
        next_index = min(max(closest_index + step, 0), len(self._ZOOM_STEPS) - 1)
        self._fit_to_view = False
        self._zoom_factor = self._ZOOM_STEPS[next_index]
        self._distance = self._FIT_DISTANCE / self._zoom_factor
        self._sync_camera_to_bridge()
        self.view_state_changed.emit(self._zoom_factor, self._fit_to_view)
        event.accept()
        return True

    def _refresh_debug_details(self) -> None:
        base_texture_count = sum(1 for payload in self._payloads if payload.texture_source)
        normal_texture_count = sum(1 for payload in self._payloads if payload.normal_texture_source)
        material_texture_count = sum(
            1
            for payload in self._payloads
            if payload.occlusion_texture_source
            or payload.roughness_texture_source
            or payload.metalness_texture_source
            or payload.specular_texture_source
        )
        height_texture_count = sum(1 for payload in self._payloads if payload.height_texture_source)
        material_slot_names = ("occlusion", "roughness", "metalness", "specular")
        material_slot_available_summary = " ".join(
            f"{slot}:{sum(1 for payload in self._payloads if slot in payload.material_texture_slots)}"
            for slot in material_slot_names
        )
        material_slot_active_summary = " ".join(
            f"{slot}:{sum(1 for index in range(len(self._payloads)) if self._bridge.materialTextureEnabledFor(index, self._bridge.revision, slot))}"
            for slot in material_slot_names
        )
        normal_active_count = sum(
            1
            for index in range(len(self._payloads))
            if self._bridge.normalTextureEnabledFor(index, self._bridge.revision)
        )
        height_active_count = sum(
            1
            for index in range(len(self._payloads))
            if self._bridge.heightTextureEnabledFor(index, self._bridge.revision)
        )
        opacity_suppressed_count = sum(
            1
            for payload in self._payloads
            if payload.material_texture_source
            and (
                payload.material_texture_subtype in {"opacity", "opacity_mask", "alpha"}
                or any(channel in {"opacity", "alpha"} for channel in payload.material_texture_packed_channels)
            )
        )
        base_texture_notes = []
        for batch_index, payload in enumerate(self._payloads[:6]):
            if not payload.texture_source:
                continue
            source_name = Path(self._source_url_local_path(payload.texture_source)).name
            label = payload.material_name or payload.texture_name or f"batch {batch_index}"
            note = payload.texture_prepare_note or "raw"
            base_texture_notes.append(f"{batch_index}:{label}->{source_name} ({note})")
        base_texture_note_line = ""
        if base_texture_notes:
            remaining = max(0, base_texture_count - len(base_texture_notes))
            base_texture_note_line = "Base Texture Inputs: " + "; ".join(base_texture_notes)
            if remaining:
                base_texture_note_line += f"; +{remaining:,} more"
        combiner_active_count = sum(1 for payload in self._payloads if payload.material_combiner_active)
        combiner_output_counts = {
            "albedo": sum(1 for payload in self._payloads if "albedo" in payload.material_combiner_outputs),
            "normal": sum(
                1
                for payload in self._payloads
                if "normal" in payload.material_combiner_outputs or "normal-from-height" in payload.material_combiner_outputs
            ),
            "ao": sum(1 for payload in self._payloads if "occlusion" in payload.material_combiner_outputs),
            "roughness": sum(1 for payload in self._payloads if "roughness" in payload.material_combiner_outputs),
            "metal": sum(1 for payload in self._payloads if "metalness" in payload.material_combiner_outputs),
            "specular": sum(1 for payload in self._payloads if "specular" in payload.material_combiner_outputs),
            "height": sum(1 for payload in self._payloads if "height" in payload.material_combiner_outputs),
        }
        combiner_decode_modes: list[str] = []
        combiner_notes: list[str] = []
        combiner_outputs: list[str] = []
        for payload in self._payloads:
            for mode in payload.material_combiner_decode_modes:
                if mode and mode not in combiner_decode_modes:
                    combiner_decode_modes.append(mode)
            for note in payload.material_combiner_notes:
                if note and note not in combiner_notes:
                    combiner_notes.append(note)
            for output in payload.material_combiner_outputs:
                if output and output not in combiner_outputs:
                    combiner_outputs.append(output)
        combiner_line = (
            "Material Combiner: "
            f"active={'yes' if combiner_active_count else 'no'}; "
            f"batches={combiner_active_count:,}; "
            "generated="
            + " ".join(f"{slot}:{count:,}" for slot, count in combiner_output_counts.items())
            + (
                f"; decode={','.join(combiner_decode_modes[:6])}"
                if combiner_decode_modes
                else "; decode=none"
            )
        )
        combiner_note_line = ""
        if combiner_notes:
            combiner_note_line = "Material Combiner Notes: " + "; ".join(combiner_notes[:8])
            if len(combiner_notes) > 8:
                combiner_note_line += f"; +{len(combiner_notes) - 8:,} more"
        combiner_output_line = ""
        if combiner_outputs:
            combiner_output_line = "Generated PBR Maps: " + ", ".join(combiner_outputs[:10])
        details = "\n".join(
            (
                "Visible Mode: Qt Quick 3D Experimental",
                (
                    "Renderer: Qt Quick 3D experimental; "
                    f"available={'yes' if self._available else 'no'}; "
                    f"batches={len(self._payloads):,}; "
                    f"vertices={sum(payload.vertex_count for payload in self._payloads):,}; "
                    f"textures=base:{base_texture_count:,} normal:{normal_texture_count:,} "
                    f"material:{material_texture_count:,} height:{height_texture_count:,}; "
                    f"use_textures={'yes' if self._use_textures else 'no'}; "
                    f"support_maps={'yes' if self._support_maps_globally_enabled() else 'no'}; "
                    f"payload={self._last_payload_ms:.1f} ms; apply={self._last_apply_ms:.1f} ms"
                ),
                (
                    f"PBR Slots: available {material_slot_available_summary}; active {material_slot_active_summary}; "
                    f"normal_active:{normal_active_count:,}; height_active:{height_active_count:,}; "
                    f"normal_pbr={'yes' if self._bridge.normal_pbr_maps_enabled() else 'no'}; "
                    f"material_pbr={'yes' if self._bridge.material_pbr_maps_enabled() else 'no'}; "
                    f"height_pbr={'yes' if self._bridge.height_pbr_maps_enabled() else 'no'}"
                    + (f"; opacity maps suppressed:{opacity_suppressed_count:,}" if opacity_suppressed_count else "")
                ),
                combiner_line,
                *((combiner_output_line,) if combiner_output_line else ()),
                *((combiner_note_line,) if combiner_note_line else ()),
                *((base_texture_note_line,) if base_texture_note_line else ()),
                (
                    "Renderer Limitation: shader-specific detail/vector/opacity layers are skipped or conservatively decoded; "
                    "height is preview relief, not real mesh displacement."
                ),
                (
                    "Legacy-only: detailed shader diagnostics, texture probe modes, HKX overlays, alignment handles, and mesh editing."
                ),
                *(("Renderer Fallback: " + self._failure_reason,) if self._failure_reason else ()),
            )
        )
        if details != self._last_debug_details:
            self._last_debug_details = details
            self.debug_details_changed.emit(details)


__all__ = [
    "ARCHIVE_MODEL_RENDERER_DEFAULT",
    "ARCHIVE_MODEL_RENDERER_LABELS",
    "ARCHIVE_MODEL_RENDERER_LEGACY_OPENGL",
    "ARCHIVE_MODEL_RENDERER_QTQUICK3D",
    "ExperimentalQtQuick3DModelPreviewWidget",
    "QtQuick3DPreviewBatchPayload",
    "build_qtquick3d_preview_payloads",
    "configure_experimental_qtquick3d_rhi",
    "normalize_archive_model_renderer_backend",
]
