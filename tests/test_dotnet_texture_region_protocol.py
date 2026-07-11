from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")


def test_dotnet_texture_region_protocol_is_negotiated_validated_and_acknowledged() -> None:
    protocol = _source("ExperimentForm.Protocol.cs")
    region = _source("ExperimentForm.TextureRegionProtocol.cs")
    status = _source("MeshViewport.Status.cs")

    assert 'ResidentTextureRegionUpdatesCapability = "resident_texture_region_updates_v1"' in region
    assert 'case "texture_region_update":' in protocol
    assert "HandleTextureRegionUpdate(document.RootElement);" in protocol
    assert "ResidentTextureRegionUpdatesCapability" in protocol
    assert 'capabilities.Add("resident_texture_region_updates_v1")' in status
    assert 'WriteProtocolEvent("texture_region_applied"' in region
    assert 'WriteProtocolEvent("texture_region_failed"' in region
    for field in (
        "session_id",
        "edit_revision",
        "texture_revision",
        "generation",
        "resource_id",
        "channel",
        "affected_submeshes",
        "texture_width",
        "texture_height",
        "pixel_format",
        "row_pitch",
        "binary",
        "sha256",
        "delete_after",
    ):
        assert f'"{field}"' in region


def test_dotnet_texture_region_binary_contract_checks_bounds_sizes_and_hash() -> None:
    source = _source("ExperimentForm.TextureRegionProtocol.cs")

    assert "MaxTextureDimension = 16384" in source
    assert "MaxTextureRegionBytes = 256L * 1024 * 1024" in source
    assert "checked(update.Rect.X + update.Rect.Width)" in source
    assert "checked(update.Rect.Y + update.Rect.Height)" in source
    assert "checked(update.Rect.Width * 4)" in source
    assert "checked((long)update.RowPitch * update.Rect.Height)" in source
    assert '"bgra8_unorm"' in source
    assert "checked(binary.Offset + binary.Length)" in source
    assert "stream.ReadExactly(bytes);" in source
    assert "SHA256.HashData(bytes)" in source
    assert "CryptographicOperations.FixedTimeEquals" in source
    assert '"cdmw_resident_texture_region_update_v1"' in source
    assert 'JsonLongValue(root, "version") != 1' in source
    assert 'string.Equals(update.Channel, "base"' in source
    assert "PathWithin(path, _options.OutputDir)" in source
    assert "Path.GetTempPath()" not in source
    assert "FileAttributes.ReparsePoint" in source
    assert "File.Delete(binary.Path);" in source
    assert "CanApplyMaterialEditRevision(update.EditRevision" in source
    assert 'WriteTextureRegionFailed(update, "invalid_submesh"' in source
    assert "_lastRequestedTextureRegionGeneration" in source
    assert '"stale_generation"' in source
    assert '"superseded"' in source


def test_dotnet_texture_region_gpu_path_is_copy_on_write_then_boxed_upload_only() -> None:
    source = _source("D3D11MaterialViewport.TextureRegions.cs")
    resources = _source("D3D11MaterialViewport.Resources.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")

    existing, first = source.split(
        "if (_editableTextureRegions.TryGetValue(update.ResourceId, out var editable))",
        maxsplit=1,
    )[1].split('if (!_textureSrvCache.TryGetValue(sourceCacheKey, out var source))', maxsplit=1)
    assert "UploadTextureRegion(editable.Texture, update, pixels);" in existing
    assert "CreateTexture2D" not in existing
    assert "CreateShaderResourceView" not in existing
    assert "WithShaderResource" not in existing
    assert "Usage = ResourceUsage.Default" in first
    assert "_context.CopyResource(texture, source.Texture);" in first
    assert "_device.CreateShaderResourceView(texture);" in first
    assert "WithShaderResource(channelIndex, view)" in first
    assert "new Box(" in source
    assert "(uint)update.RowPitch" in source
    assert "resource_id does not match the active affected-submesh channel" in source
    assert "Last-good immutable source texture is not resident" in source

    assert "ID3D11Texture2D Texture" in resources
    assert "entry.View.Dispose();" in resources
    assert "entry.Texture.Dispose();" in resources
    assert "PruneEditableTextureRegions();" in resources
    for metric in (
        "texture_region_patch_count",
        "texture_region_bytes_uploaded",
        "texture_region_failure_count",
        "texture_region_affected_batch_rebinds",
        "editable_texture_resources",
    ):
        assert f'["{metric}"]' in metrics


def test_dotnet_texture_region_lifecycle_counts_are_reported() -> None:
    source = _source("ExperimentForm.MaterialProtocol.cs")

    assert '["texture_region_update_count"] = _textureRegionUpdateCount' in source
    assert '["texture_region_applied_count"] = _textureRegionAppliedCount' in source
    assert '["texture_region_failed_count"] = _textureRegionFailedCount' in source
