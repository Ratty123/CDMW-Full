using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.ViewModels;

public sealed class MainWindowViewModel : ObservableObject
{
    private readonly WorkerProcessHost _worker;
    private LiteSettings _settings;
    private string _status = LocalizationManager.Get("ConnectingWorker");
    private bool _isShuttingDown;
    private LanguageOption _selectedLanguage;
    private ThemeOption _selectedTheme;

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
        Themes = ThemeManager.AvailableThemes
            .Select(definition => new ThemeOption(definition.Id, LocalizationManager.Get(definition.ResourceKey)))
            .ToArray();
        _selectedTheme = Themes.FirstOrDefault(option => option.Id.Equals(settings.Theme, StringComparison.OrdinalIgnoreCase)) ?? Themes[0];
        ArchiveBrowser = new ArchiveBrowserViewModel(
            worker,
            settings.ArchiveRoot,
            UpdateStatus,
            settings.ArchiveSortField,
            settings.ArchiveSortDescending);
        TextSearch = new TextSearchViewModel(worker, () => ArchiveBrowser.SessionId, UpdateStatus);
        ArchiveBrowser.SessionChanged += (_, _) => TextSearch.NotifyArchiveSessionChanged();
    }

    public ArchiveBrowserViewModel ArchiveBrowser { get; }

    public TextSearchViewModel TextSearch { get; }

    public IReadOnlyList<LanguageOption> Languages { get; }

    public IReadOnlyList<ThemeOption> Themes { get; }

    public IReadOnlyList<string>? ArchiveVisibleColumns => _settings.ArchiveVisibleColumns;

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

    public LanguageOption SelectedLanguage
    {
        get => _selectedLanguage;
        set
        {
            if (value is not null && SetProperty(ref _selectedLanguage, value))
            {
                _settings = _settings with { Language = value.Code };
                Status = LocalizationManager.Get("LanguageRestart");
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
        var result = await _worker.SendAsync<PingRequest, PingResult>(
            WorkerProtocol.Ping,
            1,
            new PingRequest(typeof(MainWindowViewModel).Assembly.GetName().Version?.ToString() ?? "0.0.0"),
            CancellationToken.None).ConfigureAwait(true);
        Status = LocalizationManager.Format("WorkerConnected", result.ProtocolVersion);
    }

    public async Task ShutdownAsync()
    {
        if (IsShuttingDown)
        {
            return;
        }

        IsShuttingDown = true;
        Status = LocalizationManager.Get("Closing");
        ArchiveBrowser.RequestShutdown();
        TextSearch.RequestShutdown();
        _settings = _settings with
        {
            ArchiveRoot = ArchiveBrowser.ArchiveRoot,
            ArchiveSortField = ArchiveBrowser.SortField,
            ArchiveSortDescending = ArchiveBrowser.SortDescending,
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
}

public sealed record LanguageOption(string Code, string Label)
{
    public override string ToString() => Label;
}

public sealed record ThemeOption(string Id, string Label)
{
    public override string ToString() => Label;
}
