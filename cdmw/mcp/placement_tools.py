"""Typed controls for the resident Placement & Animations window."""

from __future__ import annotations

import math
from contextlib import ExitStack
from dataclasses import asdict, astuple, replace

from cdmw.mcp.errors import INVALID_ARGUMENTS, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.tools import ON_CALL, ON_WORKER, Tool, object_schema
from cdmw.mcp.ui_actions import run_action

_AREAS = ("placement", "animation", "constraints", "rig")


def _invalid(message):
    raise ToolError(INVALID_ARGUMENTS, message)


def _need(args, *fields):
    for name in fields:
        if name not in args:
            _invalid(f"{args.get('action', 'This action')} requires {name}.")


def _tab(context):
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    shell = getattr(context.window, "shell", None)
    return created_tool_widget(getattr(shell, "placement_studio_tab", None))


def _window(context):
    window = getattr(_tab(context), "_studio", None)
    if window is None or window._session is None or window._model_loading:
        raise ToolError(UNAVAILABLE, "Prepare or finish loading the character with placement_open first.")
    return window


def _history(w):
    return {area: {"position": position, "can_redo": redo}
            for area in _AREAS for position, redo in [w._history_position(area)]}


def _tracked(call, action):
    def go():
        for name, value in call.arguments.items():
            values = value if isinstance(value, list) else (value,)
            if any(isinstance(v, float) and not math.isfinite(v) for v in values):
                _invalid(f"{name} must be finite.")
        w = _window(call.context)
        before = _history(w)
        try:
            result = action(w, call.arguments) or {}
        except (ValueError, ArithmeticError) as error:
            raise ToolError(INVALID_ARGUMENTS, str(error)) from None
        return {"history_before": before, "history_after": _history(w),
                "status": w.statusBar().currentMessage(), **result}

    answers = {"confirm": call.arguments.get("confirm", "no")}
    if call.arguments.get("action") == "load_file":
        answers["file"] = call.arguments.get("file", "")
    outcome = run_action(call.context, go, answers)
    return {**outcome.pop("result", {}), **outcome}


def _select(box, value):
    for index in range(box.count()):
        data = box.itemData(index)
        if value in (getattr(data, "weapon_id", data), box.itemText(index)):
            box.setCurrentIndex(index)
            return
    _invalid(f"No choice named {value!r} in this control.")


def _choices(box):
    return [dict(name=box.itemText(i), id=getattr(box.itemData(i), "weapon_id", box.itemData(i)))
            for i in range(box.count())]


def _page(w, name):
    w._ensure_tab(name)
    w._lower.setCurrentWidget(w._tab_page(name))


def _prepare(call):
    context = call.context

    def prepare():
        tab = _tab(context)
        w = getattr(tab, "_studio", None)
        before = _history(w) if w else {}
        context.window.shell._activate_tool_key("placement_studio")
        tab = _tab(context)
        if tab and tab._studio is None and tab._action.isEnabled():
            tab._action.click()
        w = getattr(tab, "_studio", None)
        return {"ready": bool(w and w._session and not w._model_loading),
                "status": tab._status.text() if tab and not w else "",
                "history_before": before, "history_after": _history(w) if w else {}}

    outcome = run_action(context, prepare)
    return {**outcome.pop("result", {}), **outcome}


def _open(w, args):
    action = args["action"]
    if action == "character":
        _need(args, "name")
        _select(w._model_box, args["name"])
    elif action == "weapon":
        _need(args, "name")
        _select(w._weapon_box, args["name"])
    elif action == "armour":
        _need(args, "slot", "name")
        _page(w, "armour")
        box = w._armour_boxes.get(args["slot"])
        if box is None:
            _invalid("Unknown armour slot.")
        _select(box, args["name"])
    elif action == "clips":
        _page(w, "animations")
        w._ensure_clip_index()
    elif action in ("constraints", "rig"):
        _page(w, "advanced")
        w._advanced_tabs.setCurrentWidget(w._constraints_page if action == "constraints" else w._behaviour_page)
        w._sync_rig_tab("constraints" if action == "constraints" else "behaviour")
    return {"loading": _loading(w)}


def _loading(w):
    tasks = ("model", "mesh", "archive", "move", "clip", "clip_index", "clip_edit", "timing", "join", "splice", "import")
    return [name for name in tasks if getattr(getattr(w, f"_{name}_task", None), "busy", False)] + (
        ["rig"] if w._rig_scan is not None else [])


def _play_state(w):
    p = w._playback
    return {"loaded": p.loaded, "clip": p.label, "playing": p.playing, "loop": p.looping,
            "seconds": p.frame / 30, "last_frame": p.last_frame}


def _snapshot(context, args):
    from tools.placement_studio.armour import SLOT_KEYS

    tab = _tab(context)
    w = getattr(tab, "_studio", None)
    if w is None or w._session is None:
        return {"open": tab is not None, "ready": False,
                "status": tab._status.text() if tab and not w else ""}, {}
    session = w._session
    offset, limit = args.get("offset", 0), args.get("limit", 100)
    query = args.get("clip_filter", "").casefold()
    state = {"open": True, "ready": not w._model_loading, "loading": _loading(w),
             "status": w.statusBar().currentMessage(), "warnings": list(dict.fromkeys([*session.warnings, *w._body_problems])),
             "history": _history(w), "active_history": w._visible_history(),
             "character": session.model, "characters": _choices(w._model_box),
             "weapon": getattr(session.weapon, "weapon_id", ""), "weapons": _choices(w._weapon_box),
             "armour": dict(getattr(w, "_armour_choice", {})), "armour_options": {
                 slot: [p.path for p in w._armour_index.pieces(session.model, slot)]
                 for slot in SLOT_KEYS},
             "sockets": [{"name": s.name, "file": s.source_file, "parent": s.parent_bone,
                          "translation": astuple(s.translation), "quaternion": astuple(s.rotation)}
                         for s in (*session.body_sockets(), *session.child_sockets())],
             "routes": [asdict(b.part) for b in w._bindings],
             "pending": [{**asdict(c), "included": c.saveable and c.key not in w._mod_unchecked}
                         for c in w._mod_changes()],
             "clips_ready": w.clip_index_ready, "playback": _play_state(w)}
    edit = w._clip_edit
    if edit is not None:
        state["animation"] = {"target": w._clip_edit_target, "last_frame": edit.last_frame,
                              "speed": edit.speed, "trim_start": edit.trim_start, "trim_end": edit.trim_end,
                              "hold": edit.hold_end, "distance_percent": edit.root_distance * 100,
                              "mirror": edit.mirror, "reverse": edit.reverse,
                              "joins": [{"label": j.label, "blend": j.blend} for j in edit.joins],
                              "splices": [{"label": s.label, "weight": s.weight} for s in edit.splices],
                              "regions": _choices(w._splice_region),
                              "pose_tracks": _choices(w._pose_bone_box), "reach_tracks": _choices(w._reach_end_box),
                              "pose": [asdict(t) for t in edit.pose], "reach": [asdict(t) for t in edit.reach],
                              "status": w._clip_edit_status.text()}
    state["constraints"] = [{"chain": c.name, "strength": c.strength} for c in
                            (w._rig_constraints.chains if w._rig_constraints else ())]
    state["rig"] = [{"row": i, "section": s.section, "path": s.path, "value": s.value}
                    for i, s in enumerate(getattr(w, "_behaviour_rows", ()))]
    if w._tab_built("advanced"):
        state["rig_skeletons"] = [w._behaviour_rig.itemText(i) for i in range(w._behaviour_rig.count())]
        state["rig_sections"] = [w._behaviour_section.itemText(i) for i in range(w._behaviour_section.count())]
        state["rig_status"] = w._behaviour_header.text()
        state["constraints_status"] = w._constraint_header.text()
    state["timing"] = [{"chart": r.event.chart, "animation": r.event.animation, "event": r.event.event,
                        "seconds": r.event.begin, "proposed": r.proposed, "movable": r.movable}
                       for r in w._timing_all_rows]
    charts = w._edits.charts() if w._edits else []
    chart = args.get("chart")
    if chart and chart not in charts:
        _invalid("Unknown loaded chart.")
    state["charts"] = charts
    # The index entries and chart bytes are immutable. Filtering and decoding happen on the worker.
    return state, (w._clip_index.entries, query, {p: w._edits.chart_bytes(p)
                        for p in ([chart] if chart else charts)}, offset, limit)


def _state(call):
    from cdmw.core.action_chart_binary import (ActionChartError, MODEL_ATTACHMENT_SOCKET_KIND,
                                               decode_action_chart, frame_event_at)

    state, inputs = call.context.ui_call(lambda: _snapshot(call.context, call.arguments))
    if not inputs:
        return state
    entries, query, charts, offset, limit = inputs
    clips = [e.path for e in entries if query in e.path.casefold()]
    state.update(clips=clips[offset:offset + limit], clip_count=len(clips))
    events = []
    count = 0
    for path, data in charts.items():
        call.check_cancelled()
        try:
            chart = decode_action_chart(data, virtual_path=path)
            for animation in chart.animations:
                for i, ref in enumerate(animation.events):
                    if frame_event_at(chart, data, ref).kind == MODEL_ATTACHMENT_SOCKET_KIND:
                        if offset <= count < offset + limit:
                            events.append(dict(chart=path, animation=animation.index, event=i, seconds=ref.begin,
                                               start=animation.start_time, end=animation.end_time))
                        count += 1
        except (ActionChartError, ValueError, IndexError) as error:
            state["warnings"].append(f"{path}: {error}")
    return {**state, "events": events, "event_count": count}


def _spin_value(spin, value):
    if not math.isfinite(value) or not spin.minimum() <= value <= spin.maximum():
        _invalid(f"Value must be between {spin.minimum()} and {spin.maximum()}.")


def _fill_spins(pairs, apply):
    from PySide6.QtCore import QSignalBlocker
    pairs = list(pairs)
    for spin, value in pairs:
        _spin_value(spin, value)
    with ExitStack() as stack:
        for spin, value in pairs:
            stack.enter_context(QSignalBlocker(spin))
            spin.setValue(value)
    apply()


def _socket(w, args):
    from PySide6.QtWidgets import QDialogButtonBox
    from tools.placement_studio.editing import EditError
    from tools.placement_studio.model import Quat, Vec3

    _need(args, "name")
    name, action = args["name"], args["action"]
    edits = w._edits
    path = w._socket_file_of(name)
    if action != "add" and not path:
        _invalid(f"No socket {name!r} on the selected character or item.")
    if args.get("file") and action != "add" and args["file"] != path:
        _invalid("This socket is not selected from the named file.")
    if action == "add":
        _need(args, "file")
        if args["file"] not in [path for _, path in w._socket_files()]:
            _invalid("Choose a socket file from the current character or weapon.")
    _page(w, "advanced")
    w._advanced_tabs.setCurrentIndex(0)
    try:
        with edits.undo_step():
            if action == "add":
                point = Vec3(*args["world_point"]) if "world_point" in args else None
                dialog = w._new_socket_dialog(point)
                try:
                    _select(dialog._file_box, args["file"])
                    if "source" in args:
                        _select(dialog._copy_box, args["source"])
                    if "parent" in args:
                        parent = args["parent"]
                        i = dialog._bone_box.findData(parent)
                        dialog._bone_box.setCurrentIndex(i)
                        if i < 0:
                            dialog._bone_box.setEditText(parent)
                    dialog._name_edit.setText(name)
                    if not dialog._buttons.button(QDialogButtonBox.Ok).isEnabled():
                        _invalid(dialog._problem.text())
                    socket = dialog.socket()
                    if "translation" in args:
                        socket = replace(socket, translation=Vec3(*args["translation"]))
                    w._add_new_socket(dialog.game_path, socket)
                finally:
                    dialog.deleteLater()
                return
            if action in ("route", "orientation"):
                _need(args, "part")
                _select(w._part_box, args["part"])
                _select(w._mesh_role_box, args.get("role", "stowed"))
            w._select_socket(name)
            if action == "translate":
                _need(args, "translation")
                values = [v * 100 for v in args["translation"]]
                for spin, value in zip(w._position, values):
                    _spin_value(spin, value)
                for i, value in enumerate(values):
                    w._position[i].setValue(value)
            elif action == "rotate":
                if ("euler" in args) == ("quaternion" in args):
                    _invalid("Give one rotation as euler or quaternion.")
                if "euler" in args:
                    _fill_spins(zip(w._euler, args["euler"]), w._apply_euler)
                else:
                    q = args["quaternion"]
                    if not math.isclose(math.hypot(*q), 1, abs_tol=1e-4):
                        _invalid("The quaternion must have unit length (x, y, z, w).")
                    edits.set_rotation_quaternion(path, name, Quat(*q))
                    w._after_edit()
            elif action == "reparent":
                _need(args, "parent")
                edits.reparent(path, name, args["parent"])
                w._after_edit()
            elif action == "route":
                w._route_selected_part_to(name)
            elif action == "orientation":
                w._use_selected_as_orientation()
            elif action == "turn":
                _need(args, "axis", "degrees")
                if not math.hypot(*args["axis"]):
                    _invalid("Choose a nonzero world rotation axis.")
                w._on_socket_rotated(name, *args["axis"], args["degrees"])
                w._settle_after_drag()
            elif action == "roll":
                _need(args, "degrees")
                w._on_socket_rolled(name, args["degrees"])
                w._settle_after_drag()
            elif action == "other_shoulder":
                w._mirror_over_other_shoulder()
            elif action == "hang_like":
                _need(args, "source")
                source = next((s for s in w._hang_like_sources()
                               if args["source"] in (s.socket_file, s.label)), None)
                if source is None:
                    _invalid("Choose another item defining this attach point.")
                w._hang_like(source)
            elif action == "back_step":
                _need(args, "direction", "sign")
                _select(w._back_move_box, args["direction"])
                if "in_step" in args:
                    w._back_in_step_box.setChecked(args["in_step"])
                w._move_on_back(args["sign"])
            elif action == "drag":
                _need(args, "delta")
                w._on_socket_dragged(name, *args["delta"])
                w._settle_after_drag()
            elif action == "revert":
                w._revert_socket()
            elif action == "flip":
                w._turn_selected_socket_over()
    except EditError as error:
        _invalid(str(error))


def _socket_tool(call):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    args = call.arguments
    action = args["action"]
    if action not in ("carry", "move", "review_move"):
        return _tracked(call, _socket)

    def prepare(w, args):
        _need(args, "part")
        _select(w._part_box, args["part"])
        if action == "carry":
            _select(w._carry_box, args["name"])
            if "mirror" in args:
                w._carry_mirror.setChecked(args["mirror"])
            plan = w._carry_plan
            if plan is None or plan.blocked or not plan.changes_anything:
                raise ToolError(UNAVAILABLE, w._carry_plan_label.text())
        else:
            if not w.clip_index_ready:
                w._ensure_clip_index()
                raise ToolError(UNAVAILABLE, "The clip index is loading. Retry when clips_ready is true.")
            dialog = w._make_move_dialog()
            if dialog is None:
                raise ToolError(UNAVAILABLE, w.statusBar().currentMessage())
            try:
                _select(dialog._to_box, args["name"])
                dialog._scope_buttons[args.get("scope", "placement_only")].setChecked(True)
                for name in ("include_borrowed", "include_mounted", "orientation_reviewed", "advanced_confirmed"):
                    getattr(dialog, "_" + ("advanced_confirm" if name == "advanced_confirmed" else name)
                            ).setChecked(args.get(name, False))
                for key, boxes in (("contexts", dialog._context_boxes), ("include_links", dialog._link_boxes)):
                    if key in args:
                        if set(args[key]) - boxes.keys():
                            _invalid(f"Unknown choice in {key}.")
                        for name, box in boxes.items():
                            box.setChecked(name in args[key])
                model = dialog._file_model
                if "pairs" in args:
                    by_target = {row.target_path: i for i, row in enumerate(model.rows)}
                    model.select_all(False)
                    for pair in args["pairs"]:
                        i = by_target.get(pair["target"])
                        if i is None or not model.setData(model.index(i, 2), pair["donor"]):
                            _invalid("That target/donor pair is not offered for this move.")
                        model.setData(model.index(i, 0), Qt.Checked, Qt.CheckStateRole)
                plan = dialog.plan()
                if action == "review_move":
                    return {"review": plan.review_lines(), "blockers": list(plan.blockers),
                            "links": list(dialog._link_boxes), "contexts": list(dialog._context_boxes),
                            "pairs": [{"target": r.target_path, "donors": [d.path for d in r.options or (r.donor,)]}
                                      for r in model.rows]}
                if plan.blocked or not plan.changes_anything:
                    raise ToolError(UNAVAILABLE, "; ".join(plan.blockers) or "There is no change to apply.")
            finally:
                dialog.close()
                dialog.deleteLater()
        work = None if plan.mirror_of else w._move_preparation_work(plan)
        return {"inputs": (w, w._session, w._edits.capture(), plan, work)}

    result = _tracked(call, prepare)
    if "inputs" not in result:
        return result
    window, session, snapshot, plan, work = result.pop("inputs")
    prepared = work(call.cancelled, lambda done, total: call.progress(done, total)).prepared if work else None
    call.check_cancelled()

    def commit(w, _args):
        if w is not window or w._session is not session or w._edits.capture() != snapshot:
            raise ToolError(UNAVAILABLE, "The character or edits changed while preparing the move.")
        w._play_after_swap = False
        pairs = [(r.target, r.donor) for r in plan.request.replacements]
        w._swap_preview = w._preview_pair(pairs) if pairs else None
        with w._edits.undo_step():
            applied = w._apply_move_operation(plan, prepared, acknowledge=lambda box:
                                              QMessageBox.information(w, box.windowTitle(), box.text()))
        if not applied:
            raise ToolError(UNAVAILABLE, w.statusBar().currentMessage())
        return {"review": plan.review_lines()}

    return _tracked(call, commit)


def _frame(seconds, last):
    frame = seconds * 30
    if not math.isfinite(frame) or not 0 <= frame <= last + 1e-6:
        _invalid(f"Time must be in the clip (0 to {last / 30:g} seconds).")
    return round(frame)


def _key(w, args):
    _need(args, "lane", "track")
    pose = args["lane"] == "pose"
    _select(w._pose_bone_box if pose else w._reach_end_box, args["track"])
    action = args["action"]
    if action == "clear_track":
        if pose:
            w._clear_pose_bone()
        else:
            w._clear_reach()
        return
    _need(args, "seconds")
    edit = w._clip_edit
    frame = _frame(args["seconds"], edit.last_frame)
    if action in ("plant", "release"):
        if pose:
            _invalid("Select a reach track for this action.")
        w._seek_from_timeline(frame)
        if action == "plant":
            w._plant_reach()
        else:
            w._release_reach()
        return
    if action in ("move_key", "remove_key"):
        track = edit.pose_track(w._selected_bone_hash()) if pose else edit.reach_track(w._selected_reach_end())
        if track is None or not any(key.frame == frame for key in track.keys):
            _invalid("There is no key on that track at that time.")
        if action == "move_key":
            _need(args, "to_seconds")
            w._move_key_on_timeline(args["lane"], frame, _frame(args["to_seconds"], edit.last_frame))
        else:
            w._remove_key_on_timeline(args["lane"], frame)
        return
    if pose and ("weight" in args or "pinned" in args):
        _invalid("Weight and pinned belong to reach keys.")
    if not pose and "euler" in args:
        _invalid("Angles belong to pose keys.")
    w._seek_from_timeline(frame)
    if pose:
        pairs = list(zip(w._pose_turn, args.get("euler", ())))
        pairs.extend(zip(w._pose_move, (x * 100 for x in args.get("translation", ()))))
        _fill_spins(pairs, lambda: w._on_pose_value_changed(0))
    else:
        pairs = list(zip(w._reach_move, (x * 100 for x in args.get("translation", ()))))
        if "weight" in args:
            pairs.append((w._reach_weight, args["weight"] * 100))
        _fill_spins(pairs, lambda: w._set_reach_key(pinned=args.get("pinned")))


def _animation(w, args):
    from tools.placement_studio.carry_timing import event_key
    from tools.placement_studio.editing import EditError, OP_RETIME_EVENTS, OperationScope

    action = args["action"]
    if action in ("measure_timing", "apply_timing", "retime_event"):
        _page(w, "animations")
        w._show_animation_page("timing")
    if action == "retime_event":
        _need(args, "chart", "animation", "event", "seconds")
        chart, animation, event = (args[k] for k in ("chart", "animation", "event"))
        if chart not in w._edits.charts():
            _invalid("Unknown loaded chart.")
        scope = OperationScope(kind=OP_RETIME_EVENTS, model=w._session.model,
                               allowed_chart_events=(event_key(chart, animation, event),))
        try:
            with w._edits.keep_on_failure(), w._edits.begin_operation(
                    scope, label=f"{chart} ({animation}, {event})") as handle:
                handle.retime_event(chart, animation, event, args["seconds"])
        except EditError as error:
            _invalid(str(error))
        w._after_edit()
        return
    if action == "retarget":
        _need(args, "source", "target")
        _page(w, "advanced")
        w._advanced_tabs.setCurrentIndex(3)
        _select(w._chart_socket_box, args["source"])
        _select(w._retarget_box, args["target"])
        with w._edits.undo_step():
            w._apply_retarget()
        return
    if action in ("measure_timing", "apply_timing"):
        if "part" in args:
            _select(w._part_box, args["part"])
        if action == "measure_timing":
            w._start_timing()
        else:
            selected = "chart" in args
            if selected:
                _need(args, "animation", "event")
                key = event_key(args["chart"], args["animation"], args["event"])
                row = next((i for i, r in enumerate(w._timing_rows) if r.event.key == key and r.movable), None)
                if row is None:
                    _invalid("No measured, movable hand-off matches that event.")
                w._timing_table.selectRow(row)
            w._move_timing(selected_only=selected)
        return {"timing_status": w._timing_status.text()}
    _page(w, "edit")
    if action in ("start", "from_pose"):
        if not w._playback.loaded:
            raise ToolError(UNAVAILABLE, "Load a clip first.")
        if action == "start":
            w._start_clip_edit()
        else:
            if "seconds" in args:
                _spin_value(w._new_length, args["seconds"])
                w._new_length.setValue(args["seconds"])
            w._start_from_pose()
        return
    if w._clip_edit is None:
        raise ToolError(UNAVAILABLE, "Start editing the playing clip first.")
    if action in ("edit_key", "move_key", "remove_key", "clear_track", "plant", "release"):
        _key(w, args)
    elif action == "clip_timing":
        from PySide6.QtCore import QSignalBlocker
        pairs = [(spin, args[key]) for key, spin in
                 (("speed", w._edit_speed), ("trim_start", w._edit_trim_start),
                  ("trim_end", w._edit_trim_end), ("hold", w._edit_hold),
                  ("distance_percent", w._edit_distance)) if key in args]
        for spin, value in pairs:
            _spin_value(spin, value)
        for key, box in (("mirror", w._edit_mirror), ("reverse", w._edit_reverse)):
            if key in args:
                with QSignalBlocker(box):
                    box.setChecked(args[key])
        _fill_spins(pairs, w._on_timing_changed)
    elif action == "reset":
        w._reset_clip_edit()
    elif action in ("remove_join", "remove_splice"):
        _need(args, "row")
        listing = w._join_list if action == "remove_join" else w._splice_list
        if args["row"] >= listing.count():
            _invalid("That layer does not exist.")
        listing.setCurrentRow(args["row"])
        w._remove_join() if action == "remove_join" else w._remove_splice()
    elif action == "track_options":
        _need(args, "lane", "track", "enabled")
        if args["lane"] == "pose":
            _select(w._pose_bone_box, args["track"])
            w._pose_smooth.setChecked(args["enabled"])
        else:
            _select(w._reach_end_box, args["track"])
            w._reach_keep_angle.setChecked(args["enabled"])
    return {"animation_status": w._clip_edit_status.text()}


def _clip_entry(w, path):
    entry = w._clip_index.find(path)
    if entry is None:
        entry = getattr(w, "_playback_entry", None)
        if entry is None or entry.path != path:
            _invalid("Unknown clip path. Open the clip list and read placement_state.")
    return entry


def _clip_work(call):
    """Read, bake and encode outside Qt. Only the window commits the finished edit."""
    from tools.paa_motion.edit import render
    from tools.paa_motion.encode import encode_paa
    from tools.placement_studio.clips import read_clip
    from tools.placement_studio.playback import coverage, load_clip

    args, action = call.arguments, call.arguments["action"]

    def prepare():
        w = _window(call.context)
        _page(w, "edit")
        edit = w._clip_edit
        source = _clip_entry(w, args["source"]) if "source" in args else None
        if edit is not None and w._clip_edit_model != w._current_model():
            raise ToolError(UNAVAILABLE, "Start an edit on the selected character.")
        if edit is None and (source is None or action != "replace_clip"):
            raise ToolError(UNAVAILABLE, "Start an animation edit first.")
        target = args.get("target", w._clip_edit_target)
        if action == "replace_clip":
            if not target or not target.startswith("character/"):
                _invalid("Select a game clip as the replacement target.")
            if target != w._clip_edit_target:
                _clip_entry(w, target)
        elif source is None:
            _invalid(f"{action} requires a source clip path.")
        if action == "splice":
            _need(args, "region")
            _select(w._splice_region, args["region"])
        previous_target = w._clip_edit_target
        original = w._clip_edit_from_game and w._clip_edit_entry and w._clip_edit_entry.path == target
        return (w, w._session, w._session.hierarchy, edit, w._editor_skeleton(), source, target,
                bool(original), w._clip_edit_label, previous_target)

    prepared = run_action(call.context, prepare)
    if "result" not in prepared:
        return prepared
    window, session, hierarchy, edit, skeleton, source, target, from_game, label, previous_target = prepared["result"]
    if source:
        data = read_clip(source)
        clip = load_clip(data, source.name)
        if action == "replace_clip" and coverage(hierarchy, clip) <= 0:
            _invalid("The source clip animates no bone on this rig.")
    else:
        clip = render(edit, skeleton, should_stop=call.cancelled)
        data = encode_paa(clip)
    original = encode_paa(edit.base) if edit is not None and from_game and action == "replace_clip" else None
    call.check_cancelled()

    def apply(w, args):
        if (w is not window or w._session is not session or w._clip_edit is not edit
                or w._clip_edit_target != previous_target):
            raise ToolError(UNAVAILABLE, "The character, target or animation changed while preparing the clip.")
        if action == "replace_clip":
            if edit is not None and w._clip_edit_target != target:
                w._set_clip_edit_target(target)
            if w._record_clip_replacement(target, data, source.name if source else label, original):
                _page(w, "mod")
        elif action == "join":
            blend = args.get("blend", w._join_blend.value())
            _spin_value(w._join_blend, blend)
            w._join_blend.setValue(blend)
            w._join_read((source, blend, clip, edit.base), "")
        else:
            weight = args.get("weight", w._splice_weight.value() / 100)
            w._splice_weight.setValue(weight * 100)
            w._splice_read((source, args["region"], weight, clip, edit.base), "")
        return {"animation_status": w._clip_edit_status.text()}

    return _tracked(call, apply)


def _import_animation(call):
    from PySide6.QtWidgets import QFileDialog
    from tools.paa_motion.gltf_import import import_animation

    args = call.arguments
    _need(args, "file")

    def prepare():
        w = _window(call.context)
        _page(w, "edit")
        edit = w._clip_edit
        template = edit.base if edit else w._playback.clip
        skeleton = w._editor_skeleton()
        if template is None or skeleton is None:
            raise ToolError(UNAVAILABLE, "Load the animation and character used for the import.")
        if not w._confirm_replace_edit():
            raise ToolError(REFUSED, "The current animation draft was kept.")
        path, _ = QFileDialog.getOpenFileName(w, "Import an animation from Blender", "", "glTF (*.glb *.gltf)")
        if not path:
            _invalid("Choose an existing glTF file.")
        return w, w._session, edit, skeleton, template, path

    outcome = run_action(call.context, prepare, {"file": args["file"], "confirm": args.get("confirm", "no")})
    if "result" not in outcome:
        return outcome
    window, session, edit, skeleton, template, path = outcome["result"]
    report = import_animation(path, skeleton, template, should_stop=call.cancelled)
    call.check_cancelled()

    def apply(w, _args):
        if w is not window or w._session is not session or w._clip_edit is not edit:
            raise ToolError(UNAVAILABLE, "The character or draft changed during import.")
        w._blender_imported((path, report), "")
        return {"animation_status": w._clip_edit_status.text()}

    result = _tracked(call, apply)
    result["asked"] = outcome["asked"] + result["asked"]
    return result


def _discard(w, args):
    # These are the same irreversible controls and confirmation the mod page offers.
    _page(w, "mod")
    if args["action"] == "all":
        w._start_over()
    else:
        _need(args, "key")
        row = next((i for i, change in enumerate(w._mod_changes()) if change.key == args["key"]), None)
        if row is None:
            _invalid("Unknown pending change.")
        w._mod_list.setCurrentItem(w._mod_list.topLevelItem(row))
        w._discard_selected_change()


def _constraints(w, args):
    _open(w, {"action": "constraints"})
    if w._rig_constraints is None or w._rig_scan is not None:
        raise ToolError(UNAVAILABLE, w._constraint_header.text())
    if args["action"] == "reset":
        w._on_chain_reset()
    else:
        _need(args, "chain")
        if w._rig_constraints.chain_named(args["chain"]) is None:
            _invalid("Unknown chain.")
        w._reselect(args["chain"])
        if not w._chain_slider.isEnabled():
            raise ToolError(UNAVAILABLE, "This chain has no editable strength.")
        if args["action"] == "off":
            w._on_chain_off()
        else:
            _need(args, "strength")
            w._apply_strength(args["strength"])
    return {"pending": list(w.constraint_changes())}


def _rig(w, args):
    _open(w, {"action": "rig"})
    if w._behaviour is None or w._rig_scan is not None:
        raise ToolError(UNAVAILABLE, w._behaviour_header.text())
    if args["action"] == "reset":
        w._on_behaviour_reset()
    else:
        if "skeleton" in args:
            _select(w._behaviour_rig, args["skeleton"])
        if "section" in args:
            _select(w._behaviour_section, args["section"])
        if "row" in args:
            row = args["row"]
            if row >= len(w._behaviour_rows):
                _invalid("Unknown setting row.")
        else:
            _need(args, "path")
            rows = [i for i, s in enumerate(w._behaviour_rows) if s.path == args["path"]]
            if len(rows) != 1:
                _invalid("Select one setting by row or its unique path.")
            row = rows[0]
        w._behaviour_table.selectRow(row)
        if args["action"] == "scale":
            _need(args, "factor")
            if not w._selected_setting().numeric:
                _invalid("This rig setting is not numeric.")
            w._on_behaviour_scale(args["factor"])
        else:
            _need(args, "value")
            w._behaviour_value.setText(args["value"])
            w._on_behaviour_apply()
    return {"pending": list(w.rig_behaviour_changes()), "message": w._behaviour_pending.text()}


def _playback(w, args):
    action = args["action"]
    if action == "load_file":
        _need(args, "file")
        w._on_playback_load()
    elif action == "load":
        _need(args, "clip")
        w._play_clip_entry(_clip_entry(w, args["clip"]))
    elif action == "clear":
        w._on_playback_clear()
    else:
        if not w._playback.loaded:
            raise ToolError(UNAVAILABLE, "Load a clip before controlling playback.")
        if action == "scrub":
            _need(args, "seconds")
            w._seek_from_timeline(_frame(args["seconds"], w._playback.last_frame))
        elif action == "loop":
            _need(args, "enabled")
            w._playback_loop_box.setChecked(args["enabled"])
        elif (action == "play") != w._playback.playing:
            w._on_playback_toggle()
    return {"playback": _play_state(w)}


_SHOW = {"bones": "_show_bones", "labels": "_show_labels", "unused_sockets": "_show_unused",
         "meshes": "_show_meshes", "solid_body": "_solid_body", "reverse_drag": "_reverse_orbit"}


def _view(call):
    """The window's Show menu and Reset view (R): what the viewport draws, not the mod."""

    args = call.arguments

    def go():
        w = _window(call.context)
        for key, name in _SHOW.items():
            if key in args:
                getattr(w, name).setChecked(bool(args[key]))
        if args.get("reset"):
            w._viewport.reset_view()
        return {"show": {key: getattr(w, name).isChecked() for key, name in _SHOW.items()}}

    return call.context.ui_call(go)


def _export(call):
    """Export files on their own, as the window's Export buttons do: a Blender GLB of the playing or edited
    animation, the edited animation as a .paa, or every edited file into a folder."""

    import time
    from pathlib import Path

    args = call.arguments
    kind = args["kind"]
    if kind == "edited_files":
        if not args.get("folder"):
            _invalid("Give the folder to export the edited files into.")
        target = Path(str(args["folder"]))
        if not target.is_dir():
            _invalid("Choose an existing folder.")
        answers = {"folder": str(target)}
    else:
        if not args.get("save_file"):
            _invalid("Give save_file for this export.")
        target = Path(str(args["save_file"]))
        suffix = ".glb" if kind == "blender_glb" else ".paa"
        if target.suffix.lower() != suffix:
            _invalid(f"Save this export as a {suffix} file.")
        answers = {"save_file": str(target)}
    before = target.stat().st_mtime_ns if kind != "edited_files" and target.exists() else None

    def press():
        w = _window(call.context)
        if kind == "blender_glb":
            w._export_for_blender()
        elif kind == "animation":
            if w._clip_edit is None:
                raise ToolError(UNAVAILABLE, "Start an animation edit first (placement_animation start).")
            w._export_clip_edit()
        else:
            if w._edits is None or not w._edits.modified_paths():
                raise ToolError(UNAVAILABLE, "There are no edited files to export.")
            w._export()
        return w.statusBar().currentMessage()

    outcome = run_action(call.context, press, answers)
    if "result" not in outcome or kind == "edited_files":
        return outcome
    deadline = time.monotonic() + 60.0
    while not (target.exists() and target.stat().st_mtime_ns != before):
        call.check_cancelled()
        if any(row.get("kind") == "warning" for row in outcome.get("asked") or ()):
            raise ToolError(REFUSED, "The export stopped; see asked for the window's message.", outcome)
        if time.monotonic() > deadline:
            raise ToolError(UNAVAILABLE, "The export did not finish in time. "
                            + str(call.context.ui_call(lambda: _window(call.context).statusBar().currentMessage())),
                            outcome)
        time.sleep(0.05)
    return {**outcome, "saved": str(target)}


def _capture(call):
    from cdmw.mcp.control_tools import MAX_PICTURE_SIDE, png_of
    from cdmw.mcp.server import ImageResult

    def grab():
        w = _window(call.context)
        return w._viewport.grab().toImage(), _play_state(w)

    frame, playhead = call.context.ui_call(grab)
    data, width, height = png_of(frame, call.arguments.get("max_side", MAX_PICTURE_SIDE))
    return ImageResult(data, {"view": "placement", "width": width, "height": height, "playback": playhead})


def _save(call):
    from cdmw.domain.output_paths import OutputPathRefused, check_output_path
    from tools.placement_studio import save_mod
    from tools.placement_studio.corpus import baseline_is_stale
    from tools.placement_studio.editing import EditSession
    from tools.placement_studio.packaging import PackageMetadata, PackagingError, package_destinations
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtCore import Qt

    args = call.arguments
    game = call.context.game_folder()
    try:
        folder = check_output_path(args["folder"], game_folder=game, allow_existing=True)
    except OutputPathRefused as error:
        raise ToolError(REFUSED, str(error)) from None
    if not folder.is_dir():
        _invalid("Choose an existing output folder.")

    def prepare():
        w = _window(call.context)
        before = _history(w)
        _page(w, "mod")
        if "include" in args:
            selected = set(args["include"])
            if not selected or selected - {c.key for c in w._mod_changes() if c.saveable}:
                _invalid("include must contain saveable keys from the pending change list.")
            for index, change in enumerate(w._mod_changes()):
                if change.saveable:
                    item = w._mod_list.topLevelItem(index)
                    item.setCheckState(0, Qt.Checked if change.key in selected else Qt.Unchecked)
        for key, box in (("name", w._mod_name_edit), ("author", w._mod_author_edit),
                         ("version", w._mod_version_edit)):
            if key in args:
                box.setText(args[key])
        w._save_to_folder.setChecked(True)
        request = w._save_request()
        if request is None:
            raise ToolError(UNAVAILABLE, w.statusBar().currentMessage())
        return w, request, w._edits.capture(), w._prepare_save_inputs(request), before

    outcome = run_action(call.context, prepare, {"folder": str(folder)})
    if "result" not in outcome:
        return outcome
    window, request, snapshot, build_inputs, before = outcome["result"]
    try:
        for target in package_destinations(PackageMetadata(name=request.name), out_root=folder,
                                           managers=save_mod.MOD_MANAGERS):
            check_output_path(target, game_folder=game)
    except (OutputPathRefused, PackagingError) as error:
        raise ToolError(REFUSED, str(error)) from None

    edits = EditSession.from_snapshot(snapshot)
    inputs = build_inputs()

    def current():
        return not baseline_is_stale(inputs["baseline"])

    call.check_cancelled()
    result = save_mod.save_mod(edits, request, **inputs, baseline_current=current)
    asked = outcome["asked"]
    if result.warnings:
        warning = run_action(call.context, lambda: QMessageBox.question(
            window, "Check before saving", "\n".join(result.warnings),
            QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel),
            {"confirm": "save" if args.get("accept_warnings") else "cancel"})
        asked.extend(warning["asked"])
        if warning.get("result") == QMessageBox.Save:
            call.check_cancelled()
            result = save_mod.save_mod(edits, replace(request, accept_warnings=True), **inputs,
                                       baseline_current=current)

    def finish():
        tab = _tab(call.context)
        if getattr(tab, "_studio", None) is window:
            if result.manual_operation and window._edits.capture() == snapshot:
                window._edits.adopt_loose_commands("Manual adjustments")
                window._refresh_mod_list()
            if result.saved:
                window._show_saved_mod(request, result.results[0].root, window._backup_note(result.backup))
            return _history(window)
        return None

    after = run_action(call.context, finish)
    return {"saved": result.saved, "destination": str(result.destination or ""),
            "problems": list(result.problems), "warnings": list(result.warnings), "asked": asked,
            "history_before": before, "history_after": after.get("result")}


def _enum(*choices):
    return {"type": "string", "enum": list(choices)}


def _vector(size):
    return {"type": "array", "items": {"type": "number"}, "minItems": size, "maxItems": size}


def _open_tool(call):
    if call.arguments.get("action", "prepare") == "prepare":
        return _prepare(call)
    return _tracked(call, _open)


def _animation_tool(call):
    if call.arguments["action"] == "import":
        return _import_animation(call)
    if call.arguments["action"] in ("replace_clip", "join", "splice"):
        return _clip_work(call)
    return _tracked(call, _animation)


def _step(call):
    def step(w, args):
        area = args.get("area", w._visible_history())
        redo = call.tool.name == "placement.redo"
        if area == "operation":
            w._edits.redo_operation() if redo else w._edits.undo_operation()
            w._after_edit()
            w._populate_parts()
            w._populate_carry_box()
        else:
            w._step_history(area, redo=redo)
        return {"area": area}
    return _tracked(call, step)


def placement_tools() -> list[Tool]:
    text = {"type": "string", "maxLength": 1024}
    number = {"type": "number"}
    seconds = {"type": "number", "minimum": 0}
    index = {"type": "integer", "minimum": 0}
    flag = {"type": "boolean"}
    strings = {"type": "array", "items": text, "maxItems": 256}
    confirm = _enum("yes", "no")
    def edit(fn):
        def handler(call):
            return _tracked(call, fn)
        return handler

    def tool(name, description, fields, handler, route, *, required=(), effect=EDIT, runs_on=ON_CALL, **kwargs):
        return Tool(name=f"placement.{name}", family="placement", description=description,
                    input_schema=object_schema(fields, required), effect=effect, route=f"ui:{route}",
                    handler=handler, runs_on=runs_on, **kwargs)

    return [
        tool("state", "Read the current character, sockets (metres, xyzw), routes, clip and event pages, "
             "draft keys, rig settings, history, warnings and checked changes. Clip and event pages use "
             "the same offset and limit. Filter clips by path or events by chart.",
             {"offset": index, "limit": {"type": "integer", "minimum": 1, "maximum": 500},
              "clip_filter": text, "chart": text}, _state, "PlacementStudioWindow", effect=READ, runs_on=ON_WORKER),
        tool("open", "Prepare Placement & Animations, select a character/weapon by name or ID, select armour "
             "by slot and name/path, or open a page to start indexing. Poll placement_state for readiness.",
             {"action": _enum("prepare", "character", "weapon", "armour", "clips", "constraints", "rig"),
              "name": text, "slot": text}, _open_tool, "PlacementStudioTab._start"),
        tool("socket", "Edit the named attach point. translation is absolute in parent-local metres, "
             "delta is a world-space drag in metres, euler is roll/pitch/yaw in degrees, quaternion is xyzw. "
             "Add requires the socket file. Route/orientation/carry require a part. review_move lists compatible "
             "donors for a destination, scope and linked parts. move prepares, checks and applies that request.",
             {"action": _enum("add", "translate", "rotate", "drag", "reparent", "route", "orientation",
                              "carry", "review_move", "move", "turn", "roll", "other_shoulder",
                              "hang_like", "back_step", "flip", "revert"), "name": text, "file": text, "parent": text,
              "part": text, "role": _enum("held", "stowed"), "translation": _vector(3), "delta": _vector(3),
              "euler": _vector(3), "quaternion": _vector(4), "mirror": flag, "confirm": confirm,
              "world_point": _vector(3), "axis": _vector(3), "degrees": number, "direction": text, "source": text, "in_step": flag,
              "sign": {"type": "integer", "enum": [-1, 1]},
              "scope": _enum("placement_only", "draw_stow", "stowed_locomotion", "full_body"),
              "contexts": strings, "include_links": strings, "include_mounted": flag,
              "include_borrowed": flag, "orientation_reviewed": flag, "advanced_confirmed": flag,
              "pairs": {"type": "array", "maxItems": 512,
                        "items": object_schema({"target": text, "donor": text}, ["target", "donor"])}},
             _socket_tool, "EditPanelMixin", required=("action", "name"), runs_on=ON_WORKER),
        tool("animation", "Edit the playing clip with start/from_pose. Address pose and reach keys by lane, "
             "track name and seconds (30 fps). Move to to_seconds. Offsets use metres, angles degrees. "
             "replace_clip adds the edited draft to Your mod, or uses an indexed source and target clip. "
             "retime_event needs chart, animation index, event index and seconds. measure_timing surveys "
             "carry/draw hand-offs. apply_timing takes a measured event or all sure proposals. "
             "join and splice take a source clip. track_options sets ease/keep angle.",
             {"action": _enum("import", "start", "from_pose", "edit_key", "move_key", "remove_key", "replace_clip",
                              "clear_track", "plant", "release", "retime_event", "measure_timing",
                              "apply_timing", "retarget", "clip_timing",
                              "join", "splice", "remove_join", "remove_splice", "track_options", "reset"),
              "chart": text, "animation": index, "event": index, "seconds": seconds, "to_seconds": seconds,
              "track": text, "lane": _enum("pose", "reach"), "translation": _vector(3), "euler": _vector(3),
              "weight": {"type": "number", "minimum": 0, "maximum": 1}, "pinned": flag, "enabled": flag,
              "part": text, "source": text, "target": text, "speed": number, "trim_start": seconds,
              "trim_end": seconds, "hold": seconds, "distance_percent": number, "mirror": flag, "reverse": flag,
              "file": text, "region": text, "row": index, "blend": seconds, "confirm": confirm}, _animation_tool,
             "AnimationEditorMixin|TimingPanelMixin", required=("action",), runs_on=ON_WORKER),
        tool("constraints", "Set a named driven-bone chain's strength in percent, switch it off, or reset "
             "all chains on the character's Constraints page.", {"action": _enum("set", "off", "reset"),
             "chain": text, "strength": {"type": "integer", "minimum": 0, "maximum": 100}},
             edit(_constraints), "SecondaryMotionMixin._set_chain_target", required=("action",)),
        tool("rig", "Set or scale a Rig Behaviour setting by row or unique path, or reset the descriptor. "
             "Optional skeleton and section select the same filters as the page.",
             {"action": _enum("set", "scale", "reset"), "skeleton": text, "section": text,
              "path": text, "row": index, "value": text, "factor": number},
             edit(_rig), "RigBehaviourMixin._on_behaviour_apply", required=("action",)),
        *[tool(name, f"{name.capitalize()} in the window's history. Defaults to the visible page. "
               "Use placement for committed mod changes, animation for draft keys.",
               {"area": _enum(*_AREAS, "operation")}, _step, "EditPanelMixin._step_history") for name in ("undo", "redo")],
        tool("discard", "Remove a pending change by key, or start over. The window asks for confirmation. "
             "Pass confirm=yes to remove the changes.", {"action": _enum("change", "all"), "key": text,
             "confirm": confirm}, edit(_discard), "SaveModMixin._discard_selected_change",
             required=("action",), effect=DESTRUCTIVE),
        tool("save_mod", "Save the checked changes in a new mod folder under an existing non-game folder. "
             "Optionally choose pending keys with include. Refusals and preflight warnings are returned.",
             {"folder": text, "name": text, "author": text, "version": text,
              "include": {"type": "array", "items": text, "maxItems": 512}, "accept_warnings": flag},
             _save, "SaveModMixin._save_request", required=("folder",), effect=OUTPUT, runs_on=ON_WORKER,
             output_folders=("folder",)),
        tool("view", "The viewport's Show menu (bones, labels, unused_sockets, meshes, solid_body, reverse_drag) "
             "and Reset view. Without arguments, what is shown. Take a picture with placement_capture.",
             {**{key: flag for key in _SHOW}, "reset": flag}, _view, "PlacementStudioWindow._show_actions",
             effect=READ),
        tool("export", "Export files on their own (no mod): blender_glb writes the playing or edited animation "
             "as a .glb for Blender, animation writes the edited animation as a .paa, edited_files writes every "
             "edited file into an existing folder. Use placement_save_mod for a mod.",
             {"kind": _enum("blender_glb", "animation", "edited_files"), "save_file": text, "folder": text},
             _export, "AnimationEditorMixin._export_for_blender|EditPanelMixin._export", required=("kind",),
             effect=OUTPUT, runs_on=ON_WORKER, output_paths=("save_file",), output_folders=("folder",)),
        tool("playback", "Load an indexed clip by path, play, pause, scrub to seconds, set looping or clear.",
             {"action": _enum("load", "load_file", "play", "pause", "scrub", "loop", "clear"),
              "clip": text, "file": text,
              "seconds": seconds, "enabled": flag}, edit(_playback), "PlaybackMixin", required=("action",)),
        tool("capture", "Return the current Placement viewport as a PNG with the playhead position.",
             {"max_side": {"type": "integer", "minimum": 1, "maximum": 1600}}, _capture,
             "SkeletonViewport.grab", effect=READ),
    ]
