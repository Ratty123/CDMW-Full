from pathlib import Path
import threading

import pytest

from cdmw.models import AppConfig, RunCancelled, RunSummary
from cdmw.services.texture_job_service import TextureJobInput, run_texture_job_pipeline


@pytest.mark.parametrize("outcome", ["success", "preparation_failed", "publication_failed", "cancelled"])
def test_replacement_profiles_and_zips_publish_together_or_preserve_prior_output(tmp_path, monkeypatch, outcome):
    from cdmw.core import replace_assistant_package as packaging
    from cdmw.domain.packages.export_policy import mod_package_export_options_for_profiles
    from cdmw.models import ModPackageInfo
    import zipfile

    source = tmp_path / "source"
    source.mkdir()
    texture = source / "coat.dds"
    texture.write_bytes(b"previous")
    output = tmp_path / "packages"
    options = dict(
        output_parent=output, package_info=ModPackageInfo(title="Texture job"),
        export_options=mod_package_export_options_for_profiles(("dmm", "jmm"), create_zip=True),
        create_no_encrypt_file=False, overwrite=True, file_count=1,
    )
    packaging.publish_replace_assistant_packages(source, **options)

    def snapshot():
        return {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}

    previous = snapshot()
    assert any(name.endswith(".zip") for name in previous)
    texture.write_bytes(b"updated")
    stop = threading.Event()
    write_manifest = packaging.write_mod_package_manifest
    replace_path = Path.replace
    calls = 0

    def prepare(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected preparation failure")
        return write_manifest(*args, **kwargs)

    def publish(path, target):
        nonlocal calls
        if path.parent.name.startswith(".cdmw-replacement-"):
            calls += 1
            if outcome == "publication_failed" and calls == 2:
                raise OSError("injected publication failure")
            result = replace_path(path, target)
            if outcome == "cancelled":
                stop.set()
            return result
        return replace_path(path, target)

    if outcome == "preparation_failed":
        monkeypatch.setattr(packaging, "write_mod_package_manifest", prepare)
    elif outcome != "success":
        monkeypatch.setattr(Path, "replace", publish)
    if outcome == "success":
        packaging.publish_replace_assistant_packages(source, stop_event=stop, **options)
        assert all(p.read_bytes() == b"updated" for p in output.rglob("*.dds"))
        for path in output.glob("*.zip"):
            with zipfile.ZipFile(path) as archive:
                assert all(archive.read(name) == b"updated" for name in archive.namelist() if name.endswith(".dds"))
    else:
        with pytest.raises((RuntimeError, OSError, RunCancelled)):
            packaging.publish_replace_assistant_packages(source, stop_event=stop, **options)
        assert snapshot() == previous
    assert not any(path.name.startswith(".") for path in output.iterdir())


def _config(tmp_path):
    return AppConfig(original_dds_root=str(tmp_path / "original"), png_root=str(tmp_path / "png"),
                     output_root=str(tmp_path / "output"), enable_dds_staging=False,
                     enable_mod_ready_loose_export=False)


@pytest.mark.parametrize("outcome", ["success", "failed", "cancelled"])
def test_job_publishes_complete_selected_outputs_only(tmp_path, outcome):
    config = _config(tmp_path)
    original = tmp_path / "source.dds"
    original.write_bytes(b"original")
    final = Path(config.output_root)
    final.mkdir()
    (final / "chosen.dds").write_bytes(b"previous")
    (final / "unrelated.dds").write_bytes(b"keep")
    stop = threading.Event()

    def pipeline(staged, **callbacks):
        assert Path(staged.original_dds_root) != original.parent
        assert [p.name for p in Path(staged.original_dds_root).rglob("*.dds")] == ["chosen.dds"]
        assert (Path(staged.original_dds_root) / "chosen.dds").read_bytes() == b"original"
        assert (final / "chosen.dds").read_bytes() == b"previous"
        (Path(staged.output_root) / "chosen.dds").write_bytes(b"new")
        (Path(staged.png_root) / "chosen.png").write_bytes(b"png")
        if outcome == "cancelled":
            callbacks["stop_event"].set()
        return RunSummary(total_files=1, converted=1, skipped=0, failed=int(outcome == "failed"))

    inputs = (TextureJobInput("chosen.dds", original),)
    if outcome == "cancelled":
        with pytest.raises(RunCancelled):
            run_texture_job_pipeline(config, inputs, pipeline, stop_event=stop)
    else:
        run_texture_job_pipeline(config, inputs, pipeline, stop_event=stop)
    assert (final / "chosen.dds").read_bytes() == (b"new" if outcome == "success" else b"previous")
    assert (final / "unrelated.dds").read_bytes() == b"keep"
    assert original.read_bytes() == b"original"
    assert (Path(config.png_root) / "chosen.png").exists() == (outcome == "success")
    assert not list(tmp_path.glob(".cdmw-texture-*"))


def test_job_requires_unambiguous_targets_before_running(tmp_path):
    config = _config(tmp_path)
    source = tmp_path / "source.dds"
    source.write_bytes(b"original")
    def forbidden(*args, **kwargs):
        pytest.fail("Pipeline must not start before target validation")
    for inputs in ((TextureJobInput("../outside.dds", source),),
                   (TextureJobInput("same.dds", source), TextureJobInput("SAME.dds", source))):
        with pytest.raises(ValueError):
            run_texture_job_pipeline(config, inputs, forbidden, stop_event=threading.Event())


def test_zip_original_is_materialized_without_extra_pipeline_inputs(tmp_path):
    import zipfile
    from cdmw.core.recolor_variants import analyze_recolor_variant_package
    from tests.test_recolor_variants import _write_mod

    source = _write_mod(tmp_path)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in source.rglob("*"):
            if path.is_file():
                handle.write(path, path.relative_to(source).as_posix())
    analysis = analyze_recolor_variant_package(archive)
    target = next(target for target in analysis.targets if target.target_kind == "texture_slot")

    def pipeline(staged, **callbacks):
        root = Path(staged.original_dds_root)
        assert [path.relative_to(root).as_posix() for path in root.rglob("*.dds")] == [target.game_path]
        return RunSummary(1, 1, 0, 0)

    run_texture_job_pipeline(
        _config(tmp_path), (TextureJobInput(target.game_path, None, package_path=archive, package_target=target),),
        pipeline, stop_event=threading.Event(),
    )


def test_edited_input_uses_current_pixels_and_original_dds_metadata(tmp_path, monkeypatch):
    from PIL import Image
    from cdmw.core import texture_native
    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.services.texture_editor_service import TextureEditorService
    from cdmw.services.texture_job_service import write_texture_job_input
    from tests.test_recolor_variants import _write_mod

    source = next(_write_mod(tmp_path).rglob("*.dds"))
    info = parse_dds(source)
    png = tmp_path / "edit.png"
    Image.new("RGBA", (8, 8), (20, 40, 160, 255)).save(png)
    document, pixels, _ = TextureEditorService.create_document_from_source(png, workspace_root=tmp_path / "editor")
    observed = []
    def encode(png_path, destination, **options):
        observed.append((Image.open(png_path).getpixel((0, 0)), options))
        Path(destination).write_bytes(b"edited DDS")
        return True
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", encode)
    destination = tmp_path / "stage" / "edited.dds"
    write_texture_job_input(TextureJobInput("edited.dds", source, document, pixels), destination, stop_event=threading.Event())
    assert observed[0][0] == (20, 40, 160, 255)
    assert observed[0][1]["dds_format"] == info.dds_format
    assert observed[0][1]["mip_count"] == info.mip_count
    assert destination.read_bytes() == b"edited DDS"
