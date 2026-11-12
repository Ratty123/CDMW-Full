//! Tool groups that unlock as their back end becomes ready (P4 V4).
//!
//! The editor shows at once; CDMW prepares the authoring session, the morph
//! data and the rest behind it. Until a group is ready CDMW says so with a
//! `tool_groups` message, and the group's controls stay visible and focusable:
//! using one shows the reason and does nothing. Nothing is queued for later.

use crate::CdmwRailPage;
use serde_json::Value;
use std::collections::BTreeMap;

/// The groups CDMW names, in the order the rail shows them.
pub(crate) const TOOL_GROUPS: [&str; 6] =
    ["select", "transform", "sculpt", "mesh_data", "rig", "morph"];

/// The group a rail page belongs to.
pub(crate) const fn group_of(page: CdmwRailPage) -> &'static str {
    match page {
        CdmwRailPage::Select => "select",
        CdmwRailPage::Move | CdmwRailPage::Rotate | CdmwRailPage::Scale => "transform",
        CdmwRailPage::Grab
        | CdmwRailPage::Bend
        | CdmwRailPage::Smooth
        | CdmwRailPage::Inflate
        | CdmwRailPage::Pinch => "sculpt",
        CdmwRailPage::VertexParameters
        | CdmwRailPage::Topology
        | CdmwRailPage::Cleanup
        | CdmwRailPage::Normals
        | CdmwRailPage::Uv
        | CdmwRailPage::Cloth
        | CdmwRailPage::Jiggle => "mesh_data",
        CdmwRailPage::RigWeights => "rig",
        CdmwRailPage::MorphRefit => "morph",
    }
}

/// Which groups are still preparing, and why. Empty: everything is ready, as
/// for an editor opened the old way.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub(crate) struct ToolGroupState {
    preparing: BTreeMap<String, String>,
}

impl ToolGroupState {
    /// Read `{"groups": {"transform": {"ready": false, "reason": "..."}, ...}}`.
    /// A group CDMW does not name is ready.
    pub(crate) fn from_host(payload: &Value) -> Self {
        let mut preparing = BTreeMap::new();
        if let Some(groups) = payload.get("groups").and_then(Value::as_object) {
            for (name, group) in groups {
                if !TOOL_GROUPS.contains(&name.as_str()) {
                    continue;
                }
                if group.get("ready").and_then(Value::as_bool) == Some(false) {
                    let reason = group
                        .get("reason")
                        .and_then(Value::as_str)
                        .filter(|reason| !reason.trim().is_empty())
                        .unwrap_or("Preparing");
                    preparing.insert(name.clone(), reason.to_owned());
                }
            }
        }
        Self { preparing }
    }

    /// The reason a page cannot be used yet, if its group is preparing.
    pub(crate) fn refusal(&self, page: CdmwRailPage) -> Option<&str> {
        self.preparing.get(group_of(page)).map(String::as_str)
    }

    pub(crate) fn is_preparing(&self, group: &str) -> bool {
        self.preparing.contains_key(group)
    }

    pub(crate) fn all_ready(&self) -> bool {
        self.preparing.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_group_is_ready_unless_cdmw_says_it_is_preparing() {
        let state = ToolGroupState::from_host(&json!({"groups": {
            "transform": {"ready": false, "reason": "The edit session is being prepared."},
            "morph": {"ready": false},
            "select": {"ready": true},
            "unknown": {"ready": false},
        }}));
        assert_eq!(
            state.refusal(CdmwRailPage::Rotate),
            Some("The edit session is being prepared.")
        );
        assert_eq!(state.refusal(CdmwRailPage::MorphRefit), Some("Preparing"));
        assert_eq!(state.refusal(CdmwRailPage::Select), None);
        assert_eq!(state.refusal(CdmwRailPage::Grab), None);
        assert!(!state.all_ready() && state.is_preparing("morph"));
        assert!(ToolGroupState::from_host(&json!({})).all_ready());
    }

    #[test]
    fn every_rail_page_has_a_named_group() {
        for page in [
            CdmwRailPage::Select,
            CdmwRailPage::Move,
            CdmwRailPage::Grab,
            CdmwRailPage::VertexParameters,
            CdmwRailPage::Jiggle,
            CdmwRailPage::RigWeights,
            CdmwRailPage::MorphRefit,
        ] {
            assert!(TOOL_GROUPS.contains(&group_of(page)));
        }
    }
}
