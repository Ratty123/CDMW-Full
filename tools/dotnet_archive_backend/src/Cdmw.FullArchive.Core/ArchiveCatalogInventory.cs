using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

/// <summary>
/// The archive entries a catalogue builder can use, in archive entry order.
/// A builder keeps a few file types out of some two million entries, so it reads
/// the per-extension entry lists and looks at a path before paying for a whole entry.
/// </summary>
internal static class ArchiveCatalogInventory
{
    internal static long[] EntryIds(ArchiveSession session, IEnumerable<string> extensions, CancellationToken token) =>
        session.Index.GetEntryIdsByExtension(
            extensions.Distinct(StringComparer.OrdinalIgnoreCase).ToArray(), token);

    /// <summary>
    /// Files under <c>character/</c> with one of <paramref name="extensions"/>, plus the
    /// static tables <see cref="ArchiveItemSources"/> selects: everything the character
    /// and NPC catalogue builders keep from a full inventory.
    /// </summary>
    internal static IEnumerable<ArchiveEntryDto> CharacterEntries(
        ArchiveSession session, IEnumerable<string> extensions, CancellationToken token)
    {
        var ids = EntryIds(session, extensions.Concat(ArchiveItemSources.CandidateExtensions), token);
        for (var index = 0; index < ids.Length; index++)
        {
            if ((index & 0x1FFF) == 0) token.ThrowIfCancellationRequested();
            var path = session.Index.ReadEntryPath(ids[index]);
            if (!path.StartsWith("character/", StringComparison.OrdinalIgnoreCase) && !ArchiveItemSources.IsCandidatePath(path))
                continue;
            yield return session.Index.ReadEntry(ids[index], session.Id);
        }
    }
}
