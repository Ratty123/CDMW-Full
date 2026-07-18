namespace Cdmw.ArchiveLite.Contracts;

public sealed record GameInstallDiscoveryRequest;

public sealed record GameInstallDiscoveryResult(
    IReadOnlyList<string> Candidates,
    string? PreferredRoot);
