using System.Windows;
using System.Windows.Input;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Dialogs;

public partial class ArchiveCacheChoiceDialog : Window
{
    public ArchiveCacheChoiceDialog(string packageRoot, bool forceRefresh)
    {
        InitializeComponent();
        SourcePathText.Text = packageRoot;
        PersistentTitleText.Text = LocalizationManager.Get(
            forceRefresh ? "CacheChoicePersistentRefreshTitle" : "CacheChoicePersistentTitle");
        PersistentBodyText.Text = LocalizationManager.Get(
            forceRefresh ? "CacheChoicePersistentRefreshBody" : "CacheChoicePersistentBody");
        Loaded += (_, _) => PersistentButton.Focus();
    }

    public ArchiveCacheMode? Selection { get; private set; }

    private void OnPersistentClick(object sender, RoutedEventArgs eventArgs) =>
        Complete(ArchiveCacheMode.Persistent);

    private void OnSessionOnlyClick(object sender, RoutedEventArgs eventArgs) =>
        Complete(ArchiveCacheMode.SessionOnly);

    private void Complete(ArchiveCacheMode cacheMode)
    {
        Selection = cacheMode;
        DialogResult = true;
    }

    private void OnCloseClick(object sender, RoutedEventArgs eventArgs) => DialogResult = false;

    private void OnTitleBarMouseLeftButtonDown(object sender, MouseButtonEventArgs eventArgs)
    {
        if (eventArgs.ButtonState == MouseButtonState.Pressed)
        {
            DragMove();
        }
    }
}
