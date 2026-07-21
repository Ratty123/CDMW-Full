using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveItemCatalogBuildService(
    ArchiveSessionManager sessions,
    NativeArchiveCore native)
{
    private const int CacheSchemaVersion = 3;
    private const int NativeCatalogSchemaVersion = 1;
    private const int MaximumDiagnosticCharacters = 64 * 1024;
    private static readonly TimeSpan IndexerTimeout = TimeSpan.FromMinutes(3);
    private static readonly JsonSerializerOptions CacheJsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false,
    };
    private static readonly (string Language, string TableName)[] LocalizationTables =
    [
        ("kor", "localizationstring_kor"), ("eng", "localizationstring_eng"),
        ("jpn", "localizationstring_jpn"), ("rus", "localizationstring_rus"),
        ("tur", "localizationstring_tur"), ("spa-es", "localizationstring_spa-es"),
        ("spa-mx", "localizationstring_spa-mx"), ("fre", "localizationstring_fre"),
        ("ger", "localizationstring_ger"), ("ita", "localizationstring_ita"),
        ("pol", "localizationstring_pol"), ("por-br", "localizationstring_por-br"),
        ("zho-tw", "localizationstring_zho-tw"), ("zho-cn", "localizationstring_zho-cn"),
    ];
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _buildGates = new(StringComparer.OrdinalIgnoreCase);

    public async Task<BuildNameIndexResult> BuildAsync(
        BuildNameIndexRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        if (session.TryGetItemCatalog(out var active) && active is not null)
        {
            return Result(session, active, usedCache: true);
        }
        var gate = _buildGates.GetOrAdd(session.GenerationPath, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (session.TryGetItemCatalog(out active) && active is not null)
            {
                return Result(session, active, usedCache: true);
            }
            var cachePath = Path.Combine(session.GenerationPath, "item-catalog-v3.json");
            var cached = await TryLoadCacheAsync(cachePath, cancellationToken).ConfigureAwait(false);
            if (cached is not null)
            {
                session.SetCatalogue(cached.NameIndex, cached.ItemCatalog);
                return Result(session, cached.ItemCatalog, usedCache: true);
            }

            var ownedRoot = Path.Combine(Path.GetTempPath(), "cdmw-full-item-index");
            Directory.CreateDirectory(ownedRoot);
            var workRoot = Path.Combine(ownedRoot, $"{SafeFilePart(session.Fingerprint)}-{Guid.NewGuid():N}");
            Directory.CreateDirectory(workRoot);
            try
            {
                var payloadRoot = Path.Combine(workRoot, "payloads");
                Directory.CreateDirectory(payloadRoot);
                var entriesPath = Path.Combine(workRoot, "entries.tsv");
                var sources = await WriteEntriesAndFindSourcesAsync(
                    session,
                    entriesPath,
                    publishProgress,
                    cancellationToken).ConfigureAwait(false);
                if (sources.ItemInfo is null)
                {
                    return new BuildNameIndexResult(
                        session.Id,
                        Available: false,
                        UsedCache: false,
                        ExactNameCount: 0,
                        RelatedNameCount: 0,
                        Warning: "ItemInfo was not found in package 0008, so the item catalogue is empty.");
                }
                await ExtractSourcesAsync(sources, payloadRoot, publishProgress, cancellationToken).ConfigureAwait(false);
                var reportPath = Path.Combine(workRoot, "item-index.json");
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(0, 0, "item_catalog_build")).ConfigureAwait(false);
                }
                await RunIndexerAsync(entriesPath, payloadRoot, reportPath, cancellationToken).ConfigureAwait(false);
                var built = await ReadReportAsync(reportPath, cancellationToken).ConfigureAwait(false);
                await SaveCacheAsync(cachePath, built, cancellationToken).ConfigureAwait(false);
                session.SetCatalogue(built.NameIndex, built.ItemCatalog);
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(1, 1, "item_catalog_ready")).ConfigureAwait(false);
                }
                return Result(session, built.ItemCatalog, usedCache: false);
            }
            finally
            {
                DeleteOwnedWorkDirectory(workRoot, ownedRoot);
            }
        }
        finally
        {
            gate.Release();
        }
    }

    private static BuildNameIndexResult Result(ArchiveSession session, ArchiveItemCatalog catalog, bool usedCache)
    {
        session.TryGetNameIndex(out var names);
        return new BuildNameIndexResult(
            session.Id,
            Available: true,
            UsedCache: usedCache,
            ExactNameCount: names?.ExactNames.Count ?? 0,
            RelatedNameCount: names?.RelatedNames.Count ?? 0,
            ItemCount: catalog.Count);
    }

    private static async Task<NameIndexSources> WriteEntriesAndFindSourcesAsync(
        ArchiveSession session,
        string entriesPath,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        var sources = new NameIndexSources();
        var total = session.Index.EntryCount;
        await using var stream = new FileStream(entriesPath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1024 * 1024, FileOptions.SequentialScan);
        await using var writer = new StreamWriter(stream, new UTF8Encoding(false), 1024 * 1024, leaveOpen: false) { NewLine = "\n" };
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(entryId, total, "item_catalog_scan")).ConfigureAwait(false);
                }
            }
            var entry = session.ReadEntry(entryId);
            FindSource(sources, entry);
            writer.Write(entryId); writer.Write('\t');
            writer.Write(CleanTsv(entry.Path)); writer.Write('\t');
            writer.Write(CleanTsv(entry.SourcePamt)); writer.Write('\t');
            writer.Write(CleanTsv(entry.PazFile)); writer.Write('\t');
            writer.Write(entry.Offset); writer.Write('\t');
            writer.Write(entry.StoredSize); writer.Write('\t');
            writer.Write(entry.OriginalSize); writer.Write('\t');
            writer.Write(entry.Flags); writer.Write('\t');
            writer.Write(entry.PazIndex); writer.WriteLine();
        }
        await writer.FlushAsync(cancellationToken).ConfigureAwait(false);
        return sources;
    }

    private static void FindSource(NameIndexSources sources, ArchiveEntryDto entry)
    {
        var lowerPath = entry.Path.Replace('\\', '/').ToLowerInvariant();
        var basename = Path.GetFileName(lowerPath);
        var packageGroup = Path.GetFileName(Path.GetDirectoryName(entry.SourcePamt))?.ToLowerInvariant() ?? string.Empty;
        if (packageGroup == "0008")
        {
            if (sources.ItemInfo is null && lowerPath.Contains("iteminfo.pabgb", StringComparison.Ordinal)) sources.ItemInfo = entry;
            else if (sources.StringInfo is null && basename == "stringinfo.pabgb") sources.StringInfo = entry;
            else if (sources.PartPrefabDyeSlotInfo is null && basename == "partprefabdyeslotinfo.pabgb") sources.PartPrefabDyeSlotInfo = entry;
        }
        if (packageGroup != "0020" || !lowerPath.Contains("localizationstring_", StringComparison.Ordinal)) return;
        foreach (var (language, tableName) in LocalizationTables)
        {
            if (!sources.Localizations.ContainsKey(language) && lowerPath.Contains(tableName, StringComparison.Ordinal))
            {
                sources.Localizations[language] = entry;
                break;
            }
        }
    }

    private async Task ExtractSourcesAsync(
        NameIndexSources sources,
        string payloadRoot,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        var payloads = new List<(string Name, ArchiveEntryDto Entry)> { ("iteminfo.bin", sources.ItemInfo!) };
        if (sources.StringInfo is not null) payloads.Add(("stringinfo.bin", sources.StringInfo));
        if (sources.PartPrefabDyeSlotInfo is not null) payloads.Add(("partprefabdyeslotinfo.bin", sources.PartPrefabDyeSlotInfo));
        payloads.AddRange(sources.Localizations.Select(pair => ($"loc_{pair.Key}.bin", pair.Value)));
        for (var index = 0; index < payloads.Count; index++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var (name, entry) = payloads[index];
            if (publishProgress is not null)
            {
                await publishProgress(new ProgressUpdate(index, payloads.Count, "item_catalog_extract", name)).ConfigureAwait(false);
            }
            var decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
            await File.WriteAllBytesAsync(Path.Combine(payloadRoot, name), decoded.Bytes, cancellationToken).ConfigureAwait(false);
        }
    }

    private static async Task RunIndexerAsync(string entriesPath, string payloadRoot, string reportPath, CancellationToken cancellationToken)
    {
        var executable = ResolveIndexerPath();
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(executable) ?? AppContext.BaseDirectory,
        };
        startInfo.ArgumentList.Add("item-index-job");
        startInfo.ArgumentList.Add(entriesPath);
        startInfo.ArgumentList.Add(payloadRoot);
        startInfo.ArgumentList.Add(reportPath);
        using var process = Process.Start(startInfo) ?? throw new InvalidOperationException("cdmw-archive-accelerator could not be started.");
        var stdout = ReadBoundedAsync(process.StandardOutput, cancellationToken);
        var stderr = ReadBoundedAsync(process.StandardError, cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(IndexerTimeout);
        try
        {
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            StopProcess(process);
            await ObserveCaptureAsync(stdout, stderr).ConfigureAwait(false);
            if (!cancellationToken.IsCancellationRequested)
            {
                throw new TimeoutException($"The native item catalogue indexer did not finish within {IndexerTimeout.TotalMinutes:N0} minutes.");
            }
            throw;
        }
        var stdoutText = await stdout.ConfigureAwait(false);
        var stderrText = await stderr.ConfigureAwait(false);
        if (process.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(stderrText) ? stdoutText : stderrText;
            throw new InvalidDataException($"cdmw-archive-accelerator exited with code {process.ExitCode}: {detail.Trim()}");
        }
    }

    private static async Task<CatalogueBuildState> ReadReportAsync(string reportPath, CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(reportPath);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
        var root = document.RootElement;
        var status = root.TryGetProperty("status", out var statusValue) ? statusValue.GetString() : null;
        if (!string.Equals(status, "ok", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(root.TryGetProperty("message", out var message) ? message.GetString() : "The native item catalogue report is invalid.");
        }
        if (root.TryGetProperty("catalog_schema", out var schemaValue)
            && (!schemaValue.TryGetInt32(out var schema) || schema != NativeCatalogSchemaVersion))
        {
            throw new InvalidDataException($"The native item catalogue schema is not supported; expected {NativeCatalogSchemaVersion}.");
        }
        var exact = ReadStringMap(root, "model_base_exact_display_names");
        var related = ReadStringMap(root, "model_base_display_names");
        foreach (var (key, value) in ReadStringMap(root, "model_base_related_display_names")) related[key] = value;
        return new CatalogueBuildState(
            ArchiveNameIndex.FromMappings(exact, related),
            ArchiveItemCatalog.FromRecords(ReadItems(root)));
    }

    private static IReadOnlyList<ArchiveItemCatalogRecord> ReadItems(JsonElement root)
    {
        if (!root.TryGetProperty("items", out var rows) || rows.ValueKind != JsonValueKind.Array) return [];
        var result = new List<ArchiveItemCatalogRecord>();
        foreach (var row in rows.EnumerateArray())
        {
            if (!row.TryGetProperty("item_id", out var itemIdValue) || !itemIdValue.TryGetInt32(out var itemId) || itemId <= 0) continue;
            var internalName = ReadString(row, "internal_name");
            if (internalName.Length == 0) continue;
            result.Add(new ArchiveItemCatalogRecord(
                itemId,
                internalName,
                ReadString(row, "display_name"),
                ReadStrings(row, "localized_names"),
                ReadUInt32s(row, "prefab_hashes"),
                ReadStrings(row, "model_stems"),
                ReadStrings(row, "pac_files"),
                ReadStrings(row, "icon_paths"),
                ReadStrings(row, "material_tags")));
        }
        return result;
    }

    private static async Task<CatalogueBuildState?> TryLoadCacheAsync(string cachePath, CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = File.OpenRead(cachePath);
            var payload = await JsonSerializer.DeserializeAsync<NameIndexCachePayload>(stream, CacheJsonOptions, cancellationToken).ConfigureAwait(false);
            if (payload is not { SchemaVersion: CacheSchemaVersion } || payload.ExactNames is null || payload.RelatedNames is null || payload.Items is null) return null;
            return new CatalogueBuildState(
                ArchiveNameIndex.FromMappings(payload.ExactNames, payload.RelatedNames),
                ArchiveItemCatalog.FromRecords(payload.Items));
        }
        catch (Exception exception) when (exception is FileNotFoundException or JsonException or IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static async Task SaveCacheAsync(string cachePath, CatalogueBuildState state, CancellationToken cancellationToken)
    {
        var staging = Path.Combine(Path.GetDirectoryName(cachePath)!, $".{Path.GetFileName(cachePath)}.{Guid.NewGuid():N}.tmp");
        try
        {
            await using (var stream = new FileStream(staging, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1024 * 1024, FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await JsonSerializer.SerializeAsync(
                    stream,
                    new NameIndexCachePayload(
                        CacheSchemaVersion,
                        state.NameIndex.ExactNames.ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.OrdinalIgnoreCase),
                        state.NameIndex.RelatedNames.ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.OrdinalIgnoreCase),
                        state.ItemCatalog.Items),
                    CacheJsonOptions,
                    cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }
            cancellationToken.ThrowIfCancellationRequested();
            File.Move(staging, cachePath, overwrite: true);
        }
        finally
        {
            try { File.Delete(staging); } catch { }
        }
    }

    private static string ResolveIndexerPath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_FULL_ARCHIVE_ITEM_INDEX_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath)) return Path.GetFullPath(overridePath);
        var packaged = Path.Combine(AppContext.BaseDirectory, "indexer", "cdmw-archive-accelerator.exe");
        if (File.Exists(packaged)) return packaged;
        var packagedSibling = Path.GetFullPath(Path.Combine(
            AppContext.BaseDirectory,
            "..",
            "native",
            "cdmw-archive-accelerator.exe"));
        if (File.Exists(packagedSibling)) return packagedSibling;
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            foreach (var configuration in new[] { "Release", "Debug" })
            {
                var candidate = Path.Combine(current.FullName, "native", "cdmw_archive_accelerator", "build", configuration, "cdmw-archive-accelerator.exe");
                if (File.Exists(candidate)) return candidate;
            }
        }
        throw new FileNotFoundException("cdmw-archive-accelerator.exe was not found. Rebuild CDMW Full or set CDMW_FULL_ARCHIVE_ITEM_INDEX_PATH.");
    }

    private static string ReadString(JsonElement row, string name) =>
        row.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()?.Trim() ?? string.Empty : string.Empty;

    private static string[] ReadStrings(JsonElement row, string name) =>
        row.TryGetProperty(name, out var values) && values.ValueKind == JsonValueKind.Array
            ? values.EnumerateArray().Where(static value => value.ValueKind == JsonValueKind.String)
                .Select(static value => value.GetString()?.Trim() ?? string.Empty).Where(static value => value.Length > 0)
                .Distinct(StringComparer.OrdinalIgnoreCase).ToArray()
            : [];

    private static uint[] ReadUInt32s(JsonElement row, string name)
    {
        if (!row.TryGetProperty(name, out var values) || values.ValueKind != JsonValueKind.Array) return [];
        return values.EnumerateArray().Select(static value => value.TryGetUInt32(out var number) ? number : 0).Where(static value => value > 0).Distinct().ToArray();
    }

    private static Dictionary<string, string> ReadStringMap(JsonElement root, string name)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!root.TryGetProperty(name, out var rows) || rows.ValueKind != JsonValueKind.Array) return result;
        foreach (var row in rows.EnumerateArray())
        {
            if (row.ValueKind != JsonValueKind.Array || row.GetArrayLength() < 2) continue;
            var key = row[0].GetString()?.Trim().ToLowerInvariant();
            var value = row[1].GetString()?.Trim();
            if (!string.IsNullOrWhiteSpace(key) && !string.IsNullOrWhiteSpace(value)) result[key] = value;
        }
        return result;
    }

    private static string CleanTsv(string value) => value.Replace('\t', ' ').Replace('\r', ' ').Replace('\n', ' ');
    private static string SafeFilePart(string value) => string.Concat(value.Take(32).Where(static character => char.IsLetterOrDigit(character)));

    private static async Task<string> ReadBoundedAsync(StreamReader reader, CancellationToken cancellationToken)
    {
        var output = new StringBuilder();
        var buffer = new char[4096];
        while (true)
        {
            var count = await reader.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
            if (count == 0) break;
            if (output.Length < MaximumDiagnosticCharacters) output.Append(buffer, 0, Math.Min(count, MaximumDiagnosticCharacters - output.Length));
        }
        return output.ToString();
    }

    private static async Task ObserveCaptureAsync(params Task<string>[] tasks)
    {
        foreach (var task in tasks) try { _ = await task.ConfigureAwait(false); } catch { }
    }

    private static void StopProcess(Process process)
    {
        try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch { }
    }

    private static void DeleteOwnedWorkDirectory(string workRoot, string ownedRoot)
    {
        try
        {
            var prefix = Path.GetFullPath(ownedRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var resolved = Path.GetFullPath(workRoot);
            if (resolved.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) && Directory.Exists(resolved)) Directory.Delete(resolved, recursive: true);
        }
        catch { }
    }

    private sealed class NameIndexSources
    {
        public ArchiveEntryDto? ItemInfo { get; set; }
        public ArchiveEntryDto? StringInfo { get; set; }
        public ArchiveEntryDto? PartPrefabDyeSlotInfo { get; set; }
        public Dictionary<string, ArchiveEntryDto> Localizations { get; } = new(StringComparer.OrdinalIgnoreCase);
    }

    private sealed record NameIndexCachePayload(
        int SchemaVersion,
        Dictionary<string, string> ExactNames,
        Dictionary<string, string> RelatedNames,
        IReadOnlyList<ArchiveItemCatalogRecord> Items);

    private sealed record CatalogueBuildState(ArchiveNameIndex NameIndex, ArchiveItemCatalog ItemCatalog);
}
