using System.Security.Cryptography;
using System.Text;

namespace Cdmw.ArchiveLite.Core;

public sealed class TextDocumentPreviewService
{
    public const long MaximumDocumentBytes = 64L * 1024L * 1024L;
    private const string ArtifactVersion = "text_document_v1";

    public async Task<TextDocumentArtifact> PublishAsync(
        string identity,
        string displayPath,
        byte[] bytes,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(identity);
        ArgumentException.ThrowIfNullOrWhiteSpace(displayPath);
        ArgumentNullException.ThrowIfNull(bytes);
        if (bytes.LongLength > MaximumDocumentBytes)
        {
            throw new InvalidDataException($"Text document exceeds the {MaximumDocumentBytes / (1024 * 1024)} MiB preview limit.");
        }

        cancellationToken.ThrowIfCancellationRequested();
        var contentHash = Convert.ToHexString(SHA256.HashData(bytes));
        var keyBytes = Encoding.UTF8.GetBytes($"{ArtifactVersion}|{identity}|{contentHash}");
        var key = Convert.ToHexString(SHA256.HashData(keyBytes)).ToLowerInvariant();
        ArchiveLiteDataPaths.EnsureCreated();
        var textRoot = Path.Combine(ArchiveLiteDataPaths.PreviewCache, "text");
        Directory.CreateDirectory(textRoot);
        var destination = Path.Combine(textRoot, key + ".txt");
        if (!File.Exists(destination))
        {
            var text = TextDecoding.Decode(bytes);
            await AtomicFile.WriteAsync(
                destination,
                async (stream, token) =>
                {
                    await using var writer = new StreamWriter(
                        stream,
                        new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                        128 * 1024,
                        leaveOpen: true);
                    await writer.WriteAsync(text.AsMemory(), token).ConfigureAwait(false);
                    await writer.FlushAsync(token).ConfigureAwait(false);
                },
                cancellationToken).ConfigureAwait(false);
        }
        return new TextDocumentArtifact(destination, SyntaxForPath(displayPath));
    }

    public static string SyntaxForPath(string path)
    {
        var extension = Path.GetExtension(path).ToLowerInvariant();
        return extension switch
        {
            ".pac_xml" or ".pam_xml" or ".pamlod_xml" or ".prefabdata_xml" or ".app_xml" => ".xml",
            ".material" or ".shader" => ".hlsl",
            ".cfg" or ".ini" => ".ini",
            ".yml" => ".yaml",
            _ => extension,
        };
    }
}

public sealed record TextDocumentArtifact(string Path, string Syntax);
