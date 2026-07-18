using System.Security.Cryptography;
using System.Text;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchivePreviewService(ArchiveSessionManager sessions, NativeArchiveCore native)
{
    private const long MaximumPreviewBytes = 64L * 1024L * 1024L;
    private const string PreviewArtifactVersion = "preview_v2_pathc";

    public Task<PreviewResult> BuildAsync(PreviewRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        return Task.Run(
            async () => await BuildCoreAsync(session, request, cancellationToken).ConfigureAwait(false),
            cancellationToken);
    }

    private async Task<PreviewResult> BuildCoreAsync(
        ArchiveSession session,
        PreviewRequest request,
        CancellationToken cancellationToken)
    {
        var entry = session.Index.ReadEntry(request.EntryId);
        var metadata = BuildMetadata(entry);
        if (entry.OriginalSize > MaximumPreviewBytes)
        {
            return new PreviewResult(
                session.Id,
                entry.EntryId,
                PreviewKind.Metadata,
                entry.Name,
                metadata,
                Warnings: [$"Preview was not decoded because the entry exceeds {MaximumPreviewBytes / (1024 * 1024)} MiB."]);
        }
        cancellationToken.ThrowIfCancellationRequested();
        var decoded = native.Decode(entry);
        cancellationToken.ThrowIfCancellationRequested();
        var warnings = new List<string>();
        if (!string.IsNullOrWhiteSpace(decoded.Note)) warnings.Add(decoded.Note);

        if (entry.Role is ArchiveEntryRole.Text or ArchiveEntryRole.Metadata || LooksTextual(decoded.Bytes))
        {
            var text = TextDecoding.Decode(decoded.Bytes);
            var characterLimit = Math.Clamp(request.TextCharacterLimit, 1_000, 120_000);
            if (text.Length > characterLimit)
            {
                text = text[..characterLimit];
                warnings.Add($"Text preview is limited to {characterLimit:N0} characters.");
            }
            return new PreviewResult(session.Id, entry.EntryId, PreviewKind.Text, entry.Name, metadata, text, Warnings: warnings);
        }

        if (entry.Role is ArchiveEntryRole.Image or ArchiveEntryRole.Normal or ArchiveEntryRole.Material or ArchiveEntryRole.UserInterface or ArchiveEntryRole.Impostor)
        {
            var artifact = await PublishArtifactAsync(session, entry, decoded.Bytes, cancellationToken).ConfigureAwait(false);
            return new PreviewResult(session.Id, entry.EntryId, PreviewKind.Image, entry.Name, metadata, ArtifactPath: artifact, Warnings: warnings);
        }

        if (entry.Role is ArchiveEntryRole.Audio or ArchiveEntryRole.Video)
        {
            if (entry.Extension is not (".mp3" or ".mp4" or ".wav"))
            {
                warnings.Add($"Direct playback for {entry.Extension} is not available through Windows Media Foundation in Archive Lite.");
                return new PreviewResult(
                    session.Id,
                    entry.EntryId,
                    PreviewKind.Hex,
                    entry.Name,
                    metadata,
                    BuildHex(decoded.Bytes, request.BinaryByteLimit),
                    Warnings: warnings);
            }
            var artifact = await PublishArtifactAsync(session, entry, decoded.Bytes, cancellationToken).ConfigureAwait(false);
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
