import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from cdmw.core.model_catalogue import (
    DEFAULT_MODEL_MIRROR_URL,
    MirrorDownloadCandidate,
    build_mirror_catalogue_index,
    download_mirror_model,
    download_mirror_model_candidate,
    initialize_catalogue_db,
    mirror_download_candidates,
    normalize_mirror_base_url,
    normalize_mirror_model_record,
    parse_catalogue_links,
    resolve_importable_model_path,
    safe_extract_zip,
    scan_local_model_files,
    search_catalogue_records,
    upsert_catalogue_records,
    zip_contains_importable_model,
)


class ModelCatalogueTests(unittest.TestCase):
    def test_parse_catalogue_links_keeps_json_pages(self) -> None:
        html = """
        <a href="../">../</a>
        <a href="bak/">bak/</a>
        <a href="None.json">None.json</a>
        <a href="cD0y%3D.json">cD0y=.json</a>
        """

        self.assertEqual(parse_catalogue_links(html), ("cD0y%3D.json", "None.json"))

    def test_normalize_mirror_base_url_accepts_catalogue_url(self) -> None:
        self.assertEqual(
            normalize_mirror_base_url("https://mirror.traines.eu/sketchfab-backup/+catalogue/"),
            DEFAULT_MODEL_MIRROR_URL,
        )

    def test_normalize_mirror_base_url_requires_user_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "mirror URL"):
            normalize_mirror_base_url("")

    def test_normalize_record_builds_mirror_download_urls(self) -> None:
        record = normalize_mirror_model_record(
            {
                "uid": "0c03ea90f649461e9799063f9944f62d",
                "name": "Elemental sword",
                "viewerUrl": "https://sketchfab.com/3d-models/example",
                "archives": {"gltf": {"size": 10}, "source": {"size": 20}},
                "license": {"label": "CC Attribution"},
                "user": {"displayName": "Artist"},
                "tags": [{"name": "sword"}],
            },
            DEFAULT_MODEL_MIRROR_URL,
        )

        self.assertEqual(record["creator_name"], "Artist")
        self.assertEqual(record["license_label"], "CC Attribution")
        self.assertEqual(record["gltf_url"], "https://mirror.traines.eu/sketchfab-backup/0c/0c03ea90f649461e9799063f9944f62d.zip")
        self.assertEqual(record["source_url"], "https://mirror.traines.eu/sketchfab-backup/0c/0c03ea90f649461e9799063f9944f62d.source.zip")
        formats = [candidate.format for candidate in mirror_download_candidates(record, DEFAULT_MODEL_MIRROR_URL)]
        self.assertEqual(formats[:2], ["gltf", "source"])

    def test_scan_local_model_files_marks_importable_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "model.glb").write_bytes(b"glb")
            (root / "model.dae").write_text("<COLLADA />", encoding="utf-8")
            (root / "source.fbx").write_bytes(b"fbx")
            with zipfile.ZipFile(root / "packed.zip", "w") as zip_file:
                zip_file.writestr("scene/model.gltf", "{}")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            rows = scan_local_model_files([root])

        by_name = {row.path.name: row for row in rows}
        self.assertIn("model.glb", by_name)
        self.assertIn("model.dae", by_name)
        self.assertIn("source.fbx", by_name)
        self.assertIn("packed.zip", by_name)
        self.assertEqual(by_name["model.glb"].name, "model")
        self.assertTrue(by_name["model.glb"].import_supported)
        self.assertTrue(by_name["model.dae"].import_supported)
        self.assertTrue(by_name["packed.zip"].import_supported)
        self.assertFalse(by_name["source.fbx"].import_supported)

    def test_scan_local_model_files_uses_metadata_name_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_dir = root / "downloads" / "Windum--Low-c8a2cbf0faf84720938402558e574c40"
            scene_dir = asset_dir / "gltf"
            scene_dir.mkdir(parents=True)
            (asset_dir / "model_metadata.json").write_text(json.dumps({"name": "Windum - Low"}), encoding="utf-8")
            (scene_dir / "scene.gltf").write_text("{}", encoding="utf-8")
            (asset_dir / "c8a2cbf0faf84720938402558e574c40.zip").write_bytes(b"zip")

            rows = scan_local_model_files([root])

        by_file = {row.path.name: row for row in rows}
        self.assertEqual(by_file["scene.gltf"].name, "Windum - Low")
        self.assertEqual(by_file["c8a2cbf0faf84720938402558e574c40.zip"].name, "Windum - Low")

    def test_scan_local_model_files_uses_parent_name_for_generic_scene_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scene_dir = root / "Swordfish-2-15df20021f74133b75868ee00ea7207" / "gltf"
            scene_dir.mkdir(parents=True)
            (scene_dir / "scene.gltf").write_text("{}", encoding="utf-8")
            (scene_dir / "blade.gltf").write_text("{}", encoding="utf-8")

            rows = scan_local_model_files([root])

        by_file = {row.path.name: row for row in rows}
        self.assertEqual(by_file["scene.gltf"].name, "Swordfish 2")
        self.assertEqual(by_file["blade.gltf"].name, "blade")

    def test_scan_local_model_files_ignores_internal_zip_extract_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "escanor axe rhitta.zip").write_bytes(b"zip")
            extracted_dir = root / ".cdmw_extracted" / "escanor_axe_rhitta"
            extracted_dir.mkdir(parents=True)
            (extracted_dir / "scene.gltf").write_text("{}", encoding="utf-8")
            nested_dir = root / ".cdmw_nested_zip" / "inner"
            nested_dir.mkdir(parents=True)
            (nested_dir / "inner_scene.gltf").write_text("{}", encoding="utf-8")

            rows = scan_local_model_files([root])

        self.assertEqual([row.path.name for row in rows], ["escanor axe rhitta.zip"])
        self.assertEqual([row.name for row in rows], ["escanor axe rhitta"])

    def test_resolve_importable_model_path_extracts_zip_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "packed.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("textures/diffuse.png", b"png")
                zip_file.writestr("scene/model.gltf", "{}")

            self.assertTrue(zip_contains_importable_model(archive))
            resolved = resolve_importable_model_path(archive, extract_root=root / "extracted")

            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.name, "model.gltf")
            self.assertTrue(resolved.is_file())

    def test_download_mirror_model_can_require_importable_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            record = normalize_mirror_model_record(
                {
                    "uid": "cccc",
                    "name": "Source Only",
                    "archives": {"source": {"size": 20}},
                },
                DEFAULT_MODEL_MIRROR_URL,
            )

            def write_unsupported_source_zip(_url: str, output_path: Path, *, timeout: float) -> None:
                with zipfile.ZipFile(output_path, "w") as zip_file:
                    zip_file.writestr("source.fbx", b"fbx")

            with self.assertRaisesRegex(ValueError, "importable"):
                with mock.patch("cdmw.core.model_catalogue._download_url_to_file", side_effect=write_unsupported_source_zip):
                    download_mirror_model(
                        record,
                        mirror_url=DEFAULT_MODEL_MIRROR_URL,
                        output_root=Path(temp_dir),
                        preferred_format="source",
                        require_importable=True,
                    )

    def test_download_mirror_model_candidate_downloads_exact_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            record = normalize_mirror_model_record(
                {
                    "uid": "dddd",
                    "name": "Exact Archive",
                    "archives": {"source": {"size": 20}},
                },
                DEFAULT_MODEL_MIRROR_URL,
            )
            candidate = MirrorDownloadCandidate(
                "source",
                "Original source ZIP",
                "https://example.invalid/dddd.source.zip",
                "dddd.source.zip",
                False,
            )

            def write_archive(_url: str, output_path: Path, *, timeout: float) -> None:
                output_path.write_bytes(b"archive")

            with mock.patch("cdmw.core.model_catalogue._download_url_to_file", side_effect=write_archive) as download:
                result = download_mirror_model_candidate(record, candidate, output_root=Path(temp_dir))

            download.assert_called_once()
            self.assertEqual(result.candidate, candidate)
            self.assertEqual(result.archive_path.name, "dddd.source.zip")
            self.assertTrue(result.archive_path.is_file())
            self.assertIsNone(result.import_path)

    def test_source_zip_download_can_resolve_importable_dae(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            record = normalize_mirror_model_record(
                {
                    "uid": "eeee",
                    "name": "DAE Source",
                    "archives": {"source": {"size": 20}},
                },
                DEFAULT_MODEL_MIRROR_URL,
            )
            candidate = mirror_download_candidates(record, DEFAULT_MODEL_MIRROR_URL, preferred_format="source")[0]

            def write_archive(_url: str, output_path: Path, *, timeout: float) -> None:
                with zipfile.ZipFile(output_path, "w") as zip_file:
                    zip_file.writestr("scene/model.dae", "<COLLADA />")

            with mock.patch("cdmw.core.model_catalogue._download_url_to_file", side_effect=write_archive):
                result = download_mirror_model_candidate(record, candidate, output_root=Path(temp_dir))

            self.assertEqual(candidate.format, "source")
            self.assertTrue(candidate.import_supported)
            self.assertIsNotNone(result.import_path)
            assert result.import_path is not None
            self.assertEqual(result.import_path.suffix.lower(), ".dae")

    def test_search_catalogue_records_filters_license_creator_and_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalogue.sqlite"
            conn = initialize_catalogue_db(db_path)
            try:
                upsert_catalogue_records(
                    conn,
                    [
                        normalize_mirror_model_record(
                            {
                                "uid": "aaaa",
                                "name": "Iron Sword",
                                "archives": {"gltf": {"size": 10}},
                                "license": {"label": "CC0"},
                                "user": {"displayName": "Mira"},
                                "tags": [{"name": "weapon"}],
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                        normalize_mirror_model_record(
                            {
                                "uid": "bbbb",
                                "name": "Wood Shield",
                                "archives": {"glb": {"size": 20}},
                                "license": {"label": "CC Attribution-NonCommercial"},
                                "user": {"displayName": "Noah"},
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                    ],
                    shard_name="test.json",
                    shard_url="https://example.test/test.json",
                )
            finally:
                conn.close()

            rows = search_catalogue_records(
                db_path,
                "sword",
                license_contains="CC0",
                creator_contains="Mira",
                required_format="gltf",
            )

        self.assertEqual([row["uid"] for row in rows], ["aaaa"])

    def test_search_catalogue_records_excludes_multiple_creators(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalogue.sqlite"
            conn = initialize_catalogue_db(db_path)
            try:
                upsert_catalogue_records(
                    conn,
                    [
                        normalize_mirror_model_record(
                            {
                                "uid": "aaaa",
                                "name": "Iron Sword",
                                "archives": {"gltf": {"size": 10}},
                                "user": {"displayName": "Mira", "username": "mira_art"},
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                        normalize_mirror_model_record(
                            {
                                "uid": "bbbb",
                                "name": "Steel Sword",
                                "archives": {"gltf": {"size": 10}},
                                "user": {"displayName": "Noah", "username": "noah_models"},
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                        normalize_mirror_model_record(
                            {
                                "uid": "cccc",
                                "name": "Bronze Sword",
                                "archives": {"gltf": {"size": 10}},
                                "user": {"displayName": "Rin", "username": "rin_props"},
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                    ],
                    shard_name="test.json",
                    shard_url="https://example.test/test.json",
                )
            finally:
                conn.close()

            rows = search_catalogue_records(db_path, "sword", creator_excludes="Mira; noah_models", limit=10)

        self.assertEqual([row["uid"] for row in rows], ["cccc"])

    def test_search_catalogue_records_falls_back_to_partial_token_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalogue.sqlite"
            conn = initialize_catalogue_db(db_path)
            try:
                upsert_catalogue_records(
                    conn,
                    [
                        normalize_mirror_model_record(
                            {
                                "uid": "aaaa",
                                "name": "Epitaph Of Calamity",
                                "archives": {"gltf": {"size": 10}},
                                "tags": [
                                    {"name": "monster"},
                                    {"name": "hunter"},
                                    {"name": "sword"},
                                    {"name": "blade"},
                                ],
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                        normalize_mirror_model_record(
                            {
                                "uid": "bbbb",
                                "name": "Wood Shield",
                                "archives": {"gltf": {"size": 10}},
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                    ],
                    shard_name="test.json",
                    shard_url="https://example.test/test.json",
                )
            finally:
                conn.close()

            rows = search_catalogue_records(db_path, "Monster Hunter Great Sword", limit=5000)

        self.assertEqual(rows[0]["uid"], "aaaa")

    def test_search_catalogue_records_ranks_name_matches_before_tag_only_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "catalogue.sqlite"
            conn = initialize_catalogue_db(db_path)
            try:
                upsert_catalogue_records(
                    conn,
                    [
                        normalize_mirror_model_record(
                            {
                                "uid": "aaaa",
                                "name": "2827850",
                                "archives": {"gltf": {"size": 10}},
                                "tags": [{"name": "axe"}],
                                "viewCount": 100000,
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                        normalize_mirror_model_record(
                            {
                                "uid": "bbbb",
                                "name": "Axe",
                                "archives": {"gltf": {"size": 10}},
                                "viewCount": 10,
                            },
                            DEFAULT_MODEL_MIRROR_URL,
                        ),
                    ],
                    shard_name="test.json",
                    shard_url="https://example.test/test.json",
                )
            finally:
                conn.close()

            rows = search_catalogue_records(db_path, "axe", limit=10)

        self.assertEqual([row["uid"] for row in rows[:2]], ["bbbb", "aaaa"])

    def test_build_mirror_catalogue_index_can_scope_to_query(self) -> None:
        listing_html = '<a href="one.json">one.json</a>'
        shard_payload = {
            "results": [
                {
                    "uid": "aaaa",
                    "name": "Iron Sword",
                    "archives": {"gltf": {"size": 10}},
                    "tags": [{"name": "weapon"}],
                },
                {
                    "uid": "bbbb",
                    "name": "Wood Shield",
                    "archives": {"gltf": {"size": 10}},
                    "tags": [{"name": "armor"}],
                },
            ]
        }

        def fetch_text(url: str, *, timeout: float) -> str:
            if url.endswith("+README/"):
                return "readme"
            if url.endswith("+catalogue/"):
                return listing_html
            if url.endswith("one.json"):
                return json.dumps(shard_payload)
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch("cdmw.core.model_catalogue._fetch_text", side_effect=fetch_text):
            manifest = build_mirror_catalogue_index(
                mirror_url=DEFAULT_MODEL_MIRROR_URL,
                output_dir=Path(temp_dir),
                index_query="sword",
                clear_existing=True,
            )
            rows = search_catalogue_records(Path(temp_dir) / "mirror_catalogue.sqlite", "sword", limit=10)
            all_rows = search_catalogue_records(Path(temp_dir) / "mirror_catalogue.sqlite", "", limit=10)

        self.assertTrue(manifest["index_scoped"])
        self.assertEqual(manifest["indexed_model_records_this_run"], 1)
        self.assertEqual(manifest["seen_model_records_this_run"], 2)
        self.assertEqual([row["uid"] for row in rows], ["aaaa"])
        self.assertEqual([row["uid"] for row in all_rows], ["aaaa"])

    def test_safe_extract_zip_blocks_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("../escape.gltf", "{}")

            with self.assertRaisesRegex(ValueError, "Unsafe path"):
                safe_extract_zip(archive, root / "out")


if __name__ == "__main__":
    unittest.main()
