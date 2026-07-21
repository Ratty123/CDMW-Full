using System.ComponentModel;
using System.Windows;
using System.Windows.Input;
using Cdmw.ArchiveLite.App.Infrastructure;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.App.ViewModels;

namespace Cdmw.ArchiveLite.App.Dialogs;

public partial class ItemFinderDialog : Window
{
    private readonly ItemFinderViewModel _viewModel;

    public ItemFinderDialog(ItemFinderViewModel viewModel)
    {
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        InitializeComponent();
        DataContext = viewModel;
        Width = viewModel.WindowWidth;
        Height = viewModel.WindowHeight;
        _viewModel.CloseRequested += OnCloseRequested;
        Loaded += OnLoaded;
        Closing += OnClosing;
        Closed += OnClosed;
        SourceInitialized += OnSourceInitialized;
        ThemeManager.ThemeChanged += OnThemeChanged;
    }

    private void OnSourceInitialized(object? sender, EventArgs eventArgs) => ThemedWindowChrome.Apply(this);

    private void OnThemeChanged(object? sender, EventArgs eventArgs)
    {
        if (Dispatcher.CheckAccess())
        {
            ThemedWindowChrome.Apply(this);
        }
        else
        {
            _ = Dispatcher.BeginInvoke(() => ThemedWindowChrome.Apply(this));
        }
    }

    private async void OnLoaded(object sender, RoutedEventArgs eventArgs)
    {
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
        _viewModel.UpdateWindowSize(ActualWidth, ActualHeight);
        _viewModel.Deactivate();
        _viewModel.CloseRequested -= OnCloseRequested;
    }

    private void OnClosed(object? sender, EventArgs eventArgs)
    {
        ThemeManager.ThemeChanged -= OnThemeChanged;
        SourceInitialized -= OnSourceInitialized;
        Closed -= OnClosed;
    }

    private void OnSearchKeyDown(object sender, KeyEventArgs eventArgs)
    {
        if (eventArgs.Key != Key.Enter)
        {
            return;
        }
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
