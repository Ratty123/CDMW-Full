#![forbid(unsafe_code)]

use anyhow::{Context, Result, ensure};
use serde::Serialize;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

const RUST_SCHEMA: &str = "cdmw_rust_mesh_editor_control_contract_v2";

#[derive(Debug, Clone, Serialize)]
struct ContractRow<'a> {
    key: &'a str,
    surface: &'a str,
    disposition: &'a str,
    availability: &'a str,
    host_owned: bool,
    reason: &'a str,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RuntimeRouteKind {
    LocalTool,
    LocalPage,
    LocalState,
    UiAction,
    ShadowCommand,
    ShadowTopology,
    HostAction,
    PointerGesture,
    ReadOnlyState,
    Unavailable,
    Unregistered,
}

impl RuntimeRouteKind {
    const fn label(self) -> &'static str {
        match self {
            Self::LocalTool => "local_tool",
            Self::LocalPage => "local_page",
            Self::LocalState => "local_state",
            Self::UiAction => "ui_action",
            Self::ShadowCommand => "typed_shadow_command",
            Self::ShadowTopology => "typed_shadow_topology",
            Self::HostAction => "host_action",
            Self::PointerGesture => "pointer_gesture",
            Self::ReadOnlyState => "read_only_state",
            Self::Unavailable => "deliberately_unavailable",
            Self::Unregistered => "unregistered",
        }
    }

    const fn dispatches(self) -> bool {
        !matches!(
            self,
            Self::ReadOnlyState | Self::Unavailable | Self::Unregistered
        )
    }
}

#[derive(Debug, Clone, Copy)]
struct RuntimeRoute {
    kind: RuntimeRouteKind,
    target: &'static str,
}

impl RuntimeRoute {
    const fn new(kind: RuntimeRouteKind, target: &'static str) -> Self {
        Self { kind, target }
    }

    fn source_binding_verified(self) -> bool {
        match self.kind {
            RuntimeRouteKind::LocalTool => {
                all_anchors_present(CDMW_UI_SOURCE, self.target)
                    && all_anchors_present(MAIN_SOURCE, self.target)
            }
            RuntimeRouteKind::LocalPage => {
                all_anchors_present(CDMW_UI_SOURCE, self.target)
                    && MAIN_SOURCE.contains("enum CdmwRailPage")
            }
            RuntimeRouteKind::LocalState => self.target.split('+').all(|target| {
                CDMW_UI_SOURCE.contains(&format!("self.{target}"))
                    || CDMW_UI_SOURCE.contains(&format!("&mut self.{target}"))
            }),
            RuntimeRouteKind::UiAction | RuntimeRouteKind::HostAction => {
                all_anchors_present(CDMW_UI_SOURCE, self.target)
                    && all_anchors_present(MAIN_SOURCE, self.target)
            }
            RuntimeRouteKind::ShadowCommand => {
                self.target
                    .split('+')
                    .all(|command| CDMW_UI_SOURCE.contains(&format!("command: \"{command}\"")))
                    && MAIN_SOURCE.contains("UiAction::CdmwCommand")
                    && MAIN_SOURCE.contains("submit_cdmw_command(command, arguments, label)")
            }
            RuntimeRouteKind::ShadowTopology => {
                self.target
                    .split('+')
                    .all(|action| CDMW_UI_SOURCE.contains(&format!("\"{action}\"")))
                    && MAIN_SOURCE.contains("UiAction::CdmwTopology")
                    && MAIN_SOURCE.contains("submit_cdmw_topology(action, label, params)")
            }
            RuntimeRouteKind::PointerGesture => {
                all_anchors_present(MAIN_SOURCE, self.target)
                    && CDMW_UI_SOURCE.contains("draw_cdmw_viewport(root_ui)")
            }
            RuntimeRouteKind::ReadOnlyState => all_anchors_present(CDMW_UI_SOURCE, self.target),
            RuntimeRouteKind::Unavailable => CDMW_UI_SOURCE.contains(&format!(
                "add_enabled(false, Button::new(\"{}\"))",
                self.target
            )),
            RuntimeRouteKind::Unregistered => false,
        }
    }
}

fn all_anchors_present(source: &str, anchors: &str) -> bool {
    anchors
        .split('+')
        .all(|anchor| !anchor.is_empty() && source.contains(anchor))
}

// These are the actual integrated UI and action-dispatch sources compiled into this
// executable. A contract route is not accepted merely because it was listed below:
// its concrete control/action/command anchor must also exist in the runtime source.
const CDMW_UI_SOURCE: &str = include_str!("cdmw_ui.rs");
const MAIN_SOURCE: &str = include_str!("main.rs");

const PRODUCT_ROW_FIELDS: [&str; 14] = [
    "key",
    "surface",
    "owner",
    "route",
    "disposition",
    "availability",
    "reason",
    "evidence_category",
    "host_owned",
    "control_type",
    "control_name",
    "control_text",
    "currently_visible",
    "currently_enabled",
];

pub fn write_control_contract(path: &Path) -> Result<()> {
    let parent = path
        .parent()
        .context("control contract output has no parent directory")?;
    fs::create_dir_all(parent)?;
    let product_core_rows = parse_product_core_rows()?;
    let required_surfaces = [
        "session",
        "selection",
        "tools",
        "topology",
        "parts_layers",
        "morph_refit",
        "material_colour",
        "camera_display",
        "import_output_export",
        "exact_free_edit",
    ];
    let invalid_disabled_rows = product_core_rows
        .iter()
        .filter(|row| row.disposition == "deliberately_disabled" && row.reason.trim().is_empty())
        .map(|row| row.key)
        .collect::<Vec<_>>();
    let runtime_routes = product_core_rows
        .iter()
        .map(|row| runtime_route(row.key))
        .collect::<Vec<_>>();
    let missing_runtime_routes = product_core_rows
        .iter()
        .zip(&runtime_routes)
        .filter(|(_, route)| route.kind == RuntimeRouteKind::Unregistered)
        .map(|(row, _)| row.key)
        .collect::<Vec<_>>();
    let unverified_runtime_routes = product_core_rows
        .iter()
        .zip(&runtime_routes)
        .filter(|(_, route)| !route.source_binding_verified())
        .map(|(row, _)| row.key)
        .collect::<Vec<_>>();
    let compiled_anchor_rows = product_compiled_anchor_rows()?;
    let invalid_product_anchor_rows = compiled_anchor_rows
        .iter()
        .filter(|row| row.get("source_binding_verified").and_then(Value::as_bool) != Some(true))
        .filter_map(|row| row.get("key").and_then(Value::as_str))
        .collect::<Vec<_>>();
    let mut rows = product_core_report_rows(&product_core_rows, &runtime_routes);
    rows.extend(compiled_anchor_rows.iter().cloned());
    let keys = rows
        .iter()
        .filter_map(|row| row.get("key").and_then(Value::as_str))
        .collect::<BTreeSet<_>>();
    let surfaces = rows
        .iter()
        .filter_map(|row| row.get("surface").and_then(Value::as_str))
        .collect::<BTreeSet<_>>();
    let runtime_control_ids = rows
        .iter()
        .filter_map(|row| row.get("rust_control_id").and_then(Value::as_str))
        .collect::<BTreeSet<_>>();
    let missing_surfaces = required_surfaces
        .iter()
        .filter(|surface| !surfaces.contains(**surface))
        .copied()
        .collect::<Vec<_>>();
    let preview_contract = crate::cdmw_preview::control_contract();
    let preview_ok = preview_contract.get("ok").and_then(Value::as_bool) == Some(true);
    let ok = keys.len() == rows.len()
        && runtime_control_ids.len() == rows.len()
        && missing_surfaces.is_empty()
        && invalid_disabled_rows.is_empty()
        && missing_runtime_routes.is_empty()
        && unverified_runtime_routes.is_empty()
        && invalid_product_anchor_rows.is_empty()
        && preview_ok;
    let report = json!({
        "schema": RUST_SCHEMA,
        "renderer": "wgpu_d3d12_rust",
        "edit_backend": "cdmw_rust_mesh_0.1",
        "proof_class": "headless_rust_control_manifest",
        "visual_proof": false,
        "ok": ok,
        "row_count": rows.len(),
        "required_surfaces": required_surfaces,
        "missing_surfaces": missing_surfaces,
        "duplicate_keys": if keys.len() == rows.len() { Vec::<&str>::new() } else { vec!["duplicate"] },
        "duplicate_runtime_control_ids": if runtime_control_ids.len() == rows.len() { Vec::<&str>::new() } else { vec!["duplicate"] },
        "invalid_disabled_rows": invalid_disabled_rows,
        "missing_runtime_routes": missing_runtime_routes,
        "unverified_runtime_routes": unverified_runtime_routes,
        "invalid_product_anchor_rows": invalid_product_anchor_rows,
        "runtime_route_registry": "compiled_rust_integrated_ui_v2",
        "preview_contract": preview_contract,
        "rows": rows,
        "product_contract": {
            "fields": PRODUCT_ROW_FIELDS,
            "source": "compiled Rust UI and dispatch anchors",
            "require_unique_row_set": true
        }
    });
    fs::write(path, serde_json::to_vec_pretty(&report)?)?;
    Ok(())
}

fn product_compiled_anchor_rows() -> Result<Vec<Value>> {
    PRODUCT_COMPILED_ANCHOR_ROWS
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| {
            let mut values = line.splitn(4, '|');
            let key = values.next().unwrap_or_default();
            let surface = values.next().unwrap_or_default();
            let ui_anchor = values.next().unwrap_or_default();
            let main_anchor = values.next().unwrap_or_default();
            ensure!(
                !key.is_empty()
                    && !surface.is_empty()
                    && !ui_anchor.is_empty()
                    && !main_anchor.is_empty(),
                "invalid Rust product control row"
            );
            let verified = CDMW_UI_SOURCE.contains(ui_anchor) && MAIN_SOURCE.contains(main_anchor);
            Ok(json!({
                "key": key,
                "surface": surface,
                "owner": "rust",
                "route": format!("compiled_anchor:{main_anchor}"),
                "disposition": "executable",
                "availability": "session",
                "reason": "",
                "evidence_category": "compiled_rust_control_contract",
                "host_owned": false,
                "control_type": "RustIntegratedControl",
                "control_name": key,
                "control_text": "",
                "currently_visible": true,
                "currently_enabled": true,
                "rust_control_id": format!("rust.integrated.anchor.{key}"),
                "rust_route": format!("compiled_anchor:{main_anchor}"),
                "rust_route_kind": "compiled_anchor",
                "rust_route_target": main_anchor,
                "rust_runtime_dispatch": true,
                "source_binding_verified": verified,
                "rust_source_binding_verified": verified,
                "rust_implementation_basis": "compiled_runtime_binding_registry_v2",
                "rust_implemented": verified,
                "rust_state_feedback": ["enabled", "disabled", "selected", "hover", "pressed", "failure_reason"],
                "ui_anchor": ui_anchor,
                "dispatch_anchor": main_anchor,
            }))
        })
        .collect()
}

fn product_core_report_rows(
    rows: &[ContractRow<'static>],
    runtime_routes: &[RuntimeRoute],
) -> Vec<Value> {
    rows.iter()
        .zip(runtime_routes)
        .map(|(row, route)| {
            let mut value = json!({
                "key": row.key,
                "surface": row.surface,
                "owner": "rust",
                "route": format!("{}:{}", route.kind.label(), route.target),
                "disposition": row.disposition,
                "availability": row.availability,
                "reason": row.reason,
                "evidence_category": "compiled_rust_control_contract",
                "host_owned": row.host_owned,
                "control_type": "RustIntegratedControl",
                "control_name": row.key,
                "control_text": "",
                "currently_visible": true,
                "currently_enabled": row.disposition == "executable"
            })
            .as_object()
            .cloned()
            .expect("fallback row object");
            add_rust_proof(&mut value, row.key, *route);
            Value::Object(value)
        })
        .collect()
}

fn add_rust_proof(row: &mut Map<String, Value>, key: &str, route: RuntimeRoute) {
    let verified = route.source_binding_verified();
    row.insert(
        "rust_control_id".to_owned(),
        json!(format!("rust.integrated.{key}")),
    );
    row.insert(
        "rust_route".to_owned(),
        json!(format!("{}:{}", route.kind.label(), route.target)),
    );
    row.insert("rust_route_kind".to_owned(), json!(route.kind.label()));
    row.insert("rust_route_target".to_owned(), json!(route.target));
    row.insert(
        "rust_runtime_dispatch".to_owned(),
        json!(route.kind.dispatches()),
    );
    row.insert("rust_source_binding_verified".to_owned(), json!(verified));
    row.insert(
        "rust_implementation_basis".to_owned(),
        json!("compiled_runtime_binding_registry_v2"),
    );
    row.insert("rust_implemented".to_owned(), json!(verified));
    row.insert(
        "rust_state_feedback".to_owned(),
        json!([
            "enabled",
            "disabled",
            "selected",
            "hover",
            "pressed",
            "failure_reason"
        ]),
    );
}

fn runtime_route(key: &str) -> RuntimeRoute {
    use RuntimeRouteKind as Kind;

    let (kind, target) = match key {
        "tool.select" => (Kind::LocalTool, "ViewportTool::Select"),
        "tool.move" => (Kind::LocalTool, "ViewportTool::Move"),
        "tool.grab" => (Kind::LocalTool, "ViewportTool::Grab"),
        "tool.smooth" => (Kind::LocalTool, "ViewportTool::Smooth"),
        "tool.inflate" => (Kind::LocalTool, "ViewportTool::Inflate"),
        "tool.pinch" => (Kind::LocalTool, "ViewportTool::Pinch"),
        "page.topology" => (Kind::LocalPage, "CdmwRailPage::Topology"),
        "page.morph_refit" => (Kind::LocalPage, "CdmwRailPage::MorphRefit"),
        "session.clear_selection" => (Kind::UiAction, "UiAction::ClearSelection"),
        "session.select_all" => (
            Kind::UiAction,
            "UiAction::SelectAllVertices+UiAction::SelectAllEdges+UiAction::SelectAllFaces",
        ),
        "session.invert" => (Kind::UiAction, "UiAction::InvertSelection"),
        "session.undo" => (Kind::UiAction, "UiAction::Undo"),
        "session.redo" => (Kind::UiAction, "UiAction::Redo"),
        "output.configure_free_edit" => (Kind::ShadowCommand, "configure_output_policy"),
        "output.export_free_edit" => (Kind::ShadowCommand, "export_free_edit"),
        "session.finish" => (Kind::HostAction, "UiAction::FinishCdmw"),
        "selection.target" => (Kind::LocalState, "selection_domain"),
        "selection.shape" => (Kind::LocalState, "selection_tool"),
        "selection.operation" => (Kind::LocalState, "selection_operation"),
        "selection.xray" => (Kind::LocalState, "selection_visible_only"),
        "selection.grow" => (Kind::UiAction, "UiAction::GrowSelection"),
        "selection.shrink" => (Kind::UiAction, "UiAction::ShrinkSelection"),
        "selection.create_part" => (Kind::ShadowTopology, "separate"),
        "transform.translate_step" => (Kind::LocalState, "transform_translate_step"),
        "transform.grab_radius" => (Kind::LocalState, "brush_radius"),
        "transform.nudge.-x" | "transform.nudge.+x" | "transform.nudge.-y"
        | "transform.nudge.+y" | "transform.nudge.-z" | "transform.nudge.+z" => {
            (Kind::UiAction, "UiAction::Nudge")
        }
        "brush.radius" => (Kind::LocalState, "brush_radius"),
        "brush.strength" => (Kind::LocalState, "brush_strength"),
        "brush.falloff" => (Kind::LocalState, "brush_falloff"),
        "topology.delete_selection" => (Kind::ShadowTopology, "delete"),
        "topology.duplicate_selection" => (Kind::ShadowTopology, "duplicate"),
        "topology.subdivide" => (Kind::ShadowTopology, "subdivide"),
        "topology.refine_smooth" => (Kind::ShadowTopology, "refine_smooth"),
        "topology.bridge" => (Kind::ShadowTopology, "bridge"),
        "topology.edge_split" => (Kind::ShadowTopology, "edge_split"),
        "topology.extrude" => (Kind::ShadowTopology, "extrude"),
        "topology.fill" => (Kind::ShadowTopology, "fill"),
        "topology.inset" => (Kind::ShadowTopology, "inset"),
        "topology.loop_cut" => (Kind::ShadowTopology, "loop_cut"),
        "topology.merge" => (Kind::ShadowTopology, "merge"),
        "topology.split" => (Kind::ShadowTopology, "split"),
        "topology.dissolve" => (Kind::ShadowTopology, "dissolve"),
        "topology.separate" => (Kind::ShadowTopology, "separate"),
        "topology.weld" => (Kind::ShadowTopology, "weld"),
        "parts.selection" | "parts.select_all" | "parts.select_none" | "parts.invert" => {
            (Kind::UiAction, "UiAction::SetPartSelection")
        }
        "parts.visibility" => (Kind::Unavailable, "Visibility"),
        "parts.duplicate" => (Kind::ShadowTopology, "duplicate"),
        "parts.delete" => (Kind::ShadowTopology, "delete"),
        "layers.list" => (Kind::ShadowCommand, "layer_activate"),
        "layers.copy" => (Kind::ShadowCommand, "layer_copy"),
        "layers.paste" => (Kind::ShadowCommand, "layer_paste"),
        "layers.rename" => (Kind::ShadowCommand, "layer_rename"),
        "layers.move_up" | "layers.move_down" => (Kind::ShadowCommand, "layer_move"),
        "layers.delete" => (Kind::ShadowCommand, "layer_delete"),
        "history.timeline" => (Kind::ReadOnlyState, "history_entries+history_cursor"),
        "morph.collapse" => (Kind::LocalPage, "CdmwRailPage::MorphRefit"),
        "morph.profile" => (Kind::ShadowCommand, "morph_activate"),
        "morph.create_profile" => (Kind::ShadowCommand, "morph_create"),
        "morph.edit_slider" => (Kind::LocalState, "cdmw_morph_definition_edit_id"),
        "morph.replace_slider_scope" => (Kind::LocalState, "cdmw_morph_replace_selection_on_edit"),
        "morph.update_slider" => (Kind::ShadowCommand, "morph_create"),
        "morph.delete_slider" => (Kind::ShadowCommand, "morph_delete_definition"),
        "morph.save_profile" => (Kind::ShadowCommand, "morph_save_profile"),
        "morph.delete_profile" => (Kind::ShadowCommand, "morph_delete_profile"),
        "morph.preset" => (Kind::ShadowCommand, "morph_apply_preset"),
        "morph.save_preset" => (Kind::ShadowCommand, "morph_save_preset"),
        "morph.delete_preset" => (Kind::ShadowCommand, "morph_delete_preset"),
        "refit.set_driver" => (Kind::ShadowCommand, "refit_set_driver"),
        "refit.bind_garment" => (Kind::ShadowCommand, "refit_bind"),
        "refit.clear" => (Kind::ShadowCommand, "refit_clear"),
        "refit.enabled" => (Kind::LocalState, "cdmw_refit_enabled"),
        "refit.mode" => (Kind::LocalState, "cdmw_refit_mode"),
        "refit.intensity" => (Kind::LocalState, "cdmw_refit_intensity"),
        "refit.clearance" => (Kind::LocalState, "cdmw_refit_clearance"),
        "refit.apply" => (Kind::ShadowCommand, "refit_configure"),
        "refit.apply_all" => (Kind::ShadowCommand, "refit_configure"),
        "morph.reset" => (Kind::ShadowCommand, "morph_reset"),
        "morph.bake" => (Kind::ShadowCommand, "morph_bake"),
        "display.mode" => (Kind::LocalState, "view_mode"),
        "display.overlay.wire_colour" => (Kind::LocalState, "overlay_wire_colour"),
        "display.overlay.vertex_colour" => (Kind::LocalState, "overlay_vertex_colour"),
        "display.overlay.selection_colour" => (Kind::LocalState, "overlay_selection_colour"),
        "display.overlay.live_selection_colour" => {
            (Kind::LocalState, "overlay_live_selection_colour")
        }
        "display.overlay.reset" => (
            Kind::LocalState,
            "overlay_wire_colour+overlay_vertex_colour+overlay_selection_colour+overlay_live_selection_colour",
        ),
        "display.overlay.wire_width" => (Kind::LocalState, "overlay_wire_width"),
        "display.overlay.vertex_size" => (Kind::LocalState, "overlay_vertex_size"),
        "display.background_colour" => (Kind::LocalState, "viewport_background_colour"),
        "display.grid_colour" => (Kind::LocalState, "viewport_grid_colour"),
        "display.colours.reset" => (
            Kind::LocalState,
            "viewport_background_colour+viewport_grid_colour",
        ),
        "camera.front" | "camera.back" | "camera.top" | "camera.left" | "camera.right"
        | "camera.bottom" => (Kind::UiAction, "UiAction::StandardView"),
        "camera.yaw_minus_15" | "camera.yaw_plus_15" => (Kind::UiAction, "UiAction::OrbitYaw"),
        "camera.fit" => (Kind::UiAction, "UiAction::FrameAll"),
        "camera.orbit" => (Kind::UiAction, "UiAction::OrbitMode"),
        "viewport.pointer_surface" => (
            Kind::PointerGesture,
            "ViewportPointerEvent+capture_viewport_pointer_event",
        ),
        "material_colour.unavailable" => (Kind::Unavailable, "Material Colour"),
        "import.open_package" => (Kind::HostAction, "UiAction::ChooseCdmwImportPackage"),
        "policy.exact_free_edit" => (Kind::ShadowCommand, "configure_output_policy"),
        _ => (Kind::Unregistered, ""),
    };
    RuntimeRoute::new(kind, target)
}

fn parse_product_core_rows() -> Result<Vec<ContractRow<'static>>> {
    PRODUCT_CORE_ROWS
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| {
            let mut values = line.splitn(6, '|');
            let key = values.next().unwrap_or_default();
            let surface = values.next().unwrap_or_default();
            let disposition = values.next().unwrap_or_default();
            let availability = values.next().unwrap_or_default();
            let host_owned = values.next().unwrap_or_default() == "true";
            let reason = values.next().unwrap_or_default();
            ensure!(
                !key.is_empty() && !surface.is_empty(),
                "invalid control contract row"
            );
            Ok(ContractRow {
                key,
                surface,
                disposition,
                availability,
                host_owned,
                reason,
            })
        })
        .collect()
}

// Rust-owned product controls. No external renderer contract is loaded to
// generate, compare, or validate this inventory.
const PRODUCT_CORE_ROWS: &str = r#"
tool.select|tools|executable|session|false|
tool.move|tools|executable|session|false|
tool.grab|tools|executable|session|false|
tool.smooth|tools|executable|session|false|
tool.inflate|tools|executable|session|false|
tool.pinch|tools|executable|session|false|
page.topology|topology|executable|session|false|
page.morph_refit|morph_refit|executable|session|false|
session.clear_selection|session|executable|session|false|
session.select_all|session|executable|session|false|
session.invert|session|executable|session|false|
session.undo|session|executable|history|false|
session.redo|session|executable|history|false|
output.configure_free_edit|import_output_export|executable|session|false|
output.export_free_edit|import_output_export|deliberately_disabled|free_edit_only|false|Export is enabled only after a Free Edit OBJ destination is proven.
session.finish|session|executable|host_owned|true|
selection.target|selection|executable|session|false|
selection.shape|selection|executable|session|false|
selection.operation|selection|executable|session|false|
selection.xray|selection|executable|session|false|
selection.grow|selection|executable|session|false|
selection.shrink|selection|executable|session|false|
selection.create_part|selection|deliberately_disabled|free_edit_faces_only|false|Create Part is unavailable because the exact PAC writer cannot add a protected submesh record.
transform.translate_step|tools|executable|session|false|
transform.grab_radius|tools|executable|session|false|
transform.nudge.-x|tools|executable|session|false|
transform.nudge.+x|tools|executable|session|false|
transform.nudge.-y|tools|executable|session|false|
transform.nudge.+y|tools|executable|session|false|
transform.nudge.-z|tools|executable|session|false|
transform.nudge.+z|tools|executable|session|false|
brush.radius|tools|executable|session|false|
brush.strength|tools|executable|session|false|
brush.falloff|tools|executable|session|false|
topology.delete_selection|topology|executable|session|false|
topology.duplicate_selection|topology|deliberately_disabled|free_edit_only|false|Duplicate Selection is unavailable because the exact PAC writer cannot add protected geometry records.
topology.subdivide|topology|deliberately_disabled|free_edit_only|false|Subdivide is unavailable because derived PAC vertices cannot preserve protected bytes.
topology.refine_smooth|topology|deliberately_disabled|free_edit_only|false|Refine Smooth is unavailable because derived PAC vertices cannot preserve protected bytes.
topology.bridge|topology|deliberately_disabled|free_edit_only|false|Bridge has no exact protected-record writeback route.
topology.edge_split|topology|deliberately_disabled|free_edit_only|false|Edge Split has no exact protected-record writeback route.
topology.extrude|topology|deliberately_disabled|free_edit_only|false|Extrude has no exact protected-record writeback route.
topology.fill|topology|deliberately_disabled|free_edit_only|false|Fill has no exact protected-record writeback route.
topology.inset|topology|deliberately_disabled|free_edit_only|false|Inset has no exact protected-record writeback route.
topology.loop_cut|topology|deliberately_disabled|free_edit_only|false|Loop Cut derives vertices whose protected bytes cannot be derived.
topology.merge|topology|deliberately_disabled|free_edit_only|false|Merge has no exact protected-record writeback route.
topology.split|topology|deliberately_disabled|free_edit_only|false|Split has no exact protected-record writeback route.
topology.dissolve|topology|deliberately_disabled|free_edit_only|false|Dissolve has no exact protected-record writeback route.
topology.separate|topology|deliberately_disabled|free_edit_only|false|Separate has no exact protected-record writeback route.
topology.weld|topology|deliberately_disabled|free_edit_only|false|Weld has no exact protected-record writeback route.
parts.selection|parts_layers|executable|session|false|
parts.select_all|parts_layers|executable|session|false|
parts.select_none|parts_layers|executable|session|false|
parts.invert|parts_layers|executable|session|false|
parts.visibility|parts_layers|deliberately_disabled|not_stored_in_exact_output|false|Part visibility editing has no stored output authority in direct authoring.
parts.duplicate|parts_layers|deliberately_disabled|free_edit_only|false|Duplicate Part is unavailable because the exact PAC writer cannot add a protected submesh record.
parts.delete|parts_layers|deliberately_disabled|free_edit_only|false|Delete Part is unavailable because the exact PAC writer cannot remove a protected submesh record.
layers.list|parts_layers|executable|session|false|
layers.copy|parts_layers|deliberately_disabled|free_edit_only|false|Copy is unavailable because copied geometry has no exact PAC writeback route.
layers.paste|parts_layers|deliberately_disabled|free_edit_only|false|Paste is unavailable because copied geometry has no exact PAC writeback route.
layers.rename|parts_layers|executable|non_base_layer|false|
layers.move_up|parts_layers|executable|non_base_layer|false|
layers.move_down|parts_layers|executable|non_base_layer|false|
layers.delete|parts_layers|deliberately_disabled|free_edit_non_base_layer|false|Layer Delete is unavailable because changed topology has no exact PAC writeback route.
history.timeline|session|executable|read_only_view|false|
morph.collapse|morph_refit|executable|session|false|
morph.profile|morph_refit|executable|session|false|
morph.create_profile|morph_refit|executable|session|false|
morph.edit_slider|morph_refit|executable|baked_active_profile|false|
morph.replace_slider_scope|morph_refit|executable|editing_slider_and_selection|false|
morph.update_slider|morph_refit|executable|editing_slider_baked|false|
morph.delete_slider|morph_refit|executable|baked_active_profile|false|
morph.save_profile|morph_refit|executable|active_profile|false|
morph.delete_profile|morph_refit|executable|active_profile|false|
morph.preset|morph_refit|executable|session|false|
morph.save_preset|morph_refit|executable|active_profile|false|
morph.delete_preset|morph_refit|executable|active_preset|false|
refit.set_driver|morph_refit|executable|part_selection|false|
refit.bind_garment|morph_refit|executable|driver_and_part_selection|false|
refit.clear|morph_refit|executable|session|false|
refit.enabled|morph_refit|executable|bound_garment|false|
refit.mode|morph_refit|executable|bound_garment|false|
refit.intensity|morph_refit|executable|bound_garment|false|
refit.clearance|morph_refit|executable|bound_garment|false|
refit.apply|morph_refit|executable|bound_garment|false|
refit.apply_all|morph_refit|executable|bound_garment|false|
morph.reset|morph_refit|executable|active_profile|false|
morph.bake|morph_refit|executable|unbaked_change|false|
display.mode|camera_display|executable|session|false|
display.overlay.wire_colour|camera_display|executable|session|false|
display.overlay.vertex_colour|camera_display|executable|session|false|
display.overlay.selection_colour|camera_display|executable|session|false|
display.overlay.live_selection_colour|camera_display|executable|session|false|
display.overlay.reset|camera_display|executable|session|false|
display.overlay.wire_width|camera_display|executable|session|false|
display.overlay.vertex_size|camera_display|executable|session|false|
display.background_colour|camera_display|executable|session|false|
display.grid_colour|camera_display|executable|session|false|
display.colours.reset|camera_display|executable|session|false|
camera.front|camera_display|executable|session|false|
camera.back|camera_display|executable|session|false|
camera.top|camera_display|executable|session|false|
camera.left|camera_display|executable|session|false|
camera.right|camera_display|executable|session|false|
camera.bottom|camera_display|executable|session|false|
camera.yaw_minus_15|camera_display|executable|session|false|
camera.yaw_plus_15|camera_display|executable|session|false|
camera.fit|camera_display|executable|session|false|
camera.orbit|camera_display|executable|session|false|
viewport.pointer_surface|camera_display|executable|session|false|
material_colour.unavailable|material_colour|deliberately_disabled|not_reachable|true|Mesh Editor no longer exposes the obsolete Colour authoring section.
import.open_package|import_output_export|executable|host_owned|true|
policy.exact_free_edit|exact_free_edit|executable|session_policy|true|
"#;

// Product controls whose UI and dispatcher anchors are both verified directly.
const PRODUCT_COMPILED_ANCHOR_ROWS: &str = r#"
tool.rotate|transform|CdmwRailPage::Rotate|ViewportTool::Rotate
tool.scale|transform|CdmwRailPage::Scale|ViewportTool::Scale
transform.numeric_rotate|transform|UiAction::RotateStep|UiAction::RotateStep
transform.numeric_scale|transform|UiAction::ScaleStep|UiAction::ScaleStep
sculpt.inflate_deflate|tools|-1.0..=1.0|SculptTool::Inflate
display.deformation_heatmap|camera_display|Persistent edit colours|deformation_heatmap_enabled
topology.extrude_axis|topology|cdmw_extrude_axis|cdmw_extrude_axis
page.cleanup|cleanup|CdmwRailPage::Cleanup|Cleanup,
cleanup.remove_doubles|cleanup|"remove_doubles"|UiAction::CdmwMeshAction
cleanup.delete_loose|cleanup|"delete_loose_vertices"|UiAction::CdmwMeshAction
cleanup.compact_orphans|cleanup|"compact_orphans"|UiAction::CdmwMeshAction
cleanup.fix_winding|cleanup|"fix_winding"|UiAction::CdmwMeshAction
cleanup.fill_holes|cleanup|"fill_holes"|UiAction::CdmwMeshAction
cleanup.mirror|cleanup|"mirror"|UiAction::CdmwMeshAction
page.normals|normals|CdmwRailPage::Normals|Normals,
normals.recalculate|normals|"recalculate_normals"|UiAction::CdmwMeshAction
normals.tangents|normals|"generate_tangents"|UiAction::CdmwMeshAction
normals.flip|normals|"flip_normals"|UiAction::CdmwMeshAction
normals.sharpen|normals|"sharpen_normals"|UiAction::CdmwMeshAction
normals.soften|normals|"soften_normals"|UiAction::CdmwMeshAction
normals.weighted|normals|"weighted_normals"|UiAction::CdmwMeshAction
normals.copy_source|normals|"copy_normals"|UiAction::CdmwMeshAction
page.uv|uv|CdmwRailPage::Uv|Uv,
uv.transform|uv|"uv_transform"|UiAction::CdmwMeshAction
uv.auto_unwrap|uv|"auto_uv"|UiAction::CdmwMeshAction
uv.pixel_snap|uv|"snap_pixels"|UiAction::CdmwMeshAction
page.rig_weights|rig_weights|CdmwRailPage::RigWeights|RigWeights,
rig.select_bone|rig_weights|"rig_select_bone"|UiAction::CdmwCommand
rig.adjust_weight|rig_weights|"rig_adjust_weight"|UiAction::CdmwCommand
rig.normalize_weights|rig_weights|"rig_normalize_weights"|UiAction::CdmwCommand
rig.transfer_weights|rig_weights|"rig_transfer_weights"|UiAction::CdmwCommand
topology.loop_cut_parameters|topology|cdmw_loop_cut_count|cdmw_loop_cut_count
topology.refine_parameters|topology|cdmw_refine_strength|cdmw_refine_strength
topology.weld_distance|topology|cdmw_weld_distance|cdmw_weld_distance
output.host_handoff|import_output_export|Game / Mod output|UiAction::FinishCdmw
"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rust_product_core_has_unique_rows_and_required_disabled_reasons() {
        let rows = parse_product_core_rows().expect("rows");
        assert!(rows.len() >= 100);
        assert_eq!(
            rows.iter()
                .map(|row| row.key)
                .collect::<BTreeSet<_>>()
                .len(),
            rows.len()
        );
        assert!(
            rows.iter()
                .filter(|row| row.disposition == "deliberately_disabled")
                .all(|row| !row.reason.is_empty())
        );
    }

    #[test]
    fn every_live_row_has_a_source_backed_concrete_runtime_route() {
        let rows = parse_product_core_rows().expect("rows");
        for row in rows {
            let route = runtime_route(row.key);
            assert_ne!(
                route.kind,
                RuntimeRouteKind::Unregistered,
                "{} has no runtime route",
                row.key
            );
            assert!(!route.target.is_empty(), "{} has an empty route", row.key);
            assert!(
                route.source_binding_verified(),
                "{} route {}:{} is not bound in the compiled integrated UI/dispatcher",
                row.key,
                route.kind.label(),
                route.target
            );
            if row.disposition == "executable" {
                assert_ne!(
                    route.kind,
                    RuntimeRouteKind::Unavailable,
                    "{} is executable but unavailable in Rust",
                    row.key
                );
            }
        }
    }

    #[test]
    fn only_permanently_unavailable_rows_lack_a_runtime_dispatch() {
        let rows = parse_product_core_rows().expect("rows");
        let unavailable = rows
            .iter()
            .filter(|row| runtime_route(row.key).kind == RuntimeRouteKind::Unavailable)
            .map(|row| row.key)
            .collect::<BTreeSet<_>>();
        assert_eq!(
            unavailable,
            BTreeSet::from(["material_colour.unavailable", "parts.visibility"])
        );

        for row in rows {
            let route = runtime_route(row.key);
            if !unavailable.contains(row.key) && route.kind != RuntimeRouteKind::ReadOnlyState {
                assert!(route.kind.dispatches(), "{} must dispatch", row.key);
            }
        }
    }

    #[test]
    fn product_compiled_anchor_rows_are_source_bound() {
        let rows = product_compiled_anchor_rows().expect("Rust product anchor rows");
        assert!(rows.len() >= 30);
        let keys = rows
            .iter()
            .filter_map(|row| row.get("key").and_then(Value::as_str))
            .collect::<BTreeSet<_>>();
        assert_eq!(keys.len(), rows.len());
        assert!(keys.contains("tool.rotate"));
        assert!(keys.contains("cleanup.remove_doubles"));
        assert!(keys.contains("normals.weighted"));
        assert!(keys.contains("uv.auto_unwrap"));
        assert!(keys.contains("rig.transfer_weights"));
        assert!(rows.iter().all(|row| {
            row.get("source_binding_verified").and_then(Value::as_bool) == Some(true)
        }));
    }
}
