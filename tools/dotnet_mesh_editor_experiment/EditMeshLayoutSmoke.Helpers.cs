using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal static partial class EditMeshLayoutSmoke
{
    private static T RequiredControl<T>(Control root, string name) where T : Control
    {
        var control = root.Controls.Find(name, searchAllChildren: true).OfType<T>().SingleOrDefault();
        return control ?? throw new InvalidOperationException($"Morph wizard control {name} is missing or duplicated.");
    }

    private static void InvokeButton(Button button)
    {
        var onClick = typeof(Button).GetMethod(
            "OnClick",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("WinForms Button.OnClick is unavailable.");
        onClick.Invoke(button, new object[] { EventArgs.Empty });
    }

    private static string RequiredValue(string[] args, string name)
    {
        var index = Array.FindIndex(
            args,
            arg => string.Equals(arg, name, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]))
        {
            throw new ArgumentException($"{name} requires an output path.");
        }
        return Path.GetFullPath(args[index + 1]);
    }

    private static TableLayoutPanel CreateStack(string name)
    {
        var stack = new TableLayoutPanel
        {
            Name = name,
            ColumnCount = 1,
            RowCount = 0,
            AutoSize = true,
        };
        stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        return stack;
    }

    private static GroupBox NewSection(string name)
    {
        return new GroupBox
        {
            Name = name.Replace(" ", string.Empty).Replace("&", string.Empty),
            Text = name,
        };
    }

    private static void AddRow(TableLayoutPanel stack, Control control)
    {
        var row = stack.RowCount;
        stack.RowCount = row + 1;
        stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        EditMeshLayoutContracts.MoveControl(control, stack, 0, row, DockStyle.Top);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
