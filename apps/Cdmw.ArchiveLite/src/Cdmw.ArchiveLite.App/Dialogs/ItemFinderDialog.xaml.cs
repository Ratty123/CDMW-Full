using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using Cdmw.ArchiveLite.App.ViewModels;

namespace Cdmw.ArchiveLite.App.Dialogs;

public partial class ItemFinderDialog : Window
{
    private readonly ItemFinderViewModel _viewModel;
    private readonly DispatcherTimer _filterTimer;
    private bool _loaded;

    public ItemFinderDialog(ItemFinderViewModel viewModel)
    {
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        InitializeComponent();
        DataContext = viewModel;
        Width = viewModel.WindowWidth;
        Height = viewModel.WindowHeight;
        _filterTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(220),
        };
        _filterTimer.Tick += OnFilterTimerTick;
        _viewModel.CloseRequested += OnCloseRequested;
        Loaded += OnLoaded;
        Closing += OnClosing;
    }

    private async void OnLoaded(object sender, RoutedEventArgs eventArgs)
    {
        _loaded = true;
        SearchBox.Focus();
        try
        {
            await _viewModel.ActivateAsync(CancellationToken.None).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            // Closing the dialog during activation is expected.
        }
    }

    private void OnClosing(object? sender, CancelEventArgs eventArgs)
    {
        _loaded = false;
        _filterTimer.Stop();
        _viewModel.UpdateWindowSize(ActualWidth, ActualHeight);
        _viewModel.Deactivate();
        _viewModel.CloseRequested -= OnCloseRequested;
    }

    private void OnFilterChanged(object sender, TextChangedEventArgs eventArgs)
    {
        if (sender is TextBox { IsKeyboardFocusWithin: true })
        {
            ScheduleFilter();
        }
    }

    private void OnFilterSelectionChanged(object sender, SelectionChangedEventArgs eventArgs)
    {
        if (sender is ComboBox comboBox && (comboBox.IsDropDownOpen || comboBox.IsKeyboardFocusWithin))
        {
            ScheduleFilter();
        }
    }

    private void ScheduleFilter()
    {
        if (!_loaded)
        {
            return;
        }
        _filterTimer.Stop();
        _filterTimer.Start();
    }

    private async void OnFilterTimerTick(object? sender, EventArgs eventArgs)
    {
        _filterTimer.Stop();
        try
        {
            await _viewModel.RefreshAsync(CancellationToken.None).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            // A newer filter owns the result.
        }
    }

    private void OnSearchKeyDown(object sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.Key != Key.Enter)
        {
            return;
        }
        _filterTimer.Stop();
        _viewModel.SearchCommand.Execute(null);
        eventArgs.Handled = true;
    }

    private void OnCloseClick(object sender, RoutedEventArgs eventArgs) => Close();

    private void OnCloseRequested(object? sender, EventArgs eventArgs) => Close();

    private void OnTitleBarMouseLeftButtonDown(object sender, MouseButtonEventArgs eventArgs)
    {
        if (eventArgs.ClickCount == 2)
        {
            WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
        }
        else if (eventArgs.ButtonState == MouseButtonState.Pressed)
        {
            DragMove();
        }
    }
}
