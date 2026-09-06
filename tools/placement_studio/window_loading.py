"""Bounded background preparation and UI-thread publication for the Studio."""
from __future__ import annotations

from .background import LatestTask
from .loading import MeshRequest, prepare_meshes


class StudioLoadingMixin:
    def _init_loading(self, enabled):
        self._background_loading = enabled
        self._model_task = LatestTask(self)
        self._model_task.setObjectName('model_preparation')
        self._model_task.ready.connect(self._model_prepared)
        self._mesh_task = LatestTask(self)
        self._mesh_task.setObjectName('mesh_preparation')
        self._mesh_task.ready.connect(self._meshes_prepared)
        self._mesh_requested = None
        self._mesh_ready = None
        self._mesh_body_ready = None
        self._model_loading = False

    def _request_model(self, model=None):
        from .editing import session_from_baseline
        from .session import PlacementSession

        self._stop_archive_content_load()
        self._mesh_task.cancel()
        self._mesh_requested = None
        self._model_loading = True
        baseline, needs_edits = self._baseline, self._edits is None
        self._weapon_box.setEnabled(False)
        self.statusBar().showMessage("Loading...")

        def work(cancelled, progress):
            models = PlacementSession.available_models(baseline) if model is None else ()
            selected = model or next(iter(models), "")
            if cancelled():
                return None
            session = PlacementSession.from_baseline(baseline, selected) if selected else None
            if cancelled():
                return None
            edits = session_from_baseline(baseline) if needs_edits else None
            return models, session, edits

        self._model_task.submit(work)

    def _model_prepared(self, result, error):
        from .session import KNOWN_MODELS

        self._model_loading = False
        self._weapon_box.setEnabled(True)
        if error or result is None:
            self.statusBar().showMessage(error)
            return
        models, session, edits = result
        if models:
            self._model_box.blockSignals(True)
            self._model_box.clear()
            for model in models:
                self._model_box.addItem(KNOWN_MODELS.get(model, model), model)
            self._model_box.blockSignals(False)
        if session is None:
            self.statusBar().clearMessage()
            return
        if self._session is not None and self._session.model != session.model:
            self._armour_choice = {}
        self._session = session
        if edits is not None:
            self._edits = edits
        self._populate_armour()
        self._start_archive_content_load()
        self._populate_weapons(select_first=True)

    def _ensure_meshes_prepared(self):
        """Keep the last scene while a captured selection is being read and decoded."""
        if self._model_loading:
            return False
        session = self._session
        parsed = getattr(session.hierarchy, "parsed", None)
        body_paths = tuple(self._base_body_paths(session.model))
        armour_paths = tuple(sorted(self._armour_choice.values()))
        index = getattr(self, "_armour_index", None)
        body_key = (id(parsed), body_paths, armour_paths, id(index))
        weapon = session.weapon
        from .meshes import weapon_mesh_path
        weapon_path = ((getattr(weapon, "mesh_path", "") or
                        weapon_mesh_path(weapon.weapon_id, session.model)) if weapon else "")
        weapon_entries = getattr(self, "_weapon_mesh_entries", {})
        if weapon_path not in self._baseline and weapon_path not in weapon_entries:
            weapon_path = ""
        key = (id(session), body_key, weapon_path)
        if self._mesh_ready == key:
            return True
        if self._mesh_requested == key:
            return False
        self._mesh_requested = key
        reuse = self._mesh_body_ready == body_key

        def entry(path):
            piece = index.piece(path) if index is not None else None
            return piece.source if piece is not None else None

        # Capture archive locations now; the worker never reads a live picker or session.
        request = MeshRequest(
            self._baseline, session.model, session.hierarchy,
            tuple((path, entry(path)) for path in body_paths),
            tuple((path, entry(path)) for path in armour_paths),
            (weapon_path, weapon_entries.get(weapon_path))
                if weapon_path not in self._weapon_mesh_cache else ("", None),
            tuple(self._skinned_meshes) if reuse else None,
            self._skinned_body_count if reuse else 0,
        )
        self.statusBar().showMessage("Loading...")
        self._mesh_task.submit(lambda cancelled, progress:
                               (key, prepare_meshes(request, cancelled, progress)))
        return False

    def _meshes_prepared(self, value, error):
        if error or value is None:
            self.statusBar().showMessage(error)
            return
        key, result = value
        if key != self._mesh_requested or result is None or self._model_loading:
            return
        body_changed = self._mesh_body_ready != key[1]
        self._mesh_ready = key
        self._mesh_body_ready = key[1]
        self._skinned_cache_model = self._session.model
        self._skinned_meshes = list(result.skinned)
        self._skinned_body_count = result.body_count
        self._skinned_faces = ()
        self._skinned_groups = None
        self._body_cache_model = self._session.model
        if body_changed:
            self._body_mesh_cached = result.proxy
            self._body_problems = list(result.problems)
            self._body_coverage = result.coverage
        if result.weapon_path:
            self._weapon_mesh_cache[result.weapon_path] = result.weapon
        self._refresh_scene()
        worn = len(result.skinned)
        self._armour_status.setText(f"{len(self._armour_choice)} piece(s) worn, {worn} skinned")
        self._report_status()

    def _request_archive_content(self, weapons):
        from .archive_loading import ArchiveRequest, prepare_archive_content
        from .armour import CHART_SLOT, WEAPON_PREFAB_SLOT
        from .corpus import game_root
        session, index = self._session, getattr(self, '_armour_index', None)
        if self._model_loading or session is None or index is None:
            return
        if getattr(self, '_archive_task', None) is None:
            self._archive_task = LatestTask(self)
            self._archive_task.setObjectName('archive_preparation')
            self._archive_task.ready.connect(self._archive_prepared)
        model = session.model
        paths = frozenset(self._baseline.paths())
        request = ArchiveRequest(
            game_root(), model, paths,
            tuple((path, entry) for path, entry in self._weapon_socket_entries.items()
                  if f'/{model}/' in path and path not in paths),
            tuple((piece.path, piece.source) for piece in index.pieces(model, WEAPON_PREFAB_SLOT)),
            tuple((piece.path, piece.source) for piece in index.pieces(model, CHART_SLOT)
                  if piece.path not in paths),
            frozenset(self._weapon_mesh_entries), weapons,
        )
        self._archive_task.submit(lambda cancelled, progress:
                                 (session, request, prepare_archive_content(request, cancelled, progress)))

    def _archive_prepared(self, value, error):
        if error or value is None:
            self.statusBar().showMessage(error)
            return
        session, request, result = value
        if session is not self._session or result is None or self._model_loading:
            return
        # Only in-memory registration remains on Qt, in bounded slices. Do not give the
        # worker the live resolver or edit history; edits made while loading must survive.
        from PySide6.QtCore import QTimer
        self._archive_load = self._publish_archive_content(session, request, result)
        timer = self._archive_load_timer = QTimer(self)
        timer.timeout.connect(self._step_archive_content_load)
        timer.start(0)

    def _publish_archive_content(self, session, request, result):
        errors = list(result.errors)
        for number, (path, data) in enumerate(result.sockets):
            try:
                session.add_socket_file(path, data)
            except Exception as exc:
                errors.append(f'{path}: {exc}')
            if number % self._CACHED_LOAD_SLICE == 0:
                yield
        if request.weapons:
            session._equipment_models = result.models
            session._equipment_model_errors = tuple(errors)
        if self._edits is not None:
            self._edits.add_base_files(dict(result.sockets + result.charts))
        yield
        if request.weapons:
            self._populate_weapons()
        self._refresh_animation()
        if errors:
            self._armour_status.setToolTip('\n'.join(errors))

    def _stop_loading(self):
        for name in ("_model_task", "_mesh_task", "_chart_task", "_archive_task"):
            task = getattr(self, name, None)
            if task is not None:
                task.shutdown()
