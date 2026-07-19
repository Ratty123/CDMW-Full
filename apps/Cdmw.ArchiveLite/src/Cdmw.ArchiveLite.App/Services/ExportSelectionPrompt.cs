using System.Windows;
using Cdmw.ArchiveLite.App.Dialogs;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Services;

public sealed class ExportSelectionPrompt(Func<Window?> ownerProvider)
{
    public ExportSelection? Choose(int selectedCount, bool supportsModelExport, bool canExportFamily)
    {
        var dialog = new ExportSelectionDialog(selectedCount, supportsModelExport, canExportFamily);
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

public enum ExportSelectionMode
{
    FilesOnly,
    PreserveStructure,
    Family,
}

public sealed record ExportSelection(ExportSelectionMode Mode, ExportKind Kind);
