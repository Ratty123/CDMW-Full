"""Private, synchronized Before/After scenes for a fully prepared operation."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
                               QSlider, QLabel, QCheckBox, QDoubleSpinBox, QSplitter, QPlainTextEdit)

from tools.paa_motion.format import FPS
from tools.paa_motion.timing import duration_seconds
from cdmw.services.active_ui_translation import translate_active_ui_text as tr

from .scene_preparation import PreparedScene, build_scene  # compatibility imports


class MovePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from .viewport import SkeletonViewport
        from .blend_playback import PreviewBlends
        self._blend_states = PreviewBlends()
        self.scene = None
        self._stale_message = ''
        self.seconds = 0.0
        self._last_tick = 0.0
        self._follow_anchor = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._views = [SkeletonViewport(), SkeletonViewport()]
        self._views[0].setMinimumSize(200, 220)
        self._views[1].setMinimumSize(200, 220)
        for view in self._views:
            view.set_follow(False)
            view.set_solid(True)
            view.set_show_labels(False)
            view.set_show_unused(False)
        self._views[1]._camera = self._views[0]._camera
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.view_mode = QComboBox()
        self.view_mode.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        for label in ("After", "Before", "Compare"):
            self.view_mode.addItem(label, label)
        self.view_mode.currentIndexChanged.connect(self._show_views)
        controls.addWidget(self.view_mode)
        self.role = QComboBox()
        self.role.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        for label in ("Stowed", "Held"):
            self.role.addItem(label, label)
        self.role.setToolTip("Initial attachment state; also used when chart events are unavailable")
        self.role.currentIndexChanged.connect(self.render)
        controls.addWidget(self.role)
        self.chart_events = QCheckBox("Chart events")
        self.chart_events.setChecked(True)
        self.chart_events.setToolTip("Apply decoded handoffs from the initial state. Conditional or conflicting timelines use manual inspection.")
        self.chart_events.toggled.connect(self.render)
        controls.addWidget(self.chart_events)
        self.follow = QCheckBox("Follow")
        self.follow.setChecked(True)
        self.follow.setToolTip("Follow Before's root travel with the shared comparison camera")
        controls.addWidget(self.follow)
        controls.addStretch(1)
        self.time_label = QLabel("Prepare a selection to preview")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        for label, view in zip(("Before · current session", "After · proposed operation"), self._views):
            panel = QWidget()
            pane = QVBoxLayout(panel)
            pane.setContentsMargins(0, 0, 0, 0)
            pane.addWidget(QLabel(label))
            pane.addWidget(view, 1)
            self.splitter.addWidget(panel)
        layout.addWidget(self.splitter, 1)
        transport = QHBoxLayout()
        self.play = QPushButton("Play")
        self.play.setEnabled(False)
        self.play.clicked.connect(self.toggle)
        transport.addWidget(self.play)
        for label, delta in (("Previous", -1), ("Next", 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda _c=False, d=delta: self._step(d))
            transport.addWidget(button)
        self.clip_box = QComboBox()
        self.clip_box.setMinimumWidth(100)
        self.clip_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.clip_box.currentIndexChanged.connect(self._clip_changed)
        transport.addWidget(self.clip_box, 1)
        self.loop = QCheckBox("Loop")
        self.loop.setChecked(True)
        transport.addWidget(self.loop)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(.1, 3.)
        self.speed.setSingleStep(.1)
        self.speed.setValue(1.)
        self.speed.setSuffix("×")
        transport.addWidget(self.speed)
        layout.addLayout(transport)
        blend_row = QHBoxLayout()
        self.blend_box = QComboBox()
        self.blend_box.setProperty('_i18n_translate_combo_items', True)
        self.blend_box.addItem("Selected clip", None)
        self.blend_box.currentIndexChanged.connect(self._blend_changed)
        blend_row.addWidget(self.blend_box, 1)
        parameter_row = QHBoxLayout()
        self._parameters = []
        for _ in range(3):
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setMaximumWidth(210)
            spin.valueChanged.connect(self._clip_changed)
            spin.hide()
            self._parameters.append(spin)
            parameter_row.addWidget(spin)
        self.blend_scale = QDoubleSpinBox()
        self.blend_scale.setRange(.05, 10.)
        self.blend_scale.setValue(1.)
        self.blend_scale.setPrefix("Blend rate ")
        self.blend_scale.setToolTip("Manual playback rate. The stored character scale adjusts automatic inputs, not clip timing.")
        self.blend_scale.valueChanged.connect(self._clip_changed)
        self.blend_scale.hide()
        blend_row.addWidget(self.blend_scale)
        self.smoothing = QCheckBox("Smoothing")
        self.smoothing.setChecked(True)
        self.smoothing.setToolTip("Use stored parameter and weight smoothing during playback. Seeking resets the blend to the current inputs.")
        self.smoothing.toggled.connect(self._reset_blend)
        self.smoothing.hide()
        blend_row.addWidget(self.smoothing)
        self.restart_blend = QPushButton("Restart blend")
        self.restart_blend.setToolTip("Restart from current inputs, including a stored initial weight hold")
        self.restart_blend.clicked.connect(lambda: self.seek(0))
        self.restart_blend.hide()
        blend_row.addWidget(self.restart_blend)
        layout.addLayout(blend_row)
        layout.addLayout(parameter_row)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.seek)
        layout.addWidget(self.slider)
        self.status = QLabel("Preview checks: Unverified")
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        detail_button = QPushButton('Preview details')
        detail_button.setCheckable(True)
        status_row.addWidget(detail_button)
        layout.addLayout(status_row)
        self._status_details = QPlainTextEdit()
        self._status_details.setReadOnly(True)
        self._status_details.setMaximumHeight(110)
        self._status_details.hide()
        detail_button.toggled.connect(self._status_details.setVisible)
        layout.addWidget(self._status_details)
        self._show_views()

    def set_scene(self, scene):
        self._stale_message = ''
        old = self.clip_box.currentData()
        self.scene = scene
        self._blend_states.reset()
        self._follow_anchor = self._views[0]._root_anchor(scene.before.hierarchy)
        self.blend_box.blockSignals(True)
        selected_space = self.blend_box.currentData()
        self.blend_box.clear()
        self.blend_box.addItem("Selected clip", None)
        for space in scene.blendspaces:
            self.blend_box.addItem(space.path.rsplit('/', 1)[-1], space.path)
        self.blend_box.setCurrentIndex(max(0, self.blend_box.findData(selected_space)))
        self.blend_box.blockSignals(False)
        self.clip_box.blockSignals(True)
        self.clip_box.clear()
        by_target = {r.target_path:r for r in scene.prepared.plan.request.replacements}
        for path in scene.preview_paths:
            row = by_target.get(path)
            self.clip_box.addItem(path.rsplit('/',1)[-1], path)
            self.clip_box.setItemData(self.clip_box.count() - 1,
                                      f"{path}\n→ {row.donor.path}" if row else f"{path}\nExisting animation; excluded from export", Qt.ToolTipRole)
        self.clip_box.setCurrentIndex(max(0, self.clip_box.findData(old)))
        self.clip_box.blockSignals(False)
        self._clip_changed()
        self._blend_changed()

    def mark_stale(self, message):
        self._stale_message = message
        self.status.setText(message)

    def _clips(self):
        if self.scene is None:
            return None, None
        path = self.clip_box.currentData()
        return self.scene.clips.get(path), (self.scene.after_clips or {}).get(path)

    def _space(self):
        return next((s for s in self.scene.blendspaces if s.path == self.blend_box.currentData()), None) if self.scene else None

    def _blend_changed(self):
        self._blend_states.reset()
        space = self._space()
        for i, spin in enumerate(self._parameters):
            spin.blockSignals(True)
            spin.setVisible(space is not None and i < len(space.dimensions))
            if space is not None and i < len(space.dimensions):
                dim = space.dimensions[i]
                spin.setRange(*dim.input_bounds)
                spin.setPrefix(dim.name + " ")
                spin.setToolTip(f"{dim.name}: input scale {dim.scale if dim.scale is not None else 1:g}; smoothing {dim.smoothing or 0:g}. Automatic actor inputs are Unverified.")
            spin.blockSignals(False)
        self.blend_scale.setVisible(space is not None)
        self.smoothing.setVisible(space is not None)
        self.restart_blend.setVisible(space is not None)
        if space is not None and space.loop is not None:
            self.loop.setChecked(space.loop)
        self._clip_changed()

    def _reset_blend(self):
        self._blend_states.reset()
        self._clip_changed()

    def _blend_frame(self, space, parameters):
        return self._blend_states.sample(space, parameters, self.seconds,
            playing=self._timer.isActive(), smoothing=self.smoothing.isChecked())

    def duration(self):
        space = self._space()
        if space:
            from .preview_pose import space_duration
            try:
                parameters = tuple(s.value() for s in self._parameters[:len(space.dimensions)])
                weights = self._blend_frame(space, parameters).weights
                return max(space_duration(space, clips, parameters, scale=self.blend_scale.value(), weights=weights)
                           for clips in (self.scene.clips, self.scene.after_clips))
            except ValueError:
                pass  # The supported single-clip preview remains usable.
        return max((duration_seconds(c) for c in self._clips() if c is not None), default=0.)

    def _clip_changed(self):
        end = self.duration()
        self.seconds = min(self.seconds, end)
        self.slider.blockSignals(True)
        self.slider.setRange(0, round(end * 1000))
        self.slider.setValue(round(self.seconds * 1000))
        self.slider.blockSignals(False)
        self.play.setEnabled(end > 0)
        if end <= 0:
            self.stop()
        self.render()

    def _step(self, delta):
        count = self.clip_box.count()
        if count:
            self.clip_box.setCurrentIndex((self.clip_box.currentIndex() + delta) % count)

    def watch(self, path):
        index = self.clip_box.findData(path)
        if index >= 0:
            self.clip_box.setCurrentIndex(index)

    def _show_views(self):
        mode = self.view_mode.currentData()
        self.splitter.widget(0).setVisible(mode != "After")
        self.splitter.widget(1).setVisible(mode != "Before")
        if mode == "Compare" and min(self.splitter.sizes()) == 0:
            self.splitter.setSizes([max(1,self.splitter.width()//2)]*2)
        self.render()

    def toggle(self):
        if self._timer.isActive():
            self.stop()
        elif self.duration() > 0:
            self._last_tick = time.monotonic()
            self._timer.start()
            self.play.setText("Pause")

    def stop(self):
        self._timer.stop()
        self.play.setText("Play")
        for view in self._views:
            view.set_moving(False)

    def seek(self, milliseconds):
        self._blend_states.reset()
        self.seconds = max(0., min(milliseconds / 1000., self.duration()))
        self.render()

    def _tick(self):
        now = time.monotonic()
        self.seconds += (now - self._last_tick) * self.speed.value()
        self._last_tick = now
        end = self.duration()
        if end <= 0:
            self.stop()
            return
        if self.seconds >= end:
            if self.loop.isChecked():
                self.seconds %= end
            else:
                self.seconds = end
                self.stop()
        self.slider.blockSignals(True)
        self.slider.setRange(0, round(end * 1000))
        self.slider.setValue(round(self.seconds * 1000))
        self.slider.blockSignals(False)
        started = time.monotonic()
        self.render()
        self._timer.setInterval(min(100, max(33, int((time.monotonic() - started) * 1250))))

    def render(self):
        if self.scene is None:
            return
        from .skinning import deform, skin_matrices
        from .window import PosedMesh
        import numpy as np
        clips = self._clips()
        messages = []
        space = self._space()
        # The shared clock owns looping. A shorter clip holds its endpoint;
        # seeking the end never wraps an individual character or attachment.
        for index, (view, session, clip) in enumerate(zip(self._views, (self.scene.before, self.scene.after), clips)):
            if space is not None and session.has_skeleton:
                from .preview_pose import apply_space
                try:
                    contributing, notes = apply_space(session, space, self.scene.clips if index == 0 else self.scene.after_clips,
                        tuple(s.value() for s in self._parameters[:len(space.dimensions)]), self.seconds,
                        looping=False, scale=self.blend_scale.value(),
                        weights=self._blend_frame(space, tuple(s.value() for s in self._parameters[:len(space.dimensions)])).weights)
                    messages.extend(notes)
                    messages.extend(space.limitations)
                    messages.append(f"Stored character scale: {space.scale if space.scale is not None else 1:g}; automatic actor inputs Unverified")
                    messages.append("Contributors: " + ", ".join(f"{p.rsplit('/', 1)[-1]} {w:.0%}" for p, w in contributing))
                except ValueError as error:
                    messages.append(f"Blend preview: Unverified — {error}")
                    if clip is not None:
                        session.apply_pose(clip, min(self.seconds, duration_seconds(clip)) * FPS)
            elif clip is not None and session.has_skeleton:
                session.apply_pose(clip, min(self.seconds, duration_seconds(clip)) * FPS)
            else:
                session.clear_pose()
            view.set_scene(session.hierarchy, session.placed_sockets())
            view.set_moving(self._timer.isActive())
            if (index == 0 and self.view_mode.currentData() == "After") or (index == 1 and self.view_mode.currentData() == "Before"):
                continue
            body = None
            if self.scene.body and session.has_skeleton:
                matrices = skin_matrices(session.hierarchy.parsed, session.pose_matrices) if session.pose_matrices is not None else None
                points = []
                for mesh in self.scene.body:
                    points.append(deform(mesh, matrices) if matrices is not None else mesh.rest[:, :3])
                body = PosedMesh(np.concatenate(points), self.scene.body_faces)
            part = session.descriptor_part(self.scene.prepared.plan.unit.primary_part)
            weapon = None
            if part:
                held = self.role.currentData() == "Held"
                socket = part.out_socket if held else part.in_socket
                child = part.out_child_socket if held else part.in_child_socket
                if self.chart_events.isChecked():
                    timeline = (self.scene.timelines[index].get(self.clip_box.currentData())
                                if self.scene.timelines else None)
                    if timeline and space is None and clip is not None:
                        socket, child = timeline.at(self.seconds, duration_seconds(clip), part, initial_held=held)
                        messages.append('Chart handoffs: Passed; initial state selected manually' if timeline.supported else
                                        'Chart handoffs: Unverified — ' + '; '.join(timeline.limitations))
                        held = (socket, child) == (part.out_socket, part.out_child_socket)
                    else:
                        messages.append('Chart handoffs: Unverified for this preview; using the initial state')
                matrix = session.attachment_matrix(socket, child)
                if matrix and self.scene.weapon:
                    weapon = self.scene.weapon.transformed(matrix)
                    if self.scene.equipment:
                        binding, _, mappings = self.scene.equipment
                        mapped, reason = mappings.get(space.path if space else self.clip_box.currentData(), ("", "No attachment animation mapping"))
                        equipment_clip = self.scene.clips.get(mapped)
                        if binding and equipment_clip and space is None:
                            from .preview_pose import attachment_points
                            points = attachment_points(binding, equipment_clip, self.seconds, matrix, looping=False)
                            weapon = PosedMesh(points, tuple(map(tuple, binding.mesh.faces)))
                            missing = binding.unmatched(equipment_clip)
                            messages.append(f"Equipment: {reason}" + (f" · {len(missing)} unmapped tracks: Unverified" if missing else " · track mapping Passed"))
                        elif binding and space and mapped in self.scene.relationships.spaces:
                            from .preview_pose import samples_for_space, blend_matrices
                            from .skinning import deform, skin_matrices
                            attachment_space = self.scene.relationships.spaces[mapped]
                            parameters = {d.name:s.value() for d,s in zip(space.dimensions,self._parameters)}
                            try:
                                values = tuple(parameters[d.name] for d in attachment_space.dimensions)
                                samples, _, notes = samples_for_space(attachment_space, self.scene.clips, values, self.seconds,
                                    looping=False,scale=self.blend_scale.value(),
                                    weights=self._blend_frame(attachment_space, values).weights)
                                world = blend_matrices(binding.skeleton, samples)
                                points = deform(binding.mesh,skin_matrices(binding.skeleton,world))
                                points = (np.column_stack((points,np.ones(len(points)))) @ np.asarray(matrix).reshape(4,4))[:,:3]
                                weapon = PosedMesh(points, tuple(map(tuple,binding.mesh.faces)))
                                messages.extend(notes)
                                unmatched = set(h for clip, _, _ in samples for h in binding.unmatched(clip))
                                if unmatched:
                                    messages.append(f'Equipment blend: {len(unmatched)} unmapped tracks; deformation Unverified')
                                messages.append("Equipment blend: mapped parameters, common clock; runtime graph Unverified")
                            except (ValueError,KeyError) as error:
                                messages.append(f"Equipment blend: Unverified — {error}")
                        elif mapped:
                            messages.append(f"Equipment: {reason} · deformation Unverified")
                point = session.attachment_point(socket, child)
                view.set_attachments({"held" if held else "stowed": point} if point else {})
            view.set_meshes(body, weapon)
        anchor = self._views[0]._root_anchor(self.scene.before.hierarchy)
        if anchor is not None and self._follow_anchor is not None and self.follow.isChecked():
            from .model import Vec3
            camera = self._views[0]._camera
            camera.target = Vec3(camera.target.x + anchor.x - self._follow_anchor.x,
                                 camera.target.y + anchor.y - self._follow_anchor.y,
                                 camera.target.z + anchor.z - self._follow_anchor.z)
            for view in self._views:
                view.update()
        self._follow_anchor = anchor
        self.time_label.setText(f"{self.seconds:.2f} / {self.duration():.2f} s")
        details = '\n'.join(dict.fromkeys((*self.scene.notes, *messages, 'In-game behavior: Unverified')))
        self.status.setText(tr(self._stale_message or ('Preview available · review checks and contributing clips' if any(clips) else 'Static preview · animation Unverified')))
        self.status.setToolTip(details)
        if self._status_details.toPlainText() != details:
            self._status_details.setPlainText(details)
