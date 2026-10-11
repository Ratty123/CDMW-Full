"""Snug fitting through the resident native protocol, without character rules."""
from contextlib import contextmanager
from copy import deepcopy
import math

import pytest

from tests.test_native_mesh_editor_morph_refit import (
    ParsedMesh, _command, _open, _part, _refit_tube_part, _snapshot, _state, mesh_native_core,
)


def _mesh(*parts):
    return ParsedMesh(path="snug-fit.pac", format="pac", submeshes=list(parts),
                      total_vertices=sum(len(p.vertices) for p in parts),
                      total_faces=sum(len(p.faces) for p in parts))


def _sleeve(offset=0.0, segments=32, radius=.1):
    return _refit_tube_part("sleeve", radius, offset, (.1, .15, .2, .25, .3, .35, .4), segments)


def _arm(radius=.06):
    return _refit_tube_part("body", radius, 0., (0., .1, .2, .3, .4, .5), 64, True)


@contextmanager
def _bound(mesh):
    session = _open(mesh)
    try:
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
            "definitions": [], "fields": [],
        }})
        _command(session, "morph_set_driver", {"submesh_indices": [0]})
        _command(session, "morph_bind", {"garment_submesh_indices": list(range(1, len(mesh.submeshes)))})
        yield session
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)


def _fit(session, garments=(1,), tightness=100., **settings):
    return _command(session, "morph_configure_refit", {
        "garment_submesh_indices": list(garments), "clearance_percent": .1,
        "tightness_percent": tightness, **settings,
    })


@pytest.mark.parametrize("offset", (0., .06))
@pytest.mark.parametrize("body_radius", (.06, .09))
def test_snug_fit_contracts_loose_side_and_clears_the_other(offset, body_radius):
    mesh = _mesh(_arm(body_radius), _sleeve(offset, radius=.13))
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
        for ring in range(7):
            points = fitted.submeshes[1].vertices[ring*32:(ring+1)*32]
            assert max(math.hypot(x, z) for x, _, z in points) < body_radius + .02
            winding = sum(math.atan2(a[0]*b[2]-a[2]*b[0], a[0]*b[0]+a[2]*b[2])
                          for a, b in zip(points, points[1:]+points[:1]))
            assert winding == pytest.approx(2*math.pi)
            for a, b in zip(points, points[1:]+points[:1]):
                assert math.hypot((a[0]+b[0])/2, (a[2]+b[2])/2) >= body_radius
        assert fitted.submeshes[0].vertices == mesh.submeshes[0].vertices
        for attr in ("faces", "uvs", "bone_weights", "bone_indices", "name", "material"):
            assert getattr(fitted.submeshes[1], attr) == getattr(mesh.submeshes[1], attr)


def test_tessellation_taper_ellipse_and_folded_opening():
    radii = []
    for segments in (24, 48):
        body, garment = _arm(), _sleeve(segments=segments)
        body.vertices = [(x*(.6+y), y, z*(1.1-.4*y)) for x, y, z in body.vertices]
        garment.vertices = [(x*(1.15 if y == .1 else 1), y, z*(1.15 if y == .1 else 1))
                            for x, y, z in garment.vertices]
        mesh = _mesh(body, garment)
        with _bound(mesh) as session:
            _fit(session)
            positions = _snapshot(mesh, session).submeshes[1].vertices
        # The opening remains flared; lower and upper sections inherit body taper.
        rings = [positions[i*segments:(i+1)*segments] for i in range(7)]
        width = [max(v[0] for v in ring)-min(v[0] for v in ring) for ring in rings]
        depth = [max(v[2] for v in ring)-min(v[2] for v in ring) for ring in rings]
        assert width[0] > width[1] + .012
        assert width[5] > width[1] + .01
        assert depth[3] > width[3] + .008
        radii.append((width[3], depth[3]))
    assert radii[0] == pytest.approx(radii[1], abs=.004)


def test_layers_material_seams_and_protection_are_retained():
    sleeve = _sleeve()
    first = _part("front", sleeve.vertices, sleeve.faces[:192], material="front", texture="")
    second = _part("back", sleeve.vertices, sleeve.faces[192:], material="back", texture="")
    # Shared vertices are intentionally duplicated across material Parts.
    outer = _sleeve(radius=.11)
    mesh = _mesh(_arm(), first, second, outer)
    with _bound(mesh) as session:
        _fit(session, (1, 2, 3), vertex_masks=[{
            "submesh_index": 1, "vertex_indices": list(range(1, len(sleeve.vertices))),
            "weights": [1.]*(len(sleeve.vertices)-1),
        }])
        fitted = _snapshot(mesh, session)
        assert fitted.submeshes[1].vertices == fitted.submeshes[2].vertices
        assert fitted.submeshes[1].vertices[0] == sleeve.vertices[0]
        for a, b in zip(fitted.submeshes[1].vertices[64:160], fitted.submeshes[3].vertices[64:160]):
            assert math.hypot(b[0], b[2])-math.hypot(a[0], a[2]) > .005


def test_layers_starting_inside_a_larger_body_keep_their_spacing():
    mesh = _mesh(_arm(.08),_sleeve(radius=.06),_sleeve(radius=.07))
    with _bound(mesh) as session:
        _fit(session,(1,2))
        fitted = _snapshot(mesh,session)
        for inner,outer in zip(fitted.submeshes[1].vertices,fitted.submeshes[2].vertices):
            assert math.hypot(inner[0],inner[2]) > .08
            assert math.hypot(outer[0],outer[2])-math.hypot(inner[0],inner[2]) > .005


def test_repeat_percentage_reset_bake_and_history_are_neutral_based():
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        _fit(session, tightness=0.)
        original = _snapshot(mesh, session).submeshes[1].vertices
        assert original == mesh.submeshes[1].vertices
        _fit(session)
        full = _snapshot(mesh, session).submeshes[1].vertices
        _fit(session)
        assert _snapshot(mesh, session).submeshes[1].vertices == full
        _fit(session, tightness=50.)
        half = _snapshot(mesh, session).submeshes[1].vertices
        for a, b, c in zip(original, full, half):
            assert c == pytest.approx(tuple((x+y)/2 for x, y in zip(a, b)), abs=3e-4)
        _command(session, "morph_reset")
        assert _snapshot(mesh, session).submeshes[1].vertices == original
        assert _state(session)["refit"]["garment_settings"][0]["tightness_percent"] == 0.
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert _snapshot(mesh, session).submeshes[1].vertices == half
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        _fit(session)
        _command(session, "morph_bake")
        assert _snapshot(mesh, session).submeshes[1].vertices == full
        assert _state(session)["refit"]["garment_settings"][0]["tightness_percent"] == 0.
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert _state(session)["refit"]["garment_settings"][0]["tightness_percent"] == 100.
        assert _snapshot(mesh, session).submeshes[1].vertices == full
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        _command(session, "morph_reset")
        assert _snapshot(mesh, session).submeshes[1].vertices == full


def test_rigid_components_tighten_independently_of_follow_intensity():
    plate = _part("plate", [(x, y, .13) for x, y in ((-.01,.2),(.01,.2),(.01,.3),(-.01,.3))],
                  [(0,1,2),(0,2,3)], material="plate", texture="")
    mesh = _mesh(_arm(), plate)
    with _bound(mesh) as session:
        _fit(session, mode="rigid_component", intensity_percent=0.)
        fitted = _snapshot(mesh, session).submeshes[1].vertices
        assert max(v[2] for v in fitted) < .07
        for a in range(4):
            for b in range(4):
                assert math.dist(fitted[a], fitted[b]) == pytest.approx(math.dist(plate.vertices[a], plate.vertices[b]), abs=1e-7)


def test_selected_fit_keeps_the_seam_with_an_inactive_material_part():
    sleeve = _sleeve()
    parts = []
    for positive in (True,False):
        faces = [f for f in sleeve.faces if (sum(sleeve.vertices[i][0] for i in f)>=0) == positive]
        indices = sorted({i for f in faces for i in f})
        mapping = {v:i for i,v in enumerate(indices)}
        parts.append(_part(str(positive),[sleeve.vertices[i] for i in indices],
                           [tuple(mapping[i] for i in f) for f in faces], material="cloth",texture=""))
    shared = set(parts[0].vertices)&set(parts[1].vertices)
    assert shared
    mesh = _mesh(_arm(),*parts)
    with _bound(mesh) as session:
        _fit(session, (1,))
        fitted = _snapshot(mesh,session)
        assert fitted.submeshes[2].vertices == parts[1].vertices
        assert fitted.submeshes[1].vertices != parts[0].vertices
        for i,point in enumerate(parts[0].vertices):
            if point in shared:
                assert fitted.submeshes[1].vertices[i] == pytest.approx(point,abs=1e-8)


@pytest.mark.parametrize("tightness", (0., 100.))
def test_body_slider_following_remains_correct(tightness):
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        # A translation morph makes the body-following contract measurable
        # independently of changes in silhouette or signed clearance.
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a"*64,
            "definitions": [{"definition_id":"move", "label":"Move", "min_percent":0., "max_percent":100., "default_percent":0.}],
            "fields": [{"definition_id":"move", "submesh_index":0,
                        "vertex_indices":list(range(len(mesh.submeshes[0].vertices))),
                        "deltas":[[0., .03, 0.]]*len(mesh.submeshes[0].vertices)}],
        }})
        _fit(session, tightness=tightness)
        before = _snapshot(mesh, session)
        _command(session, "morph_change", {"definition_id":"move", "value":100., "phase":"end", "change_id":"move-fit"})
        after = _snapshot(mesh, session)
        for a, b in zip(before.submeshes[1].vertices, after.submeshes[1].vertices):
            assert b == pytest.approx((a[0],a[1]+.03,a[2]), abs=1e-6)


def test_unreliable_fit_fails_without_partial_settings_or_geometry():
    garment = _sleeve()
    garment.vertices = [(x+3.,y,z) for x,y,z in garment.vertices]
    mesh = _mesh(_arm(), _sleeve(), garment)
    with _bound(mesh) as session:
        before = _state(session)
        report = mesh_native_core.native_mesh_editor_session_command("morph_configure_refit", session, {
            "garment_submesh_indices": [1,2], "tightness_percent": 100., "clearance_percent": .1,
        })
        assert report is None
        assert "Part 2" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)["refit"] == before["refit"]
        assert _snapshot(mesh, session).submeshes[1].vertices == mesh.submeshes[1].vertices


@pytest.mark.parametrize("command", ("morph_change", "morph_apply_preset"))
def test_failed_body_change_with_active_fit_is_atomic(command):
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        _command(session, "morph_upload", {"profile": {
            "profile_id":"fit", "name":"Fit", "topology_fingerprint":"a"*64,
            "definitions":[{"definition_id":"move", "label":"Move", "min_percent":0., "max_percent":100., "default_percent":0.}],
            "fields":[{"definition_id":"move", "submesh_index":0,
                       "vertex_indices":list(range(len(mesh.submeshes[0].vertices))),
                       "deltas":[[.08,0.,0.]]*len(mesh.submeshes[0].vertices)}],
        }})
        _fit(session, vertex_masks=[{"submesh_index":1,"vertex_indices":[],"weights":[]}])
        before = _state(session)
        positions = _snapshot(mesh, session)
        arguments = ({"definition_id":"move", "value":100., "phase":"end", "change_id":"blocked"}
                     if command == "morph_change" else {"values":{"move":100.}, "preset_id":"blocked"})
        assert mesh_native_core.native_mesh_editor_session_command(command, session, arguments) is None
        assert "Part 1" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session) == before
        after = _snapshot(mesh, session)
        assert [p.vertices for p in after.submeshes] == [p.vertices for p in positions.submeshes]


def test_rigid_fit_checks_face_interior_and_rejects_a_pinned_collision():
    plate = _part("plate", [(x,y,.05) for x,y in ((-.08,.2),(.08,.2),(.08,.3),(-.08,.3))],
                  [(0,1,2),(0,2,3)], material="plate", texture="")
    mesh = _mesh(_arm(), plate)
    with _bound(mesh) as session:
        _fit(session, mode="rigid_component", intensity_percent=0.)
        fitted = _snapshot(mesh, session).submeshes[1].vertices
        assert sum(p[2] for p in fitted)/4 > .06
        assert math.dist(fitted[0],fitted[2]) == pytest.approx(math.dist(plate.vertices[0],plate.vertices[2]),abs=1e-7)
        _command(session,"morph_reset")
        before = _state(session)
        assert mesh_native_core.native_mesh_editor_session_command("morph_configure_refit", session, {
            "garment_submesh_indices":[1], "mode":"rigid_component", "tightness_percent":100.,
            "clearance_percent":.1, "vertex_masks":[{"submesh_index":1,"vertex_indices":[],"weights":[]}],
        }) is None
        assert "rigid component cannot clear" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)==before


def test_post_fit_correction_cannot_publish_a_body_intersection():
    mesh = _mesh(_arm(),_sleeve())
    with _bound(mesh) as session:
        _command(session,"morph_upload",{"profile":{
            "profile_id":"fit","name":"Fit","topology_fingerprint":"a"*64,
            "definitions":[{"definition_id":"correct","label":"Correct","min_percent":0.,"max_percent":100.,"default_percent":0.}],
            "fields":[{"definition_id":"correct","stage":"post_refit","submesh_index":1,
                       "vertex_indices":list(range(len(mesh.submeshes[1].vertices))),
                       "deltas":[[0.,0.,.05]]*len(mesh.submeshes[1].vertices)}],
        }})
        _fit(session)
        before = _state(session)
        positions = _snapshot(mesh,session).submeshes[1].vertices
        assert mesh_native_core.native_mesh_editor_session_command("morph_change",session,{
            "definition_id":"correct","value":100.,"phase":"end","change_id":"blocked-correction",
        }) is None
        assert "Part 1" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)==before
        assert _snapshot(mesh,session).submeshes[1].vertices==positions


def test_post_fit_correction_cannot_stretch_a_rigid_component():
    plate = _part("plate",[(x,y,.13) for x,y in ((-.01,.2),(.01,.2),(.01,.3),(-.01,.3))],
                  [(0,1,2),(0,2,3)],material="plate",texture="")
    mesh = _mesh(_arm(),plate)
    with _bound(mesh) as session:
        _command(session,"morph_upload",{"profile":{
            "profile_id":"fit","name":"Fit","topology_fingerprint":"a"*64,
            "definitions":[{"definition_id":"stretch","label":"Stretch","min_percent":0.,"max_percent":100.,"default_percent":0.}],
            "fields":[{"definition_id":"stretch","stage":"post_refit","submesh_index":1,
                       "vertex_indices":list(range(4)),"deltas":[[x,0.,0.] for x,_,_ in plate.vertices]}],
        }})
        _fit(session,mode="rigid_component")
        before=_state(session)
        assert mesh_native_core.native_mesh_editor_session_command("morph_change",session,{
            "definition_id":"stretch","value":100.,"phase":"end","change_id":"blocked-stretch",
        }) is None
        assert "rigid component dimensions" in mesh_native_core.last_native_mesh_core_job_error()
        assert _state(session)==before


def test_native_snapshot_v2_replacement_and_v1_defaults():
    import hashlib
    import json
    from pathlib import Path
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        _fit(session, tightness=73.)
        fitted = _snapshot(mesh, session)
        descriptor = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(session)
        assert descriptor and descriptor["version"] == 2
        target = _open(fitted)
        try:
            assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, descriptor)
            assert _state(target)["refit"]["garment_settings"][0]["tightness_percent"] == 73.
            # A genuine v1 document has no tightness field. Its geometry is retained.
            path = Path(descriptor["path"])
            document = json.loads(path.read_text(encoding="utf-8"))
            document["version"] = 1
            for item in document["runtime"]["refit"]["garment_settings"]:
                item.pop("tightness_percent")
            document["retained_bytes"] = len(json.dumps(document["runtime"]).encode())
            raw = json.dumps(document).encode()
            path.write_bytes(raw)
            legacy = dict(descriptor, version=1, sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw),
                          retained_bytes=document["retained_bytes"])
            assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(target, legacy)
            assert _state(target)["refit"]["garment_settings"][0]["tightness_percent"] == 0.
            descriptor = legacy
        finally:
            mesh_native_core.close_native_mesh_editor_session(target)
            mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor)
