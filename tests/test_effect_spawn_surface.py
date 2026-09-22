"""Surface data, placement targets and exported spawn edits use the actual contracts."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.effect_spawn_surface import spawn_surface_geometry


def mesh():
    return SimpleNamespace(submeshes=[SimpleNamespace(
        vertices=[(0.,0.,0.), (1.,0.,0.), (0.,1.,0.)],
        normals=[(0.,0.,2.)] * 3, faces=[(0,1,2)],
    )])


def test_surface_keeps_triangle_order_and_normalized_normals():
    source = mesh()
    source.submeshes *= 2
    surface = spawn_surface_geometry(source)
    assert surface['faces'] == [(0,1,2), (3,4,5)]
    assert surface['normals'] == [(0.,0.,1.)] * 6
    assert surface['areas'] == [.5,.5]
    source.submeshes[0].normals = []
    assert spawn_surface_geometry(source)['normals'] == surface['normals']


def test_invalid_empty_and_cancelled_surfaces_cannot_become_origin_particles():
    source = mesh()
    source.submeshes[0].faces = [(0,1,3)]
    with pytest.raises(ValueError, match='indices'):
        spawn_surface_geometry(source)
    with pytest.raises(ValueError, match='no triangles'):
        spawn_surface_geometry(None)
    with pytest.raises(RunCancelled):
        spawn_surface_geometry(mesh(), lambda: (_ for _ in ()).throw(RunCancelled()))


def test_package_carries_item_and_real_character_but_never_the_stand_in(tmp_path):
    from tests.test_effect_placement_preview import _blade, _fire_preview, _rust_package_state
    from cdmw.services.effect_placement_preview import build_effect_placement_package, character_reference_mesh
    source = _fire_preview()
    source = replace(source, emitters=tuple(replace(e, spawn_volume_type=6) for e in source.emitters))
    for label, character in (('none', None), ('stand-in', character_reference_mesh()), ('real', _blade())):
        package = build_effect_placement_package(_blade(), (-1,-1,-1), (1,1,1),
            output_root=tmp_path / label, effect_preview=source, character_mesh=character)
        _, scene = _rust_package_state(package)
        surfaces = scene['effects_overlay']['spawn_surfaces']
        assert surfaces['item']['faces']
        assert ('character' in surfaces) == (label == 'real')
        assert len(surfaces['item']['faces']) == len(_blade().submeshes[0].faces)
