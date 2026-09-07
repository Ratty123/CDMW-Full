"""Placement Studio as an embeddable tool tab.

Graduation wrapper. Two jobs the standalone script does not need:

**Baseline bootstrapping.** The studio reads a pinned vanilla baseline extracted from the game
archives. Inside the app that has to happen on demand, from the configured
`archive_package_root`, on a worker thread — never on the UI thread, because it walks 33 archive
tables and writes ~508 files.

**Staying harmless when it cannot work.** No game path, no archives, a failed extraction: the tab
shows why and stays inert. It never raises into the shell, exactly as a missing native helper is
treated elsewhere in the app.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .background import LatestTask


class BaselineWorker(QObject):
    """Extracts the pinned vanilla baseline off the UI thread."""

    progress = Signal(str)
    done = Signal(object, str)  # (Baseline or None, error message)

    def __init__(self, game_root: str, *, cancelled=lambda: False) -> None:
        super().__init__()
        self._game_root = str(game_root or "")
        self._cancelled = cancelled

    def run(self) -> None:
        try:
            def report(message):
                if self._cancelled():
                    raise InterruptedError("Placement preparation cancelled")
                self.progress.emit(message)

            # The extractor reads its roots from the environment, which is also how the CLI
            # overrides them; setting it here keeps one mechanism rather than two.
            if self._game_root:
                os.environ["CDMW_PS_GAME_ROOT"] = self._game_root

            from tools.placement_studio.cli_support import discover_body_meshes
            from tools.placement_studio.corpus import (
                discover_golden_mods,
                extract_baseline,
                golden_game_paths,
            )
            from tools.placement_studio.meshes import weapon_mesh_path
            from tools.placement_studio.resolver import model_of, weapon_id_of
            from tools.placement_studio.session import skeleton_paths_for

            report("Collecting the paths the studio needs...")
            try:
                paths = set(golden_game_paths(discover_golden_mods()))
            except FileNotFoundError:
                # No golden corpus on this machine: that is only needed by the gates, so fall
                # back to the vanilla placement files the studio itself reads.
                paths = set(_DEFAULT_STUDIO_PATHS)

            paths |= set(skeleton_paths_for(paths))
            models = sorted({model_of(p) for p in paths if p.endswith(".sockets.xml")})
            for path in list(paths):
                if path.endswith(".sockets.xml") and "/weapon/" in path:
                    model = model_of(path)
                    if model:
                        paths.add(weapon_mesh_path(weapon_id_of(path), model))
            if self._cancelled():
                return
            paths |= set(discover_body_meshes(models))

            report(f"Extracting {len(paths):,} file(s) from the archives...")
            baseline = extract_baseline(sorted(paths), on_log=report)
            if not len(baseline):
                self.done.emit(None, "The archives yielded no placement files.")
                return
            self.done.emit(baseline, "")
        except Exception as exc:  # noqa: BLE001 - never raise into the shell
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


# Minimum set the studio needs when no golden corpus is present.
_DEFAULT_STUDIO_PATHS = (
    "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml",
    "character/descriptors/socketbonedata/1_pc/2_phw/phw_01.pab.sockets.xml",
    "character/descriptors/socketbonedata/1_pc/2_phw/phw_damian_01.pab.sockets.xml",
    "character/descriptors/characterdescription/phm_description_player_kliff.xml",
    "character/descriptors/characterdescription/phw_description_player_001.xml",
    "actionchart/bin__/upperaction/1_pc/1_phm/basic_upper_weaponin.paac",
    "actionchart/bin__/upperaction/1_pc/1_phm/ride_upper.paac",
    "actionchart/bin__/upperaction/1_pc/1_phm/ride_weapon_upper.paac",
    "actionchart/bin__/upperaction/1_pc/1_phm/ride_weapon_twohandsword_upper.paac",
    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0001_r.sockets.xml",
    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0001.sockets.xml",
)


def _prepare_startup(root, cancelled, progress):
    """Even cached baselines and first imports must not stall the shell's event loop."""
    from .corpus import Baseline, baseline_root

    if root:
        os.environ["CDMW_PS_GAME_ROOT"] = root
    try:
        baseline = Baseline.load()
    except FileNotFoundError:
        baseline = None
    if cancelled():
        return None
    if baseline is None or not len(baseline):
        if not root:
            raise ValueError(
                "Placement Studio could not read the archive package root.\n\n"
                "Set it under Settings -> Archive Locations -> Game / Package, then reopen "
                f"this tab.\n\nBaseline looked for at:\n{baseline_root()}"
            )
        if not Path(root).is_dir():
            raise ValueError(
                "The configured archive package root does not exist:\n\n"
                f"{root}\n\n"
                "Fix it under Settings -> Archive Locations, then reopen this tab."
            )
        worker = BaselineWorker(root, cancelled=cancelled)
        result = []
        worker.done.connect(lambda value, error: result.append((value, error)), Qt.DirectConnection)
        worker.run()
        if cancelled():
            return None
        baseline, error = result[0]
        if baseline is None:
            raise ValueError(error)
    if cancelled():
        return None
    # The shell preloads the Qt window module on the GUI thread. Standalone
    # embedding imports it in _install, also on the GUI thread.
    return None if cancelled() else baseline


class PlacementStudioTab(QWidget):
    """Hosts the studio, extracting its baseline on first open if needed."""

    def __init__(
        self, parent: Optional[QWidget] = None, *, settings=None, window=None
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._window = window
        self._thread: Optional[QThread] = None
        self._worker: Optional[BaselineWorker] = None
        self._studio: Optional[QWidget] = None
        self._closing = False
        self._startup_task = LatestTask(self)
        self._startup_task.setObjectName('baseline_preparation')
        self._startup_task.ready.connect(self._finished)

        self._status = QLabel("Placement Studio")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate: the sweep length is not known up front
        self._progress.setVisible(False)

        self._action = QPushButton("Prepare Placement Studio")
        self._action.clicked.connect(self._start)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._action)
        buttons.addStretch(1)

        # The bootstrap panel lives in its own container so installing the studio can *remove*
        # it. Merely hiding the widgets leaves their stretch items holding a band of empty
        # space under the tab bar.
        self._bootstrap_panel = QWidget()
        panel_layout = QVBoxLayout(self._bootstrap_panel)
        panel_layout.setContentsMargins(24, 24, 24, 24)
        panel_layout.addStretch(1)
        panel_layout.addWidget(self._status)
        panel_layout.addWidget(self._progress)
        panel_layout.addLayout(buttons)
        panel_layout.addStretch(1)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._bootstrap_panel, 1)

        QTimer.singleShot(0, self._bootstrap)

    # ── bootstrap ───────────────────────────────────────────────────

    def _game_root(self) -> str:
        """The archive root the user has configured, read the way the app itself reads it.

        The live edit belongs to MainWindow.archive. QSettings persists the same
        value under archive/package_root; older embedding inputs remain accepted.
        """

        archive = getattr(self._window, "archive", self._window)
        edit = getattr(archive, "archive_package_root_edit", None)
        if edit is not None:
            try:
                text = str(edit.text() or "").strip()
            except Exception:  # noqa: BLE001 - a widget torn down mid-teardown
                text = ""
            if text:
                return text

        settings = self._settings
        if settings is not None:
            getter = getattr(settings, "value", None)
            if callable(getter):  # QSettings
                for key in ("archive/package_root", "archive_package_root", "paths/archive_package_root"):
                    text = str(getter(key, "") or "").strip()
                    if text:
                        return text
            text = str(getattr(settings, "archive_package_root", "") or "").strip()
            if text:
                return text
        return ""

    def _bootstrap(self) -> None:
        """Let the shell paint before starting cached or first-use preparation."""
        self._start()

    def _start(self) -> None:
        if self._closing or self._startup_task.busy:
            return
        self._action.setEnabled(False)
        self._progress.setVisible(True)
        self._status.setText("Loading...")
        root = self._game_root()  # Read settings/widgets only on the UI thread.
        self._startup_task.submit(lambda cancelled, progress: _prepare_startup(root, cancelled, progress))

    def _finished(self, baseline, error: str) -> None:
        if self._closing:
            return
        self._progress.setVisible(False)
        self._worker = None

        if baseline is None:
            self._status.setText(
                f"Placement Studio could not prepare its baseline.\n\n{error}\n\n"
                "The rest of the app is unaffected."
            )
            self._action.setText("Try again")
            self._action.setEnabled(True)
            return
        self._install(baseline)

    def _install(self, baseline) -> None:
        """Swap the bootstrap panel for the studio itself."""

        from tools.placement_studio.window import PlacementStudioWindow

        self._layout.removeWidget(self._bootstrap_panel)
        self._bootstrap_panel.setParent(None)
        self._bootstrap_panel.deleteLater()

        # The studio is a QMainWindow; embedded as a child it keeps its own status bar and
        # layout without the tab having to re-implement either.
        self._studio = PlacementStudioWindow(baseline, parent=self, background_loading=True)
        self._studio.setWindowFlags(Qt.Widget)
        self._layout.addWidget(self._studio, 1)
        self._studio.show()

    # ── lifecycle ───────────────────────────────────────────────────

    def iter_shutdown_workers(self):
        """Every thread the shell's close sweep has to know about.

        The shell finds threads through `findChildren`, so it did wait for these -- but
        it could not name them, could not ask them to stop, and its force-stop pass
        never reached them. Closing during a baseline extraction, a carry measurement
        or an armour index therefore hid the window and left the process alive until
        the sweep ended on its own.
        """

        tracked = [("baseline", self._thread, self._worker)]
        studio = self._studio
        if studio is not None:
            for name in ("_armour_thread", "_swap_thread", "_carry_thread"):
                thread = getattr(studio, name, None)
                if thread is not None:
                    tracked.append((name.lstrip("_"), thread, None))
        for owner in (self, studio):
            if owner is None or not hasattr(owner, 'findChildren'):
                continue
            for number, task in enumerate(owner.findChildren(LatestTask)):
                if task._thread is not None and all(task._thread is not row[1] for row in tracked):
                    tracked.append((task.objectName() or f'preparation_{number}', task._thread, task))
        return tuple((name, thread, worker) for name, thread, worker in tracked if thread is not None)

    def request_shutdown(self) -> None:
        """Ask every thread to finish, without waiting for any of them.

        LatestTask retains native threads until teardown; neither close path waits here.
        """

        self._closing = True
        for owner in (self, self._studio):
            if owner is not None and hasattr(owner, 'findChildren'):
                for task in owner.findChildren(LatestTask):
                    task.shutdown()
        studio = self._studio
        if studio is not None and hasattr(studio, 'close'):
            studio.close()
        for _name, thread, _worker in self.iter_shutdown_workers():
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                continue

    def shutdown(self) -> None:
        """Stop the worker so closing the app never waits on an archive sweep."""

        self.request_shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        self.shutdown()
        super().closeEvent(event)
