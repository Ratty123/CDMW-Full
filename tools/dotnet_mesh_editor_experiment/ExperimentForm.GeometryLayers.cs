using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private sealed record GeometryLayerRow(
        string LayerId,
        string Name,
        int[] SubmeshIndices,
        bool Visible,
        bool Base,
        bool Active);

    private readonly ListView _geometryLayerList = new();
    private GroupBox? _layersSection;
    private Button? _layerPasteButton;
    private Button? _layerRenameButton;
    private Button? _layerMoveUpButton;
    private Button? _layerMoveDownButton;
    private Button? _layerDeleteButton;
    private bool _syncingGeometryLayerList;
    private long _geometryLayerRevision = -1;

    private GroupBox BuildGeometryLayersSection(TableLayoutPanel stack)
    {
        _geometryLayerList.Name = "DotNetMeshEditorGeometryLayerList";
        _geometryLayerList.AccessibleName = "Mesh geometry layers";
        _geometryLayerList.Dock = DockStyle.Top;
        _geometryLayerList.Height = 112;
        _geometryLayerList.View = View.Details;
        _geometryLayerList.HeaderStyle = ColumnHeaderStyle.None;
        _geometryLayerList.FullRowSelect = true;
        _geometryLayerList.HideSelection = false;
        _geometryLayerList.MultiSelect = false;
        _geometryLayerList.CheckBoxes = true;
        _geometryLayerList.LabelEdit = true;
        _geometryLayerList.BackColor = ThemeInputBackground;
        _geometryLayerList.ForeColor = ThemeText;
        _geometryLayerList.BorderStyle = BorderStyle.FixedSingle;
        _geometryLayerList.Columns.Add("Layer", ScaleToolPanelWidth(EditMeshToolColumnMetrics.InspectorFloor - 40));
        ApplyDarkScrollbars(_geometryLayerList);

        _geometryLayerList.SelectedIndexChanged += (_, _) =>
        {
            RefreshGeometryLayerButtonState();
            if (_syncingGeometryLayerList || SelectedGeometryLayer() is not { } layer)
            {
                return;
            }
            WriteCommandRequest("layer_activate", new Dictionary<string, object?>
            {
                ["layer_id"] = layer.LayerId,
            });
        };
        _geometryLayerList.ItemChecked += (_, eventArgs) =>
        {
            if (_syncingGeometryLayerList || eventArgs.Item.Tag is not GeometryLayerRow layer)
            {
                return;
            }
            if (layer.Base && !eventArgs.Item.Checked)
            {
                _syncingGeometryLayerList = true;
                eventArgs.Item.Checked = true;
                _syncingGeometryLayerList = false;
                _statusLabel.Text = "Base mesh is always visible.";
                return;
            }
            WriteCommandRequest("layer_visibility", new Dictionary<string, object?>
            {
                ["layer_id"] = layer.LayerId,
                ["visible"] = eventArgs.Item.Checked,
            });
        };
        _geometryLayerList.BeforeLabelEdit += (_, eventArgs) =>
        {
            if (eventArgs.Item < 0
                || eventArgs.Item >= _geometryLayerList.Items.Count
                || _geometryLayerList.Items[eventArgs.Item].Tag is not GeometryLayerRow layer
                || layer.Base)
            {
                eventArgs.CancelEdit = true;
            }
        };
        _geometryLayerList.AfterLabelEdit += (_, eventArgs) =>
        {
            if (eventArgs.CancelEdit || eventArgs.Label is null || eventArgs.Item < 0
                || eventArgs.Item >= _geometryLayerList.Items.Count
                || _geometryLayerList.Items[eventArgs.Item].Tag is not GeometryLayerRow layer)
            {
                return;
            }
            var name = eventArgs.Label.Trim();
            if (name.Length == 0)
            {
                eventArgs.CancelEdit = true;
                _statusLabel.Text = "Layer name cannot be empty.";
                return;
            }
            WriteCommandRequest("layer_rename", new Dictionary<string, object?>
            {
                ["layer_id"] = layer.LayerId,
                ["name"] = name,
            });
        };

        var copyButton = StyledActionButton("Copy", () => WriteCommandRequest("copy"));
        _layerPasteButton = StyledActionButton("Paste", () => WriteCommandRequest("paste"));
        _layerRenameButton = StyledActionButton("Rename", BeginRenameGeometryLayer);
        _layerMoveUpButton = StyledActionButton("Up", () => MoveSelectedGeometryLayer(-1));
        _layerMoveDownButton = StyledActionButton("Down", () => MoveSelectedGeometryLayer(1));
        _layerDeleteButton = StyledActionButton("Delete", DeleteSelectedGeometryLayer);
        _layerPasteButton.Enabled = false;

        var section = AddHelpSection(
            stack,
            "Layers",
            "Base mesh is always included. Only the active layer can be edited; visible inactive layers are reference geometry.",
            out _,
            _geometryLayerList,
            ButtonRow(copyButton, _layerPasteButton, _layerRenameButton),
            ButtonRow(_layerMoveUpButton, _layerMoveDownButton, _layerDeleteButton));
        RefreshGeometryLayerButtonState();
        return section;
    }

    private GeometryLayerRow? SelectedGeometryLayer() =>
        _geometryLayerList.SelectedItems.Count == 1
            ? _geometryLayerList.SelectedItems[0].Tag as GeometryLayerRow
            : null;

    private void RefreshGeometryLayerButtonState()
    {
        var selected = SelectedGeometryLayer();
        var editable = selected is not null && !selected.Base;
        if (_layerRenameButton is not null) _layerRenameButton.Enabled = editable;
        if (_layerMoveUpButton is not null)
        {
            _layerMoveUpButton.Enabled = editable && _geometryLayerList.SelectedIndices[0] > 1;
        }
        if (_layerMoveDownButton is not null)
        {
            _layerMoveDownButton.Enabled = editable
                && _geometryLayerList.SelectedIndices[0] < _geometryLayerList.Items.Count - 1;
        }
        if (_layerDeleteButton is not null) _layerDeleteButton.Enabled = editable;
    }

    private void BeginRenameGeometryLayer()
    {
        if (SelectedGeometryLayer() is { Base: false })
        {
            _geometryLayerList.SelectedItems[0].BeginEdit();
        }
    }

    private void MoveSelectedGeometryLayer(int direction)
    {
        if (SelectedGeometryLayer() is not { Base: false } layer)
        {
            return;
        }
        WriteCommandRequest("layer_move", new Dictionary<string, object?>
        {
            ["layer_id"] = layer.LayerId,
            ["direction"] = direction,
        });
    }

    private void DeleteSelectedGeometryLayer()
    {
        if (SelectedGeometryLayer() is not { Base: false } layer)
        {
            return;
        }
        WriteCommandRequest("layer_delete", new Dictionary<string, object?>
        {
            ["layer_id"] = layer.LayerId,
        });
    }

    private void ApplyGeometryLayerState(JsonElement root)
    {
        if (!root.TryGetProperty("geometry_layers", out var state)
            || state.ValueKind != JsonValueKind.Object)
        {
            return;
        }
        var revision = Math.Max(0, JsonLongValue(state, "revision"));
        if (revision < _geometryLayerRevision)
        {
            return;
        }
        var rows = new List<GeometryLayerRow>();
        if (state.TryGetProperty("layers", out var layers) && layers.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in layers.EnumerateArray())
            {
                var layerId = JsonString(item, "layer_id").Trim();
                if (layerId.Length == 0)
                {
                    continue;
                }
                rows.Add(new GeometryLayerRow(
                    layerId,
                    JsonString(item, "name").Trim() is { Length: > 0 } name ? name : layerId,
                    GeometryLayerIntArray(item, "submesh_indices"),
                    JsonBoolean(item, "visible"),
                    JsonBoolean(item, "base"),
                    JsonBoolean(item, "active")));
            }
        }
        if (rows.Count == 0)
        {
            rows.Add(new GeometryLayerRow(
                "base",
                "Base mesh",
                Enumerable.Range(0, Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count)).ToArray(),
                true,
                true,
                true));
        }

        _geometryLayerRevision = revision;
        _syncingGeometryLayerList = true;
        _geometryLayerList.BeginUpdate();
        try
        {
            _geometryLayerList.Items.Clear();
            foreach (var row in rows)
            {
                var item = new ListViewItem(row.Name)
                {
                    Name = row.LayerId,
                    Tag = row,
                    Checked = row.Visible,
                    Selected = row.Active,
                };
                _geometryLayerList.Items.Add(item);
            }
        }
        finally
        {
            _geometryLayerList.EndUpdate();
            _syncingGeometryLayerList = false;
        }
        if (_layerPasteButton is not null)
        {
            _layerPasteButton.Enabled = JsonBoolean(state, "clipboard_ready");
        }
        RefreshGeometryLayerButtonState();
        var activeIndices = rows.FirstOrDefault(row => row.Active)?.SubmeshIndices ?? rows[0].SubmeshIndices;
        var hiddenIndices = rows.Where(row => !row.Visible).SelectMany(row => row.SubmeshIndices);
        _viewport.SetGeometryLayerState(activeIndices, hiddenIndices);
    }

    private static int[] GeometryLayerIntArray(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<int>();
        }
        return values.EnumerateArray()
            .Where(value => value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out _))
            .Select(value => value.GetInt32())
            .Where(index => index >= 0)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
    }
}
