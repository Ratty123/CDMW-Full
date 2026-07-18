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
    private long _generation;
    private TextSearchSourceKind _sourceKind = TextSearchSourceKind.Archive;
    private string _looseFolder = string.Empty;
    private string _query = string.Empty;
    private string _pathFilter = string.Empty;
    private string _extensions = ".xml;.txt;.json;.cfg;.ini;.lua;.material;.shader;.yaml;.yml";
    private bool _useRegularExpression;
    private bool _caseSensitive;
    private TextSearchMatchDto? _selectedMatch;
    private string _previewText = LocalizationManager.Get("PreviewEmpty");
    private bool _isBusy;

    public TextSearchViewModel(WorkerProcessHost worker, Func<string?> archiveSession, Action<string> setShellStatus)
    {
        _worker = worker;
        _archiveSession = archiveSession;
        _setShellStatus = setShellStatus;
        BrowseCommand = new AsyncCommand(_ => BrowseAsync(), () => SourceKind == TextSearchSourceKind.LooseFolder);
        SearchCommand = new AsyncCommand(SearchAsync, CanSearch);
        CancelCommand = new RelayCommand(RequestShutdown, () => IsBusy);
        ExportResultsCommand = new AsyncCommand(ExportResultsAsync, () => Matches.Count > 0 && !IsBusy);
        SourceOptions =
        [
            new LocalizedOption<TextSearchSourceKind>(TextSearchSourceKind.Archive, LocalizationManager.Get("Archive")),
            new LocalizedOption<TextSearchSourceKind>(TextSearchSourceKind.LooseFolder, LocalizationManager.Get("LooseFolder")),
        ];
    }

    public ObservableCollection<TextSearchMatchDto> Matches { get; } = [];
    public IReadOnlyList<LocalizedOption<TextSearchSourceKind>> SourceOptions { get; }
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
                PreviewText = value?.Context ?? LocalizationManager.Get("PreviewEmpty");
            }
        }
    }

    public string PreviewText
    {
        get => _previewText;
        private set => SetProperty(ref _previewText, value);
    }

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
        _operation?.Cancel();
        IsBusy = false;
    }

    public void NotifyArchiveSessionChanged() => SearchCommand.RaiseCanExecuteChanged();

    private bool CanSearch() =>
        !IsBusy &&
        !string.IsNullOrWhiteSpace(Query) &&
        (SourceKind == TextSearchSourceKind.Archive
            ? !string.IsNullOrWhiteSpace(_archiveSession())
            : Directory.Exists(LooseFolder));

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
}
