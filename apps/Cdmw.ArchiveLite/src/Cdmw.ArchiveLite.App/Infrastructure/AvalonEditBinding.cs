using System.Windows;
using System.Windows.Threading;
using System.Xml;
using System.Xml.Linq;
using Cdmw.ArchiveLite.App.Services;
using ICSharpCode.AvalonEdit;
using ICSharpCode.AvalonEdit.Highlighting;
using ICSharpCode.AvalonEdit.Highlighting.Xshd;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public static class AvalonEditBinding
{
    private const string HighlightingResourcePrefix = "ICSharpCode.AvalonEdit.Highlighting.Resources.";

    private static readonly IReadOnlyDictionary<string, string> HighlightingResources =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["ASP/XHTML"] = "ASPX.xshd",
            ["Boo"] = "Boo.xshd",
            ["Coco"] = "Coco-Mode.xshd",
            ["C++"] = "CPP-Mode.xshd",
            ["C#"] = "CSharp-Mode.xshd",
            ["CSS"] = "CSS-Mode.xshd",
            ["HTML"] = "HTML-Mode.xshd",
            ["Java"] = "Java-Mode.xshd",
            ["JavaScript"] = "JavaScript-Mode.xshd",
            ["Json"] = "Json.xshd",
            ["MarkDown"] = "MarkDown-Mode.xshd",
            ["MarkDownWithFontSize"] = "MarkDownWithFontSize-Mode.xshd",
            ["Patch"] = "Patch-Mode.xshd",
            ["PHP"] = "PHP-Mode.xshd",
            ["PowerShell"] = "PowerShell.xshd",
            ["Python"] = "Python-Mode.xshd",
            ["TeX"] = "Tex-Mode.xshd",
            ["TSQL"] = "TSQL-Mode.xshd",
            ["VB"] = "VB-Mode.xshd",
            ["XML"] = "XML-Mode.xshd",
            ["XmlDoc"] = "XmlDoc.xshd",
        };

    private static readonly Dictionary<(string ResourceName, bool IsDark), IHighlightingDefinition> ThemedHighlightingCache = [];
    private static readonly object ThemedHighlightingLock = new();

    private static readonly EditorPalette DarkPalette = new(
        Foreground: "#D4D4D4",
        Comment: "#6A9955",
        Keyword: "#C586C0",
        Tag: "#569CD6",
        Type: "#4EC9B0",
        Property: "#9CDCFE",
        String: "#CE9178",
        Number: "#B5CEA8",
        Function: "#DCDCAA",
        Link: "#3794FF",
        Added: "#B5CEA8",
        Error: "#F44747");

    private static readonly EditorPalette LightPalette = new(
        Foreground: "#1F1F1F",
        Comment: "#008000",
        Keyword: "#AF00DB",
        Tag: "#0000FF",
        Type: "#267F99",
        Property: "#001080",
        String: "#A31515",
        Number: "#098658",
        Function: "#795E26",
        Link: "#0000FF",
        Added: "#008000",
        Error: "#CD3131");

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

    public static void RefreshSyntax(TextEditor editor)
    {
        ArgumentNullException.ThrowIfNull(editor);
        editor.SyntaxHighlighting = ResolveHighlighting(GetSyntax(editor));
    }

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
        if (dependencyObject is TextEditor editor)
        {
            RefreshSyntax(editor);
        }
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
        var definition = manager.GetDefinitionByExtension(extension) ?? extension switch
        {
            ".dae" or ".pac_xml" or ".pam_xml" or ".pamlod_xml" or ".prefabdata_xml" or ".app_xml" => manager.GetDefinition("XML"),
            ".gltf" or ".json" => manager.GetDefinition("Json"),
            ".js" => manager.GetDefinition("JavaScript"),
            ".hlsl" or ".shader" or ".material" => manager.GetDefinition("C++"),
            _ => null,
        };
        if (definition is null || !HighlightingResources.TryGetValue(definition.Name, out var resourceName))
        {
            return definition;
        }
        return ResolveThemedHighlighting(definition, resourceName, ThemeManager.Current.IsDark);
    }

    private static IHighlightingDefinition ResolveThemedHighlighting(
        IHighlightingDefinition fallback,
        string resourceName,
        bool isDark)
    {
        var key = (resourceName, isDark);
        lock (ThemedHighlightingLock)
        {
            if (ThemedHighlightingCache.TryGetValue(key, out var cached))
            {
                return cached;
            }

            IHighlightingDefinition themed;
            try
            {
                themed = LoadThemedHighlighting(resourceName, isDark);
            }
            catch (Exception exception) when (exception is IOException
                or XmlException
                or HighlightingDefinitionInvalidException)
            {
                themed = fallback;
            }
            ThemedHighlightingCache[key] = themed;
            return themed;
        }
    }

    private static IHighlightingDefinition LoadThemedHighlighting(string resourceName, bool isDark)
    {
        var assembly = typeof(HighlightingManager).Assembly;
        using var stream = assembly.GetManifestResourceStream(HighlightingResourcePrefix + resourceName)
            ?? throw new InvalidDataException($"AvalonEdit highlighting resource '{resourceName}' is missing.");
        var document = XDocument.Load(stream);
        var palette = isDark ? DarkPalette : LightPalette;
        foreach (var colorElement in document.Descendants().Where(element => element.Name.LocalName == "Color"))
        {
            var name = (string?)colorElement.Attribute("name") ?? string.Empty;
            colorElement.SetAttributeValue("foreground", PaletteColor(name, palette));
            colorElement.Attribute("background")?.Remove();
        }
        using var reader = document.CreateReader();
        return HighlightingLoader.Load(reader, HighlightingManager.Instance);
    }

    private static string PaletteColor(string colorName, EditorPalette palette)
    {
        var normalized = colorName.ToLowerInvariant();
        if (normalized.Contains("comment", StringComparison.Ordinal)
            || normalized.Contains("blockquote", StringComparison.Ordinal))
        {
            return palette.Comment;
        }
        if (normalized.Contains("broken", StringComparison.Ordinal)
            || normalized.Contains("error", StringComparison.Ordinal)
            || normalized.Contains("removed", StringComparison.Ordinal))
        {
            return palette.Error;
        }
        if (normalized.Contains("added", StringComparison.Ordinal))
        {
            return palette.Added;
        }
        if (normalized.Contains("attributevalue", StringComparison.Ordinal)
            || normalized.Contains("string", StringComparison.Ordinal)
            || normalized.Contains("character", StringComparison.Ordinal)
            || normalized.Contains("regex", StringComparison.Ordinal)
            || normalized.Contains("cdata", StringComparison.Ordinal)
            || normalized == "char"
            || normalized == "code"
            || normalized == "value")
        {
            return palette.String;
        }
        if (normalized.Contains("tag", StringComparison.Ordinal))
        {
            return palette.Tag;
        }
        if (normalized.Contains("doctype", StringComparison.Ordinal)
            || normalized.Contains("declaration", StringComparison.Ordinal)
            || normalized.Contains("preprocessor", StringComparison.Ordinal))
        {
            return palette.Keyword;
        }
        if (normalized.Contains("typekeyword", StringComparison.Ordinal)
            || normalized.Contains("valuetype", StringComparison.Ordinal)
            || normalized.Contains("referencetype", StringComparison.Ordinal)
            || normalized.Contains("datatype", StringComparison.Ordinal)
            || normalized.Contains("class", StringComparison.Ordinal)
            || normalized.Contains("selector", StringComparison.Ordinal))
        {
            return palette.Type;
        }
        if (normalized.Contains("keyword", StringComparison.Ordinal)
            || normalized.Contains("modifier", StringComparison.Ordinal)
            || normalized.Contains("operator", StringComparison.Ordinal)
            || normalized.Contains("control", StringComparison.Ordinal)
            || normalized.Contains("selection", StringComparison.Ordinal)
            || normalized.Contains("iteration", StringComparison.Ordinal)
            || normalized.Contains("exception", StringComparison.Ordinal)
            || normalized.Contains("loop", StringComparison.Ordinal)
            || normalized.Contains("jump", StringComparison.Ordinal)
            || normalized.Contains("visibility", StringComparison.Ordinal)
            || normalized.Contains("access", StringComparison.Ordinal)
            || normalized is "this" or "package" or "void")
        {
            return palette.Keyword;
        }
        if (normalized.Contains("attribute", StringComparison.Ordinal)
            || normalized.Contains("field", StringComparison.Ordinal)
            || normalized.Contains("property", StringComparison.Ordinal)
            || normalized.Contains("variable", StringComparison.Ordinal)
            || normalized.Contains("parameter", StringComparison.Ordinal))
        {
            return palette.Property;
        }
        if (normalized.Contains("number", StringComparison.Ordinal)
            || normalized.Contains("digit", StringComparison.Ordinal)
            || normalized.Contains("bool", StringComparison.Ordinal)
            || normalized.Contains("literal", StringComparison.Ordinal)
            || normalized.Contains("constant", StringComparison.Ordinal)
            || normalized.Contains("truefalse", StringComparison.Ordinal)
            || normalized == "null"
            || normalized == "position")
        {
            return palette.Number;
        }
        if (normalized.Contains("method", StringComparison.Ordinal)
            || normalized.Contains("function", StringComparison.Ordinal)
            || normalized.Contains("command", StringComparison.Ordinal)
            || normalized.Contains("entity", StringComparison.Ordinal))
        {
            return palette.Function;
        }
        if (normalized.Contains("namespace", StringComparison.Ordinal)
            || normalized.Contains("type", StringComparison.Ordinal))
        {
            return palette.Type;
        }
        if (normalized.Contains("link", StringComparison.Ordinal))
        {
            return palette.Link;
        }
        if (normalized.Contains("heading", StringComparison.Ordinal)
            || normalized.Contains("header", StringComparison.Ordinal))
        {
            return palette.Keyword;
        }
        if (normalized.Contains("file", StringComparison.Ordinal)
            || normalized.Contains("image", StringComparison.Ordinal))
        {
            return palette.String;
        }
        return palette.Foreground;
    }

    private sealed record EditorPalette(
        string Foreground,
        string Comment,
        string Keyword,
        string Tag,
        string Type,
        string Property,
        string String,
        string Number,
        string Function,
        string Link,
        string Added,
        string Error);
}
