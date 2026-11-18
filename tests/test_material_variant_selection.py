"""Which material variant a Browse preview draws, with and without the item in view.

The gauntlet ``cd_phm_00_hand_0003.pac`` has eleven variants (0 to 10) and is
eleven items: its own-name prefab draws variant 0, ``..._index01`` variant 1,
``..._index02`` variant 2, and so on (material coverage census, 18 Nov 2026).
"""
import threading
from types import SimpleNamespace

import pytest

from cdmw.rendering.native_preview_core import NativePreviewCoreAttempt
from cdmw.workers import archive_preview_native as owner
from tests import prefab_variant_fixtures as census

HAND_XML = "character/modelproperty/1_pc/1_phm/armor/11_hand/cd_phm_00_hand_0003.pac_xml"
HAND_XML_TEXT = "<ModelPropertyList>" + "".join(
    f'<ModelProperty Index="{index}"><SkinnedMeshMaterialWrapper _subMeshName="cd_phm_00_hand_0003"/>'
    "</ModelProperty>" for index in range(11)) + "</ModelPropertyList>"


def _worker(monkeypatch, prefabs, *, item_context):
    census.install(monkeypatch, files={HAND_XML: HAND_XML_TEXT.encode("utf-8")})
    pac = census.entry(census.HAND_0003)
    worker = owner.ArchivePreviewNativeMixin()
    worker.entry = pac
    worker.stop_event = threading.Event()
    worker.native_preview_dependency_entries = (pac, *(census.entry(path) for path in prefabs),
                                                census.entry(HAND_XML))
    worker.native_preview_dependency_entries_complete = True
    worker.native_preview_item_context = item_context
    worker.native_preview_core_cache_root = None
    worker.native_preview_core_package_root = None
    worker.companion_entry = None
    worker.render_settings = SimpleNamespace(use_textures_by_default=False)
    worker._prepare_native_preview_presentation_geometry = lambda: (b"", "", ())
    worker._prepare_native_head_component_geometry = lambda: ((), ())
    jobs = []

    def native(entry, **kwargs):
        jobs.append(kwargs)
        return NativePreviewCoreAttempt(status="error", fallback_reason="stubbed")

    monkeypatch.setattr(owner, "run_native_preview_core_preview_job", native)
    attempt = worker._run_native_preview_core_with_presentation(
        output_root=None, dds_cache_max_bytes=0, dds_cache_target_bytes=0)
    return jobs[0]["model_property_indices"], attempt.diagnostics.get("material_variant")


def test_a_pac_opened_alone_draws_the_variant_of_the_one_item_in_view(monkeypatch):
    indices, variant = _worker(monkeypatch, (census.HAND_0003_INDEX01,), item_context=False)
    assert indices == {census.HAND_0003: 1}
    assert variant["index"] == 1 and variant["from_prefab"]
    assert variant["selecting_prefabs"] == ["cd_phm_00_hand_0003_index01.prefab"]
    assert variant["available"] == list(range(11))


def test_a_pac_opened_alone_does_not_take_whichever_prefab_came_first(monkeypatch):
    # Before, the first prefab listed won: variant 2 here, one item's colours of three.
    indices, variant = _worker(
        monkeypatch, (census.HAND_0003_INDEX02, census.HAND_0003_PREFAB, census.HAND_0003_INDEX01),
        item_context=False)
    assert indices == {}
    assert variant["index"] == 0 and not variant["from_prefab"]
    assert variant["selected_variants"] == [0, 1, 2]


def test_an_items_prefab_still_picks_its_variant(monkeypatch):
    # The scoped item's prefab is first among the dependencies, and it wins.
    indices, variant = _worker(
        monkeypatch, (census.HAND_0003_INDEX02, census.HAND_0003_PREFAB), item_context=True)
    assert indices == {census.HAND_0003: 2}
    assert variant is None


@pytest.mark.parametrize("variant, line", [
    ({"index": 1, "from_prefab": True, "selecting_prefabs": ["cd_phm_00_hand_0003_index01.prefab"],
      "selected_variants": [1], "available": [0, 1, 2]},
     "Material variant 1 is shown, as cd_phm_00_hand_0003_index01.prefab selects; this model has variants 0, 1, 2."),
    ({"index": 0, "from_prefab": False, "selecting_prefabs": [], "selected_variants": [0, 1, 2],
      "available": [0, 1, 2]},
     "Material variant 0 is shown; this model has variants 0, 1, 2. Open the model from its item to see that "
     "item's colours."),
    ({"index": 0, "from_prefab": False, "selecting_prefabs": [], "selected_variants": [], "available": [0, 3]},
     "Material variant 0 is shown; this model has variants 0, 3. Open the model from its item to see that "
     "item's colours."),
])
def test_the_preview_details_say_which_variant_is_shown_and_which_exist(tmp_path, monkeypatch, variant, line):
    worker = owner.ArchivePreviewNativeMixin()
    worker.entry = census.entry(census.HAND_0003)
    worker.sidecar_generation = 0
    worker._native_preview_core_manifest_metadata = lambda _path: ((), None, (), 8)
    worker._native_preview_core_shader_fidelity_lines = lambda _path: ()
    attempt = NativePreviewCoreAttempt(status="ok", package_path=str(tmp_path),
                                       diagnostics={"material_variant": variant})
    result = worker._native_preview_core_package_result(
        attempt, {}, SimpleNamespace(package_dir=tmp_path), quality_tier="full", material_quality="direct")
    assert line in result.detail_text.splitlines()


def test_browse_says_whether_an_item_is_in_view():
    from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin

    def context(**bridge):
        return ArchivePreviewCacheMixin._archive_preview_item_context(
            SimpleNamespace(archive_remote_bridge=SimpleNamespace(**bridge) if bridge else None))

    assert context(displays_v2=True, item_scope_preferred_prefab_stems=("cd_phm_00_hand_0003_index01",)) is True
    assert context(displays_v2=True, item_scope_preferred_prefab_stems=()) is False
    assert context() is None


@pytest.mark.parametrize("prefabs, expected", [
    # Opened alone with one item's prefab in view: that item's variant.
    ((census.HAND_0003_INDEX02,), {census.HAND_0003: 2}),
    # Several items in view that disagree: variant 0, not the first one listed.
    ((census.HAND_0003_INDEX02, census.HAND_0003_INDEX01), {}),
])
def test_the_reference_preview_draws_the_variant_browse_would(tmp_path, monkeypatch, prefabs, expected):
    from cdmw.ui.archive_browser import reference_preview
    from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
    from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11

    census.install(monkeypatch)
    pac = census.entry(census.HAND_0003)
    dependencies = SimpleNamespace(entries=(pac, *(census.entry(path) for path in prefabs)),
                                   entries_by_normalized_path={})
    tasks, jobs = [], []

    def native(entry, **kwargs):
        jobs.append(kwargs)
        return NativePreviewCoreAttempt(status="error", fallback_reason="stubbed")

    monkeypatch.setattr(reference_preview, "run_native_preview_core_preview_job", native)

    class Browser:
        archive_remote_bridge = SimpleNamespace(displays_v2=True, item_scope_preferred_prefab_stems=(),
                                                prepared_dependencies_for=lambda _entry: dependencies)
        archive_package_root_edit = SimpleNamespace(text=lambda: "")
        archive_sidecar_generation = 0
        shell = SimpleNamespace(_run_utility_task=lambda **kwargs: tasks.append(kwargs["task"]),
                                set_status_message=lambda *_args, **_kwargs: None)
        _archive_preview_item_context = ArchivePreviewCacheMixin._archive_preview_item_context
        _current_archive_preview_result_for_reference_entry = lambda self, _entry: None
        _find_archive_preview_companion_entry = lambda self, _entry, **_kwargs: None
        _current_model_preview_render_settings = lambda self: SimpleNamespace(use_textures_by_default=False)
        _native_preview_core_cache_root = lambda self: tmp_path / "native"
        _native_preview_package_cache_root = lambda self: tmp_path / "packages"
        _native_preview_package_cache_mode = lambda self: "off"
        _native_preview_package_cache_budget = lambda self: (0, 0)
        _archive_model_renderer_backend = lambda self: ARCHIVE_MODEL_RENDERER_D3D11

    reference_preview.ArchiveReferencePreviewMixin._open_archive_reference_preview_entry(Browser(), pac)
    result = tasks[0](lambda _message: None)
    assert result.status == "error"
    assert jobs[0]["model_property_indices"] == expected
