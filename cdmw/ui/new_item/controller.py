"""The New Item Studio's controller: holds the draft, talks to the service, owns the worker.

The panels never touch the service or the archives. They edit the draft and ask the
controller for facts about the template; the controller runs the snapshot, the plan,
the export and the install through :mod:`cdmw.workers.new_item_workers` on one owned
thread at a time, and reports back through signals. Nothing here writes to the game
except `start_install`, which goes through `ArchiveMutationService`.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal

from cdmw.domain.new_item.rules import ValidationIssue, has_errors
from cdmw.domain.new_item.spec import IconSource, ModelSource, NewItemSpec
from cdmw.models import ArchiveEntry
from cdmw.services.effect_catalogue import EffectCatalogue, EffectFacts, build_effect_catalogue, catalogue_signature, load_effect_catalogue, save_effect_catalogue
from cdmw.services.new_item_baseline import baseline_facts, baseline_lines
from cdmw.services.new_item_planning import NewItemPlan, NewItemPlanError
from cdmw.services.new_item_service import NewItemInstallRefused, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot, NewItemSnapshotError
from cdmw.ui.new_item.state import NewItemDraft, StatGrid, spec_from_draft, stat_grid_for, with_template
from cdmw.workers.new_item_workers import export_task, install_task, plan_task, snapshot_task
from cdmw.workers.utility_workers import UtilityWorker


class NewItemStudioController(QObject):
    busy_changed = Signal(bool)
    log_message = Signal(str)
    status_message = Signal(str, bool)
    snapshot_ready = Signal()
    snapshot_failed = Signal(str)
    template_changed = Signal(object)
    plan_ready = Signal(object)
    plan_failed = Signal(str, object)
    export_finished = Signal(object)
    install_finished = Signal(object)
    model_changed = Signal(object)
    effect_catalogue_ready = Signal()

    def __init__(
        self,
        *,
        service: Optional[NewItemService] = None,
        read_entry: Optional[Callable[[ArchiveEntry], bytes]] = None,
        synchronous: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or NewItemService()
        self._read_entry = read_entry
        self._synchronous = bool(synchronous)
        self.snapshot: Optional[NewItemSnapshot] = None
        self.draft = NewItemDraft()
        self.plan: Optional[NewItemPlan] = None
        self.model_result: object | None = None
        self.model_entry: Optional[ArchiveEntry] = None
        self.model_scene: object | None = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._lane: str = ""
        #: What every shipped effect is made of, once indexed (a minute, cached on disk).
        self.effect_catalogue: Optional[EffectCatalogue] = None
        #: Where the catalogue cache lives; None keeps it in memory only.
        self.effect_cache_path: Optional[Path] = None

    # ------------------------------------------------------------------ facts

    @property
    def busy(self) -> bool:
        return self._thread is not None

    @property
    def ready(self) -> bool:
        return self.snapshot is not None

    def template_options(self, text: str = "", *, limit: int = 60) -> List[Tuple[int, str, str]]:
        """(key, internal name, equip type) for equipment whose name or key matches `text`."""

        if self.snapshot is None:
            return []
        needle = str(text or "").strip().casefold()
        out: List[Tuple[int, str, str]] = []
        for key, row in self.snapshot.rows.items():
            equip = self.snapshot.equip_type_name(row)
            if not equip:
                continue
            if needle and needle not in row.string_key.casefold() and needle != str(key):
                continue
            out.append((key, row.string_key, equip))
            if len(out) >= limit:
                break
        out.sort(key=lambda item: item[1].casefold())
        return out

    def template_summary(self) -> Tuple[str, ...]:
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        row = self.snapshot.row(self.draft.template_key)
        facts = self.service.build_context(self.snapshot, row.key).template
        lines = [
            f"{row.string_key} (item {row.key}), {facts.equip_type_name or 'no equip type'}, item type {row.item_type}",
            f"{len(row.enchant_levels)} enchant level(s), {len(row.price_list)} price entr(ies), stack {row.max_stack_count}",
        ]
        try:
            family = self.snapshot.family(row.key)
            lines.append(f"model {family.model_stem}: owns {', '.join(family.owned_stems) or 'nothing'}; borrows {', '.join(family.borrowed_stems) or 'nothing'}")
            missing = [item.path for item in family.missing_files]
            if missing:
                lines.append(f"missing family files: {', '.join(missing)}")
            lines.extend(baseline_lines(baseline_facts(family, self.snapshot.payload)))
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            lines.append(f"model family: {exc}")
        groups = facts.item_group_keys
        lines.append(f"in {len(groups)} item group(s)")
        return tuple(lines)

    def stat_grid(self) -> Optional[StatGrid]:
        if self.snapshot is None or self.draft.template_key is None:
            return None
        row = self.snapshot.row(self.draft.template_key)
        return stat_grid_for(row, self.snapshot.status_names, {key: r.string_key for key, r in self.snapshot.rows.items()})

    def store_names(self) -> Tuple[str, ...]:
        return tuple(sorted(store.name for store in self.snapshot.stores)) if self.snapshot else ()

    def store_stock(self, store_name: str) -> Tuple[Tuple[int, str, str], ...]:
        """(item key, internal name, unlock requirement item name or "") per buyable line."""

        if self.snapshot is None:
            return ()
        try:
            store = self.snapshot.store(store_name)
        except NewItemSnapshotError:
            return ()
        names = []
        for entry in store.entries:
            if not entry.is_buyable:
                continue
            row = self.snapshot.rows.get(entry.item_key)
            requirement = ""
            if entry.requirement_item_key is not None:
                unlock = self.snapshot.rows.get(entry.requirement_item_key)
                requirement = unlock.string_key if unlock is not None else str(entry.requirement_item_key)
            names.append((entry.item_key, row.string_key if row is not None else str(entry.item_key), requirement))
        return tuple(names)

    def line_requirement(self, store_name: str, old_item_name: str) -> str:
        for _key, name, requirement in self.store_stock(store_name):
            if name == old_item_name:
                return requirement
        return ""

    def item_groups(self, text: str = "", *, limit: int = 200) -> Tuple[Tuple[int, str], ...]:
        if self.snapshot is None:
            return ()
        needle = str(text or "").strip().casefold()
        out = [(g.key, g.name) for g in self.snapshot.item_groups if not needle or needle in g.name.casefold()]
        return tuple(sorted(out, key=lambda item: item[1].casefold())[:limit])

    def template_group_names(self) -> Tuple[str, ...]:
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        key = self.draft.template_key
        return tuple(g.name for g in self.snapshot.item_groups if key in g.members)

    def languages(self) -> Tuple[str, ...]:
        return self.snapshot.languages if self.snapshot else ("eng",)

    def perk_catalogue(self, text: str = "", *, limit: int = 400) -> Tuple[Tuple[int, str], ...]:
        """(item key, label) for every gem the archives know (embedded socket items and every
        item of their type), by English name."""

        if self.snapshot is None:
            return ()
        needle = str(text or "").strip().casefold()
        english = self.snapshot.english.index()
        out = []
        for key in self.snapshot.perk_item_keys:
            row = self.snapshot.rows.get(key)
            if row is None:
                continue
            entry = english.get(row.name_key) if row.name_key else None
            label = f"{entry.text} ({row.string_key})" if entry is not None else row.string_key
            if needle and needle not in label.casefold() and needle != str(key):
                continue
            out.append((key, label))
        return tuple(sorted(out, key=lambda item: item[1].casefold())[:limit])

    def perk_label(self, key: int) -> str:
        for candidate, label in self.perk_catalogue():
            if candidate == int(key):
                return label
        return str(key)

    def template_socket_items(self) -> Tuple[int, ...]:
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        return tuple(self.snapshot.row(self.draft.template_key).socket_items)

    def effect_stems(self, text: str = "", *, limit: int = 300) -> Tuple[str, ...]:
        """Shipped effect stems matching `text`, alphabetical. With the catalogue indexed
        the match runs over the effect's emitters, textures and meshes as well as its
        stem, and every word of `text` must match; before, over the stem alone."""

        if self.snapshot is None:
            return ()
        if self.effect_catalogue is not None and len(self.effect_catalogue):
            return tuple(item.stem for item in self.effect_catalogue.search(text, limit=limit))
        needle = str(text or "").strip().casefold()
        stems = [stem for stem in self.snapshot.effect_stems if not needle or needle in stem.casefold()]
        return tuple(sorted(stems)[:limit])

    def effect_facts(self, stem: str) -> Optional[EffectFacts]:
        """What the catalogue knows about `stem`, or None before indexing."""

        if self.effect_catalogue is None:
            return None
        return self.effect_catalogue.get(stem)

    def load_effect_catalogue(self) -> bool:
        """Take the on-disk catalogue when it was built for these archives' effects."""

        if self.snapshot is None or self.effect_cache_path is None:
            return False
        catalogue = load_effect_catalogue(self.effect_cache_path, signature=catalogue_signature(self.snapshot))
        if catalogue is None:
            return False
        self.effect_catalogue = catalogue
        self.effect_catalogue_ready.emit()
        return True

    def start_effect_index(self) -> bool:
        """Read and decode every shipped effect into the catalogue (a minute, once)."""

        if self.snapshot is None:
            self.status_message.emit("Read the archives first.", True)
            return False
        if self.load_effect_catalogue():
            return True
        snapshot = self.snapshot

        def task(log, stop_event):
            return build_effect_catalogue(snapshot, on_log=log, stop_event=stop_event)

        def done(result: object) -> None:
            if isinstance(result, EffectCatalogue):
                self.effect_catalogue = result
                if self.effect_cache_path is not None:
                    try:
                        save_effect_catalogue(result, self.effect_cache_path)
                    except OSError as exc:
                        self.log_message.emit(f"The effect catalogue could not be cached: {exc}")
                self.effect_catalogue_ready.emit()

        return self._run("effects", task, done, lambda message: self.status_message.emit(message, True))

    def template_entries(self) -> Tuple[ArchiveEntry, ...]:
        """The template's own model files, for the Builder to import over."""

        if self.snapshot is None or self.draft.template_key is None:
            return ()
        try:
            family = self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001
            return ()
        return tuple(self.snapshot.entry(item.path) for item in family.files_for("pac") if item.exists)

    def current_spec(self) -> NewItemSpec:
        return spec_from_draft(self.draft, self.stat_grid())

    def validate(self) -> Tuple[ValidationIssue, ...]:
        if self.snapshot is None:
            return ()
        try:
            spec = self.current_spec()
        except ValueError:
            return ()
        return self.service.validate(spec, self.snapshot)

    # ------------------------------------------------------------------ edits

    def set_template(self, template_key: Optional[int]) -> None:
        if template_key is not None and (self.snapshot is None or template_key not in self.snapshot.rows):
            self.status_message.emit(f"Item {template_key} is not in the snapshot.", True)
            return
        self.draft = with_template(self.draft, template_key)
        self.plan = None
        self.model_result = None
        self.model_entry = None
        self.model_scene = None
        self.template_changed.emit(template_key)

    def set_imported_model(self, entry: Optional[ArchiveEntry], result: object | None, scene: object | None = None) -> None:
        """Take a Builder result for the template's mesh; None clears it. `scene` is the
        scene import the Builder ran from, when the hand-off carried it: the plain-PBR
        route reads the source's own textures through it."""

        self.model_result = result
        self.model_entry = entry
        self.model_scene = scene if result is not None else None
        self.draft.model_source = ModelSource.IMPORTED if result is not None else ModelSource.TEMPLATE
        self.plan = None
        self.model_changed.emit(result)

    # ------------------------------------------------------------------ tasks

    def start_snapshot(self, entries: Iterable[ArchiveEntry]) -> bool:
        frozen = tuple(entries)
        if not frozen:
            self.snapshot_failed.emit("The archive list is empty; scan the archives first.")
            return False
        task = snapshot_task(frozen, service=self.service, read_entry=self._read_entry)

        def done(result: object) -> None:
            if isinstance(result, NewItemSnapshot):
                self.snapshot = result
                self.snapshot_ready.emit()
            else:
                self.snapshot_failed.emit("The snapshot finished with an unexpected result.")

        return self._run("snapshot", task, done, self.snapshot_failed.emit)

    def start_plan(self) -> bool:
        self.plan = None
        if self.snapshot is None:
            self.plan_failed.emit("Read the archives first.", ())
            return False
        try:
            spec = self.current_spec()
        except ValueError as exc:
            self.plan_failed.emit(str(exc), ())
            return False
        issues = self.service.validate(spec, self.snapshot)
        if has_errors(issues):
            self.plan_failed.emit("; ".join(issue.message for issue in issues if issue.is_error), issues)
            return False
        icon_source: Optional[Path] = None
        if spec.icon is IconSource.GENERATED:
            try:
                icon_source = self._resolve_icon_source(spec)
            except ValueError as exc:
                self.plan_failed.emit(str(exc), ())
                return False
        task = plan_task(spec, self.snapshot, service=self.service, model=self.model_result, scene=self.model_scene, icon_source_path=icon_source)

        def done(result: object) -> None:
            if isinstance(result, NewItemPlan):
                self.plan = result
                self.plan_ready.emit(result)
            else:
                self.plan_failed.emit("The plan finished with an unexpected result.", ())

        return self._run("plan", task, done, lambda message: self.plan_failed.emit(message, ()))

    def _resolve_icon_source(self, spec: NewItemSpec) -> Path:
        """The image the icon is generated from: a file as given, or the best match in a folder."""

        text = str(self.draft.icon_source_path or "").strip()
        if not text:
            raise ValueError("Choose an image (or a folder of images) to generate the icon from, or keep the template's icon.")
        source = Path(text)
        if source.is_file():
            return source
        if not source.is_dir():
            raise ValueError(f"The icon source {source} does not exist.")
        from cdmw.services.item_icon_service import ItemIconService

        assert self.snapshot is not None
        template = self.snapshot.row(spec.template_key)
        stems = [spec.stem or ""] + [str(self.snapshot.family(spec.template_key).model_stem)]
        chosen, _candidates, message = ItemIconService().choose_source(
            source, target_path=f"itemicon_prefab_{spec.stem or ''}.dds", related_stems=[s for s in stems if s],
            display_name=spec.display_names.get("eng", "") or template.string_key,
        )
        if chosen is None:
            raise ValueError(message or f"No image in {source} matched the new item closely enough; pick a file instead.")
        return Path(chosen.path)

    def start_export(self, package_root: Path, manager: str) -> bool:
        if self.plan is None:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = export_task(self.plan, Path(package_root), service=self.service, manager=manager)
        return self._run("export", task, self.export_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_install(self, mutation_service) -> bool:
        if self.plan is None:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = install_task(self.plan, service=self.service, mutation_service=mutation_service, confirmed=True)
        return self._run("install", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def _run(self, lane: str, task, on_done: Callable[[object], None], on_error: Callable[[str], None]) -> bool:
        if self.busy:
            self.status_message.emit(f"Still busy with the previous step ({self._lane}); wait for it to finish.", True)
            return False
        if self._synchronous:
            try:
                result = task(self.log_message.emit, threading.Event())
            except (NewItemPlanError, NewItemSnapshotError, NewItemInstallRefused, ValueError, RuntimeError, OSError) as exc:
                on_error(str(exc))
                return True
            on_done(result)
            return True
        worker = UtilityWorker(task, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker, self._lane = thread, worker, lane
        self.busy_changed.emit(True)
        worker.log_message.connect(self.log_message.emit)

        def finish() -> None:
            self._thread = None
            self._worker = None
            self._lane = ""
            thread.quit()
            thread.wait(5000)
            worker.deleteLater()
            thread.deleteLater()
            self.busy_changed.emit(False)

        worker.completed.connect(on_done)
        worker.error.connect(on_error)
        worker.finished.connect(finish)
        thread.started.connect(worker.run)
        thread.start()
        return True

    # ------------------------------------------------------------------ shutdown

    def iter_shutdown_workers(self) -> Tuple[Tuple[str, QThread, object], ...]:
        return ((self._lane or "task", self._thread, self._worker),) if self._thread is not None else ()

    def request_shutdown(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.stop()
        thread = self._thread
        if thread is not None:
            thread.requestInterruption()
            thread.quit()

    def shutdown(self) -> None:
        self.request_shutdown()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.wait(5000)


__all__ = ["NewItemStudioController"]
