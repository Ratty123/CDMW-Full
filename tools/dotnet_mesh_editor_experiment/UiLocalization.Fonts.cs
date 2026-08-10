using System.Globalization;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class UiLocalizationOwner
{
    private static CultureInfo PresentationCulture(string languageCode)
    {
        var cultureCode = languageCode switch
        {
            "es-419" => "es-MX",
            "zh-Hans" => "zh-CN",
            "zh-Hant" => "zh-TW",
            _ => languageCode,
        };
        try
        {
            return CultureInfo.GetCultureInfo(cultureCode);
        }
        catch (CultureNotFoundException)
        {
            return CultureInfo.InvariantCulture;
        }
    }

    private void ApplyFont(Control control, SourceProperties source)
    {
        source.OriginalFont ??= control.Font;
        if (!TryCjkFallbacks(_languageCode, out var fallbacks)
            || FontCoversLocale(source.OriginalFont.FontFamily.Name, fallbacks))
        {
            if (!ReferenceEquals(control.Font, source.OriginalFont))
            {
                control.Font = source.OriginalFont;
            }
            return;
        }
        var familyName = ResolveCjkFallbackFontFamily(_languageCode);
        if (familyName is null)
        {
            return;
        }
        var key = new FontKey(
            familyName,
            source.OriginalFont.Size,
            source.OriginalFont.Style,
            source.OriginalFont.Unit,
            source.OriginalFont.GdiCharSet,
            source.OriginalFont.GdiVerticalFont);
        if (!_fallbackFonts.TryGetValue(key, out var fallback))
        {
            fallback = new Font(
                familyName,
                key.Size,
                key.Style,
                key.Unit,
                key.CharSet,
                key.Vertical);
            _fallbackFonts[key] = fallback;
        }
        control.Font = fallback;
    }

    internal static string? ResolveCjkFallbackFontFamily(string languageCode)
    {
        if (!TryCjkFallbacks(languageCode, out var fallbacks))
        {
            return null;
        }
        var installed = FontFamily.Families
            .Select(family => family.Name)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        return fallbacks.FirstOrDefault(installed.Contains);
    }

    private static bool TryCjkFallbacks(string languageCode, out string[] fallbacks)
    {
        foreach (var pair in CjkFontFallbacks)
        {
            if (languageCode.Equals(pair.Key, StringComparison.OrdinalIgnoreCase)
                || languageCode.StartsWith(pair.Key + "-", StringComparison.OrdinalIgnoreCase))
            {
                fallbacks = pair.Value;
                return true;
            }
        }
        fallbacks = Array.Empty<string>();
        return false;
    }

    private static bool FontCoversLocale(string familyName, IEnumerable<string> fallbacks) =>
        UniversalCjkFontFamilies.Contains(familyName)
        || fallbacks.Contains(familyName, StringComparer.OrdinalIgnoreCase);
}
