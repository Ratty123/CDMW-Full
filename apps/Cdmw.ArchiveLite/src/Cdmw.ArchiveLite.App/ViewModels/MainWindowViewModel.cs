using System.Windows;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.ViewModels;

public sealed class MainWindowViewModel : ObservableObject
{
    private readonly WorkerProcessHost _worker;
    private readonly CancellationTokenSource _startupOperation = new();
    private LiteSettings _settings;
    private string _status = LocalizationManager.Get("ConnectingWorker");
    private bool _isShuttingDown;
    private LanguageOption _selectedLanguage;
    private ThemeOption _selectedTheme;
    private IReadOnlyList<ThemeOption> _themes = [];

    public MainWindowViewModel(WorkerProcessHost worker, LiteSettings settings)
    {
        _worker = worker;
        _settings = settings;
        Languages =
        [
            new LanguageOption("en", "English"),
            new LanguageOption("de", "Deutsch"),
            new LanguageOption("es", "Español"),
        ];
        _selectedLanguage = Languages.FirstOrDefault(option => option.Code.Equals(settings.Language, StringComparison.OrdinalIgnoreCase)) ?? Languages[0];
        _themes = BuildThemeOptions();
        _selectedTheme = Themes.FirstOrDefault(option => option.Id.Equals(settings.Theme, StringComparison.OrdinalIgnoreCase)) ?? Themes[0];
        var cacheChoicePrompt = new ArchiveCacheChoicePrompt(() => Application.Current?.MainWindow);
        ArchiveBrowser = new ArchiveBrowserViewModel(
            worker,
            settings.ArchiveRoot,
            UpdateStatus,
            cacheChoicePrompt.Choose,
            settings.ArchiveSortField,
            settings.ArchiveSortDescending,
            settings.ArchiveBrowser);
        TextSearch = new TextSearchViewModel(
            worker,
            () => ArchiveBrowser.SessionId,
            UpdateStatus,
            settings.TextSearch);
        ArchiveBrowser.SessionChanged += (_, _) => TextSearch.NotifyArchiveSessionChanged();
    }

    public ArchiveBrowserViewModel ArchiveBrowser { get; }

    public TextSearchViewModel TextSearch { get; }

    public IReadOnlyList<LanguageOption> Languages { get; }

    public IReadOnlyList<ThemeOption> Themes => _themes;

    public IReadOnlyList<string>? ArchiveVisibleColumns => _settings.ArchiveVisibleColumns;

    public WindowPlacementSettings? WindowPlacement => _settings.WindowPlacement;

    public WorkspaceLayoutSettings? WorkspaceLayout => _settings.WorkspaceLayout;

    public IReadOnlyList<GridColumnSettings>? ArchiveColumnLayout => _settings.ArchiveColumnLayout;

    public IReadOnlyList<GridColumnSettings>? TextSearchColumnLayout => _settings.TextSearchColumnLayout;

    public void SetArchiveVisibleColumns(IEnumerable<string> columns)
    {
        _settings = _settings with
        {
            ArchiveVisibleColumns = columns
                .Where(static column => !string.IsNullOrWhiteSpace(column))
                .Distinct(StringComparer.Ordinal)
                .ToArray(),
        };
    }

    public void SetUiLayout(
        WindowPlacementSettings windowPlacement,
        WorkspaceLayoutSettings workspaceLayout,
        IEnumerable<GridColumnSettings> archiveColumns,
        IEnumerable<GridColumnSettings> textSearchColumns)
    {
        _settings = _settings with
        {
            WindowPlacement = windowPlacement,
            WorkspaceLayout = workspaceLayout,
            ArchiveColumnLayout = archiveColumns.ToArray(),
            TextSearchColumnLayout = textSearchColumns.ToArray(),
        };
    }

    public LanguageOption SelectedLanguage
    {
        get => _selectedLanguage;
        set
        {
            if (value is not null && SetProperty(ref _selectedLanguage, value))
            {
                _settings = _settings with { Language = value.Code };
                LocalizationManager.ApplyCulture(value.Code);
                ArchiveBrowser.RefreshLocalization();
                TextSearch.RefreshLocalization();
                RefreshThemeLabels();
                Status = LocalizationManager.Get("LanguageApplied");
            }
        }
    }

    public ThemeOption SelectedTheme
    {
        get => _selectedTheme;
        set
        {
            if (value is not null && SetProperty(ref _selectedTheme, value))
            {
                ThemeManager.Apply(value.Id);
                _settings = _settings with { Theme = value.Id };
                Status = LocalizationManager.Get("ThemeApplied");
            }
        }
    }

    public string Status
    {
        get => _status;
        private set => SetProperty(ref _status, value);
    }

    public bool IsShuttingDown
    {
        get => _isShuttingDown;
        private set => SetProperty(ref _isShuttingDown, value);
    }

    public async Task InitializeAsync()
    {
        try
        {
            var result = await _worker.SendAsync<PingRequest, PingResult>(
                WorkerProtocol.Ping,
                1,
                new PingRequest(typeof(MainWindowViewModel).Assembly.GetName().Version?.ToString() ?? "0.0.0"),
                _startupOperation.Token).ConfigureAwait(true);
            Status = LocalizationManager.Format("WorkerConnected", result.ProtocolVersion);
            await ArchiveBrowser.InitializeEnvironmentAsync(_startupOperation.Token).ConfigureAwait(true);
        }
        catch (OperationCanceledException) when (IsShuttingDown)
        {
            // Closing during startup is an expected cooperative cancellation path.
        }
    }

    public async Task ShutdownAsync()
    {
        if (IsShuttingDown)
        {
            return;
        }

        IsShuttingDown = true;
        Status = LocalizationManager.Get("Closing");
        _startupOperation.Cancel();
        ArchiveBrowser.RequestShutdown();
        TextSearch.RequestShutdown();
        _settings = _settings with
        {
            ArchiveRoot = ArchiveBrowser.ArchiveRoot,
            ArchiveSortField = ArchiveBrowser.SortField,
            ArchiveSortDescending = ArchiveBrowser.SortDescending,
            ArchiveBrowser = new ArchiveBrowserSettings(
                ArchiveBrowser.PathFilter,
                ArchiveBrowser.ExtensionFilter,
                ArchiveBrowser.PackageFilter,
                ArchiveBrowser.PreviewableOnly,
                ArchiveBrowser.ViewMode,
                ArchiveBrowser.SelectedFolder?.Path,
                ArchiveBrowser.SelectedRole.Role,
                ArchiveBrowser.CollisionPolicy,
                ArchiveBrowser.ManifestFormat),
            TextSearch = new TextSearchSettings(
                TextSearch.SourceKind,
                TextSearch.LooseFolder,
                TextSearch.Query,
                TextSearch.PathFilter,
                TextSearch.Extensions,
                TextSearch.UseRegularExpression,
                TextSearch.CaseSensitive),
        };
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            await SettingsStore.SaveAsync(_settings, timeout.Token).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            // Worker shutdown remains authoritative over settings persistence.
        }
        catch (IOException exception)
        {
            await DiagnosticLog.WriteAsync("settings-save", exception.ToString(), CancellationToken.None).ConfigureAwait(true);
        }

        await _worker.ShutdownAsync().ConfigureAwait(true);
    }

    private void UpdateStatus(string status) => Status = status;

    private static IReadOnlyList<ThemeOption> BuildThemeOptions() => ThemeManager.AvailableThemes
        .Select(definition => new ThemeOption(definition.Id, LocalizationManager.Get(definition.ResourceKey)))
        .ToArray();

    private void RefreshThemeLabels()
    {
        var selectedThemeId = _selectedTheme.Id;
        _themes = BuildThemeOptions();
        OnPropertyChanged(nameof(Themes));
        _selectedTheme = Themes.First(option => option.Id.Equals(selectedThemeId, StringComparison.OrdinalIgnoreCase));
        OnPropertyChanged(nameof(SelectedTheme));
    }
}

public sealed record LanguageOption(string Code, string Label)
{
    public override string ToString() => Label;
}

public sealed record ThemeOption(string Id, string Label)
{
    public override string ToString() => Label;
}
