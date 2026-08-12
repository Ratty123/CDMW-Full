"""Qt Quick 3D viewport spike.

Renders a real PAC through CDMW's own parser inside a `QQuick3DGeometry` node,
to answer one question the current architecture cannot: can the mesh viewport be
an ordinary Qt scene-graph item instead of a Win32 child window reparented with
`SetParent`?

This is an experiment. It is deliberately outside `cdmw/` and touches no
production Edit Mesh code. It reads assets and never writes them.

Background, measured before this was written:

- Packing a 200k-vertex interleaved buffer and calling `setVertexData` costs
  ~1.45 ms, 9% of a 16.6 ms frame.
- A 200k-vertex point cloud republished in full every frame sustained 173 fps
  with 1.8% RSS growth over 4,336 frames. The documented dynamic-geometry
  memory growth did not reproduce.

What this spike adds is the real thing: actual PAC geometry, real triangle
counts, real submesh splits, and Qt UI composited above the 3D content, which a
child HWND can never allow.

Usage:

    .venv\\Scripts\\python.exe tools\\qtquick3d_viewport_spike\\viewport_spike.py --pac <path>
    .venv\\Scripts\\python.exe tools\\qtquick3d_viewport_spike\\viewport_spike.py --synthetic 200000

`--seconds N` closes the window automatically and writes a JSON report, which is
how it runs unattended.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QByteArray, QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QVector3D  # noqa: E402
from PySide6.QtQml import qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface  # noqa: E402
from PySide6.QtQuick3D import QQuick3DGeometry  # noqa: E402

STRIDE_FLOATS = 8  # position3 + normal3 + uv2
STRIDE_BYTES = STRIDE_FLOATS * 4


@dataclass(frozen=True)
class LoadedMesh:
    """Flattened, render-ready geometry plus where it came from."""

    interleaved: np.ndarray  # (n, 8) float32
    indices: np.ndarray  # (m,) uint32
    submesh_count: int
    source: str

    @property
    def vertex_count(self) -> int:
        return int(self.interleaved.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.indices.size // 3)


def load_pac(path: Path) -> LoadedMesh:
    """Flatten every submesh of a parsed PAC into one interleaved buffer.

    Submeshes are concatenated with their face indices rebased, because this
    spike is answering a rendering question, not a per-part selection one.
    """
    from cdmw.modding.mesh_parser import parse_mesh

    # parse_mesh takes bytes and dispatches on the filename's extension. Passing
    # a path as `data` silently routes to the PAM branch and reports the path's
    # own first four characters as a bad magic number.
    parsed = parse_mesh(path.read_bytes(), str(path))
    blocks: list[np.ndarray] = []
    index_blocks: list[np.ndarray] = []
    base = 0

    for submesh in parsed.submeshes:
        count = len(submesh.vertices)
        if count == 0:
            continue
        block = np.zeros((count, STRIDE_FLOATS), dtype=np.float32)
        block[:, 0:3] = np.asarray(submesh.vertices, dtype=np.float32)
        if len(submesh.normals) == count:
            block[:, 3:6] = np.asarray(submesh.normals, dtype=np.float32)
        else:
            block[:, 4] = 1.0
        if len(submesh.uvs) == count:
            block[:, 6:8] = np.asarray(submesh.uvs, dtype=np.float32)
        blocks.append(block)

        if submesh.faces:
            faces = np.asarray(submesh.faces, dtype=np.uint32).reshape(-1)
            index_blocks.append(faces + np.uint32(base))
        base += count

    if not blocks:
        raise ValueError(
            f"{path.name} parsed but contains no geometry. Repo test extracts "
            f"are sanitised stubs; point --pac at a real game asset."
        )

    interleaved = np.concatenate(blocks, axis=0)
    indices = (
        np.concatenate(index_blocks) if index_blocks
        else np.arange(interleaved.shape[0], dtype=np.uint32)
    )
    return LoadedMesh(interleaved, indices, len(blocks), path.name)


def build_synthetic(target_vertices: int) -> LoadedMesh:
    """A dense UV sphere at roughly character scale, for when no real asset is
    reachable. Labelled as synthetic everywhere it is reported."""
    rings = max(4, int(math.sqrt(target_vertices / 2)))
    segments = rings * 2
    u = np.linspace(0.0, math.pi, rings, dtype=np.float32)
    v = np.linspace(0.0, 2.0 * math.pi, segments, dtype=np.float32)
    uu, vv = np.meshgrid(u, v, indexing="ij")
    radius = 90.0

    normals = np.stack(
        [np.sin(uu) * np.cos(vv), np.cos(uu), np.sin(uu) * np.sin(vv)], axis=-1
    ).reshape(-1, 3)
    positions = normals * radius

    block = np.zeros((positions.shape[0], STRIDE_FLOATS), dtype=np.float32)
    block[:, 0:3] = positions
    block[:, 3:6] = normals
    block[:, 6] = (vv / (2.0 * math.pi)).reshape(-1)
    block[:, 7] = (uu / math.pi).reshape(-1)

    tris: list[tuple[int, int, int]] = []
    for i in range(rings - 1):
        for j in range(segments - 1):
            a = i * segments + j
            b = a + segments
            tris.append((a, b, a + 1))
            tris.append((a + 1, b, b + 1))
    indices = np.asarray(tris, dtype=np.uint32).reshape(-1)
    return LoadedMesh(block, indices, 1, f"synthetic sphere ({rings}x{segments})")


class MeshGeometry(QQuick3DGeometry):
    """The whole point of the spike: real mesh data as a scene-graph node."""

    mesh: LoadedMesh | None = None

    def __init__(self, parent=None):
        super().__init__(parent)
        mesh = MeshGeometry.mesh
        if mesh is None:
            raise RuntimeError("MeshGeometry.mesh must be set before QML loads")
        self._mesh = mesh
        self._buffer = mesh.interleaved.copy()
        self._phase = 0.0

        self.setStride(STRIDE_BYTES)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(
            QQuick3DGeometry.Attribute.PositionSemantic, 0,
            QQuick3DGeometry.Attribute.F32Type,
        )
        self.addAttribute(
            QQuick3DGeometry.Attribute.NormalSemantic, 12,
            QQuick3DGeometry.Attribute.F32Type,
        )
        self.addAttribute(
            QQuick3DGeometry.Attribute.TexCoord0Semantic, 24,
            QQuick3DGeometry.Attribute.F32Type,
        )
        self.addAttribute(
            QQuick3DGeometry.Attribute.IndexSemantic, 0,
            QQuick3DGeometry.Attribute.U32Type,
        )
        self.setIndexData(QByteArray(mesh.indices.tobytes()))

        lo = mesh.interleaved[:, 0:3].min(axis=0)
        hi = mesh.interleaved[:, 0:3].max(axis=0)
        self.setBounds(
            QVector3D(float(lo[0]), float(lo[1]), float(lo[2])),
            QVector3D(float(hi[0]), float(hi[1]), float(hi[2])),
        )
        self._publish()

    def _publish(self) -> None:
        self.setVertexData(QByteArray(self._buffer.tobytes()))
        self.update()

    def sculpt_tick(self) -> None:
        """Stand in for a brush stroke: displace along normals and republish the
        whole buffer, which is the worst case the real editor produces."""
        self._phase += 0.04
        amount = 2.5 * math.sin(self._phase)
        np.add(
            self._mesh.interleaved[:, 0:3],
            self._mesh.interleaved[:, 3:6] * amount,
            out=self._buffer[:, 0:3],
        )
        self._publish()


QML_TEMPLATE = """
import QtQuick
import QtQuick.Controls
import QtQuick3D
import Cdmw.Spike

Item {
    anchors.fill: parent

    View3D {
        id: view
        anchors.fill: parent
        // Declaring a camera inside View3D does NOT activate it. Without this
        // the scene presents empty frames, which benchmarks beautifully and
        // means nothing.
        camera: cam
        environment: SceneEnvironment {
            clearColor: "#1c1c20"
            backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA
        }
        PerspectiveCamera {
            id: cam
            z: %(camz)f
            clipFar: 100000
        }
        DirectionalLight { eulerRotation.x: -30; eulerRotation.y: -60 }
        DirectionalLight { eulerRotation.x: 20; eulerRotation.y: 130; brightness: 0.4 }
        Model {
            id: model
            geometry: MeshGeometry { }
            materials: PrincipledMaterial {
                baseColor: "#93a4c8"
                metalness: 0.05
                roughness: 0.65
            }
            eulerRotation.y: orbit.angle
        }
    }

    QtObject { id: orbit; property real angle: 0 }
    NumberAnimation {
        target: orbit; property: "angle"; from: 0; to: 360
        duration: 18000; loops: Animation.Infinite; running: true
    }

    // The thing a child HWND makes impossible: Qt UI drawn OVER the 3D view.
    Rectangle {
        anchors { left: parent.left; top: parent.top; margins: 12 }
        width: overlayText.implicitWidth + 24
        height: overlayText.implicitHeight + 16
        radius: 6
        color: "#cc000000"
        Text {
            id: overlayText
            anchors.centerIn: parent
            color: "#e8e8ea"
            font.pixelSize: 12
            text: "%(caption)s"
        }
    }
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pac", type=Path, help="path to a real PAC/PAM asset")
    src.add_argument("--synthetic", type=int, metavar="N",
                     help="synthetic sphere with about N vertices")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="auto-close after N seconds and write a JSON report")
    ap.add_argument("--no-sculpt", action="store_true",
                    help="render statically instead of republishing every frame")
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()

    if args.pac:
        mesh = load_pac(args.pac)
        kind = "real_pac"
    else:
        mesh = build_synthetic(args.synthetic)
        kind = "synthetic"

    print(f"source        : {mesh.source}  [{kind}]")
    print(f"vertices      : {mesh.vertex_count:,}")
    print(f"triangles     : {mesh.triangle_count:,}")
    print(f"submeshes     : {mesh.submesh_count}")
    print(f"buffer        : {mesh.interleaved.nbytes / 1e6:.1f} MB")

    MeshGeometry.mesh = mesh
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    app = QGuiApplication(sys.argv)
    qmlRegisterType(MeshGeometry, "Cdmw.Spike", 1, 0, "MeshGeometry")

    extent = float(np.abs(mesh.interleaved[:, 0:3]).max()) or 100.0
    caption = (
        f"{mesh.source}   {mesh.vertex_count:,} verts / "
        f"{mesh.triangle_count:,} tris   Qt Quick 3D"
    )
    qml_path = Path(__file__).with_name("_spike.qml")
    qml_path.write_text(
        QML_TEMPLATE % {"camz": extent * 3.0, "caption": caption},
        encoding="utf-8",
    )

    view = QQuickView()
    view.setTitle("CDMW Qt Quick 3D viewport spike")
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(1100, 720)
    view.setSource(QUrl.fromLocalFile(str(qml_path)))
    if view.status() == QQuickView.Status.Error:
        for err in view.errors():
            print("QML ERROR:", err.toString())
        return 2
    view.show()

    geometry = next(iter(view.rootObject().findChildren(MeshGeometry)), None)
    if geometry is None:
        print("could not reach the geometry instance")
        return 3

    stats = {"frames": 0, "warm_frames": 0, "warm_t0": None, "t0": time.perf_counter()}
    warmup_s = min(3.0, max(1.0, args.seconds / 6.0)) if args.seconds else 3.0

    def on_frame() -> None:
        stats["frames"] += 1
        if stats["warm_t0"] is None and time.perf_counter() - stats["t0"] >= warmup_s:
            stats["warm_t0"] = time.perf_counter()
            stats["warm_frames"] = stats["frames"]
        if not args.no_sculpt:
            geometry.sculpt_tick()

    view.frameSwapped.connect(on_frame)

    if args.seconds > 0:
        def finish() -> None:
            now = time.perf_counter()
            elapsed = now - (stats["warm_t0"] or stats["t0"])
            frames = stats["frames"] - stats["warm_frames"]
            fps = frames / elapsed if elapsed > 0 else 0.0

            # Proof the frames contained geometry. An unassigned camera renders
            # empty frames very fast, so fps alone is not evidence of anything.
            shot = view.grabWindow()
            clear = shot.pixelColor(4, 4).rgb() if not shot.isNull() else 0
            drawn = 0
            total = 0
            if not shot.isNull():
                step = max(1, shot.width() // 160)
                for y in range(0, shot.height(), step):
                    for x in range(0, shot.width(), step):
                        total += 1
                        if shot.pixelColor(x, y).rgb() != clear:
                            drawn += 1
            coverage = (drawn / total * 100.0) if total else 0.0

            report = {
                "pixel_coverage_pct": round(coverage, 1),
                "geometry_visible": coverage > 1.0,
                "source": mesh.source,
                "kind": kind,
                "vertices": mesh.vertex_count,
                "triangles": mesh.triangle_count,
                "submeshes": mesh.submesh_count,
                "republish_every_frame": not args.no_sculpt,
                "sustained_fps": round(fps, 1),
                "frames_measured": frames,
            }
            print(json.dumps(report, indent=2))
            if args.report:
                args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            app.quit()

        QTimer.singleShot(int(args.seconds * 1000), finish)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
