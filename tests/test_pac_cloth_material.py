"""Material-driven initial values and the decoded underwater guide blend."""

from dataclasses import replace
import hashlib
import json
import math
import struct

import pytest

from cdmw.core.pbd_cloth import parse_pbd_material_settings
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_particle_initialization
from cdmw.modding.pac_cloth_skinning import blend_render_cloth_matrix, guide_runtime_blend_factor
from tests.test_pac_cloth_guides import guide_fixture
from tests.test_pac_cloth_skinning import frame, point, record
from tools.pac_cloth_guide_study import inspect_pac, main


def test_guide_material_defaults_are_not_inferred_from_a_clothing_filename():
    settings = parse_pbd_material_settings('<SimulationParameters/>', material_name='ClothDress')
    assert settings.mass == 1
    assert settings.use_vertex_alpha_position_blending is True
    assert settings.use_rotation_correction is False
    assert settings.underwater_guide_mesh_vertex_weight_coefficient == 1


@pytest.mark.parametrize('body, expected', [
    ('<SimulationMode>cloth</SimulationMode>', True),
    ('<SimulationMode>spline</SimulationMode>', False),
    ('<UseRotationCorrection>0</UseRotationCorrection><SimulationMode>cloth</SimulationMode>', True),
    ('<UseRotationCorrection>1</UseRotationCorrection><SimulationMode>spline</SimulationMode>', False),
    ('<SimulationMode>cloth</SimulationMode><UseRotationCorrection>0</UseRotationCorrection>', False),
    ('<SimulationMode>spline</SimulationMode><UseRotationCorrection>1</UseRotationCorrection>', True),
])
def test_rotation_correction_obeys_mode_resets_and_document_order(body, expected):
    settings = parse_pbd_material_settings('<SimulationParameters>' + body + '</SimulationParameters>')
    assert settings.use_rotation_correction is expected


@pytest.mark.parametrize('attached_first', [False, True])
def test_attached_cloth_does_not_overwrite_parent_guide_options(attached_first):
    parent = ('<SimulationMode>spline</SimulationMode><Mass>4</Mass>'
              '<UseVertexAlphaPositionBlending>0</UseVertexAlphaPositionBlending>'
              '<UnderWaterGuideMeshVertexWeightCoefficient>0.3</UnderWaterGuideMeshVertexWeightCoefficient>')
    child = ('<AttachedCloth><SimulationMode>cloth</SimulationMode><Mass>8</Mass>'
             '<UseVertexAlphaPositionBlending>1</UseVertexAlphaPositionBlending>'
             '<UnderWaterGuideMeshVertexWeightCoefficient>0.7</UnderWaterGuideMeshVertexWeightCoefficient>'
             '</AttachedCloth>')
    settings = parse_pbd_material_settings('<SimulationParameters>' +
                                           (child + parent if attached_first else parent + child) + '</SimulationParameters>')
    assert settings.mass == 4
    assert settings.use_vertex_alpha_position_blending is False
    assert settings.use_rotation_correction is False
    assert settings.underwater_guide_mesh_vertex_weight_coefficient == .3


@pytest.mark.parametrize('mass, inverse', [(4, .25), (0, 1.), (-5, 1.)])
@pytest.mark.parametrize('alpha', [False, True])
def test_supplied_material_initializes_mass_and_blend_without_making_fractional_pins(mass, inverse, alpha):
    guides = replace(decode_pac_cloth_guides(guide_fixture()[0]), channel_b=bytes((0, 127, 255)))
    result = inspect_guide_particle_initialization(guides, material_mass=mass, use_vertex_alpha_position_blending=alpha)
    supplied = result['supplied_material_initialization']
    assert supplied['inverse_masses'] == [inverse, inverse, 0]
    assert supplied['position_blends'] == ([0, .498046875, 1] if alpha else [0, 0, 1])
    assert result['fixed_vertex_indices'] == [2]


@pytest.mark.parametrize('kwargs', [
    {'material_mass': 1}, {'use_vertex_alpha_position_blending': False},
    {'material_mass': math.nan, 'use_vertex_alpha_position_blending': True},
    {'material_mass': 1, 'use_vertex_alpha_position_blending': 1},
])
def test_partial_or_invalid_material_context_is_not_silently_inferred(kwargs):
    guides = decode_pac_cloth_guides(guide_fixture()[0])
    with pytest.raises(ValueError, match='Mass.*flag'):
        inspect_guide_particle_initialization(guides, **kwargs)


@pytest.mark.parametrize('inverse_mass, flags, coefficient, expected', [
    (.25, 0, .3, 1.), (.25, 0x80, .3, .300048828125),
    (0., 0x80, .3, 1.), (.25, 0x800080, .3, 1.),
    (.25, 0x180, 1/3, .333251953125),
    (.25, 0x80, -5, 0.), (.25, 0x80, 5, 1.),
])
def test_underwater_factor_uses_particle_flags_mass_half_rounding_and_saturation(inverse_mass, flags, coefficient, expected):
    assert guide_runtime_blend_factor(inverse_mass=inverse_mass, particle_flags=flags,
                                     underwater_coefficient=coefficient) == expected


def test_underwater_factor_changes_render_blend_but_override_does_not_force_full_skinning():
    factor = guide_runtime_blend_factor(inverse_mass=1, particle_flags=0x80, underwater_coefficient=0)
    matrix = blend_render_cloth_matrix(record(21), 0, skeletal_matrix=frame((20, 0, 0)),
                                       guide_matrices=(frame((5, 0, 0), factor),))
    assert point(matrix, (1, 0, 0)) == pytest.approx((6, 0, 0))
    factor = guide_runtime_blend_factor(inverse_mass=1, particle_flags=0x800080, underwater_coefficient=0)
    matrix = blend_render_cloth_matrix(record(21), 0, skeletal_matrix=frame((20, 0, 0)),
                                       guide_matrices=(frame((5, 0, 0), factor),))
    assert point(matrix, (1, 0, 0)) == pytest.approx((11, 0, 0))  # Authored 1/3 blend, not full skinning at 21.


def test_underwater_factor_preserves_the_cpu_packer_subnormal_rounding_edge():
    coefficient = struct.unpack('<f', struct.pack('<I', 0x33000001))[0]
    # Just above halfway to the smallest IEEE half subnormal. The game's
    # preliminary right shift discards that extra bit and rounds the tie to 0.
    assert struct.unpack('<e', struct.pack('<e', coefficient))[0] == 2**-24
    assert guide_runtime_blend_factor(inverse_mass=1, particle_flags=0x80,
                                     underwater_coefficient=coefficient) == 0


def test_underwater_factor_does_not_invent_a_result_for_nonfinite_packed_data():
    with pytest.raises(ValueError, match='non-finite half'):
        guide_runtime_blend_factor(inverse_mass=1, particle_flags=0x80, underwater_coefficient=1e20)
    # This branch never consumes the packed value.
    assert guide_runtime_blend_factor(inverse_mass=1, particle_flags=0,
                                     underwater_coefficient=1e20) == 1


def test_inspector_cli_uses_explicit_profile_and_records_its_hash(tmp_path, capsys):
    data, offsets = guide_fixture()
    data = bytearray(data)
    data[offsets['channel_b']:offsets['channel_b'] + 3] = bytes((0, 127, 255))
    pac = tmp_path / 'owned.pac'
    pac.write_bytes(data)
    profile = tmp_path / 'owned.xml'
    profile.write_text('<SimulationParameters><SimulationMode>cloth</SimulationMode><Mass>4</Mass>'
                       '<UseVertexAlphaPositionBlending>0</UseVertexAlphaPositionBlending>'
                       '<UnderWaterGuideMeshVertexWeightCoefficient>0.3</UnderWaterGuideMeshVertexWeightCoefficient>'
                       '</SimulationParameters>', encoding='utf-8')
    before = profile.read_bytes()
    assert main([str(pac), '--material', str(profile)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['material_profile']['sha256'] == hashlib.sha256(before).hexdigest()
    assert report['material_profile']['path'] == str(profile)
    asset = report['assets'][0]
    values = asset['particle_initialization']['supplied_material_initialization']
    assert values['inverse_masses'] == [.25, .25, 0]
    assert values['position_blends'] == [0, 0, 1]
    assert asset['supplied_material']['use_rotation_correction'] is True
    assert asset['supplied_material']['dynamic_underwater_guide_matrix_factor'] == .300048828125
    assert 'not proof of the active in-game material' in asset['supplied_material']['limitations']
    assert profile.read_bytes() == before and pac.read_bytes() == data
    assert 'supplied_material' not in inspect_pac(data)


def test_malformed_profile_does_not_become_successful_default_initialization(tmp_path, capsys):
    profile = tmp_path / 'broken.xml'
    profile.write_text('<SimulationParameters><Mass>4</Mass>', encoding='utf-8')
    with pytest.raises(SystemExit) as failure:
        main([str(tmp_path / 'unread.pac'), '--material', str(profile)])
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert 'malformed' in output.err and not output.out
