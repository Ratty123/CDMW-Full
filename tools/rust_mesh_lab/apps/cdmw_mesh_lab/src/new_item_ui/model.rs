//! Presentation-only contract. Item rules and output authority remain in CDMW.

use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

pub const PROTOCOL: &str = "cdmw_new_item_ui_v1";
pub const MAX_MESSAGE_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct Node {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub revision: u64,
    pub kind: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub tooltip: String,
    #[serde(default = "enabled_default")]
    pub enabled: bool,
    #[serde(default)]
    pub props: Value,
    #[serde(default)]
    pub children: Vec<Node>,
    #[serde(default)]
    pub cell: Option<[i32; 4]>,
    #[serde(default)]
    pub stretch: u32,
    #[serde(default)]
    pub slot: String,
}

fn enabled_default() -> bool {
    true
}

impl Node {
    pub fn text(&self, key: &str) -> &str {
        self.props[key].as_str().unwrap_or("")
    }
    pub fn flag(&self, key: &str) -> bool {
        self.props[key].as_bool().unwrap_or(false)
    }
    pub fn number(&self, key: &str, fallback: f64) -> f64 {
        self.props[key]
            .as_f64()
            .filter(|v| v.is_finite())
            .unwrap_or(fallback)
    }
    pub fn array(&self, key: &str) -> &[Value] {
        self.props[key]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default()
    }
    pub fn flexible(&self) -> bool {
        self.stretch > 0
            || matches!(
                self.kind.as_str(),
                "viewport" | "table" | "scroll" | "image_crop"
            )
            || self.children.iter().any(Self::flexible)
            || self.kind == "text" && self.flag("multiline")
    }
    pub fn embedded_nodes(&self) -> Vec<Node> {
        fn collect(value: &Value, nodes: &mut Vec<Node>) {
            match value {
                Value::Object(fields)
                    if fields.contains_key("kind") && fields.contains_key("props") =>
                {
                    if let Ok(node) = serde_json::from_value(value.clone()) {
                        nodes.push(node);
                    }
                }
                Value::Object(fields) => {
                    for value in fields.values() {
                        collect(value, nodes);
                    }
                }
                Value::Array(values) => {
                    for value in values {
                        collect(value, nodes);
                    }
                }
                _ => {}
            }
        }
        let mut nodes = Vec::new();
        collect(&self.props, &mut nodes);
        nodes
    }

    pub fn find_revision(&self, id: &str) -> Option<u64> {
        if self.id == id {
            return Some(self.revision);
        }
        self.children
            .iter()
            .find_map(|child| child.find_revision(id))
            .or_else(|| {
                self.embedded_nodes()
                    .iter()
                    .find_map(|child| child.find_revision(id))
            })
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct State {
    pub protocol: String,
    pub session: String,
    pub generation: u64,
    #[serde(default)]
    pub last_request: u64,
    #[serde(default)]
    pub native_modal: bool,
    pub root: Node,
    #[serde(default)]
    pub dialogs: Vec<Node>,
    #[serde(default)]
    pub theme: Value,
    #[serde(default)]
    pub strings: BTreeMap<String, String>,
    #[serde(default)]
    pub assets: BTreeMap<String, ImageAsset>,
    #[serde(default)]
    pub unsupported: Vec<Value>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ImageAsset {
    pub png_hex: String,
    pub width: u32,
    pub height: u32,
}

impl State {
    pub fn validate(&self, session: &str) -> Result<()> {
        if self.protocol != PROTOCOL || self.session != session || self.session.len() > 64 {
            bail!("The New Item presentation session does not match.");
        }
        let mut count = 0;
        fn check(node: &Node, depth: usize, count: &mut usize) -> Result<()> {
            *count += 1;
            if depth > 64 || *count > 12_000 {
                bail!("Presentation control-tree limit exceeded.");
            }
            for child in &node.children {
                check(child, depth + 1, count)?;
            }
            for child in node.embedded_nodes() {
                check(&child, depth + 1, count)?;
            }
            Ok(())
        }
        check(&self.root, 0, &mut count)?;
        for dialog in &self.dialogs {
            check(dialog, 0, &mut count)?;
        }
        if self.assets.len() > 256
            || self.assets.values().any(|image| {
                image.width > 1024 || image.height > 1024 || image.png_hex.len() > 8 * 1024 * 1024
            })
        {
            bail!("Presentation image limit exceeded.");
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct Input {
    pub control: String,
    pub revision: u64,
    pub action: &'static str,
    pub value: Value,
}

impl Input {
    pub fn new(node: &Node, action: &'static str, value: Value) -> Self {
        Self {
            control: node.id.clone(),
            revision: node.revision,
            action,
            value,
        }
    }
    pub fn edit_key(&self) -> String {
        if self.action == "cell" {
            format!(
                "{}:{}:{}",
                self.control, self.value["path"], self.value["column"]
            )
        } else {
            self.control.clone()
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct ControlRect {
    pub id: String,
    pub kind: String,
    pub label: String,
    pub rect: [f32; 4],
    pub clip: [f32; 4],
    pub enabled: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct Portal {
    pub id: String,
    pub rect: [f32; 4],
    pub clip: [f32; 4],
    pub occlusions: Vec<[f32; 4]>,
}

pub fn rect_array(rect: egui::Rect) -> [f32; 4] {
    [rect.min.x, rect.min.y, rect.width(), rect.height()]
}
