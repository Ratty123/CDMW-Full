import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from dataclasses import replace
import threading

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.workers.new_item_authoring_index import authoring_index_task
from tests.test_independent_item_behavior import behavior_game, definition_game, extended_game
from tests.test_new_item_settings_editor import editor_fixture, native_edit
from tests.test_new_item_definition_editor import select_field, model_path
from tests.test_independent_items import setup_game


def test_remaining_behavior_controls_use_native_exact_values_and_preserve_reset_contracts(tmp_path,behavior_game):
    app=QApplication.instance() or QApplication([])
    controller,panel,settings=editor_fixture(tmp_path); editor=settings.behavior
    panel.views.setCurrentWidget(settings); settings.pages.setCurrentWidget(editor)
    document=PresentationDocument()
    def cell(path,value):
        native_edit(document,panel,editor.tree,'cell',{'path':model_path(editor,path),'column':1,'text':value}); app.processEvents()
    try:
        editor.load.click(); assert editor.index is not None
        select_field(editor,'metadata','memo'); cell((),'Owned 日本語 memo')
        assert controller.current_spec().behavior_settings.fields['memo']=='Owned 日本語 memo'
        select_field(editor,'classification','category'); cell((),'65,535')
        assert controller.current_spec().behavior_settings.fields['category']==65535
        select_field(editor,'drops','default_subitem'); cell(('type',),'3'); cell(('value',),'900001')
        assert controller.draft.behavior_settings.fields['default_subitem']=={'type':3,'value':900001}
        cell(('type',),'17'); assert controller.draft.behavior_settings.fields['default_subitem']['value'] is None
        select_field(editor,'inspection','fixed_pages'); editor.tree.setCurrentIndex(editor._nodes[()].index()); editor.add.click()
        cell((1,'left_texture'),'ui/texture/left.dds')
        assert len(controller.current_spec().behavior_settings.fields['fixed_pages'])==2
        select_field(editor,'inspection','inspections')
        assert editor._nodes[(0,'description','category')].index().siblingAtColumn(0).data()=='Localization category'
        editor.tree.setCurrentIndex(editor._nodes[(0,'description','text_key')].index())
        assert editor.picker.count()>0; selected=editor.picker.currentData(); editor.use.click()
        assert controller.draft.behavior_settings.fields['inspections'][0]['description']==editor.index.localizations[selected]
        select_field(editor,'interaction','docking'); editor.tree.setCurrentIndex(editor._nodes[()].index()); editor.remove.click()
        assert controller.draft.behavior_settings.fields['docking'] is None
        editor.add.click(); assert controller.draft.behavior_settings.fields['docking']['collision'] is False
        select_field(editor,'currency','money'); cell(('price_floor',),'18,446,744,073,709,551,615')
        assert controller.draft.behavior_settings.fields['money']['price_floor']==(1<<64)-1
        select_field(editor,'presentation','prefabs'); cell((0,'scale',0),'1.25')
        assert controller.draft.behavior_settings.fields['prefabs'][0]['scale'][0]==1.25
        cell((0,'scale',0),'nan')
        assert controller.draft.behavior_settings.fields['prefabs'][0]['scale'][0]==1.25
        assert 'Invalid' in editor.message.text()
        editor.reset.click(); assert controller.draft.behavior_settings is None
        select_field(editor,'metadata','memo'); panel._reset(); assert controller.draft.behavior_settings is None
        select_field(editor,'metadata','memo'); controller.set_template(1005300)
        assert controller.draft.behavior_settings is None
        controller.snapshot=None; panel.rebuild(); assert not editor.isEnabled()
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()


def test_behavior_catalogue_cancel_and_stale_delivery_are_rejected(tmp_path,behavior_game,monkeypatch):
    app=QApplication.instance() or QApplication([])
    _,snapshot,_=setup_game(tmp_path/'source')
    import cdmw.services.new_item_behavior as service
    stop=threading.Event(); original=service.read_behavior_fields
    def cancel(raw):
        result=original(raw); stop.set(); return result
    monkeypatch.setattr(service,'read_behavior_fields',cancel)
    with pytest.raises(RunCancelled): authoring_index_task('item-behavior',snapshot)(lambda *_:None,stop)
    assert 'item-behavior' not in snapshot._authoring_indexes
    controller,panel,settings=editor_fixture(tmp_path/'controls'); callbacks=[]
    try:
        def capture(_kind,_task,done,_failed): callbacks.append(done); return True
        monkeypatch.setattr(controller,'_run',capture)
        controller.start_authoring_index('item-behavior')
        controller.snapshot=replace(controller.snapshot,_authoring_indexes={})
        callbacks[0](object()); assert settings.behavior.index is None
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()


def test_stock_export_button_writes_existing_identity_without_planning_or_allocation(tmp_path,behavior_game,monkeypatch):
    from cdmw.ui.new_item.item_settings_editor import QFileDialog
    from cdmw.services.independent_item_package import read_package
    app=QApplication.instance() or QApplication([])
    controller,panel,settings=editor_fixture(tmp_path)
    path=tmp_path/'stock.cditem'; results=[]
    try:
        controller.export_finished.connect(results.append)
        editor=settings.behavior
        select_field(editor,'metadata','memo')
        editor._nodes[()].setText('Stock memo'); app.processEvents()
        panel.views.setCurrentWidget(settings)
        monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_args,**_kwargs:(str(path),''))
        def refuse(*_args,**_kwargs): raise AssertionError('Stock export allocated a new item')
        monkeypatch.setattr(type(controller.service),'allocate',refuse)
        native_edit(PresentationDocument(),panel,settings.write_stock,'activate')
        assert results and path.is_file() and controller.plan is None and not controller.issued_keys
        package=read_package(path)
        operations=package.manifest['modules'][0]['data']['operations']
        assert package.manifest['requires']=={'item.overrides':1}
        assert operations[0]['target']['key']==1001295
        assert operations[0]['field']=={'family':'behavior','name':'memo'}
        assert operations[0]['value']=='Stock memo'
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()


def test_stock_export_refuses_cancellation_and_a_changed_source_before_publication(tmp_path,behavior_game,monkeypatch):
    from cdmw.domain.new_item.item_behavior import ItemBehaviorSettings
    import cdmw.services.independent_item_package as packages
    app=QApplication.instance() or QApplication([])
    controller,panel,_settings=editor_fixture(tmp_path); tasks=[]
    try:
        controller.draft.behavior_settings=ItemBehaviorSettings({'memo':'Captured edit'})
        monkeypatch.setattr(controller,'_run',lambda _lane,task,*_args,**_kwargs:tasks.append(task) or True)
        target=tmp_path/'refused.cditem'
        assert controller.start_stock_item_export(target)
        stop=threading.Event(); stop.set()
        with pytest.raises(RunCancelled): tasks[0](lambda *_:None,stop)
        assert not target.exists()
        original=packages.write_package
        def changed(package,path,**kwargs):
            source=controller.snapshot.entry('ui/texture/left.dds').paz_file
            with open(source,'ab') as handle: handle.write(b'changed')
            return original(package,path,**kwargs)
        monkeypatch.setattr(packages,'write_package',changed)
        with pytest.raises(ValueError,match='changed|stale'): tasks[0](lambda *_:None,threading.Event())
        assert not target.exists() and not tuple(tmp_path.glob('.cditem-*.tmp'))
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()


def test_behavior_tree_and_stock_action_translate_in_all_builtin_locales(tmp_path,behavior_game):
    from cdmw.domain.localization import BUILTIN_LANGUAGES
    from cdmw.ui.localization import UiLocalizer
    from cdmw.services.active_ui_translation import ACTIVE_UI_LOCALIZER_PROPERTY
    app=QApplication.instance() or QApplication([])
    previous=app.property(ACTIVE_UI_LOCALIZER_PROPERTY)
    try:
        for language in BUILTIN_LANGUAGES:
            localizer=UiLocalizer(language_dir=tmp_path/'languages',language_code=language.code)
            app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY,localizer)
            controller,panel,settings=editor_fixture(tmp_path/language.code)
            try:
                panel.views.setCurrentWidget(settings)
                localizer.apply(panel)
                select_field(settings.behavior,'classification','category')
                assert settings.behavior._nodes[()].index().siblingAtColumn(0).data()==localizer.translate('Item category')
                select_field(settings.behavior,'inspection','inspections')
                assert settings.behavior._nodes[(0,'description','category')].index().siblingAtColumn(0).data()==localizer.translate('Localization category')
                assert settings.write_stock.text()==localizer.translate('Write stock item package…')
                if language.code!='en': assert settings.write_stock.text()!='Write stock item package…'
            finally:
                panel.deleteLater(); controller.deleteLater(); app.processEvents(); localizer.shutdown()
    finally: app.setProperty(ACTIVE_UI_LOCALIZER_PROPERTY,previous)
