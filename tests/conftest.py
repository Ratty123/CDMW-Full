from __future__ import annotations

import cdmw  # noqa: F401  (first: bounds OpenBLAS's threads before any test imports numpy)
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def retained_mod_folder_tools(monkeypatch):
    """Exercise Mod Management's hidden mod folder tools (convert, combine, update, health)."""
    monkeypatch.setattr("cdmw.constants.MOD_FOLDER_TOOLS_ENABLED", True)


@pytest.fixture(autouse=True)
def _no_protected_game_folder():
    """A test that configures a game folder protects it only for itself (decision 46).

    In the app a protected root stays for the whole session; a test is a session.
    """
    from cdmw.core import protected_roots

    protected_roots._reset_for_tests()
    yield
    protected_roots._reset_for_tests()


@pytest.fixture(autouse=True)
def _isolate_mod_export_history(tmp_path, monkeypatch):
    """Exports must never write authoring records into the user's real history."""
    monkeypatch.setattr("cdmw.core.mod_export_history._history_root", lambda: tmp_path / "mod-history")
    # The folder earlier versions filed into is read too; never the user's real one.
    monkeypatch.setattr("cdmw.core.mod_export_history._legacy_history_root",
                        lambda: tmp_path / "mod-history-earlier")


@pytest.fixture(autouse=True)
def _isolate_shared_preview_settings(tmp_path, monkeypatch):
    """Give each test its own shared Preview settings store.

    The real store writes the app's settings file next to the project; a test
    must never change it or depend on what is in it.
    """
    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from cdmw.ui.preview import preview_settings_hub as hub_module
    except ImportError:
        yield
        return
    path = tmp_path / "shared-preview-settings.ini"
    monkeypatch.setattr(hub_module, "_open_settings",
                        lambda: QSettings(str(path), QSettings.Format.IniFormat))
    application = QApplication.instance()
    previous = getattr(application, "_cdmw_preview_settings_hub", None) if application is not None else None
    if application is not None:
        application._cdmw_preview_settings_hub = None
    try:
        yield
    finally:
        application = QApplication.instance()
        if application is not None:
            application._cdmw_preview_settings_hub = previous


@pytest.fixture(autouse=True)
def _isolate_engine_router():
    """Each test starts with no preview process registered as Browse's engine (P4 V5)."""
    from cdmw.services import engine_capture

    # One router object for the run: dropping a parentless QObject lets the
    # collector destroy it in the middle of another test's Qt work.
    router = engine_capture._router
    if router is not None:
        router.forget_all()
    yield
    router = engine_capture._router
    if router is not None:
        router.forget_all()


@pytest.fixture(autouse=True)
def _isolate_verified_preview_files():
    """Each test starts with no remembered preview file digests."""
    from cdmw.services.mesh_rust_preview_files import forget_verified_preview_files

    forget_verified_preview_files()
    yield
    forget_verified_preview_files()


@pytest.fixture(autouse=True)
def _restore_process_environment():
    """Undo environment changes a test leaves behind, whoever made them.

    The application sets process-wide flags during startup and clears them when
    startup finishes -- `CDMW_DEFER_TEXTURE_PREVIEW` in `startup_controller` and
    `startup_restore`, for instance. A test that builds the startup surface but
    never completes startup leaves the flag set, and because it is read with a
    bare `os.environ.get`, every later test in the session inherits it. That one
    flag made `ensure_directxtex_dds_preview_pngs` return an empty result before
    doing any work, which failed ten texture-backend tests and the decode-cache
    concurrency test with symptoms that pointed nowhere near startup.

    `monkeypatch.setenv` does not help here: the leak comes from application code
    reached during the test, not from the test's own setup.
    """

    snapshot = dict(os.environ)
    yield
    if os.environ != snapshot:
        os.environ.clear()
        os.environ.update(snapshot)


_CACHE_ENV = "CDMW_TEMP_CACHE_ROOT"
_original_cache_root: str | None = None
_pytest_cache_root: Path | None = None


def _canonicalize_temp_root() -> None:
    """Make `tempfile` hand out the long form of the temp directory.

    On the GitHub runner `%TEMP%` is the 8.3 short form
    (`C:\\Users\\RUNNER~1\\AppData\\Local\\Temp`), so a test that builds an
    expected path from `tempfile` and compares it against one the application
    produced fails on the name rather than on the behaviour: the app resolves,
    and `C:\\Users\\RUNNER~1\\...` != `C:\\Users\\runneradmin\\...` even though
    both name the same directory. Nineteen tests across thirteen files failed
    that way and none of them was about short names.

    Both forms address the same directory, so resolving here changes what the
    comparison sees and nothing about where files go.
    """

    try:
        resolved = str(Path(tempfile.gettempdir()).resolve())
    except OSError:
        return
    tempfile.tempdir = resolved
    for variable in ("TMP", "TEMP", "TMPDIR"):
        if os.environ.get(variable):
            os.environ[variable] = resolved


_PROFILE_ENV = "CDMW_PROFILE_DIR"
_pytest_profile_root: Path | None = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Free the finished test's cycles on the main thread, between Qt calls as the app does."""

    yield
    from tests.gui_thread_gc import collect_after_test

    collect_after_test()


def pytest_configure() -> None:
    global _original_cache_root, _pytest_cache_root, _pytest_profile_root
    # As in the app: no automatic cyclic collection, which would start inside
    # whatever allocates next (a Qt re-polish, a worker thread). See
    # tests/gui_thread_gc.py.
    from tests.gui_thread_gc import install

    install()
    _canonicalize_temp_root()
    _original_cache_root = os.environ.get(_CACHE_ENV)
    _pytest_cache_root = Path(tempfile.mkdtemp(prefix="cdmw-pytest-cache-"))
    os.environ[_CACHE_ENV] = str(_pytest_cache_root)
    # The whole run is a private CDMW profile: settings, workspace and the
    # values that used to live in the registry resolve inside it, so no test
    # writes the project's settings file or reads the user's registry key.
    if not os.environ.get(_PROFILE_ENV):
        _pytest_profile_root = Path(tempfile.mkdtemp(prefix="cdmw-pytest-profile-"))
        os.environ[_PROFILE_ENV] = str(_pytest_profile_root)


def pytest_unconfigure() -> None:
    # Pytest can retain test instances and Qt wrappers until interpreter teardown.
    # Destroy the application explicitly while Python callbacks are still usable;
    # otherwise qoffscreen can crash after the successful terminal summary.
    qt_widgets = sys.modules.get("PySide6.QtWidgets")
    if qt_widgets is not None:
        app = qt_widgets.QApplication.instance()
        if app is not None:
            from PySide6.QtCore import QCoreApplication, QEvent

            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.shutdown()
    from cdmw.core.owned_temp import close_owned_temp_directory_locks

    close_owned_temp_directory_locks()
    if _original_cache_root is None:
        os.environ.pop(_CACHE_ENV, None)
    else:
        os.environ[_CACHE_ENV] = _original_cache_root
    if _pytest_cache_root is not None:
        shutil.rmtree(_pytest_cache_root, ignore_errors=True)
    if _pytest_profile_root is not None:
        os.environ.pop(_PROFILE_ENV, None)
        shutil.rmtree(_pytest_profile_root, ignore_errors=True)


_CHECKOUT_WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"
_workspace_files_at_start: frozenset[str] | None = None


def _checkout_workspace_files() -> frozenset[str]:
    """Every file under the checkout's own workspace folder, relative to it."""

    if not _CHECKOUT_WORKSPACE.is_dir():
        return frozenset()
    found = set()
    for folder, _dirs, files in os.walk(_CHECKOUT_WORKSPACE):
        for name in files:
            found.add(os.path.relpath(os.path.join(folder, name), _CHECKOUT_WORKSPACE))
    return frozenset(found)


_user_state_at_start: dict[str, frozenset] | None = None


def _user_folders() -> tuple[Path, ...]:
    """The folders outside the CDMW folder that CDMW wrote into in earlier versions."""

    from cdmw.constants import APP_NAME

    folders = []
    for variable, name in (("LOCALAPPDATA", APP_NAME), ("APPDATA", "CDMW")):
        base = os.environ.get(variable, "").strip()
        if base:
            folders.append(Path(base) / name)
    return tuple(folders)


def _user_registry_keys() -> tuple[str, ...]:
    from cdmw.constants import APP_ORGANIZATION

    return ("Software\\CDMWTests", "Software\\CDMWHarness", f"Software\\{APP_ORGANIZATION}")


def _folder_state(folder: Path) -> frozenset:
    """(path, size, modified) of every file under ``folder``: a new or changed file shows."""

    if not folder.is_dir():
        return frozenset()
    state = set()
    for current, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(current, name)
            try:
                info = os.stat(path)
            except OSError:
                continue
            state.add((os.path.relpath(path, folder), info.st_size, info.st_mtime_ns))
    return frozenset(state)


def _registry_state(key_path: str) -> frozenset:
    """Every value under a HKEY_CURRENT_USER key, read only (Windows; empty elsewhere)."""

    try:
        import winreg
    except ImportError:
        return frozenset()
    state = set()

    def walk(path: str) -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        except OSError:
            return
        with key:
            state.add((path, "", ""))
            index = 0
            while True:
                try:
                    name, value, kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                state.add((path, name, f"{kind}:{value!r}"))
                index += 1
            index = 0
            while True:
                try:
                    child = winreg.EnumKey(key, index)
                except OSError:
                    break
                walk(f"{path}\\{child}")
                index += 1

    walk(key_path)
    return frozenset(state)


def _user_state() -> dict[str, frozenset]:
    state = {str(folder): _folder_state(folder) for folder in _user_folders()}
    state.update({f"HKEY_CURRENT_USER\\{key}": _registry_state(key) for key in _user_registry_keys()})
    return state


def pytest_sessionstart(session):
    global _workspace_files_at_start, _user_state_at_start
    _workspace_files_at_start = _checkout_workspace_files()
    _user_state_at_start = _user_state()


def pytest_sessionfinish(session, exitstatus):
    """Remove the native delta payloads tests allocated in the shared temp folder.

    Each one is tiny, but a run leaves thousands, and every later app launch's
    stale sweep has to walk them.
    """
    module = sys.modules.get("cdmw.modding.mesh_native_core_temp_paths")
    if module is not None:
        module.cleanup_native_preview_delta_paths()
    # Tests write inside the run's private profile, never the checkout's own
    # workspace: in the main checkout that is the user's real workspace.
    written: list[str] = []
    if _workspace_files_at_start is not None:
        added = sorted(_checkout_workspace_files() - _workspace_files_at_start)
        written += [os.path.join(str(_CHECKOUT_WORKSPACE), path) for path in added]
    if _user_state_at_start is not None:
        # The user's AppData folders and registry keys: a new or changed entry is a
        # test writing outside the run's profile (the app writes only in its folder).
        now = _user_state()
        for place, before in _user_state_at_start.items():
            changed = sorted({entry[:2] for entry in now.get(place, frozenset()) - before})
            registry = place.startswith("HKEY_")
            written += [f"{place}{os.sep}{entry[0]}" if not registry
                        else entry[0] + (f" [{entry[1]}]" if entry[1] else "")
                        for entry in changed]
    if written:
        shown = "\n".join(f"  {path}" for path in written[:20])
        more = f"\n  ... and {len(written) - 20} more" if len(written) > 20 else ""
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        message = ("This test run wrote outside its profile (the checkout's workspace, "
                   "AppData or the registry); tests must write under the run's profile "
                   f"or tmp_path:\n{shown}{more}")
        if reporter is not None:
            reporter.write_sep("=", "files written outside the run's profile", red=True)
            reporter.write_line(message)
        else:
            print(message, file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
