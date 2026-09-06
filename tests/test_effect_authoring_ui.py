"""Real Qt controls route recipes and preview-only settings without a native window."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
import pytest
import shiboken6

from cdmw.domain.new_item.effect_authoring import EffectLayer, EffectLook, EmitterEdit
from cdmw.ui.new_item.effect_recipe_panel import EffectRecipePanel, EffectUserLibrary
from cdmw.ui.new_item.state import EffectWorkspaceState

_APP = QApplication.instance() or QApplication([])


def test_real_emitter_controls_show_inherited_values_and_route_overrides():
    panel = EffectRecipePanel(EffectUserLibrary())
    received = []
    panel.changed.connect(received.append)
    panel.changed.connect(panel.set_state)
    panel.set_state(EffectWorkspaceState.from_layers((EffectLayer('fx_fire'),)))
    preview = SimpleNamespace(editor_emitters=({'index':0,'name':'Sparks','enabled':True,'resolved':True,'fields':('_spawnCountMin','_spawnCountMax'), 'values':{'_spawnCountMin':(3,), '_spawnCountMax':(4,)}},))
    panel.set_preview(preview)
    check, spins = panel._fields['_spawnCountMax']
    assert spins[0].value() == 4
    assert check.checkState() == Qt.CheckState.Unchecked
    spins[0].setValue(8)
    assert dict(received[-1].look.emitters[0].values)['_spawnCountMax'] == (8.,)
    assert check.checkState() == Qt.CheckState.Checked
    panel.emitter_enabled.setChecked(False)
    assert received[-1].look.emitters[0].enabled is False
    panel.create_from_emitter()
    assert received[-1].resolved_layers()[0].name == 'Custom effect'
    assert received[-1].look.emitter_order == (0,)
    panel.set_preview(None)
    assert not panel.emitter_enabled.isEnabled()
    panel.close()
    shiboken6.delete(panel)


def test_layer_selection_keeps_edits_and_visibility_independent():
    panel = EffectRecipePanel(EffectUserLibrary())
    panel.changed.connect(panel.set_state)
    panel.set_state(EffectWorkspaceState.from_layers((EffectLayer('fx_fire'), EffectLayer('fx_sparks', offset=(1,2,3)))))
    panel.layers.setCurrentRow(1)
    assert panel.state.offset == (1,2,3)
    panel.layers.item(0).setCheckState(Qt.CheckState.Unchecked)
    layers = panel.state.resolved_layers()
    assert not layers[0].enabled and layers[1].enabled
    panel.duplicate_layer()
    assert len(panel.state.resolved_layers()) == 3
    panel.remove_layer()
    assert len(panel.state.resolved_layers()) == 2
    panel.close()
    shiboken6.delete(panel)


def test_unrelated_edits_preserve_imported_curve_samples():
    panel = EffectRecipePanel(EffectUserLibrary())
    panel.changed.connect(panel.set_state)
    edit = EmitterEdit(0, size_curve=(1., .2, .8, 2., 1.), opacity_curve=(0., .2, .6, .9, 0.),
                       color_curve=((1., 0., 0.), (.8, .2, 0.), (.5, .5, 0.), (.2, .8, 0.), (0., 1., 0.)))
    panel.set_state(EffectWorkspaceState.from_layers((EffectLayer('fx_fire', look=EffectLook(emitters=(edit,))),)))
    panel.set_preview(SimpleNamespace(editor_emitters=({'name':'Sparks','enabled':True,'resolved':True},)))
    panel.emitter_enabled.setChecked(False)
    updated = panel.state.look.emitters[0]
    assert updated.size_curve == edit.size_curve
    assert updated.opacity_curve == edit.opacity_curve
    assert updated.color_curve == edit.color_curve
    panel.curves['size_curve'][1][1].setValue(3.)
    updated = panel.state.look.emitters[0]
    assert updated.size_curve == (1., 3., 1.)
    assert updated.opacity_curve == edit.opacity_curve
    assert updated.color_curve == edit.color_curve
    panel.close()
    shiboken6.delete(panel)


def test_recipe_limit_failure_preserves_saved_library(monkeypatch):
    from cdmw.ui.new_item import effect_recipe_panel as module
    library = EffectUserLibrary()
    library.recipes = {str(i): '{"schema":1,"layers":[]}' for i in range(64)}
    before = library.recipes.copy()
    panel = EffectRecipePanel(library)
    monkeypatch.setattr(module.QInputDialog, 'getText', lambda *args: ('Extra', True))
    failures = []
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *args: failures.append(args[-1]))
    panel.save_recipe()
    assert library.recipes == before
    assert failures
    library.save()  # Later preference saves remain usable after rejecting the extra recipe.
    panel.close()
    shiboken6.delete(panel)


def test_effect_controls_update_live_patch_and_replay_state():
    from cdmw.ui.preview.dotnet_host import RustPreviewHostFrame
    patches = []
    host = SimpleNamespace(_presentation_state={'display':{'grid_visible':True}}, _remember_presentation_state=lambda value: patches.append(value) or True)
    method = RustPreviewHostFrame.set_effect_preview_controls
    method(host, speed=.5, time_seconds=2, seed=7, quality=1024, solo_layer=1)
    assert host._presentation_state['display']['effect_seek_seconds'] == 2
    assert host._presentation_state['display']['grid_visible'] is True
    serial = patches[-1]['display']['effect_seek_serial']
    method(host, time_seconds=2)
    assert patches[-1]['display']['effect_seek_serial'] == serial + 1
    with pytest.raises(ValueError):
        method(host, speed=float('nan'))
