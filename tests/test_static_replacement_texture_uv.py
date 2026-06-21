from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_texture_uv import (
    current_texture_uv_transforms,
    ensure_texture_uv_transform_state,
    global_flip_v_fast_preview_value,
    record_texture_uv_global_transform_state,
    record_texture_uv_transform_state,
    reset_texture_uv_transform_state,
    texture_transform_controls_loading_initial_state,
    texture_transform_controls_set_loading,
    texture_uv_control_text,
    texture_uv_fast_preview_initial_state,
    texture_uv_fast_preview_record_global_flip_v,
    texture_uv_global_transform_control_state,
    texture_uv_global_transform_initial_state,
    texture_uv_material_names,
    texture_uv_transform_control_load_state,
    texture_uv_transform_control_save_state,
    texture_uv_transform_control_state,
    texture_uv_transform_control_values,
    texture_uv_transform_materials_state,
    texture_uv_transform_payload,
    texture_uv_transform_reset_state,
)


def _state_has_edits(state: dict[str, object]) -> bool:
    return any(
        (
            int(state.get("rotate_degrees") or 0) != 0,
            bool(state.get("flip_u")),
            bool(state.get("flip_v")),
            abs(float(state.get("offset_u") or 0.0)) > 1e-8,
            abs(float(state.get("offset_v") or 0.0)) > 1e-8,
            abs(float(state.get("scale_u") or 1.0) - 1.0) > 1e-8,
            abs(float(state.get("scale_v") or 1.0) - 1.0) > 1e-8,
        )
    )


def _key(value: str) -> str:
    return value.strip().lower()


def test_texture_transform_controls_loading_initial_state_preserves_defaults() -> None:
    assert texture_transform_controls_loading_initial_state() == {"active": False, "key": ""}


def test_texture_transform_controls_set_loading_updates_key_only_when_requested() -> None:
    state = texture_transform_controls_loading_initial_state()

    assert texture_transform_controls_set_loading(state, active=True, key="body") == {"active": True, "key": "body"}
    assert state == {"active": True, "key": "body"}
    assert texture_transform_controls_set_loading(state, active=False) == {"active": False, "key": "body"}


def test_texture_uv_control_text_preserves_panel_and_setup_guidance() -> None:
    text = texture_uv_control_text()

    assert text["transform_group"] == "Texture Orientation / UV Transform"
    assert text["note"] == "UV transform for the selected source material."
    assert text["help"] == (
        "Adjust the selected source material's UVs without rotating the model. "
        "The correction applies to base, normal, mask, and height maps together in preview and export."
    )
    assert text["material_label"] == "Material"
    assert text["rotate_label"] == "Rotate"
    assert text["flip_u_label"] == "Flip U"
    assert text["flip_v_label"] == "Flip V"
    assert text["offset_u_label"] == "Offset U"
    assert text["offset_v_label"] == "Offset V"
    assert text["scale_u_label"] == "Scale U"
    assert text["scale_v_label"] == "Scale V"
    assert text["reset_button"] == "Reset UV"
    assert text["material_tooltip"] == "Choose the replacement source material whose UVs should be corrected."
    assert text["rotate_tooltip"] == "Rotate UVs around the 0.5/0.5 texture center."
    assert text["flip_u_tooltip"] == "Mirror the selected material horizontally in UV space."
    assert text["flip_v_tooltip"] == "Mirror the selected material vertically in UV space."
    assert text["offset_u_tooltip"] == "Move UVs horizontally after flip/rotation."
    assert text["offset_v_tooltip"] == "Move UVs vertically after flip/rotation."
    assert text["scale_u_tooltip"] == "Scale U around the 0.5/0.5 texture center."
    assert text["scale_v_tooltip"] == "Scale V around the 0.5/0.5 texture center."
    assert text["reset_tooltip"] == "Reset UV orientation for the selected source material."
    assert text["setup_rotate_tooltip"] == (
        "Default UV rotation for replacement source materials. "
        "Per-material settings in Materials & Textures override this."
    )
    assert text["setup_flip_u_tooltip"] == "Default horizontal UV mirror for replacement textures."
    assert text["setup_flip_v_tooltip"] == (
        "Default vertical UV mirror for replacement textures. "
        "Use this when imported textures appear upside down."
    )
    assert text["setup_output_size_tooltip"] == (
        "Choose the dimensions for generated DDS textures. Source image size preserves imported 4K textures; "
        "Original DDS size keeps the old template dimensions."
    )
    assert text["setup_reset_button"] == "Reset"
    assert text["setup_reset_tooltip"] == "Reset global texture orientation defaults."


def test_current_texture_uv_transforms_apply_global_then_material_override() -> None:
    texture_sets = {
        "body": SimpleNamespace(material_name="Body"),
        "cape": SimpleNamespace(material_name="Cape"),
    }
    global_state = {
        "rotate_degrees": 90,
        "flip_u": True,
        "flip_v": False,
        "offset_u": 0.25,
        "offset_v": 0.0,
        "scale_u": 1.0,
        "scale_v": 1.0,
    }
    per_material = {
        "cape": {
            "source_material_name": "Cape",
            "rotate_degrees": 180,
            "flip_u": False,
            "flip_v": True,
            "offset_u": 0.0,
            "offset_v": 0.125,
            "scale_u": 2.0,
            "scale_v": 1.0,
        },
        "unused": {
            "source_material_name": "Unused",
            "rotate_degrees": 0,
            "flip_u": False,
            "flip_v": False,
            "offset_u": 0.0,
            "offset_v": 0.0,
            "scale_u": 1.0,
            "scale_v": 1.0,
        },
    }

    transforms = current_texture_uv_transforms(
        texture_sets,
        per_material,
        global_state,
        state_has_edits=_state_has_edits,
        transform_key=_key,
    )

    assert [(transform.source_material_name, transform.rotate_degrees) for transform in transforms] == [
        ("Body", 90),
        ("Cape", 180),
    ]
    assert transforms[0].flip_u is True
    assert transforms[1].flip_v is True
    assert transforms[1].scale_uv == (2.0, 1.0)


def test_texture_uv_transform_payload_rounds_and_sorts() -> None:
    transforms = current_texture_uv_transforms(
        {"cape": SimpleNamespace(material_name="Cape")},
        {
            "cape": {
                "source_material_name": "Cape",
                "rotate_degrees": 0,
                "flip_u": False,
                "flip_v": False,
                "offset_u": 0.1234567,
                "offset_v": 0,
                "scale_u": 1,
                "scale_v": 0.9876543,
            }
        },
        {},
        state_has_edits=_state_has_edits,
        transform_key=_key,
    )

    assert texture_uv_transform_payload(transforms) == [
        ("Cape", 0, False, False, 0.123457, 0.0, 1.0, 0.987654),
    ]


def test_texture_uv_transform_state_helpers_ensure_record_and_reset() -> None:
    transform_state: dict[str, object] = {}
    default_state = {
        "source_material_name": "body",
        "rotate_degrees": 0,
        "flip_u": False,
        "flip_v": False,
        "offset_u": 0.0,
        "offset_v": 0.0,
        "scale_u": 1.0,
        "scale_v": 1.0,
    }

    state = ensure_texture_uv_transform_state(transform_state, "body", default_state)

    assert state == default_state
    assert transform_state["body"] == default_state
    assert record_texture_uv_transform_state(transform_state, "body", default_state) is False

    updated_state = {**default_state, "flip_v": True}

    assert record_texture_uv_transform_state(transform_state, "body", updated_state) is True
    assert transform_state["body"] == updated_state

    reset_texture_uv_transform_state(transform_state, "body", default_state)

    assert transform_state["body"] == default_state


def test_texture_uv_global_transform_state_helpers_record_defaults_and_controls() -> None:
    state = texture_uv_global_transform_initial_state()

    assert state == {
        "source_material_name": "__global__",
        "rotate_degrees": 0,
        "flip_u": False,
        "flip_v": False,
        "offset_u": 0.0,
        "offset_v": 0.0,
        "scale_u": 1.0,
        "scale_v": 1.0,
    }

    record_texture_uv_global_transform_state(
        state,
        texture_uv_global_transform_control_state(
            rotate_degrees=180,
            flip_u=True,
            flip_v=False,
        ),
    )

    assert state["rotate_degrees"] == 180
    assert state["flip_u"] is True
    assert state["source_material_name"] == "__global__"


def test_texture_uv_transform_control_helpers_normalize_widget_values() -> None:
    state = texture_uv_transform_control_state(
        " Body ",
        rotate_degrees=450,
        flip_u=1,
        flip_v="",
        offset_u="0.25",
        offset_v=None,
        scale_u="2",
        scale_v=None,
    )

    assert state == {
        "source_material_name": "Body",
        "rotate_degrees": 450,
        "flip_u": True,
        "flip_v": False,
        "offset_u": 0.25,
        "offset_v": 0.0,
        "scale_u": 2.0,
        "scale_v": 1.0,
    }
    assert texture_uv_transform_control_values(state) == {
        "rotate_degrees": 90,
        "flip_u": True,
        "flip_v": False,
        "offset_u": 0.25,
        "offset_v": 0.0,
        "scale_u": 2.0,
        "scale_v": 1.0,
    }


def test_texture_uv_transform_control_load_save_and_reset_state() -> None:
    transform_state: dict[str, object] = {}
    default_state = texture_uv_transform_control_state(
        "Body",
        rotate_degrees=0,
        flip_u=False,
        flip_v=False,
        offset_u=0,
        offset_v=0,
        scale_u=1,
        scale_v=1,
    )
    loading_state = texture_transform_controls_loading_initial_state()

    load_state = texture_uv_transform_control_load_state(
        transform_state,
        " Body ",
        default_state,
        transform_key=_key,
    )

    assert load_state["key"] == "body"
    assert load_state["material_name"] == "Body"
    assert load_state["values"] == texture_uv_transform_control_values(default_state)
    assert transform_state["body"] == default_state

    texture_transform_controls_set_loading(loading_state, active=False, key="body")
    save_state = texture_uv_transform_control_save_state(
        transform_state,
        loading_state,
        material_name="Body",
        rotate_degrees=90,
        flip_u=True,
        flip_v=False,
        offset_u=0.25,
        offset_v=0,
        scale_u=1,
        scale_v=1,
        queue_preview=True,
    )

    assert save_state == {"saved": True, "queue_preview": True, "mark_dirty": False}
    assert transform_state["body"]["rotate_degrees"] == 90  # type: ignore[index]
    assert transform_state["body"]["flip_u"] is True  # type: ignore[index]

    assert texture_uv_transform_control_save_state(
        transform_state,
        {**loading_state, "active": True},
        material_name="Body",
        rotate_degrees=180,
        flip_u=False,
        flip_v=False,
        offset_u=0,
        offset_v=0,
        scale_u=1,
        scale_v=1,
        queue_preview=True,
    ) == {"saved": False, "queue_preview": False, "mark_dirty": False}

    dirty_state = texture_uv_transform_control_save_state(
        transform_state,
        loading_state,
        material_name="Body",
        rotate_degrees=180,
        flip_u=False,
        flip_v=False,
        offset_u=0,
        offset_v=0,
        scale_u=1,
        scale_v=1,
        queue_preview=False,
    )
    assert dirty_state == {"saved": True, "queue_preview": False, "mark_dirty": True}

    reset_state = texture_uv_transform_reset_state(
        transform_state,
        "Body",
        default_state,
        transform_key=_key,
    )
    assert reset_state == {"reset": True, "key": "body", "material_name": "Body"}
    assert transform_state["body"] == default_state
    assert texture_uv_transform_reset_state(transform_state, "", default_state, transform_key=_key) == {
        "reset": False,
        "key": "",
        "material_name": "",
    }


def test_texture_uv_transform_materials_state_builds_choices_and_preserves_selection() -> None:
    transform_state: dict[str, object] = {}
    texture_sets = {
        "body": SimpleNamespace(material_name="Body"),
        "cape": SimpleNamespace(material_name="Cape"),
    }

    sync_state = texture_uv_transform_materials_state(
        texture_sets,
        transform_state,
        "cape",
        transform_key=_key,
        default_state_for_material=lambda material_name: texture_uv_transform_control_state(
            material_name,
            rotate_degrees=0,
            flip_u=False,
            flip_v=False,
            offset_u=0,
            offset_v=0,
            scale_u=1,
            scale_v=1,
        ),
    )

    assert sync_state == {
        "choices": (("Body", "body"), ("Cape", "cape")),
        "selected_key": "cape",
        "has_materials": True,
    }
    assert tuple(transform_state) == ("body", "cape")

    fallback_state = texture_uv_transform_materials_state(
        texture_sets,
        transform_state,
        "missing",
        transform_key=_key,
        default_state_for_material=lambda material_name: texture_uv_transform_control_state(
            material_name,
            rotate_degrees=0,
            flip_u=False,
            flip_v=False,
            offset_u=0,
            offset_v=0,
            scale_u=1,
            scale_v=1,
        ),
    )
    assert fallback_state["selected_key"] == "body"
    assert texture_uv_transform_materials_state(
        {},
        transform_state,
        "body",
        transform_key=_key,
        default_state_for_material=lambda material_name: {},
    ) == {"choices": (), "selected_key": "", "has_materials": False}


def test_texture_uv_material_names_keeps_nonempty_names_in_order() -> None:
    texture_sets = {
        "body": SimpleNamespace(material_name=" Body "),
        "blank": SimpleNamespace(material_name=" "),
        "cape": SimpleNamespace(material_name="Cape"),
    }

    assert texture_uv_material_names(texture_sets) == ("Body", "Cape")


def test_global_flip_v_fast_preview_value_accepts_only_simple_global_flip() -> None:
    global_state = {
        "rotate_degrees": 0,
        "flip_u": False,
        "flip_v": True,
        "offset_u": 0.0,
        "offset_v": 0.0,
        "scale_u": 1.0,
        "scale_v": 1.0,
    }

    assert (
        global_flip_v_fast_preview_value(
            d3d11_preview_active=True,
            texture_uv_transform_state={},
            texture_uv_global_transform_state=global_state,
            state_has_edits=_state_has_edits,
        )
        is True
    )
    assert (
        global_flip_v_fast_preview_value(
            d3d11_preview_active=False,
            texture_uv_transform_state={},
            texture_uv_global_transform_state=global_state,
            state_has_edits=_state_has_edits,
        )
        is None
    )
    assert (
        global_flip_v_fast_preview_value(
            d3d11_preview_active=True,
            texture_uv_transform_state={"body": {"flip_u": True}},
            texture_uv_global_transform_state=global_state,
            state_has_edits=_state_has_edits,
        )
        is None
    )


def test_global_flip_v_fast_preview_value_rejects_non_flip_v_global_edits() -> None:
    assert (
        global_flip_v_fast_preview_value(
            d3d11_preview_active=True,
            texture_uv_transform_state={},
            texture_uv_global_transform_state={"rotate_degrees": 90, "flip_v": True},
            state_has_edits=_state_has_edits,
        )
        is None
    )

    assert (
        global_flip_v_fast_preview_value(
            d3d11_preview_active=True,
            texture_uv_transform_state={},
            texture_uv_global_transform_state={"offset_u": 0.1, "flip_v": True},
            state_has_edits=_state_has_edits,
        )
        is None
    )
    assert (
        global_flip_v_fast_preview_value(
            d3d11_preview_active=True,
            texture_uv_transform_state={},
            texture_uv_global_transform_state={"scale_v": 0.5, "flip_v": True},
            state_has_edits=_state_has_edits,
        )
        is None
    )


def test_texture_uv_fast_preview_state_records_global_flip_v() -> None:
    state = texture_uv_fast_preview_initial_state()

    assert state == {"global_flip_v": False}
    assert texture_uv_fast_preview_record_global_flip_v(state, True) is True
    assert state == {"global_flip_v": True}
    assert texture_uv_fast_preview_record_global_flip_v(state, False) is False
    assert state == {"global_flip_v": False}
