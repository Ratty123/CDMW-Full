namespace Cdmw.ArchiveLite.Contracts;

public sealed record ArchiveCacheHealthRequest(string PackageRoot);

public sealed record ArchiveCacheHealthResult(
    string PackageRoot,
    ArchiveCacheHealthState State,
    string Reason,
    int SourceCount = 0,
    int ChangedSourceCount = 0,
    string? CachedFingerprint = null);

public enum ArchiveCacheHealthState
{
    Unknown,
    Checking,
    Current,
    Missing,
    Stale,
    Invalid,
}
