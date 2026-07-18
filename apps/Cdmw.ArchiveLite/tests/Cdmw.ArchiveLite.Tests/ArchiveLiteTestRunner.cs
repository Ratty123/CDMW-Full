using System.Security.Cryptography;
using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;
using Cdmw.ArchiveLite.Core;

namespace Cdmw.ArchiveLite.Tests;

internal static class ArchiveLiteTestRunner
{
    public static async Task<int> RunAsync()
    {
        var tests = new (string Name, Func<Task> Run)[]
        {
            ("protocol serializes snake-case messages", TestProtocolAsync),
            ("English, German, and Spanish resources have identical keys", TestLocalizationResourcesAsync),
            ("read-only WPF text bindings are explicitly one-way", TestReadOnlyWpfBindingsAsync),
            ("export paths reject traversal and roots", TestExportPathPolicyAsync),
            ("isolated cache maintenance is bounded and deterministic", TestCacheMaintenanceAsync),
            ("UTF-8, UTF-16, and Latin-1 text decode without Python codecs", TestTextDecodingAsync),
            ("native archive ABI scans and decodes synthetic PAMT/PAZ", TestNativeArchiveAsync),
            ("archive query, preview, and text search are read-only", TestArchiveServicesAsync),
            ("archive export is contained, atomic, and manifested", TestArchiveExportAsync),
            ("named-pipe worker opens and queries an archive", TestWorkerBoundaryAsync),
        };
        var failures = new List<string>();
        foreach (var test in tests)
        {
            try
            {
                await test.Run().ConfigureAwait(false);
                Console.WriteLine($"PASS: {test.Name}");
            }
            catch (Exception exception)
            {
                failures.Add($"{test.Name}: {exception}");
                Console.Error.WriteLine($"FAIL: {test.Name}: {exception.Message}");
            }
        }
        if (failures.Count == 0)
        {
            Console.WriteLine($"CDMW Archive Lite focused tests: PASS ({tests.Length} scenarios)");
            return 0;
        }
        Console.Error.WriteLine($"CDMW Archive Lite focused tests: FAIL ({failures.Count}/{tests.Length})");
        return 1;
    }

    private static Task TestProtocolAsync()
    {
        var message = WorkerProtocol.Request(Guid.Parse("11111111-1111-1111-1111-111111111111"), 7, WorkerProtocol.Ping, new PingRequest("1.0"));
        var json = System.Text.Json.JsonSerializer.Serialize(message, WorkerProtocol.JsonOptions);
        Require(json.Contains("\"protocol_version\":1", StringComparison.Ordinal), "protocol_version is not snake case");
        Require(WorkerProtocol.ReadPayload<PingRequest>(message)?.ClientVersion == "1.0", "protocol payload did not round-trip");
        return Task.CompletedTask;
    }

    private static Task TestLocalizationResourcesAsync()
    {
        var resourceRoot = Path.Combine(
            FindRepositoryRoot(),
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.App",
            "Resources");
        var resources = new[] { "Strings.resx", "Strings.de.resx", "Strings.es.resx" }
            .Select(filename => System.Xml.Linq.XDocument.Load(Path.Combine(resourceRoot, filename)))
            .Select(document => document.Root!.Elements("data").ToDictionary(
                element => (string)element.Attribute("name")!,
                element => (string?)element.Element("value") ?? string.Empty,
                StringComparer.Ordinal))
            .ToArray();
        var expected = resources[0].Keys.Order(StringComparer.Ordinal).ToArray();
        foreach (var resource in resources)
        {
            Require(resource.Keys.Order(StringComparer.Ordinal).SequenceEqual(expected), "localized resource keys do not match");
            Require(resource.Values.All(static value => !string.IsNullOrWhiteSpace(value)), "localized resource contains an empty value");
        }
        return Task.CompletedTask;
    }

    private static Task TestReadOnlyWpfBindingsAsync()
    {
        var windowPath = Path.Combine(
            FindRepositoryRoot(),
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.App",
            "MainWindow.xaml");
        var document = System.Xml.Linq.XDocument.Load(windowPath);
        var readOnlyTextBindings = document
            .Descendants()
            .Where(element => element.Name.LocalName == "TextBox")
            .Where(element => string.Equals((string?)element.Attribute("IsReadOnly"), "True", StringComparison.OrdinalIgnoreCase))
            .Select(element => (string?)element.Attribute("Text"))
            .Where(static value => value?.StartsWith("{Binding", StringComparison.Ordinal) == true)
            .ToArray();
        Require(readOnlyTextBindings.Length > 0, "MainWindow has no read-only TextBox binding to validate");
        Require(
            readOnlyTextBindings.All(static binding => binding!.Contains("Mode=OneWay", StringComparison.Ordinal)),
            "a read-only TextBox uses WPF's default TwoWay Text binding");
        return Task.CompletedTask;
    }

    private static Task TestExportPathPolicyAsync()
    {
        Require(ExportPathPolicy.NormalizeVirtualPath("folder/file.txt") == "folder/file.txt", "safe path changed");
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("../escape.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("C:/escape.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("//server/share.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("folder/bad. "));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("folder/CON.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("LPT1/report.txt"));
        return Task.CompletedTask;
    }

    private static async Task TestCacheMaintenanceAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cdmw-archive-lite-cache-test-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            for (var index = 0; index < 3; index++)
            {
                var path = Path.Combine(root, $"cache-{index}.bin");
                await File.WriteAllBytesAsync(path, new byte[1_000]).ConfigureAwait(false);
                File.SetLastWriteTimeUtc(path, DateTime.UtcNow.AddHours(index - 4));
            }
            var result = ArchiveLiteCacheMaintenance.Prune(root, 1_500);
            Require(result.BytesBefore == 3_000, "cache size accounting is wrong");
            Require(result.BytesAfter <= 1_350 && result.FilesRemoved == 2, "cache did not prune to its low-water mark");
            Require(File.Exists(Path.Combine(root, "cache-2.bin")), "cache pruning did not retain the newest entry");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
    }

    private static Task TestTextDecodingAsync()
    {
        var utf16 = Encoding.Unicode.GetPreamble().Concat(Encoding.Unicode.GetBytes("Crimson UTF-16")).ToArray();
        Require(TextDecoding.LooksTextual(utf16), "UTF-16 text was classified as binary");
        Require(TextDecoding.Decode(utf16) == "Crimson UTF-16", "UTF-16 decode is wrong");
        var latin1 = new byte[] { (byte)'C', (byte)'a', (byte)'f', 0xE9 };
        Require(TextDecoding.Decode(latin1) == "Café", "Latin-1 fallback decode is wrong");
        return Task.CompletedTask;
    }

    private static async Task TestNativeArchiveAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var native = new NativeArchiveCore();
        native.EnsureCompatible();
        var singlePamtFingerprint = await ArchiveFingerprint.ComputeAsync(fixture.Pamt, CancellationToken.None).ConfigureAwait(false);
        Require(singlePamtFingerprint.SourceFiles.Contains(fixture.Paz, StringComparer.OrdinalIgnoreCase), "single-PAMT fingerprint omitted its PAZ source");
        Require(singlePamtFingerprint.SourceFiles.Contains(fixture.Pathc, StringComparer.OrdinalIgnoreCase), "single-PAMT fingerprint omitted PATHC metadata");
        var indexPath = Path.Combine(fixture.Root, "native-index.ali");
        var count = native.BuildIndex(fixture.Root, indexPath);
        Require(count == 4, "native index count is wrong");
        using var index = ArchiveIndex.Open(indexPath);
        Require(index.EntryCount == 4, "managed index count is wrong");
        var entries = Enumerable.Range(0, 4).Select(id => index.ReadEntry(id)).ToArray();
        var text = entries.Single(entry => entry.Path == "text/hello.txt");
        var decoded = native.Decode(text);
        Require(Encoding.UTF8.GetString(decoded.Bytes).Contains("Crimson", StringComparison.Ordinal), "raw text decode failed");
        var lz4 = entries.Single(entry => entry.Path == "materials/sample.material");
        var lz4Decoded = native.Decode(lz4);
        Require(Encoding.UTF8.GetString(lz4Decoded.Bytes) == "material alpha", "LZ4 text decode failed");
        Require(lz4Decoded.Note == "LZ4", "LZ4 diagnostic note is missing");
        var partialDds = native.Decode(entries.Single(entry => entry.Path == "texture/test.dds"));
        Require(partialDds.Bytes.Length == 0x88 && partialDds.Bytes.AsSpan(0, 4).SequenceEqual("DDS "u8), "managed PATHC DDS decode failed");
        Require(partialDds.Note == "PartialDDS+PATHC", "managed PATHC DDS diagnostic note is missing");
    }

    private static async Task TestArchiveServicesAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var beforePamt = await Sha256Async(fixture.Pamt).ConfigureAwait(false);
        var beforePaz = await Sha256Async(fixture.Paz).ConfigureAwait(false);
        var beforePathc = await Sha256Async(fixture.Pathc).ConfigureAwait(false);
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native);
        var openProgress = new List<ProgressUpdate>();
        var opened = await sessions.OpenAsync(
            new OpenArchiveRequest(fixture.Root, true),
            CancellationToken.None,
            update =>
            {
                openProgress.Add(update);
                return Task.CompletedTask;
            }).ConfigureAwait(false);
        Require(openProgress.Any(update => update.Phase == "fingerprint"), "archive open did not publish fingerprint progress");
        Require(openProgress.Any(update => update.Phase == "index_build"), "archive open did not publish index-build progress");
        Require(openProgress.Any(update => update.Phase == "validate"), "archive open did not publish validation progress");
        var queries = new ArchiveQueryService(sessions);
        var directPage = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, PageSize: 2),
            8,
            CancellationToken.None).ConfigureAwait(false);
        Require(directPage.TotalMatches == 4 && directPage.Entries.Count == 2, "direct flat-path page is wrong");
        Require(directPage.Folders.Count == 0 && directPage.Categories.Count == 0, "direct flat-path page performed navigation aggregation");
        var page = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, Extensions: [".txt", ".material"]),
            9,
            CancellationToken.None).ConfigureAwait(false);
        Require(page.TotalMatches == 2, "archive extension query count is wrong");
        Require(page.Generation == 9, "query generation was not retained");
        var sortedPage = await queries.QueryAsync(
            new ArchiveQuerySpec(
                opened.SessionId,
                SortField: ArchiveSortField.OriginalSize,
                SortDescending: true,
                PageSize: 2),
            10,
            CancellationToken.None).ConfigureAwait(false);
        Require(sortedPage.Entries.Count == 2, "bounded sorted page size is wrong");
        Require(sortedPage.Entries[0].OriginalSize >= sortedPage.Entries[1].OriginalSize, "server-side descending sort is wrong");
        var reversePathPage = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, SortDescending: true, PageSize: 2),
            11,
            CancellationToken.None).ConfigureAwait(false);
        Require(StringComparer.OrdinalIgnoreCase.Compare(reversePathPage.Entries[0].Path, reversePathPage.Entries[1].Path) >= 0, "descending path paging is wrong");
        var previewService = new ArchivePreviewService(sessions, native);
        var textEntry = page.Entries.Single(entry => entry.Extension == ".txt");
        var preview = await previewService.BuildAsync(
            new PreviewRequest(opened.SessionId, textEntry.EntryId),
            CancellationToken.None).ConfigureAwait(false);
        Require(preview.Kind == PreviewKind.Text && preview.Text?.Contains("Crimson", StringComparison.Ordinal) == true, "text preview is wrong");
        var imagePage = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, Extensions: [".dds"]),
            12,
            CancellationToken.None).ConfigureAwait(false);
        var imagePreview = await previewService.BuildAsync(
            new PreviewRequest(opened.SessionId, imagePage.Entries.Single().EntryId),
            CancellationToken.None).ConfigureAwait(false);
        Require(imagePreview.Kind == PreviewKind.Image && imagePreview.ArtifactPath is not null, "DDS preview artifact is missing");
        var imageBytes = await File.ReadAllBytesAsync(imagePreview.ArtifactPath!).ConfigureAwait(false);
        Require(imageBytes.AsSpan(0, 4).SequenceEqual("DDS "u8), "DDS preview artifact is not reconstructed");
        var search = new TextSearchService(sessions, native);
        var result = await search.SearchAsync(
            new TextSearchRequest(
                TextSearchSourceKind.Archive,
                opened.SessionId,
                "crimson",
                false,
                false,
                null,
                [".txt"]),
            CancellationToken.None).ConfigureAwait(false);
        Require(result.Matches.Count == 1, "literal archive search did not find one match");
        Require(result.Matches[0].Line == 1, "search line number is wrong");
        var regex = await search.SearchAsync(
            new TextSearchRequest(
                TextSearchSourceKind.Archive,
                opened.SessionId,
                "line\\s+2",
                true,
                false,
                null,
                [".txt"]),
            CancellationToken.None).ConfigureAwait(false);
        Require(regex.Matches.Count == 1, "regex archive search did not find one match");
        Require(await Sha256Async(fixture.Pamt).ConfigureAwait(false) == beforePamt, "PAMT changed during read-only services");
        Require(await Sha256Async(fixture.Paz).ConfigureAwait(false) == beforePaz, "PAZ changed during read-only services");
        Require(await Sha256Async(fixture.Pathc).ConfigureAwait(false) == beforePathc, "PATHC changed during read-only services");
    }

    private static async Task TestArchiveExportAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native);
        var opened = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root, true), CancellationToken.None).ConfigureAwait(false);
        var queries = new ArchiveQueryService(sessions);
        var page = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, PathText: "hello"),
            1,
            CancellationToken.None).ConfigureAwait(false);
        var exportRoot = fixture.OutputRoot;
        var service = new ArchiveExportService(sessions, queries, native);
        await RequireThrowsAsync<InvalidDataException>(() => service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.RawEntries,
                fixture.Root,
                [page.Entries.Single().EntryId],
                null),
            null,
            CancellationToken.None)).ConfigureAwait(false);
        await RequireThrowsAsync<NotSupportedException>(() => service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.Obj,
                exportRoot,
                [page.Entries.Single().EntryId],
                null),
            null,
            CancellationToken.None)).ConfigureAwait(false);
        var result = await service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.RawEntries,
                exportRoot,
                [page.Entries.Single().EntryId],
                null),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(result.Exported == 1 && result.Failed == 0, "archive export result is wrong");
        var output = Path.Combine(exportRoot, "text", "hello.txt");
        Require(File.Exists(output), "archive export did not preserve the virtual path");
        Require(await File.ReadAllTextAsync(output).ConfigureAwait(false) == "Hello Crimson\nline 2", "archive export bytes are wrong");
        Require(result.ManifestPath is not null && File.Exists(result.ManifestPath), "JSON manifest was not written");

        var collision = await service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.RawEntries,
                exportRoot,
                [page.Entries.Single().EntryId],
                null,
                CollisionPolicy: ExportCollisionPolicy.Skip),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(collision.Skipped == 1, "skip collision policy did not preserve the destination");

        var looseRoot = Path.Combine(fixture.Root, "loose-source");
        Directory.CreateDirectory(Path.Combine(looseRoot, "notes"));
        await File.WriteAllTextAsync(Path.Combine(looseRoot, "notes", "result.txt"), "Crimson loose result").ConfigureAwait(false);
        var textSearch = new TextSearchService(sessions, native);
        var looseSearch = await textSearch.SearchAsync(
            new TextSearchRequest(
                TextSearchSourceKind.LooseFolder,
                looseRoot,
                "loose",
                false,
                false,
                null,
                [".txt"]),
            CancellationToken.None).ConfigureAwait(false);
        Require(looseSearch.Matches.Count == 1, "loose-folder search did not find its text file");
        await RequireThrowsAsync<InvalidDataException>(() => service.ExportAsync(
            new ExportPlanRequest(
                null,
                ExportKind.RawEntries,
                Path.Combine(looseRoot, "unsafe-output"),
                [],
                [looseSearch.Matches[0].Path],
                looseRoot),
            null,
            CancellationToken.None)).ConfigureAwait(false);
        var looseExport = await service.ExportAsync(
            new ExportPlanRequest(
                null,
                ExportKind.RawEntries,
                Path.Combine(fixture.OutputRoot, "loose-search"),
                [],
                [looseSearch.Matches[0].Path],
                looseRoot),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(looseExport.Exported == 1, "loose search-result export failed");
        await using var looseManifestStream = File.OpenRead(looseExport.ManifestPath!);
        var looseManifest = await JsonSerializer.DeserializeAsync<ArchiveLiteManifest>(
            looseManifestStream,
            WorkerProtocol.JsonOptions).ConfigureAwait(false);
        Require(looseManifest?.LooseFiles.Count == 1, "loose export manifest did not record its source");
    }

    private static async Task TestWorkerBoundaryAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var beforePamt = await Sha256Async(fixture.Pamt).ConfigureAwait(false);
        var beforePaz = await Sha256Async(fixture.Paz).ConfigureAwait(false);
        var configuration = AppContext.BaseDirectory.Contains($"{Path.DirectorySeparatorChar}Release{Path.DirectorySeparatorChar}", StringComparison.OrdinalIgnoreCase)
            ? "Release"
            : "Debug";
        var repositoryRoot = FindRepositoryRoot();
        var workerPath = Path.Combine(
            repositoryRoot,
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.Worker",
            "bin",
            configuration,
            "net10.0-windows",
            "win-x64",
            "CdmwArchiveLite.Worker.exe");
        Require(File.Exists(workerPath), $"worker output was not found: {workerPath}");

        var pipeName = $"cdmw-archive-lite-test-{Environment.ProcessId}-{Guid.NewGuid():N}";
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = workerPath,
            Arguments = $"--pipe \"{pipeName}\"",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
            WorkingDirectory = Path.GetDirectoryName(workerPath)!,
        }) ?? throw new InvalidOperationException("worker test process could not be started");
        var stderrTask = process.StandardError.ReadToEndAsync();
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        try
        {
            await using var pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.WriteThrough);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
            await pipe.ConnectAsync(timeout.Token).ConfigureAwait(false);
            using var reader = new StreamReader(pipe, new UTF8Encoding(false), false, 16 * 1024, leaveOpen: true);
            using var writer = new StreamWriter(pipe, new UTF8Encoding(false), 16 * 1024, leaveOpen: true) { AutoFlush = true, NewLine = "\n" };

            var ping = await ExchangeAsync(writer, reader, WorkerProtocol.Ping, 1, new PingRequest("test"), timeout.Token).ConfigureAwait(false);
            var pingResult = WorkerProtocol.ReadPayload<PingResult>(ping);
            Require(pingResult?.ProtocolVersion == WorkerProtocol.Version, "worker ping protocol version is wrong");

            var workerProgress = new List<ProgressUpdate>();
            var openedMessage = await ExchangeAsync(
                writer,
                reader,
                WorkerProtocol.OpenArchive,
                2,
                new OpenArchiveRequest(fixture.Root, true),
                timeout.Token,
                workerProgress).ConfigureAwait(false);
            var opened = WorkerProtocol.ReadPayload<OpenArchiveResult>(openedMessage)
                ?? throw new InvalidDataException("worker open response is missing");
            Require(opened.EntryCount == 4, "worker archive count is wrong");
            Require(workerProgress.Any(update => update.Phase == "fingerprint"), "worker did not forward archive-open progress");

            var queryMessage = await ExchangeAsync(
                writer,
                reader,
                WorkerProtocol.QueryArchive,
                3,
                new ArchiveQuerySpec(opened.SessionId, PathText: "hello"),
                timeout.Token).ConfigureAwait(false);
            var page = WorkerProtocol.ReadPayload<ArchivePageResult>(queryMessage)
                ?? throw new InvalidDataException("worker query response is missing");
            Require(page.TotalMatches == 1 && page.Entries.Single().Path == "text/hello.txt", "worker query result is wrong");

            await ExchangeAsync(writer, reader, WorkerProtocol.Shutdown, 4, new { }, timeout.Token).ConfigureAwait(false);
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
            Require(process.ExitCode == 0, "worker did not exit cleanly");
        }
        catch (Exception exception)
        {
            var stderr = process.HasExited ? await stderrTask.ConfigureAwait(false) : string.Empty;
            throw new InvalidOperationException($"Worker boundary failed. {stderr}", exception);
        }
        finally
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync().ConfigureAwait(false);
            _ = await stderrTask.ConfigureAwait(false);
            _ = await stdoutTask.ConfigureAwait(false);
        }

        Require(await Sha256Async(fixture.Pamt).ConfigureAwait(false) == beforePamt, "worker changed the PAMT source");
        Require(await Sha256Async(fixture.Paz).ConfigureAwait(false) == beforePaz, "worker changed the PAZ source");
    }

    private static async Task<WorkerMessage> ExchangeAsync<T>(
        StreamWriter writer,
        StreamReader reader,
        string kind,
        long generation,
        T payload,
        CancellationToken cancellationToken,
        ICollection<ProgressUpdate>? progress = null)
    {
        var request = WorkerProtocol.Request(Guid.NewGuid(), generation, kind, payload);
        var json = JsonSerializer.Serialize(request, WorkerProtocol.JsonOptions);
        await writer.WriteLineAsync(json.AsMemory(), cancellationToken).ConfigureAwait(false);
        while (true)
        {
            var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false)
                ?? throw new IOException("worker disconnected before replying");
            Require(Encoding.UTF8.GetByteCount(line) <= WorkerProtocol.MaximumMessageBytes, "worker response exceeds the protocol limit");
            var response = JsonSerializer.Deserialize<WorkerMessage>(line, WorkerProtocol.JsonOptions)
                ?? throw new InvalidDataException("worker response could not be decoded");
            if (response.RequestId != request.RequestId)
            {
                continue;
            }
            if (response.Status == WorkerMessageStatus.Progress)
            {
                if (WorkerProtocol.ReadPayload<ProgressUpdate>(response) is { } update)
                {
                    progress?.Add(update);
                }
                continue;
            }
            if (response.Status == WorkerMessageStatus.Started)
            {
                continue;
            }
            if (response.Status == WorkerMessageStatus.Error)
            {
                throw new InvalidOperationException(response.Error?.Message ?? "worker request failed");
            }
            Require(response.Status == WorkerMessageStatus.Result, $"unexpected worker terminal status: {response.Status}");
            return response;
        }
    }

    private static string FindRepositoryRoot()
    {
        foreach (var start in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
        {
            var current = new DirectoryInfo(start);
            while (current is not null)
            {
                if (Directory.Exists(Path.Combine(current.FullName, "apps", "Cdmw.ArchiveLite"))) return current.FullName;
                current = current.Parent;
            }
        }
        throw new DirectoryNotFoundException("repository root could not be located");
    }

    private static async Task<string> Sha256Async(string path)
    {
        await using var stream = File.OpenRead(path);
        return Convert.ToHexString(await SHA256.HashDataAsync(stream).ConfigureAwait(false));
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void RequireThrows<TException>(Action action) where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException($"Expected {typeof(TException).Name} was not thrown.");
    }

    private static async Task RequireThrowsAsync<TException>(Func<Task> action) where TException : Exception
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException($"Expected {typeof(TException).Name} was not thrown.");
    }
}
