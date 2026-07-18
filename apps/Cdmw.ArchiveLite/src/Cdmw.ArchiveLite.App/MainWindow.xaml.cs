using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.App.ViewModels;

namespace Cdmw.ArchiveLite.App;

public partial class MainWindow : Window
{
    private readonly MainWindowViewModel _viewModel;
    private bool _shutdownStarted;
    private bool _shutdownComplete;

    public MainWindow(MainWindowViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;
        Closing += OnClosing;
        Closed += OnClosed;
        SourceInitialized += OnSourceInitialized;
        ThemeManager.ThemeChanged += OnThemeChanged;
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
    }

    private void OnClosed(object? sender, EventArgs eventArgs)
    {
        ThemeManager.ThemeChanged -= OnThemeChanged;
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
