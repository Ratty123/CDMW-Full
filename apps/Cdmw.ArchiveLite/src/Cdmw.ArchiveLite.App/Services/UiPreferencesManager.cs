using System.Windows;

namespace Cdmw.ArchiveLite.App.Services;

public static class UiPreferencesManager
{
    private const string DefaultFontSizeId = "medium";
    private const string DefaultLayoutDensityId = "comfortable";

    private static readonly FontSizeDefinition[] FontSizes =
    [
        new("small", "FontSizeSmall", 12, 11, 16, 13.5, 20, 9.5, 12),
        new("medium", "FontSizeMedium", 13, 12, 17, 14.5, 22, 10, 12.5),
        new("large", "FontSizeLarge", 15, 14, 19, 16.5, 25, 11, 14),
        new("extra-large", "FontSizeExtraLarge", 17, 16, 21, 18.5, 28, 12, 16),
    ];

    private static readonly LayoutDensityDefinition[] LayoutDensities =
    [
        new("compact", "LayoutCompact", new(11), new(10, 5, 10, 5), 30, new(8, 3, 8, 3), 26, new(8, 4, 34, 4), new(8, 5, 8, 5), new(10), new(0, 0, 0, 8), new(11, 5, 11, 5), 32, new(6, 3, 6, 3), new(8, 5, 8, 5), 29, new(8, 4, 8, 4)),
        new("comfortable", "LayoutComfortable", new(16), new(13, 7, 13, 7), 34, new(10, 5, 10, 5), 30, new(10, 6, 38, 6), new(10, 7, 10, 7), new(14), new(0, 0, 0, 12), new(14, 7, 14, 7), 36, new(8, 6, 8, 6), new(10, 8, 10, 8), 34, new(10, 6, 10, 6)),
        new("spacious", "LayoutSpacious", new(20), new(16, 9, 16, 9), 40, new(13, 7, 13, 7), 34, new(12, 8, 42, 8), new(12, 9, 12, 9), new(18), new(0, 0, 0, 16), new(17, 9, 17, 9), 42, new(10, 8, 10, 8), new(12, 10, 12, 10), 40, new(12, 8, 12, 8)),
    ];

    public static IReadOnlyList<FontSizeDefinition> AvailableFontSizes => FontSizes;
    public static IReadOnlyList<LayoutDensityDefinition> AvailableLayoutDensities => LayoutDensities;
    public static FontSizeDefinition CurrentFontSize { get; private set; } = FontSizes[1];
    public static LayoutDensityDefinition CurrentLayoutDensity { get; private set; } = LayoutDensities[1];

    public static void Apply(string? fontSizeId, string? layoutDensityId)
    {
        CurrentFontSize = FontSizes.FirstOrDefault(candidate => candidate.Id.Equals(fontSizeId, StringComparison.OrdinalIgnoreCase))
            ?? FontSizes.First(candidate => candidate.Id == DefaultFontSizeId);
        CurrentLayoutDensity = LayoutDensities.FirstOrDefault(candidate => candidate.Id.Equals(layoutDensityId, StringComparison.OrdinalIgnoreCase))
            ?? LayoutDensities.First(candidate => candidate.Id == DefaultLayoutDensityId);
        var resources = Application.Current?.Resources;
        if (resources is null)
        {
            return;
        }

        resources["BaseFontSize"] = CurrentFontSize.Base;
        resources["CaptionFontSize"] = CurrentFontSize.Caption;
        resources["SectionTitleFontSize"] = CurrentFontSize.SectionTitle;
        resources["TitleFontSize"] = CurrentFontSize.Title;
        resources["DialogTitleFontSize"] = CurrentFontSize.DialogTitle;
        resources["BadgeFontSize"] = CurrentFontSize.Badge;
        resources["EditorFontSize"] = CurrentFontSize.Editor;
        resources["CardPadding"] = CurrentLayoutDensity.CardPadding;
        resources["ControlPadding"] = CurrentLayoutDensity.ControlPadding;
        resources["ControlMinHeight"] = CurrentLayoutDensity.ControlMinHeight;
        resources["CompactControlPadding"] = CurrentLayoutDensity.CompactControlPadding;
        resources["CompactControlMinHeight"] = CurrentLayoutDensity.CompactControlMinHeight;
        resources["ComboBoxPadding"] = CurrentLayoutDensity.ComboBoxPadding;
        resources["ComboItemPadding"] = CurrentLayoutDensity.ComboItemPadding;
        resources["GroupBoxPadding"] = CurrentLayoutDensity.GroupBoxPadding;
        resources["GroupBoxMargin"] = CurrentLayoutDensity.GroupBoxMargin;
        resources["NavigationPadding"] = CurrentLayoutDensity.NavigationPadding;
        resources["NavigationHeight"] = CurrentLayoutDensity.NavigationHeight;
        resources["ListItemPadding"] = CurrentLayoutDensity.ListItemPadding;
        resources["DataGridHeaderPadding"] = CurrentLayoutDensity.DataGridHeaderPadding;
        resources["DataGridRowMinHeight"] = CurrentLayoutDensity.DataGridRowMinHeight;
        resources["DataGridCellPadding"] = CurrentLayoutDensity.DataGridCellPadding;
    }
}

public sealed record FontSizeDefinition(string Id, string ResourceKey, double Base, double Caption, double SectionTitle, double Title, double DialogTitle, double Badge, double Editor);

public sealed record LayoutDensityDefinition(
    string Id,
    string ResourceKey,
    Thickness CardPadding,
    Thickness ControlPadding,
    double ControlMinHeight,
    Thickness CompactControlPadding,
    double CompactControlMinHeight,
    Thickness ComboBoxPadding,
    Thickness ComboItemPadding,
    Thickness GroupBoxPadding,
    Thickness GroupBoxMargin,
    Thickness NavigationPadding,
    double NavigationHeight,
    Thickness ListItemPadding,
    Thickness DataGridHeaderPadding,
    double DataGridRowMinHeight,
    Thickness DataGridCellPadding);
