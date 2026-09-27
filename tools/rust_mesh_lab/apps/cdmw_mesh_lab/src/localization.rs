//! Host-owned interface translations. IDs, commands and editable values remain
//! English/source data; translation happens only at presentation boundaries.

use egui::{Context, Id};
use serde_json::Value;
use std::{cell::RefCell, collections::BTreeMap, sync::Arc};

#[derive(Default)]
struct Catalog {
    entries: BTreeMap<String, String>,
    templates: Vec<(Vec<String>, Vec<String>, String)>,
}

fn fields(source: &str) -> (Vec<String>, Vec<String>) {
    let mut literals = Vec::new();
    let mut names = Vec::new();
    let mut remaining = source;
    while let Some(start) = remaining.find("{value_") {
        let Some(end) = remaining[start..].find('}') else {
            break;
        };
        literals.push(remaining[..start].to_owned());
        names.push(remaining[start..=start + end].to_owned());
        remaining = &remaining[start + end + 1..];
    }
    literals.push(remaining.to_owned());
    (literals, names)
}

impl Catalog {
    fn from_payload(payload: &Value) -> Self {
        let mut result = Self::default();
        if let Some(entries) = payload.as_object() {
            for (key, value) in entries {
                if let Some(value) = value.as_str().or_else(|| value["other"].as_str()) {
                    result.entries.insert(key.clone(), value.to_owned());
                }
            }
        }
        for (source, translated) in &result.entries {
            let (literals, names) = fields(source);
            // Reject generic formatting/units. They must not consume arbitrary
            // labels or file names merely because their suffix happens to fit.
            if names.is_empty()
                || literals
                    .iter()
                    .map(|s| s.chars().filter(|c| c.is_alphabetic()).count())
                    .sum::<usize>()
                    < 3
            {
                continue;
            }
            result.templates.push((literals, names, translated.clone()));
        }
        result.templates.sort_by_key(|(literals, _, _)| {
            std::cmp::Reverse(literals.iter().map(String::len).sum::<usize>())
        });
        result
    }

    fn translate(&self, source: &str) -> String {
        if let Some(value) = self.entries.get(source) {
            return value.clone();
        }
        for (literals, names, translated) in &self.templates {
            let Some(mut rest) = source.strip_prefix(&literals[0]) else {
                continue;
            };
            let mut values = Vec::new();
            let mut matched = true;
            for (index, literal) in literals.iter().enumerate().skip(1) {
                let end = if index == names.len() {
                    rest.strip_suffix(literal).map(str::len)
                } else if literal.is_empty() {
                    None
                } else {
                    rest.find(literal)
                };
                let Some(end) = end.filter(|end| *end > 0) else {
                    matched = false;
                    break;
                };
                values.push(&rest[..end]);
                rest = &rest[end + literal.len()..];
            }
            if matched && rest.is_empty() && values.len() == names.len() {
                // Substitute the template in one pass. Values may themselves
                // contain braces, and must never become another substitution.
                let mut output = String::new();
                let mut rest = translated.as_str();
                while let Some(start) = rest.find("{value_") {
                    output.push_str(&rest[..start]);
                    let Some(end) = rest[start..].find('}') else {
                        break;
                    };
                    let name = &rest[start..=start + end];
                    if let Some(index) = names.iter().position(|field| field == name) {
                        output.push_str(values[index]);
                    } else {
                        output.push_str(name);
                    }
                    rest = &rest[start + end + 1..];
                }
                output.push_str(rest);
                return output;
            }
        }
        source.to_owned()
    }
}

thread_local! {
    static ACTIVE: RefCell<Option<Arc<Catalog>>> = const { RefCell::new(None) };
}

fn catalog_id() -> Id {
    Id::new("cdmw-interface-catalog")
}

pub(super) fn configure(context: &Context, theme: &Value) {
    let catalog = Arc::new(Catalog::from_payload(&theme["translations"]));
    context.data_mut(|data| data.insert_temp(catalog_id(), catalog));
}

pub(super) struct Scope(Option<Arc<Catalog>>);

impl Drop for Scope {
    fn drop(&mut self) {
        ACTIVE.with(|current| {
            current.replace(self.0.take());
        });
    }
}

/// A scope isolates contexts and test threads, and restores a parent's catalog
/// when an embedded surface finishes drawing.
pub(super) fn enter(context: &Context) -> Scope {
    let catalog = context.data(|data| data.get_temp::<Arc<Catalog>>(catalog_id()));
    Scope(ACTIVE.with(|current| current.replace(catalog)))
}

pub(super) fn tr(source: impl AsRef<str>) -> String {
    ACTIVE.with(|current| {
        current.borrow().as_ref().map_or_else(
            || source.as_ref().to_owned(),
            |catalog| catalog.translate(source.as_ref()),
        )
    })
}

pub(super) fn combo(source: impl AsRef<str>) -> egui::ComboBox {
    egui::ComboBox::new(source.as_ref(), tr(source.as_ref()))
}

pub(super) fn collapsing(source: impl AsRef<str>) -> egui::CollapsingHeader {
    egui::CollapsingHeader::new(tr(source.as_ref())).id_salt(source.as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn native_localization_preserves_dynamic_values_and_context_ownership() {
        let context = Context::default();
        configure(
            &context,
            &json!({"translations": {
                "Mesh Editor": "メッシュエディター",
                "Apply to {value_0} vertices": "{value_0} 個の頂点に適用",
                "{value_0} {value_1}s": "{value_0} {value_1}",
            }}),
        );
        {
            let _scope = enter(&context);
            assert_eq!(tr("Mesh Editor"), "メッシュエディター");
            assert_eq!(tr("Apply to 32 vertices"), "32 個の頂点に適用");
            assert_eq!(tr("Unlisted Widgets"), "Unlisted Widgets");
            assert_eq!(tr("character/model.pac"), "character/model.pac");
            {
                let _other = enter(&Context::default());
                assert_eq!(tr("Mesh Editor"), "Mesh Editor");
            }
            assert_eq!(tr("Mesh Editor"), "メッシュエディター");
        }
        assert_eq!(tr("Mesh Editor"), "Mesh Editor");
        configure(&context, &json!({"translations": {}}));
        let _scope = enter(&context);
        assert_eq!(tr("Mesh Editor"), "Mesh Editor");
    }
}
