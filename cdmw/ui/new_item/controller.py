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
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal

from cdmw.domain.new_item.rules import ValidationIssue, has_errors
from cdmw.domain.new_item.spec import IconSource, ModelSource, NewItemSpec
from cdmw.models import ArchiveEntry
from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement, build_placed_import, fitted_placement, load_model_import_source, mesh_bounds, mesh_centroid
from cdmw.services.effect_catalogue import EffectCatalogue, EffectFacts, build_effect_catalogue, catalogue_signature, load_effect_catalogue, save_effect_catalogue
from cdmw.services.new_item_baseline import baseline_facts, baseline_lines
from cdmw.services.new_item_planning import NewItemPlan, NewItemPlanError
from cdmw.services.new_item_service import NewItemInstallRefused, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot, NewItemSnapshotError
from cdmw.ui.new_item.state import NewItemDraft, StatGrid, spec_from_draft, stat_grid_for, status_label, with_template
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
    #: a model file was read for the studio (a ModelImportSource), or discarded (None)
    model_import_changed = Signal(object)
    #: the imported model's placement over the template moved (a ModelPlacement)
    model_placement_changed = Signal(object)
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
        #: the model file read for the studio's own placement, and where it sits
        self.model_import: Optional[ModelImportSource] = None
        self.model_placement: ModelPlacement = ModelPlacement()
        #: the template's decoded preview (textures resolved), kept for the current template so
        #: a re-fit or an import does not decode it again (the worker fills it)
        self._template_models: Dict[tuple, object] = {}
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

    def template_name(self) -> str:
        """The template's internal name, or "" before one is chosen."""

        if self.snapshot is None or self.draft.template_key is None:
            return ""
        row = self.snapshot.rows.get(int(self.draft.template_key))
        return row.string_key if row is not None else ""

    def suggest_internal_name(self) -> str:
        """`<Template>_New`, or `_New2`, `_New3`... until no shipped item has the name."""

        template = self.template_name()
        if not template or self.snapshot is None:
            return ""
        taken = {row.string_key.casefold() for row in self.snapshot.rows.values()}
        for index in range(1, 100):
            candidate = f"{template}_New" if index == 1 else f"{template}_New{index}"
            if candidate.casefold() not in taken:
                return candidate
        return ""

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
        return stat_grid_for(row, self.snapshot.status_names, {key: r.string_key for key, r in self.snapshot.rows.items()}, self.draft.extra_stat_keys)

    def status_choices(self) -> Tuple[Tuple[int, str, bool], ...]:
        """Every StatusInfo entry as (key, label, carried by shipped equipment): the ones
        some shipped weapon or armour ladder carries first, then the rest by name."""

        if self.snapshot is None:
            return ()
        carried = self._equipment_status_keys()
        out = [(int(key), status_label(name), int(key) in carried) for key, name in self.snapshot.status_names.items()]
        return tuple(sorted(out, key=lambda item: (not item[2], item[1].casefold())))

    def _equipment_status_keys(self) -> frozenset:
        cached = getattr(self, "_equipment_status_cache", None)
        if cached is not None:
            return cached
        keys = set()
        if self.snapshot is not None:
            for row in self.snapshot.rows.values():
                if not self.snapshot.equip_type_name(row):
                    continue
                for level in row.enchant_levels:
                    for stat in level.stats:
                        keys.add(int(stat.status_key))
        self._equipment_status_cache = frozenset(keys)
        return self._equipment_status_cache

    def store_names(self) -> Tuple[str, ...]:
        return tuple(sorted(store.name for store in self.snapshot.stores)) if self.snapshot else ()

    def store_choices(self) -> Tuple[Tuple[str, str, int, bool], ...]:
        """Every store as (name, label, buyable line count, is the player's camp), the camp
        first, then the rest by name; a label reads "Store_Del_Equipment  (Equipment, 41 lines)"."""

        if self.snapshot is None:
            return ()
        out = []
        for store in self.snapshot.stores:
            name = str(store.name)
            parts = name.split("_")
            camp = len(parts) > 1 and parts[1].lower() == "camp"
            kind = parts[-1] if len(parts) > 2 else (parts[1] if len(parts) > 1 else name)
            count = len(store.buyable_entries)
            place = "your camp (base)" if camp else (parts[1] if len(parts) > 2 else "")
            lines = f"{count} line(s)" if count else "no lines yet"
            label = f"{name}  ({', '.join(item for item in (place, kind) if item)}, {lines})"
            out.append((name, label, count, camp))
        return tuple(sorted(out, key=lambda item: (not item[3], item[0].casefold())))

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

    def item_mesh_for_preview(self):
        """The item's mesh as it will be: the imported model, else the template's own.
        None when there is nothing to parse (no snapshot, no template, no mesh)."""

        from cdmw.modding.mesh_parser import parse_pac

        data = bytes(getattr(self.model_result, "rebuilt_data", b"") or b"")
        label = "imported model"
        if not data and self.snapshot is not None and self.draft.template_key is not None:
            try:
                family = self.snapshot.family(self.draft.template_key)
            except Exception:  # noqa: BLE001 - no mesh is a plain "None"
                return None
            primary = next((item for item in family.files_for("pac") if item.exists and item.path.lower().rsplit("/", 1)[-1] == f"{family.model_stem.lower()}.pac"), None)
            primary = primary or next((item for item in family.files_for("pac") if item.exists), None)
            if primary is None:
                return None
            data = self.snapshot.payload(primary.path)
            label = primary.path
        if not data:
            return None
        try:
            return parse_pac(data, label)
        except Exception:  # noqa: BLE001
            return None

    def item_preview_source(self):
        """What the Model and icon step's viewport shows, textured the way the Model
        Library and the Builder show it: a `(token, build)` pair, or None when there
        is nothing to show. `build(stop_event)` runs off the UI thread and returns a
        `ModelPreviewData` (the imported model's own preview, textures and all; else
        the template's mesh decoded from the archives with its textures resolved) or,
        when the decode will not go, the bare `ParsedMesh` of `item_mesh_for_preview`.
        `token` names the source, so a view already showing it is left alone."""

        source = self.model_import
        if source is not None:
            template = self._template_preview_build()
            if template is None:
                return None
            template_token, template_build = template
            placement = self.model_placement

            def build_scene(stop_event):
                from cdmw.ui.new_item.item_preview import PlacementScene

                model = source.baked_preview_mesh()
                return PlacementScene(template=template_build(stop_event), model=model, placement=placement, model_bounds=source.baked_bounds())

            return (("placement", id(source), source.bake_generation, template_token), build_scene)
        result = self.model_result
        model = getattr(result, "preview_model", None)
        if result is not None and model is not None and getattr(model, "meshes", None):
            return (("imported", id(result)), lambda _stop_event: model)
        if result is not None:
            mesh = self.item_mesh_for_preview()
            return (("imported-bare", id(result)), lambda _stop_event: mesh) if mesh is not None else None
        return self._template_preview_build()

    def _template_preview_build(self):
        """`(token, build)` for the template's own mesh: the archive decode with its
        textures, else the bare parse; None without a template."""

        snapshot = self.snapshot
        if snapshot is None or self.draft.template_key is None:
            return None
        entries = self.template_entries()
        if not entries:
            return None
        try:
            family = snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001
            return None
        stem = family.model_stem.lower()
        entry = next((item for item in entries if item.path.lower().rsplit("/", 1)[-1] == f"{stem}.pac"), entries[0])
        controller = self
        cache_key = (id(snapshot), entry.path)
        cache = self._template_models

        def build(stop_event):
            from cdmw.core.archive_preview_result_builder import build_archive_preview_result

            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            by_path, by_basename = snapshot.archive_index_maps()
            try:
                decoded = build_archive_preview_result(
                    entry,
                    texture_entries_by_normalized_path=by_path,
                    texture_entries_by_basename=by_basename,
                    enable_hkx_visual_preview=False,
                    stop_event=stop_event,
                )
            except Exception:  # noqa: BLE001 - the bare mesh still shows
                decoded = None
            model = getattr(decoded, "preview_model", None) if decoded is not None else None
            if model is not None and getattr(decoded, "preferred_view", "") == "model" and getattr(model, "meshes", None):
                cache.clear()
                cache[cache_key] = model
                return model
            return controller.item_mesh_for_preview()

        return (("template", self.draft.template_key, entry.path), build)

    def effect_preview_for_placement(self, stem: str = ""):
        """The chosen effect's simulation description with the draft's look applied, and a
        reader for its sprite textures, for the placement dialog's viewport; (None, None)
        when there is no snapshot, no effect, or the effect will not read."""

        from cdmw.domain.new_item.spec import EffectLook
        from cdmw.services.effect_preview_model import preview_effect_from_snapshot

        snapshot = self.snapshot
        chosen = str(stem or self.draft.effect_stem or "")
        if snapshot is None or not chosen:
            return None, None
        draft = self.draft
        look = EffectLook(
            color=tuple(float(v) for v in draft.effect_color) if draft.effect_color is not None else None,
            intensity=float(draft.effect_intensity), size=float(draft.effect_size),
            rate=float(draft.effect_rate), lifetime=float(draft.effect_lifetime),
        )
        try:
            preview = preview_effect_from_snapshot(snapshot, chosen, look)
        except Exception as exc:  # noqa: BLE001 - the box still places; the description is extra
            self.log_message.emit(f"The effect {chosen} gave no particle description: {exc}")
            return None, None

        def read_texture(path: str) -> Optional[bytes]:
            try:
                return snapshot.payload(path) if snapshot.has_entry(path) else None
            except Exception:  # noqa: BLE001
                return None

        return preview, read_texture

    def effect_box(self, stem: str = "") -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        """The chosen effect's bounding box at scale 1.0, or a metre cube before indexing."""

        facts = self.effect_facts(stem or self.draft.effect_stem)
        if facts is None or all(abs(v) < 1e-9 for v in (*facts.box_min, *facts.box_max)):
            return (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)
        return facts.box_min, facts.box_max

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

    def import_dependency_context(self):
        """A dependency context for importing a model over the template's mesh: the
        template's family files, everything under the family's model folder, and every
        entry whose basename starts with the family's model stem as the bounded member
        list, with the whole listing behind the path and basename maps (the texture
        resolver walks those, and a weapon's textures sit under `character/texture/`).
        Built from the studio's own listing, so the Archive Browser's selection plays
        no part."""

        from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext

        if self.snapshot is None or self.draft.template_key is None:
            return None
        try:
            family = self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001
            return None
        folder = str(family.model_folder or "").replace("\\", "/").strip("/").lower()
        stem = str(family.model_stem or "").lower()
        chosen: Dict[str, ArchiveEntry] = {}
        for item in family.files:
            if item.exists:
                key = str(item.path).replace("\\", "/").strip("/").lower()
                entry = self.snapshot.entries.get(key)
                if entry is not None:
                    chosen[key] = entry
        for key, entry in self.snapshot.entries.items():
            basename = key.rsplit("/", 1)[-1]
            if (folder and key.startswith(f"character/model/{folder}/")) or (stem and basename.startswith(stem)):
                chosen[key] = entry
        if not chosen:
            return None
        by_path, by_basename = self.snapshot.archive_index_maps()
        primary = self.template_entries()
        selected = primary[0] if primary else next(iter(chosen.values()))
        return ArchiveWorkflowDependencyContext(
            selected_entry=selected,
            entries=tuple(chosen.values()),
            entries_by_normalized_path=by_path,
            entries_by_basename=by_basename,
            remote=False,
        )

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
        issues = tuple(self.service.validate(spec, self.snapshot))
        if self.model_import is not None and self.model_result is None:
            issues += (ValidationIssue(
                code="model_placement_not_applied",
                field="model",
                message=f"{self.model_import.label} is imported but its placement is not applied yet: step 3, Apply the placement.",
            ),)
        return issues

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
        had_import = self.model_import is not None
        self.model_import = None
        self.model_placement = ModelPlacement()
        self.template_changed.emit(template_key)
        if had_import:
            self.model_import_changed.emit(None)

    def set_imported_model(self, entry: Optional[ArchiveEntry], result: object | None, scene: object | None = None) -> None:
        """Take a Builder result for the template's mesh; None clears it. `scene` is the
        scene import the Builder ran from, when the hand-off carried it: the plain-PBR
        route reads the source's own textures through it."""

        self.model_result = result
        self.model_entry = entry
        self.model_scene = scene if result is not None else None
        self.draft.model_source = ModelSource.IMPORTED if (result is not None or self.model_import is not None) else ModelSource.TEMPLATE
        self.plan = None
        self.model_changed.emit(result)

    # ------------------------------------------------------------------ the studio's own import

    def template_bounds(self):
        """The template mesh's bounds in the game's frame, for the first fit; None without one."""

        return mesh_bounds(self._template_mesh())

    def template_centroid(self):
        return mesh_centroid(self._template_mesh())

    def _fitted_placement(self, source: ModelImportSource) -> ModelPlacement:
        return fitted_placement(source.bounds, self.template_bounds(), source_centroid=source.centroid, template_centroid=self.template_centroid())

    def _template_mesh(self):
        saved, self.model_result = self.model_result, None
        try:
            return self.item_mesh_for_preview()
        finally:
            self.model_result = saved

    def start_model_import(self, path: Path) -> bool:
        """Read a model file (or a zip holding one) for the studio's own placement: the
        scene import and the source's textures, off the UI thread. On success the model
        shows over the template at a first fit; a result built before is dropped."""

        chosen = Path(path)
        if self.snapshot is None or self.draft.template_key is None:
            self.status_message.emit("Choose a template first; the model is placed over its mesh.", True)
            return False

        def task(log, stop_event):
            log(f"Reading {chosen.name}...")
            return load_model_import_source(chosen, stop_event=stop_event)

        def done(result: object) -> None:
            if not isinstance(result, ModelImportSource):
                self.status_message.emit("The model import finished with an unexpected result.", True)
                return
            self.model_import = result
            result.set_bake(self._fitted_placement(result))
            self.model_placement = ModelPlacement()
            if self.model_result is not None:
                self.set_imported_model(None, None)
            self.draft.model_source = ModelSource.IMPORTED
            self.plan = None
            self.model_import_changed.emit(result)
            self.model_placement_changed.emit(self.model_placement)

        def failed(message: str) -> None:
            self.status_message.emit(f"The model could not be read: {message}", True)

        return self._run("model_import", task, done, failed)

    def set_model_placement(self, placement: ModelPlacement) -> None:
        """Move the imported model (the gizmo, the numbers, a fit, a reset). A result
        built at another placement is dropped: it no longer says where the model sits."""

        self.model_placement = placement
        source = self.model_import
        if self.model_result is not None and source is not None and source.applied != (source.bake, placement):
            self.set_imported_model(None, None)
        self.plan = None
        self.model_placement_changed.emit(placement)

    def fit_model_placement(self) -> None:
        """Re-fit the model to the template: the fit is baked into the mesh the viewport
        and the build see, and the numbers go back to zero on top of it."""

        source = self.model_import
        if source is None:
            return
        source.set_bake(self._fitted_placement(source))
        if self.model_result is not None:
            self.set_imported_model(None, None)
        self.model_placement = ModelPlacement()
        self.plan = None
        self.model_import_changed.emit(source)
        self.model_placement_changed.emit(self.model_placement)

    def start_model_apply(self) -> bool:
        """Build the item's mesh from the imported model at its placement: the Builder's
        import over the template's mesh, headless, off the UI thread. The result is what
        the plan writes (the rebuilt mesh and its side files)."""

        source = self.model_import
        entries = self.template_entries()
        if source is None or not entries:
            self.status_message.emit("Import a model first; there is nothing to place.", True)
            return False
        entry = entries[0]
        placement = self.model_placement
        context = self.import_dependency_context()
        by_path = getattr(context, "entries_by_normalized_path", None)
        by_basename = getattr(context, "entries_by_basename", None)

        def task(log, stop_event):
            log(f"Building {entry.basename} from {source.label} at its placement...")
            return build_placed_import(entry, source, placement, entries_by_normalized_path=by_path, entries_by_basename=by_basename, stop_event=stop_event)

        def done(result: object) -> None:
            source.applied = (source.bake, placement)
            self.set_imported_model(entry, result, source.scene)

        def failed(message: str) -> None:
            self.status_message.emit(f"The placement could not be built: {message}", True)

        return self._run("model_apply", task, done, failed)

    def discard_model(self) -> None:
        """Drop the imported model, its placement and any result: back to the template's model."""

        self.model_import = None
        self.model_placement = ModelPlacement()
        if self.model_result is not None:
            self.set_imported_model(None, None)
        else:
            self.draft.model_source = ModelSource.TEMPLATE
            self.plan = None
        self.model_import_changed.emit(None)

    # ------------------------------------------------------------------ tasks

    def start_snapshot(self, entries: Iterable[ArchiveEntry], *, package_root: Optional[Path] = None) -> bool:
        """Read the tables from `entries`, or, with none, list the archives under
        `package_root` first (the shell's catalogue backend leaves the legacy list empty)."""

        frozen = tuple(entries)
        if not frozen and package_root is None:
            self.snapshot_failed.emit("The archive list is empty; scan the archives first.")
            return False
        task = snapshot_task(frozen, service=self.service, read_entry=self._read_entry, package_root=package_root)

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
