using System.Windows;

namespace Cdmw.ArchiveLite.App.Services;

public static class ThemeManager
{
    private const string DefaultThemeId = "graphite";
    private static readonly ThemeDefinition[] Definitions =
    [
        new("graphite", "ThemeGraphite", "Themes/Theme.Graphite.xaml", true),
        new("midnight", "ThemeMidnight", "Themes/Theme.Midnight.xaml", true),
        new("light", "ThemeLight", "Themes/Theme.Light.xaml", false),
    ];

    public static event EventHandler? ThemeChanged;

    public static IReadOnlyList<ThemeDefinition> AvailableThemes => Definitions;

    public static ThemeDefinition Current { get; private set; } = Definitions[0];

    public static void Apply(string? themeId)
    {
        var definition = Definitions.FirstOrDefault(candidate =>
                candidate.Id.Equals(themeId, StringComparison.OrdinalIgnoreCase))
            ?? Definitions.First(candidate => candidate.Id == DefaultThemeId);
        var application = Application.Current;
        if (application is null)
        {
            Current = definition;
            return;
        }

        var dictionaries = application.Resources.MergedDictionaries;
        var replacement = new ResourceDictionary
        {
            Source = new Uri(definition.ResourcePath, UriKind.Relative),
        };
        var themeIndex = -1;
        for (var index = 0; index < dictionaries.Count; index++)
        {
            var source = dictionaries[index].Source?.OriginalString ?? string.Empty;
            if (source.Contains("Themes/Theme.", StringComparison.OrdinalIgnoreCase))
            {
                themeIndex = index;
                break;
            }
        }

        if (themeIndex >= 0)
        {
            dictionaries[themeIndex] = replacement;
        }
        else
        {
            dictionaries.Insert(0, replacement);
        }
        Current = definition;
        ThemeChanged?.Invoke(null, EventArgs.Empty);
    }
}

public sealed record ThemeDefinition(string Id, string ResourceKey, string ResourcePath, bool IsDark);
