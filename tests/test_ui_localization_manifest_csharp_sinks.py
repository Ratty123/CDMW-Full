from scripts.generate_ui_localization_manifest import _csharp_sink_regions


def test_csharp_text_equality_is_not_a_ui_assignment_sink() -> None:
    assert _csharp_sink_regions('Require(label.Text == "Ready", "failure");') == ()


def test_csharp_text_assignment_remains_a_ui_sink() -> None:
    regions = _csharp_sink_regions('label.Text = "Ready";')

    assert len(regions) == 1
    assert regions[0][2] == ".Text="
