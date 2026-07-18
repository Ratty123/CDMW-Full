using System.Globalization;
using System.Reflection;
using System.Resources;

namespace Cdmw.ArchiveLite.App.Services;

public static class LocalizationManager
{
    private static readonly ResourceManager Resources = new(
        "Cdmw.ArchiveLite.App.Resources.Strings",
        Assembly.GetExecutingAssembly());

    public static void ApplyCulture(string? language)
    {
        var normalized = language?.Trim().ToLowerInvariant() switch
        {
            "de" => "de",
            "es" => "es",
            _ => "en",
        };
        var culture = CultureInfo.GetCultureInfo(normalized);
        CultureInfo.CurrentCulture = culture;
        CultureInfo.CurrentUICulture = culture;
        Thread.CurrentThread.CurrentCulture = culture;
        Thread.CurrentThread.CurrentUICulture = culture;
    }

    public static string Get(string key) => Resources.GetString(key, CultureInfo.CurrentUICulture) ?? $"[{key}]";

    public static string Format(string key, params object?[] values) =>
        string.Format(CultureInfo.CurrentCulture, Get(key), values);
}
