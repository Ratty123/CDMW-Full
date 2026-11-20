"""A template whose stock material file names a texture the game does not ship."""
from dataclasses import replace
from uuid import uuid4

import pytest

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.spec import ModelSource
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package, recipe_plan
from cdmw.services.independent_item_references import audit_references
from cdmw.services.new_item_planning import ModelFiles
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import imported_game
from tests.test_new_item_service import PAC_XML, imported_pac

# Real examples from 1.0.0.3732: a missing slash, and an empty file name.
DANGLING = ('character/texturecd_phw_00_sho_belt_00_0161_disp.dds', 'character/texture/.dds')


@pytest.mark.parametrize('dangling', DANGLING)
def test_a_table_only_item_on_such_a_template_can_become_a_package(tmp_path, dangling):
    service, snapshot = imported_game(tmp_path, dangling_texture=dangling)
    assert not snapshot.has_entry(dangling)
    plan = service.plan(shop_spec('StockDangling'), snapshot, capture_independent=True)
    notes = plan.reference_assessment.unresolved
    assert any(dangling in note and 'does not ship' in note for note in notes)
    assert any(dangling in warning for warning in plan.warnings)
    package = from_plan(plan, uuid4().hex)
    assert dangling not in package.dependencies
    again = read_package(package_bytes(package))
    replanned = recipe_plan(again, snapshot)
    assert any(dangling in note for note in replanned.plan.reference_assessment.unresolved)


def test_an_imported_model_keeps_the_dangling_reference_as_a_note(tmp_path):
    dangling = DANGLING[0]
    service, snapshot = imported_game(tmp_path, dangling_texture=dangling)
    choice = replace(shop_spec('StockDanglingModel'), model_source=ModelSource.IMPORTED)
    plan = service.plan(choice, snapshot, model=ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}),
                        capture_independent=True)
    assert any(dangling in note and 'does not ship' in note for note in plan.reference_assessment.unresolved)
    assert not any(request.path.lower() == dangling for request in plan.additions)


def test_a_missing_reference_the_plan_itself_adds_still_refuses(tmp_path):
    service, snapshot = imported_game(tmp_path)
    choice = replace(shop_spec('OwnDangling'), model_source=ModelSource.IMPORTED)
    plan = service.plan(choice, snapshot, model=ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}),
                        capture_independent=True)
    missing = 'character/texture/1_pc/not_in_the_game_n.dds'
    owned_xml = next(request for request in plan.additions if request.path.lower().endswith('.pac_xml'))
    text = bytes(owned_xml.payload_data).decode('utf-8')
    path = next(part.split('"')[0] for part in text.split('_path="')[1:] if part.split('"')[0].endswith('.dds'))
    changed = replace(owned_xml, payload_data=text.replace(path, missing).encode('utf-8'))
    edited = replace(plan, additions=tuple(changed if request is owned_xml else request for request in plan.additions))
    with pytest.raises(IndependentItemError, match='Unresolved item dependency'):
        audit_references(edited, snapshot)
