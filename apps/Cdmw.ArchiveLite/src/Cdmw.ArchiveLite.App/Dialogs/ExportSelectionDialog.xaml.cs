using System.Windows;
using System.Windows.Input;
using Cdmw.ArchiveLite.App.Services;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Dialogs;

public partial class ExportSelectionDialog : Window
{
    public ExportSelectionDialog(int selectedCount, bool supportsModelExport, bool canExportFamily)
    {
        InitializeComponent();
        IntroText.Text = LocalizationManager.Format("ExportChoiceIntro", selectedCount);
        FormatComboBox.ItemsSource = BuildFormats(supportsModelExport);
        FormatComboBox.SelectedIndex = 0;
        FormatPanel.Visibility = selectedCount == 1 ? Visibility.Visible : Visibility.Collapsed;
        FamilyRadio.Visibility = canExportFamily ? Visibility.Visible : Visibility.Collapsed;
        Loaded += (_, _) => FilesOnlyRadio.Focus();
    }

    public ExportSelection? Selection { get; private set; }

    private static IReadOnlyList<ExportFormatOption> BuildFormats(bool supportsModelExport)
    {
        var formats = new List<ExportFormatOption>
        {
            new(ExportKind.RawEntries, LocalizationManager.Get("ExportChoiceOriginal")),
        };
        if (supportsModelExport)
        {
            formats.Add(new(ExportKind.Glb, LocalizationManager.Get("ExportChoiceGlb")));
            formats.Add(new(ExportKind.Obj, LocalizationManager.Get("ExportChoiceObj")));
            formats.Add(new(ExportKind.Fbx, LocalizationManager.Get("ExportChoiceFbx")));
        }
        return formats;
    }

    private void OnContinueClick(object sender, RoutedEventArgs eventArgs)
    {
        var mode = FamilyRadio.IsChecked == true
            ? ExportSelectionMode.Family
            : StructureRadio.IsChecked == true
                ? ExportSelectionMode.PreserveStructure
                : ExportSelectionMode.FilesOnly;
        var kind = mode == ExportSelectionMode.FilesOnly
            && FormatComboBox.SelectedItem is ExportFormatOption format
                ? format.Kind
                : ExportKind.RawEntries;
        Selection = new ExportSelection(mode, kind);
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

public sealed record ExportFormatOption(ExportKind Kind, string Label)
{
    public override string ToString() => Label;
}
