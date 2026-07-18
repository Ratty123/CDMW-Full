using System.Buffers.Binary;
using System.Globalization;
using System.Security.Cryptography;
using System.Diagnostics;
using System.IO.Compression;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Windows.Threading;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.App.ViewModels;
using Cdmw.ArchiveLite.Contracts;
using Cdmw.ArchiveLite.Core;
using Cdmw.ArchiveLite.Standalone;

namespace Cdmw.ArchiveLite.Tests;

internal static class ArchiveLiteTestRunner
{
    public static async Task<int> RunAsync()
    {
        var tests = new (string Name, Func<Task> Run)[]
        {
            ("protocol serializes snake-case messages", TestProtocolAsync),
            ("English, German, and Spanish resources have identical keys", TestLocalizationResourcesAsync),
            ("compiled localization persists across later UI work", TestCompiledLocalizationAsync),
            ("read-only WPF text bindings are explicitly one-way", TestReadOnlyWpfBindingsAsync),
            ("fatal diagnostics are written to portable log and crash folders", TestFatalDiagnosticsAsync),
            ("portable settings retain filters, window placement, panes, and columns", TestPortableUiSettingsAsync),
            ("WPF themes expose the shared palette and safe progress bindings", TestWpfThemesAsync),
            ("modern shell exposes cache health, game detection, and Enter search", TestModernShellAsync),
            ("archive grid exposes configurable sortable columns and categorized extensions", TestArchiveGridFeaturesAsync),
            ("associated assets resolve references and same-family companions read-only", TestAssociatedAssetsAsync),
            ("export paths reject traversal and roots", TestExportPathPolicyAsync),
            ("isolated cache maintenance is bounded and deterministic", TestCacheMaintenanceAsync),
            ("standalone payload extraction is atomic, reusable, and traversal-safe", TestStandaloneRuntimeAsync),
            ("game discovery recognizes archive roots and Steam libraries", TestGameInstallDiscoveryAsync),
            ("archive cache health detects missing, current, and stale indexes", TestArchiveCacheHealthAsync),
            ("archive loading supports reusable and session-only indexes", TestArchiveCacheModesAsync),
            ("startup auto-loads current cache and recommends manual refresh after hash changes", TestStartupCacheAutoLoadAsync),
            ("native model packages adapt safely and export Blender interchange formats", TestNativeModelPreviewPackageAsync),
            ("known item names distinguish exact names from related hints", TestArchiveItemNamesAsync),
            ("UTF-8, UTF-16, and Latin-1 text decode without Python codecs", TestTextDecodingAsync),
            ("native archive ABI scans and decodes synthetic PAMT/PAZ", TestNativeArchiveAsync),
            ("archive query, preview, and text search are read-only", TestArchiveServicesAsync),
            ("archive export is contained, atomic, and manifested", TestArchiveExportAsync),
            ("named-pipe worker opens and queries an archive", TestWorkerBoundaryAsync),
        };
        var failures = new List<string>();
        foreach (var test in tests)
        {
            try
            {
                await test.Run().ConfigureAwait(false);
                Console.WriteLine($"PASS: {test.Name}");
            }
            catch (Exception exception)
            {
                failures.Add($"{test.Name}: {exception}");
                Console.Error.WriteLine($"FAIL: {test.Name}: {exception.Message}");
            }
        }
        if (failures.Count == 0)
        {
            Console.WriteLine($"CDMW Archive Lite focused tests: PASS ({tests.Length} scenarios)");
            return 0;
        }
        Console.Error.WriteLine($"CDMW Archive Lite focused tests: FAIL ({failures.Count}/{tests.Length})");
        return 1;
    }

    private static Task TestProtocolAsync()
    {
        var message = WorkerProtocol.Request(Guid.Parse("11111111-1111-1111-1111-111111111111"), 7, WorkerProtocol.Ping, new PingRequest("1.0"));
        var json = System.Text.Json.JsonSerializer.Serialize(message, WorkerProtocol.JsonOptions);
        Require(json.Contains("\"protocol_version\":1", StringComparison.Ordinal), "protocol_version is not snake case");
        Require(WorkerProtocol.ReadPayload<PingRequest>(message)?.ClientVersion == "1.0", "protocol payload did not round-trip");
        var openMessage = WorkerProtocol.Request(
            Guid.Parse("22222222-2222-2222-2222-222222222222"),
            8,
            WorkerProtocol.OpenArchive,
            new OpenArchiveRequest("C:\\game", CacheMode: ArchiveCacheMode.SessionOnly));
        var openJson = JsonSerializer.Serialize(openMessage, WorkerProtocol.JsonOptions);
        Require(openJson.Contains("\"cache_mode\":\"session_only\"", StringComparison.Ordinal), "cache_mode is not a snake-case protocol enum");
        Require(
            WorkerProtocol.ReadPayload<OpenArchiveRequest>(openMessage)?.CacheMode == ArchiveCacheMode.SessionOnly,
            "archive cache mode did not round-trip");
        var cachedOnlyMessage = WorkerProtocol.Request(
            Guid.Parse("23232323-2323-2323-2323-232323232323"),
            8,
            WorkerProtocol.OpenArchive,
            new OpenArchiveRequest("C:\\game", CacheMode: ArchiveCacheMode.Persistent, AllowCacheBuild: false));
        var cachedOnlyJson = JsonSerializer.Serialize(cachedOnlyMessage, WorkerProtocol.JsonOptions);
        Require(cachedOnlyJson.Contains("\"allow_cache_build\":false", StringComparison.Ordinal), "cached-only startup intent is not serialized");
        var associationMessage = WorkerProtocol.Request(
            Guid.Parse("33333333-3333-3333-3333-333333333333"),
            9,
            WorkerProtocol.FindAssociatedAssets,
            new FindAssociatedAssetsRequest("session", 42, 96));
        var associationJson = JsonSerializer.Serialize(associationMessage, WorkerProtocol.JsonOptions);
        Require(
            associationJson.Contains("\"maximum_results\":96", StringComparison.Ordinal),
            "associated-asset request is not snake case");
        Require(
            WorkerProtocol.ReadPayload<FindAssociatedAssetsRequest>(associationMessage)?.EntryId == 42,
            "associated-asset request did not round-trip");
        var folderExportMessage = WorkerProtocol.Request(
            Guid.Parse("34343434-3434-3434-3434-343434343434"),
            10,
            WorkerProtocol.Export,
            new ExportPlanRequest(
                "session",
                ExportKind.FolderTree,
                "C:\\output",
                [],
                null,
                FolderPath: "character/model"));
        var folderExportJson = JsonSerializer.Serialize(folderExportMessage, WorkerProtocol.JsonOptions);
        Require(folderExportJson.Contains("\"folder_path\":\"character/model\"", StringComparison.Ordinal), "folder export scope is not serialized");
        return Task.CompletedTask;
    }

    private static Task TestLocalizationResourcesAsync()
    {
        var resourceRoot = Path.Combine(
            FindRepositoryRoot(),
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.App",
            "Resources");
        var resources = new[] { "Strings.resx", "Strings.de.resx", "Strings.es.resx" }
            .Select(filename => System.Xml.Linq.XDocument.Load(Path.Combine(resourceRoot, filename)))
            .Select(document => document.Root!.Elements("data").ToDictionary(
                element => (string)element.Attribute("name")!,
                element => (string?)element.Element("value") ?? string.Empty,
                StringComparer.Ordinal))
            .ToArray();
        var expected = resources[0].Keys.Order(StringComparer.Ordinal).ToArray();
        foreach (var resource in resources)
        {
            Require(resource.Keys.Order(StringComparer.Ordinal).SequenceEqual(expected), "localized resource keys do not match");
            Require(resource.Values.All(static value => !string.IsNullOrWhiteSpace(value)), "localized resource contains an empty value");
        }
        return Task.CompletedTask;
    }

    private static Task TestCompiledLocalizationAsync()
    {
        var originalCulture = CultureInfo.CurrentCulture;
        var originalUiCulture = CultureInfo.CurrentUICulture;
        var originalDefaultCulture = CultureInfo.DefaultThreadCurrentCulture;
        var originalDefaultUiCulture = CultureInfo.DefaultThreadCurrentUICulture;
        var refreshCount = 0;
        System.ComponentModel.PropertyChangedEventHandler handler = (_, args) =>
        {
            if (string.Equals(args.PropertyName, "Item[]", StringComparison.Ordinal))
            {
                refreshCount++;
            }
        };
        LocalizedStringSource.Instance.PropertyChanged += handler;
        try
        {
            var expectations = new[]
            {
                (Language: "en", Title: "Archive loading"),
                (Language: "de", Title: "Archiv laden"),
                (Language: "es", Title: "Carga del archivo"),
            };
            foreach (var expectation in expectations)
            {
                LocalizationManager.ApplyCulture(expectation.Language);
                Require(
                    string.Equals(CultureInfo.CurrentUICulture.TwoLetterISOLanguageName, expectation.Language, StringComparison.Ordinal),
                    $"current UI culture did not switch to {expectation.Language}");
                Require(
                    string.Equals(CultureInfo.DefaultThreadCurrentUICulture?.TwoLetterISOLanguageName, expectation.Language, StringComparison.Ordinal),
                    $"default UI culture did not persist {expectation.Language} for later UI callbacks");
                Require(
                    string.Equals(LocalizationManager.Get("CacheChoiceTitle"), expectation.Title, StringComparison.Ordinal),
                    $"compiled {expectation.Language} cache-dialog resources fell back to another language");
                Require(
                    string.Equals(LocalizedStringSource.Instance["CacheChoiceTitle"], expectation.Title, StringComparison.Ordinal),
                    $"live localized binding source did not expose {expectation.Language}");
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("en");
                CultureInfo.CurrentUICulture = CultureInfo.GetCultureInfo("en");
                Require(
                    string.Equals(LocalizationManager.Get("CacheChoiceTitle"), expectation.Title, StringComparison.Ordinal),
                    $"compiled {expectation.Language} resources drifted with a later async culture context");
            }
            Require(refreshCount >= expectations.Length, "live localized bindings were not refreshed for each culture change");

            var locExtensionSource = File.ReadAllText(Path.Combine(
                FindRepositoryRoot(),
                "apps",
                "Cdmw.ArchiveLite",
                "src",
                "Cdmw.ArchiveLite.App",
                "Infrastructure",
                "LocExtension.cs"));
            Require(
                locExtensionSource.Contains("LocalizedStringSource.Instance", StringComparison.Ordinal)
                && locExtensionSource.Contains("BindingMode.OneWay", StringComparison.Ordinal),
                "XAML localization still resolves to a one-time static string");
        }
        finally
        {
            LocalizedStringSource.Instance.PropertyChanged -= handler;
            CultureInfo.DefaultThreadCurrentCulture = originalDefaultCulture;
            CultureInfo.DefaultThreadCurrentUICulture = originalDefaultUiCulture;
            CultureInfo.CurrentCulture = originalCulture;
            CultureInfo.CurrentUICulture = originalUiCulture;
            Thread.CurrentThread.CurrentCulture = originalCulture;
            Thread.CurrentThread.CurrentUICulture = originalUiCulture;
        }
        return Task.CompletedTask;
    }

    private static Task TestReadOnlyWpfBindingsAsync()
    {
        var windowPath = Path.Combine(
            FindRepositoryRoot(),
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.App",
            "MainWindow.xaml");
        var document = System.Xml.Linq.XDocument.Load(windowPath);
        var readOnlyTextBindings = document
            .Descendants()
            .Where(element => element.Name.LocalName == "TextBox")
            .Where(element => string.Equals((string?)element.Attribute("IsReadOnly"), "True", StringComparison.OrdinalIgnoreCase))
            .Select(element => (string?)element.Attribute("Text"))
            .Where(static value => value?.StartsWith("{Binding", StringComparison.Ordinal) == true)
            .ToArray();
        Require(readOnlyTextBindings.Length > 0, "MainWindow has no read-only TextBox binding to validate");
        Require(
            readOnlyTextBindings.All(static binding => binding!.Contains("Mode=OneWay", StringComparison.Ordinal)),
            "a read-only TextBox uses WPF's default TwoWay Text binding");
        var runTextBindings = document
            .Descendants()
            .Where(element => element.Name.LocalName == "Run")
            .Select(element => (string?)element.Attribute("Text"))
            .Where(static value => value?.StartsWith("{Binding", StringComparison.Ordinal) == true)
            .ToArray();
        Require(runTextBindings.Length > 0, "MainWindow has no inline Run binding to validate");
        Require(
            runTextBindings.All(static binding => binding!.Contains("Mode=OneWay", StringComparison.Ordinal)),
            "an inline Run uses WPF's write-back binding mode for a read-only row property");
        return Task.CompletedTask;
    }

    private static Task TestFatalDiagnosticsAsync()
    {
        var portableRoot = Path.GetFullPath(Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DATA_ROOT")!);
        var appAssembly = typeof(MainWindowViewModel).Assembly;
        var diagnosticLog = appAssembly.GetType("Cdmw.ArchiveLite.App.Services.DiagnosticLog")
            ?? throw new InvalidOperationException("DiagnosticLog type was not found");
        var writeFatal = diagnosticLog.GetMethod("WriteFatal", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static)
            ?? throw new InvalidOperationException("DiagnosticLog.WriteFatal was not found");
        writeFatal.Invoke(null, ["test-fatal", new InvalidOperationException("synthetic fatal diagnostic")]);
        var logPath = Path.Combine(portableRoot, "logs", "archive-lite.log");
        var crashFiles = Directory.GetFiles(Path.Combine(portableRoot, "crash"), "archive-lite-crash-*.log");
        Require(File.Exists(logPath), "fatal diagnostic did not reach the portable log folder");
        Require(crashFiles.Length > 0, "fatal diagnostic did not reach the portable crash folder");
        Require(
            File.ReadAllText(crashFiles[^1]).Contains("synthetic fatal diagnostic", StringComparison.Ordinal),
            "portable crash diagnostic omitted the underlying exception");
        return Task.CompletedTask;
    }

    private static async Task TestPortableUiSettingsAsync()
    {
        var expected = new LiteSettings(
            Language: "de",
            ArchiveRoot: "C:\\game",
            Theme: "midnight",
            ArchiveSortField: ArchiveSortField.KnownName,
            ArchiveSortDescending: true,
            ArchiveVisibleColumns: ["Name", "Path"],
            ArchiveBrowser: new ArchiveBrowserSettings(
                "character/model",
                ".pac;.pam",
                "base",
                true,
                ArchiveViewMode.CategoriesAndFolders,
                "character/model/player",
                ArchiveEntryRole.Model,
                ExportCollisionPolicy.Overwrite,
                ExportManifestFormat.Csv),
            TextSearch: new TextSearchSettings(
                TextSearchSourceKind.LooseFolder,
                "C:\\loose",
                "material_name",
                "character",
                ".xml;.material",
                true,
                true),
            WindowPlacement: new WindowPlacementSettings(120, 80, 1320, 790, true),
            WorkspaceLayout: new WorkspaceLayoutSettings(336, 488, 318, 452),
            ArchiveColumnLayout:
            [
                new GridColumnSettings("Name", 1, 240),
                new GridColumnSettings("Path", 0, 510),
            ],
            TextSearchColumnLayout:
            [
                new GridColumnSettings("Path", 0, 420),
                new GridColumnSettings("Context", 2, 560),
            ]);
        var settingsStore = typeof(MainWindowViewModel).Assembly.GetType("Cdmw.ArchiveLite.App.Services.SettingsStore")
            ?? throw new InvalidOperationException("SettingsStore type was not found");
        var saveMethod = settingsStore.GetMethod("SaveAsync", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static)
            ?? throw new InvalidOperationException("SettingsStore.SaveAsync was not found");
        var loadMethod = settingsStore.GetMethod("LoadAsync", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static)
            ?? throw new InvalidOperationException("SettingsStore.LoadAsync was not found");
        var saveTask = saveMethod.Invoke(null, [expected, CancellationToken.None]) as Task
            ?? throw new InvalidOperationException("SettingsStore.SaveAsync did not return a task");
        await saveTask.ConfigureAwait(false);
        var loadTask = loadMethod.Invoke(null, [CancellationToken.None]) as Task
            ?? throw new InvalidOperationException("SettingsStore.LoadAsync did not return a task");
        await loadTask.ConfigureAwait(false);
        var actual = loadTask.GetType().GetProperty("Result")?.GetValue(loadTask) as LiteSettings
            ?? throw new InvalidOperationException("SettingsStore.LoadAsync did not return LiteSettings");

        Require(actual.ArchiveBrowser == expected.ArchiveBrowser, "archive filters did not round-trip through portable settings");
        Require(actual.TextSearch == expected.TextSearch, "text-search filters did not round-trip through portable settings");
        Require(actual.WindowPlacement == expected.WindowPlacement, "window placement did not round-trip through portable settings");
        Require(actual.WorkspaceLayout == expected.WorkspaceLayout, "split-pane widths did not round-trip through portable settings");
        Require(
            actual.ArchiveColumnLayout?.SequenceEqual(expected.ArchiveColumnLayout!) == true,
            "archive column widths/order did not round-trip through portable settings");
        Require(
            actual.TextSearchColumnLayout?.SequenceEqual(expected.TextSearchColumnLayout!) == true,
            "text-search column widths/order did not round-trip through portable settings");

        var portableRoot = Path.GetFullPath(Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DATA_ROOT")!);
        var settingsPath = Path.Combine(portableRoot, "settings.json");
        var json = await File.ReadAllTextAsync(settingsPath).ConfigureAwait(false);
        Require(
            json.Contains("\"archive_browser\"", StringComparison.Ordinal)
            && json.Contains("\"window_placement\"", StringComparison.Ordinal)
            && json.Contains("\"workspace_layout\"", StringComparison.Ordinal),
            "portable settings do not use the expected stable snake-case sections");

        await RunOnWpfDispatcherAsync(() =>
        {
            var browser = new ArchiveBrowserViewModel(
                null!,
                expected.ArchiveRoot,
                _ => { },
                (_, _) => ArchiveCacheMode.Persistent,
                expected.ArchiveSortField,
                expected.ArchiveSortDescending,
                actual.ArchiveBrowser);
            var search = new TextSearchViewModel(null!, () => null, _ => { }, actual.TextSearch);
            Require(browser.PathFilter == "character/model", "archive path filter was not restored into the view model");
            Require(browser.ExtensionFilter == ".pac;.pam", "archive extension filter was not restored into the view model");
            Require(browser.PackageFilter == "base", "archive package filter was not restored into the view model");
            Require(browser.PreviewableOnly, "previewable-only filter was not restored into the view model");
            Require(browser.ViewMode == ArchiveViewMode.CategoriesAndFolders, "archive view filter was not restored into the view model");
            Require(browser.SelectedFolder?.Path == "character/model/player", "folder filter was not ready before the first archive query");
            Require(browser.SelectedRole.Role == ArchiveEntryRole.Model, "role filter was not restored into the view model");
            Require(browser.CollisionPolicy == ExportCollisionPolicy.Overwrite, "export collision policy was not restored");
            Require(browser.ManifestFormat == ExportManifestFormat.Csv, "export manifest format was not restored");
            Require(search.SourceKind == TextSearchSourceKind.LooseFolder, "text-search source was not restored");
            Require(search.LooseFolder == "C:\\loose", "text-search loose folder was not restored");
            Require(search.Query == "material_name", "text-search query was not restored");
            Require(search.PathFilter == "character", "text-search path filter was not restored");
            Require(search.Extensions == ".xml;.material", "text-search extensions were not restored");
            Require(search.UseRegularExpression && search.CaseSensitive, "text-search boolean filters were not restored");
            browser.RequestShutdown();
            search.RequestShutdown();
            return Task.CompletedTask;
        }).ConfigureAwait(false);
    }

    private static Task TestWpfThemesAsync()
    {
        var appRoot = Path.Combine(
            FindRepositoryRoot(),
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.App");
        var themeRoot = Path.Combine(appRoot, "Themes");
        var themePaths = Directory.GetFiles(themeRoot, "Theme.*.xaml", SearchOption.TopDirectoryOnly);
        Require(themePaths.Length == 3, "Archive Lite must ship exactly three selectable color themes");

        var requiredKeys = new[]
        {
            "WindowBackgroundBrush",
            "SurfaceBrush",
            "InputBackgroundBrush",
            "TextBrush",
            "TextMutedBrush",
            "AccentBrush",
            "AccentTextBrush",
            "BorderBrush",
            "SelectionBrush",
        };
        foreach (var themePath in themePaths)
        {
            var document = System.Xml.Linq.XDocument.Load(themePath);
            var keys = document.Root!
                .Elements()
                .Select(element => element.Attributes().FirstOrDefault(attribute => attribute.Name.LocalName == "Key")?.Value)
                .Where(static key => key is not null)
                .ToHashSet(StringComparer.Ordinal);
            Require(
                requiredKeys.All(requiredKey => keys.Contains(requiredKey)),
                $"{Path.GetFileName(themePath)} is missing a shared theme resource");
        }

        var window = System.Xml.Linq.XDocument.Load(Path.Combine(appRoot, "MainWindow.xaml"));
        var progressBindings = window
            .Descendants()
            .Where(element => element.Name.LocalName == "ProgressBar")
            .SelectMany(element => new[] { (string?)element.Attribute("Value"), (string?)element.Attribute("IsIndeterminate") })
            .Where(static value => value?.StartsWith("{Binding", StringComparison.Ordinal) == true)
            .ToArray();
        Require(progressBindings.Length >= 2, "MainWindow has no bound progress indicator to validate");
        Require(
            progressBindings.All(static binding => binding!.Contains("Mode=OneWay", StringComparison.Ordinal)),
            "a read-only progress property uses WPF's default TwoWay binding");
        return Task.CompletedTask;
    }

    private static Task TestModernShellAsync()
    {
        var appRoot = Path.Combine(
            FindRepositoryRoot(),
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.App");
        var window = System.Xml.Linq.XDocument.Load(Path.Combine(appRoot, "MainWindow.xaml"));
        Require(
            string.Equals((string?)window.Root?.Attribute("WindowStyle"), "None", StringComparison.Ordinal),
            "MainWindow is still using the bare native window shell");
        Require(
            window.Descendants().Any(element => element.Name.LocalName == "WindowChrome"),
            "MainWindow has no resizable custom window chrome");
        Require(
            window.Descendants().Any(element => ((string?)element.Attribute("Command"))?.Contains("DetectGameCommand", StringComparison.Ordinal) == true),
            "MainWindow has no game-folder detection action");
        Require(
            window.Descendants().Any(element => ((string?)element.Attribute("Command"))?.Contains("ExportMeshCommand", StringComparison.Ordinal) == true),
            "MainWindow has no selected PAC/PAM mesh export action");
        Require(
            window.Descendants().Any(element => ((string?)element.Attribute("Text"))?.Contains("CacheHealthLabel", StringComparison.Ordinal) == true),
            "MainWindow does not expose archive cache health");

        var searchQuery = window.Descendants()
            .Single(element => element.Name.LocalName == "TextBox"
                && ((string?)element.Attribute("Text"))?.Contains("TextSearch.Query", StringComparison.Ordinal) == true);
        Require(
            searchQuery.Descendants().Any(element => element.Name.LocalName == "KeyBinding"
                && string.Equals((string?)element.Attribute("Key"), "Enter", StringComparison.Ordinal)
                && ((string?)element.Attribute("Command"))?.Contains("TextSearch.SearchCommand", StringComparison.Ordinal) == true),
            "the main text query does not start searching when Enter is pressed");

        var controls = System.Xml.Linq.XDocument.Load(Path.Combine(appRoot, "Themes", "Controls.xaml"));
        var styleKeys = controls.Root!
            .Elements()
            .Select(element => element.Attributes().FirstOrDefault(attribute => attribute.Name.LocalName == "Key")?.Value)
            .Where(static key => key is not null)
            .ToHashSet(StringComparer.Ordinal);
        Require(styleKeys.Contains("WindowCaptionButtonStyle"), "custom chrome has no theme-aware caption button style");
        Require(styleKeys.Contains("TopBarComboBoxStyle"), "custom chrome has no compact top-bar selector style");
        Require(styleKeys.Contains("WorkspaceNavigationButtonStyle"), "title row has no shared workspace navigation style");
        Require(styleKeys.Contains("WorkspaceContentTabControlStyle"), "workspace content has no headerless tab host style");
        var navigationButtons = window.Descendants()
            .Where(element => element.Name.LocalName == "ToggleButton"
                && string.Equals((string?)element.Attribute("Click"), "OnWorkspaceNavigationClick", StringComparison.Ordinal))
            .ToArray();
        Require(navigationButtons.Length == 2, "Archive Browser and Text Search were not both moved into the title row");
        var topTabs = window.Descendants().Single(element => element.Name.LocalName == "TabControl");
        Require(
            string.Equals((string?)topTabs.Attribute("Margin"), "16,8,16,10", StringComparison.Ordinal)
            && ((string?)topTabs.Attribute("Style"))?.Contains("WorkspaceContentTabControlStyle", StringComparison.Ordinal) == true
            && topTabs.Elements().Where(element => element.Name.LocalName == "TabItem")
                .SelectMany(element => element.Elements().Where(child => child.Name.LocalName == "Grid"))
                .All(element => string.Equals((string?)element.Attribute("Margin"), "0", StringComparison.Ordinal)),
            "workspace content still stacks a separate tab row or duplicate page margins");
        Require(
            string.Equals((string?)topTabs.Attribute("SelectedIndex"), "0", StringComparison.Ordinal),
            "Archive Browser is not the explicit default startup workspace");
        var namedLayoutElements = window.Descendants()
            .SelectMany(element => element.Attributes()
                .Where(attribute => attribute.Name.LocalName == "Name")
                .Select(static attribute => attribute.Value))
            .ToHashSet(StringComparer.Ordinal);
        Require(
            new[]
            {
                "ArchiveFilterColumn",
                "ArchivePreviewColumn",
                "TextSearchFilterColumn",
                "TextSearchPreviewColumn",
                "TextSearchResultsGrid",
            }.All(namedLayoutElements.Contains),
            "user-resizable panes or result columns are not addressable for persistence");
        var windowSource = File.ReadAllText(Path.Combine(appRoot, "MainWindow.xaml.cs"));
        Require(
            windowSource.Split("WorkspaceTabs.SelectedIndex = 0;", StringSplitOptions.None).Length >= 3,
            "startup does not defensively restore Archive Browser after XAML initialization and load");
        Require(
            windowSource.Contains("CaptureUiState();", StringComparison.Ordinal)
            && windowSource.Contains("CaptureWindowPlacement()", StringComparison.Ordinal)
            && windowSource.Contains("CaptureGridColumnLayout", StringComparison.Ordinal),
            "window, pane, or column resizing is not captured during orderly shutdown");
        var controlsSource = File.ReadAllText(Path.Combine(appRoot, "Themes", "Controls.xaml"));
        Require(
            !controlsSource.Contains("<TabPanel", StringComparison.Ordinal)
            && controlsSource.Contains("CornerRadius=\"9\"", StringComparison.Ordinal)
            && controlsSource.Contains("BorderThickness=\"{TemplateBinding BorderThickness}\"", StringComparison.Ordinal),
            "title-row navigation still uses the clipped secondary tab panel");

        var cacheDialog = System.Xml.Linq.XDocument.Load(
            Path.Combine(appRoot, "Dialogs", "ArchiveCacheChoiceDialog.xaml"));
        Require(
            string.Equals((string?)cacheDialog.Root?.Attribute("WindowStyle"), "None", StringComparison.Ordinal),
            "the cache choice still uses a bare native dialog shell");
        Require(
            cacheDialog.Descendants().Count(element => element.Name.LocalName == "Button"
                && ((string?)element.Attribute("Click") is "OnPersistentClick" or "OnSessionOnlyClick")) == 2,
            "the cache dialog does not expose both persistent and session-only choices");
        Require(
            cacheDialog.Descendants().Where(element => element.Name.LocalName == "TextBlock")
                .Any(element => string.Equals((string?)element.Attribute("TextWrapping"), "Wrap", StringComparison.Ordinal)),
            "cache choice explanations cannot wrap safely");
        Require(
            string.Equals((string?)cacheDialog.Root?.Attribute("AllowsTransparency"), "True", StringComparison.OrdinalIgnoreCase)
            && string.Equals((string?)cacheDialog.Root?.Attribute("Background"), "Transparent", StringComparison.OrdinalIgnoreCase),
            "cache dialog does not use a transparent rounded host window");
        Require(
            !cacheDialog.Descendants().Any(element => element.Name.LocalName == "WindowChrome"),
            "cache dialog still combines WindowChrome with rounded content and can expose white corner arcs");
        var cacheDialogFrame = cacheDialog.Descendants().Single(element =>
            element.Attributes().Any(attribute => attribute.Name.LocalName == "Name" && attribute.Value == "CacheDialogFrame"));
        Require(
            string.Equals((string?)cacheDialogFrame.Attribute("Margin"), "12", StringComparison.Ordinal)
            && string.Equals((string?)cacheDialogFrame.Attribute("CornerRadius"), "14", StringComparison.Ordinal),
            "cache dialog shadow and rounded frame are not inset safely from the window edge");

        var archiveViewModelSource = File.ReadAllText(
            Path.Combine(appRoot, "ViewModels", "ArchiveBrowserViewModel.cs"));
        Require(
            archiveViewModelSource.Contains("ChooseAndOpenArchiveAsync(false", StringComparison.Ordinal)
            && archiveViewModelSource.Contains("ChooseAndOpenArchiveAsync(true", StringComparison.Ordinal),
            "Load and Refresh do not share the cache-choice flow");
        return Task.CompletedTask;
    }

    private static Task TestArchiveGridFeaturesAsync()
    {
        var repositoryRoot = FindRepositoryRoot();
        var appRoot = Path.Combine(
            repositoryRoot,
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.App");
        var window = System.Xml.Linq.XDocument.Load(Path.Combine(appRoot, "MainWindow.xaml"));
        var archiveGrid = window
            .Descendants()
            .Single(element => element.Name.LocalName == "DataGrid"
                && element.Attributes().Any(attribute => attribute.Name.LocalName == "Name" && attribute.Value == "ArchiveGrid"));
        Require(
            string.Equals((string?)archiveGrid.Attribute("CanUserSortColumns"), "True", StringComparison.OrdinalIgnoreCase),
            "archive grid column sorting is disabled");
        Require(
            string.Equals((string?)archiveGrid.Attribute("CanUserReorderColumns"), "True", StringComparison.OrdinalIgnoreCase),
            "archive grid column reordering is disabled");
        Require(
            string.Equals((string?)archiveGrid.Attribute("SelectionMode"), "Extended", StringComparison.OrdinalIgnoreCase)
            && string.Equals((string?)archiveGrid.Attribute("SelectionChanged"), "OnArchiveGridSelectionChanged", StringComparison.Ordinal),
            "archive grid does not support exporting multiple selected files");
        Require(
            double.TryParse((string?)archiveGrid.Attribute("MinColumnWidth"), out var minimumColumnWidth)
            && minimumColumnWidth >= 70,
            "archive grid allows columns to collapse into unreadable slivers");
        Require(
            archiveGrid.Attributes().Any(attribute =>
                attribute.Name.LocalName.EndsWith("HorizontalScrollBarVisibility", StringComparison.Ordinal)
                && string.Equals(attribute.Value, "Auto", StringComparison.Ordinal)),
            "archive grid has no horizontal overflow path for user-selected columns");
        var sortMembers = archiveGrid
            .Descendants()
            .Select(element => (string?)element.Attribute("SortMemberPath"))
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .ToHashSet(StringComparer.Ordinal);
        var expectedSortMembers = new[]
        {
            nameof(ArchiveSortField.Name),
            nameof(ArchiveSortField.KnownName),
            nameof(ArchiveSortField.NameEvidence),
            nameof(ArchiveSortField.Extension),
            nameof(ArchiveSortField.Role),
            nameof(ArchiveSortField.OriginalSize),
            nameof(ArchiveSortField.StoredSize),
            nameof(ArchiveSortField.Compression),
            nameof(ArchiveSortField.Package),
            nameof(ArchiveSortField.Path),
        };
        Require(expectedSortMembers.All(sortMembers.Contains), "archive grid is missing a sortable requested column");
        Require(
            window.Descendants().Any(element => element.Attributes().Any(
                attribute => attribute.Name.LocalName == "Name" && attribute.Value == "ArchiveColumnChooser")),
            "archive grid has no column chooser");
        foreach (var commandName in new[]
        {
            "ExportSelectedCommand",
            "ExportFolderCommand",
            "ExportFilteredCommand",
            "AssociatedAssets.ExportSelectedCommand",
            "AssociatedAssets.ExportFamilyCommand",
        })
        {
            Require(
                window.Descendants().Any(element => ((string?)element.Attribute("Command"))?.Contains(commandName, StringComparison.Ordinal) == true),
                $"Archive Browser does not expose {commandName}");
        }
        var associatedAssetsList = window.Descendants().Single(element =>
            element.Attributes().Any(attribute => attribute.Name.LocalName == "Name" && attribute.Value == "AssociatedAssetsList"));
        Require(
            string.Equals((string?)associatedAssetsList.Attribute("SelectionMode"), "Extended", StringComparison.OrdinalIgnoreCase)
            && string.Equals((string?)associatedAssetsList.Attribute("SelectionChanged"), "OnAssociatedAssetsSelectionChanged", StringComparison.Ordinal),
            "associated-assets export does not support multiple selected family rows");
        Require(
            window.Descendants()
                .Where(element => element.Name.LocalName == "ComboBox")
                .Any(element => ((string?)element.Attribute("ItemsSource"))?.Contains("ExtensionChoicesView", StringComparison.Ordinal) == true
                    && element.Descendants().Any(descendant => descendant.Name.LocalName == "GroupStyle")),
            "extension filter is not a categorized picker");
        var controlsSource = File.ReadAllText(Path.Combine(appRoot, "Themes", "Controls.xaml"));
        Require(
            controlsSource.Contains("<ItemsPresenter KeyboardNavigation.DirectionalNavigation=\"Contained\"", StringComparison.Ordinal)
            && !controlsSource.Contains("<StackPanel IsItemsHost=\"True\"", StringComparison.Ordinal),
            "the shared ComboBox template cannot expand grouped extension children");
        Require(
            window.Descendants().Any(element => ((string?)element.Attribute("Text"))?.Contains("ItemCount", StringComparison.Ordinal) == true)
            && window.Descendants().Any(element => ((string?)element.Attribute("Text"))?.Contains("{Binding Label}", StringComparison.Ordinal) == true),
            "extension categories do not expose both their extensions and counts");

        var archiveViewModelSource = File.ReadAllText(Path.Combine(appRoot, "ViewModels", "ArchiveBrowserViewModel.cs"));
        Require(
            archiveViewModelSource.Contains("ExtensionChoicesView.Refresh();", StringComparison.Ordinal)
            && !archiveViewModelSource.Contains("ExtensionChoicesView.DeferRefresh", StringComparison.Ordinal),
            "extension facets can mutate the collection while its WPF view refresh is deferred");
        Require(
            archiveViewModelSource.Contains("OnPropertyChanged(nameof(ViewMode));", StringComparison.Ordinal)
            && archiveViewModelSource.Contains("OnPropertyChanged(nameof(SortField));", StringComparison.Ordinal)
            && archiveViewModelSource.Contains("OnPropertyChanged(nameof(CollisionPolicy));", StringComparison.Ordinal)
            && archiveViewModelSource.Contains("OnPropertyChanged(nameof(ManifestFormat));", StringComparison.Ordinal),
            "live localization does not restore value-selected ComboBox selections after replacing their options");

        var windowSource = File.ReadAllText(Path.Combine(appRoot, "MainWindow.xaml.cs"));
        Require(
            windowSource.Contains("LegacyDefaultArchiveColumns", StringComparison.Ordinal),
            "legacy default column layouts are not migrated to the readable modern default");

        var hostSource = File.ReadAllText(Path.Combine(appRoot, "Controls", "DotNetModelPreviewHost.cs"));
        Require(hostSource.Contains("--simple-preview", StringComparison.Ordinal), "Archive Lite does not request the simple renderer surface");
        var previewSource = File.ReadAllText(Path.Combine(
            repositoryRoot,
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.Core",
            "NativeModelPreviewService.cs"));
        Require(previewSource.Contains("[\"use_textures_by_default\"] = false", StringComparison.Ordinal), "native PAC preview still requests textures");
        var rendererProgram = File.ReadAllText(Path.Combine(
            repositoryRoot,
            "tools",
            "dotnet_mesh_editor_experiment",
            "Program.cs"));
        Require(
            rendererProgram.Contains("_presentationGridVisible = scene.GridVisible", StringComparison.Ordinal)
            && rendererProgram.Contains("_presentationGizmoVisible = scene.GizmoVisible", StringComparison.Ordinal),
            "the renderer presentation contexts can restore the grid or gizmo over a hidden scene setting");
        var materialShader = File.ReadAllText(Path.Combine(
            repositoryRoot,
            "tools",
            "dotnet_mesh_editor_experiment",
            "D3D11MaterialShaders.hlsl"));
        Require(
            materialShader.Contains("per-part tone shift", StringComparison.Ordinal)
            && materialShader.Contains("keyLight * 0.48f", StringComparison.Ordinal),
            "textureless preview shading does not preserve enough part and contour separation");
        return Task.CompletedTask;
    }

    private static async Task TestAssociatedAssetsAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAssociatedAssetsAsync().ConfigureAwait(false);
        var beforePamt = await Sha256Async(fixture.Pamt).ConfigureAwait(false);
        var beforePaz = await Sha256Async(fixture.Paz).ConfigureAwait(false);
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native);
        var opened = await sessions.OpenAsync(
            new OpenArchiveRequest(fixture.Root, true, ArchiveCacheMode.SessionOnly),
            CancellationToken.None).ConfigureAwait(false);
        var query = new ArchiveQueryService(sessions);
        var modelPage = await query.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, PathText: "character/model/hero.pac"),
            1,
            CancellationToken.None).ConfigureAwait(false);
        var model = modelPage.Entries.Single(entry => entry.Path == "character/model/hero.pac");
        var progress = new List<ProgressUpdate>();
        var associations = new ArchiveAssociationService(sessions, native);
        var result = await associations.FindAsync(
            new FindAssociatedAssetsRequest(opened.SessionId, model.EntryId),
            update =>
            {
                progress.Add(update);
                return Task.CompletedTask;
            },
            CancellationToken.None).ConfigureAwait(false);

        Require(result.Assets.Count == 6, "the synthetic model family did not resolve all six companions");
        Require(!result.Truncated, "the bounded synthetic model family was unexpectedly truncated");
        Require(result.ScannedEntries == opened.EntryCount, "associated assets did not use one bounded index pass");
        Require(progress.Any(update => update.Phase == "association_scan"), "associated-asset scan progress was not published");
        Require(
            result.Assets.Single(asset => asset.Entry.Path == "character/modelproperty/hero.pac_xml").Evidence
                == AssociationEvidence.ExactCompanion,
            "PAC material sidecar was not identified as an expected companion");
        Require(
            result.Assets.Count(asset => asset.Category == AssociatedAssetCategory.Texture
                && asset.Evidence == AssociationEvidence.ExplicitReference) == 2,
            "material-sidecar DDS references were not resolved as explicit textures");
        Require(
            result.Assets.Any(asset => asset.Category == AssociatedAssetCategory.Physics
                && asset.Entry.Path == "character/physics/hero.hkx"),
            "explicit HKX physics reference was not categorized");
        Require(
            result.Assets.Any(asset => asset.Category == AssociatedAssetCategory.MeshMetadata
                && asset.Entry.Path == "character/model/hero.meshinfo"),
            "same-family mesh metadata was not found");
        Require(
            result.Assets.Any(asset => asset.Category == AssociatedAssetCategory.PrefabMetadata
                && asset.Entry.Path == "character/model/hero.prefab"),
            "same-family prefab metadata was not found");
        Require(
            result.Assets.All(asset => asset.Entry.Path != "unrelated/other.dds"),
            "an unrelated texture leaked into the model family");
        Require(
            result.Assets.Single(asset => asset.Entry.Path.EndsWith(".pac_xml", StringComparison.Ordinal)).Entry.Role
                == ArchiveEntryRole.Text,
            "material sidecars are not previewable as text");

        var familyExportRoot = Path.Combine(fixture.OutputRoot, "family");
        var exportService = new ArchiveExportService(
            sessions,
            query,
            native,
            new NativeModelExportService(new NativeModelPreviewService()));
        var familyEntryIds = new[] { model.EntryId }
            .Concat(result.Assets.Select(static asset => asset.Entry.EntryId))
            .ToArray();
        var familyExport = await exportService.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.RawEntries,
                familyExportRoot,
                familyEntryIds,
                null),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(familyExport.Exported == 7 && familyExport.Failed == 0, "asset-family raw export did not include the source and six companions");
        Require(
            File.Exists(Path.Combine(familyExportRoot, "base", "character", "model", "hero.pac"))
            && File.Exists(Path.Combine(familyExportRoot, "base", "character", "texture", "hero_body_d.dds")),
            "asset-family export did not preserve the full-app package and virtual folder structure");

        var diffuse = result.Assets.Single(asset => asset.Entry.Path.EndsWith("hero_body_d.dds", StringComparison.Ordinal)).Entry;
        var reverse = await associations.FindAsync(
            new FindAssociatedAssetsRequest(opened.SessionId, diffuse.EntryId),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(reverse.ScannedEntries == 0, "a learned reverse family performed another full index scan");
        Require(reverse.Assets.Any(asset => asset.Entry.EntryId == model.EntryId), "DDS reverse lookup did not return its PAC model");
        Require(
            reverse.Assets.Any(asset => asset.Entry.Path == "character/modelproperty/hero.pac_xml"),
            "DDS reverse lookup did not return its material sidecar");

        var unrelatedPage = await query.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, PathText: "unrelated/other.dds"),
            2,
            CancellationToken.None).ConfigureAwait(false);
        using (var cancelled = new CancellationTokenSource())
        {
            cancelled.Cancel();
            await RequireThrowsAsync<OperationCanceledException>(() => associations.FindAsync(
                new FindAssociatedAssetsRequest(opened.SessionId, unrelatedPage.Entries.Single().EntryId),
                null,
                cancelled.Token)).ConfigureAwait(false);
        }

        var repositoryRoot = FindRepositoryRoot();
        var appRoot = Path.Combine(repositoryRoot, "apps", "Cdmw.ArchiveLite", "src", "Cdmw.ArchiveLite.App");
        var windowSource = File.ReadAllText(Path.Combine(appRoot, "MainWindow.xaml"));
        Require(
            windowSource.Contains("AssociatedAssets.AssetsView", StringComparison.Ordinal)
            && windowSource.Contains("AssociatedAssets.FindCommand", StringComparison.Ordinal)
            && windowSource.Contains("AssociatedAssets.ShowInBrowserCommand", StringComparison.Ordinal)
            && windowSource.Contains("AssociatedAssets.ExportSelectedCommand", StringComparison.Ordinal)
            && windowSource.Contains("AssociatedAssets.ExportFamilyCommand", StringComparison.Ordinal),
            "Archive Browser does not expose grouped find, open, and export associated-assets controls");
        var viewModelSource = File.ReadAllText(Path.Combine(appRoot, "ViewModels", "AssociatedAssetsViewModel.cs"));
        Require(
            viewModelSource.Contains("CancellationTokenSource.CreateLinkedTokenSource", StringComparison.Ordinal)
            && viewModelSource.Contains("IsCurrent(sessionId, source.EntryId, generation)", StringComparison.Ordinal)
            && viewModelSource.Contains("RequestShutdown()", StringComparison.Ordinal)
            && viewModelSource.Contains("CancelOperation(Interlocked.Exchange", StringComparison.Ordinal),
            "associated-asset UI work is missing cancellation, stale-result, or shutdown ownership");

        Require(await Sha256Async(fixture.Pamt).ConfigureAwait(false) == beforePamt, "associated-asset lookup changed PAMT bytes");
        Require(await Sha256Async(fixture.Paz).ConfigureAwait(false) == beforePaz, "associated-asset lookup changed PAZ bytes");
    }

    private static Task TestExportPathPolicyAsync()
    {
        Require(ExportPathPolicy.NormalizeVirtualPath("folder/file.txt") == "folder/file.txt", "safe path changed");
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("../escape.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("C:/escape.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("//server/share.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("folder/bad. "));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("folder/CON.txt"));
        RequireThrows<InvalidDataException>(() => ExportPathPolicy.NormalizeVirtualPath("LPT1/report.txt"));
        return Task.CompletedTask;
    }

    private static async Task TestCacheMaintenanceAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cdmw-archive-lite-cache-test-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            for (var index = 0; index < 3; index++)
            {
                var path = Path.Combine(root, $"cache-{index}.bin");
                await File.WriteAllBytesAsync(path, new byte[1_000]).ConfigureAwait(false);
                File.SetLastWriteTimeUtc(path, DateTime.UtcNow.AddHours(index - 4));
            }
            var result = ArchiveLiteCacheMaintenance.Prune(root, 1_500);
            Require(result.BytesBefore == 3_000, "cache size accounting is wrong");
            Require(result.BytesAfter <= 1_350 && result.FilesRemoved == 2, "cache did not prune to its low-water mark");
            Require(File.Exists(Path.Combine(root, "cache-2.bin")), "cache pruning did not retain the newest entry");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
    }

    private static async Task TestStandaloneRuntimeAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cdmw-archive-lite-standalone-test-{Guid.NewGuid():N}");
        try
        {
            var payloadBytes = CreateStandaloneTestPayload();
            await using var firstPayload = new MemoryStream(payloadBytes, writable: false);
            var extracted = await StandaloneRuntime.EnsureExtractedAsync(
                firstPayload,
                root,
                CancellationToken.None).ConfigureAwait(false);
            var workerPath = Path.Combine(extracted, "CdmwArchiveLite.Worker.exe");
            var markerPath = Path.Combine(extracted, StandaloneRuntime.ReadyMarkerName);
            Require(File.Exists(Path.Combine(extracted, "CdmwArchiveLite.exe")), "standalone application was not extracted");
            Require(File.Exists(workerPath), "standalone worker was not extracted");
            Require(File.Exists(markerPath), "standalone ready marker was not published");
            var markerTimestamp = File.GetLastWriteTimeUtc(markerPath);
            var markerContents = await File.ReadAllTextAsync(markerPath).ConfigureAwait(false);

            await using var secondPayload = new MemoryStream(payloadBytes, writable: false);
            var reused = await StandaloneRuntime.EnsureExtractedAsync(
                secondPayload,
                root,
                CancellationToken.None).ConfigureAwait(false);
            Require(reused == extracted, "standalone runtime did not reuse its content-addressed cache");
            Require(File.GetLastWriteTimeUtc(markerPath) == markerTimestamp, "standalone cache reuse rewrote its ready marker");
            Require(await File.ReadAllTextAsync(markerPath).ConfigureAwait(false) == markerContents, "standalone cache marker changed during reuse");

            File.Delete(workerPath);
            await using var repairPayload = new MemoryStream(payloadBytes, writable: false);
            var repaired = await StandaloneRuntime.EnsureExtractedAsync(
                repairPayload,
                root,
                CancellationToken.None).ConfigureAwait(false);
            Require(repaired == extracted && File.Exists(workerPath), "standalone runtime did not rebuild a damaged cache");
            Require(
                Directory.GetDirectories(Path.Combine(root, "payloads"), "*.invalid-*").Length == 1,
                "damaged standalone runtime was not quarantined before replacement");

            var maliciousPayloadBytes = CreateStandaloneTraversalPayload();
            await using var maliciousPayload = new MemoryStream(maliciousPayloadBytes, writable: false);
            await RequireThrowsAsync<InvalidDataException>(() => StandaloneRuntime.EnsureExtractedAsync(
                maliciousPayload,
                root,
                CancellationToken.None)).ConfigureAwait(false);
            Require(!File.Exists(Path.Combine(root, "escape.txt")), "standalone payload escaped its runtime root");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
    }

    private static byte[] CreateStandaloneTestPayload()
    {
        var files = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["CdmwArchiveLite.exe"] = Encoding.UTF8.GetBytes("test application"),
            ["CdmwArchiveLite.Worker.exe"] = Encoding.UTF8.GetBytes("test worker"),
            ["cdmw-archive-core.dll"] = Encoding.UTF8.GetBytes("test archive core"),
            ["preview/cdmw-preview-core.exe"] = Encoding.UTF8.GetBytes("test preview"),
            ["indexer/cdmw-archive-accelerator.exe"] = Encoding.UTF8.GetBytes("test indexer"),
            ["mesh/cdmw-mesh-core.exe"] = Encoding.UTF8.GetBytes("test mesh exporter"),
            ["renderer/cdmw-mesh-dotnet-editor.exe"] = Encoding.UTF8.GetBytes("test renderer"),
        };
        var manifest = JsonSerializer.SerializeToUtf8Bytes(files.Select(file => new
        {
            path = file.Key,
            bytes = file.Value.LongLength,
            sha256 = Convert.ToHexString(SHA256.HashData(file.Value)).ToLowerInvariant(),
        }));

        using var payload = new MemoryStream();
        using (var archive = new ZipArchive(payload, ZipArchiveMode.Create, leaveOpen: true))
        {
            foreach (var file in files)
            {
                WriteZipEntry(archive, $"CDMW-Archive-Lite-win-x64/{file.Key}", file.Value);
            }
            WriteZipEntry(archive, "CDMW-Archive-Lite-win-x64/PACKAGE-CONTENTS.json", manifest);
        }
        return payload.ToArray();
    }

    private static byte[] CreateStandaloneTraversalPayload()
    {
        using var payload = new MemoryStream();
        using (var archive = new ZipArchive(payload, ZipArchiveMode.Create, leaveOpen: true))
        {
            WriteZipEntry(archive, "CDMW-Archive-Lite-win-x64/../../escape.txt", Encoding.UTF8.GetBytes("unsafe"));
        }
        return payload.ToArray();
    }

    private static void WriteZipEntry(ZipArchive archive, string path, byte[] contents)
    {
        var entry = archive.CreateEntry(path, CompressionLevel.Fastest);
        using var output = entry.Open();
        output.Write(contents);
    }

    private static async Task TestGameInstallDiscoveryAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        Require(
            GameInstallDiscoveryService.LooksLikeArchivePackageRoot(Path.GetDirectoryName(fixture.Pamt)!),
            "synthetic archive root was not recognized as a game package root");
        Require(
            !GameInstallDiscoveryService.LooksLikeArchivePackageRoot(fixture.OutputRoot),
            "an ordinary output folder was misidentified as a game package root");

        const string vdf = """
            "libraryfolders"
            {
                "0" { "path" "C:\\Program Files (x86)\\Steam" }
                "1" { "path" "D:\\Games\\Steam" }
            }
            """;
        var paths = GameInstallDiscoveryService.ParseSteamLibraryPaths(vdf);
        Require(paths.Contains(@"C:\Program Files (x86)\Steam", StringComparer.OrdinalIgnoreCase), "primary Steam library was not parsed");
        Require(paths.Contains(@"D:\Games\Steam", StringComparer.OrdinalIgnoreCase), "secondary Steam library was not parsed");
    }

    private static async Task TestArchiveCacheHealthAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var health = new ArchiveCacheHealthService();
        var missing = await health.InspectAsync(
            new ArchiveCacheHealthRequest(fixture.Root),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(missing.State == ArchiveCacheHealthState.Missing, "a never-opened archive cache was not reported missing");

        var native = new NativeArchiveCore();
        using (var sessions = new ArchiveSessionManager(native))
        {
            _ = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root, true),
                CancellationToken.None).ConfigureAwait(false);
        }

        var current = await health.InspectAsync(
            new ArchiveCacheHealthRequest(fixture.Root),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(current.State == ArchiveCacheHealthState.Current, "a verified archive cache was not reported current");

        var timestamp = File.GetLastWriteTimeUtc(fixture.Pamt);
        File.SetLastWriteTimeUtc(fixture.Pamt, timestamp.AddSeconds(2));
        var stale = await health.InspectAsync(
            new ArchiveCacheHealthRequest(fixture.Root),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(stale.State == ArchiveCacheHealthState.Stale, "changed archive source metadata did not mark the cache stale");
        Require(stale.ChangedSourceCount > 0, "stale cache did not report changed source files");
    }

    private static async Task TestArchiveCacheModesAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var sourceHashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            [fixture.Pamt] = await Sha256Async(fixture.Pamt).ConfigureAwait(false),
            [fixture.Paz] = await Sha256Async(fixture.Paz).ConfigureAwait(false),
            [fixture.Pathc] = await Sha256Async(fixture.Pathc).ConfigureAwait(false),
        };
        var native = new NativeArchiveCore();
        string persistentPath;
        string temporaryPath;
        using (var sessions = new ArchiveSessionManager(native))
        {
            var built = await sessions.OpenAsync(
                new OpenArchiveRequest(
                    fixture.Root,
                    ForceRefresh: true,
                    CacheMode: ArchiveCacheMode.Persistent),
                CancellationToken.None).ConfigureAwait(false);
            persistentPath = sessions.GetRequired(built.SessionId).Index.Path;
            Require(built.CacheMode == ArchiveCacheMode.Persistent, "persistent cache mode was not returned");
            Require(!built.UsedCachedIndex, "a forced persistent build incorrectly reported a cache hit");
            Require(File.Exists(persistentPath), "persistent archive index was not retained");

            var reused = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root, CacheMode: ArchiveCacheMode.Persistent),
                CancellationToken.None).ConfigureAwait(false);
            Require(reused.UsedCachedIndex, "a verified persistent index was not reused");

            var originalPamt = await File.ReadAllBytesAsync(fixture.Pamt).ConfigureAwait(false);
            var originalTimestamp = File.GetLastWriteTimeUtc(fixture.Pamt);
            var changedPamt = originalPamt.ToArray();
            changedPamt[^1] ^= 0x01;
            await File.WriteAllBytesAsync(fixture.Pamt, changedPamt).ConfigureAwait(false);
            File.SetLastWriteTimeUtc(fixture.Pamt, originalTimestamp);
            try
            {
                await RequireThrowsAsync<ArchiveCacheRefreshRequiredException>(() => sessions.OpenAsync(
                    new OpenArchiveRequest(
                        fixture.Root,
                        CacheMode: ArchiveCacheMode.Persistent,
                        AllowCacheBuild: false),
                    CancellationToken.None)).ConfigureAwait(false);
            }
            finally
            {
                await File.WriteAllBytesAsync(fixture.Pamt, originalPamt).ConfigureAwait(false);
                File.SetLastWriteTimeUtc(fixture.Pamt, originalTimestamp);
            }

            var sessionOnly = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root, CacheMode: ArchiveCacheMode.SessionOnly),
                CancellationToken.None).ConfigureAwait(false);
            temporaryPath = sessions.GetRequired(sessionOnly.SessionId).Index.Path;
            Require(sessionOnly.CacheMode == ArchiveCacheMode.SessionOnly, "session-only cache mode was not returned");
            Require(!sessionOnly.UsedCachedIndex, "session-only loading reused a persistent index");
            Require(File.Exists(temporaryPath), "session-only index was not available for the live session");
            Require(
                !Path.GetFullPath(temporaryPath).Equals(Path.GetFullPath(persistentPath), StringComparison.OrdinalIgnoreCase),
                "session-only loading wrote into the persistent index path");
        }

        Require(File.Exists(persistentPath), "closing a session removed its persistent index");
        Require(!File.Exists(temporaryPath), "closing the worker session retained a one-time index");
        foreach (var (sourcePath, expectedHash) in sourceHashes)
        {
            Require(
                string.Equals(await Sha256Async(sourcePath).ConfigureAwait(false), expectedHash, StringComparison.Ordinal),
                $"archive cache loading changed source bytes: {sourcePath}");
        }
    }

    private static async Task TestStartupCacheAutoLoadAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var native = new NativeArchiveCore();
        using (var sessions = new ArchiveSessionManager(native))
        {
            _ = await sessions.OpenAsync(
                new OpenArchiveRequest(
                    fixture.Root,
                    ForceRefresh: true,
                    CacheMode: ArchiveCacheMode.Persistent),
                CancellationToken.None).ConfigureAwait(false);
        }

        var expectedPortableRoot = Path.GetFullPath(Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DATA_ROOT")!);
        var expectedCache = Path.Combine(expectedPortableRoot, "cache");
        Require(
            Path.GetFullPath(ArchiveLiteDataPaths.Root).Equals(expectedPortableRoot, StringComparison.OrdinalIgnoreCase),
            "worker data root did not honor the isolated portable root");
        Require(
            Path.GetFullPath(ArchiveLiteDataPaths.Cache).Equals(expectedCache, StringComparison.OrdinalIgnoreCase),
            "worker cache path did not honor the isolated portable cache root");
        var appDataPaths = typeof(MainWindowViewModel).Assembly.GetType("Cdmw.ArchiveLite.App.Services.AppDataPaths")
            ?? throw new InvalidOperationException("AppDataPaths type was not found");
        var appPortableRoot = appDataPaths.GetProperty("Root")?.GetValue(null) as string;
        Require(
            Path.GetFullPath(appPortableRoot!).Equals(expectedPortableRoot, StringComparison.OrdinalIgnoreCase),
            "application settings/log root did not honor the isolated portable root");
        foreach (var (propertyName, expectedPath) in new[]
        {
            ("Settings", Path.Combine(expectedPortableRoot, "settings.json")),
            ("Cache", expectedCache),
            ("Logs", Path.Combine(expectedPortableRoot, "logs")),
            ("Crash", Path.Combine(expectedPortableRoot, "crash")),
        })
        {
            var actualPath = appDataPaths.GetProperty(propertyName)?.GetValue(null) as string;
            Require(
                Path.GetFullPath(actualPath!).Equals(expectedPath, StringComparison.OrdinalIgnoreCase),
                $"application {propertyName.ToLowerInvariant()} path was not routed beside the executable");
        }

        await RunOnWpfDispatcherAsync(async () =>
        {
            var previousWorkerPath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_WORKER_PATH");
            Environment.SetEnvironmentVariable("CDMW_ARCHIVE_LITE_WORKER_PATH", FindWorkerOutputPath());
            WorkerProcessHost? worker = null;
            ArchiveBrowserViewModel? currentViewModel = null;
            ArchiveBrowserViewModel? changedViewModel = null;
            byte[]? originalPamt = null;
            DateTime originalTimestamp = default;
            try
            {
                worker = await WorkerProcessHost.StartAsync(CancellationToken.None);
                var promptCount = 0;
                ArchiveCacheMode? CacheChoice(string _, bool __)
                {
                    promptCount++;
                    return ArchiveCacheMode.Persistent;
                }

                LocalizationManager.ApplyCulture("en");
                currentViewModel = new ArchiveBrowserViewModel(worker, fixture.Root, _ => { }, CacheChoice);
                await currentViewModel.InitializeEnvironmentAsync(CancellationToken.None);
                Require(!string.IsNullOrWhiteSpace(currentViewModel.SessionId), "current persistent cache was not auto-loaded at startup");
                Require(currentViewModel.CacheHealthState == ArchiveCacheHealthState.Current, "auto-loaded cache was not reported current");
                Require(promptCount == 0, "startup auto-load displayed the manual cache-choice prompt");

                originalPamt = await File.ReadAllBytesAsync(fixture.Pamt);
                originalTimestamp = File.GetLastWriteTimeUtc(fixture.Pamt);
                var changedPamt = originalPamt.ToArray();
                changedPamt[^1] ^= 0x01;
                await File.WriteAllBytesAsync(fixture.Pamt, changedPamt);
                File.SetLastWriteTimeUtc(fixture.Pamt, originalTimestamp);

                changedViewModel = new ArchiveBrowserViewModel(worker, fixture.Root, _ => { }, CacheChoice);
                await changedViewModel.InitializeEnvironmentAsync(CancellationToken.None);
                Require(string.IsNullOrWhiteSpace(changedViewModel.SessionId), "hash-changed game files were silently reindexed at startup");
                Require(changedViewModel.CacheHealthState == ArchiveCacheHealthState.Stale, "hash change did not mark the startup cache stale");
                Require(changedViewModel.RefreshCommand.CanExecute(null), "manual Refresh was not enabled for a stale startup cache");
                Require(!changedViewModel.OpenCommand.CanExecute(null), "Open remained enabled for a stale startup cache");
                Require(
                    changedViewModel.CacheHealthDetail.Contains(LocalizationManager.Get("CacheRefreshRecommended"), StringComparison.Ordinal),
                    "stale startup cache did not recommend manual Refresh");
                Require(promptCount == 0, "stale startup inspection displayed a cache-choice prompt without user action");
            }
            finally
            {
                currentViewModel?.RequestShutdown();
                changedViewModel?.RequestShutdown();
                if (worker is not null)
                {
                    await worker.ShutdownAsync();
                }
                Environment.SetEnvironmentVariable("CDMW_ARCHIVE_LITE_WORKER_PATH", previousWorkerPath);
                if (originalPamt is not null)
                {
                    await File.WriteAllBytesAsync(fixture.Pamt, originalPamt);
                    File.SetLastWriteTimeUtc(fixture.Pamt, originalTimestamp);
                }
            }
        }).ConfigureAwait(false);
    }

    private static async Task TestNativeModelPreviewPackageAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"cdmw-archive-lite-model-preview-test-{Guid.NewGuid():N}");
        try
        {
            var geometryRoot = Path.Combine(root, "geometry");
            Directory.CreateDirectory(geometryRoot);
            var geometryPath = Path.Combine(geometryRoot, "batch_000.bin");
            using (var writer = new BinaryWriter(File.Create(geometryPath), Encoding.UTF8, leaveOpen: false))
            {
                foreach (var position in new[]
                {
                    new[] { -0.5f, 0.0f, 0.0f },
                    new[] { 0.5f, 0.0f, 0.0f },
                    new[] { 0.0f, 1.0f, 0.0f },
                })
                {
                    var vertex = new float[23];
                    vertex[0] = position[0];
                    vertex[1] = position[1];
                    vertex[2] = position[2];
                    vertex[5] = 1.0f;
                    vertex[9] = position[0] + 0.5f;
                    vertex[10] = position[1];
                    foreach (var value in vertex) writer.Write(value);
                }
            }
            var manifestPath = Path.Combine(root, "manifest.json");
            await File.WriteAllTextAsync(
                manifestPath,
                JsonSerializer.Serialize(new
                {
                    schema_version = 8,
                    backend = "d3d11",
                    batches = new[]
                    {
                        new
                        {
                            index = 0,
                            material_name = "synthetic_metal",
                            vertex_file = "geometry/batch_000.bin",
                            vertex_count = 3,
                            base_color = new[] { 0.3f, 0.45f, 0.6f },
                            roughness = 0.4f,
                            metalness = 0.8f,
                            specular = 0.5f,
                            material_category = "metal",
                            material_category_confidence = 0.9f,
                            material_response_promoted = true,
                            dds_textures = new Dictionary<string, object>(),
                        },
                    },
                }),
                Encoding.UTF8).ConfigureAwait(false);

            var geometryHash = await Sha256Async(geometryPath).ConfigureAwait(false);
            var result = await NativePreviewPackageAdapter.PrepareAsync(root, "synthetic:test", CancellationToken.None).ConfigureAwait(false);
            Require(result.BatchCount == 1 && result.VertexCount == 3, "native preview package counts are wrong");
            Require(File.Exists(Path.Combine(root, "net_materials.json")), "renderer materials sidecar was not created");
            Require(File.Exists(Path.Combine(root, "dotnet_scene.json")), "renderer scene sidecar was not created");
            Require(File.Exists(Path.Combine(root, "mesh.cdmeta.json")), "renderer metadata sidecar was not created");
            using (var scene = JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(root, "dotnet_scene.json")).ConfigureAwait(false)))
            {
                Require(!scene.RootElement.GetProperty("grid").GetProperty("visible").GetBoolean(), "read-only preview scene exposed the grid");
                Require(!scene.RootElement.GetProperty("gizmo").GetProperty("visible").GetBoolean(), "read-only preview scene exposed the edit gizmo");
                Require(scene.RootElement.GetProperty("interaction_mode").GetString() == "placement", "preview scene mode is wrong");
            }
            using (var materials = JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(root, "net_materials.json")).ConfigureAwait(false)))
            {
                Require(materials.RootElement.GetProperty("submeshes").GetArrayLength() == 1, "renderer material sidecar count is wrong");
                var submesh = materials.RootElement.GetProperty("submeshes")[0];
                Require(submesh.GetProperty("resolved_channels").GetRawText() == "{}", "mesh-only preview retained resolved textures");
                Require(string.IsNullOrEmpty(submesh.GetProperty("texture").GetString()), "mesh-only preview retained a base texture");
            }

            var exportRoot = Path.Combine(root, "exports");
            Directory.CreateDirectory(exportRoot);
            var exporter = new NativeModelExportService(new NativeModelPreviewService());
            var progressUpdates = new List<ProgressUpdate>();
            Task CaptureProgress(ProgressUpdate update)
            {
                progressUpdates.Add(update);
                return Task.CompletedTask;
            }
            var glbPath = Path.Combine(exportRoot, "triangle.glb");
            await exporter.ExportPackageAsync(
                root,
                "models/triangle.pac",
                ExportKind.Glb,
                glbPath,
                overwrite: false,
                CaptureProgress,
                "models/triangle.pac",
                CancellationToken.None).ConfigureAwait(false);
            var glb = await File.ReadAllBytesAsync(glbPath).ConfigureAwait(false);
            Require(glb.AsSpan(0, 4).SequenceEqual("glTF"u8), "GLB export has no glTF container signature");
            Require(BinaryPrimitives.ReadUInt32LittleEndian(glb.AsSpan(4, 4)) == 2, "GLB export version is not 2");
            Require(BinaryPrimitives.ReadUInt32LittleEndian(glb.AsSpan(8, 4)) == glb.Length, "GLB declared length is wrong");
            var jsonLength = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(glb.AsSpan(12, 4)));
            using (var glbDocument = JsonDocument.Parse(glb.AsMemory(20, jsonLength)))
            {
                Require(glbDocument.RootElement.GetProperty("meshes")[0].GetProperty("primitives").GetArrayLength() == 1, "GLB export lost its mesh primitive");
                Require(glbDocument.RootElement.GetProperty("materials").GetArrayLength() == 1, "GLB export lost its material identity");
                var views = glbDocument.RootElement.GetProperty("bufferViews");
                var binaryOffset = checked(20 + jsonLength + 8);
                var firstPositionOffset = binaryOffset + views[0].GetProperty("byteOffset").GetInt32();
                var firstUvOffset = binaryOffset + views[2].GetProperty("byteOffset").GetInt32();
                Require(
                    BinaryPrimitives.ReadSingleLittleEndian(glb.AsSpan(firstPositionOffset, 4)) == -0.5f,
                    "GLB export changed the first vertex position");
                Require(
                    BinaryPrimitives.ReadSingleLittleEndian(glb.AsSpan(firstUvOffset + 4, 4)) == 1.0f,
                    "GLB export did not apply the workbench UV convention");
            }

            var objPath = Path.Combine(exportRoot, "triangle.obj");
            await exporter.ExportPackageAsync(
                root,
                "models/triangle.pac",
                ExportKind.Obj,
                objPath,
                overwrite: false,
                CaptureProgress,
                "models/triangle.pac",
                CancellationToken.None).ConfigureAwait(false);
            var obj = await File.ReadAllTextAsync(objPath).ConfigureAwait(false);
            Require(obj.Contains("# Crimson Desert Mesh", StringComparison.Ordinal), "OBJ export did not use the workbench writer");
            Require(obj.Contains("f 1/1/1 2/2/2 3/3/3", StringComparison.Ordinal), "OBJ export has no triangle face");

            var fbxPath = Path.Combine(exportRoot, "triangle.fbx");
            await exporter.ExportPackageAsync(
                root,
                "models/triangle.pac",
                ExportKind.Fbx,
                fbxPath,
                overwrite: false,
                CaptureProgress,
                "models/triangle.pac",
                CancellationToken.None).ConfigureAwait(false);
            var fbx = await File.ReadAllBytesAsync(fbxPath).ConfigureAwait(false);
            Require(Encoding.ASCII.GetString(fbx, 0, 20) == "Kaydara FBX Binary  ", "FBX export is not a binary FBX file");
            Require(progressUpdates.Any(update => update.Phase == "mesh_export_prepare" && update.Total > 0), "mesh export did not report determinate preparation progress");
            Require(progressUpdates.Any(update => update.Phase == "mesh_export_write" && update.Completed == update.Total), "mesh export did not report completion progress");

            var preservedPath = Path.Combine(exportRoot, "preserved.glb");
            await File.WriteAllTextAsync(preservedPath, "preserve-me").ConfigureAwait(false);
            using (var cancelled = new CancellationTokenSource())
            {
                cancelled.Cancel();
                await RequireThrowsAsync<OperationCanceledException>(() => exporter.ExportPackageAsync(
                    root,
                    "models/triangle.pac",
                    ExportKind.Glb,
                    preservedPath,
                    overwrite: true,
                    null,
                    null,
                    cancelled.Token)).ConfigureAwait(false);
            }
            Require(await File.ReadAllTextAsync(preservedPath).ConfigureAwait(false) == "preserve-me", "cancelled mesh export replaced an existing destination");

            var unsafeRoot = Path.Combine(root, "unsafe");
            Directory.CreateDirectory(unsafeRoot);
            await File.WriteAllTextAsync(
                Path.Combine(unsafeRoot, "manifest.json"),
                JsonSerializer.Serialize(new
                {
                    schema_version = 8,
                    batches = new[]
                    {
                        new { index = 0, vertex_file = "../geometry/batch_000.bin", vertex_count = 3 },
                    },
                }),
                Encoding.UTF8).ConfigureAwait(false);
            await RequireThrowsAsync<InvalidDataException>(() => NativePreviewPackageAdapter.PrepareAsync(
                unsafeRoot,
                "synthetic:unsafe",
                CancellationToken.None)).ConfigureAwait(false);

            var rendererPath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH");
            if (!string.IsNullOrWhiteSpace(rendererPath))
            {
                await RunConfiguredRendererSmokeAsync(rendererPath, root, manifestPath).ConfigureAwait(false);
            }
            Require(await Sha256Async(geometryPath).ConfigureAwait(false) == geometryHash, "preview preparation or rendering changed native geometry");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
    }

    private static Task TestArchiveItemNamesAsync()
    {
        var names = ArchiveItemNameIndex.FromMappings(
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["cd_phm_01_sword_0016"] = "Gilded Longsword",
            },
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["cd_phm_02_sword_0042"] = "Ashen Greatsword",
            });
        var exact = names.Enrich(CreateArchiveEntry("equipment/cd_phm_01_sword_0016.pac"));
        Require(exact.KnownName == "Gilded Longsword", "exact localized name was not attached");
        Require(exact.NameEvidence == "Exact localization", "exact localized name evidence is wrong");

        var related = names.Enrich(CreateArchiveEntry("equipment/cd_phm_02_sword_0042_l.pac"));
        Require(string.IsNullOrEmpty(related.KnownName), "related family hint was presented as an exact name");
        Require(related.NameEvidence == "Name hint: Ashen Greatsword", "related family hint was not attached");
        return Task.CompletedTask;
    }

    private static ArchiveEntryDto CreateArchiveEntry(string path) => new(
        EntryId: 0,
        Path: path,
        SourcePamt: "synthetic.pamt",
        PazFile: "synthetic.paz",
        PazIndex: 0,
        Offset: 0,
        StoredSize: 1,
        OriginalSize: 1,
        Flags: 0,
        Extension: Path.GetExtension(path),
        Package: "synthetic",
        Role: ArchiveEntryRole.Model,
        IsPreviewable: true);

    private static async Task RunConfiguredRendererSmokeAsync(string rendererPath, string packageRoot, string manifestPath)
    {
        var resolvedRenderer = Path.GetFullPath(rendererPath);
        Require(File.Exists(resolvedRenderer), $"configured .NET preview renderer was not found: {resolvedRenderer}");
        var runtimeRoot = Path.Combine(packageRoot, "headless-smoke");
        Directory.CreateDirectory(runtimeRoot);
        var statusPath = Path.Combine(runtimeRoot, "status.json");
        var outputRoot = Path.Combine(runtimeRoot, "output");
        var startInfo = new ProcessStartInfo
        {
            FileName = resolvedRenderer,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            WorkingDirectory = Path.GetDirectoryName(resolvedRenderer)!,
        };
        foreach (var argument in new[]
        {
            "--input-package", packageRoot,
            "--mesh", manifestPath,
            "--metadata", Path.Combine(packageRoot, "mesh.cdmeta.json"),
            "--status", statusPath,
            "--output", outputRoot,
            "--edit-operations", Path.Combine(runtimeRoot, "edit_operations.json"),
            "--evaluation", Path.Combine(runtimeRoot, "evaluation.md"),
            "--headless-smoke",
        })
        {
            startInfo.ArgumentList.Add(argument);
        }
        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("configured .NET preview renderer could not be started");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync().ConfigureAwait(false);
            throw new TimeoutException("configured .NET preview renderer did not finish its synthetic package smoke test");
        }
        var stdoutText = await stdout.ConfigureAwait(false);
        var stderrText = await stderr.ConfigureAwait(false);
        Require(process.ExitCode == 0, $"configured .NET preview renderer failed: {stderrText}{stdoutText}");
        Require(File.Exists(Path.Combine(outputRoot, "mesh.obj")), "configured .NET preview renderer did not load and export the native manifest");
        using var status = JsonDocument.Parse(await File.ReadAllTextAsync(statusPath).ConfigureAwait(false));
        Require(status.RootElement.GetProperty("event").GetString() == "saved", "configured .NET preview renderer did not report a successful smoke result");
    }

    private static Task TestTextDecodingAsync()
    {
        var utf16 = Encoding.Unicode.GetPreamble().Concat(Encoding.Unicode.GetBytes("Crimson UTF-16")).ToArray();
        Require(TextDecoding.LooksTextual(utf16), "UTF-16 text was classified as binary");
        Require(TextDecoding.Decode(utf16) == "Crimson UTF-16", "UTF-16 decode is wrong");
        var latin1 = new byte[] { (byte)'C', (byte)'a', (byte)'f', 0xE9 };
        Require(TextDecoding.Decode(latin1) == "Café", "Latin-1 fallback decode is wrong");
        return Task.CompletedTask;
    }

    private static async Task TestNativeArchiveAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var native = new NativeArchiveCore();
        native.EnsureCompatible();
        var singlePamtFingerprint = await ArchiveFingerprint.ComputeAsync(fixture.Pamt, CancellationToken.None).ConfigureAwait(false);
        Require(singlePamtFingerprint.SourceFiles.Contains(fixture.Paz, StringComparer.OrdinalIgnoreCase), "single-PAMT fingerprint omitted its PAZ source");
        Require(singlePamtFingerprint.SourceFiles.Contains(fixture.Pathc, StringComparer.OrdinalIgnoreCase), "single-PAMT fingerprint omitted PATHC metadata");
        var indexPath = Path.Combine(fixture.Root, "native-index.ali");
        var count = native.BuildIndex(fixture.Root, indexPath);
        Require(count == 4, "native index count is wrong");
        using var index = ArchiveIndex.Open(indexPath);
        Require(index.EntryCount == 4, "managed index count is wrong");
        var pathMatches = index.FindEntriesByPath("TEXT\\HELLO.TXT");
        Require(pathMatches.Count == 1 && pathMatches[0].Path == "text/hello.txt", "indexed companion-path lookup is wrong");
        var entries = Enumerable.Range(0, 4).Select(id => index.ReadEntry(id)).ToArray();
        var text = entries.Single(entry => entry.Path == "text/hello.txt");
        var decoded = native.Decode(text);
        Require(Encoding.UTF8.GetString(decoded.Bytes).Contains("Crimson", StringComparison.Ordinal), "raw text decode failed");
        var lz4 = entries.Single(entry => entry.Path == "materials/sample.material");
        var lz4Decoded = native.Decode(lz4);
        Require(Encoding.UTF8.GetString(lz4Decoded.Bytes) == "material alpha", "LZ4 text decode failed");
        Require(lz4Decoded.Note == "LZ4", "LZ4 diagnostic note is missing");
        var partialDds = native.Decode(entries.Single(entry => entry.Path == "texture/test.dds"));
        Require(partialDds.Bytes.Length == 0x88 && partialDds.Bytes.AsSpan(0, 4).SequenceEqual("DDS "u8), "managed PATHC DDS decode failed");
        Require(partialDds.Note == "PartialDDS+PATHC", "managed PATHC DDS diagnostic note is missing");
    }

    private static async Task TestArchiveServicesAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var beforePamt = await Sha256Async(fixture.Pamt).ConfigureAwait(false);
        var beforePaz = await Sha256Async(fixture.Paz).ConfigureAwait(false);
        var beforePathc = await Sha256Async(fixture.Pathc).ConfigureAwait(false);
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native);
        var openProgress = new List<ProgressUpdate>();
        var opened = await sessions.OpenAsync(
            new OpenArchiveRequest(fixture.Root, true),
            CancellationToken.None,
            update =>
            {
                openProgress.Add(update);
                return Task.CompletedTask;
            }).ConfigureAwait(false);
        Require(openProgress.Any(update => update.Phase == "fingerprint"), "archive open did not publish fingerprint progress");
        Require(openProgress.Any(update => update.Phase == "index_build"), "archive open did not publish index-build progress");
        Require(openProgress.Any(update => update.Phase == "validate"), "archive open did not publish validation progress");
        var queries = new ArchiveQueryService(sessions);
        var directPage = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, PageSize: 2),
            8,
            CancellationToken.None).ConfigureAwait(false);
        Require(directPage.TotalMatches == 4 && directPage.Entries.Count == 2, "direct flat-path page is wrong");
        Require(directPage.Folders.Count == 0 && directPage.Categories.Count == 0, "direct flat-path page performed navigation aggregation");
        var page = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, Extensions: [".txt", ".material"]),
            9,
            CancellationToken.None).ConfigureAwait(false);
        Require(page.TotalMatches == 2, "archive extension query count is wrong");
        Require(page.Generation == 9, "query generation was not retained");
        var facetProgress = new List<ProgressUpdate>();
        var facets = await new ArchiveFacetsService(sessions).LoadAsync(
            new ArchiveFacetsRequest(opened.SessionId),
            update =>
            {
                facetProgress.Add(update);
                return Task.CompletedTask;
            },
            CancellationToken.None).ConfigureAwait(false);
        Require(facets.Extensions.Count == 4, "extension catalogue count is wrong");
        Require(
            facets.Extensions.Single(item => item.Extension == ".dds").Category == ArchiveExtensionCategory.TextureImage,
            "DDS extension category is wrong");
        Require(
            facets.Extensions.Single(item => item.Extension == ".material").Category == ArchiveExtensionCategory.MaterialMetadata,
            "material extension category is wrong");
        Require(
            facets.Extensions.Single(item => item.Extension == ".txt").Category == ArchiveExtensionCategory.UserInterfaceText,
            "text extension category is wrong");
        Require(facetProgress.Any(update => update.Phase == "extension_scan"), "extension catalogue did not report progress");
        var sortedPage = await queries.QueryAsync(
            new ArchiveQuerySpec(
                opened.SessionId,
                SortField: ArchiveSortField.OriginalSize,
                SortDescending: true,
                PageSize: 2),
            10,
            CancellationToken.None).ConfigureAwait(false);
        Require(sortedPage.Entries.Count == 2, "bounded sorted page size is wrong");
        Require(sortedPage.Entries[0].OriginalSize >= sortedPage.Entries[1].OriginalSize, "server-side descending sort is wrong");
        var reversePathPage = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, SortDescending: true, PageSize: 2),
            11,
            CancellationToken.None).ConfigureAwait(false);
        Require(StringComparer.OrdinalIgnoreCase.Compare(reversePathPage.Entries[0].Path, reversePathPage.Entries[1].Path) >= 0, "descending path paging is wrong");
        var previewService = new ArchivePreviewService(sessions, native);
        var textEntry = page.Entries.Single(entry => entry.Extension == ".txt");
        var preview = await previewService.BuildAsync(
            new PreviewRequest(opened.SessionId, textEntry.EntryId),
            CancellationToken.None).ConfigureAwait(false);
        Require(preview.Kind == PreviewKind.Text && preview.Text?.Contains("Crimson", StringComparison.Ordinal) == true, "text preview is wrong");
        var imagePage = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, Extensions: [".dds"]),
            12,
            CancellationToken.None).ConfigureAwait(false);
        var imagePreview = await previewService.BuildAsync(
            new PreviewRequest(opened.SessionId, imagePage.Entries.Single().EntryId),
            CancellationToken.None).ConfigureAwait(false);
        Require(imagePreview.Kind == PreviewKind.Image && imagePreview.ArtifactPath is not null, "DDS preview artifact is missing");
        var imageBytes = await File.ReadAllBytesAsync(imagePreview.ArtifactPath!).ConfigureAwait(false);
        Require(imageBytes.AsSpan(0, 4).SequenceEqual("DDS "u8), "DDS preview artifact is not reconstructed");
        var search = new TextSearchService(sessions, native);
        var result = await search.SearchAsync(
            new TextSearchRequest(
                TextSearchSourceKind.Archive,
                opened.SessionId,
                "crimson",
                false,
                false,
                null,
                [".txt"]),
            CancellationToken.None).ConfigureAwait(false);
        Require(result.Matches.Count == 1, "literal archive search did not find one match");
        Require(result.Matches[0].Line == 1, "search line number is wrong");
        var regex = await search.SearchAsync(
            new TextSearchRequest(
                TextSearchSourceKind.Archive,
                opened.SessionId,
                "line\\s+2",
                true,
                false,
                null,
                [".txt"]),
            CancellationToken.None).ConfigureAwait(false);
        Require(regex.Matches.Count == 1, "regex archive search did not find one match");
        Require(await Sha256Async(fixture.Pamt).ConfigureAwait(false) == beforePamt, "PAMT changed during read-only services");
        Require(await Sha256Async(fixture.Paz).ConfigureAwait(false) == beforePaz, "PAZ changed during read-only services");
        Require(await Sha256Async(fixture.Pathc).ConfigureAwait(false) == beforePathc, "PATHC changed during read-only services");
    }

    private static async Task TestArchiveExportAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native);
        var opened = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root, true), CancellationToken.None).ConfigureAwait(false);
        var queries = new ArchiveQueryService(sessions);
        var page = await queries.QueryAsync(
            new ArchiveQuerySpec(opened.SessionId, PathText: "hello"),
            1,
            CancellationToken.None).ConfigureAwait(false);
        var exportRoot = fixture.OutputRoot;
        var service = new ArchiveExportService(
            sessions,
            queries,
            native,
            new NativeModelExportService(new NativeModelPreviewService()));
        await RequireThrowsAsync<InvalidDataException>(() => service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.RawEntries,
                fixture.Root,
                [page.Entries.Single().EntryId],
                null),
            null,
            CancellationToken.None)).ConfigureAwait(false);
        await RequireThrowsAsync<NotSupportedException>(() => service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.Wav,
                exportRoot,
                [page.Entries.Single().EntryId],
                null),
            null,
            CancellationToken.None)).ConfigureAwait(false);
        await RequireThrowsAsync<InvalidDataException>(() => service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.Obj,
                exportRoot,
                [page.Entries.Single().EntryId],
                null,
                ManifestFormat: ExportManifestFormat.None,
                SingleOutputPath: Path.Combine(fixture.Root, "unsafe.obj")),
            null,
            CancellationToken.None)).ConfigureAwait(false);
        var unsupportedMesh = await service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.Obj,
                Path.Combine(exportRoot, "unsupported-mesh"),
                [page.Entries.Single().EntryId],
                null,
                ManifestFormat: ExportManifestFormat.None),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(
            unsupportedMesh.Failed == 1 && unsupportedMesh.Exported == 0,
            "non-model OBJ export did not fail closed");
        Require(
            !File.Exists(Path.Combine(exportRoot, "unsupported-mesh", "base", "text", "hello.obj")),
            "non-model OBJ export silently wrote a differently formatted file");
        var result = await service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.RawEntries,
                exportRoot,
                [page.Entries.Single().EntryId],
                null),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(result.Exported == 1 && result.Failed == 0, "archive export result is wrong");
        var output = Path.Combine(exportRoot, "base", "text", "hello.txt");
        Require(File.Exists(output), "archive export did not preserve the package and virtual path");
        Require(await File.ReadAllTextAsync(output).ConfigureAwait(false) == "Hello Crimson\nline 2", "archive export bytes are wrong");
        Require(result.ManifestPath is not null && File.Exists(result.ManifestPath), "JSON manifest was not written");

        var folderExportRoot = Path.Combine(fixture.OutputRoot, "folder-tree");
        var folderExport = await service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.FolderTree,
                folderExportRoot,
                [],
                null,
                FolderPath: "text"),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(folderExport.Exported == 1 && folderExport.Failed == 0, "folder-tree export did not resolve the selected archive folder");
        Require(
            File.Exists(Path.Combine(folderExportRoot, "base", "text", "hello.txt")),
            "folder-tree export did not preserve the full-app package folder structure");

        var collision = await service.ExportAsync(
            new ExportPlanRequest(
                opened.SessionId,
                ExportKind.RawEntries,
                exportRoot,
                [page.Entries.Single().EntryId],
                null,
                CollisionPolicy: ExportCollisionPolicy.Skip),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(collision.Skipped == 1, "skip collision policy did not preserve the destination");

        var looseRoot = Path.Combine(fixture.Root, "loose-source");
        Directory.CreateDirectory(Path.Combine(looseRoot, "notes"));
        await File.WriteAllTextAsync(Path.Combine(looseRoot, "notes", "result.txt"), "Crimson loose result").ConfigureAwait(false);
        var textSearch = new TextSearchService(sessions, native);
        var looseSearch = await textSearch.SearchAsync(
            new TextSearchRequest(
                TextSearchSourceKind.LooseFolder,
                looseRoot,
                "loose",
                false,
                false,
                null,
                [".txt"]),
            CancellationToken.None).ConfigureAwait(false);
        Require(looseSearch.Matches.Count == 1, "loose-folder search did not find its text file");
        await RequireThrowsAsync<InvalidDataException>(() => service.ExportAsync(
            new ExportPlanRequest(
                null,
                ExportKind.RawEntries,
                Path.Combine(looseRoot, "unsafe-output"),
                [],
                [looseSearch.Matches[0].Path],
                looseRoot),
            null,
            CancellationToken.None)).ConfigureAwait(false);
        var looseExport = await service.ExportAsync(
            new ExportPlanRequest(
                null,
                ExportKind.RawEntries,
                Path.Combine(fixture.OutputRoot, "loose-search"),
                [],
                [looseSearch.Matches[0].Path],
                looseRoot),
            null,
            CancellationToken.None).ConfigureAwait(false);
        Require(looseExport.Exported == 1, "loose search-result export failed");
        await using var looseManifestStream = File.OpenRead(looseExport.ManifestPath!);
        var looseManifest = await JsonSerializer.DeserializeAsync<ArchiveLiteManifest>(
            looseManifestStream,
            WorkerProtocol.JsonOptions).ConfigureAwait(false);
        Require(looseManifest?.LooseFiles.Count == 1, "loose export manifest did not record its source");
    }

    private static async Task TestWorkerBoundaryAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var beforePamt = await Sha256Async(fixture.Pamt).ConfigureAwait(false);
        var beforePaz = await Sha256Async(fixture.Paz).ConfigureAwait(false);
        var workerPath = FindWorkerOutputPath();
        Require(File.Exists(workerPath), $"worker output was not found: {workerPath}");

        var pipeName = $"cdmw-archive-lite-test-{Environment.ProcessId}-{Guid.NewGuid():N}";
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = workerPath,
            Arguments = $"--pipe \"{pipeName}\"",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
            WorkingDirectory = Path.GetDirectoryName(workerPath)!,
        }) ?? throw new InvalidOperationException("worker test process could not be started");
        var stderrTask = process.StandardError.ReadToEndAsync();
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        try
        {
            await using var pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.WriteThrough);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
            await pipe.ConnectAsync(timeout.Token).ConfigureAwait(false);
            using var reader = new StreamReader(pipe, new UTF8Encoding(false), false, 16 * 1024, leaveOpen: true);
            using var writer = new StreamWriter(pipe, new UTF8Encoding(false), 16 * 1024, leaveOpen: true) { AutoFlush = true, NewLine = "\n" };

            var ping = await ExchangeAsync(writer, reader, WorkerProtocol.Ping, 1, new PingRequest("test"), timeout.Token).ConfigureAwait(false);
            var pingResult = WorkerProtocol.ReadPayload<PingResult>(ping);
            Require(pingResult?.ProtocolVersion == WorkerProtocol.Version, "worker ping protocol version is wrong");

            var workerProgress = new List<ProgressUpdate>();
            var openedMessage = await ExchangeAsync(
                writer,
                reader,
                WorkerProtocol.OpenArchive,
                2,
                new OpenArchiveRequest(fixture.Root, true),
                timeout.Token,
                workerProgress).ConfigureAwait(false);
            var opened = WorkerProtocol.ReadPayload<OpenArchiveResult>(openedMessage)
                ?? throw new InvalidDataException("worker open response is missing");
            Require(opened.EntryCount == 4, "worker archive count is wrong");
            Require(workerProgress.Any(update => update.Phase == "fingerprint"), "worker did not forward archive-open progress");

            var queryMessage = await ExchangeAsync(
                writer,
                reader,
                WorkerProtocol.QueryArchive,
                3,
                new ArchiveQuerySpec(opened.SessionId, PathText: "hello"),
                timeout.Token).ConfigureAwait(false);
            var page = WorkerProtocol.ReadPayload<ArchivePageResult>(queryMessage)
                ?? throw new InvalidDataException("worker query response is missing");
            Require(page.TotalMatches == 1 && page.Entries.Single().Path == "text/hello.txt", "worker query result is wrong");

            var associationProgress = new List<ProgressUpdate>();
            var associationMessage = await ExchangeAsync(
                writer,
                reader,
                WorkerProtocol.FindAssociatedAssets,
                4,
                new FindAssociatedAssetsRequest(opened.SessionId, page.Entries.Single().EntryId),
                timeout.Token,
                associationProgress).ConfigureAwait(false);
            var associations = WorkerProtocol.ReadPayload<FindAssociatedAssetsResult>(associationMessage)
                ?? throw new InvalidDataException("worker associated-assets response is missing");
            Require(associations.Assets.Count == 0, "worker invented associations for an isolated text file");
            Require(
                associationProgress.Any(update => update.Phase == "association_scan"),
                "worker did not forward associated-asset progress");

            var healthMessage = await ExchangeAsync(
                writer,
                reader,
                WorkerProtocol.InspectArchiveCache,
                5,
                new ArchiveCacheHealthRequest(fixture.Root),
                timeout.Token).ConfigureAwait(false);
            var health = WorkerProtocol.ReadPayload<ArchiveCacheHealthResult>(healthMessage)
                ?? throw new InvalidDataException("worker cache-health response is missing");
            Require(health.State == ArchiveCacheHealthState.Current, "worker did not report the freshly opened archive cache as current");

            await ExchangeAsync(writer, reader, WorkerProtocol.Shutdown, 6, new { }, timeout.Token).ConfigureAwait(false);
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
            Require(process.ExitCode == 0, "worker did not exit cleanly");
        }
        catch (Exception exception)
        {
            var stderr = process.HasExited ? await stderrTask.ConfigureAwait(false) : string.Empty;
            throw new InvalidOperationException($"Worker boundary failed. {stderr}", exception);
        }
        finally
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync().ConfigureAwait(false);
            _ = await stderrTask.ConfigureAwait(false);
            _ = await stdoutTask.ConfigureAwait(false);
        }

        Require(await Sha256Async(fixture.Pamt).ConfigureAwait(false) == beforePamt, "worker changed the PAMT source");
        Require(await Sha256Async(fixture.Paz).ConfigureAwait(false) == beforePaz, "worker changed the PAZ source");
    }

    private static async Task<WorkerMessage> ExchangeAsync<T>(
        StreamWriter writer,
        StreamReader reader,
        string kind,
        long generation,
        T payload,
        CancellationToken cancellationToken,
        ICollection<ProgressUpdate>? progress = null)
    {
        var request = WorkerProtocol.Request(Guid.NewGuid(), generation, kind, payload);
        var json = JsonSerializer.Serialize(request, WorkerProtocol.JsonOptions);
        await writer.WriteLineAsync(json.AsMemory(), cancellationToken).ConfigureAwait(false);
        while (true)
        {
            var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false)
                ?? throw new IOException("worker disconnected before replying");
            Require(Encoding.UTF8.GetByteCount(line) <= WorkerProtocol.MaximumMessageBytes, "worker response exceeds the protocol limit");
            var response = JsonSerializer.Deserialize<WorkerMessage>(line, WorkerProtocol.JsonOptions)
                ?? throw new InvalidDataException("worker response could not be decoded");
            if (response.RequestId != request.RequestId)
            {
                continue;
            }
            if (response.Status == WorkerMessageStatus.Progress)
            {
                if (WorkerProtocol.ReadPayload<ProgressUpdate>(response) is { } update)
                {
                    progress?.Add(update);
                }
                continue;
            }
            if (response.Status == WorkerMessageStatus.Started)
            {
                continue;
            }
            if (response.Status == WorkerMessageStatus.Error)
            {
                throw new InvalidOperationException(response.Error?.Message ?? "worker request failed");
            }
            Require(response.Status == WorkerMessageStatus.Result, $"unexpected worker terminal status: {response.Status}");
            return response;
        }
    }

    private static string FindRepositoryRoot()
    {
        foreach (var start in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
        {
            var current = new DirectoryInfo(start);
            while (current is not null)
            {
                if (Directory.Exists(Path.Combine(current.FullName, "apps", "Cdmw.ArchiveLite"))) return current.FullName;
                current = current.Parent;
            }
        }
        throw new DirectoryNotFoundException("repository root could not be located");
    }

    private static string FindWorkerOutputPath()
    {
        var configuration = AppContext.BaseDirectory.Contains(
            $"{Path.DirectorySeparatorChar}Release{Path.DirectorySeparatorChar}",
            StringComparison.OrdinalIgnoreCase)
            ? "Release"
            : "Debug";
        return Path.Combine(
            FindRepositoryRoot(),
            "apps",
            "Cdmw.ArchiveLite",
            "src",
            "Cdmw.ArchiveLite.Worker",
            "bin",
            configuration,
            "net10.0-windows",
            "win-x64",
            "CdmwArchiveLite.Worker.exe");
    }

    private static Task RunOnWpfDispatcherAsync(Func<Task> action)
    {
        var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() =>
        {
            var dispatcher = Dispatcher.CurrentDispatcher;
            SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(dispatcher));
            dispatcher.BeginInvoke(new Action(async () =>
            {
                try
                {
                    await action();
                    completion.TrySetResult(true);
                }
                catch (Exception exception)
                {
                    completion.TrySetException(exception);
                }
                finally
                {
                    dispatcher.BeginInvokeShutdown(DispatcherPriority.Background);
                }
            }));
            Dispatcher.Run();
        })
        {
            IsBackground = true,
            Name = "ArchiveLiteStartupCacheTest",
        };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        return completion.Task;
    }

    private static async Task<string> Sha256Async(string path)
    {
        await using var stream = File.OpenRead(path);
        return Convert.ToHexString(await SHA256.HashDataAsync(stream).ConfigureAwait(false));
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void RequireThrows<TException>(Action action) where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException($"Expected {typeof(TException).Name} was not thrown.");
    }

    private static async Task RequireThrowsAsync<TException>(Func<Task> action) where TException : Exception
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException($"Expected {typeof(TException).Name} was not thrown.");
    }
}
