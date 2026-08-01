"""Load the Qt Quick RHI plugin, render, and exit. Prints one summary line.

Run out of process by tests/test_qt_rhi_plugin_contract.py, because the thing
under test includes whether the process can exit at all: a hang inside pytest
would take the whole suite with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

QML = """
import QtQuick
import QtQuick.Window
import CdmwQtRhi 1.0

Window {
    id: win
    width: 480; height: 320
    visible: true
    color: "#141821"
    property int frames: 0
    RhiTriangle { id: viewport; anchors.fill: parent }
    // QML over the 3D content: the thing an embedded child window cannot do.
    Rectangle {
        anchors.centerIn: parent
        width: 180; height: 48; radius: 8
        color: "#aa1b2433"; border.color: "#3d84f7"
        Text { anchors.centerIn: parent; text: "overlay"; color: "white" }
    }
    Timer {
        interval: 250; running: true; repeat: true
        onTriggered: win.frames = viewport.frameCount()
    }
}
"""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: qt_rhi_plugin_probe.py <qml-import-dir>")
        return 2
    import_dir = Path(argv[1])

    app = QGuiApplication([argv[0]])
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(import_dir))

    problems: list[str] = []
    engine.warnings.connect(
        lambda errors: problems.extend(str(e.toString()) for e in errors)
    )

    engine.loadData(QML.encode(), QUrl("qrc:/probe.qml"))
    roots = engine.rootObjects()
    if not roots:
        print("frames=0 loaded=no")
        for problem in problems:
            print("  " + problem)
        return 3
    window = roots[0]

    def finish() -> None:
        # The platform is reported because the offscreen plugin has no real
        # surface and renders nothing; a frame count is only meaningful when a
        # real one is in use.
        platform = QGuiApplication.platformName()
        print(f"frames={int(window.property('frames') or 0)} loaded=yes platform={platform}")
        window.close()
        engine.clearComponentCache()
        engine.deleteLater()
        QTimer.singleShot(150, app.quit)

    QTimer.singleShot(1500, finish)
    QTimer.singleShot(30000, app.quit)  # never hang the gate
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
