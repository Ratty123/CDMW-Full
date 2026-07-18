using System.Diagnostics;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Cdmw.ArchiveLite.Standalone;

internal static class StandaloneRuntime
{
    internal const string ReadyMarkerName = ".standalone-ready";
    private const long MaximumExpandedPayloadBytes = 2L * 1024 * 1024 * 1024;
    private const int MaximumPayloadEntries = 20_000;
    private static readonly UTF8Encoding Utf8WithoutBom = new(false);
    private static readonly string[] RequiredRuntimeFiles =
    {
        "CdmwArchiveLite.exe",
        "CdmwArchiveLite.Worker.exe",
        "cdmw-archive-core.dll",
        "PACKAGE-CONTENTS.json",
        "preview/cdmw-preview-core.exe",
        "indexer/cdmw-archive-accelerator.exe",
        "mesh/cdmw-mesh-core.exe",
        "renderer/cdmw-mesh-dotnet-editor.exe",
    };

    internal static string ResolveRuntimeRoot()
    {
        var testMode = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_TEST_MODE");
        var dataRoot = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DATA_ROOT");
        if (testMode == "1" && !string.IsNullOrWhiteSpace(dataRoot))
        {
            var resolvedDataRoot = Path.GetFullPath(dataRoot);
            if (!IsDriveRoot(resolvedDataRoot))
            {
                return Path.Combine(resolvedDataRoot, "standalone");
            }
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Ratrider",
            "CDMWArchiveLite",
            "standalone");
    }

    internal static async Task<string> EnsureExtractedAsync(
        Stream payload,
        string runtimeRoot,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(payload);
        if (!payload.CanRead || !payload.CanSeek)
        {
            throw new ArgumentException("The embedded standalone payload must be a readable, seekable stream.", nameof(payload));
        }

        var resolvedRoot = ResolveSafeRoot(runtimeRoot);
        var initialPosition = payload.Position;
        var payloadHashBytes = await SHA256.HashDataAsync(payload, cancellationToken).ConfigureAwait(false);
        payload.Position = initialPosition;
        var payloadHash = Convert.ToHexString(payloadHashBytes).ToLowerInvariant();
        var payloadRoot = Path.Combine(resolvedRoot, "payloads");
        var destination = Path.Combine(payloadRoot, payloadHash);
        Directory.CreateDirectory(payloadRoot);

        await using var extractionLock = await AcquireExtractionLockAsync(
            payloadRoot,
            payloadHash,
            cancellationToken).ConfigureAwait(false);
        if (IsReady(destination, payloadHash))
        {
            return destination;
        }

        QuarantineInvalidDestination(payloadRoot, destination);
        var staging = Path.Combine(
            payloadRoot,
            $".extracting-{payloadHash[..16]}-{Environment.ProcessId}-{Guid.NewGuid():N}");
        EnsureContainedDirectory(payloadRoot, staging);
        Directory.CreateDirectory(staging);
        try
        {
            await ExtractPayloadAsync(payload, staging, cancellationToken).ConfigureAwait(false);
            await ValidatePackageManifestAsync(staging, cancellationToken).ConfigureAwait(false);
            await File.WriteAllTextAsync(
                Path.Combine(staging, ReadyMarkerName),
                $"schema=1{Environment.NewLine}payload_sha256={payloadHash}{Environment.NewLine}",
                Utf8WithoutBom,
                cancellationToken).ConfigureAwait(false);
            Directory.Move(staging, destination);
        }
        catch
        {
            DeleteOwnedStagingDirectory(payloadRoot, staging);
            throw;
        }

        return destination;
    }

    private static async Task<FileStream> AcquireExtractionLockAsync(
        string payloadRoot,
        string payloadHash,
        CancellationToken cancellationToken)
    {
        var lockPath = Path.Combine(payloadRoot, $".lock-{payloadHash}");
        var started = Stopwatch.GetTimestamp();
        while (Stopwatch.GetElapsedTime(started) < TimeSpan.FromMinutes(3))
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                return new FileStream(
                    lockPath,
                    FileMode.OpenOrCreate,
                    FileAccess.ReadWrite,
                    FileShare.None,
                    bufferSize: 1,
                    options: FileOptions.Asynchronous);
            }
            catch (IOException)
            {
                await Task.Delay(100, cancellationToken).ConfigureAwait(false);
            }
        }
        throw new TimeoutException("Another Archive Lite launch did not finish preparing the standalone runtime.");
    }

    private static async Task ExtractPayloadAsync(Stream payload, string destination, CancellationToken cancellationToken)
    {
        using var archive = new ZipArchive(payload, ZipArchiveMode.Read, leaveOpen: true);
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaximumPayloadEntries)
        {
            throw new InvalidDataException("The standalone payload has an invalid entry count.");
        }

        var entries = archive.Entries.Select(CreateEntryDescriptor).ToArray();
        var files = entries.Where(entry => !entry.IsDirectory).ToArray();
        if (files.Length == 0)
        {
            throw new InvalidDataException("The standalone payload contains no files.");
        }

        var commonRoot = FindCommonRoot(files);
        long expandedBytes = 0;
        var destinations = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            expandedBytes = checked(expandedBytes + entry.Entry.Length);
            if (expandedBytes > MaximumExpandedPayloadBytes)
            {
                throw new InvalidDataException("The standalone payload exceeds the expanded-size limit.");
            }

            var logicalSegments = commonRoot is null ? entry.Segments : entry.Segments[1..];
            if (logicalSegments.Length == 0)
            {
                throw new InvalidDataException($"Payload entry has no file name: {entry.Entry.FullName}");
            }
            var outputPath = ResolveContainedFile(destination, logicalSegments);
            if (!destinations.Add(outputPath))
            {
                throw new InvalidDataException($"Payload contains duplicate output path: {entry.Entry.FullName}");
            }

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            await using var input = entry.Entry.Open();
            await using var output = new FileStream(
                outputPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                bufferSize: 128 * 1024,
                options: FileOptions.Asynchronous | FileOptions.SequentialScan);
            await input.CopyToAsync(output, 128 * 1024, cancellationToken).ConfigureAwait(false);
            await output.FlushAsync(cancellationToken).ConfigureAwait(false);
            if (output.Length != entry.Entry.Length)
            {
                throw new InvalidDataException($"Payload entry length changed during extraction: {entry.Entry.FullName}");
            }
        }
    }

    private static EntryDescriptor CreateEntryDescriptor(ZipArchiveEntry entry)
    {
        var normalized = entry.FullName.Replace('\\', '/');
        if (string.IsNullOrWhiteSpace(normalized) || normalized.StartsWith("/", StringComparison.Ordinal))
        {
            throw new InvalidDataException($"Payload entry has an unsafe path: {entry.FullName}");
        }

        var isDirectory = normalized.EndsWith("/", StringComparison.Ordinal);
        var segments = normalized.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Length == 0 || segments.Any(segment => !IsSafeSegment(segment)))
        {
            throw new InvalidDataException($"Payload entry has an unsafe path: {entry.FullName}");
        }
        return new EntryDescriptor(entry, segments, isDirectory);
    }

    private static bool IsSafeSegment(string segment)
    {
        if (segment is "." or ".." ||
            segment.EndsWith(' ') ||
            segment.EndsWith('.') ||
            segment.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
        {
            return false;
        }

        var baseName = segment.Split('.')[0];
        return !baseName.Equals("CON", StringComparison.OrdinalIgnoreCase) &&
               !baseName.Equals("PRN", StringComparison.OrdinalIgnoreCase) &&
               !baseName.Equals("AUX", StringComparison.OrdinalIgnoreCase) &&
               !baseName.Equals("NUL", StringComparison.OrdinalIgnoreCase) &&
               !(baseName.Length == 4 &&
                 (baseName.StartsWith("COM", StringComparison.OrdinalIgnoreCase) ||
                  baseName.StartsWith("LPT", StringComparison.OrdinalIgnoreCase)) &&
                 baseName[3] is >= '1' and <= '9');
    }

    private static string? FindCommonRoot(IReadOnlyList<EntryDescriptor> entries)
    {
        var candidate = entries[0].Segments[0];
        return entries.All(entry =>
            entry.Segments.Length > 1 &&
            entry.Segments[0].Equals(candidate, StringComparison.OrdinalIgnoreCase))
            ? candidate
            : null;
    }

    private static async Task ValidatePackageManifestAsync(string destination, CancellationToken cancellationToken)
    {
        var manifestPath = Path.Combine(destination, "PACKAGE-CONTENTS.json");
        if (!File.Exists(manifestPath))
        {
            throw new InvalidDataException("The extracted payload is missing PACKAGE-CONTENTS.json.");
        }

        await using var manifestStream = File.OpenRead(manifestPath);
        using var manifest = await JsonDocument.ParseAsync(manifestStream, cancellationToken: cancellationToken).ConfigureAwait(false);
        if (manifest.RootElement.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("PACKAGE-CONTENTS.json must contain an array.");
        }

        var validatedPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in manifest.RootElement.EnumerateArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!item.TryGetProperty("path", out var pathProperty) ||
                !item.TryGetProperty("bytes", out var bytesProperty) ||
                !item.TryGetProperty("sha256", out var hashProperty))
            {
                throw new InvalidDataException("PACKAGE-CONTENTS.json contains an incomplete entry.");
            }

            var relativePath = pathProperty.GetString();
            var expectedHash = hashProperty.GetString();
            if (string.IsNullOrWhiteSpace(relativePath) ||
                string.IsNullOrWhiteSpace(expectedHash) ||
                !bytesProperty.TryGetInt64(out var expectedBytes) ||
                expectedBytes < 0)
            {
                throw new InvalidDataException("PACKAGE-CONTENTS.json contains invalid values.");
            }

            var segments = relativePath.Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries);
            if (segments.Length == 0 || segments.Any(segment => !IsSafeSegment(segment)))
            {
                throw new InvalidDataException($"Package manifest contains an unsafe path: {relativePath}");
            }
            var filePath = ResolveContainedFile(destination, segments);
            if (!validatedPaths.Add(filePath) || !File.Exists(filePath))
            {
                throw new InvalidDataException($"Package manifest entry is missing or duplicated: {relativePath}");
            }

            var fileInfo = new FileInfo(filePath);
            if (fileInfo.Length != expectedBytes)
            {
                throw new InvalidDataException($"Package file length does not match its manifest: {relativePath}");
            }
            await using var file = fileInfo.OpenRead();
            var actualHash = Convert.ToHexString(
                await SHA256.HashDataAsync(file, cancellationToken).ConfigureAwait(false));
            if (!actualHash.Equals(expectedHash, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException($"Package file hash does not match its manifest: {relativePath}");
            }
        }

        foreach (var requiredFile in RequiredRuntimeFiles)
        {
            var requiredPath = ResolveContainedFile(
                destination,
                requiredFile.Split('/', StringSplitOptions.RemoveEmptyEntries));
            if (!File.Exists(requiredPath))
            {
                throw new InvalidDataException($"The extracted runtime is missing {requiredFile}.");
            }
        }
    }

    private static bool IsReady(string destination, string payloadHash)
    {
        if (!Directory.Exists(destination))
        {
            return false;
        }

        var markerPath = Path.Combine(destination, ReadyMarkerName);
        try
        {
            var marker = File.ReadAllText(markerPath);
            if (!marker.Contains($"payload_sha256={payloadHash}", StringComparison.Ordinal))
            {
                return false;
            }
            return RequiredRuntimeFiles.All(relativePath => File.Exists(
                ResolveContainedFile(destination, relativePath.Split('/', StringSplitOptions.RemoveEmptyEntries))));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static string ResolveSafeRoot(string runtimeRoot)
    {
        if (string.IsNullOrWhiteSpace(runtimeRoot))
        {
            throw new ArgumentException("Standalone runtime root cannot be empty.", nameof(runtimeRoot));
        }
        var resolved = Path.GetFullPath(runtimeRoot);
        if (IsDriveRoot(resolved))
        {
            throw new InvalidOperationException("Refusing to use a drive root for the standalone runtime.");
        }
        return resolved;
    }

    private static bool IsDriveRoot(string path) =>
        path.Equals(Path.GetPathRoot(path), StringComparison.OrdinalIgnoreCase);

    private static string ResolveContainedFile(string root, IReadOnlyList<string> segments)
    {
        var resolvedRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var combined = segments.Aggregate(resolvedRoot, Path.Combine);
        var resolved = Path.GetFullPath(combined);
        var prefix = resolvedRoot + Path.DirectorySeparatorChar;
        if (!resolved.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Payload path escapes the standalone runtime.");
        }
        return resolved;
    }

    private static void EnsureContainedDirectory(string root, string path)
    {
        var resolvedRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var resolvedPath = Path.GetFullPath(path);
        if (!resolvedPath.StartsWith(resolvedRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Standalone extraction path escapes its app-owned root.");
        }
    }

    private static void QuarantineInvalidDestination(string payloadRoot, string destination)
    {
        EnsureContainedDirectory(payloadRoot, destination);
        if (!Directory.Exists(destination) && !File.Exists(destination))
        {
            return;
        }

        var quarantine = destination + $".invalid-{DateTimeOffset.UtcNow:yyyyMMddHHmmss}-{Guid.NewGuid():N}";
        EnsureContainedDirectory(payloadRoot, quarantine);
        if (Directory.Exists(destination))
        {
            Directory.Move(destination, quarantine);
        }
        else
        {
            File.Move(destination, quarantine);
        }
    }

    private static void DeleteOwnedStagingDirectory(string payloadRoot, string staging)
    {
        try
        {
            EnsureContainedDirectory(payloadRoot, staging);
            if (Directory.Exists(staging))
            {
                Directory.Delete(staging, recursive: true);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A failed extraction is never published; OS cleanup can reclaim an unremovable staging directory.
        }
    }

    private sealed record EntryDescriptor(ZipArchiveEntry Entry, string[] Segments, bool IsDirectory);
}
