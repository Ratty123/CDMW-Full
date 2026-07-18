using System.Windows;
using Cdmw.ArchiveLite.App.Dialogs;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Services;

public sealed class ArchiveCacheChoicePrompt(Func<Window?> ownerProvider)
{
    public ArchiveCacheMode? Choose(string packageRoot, bool forceRefresh)
    {
        var dialog = new ArchiveCacheChoiceDialog(packageRoot, forceRefresh);
        var owner = ownerProvider();
        if (owner is not null && owner.IsLoaded)
        {
            dialog.Owner = owner;
        }
        else
        {
            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen;
        }
        return dialog.ShowDialog() == true ? dialog.Selection : null;
    }
}
