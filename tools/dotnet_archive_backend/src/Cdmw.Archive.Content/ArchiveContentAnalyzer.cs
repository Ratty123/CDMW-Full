namespace Cdmw.Archive.Content;

public sealed class ArchiveContentAnalyzer
{
    public const string AnalyzerVersion = "cdmw-archive-content/1";
    public const int DefaultMaximumAnalysisBytes = 8 * 1024 * 1024;

    private readonly int _maximumAnalysisBytes;

    public ArchiveContentAnalyzer(int maximumAnalysisBytes = DefaultMaximumAnalysisBytes)
    {
        if (maximumAnalysisBytes is < 4096 or > 64 * 1024 * 1024)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumAnalysisBytes));
        }
        _maximumAnalysisBytes = maximumAnalysisBytes;
    }

    public ArchiveContentDocument Analyze(
        string extension,
        string virtualPath,
        ReadOnlyMemory<byte> payload,
        long? sourceLength = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(virtualPath);
        var capability = ArchiveContentRegistry.Describe(extension);
        var boundedLength = Math.Min(payload.Length, _maximumAnalysisBytes);
        var data = payload[..boundedLength];
        var totalLength = sourceLength ?? payload.Length;
        var truncated = totalLength > boundedLength;

        try
        {
            return capability.Analyzer switch
            {
                "text" or "text_model" or "obj" or "json" or "xml" or "material_text" =>
                    ArchiveStructuredAnalyzers.AnalyzeText(capability, virtualPath, data, totalLength, truncated),
                "pat" => ArchivePatAnalyzer.Analyze(capability, virtualPath, data, totalLength, truncated),
                "dds" => ArchiveStructuredAnalyzers.AnalyzeDds(capability, virtualPath, data, totalLength, truncated),
                "bnk" => ArchiveStructuredAnalyzers.AnalyzeBnk(capability, virtualPath, data, totalLength, truncated),
                "meshinfo" => ArchiveStructuredAnalyzers.AnalyzeMeshInfo(capability, virtualPath, data, totalLength, truncated),
                "media" or "wem" or "image" =>
                    ArchiveStructuredAnalyzers.AnalyzeMedia(capability, virtualPath, data, totalLength, truncated),
                "hkx" => ArchiveStructuredAnalyzers.AnalyzeHkx(capability, virtualPath, data, totalLength, truncated),
                "pab" => ArchiveStructuredAnalyzers.AnalyzePab(capability, virtualPath, data, totalLength, truncated),
                "pathc" => ArchiveStructuredAnalyzers.AnalyzePathc(capability, virtualPath, data, totalLength, truncated),
                _ when capability.Structured =>
                    ArchiveStructuredAnalyzers.AnalyzeStructured(capability, virtualPath, data, totalLength, truncated),
                _ => ArchiveStructuredAnalyzers.AnalyzeGeneric(capability, virtualPath, data, totalLength, truncated),
            };
        }
        catch (Exception exception) when (exception is InvalidDataException or OverflowException or ArgumentException)
        {
            var fallback = ArchiveStructuredAnalyzers.AnalyzeGeneric(
                capability,
                virtualPath,
                data,
                totalLength,
                truncated);
            return fallback with
            {
                Title = $"{capability.Extension} safe fallback analysis",
                Warnings = [.. fallback.Warnings, $"Format-specific analysis stopped safely: {exception.Message}"],
            };
        }
    }

    public async Task<ArchiveContentDocument> AnalyzeFileAsync(
        string path,
        string? extension = null,
        string? virtualPath = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 64 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        var length = stream.Length;
        var readLength = checked((int)Math.Min(length, _maximumAnalysisBytes));
        var payload = new byte[readLength];
        var offset = 0;
        while (offset < payload.Length)
        {
            var read = await stream.ReadAsync(payload.AsMemory(offset), cancellationToken).ConfigureAwait(false);
            if (read == 0) break;
            offset += read;
        }
        return Analyze(
            extension ?? Path.GetExtension(path),
            virtualPath ?? path,
            payload.AsMemory(0, offset),
            length);
    }
}
