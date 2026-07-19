using System.Security.Cryptography;
using System.Text;
using Cdmw.Archive.Content;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveContentPreviewService
{
    private const string ArtifactVersion = "archive_content_v1";
    private readonly ArchiveContentAnalyzer _analyzer = new(64 * 1024 * 1024);

    public async Task<ArchiveContentPreviewArtifact> BuildAsync(
        string sessionFingerprint,
        ArchiveEntryDto entry,
        byte[] bytes,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionFingerprint);
        ArgumentNullException.ThrowIfNull(entry);
        ArgumentNullException.ThrowIfNull(bytes);
        cancellationToken.ThrowIfCancellationRequested();

        var document = _analyzer.Analyze(entry.Extension, entry.Path, bytes, entry.OriginalSize);
        var identity = Encoding.UTF8.GetBytes(
            $"{ArtifactVersion}|{sessionFingerprint}|{entry.EntryId}|{entry.Path}|{entry.Offset}|{entry.StoredSize}");
        var key = Convert.ToHexString(SHA256.HashData(identity)).ToLowerInvariant();
        ArchiveLiteDataPaths.EnsureCreated();
        var destination = Path.Combine(ArchiveLiteDataPaths.ContentAnalysisCache, key + ".json");
        if (!File.Exists(destination))
        {
            var json = ArchiveContentJson.Serialize(document);
            await AtomicFile.WriteAsync(
                destination,
                async (stream, token) =>
                {
                    var content = Encoding.UTF8.GetBytes(json);
                    await stream.WriteAsync(content, token).ConfigureAwait(false);
                },
                cancellationToken).ConfigureAwait(false);
        }
        return new ArchiveContentPreviewArtifact(document, destination);
    }
}

public sealed record ArchiveContentPreviewArtifact(
    ArchiveContentDocument Document,
    string JsonPath);
