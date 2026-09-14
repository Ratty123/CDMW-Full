"""Resident character preparation for Hair, without a modal filename search."""

from dataclasses import dataclass, replace
from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.character_catalogue import CharacterCatalogDetailRequest, CharacterCatalogDetailResult
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
from cdmw.domain.hair_characters import hair_character

# The supported character registration owns this appearance, not a guessed PAC.
DAMIANE_APPEARANCE = "character/appearance/1_pc/2_phw/cd_phw_damian/cd_phw_damian_00000.app_xml"


@dataclass(frozen=True)
class HairCharacterContext:
    session_id: str
    generation: str
    appearance_path: str
    head: object
    body: object
    dependencies: ArchiveWorkflowDependencyContext
    character: str = "Damiane"
    head_scale: float = 1.0
    body_scale: float = 1.0
    head_details: tuple = ()
    authored_descriptors: tuple = ()

    def arguments(self):
        return {"_archive_entry": self.head, "_archive_dependencies": self.dependencies,
                "_body_archive_entry": self.body, "_body_archive_dependencies": self.dependencies,
                "character": self.character, "_head_scale": self.head_scale, "_body_scale": self.body_scale,
                "_head_details": self.head_details,
                "_hair_authored_descriptors": dict(self.authored_descriptors),
                "_hair_context_identity": (self.session_id, self.generation, self.character)}


class HairContextPreparation(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self._preparation = CharacterPreviewPreparation(service, self)
        self._preparation.ready.connect(self._prepared)
        self._preparation.failed.connect(self._preparation_failed)
        service.result_ready.connect(self._result)
        service.request_failed.connect(self._failure)
        service.session_published.connect(self._session_changed)
        self._request = None
        self._token = 0
        self._session_id = ""
        self._cache = None
        self._pending = False

    def start(self, character="Damiane"):
        self.cancel()
        self._profile = hair_character(character)
        session = self._service.current_session
        if session is None:
            self.failed.emit("Load the archive catalogue before opening Hair.")
            return
        self._session_id = session.session_id
        if (self._cache is not None and self._cache.session_id == self._session_id
                and self._cache.character == self._profile.name):
            self.ready.emit(self._cache)
            return
        try:
            self._pending = True
            self._request = self._service.get_character_catalog_detail(
                CharacterCatalogDetailRequest(self._session_id, "appearance:" + self._profile.appearance_path + "#body"),
                ui_generation=self._token)
        except Exception as error:
            self._pending = False
            self.failed.emit(str(error))

    def cancel(self):
        self._token += 1
        self._pending = False
        self._preparation.cancel()
        request, self._request = self._request, None
        if request:
            self._service.cancel(request)

    def _session_changed(self, *_):
        pending = self._pending
        self.cancel()
        self._cache = None
        if pending:
            self.failed.emit("The archive catalogue changed while loading the character. Open Hair again after loading completes.")

    def _preparation_failed(self, token, message):
        if token == self._token and self._pending:
            self._pending = False
            self.failed.emit(message)

    def _result(self, request, _operation, detail):
        if request != self._request or not isinstance(detail, CharacterCatalogDetailResult):
            return
        self._request = None
        if detail.session_id != self._session_id:
            return
        heads = [m for m in detail.models if self._profile.accepts_reference(m.path, "head")]
        bodies = [m for m in detail.models if self._profile.accepts_reference(m.path, "body")]
        if len(heads) != 1 or len(bodies) != 1:
            self._pending = False
            self.failed.emit(f"{self._profile.name}'s mounted appearance does not resolve to one compatible head and base body. Refresh the catalogue after checking the installed character data.")
            return
        self._head_id, self._body_id = heads[0].entry_id, bodies[0].entry_id
        self._scales = {model_id: component.scale for component in detail.components for model_id in component.model_entry_ids}
        extras = tuple(m for m in detail.models if "/head/head_sub/" in m.path.casefold() and m.extension == ".pac")
        self._extra_ids = tuple(m.entry_id for m in extras)
        # Retain the appearance and all its dependencies, but decode only the
        # fitting roles. CharacterPreviewPreparation remains the dependency owner.
        self._preparation.start(replace(detail, models=(heads[0], bodies[0], *extras)), self._token)

    def _prepared(self, token, inputs):
        if token != self._token or inputs.detail.session_id != self._session_id:
            return
        if not inputs.dependencies_complete:
            self._pending = False
            self.failed.emit(f"{self._profile.name}'s character dependencies are incomplete. Refresh the mounted archives.")
            return
        head, body = inputs.entries_by_id[self._head_id], inputs.entries_by_id[self._body_id]
        paths, names = {}, {}
        for entry in inputs.entries:
            paths.setdefault(entry.path.casefold(), []).append(entry)
            names.setdefault(entry.basename.casefold(), []).append(entry)
        dependencies = ArchiveWorkflowDependencyContext(head, inputs.entries, paths, names, True)
        from pathlib import PurePosixPath
        descriptors = []
        for component in inputs.detail.components:
            name = PurePosixPath(component.name.replace("\\", "/")).stem.casefold()
            choices = [entry for i in component.context_entry_ids
                if (entry := inputs.entries_by_id.get(i)) is not None
                and entry.basename.casefold() in {name + ".prefabdata_xml", name + ".prefabdata.xml"}]
            if len(choices) > 1:
                self._pending = False
                self.failed.emit("The mounted appearance has ambiguous component descriptors.")
                return
            for i in component.model_entry_ids:
                if i in inputs.entries_by_id:
                    descriptors.append((inputs.entries_by_id[i].path.casefold(), choices[0] if choices else None))
        self._cache = HairCharacterContext(self._session_id, inputs.detail.context_key,
            inputs.detail.appearance_path, head, body, dependencies, self._profile.name,
            self._scales.get(self._head_id, 1.0), self._scales.get(self._body_id, 1.0),
            tuple((inputs.entries_by_id[i], self._scales.get(i, 1.0)) for i in self._extra_ids), tuple(descriptors))
        self._pending = False
        self.ready.emit(self._cache)

    def _failure(self, request, error):
        if request == self._request:
            self._request = None
            self._pending = False
            self.failed.emit(str(getattr(error, "message", error)))
