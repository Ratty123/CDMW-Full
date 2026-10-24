import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import threading

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.item_stats import ItemStatSettings, PassiveSkill
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_stats import StatsPanel
from cdmw.ui.new_item.state import NewItemDraft
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.services.new_item_settings import load_settings_index
from tests.test_independent_item_stats import stat_game
from tests.test_independent_item_settings import extended_game
from tests.test_independent_items import setup_game
from tests.test_new_item_settings_editor import native_edit


def test_real_editor_handles_nonempty_stat_lists_passive_levels_clear_and_reset(tmp_path,stat_game):
    app=QApplication.instance() or QApplication([])
    service,snapshot,_=setup_game(tmp_path)
    controller=NewItemStudioController(service=service,synchronous=True)
    controller.snapshot=snapshot
    controller.draft=NewItemDraft(template_key=1001295,internal_name='Stats',display_names={'eng':'Stats'})
    panel=StatsPanel(controller)
    editor=panel.item_settings.stats
    try:
        assert panel.item_settings.pages.isEnabled() and editor.isEnabled()
        assert editor.statistics.rowCount()==6
        panel.item_settings.load.click()
        assert editor.skill.count()==2
        editor.stat_kind.setCurrentIndex(editor.stat_kind.findData('regeneration'))
        editor.stat_level.setCurrentIndex(editor.stat_level.findData(1))
        editor.stat_key.setCurrentIndex(editor.stat_key.findData(1000002))
        editor.add_stat.click()
        assert controller.draft.stat_settings.statistics[0].key==1000002
        editor.statistics.selectRow(editor.statistics.rowCount()-1);editor.remove_stat.click()
        assert controller.draft.stat_settings is None
        regen=next(i for i,row in enumerate(editor._statistics) if (row.kind,row.level)==('regeneration',0))
        parameter=next(i for i,row in enumerate(editor._statistics) if (row.kind,row.level)==('level_stat',1))
        panel.item_settings.pages.setCurrentWidget(editor)
        native_edit(PresentationDocument(),editor,editor.statistics,'cell',
                    {'path':[regen],'column':4,'text':'-9,223,372,036,854,775,808'})
        editor.statistics.item(parameter,4).setText('0')
        assert controller.draft.stat_settings.statistics[0].value==-(1<<63)
        editor.statistics.item(parameter,4).setText('256')
        assert editor.statistics.item(parameter,4).text()=='0'
        assert 'Invalid' in editor.message.text()
        editor.override_passives.setChecked(True)
        editor.skill.setCurrentIndex(editor.skill.findData(600002))
        editor.add.click()
        editor.passives.item(1,1).setText('4,294,967,295')
        assert controller.current_spec().stat_settings.passive_skills==(PassiveSkill(600001,4),PassiveSkill(600002,0xffffffff))
        editor.passives.selectAll();editor.remove.click()
        assert controller.draft.stat_settings.passive_skills==()
        editor.reset.click()
        assert controller.draft.stat_settings is None
        assert editor.passives.rowCount()==1 and not editor.override_passives.isChecked()
        editor.override_passives.setChecked(True)
        panel._reset()
        assert controller.draft.stat_settings is None
        controller.set_template(1005300)
        assert controller.draft.stat_settings is None
        controller.draft.stat_settings=ItemStatSettings(passive_skills=(PassiveSkill(600001,1),))
        controller.snapshot=None
        panel.rebuild()
        assert not editor.isEnabled() and editor.statistics.rowCount()==editor.passives.rowCount()==0
    finally:
        panel.deleteLater();controller.deleteLater();app.processEvents()


def test_skill_catalogue_cancellation_never_publishes_partial_results(tmp_path,stat_game,monkeypatch):
    _,snapshot,_=setup_game(tmp_path)
    import cdmw.services.new_item_settings as service
    original=service.Cursor.text
    stop=threading.Event()
    def text(cursor):
        result=original(cursor)
        if int.from_bytes(cursor.raw[:4],'little')==600001:
            stop.set()
        return result
    monkeypatch.setattr(service.Cursor,'text',text)
    with pytest.raises(RunCancelled):load_settings_index(snapshot,stop_event=stop)
    assert 'item-settings' not in snapshot._authoring_indexes
