from dataclasses import replace
from pathlib import Path

from cdmw.models import TextureEditorDocument, TextureEditorSourceBinding
from cdmw.ui.texture_workflow.editor_session import _TextureEditorSession
from cdmw.ui.texture_workflow.job import TextureJob


def _session(path: str) -> _TextureEditorSession:
    binding = TextureEditorSourceBinding(
        source_path=path, original_dds_path=path,
        archive_relative_path="textures/coat.dds", original_dds_format="BC7_UNORM",
    )
    document = TextureEditorDocument("coat.dds", 4, 4, source_binding=binding)
    return _TextureEditorSession("coat.dds", document, {}, [{"checkpoint": "original"}], 0)


def test_mode_changes_retain_the_sessions_history_selection_and_original_target() -> None:
    job = TextureJob()
    session = _session("coat.dds")
    job.sessions.append(session)
    job.synchronize_sessions(0)
    asset = job.assets[job.active_asset_key]
    original_history = session.history_snapshots
    token = job.begin("upscale")
    for mode in ("recolor", "upscale", "edit"):
        job.mode = mode
        job.synchronize_sessions(0)
        assert asset.session is session
        assert session.history_snapshots is original_history
        assert asset.key in job.selected
        assert asset.source_binding.original_dds_path == "coat.dds"
        assert asset.source_binding.original_dds_format == "BC7_UNORM"
    assert job.complete(token, Path("output.dds"))


def test_edited_or_cancelled_requests_cannot_replace_usable_results() -> None:
    job = TextureJob()
    session = _session("coat.dds")
    job.sessions.append(session)
    job.synchronize_sessions(0)
    assert job.complete(job.begin("upscale"), "previous usable output")
    pending = job.begin("upscale")
    session.document = replace(session.document, composite_revision=1)
    assert not job.complete(pending, "stale output")
    pending = job.begin("upscale")
    job.cancel("upscale")
    assert not job.complete(pending, "cancelled output")
    assert [result.value for result in job.results] == ["previous usable output"]


def test_newer_request_wins_without_conflating_files_that_share_a_name() -> None:
    job = TextureJob()
    first = job.add_source(Path("first/coat.dds"))
    second = job.add_source(Path("second/coat.dds"))
    assert first is not second
    assert job.add_source(Path("first/coat.dds")) is first
    job.set_selected([second.key])
    old = job.begin("preview")
    new = job.begin("preview")
    assert not job.accept(old)
    assert job.accept(new)
    assert job.selected == {second.key}


def test_batch_result_rejects_changed_selection_but_preview_tracks_its_explicit_asset() -> None:
    job = TextureJob()
    first = job.add_source(Path("first.dds"))
    second = job.add_source(Path("second.dds"))
    batch = job.begin("upscale")
    preview = job.begin("preview", asset_keys=[first.key])
    job.set_selected([second.key])
    assert not job.accept(batch)
    assert job.accept(preview)
