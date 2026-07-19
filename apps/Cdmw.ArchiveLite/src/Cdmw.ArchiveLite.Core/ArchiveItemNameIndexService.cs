using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveItemNameIndexService(
    ArchiveSessionManager sessions,
    NativeArchiveCore native)
{
    private const int CacheSchemaVersion = 2;
    private const int NativeCatalogSchemaVersion = 1;
    private const int MaximumDiagnosticCharacters = 64 * 1024;
    private static readonly TimeSpan IndexerTimeout = TimeSpan.FromMinutes(3);
    private static readonly JsonSerializerOptions CacheJsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
    };

    private static readonly (string Language, string TableName)[] LocalizationTables =
    [
        ("kor", "localizationstring_kor"),
        ("eng", "localizationstring_eng"),
        ("jpn", "localizationstring_jpn"),
        ("rus", "localizationstring_rus"),
        ("tur", "localizationstring_tur"),
        ("spa-es", "localizationstring_spa-es"),
        ("spa-mx", "localizationstring_spa-mx"),
        ("fre", "localizationstring_fre"),
        ("ger", "localizationstring_ger"),
        ("ita", "localizationstring_ita"),
        ("pol", "localizationstring_pol"),
        ("por-br", "localizationstring_por-br"),
        ("zho-tw", "localizationstring_zho-tw"),
        ("zho-cn", "localizationstring_zho-cn"),
    ];

    public async Task<BuildNameIndexResult> BuildAsync(
        BuildNameIndexRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        await session.NameIndexBuildGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (session.TryGetNameIndex(out var active)
                && active is not null
                && session.TryGetItemCatalog(out var activeCatalog)
                && activeCatalog is not null)
            {
                return Result(session, active, activeCatalog, usedCache: true);
            }

            ArchiveLiteDataPaths.EnsureCreated();
            var cachePath = Path.Combine(ArchiveLiteDataPaths.NameIndexCache, $"{session.Fingerprint}.json");
            var cached = await TryLoadCacheAsync(cachePath, cancellationToken).ConfigureAwait(false);
            if (cached is not null)
            {
                session.SetCatalogue(cached.NameIndex, cached.ItemCatalog);
                return Result(session, cached.NameIndex, cached.ItemCatalog, usedCache: true);
            }

            var workRoot = Path.Combine(ArchiveLiteDataPaths.NameIndexCache, $".work-{Guid.NewGuid():N}");
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
                        Warning: "ItemInfo was not found in package 0008, so known in-game names and Item Finder are unavailable.",
                        ItemCount: 0);
                }

                await ExtractSourcesAsync(sources, payloadRoot, publishProgress, cancellationToken).ConfigureAwait(false);
                var reportPath = Path.Combine(workRoot, "item-index.json");
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(0, 0, "name_build")).ConfigureAwait(false);
                }
                await RunIndexerAsync(entriesPath, payloadRoot, reportPath, cancellationToken).ConfigureAwait(false);
                var catalogue = await ReadReportAsync(reportPath, cancellationToken).ConfigureAwait(false);
                await SaveCacheAsync(cachePath, catalogue, cancellationToken).ConfigureAwait(false);
                session.SetCatalogue(catalogue.NameIndex, catalogue.ItemCatalog);
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(1, 1, "name_publish")).ConfigureAwait(false);
                }
                return Result(session, catalogue.NameIndex, catalogue.ItemCatalog, usedCache: false);
            }
            finally
            {
                DeleteOwnedWorkDirectory(workRoot);
            }
        }
        finally
        {
            session.NameIndexBuildGate.Release();
        }
    }

    private static BuildNameIndexResult Result(
        ArchiveSession session,
        ArchiveItemNameIndex index,
        ArchiveItemCatalog catalog,
        bool usedCache) => new(
            session.Id,
            Available: true,
            UsedCache: usedCache,
            ExactNameCount: index.ExactNameCount,
            RelatedNameCount: index.RelatedNameCount,
            ItemCount: catalog.Count);

    private static async Task<NameIndexSources> WriteEntriesAndFindSourcesAsync(
        ArchiveSession session,
        string entriesPath,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        var sources = new NameIndexSources();
        var total = session.Index.EntryCount;
        await using var stream = new FileStream(
            entriesPath,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            1024 * 1024,
            FileOptions.SequentialScan);
        await using var writer = new StreamWriter(stream, new UTF8Encoding(false), 1024 * 1024, leaveOpen: false)
        {
            NewLine = "\n",
        };
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(entryId, total, "name_scan")).ConfigureAwait(false);
                }
            }
            var entry = session.Index.ReadEntry(entryId);
            FindSource(sources, entry);
            writer.Write(entryId);
            writer.Write('\t');
            writer.Write(CleanTsv(entry.Path));
            writer.Write('\t');
            writer.Write(CleanTsv(entry.SourcePamt));
            writer.Write('\t');
            writer.Write(CleanTsv(entry.PazFile));
            writer.Write('\t');
            writer.Write(entry.Offset);
            writer.Write('\t');
            writer.Write(entry.StoredSize);
            writer.Write('\t');
            writer.Write(entry.OriginalSize);
            writer.Write('\t');
            writer.Write(entry.Flags);
            writer.Write('\t');
            writer.Write(entry.PazIndex);
            writer.WriteLine();
        }
        cancellationToken.ThrowIfCancellationRequested();
        await writer.FlushAsync(cancellationToken).ConfigureAwait(false);
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(total, total, "name_scan")).ConfigureAwait(false);
        }
        return sources;
    }

    private static void FindSource(NameIndexSources sources, ArchiveEntryDto entry)
    {
        var lowerPath = entry.Path.Replace('\\', '/').ToLowerInvariant();
        var basename = Path.GetFileName(lowerPath);
        var packageGroup = Path.GetFileName(Path.GetDirectoryName(entry.SourcePamt))?.ToLowerInvariant() ?? string.Empty;
        if (packageGroup == "0008")
        {
            if (sources.ItemInfo is null && lowerPath.Contains("iteminfo.pabgb", StringComparison.Ordinal))
            {
                sources.ItemInfo = entry;
            }
            else if (sources.StringInfo is null && basename == "stringinfo.pabgb")
            {
                sources.StringInfo = entry;
            }
            else if (sources.PartPrefabDyeSlotInfo is null && basename == "partprefabdyeslotinfo.pabgb")
            {
                sources.PartPrefabDyeSlotInfo = entry;
            }
        }
        if (packageGroup != "0020" || !lowerPath.Contains("localizationstring_", StringComparison.Ordinal))
        {
            return;
        }
        foreach (var (language, tableName) in LocalizationTables)
        {
            if (!sources.Localizations.ContainsKey(language)
                && lowerPath.Contains(tableName, StringComparison.Ordinal))
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
        var payloads = new List<(string Name, ArchiveEntryDto Entry)>
        {
            ("iteminfo.bin", sources.ItemInfo!),
        };
        if (sources.StringInfo is not null)
        {
            payloads.Add(("stringinfo.bin", sources.StringInfo));
        }
        if (sources.PartPrefabDyeSlotInfo is not null)
        {
            payloads.Add(("partprefabdyeslotinfo.bin", sources.PartPrefabDyeSlotInfo));
        }
        payloads.AddRange(sources.Localizations.Select(pair => ($"loc_{pair.Key}.bin", pair.Value)));

        for (var index = 0; index < payloads.Count; index++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var (name, entry) = payloads[index];
            if (publishProgress is not null)
            {
                await publishProgress(new ProgressUpdate(index, payloads.Count, "name_extract", name)).ConfigureAwait(false);
            }
            var decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
            await File.WriteAllBytesAsync(Path.Combine(payloadRoot, name), decoded.Bytes, cancellationToken).ConfigureAwait(false);
        }
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(payloads.Count, payloads.Count, "name_extract")).ConfigureAwait(false);
        }
    }

    private static async Task RunIndexerAsync(
        string entriesPath,
        string payloadRoot,
        string reportPath,
        CancellationToken cancellationToken)
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
        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("cdmw-archive-accelerator could not be started.");
        var stdout = ReadBoundedAsync(process.StandardOutput, cancellationToken);
        var stderr = ReadBoundedAsync(process.StandardError, cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(IndexerTimeout);
        try
        {
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            StopProcess(process);
            await ObserveCaptureAsync(stdout, stderr).ConfigureAwait(false);
            throw new TimeoutException($"The native item catalog indexer did not finish within {IndexerTimeout.TotalMinutes:N0} minutes.");
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
            throw new InvalidDataException($"cdmw-archive-accelerator exited with code {process.ExitCode}: {detail.Trim()}");
        }
    }

    private static async Task<CatalogueBuildState> ReadReportAsync(
        string reportPath,
        CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            reportPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            1024 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
        var root = document.RootElement;
        var status = root.TryGetProperty("status", out var statusValue) ? statusValue.GetString() : null;
        if (!string.Equals(status, "ok", StringComparison.OrdinalIgnoreCase))
        {
            var message = root.TryGetProperty("message", out var messageValue) ? messageValue.GetString() : null;
            throw new InvalidDataException(message ?? "The native item catalog indexer returned an invalid report.");
        }
        if (root.TryGetProperty("catalog_schema", out var schemaValue)
            && (!schemaValue.TryGetInt32(out var schema) || schema != NativeCatalogSchemaVersion))
        {
            throw new InvalidDataException($"The native item catalog schema is not supported; expected {NativeCatalogSchemaVersion}.");
        }
        var exact = ReadStringMap(root, "model_base_exact_display_names");
        var related = ReadStringMap(root, "model_base_display_names");
        foreach (var (key, value) in ReadStringMap(root, "model_base_related_display_names"))
        {
            related[key] = value;
        }
        var nameIndex = ArchiveItemNameIndex.FromMappings(exact, related);
        var itemCatalog = ArchiveItemCatalog.FromRecords(ReadItems(root));
        return new CatalogueBuildState(nameIndex, itemCatalog);
    }

    private static IReadOnlyList<ArchiveItemCatalogRecord> ReadItems(JsonElement root)
    {
        if (!root.TryGetProperty("items", out var rows) || rows.ValueKind != JsonValueKind.Array)
        {
            return [];
        }
        var result = new List<ArchiveItemCatalogRecord>();
        foreach (var row in rows.EnumerateArray())
        {
            if (row.ValueKind != JsonValueKind.Object
                || !row.TryGetProperty("item_id", out var itemIdValue)
                || !itemIdValue.TryGetInt32(out var itemId)
                || itemId <= 0)
            {
                continue;
            }
            var internalName = ReadString(row, "internal_name");
            if (string.IsNullOrWhiteSpace(internalName))
            {
                continue;
            }
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

    private static string ReadString(JsonElement row, string propertyName) =>
        row.TryGetProperty(propertyName, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()?.Trim() ?? string.Empty
            : string.Empty;

    private static string[] ReadStrings(JsonElement row, string propertyName)
    {
        if (!row.TryGetProperty(propertyName, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return [];
        }
        return values.EnumerateArray()
            .Where(static value => value.ValueKind == JsonValueKind.String)
            .Select(static value => value.GetString()?.Trim() ?? string.Empty)
            .Where(static value => value.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static uint[] ReadUInt32s(JsonElement row, string propertyName)
    {
        if (!row.TryGetProperty(propertyName, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return [];
        }
        var result = new List<uint>();
        foreach (var value in values.EnumerateArray())
        {
            if (value.TryGetUInt32(out var number)) result.Add(number);
        }
        return result.Distinct().ToArray();
    }

    private static Dictionary<string, string> ReadStringMap(JsonElement root, string propertyName)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!root.TryGetProperty(propertyName, out var rows) || rows.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var row in rows.EnumerateArray())
        {
            if (row.ValueKind != JsonValueKind.Array || row.GetArrayLength() < 2)
            {
                continue;
            }
            var key = row[0].GetString()?.Trim().ToLowerInvariant();
            var value = row[1].GetString()?.Trim();
            if (!string.IsNullOrWhiteSpace(key) && !string.IsNullOrWhiteSpace(value))
            {
                result[key] = value;
            }
        }
        return result;
    }

    private static async Task<CatalogueBuildState?> TryLoadCacheAsync(
        string cachePath,
        CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = File.OpenRead(cachePath);
            var payload = await JsonSerializer.DeserializeAsync<NameIndexCachePayload>(
                stream,
                CacheJsonOptions,
                cancellationToken).ConfigureAwait(false);
            if (payload is not { SchemaVersion: CacheSchemaVersion }
                || payload.ExactNames is null
                || payload.RelatedNames is null
                || payload.Items is null)
            {
                return null;
            }
            return new CatalogueBuildState(
                ArchiveItemNameIndex.FromMappings(payload.ExactNames, payload.RelatedNames),
                ArchiveItemCatalog.FromRecords(payload.Items));
        }
        catch (FileNotFoundException)
        {
            return null;
        }
        catch (JsonException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
    }

    private static Task SaveCacheAsync(
        string cachePath,
        CatalogueBuildState catalogue,
        CancellationToken cancellationToken) => AtomicFile.WriteAsync(
            cachePath,
            async (stream, token) => await JsonSerializer.SerializeAsync(
                stream,
                new NameIndexCachePayload(
                    CacheSchemaVersion,
                    catalogue.NameIndex.ExactNames.ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.OrdinalIgnoreCase),
                    catalogue.NameIndex.RelatedNames.ToDictionary(static pair => pair.Key, static pair => pair.Value, StringComparer.OrdinalIgnoreCase),
                    catalogue.ItemCatalog.Items.ToArray()),
                CacheJsonOptions,
                token).ConfigureAwait(false),
            cancellationToken);

    private static string ResolveIndexerPath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
        {
            return Path.GetFullPath(overridePath);
        }
        var packaged = Path.Combine(AppContext.BaseDirectory, "indexer", "cdmw-archive-accelerator.exe");
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
                    "cdmw_archive_accelerator",
                    "build",
                    configuration,
                    "cdmw-archive-accelerator.exe");
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
        }
        throw new FileNotFoundException(
            "cdmw-archive-accelerator.exe was not found. Rebuild the Archive Lite portable package or set CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH.");
    }

    private static string CleanTsv(string value) => value
        .Replace('\t', ' ')
        .Replace('\r', ' ')
        .Replace('\n', ' ');

    private static async Task<string> ReadBoundedAsync(
        StreamReader reader,
        CancellationToken cancellationToken)
    {
        var output = new StringBuilder();
        var buffer = new char[4096];
        while (true)
        {
            var count = await reader.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
            if (count == 0)
            {
                break;
            }
            if (output.Length < MaximumDiagnosticCharacters)
            {
                output.Append(buffer, 0, Math.Min(count, MaximumDiagnosticCharacters - output.Length));
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
                // The owned process is already being torn down.
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
            // Preserve the cancellation or timeout that owns this teardown.
        }
    }

    private static void DeleteOwnedWorkDirectory(string workRoot)
    {
        try
        {
            var cacheRoot = Path.GetFullPath(ArchiveLiteDataPaths.NameIndexCache)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var resolved = Path.GetFullPath(workRoot);
            if (resolved.StartsWith(cacheRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                && Directory.Exists(resolved))
            {
                Directory.Delete(resolved, recursive: true);
            }
        }
        catch
        {
            // Bounded cache maintenance can remove a stale work folder later.
        }
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

    private sealed record CatalogueBuildState(
        ArchiveItemNameIndex NameIndex,
        ArchiveItemCatalog ItemCatalog);
}
