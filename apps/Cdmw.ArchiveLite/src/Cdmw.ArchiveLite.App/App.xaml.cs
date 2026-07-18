using System.Globalization;
using System.Windows;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.App.ViewModels;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App;

public partial class App : Application
{
    private WorkerProcessHost? _worker;

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
                    window.ApplyTemplate();
                    window.Measure(size);
                    window.Arrange(new Rect(new Point(), size));
                    if (!double.IsFinite(window.DesiredSize.Width) || !double.IsFinite(window.DesiredSize.Height))
                    {
                        throw new InvalidDataException($"The {theme.Id} theme produced an invalid window layout.");
                    }
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

    protected override void OnExit(ExitEventArgs e)
    {
        if (_worker is not null)
        {
            _worker.DisposeImmediately();
        }

        base.OnExit(e);
    }
}
