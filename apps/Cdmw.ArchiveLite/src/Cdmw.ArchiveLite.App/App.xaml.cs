using System.Globalization;
using System.Windows;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.App.ViewModels;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App;

public partial class App : Application
{
    private WorkerProcessHost? _worker;

    public App()
    {
        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnDomainUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
    }

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        AppDataPaths.EnsureCreated();
        if (e.Args.Contains("--self-test", StringComparer.OrdinalIgnoreCase))
        {
            await RunSelfTestAsync().ConfigureAwait(true);
            return;
        }

        var settings = await SettingsStore.LoadAsync(CancellationToken.None).ConfigureAwait(true);
        LocalizationManager.ApplyCulture(settings.Language);
        ThemeManager.Apply(settings.Theme);
        UiPreferencesManager.Apply(settings.FontSize, settings.LayoutDensity);

        try
        {
            _worker = await WorkerProcessHost.StartAsync(CancellationToken.None).ConfigureAwait(true);
            var viewModel = new MainWindowViewModel(_worker, settings);
            var window = new MainWindow(viewModel);
            MainWindow = window;
            ShutdownMode = ShutdownMode.OnMainWindowClose;
            window.Show();
            await viewModel.InitializeAsync().ConfigureAwait(true);
        }
        catch (Exception exception)
        {
            await DiagnosticLog.WriteAsync("startup", exception.ToString(), CancellationToken.None).ConfigureAwait(true);
            MessageBox.Show(
                LocalizationManager.Format("StartupFailureMessage", exception.Message),
                LocalizationManager.Get("StartupFailureTitle"),
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown(1);
        }
    }

    private async Task RunSelfTestAsync()
    {
        try
        {
            LocalizationManager.ApplyCulture("en");
            ThemeManager.Apply("graphite");
            UiPreferencesManager.Apply("medium", "comfortable");
            _worker = await WorkerProcessHost.StartAsync(CancellationToken.None).ConfigureAwait(true);
            var result = await _worker.SendAsync<PingRequest, PingResult>(
                WorkerProtocol.Ping,
                1,
                new PingRequest(typeof(App).Assembly.GetName().Version?.ToString() ?? "0.0.0"),
                CancellationToken.None).ConfigureAwait(true);
            if (result.ProtocolVersion != WorkerProtocol.Version)
            {
                throw new InvalidDataException("Worker protocol self-test failed.");
            }
            var viewModel = new MainWindowViewModel(_worker, new LiteSettings());
            var window = new MainWindow(viewModel);
            foreach (var theme in ThemeManager.AvailableThemes)
            {
                ThemeManager.Apply(theme.Id);
                foreach (var size in new[] { new Size(1440, 880), new Size(1200, 720) })
                {
                    ValidateHiddenLayout(window, size, $"theme {theme.Id}");
                }
            }
            ThemeManager.Apply("graphite");
            foreach (var fontSize in UiPreferencesManager.AvailableFontSizes)
            {
                foreach (var density in UiPreferencesManager.AvailableLayoutDensities)
                {
                    UiPreferencesManager.Apply(fontSize.Id, density.Id);
                    var size = new Size(1200, 720);
                    ValidateHiddenLayout(window, size, $"appearance {fontSize.Id}/{density.Id}");
                }
            }
            await _worker.ShutdownAsync().ConfigureAwait(true);
            Shutdown(0);
        }
        catch (Exception exception)
        {
            await DiagnosticLog.WriteAsync("self-test", exception.ToString(), CancellationToken.None).ConfigureAwait(true);
            Shutdown(1);
        }
    }

    private static void ValidateHiddenLayout(MainWindow window, Size size, string variant)
    {
        window.ApplyTemplate();
        window.Measure(size);
        window.Arrange(new Rect(new Point(), size));
        window.UpdateLayout();
        if (!double.IsFinite(window.DesiredSize.Width) || !double.IsFinite(window.DesiredSize.Height))
        {
            throw new InvalidDataException($"The {variant} produced an invalid window layout.");
        }

        const double tolerance = 0.5;
        foreach (var child in window.TitleBarGrid.Children.OfType<FrameworkElement>().Where(static child => child.Visibility == Visibility.Visible))
        {
            var origin = child.TranslatePoint(new Point(), window.TitleBarGrid);
            if (!double.IsFinite(origin.X)
                || origin.X < -tolerance
                || origin.X + child.ActualWidth > window.TitleBarGrid.ActualWidth + tolerance)
            {
                throw new InvalidDataException($"The {variant} places a title-row control outside the available window width.");
            }
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        DispatcherUnhandledException -= OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException -= OnDomainUnhandledException;
        TaskScheduler.UnobservedTaskException -= OnUnobservedTaskException;
        if (_worker is not null)
        {
            _worker.DisposeImmediately();
        }

        base.OnExit(e);
    }

    private static void OnDispatcherUnhandledException(
        object sender,
        System.Windows.Threading.DispatcherUnhandledExceptionEventArgs eventArgs) =>
        DiagnosticLog.WriteFatal("dispatcher-unhandled", eventArgs.Exception);

    private static void OnDomainUnhandledException(object? sender, UnhandledExceptionEventArgs eventArgs)
    {
        var exception = eventArgs.ExceptionObject as Exception
            ?? new InvalidOperationException($"Unhandled non-exception object: {eventArgs.ExceptionObject}");
        DiagnosticLog.WriteFatal("domain-unhandled", exception);
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs eventArgs)
    {
        DiagnosticLog.WriteFatal("task-unobserved", eventArgs.Exception);
        eventArgs.SetObserved();
    }
}
