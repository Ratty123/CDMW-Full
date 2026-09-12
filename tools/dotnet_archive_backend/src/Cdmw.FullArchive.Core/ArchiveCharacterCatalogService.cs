using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveCharacterCatalogService(ArchiveSessionManager sessions, NativeArchiveCore native)
{
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _gates = new(StringComparer.Ordinal);
    private static readonly JsonSerializerOptions CacheOptions = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    public async Task<BuildCharacterCatalogResult> BuildAsync(BuildCharacterCatalogRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var session = sessions.GetRequired(request.SessionId);
        if (session.TryGetCharacterCatalog(out var present)) return Summary(session.Id, present!, true);
        var gate = _gates.GetOrAdd(session.GenerationPath, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(token).ConfigureAwait(false);
        try
        {
            if (session.TryGetCharacterCatalog(out present)) return Summary(session.Id, present!, true);
            var mount = Path.Combine(session.PackageRoot, "meta", "0.papgt");
            var signature = session.Fingerprint + ":" + (File.Exists(mount)
                ? Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(mount, token).ConfigureAwait(false))) : "unmounted");
            var cachePath = Path.Combine(session.GenerationPath, $"character-catalog-v{ArchiveCharacterCatalogBuilder.Version}.json");
            CharacterCatalogSnapshot? snapshot = null;
            if (File.Exists(cachePath) && new FileInfo(cachePath).Length <= 128 * 1024 * 1024)
            {
                try
                {
                    await using var stream = File.OpenRead(cachePath);
                    var cached = await JsonSerializer.DeserializeAsync<CharacterCatalogSnapshot>(stream, CacheOptions, token).ConfigureAwait(false);
                    if (cached is not null && cached.Version == ArchiveCharacterCatalogBuilder.Version && cached.Signature == signature)
                        snapshot = cached;
                }
                catch (Exception error) when (error is IOException or JsonException or NotSupportedException) { }
            }
            var usedCache = snapshot is not null;
            if (snapshot is null)
            {
                snapshot = await Task.Run(() => ArchiveCharacterCatalogBuilder.Build(session.PackageRoot, signature,
                    Enumerate(session, token), entry => native.Decode(entry).Bytes, token,
                    (done, total, phase) => {
                        if ((done & 0x7F) == 0 && progress is not null)
                            progress(new ProgressUpdate(done, total, "character_catalog", phase)).GetAwaiter().GetResult();
                    }), token).ConfigureAwait(false);
                var temporary = cachePath + "." + Guid.NewGuid().ToString("N") + ".tmp";
                try
                {
                    await using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    {
                        await JsonSerializer.SerializeAsync(output, snapshot, CacheOptions, token).ConfigureAwait(false);
                        await output.FlushAsync(token).ConfigureAwait(false);
                    }
                    token.ThrowIfCancellationRequested();
                    sessions.GetRequired(session.Id);
                    File.Move(temporary, cachePath, overwrite: true);
                }
                finally { if (File.Exists(temporary)) File.Delete(temporary); }
            }
            token.ThrowIfCancellationRequested();
            sessions.GetRequired(session.Id);
            var catalog = new ArchiveCharacterCatalog(snapshot);
            session.SetCharacterCatalog(catalog);
            return Summary(session.Id, catalog, usedCache);
        }
        finally { gate.Release(); }
    }

    public async Task<CharacterCatalogSearchResult> SearchAsync(CharacterCatalogSearchRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var catalog = await RequiredAsync(request.SessionId, progress, token).ConfigureAwait(false);
        token.ThrowIfCancellationRequested();
        return catalog.Search(request);
    }

    public async Task<CharacterCatalogDetailResult> DetailAsync(CharacterCatalogDetailRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var catalog = await RequiredAsync(request.SessionId, progress, token).ConfigureAwait(false);
        var session = sessions.GetRequired(request.SessionId);
        var record = catalog.GetRequired(request.Key);
        var wantedRole = record.Row.Role == "whole_character" ? "body" : record.Row.Role;
        var models = record.Components.SelectMany(static component => component.ModelEntryIds).Distinct()
            .OrderBy(id => ArchiveCharacterReferences.Role(session.ReadEntry(id).Path) == wantedRole ? 0 : 1)
            .ThenBy(static id => id).ToArray();
        var ids = record.RelatedIds.Distinct().ToArray();
        var direct = record.DirectIds.ToHashSet();
        var files = ids.Take(256).Select(id => {
            token.ThrowIfCancellationRequested();
            var entry = session.ReadEntry(id);
            return new CharacterCatalogFile(id, entry.Path, entry.Extension, direct.Contains(id) ? "direct" : "dependency", entry.SourcePamt);
        }).ToArray();
        return new(session.Id, record.Row, models.Take(64).Select(session.ReadEntry).ToArray(), record.Components,
            files, record.Characters.Take(128).ToArray(), record.RelatedKeys.Take(128).Select(key => catalog.GetRequired(key).Row).ToArray(),
            record.Evidence.Take(64).Select(static line => line.Length <= 2048 ? line : line[..2048]).ToArray(), ids.Length,
            record.RelatedKeys.Length, record.Characters.Length,
            ids.Length > 256 || record.RelatedKeys.Length > 128 || record.Characters.Length > 128 || models.Length > 64,
            record.AppearancePath, record.ContextKey);
    }

    public async Task<CharacterCatalogScopeResult> ScopeAsync(CharacterCatalogScopeRequest request,
        Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        var catalog = await RequiredAsync(request.SessionId, progress, token).ConfigureAwait(false);
        var record = catalog.GetRequired(request.Key);
        var ids = request.IncludeRelated ? record.RelatedIds : record.DirectIds;
        var all = ids.Distinct().Order().ToArray();
        var limit = Math.Clamp(request.MaximumResults, 1, 4096);
        token.ThrowIfCancellationRequested();
        return new(request.SessionId, all.Take(limit).ToArray(), record.DirectIds.Distinct().Count(), all.Length, all.Length > limit);
    }

    private async Task<ArchiveCharacterCatalog> RequiredAsync(string sessionId, Func<ProgressUpdate, Task>? progress, CancellationToken token)
    {
        await BuildAsync(new(sessionId), progress, token).ConfigureAwait(false);
        sessions.GetRequired(sessionId).TryGetCharacterCatalog(out var catalog);
        return catalog ?? throw new InvalidOperationException("Character catalogue was not published.");
    }

    private static IEnumerable<ArchiveEntryDto> Enumerate(ArchiveSession session, CancellationToken token)
    {
        for (long i = 0; i < session.Index.EntryCount; i++)
        {
            if ((i & 0x1FFF) == 0) token.ThrowIfCancellationRequested();
            yield return session.Index.ReadEntry(i, session.Id);
        }
    }

    private static BuildCharacterCatalogResult Summary(string sessionId, ArchiveCharacterCatalog catalog, bool cached)
    {
        var snapshot = catalog.Snapshot;
        return new(sessionId, cached, snapshot.Records.Count(static row => row.Row.View == "assets"),
            snapshot.Records.Count(static row => row.Row.View == "appearances"), snapshot.Coverage.Length,
            snapshot.Coverage.Count(static row => row.Resolution == "resolved"),
            snapshot.Coverage.Count(static row => row.Resolution is not ("resolved" or "excluded")),
            snapshot.Coverage.Count(static row => row.Resolution == "excluded"), snapshot.Warnings);
    }
}
