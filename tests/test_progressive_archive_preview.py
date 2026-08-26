import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.core import archive
from cdmw.core.archive_mesh_appearance import (
    apply_archive_mesh_appearance,
    apply_archive_mesh_appearance_to_preview_model,
    apply_loose_character_appearance,
    resolve_loose_character_appearance_sources,
    write_character_appearance_bundle_manifest,
)
from cdmw.core.common import RunCancelled
from cdmw.models import (
    ArchiveEntry,
    ArchivePreviewResult,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
)
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.ui.archive_browser.preview_loading import ArchivePreviewLoadingMixin
from cdmw.ui.archive_browser.workers import _archive_preview_debounce_ms
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker


def _entry(path: str, extension: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("package.pamt"),
        paz_file=Path("package_0.paz"),
        offset=0,
        comp_size=100,
        orig_size=100,
        flags=0,
        paz_index=0,
    )


def _preview_model(face_count: int, *, fmt: str = "pac", lod_index: int = -1, lod_count: int = 0) -> ModelPreviewData:
    positions = []
    for index in range(face_count):
        base = float(index) * 2.0
        positions.extend(((base, 0.0, 0.0), (base + 1.0, 0.0, 0.0), (base, 1.0, 0.0)))
    indices = list(range(face_count * 3))
    mesh = ModelPreviewMesh(
        material_name="mat",
        positions=positions,
        normals=[(0.0, 0.0, 1.0)] * len(positions),
        texture_coordinates=[(0.0, 0.0)] * len(positions),
        indices=indices,
    )
    return ModelPreviewData(
        path=f"mesh.{fmt}",
        format=fmt,
        mesh_count=1,
        vertex_count=len(positions),
        face_count=face_count,
        lod_index=lod_index,
        lod_count=lod_count,
        meshes=[mesh],
    )


class ProgressiveArchivePreviewTests(unittest.TestCase):
    def test_archive_preview_support_slots_include_sparse_emissive_maps(self) -> None:
        settings = SimpleNamespace(
            disable_all_support_maps=False,
            disable_normal_map=False,
            disable_material_map=False,
            disable_height_map=False,
        )

        self.assertEqual(
            ("normal", "material", "height", "emissive"),
            ArchivePreviewCacheMixin._archive_preview_support_texture_slots(settings),
        )

    def test_full_dotnet_package_uses_one_canonical_material_synthesis_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "canonical-package"
            worker = ArchivePreviewWorker(
                request_id=1,
                entry=_entry("character/model/body.pac", ".pac"),
                companion_entry=None,
                texture_entries_by_normalized_path={},
                texture_entries_by_basename={},
                sidecar_entries_by_texture_path=None,
                sidecar_entries_by_texture_basename=None,
                loose_search_roots=(),
                attach_preview_images=False,
                native_preview_package_cache_root=Path(temp_dir),
            )
            model = _preview_model(1)
            payload = ArchivePreviewResult(
                status="ok",
                preview_model=model,
                preferred_view="model",
            )
            prepare_calls: list[dict[str, object]] = []

            def prepare(preview_model: object, **kwargs: object):
                prepare_calls.append(dict(kwargs))
                return preview_model, SimpleNamespace()

            with (
                patch(
                    "cdmw.workers.archive_preview_workers.build_archive_preview_result",
                    return_value=payload,
                ),
                patch(
                    "cdmw.workers.archive_preview_workers.prepare_model_preview",
                    side_effect=prepare,
                ),
                patch(
                    "cdmw.workers.archive_preview_workers.build_or_lookup_dotnet_preview_package_from_model",
                    return_value=SimpleNamespace(package_dir=package_dir),
                ),
            ):
                result = worker._build_archive_preview_payload(
                    quality_tier="full",
                    render_settings=ModelPreviewRenderSettings(),
                )

        self.assertEqual(1, len(prepare_calls))
        self.assertIs(False, prepare_calls[0]["enable_material_combiner"])
        self.assertEqual(str(package_dir), result.dotnet_preview_package_path)

    def test_native_model_preview_uses_key_repeat_selection_dwell(self) -> None:
        # Still above the ~30 ms key-repeat interval, so a held arrow key keeps
        # resetting the timer and only the row it settles on starts a preview.
        self.assertEqual(60, _archive_preview_debounce_ms(_entry("character/model/body.pac", ".pac")))
        self.assertEqual(60, _archive_preview_debounce_ms(_entry("character/model/body.pam", ".pam")))
        self.assertEqual(60, _archive_preview_debounce_ms(_entry("character/model/body.pamlod", ".pamlod")))
        self.assertEqual(90, _archive_preview_debounce_ms(_entry("ui/texture/icon.dds", ".dds")))
        self.assertEqual(90, _archive_preview_debounce_ms(None))

    def test_quick_preview_resolves_dot_xml_material_sidecar(self) -> None:
        mesh = _entry("character/model/body.pac", ".pac")
        sidecar = _entry("character/model/body.pac.xml", ".xml")
        owner = SimpleNamespace(
            archive_entries_by_basename={sidecar.basename.lower(): [sidecar]},
            archive_sidecar_generation=7,
        )

        result = ArchivePreviewLoadingMixin._quick_archive_model_preview_result(owner, mesh)

        self.assertIsNotNone(result)
        self.assertEqual(7, result.sidecar_generation)
        self.assertEqual(1, len(result.model_texture_references))
        self.assertIs(sidecar, result.model_texture_references[0].resolved_entry)

    def test_native_preview_emits_quick_metadata_before_full_generation(self) -> None:
        worker = ArchivePreviewWorker(
            request_id=1,
            entry=_entry("character/model/body.pac", ".pac"),
            companion_entry=None,
            texture_entries_by_normalized_path={},
            texture_entries_by_basename={},
            sidecar_entries_by_texture_path=None,
            sidecar_entries_by_texture_basename=None,
            loose_search_roots=(),
            native_preview_core_enabled=True,
            emit_quick_preview=True,
        )
        order: list[str] = []
        quick_payload = object()
        native_attempt = object()

        with (
            patch.object(worker, "_cached_preview_payload", return_value=None),
            patch.object(worker, "_durable_native_preview_cache_payload", return_value=None),
            patch.object(worker, "_native_preview_core_supported_for_entry", return_value=True),
            patch.object(
                worker,
                "_quick_archive_model_preview_payload",
                side_effect=lambda: order.append("quick_build") or quick_payload,
            ),
            patch.object(
                worker,
                "_emit_preview_payload",
                side_effect=lambda _payload: order.append("quick_emit"),
            ),
            patch.object(
                worker,
                "_try_native_preview_core",
                side_effect=lambda: order.append("native_build") or native_attempt,
            ),
            patch.object(
                worker,
                "_emit_native_preview_core_attempt",
                side_effect=lambda _attempt, _timings: order.append("full_emit") or True,
            ),
        ):
            worker.run()

        self.assertEqual(["quick_build", "quick_emit", "native_build", "full_emit"], order)

    def test_quick_metadata_keeps_running_native_renderer_source_guard(self) -> None:
        source = Path("cdmw/ui/archive_browser/preview_result.py").read_text(encoding="utf-8")
        quick_guard = source[source.index('and preferred_view == "info"'):source.index('if preferred_view == "image"')]

        self.assertIn('getattr(result, "quality_tier", "")', quick_guard)
        self.assertIn('== "quick"', quick_guard)
        self.assertIn("self._archive_isolated_renderer_process_running()", quick_guard)
        self.assertIn("return 0.0", quick_guard)

    def test_loose_preview_bypasses_cache_so_dependency_changes_refresh(self) -> None:
        class CacheKeyHarness(ArchivePreviewCacheMixin):
            archive_sidecar_generation = 0

            @staticmethod
            def _archive_model_renderer_backend() -> str:
                return "software"

            @staticmethod
            def _current_model_preview_render_settings() -> object:
                return SimpleNamespace(
                    disable_all_support_maps=False,
                    disable_normal_map=False,
                    disable_material_map=False,
                    disable_height_map=False,
                    visible_texture_mode="mesh_base_first",
                    preview_texture_max_dimension=2048,
                    low_quality_texture_max_dimension=512,
                    flip_texture_v=False,
                    high_quality_by_default=True,
                    use_textures_by_default=True,
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            loose_root = root / "loose"
            loose_path = loose_root / "ui" / "texture" / "icon.dds"
            loose_path.parent.mkdir(parents=True)
            loose_path.write_bytes(b"first")
            entry = ArchiveEntry(
                path="ui/texture/icon.dds",
                pamt_path=root / "0001" / "0.pamt",
                paz_file=root / "0001" / "0.paz",
                offset=0,
                comp_size=5,
                orig_size=5,
                flags=0,
                paz_index=0,
            )
            harness = CacheKeyHarness()
            archive_key = harness._archive_preview_cache_key(entry, [loose_root])
            first_key = harness._archive_preview_cache_key(
                entry,
                [loose_root],
                include_loose_preview_assets=True,
            )
            loose_path.write_bytes(b"second payload")
            second_key = harness._archive_preview_cache_key(
                entry,
                [loose_root],
                include_loose_preview_assets=True,
            )

            self.assertEqual("", first_key)
            self.assertEqual("", second_key)
            self.assertEqual(archive_key, harness._archive_preview_cache_key(entry, [loose_root]))

    def test_fast_preview_reduces_preview_only_geometry(self) -> None:
        full_model = _preview_model(60_000)
        reduced = archive._reduce_archive_preview_model_geometry(full_model, max_faces=10_000)

        self.assertEqual(60_000, full_model.face_count)
        self.assertLessEqual(reduced.face_count, 10_000)
        self.assertGreater(reduced.face_count, 0)
        self.assertLess(len(reduced.meshes[0].indices), len(full_model.meshes[0].indices))

    def test_pamlod_fast_tier_requests_low_detail_lod(self) -> None:
        calls = []

        def fake_build(_entry, _data, *, lod_index=None, stop_event=None):
            calls.append(lod_index)
            return _preview_model(3, fmt="pamlod", lod_index=2 if lod_index == -1 else 0, lod_count=3)

        with patch("cdmw.core.archive_model_preview.build_pamlod_model_preview", side_effect=fake_build):
            fast_model, _notes = archive._build_pamlod_model_preview_with_fallback(
                _entry("character/model/body.pamlod", ".pamlod"),
                b"data",
                set(),
                quality_tier="fast",
            )
            full_model, _notes = archive._build_pamlod_model_preview_with_fallback(
                _entry("character/model/body.pamlod", ".pamlod"),
                b"data",
                set(),
                quality_tier="full",
            )

        self.assertEqual([-1, None], calls)
        self.assertEqual(2, fast_model.lod_index)
        self.assertEqual(0, full_model.lod_index)

    def test_pac_fast_tier_reduces_but_full_tier_preserves_geometry(self) -> None:
        source_model = _preview_model(60_000, fmt="pac")
        parsed_mesh = object()

        with patch(
            "cdmw.core.archive_model_preview.build_mesh_preview_from_bytes",
            return_value=(source_model, parsed_mesh),
        ):
            fast_model, fast_parsed, _notes = archive._build_pac_model_preview_with_fallback(
                _entry("character/model/body.pac", ".pac"),
                b"data",
                set(),
                quality_tier="fast",
            )
            full_model, full_parsed, _notes = archive._build_pac_model_preview_with_fallback(
                _entry("character/model/body.pac", ".pac"),
                b"data",
                set(),
                quality_tier="full",
            )

        self.assertLess(fast_model.face_count, full_model.face_count)
        self.assertEqual(60_000, full_model.face_count)
        self.assertIs(parsed_mesh, fast_parsed)
        self.assertIs(parsed_mesh, full_parsed)

    def test_pac_preview_rebuilds_from_resolved_character_appearance(self) -> None:
        source_model = _preview_model(1, fmt="pac")
        appearance_model = _preview_model(2, fmt="pac")
        parsed_mesh = SimpleNamespace(path="character/model/head.pac")
        appearance_mesh = SimpleNamespace(path="character/model/head.pac")

        with (
            patch(
                "cdmw.core.archive_model_preview.build_mesh_preview_from_bytes",
                return_value=(source_model, parsed_mesh),
            ),
            patch(
                "cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance",
                return_value=(appearance_mesh, ("Applied head.pabc skeleton variation.",)),
            ) as apply_appearance,
            patch(
                "cdmw.core.archive_mesh_import_scene_preview.parsed_mesh_to_preview_model",
                return_value=appearance_model,
            ) as rebuild_preview,
        ):
            preview, parsed, notes = archive._build_pac_model_preview_with_fallback(
                _entry("character/model/head.pac", ".pac"),
                b"data",
                set(),
                quality_tier="full",
                archive_entries_by_normalized_path={"character/model/head.pac": ()},
                archive_entries_by_basename={"head.pac": ()},
            )

        self.assertIs(appearance_model, preview)
        self.assertIs(appearance_mesh, parsed)
        self.assertIn("Applied head.pabc skeleton variation.", notes)
        apply_appearance.assert_called_once()
        rebuild_preview.assert_called_once_with(appearance_mesh)

    def test_pac_appearance_preparation_honors_worker_cancellation_before_io(self) -> None:
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaises(RunCancelled):
            apply_archive_mesh_appearance(
                _entry("character/model/head.pac", ".pac"),
                SimpleNamespace(format="pac"),
                b"PAR ",
                archive_entries_by_normalized_path={},
                archive_entries_by_basename={},
                stop_event=stop_event,
            )

    def test_pac_appearance_failure_keeps_original_preview_and_reports_reason(self) -> None:
        source_model = _preview_model(1, fmt="pac")
        parsed_mesh = SimpleNamespace(format="pac")
        with patch(
            "cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance_for_preview",
            return_value=(parsed_mesh, ("Character appearance deformation was not applied: broken PABC",)),
        ):
            preview, parsed, notes = apply_archive_mesh_appearance_to_preview_model(
                _entry("character/model/head.pac", ".pac"),
                b"PAR ",
                source_model,
                parsed_mesh,
                path_index={},
                basename_index={},
                stop_event=None,
            )

        self.assertIs(source_model, preview)
        self.assertIs(parsed_mesh, parsed)
        self.assertIn("broken PABC", notes[0])

    def test_pac_appearance_uses_indexed_pab_without_archive_wide_descriptor_scan(self) -> None:
        model_entry = _entry("character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pac", ".pac")
        pabc_entry = _entry("character/binary/skeletonvariation/head.pabc", ".pabc")
        pab_entry = _entry("character/model/1_pc/2_phw/phw_01.pab", ".pab")
        source_mesh = SimpleNamespace(format="pac")
        appearance_mesh = SimpleNamespace(format="pac")
        skeleton = SimpleNamespace(bones=(SimpleNamespace(),))
        variation = SimpleNamespace(matched_record_count=1, record_count=1)

        with (
            patch("cdmw.core.archive_mesh_appearance._related_appearance_entries", return_value=(pabc_entry,)),
            patch("cdmw.core.archive_mesh_appearance.read_archive_entry_data", return_value=(b"PAR data", False, "")),
            patch("cdmw.core.archive_mesh_appearance.parse_pab", return_value=skeleton),
            patch("cdmw.core.archive_mesh_appearance.parse_pabc_skeleton_variation", return_value=variation),
            patch("cdmw.core.archive_mesh_appearance.resolve_pac_bone_palette", return_value=(0,)),
            patch("cdmw.core.archive_mesh_appearance.apply_skeleton_variation_to_mesh", return_value=appearance_mesh),
            patch("cdmw.core.archive_mesh_appearance.resolve_skeleton_for_model") as broad_resolver,
        ):
            result, notes = apply_archive_mesh_appearance(
                model_entry,
                source_mesh,
                b"PAC data",
                archive_entries_by_normalized_path={},
                archive_entries_by_basename={"phw_01.pab": (pab_entry,)},
            )

        self.assertIs(appearance_mesh, result)
        self.assertIn("1/1 records", notes[0])
        broad_resolver.assert_not_called()

    def test_pac_fbx_appearance_recovers_pamt_targets_without_a_pabc(self) -> None:
        model_entry = _entry("character/model/2_mon/wolf/wolf.pac", ".pac")
        pamt_entry = _entry("character/model/2_mon/wolf/wolf.pamt", ".pamt")
        pab_entry = _entry("character/model/2_mon/wolf/wolf.pab", ".pab")
        source_mesh = SimpleNamespace(format="pac")
        appearance_mesh = SimpleNamespace(format="pac")
        skeleton = SimpleNamespace(bones=(SimpleNamespace(),))
        morphs = SimpleNamespace(target_count=3)

        with (
            patch("cdmw.core.archive_mesh_appearance._related_appearance_entries", return_value=(pamt_entry,)),
            patch("cdmw.core.archive_mesh_appearance.read_archive_entry_data", return_value=(b"PAR data", False, "")),
            patch("cdmw.core.archive_mesh_appearance.parse_pab", return_value=skeleton),
            patch("cdmw.core.archive_mesh_appearance.parse_pamt_morph_target_set", return_value=morphs),
            patch("cdmw.core.archive_mesh_appearance.resolve_pac_bone_palette", return_value=(0,)),
            patch("cdmw.core.archive_mesh_appearance.apply_skeleton_variation_to_mesh", return_value=appearance_mesh) as apply_appearance,
        ):
            result, notes = apply_archive_mesh_appearance(
                model_entry,
                source_mesh,
                b"PAC data",
                archive_entries_by_normalized_path={},
                archive_entries_by_basename={"wolf.pab": (pab_entry,)},
                include_morph_targets=True,
            )

        self.assertIs(appearance_mesh, result)
        self.assertIn("2 appearance shape target", notes[0])
        self.assertIsNone(apply_appearance.call_args.args[3])
        self.assertIs(morphs, apply_appearance.call_args.kwargs["morph_target_set"])

    def test_pac_appearance_prefers_the_descriptor_named_pamt_over_nearby_candidates(self) -> None:
        stem = "cd_phw_00_head_00_0111"
        model_entry = _entry(f"character/model/1_pc/2_phw/head/head/{stem}.pac", ".pac")
        descriptor_entry = _entry(f"character/prefab/1_pc/2_phw/head/head/{stem}.prefabdata_xml", ".prefabdata_xml")
        pab_entry = _entry("character/model/1_pc/2_phw/phw_01.pab", ".pab")
        pabc_entry = _entry(f"character/binary/skeletonvariation/1_pc/2_phw/head/head/{stem}.pabc", ".pabc")
        wrong_pamt = _entry("character/model/1_pc/2_phw/phw_01.pamt", ".pamt")
        exact_pamt = _entry("character/model/1_pc/2_phw/phw_damian.pamt", ".pamt")
        entries = (model_entry, descriptor_entry, pab_entry, pabc_entry, wrong_pamt, exact_pamt)
        path_index = {entry.path.casefold(): (entry,) for entry in entries}
        basename_index = {entry.basename.casefold(): (entry,) for entry in entries}
        descriptor_xml = (
            "<HeadPrefabData>"
            '<SkeletonName FileName="1_pc/2_phw/phw_01.pab"/>'
            f'<SkeletonVariationName FileName="1_pc/2_phw/head/head/{stem}.pabc"/>'
            '<MorphTargetSet FileName="1_pc/2_phw/phw_damian.pamt"/>'
            "</HeadPrefabData>"
        ).encode()
        payloads = {
            descriptor_entry.path: descriptor_xml,
            pab_entry.path: b"PAB exact",
            pabc_entry.path: b"PABC exact",
            wrong_pamt.path: b"PAMT wrong",
            exact_pamt.path: b"PAMT exact",
        }
        source_mesh = SimpleNamespace(format="pac")
        appearance_mesh = SimpleNamespace(format="pac")
        skeleton = SimpleNamespace(bones=(SimpleNamespace(),))
        variation = SimpleNamespace(path=pabc_entry.path, matched_record_count=1, record_count=1)
        morphs = SimpleNamespace(path=exact_pamt.path, target_count=2)

        with (
            patch(
                "cdmw.core.archive_mesh_appearance.read_archive_entry_data",
                side_effect=lambda entry, **_kwargs: (payloads[entry.path], False, ""),
            ),
            patch("cdmw.core.archive_mesh_appearance.parse_pab", return_value=skeleton),
            patch("cdmw.core.archive_mesh_appearance.parse_pabc_skeleton_variation", return_value=variation),
            patch("cdmw.core.archive_mesh_appearance.parse_pamt_morph_target_set", return_value=morphs) as parse_morphs,
            patch("cdmw.core.archive_mesh_appearance.resolve_pac_bone_palette", return_value=(0,)),
            patch("cdmw.core.archive_mesh_appearance.apply_skeleton_variation_to_mesh", return_value=appearance_mesh),
        ):
            result, _notes = apply_archive_mesh_appearance(
                model_entry,
                source_mesh,
                b"PAC data",
                archive_entries_by_normalized_path=path_index,
                archive_entries_by_basename=basename_index,
                include_morph_targets=True,
            )

        self.assertIs(appearance_mesh, result)
        self.assertEqual(b"PAMT exact", parse_morphs.call_args.args[0])

    def test_loose_character_package_resolves_exact_descriptor_companions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pac"
            descriptor = root / "character/prefab/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.prefabdata_xml"
            skeleton = root / "character/model/1_pc/2_phw/phw_01.pab"
            variation = root / "character/binary/skeletonvariation/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pabc"
            morphs = root / "character/model/1_pc/2_phw/phw_damian.pamt"
            unrelated = root / "character/model/1_pc/1_phm/phm_01.pamt"
            for path in (model, skeleton, variation, morphs, unrelated):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"PAR ")
            descriptor.parent.mkdir(parents=True, exist_ok=True)
            descriptor.write_text(
                "<HeadPrefabData>"
                '<SkeletonName FileName="1_pc/2_phw/phw_01.pab"/>'
                '<SkeletonVariationName FileName="1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pabc"/>'
                '<MorphTargetSet FileName="1_pc/2_phw/phw_damian.pamt"/>'
                "</HeadPrefabData>",
                encoding="utf-8",
            )
            manifest_path = write_character_appearance_bundle_manifest(
                root,
                primary_model_path="character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pac",
                selected_appearance_path="character/appearance/damian.app_xml",
                entries=(
                    _entry("character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pac", ".pac"),
                    _entry("character/prefab/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.prefabdata_xml", ".prefabdata_xml"),
                    _entry("character/model/1_pc/2_phw/phw_01.pab", ".pab"),
                    _entry("character/binary/skeletonvariation/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pabc", ".pabc"),
                    _entry("character/model/1_pc/2_phw/phw_damian.pamt", ".pamt"),
                ),
            )

            sources = resolve_loose_character_appearance_sources(model)

            self.assertIsNotNone(sources)
            assert sources is not None
            self.assertEqual(root, sources.package_root)
            self.assertEqual(descriptor, sources.descriptor_path)
            self.assertEqual(skeleton, sources.skeleton_path)
            self.assertEqual(variation, sources.skeleton_variation_path)
            self.assertEqual(morphs, sources.morph_target_path)
            self.assertEqual(manifest_path, sources.manifest_path)
            self.assertEqual(5, len(sources.expected_hashes))

    def test_loose_character_package_combines_body_descriptor_with_sibling_head_morphs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            family = Path(
                "character/model/2_mon/cd_m0002_00_fourfeet/"
                "cd_m0002_00_buffalo/cd_m0002_00_buffalo"
            )
            prefab_family = Path(str(family).replace("character\\model", "character\\prefab"))
            model = root / family / "cd_m0002_00_buffalo_00_0001.pac"
            body_descriptor = root / prefab_family / "cd_m0002_00_buffalo_00_0001.prefabdata_xml"
            head_descriptor = root / prefab_family / "cd_m0002_00_buffalo_head_0001.prefabdata_xml"
            skeleton = root / family / "cd_m0002_00_buffalo.pab"
            morphs = root / family / "cd_m0002_00_buffalo.pamt"
            for path in (model, skeleton, morphs):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"PAR ")
            body_descriptor.parent.mkdir(parents=True, exist_ok=True)
            body_descriptor.write_text(
                '<NudePrefabData><SkeletonName FileName="2_mon/cd_m0002_00_fourfeet/'
                'cd_m0002_00_buffalo/cd_m0002_00_buffalo/cd_m0002_00_buffalo.pab"/>'
                '</NudePrefabData>',
                encoding="utf-8",
            )
            head_descriptor.write_text(
                '<HeadPrefabData><MorphTargetSet FileName="2_mon/cd_m0002_00_fourfeet/'
                'cd_m0002_00_buffalo/cd_m0002_00_buffalo/cd_m0002_00_buffalo.pamt"/>'
                '</HeadPrefabData>',
                encoding="utf-8",
            )

            sources = resolve_loose_character_appearance_sources(model)

            self.assertIsNotNone(sources)
            assert sources is not None
            self.assertEqual(body_descriptor, sources.descriptor_path)
            self.assertEqual(head_descriptor, sources.morph_descriptor_path)
            self.assertEqual(skeleton, sources.skeleton_path)
            self.assertEqual(morphs, sources.morph_target_path)

    def test_loose_character_package_resolves_cross_folder_same_family_morphs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            body_family = Path(
                "character/model/2_mon/cd_m0002_00_fourfeet/"
                "cd_m0002_00_dog/cd_m0002_00_cat"
            )
            body_prefab = Path(str(body_family).replace("character\\model", "character\\prefab"))
            model = root / body_family / "cd_m0002_00_hatch_00_0001.pac"
            body_descriptor = root / body_prefab / "cd_m0002_00_hatch_00_0001.prefabdata_xml"
            wrong_head = root / body_prefab / "cd_m0002_00_catbaby_head_0001.prefabdata_xml"
            hatch_head = root / (
                "character/prefab/2_mon/cd_m0002_00_fourfeet/"
                "cd_m0002_00_hatch/cd_m0002_00_hatch_head_00_0001.prefabdata_xml"
            )
            skeleton = root / "character/model/2_mon/cd_m0002_00_fourfeet/cd_m0011_00_dog.pab"
            wrong_morphs = root / body_family / "cd_m0002_00_cat.pamt"
            hatch_morphs = root / (
                "character/model/2_mon/cd_m0002_00_fourfeet/"
                "cd_m0002_00_hatch/cd_m0002_00_hatch.pamt"
            )
            for path in (model, skeleton, wrong_morphs, hatch_morphs):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"PAR ")
            body_descriptor.parent.mkdir(parents=True, exist_ok=True)
            body_descriptor.write_text(
                '<NudePrefabData><SkeletonName FileName="2_mon/cd_m0002_00_fourfeet/'
                'cd_m0011_00_dog.pab"/></NudePrefabData>',
                encoding="utf-8",
            )
            wrong_head.write_text(
                '<HeadPrefabData><MorphTargetSet FileName="2_mon/cd_m0002_00_fourfeet/'
                'cd_m0002_00_dog/cd_m0002_00_cat/cd_m0002_00_cat.pamt"/></HeadPrefabData>',
                encoding="utf-8",
            )
            hatch_head.parent.mkdir(parents=True, exist_ok=True)
            hatch_head.write_text(
                '<HeadPrefabData><MorphTargetSet FileName="2_mon/cd_m0002_00_fourfeet/'
                'cd_m0002_00_hatch/cd_m0002_00_hatch.pamt"/></HeadPrefabData>',
                encoding="utf-8",
            )

            sources = resolve_loose_character_appearance_sources(model)

            self.assertIsNotNone(sources)
            assert sources is not None
            self.assertEqual(body_descriptor, sources.descriptor_path)
            self.assertEqual(hatch_head, sources.morph_descriptor_path)
            self.assertEqual(hatch_morphs, sources.morph_target_path)

    def test_loose_character_package_uses_selected_app_sibling_for_shared_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "character/model/1_pc/5_pom/head/head/cd_pom_00_head_0001_oongka.pac"
            head_descriptor = root / (
                "character/prefab/1_pc/05_pom/head/head/"
                "cd_pom_00_head_00_0001_oongka.prefabdata_xml"
            )
            nude_descriptor = root / (
                "character/prefab/1_pc/05_pom/nude/"
                "cd_pom_00_nude_00_0001_oongka.prefabdata_xml"
            )
            app = root / "character/appearance/1_pc/1_phm/cd_phm_oongka/cd_phm_oongka_00000.app_xml"
            skeleton = root / "character/model/1_pc/1_phm/phm_01.pab"
            variation = root / (
                "character/binary/skeletonvariation/1_pc/5_pom/head/head/"
                "cd_pom_oongka_head_0001.pabc"
            )
            morphs = root / "character/model/1_pc/5_pom/pom_oongka.pamt"
            for path in (model, skeleton, variation, morphs):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"PAR ")
            head_descriptor.parent.mkdir(parents=True, exist_ok=True)
            head_descriptor.write_text(
                '<HeadPrefabData><SkeletonVariationName FileName="1_pc/5_pom/head/head/'
                'cd_pom_oongka_head_0001.pabc"/><MorphTargetSet FileName="1_pc/5_pom/'
                'pom_oongka.pamt"/></HeadPrefabData>',
                encoding="utf-8",
            )
            nude_descriptor.parent.mkdir(parents=True, exist_ok=True)
            nude_descriptor.write_text(
                '<NudePrefabData><SkeletonName FileName="1_pc/1_phm/phm_01.pab"/></NudePrefabData>',
                encoding="utf-8",
            )
            app.parent.mkdir(parents=True, exist_ok=True)
            app.write_text(
                '<Appearance><Nude><Prefab Name="cd_pom_00_nude_00_0001_oongka"/></Nude>'
                '<Head><Prefab Name="cd_pom_00_head_00_0001_oongka"/></Head></Appearance>',
                encoding="utf-8",
            )

            sources = resolve_loose_character_appearance_sources(model)

            self.assertIsNotNone(sources)
            assert sources is not None
            self.assertEqual(head_descriptor, sources.descriptor_path)
            self.assertEqual(nude_descriptor, sources.skeleton_descriptor_path)
            self.assertEqual(head_descriptor, sources.morph_descriptor_path)
            self.assertEqual(skeleton, sources.skeleton_path)
            self.assertEqual(variation, sources.skeleton_variation_path)
            self.assertEqual(morphs, sources.morph_target_path)

    def test_loose_character_package_finds_a_differently_named_descriptor_by_model_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "character/model/2_mon/wolf/body_visual.pac"
            descriptor = root / "character/prefab/2_mon/wolf/creature_profile.prefabdata_xml"
            skeleton = root / "character/model/2_mon/wolf/wolf.pab"
            variation = root / "character/binary/skeletonvariation/2_mon/wolf/wolf_pose.pabc"
            for path in (model, skeleton, variation):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"PAR ")
            descriptor.parent.mkdir(parents=True, exist_ok=True)
            descriptor.write_text(
                "<CreaturePrefabData>"
                '<SkinnedMesh FileName="character/model/2_mon/wolf/body_visual.pac"/>'
                '<SkeletonName FileName="2_mon/wolf/wolf.pab"/>'
                '<SkeletonVariationName FileName="2_mon/wolf/wolf_pose.pabc"/>'
                "</CreaturePrefabData>",
                encoding="utf-8",
            )

            sources = resolve_loose_character_appearance_sources(model)

            self.assertIsNotNone(sources)
            assert sources is not None
            self.assertEqual(descriptor, sources.descriptor_path)
            self.assertEqual(skeleton, sources.skeleton_path)
            self.assertEqual(variation, sources.skeleton_variation_path)

    def test_loose_character_manifest_rejects_a_changed_companion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "character/model/head.pac"
            descriptor = root / "character/prefab/head.prefabdata_xml"
            skeleton_path = root / "character/model/head.pab"
            variation = root / "character/binary/skeletonvariation/head.pabc"
            for path, payload in (
                (model, b"PAC data"),
                (skeleton_path, b"PAB data"),
                (variation, b"PABC data"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            descriptor.parent.mkdir(parents=True, exist_ok=True)
            descriptor.write_text(
                "<HeadPrefabData>"
                '<SkeletonName FileName="head.pab"/>'
                '<SkeletonVariationName FileName="head.pabc"/>'
                "</HeadPrefabData>",
                encoding="utf-8",
            )
            write_character_appearance_bundle_manifest(
                root,
                primary_model_path="character/model/head.pac",
                selected_appearance_path="",
                entries=(
                    _entry("character/model/head.pac", ".pac"),
                    _entry("character/prefab/head.prefabdata_xml", ".prefabdata_xml"),
                    _entry("character/model/head.pab", ".pab"),
                    _entry("character/binary/skeletonvariation/head.pabc", ".pabc"),
                ),
            )
            variation.write_bytes(b"changed after export")
            parsed_mesh = SimpleNamespace(format="pac")
            parsed_skeleton = SimpleNamespace(bones=(SimpleNamespace(),))

            with (
                patch("cdmw.core.archive_mesh_appearance.parse_pab", return_value=parsed_skeleton),
                patch("cdmw.core.archive_mesh_appearance.resolve_pac_bone_palette", return_value=(0,)),
            ):
                with self.assertRaisesRegex(ValueError, "bundle hash mismatch"):
                    apply_loose_character_appearance(model, parsed_mesh, b"PAC data")

    def test_loose_character_appearance_uses_a_presentation_clone_only(self) -> None:
        source_mesh = SimpleNamespace(format="pac")
        presentation_mesh = SimpleNamespace(format="pac")
        sources = SimpleNamespace(
            package_root=Path("."),
            model_virtual_path="face.pac",
            skeleton_path=Path("rig.pab"),
            skeleton_variation_path=Path("shape.pabc"),
            morph_target_path=Path("expressions.pamt"),
            expected_hashes=(),
        )
        skeleton = SimpleNamespace(bones=(SimpleNamespace(),))
        variation = SimpleNamespace(path="shape.pabc", matched_record_count=1, record_count=1)
        morphs = SimpleNamespace(path="expressions.pamt", target_count=4)
        with (
            patch("cdmw.core.archive_mesh_appearance.resolve_loose_character_appearance_sources", return_value=sources),
            patch("cdmw.core.archive_mesh_appearance._read_loose_appearance_payload", return_value=b"PAR "),
            patch("cdmw.core.archive_mesh_appearance.parse_pab", return_value=skeleton),
            patch("cdmw.core.archive_mesh_appearance.parse_pabc_skeleton_variation", return_value=variation),
            patch("cdmw.core.archive_mesh_appearance.parse_pamt_morph_target_set", return_value=morphs),
            patch("cdmw.core.archive_mesh_appearance.resolve_pac_bone_palette", return_value=(0,)),
            patch("cdmw.core.archive_mesh_appearance.apply_skeleton_variation_to_mesh", return_value=presentation_mesh),
        ):
            result, notes = apply_loose_character_appearance(
                Path("face.pac"),
                source_mesh,
                b"PAC data",
                include_morph_targets=True,
            )

        self.assertIs(presentation_mesh, result)
        self.assertIsNot(source_mesh, result)
        self.assertIn("shape.pabc", notes[0])
        self.assertIn("3 appearance shape target", notes[1])

    def test_archive_preview_cache_key_has_quality_tier_source_guard(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        )

        self.assertIn('quality_tier: str = "full"', source)
        self.assertIn('f"quality:{', source)
        self.assertIn('quality_tier="fast"', source)
        self.assertIn('quality_tier="full"', source)

    def test_fast_result_does_not_finalize_request_source_guard(self) -> None:
        source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        handler = source[source.index("def _handle_archive_preview_ready"):source.index("def _handle_archive_preview_error")]

        self.assertIn("is_fast_result = quality_tier == \"fast\"", handler)
        self.assertIn("is_interim_result = is_fast_result or quality_tier == \"quick\" or source == \"quick_preview\"", handler)
        self.assertIn("if not is_interim_result:", handler)
        self.assertIn("Fast preview loaded; refining full-quality preview", handler)

    def test_archive_preview_worker_owns_cache_and_quick_payloads_source_guard(self) -> None:
        source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        worker = Path("cdmw/workers/archive_preview_workers.py").read_text(encoding="utf-8")

        self.assertIn("class _ArchivePreviewWorkerPayload", worker)
        self.assertIn("preview_cache_snapshot", worker)
        self.assertIn("def _cached_preview_payload", worker)
        self.assertIn("def _durable_native_preview_cache_payload", worker)
        self.assertIn("def _quick_archive_model_preview_payload", worker)
        self.assertIn('source="preview_cache"', worker)
        self.assertIn('source="preview_cache_fast"', worker)
        self.assertIn('source="dotnet_package_cache"', worker)
        self.assertIn('source="quick_preview"', worker)
        self.assertIn("emit_private_payloads=True", source)

    def test_preview_loading_watchdog_preserves_fast_result_source_guard(self) -> None:
        source = Path("cdmw/ui/archive_browser/preview_loading.py").read_text(encoding="utf-8")
        watchdog = source[
            source.index("def _handle_archive_preview_loading_stall")
            : source.index("def _stop_archive_preview_loading_indicator")
        ]

        self.assertIn("archive_preview_loading_request_id", source)
        self.assertIn("if int(getattr(self, \"archive_preview_loading_request_id\"", source)
        self.assertIn("preview_phase = \"full_after_fast\"", watchdog)
        self.assertIn("self.archive_preview_worker.stop()", watchdog)
        self.assertIn("self.archive_preview_thread.requestInterruption()", watchdog)
        self.assertIn("self.archive_preview_thread.quit()", watchdog)
        self.assertIn("shutdown_native_preview_core_service()", watchdog)
        self.assertIn('"archive_preview_stalled"', watchdog)
        self.assertIn("preview_stalled=True", watchdog)
        self.assertIn("request_id=request_id", watchdog)
        self.assertIn("self.archive_preview_request_id += 1", watchdog)
        self.assertIn("Fast preview remains visible; full preview timed out and was stopped.", watchdog)


if __name__ == "__main__":
    unittest.main()
