"""Can CDMW reconstruct Qt Quick 3D's projection well enough to do its own
per-vertex picking?

This is the question that decides whether Qt Quick 3D can host the Edit Mesh
viewport. Rendering throughput is already proven (397k triangles at 174 fps).
Picking is not, and it is the harder half:

- PySide6's QtQuick3D module exports only QQuick3D, QQuick3DGeometry,
  QQuick3DInstancing, QQuick3DObject, QQuick3DRenderExtension and
  QQuick3DTextureData. There is no camera or viewport class, so Python cannot
  ask Qt for a view-projection matrix.
- CDMW's selection is per-vertex (click, brush, rectangle, lasso) over meshes
  far too dense to round-trip through QML per pointer sample. It must project
  vertices itself, in bulk, using a matrix it builds once per gesture. That is
  what the C# renderer already does.

So the matrix has to be reconstructed. If the reconstruction disagrees with Qt
even slightly, every selection lands offset from the cursor, which is exactly
the class of defect this project keeps paying for.

Method: read the camera's `sceneTransform` and lens properties through QML,
build the view-projection matrix in Python, project known points, and compare
against `View3D.mapFrom3DScene()` as ground truth.

PASS     : max error < 0.5 px  (sub-pixel, picking is solved)
MARGINAL : max error < 2.0 px  (usable, but investigate before relying on it)
FAIL     : >= 2.0 px, or the camera transform cannot be read at all
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QMetaObject, QTimer, QUrl, Qt
import numpy as np
from PySide6.QtGui import QGuiApplication, QMatrix4x4
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

WIDTH, HEIGHT = 1024, 768

# Deliberately an awkward camera: off-axis position and rotation on two axes,
# so an accidental convention match cannot pass by symmetry.
CAM_POS = (120.0, 80.0, 300.0)
CAM_EULER = (-15.0, 20.0, 0.0)
FOV = 55.0
CLIP_NEAR, CLIP_FAR = 1.0, 10000.0

# Spread across the frustum, including off-centre and near-edge cases.
TEST_POINTS = [
    (0.0, 0.0, 0.0),
    (50.0, 0.0, 0.0),
    (-50.0, 0.0, 0.0),
    (0.0, 60.0, 0.0),
    (0.0, -60.0, 0.0),
    (40.0, 40.0, 40.0),
    (-40.0, -40.0, -40.0),
    (90.0, -20.0, 60.0),
    (-70.0, 35.0, -80.0),
    (10.0, 5.0, 150.0),
    (-120.0, 90.0, 20.0),
    (25.0, -75.0, -110.0),
]

QML = """
import QtQuick
import QtQuick3D

Item {
    id: root
    anchors.fill: parent

    property var testPoints: []
    property var mapped: []
    property var camXform: null
    property real camFov: 0
    property real camNear: 0
    property real camFar: 0
    property int  camFovOrientation: 0
    property real viewW: 0
    property real viewH: 0

    View3D {
        id: view
        anchors.fill: parent
        // Declaring a camera inside View3D does NOT activate it. Without this
        // line mapFrom3DScene returns a null vector for every point.
        camera: cam
        environment: SceneEnvironment { clearColor: "#181820"; backgroundMode: SceneEnvironment.Color }
        PerspectiveCamera {
            id: cam
            position: Qt.vector3d(%(px)f, %(py)f, %(pz)f)
            eulerRotation: Qt.vector3d(%(rx)f, %(ry)f, %(rz)f)
            fieldOfView: %(fov)f
            clipNear: %(near)f
            clipFar: %(far)f
        }
        DirectionalLight { }
    }

    // Called from Python. Publishes Qt's own answer plus everything needed to
    // reconstruct it, so the comparison uses one consistent frame.
    function collect() {
        root.camXform = cam.sceneTransform;
        root.camFov = cam.fieldOfView;
        root.camNear = cam.clipNear;
        root.camFar = cam.clipFar;
        root.camFovOrientation = cam.fieldOfViewOrientation;
        root.viewW = view.width;
        root.viewH = view.height;

        var out = [];
        for (var i = 0; i < root.testPoints.length; ++i) {
            var p = root.testPoints[i];
            var s = view.mapFrom3DScene(Qt.vector3d(p.x, p.y, p.z));
            out.push({ "x": s.x, "y": s.y, "z": s.z });
        }
        root.mapped = out;
    }
}
"""


def as_numpy(matrix: QMatrix4x4) -> np.ndarray:
    """QMatrix4x4.data() is column-major, verified against a known translation:
    a translate(10,20,30) puts 10,20,30 at indices 12..14. Transposing gives the
    row-major form where `M @ [x, y, z, 1]` is the transform."""
    return np.array(matrix.data(), dtype=np.float64).reshape(4, 4).T


def build_view_projection(
    world: QMatrix4x4, fov_deg: float, aspect: float, near: float, far: float
) -> np.ndarray:
    """The matrix CDMW would build once per gesture and reuse for every vertex."""
    view_matrix, invertible = world.inverted()
    if not invertible:
        raise ValueError("camera sceneTransform is not invertible")
    projection = QMatrix4x4()
    projection.perspective(fov_deg, aspect, near, far)
    return as_numpy(projection) @ as_numpy(view_matrix)


def project_bulk(
    view_projection: np.ndarray,
    points: np.ndarray,
    width: float,
    height: float,
) -> np.ndarray:
    """Project every point at once, the way a brush or lasso actually needs to."""
    homogeneous = np.column_stack([points, np.ones(len(points))])
    clip = homogeneous @ view_projection.T
    w = clip[:, 3]
    if np.any(np.abs(w) < 1e-12):
        raise ValueError("degenerate w for a test point")
    ndc = clip[:, :3] / w[:, None]
    screen = np.empty((len(points), 2), dtype=np.float64)
    screen[:, 0] = (ndc[:, 0] * 0.5 + 0.5) * width
    screen[:, 1] = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * height
    return screen


def main() -> int:
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    app = QGuiApplication(sys.argv)

    qml_path = Path(__file__).with_name("_picking.qml")
    qml_path.write_text(
        QML % {
            "px": CAM_POS[0], "py": CAM_POS[1], "pz": CAM_POS[2],
            "rx": CAM_EULER[0], "ry": CAM_EULER[1], "rz": CAM_EULER[2],
            "fov": FOV, "near": CLIP_NEAR, "far": CLIP_FAR,
        },
        encoding="utf-8",
    )

    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(WIDTH, HEIGHT)
    view.setSource(QUrl.fromLocalFile(str(qml_path)))
    if view.status() == QQuickView.Status.Error:
        for err in view.errors():
            print("QML ERROR:", err.toString())
        return 2
    view.show()

    root = view.rootObject()
    root.setProperty(
        "testPoints",
        [{"x": p[0], "y": p[1], "z": p[2]} for p in TEST_POINTS],
    )

    result: dict = {}
    state = {"done": False}

    def run_comparison() -> None:
        if state["done"]:
            return
        state["done"] = True
        try:
            _compare()
        except Exception:
            import traceback
            result.update(verdict="FAIL", reason=traceback.format_exc())
        app.quit()

    def _compare() -> None:
        QMetaObject.invokeMethod(root, "collect", Qt.ConnectionType.DirectConnection)

        world = root.property("camXform")
        if not isinstance(world, QMatrix4x4):
            result.update(
                verdict="FAIL",
                reason=f"camera sceneTransform unreadable from Python "
                       f"(got {type(world).__name__})",
            )
            return

        # QML `var` arrays arrive as QJSValue, not a Python list.
        mapped = root.property("mapped")
        if hasattr(mapped, "toVariant"):
            mapped = mapped.toVariant()
        mapped = mapped or []
        vw = float(root.property("viewW") or WIDTH)
        vh = float(root.property("viewH") or HEIGHT)
        fov = float(root.property("camFov"))
        near = float(root.property("camNear"))
        far = float(root.property("camFar"))
        orientation = int(root.property("camFovOrientation"))
        aspect = vw / vh

        # fieldOfViewOrientation 0 == Vertical. Horizontal needs converting to
        # the vertical FOV that QMatrix4x4.perspective expects.
        import math
        effective_fov = fov
        if orientation == 1:
            effective_fov = math.degrees(
                2.0 * math.atan(math.tan(math.radians(fov) / 2.0) / aspect)
            )

        view_projection = build_view_projection(
            world, effective_fov, aspect, near, far
        )
        mine_all = project_bulk(
            view_projection, np.asarray(TEST_POINTS, dtype=np.float64), vw, vh
        )

        rows = []
        worst = 0.0
        for point, qt_value, mine in zip(TEST_POINTS, mapped, mine_all):
            qt_x = float(qt_value["x"])
            qt_y = float(qt_value["y"])
            err = math.hypot(mine[0] - qt_x, mine[1] - qt_y)
            worst = max(worst, err)
            rows.append({
                "point": point,
                "qt": [round(qt_x, 3), round(qt_y, 3)],
                "reconstructed": [round(float(mine[0]), 3), round(float(mine[1]), 3)],
                "error_px": round(err, 4),
            })

        verdict = "PASS" if worst < 0.5 else "MARGINAL" if worst < 2.0 else "FAIL"
        result.update(
            verdict=verdict,
            max_error_px=round(worst, 4),
            viewport=[vw, vh],
            fov=fov,
            fov_orientation="vertical" if orientation == 0 else "horizontal",
            points_tested=len(rows),
            rows=rows,
        )

    # One frame must be presented before sceneTransform and the view size are
    # meaningful, so the comparison hangs off frameSwapped rather than a timer.
    # A guard flag makes it single-shot; a hard timer means a scene that never
    # presents reports a failure instead of hanging with a window open.
    view.frameSwapped.connect(run_comparison)
    QTimer.singleShot(15000, run_comparison)

    app.exec()

    if not result:
        print(json.dumps({"verdict": "FAIL", "reason": "no frame was presented"}, indent=2))
        return 1

    for row in result.get("rows", []):
        print(
            f"  {str(row['point']):>24}  qt={row['qt']!s:>22}  "
            f"mine={row['reconstructed']!s:>22}  err={row['error_px']:.4f} px"
        )
    summary = {k: v for k, v in result.items() if k != "rows"}
    print(json.dumps(summary, indent=2))
    return 0 if result["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
