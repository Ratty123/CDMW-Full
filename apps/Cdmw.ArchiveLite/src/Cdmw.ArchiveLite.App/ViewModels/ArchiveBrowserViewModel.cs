using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Windows.Data;
using System.Windows.Media.Imaging;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;
using Microsoft.Win32;

namespace Cdmw.ArchiveLite.App.ViewModels;

public sealed class ArchiveBrowserViewModel : ObservableObject
{
    private const int PageSize = 256;

    private readonly WorkerProcessHost _worker;
    private readonly Action<string> _setShellStatus;
    private readonly Func<string, bool, ArchiveCacheMode?> _chooseCacheMode;
    private CancellationTokenSource? _foregroundOperation;
    private CancellationTokenSource? _previewOperation;
    private CancellationTokenSource? _catalogueOperation;
    private CancellationTokenSource? _environmentOperation;
    private long _foregroundGeneration;
    private long _previewGeneration;
    private long _catalogueGeneration;
    private long _environmentGeneration;
    private string _archiveRoot;
    private string? _sessionId;
    private string _pathFilter = string.Empty;
    private string _extensionFilter = string.Empty;
    private string _packageFilter = string.Empty;
    private bool _previewableOnly;
    private ArchiveViewMode _viewMode = ArchiveViewMode.Flat;
    private ArchiveSortField _sortField = ArchiveSortField.Path;
    private bool _sortDescending;
    private ArchiveFolderFilter? _selectedFolder;
    private ArchiveRoleFilter _selectedRole = null!;
    private ArchiveCategoryCount? _selectedCategory;
    private ArchiveEntryDto? _selectedEntry;
    private string _previewTitle = LocalizationManager.Get("Preview");
    private string _previewMetadata = string.Empty;
    private string _previewText = LocalizationManager.Get("PreviewEmpty");
    private string _previewWarnings = string.Empty;
    private BitmapSource? _previewImage;
    private Uri? _previewMediaSource;
    private string? _modelPreviewPackagePath;
    private PreviewKind _previewKind = PreviewKind.Metadata;
    private bool _isPreviewBusy;
    private string _previewProgressText = string.Empty;
    private long _totalMatches;
    private int _pageStart;
    private bool _isBusy;
    private string _operationProgressText = string.Empty;
    private double _operationProgressPercent;
    private bool _isOperationProgressIndeterminate = true;
    private ExportCollisionPolicy _collisionPolicy = ExportCollisionPolicy.Skip;
    private ExportManifestFormat _manifestFormat = ExportManifestFormat.Json;
    private bool _isExtensionCatalogBusy;
    private bool _isNameIndexBusy;
    private string _catalogueStatus = string.Empty;
    private bool _suppressPreviewSelection;
    private ArchiveQuerySpec? _lastAppliedQuery;
    private bool _isEnvironmentBusy;
    private ArchiveCacheHealthState _cacheHealthState = ArchiveCacheHealthState.Unknown;
    private string _cacheHealthDetail = LocalizationManager.Get("CacheNotChecked");
    private string _cacheHealthRoot = string.Empty;
    private string _environmentStatus = string.Empty;
    private IReadOnlyList<LocalizedOption<ArchiveViewMode>> _viewModes = [];
    private IReadOnlyList<LocalizedOption<ArchiveSortField>> _sortFields = [];
    private IReadOnlyList<ArchiveRoleFilter> _roleFilters = [];
    private IReadOnlyList<LocalizedOption<ExportCollisionPolicy>> _collisionPolicies = [];
    private IReadOnlyList<LocalizedOption<ExportManifestFormat>> _manifestFormats = [];

    public ArchiveBrowserViewModel(
        WorkerProcessHost worker,
        string? archiveRoot,
        Action<string> setShellStatus,
        Func<string, bool, ArchiveCacheMode?> chooseCacheMode,
        ArchiveSortField initialSortField = ArchiveSortField.Path,
        bool initialSortDescending = false)
    {
        _worker = worker;
        _setShellStatus = setShellStatus;
        _chooseCacheMode = chooseCacheMode ?? throw new ArgumentNullException(nameof(chooseCacheMode));
        _archiveRoot = archiveRoot ?? string.Empty;
        _sortField = initialSortField;
        _sortDescending = initialSortDescending;
        AssociatedAssets = new AssociatedAssetsViewModel(
            worker,
            ShowAssociatedAssetInBrowserAsync,
            () => !IsBusy && !IsEnvironmentBusy,
            setShellStatus);
        BrowseCommand = new AsyncCommand(BrowseAsync, () => !IsBusy && !IsEnvironmentBusy);
        DetectGameCommand = new AsyncCommand(
            token => DetectAndInspectEnvironmentAsync(preferDetectedRoot: true, token),
            () => !IsBusy && !IsEnvironmentBusy);
        OpenCommand = new AsyncCommand(token => ChooseAndOpenArchiveAsync(false, token), CanOpenArchive);
        RefreshCommand = new AsyncCommand(
            token => ChooseAndOpenArchiveAsync(true, token),
            CanRefreshArchive);
        ApplyFilterCommand = new AsyncCommand(token => QueryAsync(0, token), () => !string.IsNullOrWhiteSpace(SessionId) && !IsBusy);
        PreviousPageCommand = new AsyncCommand(token => QueryAsync(Math.Max(0, PageStart - PageSize), token), () => PageStart > 0 && !IsBusy);
        NextPageCommand = new AsyncCommand(token => QueryAsync(PageStart + PageSize, token), () => PageStart + Entries.Count < TotalMatches && !IsBusy);
        CancelCommand = new RelayCommand(CancelForeground, () => IsBusy);
        ExportSelectedCommand = new AsyncCommand(ExportSelectedAsync, () => SelectedEntry is not null && !IsBusy);
        ExportMeshCommand = new AsyncCommand(ExportMeshAsync, () => CanExportSelectedMesh && !IsBusy);
        ExportFilteredCommand = new AsyncCommand(ExportFilteredAsync, () => TotalMatches > 0 && !IsBusy);
        RebuildLocalizedOptions();
        ExtensionChoices.Add(ArchiveExtensionChoice.AllFiles(LocalizationManager.Get("AllFiles"), LocalizationManager.Get("ExtensionGroupAll")));
        ExtensionChoicesView = CollectionViewSource.GetDefaultView(ExtensionChoices);
        ExtensionChoicesView.GroupDescriptions.Add(new PropertyGroupDescription(nameof(ArchiveExtensionChoice.Group)));
    }

    public ObservableCollection<ArchiveEntryDto> Entries { get; } = [];
    public ObservableCollection<ArchiveFolderFilter> Folders { get; } = [];
    public ObservableCollection<ArchiveCategoryCount> Categories { get; } = [];
    public ObservableCollection<ArchiveExtensionChoice> ExtensionChoices { get; } = [];
    public ICollectionView ExtensionChoicesView { get; }
    public AssociatedAssetsViewModel AssociatedAssets { get; }

    public IReadOnlyList<LocalizedOption<ArchiveViewMode>> ViewModes => _viewModes;
    public IReadOnlyList<LocalizedOption<ArchiveSortField>> SortFields => _sortFields;
    public IReadOnlyList<ArchiveRoleFilter> RoleFilters => _roleFilters;
    public IReadOnlyList<LocalizedOption<ExportCollisionPolicy>> CollisionPolicies => _collisionPolicies;
    public IReadOnlyList<LocalizedOption<ExportManifestFormat>> ManifestFormats => _manifestFormats;

    public AsyncCommand BrowseCommand { get; }
    public AsyncCommand DetectGameCommand { get; }
    public AsyncCommand OpenCommand { get; }
    public AsyncCommand RefreshCommand { get; }
    public AsyncCommand ApplyFilterCommand { get; }
    public AsyncCommand PreviousPageCommand { get; }
    public AsyncCommand NextPageCommand { get; }
    public RelayCommand CancelCommand { get; }
    public AsyncCommand ExportSelectedCommand { get; }
    public AsyncCommand ExportMeshCommand { get; }
    public AsyncCommand ExportFilteredCommand { get; }

    public event EventHandler? SessionChanged;

    public void RefreshLocalization()
    {
        RebuildLocalizedOptions(SelectedRole.Role);
        RefreshNavigationLabels();
        RefreshExtensionLabels();
        AssociatedAssets.RefreshLocalization();
        OnPropertyChanged(nameof(CacheHealthLabel));
        OnPropertyChanged(nameof(PageSummary));
        OnPropertyChanged(nameof(TotalMatchesLabel));

        CacheHealthDetail = CacheHealthState switch
        {
            ArchiveCacheHealthState.Checking => LocalizationManager.Get("CacheChecking"),
            ArchiveCacheHealthState.Current => LocalizationManager.Get("CacheCurrent"),
            ArchiveCacheHealthState.SessionOnly => LocalizationManager.Get("CacheSessionOnly"),
            ArchiveCacheHealthState.Missing => LocalizationManager.Get("CacheMissing"),
            ArchiveCacheHealthState.Stale => LocalizationManager.Get("CacheRefreshRecommended"),
            ArchiveCacheHealthState.Invalid => LocalizationManager.Get("CacheInvalid"),
            _ => LocalizationManager.Get("CacheNotChecked"),
        };
        if (!string.IsNullOrWhiteSpace(EnvironmentStatus))
        {
            EnvironmentStatus = string.IsNullOrWhiteSpace(ArchiveRoot)
                ? LocalizationManager.Get("GameNotFound")
                : LocalizationManager.Format("GameFolderReady", ArchiveRoot);
        }
        if (IsExtensionCatalogBusy)
        {
            CatalogueStatus = LocalizationManager.Get("ExtensionCatalogLoading");
        }
        else if (IsNameIndexBusy)
        {
            CatalogueStatus = LocalizationManager.Get("NameIndexLoading");
        }
        if (SelectedEntry is null)
        {
            PreviewTitle = LocalizationManager.Get("Preview");
            PreviewText = LocalizationManager.Get("PreviewEmpty");
        }
        if (IsPreviewBusy)
        {
            PreviewProgressText = LocalizationManager.Get("PreviewProgressPreparing");
        }
        if (IsBusy)
        {
            OperationProgressText = LocalizationManager.Get("ProgressWorking");
        }
    }

    public string ArchiveRoot
    {
        get => _archiveRoot;
        set
        {
            if (SetProperty(ref _archiveRoot, value))
            {
                if (!PathsEqual(_cacheHealthRoot, value))
                {
                    _cacheHealthRoot = string.Empty;
                    CacheHealthState = ArchiveCacheHealthState.Unknown;
                    CacheHealthDetail = LocalizationManager.Get("CacheNotChecked");
                }
                RaiseCommandStates();
            }
        }
    }

    public bool IsEnvironmentBusy
    {
        get => _isEnvironmentBusy;
        private set
        {
            if (SetProperty(ref _isEnvironmentBusy, value))
            {
                RaiseCommandStates();
            }
        }
    }

    public ArchiveCacheHealthState CacheHealthState
    {
        get => _cacheHealthState;
        private set
        {
            if (SetProperty(ref _cacheHealthState, value))
            {
                OnPropertyChanged(nameof(CacheHealthLabel));
                RaiseCommandStates();
            }
        }
    }

    public string CacheHealthLabel => LocalizationManager.Get(CacheHealthState switch
    {
        ArchiveCacheHealthState.Checking => "CacheChecking",
        ArchiveCacheHealthState.Current => "CacheCurrent",
        ArchiveCacheHealthState.SessionOnly => "CacheSessionOnly",
        ArchiveCacheHealthState.Missing => "CacheMissing",
        ArchiveCacheHealthState.Stale => "CacheStale",
        ArchiveCacheHealthState.Invalid => "CacheInvalid",
        _ => "CacheNotChecked",
    });

    public string CacheHealthDetail
    {
        get => _cacheHealthDetail;
        private set => SetProperty(ref _cacheHealthDetail, value);
    }

    public string EnvironmentStatus
    {
        get => _environmentStatus;
        private set => SetProperty(ref _environmentStatus, value);
    }

    public string? SessionId
    {
        get => _sessionId;
        private set
        {
            if (SetProperty(ref _sessionId, value))
            {
                AssociatedAssets.SelectSource(value, null);
                RaiseCommandStates();
                SessionChanged?.Invoke(this, EventArgs.Empty);
            }
        }
    }

    public string PathFilter
    {
        get => _pathFilter;
        set => SetProperty(ref _pathFilter, value);
    }

    public string ExtensionFilter
    {
        get => _extensionFilter;
        set => SetProperty(ref _extensionFilter, value);
    }

    public string PackageFilter
    {
        get => _packageFilter;
        set => SetProperty(ref _packageFilter, value);
    }

    public bool PreviewableOnly
    {
        get => _previewableOnly;
        set => SetProperty(ref _previewableOnly, value);
    }

    public ArchiveViewMode ViewMode
    {
        get => _viewMode;
        set
        {
            if (SetProperty(ref _viewMode, value))
            {
                OnPropertyChanged(nameof(ShowFolderNavigator));
                OnPropertyChanged(nameof(ShowCategoryNavigator));
            }
        }
    }

    public bool ShowFolderNavigator => ViewMode is ArchiveViewMode.Folders or ArchiveViewMode.CategoriesAndFolders;
    public bool ShowCategoryNavigator => ViewMode is ArchiveViewMode.Categories or ArchiveViewMode.CategoriesAndFolders;

    public ArchiveSortField SortField
    {
        get => _sortField;
        set => SetProperty(ref _sortField, value);
    }

    public bool SortDescending
    {
        get => _sortDescending;
        set => SetProperty(ref _sortDescending, value);
    }

    public bool IsExtensionCatalogBusy
    {
        get => _isExtensionCatalogBusy;
        private set => SetProperty(ref _isExtensionCatalogBusy, value);
    }

    public bool IsNameIndexBusy
    {
        get => _isNameIndexBusy;
        private set => SetProperty(ref _isNameIndexBusy, value);
    }

    public string CatalogueStatus
    {
        get => _catalogueStatus;
        private set => SetProperty(ref _catalogueStatus, value);
    }

    public void ApplyColumnSort(ArchiveSortField field)
    {
        if (IsBusy || string.IsNullOrWhiteSpace(SessionId))
        {
            return;
        }
        if (SortField == field)
        {
            SortDescending = !SortDescending;
        }
        else
        {
            SortField = field;
            SortDescending = false;
        }
        ApplyFilterCommand.Execute(null);
    }

    public ArchiveFolderFilter? SelectedFolder
    {
        get => _selectedFolder;
        set => SetProperty(ref _selectedFolder, value);
    }

    public ArchiveRoleFilter SelectedRole
    {
        get => _selectedRole;
        set
        {
            if (value is not null) SetProperty(ref _selectedRole, value);
        }
    }

    public ArchiveCategoryCount? SelectedCategory
    {
        get => _selectedCategory;
        set
        {
            if (!SetProperty(ref _selectedCategory, value) || value is null || !Enum.TryParse<ArchiveEntryRole>(value.Name, out var role))
            {
                return;
            }

            SelectedRole = RoleFilters.First(option => option.Role == role);
        }
    }

    public ArchiveEntryDto? SelectedEntry
    {
        get => _selectedEntry;
        set
        {
            if (SetProperty(ref _selectedEntry, value))
            {
                AssociatedAssets.SelectSource(SessionId, value);
                ExportSelectedCommand.RaiseCanExecuteChanged();
                ExportMeshCommand.RaiseCanExecuteChanged();
                OnPropertyChanged(nameof(CanExportSelectedMesh));
                if (!_suppressPreviewSelection)
                {
                    _ = LoadPreviewLatestAsync(value);
                }
            }
        }
    }

    public string PreviewTitle
    {
        get => _previewTitle;
        private set => SetProperty(ref _previewTitle, value);
    }

    public string PreviewMetadata
    {
        get => _previewMetadata;
        private set => SetProperty(ref _previewMetadata, value);
    }

    public string PreviewText
    {
        get => _previewText;
        private set => SetProperty(ref _previewText, value);
    }

    public string PreviewWarnings
    {
        get => _previewWarnings;
        private set => SetProperty(ref _previewWarnings, value);
    }

    public BitmapSource? PreviewImage
    {
        get => _previewImage;
        private set => SetProperty(ref _previewImage, value);
    }

    public Uri? PreviewMediaSource
    {
        get => _previewMediaSource;
        private set => SetProperty(ref _previewMediaSource, value);
    }

    public PreviewKind PreviewKind
    {
        get => _previewKind;
        private set
        {
            if (SetProperty(ref _previewKind, value))
            {
                OnPropertyChanged(nameof(IsImagePreview));
                OnPropertyChanged(nameof(IsMediaPreview));
                OnPropertyChanged(nameof(IsModelPreview));
                OnPropertyChanged(nameof(IsTextPreview));
            }
        }
    }

    public string? ModelPreviewPackagePath
    {
        get => _modelPreviewPackagePath;
        private set
        {
            if (SetProperty(ref _modelPreviewPackagePath, value))
            {
                OnPropertyChanged(nameof(IsModelPreview));
                OnPropertyChanged(nameof(IsTextPreview));
            }
        }
    }

    public bool IsPreviewBusy
    {
        get => _isPreviewBusy;
        private set => SetProperty(ref _isPreviewBusy, value);
    }

    public string PreviewProgressText
    {
        get => _previewProgressText;
        private set => SetProperty(ref _previewProgressText, value);
    }

    public bool IsImagePreview => PreviewKind == PreviewKind.Image && PreviewImage is not null;
    public bool IsMediaPreview => PreviewKind is PreviewKind.Audio or PreviewKind.Video && PreviewMediaSource is not null;
    public bool IsModelPreview => PreviewKind == PreviewKind.Model && !string.IsNullOrWhiteSpace(ModelPreviewPackagePath);
    public bool IsTextPreview => !IsImagePreview && !IsMediaPreview && !IsModelPreview;

    public long TotalMatches
    {
        get => _totalMatches;
        private set
        {
            if (SetProperty(ref _totalMatches, value))
            {
                OnPropertyChanged(nameof(PageSummary));
                OnPropertyChanged(nameof(TotalMatchesLabel));
                RaiseCommandStates();
            }
        }
    }

    public int PageStart
    {
        get => _pageStart;
        private set
        {
            if (SetProperty(ref _pageStart, value))
            {
                OnPropertyChanged(nameof(PageSummary));
                RaiseCommandStates();
            }
        }
    }

    public string PageSummary => TotalMatches == 0
        ? "0"
        : $"{PageStart + 1:N0}-{Math.Min(TotalMatches, PageStart + Entries.Count):N0} / {TotalMatches:N0}";

    public string TotalMatchesLabel => LocalizationManager.Format("EntriesCount", TotalMatches);

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                OnPropertyChanged(nameof(IsOperationProgressVisible));
                RaiseCommandStates();
            }
        }
    }

    public bool IsOperationProgressVisible => IsBusy;

    public string OperationProgressText
    {
        get => _operationProgressText;
        private set => SetProperty(ref _operationProgressText, value);
    }

    public double OperationProgressPercent
    {
        get => _operationProgressPercent;
        private set => SetProperty(ref _operationProgressPercent, value);
    }

    public bool IsOperationProgressIndeterminate
    {
        get => _isOperationProgressIndeterminate;
        private set => SetProperty(ref _isOperationProgressIndeterminate, value);
    }

    public ExportCollisionPolicy CollisionPolicy
    {
        get => _collisionPolicy;
        set => SetProperty(ref _collisionPolicy, value);
    }

    public ExportManifestFormat ManifestFormat
    {
        get => _manifestFormat;
        set => SetProperty(ref _manifestFormat, value);
    }

    public bool CanExportSelectedMesh => SelectedEntry is not null
        && SelectedEntry.Extension.ToLowerInvariant() is ".pac" or ".pam" or ".pamlod";

    public void RequestShutdown()
    {
        CancelEnvironment();
        CancelForeground();
        Interlocked.Increment(ref _previewGeneration);
        CancelOperation(Interlocked.Exchange(ref _previewOperation, null));
        Interlocked.Increment(ref _catalogueGeneration);
        CancelOperation(Interlocked.Exchange(ref _catalogueOperation, null));
        AssociatedAssets.RequestShutdown();
    }

    public async Task InitializeEnvironmentAsync(CancellationToken cancellationToken)
    {
        await DetectAndInspectEnvironmentAsync(preferDetectedRoot: false, cancellationToken).ConfigureAwait(true);
        cancellationToken.ThrowIfCancellationRequested();
        if (CacheHealthState == ArchiveCacheHealthState.Current &&
            string.IsNullOrWhiteSpace(SessionId) &&
            !string.IsNullOrWhiteSpace(ArchiveRoot))
        {
            await OpenArchiveAsync(
                forceRefresh: false,
                ArchiveCacheMode.Persistent,
                cancellationToken,
                allowCacheBuild: false).ConfigureAwait(true);
        }
    }

    private async Task BrowseAsync(CancellationToken cancellationToken)
    {
        var dialog = new OpenFolderDialog
        {
            Title = LocalizationManager.Get("ArchiveRoot"),
            Multiselect = false,
        };
        if (dialog.ShowDialog() == true)
        {
            ArchiveRoot = dialog.FolderName;
            await InspectSelectedRootAsync(cancellationToken).ConfigureAwait(true);
        }
    }

    private bool CanOpenArchive() =>
        !string.IsNullOrWhiteSpace(ArchiveRoot) &&
        CacheHealthState != ArchiveCacheHealthState.Stale &&
        !IsBusy &&
        !IsEnvironmentBusy;

    private bool CanRefreshArchive() =>
        !string.IsNullOrWhiteSpace(ArchiveRoot) && !IsBusy && !IsEnvironmentBusy;

    private async Task DetectAndInspectEnvironmentAsync(
        bool preferDetectedRoot,
        CancellationToken cancellationToken)
    {
        using var operation = BeginEnvironmentOperation(cancellationToken);
        var generation = Interlocked.Increment(ref _environmentGeneration);
        try
        {
            EnvironmentStatus = LocalizationManager.Get("DetectingGame");
            var discovery = await _worker.SendAsync<GameInstallDiscoveryRequest, GameInstallDiscoveryResult>(
                WorkerProtocol.DiscoverGameRoots,
                generation,
                new GameInstallDiscoveryRequest(),
                operation.Token).ConfigureAwait(true);
            if (!EnvironmentIsCurrent(generation))
            {
                return;
            }

            var configuredRoot = ArchiveRoot.Trim();
            var configuredExists = Path.Exists(configuredRoot);
            var selectedRoot = preferDetectedRoot && discovery.PreferredRoot is not null
                ? discovery.PreferredRoot
                : configuredExists
                    ? configuredRoot
                    : discovery.PreferredRoot ?? (configuredRoot.Length > 0 ? configuredRoot : null);

            if (string.IsNullOrWhiteSpace(selectedRoot))
            {
                EnvironmentStatus = LocalizationManager.Get("GameNotFound");
                CacheHealthState = ArchiveCacheHealthState.Unknown;
                CacheHealthDetail = LocalizationManager.Get("CacheNotChecked");
                return;
            }

            ArchiveRoot = selectedRoot;
            EnvironmentStatus = LocalizationManager.Format(
                PathsEqual(selectedRoot, discovery.PreferredRoot) ? "GameDetected" : "GameFolderReady",
                selectedRoot);
            await InspectCacheCoreAsync(selectedRoot, generation, operation.Token).ConfigureAwait(true);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            if (EnvironmentIsCurrent(generation))
            {
                EnvironmentStatus = exception.Message;
                CacheHealthState = ArchiveCacheHealthState.Invalid;
                CacheHealthDetail = exception.Message;
            }
        }
        finally
        {
            EndEnvironmentOperation(operation);
        }
    }

    private async Task InspectSelectedRootAsync(CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(ArchiveRoot))
        {
            return;
        }

        using var operation = BeginEnvironmentOperation(cancellationToken);
        var generation = Interlocked.Increment(ref _environmentGeneration);
        try
        {
            EnvironmentStatus = LocalizationManager.Format("GameFolderReady", ArchiveRoot);
            await InspectCacheCoreAsync(ArchiveRoot, generation, operation.Token).ConfigureAwait(true);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            if (EnvironmentIsCurrent(generation))
            {
                CacheHealthState = ArchiveCacheHealthState.Invalid;
                CacheHealthDetail = exception.Message;
                EnvironmentStatus = exception.Message;
            }
        }
        finally
        {
            EndEnvironmentOperation(operation);
        }
    }

    private async Task InspectCacheCoreAsync(
        string archiveRoot,
        long generation,
        CancellationToken cancellationToken)
    {
        CacheHealthState = ArchiveCacheHealthState.Checking;
        CacheHealthDetail = LocalizationManager.Get("CacheChecking");
        var result = await _worker.SendAsync<ArchiveCacheHealthRequest, ArchiveCacheHealthResult>(
            WorkerProtocol.InspectArchiveCache,
            generation,
            new ArchiveCacheHealthRequest(archiveRoot),
            cancellationToken).ConfigureAwait(true);
        if (!EnvironmentIsCurrent(generation) || !PathsEqual(ArchiveRoot, result.PackageRoot))
        {
            return;
        }

        _cacheHealthRoot = result.PackageRoot;
        CacheHealthState = result.State;
        CacheHealthDetail = result.State == ArchiveCacheHealthState.Stale
            ? $"{result.Reason} {LocalizationManager.Get("CacheRefreshRecommended")}"
            : result.Reason;
    }

    private async Task ChooseAndOpenArchiveAsync(bool forceRefresh, CancellationToken commandToken)
    {
        commandToken.ThrowIfCancellationRequested();
        var cacheMode = _chooseCacheMode(ArchiveRoot.Trim(), forceRefresh);
        if (cacheMode is null)
        {
            return;
        }
        await OpenArchiveAsync(forceRefresh, cacheMode.Value, commandToken).ConfigureAwait(true);
    }

    private async Task OpenArchiveAsync(
        bool forceRefresh,
        ArchiveCacheMode cacheMode,
        CancellationToken commandToken,
        bool allowCacheBuild = true)
    {
        using var operation = BeginForegroundOperation(commandToken);
        var generation = Interlocked.Increment(ref _foregroundGeneration);
        CancelCatalogue();
        CancelPreviewAndClear();
        try
        {
            _setShellStatus(LocalizationManager.Format("OpeningArchive", ArchiveRoot));
            SetOperationProgress(LocalizationManager.Get("ProgressDiscovering"));
            var progress = new Progress<ProgressUpdate>(update => ApplyForegroundProgress(generation, update));
            var result = await _worker.SendAsync<OpenArchiveRequest, OpenArchiveResult>(
                WorkerProtocol.OpenArchive,
                generation,
                new OpenArchiveRequest(ArchiveRoot, forceRefresh, cacheMode, allowCacheBuild),
                operation.Token,
                progress).ConfigureAwait(true);
            if (generation != Volatile.Read(ref _foregroundGeneration))
            {
                return;
            }

            SessionId = result.SessionId;
            _cacheHealthRoot = result.PackageRoot;
            CacheHealthState = result.CacheMode == ArchiveCacheMode.SessionOnly
                ? ArchiveCacheHealthState.SessionOnly
                : ArchiveCacheHealthState.Current;
            CacheHealthDetail = LocalizationManager.Get(result.CacheMode == ArchiveCacheMode.SessionOnly
                ? "CacheSessionOnlyLoaded"
                : (result.UsedCachedIndex ? "CacheReused" : "CacheRebuilt"));
            _setShellStatus(LocalizationManager.Format("OpenedEntries", result.EntryCount));
            SetOperationProgress(LocalizationManager.Get("ProgressLoadingEntries"));
            await QueryPageCoreAsync(0, generation, operation.Token).ConfigureAwait(true);
            StartCatalogueLoad(result.SessionId);
        }
        catch (WorkerRequestException exception) when (exception.Error.Code == "cache_refresh_required")
        {
            _cacheHealthRoot = ArchiveRoot;
            CacheHealthState = ArchiveCacheHealthState.Stale;
            CacheHealthDetail = LocalizationManager.Get("CacheRefreshRecommended");
            _setShellStatus(CacheHealthDetail);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _setShellStatus(exception.Message);
        }
        finally
        {
            EndForegroundOperation(operation);
        }
    }

    private async Task QueryAsync(int pageStart, CancellationToken commandToken)
    {
        if (string.IsNullOrWhiteSpace(SessionId))
        {
            return;
        }

        using var operation = BeginForegroundOperation(commandToken);
        var generation = Interlocked.Increment(ref _foregroundGeneration);
        try
        {
            SetOperationProgress(LocalizationManager.Get("ProgressLoadingEntries"));
            await QueryPageCoreAsync(pageStart, generation, operation.Token).ConfigureAwait(true);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _setShellStatus(exception.Message);
        }
        finally
        {
            EndForegroundOperation(operation);
        }
    }

    private async Task QueryPageCoreAsync(int pageStart, long generation, CancellationToken cancellationToken)
    {
        var sessionId = SessionId;
        if (string.IsNullOrWhiteSpace(sessionId))
        {
            return;
        }

        var request = CreateQuerySpec(sessionId, pageStart);
        var result = await _worker.SendAsync<ArchiveQuerySpec, ArchivePageResult>(
            WorkerProtocol.QueryArchive,
            generation,
            request,
            cancellationToken).ConfigureAwait(true);
        if (generation != Volatile.Read(ref _foregroundGeneration))
        {
            return;
        }
        _lastAppliedQuery = request;

        CancelPreviewAndClear();
        SelectedEntry = null;
        Entries.Clear();
        foreach (var entry in result.Entries)
        {
            Entries.Add(entry);
        }

        Folders.Clear();
        var previousFolder = SelectedFolder?.Path;
        Folders.Add(new ArchiveFolderFilter(null, LocalizationManager.Get("All")));
        foreach (var folder in result.Folders)
        {
            Folders.Add(new ArchiveFolderFilter(folder, folder));
        }
        SelectedFolder = Folders.FirstOrDefault(folder => string.Equals(folder.Path, previousFolder, StringComparison.OrdinalIgnoreCase)) ?? Folders[0];

        Categories.Clear();
        foreach (var category in result.Categories.OrderBy(static pair => pair.Key, StringComparer.OrdinalIgnoreCase))
        {
            var roleLabel = Enum.TryParse<ArchiveEntryRole>(category.Key, out var parsedRole)
                ? LocalizationManager.Get($"Role{parsedRole}")
                : category.Key;
            Categories.Add(new ArchiveCategoryCount(category.Key, roleLabel, category.Value));
        }
        SelectedCategory = null;

        PageStart = result.PageStart;
        TotalMatches = result.TotalMatches;
        OnPropertyChanged(nameof(PageSummary));
        RaiseCommandStates();
        _setShellStatus(LocalizationManager.Format("ShowingEntries", PageSummary));
    }

    private async Task ShowAssociatedAssetInBrowserAsync(
        string sessionId,
        ArchiveEntryDto target,
        CancellationToken commandToken)
    {
        if (IsBusy || !string.Equals(SessionId, sessionId, StringComparison.Ordinal))
        {
            return;
        }

        PathFilter = target.Path;
        ExtensionFilter = string.Empty;
        PackageFilter = string.Empty;
        PreviewableOnly = false;
        ViewMode = ArchiveViewMode.Flat;
        SortField = ArchiveSortField.Path;
        SortDescending = false;
        SelectedFolder = Folders.FirstOrDefault(static folder => folder.Path is null);
        SelectedRole = RoleFilters.First(static role => role.Role is null);
        SelectedCategory = null;

        using var operation = BeginForegroundOperation(commandToken);
        var generation = Interlocked.Increment(ref _foregroundGeneration);
        try
        {
            SetOperationProgress(LocalizationManager.Get("ProgressLoadingEntries"));
            await QueryPageCoreAsync(0, generation, operation.Token).ConfigureAwait(true);
            if (generation != Volatile.Read(ref _foregroundGeneration))
            {
                return;
            }

            var located = Entries.FirstOrDefault(entry => entry.EntryId == target.EntryId);
            if (located is null)
            {
                _setShellStatus(LocalizationManager.Get("AssociatedAssetNotLocated"));
                return;
            }
            SelectedEntry = located;
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _setShellStatus(exception.Message);
        }
        finally
        {
            EndForegroundOperation(operation);
        }
    }

    private ArchiveQuerySpec CreateQuerySpec(string sessionId, int pageStart)
    {
        var extensions = ExtensionFilter.Split([';', ',', ' '], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return new ArchiveQuerySpec(
            sessionId,
            PathFilter,
            extensions,
            PackageFilter,
            SelectedFolder?.Path,
            SelectedRole.Role is { } role ? [role] : null,
            PreviewableOnly: PreviewableOnly,
            ViewMode: ViewMode,
            SortField: SortField,
            SortDescending: SortDescending,
            PageStart: pageStart,
            PageSize: PageSize);
    }

    private void StartCatalogueLoad(string sessionId)
    {
        var generation = Interlocked.Increment(ref _catalogueGeneration);
        var operation = new CancellationTokenSource();
        CancelOperation(Interlocked.Exchange(ref _catalogueOperation, operation));
        _ = LoadCatalogueLatestAsync(sessionId, generation, operation);
    }

    private async Task LoadCatalogueLatestAsync(
        string sessionId,
        long generation,
        CancellationTokenSource operation)
    {
        try
        {
            IsExtensionCatalogBusy = true;
            CatalogueStatus = LocalizationManager.Get("ExtensionCatalogLoading");
            var facetProgress = new Progress<ProgressUpdate>(update =>
            {
                if (generation == Volatile.Read(ref _catalogueGeneration))
                {
                    CatalogueStatus = update.Total > 0
                        ? LocalizationManager.Format("ExtensionCatalogProgress", update.Completed, update.Total)
                        : LocalizationManager.Get("ExtensionCatalogLoading");
                }
            });
            var facets = await _worker.SendAsync<ArchiveFacetsRequest, ArchiveFacetsResult>(
                WorkerProtocol.ArchiveFacets,
                generation,
                new ArchiveFacetsRequest(sessionId),
                operation.Token,
                facetProgress).ConfigureAwait(true);
            if (!CatalogueIsCurrent(sessionId, generation))
            {
                return;
            }
            ApplyExtensionFacets(facets.Extensions);
            IsExtensionCatalogBusy = false;

            IsNameIndexBusy = true;
            CatalogueStatus = LocalizationManager.Get("NameIndexLoading");
            var nameProgress = new Progress<ProgressUpdate>(update => ApplyNameIndexProgress(sessionId, generation, update));
            var names = await _worker.SendAsync<BuildNameIndexRequest, BuildNameIndexResult>(
                WorkerProtocol.BuildNameIndex,
                generation,
                new BuildNameIndexRequest(sessionId),
                operation.Token,
                nameProgress).ConfigureAwait(true);
            if (!CatalogueIsCurrent(sessionId, generation))
            {
                return;
            }

            CatalogueStatus = names.Available
                ? LocalizationManager.Format("NameIndexReady", names.ExactNameCount, names.RelatedNameCount)
                : names.Warning ?? LocalizationManager.Get("NameIndexUnavailable");
            IsNameIndexBusy = false;
            if (names.Available)
            {
                await RefreshCurrentPageAfterNameIndexAsync(sessionId, generation, operation.Token).ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            // A newer archive session or application shutdown owns catalogue work.
        }
        catch (Exception exception)
        {
            if (CatalogueIsCurrent(sessionId, generation))
            {
                CatalogueStatus = LocalizationManager.Format("NameIndexFailed", exception.Message);
            }
        }
        finally
        {
            if (generation == Volatile.Read(ref _catalogueGeneration))
            {
                IsExtensionCatalogBusy = false;
                IsNameIndexBusy = false;
            }
            Interlocked.CompareExchange(ref _catalogueOperation, null, operation);
            operation.Dispose();
        }
    }

    private void ApplyExtensionFacets(IReadOnlyList<ArchiveExtensionFacet> facets)
    {
        ExtensionChoices.Clear();
        ExtensionChoices.Add(ArchiveExtensionChoice.AllFiles(
            LocalizationManager.Get("AllFiles"),
            LocalizationManager.Get("ExtensionGroupAll")));
        foreach (var facet in facets)
        {
            ExtensionChoices.Add(new ArchiveExtensionChoice(
                facet.Extension,
                facet.Count,
                LocalizationManager.Get($"ExtensionGroup{facet.Category}"),
                facet.Category));
        }
        ExtensionChoicesView.Refresh();
    }

    private void RebuildLocalizedOptions(ArchiveEntryRole? selectedRole = null)
    {
        _viewModes =
        [
            new LocalizedOption<ArchiveViewMode>(ArchiveViewMode.Folders, LocalizationManager.Get("FoldersView")),
            new LocalizedOption<ArchiveViewMode>(ArchiveViewMode.Categories, LocalizationManager.Get("CategoriesView")),
            new LocalizedOption<ArchiveViewMode>(ArchiveViewMode.CategoriesAndFolders, LocalizationManager.Get("CategoriesFoldersView")),
            new LocalizedOption<ArchiveViewMode>(ArchiveViewMode.Flat, LocalizationManager.Get("FlatView")),
        ];
        _sortFields = Enum.GetValues<ArchiveSortField>()
            .Select(field => new LocalizedOption<ArchiveSortField>(field, LocalizationManager.Get($"Sort{field}")))
            .ToArray();
        _collisionPolicies = Enum.GetValues<ExportCollisionPolicy>()
            .Select(policy => new LocalizedOption<ExportCollisionPolicy>(policy, LocalizationManager.Get($"Collision{policy}")))
            .ToArray();
        _manifestFormats = Enum.GetValues<ExportManifestFormat>()
            .Select(format => new LocalizedOption<ExportManifestFormat>(format, LocalizationManager.Get($"Manifest{format}")))
            .ToArray();
        _roleFilters =
        [
            new ArchiveRoleFilter(null, LocalizationManager.Get("All")),
            .. Enum.GetValues<ArchiveEntryRole>()
                .Select(role => new ArchiveRoleFilter(role, LocalizationManager.Get($"Role{role}"))),
        ];
        _selectedRole = RoleFilters.First(option => option.Role == selectedRole);

        OnPropertyChanged(nameof(ViewModes));
        OnPropertyChanged(nameof(SortFields));
        OnPropertyChanged(nameof(CollisionPolicies));
        OnPropertyChanged(nameof(ManifestFormats));
        OnPropertyChanged(nameof(RoleFilters));
        // Replacing a ComboBox ItemsSource can temporarily clear its selection.
        // Reassert the stable enum values after the localized options are visible
        // so a live language switch cannot leave a blank, invalid selection.
        OnPropertyChanged(nameof(ViewMode));
        OnPropertyChanged(nameof(SortField));
        OnPropertyChanged(nameof(CollisionPolicy));
        OnPropertyChanged(nameof(ManifestFormat));
        OnPropertyChanged(nameof(SelectedRole));
    }

    private void RefreshNavigationLabels()
    {
        if (Folders.Count > 0)
        {
            var selectedPath = SelectedFolder?.Path;
            var paths = Folders.Select(static folder => folder.Path).ToArray();
            Folders.Clear();
            foreach (var path in paths)
            {
                Folders.Add(new ArchiveFolderFilter(path, path ?? LocalizationManager.Get("All")));
            }
            SelectedFolder = Folders.FirstOrDefault(folder => string.Equals(folder.Path, selectedPath, StringComparison.OrdinalIgnoreCase))
                ?? Folders[0];
        }

        if (Categories.Count > 0)
        {
            var selectedName = SelectedCategory?.Name;
            var categories = Categories.Select(static category => (category.Name, category.Count)).ToArray();
            Categories.Clear();
            foreach (var category in categories)
            {
                var label = Enum.TryParse<ArchiveEntryRole>(category.Name, out var role)
                    ? LocalizationManager.Get($"Role{role}")
                    : category.Name;
                Categories.Add(new ArchiveCategoryCount(category.Name, label, category.Count));
            }
            SelectedCategory = selectedName is null
                ? null
                : Categories.FirstOrDefault(category => string.Equals(category.Name, selectedName, StringComparison.OrdinalIgnoreCase));
        }
    }

    private void RefreshExtensionLabels()
    {
        var extensions = ExtensionChoices
            .Where(static choice => choice.Category.HasValue)
            .Select(static choice => (choice.Extension, choice.Count, Category: choice.Category!.Value))
            .ToArray();
        ApplyExtensionFacets(extensions
            .Select(static choice => new ArchiveExtensionFacet(choice.Extension, choice.Count, choice.Category))
            .ToArray());
    }

    private void ApplyNameIndexProgress(string sessionId, long generation, ProgressUpdate update)
    {
        if (!CatalogueIsCurrent(sessionId, generation))
        {
            return;
        }
        CatalogueStatus = update.Phase switch
        {
            "name_scan" when update.Total > 0 => LocalizationManager.Format("NameIndexScanProgress", update.Completed, update.Total),
            "name_extract" when !string.IsNullOrWhiteSpace(update.CurrentItem) => LocalizationManager.Format("NameIndexExtracting", update.CurrentItem),
            "name_build" => LocalizationManager.Get("NameIndexResolving"),
            "name_publish" => LocalizationManager.Get("NameIndexPublishing"),
            _ => LocalizationManager.Get("NameIndexLoading"),
        };
    }

    private async Task RefreshCurrentPageAfterNameIndexAsync(
        string sessionId,
        long catalogueGeneration,
        CancellationToken cancellationToken)
    {
        var foregroundGeneration = Volatile.Read(ref _foregroundGeneration);
        var request = _lastAppliedQuery;
        if (IsBusy
            || request is null
            || !string.Equals(request.SessionId, sessionId, StringComparison.Ordinal))
        {
            return;
        }
        var result = await _worker.SendAsync<ArchiveQuerySpec, ArchivePageResult>(
            WorkerProtocol.QueryArchive,
            foregroundGeneration,
            request,
            cancellationToken).ConfigureAwait(true);
        if (!CatalogueIsCurrent(sessionId, catalogueGeneration)
            || foregroundGeneration != Volatile.Read(ref _foregroundGeneration))
        {
            return;
        }

        _lastAppliedQuery = request;
        var selectedEntryId = SelectedEntry?.EntryId;
        _suppressPreviewSelection = true;
        try
        {
            Entries.Clear();
            foreach (var entry in result.Entries)
            {
                Entries.Add(entry);
            }
            SelectedEntry = selectedEntryId is { } entryId
                ? Entries.FirstOrDefault(entry => entry.EntryId == entryId)
                : null;
        }
        finally
        {
            _suppressPreviewSelection = false;
        }

        Folders.Clear();
        var previousFolder = SelectedFolder?.Path;
        Folders.Add(new ArchiveFolderFilter(null, LocalizationManager.Get("All")));
        foreach (var folder in result.Folders)
        {
            Folders.Add(new ArchiveFolderFilter(folder, folder));
        }
        SelectedFolder = Folders.FirstOrDefault(folder => string.Equals(folder.Path, previousFolder, StringComparison.OrdinalIgnoreCase)) ?? Folders[0];

        Categories.Clear();
        foreach (var category in result.Categories.OrderBy(static pair => pair.Key, StringComparer.OrdinalIgnoreCase))
        {
            var roleLabel = Enum.TryParse<ArchiveEntryRole>(category.Key, out var parsedRole)
                ? LocalizationManager.Get($"Role{parsedRole}")
                : category.Key;
            Categories.Add(new ArchiveCategoryCount(category.Key, roleLabel, category.Value));
        }
        PageStart = result.PageStart;
        TotalMatches = result.TotalMatches;
        OnPropertyChanged(nameof(PageSummary));
        RaiseCommandStates();
    }

    private bool CatalogueIsCurrent(string sessionId, long generation) =>
        generation == Volatile.Read(ref _catalogueGeneration)
        && string.Equals(SessionId, sessionId, StringComparison.Ordinal);

    private void CancelCatalogue()
    {
        Interlocked.Increment(ref _catalogueGeneration);
        CancelOperation(Interlocked.Exchange(ref _catalogueOperation, null));
        IsExtensionCatalogBusy = false;
        IsNameIndexBusy = false;
        CatalogueStatus = string.Empty;
        ExtensionChoices.Clear();
        ExtensionChoices.Add(ArchiveExtensionChoice.AllFiles(
            LocalizationManager.Get("AllFiles"),
            LocalizationManager.Get("ExtensionGroupAll")));
    }

    private async Task LoadPreviewLatestAsync(ArchiveEntryDto? entry)
    {
        var sessionId = SessionId;
        var generation = Interlocked.Increment(ref _previewGeneration);
        using var operation = new CancellationTokenSource();
        var prior = Interlocked.Exchange(ref _previewOperation, operation);
        CancelOperation(prior);
        if (entry is null || string.IsNullOrWhiteSpace(sessionId))
        {
            ClearPreview();
            Interlocked.CompareExchange(ref _previewOperation, null, operation);
            return;
        }

        try
        {
            var isNativeModel = entry.Extension.Equals(".pac", StringComparison.OrdinalIgnoreCase)
                || entry.Extension.Equals(".pam", StringComparison.OrdinalIgnoreCase)
                || entry.Extension.Equals(".pamlod", StringComparison.OrdinalIgnoreCase);
            var milliseconds = isNativeModel ? 450 : 90;
            await Task.Delay(milliseconds, operation.Token).ConfigureAwait(true);
            if (generation != Volatile.Read(ref _previewGeneration))
            {
                return;
            }
            IsPreviewBusy = true;
            PreviewProgressText = LocalizationManager.Get("PreviewProgressPreparing");
            var progress = new Progress<ProgressUpdate>(update => ApplyPreviewProgress(generation, update));
            var result = await _worker.SendAsync<PreviewRequest, PreviewResult>(
                WorkerProtocol.Preview,
                generation,
                new PreviewRequest(sessionId, entry.EntryId),
                operation.Token,
                progress).ConfigureAwait(true);
            if (generation != Volatile.Read(ref _previewGeneration))
            {
                return;
            }

            await PresentPreviewAsync(result, generation, operation.Token).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            // A newer selection owns the preview lane.
        }
        catch (Exception exception)
        {
            if (generation == Volatile.Read(ref _previewGeneration))
            {
                ClearPreview();
                PreviewTitle = entry.Name;
                PreviewText = exception.Message;
            }
        }
        finally
        {
            if (generation == Volatile.Read(ref _previewGeneration))
            {
                IsPreviewBusy = false;
                PreviewProgressText = string.Empty;
            }
            Interlocked.CompareExchange(ref _previewOperation, null, operation);
        }
    }

    private void ApplyPreviewProgress(long generation, ProgressUpdate update)
    {
        if (generation != Volatile.Read(ref _previewGeneration))
        {
            return;
        }
        IsPreviewBusy = true;
        PreviewProgressText = update.Phase switch
        {
            "model_preview_native" => LocalizationManager.Get("PreviewProgressNative"),
            "model_preview_adapt" => LocalizationManager.Get("PreviewProgressAdapting"),
            _ => string.IsNullOrWhiteSpace(update.CurrentItem) ? update.Phase : update.CurrentItem,
        };
    }

    private async Task PresentPreviewAsync(PreviewResult result, long generation, CancellationToken cancellationToken)
    {
        BitmapSource? image = null;
        var warnings = result.Warnings?.ToList() ?? [];
        if (result.Kind == PreviewKind.Image && !string.IsNullOrWhiteSpace(result.ArtifactPath))
        {
            try
            {
                image = await PreviewImageLoader.LoadFrozenAsync(result.ArtifactPath, cancellationToken).ConfigureAwait(true);
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or NotSupportedException or InvalidDataException)
            {
                warnings.Add($"Image decoder: {exception.Message}");
            }
        }

        cancellationToken.ThrowIfCancellationRequested();
        if (generation != Volatile.Read(ref _previewGeneration))
        {
            return;
        }

        PreviewTitle = result.Title;
        PreviewMetadata = result.Metadata;
        PreviewText = string.IsNullOrWhiteSpace(result.Text) ? result.Metadata : result.Text;
        PreviewWarnings = string.Join(Environment.NewLine, warnings);
        PreviewImage = image;
        PreviewMediaSource = result.Kind is PreviewKind.Audio or PreviewKind.Video && !string.IsNullOrWhiteSpace(result.ArtifactPath)
            ? new Uri(result.ArtifactPath, UriKind.Absolute)
            : null;
        ModelPreviewPackagePath = result.Kind == PreviewKind.Model && !string.IsNullOrWhiteSpace(result.ArtifactPath)
            ? result.ArtifactPath
            : null;
        PreviewKind = result.Kind;
        OnPropertyChanged(nameof(IsImagePreview));
        OnPropertyChanged(nameof(IsMediaPreview));
        OnPropertyChanged(nameof(IsModelPreview));
        OnPropertyChanged(nameof(IsTextPreview));
    }

    private void ClearPreview()
    {
        PreviewTitle = LocalizationManager.Get("Preview");
        PreviewMetadata = string.Empty;
        PreviewText = LocalizationManager.Get("PreviewEmpty");
        PreviewWarnings = string.Empty;
        PreviewImage = null;
        PreviewMediaSource = null;
        ModelPreviewPackagePath = null;
        PreviewKind = PreviewKind.Metadata;
        IsPreviewBusy = false;
        PreviewProgressText = string.Empty;
        OnPropertyChanged(nameof(IsImagePreview));
        OnPropertyChanged(nameof(IsMediaPreview));
        OnPropertyChanged(nameof(IsModelPreview));
        OnPropertyChanged(nameof(IsTextPreview));
    }

    private void CancelPreviewAndClear()
    {
        Interlocked.Increment(ref _previewGeneration);
        var operation = Interlocked.Exchange(ref _previewOperation, null);
        CancelOperation(operation);
        ClearPreview();
    }

    private async Task ExportSelectedAsync(CancellationToken cancellationToken)
    {
        if (SelectedEntry is null || string.IsNullOrWhiteSpace(SessionId))
        {
            return;
        }

        var destination = PickExportFolder();
        if (destination is null)
        {
            return;
        }

        await RunExportAsync([SelectedEntry.EntryId], destination, ExportKind.RawEntries, cancellationToken).ConfigureAwait(true);
    }

    private async Task ExportMeshAsync(CancellationToken cancellationToken)
    {
        if (!CanExportSelectedMesh || SelectedEntry is null || string.IsNullOrWhiteSpace(SessionId))
        {
            return;
        }

        var baseName = Path.GetFileNameWithoutExtension(SelectedEntry.Name);
        var dialog = new SaveFileDialog
        {
            Title = LocalizationManager.Get("ExportMesh"),
            FileName = $"{baseName}.glb",
            DefaultExt = ".glb",
            AddExtension = true,
            OverwritePrompt = CollisionPolicy == ExportCollisionPolicy.Overwrite,
            Filter = LocalizationManager.Get("MeshExportFilter"),
            FilterIndex = 1,
        };
        if (dialog.ShowDialog() != true)
        {
            return;
        }

        var selection = dialog.FilterIndex switch
        {
            1 => (Kind: ExportKind.Glb, Extension: ".glb"),
            2 => (Kind: ExportKind.Obj, Extension: ".obj"),
            3 => (Kind: ExportKind.Fbx, Extension: ".fbx"),
            _ => ((ExportKind Kind, string Extension)?)null,
        };
        if (selection is null)
        {
            _setShellStatus(LocalizationManager.Get("MeshExportUnsupportedExtension"));
            return;
        }
        var outputPath = Path.ChangeExtension(dialog.FileName, selection.Value.Extension);
        var destination = Path.GetDirectoryName(outputPath);
        if (string.IsNullOrWhiteSpace(destination))
        {
            return;
        }

        await RunExportAsync(
            [SelectedEntry.EntryId],
            destination,
            selection.Value.Kind,
            cancellationToken,
            singleOutputPath: outputPath,
            manifestFormat: ExportManifestFormat.None).ConfigureAwait(true);
    }

    private async Task ExportFilteredAsync(CancellationToken cancellationToken)
    {
        var destination = PickExportFolder();
        if (destination is null)
        {
            return;
        }

        await RunExportAsync([], destination, ExportKind.FilteredEntries, cancellationToken).ConfigureAwait(true);
    }

    private async Task RunExportAsync(
        IReadOnlyList<long> entryIds,
        string destination,
        ExportKind kind,
        CancellationToken cancellationToken,
        string? singleOutputPath = null,
        ExportManifestFormat? manifestFormat = null)
    {
        if (string.IsNullOrWhiteSpace(SessionId))
        {
            return;
        }

        using var operation = BeginForegroundOperation(cancellationToken);
        var generation = Interlocked.Increment(ref _foregroundGeneration);
        try
        {
            SetOperationProgress(LocalizationManager.Get("ProgressExporting"));
            var progress = new Progress<ProgressUpdate>(update => ApplyForegroundProgress(generation, update));
            var result = await _worker.SendAsync<ExportPlanRequest, ExportPlanResult>(
                WorkerProtocol.Export,
                generation,
                new ExportPlanRequest(
                    SessionId,
                    kind,
                    destination,
                    entryIds,
                    null,
                    CollisionPolicy: CollisionPolicy,
                    ManifestFormat: manifestFormat ?? ManifestFormat,
                    SingleOutputPath: singleOutputPath),
                operation.Token,
                progress).ConfigureAwait(true);
            if (generation == Volatile.Read(ref _foregroundGeneration))
            {
                _setShellStatus(LocalizationManager.Format("ExportSummary", result.Exported, result.Skipped, result.Failed));
            }
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            _setShellStatus(exception.Message);
        }
        finally
        {
            EndForegroundOperation(operation);
        }
    }

    private static string? PickExportFolder()
    {
        var dialog = new OpenFolderDialog
        {
            Title = LocalizationManager.Get("ExportSelected"),
            Multiselect = false,
        };
        return dialog.ShowDialog() == true ? dialog.FolderName : null;
    }

    private CancellationTokenSource BeginForegroundOperation(CancellationToken commandToken)
    {
        var operation = CancellationTokenSource.CreateLinkedTokenSource(commandToken);
        var prior = Interlocked.Exchange(ref _foregroundOperation, operation);
        CancelOperation(prior);
        IsBusy = true;
        return operation;
    }

    private CancellationTokenSource BeginEnvironmentOperation(CancellationToken commandToken)
    {
        var operation = CancellationTokenSource.CreateLinkedTokenSource(commandToken);
        var prior = Interlocked.Exchange(ref _environmentOperation, operation);
        CancelOperation(prior);
        IsEnvironmentBusy = true;
        return operation;
    }

    private bool EnvironmentIsCurrent(long generation) =>
        generation == Volatile.Read(ref _environmentGeneration);

    private void EndEnvironmentOperation(CancellationTokenSource operation)
    {
        if (ReferenceEquals(Interlocked.CompareExchange(ref _environmentOperation, null, operation), operation))
        {
            IsEnvironmentBusy = false;
        }
    }

    private void CancelEnvironment()
    {
        Interlocked.Increment(ref _environmentGeneration);
        CancelOperation(Interlocked.Exchange(ref _environmentOperation, null));
        IsEnvironmentBusy = false;
    }

    private static bool PathsEqual(string? left, string? right)
    {
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
        {
            return string.IsNullOrWhiteSpace(left) && string.IsNullOrWhiteSpace(right);
        }
        try
        {
            return string.Equals(
                Path.GetFullPath(left.Trim()).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
                Path.GetFullPath(right.Trim()).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
                StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception exception) when (exception is ArgumentException or NotSupportedException)
        {
            return string.Equals(left.Trim(), right.Trim(), StringComparison.OrdinalIgnoreCase);
        }
    }

    private void ApplyForegroundProgress(long generation, ProgressUpdate update)
    {
        if (generation != Volatile.Read(ref _foregroundGeneration) || !IsBusy)
        {
            return;
        }

        var phase = update.Phase switch
        {
            "discover" => LocalizationManager.Get("ProgressDiscovering"),
            "fingerprint" => LocalizationManager.Get("ProgressFingerprinting"),
            "index_cache" => LocalizationManager.Get("ProgressOpeningIndex"),
            "index_build" => LocalizationManager.Get("ProgressBuildingIndex"),
            "validate" => LocalizationManager.Get("ProgressValidating"),
            "export" => LocalizationManager.Get("ProgressExporting"),
            "mesh_export_prepare" => LocalizationManager.Get("ProgressPreparingMesh"),
            "mesh_export_write" => LocalizationManager.Get("ProgressWritingMesh"),
            "complete" => LocalizationManager.Get("ProgressFinishing"),
            _ => LocalizationManager.Get("ProgressWorking"),
        };
        OperationProgressText = string.IsNullOrWhiteSpace(update.CurrentItem) || update.CurrentItem == "complete"
            ? phase
            : $"{phase}  ·  {update.CurrentItem}";
        IsOperationProgressIndeterminate = update.Total <= 0;
        OperationProgressPercent = update.Total <= 0
            ? 0
            : Math.Clamp(update.Completed * 100.0 / update.Total, 0, 100);
    }

    private void SetOperationProgress(string text)
    {
        OperationProgressText = text;
        OperationProgressPercent = 0;
        IsOperationProgressIndeterminate = true;
    }

    private void EndForegroundOperation(CancellationTokenSource operation)
    {
        if (ReferenceEquals(Interlocked.CompareExchange(ref _foregroundOperation, null, operation), operation))
        {
            IsBusy = false;
        }
    }

    private void CancelForeground()
    {
        Interlocked.Increment(ref _foregroundGeneration);
        CancelOperation(Interlocked.Exchange(ref _foregroundOperation, null));
        IsBusy = false;
    }

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
            // Completion may dispose a latest-wins operation immediately after ownership is exchanged.
        }
    }

    private void RaiseCommandStates()
    {
        BrowseCommand.RaiseCanExecuteChanged();
        DetectGameCommand.RaiseCanExecuteChanged();
        OpenCommand.RaiseCanExecuteChanged();
        RefreshCommand.RaiseCanExecuteChanged();
        ApplyFilterCommand.RaiseCanExecuteChanged();
        PreviousPageCommand.RaiseCanExecuteChanged();
        NextPageCommand.RaiseCanExecuteChanged();
        CancelCommand.RaiseCanExecuteChanged();
        ExportSelectedCommand.RaiseCanExecuteChanged();
        ExportMeshCommand.RaiseCanExecuteChanged();
        ExportFilteredCommand.RaiseCanExecuteChanged();
        AssociatedAssets.RaiseCommandStates();
    }
}

public sealed record ArchiveRoleFilter(ArchiveEntryRole? Role, string Label)
{
    public override string ToString() => Label;
}

public sealed record ArchiveCategoryCount(string Name, string Label, long Count)
{
    public override string ToString() => $"{Label} ({Count:N0})";
}

public sealed record ArchiveFolderFilter(string? Path, string Label)
{
    public override string ToString() => Label;
}

public sealed record ArchiveExtensionChoice(
    string Extension,
    long Count,
    string Group,
    ArchiveExtensionCategory? Category = null,
    string? DisplayLabel = null)
{
    public string Label => DisplayLabel ?? Extension;

    public static ArchiveExtensionChoice AllFiles(string label, string group) => new(string.Empty, 0, group, null, label);

    public override string ToString() => Extension;
}
