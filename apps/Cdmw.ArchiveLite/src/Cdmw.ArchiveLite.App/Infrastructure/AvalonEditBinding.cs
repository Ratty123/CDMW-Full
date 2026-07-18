using System.Windows;
using System.Windows.Threading;
using ICSharpCode.AvalonEdit;
using ICSharpCode.AvalonEdit.Highlighting;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public static class AvalonEditBinding
{
    public static readonly DependencyProperty TextProperty = DependencyProperty.RegisterAttached(
        "Text",
        typeof(string),
        typeof(AvalonEditBinding),
        new FrameworkPropertyMetadata(string.Empty, OnTextChanged));

    public static readonly DependencyProperty SyntaxProperty = DependencyProperty.RegisterAttached(
        "Syntax",
        typeof(string),
        typeof(AvalonEditBinding),
        new FrameworkPropertyMetadata(string.Empty, OnSyntaxChanged));

    public static readonly DependencyProperty SelectionLineProperty = DependencyProperty.RegisterAttached(
        "SelectionLine",
        typeof(int),
        typeof(AvalonEditBinding),
        new FrameworkPropertyMetadata(1, OnSelectionChanged));

    public static readonly DependencyProperty SelectionColumnProperty = DependencyProperty.RegisterAttached(
        "SelectionColumn",
        typeof(int),
        typeof(AvalonEditBinding),
        new FrameworkPropertyMetadata(1, OnSelectionChanged));

    public static readonly DependencyProperty SelectionLengthProperty = DependencyProperty.RegisterAttached(
        "SelectionLength",
        typeof(int),
        typeof(AvalonEditBinding),
        new FrameworkPropertyMetadata(0, OnSelectionChanged));

    public static void SetText(DependencyObject element, string value) => element.SetValue(TextProperty, value);

    public static string GetText(DependencyObject element) => (string)element.GetValue(TextProperty);

    public static void SetSyntax(DependencyObject element, string value) => element.SetValue(SyntaxProperty, value);

    public static string GetSyntax(DependencyObject element) => (string)element.GetValue(SyntaxProperty);

    public static void SetSelectionLine(DependencyObject element, int value) => element.SetValue(SelectionLineProperty, value);

    public static int GetSelectionLine(DependencyObject element) => (int)element.GetValue(SelectionLineProperty);

    public static void SetSelectionColumn(DependencyObject element, int value) => element.SetValue(SelectionColumnProperty, value);

    public static int GetSelectionColumn(DependencyObject element) => (int)element.GetValue(SelectionColumnProperty);

    public static void SetSelectionLength(DependencyObject element, int value) => element.SetValue(SelectionLengthProperty, value);

    public static int GetSelectionLength(DependencyObject element) => (int)element.GetValue(SelectionLengthProperty);

    private static void OnTextChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs eventArgs)
    {
        if (dependencyObject is TextEditor editor)
        {
            var next = eventArgs.NewValue as string ?? string.Empty;
            if (!string.Equals(editor.Text, next, StringComparison.Ordinal))
            {
                editor.Text = next;
                editor.ScrollToHome();
            }
            ScheduleSelection(editor);
        }
    }

    private static void OnSyntaxChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs eventArgs)
    {
        if (dependencyObject is not TextEditor editor)
        {
            return;
        }
        var syntax = eventArgs.NewValue as string ?? string.Empty;
        editor.SyntaxHighlighting = ResolveHighlighting(syntax);
    }

    private static void OnSelectionChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs eventArgs)
    {
        if (dependencyObject is TextEditor editor)
        {
            ScheduleSelection(editor);
        }
    }

    private static void ScheduleSelection(TextEditor editor) =>
        _ = editor.Dispatcher.BeginInvoke(
            DispatcherPriority.Background,
            () => ApplySelection(editor));

    private static void ApplySelection(TextEditor editor)
    {
        if (editor.Document.LineCount == 0)
        {
            return;
        }
        var lineNumber = Math.Clamp(GetSelectionLine(editor), 1, editor.Document.LineCount);
        var line = editor.Document.GetLineByNumber(lineNumber);
        var columnOffset = Math.Clamp(GetSelectionColumn(editor) - 1, 0, line.Length);
        var offset = line.Offset + columnOffset;
        var length = Math.Clamp(GetSelectionLength(editor), 0, editor.Document.TextLength - offset);
        editor.Select(offset, length);
        editor.ScrollTo(lineNumber, columnOffset + 1);
    }

    private static IHighlightingDefinition? ResolveHighlighting(string syntax)
    {
        var extension = syntax.Trim().ToLowerInvariant();
        if (extension.Length == 0)
        {
            return null;
        }
        if (!extension.StartsWith('.'))
        {
            extension = "." + extension;
        }
        var manager = HighlightingManager.Instance;
        return manager.GetDefinitionByExtension(extension) ?? extension switch
        {
            ".json" or ".js" => manager.GetDefinition("JavaScript"),
            ".hlsl" or ".shader" or ".material" => manager.GetDefinition("C++"),
            _ => null,
        };
    }
}
