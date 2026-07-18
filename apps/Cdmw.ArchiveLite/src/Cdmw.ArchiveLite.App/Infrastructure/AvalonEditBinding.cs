using System.Windows;
using ICSharpCode.AvalonEdit;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public static class AvalonEditBinding
{
    public static readonly DependencyProperty TextProperty = DependencyProperty.RegisterAttached(
        "Text",
        typeof(string),
        typeof(AvalonEditBinding),
        new FrameworkPropertyMetadata(string.Empty, OnTextChanged));

    public static void SetText(DependencyObject element, string value) => element.SetValue(TextProperty, value);

    public static string GetText(DependencyObject element) => (string)element.GetValue(TextProperty);

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
        }
    }
}
