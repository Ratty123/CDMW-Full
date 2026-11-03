"""PAC/sidecar/PAB import discovers stock DDS through the actual loader."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.services.dmm_character_mods import scan_character_library
from cdmw.services.dmm_character_models import InstalledCharacterModel
from cdmw.services.new_item_variants import xml_path
from cdmw.ui.new_item.installed_model_import import load_installed_model
from tests.test_dmm_character_mods import installed, write
from tests.test_mesh_replacement_imported_skinning import editor
from tests.test_mesh_editor_pab_resolution import _pab
from cdmw.services.new_item_materials import encode_emissive_solid
from tests.test_pac_xml_standard_material import HEAD, TAIL, texture, wrapper


@pytest.mark.parametrize('missing', (False, True))
def test_loader_keeps_resolved_joint_identity_and_discovers_declared_game_texture(installed, editor, missing):
    install, mods, model, _ = installed
    service, sid, _ = editor
    captured = service.capture_export_snapshot(sid)
    write(mods, 'fit/0009/' + model, captured.original_data)
    hashes = tuple(bone.name_hash for bone in captured.mesh.interchange_skeleton.bones)
    write(mods, 'fit/0009/' + str(Path(model).with_suffix('.pab')).replace('\\', '/'), _pab(hashes))
    texture_path = 'character/texture/owned/shared.dds'
    material = HEAD + ''.join(wrapper(part.name, 'SkinnedMeshStandard', texture('_baseColorTexture', '5', texture_path, 0), 20+i)
                              for i, part in enumerate(captured.mesh.submeshes)) + TAIL
    write(mods, 'fit/0009/' + xml_path(model), material)
    reads = []
    pixels = encode_emissive_solid()
    def payload(path):
        reads.append(path)
        if missing or path != texture_path:
            raise KeyError(path)
        return pixels
    snapshot = SimpleNamespace(payload=payload, entry_paths_with_extensions=lambda _ext: ())
    request = InstalledCharacterModel(scan_character_library(str(install)), 'fit', model)
    if missing:
        with pytest.raises(ValueError, match='Missing required texture: character/texture/owned/shared.dds'):
            load_installed_model(request, snapshot)
        return
    source = load_installed_model(request, snapshot)
    root = source.extract_root
    try:
        assert texture_path in reads  # It was discovered, not manually passed to the importer.
        assert source.texture_count > 0, (source.scene.discovered_texture_files, source.notes,
                                          [(p.name, p.material) for p in source.scene.mesh.submeshes])
        assert all(part.interchange_skin for part in source.scene.mesh.submeshes)
        for part in source.scene.mesh.submeshes:
            skin = part.interchange_skin
            assert all(0 <= joint < len(skin['joints']) for row in part.bone_indices for joint in row)
            assert {skin['nodes'][joint]['name'] for joint in skin['joints']} == {f'Bone{i}' for i in range(8)}
        assert (root / 'files' / texture_path).read_bytes() == pixels
        source.dmm_source_revision.validate()
        # Loading is not acceptance: run the same rig preflight as the worker.
        from cdmw.modding.skeleton_parser import parse_pab
        from cdmw.services.mesh_skinning_preflight import preflight_imported_skin
        rig = parse_pab(_pab(hashes), 'owned.pab')
        mapped, reports = preflight_imported_skin(source.raw_import_mesh, captured.original_data, rig, model)
        assert reports and all(report.policy == 'preserve' for report in reports)
        for actual, expected in zip(mapped.submeshes, captured.mesh.submeshes, strict=True):
            assert actual.bone_indices == expected.bone_indices
            for actual_row, expected_row in zip(actual.bone_weights, expected.bone_weights, strict=True):
                assert actual_row == pytest.approx(expected_row)
        from dataclasses import replace
        foreign = replace(rig, bones=[replace(bone, name='foreign_' + bone.name) for bone in rig.bones])
        with pytest.raises(ValueError, match='Missing equipment palette bones'):
            preflight_imported_skin(source.raw_import_mesh, captured.original_data, foreign, model)
    finally:
        source.cleanup()
    assert not root.exists()
