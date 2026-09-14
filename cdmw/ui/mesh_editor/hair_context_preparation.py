"""Resident character preparation for Hair, without a modal filename search."""

from dataclasses import dataclass, replace
from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.character_catalogue import CharacterCatalogDetailRequest, CharacterCatalogDetailResult
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation

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

    def arguments(self):
        return {"_archive_entry": self.head, "_archive_dependencies": self.dependencies,
                "_body_archive_entry": self.body, "_body_archive_dependencies": self.dependencies,
                "_hair_context_identity": (self.session_id, self.generation)}


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

    def start(self):
        self.cancel()
        session = self._service.current_session
        if session is None:
            self.failed.emit("Load the archive catalogue before opening Hair.")
            return
        self._session_id = session.session_id
        if self._cache is not None and self._cache.session_id == self._session_id:
            self.ready.emit(self._cache)
            return
        try:
            self._pending = True
            self._request = self._service.get_character_catalog_detail(
                CharacterCatalogDetailRequest(self._session_id, "appearance:" + DAMIANE_APPEARANCE + "#body"),
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
        heads = [m for m in detail.models if "/1_pc/2_phw/head/head/" in m.path.casefold() and m.extension == ".pac"]
        bodies = [m for m in detail.models if "/1_pc/2_phw/nude/cd_phw_00_nude_" in m.path.casefold() and m.extension == ".pac"]
        if len(heads) != 1 or len(bodies) != 1:
            self._pending = False
            self.failed.emit("Damiane's mounted appearance does not resolve to one compatible head and base body. Refresh the catalogue after checking the installed character data.")
            return
        self._head_id, self._body_id = heads[0].entry_id, bodies[0].entry_id
        # Retain the appearance and all its dependencies, but decode only the
        # fitting roles. CharacterPreviewPreparation remains the dependency owner.
        self._preparation.start(replace(detail, models=(heads[0], bodies[0])), self._token)

    def _prepared(self, token, inputs):
        if token != self._token or inputs.detail.session_id != self._session_id:
            return
        if not inputs.dependencies_complete:
            self._pending = False
            self.failed.emit("Damiane's character dependencies are incomplete. Refresh the mounted archives.")
            return
        head, body = inputs.entries_by_id[self._head_id], inputs.entries_by_id[self._body_id]
        paths, names = {}, {}
        for entry in inputs.entries:
            paths.setdefault(entry.path.casefold(), []).append(entry)
            names.setdefault(entry.basename.casefold(), []).append(entry)
        dependencies = ArchiveWorkflowDependencyContext(head, inputs.entries, paths, names, True)
        self._cache = HairCharacterContext(self._session_id, inputs.detail.context_key,
            inputs.detail.appearance_path, head, body, dependencies)
        self._pending = False
        self.ready.emit(self._cache)

    def _failure(self, request, error):
        if request == self._request:
            self._request = None
            self._pending = False
            self.failed.emit(str(getattr(error, "message", error)))
