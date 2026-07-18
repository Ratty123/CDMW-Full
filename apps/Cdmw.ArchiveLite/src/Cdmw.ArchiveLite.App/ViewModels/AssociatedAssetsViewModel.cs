using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Windows.Data;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.ViewModels;

public sealed class AssociatedAssetsViewModel : ObservableObject
{
    private readonly WorkerProcessHost _worker;
    private readonly Func<string, ArchiveEntryDto, CancellationToken, Task> _showInBrowser;
    private readonly Func<bool> _canInteract;
    private readonly Action<string> _setShellStatus;
    private CancellationTokenSource? _findOperation;
    private long _generation;
    private string? _sessionId;
    private ArchiveEntryDto? _source;
    private IReadOnlyList<AssociatedAssetDto> _assetDtos = [];
    private AssociatedAssetRow? _selectedAsset;
    private bool _isBusy;
    private bool _isExpanded;
    private bool _hasLoaded;
    private bool _truncated;
    private long _progressCompleted;
    private long _progressTotal;
    private string? _lastError;
    private string _status = LocalizationManager.Get("AssociatedAssetsSelectFile");

    public AssociatedAssetsViewModel(
        WorkerProcessHost worker,
        Func<string, ArchiveEntryDto, CancellationToken, Task> showInBrowser,
        Func<bool> canInteract,
        Action<string> setShellStatus)
    {
        _worker = worker;
        _showInBrowser = showInBrowser;
        _canInteract = canInteract;
        _setShellStatus = setShellStatus;
        FindCommand = new AsyncCommand(FindAsync, CanFind);
        CancelCommand = new RelayCommand(CancelFind, () => IsBusy);
        ShowInBrowserCommand = new AsyncCommand(ShowSelectedInBrowserAsync, CanShowInBrowser);
        AssetsView = CollectionViewSource.GetDefaultView(Assets);
        AssetsView.GroupDescriptions.Add(new PropertyGroupDescription(nameof(AssociatedAssetRow.CategoryLabel)));
    }

    public ObservableCollection<AssociatedAssetRow> Assets { get; } = [];
    public ICollectionView AssetsView { get; }
    public AsyncCommand FindCommand { get; }
    public RelayCommand CancelCommand { get; }
    public AsyncCommand ShowInBrowserCommand { get; }

    public AssociatedAssetRow? SelectedAsset
    {
        get => _selectedAsset;
        set
        {
            if (SetProperty(ref _selectedAsset, value))
            {
                ShowInBrowserCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaiseCommandStates();
            }
        }
    }

    public bool IsExpanded
    {
        get => _isExpanded;
        set => SetProperty(ref _isExpanded, value);
    }

    public bool HasAssets => Assets.Count > 0;

    public string Header => _hasLoaded
        ? LocalizationManager.Format("AssociatedAssetsHeaderCount", Assets.Count)
        : LocalizationManager.Get("AssociatedAssets");

    public string Status
    {
        get => _status;
        private set => SetProperty(ref _status, value);
    }

    public void SelectSource(string? sessionId, ArchiveEntryDto? source)
    {
        Interlocked.Increment(ref _generation);
        Interlocked.Exchange(ref _findOperation, null)?.Cancel();
        _sessionId = sessionId;
        _source = source;
        _assetDtos = [];
        _hasLoaded = false;
        _truncated = false;
        _lastError = null;
        _progressCompleted = 0;
        _progressTotal = 0;
        Assets.Clear();
        SelectedAsset = null;
        IsBusy = false;
        Status = LocalizationManager.Get(source is null
            ? "AssociatedAssetsSelectFile"
            : "AssociatedAssetsNotLoaded");
        OnPropertyChanged(nameof(HasAssets));
        OnPropertyChanged(nameof(Header));
        RaiseCommandStates();
    }

    public void RefreshLocalization()
    {
        RebuildRows();
        RefreshStatus();
        OnPropertyChanged(nameof(Header));
    }

    public void RaiseCommandStates()
    {
        FindCommand.RaiseCanExecuteChanged();
        CancelCommand.RaiseCanExecuteChanged();
        ShowInBrowserCommand.RaiseCanExecuteChanged();
    }

    public void RequestShutdown()
    {
        Interlocked.Increment(ref _generation);
        Interlocked.Exchange(ref _findOperation, null)?.Cancel();
        FindCommand.Cancel();
        ShowInBrowserCommand.Cancel();
        IsBusy = false;
    }

    private bool CanFind() =>
        _source is not null
        && !string.IsNullOrWhiteSpace(_sessionId)
        && !IsBusy
        && _canInteract();

    private bool CanShowInBrowser() =>
        SelectedAsset is not null
        && !IsBusy
        && !string.IsNullOrWhiteSpace(_sessionId)
        && _canInteract();

    private void CancelFind()
    {
        Interlocked.Increment(ref _generation);
        Interlocked.Exchange(ref _findOperation, null)?.Cancel();
        _lastError = null;
        IsBusy = false;
        RefreshStatus();
    }

    private async Task FindAsync(CancellationToken commandToken)
    {
        var sessionId = _sessionId;
        var source = _source;
        if (source is null || string.IsNullOrWhiteSpace(sessionId))
        {
            return;
        }

        var generation = Interlocked.Increment(ref _generation);
        using var operation = CancellationTokenSource.CreateLinkedTokenSource(commandToken);
        Interlocked.Exchange(ref _findOperation, operation)?.Cancel();
        try
        {
            IsBusy = true;
            IsExpanded = true;
            _lastError = null;
            _progressCompleted = 0;
            _progressTotal = 0;
            Status = LocalizationManager.Get("AssociatedAssetsSearching");
            var progress = new Progress<ProgressUpdate>(update =>
                ApplyProgress(sessionId, source.EntryId, generation, update));
            var result = await _worker.SendAsync<FindAssociatedAssetsRequest, FindAssociatedAssetsResult>(
                WorkerProtocol.FindAssociatedAssets,
                generation,
                new FindAssociatedAssetsRequest(sessionId, source.EntryId),
                operation.Token,
                progress).ConfigureAwait(true);
            if (!IsCurrent(sessionId, source.EntryId, generation))
            {
                return;
            }

            _assetDtos = result.Assets;
            _hasLoaded = true;
            _truncated = result.Truncated;
            RebuildRows();
            RefreshStatus();
        }
        catch (OperationCanceledException)
        {
            // A newer selection, request, or shutdown owns this lane.
        }
        catch (Exception exception)
        {
            if (IsCurrent(sessionId, source.EntryId, generation))
            {
                _lastError = exception.Message;
                RefreshStatus();
                _setShellStatus(exception.Message);
            }
        }
        finally
        {
            if (IsCurrent(sessionId, source.EntryId, generation))
            {
                IsBusy = false;
                RefreshStatus();
            }
            Interlocked.CompareExchange(ref _findOperation, null, operation);
        }
    }

    private async Task ShowSelectedInBrowserAsync(CancellationToken cancellationToken)
    {
        var sessionId = _sessionId;
        var selected = SelectedAsset;
        if (selected is null || string.IsNullOrWhiteSpace(sessionId))
        {
            return;
        }
        try
        {
            await _showInBrowser(sessionId, selected.Entry, cancellationToken).ConfigureAwait(true);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _setShellStatus(exception.Message);
        }
    }

    private void ApplyProgress(string sessionId, long entryId, long generation, ProgressUpdate update)
    {
        if (!IsCurrent(sessionId, entryId, generation))
        {
            return;
        }
        _progressCompleted = update.Completed;
        _progressTotal = update.Total;
        Status = update.Total > 0
            ? LocalizationManager.Format("AssociatedAssetsScanningProgress", update.Completed, update.Total)
            : LocalizationManager.Get("AssociatedAssetsSearching");
    }

    private bool IsCurrent(string sessionId, long entryId, long generation) =>
        generation == Volatile.Read(ref _generation)
        && string.Equals(_sessionId, sessionId, StringComparison.Ordinal)
        && _source?.EntryId == entryId;

    private void RebuildRows()
    {
        var selectedId = SelectedAsset?.Entry.EntryId;
        Assets.Clear();
        foreach (var asset in _assetDtos)
        {
            Assets.Add(new AssociatedAssetRow(asset));
        }
        SelectedAsset = selectedId is { } entryId
            ? Assets.FirstOrDefault(asset => asset.Entry.EntryId == entryId)
            : null;
        AssetsView.Refresh();
        OnPropertyChanged(nameof(HasAssets));
        OnPropertyChanged(nameof(Header));
    }

    private void RefreshStatus()
    {
        Status = _lastError is not null
            ? LocalizationManager.Format("AssociatedAssetsFailed", _lastError)
            : IsBusy && _progressTotal > 0
                ? LocalizationManager.Format("AssociatedAssetsScanningProgress", _progressCompleted, _progressTotal)
                : IsBusy
                    ? LocalizationManager.Get("AssociatedAssetsSearching")
                    : _source is null
                        ? LocalizationManager.Get("AssociatedAssetsSelectFile")
                        : !_hasLoaded
                            ? LocalizationManager.Get("AssociatedAssetsNotLoaded")
                            : Assets.Count == 0
                                ? LocalizationManager.Get("AssociatedAssetsNone")
                                : LocalizationManager.Format(
                                    _truncated ? "AssociatedAssetsFoundTruncated" : "AssociatedAssetsFound",
                                    Assets.Count);
    }
}

public sealed record AssociatedAssetRow(AssociatedAssetDto Asset)
{
    public ArchiveEntryDto Entry => Asset.Entry;
    public string Name => Entry.Name;
    public string KnownName => Entry.KnownName;
    public string Path => Entry.Path;
    public string CategoryLabel => LocalizationManager.Get($"AssociatedCategory{Asset.Category}");
    public string EvidenceLabel => LocalizationManager.Get($"AssociationEvidence{Asset.Evidence}");
    public string Reason => LocalizationManager.Format($"AssociationReason{Asset.Evidence}", Asset.EvidenceSource);
}
