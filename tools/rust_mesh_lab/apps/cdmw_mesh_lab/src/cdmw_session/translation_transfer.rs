//! Host translation catalogues larger than one control line.
//!
//! The host splits the catalogue's compact JSON text into ordered
//! `theme_translations_part` lines, then sends a `theme_update` that names the
//! transfer instead of carrying the catalogue. Only a complete, contiguous
//! transfer whose joined text matches the declared length and SHA-256 becomes
//! that update's translations. A gap, an overlap, a stale request or an update
//! that interrupts a transfer is a protocol error.

use super::{SessionError, required_u64, sha256_upper};
use serde_json::Value;

pub(super) const PART_EVENT: &str = "theme_translations_part";
pub(super) const CAPABILITY: &str = "ui_translation_parts_v1";
/// The host's `RUST_UI_TRANSLATION_MAX_BYTES` and `RUST_UI_TRANSLATION_MAX_ENTRIES`.
pub(super) const MAX_CATALOG_BYTES: u64 = 4 * 1024 * 1024;
const MAX_CATALOG_ENTRIES: usize = 10_000;
const MAX_PARTS: u64 = 64;
const PLURAL_CATEGORIES: [&str; 6] = ["zero", "one", "two", "few", "many", "other"];

fn invalid(message: &str) -> SessionError {
    SessionError::InvalidPayload(message.to_owned())
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Transfer {
    part_count: u64,
    byte_length: u64,
    sha256: String,
}

impl Transfer {
    fn read(value: &Value) -> Result<Self, SessionError> {
        let transfer = Self {
            part_count: required_u64(value, "part_count")?,
            byte_length: required_u64(value, "byte_length")?,
            sha256: value
                .get("sha256")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_ascii_uppercase(),
        };
        if !(1..=MAX_PARTS).contains(&transfer.part_count)
            || !(1..=MAX_CATALOG_BYTES).contains(&transfer.byte_length)
            || transfer.part_count > transfer.byte_length
            || transfer.sha256.len() != 64
            || !transfer.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
        {
            return Err(invalid("translation transfer size, part count or SHA-256 is invalid"));
        }
        Ok(transfer)
    }
}

#[derive(Debug)]
struct Pending {
    request_id: u64,
    transfer: Transfer,
    received: u64,
    text: String,
}

#[derive(Debug, Default)]
pub(super) struct TranslationTransfers {
    pending: Option<Pending>,
    completed_request_id: u64,
}

impl TranslationTransfers {
    /// Part 0 opens a transfer; every later part must follow it in order.
    pub(super) fn accept_part(&mut self, value: &Value) -> Result<(), SessionError> {
        let request_id = required_u64(value, "request_id")?;
        let index = required_u64(value, "part_index")?;
        let transfer = Transfer::read(value)?;
        let data = value
            .get("data")
            .and_then(Value::as_str)
            .filter(|data| !data.is_empty())
            .ok_or_else(|| invalid("translation part carries no text"))?;
        if index == 0 {
            if self.pending.is_some() {
                return Err(invalid(
                    "a translation transfer started before the previous one completed",
                ));
            }
            if request_id <= self.completed_request_id {
                return Err(invalid("translation transfer request is stale"));
            }
            let mut text = String::new();
            text.try_reserve_exact(usize::try_from(transfer.byte_length).unwrap_or(usize::MAX))
                .map_err(|_| invalid("translation transfer exceeds available memory"))?;
            self.pending = Some(Pending {
                request_id,
                transfer: transfer.clone(),
                received: 0,
                text,
            });
        }
        let pending = self
            .pending
            .as_mut()
            .filter(|pending| {
                pending.request_id == request_id
                    && pending.transfer == transfer
                    && pending.received == index
            })
            .ok_or_else(|| invalid("translation part is out of sequence"))?;
        if index >= transfer.part_count
            || (pending.text.len() + data.len()) as u64 > transfer.byte_length
        {
            return Err(invalid("translation parts exceed their declared transfer"));
        }
        pending.text.push_str(data);
        pending.received += 1;
        Ok(())
    }

    /// Check a theme update's translations, first completing the transfer it names.
    pub(super) fn resolve_update(&mut self, value: &mut Value) -> Result<(), SessionError> {
        let Some(descriptor) = value.get("translations_transfer") else {
            if self.pending.is_some() {
                return Err(invalid("a theme update interrupted a translation transfer"));
            }
            return match value.get("payload").and_then(|payload| payload.get("translations")) {
                Some(translations) => validate_catalog(translations).map(drop),
                None => Ok(()),
            };
        };
        if descriptor.as_object().is_none_or(|fields| fields.len() != 4) {
            return Err(invalid("translation transfer descriptor has unexpected fields"));
        }
        let request_id = required_u64(value, "request_id")?;
        let transfer = Transfer::read(descriptor)?;
        let entry_count = required_u64(descriptor, "entry_count")?;
        let pending = self
            .pending
            .take()
            .filter(|pending| pending.request_id == request_id && pending.transfer == transfer)
            .ok_or_else(|| invalid("theme update names a translation transfer that was not sent"))?;
        if pending.received != transfer.part_count
            || pending.text.len() as u64 != transfer.byte_length
            || sha256_upper(pending.text.as_bytes()) != transfer.sha256
        {
            return Err(invalid(
                "translation transfer is incomplete or its SHA-256 does not match",
            ));
        }
        let translations: Value = serde_json::from_str(&pending.text)?;
        if validate_catalog(&translations)? as u64 != entry_count {
            return Err(invalid("translation transfer entry count does not match"));
        }
        let payload = value
            .get_mut("payload")
            .and_then(Value::as_object_mut)
            .filter(|payload| !payload.contains_key("translations"))
            .ok_or_else(|| invalid("theme update carries its translations twice"))?;
        payload.insert("translations".to_owned(), translations);
        self.completed_request_id = request_id;
        Ok(())
    }
}

/// Check the catalogue a session manifest's theme carries, under the same bounds.
pub(super) fn validate_manifest_theme(theme: &Value) -> Result<(), SessionError> {
    let Some(translations) = theme.get("translations") else {
        return Ok(());
    };
    validate_catalog(translations)?;
    if serde_json::to_vec(translations)?.len() as u64 > MAX_CATALOG_BYTES {
        return Err(invalid("manifest translations exceed 4 MiB"));
    }
    Ok(())
}

/// Accept source-text keys mapped to text or to CLDR plural forms. Returns the entry count.
fn validate_catalog(translations: &Value) -> Result<usize, SessionError> {
    let entries = translations
        .as_object()
        .filter(|entries| entries.len() <= MAX_CATALOG_ENTRIES)
        .ok_or_else(|| invalid("translations must be an object of at most 10,000 entries"))?;
    let valid = entries.iter().all(|(source, entry)| {
        !source.is_empty()
            && match entry {
                Value::String(_) => true,
                Value::Object(forms) => {
                    !forms.is_empty()
                        && forms.iter().all(|(category, form)| {
                            PLURAL_CATEGORIES.contains(&category.as_str()) && form.is_string()
                        })
                }
                _ => false,
            }
    });
    if !valid {
        return Err(invalid("a translation entry is not text or plural forms"));
    }
    Ok(entries.len())
}

#[cfg(test)]
mod tests {
    use super::super::{CdmwBridge, HostEvent, MAX_CONTROL_LINE_BYTES, PROTOCOL};
    use super::*;
    use serde_json::{Map, json};
    use tempfile::tempdir;

    fn fresh_bridge() -> (tempfile::TempDir, CdmwBridge) {
        let root = tempdir().expect("root");
        let bridge = CdmwBridge::for_test(root.path().to_path_buf(), "session", 3, 4);
        (root, bridge)
    }

    fn message(event: &str, request_id: u64) -> Value {
        json!({
            "event": event,
            "protocol": PROTOCOL,
            "session_id": "session",
            "request_id": request_id,
            "base_revision": 4,
            "process_generation": 3,
        })
    }

    /// Quotes, backslashes, templates, plural forms and four scripts, past 1 MiB.
    fn large_catalog() -> Value {
        let samples = [
            "Редактор сетки «{value_0}»",
            "メッシュエディター \"引用\" \\ パス",
            "Kafelek – zażółć gęślą jaźń",
            "网格编辑器：{value_0} 个顶点",
        ];
        let mut entries = Map::new();
        for index in 0..6_000 {
            let key = format!("Source label {index} with \"quotes\" and \\ backslash {{value_0}}");
            let text = samples[index % samples.len()].repeat(4);
            let entry = if index % 97 == 1 {
                json!({"one": text, "few": text, "many": text, "other": text})
            } else {
                Value::String(text)
            };
            entries.insert(key, entry);
        }
        let catalog = Value::Object(entries);
        assert!(serde_json::to_vec(&catalog).unwrap().len() > 1 << 20);
        catalog
    }

    /// Split like the host: whole characters, so a slice may end inside an escape.
    fn transfer(request_id: u64, text: &str, slice_bytes: usize) -> (Vec<Value>, Value) {
        let mut fragments = Vec::new();
        let mut start = 0;
        for (offset, character) in text.char_indices() {
            if offset + character.len_utf8() - start > slice_bytes {
                fragments.push(&text[start..offset]);
                start = offset;
            }
        }
        fragments.push(&text[start..]);
        let digest = sha256_upper(text.as_bytes());
        let parts = fragments
            .iter()
            .enumerate()
            .map(|(index, fragment)| {
                let mut part = message(PART_EVENT, request_id);
                part["part_index"] = json!(index);
                part["part_count"] = json!(fragments.len());
                part["byte_length"] = json!(text.len());
                part["sha256"] = json!(digest);
                part["data"] = json!(fragment);
                part
            })
            .collect();
        let descriptor = json!({
            "part_count": fragments.len(),
            "byte_length": text.len(),
            "sha256": digest,
        });
        (parts, descriptor)
    }

    fn update(request_id: u64, descriptor: &Value, entry_count: usize) -> Value {
        let mut update = message("theme_update", request_id);
        update["payload"] = json!({"schema": "cdmw_ui_theme_v1", "language": "ru", "theme": "nord"});
        update["translations_transfer"] = descriptor.clone();
        update["translations_transfer"]["entry_count"] = json!(entry_count);
        update
    }

    fn is_fatal(event: Option<HostEvent>) -> bool {
        matches!(event, Some(HostEvent::Fatal(_)))
    }

    #[test]
    fn native_localization_parts_deliver_a_large_catalog_as_one_theme_update() {
        let (_root, mut bridge) = fresh_bridge();
        let catalog = large_catalog();
        let text = serde_json::to_string(&catalog).unwrap();
        let (parts, descriptor) = transfer(9, &text, 200 * 1024);
        assert!(parts.len() > 5);
        for part in parts {
            assert!(serde_json::to_vec(&part).unwrap().len() < MAX_CONTROL_LINE_BYTES);
            assert!(bridge.decode_host_message(part).is_none());
        }
        let entry_count = catalog.as_object().unwrap().len();
        let Some(HostEvent::Theme(theme)) =
            bridge.decode_host_message(update(9, &descriptor, entry_count))
        else {
            panic!("a complete transfer must become one theme update");
        };
        assert_eq!(theme["translations"], catalog);
        assert_eq!(theme["theme"], "nord");

        let context = egui::Context::default();
        crate::localization::configure(&context, &theme);
        let _scope = crate::localization::enter(&context);
        assert_eq!(
            crate::localization::tr("Source label 2 with \"quotes\" and \\ backslash {value_0}"),
            "Kafelek – zażółć gęślą jaźń".repeat(4),
        );
        assert_eq!(
            crate::localization::tr("Source label 4 with \"quotes\" and \\ backslash 12"),
            "Редактор сетки «12»".repeat(4),
        );

        // A later language switch replaces the catalogue the same way.
        let smaller = json!({"Mesh Editor": "メッシュエディター"});
        let (parts, descriptor) = transfer(10, &smaller.to_string(), 8);
        for part in parts {
            assert!(bridge.decode_host_message(part).is_none());
        }
        let Some(HostEvent::Theme(theme)) = bridge.decode_host_message(update(10, &descriptor, 1))
        else {
            panic!("the second transfer must apply");
        };
        assert_eq!(theme["translations"], smaller);
    }

    #[test]
    fn native_localization_parts_reject_gaps_overlaps_and_mismatched_transfers() {
        let text = json!({"Mesh Editor": "Редактор сетки", "Undo": "Отменить"}).to_string();
        let (parts, descriptor) = transfer(5, &text, 16);
        assert!(parts.len() >= 3);

        let (_root, mut bridge) = fresh_bridge();
        assert!(is_fatal(bridge.decode_host_message(parts[1].clone())), "a transfer starts at part 0");

        let (_root, mut bridge) = fresh_bridge();
        assert!(bridge.decode_host_message(parts[0].clone()).is_none());
        assert!(is_fatal(bridge.decode_host_message(parts[2].clone())), "gap");

        let (_root, mut bridge) = fresh_bridge();
        assert!(bridge.decode_host_message(parts[0].clone()).is_none());
        assert!(is_fatal(bridge.decode_host_message(parts[0].clone())), "overlap");

        let (_root, mut bridge) = fresh_bridge();
        let mut changed = parts[1].clone();
        changed["sha256"] = json!("0".repeat(64));
        assert!(bridge.decode_host_message(parts[0].clone()).is_none());
        assert!(is_fatal(bridge.decode_host_message(changed)), "descriptor changed mid-transfer");

        let (_root, mut bridge) = fresh_bridge();
        let mut oversized = parts[0].clone();
        oversized["data"] = json!(text.clone() + " ");
        assert!(is_fatal(bridge.decode_host_message(oversized)), "more text than declared");

        for (field, bad) in [
            ("part_count", json!(0)),
            ("part_count", json!(MAX_PARTS + 1)),
            ("byte_length", json!(MAX_CATALOG_BYTES + 1)),
            ("sha256", json!("not-a-digest")),
            ("data", json!("")),
        ] {
            let (_root, mut bridge) = fresh_bridge();
            let mut invalid = parts[0].clone();
            invalid[field] = bad;
            assert!(is_fatal(bridge.decode_host_message(invalid)), "{field}");
        }

        let complete = |bridge: &mut CdmwBridge| {
            for part in &parts {
                assert!(bridge.decode_host_message(part.clone()).is_none());
            }
        };
        let (_root, mut bridge) = fresh_bridge();
        complete(&mut bridge);
        let mut wrong_digest = update(5, &descriptor, 2);
        wrong_digest["translations_transfer"]["sha256"] = json!("A".repeat(64));
        assert!(is_fatal(bridge.decode_host_message(wrong_digest)), "digest");

        let (_root, mut bridge) = fresh_bridge();
        complete(&mut bridge);
        assert!(is_fatal(bridge.decode_host_message(update(5, &descriptor, 3))), "entry count");

        let (_root, mut bridge) = fresh_bridge();
        complete(&mut bridge);
        let mut extra = update(5, &descriptor, 2);
        extra["translations_transfer"]["schema"] = json!("other");
        assert!(is_fatal(bridge.decode_host_message(extra)), "descriptor field");

        let (_root, mut bridge) = fresh_bridge();
        complete(&mut bridge);
        let mut twice = update(5, &descriptor, 2);
        twice["payload"]["translations"] = json!({});
        assert!(is_fatal(bridge.decode_host_message(twice)), "translations in two forms");

        let malformed = json!({"Mesh Editor": 7}).to_string();
        let (malformed_parts, malformed_descriptor) = transfer(6, &malformed, 1024);
        let (_root, mut bridge) = fresh_bridge();
        assert!(bridge.decode_host_message(malformed_parts[0].clone()).is_none());
        assert!(
            is_fatal(bridge.decode_host_message(update(6, &malformed_descriptor, 1))),
            "entry shape"
        );
    }

    #[test]
    fn native_localization_parts_reject_stale_foreign_and_interleaved_updates() {
        let text = json!({"Mesh Editor": "Редактор сетки", "Undo": "Отменить"}).to_string();
        let (parts, descriptor) = transfer(5, &text, 16);

        for (field, stale) in [
            ("process_generation", json!(2)),
            ("session_id", json!("previous-session")),
            ("protocol", json!("cdmw_rust_mesh_editor_protocol_v0")),
        ] {
            let (_root, mut bridge) = fresh_bridge();
            let mut foreign = parts[0].clone();
            foreign[field] = stale;
            assert!(is_fatal(bridge.decode_host_message(foreign)), "{field}");
        }

        // An update must follow its own complete transfer.
        let (_root, mut bridge) = fresh_bridge();
        assert!(bridge.decode_host_message(parts[0].clone()).is_none());
        assert!(is_fatal(bridge.decode_host_message(update(5, &descriptor, 2))), "incomplete");

        let (_root, mut bridge) = fresh_bridge();
        assert!(bridge.decode_host_message(parts[0].clone()).is_none());
        let mut inline = message("theme_update", 6);
        inline["payload"] = json!({"theme": "nord", "translations": {}});
        assert!(is_fatal(bridge.decode_host_message(inline)), "inline update mid-transfer");

        let (_root, mut bridge) = fresh_bridge();
        assert!(bridge.decode_host_message(parts[0].clone()).is_none());
        let (newer, _) = transfer(6, &text, 16);
        assert!(is_fatal(bridge.decode_host_message(newer[0].clone())), "racing transfer");

        let (_root, mut bridge) = fresh_bridge();
        for part in &parts {
            assert!(bridge.decode_host_message(part.clone()).is_none());
        }
        assert!(is_fatal(bridge.decode_host_message(update(4, &descriptor, 2))), "request id");

        let (_root, mut bridge) = fresh_bridge();
        assert!(is_fatal(bridge.decode_host_message(update(5, &descriptor, 2))), "never sent");

        // Other host events may interleave; a completed request cannot be replayed.
        let (_root, mut bridge) = fresh_bridge();
        for part in &parts {
            assert!(bridge.decode_host_message(part.clone()).is_none());
            assert!(matches!(
                bridge.decode_host_message(message("focus_request", 0)),
                Some(HostEvent::Focus)
            ));
        }
        assert!(matches!(
            bridge.decode_host_message(update(5, &descriptor, 2)),
            Some(HostEvent::Theme(_))
        ));
        assert!(is_fatal(bridge.decode_host_message(parts[0].clone())), "replayed transfer");
    }

    #[test]
    fn native_localization_inline_updates_still_apply_and_are_shape_checked() {
        let mut inline = message("theme_update", 2);
        inline["payload"] = json!({"theme": "nord", "translations": {
            "Mesh Editor": "Редактор сетки",
            "{value_0} vertices": {
                "one": "{value_0} вершина", "few": "{value_0} вершины", "other": "{value_0} вершин"
            },
        }});
        let (_root, mut bridge) = fresh_bridge();
        let Some(HostEvent::Theme(theme)) = bridge.decode_host_message(inline.clone()) else {
            panic!("an inline catalogue still applies");
        };
        assert_eq!(theme["translations"]["Mesh Editor"], "Редактор сетки");
        for bad in [
            json!([]),
            json!({"Mesh Editor": null}),
            json!({"": "empty source"}),
            json!({"{value_0} vertices": {"several": "{value_0} вершин"}}),
            json!({"{value_0} vertices": {}}),
        ] {
            let (_root, mut bridge) = fresh_bridge();
            let mut invalid = inline.clone();
            invalid["payload"]["translations"] = bad;
            assert!(is_fatal(bridge.decode_host_message(invalid)));
        }
    }

    #[test]
    fn native_localization_manifest_catalog_is_bounded_and_shape_checked() {
        assert!(validate_manifest_theme(&json!({"translations": large_catalog()})).is_ok());
        assert!(validate_manifest_theme(&json!({"theme": "nord"})).is_ok());
        assert!(validate_manifest_theme(&json!({"translations": {"Undo": 1}})).is_err());
        let mut huge = Map::new();
        for index in 0..5 {
            huge.insert(format!("Label {index}"), json!("x".repeat(1 << 20)));
        }
        assert!(validate_manifest_theme(&json!({"translations": huge})).is_err());
    }
}
