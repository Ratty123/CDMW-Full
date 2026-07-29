import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"
LOCALIZATION_RESOURCES = ROOT / "cdmw" / "resources" / "localization"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


def _helper_localization_keys() -> list[str]:
    source = _source("ExperimentForm.UiLocalization.cs")
    body = source.split(
        "private static readonly string[] KeyManifest =", maxsplit=1
    )[1].split("};", maxsplit=1)[0]
    return [
        json.loads(match.group(0))
        for match in re.finditer(r'"(?:\\.|[^"\\])*"', body)
    ]


def test_helper_localization_manifest_matches_the_generated_csharp_catalogue() -> None:
    manifest = json.loads(
        (LOCALIZATION_RESOURCES / "source_manifest.json").read_text(encoding="utf-8")
    )
    generated = sorted(
        {
            entry["key"]
            for entry in manifest["entries"]
            if any(
                origin["path"].replace("\\", "/").startswith(
                    "tools/dotnet_mesh_editor_experiment/"
                )
                for origin in entry["origins"]
            )
        }
    )
    helper = _helper_localization_keys()

    assert helper == sorted(set(helper))
    assert helper == generated
    for path in sorted(LOCALIZATION_RESOURCES.glob("*.json")):
        if path.name == "source_manifest.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "translations" not in payload:
            continue
        catalogue = payload["translations"]
        assert set(helper) <= set(catalogue), path.name


def test_helper_negotiates_and_acknowledges_exact_localization_correlation() -> None:
    provenance = _source("HelperBuildProvenance.cs")
    protocol = _source("ExperimentForm.Protocol.cs")
    localization = _source("ExperimentForm.UiLocalization.cs")

    assert '"ui_localization_v1"' in provenance
    assert '["localization_keys"] = UiLocalizationOwner.LocalizationKeys' in protocol
    assert (
        '["localization_key_manifest_hash"] = '
        "UiLocalizationOwner.LocalizationKeyManifestHash"
    ) in protocol
    assert 'case "ui_localization_state":' in protocol
    assert "HandleUiLocalizationState(root);" in protocol
    assert 'WriteProtocolEvent("ui_localization_state_ack", acknowledgement);' in localization
    for field in (
        "language_code",
        "plural_rule",
        "catalog_hash",
        "key_manifest_hash",
        "session_id",
        "process_generation",
        "request_id",
        "localization_revision",
    ):
        assert f'["{field}"]' in localization
    assert 'status = "applied";' in localization
    assert 'status = "stale";' in localization
    assert "revision < _revision" in localization
    assert "key_manifest_hash_mismatch" in localization
    assert "catalog_hash_mismatch" in localization
    assert "translation_placeholders_mismatch" in localization
    assert "helper_translation_keys_are_incomplete" in localization
    assert "plural_translation_is_incomplete" in localization
    assert "MaximumProtocolLineBytes = 256 * 1024" in localization
    assert "Encoding.UTF8.GetByteCount(root.GetRawText())" in localization
    assert "JavaScriptEncoder.UnsafeRelaxedJsonEscaping" in localization


def test_helper_localizer_preserves_control_identity_and_captures_dynamic_sources() -> None:
    localization = _source("ExperimentForm.UiLocalization.cs")

    assert "listControl.Format += FormatListItem;" in localization
    assert ".Items.Clear()" not in localization
    assert ".Items.Add(" not in localization
    assert "control.TextChanged += " in localization
    assert "item.TextChanged += " in localization
    assert "control.ControlAdded += " in localization
    assert "_toolTip.GetToolTip(control)" in localization
    assert "control.AccessibleName" in localization
    assert "control.AccessibleDescription" in localization
    assert "ApplyOpenForms(onlyNew: true)" in localization
    assert "_knownForms.Contains(form)" in localization
    assert "_knownForms.Add(form)" in localization
    assert "control.Refresh()" not in localization
    assert "ShouldTranslateControlText(control)" in localization
    assert "TextBoxBase textBox => textBox.ReadOnly" in localization
    assert "item is not ToolStripTextBox and not ToolStripComboBox" in localization
    assert "TranslateRendered(argument.Value)" in localization
    assert "Microsoft YaHei UI" in localization
    assert "Microsoft JhengHei UI" in localization
    assert "Yu Gothic UI" in localization
    assert "Malgun Gothic" in localization
    assert "form.SuspendLayout();" in localization
    assert "form.ResumeLayout(performLayout: true);" in localization


def test_helper_plural_and_catalog_hash_contract_smoke_is_registered() -> None:
    program = _source("ProgramEntry.cs")
    smoke = _source("UiLocalizationContractSmoke.cs")
    localization = _source("ExperimentForm.UiLocalization.cs")
    protocol = _source("ExperimentForm.Protocol.cs")

    assert "UiLocalizationContractSmoke.IsRequested(args)" in program
    assert '"--headless-ui-localization-contract"' in program
    assert "SelectPluralCategory" in localization
    for rule in (
        "one_other",
        "spanish_million",
        "italian_million",
        "zero_one_million",
        "polish",
        "russian",
        "other",
    ):
        assert f'"{rule}"' in smoke
    for locale in ("ja", "ko", "zh-Hans", "zh-Hant"):
        assert f'"{locale}"' in smoke
    assert "CatalogHashFromJson" in smoke
    assert "LocalizePresentationArgument" in smoke
    assert "presentation_format_ok" in smoke
    assert "FormattableString.Invariant" in protocol
    assert "CultureInfo.GetCultureInfo(\"sv-SE\")" in smoke
    assert "invariant_metrics_source_ok" in smoke
    assert "ResolveCjkFallbackFontFamily" in smoke
    assert "cjk_font_fallbacks_ok" in smoke
    assert "renderer_started = false" in smoke
    assert "visible_window_started = false" in smoke
