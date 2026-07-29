using System.Globalization;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class UiLocalizationContractSmoke
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(
            arg,
            "--headless-ui-localization-contract",
            StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = RequiredValue(args, "--localization-report");
        Directory.CreateDirectory(
            Path.GetDirectoryName(reportPath)
                ?? throw new InvalidOperationException(
                    "Localization report has no parent directory."));
        try
        {
            var boundaries = new[]
            {
                new Boundary("one_other", "en", 1m, "one"),
                new Boundary("one_other", "en", 2m, "other"),
                new Boundary("one_other", "en", 1.0m, "other"),
                new Boundary("spanish_million", "es-ES", 1m, "one"),
                new Boundary("spanish_million", "es-419", 1.0m, "one"),
                new Boundary("spanish_million", "es-419", 2m, "other"),
                new Boundary("italian_million", "it", 1.0m, "other"),
                new Boundary("italian_million", "it", 1_000_000m, "many"),
                new Boundary("zero_one_million", "fr", 0m, "one"),
                new Boundary("zero_one_million", "pt-BR", 1m, "one"),
                new Boundary("zero_one_million", "fr", 1.5m, "one"),
                new Boundary("zero_one_million", "pt-BR", 0.5m, "one"),
                new Boundary("zero_one_million", "fr", 2m, "other"),
                new Boundary("zero_one_million", "pt-BR", 1_000_000m, "many"),
                new Boundary("polish", "pl", 1m, "one"),
                new Boundary("polish", "pl", 2m, "few"),
                new Boundary("polish", "pl", 5m, "many"),
                new Boundary("polish", "pl", 12m, "many"),
                new Boundary("polish", "pl", 22m, "few"),
                new Boundary("polish", "pl", 1.2m, "other"),
                new Boundary("russian", "ru", 1m, "one"),
                new Boundary("russian", "ru", 2m, "few"),
                new Boundary("russian", "ru", 5m, "many"),
                new Boundary("russian", "ru", 11m, "many"),
                new Boundary("russian", "ru", 21m, "one"),
                new Boundary("russian", "ru", 22m, "few"),
                new Boundary("russian", "ru", 1.2m, "other"),
                new Boundary("other", "tr", 1m, "other"),
                new Boundary("other", "ja", 2m, "other"),
                new Boundary("other", "ko", 5m, "other"),
                new Boundary("other", "zh-Hans", 0m, "other"),
                new Boundary("other", "zh-Hant", 1_000_000m, "other"),
            };
            var results = boundaries.Select(boundary => new
            {
                boundary.Rule,
                boundary.Locale,
                boundary.Count,
                boundary.Expected,
                Actual = UiLocalizationOwner.SelectPluralCategory(
                    boundary.Rule,
                    boundary.Locale,
                    boundary.Count),
            }).ToArray();
            var catalogHash = UiLocalizationOwner.CatalogHashFromJson(
                "{\"Save\":\"Speichern\",\"日本語\":\"保存\"}");
            var presentationFormatOk =
                UiLocalizationOwner.LocalizePresentationArgument(
                    "de",
                    "1,234.5 MB") == "1.234,5 MB"
                && UiLocalizationOwner.LocalizePresentationArgument(
                    "de",
                    "1234",
                    "Found {value_0} items") == "1.234"
                && UiLocalizationOwner.LocalizePresentationArgument(
                    "de",
                    "1234",
                    "Part (ID {value_0})") == "1234";
            var previousCulture = CultureInfo.CurrentCulture;
            var invariantMetricsSourceOk = false;
            try
            {
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("sv-SE");
                var metrics = new RenderMetrics();
                metrics.Record(1.5, 0.5, 0.5, string.Empty);
                var metricsSource = ExperimentForm.RendererMetricsText(
                    metrics,
                    "d3d11",
                    compact: true);
                invariantMetricsSourceOk =
                    metricsSource.Contains("FPS 0.0", StringComparison.Ordinal)
                    && metricsSource.Contains("Interval 0.00 ms", StringComparison.Ordinal)
                    && !metricsSource.Contains("0,0", StringComparison.Ordinal);
            }
            finally
            {
                CultureInfo.CurrentCulture = previousCulture;
            }
            var cjkFonts = new[] { "ja", "ko", "zh-Hans", "zh-Hant" }
                .ToDictionary(
                    locale => locale,
                    UiLocalizationOwner.ResolveCjkFallbackFontFamily,
                    StringComparer.Ordinal);
            var cjkFontFallbacksOk = cjkFonts.Values.All(
                family => !string.IsNullOrWhiteSpace(family));
            var ok = results.All(result => result.Actual == result.Expected)
                && catalogHash
                    == "ef15ede0b82aa0976a87e9db80b51e61bccc5976fbc4fd8fc0e8d8d9b19b7385"
                && presentationFormatOk
                && invariantMetricsSourceOk
                && cjkFontFallbacksOk
                && UiLocalizationOwner.LocalizationKeys.Count > 0
                && UiLocalizationOwner.LocalizationKeyManifestHash.Length == 64;
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(
                    new
                    {
                        ok,
                        boundary_count = results.Length,
                        boundaries = results,
                        catalog_hash = catalogHash,
                        presentation_format_ok = presentationFormatOk,
                        invariant_metrics_source_ok = invariantMetricsSourceOk,
                        cjk_font_fallbacks_ok = cjkFontFallbacksOk,
                        cjk_fonts = cjkFonts,
                        localization_key_count =
                            UiLocalizationOwner.LocalizationKeys.Count,
                        localization_key_manifest_hash =
                            UiLocalizationOwner.LocalizationKeyManifestHash,
                        renderer_started = false,
                        visible_window_started = false,
                    },
                    new JsonSerializerOptions { WriteIndented = true }));
            return ok ? 0 : 1;
        }
        catch (Exception ex)
        {
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(
                    new
                    {
                        ok = false,
                        error = ex.Message,
                        error_type = ex.GetType().FullName,
                    },
                    new JsonSerializerOptions { WriteIndented = true }));
            return 1;
        }
    }

    private static string RequiredValue(string[] args, string name)
    {
        var index = Array.FindIndex(
            args,
            arg => string.Equals(arg, name, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length)
        {
            throw new ArgumentException($"{name} requires a value.");
        }
        return Path.GetFullPath(args[index + 1]);
    }

    private sealed record Boundary(
        string Rule,
        string Locale,
        decimal Count,
        string Expected);
}
