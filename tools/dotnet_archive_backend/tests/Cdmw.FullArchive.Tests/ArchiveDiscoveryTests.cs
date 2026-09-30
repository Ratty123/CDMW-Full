using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class ArchiveDiscoveryTests
{
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
            var modPamt = Path.Combine(fixture.Root, "Cdmods", "some_mod", "0009", "0.pamt");
            Directory.CreateDirectory(Path.GetDirectoryName(modPamt)!);
            File.Copy(fixture.Pamt, modPamt);
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
                    && !relativeSource.StartsWith("cdmods" + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase),
                    "native scan retained an ignored archive source");
            }

            var current = await ArchiveFingerprint.ComputeAsync(fixture.Root, CancellationToken.None).ConfigureAwait(false);
            Require(current.Value == liveFingerprint.Value && current.SourceFiles.SequenceEqual(liveFingerprint.SourceFiles),
                "backup sources changed the live archive fingerprint");
            await File.AppendAllTextAsync(backupPamt, "changed backup").ConfigureAwait(false);
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
            var backupPamt = CopyBackupIndex(fixture, "backups");
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
