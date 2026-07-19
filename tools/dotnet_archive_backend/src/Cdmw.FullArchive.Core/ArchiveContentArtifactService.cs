using System.Text;
using Cdmw.Archive.Content;

namespace Cdmw.FullArchive.Core;

internal sealed class ArchiveContentArtifactService
{
    private const string ArtifactSuffix = ".content-v1";
    private readonly ArchiveContentAnalyzer _analyzer = new(64 * 1024 * 1024);

    public async Task<ArchiveContentArtifact> BuildFromFileAsync(
        string preparedPath,
        string extension,
        string virtualPath,
        CancellationToken cancellationToken)
    {
        var paths = Paths(preparedPath);
        if (File.Exists(paths.JsonPath) && File.Exists(paths.TextPath)) return paths;
        var document = await _analyzer.AnalyzeFileAsync(
            preparedPath,
            extension,
            virtualPath,
            cancellationToken).ConfigureAwait(false);
        await PublishAsync(document, paths, cancellationToken).ConfigureAwait(false);
        return paths;
    }

    public async Task<ArchiveContentArtifact> BuildFromBytesAsync(
        string preparedPath,
        string extension,
        string virtualPath,
        byte[] bytes,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        var paths = Paths(preparedPath);
        if (File.Exists(paths.JsonPath) && File.Exists(paths.TextPath)) return paths;
        cancellationToken.ThrowIfCancellationRequested();
        var document = _analyzer.Analyze(extension, virtualPath, bytes, bytes.LongLength);
        await PublishAsync(document, paths, cancellationToken).ConfigureAwait(false);
        return paths;
    }

    private static ArchiveContentArtifact Paths(string preparedPath) => new(
        preparedPath + ArtifactSuffix + ".json",
        preparedPath + ArtifactSuffix + ".txt",
        ArchiveContentAnalyzer.AnalyzerVersion);

    private static async Task PublishAsync(
        ArchiveContentDocument document,
        ArchiveContentArtifact paths,
        CancellationToken cancellationToken)
    {
        await PublishFileAsync(
            paths.JsonPath,
            ArchiveContentJson.Serialize(document),
            cancellationToken).ConfigureAwait(false);
        await PublishFileAsync(
            paths.TextPath,
            document.ToReadableText(),
            cancellationToken).ConfigureAwait(false);
    }

    private static async Task PublishFileAsync(
        string destination,
        string text,
        CancellationToken cancellationToken)
    {
        var directory = Path.GetDirectoryName(destination)
            ?? throw new InvalidDataException("Content-analysis artifact has no parent directory.");
        Directory.CreateDirectory(directory);
        var staging = Path.Combine(directory, $".{Path.GetFileName(destination)}.{Guid.NewGuid():N}.tmp");
        try
        {
            await File.WriteAllTextAsync(staging, text, new UTF8Encoding(false), cancellationToken)
                .ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            File.Move(staging, destination, overwrite: true);
        }
        finally
        {
            TryDelete(staging);
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (IOException)
        {
            // A later cache cleanup can remove a locked staging file.
        }
        catch (UnauthorizedAccessException)
        {
            // Preserve the primary operation result.
        }
    }
}

internal sealed record ArchiveContentArtifact(
    string JsonPath,
    string TextPath,
    string Version);
