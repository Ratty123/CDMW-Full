using System.Security.Cryptography;
using System.Text;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchivePreviewService
{
    private const long MaximumPreviewBytes = 64L * 1024L * 1024L;
    private const string PreviewArtifactVersion = "preview_v3_native_media";
    private static readonly HashSet<string> DirectAudioExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".wma",
    };
    private static readonly HashSet<string> DirectVideoExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".avi", ".bk2", ".m4v", ".mov", ".mp4", ".mpeg", ".mpg", ".webm", ".wmv",
    };
    private readonly ArchiveSessionManager _sessions;
    private readonly NativeArchiveCore _native;
    private readonly NativeModelPreviewService _modelPreviews;
    private readonly NativeTexturePreviewService _texturePreviews;
    private readonly NativeMediaPreviewService _mediaPreviews;
    private readonly TextDocumentPreviewService _textDocuments;

    public ArchivePreviewService(
        ArchiveSessionManager sessions,
        NativeArchiveCore native,
        NativeModelPreviewService? modelPreviews = null,
        NativeTexturePreviewService? texturePreviews = null,
        NativeMediaPreviewService? mediaPreviews = null,
        TextDocumentPreviewService? textDocuments = null)
    {
        _sessions = sessions;
        _native = native;
        _modelPreviews = modelPreviews ?? new NativeModelPreviewService();
        _texturePreviews = texturePreviews ?? new NativeTexturePreviewService();
        _mediaPreviews = mediaPreviews ?? new NativeMediaPreviewService();
        _textDocuments = textDocuments ?? new TextDocumentPreviewService();
    }

    public Task<PreviewResult> BuildAsync(
        PreviewRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? publishProgress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = _sessions.GetRequired(request.SessionId);
        return Task.Run(
            async () => await BuildCoreAsync(session, request, publishProgress, cancellationToken).ConfigureAwait(false),
            cancellationToken);
    }

    private async Task<PreviewResult> BuildCoreAsync(
        ArchiveSession session,
        PreviewRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        var entry = session.Index.ReadEntry(request.EntryId);
        var metadata = BuildMetadata(entry);
        var warnings = new List<string>();
        if (NativeModelPreviewService.Supports(entry.Extension))
        {
            try
            {
                var package = await _modelPreviews.BuildAsync(
                    session,
                    entry,
                    publishProgress,
                    cancellationToken).ConfigureAwait(false);
                return new PreviewResult(
                    session.Id,
                    entry.EntryId,
                    PreviewKind.Model,
                    entry.Name,
                    metadata,
                    ArtifactPath: package,
                    Warnings: warnings);
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception)
            {
                warnings.Add($".NET model preview unavailable: {exception.Message}");
            }
        }

        if (entry.OriginalSize > MaximumPreviewBytes)
        {
            return new PreviewResult(
                session.Id,
                entry.EntryId,
                NativeModelPreviewService.Supports(entry.Extension) ? PreviewKind.Model : PreviewKind.Metadata,
                entry.Name,
                metadata,
                Text: metadata,
                Warnings: [.. warnings, $"Preview was not decoded because the entry exceeds {MaximumPreviewBytes / (1024 * 1024)} MiB."]);
        }
        cancellationToken.ThrowIfCancellationRequested();
        var decoded = _native.Decode(entry);
        cancellationToken.ThrowIfCancellationRequested();
        if (!string.IsNullOrWhiteSpace(decoded.Note)) warnings.Add(decoded.Note);

        if (entry.Role is ArchiveEntryRole.Text or ArchiveEntryRole.Metadata || LooksTextual(decoded.Bytes))
        {
            var artifact = await _textDocuments.PublishAsync(
                $"archive|{session.Fingerprint}|{entry.EntryId}|{entry.Path}",
                entry.Path,
                decoded.Bytes,
                cancellationToken).ConfigureAwait(false);
            return new PreviewResult(
                session.Id,
                entry.EntryId,
                PreviewKind.Text,
                entry.Name,
                metadata,
                ArtifactPath: artifact.Path,
                Warnings: warnings,
                Syntax: artifact.Syntax);
        }

        if (entry.Role is ArchiveEntryRole.Image or ArchiveEntryRole.Normal or ArchiveEntryRole.Material or ArchiveEntryRole.UserInterface or ArchiveEntryRole.Impostor)
        {
            var artifact = await PublishArtifactAsync(session, entry, decoded.Bytes, cancellationToken).ConfigureAwait(false);
            if (entry.Extension.Equals(".dds", StringComparison.OrdinalIgnoreCase))
            {
                try
                {
                    artifact = await _texturePreviews.BuildAsync(session, entry, artifact, cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (Exception exception)
                {
                    warnings.Add($"DirectXTex DDS preview unavailable: {exception.Message}");
                    return new PreviewResult(
                        session.Id,
                        entry.EntryId,
                        PreviewKind.Hex,
                        entry.Name,
                        metadata,
                        BuildHex(decoded.Bytes, request.BinaryByteLimit),
                        Warnings: warnings);
                }
            }
            return new PreviewResult(session.Id, entry.EntryId, PreviewKind.Image, entry.Name, metadata, ArtifactPath: artifact, Warnings: warnings);
        }

        if (entry.Role is ArchiveEntryRole.Audio or ArchiveEntryRole.Video)
        {
            var artifact = await PublishArtifactAsync(session, entry, decoded.Bytes, cancellationToken).ConfigureAwait(false);
            if (NativeMediaPreviewService.Supports(entry.Extension))
            {
                try
                {
                    artifact = await _mediaPreviews.BuildAsync(session, entry, artifact, cancellationToken).ConfigureAwait(false);
                    warnings.Add("Decoded for playback with bundled vgmstream.");
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (Exception exception)
                {
                    warnings.Add($"Wwise audio decode unavailable: {exception.Message}");
                    return new PreviewResult(
                        session.Id,
                        entry.EntryId,
                        PreviewKind.Hex,
                        entry.Name,
                        metadata,
                        BuildHex(decoded.Bytes, request.BinaryByteLimit),
                        Warnings: warnings);
                }
            }
            else if ((entry.Role == ArchiveEntryRole.Audio && !DirectAudioExtensions.Contains(entry.Extension))
                || (entry.Role == ArchiveEntryRole.Video && !DirectVideoExtensions.Contains(entry.Extension)))
            {
                warnings.Add($"No bundled decoder is available for {entry.Extension}; showing a binary preview instead.");
                return new PreviewResult(
                    session.Id,
                    entry.EntryId,
                    PreviewKind.Hex,
                    entry.Name,
                    metadata,
                    BuildHex(decoded.Bytes, request.BinaryByteLimit),
                    Warnings: warnings);
            }
            if (entry.Extension.Equals(".bk2", StringComparison.OrdinalIgnoreCase))
            {
                warnings.Add("BK2 playback requires a compatible Bink/Media Foundation codec installed on Windows.");
            }
            var kind = entry.Role == ArchiveEntryRole.Audio ? PreviewKind.Audio : PreviewKind.Video;
            return new PreviewResult(session.Id, entry.EntryId, kind, entry.Name, metadata, ArtifactPath: artifact, MediaKind: entry.Role.ToString().ToLowerInvariant(), Warnings: warnings);
        }

        if (entry.Role is ArchiveEntryRole.Model or ArchiveEntryRole.Animation or ArchiveEntryRole.Physics)
        {
            var kind = entry.Role == ArchiveEntryRole.Model ? PreviewKind.Model : PreviewKind.Hkx;
            return new PreviewResult(
                session.Id,
                entry.EntryId,
                kind,
                entry.Name,
                metadata,
                Text: BuildHex(decoded.Bytes, request.BinaryByteLimit),
                Warnings: warnings);
        }

        return new PreviewResult(
            session.Id,
            entry.EntryId,
            PreviewKind.Hex,
            entry.Name,
            metadata,
            BuildHex(decoded.Bytes, request.BinaryByteLimit),
            Warnings: warnings);
    }

    private static string BuildMetadata(ArchiveEntryDto entry) => string.Join(
        Environment.NewLine,
        $"Path: {entry.Path}",
        $"Package: {entry.Package}",
        $"Source PAMT: {entry.SourcePamt}",
        $"PAZ: {entry.PazFile} ({entry.PazIndex})",
        $"Offset: 0x{entry.Offset:X}",
        $"Stored size: {entry.StoredSize:N0} bytes",
        $"Original size: {entry.OriginalSize:N0} bytes",
        $"Compression: {entry.CompressionType}",
        $"Encryption: {entry.EncryptionType}",
        $"Role: {entry.Role}");

    private static bool LooksTextual(byte[] bytes) => TextDecoding.LooksTextual(bytes);

    private static string BuildHex(byte[] bytes, int requestedLimit)
    {
        var limit = Math.Clamp(requestedLimit, 16, 4096);
        var count = Math.Min(bytes.Length, limit);
        var output = new StringBuilder(count * 4);
        for (var offset = 0; offset < count; offset += 16)
        {
            output.Append(offset.ToString("X8")).Append("  ");
            var lineCount = Math.Min(16, count - offset);
            for (var index = 0; index < 16; index++)
            {
                if (index < lineCount) output.Append(bytes[offset + index].ToString("X2"));
                else output.Append("  ");
                output.Append(index == 7 ? "  " : " ");
            }
            output.Append(' ');
            for (var index = 0; index < lineCount; index++)
            {
                var value = bytes[offset + index];
                output.Append(value is >= 0x20 and <= 0x7E ? (char)value : '.');
            }
            output.AppendLine();
        }
        if (bytes.Length > count) output.AppendLine($"… {bytes.Length - count:N0} additional bytes");
        return output.ToString();
    }

    private static async Task<string> PublishArtifactAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        byte[] bytes,
        CancellationToken cancellationToken)
    {
        ArchiveLiteDataPaths.EnsureCreated();
        var identity = Encoding.UTF8.GetBytes($"{PreviewArtifactVersion}|{session.Fingerprint}|{entry.EntryId}|{entry.Path}|{entry.Offset}|{entry.StoredSize}");
        var key = Convert.ToHexString(SHA256.HashData(identity)).ToLowerInvariant();
        var extension = string.IsNullOrWhiteSpace(entry.Extension) ? ".bin" : entry.Extension;
        var destination = Path.Combine(ArchiveLiteDataPaths.PreviewCache, key + extension);
        if (!File.Exists(destination))
        {
            await AtomicFile.WriteAsync(
                destination,
                async (stream, token) => await stream.WriteAsync(bytes, token).ConfigureAwait(false),
                cancellationToken).ConfigureAwait(false);
        }
        return destination;
    }
}
