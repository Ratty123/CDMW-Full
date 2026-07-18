using System.Collections.ObjectModel;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;
using Microsoft.Win32;

namespace Cdmw.ArchiveLite.App.ViewModels;

public sealed class TextSearchViewModel : ObservableObject
{
    private readonly WorkerProcessHost _worker;
    private readonly Func<string?> _archiveSession;
    private readonly Action<string> _setShellStatus;
    private CancellationTokenSource? _operation;
    private CancellationTokenSource? _previewOperation;
    private long _generation;
    private long _previewGeneration;
    private TextSearchSourceKind _sourceKind = TextSearchSourceKind.Archive;
    private string _looseFolder = string.Empty;
    private string _query = string.Empty;
    private string _pathFilter = string.Empty;
    private string _extensions = ".xml;.txt;.json;.cfg;.ini;.lua;.material;.shader;.yaml;.yml";
    private bool _useRegularExpression;
    private bool _caseSensitive;
    private TextSearchMatchDto? _selectedMatch;
    private string _previewText = LocalizationManager.Get("PreviewEmpty");
    private string _previewSyntax = string.Empty;
    private int _previewLine = 1;
    private int _previewColumn = 1;
    private int _previewLength;
    private bool _isPreviewBusy;
    private bool _isBusy;
    private IReadOnlyList<LocalizedOption<TextSearchSourceKind>> _sourceOptions = [];

    public TextSearchViewModel(
        WorkerProcessHost worker,
        Func<string?> archiveSession,
        Action<string> setShellStatus,
        TextSearchSettings? initialSettings = null)
    {
        var searchSettings = initialSettings ?? new TextSearchSettings();
        _worker = worker;
        _archiveSession = archiveSession;
        _setShellStatus = setShellStatus;
        _sourceKind = Enum.IsDefined(searchSettings.SourceKind)
            ? searchSettings.SourceKind
            : TextSearchSourceKind.Archive;
        _looseFolder = searchSettings.LooseFolder ?? string.Empty;
        _query = searchSettings.Query ?? string.Empty;
        _pathFilter = searchSettings.PathFilter ?? string.Empty;
        _extensions = searchSettings.Extensions ?? string.Empty;
        _useRegularExpression = searchSettings.UseRegularExpression;
        _caseSensitive = searchSettings.CaseSensitive;
        BrowseCommand = new AsyncCommand(_ => BrowseAsync(), () => SourceKind == TextSearchSourceKind.LooseFolder);
        SearchCommand = new AsyncCommand(SearchAsync, CanSearch);
        CancelCommand = new RelayCommand(RequestShutdown, () => IsBusy);
        ExportResultsCommand = new AsyncCommand(ExportResultsAsync, () => Matches.Count > 0 && !IsBusy);
        RefreshSourceOptions();
    }

    public ObservableCollection<TextSearchMatchDto> Matches { get; } = [];
    public IReadOnlyList<LocalizedOption<TextSearchSourceKind>> SourceOptions => _sourceOptions;
    public AsyncCommand BrowseCommand { get; }
    public AsyncCommand SearchCommand { get; }
    public RelayCommand CancelCommand { get; }
    public AsyncCommand ExportResultsCommand { get; }

    public TextSearchSourceKind SourceKind
    {
        get => _sourceKind;
        set
        {
            if (SetProperty(ref _sourceKind, value))
            {
                CancelPreviewAndClear();
                BrowseCommand.RaiseCanExecuteChanged();
                SearchCommand.RaiseCanExecuteChanged();
                OnPropertyChanged(nameof(IsArchiveSource));
                OnPropertyChanged(nameof(IsLooseFolderSource));
            }
        }
    }

    public bool IsArchiveSource => SourceKind == TextSearchSourceKind.Archive;
    public bool IsLooseFolderSource => SourceKind == TextSearchSourceKind.LooseFolder;

    public string LooseFolder
    {
        get => _looseFolder;
        set
        {
            if (SetProperty(ref _looseFolder, value))
            {
                CancelPreviewAndClear();
                SearchCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string Query
    {
        get => _query;
        set
        {
            if (SetProperty(ref _query, value))
            {
                SearchCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string PathFilter
    {
        get => _pathFilter;
        set => SetProperty(ref _pathFilter, value);
    }

    public string Extensions
    {
        get => _extensions;
        set => SetProperty(ref _extensions, value);
    }

    public bool UseRegularExpression
    {
        get => _useRegularExpression;
        set => SetProperty(ref _useRegularExpression, value);
    }

    public bool CaseSensitive
    {
        get => _caseSensitive;
        set => SetProperty(ref _caseSensitive, value);
    }

    public TextSearchMatchDto? SelectedMatch
    {
        get => _selectedMatch;
        set
        {
            if (SetProperty(ref _selectedMatch, value))
            {
                OnPropertyChanged(nameof(HasPreviewDocument));
                _ = LoadPreviewLatestAsync(value);
            }
        }
    }

    public string PreviewText
    {
        get => _previewText;
        private set => SetProperty(ref _previewText, value);
    }

    public string PreviewSyntax
    {
        get => _previewSyntax;
        private set => SetProperty(ref _previewSyntax, value);
    }

    public int PreviewLine
    {
        get => _previewLine;
        private set => SetProperty(ref _previewLine, value);
    }

    public int PreviewColumn
    {
        get => _previewColumn;
        private set => SetProperty(ref _previewColumn, value);
    }

    public int PreviewLength
    {
        get => _previewLength;
        private set => SetProperty(ref _previewLength, value);
    }

    public bool IsPreviewBusy
    {
        get => _isPreviewBusy;
        private set => SetProperty(ref _isPreviewBusy, value);
    }

    public bool HasPreviewDocument => SelectedMatch is not null;

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                CancelCommand.RaiseCanExecuteChanged();
                ExportResultsCommand.RaiseCanExecuteChanged();
                SearchCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public void RequestShutdown()
    {
        Interlocked.Increment(ref _generation);
        CancelOperation(Interlocked.Exchange(ref _operation, null));
        Interlocked.Increment(ref _previewGeneration);
        CancelOperation(Interlocked.Exchange(ref _previewOperation, null));
        IsBusy = false;
        IsPreviewBusy = false;
    }

    public void NotifyArchiveSessionChanged() => SearchCommand.RaiseCanExecuteChanged();

    public void RefreshLocalization()
    {
        RefreshSourceOptions();
        if (SelectedMatch is null)
        {
            PreviewText = LocalizationManager.Get("PreviewEmpty");
        }
    }

    private bool CanSearch() =>
        !IsBusy &&
        !string.IsNullOrWhiteSpace(Query) &&
        (SourceKind == TextSearchSourceKind.Archive
            ? !string.IsNullOrWhiteSpace(_archiveSession())
            : Directory.Exists(LooseFolder));

    private void RefreshSourceOptions()
    {
        _sourceOptions =
        [
            new LocalizedOption<TextSearchSourceKind>(TextSearchSourceKind.Archive, LocalizationManager.Get("Archive")),
            new LocalizedOption<TextSearchSourceKind>(TextSearchSourceKind.LooseFolder, LocalizationManager.Get("LooseFolder")),
        ];
        OnPropertyChanged(nameof(SourceOptions));
    }

    private Task BrowseAsync()
    {
        var dialog = new OpenFolderDialog
        {
            Title = LocalizationManager.Get("LooseFolder"),
            Multiselect = false,
        };
        if (dialog.ShowDialog() == true)
        {
            LooseFolder = dialog.FolderName;
        }

        return Task.CompletedTask;
    }

    private async Task SearchAsync(CancellationToken commandToken)
    {
        var source = SourceKind == TextSearchSourceKind.Archive ? _archiveSession() : LooseFolder;
        if (string.IsNullOrWhiteSpace(source))
        {
            return;
        }

        using var operation = BeginOperation(commandToken);
        try
        {
            SelectedMatch = null;
            Matches.Clear();
            var generation = Interlocked.Increment(ref _generation);
            var request = new TextSearchRequest(
                SourceKind,
                source,
                Query,
                UseRegularExpression,
                CaseSensitive,
                PathFilter,
                Extensions.Split([';', ',', ' '], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));
            var result = await _worker.SendAsync<TextSearchRequest, TextSearchResultBatch>(
                WorkerProtocol.TextSearch,
                generation,
                request,
                operation.Token).ConfigureAwait(true);
            if (generation != Volatile.Read(ref _generation))
            {
                return;
            }

            Matches.Clear();
            foreach (var match in result.Matches)
            {
                Matches.Add(match);
            }

            _setShellStatus(LocalizationManager.Format("SearchSummary", result.Matches.Count, result.FilesScanned));
            ExportResultsCommand.RaiseCanExecuteChanged();
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _setShellStatus(exception.Message);
        }
        finally
        {
            EndOperation(operation);
        }
    }

    private async Task ExportResultsAsync(CancellationToken cancellationToken)
    {
        var dialog = new OpenFolderDialog
        {
            Title = LocalizationManager.Get("ExportResults"),
            Multiselect = false,
        };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        using var operation = BeginOperation(cancellationToken);
        try
        {
            var entryIds = Matches.Where(static match => match.EntryId.HasValue).Select(static match => match.EntryId!.Value).Distinct().ToArray();
            var loosePaths = Matches.Where(static match => !match.EntryId.HasValue).Select(static match => match.Path).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
            var result = await _worker.SendAsync<ExportPlanRequest, ExportPlanResult>(
                WorkerProtocol.Export,
                Interlocked.Increment(ref _generation),
                new ExportPlanRequest(
                    SourceKind == TextSearchSourceKind.Archive ? _archiveSession() : null,
                    ExportKind.RawEntries,
                    dialog.FolderName,
                    entryIds,
                    loosePaths,
                    SourceKind == TextSearchSourceKind.LooseFolder ? LooseFolder : null),
                operation.Token).ConfigureAwait(true);
            _setShellStatus(LocalizationManager.Format("SearchExportSummary", result.Exported));
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _setShellStatus(exception.Message);
        }
        finally
        {
            EndOperation(operation);
        }
    }

    private CancellationTokenSource BeginOperation(CancellationToken commandToken)
    {
        var operation = CancellationTokenSource.CreateLinkedTokenSource(commandToken);
        var prior = Interlocked.Exchange(ref _operation, operation);
        prior?.Cancel();
        IsBusy = true;
        return operation;
    }

    private void EndOperation(CancellationTokenSource operation)
    {
        if (ReferenceEquals(Interlocked.CompareExchange(ref _operation, null, operation), operation))
        {
            IsBusy = false;
        }
    }

    private async Task LoadPreviewLatestAsync(TextSearchMatchDto? match)
    {
        var generation = Interlocked.Increment(ref _previewGeneration);
        var operation = new CancellationTokenSource();
        CancelOperation(Interlocked.Exchange(ref _previewOperation, operation));
        if (match is null)
        {
            ClearPreview();
            Interlocked.CompareExchange(ref _previewOperation, null, operation);
            operation.Dispose();
            return;
        }

        var sourceKind = SourceKind;
        var source = sourceKind == TextSearchSourceKind.Archive ? _archiveSession() : LooseFolder;
        if (string.IsNullOrWhiteSpace(source))
        {
            PreviewText = match.Context;
            PreviewSyntax = TextDocumentSyntax(match.Path);
            ApplyMatchSelection(match);
            Interlocked.CompareExchange(ref _previewOperation, null, operation);
            operation.Dispose();
            return;
        }

        try
        {
            IsPreviewBusy = true;
            await Task.Delay(80, operation.Token).ConfigureAwait(true);
            var result = await _worker.SendAsync<TextDocumentRequest, PreviewResult>(
                WorkerProtocol.TextDocument,
                generation,
                new TextDocumentRequest(sourceKind, source, match.Path, match.EntryId),
                operation.Token).ConfigureAwait(true);
            var text = !string.IsNullOrWhiteSpace(result.ArtifactPath)
                ? await PreviewTextLoader.LoadAsync(result.ArtifactPath, operation.Token).ConfigureAwait(true)
                : result.Text ?? match.Context;
            operation.Token.ThrowIfCancellationRequested();
            if (generation != Volatile.Read(ref _previewGeneration))
            {
                return;
            }
            PreviewText = text;
            PreviewSyntax = result.Syntax ?? TextDocumentSyntax(match.Path);
            ApplyMatchSelection(match);
        }
        catch (OperationCanceledException)
        {
            // Selection changed or the application is closing.
        }
        catch (Exception exception)
        {
            if (generation == Volatile.Read(ref _previewGeneration))
            {
                PreviewText = match.Context;
                PreviewSyntax = TextDocumentSyntax(match.Path);
                ApplyMatchSelection(match);
                _setShellStatus(exception.Message);
            }
        }
        finally
        {
            if (generation == Volatile.Read(ref _previewGeneration))
            {
                IsPreviewBusy = false;
            }
            Interlocked.CompareExchange(ref _previewOperation, null, operation);
            operation.Dispose();
        }
    }

    private void ApplyMatchSelection(TextSearchMatchDto match)
    {
        PreviewLine = Math.Max(1, match.Line);
        PreviewColumn = Math.Max(1, match.Column);
        PreviewLength = Math.Max(0, match.Length);
    }

    private void CancelPreviewAndClear()
    {
        Interlocked.Increment(ref _previewGeneration);
        CancelOperation(Interlocked.Exchange(ref _previewOperation, null));
        SelectedMatch = null;
        ClearPreview();
    }

    private void ClearPreview()
    {
        PreviewText = LocalizationManager.Get("PreviewEmpty");
        PreviewSyntax = string.Empty;
        PreviewLine = 1;
        PreviewColumn = 1;
        PreviewLength = 0;
        IsPreviewBusy = false;
    }

    private static string TextDocumentSyntax(string path) => Path.GetExtension(path).ToLowerInvariant() switch
    {
        ".pac_xml" or ".pam_xml" or ".pamlod_xml" or ".prefabdata_xml" or ".app_xml" => ".xml",
        ".material" or ".shader" => ".hlsl",
        ".cfg" or ".ini" => ".ini",
        ".yml" => ".yaml",
        var extension => extension,
    };

    private static void CancelOperation(CancellationTokenSource? operation)
    {
        if (operation is null)
        {
            return;
        }
        try
        {
            operation.Cancel();
        }
        catch (ObjectDisposedException)
        {
            // A latest-wins completion may dispose the operation concurrently.
        }
    }
}
