"""Drafts & Mods lists Create New Item's .cdmw packages and continues them in the studio."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import fields, replace
import json
import time

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh.emission import GlowAnimation
from cdmw.domain.new_item.authoring import SocketSlot
from cdmw.domain.new_item.spec import IconSource, ItemGroupsChoice, MaterialRoute, PlacementKind, StatEdit
from cdmw.domain.textures.transparency_mask import TransparencyMask
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.services import independent_item_package as packages
from cdmw.services.item_package_saved_work import (
    ITEM_DRAFT_NAME,
    add_item_package_file,
    read_item_package_index,
    register_item_package,
)
from cdmw.services.mesh_saved_work_service import (
    KIND_ITEM_PACKAGE,
    STATUS_PACKAGE_FOUND,
    STATUS_PACKAGE_MISSING,
    list_saved_work,
    remove_built_mod_from_list,
    saved_work_status,
    update_saved_work_details,
)
from cdmw.ui.new_item.continue_launch import prepare_item_package_launch
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.draft_file import DraftFileError, decode_draft, encode_draft
from cdmw.ui.new_item.state import NewItemDraft, draft_from_spec, grid_values_from_edits, spec_from_draft
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import setup_game


def _draft():
    mask = TransparencyMask(2, 1, b'\x00\xff')
    return NewItemDraft(
        template_key=7, internal_name='Blade', display_names={'eng': 'Blade', 'deu': 'Klinge'},
        material_route=MaterialRoute.BUILDER, glow_parts=('blade',), glow_animation=GlowAnimation(),
        icon=IconSource.GENERATED, icon_source_path='C:/icons/blade.png',
        grid_values={(0, 1): 40, (2, 0): None}, extra_stat_keys=[12], price_values={5: 100},
        placement_kind=PlacementKind.SWAP, store_name='Store_Camp_Equipment', stock_index=3,
        item_groups=ItemGroupsChoice.EXPLICIT, explicit_item_groups=(4, 9), socket_items=[1, 2],
        socket_slots=(SocketSlot(material_key=11, amount=2),), effect_offset=(0.0, 1.5, 0.0),
        translucency=TranslucencyChoice(parts=('veil',), masks=(('veil', mask),)),
        authoring_errors={'stats': 'not saved'}, independent_identity='a' * 32,
    )


def test_draft_file_round_trips_every_field_and_drops_session_errors():
    draft = _draft()
    restored = decode_draft(encode_draft(draft))
    for field in fields(NewItemDraft):
        if field.name != 'authoring_errors':
            assert getattr(restored, field.name) == getattr(draft, field.name), field.name
    assert restored.authoring_errors == {}
    assert type(restored.grid_values) is dict and (0, 1) in restored.grid_values
    assert type(restored.extra_stat_keys) is list and type(restored.explicit_item_groups) is tuple


def test_draft_file_reads_only_cdmw_types_and_tolerates_other_versions():
    payload = json.loads(encode_draft(NewItemDraft(template_key=3)))
    payload['draft']['field_from_a_later_version'] = 1
    del payload['draft']['effect_scale']
    restored = decode_draft(json.dumps(payload).encode())
    assert restored.template_key == 3 and restored.effect_scale == 1.0
    payload['draft']['icon'] = {'$enum': 'os:PathLike', 'name': 'x'}
    with pytest.raises(DraftFileError, match='outside CDMW'):
        decode_draft(json.dumps(payload).encode())
    payload['draft']['icon'] = {'$data': 'subprocess:Popen', 'fields': {'args': 'calc'}}
    with pytest.raises(DraftFileError, match='outside CDMW'):
        decode_draft(json.dumps(payload).encode())
    with pytest.raises(DraftFileError):
        decode_draft(b'{"format": "something else"}')


def test_package_rows_keep_their_details_and_never_touch_the_package(tmp_path):
    drafts, package = tmp_path / 'drafts', tmp_path / 'out' / 'Blade.cdmw'
    package.parent.mkdir()
    package.write_bytes(b'package')
    first = register_item_package(drafts, package_path=package, identity='i' * 32, title='Blade',
                                  draft_bytes=b'{}', template_name='Sword_A')
    (row,) = list_saved_work(drafts)
    assert row.kind == KIND_ITEM_PACKAGE and row.has_draft and row.edit_pass == 1
    assert row.package_path == package.resolve() and row.source_package == 'Sword_A'
    assert saved_work_status(row, found=False) == STATUS_PACKAGE_FOUND
    update_saved_work_details(drafts, row, name='My blade', notes='v1')
    second = register_item_package(drafts, package_path=package, identity='i' * 32, title='Blade',
                                   draft_bytes=b'{"x": 1}')
    assert second['id'] == first['id'] and second['draft_dir'] == first['draft_dir']
    (row,) = list_saved_work(drafts)
    assert (row.display_name, row.notes, row.edit_pass, row.source_package) == ('My blade', 'v1', 2, 'Sword_A')
    assert (drafts / first['draft_dir'] / ITEM_DRAFT_NAME).read_bytes() == b'{"x": 1}'
    with pytest.raises(ValueError, match='already in the list'):
        add_item_package_file(drafts, package)
    remove_built_mod_from_list(drafts, row)
    assert list_saved_work(drafts) == () and read_item_package_index(drafts) == []
    assert package.read_bytes() == b'package' and not (drafts / first['draft_dir']).exists()
    package.unlink()
    register_item_package(drafts, package_path=package, identity='i' * 32, title='Blade', draft_bytes=None)
    (row,) = list_saved_work(drafts)
    assert not row.has_draft and saved_work_status(row, found=True) == STATUS_PACKAGE_MISSING


def test_grid_edits_map_onto_the_template_ladder_and_name_missing_stats():
    from cdmw.ui.new_item.state import STAT_KIND, StatColumn, StatGrid

    grid = StatGrid(columns=(StatColumn(STAT_KIND, 10, 'Attack'),), template_values=((5,), (6,)), price_items=())
    values, extra, missing = grid_values_from_edits(
        grid, (StatEdit(level=1, status_key=10, value=9), StatEdit(level=3, status_key=99, value=1),
               StatEdit(level=2, status_key=10, value=8)), ())
    assert values == {(1, 0): 9, (2, 0): 8} and extra == 1 and missing == [99]


def _pump(app, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert predicate()


@pytest.fixture
def game(tmp_path):
    app = QApplication.instance() or QApplication([])
    service, snapshot, _ = setup_game(tmp_path / 'author')
    controllers = []

    def studio():
        controller = NewItemStudioController(service=service, synchronous=True)
        controller.snapshot = snapshot
        controller.independent_mode = True
        controller.saved_work_root = tmp_path / 'drafts'
        controllers.append(controller)
        return controller

    try:
        yield app, studio, shop_spec('ContinuedBlade')
    finally:
        for controller in controllers:
            controller.request_shutdown()
            _pump(app, lambda c=controller: not c.iter_shutdown_workers())


def _author(app, controller, spec):
    controller.set_template(spec.template_key)
    draft = draft_from_spec(spec)
    for name in ('display_names', 'placement_kind', 'store_name', 'unlimited_stock', 'stock_count'):
        setattr(controller.draft, name, getattr(draft, name))
    controller.draft.descriptions = {'eng': 'Kept across sessions'}
    controller.draft.max_stack_count = 3
    assert controller.start_plan(), controller.plan
    _pump(app, lambda: controller.has_current_plan)


def _export(app, controller, path, *, update=False):
    done = []
    controller.export_finished.connect(done.append)
    assert controller.start_independent_export(str(path), update=update)
    _pump(app, lambda: done and not controller.busy)
    return done[-1]


def _continue(app, controller, launch):
    controller.set_template(launch.draft.template_key)
    controller.restore_continued_item(launch)


def test_a_written_package_continues_with_its_draft_and_updates_in_place(game, tmp_path):
    app, studio, spec = game
    author = studio()
    _author(app, author, spec)
    saved = replace(author.draft)
    written = _export(app, author, tmp_path / 'Blade.cdmw')
    (row,) = list_saved_work(tmp_path / 'drafts')
    assert row.is_item_package and row.has_draft and row.edit_pass == 1

    launch = prepare_item_package_launch(tmp_path / 'drafts', row.row_id)
    assert launch.from_saved_draft and launch.identity == written.identity
    again = studio()
    _continue(app, again, launch)
    for field in fields(NewItemDraft):
        if field.name not in ('authoring_errors', 'independent_identity'):
            assert getattr(again.draft, field.name) == getattr(saved, field.name), field.name
    assert again.draft.independent_identity == written.identity
    assert again.continued_package_path == (tmp_path / 'Blade.cdmw')
    assert spec_from_draft(replace(again.draft, independent_identity=''), again.stat_grid()) == \
        spec_from_draft(replace(saved, independent_identity=''), author.stat_grid())

    again.draft.descriptions = {'eng': 'Second pass'}
    again.invalidate_plan()
    assert again.start_plan()
    _pump(app, lambda: again.has_current_plan)
    updated = _export(app, again, again.continued_package_path, update=True)
    assert updated.identity == written.identity and updated.digest != written.digest
    (row,) = list_saved_work(tmp_path / 'drafts')
    assert row.edit_pass == 2
    reread = prepare_item_package_launch(tmp_path / 'drafts', row.row_id)
    assert reread.draft.descriptions == {'eng': 'Second pass'}

    again.set_template(spec.template_key)
    assert again.continued_package_path is None, 'another item never writes into the continued package'


def test_a_listed_package_without_a_draft_continues_from_its_recipe(game, tmp_path):
    app, studio, spec = game
    author = studio()
    author.saved_work_root = None
    _author(app, author, spec)
    expected = author.current_spec()
    _export(app, author, tmp_path / 'Shared.cdmw')
    assert not (tmp_path / 'drafts').exists()
    add_item_package_file(tmp_path / 'drafts', tmp_path / 'Shared.cdmw')
    (row,) = list_saved_work(tmp_path / 'drafts')
    assert not row.has_draft
    launch = prepare_item_package_launch(tmp_path / 'drafts', row.row_id)
    assert not launch.from_saved_draft
    again = studio()
    _continue(app, again, launch)
    rebuilt = again.current_spec()
    for name in ('template_key', 'display_names', 'descriptions', 'placement', 'max_stack_count',
                 'stat_edits', 'buy_price_edits', 'price_edits', 'icon', 'model_source'):
        assert getattr(rebuilt, name) == getattr(expected, name), name
    assert again.start_plan()
    _pump(app, lambda: again.has_current_plan)


def test_a_continued_custom_icon_falls_back_to_the_package_icon(game, tmp_path):
    from tests.test_new_item_service import _fake_dds

    app, studio, spec = game
    controller = studio()
    controller.set_template(spec.template_key)
    draft = replace(draft_from_spec(spec), icon=IconSource.GENERATED, icon_source_path=str(tmp_path / 'moved.png'))
    from cdmw.ui.new_item.continue_launch import ItemPackageLaunch

    controller.restore_continued_item(ItemPackageLaunch(tmp_path / 'x.cdmw', 'd' * 32, 'X', draft, icon_data=_fake_dds()))
    assert controller.start_plan()
    _pump(app, lambda: controller.has_current_plan)
    assert controller.plan.independent_inputs[2] == _fake_dds()
    controller.forget_continued_package()
    failures = []
    controller.plan_failed.connect(lambda message, _issues: failures.append(message))
    controller.invalidate_plan()
    controller.start_plan()
    assert failures and 'does not exist' in failures[-1]


def test_packages_from_other_tools_are_listed_but_not_continued(tmp_path, monkeypatch):
    drafts, package = tmp_path / 'drafts', tmp_path / 'Prefab.cdmw'
    package.write_bytes(b'x')
    register_item_package(drafts, package_path=package, identity='p' * 32, title='Prefab', draft_bytes=None)
    (row,) = list_saved_work(drafts)

    class Package:
        identity, title = 'p' * 32, 'Prefab'
        manifest = {'modules': [{'type': 'prefab.edit'}]}

    monkeypatch.setattr(packages, 'read_package', lambda *_args, **_kwargs: Package())
    monkeypatch.setattr('cdmw.services.independent_mod_package.has_legacy_item', lambda _package: False)
    with pytest.raises(ValueError, match='not written by Create New Item'):
        prepare_item_package_launch(drafts, row.row_id)


def test_a_baked_package_model_is_never_given_its_settings_twice():
    from cdmw.domain.new_item.surface import SurfaceEdit
    from cdmw.services.new_item_planning import ModelFiles, NewItemPlanError, baked_model_files, require_baked_appearance

    files = baked_model_files(ModelFiles(b'pac'), None, (), ())
    require_baked_appearance(files, None, (), (), 'Blade')
    with pytest.raises(NewItemPlanError, match='Import the source model again'):
        require_baked_appearance(files, None, (('blade', SurfaceEdit()),), (), 'Blade')


def test_drafts_and_mods_page_shows_a_package_row_and_routes_continue(tmp_path):
    from cdmw.ui.mesh_editor.saved_work_page import SavedWorkPage

    app = QApplication.instance() or QApplication([])
    drafts, package = tmp_path / 'drafts', tmp_path / 'Blade.cdmw'
    package.write_bytes(b'package')
    register_item_package(drafts, package_path=package, identity='i' * 32, title='Blade', draft_bytes=b'{}',
                          template_name='Sword_A')
    page = SavedWorkPage(draft_root=drafts)
    continued = []
    page.continue_requested.connect(continued.append)
    try:
        page.show()
        _pump(app, lambda: page.table.rowCount() == 1 and page.status_code(page.rows()[0]) == STATUS_PACKAGE_FOUND)
        page.table.selectRow(0)
        assert page.kind_value.text() == 'Item package'
        assert page.game_file_value.toolTip() or page.game_file_value.text()
        assert page.status_value.text() == 'Package file found'
        assert page.delete_button.text() == 'Remove from List...'
        assert not page.duplicate_button.isEnabled() and page.continue_button.isEnabled()
        assert page.table.item(0, 2).text() == 'New item based on Sword_A'
        assert page.table.item(0, 2).toolTip() == str(package.resolve())
        page.continue_button.click()
        assert [row.package_path for row in continued] == [package.resolve()]
    finally:
        page.close()
        page.deleteLater()
