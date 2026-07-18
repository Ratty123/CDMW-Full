using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Services;

public sealed record LiteSettings(
    string Language = "en",
    string? ArchiveRoot = null,
    string? ExportRoot = null,
    string Theme = "graphite",
    ArchiveSortField ArchiveSortField = ArchiveSortField.Path,
    bool ArchiveSortDescending = false,
    string[]? ArchiveVisibleColumns = null);
