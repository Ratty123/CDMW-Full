using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class NativeMediaPreviewService
{
    private const string ArtifactVersion = "vgmstream_preview_v1";
    private static readonly TimeSpan DecodeTimeout = TimeSpan.FromSeconds(90);
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _decodeGates = new(StringComparer.Ordinal);

    public static bool Supports(string extension) => extension.Equals(".wem", StringComparison.OrdinalIgnoreCase);

    public async Task<string> BuildAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        string sourcePath,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(entry);
        ArgumentException.ThrowIfNullOrWhiteSpace(sourcePath);
        if (!Supports(entry.Extension))
        {
            throw new NotSupportedException($"vgmstream preview does not support {entry.Extension}.");
        }

        ArchiveLiteDataPaths.EnsureCreated();
        var identity = Encoding.UTF8.GetBytes(string.Join(
            '|',
            ArtifactVersion,
            session.Fingerprint,
            entry.EntryId,
            entry.Path,
            entry.Offset,
            entry.StoredSize,
            entry.OriginalSize));
        var key = Convert.ToHexString(SHA256.HashData(identity)).ToLowerInvariant();
        var mediaRoot = Path.Combine(ArchiveLiteDataPaths.PreviewCache, "media");
        Directory.CreateDirectory(mediaRoot);
        var destination = Path.Combine(mediaRoot, key + ".wav");
        if (IsWave(destination))
        {
            return destination;
        }

        var gate = _decodeGates.GetOrAdd(key, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (IsWave(destination))
            {
                return destination;
            }
            var staging = Path.Combine(mediaRoot, $".{key}.{Guid.NewGuid():N}.staging.wav");
            try
            {
                await RunDecoderAsync(sourcePath, staging, cancellationToken).ConfigureAwait(false);
                if (!IsWave(staging))
                {
                    throw new InvalidDataException("vgmstream did not produce a valid WAV preview.");
                }
                File.Move(staging, destination, overwrite: true);
                return destination;
            }
            finally
            {
                try
                {
                    File.Delete(staging);
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    // A later cache cleanup can remove a locked staging file.
                }
            }
        }
        finally
        {
            gate.Release();
        }
    }

    private static async Task RunDecoderAsync(
        string sourcePath,
        string outputPath,
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
        startInfo.ArgumentList.Add("-o");
        startInfo.ArgumentList.Add(outputPath);
        startInfo.ArgumentList.Add(Path.GetFullPath(sourcePath));
        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("vgmstream-cli could not be started.");
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
            throw new TimeoutException($"vgmstream-cli did not finish within {DecodeTimeout.TotalSeconds:N0} seconds.");
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
            throw new InvalidDataException($"vgmstream-cli exited with code {process.ExitCode}: {detail.Trim()}");
        }
    }

    private static string ResolveDecoderPath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_VGMSTREAM_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
        {
            return Path.GetFullPath(overridePath);
        }
        var packaged = Path.Combine(AppContext.BaseDirectory, "media", "vgmstream-cli.exe");
        if (File.Exists(packaged))
        {
            return packaged;
        }
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            var candidate = Path.Combine(current.FullName, ".tools", "vgmstream", "vgmstream-cli.exe");
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }
        throw new FileNotFoundException(
            "vgmstream-cli.exe was not found. Rebuild Archive Lite or set CDMW_ARCHIVE_LITE_VGMSTREAM_PATH.");
    }

    private static bool IsWave(string path)
    {
        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
            Span<byte> header = stackalloc byte[12];
            return stream.Length > 44
                && stream.Read(header) == header.Length
                && header[..4].SequenceEqual("RIFF"u8)
                && header[8..].SequenceEqual("WAVE"u8);
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
