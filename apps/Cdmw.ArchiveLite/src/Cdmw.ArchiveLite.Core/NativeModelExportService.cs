using System.Buffers.Binary;
using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;
using static Cdmw.ArchiveLite.Core.NativePreviewGeometryIO;

namespace Cdmw.ArchiveLite.Core;

public sealed class NativeModelExportService(NativeModelPreviewService previews)
{
    private static readonly TimeSpan NativeExportTimeout = TimeSpan.FromMinutes(5);
    private static readonly JsonSerializerOptions CompactJson = new() { WriteIndented = false };

    public static bool SupportsFormat(ExportKind kind) => kind is ExportKind.Obj or ExportKind.Fbx or ExportKind.Glb;

    public static string FileExtension(ExportKind kind) => kind switch
    {
        ExportKind.Obj => ".obj",
        ExportKind.Fbx => ".fbx",
        ExportKind.Glb => ".glb",
        _ => throw new NotSupportedException($"{kind} is not a mesh interchange format."),
    };

    public async Task ExportAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        ExportKind kind,
        string destination,
        bool overwrite,
        Func<ProgressUpdate, Task>? progress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(entry);
        if (!NativeModelPreviewService.Supports(entry.Extension))
        {
            throw new NotSupportedException($"Mesh interchange export does not support {entry.Extension} files.");
        }

        var packageRoot = await previews.BuildAsync(session, entry, progress, cancellationToken).ConfigureAwait(false);
        await ExportPackageAsync(
            packageRoot,
            entry.Path,
            kind,
            destination,
            overwrite,
            progress,
            entry.Path,
            cancellationToken).ConfigureAwait(false);
    }

    public async Task ExportPackageAsync(
        string packageRoot,
        string sourcePath,
        ExportKind kind,
        string destination,
        bool overwrite,
        Func<ProgressUpdate, Task>? progress,
        string? currentItem,
        CancellationToken cancellationToken)
    {
        if (!SupportsFormat(kind))
        {
            throw new NotSupportedException($"Archive Lite does not support {kind} as a model interchange format.");
        }

        var fullDestination = Path.GetFullPath(destination);
        var expectedExtension = FileExtension(kind);
        if (!Path.GetExtension(fullDestination).Equals(expectedExtension, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException($"The {kind} export destination must use the {expectedExtension} extension.");
        }

        var package = await NativePreviewMeshPackage.ReadAsync(packageRoot, cancellationToken).ConfigureAwait(false);
        var parent = Path.GetDirectoryName(fullDestination)
            ?? throw new InvalidDataException("Mesh export destination has no parent directory.");
        Directory.CreateDirectory(parent);

        if (kind == ExportKind.Glb)
        {
            await NativeGlbExportWriter.WriteAsync(
                package,
                sourcePath,
                fullDestination,
                overwrite,
                progress,
                currentItem,
                cancellationToken).ConfigureAwait(false);
            return;
        }

        await WriteNativeInterchangeAsync(
            package,
            sourcePath,
            kind,
            fullDestination,
            overwrite,
            progress,
            currentItem,
            cancellationToken).ConfigureAwait(false);
    }

    private static async Task WriteNativeInterchangeAsync(
        NativePreviewMeshPackage package,
        string sourcePath,
        ExportKind kind,
        string destination,
        bool overwrite,
        Func<ProgressUpdate, Task>? progress,
        string? currentItem,
        CancellationToken cancellationToken)
    {
        var workRoot = Path.Combine(
            Path.GetTempPath(),
            "cdmw-archive-lite-mesh-export",
            Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
        Directory.CreateDirectory(workRoot);
        var stagedOutput = Path.Combine(
            Path.GetDirectoryName(destination)!,
            $".{Path.GetFileNameWithoutExtension(destination)}.{Guid.NewGuid():N}.tmp{FileExtension(kind)}");
        try
        {
            var totalWork = checked(package.TotalVertices * 2L);
            await ReportAsync(progress, 0, totalWork, "mesh_export_prepare", currentItem).ConfigureAwait(false);
            var prepared = await PrepareNativeSidecarsAsync(
                package,
                workRoot,
                totalWork,
                progress,
                currentItem,
                cancellationToken).ConfigureAwait(false);

            var jobPath = Path.Combine(workRoot, "job.json");
            var reportPath = Path.Combine(workRoot, "report.json");
            var baseName = CleanName(Path.GetFileNameWithoutExtension(sourcePath), "mesh");
            var operation = kind == ExportKind.Obj ? "obj_export" : "fbx_export";
            var job = new Dictionary<string, object?>
            {
                ["version"] = 1,
                ["backend"] = "cdmw_mesh_core_0.1",
                ["operation"] = operation,
                ["output_path"] = stagedOutput,
                ["base_name"] = baseName,
                ["scale"] = 1.0,
                ["submeshes"] = prepared.Select(static batch => batch.Payload).ToArray(),
            };
            if (kind == ExportKind.Obj)
            {
                job["export_path"] = destination;
                job["source_path"] = sourcePath;
                job["source_format"] = Path.GetExtension(sourcePath).TrimStart('.').ToLowerInvariant();
                job["mtl_filename"] = string.Empty;
                job["total_vertices"] = package.TotalVertices;
                job["total_faces"] = package.TotalVertices / 3;
            }
            else
            {
                job["bones"] = Array.Empty<object>();
            }

            await WriteJsonAsync(jobPath, job, cancellationToken).ConfigureAwait(false);
            await ReportAsync(
                progress,
                package.TotalVertices,
                totalWork,
                "mesh_export_write",
                currentItem).ConfigureAwait(false);
            await RunNativeExportAsync(
                kind == ExportKind.Obj ? "obj-export-json" : "fbx-export-json",
                operation,
                jobPath,
                reportPath,
                stagedOutput,
                cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            File.Move(stagedOutput, destination, overwrite);
            await ReportAsync(progress, totalWork, totalWork, "mesh_export_write", currentItem).ConfigureAwait(false);
        }
        finally
        {
            TryDeleteFile(stagedOutput);
            TryDeleteOwnedDirectory(workRoot);
        }
    }

    private static async Task<IReadOnlyList<PreparedNativeBatch>> PrepareNativeSidecarsAsync(
        NativePreviewMeshPackage package,
        string workRoot,
        long totalWork,
        Func<ProgressUpdate, Task>? progress,
        string? currentItem,
        CancellationToken cancellationToken)
    {
        var result = new List<PreparedNativeBatch>(package.Batches.Count);
        long completed = 0;
        for (var batchOrdinal = 0; batchOrdinal < package.Batches.Count; batchOrdinal++)
        {
            var batch = package.Batches[batchOrdinal];
            var prefix = Path.Combine(workRoot, $"batch_{batchOrdinal:000}");
            var verticesPath = prefix + "_vertices.bin";
            var normalsPath = prefix + "_normals.bin";
            var uvsPath = prefix + "_uvs.bin";
            var facesPath = prefix + "_faces.bin";

            await using var input = OpenRead(batch.GeometryPath);
            await using var vertices = OpenNew(verticesPath);
            await using var normals = OpenNew(normalsPath);
            await using var uvs = OpenNew(uvsPath);
            await using var faces = OpenNew(facesPath);
            var inputBuffer = new byte[RecordsPerChunk * BytesPerPreviewVertex];
            var verticesBuffer = new byte[RecordsPerChunk * 3 * sizeof(double)];
            var normalsBuffer = new byte[RecordsPerChunk * 3 * sizeof(double)];
            var uvsBuffer = new byte[RecordsPerChunk * 2 * sizeof(double)];
            var facesBuffer = new byte[(RecordsPerChunk / 3) * 3 * sizeof(int)];

            var batchCompleted = 0;
            while (batchCompleted < batch.VertexCount)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var count = Math.Min(RecordsPerChunk, batch.VertexCount - batchCompleted);
                var inputBytes = checked(count * BytesPerPreviewVertex);
                await input.ReadExactlyAsync(inputBuffer.AsMemory(0, inputBytes), cancellationToken).ConfigureAwait(false);
                var vertexBytes = checked(count * 3 * sizeof(double));
                var uvBytes = checked(count * 2 * sizeof(double));
                for (var localIndex = 0; localIndex < count; localIndex++)
                {
                    var sourceOffset = localIndex * BytesPerPreviewVertex;
                    WriteFiniteVec3AsF64(inputBuffer, sourceOffset, verticesBuffer, localIndex * 24, "position");
                    WriteFiniteVec3AsF64(
                        inputBuffer,
                        sourceOffset + (3 * sizeof(float)),
                        normalsBuffer,
                        localIndex * 24,
                        "normal");
                    WriteFiniteVec2AsF64(
                        inputBuffer,
                        sourceOffset + (9 * sizeof(float)),
                        uvsBuffer,
                        localIndex * 16,
                        "UV");
                }

                var faceBytes = 0;
                for (var localIndex = 0; localIndex < count; localIndex += 3)
                {
                    var index = checked(batchCompleted + localIndex);
                    BinaryPrimitives.WriteInt32LittleEndian(facesBuffer.AsSpan(faceBytes, 4), index);
                    BinaryPrimitives.WriteInt32LittleEndian(facesBuffer.AsSpan(faceBytes + 4, 4), index + 1);
                    BinaryPrimitives.WriteInt32LittleEndian(facesBuffer.AsSpan(faceBytes + 8, 4), index + 2);
                    faceBytes += 12;
                }

                await vertices.WriteAsync(verticesBuffer.AsMemory(0, vertexBytes), cancellationToken).ConfigureAwait(false);
                await normals.WriteAsync(normalsBuffer.AsMemory(0, vertexBytes), cancellationToken).ConfigureAwait(false);
                await uvs.WriteAsync(uvsBuffer.AsMemory(0, uvBytes), cancellationToken).ConfigureAwait(false);
                await faces.WriteAsync(facesBuffer.AsMemory(0, faceBytes), cancellationToken).ConfigureAwait(false);
                batchCompleted += count;
                completed += count;
                await ReportAsync(progress, completed, totalWork, "mesh_export_prepare", currentItem).ConfigureAwait(false);
            }

            var name = CleanName(batch.MaterialName, $"part_{batch.Index:000}");
            result.Add(new PreparedNativeBatch(new Dictionary<string, object?>
            {
                ["index"] = batch.Index,
                ["name"] = name,
                ["material"] = name,
                ["vertices_binary"] = BinaryDescriptor(verticesPath, batch.VertexCount, 3, "f64"),
                ["faces_binary"] = BinaryDescriptor(facesPath, batch.VertexCount / 3, 3, "i32"),
                ["normals_binary"] = BinaryDescriptor(normalsPath, batch.VertexCount, 3, "f64"),
                ["uvs_binary"] = BinaryDescriptor(uvsPath, batch.VertexCount, 2, "f64"),
            }));
        }
        return result;
    }

    private static Dictionary<string, object?> BinaryDescriptor(
        string path,
        int count,
        int components,
        string type) => new()
    {
        ["path"] = path,
        ["count"] = count,
        ["components"] = components,
        ["type"] = type,
    };

    private static async Task RunNativeExportAsync(
        string command,
        string expectedOperation,
        string jobPath,
        string reportPath,
        string expectedOutput,
        CancellationToken cancellationToken)
    {
        var executable = ResolveMeshCorePath();
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(executable) ?? AppContext.BaseDirectory,
        };
        startInfo.ArgumentList.Add(command);
        startInfo.ArgumentList.Add(jobPath);
        startInfo.ArgumentList.Add(reportPath);
        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("cdmw-mesh-core could not be started.");
        var stdout = ReadBoundedAsync(process.StandardOutput, cancellationToken);
        var stderr = ReadBoundedAsync(process.StandardError, cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(NativeExportTimeout);
        try
        {
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            StopProcess(process);
            await ObserveCaptureAsync(stdout, stderr).ConfigureAwait(false);
            throw new TimeoutException($"cdmw-mesh-core did not finish within {NativeExportTimeout.TotalMinutes:N0} minutes.");
        }
        catch (OperationCanceledException)
        {
            StopProcess(process);
            await ObserveCaptureAsync(stdout, stderr).ConfigureAwait(false);
            throw;
        }

        var stdoutText = await stdout.ConfigureAwait(false);
        var stderrText = await stderr.ConfigureAwait(false);
        if (process.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(stderrText) ? stdoutText : stderrText;
            throw new InvalidDataException($"cdmw-mesh-core exited with code {process.ExitCode}: {detail.Trim()}");
        }
        await ValidateNativeReportAsync(reportPath, expectedOperation, expectedOutput, cancellationToken).ConfigureAwait(false);
    }

    private static async Task ValidateNativeReportAsync(
        string reportPath,
        string expectedOperation,
        string expectedOutput,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(reportPath))
        {
            throw new InvalidDataException("cdmw-mesh-core did not produce an export report.");
        }
        using var report = JsonDocument.Parse(
            await File.ReadAllTextAsync(reportPath, cancellationToken).ConfigureAwait(false));
        var root = report.RootElement;
        if (ReadString(root, "status") != "ok"
            || ReadString(root, "backend") != "cdmw_mesh_core_0.1"
            || ReadString(root, "operation") != expectedOperation)
        {
            throw new InvalidDataException($"cdmw-mesh-core returned an invalid {expectedOperation} report.");
        }
        var reportedOutput = Path.GetFullPath(ReadString(root, "output_path"));
        if (!reportedOutput.Equals(Path.GetFullPath(expectedOutput), StringComparison.OrdinalIgnoreCase)
            || !File.Exists(reportedOutput)
            || new FileInfo(reportedOutput).Length == 0)
        {
            throw new InvalidDataException("cdmw-mesh-core reported an unexpected or empty output file.");
        }
    }

    private static string ResolveMeshCorePath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_MESH_CORE_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
        {
            return Path.GetFullPath(overridePath);
        }
        var packaged = Path.Combine(AppContext.BaseDirectory, "mesh", "cdmw-mesh-core.exe");
        if (File.Exists(packaged))
        {
            return packaged;
        }
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            foreach (var configuration in new[] { "Release", "Debug" })
            {
                var candidate = Path.Combine(
                    current.FullName,
                    "native",
                    "cdmw_mesh_core",
                    "build",
                    configuration,
                    "cdmw-mesh-core.exe");
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
        }
        throw new FileNotFoundException(
            "cdmw-mesh-core.exe was not found. Rebuild the Archive Lite portable package or set CDMW_ARCHIVE_LITE_MESH_CORE_PATH.");
    }

    private static async Task WriteJsonAsync(string path, object payload, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            64 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        await JsonSerializer.SerializeAsync(stream, payload, CompactJson, cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task ReportAsync(
        Func<ProgressUpdate, Task>? progress,
        long completed,
        long total,
        string phase,
        string? currentItem)
    {
        if (progress is not null)
        {
            await progress(new ProgressUpdate(completed, total, phase, currentItem)).ConfigureAwait(false);
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

    private static async Task ObserveCaptureAsync(params Task<string>[] captures)
    {
        foreach (var capture in captures)
        {
            try
            {
                _ = await capture.ConfigureAwait(false);
            }
            catch
            {
                // The helper is already being torn down; only observe the capture task.
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

    private static string CleanName(string? value, string fallback)
    {
        var source = string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
        var builder = new StringBuilder(Math.Min(source.Length, 96));
        foreach (var character in source)
        {
            if (builder.Length >= 96)
            {
                break;
            }
            builder.Append(char.IsControl(character) || character is '/' or '\\' ? '_' : character);
        }
        return builder.Length == 0 ? fallback : builder.ToString();
    }

    private static void TryDeleteFile(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (IOException)
        {
            // A later temp cleanup can remove a locked staging file.
        }
        catch (UnauthorizedAccessException)
        {
            // Preserve the primary conversion result.
        }
    }

    private static void TryDeleteOwnedDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (IOException)
        {
            // A later temp cleanup can remove a locked work directory.
        }
        catch (UnauthorizedAccessException)
        {
            // Preserve the primary conversion result.
        }
    }

    private static string ReadString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
    }

    private sealed record PreparedNativeBatch(Dictionary<string, object?> Payload);
}
