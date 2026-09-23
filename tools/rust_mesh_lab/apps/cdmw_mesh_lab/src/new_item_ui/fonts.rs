//! Native Windows fonts, including the glyph coverage used by the host's UI.
//! Bytes are loaded once per helper, never once per state or frame.

use egui::{FontData, FontDefinitions, FontFamily};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, OnceLock},
};

fn available_fonts() -> &'static BTreeMap<String, Arc<FontData>> {
    static FONTS: OnceLock<BTreeMap<String, Arc<FontData>>> = OnceLock::new();
    FONTS.get_or_init(|| {
        let Some(windows) = std::env::var_os("WINDIR") else {
            return BTreeMap::new();
        };
        let root = PathBuf::from(windows).join("Fonts");
        [
            "segoeui.ttf",
            "arial.ttf",
            "tahoma.ttf",
            "calibri.ttf",
            "consola.ttf",
            "msyh.ttc",
            "msjh.ttc",
            "YuGothR.ttc",
            "malgun.ttf",
            "seguisym.ttf",
        ]
        .into_iter()
        .filter_map(|name| {
            let path = root.join(name);
            let size = std::fs::metadata(&path).ok()?.len();
            if size == 0 || size > 48 * 1024 * 1024 {
                return None;
            }
            let bytes = std::fs::read(path).ok()?;
            Some((name.to_owned(), Arc::new(FontData::from_owned(bytes))))
        })
        .collect()
    })
}

pub fn configure(context: &egui::Context, theme: &Value) {
    let family = theme["font_family"]
        .as_str()
        .unwrap_or("Segoe UI")
        .to_lowercase();
    let language = theme["language"].as_str().unwrap_or("en");
    let key = (family.clone(), language.to_owned());
    let cache_id = egui::Id::new("new-item-font-configuration");
    if context
        .data(|data| data.get_temp::<(String, String)>(cache_id))
        .as_ref()
        == Some(&key)
    {
        return;
    }
    let mut fonts = FontDefinitions::default();
    let available = available_fonts();
    fonts.font_data.extend(
        available
            .iter()
            .map(|(name, font)| (name.clone(), font.clone())),
    );
    let primary = if family.contains("arial") {
        "arial.ttf"
    } else if family.contains("tahoma") {
        "tahoma.ttf"
    } else if family.contains("calibri") {
        "calibri.ttf"
    } else if family.contains("consolas") {
        "consola.ttf"
    } else {
        "segoeui.ttf"
    };
    let cjk = match language {
        "ja" => ["YuGothR.ttc", "msyh.ttc", "msjh.ttc", "malgun.ttf"],
        "ko" => ["malgun.ttf", "msyh.ttc", "YuGothR.ttc", "msjh.ttc"],
        "zh-Hant" => ["msjh.ttc", "msyh.ttc", "YuGothR.ttc", "malgun.ttf"],
        _ => ["msyh.ttc", "YuGothR.ttc", "msjh.ttc", "malgun.ttf"],
    };
    for family in [FontFamily::Proportional, FontFamily::Monospace] {
        let list = fonts.families.entry(family.clone()).or_default();
        let chosen = if family == FontFamily::Monospace {
            "consola.ttf"
        } else {
            primary
        };
        if available.contains_key(chosen) {
            list.insert(0, chosen.to_owned());
        }
        for name in cjk.into_iter().chain(["seguisym.ttf"]) {
            if available.contains_key(name) {
                list.push(name.to_owned());
            }
        }
    }
    context.set_fonts(fonts);
    context.data_mut(|data| data.insert_temp(cache_id, key));
}
