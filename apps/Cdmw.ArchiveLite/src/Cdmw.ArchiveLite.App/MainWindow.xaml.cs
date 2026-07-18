using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.App.ViewModels;

namespace Cdmw.ArchiveLite.App;

public partial class MainWindow : Window
{
    private readonly MainWindowViewModel _viewModel;
    private bool _shutdownStarted;
    private bool _shutdownComplete;
    private bool _applyingArchiveColumnLayout;

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
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;
        Closing += OnClosing;
        Closed += OnClosed;
        Loaded += OnLoaded;
        SourceInitialized += OnSourceInitialized;
        ThemeManager.ThemeChanged += OnThemeChanged;
        _viewModel.ArchiveBrowser.PropertyChanged += OnArchiveBrowserPropertyChanged;
    }

    private void OnSourceInitialized(object? sender, EventArgs eventArgs) => ApplyTitleBarTheme();

    private void OnThemeChanged(object? sender, EventArgs eventArgs)
    {
        if (Dispatcher.CheckAccess())
        {
            ApplyTitleBarTheme();
        }
        else
        {
            _ = Dispatcher.BeginInvoke(ApplyTitleBarTheme);
        }
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

    private void ToggleMaximizedState() =>
        WindowState = WindowState == WindowState.Maximized
            ? WindowState.Normal
            : WindowState.Maximized;

    private void OnClosed(object? sender, EventArgs eventArgs)
    {
        ThemeManager.ThemeChanged -= OnThemeChanged;
        _viewModel.ArchiveBrowser.PropertyChanged -= OnArchiveBrowserPropertyChanged;
    }

    private void OnLoaded(object sender, RoutedEventArgs eventArgs)
    {
        ArchiveColumnChooser.ItemsSource = ArchiveGrid.Columns;
        ApplyArchiveColumnLayout();
        UpdateArchiveSortIndicators();
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

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(
        IntPtr windowHandle,
        int attribute,
        ref int attributeValue,
        int attributeSize);
}
