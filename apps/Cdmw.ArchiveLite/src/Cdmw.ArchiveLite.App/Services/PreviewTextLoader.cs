using System.Text;

namespace Cdmw.ArchiveLite.App.Services;

internal static class PreviewTextLoader
{
    private const long MaximumPreviewBytes = 64L * 1024L * 1024L;

    public static async Task<string> LoadAsync(string path, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var fullPath = Path.GetFullPath(path);
        var info = new FileInfo(fullPath);
        if (!info.Exists)
        {
            throw new FileNotFoundException("The prepared text preview is missing.", fullPath);
        }
        if (info.Length > MaximumPreviewBytes)
        {
            throw new InvalidDataException("The prepared text preview exceeds the 64 MiB display limit.");
        }

        await using var stream = new FileStream(
            fullPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read | FileShare.Delete,
            128 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        using var reader = new StreamReader(
            stream,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true),
            detectEncodingFromByteOrderMarks: true,
            128 * 1024,
            leaveOpen: false);
        return await reader.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
    }
}
