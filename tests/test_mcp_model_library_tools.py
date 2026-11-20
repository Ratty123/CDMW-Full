from PySide6.QtCore import QTimer

from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_model_library_icon_output_async import _app, _image, _tab_with_selection


def test_model_library_sources_use_and_generate_icon_through_the_page(tmp_path, monkeypatch):
    _app()
    tab, payload, item = _tab_with_selection(tmp_path)
    client = RailClient(tmp_path, widgets={"model_library": tab})
    path = tmp_path / "hero.obj"
    path.write_text("v 0 0 0\n", encoding="utf-8")
    from PySide6.QtCore import Qt

    payload["import_supported"] = True
    item.setData(0, Qt.ItemDataRole.UserRole, payload)
    tab._update_selection_state()
    seen = []
    tab.use_in_new_item_studio_requested.connect(lambda source, row: seen.append((source, row["name"])))
    catalogue = tmp_path / "catalogue"
    catalogue.mkdir()
    try:
        state = client.ok("models.state")
        assert state["rows"][0]["name"] == "Async Hero"
        client.ok("models.change", action="use", row=0)
        wait_for(lambda: bool(seen))
        assert seen[-1] == (str(path), payload["name"])

        host = tab._ensure_inline_d3d11_preview_host()
        tab.inline_preview_stack.setCurrentWidget(host)
        tab._inline_preview_loaded_payload = dict(payload)
        tab._inline_preview_loaded_import_path = path

        def capture(destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            assert _image().save(str(destination))
            QTimer.singleShot(0, lambda: tab._handle_inline_dotnet_capture_completed({"status": "captured"}))
            return True

        monkeypatch.setattr(host, "capture_replacement_icon", capture)
        icons = []
        tab.item_icon_source_generated.connect(lambda icon, _row: icons.append(icon))
        client.ok("models.output", action="icon", folder=str(catalogue), row=0)
        wait_for(lambda: bool(icons))
        assert list((catalogue / "generated_icons").glob("*.png"))

        client.ok("models.change", action="add_source", path=str(tmp_path))
        wait_for(lambda: tab._task_thread is None)
        assert str(tmp_path) in tab.local_roots
        tab.settings.sync()
        assert str(tmp_path).replace("\\", "\\\\") in tab.settings.value("model_library/local_roots_json")
    finally:
        tab.request_shutdown()
        wait_for(lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()


def test_model_library_index_and_checked_download_use_the_page_workers(tmp_path, monkeypatch):
    import json
    import zipfile
    from cdmw.core.model_catalogue import DEFAULT_MODEL_MIRROR_URL, catalogue_stats
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.model_library.tab import ModelLibraryTab

    _app()
    tab = ModelLibraryTab(settings=create_settings(settings_file_path=tmp_path / "settings.ini"), base_dir=tmp_path)
    client = RailClient(tmp_path, widgets={"model_library": tab})
    folder = tmp_path / "catalogue"
    folder.mkdir()

    def fetch(url, *, timeout):
        if url.endswith("+README/"):
            return "Owned model fixture"
        if url.endswith("+catalogue/"):
            return '<a href="owned.json">owned.json</a>'
        assert url.endswith("owned.json")
        return json.dumps({"results": [{"uid": "aaaa", "name": "Owned Sword", "archives": {"gltf": {"size": 10}}}]})

    def download(_url, destination, *, timeout, **_):
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("scene.gltf", '{"asset":{"version":"2.0"}}')

    monkeypatch.setattr("cdmw.core.model_catalogue._fetch_text", fetch)
    monkeypatch.setattr("cdmw.core.model_catalogue._download_url_to_file", download)
    try:
        client.ok("models.output", action="index", folder=str(folder), mirror_url=DEFAULT_MODEL_MIRROR_URL)
        wait_for(lambda: tab._task_thread is None)
        assert catalogue_stats(folder / "mirror_catalogue.sqlite")["models"] == 1
        client.ok("models.change", action="search", view="mirror", query="Owned Sword")
        wait_for(lambda: tab.results_tree.topLevelItemCount() == 1 and tab._task_thread is None)
        client.ok("models.output", action="download", folder=str(folder), rows=[0], formats=["gltf"])
        wait_for(lambda: tab._task_thread is None)
        assert list((folder / "downloads").rglob("*.zip"))
    finally:
        tab.request_shutdown()
        wait_for(lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()


def test_model_library_deletes_only_downloaded_copies(tmp_path, monkeypatch):
    from cdmw.workers.model_library_rows import ModelLibraryDeleteTarget, model_library_delete_identity

    _app()
    tab, _payload, _item = _tab_with_selection(tmp_path)
    client = RailClient(tmp_path, widgets={"model_library": tab})
    try:
        # A local file of the user's is not a download: refused, nothing deleted.
        monkeypatch.setattr(tab, "_downloaded_model_folder_target_for_payload", lambda payload: None)
        refused = client.call("models.delete", action="downloads", rows=[0])
        assert refused["error"]["code"] == "refused"

        folder = tmp_path / "catalogue" / "downloads" / "hero-abc123"
        folder.mkdir(parents=True)
        (folder / "hero.glb").write_bytes(b"glb")
        (folder / "model_metadata.json").write_text('{"uid": "abc123"}', encoding="utf-8")
        target = ModelLibraryDeleteTarget(str(folder), "Async Hero", "download_dir", str(folder.parent),
                                          model_library_delete_identity(folder))
        monkeypatch.setattr(tab, "_downloaded_model_folder_target_for_payload", lambda payload: target)
        monkeypatch.setattr(tab, "_local_delete_targets_for_payloads", lambda payloads: [target])
        client.ok("models.delete", action="downloads", rows=[0])
        wait_for(lambda: not folder.exists())
        assert client.call("models.delete", action="downloads", rows=[99])["error"]["code"] == "not_found"
    finally:
        tab.request_shutdown()
        wait_for(lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
