using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const string ResidentTextureRegionUpdatesCapability = "resident_texture_region_updates_v1";
    private const int MaxTextureDimension = 16384;
    private const long MaxTextureRegionBytes = 256L * 1024 * 1024;
    private readonly Dictionary<string, long> _lastRequestedTextureRegionGeneration = new(StringComparer.Ordinal);
    private readonly Dictionary<string, long> _lastAppliedTextureRegionGeneration = new(StringComparer.Ordinal);
    private readonly Dictionary<string, long> _lastAppliedTextureRevision = new(StringComparer.Ordinal);
    private long _textureRegionUpdateCount;
    private long _textureRegionAppliedCount;
    private long _textureRegionFailedCount;

    private void HandleTextureRegionUpdate(JsonElement root)
    {
        _textureRegionUpdateCount++;
        NetTextureRegionUpdate update;
        try
        {
            update = ParseTextureRegionUpdate(root);
            ValidateTextureRegionEnvelope(update);
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or ArgumentException or OverflowException)
        {
            WriteTextureRegionFailed(
                JsonString(root, "session_id"),
                JsonLongValue(root, "request_id"),
                JsonLongValue(root, "base_revision"),
                JsonLongValue(root, "process_generation"),
                JsonLongValue(root, "protocol_version"),
                JsonLongValue(root, "edit_revision"),
                JsonLongValue(root, "texture_revision"),
                JsonLongValue(root, "generation"),
                JsonString(root, "resource_id"),
                JsonString(root, "channel"),
                "invalid_payload",
                ex.Message);
            return;
        }

        if (update.RequestId <= 0)
        {
            WriteTextureRegionFailed(update, "missing_request_id", "Texture region update requires a correlated request id.");
            return;
        }
        if (update.ProcessGeneration <= 0 || update.ProcessGeneration != _residentProcessGeneration)
        {
            WriteTextureRegionFailed(update, "stale_process_generation", "Texture region update does not match the resident process generation.");
            return;
        }
        if (!AcceptMaterialSession(update.SessionId, out var sessionError))
        {
            WriteTextureRegionFailed(update, "session_mismatch", sessionError);
            return;
        }
        if (!CanApplyTextureEditRevision(update, out var revisionError))
        {
            WriteTextureRegionFailed(update, revisionError, "Texture edit revision does not match the resident session revision.");
            return;
        }
        if (update.AffectedSubmeshes.Any(index => index < 0 || index >= _document.Submeshes.Count))
        {
            WriteTextureRegionFailed(update, "invalid_submesh", "Texture region update references an unknown submesh.");
            return;
        }
        if (_lastRequestedTextureRegionGeneration.TryGetValue(update.ResourceId, out var requested)
            && update.Generation <= requested)
        {
            WriteTextureRegionFailed(update, "stale_generation", "Texture region generation is not newer than the last request for this resource.");
            return;
        }
        if (_lastAppliedTextureRevision.TryGetValue(update.ResourceId, out var appliedRevision)
            && update.TextureRevision < appliedRevision)
        {
            WriteTextureRegionFailed(update, "stale_texture_revision", "Texture revision is older than the last applied revision for this resource.");
            return;
        }

        _lastRequestedTextureRegionGeneration[update.ResourceId] = update.Generation;
        _ = Task.Run(() => ReadTextureRegionBinary(update.Binary)).ContinueWith(task =>
        {
            if (IsDisposed || Disposing || !IsHandleCreated)
            {
                return;
            }
            try
            {
                BeginInvoke(new Action(() => CompleteTextureRegionUpdate(update, task)));
            }
            catch (InvalidOperationException)
            {
            }
        }, TaskScheduler.Default);
    }

    private void CompleteTextureRegionUpdate(NetTextureRegionUpdate update, Task<byte[]> task)
    {
        if (!_lastRequestedTextureRegionGeneration.TryGetValue(update.ResourceId, out var requested)
            || requested != update.Generation)
        {
            WriteTextureRegionFailed(update, "superseded", "A newer texture generation replaced this request.");
            return;
        }
        if (!CanApplyTextureEditRevision(update, out var revisionError))
        {
            WriteTextureRegionFailed(update, revisionError, "Resident edit revision changed while the texture patch was loading.");
            return;
        }
        if (_lastAppliedTextureRevision.TryGetValue(update.ResourceId, out var appliedRevision)
            && update.TextureRevision < appliedRevision)
        {
            WriteTextureRegionFailed(update, "stale_texture_revision", "Texture revision became stale while the patch was loading.");
            return;
        }
        if (task.IsCanceled || task.IsFaulted)
        {
            WriteTextureRegionFailed(update, "binary_read_failed", task.Exception?.GetBaseException().Message ?? "Texture patch read was cancelled.");
            return;
        }
        if (!_viewport.TryApplyTextureRegion(update, task.Result, out var bytesUploaded, out var error))
        {
            WriteTextureRegionFailed(update, "renderer_rejected", error);
            return;
        }

        _lastAppliedTextureRegionGeneration[update.ResourceId] = update.Generation;
        _lastAppliedTextureRevision[update.ResourceId] = update.TextureRevision;
        _textureRegionAppliedCount++;
        MarkEditRevisionApplied(update.EditRevision);
        WriteProtocolEvent("texture_region_applied", TextureRegionPayload(update, new Dictionary<string, object?>
        {
            ["bytes_uploaded"] = bytesUploaded,
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentTextureRegionUpdatesCapability },
        }));
    }

    private void WriteTextureRegionFailed(NetTextureRegionUpdate update, string reason, string message)
    {
        WriteTextureRegionFailed(
            update.SessionId,
            update.RequestId,
            update.BaseRevision,
            update.ProcessGeneration,
            update.ProtocolVersion,
            update.EditRevision,
            update.TextureRevision,
            update.Generation,
            update.ResourceId,
            update.Channel,
            reason,
            message,
            update);
    }

    private void WriteTextureRegionFailed(
        string sessionId,
        long requestId,
        long baseRevision,
        long processGeneration,
        long protocolVersion,
        long editRevision,
        long textureRevision,
        long generation,
        string resourceId,
        string channel,
        string reason,
        string message,
        NetTextureRegionUpdate? update = null)
    {
        _textureRegionFailedCount++;
        var extra = new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["request_id"] = requestId,
            ["base_revision"] = baseRevision,
            ["process_generation"] = processGeneration,
            ["protocol_version"] = protocolVersion,
            ["edit_revision"] = editRevision,
            ["texture_revision"] = textureRevision,
            ["generation"] = generation,
            ["resource_id"] = resourceId,
            ["channel"] = channel,
            ["reason"] = reason,
            ["message"] = message,
            ["last_applied_generation"] = _lastAppliedTextureRegionGeneration.GetValueOrDefault(resourceId),
            ["last_applied_texture_revision"] = _lastAppliedTextureRevision.GetValueOrDefault(resourceId),
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentTextureRegionUpdatesCapability },
        };
        WriteProtocolEvent("texture_region_failed", update is null ? extra : TextureRegionPayload(update, extra));
    }

    private static Dictionary<string, object?> TextureRegionPayload(
        NetTextureRegionUpdate update,
        Dictionary<string, object?> payload)
    {
        payload["session_id"] = update.SessionId;
        payload["request_id"] = update.RequestId;
        payload["base_revision"] = update.BaseRevision;
        payload["process_generation"] = update.ProcessGeneration;
        payload["protocol_version"] = update.ProtocolVersion;
        payload["edit_revision"] = update.EditRevision;
        payload["texture_revision"] = update.TextureRevision;
        payload["generation"] = update.Generation;
        payload["resource_id"] = update.ResourceId;
        payload["channel"] = update.Channel;
        payload["affected_submeshes"] = update.AffectedSubmeshes;
        payload["rect"] = new Dictionary<string, object?>
        {
            ["x"] = update.Rect.X,
            ["y"] = update.Rect.Y,
            ["width"] = update.Rect.Width,
            ["height"] = update.Rect.Height,
        };
        return payload;
    }

    private bool CanApplyTextureEditRevision(NetTextureRegionUpdate update, out string reason)
    {
        reason = string.Empty;
        var residentRevision = Math.Max(_lastAppliedEditRevision, _lastObservedSessionRevision);
        if (update.EditRevision < residentRevision)
        {
            reason = "stale_edit_revision";
            return false;
        }
        if (update.EditRevision > residentRevision && update.BaseRevision != residentRevision)
        {
            reason = "future_edit_revision";
            return false;
        }
        return true;
    }

    private NetTextureRegionUpdate ParseTextureRegionUpdate(JsonElement root)
    {
        if (!string.Equals(JsonString(root, "schema"), "cdmw_resident_texture_region_update_v1", StringComparison.Ordinal)
            || JsonLongValue(root, "version") != 1)
        {
            throw new InvalidDataException("Texture region update requires cdmw_resident_texture_region_update_v1 version 1.");
        }
        if (!root.TryGetProperty("rect", out var rect) || rect.ValueKind != JsonValueKind.Object
            || !root.TryGetProperty("binary", out var binary) || binary.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("Texture region update requires rect and binary objects.");
        }
        var path = Path.GetFullPath(JsonString(binary, "path"));
        var deleteAfter = JsonBoolean(binary, "delete_after");
        if (!deleteAfter || !OwnedTextureBinaryPath(path))
        {
            throw new InvalidDataException("Texture patch must be an owned regular .bgra file under the editor output directory.");
        }
        return new NetTextureRegionUpdate(
            JsonString(root, "session_id").Trim(),
            JsonLongValue(root, "request_id"),
            JsonLongValue(root, "base_revision"),
            JsonLongValue(root, "process_generation"),
            JsonLongValue(root, "protocol_version"),
            JsonLongValue(root, "edit_revision"),
            JsonLongValue(root, "texture_revision"),
            JsonLongValue(root, "generation"),
            JsonString(root, "resource_id").Trim(),
            JsonString(root, "channel").Trim().ToLowerInvariant(),
            JsonIntValues(root, "affected_submeshes").Distinct().Order().ToArray(),
            JsonInt(root, "texture_width", 0),
            JsonInt(root, "texture_height", 0),
            new NetTextureRegionRect(JsonInt(rect, "x", -1), JsonInt(rect, "y", -1), JsonInt(rect, "width", 0), JsonInt(rect, "height", 0)),
            JsonString(root, "pixel_format").Trim().ToLowerInvariant(),
            JsonInt(root, "row_pitch", 0),
            new NetTextureRegionBinary(
                path,
                JsonLongValue(binary, "offset"),
                JsonLongValue(binary, "length"),
                JsonString(binary, "sha256").Trim(),
                deleteAfter));
    }

    private static void ValidateTextureRegionEnvelope(NetTextureRegionUpdate update)
    {
        if (string.IsNullOrWhiteSpace(update.SessionId) || string.IsNullOrWhiteSpace(update.ResourceId))
            throw new InvalidDataException("Texture region update requires session_id and resource_id.");
        if (update.ProtocolVersion < 2 || update.BaseRevision < 0 || update.EditRevision < update.BaseRevision)
            throw new InvalidDataException("Texture region update requires a valid mutation envelope.");
        if (!string.Equals(update.Channel, "base", StringComparison.Ordinal))
            throw new InvalidDataException("Resident dirty-region editing currently supports only the base channel.");
        if (update.EditRevision < 0 || update.TextureRevision < 0 || update.Generation <= 0)
            throw new InvalidDataException("Texture region revisions must be nonnegative and generation must be positive.");
        if (update.AffectedSubmeshes.Count == 0 || update.AffectedSubmeshes.Any(index => index < 0))
            throw new InvalidDataException("Texture region update requires valid affected_submeshes.");
        if (update.TextureWidth <= 0 || update.TextureHeight <= 0 || update.TextureWidth > MaxTextureDimension || update.TextureHeight > MaxTextureDimension)
            throw new InvalidDataException("Texture dimensions are outside the supported range.");
        if (update.Rect.X < 0 || update.Rect.Y < 0 || update.Rect.Width <= 0 || update.Rect.Height <= 0
            || checked(update.Rect.X + update.Rect.Width) > update.TextureWidth
            || checked(update.Rect.Y + update.Rect.Height) > update.TextureHeight)
            throw new InvalidDataException("Texture patch rectangle is outside the texture bounds.");
        if (!string.Equals(update.PixelFormat, "bgra8_unorm", StringComparison.Ordinal))
            throw new InvalidDataException("Texture patch pixel_format must be bgra8_unorm.");
        var minimumPitch = checked(update.Rect.Width * 4);
        var expectedLength = checked((long)update.RowPitch * update.Rect.Height);
        if (update.RowPitch < minimumPitch || expectedLength <= 0 || expectedLength > MaxTextureRegionBytes || update.Binary.Length != expectedLength)
            throw new InvalidDataException("Texture patch row_pitch or binary length is invalid.");
        if (update.Binary.Offset < 0 || update.Binary.Sha256.Length != 64 || !update.Binary.Sha256.All(Uri.IsHexDigit))
            throw new InvalidDataException("Texture patch binary descriptor is invalid.");
    }

    private static byte[] ReadTextureRegionBinary(NetTextureRegionBinary binary)
    {
        try
        {
            using var stream = new FileStream(binary.Path, FileMode.Open, FileAccess.Read, FileShare.Read, 64 * 1024, FileOptions.SequentialScan);
            if (checked(binary.Offset + binary.Length) > stream.Length)
                throw new InvalidDataException("Texture patch binary range exceeds the file length.");
            stream.Position = binary.Offset;
            var bytes = GC.AllocateUninitializedArray<byte>(checked((int)binary.Length));
            stream.ReadExactly(bytes);
            var expectedHash = Convert.FromHexString(binary.Sha256);
            var actualHash = SHA256.HashData(bytes);
            if (!CryptographicOperations.FixedTimeEquals(expectedHash, actualHash))
                throw new InvalidDataException("Texture patch SHA-256 mismatch.");
            return bytes;
        }
        finally
        {
            if (binary.DeleteAfter)
            {
                File.Delete(binary.Path);
            }
        }
    }

    private bool OwnedTextureBinaryPath(string path)
    {
        if (!PathWithin(path, _options.OutputDir)
            || !Path.GetExtension(path).Equals(".bgra", StringComparison.OrdinalIgnoreCase)
            || !File.Exists(path))
        {
            return false;
        }
        var root = Path.GetFullPath(_options.OutputDir);
        var current = new FileInfo(path);
        if ((current.Attributes & FileAttributes.ReparsePoint) != 0)
        {
            return false;
        }
        for (var directory = current.Directory; directory is not null; directory = directory.Parent)
        {
            if ((directory.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                return false;
            }
            if (string.Equals(directory.FullName, root, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

    private static bool PathWithin(string path, string root)
    {
        if (string.IsNullOrWhiteSpace(root)) return false;
        var relative = Path.GetRelativePath(Path.GetFullPath(root), path);
        return !Path.IsPathRooted(relative)
            && !string.Equals(relative, "..", StringComparison.Ordinal)
            && !relative.StartsWith($"..{Path.DirectorySeparatorChar}", StringComparison.Ordinal);
    }

    private static long JsonLongValue(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value)) return 0;
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)) return number;
        return value.ValueKind == JsonValueKind.String
            && long.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number) ? number : 0;
    }

    private static bool JsonBoolean(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.String => bool.TryParse(value.GetString(), out var parsed) && parsed,
            _ => false,
        };
    }
}

internal sealed record NetTextureRegionUpdate(
    string SessionId,
    long RequestId,
    long BaseRevision,
    long ProcessGeneration,
    long ProtocolVersion,
    long EditRevision,
    long TextureRevision,
    long Generation,
    string ResourceId,
    string Channel,
    IReadOnlyList<int> AffectedSubmeshes,
    int TextureWidth,
    int TextureHeight,
    NetTextureRegionRect Rect,
    string PixelFormat,
    int RowPitch,
    NetTextureRegionBinary Binary);

internal readonly record struct NetTextureRegionRect(int X, int Y, int Width, int Height);
internal sealed record NetTextureRegionBinary(string Path, long Offset, long Length, string Sha256, bool DeleteAfter);
