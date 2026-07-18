using System.Globalization;
using System.Reflection;
using System.Resources;

namespace Cdmw.ArchiveLite.App.Services;

public static class LocalizationManager
{
    private static readonly ResourceManager Resources = new(
        "Cdmw.ArchiveLite.App.Resources.Strings",
        Assembly.GetExecutingAssembly());
    private static CultureInfo _selectedCulture = CultureInfo.GetCultureInfo("en");

    public static void ApplyCulture(string? language)
    {
        var normalized = language?.Trim().ToLowerInvariant() switch
        {
            "de" => "de",
            "es" => "es",
            _ => "en",
        };
        var culture = CultureInfo.GetCultureInfo(normalized);
        Volatile.Write(ref _selectedCulture, culture);
        CultureInfo.DefaultThreadCurrentCulture = culture;
        CultureInfo.DefaultThreadCurrentUICulture = culture;
        CultureInfo.CurrentCulture = culture;
        CultureInfo.CurrentUICulture = culture;
        Thread.CurrentThread.CurrentCulture = culture;
        Thread.CurrentThread.CurrentUICulture = culture;
        LocalizedStringSource.Instance.Refresh();
    }

    public static string Get(string key) => Resources.GetString(key, Volatile.Read(ref _selectedCulture)) ?? $"[{key}]";

    public static string Format(string key, params object?[] values) =>
        string.Format(Volatile.Read(ref _selectedCulture), Get(key), values);
}
