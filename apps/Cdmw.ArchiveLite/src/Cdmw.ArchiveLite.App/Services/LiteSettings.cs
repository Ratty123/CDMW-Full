using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Services;

public sealed record LiteSettings(
    string Language = "en",
    string? ArchiveRoot = null,
    string? ExportRoot = null,
    string Theme = "graphite",
    string FontSize = "medium",
    string LayoutDensity = "comfortable",
    ArchiveSortField ArchiveSortField = ArchiveSortField.Path,
    bool ArchiveSortDescending = false,
    string[]? ArchiveVisibleColumns = null,
    ArchiveBrowserSettings? ArchiveBrowser = null,
    TextSearchSettings? TextSearch = null,
    ItemFinderSettings? ItemFinder = null,
    WindowPlacementSettings? WindowPlacement = null,
    WorkspaceLayoutSettings? WorkspaceLayout = null,
    GridColumnSettings[]? ArchiveColumnLayout = null,
    GridColumnSettings[]? TextSearchColumnLayout = null);

public sealed record ArchiveBrowserSettings(
    string PathFilter = "",
    string ExtensionFilter = "",
    ArchiveViewMode ViewMode = ArchiveViewMode.Flat,
    string? FolderPath = null,
    ExportCollisionPolicy CollisionPolicy = ExportCollisionPolicy.Skip,
    ExportManifestFormat ManifestFormat = ExportManifestFormat.Json);

public sealed record TextSearchSettings(
    TextSearchSourceKind SourceKind = TextSearchSourceKind.Archive,
    string LooseFolder = "",
    string Query = "",
    string PathFilter = "",
    string Extensions = ".xml;.txt;.json;.cfg;.ini;.lua;.material;.shader;.yaml;.yml",
    bool UseRegularExpression = false,
    bool CaseSensitive = false);

public sealed record ItemFinderSettings(
    string Query = "",
    string? Category = null,
    string? Group = null,
    string? MaterialTag = null,
    double Width = 1240,
    double Height = 800);

public sealed record WindowPlacementSettings(
    double? Left = null,
    double? Top = null,
    double Width = 1440,
    double Height = 880,
    bool IsMaximized = false);

public sealed record WorkspaceLayoutSettings(
    double ArchiveFilterWidth = 278,
    double ArchivePreviewWidth = 420,
    double TextSearchFilterWidth = 300,
    double TextSearchPreviewWidth = 420);

public sealed record GridColumnSettings(
    string Key,
    int DisplayIndex,
    double Width);
