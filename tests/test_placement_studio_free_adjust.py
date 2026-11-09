"""Free adjustment of a moved item: drags and buttons act in the frame the user sees.

The item hangs as `inverse(child socket) . body socket world`. After a move to the back the
body socket sits on a spine bone that is turned well away from the world axes, and the item's
own point is turned again. Three faults met there, and each read as "it will not rotate":

* the drag axis was passed into the item's own point unconverted, so it turned about the
  item's model axes (negated) rather than the ring that was grabbed;
* a move drag fed a world-space delta straight into a bone- or item-space translation;
* the free and edge-on rotate drags snapped every mouse event on its own and threw the rest
  away, so a slow drag of a few pixels per event never turned anything.

Synthetic rig and files only; no game install.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from tests.test_placement_studio_operations import (
    ALIAS,
    BODY,
    DESC,
    FILES,
    MODEL,
    W1H,
    _sockets,
)
from tools.placement_studio import corpus
from tools.placement_studio.editing import EditSession
from tools.placement_studio.model import Quat, Vec3
from tools.placement_studio.resolver import PlacementResolver
from tools.placement_studio.session import PlacementSession
from tools.placement_studio.skeleton import (
    BoneHierarchy,
    BoneNode,
    matrix_from,
    transform_point,
    translation_of,
)


@pytest.fixture
def window(monkeypatch, tmp_path):
    """The headless window over the synthetic files, as the task layout tests build it."""

    QApplication.instance() or QApplication([])
    from tools.placement_studio.window import PlacementStudioWindow

    monkeypatch.setattr(PlacementStudioWindow, "_start_armour_index", lambda self: None)
    monkeypatch.setattr(PlacementStudioWindow, "_start_archive_content_load",
                        lambda *a, **k: None)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(PlacementStudioWindow, "_mod_settings", lambda self: settings)
    base = tmp_path / "vanilla"
    records = {path: corpus._pin(base, path, data, "0009") for path, data in FILES.items()}
    studio = PlacementStudioWindow(corpus.Baseline(base, records), background_loading=False)
    yield studio
    studio.close()
    studio.deleteLater()


BACK = "Spine2_B_MainWeapon_Socket"
GRIP = "CDMW_Sword_R_back_ChildSocket"


def _files() -> dict:
    """The fixture, with a turned back socket and a turned, offset point on the sword."""

    files = dict(FILES)
    back_turn = Quat.from_euler_degrees(20.0, -35.0, 70.0)
    grip_turn = Quat.from_euler_degrees(-60.0, 15.0, 110.0)
    body = files[BODY].decode("utf-8-sig")
    files[BODY] = body.replace(
        f'Name="{BACK}" Parent="Bip01 Spine2" Rotation="0.000000 0.000000 0.000000 1.000000"',
        f'Name="{BACK}" Parent="Bip01 Spine2" Rotation="{back_turn.x:.6f} {back_turn.y:.6f} '
        f'{back_turn.z:.6f} {back_turn.w:.6f}"',
    ).encode("utf-8-sig")
    assert files[BODY] != FILES[BODY]
    files[W1H] = _sockets(
        "Basic_ChildSocket||0.000000 0.000000 0.000000 1.000000|0.000000 0.000000 0.000000",
        "Pelvis_L_ChildSocket||0.000000 0.000000 0.000000 1.000000|0.000000 -0.200000 0.000000",
        f"{GRIP}||{grip_turn.x:.6f} {grip_turn.y:.6f} {grip_turn.z:.6f} {grip_turn.w:.6f}"
        "|0.030000 -0.250000 0.010000",
    )
    for path in (DESC, ALIAS):
        files[path] = files[path].replace(
            b'InSocketBone="Pelvis_L_Socket" OutSocketBone="RHand_Socket"'
            b' InChildSocketBone="Pelvis_L_ChildSocket"',
            f'InSocketBone="{BACK}" OutSocketBone="RHand_Socket"'
            f' InChildSocketBone="{GRIP}"'.encode(),
        )
        assert files[path] != FILES[path]
    return files


def _rig() -> BoneHierarchy:
    """Pelvis and a spine bone turned off every world axis, so a missed conversion shows."""

    spine = matrix_from(Quat.from_euler_degrees(-25.0, 40.0, 160.0), Vec3(0.0, 1.35, -0.05))
    pelvis = matrix_from(Quat(), Vec3(0.0, 1.0, 0.0))
    hand = matrix_from(Quat.from_euler_degrees(10.0, 0.0, -80.0), Vec3(0.4, 1.1, 0.2))
    return BoneHierarchy([
        BoneNode(0, "Bip01 Pelvis", -1, pelvis, Vec3(0.0, 1.0, 0.0)),
        BoneNode(1, "Bip01 Spine2", 0, spine, Vec3(0.0, 0.35, -0.05)),
        BoneNode(2, "Bip01 R Hand", 1, hand, Vec3(0.4, -0.25, 0.25)),
    ], "test")


def _session(files) -> PlacementSession:
    resolver = PlacementResolver()
    resolver.add_files(files)
    session = PlacementSession(MODEL, _rig(), resolver)
    session.select_weapon(next(w for w in session.weapons() if w.game_path == W1H))
    return session


def _rotation_of(matrix) -> tuple:
    return tuple(matrix[i] for i in (0, 1, 2, 4, 5, 6, 8, 9, 10))


def _close(a, b, tolerance=1e-5) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def _world_turn(matrix, axis: Vec3, degrees: float) -> tuple:
    """`matrix`'s rotation followed by a world turn, the way the ring promises."""

    turn = matrix_from(Quat.from_axis_angle(axis, degrees), Vec3())
    rows = [transform_point(Vec3(*_rotation_of(matrix)[i:i + 3]), turn) for i in (0, 3, 6)]
    return tuple(c for row in rows for c in (row.x, row.y, row.z))


@pytest.mark.parametrize("axis", [Vec3(1.0, 0.0, 0.0), Vec3(0.0, 1.0, 0.0),
                                  Vec3(0.3, -0.5, 0.8)])
def test_turning_the_items_own_point_turns_the_item_about_the_world_axis(axis) -> None:
    files = _files()
    session = _session(files)
    before = session.attachment_matrix(BACK, GRIP)
    edits = EditSession(files)

    local = session.world_axis_for_socket(GRIP, axis, attached_to=BACK)
    edits.rotate_by(W1H, GRIP, local, 25.0, item_side=True)
    after = session.with_edited_files(edits.current_files()).attachment_matrix(BACK, GRIP)

    assert _close(_rotation_of(after), _world_turn(before, axis, 25.0))
    # It turns about the point it hangs from: the grip stays on the back socket.
    grip = session.weapon.sockets[GRIP].translation
    spot = session.placed(BACK).world_position
    for matrix in (before, after):
        held = transform_point(grip, matrix)
        assert _close((held.x, held.y, held.z), (spot.x, spot.y, spot.z))


def test_the_unconverted_axis_turned_the_item_about_something_else() -> None:
    """Guards the test above: in this rig the old composition really is wrong."""

    files = _files()
    session = _session(files)
    before = session.attachment_matrix(BACK, GRIP)
    edits = EditSession(files)
    edits.rotate_by(W1H, GRIP, Vec3(0.0, 1.0, 0.0), 25.0)
    after = session.with_edited_files(edits.current_files()).attachment_matrix(BACK, GRIP)
    assert not _close(_rotation_of(after), _world_turn(before, Vec3(0.0, 1.0, 0.0), 25.0),
                      1e-3)


def test_turning_a_body_spot_still_turns_about_the_world_axis() -> None:
    files = _files()
    session = _session(files)
    axis = Vec3(0.0, 0.0, 1.0)
    before = session.placed(BACK).world_matrix
    edits = EditSession(files)
    edits.rotate_by(BODY, BACK, session.world_axis_for_socket(BACK, axis), 30.0)
    after = session.with_edited_files(edits.current_files()).placed(BACK).world_matrix
    assert _close(_rotation_of(after), _world_turn(before, axis, 30.0))


@pytest.mark.parametrize("name,path", [(GRIP, W1H), (BACK, BODY)])
def test_a_move_drag_moves_the_item_by_the_world_delta(name, path) -> None:
    files = _files()
    session = _session(files)
    delta = Vec3(0.04, -0.02, 0.03)
    before = translation_of(session.attachment_matrix(BACK, GRIP))
    edits = EditSession(files)
    local = session.world_delta_for_socket(name, delta, attached_to=BACK)
    edits.nudge(path, name, local.x, local.y, local.z)
    after = translation_of(
        session.with_edited_files(edits.current_files()).attachment_matrix(BACK, GRIP))
    moved = (after.x - before.x, after.y - before.y, after.z - before.z)
    assert _close(moved, (delta.x, delta.y, delta.z))


# ── the window: what a person clicks ────────────────────────────────

def _move_to_back(window, monkeypatch):
    """What a move to another spot does once its worker is done, with the result dialog stubbed."""

    from PySide6.QtWidgets import QMessageBox

    from tools.placement_studio import carry
    from tools.placement_studio.move_operation import MoveRequest, plan_move

    monkeypatch.setattr(QMessageBox, "exec", lambda box: 0)
    window._part_box.setCurrentIndex(window._part_box.findData("CD_MainWeapon_Sword_R"))
    unit, error = window._resolve_unit("CD_MainWeapon_Sword_R")
    assert unit is not None, error
    plan = plan_move(window._session, window._edits, MoveRequest(
        unit=unit, destination_socket=BACK,
        scope=carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY), orientation_reviewed=False,
    ))
    assert not plan.blocked
    window._apply_move_operation(plan, {})


def _with_rig(window) -> None:
    window._session.hierarchy = _rig()
    window._session._reposition()


def test_a_move_shows_the_item_put_away_and_fine_tune_acts_on_its_new_point(
        window, monkeypatch) -> None:
    assert window._mesh_role_box.currentData() == "held"
    _move_to_back(window, monkeypatch)
    assert window._mesh_role_box.currentData() == "stowed"
    assert window._selected_socket == GRIP
    assert window._adjust_target_box.currentData() == "item"
    for widget in (*window._euler, *window._position, *window._turn_buttons):
        assert widget.isEnabled()


def test_the_angle_arrows_turn_it_rather_than_waiting_for_enter(window, monkeypatch) -> None:
    _move_to_back(window, monkeypatch)
    before = window._edits.socket(W1H, GRIP).rotation
    window._euler[2].stepUp()
    after = window._edits.socket(W1H, GRIP).rotation
    assert after.angle_to(before) == pytest.approx(1.0, abs=0.05)
    assert after.to_euler_degrees()[2] == pytest.approx(window._euler[2].value(), abs=0.05)


def test_a_position_box_sets_its_own_axis_and_keeps_the_others_exact(window, monkeypatch) -> None:
    _move_to_back(window, monkeypatch)
    before = window._edits.socket(W1H, GRIP).translation
    # The boxes show the new point's own offset, not the previous point's.
    shown = [box.value() for box in window._position]
    assert shown == pytest.approx([before.x * 100, before.y * 100, before.z * 100], abs=0.05)
    window._position[0].setValue(window._position[0].value() + 3.0)
    after = window._edits.socket(W1H, GRIP).translation
    assert after.x == pytest.approx(before.x + 0.03, abs=1e-6)
    assert (after.y, after.z) == (before.y, before.z)


@pytest.mark.parametrize("button,axis_index,sign", [(0, 1, 1.0), (3, 0, -1.0), (5, 2, -1.0)])
def test_a_turn_button_turns_the_item_about_the_view_direction(
        window, monkeypatch, button, axis_index, sign) -> None:
    _move_to_back(window, monkeypatch)
    _with_rig(window)
    window._viewport._camera.yaw, window._viewport._camera.pitch = 35.0, -20.0
    before = window._session.attachment_matrix(BACK, GRIP)
    window._turn_buttons[button].click()
    after = window._session.attachment_matrix(BACK, GRIP)
    axis = window._viewport.view_axes()[axis_index]
    degrees = sign * float(window._angle_box.currentData())
    assert _close(_rotation_of(after), _world_turn(before, axis, degrees))


def test_a_move_drag_follows_the_pointer_on_a_turned_bone(window, monkeypatch) -> None:
    _move_to_back(window, monkeypatch)
    _with_rig(window)
    before = translation_of(window._session.attachment_matrix(BACK, GRIP))
    window._on_socket_dragged(GRIP, 0.02, 0.0, -0.04)
    after = translation_of(window._session.attachment_matrix(BACK, GRIP))
    assert _close((after.x - before.x, after.y - before.y, after.z - before.z),
                  (0.02, 0.0, -0.04))


def test_turn_by_stays_usable_outside_the_drag_modes(window) -> None:
    window._set_mode("off")
    assert window._angle_box.isEnabled()


# ── the view: slow drags ────────────────────────────────────────────

def _viewport():
    from PySide6.QtWidgets import QApplication

    from tools.placement_studio.model import Socket
    from tools.placement_studio.viewport import SkeletonViewport

    QApplication.instance() or QApplication([])
    hierarchy = _rig()
    view = SkeletonViewport()
    view.resize(800, 600)
    placed = hierarchy.place(Socket(name=BACK, parent_bone="Bip01 Spine2"))
    view.set_scene(hierarchy, [placed], {BACK: 1})
    view.set_selected(BACK)
    view.set_edit_mode("rotate")
    view.set_angle_snap(5.0)
    view._dragging_socket = BACK
    turned = []
    view.socket_rotated.connect(lambda _name, _x, _y, _z, degrees: turned.append(degrees))
    return view, turned


def test_a_slow_free_drag_still_turns() -> None:
    view, turned = _viewport()
    for _ in range(10):
        view._rotate_socket(2, 0)  # one degree per event, a fifth of the 5 degree step
    assert sum(turned) == pytest.approx(-10.0)


def test_a_slow_drag_across_an_edge_on_ring_still_turns(monkeypatch) -> None:
    from PySide6.QtCore import QPoint

    view, turned = _viewport()
    view._grabbed_axis = "Y"
    monkeypatch.setattr(view, "_ring_plane_hit", lambda *_a: None)
    monkeypatch.setattr(view, "_ring_screen_direction", lambda *_a: (1.0, 0.0))
    point = QPoint(400, 300)
    for _ in range(10):
        following = QPoint(point.x(), point.y() + 2)
        view._rotate_about_axis(point, following)
        point = following
    assert abs(sum(turned)) == pytest.approx(10.0)


# ── the view: which way a drag turns it, and what a drag refreshes ──

def _orbit_drag(view, dx: int, dy: int) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    start, end = QPointF(400, 300), QPointF(400 + dx, 300 + dy)
    view.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, start, start,
                                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    view.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, end, end,
                                    Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, end, end,
                                       Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def _near_side_moves(view, dx: int, dy: int) -> tuple:
    """How far, on screen, a point on the near side of the target moves for one drag."""

    camera = view._camera
    camera.target, camera.distance, camera.yaw, camera.pitch = Vec3(0, 1, 0), 3.0, 30.0, -12.0
    _right, _up, forward = camera.basis()
    near = Vec3(-forward.x * 0.3, 1 - forward.y * 0.3, -forward.z * 0.3)
    view._frame_key = None
    before = view._project(near)
    _orbit_drag(view, dx, dy)
    view._frame_key = None
    after = view._project(near)
    return after.x() - before.x(), after.y() - before.y()


def test_by_default_the_character_turns_the_way_the_pointer_moves() -> None:
    view, _turned = _viewport()
    view.set_edit_mode("off")
    across, _ = _near_side_moves(view, 10, 0)
    _, down = _near_side_moves(view, 0, 10)
    assert across > 0 and down > 0


def test_reverse_view_drag_moves_the_camera_with_the_pointer_instead() -> None:
    view, _turned = _viewport()
    view.set_edit_mode("off")
    view.set_orbit_follows_pointer(False)
    across, _ = _near_side_moves(view, 10, 0)
    _, down = _near_side_moves(view, 0, 10)
    assert across < 0 and down < 0


def test_the_reverse_view_drag_choice_is_remembered(window) -> None:
    assert not window._reverse_orbit.isChecked()
    assert window._viewport._orbit_follows_pointer
    window._reverse_orbit.setChecked(True)
    assert not window._viewport._orbit_follows_pointer
    assert window._mod_settings().value("placement_studio/reverse_view_drag", False, type=bool)


def test_a_drag_refreshes_the_view_at_once_and_the_panels_when_it_ends(window, monkeypatch) -> None:
    _move_to_back(window, monkeypatch)
    _with_rig(window)
    changes = window._mod_summary_button.text()
    before = translation_of(window._session.attachment_matrix(BACK, GRIP))
    window._on_socket_dragged(GRIP, 0.02, 0.0, 0.0)
    # The view and Fine-tune follow the drag straight away...
    after = translation_of(window._session.attachment_matrix(BACK, GRIP))
    assert after.x == pytest.approx(before.x + 0.02, abs=1e-6)
    assert window._position[0].value() == pytest.approx(
        window._edits.socket(W1H, GRIP).translation.x * 100, abs=0.05)
    # ...the list of changes waits for the drag to end.
    assert window._drag_settle_pending
    assert window._mod_summary_button.text() == changes
    window._viewport.drag_finished.emit()
    assert not window._drag_settle_pending
    assert window._mod_summary_button.text() != changes


def test_a_button_edit_still_refreshes_everything_at_once(window, monkeypatch) -> None:
    _move_to_back(window, monkeypatch)
    changes = window._mod_summary_button.text()
    window._nudge_buttons[1].click()
    assert not getattr(window, "_drag_settle_pending", False)
    assert window._mod_summary_button.text() != changes


def test_parsed_files_are_reused_without_sharing_what_callers_change() -> None:
    from tools.placement_studio import resolver as resolver_module

    files = _files()
    first, second = PlacementResolver(), PlacementResolver()
    first.add_files(files)
    hits = len(resolver_module._PARSED)
    second.add_files(files)
    assert len(resolver_module._PARSED) == hits  # nothing parsed twice
    weapon = next(w for w in first.weapons() if w.game_path == W1H)
    weapon.sockets.pop(GRIP)
    again = next(w for w in second.weapons() if w.game_path == W1H)
    assert GRIP in again.sockets
    # Different bytes are parsed afresh.
    changed = dict(files)
    changed[W1H] = files[W1H].replace(b"0.030000 -0.250000", b"0.040000 -0.250000")
    third = PlacementResolver()
    third.add_files(changed)
    moved = next(w for w in third.weapons() if w.game_path == W1H).sockets[GRIP]
    assert moved.translation.x == pytest.approx(0.04)


# ── the view: Alt and the right button turn the view in the edit modes ──

def _mouse(view, kind: str, x: float, y: float, *, button=None, held=None, alt=False) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    types = {"press": QMouseEvent.Type.MouseButtonPress, "move": QMouseEvent.Type.MouseMove,
             "release": QMouseEvent.Type.MouseButtonRelease}
    point = QPointF(x, y)
    event = QMouseEvent(types[kind], point, point, button or Qt.NoButton, held or Qt.NoButton,
                        Qt.AltModifier if alt else Qt.NoModifier)
    {"press": view.mousePressEvent, "move": view.mouseMoveEvent,
     "release": view.mouseReleaseEvent}[kind](event)


def _move_mode_view():
    view, _turned = _viewport()
    view.set_edit_mode("move")
    view.set_snap(0.0)
    moved, finished = [], []
    view.socket_dragged.connect(lambda *args: moved.append(args))
    view.drag_finished.connect(lambda: finished.append(True))
    return view, moved, finished


@pytest.mark.parametrize("alt,button_name", [(True, "LeftButton"), (False, "RightButton")])
def test_alt_drag_and_right_drag_turn_the_view_not_the_item(alt, button_name) -> None:
    from PySide6.QtCore import Qt

    view, moved, finished = _move_mode_view()
    button = getattr(Qt, button_name)
    yaw = view._camera.yaw
    _mouse(view, "press", 400, 300, button=button, held=button, alt=alt)
    _mouse(view, "move", 430, 300, held=button, alt=alt)
    _mouse(view, "release", 430, 300, button=button, alt=alt)
    assert moved == [] and finished == []
    assert view._camera.yaw != yaw


def test_alt_during_a_drag_pauses_the_edit_and_letting_go_carries_on() -> None:
    from PySide6.QtCore import Qt

    view, moved, finished = _move_mode_view()
    _mouse(view, "press", 400, 300, button=Qt.LeftButton, held=Qt.LeftButton)
    _mouse(view, "move", 410, 300, held=Qt.LeftButton)
    assert len(moved) == 1
    yaw = view._camera.yaw
    _mouse(view, "move", 440, 300, held=Qt.LeftButton, alt=True)
    assert len(moved) == 1 and view._camera.yaw != yaw
    _mouse(view, "move", 450, 300, held=Qt.LeftButton)
    assert len(moved) == 2
    _mouse(view, "release", 450, 300, button=Qt.LeftButton)
    assert finished == [True]


def test_alt_click_does_not_add_an_attach_point(monkeypatch) -> None:
    from PySide6.QtCore import Qt

    view, _moved, _finished = _move_mode_view()
    view.set_edit_mode("pick")
    monkeypatch.setattr(view, "pick_surface", lambda _point: Vec3(0.0, 1.0, 0.0))
    picked = []
    view.surface_picked.connect(lambda *args: picked.append(args))
    _mouse(view, "press", 400, 300, button=Qt.LeftButton, held=Qt.LeftButton, alt=True)
    assert picked == []
    _mouse(view, "release", 400, 300, button=Qt.LeftButton, alt=True)
    _mouse(view, "press", 400, 300, button=Qt.LeftButton, held=Qt.LeftButton)
    assert len(picked) == 1
