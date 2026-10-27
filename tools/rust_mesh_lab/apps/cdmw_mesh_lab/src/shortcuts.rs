//! Rebindable Mesh Editor keyboard shortcuts.
//!
//! Defaults follow Blender where this editor has the same tool. The host stores
//! only overrides of these defaults: a missing ID keeps its default, an empty
//! list unbinds it, and IDs this build does not know are kept for newer helpers.
//! Display labels live in `cdmw_ui::shortcuts`, which the catalogue scanner reads;
//! key names here stay untranslated.

use std::collections::BTreeMap;

use serde_json::{Map, Value};

pub(crate) const MAX_CHORDS: usize = 2;
pub(crate) const MAX_OVERRIDES: usize = 256;
const MAX_ID_LENGTH: usize = 64;
const MAX_CHORD_LENGTH: usize = 32;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) enum NumpadKey {
    Digit(u8),
    Decimal,
    Plus,
    Minus,
    Multiply,
    Divide,
    Enter,
}

impl NumpadKey {
    fn name(self) -> String {
        match self {
            Self::Digit(digit) => format!("Num{digit}"),
            Self::Decimal => "NumDecimal".to_owned(),
            Self::Plus => "NumPlus".to_owned(),
            Self::Minus => "NumMinus".to_owned(),
            Self::Multiply => "NumMultiply".to_owned(),
            Self::Divide => "NumDivide".to_owned(),
            Self::Enter => "NumEnter".to_owned(),
        }
    }

    fn from_name(name: &str) -> Option<Self> {
        Some(match name {
            "NumDecimal" => Self::Decimal,
            "NumPlus" => Self::Plus,
            "NumMinus" => Self::Minus,
            "NumMultiply" => Self::Multiply,
            "NumDivide" => Self::Divide,
            "NumEnter" => Self::Enter,
            _ => {
                let digit = name.strip_prefix("Num")?.parse::<u8>().ok()?;
                return (digit <= 9).then_some(Self::Digit(digit));
            }
        })
    }

    /// The numpad key a raw window key code names, independent of Num Lock.
    pub(crate) fn from_key_code(code: winit::keyboard::KeyCode) -> Option<Self> {
        use winit::keyboard::KeyCode as Code;
        Some(match code {
            Code::Numpad0 => Self::Digit(0),
            Code::Numpad1 => Self::Digit(1),
            Code::Numpad2 => Self::Digit(2),
            Code::Numpad3 => Self::Digit(3),
            Code::Numpad4 => Self::Digit(4),
            Code::Numpad5 => Self::Digit(5),
            Code::Numpad6 => Self::Digit(6),
            Code::Numpad7 => Self::Digit(7),
            Code::Numpad8 => Self::Digit(8),
            Code::Numpad9 => Self::Digit(9),
            Code::NumpadDecimal | Code::NumpadComma => Self::Decimal,
            Code::NumpadAdd => Self::Plus,
            Code::NumpadSubtract => Self::Minus,
            Code::NumpadMultiply | Code::NumpadStar => Self::Multiply,
            Code::NumpadDivide => Self::Divide,
            Code::NumpadEnter => Self::Enter,
            _ => return None,
        })
    }
}

/// egui reports numpad digits as top-row digits. The window loop records each
/// numpad press under the egui key it produced, and the dispatcher pairs them.
/// Like egui-winit, this prefers the key's text and falls back to its position.
pub(crate) fn numpad_egui_key(
    numpad: NumpadKey,
    logical: &winit::keyboard::Key,
) -> Option<egui::Key> {
    egui_key_for_winit_key(logical).or(match numpad {
        NumpadKey::Digit(digit) => egui::Key::from_name(&digit.to_string()),
        NumpadKey::Plus => Some(egui::Key::Plus),
        NumpadKey::Minus => Some(egui::Key::Minus),
        NumpadKey::Divide => Some(egui::Key::Slash),
        NumpadKey::Enter => Some(egui::Key::Enter),
        NumpadKey::Decimal | NumpadKey::Multiply => None,
    })
}

fn egui_key_for_winit_key(key: &winit::keyboard::Key) -> Option<egui::Key> {
    use winit::keyboard::{Key, NamedKey};
    match key {
        Key::Character(text) => egui::Key::from_name(text),
        Key::Named(named) => match named {
            NamedKey::ArrowDown => Some(egui::Key::ArrowDown),
            NamedKey::ArrowLeft => Some(egui::Key::ArrowLeft),
            NamedKey::ArrowRight => Some(egui::Key::ArrowRight),
            NamedKey::ArrowUp => Some(egui::Key::ArrowUp),
            NamedKey::End => Some(egui::Key::End),
            NamedKey::Home => Some(egui::Key::Home),
            NamedKey::PageDown => Some(egui::Key::PageDown),
            NamedKey::PageUp => Some(egui::Key::PageUp),
            NamedKey::Insert => Some(egui::Key::Insert),
            NamedKey::Delete => Some(egui::Key::Delete),
            NamedKey::Enter => Some(egui::Key::Enter),
            _ => None,
        },
        _ => None,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) enum ShortcutKey {
    Key(egui::Key),
    Numpad(NumpadKey),
}

impl ShortcutKey {
    fn name(self) -> String {
        match self {
            Self::Key(key) => key.name().to_owned(),
            Self::Numpad(key) => key.name(),
        }
    }

    fn from_name(name: &str) -> Option<Self> {
        if let Some(key) = NumpadKey::from_name(name) {
            return Some(Self::Numpad(key));
        }
        // egui also accepts its own "Numpad1" spellings; reserve those for numpad keys.
        if name.starts_with("Numpad") {
            return None;
        }
        egui::Key::from_name(name).map(Self::Key)
    }

    /// Keys a shortcut may never take: they cancel, edit text, or move focus.
    fn reserved(self) -> bool {
        matches!(
            self,
            Self::Key(
                egui::Key::Escape
                    | egui::Key::Tab
                    | egui::Key::Backspace
                    | egui::Key::Enter
                    | egui::Key::Space
                    | egui::Key::ArrowUp
                    | egui::Key::ArrowDown
                    | egui::Key::ArrowLeft
                    | egui::Key::ArrowRight
            )
        )
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) enum ModifierKey {
    Ctrl,
    Alt,
    Shift,
}

impl ModifierKey {
    fn name(self) -> &'static str {
        match self {
            Self::Ctrl => "Ctrl",
            Self::Alt => "Alt",
            Self::Shift => "Shift",
        }
    }

    pub(crate) fn held(self, modifiers: egui::Modifiers) -> bool {
        match self {
            Self::Ctrl => modifiers.ctrl || modifiers.command,
            Self::Alt => modifiers.alt,
            Self::Shift => modifiers.shift,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) struct KeyChord {
    pub(crate) ctrl: bool,
    pub(crate) alt: bool,
    pub(crate) shift: bool,
    pub(crate) key: ShortcutKey,
}

impl KeyChord {
    pub(crate) fn new(key: ShortcutKey, modifiers: egui::Modifiers) -> Self {
        Self {
            ctrl: modifiers.ctrl || modifiers.command,
            alt: modifiers.alt,
            shift: modifiers.shift,
            key,
        }
    }

    pub(crate) fn text(self) -> String {
        let mut parts = Vec::with_capacity(4);
        for (held, modifier) in [
            (self.ctrl, ModifierKey::Ctrl),
            (self.alt, ModifierKey::Alt),
            (self.shift, ModifierKey::Shift),
        ] {
            if held {
                parts.push(modifier.name().to_owned());
            }
        }
        parts.push(self.key.name());
        parts.join("+")
    }

    /// Why this chord may not be assigned, if it is reserved.
    pub(crate) fn reserved_reason(self) -> Option<ReservedChord> {
        if self.key.reserved() {
            Some(ReservedChord::EditingKey)
        } else if self.alt && self.key == ShortcutKey::Key(egui::Key::F4) {
            Some(ReservedChord::CloseWindow)
        } else if self.ctrl
            && matches!(
                self.key,
                ShortcutKey::Key(egui::Key::C | egui::Key::V | egui::Key::X)
            )
        {
            Some(ReservedChord::Clipboard)
        } else {
            None
        }
    }
}

/// Chords a shortcut may not take; `cdmw_ui::keyboard` words the reason.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ReservedChord {
    EditingKey,
    CloseWindow,
    Clipboard,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) enum Binding {
    Chord(KeyChord),
    Modifier(ModifierKey),
}

impl Binding {
    pub(crate) fn text(self) -> String {
        match self {
            Self::Chord(chord) => chord.text(),
            Self::Modifier(modifier) => modifier.name().to_owned(),
        }
    }

    pub(crate) fn parse(text: &str) -> Option<Self> {
        let text = text.trim();
        if text.is_empty() || text.len() > MAX_CHORD_LENGTH {
            return None;
        }
        let parts = text.split('+').collect::<Vec<_>>();
        let (key, modifiers) = parts.split_last()?;
        let mut chord = KeyChord {
            ctrl: false,
            alt: false,
            shift: false,
            key: ShortcutKey::Key(egui::Key::A),
        };
        for modifier in modifiers {
            let flag = match *modifier {
                "Ctrl" => &mut chord.ctrl,
                "Alt" => &mut chord.alt,
                "Shift" => &mut chord.shift,
                _ => return None,
            };
            if *flag {
                return None;
            }
            *flag = true;
        }
        if modifiers.is_empty() {
            match *key {
                "Ctrl" => return Some(Self::Modifier(ModifierKey::Ctrl)),
                "Alt" => return Some(Self::Modifier(ModifierKey::Alt)),
                "Shift" => return Some(Self::Modifier(ModifierKey::Shift)),
                _ => {}
            }
        }
        chord.key = ShortcutKey::from_name(key)?;
        Some(Self::Chord(chord))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) enum ShortcutScope {
    /// Live in both the mesh and the hair editor: view, history and plain selection.
    Global,
    Mesh,
    Hair,
}

impl ShortcutScope {
    fn overlaps(self, other: Self) -> bool {
        self == other || self == Self::Global || other == Self::Global
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) enum ShortcutGroup {
    Tools,
    Pages,
    Selection,
    SelectionModifiers,
    View,
    History,
    Editing,
    Hair,
}

pub(crate) const SHORTCUT_GROUPS: [ShortcutGroup; 8] = [
    ShortcutGroup::Tools,
    ShortcutGroup::Pages,
    ShortcutGroup::Selection,
    ShortcutGroup::SelectionModifiers,
    ShortcutGroup::View,
    ShortcutGroup::History,
    ShortcutGroup::Editing,
    ShortcutGroup::Hair,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) enum ShortcutAction {
    ToolSelect,
    ToolMove,
    ToolRotate,
    ToolScale,
    ToolGrab,
    ToolBend,
    ToolSmooth,
    ToolInflate,
    ToolPinch,
    Orbit,
    PageViewport,
    PageOutput,
    PageVertexParameters,
    PageTopology,
    PageCleanup,
    PageNormals,
    PageUv,
    PageCloth,
    PageJiggle,
    PageMorphRefit,
    TargetVertex,
    TargetEdge,
    TargetFace,
    ShapeClick,
    ShapeBrush,
    ShapeRectangle,
    ShapeLasso,
    OperationReplace,
    OperationAdd,
    OperationSubtract,
    OperationToggle,
    SelectAll,
    ClearSelection,
    InvertSelection,
    SelectLinked,
    GrowSelection,
    ShrinkSelection,
    ToggleXRay,
    ExtendModifier,
    SubtractModifier,
    FrameSelected,
    FrameAll,
    ViewFront,
    ViewBack,
    ViewRight,
    ViewLeft,
    ViewTop,
    ViewBottom,
    YawMinus15,
    YawPlus15,
    Undo,
    Redo,
    DeleteSelection,
    HairSelect,
    HairMove,
    HairDraw,
    HairErase,
    HairCut,
    HairLengthen,
    HairComb,
    HairSmooth,
    HairCurl,
    HairClump,
    HairPhysics,
    HairDeleteGuides,
}

pub(crate) struct ShortcutSpec {
    pub(crate) action: ShortcutAction,
    pub(crate) id: &'static str,
    pub(crate) group: ShortcutGroup,
    pub(crate) scope: ShortcutScope,
    pub(crate) defaults: &'static [&'static str],
}

impl ShortcutSpec {
    /// Selection modifiers take one held modifier key, not a key chord.
    pub(crate) fn takes_modifier(&self) -> bool {
        self.group == ShortcutGroup::SelectionModifiers
    }
}

const fn spec(
    action: ShortcutAction,
    id: &'static str,
    group: ShortcutGroup,
    scope: ShortcutScope,
    defaults: &'static [&'static str],
) -> ShortcutSpec {
    ShortcutSpec {
        action,
        id,
        group,
        scope,
        defaults,
    }
}

use ShortcutAction as A;
use ShortcutGroup as G;
use ShortcutScope as S;

/// Stable IDs reuse the control-contract keys where one exists.
pub(crate) const SHORTCUTS: &[ShortcutSpec] = &[
    spec(A::ToolSelect, "tool.select", G::Tools, S::Mesh, &["Q"]),
    spec(A::ToolMove, "tool.move", G::Tools, S::Mesh, &["G"]),
    spec(A::ToolRotate, "tool.rotate", G::Tools, S::Mesh, &["R"]),
    spec(A::ToolScale, "tool.scale", G::Tools, S::Mesh, &["S"]),
    spec(A::ToolGrab, "tool.grab", G::Tools, S::Mesh, &["Shift+G"]),
    spec(A::ToolBend, "tool.bend", G::Tools, S::Mesh, &["Shift+W"]),
    spec(
        A::ToolSmooth,
        "tool.smooth",
        G::Tools,
        S::Mesh,
        &["Shift+S"],
    ),
    spec(A::ToolInflate, "tool.inflate", G::Tools, S::Mesh, &["I"]),
    spec(A::ToolPinch, "tool.pinch", G::Tools, S::Mesh, &["P"]),
    spec(A::Orbit, "camera.orbit", G::Tools, S::Mesh, &[]),
    spec(A::PageViewport, "page.viewport", G::Pages, S::Mesh, &[]),
    spec(A::PageOutput, "page.output", G::Pages, S::Mesh, &[]),
    spec(
        A::PageVertexParameters,
        "page.vertex_parameters",
        G::Pages,
        S::Mesh,
        &[],
    ),
    spec(A::PageTopology, "page.topology", G::Pages, S::Mesh, &[]),
    spec(A::PageCleanup, "page.cleanup", G::Pages, S::Mesh, &[]),
    spec(A::PageNormals, "page.normals", G::Pages, S::Mesh, &[]),
    spec(A::PageUv, "page.uv", G::Pages, S::Mesh, &[]),
    spec(A::PageCloth, "page.cloth", G::Pages, S::Mesh, &[]),
    spec(A::PageJiggle, "page.jiggle", G::Pages, S::Mesh, &[]),
    spec(
        A::PageMorphRefit,
        "page.morph_refit",
        G::Pages,
        S::Mesh,
        &[],
    ),
    spec(
        A::TargetVertex,
        "selection.target.vertex",
        G::Selection,
        S::Mesh,
        &["1"],
    ),
    spec(
        A::TargetEdge,
        "selection.target.edge",
        G::Selection,
        S::Mesh,
        &["2"],
    ),
    spec(
        A::TargetFace,
        "selection.target.face",
        G::Selection,
        S::Mesh,
        &["3"],
    ),
    spec(
        A::ShapeClick,
        "selection.shape.click",
        G::Selection,
        S::Mesh,
        &[],
    ),
    spec(
        A::ShapeBrush,
        "selection.shape.brush",
        G::Selection,
        S::Mesh,
        &["C"],
    ),
    spec(
        A::ShapeRectangle,
        "selection.shape.rectangle",
        G::Selection,
        S::Mesh,
        &["B"],
    ),
    spec(
        A::ShapeLasso,
        "selection.shape.lasso",
        G::Selection,
        S::Mesh,
        &[],
    ),
    spec(
        A::OperationReplace,
        "selection.operation.replace",
        G::Selection,
        S::Mesh,
        &[],
    ),
    spec(
        A::OperationAdd,
        "selection.operation.add",
        G::Selection,
        S::Mesh,
        &[],
    ),
    spec(
        A::OperationSubtract,
        "selection.operation.subtract",
        G::Selection,
        S::Mesh,
        &[],
    ),
    spec(
        A::OperationToggle,
        "selection.operation.toggle",
        G::Selection,
        S::Mesh,
        &[],
    ),
    spec(
        A::SelectAll,
        "session.select_all",
        G::Selection,
        S::Global,
        &["A"],
    ),
    spec(
        A::ClearSelection,
        "session.clear_selection",
        G::Selection,
        S::Global,
        &["Alt+A"],
    ),
    spec(
        A::InvertSelection,
        "session.invert",
        G::Selection,
        S::Global,
        &["Ctrl+I"],
    ),
    spec(
        A::SelectLinked,
        "selection.linked",
        G::Selection,
        S::Mesh,
        &["L"],
    ),
    spec(
        A::GrowSelection,
        "selection.grow",
        G::Selection,
        S::Mesh,
        &["Ctrl+NumPlus"],
    ),
    spec(
        A::ShrinkSelection,
        "selection.shrink",
        G::Selection,
        S::Mesh,
        &["Ctrl+NumMinus"],
    ),
    spec(
        A::ToggleXRay,
        "selection.xray",
        G::Selection,
        S::Mesh,
        // Not Alt+Z: the AMD and NVIDIA overlays take it as a global hotkey.
        &["Shift+Z"],
    ),
    spec(
        A::ExtendModifier,
        "selection.extend_modifier",
        G::SelectionModifiers,
        S::Mesh,
        &["Shift"],
    ),
    spec(
        A::SubtractModifier,
        "selection.subtract_modifier",
        G::SelectionModifiers,
        S::Mesh,
        &["Ctrl"],
    ),
    spec(
        A::FrameSelected,
        "camera.frame_selected",
        G::View,
        S::Global,
        &["F", "NumDecimal"],
    ),
    spec(A::FrameAll, "camera.fit", G::View, S::Global, &["Home"]),
    spec(A::ViewFront, "camera.front", G::View, S::Global, &["Num1"]),
    spec(
        A::ViewBack,
        "camera.back",
        G::View,
        S::Global,
        &["Ctrl+Num1"],
    ),
    spec(A::ViewRight, "camera.right", G::View, S::Global, &["Num3"]),
    spec(
        A::ViewLeft,
        "camera.left",
        G::View,
        S::Global,
        &["Ctrl+Num3"],
    ),
    spec(A::ViewTop, "camera.top", G::View, S::Global, &["Num7"]),
    spec(
        A::ViewBottom,
        "camera.bottom",
        G::View,
        S::Global,
        &["Ctrl+Num7"],
    ),
    spec(
        A::YawMinus15,
        "camera.yaw_minus_15",
        G::View,
        S::Global,
        &[],
    ),
    spec(A::YawPlus15, "camera.yaw_plus_15", G::View, S::Global, &[]),
    spec(A::Undo, "session.undo", G::History, S::Global, &["Ctrl+Z"]),
    spec(
        A::Redo,
        "session.redo",
        G::History,
        S::Global,
        &["Ctrl+Shift+Z", "Ctrl+Y"],
    ),
    spec(
        A::DeleteSelection,
        "topology.delete_selection",
        G::Editing,
        S::Mesh,
        &["Delete"],
    ),
    spec(A::HairSelect, "hair.tool.select", G::Hair, S::Hair, &[]),
    spec(A::HairMove, "hair.tool.move", G::Hair, S::Hair, &[]),
    spec(A::HairDraw, "hair.tool.draw", G::Hair, S::Hair, &[]),
    spec(A::HairErase, "hair.tool.erase", G::Hair, S::Hair, &[]),
    spec(A::HairCut, "hair.tool.cut", G::Hair, S::Hair, &[]),
    spec(A::HairLengthen, "hair.tool.lengthen", G::Hair, S::Hair, &[]),
    spec(A::HairComb, "hair.tool.comb", G::Hair, S::Hair, &[]),
    spec(A::HairSmooth, "hair.tool.smooth", G::Hair, S::Hair, &[]),
    spec(A::HairCurl, "hair.tool.curl", G::Hair, S::Hair, &[]),
    spec(A::HairClump, "hair.tool.clump", G::Hair, S::Hair, &[]),
    spec(A::HairPhysics, "hair.tool.physics", G::Hair, S::Hair, &[]),
    spec(
        A::HairDeleteGuides,
        "hair.delete_guides",
        G::Hair,
        S::Hair,
        &["Delete"],
    ),
];

pub(crate) fn spec_for(action: ShortcutAction) -> &'static ShortcutSpec {
    SHORTCUTS
        .iter()
        .find(|spec| spec.action == action)
        .expect("every shortcut action has a spec")
}

fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= MAX_ID_LENGTH
        && id.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || b"_.+-".contains(&byte)
        })
}

fn default_bindings(spec: &ShortcutSpec) -> Vec<Binding> {
    spec.defaults
        .iter()
        .filter_map(|text| Binding::parse(text))
        .collect()
}

/// The Keyboard Shortcuts window and whether the host saves changes.
#[derive(Debug, Default)]
pub(crate) struct EditorState {
    pub(crate) open: bool,
    /// The action and slot waiting for a key press.
    pub(crate) capture: Option<(ShortcutAction, usize)>,
    pub(crate) filter: String,
    pub(crate) notice: Option<String>,
    pub(crate) persist: bool,
}

/// A rebinding that took a chord away from another action.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct MovedBinding {
    pub(crate) from: ShortcutAction,
    pub(crate) binding: Binding,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct Keymap {
    overrides: BTreeMap<ShortcutAction, Vec<Binding>>,
    /// Override entries this build cannot interpret, written back untouched.
    passthrough: Map<String, Value>,
}

impl Keymap {
    pub(crate) fn from_overrides(value: &Value) -> Self {
        let mut keymap = Self::default();
        let Some(entries) = value.as_object() else {
            return keymap;
        };
        for (id, chords) in entries.iter().take(MAX_OVERRIDES) {
            if !valid_id(id) {
                continue;
            }
            let Some(spec) = SHORTCUTS.iter().find(|spec| spec.id == id) else {
                keymap.passthrough.insert(id.clone(), chords.clone());
                continue;
            };
            let Some(chords) = chords
                .as_array()
                .filter(|chords| chords.len() <= MAX_CHORDS)
            else {
                continue;
            };
            let bindings = chords
                .iter()
                .filter_map(Value::as_str)
                .filter_map(Binding::parse)
                .filter(|binding| matches!(binding, Binding::Modifier(_)) == spec.takes_modifier())
                .collect::<Vec<_>>();
            if bindings.len() == chords.len() {
                keymap.overrides.insert(spec.action, bindings);
            }
        }
        keymap
    }

    pub(crate) fn overrides_value(&self) -> Value {
        let mut entries = self.passthrough.clone();
        for (action, bindings) in &self.overrides {
            entries.insert(
                spec_for(*action).id.to_owned(),
                Value::Array(
                    bindings
                        .iter()
                        .map(|binding| Value::String(binding.text()))
                        .collect(),
                ),
            );
        }
        Value::Object(entries)
    }

    pub(crate) fn bindings(&self, action: ShortcutAction) -> Vec<Binding> {
        self.overrides
            .get(&action)
            .cloned()
            .unwrap_or_else(|| default_bindings(spec_for(action)))
    }

    pub(crate) fn is_default(&self, action: ShortcutAction) -> bool {
        self.bindings(action) == default_bindings(spec_for(action))
    }

    /// The primary binding as shown after a control's name, for example `G`.
    pub(crate) fn hint(&self, action: ShortcutAction) -> Option<String> {
        self.bindings(action).first().map(|binding| binding.text())
    }

    pub(crate) fn modifier(&self, action: ShortcutAction) -> Option<ModifierKey> {
        self.bindings(action)
            .into_iter()
            .find_map(|binding| match binding {
                Binding::Modifier(modifier) => Some(modifier),
                Binding::Chord(_) => None,
            })
    }

    /// The command a chord triggers in the given editor scope.
    pub(crate) fn action_for(
        &self,
        chord: KeyChord,
        scope: ShortcutScope,
    ) -> Option<ShortcutAction> {
        SHORTCUTS
            .iter()
            .filter(|spec| spec.scope.overlaps(scope) && !spec.takes_modifier())
            .find(|spec| self.bindings(spec.action).contains(&Binding::Chord(chord)))
            .map(|spec| spec.action)
    }

    /// Another action in an overlapping scope that already uses this binding.
    pub(crate) fn conflict(
        &self,
        action: ShortcutAction,
        binding: Binding,
    ) -> Option<ShortcutAction> {
        let scope = spec_for(action).scope;
        SHORTCUTS
            .iter()
            .filter(|spec| spec.action != action && spec.scope.overlaps(scope))
            .filter(|spec| spec.takes_modifier() == spec_for(action).takes_modifier())
            .find(|spec| self.bindings(spec.action).contains(&binding))
            .map(|spec| spec.action)
    }

    /// Sets one slot of an action, moving the binding away from any action it conflicts with.
    pub(crate) fn assign(
        &mut self,
        action: ShortcutAction,
        slot: usize,
        binding: Binding,
    ) -> Option<MovedBinding> {
        let moved = self.conflict(action, binding).map(|from| {
            let mut remaining = self.bindings(from);
            remaining.retain(|candidate| *candidate != binding);
            self.set(from, remaining);
            MovedBinding { from, binding }
        });
        let mut bindings = self.bindings(action);
        bindings.retain(|candidate| *candidate != binding);
        if slot < bindings.len() {
            bindings[slot] = binding;
        } else {
            bindings.push(binding);
        }
        bindings.truncate(MAX_CHORDS);
        self.set(action, bindings);
        moved
    }

    pub(crate) fn clear_slot(&mut self, action: ShortcutAction, slot: usize) {
        let mut bindings = self.bindings(action);
        if slot < bindings.len() {
            bindings.remove(slot);
        }
        self.set(action, bindings);
    }

    pub(crate) fn reset(&mut self, action: ShortcutAction) {
        self.overrides.remove(&action);
    }

    pub(crate) fn reset_all(&mut self) {
        self.overrides.clear();
    }

    fn set(&mut self, action: ShortcutAction, bindings: Vec<Binding>) {
        if bindings == default_bindings(spec_for(action)) {
            self.overrides.remove(&action);
        } else {
            self.overrides.insert(action, bindings);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn chord(text: &str) -> KeyChord {
        match Binding::parse(text) {
            Some(Binding::Chord(chord)) => chord,
            other => panic!("{text} parsed as {other:?}"),
        }
    }

    #[test]
    fn every_default_parses_and_round_trips() {
        for spec in SHORTCUTS {
            assert!(valid_id(spec.id), "{}", spec.id);
            for text in spec.defaults {
                let binding = Binding::parse(text).unwrap_or_else(|| panic!("{} {text}", spec.id));
                assert_eq!(binding.text(), *text, "{}", spec.id);
                assert_eq!(
                    matches!(binding, Binding::Modifier(_)),
                    spec.takes_modifier(),
                    "{}",
                    spec.id
                );
            }
            assert!(spec.defaults.len() <= MAX_CHORDS, "{}", spec.id);
        }
        let mut ids = SHORTCUTS.iter().map(|spec| spec.id).collect::<Vec<_>>();
        ids.sort_unstable();
        ids.dedup();
        assert_eq!(ids.len(), SHORTCUTS.len(), "shortcut IDs are unique");
    }

    #[test]
    fn defaults_never_share_a_chord_within_overlapping_scopes() {
        let keymap = Keymap::default();
        for spec in SHORTCUTS {
            for binding in keymap.bindings(spec.action) {
                assert_eq!(
                    keymap.conflict(spec.action, binding),
                    None,
                    "{} {}",
                    spec.id,
                    binding.text()
                );
            }
        }
    }

    #[test]
    fn numpad_digits_are_distinct_from_top_row_digits() {
        let top = chord("1");
        let numpad = chord("Num1");
        assert_ne!(top, numpad);
        assert_eq!(numpad.key, ShortcutKey::Numpad(NumpadKey::Digit(1)));
        assert_eq!(top.key, ShortcutKey::Key(egui::Key::Num1));
        let keymap = Keymap::default();
        assert_eq!(
            keymap.action_for(top, ShortcutScope::Mesh),
            Some(ShortcutAction::TargetVertex)
        );
        assert_eq!(
            keymap.action_for(numpad, ShortcutScope::Mesh),
            Some(ShortcutAction::ViewFront)
        );
        assert_eq!(
            Binding::parse("Numpad1"),
            None,
            "egui's own numpad spelling is not ambiguous"
        );
        assert_eq!(
            NumpadKey::from_key_code(winit::keyboard::KeyCode::Numpad7),
            Some(NumpadKey::Digit(7))
        );
        assert_eq!(
            NumpadKey::from_key_code(winit::keyboard::KeyCode::Digit7),
            None
        );
    }

    #[test]
    fn modifiers_parse_in_any_order_and_print_canonically() {
        assert_eq!(chord("Shift+Ctrl+Z").text(), "Ctrl+Shift+Z");
        assert_eq!(Binding::parse("Ctrl+Ctrl+Z"), None);
        assert_eq!(Binding::parse("Super+Z"), None);
        assert_eq!(Binding::parse(""), None);
        assert_eq!(
            Binding::parse("Shift"),
            Some(Binding::Modifier(ModifierKey::Shift))
        );
        assert_eq!(
            chord("Ctrl+NumPlus").key,
            ShortcutKey::Numpad(NumpadKey::Plus)
        );
    }

    #[test]
    fn overrides_unbind_replace_and_keep_unknown_ids() {
        let keymap = Keymap::from_overrides(&json!({
            "tool.move": [],
            "tool.rotate": ["Ctrl+R"],
            "future.tool": ["K"],
            "selection.extend_modifier": ["Alt"],
            "selection.subtract_modifier": ["Ctrl+X"],
            "camera.fit": ["Bogus"],
            "Bad ID": ["K"],
        }));
        assert!(keymap.bindings(ShortcutAction::ToolMove).is_empty());
        assert_eq!(
            keymap.hint(ShortcutAction::ToolRotate).as_deref(),
            Some("Ctrl+R")
        );
        assert_eq!(
            keymap.modifier(ShortcutAction::ExtendModifier),
            Some(ModifierKey::Alt)
        );
        assert_eq!(
            keymap.modifier(ShortcutAction::SubtractModifier),
            Some(ModifierKey::Ctrl)
        );
        assert_eq!(
            keymap.hint(ShortcutAction::FrameAll).as_deref(),
            Some("Home")
        );
        let saved = keymap.overrides_value();
        assert_eq!(saved["future.tool"], json!(["K"]));
        assert_eq!(saved["tool.move"], json!([]));
        assert!(saved.get("Bad ID").is_none());
        assert!(saved.get("camera.fit").is_none());
        assert_eq!(Keymap::from_overrides(&saved), keymap);
    }

    #[test]
    fn assigning_a_used_chord_moves_it_and_reset_restores_defaults() {
        let mut keymap = Keymap::default();
        let g = Binding::parse("G").expect("G");
        let moved = keymap.assign(ShortcutAction::ToolScale, 0, g);
        assert_eq!(
            moved,
            Some(MovedBinding {
                from: ShortcutAction::ToolMove,
                binding: g
            })
        );
        assert!(keymap.bindings(ShortcutAction::ToolMove).is_empty());
        assert_eq!(
            keymap.action_for(chord("G"), ShortcutScope::Mesh),
            Some(ShortcutAction::ToolScale)
        );
        // Mesh and hair tools are never live together, so they may share a key.
        assert_eq!(keymap.assign(ShortcutAction::HairDraw, 0, g), None);
        keymap.reset_all();
        assert_eq!(keymap, Keymap::default());
        keymap.assign(
            ShortcutAction::Redo,
            1,
            Binding::parse("Ctrl+R").expect("chord"),
        );
        assert_eq!(
            keymap.hint(ShortcutAction::Redo).as_deref(),
            Some("Ctrl+Shift+Z")
        );
        keymap.clear_slot(ShortcutAction::Redo, 1);
        keymap.reset(ShortcutAction::Redo);
        assert!(keymap.is_default(ShortcutAction::Redo));
    }

    #[test]
    fn global_shortcuts_reach_both_editors() {
        let keymap = Keymap::default();
        assert_eq!(
            keymap.action_for(chord("Ctrl+Z"), ShortcutScope::Hair),
            Some(ShortcutAction::Undo)
        );
        assert_eq!(
            keymap.action_for(chord("Delete"), ShortcutScope::Hair),
            Some(ShortcutAction::HairDeleteGuides)
        );
        assert_eq!(
            keymap.action_for(chord("Delete"), ShortcutScope::Mesh),
            Some(ShortcutAction::DeleteSelection)
        );
        assert_eq!(keymap.action_for(chord("G"), ShortcutScope::Hair), None);
    }

    #[test]
    fn reserved_chords_explain_why() {
        assert!(chord("Escape").reserved_reason().is_some());
        assert!(chord("Alt+F4").reserved_reason().is_some());
        assert!(chord("Ctrl+C").reserved_reason().is_some());
        assert!(chord("Ctrl+Z").reserved_reason().is_none());
    }
}
