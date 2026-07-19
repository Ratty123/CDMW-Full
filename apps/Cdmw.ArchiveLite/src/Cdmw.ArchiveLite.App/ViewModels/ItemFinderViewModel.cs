using System.Collections.ObjectModel;
using System.Windows.Media.Imaging;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.ViewModels;

public sealed class ItemFinderViewModel : ObservableObject
{
    private const int PageSize = 72;
    private const int IconBatchSize = 24;
    private const int ThumbnailSize = 120;
    private const int MaximumMemoryIcons = 96;
    private readonly WorkerProcessHost _worker;
    private readonly Func<string?> _getSessionId;
    private readonly Action<string> _setShellStatus;
    private readonly Func<int, string, bool, CancellationToken, Task<bool>> _showItemScope;
    private readonly Dictionary<string, CachedBitmap> _bitmapCache = new(StringComparer.Ordinal);
    private readonly LinkedList<string> _bitmapLru = new();
    private CancellationTokenSource? _activation;
    private CancellationTokenSource? _searchOperation;
    private CancellationTokenSource? _warmupOperation;
    private Task? _pageIconTask;
    private Task? _warmupTask;
    private long _generation;
    private long _warmupGeneration;
    private string? _sessionId;
    private string? _warmupSessionId;
    private string _warmupSummary = string.Empty;
    private string _query = string.Empty;
    private ItemFinderCategoryOption? _selectedCategory;
    private ItemFinderValueOption? _selectedMaterialTag;
    private ItemFinderRowViewModel? _selectedItem;
    private string _status = LocalizationManager.Get("ItemFinderOpenArchive");
    private string _iconWarmupStatus = string.Empty;
    private bool _isBusy;
    private bool _isActive;
    private int _pageStart;
    private long _totalMatches;
    private string? _preferredCategory;
    private string? _preferredGroup;
    private string? _preferredMaterialTag;

    public ItemFinderViewModel(
        WorkerProcessHost worker,
        Func<string?> getSessionId,
        Action<string> setShellStatus,
        Func<int, string, bool, CancellationToken, Task<bool>> showItemScope,
        ItemFinderSettings? initialSettings = null)
    {
        _worker = worker;
        _getSessionId = getSessionId;
        _setShellStatus = setShellStatus;
        _showItemScope = showItemScope;
        var settings = initialSettings ?? new ItemFinderSettings();
        _query = settings.Query ?? string.Empty;
        _preferredCategory = settings.Category;
        _preferredGroup = settings.Group;
        _preferredMaterialTag = settings.MaterialTag;
        WindowWidth = NormalizeWindowDimension(settings.Width, 1240, 940, 2400);
        WindowHeight = NormalizeWindowDimension(settings.Height, 800, 640, 1600);
        SearchCommand = new AsyncCommand(token => SearchLatestAsync(resetPage: true, token), () => IsAvailable);
        PreviousPageCommand = new AsyncCommand(token => MovePageAsync(-PageSize, token), () => IsAvailable && PageStart > 0);
        NextPageCommand = new AsyncCommand(token => MovePageAsync(PageSize, token), () => IsAvailable && PageStart + PageSize < TotalMatches);
        ClearCommand = new RelayCommand(ClearFilters, () => IsAvailable);
        ShowExactLinksCommand = new AsyncCommand(token => ShowScopeAsync(includeRelated: false, token), () => SelectedItem is not null && !IsBusy);
        ShowRelatedSetCommand = new AsyncCommand(token => ShowScopeAsync(includeRelated: true, token), () => SelectedItem is not null && !IsBusy);
        CategoryOptions.Add(ItemFinderCategoryOption.All());
        MaterialTagOptions.Add(ItemFinderValueOption.All());
        _selectedCategory = CategoryOptions[0];
        _selectedMaterialTag = MaterialTagOptions[0];
    }

    public ObservableCollection<ItemFinderRowViewModel> Items { get; } = [];
    public ObservableCollection<ItemFinderCategoryOption> CategoryOptions { get; } = [];
    public ObservableCollection<ItemFinderValueOption> MaterialTagOptions { get; } = [];
    public AsyncCommand SearchCommand { get; }
    public AsyncCommand PreviousPageCommand { get; }
    public AsyncCommand NextPageCommand { get; }
    public RelayCommand ClearCommand { get; }
    public AsyncCommand ShowExactLinksCommand { get; }
    public AsyncCommand ShowRelatedSetCommand { get; }
    public event EventHandler? CloseRequested;

    public string Query
    {
        get => _query;
        set => SetProperty(ref _query, value ?? string.Empty);
    }

    public ItemFinderCategoryOption? SelectedCategory
    {
        get => _selectedCategory;
        set => SetProperty(ref _selectedCategory, value);
    }

    public ItemFinderValueOption? SelectedMaterialTag
    {
        get => _selectedMaterialTag;
        set => SetProperty(ref _selectedMaterialTag, value);
    }

    public ItemFinderRowViewModel? SelectedItem
    {
        get => _selectedItem;
        set
        {
            if (SetProperty(ref _selectedItem, value))
            {
                ShowExactLinksCommand.RaiseCanExecuteChanged();
                ShowRelatedSetCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string Status
    {
        get => _status;
        private set => SetProperty(ref _status, value);
    }

    public string IconWarmupStatus
    {
        get => _iconWarmupStatus;
        private set => SetProperty(ref _iconWarmupStatus, value);
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

    public bool IsAvailable => !string.IsNullOrWhiteSpace(_sessionId);
    public double WindowWidth { get; private set; }
    public double WindowHeight { get; private set; }
    public int PageStart => _pageStart;
    public long TotalMatches => _totalMatches;
    public string PageSummary => TotalMatches == 0
        ? LocalizationManager.Get("ItemFinderNoMatches")
        : LocalizationManager.Format(
            "ItemFinderPageSummary",
            PageStart + 1,
            Math.Min(TotalMatches, PageStart + PageSize),
            TotalMatches);

    public async Task ActivateAsync(CancellationToken cancellationToken)
    {
        if (_isActive)
        {
            return;
        }
        _isActive = true;
        _activation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _sessionId = _getSessionId();
        RaiseAvailability();
        if (!IsAvailable)
        {
            Status = LocalizationManager.Get("ItemFinderOpenArchive");
            return;
        }
        await SearchLatestAsync(resetPage: true, _activation.Token).ConfigureAwait(true);
    }

    public async Task RefreshAsync(CancellationToken cancellationToken) =>
        await SearchLatestAsync(resetPage: true, cancellationToken).ConfigureAwait(true);

    public void Deactivate()
    {
        _isActive = false;
        CancelDialogOperations();
        IconWarmupStatus = string.Empty;
    }

    public void NotifyArchiveSessionChanged()
    {
        Interlocked.Increment(ref _generation);
        CancelDialogOperations();
        CancelWarmup();
        _sessionId = _getSessionId();
        _warmupSessionId = null;
        _warmupSummary = string.Empty;
        Items.Clear();
        SelectedItem = null;
        _pageStart = 0;
        _totalMatches = 0;
        ClearBitmapCache();
        Status = IsAvailable
            ? LocalizationManager.Get("ItemFinderReady")
            : LocalizationManager.Get("ItemFinderOpenArchive");
        IconWarmupStatus = string.Empty;
        OnPropertyChanged(nameof(PageStart));
        OnPropertyChanged(nameof(TotalMatches));
        OnPropertyChanged(nameof(PageSummary));
        RaiseAvailability();
    }

    public void RequestShutdown()
    {
        _isActive = false;
        CancelDialogOperations();
        CancelWarmup();
        ClearBitmapCache();
    }

    public void NotifyCatalogReady(string sessionId)
    {
        if (string.Equals(_sessionId, sessionId, StringComparison.Ordinal))
        {
            StartWarmup(sessionId, []);
        }
    }

    public void RefreshLocalization()
    {
        var selectedCategoryKey = SelectedCategory?.Key;
        var selectedMaterial = SelectedMaterialTag?.Value;
        if (CategoryOptions.Count > 0)
        {
            CategoryOptions[0] = ItemFinderCategoryOption.All();
            SelectedCategory = CategoryOptions.FirstOrDefault(option => option.Key == selectedCategoryKey) ?? CategoryOptions[0];
        }
        if (MaterialTagOptions.Count > 0)
        {
            MaterialTagOptions[0] = ItemFinderValueOption.All();
            SelectedMaterialTag = MaterialTagOptions.FirstOrDefault(option => option.Value == selectedMaterial) ?? MaterialTagOptions[0];
        }
        OnPropertyChanged(nameof(PageSummary));
    }

    public ItemFinderSettings CaptureSettings() => new(
        Query,
        SelectedCategory?.Category ?? _preferredCategory,
        SelectedCategory?.Group ?? _preferredGroup,
        SelectedMaterialTag?.Value ?? _preferredMaterialTag,
        WindowWidth,
        WindowHeight);

    public void UpdateWindowSize(double width, double height)
    {
        WindowWidth = NormalizeWindowDimension(width, 1240, 940, 2400);
        WindowHeight = NormalizeWindowDimension(height, 800, 640, 1600);
    }

    private async Task SearchLatestAsync(bool resetPage, CancellationToken commandToken)
    {
        var sessionId = _sessionId;
        if (!_isActive || string.IsNullOrWhiteSpace(sessionId))
        {
            Status = LocalizationManager.Get("ItemFinderOpenArchive");
            return;
        }
        if (resetPage)
        {
            _pageStart = 0;
        }

        _searchOperation?.Cancel();
        _searchOperation?.Dispose();
        _searchOperation = CancellationTokenSource.CreateLinkedTokenSource(commandToken, _activation?.Token ?? CancellationToken.None);
        var cancellationToken = _searchOperation.Token;
        var generation = Interlocked.Increment(ref _generation);
        IsBusy = true;
        Status = LocalizationManager.Get("ItemFinderLoading");
        RaiseCommandStates();
        try
        {
            var categoryName = _preferredCategory ?? SelectedCategory?.Category;
            var groupName = _preferredGroup ?? SelectedCategory?.Group;
            var materialTag = _preferredMaterialTag ?? SelectedMaterialTag?.Value;
            var result = await _worker.SendAsync<ItemCatalogSearchRequest, ItemCatalogSearchResult>(
                WorkerProtocol.SearchItemCatalog,
                generation,
                new ItemCatalogSearchRequest(
                    sessionId,
                    Query,
                    categoryName,
                    groupName,
                    materialTag,
                    _pageStart,
                    PageSize),
                cancellationToken).ConfigureAwait(true);
            if (!IsCurrent(sessionId, generation))
            {
                return;
            }

            ApplyFacets(result);
            Items.Clear();
            foreach (var row in result.Items)
            {
                var viewModel = new ItemFinderRowViewModel(row);
                if (TryGetBitmap(sessionId, row.ItemId, out var cached))
                {
                    viewModel.Icon = cached;
                }
                Items.Add(viewModel);
            }
            SelectedItem = Items.FirstOrDefault();
            _pageStart = result.PageStart;
            _totalMatches = result.TotalMatches;
            OnPropertyChanged(nameof(PageStart));
            OnPropertyChanged(nameof(TotalMatches));
            OnPropertyChanged(nameof(PageSummary));
            Status = result.Warning ?? PageSummary;
            if (Items.Count > 0)
            {
                await LoadIconsAsync(Items.Take(IconBatchSize).ToArray(), sessionId, generation, cancellationToken).ConfigureAwait(true);
                if (IsCurrent(sessionId, generation))
                {
                    _pageIconTask = LoadRemainingIconsAsync(
                        Items.Skip(IconBatchSize).ToArray(),
                        sessionId,
                        generation,
                        cancellationToken);
                }
            }
            StartWarmup(sessionId, Items.Select(static item => item.ItemId).ToArray());
        }
        catch (OperationCanceledException)
        {
            // A newer filter, archive session, dialog close, or shutdown owns the UI.
        }
        catch (Exception exception)
        {
            if (IsCurrent(sessionId, generation))
            {
                Status = LocalizationManager.Format("ItemFinderFailed", exception.Message);
                _setShellStatus(Status);
            }
        }
        finally
        {
            if (IsCurrent(sessionId, generation))
            {
                IsBusy = false;
                RaiseCommandStates();
            }
        }
    }

    private async Task MovePageAsync(int delta, CancellationToken cancellationToken)
    {
        _pageStart = Math.Max(0, _pageStart + delta);
        await SearchLatestAsync(resetPage: false, cancellationToken).ConfigureAwait(true);
    }

    private void ApplyFacets(ItemCatalogSearchResult result)
    {
        var categoryKey = !string.IsNullOrWhiteSpace(_preferredCategory)
            ? ItemFinderCategoryOption.BuildKey(_preferredCategory, _preferredGroup)
            : SelectedCategory?.Key;
        var materialValue = _preferredMaterialTag ?? SelectedMaterialTag?.Value;
        CategoryOptions.Clear();
        CategoryOptions.Add(ItemFinderCategoryOption.All());
        foreach (var facet in result.Categories)
        {
            CategoryOptions.Add(new ItemFinderCategoryOption(
                facet.Category,
                facet.Group,
                $"{facet.Category} / {facet.Group} ({facet.Count:N0})"));
        }
        SelectedCategory = CategoryOptions.FirstOrDefault(option => option.Key == categoryKey) ?? CategoryOptions[0];

        MaterialTagOptions.Clear();
        MaterialTagOptions.Add(ItemFinderValueOption.All());
        foreach (var facet in result.MaterialTags.Take(250))
        {
            MaterialTagOptions.Add(new ItemFinderValueOption(facet.Value, $"{facet.Value} ({facet.Count:N0})"));
        }
        SelectedMaterialTag = MaterialTagOptions.FirstOrDefault(option => option.Value == materialValue) ?? MaterialTagOptions[0];
        _preferredCategory = null;
        _preferredGroup = null;
        _preferredMaterialTag = null;
    }

    private async Task LoadRemainingIconsAsync(
        IReadOnlyList<ItemFinderRowViewModel> rows,
        string sessionId,
        long generation,
        CancellationToken cancellationToken)
    {
        try
        {
            for (var offset = 0; offset < rows.Count; offset += IconBatchSize)
            {
                cancellationToken.ThrowIfCancellationRequested();
                await LoadIconsAsync(
                    rows.Skip(offset).Take(IconBatchSize).ToArray(),
                    sessionId,
                    generation,
                    cancellationToken).ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            // A newer page or dialog close owns row icons.
        }
        catch (Exception exception)
        {
            if (IsCurrent(sessionId, generation))
            {
                IconWarmupStatus = LocalizationManager.Format("ItemFinderIconFailed", exception.Message);
            }
        }
    }

    private async Task LoadIconsAsync(
        IReadOnlyList<ItemFinderRowViewModel> rows,
        string sessionId,
        long generation,
        CancellationToken cancellationToken)
    {
        var pending = rows.Where(static row => row.Icon is null && row.IconPaths.Count > 0).ToArray();
        if (pending.Length == 0)
        {
            return;
        }
        var result = await _worker.SendAsync<ItemIconBatchRequest, ItemIconBatchResult>(
            WorkerProtocol.LoadItemIcons,
            generation,
            new ItemIconBatchRequest(sessionId, pending.Select(static row => row.ItemId).ToArray(), ThumbnailSize),
            cancellationToken).ConfigureAwait(true);
        if (!IsCurrent(sessionId, generation))
        {
            return;
        }
        var rowsById = pending.ToDictionary(static row => row.ItemId);
        foreach (var icon in result.Items)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (string.IsNullOrWhiteSpace(icon.PngPath) || !rowsById.TryGetValue(icon.ItemId, out var row))
            {
                continue;
            }
            var bitmap = await PreviewImageLoader.LoadFrozenAsync(icon.PngPath, cancellationToken).ConfigureAwait(true);
            if (!IsCurrent(sessionId, generation))
            {
                return;
            }
            row.Icon = bitmap;
            StoreBitmap(sessionId, icon.ItemId, bitmap);
        }
    }

    private void StartWarmup(string sessionId, IReadOnlyList<int> prioritizedItemIds)
    {
        if (string.Equals(_warmupSessionId, sessionId, StringComparison.Ordinal))
        {
            if (_isActive && !string.IsNullOrWhiteSpace(_warmupSummary))
            {
                IconWarmupStatus = _warmupSummary;
            }
            return;
        }
        _warmupOperation?.Cancel();
        _warmupOperation?.Dispose();
        _warmupOperation = new CancellationTokenSource();
        _warmupSessionId = sessionId;
        _warmupSummary = LocalizationManager.Get("ItemFinderIconWarmupStarting");
        if (_isActive)
        {
            IconWarmupStatus = _warmupSummary;
        }
        var progress = new Progress<ProgressUpdate>(update =>
        {
            if (_isActive && string.Equals(_sessionId, sessionId, StringComparison.Ordinal))
            {
                IconWarmupStatus = update.Total > 0
                    ? LocalizationManager.Format("ItemFinderIconWarmup", update.Completed, update.Total)
                    : LocalizationManager.Get("ItemFinderIconWarmupStarting");
                _warmupSummary = IconWarmupStatus;
            }
        });
        _warmupTask = WarmIconsAsync(sessionId, prioritizedItemIds, _warmupOperation.Token, progress);
    }

    private async Task WarmIconsAsync(
        string sessionId,
        IReadOnlyList<int> prioritizedItemIds,
        CancellationToken cancellationToken,
        IProgress<ProgressUpdate> progress)
    {
        try
        {
            var result = await _worker.SendAsync<WarmItemIconsRequest, WarmItemIconsResult>(
                WorkerProtocol.WarmItemIcons,
                Interlocked.Increment(ref _warmupGeneration),
                new WarmItemIconsRequest(sessionId, prioritizedItemIds, MaximumIcons: 0, ThumbnailSize),
                cancellationToken,
                progress).ConfigureAwait(true);
            if (_isActive && string.Equals(_sessionId, sessionId, StringComparison.Ordinal))
            {
                IconWarmupStatus = LocalizationManager.Format("ItemFinderIconWarmupReady", result.Ready, result.Considered);
            }
            _warmupSummary = LocalizationManager.Format("ItemFinderIconWarmupReady", result.Ready, result.Considered);
        }
        catch (OperationCanceledException)
        {
            // Dialog/session lifecycle owns background preload cancellation.
        }
        catch (Exception exception)
        {
            if (_isActive && string.Equals(_sessionId, sessionId, StringComparison.Ordinal))
            {
                IconWarmupStatus = LocalizationManager.Format("ItemFinderIconFailed", exception.Message);
            }
            _warmupSummary = LocalizationManager.Format("ItemFinderIconFailed", exception.Message);
            _warmupSessionId = null;
        }
    }

    private bool IsCurrent(string sessionId, long generation) =>
        _isActive
        && generation == Volatile.Read(ref _generation)
        && string.Equals(_sessionId, sessionId, StringComparison.Ordinal);

    private void ClearFilters()
    {
        Query = string.Empty;
        SelectedCategory = CategoryOptions.FirstOrDefault();
        SelectedMaterialTag = MaterialTagOptions.FirstOrDefault();
        SearchCommand.Execute(null);
    }

    private async Task ShowScopeAsync(bool includeRelated, CancellationToken cancellationToken)
    {
        var selected = SelectedItem;
        if (selected is null)
        {
            return;
        }
        IsBusy = true;
        Status = LocalizationManager.Get("ItemFinderScopeLoading");
        RaiseCommandStates();
        try
        {
            if (await _showItemScope(
                    selected.ItemId,
                    selected.DisplayName,
                    includeRelated,
                    cancellationToken).ConfigureAwait(true))
            {
                CloseRequested?.Invoke(this, EventArgs.Empty);
            }
        }
        finally
        {
            IsBusy = false;
            RaiseCommandStates();
        }
    }

    private void RaiseAvailability()
    {
        OnPropertyChanged(nameof(IsAvailable));
        RaiseCommandStates();
    }

    private void RaiseCommandStates()
    {
        SearchCommand.RaiseCanExecuteChanged();
        PreviousPageCommand.RaiseCanExecuteChanged();
        NextPageCommand.RaiseCanExecuteChanged();
        ClearCommand.RaiseCanExecuteChanged();
        ShowExactLinksCommand.RaiseCanExecuteChanged();
        ShowRelatedSetCommand.RaiseCanExecuteChanged();
    }

    private string BitmapKey(string sessionId, int itemId) => $"{sessionId}:{itemId}:{ThumbnailSize}";

    private bool TryGetBitmap(string sessionId, int itemId, out BitmapSource? bitmap)
    {
        var key = BitmapKey(sessionId, itemId);
        if (!_bitmapCache.TryGetValue(key, out var cached))
        {
            bitmap = null;
            return false;
        }
        _bitmapLru.Remove(cached.Node);
        _bitmapLru.AddFirst(cached.Node);
        bitmap = cached.Bitmap;
        return true;
    }

    private void StoreBitmap(string sessionId, int itemId, BitmapSource bitmap)
    {
        var key = BitmapKey(sessionId, itemId);
        if (_bitmapCache.Remove(key, out var existing))
        {
            _bitmapLru.Remove(existing.Node);
        }
        var node = _bitmapLru.AddFirst(key);
        _bitmapCache[key] = new CachedBitmap(bitmap, node);
        while (_bitmapCache.Count > MaximumMemoryIcons && _bitmapLru.Last is { } last)
        {
            _bitmapLru.RemoveLast();
            _bitmapCache.Remove(last.Value);
        }
    }

    private void ClearBitmapCache()
    {
        _bitmapCache.Clear();
        _bitmapLru.Clear();
    }

    private void CancelDialogOperations()
    {
        SearchCommand.Cancel();
        PreviousPageCommand.Cancel();
        NextPageCommand.Cancel();
        ShowExactLinksCommand.Cancel();
        ShowRelatedSetCommand.Cancel();
        _searchOperation?.Cancel();
        _activation?.Cancel();
        _searchOperation?.Dispose();
        _activation?.Dispose();
        _searchOperation = null;
        _activation = null;
        _pageIconTask = null;
    }

    private void CancelWarmup()
    {
        _warmupOperation?.Cancel();
        _warmupOperation?.Dispose();
        _warmupOperation = null;
        _warmupTask = null;
    }

    private static double NormalizeWindowDimension(double value, double fallback, double minimum, double maximum) =>
        double.IsFinite(value) ? Math.Clamp(value, minimum, maximum) : fallback;

    private sealed record CachedBitmap(BitmapSource Bitmap, LinkedListNode<string> Node);
}

public sealed class ItemFinderRowViewModel(ItemCatalogRow source) : ObservableObject
{
    private BitmapSource? _icon;

    public int ItemId => source.ItemId;
    public string InternalName => source.InternalName;
    public string DisplayName => source.DisplayName;
    public string Category => source.Category;
    public string Group => source.Group;
    public string CategoryPath => $"{Category} / {Group}";
    public string CategoryEvidence => source.CategoryEvidence;
    public IReadOnlyList<string> PacFiles => source.PacFiles;
    public IReadOnlyList<string> ModelStems => source.ModelStems;
    public IReadOnlyList<string> IconPaths => source.IconPaths;
    public IReadOnlyList<string> LocalizedNames => source.LocalizedNames;
    public IReadOnlyList<string> MaterialTags => source.MaterialTags;
    public int VariantCount => source.VariantCount;
    public string Evidence => source.Evidence;
    public string FallbackText => string.IsNullOrWhiteSpace(DisplayName) ? "?" : DisplayName[..1].ToUpperInvariant();
    public string LinkedSummary => LocalizationManager.Format("ItemFinderLinkedSummary", PacFiles.Count, IconPaths.Count, VariantCount);
    public string LocalizedNamesText => LocalizedNames.Count > 0 ? string.Join(", ", LocalizedNames) : LocalizationManager.Get("None");
    public string MaterialTagsText => MaterialTags.Count > 0 ? string.Join(", ", MaterialTags) : LocalizationManager.Get("None");
    public string ModelFilesText => PacFiles.Count > 0 ? string.Join(Environment.NewLine, PacFiles) : LocalizationManager.Get("None");
    public string IconPathsText => IconPaths.Count > 0 ? string.Join(Environment.NewLine, IconPaths) : LocalizationManager.Get("None");

    public BitmapSource? Icon
    {
        get => _icon;
        set => SetProperty(ref _icon, value);
    }
}

public sealed record ItemFinderCategoryOption(string? Category, string? Group, string Label)
{
    public string Key => BuildKey(Category, Group);
    public static string BuildKey(string? category, string? group) => $"{category}\u001f{group}";
    public static ItemFinderCategoryOption All() => new(null, null, LocalizationManager.Get("ItemFinderAllCategories"));
    public override string ToString() => Label;
}

public sealed record ItemFinderValueOption(string? Value, string Label)
{
    public static ItemFinderValueOption All() => new(null, LocalizationManager.Get("ItemFinderAllMaterials"));
    public override string ToString() => Label;
}
