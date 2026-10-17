using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class ArchiveDiscoveryTests
{
    public static async Task CustomFoldersAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = Path.Combine(Path.GetTempPath(), $"cdmw-custom-discovery-{Guid.NewGuid():N}");
        var cache = new ArchiveCacheStore(cacheRoot);
        try
        {
            var ignoredDirectory = Path.Combine(fixture.Root, "Extras", "Äldre");
            var siblingDirectory = ignoredDirectory + "2";
            foreach (var directory in new[] { ignoredDirectory, siblingDirectory })
            {
                Directory.CreateDirectory(directory);
                File.Copy(fixture.Pamt, Path.Combine(directory, "0.pamt"));
                File.Copy(fixture.Paz, Path.Combine(directory, "0.paz"));
            }
            var native = new NativeArchiveCore();
            using var sessions = new ArchiveSessionManager(native, cache);
            var original = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None).ConfigureAwait(false);
            Require(original.EntryCount == 12, "fixture must initially include all three sources");
            string[] ignored = ["extras\\äLDRE"];
            var request = JsonSerializer.Deserialize<OpenArchiveRequest>(
                JsonSerializer.Serialize(new OpenArchiveRequest(fixture.Root, IgnoredFolders: ignored), WorkerProtocol.JsonOptions), WorkerProtocol.JsonOptions)!;
            await File.WriteAllBytesAsync(Path.Combine(ignoredDirectory, "0.pamt"), [0]).ConfigureAwait(false);
            var filtered = await sessions.OpenAsync(request, CancellationToken.None).ConfigureAwait(false);
            Require(!filtered.CacheHit && filtered.EntryCount == 8, "custom folder change reused an unfiltered catalogue or hid a similar sibling");
            var sources = ArchiveFingerprint.DiscoverSourceFiles(fixture.Root, ignored);
            Require(!sources.Any(path => Path.GetDirectoryName(path) == ignoredDirectory), "ignored subtree entered fingerprint sources");
            Require(sources.Contains(Path.Combine(siblingDirectory, "0.pamt")), "similar sibling was incorrectly excluded");
            var session = sessions.GetRequired(filtered.SessionId);
            for (long id = 0; id < filtered.EntryCount; id++)
                Require(Path.GetDirectoryName(session.ReadEntry(id).SourcePamt) != ignoredDirectory, "native scan included a custom ignored source");
            await File.WriteAllBytesAsync(Path.Combine(ignoredDirectory, "0.pamt"), [1, 2]).ConfigureAwait(false);
            var warm = await sessions.OpenAsync(request, CancellationToken.None).ConfigureAwait(false);
            Require(warm.CacheHit, "changes inside an ignored subtree invalidated the catalogue");
            var health = await cache.InspectAsync(fixture.Root, CancellationToken.None, ignoredFolders: ignored).ConfigureAwait(false);
            Require(health.State == "current", "cache health did not honor custom exclusions");
            File.Copy(fixture.Pamt, Path.Combine(ignoredDirectory, "0.pamt"), overwrite: true);
            var restored = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None).ConfigureAwait(false);
            Require(!restored.CacheHit && restored.EntryCount == 12, "removing an exclusion did not restore its archives");
            foreach (var invalid in new[] { ".", "../outside", "/outside", "C:/outside", "Extras/*", "Extras/../0009" })
            {
                var rejected = false;
                try { ArchiveFingerprint.DiscoverSourceFiles(fixture.Root, [invalid]); }
                catch (ArgumentException) { rejected = true; }
                Require(rejected, "invalid custom folder path was accepted");
            }
            using var cancellation = new CancellationTokenSource();
            var cancelled = false;
            var cancelledIndex = Path.Combine(cacheRoot, "cancelled.ali");
            try
            {
                native.BuildIndex(fixture.Root, cancelledIndex, _ => cancellation.Cancel(), cancellation.Token,
                    [fixture.Pamt]);
            }
            catch (OperationCanceledException) { cancelled = true; }
            Require(cancelled && !File.Exists(cancelledIndex), "filtered native build ignored cancellation or published a partial index");
        }
        finally
        {
            await cache.WaitForMaintenanceAsync(CancellationToken.None).ConfigureAwait(false);
            if (Directory.Exists(cacheRoot)) Directory.Delete(cacheRoot, recursive: true);
        }
    }

    public static async Task ScanAndExportAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = Path.Combine(Path.GetTempPath(), $"cdmw-backup-discovery-{Guid.NewGuid():N}");
        try
        {
            var overlay = Path.Combine(fixture.Root, "0036");
            Directory.CreateDirectory(overlay);
            File.Copy(fixture.Pamt, Path.Combine(overlay, "0.pamt"));
            File.Copy(fixture.Paz, Path.Combine(overlay, "0.paz"));
            var liveFingerprint = await ArchiveFingerprint.ComputeAsync(fixture.Root, CancellationToken.None).ConfigureAwait(false);

            var backupPamt = CopyBackupIndex(fixture, "BaCkUpS");
            var crimsonForgePamt = Path.Combine(fixture.Root, "CrImSoNfOrGe_BaCkUpS", "20261002_173535", "0.pamt");
            Directory.CreateDirectory(Path.GetDirectoryName(crimsonForgePamt)!);
            File.Copy(fixture.Pamt, crimsonForgePamt);
            Require(!File.Exists(Path.ChangeExtension(crimsonForgePamt, ".paz")), "CrimsonForge backup fixture must have no PAZ payload");
            Require(ArchiveFingerprint.DiscoverSourceFiles(crimsonForgePamt).Contains(crimsonForgePamt),
                "an explicitly selected CrimsonForge backup index cannot be inspected");
            var modPamt = Path.Combine(fixture.Root, "Cdmods", "some_mod", "0009", "0.pamt");
            Directory.CreateDirectory(Path.GetDirectoryName(modPamt)!);
            File.Copy(fixture.Pamt, modPamt);
            var generationPamt = Path.Combine(fixture.Root, ".CdMw", "virtual-loader", "generations", "previous", "files", "0041", "0.pamt");
            Directory.CreateDirectory(Path.GetDirectoryName(generationPamt)!);
            File.Copy(fixture.Pamt, generationPamt);
            File.Copy(fixture.Paz, Path.ChangeExtension(generationPamt, ".paz"));
            var generationMetadata = Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(generationPamt)!)!, "meta");
            Directory.CreateDirectory(generationMetadata);
            await File.WriteAllTextAsync(Path.Combine(generationMetadata, "0.pathc"), "saved registry").ConfigureAwait(false);
            Require(ArchiveFingerprint.DiscoverSourceFiles(generationPamt).Contains(generationPamt),
                "an explicitly selected internal index cannot be inspected");
            await File.WriteAllTextAsync(Path.Combine(Path.GetDirectoryName(backupPamt)!, "0.pathc"), "backup metadata").ConfigureAwait(false);
            Require(!File.Exists(Path.ChangeExtension(backupPamt, ".paz")), "backup fixture must have no PAZ payload");

            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var handle = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None).ConfigureAwait(false);
            var exports = new ArchiveExportService(
                sessions, new ArchiveQueryService(sessions), new ArchiveLookupService(sessions, cache, native), native);
            var exported = await exports.ExportAsync(
                new ArchiveExportRequest(handle.SessionId, ArchiveExportSelectionKind.Folder, fixture.OutputRoot,
                    FolderPath: "text", CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite),
                CancellationToken.None).ConfigureAwait(false);
            Require(exported.Failed == 0 && exported.Exported == 1, "live folder extraction failed with a backup vault present");
            Require(await File.ReadAllTextAsync(Path.Combine(fixture.OutputRoot, "text", "hello.txt")).ConfigureAwait(false)
                == "Hello Crimson\nline 2", "folder extraction did not retain the live payload");
            Require(handle.EntryCount == 8, "backup or mod-library indexes entered the native catalogue, or a live overlay was omitted");
            var session = sessions.GetRequired(handle.SessionId);
            for (long id = 0; id < handle.EntryCount; id++)
            {
                var relativeSource = Path.GetRelativePath(fixture.Root, session.ReadEntry(id).SourcePamt);
                Require(!relativeSource.StartsWith("backups" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                    && !relativeSource.StartsWith("cdmods" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                    && !relativeSource.StartsWith("crimsonforge_backups" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                    && !relativeSource.StartsWith(".cdmw" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase),
                    "native scan retained an ignored archive source");
            }

            var current = await ArchiveFingerprint.ComputeAsync(fixture.Root, CancellationToken.None).ConfigureAwait(false);
            Require(current.Value == liveFingerprint.Value && current.SourceFiles.SequenceEqual(liveFingerprint.SourceFiles),
                "backup sources changed the live archive fingerprint");
            await File.AppendAllTextAsync(backupPamt, "changed backup").ConfigureAwait(false);
            await File.AppendAllTextAsync(crimsonForgePamt, "changed CrimsonForge backup").ConfigureAwait(false);
            await File.AppendAllTextAsync(generationPamt, "changed saved generation").ConfigureAwait(false);
            var changedBackup = await ArchiveFingerprint.ComputeAsync(fixture.Root, CancellationToken.None).ConfigureAwait(false);
            Require(changedBackup.Value == liveFingerprint.Value, "changing a backup invalidated the live archive cache");
        }
        finally
        {
            if (Directory.Exists(cacheRoot)) Directory.Delete(cacheRoot, recursive: true);
        }
    }

    public static async Task ExistingBackupCacheAsync()
    {
        foreach (var directoryName in new[] { "backups", ".cdmw", "crimsonforge_backups" })
        {
            await ExistingIgnoredCacheAsync(directoryName).ConfigureAwait(false);
        }
    }

    private static async Task ExistingIgnoredCacheAsync(string directoryName)
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = Path.Combine(Path.GetTempPath(), $"cdmw-backup-cache-{Guid.NewGuid():N}");
        try
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            string generationPath;
            using (var sessions = new ArchiveSessionManager(native, cache))
            {
                var handle = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None).ConfigureAwait(false);
                generationPath = sessions.GetRequired(handle.SessionId).GenerationPath;
            }

            // Recreate a previously published catalogue that resolves its entries to the vault.
            var backupPamt = CopyBackupIndex(fixture, directoryName);
            var entryCount = native.BuildIndex(backupPamt, Path.Combine(generationPath, "archive.ali"));
            var oldSources = Directory.EnumerateFiles(fixture.Root, "*", SearchOption.AllDirectories)
                .Where(static path => path.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase)
                    || path.EndsWith(".paz", StringComparison.OrdinalIgnoreCase)
                    || path.EndsWith(".pathc", StringComparison.OrdinalIgnoreCase))
                .Order(StringComparer.OrdinalIgnoreCase).ToArray();
            var oldFingerprint = await FingerprintIncludingBackupsAsync(fixture.Root, oldSources).ConfigureAwait(false);
            var manifestPath = Path.Combine(generationPath, "manifest.json");
            var manifest = JsonSerializer.Deserialize<ArchiveGenerationManifest>(
                await File.ReadAllTextAsync(manifestPath).ConfigureAwait(false), WorkerProtocol.JsonOptions)!;
            manifest = manifest with
            {
                Fingerprint = oldFingerprint,
                EntryCount = entryCount,
                SourceFiles = oldSources.Select(path => new ArchiveSourceReference(
                    Path.GetRelativePath(fixture.Root, path).Replace('\\', '/'),
                    new FileInfo(path).Length, File.GetLastWriteTimeUtc(path).Ticks)).ToArray(),
            };
            await File.WriteAllTextAsync(manifestPath, JsonSerializer.Serialize(manifest, WorkerProtocol.JsonOptions)).ConfigureAwait(false);
            var pointerPath = Path.Combine(cache.CatalogueRoot, ArchiveCacheStore.DeriveRootId(fixture.Root), "current.json");
            var pointer = JsonSerializer.Deserialize<ArchiveCurrentPointer>(
                await File.ReadAllTextAsync(pointerPath).ConfigureAwait(false), WorkerProtocol.JsonOptions)!;
            await File.WriteAllTextAsync(pointerPath,
                JsonSerializer.Serialize(pointer with { Fingerprint = oldFingerprint }, WorkerProtocol.JsonOptions)).ConfigureAwait(false);

            var health = await cache.InspectAsync(fixture.Root, CancellationToken.None).ConfigureAwait(false);
            Require(health.State == "stale", "a catalogue fingerprinted with backup sources was not marked stale");
            using var reopenedSessions = new ArchiveSessionManager(native, cache);
            var rebuilt = await reopenedSessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None).ConfigureAwait(false);
            Require(!rebuilt.CacheHit && rebuilt.EntryCount == 4, "the backup catalogue was not rebuilt automatically");
            var rebuiltSession = reopenedSessions.GetRequired(rebuilt.SessionId);
            Require(rebuiltSession.GenerationPath != generationPath, "the polluted generation was reused");
            for (long id = 0; id < rebuilt.EntryCount; id++)
            {
                Require(rebuiltSession.ReadEntry(id).SourcePamt.Equals(fixture.Pamt, StringComparison.OrdinalIgnoreCase),
                    "the rebuilt catalogue still resolves to a backup index");
            }
            Require(Encoding.UTF8.GetString(native.Decode(rebuiltSession.ReadEntry(2)).Bytes) == "Hello Crimson\nline 2",
                "the rebuilt catalogue cannot decode the live archive");
        }
        finally
        {
            if (Directory.Exists(cacheRoot)) Directory.Delete(cacheRoot, recursive: true);
        }
    }

    private static string CopyBackupIndex(SyntheticArchiveFixture fixture, string directoryName)
    {
        var pamt = Path.Combine(fixture.Root, directoryName, "vault", "5c03e5214c46a260", "files", "0009", "0.pamt");
        Directory.CreateDirectory(Path.GetDirectoryName(pamt)!);
        File.Copy(fixture.Pamt, pamt);
        return pamt;
    }

    private static async Task<string> FingerprintIncludingBackupsAsync(string root, IEnumerable<string> sources)
    {
        // Preserve the former fingerprint format to reproduce an existing cache after upgrade.
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var metadata = new byte[16];
        foreach (var path in sources)
        {
            var info = new FileInfo(path);
            hash.AppendData(Encoding.UTF8.GetBytes(Path.GetRelativePath(root, path).Replace('\\', '/').ToLowerInvariant()));
            BinaryPrimitives.WriteInt64LittleEndian(metadata, info.Length);
            BinaryPrimitives.WriteInt64LittleEndian(metadata.AsSpan(8), info.LastWriteTimeUtc.Ticks);
            hash.AppendData(metadata);
            if (path.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase) || path.EndsWith(".pathc", StringComparison.OrdinalIgnoreCase))
            {
                hash.AppendData(await File.ReadAllBytesAsync(path).ConfigureAwait(false));
            }
        }
        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
