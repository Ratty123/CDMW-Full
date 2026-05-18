import unittest
from unittest.mock import patch

from cdmw.core import archive
from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewMesh


def _entry(path: str, extension: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path="package.pamt",
        paz_file="package_0.paz",
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

        with patch.object(archive, "build_pamlod_model_preview", side_effect=fake_build):
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

        with patch.object(archive, "build_mesh_preview_from_bytes", return_value=(source_model, parsed_mesh)):
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

    def test_archive_preview_cache_key_has_quality_tier_source_guard(self) -> None:
        source = __import__("pathlib").Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn('quality_tier: str = "full"', source)
        self.assertIn('f"quality:{', source)
        self.assertIn('quality_tier="fast"', source)
        self.assertIn('quality_tier="full"', source)

    def test_fast_result_does_not_finalize_request_source_guard(self) -> None:
        source = __import__("pathlib").Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        handler = source[source.index("def _handle_archive_preview_ready"):source.index("def _handle_archive_preview_error")]

        self.assertIn("is_fast_result = quality_tier == \"fast\"", handler)
        self.assertIn("if not is_fast_result:", handler)
        self.assertIn("Fast preview loaded; refining full-quality preview", handler)


if __name__ == "__main__":
    unittest.main()
