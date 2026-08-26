"""Preview controls and guided-presentation cases for the effect placement dialog."""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtWidgets import QLabel, QScrollArea

from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from tests.test_effect_placement_dialog import _Host, _blade


class _DialogPresentationMixin:
    def test_the_trail_button_appears_only_when_the_item_has_its_own_trail(self) -> None:
        """Weapons share socket files, so a borrowed one puts the trail at another weapon's
        tip. The button is the game's own answer or it is not offered at all."""

        from cdmw.services.effect_character_reference import TRAIL_SOCKET

        dialog = self._dialog()
        dialog._offer_the_trail_socket()
        self.assertFalse(dialog.trail_button.isVisible(), "nothing read yet, nothing offered")

        dialog._effect_sockets = (("FX_Muzzle_00_Socket", (0.0, 0.0, -0.4)),)
        dialog._offer_the_trail_socket()
        self.assertFalse(dialog.trail_button.isVisible(), "a muzzle is not a trail")

        dialog._effect_sockets = ((TRAIL_SOCKET, (0.0, 0.02, -1.1)),)
        dialog._offer_the_trail_socket()
        self.assertTrue(dialog.trail_button.isVisibleTo(dialog), "the item's own trail is offered")
        self.assertIn("-1.10", dialog.trail_button.toolTip(), "and the tooltip says where it is")

        dialog._put_it_at("trail")
        self.assertEqual(tuple(round(v, 6) for v in dialog.offset), (0.0, 0.02, -1.1))

    def test_the_particles_can_be_held_where_they_are(self) -> None:
        """Hiding the fire answers "what is under it". Holding it answers "where exactly is
        this one", which a cloud in motion never lets anyone read."""

        dialog = self._dialog()
        self.assertFalse(dialog.pause_button.isChecked())
        dialog.pause_button.setChecked(True)
        self.assertEqual(dialog.host.paused, [True])
        self.assertEqual(dialog.pause_button.text(), "Paused", "the button says which state it is in")
        dialog.pause_button.setChecked(False)
        self.assertEqual(dialog.host.paused, [True, False])
        self.assertEqual(dialog.pause_button.text(), "Pause")
        self.assertEqual(dialog.host.particles, [], "pausing is not hiding")

    def test_the_backdrop_is_chosen_and_remembered(self) -> None:
        """An effect adds its light to what is behind it, so it reads best on a dark
        backdrop; the Mesh Editor's grey is there for judging the item's own textures,
        which is the other half of what this dialog is for."""

        from cdmw.ui.new_item.effect_placement_dialog_support import BACKDROPS, remembered_backdrop

        dialog = self._dialog()
        self.assertEqual([dialog.backdrop_choice.itemData(row) for row in range(dialog.backdrop_choice.count())],
                         list(BACKDROPS))
        self.assertEqual(dialog.backdrop_choice.currentData(), remembered_backdrop(), "it opens on the last one chosen")

        grey = BACKDROPS.index("#3B3B3B")
        dialog.backdrop_choice.setCurrentIndex(grey)
        self.assertEqual(dialog.host.backdrops[-1], "#3B3B3B", "the viewport is told")
        self.assertEqual(remembered_backdrop(), "#3B3B3B", "and the next dialog opens on it")

        dark = BACKDROPS.index("#101014")
        dialog.backdrop_choice.setCurrentIndex(dark)
        self.assertEqual(remembered_backdrop(), "#101014")

    def test_orbit_inversion_is_visible_shared_and_applied_to_this_viewport(self) -> None:
        with patch(
            "cdmw.ui.new_item.effect_placement_dialog.remembered_orbit_inversion",
            return_value=(True, False),
        ):
            dialog = self._dialog()

        self.assertTrue(dialog.invert_orbit_x_checkbox.isChecked())
        self.assertFalse(dialog.invert_orbit_y_checkbox.isChecked())
        dialog._host_state("ready", "")
        self.assertEqual(
            dialog.host.camera_bindings[-1],
            {"right": "orbit", "invert_orbit_x": True, "invert_orbit_y": False},
        )

        with patch("cdmw.ui.new_item.effect_placement_dialog.remember_orbit_inversion") as remember:
            dialog.invert_orbit_y_checkbox.setChecked(True)
            remember.assert_called_once_with(True, True)
        self.assertTrue(dialog.host.camera_bindings[-1]["invert_orbit_y"])
        dialog._closed = True

    def test_orbit_inversion_uses_the_shared_preview_setting_keys(self) -> None:
        from cdmw.ui.new_item.effect_placement_dialog_support import (
            remember_orbit_inversion,
            remembered_orbit_inversion,
        )

        class Settings:
            values = {
                "preview/invert_orbit_x": "true",
                "preview/invert_orbit_y": 0,
            }

            def __init__(self, *_args) -> None:
                pass

            def value(self, key, default=False):
                return self.values.get(key, default)

            def setValue(self, key, value) -> None:
                self.values[key] = value

        with patch("PySide6.QtCore.QSettings", Settings):
            self.assertEqual(remembered_orbit_inversion(), (True, False))
            remember_orbit_inversion(False, True)
            self.assertEqual(remembered_orbit_inversion(), (False, True))

    def test_the_panel_is_grouped_and_the_legend_folds_away(self) -> None:
        """Fourteen controls, five legend rows and four labels in one column read as a
        wall. What moves the effect and what is drawn are two questions, and the legend
        answers a third that is asked once."""

        from PySide6.QtWidgets import QGroupBox

        dialog = self._dialog()
        groups = [box.title() for box in dialog.findChildren(QGroupBox)]
        self.assertEqual(groups, ["Placement", "Preview"])
        self.assertFalse(dialog.legend_toggle.toggle.isChecked(), "the legend starts folded")
        for label in dialog.legend_rows.values():
            self.assertFalse(label.isVisibleTo(dialog), "and its rows are not taking room")
        dialog.legend_toggle.toggle.setChecked(True)
        self.assertTrue(dialog.legend_rows["anchor"].isVisibleTo(dialog), "one click and it is there")

    def test_guided_presentation_exposes_the_exact_toolbar_and_inspector_controls(self) -> None:
        workspace = EffectPlacementWorkspace(
            item_mesh=_blade(),
            box_min=(-1.0, -1.0, -1.0),
            box_max=(1.0, 1.0, 1.0),
            host_factory=lambda parent: _Host(parent),
            compatibility_ui=False,
        )
        self.addCleanup(workspace.request_shutdown)
        self.addCleanup(workspace.deleteLater)
        workspace.resize(1000, 700)
        workspace.show()
        self.app.processEvents()
        visible_scrolls = [scroll.objectName() for scroll in workspace.findChildren(QScrollArea) if scroll.isVisibleTo(workspace)]
        self.assertEqual(visible_scrolls, ["effect_inspector_scroll"])
        inspector_scroll = workspace.preview_splitter.widget(1)
        self.assertEqual(inspector_scroll.horizontalScrollBar().maximum(), 0)
        inspector_width = inspector_scroll.viewport().width()
        apply_bottom = workspace.apply_button.mapTo(
            inspector_scroll.viewport(), workspace.apply_button.rect().bottomRight()
        ).y()
        self.assertLess(apply_bottom, inspector_scroll.viewport().height(), "Apply stays visible at the 900px-window body height")
        for spin in (*workspace.offset_spins, *workspace.rotation_spins):
            right_edge = spin.mapTo(inspector_scroll.viewport(), spin.rect().bottomRight()).x()
            self.assertLess(right_edge, inspector_width, "every axis value remains visible at the inspector minimum")
        self.assertGreater(workspace.offset_spins[0].x(), 80, "the Position caption and X control do not overlap")
        self.assertGreater(workspace.rotation_spins[0].x(), 80, "the Rotation caption and X control do not overlap")
        orphaned_captions = [
            label.text()
            for label in workspace.findChildren(QLabel)
            if label.parent() is workspace and label.isVisibleTo(workspace) and label.text() in {"Effect", "Model", "View"}
        ]
        self.assertEqual(orphaned_captions, [])
        self.assertEqual(
            [workspace.move_button.text(), workspace.rotate_button.text(), workspace.scale_button.text()],
            ["Move", "Rotate", "Scale"],
        )
        self.assertEqual([button.text() for button in workspace.view_buttons[:3]], ["Front", "Side", "Top"])
        self.assertEqual((workspace.frame_button.text(), workspace.pause_button.text()), ("Frame", "Pause"))
        for button in (
            workspace.move_button,
            workspace.rotate_button,
            workspace.scale_button,
            *workspace.view_buttons[:3],
            workspace.frame_button,
            workspace.pause_button,
        ):
            self.assertFalse(button.icon().isNull(), button.text())
        self.assertEqual([workspace.anchor_choice.itemText(i) for i in range(workspace.anchor_choice.count())], ["Origin", "Center", "End"])
        self.assertEqual(workspace.show_reach.text(), "Show bounds")
        self.assertEqual(workspace.fit_button.text(), "Fit")
        self.assertEqual([workspace.backdrop_choice.itemText(i) for i in range(workspace.backdrop_choice.count())], ["Neutral", "Dark", "Black"])
        self.assertEqual(set(workspace.look_spins), {"intensity", "particle_size", "spawn_rate", "lifetime"})
        workspace.look_spins["intensity"].setValue(20.0)
        self.assertEqual(workspace.look_sliders["intensity"].value(), 1000)
        workspace.look_sliders["intensity"].setValue(0)
        self.assertEqual(workspace.look_spins["intensity"].value(), 1.0)
        workspace.anchor_choice.setCurrentIndex(workspace.anchor_choice.findData("center"))
        self.assertAlmostEqual(workspace.offset[2], -0.35)
        workspace.anchor_choice.setCurrentIndex(workspace.anchor_choice.findData("end"))
        self.assertAlmostEqual(workspace.offset[2], -0.9)
        workspace.scale_spin.setValue(2.0)
        workspace.rotation_spins[1].setValue(45.0)
        workspace.guided_restore_button.click()
        self.assertEqual((workspace.scale, workspace.offset, workspace.rotation), (1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))

        from cdmw.services.effect_character_reference import TRAIL_SOCKET

        workspace._effect_sockets = ((TRAIL_SOCKET, (0.1, 0.2, -0.9)),)
        workspace._offer_the_trail_socket()
        trail = workspace.anchor_choice.findData("trail")
        self.assertGreaterEqual(trail, 0)
        self.assertEqual(workspace.anchor_choice.itemText(trail), "Trail Socket")
        workspace.anchor_choice.setCurrentIndex(trail)
        self.assertEqual(tuple(round(value, 6) for value in workspace.offset), (0.1, 0.2, -0.9))

    def test_an_exact_decoder_reason_disables_only_look_authoring(self) -> None:
        workspace = EffectPlacementWorkspace(
            item_mesh=_blade(),
            box_min=(-1.0, -1.0, -1.0),
            box_max=(1.0, 1.0, 1.0),
            host_factory=lambda _parent: None,
        )
        self.addCleanup(workspace.request_shutdown)
        self.addCleanup(workspace.deleteLater)
        reason = "unexpected marker at byte 418"
        workspace.set_decoder_reason(reason)
        self.assertEqual(workspace.decoder_reason.text(), reason)
        self.assertFalse(workspace.colour_as_shipped.isEnabled())
        self.assertTrue(workspace.scale_spin.isEnabled(), "numeric placement remains available")
        workspace.set_decoder_reason("")
        self.assertTrue(workspace.look_spins["intensity"].isEnabled())

        self.assertFalse(workspace.show_reach.isEnabled())
        self.assertFalse(workspace.backdrop_choice.isEnabled())
        self.assertFalse(workspace.show_character.isEnabled())
        self.assertTrue(workspace.fit_button.isEnabled(), "Fit remains a numeric scale operation")

    def test_the_context_and_actions_are_compact_and_specific(self) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        dialog = self._dialog(effect_label="pafx_weapon_fire", item_label="placed")
        self.assertEqual(dialog.effect_name_label.text(), "pafx_weapon_fire")
        self.assertEqual(dialog.showing_label.text(), "Imported")
        self.assertIn("step 3", dialog.showing_label.toolTip(), "detail stays available without another paragraph")
        self.assertIn("right mouse button", dialog.host.toolTip(), "gesture help moved off the permanent canvas")
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertIsNotNone(buttons)
        self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Ok).text(), "Apply")

    def test_a_reach_far_larger_than_the_item_starts_hidden(self) -> None:
        dialog = self._dialog()
        self.assertFalse(dialog.show_reach.isChecked())
        self.assertIn("dwarfs the item", dialog.size_label.text())
