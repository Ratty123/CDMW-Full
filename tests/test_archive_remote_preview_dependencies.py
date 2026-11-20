from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveAssociationResult,
    ArchiveDurableIdentity,
    ArchiveEntryRef,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveViewMode,
)
from cdmw.domain.archives.catalogue_operations import PrepareEntriesRequest, PrepareEntriesResult, PrepareEntryResult
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    ArchivePreviewDependencySet,
    ArchiveRemotePreviewDependencyProvider,
    MAX_ARCHIVE_PREVIEW_DEPENDENCIES,
    MAX_ARCHIVE_PREVIEW_SNAPSHOTS,
    MAX_BEST_EFFORT_PREVIEW_DEPENDENCIES,
)
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin


class _CatalogueService(QObject):
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    progress = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[object, int]] = []
        self.cancelled: list[str] = []

    def find_association_candidates(self, request: object, *, ui_generation: int) -> str:
        self.requests.append((request, ui_generation))
        return f"association-{len(self.requests)}"

    def resolve_entries(self, request: object, *, ui_generation: int) -> str:
        self.requests.append((request, ui_generation))
        return f"resolve-{len(self.requests)}"

    def prepare_entries(self, request: object, *, ui_generation: int) -> str:
        self.requests.append((request, ui_generation))
        return f"prepare-{len(self.requests)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


def _dto(entry_id: int, path: str) -> ArchiveEntryDto:
    extension = Path(path).suffix.casefold()
    return ArchiveEntryDto(
        "session-a",
        entry_id,
        ArchiveDurableIdentity(path.casefold(), "c:/game/0009/0.pamt", 0, entry_id * 100),
        path,
        "C:/Game/0009/0.pamt",
        "C:/Game/0009/0.paz",
        0,
        entry_id * 100,
        20,
        40,
        0,
        extension,
        "0009/0.pamt",
        ArchiveEntryRole.MODEL if extension != ".dds" else ArchiveEntryRole.IMAGE,
        "model" if extension != ".dds" else "texture",
        True,
    )


def _prepared(dto: ArchiveEntryDto) -> PrepareEntryResult:
    return PrepareEntryResult(
        ArchiveEntryRef(dto.session_id, dto.entry_id, dto.identity, dto.path),
        f"C:/cache/{dto.entry_id}{dto.extension}",
        dto.original_size,
        f"sha-{dto.entry_id}",
        "prepared test source",
    )


def test_set_dependencies_include_every_models_materials_and_keep_selected_authority() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    primary, lower, shoulder = (_dto(1, "a_ub_01.pac"), _dto(2, "a_lb_01.pac"), _dto(3, "shoulder.pac"))
    own = (_dto(11, "upper.pac_xml"), _dto(12, "lower.pac_xml"), _dto(13, "shoulder.dds"))
    ready = []
    provider.ready.connect(lambda _, snapshot: ready.append(snapshot))
    assert provider.request(primary, ui_request_id=61, component_entries=(lower, shoulder))
    for number, (model, dependency) in enumerate(zip((primary, lower, shoulder), own), 1):
        assert service.requests[-1][0].entry_id == model.entry_id
        service.result_ready.emit(f"association-{number}", "find_association_candidates",
            ArchiveAssociationResult("session-a", model.entry_id, (dependency,), 1, False))
    request = service.requests[-1][0]
    assert set(request.entry_ids) == {1, 2, 3, 11, 12, 13}
    assert request.content_analysis_entry_id == 1
    service.result_ready.emit("prepare-4", "prepare_entry", PrepareEntriesResult(
        "session-a", tuple(_prepared(row) for row in (primary, lower, shoulder, *own)), 6, 6, 240))
    assert len(ready) == 1
    assert ready[0].selected_entry.path == primary.path
    assert {entry.path for entry in ready[0].entries} == {entry.path for entry in (primary, lower, shoulder, *own)}


def test_set_dependency_cancel_ignores_late_component_completion() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    primary, lower = _dto(1, "upper.pac"), _dto(2, "lower.pac")
    ready = []
    provider.ready.connect(lambda *_: ready.append(True))
    assert provider.request(primary, ui_request_id=1, component_entries=(lower,))
    service.result_ready.emit("association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 1, (), 0, False))
    provider.cancel(clear_snapshot=True)
    service.result_ready.emit("association-2", "find_association_candidates",
        ArchiveAssociationResult("session-a", 2, (), 0, False))
    assert service.cancelled == ["association-2"]
    assert len(service.requests) == 2 and not ready


@pytest.mark.parametrize("wrong_session,truncated", ((True, False), (False, True)))
def test_item_set_rejects_invalid_component_dependencies(wrong_session, truncated) -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    failures, ready = [], []
    provider.failed.connect(lambda *args: failures.append(args))
    provider.ready.connect(lambda *args: ready.append(args))
    assert provider.request(_dto(1, "upper.pac"), ui_request_id=1, component_entries=(_dto(2, "lower.pac"),))
    service.result_ready.emit("association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 1, (), 0, False))
    service.result_ready.emit("association-2", "find_association_candidates",
        ArchiveAssociationResult("other-session" if wrong_session else "session-a", 2, (), 0, truncated))
    assert failures and not ready and len(service.requests) == 2


def test_invalid_set_request_supersedes_pending_preview() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    ready, failures = [], []
    provider.ready.connect(lambda *args: ready.append(args))
    provider.failed.connect(lambda *args: failures.append(args))
    primary = _dto(1, "upper.pac")
    assert provider.request(primary, ui_request_id=1)
    invalid = replace(_dto(2, "lower.pac"), session_id="other-session")
    assert not provider.request(primary, ui_request_id=2, component_entries=(invalid,))
    service.result_ready.emit("association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 1, (), 0, False))
    assert service.cancelled == ["association-1"] and failures and not ready
    assert len(service.requests) == 1


# Kuku Marni Laser Helm (item 1002284) as Show Exact Links scopes it in the installed
# game, read 2026-11-17: the helm for each wearer, their prefabs and two icons.
_KUKU_HELM_SCOPE = (
    (219249, "character/bin__/prefab/1_pc/01_phm/armor/13_hel/cd_phm_00_hel_00_0363_index01_c.prefab", 1998),
    (223625, "character/bin__/prefab/1_pc/02_phw/armor/13_hel/cd_phw_01_hel_00_0363_index01_c.prefab", 1998),
    (241806, "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0363.pac", 358376),
    (245521, "character/model/1_pc/2_phw/armor/13_hel/cd_phw_01_hel_00_0363.pac", 351507),
    (2084028, "ui/texture/icon/itemicon_prefab_cd_phm_00_hel_00_0363_c.dds", 65664),
    (2084029, "ui/texture/icon/itemicon_prefab_cd_phm_00_hel_00_0363_index01_c.dds", 65664),
)


def _sized(entry_id: int, path: str, size: int) -> ArchiveEntryDto:
    return replace(_dto(entry_id, path), original_size=size)


_PREFAB = "character/bin__/prefab/"
_MODEL = "character/model/"
# (prefab, the PACs it lists) in the item's stem order, as the game's files read 2026-11-17.
_KUKU_HELM_PREFABS = (
    (_KUKU_HELM_SCOPE[0][1], (_KUKU_HELM_SCOPE[2][1],)),
    (_KUKU_HELM_SCOPE[1][1], (_KUKU_HELM_SCOPE[3][1],)),
)


def _listing(prefab: str, *models: ArchiveEntryDto) -> tuple[str, tuple[str, ...]]:
    return prefab, tuple(model.path for model in models)


def test_a_worn_set_leaves_out_another_wearer_s_copy() -> None:
    """Fredric, 2026-11-17: Item Finder opened the Kuku Marni Laser Helm twice. Its
    scope holds the male and the female helm, and the set drew both in one place.
    The item's prefabs say whose each file is."""
    from cdmw.domain.archives.item_sets import worn_set_members

    entries = tuple(_sized(*row) for row in _KUKU_HELM_SCOPE)
    male, female = entries[2], entries[3]
    assert worn_set_members(entries) == (male, female)  # Without the prefabs: every worn model.
    assert worn_set_members(entries, _KUKU_HELM_PREFABS) == (male,)
    assert worn_set_members(entries, _KUKU_HELM_PREFABS[::-1]) == (female,)
    # Crimson Chaser Mail (item 8700): a set per wearer; the female's lower body is
    # another model (`cd_phw_00_lb_00_0166`) than the male's.
    male_set = (
        _sized(243569, _MODEL + "1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0350.pac", 506589),
        _sized(241120, _MODEL + "1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_00_0350.pac", 175274),
        _sized(241178, _MODEL + "1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_belt_00_0001.pac", 143587),
        _sized(242290, _MODEL + "1_pc/1_phm/armor/14_sho/cd_phm_00_sho_0350.pac", 94490),
    )
    female_set = (
        _sized(246460, _MODEL + "1_pc/2_phw/armor/9_upperbody/cd_phw_01_ub_00_0350.pac", 368882),
        _sized(245060, _MODEL + "1_pc/2_phw/armor/10_lowerbody/cd_phw_00_lb_00_0166.pac", 374678),
        _sized(245628, _MODEL + "1_pc/2_phw/armor/14_sho/cd_phw_01_sho_00_0350.pac", 88768),
    )
    assert worn_set_members((*female_set, *male_set), (
        _listing(_PREFAB + "1_pc/01_phm/armor/9_upperbody/cd_phm_00_ub_00_0350.prefab", *male_set),
        _listing(_PREFAB + "1_pc/02_phw/armor/9_upperbody/cd_phw_01_ub_00_0350.prefab", *female_set),
    )) == male_set
    # Martial Monk's Cloth Robe (item 1000319): the robe refitted for the player and the
    # NPC's own robe it was made from. The player prefab comes first.
    npc = _MODEL + "2_mon/cd_m0001_00_twofeet/cd_m0001_00_orcumer/"
    robe = (
        _sized(243736, _MODEL + "1_pc/1_phm/armor/9_upperbody/cd_phm_m0001_00_orcumer_ub_0003.pac", 360843),
        _sized(241203, _MODEL + "1_pc/1_phm/armor/10_lowerbody/cd_phm_m0001_00_orcumer_lb_0003.pac", 113877),
    )
    npc_robe = (_sized(247789, npc + "cd_m0001_00_orcumer_ub_0003.pac", 512160),
                _sized(247784, npc + "cd_m0001_00_orcumer_lb_0003.pac", 85109))
    assert worn_set_members((*npc_robe, *robe), (
        _listing(_PREFAB + "1_pc/01_phm/armor/9_upperbody/cd_phm_m0001_00_orcumer_ub_0003.prefab", *robe),
        _listing(_PREFAB + "2_mon/cd_m0001_00_twofeet/cd_m0001_00_orcumer/cd_m0001_00_orcumer_ub_0003.prefab", *npc_robe),
    )) == robe


def test_a_worn_set_keeps_pieces_its_wearer_wears_together() -> None:
    """Real items whose one wearer's pieces sit in several prefabs or in another
    wearer's folders; none of them is a duplicate."""
    from cdmw.domain.archives.item_sets import worn_set_members

    # Barbaros Leather Armor (item 113660): one prefab lists an NPC-built orc upper body
    # with the human gloves, boots and belt. The gloves and boots also have item prefabs.
    barbaros = (
        _sized(249200, _MODEL + "2_mon/cd_m0001_00_twofeet/cd_m0001_05_pom/armor_south/9_upperbody/cd_m0001_00_so_pom_ub_12005.pac", 664768),
        _sized(243688, _MODEL + "1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_belt_00_0001.pac", 479651),
        _sized(241500, _MODEL + "1_pc/1_phm/armor/12_foot/cd_phm_00_foot_0056.pac", 251381),
        _sized(241214, _MODEL + "1_pc/1_phm/armor/11_hand/cd_phm_00_hand_0018_02.pac", 128818),
    )
    assert worn_set_members(barbaros[::-1], (
        _listing(_PREFAB + "2_mon/cd_m0001_00_twofeet/cd_m0001_05_pom/armor_south/cd_m0001_00_so_pom_ub_12005.prefab", *barbaros),
        _listing(_PREFAB + "1_pc/01_phm/armor/11_hand/cd_phm_00_hand_0018_02.prefab", barbaros[3]),
        _listing(_PREFAB + "1_pc/01_phm/armor/12_foot/cd_phm_00_foot_0056.prefab", barbaros[2]),
    )) == barbaros
    # Axiom Bracelet (item 1001129) and Angler's Pack (item 950042): two prefabs of the
    # same wearer, both worn.
    gauntlet = _MODEL + "6_object/object/t0281_abyss_gauntlet/"
    axiom = (_sized(253571, gauntlet + "cd_t0281_abyss_gauntlet_0001_l.pac", 5227124),
             _sized(253572, gauntlet + "cd_t0281_abyss_gauntlet_0001_r_sub01.pac", 146890))
    assert worn_set_members(axiom, (
        _listing(_PREFAB + "1_pc/01_phm/armor/18_acc/cd_phm_00_rinkband_0001_rb.prefab", axiom[0]),
        _listing(_PREFAB + "1_pc/01_phm/armor/18_acc/cd_phm_00_rinkband_wire_0001_r.prefab", axiom[1]),
    )) == axiom
    pack = (_sized(243071, _MODEL + "1_pc/1_phm/armor/18_acc/cd_phm_14_bag_0003.pac", 3384569),
            _sized(242962, _MODEL + "1_pc/1_phm/armor/18_acc/cd_phm_00_bag_belt_0003.pac", 182931))
    assert worn_set_members(pack, (
        _listing(_PREFAB + "1_pc/01_phm/armor/18_acc/cd_phm_14_bag_0003.prefab", pack[0]),
        _listing(_PREFAB + "1_pc/01_phm/armor/18_acc/cd_phm_00_bag_belt_0003.prefab", pack[1]),
    )) == pack
    # St. Halssius Priest's Cloak (item 1000325): no prefab lists the cloak itself; a
    # file no prefab names stays.
    cloak = (_sized(243110, _MODEL + "1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_0054_16.pac", 5787247),
             _sized(251358, _MODEL + "3_npc/1_nhm/armor_south/14_sho/cd_nhm_00_so_sho_10181.pac", 97930))
    assert worn_set_members(cloak, (
        _listing(_PREFAB + "1_pc/01_phm/armor/19_cloak/cd_phm_00_cloak_0054_16_t.prefab", cloak[1]),
    )) == cloak
    # A prefab naming no scoped model leaves the set whole.
    helm = tuple(_sized(*row) for row in _KUKU_HELM_SCOPE)
    assert worn_set_members(helm, ((_KUKU_HELM_SCOPE[0][1], (_MODEL + "other.pac",)),)) == helm[2:4]


def test_item_set_scope_reads_the_item_s_prefabs_in_its_own_order() -> None:
    from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult
    from cdmw.domain.archives.item_sets import worn_set_members
    from cdmw.ui.archive_browser.item_set_preview import ItemSetScopeResolver

    service = _CatalogueService()
    contents = {f"C:/cache/{entry_id}.prefab": models for entry_id, (_path, models) in zip((219249, 223625), _KUKU_HELM_PREFABS)}
    read = []
    resolver = ItemSetScopeResolver(service, prefab_reader=lambda path: read.append(path) or contents[path])
    ready, failures = [], []
    resolver.ready.connect(lambda session, rows, prefabs: ready.append((session, rows, prefabs)))
    resolver.failed.connect(failures.append)
    entries = tuple(_sized(*row) for row in _KUKU_HELM_SCOPE)
    ids = tuple(entry.entry_id for entry in entries)
    stems = ("cd_phm_00_hel_00_0363_index01_c", "cd_phw_01_hel_00_0363_index01_c", "cd_phm_00_hel_00_0363", "cd_phw_01_hel_00_0363")
    assert resolver.request("session-a", ids, 8, stems)
    service.result_ready.emit("resolve-1", "resolve_entries", ArchiveLookupResult("session-a", entries[::-1], len(ids), False))
    assert not ready
    prepare = service.requests[-1][0]
    assert prepare.entry_ids == (219249, 223625)  # The item's stem order; the icons are not read.
    prepared = PrepareEntriesResult("session-a", tuple(_prepared(entry) for entry in entries[:2]), 2, 2, 3996)
    service.result_ready.emit("prepare-2", "prepare_entry", prepared)
    assert read == ["C:/cache/219249.prefab", "C:/cache/223625.prefab"]
    assert ready[0][0] == "session-a" and ready[0][2] == _KUKU_HELM_PREFABS
    assert worn_set_members(ready[0][1], ready[0][2]) == (entries[2],)
    # A failed prefab read still opens the set, whole.
    assert resolver.request("session-a", ids, 9, stems)
    service.result_ready.emit("resolve-3", "resolve_entries", ArchiveLookupResult("session-a", entries, len(ids), False))
    service.request_failed.emit("prepare-4", "worker gone")
    assert len(ready) == 2 and ready[1][2] == () and not failures
    # Without the item's stems (an automation set) no prefab is read.
    assert resolver.request("session-a", ids, 10)
    service.result_ready.emit("resolve-5", "resolve_entries", ArchiveLookupResult("session-a", entries, len(ids), False))
    assert len(ready) == 3 and ready[2][2] == () and len(service.requests) == 5
    # A late prefab reply after cancellation is ignored.
    assert resolver.request("session-a", ids, 11, stems)
    service.result_ready.emit("resolve-6", "resolve_entries", ArchiveLookupResult("session-a", entries, len(ids), False))
    resolver.cancel()
    service.result_ready.emit("prepare-7", "prepare_entry", prepared)
    assert len(ready) == 3 and service.cancelled == ["prepare-7"]


def test_item_set_scope_resolves_all_pages_and_rejects_stale_or_partial_results() -> None:
    from cdmw.ui.archive_browser.item_set_preview import ItemSetScopeResolver
    from cdmw.domain.archives.item_sets import worn_set_members
    service = _CatalogueService()
    resolver = ItemSetScopeResolver(service)
    ready, failures = [], []
    resolver.ready.connect(lambda session, rows, _prefabs: ready.append((session, rows)))
    resolver.failed.connect(failures.append)
    lower = replace(_dto(1, "a_lb_01.pac"), original_size=500)
    upper = _dto(2, "a_ub_01.pac")
    dropped = _dto(3, "dropitem/large.pac")
    assert worn_set_members((lower, dropped, upper)) == (upper, lower)
    assert worn_set_members((dropped,)) == (dropped,)
    assert worn_set_members((lower, _dto(4, "a_ub_acc_01.pac"))) == (lower, _dto(4, "a_ub_acc_01.pac"))
    assert resolver.request("session-a", (1, 2, 3), 8)
    service.batch_ready.emit("resolve-1", "resolve_entries", ArchiveLookupResult("session-a", (lower, dropped), 3, False))
    service.result_ready.emit("resolve-1", "resolve_entries", ArchiveLookupResult("session-a", (upper,), 3, False))
    assert worn_set_members(ready[0][1]) == (upper, lower)
    assert resolver.request("session-a", (1, 2), 9)
    assert resolver.request("session-a", (3,), 10)
    service.result_ready.emit("resolve-2", "resolve_entries", ArchiveLookupResult("session-a", (lower, upper), 2, False))
    assert len(ready) == 1 and service.cancelled == ["resolve-2"]
    service.result_ready.emit("resolve-3", "resolve_entries", ArchiveLookupResult("session-a", (), 1, False))
    assert failures and len(ready) == 1
    assert resolver.request("session-a", (3,), 11)
    resolver.cancel()
    service.result_ready.emit("resolve-4", "resolve_entries", ArchiveLookupResult("session-a", (dropped,), 1, False))
    assert len(ready) == 1


def test_remote_preview_rejects_incomplete_discovery_below_the_candidate_limit() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    failures, ready = [], []
    provider.failed.connect(lambda request_id, message: failures.append((request_id, message)))
    provider.ready.connect(lambda *_: ready.append(True))
    selected = _dto(7, "character/dress.pac")
    assert provider.request(selected, ui_request_id=74)
    service.result_ready.emit(
        "association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (_dto(8, "character/dress.pac_xml"),), 1, True),
    )
    assert failures == [(74, "This choice has incomplete or ambiguous dependencies.")]
    assert not ready and len(service.requests) == 1  # No partial preparation/publication.
    assert provider.pending_ui_request_id is None


def _texture_request(provider, service):
    ready, failures = [], []
    provider.ready.connect(lambda request_id, snapshot: ready.append((request_id, snapshot)))
    provider.failed.connect(lambda request_id, message: failures.append((request_id, message)))
    selected = _dto(7, "ui/texture/image/worldmap/fog.dds")
    assert provider.request(selected, ui_request_id=74)
    return selected, ready, failures


def test_a_texture_previews_when_its_related_files_lookup_is_incomplete() -> None:
    """A texture is drawn from its own bytes: an incomplete list of related files does not refuse it."""

    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    selected, ready, failures = _texture_request(provider, service)
    sidecar = _dto(8, "ui/texture/image/worldmap/fog.xml")
    service.result_ready.emit(
        "association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (sidecar,), 1, True),
    )
    assert not failures
    prepare = service.requests[-1][0]
    assert isinstance(prepare, PrepareEntriesRequest) and prepare.entry_ids == (7, 8)
    service.result_ready.emit(
        "prepare-2", "prepare_entry", PrepareEntriesResult("session-a", (_prepared(selected), _prepared(sidecar)), 2, 2, 80),
    )
    assert [request_id for request_id, _snapshot in ready] == [74]
    snapshot = ready[0][1]
    assert not snapshot.truncated and [entry.path for entry in snapshot.entries] == [selected.path, sidecar.path]


def test_a_long_arbitrary_cut_of_related_files_is_dropped_not_prepared() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    selected, ready, failures = _texture_request(provider, service)
    many = tuple(_dto(100 + index, f"ui/texture/other_{index}.dds") for index in range(MAX_BEST_EFFORT_PREVIEW_DEPENDENCIES + 1))
    service.result_ready.emit(
        "association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, many, 4096, True),
    )
    assert not failures and service.requests[-1][0].entry_ids == (7,)
    service.result_ready.emit(
        "prepare-2", "prepare_entry", PrepareEntriesResult("session-a", (_prepared(selected),), 1, 1, 40),
    )
    assert len(ready) == 1 and ready[0][1].total_candidates == 0 and not ready[0][1].truncated


def test_a_failed_related_files_lookup_still_shows_a_texture_but_not_a_model() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    selected, ready, failures = _texture_request(provider, service)
    service.request_failed.emit("association-1", "The value cannot be an empty string.")
    assert not failures and service.requests[-1][0].entry_ids == (7,)
    # The file itself failing to prepare is still a failure.
    service.request_failed.emit("prepare-2", "The archive session was closed.")
    assert failures == [(74, "The archive session was closed.")] and not ready

    model = _dto(9, "character/dress.pac")
    assert provider.request(model, ui_request_id=75)
    service.request_failed.emit(f"association-{len(service.requests)}", "lookup failed")
    assert failures[-1] == (75, "lookup failed") and not ready


def test_remote_preview_provider_streams_one_bounded_candidate_snapshot() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    ready: list[tuple[int, ArchivePreviewDependencySet]] = []
    provider.ready.connect(lambda request_id, payload: ready.append((request_id, payload)))
    selected = _dto(7, "character/sword.pac")

    assert provider.request(selected, ui_request_id=41)
    request, generation = service.requests[0]
    assert request.session_id == "session-a"
    assert request.entry_id == 7
    assert request.limit == MAX_ARCHIVE_PREVIEW_DEPENDENCIES
    assert request.purpose.value == "preview"
    assert generation == 41

    first = _dto(8, "character/sword.pac_xml")
    second = _dto(9, "texture/sword_d.dds")
    service.batch_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (first,), 2, False),
    )
    service.batch_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (first, second), 2, False),
    )
    service.result_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (), 2, False),
    )
    assert service.requests[1][0].entry_ids == (7, 8, 9)
    assert service.requests[1][0].content_analysis_entry_id == 7
    service.batch_ready.emit(
        "prepare-2",
        "prepare_entry",
        PrepareEntriesResult("session-a", (_prepared(selected), _prepared(first)), 3, 3, 120),
    )
    service.batch_ready.emit(
        "prepare-2",
        "prepare_entry",
        PrepareEntriesResult("session-a", (_prepared(second),), 3, 3, 120),
    )
    service.result_ready.emit(
        "prepare-2",
        "prepare_entry",
        PrepareEntriesResult("session-a", (), 3, 3, 120),
    )

    assert len(ready) == 1
    request_id, snapshot = ready[0]
    assert request_id == 41
    assert [entry.path for entry in snapshot.entries] == [
        "character/sword.pac",
        "character/sword.pac_xml",
        "texture/sword_d.dds",
    ]
    assert snapshot.entries_by_normalized_path["character/sword.pac_xml"][0].offset == 800
    assert snapshot.entries_by_basename["sword_d.dds"][0].offset == 900
    assert snapshot.entries[0].prepared_path == Path("C:/cache/7.pac")
    assert snapshot.entries[0].prepared_sha256 == "sha-7"
    assert all(entry.prepared_path is not None for entry in snapshot.entries)
    assert not snapshot.truncated
    assert provider.snapshot_for(41, 7) is snapshot
    assert provider.snapshot_for(42, 7) is None
    assert provider.snapshot_for_entry(snapshot.selected_entry) is snapshot

    assert provider.request(_dto(10, "character/next.pac"), ui_request_id=42)
    assert provider.snapshot_for_entry(snapshot.selected_entry) is snapshot
    provider.cancel(clear_snapshot=True)
    assert provider.snapshot_for_entry(snapshot.selected_entry) is None


def test_dependency_snapshot_carries_actual_prepared_size_separately_from_archive_size() -> None:
    selected = _dto(7, "effect/mesh/leaf.pam")
    snapshot = ArchivePreviewDependencySet.from_dtos(
        selected, (), total_candidates=0, truncated=False,
        prepared={7: replace(_prepared(selected), size=23)},
    )

    assert snapshot.selected_entry.prepared_size == 23
    assert snapshot.selected_entry.orig_size == selected.original_size == 40


def test_remote_preview_provider_prioritizes_the_selected_items_logical_prefab() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    selected = _dto(7, "character/model/cd_m0001_00_so_phm_ub_31037.pac")
    physical_prefab = _dto(8, "character/prefab/cd_m0001_00_so_phm_ub_31037.prefab")
    sidecar = _dto(9, "character/model/cd_m0001_00_so_phm_ub_31037.pac_xml")
    logical_prefab = _dto(10, "character/prefab/cd_m0001_00_so_phm_ub_31035.prefab")

    assert provider.request(
        selected,
        ui_request_id=41,
        preferred_prefab_stems=("cd_m0001_00_so_phm_ub_31035",),
        scope_entry_ids=(logical_prefab.entry_id,),
    )
    lookup_request = service.requests[-1][0]
    assert lookup_request.entry_ids == (logical_prefab.entry_id,)
    service.result_ready.emit(
        "resolve-1",
        "resolve_entries",
        ArchiveLookupResult(
            "session-a",
            (logical_prefab,),
            1,
            False,
        ),
    )
    service.result_ready.emit(
        "association-2",
        "find_association_candidates",
        ArchiveAssociationResult(
            "session-a",
            selected.entry_id,
            (physical_prefab, sidecar),
            2,
            False,
        ),
    )

    request = service.requests[-1][0]
    assert request.entry_ids == (7, 10, 8, 9)


def test_remote_preview_provider_cancels_and_ignores_obsolete_requests() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    ready: list[int] = []
    provider.ready.connect(lambda request_id, _payload: ready.append(request_id))

    assert provider.request(_dto(7, "character/old.pac"), ui_request_id=1)
    assert provider.request(_dto(8, "character/new.pac"), ui_request_id=2)
    assert service.cancelled == ["association-1"]

    service.result_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (), 0, False),
    )
    service.result_ready.emit(
        "association-2",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 8, (), 0, False),
    )
    service.batch_ready.emit(
        "prepare-3",
        "prepare_entry",
        PrepareEntriesResult(
            "session-a",
            (_prepared(_dto(8, "character/new.pac")),),
            1,
            1,
            40,
        ),
    )
    service.result_ready.emit(
        "prepare-3",
        "prepare_entry",
        PrepareEntriesResult("session-a", (), 1, 1, 40),
    )

    assert ready == [2]
    assert provider.snapshot_for(2, 8) is not None


def _settle_stamps(provider, timeout: float = 10.0) -> None:
    """Wait for the provider's file stamps, taken on a worker thread, to arrive."""

    import time

    from tests.test_archive_remote_window_bridge import _app

    app = _app()
    deadline = time.monotonic() + timeout
    while provider.stamping and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()
    assert not provider.stamping


def _reusable_provider(tmp_path: Path, *, settle: bool = True):
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    pamt, paz = tmp_path / "0.pamt", tmp_path / "0.paz"
    pamt.write_bytes(b"owned catalogue")
    paz.write_bytes(b"owned archive")
    rows = tuple(replace(
        _dto(index, path), source_pamt=str(pamt), paz_file=str(paz),
        identity=ArchiveDurableIdentity(path.casefold(), str(pamt).casefold(), 0, index * 100),
    ) for index, path in ((7, "character/sword.pac"), (8, "texture/sword.dds")))
    prepared = []
    for row in rows:
        path = tmp_path / f"{row.entry_id}{row.extension}"
        payload = b"owned source " * 4
        path.write_bytes(payload)
        prepared.append(PrepareEntryResult(
            ArchiveEntryRef(row.session_id, row.entry_id, row.identity, row.path),
            str(path), len(payload), hashlib.sha256(payload).hexdigest(), "owned fixture",
        ))
    assert provider.request(rows[0], ui_request_id=1)
    service.result_ready.emit("association-1", "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (rows[1],), 1, False))
    service.result_ready.emit("prepare-2", "prepare_entry",
        PrepareEntriesResult("session-a", tuple(prepared), 2, 2, sum(item.size for item in prepared)))
    if settle:
        _settle_stamps(provider)
    return service, provider, rows[0]


def test_texture_followup_reuses_verified_snapshot_without_archive_operations(tmp_path: Path) -> None:
    from cdmw.ui.archive_browser.remote_window_bridge import ArchiveRemoteWindowBridge
    from tests.test_archive_preview_request_coalescing import _DispatchHost
    from tests.test_archive_remote_window_bridge import _app, _RemoteExportWindow

    app = _app()
    service, provider, selected = _reusable_provider(tmp_path)
    original = provider.snapshot_for(1, selected.entry_id)
    window = _RemoteExportWindow()
    bridge = ArchiveRemoteWindowBridge(window)
    bridge._preview_dependencies = provider
    bridge.model.publish_query(
        ArchiveQueryHandle(selected.session_id, "query-a", 1, 1),
        view_mode=ArchiveViewMode.FLAT, prime=False,
    )
    assert bridge.model.accept_page(ArchivePage(selected.session_id, "query-a", 1, 1, 0, (selected,)))
    window.archive_tree.setCurrentIndex(bridge.model.index(0, 0))
    host = _DispatchHost()
    host.archive_preview_request_id = 1
    host._archive_texture_request_id = window._archive_texture_request_id = 2
    host._archive_texture_request_loading = window._archive_texture_request_loading = True
    host.archive_remote_bridge = bridge
    host._set_archive_preview_base_detail_text = lambda *_args, **_kwargs: None
    host.set_status_message = lambda _message: None
    entry = bridge.current_compatibility_entry()
    host._render_archive_preview(entry, force=True)
    ready = []
    provider.ready.connect(lambda request_id, payload: ready.append((request_id, payload)))
    assert host._resolve_scheduled_remote_preview_dependencies(2, entry) == (None, True)
    assert len(service.requests) == 2
    assert provider.pending_ui_request_id == 2
    assert ready == [], "cached delivery must remain queued"
    _settle_stamps(provider)
    assert ready == [(2, original)]
    assert provider.snapshot_for(2, selected.entry_id) is original
    assert provider.snapshot_for(1, selected.entry_id) is None
    assert provider.pending_ui_request_id is None
    assert host._resolve_scheduled_remote_preview_dependencies(2, entry) == (original, False)


@pytest.mark.parametrize("change", ("pamt", "paz", "prepared", "scope", "session", "index", "refresh"))
def test_texture_followup_rebuilds_changed_or_ineligible_dependencies(tmp_path: Path, change: str) -> None:
    service, provider, selected = _reusable_provider(tmp_path)
    options = {"reuse_prepared": True}
    if change in {"pamt", "paz"}:
        # Change size as well as content; Windows may coalesce rapid write timestamps.
        Path(selected.source_pamt if change == "pamt" else selected.paz_file).write_bytes(b"changed archive contents")
    elif change == "prepared":
        (tmp_path / "8.dds").unlink()
    elif change == "scope":
        options["preferred_prefab_stems"] = ("different-item",)
    elif change == "session":
        selected = replace(selected, session_id="new-session")
    elif change == "index":
        provider._snapshot = replace(provider._snapshot, secondary_index_pending=True)
    else:
        options["reuse_prepared"] = False
    assert provider.request(selected, ui_request_id=2, **options)
    # A changed file is found by the stamp check on the worker; the lookup then starts.
    _settle_stamps(provider)
    assert len(service.requests) == 3
    assert provider.snapshot_for(2, selected.entry_id) is None


def test_the_set_s_file_stamps_are_taken_off_the_ui_thread(tmp_path: Path, monkeypatch) -> None:
    """Defect 2: stamping a set's dependencies held the UI thread for 1.9 s."""

    import threading

    threads: list[str] = []
    original = ArchiveRemotePreviewDependencyProvider._snapshot_file_stamps

    def recording(snapshot):
        threads.append(threading.current_thread().name)
        return original(snapshot)

    monkeypatch.setattr(ArchiveRemotePreviewDependencyProvider, "_snapshot_file_stamps", staticmethod(recording))
    service, provider, selected = _reusable_provider(tmp_path)
    assert threads == ["preview-dependency-stamps"]
    assert provider.request(selected, ui_request_id=2, reuse_prepared=True)
    _settle_stamps(provider)
    assert threads == ["preview-dependency-stamps"] * 2
    assert provider.snapshot_for(2, selected.entry_id) is not None
    assert len(service.requests) == 2


def test_a_follow_up_while_stamps_are_taken_reuses_the_snapshot(tmp_path: Path) -> None:
    """A texture follow-up right after the preview's dependencies arrived must not lose
    the reuse because their stamps are still being taken."""

    service, provider, selected = _reusable_provider(tmp_path, settle=False)
    ready = []
    provider.ready.connect(lambda request_id, payload: ready.append(request_id))
    assert provider.request(selected, ui_request_id=2, reuse_prepared=True)
    _settle_stamps(provider)
    assert ready == [2] and len(service.requests) == 2


@pytest.mark.parametrize("supersede", (False, True))
def test_reused_snapshot_delivery_respects_cancellation_and_selection(tmp_path: Path, supersede: bool) -> None:
    from tests.test_archive_remote_window_bridge import _app
    app = _app()
    _service, provider, selected = _reusable_provider(tmp_path)
    ready = []
    provider.ready.connect(lambda request_id, _payload: ready.append(request_id))
    assert provider.request(selected, ui_request_id=2, reuse_prepared=True)
    if supersede:
        provider.request(_dto(9, "character/other.pac"), ui_request_id=3)
    else:
        provider.cancel()
    app.processEvents()
    assert ready == []
    assert provider.snapshot_for(2, selected.entry_id) is None


def test_reused_snapshot_delivery_is_discarded_when_its_owner_is_deleted(tmp_path: Path) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent
    from tests.test_archive_remote_window_bridge import _app

    app = _app()
    _service, provider, selected = _reusable_provider(tmp_path)
    ready = []
    provider.ready.connect(lambda request_id, _payload: ready.append(request_id))
    assert provider.request(selected, ui_request_id=2, reuse_prepared=True)
    provider.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    assert ready == []


@pytest.mark.parametrize("stage", ("discovery", "preparation"))
def test_texture_followup_retargets_matching_work_already_running(stage: str) -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    selected = _dto(7, "character/sword.pac")
    ready = []
    provider.ready.connect(lambda request_id, _payload: ready.append(request_id))
    assert provider.request(selected, ui_request_id=1)
    discovery = ArchiveAssociationResult("session-a", 7, (), 0, False)
    if stage == "preparation":
        service.result_ready.emit("association-1", "find_association_candidates", discovery)
    before = len(service.requests)
    assert provider.request(selected, ui_request_id=2, reuse_prepared=True)
    assert len(service.requests) == before
    assert service.cancelled == []
    if stage == "discovery":
        service.result_ready.emit("association-1", "find_association_candidates", discovery)
    service.result_ready.emit("prepare-2", "prepare_entry",
        PrepareEntriesResult("session-a", (_prepared(selected),), 1, 1, 40))
    assert ready == [2]


def test_remote_preview_provider_retains_only_the_bounded_recent_snapshots() -> None:
    provider = ArchiveRemotePreviewDependencyProvider(_CatalogueService())
    selected_entries: list[ArchiveEntry] = []
    for index in range(MAX_ARCHIVE_PREVIEW_SNAPSHOTS + 1):
        dto = _dto(index, f"character/model_{index}.pac")
        snapshot = ArchivePreviewDependencySet.from_dtos(
            dto,
            (),
            total_candidates=0,
            truncated=False,
            prepared={dto.entry_id: _prepared(dto)},
        )
        selected_entries.append(snapshot.selected_entry)
        provider._remember_snapshot(snapshot)

    assert provider.snapshot_for_entry(selected_entries[0]) is None
    assert provider.snapshot_for_entry(selected_entries[-1]) is not None


def test_remote_preview_provider_resolves_a_bounded_snapshot_member() -> None:
    provider = ArchiveRemotePreviewDependencyProvider(_CatalogueService())
    selected = _dto(70, "character/model/hero.pac")
    dependency = _dto(71, "character/physics/hero.hkx")
    snapshot = ArchivePreviewDependencySet.from_dtos(
        selected,
        (dependency,),
        total_candidates=1,
        truncated=False,
        prepared={
            selected.entry_id: _prepared(selected),
            dependency.entry_id: _prepared(dependency),
        },
    )
    provider._remember_snapshot(snapshot)

    assert provider.snapshot_for_entry(snapshot.entries[1]) is snapshot


class _PreviewBridge:
    displays_v2 = True

    def __init__(self, snapshot: ArchivePreviewDependencySet | None) -> None:
        self.snapshot = snapshot
        self.requested: list[tuple[int, ArchiveEntry]] = []

    def preview_dependencies_for(
        self,
        _request_id: int,
        _entry: ArchiveEntry,
    ) -> ArchivePreviewDependencySet | None:
        return self.snapshot

    def preview_dependencies_pending_for(self, _request_id: int) -> bool:
        return False

    def request_preview_dependencies(self, request_id: int, entry: ArchiveEntry) -> bool:
        self.requested.append((request_id, entry))
        return True


class _PreviewHarness(ArchivePreviewWorkerMixin):
    def __init__(self, snapshot: ArchivePreviewDependencySet | None) -> None:
        self.shell = self
        self.archive = self
        self.textures = self
        self.archive_remote_bridge = _PreviewBridge(snapshot)
        selected = _entry("character/sword.pac", 700)
        self.scheduled_archive_preview_request = (5, selected, False, False)
        self.archive_preview_request_id = 5
        self.archive_preview_thread = None
        self.archive_preview_worker = None
        self.pending_archive_preview_request = None
        self.archive_sidecar_generation = 0
        self.archive_preview_cache_keys: dict[int, str] = {}
        self.archive_preview_cache: dict[str, object] = {}
        self.started: dict[str, object] | None = None
        self.detail = ""
        self.status = ""

    @property
    def archive_entries_by_normalized_path(self) -> object:
        raise AssertionError("v2 preview read the global path index")

    @property
    def archive_entries_by_basename(self) -> object:
        raise AssertionError("v2 preview read the global basename index")

    @property
    def archive_sidecar_entries_by_texture_path(self) -> object:
        raise AssertionError("v2 preview read the global sidecar path index")

    @property
    def archive_sidecar_entries_by_texture_basename(self) -> object:
        raise AssertionError("v2 preview read the global sidecar basename index")

    def _mesh_replacement_builder_active(self) -> bool:
        return False

    def _archive_basic_index_missing_for_lookup(self) -> bool:
        return False

    def _collect_archive_preview_loose_roots(self) -> list[Path]:
        return []

    def _archive_preview_cache_key(self, *_args: object, quality_tier: str, **_kwargs: object) -> str:
        return f"quality:{quality_tier}"

    def _find_archive_preview_companion_entry(self, _entry: object, **_kwargs: object) -> None:
        return None

    def _current_archive_performance_settings(self) -> object:
        return SimpleNamespace(quick_then_full_preview=False)

    def _show_archive_preview_loading_state(self, _entry: object) -> None:
        return None

    def _set_archive_preview_base_detail_text(self, text: str, **_kwargs: object) -> None:
        self.detail = text

    def set_status_message(self, text: str, **_kwargs: object) -> None:
        self.status = text

    def _start_archive_preview_worker(self, _request_id: int, entry: object, *_args: object, **kwargs: object) -> None:
        kwargs["entry"] = entry
        self.started = kwargs


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0.pamt"), Path("0.paz"), offset, 20, 40, 0, 0)


def test_v2_preview_flush_uses_only_remote_dependency_maps() -> None:
    snapshot = ArchivePreviewDependencySet.from_dtos(
        _dto(7, "character/sword.pac"),
        (_dto(8, "character/sword.pac_xml"),),
        total_candidates=1,
        truncated=False,
        prepared={
            7: _prepared(_dto(7, "character/sword.pac")),
            8: _prepared(_dto(8, "character/sword.pac_xml")),
        },
    )
    harness = _PreviewHarness(snapshot)
    harness.archive_remote_bridge.current_session = SimpleNamespace(
        session_id=snapshot.session_id, index_path="C:/cache/g/current/archive.ali"
    )

    harness._flush_scheduled_archive_preview_request()

    assert harness.started is not None
    assert harness.started["entry"] is snapshot.selected_entry
    assert harness.started["entry"].prepared_path == Path("C:/cache/7.pac")
    assert harness.started["texture_entries_by_normalized_path"] is snapshot.entries_by_normalized_path
    assert harness.started["texture_entries_by_basename"] is snapshot.entries_by_basename
    assert harness.started["sidecar_entries_by_texture_path"] == {}
    assert harness.started["sidecar_entries_by_texture_basename"] == {}
    assert harness.started["native_preview_dependency_entries"] is snapshot.entries
    assert harness.started["native_preview_dependency_entries_complete"] is True
    assert harness.started["native_preview_archive_index_path"] == Path("C:/cache/g/current/archive.ali")


def test_v2_preview_does_not_pass_a_different_sessions_index() -> None:
    snapshot = ArchivePreviewDependencySet.from_dtos(
        _dto(7, "character/sword.pac"), (), total_candidates=0, truncated=False,
        prepared={7: _prepared(_dto(7, "character/sword.pac"))},
    )
    harness = _PreviewHarness(snapshot)
    harness.archive_remote_bridge.current_session = SimpleNamespace(
        session_id="other-session", index_path="C:/cache/g/other/archive.ali"
    )
    harness._flush_scheduled_archive_preview_request()
    assert harness.started["native_preview_archive_index_path"] is None


def test_v2_preview_flush_waits_for_remote_dependencies_without_starting_worker() -> None:
    harness = _PreviewHarness(None)

    harness._flush_scheduled_archive_preview_request()

    assert harness.started is None
    assert len(harness.archive_remote_bridge.requested) == 1
    assert harness.archive_remote_bridge.requested[0][0] == 5
    assert harness.detail == "Resolving bounded archive preview dependencies..."


def test_v2_preview_flush_reissues_the_row_current_after_selection_settles() -> None:
    from cdmw.ui.archive_browser import workers as workers_module

    replacement = _entry("character/current.pac", 900)

    class _RemappedSelectionBridge(_PreviewBridge):
        def __init__(self) -> None:
            super().__init__(None)
            self.current_entries = [None, replacement]

        def current_compatibility_entry(self) -> ArchiveEntry | None:
            return self.current_entries.pop(0) if len(self.current_entries) > 1 else replacement

        def request_preview_dependencies(self, request_id: int, entry: ArchiveEntry) -> bool:
            self.requested.append((request_id, entry))
            return False

    class _RemappedSelectionHarness(_PreviewHarness):
        def __init__(self) -> None:
            super().__init__(None)
            self.shell = self
            self.archive = self
            self.textures = self
            self.archive_remote_bridge = _RemappedSelectionBridge()
            self._shutting_down = False
            self.reissued: list[ArchiveEntry] = []
            self.scheduled_delays: list[int] = []

        def _render_archive_preview(self, entry: ArchiveEntry, **_kwargs: object) -> None:
            self.reissued.append(entry)

        def _single_shot(self, delay_ms: int, callback: object) -> None:
            self.scheduled_delays.append(int(delay_ms))
            callback()

    harness = _RemappedSelectionHarness()
    original_timer = workers_module.QTimer
    workers_module.QTimer = SimpleNamespace(singleShot=harness._single_shot)
    try:
        harness._flush_scheduled_archive_preview_request()
    finally:
        workers_module.QTimer = original_timer

    assert harness.started is None
    assert harness.scheduled_delays == [workers_module.ARCHIVE_PREVIEW_SELECTION_RETRY_MS]
    assert harness.reissued == [replacement]


def test_v2_preview_selection_settle_retry_is_bounded() -> None:
    from cdmw.ui.archive_browser import workers as workers_module

    class _UnavailableSelectionBridge(_PreviewBridge):
        def current_compatibility_entry(self) -> None:
            return None

        def request_preview_dependencies(self, _request_id: int, _entry: ArchiveEntry) -> bool:
            raise AssertionError("unavailable selection reached the archive backend")

    class _UnavailableSelectionHarness(_PreviewHarness):
        def __init__(self) -> None:
            super().__init__(None)
            self.shell = self
            self.archive = self
            self.textures = self
            self.archive_remote_bridge = _UnavailableSelectionBridge(None)
            self._shutting_down = False
            self.scheduled_delays: list[int] = []
            self.cleared: list[str] = []

        def _clear_archive_preview(self, message: str) -> None:
            self.cleared.append(message)
            self.scheduled_archive_preview_request = None

        def _single_shot(self, delay_ms: int, callback: object) -> None:
            self.scheduled_delays.append(int(delay_ms))
            callback()

    harness = _UnavailableSelectionHarness()
    original_timer = workers_module.QTimer
    workers_module.QTimer = SimpleNamespace(singleShot=harness._single_shot)
    try:
        harness._flush_scheduled_archive_preview_request()
    finally:
        workers_module.QTimer = original_timer

    step = workers_module.ARCHIVE_PREVIEW_SELECTION_RETRY_MS
    limit = workers_module.ARCHIVE_PREVIEW_SELECTION_RETRY_LIMIT
    assert harness.scheduled_delays == [step * attempt for attempt in range(1, limit + 1)]
    assert harness.cleared == ["Select an archive file to preview it here."]
    assert harness.scheduled_archive_preview_request is None


def test_preview_flush_drops_an_in_flight_preview_core_prewarm() -> None:
    snapshot = ArchivePreviewDependencySet.from_dtos(
        _dto(7, "character/sword.pac"),
        (),
        total_candidates=0,
        truncated=False,
        prepared={7: _prepared(_dto(7, "character/sword.pac"))},
    )
    harness = _PreviewHarness(snapshot)
    cancelled: list[bool] = []
    harness._cancel_archive_preview_core_prewarm = lambda: cancelled.append(True)

    harness._flush_scheduled_archive_preview_request()

    # The service runs one job at a time, so the warm-up must yield before the
    # click's job is dispatched rather than queueing in front of it.
    assert cancelled == [True]
    assert harness.started is not None


def test_association_result_defaults_secondary_index_pending_off_the_wire() -> None:
    payload = {
        "session_id": "session-a",
        "entry_id": 7,
        "candidates": [],
        "total_candidates": 0,
        "truncated": False,
    }

    # A worker that predates the flag must still parse.
    assert ArchiveAssociationResult.from_wire(payload).secondary_index_pending is False
    assert ArchiveAssociationResult.from_wire(
        {**payload, "secondary_index_pending": True}
    ).secondary_index_pending is True


def test_pending_secondary_index_propagates_from_batches_into_the_snapshot() -> None:
    service = _CatalogueService()
    provider = ArchiveRemotePreviewDependencyProvider(service)
    ready: list[ArchivePreviewDependencySet] = []
    provider.ready.connect(lambda _request_id, payload: ready.append(payload))
    selected = _dto(7, "character/sword.pac")
    candidate = _dto(8, "character/sword.pac_xml")

    assert provider.request(selected, ui_request_id=41)
    service.batch_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (candidate,), 1, False, True),
    )
    service.result_ready.emit(
        "association-1",
        "find_association_candidates",
        ArchiveAssociationResult("session-a", 7, (), 1, False, True),
    )
    service.result_ready.emit(
        "prepare-2",
        "prepare_entry",
        PrepareEntriesResult(
            "session-a",
            (_prepared(selected), _prepared(candidate)),
            2,
            2,
            80,
        ),
    )

    assert len(ready) == 1
    assert ready[0].secondary_index_pending is True


class _SecondaryIndexRetryHarness(_PreviewHarness):
    def __init__(self, snapshot: ArchivePreviewDependencySet) -> None:
        super().__init__(snapshot)
        self.shell = self
        self.archive = self
        self.textures = self
        self._shutting_down = False
        self.scheduled_delays: list[int] = []
        self.rendered: list[object] = []
        self._entry_override = snapshot.selected_entry

    def _current_archive_entry(self) -> object:
        return self._entry_override

    def _render_archive_preview(self, entry: object, **_kwargs: object) -> None:
        self.rendered.append(entry)

    def _single_shot(self, delay_ms: int, callback: object) -> None:
        self.scheduled_delays.append(int(delay_ms))
        callback()


def _pending_snapshot(pending: bool) -> ArchivePreviewDependencySet:
    selected = _dto(7, "character/sword.pac")
    return ArchivePreviewDependencySet.from_dtos(
        selected,
        (),
        total_candidates=0,
        truncated=False,
        prepared={7: _prepared(selected)},
        secondary_index_pending=pending,
    )


def test_settled_dependencies_do_not_schedule_a_secondary_index_retry() -> None:
    harness = _SecondaryIndexRetryHarness(_pending_snapshot(False))
    harness._archive_preview_secondary_index_retries = 2

    harness._schedule_archive_preview_secondary_index_retry(harness.archive_remote_bridge.snapshot)

    assert harness.scheduled_delays == []
    assert harness._archive_preview_secondary_index_retries == 0


def test_pending_secondary_index_retries_with_a_bounded_backoff() -> None:
    from cdmw.ui.archive_browser import workers as workers_module

    snapshot = _pending_snapshot(True)
    harness = _SecondaryIndexRetryHarness(snapshot)
    original_timer = workers_module.QTimer
    workers_module.QTimer = SimpleNamespace(singleShot=harness._single_shot)
    try:
        for _ in range(workers_module.ARCHIVE_PREVIEW_SECONDARY_INDEX_RETRY_LIMIT + 2):
            harness._schedule_archive_preview_secondary_index_retry(snapshot)
    finally:
        workers_module.QTimer = original_timer

    limit = workers_module.ARCHIVE_PREVIEW_SECONDARY_INDEX_RETRY_LIMIT
    step = workers_module.ARCHIVE_PREVIEW_SECONDARY_INDEX_RETRY_MS
    assert harness.scheduled_delays == [step * attempt for attempt in range(1, limit + 1)]
    assert len(harness.rendered) == limit
    assert all(entry is snapshot.selected_entry for entry in harness.rendered)
