"""Automation commands for the loading and responsiveness review (test runs only).

Each path the review measures gets an action that does what a click does and a read
that reports what the window shows: progress, a Cancel button, busy flags, counts.
An action starts the work and returns; the driver polls the read, so no command
waits on the UI thread (the bridge gives up after 60 s, and a wait there would be
the stall the review measures).

Paths: a start after a game update (``fake_game_update``, ``cache_state``), scrolling
Browse's list (``scroll_start``, ``scroll_state``), Item Finder and Body & Face Finder
(``finder_*``, ``scene_action``), cancelling Build Mod and a scan (``job_state``,
``job_cancel``, ``scan_start``), closing during a job (``close_during_job``), and
Create New Item, Model Library and Textures (``new_item_*``, ``model_library_state``,
``textures_*``).

Writes stay inside the run's private profile (``cdmw_folder()``), never in a game folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

# ----- helpers ---------------------------------------------------------------------


def _alive(widget) -> bool:
    try:
        return widget is not None and bool(widget.isVisible())
    except RuntimeError:
        return False


def _text(widget) -> str:
    try:
        return str(widget.text()) if widget is not None else ""
    except RuntimeError:
        return ""


def _button(widget) -> dict[str, object]:
    try:
        return {"text": _text(widget), "visible": _alive(widget), "enabled": bool(widget.isEnabled())}
    except (AttributeError, RuntimeError):
        return {"text": "", "visible": False, "enabled": False}


def inside_profile(path: Path | str) -> Path:
    """``path`` resolved, if it lies inside the run's profile and in no protected game folder."""

    from cdmw.app.app_folder import cdmw_folder

    target = Path(path).expanduser().resolve()
    if not target.is_relative_to(cdmw_folder()):
        raise ValueError(f"{target} is outside the run's own profile folder.")
    try:
        from cdmw.core.protected_roots import protected_roots

        if any(target == root or target.is_relative_to(root) for root in protected_roots()):
            raise ValueError(f"{target} is inside a game folder.")
    except ImportError:
        pass
    return target


def _created(holder):
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    return created_tool_widget(holder)


# ----- 1. A start after a game update ---------------------------------------------------
# CDMW decides the archive catalogue is current in two places, and a game update trips both:
# the archive worker compares a fingerprint of every .pamt/.pathc (contents) and .paz (size and
# time) with the one in its cache's current.json; and before that the window hashes
# CrimsonDesert.exe when its size or time differ from the record in the cfg. The fakes below
# change the profile's copies of those records only.

FINGERPRINT_KEY = "fingerprint"
EXECUTABLE_SETTING = "archive/game_executable_fingerprints"


def stale_fingerprint(value: str) -> str:
    """Another well-formed fingerprint (64 lowercase hex), so the worker takes its mismatch path."""

    return hashlib.sha256(("review-stale:" + str(value or "")).encode("utf-8")).hexdigest()


def stale_pointer(data: dict) -> tuple[dict, str, str]:
    """current.json with its fingerprint changed: (new data, old, new)."""

    if not isinstance(data, dict) or not isinstance(data.get(FINGERPRINT_KEY), str):
        raise ValueError("current.json has no fingerprint field.")
    old = data[FINGERPRINT_KEY]
    return {**data, FINGERPRINT_KEY: stale_fingerprint(old)}, old, stale_fingerprint(old)


def stale_executable_record(record: dict) -> dict:
    """The recorded CrimsonDesert.exe as an older build would have left it: another hash, and a
    time one tick off, so the check hashes the file again instead of trusting the stamp."""

    if not str(record.get("sha256", "") or "").strip():
        raise ValueError("No CrimsonDesert.exe hash is recorded yet (start once with the game connected).")
    changed = dict(record)
    changed["sha256"] = stale_fingerprint(record["sha256"])
    changed["mtime_ns"] = int(record.get("mtime_ns", 0) or 0) - 1
    return changed


def _session(window):
    bridge = getattr(window.archive, "archive_remote_bridge", None)
    return getattr(bridge, "current_session", None)


def catalogue_pointer_path(window) -> Path | None:
    """The cache's current.json for the open catalogue: <family>/<root id>/current.json, two
    levels above the generation folder that holds the session's archive.ali."""

    session = _session(window)
    index_path = str(getattr(session, "index_path", "") or "")
    if not index_path:
        return None
    return Path(index_path).parents[2] / "current.json"


def _read_json(path: Path | None) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path is not None else None
    except (OSError, ValueError):
        return None


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(f".{path.name}.review-{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def _executable_records(window) -> dict:
    return dict(window.shell._load_game_executable_fingerprints() or {})


def fake_game_update(window, args: dict) -> dict[str, object]:
    """Make the profile's archive cache look as a game update leaves it, then (``rescan``,
    the default) scan as the Scan button does. ``kind``: ``catalogue`` (the archive
    fingerprint in current.json, the default) or ``executable`` (the recorded
    CrimsonDesert.exe). One at a time: an executable change forces a refresh, which skips
    the fingerprint check the other one tests."""

    kind = str(args.get("kind", "catalogue"))
    changed: dict[str, object] = {"kind": kind}
    if kind == "catalogue":
        pointer = catalogue_pointer_path(window)
        if pointer is None or not pointer.is_file():
            raise RuntimeError("No archive catalogue is open, so there is no current.json to change.")
        pointer = inside_profile(pointer)
        data = _read_json(pointer)
        updated, old, new = stale_pointer(data or {})
        _write_json_atomic(pointer, updated)
        changed.update(path=str(pointer), old=old, new=new, generation_id=str(updated.get("generation_id", "")))
    elif kind == "executable":
        inside_profile(Path(window.shell.settings.fileName()))
        records = _executable_records(window)
        if not records:
            raise RuntimeError("No CrimsonDesert.exe hash is recorded yet.")
        key = next(iter(sorted(records)))
        records[key] = stale_executable_record(records[key])
        window.shell._save_game_executable_fingerprints(records)
        changed.update(executable=key, recorded_sha256=records[key]["sha256"])
    else:
        raise ValueError("kind is catalogue or executable")
    if args.get("rescan", True):
        window.archive.archive_scan_button.click()
        changed["rescan"] = True
    return changed


def _log_tail(window, limit: int = 12, pattern: str = "") -> list[str]:
    view = getattr(window.archive, "archive_log_view", None)
    try:
        lines = view.toPlainText().splitlines() if view is not None else []
    except RuntimeError:
        return []
    if pattern:
        words = [w.casefold() for w in pattern.split("|") if w]
        lines = [line for line in lines if any(w in line.casefold() for w in words)]
    return lines[-limit:]


def cache_state(window, args: dict) -> dict[str, object]:
    """What the window says about the archive catalogue and its cache right now."""

    archive = window.archive
    session = _session(window)
    pointer_path = catalogue_pointer_path(window)
    pointer = _read_json(pointer_path) if pointer_path is not None else None
    generations: list[str] = []
    if pointer_path is not None:
        try:
            generations = sorted(p.name for p in (pointer_path.parent / "g").iterdir())
        except OSError:
            generations = []
    record = next(iter(_executable_records(window).values()), {}) if args.get("executable", True) else {}
    return {
        "pending": bool(getattr(archive, "archive_remote_query_pending", False)),
        "session": None if session is None else {
            "id": str(session.session_id), "fingerprint": str(session.fingerprint),
            "cache_hit": bool(session.cache_hit), "entry_count": int(session.entry_count),
            "generation_id": Path(str(session.index_path)).parent.name if session.index_path else "",
        },
        "pointer": None if pointer is None else {
            "path": str(pointer_path), "fingerprint": str(pointer.get(FINGERPRINT_KEY, "")),
            "generation_id": str(pointer.get("generation_id", "")),
        },
        "generations": generations,
        "health": {"state": str(getattr(archive, "_archive_cache_health_state", "") or ""),
                   "reason": str(getattr(archive, "_archive_cache_health_reason", "") or "")},
        "progress": _scan_progress(archive),
        "executable_record": {"sha256": str(record.get("sha256", ""))[:16],
                              "previous_sha256": str(record.get("previous_sha256", ""))[:16],
                              "update_detected_at": record.get("update_detected_at")},
        "log": _log_tail(window, int(args.get("log_lines", 12)),
                         str(args.get("log_pattern", "game update|game build|cache|catalogue|stale"))),
    }


def _scan_progress(archive) -> dict[str, object]:
    bar = getattr(archive, "archive_scan_progress_bar", None)
    return {
        "active": bool(getattr(archive, "_archive_load_progress_active", False)),
        "percent": int(getattr(archive, "_archive_load_progress_percent", 0) or 0),
        "detail": str(getattr(archive, "_archive_load_progress_detail", "") or ""),
        "bar_visible": _alive(bar),
        "label": _text(getattr(archive, "archive_scan_progress_label", None)),
        "cancel_button": _button(getattr(archive, "archive_refresh_scan_button", None)),
    }


# ----- 2. Scrolling Browse's long list -----------------------------------------------------

_SCROLL: dict[str, object] = {}


def browse_list(window):
    """(the view that shows Browse's list, its model, "flat" or "tree"). The flat view of a
    large catalogue is a table laid over the tree (the tree then holds a placeholder model)."""

    tree = window.archive.archive_tree
    model = getattr(tree, "_remote_archive_model", None)
    flat = getattr(tree, "_flat_table", None)
    if getattr(tree, "_flat_remote_active", False) and flat is not None:
        return flat, model or flat.model(), "flat"
    return tree, model or tree.model(), "tree"


def _rows_loading(view, model) -> tuple[int, int]:
    """(rows shown, rows shown still "Loading...", which the model marks "loading")."""

    from PySide6.QtCore import Qt

    viewport = view.viewport()
    top = view.indexAt(viewport.rect().topLeft())
    if model is None or not top.isValid():
        return 0, 0
    bottom = viewport.rect().bottom()
    shown = loading = 0
    index = top
    below = getattr(view, "indexBelow", None)
    while index.isValid() and view.visualRect(index).top() <= bottom and shown < 400:
        shown += 1
        if str(model.data(index, Qt.ItemDataRole.UserRole)) == "loading":
            loading += 1
        index = below(index) if callable(below) else model.index(index.row() + 1, 0, index.parent())
    return shown, loading


def _row_pixels(view) -> int:
    top = view.indexAt(view.viewport().rect().topLeft())
    height = view.visualRect(top).height() if top.isValid() else 0
    return max(1, int(height or 20))


def scroll_start(window, args: dict) -> dict[str, object]:
    """Scroll Browse's list quickly as a dragged scroll bar does: ``steps`` moves of
    ``rows`` rows (default a page), one every ``interval_ms`` from a timer, so the event
    loop runs between them as it does between mouse moves. Read with ``scroll_state``."""

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QAbstractItemView

    view, model, mode = browse_list(window)
    bar = view.verticalScrollBar()
    previous = _SCROLL.get("timer")
    if previous is not None:
        previous.stop()
    steps = max(1, int(args.get("steps", 40)))
    per_pixel = view.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    rows = int(args.get("rows", 0) or 0)
    move = rows * _row_pixels(view) if rows and per_pixel else rows or max(1, bar.pageStep())
    direction = -1 if str(args.get("direction", "down")) == "up" else 1
    state = {"steps": steps, "done_steps": 0, "rows_per_step": rows or None, "move": move, "view": mode,
             "started": time.perf_counter(), "finished": None, "loaded": None, "tick_ms": [],
             "pages_requested": 0, "start_value": bar.value(), "maximum": bar.maximum()}
    requested = getattr(model, "pageRequested", None)
    activity = getattr(window.archive, "_note_archive_ui_activity", None)

    def count(_fetch) -> None:
        state["pages_requested"] += 1

    if requested is not None:
        requested.connect(count)
    timer = QTimer(view)
    timer.setInterval(max(1, int(args.get("interval_ms", 16))))
    settle = QTimer(view)
    settle.setInterval(20)

    def tick() -> None:
        began = time.perf_counter()
        if callable(activity):
            activity()  # what the list's own input events report while the user scrolls
        bar.setValue(bar.value() + direction * move)
        state["tick_ms"].append((time.perf_counter() - began) * 1000.0)
        state["done_steps"] += 1
        if state["done_steps"] >= steps or bar.value() in (bar.minimum(), bar.maximum()):
            timer.stop()
            state["finished"] = time.perf_counter()
            settle.start()

    def settled() -> None:
        _shown, loading = _rows_loading(view, model)
        if not loading:
            state["loaded"] = time.perf_counter()
            settle.stop()
            if requested is not None:
                try:
                    requested.disconnect(count)
                except (RuntimeError, TypeError):
                    pass
        elif time.perf_counter() - state["finished"] > 60:
            settle.stop()

    timer.timeout.connect(tick)
    settle.timeout.connect(settled)
    _SCROLL.update(timer=timer, settle=settle, state=state)
    timer.start()
    return {"steps": steps, "rows_per_step": rows or None, "move": move, "view": mode, "maximum": bar.maximum(),
            "value": bar.value()}


def scroll_state(window, _args: dict) -> dict[str, object]:
    state = dict(_SCROLL.get("state") or {})
    if not state:
        return {"started": False}
    view, model, mode = browse_list(window)
    shown, loading = _rows_loading(view, model)
    ticks = list(state.get("tick_ms") or [])
    started = state["started"]
    return {
        "started": True, "done": state["finished"] is not None, "loaded": state["loaded"] is not None,
        "done_steps": state["done_steps"], "steps": state["steps"], "view": mode,
        "scroll_s": None if state["finished"] is None else round(state["finished"] - started, 3),
        "loaded_after_scroll_s": (None if state["loaded"] is None
                                  else round(state["loaded"] - state["finished"], 3)),
        "longest_tick_ms": round(max(ticks), 1) if ticks else None,
        "pages_requested": state["pages_requested"],
        "pages_in_flight": len(getattr(model, "inflight_page_starts", ()) or ()),
        "visible_rows": shown, "visible_loading": loading,
        "value": view.verticalScrollBar().value(), "maximum": view.verticalScrollBar().maximum(),
    }


# ----- 3. Item Finder and Body & Face Finder -----------------------------------------------


def _finder(window, which: str):
    name = "_character_finder_dialogs" if which == "character" else "_remote_archive_finder_dialogs"
    for dialog in tuple(getattr(window.archive, name, None) or ()):
        try:
            if dialog.isVisible() and not getattr(dialog, "_closing", False):
                return dialog
        except RuntimeError:
            continue
    return None


def finder_open(window, args: dict) -> dict[str, object]:
    """Open Item Finder (``finder`` item, the default) or Body & Face Finder (character) with
    its button. Item Finder is modal (its exec runs a nested event loop), so the click is
    queued and this returns at once; ``finder_state`` tells when it is shown."""

    from PySide6.QtCore import QTimer

    which = str(args.get("finder", "item"))
    archive = window.archive
    button = archive.archive_character_finder_button if which == "character" else archive.archive_asset_catalog_button
    state = _button(button)
    if not state["enabled"]:
        return {"opened": False, "button": state}
    QTimer.singleShot(0, button.click)
    return {"opened": True, "button": state}


def finder_state(window, args: dict) -> dict[str, object]:
    which = str(args.get("finder", "item"))
    dialog = _finder(window, which)
    if dialog is None:
        return {"shown": False}
    if which == "character":
        grid = dialog._grid
        # The dialog keeps one look-ahead request for the next page outstanding: not busy.
        busy = any(kind != "prefetch" for kind in (getattr(dialog, "_requests", None) or {}))
        scene = getattr(getattr(dialog, "_scene_panel", None), "panel", None)
        extra = {
            "preview_status": _text(getattr(dialog, "_preview_status", None)),
            "preview_busy": _alive(getattr(dialog, "_preview_busy", None)),
            "requests": sorted(str(k) for k in (getattr(dialog, "_requests", None) or {})),
            "scene_parts": len(getattr(scene, "_parts", {}) or {}) if scene is not None else 0,
            "scene_visible": _alive(scene),
            "exact": _button(getattr(dialog, "_exact", None)),
            "related": _button(getattr(dialog, "_related", None)),
            # Body & Face Finder has no Cancel button: closing it cancels its requests.
            "cancel_button": None,
        }
    else:
        grid = dialog._item_grid
        busy = bool(getattr(dialog, "_search_request_id", None) or getattr(dialog, "_scope_request_id", None))
        extra = {
            "exact": _button(getattr(dialog, "_exact_button", None)),
            "related": _button(getattr(dialog, "_related_button", None)),
            "cancel_button": _button(getattr(dialog, "_cancel_button", None)),
            "facets_ready": bool(getattr(dialog, "_facets_ready", False)),
        }
    current = grid.currentItem()
    return {
        "shown": True, "busy": busy, "status": _text(getattr(dialog, "_status", None)),
        "search": _text(getattr(dialog, "_search_edit", None)),
        "results": int(grid.count()), "grid_enabled": bool(grid.isEnabled()),
        "selected": "" if current is None else str(current.text()).splitlines()[0],
        "first_results": [str(grid.item(i).text()).splitlines()[0] for i in range(min(grid.count(), 8))],
        **extra,
    }


def finder_search(window, args: dict) -> dict[str, object]:
    """Type ``text`` into the finder's search box (after Clear filters, unless ``clear`` is
    false), as a user does; the search runs after the box's own short delay."""

    which = str(args.get("finder", "item"))
    dialog = _finder(window, which)
    if dialog is None:
        raise RuntimeError("The finder is not shown.")
    if args.get("clear", True):
        dialog._clear_filters()
    dialog._search_edit.setText(str(args.get("text", "")))
    return {"search": dialog._search_edit.text()}


def finder_select(window, args: dict) -> dict[str, object]:
    """Select the first result whose name holds ``match`` (any case), as a click does."""

    which = str(args.get("finder", "item"))
    dialog = _finder(window, which)
    if dialog is None:
        raise RuntimeError("The finder is not shown.")
    grid = dialog._grid if which == "character" else dialog._item_grid
    wanted = str(args.get("match", "")).casefold()
    for row in range(grid.count()):
        item = grid.item(row)
        if wanted in str(item.text()).casefold():
            grid.setCurrentItem(item)
            item.setSelected(True)
            return {"selected": str(item.text()).splitlines()[0], "row": row}
    return {"selected": "", "row": -1}


def finder_scope(window, args: dict) -> dict[str, object]:
    """Click the finder's exact (``how`` exact, the default) or related button: it scopes
    Browse to the item's files and, for Item Finder, opens its worn set and closes."""

    which = str(args.get("finder", "item"))
    dialog = _finder(window, which)
    if dialog is None:
        raise RuntimeError("The finder is not shown.")
    related = str(args.get("how", "exact")) == "related"
    if which == "character":
        button = dialog._related if related else dialog._exact
    else:
        button = dialog._related_button if related else dialog._exact_button
    state = _button(button)
    if state["enabled"]:
        button.click()
    return {"clicked": bool(state["enabled"]), "button": state}


def finder_close(window, args: dict) -> bool:
    dialog = _finder(window, str(args.get("finder", "item")))
    if dialog is None:
        return False
    dialog.reject()
    return True


def _scene_panel(window, where: str):
    if where == "character":
        dialog = _finder(window, "character")
        return getattr(getattr(dialog, "_scene_panel", None), "panel", None)
    return getattr(window.archive, "archive_item_set_components", None)


def scene_action(window, args: dict) -> dict[str, object]:
    """Show all or Isolate in a Scene panel (Browse's, or Body & Face Finder's with ``where``
    character), with its buttons. Isolate first makes the named file's row (``path``, a
    file name or path; else the first file) the current row, as a click on it does."""

    from PySide6.QtCore import Qt

    panel = _scene_panel(window, str(args.get("where", "browse")))
    if panel is None:
        raise RuntimeError("No Scene panel is shown.")
    action = str(args.get("action", "show_all"))
    if action == "isolate":
        wanted = str(args.get("path", "")).replace("\\", "/").casefold()
        tree = panel.tree
        target = None
        for top in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(top)
            path = str(group.toolTip(0) or group.text(0)).replace("\\", "/").casefold()
            if not wanted or path == wanted or path.endswith("/" + wanted):
                target = group
                break
        if target is None:
            raise RuntimeError(f"No Scene panel row for {wanted or 'any file'}.")
        tree.setCurrentItem(target)
        target.setSelected(True)
        button = panel.isolate_button
    elif action == "show_all":
        button = panel.show_all_button
    else:
        raise ValueError("action is show_all or isolate")
    state = _button(button)
    if state["enabled"]:
        button.click()
    hidden = tuple(panel.hidden_indices)
    archive = window.archive
    return {"clicked": bool(state["enabled"]), "button": state, "hidden": list(hidden),
            "parts": len(getattr(panel, "_parts", {}) or {}),
            "sent_to_view": bool(getattr(archive, "_archive_item_set_visibility_active", False))
            if str(args.get("where", "browse")) == "browse" else None,
            "checked_parts": sum(1 for item in (getattr(panel, "_parts", {}) or {}).values()
                                 if item.checkState(0) == Qt.CheckState.Checked)}


# ----- 4. Cancelling Build Mod and an archive scan -------------------------------------------


def _mesh_document(window):
    view = _created(window.shell.mesh_editor_tab)
    return getattr(view, "active", None) or view


def _progress_dialog_state(progress) -> dict[str, object] | None:
    from PySide6.QtWidgets import QPushButton

    if progress is None:
        return None
    try:
        buttons = progress.findChildren(QPushButton)
        return {"visible": bool(progress.isVisible()), "value": int(progress.value()),
                "label": str(progress.labelText()), "canceled": bool(progress.wasCanceled()),
                "cancel_button": _button(buttons[0]) if buttons else None}
    except RuntimeError:
        return None


def job_state(window, args: dict) -> dict[str, object]:
    """A long job as the window shows it: ``job`` build_mod (the shown Mesh Editor
    document's Build Mod) or scan (Browse's archive catalogue)."""

    job = str(args.get("job", "build_mod"))
    if job == "scan":
        archive = window.archive
        task = getattr(archive, "archive_game_fingerprint_task", None)
        return {"job": job, "busy": bool(getattr(archive, "archive_remote_query_pending", False)),
                "checking_game_version": task is not None, **_scan_progress(archive)}
    tab = _mesh_document(window)
    if tab is None:
        return {"job": job, "busy": False, "document": False}
    busy = getattr(tab, "_mesh_direct_output_busy", None)
    thread = getattr(tab, "standalone_output_thread", None)
    return {"job": job, "document": True, "busy": bool(busy()) if callable(busy) else thread is not None,
            "thread": thread is not None, "kind": str(getattr(tab, "standalone_output_kind", "") or ""),
            "progress": _progress_dialog_state(getattr(tab, "standalone_output_progress", None)),
            "status": _text(getattr(tab, "standalone_status_label", None))}


def job_cancel(window, args: dict) -> dict[str, object]:
    """Click the job's Cancel button, if it is shown: Build Mod's progress dialog, or Browse's
    Refresh button while it reads Cancel during a catalogue update."""

    from PySide6.QtWidgets import QPushButton

    job = str(args.get("job", "build_mod"))
    if job == "scan":
        button = window.archive.archive_refresh_scan_button
        state = _button(button)
        busy = bool(getattr(window.archive, "archive_remote_query_pending", False))
        clicked = busy and state["visible"] and state["enabled"]
        if clicked:
            button.click()
        return {"clicked": clicked, "button": state, "busy_before": busy}
    tab = _mesh_document(window)
    progress = getattr(tab, "standalone_output_progress", None) if tab is not None else None
    if progress is None:
        return {"clicked": False, "reason": "no Build Mod is running"}
    buttons = progress.findChildren(QPushButton)
    state = _button(buttons[0]) if buttons else {"visible": False, "enabled": False, "text": ""}
    clicked = bool(buttons) and state["visible"] and state["enabled"]
    if clicked:
        buttons[0].click()
    return {"clicked": clicked, "button": state}


def scan_start(window, args: dict) -> dict[str, object]:
    """Start a catalogue update as a click does: Refresh (``force_refresh``, the default,
    rebuilds from the .pamt files) or Scan."""

    archive = window.archive
    button = archive.archive_refresh_scan_button if args.get("force_refresh", True) else archive.archive_scan_button
    state = _button(button)
    if bool(getattr(archive, "archive_remote_query_pending", False)):
        return {"started": False, "reason": "a catalogue update is already running", "button": state}
    if state["enabled"]:
        button.click()
    return {"started": bool(state["enabled"]), "button": state}


# ----- 5. Closing the app during a job -----------------------------------------------------


def close_during_job(window, args: dict) -> dict[str, object]:
    """Close the main window now, as its close button does, whatever is running. An open
    edit is discarded (no question). Returns what was running and the process ids the
    app owns, so the driver can check that none is left after the exit."""

    from PySide6.QtCore import QTimer

    from cdmw.core.common import _windows_descendant_pids
    from cdmw.ui.mesh_editor.live_edit import end_edit_prompt

    running = {"build_mod": job_state(window, {"job": "build_mod"}).get("busy", False),
               "scan": job_state(window, {"job": "scan"}).get("busy", False)}
    pids = [os.getpid(), *_windows_descendant_pids(os.getpid())]
    end_edit_prompt.prompt_override = lambda *_args: end_edit_prompt.DISCARD
    log = _record_close_events(window, args.get("close_log"))
    QTimer.singleShot(int(args.get("delay_ms", 0) or 0), window.close)
    return {"running": running, "pids": pids, "close_log": "" if log is None else str(log)}


def _record_close_events(window, requested: object) -> Path | None:
    """Append each close phase the window records (waiting for which workers and
    processes, force stop, finalize) to a JSON-lines file in the run's profile, so a
    close the watchdog ends can still be read after the app is gone."""

    from cdmw.app.app_folder import cdmw_folder

    recorder = getattr(window, "_record_runtime_event", None)
    if not callable(recorder) or getattr(recorder, "_review_close_log", None) is not None:
        return getattr(recorder, "_review_close_log", None)
    try:
        log = inside_profile(requested or (cdmw_folder() / "logs" / "review-close-events.jsonl"))
        log.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError):
        return None
    started = time.monotonic()

    def record(event: str, **fields: object):
        if str(event).startswith("close"):
            try:
                with log.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"s": round(time.monotonic() - started, 3), "event": str(event),
                                             **fields}, default=str) + "\n")
            except OSError:
                pass
        return recorder(event, **fields)

    record._review_close_log = log
    window._record_runtime_event = record
    shell = getattr(window, "shell", None)
    if shell is not None and shell is not window and getattr(shell, "_record_runtime_event", None) is recorder:
        shell._record_runtime_event = record
    return log


# ----- 6. Create New Item, Model Library, Textures --------------------------------------------

_PREVIEW_STATUS: dict[int, list[str]] = {}
#: id(controller) -> the viewport controller's states, oldest first (the last 24)
_PREVIEW_HOST_STATES: dict[int, list[list[object]]] = {}


def _preview_host_state(tab, preview) -> dict[str, object] | None:
    """Where the preview's viewport is and what its controller last said: whether the
    host exists and is shown, which widget holds it (the off-screen workflow or the
    Rust page's host), whether the Rust page has attached it, and the controller's
    handshake gates, package generations and recent states."""

    from PySide6.QtCore import Qt

    host = getattr(preview, "host", None)
    if host is None:
        return {"host": False, "host_error": str(getattr(preview, "_host_error", "") or "")}
    controller = getattr(host, "controller", None)
    states = _PREVIEW_HOST_STATES.get(id(controller))
    if controller is not None and states is None:
        states = _PREVIEW_HOST_STATES[id(controller)] = []

        def kept(state, message, states=states) -> None:
            states.append([round(time.monotonic(), 2), str(state), str(message)[:160]])
            del states[:-24]

        controller.state_changed.connect(kept)
    try:
        parent = host.parentWidget()
        shown = {"visible": bool(host.isVisible()), "hidden": bool(host.isHidden()),
                 "parent": type(parent).__name__ if parent is not None else "",
                 "geometry": list(host.geometry().getRect()),
                 "window_on_screen": not host.window().testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)}
    except (RuntimeError, AttributeError):
        shown = {"visible": False, "deleted": True}
    portals = getattr(tab, "_portals", None)
    attached = [entry[0] is host for entry in (getattr(portals, "_attached", {}) or {}).values()]

    def flag(name):
        return bool(getattr(controller, name, False))

    def number(name):
        try:
            return int(getattr(controller, name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    process = getattr(controller, "process", None)
    return {
        "host": True, **shown, "portal_attached": any(attached),
        "rust_page": {"ready": bool(getattr(tab, "_ready", False)),
                      "first_frame": bool(getattr(tab, "_first_frame_ready", False)),
                      "sent_generation": int(getattr(tab, "_sent_generation", 0) or 0),
                      "received_generation": int(getattr(tab, "_received_generation", 0) or 0)},
        "controller": None if controller is None else {
            "visible": flag("_visible"), "running": flag("is_running"),
            "process": type(process).__name__ if process is not None else "",
            "protocol_ready": flag("_protocol_ready"), "renderer_ready": flag("_renderer_ready"),
            "session_established": flag("_session_established"),
            "localization_established": flag("_localization_initial_established"),
            "gpu_failed": flag("_gpu_failed"), "active": flag("_active"),
            "edit_held": getattr(controller, "_edit_channel", None) is not None,
            "package_generation": number("_package_generation"),
            "pending_package_generation": number("_pending_package_generation"),
            "applied_package_generation": number("_applied_package_generation"),
            "deferred_for_interaction": number("_interaction_deferred_package_generation"),
            "activation_pending": getattr(controller, "_pending_activation", None) is not None,
            "desired_package": Path(str(getattr(controller, "desired_package_path", "") or "")).name,
            "applied_package": Path(str(getattr(controller, "applied_package_path", "") or "")).name,
            "retry_attempt": number("_retry_attempt"),
            "states": list(states or ()),
        },
        "frame": {"loaded_stage": str(getattr(preview, "_loaded_stage", "") or ""),
                  "loaded_is_pending": (getattr(preview, "_pending", None) or (None,))[0]
                  == getattr(preview, "_loaded_token", None),
                  "package": Path(str(getattr(preview, "_package_dir", "") or "")).name},
    }


def _new_item(window):
    tab = _created(window.shell.new_item_studio_tab)
    workflow = getattr(tab, "workflow", None)
    return tab, workflow


def new_item_state(window, _args: dict) -> dict[str, object]:
    tab, workflow = _new_item(window)
    if workflow is None:
        return {"created": tab is not None}
    controller = getattr(tab, "controller", None) or getattr(workflow, "controller", None)
    panel = workflow.template_panel
    preview = getattr(getattr(workflow, "model_panel", None), "preview", None)
    if preview is not None and id(preview) not in _PREVIEW_STATUS:
        texts: list[str] = []
        _PREVIEW_STATUS[id(preview)] = texts
        preview.status_changed.connect(lambda text, kept=texts: kept.append(str(text)))
    matches = panel.matches
    current = matches.currentItem()
    return {
        "created": True,
        "rust_ready": bool(getattr(tab, "_ready", False)), "first_frame": bool(getattr(tab, "_first_frame_ready", False)),
        "snapshot_ready": bool(getattr(controller, "ready", False)), "busy": bool(getattr(controller, "busy", False)),
        "search": _text(panel.filter_edit), "results": int(matches.topLevelItemCount()),
        "options": len(getattr(panel, "_match_options", ()) or ()),
        "picked": "" if current is None else str(current.text(0)),
        "preview": None if preview is None else {
            "ready": bool(getattr(preview, "is_ready", False)),
            "building": getattr(preview, "_thread", None) is not None,
            "deferred": getattr(preview, "_deferred_package", None) is not None,
            "status": (_PREVIEW_STATUS.get(id(preview)) or [""])[-1],
        },
        "preview_statuses": list((_PREVIEW_STATUS.get(id(preview)) or [])[-12:]),
        "preview_host": None if preview is None else _preview_host_state(tab, preview),
    }


def new_item_search(window, args: dict) -> dict[str, object]:
    """Type ``text`` into Create New Item's template search, as a user does."""

    tab, workflow = _new_item(window)
    if workflow is None:
        raise RuntimeError("Create New Item is not open yet.")
    workflow.template_panel.filter_edit.setText(str(args.get("text", "")))
    return {"search": workflow.template_panel.filter_edit.text()}


def new_item_pick(window, args: dict) -> dict[str, object]:
    """Click the first template whose row holds ``match`` (any case), or row ``row``."""

    _tab, workflow = _new_item(window)
    if workflow is None:
        raise RuntimeError("Create New Item is not open yet.")
    matches = workflow.template_panel.matches
    wanted = str(args.get("match", "")).casefold()
    chosen = None
    for row in range(matches.topLevelItemCount()):
        item = matches.topLevelItem(row)
        if (wanted and wanted in str(item.text(0)).casefold()) or (not wanted and row == int(args.get("row", 0))):
            chosen = item
            break
    if chosen is None:
        return {"picked": ""}
    matches.setCurrentItem(chosen)
    matches.itemClicked.emit(chosen, 0)
    return {"picked": str(chosen.text(0))}


def model_library_state(window, _args: dict) -> dict[str, object]:
    tab = _created(window.shell.model_library_tab)
    if tab is None:
        return {"created": False}
    tree = getattr(tab, "results_tree", None)
    database = getattr(tab, "catalogue_db_path", None)
    try:
        database_present = bool(callable(database) and database().is_file())
    except (OSError, RuntimeError):
        database_present = False
    return {
        "created": True,
        # Mirror Catalogue lists a downloaded copy of an online model mirror, not the
        # game archive: with no catalogue downloaded and no local folder added, an
        # empty table is what a fresh profile shows.
        "view": str(getattr(tab, "_active_results_view", "") or ""),
        "catalogue_downloaded": database_present,
        "catalogue_indexed": bool(getattr(tab, "_catalogue_index_available", False)),
        "local_folders": len(getattr(tab, "local_roots", ()) or ()),
        "busy": getattr(tab, "_task_thread", None) is not None or bool(getattr(tab, "_populating_results", False)),
        "task_running": getattr(tab, "_task_thread", None) is not None,
        "populating": bool(getattr(tab, "_populating_results", False)),
        "rows": int(tree.topLevelItemCount()) if tree is not None else 0,
        "status": _text(getattr(tab, "status_label", None)),
        "results_status": _text(getattr(tab, "results_status_label", None)),
    }


def textures_open(window, args: dict) -> dict[str, object]:
    """Open ``path`` (a DDS inside the profile) in the Textures workspace, as Add Textures does
    after its file dialog."""

    source = inside_profile(str(args["path"]))
    if not source.is_file():
        raise ValueError(f"{source} is not a file.")
    shell = window.shell
    shell._activate_tool_widget(shell.texture_editor_tab)
    shell.textures.open_texture_sources([source])
    return {"path": str(source), "bytes": source.stat().st_size}


def textures_state(window, _args: dict) -> dict[str, object]:
    textures = window.shell.textures
    editor = _created(getattr(textures, "editor_container", None))
    document = getattr(editor, "document", None)
    width = getattr(document, "width", None)
    height = getattr(document, "height", None)
    busy = getattr(editor, "_busy", None)
    return {
        "editor": editor is not None,
        "busy": bool(busy()) if callable(busy) else False,
        "task_running": getattr(editor, "_task_thread", None) is not None,
        "pending": len(getattr(textures, "_pending_texture_sources", ()) or ()),
        "sessions": len(getattr(editor, "_sessions", ()) or ()),
        "document": None if document is None else {"width": width, "height": height,
                                                   "title": str(getattr(document, "title", "") or ""),
                                                   "source": str(getattr(getattr(document, "source_binding", None),
                                                                         "source_path", "") or "")},
        "status": _text(getattr(editor, "status_label", None)),
    }


COMMANDS = {
    "review_fake_game_update": fake_game_update,
    "review_cache_state": cache_state,
    "review_scroll_start": scroll_start,
    "review_scroll_state": scroll_state,
    "review_finder_open": finder_open,
    "review_finder_state": finder_state,
    "review_finder_search": finder_search,
    "review_finder_select": finder_select,
    "review_finder_scope": finder_scope,
    "review_finder_close": finder_close,
    "review_scene_action": scene_action,
    "review_job_state": job_state,
    "review_job_cancel": job_cancel,
    "review_scan_start": scan_start,
    "review_close_during_job": close_during_job,
    "review_new_item_state": new_item_state,
    "review_new_item_search": new_item_search,
    "review_new_item_pick": new_item_pick,
    "review_model_library_state": model_library_state,
    "review_textures_open": textures_open,
    "review_textures_state": textures_state,
}

# The commands that only read: a stall inside one is the driver's own read (drive_review.py).
READ_ONLY = frozenset({"cache_state", "scroll_state", "finder_state", "job_state", "new_item_state",
                       "model_library_state", "textures_state"})
