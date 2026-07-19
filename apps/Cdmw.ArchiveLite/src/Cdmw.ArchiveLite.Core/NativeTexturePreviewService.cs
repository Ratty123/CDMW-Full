using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class NativeTexturePreviewService
{
    private const string ArtifactVersion = "directxtex_preview_v2";
    private static readonly TimeSpan DecodeTimeout = TimeSpan.FromSeconds(45);
    private static readonly byte[] PngSignature = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _decodeGates = new(StringComparer.Ordinal);

    public async Task<string> BuildAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        string ddsPath,
        CancellationToken cancellationToken)
        => await BuildCoreAsync(session, entry, ddsPath, 4096, "textures", cancellationToken).ConfigureAwait(false);

    public async Task<string> BuildThumbnailAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        string ddsPath,
        int maximumDimension,
        CancellationToken cancellationToken)
        => await BuildCoreAsync(session, entry, ddsPath, maximumDimension, "item-icons", cancellationToken).ConfigureAwait(false);

    public string? TryGetCachedThumbnail(
        ArchiveSession session,
        ArchiveEntryDto entry,
        int maximumDimension)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(entry);
        ValidateMaximumDimension(maximumDimension);
        var destination = ResolveDestination(session, entry, maximumDimension, "item-icons");
        return IsPng(destination) ? destination : null;
    }

    private async Task<string> BuildCoreAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        string ddsPath,
        int maximumDimension,
        string cacheNamespace,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(entry);
        ArgumentException.ThrowIfNullOrWhiteSpace(ddsPath);
        if (!entry.Extension.Equals(".dds", StringComparison.OrdinalIgnoreCase))
        {
            throw new NotSupportedException($"DirectXTex preview does not support {entry.Extension}.");
        }
        ValidateMaximumDimension(maximumDimension);

        ArchiveLiteDataPaths.EnsureCreated();
        var destination = ResolveDestination(session, entry, maximumDimension, cacheNamespace);
        var key = Path.GetFileNameWithoutExtension(destination);
        var textureRoot = Path.GetDirectoryName(destination)!;
        Directory.CreateDirectory(textureRoot);
        if (IsPng(destination))
        {
            return destination;
        }

        var gate = _decodeGates.GetOrAdd(key, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (IsPng(destination))
            {
                return destination;
            }

            var staging = Path.Combine(textureRoot, $".{key}.{Guid.NewGuid():N}.staging");
            Directory.CreateDirectory(staging);
            try
            {
                var outputPath = Path.Combine(staging, "preview.png");
                var jobPath = Path.Combine(staging, "job.json");
                var reportPath = Path.Combine(staging, "report.json");
                await AtomicFile.WriteAsync(
                    jobPath,
                    async (stream, token) => await JsonSerializer.SerializeAsync(
                        stream,
                        new
                        {
                            version = 2,
                            backend = "directxtex_native_0.2",
                            jobs = new[]
                            {
                                new
                                {
                                    input = Path.GetFullPath(ddsPath),
                                    output = outputPath,
                                    slot = entry.Role == ArchiveEntryRole.Normal ? "normal" : "base",
                                    normal_space = "auto",
                                    max_dimension = maximumDimension,
                                    requested_mip = 0,
                                    output_pixel_type = "rgba8",
                                },
                            },
                        },
                        WorkerProtocol.JsonOptions,
                        token).ConfigureAwait(false),
                    cancellationToken).ConfigureAwait(false);
                await RunDecoderAsync(jobPath, reportPath, cancellationToken).ConfigureAwait(false);
                ValidateReport(reportPath, outputPath);
                try
                {
                    File.Move(outputPath, destination, overwrite: true);
                }
                catch (IOException) when (IsPng(destination))
                {
                    // Another immutable decode won the publication race.
                }
                if (!IsPng(destination))
                {
                    throw new InvalidDataException("DirectXTex did not publish a valid PNG preview.");
                }
                return destination;
            }
            finally
            {
                try
                {
                    if (Directory.Exists(staging))
                    {
                        Directory.Delete(staging, recursive: true);
                    }
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    // A later bounded preview-cache prune can remove locked staging output.
                }
            }
        }
        finally
        {
            gate.Release();
        }
    }

    private static string ResolveDestination(
        ArchiveSession session,
        ArchiveEntryDto entry,
        int maximumDimension,
        string cacheNamespace)
    {
        var identity = Encoding.UTF8.GetBytes(string.Join(
            '|',
            ArtifactVersion,
            maximumDimension,
            session.Fingerprint,
            entry.EntryId,
            entry.Path,
            entry.Offset,
            entry.StoredSize,
            entry.OriginalSize));
        var key = Convert.ToHexString(SHA256.HashData(identity)).ToLowerInvariant();
        return Path.Combine(ArchiveLiteDataPaths.PreviewCache, cacheNamespace, key + ".png");
    }

    private static void ValidateMaximumDimension(int maximumDimension)
    {
        if (maximumDimension is < 32 or > 4096)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumDimension), "Texture preview size must be between 32 and 4096 pixels.");
        }
    }

    private static async Task RunDecoderAsync(
        string jobPath,
        string reportPath,
        CancellationToken cancellationToken)
    {
        var executable = ResolveDecoderPath();
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(executable) ?? AppContext.BaseDirectory,
        };
        startInfo.ArgumentList.Add("batch-preview-json");
        startInfo.ArgumentList.Add(jobPath);
        startInfo.ArgumentList.Add(reportPath);
        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("cd-texture-dx could not be started.");
        var stdout = ReadBoundedAsync(process.StandardOutput, cancellationToken);
        var stderr = ReadBoundedAsync(process.StandardError, cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(DecodeTimeout);
        try
        {
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            StopProcess(process);
            await ObserveAsync(stdout, stderr).ConfigureAwait(false);
            throw new TimeoutException($"cd-texture-dx did not finish within {DecodeTimeout.TotalSeconds:N0} seconds.");
        }
        catch (OperationCanceledException)
        {
            StopProcess(process);
            await ObserveAsync(stdout, stderr).ConfigureAwait(false);
            throw;
        }

        var stdoutText = await stdout.ConfigureAwait(false);
        var stderrText = await stderr.ConfigureAwait(false);
        if (process.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(stderrText) ? stdoutText : stderrText;
            throw new InvalidDataException($"cd-texture-dx exited with code {process.ExitCode}: {detail.Trim()}");
        }
    }

    private static void ValidateReport(string reportPath, string expectedOutput)
    {
        if (!File.Exists(reportPath))
        {
            throw new InvalidDataException("cd-texture-dx did not produce a decode report.");
        }
        using var document = JsonDocument.Parse(File.ReadAllText(reportPath));
        var root = document.RootElement;
        if (!root.TryGetProperty("status", out var status)
            || !string.Equals(status.GetString(), "ok", StringComparison.OrdinalIgnoreCase)
            || !root.TryGetProperty("items", out var items)
            || items.ValueKind != JsonValueKind.Array
            || items.GetArrayLength() != 1)
        {
            throw new InvalidDataException("cd-texture-dx returned an invalid decode report.");
        }
        var item = items[0];
        var itemStatus = item.TryGetProperty("status", out var itemStatusValue) ? itemStatusValue.GetString() : null;
        var output = item.TryGetProperty("output_path", out var outputValue) ? outputValue.GetString() : null;
        if (!string.Equals(itemStatus, "decoded", StringComparison.OrdinalIgnoreCase)
            || string.IsNullOrWhiteSpace(output)
            || !Path.GetFullPath(output).Equals(Path.GetFullPath(expectedOutput), StringComparison.OrdinalIgnoreCase)
            || !IsPng(expectedOutput))
        {
            var message = item.TryGetProperty("message", out var messageValue) ? messageValue.GetString() : null;
            throw new InvalidDataException(message ?? "DirectXTex could not decode the selected DDS.");
        }
    }

    private static string ResolveDecoderPath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
        {
            return Path.GetFullPath(overridePath);
        }
        var packaged = Path.Combine(AppContext.BaseDirectory, "texture", "cd-texture-dx.exe");
        if (File.Exists(packaged))
        {
            return packaged;
        }
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            foreach (var configuration in new[] { "Release", "Debug" })
            {
                var candidate = Path.Combine(current.FullName, "native", "cd_texture_dx", "build", configuration, "cd-texture-dx.exe");
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
        }
        throw new FileNotFoundException(
            "cd-texture-dx.exe was not found. Rebuild Archive Lite or set CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH.");
    }

    private static bool IsPng(string path)
    {
        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
            Span<byte> signature = stackalloc byte[PngSignature.Length];
            return stream.Read(signature) == signature.Length && signature.SequenceEqual(PngSignature);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static async Task<string> ReadBoundedAsync(StreamReader reader, CancellationToken cancellationToken)
    {
        const int maximumCharacters = 64 * 1024;
        var output = new StringBuilder();
        var buffer = new char[4096];
        while (true)
        {
            var count = await reader.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
            if (count == 0)
            {
                break;
            }
            if (output.Length < maximumCharacters)
            {
                output.Append(buffer, 0, Math.Min(count, maximumCharacters - output.Length));
            }
        }
        return output.ToString();
    }

    private static async Task ObserveAsync(params Task<string>[] captures)
    {
        foreach (var capture in captures)
        {
            try
            {
                _ = await capture.ConfigureAwait(false);
            }
            catch
            {
                // The owned process is already stopping; observe reader completion only.
            }
        }
    }

    private static void StopProcess(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            // Preserve the cancellation or timeout that owns teardown.
        }
    }
}
