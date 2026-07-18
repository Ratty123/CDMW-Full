using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.App.ViewModels;
using Cdmw.ArchiveLite.Contracts;
using ICSharpCode.AvalonEdit;

namespace Cdmw.ArchiveLite.App;

public partial class MainWindow : Window
{
    private readonly MainWindowViewModel _viewModel;
    private bool _shutdownStarted;
    private bool _shutdownComplete;
    private bool _applyingArchiveColumnLayout;
    private WindowState _lastNonMinimizedWindowState = WindowState.Normal;

    private static readonly HashSet<string> DefaultArchiveColumns = new(StringComparer.Ordinal)
    {
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Name),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.KnownName),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.NameEvidence),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Extension),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Path),
    };

    private static readonly HashSet<string> LegacyDefaultArchiveColumns = new(StringComparer.Ordinal)
    {
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Name),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.KnownName),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.NameEvidence),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Extension),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Role),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.OriginalSize),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Package),
        nameof(Cdmw.ArchiveLite.Contracts.ArchiveSortField.Path),
    };

    public MainWindow(MainWindowViewModel viewModel)
    {
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        InitializeComponent();
        DataContext = viewModel;
        WorkspaceTabs.SelectedIndex = 0;
        Closing += OnClosing;
        Closed += OnClosed;
        Loaded += OnLoaded;
        SourceInitialized += OnSourceInitialized;
        StateChanged += OnWindowStateChanged;
        ThemeManager.ThemeChanged += OnThemeChanged;
        _viewModel.ArchiveBrowser.PropertyChanged += OnArchiveBrowserPropertyChanged;
        ApplyWindowPlacement();
    }

    private void OnSourceInitialized(object? sender, EventArgs eventArgs) => ApplyTitleBarTheme();

    private void OnThemeChanged(object? sender, EventArgs eventArgs)
    {
        if (Dispatcher.CheckAccess())
        {
            ApplyThemePresentation();
        }
        else
        {
            _ = Dispatcher.BeginInvoke(ApplyThemePresentation);
        }
    }

    private void ApplyThemePresentation()
    {
        ApplyTitleBarTheme();
        AvalonEditBinding.RefreshSyntax(ArchiveTextPreviewEditor);
        AvalonEditBinding.RefreshSyntax(TextSearchPreviewEditor);
    }

    private void ApplyTitleBarTheme()
    {
        var handle = new WindowInteropHelper(this).Handle;
        if (handle == IntPtr.Zero)
        {
            return;
        }

        var dark = ThemeManager.Current.IsDark ? 1 : 0;
        if (DwmSetWindowAttribute(handle, 20, ref dark, sizeof(int)) != 0)
        {
            _ = DwmSetWindowAttribute(handle, 19, ref dark, sizeof(int));
        }

        const int roundedCornerPreference = 2;
        var corners = roundedCornerPreference;
        _ = DwmSetWindowAttribute(handle, 33, ref corners, sizeof(int));
    }

    private void OnTitleBarMouseLeftButtonDown(object sender, MouseButtonEventArgs eventArgs)
    {
        if (eventArgs.ClickCount == 2)
        {
            ToggleMaximizedState();
            return;
        }

        if (eventArgs.ButtonState == MouseButtonState.Pressed)
        {
            DragMove();
        }
    }

    private void OnMinimizeClick(object sender, RoutedEventArgs eventArgs) =>
        WindowState = WindowState.Minimized;

    private void OnMaximizeRestoreClick(object sender, RoutedEventArgs eventArgs) =>
        ToggleMaximizedState();

    private void OnCloseClick(object sender, RoutedEventArgs eventArgs) => Close();

    private void OnWorkspaceNavigationClick(object sender, RoutedEventArgs eventArgs)
    {
        if (sender is System.Windows.Controls.Primitives.ToggleButton { Tag: string rawIndex }
            && int.TryParse(rawIndex, out var index)
            && index >= 0
            && index < WorkspaceTabs.Items.Count)
        {
            WorkspaceTabs.SelectedIndex = index;
        }
        UpdateWorkspaceNavigationState();
    }

    private void OnWorkspaceTabSelectionChanged(object sender, SelectionChangedEventArgs eventArgs) =>
        UpdateWorkspaceNavigationState();

    private void UpdateWorkspaceNavigationState()
    {
        if (ArchiveBrowserNavigationButton is null || TextSearchNavigationButton is null || WorkspaceTabs is null)
        {
            return;
        }
        ArchiveBrowserNavigationButton.IsChecked = WorkspaceTabs.SelectedIndex == 0;
        TextSearchNavigationButton.IsChecked = WorkspaceTabs.SelectedIndex == 1;
    }

    private void ToggleMaximizedState() =>
        WindowState = WindowState == WindowState.Maximized
            ? WindowState.Normal
            : WindowState.Maximized;

    private void OnClosed(object? sender, EventArgs eventArgs)
    {
        StateChanged -= OnWindowStateChanged;
        ThemeManager.ThemeChanged -= OnThemeChanged;
        _viewModel.ArchiveBrowser.PropertyChanged -= OnArchiveBrowserPropertyChanged;
    }

    private void OnLoaded(object sender, RoutedEventArgs eventArgs)
    {
        WorkspaceTabs.SelectedIndex = 0;
        ArchiveColumnChooser.ItemsSource = ArchiveGrid.Columns;
        ApplyArchiveColumnLayout();
        ApplyGridColumnLayout(ArchiveGrid, _viewModel.ArchiveColumnLayout);
        ApplyGridColumnLayout(TextSearchResultsGrid, _viewModel.TextSearchColumnLayout);
        ApplyWorkspaceLayout();
        UpdateArchiveSortIndicators();
        UpdateWorkspaceNavigationState();
    }

    private void OnArchiveGridSelectionChanged(object sender, SelectionChangedEventArgs eventArgs) =>
        _viewModel.ArchiveBrowser.SetSelectedEntries(ArchiveGrid.SelectedItems.OfType<ArchiveEntryDto>());

    private void OnAssociatedAssetsSelectionChanged(object sender, SelectionChangedEventArgs eventArgs) =>
        _viewModel.ArchiveBrowser.AssociatedAssets.SetSelectedAssets(
            AssociatedAssetsList.SelectedItems.OfType<AssociatedAssetRow>());

    private void OnArchivePreviewFindNextClick(object sender, RoutedEventArgs eventArgs) =>
        FindInEditor(ArchiveTextPreviewEditor, ArchivePreviewFindBox.Text, findPrevious: false);

    private void OnArchivePreviewFindPreviousClick(object sender, RoutedEventArgs eventArgs) =>
        FindInEditor(ArchiveTextPreviewEditor, ArchivePreviewFindBox.Text, findPrevious: true);

    private void OnTextSearchPreviewFindNextClick(object sender, RoutedEventArgs eventArgs) =>
        FindInEditor(TextSearchPreviewEditor, TextSearchPreviewFindBox.Text, findPrevious: false);

    private void OnTextSearchPreviewFindPreviousClick(object sender, RoutedEventArgs eventArgs) =>
        FindInEditor(TextSearchPreviewEditor, TextSearchPreviewFindBox.Text, findPrevious: true);

    private void OnMediaPlayClick(object sender, RoutedEventArgs eventArgs) => ArchiveMediaPreview.Play();

    private void OnMediaPauseClick(object sender, RoutedEventArgs eventArgs) => ArchiveMediaPreview.Pause();

    private void OnMediaStopClick(object sender, RoutedEventArgs eventArgs) => ArchiveMediaPreview.Stop();

    private void OnArchivePreviewFindKeyDown(object sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.Key == Key.Enter)
        {
            FindInEditor(ArchiveTextPreviewEditor, ArchivePreviewFindBox.Text, Keyboard.Modifiers.HasFlag(ModifierKeys.Shift));
            eventArgs.Handled = true;
        }
    }

    private void OnTextSearchPreviewFindKeyDown(object sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.Key == Key.Enter)
        {
            FindInEditor(TextSearchPreviewEditor, TextSearchPreviewFindBox.Text, Keyboard.Modifiers.HasFlag(ModifierKeys.Shift));
            eventArgs.Handled = true;
        }
    }

    private static void FindInEditor(TextEditor editor, string query, bool findPrevious)
    {
        if (string.IsNullOrEmpty(query) || editor.Document.TextLength == 0)
        {
            return;
        }

        var text = editor.Text;
        int match;
        if (findPrevious)
        {
            var start = editor.SelectionStart > 0
                ? Math.Min(text.Length - 1, editor.SelectionStart - 1)
                : text.Length - 1;
            match = text.LastIndexOf(query, start, StringComparison.OrdinalIgnoreCase);
            if (match < 0)
            {
                match = text.LastIndexOf(query, StringComparison.OrdinalIgnoreCase);
            }
        }
        else
        {
            var start = Math.Min(text.Length, editor.SelectionStart + editor.SelectionLength);
            match = text.IndexOf(query, start, StringComparison.OrdinalIgnoreCase);
            if (match < 0)
            {
                match = text.IndexOf(query, StringComparison.OrdinalIgnoreCase);
            }
        }
        if (match < 0)
        {
            return;
        }

        editor.Select(match, query.Length);
        editor.ScrollToLine(editor.Document.GetLineByOffset(match).LineNumber);
    }

    private void OnArchiveBrowserPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName is nameof(ArchiveBrowserViewModel.SortField)
            or nameof(ArchiveBrowserViewModel.SortDescending))
        {
            UpdateArchiveSortIndicators();
        }
    }

    private void ApplyArchiveColumnLayout()
    {
        var configured = _viewModel.ArchiveVisibleColumns;
        var configuredSet = configured is { Count: > 0 }
            ? configured.ToHashSet(StringComparer.Ordinal)
            : null;
        var visible = configuredSet is null || configuredSet.SetEquals(LegacyDefaultArchiveColumns)
            ? DefaultArchiveColumns
            : configuredSet;
        _applyingArchiveColumnLayout = true;
        try
        {
            foreach (var column in ArchiveGrid.Columns)
            {
                column.Visibility = visible.Contains(column.SortMemberPath)
                    ? Visibility.Visible
                    : Visibility.Collapsed;
            }
            if (!ArchiveGrid.Columns.Any(static column => column.Visibility == Visibility.Visible)
                && ArchiveGrid.Columns.Count > 0)
            {
                ArchiveGrid.Columns[0].Visibility = Visibility.Visible;
            }
        }
        finally
        {
            _applyingArchiveColumnLayout = false;
        }
        SaveArchiveColumnLayout();
    }

    private void OnArchiveColumnsButtonClick(object sender, RoutedEventArgs eventArgs)
    {
        ArchiveColumnsPopup.IsOpen = !ArchiveColumnsPopup.IsOpen;
    }

    private void OnArchiveColumnVisibilityChanged(object sender, RoutedEventArgs eventArgs)
    {
        if (_applyingArchiveColumnLayout || sender is not CheckBox { DataContext: DataGridColumn changedColumn })
        {
            return;
        }
        if (!ArchiveGrid.Columns.Any(static column => column.Visibility == Visibility.Visible))
        {
            _applyingArchiveColumnLayout = true;
            changedColumn.Visibility = Visibility.Visible;
            _applyingArchiveColumnLayout = false;
        }
        SaveArchiveColumnLayout();
    }

    private void OnShowAllArchiveColumnsClick(object sender, RoutedEventArgs eventArgs)
    {
        _applyingArchiveColumnLayout = true;
        try
        {
            foreach (var column in ArchiveGrid.Columns)
            {
                column.Visibility = Visibility.Visible;
            }
        }
        finally
        {
            _applyingArchiveColumnLayout = false;
        }
        SaveArchiveColumnLayout();
    }

    private void SaveArchiveColumnLayout()
    {
        _viewModel.SetArchiveVisibleColumns(ArchiveGrid.Columns
            .Where(static column => column.Visibility == Visibility.Visible)
            .Select(static column => column.SortMemberPath));
    }

    private void OnArchiveGridSorting(object sender, DataGridSortingEventArgs eventArgs)
    {
        eventArgs.Handled = true;
        if (Enum.TryParse<Cdmw.ArchiveLite.Contracts.ArchiveSortField>(
            eventArgs.Column.SortMemberPath,
            ignoreCase: false,
            out var field))
        {
            _viewModel.ArchiveBrowser.ApplyColumnSort(field);
            UpdateArchiveSortIndicators();
        }
    }

    private void UpdateArchiveSortIndicators()
    {
        if (!IsLoaded)
        {
            return;
        }
        var field = _viewModel.ArchiveBrowser.SortField.ToString();
        foreach (var column in ArchiveGrid.Columns)
        {
            column.SortDirection = column.SortMemberPath.Equals(field, StringComparison.Ordinal)
                ? (_viewModel.ArchiveBrowser.SortDescending
                    ? ListSortDirection.Descending
                    : ListSortDirection.Ascending)
                : null;
        }
    }

    private async void OnClosing(object? sender, CancelEventArgs eventArgs)
    {
        if (_shutdownComplete)
        {
            return;
        }

        eventArgs.Cancel = true;
        if (_shutdownStarted)
        {
            return;
        }

        _shutdownStarted = true;
        CaptureUiState();
        IsEnabled = false;
        try
        {
            await ModelPreviewHost.ShutdownAsync().ConfigureAwait(true);
            await _viewModel.ShutdownAsync().ConfigureAwait(true);
        }
        finally
        {
            _shutdownComplete = true;
            Close();
        }
    }

    private void OnWindowStateChanged(object? sender, EventArgs eventArgs)
    {
        if (WindowState != WindowState.Minimized)
        {
            _lastNonMinimizedWindowState = WindowState;
        }
    }

    private void ApplyWindowPlacement()
    {
        var placement = _viewModel.WindowPlacement;
        if (placement is null)
        {
            return;
        }

        var virtualLeft = SystemParameters.VirtualScreenLeft;
        var virtualTop = SystemParameters.VirtualScreenTop;
        var virtualWidth = Math.Max(MinWidth, SystemParameters.VirtualScreenWidth);
        var virtualHeight = Math.Max(MinHeight, SystemParameters.VirtualScreenHeight);
        var width = NormalizeDimension(placement.Width, Width, MinWidth, virtualWidth);
        var height = NormalizeDimension(placement.Height, Height, MinHeight, virtualHeight);
        Width = width;
        Height = height;

        if (placement.Left is { } left
            && placement.Top is { } top
            && double.IsFinite(left)
            && double.IsFinite(top))
        {
            WindowStartupLocation = WindowStartupLocation.Manual;
            Left = Math.Clamp(left, virtualLeft, virtualLeft + Math.Max(0, virtualWidth - width));
            Top = Math.Clamp(top, virtualTop, virtualTop + Math.Max(0, virtualHeight - height));
        }

        _lastNonMinimizedWindowState = placement.IsMaximized
            ? WindowState.Maximized
            : WindowState.Normal;
        WindowState = _lastNonMinimizedWindowState;
    }

    private void ApplyWorkspaceLayout()
    {
        var layout = _viewModel.WorkspaceLayout;
        if (layout is null)
        {
            return;
        }

        ArchiveFilterColumn.Width = PixelGridLength(layout.ArchiveFilterWidth, 250, 720, 278);
        ArchiveResultsColumn.Width = new GridLength(1, GridUnitType.Star);
        ArchivePreviewColumn.Width = PixelGridLength(layout.ArchivePreviewWidth, 350, 1000, 420);
        TextSearchFilterColumn.Width = PixelGridLength(layout.TextSearchFilterWidth, 270, 720, 300);
        TextSearchResultsColumn.Width = new GridLength(1, GridUnitType.Star);
        TextSearchPreviewColumn.Width = PixelGridLength(layout.TextSearchPreviewWidth, 350, 1000, 420);
    }

    private static void ApplyGridColumnLayout(
        DataGrid grid,
        IReadOnlyList<GridColumnSettings>? configured)
    {
        if (configured is not { Count: > 0 } || grid.Columns.Count == 0)
        {
            return;
        }

        var columnsByKey = grid.Columns
            .Where(static column => !string.IsNullOrWhiteSpace(column.SortMemberPath))
            .ToDictionary(static column => column.SortMemberPath, StringComparer.Ordinal);
        var layoutByKey = configured
            .Where(setting => !string.IsNullOrWhiteSpace(setting.Key) && columnsByKey.ContainsKey(setting.Key))
            .GroupBy(static setting => setting.Key, StringComparer.Ordinal)
            .Select(static group => group.First())
            .ToDictionary(static setting => setting.Key, StringComparer.Ordinal);
        var orderedColumns = configured
            .Where(setting => layoutByKey.TryGetValue(setting.Key, out var canonical) && ReferenceEquals(setting, canonical))
            .OrderBy(static setting => setting.DisplayIndex)
            .Select(setting => columnsByKey[setting.Key])
            .Concat(grid.Columns.Where(column => !layoutByKey.ContainsKey(column.SortMemberPath)))
            .Distinct()
            .ToArray();

        for (var index = 0; index < orderedColumns.Length; index++)
        {
            orderedColumns[index].DisplayIndex = index;
        }
        foreach (var (key, setting) in layoutByKey)
        {
            var column = columnsByKey[key];
            if (double.IsFinite(setting.Width) && setting.Width > 0)
            {
                var minimum = Math.Max(48, Math.Max(grid.MinColumnWidth, column.MinWidth));
                column.Width = new DataGridLength(Math.Clamp(setting.Width, minimum, 1600), DataGridLengthUnitType.Pixel);
            }
        }
    }

    private void CaptureUiState()
    {
        SaveArchiveColumnLayout();
        var priorWorkspace = _viewModel.WorkspaceLayout ?? new WorkspaceLayoutSettings();
        _viewModel.SetUiLayout(
            CaptureWindowPlacement(),
            new WorkspaceLayoutSettings(
                MeasuredWidthOrFallback(ArchiveFilterColumn, priorWorkspace.ArchiveFilterWidth),
                MeasuredWidthOrFallback(ArchivePreviewColumn, priorWorkspace.ArchivePreviewWidth),
                MeasuredWidthOrFallback(TextSearchFilterColumn, priorWorkspace.TextSearchFilterWidth),
                MeasuredWidthOrFallback(TextSearchPreviewColumn, priorWorkspace.TextSearchPreviewWidth)),
            CaptureGridColumnLayout(ArchiveGrid, _viewModel.ArchiveColumnLayout),
            CaptureGridColumnLayout(TextSearchResultsGrid, _viewModel.TextSearchColumnLayout));
    }

    private WindowPlacementSettings CaptureWindowPlacement()
    {
        var isMaximized = WindowState == WindowState.Maximized
            || (WindowState == WindowState.Minimized && _lastNonMinimizedWindowState == WindowState.Maximized);
        var bounds = WindowState == WindowState.Normal
            ? new Rect(Left, Top, ActualWidth, ActualHeight)
            : RestoreBounds;
        if (!IsUsableBounds(bounds))
        {
            bounds = new Rect(Left, Top, Width, Height);
        }
        return new WindowPlacementSettings(bounds.Left, bounds.Top, bounds.Width, bounds.Height, isMaximized);
    }

    private static IReadOnlyList<GridColumnSettings> CaptureGridColumnLayout(
        DataGrid grid,
        IReadOnlyList<GridColumnSettings>? priorLayout)
    {
        var priorWidths = priorLayout?
            .Where(static setting => !string.IsNullOrWhiteSpace(setting.Key))
            .GroupBy(static setting => setting.Key, StringComparer.Ordinal)
            .ToDictionary(static group => group.Key, static group => group.First().Width, StringComparer.Ordinal)
            ?? new Dictionary<string, double>(StringComparer.Ordinal);
        return grid.Columns
            .Where(static column => !string.IsNullOrWhiteSpace(column.SortMemberPath))
            .Select(column => new GridColumnSettings(
                column.SortMemberPath,
                column.DisplayIndex,
                MeasuredColumnWidthOrFallback(column, priorWidths.GetValueOrDefault(column.SortMemberPath))))
            .ToArray();
    }

    private static double MeasuredColumnWidthOrFallback(DataGridColumn column, double fallback)
    {
        if (double.IsFinite(column.ActualWidth) && column.ActualWidth > 0)
        {
            return column.ActualWidth;
        }
        if (double.IsFinite(fallback) && fallback > 0)
        {
            return fallback;
        }
        return column.Width.UnitType == DataGridLengthUnitType.Pixel
            && double.IsFinite(column.Width.DisplayValue)
            && column.Width.DisplayValue > 0
                ? column.Width.DisplayValue
                : 0;
    }

    private static double MeasuredWidthOrFallback(ColumnDefinition column, double fallback) =>
        double.IsFinite(column.ActualWidth) && column.ActualWidth >= column.MinWidth
            ? column.ActualWidth
            : fallback;

    private static GridLength PixelGridLength(double value, double minimum, double maximum, double fallback) =>
        new(NormalizeDimension(value, fallback, minimum, maximum), GridUnitType.Pixel);

    private static double NormalizeDimension(double value, double fallback, double minimum, double maximum)
    {
        var normalized = double.IsFinite(value) ? value : fallback;
        return Math.Clamp(normalized, minimum, Math.Max(minimum, maximum));
    }

    private static bool IsUsableBounds(Rect bounds) =>
        !bounds.IsEmpty
        && double.IsFinite(bounds.Left)
        && double.IsFinite(bounds.Top)
        && double.IsFinite(bounds.Width)
        && double.IsFinite(bounds.Height)
        && bounds.Width > 0
        && bounds.Height > 0;

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(
        IntPtr windowHandle,
        int attribute,
        ref int attributeValue,
        int attributeSize);
}
